"""Unit tests of the COSMIC defaults wiring check in scripts/verify.py
(python3 -B -m unittest discover -s scripts/tests -v)."""

import importlib.util
import pathlib
import tempfile
import unittest

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "verify.py"
spec = importlib.util.spec_from_file_location("verify", SCRIPT)
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)

OVERLAY = "/usr/share/athanor/cosmic-defaults"
ENV_FILE = "forge/specs/athanor-calmo/SOURCES/usr/lib/environment.d/60-athanor-cosmic-defaults.conf"
SESSION = "forge/specs/athanor-system-config/SOURCES/usr/bin/athanor-session"
SPEC = "forge/specs/athanor-calmo/athanor-calmo.spec"
KEY = "system/athanor-style/calmo/generated/cosmic/cosmic/com.system76.CosmicTheme.Mode/v1/is_dark"


class CosmicDefaultsTest(unittest.TestCase):
    def tree(self, tmp, **overrides):
        files = {
            KEY: "false",
            ENV_FILE: f"XDG_DATA_DIRS={OVERLAY}:${{XDG_DATA_DIRS:-/usr/local/share:/usr/share}}\n",
            SESSION: f'export XDG_DATA_DIRS="{OVERLAY}:${{XDG_DATA_DIRS:-/usr/local/share:/usr/share}}"\n',
            SPEC: ("%install\ncp -a system/athanor-style/calmo/generated/cosmic/cosmic "
                   f"%{{buildroot}}{OVERLAY}/\n%files\n{OVERLAY}\n"
                   "/usr/lib/environment.d/60-athanor-cosmic-defaults.conf\n"),
        }
        files.update(overrides)
        root = pathlib.Path(tmp)
        for name, text in files.items():
            if text is not None:
                (root / name).parent.mkdir(parents=True, exist_ok=True)
                (root / name).write_text(text)
        return root

    def test_a_complete_wiring_has_no_problem(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(verify.cosmic_defaults_problems(self.tree(tmp)), [])

    def test_no_generated_defaults_is_a_problem(self):
        with tempfile.TemporaryDirectory() as tmp:
            problems = verify.cosmic_defaults_problems(self.tree(tmp, **{KEY: None}))
            self.assertEqual(len(problems), 1)
            self.assertIn("derive.sh", problems[0])

    def test_the_overlay_must_come_first_for_the_user_manager(self):
        with tempfile.TemporaryDirectory() as tmp:
            late = f"XDG_DATA_DIRS=/usr/share:{OVERLAY}\n"
            problems = verify.cosmic_defaults_problems(self.tree(tmp, **{ENV_FILE: late}))
            self.assertEqual(len(problems), 1)
            self.assertIn("environment.d", problems[0])

    def test_the_compositor_needs_the_export_too(self):
        with tempfile.TemporaryDirectory() as tmp:
            problems = verify.cosmic_defaults_problems(self.tree(tmp, **{SESSION: "exec cosmic-comp\n"}))
            self.assertEqual(len(problems), 1)
            self.assertIn("athanor-session", problems[0])

    def test_the_spec_must_ship_the_overlay_and_the_environment_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            problems = verify.cosmic_defaults_problems(self.tree(tmp, **{SPEC: "%files\n"}))
            self.assertEqual(len(problems), 2)


if __name__ == "__main__":
    unittest.main()
