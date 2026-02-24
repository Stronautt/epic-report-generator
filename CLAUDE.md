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
- `--nofollow-import-to` exclusions for unused stdlib modules and heavy PySide6 modules (WebEngine, 3D, Quick/QML, Multimedia, etc.)

Linux uses `--onedir` (not `--onefile`) because AppImage provides its own single-file SquashFS layer. macOS uses `--macos-create-app-bundle` instead of `--onefile`. Windows uses `--onefile` and embeds a `.ico` converted from `logo.png` at build time via Pillow.

Only installer artifacts are uploaded — plain binaries are not retained. The workflow has no release job; GitHub Releases are created manually.

## Tech Stack

- **GUI**: PySide6 (Qt 6)
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
│   ├── data_models.py             # Dataclasses: JiraIssue, EpicData, EpicMetrics, ReportConfig, ReportData, TimelineItem
│   ├── jira_client.py             # JIRA library wrapper, API-token + OAuth connection, pagination, retry, date expansion
│   ├── metrics.py                 # Progress, velocity, cycle time, scope change, forecasting, time-series
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
│   └── styles.py                  # QSS stylesheets (light/dark themes)
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

```python
progress = (completed_estimate / total_estimate) * (closed_issues / total_issues) * 100
# "estimate" = story points or calendar days depending on estimation_method
# Fallback to issue-count ratio when total_estimate == 0
# Returns 0 when total_issues == 0; clamped to [0, 100]
```

### PDF Layout

Landscape 16:9 pages (406mm x 228.4mm). Page 1: title page. Page 2: summary table with progress bars (label-group header rows show aggregated statistics). Page 3: Gantt-style timeline chart. Pages 4+: per-epic detail with trend chart + metrics sidebar.

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
