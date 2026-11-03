#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

command -v brew >/dev/null || { echo "Install Homebrew first from https://brew.sh"; exit 1; }
python3 -c "import tkinter" 2>/dev/null || brew install "python-tk@$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"

brew list --versions postgresql@17 >/dev/null || brew install postgresql@17
pg_bin="$(brew --prefix postgresql@17)/bin"

if ! "$pg_bin/pg_isready" -q; then
    brew services start postgresql@17
fi
for attempt in {1..20}; do
    "$pg_bin/pg_isready" -q && break
    sleep 1
done

if ! "$pg_bin/psql" -X -d pantry_meals_public -Atqc 'SELECT 1' >/dev/null 2>&1; then
    "$pg_bin/createdb" pantry_meals_public
fi

venv="${PANTRY_VENV:-.venv}"
settings="${PANTRY_SETTINGS:-.env}"
python3 -m venv "$venv"
"$venv/bin/python" -m pip install -r requirements.txt
if [ ! -f "$settings" ]; then
    cp .env.example "$settings"
    chmod 600 "$settings"
fi
"$venv/bin/python" meals.py init
