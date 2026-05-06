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
    --noconfirm \
    main.py

# remove quarantine flag so users don't get the malware warning
echo "Removing quarantine flags..."
xattr -cr "dist/S1 Command Center.app"

# create DMG
echo "Creating DMG installer..."
hdiutil create -volname "S1 Command Center" \
    -srcfolder "dist/S1 Command Center.app" \
    -ov -format UDZO "dist/S1-Command-Center.dmg"

# remove quarantine from DMG too
xattr -cr "dist/S1-Command-Center.dmg"

echo ""
echo "═══════════════════════════════════════════════════"
echo "  ✅ Build complete!"
echo "  App: dist/S1 Command Center.app"
echo "  DMG: dist/S1-Command-Center.dmg"
echo "═══════════════════════════════════════════════════"
