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
- **Custom issue-type hierarchy**: per report profile, define which Jira issue types map to the Epic / Story / Sub-task tiers and how they connect (native parent or issue links), with per-type Show/Estimate toggles. Leave it empty for the classic Epic→Story→Sub-task default

## Functional Requirements

- **FR-01. Jira API Integration:** The system must connect to Jira's REST API using user-provided credentials (API Token/Basic Auth) to fetch issue data.
- **FR-02. Configuration (Epics Extraction):** The app must allow users to define Epic keys to specify which issues should be included in the report.
- **FR-03. Report Metadata:** Users must be able to specify report metadata: "Report Title", "Author Name", "Project Display Name", and "Report Date".
- **FR-04. Custom Field Mapping:** The system must allow users to specify custom Jira field IDs (e.g., `customfield_10106`) for "Story Points" and "Epic Link" to ensure compatibility with Jira instances using non-standard field naming.
- **FR-05. Epic-Level Aggregation:** The system must aggregate child issue data (Stories/Tasks) into a high-level "Epic Progress Summary" table, including completion percentages.
- **FR-06. Burndown/Burnup Visualization:** The app must generate time-series charts for each Epic showing Total Story Points, Completed Story Points, Cumulative Issues, and Unestimated Issues over time.
- **FR-07. Velocity Calculation:** The system must calculate a rolling velocity based on the last 4 weeks of work (e.g., "4.0 SP/wk") to drive completion estimates.
- **FR-08. Cycle Time Analysis:** The system must calculate the Average Cycle Time (in days) for issues within a specific Epic.
- **FR-09. Scope Change Tracking:** The app must calculate and report the percentage of Scope Change to indicate how much an Epic's requirements have grown since its inception.
- **FR-10. Predictive Forecasting:** Based on current velocity and remaining story points, the system must generate a Forecast Completion Date for each Epic.
- **FR-11. PDF Report Generation & Styling:** The app must compile all tables and charts into a multi-page PDF document. It must support adding a customizable footer (e.g., `"CONFIDENTIAL — {company}"`) to every page and offer an "Always use light theme for report" option to override dark UI themes during export.
- **FR-12. Jira Label Aggregation & Drill-Down:** The system must aggregate child issue data into a high-level "Label Progress Summary" table. Users must be able to drill down into any report row to view, rename, reorder, or exclude underlying child items (epics in a label, or stories/tasks in an epic), with these adjustments persisting between sessions.
- **FR-13. Scope Certainty:** The system must allow users to set Scope certainty ("Low", "Medium", "High") during configuration. The "Label Certainty" dropdown must include a "Consolidated" option to display an average calculated from underlying child epics. The final report's "Scope Certainty" column must render conditionally, displaying only if at least one certainty value has been configured.
- **FR-14. Interactive Hierarchy Customization:** Users must be able to drag-and-drop rows to manually re-order report items, rename them, or drop undesired items from both high-level lists and deep-dive drill-downs.
- **FR-15. Flexible Issue-Type Mapping:** The system must map complex, multi-tiered Jira hierarchies (e.g., `Capability` → `Feature` → `Story` → `Task` → `Sub-task`) into the report's three standardized display tiers: "Epic", "Story", and "Sub-task". 
- **FR-16. Interactive Chain Configuration:** The system must provide a drag-and-drop interface with drag-handles on each row to allow users to manually reorder the active hierarchy chain.
- **FR-17. Advanced Edge Definition (Parent vs. Link):** For each issue type in the hierarchy, the system must support connecting to the tier above using either:
    * **Parent Relationship:** Jira's native parent/child link.
    * **Link Relationship:** One or more specified issue-link types (matched bidirectionally), displaying a multi-select dropdown for link types only when "Link" is active.
- **FR-18. Granular Display & Estimation Toggles:** Each active row must expose two independent controls:
    * **Show:** Toggles the display of this issue type (summary rows, timeline bars, icons) in the final report.
    * **Estimate:** Dictates whether issues of this type count toward progress percentages, metrics, and estimate weight.
- **FR-19. Cascading Toggle Validation:** Disabling either "Show" or "Estimate" on a parent row must automatically disable and grey out that toggle for all child tiers below it in the chain (ensuring nested children cannot render or be counted if their parent type is ignored).
- **FR-20. Exclude Pool Partitioning:** The UI must feature an "Exclude" pool where users can park unneeded Jira issue types. Parked types must be ignored during data fetching, and users must be able to drag them back into the active chain at any time.
- **FR-21. Zero-Configuration Fallback:** On the first launch, the app must automatically pull configuration data from Jira to construct a default chain. If left unmodified, the system must seamlessly fall back to the standard `Epic` → `Story` → `Sub-task` processing behavior.
- **FR-22. Non-Blocking Live Schema Sync:** The system must provide a "Refresh" capability to fetch updated issue types, link types, and icons from the Jira instance. The sync process must retain existing user-configured hierarchy mappings and, if a previously configured issue/link type no longer exists in Jira, warn the user rather than block app execution.
- **FR-23. In-App Interactive Preview:** The app must render a fully scrollable, window-fitted preview of the generated report so users can read the entire document before exporting.
- **FR-24. Data & Connection Validation:** The app must feature a "Validate" tool to check epics and labels against Jira's API. It must block report generation on critical errors (e.g., missing issues) while flagging warnings for non-critical anomalies.
- **FR-25. Built-In Help & Guidance:** The interface must feature an easily accessible Help panel to assist users with configuration and syntax directly in-app.

## Non-Functional Requirements

-   **NFR-01. Security (Auth):** The application must not store plain-text passwords; it must secure sensitive credentials using Jira API Tokens and system environment variables.
-   **NFR-02. Portability & Distribution:** The application must be cross-platform (Windows, macOS, Linux). macOS builds must support native `.dmg` installation and comply with App Store sandboxing requirements (via TestFlight support).
-   **NFR-03. Reliability & Connection Resilience:** The system must gracefully handle network failures, slow speeds, or dead Jira API connections without crashing or locking up the UI.
-   **NFR-04. Dynamic UI Layout:** The "Epic Progress Summary" page and generated PDFs must dynamically adjust their vertical scaling based on the cumulative height of tables, preventing text clipping or unnatural overflows.
-   **NFR-05. App & Report Theming:** The app must support theme customization (accent color, font loader via file or Google Fonts) persisted between sessions. It must include a default "System" theme that syncs live with the operating system's light/dark settings.
-   **NFR-06. Performance (Non-Blocking UI):** Long-running tasks—such as authenticating with Jira, fetching massive issue datasets, and compiling PDF outputs—must run asynchronously, ensuring the UI remains snappy and responsive.
-   **NFR-07. Multi-Language / CJK Character Support:** The application must correctly render Chinese, Japanese, and Korean (CJK) characters both in the UI screens and in the exported PDF reports.
-   **NFR-08. UX State Persistence:** The application must remember and restore user preferences between sessions, including the window size/position, the last-used export directory, and customized row configurations.
-   **NFR-09. Backward Compatibility:** The system must gracefully handle legacy configuration files (such as migrating old global subtask/timeline checkboxes onto the new three-silo hierarchy model) automatically on first launch without breaking existing setups.

## Quick start

### Install from a Release

Go to the [Releases](../../releases) page and download the installer for your platform:

| Platform | File | How to install |
|----------|------|----------------|
| **Windows** | `epic-report-generator-setup.exe` | Run the installer; creates Start Menu and desktop shortcuts |
| **macOS** | `epic-report-generator.dmg` | Open the DMG, drag the app to Applications |
| **Linux** | `epic-report-generator.AppImage` | `chmod +x epic-report-generator.AppImage && ./epic-report-generator.AppImage` |

No Python installation required. The app is fully self-contained.

#### macOS: two channels

macOS is available two ways:

- **Direct download:** the `epic-report-generator.dmg` above. Supports both
  API-Token and OAuth sign-in.
- **Mac App Store:** a sandboxed build that ships API-Token sign-in only
  (the OAuth tab is hidden). The App Store handles updates.

> **The Mac App Store build is the same app as the free direct download** on the
> [Releases](../../releases) page: same features, same reports, nothing locked
> behind a paywall. The only reason to buy it is to support the work. If you'd
> rather not pay, grab the `.dmg` above and run the same app for free.

The two builds keep separate storage with no migration between them: the Mac App
Store build stores its settings and cache inside its sandbox
container (`~/Library/Containers/com.epicreportgenerator.app/Data/…`), while the
direct download uses `~/Library/Application Support/Epic Report Generator/…`. If
you switch channels, re-enter your Jira URL, email, and API token once.

See the [Privacy Policy](docs/privacy-policy.md) for how your data is handled
(short version: local-first, no developer servers, no analytics).

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

PySide6 · qt-material · Typst (typst-py) · jira · requests · keyring · platformdirs · python-dateutil · markdown

## License

MIT
