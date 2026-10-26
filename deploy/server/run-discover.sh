#!/bin/bash
# Wöchentlicher Discovery-Lauf für opendata.li (Cron, sonntags 05:30 UTC) bzw. manuell:
#   ~/daten-li/bin/run-discover.sh      Bericht: ~/daten-li/data/discovery-report.md
BASE="$HOME/daten-li"
exec 9>"$BASE/discover.lock"
flock -n 9 || { echo "Discovery läuft bereits"; exit 0; }
cd "$BASE/app" || exit 1
export SQLITE_PATH="$BASE/data/liechtenstein.sqlite"
export CACHE_DIR="$BASE/cache"
mkdir -p "$BASE/logs"
"$BASE/venv/bin/python" -u discover.py >>"$BASE/logs/discover.log" 2>&1
