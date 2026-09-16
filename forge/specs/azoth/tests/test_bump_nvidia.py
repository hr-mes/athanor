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
