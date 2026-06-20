#!/usr/bin/env bash
#
# Inside-out Mac App Store codesigning for "Epic Report Generator.app".
#
# Unlike the Developer ID path (sign_devid.sh — inside-out signing with the
# hardened runtime and cs.* entitlement exceptions), the Mac App Store requires:
#   * the App Sandbox (no hardened runtime — that is a Dev-ID concept);
#   * every nested Mach-O signed individually, deepest first ("inside-out"),
#     each with our own Team ID so library validation passes WITHOUT
#     `disable-library-validation`;
#   * NO `--deep` signing (it would stamp nested code with the container's
#     entitlements — wrong; nested code gets the `inherit` entitlements).
#
# Signing order (deepest first):
#   1. Embed the provisioning profile (if supplied) at Contents/.
#   2. Strip every Mach-O (stripping invalidates any prior signature, so it
#      MUST happen before signing).
#   3. Sign each *.framework as a bundle (respects Versions/Current), deepest
#      framework first.
#   4. Sign loose dylibs / .so / Mach-O bundles outside any framework with the
#      identity only.
#   5. Sign nested executables with the inherit entitlements.
#   6. Sign the main executable with the inherit entitlements.
#   7. Sign the .app bundle last with the container entitlements.
#   8. Verify (`--strict`) and dump the sealed entitlements.
#
# Usage:
#   sign_mas.sh <app-path> <identity> [container-entitlements] \
#               [inherit-entitlements] [provision-profile]
#
# Or via environment (positional args win):
#   MAS_APP, APPLE_DIST_IDENTITY, MAS_ENTITLEMENTS, MAS_INHERIT_ENTITLEMENTS,
#   MAS_PROFILE
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

APP="${1:-${MAS_APP:-Epic Report Generator.app}}"
IDENTITY="${2:-${APPLE_DIST_IDENTITY:-}}"
ENTITLEMENTS="${3:-${MAS_ENTITLEMENTS:-$SCRIPT_DIR/entitlements.mas.plist}}"
INHERIT_ENTITLEMENTS="${4:-${MAS_INHERIT_ENTITLEMENTS:-$SCRIPT_DIR/entitlements.mas.inherit.plist}}"
PROFILE="${5:-${MAS_PROFILE:-}}"

die() { echo "::error::$*" >&2; exit 1; }

[ -n "$IDENTITY" ] || die "no signing identity (arg 2 or APPLE_DIST_IDENTITY); expected an 'Apple Distribution' identity"
[ -d "$APP" ] || die "app bundle not found: $APP"
[ -f "$ENTITLEMENTS" ] || die "container entitlements not found: $ENTITLEMENTS"
[ -f "$INHERIT_ENTITLEMENTS" ] || die "inherit entitlements not found: $INHERIT_ENTITLEMENTS"

echo "App:        $APP"
echo "Identity:   $IDENTITY"
echo "Container:  $ENTITLEMENTS"
echo "Inherit:    $INHERIT_ENTITLEMENTS"

# Resolve the main executable from Info.plist (falls back to the slug name).
EXEC_NAME="$(plutil -extract CFBundleExecutable raw "$APP/Contents/Info.plist" 2>/dev/null || true)"
[ -n "$EXEC_NAME" ] || EXEC_NAME="epic-report-generator"
MAIN_EXE="$APP/Contents/MacOS/$EXEC_NAME"

is_macho() { file -b "$1" 2>/dev/null | grep -q 'Mach-O'; }

# ── 1. Embed the provisioning profile ──────────────────────────────────
if [ -n "$PROFILE" ]; then
  [ -f "$PROFILE" ] || die "provisioning profile not found: $PROFILE"
  echo "Embedding provisioning profile → Contents/embedded.provisionprofile"
  cp "$PROFILE" "$APP/Contents/embedded.provisionprofile"
else
  echo "::warning::no provisioning profile (arg 5 or MAS_PROFILE); the signed .app will have no embedded.provisionprofile and the resulting .pkg cannot be installed or accepted by App Review"
fi

# ── 1b. Inject the application-identifier into the container entitlements ─
# The Mac App Store signature must embed com.apple.application-identifier
# matching the provisioning profile, or TestFlight rejects the build
# (ITMS-90886). Xcode injects this automatically; plain codesign does not, so
# add it here. Prefer the exact value from the embedded profile (guaranteed to
# match); fall back to $APPLE_TEAM_ID + the bundle id. The augmented file is
# reused for the final app-bundle signing (step 7).
BUNDLE_ID="$(plutil -extract CFBundleIdentifier raw "$APP/Contents/Info.plist" 2>/dev/null || true)"
APP_IDENTIFIER=""
if [ -n "$PROFILE" ] && [ -f "$PROFILE" ]; then
  PROFILE_PLIST="$(mktemp)"
  if security cms -D -i "$PROFILE" >"$PROFILE_PLIST" 2>/dev/null; then
    APP_IDENTIFIER="$(/usr/libexec/PlistBuddy -c 'Print :Entitlements:com.apple.application-identifier' "$PROFILE_PLIST" 2>/dev/null \
      || /usr/libexec/PlistBuddy -c 'Print :Entitlements:application-identifier' "$PROFILE_PLIST" 2>/dev/null || true)"
  fi
  rm -f "$PROFILE_PLIST"
fi
if [ -z "$APP_IDENTIFIER" ] && [ -n "${APPLE_TEAM_ID:-}" ] && [ -n "$BUNDLE_ID" ]; then
  APP_IDENTIFIER="$APPLE_TEAM_ID.$BUNDLE_ID"
fi

if [ -n "$APP_IDENTIFIER" ]; then
  TEAM_IDENTIFIER="${APP_IDENTIFIER%%.*}"
  AUGMENTED_ENT="$(mktemp "${TMPDIR:-/tmp}/mas_entitlements.XXXXXX")"
  cp "$ENTITLEMENTS" "$AUGMENTED_ENT"
  /usr/libexec/PlistBuddy -c "Delete :com.apple.application-identifier" "$AUGMENTED_ENT" 2>/dev/null || true
  /usr/libexec/PlistBuddy -c "Add :com.apple.application-identifier string $APP_IDENTIFIER" "$AUGMENTED_ENT"
  /usr/libexec/PlistBuddy -c "Delete :com.apple.developer.team-identifier" "$AUGMENTED_ENT" 2>/dev/null || true
  /usr/libexec/PlistBuddy -c "Add :com.apple.developer.team-identifier string $TEAM_IDENTIFIER" "$AUGMENTED_ENT"
  ENTITLEMENTS="$AUGMENTED_ENT"
  echo "Container entitlements: application-identifier=$APP_IDENTIFIER team-identifier=$TEAM_IDENTIFIER"
else
  echo "::warning::no application-identifier (no profile entitlement and no APPLE_TEAM_ID); the signature will omit it and TestFlight will reject the build (ITMS-90886)"
fi

# ── 2. Strip every Mach-O (invalidates prior signatures) ───────────────
echo "Stripping Mach-O binaries…"
find "$APP/Contents" -type f -print | while IFS= read -r f; do
  is_macho "$f" && strip -x "$f" 2>/dev/null || true
done

# ── 3. Sign frameworks as bundles, deepest first ───────────────────────
echo "Signing frameworks…"
find "$APP" -type d -name '*.framework' -print \
  | awk -F/ '{ print NF, $0 }' | sort -rn | cut -d' ' -f2- \
  | while IFS= read -r fw; do
      [ -n "$fw" ] || continue
      echo "  framework: $fw"
      codesign --force --timestamp --sign "$IDENTITY" "$fw"
    done

# ── 4/5. Sign loose Mach-O outside frameworks ──────────────────────────
# dylibs / .so / Mach-O bundles → identity only.
# nested executables → inherit entitlements.
# The main executable is handled separately in step 6 (skipped here).
echo "Signing nested Mach-O…"
find "$APP/Contents" -type f ! -path '*.framework/*' -print | while IFS= read -r f; do
  [ "$f" = "$MAIN_EXE" ] && continue
  is_macho "$f" || continue
  info="$(file -b "$f" 2>/dev/null || true)"
  case "$info" in
    *executable*)
      echo "  exe:  $f"
      codesign --force --timestamp --sign "$IDENTITY" \
        --entitlements "$INHERIT_ENTITLEMENTS" "$f"
      ;;
    *)
      echo "  lib:  $f"
      codesign --force --timestamp --sign "$IDENTITY" "$f"
      ;;
  esac
done

# ── 6. Sign the main executable with inherit entitlements ──────────────
if [ -f "$MAIN_EXE" ]; then
  echo "Signing main executable: $MAIN_EXE"
  codesign --force --timestamp --sign "$IDENTITY" \
    --entitlements "$INHERIT_ENTITLEMENTS" "$MAIN_EXE"
fi

# ── 7. Sign the app bundle last with the container entitlements ────────
echo "Signing app bundle…"
codesign --force --timestamp --sign "$IDENTITY" \
  --entitlements "$ENTITLEMENTS" "$APP"

# ── 8. Verify ──────────────────────────────────────────────────────────
echo "Verifying signature…"
codesign --verify --strict --verbose=2 "$APP"

echo "Sealed entitlements:"
codesign -d --entitlements :- "$APP" 2>/dev/null || codesign -dv --entitlements - "$APP" 2>&1 || true

echo "MAS signing complete: $APP"
