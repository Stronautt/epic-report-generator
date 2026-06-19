"""Tests for the accent-tokenised QSS overlay templates (NFR-05)."""

from __future__ import annotations

from epic_report_generator.ui import styles

_TOKENS = ("@ACCENT@", "@SOFT@", "@SOFTER@", "@BORDER@")


def test_default_overlays_have_no_unresolved_tokens() -> None:
    for css in (styles.light_theme(), styles.dark_theme()):
        assert not any(tok in css for tok in _TOKENS)


def test_default_overlays_embed_stock_palette() -> None:
    # The default overlays embed the stock palette derived from the accent
    # maths; the exact hex values are pinned by test_theming's snapshot test.
    from epic_report_generator.core import theming

    light = styles.light_theme()
    light_shades = theming.qt_shades(theming.DEFAULT_ACCENT, dark=False)
    assert all(light_shades[k] in light for k in ("accent", "soft", "border"))
    dark = styles.dark_theme()
    dark_shades = theming.qt_shades(theming.DEFAULT_ACCENT, dark=True)
    assert all(dark_shades[k] in dark for k in ("accent", "soft", "border"))


def test_custom_shades_substitute_tokens() -> None:
    shades = {
        "accent": "#16a34a",
        "soft": "#dcfce7",
        "softer": "#f0fdf4",
        "border": "#86efac",
    }
    css = styles.light_theme(shades)
    assert not any(tok in css for tok in _TOKENS)
    for value in shades.values():
        assert value in css
    # The stock accent must be gone once a custom accent is supplied.
    assert "#2979ff" not in css
