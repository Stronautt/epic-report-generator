"""Tests for the Mac App Store entitlements property lists.

Covers three MAS plists under ``packaging/macos/`` — the sandboxed container
(``entitlements.mas.plist``), the nested Mach-O inherit plist
(``entitlements.mas.inherit.plist``), and the future OAuth-enabled container
(``entitlements.mas.oauth.plist``).

These are signing inputs, never parsed by the app, so the guards are static:

- required sandbox/network/file keys are present with the right boolean values;
- the v1 plists carry **no** ``com.apple.security.cs.*`` key (those stay on the
  Dev-ID build and are MAS-illegal);
- no plist contains an XML comment (``<!--``) — AMFI's entitlements parser
  rejects them outright ("AMFIUnserializeXML: syntax error");
- the Dev-ID ``entitlements.plist`` keeps its executable-memory ``cs.*`` keys
  (``allow-jit`` / ``allow-unsigned-executable-memory``) but no longer disables
  library validation — inside-out signing makes that exception unnecessary;
- the future ``oauth`` plist differs from v1 **only** by ``network.server``.
"""

from __future__ import annotations

import plistlib
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
MACOS_DIR = REPO_ROOT / "packaging" / "macos"

CONTAINER_PLIST = MACOS_DIR / "entitlements.mas.plist"
INHERIT_PLIST = MACOS_DIR / "entitlements.mas.inherit.plist"
OAUTH_PLIST = MACOS_DIR / "entitlements.mas.oauth.plist"
DEVID_PLIST = MACOS_DIR / "entitlements.plist"

# v1 MAS plists (the OAuth one is a future, not-yet-shipped variant).
V1_PLISTS = (CONTAINER_PLIST, INHERIT_PLIST)
ALL_MAS_PLISTS = (CONTAINER_PLIST, INHERIT_PLIST, OAUTH_PLIST)

SANDBOX = "com.apple.security.app-sandbox"
NETWORK_CLIENT = "com.apple.security.network.client"
NETWORK_SERVER = "com.apple.security.network.server"
FILES_RW = "com.apple.security.files.user-selected.read-write"
INHERIT = "com.apple.security.inherit"
CS_PREFIX = "com.apple.security.cs."


def _load(path: Path) -> dict[str, Any]:
    return plistlib.loads(path.read_bytes())


class TestFilesExist:
    def test_all_mas_plists_present(self) -> None:
        for path in ALL_MAS_PLISTS:
            assert path.is_file(), f"missing MAS plist {path.name}"


class TestNoXmlComments:
    """AMFI rejects ``<!-- ... -->`` comments in entitlements plists."""

    def test_no_comment_in_any_mas_plist(self) -> None:
        for path in ALL_MAS_PLISTS:
            assert b"<!--" not in path.read_bytes(), f"XML comment in {path.name}"


class TestContainerPlist:
    def setup_method(self) -> None:
        self.data = _load(CONTAINER_PLIST)

    def test_app_sandbox_enabled(self) -> None:
        assert self.data[SANDBOX] is True

    def test_network_client_enabled(self) -> None:
        assert self.data[NETWORK_CLIENT] is True

    def test_user_selected_files_read_write(self) -> None:
        # Required: without it the powerbox denies write to the chosen export
        # location and PDF export fails silently.
        assert self.data[FILES_RW] is True

    def test_no_network_server(self) -> None:
        # v1 is API-Token-only; loopback OAuth (network.server) is deferred.
        assert NETWORK_SERVER not in self.data


class TestInheritPlist:
    def setup_method(self) -> None:
        self.data = _load(INHERIT_PLIST)

    def test_app_sandbox_enabled(self) -> None:
        assert self.data[SANDBOX] is True

    def test_inherit_enabled(self) -> None:
        assert self.data[INHERIT] is True

    def test_only_sandbox_and_inherit(self) -> None:
        assert set(self.data) == {SANDBOX, INHERIT}


class TestNoCodeSigningEntitlements:
    """The MAS v1 plists must carry no ``cs.*`` keys (Dev-ID only)."""

    def test_no_cs_keys_in_v1_plists(self) -> None:
        for path in V1_PLISTS:
            data = _load(path)
            cs_keys = [k for k in data if k.startswith(CS_PREFIX)]
            assert not cs_keys, f"{path.name} has cs.* keys: {cs_keys}"

    def test_oauth_plist_has_no_cs_keys(self) -> None:
        data = _load(OAUTH_PLIST)
        assert not [k for k in data if k.startswith(CS_PREFIX)]


class TestDevIdPlist:
    """The Dev-ID plist keeps its executable-memory ``cs.*`` entitlements but
    no longer disables library validation (inside-out signing under one Team ID
    makes library validation pass on its own); not a MAS plist."""

    def test_devid_keeps_executable_memory_cs_keys(self) -> None:
        data = _load(DEVID_PLIST)
        # CPython/Qt need W^X relaxation — unrelated to library loading.
        assert "com.apple.security.cs.allow-jit" in data
        assert "com.apple.security.cs.allow-unsigned-executable-memory" in data

    def test_devid_does_not_disable_library_validation(self) -> None:
        # Dropped: sign_devid.sh re-signs every nested Mach-O with our Team ID,
        # so the hardened runtime can enforce library validation.
        assert "com.apple.security.cs.disable-library-validation" not in _load(DEVID_PLIST)

    def test_devid_is_not_sandboxed(self) -> None:
        assert SANDBOX not in _load(DEVID_PLIST)


class TestOAuthPlistDiff:
    """The future OAuth plist differs from v1 container only by network.server."""

    def test_oauth_is_superset_by_network_server(self) -> None:
        container = _load(CONTAINER_PLIST)
        oauth = _load(OAUTH_PLIST)
        assert set(oauth) - set(container) == {NETWORK_SERVER}
        assert set(container) - set(oauth) == set()

    def test_shared_keys_have_identical_values(self) -> None:
        container = _load(CONTAINER_PLIST)
        oauth = _load(OAUTH_PLIST)
        for key in container:
            assert oauth[key] == container[key]

    def test_oauth_enables_network_server(self) -> None:
        assert _load(OAUTH_PLIST)[NETWORK_SERVER] is True
