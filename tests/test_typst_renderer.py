"""Tests for the Typst renderer's CJK detection and conditional font paths.

The bundled 16MB Noto Sans CJK JP font lives in a sibling ``fonts_cjk`` dir that
is only added to Typst's font search path when the report actually contains CJK
text, so pure-Latin renders never pay to scan it. These tests cover the detector
and the path-gating without running the (slow) native Typst compiler.
"""

from __future__ import annotations

import epic_report_generator.core.typst_renderer as tr


def test_needs_cjk_latin_and_cyrillic_are_false() -> None:
    assert tr._needs_cjk("Epic Progress Q3 (50%)") is False
    assert tr._needs_cjk("Отчёт по эпикам — Спринт 5") is False
    assert tr._needs_cjk("") is False


def test_needs_cjk_detects_japanese_korean_chinese() -> None:
    assert tr._needs_cjk("プロジェクト計画") is True  # Japanese (kana + kanji)
    assert tr._needs_cjk("프로젝트 보고서") is True  # Korean (Hangul)
    assert tr._needs_cjk("项目进度报告") is True  # Chinese (Han)
    assert tr._needs_cjk("Sprint 計画 2026") is True  # mixed


def _capture_font_paths(monkeypatch) -> dict:
    """Patch the lazily-imported ``typst.compile`` to record its font_paths."""
    import typst

    captured: dict = {}

    def fake_compile(*, input, root, font_paths, ignore_system_fonts):  # noqa: A002
        captured["font_paths"] = list(font_paths)
        return b"%PDF-1.7 fake"

    monkeypatch.setattr(typst, "compile", fake_compile)
    return captured


def test_latin_payload_excludes_cjk_font(monkeypatch) -> None:
    captured = _capture_font_paths(monkeypatch)
    out = tr.render_pdf({"title": {"title": "Plain Latin Report"}})
    assert out == b"%PDF-1.7 fake"
    paths = captured["font_paths"]
    assert any(p.endswith("fonts") for p in paths)  # base (Inter) always present
    assert not any("fonts_cjk" in p for p in paths)  # CJK dir skipped


def test_cjk_payload_includes_cjk_font(monkeypatch) -> None:
    captured = _capture_font_paths(monkeypatch)
    tr.render_pdf({"title": {"title": "プロジェクト計画レポート"}})
    paths = captured["font_paths"]
    assert any("fonts_cjk" in p for p in paths)  # CJK dir added on demand
