#!/bin/bash
# ═══════════════════════════════════════════════════════════
#  S1 Command Center — macOS Build Script
#  Creates a standalone .app bundle and .dmg installer
# ═══════════════════════════════════════════════════════════
set -e

APP_NAME="S1 Command Center"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "═══════════════════════════════════════════════════"
echo "  Building ${APP_NAME} for macOS"
echo "═══════════════════════════════════════════════════"

# ── Reproducible build: same code = same hash every time ──
export SOURCE_DATE_EPOCH=1750000000
export PYTHONHASHSEED=0

# ensure venv
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi
source venv/bin/activate

# install deps
echo "Installing dependencies..."
pip install -q -r requirements.txt
pip install -q pyinstaller

# clean previous builds
rm -rf build dist

# build
echo "Building application..."
pyinstaller \
    --name "S1 Command Center" \
    --windowed \
    --onedir \
    --icon s1cc.ico \
    --add-data "s1cc.ico:." \
    --add-data "export_utils.py:." \
    --hidden-import customtkinter \
    --hidden-import openpyxl \
    --hidden-import PIL \
    --collect-all customtkinter \
    --collect-all keyring \
    --hidden-import keyring.backends.macOS \
    --exclude-module jira_page \
    --noconfirm \
    main.py

# remove quarantine flag on build machine
echo "Removing quarantine flags..."
xattr -cr "dist/S1 Command Center.app"

# create DMG staging folder with app + installer script
echo "Preparing DMG contents..."
DMG_STAGE="dist/dmg_stage"
rm -rf "$DMG_STAGE"
mkdir -p "$DMG_STAGE"
cp -R "dist/S1 Command Center.app" "$DMG_STAGE/"

# Copy the installer script + README from the canonical source files.
# Keeping them in installer/ on disk means both this script and CI get
# byte-for-byte identical contents — important so macOS's content-hash
# Gatekeeper approval ("Open Anyway") stays valid across rebuilds.
cp "installer/Install & Launch.command" "$DMG_STAGE/Install & Launch.command"
chmod +x "$DMG_STAGE/Install & Launch.command"
cp "installer/README.txt" "$DMG_STAGE/README.txt"

# create DMG
echo "Creating DMG installer..."
hdiutil create -volname "S1 Command Center" \
    -srcfolder "$DMG_STAGE" \
    -ov -format UDZO "dist/S1-Command-Center.dmg"

# remove quarantine from DMG too
xattr -cr "dist/S1-Command-Center.dmg"

# clean up staging
rm -rf "$DMG_STAGE"

echo ""
echo "═══════════════════════════════════════════════════"
echo "  ✅ Build complete!"
echo "  App: dist/S1 Command Center.app"
echo "  DMG: dist/S1-Command-Center.dmg"
echo ""
echo "  DMG contains:"
echo "    • S1 Command Center.app"
echo "    • Install & Launch.command (quarantine fix)"
echo "    • README.txt"
echo "═══════════════════════════════════════════════════"
