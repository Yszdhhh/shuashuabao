#!/usr/bin/env bash
# Idempotent Cloud Agent setup for GameScript-Local.
# Prepares the Python backend/test toolchain and builds the web control panel.
set -euo pipefail

cd "$(dirname "$0")/.."

# --- System packages -------------------------------------------------------
# python venv/dev + a C toolchain are needed to build native wheels (evdev),
# and the libEGL/GL/xkb/dbus/glib runtime lets PySide6 (Qt) import so the
# desktop-app test suite can run headless with QT_QPA_PLATFORM=offscreen.
export DEBIAN_FRONTEND=noninteractive
sudo apt-get update -qq
sudo apt-get install -y --no-install-recommends \
  python3.12-venv python3.12-dev build-essential \
  libegl1 libgl1 libglib2.0-0 libxkbcommon0 libdbus-1-3

# --- Python virtual environment -------------------------------------------
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
. .venv/bin/activate
python -m pip install --upgrade pip
# requirements.txt is the full desktop+web dependency set; pytest(+timeout)
# power the automated suite.
pip install -r requirements.txt pytest pytest-timeout

# --- Frontend build --------------------------------------------------------
# FastAPI serves ui/dist at "/" when present, so build it during setup.
pushd ui >/dev/null
if [ -f package-lock.json ]; then
  npm ci
else
  npm install
fi
npm run build
popd >/dev/null

echo "GameScript-Local environment ready."
