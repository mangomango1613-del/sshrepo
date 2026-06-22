#!/bin/bash
# build_nuitka.sh - Linux/macOS Nuitka build with BusyBox bundling
set -e

APP_NAME="${1:-PyTermSSH}"
ICON_FILE="${2:-icon.png}"

echo "=== ${APP_NAME} Nuitka Build ==="

if [ ! -d "venv" ]; then python3 -m venv venv; fi
source venv/bin/activate

pip install --upgrade pip -q
pip install -r requirements.txt -q
pip install nuitka ordered-set zstandard -q

echo "[1/3] Preparing bundled environment..."
python tools/download_busybox.py

echo "[2/3] Compiling Python to native C++..."
command -v ccache &>/dev/null && export CC="ccache gcc" CXX="ccache g++"

ICON_ARG=""
[ -f "$ICON_FILE" ] && ICON_ARG="--linux-icon=${ICON_FILE}"
[[ "$OSTYPE" == "darwin"* ]] && [ -f "icon.icns" ] && ICON_ARG="--macos-app-icon=icon.icns"

python3 -m nuitka \
  --standalone --onefile \
  --output-filename="${APP_NAME}" \
  --output-dir=dist \
  --enable-plugin=pyside6 \
  --include-package=paramiko,pyte,cryptography,sqlalchemy,bcrypt,core,db,ui \
  --include-data-dir=bundled_env=bundled_env \
  --nofollow-import-to=tkinter,matplotlib,numpy,scipy,pandas \
  --nofollow-import-to=PySide6.Qt3DAnimation,PySide6.Qt3DCore,PySide6.Qt3DExtras \
  --nofollow-import-to=PySide6.QtBluetooth,PySide6.QtCharts,PySide6.QtDataVisualization \
  --nofollow-import-to=PySide6.QtGraphs,PySide6.QtLocation,PySide6.QtMultimedia \
  --nofollow-import-to=PySide6.QtMultimediaWidgets,PySide6.QtNetwork,PySide6.QtNfc \
  --nofollow-import-to=PySide6.QtOpenGL,PySide6.QtOpenGLWidgets,PySide6.QtPdf \
  --nofollow-import-to=PySide6.QtPdfWidgets,PySide6.QtPositioning,PySide6.QtPrintSupport \
  --nofollow-import-to=PySide6.QtQml,PySide6.QtQuick,PySide6.QtQuickControls2 \
  --nofollow-import-to=PySide6.QtQuickWidgets,PySide6.QtRemoteObjects,PySide6.QtScxml \
  --nofollow-import-to=PySide6.QtSensors,PySide6.QtSerialBus,PySide6.QtSerialPort \
  --nofollow-import-to=PySide6.QtSpatialAudio,PySide6.QtSql,PySide6.QtSvg \
  --nofollow-import-to=PySide6.QtSvgWidgets,PySide6.QtTest,PySide6.QtTextToSpeech \
  --nofollow-import-to=PySide6.QtUiTools,PySide6.QtWebChannel,PySide6.QtWebEngineCore \
  --nofollow-import-to=PySide6.QtWebEngineQuick,PySide6.QtWebEngineWidgets \
  --nofollow-import-to=PySide6.QtWebSockets,PySide6.QtXml \
  --nofollow-import-to=sqlalchemy.dialects.postgresql,sqlalchemy.dialects.mysql \
  --nofollow-import-to=sqlalchemy.dialects.oracle,sqlalchemy.dialects.mssql \
  --nofollow-import-to=sqlalchemy.dialects.firebird,sqlalchemy.testing \
  ${ICON_ARG} \
  --python-flag=no_docstrings,no_warnings \
  main.py

echo "[3/3] Done!"
SIZE=$(du -sh "dist/${APP_NAME}" 2>/dev/null | cut -f1)
echo "Output: dist/${APP_NAME}  (${SIZE})"
echo "BusyBox Unix commands bundled inside."
