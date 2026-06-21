<p align="center">
  <img src="logo.png" alt="Epic Report Generator" width="96">
</p>

<h1 align="center">Epic Report Generator — User Guide</h1>

<p align="center">
  <em>Turn your Jira epics into polished, landscape PDF reports.</em>
</p>

## The Interface

After signing in, the app splits into a **sidebar** and a **work area**.
```
┌──────────────┬─────────────────────────────────────┐
│  Report      │  Step 1 · Configuration             │
│  Settings    │    ↳ choose epics, tune the report  │
│  User Guide  │  Step 2 · Preview & Export          │
│  Logs        │    ↳ view and save the PDF          │
│              │                                     │
│  <Your Name> │                                     │
│  Log out     │                                     │
└──────────────┴─────────────────────────────────────┘
```

| Sidebar | What it's for |
|---------|---------------|
| **Report** | Build, generate, and export your report |
| **Settings** | Connection, appearance, and default values |
| **User Guide** | This guide, available any time inside the app |
| **Logs** | Live activity log (handy if something goes wrong) |

Your name, Jira site, and sign-in method appear at the bottom, along with a **Log out** link.

### Shortcuts

| `Ctrl + G` | `Ctrl + E` | `Ctrl + ,` |
|:---:|:---:|:---:|
| Generate report | Export as PDF | Open Settings |

---

## Build Your Report

The **Report** panel works in two steps. **Step 1 · Configuration** is open by default and holds everything below in collapsible sections. Everything you set **saves automatically**.

### Profiles

The bar at the top lets you keep **separate report setups**, one per project or client, and switch between them instantly.

| Control | Action |
|---------|--------|
| **Dropdown** | Switch profiles; settings load immediately |
| **Save As…** | Copy the current setup into a new named profile |
| **Rename** / **Delete** | Manage profiles (the **Default** profile is permanent) |

### Report items

This is the core of the report: the list of what to include. Add as many rows as you like.

| Type | What to enter | Result |
|------|---------------|--------|
| **Epic** | A Jira epic key (e.g. `PROJ-123`) | The epic and its issues. The name is fetched automatically. |
| **Label** | A Jira label name | **Every** epic carrying that label, grouped together. A display name is optional but recommended; without one, the raw label text is used. |

Drag the handle on the left of any row to **reorder**. The order you see is the order in the PDF.

#### Scope certainty *(optional)*

Each row has a **Cert.** dropdown: `--`, `Low`, `Med`, or `High`, to flag how confident you are in an item's scope. In the report it appears as a 3-segment confidence meter: the more segments filled, the higher the confidence, and the colour reinforces the level (green / amber / red). When any row sets a certainty, a matching legend appears:

| 🟩🟩🟩 High | 🟨🟨 Medium | 🟥 Low |
|:---:|:---:|:---:|

#### Customize a row *(optional)*

Click the **gear** icon on a row to fine-tune its children: the epics under a label, or the stories/tasks under an epic. For each child you can:

| Control | What it does |
|---------|--------------|
| **Display Name** | Rename the child for the report (leave blank to keep its Jira summary) |
| **Include** | On by default; untick to **leave that child out** of the report entirely (it stops counting toward progress and disappears from the timeline) |
| **Cert.** | Set the child's scope certainty (only when the row's own certainty is left at `--`) |
| **drag handle** | Reorder children; the order here is the order in the report |

For a **label**, every child is an epic, so each row also has its own **gear** button: click it to drill in and customize *that epic's* stories/tasks (rename, include/exclude, reorder) using the same controls, one level deeper. Children are always fetched fresh from Jira each time you open the dialog, so the list stays current.

#### Automatic validation

> **Validate** (button in the section header) checks every epic and label against Jira in the background. Problems are outlined on the offending rows and listed in a summary below the table. It also runs automatically when you generate: **errors block** generation, **warnings don't**.

### Title page

Customize the report's cover.

| Field | Default | Notes |
|-------|---------|-------|
| **Report Title** | "Epic Progress Report" | The headline on the cover |
| **Author** | *empty* | Who created the report |
| **Project Name** | *from Jira* | Override the project name |
| **Report Date** | Today | Date printed on the cover |
| **Include confidentiality notice** | Off | Adds a *"CONFIDENTIAL — {Company}"* footer to every page (set the company name alongside it) |

### Estimation & progress

**How issue size is measured:**

| Method | Based on | Unit |
|--------|----------|------|
| **Story Points** *(default)* | A points field on each issue | SP |
| **Time — Days** | The span between an issue's start and due dates | Days |

**How progress is calculated:**

| Method | In plain terms |
|--------|----------------|
| **Combined (Estimates × Issues)** *(default)* | Blends *how much work* is done with *how many issues* are done |
| **Issues Only** | Counts done vs. open issues equally, ignoring size |
| **Estimates Only** | Weighs purely by size; unestimated issues are skipped |

> **Include subtasks into progress calculation** *(on by default)* counts sub-tasks toward each issue's progress, so a parent with 2 of 3 sub-tasks done shows ~67% instead of all-or-nothing.

### Report content

| Option | Default | Adds |
|--------|:---:|------|
| **Show detailed metrics** | On | Cycle time, velocity, scope change, and a completion forecast on each epic's page |
| **Expand label epics** | On | A separate page per epic under a label (instead of one combined page) |

> **Always use light theme for report** *(on by default)* keeps the PDF light even when the app is in dark mode. Turn it off to let a dark app theme carry through to the report.

### Timeline

A Gantt-style timeline page showing when epics start and finish.

| Option | Default | Notes |
|--------|:---:|-------|
| **Include timeline page** | On | Turn the whole page on or off |
| **Show stories/tasks on timeline** | Off | Draw child issues as their own bars |
| **Fixed Start / End Date** | *empty* | Lock the timeline's date range; leave empty to auto-fit |

> Epics still appear even without explicit dates: the app falls back to their children's sprint dates, then their estimation dates. *(Fixed dates must be at least 5 days apart; the app nudges them if not.)*

### Jira field mapping

Most people never touch this. If your Jira uses non-standard custom fields, click **Detect Fields**. The app scans your instance and lets you pick the right fields from dropdowns.

---

## Generate & Export (Save As)

1. Click **Generate Report** (or `Ctrl + G`).
2. The app validates your items, fetches data, and builds the PDF. A progress bar keeps you posted, and the app stays responsive throughout.
3. **Step 2 · Preview & Export** opens with a scrollable, page-by-page preview.
4. Click **Export as PDF** (or `Ctrl + E`) and choose where to save. The app remembers your last folder.

If a few epics can't be fetched, you'll see which ones, and the report is still built from the rest.

**What's in the PDF:**

| Page | Contents |
|------|----------|
| **Cover** | Title, author, date, project |
| **Summary** | Every item with progress bars and key totals |
| **Timeline** | Gantt-style chart *(optional)* |
| **Per epic** | Detail page with a trend chart and metrics |

---

## Application Settings

Open via the sidebar or `Ctrl + ,`.

### Appearance

| Control | What it does |
|---------|--------------|
| **Theme** | Switch between **Light** and **Dark** |
| **Accent Color** | Pick a custom accent for the app *and* the PDF |
| **Font** | Use the default, load a font **From File…**, or pull one from **Google Fonts** by name |

Changes apply right away to both the app and your reports.

### Default values

Pre-fill the **Title**, **Author**, and **Company Name** used for every new report. Click **Save Settings** to keep them.

### Connection & cache

See your current connection details (and OAuth credentials, if you use OAuth). **Invalidate Cache** forces a fresh pull from Jira if data looks stale.

### Log out

Clears your stored tokens and returns to the sign-in screen. Your profiles and defaults are kept.

---

## Tips & Troubleshooting

### Tips

- **Everything auto-saves**, so report settings need no manual save.
- **Use labels** to pull in dozens of epics at once; the summary groups them with combined totals.
- **Use profiles** to keep distinct report templates and switch instantly.
- **Validate before generating** to catch typos early.

### Common issues

| Problem | Try this |
|---------|----------|
| *No data to generate a report* | Confirm the epic keys are correct and the epics have child issues. |
| *Progress shows 0%* | Check your **Estimation Method**, or click **Detect Fields** to find the right fields. |
| *PDF preview is blank* | Use **Export as PDF** and open the file in any PDF viewer. |
| *Lost connection / signed out* | Sign in again from the connection screen. |
