"""Loads tokens.toml and resolves each variant to concrete colours."""
import tomllib
from pathlib import Path

from color import resolve

HERE = Path(__file__).resolve().parent
VARIANTS = ("light", "dark", "light-hc", "dark-hc")


def load(path=HERE / "tokens.toml"):
    with open(path, "rb") as handle:
        return tomllib.load(handle)


def colors(tokens, variant):
    """{name: (r, g, b, a)} for one variant, with `inherits` applied."""
    section = tokens["variant"][variant]
    specs = {}
    if "inherits" in section:
        specs.update(tokens["variant"][section["inherits"]]["color"])
    specs.update(section.get("color", {}))
    accent = tokens["accent"]
    return {name: resolve(spec, accent["hue"], accent["saturation"]) for name, spec in specs.items()}
