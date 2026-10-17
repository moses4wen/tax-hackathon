#!/bin/sh
set -eu
cd "$(dirname "$0")"
PYTHON_BIN="${PYTHON_BIN:-python3}"
"$PYTHON_BIN" -c 'import sys; assert sys.version_info >= (3,11), "Python 3.11+ erforderlich"'
if [ ! -d .venv ]; then
  echo "Python-Umgebung wird eingerichtet ..."
  "$PYTHON_BIN" -m venv .venv
fi
if ! .venv/bin/python -c 'from importlib.metadata import version
from pathlib import Path
for line in Path("requirements.txt").read_text().splitlines():
    if "==" in line:
        name, expected = line.strip().split("==", 1)
        if version(name) != expected:
            raise SystemExit(1)' >/dev/null 2>&1; then
  echo "Python-Abhängigkeiten werden installiert ..."
  .venv/bin/python -m pip install -r requirements.txt
fi
if [ -f .env ]; then
  set -a
  . ./.env
  set +a
fi
HOST="${BIND_ADDRESS:-127.0.0.1}"
PORT="${PORT:-8080}"
echo "processGraph startet: http://$HOST:$PORT (Ctrl+C zum Beenden)"
exec .venv/bin/python -m uvicorn app.server:app --host "$HOST" --port "$PORT"
