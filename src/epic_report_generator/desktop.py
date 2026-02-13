"""Install and uninstall desktop launcher shortcuts."""

from __future__ import annotations

import logging
import os
import shutil
import stat
import sys
from pathlib import Path

from epic_report_generator.resources_util import get_resource_path

logger = logging.getLogger(__name__)

APP_ID = "epic-report-generator"
APP_NAME = "Epic Report Generator"
_GUI_ENTRY_POINT = "epic-report-generator-gui"


def _resolve_gui_bin() -> str:
    """Return the absolute path to the ``epic-report-generator-gui`` binary.

    Raises :class:`SystemExit` with a helpful message when the entry-point
    cannot be found on ``PATH``.
    """
    found = shutil.which(_GUI_ENTRY_POINT)
    if found is None:
        logger.error(
            "Could not find '%s' on PATH. "
            "Make sure the package is installed (pip install epic-report-generator) "
            "and the entry-point is available before running --install-desktop.",
            _GUI_ENTRY_POINT,
        )
        raise SystemExit(1)
    return str(Path(found).resolve())


# ---------------------------------------------------------------------------
# Linux (freedesktop.org)
# ---------------------------------------------------------------------------

_DESKTOP_ENTRY = """\
[Desktop Entry]
Type=Application
Name=Epic Report Generator
Comment=Generate PDF Epic progress reports from Jira Cloud
Exec={bin_path}
Terminal=false
Icon={icon_path}
Categories=Office;ProjectManagement;
Keywords=jira;epic;report;pdf;
StartupWMClass=epic-report-generator
"""


def _xdg_data_home() -> Path:
    """Return ``$XDG_DATA_HOME``, defaulting to ``~/.local/share``."""
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")


def _linux_install() -> None:
    icon_src = get_resource_path("logo.png")
    bin_path = _resolve_gui_bin()

    data_home = _xdg_data_home()

    # Install icon first so we can reference its absolute path in the .desktop
    icon_dst = data_home / "icons" / "hicolor" / "256x256" / "apps" / f"{APP_ID}.png"
    icon_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(icon_src, icon_dst)
    logger.info("Installed %s", icon_dst)

    # Write .desktop file with absolute paths to avoid PATH issues
    desktop_dst = data_home / "applications" / f"{APP_ID}.desktop"
    desktop_dst.parent.mkdir(parents=True, exist_ok=True)
    desktop_dst.write_text(
        _DESKTOP_ENTRY.format(bin_path=bin_path, icon_path=icon_dst),
        encoding="utf-8",
    )
    logger.info("Installed %s", desktop_dst)


def _linux_uninstall() -> None:
    data_home = _xdg_data_home()

    for path in (
        data_home / "applications" / f"{APP_ID}.desktop",
        data_home / "icons" / "hicolor" / "256x256" / "apps" / f"{APP_ID}.png",
    ):
        if path.exists():
            path.unlink()
            logger.info("Removed %s", path)
        else:
            logger.info("Not found, skipping: %s", path)


# ---------------------------------------------------------------------------
# macOS (.app bundle)
# ---------------------------------------------------------------------------

_MACOS_APP_DIR = Path.home() / "Applications"
_MACOS_APP_BUNDLE = _MACOS_APP_DIR / f"{APP_NAME}.app"

_INFO_PLIST = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>{name}</string>
    <key>CFBundleIdentifier</key>
    <string>com.epicreportgenerator.app</string>
    <key>CFBundleExecutable</key>
    <string>{executable}</string>
    <key>CFBundleIconFile</key>
    <string>icon.png</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleVersion</key>
    <string>1.0</string>
</dict>
</plist>
"""

_LAUNCHER_SCRIPT = """\
#!/bin/bash
# macOS .app bundles launched from Finder get a minimal PATH that does not
# include pip/pipx/Homebrew bin directories.  We bake the absolute path to
# the GUI entry-point at install time so the app starts reliably.
exec {bin_path} "$@"
"""


def _macos_install() -> None:
    icon_src = get_resource_path("logo.png")
    bin_path = _resolve_gui_bin()

    contents = _MACOS_APP_BUNDLE / "Contents"
    macos_dir = contents / "MacOS"
    resources_dir = contents / "Resources"

    macos_dir.mkdir(parents=True, exist_ok=True)
    resources_dir.mkdir(parents=True, exist_ok=True)

    # Info.plist
    plist = contents / "Info.plist"
    plist.write_text(
        _INFO_PLIST.format(name=APP_NAME, executable=APP_ID),
        encoding="utf-8",
    )

    # Launcher script
    launcher = macos_dir / APP_ID
    launcher.write_text(
        _LAUNCHER_SCRIPT.format(bin_path=bin_path), encoding="utf-8",
    )
    launcher.chmod(launcher.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    # Icon
    shutil.copy2(icon_src, resources_dir / "icon.png")

    logger.info("Installed %s", _MACOS_APP_BUNDLE)


def _macos_uninstall() -> None:
    if _MACOS_APP_BUNDLE.exists():
        shutil.rmtree(_MACOS_APP_BUNDLE)
        logger.info("Removed %s", _MACOS_APP_BUNDLE)
    else:
        logger.info("Not found, skipping: %s", _MACOS_APP_BUNDLE)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def install_desktop() -> None:
    """Install a desktop launcher shortcut for the current platform."""
    platform = sys.platform
    if platform == "linux":
        _linux_install()
    elif platform == "darwin":
        _macos_install()
    elif platform == "win32":
        logger.info("Windows desktop shortcuts are handled by the installer.")
    else:
        logger.warning("Unsupported platform for desktop integration: %s", platform)


def uninstall_desktop() -> None:
    """Remove the desktop launcher shortcut for the current platform."""
    platform = sys.platform
    if platform == "linux":
        _linux_uninstall()
    elif platform == "darwin":
        _macos_uninstall()
    elif platform == "win32":
        logger.info("Windows desktop shortcuts are handled by the installer.")
    else:
        logger.warning("Unsupported platform for desktop integration: %s", platform)
