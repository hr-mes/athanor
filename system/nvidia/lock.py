#!/usr/bin/env python3
"""Locks for the third-party NVIDIA driver packages of the system image variants
(docs/architecture/doc_system_image.md, S4, S5 and S7).

  lock.py generate open|legacy --version V   resolve the branch's packages at exactly V in its
                                             repository and write locks/<branch>.lock with the
                                             SHA-256 of each downloaded RPM
  lock.py fetch open|legacy --out DIR        download the locked RPMs and verify each SHA-256;
                                             prints the lock's version
  lock.py check open|legacy --version V      exit 0 if the repository publishes the branch at V

GPG signatures are verified by build-rpms.sh with rpmkeys and the keys in keys/: the lock
covers what the unsigned repository metadata of negativo17 cannot.
"""

import argparse
import gzip
import hashlib
import pathlib
import sys
import urllib.request
import xml.etree.ElementTree as ET

HERE = pathlib.Path(__file__).resolve().parent
LOCKS = HERE / "locks"
COMMON = "{http://linux.duke.edu/metadata/common}"
REPO = "{http://linux.duke.edu/metadata/repo}"
ARCHES = ("x86_64", "noarch")
BRANCHES = {
    "open": {
        "baseurl": "https://negativo17.org/repos/nvidia/fedora-43/x86_64/",
        "packages": [
            "nvidia-driver", "nvidia-driver-common", "nvidia-driver-cuda", "nvidia-driver-cuda-libs",
            "nvidia-driver-libs", "nvidia-kmod-common", "nvidia-modprobe", "nvidia-persistenced",
        ],
    },
    "legacy": {
        "baseurl": "https://download1.rpmfusion.org/nonfree/fedora/updates/43/x86_64/",
        "packages": [
            "nvidia-modprobe", "nvidia-persistenced", "nvidia-settings", "xorg-x11-drv-nvidia",
            "xorg-x11-drv-nvidia-cuda", "xorg-x11-drv-nvidia-cuda-libs", "xorg-x11-drv-nvidia-libs",
        ],
    },
}


class LockError(Exception):
    """A lock that cannot be produced or honoured; the message names the package or file."""


def http_get(url):
    with urllib.request.urlopen(url, timeout=120) as response:
        return response.read()


def parse_xml(data):
    """Repository metadata comes from the network: refuse any DTD, so no entity can expand
    or resolve (the standard library parser has no switch for it and defusedxml is not in
    the build stage)."""
    if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
        raise LockError("repository metadata declares a DTD or entities: refused")
    return ET.fromstring(data)


def primary_href(repomd):
    for data in parse_xml(repomd).iter(f"{REPO}data"):
        if data.get("type") == "primary":
            return data.find(f"{REPO}location").get("href")
    raise LockError("repomd.xml has no primary metadata")


def select(primary_xml, names, version):
    """One entry per name at exactly `version`, for x86_64 or noarch."""
    found = {name: [] for name in names}
    for pkg in parse_xml(primary_xml).iter(f"{COMMON}package"):
        name = pkg.findtext(f"{COMMON}name")
        ver = pkg.find(f"{COMMON}version")
        if name in found and ver.get("ver") == version and pkg.findtext(f"{COMMON}arch") in ARCHES:
            found[name].append({
                "name": name,
                "href": pkg.find(f"{COMMON}location").get("href"),
                "sha256": pkg.findtext(f"{COMMON}checksum"),
            })
    missing = sorted(n for n, entries in found.items() if not entries)
    if missing:
        raise LockError(f"not published at {version}: {', '.join(missing)}")
    ambiguous = sorted(n for n, entries in found.items() if len(entries) > 1)
    if ambiguous:
        raise LockError(f"ambiguous at {version} (several releases or arches): {', '.join(ambiguous)}")
    return [found[n][0] for n in sorted(names)]


def write_lock(path, branch, version, baseurl, entries):
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# branch {branch}", f"# version {version}", f"# repository {baseurl}"]
    lines += [f"{sha}  {url}" for sha, url in sorted(entries, key=lambda e: e[1])]
    path.write_text("\n".join(lines) + "\n")


def read_lock(path):
    version = baseurl = None
    entries = []
    for line in path.read_text().splitlines():
        if line.startswith("# version "):
            version = line.split(" ", 2)[2]
        elif line.startswith("# repository "):
            baseurl = line.split(" ", 2)[2]
        elif line and not line.startswith("#"):
            sha, url = line.split("  ", 1)
            entries.append((sha, url))
    if not version or not baseurl or not entries:
        raise LockError(f"{path}: incomplete lock")
    return version, baseurl, entries


def resolve(branch, version, download):
    base = BRANCHES[branch]["baseurl"]
    href = primary_href(download(base + "repodata/repomd.xml"))
    return select(gzip.decompress(download(base + href)), BRANCHES[branch]["packages"], version)


def main(argv=None, download=http_get):
    parser = argparse.ArgumentParser(description="Locks for the third-party NVIDIA RPMs.")
    parser.add_argument("command", choices=("generate", "fetch", "check"))
    parser.add_argument("branch", choices=sorted(BRANCHES))
    parser.add_argument("--version")
    parser.add_argument("--out", type=pathlib.Path)
    parser.add_argument("--locks", type=pathlib.Path, default=LOCKS)
    args = parser.parse_args(argv)
    try:
        if args.command in ("generate", "check") and not args.version:
            raise LockError(f"{args.command} needs --version")
        if args.command == "check":
            resolve(args.branch, args.version, download)
            return 0
        if args.command == "generate":
            base = BRANCHES[args.branch]["baseurl"]
            entries = []
            for entry in resolve(args.branch, args.version, download):
                url = base + entry["href"]
                sha = hashlib.sha256(download(url)).hexdigest()
                if sha != entry["sha256"]:
                    raise LockError(f"{url}: downloaded SHA-256 {sha} differs from the repository metadata {entry['sha256']}")
                entries.append((sha, url))
            write_lock(args.locks / f"{args.branch}.lock", args.branch, args.version, base, entries)
            return 0
        if not args.out:
            raise LockError("fetch needs --out")
        version, _, entries = read_lock(args.locks / f"{args.branch}.lock")
        args.out.mkdir(parents=True, exist_ok=True)
        for sha, url in entries:
            data = download(url)
            got = hashlib.sha256(data).hexdigest()
            if got != sha:
                raise LockError(f"{url}: SHA-256 {got}, locked {sha}")
            (args.out / url.rsplit("/", 1)[1]).write_bytes(data)
        print(version)
        return 0
    except (LockError, OSError, ET.ParseError) as error:
        print(f"lock.py: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
