#!/usr/bin/env bash
#
# Inside-out Developer-ID codesigning for "Epic Report Generator.app".
#
# This is the sibling of sign_mas.sh for the *Developer ID* / notarized .dmg
# channel. Both sign inside-out (strip, then sign every nested Mach-O deepest
# first, the app bundle last, no `--deep`), but the Dev-ID build differs from
# the Mac App Store build in two ways:
#   * it enables the **hardened runtime** (`--options runtime`) — a Dev-ID /
#     notarization concept, the opposite of the MAS App Sandbox; and
#   * it stamps the executables with the Dev-ID entitlements
#     (`entitlements.plist`: cs.allow-jit / cs.allow-unsigned-executable-memory),
#     NOT the sandbox/inherit pair.
#
# Why inside-out instead of `codesign --deep`? `--deep` is deprecated ("for
# emergency repairs and ad-hoc testing only" per the codesign man page) and it
# does not strip first, so a stale nested signature can slip into notarization.
# Signing every nested Mach-O ourselves (with our own Team ID) also lets the
# Dev-ID build drop `cs.disable-library-validation`: with all bundled code under
# one Team ID, library validation passes on its own (system frameworks are Apple
# platform binaries, always allowed).
#
# Signing order (deepest first):
#   1. Strip every Mach-O (stripping invalidates any prior signature, so it MUST
#      happen before signing).
#   2. Sign each *.framework as a bundle (respects Versions/Current), deepest
#      framework first.
#   3. Sign loose dylibs / .so / Mach-O bundles outside any framework with the
#      identity + hardened runtime (no entitlements — inert on libraries).
#   4. Sign nested executables with the hardened runtime + Dev-ID entitlements.
#   5. Sign the main executable with the hardened runtime + Dev-ID entitlements.
#   6. Sign the .app bundle last with the hardened runtime + Dev-ID entitlements.
#   7. Verify (`--strict`) and dump the sealed entitlements / signing flags.
#
# When no real identity is supplied (forks / no-secrets CI), it falls back to an
# inside-out **ad-hoc** signature (`-`) with no hardened runtime and no
# entitlements — the inside-out equivalent of the historical
# `codesign --deep --sign -` fallback. The notarize-macos job is gated on the
# signing secrets, so an ad-hoc build is never notarized.
#
# Usage:
#   sign_devid.sh <app-path> [identity] [entitlements]
#
# Or via environment (positional args win):
#   DEVID_APP, MACOS_SIGN_IDENTITY, DEVID_ENTITLEMENTS
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

APP="${1:-${DEVID_APP:-Epic Report Generator.app}}"
IDENTITY="${2:-${MACOS_SIGN_IDENTITY:-}}"
ENTITLEMENTS="${3:-${DEVID_ENTITLEMENTS:-$SCRIPT_DIR/entitlements.plist}}"

die() { echo "::error::$*" >&2; exit 1; }

[ -d "$APP" ] || die "app bundle not found: $APP"

# Ad-hoc fallback when no Developer-ID identity is available (forks / no secrets):
# an ad-hoc signature carries neither a hardened runtime nor entitlements.
ADHOC=0
if [ -z "$IDENTITY" ]; then
  ADHOC=1
  IDENTITY="-"
  echo "::warning::no MACOS_SIGN_IDENTITY — signing inside-out ad-hoc (no hardened runtime, no entitlements); the result is not notarizable"
else
  [ -f "$ENTITLEMENTS" ] || die "entitlements not found: $ENTITLEMENTS"
fi

echo "App:        $APP"
echo "Identity:   $IDENTITY"
[ "$ADHOC" -eq 1 ] || echo "Entitlements: $ENTITLEMENTS"

# Resolve the main executable from Info.plist (falls back to the slug name).
EXEC_NAME="$(plutil -extract CFBundleExecutable raw "$APP/Contents/Info.plist" 2>/dev/null || true)"
[ -n "$EXEC_NAME" ] || EXEC_NAME="epic-report-generator"
MAIN_EXE="$APP/Contents/MacOS/$EXEC_NAME"

is_macho() { file -b "$1" 2>/dev/null | grep -q 'Mach-O'; }

# Libraries/frameworks: hardened runtime, no entitlements (inert on libraries).
sign_lib() {
  if [ "$ADHOC" -eq 1 ]; then
    codesign --force --sign "$IDENTITY" "$1"
  else
    codesign --force --timestamp --options runtime --sign "$IDENTITY" "$1"
  fi
}

# Executables (incl. the main exe) and the app bundle: hardened runtime + the
# Dev-ID entitlements (cs.allow-jit / cs.allow-unsigned-executable-memory).
sign_exe() {
  if [ "$ADHOC" -eq 1 ]; then
    codesign --force --sign "$IDENTITY" "$1"
  else
    codesign --force --timestamp --options runtime \
      --entitlements "$ENTITLEMENTS" --sign "$IDENTITY" "$1"
  fi
}

# ── 1. Strip every Mach-O (invalidates prior signatures) ───────────────
echo "Stripping Mach-O binaries…"
find "$APP/Contents" -type f -print | while IFS= read -r f; do
  is_macho "$f" && strip -x "$f" 2>/dev/null || true
done

# ── 2. Sign frameworks as bundles, deepest first ───────────────────────
echo "Signing frameworks…"
find "$APP" -type d -name '*.framework' -print \
  | awk -F/ '{ print NF, $0 }' | sort -rn | cut -d' ' -f2- \
  | while IFS= read -r fw; do
      [ -n "$fw" ] || continue
      echo "  framework: $fw"
      sign_lib "$fw"
    done

# ── 3/4. Sign loose Mach-O outside frameworks ──────────────────────────
# dylibs / .so / Mach-O bundles → library signing (runtime, no entitlements).
# nested executables → executable signing (runtime + Dev-ID entitlements).
# The main executable is handled separately in step 5 (skipped here).
echo "Signing nested Mach-O…"
find "$APP/Contents" -type f ! -path '*.framework/*' -print | while IFS= read -r f; do
  [ "$f" = "$MAIN_EXE" ] && continue
  is_macho "$f" || continue
  info="$(file -b "$f" 2>/dev/null || true)"
  case "$info" in
    *executable*)
      echo "  exe:  $f"
      sign_exe "$f"
      ;;
    *)
      echo "  lib:  $f"
      sign_lib "$f"
      ;;
  esac
done

# ── 5. Sign the main executable with runtime + entitlements ────────────
if [ -f "$MAIN_EXE" ]; then
  echo "Signing main executable: $MAIN_EXE"
  sign_exe "$MAIN_EXE"
fi

# ── 6. Sign the app bundle last with runtime + entitlements ────────────
echo "Signing app bundle…"
sign_exe "$APP"

# ── 7. Verify ──────────────────────────────────────────────────────────
# `--deep` here is the *verification* form — it recursively validates every
# nested seal, which is the supported use. Only `--deep` *signing* is deprecated.
echo "Verifying signature…"
codesign --verify --deep --strict --verbose=2 "$APP"

echo "Signing details (flags / entitlements):"
codesign -dv --verbose=4 "$APP" 2>&1 || true
codesign -d --entitlements :- "$APP" 2>&1 || echo "::warning::could not read sealed entitlements"

echo "Developer-ID signing complete: $APP"
