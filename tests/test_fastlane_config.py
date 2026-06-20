"""Tests for the fastlane configuration of the Mac App Store channel.

Covers ``fastlane/Appfile`` and ``fastlane/Fastfile`` (lanes
``bootstrap``/``profile``/``beta``/``release`` with an ASC API key, **no
Matchfile**) plus a ``Gemfile`` pinning fastlane for reproducible CI installs.

The config is Ruby, so the guards are static:

- the ``Appfile``, ``Fastfile``, ``Gemfile`` and ``fastlane/README`` exist;
- the lanes reference the App-Store-Connect API-key / bundle / package env vars
  (``ASC_KEY_ID``, ``ASC_ISSUER_ID``, ``ASC_KEY_P8``, ``MAS_BUNDLE_ID``,
  ``MAS_PKG_PATH``);
- the expected lanes are declared;
- there are **no** ``match(`` (no Matchfile) or ``gym(`` (Nuitka, not Xcode)
  calls;
- the ``Gemfile`` pins ``fastlane`` to an exact version.

The forbidden-string guards run against the *code* (Ruby ``#`` comment lines
stripped) so the header may explain "no Matchfile" / "no gym" without tripping
the substring assertions.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
FASTLANE_DIR = REPO_ROOT / "fastlane"
APPFILE = FASTLANE_DIR / "Appfile"
FASTFILE = FASTLANE_DIR / "Fastfile"
README = FASTLANE_DIR / "README.md"
GEMFILE = REPO_ROOT / "Gemfile"


def _strip_comments(text: str) -> str:
    """Return only the executable lines (drop whole-line ``#`` comments)."""
    return "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )


@pytest.fixture(scope="module")
def fastfile_text() -> str:
    return FASTFILE.read_text()


@pytest.fixture(scope="module")
def fastfile_code(fastfile_text: str) -> str:
    return _strip_comments(fastfile_text)


@pytest.fixture(scope="module")
def appfile_text() -> str:
    return APPFILE.read_text()


@pytest.fixture(scope="module")
def appfile_code(appfile_text: str) -> str:
    return _strip_comments(appfile_text)


@pytest.fixture(scope="module")
def gemfile_text() -> str:
    return GEMFILE.read_text()


class TestFilesExist:
    def test_appfile_present(self) -> None:
        assert APPFILE.is_file(), "missing fastlane/Appfile"

    def test_fastfile_present(self) -> None:
        assert FASTFILE.is_file(), "missing fastlane/Fastfile"

    def test_readme_present(self) -> None:
        assert README.is_file(), "missing fastlane/README.md"

    def test_gemfile_present(self) -> None:
        assert GEMFILE.is_file(), "missing Gemfile"


class TestAppfile:
    def test_app_identifier_from_bundle_env(self, appfile_code: str) -> None:
        assert 'app_identifier(ENV["MAS_BUNDLE_ID"])' in appfile_code

    def test_team_id_from_env(self, appfile_code: str) -> None:
        assert 'team_id(ENV["APPLE_TEAM_ID"])' in appfile_code

    def test_apple_id_from_env(self, appfile_code: str) -> None:
        # apple_id is only needed for the local `produce`/bootstrap run.
        assert 'apple_id(ENV["FASTLANE_APPLE_ID"])' in appfile_code


class TestFastfileLanes:
    @pytest.mark.parametrize("lane", ["bootstrap", "profile", "beta", "release"])
    def test_lane_declared(self, fastfile_code: str, lane: str) -> None:
        assert f"lane :{lane} do" in fastfile_code

    def test_targets_mac_platform(self, fastfile_code: str) -> None:
        assert "default_platform(:mac)" in fastfile_code
        assert "platform :mac do" in fastfile_code

    def test_uses_asc_api_key_helper(self, fastfile_code: str) -> None:
        assert "app_store_connect_api_key(" in fastfile_code


class TestFastfileEnvVars:
    @pytest.mark.parametrize(
        "env_var",
        ["ASC_KEY_ID", "ASC_ISSUER_ID", "ASC_KEY_P8", "MAS_BUNDLE_ID", "MAS_PKG_PATH"],
    )
    def test_env_var_referenced(self, fastfile_code: str, env_var: str) -> None:
        assert f'ENV["{env_var}"]' in fastfile_code

    def test_key_content_is_base64(self, fastfile_code: str) -> None:
        # The .p8 arrives base64-encoded; fastlane decodes it.
        assert "is_key_content_base64: true" in fastfile_code


class TestNoMatchNoGym:
    def test_no_match_call(self, fastfile_code: str, appfile_code: str) -> None:
        # Manual signing — no Matchfile, no match() action anywhere.
        assert "match(" not in fastfile_code
        assert "match(" not in appfile_code

    def test_no_gym_call(self, fastfile_code: str, appfile_code: str) -> None:
        # Nuitka builds the .app, not Xcode — no gym() / build_app().
        assert "gym(" not in fastfile_code
        assert "gym(" not in appfile_code
        assert "build_app(" not in fastfile_code


class TestGemfile:
    def test_pins_fastlane(self, gemfile_text: str) -> None:
        # An exact-version pin keeps CI installs reproducible.
        import re

        match = re.search(
            r'gem\s+["\']fastlane["\']\s*,\s*["\'](?P<ver>[^"\']+)["\']',
            gemfile_text,
        )
        assert match is not None, "Gemfile does not pin fastlane to a version"
        version = match.group("ver")
        # Exact pin (e.g. "2.227.2"), not a fuzzy "~>" / ">=" constraint.
        assert version[0].isdigit(), f"fastlane pin is not exact: {version!r}"

    def test_uses_rubygems_source(self, gemfile_text: str) -> None:
        assert 'source "https://rubygems.org"' in gemfile_text


class TestReadme:
    def test_documents_bootstrap_runs_locally(self) -> None:
        text = README.read_text().lower()
        assert "bootstrap" in text
        assert "local" in text


class TestMetadata:
    """The App Store listing copy is version-controlled and within ASC limits."""

    METADATA_DIR = FASTLANE_DIR / "metadata" / "en-US"

    @pytest.mark.parametrize(
        "name", ["description.txt", "keywords.txt", "promotional_text.txt"]
    )
    def test_metadata_file_present_and_nonempty(self, name: str) -> None:
        path = self.METADATA_DIR / name
        assert path.is_file(), f"missing metadata file: {name}"
        assert path.read_text().strip(), f"empty metadata file: {name}"

    def test_description_within_limit(self) -> None:
        # App Store description hard limit is 4000 characters.
        text = (self.METADATA_DIR / "description.txt").read_text().strip()
        assert len(text) <= 4000

    def test_keywords_within_limit(self) -> None:
        # Keywords field is a single comma-separated line, max 100 characters.
        text = (self.METADATA_DIR / "keywords.txt").read_text().strip()
        assert len(text) <= 100, f"keywords too long: {len(text)} chars"
        assert "\n" not in text, "keywords must be a single comma-separated line"

    def test_promotional_text_within_limit(self) -> None:
        # Promotional text hard limit is 170 characters.
        text = (self.METADATA_DIR / "promotional_text.txt").read_text().strip()
        assert len(text) <= 170, f"promotional text too long: {len(text)} chars"


class TestReleaseLaneWiring:
    """The release lane consumes the version-controlled metadata."""

    def test_release_points_at_metadata_dir(self, fastfile_code: str) -> None:
        assert "metadata_path:" in fastfile_code

    def test_release_skips_screenshots(self, fastfile_code: str) -> None:
        # Screenshots are managed by hand in ASC; an empty folder must not wipe
        # them on a metadata-only deliver run.
        assert "skip_screenshots: true" in fastfile_code

    def test_release_targets_osx_platform(self, fastfile_code: str) -> None:
        assert 'platform: "osx"' in fastfile_code
