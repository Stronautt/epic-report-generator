# Mac App Store Submission Guide

Reference checklist for submitting **Epic Report Generator** to the Mac App
Store (MAS). This is the App Store Connect (ASC) side of the work: the in-repo
signing, packaging, and CI pieces are covered by the
[distribution plan](plans/2026-06-20-mac-app-store-distribution.md), and the
feasibility analysis and channel comparison live in the
[research & feasibility doc](mac-app-store-research.md). Fill in the ASC
metadata fields below when creating the app record and the first build's
"Prepare for Submission" page.

> **Signing vs. notarization.** The two macOS channels diverge here. The
> direct-download `.dmg` is **Developer-ID signed and notarized** (`notarytool`
> + staple). The MAS `.pkg` is **Apple-Distribution signed and *not*
> notarized** — App Review replaces notarization, the installer is signed with
> the *Mac Installer Distribution* cert, and the app carries an embedded
> provisioning profile instead of a notarization ticket. See the
> [research doc, §3](mac-app-store-research.md#3-the-build--upload-pipeline-what-changes-vs-today)
> for the full step-by-step diff.

- **Bundle ID:** `com.epicreportgenerator.app` (one ID for both macOS channels).
- **Distribution channel:** Mac App Store, sandboxed, **API-Token sign-in only**
  (the OAuth tab is hidden in store builds). The Developer-ID `.dmg` keeps OAuth.
  - **OAuth re-enablement path (future store update):** OAuth returns by
    swapping the container entitlements to
    `packaging/macos/entitlements.mas.oauth.plist` (the only difference is the
    added `com.apple.security.network.server`, needed for the loopback callback
    server) and un-gating the tab
    (`login_panel` builds it only when `not install_source.is_store_install()`).
    It is a flag-flip plus one entitlement, not a rewrite. See the
    [research doc, §2.2](mac-app-store-research.md#22-oauth-loopback-callback-server--highest-risk-feature).
- **Privacy policy URL:**
  `https://github.com/Stronautt/epic-report-generator/blob/main/docs/privacy-policy.md`
  (swap to the GitHub Pages URL once Pages is enabled). This is the same URL the
  in-app **Help → Privacy Policy** link opens.

## Privacy Nutrition Label

Declare **Data Not Collected** for every category. The App is local-first: it
holds no developer-operated servers, accounts, analytics, or tracking SDKs, and
the developer never receives the user's data.

- **Data used to track you:** none.
- **Data linked to you:** none.
- **Data not linked to you:** none collected by the developer.

Justifying review note (paste into App Review notes alongside the demo account):

> Epic Report Generator is a local-first desktop tool. All Jira credentials and
> fetched issue data flow **only** between the user's device and the user's own
> Jira/Atlassian Cloud site. The developer operates no servers and receives no
> user data. Secrets are stored in the macOS Keychain; non-secret settings live
> in the app's sandbox container. There are no third-party analytics, advertising,
> or crash-reporting services. The automatic GitHub update check is disabled in
> store builds. See the privacy policy URL above.

`ITSAppUsesNonExemptEncryption = false` is set in `Info.plist` (HTTPS-only, so the
build is export-compliance exempt and the per-upload encryption questionnaire is
skipped).

## Account Handling

There is **no developer-operated account system** — the user does not create an
account with us, and we store no user records. The user authenticates directly to
their **own** Jira Cloud site with their own API token.

- **Sign-in:** Jira site URL + email + a Jira API token the user generates in
  their own Atlassian account.
- **Account deletion:** not applicable — there is no developer account to delete.
  The in-app **Logout** clears the stored credentials from the OS keychain, and
  removing the app removes its sandbox container. Note this in the ASC "Account
  Deletion" / sign-in review fields so the "no account deletion path" answer is
  justified.

## Reviewer Demo Account

App Review must be able to exercise the full flow (Guideline 2.1), so supply a
working demo Jira instance in the review notes:

- Spin up a **free Jira Cloud site** with a few sample Epics and child issues.
- Create a **low-privilege user** dedicated to review, generate an **API token**
  for it, and **disable 2FA** on that account (API-token auth does not prompt for
  2FA, but keep it off to avoid friction).
- In the App Review "Sign-In Information" / notes, provide: the Jira **site URL**,
  the reviewer **email**, and the **API token**. Tell the reviewer to choose the
  **API Token** tab, paste the three values, connect, and generate a report.
- Confirm the demo site is reachable and the sample data renders before
  submitting.

### Make the dependency easier — two levels

The hard part of Guideline 2.1 here is that the reviewer cannot evaluate the app
without a working Jira. Two ways to de-risk it, cheapest first:

1. **Ship-now (no code): a stable, dedicated demo site.** Create a *throwaway*
   free Atlassian Cloud site used **only** for review — not a personal/work site.
   Seed one project (`DEMO`) with ~3 Epics, a dozen child issues carrying story
   points and start/due dates, and a couple of labels, so every report surface
   (summary, timeline, per-epic detail) has data. Generate a **long-lived API
   token** on the review user and **disable 2FA** on it. Paste URL + email + token
   into the review notes. Caveats that cause re-review: tokens can be revoked,
   free sites can be deactivated for inactivity, and rate limits / outages all
   read to the reviewer as "app is broken." Re-verify the day you submit.

2. **Durable (small code change), recommended: an offline "Sample data" mode.**
   Add a **"Try with sample data"** button on the login panel that loads bundled
   demo `EpicData`/`ReportData` fixtures and skips the network entirely. The
   reviewer evaluates the full report flow with **no credentials, no external
   site, no token to expire** — which removes the single biggest 2.1 rejection
   cause for credential-gated apps. Seam: `login_panel` already gates UI on
   `install_source.is_store_install()` (see `_oauth_enabled` at
   `login_panel.py:69`); add the demo entry the same way and feed a stub that
   returns bundled fixtures into the existing `JiraClient` → report path instead
   of `connect_basic()`. Bundle the fixtures as package data under
   `resources/`. This also doubles as a first-run "what does a report look like?"
   onboarding for real users.

Best practice is **both**: ship the demo button *and* still put working demo creds
in the notes (belt-and-suspenders), so the reviewer can exercise the live-Jira
path too if they choose.

## App Category

- **Primary:** Productivity (`public.app-category.productivity`, matching
  `LSApplicationCategoryType`).
- **Secondary (optional):** Business.

## Screenshots

macOS App Store screenshots are **landscape**, **RGB**, **no alpha/transparency**
(flatten before upload), PNG or JPEG. ASC requires the image to be *exactly* one
of these pixel sizes — a normal window grab will not match, so capture at a fixed
size (procedure below). Provide 1–10 shots in **one** size; the whole set must use
the same size:

- 1280 × 800
- 1440 × 900
- 2560 × 1600  ← easiest on Retina (capture 1280×800 points)
- 2880 × 1800  ← easiest on Retina (capture 1440×900 points)

Shot list (capture in light *or* dark theme, consistent across the set):

1. **Login** — the API-Token tab with the Jira URL/email/token fields.
2. **Report Items configuration** — Step 1 with Epic/label rows, certainty
   column, and the drag-to-reorder handles.
3. **Report preview** — the in-app PDF preview of a generated report.
4. **Exported PDF page** — a summary or per-epic detail page of an exported PDF.
5. **Settings / Appearance** — theme, accent colour, and font customization.

### How to capture at an exact size

You need a Mac. Install the uploaded build from **TestFlight** (TestFlight.app →
Epic Report Generator → Install) or run the Nuitka `.app` locally. To get real
data into shots 2–4, connect with the **demo Jira** (next section) and generate a
report first.

**Retina trick.** `screencapture -R` takes coordinates in *points*; on a 2× Retina
display the PNG comes out at double the pixels. So a 1440×900-point region →
**2880×1800 px**, and 1280×800 points → **2560×1600 px** — both valid sizes with
no resizing.

1. Move the app window to the **top-left** of the main display and resize its
   content so it is at least 1440×900 points (it must fully cover the capture
   region — anything outside the window captures desktop).
2. Capture the fixed region in Terminal (`-x` mutes the shutter, `-t png`):

   ```sh
   screencapture -R 0,0,1440,900 -t png -x ~/Desktop/shot1.png   # → 2880 × 1800 px
   # or, for the smaller set:
   screencapture -R 0,0,1280,800 -t png -x ~/Desktop/shot1.png   # → 2560 × 1600 px
   ```
3. Verify the pixels: `sips -g pixelWidth -g pixelHeight ~/Desktop/shot1.png`.
4. Repeat for each shot, navigating the app between captures (keep the window in
   the same place/size so every image is identical dimensions).
5. **Flatten alpha** before upload (window content is opaque, but be safe):

   ```sh
   sips -s format jpeg -s formatOptions best ~/Desktop/shot1.png --out ~/Desktop/shot1.jpg
   ```
6. ASC → **My Apps → (app) → macOS App → version → Screenshots**: drag the set in,
   then order them to match the shot list.

**Not on a Retina Mac, or window too small?** Grab the window with
`Cmd+Shift+4` then `Space` (click the window), then in Preview place/scale it onto
a solid-colour canvas sized exactly to one of the sizes above (ASC allows a
background around the window). Flatten and export as in step 5.

## Fresh-Start Migration

The MAS build is a **fresh start** — there is **no migration** of data from the
direct-download `.dmg` build. The two channels keep separate storage:

- The `.dmg` build stores settings under
  `~/Library/Application Support/Epic Report Generator/...`.
- The MAS build is sandboxed; its settings and cached files live in the app's
  sandbox container, `~/Library/Containers/com.epicreportgenerator.app/Data/...`.

Users moving from the `.dmg` to the MAS build re-enter their Jira URL/email/token
once. Document this so it does not read as data loss.

## Submission Checklist

- [ ] App record created in ASC for `com.epicreportgenerator.app` (`fastlane mac
      bootstrap` / `produce`, run locally once).
- [ ] Privacy nutrition label set to **Data Not Collected**, with the review note.
- [ ] Privacy policy URL filled in (link above).
- [ ] Category set to **Productivity**.
- [ ] Screenshots uploaded (one landscape size set, the five shots above).
- [ ] Demo Jira account (URL + email + API token) in the App Review notes.
- [ ] `ITSAppUsesNonExemptEncryption = false` confirmed in the uploaded build.
- [ ] A signed `.pkg` uploaded via `fastlane mac beta` (TestFlight) or `release`,
      and the Sandbox QA Checklist (in the plan) passed on the signed build.
