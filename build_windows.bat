@echo off
REM ═══════════════════════════════════════════════════════════
REM  S1 Command Center — Windows Build Script
REM  Creates a standalone .exe installer
REM ═══════════════════════════════════════════════════════════

set APP_NAME=S1 Command Center
echo ═══════════════════════════════════════════════════
echo   Building %APP_NAME% for Windows
echo ═══════════════════════════════════════════════════

REM ── Reproducible build: same code = same hash every time ──
REM  SOURCE_DATE_EPOCH  → deterministic timestamps in .pyc and PE headers
REM  PYTHONHASHSEED     → deterministic dict/set ordering
set SOURCE_DATE_EPOCH=1750000000
set PYTHONHASHSEED=0

REM ensure venv
if not exist venv (
    echo Creating virtual environment...
    python -m venv venv
)
call venv\Scripts\activate.bat

REM install deps
echo Installing dependencies...
pip install -q -r requirements.txt
pip install -q pyinstaller

REM ── Optional: compile a custom PyInstaller bootloader ──────────
REM  The stock bootloader is flagged by most AV/EDR products because
REM  its hash matches thousands of PyInstaller-built apps (incl. malware).
REM  Compiling from source produces a unique binary that bypasses those
REM  signatures. Requires Visual Studio / MSVC Build Tools to be installed.
REM  Uncomment the next 3 lines to enable:
REM pushd %VIRTUAL_ENV%\Lib\site-packages\PyInstaller\bootloader
REM python .\waf distclean all
REM popd

REM clean previous builds
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

REM build
echo Building application...
pyinstaller ^
    --name "S1 Command Center" ^
    --windowed ^
    --onedir ^
    --icon s1cc.ico ^
    --version-file version_info.txt ^
    --add-data "s1cc.ico;." ^
    --add-data "export_utils.py;." ^
    --hidden-import customtkinter ^
    --hidden-import openpyxl ^
    --hidden-import PIL ^
    --collect-all customtkinter ^
    --exclude-module jira_page ^
    --noconfirm ^
    main.py

echo.
echo ═══════════════════════════════════════════════════
echo   Build complete!
echo   Executable: dist\S1 Command Center\S1 Command Center.exe
echo.
echo   SHA256 (for cloud whitelisting):
certutil -hashfile "dist\S1 Command Center\S1 Command Center.exe" SHA256
echo ═══════════════════════════════════════════════════
pause
