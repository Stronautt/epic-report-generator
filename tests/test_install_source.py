"""Tests for epic_report_generator.services.install_source."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

import epic_report_generator.services.install_source as ins


class TestMacAppStore:
    def test_bundle_with_receipt_is_store(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        bundle = tmp_path / "Epic Report Generator.app"
        exe = bundle / "Contents" / "MacOS" / "Epic Report Generator"
        exe.parent.mkdir(parents=True)
        exe.write_text("")
        receipt = bundle / "Contents" / "_MASReceipt" / "receipt"
        receipt.parent.mkdir(parents=True)
        receipt.write_text("x")
        monkeypatch.setattr(sys, "executable", str(exe))
        assert ins._mac_app_store() is True

    def test_bundle_without_receipt_is_not_store(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        bundle = tmp_path / "Epic Report Generator.app"
        exe = bundle / "Contents" / "MacOS" / "Epic Report Generator"
        exe.parent.mkdir(parents=True)
        exe.write_text("")
        monkeypatch.setattr(sys, "executable", str(exe))
        assert ins._mac_app_store() is False

    def test_non_bundle_executable_is_not_store(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        exe = tmp_path / "bin" / "app"
        exe.parent.mkdir(parents=True)
        exe.write_text("")
        monkeypatch.setattr(sys, "executable", str(exe))
        assert ins._mac_app_store() is False


class TestLinuxStore:
    def test_snap(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SNAP", "/snap/epic/42")
        monkeypatch.setenv("SNAP_NAME", "epic")
        monkeypatch.delenv("FLATPAK_ID", raising=False)
        assert ins._linux_store() == "Snap"

    def test_flatpak_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SNAP", raising=False)
        monkeypatch.delenv("SNAP_NAME", raising=False)
        monkeypatch.setenv("FLATPAK_ID", "com.example.Epic")
        assert ins._linux_store() == "Flatpak"

    def test_plain_install_is_not_store(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for var in ("SNAP", "SNAP_NAME", "FLATPAK_ID"):
            monkeypatch.delenv(var, raising=False)
        # AppImage env must NOT count as a store (it is the GH installer).
        monkeypatch.setenv("APPIMAGE", "/home/u/Epic.AppImage")
        assert ins._linux_store() is None


class TestStoreSourceDispatch:
    def test_darwin_store(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "platform", "darwin")
        monkeypatch.setattr(ins, "_mac_app_store", lambda: True)
        assert ins.store_source() == "Mac App Store"
        assert ins.is_store_install() is True

    def test_darwin_not_store(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "platform", "darwin")
        monkeypatch.setattr(ins, "_mac_app_store", lambda: False)
        assert ins.store_source() is None
        assert ins.is_store_install() is False

    def test_win32_store(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setattr(ins, "_windows_store", lambda: True)
        assert ins.store_source() == "Microsoft Store"

    def test_linux_store(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setattr(ins, "_linux_store", lambda: "Flatpak")
        assert ins.store_source() == "Flatpak"

    def test_unknown_platform(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "platform", "freebsd13")
        assert ins.store_source() is None

    def test_detection_errors_are_swallowed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sys, "platform", "darwin")

        def boom() -> bool:
            raise RuntimeError("probe blew up")

        monkeypatch.setattr(ins, "_mac_app_store", boom)
        # Must never propagate — detection failure means "not a store".
        assert ins.store_source() is None
