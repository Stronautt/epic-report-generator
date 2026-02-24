# Epic Report Generator

Generate polished, landscape PDF reports from your Jira Epics — in a few clicks.

Epic Report Generator is a desktop app that connects to Jira Cloud, pulls Epic progress data (story points, issue counts, velocity, cycle time), renders Jira-style trend charts, and produces ready-to-share PDF reports. Hand them to stakeholders, attach them to Confluence, or drop them in Slack — no spreadsheets required.

## What you get

- **Title page** with project name, date, author, and optional confidentiality notice
- **Summary table** — one row per Epic with progress bars, story points, issue counts, and assignees
- **Per-Epic detail pages** — trend chart (total vs. completed SP, cumulative issues, weekend bands) plus a metrics sidebar (velocity, cycle time, scope change %, forecast date)
- **Light & Dark themes** — the PDF and the app UI both follow your preference

## Quick start

### Install from a Release

Go to the [Releases](../../releases) page and download the installer for your platform:

| Platform | File | How to install |
|----------|------|----------------|
| **Windows** | `epic-report-generator-setup.exe` | Run the installer; creates Start Menu and desktop shortcuts |
| **macOS** | `epic-report-generator.dmg` | Open the DMG, drag the app to Applications |
| **Linux** | `epic-report-generator.AppImage` | `chmod +x epic-report-generator.AppImage && ./epic-report-generator.AppImage` |

No Python installation required — the app is fully self-contained.

### Connect to Jira

The app supports two authentication methods:

| Method | Best for | Setup |
|--------|----------|-------|
| **API Token** (recommended) | Most users | Create a token at [id.atlassian.com](https://id.atlassian.com/manage-profile/security/api-tokens), paste it into the app |
| **OAuth 2.0 (3LO)** | Shared/org-wide deployments | Register an app at the [Atlassian Developer Console](https://developer.atlassian.com/console/myapps/), enter Client ID & Secret |

On first launch the app walks you through whichever method you choose.

### Generate a report

1. Switch to the **Report** tab
2. Type your Epic keys (e.g. `PROJ-101`, `PROJ-102`) and press Enter
3. Click **Generate Report** (or `Ctrl+G`)
4. Preview the pages, then **Export as PDF** (or `Ctrl+E`)

## Keyboard shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl+G` | Generate report |
| `Ctrl+E` | Export as PDF |
| `Ctrl+,` | Open settings |

## Development

```bash
git clone https://github.com/stronautt/epic-report-generator.git
cd epic-report-generator

python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

# Run the app
python -m epic_report_generator

# Run tests
pytest

# Build a wheel
python -m build --wheel
```

## Estimation methods

The app supports two ways to measure issue effort:

| Method | When to use | How it works |
|--------|-------------|--------------|
| **Story Points** (default) | Teams that estimate in SP | Reads the Story Points field from each issue |
| **Time — Days** | Teams using Jira Timeline with start/due dates | Calculates `(due_date - start_date)` in calendar days |

Switch between them in **Report → Custom Field Mapping → Estimation Method**. When "Time — Days" is selected, you can configure which Jira fields hold the start and due dates (defaults: `startdate` / `duedate`).

## How the progress formula works

```
progress = (completed_estimate / total_estimate) × (closed_issues / total_issues) × 100
```

- "estimate" is story points or calendar days, depending on the selected estimation method
- If no estimates exist, falls back to issue-count ratio
- If there are no issues, progress is 0 %
- Result is clamped to 0–100 %

## Tech stack

PySide6 · ReportLab · matplotlib · jira · keyring · platformdirs · pandas

## License

MIT
