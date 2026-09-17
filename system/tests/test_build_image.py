"""Unit tests of the kernel artifacts in system/build-image.sh, with a podman stub that records
its arguments (python3 -B -m unittest discover -s system/tests -v)."""

import os
import pathlib
import subprocess
import tempfile
import textwrap
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
BUILD = ROOT / "system" / "build-image.sh"
NVR = subprocess.run(["bash", str(ROOT / "forge/specs/azoth/nvr.sh")], capture_output=True, text=True, check=True).stdout.strip()
KERNEL = "sha256:" + "1" * 64
OPEN = "sha256:" + "3" * 64
LEGACY = "sha256:" + "4" * 64


class BuildImage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self.tmp.name)
        bin_dir = self.dir / "bin"
        bin_dir.mkdir()
        (bin_dir / "podman").write_text(textwrap.dedent(f"""\
            #!/bin/bash
            printf '%s\\n' "$@" > {self.dir}/podman.args
            """))
        (bin_dir / "podman").chmod(0o755)
        self.artifacts = self.dir / "artifacts"
        self.artifacts.mkdir()
        # SECUREBOOT_SIGNING_KEY set: the stub never reads it, and no throwaway key is generated.
        self.env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}", KERNEL_ARTIFACTS_DIR=str(self.artifacts),
                        SECUREBOOT_SIGNING_KEY="unused by the stub")

    def tearDown(self):
        self.tmp.cleanup()

    def artifacts_file(self, **values):
        lines = {"state": "ready", "nvr": NVR, "registry": "ghcr.io/hr-mes", "kernel_digest": KERNEL,
                 "nvidia_open_digest": OPEN, "nvidia_legacy_digest": LEGACY, **values}
        (self.artifacts / "kernel-artifacts.env").write_text("".join(f"{k}={v}\n" for k, v in lines.items() if v is not None))

    def build(self, gpu):
        r = subprocess.run(["bash", str(BUILD), "--gpu", gpu, "--registry", "localhost", "--tag", "check"],
                           capture_output=True, text=True, env=self.env)
        args = (self.dir / "podman.args").read_text().splitlines() if (self.dir / "podman.args").exists() else []
        return r, args

    def test_nvidia_builds_from_the_open_module_digest(self):
        self.artifacts_file()
        r, args = self.build("nvidia")
        self.assertEqual(r.returncode, 0, r.stderr)
        for expected in (f"AZOTH_NVR={NVR}", "KERNEL_REGISTRY=ghcr.io/hr-mes", f"NVIDIA_OPEN_DIGEST={OPEN}",
                         f"io.athanor.azoth.digest={KERNEL}", f"io.athanor.azoth-nvidia.digest={OPEN}"):
            self.assertIn(expected, args)
        self.assertNotIn(f"NVIDIA_LEGACY_DIGEST={LEGACY}", args)

    def test_default_image_builds_while_modules_are_missing(self):
        self.artifacts_file(state="modules-missing", nvidia_open_digest=None, nvidia_legacy_digest=None)
        r, args = self.build("none")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(any(a.startswith("NVIDIA_") for a in args))

    def test_variant_without_its_module_digest_is_refused(self):
        self.artifacts_file(state="modules-missing", nvidia_legacy_digest=None)
        r, args = self.build("nvidia-legacy")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("nvidia_legacy_digest", r.stderr)
        self.assertEqual(args, [])

    def test_missing_kernel_is_refused(self):
        self.artifacts_file(state="kernel-missing", kernel_digest=None, nvidia_open_digest=None, nvidia_legacy_digest=None)
        r, args = self.build("none")
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(args, [])

    def test_artifacts_of_other_pins_are_refused(self):
        self.artifacts_file(nvr="7.0.0-100.azoth.fc43")
        r, args = self.build("none")
        self.assertEqual(r.returncode, 2)
        self.assertIn("resolve again", r.stderr)
        self.assertEqual(args, [])


if __name__ == "__main__":
    unittest.main()
