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
| `tab_factbook.py`, `factbook_import.py` | Tab «Factbook» (CIA World Factbook, Archiv 1990–2025, abgeschlossen) und der einmalige Import |
| `tab_quellen.py` | Seite «Datenquellen» (`?tab=quellen`, Link in der Fusszeile jeder Seite): Quellen je Bereich mit Herausgeber, Lizenz, Rhythmus, letztem Abruf; Zustand der Automatik |
| `tab_imf.py`, `imf.py` | Tab «IWF» (World Economic Outlook, DataMapper API) |
| `tab_migration.py`, `migration.py` | Tab «Migration»: Anteile, Liechtenstein im Detail, Wanderung/Einbürgerung/Asyl, Straffälligkeit |
| `tab_police.py`, `police.py` | Tab «Polizeistatistik»: Jahresberichte der Landespolizei (Import/Parser) + Eurostat-Kriminalität nach Staatsangehörigkeit |
| `tab_klima.py`, `climate.py` | Tab «Klimawandel»: ERA5-Langzeitreihen je Gemeinde (Open-Meteo-Archiv), Kennzahlen, Trends |
| `tab_bildung.py`, `bildung.py` | Tab «Bildung»: Schulen, Lernende, Studierende, Staatsbürgerschaft der Schulkinder, Bildungsstand, Bildungsausgaben, PISA 2000–2012 |
| `landesrechnung.py` | Ausgaben des Landes für das Asylwesen (Landesrechnung Konto 590, ab 2009) mit Fundstellen; Tab «Migration» Abschnitt 5; automatische Übernahme neuer Jahre |
| `tab_lohn.py`, `lohn.py` | Tab «Lohn»: Lohnstatistik (Median, Quartile, Lohnunterschied, Branchen, Alter, Wohnsitz, Verteilung), Einordnung Schweiz (BFS) |
| `tab_prognose.py`, `forecast.py` | Tab «Prognosen»: ETS/ARIMA/Theta/Drift mit Rückwärtstest (MASE), 80-/95-%-Bänder, Schwellenrechner, daneben Amt-Szenarien und IWF-Projektionen |
| `tab_korrelation.py`, `correlate.py` | Tab «Korrelations-Labor»: Reihenkatalog (~120 Jahresreihen), Pearson/Spearman, Transformationen, Zeitverschiebung, Hypothesen-Galerie |
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
`factbook_import.py` (einmalig, **abgeschlossen**, nichts nachzuführen; `deploy.ps1 -ImportFactbook`, kein Cron) lädt die SQL-Dumps des Archiv-Datenbestands
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
- **Straffälligkeit:** steht im Tab «Polizeistatistik» (Verweis im Tab «Migration»).
- **Ausgaben je Migrant:** bewusst keine Zahlen — Eurostat/OECD/Liechtenstein liefern keine belastbare, vergleichbare Statistik (Begründung im Tab).
- **Datenhaltung:** Worker spiegelt die Quellen höchstens wöchentlich (`migration.all_sources()`, Cache-Schlüssel `es:`, `wb:`, `pxs:` in `px_cache`).
  Lizenzen: Eurostat © EU CC BY 4.0, Weltbank/UN DESA CC BY 4.0, Amt für Statistik Namensnennung.
- **Nicht umgesetzt (Quelle fehlt/unzuverlässig):** Rücküberweisungen (Weltbank-Indikator ohne Liechtenstein), Armutsgefährdung nach Geburtsland (ohne Liechtenstein),
  Bildungsabschlüsse nach Herkunft (LI nur Volkszählung 2020, andere Länder nicht vergleichbar aufbereitet).

## Automatische Nachführung (nichts von Hand)

Der tägliche Worker (`worker.py`, Cron 06:00 UTC) führt alles nach; der Zustand steht in der Tabelle `auto_status` und auf der Seite «Datenquellen» (Fusszeile).

| Was | Wann | Übernahme | Wenn die Prüfung nicht besteht |
|---|---|---|---|
| Weltbank, Eurostat, OSM, IWF, Amt für Statistik, BFS, Katalogdateien | täglich (Explorer-Cache höchstens 7 Tage, Lohn/Bildung/Migration wöchentlich) | sofort | alter Stand bleibt, Fehler im Log |
| Klimaarchiv ERA5 (11 Gemeinden, 1950–) | täglich, bis zu 24 Abschnitte; bei HTTP 429/Tageslimit Abbruch, am nächsten Tag weiter; danach ab 15. Januar das neue Jahr (11 Abrufe) | sofort | – |
| Polizei-Jahresberichte | monatlich (bei offener Prüfung wöchentlich), `police.auto_update()` | nur wenn alle Kernkennzahlen (`CORE_METRICS`) gefunden, ≥ 75 % der üblichen Kennzahlenzahl, keine Plausibilitäts-Markierung und kein Widerspruch zu den Vorjahreswerten | **nichts** wird in `police_metrics` geschrieben; `police_reports.error = «wartet auf Prüfung: …»`, sichtbar im Tab unter «Abdeckung», PDF bleibt im Archiv; Freigabe: `~/daten-li/bin/run-police-import.sh` (Gesamtimport, Markierungen sichtbar). Bestehende Jahre werden nie verändert |
| Landesrechnung Konto 590 | täglich ab 1. März des Folgejahres (bei offener Prüfung wöchentlich), `landesrechnung.auto_update()`: Berichtsseite auf llv.li → PDF «IV. Landesrechnung» → Konto 590 samt Teilkonten | nur wenn Teilkonten = Total (±2 CHF), Vorjahresspalte = bereits geprüfte Vorjahreswerte, Berichtsjahr im Spaltenkopf stimmt und die gedruckte Seitenzahl lesbar ist; Ablage in `lr_asyl` mit Dokument/Seite/SHA-256 (die Konstante `ROWS` hat Vorrang und wird nie überschrieben) | Zeile mit `status = hold` (nicht veröffentlicht), Hinweis «Neues Jahr wartet auf Prüfung» im Tab «Migration» und auf «Datenquellen»; Freigabe nach Sichtprüfung: `python -c "import landesrechnung as L; L.approve(2026)"` |
| Projektionen | wöchentlich | sofort | alter Stand |
| opendata.li Discovery | sonntags 05:30 UTC | **nur Meldungen**, nichts wird automatisch veröffentlicht | – |
| CIA World Factbook (Archiv) | **abgeschlossen** (Factbook eingestellt am 4. Feb. 2026) | – | – |

Grenzen der Automatik (bleibt bewusst von Hand): die Investitionsrechnung der Landesrechnung (`INVEST`, Konto 590.503.00), neue Definitionshinweise (`DEF_NOTES`/Erklärkästen), neue
Hypothesen der Galerie im Korrelations-Labor, Freigabe bei Prüfung «hold». Ändert die Regierung das Layout der Landesrechnung oder die Polizei den Berichtsaufbau, liest die Automatik
nichts oder markiert es, sie schreibt nichts Falsches: dann den Parser (`landesrechnung.parse_konto590`, `police.parse_report`) anpassen. Die Abrufe nutzen einen ASCII-User-Agent
(`llv.li` lehnt Header mit Umlauten ab), prüfen `robots.txt` und halten 2 s Pause.

## Polizeistatistik (Tab «Polizeistatistik»)

- **Landespolizei Liechtenstein:** `police.py` (Erstimport `deploy.ps1 -ImportPolice`; neue Jahresberichte holt der Worker monatlich selbst, siehe «Automatische Nachführung») lädt die öffentlichen Jahresberichte ab 2009 (17 bis 2025) von
  [landespolizei.li/ueber-uns/jahresberichte](https://www.landespolizei.li/ueber-uns/jahresberichte) (robots.txt erlaubt es; 2 s Pause, ein Request je PDF),
  legt sie unter `~/daten-li/data/archive/police/` ab (+ `manifest.json` mit URL/SHA-256) und liest per `pypdf` Kennzahlen aus dem Text: Straftatbestände StGB,
  Aufklärungsrate, Tatverdächtige (gesamt, Anteil Liechtensteiner/Ausländer, minderjährig), Deliktsgruppen, Verkehrsunfälle/Verletzte/Tote, Untersuchungshaften
  (Herkunft/Wohnsitz), Notrufe/Einsätze LNEZ. **Jeder Wert speichert Seite und Textausschnitt** (`police_metrics`; im Tab «Beleg je Wert» einsehbar).
  Querprüfung: nennt ein Bericht den Vorjahreswert, muss er zum Wert im Vorjahresbericht passen, sonst `flag` (hohler Marker im Diagramm).
  Lücken bleiben Lücken (keine Schätzungen); Tab «Abdeckung» zeigt je Jahr/Kennzahl, was gefunden wurde.
- **Definitionswechsel (belegt aus den Berichten):** Aufklärungsquote 2009/2010 «ohne Wirtschafts-/Betäubungsmitteldelikte» (38 %), ab Bericht 2017 ausdrücklich
  StGB + BMG, 2011–2013 nicht im Text, 2014–2016 Basis nicht beschrieben; Notrufe «Notrufe» (bis 2013) vs. «Meldungen» (ab 2018); Verkehrsunfälle ab 2024 nur noch im
  Fliesstext. Reihen werden nicht über solche Brüche verbunden.
- **Eurostat-Ländervergleich** (aus dem Tab «Migration» verschoben): `crim_just_ctz`, Raten je Gruppe, Methodikkasten; Vergleich nur innerhalb eines Landes, kein Ranking.
- Lizenz Landespolizei: öffentlich zugängliche amtliche Publikation ohne ausdrückliche Lizenzangabe → nur Kennzahlen mit Quellen-/Seitenangabe, keine Textübernahme.

## Klimawandel je Gemeinde (Tab «Klimawandel»)

- **Daten:** Open-Meteo Historical Weather API, Modell ERA5 (ECMWF/Copernicus; CC BY 4.0), tägliche Werte ab 1950 (Tmean/Tmax/Tmin, Niederschlag, Schneefall) für die
  Koordinaten der 11 Gemeinden. `climate.py`: Ladung in 5-Jahres-Abschnitten (176 Abrufe; Erstladung am 27.10.2026 01:17 UTC abgeschlossen). Den Rest macht der tägliche Worker
  selbst (`climate.auto_update`: bis 24 Abschnitte je Lauf, 15 s Pause, bei HTTP 429/Tageslimit Abbruch und Fortsetzung am nächsten Tag; ab 15. Januar das neue Jahr). Das Skript
  `~/daten-li/bin/run-climate-import.sh` (wartet bei 429 geduldig) ist nur noch ein Notbehelf.
  Rohantworten: `~/daten-li/data/archive/climate/<gemeinde>_<von>-<bis>.json.gz`; Tageswerte komprimiert in `clim_daily`, Jahreskennzahlen in `clim_annual`.
- **Auswertung:** Warming Stripes (Abweichung vom Mittel 1991–2020 je Gemeinde), Hitze-/Sommer-/Frost-/Eis-/Schneefall-/Starkregentage, Jahresniederschlag/-schnee,
  Trends nach Theil-Sen mit Mann-Kendall-Test (eigene numpy-Implementierung), Talgemeinden (< 600 m) vs. Berggemeinden (Triesenberg, Planken).
- **Auflösung ehrlich gekennzeichnet:** ERA5 ≈ 25–30 km Raster; Open-Meteo liefert die Höhe seines Höhenmodells am Punkt (z. B. Triesenberg 1042 m statt 884 m) und die Temperaturen
  unterscheiden sich im Mass der Höhenunterschiede (≈ 5–6 K/km) → Höhenkorrektur der Temperatur durch Open-Meteo wahrscheinlich; Niederschlag/Schnee als Rasterwerte. Wir korrigieren nicht nach,
  zeigen aber die Rasterpunkt-Höhe in der Trendtabelle.

## Korrelations-Labor (Tab «Korrelations-Labor»)

- **Reihen:** Jahreswerte aus der SQLite-DB (Weltbank, Eurostat-Tourismus, IWF-Ist-Werte, Factbook je Bezugsjahr, Amt für Statistik: Bevölkerung/Wohnen/Migration/Arbeitslosigkeit,
  Eurostat-Migration, Landespolizei, ERA5-Klima je Gemeinde); Projektionen (IWF ≥ 2026) werden nie korreliert. Nichts wird live abgerufen; die Berechnung (n ≤ ~80) ist
  in Millisekunden erledigt (`correlate.py`: numpy/pandas, p-Werte über die regularisierte unvollständige Betafunktion, 95-%-KI über Fisher-z, kein SciPy nötig).
- **Funktionen:** Pearson und Spearman (r, p, KI, n), Transformationen (Niveau, Δ, %, Trend entfernt), Zeitverschiebung ±8 Jahre mit Lag-Scan, Streudiagramm + Zeitreihe mit zwei
  Achsen, Tabelle aller Transformationen (Scheinkorrelations-Check), teilbarer Link (`?tab=korrelation&ka=<A>&kb=<B>&kh=<Transformation>&kl=<Lag>`).
- **Warnschilder:** n < 15, gemeinsamer Trend (Mann-Kendall beider Reihen), viele getestete Paare/Verschiebungen, keine Kausalität; Autokorrelation macht p-Werte optimistisch.
- **Hypothesen-Galerie:** kuratierte Fragen mit «warum plausibel» und «dagegen spricht» — als Hypothese gekennzeichnet, kein Beleg. Monatswerte werden nicht angeboten (fast alle Daten sind jährlich).

## Prognosen (Tab «Prognosen»)

Transparente Projektionen — «Projektion, keine Vorhersage». `forecast.py` rechnet im Worker (höchstens wöchentlich; statsmodels wird nur dort importiert, die App liest `fc_results`):

- **Reihen**: Wohnbevölkerung (Amt für Statistik), Bevölkerung (Weltbank), Wohnungsbestand, Übernachtungen, Ankünfte, BIP, BIP pro Kopf, Jahrestemperatur Vaduz (ERA5, sobald Klimadaten geladen sind).
- **Methoden**: Naive Basis, Drift, ETS, ARIMA (kleine Ordnungsauswahl nach AICc), Theta; Intervalle 80 %/95 %.
- **Rückwärtstest** (rolling origin ab 60 % der Reihe, Horizont 1–3 Jahre): MASE gegen die naive Basis, Abdeckung der Bänder. **Keine Projektion** (mit Begründung), wenn < 15 aufeinanderfolgende Jahre vorliegen, keine Methode die naive Basis um ≥ 5 % schlägt oder die beste Methode MASE > 2 hat.
- **Schwellenrechner** («Wann erreicht Liechtenstein X Einwohner?») mit Jahr der zentralen Projektion und 80-%-Bereich (punktweise Wahrscheinlichkeit je Jahr).
- **Getrennt daneben**: Bevölkerungsszenarien des Amts für Statistik (`pxs:li_scen`, 9 Szenarien bis 2060) und IWF-WEO-Projektionen; nie in die eigene Projektion eingerechnet.
- Manuell neu rechnen: `python forecast.py` (im App-Verzeichnis, venv aktiv).

## Bildung (Tab «Bildung»)

`bildung.py` spiegelt (Worker, höchstens wöchentlich, Cache-Schlüssel `edu:<Name>` in `px_cache`) und `tab_bildung.py` zeigt:

- **Amt für Statistik (PXWeb/opendata.li, CC BY):** Schulkinder nach Schultyp/Schulstufe (481.001), nach Staatsbürgerschaft (481.002), Klassengrösse (481.003), Abschlüsse Sekundarstufe II (481.101),
  Schulpersonal in VZÄ (481.202), Studierende an Hochschulen in FL (482.007), Lernende (483.011), Bildungsstand der Bevölkerung (491.002d), Staatsausgaben für das Bildungswesen (COFOG 9, 501.031).
- **PISA** (OECD, Mittelwerte Lesen/Mathematik/Naturwissenschaften) über die Weltbank-Datenbank EdStats (`LO.PISA.*`, API-Quelle 12, Stand 2024-06-25) für Liechtenstein, Schweiz, Österreich, Deutschland.
  Liechtenstein hat nur 2000, 2003, 2006, 2009 und 2012 teilgenommen (OECD-Länderseite); seit 2015 nicht mehr.
- **Lücken** (im Tab unter «Was nicht verfügbar ist» aufgeführt): kein PISA nach 2012, kein OECD-Durchschnitt je Erhebung (keine einheitliche maschinenlesbare Reihe), kein Migrationshintergrund
  (nur Staatsbürgerschaft), keine Abschlussquote, keine Bildungsausgaben nach Stufe (Eurostat `educ_uoe_fine*` ist für LI leer).
- Korrelations-Labor: Bildungsreihen (`edu|…`) und PISA (`pisa|LIE|…`) im Katalog; PISA gegen den Anteil Schulkinder ohne LI-Staatsbürgerschaft als Hypothese mit Warnhinweisen (nur 3 gemeinsame Jahre).

## Asylwesen-Kosten (Tab «Migration», Abschnitt 5)

`landesrechnung.py` enthält die Ausgaben des Landes auf Konto 590 «Flüchtlingswesen» der Landesrechnung (Erfolgsrechnung), Rechnungsjahre 2009–2025:
Betreuung Aufnahmezentrum, Verfahrenskosten, Rechtsberatungen/Verwaltungskosten der Hilfswerke, Sozialhilfe für Asylsuchende / Rückkehrhilfe (Aufwand brutto) und Rückerstattungen
Lohnverwaltung (Ertrag; netto = brutto − Ertrag). Es gibt keine maschinenlesbare Reihe: die Werte sind aus den Rechenschaftsberichten (Teil IV Landesrechnung; llv.li und bua.regierung.li) übertragen,
je Jahr mit Dokument und Seite (`SOURCES`), gegen die Vorjahresspalte des Folgeberichts und die Summe der Teilkonten geprüft (`landesrechnung.check()` muss `[]` liefern).
Neues Rechnungsjahr: Zeile in `ROWS` und `SOURCES` ergänzen (Konto 590 im Kapitel «Konten der Erfolgsrechnung»), `check()` laufen lassen.

- Näherungswerte je Person: Aufwand netto / Mittel aus Bestand Vorjahres- und Jahresende (`landesrechnung.per_capita`), zusätzlich mit Jahresend-Bestand und je Einwohner (Wohnbevölkerung 211.002);
  im Tab mit Hinweiskasten (nur Konto 590, Stichtag vs. Jahreswert, Sprung 2022). Keine Aufteilung nach Status möglich (Kostenseite hat keine).
- Daneben der Bestand Asylbewerber/vorläufig Aufgenommene/Schutzbedürftige (Amt für Statistik 233.302, `pxs:li_asyl_stock`).
- Bewusst **keine** Kosten je Gesuch (Verfahren dauern mehrjährig; Aufwand folgt dem Bestand) und keine Aufteilung nach Herkunft (in der Landesrechnung nicht vorhanden).
- Nicht enthalten: Personal-/Sachaufwand der Ämter, Leistungen ausserhalb Konto 590, Gemeinden, Hilfe im Ausland (Konto 591.367.09). Investitionsrechnung (590.503.00 «Wohnraum für Schutzbedürftige», 2023–2025) getrennt ausgewiesen.
- Korrelations-Labor: Reihen `li|asyl_aufwand`, `li|asyl_netto`, `li|asyl_bestand`; zwei Hypothesen mit Warnhinweisen.

## Lohn (Tab «Lohn»)

`lohn.py` spiegelt (Worker, höchstens wöchentlich, Cache-Schlüssel `lohn:<Name>` in `px_cache`) und `tab_lohn.py` zeigt die **Lohnstatistik des Amts für Statistik** (PXWeb/opendata.li, CC BY):
Tabellen 291.001 (nach Wirtschaftszweig, Wohnsitz, Voll-/Teilzeit, Geschlecht), 291.002 (Staatsbürgerschaft), 291.011 (Unternehmensgrösse), 291.022 (Alter), 291.031 (Aufenthaltsstatus),
291.041 (Wohnort), 291.081 (Häufigkeitsverteilung); monatlicher Bruttolohn, Median und 1./3. Quartil, Berichtsjahre 2006–2024 alle zwei Jahre, auf Vollzeit (100 %) hochgerechnet.
Dazu der Zentralwert der Schweiz (BFS Lohnstrukturerhebung, PXWeb-API `px-x-0304010000_201`) als Einordnung und der Schweizer Konsumentenpreisindex (Weltbank `FP.CPI.TOTL`) als Deflator für «reale Löhne» (Näherung).
- **Lücken** (im Tab unter «Was nicht verfügbar ist»): keine Ausbildung/Anforderungsniveau/berufliche Stellung (Verwaltungsdaten), keine Stundenlöhne, kein Durchschnittslohn, kein bereinigter Lohnunterschied,
  kein liechtensteinischer Preisindex, keine Zwischenjahre, kein EU-Vergleich.
- Korrelations-Labor: Reihen `lohn|…` (Median gesamt/Frauen/Männer, Lohnunterschied, real, Zupendler, Liechtensteiner/Ausländer, Schweiz) und drei Hypothesen mit Warnhinweisen (nur gerade Jahre, n ≤ 10).

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
Manuell: `ssh … '~/daten-li/bin/run-worker.sh'` (dauert ca. 3 Min., Log in `~/daten-li/logs/worker.log`). Was der Worker nachführt und was nicht: Abschnitt «Automatische Nachführung».

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
