# Privacy Policy for Epic Report Generator

**Effective Date:** 2026-06-20

## Overview

Epic Report Generator ("the App") is a desktop application that connects to your
own Jira Cloud site, fetches Epic progress data, and generates PDF reports on
your computer. It is a **local-first tool**: there are no developer-operated
servers, no accounts to create with us, and no analytics or tracking. The only
data the App sends over the network goes to services **you** already use — your
own Jira/Atlassian Cloud — plus optional, clearly described helper downloads.

## Information You Provide

To connect to Jira you enter, depending on the sign-in method you choose:

- **API Token method** — your Jira site URL, your email address, and a Jira API
  token you generate in your own Atlassian account.
- **OAuth 2.0 method** (direct-download builds only) — an OAuth client ID and
  client secret you create in your own Atlassian Developer Console, plus the
  access and rotating refresh tokens the consent flow returns.

You may also configure report settings (Epic keys, field mappings, accent
colour, font, company name). None of this is transmitted to the developer.

## How Your Data Is Used

- Your Jira credentials are used **only** to authenticate to your own Jira/
  Atlassian Cloud and to read the Epic and issue data you ask the App to report
  on.
- The fetched Jira data is used **only** to render your PDF report locally.
- PDF generation runs **entirely on your device**; report content is never
  uploaded anywhere.
- The developer never receives your credentials, your Jira data, or your
  generated reports.

## Data Storage

- **Secrets** (API token, or OAuth client secret and tokens) are stored in your
  operating system's secure keychain (macOS Keychain, Windows Credential
  Manager, or the Linux Secret Service), never in plain-text configuration
  files.
- **Non-secret settings** (your Jira URL, email, and report preferences) are
  stored in a local JSON configuration file in your user profile directory.
- **Generated PDFs** are written only to the location you choose when you export.
- You can clear stored credentials at any time with **Logout**, which removes
  them from the keychain.

## Network Connections

The App makes outbound connections only to:

- **Your own Jira/Atlassian Cloud site** — to authenticate and fetch Epic data.
- **Atlassian authentication endpoints** — only when you use OAuth, to complete
  sign-in and refresh tokens.
- **GitHub Releases** — an automatic update check that runs in the
  direct-download (non-store) builds **only**. It downloads release metadata to
  your device and sends none of your data outward.
- **GitHub / Google Fonts** — only if you opt to download a custom report font;
  this transfers a font file to your device and uploads none of your data.

No connection carries your Jira data or credentials to the developer or to any
third-party analytics, advertising, or tracking service.

## Data Sharing

The App does **not** sell, rent, or share your data with anyone. There are no
third-party analytics SDKs, no advertising, and no crash-reporting services.
Your Jira data flows only between your device and your own Jira instance.

## Mac App Store Builds

The version distributed through the Mac App Store runs inside Apple's App
Sandbox and ships **API-Token sign-in only**; the OAuth tab is hidden. The
automatic GitHub update check is **disabled** in store builds (the store handles
updates). Settings and cached files for the store build live inside the app's
sandbox container (`~/Library/Containers/com.epicreportgenerator.app/Data/...`)
and are not shared with the direct-download build.

## Permissions

The App requests only what its features require:

- **Network access** — for the Jira connections and optional downloads described
  above.
- **Read/write to files you select** — only the export location you pick in the
  save dialog, or a font file you choose to import.

No access to contacts, location, microphone, camera, or other sensitive devices
is requested.

## Children's Privacy

The App is a workplace productivity tool, not directed at children under 13, and
does not knowingly collect information from children.

## Changes to This Policy

If this policy is updated, the new version will be published at the same URL with
a revised effective date.

## Contact

If you have questions about this privacy policy, contact us at:
pavlo.o.hrytsenko@gmail.com
