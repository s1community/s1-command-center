═══════════════════════════════════════════════════════════════
  S1 Command Center — Installation
═══════════════════════════════════════════════════════════════

★ FASTEST INSTALL (recommended) — zero Gatekeeper prompts ★
───────────────────────────────────────────────────────────────
You DON'T need to drag anything from this window. Instead:

  1. Open Terminal
     (Spotlight: press ⌘+Space, type "Terminal", Enter)

  2. Copy and paste this entire line into Terminal, then
     press Return:

     /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/s1community/s1-command-center/main/installer/install.sh)"

  3. Done. The app installs to /Applications and launches
     automatically. macOS never shows "Apple could not
     verify…" — because the installer strips the quarantine
     flag before the first launch.

You can close this DMG window now and skip the rest of
this file. Or read on for the manual install path.

───────────────────────────────────────────────────────────────
  Manual install (traditional, requires a one-time Gatekeeper
  bypass via System Settings)
───────────────────────────────────────────────────────────────

  1. Drag "S1 Command Center.app" onto the "Applications"
     folder shown in this window.
  2. Close this DMG window.
  3. Open the app from Launchpad or /Applications.

On the very first launch macOS will say "Apple could not
verify…" because the app isn't signed with an Apple
Developer ID. After you unblock it once, macOS remembers
and never prompts again.

To unblock:

  macOS Sonoma (14) / Sequoia (15) and newer:
    1. Click "Done" on the warning.
    2. Open System Settings → Privacy & Security.
       (Spotlight tip: type "Privacy & Security".)
    3. Scroll to the bottom — you'll see "S1 Command
       Center was blocked from use…".
    4. Click "Open Anyway".
    5. Enter your password / Touch ID.

  macOS Ventura (13) and older:
    → Right-click "S1 Command Center.app" in /Applications
      and choose "Open" → click "Open" on the dialog.

  Or skip Settings entirely. In Terminal, paste:

      xattr -cr "/Applications/S1 Command Center.app"

  Then double-click the app normally.

───────────────────────────────────────────────────────────────
  Source & support
───────────────────────────────────────────────────────────────
  https://github.com/s1community/s1-command-center
