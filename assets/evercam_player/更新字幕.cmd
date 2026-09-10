@echo off
rem Project: https://github.com/kaoshou/evercam-subtitle-player
setlocal
title EverCam Subtitle Updater

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\Build-Subtitles.ps1"
if errorlevel 1 (
    echo.
    echo Subtitle update failed. Please check the file names and try again.
    pause
    exit /b 1
)

if /I "%~1"=="--no-launch" exit /b 0

echo.
echo Opening the course player...
start "" "%~dp0index.html"
timeout /t 2 /nobreak >nul
