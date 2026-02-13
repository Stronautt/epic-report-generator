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
