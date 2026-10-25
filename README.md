# Liechtenstein Dashboard

Dash-Dashboard (Python) mit offenen Daten zu Liechtenstein (World Bank, Open-Meteo, Eurostat, OpenStreetMap).
Live unter <https://daten.li>.

| Datei | Aufgabe |
|---|---|
| `app.py` | Dash-App (`app:server` ist das WSGI-Objekt) |
| `data_fetcher.py` | Abruf der externen APIs inkl. Fallbacks bei Rate-Limits (Open-Meteo 429, Eurostat, OSM) |
| `db.py` | Datenbankschicht, SQLite (optional `DATABASE_URL`, z. B. PostgreSQL) |
| `worker.py` | Täglicher Datenabruf, schreibt die DB |
| `deploy/` | Deployment nach cyon |

## Lokal starten

```bash
pip install -r requirements.txt
python worker.py     # optional: DB füllen (data/liechtenstein.sqlite); ohne Daten ruft die App die APIs direkt auf
python app.py        # http://127.0.0.1:8050
```

Umgebungsvariablen (alle optional):

- `SQLITE_PATH` – Pfad der SQLite-Datei (Standard `data/liechtenstein.sqlite`)
- `DATABASE_URL` – hat Vorrang vor SQLite, z. B. `postgresql://…`
- `CACHE_DIR` – Verzeichnis für den API-Cache (Standard `cache_data/`)

## Deployment auf cyon

Aufbau auf dem Server (Account `rdkli@s033.cyon.net`, alles unter `~/daten-li/`, ausserhalb des Webroots):

```
~/daten-li/app/       Code (von deploy.ps1 hochgeladen)
~/daten-li/venv/      Python-3.11-venv mit requirements.txt
~/daten-li/data/      liechtenstein.sqlite (+ -wal/-shm)
~/daten-li/cache/     API-Cache
~/daten-li/logs/      gunicorn.log, worker.log
~/daten-li/bin/       keepalive.sh, stop.sh, run-worker.sh
~/public_html/datasites/.htaccess   (Webroot von daten.li: nur diese Datei)
```

**Wie es läuft:** Der CloudLinux-Python-Selector/Passenger ist auf dem Account nicht aktiviert
(`cloudlinux-selector create` → „Selector is disabled“). Deshalb startet ein Cron-Keepalive
(`* * * * *`, `keepalive.sh`) gunicorn auf `127.0.0.1:38517`, und LiteSpeed leitet daten.li per
`.htaccess` (`RewriteRule … [P]`) darauf weiter. Stürzt der Prozess ab, startet ihn Cron innerhalb einer Minute neu.

**Datenabruf:** Cron `0 6 * * *` mit `CRON_TZ=UTC` (06:00 UTC) ruft `run-worker.sh` → `worker.py`.
Manuell: `ssh … '~/daten-li/bin/run-worker.sh'` (dauert ca. 3 Min., Log in `~/daten-li/logs/worker.log`).

**Deploy** (PowerShell, SSH-Key `~\.ssh\bnutt_cyon_ed25519`):

```powershell
.\deploy\deploy.ps1                         # Code + Abhängigkeiten + Crontab, gunicorn neu starten
.\deploy\deploy.ps1 -Htaccess -RunWorker    # erster Lauf: zusätzlich .htaccess (Backup .htaccess.bak) + Datenabruf
```

**HTTPS:** Das Let's-Encrypt-Zertifikat (daten.li, www.daten.li, dataportal.li, datenportal.li) wird im cyon-Panel
ausgestellt/erneuert (AutoSSL ist per SSH nicht verfügbar). `deploy.ps1 -ForceHttps` schreibt die `.htaccess` mit
HTTP→HTTPS-Weiterleitung und HSTS (nur verwenden, solange ein gültiges Zertifikat installiert ist); `/.well-known/`
bleibt für die Validierung frei. daten.li, dataportal.li und datenportal.li liefern gleichwertig dasselbe Dashboard aus (keine festen Hostnamen in der App); `www.` leitet jeweils auf die Domain ohne `www.`.

**OpenStreetMap:** `overpass-api.de` lehnt automatisierte Abfragen teils mit 502 ab, deshalb fragt der Worker zuerst
`overpass.osm.ch` (deckt Liechtenstein ab) und fällt auf `overpass-api.de` zurück. Schlägt alles fehl, bricht er nach zwei
Kategorien ab und lässt bestehende `osm_poi_counts` unverändert. Die Seite ruft Overpass nie live auf; ohne Daten
blendet das Dashboard den POI-Abschnitt aus.

**Render:** `render.yaml` ist nur noch Archiv der alten Einrichtung; Web-Service, Cron und Postgres bei Render
werden nicht mehr gebraucht.
