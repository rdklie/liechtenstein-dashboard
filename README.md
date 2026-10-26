# Liechtenstein Dashboard

Dash-Dashboard (Python) mit offenen Daten zu Liechtenstein (World Bank, Open-Meteo, Eurostat, OpenStreetMap).
Live unter <https://daten.li>.

| Datei | Aufgabe |
|---|---|
| `app.py` | Dash-App (`app:server` ist das WSGI-Objekt) |
| `data_fetcher.py` | Abruf der externen APIs inkl. Fallbacks bei Rate-Limits (Open-Meteo 429, Eurostat, OSM) |
| `db.py` | Datenbankschicht, SQLite (optional `DATABASE_URL`, z. B. PostgreSQL) |
| `worker.py` | Täglicher Datenabruf, schreibt die DB |
| `opendata.py` | Anbindung opendata.li: Katalog (EntryStore/DCAT) und PXWeb-API des Amts für Statistik |
| `discover.py` | Wöchentlicher Discovery-Crawler: meldet neue/geänderte/entfernte Datensätze |
| `tab_wohnen.py`, `tab_opendata.py` | Tabs «Wohnen & Immobilien» und «Open Data» (Explorer) |
| `ui.py` | Gemeinsame Farben/Diagramm-Helfer |
| `deploy/` | Deployment nach cyon |

## Open Data & Wohnen

**Quelle:** [opendata.li](https://www.opendata.li/de/daten) (Landesverwaltung). Die Seite lädt den Katalog per EntryScape aus dem
EntryStore `https://catalog.opendata.li/store/` (DCAT, ~500 Datensätze). Gut 460 davon sind Statistik-Tabellen des Amts für
Statistik, abrufbar über die PXWeb-API `https://etab.llv.li/PXWeb/api/v1/de/eTab/…` (GET = Metadaten, POST = Daten; das Format
`json-stat2` liefert dort fehlerhaft nur einen Wert, deshalb wird `json` verwendet). Der Rest sind Geodaten und Dateien.
**Lizenz:** Namensnennung (CC BY, dcat-ap.ch `terms_by`) — «Amt für Statistik Liechtenstein, opendata.li»; die Quelle steht unter jedem Diagramm.

- **Tab «Wohnen»:** Wohnungsbestand seit 1980, am Stichtag nicht bewohnte Wohnungen (2014–2025), Mietpreise (Volkszählung 2010/2015/2020),
  Bautätigkeit, jeweils je Gemeinde. Die Tabellen stehen in `opendata.CURATED`; der Worker spiegelt sie täglich nach SQLite (`px_cache`).
  **Nicht verfügbar:** Kaufpreise und m²-Preise (keine offizielle Quelle; kommerzielle Portale werden nicht ausgewertet). Die Mietpreise sind
  Durchschnitte pro Wohnung und Monat, keine m²-Preise.
- **Tab «Open Data»:** Explorer über den ganzen Katalog (Tabelle suchen, Achsen/Gruppierung/Filter wählen, Diagramm, Vorschau, CSV).
  Tabellen, die nicht im Cache liegen oder älter als 7 Tage sind, werden einmalig live geladen und gespeichert.
- **Discovery:** `discover.py` (Cron sonntags 05:30 UTC, manuell `~/daten-li/bin/run-discover.sh`) liest Katalog und PXWeb-Baum, vergleicht
  mit dem letzten Stand (`od_catalog`) und meldet neu/geändert/entfernt/«PX-Tabelle nicht im Katalog» in `od_discovery_log`,
  `~/daten-li/data/discovery-report.md` und im Tab «Open Data». Er veröffentlicht nichts automatisch.
- **Rücksicht auf die APIs:** ≥ 0,4 s Pause je Request, Retries mit Backoff, grosse Tabellen werden auf ≤ 40 000 Zellen reduziert;
  die App ruft die APIs nur beim Explorer-Livezugriff auf.

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

**Datenabruf:** Cron `0 6 * * *` mit `CRON_TZ=UTC` (06:00 UTC) ruft `run-worker.sh` → `worker.py`; sonntags 05:30 UTC läuft `run-discover.sh` → `discover.py`.
Manuell: `ssh … '~/daten-li/bin/run-worker.sh'` (dauert ca. 3 Min., Log in `~/daten-li/logs/worker.log`).

**Deploy** (PowerShell, SSH-Key `~\.ssh\bnutt_cyon_ed25519`):

```powershell
.\deploy\deploy.ps1                         # Code + Abhängigkeiten + Crontab, gunicorn neu starten
.\deploy\deploy.ps1 -Htaccess -RunWorker -RunDiscover   # erster Lauf: zusätzlich .htaccess (Backup .htaccess.bak), Datenabruf, Katalog-Discovery
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
