"""Unit tests of system/kernel-artifacts.sh against an offline registry
(python3 -B -m unittest discover -s system/tests -v)."""

import json
import os
import pathlib
import re
import subprocess
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SCRIPT = ROOT / "system" / "kernel-artifacts.sh"
PINS = dict(re.findall(r"^(\w+)=(.*)$", (ROOT / "forge/specs/azoth/pins.env").read_text(), re.M))
NVR = subprocess.run(["bash", str(ROOT / "forge/specs/azoth/nvr.sh")], capture_output=True, text=True, check=True).stdout.strip()
REG = "ghcr.io/hr-mes"
KERNEL = "sha256:" + "1" * 64
DEVEL = "sha256:" + "2" * 64
OTHER_KERNEL = "sha256:" + "9" * 64
MODULE = {"open": "sha256:" + "3" * 64, "legacy": "sha256:" + "4" * 64}
KERNEL_BUILD = "https://github.com/hr-mes/athanor/.github/workflows/kernel-build.yml@refs/heads/iso-v0"
KMOD = "https://github.com/hr-mes/athanor/.github/workflows/nvidia-kmod.yml@refs/heads/iso-v0"


def tag(branch, kernel=KERNEL):
    return f"{NVR}-k{kernel[7:19]}-{branch}-{PINS[f'NVIDIA_{branch.upper()}_VERSION']}"


def predicate(branch, kernel=KERNEL):
    return {"driver": branch, "version": PINS[f"NVIDIA_{branch.upper()}_VERSION"], "kernel": f"{NVR}.x86_64",
            "kernel_digest": kernel, "devel_digest": DEVEL,
            "pins": {k: v for k, v in PINS.items() if k.startswith("NVIDIA_")}}


def published(branches=("open", "legacy")):
    """A registry holding the signed kernel of the pins and the attested modules of BRANCHES."""
    fx = {
        "tags": {f"{REG}/azoth:{NVR}": KERNEL, f"{REG}/azoth-devel:{NVR}": DEVEL},
        "signatures": {f"{REG}/azoth@{KERNEL}": KERNEL_BUILD, f"{REG}/azoth-devel@{DEVEL}": KERNEL_BUILD},
        "attestations": {},
        "errors": [],
    }
    for branch in branches:
        ref = f"{REG}/azoth-nvidia@{MODULE[branch]}"
        fx["tags"][f"{REG}/azoth-nvidia:{tag(branch)}"] = MODULE[branch]
        fx["signatures"][ref] = KMOD
        fx["attestations"][ref] = [{"identity": KMOD, "predicate": predicate(branch)}]
    return fx


class Tool(unittest.TestCase):
    """A temporary directory with the fakes on PATH, the artifacts directory and a git identity."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self.tmp.name)
        bin_dir = self.dir / "bin"
        bin_dir.mkdir()
        for tool in ("skopeo", "cosign", "gh"):
            (bin_dir / tool).symlink_to(HERE / "fake_registry.py")
        self.artifacts = self.dir / "artifacts"
        self.env = {
            "PATH": f"{bin_dir}:{os.environ['PATH']}", "HOME": str(self.dir), "RETRY_ATTEMPTS": "1",
            "KERNEL_ARTIFACTS_DIR": str(self.artifacts), "FAKE_REGISTRY": str(self.dir / "registry.json"),
            "FAKE_LOG": str(self.dir / "calls.log"), "GITHUB_REPOSITORY_OWNER": "hr-mes",
            "GITHUB_REPOSITORY": "hr-mes/athanor", "GITHUB_SERVER_URL": "https://github.com",
            "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
        }
        self.registry({})

    def tearDown(self):
        self.tmp.cleanup()

    def registry(self, fx):
        (self.dir / "registry.json").write_text(json.dumps(fx))

    def run_script(self, *args, cwd=None):
        return subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True, env=self.env, cwd=cwd or self.dir)

    def state_file(self):
        path = self.artifacts / "kernel-artifacts.env"
        return dict(line.split("=", 1) for line in path.read_text().splitlines()) if path.exists() else None


class Resolve(Tool):
    def test_ready_records_every_digest_and_the_tag_form(self):
        self.registry(published())
        r = self.run_script("resolve")
        self.assertEqual(r.returncode, 0, r.stderr)
        got = self.state_file()
        self.assertEqual(got["state"], "ready")
        self.assertEqual((got["kernel_digest"], got["devel_digest"]), (KERNEL, DEVEL))
        self.assertEqual((got["nvidia_open_digest"], got["nvidia_legacy_digest"]), (MODULE["open"], MODULE["legacy"]))
        self.assertEqual(got["nvidia_open_tag"], f"{NVR}-k{'1' * 12}-open-{PINS['NVIDIA_OPEN_VERSION']}")

    def test_missing_module_tag_is_modules_missing(self):
        self.registry(published(branches=("open",)))
        r = self.run_script("resolve")
        self.assertEqual(r.returncode, 0, r.stderr)
        got = self.state_file()
        self.assertEqual(got["state"], "modules-missing")
        self.assertEqual(got["nvidia_open_digest"], MODULE["open"])
        self.assertNotIn("nvidia_legacy_digest", got)
        self.assertEqual(got["nvidia_legacy_tag"], tag("legacy"))

    def test_absent_kernel_is_kernel_missing(self):
        fx = published()
        del fx["tags"][f"{REG}/azoth:{NVR}"]
        self.registry(fx)
        r = self.run_script("resolve")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.state_file(), {"state": "kernel-missing", "nvr": NVR, "registry": REG})

    def test_unsigned_kernel_is_kernel_missing(self):
        fx = published()
        del fx["signatures"][f"{REG}/azoth@{KERNEL}"]
        self.registry(fx)
        r = self.run_script("resolve")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.state_file()["state"], "kernel-missing")

    def test_absent_devel_is_kernel_missing(self):
        fx = published()
        del fx["tags"][f"{REG}/azoth-devel:{NVR}"]
        self.registry(fx)
        r = self.run_script("resolve")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.state_file()["state"], "kernel-missing")

    def test_unsigned_devel_is_kernel_missing(self):
        fx = published()
        del fx["signatures"][f"{REG}/azoth-devel@{DEVEL}"]
        self.registry(fx)
        r = self.run_script("resolve")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.state_file()["state"], "kernel-missing")

    def test_kernel_tag_transport_error_fails(self):
        fx = published()
        fx["errors"].append(f"{REG}/azoth:{NVR}")
        self.registry(fx)
        r = self.run_script("resolve")
        self.assertEqual(r.returncode, 1)
        self.assertIn("i/o timeout", r.stderr)
        self.assertIsNone(self.state_file())

    def test_transient_signature_error_is_not_folded_into_unsigned(self):
        fx = published()
        fx["signature_transient_errors"] = [f"{REG}/azoth@{KERNEL}"]
        self.registry(fx)
        r = self.run_script("resolve")
        self.assertEqual(r.returncode, 1)
        self.assertIn("502 Bad Gateway", r.stderr)
        self.assertIsNone(self.state_file())

    def test_registry_error_fails_and_leaves_no_file(self):
        self.registry(published())
        self.assertEqual(self.run_script("resolve").returncode, 0)
        fx = published()
        fx["errors"].append(f"{REG}/azoth-nvidia:{tag('legacy')}")
        self.registry(fx)
        r = self.run_script("resolve")
        self.assertEqual(r.returncode, 1)
        self.assertIn("i/o timeout", r.stderr)
        self.assertIsNone(self.state_file())

    def test_rekor_error_fails(self):
        fx = published()
        fx["errors"].append(f"{REG}/azoth-nvidia@{MODULE['open']}")
        self.registry(fx)
        r = self.run_script("resolve")
        self.assertEqual(r.returncode, 1)
        self.assertIn("502 Bad Gateway", r.stderr)
        self.assertIsNone(self.state_file())

    def test_unsigned_module_tag_is_modules_missing(self):
        fx = published()
        del fx["signatures"][f"{REG}/azoth-nvidia@{MODULE['legacy']}"]
        self.registry(fx)
        r = self.run_script("resolve")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.state_file()["state"], "modules-missing")
        self.assertNotIn("nvidia_legacy_digest", self.state_file())

    def test_module_signed_by_another_workflow_is_modules_missing(self):
        fx = published()
        ref = f"{REG}/azoth-nvidia@{MODULE['open']}"
        fx["signatures"][ref] = KERNEL_BUILD
        fx["attestations"][ref] = [{"identity": KERNEL_BUILD, "predicate": predicate("open")}]
        self.registry(fx)
        r = self.run_script("resolve")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.state_file()["state"], "modules-missing")
        self.assertNotIn("nvidia_open_digest", self.state_file())

    def test_module_signed_without_attestation_is_modules_missing(self):
        fx = published()
        ref = f"{REG}/azoth-nvidia@{MODULE['open']}"
        fx["attestations"][ref] = []
        self.registry(fx)
        r = self.run_script("resolve")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.state_file()["state"], "modules-missing")
        self.assertNotIn("nvidia_open_digest", self.state_file())

    def test_attestation_for_wrong_driver_is_modules_missing(self):
        fx = published()
        ref = f"{REG}/azoth-nvidia@{MODULE['open']}"
        wrong = predicate("open")
        wrong["driver"] = "legacy"
        fx["attestations"][ref] = [{"identity": KMOD, "predicate": wrong}]
        self.registry(fx)
        r = self.run_script("resolve")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.state_file()["state"], "modules-missing")
        self.assertNotIn("nvidia_open_digest", self.state_file())

    def test_attestation_for_another_kernel_digest_is_modules_missing(self):
        fx = published()
        ref = f"{REG}/azoth-nvidia@{MODULE['open']}"
        fx["attestations"][ref] = [{"identity": KMOD, "predicate": predicate("open", kernel=OTHER_KERNEL)}]
        self.registry(fx)
        r = self.run_script("resolve")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.state_file()["state"], "modules-missing")
        self.assertNotIn("nvidia_open_digest", self.state_file())

    def test_attestation_for_another_devel_digest_is_modules_missing(self):
        fx = published()
        ref = f"{REG}/azoth-nvidia@{MODULE['open']}"
        stale = predicate("open")
        stale["devel_digest"] = OTHER_KERNEL
        fx["attestations"][ref] = [{"identity": KMOD, "predicate": stale}]
        self.registry(fx)
        r = self.run_script("resolve")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.state_file()["state"], "modules-missing")
        self.assertNotIn("nvidia_open_digest", self.state_file())

    def test_attestation_for_other_nvidia_pins_is_modules_missing(self):
        fx = published()
        ref = f"{REG}/azoth-nvidia@{MODULE['open']}"
        stale = predicate("open")
        stale["pins"]["NVIDIA_OPEN_COMMIT"] = "0" * 40
        fx["attestations"][ref] = [{"identity": KMOD, "predicate": stale}]
        self.registry(fx)
        self.assertEqual(self.run_script("resolve").returncode, 0)
        self.assertEqual(self.state_file()["state"], "modules-missing")

    def test_republished_kernel_fails_against_the_expected_digest(self):
        self.registry(published())
        r = self.run_script("resolve", "--expect-kernel-digest", OTHER_KERNEL)
        self.assertEqual(r.returncode, 1)
        self.assertIn("republished", r.stderr)

    def test_republished_kernel_leaves_no_stale_file(self):
        self.registry(published())
        self.assertEqual(self.run_script("resolve").returncode, 0)
        self.assertIsNotNone(self.state_file())
        r = self.run_script("resolve", "--expect-kernel-digest", OTHER_KERNEL)
        self.assertEqual(r.returncode, 1)
        self.assertIsNone(self.state_file())

    def test_expect_kernel_digest_fails_when_kernel_becomes_absent(self):
        fx = published()
        del fx["tags"][f"{REG}/azoth:{NVR}"]
        self.registry(fx)
        r = self.run_script("resolve", "--expect-kernel-digest", KERNEL)
        self.assertEqual(r.returncode, 1)
        self.assertIsNone(self.state_file())

    def test_expect_kernel_digest_fails_when_kernel_becomes_unsigned(self):
        fx = published()
        del fx["signatures"][f"{REG}/azoth@{KERNEL}"]
        self.registry(fx)
        r = self.run_script("resolve", "--expect-kernel-digest", KERNEL)
        self.assertEqual(r.returncode, 1)
        self.assertIsNone(self.state_file())

    def test_require_ready(self):
        self.registry(published(branches=("open",)))
        self.assertEqual(self.run_script("require-ready").returncode, 1)
        self.registry(published())
        self.assertEqual(self.run_script("require-ready").returncode, 0)

    def test_get_and_has(self):
        self.registry(published(branches=("open",)))
        self.run_script("resolve")
        self.assertEqual(self.run_script("get", "kernel_digest").stdout.strip(), KERNEL)
        self.assertEqual(self.run_script("get", "nvidia_legacy_digest").returncode, 1)
        self.assertEqual(self.run_script("has", "nvidia_open_digest").returncode, 0)
        self.assertEqual(self.run_script("has", "nvidia_legacy_digest").returncode, 1)


if __name__ == "__main__":
    unittest.main()
