"""Tests for the macOS bundle identity and MAS-required Info.plist keys.

Covers one registered ``CFBundleIdentifier`` shared by both channels, the
MAS-required Info.plist keys, and a monotonic ``CFBundleVersion`` stamped in CI.

The shipped ``Info.plist`` is produced by Nuitka + ``plutil`` in CI (not
available here), so the build-side assertions verify that the CI workflow feeds
the right values into the ``plutil`` steps. The Python side asserts the shared
constant and the ``desktop._INFO_PLIST`` template.
"""

from __future__ import annotations

import plistlib
from pathlib import Path
from typing import Any

import yaml

import epic_report_generator.desktop as desktop

REPO_ROOT = Path(__file__).resolve().parents[1]
BUILD_YML = REPO_ROOT / ".github" / "workflows" / "build.yml"

EXPECTED_BUNDLE_ID = "com.epicreportgenerator.app"


def _load_workflow() -> dict[str, Any]:
    return yaml.safe_load(BUILD_YML.read_text(encoding="utf-8"))


def _build_steps() -> list[dict[str, Any]]:
    return _load_workflow()["jobs"]["build"]["steps"]


def _step_by_name(steps: list[dict[str, Any]], needle: str) -> dict[str, Any]:
    for step in steps:
        if needle in str(step.get("name", "")):
            return step
    raise AssertionError(f"no build step matching {needle!r}")


class TestSharedConstant:
    def test_bundle_id_value(self) -> None:
        assert desktop.BUNDLE_ID == EXPECTED_BUNDLE_ID

    def test_info_plist_uses_constant(self) -> None:
        """``desktop._INFO_PLIST`` formats with the shared constant."""
        # The hardcoded literal must be gone; only the placeholder remains.
        assert "{bundle_id}" in desktop._INFO_PLIST
        assert EXPECTED_BUNDLE_ID not in desktop._INFO_PLIST

        rendered = desktop._INFO_PLIST.format(
            name=desktop.APP_NAME,
            executable=desktop.APP_ID,
            bundle_id=desktop.BUNDLE_ID,
        )
        parsed = plistlib.loads(rendered.encode("utf-8"))
        assert parsed["CFBundleIdentifier"] == EXPECTED_BUNDLE_ID
        assert parsed["CFBundleName"] == desktop.APP_NAME
        assert parsed["CFBundleExecutable"] == desktop.APP_ID


class TestBuildWorkflowBundleId:
    def test_mas_bundle_id_env_matches_constant(self) -> None:
        """CI build var is the single source of truth, matching desktop.py."""
        env = _load_workflow()["env"]
        assert env["MAS_BUNDLE_ID"] == EXPECTED_BUNDLE_ID
        assert env["MAS_BUNDLE_ID"] == desktop.BUNDLE_ID

    def test_macos_deployment_target_present(self) -> None:
        env = _load_workflow()["env"]
        # arm64-only App Store builds require a 12.0+ deployment target
        # (ITMS-90869); both channels share this floor.
        assert str(env["MACOS_DEPLOYMENT_TARGET"]).startswith("12")

    def test_nuitka_uses_signed_app_name(self) -> None:
        run = _step_by_name(_build_steps(), "Build Nuitka binary")["run"]
        assert "--macos-signed-app-name=$MAS_BUNDLE_ID" in run

    def test_checkout_has_full_history(self) -> None:
        """git rev-list --count HEAD needs full history (fetch-depth: 0)."""
        checkout = _build_steps()[0]
        assert "checkout" in checkout["uses"]
        assert checkout["with"]["fetch-depth"] == 0


class TestInfoPlistStampStep:
    def setup_method(self) -> None:
        self.run = _step_by_name(
            _build_steps(), "Set bundle identity + Info.plist keys"
        )["run"]

    def test_sets_bundle_identifier_from_env(self) -> None:
        assert (
            'plutil -replace CFBundleIdentifier -string "$MAS_BUNDLE_ID"' in self.run
        )

    def test_sets_application_category(self) -> None:
        assert (
            "plutil -replace LSApplicationCategoryType -string "
            '"public.app-category.productivity"' in self.run
        )

    def test_sets_encryption_exempt_false(self) -> None:
        assert (
            "plutil -replace ITSAppUsesNonExemptEncryption -bool false" in self.run
        )

    def test_sets_minimum_system_version_from_env(self) -> None:
        assert (
            'plutil -replace LSMinimumSystemVersion -string "$MACOS_DEPLOYMENT_TARGET"'
            in self.run
        )

    def test_stamps_monotonic_build_number(self) -> None:
        assert "git rev-list --count HEAD" in self.run
        assert (
            'plutil -replace CFBundleVersion -string "$BUILD_NUMBER"' in self.run
        )

    def test_marketing_version_distinct_from_build_number(self) -> None:
        # CFBundleShortVersionString stays the pyproject marketing version.
        assert "CFBundleShortVersionString" in self.run

    def test_runs_only_on_macos(self) -> None:
        step = _step_by_name(
            _build_steps(), "Set bundle identity + Info.plist keys"
        )
        assert "macOS" in step["if"]


class TestMachOMinVersionStep:
    """A vtool step rewrites the Mach-O minos so an arm64-only build passes
    App Store validation (ITMS-90869 reads the binary minos, not the plist)."""

    def setup_method(self) -> None:
        self.step = _step_by_name(_build_steps(), "Set Mach-O minimum macOS version")

    def test_runs_only_on_macos(self) -> None:
        assert "macOS" in self.step["if"]

    def test_uses_vtool_with_deployment_target(self) -> None:
        run = self.step["run"]
        assert "vtool -set-build-version macos" in run
        assert "$MACOS_DEPLOYMENT_TARGET" in run

    def test_runs_before_signing_and_archive(self) -> None:
        """minos must be rewritten before the unsigned .app is archived (→ MAS)
        and before the Dev-ID signing step, or those binaries keep the old minos
        (vtool edits load commands and would invalidate a later-applied sig)."""
        names = [str(s.get("name", "")) for s in _build_steps()]
        vtool_idx = names.index("Set Mach-O minimum macOS version (macOS)")
        archive_idx = names.index("Archive unsigned .app (macOS)")
        sign_idx = names.index("Sign binaries (macOS)")
        assert vtool_idx < archive_idx
        assert vtool_idx < sign_idx
