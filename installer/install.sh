#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  S1 Command Center — one-line macOS installer
#
#  Usage (paste into Terminal):
#    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/s1community/s1-command-center/main/installer/install.sh)"
#
#  What it does:
#    1. Resolves the latest GitHub release and downloads the .dmg
#    2. Mounts the .dmg
#    3. Copies "S1 Command Center.app" to /Applications (with sudo if needed)
#    4. Strips the com.apple.quarantine extended attribute
#    5. Unmounts the .dmg and launches the app
#
#  Why this avoids Gatekeeper:
#    Gatekeeper only enforces on GUI launches (Finder double-click, `open`
#    on a quarantined file). Files run from Terminal via bash/curl never go
#    through Gatekeeper. We strip the quarantine xattr from the .app before
#    we open it, so the first launch also bypasses Gatekeeper.
#
#  Optional env vars:
#    S1CC_VERSION   pin a specific tag (e.g. "v1.3.5"); default = latest
#    S1CC_NO_LAUNCH set to "1" to skip the final auto-launch
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

REPO="s1community/s1-command-center"
APP_NAME="S1 Command Center"
DEST="/Applications/${APP_NAME}.app"
VERSION="${S1CC_VERSION:-latest}"

bold()  { printf "\033[1m%s\033[0m\n" "$*"; }
dim()   { printf "\033[2m%s\033[0m\n" "$*"; }
ok()    { printf "\033[32m✓\033[0m %s\n" "$*"; }
warn()  { printf "\033[33m!\033[0m %s\n" "$*"; }
fail()  { printf "\033[31m✗\033[0m %s\n" "$*" >&2; exit 1; }

# ── sanity checks ───────────────────────────────────────────────────────────
[ "$(uname -s)" = "Darwin" ] || fail "This installer is macOS-only."
command -v curl    >/dev/null || fail "curl not found."
command -v hdiutil >/dev/null || fail "hdiutil not found (this should be impossible on macOS)."

echo
bold "── S1 Command Center installer ────────────────────────"
dim  "   target version : ${VERSION}"
dim  "   destination    : ${DEST}"
echo

# ── 1. resolve DMG download URL ─────────────────────────────────────────────
if [ "$VERSION" = "latest" ]; then
    API_URL="https://api.github.com/repos/${REPO}/releases/latest"
else
    API_URL="https://api.github.com/repos/${REPO}/releases/tags/${VERSION}"
fi

dim "→ querying GitHub release API…"
RELEASE_JSON="$(curl -fsSL "$API_URL")" \
    || fail "Couldn't reach GitHub. Check your network."

DMG_URL="$(printf '%s' "$RELEASE_JSON" \
    | grep -o '"browser_download_url": *"[^"]*\.dmg"' \
    | head -n1 \
    | sed -E 's/.*"(https:[^"]+\.dmg)".*/\1/')"

[ -n "$DMG_URL" ] || fail "No .dmg asset found on release ${VERSION}."
ok "found DMG: $(basename "$DMG_URL")"

# ── 2. download to a temp dir ───────────────────────────────────────────────
TMP="$(mktemp -d -t s1cc-install)"
DMG="${TMP}/S1-Command-Center.dmg"
MOUNT=""

cleanup() {
    if [ -n "$MOUNT" ] && [ -d "$MOUNT" ]; then
        hdiutil detach "$MOUNT" -quiet -force 2>/dev/null || true
    fi
    rm -rf "$TMP"
}
trap cleanup EXIT INT TERM

dim "→ downloading…"
curl -fL# -o "$DMG" "$DMG_URL" \
    || fail "Download failed."
ok "downloaded $(du -h "$DMG" | awk '{print $1}')"

# ── 3. mount ────────────────────────────────────────────────────────────────
dim "→ mounting DMG…"
MOUNT_INFO="$(hdiutil attach -nobrowse -noautoopen -readonly "$DMG")"
MOUNT="$(printf '%s' "$MOUNT_INFO" | grep -E '/Volumes/' | head -n1 | awk -F'\t' '{print $NF}')"
[ -d "$MOUNT" ] || fail "Mount failed. (hdiutil output: $MOUNT_INFO)"
SRC="${MOUNT}/${APP_NAME}.app"
[ -d "$SRC" ] || fail "Couldn't find '${APP_NAME}.app' inside the DMG."
ok "mounted at $MOUNT"

# ── 4. copy to /Applications (with sudo fallback) ───────────────────────────
dim "→ installing to /Applications…"
if [ -d "$DEST" ]; then
    warn "existing install found — replacing"
    rm -rf "$DEST" 2>/dev/null || sudo rm -rf "$DEST"
fi
cp -R "$SRC" /Applications/ 2>/dev/null || {
    warn "need admin password to write to /Applications"
    sudo cp -R "$SRC" /Applications/
}
ok "copied to ${DEST}"

# ── 5. strip quarantine so first launch bypasses Gatekeeper ─────────────────
dim "→ removing quarantine flag…"
xattr -cr "$DEST" 2>/dev/null || sudo xattr -cr "$DEST"
ok "quarantine cleared"

# ── 6. unmount ──────────────────────────────────────────────────────────────
hdiutil detach "$MOUNT" -quiet 2>/dev/null || true
MOUNT=""

echo
bold "── ✅ S1 Command Center installed ────────────────────"
dim  "   location: ${DEST}"
echo

# ── 7. launch (unless suppressed) ───────────────────────────────────────────
if [ "${S1CC_NO_LAUNCH:-0}" != "1" ]; then
    dim "→ launching…"
    open "$DEST"
else
    dim "skipping auto-launch (S1CC_NO_LAUNCH=1)"
fi
