"""Tests for the shared unsigned ``.app`` export in CI.

The macOS build leg must, after Nuitka + strip and **before** the Developer-ID
sign, archive the unsigned bundle with ``ditto`` and upload it as the
``unsigned-macos-app`` artifact that the decoupled ``mas-upload`` job re-signs
for the App Store.

The workflow is parsed with ``yaml.safe_load`` so the assertions track the real
step list and its ordering (strip → archive → Developer-ID sign).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
BUILD_YML = REPO_ROOT / ".github" / "workflows" / "build.yml"

ARTIFACT_NAME = "unsigned-macos-app"


def _load_workflow() -> dict[str, Any]:
    return yaml.safe_load(BUILD_YML.read_text(encoding="utf-8"))


def _build_steps() -> list[dict[str, Any]]:
    return _load_workflow()["jobs"]["build"]["steps"]


def _index_by_name(steps: list[dict[str, Any]], needle: str) -> int:
    for i, step in enumerate(steps):
        if needle in str(step.get("name", "")):
            return i
    raise AssertionError(f"no build step matching {needle!r}")


class TestArchiveStep:
    def setup_method(self) -> None:
        self.steps = _build_steps()
        self.archive = self.steps[_index_by_name(self.steps, "Archive unsigned .app")]

    def test_archive_step_exists_and_macos_only(self) -> None:
        assert "macOS" in self.archive["if"]

    def test_archive_uses_ditto_keepparent(self) -> None:
        run = self.archive["run"]
        # ditto preserves the bundle's symlinks/permissions that zip mangles.
        assert "ditto -c -k" in run
        assert "--keepParent" in run
        assert "unsigned-app.zip" in run

    def test_archive_targets_the_app_bundle(self) -> None:
        assert "Epic Report Generator.app" in self.archive["run"]


class TestUploadStep:
    def setup_method(self) -> None:
        self.steps = _build_steps()
        self.upload = self.steps[_index_by_name(self.steps, "Upload unsigned .app")]

    def test_upload_uses_upload_artifact_action(self) -> None:
        assert "upload-artifact" in self.upload["uses"]

    def test_upload_artifact_name_and_path(self) -> None:
        with_ = self.upload["with"]
        assert with_["name"] == ARTIFACT_NAME
        assert with_["path"] == "unsigned-app.zip"

    def test_upload_retention_three_days(self) -> None:
        assert int(self.upload["with"]["retention-days"]) == 3

    def test_upload_macos_only(self) -> None:
        assert "macOS" in self.upload["if"]


class TestStepOrdering:
    """strip → archive → upload → Developer-ID sign, all before the DMG."""

    def setup_method(self) -> None:
        self.steps = _build_steps()

    def test_archive_after_strip(self) -> None:
        strip = _index_by_name(self.steps, "Strip binaries (macOS)")
        archive = _index_by_name(self.steps, "Archive unsigned .app")
        assert strip < archive

    def test_archive_before_dev_id_sign(self) -> None:
        archive = _index_by_name(self.steps, "Archive unsigned .app")
        sign = _index_by_name(self.steps, "Sign binaries (macOS)")
        assert archive < sign

    def test_upload_between_archive_and_sign(self) -> None:
        archive = _index_by_name(self.steps, "Archive unsigned .app")
        upload = _index_by_name(self.steps, "Upload unsigned .app")
        sign = _index_by_name(self.steps, "Sign binaries (macOS)")
        assert archive < upload < sign

    def test_unsigned_export_before_dmg(self) -> None:
        # The MAS handoff must capture the bundle before the DMG packaging.
        archive = _index_by_name(self.steps, "Archive unsigned .app")
        dmg = _index_by_name(self.steps, "Build macOS DMG")
        assert archive < dmg


class TestStripNoLongerSigns:
    """The split moved signing out of the strip step into its own step."""

    def test_strip_step_does_not_codesign(self) -> None:
        steps = _build_steps()
        strip = steps[_index_by_name(steps, "Strip binaries (macOS)")]
        assert "codesign" not in strip["run"]

    def test_sign_step_invokes_devid_script(self) -> None:
        steps = _build_steps()
        sign = steps[_index_by_name(steps, "Sign binaries (macOS)")]
        # Signing moved out of the inline `codesign --deep` block into the
        # inside-out Dev-ID signer (mirrors how the MAS job calls sign_mas.sh).
        assert "packaging/macos/sign_devid.sh" in sign["run"]
        # The signing identity is threaded through as the script's 2nd arg; an
        # empty value drives the ad-hoc fallback (forks / no secrets).
        assert "MACOS_SIGN_IDENTITY" in sign["run"]
