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

# create the installer script that removes quarantine + launches
cat > "$DMG_STAGE/Install & Launch.command" << 'SCRIPT'
#!/bin/bash
# ─────────────────────────────────────────────────────
#  S1 Command Center — macOS Setup
#  Removes quarantine flag and launches the app.
#  Run this ONCE after downloading. After that, open
#  the app normally from /Applications.
# ─────────────────────────────────────────────────────
clear
echo ""
echo "═══════════════════════════════════════════════════"
echo "  🛡️  S1 Command Center — Setup"
echo "═══════════════════════════════════════════════════"
echo ""

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_PATH="$SCRIPT_DIR/S1 Command Center.app"
DEST="/Applications/S1 Command Center.app"

if [ ! -d "$APP_PATH" ]; then
    echo "❌ Could not find 'S1 Command Center.app' next to this script."
    echo "   Make sure both files are in the same folder."
    echo ""
    read -p "Press Enter to close..." _
    exit 1
fi

echo "📦 Copying to /Applications..."
cp -R "$APP_PATH" "/Applications/" 2>/dev/null || {
    echo "⚠️  Need admin permission to copy to /Applications."
    sudo cp -R "$APP_PATH" "/Applications/"
}

echo "🔓 Removing macOS quarantine flag..."
xattr -cr "$DEST" 2>/dev/null
sudo xattr -cr "$DEST" 2>/dev/null

echo "🚀 Launching S1 Command Center..."
echo ""
echo "═══════════════════════════════════════════════════"
echo "  ✅ Setup complete! The app is now in /Applications."
echo "  You can open it normally from now on."
echo "═══════════════════════════════════════════════════"
echo ""

open "$DEST"
sleep 2
SCRIPT
chmod +x "$DMG_STAGE/Install & Launch.command"

# create a README in the DMG
cat > "$DMG_STAGE/README.txt" << 'README'
S1 Command Center — Installation
═════════════════════════════════

Double-click "Install & Launch.command" to:
  1. Copy the app to /Applications
  2. Remove the macOS quarantine flag
  3. Launch the app

After the first run, open the app normally
from /Applications or Spotlight.
README

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
