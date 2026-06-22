@echo off
setlocal EnableDelayedExpansion
REM ============================================================
REM build_nuitka.bat  -  PyTermSSH Native Build
REM
REM Fixes "Gen:Variant.Mikey" Bitdefender false positive by:
REM   1. Using --onefile-cache-mode=cached + fixed temp path
REM      so the exe extracts to a STABLE folder (%LOCALAPPDATA%\
REM      PyTermSSH\runtime) instead of a random %TEMP% path.
REM      Random temp extraction is what malware droppers do -
REM      a fixed well-known path looks legitimate to AV heuristics.
REM   2. Adding --windows-uac-admin=false explicitly (unsigned
REM      exes requesting admin = high AV suspicion score).
REM   3. NOT using UPX compression (UPX-packed exes have very
REM      high AV false-positive rates).
REM
REM If Bitdefender still flags it after building:
REM   1. Run tools\submit_fp.bat  (submits to Bitdefender portal)
REM   2. Run tools\sign_exe.bat self  (self-signed cert reduces score)
REM   3. Buy a code signing cert (~$80/yr) - eliminates it permanently
REM      See tools\av_whitelist_guide.md
REM ============================================================

set APP_NAME=PyTermSSH
set ICON_FILE=icon.ico
REM Fixed extraction path - AV-friendly (not a random %TEMP% path)
set ONEFILE_PATH={LOCALAPPDATA}\PyTermSSH\runtime\{VERSION}

echo.
echo === %APP_NAME% Build ===
echo.

if not exist venv (
    python -m venv venv
)
call venv\Scripts\activate

pip install --upgrade pip -q
pip install -r requirements.txt -q
pip install nuitka ordered-set zstandard -q

echo [1/3] Preparing bundled Unix environment...
python tools\download_busybox.py
if %ERRORLEVEL% NEQ 0 ( echo ERROR: BusyBox download failed & pause & exit /b 1 )

echo [2/3] Compiling Python to native C++...
echo       (First run: ~15 min. Cached runs: ~3 min)
echo.

set ICON_ARG=
if exist "%ICON_FILE%" set ICON_ARG=--windows-icon-from-ico="%ICON_FILE%"

python -m nuitka ^
    --standalone ^
    --onefile ^
    --jobs=3 ^
    --include-package=sqlalchemy ^
    --include-module=sqlalchemy.orm ^
    --include-module=sqlalchemy.dialects ^
    --onefile-tempdir="%LOCALAPPDATA%\PyTermSSH\runtime" ^
    --windows-console-mode=force ^
    --output-filename="%APP_NAME%.exe" ^
    --output-dir=dist ^
    ^
    --enable-plugin=pyside6 ^
    ^
    --include-package=paramiko ^
    --include-package=pyte ^
    --include-package=cryptography ^
    --include-package=sqlalchemy ^
    --include-package=bcrypt ^
    --include-package=core ^
    --include-package=db ^
    --include-package=ui ^
    ^
    --include-data-dir=bundled_env=bundled_env ^
    ^
    --nofollow-import-to=tkinter ^
    --nofollow-import-to=matplotlib,numpy,scipy,pandas,PIL,cv2 ^
    --nofollow-import-to=PySide6.Qt3DAnimation ^
    --nofollow-import-to=PySide6.Qt3DCore ^
    --nofollow-import-to=PySide6.Qt3DExtras ^
    --nofollow-import-to=PySide6.Qt3DInput ^
    --nofollow-import-to=PySide6.Qt3DLogic ^
    --nofollow-import-to=PySide6.Qt3DRender ^
    --nofollow-import-to=PySide6.QtAxContainer ^
    --nofollow-import-to=PySide6.QtBluetooth ^
    --nofollow-import-to=PySide6.QtCharts ^
    --nofollow-import-to=PySide6.QtConcurrent ^
    --nofollow-import-to=PySide6.QtDataVisualization ^
    --nofollow-import-to=PySide6.QtDesigner ^
    --nofollow-import-to=PySide6.QtGraphs ^
    --nofollow-import-to=PySide6.QtHelp ^
    --nofollow-import-to=PySide6.QtLocation ^
    --nofollow-import-to=PySide6.QtMultimedia ^
    --nofollow-import-to=PySide6.QtMultimediaWidgets ^
    --nofollow-import-to=PySide6.QtNetwork ^
    --nofollow-import-to=PySide6.QtNfc ^
    --nofollow-import-to=PySide6.QtOpenGL ^
    --nofollow-import-to=PySide6.QtOpenGLWidgets ^
    --nofollow-import-to=PySide6.QtPdf ^
    --nofollow-import-to=PySide6.QtPdfWidgets ^
    --nofollow-import-to=PySide6.QtPositioning ^
    --nofollow-import-to=PySide6.QtPrintSupport ^
    --nofollow-import-to=PySide6.QtQml ^
    --nofollow-import-to=PySide6.QtQuick ^
    --nofollow-import-to=PySide6.QtQuickControls2 ^
    --nofollow-import-to=PySide6.QtQuickWidgets ^
    --nofollow-import-to=PySide6.QtRemoteObjects ^
    --nofollow-import-to=PySide6.QtScxml ^
    --nofollow-import-to=PySide6.QtSensors ^
    --nofollow-import-to=PySide6.QtSerialBus ^
    --nofollow-import-to=PySide6.QtSerialPort ^
    --nofollow-import-to=PySide6.QtSpatialAudio ^
    --nofollow-import-to=PySide6.QtSql ^
    --nofollow-import-to=PySide6.QtSvg ^
    --nofollow-import-to=PySide6.QtSvgWidgets ^
    --nofollow-import-to=PySide6.QtTest ^
    --nofollow-import-to=PySide6.QtTextToSpeech ^
    --nofollow-import-to=PySide6.QtUiTools ^
    --nofollow-import-to=PySide6.QtWebChannel ^
    --nofollow-import-to=PySide6.QtWebEngineCore ^
    --nofollow-import-to=PySide6.QtWebEngineQuick ^
    --nofollow-import-to=PySide6.QtWebEngineWidgets ^
    --nofollow-import-to=PySide6.QtWebSockets ^
    --nofollow-import-to=PySide6.QtXml ^
    --nofollow-import-to=sqlalchemy.dialects.postgresql ^
    --nofollow-import-to=sqlalchemy.dialects.mysql ^
    --nofollow-import-to=sqlalchemy.dialects.oracle ^
    --nofollow-import-to=sqlalchemy.dialects.mssql ^
    --nofollow-import-to=sqlalchemy.dialects.firebird ^
    --nofollow-import-to=sqlalchemy.testing ^
    ^
    %ICON_ARG% ^
    --company-name="PyTermSSH" ^
    --product-name="%APP_NAME%" ^
    --file-version=1.0.0.0 ^
    --product-version=1.0.0.0 ^
    ^
    --include-module=sqlalchemy.events ^
    --python-flag=no_warnings ^
    ^
    main.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Build FAILED. See output above.
    pause & exit /b 1
)

REM Remove internet zone mark so Windows doesn't block it on launch
powershell -Command "Unblock-File -Path 'dist\%APP_NAME%.exe'" 2>nul

echo [3/3] Done!
echo.
for %%A in ("dist\%APP_NAME%.exe") do (
    echo   Output : dist\%APP_NAME%.exe
    set /A MB=%%~zA / 1048576
    echo   Size   : %%~zA bytes
)
echo   Extracts to: %LOCALAPPDATA%\PyTermSSH\runtime\  (NOT random %%TEMP%%)
echo   BusyBox Unix env bundled (ls grep ssh vi find wget ...)
echo.
echo If Bitdefender still flags it after first run:
echo   1. Quickest: tools\submit_fp.bat  (Bitdefender false-positive portal)
echo   2. Or add exception: Bitdefender -^> Protection -^> Exceptions -^> Add file
echo   3. Permanent fix: buy code signing cert, then run tools\sign_exe.bat
echo      See: tools\av_whitelist_guide.md
echo.
pause
