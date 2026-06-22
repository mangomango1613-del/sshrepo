@echo off
REM ============================================================
REM tools/submit_fp.bat
REM Submit PyTermSSH.exe to AV vendors as a false positive.
REM This is FREE and the fastest way to stop AV detections.
REM Bitdefender reviews and whitelists within 24-48 hours.
REM ============================================================

set EXE=dist\PyTermSSH.exe

if not exist "%EXE%" (
    echo %EXE% not found. Build it first.
    pause & goto :eof
)

echo ============================================================
echo  Submitting to Bitdefender False Positive Portal
echo ============================================================
echo.
echo Your file: %CD%\%EXE%
echo Detection: Gen:Variant.Mikey  (Nuitka false positive)
echo.
echo Steps:
echo   1. We will open the Bitdefender submission page.
echo   2. Upload %EXE%
echo   3. Select: "False Positive"
echo   4. Category: "Clean Software wrongly detected"
echo   5. Description (copy/paste this):
echo.
echo   -------------------------------------------------------
echo   This file is a legitimate Python application compiled
echo   with Nuitka (https://nuitka.net) to native C++/exe.
echo   The Gen:Variant.Mikey detection is a known false positive
echo   for Nuitka-compiled applications. The application is an
echo   SSH/SFTP client (PyTermSSH) with open source on GitHub.
echo   The exe extracts to %%LOCALAPPDATA%%\PyTermSSH\runtime\
echo   (not a random %%TEMP%% path) and does not modify system files.
echo   -------------------------------------------------------
echo.
echo   6. Submit and wait 24-48 hours.
echo.

set /p OPEN="Open Bitdefender submission page? (Y/N): "
if /i "%OPEN%"=="Y" (
    start https://www.bitdefender.com/submit/
)

echo.
echo ============================================================
echo  Also submit to Windows Defender (Microsoft):
echo ============================================================
echo   https://www.microsoft.com/en-us/wdsi/filesubmission
echo   Select: "Software developer" -> "Submit file for analysis"
echo.
set /p OPEN2="Open Microsoft submission page? (Y/N): "
if /i "%OPEN2%"=="Y" (
    start https://www.microsoft.com/en-us/wdsi/filesubmission
)

echo.
echo ============================================================
echo  Immediate workaround while waiting for whitelist:
echo ============================================================
echo   Add exception in Bitdefender:
echo   1. Open Bitdefender
echo   2. Protection -^> Antivirus -^> Settings
echo   3. Exceptions -^> Add Exception
echo   4. Browse to: %CD%\%EXE%
echo   5. Click Save
echo.
pause
