#!/bin/bash
# Einmaliger Import des CIA-World-Factbook-Archivs (Liechtenstein, 1990-2025). Kein Cron!
# Rohdateien: ~/daten-li/data/archive/factbook/ (bereits vorhandene Jahre werden nicht erneut geladen)
BASE="$HOME/daten-li"
cd "$BASE/app" || exit 1
export SQLITE_PATH="$BASE/data/liechtenstein.sqlite"
export CACHE_DIR="$BASE/cache"
mkdir -p "$BASE/logs"
"$BASE/venv/bin/python" -u factbook_import.py 2>&1 | tee -a "$BASE/logs/factbook-import.log"
