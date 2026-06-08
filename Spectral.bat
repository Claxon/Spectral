@echo off
REM Launch the packaged Spectral spectrum analyzer.
REM Double-click this file (or run it from a terminal) to start the app.

set "EXE=%~dp0dist\SpectrumAnalyzer\SpectrumAnalyzer.exe"

if not exist "%EXE%" (
    echo Could not find the built executable:
    echo   "%EXE%"
    echo Build it first with:  python -m PyInstaller --noconfirm SpectrumAnalyzer.spec
    pause
    exit /b 1
)

start "" "%EXE%"
