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
- **OAuth**: `requests_oauthlib` for Atlassian OAuth 2.0 (3LO)
- **PDF**: ReportLab
- **Charts**: matplotlib with `Agg` backend
- **Data**: pandas
- **Token storage**: `keyring` (OS-native)
- **Config**: `platformdirs` + JSON
- **Dates**: python-dateutil
- **Python**: >=3.10

## Project Structure

```
src/epic_report_generator/
├── __init__.py                    # Package version
├── __main__.py                    # Entry point
├── app.py                         # QApplication setup, signal handlers
├── core/
│   ├── data_models.py             # Dataclasses: JiraIssue (with parent_key, progress, effective_weight), EpicData, EpicMetrics, ReportConfig, ReportData, TimelineItem
│   ├── jira_client.py             # JIRA library wrapper, API-token + OAuth connection, pagination, retry, date expansion
│   ├── metrics.py                 # Bottom-up hierarchical progress, velocity, cycle time, scope change, forecasting, time-series
│   ├── chart_generator.py         # Matplotlib Jira-style trend charts (light/dark)
│   └── pdf_generator.py           # ReportLab PDF builder (title, summary table, epic detail pages)
├── services/
│   ├── auth_manager.py            # OAuth 2.0 (3LO) flow + API-token auth + keyring token storage
│   ├── config_manager.py          # JSON config via platformdirs
│   └── oauth_server.py            # Local HTTP callback server for OAuth redirect
├── ui/
│   ├── main_window.py             # Login overlay → sidebar/stacked-panel layout
│   ├── login_panel.py             # Dual-auth login: API Token tab + OAuth tab, session restore
│   ├── config_panel.py            # Epic keys (tag input), metadata, field mapping
│   ├── report_panel.py            # Two-step flow: configuration + preview (collapsible sections)
│   ├── preview_panel.py           # PDF generation worker, QPdfDocument preview, export
│   ├── settings_panel.py          # Connection info, theme toggle, logout, defaults
│   ├── log_panel.py               # Live log viewer with level filtering
│   ├── widgets.py                 # Reusable: StatusIndicator, LabelledField, GuideStep, FlowLayout,
│   │                              #   CollapsibleSection, EpicKeyTagInput, SidebarUserInfo
│   └── styles.py                  # App-specific QSS overlays on top of qt-material base themes
└── resources/
    ├── fonts/
    └── icons/
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

Landscape 16:9 pages (406mm x 228.4mm). Page 1: title page. Page 2: summary table with progress bars (label-group header rows show aggregated statistics) and optional scope-certainty legend. Page 3: Gantt-style timeline chart with optional scope-certainty legend. Pages 4+: per-epic detail with trend chart + metrics sidebar.

When `confidential` is enabled and `company_name` is set, a repeating footer appears on all pages except the title page: "CONFIDENTIAL — {company_name}" on the left, report date and author on the right.

### Theming

The UI uses a two-layer theming architecture:

1. **Base layer**: `qt_material.apply_stylesheet()` applies a Material Design theme (`light_blue.xml` or `dark_blue.xml`) at the `QApplication` level. This handles all standard Qt widgets (buttons, inputs, tabs, checkboxes, progress bars, scroll areas, etc.).

2. **Overlay layer**: `styles.py` contains app-specific QSS overrides applied at the `QMainWindow` level. These use object-name selectors (`#sidebar`, `#collapsibleHeader`, etc.) and property selectors (`QPushButton[secondary="true"]`) to style custom UI components without duplicating base widget rules.

A global `_JsonCursorFilter` event filter in `app.py` sets `PointingHandCursor` on interactive controls (`QAbstractButton`, `QComboBox`, `QAbstractSpinBox`, `QTabBar`, `QGroupBox`).

## Code Standards

- Type hints on all functions; docstrings on public classes and methods
- `QThread` + signals for blocking operations (login, PDF generation)
- OAuth tokens never logged or displayed in plain text
- Exponential backoff for Jira rate limiting (429 responses)
- `RE_EPIC_KEY` regex (in `widgets.py`) is the single source of truth for epic key validation
- matplotlib backend set to `Agg` before any matplotlib submodule imports
- Custom/configurable Jira fields read via `_get_raw_field()` (raw JSON dict) rather than the `jira` library's `PropertyHolder` which may drop custom fields

## Security

- OAuth tokens stored in `keyring` only, never in config files
- OAuth `state` parameter validated to prevent CSRF
- Rotating refresh tokens stored immediately after each refresh
- API tokens stored in `keyring`, not config
