#!/usr/bin/env bash
#
# Wrap a MAS-signed "Epic Report Generator.app" in a signed installer .pkg for
# Mac App Store upload.
#
# The Mac App Store ships a product archive (.pkg), not a .dmg. The package is
# signed with the **Mac Installer Distribution** identity (a.k.a. "3rd Party Mac
# Developer Installer: <Team> (<TeamID>)") — a different certificate from the
# **Apple Distribution** identity that signs the .app itself (see sign_mas.sh).
# Signing the .pkg with the wrong identity is the classic `90237`-class upload
# rejection, so this script ONLY accepts an installer identity.
#
# `productbuild --component <app> /Applications` installs the bundle into
# /Applications (the install location the App Store requires).
#
# After building, an optional `xcrun altool --validate-app` runs when the ASC
# API-key env vars are present (ASC_KEY_ID + ASC_ISSUER_ID). Validation catches
# sandbox/entitlement/installer-cert errors before the (separate) upload step,
# so fix them here, not after a failed App Review upload. Without the creds the
# validation is skipped (the .pkg is still produced).
#
# Usage:
#   build_pkg.sh <app-path> <installer-identity> [output-pkg]
#
# Or via environment (positional args win):
#   MAS_APP, MAC_INSTALLER_IDENTITY, MAS_PKG_PATH
#   ASC_KEY_ID, ASC_ISSUER_ID  (optional; enable --validate-app)
#
set -euo pipefail

APP="${1:-${MAS_APP:-Epic Report Generator.app}}"
INSTALLER_IDENTITY="${2:-${MAC_INSTALLER_IDENTITY:-}}"
PKG="${3:-${MAS_PKG_PATH:-epic-report-generator-mas.pkg}}"

die() { echo "::error::$*" >&2; exit 1; }

[ -n "$INSTALLER_IDENTITY" ] \
  || die "no installer identity (arg 2 or MAC_INSTALLER_IDENTITY); expected a '3rd Party Mac Developer Installer' identity"
[ -d "$APP" ] || die "app bundle not found: $APP"

echo "App:        $APP"
echo "Installer:  $INSTALLER_IDENTITY"
echo "Output:     $PKG"

# ── Build the signed product archive ───────────────────────────────────
# --component <app> /Applications installs the bundle into /Applications,
# the location the Mac App Store mandates.
echo "Building installer package…"
productbuild \
  --component "$APP" /Applications \
  --sign "$INSTALLER_IDENTITY" \
  "$PKG"

[ -f "$PKG" ] || die "productbuild did not produce: $PKG"
echo "Built: $PKG"

# ── Optional validation against App Store Connect ──────────────────────
# Gated on ASC creds so local builds without keys still produce the .pkg.
if [ -n "${ASC_KEY_ID:-}" ] && [ -n "${ASC_ISSUER_ID:-}" ]; then
  echo "Validating package with App Store Connect…"
  xcrun altool --validate-app \
    -f "$PKG" \
    -t macos \
    --apiKey "$ASC_KEY_ID" \
    --apiIssuer "$ASC_ISSUER_ID"
  echo "Validation passed: $PKG"
else
  echo "ASC API key not set (ASC_KEY_ID/ASC_ISSUER_ID); skipping --validate-app."
fi

echo "Package build complete: $PKG"
