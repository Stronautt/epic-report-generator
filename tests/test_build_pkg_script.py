"""Tests for the Mac App Store ``.pkg`` build helper.

``packaging/macos/build_pkg.sh`` wraps the MAS-signed ``.app`` in a signed
installer ``.pkg`` (``productbuild``) and, when ASC creds are present, validates
it with ``xcrun altool --validate-app``. The script is shell, so the guards are
static:

- it parses cleanly under ``bash -n`` (syntax lint);
- it signs the package with the **Mac Installer Distribution** identity (the
  installer cert), never the Apple Distribution app cert;
- it installs the bundle into ``/Applications`` via ``productbuild --component``;
- the ``--validate-app`` step is gated on the ASC API-key env vars;
- it is fail-fast (``set -euo pipefail``).

The forbidden/asserted-string guards run against the script's *code* (comment
lines stripped) so the header may explain the identities without tripping the
substring assertions.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "packaging" / "macos" / "build_pkg.sh"

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
        assert SCRIPT.is_file(), "missing packaging/macos/build_pkg.sh"

    @_POSIX_ONLY
    def test_script_is_executable(self) -> None:
        # The CI MAS job runs it directly; keep the executable bit set.
        assert SCRIPT.stat().st_mode & 0o111, "build_pkg.sh is not executable"


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


class TestProductbuild:
    def test_uses_productbuild(self, code_text: str) -> None:
        assert "productbuild" in code_text

    def test_targets_applications(self, code_text: str) -> None:
        # --component <app> /Applications installs into the App Store location.
        assert "--component" in code_text
        assert "/Applications" in code_text


class TestInstallerIdentity:
    def test_signs_with_installer_identity(self, code_text: str) -> None:
        # The .pkg must be signed with the Mac Installer Distribution cert,
        # surfaced through the MAC_INSTALLER_IDENTITY env var / arg.
        assert "MAC_INSTALLER_IDENTITY" in code_text
        assert "--sign" in code_text

    def test_does_not_sign_with_app_identity(self, code_text: str) -> None:
        # The Apple Distribution / app-signing identity belongs to sign_mas.sh,
        # not the installer wrapper.
        assert "APPLE_DIST_IDENTITY" not in code_text


class TestValidation:
    def test_validate_app_present(self, code_text: str) -> None:
        assert "--validate-app" in code_text
        assert "altool" in code_text

    def test_validation_gated_on_asc_creds(self, code_text: str) -> None:
        # The validate step only runs when the ASC API key vars are present.
        assert "ASC_KEY_ID" in code_text
        assert "ASC_ISSUER_ID" in code_text


class TestRobustness:
    def test_fail_fast(self, code_text: str) -> None:
        assert "set -euo pipefail" in code_text

    def test_requires_installer_identity(self, code_text: str) -> None:
        # Missing identity must fail fast rather than emit an unsigned package.
        assert 'die "no installer identity' in code_text
