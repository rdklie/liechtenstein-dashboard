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
| `tab_factbook.py`, `factbook_import.py` | Tab «Factbook» (CIA World Factbook, Archiv 1990–2025) und der einmalige Import |
| `tab_imf.py`, `imf.py` | Tab «IWF» (World Economic Outlook, DataMapper API) |
| `tab_migration.py`, `migration.py` | Tab «Migration»: Anteile, Liechtenstein im Detail, Wanderung/Einbürgerung/Asyl, Straffälligkeit |
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
- **Amtsstelle (Herausgeber):** Der Katalog führt je Datensatz einen Herausgeber (`dct:publisher`, Organisationen als `foaf:Organization`):
  Amt für Statistik 464, Amt für Tiefbau und Geoinformation 25, Finanzmarktaufsicht Liechtenstein 6 (Amt für Hochbau und Raumplanung ist als
  Organisation geführt, hat aber keine Datensätze). Fehlt er, wird die Amtsstelle aus dem Katalog-Bereich (EntryStore-Context) abgeleitet
  und in `od_catalog.publisher_source` als «abgeleitet» markiert; sonst «Nicht zuordenbar» (aktuell keine). 31 Katalogeinträge sind leer
  (ohne Titel/Metadaten) und werden übersprungen. Der Filter (Amtsstelle · Art · Thema · Suche) gilt für Explorer-Dropdown und Trefferliste,
  auch für Geodaten/Dateien. Geodaten (WMS/ZIP) sind nur verlinkt.
- **CSV/JSON-Dateien aus dem Katalog** (z. B. die 6 FMA-Datensätze) liest `opendata.fetch_file()` generisch: Kodierung und Trennzeichen werden erkannt,
  JSON als Liste von Datensätzen (auch GeoJSON-Properties, `{Spalte: [..]}`), Zahlenspalten zu «Wert» (mehrere → «Kennzahl»/«Wert»). Grenzen: 8 MB,
  200 000 Zeilen, 60 Spalten, ≥ 2 Zeilen; ungültige Dateien werden im Explorer mit einer verständlichen Meldung gemeldet. Cache wie bei PX in `px_cache`
  (Schlüssel `file:<URL>`), Worker-Refresh höchstens wöchentlich.
- **Discovery:** `discover.py` (Cron sonntags 05:30 UTC, manuell `~/daten-li/bin/run-discover.sh`) liest Katalog und PXWeb-Baum, vergleicht
  mit dem letzten Stand (`od_catalog`) und meldet neu/geändert/entfernt/«PX-Tabelle nicht im Katalog» in `od_discovery_log`,
  `~/daten-li/data/discovery-report.md` und im Tab «Open Data». Er veröffentlicht nichts automatisch.
- **Rücksicht auf die APIs:** ≥ 0,4 s Pause je Request, Retries mit Backoff, grosse Tabellen werden auf ≤ 40 000 Zellen reduziert;
  die App ruft die APIs nur beim Explorer-Livezugriff auf.

## World Factbook (Archiv)

Das CIA World Factbook wurde am 4. Feb. 2026 eingestellt (cia.gov leitet nur noch auf eine Abschiedsseite). Der Tab «Factbook» zeigt Liechtenstein
über alle 36 Ausgaben 1990–2025: Kennzahlen als Zeitreihen (nach Bezugsjahr oder nach Ausgabe) und eine Text-Chronik je Feld.
`factbook_import.py` (einmalig, `deploy.ps1 -ImportFactbook`, kein Cron) lädt die SQL-Dumps des Archiv-Datenbestands
[MilkMp/CIA-World-Factbooks-Archive-1990-2025](https://github.com/MilkMp/CIA-World-Factbooks-Archive-1990-2025) (MIT; die Daten sind gemeinfrei) von GitHub,
filtert Liechtenstein (FIPS `ls`), legt die Rohdaten als `~/daten-li/data/archive/factbook/liechtenstein_<Jahr>.json` + `manifest.json` (URLs, SHA-256) ab
und schreibt `factbook_fields` (Rohtext) und `factbook_values` (geparste Kennzahlen mit Ausgabe- und Bezugsjahr) nach SQLite.
`worldfactbookarchive.org` selbst wird nicht abgerufen: die robots.txt der Seite sperrt KI-Crawler (u. a. `anthropic-ai`, `claudebot`).
Parser-Grenzen: Bezugsjahre stehen im Text (z. B. «(2024 est.)») und liegen oft vor dem Ausgabejahr; Definitionen wechseln (ab 2021 «Real GDP», Preise 2015).

## IWF (World Economic Outlook, SDMX-API)

Liechtenstein ist seit dem 21. Oktober 2024 IWF-Mitglied (191. Mitglied; Quelle: [IWF-Länderseite](https://www.imf.org/en/countries/lie)).
- **DataMapper** (`imf.py`, `/api/v1/<Indikator>/LIE`): 15 von 132 Indikatoren haben Werte für Liechtenstein (BIP, BIP/Kopf, Wachstum, Inflation,
  Arbeitslosigkeit, Leistungsbilanz, Staatshaushalt/-schulden, Bevölkerung; 2000–2031, ab dem Ausgabejahr Projektionen). Nach dem Beitritt unverändert (Prüfung 26.10.2026).
  Der Worker aktualisiert höchstens wöchentlich (15 Abrufe, 1 s Pause) → Tab «IWF».
- **SDMX-API** (`api.imf.org/external/sdmx/2.1`, SDMX-JSON): von 102 aktuellen Datenflüssen liefern 15 Reihen mit Werten für `LIE` (WEO mit 33 Reihen, FSI/Financial Soundness
  Indicators, Wechselkurse, Treibhausgase, WoRLD-Staatseinnahmen, FAS, Klimaindikatoren, Gender Statistics, DIP/PIP-Gegenparteipositionen u. a.; `imf.SDMX_FLOWS`; ANEA hat nur leere Reihen).
  Sie erscheinen im Tab «Open Data» als Art «IWF-Datenfluss» und werden vom Worker höchstens wöchentlich gespiegelt (`px_cache`, Schlüssel `imf:<Agentur/Fluss/Version>`).
  Nicht dabei: IFS/CPI/BOP/GFS-Länderdatenflüsse (Abfrage liefert keine Reihen für Liechtenstein).
- `discover.py` prüft wöchentlich beide Wege auf neue Indikatoren/Datenflüsse (`iwf-neuer-indikator`, `iwf-neuer-datenfluss`) — es wird nichts automatisch eingebunden.
- Quelle/Lizenz: International Monetary Fund — Quellenangabe, nicht-kommerzielle Nutzung ([Bedingungen](https://www.imf.org/en/About/Copyright-and-Terms)); keine
  automatisierten Massendownloads, kein LLM-Training.

## Migration (Tab «Migration»)

Sachlich und quellenbasiert; zu jeder Kennzahl Definition, Quelle, Lizenz und Stand (Kasten «Wie lesen?», Hinweise direkt an den Diagrammen).
- **Anteil an der Bevölkerung** (Länder wählbar: EU27, EFTA, USA/China/Russland; Gruppenwerte EU27, EWR, D-A-CH-L): drei getrennte Kennzahlen —
  ausländische Staatsangehörige (Eurostat `migr_pop1ctz`, = Total − Staatsangehörige des Berichtslands), im Ausland Geborene (`migr_pop3ctb`) und
  internationaler Migrantenbestand (UN DESA über Weltbank `SM.POP.TOTL.ZS`, alle Länder, nur alle 5 Jahre). USA/China/Russland haben nur die UN-Reihe,
  bei Eurostat-Kennzahlen steht «keine Daten». Gruppenwert = Σ Betroffene / Σ Bevölkerung der Länder mit Daten (bevölkerungsgewichtet).
- **Liechtenstein amtlich** (PXWeb 211.002/211.101/211.006/281.005): Wohnbevölkerung nach Staatsangehörigkeit, Herkunft, Gemeinden, Altersstruktur,
  Grenzgänger (Beschäftigte mit Wohnland Ausland) getrennt; Diagramm «vier Definitionen» erklärt die Abweichung (Amt 35 % Ausländer vs. rund 70 % im Ausland
  Geborene/UN-Migrantenbestand).
- **Wanderung, Einbürgerung, Asyl, Arbeitsmarkt:** LI PX 231.101/232.001/233.201/284.101; Eurostat `migr_acq` (je 100 ausländische Einwohner),
  `migr_asyappctza` (je 100 000 Einwohner). Eurostat `lfsa_urgacob` und `ilc_li32` (Geburtsland) haben für LI keine Werte und werden nicht gezeigt.
- **Straffälligkeit:** Eurostat `crim_just_ctz` (Verdächtige/Strafverfolgte/Verurteilte; Inland/Ausland), Raten je Gruppe selbst berechnet (Eurostat selbst
  bezieht «je 100 000» auf die Gesamtbevölkerung). Mit methodischen Hinweisen (Nichtansässige im Zähler, Alter/Geschlecht, Anzeigeverhalten, Definitionen).
  Liechtenstein weist Nationalität aus: Landespolizei-Jahresbericht 2021 (S. 22, 34); das Amt für Statistik hat keine Kriminalitätstabelle.
- **Ausgaben je Migrant:** bewusst keine Zahlen — Eurostat/OECD/Liechtenstein liefern keine belastbare, vergleichbare Statistik (Begründung im Tab).
- **Datenhaltung:** Worker spiegelt die Quellen höchstens wöchentlich (`migration.all_sources()`, Cache-Schlüssel `es:`, `wb:`, `pxs:` in `px_cache`).
  Lizenzen: Eurostat © EU CC BY 4.0, Weltbank/UN DESA CC BY 4.0, Amt für Statistik Namensnennung.
- **Nicht umgesetzt (Quelle fehlt/unzuverlässig):** Rücküberweisungen (Weltbank-Indikator ohne Liechtenstein), Armutsgefährdung nach Geburtsland (ohne Liechtenstein),
  Bildungsabschlüsse nach Herkunft (LI nur Volkszählung 2020, andere Länder nicht vergleichbar aufbereitet).

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
