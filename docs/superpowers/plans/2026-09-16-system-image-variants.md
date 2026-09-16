# System Image Variants Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:**
- Build `athanor-system` on Fedora's `base-atomic:43` with `nouveau` and no NVIDIA blobs.
- Build `athanor-system-nvidia` and `athanor-system-nvidia-legacy`, each carrying the signed NVIDIA modules plus the matching firmware and userspace, version-locked and hash-pinned.

**Architecture:** The work lands in three pull requests, because the image build installs `athanor-base-config` from the published tier 0 repository. The package change must therefore be published before the new Containerfile can pass its gates.

- **PR A (Tasks 1–3):**
  - lock files and a fetch/verify tool for the third-party RPMs;
  - the `azoth-nvidia-kmod` shim and the `athanor-nvidia-config` package;
  - the move of every NVIDIA file out of `athanor-base-config`;
  - the version-lock gate.
- **PR B (Tasks 4–6):**
  - the multi-stage Containerfile (base-atomic, a builder stage for the NVIDIA RPMs, one GPU stage per variant, gated final stage);
  - `system/build-image.sh`;
  - the release workflow building, signing and publishing three images;
  - a pull-request check that builds all three unsigned on the self-hosted runner;
  - the documentation.
- **PR C (Task 7):** the bump bot keeps the base digest, the NVIDIA pins and the locks moving together.

Task 8 ships and migrates the maintainer's desktop.

**Tech Stack:** Python 3 standard library (`unittest`), Bash, RPM spec files and `rpmbuild`, `dnf5`, podman/buildah multi-stage builds, GitHub Actions, cosign/syft via the existing `forge/scripts` helpers.

**Spec:** `docs/architecture/doc_system_image.md` (approved 2026-09-16). Owned elsewhere: `docs/architecture/doc_kernel_build.md` sections 8, 10 and 13.

## Global Constraints

- **S1:** the base is `quay.io/fedora-ostree-desktops/base-atomic:43`, pinned by digest (today `sha256:ead5f8bc4032ea4bc2f61d60f3101d6cc90f6c87bb405345a3d18b8b1651cd70`).
- **S2:** there are three images from one Containerfile: `athanor-system` (GPU `none`), `athanor-system-nvidia` (GPU `nvidia`, open branch), `athanor-system-nvidia-legacy` (GPU `nvidia-legacy`, legacy branch).
- **S3:** the default image has no `nvidia*.ko`, no NVIDIA kernel argument, modprobe option or dracut configuration, and no negativo17 repository.
- **S4:** the open branch uses negativo17 packages at exactly `3:NVIDIA_OPEN_VERSION` (today 610.57.04): `nvidia-driver`, `nvidia-driver-common`, `nvidia-driver-libs`, `nvidia-driver-cuda`, `nvidia-driver-cuda-libs`, `nvidia-kmod-common`, `nvidia-modprobe`, `nvidia-persistenced`, plus `azoth-nvidia-kmod` providing `nvidia-kmod = 3:<version>`. akmods and DKMS are never installed.
- **S5:** the legacy branch uses RPM Fusion nonfree packages at exactly `3:NVIDIA_LEGACY_VERSION` (today 580.178.04): `xorg-x11-drv-nvidia`, `xorg-x11-drv-nvidia-libs`, `xorg-x11-drv-nvidia-cuda`, `xorg-x11-drv-nvidia-cuda-libs`, `nvidia-modprobe`, `nvidia-persistenced`, `nvidia-settings`, plus the same shim at the legacy version.
- **S6:** the build fails unless module versions, installed driver packages, the firmware directory (open branch) and the pin all match. Mismatches print the exact values.
- **S7:** third-party RPMs are pinned by SHA-256 in `system/nvidia/locks/<branch>.lock`, and their GPG signatures are checked against keys vendored in `system/nvidia/keys/`.
- **S8:** one signing job builds, signs and attests all three images. One ISO, from `athanor-system`.
- **Resolved dependency closures** (dnf5 in `fedora:43`, 2026-09-16). negativo17 would otherwise pull `akmod-nvidia` as the `nvidia-kmod` provider, and `nvidia-modprobe` 615.71.09 unless it is pinned. RPM Fusion pulls `akmod-nvidia` and `xorg-x11-drv-nvidia-kmodsrc`. `athanor-base-config`'s `rpmfusion.repo` excludes `*nvidia*`.
- **Project rules:**
  - English for code, comments and commits; Italian inside `doc_kernel_build.md` and `KERNEL.md`;
  - logic lives in scripts under the repository, and workflow `run:` blocks only call them;
  - no `|| true`, no `continue-on-error`;
  - never `cd` in commands; `python3 -B`;
  - never push `forge/**` while an Orchestrator cycle runs.
- **Commits** end with
  `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`
  `Claude-Session: https://claude.ai/code/session_01EUnNXqv8jNWDVMA83G7eZ4`
- **Scratch:** `SCRATCH=/tmp/claude-1000/-var-home-hr-mes-athanor/a017eddd-482c-4c5e-9fdb-3bfc898b9a39/scratchpad`.
- **Local podman:**
  - Commands that run containers need the Claude Code sandbox disabled.
  - Rootless podman on this host fails with "Read-only file system" when its pause process was started inside the greetd session namespace. Fix it with `systemd-run --user --pipe --wait podman system migrate`.
  - `quay.io/fedora-ostree-desktops/base-atomic:43` cannot be pulled locally (ostree hard-link error), so the full image builds run in CI (Task 5).
  - `registry.fedoraproject.org/fedora:43` pulls fine locally.

## File Structure

| Path | Responsibility | PR |
| --- | --- | --- |
| `system/nvidia/lock.py` | `generate`, `fetch` and `check` for the third-party RPM locks | A |
| `system/nvidia/locks/open.lock`, `legacy.lock` | pinned URLs and SHA-256 of the vendor RPMs | A |
| `system/nvidia/keys/RPM-GPG-KEY-negativo17`, `RPM-GPG-KEY-rpmfusion-nonfree-fedora-2020` | vendored signing keys | A |
| `system/nvidia/azoth-nvidia-kmod.spec` | the `nvidia-kmod` capability shim | A |
| `system/nvidia/athanor-nvidia-config/athanor-nvidia-config.spec` + `SOURCES/` | NVIDIA kargs, modprobe, dracut, sleep units and presets, moved from `athanor-base-config` | A |
| `system/nvidia/build-rpms.sh` | in the builder stage: fetch and verify the locked RPMs, build shim and config RPMs per branch | A |
| `system/nvidia/gate.sh` | S3 and S6 gates for a finished image root | A |
| `system/nvidia/tests/test_lock.py`, `test_gate.py` | unit tests | A |
| `forge/specs/athanor-base-config/` | drops the NVIDIA files, `fedora-nvidia.repo` and the negativo17 key | A |
| `system/Containerfile` | base-atomic, builder stage, GPU stages, gated final stage | B |
| `system/build-image.sh` | build (and optionally push) one image per GPU | B |
| `.github/workflows/call-system-image.yml` | three builds, signs and attestations in the signing job | B |
| `.github/workflows/system-image-check.yml` | unsigned three-image build on pull requests, package delta report | B |
| `forge/config/packages.json` | `libva-nvidia-driver` leaves `upstream_media` | B |
| `docs/architecture/doc_kernel_build.md`, `doc_kernel_profile.md`, `NEXT.md` | changes owed by spec section 8 | B |
| `forge/specs/azoth/bump.py`, `.github/workflows/kernel-bump.yml` | base digest in the bump, NVIDIA availability, lock regeneration | C |

---

## PR A — packages, locks and gate (branch `system-image-variants`)

### Task 1: Lock files for the third-party NVIDIA RPMs

**Files:**
- Create: `system/nvidia/lock.py`, `system/nvidia/tests/test_lock.py`
- Create: `system/nvidia/keys/RPM-GPG-KEY-negativo17` (copied from `forge/specs/athanor-base-config/SOURCES/etc/pki/rpm-gpg/RPM-GPG-KEY-negativo17`), `system/nvidia/keys/RPM-GPG-KEY-rpmfusion-nonfree-fedora-2020` (copied from the same directory)
- Create (generated): `system/nvidia/locks/open.lock`, `system/nvidia/locks/legacy.lock`

**Interfaces:**
- Produces:
  - `lock.py generate BRANCH --version V [--locks DIR]` writes `DIR/BRANCH.lock`.
  - `lock.py fetch BRANCH --out DIR [--locks DIR]` downloads the locked RPMs into DIR, verifies each SHA-256, and prints the lock's version on stdout.
  - `lock.py check BRANCH --version V` exits 0 when the repository publishes every package of the branch at V, and 1 otherwise, with the missing names on stderr.
  - Module functions `select(primary_xml: bytes, names, version) -> list[dict]`, `write_lock(path, branch, version, entries)`, `read_lock(path) -> (version, baseurl, [(sha256, url)])`.
- Lock format:

  ```
  # branch open
  # version 610.57.04
  # repository https://negativo17.org/repos/nvidia/fedora-43/x86_64/
  <sha256>  <url>
  ```

  Lines are sorted by URL.

- [ ] **Step 1: Write the failing tests**

```python
"""Unit tests of system/nvidia/lock.py (python3 -B -m unittest discover -s system/nvidia/tests -v)."""

import gzip
import hashlib
import io
import pathlib
import sys
import tempfile
import unittest
from contextlib import redirect_stderr

HERE = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import lock  # noqa: E402

COMMON = 'xmlns="http://linux.duke.edu/metadata/common" xmlns:rpm="http://linux.duke.edu/metadata/rpm"'


def package(name, epoch, ver, rel, arch, href, sha):
    return (
        f'<package type="rpm"><name>{name}</name><arch>{arch}</arch>'
        f'<version epoch="{epoch}" ver="{ver}" rel="{rel}"/>'
        f'<checksum type="sha256" pkgid="YES">{sha}</checksum>'
        f'<location href="{href}"/></package>'
    )


def primary(*packages):
    return f'<?xml version="1.0"?><metadata {COMMON} packages="{len(packages)}">{"".join(packages)}</metadata>'.encode()


class Select(unittest.TestCase):
    def test_picks_every_name_at_the_exact_version(self):
        xml = primary(
            package("nvidia-driver", 3, "610.57.04", "1.fc43", "x86_64", "nvidia-driver-610.57.04-1.fc43.x86_64.rpm", "a" * 64),
            package("nvidia-driver", 3, "615.71.09", "1.fc43", "x86_64", "nvidia-driver-615.71.09-1.fc43.x86_64.rpm", "b" * 64),
            package("nvidia-kmod-common", 3, "610.57.04", "1.fc43", "noarch", "nvidia-kmod-common-610.57.04-1.fc43.noarch.rpm", "c" * 64),
            package("nvidia-driver", 3, "610.57.04", "1.fc43", "i686", "nvidia-driver-610.57.04-1.fc43.i686.rpm", "d" * 64),
        )
        got = lock.select(xml, ["nvidia-driver", "nvidia-kmod-common"], "610.57.04")
        self.assertEqual(
            [(e["name"], e["href"], e["sha256"]) for e in got],
            [
                ("nvidia-driver", "nvidia-driver-610.57.04-1.fc43.x86_64.rpm", "a" * 64),
                ("nvidia-kmod-common", "nvidia-kmod-common-610.57.04-1.fc43.noarch.rpm", "c" * 64),
            ],
        )

    def test_missing_package_is_an_error_naming_it(self):
        xml = primary(package("nvidia-driver", 3, "610.57.04", "1.fc43", "x86_64", "a.rpm", "a" * 64))
        with self.assertRaisesRegex(lock.LockError, "nvidia-persistenced"):
            lock.select(xml, ["nvidia-driver", "nvidia-persistenced"], "610.57.04")

    def test_metadata_with_entities_is_refused(self):
        xml = b'<?xml version="1.0"?><!DOCTYPE m [<!ENTITY x "y">]><metadata/>'
        with self.assertRaisesRegex(lock.LockError, "DTD"):
            lock.select(xml, ["nvidia-driver"], "610.57.04")

    def test_two_releases_of_one_version_are_ambiguous(self):
        xml = primary(
            package("nvidia-driver", 3, "610.57.04", "1.fc43", "x86_64", "a.rpm", "a" * 64),
            package("nvidia-driver", 3, "610.57.04", "2.fc43", "x86_64", "b.rpm", "b" * 64),
        )
        with self.assertRaisesRegex(lock.LockError, "ambiguous"):
            lock.select(xml, ["nvidia-driver"], "610.57.04")


class LockFile(unittest.TestCase):
    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            path = pathlib.Path(d) / "open.lock"
            lock.write_lock(path, "open", "610.57.04", "https://repo/x/", [("f" * 64, "https://repo/x/b.rpm"), ("e" * 64, "https://repo/x/a.rpm")])
            version, baseurl, entries = lock.read_lock(path)
            self.assertEqual(version, "610.57.04")
            self.assertEqual(baseurl, "https://repo/x/")
            self.assertEqual(entries, [("e" * 64, "https://repo/x/a.rpm"), ("f" * 64, "https://repo/x/b.rpm")])


class Fetch(unittest.TestCase):
    def test_hash_mismatch_fails_and_keeps_nothing(self):
        payload = b"rpm bytes"
        with tempfile.TemporaryDirectory() as d:
            tmp = pathlib.Path(d)
            lock.write_lock(tmp / "open.lock", "open", "610.57.04", "https://repo/", [("0" * 64, "https://repo/a.rpm")])
            out = tmp / "out"
            err = io.StringIO()
            with redirect_stderr(err):
                code = lock.main(["fetch", "open", "--out", str(out), "--locks", str(tmp)], download=lambda url: payload)
            self.assertEqual(code, 1)
            self.assertIn("a.rpm", err.getvalue())
            self.assertFalse((out / "a.rpm").exists())

    def test_matching_hash_is_written(self):
        payload = b"rpm bytes"
        sha = hashlib.sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory() as d:
            tmp = pathlib.Path(d)
            lock.write_lock(tmp / "open.lock", "open", "610.57.04", "https://repo/", [(sha, "https://repo/a.rpm")])
            out = tmp / "out"
            code = lock.main(["fetch", "open", "--out", str(out), "--locks", str(tmp)], download=lambda url: payload)
            self.assertEqual(code, 0)
            self.assertEqual((out / "a.rpm").read_bytes(), payload)


class Repomd(unittest.TestCase):
    def test_primary_href_from_repomd(self):
        repomd = (
            b'<?xml version="1.0"?><repomd xmlns="http://linux.duke.edu/metadata/repo">'
            b'<data type="filelists"><location href="repodata/f.xml.gz"/></data>'
            b'<data type="primary"><location href="repodata/p.xml.gz"/></data></repomd>'
        )
        self.assertEqual(lock.primary_href(repomd), "repodata/p.xml.gz")

    def test_generate_writes_hashes_from_downloads(self):
        rpm = b"payload"
        sha = hashlib.sha256(rpm).hexdigest()
        xml = primary(*[
            package(n, 3, "580.178.04", "1.fc43", "x86_64", f"x/{n}.rpm", sha) for n in lock.BRANCHES["legacy"]["packages"]
        ])
        base = lock.BRANCHES["legacy"]["baseurl"]
        files = {
            base + "repodata/repomd.xml": b'<repomd xmlns="http://linux.duke.edu/metadata/repo"><data type="primary"><location href="repodata/p.xml.gz"/></data></repomd>',
            base + "repodata/p.xml.gz": gzip.compress(xml),
        }
        with tempfile.TemporaryDirectory() as d:
            code = lock.main(["generate", "legacy", "--version", "580.178.04", "--locks", d], download=lambda url: files.get(url, rpm))
            self.assertEqual(code, 0)
            version, _, entries = lock.read_lock(pathlib.Path(d) / "legacy.lock")
            self.assertEqual(version, "580.178.04")
            self.assertEqual(len(entries), len(lock.BRANCHES["legacy"]["packages"]))
            self.assertTrue(all(s == sha for s, _ in entries))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -B -m unittest discover -s system/nvidia/tests -v`

Expected: an ERROR with `ModuleNotFoundError: No module named 'lock'`.

- [ ] **Step 3: Write `system/nvidia/lock.py`**

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -B -m unittest discover -s system/nvidia/tests -v`

Expected: `Ran 9 tests` … `OK`.

- [ ] **Step 5: Vendor the keys and generate the real locks**

```bash
mkdir -p system/nvidia/keys
cp forge/specs/athanor-base-config/SOURCES/etc/pki/rpm-gpg/RPM-GPG-KEY-negativo17 system/nvidia/keys/
cp forge/specs/athanor-base-config/SOURCES/etc/pki/rpm-gpg/RPM-GPG-KEY-rpmfusion-nonfree-fedora-2020 system/nvidia/keys/
python3 -B system/nvidia/lock.py generate open --version "$(sed -n 's/^NVIDIA_OPEN_VERSION=//p' forge/specs/azoth/pins.env)"
python3 -B system/nvidia/lock.py generate legacy --version "$(sed -n 's/^NVIDIA_LEGACY_VERSION=//p' forge/specs/azoth/pins.env)"
```

These commands need network access; run them with the sandbox disabled.

Expected:
- `system/nvidia/locks/open.lock` has 8 RPM lines, all `-610.57.04-1.fc43`, with `nvidia-modprobe-610.57.04` and not 615.
- `legacy.lock` has 7 lines, all `-580.178.04-1.fc43`.
- `grep -c akmod system/nvidia/locks/*.lock` prints `0` for both files.

- [ ] **Step 6: Commit**

```bash
git -C /var/home/hr-mes/athanor add system/nvidia/lock.py system/nvidia/tests/test_lock.py system/nvidia/keys system/nvidia/locks
git -C /var/home/hr-mes/athanor commit -m "feat(system): lock the third-party NVIDIA driver packages by hash" -m "lock.py resolves the negativo17 (open) and RPM Fusion (legacy) packages at exactly the pinned NVIDIA version, records the SHA-256 of each RPM and verifies them on fetch (doc_system_image.md, S7)." -m "Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01EUnNXqv8jNWDVMA83G7eZ4"
```

---

### Task 2: The shim, `athanor-nvidia-config`, and a clean `athanor-base-config`

**Files:**
- Create: `system/nvidia/azoth-nvidia-kmod.spec`
- Create: `system/nvidia/athanor-nvidia-config/athanor-nvidia-config.spec`
- Move with `git mv`, from `forge/specs/athanor-base-config/SOURCES/` to `system/nvidia/athanor-nvidia-config/SOURCES/`, keeping the relative path:
  - `usr/bin/nvidia-sleep.sh`
  - `usr/lib/modprobe.d/nvidia-drm.conf`, `usr/lib/modprobe.d/nvidia-power-management.conf`
  - `usr/lib/modules-load.d/10-nvidia.conf`
  - `usr/lib/systemd/system-sleep/nvidia`
  - `usr/lib/systemd/system/nvidia-hibernate.service`, `nvidia-resume.service`, `nvidia-suspend.service`, `nvidia-suspend-then-hibernate.service`, `nvidia-powerd.service.d/`
  - `usr/lib/udev/rules.d/71-nvidia-uaccess.rules`
  - `usr/lib/bootc/kargs.d/01-nvidia.toml`
  - `usr/lib/dracut/dracut.conf.d/nvidia-drm.conf`
  - `usr/lib/systemd/system-preset/70-nvidia.preset`
- Delete: `forge/specs/athanor-base-config/SOURCES/etc/yum.repos.d/fedora-nvidia.repo`, `forge/specs/athanor-base-config/SOURCES/etc/pki/rpm-gpg/RPM-GPG-KEY-negativo17`
- Create: `system/nvidia/build-rpms.sh`
- Modify: `forge/specs/athanor-base-config/athanor-base-config.spec`

**Interfaces:**
- Consumes: `lock.py fetch` (Task 1).
- Produces:
  - `system/nvidia/build-rpms.sh OUTDIR`, which runs in a `fedora:43` container as root and writes `OUTDIR/open/*.rpm` and `OUTDIR/legacy/*.rpm`: the locked vendor RPMs, verified by hash and GPG, plus `azoth-nvidia-kmod` and `athanor-nvidia-config` built for that branch.
  - It reads the versions from `forge/specs/azoth/pins.env`, and fails if a lock's version differs from the pin.

- [ ] **Step 1: Find the files the vendor packages already own**

Run:

```bash
mkdir -p "$SCRATCH/nv-lists"
for b in open legacy; do python3 -B system/nvidia/lock.py fetch $b --out "$SCRATCH/nv-rpms/$b" > /dev/null; done
for f in "$SCRATCH"/nv-rpms/*/*.rpm; do rpm -qlp "$f"; done | sort -u > "$SCRATCH/nv-lists/vendor.txt"
find forge/specs/athanor-base-config/SOURCES -iname '*nvidia*' | sed 's#^forge/specs/athanor-base-config/SOURCES##' | sort > "$SCRATCH/nv-lists/ours.txt"
comm -12 "$SCRATCH/nv-lists/vendor.txt" "$SCRATCH/nv-lists/ours.txt"
```

Expected: the paths both sides ship, if any. Record them in the task report.

Every overlapping file is **not** moved: delete it instead, because the vendor package wins. That applies to units, udev rules and presets alike. `70-nvidia.preset` must still enable only units that exist after installation; Step 7 verifies that.

- [ ] **Step 2: Write `system/nvidia/azoth-nvidia-kmod.spec`**

```spec
Name:           azoth-nvidia-kmod
Version:        %{nvidia_version}
Release:        1%{?dist}
Summary:        Declares the signed NVIDIA modules of the Azoth kernel as the installed nvidia-kmod
License:        MIT
URL:            https://github.com/hr-mes/athanor
BuildArch:      noarch
# The modules themselves come from ghcr.io/hr-mes/azoth-nvidia:<kernel-nvr>-<branch>, built
# and signed by nvidia-kmod.yml; the driver packages require a package providing the module
# at their exact version (doc_system_image.md, S4 and S5).
Provides:       nvidia-kmod = 3:%{nvidia_version}
Conflicts:      akmod-nvidia
Conflicts:      kmod-nvidia
Conflicts:      dkms-nvidia

%description
Satisfies the nvidia-kmod requirement of the NVIDIA driver packages with the signed modules
that the Athanor system image copies next to the Azoth kernel. It installs no files.

%prep

%build

%install

%files

%changelog
* Wed Sep 16 2026 Athanor Forge <forge@athanor.os> - %{nvidia_version}-1
- Shim for the signed NVIDIA modules of the Azoth kernel
```

- [ ] **Step 3: Move the files and write `athanor-nvidia-config.spec`**

Run the `git mv` commands for the files listed under **Files**, skipping those that Step 1 found overlapping. Delete the overlapping ones with `git rm`. Then write the spec:

```spec
%global debug_package %{nil}
Name:           athanor-nvidia-config
Version:        1.0.0
Release:        1%{?dist}
Summary:        Athanor configuration for the NVIDIA image variants
License:        MIT
URL:            https://github.com/hr-mes/athanor
BuildArch:      noarch
Requires:       azoth-nvidia-kmod

%description
Kernel arguments, modprobe and dracut settings, suspend and resume units and their presets
for the NVIDIA driver. Installed only by athanor-system-nvidia and
athanor-system-nvidia-legacy (docs/architecture/doc_system_image.md, S4).

%prep

%build

%install
mkdir -p %{buildroot}
cp -a %{_sourcedir}/usr %{buildroot}/

%files
/usr/bin/nvidia-sleep.sh
/usr/lib/bootc/kargs.d/01-nvidia.toml
/usr/lib/dracut/dracut.conf.d/nvidia-drm.conf
/usr/lib/modprobe.d/nvidia-drm.conf
/usr/lib/modprobe.d/nvidia-power-management.conf
/usr/lib/modules-load.d/10-nvidia.conf
/usr/lib/systemd/system-preset/70-nvidia.preset
/usr/lib/systemd/system-sleep/nvidia
/usr/lib/systemd/system/nvidia-*
/usr/lib/udev/rules.d/71-nvidia-uaccess.rules

%changelog
* Wed Sep 16 2026 Athanor Forge <forge@athanor.os> - 1.0.0-1
- NVIDIA configuration moved out of athanor-base-config (doc_system_image.md, S4)
```

Remove from `%files` every line for a file Step 1 deleted. Keep the rest exactly.

- [ ] **Step 4: Clean `athanor-base-config.spec`**

In `forge/specs/athanor-base-config/athanor-base-config.spec`:
- Delete the `%files` lines for the moved files: `/usr/bin/nvidia-sleep.sh`, `/usr/lib/bootc/kargs.d/01-nvidia.toml`, `/usr/lib/systemd/system-sleep/nvidia`, `/usr/lib/systemd/system/nvidia-*`.
- Delete the globs whose directory is now empty: `/usr/lib/modprobe.d/*`, `/usr/lib/modules-load.d/*`, `/usr/lib/udev/rules.d/*`. Check each directory with `ls forge/specs/athanor-base-config/SOURCES/<dir>`; if a directory still has files, keep its line.
- Replace `Summary:` with `Athanor OS Base Configuration (Systemd, Branding, GPG)`.
- In `%description`, replace `It includes NVIDIA sleep scripts, Dracut configurations, modprobe rules,` with `It includes Dracut configurations,`.
- Bump `Release:` to `3%{?dist}`.
- Add a changelog entry at the top: `* Wed Sep 16 2026 Athanor Forge <forge@athanor.os> - 43.0.0-3` and `- Move the NVIDIA configuration and the negativo17 repository to athanor-nvidia-config (doc_system_image.md, S3)`.

- [ ] **Step 5: Write `system/nvidia/build-rpms.sh`**

```bash
#!/usr/bin/env bash
# The RPMs of the NVIDIA image variants (docs/architecture/doc_system_image.md, S4-S7), built in
# the nvidia-rpms stage of system/Containerfile on registry.fedoraproject.org/fedora:43, as
# root in a throwaway stage. For each branch: the locked vendor RPMs (lock.py fetch: SHA-256),
# their GPG signatures checked with the vendored keys, and azoth-nvidia-kmod plus
# athanor-nvidia-config built at the branch's pinned version.
#
# Usage: build-rpms.sh OUTDIR   (run from the repository copy at /src)
set -euo pipefail

OUT=${1:?usage: build-rpms.sh OUTDIR}
SRC=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
NV=$SRC/system/nvidia
die() { echo "build-rpms.sh: $*" >&2; exit 1; }
pin() { sed -n "s/^$1=//p" "$SRC/forge/specs/azoth/pins.env"; }

rpmkeys --import "$NV/keys/RPM-GPG-KEY-negativo17" "$NV/keys/RPM-GPG-KEY-rpmfusion-nonfree-fedora-2020"

for branch in open legacy; do
  case $branch in
    open) expected=$(pin NVIDIA_OPEN_VERSION) ;;
    legacy) expected=$(pin NVIDIA_LEGACY_VERSION) ;;
  esac
  dest=$OUT/$branch
  locked=$(python3 -B "$NV/lock.py" fetch "$branch" --out "$dest")
  [[ $locked == "$expected" ]] || die "$branch: locks/$branch.lock is at $locked, pins.env at $expected: regenerate the lock"
  for rpm in "$dest"/*.rpm; do
    rpmkeys --checksig "$rpm" | grep -q ': digests signatures OK$' || die "${rpm##*/}: GPG signature not verified with system/nvidia/keys"
  done
  rpmbuild -bb --define "_topdir $OUT/rpmbuild-$branch" --define "nvidia_version $expected" "$NV/azoth-nvidia-kmod.spec"
  rpmbuild -bb --define "_topdir $OUT/rpmbuild-$branch" --define "_sourcedir $NV/athanor-nvidia-config/SOURCES" \
    "$NV/athanor-nvidia-config/athanor-nvidia-config.spec"
  cp "$OUT/rpmbuild-$branch"/RPMS/noarch/*.rpm "$dest/"
  rm -rf "$OUT/rpmbuild-$branch"
  echo "build-rpms.sh: $branch $expected: $(find "$dest" -name '*.rpm' | wc -l) RPMs"
done
```

Run: `chmod 0755 system/nvidia/build-rpms.sh && bash -n system/nvidia/build-rpms.sh && shellcheck -x system/nvidia/build-rpms.sh`

Expected: no output.

- [ ] **Step 6: Run the builder and a real install for each branch**

Run with the sandbox disabled:

```bash
podman run --rm --security-opt label=disable -v /var/home/hr-mes/athanor:/src:ro -v "$SCRATCH/nv-out:/out" registry.fedoraproject.org/fedora:43 \
  bash -c 'dnf5 -y -q install rpm-build python3 >/dev/null && bash /src/system/nvidia/build-rpms.sh /out'
```

Expected:
- `build-rpms.sh: open 610.57.04: 10 RPMs`
- `build-rpms.sh: legacy 580.178.04: 9 RPMs`

Then the closure and conflict test:

```bash
for b in open legacy; do
  podman run --rm --security-opt label=disable -v "$SCRATCH/nv-out/$b:/rpms:ro" registry.fedoraproject.org/fedora:43 \
    bash -c 'dnf5 -y -q install --setopt=install_weak_deps=False /rpms/*.rpm >/tmp/log 2>&1 || { tail -30 /tmp/log; exit 1; }; rpm -q akmod-nvidia kmod-nvidia dkms-nvidia xorg-x11-drv-nvidia-kmodsrc | grep -c "is not installed"; systemctl preset-all >/dev/null 2>&1; for u in $(sed -n "s/^enable //p" /usr/lib/systemd/system-preset/70-nvidia.preset); do systemctl cat "$u" >/dev/null 2>&1 || echo "preset names missing unit $u"; done; echo "$b ok"'
done
```

Expected for each branch:
- `4`: none of the akmods, kmod, DKMS or kmodsrc packages are installed;
- no `preset names missing unit` line;
- `<branch> ok`.

If a file conflict appears, go back to Step 1: the conflicting file is vendor-owned and must be deleted from `athanor-nvidia-config`. If a preset names a missing unit, remove that `enable` line from `70-nvidia.preset`.

- [ ] **Step 7: Verify the specs and commit**

Run: `python3 -B scripts/verify.py specs 2>&1 | grep -E "athanor-base-config|athanor-nvidia-config|azoth-nvidia-kmod"`

Expected: no output.

```bash
git -C /var/home/hr-mes/athanor add -A system/nvidia forge/specs/athanor-base-config
git -C /var/home/hr-mes/athanor commit -m "feat(system): package the NVIDIA configuration for the image variants only" -m "athanor-base-config no longer ships the NVIDIA kernel arguments, modprobe, dracut, sleep units, presets or the negativo17 repository to every machine; athanor-nvidia-config carries them for the NVIDIA variants, azoth-nvidia-kmod provides nvidia-kmod for the signed modules, and build-rpms.sh assembles each branch from hash- and GPG-verified vendor RPMs (doc_system_image.md, S3-S5, S7)." -m "Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01EUnNXqv8jNWDVMA83G7eZ4"
```

---

### Task 3: The image gate

**Files:**
- Create: `system/nvidia/gate.sh`, `system/nvidia/tests/test_gate.py`

**Interfaces:**
- Produces: `gate.sh none|nvidia|nvidia-legacy PINS_ENV [ROOT]`.
  - Exit 0 when the image root satisfies S3 (`none`) or S6 plus the S8 file checks (`nvidia`, `nvidia-legacy`).
  - Exit 1 otherwise, with one line per violation on stderr, each starting `nvidia gate:`.
  - It uses `modinfo` and `rpm` from `PATH`, so tests can stub them.

- [ ] **Step 1: Write the failing tests**

```python
"""Unit tests of system/nvidia/gate.sh with stub modinfo and rpm (python3 -B -m unittest discover -s system/nvidia/tests -v)."""

import os
import pathlib
import subprocess
import tempfile
import textwrap
import unittest

GATE = pathlib.Path(__file__).resolve().parents[1] / "gate.sh"
PINS = "NVIDIA_OPEN_VERSION=610.57.04\nNVIDIA_LEGACY_VERSION=580.178.04\n"


class Gate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self.tmp.name)
        self.root = self.dir / "root"
        self.bin = self.dir / "bin"
        self.bin.mkdir()
        (self.dir / "pins.env").write_text(PINS)
        self.modules = {}
        self.packages = {}

    def tearDown(self):
        self.tmp.cleanup()

    def touch(self, rel, text=""):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def run_gate(self, gpu):
        (self.bin / "modinfo").write_text(textwrap.dedent(f"""\
            #!/bin/bash
            declare -A v=({" ".join(f'[{k}]={val}' for k, val in self.modules.items())})
            echo "${{v[$(basename "$3")]}}"
            """))
        (self.bin / "rpm").write_text(textwrap.dedent(f"""\
            #!/bin/bash
            declare -A v=({" ".join(f'[{k}]={val}' for k, val in self.packages.items())})
            name=${{@: -1}}
            if [[ -n ${{v[$name]:-}} ]]; then echo "${{v[$name]}}"; else echo "package $name is not installed"; exit 1; fi
            """))
        for f in self.bin.iterdir():
            f.chmod(0o755)
        env = dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}")
        return subprocess.run(["bash", str(GATE), gpu, str(self.dir / "pins.env"), str(self.root)], capture_output=True, text=True, env=env)

    def open_image(self, version="610.57.04"):
        for ko in ("nvidia.ko", "nvidia-drm.ko"):
            self.touch(f"usr/lib/modules/7.2.5-100.azoth.fc43.x86_64/extra/nvidia/{ko}")
            self.modules[ko] = version
        for pkg in ("nvidia-driver", "nvidia-driver-libs", "nvidia-kmod-common", "azoth-nvidia-kmod"):
            self.packages[pkg] = version
        self.touch(f"usr/lib/firmware/nvidia/{version}/gsp_ga10x.bin")
        self.touch(f"usr/lib/firmware/nvidia/{version}/gsp_tu10x.bin")
        self.touch("usr/share/glvnd/egl_vendor.d/10_nvidia.json")
        self.touch("usr/lib64/gbm/nvidia-drm_gbm.so")
        self.touch("usr/share/vulkan/icd.d/nvidia_icd.x86_64.json")

    def test_complete_open_image_passes(self):
        self.open_image()
        r = self.run_gate("nvidia")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_module_version_mismatch_fails_with_values(self):
        self.open_image()
        self.modules["nvidia-drm.ko"] = "610.43.02"
        r = self.run_gate("nvidia")
        self.assertEqual(r.returncode, 1)
        self.assertIn("nvidia-drm.ko: module 610.43.02, pin 610.57.04", r.stderr)

    def test_missing_gsp_firmware_fails(self):
        self.open_image()
        (self.root / "usr/lib/firmware/nvidia/610.57.04/gsp_tu10x.bin").unlink()
        r = self.run_gate("nvidia")
        self.assertEqual(r.returncode, 1)
        self.assertIn("gsp_tu10x.bin", r.stderr)

    def test_missing_userspace_file_fails(self):
        self.open_image()
        (self.root / "usr/lib64/gbm/nvidia-drm_gbm.so").unlink()
        r = self.run_gate("nvidia")
        self.assertEqual(r.returncode, 1)
        self.assertIn("nvidia-drm_gbm.so", r.stderr)

    def test_package_version_mismatch_fails(self):
        self.open_image()
        self.packages["nvidia-driver-libs"] = "615.71.09"
        r = self.run_gate("nvidia")
        self.assertEqual(r.returncode, 1)
        self.assertIn("nvidia-driver-libs: package 615.71.09, pin 610.57.04", r.stderr)

    def test_legacy_image_uses_legacy_pin_and_packages(self):
        for ko in ("nvidia.ko",):
            self.touch(f"usr/lib/modules/7.2.5-100.azoth.fc43.x86_64/extra/nvidia/{ko}")
            self.modules[ko] = "580.178.04"
        for pkg in ("xorg-x11-drv-nvidia", "xorg-x11-drv-nvidia-libs", "azoth-nvidia-kmod"):
            self.packages[pkg] = "580.178.04"
        self.touch("usr/share/glvnd/egl_vendor.d/10_nvidia.json")
        self.touch("usr/lib64/gbm/nvidia-drm_gbm.so")
        self.touch("usr/share/vulkan/icd.d/nvidia_icd.x86_64.json")
        r = self.run_gate("nvidia-legacy")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_default_image_rejects_nvidia_content(self):
        self.touch("usr/lib/modules/7.2.5-100.azoth.fc43.x86_64/extra/nvidia/nvidia.ko")
        self.touch("usr/lib/bootc/kargs.d/01-nvidia.toml", 'kargs = ["nvidia-drm.modeset=1"]')
        self.touch("etc/yum.repos.d/fedora-nvidia.repo", "[fedora-nvidia]\nbaseurl=https://negativo17.org/repos/nvidia/")
        r = self.run_gate("none")
        self.assertEqual(r.returncode, 1)
        for text in ("nvidia.ko", "01-nvidia.toml", "fedora-nvidia.repo"):
            self.assertIn(text, r.stderr)

    def test_clean_default_image_passes(self):
        self.touch("usr/lib/modules/7.2.5-100.azoth.fc43.x86_64/vmlinuz")
        self.touch("usr/lib/bootc/kargs.d/02-hardening.toml", 'kargs = ["slab_nomerge"]')
        self.touch("usr/lib/modprobe.d/dist-blacklist.conf", "blacklist nvidiafb\n")
        r = self.run_gate("none")
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -B -m unittest discover -s system/nvidia/tests -v`

Expected: the 8 `Gate` tests fail (`gate.sh` does not exist) and the 9 lock tests pass.

- [ ] **Step 3: Write `system/nvidia/gate.sh`**

```bash
#!/usr/bin/env bash
# Build gate of the system image (docs/architecture/doc_system_image.md, S3, S6, S8): run on the
# finished image root before the UKI is assembled.
#   none           no NVIDIA module, kernel argument, modprobe option, dracut configuration
#                  or negativo17 repository
#   nvidia         modules, driver packages, shim and GSP firmware at NVIDIA_OPEN_VERSION,
#                  and the EGL, GBM and Vulkan files of the userspace
#   nvidia-legacy  the same at NVIDIA_LEGACY_VERSION, with the RPM Fusion packages, no GSP check
# Usage: gate.sh none|nvidia|nvidia-legacy PINS_ENV [ROOT]
set -euo pipefail

GPU=${1:?usage: gate.sh none|nvidia|nvidia-legacy PINS_ENV [ROOT]}
PINS=${2:?usage: gate.sh none|nvidia|nvidia-legacy PINS_ENV [ROOT]}
ROOT=${3:-/}
bad=0
violation() { echo "nvidia gate: $*" >&2; bad=1; }

mapfile -t modules < <(find "$ROOT/usr/lib/modules" -path '*/extra/nvidia/*' -name 'nvidia*.ko*' 2> /dev/null | sort)

if [[ $GPU == none ]]; then
  for ko in "${modules[@]}"; do violation "${ko#"$ROOT"}: NVIDIA module in the default image"; done
  while IFS= read -r f; do
    violation "${f#"$ROOT"}: NVIDIA configuration in the default image"
  # Word-bounded: Fedora's dist-blacklist.conf names the unrelated framebuffer driver nvidiafb.
  done < <(grep -rlE '(^|[^[:alnum:]_])nvidia([^[:alnum:]_]|$)' "$ROOT/usr/lib/bootc/kargs.d" "$ROOT/usr/lib/modprobe.d" "$ROOT/etc/modprobe.d" "$ROOT/usr/lib/dracut/dracut.conf.d" 2> /dev/null | sort)
  while IFS= read -r f; do
    violation "${f#"$ROOT"}: negativo17 repository in the default image"
  done < <(grep -rl 'negativo17' "$ROOT/etc/yum.repos.d" 2> /dev/null | sort)
  exit "$bad"
fi

case $GPU in
  nvidia) expected=$(sed -n 's/^NVIDIA_OPEN_VERSION=//p' "$PINS"); packages=(nvidia-driver nvidia-driver-libs nvidia-kmod-common azoth-nvidia-kmod) ;;
  nvidia-legacy) expected=$(sed -n 's/^NVIDIA_LEGACY_VERSION=//p' "$PINS"); packages=(xorg-x11-drv-nvidia xorg-x11-drv-nvidia-libs azoth-nvidia-kmod) ;;
  *) echo "gate.sh: unknown GPU $GPU" >&2; exit 2 ;;
esac
[[ -n $expected ]] || { echo "gate.sh: no NVIDIA version for $GPU in $PINS" >&2; exit 2; }

[[ ${#modules[@]} -gt 0 ]] || violation "no nvidia*.ko under /usr/lib/modules/*/extra/nvidia"
for ko in "${modules[@]}"; do
  got=$(modinfo -F version "$ko")
  [[ $got == "$expected" ]] || violation "${ko##*/}: module $got, pin $expected"
done
for pkg in "${packages[@]}"; do
  if got=$(rpm --root "$ROOT" -q --qf '%{VERSION}' "$pkg"); then
    [[ $got == "$expected" ]] || violation "$pkg: package $got, pin $expected"
  else
    violation "$pkg: not installed"
  fi
done
if [[ $GPU == nvidia ]]; then
  for fw in gsp_ga10x.bin gsp_tu10x.bin; do
    [[ -f $ROOT/usr/lib/firmware/nvidia/$expected/$fw ]] || violation "/usr/lib/firmware/nvidia/$expected/$fw missing"
  done
fi
for f in usr/share/glvnd/egl_vendor.d/10_nvidia.json usr/lib64/gbm/nvidia-drm_gbm.so; do
  [[ -e $ROOT/$f ]] || violation "/$f missing"
done
compgen -G "$ROOT/usr/share/vulkan/icd.d/nvidia_icd*.json" > /dev/null || violation "/usr/share/vulkan/icd.d/nvidia_icd*.json missing"
exit "$bad"
```

Run: `chmod 0755 system/nvidia/gate.sh && shellcheck -x system/nvidia/gate.sh`

Expected: no output.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -B -m unittest discover -s system/nvidia/tests -v`

Expected: `Ran 17 tests` … `OK`.

- [ ] **Step 5: Commit, open PR A and stop for consent**

```bash
git -C /var/home/hr-mes/athanor add system/nvidia/gate.sh system/nvidia/tests/test_gate.py
git -C /var/home/hr-mes/athanor commit -m "feat(system): gate the system images on NVIDIA content and version lock" -m "gate.sh fails a default image that carries NVIDIA modules, arguments or the negativo17 repository, and an NVIDIA image whose modules, driver packages, shim or GSP firmware differ from the pin or that lacks the EGL, GBM or Vulkan files (doc_system_image.md, S3, S6, S8)." -m "Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01EUnNXqv8jNWDVMA83G7eZ4"
```

The controller then asks the maintainer before pushing `system-image-variants`, opening PR A against `iso-v0` and merging it.

After the merge the Orchestrator rebuilds `athanor-base-config` into the tier 0 repository. The old Containerfile still copies the NVIDIA modules into `athanor-system`, so the maintainer's desktop, which runs with the `modprobe.blacklist` workaround, is unaffected. Once that Orchestrator run is green, verify: `skopeo inspect docker://ghcr.io/hr-mes/athanor-forge-tier0-repo:latest` is newer than the merge, and `rpm -qlp` on its `athanor-base-config` RPM lists no `nvidia` path.

---

## PR B — Containerfile, workflows and documentation (branch `system-image-build`, from `iso-v0` after PR A)

### Task 4: The multi-stage Containerfile and `build-image.sh`

**Files:**
- Modify: `system/Containerfile`
- Create: `system/build-image.sh`
- Modify: `forge/config/packages.json`: remove `"libva-nvidia-driver",` from `upstream_media`

**Interfaces:**
- Consumes: `system/nvidia/build-rpms.sh` and `system/nvidia/gate.sh` (PR A).
- Produces: `system/build-image.sh --gpu none|nvidia|nvidia-legacy --registry REG --tag TAG [--tag TAG2] [--push]`.
  - It builds `REG/<name>:TAG` with `<name>` = `athanor-system`, `athanor-system-nvidia` or `athanor-system-nvidia-legacy`.
  - It passes `SECUREBOOT_SIGNING_KEY` as the `uki_key` secret when set, and builds unsigned otherwise.
  - With `--push` it pushes every tag.
  - It prints `image: REG/<name>:<first tag>` as its last line.

- [ ] **Step 1: Restructure `system/Containerfile`**

Apply these edits to the current file:

1. **Replace the header.** Replace everything from the first line down to and including `FROM ghcr.io/hr-mes/ermete-base-nvidia:latest` with:

```dockerfile
# The Athanor system images (docs/architecture/doc_system_image.md). One file, three images
# selected by the GPU build argument: none (athanor-system), nvidia (athanor-system-nvidia)
# and nvidia-legacy (athanor-system-nvidia-legacy). Everything up to the `system` stage is
# shared; the GPU stages add the signed NVIDIA modules of the Azoth kernel with the locked
# vendor packages; the final stage gates, assembles the UKI and lints. AZOTH_NVR is passed by
# system/build-image.sh from forge/specs/azoth/nvr.sh.
ARG AZOTH_NVR
ARG GPU=none

FROM ghcr.io/hr-mes/azoth-nvidia:${AZOTH_NVR}-open AS nvidia-modules-open
FROM ghcr.io/hr-mes/azoth-nvidia:${AZOTH_NVR}-legacy AS nvidia-modules-legacy

# The vendor RPMs of both NVIDIA branches, verified by hash and GPG, with the shim and the
# configuration package (system/nvidia/build-rpms.sh). A throwaway stage: rpm-build never
# reaches an image.
FROM registry.fedoraproject.org/fedora:43@sha256:9b8b763ff01cc0e0fe8775fd3fa286c6b008a119013d178e00444fbcc04ae9f2 AS nvidia-rpms
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
COPY forge/specs/azoth/pins.env /src/forge/specs/azoth/pins.env
COPY system/nvidia/ /src/system/nvidia/
RUN dnf5 install -y --setopt=install_weak_deps=False rpm-build python3 && \
    bash /src/system/nvidia/build-rpms.sh /out

# Fedora's atomic desktop base (S1): the bootc base of Silverblue and Kinoite, pinned by
# digest and moved by the bump bot.
FROM quay.io/fedora-ostree-desktops/base-atomic:43@sha256:ead5f8bc4032ea4bc2f61d60f3101d6cc90f6c87bb405345a3d18b8b1651cd70 AS system
```

2. **Keep the SHELL line and the Tier 0 block unchanged.**

3. **Replace the NVIDIA module copy with a kernel check.** Replace:

```dockerfile
# The signed NVIDIA modules of the Azoth kernel; depmod runs in assemble_uki.sh. The
# test ties the modules to the kernel installed above: both come from the same NVR.
ARG AZOTH_NVR
COPY --from=nvidia-modules /lib/modules/ /usr/lib/modules/
RUN test -f "/usr/lib/modules/${AZOTH_NVR}.x86_64/vmlinuz" && \
    test -f "/usr/lib/modules/${AZOTH_NVR}.x86_64/extra/nvidia/nvidia.ko"
```

with:

```dockerfile
# The Azoth kernel of the pins is the one tier 0 installed.
ARG AZOTH_NVR
RUN test -f "/usr/lib/modules/${AZOTH_NVR}.x86_64/vmlinuz"
```

4. **Insert the GPU stages and the final stage.** Keep everything from `# TIER 1` down to and including the `# Declarative Systemd presets & sysusers` RUN unchanged. Immediately after that RUN, and before `# Initramfs & Unified Kernel Image (UKI) generation`, insert:

```dockerfile
# GPU stages (S2-S5): the signed modules of the kernel NVR with the locked vendor packages of
# the same version, the shim and athanor-nvidia-config. libva-nvidia-driver (VA-API on NVDEC)
# only makes sense with the NVIDIA driver.
FROM system AS gpu-none

FROM system AS gpu-nvidia
COPY --from=nvidia-modules-open /lib/modules/ /usr/lib/modules/
COPY --from=nvidia-rpms /out/open/ /tmp/nvidia-rpms/
RUN --mount=type=cache,dst=/var/cache --mount=type=cache,dst=/var/cache/libdnf5 \
    dnf5 install -y --setopt=install_weak_deps=False --setopt=tsflags=nodocs /tmp/nvidia-rpms/*.rpm libva-nvidia-driver && \
    rm -rf /tmp/nvidia-rpms && systemctl preset-all

FROM system AS gpu-nvidia-legacy
COPY --from=nvidia-modules-legacy /lib/modules/ /usr/lib/modules/
COPY --from=nvidia-rpms /out/legacy/ /tmp/nvidia-rpms/
RUN --mount=type=cache,dst=/var/cache --mount=type=cache,dst=/var/cache/libdnf5 \
    dnf5 install -y --setopt=install_weak_deps=False --setopt=tsflags=nodocs /tmp/nvidia-rpms/*.rpm libva-nvidia-driver && \
    rm -rf /tmp/nvidia-rpms && systemctl preset-all

FROM gpu-${GPU} AS final
ARG GPU
COPY forge/specs/azoth/pins.env /scripts/pins.env
COPY system/nvidia/gate.sh /scripts/nvidia-gate.sh
RUN bash /scripts/nvidia-gate.sh "${GPU}" /scripts/pins.env /
```

5. **Keep the rest unchanged.** The UKI generation, hardening (which already removes `/scripts`) and lint stay as they are, now in the `final` stage.

Run: `grep -nE '^(FROM|ARG) ' system/Containerfile`

Expected, in this order:
- `ARG AZOTH_NVR`, `ARG GPU=none`;
- the four `FROM … AS nvidia-modules-open|nvidia-modules-legacy|nvidia-rpms|system` lines;
- the `ARG AZOTH_NVR` of the kernel check;
- `FROM system AS gpu-none`, `gpu-nvidia`, `gpu-nvidia-legacy`;
- `FROM gpu-${GPU} AS final`, `ARG GPU`.

- [ ] **Step 2: Write `system/build-image.sh`**

```bash
#!/usr/bin/env bash
# Builds one Athanor system image (docs/architecture/doc_system_image.md, S2, S8) from
# system/Containerfile, in CI and locally.
# Usage: build-image.sh --gpu none|nvidia|nvidia-legacy --registry REG --tag TAG [--tag TAG]... [--push]
# SECUREBOOT_SIGNING_KEY in the environment signs the UKI (release); without it the UKI is
# unsigned (pull-request check, local rehearsal).
set -euo pipefail

usage() { echo "usage: ${0##*/} --gpu none|nvidia|nvidia-legacy --registry REG --tag TAG [--tag TAG]... [--push]" >&2; exit 2; }
GPU='' REGISTRY='' PUSH=false TAGS=()
while [[ $# -gt 0 ]]; do
  case $1 in
    --gpu) GPU=${2:?}; shift 2 ;;
    --registry) REGISTRY=${2:?}; shift 2 ;;
    --tag) TAGS+=("${2:?}"); shift 2 ;;
    --push) PUSH=true; shift ;;
    *) usage ;;
  esac
done
case $GPU in
  none) NAME=athanor-system ;;
  nvidia) NAME=athanor-system-nvidia ;;
  nvidia-legacy) NAME=athanor-system-nvidia-legacy ;;
  *) usage ;;
esac
[[ -n $REGISTRY && ${#TAGS[@]} -gt 0 ]] || usage

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
args=(--layers --format docker --build-arg "AZOTH_NVR=$(bash "$ROOT/forge/specs/azoth/nvr.sh")" --build-arg "GPU=$GPU")
if [[ -n ${SECUREBOOT_SIGNING_KEY:-} ]]; then
  # The Secure Boot key and its certificate reach assemble_uki.sh as build secrets: never a layer.
  args+=(--secret "id=uki_key,env=SECUREBOOT_SIGNING_KEY" --secret "id=uki_cert,src=$ROOT/forge/specs/azoth/keys/secureboot/athanor-secureboot.pem")
fi
for tag in "${TAGS[@]}"; do args+=(-t "$REGISTRY/$NAME:$tag"); done
# docker format: the OCI format has no SHELL instruction and podman would drop the
# bash -o pipefail the Containerfile sets for every RUN.
podman build "${args[@]}" -f "$ROOT/system/Containerfile" "$ROOT"
if [[ $PUSH == true ]]; then
  for tag in "${TAGS[@]}"; do bash "$ROOT/forge/scripts/retry.sh" podman push "$REGISTRY/$NAME:$tag"; done
fi
echo "image: $REGISTRY/$NAME:${TAGS[0]}"
```

Run: `chmod 0755 system/build-image.sh && shellcheck -x system/build-image.sh && bash system/build-image.sh --gpu bogus --registry r --tag t; echo "exit $?"`

Expected: the usage line and `exit 2`.

- [ ] **Step 3: Rehearse the stages that do not need base-atomic**

Run with the sandbox disabled:

```bash
podman build --format docker --target nvidia-rpms -t localhost/nvidia-rpms-check -f system/Containerfile . 2>&1 | tail -4
```

Expected: the last lines include `build-rpms.sh: open 610.57.04: 10 RPMs` and `build-rpms.sh: legacy 580.178.04: 9 RPMs`, then a successful commit of the image. Remove it with `podman rmi localhost/nvidia-rpms-check`.

- [ ] **Step 4: Update `packages.json` and commit**

Remove `"libva-nvidia-driver",` from `upstream_media`. Then:

Run: `python3 -B -c 'import json; d=json.load(open("forge/config/packages.json")); assert "libva-nvidia-driver" not in d["upstream_media"]; print("ok")'`

Expected: `ok`

```bash
git -C /var/home/hr-mes/athanor add system/Containerfile system/build-image.sh forge/config/packages.json
git -C /var/home/hr-mes/athanor commit -m "feat(system): build the default and NVIDIA images from Fedora's atomic base" -m "One Containerfile, three images: base-atomic:43 pinned by digest, a throwaway stage that assembles the verified NVIDIA RPMs, a GPU stage per variant with the signed modules of the kernel NVR, and a final stage that gates the result before the UKI is assembled (doc_system_image.md, S1-S6). build-image.sh builds one of them, signed in release and unsigned for checks." -m "Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01EUnNXqv8jNWDVMA83G7eZ4"
```

---

### Task 5: Release workflow and pull-request check

**Files:**
- Modify: `.github/workflows/call-system-image.yml` (job `dag-system-image`)
- Create: `.github/workflows/system-image-check.yml`, `system/package-delta.sh`

**Interfaces:**
- Consumes: `system/build-image.sh` (Task 4).
- Produces:
  - `system/package-delta.sh OLD_IMAGE NEW_IMAGE` prints a Markdown section with the package names lost and gained.
  - The release job publishes `athanor-system`, `athanor-system-nvidia` and `athanor-system-nvidia-legacy`, each with `:<run_id>` and `:latest`, each signed and attested.

- [ ] **Step 1: Write `system/package-delta.sh`**

```bash
#!/usr/bin/env bash
# The package names an image loses and gains against another (doc_system_image.md, section 4):
# the review of a base change. Usage: package-delta.sh OLD_IMAGE NEW_IMAGE
set -euo pipefail
OLD=${1:?usage: package-delta.sh OLD_IMAGE NEW_IMAGE}
NEW=${2:?usage: package-delta.sh OLD_IMAGE NEW_IMAGE}
names() { podman run --rm --network none --entrypoint /usr/bin/rpm "$1" -qa --qf '%{NAME}\n' | sort -u; }
names "$OLD" > old.names
names "$NEW" > new.names
lost=$(comm -23 old.names new.names)
gained=$(comm -13 old.names new.names)
echo "### Package delta: \`$OLD\` → \`$NEW\`"
echo
count() { awk 'NF' <<< "$1" | wc -l; }
echo "Lost ($(count "$lost")):"
[[ -z $lost ]] || printf '```\n%s\n```\n' "$lost"
echo "Gained ($(count "$gained")):"
[[ -z $gained ]] || printf '```\n%s\n```\n' "$gained"
rm -f old.names new.names
```

Run: `shellcheck -x system/package-delta.sh`

Expected: no output.

- [ ] **Step 2: Make the release job build all three images**

In `call-system-image.yml`, job `dag-system-image`:
- Set `timeout-minutes: 180`.
- In "⚙️ Prepare environment", keep `IMAGE_REGISTRY` and `DEFAULT_TAG`, and remove `IMAGE_NAME`.
- Replace the whole `run:` of "🐳 Build OS Image" with:

```yaml
        run: |
          set -euo pipefail
          [[ -n ${SECUREBOOT_SIGNING_KEY:-} ]] || { echo "SECUREBOOT_SIGNING_KEY is not available to this job: check the signing environment" >&2; exit 1; }
          for gpu in none nvidia nvidia-legacy; do
            bash system/build-image.sh --gpu "$gpu" --registry "${IMAGE_REGISTRY}" --tag "${RUN_ID}" --tag "${DEFAULT_TAG}" --push
          done
```

- Replace the `run:` of "🔐 Sign & Attest OS Image (Zero-Trust Keyless Sigstore)" with:

```yaml
        run: |
          set -euo pipefail
          nix run nixpkgs#cosign -- login ghcr.io -u "${GITHUB_ACTOR}" -p "${GITHUB_TOKEN}"
          for name in athanor-system athanor-system-nvidia athanor-system-nvidia-legacy; do
            image="${IMAGE_REGISTRY}/${name}:${RUN_ID}"
            nix shell nixpkgs#syft -c bash forge/scripts/sbom_rootfs.sh "${image}" "${name}-sbom.spdx.json"
            nix shell nixpkgs#cosign -c bash forge/scripts/sign_attest.sh "${image}" "${name}-sbom.spdx.json"
          done
```

- In "💿 Build ISO (osbuild)", replace `"${IMAGE_REGISTRY}/${IMAGE_NAME}:${RUN_ID}"` with `"${IMAGE_REGISTRY}/athanor-system:${RUN_ID}"`.

All three images are built in the one job that holds the `signing` environment, so a cycle needs exactly one approval (S8).

- [ ] **Step 3: Write `.github/workflows/system-image-check.yml`**

```yaml
name: System Image Check

# Pull requests that change the system images build all three unsigned on the self-hosted
# runner, without pushing, and report the package delta of the default image against the
# published athanor-system (docs/architecture/doc_system_image.md, S2, S8, section 4). The
# gates of system/nvidia/gate.sh run inside the builds.

on:
  pull_request:
    paths:
      - system/**
      - forge/config/packages.json
      - forge/specs/athanor-base-config/**
      - .github/workflows/system-image-check.yml

permissions:
  contents: read
  packages: read

concurrency:
  group: system-image-check-${{ github.event.pull_request.number }}
  cancel-in-progress: true

jobs:
  build:
    # The self-hosted runner executes only code of this repository: a pull request from a
    # fork never reaches it.
    if: ${{ github.event.pull_request.head.repo.full_name == github.repository }}
    runs-on: self-hosted
    timeout-minutes: 300
    steps:
      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262

      - name: Build the three images (unsigned)
        run: |
          set -euo pipefail
          for gpu in none nvidia nvidia-legacy; do
            bash system/build-image.sh --gpu "$gpu" --registry localhost --tag check
          done

      - name: Package delta of the default image
        run: bash system/package-delta.sh ghcr.io/hr-mes/athanor-system:latest localhost/athanor-system:check >> "$GITHUB_STEP_SUMMARY"
```

- [ ] **Step 4: Lint**

Run: `actionlint .github/workflows/call-system-image.yml .github/workflows/system-image-check.yml && python3 -B scripts/verify.py workflows 2>&1 | grep -E "call-system-image|system-image-check"`

Expected: actionlint prints nothing, and the grep prints nothing.

- [ ] **Step 5: Commit**

```bash
git -C /var/home/hr-mes/athanor add .github/workflows/call-system-image.yml .github/workflows/system-image-check.yml system/package-delta.sh
git -C /var/home/hr-mes/athanor commit -m "ci(system): publish the default and NVIDIA images and check them on pull requests" -m "The signing job builds, pushes, signs and attests athanor-system, athanor-system-nvidia and athanor-system-nvidia-legacy, so one approval covers the cycle; the ISO stays on the default image. system-image-check.yml builds the three unsigned on the self-hosted runner and reports the package delta against the published default image (doc_system_image.md, S8)." -m "Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01EUnNXqv8jNWDVMA83G7eZ4"
```

---

### Task 6: Documentation owed by the spec

**Files:**
- Modify: `docs/architecture/doc_kernel_build.md` (section 10 and section 13, Italian)
- Modify: `docs/architecture/doc_kernel_profile.md` (the NVIDIA sentence of section 6 and the base-configuration note of section 14)
- Modify: `NEXT.md` (the references to `ermete-base-nvidia`)
- Modify: `docs/architecture/doc_system_image.md` (Status line)

**Interfaces:**
- Consumes: the names from Tasks 1–5.
- Produces: documentation only.

- [ ] **Step 1: `doc_kernel_build.md` section 10**

Replace:

```markdown
Pubblicazione `azoth-nvidia:<kernel-nvr>-<driver>`; le varianti
dell'immagine (`-nvidia`, `-nvidia-legacy`) le consumano.
```

with:

```markdown
Pubblicazione `azoth-nvidia:<kernel-nvr>-<driver>`; le immagini
`athanor-system-nvidia` e `athanor-system-nvidia-legacy` le consumano insieme al firmware e
allo userspace NVIDIA della stessa versione, bloccati per hash in
`system/nvidia/locks/` (docs/architecture/doc_system_image.md, S4-S7). L'immagine
predefinita `athanor-system` non porta moduli NVIDIA.
```

- [ ] **Step 2: `doc_kernel_build.md` section 13**

After the last numbered item, add:

```markdown
7. (2026-09-16) Immagini di sistema: base `base-atomic:43` di Fedora al posto di
   `ermete-base-nvidia`, immagine predefinita con `nouveau` e NVK, varianti
   `athanor-system-nvidia` (pacchetti negativo17) e `athanor-system-nvidia-legacy` (RPM
   Fusion) alla versione esatta dei moduli firmati, con gate e lock per hash
   (docs/architecture/doc_system_image.md).
```

- [ ] **Step 3: `doc_kernel_profile.md`**

Replace `NVIDIA parameters and dracut configuration move out of the base: they apply only where an
NVIDIA GPU is detected.` with `NVIDIA parameters and dracut configuration move out of the base: they apply only in the NVIDIA image variants (doc_system_image.md, S4 and S5).`

Replace `` `athanor-base-config` also ships NVIDIA dracut and
  kargs configuration to every machine (section 6), `` with `` the NVIDIA dracut and kargs configuration moved to `athanor-nvidia-config`, installed only by the NVIDIA image variants (doc_system_image.md, S4), ``.

- [ ] **Step 4: `NEXT.md` and the spec status**

In `NEXT.md`, replace every mention of `ermete-base-nvidia` as the current base with `quay.io/fedora-ostree-desktops/base-atomic:43 (docs/architecture/doc_system_image.md)`. Leave historical log entries that describe what happened in the past untouched.

In `doc_system_image.md`, change the Status line to `Status: **approved by the maintainer on 2026-09-16; implemented by docs/superpowers/plans/2026-09-16-system-image-variants.md**.`, keeping the rest of the paragraph.

Run: `python3 -B scripts/verify.py docs 2>&1 | grep -E "doc_kernel_build|doc_kernel_profile|doc_system_image|NEXT.md"`

Expected: no output.

- [ ] **Step 5: Commit, open PR B and stop for consent**

```bash
git -C /var/home/hr-mes/athanor add docs/architecture NEXT.md
git -C /var/home/hr-mes/athanor commit -m "docs(system): align the kernel specs with the system image variants" -m "Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01EUnNXqv8jNWDVMA83G7eZ4"
```

With the maintainer's consent, the controller pushes `system-image-build` and opens PR B against `iso-v0`. The PR must show:
- `System Image Check` green, with all three builds passing their gates;
- the package delta in the job summary, which the maintainer reviews: every lost package is either intended or goes into a fix commit on this branch;
- `Kernel gate` green.

---

## PR C — bump bot (branch `system-image-bump`, from `iso-v0` after PR B)

### Task 7: Base digest, NVIDIA availability and lock regeneration in the bump

**Files:**
- Modify: `forge/specs/azoth/bump.py`
- Modify: `.github/workflows/kernel-bump.yml` (the `bump-pins` artifact paths and the `git add` of the `pr` job)
- Create: `forge/specs/azoth/tests/test_bump_nvidia.py`

**Interfaces:**
- Consumes: `system/nvidia/lock.py` `main(["check"|"generate", …])` (Task 1).
- Produces:
  - `bump.py` moves the digests of the pinned `FROM` lines in `system/Containerfile` too;
  - it raises an NVIDIA version only when `lock.py check` passes for it, and otherwise records a note in the PR body;
  - `apply` regenerates the lock of every NVIDIA branch whose version moved.

- [ ] **Step 1: Write the failing test**

```python
"""Unit test of the NVIDIA availability rule of bump.py (python3 -B -m unittest discover -s forge/specs/azoth/tests -v)."""

import pathlib
import sys
import unittest

AZOTH = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AZOTH))
import bump  # noqa: E402


class NvidiaAvailability(unittest.TestCase):
    def test_version_not_packaged_keeps_the_pin_and_notes_why(self):
        notes = []
        got = bump.packaged_or_current("open", "615.71.09", "610.57.04", notes, check=lambda branch, version: False)
        self.assertEqual(got, "610.57.04")
        self.assertTrue(any("615.71.09" in n and "open" in n for n in notes))

    def test_packaged_version_moves(self):
        notes = []
        got = bump.packaged_or_current("legacy", "580.190.01", "580.178.04", notes, check=lambda branch, version: True)
        self.assertEqual(got, "580.190.01")
        self.assertEqual(notes, [])

    def test_system_containerfile_is_tracked(self):
        self.assertIn(AZOTH.parents[2] / "system" / "Containerfile", bump.CONTAINERFILES)


if __name__ == "__main__":
    unittest.main()
```

Run: `python3 -B -m unittest discover -s forge/specs/azoth/tests -v`

Expected: FAIL with `AttributeError: module 'bump' has no attribute 'packaged_or_current'`.

- [ ] **Step 2: Implement in `bump.py`**

Replace:

```python
CONTAINERFILES = [HERE / d / "Containerfile" for d in ("builder", "boot", "nvidia")]
```

with:

```python
# The kernel's Containerfiles and the system image (docs/architecture/doc_system_image.md, S1):
# every FROM pinned by digest moves in the same bump.
CONTAINERFILES = [HERE / d / "Containerfile" for d in ("builder", "boot", "nvidia")] + [HERE.parents[2] / "system" / "Containerfile"]
NVIDIA_LOCK = HERE.parents[2] / "system" / "nvidia" / "lock.py"
```

Add after `nvidia_legacy`:

```python
def lock_check(branch, version):
    """True when the branch's driver repository publishes every locked package at version."""
    return subprocess.run([sys.executable, "-B", str(NVIDIA_LOCK), "check", branch, "--version", version], capture_output=True).returncode == 0


def packaged_or_current(branch, candidate, current, notes, check=lock_check):
    """The candidate NVIDIA version if its driver packages exist (doc_system_image.md, S7), else the current pin."""
    if candidate == current or check(branch, candidate):
        return candidate
    notes.append(f"NVIDIA {branch} {candidate} is tagged upstream but its driver packages are not published yet: the pin stays at {current}")
    return current
```

Add `import subprocess` to the imports if missing.

In `compute()`, replace:

```python
    open_version, open_commit = nvidia_open(pins["NVIDIA_OPEN_VERSION"])
    if open_version != pins["NVIDIA_OPEN_VERSION"]:
```

with:

```python
    open_version, open_commit = nvidia_open(pins["NVIDIA_OPEN_VERSION"])
    open_version = packaged_or_current("open", open_version, pins["NVIDIA_OPEN_VERSION"], notes)
    if open_version != pins["NVIDIA_OPEN_VERSION"]:
```

and replace:

```python
    legacy_version = nvidia_legacy(pins["NVIDIA_LEGACY_VERSION"])
```

with:

```python
    legacy_version = packaged_or_current("legacy", nvidia_legacy(pins["NVIDIA_LEGACY_VERSION"]), pins["NVIDIA_LEGACY_VERSION"], notes)
```

The `NVIDIA_OPEN_COMMIT` assignment inside the `if` keeps using the `open_commit` of the tag. When `packaged_or_current` returns the current version the `if` is false, so the commit is not touched.

At the end of `apply(result)`, before the `KERNEL.md` update, add:

```python
    for key, branch in (("NVIDIA_OPEN_VERSION", "open"), ("NVIDIA_LEGACY_VERSION", "legacy")):
        if key in result["new"]:
            done = subprocess.run([sys.executable, "-B", str(NVIDIA_LOCK), "generate", branch, "--version", result["new"][key]])
            if done.returncode != 0:
                sys.exit(f"lock.py generate {branch} {result['new'][key]} failed")
```

Run: `python3 -B -m unittest discover -s forge/specs/azoth/tests -v`

Expected: `Ran 3 tests` … `OK`.

- [ ] **Step 3: Carry the new files through `kernel-bump.yml`**

In the `check` job's `bump-pins` upload, add to `path`:

```yaml
            system/Containerfile
            system/nvidia/locks/open.lock
            system/nvidia/locks/legacy.lock
```

In the `pr` job, replace `git add forge/specs/azoth` with `git add forge/specs/azoth system/Containerfile system/nvidia/locks`.

In the `check` job's `Run bump.py apply` step, replace:

```bash
[[ -z $(git status --porcelain -- forge/specs/azoth) ]] || changed=true
```

with:

```bash
[[ -z $(git status --porcelain -- forge/specs/azoth system/Containerfile system/nvidia/locks) ]] || changed=true
```

Run: `actionlint .github/workflows/kernel-bump.yml && python3 -B forge/specs/azoth/bump.py check | head -30`

Expected:
- actionlint is clean;
- `bump.py check` runs against the live sources (sandbox disabled) and prints its JSON;
- if `quay.io/fedora-ostree-desktops/base-atomic:43` moved since Task 4, its digest appears under `images`;
- no traceback.

- [ ] **Step 4: Commit, open PR C and stop for consent**

```bash
git -C /var/home/hr-mes/athanor add forge/specs/azoth/bump.py forge/specs/azoth/tests/test_bump_nvidia.py .github/workflows/kernel-bump.yml
git -C /var/home/hr-mes/athanor commit -m "feat(kernel-bump): move the system base and the NVIDIA locks with the pins" -m "The bump now tracks the digest of system/Containerfile, raises an NVIDIA version only when negativo17 (open) or RPM Fusion (legacy) publishes its driver packages, and regenerates the matching lock (doc_system_image.md, S1, S7)." -m "Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01EUnNXqv8jNWDVMA83G7eZ4"
```

---

## Task 8: Ship and migrate the maintainer's desktop

**Files:** none. Every step is outward and needs the maintainer's consent.

- [ ] **Step 1: Merge PR B and publish.**
  1. After the maintainer approves the package delta, rebase-merge PR B.
  2. The Orchestrator run on `iso-v0` builds the three images in the signing job; the maintainer approves the `signing` environment once.
  3. Verify:

     ```bash
     for n in athanor-system athanor-system-nvidia athanor-system-nvidia-legacy; do skopeo inspect --no-tags docker://ghcr.io/hr-mes/$n:latest | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["Name"], d["Created"])'; done
     ```

     Expected: three images created by that run.
  4. For each image, `cosign verify` and `verify-attestation` pass (`forge/scripts/sign_attest.sh` already runs them in the job; the job log shows it).
- [ ] **Step 2: ISO acceptance.** The default ISO of that run passes `iso-acceptance.yml` (weekly or dispatched) with `kernel profile holds: profile-ok`.
- [ ] **Step 3: Migrate the desktop.** The maintainer runs, in a real terminal:

  ```bash
  sudo rpm-ostree kargs --delete=modprobe.blacklist=nvidia,nvidia_drm,nvidia_modeset,nvidia_uvm,nvidia_peermem
  sudo bootc switch ghcr.io/hr-mes/athanor-system-nvidia:latest
  ```

  Then they reboot at their chosen time. The first command applies only if the workaround was installed; if it reports that the argument is not present, go on.
- [ ] **Step 4: Hardware check (spec section 6, item 3).** After the reboot:

  ```bash
  ls -l /dev/dri/ /dev/dri/by-path/
  nvidia-smi -L
  modinfo -F signer nvidia
  for c in /sys/class/drm/card*-*; do echo "$(basename $c) $(cat $c/status) $(head -1 $c/modes 2>/dev/null)"; done
  journalctl --user -b | grep -c "eglInitialize"
  athanor-profile-check
  ```

  Expected:
  - one `card` and one `renderD` node per NVIDIA GPU, with by-path entries naming `0000:04:00.0` and `0000:08:00.0`;
  - `nvidia-smi` lists the RTX 3060 and the RTX 4070 Ti SUPER;
  - the signer names the module signing key;
  - connected outputs at native modes;
  - `0` EGL initialisation errors;
  - `base: 25/25 settings hold`.
- [ ] **Step 5: Close the key rotation.** With the maintainer's consent: `gh secret delete MOK_PRIVATE_KEY --env signing --repo hr-mes/athanor`, then record the outcome in the project memory.

---

## Self-Review

1. **Spec coverage:**
   - S1 → Task 4 (FROM digest), Task 7 (bump);
   - S2 → Task 4 (stages, `build-image.sh` names);
   - S3 → Task 2 (base-config cleanup), Task 3 (`none` gate);
   - S4, S5 → Task 1 (package lists and locks), Task 2 (shim, config, closure test), Task 4 (GPU stages);
   - S6 → Task 3, run in Task 4's final stage;
   - S7 → Task 1 (hashes), Task 2 (GPG with vendored keys), Task 7 (availability and regeneration);
   - S8 → Task 5 (one signing job, ISO on default, PR check with the file checks), Task 8 (hardware check);
   - Spec section 4 package delta → Task 5 (`package-delta.sh`, reviewed on PR B);
   - Spec section 7 migration → Task 8;
   - Spec section 8 document changes → Task 6.
2. **Placeholder scan.** Task 2 Steps 1 and 3 decide file moves from a command's output, with an explicit rule (a vendor-owned file is deleted, not moved). No other open choices remain. The hosted runner's disk space for three images in one job is a known risk: if the release job fails on space, prune the pushed tags of the previous GPU before the next build in the same loop (`podman rmi` of its two tags), since the shared stages stay in cache.
3. **Type consistency:**
   - GPU values `none|nvidia|nvidia-legacy` are shared by `gate.sh`, `build-image.sh` and the Containerfile `GPU` argument and stage names `gpu-${GPU}`;
   - branch names `open|legacy` are shared by `lock.py`, `build-rpms.sh` (`/out/open`, `/out/legacy`) and `bump.py`'s `packaged_or_current`;
   - lock paths are `system/nvidia/locks/<branch>.lock` everywhere;
   - the signature of `write_lock(path, branch, version, baseurl, entries)` matches its tests.
