#!/bin/bash
# Create (or refresh) the Python environment of HEOS Home Controller.
#
# Run once after the first install, and again when requirements.txt changes:
#     sudo /opt/heos-home/setup-env.sh            # create / update
#     sudo /opt/heos-home/setup-env.sh --recreate # start from scratch
#
# The environment (/opt/heos-home/.venv) sees Debian's own python3-* packages
# (--system-site-packages); on trixie they already satisfy requirements.txt, so
# pip installs nothing. On an older system pip fetches what is missing or too
# old (Raspberry Pi OS points pip at piwheels for ready-made ARM builds).
set -euo pipefail

APP_DIR=${HEOS_HOME_APP_DIR:-/opt/heos-home}
VENV=$APP_DIR/.venv
REQUIREMENTS=$APP_DIR/requirements.txt

if [ "$(id -u)" -ne 0 ]; then
    echo "Run as root: sudo $0 $*" >&2
    exit 1
fi
if [ "${1:-}" = "--recreate" ]; then
    echo "Removing $VENV"
    rm -rf "$VENV"
fi

if [ ! -x "$VENV/bin/python" ]; then
    echo "Creating $VENV"
    python3 -m venv --system-site-packages "$VENV"
fi

echo "Checking packages from $REQUIREMENTS"
"$VENV/bin/python" -m pip install --disable-pip-version-check --no-input -r "$REQUIREMENTS"

# Fails loudly if anything the service imports is still missing.
"$VENV/bin/python" - <<'PY'
import importlib.metadata as md
import sys
for name in ("fastapi", "starlette", "pydantic", "uvicorn", "websockets", "httpx", "cryptography"):
    print(f"  {name:13} {md.version(name)}")
print(f"  {'python':13} {sys.version.split()[0]}")
PY
PYTHONPATH="$APP_DIR/src" "$VENV/bin/python" -c "import heos_home.api.app"

if systemctl is-enabled --quiet heos-home.service 2>/dev/null; then
    echo "Restarting heos-home"
    systemctl restart heos-home.service
fi
echo "Python environment ready."
