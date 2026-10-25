#!/bin/bash
# Täglicher Datenabruf (Cron) bzw. manuell: ~/daten-li/bin/run-worker.sh
BASE="$HOME/daten-li"
exec 9>"$BASE/worker.lock"
flock -n 9 || { echo "Worker läuft bereits"; exit 0; }
cd "$BASE/app" || exit 1
export SQLITE_PATH="$BASE/data/liechtenstein.sqlite"
export CACHE_DIR="$BASE/cache"
mkdir -p "$BASE/logs"
"$BASE/venv/bin/python" -u worker.py >>"$BASE/logs/worker.log" 2>&1
