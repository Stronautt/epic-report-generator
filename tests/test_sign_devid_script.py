"""Tests for the inside-out Developer-ID signing script.

``packaging/macos/sign_devid.sh`` re-signs the unsigned Nuitka ``.app`` for the
Developer-ID / notarized ``.dmg`` channel. It is the sibling of ``sign_mas.sh``
and shares its inside-out shape (strip, then sign deepest-first, the bundle
last, no ``--deep``), but it is the *inverse* on two axes:

- it references the **Dev-ID** ``entitlements.plist`` (never the MAS plists);
- its commands **enable the hardened runtime** (``--options runtime``) — the
  opposite of the MAS sandbox.

Like the MAS guard, the forbidden-flag checks run against the script's *code*
(comment lines stripped) so the header may still explain WHY ``--deep`` and
``disable-library-validation`` are absent without tripping the assertions.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "packaging" / "macos" / "sign_devid.sh"

# The POSIX execute bit and `bash -n` linting only make sense on POSIX hosts.
# These macOS packaging scripts are never run on Windows anyway.
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
        assert SCRIPT.is_file(), "missing packaging/macos/sign_devid.sh"

    @_POSIX_ONLY
    def test_script_is_executable(self) -> None:
        # The CI build job runs it directly; keep the executable bit set.
        assert SCRIPT.stat().st_mode & 0o111, "sign_devid.sh is not executable"


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
    def test_references_devid_entitlements(self, code_text: str) -> None:
        # The Dev-ID channel stamps the executables with entitlements.plist.
        assert "entitlements.plist" in code_text

    def test_does_not_reference_mas_entitlements(self, code_text: str) -> None:
        # The sandbox / inherit plists belong to sign_mas.sh, never here.
        assert "entitlements.mas" not in code_text


class TestRequiredSigningFlags:
    def test_hardened_runtime(self, code_text: str) -> None:
        # Hardened runtime is mandatory for Dev-ID notarization (MAS forbids it).
        assert "--options runtime" in code_text

    def test_secure_timestamp(self, code_text: str) -> None:
        # Notarization requires a secure timestamp on every real signature.
        assert "--timestamp" in code_text


class TestForbiddenSigningFlags:
    def test_no_deep_signing(self, code_text: str) -> None:
        # Inside-out signing replaces `--deep` *signing* entirely (deprecated;
        # does not strip first, so stale nested signatures can slip into
        # notarization). `--deep` is allowed ONLY on the `--verify` self-check,
        # where recursive validation is the supported use.
        deep_lines = [ln for ln in code_text.splitlines() if "--deep" in ln]
        assert all("--verify" in ln for ln in deep_lines), deep_lines

    def test_no_disable_library_validation(self, code_text: str) -> None:
        # Re-signing every nested Mach-O with our Team ID makes library
        # validation pass, so the script must never disable it.
        assert "disable-library-validation" not in code_text


class TestRobustness:
    def test_fail_fast(self, code_text: str) -> None:
        assert "set -euo pipefail" in code_text

    def test_signs_frameworks_as_bundles(self, code_text: str) -> None:
        # Sign each *.framework as a bundle (respecting Versions/Current).
        assert "-name '*.framework'" in code_text

    def test_app_bundle_signed_before_verify(self, code_text: str) -> None:
        # Inside-out: the .app is signed (sign_exe "$APP") after all nested code,
        # and verification comes last.
        sign_app_idx = code_text.index('sign_exe "$APP"')
        verify_idx = code_text.index("--verify")
        assert sign_app_idx < verify_idx


class TestAdHocFallback:
    """With no identity (forks / no-secrets CI) the script must still sign
    inside-out ad-hoc — the only branch exercised when build.yml passes an empty
    ``${MACOS_SIGN_IDENTITY:-}``."""

    def test_detects_empty_identity(self, code_text: str) -> None:
        assert '-z "$IDENTITY"' in code_text

    def test_adhoc_signs_without_runtime_or_entitlements(self, code_text: str) -> None:
        # The ad-hoc branch signs with `--sign "$IDENTITY"` (set to "-") and
        # neither a hardened runtime nor entitlements.
        assert "ADHOC" in code_text
        assert 'IDENTITY="-"' in code_text
