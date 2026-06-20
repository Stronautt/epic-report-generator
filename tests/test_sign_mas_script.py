"""Tests for the inside-out Mac App Store signing script.

``packaging/macos/sign_mas.sh`` re-signs a single unsigned Nuitka ``.app`` for
the Mac App Store. The script itself is not Python, so the guards are static:

- it parses cleanly under ``bash -n`` (syntax lint);
- it references the **MAS** entitlements (container + inherit), never the
  Dev-ID ``entitlements.plist``;
- its **commands** never use ``--deep`` (which would stamp nested code with the
  container entitlements) or ``disable-library-validation`` (re-signing every
  nested Mach-O with our Team ID makes library validation pass on its own);
- it is fail-fast (``set -euo pipefail``) and signs frameworks as bundles.

The forbidden-flag guards run against the script's *code* (comment lines
stripped) so the header may still explain WHY those flags are absent without
tripping the substring assertions.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "packaging" / "macos" / "sign_mas.sh"

# The POSIX execute bit and `bash -n` linting only make sense on POSIX hosts.
# On Windows the git checkout carries no execute bit (NTFS has none) and the
# `bash` on PATH is the WSL launcher stub, which errors out with no distro
# installed. These macOS packaging scripts are never run on Windows anyway.
_POSIX_ONLY = pytest.mark.skipif(
    sys.platform == "win32", reason="POSIX-only check (executable bit / bash)"
)


def _strip_comments(text: str) -> str:
    """Return only the executable lines (drop whole-line ``#`` comments)."""
    return "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )


@pytest.fixture(scope="module")
def script_text() -> str:
    return SCRIPT.read_text()


@pytest.fixture(scope="module")
def code_text(script_text: str) -> str:
    return _strip_comments(script_text)


class TestFileExists:
    def test_script_present(self) -> None:
        assert SCRIPT.is_file(), "missing packaging/macos/sign_mas.sh"

    @_POSIX_ONLY
    def test_script_is_executable(self) -> None:
        # The CI MAS job runs it directly; keep the executable bit set.
        assert SCRIPT.stat().st_mode & 0o111, "sign_mas.sh is not executable"


class TestSyntax:
    @_POSIX_ONLY
    @pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
    def test_bash_syntax_lint(self) -> None:
        result = subprocess.run(
            ["bash", "-n", str(SCRIPT)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr


class TestEntitlementsReferences:
    def test_references_mas_container_entitlements(self, code_text: str) -> None:
        assert "entitlements.mas.plist" in code_text

    def test_references_mas_inherit_entitlements(self, code_text: str) -> None:
        assert "entitlements.mas.inherit.plist" in code_text

    def test_does_not_reference_devid_entitlements(self, code_text: str) -> None:
        # The bare Dev-ID plist name must not appear (the MAS names share the
        # "entitlements" stem but never the exact "entitlements.plist" token).
        assert "entitlements.plist" not in code_text


class TestForbiddenSigningFlags:
    def test_no_deep_signing(self, code_text: str) -> None:
        # `--deep` is wrong for MAS: it stamps nested code with the parent's
        # entitlements instead of signing inside-out.
        assert "--deep" not in code_text

    def test_no_disable_library_validation(self, code_text: str) -> None:
        # Every nested Mach-O is re-signed with our Team ID, so library
        # validation passes without disabling it.
        assert "disable-library-validation" not in code_text

    def test_no_hardened_runtime(self, code_text: str) -> None:
        # Hardened runtime is a Dev-ID/notarization concept; MAS uses the
        # sandbox instead.
        assert "--options runtime" not in code_text

    def test_no_cs_entitlements(self, code_text: str) -> None:
        assert "com.apple.security.cs." not in code_text


class TestApplicationIdentifier:
    """The signature must carry com.apple.application-identifier matching the
    provisioning profile, or TestFlight rejects the build (ITMS-90886)."""

    def test_adds_application_identifier(self, code_text: str) -> None:
        assert "com.apple.application-identifier" in code_text

    def test_adds_team_identifier(self, code_text: str) -> None:
        assert "com.apple.developer.team-identifier" in code_text

    def test_derives_from_profile(self, code_text: str) -> None:
        # Prefer the exact value decoded from the embedded provisioning profile.
        assert "security cms -D" in code_text

    def test_falls_back_to_team_id_env(self, code_text: str) -> None:
        # When no profile entitlement is available, derive from APPLE_TEAM_ID.
        assert "APPLE_TEAM_ID" in code_text

    def test_signs_app_with_augmented_entitlements(self, code_text: str) -> None:
        # The augmented file is assigned back to $ENTITLEMENTS, which step 7 uses
        # to sign the app bundle (and thus the main executable).
        assert 'ENTITLEMENTS="$AUGMENTED_ENT"' in code_text


class TestRobustness:
    def test_fail_fast(self, code_text: str) -> None:
        assert "set -euo pipefail" in code_text

    def test_signs_frameworks_as_bundles(self, code_text: str) -> None:
        # Sign each *.framework as a bundle (respecting Versions/Current).
        assert "-name '*.framework'" in code_text

    def test_app_bundle_signed_before_verify(self, code_text: str) -> None:
        # Inside-out: the .app gets the container entitlements after all nested
        # code is signed, and verification comes last.
        sign_app_idx = code_text.index('--entitlements "$ENTITLEMENTS"')
        verify_idx = code_text.index("--verify")
        assert sign_app_idx < verify_idx
