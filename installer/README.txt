S1 Command Center — Installation
═════════════════════════════════

INSTALL
  1. Drag "S1 Command Center.app" onto the
     "Applications" folder shown next to it
     in this window.
  2. Close this DMG window.
  3. Open the app from Launchpad or from
     /Applications.

FIRST LAUNCH (one time only)
This app isn't signed with an Apple Developer
ID, so macOS will ask you to confirm it on the
very first launch. After you confirm once,
macOS remembers and you'll never see the prompt
again.

If macOS says "Apple could not verify…":

  macOS Sonoma (14) / Sequoia (15) and newer:
    → Click "Done" on the warning.
    → Open System Settings → Privacy & Security.
    → Scroll to the bottom — you'll see
      "S1 Command Center was blocked…".
    → Click "Open Anyway".
    → Enter your password / Touch ID.
    → The app launches and is permanently
      whitelisted on this Mac.

  macOS Ventura (13) and older:
    → Right-click "S1 Command Center.app" in
      /Applications and choose "Open".
    → Click "Open" on the warning dialog.

TROUBLESHOOTING
  If the app still refuses to launch, open
  Terminal and run:

      xattr -cr "/Applications/S1 Command Center.app"

  Then open the app normally. This strips the
  quarantine flag that macOS attaches to every
  file downloaded from the internet.

────────────────────────────────────────────
Source & support:
  https://github.com/s1community/s1-command-center
────────────────────────────────────────────
