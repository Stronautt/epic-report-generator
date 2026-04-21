# Epic Report Generator

Generate polished, landscape PDF reports from your Jira Epics — in a few clicks.

Epic Report Generator is a desktop app that connects to Jira Cloud, pulls Epic progress data (story points, issue counts, velocity, cycle time), renders Jira-style trend charts, and produces ready-to-share PDF reports. Hand them to stakeholders, attach them to Confluence, or drop them in Slack — no spreadsheets required.

## What you get

- **Title page** with project name, date, author, and optional confidentiality notice
- **Summary table** — one row per Epic with progress bars, story points, issue counts, and assignees
- **Per-Epic detail pages** — trend chart (total vs. completed SP, cumulative issues, weekend bands) plus a metrics sidebar (velocity, cycle time, scope change %, forecast date)
- **Light & Dark themes** — the PDF and the app UI both follow your preference

## Functional Requirements

- **FR-01. Jira API Integration:** The system must connect to Jira's REST API using user-provided credentials (API Token/Basic Auth) to fetch issue data.
- **FR-02. Configuration (Epics Extraction):** The app must allow users to define Epic keys to specify which issues should be included in the report.
- **FR-03. Report Metadata:** Users must be able to specify report metadata: "Report Title", "Author Name", "Project Display Name, "Report Date".
- **FR-04. Custom Field Mapping:** The system must allow users to specify custom Jira field IDs (e.g., customfield_10106) for "Story Points" and "Epic Link" to ensure compatibility with Jira instances using non-standard field naming.
- **FR-05. Epic-Level Aggregation:** The system must aggregate child issue data (Stories/Tasks) into a high-level "Epic Progress Summary" table, including completion percentages.
- **FR-06. Burndown/Burnup Visualization:** The app must generate time-series charts for each Epic showing Total Story Points, Completed Story Points, Cumulative Issues, and Unestimated Issues over time.
- **FR-07. Velocity Calculation:** The system must calculate a rolling velocity based on the last 4 weeks of work (e.g., "4.0 SP/wk") to drive completion estimates.
- **FR-08. Cycle Time Analysis:** The system must calculate the Average Cycle Time (in days) for issues within a specific Epic.
- **FR-09. Scope Change Tracking:** The app must calculate and report the percentage of Scope Change to indicate how much an Epic's requirements have grown since its inception.
- **FR-10. Predictive Forecasting:** Based on current velocity and remaining story points, the system must generate a Forecast Completion Date for each Epic.
- **FR-11. PDF Report Generation:** The app must compile all tables and charts into a multi-page PDF document.
- **FR-12. Jira Label Aggregation:** The system must aggregate child issue data (Stories/Tasks) into a high-level "Label Progress Summary" table, including completion percentages. There should be the ability to add a custom display name to each label that will appear in the report.

## Non-Functional Requirements

- **NFR-01. Security (Auth):** The application must not store plain-text passwords; it should prefer Jira API Tokens and environment variables for sensitive data.
- **NFR-02. Portability:** The application should be cross-platform (Windows/Mac/Linux).
- **NFR-03. Reliability:** The system must include error handling for API connection failures and provide meaningful logs to the user.

## Quick start

### Install from a Release

1. Go to the [Releases](../../releases) page and download the latest `.whl` file
2. Install it:
   ```bash
   pip install epic_report_generator-*.whl
   ```
3. Launch:
   ```bash
   epic-report-generator
   ```

> **Linux users** — PySide6 needs a few system libraries:
> ```bash
> sudo apt-get install libgl1 libegl1 libxkbcommon0 libxcb-cursor0
> ```

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

### Desktop shortcut

After installing, you can add a launcher entry to your OS app menu:

```bash
epic-report-generator --install-desktop
```

To remove it later:

```bash
epic-report-generator --uninstall-desktop
```

On **Linux** this creates a `.desktop` file in `~/.local/share/applications/` and an icon in `~/.local/share/icons/`. On **macOS** it creates a minimal `.app` bundle in `~/Applications/`. Windows shortcuts are handled by the installer.

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

## How the progress formula works

```
progress = (completed_sp / total_sp) × (closed_issues / total_issues) × 100
```

- If no story points exist, falls back to issue-count ratio
- If there are no issues, progress is 0 %
- Result is clamped to 0–100 %

## Tech stack

PySide6 · ReportLab · matplotlib · jira · keyring · platformdirs · pandas

## License

MIT
