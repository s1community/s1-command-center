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
