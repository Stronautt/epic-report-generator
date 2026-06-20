# fastlane — Mac App Store distribution

This directory configures [fastlane](https://fastlane.tools) for App Store
Connect (ASC) provisioning and upload of the **Mac App Store** channel. The
existing Developer-ID `.dmg` channel does **not** use fastlane.

There is **no Matchfile** (signing is manual) and **no `gym`** (Nuitka builds the
`.app`; the CI shell steps and `packaging/macos/sign_mas.sh` sign it). fastlane
only creates the ASC record, fetches the Mac App Store provisioning profile, and
uploads the already-built MAS `.pkg`.

## Lanes

| Lane | Where | Purpose |
|---|---|---|
| `bootstrap` | **local, once** | `produce` — create the ASC app record. Needs interactive Apple-ID / ASC access, so it is **not** run in CI. |
| `profile` | CI / local | `sigh` — fetch/refresh the Mac App Store provisioning profile (manual signing). |
| `beta` | CI / local | `pilot` — upload the MAS-signed `.pkg` to TestFlight (internal testing). |
| `release` | CI / local | `deliver` — upload the `.pkg` for App Review (submission gated behind `submit_for_review`). |

## Environment variables

| Variable | Used by | Notes |
|---|---|---|
| `MAS_BUNDLE_ID` | all lanes | `com.epicreportgenerator.app`. |
| `FASTLANE_APPLE_ID` | `bootstrap` | Apple-ID email; only the local `produce` run needs it. |
| `APPLE_TEAM_ID` | all lanes | Developer Team ID. |
| `ASC_KEY_ID` | `profile`/`beta`/`release` | ASC API key ID. |
| `ASC_ISSUER_ID` | `profile`/`beta`/`release` | ASC API issuer ID. |
| `ASC_KEY_P8` | `profile`/`beta`/`release` | ASC API `.p8`, **base64-encoded** (decoded by fastlane). |
| `MAS_PKG_PATH` | `beta`/`release` | Path to the built `epic-report-generator-mas.pkg`. |

## First-time setup (local)

`bootstrap` runs **locally once** to create the ASC app record. It needs an
interactive Apple-ID / App-Store-Connect login, so it is deliberately kept out of
CI:

```sh
bundle install
MAS_BUNDLE_ID=com.epicreportgenerator.app \
FASTLANE_APPLE_ID=you@example.com \
APPLE_TEAM_ID=XXXXXXXXXX \
  bundle exec fastlane mac bootstrap
```

After that, CI uses `profile`, `beta`, and `release` with the ASC API key only —
no Apple-ID password and no 2FA in CI.
