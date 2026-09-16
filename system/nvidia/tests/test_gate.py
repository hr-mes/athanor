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
