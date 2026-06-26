# CLAUDE.md

This file provides guidance to Claude Code when working with this repository.

## Project Overview

**Epic Report Generator** is a PySide6 desktop application that connects to Jira Cloud, fetches Epic progress data, and generates landscape 16:9 PDF reports. It supports two authentication methods: API Token (recommended) and OAuth 2.0 (3LO) via browser redirect.

## Commands

- `pip install -e ".[dev]"` — install in development mode
- `python -m epic_report_generator` — launch the application
- `pytest` — run tests
- `python -m build --wheel` — build pip wheel

## CI / Packaging

The GitHub Actions workflow (`.github/workflows/build.yml`) runs on `v*` tags and `workflow_dispatch`. It builds a wheel and a platform installer for each OS. Installer artifacts are retained for **3 days**; releases are created manually from the downloaded artifacts.

| Platform | Installer | Tool |
|---|---|---|
| Windows | `epic-report-generator-setup.exe` | Inno Setup (`packaging/windows/setup.iss`) |
| macOS (direct) | `epic-report-generator.dmg` | `create-dmg` from the Nuitka `.app` bundle (Developer-ID notarized) |
| macOS (store) | `epic-report-generator-mas.pkg` | `productbuild` from a re-signed Nuitka `.app` (Mac App Store) |
| Linux | `epic-report-generator.AppImage` | `appimagetool` + `packaging/linux/AppDir/` |

Key Nuitka flags used across all platforms:
- `--lto=yes`, `--python-flag=no_docstrings`, `--python-flag=no_asserts`, `--python-flag=isolated`
- `--noinclude-qt-translations`, `--include-qt-plugins=sensible`
- `--include-package-data=epic_report_generator.resources`, `--include-package-data=qt_material`
- `--nofollow-import-to` exclusions for unused stdlib modules and heavy PySide6 modules (WebEngine, 3D, Quick/QML, Multimedia, etc.)

Linux uses `--onedir` (not `--onefile`) because AppImage provides its own single-file SquashFS layer. macOS uses `--macos-create-app-bundle` with the display name `"Epic Report Generator.app"`. Windows uses `--onefile` with `--windows-console-mode=disable` and embeds a `.ico` converted at build time via Pillow from the generated `logo.png` (see below).

**App-icon assets.** The **single source of truth** for the app icon on every platform is the Icon Composer `.icon` bundle at `packaging/macos/logo.icon/` — **no raster logo is committed**. At build time `packaging/render_logo.py` reproduces the bundle's look into `resources/logo.png`: it paints the `icon.json` `fill` (the `automatic-gradient`, **Display-P3 → sRGB** converted, ≈`#D2E2EF`) as a subtle top-lighter vertical gradient into a rounded-square (squircle, radius ≈ 0.2237 × side) tile via `fillPath` (antialiased corners), then composites the foreground layer SVGs (`Assets/logo-objects.svg` under `Assets/logo-arrow.svg`, the order read from `icon.json` and painted back-to-front via PySide6 QtSvg) on top — so the PNG carries the **same background and shape** macOS renders from the same `.icon`, not a bare cut-out. (`--no-background` restores the historical transparent full-bleed foreground-only output.) The CI step **"Generate app logo from .icon bundle"** runs it before the wheel **and** the Nuitka build so both bundle the PNG. That `logo.png` feeds the Windows `.ico` (multi-size 16/24/32/48/64/128/256), the Linux AppImage/hicolor icons, the in-app `setWindowIcon`, and the Help-panel banner. `setWindowIcon` is **Windows/Linux only** — `run_app` skips it on macOS (`sys.platform == "darwin"`), because there a window icon **overrides the bundle Dock icon at runtime**: a full-bleed window icon was what made the *running* app show the wrong/oversized icon regardless of the `.icns`/`Assets.car` in the bundle. macOS instead gets its HIG-padded bundle icon from the *same* `.icon` via actool (two-tier, below); the old padded **`logo-macos.png`** variant and the `--macos-app-icon` flag were dropped. From source (no CI), `logo.png` is absent unless you run `python packaging/render_logo.py …`, and every consumer degrades gracefully (warns, skips the icon). **macOS app icon (two-tier).** The `.dmg`/`.pkg` bundle icon is **two-tier**: macOS 26 "Tahoe" gets a Liquid Glass icon and macOS 12–15 a legacy icns. The Liquid Glass source is an **Icon Composer** `.icon` bundle at `packaging/macos/logo.icon/` (`icon.json` defines a light gradient fill + two layers — `logo-objects` under `logo-arrow`, the arrow carrying dark/tinted specializations — over SVG art in `Assets/`). The build job's **"Compile Liquid Glass app icon"** step runs `xcrun actool` (Xcode 26, on the `macos-26` runner) to compile it into `Contents/Resources/` — actool emits **both** `Assets.car` (Tahoe Liquid Glass) **and** a flattened legacy `logo.icns` fallback derived from the same `.icon`. The step sets `CFBundleIconName=logo` (Tahoe → `Assets.car`) and `CFBundleIconFile=logo` (macOS 12–15 → `logo.icns`), then removes any stray `Icons.icns` (a `rm -f` no-op now that Nuitka emits none). It runs after Nuitka but **before** the unsigned-app archive (so the MAS `.pkg` inherits it) and **before** signing (so the bundle signature seals `Assets.car`/`logo.icns` — neither is Mach-O, so the strip/vtool steps skip them). Because actool derives the 12–15 fallback from the `.icon`, the macOS bundle icon needs **no committed PNG at all** — the padded `logo-macos.png` variant and the `--macos-app-icon` Nuitka flag were both removed (Nuitka therefore bakes no `Icons.icns`). The `.icon` layers were produced by stripping the `#D2E2EF` squircle background from `logo-test.svg` and splitting the black trend arrow onto its own layer (`packaging/macos/logo.icon/Assets/`). For Linux desktop integration the icon must land in `AppDir/usr/share/icons/hicolor/{256x256,512x512}/apps/epic-report-generator.png` (the AppDir-root `.DirIcon` only feeds the file-manager thumbnail; AppImageLauncher/`appimaged` read the menu icon from the hicolor theme). On Windows, `app._set_windows_app_id()` sets the `AppUserModelID` to `desktop.BUNDLE_ID` before the first window so the taskbar button unifies with the pinned shortcut. On Linux, the **running window's** dock/taskbar icon is resolved by matching the window's `WM_CLASS` / Wayland `app_id` to a `.desktop` entry (GNOME/Wayland ignores `setWindowIcon`), so `run_app` calls `app.setDesktopFileName(desktop.APP_ID)` and **both** the AppImage `.desktop` (`packaging/linux/AppDir/`) and the from-source `_DESKTOP_ENTRY` carry `StartupWMClass=epic-report-generator` — all three (`app_id`, `StartupWMClass`, `.desktop` basename) must equal `epic-report-generator`.

Both macOS channels sign **inside-out** (strip every Mach-O, sign deepest-first with our Team ID, the app bundle last — no `--deep`) via sibling scripts: `packaging/macos/sign_devid.sh` for the Developer-ID `.dmg` (hardened runtime + the `cs.*` entitlements in `entitlements.plist`) and `packaging/macos/sign_mas.sh` for the Mac App Store `.pkg` (App Sandbox + inherit entitlements). Because every nested binary is re-signed under one Team ID, **neither needs `disable-library-validation`**. `sign_devid.sh` falls back to an inside-out ad-hoc signature when no `MACOS_SIGN_IDENTITY` is set (forks / no-secrets CI); it is invoked from the build job's "Sign binaries (macOS)" step.

Only installer artifacts are uploaded — plain binaries are not retained. The `release` job is tag-driven and downloads with an `installer-*` pattern, so it publishes **only** the three platform installers (Dev-ID `.dmg` + Windows/Linux); the cross-job handoff artifacts (`unsigned-macos-app`, `notary-submission-id`) and the Mac App Store `.pkg` are **not** part of it. The `.pkg` is never stored as a workflow artifact at all — it goes straight to TestFlight.

**macOS `qt.conf` (App Sandbox startup crash).** The build job's **"Write Contents/Resources/qt.conf (macOS)"** step copies `packaging/macos/qt.conf` (`[Paths] Prefix = MacOS`, `Plugins = MacOS/PySide6/qt-plugins`) into the bundle's `Contents/Resources/` before the icon/`vtool`/upload steps and **both** sign scripts, so each channel inherits it and the signature seals it. It pins Qt's prefix so `QLibraryInfo` never derives it from the main bundle. **Why it's required:** under the **App Sandbox** (MAS only), a LaunchServices/`launchd` launch leaves `CFBundleGetMainBundle()` **NULL** during QtCore's *pre-`main()` static init* (a global `QLoggingCategory` → `QLoggingRegistry::instance()` → `QLibraryInfoPrivate::paths`), and Qt 6.11 passes that NULL straight into `CFBundleCopyBundleURL` → `EXC_BAD_ACCESS` / `KERN_INVALID_ADDRESS at 0x8` before any Python runs. The Dev-ID `.dmg` dodged it (non-sandbox launch resolves the bundle), so the TestFlight `.pkg` crashed on **every** launch while the `.dmg` was fine — same Nuitka binary. Of Qt's startup qt.conf lookups only **`Contents/Resources/qt.conf`** (`CFBundleCopyResourceURL`) is consulted that early; `Contents/MacOS/qt.conf` needs a live `QCoreApplication` and does **not** fix it (both confirmed by re-signing the `.app` ad-hoc with `entitlements.mas.plist` and launching via `open`). It is harmless to the Dev-ID build and non-load-bearing for plugins (Nuitka still sets `QT_PLUGIN_PATH`) — it only short-circuits the relocatable-prefix path.

### Mac App Store channel

macOS ships through **two** independent channels from the same Nuitka `.app`:

- **Direct download** (primary): the Developer-ID notarized `.dmg`. Keeps OAuth.
  `build` → `notarize-macos` → `release`, unchanged.
- **Mac App Store** (MAS): a sandboxed, TestFlight-distributed `.pkg`. Built by a
  **`mas-upload` job** (`needs: build`, `runs-on: macos-26`) that runs in the
  tag-driven flow — gated on the `v*` tag ref (`if: startsWith(github.ref,
  'refs/tags/v')`) plus MAS secrets, so forks/PRs and non-tag dispatches skip it.
  It only **validates then uploads to TestFlight** (`fastlane mac beta`); App
  Review submission (`fastlane mac release`) is **not** automated. The GitHub
  `release` job is **gated on it** (`mas-upload` is in `release`'s `needs`): a
  failed TestFlight upload must not cut a release. Because `mas-upload` shares
  `release`'s `v*` gate and every MAS step no-ops (job still succeeds) when the
  MAS secrets are absent, forks / no-secrets runs are unaffected — the gate only
  bites when MAS is configured and genuinely fails. (Trade-off: a real
  TestFlight/ASC hiccup will now hold back the public installer release until the
  run is fixed or re-run.)

Key MAS differences from the Dev-ID build:

- **API-Token sign-in only.** The OAuth tab is hidden in store builds
  (`login_panel` gates `_build_oauth_tab()` on `install_source.is_store_install()`).
  OAuth can return later via the `entitlements.mas.oauth.plist` (adds
  `network.server`) plus un-gating the tab — a flag-flip, not a rewrite. The
  Dev-ID `.dmg` keeps OAuth.
- **Sandbox + entitlements.** `packaging/macos/entitlements.mas.plist` (container:
  `app-sandbox` + `network.client` + `files.user-selected.read-write`) and
  `entitlements.mas.inherit.plist` (nested: `app-sandbox` + `inherit`). **No
  `cs.*`** entitlements and **no hardened runtime** (those stay on the Dev-ID
  `entitlements.plist`). No XML comments (AMFI rejects `<!--`); a plist guard test
  enforces both.
- **Inside-out signing.** `packaging/macos/sign_mas.sh` strips, then signs
  deepest-first with the **Apple Distribution** identity (every nested
  `*.dylib`/`*.so` incl. the Typst `.so`, frameworks as bundles, nested
  executables + main exe with the inherit entitlements), then the app bundle last
  with the container entitlements. **No `--deep`**, no `disable-library-validation`
  (re-signing with our Team ID makes library validation pass). The Dev-ID `.dmg`
  signs inside-out the same way via `packaging/macos/sign_devid.sh` (hardened
  runtime + `entitlements.plist` in place of sandbox/inherit), so it too dropped
  `disable-library-validation`.
  Before the final app-bundle signing, `sign_mas.sh` injects
  **`com.apple.application-identifier`** (+ `com.apple.developer.team-identifier`)
  into a copy of the container entitlements — Xcode adds these automatically but
  plain `codesign` does not, and TestFlight rejects a build whose signature lacks
  the app identifier present in the profile (**ITMS-90886**). The value is decoded
  from the embedded provisioning profile (`security cms -D`, exact match) with an
  `$APPLE_TEAM_ID` + bundle-id fallback.
- **`.pkg` wrapper.** `packaging/macos/build_pkg.sh` runs `productbuild
  --component … /Applications --sign "<Mac Installer Distribution>"`, with an
  optional `altool --validate-app` gated on ASC creds.
- **fastlane.** `fastlane/Appfile` + `Fastfile` (lanes `bootstrap`, `profile`,
  `beta`, `release`; ASC API key; **no `match`/`gym`** — Nuitka builds the `.app`).
  `Gemfile` pins `fastlane`. `bootstrap`/`produce` runs locally once.
- **Bundle identity.** One `CFBundleIdentifier = com.epicreportgenerator.app`
  (`MAS_BUNDLE_ID` build var + `desktop.BUNDLE_ID`), plus MAS Info.plist keys
  (`LSApplicationCategoryType`, `ITSAppUsesNonExemptEncryption=false`,
  `LSMinimumSystemVersion`, and a monotonic `CFBundleVersion`). The build
  number **folds the marketing version into the commit count** so it can't
  collide or regress across releases: `CFBundleVersion = MAJOR*1e12 + MINOR*1e9
  + PATCH*1e6 + git rev-list --count HEAD` (a single integer, ~13 digits, well
  under Apple's 18-char limit; TestFlight compares it numerically). The version
  dominates the ordering — a newer release always outranks an older one even if
  history was rebased/squashed — while the commit count disambiguates builds
  within a version. `CFBundleShortVersionString` stays the bare pyproject
  marketing version. (A bare commit count carried no version, so it could repeat
  or go backwards; rebuilding the *identical* commit at the *same* version still
  collides — bump the version for that.)
- **Deployment target (12.0).** The runners are Apple Silicon, so Nuitka emits an
  **arm64-only** `.app`; the App Store accepts arm64-only only at a **macOS 12.0+**
  deployment target (**ITMS-90869**), and it reads the **Mach-O `LC_BUILD_VERSION`
  `minos`** — not `LSMinimumSystemVersion` — across *every* nested binary. Nuitka
  bakes `minos` from the building Python and ignores `MACOSX_DEPLOYMENT_TARGET`
  (Nuitka #2513), so the build job's **"Set Mach-O minimum macOS version"** step
  rewrites every Mach-O with `vtool -set-build-version macos $MACOS_DEPLOYMENT_TARGET
  … -replace` *after* Nuitka and *before* any signing (vtool invalidates
  signatures; the signing steps re-sign). `MACOS_DEPLOYMENT_TARGET = "12.0"` drives
  both the plist key and the `vtool` rewrite, and the floor is shared by **both**
  channels (the Dev-ID `.dmg` also requires macOS 12).
- **Fresh-start migration.** No auto-migration from the `.dmg`. MAS data lives in
  the sandbox container `~/Library/Containers/com.epicreportgenerator.app/Data/…`,
  separate from the `.dmg`'s `~/Library/Application Support/…`.
- **No notarization.** Where the Dev-ID `.dmg` is notarized (`notarytool` +
  staple), the MAS `.pkg` is **not** — App Review replaces notarization, and the
  app carries an embedded provisioning profile instead of a notarization ticket.
  Self-update is disabled in store builds (`install_source` `_MASReceipt` gating,
  already correct).

Three cross-linked docs cover the channel: the feasibility analysis in
`docs/mac-app-store-research.md`, the in-repo execution plan in
`docs/plans/2026-06-20-mac-app-store-distribution.md`, and the ASC-side
submission metadata (privacy nutrition label, demo creds, category, screenshots)
in `docs/mac-app-store-submission.md`; the privacy policy is
`docs/privacy-policy.md`. The OAuth re-enablement path is documented as the
`entitlements.mas.oauth.plist` (adds `network.server`) flag-flip.

## Tech Stack

- **GUI**: PySide6 (Qt 6)
- **Theming**: `qt-material` (Material Design base themes) + app-specific QSS overlays
- **Jira API**: `jira` library (pycontribs/jira)
- **OAuth**: hand-rolled Atlassian OAuth 2.0 (3LO) over `requests`
- **PDF**: Typst (`typst-py`) — bundled `.typ` templates compiled to PDF
- **Charts**: drawn natively in Typst (Gantt timeline + dual-axis trend chart); no matplotlib. The trend chart is a **per-event, time-proportional** burnup: `metrics._build_time_series` emits **one point per changelog event** (issue enter / SP-change / completion) at its **exact timestamp** — plus a left anchor (window/earliest, with pre-window events folded into it as carryover) and a right anchor at `reference_date` so the staircase reaches the edge — rather than one sample per day. Same-instant events collapse into a single combined step. `m.dates` therefore holds `datetime`s (tz-stripped via `metrics._naive` so aware Jira timestamps compare with naive window/ref dates), and the view-model carries a per-point fraction list `xs` (`(t−t0)/(t1−t0)`, in the payload) that `trend_chart.typ`'s `xof(i)` reads instead of a uniform `i/(n-1)` index — so same-day events spread along x like Jira's. It uses **step-after (staircase) interpolation** for the cumulative lines *and* the SP area tops (a value holds flat until its next event, then jumps — never a diagonal ramp; `trend_chart.typ`'s `step-pts` builds the point lists) and paints **alternating ISO-week background bands** (`c.surface`). `report_view_model._week_bands(dates)` computes the bands from the **time range** `[t0,t1]` (Monday-aligned weeks → fractional x-ranges, every other week; carried as `bands`) and `_time_ticks(dates, target=10)` places ~10 date labels at their true time-fraction (`{x,label}`); `_nice_axis(target=10, step≥1, no 2.5)` yields ~10 whole-number gridlines. The Unestimated line is a neutral, accent-independent `c.text` ink (not amber `c.yellow`) so it stays legible over the accent-tinted Completed-SP area for any custom accent. The per-event series needs the changelog (`JiraClient.enrich_trend_history`, attached in `preview_panel` after fetch); without it each issue contributes a single enter (at `created`) + done (at `resolved`) point, still time-proportional
- **Token storage**: `keyring` (OS-native)
- **Config**: `platformdirs` + JSON
- **Dates**: python-dateutil
- **Docs rendering**: Python-Markdown (`markdown`) — renders the bundled user guide to HTML in the Help panel
- **Python**: >=3.11

## Project Structure

```
src/epic_report_generator/
├── __init__.py                    # Package version
├── __main__.py                    # Entry point
├── app.py                         # QApplication setup, signal handlers
├── core/
│   ├── data_models.py             # Dataclasses: JiraIssue (with parent_key, progress, effective_weight, hierarchy_parent_key, display_tier, issue_type_id, show, in_estimate), EpicData, EpicMetrics, ReportConfig (with issue_hierarchy), ReportData, ReportItem (with child_overrides + child_order), ChildOverride, TimelineItem, HierarchyNode; average_certainty(), order_by_keys(), serialize_hierarchy()/coerce_hierarchy(), epic_tier_type_names(), migrate_default_hierarchy() helpers
│   ├── jira_client.py             # JIRA library wrapper, API-token + OAuth connection, pagination, retry, date expansion
│   ├── metrics.py                 # Bottom-up hierarchical progress, velocity, cycle time, scope change, forecasting, time-series
│   ├── theming.py                 # Accent-colour maths shared by app + report: hex/mix/lighten, qt_shades(), report_overrides()
│   ├── report_view_model.py       # Flattens ReportData → JSON payload + native chart geometry (Gantt, trend)
│   ├── pdf_generator.py           # Orchestrates view-model + Typst render (generate_pdf → bytes)
│   └── typst_renderer.py          # Compiles bundled .typ templates to PDF (temp-dir project, bundled + custom fonts)
├── services/
│   ├── auth_manager.py            # OAuth 2.0 (3LO) flow + API-token auth + keyring token storage
│   ├── config_manager.py          # JSON config via platformdirs
│   ├── font_manager.py            # Provision custom fonts (file copy / Google Fonts download) for UI + report
│   ├── install_source.py          # Detect store installs (Mac App Store / MS Store / Snap / Flatpak) to gate self-update
│   ├── oauth_server.py            # Local HTTP callback server for OAuth redirect
│   └── update_checker.py          # GitHub latest-release check (no cache; 404=no stable release) + version compare
├── ui/
│   ├── main_window.py             # Login overlay → sidebar/stacked-panel layout
│   ├── login_panel.py             # Dual-auth login: API Token tab + OAuth tab, session restore
│   ├── config_panel.py            # Epic keys (tag input), metadata, field mapping
│   ├── report_panel.py            # Two-step flow: configuration + preview (collapsible sections)
│   ├── preview_panel.py           # PDF generation worker, QPdfDocument preview, export
│   ├── settings_panel.py          # Connection info, theme + accent/font customization, logout, defaults
│   ├── log_panel.py               # Live log viewer with level filtering
│   ├── help_panel.py              # User Guide: bundled user-guide.md → HTML (Python-Markdown) in a themed QTextBrowser; native banner header
│   ├── widgets.py                 # Reusable: StatusIndicator, LabelledField, GuideStep,
│   │                              #   CollapsibleSection, ReportItemTable (drag-to-reorder,
│   │                              #   per-row customize button), ChildCustomizeDialog,
│   │                              #   SidebarUserInfo, IssueHierarchyEditor (three tier
│   │                              #   silos of _HierarchyItemCard, per-card Show/Estimate
│   │                              #   toggles + _RelationshipButton, drag between silos)
│   └── styles.py                  # App-specific QSS overlays on top of qt-material base themes
└── resources/
    ├── typst/                     # Templates: theme, components (gantt, trend_chart, progress_bar, …), pages
    ├── fonts/                     # Bundled Inter (deterministic cross-OS rendering) + Noto Sans CJK JP (CJK fallback)
    └── user-guide.md              # End-user guide, rendered in-app by help_panel (bundled as package data)
```

No raster logo is committed: `resources/logo.png` (the gradient-squircle Windows/Linux/in-app icon, matching the `.icon` background + shape) is generated at build time from `packaging/macos/logo.icon/` by `packaging/render_logo.py`; the macOS bundle icon is compiled from the same `.icon` via actool. See **App-icon assets** above.

## Architecture

### Authentication

Two methods are supported — the login panel shows both as tabs:

1. **API Token** (recommended): user provides Jira URL + email + API token. Token stored in `keyring` under `"api_token"` key; URL/email stored in config.

2. **OAuth 2.0 (3LO)**: browser-based Atlassian consent flow. Requires client_id/client_secret from the Atlassian Developer Console (stored in config). Tokens (access + rotating refresh) stored in `keyring` under `"tokens"` key.

Session restore on launch: reads auth_method from config, retrieves tokens from keyring, refreshes if expired.

### Estimation Methods

Two estimation methods are supported — selectable in the Config panel under "Custom Field Mapping":

1. **Story Points** (default): uses the `story_points` (or custom) field on each issue. Labels display "SP".

2. **Time — Days**: uses `(due_date - start_date).days` as the estimate for each issue. Issues missing either date are counted as unestimated. Labels display "Days".

The `estimation_method` field on `ReportConfig` (`"story_points"` or `"time_days"`) threads through `calculate_metrics()`, chart generation, and PDF rendering. `EpicMetrics.estimation_unit` (`"SP"` or `"Days"`) drives all display labels.

### Scope Certainty (FR-13)

Each report item (epic or label) carries an optional scope certainty
(`ReportItem.scope_certainty`: `None`/`"Low"`/`"Medium"`/`"High"`) chosen in the
`Cert.` column of the `ReportItemTable`. Each row also has a **customize** button
(gear icon, left of the remove button) that opens `ChildCustomizeDialog`, listing
the item's children — the epics under a label, or the stories/tasks under an epic
(fetched fresh on every open via `JiraClient.fetch_epic_summaries_by_label` /
`fetch_child_summaries`). Per child the user can override the **display name**,
**scope certainty**, and **include** flag (checkbox, default on — unticking it
drops the child from the report entirely), persisted in `ReportItem.child_overrides`
(`dict[str, ChildOverride]`, keyed by child Jira key) inside `last_report_items`.

`ChildOverride` is **recursive**: for an *epic* child of a label item it also
carries nested `child_overrides`/`child_order` for that epic's own stories/tasks.
Each epic row in the dialog (`kind == "label"`) has its own **gear** that emits
`ChildCustomizeDialog.child_settings_requested`; `config_panel._on_child_epic_settings`
fetches that epic's children fresh and opens a nested `ChildCustomizeDialog`
(`kind="epic"`), writing the result back via `_ChildRow.set_nested`. Story/task
children (leaf) get no gear. Persistence is compact (`_serialize_override` omits the
default `include` and empty nested fields, so simple rows keep the historical
`display_name`/`scope_certainty` shape); `_coerce_overrides` reads it back recursively.

The dialog is a per-row widget grid (`_ChildRow` in `_ChildRowList`): always-
visible display-name editor (placeholder = the Jira summary) + **Include** checkbox +
certainty combo (+ gear for epic children), with a **drag handle** per row to
**reorder** children (mirrors `ReportItemTable`'s internal-move drag). The chosen
order persists as `ReportItem.child_order` (`list[str]` of child keys) in
`last_report_items`. In `preview_panel._generate_report` the helper
`_resolve_children` applies all per-child overrides together — it **drops excluded
children** (removing them from the metrics, timeline, and any detail page), reorders
the survivors by `child_order` (mirrors `widgets._order_children` / `_apply_child_order`;
unknown keys keep Jira's fetched order, appended after; empty = Jira order), and
applies display-name overrides. It runs on a top-level epic's stories, on each label
epic's stories (via the nested override), and the epic-level include filter drops
excluded epics from the label group.

Parent vs. child precedence:

- **Parent certainty set** (`Low`/`Med`/`High`) — all children inherit it; the
  per-child certainty selectors in the dialog are disabled.
- **Parent `"--"` (consolidated)** — children may each set their own certainty,
  and the report shows the **average** (`average_certainty()` maps Low/Med/High →
  1/2/3, averages set values, rounds, maps back). This is FR-13's "Consolidated"
  behaviour, triggered by the default `"--"` rather than a separate dropdown entry.
  This applies recursively: a label epic left at `"--"` consolidates the certainties
  of its own (included) stories/tasks set via the nested gear dialog.

Overrides are applied in `preview_panel._generate_report`: child display names
overwrite `JiraIssue.summary` (epic items) or `EpicData.summary` (label items),
and certainty flows to `EpicMetrics.scope_certainty` per source epic / group.
Switching a row's kind (epic↔label) drops its now-stale child overrides **and
child order**.

### Report Item Validation

A **Validate** action sits in the "Report Items" section header (right of the
title). It checks **every** non-empty row — both epics and labels — against Jira
in a background task (`config_panel._validate_items`):

- **Epics**: invalid key format or not found → **error**.
- **Labels**: no epic carries the label → **error**.
- **Child overrides** (rows with `child_overrides`): each overridden child key is
  re-fetched (`fetch_child_summaries` for epics, `fetch_epic_summaries_by_label`
  for labels); any key that no longer exists → **warning**.

Results are surfaced two ways instead of the old per-epic success list: the
offending row's key field is outlined (red for error, amber for warning, via
`_ReportItemRow.set_validation`, cleared automatically on the next edit), and a
`#validationSummary` callout below the table lists the problems in **row order**
("Error: …" / "Warning: …"). With no problems it shows a brief confirmation only.

`validate_items(on_complete)` is also the gate for **Generate Report**
(`report_panel._on_generate`): generation runs the same check first and, via the
`(has_errors, has_warnings)` callback, **blocks on any error** — keeping Step 1
expanded and scrolling back to the flagged rows (`report_items_anchor`) — while
**warnings never block** (generation proceeds, with Step 1 left open so the
warning callout stays visible).

### Issue Hierarchy

Each report **profile** can define a custom issue-type hierarchy chain
(`ReportConfig.issue_hierarchy`, a `list[HierarchyNode]`). A `HierarchyNode`
(`data_models.py`) is one Jira issue type collapsed into the report's three fixed
**display tiers** (0=Epic, 1=Story, 2=Sub-task) with an `edge` to the tier above
(`"parent"` = Jira's native parent, or `"link"` = one-or-more issue-link types
matched either direction), plus a `show` axis (display-only) and an `in_estimate`
axis (counts in metrics — the old `include_subtasks`). Serialized compactly
(`serialize_hierarchy`/`coerce_hierarchy`, default fields omitted).

An **empty chain derives the classic `Epic→Story→Sub-task` default byte-for-byte**.
The four removed global checkboxes (`include_subtasks`, `include_subtasks_in_timeline`,
`show_epic_stories_on_timeline`, `show_subtasks_on_timeline`) are kept on
`ReportConfig` **read-only for migration**: `config_panel._restore_hierarchy`
leaves the chain empty when all are default, else `migrate_default_hierarchy()`
maps them onto per-tier `show`/`in_estimate`. Only `issue_hierarchy` is written
going forward.

Fetch (`jira_client.py`): `_is_custom(chain)` (a `link` edge only — a parent-only
chain of any size stays on the fast path) routes to the N-tier `_fetch_epics_chain` (BFS, one frontier per **display tier** — *not*
per chain node: several issue types share a tier (Story + Bug at tier 1; Task +
Sub-task at tier 2) and a child tier maps **many-to-many** onto the tier above, so
each tier's frontier is the **union** of all preceding-tier matches. Walking
node-by-node — the old bug — reassigned the frontier after every node, so a second
same-tier node with no children (e.g. Bug) overwrote the first node's frontier and
any deeper tier broke on an empty frontier, dropping e.g. link-edge Tasks hung off a
Story. `_chain_tier_children` now fetches a whole tier at once: all parent-edge nodes
share **one** `parent in (...)` query, each `link` edge reads the frontier issues'
`issuelinks` and batch-fetches matching targets; each row is then claimed by the tier
its type resolves to. `apply_hierarchy` resolves **both** axes the same way: `show`
(visibility) and `in_estimate` (metrics) each **AND-cascade** up the
`hierarchy_parent_key` ancestry + the tier-0 node, so a hidden/excluded parent
hides/excludes its descendants (a Sub-task whose Story parent is hidden drops off the
timeline/nested rows with it; an excluded parent drops its descendants' weight). The
fast-path sub-task fetch is gated permissively (many-to-many): fetch when
**any** tier-2 node is shown, or any is estimated **and** some tier-1 ancestor + the epic
are estimated — the cascade then hides/excludes any that an ancestor tier drops. A
**non-custom migrated chain** stays on the fast path `_fetch_epics_bulk`, which
mirrors the chain's tier-1 node onto direct children and the tier-2 node onto
subtasks (`display_tier`/`show`/`in_estimate`) so the metrics, timeline-date, and
view-model layers gate purely on those fields instead of the legacy booleans —
**both axes must be applied or migrated profiles regress** (timeline bars / nested
summary rows). `epic_tier_type_names(chain)` (tier-0 type names, default `["Epic"]`)
is the single source for the label JQL, label validation, and epic autocomplete.

Display: the view-model treats any non-empty `issue_hierarchy` as "custom" and emits
nested summary rows + per-`show` timeline bars + issue-type icons. Icons fetch lazily
via `JiraClient.issue_type_icon` (byte cache, caches failures); `typst_renderer`
writes each into the throwaway project as `icons/<id>.<ext>` where the extension is
**sniffed from the bytes** (`icon_ext` — Jira serves PNG as often as SVG, and a
wrong extension hard-errors the whole Typst compile). The view-model's `_icon_path`
routes the filename through the same `icon_ext` so path and file always agree.

The chain is edited in `IssueHierarchyEditor` (`widgets.py`) under **Step 1 → Issue
Hierarchy** — **three tier silos** (Epic / Standard / Sub-task), each a column of
compact `_HierarchyItemCard`s (icon + type name + a `_RelationshipButton` that picks
Parent-or-link-types, + Show/Estimate toggle buttons + remove) with a dashed "+ Add"
picker of the still-unused types; cards drag between silos to change their tier, and
all silos empty ⇒ `to_hierarchy() == []` ⇒ the classic default. A "Refresh from Jira"
button reloads live issue/link types + icons. `config_panel` threads
`to_hierarchy()` into every Jira call that depends on the chain — report fetch,
**Validate**, and the per-item **customize** dialogs (epic + nested label-epic) —
so all surfaces see the same children.

### Timeline Date Computation

Timeline dates determine when epics appear on the Gantt-style timeline chart. Each `EpicData` and `JiraIssue` has separate `timeline_start`/`timeline_end` fields alongside the estimation `start_date`/`due_date`.

Two independent date field pairs are configurable in the Config panel under "Custom Field Mapping":

1. **Estimation dates** (`start_date_field`/`due_date_field`): used for time-based estimation (`time_days` method) and the trend chart time-series. Stored on `ReportConfig` as `start_date_field`/`due_date_field`.

2. **Timeline dates** (`timeline_start_field`/`timeline_end_field`): used for the Gantt chart. Stored on `ReportConfig` as `timeline_start_field`/`timeline_end_field`. Defaults to the estimation fields when not explicitly set.

Epic-level date expansion (`_fill_epic_dates_from_children`) pools dates from the epic itself and all children:

- **Estimation dates**: cascade `start_date`/`due_date` → `created`/`resolved`.
- **Timeline dates**: cascade `timeline_start`/`timeline_end` → sprint start/end dates → `start_date`/`due_date`. The sprint fallback matches Jira Cloud Timeline behaviour, which derives epic ranges from child sprint assignments when no explicit date fields are set.

The same cascade is applied in `merge_metrics()` when building synthetic label-group epics.

### Fixed Timeline Window

The Config panel's **Fixed Start Date** / **Fixed End Date** pickers (under the
Report Content section; a min 5-day gap is enforced) store
`ReportConfig.timeline_hard_start` / `timeline_hard_end` (`date | None`). When
set they **cap** the report to that window on two surfaces that must stay
consistent:

1. **Gantt timeline axis** (Page 3): `report_view_model._build_timeline` /
   `_timeline_data` lock `range_start`/`range_end` to the hard dates instead of
   auto-scaling from the data.

2. **Per-epic/label detail page** (chart + sidebar stats): `preview_panel`
   threads `timeline_hard_start`/`timeline_hard_end` into `calculate_metrics` /
   `merge_metrics` as `window_start` / `window_end`, so the page never reflects
   activity outside the fixed window:
   - `window_end` caps the effective "as of" instant (`reference_date`), which
     bounds the **velocity** lookback, the **forecast** origin, and the **trend
     chart**'s last day.
   - **velocity** counts only resolutions `≤ reference_date`, with its lookback
     clamped up to `window_start` (and the per-week divisor shrunk to match a
     narrow window).
   - **avg cycle time** counts only issues *resolved* inside the window (the
     full created→resolved span is still measured).
   - **scope change** considers only issues *created* inside the window, which
     alone form its denominator and baseline.
   - the **trend time-series** is clipped to `[window_start, reference_date]`;
     cumulative totals carry over (the left-anchor point folds in every event at
     or before the window start, so it still includes all issues created before
     the window — the chart is zoomed, not recomputed).

   Progress and the estimate roll-ups are deliberately **not** windowed — they
   always reflect the whole epic. Leaving both dates unset (`None`) keeps the
   historical unbounded behaviour byte-for-byte.

### Progress Calculation

Progress is computed **bottom-up** through the issue hierarchy:

1. **Leaf issues** (no subtasks): 100% if Done, 0% otherwise. Weight = estimate (SP or days) when using Combined, or 1.0 for Issues Only.
2. **Parent issues** (with subtasks): weighted average of subtask progress. Weight = own estimate if set, else sum of subtask weights.
3. **Epic progress**: weighted average of direct children's progress (excludes subtasks already accounted for through their parent).

Two progress methods are supported (`ReportConfig.progress_method`):

- `"combined"` (default) — bottom-up weighted average × (done_issues / total_issues). Considers both estimate weights and issue-count ratio.
- `"issues_only"` — bottom-up weighted average with weight = 1.0 for all items (purely counts open vs done). Legacy value `"story_points_only"` is normalised to `"issues_only"` for backward compatibility.

```python
# Combined example: 1 done (5 SP) + 1 todo (5 SP)
# weighted_avg = (100*5 + 0*5) / 10 = 50%
# progress = 50% × (1/2) = 25.0
#
# Issues Only: same items
# progress = (100*1 + 0*1) / 2 = 50.0
#
# Returns 0 when total_issues == 0; clamped to [0, 100]
```

For **label-group merges** (`merge_metrics`), progress is the weighted average of per-epic progress values (each weighted by the sum of its direct children's effective weights), rather than flattening all children.

### PDF Layout

Landscape pages 406mm wide. The title and per-epic pages are a fixed 16:9 (406mm x 228.4mm). Page 1: title page. Page 2: summary table with progress bars (label-group header rows show aggregated statistics) and a Scope Certainty column + legend that appear **only when at least one item sets a certainty** (`summary.has-certainty`); the aggregate KPI strip shows Epics / Overall / Issues / Total {unit} / Done {unit}. Page 3 (optional): Gantt-style timeline chart with optional scope-certainty legend — included by default but can be excluded via `ReportConfig.show_timeline_chart`. Remaining pages: per-epic detail with trend chart + metrics sidebar.

**Adaptive height (summary + timeline only).** These two pages render on `#page(height: auto)` (`main.typ`) so a large table or Gantt grows the sheet taller instead of paginating onto a second page. The floor is the standard 228.4mm height: `summary.typ` measures its body and pads up to the floor; `timeline.typ` measures the heading/legend and hands the Gantt a `min-height` so it fills to the floor, then grows beyond it. The Gantt (`gantt.typ`) therefore computes its own intrinsic height from a fixed per-row height (floored to `min-height`) rather than reading the page height. Epic detail and title pages keep their fixed 16:9 height; the epic loop uses `pagebreak(weak: true)` so the auto-height pages introduce no blank pages.

**Progress vs. certainty colour separation.** Whenever a scope certainty is in play, the two axes are kept on *different visual channels* so they never read as the same thing: **colour means certainty, length/threshold means progress**. The rule is conditional on whether any certainty is set, and is applied consistently on both the summary and the timeline.

On the **summary table** the Scope Certainty cell (`cert-meter`/`certainty-cell` in `pill.typ`) is a 3-segment confidence meter whose filled-segment **count** encodes the level (High=3 / Medium=2 / Low=1) and whose **colour** carries the certainty (green/amber/red via `certainty-color`). The progress bar (`progress_bar.typ`, `neutral:` flag driven by `show-cert`) is then a neutral **grey** fill so colour is reserved for the meter. When no item sets a certainty the column is dropped and the bar reclaims the informative `progress-color` threshold (green >= 75%, yellow >= 25%, red < 25%), since there is no longer any collision to avoid.

On the **timeline** (`gantt.typ`) the same principle is driven by `color-by-certainty` (from `timeline.has-certainty`): when any item has a certainty the epic bars **and** the group roll-up bar are tinted by `certainty-color` (the group by its aggregate, `average_certainty` over its member epics — matching the summary group row); otherwise both fall back to `progress-color`.

When `confidential` is enabled and `company_name` is set, a repeating footer appears on all pages except the title page: "CONFIDENTIAL — {company_name}" on the left, report date and author on the right.

**Export location.** The "Export as PDF" dialog (`preview_panel._export_pdf` / `_initial_export_dir`) opens in the directory of the user's last export, persisted as the global config key `last_export_dir`. When that key is unset or its directory no longer exists, it falls back to the cross-platform Downloads folder (`platformdirs.user_downloads_dir()`), then to the home directory. The chosen folder is saved after every successful export.

### Theming

The UI uses a two-layer theming architecture:

1. **Base layer**: `qt_material.apply_stylesheet()` applies a Material Design theme (`light_blue.xml` or `dark_blue.xml`) at the `QApplication` level. This handles all standard Qt widgets (buttons, inputs, tabs, checkboxes, progress bars, scroll areas, etc.).

2. **Overlay layer**: `styles.py` contains app-specific QSS overrides applied at the `QMainWindow` level. These use object-name selectors (`#sidebar`, `#collapsibleHeader`, etc.) and property selectors (`QPushButton[secondary="true"]`) to style custom UI components without duplicating base widget rules.

A global `_CursorEventFilter` event filter in `app.py` sets `PointingHandCursor` on interactive controls (`QAbstractButton`, `QComboBox`, `QAbstractSpinBox`, `QTabBar`).

**Theme selection.** The `theme` config key is `"light"`, `"dark"`, or `"system"`
— **`"system"` is the default** (new installs). `ui/_theme.resolve_theme()` is the
single resolver shared by the app and the report: it maps `light`/`dark` to
themselves and resolves `system` to the OS colour scheme via Qt's
`QStyleHints.colorScheme()` (Qt 6.5+), **falling back to `light`** when it can't be
determined (older Qt, no `QApplication`, or an `Unknown` scheme). `system` is also
the hardcoded fallback in every `config.get("theme", "system")` call.
`MainWindow._apply_theme` resolves the configured value to `effective`
(`is_dark`/`theme_xml` derive from it). In `system` mode the app tracks **live** OS
flips: `_watch_system_color_scheme` connects `QStyleHints.colorSchemeChanged` (Qt
6.5+; guarded) to `_on_system_color_scheme_changed`, which re-applies only while the
configured theme is `system`. The settings combo (`settings_panel`) carries the
value as item **data** (`Light`/`Dark`/`System`), so the displayed label is
decoupled from the stored value.

**Report theme (force-light).** The report is independent of the app theme. The
"Always use light theme for report" checkbox in **Step 1 → Report Content**
(`config_panel`, persisted as the profile key `report_force_light`, **default on**)
controls it. `report_panel._on_validated_for_generate` sets
`ReportConfig.dark_mode = app_is_dark and not force_light`, where `app_is_dark`
comes from `resolve_theme(theme)` — so a dark/system app still yields a **light**
PDF unless the user opts out.

### Theme Customization (NFR-05)

The Settings → Appearance section lets the user override the **accent colour** and
**font**, applied to both the app UI and the PDF report and persisted as **global**
config keys (`accent_color`, `font_source`, `font_value`, `font_family`) alongside
`theme`. A "Reset Appearance to Defaults" button clears them.

**Accent.** `core/theming.py` is the single source of accent maths (dependency-free,
unit-tested). It derives every shade from one base hex:

- `qt_shades(accent, dark)` → the overlay tints (`accent`/`soft`/`softer`/`border`).
  `styles.py` is tokenised (`@ACCENT@`/`@SOFT@`/`@SOFTER@`/`@BORDER@`); `light_theme()`/
  `dark_theme()` substitute them. Called with no argument they emit the historical blue
  **byte-for-byte**, so the stock look is unchanged when no accent is set.
- `qt_material_extra(accent, dark)` → `primaryColor`/`primaryLightColor` only, passed to
  `apply_stylesheet(..., extra=…)`. qt-material does `theme.update(extra)` after loading the
  XML, so this overrides the base accent without temp files. The text-colour tokens
  (`primaryTextColor`/`secondaryTextColor`) are left untouched — in qt-material they are the
  main control foreground (dark on light themes, white on dark), so overriding them would
  make text unreadable.
- `report_overrides(accent, dark)` → accent-family hex overrides injected into the Typst
  payload as `theme.colors`; `main.typ` merges them over the base palette via `c.insert`.
  Only accent-tinted entries change — semantic colours stay fixed: progress green/amber/red,
  the purple sprint lane, and the in-progress status badge (a dedicated `info` blue in
  `theme.typ`, not the accent, so a custom accent never recolours it).

**Font.** `services/font_manager.py` provisions fonts into a cache under the config dir:
a chosen **file** is copied in; a **Google Fonts** name is resolved against the upstream
`google/fonts` GitHub repo (contents API across the `ofl`/`apache`/`ufl` license dirs,
preferring the variable-font file) and its TTFs are downloaded. The repo is used because
the Fonts CSS API only serves woff2 for modern variable families (e.g. Manrope), which
Typst cannot read. The resolved family is registered with `QFontDatabase` and prepended to the
qt-material font stack for the UI; for the PDF the cache dir is added to Typst's
`font_paths` and `main.typ` sets `font: (custom, "Inter", "Noto Sans CJK JP")` so
bundled Inter stays the primary fallback (Latin/Cyrillic/Greek, real variable weights)
and bundled **Noto Sans CJK JP** is the last fallback for CJK ideographs/kana/Hangul
that Inter lacks. `report_panel` resolves accent + font onto `ReportConfig`
(`report_accent`/`report_font_family`/`report_font_dir`) just before generation, the same
place `dark_mode` is set.

### Update Notification

`services/update_checker.py` (`UpdateChecker`) queries the GitHub Releases API
(`releases/latest`, which **excludes pre-releases and drafts**) for the project's
latest *full* release and compares its tag with the running `__version__`. There
is **no caching** — the original on-disk cache was dropped because it kept
resurfacing stale data; every check hits GitHub fresh. At ~1 call/launch +
1 call/hour this stays far inside GitHub's unauthenticated 60/hour-per-IP limit.
Tags are normalised (`v1.2.0` → `1.2.0`); `is_newer()` does numeric,
length-tolerant comparison.

`fetch()` is the **single networked call** and the **worker-thread** entry point:
it holds no shared state, carries an explicit connect+read timeout (a missing one
lets a stale socket hang forever), and never raises. It returns one of two
things, and the **distinction matters**:

- a **definitive** `UpdateInfo` — HTTP 200 with a tag, *or* a **404** meaning the
  repo has no published full release (e.g. only pre-releases/drafts), which is
  reported as `update_available=False` (an empty `latest_version`), i.e. "you are
  up to date" — **not** a failure; and
- a **transient** failure (timeout, connection error, 5xx, rate-limit, bad JSON)
  → `None`, which the UI **ignores** (leaving the link as-is) so it never flaps or
  shows wrong data.

Because nothing is persisted, the worker shares no mutable state with the main
thread — complementing the `ThreadedTask` QThread-subclass design that fixed the
earlier GIL ⇄ signal-slot deadlock.

**Store installs disable it.** `services/install_source.py` (`store_source()` /
`is_store_install()`) detects a managed-store install — Mac App Store (a
`Contents/_MASReceipt/receipt` in the `.app`), Microsoft Store/MSIX
(`GetCurrentPackageFullName` package identity, `WindowsApps` path fallback),
Snap (`$SNAP`) or Flatpak (`$FLATPAK_ID` / `/.flatpak-info`). AppImage is
deliberately *not* matched — it is the GH installer. Detection is best-effort
and never raises. When a store is detected, `_setup_update_check` returns early:
no checker, task, timer, network, or link (stores own updates, and self-update
prompts violate their policies). The `_update_checker`/`_update_task`/
`_update_timer` attributes stay `None`, and `_check_for_updates`/`closeEvent`
no-op on them.

`MainWindow._setup_update_check` owns the lifecycle: `_check_for_updates` runs
`fetch` on a `ThreadedTask` worker once at startup — deferred ~3 s
(`_UPDATE_CHECK_STARTUP_DELAY_MS`) so it never competes with the first paint /
session restore — and again hourly via a `QTimer`. The completed
`_on_update_fetched` callback runs on the main thread: a definitive `UpdateInfo`
shows the link (update available) or hides it (up to date / 404), while a
transient `None` is ignored so the link doesn't flap. When an update is available
it reveals a
**blinking accent "Update available" hyperlink** in the sidebar footer, directly
below the version label and at the same font size. It is a `QLabel` rich-text
`<a>` (not a button): the accent colour + underline are set inline in the anchor
(`_render_update_link`, since QSS can't colour an anchor — `_apply_theme` tracks
`self._accent_hex` so the link re-tints with a custom accent), and
`setOpenExternalLinks` opens the latest-release page in the browser on click.
`animations.pulse`/`stop_pulse` loop its opacity slowly (~2.2s) to draw the eye;
the blink starts only on the hidden→shown transition. `#sidebarUpdateLink` holds
only structural rules (font size/alignment) in `COMMON_THEME`. `closeEvent`
stops the timer and joins the worker.

### Window Size Persistence

The main window remembers its last size across launches via the **global**
config keys `window_width`/`window_height` (defaults 1280×900).
`MainWindow.resizeEvent` persists the size on a **debounced** timer
(`_GEOMETRY_SAVE_DEBOUNCE_MS = 400`) so a drag-resize coalesces into one disk
write; only **spontaneous, windowed** resizes are saved (`event.spontaneous()`
and not maximized/fullscreen), so programmatic resizes and screen-filling states
never overwrite the remembered windowed size. `closeEvent` flushes a still-
pending save so the final size survives an immediate close.

`_restore_window_size` runs in `__init__` (before `show()`) and routes the saved
value through `_safe_window_size` — the **safety net** against an unrecoverable
window. It clamps to a lower bound (`_MIN_WINDOW_*`, the `setMinimumSize` floor)
and an upper bound (`QApplication.primaryScreen().availableGeometry()`), and
falls back to `_DEFAULT_WINDOW_*` on a non-numeric value. This prevents a stale
or oversized saved size — e.g. one captured on a large external monitor then
restored on a laptop display — from stranding the title bar and resize handles
off-screen, or shrinking the window below the point where it can be operated.

## Code Standards

- Type hints on all functions; docstrings on public classes and methods
- `QThread` + signals for blocking operations (login, PDF generation)
- OAuth tokens never logged or displayed in plain text
- Exponential backoff for Jira rate limiting (429 responses)
- `RE_EPIC_KEY` regex (in `widgets.py`) is the single source of truth for epic key validation
- Report-item order **is** the row order in `ReportItemTable._rows`. Rows carry a drag handle (`_DragHandle`); dragging starts an internal-move `QDrag`, and `dragMoveEvent` reorders live while `move_row()`/`_reposition()` handle the list mutation. Any reorder emits `items_changed`, which the config panel persists to `last_report_items` (debounced) and the view-model consumes in order — so the on-screen order, the saved order, and the PDF order are always the same
- Charts are drawn natively in Typst components (`layout()` + `place`/`rect`/`line`); the Python view-model supplies geometry (day offsets, nice axes, ticks) so labels never overlap
- Custom/configurable Jira fields read via `_get_raw_field()` (raw JSON dict) rather than the `jira` library's `PropertyHolder` which may drop custom fields

## Security

- OAuth tokens stored in `keyring` only, never in config files
- OAuth `state` parameter validated to prevent CSRF
- Rotating refresh tokens stored immediately after each refresh
- API tokens stored in `keyring`, not config
