"""Unit tests for the accent-colour derivation helpers (NFR-05)."""

from __future__ import annotations

import pytest

from epic_report_generator.core import theming


# -- hex parsing --------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("#2979FF", "#2979ff"),
        ("2979ff", "#2979ff"),
        ("#abc", "#aabbcc"),
        ("ABC", "#aabbcc"),
        ("  #Ff0000 ", "#ff0000"),
    ],
)
def test_normalize_hex_accepts_common_forms(value: str, expected: str) -> None:
    assert theming.normalize_hex(value) == expected


@pytest.mark.parametrize(
    "value", ["", "#12", "#12345", "xyzxyz", "#nothex", "12 34 56"]
)
def test_normalize_hex_rejects_invalid(value: str) -> None:
    assert not theming.is_valid_hex(value)
    with pytest.raises(ValueError):
        theming.normalize_hex(value)


def test_rgb_roundtrip() -> None:
    assert theming.hex_to_rgb("#2979ff") == (41, 121, 255)
    assert theming.rgb_to_hex((41, 121, 255)) == "#2979ff"


# -- mixing -------------------------------------------------------------------


def test_mix_endpoints_and_midpoint() -> None:
    assert theming.mix("#000000", "#ffffff", 0.0) == "#000000"
    assert theming.mix("#000000", "#ffffff", 1.0) == "#ffffff"
    assert theming.mix("#000000", "#ffffff", 0.5) == "#808080"


def test_lighten_and_darken_direction() -> None:
    base = "#2979ff"
    lighter = theming.lighten(base, 0.5)
    darker = theming.darken(base, 0.5)
    assert theming.relative_luminance(lighter) > theming.relative_luminance(base)
    assert theming.relative_luminance(darker) < theming.relative_luminance(base)


def test_on_color_contrast() -> None:
    assert theming.on_color("#ffffff") == "#212121"
    assert theming.on_color("#000000") == "#ffffff"
    # A mid blue is dark enough to warrant white text.
    assert theming.on_color("#2979ff") == "#ffffff"


# -- Qt shades ----------------------------------------------------------------


def test_qt_shades_keys_and_validity() -> None:
    for dark in (False, True):
        shades = theming.qt_shades("#2979ff", dark)
        assert set(shades) == {"accent", "soft", "softer", "border"}
        assert all(theming.is_valid_hex(v) for v in shades.values())


def test_qt_shades_light_vs_dark_differ() -> None:
    light = theming.qt_shades("#2979ff", False)
    dark = theming.qt_shades("#2979ff", True)
    # Dark soft backgrounds are far darker than the light tints.
    assert theming.relative_luminance(dark["soft"]) < theming.relative_luminance(
        light["soft"]
    )


def test_qt_material_extra_overrides_accent_only() -> None:
    extra = theming.qt_material_extra("#2979ff", False)
    # Only the accent tokens — never the text-colour tokens, which drive the
    # main control foreground and would make text unreadable if overridden.
    assert set(extra) == {"primaryColor", "primaryLightColor"}
    assert "primaryTextColor" not in extra
    assert "secondaryTextColor" not in extra
    assert extra["primaryColor"] == "#2979ff"
    assert all(theming.is_valid_hex(v) for v in extra.values())


# -- report overrides ---------------------------------------------------------


def test_report_overrides_keys_and_validity() -> None:
    expected = {
        "accent",
        "label-header",
        "label-tag-bg",
        "label-tag-text",
        "tl-group-bg",
        "tl-group-rule",
    }
    for dark in (False, True):
        overrides = theming.report_overrides("#16A34A", dark)
        assert set(overrides) == expected
        assert all(theming.is_valid_hex(v) for v in overrides.values())


def test_report_overrides_light_accent_passthrough() -> None:
    overrides = theming.report_overrides("#16a34a", dark=False)
    assert overrides["accent"] == "#16a34a"
    # Header tint is a near-white wash of the accent.
    assert theming.relative_luminance(overrides["label-header"]) > 0.7
