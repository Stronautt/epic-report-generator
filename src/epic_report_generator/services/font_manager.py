"""Resolve and provision custom report/UI fonts (NFR-05).

A font is configured one of two ways:

* **File** — the user picks a ``.ttf`` / ``.otf``; it is copied into a cache
  under the config dir so it survives even if the original is moved.
* **Google Fonts** — the user types a family name; its TTF files are downloaded
  (with an old User-Agent so Google serves TrueType, which Typst can read) and
  cached.

The same resolved family is applied to the Qt UI (registered with
``QFontDatabase`` and fed to qt-material) and to the PDF (the cache directory is
added to Typst's ``font_paths``).  Qt is imported lazily so this module can be
exercised headless; downloads use ``requests`` (already a dependency).
"""

from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path

import requests
from platformdirs import user_config_dir

from epic_report_generator.services.config_manager import APP_NAME, ConfigManager

logger = logging.getLogger(__name__)

_FONT_SUFFIXES = {".ttf", ".otf", ".ttc"}

# Google Fonts source: the upstream google/fonts repo hosts TTF files directly.
# The CSS API only serves woff2 for modern (variable) families like Manrope,
# which Typst cannot read — so we resolve families against the repo instead.
# The contents API lists a family's files; the entries' raw download URLs
# deliver the TTFs. Families live under one of these license directories.
_GH_CONTENTS = "https://api.github.com/repos/google/fonts/contents"
_GH_LICENSE_DIRS = ("ofl", "apache", "ufl")
_GH_HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "epic-report-generator",
}
_DOWNLOAD_TIMEOUT = 20


def _slug(name: str) -> str:
    """Filesystem-safe slug for a font family name."""
    return re.sub(r"[^A-Za-z0-9]+", "_", name.strip()).strip("_").lower() or "font"


class FontError(RuntimeError):
    """Raised when a font cannot be provisioned."""


class FontManager:
    """Provision custom fonts for both the Qt UI and the Typst report."""

    def __init__(self, config: ConfigManager) -> None:
        self._config = config
        self._fonts_dir = Path(user_config_dir(APP_NAME, appauthor=False)) / "fonts"
        # Track families already registered with QFontDatabase this session.
        self._registered: set[str] = set()

    # -- cache layout ---------------------------------------------------------

    @property
    def fonts_dir(self) -> Path:
        """Root cache directory for provisioned fonts."""
        return self._fonts_dir

    def _file_cache_dir(self) -> Path:
        return self._fonts_dir / "file"

    def _google_cache_dir(self, name: str) -> Path:
        return self._fonts_dir / "google" / _slug(name)

    # -- configuring (called from Settings, GUI thread) -----------------------

    def set_font_file(self, src: str) -> str:
        """Copy *src* into the cache and return the resolved font family.

        Raises :class:`FontError` if the file is missing/unsupported or its
        family name cannot be read.
        """
        path = Path(src)
        if not path.is_file() or path.suffix.lower() not in _FONT_SUFFIXES:
            raise FontError("Choose a .ttf, .otf or .ttc font file.")
        dest_dir = self._file_cache_dir()
        # Fresh dir so only the chosen file is on Typst's font_paths.
        if dest_dir.exists():
            shutil.rmtree(dest_dir, ignore_errors=True)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / path.name
        shutil.copy2(path, dest)
        family = self._register(dest)
        if not family:
            raise FontError("Could not read a font family from that file.")
        return family

    def download_google_font(self, name: str) -> str:
        """Download *name* from Google Fonts into the cache; return the cache dir.

        Network-only and Qt-free, so it is safe to call from a background
        thread (font *registration* must stay on the GUI thread — see
        :meth:`register_font_dir`). Raises :class:`FontError` if the family is
        unknown or the request fails.
        """
        name = name.strip()
        if not name:
            raise FontError("Enter a Google Fonts family name.")
        return str(self._download_google(name, force=True))

    def register_font_dir(self, directory: str, *, fallback: str = "") -> str:
        """Register every font file in *directory* with Qt; return the family.

        Must run on the GUI thread. *fallback* (e.g. the typed Google name) is
        returned when no file reports a usable family.
        """
        family = ""
        for ttf in self._ttf_files(Path(directory)):
            family = self._register(ttf) or family
        return family or fallback

    def set_google_font(self, name: str) -> str:
        """Download *name* from Google Fonts and return the resolved family.

        Convenience wrapper combining :meth:`download_google_font` and
        :meth:`register_font_dir`; the registration step requires the GUI
        thread. Raises :class:`FontError` if the family is unknown.
        """
        dest = self.download_google_font(name)
        return self.register_font_dir(dest, fallback=name.strip())

    # -- applying -------------------------------------------------------------

    def apply_to_app(self) -> str:
        """Register the configured font with Qt and return its family name.

        Returns ``""`` when no custom font is configured (use the default
        stack).  Never raises — provisioning failures fall back to default.
        """
        source = self._config.get("font_source", "")
        family = self._config.get("font_family", "")
        try:
            if source == "file":
                for ttf in self._ttf_files(self._file_cache_dir()):
                    self._register(ttf)
            elif source == "google":
                name = self._config.get("font_value", "")
                dest = self._download_google(name, force=False)
                for ttf in self._ttf_files(dest):
                    self._register(ttf)
            else:
                return ""
        except (FontError, OSError, requests.RequestException) as exc:
            logger.warning("Custom font unavailable, using default: %s", exc)
            return ""
        return family

    def resolve_for_report(self) -> tuple[str, str]:
        """Return ``(family, font_dir)`` for the Typst renderer.

        *family* is ``""`` and *font_dir* empty when no custom font applies.
        Ensures Google fonts are present (downloading on a cache miss).
        """
        source = self._config.get("font_source", "")
        family = self._config.get("font_family", "")
        try:
            if source == "file":
                dest = self._file_cache_dir()
                if self._ttf_files(dest):
                    return family, str(dest)
            elif source == "google":
                name = self._config.get("font_value", "")
                dest = self._download_google(name, force=False)
                if self._ttf_files(dest):
                    return family or name, str(dest)
        except (FontError, OSError, requests.RequestException) as exc:
            logger.warning("Report font unavailable, using bundled Inter: %s", exc)
        return "", ""

    # -- internals ------------------------------------------------------------

    @staticmethod
    def _ttf_files(directory: Path) -> list[Path]:
        if not directory.is_dir():
            return []
        return sorted(
            p for p in directory.iterdir() if p.suffix.lower() in _FONT_SUFFIXES
        )

    def _register(self, path: Path) -> str:
        """Add *path* to QFontDatabase; return the first family name (or "")."""
        try:
            from PySide6.QtGui import QFontDatabase
        except ImportError:  # pragma: no cover - headless without Qt
            return ""
        font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id == -1:
            logger.warning("QFontDatabase rejected font %s", path.name)
            return ""
        families = QFontDatabase.applicationFontFamilies(font_id)
        family = families[0] if families else ""
        if family:
            self._registered.add(family)
        return family

    def _download_google(self, name: str, *, force: bool) -> Path:
        """Ensure *name*'s TTF files are cached; return the cache dir.

        When *force* is false and the cache already holds TTFs, no network
        request is made.
        """
        name = name.strip()
        if not name:
            raise FontError("Enter a Google Fonts family name.")
        dest = self._google_cache_dir(name)
        if not force and self._ttf_files(dest):
            return dest

        urls = self._github_ttf_urls(name)
        if not urls:
            raise FontError(f"'{name}' was not found on Google Fonts.")

        dest.mkdir(parents=True, exist_ok=True)
        # Replace any stale partial download.
        for old in self._ttf_files(dest):
            old.unlink(missing_ok=True)
        for idx, url in enumerate(urls):
            resp = requests.get(url, headers=_GH_HEADERS, timeout=_DOWNLOAD_TIMEOUT)
            resp.raise_for_status()
            (dest / f"{_slug(name)}-{idx}.ttf").write_bytes(resp.content)
        logger.info("Downloaded %d file(s) for Google font %r", len(urls), name)
        return dest

    def _github_ttf_urls(self, name: str) -> list[str]:
        """Return TTF download URLs for *name* from the google/fonts repo.

        Tries each license directory in turn. When a family ships a variable
        font (filename contains ``[axes]``) only those file(s) are taken, which
        avoids pulling a large static weight set.
        """
        slug = re.sub(r"[^a-z0-9]+", "", name.lower())
        if not slug:
            return []
        for license_dir in _GH_LICENSE_DIRS:
            try:
                resp = requests.get(
                    f"{_GH_CONTENTS}/{license_dir}/{slug}",
                    headers=_GH_HEADERS,
                    timeout=_DOWNLOAD_TIMEOUT,
                )
            except requests.RequestException:
                continue
            if resp.status_code == 404:
                continue
            if resp.status_code == 403:
                raise FontError("GitHub rate limit reached — try again later.")
            if not resp.ok:
                continue
            entries = resp.json()
            if not isinstance(entries, list):
                continue
            ttfs = [
                e for e in entries if str(e.get("name", "")).lower().endswith(".ttf")
            ]
            variable = [e for e in ttfs if "[" in str(e.get("name", ""))]
            chosen = variable or ttfs
            urls = [e["download_url"] for e in chosen if e.get("download_url")]
            if urls:
                return urls
        return []
