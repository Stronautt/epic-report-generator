# Epic Report Generator

Generate landscape PDF reports from your Jira Epics in a few clicks.

Epic Report Generator is a desktop app that connects to Jira Cloud, pulls Epic progress data (story points, issue counts, velocity, cycle time), draws trend charts, and produces PDF reports. Hand them to stakeholders, attach them to Confluence, or drop them in Slack. No spreadsheets required.

## What you get

- **Title page** with the project name, date, author, and an optional confidentiality notice
- **Summary table**: one row per Epic, with progress bars, story points, issue counts, assignees, and an optional scope-certainty legend
- **Timeline page**: a Gantt-style chart of epic (and optionally child-issue) date ranges with milestone markers. On by default; turn it off with the "Include timeline chart" option
- **Per-Epic detail pages**: a trend chart (total vs. completed SP, cumulative issues, weekend bands) and a metrics sidebar (velocity, cycle time, scope change %, forecast date)
- **Light and dark themes** built on Material Design with app-specific overlays. The PDF and the app UI follow the same preference
- **Theme customization**: set a custom accent colour and font (from a file or by Google Fonts name) under Settings → Appearance. The app and the report both update, and a one-click reset restores the defaults

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
- **FR-13. Scope Certainty:** The system must allow users to set Scope certainty as "Low' or "Medium" or "High" for each label and/or epic during the Report configuration ("STEP 1. Configuration").The "Label Certainty" dropdown should include a “Consolidated” option, allowing users to set individual certainty values for each epic associated with the label. While this option is named 'Consolidated' in the configuration settings, the report itself should display 'Low,' 'Medium,' or 'High' based on the average certainty values of the underlying child epics.
- **FR-14. Report Items Re-ordering:** It should be possible to drag the items in the list to change the order in the final report.

## Non-Functional Requirements

- **NFR-01. Security (Auth):** The application must not store plain-text passwords; it should prefer Jira API Tokens and environment variables for sensitive data.
- **NFR-02. Portability:** The application should be cross-platform (Windows/Mac/Linux).
- **NFR-03. Reliability:** The system must include error handling for API connection failures and provide meaningful logs to the user.
- **NFR-04. UI:** The “Epic Progress Summary” should be configured to fit precisely on a single page, with the layout automatically scaling its vertical dimensions based on the cumulative height of the tables
- **NFR-05. UI:** The app and the report must support theme customization — a custom accent colour and a custom font (loaded from a file or by Google Fonts name), applied to both the UI and the generated PDF, persisted between sessions, and resettable to defaults.

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

## How progress works

Progress is computed **bottom-up** through the issue hierarchy:

- **Leaf issues** get 100 % if Done, 0 % otherwise, weighted by their estimate (SP or days)
- **Parent issues** with subtasks aggregate their subtask progress via weighted average
- **Epic progress** is the weighted average of its direct children's progress

Three progress methods are available:

| Method | Formula |
|--------|---------|
| **Combined** (default) | Bottom-up weighted average × (done issues / total issues) |
| **Issues Only** | Bottom-up weighted average with weight = 1.0 for every item |
| **Estimates Only** | Bottom-up weighted average using estimates as weights, without issue-count ratio; unestimated items excluded |

- If there are no issues, progress is 0 %
- Result is clamped to 0–100 %

## Tech stack

PySide6 · qt-material · ReportLab · matplotlib · jira · keyring · platformdirs

## License

MIT
