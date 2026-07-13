### ⚡ Fastest install on macOS — paste this in Terminal

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/s1community/s1-command-center/main/installer/install.sh)"
```

That's the whole install. No DMG to download, **no Gatekeeper prompts, no System Settings detour** — the script runs in Terminal (which Gatekeeper doesn't gate), strips the macOS quarantine flag from the app before the first launch, and opens it for you. Optional env vars: `S1CC_VERSION=vX.Y.Z` to pin a specific version, `S1CC_NO_LAUNCH=1` to skip auto-launch.

### Manual downloads

- **macOS**: `S1-Command-Center-macOS.dmg` — Drag the app to Applications. First launch will hit Gatekeeper; the DMG's `README.txt` explains the one-time bypass (or use the one-liner above to skip it entirely).
- **Windows (installer, recommended)**: `S1-Command-Center-Windows-Setup.exe` — Installs to `Program Files`, creates Start Menu + optional desktop shortcuts, and registers an uninstaller in *Add or Remove Programs*.
- **Windows (portable ZIP)**: `S1-Command-Center-Windows.zip` — Extract anywhere and run `S1 Command Center.exe`. No install, no Start Menu entry.

### Requirements

- No Python installation needed — fully standalone
- macOS 12+ (Intel & Apple Silicon)
- Windows 10/11 (64-bit)
