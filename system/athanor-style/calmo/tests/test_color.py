import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import color
import tokens as tk


class ColorTest(unittest.TestCase):
    def test_hex_round_trip(self):
        self.assertEqual(color.to_hex(color.from_hex("#12805f")), "#12805f")

    def test_bad_hex_is_rejected(self):
        with self.assertRaises(ValueError):
            color.from_hex("#fff")

    def test_factory_accent_matches_the_mockup(self):
        # hsl(231 62% 47%) on light, hsl(231 87% 75%) on dark.
        self.assertEqual(color.to_hex(color.resolve({"s": "accent", "l": 47}, 231, 62)), "#2e44c2")
        self.assertEqual(color.to_hex(color.resolve({"s": "accent+25", "l": 75}, 231, 62)), "#8898f7")

    def test_accent_saturation_is_capped(self):
        self.assertEqual(color.resolve({"s": "accent+80", "l": 50}, 0, 62), color.resolve({"s": 100, "l": 50}, 0, 62))

    def test_hue_offset_and_alpha(self):
        r, g, b, a = color.resolve({"dh": -38, "s": 72, "l": 86, "a": 0.42}, 231, 62)
        self.assertEqual(a, 0.42)
        self.assertEqual(color.to_hex((r, g, b)), color.to_hex(color.resolve({"s": 72, "l": 86}, 193, 62)))

    def test_unknown_saturation_word_is_rejected(self):
        with self.assertRaises(ValueError):
            color.resolve({"s": "brand", "l": 50}, 231, 62)

    def test_contrast_extremes(self):
        black, white = color.from_hex("#000000"), color.from_hex("#ffffff")
        self.assertAlmostEqual(color.contrast(black, white), 21.0, places=6)
        self.assertAlmostEqual(color.contrast(white, white), 1.0, places=6)
        self.assertEqual(color.contrast(black, white), color.contrast(white, black))

    def test_known_ratio(self):
        # #767676 on white is the textbook 4.54:1.
        self.assertAlmostEqual(color.contrast(color.from_hex("#767676"), color.from_hex("#ffffff")), 4.54, places=2)

    def test_over_composites_towards_the_top_layer(self):
        half_black = (0.0, 0.0, 0.0, 0.5)
        self.assertEqual(color.to_hex(color.over(half_black, color.from_hex("#ffffff"))), "#808080")


class TokensTest(unittest.TestCase):
    def setUp(self):
        self.tokens = tk.load()

    def test_four_variants_resolve_to_the_same_names(self):
        names = [set(tk.colors(self.tokens, v)) for v in tk.VARIANTS]
        self.assertTrue(all(n == names[0] for n in names))

    def test_high_contrast_inherits_what_it_does_not_override(self):
        self.assertEqual(tk.colors(self.tokens, "light-hc")["surf"], tk.colors(self.tokens, "light")["surf"])
        self.assertNotEqual(tk.colors(self.tokens, "light-hc")["ink2"], tk.colors(self.tokens, "light")["ink2"])

    def test_trust_colours_do_not_follow_the_accent(self):
        moved = {**self.tokens, "accent": {"hue": 18, "saturation": 72}}
        for name in ("ok", "warn", "bad"):
            self.assertEqual(tk.colors(moved, "light")[name], tk.colors(self.tokens, "light")[name])
        self.assertNotEqual(tk.colors(moved, "light")["acc"], tk.colors(self.tokens, "light")["acc"])


if __name__ == "__main__":
    unittest.main()
