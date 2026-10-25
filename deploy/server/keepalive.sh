#!/bin/bash
# Cron-Keepalive (jede Minute): startet gunicorn, falls er nicht läuft.
# cyon hat keinen aktiven Python-Selector/Passenger -> gunicorn lauscht lokal,
# LiteSpeed leitet per .htaccess ([P]) darauf weiter.
BASE="$HOME/daten-li"
PORT=38517
mkdir -p "$BASE/logs" "$BASE/data" "$BASE/cache"
exec 9>"$BASE/keepalive.lock"
flock -n 9 || exit 0

PIDFILE="$BASE/gunicorn.pid"
if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  exit 0
fi

cd "$BASE/app" || exit 1
export SQLITE_PATH="$BASE/data/liechtenstein.sqlite"
export CACHE_DIR="$BASE/cache"
# fd 9 (Lock) nicht an gunicorn vererben, sonst blockiert der Lock dauerhaft
setsid nohup "$BASE/venv/bin/gunicorn" app:server \
  --bind 127.0.0.1:$PORT --workers 2 --threads 2 --timeout 120 \
  --max-requests 2000 --max-requests-jitter 200 --preload \
  --pid "$PIDFILE" --error-logfile "$BASE/logs/gunicorn.log" \
  9>&- >>"$BASE/logs/gunicorn.out" 2>&1 &
