"""Detect whether the app was installed from a managed app store.

Store-distributed builds (Mac App Store, Microsoft Store, Snap, Flatpak) update
themselves through the store, and a self-update prompt is both pointless and a
policy violation there. The update checker is therefore disabled when
:func:`is_store_install` is true.

Everything here is best-effort and dependency-free: it inspects the bundle
layout, a couple of Win32 package APIs, and well-known sandbox environment
variables. It never raises — any probe that fails is treated as "not a store"
(the safe default, since the GH-installer builds — Inno Setup .exe, .dmg,
AppImage — are the common case and must keep update checking enabled).
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def _mac_app_store() -> bool:
    """True when running from a Mac App Store ``.app`` bundle.

    MAS apps carry a ``Contents/_MASReceipt/receipt`` file; a notarised .dmg
    build (our GH installer) does not. Walks up from the executable to the
    enclosing ``.app`` bundle and checks for that receipt.
    """
    try:
        exe = Path(sys.executable).resolve()
    except OSError:
        return False
    for parent in (exe, *exe.parents):
        if parent.suffix == ".app":
            return (parent / "Contents" / "_MASReceipt" / "receipt").is_file()
    return False


def _windows_store() -> bool:
    """True when the process has MSIX/Microsoft Store package identity.

    ``GetCurrentPackageFullName`` returns ``APPMODEL_ERROR_NO_PACKAGE`` (15700)
    for an unpackaged process (our Inno Setup install) and a different code when
    running with package identity (Store/MSIX). Falls back to the install
    location (``WindowsApps``) if the API is unavailable.
    """
    APPMODEL_ERROR_NO_PACKAGE = 15700
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        get_name = kernel32.GetCurrentPackageFullName
        get_name.argtypes = [ctypes.POINTER(wintypes.UINT), wintypes.LPWSTR]
        get_name.restype = wintypes.LONG
        length = wintypes.UINT(0)
        rc = get_name(ctypes.byref(length), None)
        return rc != APPMODEL_ERROR_NO_PACKAGE
    except (OSError, AttributeError, ValueError):
        # API missing (pre-Win8) or call failed — fall back to the path.
        return "windowsapps" in sys.executable.lower()


def _linux_store() -> str | None:
    """Return the Linux store name (Snap/Flatpak) when sandboxed, else None.

    AppImage (our GH installer) sets ``APPIMAGE``/``APPDIR`` instead and is
    deliberately *not* matched here.
    """
    if os.environ.get("SNAP") and os.environ.get("SNAP_NAME"):
        return "Snap"
    if os.environ.get("FLATPAK_ID") or Path("/.flatpak-info").is_file():
        return "Flatpak"
    return None


def store_source() -> str | None:
    """Return a human-readable store name if this is a store install, else None.

    Used both to gate the update checker and to log *why* it was disabled.
    """
    try:
        if sys.platform == "darwin":
            return "Mac App Store" if _mac_app_store() else None
        if sys.platform == "win32":
            return "Microsoft Store" if _windows_store() else None
        if sys.platform.startswith("linux"):
            return _linux_store()
    except Exception:  # noqa: BLE001 - detection must never break startup
        logger.debug("Store-install detection failed", exc_info=True)
    return None


def is_store_install() -> bool:
    """True when the app was installed from a managed app store."""
    return store_source() is not None
