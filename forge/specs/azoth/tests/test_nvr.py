"""Unit test of nvr.sh's shape check on FEDORA_KERNEL_NVR
(python3 -B -m unittest discover -s forge/specs/azoth/tests -v)."""

import pathlib
import subprocess
import tempfile
import unittest

AZOTH = pathlib.Path(__file__).resolve().parents[1]
NVR_SH = AZOTH / "nvr.sh"


class Nvr(unittest.TestCase):
    def run_nvr(self, fedora_kernel_nvr):
        with tempfile.NamedTemporaryFile("w", suffix=".env") as pins:
            pins.write(f"FEDORA_KERNEL_NVR={fedora_kernel_nvr}\n")
            pins.flush()
            return subprocess.run(["bash", str(NVR_SH), pins.name], capture_output=True, text=True)

    def test_the_current_pinned_shape(self):
        r = self.run_nvr("7.2.5-100.fc43")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "7.2.5-100.azoth.fc43")

    def test_a_prerelease_shape(self):
        r = self.run_nvr("6.14.0-0.rc4.20250226git.42.fc43")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "6.14.0-0.azoth.rc4.20250226git.42.fc43")

    def test_a_respin_shape_with_a_trailing_segment(self):
        r = self.run_nvr("7.2.5-100.fc43.1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "7.2.5-100.azoth.fc43.1")

    def test_a_malformed_value_is_rejected(self):
        r = self.run_nvr("not-a-valid-nvr")
        self.assertEqual(r.returncode, 1)
        self.assertIn("does not look like one", r.stderr)

    def test_a_value_with_no_fedora_dist_tag_is_rejected(self):
        r = self.run_nvr("7.2.5-100.el9")
        self.assertEqual(r.returncode, 1)
        self.assertIn("does not look like one", r.stderr)

    def test_shell_metacharacters_are_rejected(self):
        r = self.run_nvr("7.2.5-100;rm -rf /.fc43")
        self.assertEqual(r.returncode, 1)
        self.assertIn("does not look like one", r.stderr)


if __name__ == "__main__":
    unittest.main()
