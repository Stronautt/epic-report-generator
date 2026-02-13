# CLAUDE.md

This file provides guidance to Claude Code when working with this repository.

## Project Overview

**Epic Report Generator** is a PySide6 desktop application that connects to Jira Cloud, fetches Epic progress data, and generates landscape 16:9 PDF reports. It supports two authentication methods: API Token (recommended) and OAuth 2.0 (3LO) via browser redirect.

## Commands

- `pip install -e ".[dev]"` — install in development mode
- `python -m epic_report_generator` — launch the application
- `pytest` — run tests
- `python -m build --wheel` — build pip wheel

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
│   ├── data_models.py             # Dataclasses: JiraIssue, EpicData, EpicMetrics, ReportConfig, ReportData
│   ├── jira_client.py             # JIRA library wrapper, API-token + OAuth connection, pagination, retry
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

### Progress Calculation

```python
progress = (completed_sp / total_sp) * (closed_issues / total_issues) * 100
# Fallback to issue-count ratio when total_sp == 0
# Returns 0 when total_issues == 0; clamped to [0, 100]
```

### PDF Layout

Landscape 16:9 pages (406mm x 228.4mm). Page 1: title page. Page 2+: summary table with progress bars. Pages 3+: per-epic detail with trend chart + metrics sidebar.

## Code Standards

- Type hints on all functions; docstrings on public classes and methods
- `QThread` + signals for blocking operations (login, PDF generation)
- OAuth tokens never logged or displayed in plain text
- Exponential backoff for Jira rate limiting (429 responses)
- `RE_EPIC_KEY` regex (in `widgets.py`) is the single source of truth for epic key validation
- matplotlib backend set to `Agg` before any matplotlib submodule imports

## Security

- OAuth tokens stored in `keyring` only, never in config files
- OAuth `state` parameter validated to prevent CSRF
- Rotating refresh tokens stored immediately after each refresh
- API tokens stored in `keyring`, not config
