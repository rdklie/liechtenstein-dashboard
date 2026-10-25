#!/bin/bash
# Stoppt gunicorn; der Cron-Keepalive startet ihn innerhalb einer Minute neu
# (deploy.ps1 ruft anschliessend keepalive.sh direkt auf).
PIDFILE="$HOME/daten-li/gunicorn.pid"
if [ -f "$PIDFILE" ]; then
  PID=$(cat "$PIDFILE")
  kill "$PID" 2>/dev/null
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    kill -0 "$PID" 2>/dev/null || break
    sleep 1
  done
fi
