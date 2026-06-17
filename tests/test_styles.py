"""Tests for the accent-tokenised QSS overlay templates (NFR-05)."""

from __future__ import annotations

from epic_report_generator.ui import styles

_TOKENS = ("@ACCENT@", "@SOFT@", "@SOFTER@", "@BORDER@")


def test_default_overlays_have_no_unresolved_tokens() -> None:
    for css in (styles.light_theme(), styles.dark_theme()):
        assert not any(tok in css for tok in _TOKENS)


def test_default_overlays_preserve_stock_blue() -> None:
    # Historical hand-tuned blues — guards against accidental palette drift.
    light = styles.light_theme()
    assert "#2979ff" in light and "#d4e4ff" in light and "#b3d4ff" in light
    dark = styles.dark_theme()
    assert "#448aff" in dark and "#1a2744" in dark and "#1e3a5f" in dark


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
