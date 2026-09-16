#!/usr/bin/env python3
"""Locks for the third-party NVIDIA driver packages of the system image variants
(docs/architecture/doc_system_image.md, S4, S5 and S7).

  lock.py generate open|legacy --version V   resolve the branch's packages at exactly V in its
                                             repository and write locks/<branch>.lock with the
                                             SHA-256 of each downloaded RPM
  lock.py fetch open|legacy --out DIR        download the locked RPMs and verify each SHA-256;
                                             prints the lock's version
  lock.py check open|legacy --version V      exit 0 if the repository publishes the branch at V

Exit codes: 0 success, 3 the requested version is not published, 1 any other error
(network, metadata, lock file), 2 usage.

GPG signatures are verified by build-rpms.sh with rpmkeys and the keys in keys/: the lock
covers what the unsigned repository metadata of negativo17 cannot.
"""

import argparse
import functools
import gzip
import hashlib
import pathlib
import sys
import urllib.request
import xml.etree.ElementTree as ET
import xml.parsers.expat

HERE = pathlib.Path(__file__).resolve().parent
LOCKS = HERE / "locks"
COMMON = "{http://linux.duke.edu/metadata/common}"
REPO = "{http://linux.duke.edu/metadata/repo}"
ARCHES = ("x86_64", "noarch")
NOT_PUBLISHED = 3
BRANCHES = {
    "open": {
        "baseurl": "https://negativo17.org/repos/nvidia/fedora-43/x86_64/",
        "packages": [
            "nvidia-driver", "nvidia-driver-common", "nvidia-driver-cuda", "nvidia-driver-cuda-libs",
            "nvidia-driver-libs", "nvidia-kmod-common", "nvidia-modprobe", "nvidia-persistenced",
        ],
        # nvidia-kmod-common requires (nvidia-driver-selinux if selinux-policy-targeted).
        "companions": ["nvidia-driver-selinux"],
    },
    "legacy": {
        "baseurl": "https://download1.rpmfusion.org/nonfree/fedora/updates/43/x86_64/",
        "packages": [
            "nvidia-modprobe", "nvidia-persistenced", "nvidia-settings", "xorg-x11-drv-nvidia",
            "xorg-x11-drv-nvidia-cuda", "xorg-x11-drv-nvidia-cuda-libs", "xorg-x11-drv-nvidia-libs",
            "xorg-x11-drv-nvidia-power",
        ],
        "companions": [],
    },
}


class LockError(Exception):
    """A lock that cannot be produced or honoured; the message names the package or file."""


class NotPublished(LockError):
    """The repository does not publish the branch at the requested version."""


def http_get(url):
    with urllib.request.urlopen(url, timeout=120) as response:
        return response.read()


def parse_xml(data):
    """Repository metadata comes from the network: refuse any DTD, so no entity can expand
    or resolve. The expat DOCTYPE and ENTITY handlers below are the enforcement; the NUL and
    strict UTF-8 checks are an extra layer that refuses non-UTF-8 encodings before parsing."""
    if not data:
        raise LockError("repository metadata is empty: refused")
    if b"\x00" in data:
        raise LockError("repository metadata contains NUL bytes: refused")
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        raise LockError("repository metadata is not UTF-8: refused")
    # Single-pass parse: expat parser with TreeBuilder and DTD/entity refusal
    def _refuse(*_):
        raise LockError("repository metadata declares a DTD or entities: refused")
    parser = xml.parsers.expat.ParserCreate(namespace_separator="}")
    builder = ET.TreeBuilder()
    # Wrap TreeBuilder handlers to convert namespace format from "ns}tag" to "{ns}tag"
    def _start_element(name, attrs):
        if "}" in name:
            ns, tag = name.split("}", 1)
            name = f"{{{ns}}}{tag}"
        builder.start(name, attrs)
    def _end_element(name):
        if "}" in name:
            ns, tag = name.split("}", 1)
            name = f"{{{ns}}}{tag}"
        builder.end(name)
    parser.StartElementHandler = _start_element
    parser.EndElementHandler = _end_element
    parser.CharacterDataHandler = builder.data
    parser.StartDoctypeDeclHandler = _refuse
    parser.EntityDeclHandler = _refuse
    try:
        parser.Parse(data, True)
        return builder.close()
    except LockError:
        raise
    except xml.parsers.expat.ExpatError as e:
        raise LockError(str(e))


def attribute(element, tag, name, what):
    """`name` of the child `tag` of `element`, or LockError naming `what`."""
    child = element.find(tag)
    value = None if child is None else child.get(name)
    if not value:
        raise LockError(f"{what}: no {tag.rsplit('}', 1)[-1]} {name} in the repository metadata")
    return value


def primary_href(repomd):
    for data in parse_xml(repomd).iter(f"{REPO}data"):
        if data.get("type") == "primary":
            return attribute(data, f"{REPO}location", "href", "repomd.xml primary")
    raise LockError("repomd.xml has no primary metadata")


def rpmvercmp(a, b):
    """rpm's rpmvercmp: alphanumeric segments, numbers above letters, '~' sorts before
    anything (even the end of the string), '^' after the end but before any segment."""
    i = j = 0
    while i < len(a) or j < len(b):
        while i < len(a) and not (a[i].isascii() and a[i].isalnum()) and a[i] not in "~^":
            i += 1
        while j < len(b) and not (b[j].isascii() and b[j].isalnum()) and b[j] not in "~^":
            j += 1
        x, y = a[i:i + 1], b[j:j + 1]
        if "~" in (x, y):
            if x != y:
                return -1 if x == "~" else 1
            i, j = i + 1, j + 1
            continue
        if "^" in (x, y):
            if not x:
                return -1
            if not y:
                return 1
            if x != y:
                return 1 if y == "^" else -1
            i, j = i + 1, j + 1
            continue
        if not (x and y):
            break
        digits = x.isdigit()
        kind = str.isdigit if digits else str.isalpha
        si, sj = i, j
        while i < len(a) and a[i].isascii() and kind(a[i]):
            i += 1
        while j < len(b) and b[j].isascii() and kind(b[j]):
            j += 1
        one, two = a[si:i], b[sj:j]
        if not two:
            return 1 if digits else -1
        if digits:
            one, two = one.lstrip("0"), two.lstrip("0")
            if len(one) != len(two):
                return -1 if len(one) < len(two) else 1
        if one != two:
            return -1 if one < two else 1
    if i >= len(a) and j >= len(b):
        return 0
    return -1 if i >= len(a) else 1


def evr_compare(one, two):
    """Order of two (epoch, version, release) tuples as rpm sorts them; epochs are integers."""
    if one[0] != two[0]:
        return -1 if one[0] < two[0] else 1
    return rpmvercmp(one[1], two[1]) or rpmvercmp(one[2], two[2])


def select(primary_xml, names, version, companions=()):
    """One entry per name at exactly `version`, for x86_64 or noarch, and one per companion
    (a package whose version does not follow the driver's) at its newest published release."""
    found = {name: [] for name in names}
    published = {name: [] for name in companions}
    for pkg in parse_xml(primary_xml).iter(f"{COMMON}package"):
        name = pkg.findtext(f"{COMMON}name")
        if name not in found and name not in published:
            continue
        ver = attribute(pkg, f"{COMMON}version", "ver", name)
        if pkg.findtext(f"{COMMON}arch") not in ARCHES or (name in found and ver != version):
            continue
        if attribute(pkg, f"{COMMON}checksum", "type", name) != "sha256":
            raise LockError(f"{name}: checksum type {pkg.find(f'{COMMON}checksum').get('type')}, sha256 required")
        sha = pkg.findtext(f"{COMMON}checksum")
        if not sha:
            raise LockError(f"{name}: empty checksum in the repository metadata")
        entry = {"name": name, "href": attribute(pkg, f"{COMMON}location", "href", name), "sha256": sha}
        if name in found:
            found[name].append(entry)
        else:
            epoch = pkg.find(f"{COMMON}version").get("epoch") or "0"
            if not epoch.isascii() or not epoch.isdigit():
                raise LockError(f"{name}: epoch {epoch!r} in the repository metadata is not a number")
            evr = (int(epoch), ver, attribute(pkg, f"{COMMON}version", "rel", name))
            published[name].append((evr, entry))
    missing = sorted(n for n, entries in found.items() if not entries)
    if missing:
        raise NotPublished(f"not published at {version}: {', '.join(missing)}")
    ambiguous = sorted(n for n, entries in found.items() if len(entries) > 1)
    if ambiguous:
        raise LockError(f"ambiguous at {version} (several releases or arches): {', '.join(ambiguous)}")
    missing = sorted(n for n, releases in published.items() if not releases)
    if missing:
        raise LockError(f"not published: {', '.join(missing)}")
    for name, releases in published.items():
        newest = max((evr for evr, _ in releases), key=functools.cmp_to_key(evr_compare))
        top = [entry for evr, entry in releases if evr_compare(evr, newest) == 0]
        if len(top) > 1:
            raise LockError(f"ambiguous at its newest release: {name}")
        found[name] = top
    return [found[n][0] for n in sorted(found)]


def write_lock(path, branch, version, baseurl, entries):
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# branch {branch}", f"# version {version}", f"# repository {baseurl}"]
    lines += [f"{sha}  {url}" for sha, url in sorted(entries, key=lambda e: e[1])]
    path.write_text("\n".join(lines) + "\n")


def read_lock(path):
    branch = version = baseurl = None
    entries = []
    for number, line in enumerate(path.read_text().splitlines(), 1):
        if line.startswith("# branch "):
            branch = line.split(" ", 2)[2]
        elif line.startswith("# version "):
            version = line.split(" ", 2)[2]
        elif line.startswith("# repository "):
            baseurl = line.split(" ", 2)[2]
        elif line and not line.startswith("#"):
            sha, sep, url = line.partition("  ")
            if not sep or len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha) or not url or " " in url:
                raise LockError(f"{path}:{number}: malformed lock line, expected '<sha256>  <url>'")
            entries.append((sha, url))
    if not branch or not version or not baseurl or not entries:
        raise LockError(f"{path}: incomplete lock")
    return branch, version, baseurl, entries


def resolve(branch, version, download):
    base = BRANCHES[branch]["baseurl"]
    href = primary_href(download(base + "repodata/repomd.xml"))
    return select(gzip.decompress(download(base + href)), BRANCHES[branch]["packages"], version,
                  BRANCHES[branch]["companions"])


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
        path = args.locks / f"{args.branch}.lock"
        branch, version, baseurl, entries = read_lock(path)
        if branch != args.branch:
            raise LockError(f"{path}: lock of branch {branch}, {args.branch} requested")
        if baseurl != BRANCHES[branch]["baseurl"]:
            raise LockError(f"{path}: repository {baseurl}, the {branch} branch uses {BRANCHES[branch]['baseurl']}")
        outside = [url for _, url in entries if not url.startswith(baseurl)]
        if outside:
            raise LockError(f"{path}: URL outside the repository {baseurl}: {', '.join(outside)}")
        args.out.mkdir(parents=True, exist_ok=True)
        for sha, url in entries:
            data = download(url)
            got = hashlib.sha256(data).hexdigest()
            if got != sha:
                raise LockError(f"{url}: SHA-256 {got}, locked {sha}")
            (args.out / url.rsplit("/", 1)[1]).write_bytes(data)
        print(version)
        return 0
    except NotPublished as error:
        print(f"lock.py: {error}", file=sys.stderr)
        return NOT_PUBLISHED
    except (LockError, OSError) as error:
        print(f"lock.py: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
