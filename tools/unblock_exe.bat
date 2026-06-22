@echo off
REM tools/unblock_exe.bat
REM Run this if PyTermSSH.exe won't start after downloading.
REM Windows marks downloaded files as "from internet" and blocks
REM unsigned ones from running silently. This removes that mark.

set EXE=dist\PyTermSSH.exe

if not exist "%EXE%" (
    echo %EXE% not found. Run from the sshclient folder after building.
    pause
    goto :eof
)

echo Unblocking %EXE%...
powershell -Command "Unblock-File -Path '%EXE%'"

if %ERRORLEVEL% EQU 0 (
    echo.
    echo Done. Try running %EXE% now.
    echo.
    echo If it still doesn't start:
    echo   1. Add an exception in your antivirus for this exe.
    echo      Bitdefender: Protection -^> Antivirus -^> Exceptions -^> Add
    echo      Windows Defender: Start -^> Windows Security -^> Virus Protection
    echo                        -^> Manage Settings -^> Add Exclusion
    echo   2. Run tools\sign_exe.bat self  (creates a self-signed certificate)
    echo   3. For permanent fix: sign with a commercial cert. See:
    echo      tools\av_whitelist_guide.md
) else (
    echo Error. Try right-clicking the exe -^> Properties -^> Unblock checkbox.
)
pause
