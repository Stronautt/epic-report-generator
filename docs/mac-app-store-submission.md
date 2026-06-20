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

## App Category

- **Primary:** Productivity (`public.app-category.productivity`, matching
  `LSApplicationCategoryType`).
- **Secondary (optional):** Business.

## Screenshots

macOS App Store screenshots are **landscape**. Provide at least one set in a
supported size:

- 1280 × 800
- 1440 × 900
- 2560 × 1600
- 2880 × 1800

Shot list (capture in light or dark theme, consistent across the set):

1. **Login** — the API-Token tab with the Jira URL/email/token fields.
2. **Report Items configuration** — Step 1 with Epic/label rows, certainty
   column, and the drag-to-reorder handles.
3. **Report preview** — the in-app PDF preview of a generated report.
4. **Exported PDF page** — a summary or per-epic detail page of an exported PDF.
5. **Settings / Appearance** — theme, accent colour, and font customization.

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
