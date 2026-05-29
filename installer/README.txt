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
    1. Click "Done" on the warning.
    2. Open System Settings → Privacy & Security.
       (Tip: type "Privacy & Security" into
        Spotlight, or paste this into Terminal:
            open "x-apple.systempreferences:com.apple.settings.PrivacySecurity.extension"
       )
    3. Scroll to the bottom of that pane —
       you'll see "S1 Command Center was
       blocked…".
    4. Click "Open Anyway".
    5. Enter your password / Touch ID.
    6. The app launches and is permanently
       whitelisted on this Mac.

  macOS Ventura (13) and older:
    → Right-click "S1 Command Center.app" in
      /Applications and choose "Open".
    → Click "Open" on the warning dialog.

FASTEST PATH (one Terminal command)
  Skip the Settings dance entirely. Drag the
  app to /Applications, then open Terminal
  (Spotlight → "Terminal") and paste:

      xattr -cr "/Applications/S1 Command Center.app"

  Then double-click the app normally. That one
  command strips the quarantine flag macOS
  attaches to anything downloaded from the
  internet, which is what Gatekeeper checks
  against on first launch.

────────────────────────────────────────────
Source & support:
  https://github.com/s1community/s1-command-center
────────────────────────────────────────────
