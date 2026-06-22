@echo off
REM ============================================================
REM tools/sign_exe.bat
REM Code-sign the built exe to prevent AV false positives and
REM make Windows trust the application on first launch.
REM
REM You need ONE of these certificate types:
REM
REM   OPTION A - Self-signed certificate (FREE, fast, removes "Unknown
REM   Publisher" warning for YOUR machine only - good for personal use):
REM     Run this script with: sign_exe.bat self
REM
REM   OPTION B - Sectigo/DigiCert/GlobalSign OV certificate (~$80-200/yr,
REM   removes ALL AV warnings, green padlock, trusted everywhere):
REM     Buy from: https://www.sectigo.com/ssl-certificates/code-signing
REM               https://www.digicert.com/signing/code-signing-certificates
REM     Then run: sign_exe.bat pfx "path\to\your.pfx" "YourPassword"
REM
REM   OPTION C - Microsoft trusted signing (Azure, ~$9/mo, best AV bypass):
REM     See: https://learn.microsoft.com/en-us/azure/trusted-signing/
REM ============================================================

set EXE=dist\PyTermSSH.exe
set APP_NAME=PyTermSSH
set PUBLISHER_NAME=PyTermSSH Author

if not exist "%EXE%" (
    echo ERROR: %EXE% not found. Build it first with build_nuitka.bat
    goto :eof
)

set MODE=%1

if "%MODE%"=="self" goto :self_signed
if "%MODE%"=="pfx"  goto :pfx_sign
if "%MODE%"=="azure" goto :azure_sign

echo Usage:
echo   sign_exe.bat self                         - Self-signed cert (personal use)
echo   sign_exe.bat pfx "cert.pfx" "password"   - Commercial cert from .pfx file
echo   sign_exe.bat azure                        - Azure Trusted Signing
echo.
echo For no AV warnings on other machines, use option 'pfx' with a
echo commercial certificate from Sectigo/DigiCert (~$80-200/year).
goto :eof

REM ── Option A: Self-signed ────────────────────────────────────────────────
:self_signed
echo Creating self-signed code signing certificate...
powershell -Command ^
  "$cert = New-SelfSignedCertificate -Type CodeSigningCert ^
    -Subject 'CN=%PUBLISHER_NAME%' ^
    -CertStoreLocation Cert:\CurrentUser\My ^
    -KeyAlgorithm RSA -KeyLength 2048 ^
    -HashAlgorithm SHA256 ^
    -NotAfter (Get-Date).AddYears(3); ^
   $thumb = $cert.Thumbprint; ^
   Write-Host 'Thumbprint: '$thumb; ^
   Set-Content -Path tools\cert_thumbprint.txt -Value $thumb"

if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Could not create certificate. Run as Administrator.
    goto :eof
)

set /p THUMB=<tools\cert_thumbprint.txt
echo Signing %EXE% with self-signed certificate...
signtool sign /sha1 "%THUMB%" /fd SHA256 /t http://timestamp.digicert.com /v "%EXE%"
if %ERRORLEVEL% EQU 0 (
    echo.
    echo SUCCESS: Signed with self-signed certificate.
    echo NOTE: Windows will still show a blue SmartScreen warning on OTHER
    echo machines. For full trust everywhere, use a commercial certificate.
) else (
    echo ERROR: Signing failed. Make sure Windows SDK is installed.
    echo Download SDK: https://developer.microsoft.com/windows/downloads/windows-sdk/
)
goto :eof

REM ── Option B: Commercial .pfx certificate ────────────────────────────────
:pfx_sign
set PFX_PATH=%2
set PFX_PASS=%3

if "%PFX_PATH%"=="" (
    echo Usage: sign_exe.bat pfx "path\to\cert.pfx" "password"
    goto :eof
)

echo Signing with commercial certificate: %PFX_PATH%
signtool sign ^
  /f "%PFX_PATH%" ^
  /p "%PFX_PASS%" ^
  /fd SHA256 ^
  /tr http://timestamp.digicert.com ^
  /td SHA256 ^
  /d "%APP_NAME%" ^
  /du "https://github.com/yourusername/PyTermSSH" ^
  /v ^
  "%EXE%"

if %ERRORLEVEL% EQU 0 (
    echo.
    echo SUCCESS: Signed with commercial certificate.
    echo AV software and SmartScreen will fully trust this exe.
    signtool verify /pa /v "%EXE%"
) else (
    echo ERROR: Signing failed. Check certificate path and password.
)
goto :eof

REM ── Option C: Azure Trusted Signing ──────────────────────────────────────
:azure_sign
echo Azure Trusted Signing requires:
echo   1. Azure account + Trusted Signing resource
echo   2. azure-codesigning PowerShell module
echo.
echo Setup guide:
echo   https://learn.microsoft.com/en-us/azure/trusted-signing/quickstart
echo.
echo Once configured, run:
echo   az login
echo   AzureSignTool sign -kvu https://YOUR-VAULT.codesigning.azure.net ^
echo     -kvi "client-id" -kvt "tenant-id" -kvs "client-secret" ^
echo     -kvc "certificate-profile-name" -tr http://timestamp.acs.microsoft.com ^
echo     -v "%EXE%"
goto :eof
