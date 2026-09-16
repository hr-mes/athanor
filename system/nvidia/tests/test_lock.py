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
