# Shipping Epic Report Generator to the Mac App Store — Research & Feasibility

> Status: research / decision document. As of June 2026. The app currently ships
> as a **notarized `.dmg`** built with Nuitka (`--macos-create-app-bundle`,
> `--onedir`), signed with Developer ID for *direct distribution*. The Mac App
> Store (MAS) is a **different distribution channel** with a different signing
> chain, mandatory App Sandbox, and a different upload path.

**Related docs:** the decisions here are executed by the
[distribution plan](plans/2026-06-20-mac-app-store-distribution.md), and the
App-Store-Connect-side metadata (privacy nutrition label, demo account,
screenshots, submission checklist) lives in the
[submission guide](mac-app-store-submission.md).

---

## TL;DR — Verdict

**Feasible, but non-trivial.** A Nuitka-compiled PySide6 app *can* ship on the
MAS, but you must clear three hard gates that direct distribution never imposes:

1. **App Sandbox is mandatory** (`com.apple.security.app-sandbox`) on the app and
   *every* nested Mach-O. This is the single biggest risk for a Python/Nuitka app.
2. **The signing chain changes entirely** — MAS uses *Apple Distribution* +
   *Mac Installer Distribution* certs (historically "3rd Party Mac Developer
   Application/Installer"), an embedded **provisioning profile**, and a signed
   `.pkg` — **not** Developer ID, and **not** notarization.
3. **You cannot use `com.apple.security.cs.disable-library-validation`** the way
   you can for Developer ID. Under sandbox/MAS, every bundled `.dylib`/`.so`
   (PySide6, the Typst `.so`, etc.) must be signed **with your Team ID**.

Practical recommendation: **keep the `.dmg`/Developer-ID channel as primary** and
treat MAS as an additional, parallel target. Budget real time for sandbox
debugging (the OAuth loopback server and keyring are the two features most likely
to need rework).

---

## 1. Prerequisites (account / portal)

- **Apple Developer Program** membership ($99/yr) — already required for the
  existing Developer ID notarized build, so this is in place.
- **App Store Connect app record**: register a new app, pick a unique **Bundle ID**
  (e.g. `com.<team>.epicreportgenerator`), primary category, age rating, privacy
  policy URL (required), screenshots, description. A **privacy "nutrition label"**
  is required — declare that the app sends the user's Jira URL/email/token to the
  user's *own* Jira instance and (optionally) GitHub for update checks.
- **Certificates** (created via Xcode "Manage Certificates" or the portal):
  - **Apple Distribution** (a.k.a. *3rd Party Mac Developer Application*) — signs
    the `.app` and all nested code.
  - **Mac Installer Distribution** (a.k.a. *3rd Party Mac Developer Installer*) —
    signs the `.pkg` wrapper that you upload.
- **A MAS provisioning profile** for the bundle ID, downloaded and embedded into
  the bundle as `Contents/embedded.provisionprofile`. The profile must declare any
  capabilities you use (e.g. Keychain Sharing if you go that route).

---

## 2. The hard technical limitations for *this* app

### 2.1 App Sandbox (the main event)

MAS rejects any binary in the bundle that lacks `com.apple.security.app-sandbox = true`.
Concretely:

- The main app gets the **container** entitlements (sandbox + the specific
  resource entitlements below).
- Every **nested** Mach-O (PySide6 frameworks, the bundled Python, `typst`'s
  `.so`, any `.dylib`) must be signed with an **inherit** entitlements file:
  `com.apple.security.app-sandbox = true` **and**
  `com.apple.security.inherit = true`. Nuitka does not do MAS-style nested signing
  for you — the current CI signs for Developer ID, so this is **new signing logic**.

Sandbox side effects to verify in QA:

- **Config / cache paths**: `platformdirs` resolves to
  `~/Library/Application Support/...` and the font cache dir. Under sandbox these
  are silently redirected into the app **container**
  (`~/Library/Containers/<bundleid>/Data/...`). The code uses platformdirs
  everywhere, so it should "just work", but existing users' non-sandboxed config
  will **not** migrate automatically — a fresh MAS install starts empty.
- **No `last_export_dir` free-roam**: the user can still save the PDF anywhere via
  the **save panel** (powered-box / `NSSavePanel`) because that grants a
  user-selected file extension. Direct `open()` outside the container would fail —
  but export already goes through `QFileDialog`, which on a sandboxed app maps to
  the powerbox. Confirm the chosen path is honored.

### 2.2 OAuth loopback callback server — highest-risk feature

`services/oauth_server.py` runs a **local HTTP server** to catch the Atlassian
redirect. Under sandbox you need:

- `com.apple.security.network.client` — to call Jira/Atlassian/GitHub (outbound).
- `com.apple.security.network.server` — to **listen** on a localhost socket for the
  OAuth redirect.

Loopback servers *do* work in the sandbox with `network.server`, but the redirect
flow opens the system browser and bounces back to `http://localhost:<port>` — that
round-trip is allowed, yet it is exactly the kind of thing reviewers probe.
**Mitigation options if it's rejected or flaky:**
- Prefer the **API Token** auth path for MAS (no loopback server needed at all) and
  consider hiding/disabling the OAuth tab for store builds.
- Or switch OAuth to a **custom URL scheme** redirect (register a
  `CFBundleURLTypes` scheme) instead of a loopback server — more work, but
  sandbox-clean and avoids `network.server`.

**Shipped decision (v1) and the documented enablement path.** v1 takes the first
option: the store build is API-Token-only and the OAuth tab is hidden
(`login_panel` builds it only when `not install_source.is_store_install()`), so
the v1 container entitlements (`packaging/macos/entitlements.mas.plist`) carry
**no** `network.server`. OAuth is re-enabled in a later store update by signing
the app with `packaging/macos/entitlements.mas.oauth.plist` instead — its sole
difference from the v1 plist is the added
`com.apple.security.network.server` for the loopback callback — and un-gating the
tab. Keeping the future plist in-tree from the start makes OAuth a documented
flag-flip rather than a rewrite.

### 2.3 Keyring / Keychain

`keyring` uses the macOS Keychain. Under sandbox, Keychain access is scoped to the
app's identity. Two viable setups:

- **Default (simplest)**: rely on the sandbox's automatic per-app keychain access
  — no extra entitlement needed for storing the app's *own* items. Verify that
  `keyring` round-trips the `api_token`/`tokens` items inside the container.
- **If you hit `MissingEntitlement`/`errSecMissingEntitlement`**: add
  `keychain-access-groups = ["$(TeamIdentifierPrefix)<bundleid>"]` and enable
  **Keychain Sharing** on the provisioning profile.

Note the identity caveat: a code-signed bundle's Keychain identity is the
**bundle ID**, which differs from running `python -m ...` in dev — so test keyring
in the **signed, sandboxed** build, not from source.

### 2.4 Library validation — you lose the escape hatch

For Developer ID you *can* set `com.apple.security.cs.disable-library-validation`
to load the Nuitka-bundled dylibs. **MAS strongly discourages / effectively
disallows** the `cs.*` runtime-exception entitlements. The correct fix is to sign
**all** nested libraries with **your** Team ID so library validation passes
natively. Audit the bundle for any third-party `.dylib`/`.so` that arrives
pre-signed by someone else (or unsigned) — those must be **re-signed**. (Your
memory note already flags re-signing the Typst `.so` on macOS — that work extends
to the whole nested tree here.)

### 2.5 Hardened Runtime entitlements that may conflict

Nuitka/CPython sometimes needs `com.apple.security.cs.allow-jit` or
`allow-unsigned-executable-memory`. These are **Hardened Runtime** entitlements;
MAS permits a *narrow* set but scrutinizes them. Try to ship **without** any
`cs.*` entitlement first; add the minimum only if the app crashes at launch, and
be prepared to justify it in App Review notes.

### 2.6 Self-update must stay off (already handled ✅)

`services/install_source.py` detects a Mac App Store install via the
`Contents/_MASReceipt/receipt` file and `_setup_update_check` no-ops. MAS forbids
self-update prompts, so this gating is **already correct** — just make sure the MAS
build genuinely contains a `_MASReceipt` (it will, once installed from the store)
and that QA covers the "no update link" path.

---

## 3. The build → upload pipeline (what changes vs. today)

| Step | Direct (.dmg) today | Mac App Store |
|---|---|---|
| Bundle | Nuitka `--onedir --macos-create-app-bundle` | **Same** `.app`, but `--onefile` is impossible (already onedir on mac ✅) |
| Embedded profile | none | **`embedded.provisionprofile`** copied into `Contents/` |
| Code sign (nested) | Developer ID Application | **Apple Distribution**, every Mach-O, with sandbox **+inherit** entitlements |
| Code sign (app) | Developer ID + Hardened Runtime | **Apple Distribution** + **sandbox** container entitlements (no Developer ID) |
| Wrapper | `.dmg` via create-dmg | **`.pkg`** via `productbuild --component ... --sign "Mac Installer Distribution"` |
| Verify | notarize (`notarytool`) + staple | **No notarization.** Validate/upload to App Store Connect |
| Upload | manual GH release | `xcrun notarytool`/**`altool`/Transporter.app** → App Store Connect → App Review |

Key sequence for the MAS build:

1. Build the `.app` with Nuitka (onedir bundle).
2. Copy the downloaded `embedded.provisionprofile` into `Contents/`.
3. **Sign inside-out**: every nested `.dylib`/`.so`/helper with the *inherit*
   entitlements, then the main executable, then the `.app` with the *container*
   entitlements — all using the **Apple Distribution** identity, `--timestamp`,
   `--options runtime` only if a `cs.*` entitlement forced it.
4. `productbuild --component "Epic Report Generator.app" /Applications \
   --sign "3rd Party Mac Developer Installer: <Team>" output.pkg`.
5. Validate: `xcrun altool --validate-app -f output.pkg -t macos ...` (or
   Transporter.app). Fix `90237`-class signature errors (wrong installer cert) and
   sandbox-entitlement errors here, *before* uploading.
6. Upload: `xcrun altool --upload-app` / `notarytool` / Transporter → submit for
   review in App Store Connect.

### CI implications (GitHub Actions)

- The existing macOS job already does signing/notarization, so the runner has the
  toolchain. Add a **parallel MAS job** (or matrix leg) that:
  - imports the **Apple Distribution** + **Mac Installer Distribution** certs into a
    temp keychain (separate from the Developer ID cert),
  - installs the **provisioning profile**,
  - runs the inside-out signing + `productbuild`,
  - uploads via `altool`/`notarytool` using an **App Store Connect API key**
    (preferred over Apple-ID + app-specific-password for CI).
- Keep this job **decoupled and re-runnable** (mirrors how notarization was split
  out in commit `0f44f4b`) — App Review rejections will make you re-upload often.
- Bundle entitlements (`packaging/macos/`) need **two new plists**: a container
  entitlements file (sandbox + network.client + network.server [+ keychain group])
  and an inherit entitlements file (sandbox + inherit). Remember the AMFI parser
  **rejects XML comments** in entitlements plists (per your prior macOS notes).

---

## 4. Risk ranking & recommendation

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| OAuth loopback server flagged/flaky in sandbox | **High** | Feature loss | Push API-Token auth for MAS; or custom URL-scheme redirect |
| Nested dylib signing / library-validation failures | **High** | Build won't validate | Inside-out sign all Mach-O with Team ID; drop `disable-library-validation` |
| `cs.allow-jit` / unsigned-mem needed by CPython, then questioned by review | Medium | Review delay | Ship without `cs.*` first; add minimal + justify |
| keyring `MissingEntitlement` in container | Medium | Login breaks | Add `keychain-access-groups` + Keychain Sharing |
| Existing users' config not migrating to container | Medium | Support noise | Document fresh-start; optional import helper |
| Fonts/`platformdirs` cache path under container | Low | Cosmetic | Already platformdirs-based ✅ |

**Recommended path:** stand up the MAS build as a *second* artifact in CI, gate
OAuth out (API-Token-only) for the store build to remove the biggest review risk,
and validate locally with Transporter before the first submission. Keep the
notarized `.dmg` as the canonical download.

---

## Sources

- [Configuring the macOS App Sandbox — Apple](https://developer.apple.com/documentation/xcode/configuring-the-macos-app-sandbox)
- [Enable App Sandbox for Submission to App Store — Apple Forums](https://developer.apple.com/forums/thread/743844)
- [Python app on macOS App Store — Apple Forums](https://developer.apple.com/forums/thread/700908)
- [Deploying Python PyInstaller App to Mac App Store — pyinstaller#7123](https://github.com/pyinstaller/pyinstaller/issues/7123)
- [Disable Library Validation Entitlement — Apple](https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.security.cs.disable-library-validation)
- [Keychain Access Groups Entitlement — Apple](https://developer.apple.com/documentation/bundleresources/entitlements/keychain-access-groups)
- [Uploading macOS Builds to App Store Connect — Xojo blog (Jan 2025)](https://blog.xojo.com/2025/01/14/uploading-macos-builds-to-app-store-connect/)
- [Notarizing/signing a pkg for the store — Apple Forums](https://developer.apple.com/forums/thread/122045)
- [App bundle notarization for macOS — Nuitka#2232](https://github.com/Nuitka/Nuitka/issues/2232)
- [Apple Python standalone linking — Nuitka#1260](https://github.com/Nuitka/Nuitka/issues/1260)
- [Common App Sandboxing Issues (QA1773) — Apple](https://developer.apple.com/library/content/qa/qa1773/_index.html)

## Implementation Post-Completion
*External / manual — no checkboxes.*

Apple / ASC setup (one-time, by the user):
- Register the bundle ID; create Apple Distribution + Mac Installer Distribution
  certs; create the Mac App Store provisioning profile.
- Create the ASC app record (in the portal; `fastlane mac bootstrap` is available
  but not used in CI).
- Generate an ASC API key (`.p8`); add CI secrets `APPLE_DIST_P12(_PASSWORD)`,
  `MAC_INSTALLER_P12(_PASSWORD)`, `ASC_KEY_ID`, `ASC_ISSUER_ID`, `ASC_KEY_P8`,
  `MAS_BUNDLE_ID`, `APPLE_TEAM_ID`.

Manual verification (signed sandboxed build):
- Run the full Sandbox QA Checklist on a MAS-signed `.pkg` and a TestFlight build
  (the `_MASReceipt`-dependent "no update link" path needs TestFlight).
- Confirm keyring works in the container; add Keychain Sharing only if it fails.

Submission:
- Provide reviewer demo Jira URL/email/token (2FA off) in App Review notes.
- Supply the primary category, landscape screenshots, the privacy-policy URL, and
  a description; complete the privacy nutrition label from the drafted content.
- Push to TestFlight internal, then submit for App Review (`deliver`
  `submit_for_review: true`).
