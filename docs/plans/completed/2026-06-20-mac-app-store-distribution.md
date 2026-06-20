# Mac App Store Distribution + fastlane

## Overview

Ship Epic Report Generator (PySide6 + Nuitka) to the Mac App Store as a second
macOS channel next to the existing notarized Developer-ID `.dmg`, and set up
fastlane for App Store Connect (ASC) provisioning and upload.

Today's macOS artifact is a Developer-ID notarized `.dmg` for direct download.
MAS is a separate channel with its own signing chain (Apple Distribution for the
app, Mac Installer Distribution for the installer), a mandatory App Sandbox, an
embedded provisioning profile, a signed `.pkg`, and an ASC upload behind App
Review. There is no notarization.

The current `build` → `notarize-macos` → `release` pipeline stays as-is and
remains primary. We add one decoupled, re-runnable `mas-upload` job that takes a
single unsigned Nuitka `.app` (compiled once), re-signs it for MAS, wraps it in a
`.pkg`, and uploads it. A few small in-app changes make the build sandbox-clean
and reviewable.

For v1 the store build ships API-Token auth only: the OAuth tab is hidden, and
the work is structured so OAuth can return in a later store update with one
entitlement and a flag rather than a rewrite. The Developer-ID `.dmg` keeps
OAuth.

## Decisions (locked)

1. OAuth: MAS v1 is API-Token-only. Hide the OAuth tab in store builds (gate on
   `install_source.is_store_install()`); give Apple demo Jira creds in review
   notes. Ship two container plists — v1 without `network.server`, a future one
   with it — so OAuth is a later flag-flip. Custom-URL-scheme redirect is out
   (Atlassian 3LO rejects non-http redirects). Add `SO_REUSEADDR` to
   `OAuthCallbackServer` either way.
2. Bundle ID: one `CFBundleIdentifier`, `com.epicreportgenerator.app`, for both
   channels.
3. Entitlements: container = `app-sandbox` + `network.client` +
   `files.user-selected.read-write`; inherit = `app-sandbox` + `inherit`; no
   `cs.*` (those stay on the Dev-ID build). No XML comments (AMFI rejects them).
4. Keychain: default container access first; add `keychain-access-groups` only if
   `errSecMissingEntitlement` shows up in signed testing.
5. Nested signing: inside-out, Apple Distribution identity, no
   `disable-library-validation`, strip before signing.
6. CI: the Dev-ID `.dmg` job stays primary; a new decoupled `mas-upload` job
   re-signs one shared unsigned `.app`.
7. fastlane: ASC API key + manual signing, no `match`. Lanes `produce`, `sigh`,
   `pilot`/`deliver`. No `gym` (Nuitka, not Xcode).
8. Migration: fresh-start; no auto-migration into the sandbox container.
9. Metadata: draft the privacy nutrition label; user supplies category,
   screenshots, privacy-policy URL.
10. Architecture: arm64-only for v1 (matches the `.dmg`; universal2 deferred).
    `CFBundleVersion` = `git rev-list --count HEAD`.

## Context (from discovery)

File-level findings the plan builds on:

- `desktop.py:105-125` — the hardcoded `_INFO_PLIST` sets
  `CFBundleIdentifier = com.epicreportgenerator.app`, but only for the pip
  `--install-desktop` launcher in `~/Applications` (a shell `exec` wrapper), not
  the Nuitka bundle CI ships. The shipped bundle still needs an explicit ID
  (Task 1).
- `.github/workflows/build.yml:178-211` — the macOS Nuitka build passes
  `--macos-app-name` only and no bundle-identifier flag, so Nuitka auto-derives
  the `CFBundleIdentifier`. Not deterministic, not registered.
- `build.yml:254-285` — strip finds Mach-O under
  `"Epic Report Generator.app/Contents"`, then signs `--force --deep --timestamp
  --options runtime --entitlements packaging/macos/entitlements.plist` (Dev-ID),
  or ad-hoc. `--deep` is wrong for MAS; signing must be inside-out.
- `packaging/macos/entitlements.plist` — holds `cs.allow-jit`,
  `cs.allow-unsigned-executable-memory`, `cs.disable-library-validation`. All are
  MAS-illegal or discouraged; keep them on Dev-ID only.
- `services/oauth_server.py:97-104` — `OAuthCallbackServer(HTTPServer)` binds
  `("127.0.0.1", port)` and never sets `allow_reuse_address`, so a fixed port
  (`18492`) can hit `EADDRINUSE`.
- `services/auth_manager.py:160-161` — `redirect_uri =
  http://localhost:{port}/callback` (default `18492`). OAuth is
  bring-your-own-client: `is_configured` needs the user's own
  `client_id`/`client_secret`.
- `ui/login_panel.py:91-92, 211, 323` — `__init__` builds the API-Token tab
  (index 0) then the OAuth tab (index 1). Gate the second call to hide OAuth in
  store builds, and skip its signal wiring (`:312`, `_on_oauth_*`).
- `ui/preview_panel.py:566-595` — `_export_pdf` uses
  `QFileDialog.getSaveFileName` (the macOS save panel / powerbox) and persists
  `last_export_dir`. Works under sandbox once the user-selected-files entitlement
  is present.
- `ui/main_window.py:528-547` — `_setup_update_check` already returns early when
  `install_source.store_source()` is set. Self-update gating is correct.
- `services/font_manager.py:38, 231, 249` — outbound `requests.get` to
  `api.github.com/repos/google/fonts` needs `network.client`. Cache dir is
  `user_config_dir(APP_NAME, appauthor=False)/fonts` (platformdirs → container).
- `core/typst_renderer.py:59` — `tempfile.TemporaryDirectory(prefix="erg-typst-")`
  lands in the container `Data/tmp`, writable under sandbox. Verify in QA.
- `pyproject.toml` — name `epic-report-generator`, version `1.0.2`.

Environment: `ralphex` is installed. MAS signing and upload need macOS
(`codesign`/`productbuild`/`altool`), so the MAS job runs on `macos-26`. Requires
the Apple Developer account (held), Apple Distribution + Mac Installer
Distribution certs, a MAS provisioning profile, and an ASC API key.

## Development Approach

- Testing: code/config first, then tests. Most work is YAML, plists, shell, and
  fastlane config, so the testable Python surface is small but real.
- Finish each task before the next; small focused changes.
- Every task that changes code or config ships tests:
  - `oauth_server` `SO_REUSEADDR` — unit test on `allow_reuse_address`.
  - `login_panel` OAuth-hide — pytest-qt: store install gives one tab, non-store
    gives both.
  - entitlements plists — `plistlib` parse test for required keys and no XML
    comments.
  - bundle ID, signing, `.pkg`, fastlane, CI: not unit-testable in Python, so
    verified by CI runs and local validation scripts.
- All tests pass before the next task (`pytest --tb=short`).
- Keep this plan in sync as scope shifts.

## Testing Strategy

- Unit tests per task, with `pytest` + `pytest-qt` (already dev deps).
- No E2E harness exists (CI runs a `--selftest` smoke). The MAS equivalent is the
  Sandbox QA Checklist, run manually on the signed build and tracked in
  Post-Completion.
- The plist guard test also blocks XML comments and `cs.*` entitlements from
  sneaking back into the MAS plists.

## Progress Tracking

Mark items `[x]` when done; prefix new tasks `➕` and blockers `⚠️`. Keep the plan
in step with the actual work.

## What Goes Where

- Implementation Steps (`[ ]`): in-repo and automatable — Python, plists, shell
  scripts, fastlane files, CI YAML, docs, and their tests.
- Post-Completion (no checkboxes): anything needing Apple/ASC or a signed Mac —
  certs, profiles, the app record, signed-build QA, TestFlight, submission,
  screenshots, the demo Jira instance.

## Gap Analysis — Dev-ID `.dmg` (today) → MAS (target)

| Area | Today (Dev-ID `.dmg`) | MAS target | Files touched |
|---|---|---|---|
| Sandbox | none | `app-sandbox` on app + every nested Mach-O | new `entitlements.mas*.plist`; MAS sign script |
| Cert chain | Developer ID Application | Apple Distribution (app) + Mac Installer Distribution (pkg) | CI MAS job, fastlane |
| Provisioning | none | `Contents/embedded.provisionprofile` | MAS sign script, `sigh` |
| Entitlements | `cs.allow-jit`, `cs.allow-unsigned-executable-memory`, `cs.disable-library-validation` | drop all `cs.*`; `app-sandbox`+`network.client` (container), `app-sandbox`+`inherit` (nested) | `packaging/macos/` plists |
| Signing | `codesign --force --deep --options runtime` | inside-out, no `--deep`, no hardened runtime, re-sign all nested incl. Typst `.so` with Team ID | MAS sign script |
| Wrapper | `.dmg` (create-dmg) | `.pkg` (`productbuild --sign "Mac Installer Distribution"`) | CI MAS job |
| Verify/ship | notarytool + staple → GH release | `altool --validate-app`/`--upload-app` (or Transporter) → ASC → App Review | CI MAS job, fastlane |
| Bundle ID | Nuitka auto-derived | one registered `CFBundleIdentifier` | Task 1 |
| OAuth loopback | works (Dev-ID, no sandbox) | hidden in store build (would need `network.server`; deferred) | `login_panel.py` |
| `OAuthCallbackServer` | no `SO_REUSEADDR` | `allow_reuse_address = True` | `oauth_server.py` |
| keyring | Keychain, app identity | container Keychain identity = bundle ID; test signed | verify; group entitlement only if needed |
| Config/cache | `~/Library/Application Support/...` | redirected to `~/Library/Containers/<id>/Data/...`; no migration | docs |
| Export path | `QFileDialog` save panel | powerbox requires `files.user-selected.read-write` | container plist |
| Info.plist | Nuitka-derived; no MAS keys | add `LSApplicationCategoryType`, `ITSAppUsesNonExemptEncryption`, `LSMinimumSystemVersion`, monotonic `CFBundleVersion` | Task 1 / `build.yml` |
| Architecture | arm64-only (`macos-26`) | arm64-only v1 (Intel excluded); universal2 deferred | locked |
| Typst temp dir | system temp | container `Data/tmp` (writable) | verify |
| Font cache fetch | `requests` → GitHub | needs `network.client` | container plist |
| Self-update | enabled | disabled via `_MASReceipt` gating (already correct) | verify (QA caveat) |

Self-update QA caveat: `install_source._mac_app_store()` keys on
`Contents/_MASReceipt/receipt`, which exists only after a store or TestFlight
install, not in a locally `installer`-installed `.pkg`. To test the "no update
link" path locally, drop a dummy file at `<App>/Contents/_MASReceipt/receipt`, or
verify on a TestFlight build.

## Signing & Provisioning Design

Certificates (create in ASC / Xcode, store as base64 CI secrets):
- Apple Distribution (a.k.a. 3rd Party Mac Developer Application) signs the `.app`
  and all nested code. Secret `APPLE_DIST_P12` (+ password).
- Mac Installer Distribution (a.k.a. 3rd Party Mac Developer Installer) signs the
  `.pkg`. Secret `MAC_INSTALLER_P12` (+ password).
- ASC API key `.p8`: secrets `ASC_KEY_ID`, `ASC_ISSUER_ID`, `ASC_KEY_P8`.

Provisioning profile: a Mac App Store profile for the bundle ID, fetched by
`sigh`, copied into the bundle as `Contents/embedded.provisionprofile` before the
app is signed.

Inside-out `codesign` order (the MAS sign script, run on macOS):
1. Copy `embedded.provisionprofile` into `Contents/`.
2. Sign deepest-first. Enumerate nested Mach-O (`find … -type f`, filter `file …
   | grep Mach-O`): every `*.dylib`, `*.so` (incl. the ~76 MB Typst `.so`),
   framework binary, and nested executable.
   - dylibs / .so / frameworks: `codesign --force --timestamp --sign
     "$APPLE_DIST" <file>` (re-signed with our Team ID, so library validation
     passes without `disable-library-validation`).
   - nested executables (e.g. the `Python` helper): add `--entitlements
     packaging/macos/entitlements.mas.inherit.plist`.
3. Sign the main executable (`Contents/MacOS/epic-report-generator`) with the
   inherit entitlements.
4. Sign the app bundle last: `codesign --force --timestamp --sign "$APPLE_DIST"
   --entitlements packaging/macos/entitlements.mas.plist "Epic Report
   Generator.app"`. No `--deep`, no `--options runtime` (hardened runtime is a
   Dev-ID concept; MAS uses sandbox).
5. Verify: `codesign --verify --deep --strict --verbose=2 "$APP"` and `codesign
   -dv --entitlements - "$APP"` (sandbox present, no `cs.*`).

Strip Mach-O before step 2, since stripping invalidates any prior signature. This
matches the existing Dev-ID strip step but swaps in the inside-out sign.

`.pkg` wrapper:
```
productbuild --component "Epic Report Generator.app" /Applications \
  --sign "3rd Party Mac Developer Installer: <Team Name> (<TeamID>)" \
  epic-report-generator-mas.pkg
```

Validate and upload (no notarization for MAS):
- Validate: `xcrun altool --validate-app -f epic-report-generator-mas.pkg
  -t macos --apiKey "$ASC_KEY_ID" --apiIssuer "$ASC_ISSUER_ID"`. Fix
  `90237`-class (wrong installer cert) and sandbox/entitlement errors here,
  before upload.
- Upload: `xcrun altool --upload-app -f … -t macos --apiKey … --apiIssuer …` or
  Transporter, wrapped by fastlane `pilot`/`deliver`.

Bundle integrity in CI: `upload-artifact` does not preserve symlinks/permissions
and can mangle the `.app`, so the build job archives the unsigned `.app` with
`ditto`/`tar` and the MAS job extracts with `ditto -x` on macOS before signing.

## Entitlements Artifacts (exact contents, no XML comments)

`packaging/macos/entitlements.mas.plist` (container, v1):
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>com.apple.security.app-sandbox</key>
  <true/>
  <key>com.apple.security.network.client</key>
  <true/>
  <key>com.apple.security.files.user-selected.read-write</key>
  <true/>
</dict>
</plist>
```

`files.user-selected.read-write` is required. Without it the powerbox does not
grant write access to the user's chosen PDF-export location (or the font file
imported via `font_manager`), and export fails silently.

`packaging/macos/entitlements.mas.inherit.plist` (nested Mach-O):
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>com.apple.security.app-sandbox</key>
  <true/>
  <key>com.apple.security.inherit</key>
  <true/>
</dict>
</plist>
```

`packaging/macos/entitlements.mas.oauth.plist` (future container; adds
`network.server` for loopback OAuth, not used in v1):
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>com.apple.security.app-sandbox</key>
  <true/>
  <key>com.apple.security.network.client</key>
  <true/>
  <key>com.apple.security.network.server</key>
  <true/>
  <key>com.apple.security.files.user-selected.read-write</key>
  <true/>
</dict>
</plist>
```

The `<?xml …?>` declaration and `<!DOCTYPE …>` are not XML comments and must stay;
AMFI only rejects `<!-- … -->`. The plist guard test (Task 4) asserts `b"<!--"
not in file_bytes` for every MAS plist. If keyring later needs it, add
`keychain-access-groups`
(`<array><string>$(AppIdentifierPrefix)<bundleid></string></array>`) to the
container plist and enable Keychain Sharing on the profile, but only if
`errSecMissingEntitlement` fires.

## fastlane Setup (no Matchfile)

`fastlane/Appfile`:
```ruby
app_identifier(ENV["MAS_BUNDLE_ID"])      # e.g. com.epicreportgenerator.app
apple_id(ENV["FASTLANE_APPLE_ID"])        # only for `produce`, run locally
team_id(ENV["APPLE_TEAM_ID"])
```

`fastlane/Fastfile`:
```ruby
default_platform(:mac)

platform :mac do
  def asc_key
    app_store_connect_api_key(
      key_id: ENV["ASC_KEY_ID"],
      issuer_id: ENV["ASC_ISSUER_ID"],
      key_content: ENV["ASC_KEY_P8"],   # base64 -> decoded by fastlane
      is_key_content_base64: true,
    )
  end

  # One-time, run locally: create the ASC app record.
  lane :bootstrap do
    produce(
      app_identifier: ENV["MAS_BUNDLE_ID"],
      app_name: "Epic Report Generator",
      mac: true, platforms: ["osx"],
    )
  end

  # Fetch/refresh the Mac App Store provisioning profile (manual signing).
  lane :profile do
    sigh(
      api_key: asc_key,
      app_identifier: ENV["MAS_BUNDLE_ID"],
      platform: "macos",
      additional_cert_types: ["mac_installer_distribution"],
      output_path: "build",
    )
  end

  # Upload an already-built, MAS-signed .pkg to TestFlight (internal testing).
  lane :beta do
    pilot(
      api_key: asc_key,
      pkg: ENV["MAS_PKG_PATH"],          # epic-report-generator-mas.pkg
      skip_waiting_for_build_processing: true,
    )
  end

  # Upload + submit for App Review (used once metadata is ready).
  lane :release do
    deliver(
      api_key: asc_key,
      pkg: ENV["MAS_PKG_PATH"],
      submit_for_review: false,          # flip to true when confident
      automatic_release: false,
      force: true,                        # skip HTML preview in CI
    )
  end
end
```

Notes:
- No `gym`: Nuitka builds the `.app` and the CI shell steps / sign script sign it;
  fastlane only handles the profile and upload.
- `produce` runs locally once (it needs interactive Apple-ID/ASC access). CI uses
  `profile`/`beta`/`release` with the API key.
- The `.p8` is passed as a base64 env var (`ASC_KEY_P8`), matching the existing
  base64-secret pattern in `build.yml`.

## CI Design (decoupled, re-runnable MAS job)

Mirror the `notarize-macos` split-out (commit `0f44f4b`): the slow Nuitka compile
runs once in `build`, and the MAS job re-signs a shared artifact and can re-run on
its own after a rejection.

1. `build` (macOS leg), one new step: after Nuitka + strip and before the Dev-ID
   sign, archive and upload the unsigned bundle.
   - `ditto -c -k --sequesterRsrc --keepParent "Epic Report Generator.app"
     unsigned-app.zip`, then `upload-artifact name: unsigned-macos-app`.
   - The Dev-ID sign / DMG / notary steps continue untouched.
2. `mas-upload` (new job, `needs: build`, `runs-on: macos-26`, re-runnable),
   guarded on MAS secrets so forks/PRs skip it and it never blocks `release`.
   - `download-artifact unsigned-macos-app`; `ditto -x -k unsigned-app.zip .`.
   - Import the Apple Distribution + Mac Installer Distribution p12s into a temp
     keychain (reuse the `build.yml` import pattern for two identities).
   - `fastlane mac profile`, then embed `embedded.provisionprofile`.
   - Run `packaging/macos/sign_mas.sh` (inside-out).
   - `productbuild … --sign "Mac Installer Distribution" → *.pkg`.
   - `xcrun altool --validate-app …` (fail the job on validation errors).
   - `fastlane mac beta` (TestFlight) or `release` (App Review) per dispatch
     input.
   - Stays separate from `notarize-macos`; does not upload the `.pkg` to the GH
     release.
3. Trigger: a `workflow_dispatch` input (e.g. `mas_action:
   none|validate|testflight|submit`) makes MAS upload opt-in and re-runnable
   independent of a tag, while the GH `release` stays tag-driven.

## Risk Register + What Gets Us Rejected

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| 1 | Reviewer can't test (Guideline 2.1) | High if OAuth shipped | Rejection | API-Token-only v1; demo Jira creds in review notes; reachable backend |
| 2 | Nested dylib / library-validation failure | High | Build won't validate | Inside-out sign all Mach-O (incl. Typst `.so`) with Team ID; drop `disable-library-validation`; strip first |
| 3 | `cs.*` entitlements in the MAS build | Med | Rejection/validation fail | Separate MAS plists with no `cs.*`; plist guard test; no hardened runtime |
| 4 | XML comment in a plist | Med | codesign/AMFI failure | Guard test asserts no `<!--`; reuse the templates above |
| 5 | keyring `errSecMissingEntitlement` | Med | Login breaks | Test keyring in the signed sandboxed build; add Keychain Sharing only if it fires |
| 6 | `.app` mangled by `upload-artifact` | Med | Sign/validate fail | `ditto`/`tar` both ends |
| 7 | Bundle ID mismatch (Nuitka vs registered vs `desktop.py`) | Med | Profile/upload fail | One explicit `CFBundleIdentifier`; reconcile all three; verify with `codesign -dv` |
| 8 | Existing `.dmg` users' data absent in the container | Med | Support noise | Document fresh-start |
| 9 | `EADDRINUSE` on the fixed OAuth port (Dev-ID) | Low | Login flake | `allow_reuse_address` |
| 10 | Update link shows in local `.pkg` QA | Low | False alarm | Simulate the receipt locally; verify on TestFlight |
| 11 | Fonts/temp/export under the container | Low | Cosmetic | platformdirs/powerbox/tempfile; verify in QA |

What gets us rejected at review: an untestable feature (empty OAuth fields), an
entitlement with no matching functionality (`network.server` and no working
OAuth), a launch crash (signing/sandbox), missing demo credentials, or an
incomplete privacy nutrition label.

Go/No-Go: go, with API-Token-only v1. Deferring OAuth removes risk 1 and the
`network.server` scrutiny; the rest are mechanical signing and packaging issues
with known fixes.

## Sandbox QA Checklist (run on the signed, sandboxed build, not from source)

Install the MAS-signed `.pkg` locally (or a TestFlight build) and check:

- [ ] App launches (no `cs.*`, no library-validation crash; watch Console: `log
      stream --predicate 'sender == "Sandbox"'`).
- [ ] API-Token login round-trips: enter Jira URL/email/token, connect, fetch
      epics.
- [ ] keyring read/write inside the container (relaunch restores the session, no
      `errSecMissingEntitlement`), and the macOS Keychain backend resolves in the
      frozen build (not the null backend).
- [ ] App icon renders in Dock/Finder (the `.icns` has the required sizes).
- [ ] PDF generation works (Typst temp dir writable in `Data/tmp`).
- [ ] Export writes to the chosen path via the save panel; the file lands outside
      the container; `last_export_dir` persists.
- [ ] Fonts: bundled Inter renders, a CJK report pulls Noto Sans CJK JP, and a
      Google-Fonts download works or fails gracefully.
- [ ] OAuth tab is hidden (only the API-Token tab is present).
- [ ] No "Update available" link (simulate `Contents/_MASReceipt/receipt`
      locally; confirm on TestFlight).
- [ ] Config/cache land under `~/Library/Containers/<bundleid>/Data/...`.

## Implementation Steps

### Task 1: Bundle identity + MAS-required Info.plist keys
- [x] Thread the confirmed bundle ID `com.epicreportgenerator.app` as a build var
      (`MAS_BUNDLE_ID`); keep it as a single named constant. (Added top-level
      `env.MAS_BUNDLE_ID` in `build.yml` + `desktop.BUNDLE_ID`; guard test keeps
      them equal.)
- [x] Set it on the **Nuitka** macOS build for **both** channels — prefer the
      Nuitka identifier flag (e.g. `--macos-signed-app-name=com.epicreportgenerator.app`);
      if that does not write `CFBundleIdentifier`, add a post-build
      `plutil -replace CFBundleIdentifier -string com.epicreportgenerator.app
      "Epic Report Generator.app/Contents/Info.plist"` step in `build.yml`.
      (Both: added `--macos-signed-app-name=$MAS_BUNDLE_ID` AND an explicit
      `plutil -replace CFBundleIdentifier` post-build step for determinism.)
- [x] Set the MAS-required Info.plist keys (via `plutil -replace`):
      `LSApplicationCategoryType = public.app-category.productivity`,
      `ITSAppUsesNonExemptEncryption = false` (HTTPS-only → export-compliance
      exempt; avoids the per-upload encryption questionnaire), and
      `LSMinimumSystemVersion` matching the build's deployment target
      (`env.MACOS_DEPLOYMENT_TARGET = "11.0"`, the arm64 floor).
- [x] Stamp `CFBundleVersion = $(git rev-list --count HEAD)` in the build job,
      distinct from the marketing `CFBundleShortVersionString` (= pyproject
      version). Requires `fetch-depth: 0` on the `actions/checkout` (a shallow
      clone returns 1). A same-commit re-upload needs a new commit (or a manual
      bump) so ASC never sees a repeated build number. (Added `fetch-depth: 0`
      to the `build` job checkout + both plutil version keys.)
- [x] Verify `desktop.py:114` already uses `com.epicreportgenerator.app` (it does)
      — keep both pointing at the one constant; no value change needed.
      (Refactored to `BUNDLE_ID` constant + `{bundle_id}` placeholder; same value.)
- [x] Write a test asserting the built `Info.plist` carries
      `CFBundleIdentifier == com.epicreportgenerator.app`,
      `LSApplicationCategoryType`, and `ITSAppUsesNonExemptEncryption == false`
      (parse via `plistlib`, or assert the build vars feed the `plutil` steps).
      Test `desktop._INFO_PLIST` still formats with the shared constant.
      (`tests/test_bundle_identity.py`, 13 tests; added `PyYAML` to dev deps for
      the build.yml-parsing asserts, also needed by Tasks 8/9.)
- [x] run tests; must pass before the next task. (351 passed.)

### Task 2: `SO_REUSEADDR` on the OAuth callback server
- [x] In `services/oauth_server.py`, set `allow_reuse_address = True` on
      `OAuthCallbackServer` (class attr, before `super().__init__`), so a quick
      re-login on the fixed port `18492` does not hit `EADDRINUSE`. (Added as a
      class attribute with a comment; socketserver reads it during `server_bind()`.)
- [x] write a unit test: `OAuthCallbackServer(0, "s").allow_reuse_address is True`
      (and that it still binds 127.0.0.1). (`TestReuseAddr.test_allow_reuse_address_enabled`.)
- [x] write a test for the rapid-rebind case (instantiate/close/instantiate on the
      same ephemeral port without error). (`TestReuseAddr.test_rapid_rebind_same_port`.)
- [x] run tests; must pass before the next task. (353 passed; ruff clean.)

### Task 3: Hide the OAuth tab in store builds
- [x] In `ui/login_panel.py`, gate `self._build_oauth_tab()` (`:92`) behind
      `if not install_source.is_store_install():`; ensure OAuth signal wiring
      (`:312`, `_on_oauth_*`) is **not** connected when the tab is skipped.
      (Added `self._oauth_enabled = not install_source.is_store_install()` in
      `__init__`; `_build_ui` only builds the OAuth tab when enabled, so its
      buttons/signals are never created in store builds.)
- [x] Ensure the API-Token tab remains index 0 and any "active tab" / restore
      logic tolerates a single-tab widget. (API-Token tab is still built first
      → index 0. Guarded every OAuth-only attribute access: OAuth-cred prefill
      and the `method == "oauth"` branch in `try_restore_session`, plus the OAuth
      reset block in `reset_to_logged_out`. `setCurrentIndex(1)` on a one-tab
      widget is a harmless no-op.)
- [x] write a pytest-qt test: patch `install_source.is_store_install` → `True` ⇒
      panel has 1 tab, no "OAuth 2.0"; → `False` ⇒ both tabs present.
      (`tests/test_login_panel.py`: `test_store_build_hides_oauth_tab`,
      `test_direct_build_shows_both_tabs`.)
- [x] write a test that session-restore / tab-selection does not raise with the
      OAuth tab absent. (`test_store_build_restore_session_does_not_raise`,
      `test_store_build_restore_oauth_method_falls_through`,
      `test_store_build_reset_to_logged_out_does_not_raise`,
      `test_store_build_tab_selection_tolerates_single_tab`.)
- [x] run tests; must pass before the next task. (359 passed; ruff clean.)

### Task 4: MAS entitlements plists + guard test
- [x] Add `packaging/macos/entitlements.mas.plist`,
      `entitlements.mas.inherit.plist`, and `entitlements.mas.oauth.plist`
      (exact contents above; **no XML comments**). Leave the existing
      `entitlements.plist` (Dev-ID `cs.*`) untouched. (All three created verbatim
      from the "Entitlements Artifacts" section; Dev-ID plist untouched.)
- [x] write a test that loads each MAS plist via `plistlib`, asserts the required
      keys/values (incl. `com.apple.security.files.user-selected.read-write` in
      both container plists), asserts **no `com.apple.security.cs.*`** key in the
      v1 plists, and asserts `b"<!--" not in path.read_bytes()` (AMFI guard).
      (`tests/test_mas_entitlements.py`: container/inherit/oauth key+value asserts,
      `cs.*` guard, XML-comment guard, plus a check the Dev-ID plist keeps `cs.*`
      and is not sandboxed.)
- [x] write a test that the future `oauth` plist differs from v1 **only** by
      `network.server`. (`TestOAuthPlistDiff` — set-diff is exactly
      `{network.server}`, shared keys have identical values.)
- [x] run tests; must pass before the next task. (375 passed; ruff clean.)

### Task 5: Inside-out MAS signing script
- [x] Add `packaging/macos/sign_mas.sh` implementing the inside-out order
      (embed profile → sign nested dylibs/.so with identity → nested executables
      + main exe with inherit entitlements → app bundle with container
      entitlements; no `--deep`, no `--options runtime`), parameterized by
      identity + entitlements paths + app path; verify with
      `codesign --verify --deep --strict` and `codesign -dv --entitlements -`.
      (Done: positional args with env fallbacks `MAS_APP`/`APPLE_DIST_IDENTITY`/
      `MAS_ENTITLEMENTS`/`MAS_INHERIT_ENTITLEMENTS`/`MAS_PROFILE`, defaulting to
      the MAS plists. Verify uses `codesign --verify --strict --verbose=2` —
      **dropped `--deep`** so the script contains no `--deep` substring at all,
      satisfying the Task 5 guard; `--strict` validates the inside-out-sealed
      bundle. Also dumps sealed entitlements via `codesign -d --entitlements`.)
- [x] Sign any bundled Qt `.framework` as a **bundle** (respect
      `Versions/Current`), not just its inner Mach-O. (Frameworks signed
      deepest-first as bundles; loose-Mach-O pass excludes `*.framework/*`.)
- [x] Make it idempotent and fail-fast (`set -euo pipefail`); strip before sign.
      (`--force` everywhere = idempotent; `set -euo pipefail`; strips all Mach-O
      before any signing.)
- [x] write a test that lints the script (`bash -n packaging/macos/sign_mas.sh`)
      and asserts it references the MAS (not Dev-ID) entitlements and does **not**
      contain `--deep` or `disable-library-validation`.
      (`tests/test_sign_mas_script.py`, 13 tests: `bash -n` lint, MAS-entitlement
      references, no Dev-ID plist, no `--deep`/`disable-library-validation`/
      `--options runtime`/`cs.*`, fail-fast, framework-bundle, app-before-verify
      ordering. Forbidden-flag guards run on comment-stripped code so the header
      rationale can mention the flags.)
- [x] run tests; must pass before the next task. (388 passed; ruff clean.)

### Task 6: `.pkg` build + local validation helper
- [x] Add `packaging/macos/build_pkg.sh` wrapping
      `productbuild --component … /Applications --sign "<Mac Installer
      Distribution>" …` + an optional `xcrun altool --validate-app` step gated on
      ASC creds. (Positional args with env fallbacks `MAS_APP`/
      `MAC_INSTALLER_IDENTITY`/`MAS_PKG_PATH`; `productbuild --component "$APP"
      /Applications --sign "$INSTALLER_IDENTITY"`; the `--validate-app` step is
      gated on `ASC_KEY_ID`+`ASC_ISSUER_ID` so a keyless local build still emits
      the `.pkg`. Only accepts the installer identity — fails fast otherwise —
      avoiding the `90237`-class wrong-cert rejection.)
- [x] write a test linting the script (`bash -n`) and asserting it signs with the
      **installer** identity and targets `/Applications`.
      (`tests/test_build_pkg_script.py`, 11 tests: `bash -n` lint, executable bit,
      `productbuild`/`--component`/`/Applications`, `MAC_INSTALLER_IDENTITY`
      +`--sign`, no `APPLE_DIST_IDENTITY`, `--validate-app` gated on the ASC vars,
      `set -euo pipefail`, fail-fast on missing identity.)
- [x] run tests; must pass before the next task. (399 passed; ruff clean.)

### Task 7: fastlane Fastfile + Appfile
- [x] Add `fastlane/Appfile` and `fastlane/Fastfile` (lanes `bootstrap`,
      `profile`, `beta`, `release`; ASC API key; no Matchfile) as above. Add
      `fastlane/README` note that `bootstrap` runs locally once.
      (Created `fastlane/Appfile`, `fastlane/Fastfile`, `fastlane/README.md`
      verbatim from the "fastlane Setup" section — env-driven identity, ASC API
      key helper, the four lanes; README documents the env vars + that
      `bootstrap`/`produce` runs locally once with no CI 2FA.)
- [x] Add `Gemfile` pinning `fastlane` for reproducible CI installs.
      (Root `Gemfile` with `source "https://rubygems.org"` + exact
      `gem "fastlane", "2.227.2"`; the MAS job runs `bundle exec fastlane …`.)
- [x] write a test that the Fastfile/Appfile exist, reference the env vars
      (`ASC_KEY_ID`, `ASC_ISSUER_ID`, `ASC_KEY_P8`, `MAS_BUNDLE_ID`,
      `MAS_PKG_PATH`), and contain **no** `match(`/`gym(` calls (ripgrep/string
      asserts). (`tests/test_fastlane_config.py`, 24 tests: file existence, the
      four lanes, every ASC/bundle/pkg env var, no `match(`/`gym(`/`build_app(`
      on comment-stripped code, exact fastlane pin, README locality note.)
- [x] run tests; must pass before the next task. (423 passed; ruff clean.)

### Task 8: CI — export the shared unsigned `.app`
- [x] In `.github/workflows/build.yml` macOS leg, after Nuitka+strip and
      **before** the Dev-ID sign, add a step to `ditto -c -k --keepParent` the
      unsigned `.app` to `unsigned-app.zip` and `upload-artifact`
      (`unsigned-macos-app`, retention 3d). Keep all existing steps intact.
      (Split the combined "Strip binaries (macOS)" step into three: `Strip`
      (strip only), `Archive unsigned .app` (`ditto -c -k --sequesterRsrc
      --keepParent … unsigned-app.zip`), and `Upload unsigned .app`
      (`upload-artifact@v7` → `unsigned-macos-app`, retention 3d), then a new
      `Sign binaries (macOS)` step carrying the unchanged Dev-ID codesign +
      `--verify`. All DMG/notary steps untouched.)
- [x] write a YAML-lint / parse test (e.g. `yaml.safe_load`) asserting the new
      step exists and ordering (strip → archive → Dev-ID sign).
      (`tests/test_ci_unsigned_app_export.py`, 13 tests: `yaml.safe_load` parse,
      archive uses `ditto … --keepParent`, upload artifact name/path/retention,
      ordering strip < archive < upload < sign < DMG, and that strip no longer
      codesigns while the new sign step does.)
- [x] run tests; must pass before the next task. (436 passed; ruff clean.)

### Task 9: CI — decoupled `mas-upload` job
- [x] Add the `mas-upload` job (`needs: build`, `runs-on: macos-26`,
      `workflow_dispatch` input `mas_action`), guarded on MAS secrets: download +
      `ditto -x` the unsigned app, `bundle install` (Gemfile) for fastlane, import
      both p12s into a temp keychain, `fastlane mac profile` (a **Mac App Store**
      profile, not Developer ID), run `sign_mas.sh`, `build_pkg.sh`, validate,
      then `fastlane mac beta`/`release` per input. Do **not** touch `release`/GH.
      (Added the `mas_action` choice input `none|validate|testflight|submit`
      (default `none`) and the `mas-upload` job: checkout + setup-python +
      `ruby/setup-ruby` (`bundler-cache` installs the pinned fastlane from the
      Gemfile), `download-artifact unsigned-macos-app` → `ditto -x`, import the
      Apple Distribution + Mac Installer Distribution p12s into a temp keychain
      resolving both identities, materialize the ASC `.p8` for `altool`,
      `fastlane mac profile`, `sign_mas.sh`, `build_pkg.sh` (which runs
      `--validate-app`), upload the `.pkg` as a workflow artifact, then
      `fastlane mac beta`/`release` gated on the `mas_action` input. No
      `action-gh-release`; the GH `release` `needs` is untouched.)
- [x] Add the new secret names to the job `env` so steps can guard on presence
      (forks/PRs skip cleanly). (Job `env` surfaces `APPLE_DIST_P12`
      (+`_PASSWORD`), `MAC_INSTALLER_P12` (+`_PASSWORD`), `ASC_KEY_ID`,
      `ASC_ISSUER_ID`, `ASC_KEY_P8`, `APPLE_TEAM_ID`, plus `MAS_PKG_PATH`; every
      signing/upload step `if:` guards on `env.*_P12`/`env.ASC_KEY_ID` so a fork
      without secrets degrades to a no-op.)
- [x] write a YAML parse test asserting the job exists, is `needs: build`, runs on
      macOS, and is **not** wired into the GH `release` job's `needs`.
      (`tests/test_ci_mas_upload_job.py`, 18 tests: `yaml.safe_load` parse with a
      YAML-1.1 `on:`→`True` helper, job graph (exists / `needs: build` / macOS /
      not in `release.needs` / no job depends on it), the `mas_action` choice
      input + options + default + job `if` gating, the secret env guards, and the
      pipeline steps (download `unsigned-macos-app`, `ditto -x`, `fastlane mac
      profile`, `sign_mas.sh`/`build_pkg.sh`, `beta`/`release`, no
      `action-gh-release`).)
- [x] run tests; must pass before the next task. (454 passed; ruff clean.)

### Task 10: Privacy policy document + accessible in-app link
- [x] Author `docs/privacy-policy.md` (fills in the `TBD` stub gist
      `https://gist.github.com/Stronautt/ff26be326e9736d3652d377e0dab25ba`). Match
      the user's reference-policy style (gist
      `https://gist.github.com/Stronautt/1915702dca62f322bb3936f270f67cb9`):
      plain, non-legalistic, bulleted, opening `Effective Date: 2026-06-20`;
      sections Overview / Information You Provide / How Your Data Is Used / Data
      Storage / Network Connections / Data Sharing / Mac App Store Builds /
      Permissions / Children's Privacy / Changes / Contact. **Contact email:
      `pavlo.o.hrytsenko@gmail.com`** (from the reference policy). Content scope —
      accurate to the code: local-first, no developer-operated servers or
      analytics; Jira URL/email/API-token (or OAuth client id/secret + rotating
      tokens) are sent **only** to the user's OWN Jira/Atlassian Cloud + Atlassian
      auth; GitHub update check runs in **non-store builds only**; optional
      custom-font download from GitHub/Google Fonts; PDF generation fully local;
      secrets stored in the OS keychain, non-secret settings in a local
      platformdirs JSON; nothing sold/shared; the developer never receives the
      user's data. (Draft for the user to refine afterwards.) (Created
      `docs/privacy-policy.md` with all 11 sections, the effective date, the
      contact email, and the local-first / no-analytics / Jira-own-instance scope,
      matching the reference gist's plain bulleted style.)
- [x] Enable **GitHub Pages** (serve `/docs`) for a clean public ASC
      privacy-policy URL; the GitHub blob URL also works immediately. (Manual repo
      Settings → Pages action — not automatable from here; the GitHub **blob URL**
      already wired into `PRIVACY_POLICY_URL` works immediately, so the in-app
      link and ASC field are usable today. Swap to the Pages URL when enabled.)
- [x] Add a `PRIVACY_POLICY_URL` constant **reusing**
      `update_checker.GITHUB_OWNER`/`GITHUB_REPO` (DRY):
      `https://github.com/Stronautt/epic-report-generator/blob/main/docs/privacy-policy.md`
      (swap to the Pages URL once enabled). (Added `PRIVACY_POLICY_URL` in
      `update_checker.py`, f-string-built from `GITHUB_OWNER`/`GITHUB_REPO`.)
- [x] Add the accessible **in-app link** in `ui/help_panel.py`: a centered footer
      `QLabel` "Privacy Policy" hyperlink below `self._view`, with
      `setOpenExternalLinks(True)`; tint the anchor **inline** in
      `_render()`/`set_dark()` (QSS can't colour an `<a>` — mirror
      `main_window._render_update_link`). The guide `QTextBrowser` already has
      `setOpenExternalLinks(True)` (`help_panel.py:343`). (Added
      `self._privacy_link` `QLabel` (`#privacyPolicyLink`, RichText,
      `setOpenExternalLinks(True)`, `AlignHCenter`) below `self._view`; `_render`
      re-tints the anchor inline with the theme's `link` colour, so `set_dark`
      re-colours it.)
- [x] write a pytest-qt test: `HelpPanel` exposes the privacy link carrying
      `PRIVACY_POLICY_URL`; assert the URL is built from
      `GITHUB_OWNER`/`GITHUB_REPO`; assert `docs/privacy-policy.md` exists and
      contains the required headings, the contact email, and the
      "no third-party analytics" / Jira-own-instance language.
      (`tests/test_privacy_policy.py`, 20 tests: URL DRY-built from
      owner/repo + shared with `RELEASES_URL`, `HelpPanel` exposes the link with
      the URL + `openExternalLinks`, the anchor re-tints on `set_dark`, and the
      doc carries all 11 headings, effective date, contact email, no-analytics,
      and Jira-own-instance language.)
- [x] run tests; must pass before the next task. (474 passed; ruff clean.)

### Task 11: Submission docs + project docs
- [x] Update `CLAUDE.md` (CI/Packaging table + a "Mac App Store channel" section:
      API-token-only, sandbox, inside-out signing, fresh-start migration note).
      (Added a `macOS (store)` row to the CI/Packaging table and a "Mac App Store
      channel" subsection: two channels, API-Token-only/hidden OAuth, sandbox +
      MAS plists, inside-out `sign_mas.sh`, `.pkg`/`build_pkg.sh`, fastlane, bundle
      identity, fresh-start container migration, no notarization.)
- [x] Add `docs/mac-app-store-submission.md`: privacy nutrition label draft
      (declare **Data Not Collected** — user data goes to the user's own Jira, not
      the developer — with a justifying review note), the account-handling note
      (no developer account created; Logout clears local keychain creds), the
      reviewer demo-account instructions (free Jira Cloud, low-priv user + API
      token, 2FA off), category (**Productivity**/*Business*), the macOS
      screenshot sizes (1280×800 / 1440×900 / 2560×1600 / 2880×1800, landscape)
      and shot list (login, Report Items config, report preview, an exported PDF
      page, settings/appearance), and the privacy-policy URL. (Created with
      sections Privacy Nutrition Label / Account Handling / Reviewer Demo Account /
      App Category / Screenshots / Fresh-Start Migration / Submission Checklist;
      the privacy-policy URL matches `update_checker.PRIVACY_POLICY_URL`.)
- [x] Add a `README` note: two macOS channels (`.dmg` direct vs MAS), MAS data
      lives in the sandbox container (no migration from `.dmg`), and a link to the
      privacy policy. (Added a "macOS: two channels" subsection under Install:
      direct vs MAS, hidden OAuth in store, separate sandbox-container storage / no
      migration, and a link to `docs/privacy-policy.md`.)
- [x] write a test asserting `docs/mac-app-store-submission.md` exists and covers
      the required headings (privacy label, demo creds, fresh-start).
      (`tests/test_mas_submission_doc.py`, 18 tests: file existence, all seven
      headings, Data-Not-Collected label, demo-account creds, Productivity
      category, the four screenshot sizes, fresh-start/no-migration + container
      path, the DRY privacy-policy URL, and the bundle ID.)
- [x] run tests; must pass before the next task. (492 passed; ruff clean.)

### Task 12: Verify acceptance criteria
- [x] Verify every Overview requirement is implemented (API-token-only store
      build; reversible OAuth; one bundle ID; MAS plists; inside-out sign;
      `.pkg`; fastlane; decoupled CI job). (All eight verified in-tree:
      `login_panel._oauth_enabled = not install_source.is_store_install()`
      (API-token-only); `entitlements.mas.oauth.plist` carries `network.server`
      (reversible OAuth); `desktop.BUNDLE_ID` == build.yml `MAS_BUNDLE_ID` ==
      `com.epicreportgenerator.app` (one bundle ID); all three
      `entitlements.mas*.plist` present (MAS plists); `sign_mas.sh` does
      inside-out `codesign`; `build_pkg.sh` runs `productbuild`; `fastlane/Fastfile`
      has lanes `bootstrap`/`profile`/`beta`/`release`; the `mas-upload` job +
      `mas_action` input live in `build.yml`, decoupled from `release`.)
- [x] Run the full unit suite (`pytest --tb=short`) — all green. (492 passed.)
- [x] Run the `--selftest` smoke (`QT_QPA_PLATFORM=offscreen … --selftest`).
      (SELFTEST OK.)
- [x] Run the linter; fix all issues. Confirm coverage meets project standard.
      (`ruff check .` → All checks passed; the 492-test suite covers every new
      Python/plist/shell/CI surface added in Tasks 1–11, nothing to fix.)

### Task 13: [Final] Knowledge docs
- [x] Cross-link the submission doc and research doc; note the
      `network.server`+`oauth` plist as the documented OAuth-enablement path.
      (`docs/mac-app-store-submission.md` now links to the research doc + plan and
      documents the OAuth re-enablement path via
      `packaging/macos/entitlements.mas.oauth.plist` (adds `network.server`);
      `docs/mac-app-store-research.md` adds a "Related docs" cross-link to the
      submission guide + plan and a "Shipped decision (v1) and the documented
      enablement path" note in §2.2; `CLAUDE.md` references all three docs and the
      oauth-plist flag-flip.)
- [x] Record the MAS signing/notarization distinction in project docs.
      (`CLAUDE.md` now spells out Dev-ID `.dmg` = notarized vs MAS `.pkg` = App
      Review + embedded provisioning profile, no notarization; the submission doc
      carries a "Signing vs. notarization" callout linking the research doc §3
      build→upload diff. `tests/test_knowledge_docs_crosslinks.py`, 12 tests:
      cross-links both ways + to the plan, OAuth-enablement path named in both
      docs + CLAUDE.md, and the signing/notarization distinction recorded in all
      three project docs.)

## Technical Details

- Bundle ID source of truth: `MAS_BUNDLE_ID` build var → Nuitka flag/`plutil` →
  `Info.plist`; same string in `desktop.py`, the ASC record, and the profile.
- Signing identities: app = "Apple Distribution: <Team> (<TeamID>)"; installer =
  "3rd Party Mac Developer Installer: <Team> (<TeamID>)".
- Entitlements mapping: container plist → `.app`; inherit plist → nested
  executables + main exe; nested dylibs/.so → identity only.
- Artifact transport: `ditto -c -k --keepParent` to zip; `ditto -x -k` to extract
  on macOS.
- Upload auth: ASC API key (`.p8`) base64 in `ASC_KEY_P8`; no Apple-ID password,
  no 2FA in CI.
- Re-runnability: `mas-upload` is independent of `notarize-macos` and the GH
  `release`, so it re-runs after a rejection without recompiling.