"""Accent-colour derivation shared by the app UI and the PDF report.

A single accent colour (chosen in Settings) drives every accent-tinted surface
in both the Qt UI and the Typst report.  This module is the one place that turns
that base colour into the family of shades each layer needs — so the app and the
PDF stay visually consistent.  It is intentionally dependency-free (no Qt, no
Typst) so the maths can be unit-tested in isolation.

Two entry points:

* :func:`qt_shades` — shades consumed by the QSS overlay templates in
  ``ui/styles.py`` (sidebar selection, chips, secondary buttons, …).
* :func:`report_overrides` — hex overrides injected into the Typst palette via
  ``data.json`` (accent, label headers/tags, timeline group bands).

When no custom accent is configured, neither layer calls these helpers and the
hand-tuned default palettes are used verbatim, so the stock look is unchanged.
"""

from __future__ import annotations

# Canonical default accent (the app's historical blue).  Kept for reference and
# for the Settings swatch when nothing custom is set.
DEFAULT_ACCENT = "#2979FF"

# Neutral anchors the dark-mode tints are mixed against (sidebar / report bg).
_DARK_UI_BG = "#1A1D21"
_DARK_REPORT_BG = "#1E1E1E"

RGB = tuple[int, int, int]


def normalize_hex(value: str) -> str:
    """Return *value* as a ``#rrggbb`` string, or raise ``ValueError``.

    Accepts ``#rgb`` / ``rgb`` / ``#rrggbb`` / ``rrggbb`` (case-insensitive).
    """
    s = value.strip().lstrip("#")
    if len(s) == 3:
        s = "".join(ch * 2 for ch in s)
    if len(s) != 6 or any(c not in "0123456789abcdefABCDEF" for c in s):
        raise ValueError(f"Invalid hex colour: {value!r}")
    return "#" + s.lower()


def is_valid_hex(value: str) -> bool:
    """Return ``True`` when *value* parses as a hex colour."""
    try:
        normalize_hex(value)
    except (ValueError, AttributeError):
        return False
    return True


def hex_to_rgb(value: str) -> RGB:
    """Convert a hex colour to an ``(r, g, b)`` tuple of 0–255 ints."""
    s = normalize_hex(value).lstrip("#")
    return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)


def rgb_to_hex(rgb: RGB) -> str:
    """Convert an ``(r, g, b)`` tuple to a ``#rrggbb`` string (clamped)."""
    return "#" + "".join(f"{max(0, min(255, round(c))):02x}" for c in rgb)


def mix(color: str, other: str, t: float) -> str:
    """Blend *color* toward *other* by fraction *t* (0 = color, 1 = other)."""
    a = hex_to_rgb(color)
    b = hex_to_rgb(other)
    mixed = tuple(a[i] + (b[i] - a[i]) * t for i in range(3))
    return rgb_to_hex(mixed)  # type: ignore[arg-type]


def lighten(color: str, t: float) -> str:
    """Mix *color* toward white by fraction *t*."""
    return mix(color, "#ffffff", t)


def darken(color: str, t: float) -> str:
    """Mix *color* toward black by fraction *t*."""
    return mix(color, "#000000", t)


def relative_luminance(color: str) -> float:
    """Return the WCAG relative luminance (0–1) of *color*."""

    def channel(c: int) -> float:
        s = c / 255
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4

    r, g, b = hex_to_rgb(color)
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def on_color(color: str) -> str:
    """Return a readable foreground (near-black or white) for *color*."""
    return "#212121" if relative_luminance(color) > 0.45 else "#ffffff"


# ---------------------------------------------------------------------------
# Qt UI overlay shades (consumed by ui/styles.py templates)
# ---------------------------------------------------------------------------


def qt_shades(accent: str, dark: bool) -> dict[str, str]:
    """Derive the accent shades the QSS overlay templates need.

    Keys: ``accent`` (text/border/icon), ``soft`` (selected background),
    ``softer`` (hover/chip background), ``border`` (chip outline),
    ``accent_hover`` / ``accent_pressed`` (filled-button states),
    ``accent_on`` (readable text drawn on a filled ``accent`` fill).
    """
    accent = normalize_hex(accent)
    if dark:
        bright = lighten(accent, 0.20)
        return {
            "accent": bright,
            "soft": mix(bright, _DARK_UI_BG, 0.86),
            "softer": mix(bright, _DARK_UI_BG, 0.86),
            "border": mix(bright, _DARK_UI_BG, 0.72),
            # On dark backgrounds a filled button reads as "pressed" by
            # getting brighter, so lighten rather than darken.
            "accent_hover": lighten(bright, 0.12),
            "accent_pressed": lighten(bright, 0.22),
            "accent_on": on_color(bright),
        }
    return {
        "accent": accent,
        "soft": lighten(accent, 0.82),
        "softer": lighten(accent, 0.90),
        "border": lighten(accent, 0.62),
        "accent_hover": darken(accent, 0.10),
        "accent_pressed": darken(accent, 0.18),
        "accent_on": on_color(accent),
    }


def qt_material_extra(accent: str, dark: bool) -> dict[str, str]:
    """Return qt-material ``extra`` overrides (accent colour family only).

    qt-material merges ``extra`` over the loaded theme XML, so these override
    the base ``primaryColor`` / ``primaryLightColor`` (the accent and its light
    variant).  The text-colour tokens (``primaryTextColor`` /
    ``secondaryTextColor``) are deliberately left untouched: in qt-material they
    are the main foreground colour for controls (dark on light themes, white on
    dark), so overriding them would make control text unreadable.
    """
    accent = normalize_hex(accent)
    primary = lighten(accent, 0.20) if dark else accent
    return {
        "primaryColor": primary,
        "primaryLightColor": lighten(primary, 0.35),
    }


# ---------------------------------------------------------------------------
# Typst report palette overrides (injected via data.json)
# ---------------------------------------------------------------------------


def report_overrides(accent: str, dark: bool) -> dict[str, str]:
    """Derive the accent-family colour overrides for the Typst palette.

    Only accent-tinted entries are overridden; semantic status colours
    (green/amber/red) and the distinct sprint-lane hue stay as defined in
    ``theme.typ``.  Keys match palette entries: ``accent``, ``label-header``,
    ``label-tag-bg``, ``label-tag-text``, ``tl-group-bg``, ``tl-group-rule``.
    """
    accent = normalize_hex(accent)
    if dark:
        bright = lighten(accent, 0.15)
        return {
            "accent": bright,
            "label-header": mix(bright, _DARK_REPORT_BG, 0.80),
            "label-tag-bg": mix(bright, _DARK_REPORT_BG, 0.88),
            "label-tag-text": lighten(accent, 0.25),
            "tl-group-bg": mix(bright, _DARK_REPORT_BG, 0.82),
            "tl-group-rule": mix(bright, _DARK_REPORT_BG, 0.70),
        }
    return {
        "accent": accent,
        "label-header": lighten(accent, 0.90),
        "label-tag-bg": lighten(accent, 0.86),
        "label-tag-text": darken(accent, 0.30),
        "tl-group-bg": lighten(accent, 0.91),
        "tl-group-rule": lighten(accent, 0.78),
    }
