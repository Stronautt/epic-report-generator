"""Tests for the ``mas-upload`` CI job.

``build.yml`` must carry a ``mas-upload`` job that re-signs the shared unsigned
``.app``, wraps it in a ``.pkg``, validates it, and uploads it to TestFlight —
running as part of the tag-driven (``v*``) flow. The GitHub ``release`` job is
**gated on it** (``mas-upload`` is in ``release``'s ``needs``): a failed
TestFlight upload must not cut a release. It is gated on the tag ref plus the MAS
secrets, so forks/PRs and non-tag dispatches skip it cleanly (and each MAS step
also no-ops when its secret is absent, so the job still succeeds and the release
gate only bites when MAS is configured and genuinely fails). App Review
submission is never automated.

The workflow is parsed with ``yaml.safe_load`` so the assertions track the real
job graph. NOTE: PyYAML follows YAML 1.1, where the bare key ``on`` is the
boolean ``True`` — hence the ``_on_section`` helper.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
BUILD_YML = REPO_ROOT / ".github" / "workflows" / "build.yml"

JOB_NAME = "mas-upload"


def _load_workflow() -> dict[str, Any]:
    return yaml.safe_load(BUILD_YML.read_text(encoding="utf-8"))


def _jobs() -> dict[str, Any]:
    return _load_workflow()["jobs"]


def _mas_job() -> dict[str, Any]:
    jobs = _jobs()
    assert JOB_NAME in jobs, f"no {JOB_NAME!r} job in build.yml"
    return jobs[JOB_NAME]


def _on_section() -> dict[str, Any]:
    wf = _load_workflow()
    # YAML 1.1: `on:` parses to the boolean True; fall back to the string key.
    section = wf.get(True, wf.get("on"))
    assert isinstance(section, dict), "workflow `on:` section is not a mapping"
    return section


def _steps() -> list[dict[str, Any]]:
    return _mas_job()["steps"]


def _step_runs() -> str:
    """Concatenated ``run:`` bodies of every step (for substring asserts)."""
    return "\n".join(str(s.get("run", "")) for s in _steps())


class TestJobGraph:
    def test_job_exists(self) -> None:
        assert JOB_NAME in _jobs()

    def test_needs_build(self) -> None:
        needs = _mas_job()["needs"]
        # Accept either a bare string or a list containing "build".
        if isinstance(needs, str):
            assert needs == "build"
        else:
            assert "build" in needs

    def test_runs_on_macos(self) -> None:
        assert "macos" in str(_mas_job()["runs-on"]).lower()

    def test_in_release_needs(self) -> None:
        # The release is gated on a successful MAS upload: if mas-upload fails,
        # the GitHub release must not be cut, so it is wired into release.needs.
        release_needs = _jobs()["release"]["needs"]
        needs = [release_needs] if isinstance(release_needs, str) else list(release_needs)
        assert JOB_NAME in needs, "release must depend on mas-upload"

    def test_only_release_depends_on_mas_upload(self) -> None:
        # release is the sole gate; no build/notarize job may chain off it.
        for name, job in _jobs().items():
            if name in (JOB_NAME, "release"):
                continue
            needs = job.get("needs", [])
            needs = [needs] if isinstance(needs, str) else list(needs)
            assert JOB_NAME not in needs, f"{name} should not need {JOB_NAME}"


class TestTrigger:
    def test_no_mas_action_dispatch_input(self) -> None:
        # The old opt-in `mas_action` choice is gone: MAS upload now rides the
        # tag-driven flow, so there is nothing to choose at dispatch time.
        wd = _on_section().get("workflow_dispatch")
        inputs = (wd or {}).get("inputs") or {}
        assert "mas_action" not in inputs

    def test_job_gated_on_version_tag(self) -> None:
        # Runs in the common flow on a `v*` tag push — and ONLY then, so a plain
        # workflow_dispatch / branch / PR build never uploads to TestFlight.
        cond = "".join(_mas_job()["if"].split())  # whitespace-insensitive
        assert "startsWith(github.ref,'refs/tags/v')" in cond
        # Guard against a regression back to the dispatch-only gate.
        assert "mas_action" not in cond


class TestSecretGuards:
    def setup_method(self) -> None:
        self.env = _mas_job()["env"]

    def test_signing_secrets_surfaced_as_env(self) -> None:
        # The two new MAS .p12 secrets are surfaced as job env.
        for key in ("APPLE_DIST_P12", "MAC_INSTALLER_P12"):
            assert key in self.env, f"{key} not surfaced as job env"
            assert "secrets." in str(self.env[key])

    def test_p12_password_reuses_dev_id_password(self) -> None:
        # The MAS certs are exported with the same password as the Developer ID
        # cert, so the password reuses MACOS_CERT_PASSWORD (no new secret).
        assert "MAS_P12_PASSWORD" in self.env
        assert "MACOS_CERT_PASSWORD" in str(self.env["MAS_P12_PASSWORD"])

    def test_asc_api_key_wired(self) -> None:
        # TestFlight upload + profile fetch need an App Manager/Admin key; the
        # notarization key is Developer-only, so the key id + .p8 are dedicated
        # ASC secrets. The issuer ID is account-wide, shared with the notary key.
        assert "MACOS_NOTARY_ISSUER_ID" in str(self.env["ASC_ISSUER_ID"]), (
            "ASC_ISSUER_ID should reuse the account-wide notary issuer"
        )
        for key in ("ASC_KEY_ID", "ASC_KEY_P8"):
            assert key in self.env
            assert "secrets." in str(self.env[key])

    def test_pkg_path_env_present(self) -> None:
        assert self.env["MAS_PKG_PATH"] == "epic-report-generator-mas.pkg"

    def test_signing_steps_guard_on_secret_presence(self) -> None:
        # Steps that touch the certs must skip when the secret is absent so a
        # fork/PR run degrades to a no-op instead of failing.
        guarded = [
            s
            for s in _steps()
            if "P12" in str(s.get("if", "")) or "ASC_KEY_ID" in str(s.get("if", ""))
        ]
        assert guarded, "no MAS step guards on a secret env var"


class TestPipelineSteps:
    def setup_method(self) -> None:
        self.steps = _steps()
        self.runs = _step_runs()

    def test_downloads_unsigned_app_artifact(self) -> None:
        downloads = [
            s
            for s in self.steps
            if "download-artifact" in str(s.get("uses", ""))
            and s.get("with", {}).get("name") == "unsigned-macos-app"
        ]
        assert downloads, "mas-upload does not download the unsigned-macos-app artifact"

    def test_extracts_with_ditto(self) -> None:
        # Mirror the build job's `ditto -c -k` archive with a `ditto -x` extract.
        assert "ditto -x" in self.runs

    def test_runs_bundle_fastlane_profile(self) -> None:
        assert "bundle exec fastlane mac profile" in self.runs

    def test_invokes_sign_and_pkg_scripts(self) -> None:
        assert "packaging/macos/sign_mas.sh" in self.runs
        assert "packaging/macos/build_pkg.sh" in self.runs

    def test_uploads_to_testflight_via_beta_lane(self) -> None:
        assert "bundle exec fastlane mac beta" in self.runs

    def test_does_not_automate_app_review_submission(self) -> None:
        # Submission to App Review (the `release` lane) is a deliberate manual
        # step — CI only validates and ships to TestFlight.
        assert "bundle exec fastlane mac release" not in self.runs

    def test_does_not_store_the_pkg_as_an_artifact(self) -> None:
        # The .pkg goes straight to TestFlight; keeping it as a workflow
        # artifact would only add a stale intermediate (minimal-artifacts rule).
        for step in self.steps:
            if "upload-artifact" in str(step.get("uses", "")):
                assert step.get("with", {}).get("name") != "mas-pkg"

    def test_does_not_touch_github_release(self) -> None:
        # The MAS job must not create or upload to the GH release.
        for step in self.steps:
            assert "action-gh-release" not in str(step.get("uses", ""))


class TestReleasePicksOnlyInstallers:
    """The GH ``release`` must ship ONLY the three platform installers.

    Never the cross-job handoff artifacts (unsigned ``.app``, notary id) nor the
    MAS ``.pkg``. The download step enforces this with an ``installer-*``
    pattern instead of pulling every artifact in the run.
    """

    def setup_method(self) -> None:
        self.release = _jobs()["release"]
        self.steps = self.release["steps"]

    def _download_step(self) -> dict[str, Any]:
        for s in self.steps:
            if "download-artifact" in str(s.get("uses", "")):
                return s
        raise AssertionError("release job has no download-artifact step")

    def test_download_is_scoped_to_installer_pattern(self) -> None:
        with_ = self._download_step().get("with", {})
        # An installer-only pattern is what excludes unsigned-macos-app,
        # notary-submission-id and any MAS .pkg from the release.
        assert with_.get("pattern") == "installer-*"
        assert with_.get("merge-multiple") is True

    def test_download_does_not_pull_everything(self) -> None:
        # A bare download (no name/pattern) would grab every artifact — exactly
        # the regression this guards against.
        with_ = self._download_step().get("with", {})
        assert "pattern" in with_, "release download must be filtered, not blanket"
