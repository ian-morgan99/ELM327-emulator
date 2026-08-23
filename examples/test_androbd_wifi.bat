@echo off
REM ###########################################################################
REM Quick start script for testing AndrOBD with WiFi/Network connection (Windows)
REM Usage: test_androbd_wifi.bat [port]
REM ###########################################################################

setlocal enabledelayedexpansion

set PORT=%1
if "%PORT%"=="" set PORT=35000

set SCENARIO=car

echo ==========================================
echo ELM327 Emulator - AndrOBD WiFi Test Setup
echo ==========================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo Error: Python is not installed or not in PATH
    exit /b 1
)

REM Get IP address
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4 Address"') do (
    set IP=%%a
    set IP=!IP:~1!
    goto :found
)
:found

echo Starting ELM327 emulator...
echo   Scenario: %SCENARIO%
echo   Port: %PORT%
echo   IP Address: %IP%
echo.
echo ==========================================
echo AndrOBD Configuration:
echo ==========================================
echo   1. Open AndrOBD on your Android device
echo   2. Go to Settings
echo   3. Connection type: Network (WiFi)
echo   4. IP Address: %IP%
echo   5. Port: %PORT%
echo   6. Click Connect
echo ==========================================
echo.
echo Press Ctrl+C to stop the emulator
echo.

REM Start the emulator
python -m elm -s %SCENARIO% -n %PORT%
