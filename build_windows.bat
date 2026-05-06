@echo off
REM ═══════════════════════════════════════════════════════════
REM  S1 Command Center — Windows Build Script
REM  Creates a standalone .exe installer
REM ═══════════════════════════════════════════════════════════

set APP_NAME=S1 Command Center
echo ═══════════════════════════════════════════════════
echo   Building %APP_NAME% for Windows
echo ═══════════════════════════════════════════════════

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
    --add-data "s1cc.ico;." ^
    --add-data "export_utils.py;." ^
    --hidden-import customtkinter ^
    --hidden-import openpyxl ^
    --hidden-import PIL ^
    --collect-all customtkinter ^
    --noconfirm ^
    main.py

echo.
echo ═══════════════════════════════════════════════════
echo   Build complete!
echo   Executable: dist\S1 Command Center\S1 Command Center.exe
echo ═══════════════════════════════════════════════════
pause
