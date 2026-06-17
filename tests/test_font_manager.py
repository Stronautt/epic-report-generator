"""Tests for the font manager (NFR-05).

Network access is mocked; the only real font touched is the bundled Inter.
"""

from __future__ import annotations

import importlib.resources as res
from pathlib import Path

import pytest

from epic_report_generator.services import font_manager as fmmod
from epic_report_generator.services.font_manager import FontError, FontManager


class _FakeConfig:
    """Minimal config stand-in backed by a plain dict."""

    def __init__(self) -> None:
        self.d: dict[str, object] = {}

    def get(self, key: str, default: object = None) -> object:
        return self.d.get(key, default)

    def update(self, values: dict[str, object]) -> None:
        self.d.update(values)

    def set(self, key: str, value: object) -> None:
        self.d[key] = value


@pytest.fixture
def fm(tmp_path: Path) -> tuple[FontManager, _FakeConfig]:
    cfg = _FakeConfig()
    manager = FontManager(cfg)  # type: ignore[arg-type]
    manager._fonts_dir = tmp_path / "fonts"  # redirect cache off the real config dir
    return manager, cfg


def _inter_path() -> str:
    return str(res.files("epic_report_generator.resources") / "fonts" / "Inter.ttf")


# -- slug / defaults ----------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "slug"),
    [("Open Sans", "open_sans"), ("  Noto-Serif!! ", "noto_serif"), ("", "font")],
)
def test_slug(name: str, slug: str) -> None:
    assert fmmod._slug(name) == slug


def test_default_resolve_is_empty(fm: tuple[FontManager, _FakeConfig]) -> None:
    manager, _ = fm
    assert manager.resolve_for_report() == ("", "")
    assert manager.apply_to_app() == ""


# -- file fonts ---------------------------------------------------------------


def test_set_font_file_rejects_bad_input(
    fm: tuple[FontManager, _FakeConfig], tmp_path: Path
) -> None:
    manager, _ = fm
    with pytest.raises(FontError):
        manager.set_font_file(str(tmp_path / "missing.ttf"))
    not_a_font = tmp_path / "notes.txt"
    not_a_font.write_text("hello")
    with pytest.raises(FontError):
        manager.set_font_file(str(not_a_font))


def test_set_font_file_caches_and_resolves(
    fm: tuple[FontManager, _FakeConfig]
) -> None:
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    manager, cfg = fm
    family = manager.set_font_file(_inter_path())
    assert family == "Inter"
    # Copied into the cache, not referencing the original location.
    assert (manager.fonts_dir / "file" / "Inter.ttf").is_file()

    cfg.update(
        {"font_source": "file", "font_family": family, "font_value": _inter_path()}
    )
    resolved_family, font_dir = manager.resolve_for_report()
    assert resolved_family == "Inter"
    assert list(Path(font_dir).glob("*.ttf"))


# -- Google fonts (mocked network) --------------------------------------------


class _Resp:
    def __init__(
        self,
        *,
        content: bytes = b"",
        status_code: int = 200,
        json_data: object = None,
    ) -> None:
        self._content = content
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self._json = json_data

    def raise_for_status(self) -> None:
        if not self.ok:
            raise fmmod.requests.HTTPError("boom")

    def json(self) -> object:
        return self._json

    @property
    def content(self) -> bytes:
        return self._content


def test_github_resolves_variable_font(
    fm: tuple[FontManager, _FakeConfig], monkeypatch: pytest.MonkeyPatch
) -> None:
    manager, _ = fm
    # The repo ships Manrope as a single variable file plus the licence text;
    # only the .ttf (and, when present, the variable one) should be taken.
    contents = [
        {"name": "OFL.txt", "download_url": "https://raw.example/OFL.txt"},
        {"name": "Manrope[wght].ttf", "download_url": "https://raw.example/M.ttf"},
    ]

    def fake_get(url, params=None, headers=None, timeout=None):  # noqa: ANN001
        if url.startswith(fmmod._GH_CONTENTS):
            if url.endswith("/ofl/manrope"):
                return _Resp(json_data=contents)
            return _Resp(status_code=404)
        return _Resp(content=b"FONTDATA")  # raw download

    monkeypatch.setattr(fmmod.requests, "get", fake_get)

    assert manager._github_ttf_urls("Manrope") == ["https://raw.example/M.ttf"]
    dest = manager._download_google("Manrope", force=True)
    ttfs = list(dest.glob("*.ttf"))
    assert ttfs and ttfs[0].read_bytes() == b"FONTDATA"

    # A cached family makes no further network calls.
    def boom(*_args, **_kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("unexpected network call")

    monkeypatch.setattr(fmmod.requests, "get", boom)
    assert manager._download_google("Manrope", force=False) == dest


def test_github_falls_through_license_dirs(
    fm: tuple[FontManager, _FakeConfig], monkeypatch: pytest.MonkeyPatch
) -> None:
    manager, _ = fm
    contents = [{"name": "Roboto.ttf", "download_url": "https://raw.example/R.ttf"}]

    def fake_get(url, params=None, headers=None, timeout=None):  # noqa: ANN001
        if url.endswith("/apache/roboto"):
            return _Resp(json_data=contents)
        return _Resp(status_code=404)  # ofl misses, apache hits

    monkeypatch.setattr(fmmod.requests, "get", fake_get)
    assert manager._github_ttf_urls("Roboto") == ["https://raw.example/R.ttf"]


def test_google_unknown_family_raises(
    fm: tuple[FontManager, _FakeConfig], monkeypatch: pytest.MonkeyPatch
) -> None:
    manager, _ = fm
    monkeypatch.setattr(
        fmmod.requests, "get", lambda *a, **k: _Resp(status_code=404)
    )
    with pytest.raises(FontError):
        manager.set_google_font("No Such Family")


def test_download_google_font_returns_cache_dir(
    fm: tuple[FontManager, _FakeConfig], monkeypatch: pytest.MonkeyPatch
) -> None:
    # download_google_font must be Qt-free (it runs on a background thread).
    manager, _ = fm
    contents = [{"name": "Manrope[wght].ttf", "download_url": "https://raw/M.ttf"}]

    def fake_get(url, params=None, headers=None, timeout=None):  # noqa: ANN001
        if url.startswith(fmmod._GH_CONTENTS):
            return _Resp(json_data=contents) if url.endswith("manrope") else _Resp(
                status_code=404
            )
        return _Resp(content=b"DATA")

    monkeypatch.setattr(fmmod.requests, "get", fake_get)
    dest = manager.download_google_font("Manrope")
    assert Path(dest).is_dir() and list(Path(dest).glob("*.ttf"))


def test_register_font_dir_uses_fallback_when_empty(
    fm: tuple[FontManager, _FakeConfig], tmp_path: Path
) -> None:
    # No font files → no QFontDatabase call → the fallback name is returned.
    manager, _ = fm
    empty = tmp_path / "empty"
    empty.mkdir()
    assert manager.register_font_dir(str(empty), fallback="Manrope") == "Manrope"
