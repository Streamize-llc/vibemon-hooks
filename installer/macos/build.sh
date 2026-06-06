#!/usr/bin/env bash
# Build "VibeMon Installer.app" + VibeMon-Installer.dmg.
#
# Universal (arm64 + x86_64), ad-hoc signed — arm64 refuses to execute a
# binary with NO signature at all, so `-s -` is the floor. Real
# Developer ID signing + notarization replaces the `codesign -s -` below
# with the identity and adds `notarytool submit` (see INSTALLER_PLAN.md
# — unsigned was an explicit launch decision, 2026-06-06).
#
# Usage: bash installer/macos/build.sh [out_dir]   (default: dist-installer/)
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
OUT="${1:-$ROOT/dist-installer}"
VERSION="$(tr -d '[:space:]' < "$ROOT/VERSION")"
APP="$OUT/VibeMon Installer.app"

rm -rf "$OUT"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

SDK="$(xcrun --sdk macosx --show-sdk-path)"
for ARCH in arm64 x86_64; do
  swiftc -O -swift-version 5 -parse-as-library \
    -target "$ARCH-apple-macos13.0" -sdk "$SDK" \
    "$HERE/main.swift" -o "$OUT/VibeMonInstaller-$ARCH"
done
lipo -create \
  "$OUT/VibeMonInstaller-arm64" "$OUT/VibeMonInstaller-x86_64" \
  -output "$APP/Contents/MacOS/VibeMonInstaller"
rm "$OUT/VibeMonInstaller-arm64" "$OUT/VibeMonInstaller-x86_64"

sed "s/__VERSION__/$VERSION/g" "$HERE/Info.plist" > "$APP/Contents/Info.plist"
plutil -lint "$APP/Contents/Info.plist" >/dev/null

codesign --force --deep -s - "$APP"
codesign --verify --deep "$APP"

# Headless smoke: --version must print and exit 0 before any UI.
"$APP/Contents/MacOS/VibeMonInstaller" --version

DMG="$OUT/VibeMon-Installer.dmg"
hdiutil create -volname "VibeMon Installer" -srcfolder "$APP" \
  -ov -format UDZO "$DMG" >/dev/null
shasum -a 256 "$DMG" | awk '{print $1"  VibeMon-Installer.dmg"}' > "$DMG.sha256"

echo "built $DMG (v$VERSION, $(du -h "$DMG" | cut -f1 | tr -d ' '))"
