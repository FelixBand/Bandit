@echo off
set APP_NAME=BanditGameLauncher
set SYSTEM_FOLDER=C:\ProgramData\%APP_NAME%

:: Check if running as admin
>nul 2>&1 "%SYSTEMROOT%\system32\cacls.exe" "%SYSTEMROOT%\system32\config\system"

if '%errorlevel%' NEQ '0' (
    echo Requesting admin privileges...
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit
)

:: Create system folder
if not exist "%SYSTEM_FOLDER%" (
    mkdir "%SYSTEM_FOLDER%"
)

echo System-wide folder created at %SYSTEM_FOLDER%