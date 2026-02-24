<p align="center">
  <img src="../src/epic_report_generator/resources/logo.png" alt="Epic Report Generator" width="96">
</p>

<h1 align="center">Epic Report Generator — User Guide</h1>

<p align="center">
  <em>Generate beautiful, landscape PDF reports from your Jira Cloud epics.</em>
</p>

---

## Table of Contents

1. [Getting Started](#1-getting-started)
   - [Installation](#installation)
   - [Launching the App](#launching-the-app)
2. [Connecting to Jira](#2-connecting-to-jira)
   - [Option A — API Token (Recommended)](#option-a--api-token-recommended)
   - [Option B — OAuth 2.0](#option-b--oauth-20)
   - [Session Restore](#session-restore)
3. [The Main Interface](#3-the-main-interface)
   - [Sidebar Navigation](#sidebar-navigation)
   - [Keyboard Shortcuts](#keyboard-shortcuts)
4. [Configuring a Report](#4-configuring-a-report)
   - [Report Items — Epics & Labels](#report-items--epics--labels)
   - [Title Page](#title-page)
   - [Estimation & Progress](#estimation--progress)
   - [Report Content](#report-content)
   - [Timeline Chart](#timeline-chart)
   - [Jira Field Mapping](#jira-field-mapping)
5. [Generating & Exporting](#5-generating--exporting)
   - [Generating a Report](#generating-a-report)
   - [Previewing the PDF](#previewing-the-pdf)
   - [Exporting to PDF](#exporting-to-pdf)
6. [Settings](#6-settings)
   - [Default Values](#default-values)
   - [Theme](#theme)
   - [OAuth Configuration](#oauth-configuration)
   - [Logging Out](#logging-out)
7. [Log Viewer](#7-log-viewer)
8. [Tips & Troubleshooting](#8-tips--troubleshooting)
9. [Keyboard Shortcut Reference](#9-keyboard-shortcut-reference)

---

## 1. Getting Started

### Installation

Install from a wheel or in development mode:

```bash
pip install epic_report_generator          # from a .whl file
# or
pip install -e ".[dev]"                    # development mode
```

Pre-built installers are available for each platform:

| Platform | Installer |
|----------|-----------|
| Windows  | `epic-report-generator-setup.exe` |
| macOS    | `epic-report-generator.dmg` |
| Linux    | `epic-report-generator.AppImage` |

### Launching the App

```bash
python -m epic_report_generator
```

On Linux you can also install a desktop shortcut:

```bash
python -m epic_report_generator --install-desktop
```

The app opens at **1200 x 720 px** with a minimum size of **960 x 600 px**.

---

## 2. Connecting to Jira

When you first launch the app you'll see the **Jira Connection** screen. Two authentication methods are available, shown as tabs.

### Option A — API Token (Recommended)

This is the simplest way to connect. You need three things:

| Field | Example |
|-------|---------|
| **Jira Cloud URL** | `https://company.atlassian.net` |
| **Email** | `you@company.com` |
| **API Token** | *(paste from Atlassian)* |

#### How to create an API Token

1. **Open the API key management portal**
   Go to your Atlassian account settings:
   ```
   https://id.atlassian.com/manage-profile/security/api-tokens
   ```

2. **Choose "Create API key with specific permissions"**
   Click *Create API key*, then select *Create API key with specific permissions* to create a key with only the access this app needs.

3. **Select Jira as the authorized application**
   In the application selection step, choose **Jira** as the product this key will have access to.

4. **Assign the required permissions**
   Enable the following **classic scopes**:
   - `read:jira-work` — read issues, epics, projects, fields, and JQL search
   - `read:jira-user` — read user profiles and assignee information

   Alternatively, if your instance offers **granular scopes**, enable:
   - `read:issue-details:jira`
   - `read:jql:jira`
   - `read:field:jira`
   - `read:project:jira`
   - `read:jira-user`

   > **Note:** Do not grant any write or delete scopes. This app only reads data from Jira.

5. **Copy the API key and paste it below**
   Copy the generated key immediately — you won't be able to see it again. Paste it into the **API Token** field.

Click **Connect**. The status indicator turns green once connected.

---

### Option B — OAuth 2.0

OAuth uses a browser-based consent flow through Atlassian. It requires a one-time setup of OAuth app credentials.

#### One-Time Setup

1. **Create an OAuth 2.0 app** at the [Atlassian Developer Console](https://developer.atlassian.com/console/myapps/).
   Click *Create* → *OAuth 2.0 integration*.

2. **Name it** "Epic Report Generator" and accept the developer terms.

3. **Configure Permissions**
   In the left sidebar click *Permissions*. Find *Jira API* and click *Add*.
   Click *Configure* next to *Jira API*. Under *Jira platform REST API* → *Classic Scopes*, click *Edit Scopes* and enable:
   - `read:jira-work`
   - `read:jira-user`

4. **Set the callback URL**
   In the left sidebar click *Authorization*. Next to *OAuth 2.0 (3LO)* click *Add*. Set the callback URL to:
   ```
   http://localhost:18492/callback
   ```

5. **Copy credentials**
   In the left sidebar click *Settings*. Copy the **Client ID** and **Client Secret**, then paste them into the app.

Click **Save Credentials**, then click **Login with Atlassian**. Your browser will open for you to authorize the app.

---

### Session Restore

The app remembers your last session. On the next launch it will:

- **API Token** — automatically reconnect if the stored token is still valid.
- **OAuth 2.0** — silently refresh the access token using the stored refresh token.

If the token has expired or been revoked, you'll see a message and can re-enter your credentials.

---

## 3. The Main Interface

After logging in, the app switches to a **sidebar + panel** layout.

### Sidebar Navigation

The left sidebar (200 px) contains three navigation buttons:

| Button | Panel | Description |
|--------|-------|-------------|
| **Report** | Report panel | Configure and generate reports |
| **Settings** | Settings panel | Manage connection, defaults, and theme |
| **Logs** | Log panel | View live application logs |

At the bottom of the sidebar you'll see your **user info**:
- Your Jira avatar (or your initial)
- Display name
- Jira site name
- Auth method badge (*API Token* or *OAuth 2.0*)
- **Log out** link

### Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl+G` | Generate report |
| `Ctrl+E` | Export as PDF |
| `Ctrl+,` | Open Settings |

---

## 4. Configuring a Report

The **Report** panel uses a two-step flow:

1. **Step 1: Configuration** — set up what goes into the report
2. **Step 2: Preview & Export** — view and save the generated PDF

Step 1 is expanded by default. It contains several collapsible sections.

---

### Report Items — Epics & Labels

This is the main section where you define what appears in the report. You can add two types of items:

#### Epics

Set the **Type** dropdown to *Epic* and enter a Jira epic key (e.g. `PROJ-123`). The display name is automatically fetched from Jira.

#### Labels

Set the **Type** dropdown to *Label* and enter a Jira label name. All epics tagged with that label will be pulled into the report. A **Display Name** is required for label items.

#### Scope Certainty

Each item has an optional **Cert.** dropdown:
- `--` — no certainty badge
- `Low` / `Med` / `High` — shown as a badge on the PDF timeline

#### Buttons

- **+ Add Row** — add a new row (defaults to Epic)
- **Validate Epics** — checks each epic key against Jira and shows inline results (`✓` valid, `✗` invalid)

---

### Title Page

Customize what appears on the report's cover page:

| Field | Default | Purpose |
|-------|---------|---------|
| **Report Title** | "Epic Progress Report" | Prominent title on the cover |
| **Author** | *(empty)* | Shown as the report creator |
| **Project Name** | *(auto from Jira)* | Overrides the Jira project name |
| **Report Date** | Today | Date printed on the cover |
| **Include confidentiality notice** | Off | Adds a confidentiality statement to the footer |
| **Company Name** | *(empty)* | Referenced in the confidentiality text |

---

### Estimation & Progress

#### Estimation Method

Choose how issue size is measured:

| Method | Description | Unit |
|--------|-------------|------|
| **Story Points** | Reads a numeric field on each issue | SP |
| **Time — Days** | Uses `due_date - start_date` in calendar days | Days |

#### Progress Calculation

| Method | Formula |
|--------|---------|
| **Combined (Estimates x Issues)** | `(completed_estimate / total_estimate) × (closed_issues / total_issues) × 100` |
| **Estimates Only** | `(completed_estimate / total_estimate) × 100` |

Falls back to issue-count ratio when total estimate is zero.

#### Custom Fields

Depending on the estimation method, configure the Jira field IDs:

- **Story Points Field** — default: `story_points`
- **Start Date Field** — default: `startdate`
- **Due Date Field** — default: `duedate`

#### Include Subtasks

When checked (default), the app fetches sub-tasks linked via the `parent` field and includes them in progress calculations. Subtasks are batched in groups of 100 for efficient JQL queries.

---

### Report Content

| Option | Default | Description |
|--------|---------|-------------|
| **Show detailed metrics** | On | Display cycle time, velocity, scope change, and completion forecast on each epic's detail page |
| **Expand label epics** | On | Show a separate detail page for each epic found under a label, instead of a single aggregated page |

---

### Timeline Chart

Configure the Gantt-style timeline that appears in the report:

| Option | Default | Description |
|--------|---------|-------------|
| **Show child issues on timeline** | Off | Display each child issue as a bar alongside epics |
| **Start Date Field** | `startdate` | Jira field for epic timeline start |
| **End Date Field** | `duedate` | Jira field for epic timeline end |
| **Fixed Start Date** | *(empty)* | Lock the timeline x-axis start; leave empty to auto-scale |
| **Fixed End Date** | *(empty)* | Lock the timeline x-axis end; leave empty to auto-scale |

> **Note:** When setting fixed dates, the start must be at least 5 days before the end. The app will auto-correct the other date if this constraint is violated.

---

### Jira Field Mapping

Override the Jira custom field IDs used to fetch data. Most users can leave these at their defaults.

| Field | Default |
|-------|---------|
| **Epic Link Field** | `customfield_10014` |

#### Auto-Detection

Click **Detect Fields** to scan your Jira instance. The app queries available fields and opens a picker dialog where you can select the correct field IDs from dropdowns. This is useful when your Jira instance uses non-standard custom field IDs.

---

## 5. Generating & Exporting

### Generating a Report

1. Configure your report items and options in Step 1.
2. Click **Generate Report** (or press `Ctrl+G`).

The app will:
- Collapse Step 1 and expand Step 2
- Fetch data for each epic/label from Jira (progress shown as a percentage)
- Fetch fix versions
- Build the PDF

Status messages keep you informed:
- *"Fetching PROJ-123…"*
- *"Fetching fix versions…"*
- *"Generating PDF…"*
- *"Report ready — 5 epic(s), 12,345 bytes"*

If some epics fail to fetch, a dialog lists the errors while still showing results for the successful ones.

### Previewing the PDF

Once generated, the PDF is rendered inline as a scrollable page-by-page preview. Pages scale to fit the panel width and are HiDPI-aware.

> **Note:** PDF preview requires the `PySide6-QtPdf` package. If it's not installed, use *Export as PDF* to view the report in an external viewer.

### Exporting to PDF

Click **Export as PDF** (or press `Ctrl+E`). A save dialog opens with a default filename of `epic_report.pdf`. After saving, the status label confirms the export path.

---

## 6. Settings

Navigate to the Settings panel via the sidebar or `Ctrl+,`.

### Default Values

Pre-fill values that are used each time you create a new report:

| Setting | Purpose |
|---------|---------|
| **Default Report Title** | Pre-fills the report title |
| **Default Author Name** | Pre-fills the author field |
| **Default Company Name** | Pre-fills the company name |

Click **Save Settings** to persist.

### Theme

Switch between **Light** and **Dark** themes from the *Appearance* section. The change applies immediately to both the app UI and generated PDF charts.

### OAuth Configuration

If you're using OAuth 2.0, the Settings panel shows your **Client ID**, **Client Secret**, and **Callback Port** (default: `18492`). You can update these here.

### Logging Out

Click **Logout** (red button at the bottom of Settings, or the *Log out* link in the sidebar). You'll be asked to confirm. Logging out:

- Clears stored tokens from the OS keyring
- Returns you to the login screen
- Does **not** delete your configuration or default values

---

## 7. Log Viewer

The **Logs** panel shows a live stream of application events. It's useful for debugging connection issues or understanding what the app is doing.

**Features:**
- **Level filters** — toggle **Debug**, **Info**, **Warning**, and **Error** buttons to show/hide messages by severity
- **Color-coded** — each log level has a distinct color for quick scanning
- **Auto-scroll** — the view scrolls to the bottom as new messages arrive
- **Clear** — wipe the log buffer and start fresh
- Buffers up to **5,000 lines** (oldest lines are removed automatically)

| Level | Color |
|-------|-------|
| Debug | Blue-grey |
| Info | Dark navy / light text |
| Warning | Orange, **bold** |
| Error / Critical | Red, **bold** |

---

## 8. Tips & Troubleshooting

### General Tips

- **All configuration auto-saves.** You don't need to manually save report settings — they persist automatically between sessions.
- **Use Validate Epics** before generating to catch typos in epic keys early.
- **Detect Fields** saves time if your Jira instance uses non-standard custom field IDs.
- **Labels are powerful** — adding a single label can pull in dozens of epics automatically.

### Common Issues

| Problem | Solution |
|---------|----------|
| "Could not connect to Jira" | Double-check your Jira Cloud URL, email, and API token. Make sure the URL includes `https://`. |
| "Token expired or revoked" | Generate a new API token at Atlassian and reconnect. |
| "No data to generate a report" | Verify that your epic keys are correct and that the epics contain child issues. |
| OAuth login times out | Ensure port `18492` is not blocked by a firewall. Check the callback URL in your Atlassian app settings matches `http://localhost:18492/callback`. |
| PDF preview is blank | Install `PySide6-QtPdf` (`pip install PySide6-QtPdf`). Use *Export as PDF* as a workaround. |
| Progress shows 0% unexpectedly | Check your **Estimation Method** and custom field IDs. If issues don't have story points, try *Time — Days* or verify the field ID is correct. Use *Detect Fields* to auto-discover. |
| Subtasks not included | Make sure **Include subtasks** is checked in the *Estimation & Progress* section. |

### Security Notes

- API tokens and OAuth tokens are stored in your **OS keyring** (macOS Keychain, Windows Credential Manager, or Linux Secret Service) — never in plain-text config files.
- The app only requests **read** permissions from Jira. It cannot modify your data.
- OAuth uses a `state` parameter to prevent CSRF attacks and rotating refresh tokens for enhanced security.

---

## 9. Keyboard Shortcut Reference

| Shortcut | Action |
|----------|--------|
| `Ctrl+G` | Generate report |
| `Ctrl+E` | Export as PDF |
| `Ctrl+,` | Open Settings |

---

<p align="center">
  <sub>Epic Report Generator v0.9.1</sub>
</p>
