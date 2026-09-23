import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import cases


class CasesTest(unittest.TestCase):
    def test_the_greeter_has_the_twelve_cases_of_sh13(self):
        found = cases.surface_cases("greeter")
        self.assertEqual(len(found), 12)
        self.assertEqual(len({c.tag for c in found}), 12)
        self.assertEqual({c.scale for c in found}, {"1.0", "1.5"})
        self.assertEqual({c.variant for c in found}, {"light", "dark"})
        self.assertEqual({c.locale for c in found}, {"en_US.UTF-8", "de_DE.UTF-8", "ar_EG.UTF-8"})
        self.assertEqual({c.catalog for c in found}, {"-", "de.mo", "rtl.mo"})

    def test_tags_are_file_names(self):
        for case in cases.surface_cases("greeter"):
            self.assertRegex(case.tag, r"^greeter-(light|dark)-(1\.0|1\.5)-(en|de|rtl)$")

    def test_an_unknown_surface_is_an_error(self):
        with self.assertRaises(KeyError):
            cases.surface_cases("launcher")


if __name__ == "__main__":
    unittest.main()
