"""Colour arithmetic for the Calmo tokens: HSL to sRGB, compositing, WCAG contrast."""
import colorsys


def from_hex(text):
    """'#rrggbb' -> (r, g, b, 1.0), channels in 0..1."""
    text = text.lstrip("#")
    if len(text) != 6:
        raise ValueError(f"not a #rrggbb colour: {text!r}")
    return tuple(int(text[i:i + 2], 16) / 255 for i in (0, 2, 4)) + (1.0,)


def resolve(spec, hue, saturation):
    """A token colour (hex string or table) -> (r, g, b, a)."""
    if isinstance(spec, str):
        return from_hex(spec)
    alpha = float(spec.get("a", 1.0))
    if "hex" in spec:
        return from_hex(spec["hex"])[:3] + (alpha,)
    sat = spec["s"]
    if isinstance(sat, str):
        if not sat.startswith("accent"):
            raise ValueError(f"saturation must be a number or accent[+N]: {sat!r}")
        sat = min(100.0, saturation + float(sat[len("accent"):] or 0))
    h = (hue + spec.get("dh", 0)) % 360
    r, g, b = colorsys.hls_to_rgb(h / 360, spec["l"] / 100, sat / 100)
    return (r, g, b, alpha)


def over(top, bottom):
    """Source-over compositing of `top` on an opaque `bottom`."""
    a = top[3]
    return tuple(t * a + b * (1 - a) for t, b in zip(top[:3], bottom[:3])) + (1.0,)


def to_hex(color):
    return "#%02x%02x%02x" % tuple(round(c * 255) for c in color[:3])


def luminance(color):
    def linear(u):
        return u / 12.92 if u <= 0.04045 else ((u + 0.055) / 1.055) ** 2.4
    r, g, b = (linear(c) for c in color[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    """WCAG 2.1 contrast ratio of two opaque colours, 1.0 to 21.0."""
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)
