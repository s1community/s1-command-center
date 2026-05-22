# Installation

## Prerequisites

- **Python 3.10+** (tested on 3.11, 3.12, 3.13)
- **macOS**, **Windows**, or **Linux**

## Option 1: Download Pre-built App

Download the latest release from the [Releases page](https://github.com/s1community/s1-command-center/releases/latest):

| Platform | Download |
|----------|----------|
| **macOS** | `S1-Command-Center.dmg` |
| **Windows** | `S1-Command-Center.exe` |

### macOS First Launch

macOS may block the app because it's not from an identified developer:

1. Open **System Settings** → **Privacy & Security**
2. Scroll to the **Security** section
3. Click **Open Anyway** next to the blocked app message
4. Enter your password or Touch ID
5. Click **Open** on the confirmation

> After this one-time step, the app opens normally.

## Option 2: Run from Source

```bash
# Clone the repository
git clone https://github.com/s1community/s1-command-center.git
cd s1-command-center

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # macOS/Linux
# venv\Scripts\activate   # Windows

# Install dependencies
pip install -r requirements.txt

# Run
python main.py
```

## Dependencies

| Package | Purpose |
|---------|---------|
| `customtkinter` | Modern dark-themed GUI framework |
| `requests` | HTTP client for SentinelOne API |
| `openpyxl` | Excel report generation |
| `Pillow` | Image handling |

## Building from Source

### macOS

```bash
bash build_macos.sh
```

### Windows

```bat
build_windows.bat
```

Both scripts use PyInstaller to produce standalone executables.
