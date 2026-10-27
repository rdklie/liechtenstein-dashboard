#!/bin/bash
# Gesamtimport der Jahresberichte der Landespolizei Liechtenstein (Erstimport und Freigabe eines vom Worker zurueckgehaltenen Jahres). Kein Cron:
# neue Berichte holt der Worker (police.auto_update) monatlich selbst und uebernimmt sie nur nach bestandener Pruefung.
# Rohdateien: ~/daten-li/data/archive/police/ (vorhandene PDFs werden nicht erneut geladen)
BASE="$HOME/daten-li"
cd "$BASE/app" || exit 1
export SQLITE_PATH="$BASE/data/liechtenstein.sqlite"
export CACHE_DIR="$BASE/cache"
mkdir -p "$BASE/logs"
"$BASE/venv/bin/python" -u police.py "$@" 2>&1 | tee -a "$BASE/logs/police-import.log"
