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
| macOS | `epic-report-generator.dmg` | `create-dmg` from the Nuitka `.app` bundle |
| Linux | `epic-report-generator.AppImage` | `appimagetool` + `packaging/linux/AppDir/` |

Key Nuitka flags used across all platforms:
- `--lto=yes`, `--python-flag=no_docstrings`, `--python-flag=no_asserts`, `--python-flag=isolated`
- `--noinclude-qt-translations`, `--include-qt-plugins=sensible`
- `--include-package-data=epic_report_generator.resources`, `--include-package-data=qt_material`
- `--nofollow-import-to` exclusions for unused stdlib modules and heavy PySide6 modules (WebEngine, 3D, Quick/QML, Multimedia, etc.)

Linux uses `--onedir` (not `--onefile`) because AppImage provides its own single-file SquashFS layer. macOS uses `--macos-create-app-bundle` with the display name `"Epic Report Generator.app"`. Windows uses `--onefile` with `--windows-console-mode=disable` and embeds a `.ico` converted from `logo.png` at build time via Pillow.

Only installer artifacts are uploaded — plain binaries are not retained. The workflow has no release job; GitHub Releases are created manually.

## Tech Stack

- **GUI**: PySide6 (Qt 6)
- **Theming**: `qt-material` (Material Design base themes) + app-specific QSS overlays
- **Jira API**: `jira` library (pycontribs/jira)
- **OAuth**: hand-rolled Atlassian OAuth 2.0 (3LO) over `requests`
- **PDF**: Typst (`typst-py`) — bundled `.typ` templates compiled to PDF
- **Charts**: drawn natively in Typst (Gantt timeline + dual-axis trend chart); no matplotlib
- **Token storage**: `keyring` (OS-native)
- **Config**: `platformdirs` + JSON
- **Dates**: python-dateutil
- **Python**: >=3.11

## Project Structure

```
src/epic_report_generator/
├── __init__.py                    # Package version
├── __main__.py                    # Entry point
├── app.py                         # QApplication setup, signal handlers
├── core/
│   ├── data_models.py             # Dataclasses: JiraIssue (with parent_key, progress, effective_weight), EpicData, EpicMetrics, ReportConfig, ReportData, ReportItem (with child_overrides), ChildOverride, TimelineItem; average_certainty() helper
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
│   └── oauth_server.py            # Local HTTP callback server for OAuth redirect
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
│   │                              #   SidebarUserInfo
│   └── styles.py                  # App-specific QSS overlays on top of qt-material base themes
└── resources/
    ├── typst/                     # Templates: theme, components (gantt, trend_chart, progress_bar, …), pages
    ├── fonts/                     # Bundled Inter (deterministic cross-OS rendering) + Noto Sans CJK JP (CJK fallback)
    ├── user-guide.md              # End-user guide, rendered in-app by help_panel (bundled as package data)
    └── logo.png
```

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
`fetch_child_summaries`). Per child the user can override the **display name** and
**scope certainty**, persisted in `ReportItem.child_overrides`
(`dict[str, ChildOverride]`, keyed by child Jira key) inside `last_report_items`.

Parent vs. child precedence:

- **Parent certainty set** (`Low`/`Med`/`High`) — all children inherit it; the
  per-child certainty selectors in the dialog are disabled.
- **Parent `"--"` (consolidated)** — children may each set their own certainty,
  and the report shows the **average** (`average_certainty()` maps Low/Med/High →
  1/2/3, averages set values, rounds, maps back). This is FR-13's "Consolidated"
  behaviour, triggered by the default `"--"` rather than a separate dropdown entry.

Overrides are applied in `preview_panel._generate_report`: child display names
overwrite `JiraIssue.summary` (epic items) or `EpicData.summary` (label items),
and certainty flows to `EpicMetrics.scope_certainty` per source epic / group.
Switching a row's kind (epic↔label) drops its now-stale child overrides.

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

### Subtask Fetching

When `include_subtasks` is enabled (default `True`), `_fetch_children()` performs a second paginated JQL query (`parent in (CHILD-1, CHILD-2, ...)`) after fetching direct epic children. Subtasks are merged into the children list with key-based deduplication. Child keys are batched in groups of 100 to respect JQL `IN` clause limits. The option is exposed as a checkbox in the Config panel under "Custom Field Mapping" and stored in `ReportConfig.include_subtasks`.

### Timeline Date Computation

Timeline dates determine when epics appear on the Gantt-style timeline chart. Each `EpicData` and `JiraIssue` has separate `timeline_start`/`timeline_end` fields alongside the estimation `start_date`/`due_date`.

Two independent date field pairs are configurable in the Config panel under "Custom Field Mapping":

1. **Estimation dates** (`start_date_field`/`due_date_field`): used for time-based estimation (`time_days` method) and the trend chart time-series. Stored on `ReportConfig` as `start_date_field`/`due_date_field`.

2. **Timeline dates** (`timeline_start_field`/`timeline_end_field`): used for the Gantt chart. Stored on `ReportConfig` as `timeline_start_field`/`timeline_end_field`. Defaults to the estimation fields when not explicitly set.

Epic-level date expansion (`_fill_epic_dates_from_children`) pools dates from the epic itself and all children:

- **Estimation dates**: cascade `start_date`/`due_date` → `created`/`resolved`.
- **Timeline dates**: cascade `timeline_start`/`timeline_end` → sprint start/end dates → `start_date`/`due_date`. The sprint fallback matches Jira Cloud Timeline behaviour, which derives epic ranges from child sprint assignments when no explicit date fields are set.

The same cascade is applied in `merge_metrics()` when building synthetic label-group epics.

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
