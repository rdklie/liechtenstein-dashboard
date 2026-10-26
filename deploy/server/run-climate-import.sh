#!/bin/bash
# Einmalige Langzeitladung der ERA5-Klimadaten 1950-Vorjahr (11 Gemeinden, 176 Abrufe, mit Pause/Backoff bei HTTP 429).
# Setzt abgebrochene Läufe fort. Im Hintergrund starten:  setsid nohup ~/daten-li/bin/run-climate-import.sh >/dev/null 2>&1 &
BASE="$HOME/daten-li"
exec 9>"$BASE/climate.lock"
flock -n 9 || { echo "Klimaimport läuft bereits"; exit 0; }
cd "$BASE/app" || exit 1
export SQLITE_PATH="$BASE/data/liechtenstein.sqlite"
export CACHE_DIR="$BASE/cache"
mkdir -p "$BASE/logs"
"$BASE/venv/bin/python" -u climate.py >>"$BASE/logs/climate-import.log" 2>&1
