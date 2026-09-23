"""WCAG AA gate over every declared pair of the tokens, in the four variants."""

import sys

import tokens as tk
from color import contrast, over

THRESHOLD = {"text": 4.5, "large": 3.0, "ui": 3.0}


def expand(pairs):
    """Pairs with each = true become one pair per background."""
    for pair in pairs:
        if pair.get("each"):
            for bg in pair["bg"]:
                yield {**pair, "bg": bg, "each": False}
        else:
            yield pair


def flatten(names, palette):
    """One name, or a bottom-to-top list of names, to an opaque colour."""
    names = [names] if isinstance(names, str) else names
    result = palette[names[0]]
    if result[3] != 1.0:
        raise ValueError(f"the bottom layer must be opaque: {names[0]}")
    for name in names[1:]:
        result = over(palette[name], result)
    return result


def check(tokens):
    """[(variant, fg, bg, kind, ratio, needed)] for every pair, failures included."""
    rows = []
    for variant in tk.VARIANTS:
        palette = tk.colors(tokens, variant)
        for pair in expand(tokens["pair"]):
            if "only" in pair and variant not in pair["only"]:
                continue
            bg = flatten(pair["bg"], palette)
            fg = over(palette[pair["fg"]], bg)
            needed = pair.get("min", THRESHOLD[pair["kind"]])
            rows.append(
                (
                    variant,
                    pair["fg"],
                    pair["bg"],
                    pair["kind"],
                    contrast(fg, bg),
                    needed,
                )
            )
    return rows


def main():
    failures = 0
    for variant, fg, bg, kind, ratio, needed in check(tk.load()):
        ok = ratio >= needed
        failures += not ok
        print(
            f"{'ok  ' if ok else 'FAIL'} {variant:9s} {fg:13s} on {str(bg):34s} {kind:5s} {ratio:5.2f} (needs {needed})"
        )
    print(f"{failures} failing pair(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
