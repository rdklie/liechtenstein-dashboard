"""
worker.py — Datenfetcher-Job für das Liechtenstein Dashboard
=============================================================
Läuft täglich als Cron Job (auf cyon: 06:00 UTC, siehe deploy/).
Holt Daten von allen externen APIs und speichert sie in der SQLite-DB.

Lokal ausführen:
    SQLITE_PATH=/pfad/zur/db.sqlite python worker.py
"""

import logging
import sys
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)


def run():
    log.info("=" * 60)
    log.info("Liechtenstein Dashboard — Datenfetcher gestartet")
    log.info("Zeitpunkt: %s", datetime.utcnow().isoformat())
    log.info("=" * 60)

    # DB initialisieren (Tabellen anlegen falls nötig)
    import db
    import opendata
    db.init_db()

    errors = []

    # ── World Bank Indikatoren ────────────────────────────────────────────────
    from data_fetcher import WB_INDICATORS, fetch_world_bank
    log.info("--- World Bank (%d Indikatoren) ---", len(WB_INDICATORS))
    for indicator in WB_INDICATORS:
        try:
            df = fetch_world_bank(indicator)
            if not df.empty:
                db.write_world_bank(df, indicator)
                log.info("  ✓ %s (%d Datenpunkte)", indicator, len(df))
            else:
                log.warning("  ✗ %s — keine Daten", indicator)
        except Exception as e:
            log.error("  ✗ %s — Fehler: %s", indicator, e)
            errors.append(f"World Bank {indicator}: {e}")

    # ── Klimadaten (alle Gemeinden × letzte 5 abgeschlossene Jahre) ─────────────
    # Nur abgeschlossene Jahre fetchen — laufendes Jahr (2026) ist noch unvollständig
    # und hat ein erhöhtes Rate-Limit-Risiko bei der Open-Meteo Archive API.
    # Zwischen jedem Request 1.5s Pause um 429-Fehler zu vermeiden (66 Requests total).
    import time as _time
    from data_fetcher import MUNICIPALITIES, fetch_weather_monthly
    current_year = datetime.utcnow().year
    weather_years = list(range(current_year - 5, current_year))  # nur abgeschlossene Jahre
    log.info("--- Klimadaten (%d Gemeinden × %d Jahre, je 1.5s Pause) ---",
             len(MUNICIPALITIES), len(weather_years))
    for key, info in MUNICIPALITIES.items():
        for year in weather_years:
            try:
                df = fetch_weather_monthly(year, lat=info["lat"], lon=info["lon"])
                if not df.empty:
                    db.write_weather_monthly(df, key, year)
                    log.info("  ✓ %s %d", info["name"], year)
                else:
                    log.warning("  ✗ %s %d — keine Daten", info["name"], year)
            except Exception as e:
                log.error("  ✗ %s %d — Fehler: %s", info["name"], year, e)
                errors.append(f"Wetter {key} {year}: {e}")
            _time.sleep(1.5)  # Rate-Limit Open-Meteo: max ~1 Req/s

    # ── Eurostat — Tourismus Ankünfte ─────────────────────────────────────────
    log.info("--- Eurostat Tourismus ---")
    try:
        from data_fetcher import fetch_eurostat_tourism
        df = fetch_eurostat_tourism()
        if not df.empty:
            db.write_eurostat_tourism(df)
            log.info("  ✓ Ankünfte (%d Datenpunkte)", len(df))
        else:
            log.warning("  ✗ Ankünfte — keine Daten")
    except Exception as e:
        log.error("  ✗ Ankünfte — Fehler: %s", e)
        errors.append(f"Eurostat Tourismus: {e}")

    # ── Eurostat — Übernachtungen ─────────────────────────────────────────────
    try:
        from data_fetcher import fetch_eurostat_tourism_nights
        df = fetch_eurostat_tourism_nights()
        if not df.empty:
            db.write_eurostat_tourism_nights(df)
            log.info("  ✓ Übernachtungen (%d Datenpunkte)", len(df))
        else:
            log.warning("  ✗ Übernachtungen — keine Daten")
    except Exception as e:
        log.error("  ✗ Übernachtungen — Fehler: %s", e)
        errors.append(f"Eurostat Nächte: {e}")

    # ── Eurostat — BIP EUR ────────────────────────────────────────────────────
    try:
        from data_fetcher import fetch_eurostat_gdp_eur
        df = fetch_eurostat_gdp_eur()
        if not df.empty:
            db.write_eurostat_gdp_eur(df)
            log.info("  ✓ BIP EUR (%d Datenpunkte)", len(df))
        else:
            log.warning("  ✗ BIP EUR — keine Daten")
    except Exception as e:
        log.error("  ✗ BIP EUR — Fehler: %s", e)
        errors.append(f"Eurostat GDP: {e}")

    # ── OpenStreetMap POI ─────────────────────────────────────────────────────
    log.info("--- OpenStreetMap POI ---")
    try:
        from data_fetcher import fetch_osm_poi_counts
        counts = fetch_osm_poi_counts()
        if counts:
            db.write_osm_poi_counts(counts)
            log.info("  ✓ %d Kategorien", len(counts))
        else:
            log.warning("  ✗ OSM — keine Daten")
    except Exception as e:
        log.error("  ✗ OSM — Fehler: %s", e)
        errors.append(f"OSM POI: {e}")

    # ── Open Data (Amt für Statistik, PXWeb) — Wohnen & Immobilien ─────────────
    # Pro Tabelle 1 GET (Metadaten) + 1 POST; PAUSE in opendata.py schont die API.
    log.info("--- Open Data / PXWeb (%d Tabellen) ---", len(opendata.CURATED))
    for key, path in opendata.CURATED.items():
        try:
            df, info = opendata.px_fetch(path)
            if not df.empty:
                db.write_px_cache(path, df, info)
                log.info("  ✓ %s (%d Zeilen)", key, len(df))
            else:
                log.warning("  ✗ %s — keine Daten", key)
        except Exception as e:
            log.error("  ✗ %s — Fehler: %s", key, e)
            errors.append(f"PX {key}: {e}")
        _time.sleep(1)

    # ── IWF (World Economic Outlook, DataMapper) — höchstens wöchentlich ─────────
    import imf
    src, last = db.read_imf_info()
    if last is not None and (datetime.utcnow() - last).days < imf.REFRESH_DAYS:
        log.info("--- IWF: Daten sind %d Tage alt, übersprungen ---", (datetime.utcnow() - last).days)
    else:
        log.info("--- IWF / WEO (%d Indikatoren) ---", len(imf.INDICATORS))
        for code, (label, unit) in imf.INDICATORS.items():
            try:
                df = imf.fetch_indicator(code)
                if not df.empty:
                    db.write_imf(df, code)
                    log.info("  ✓ %s (%d Werte)", label, len(df))
                else:
                    log.warning("  ✗ %s — keine Daten", label)
            except Exception as e:
                log.error("  ✗ %s — Fehler: %s", label, e)
                errors.append(f"IWF {code}: {e}")
            _time.sleep(imf.PAUSE)
        try:
            db.write_imf_meta("WEO", imf.fetch_meta("NGDPD")["source"])
        except Exception as e:
            log.warning("IWF-Meta nicht lesbar: %s", e)

    # ── Explorer-Quellen: CSV/JSON-Dateien aus dem Katalog + IWF-SDMX-Datenflüsse (höchstens wöchentlich) ──
    import imf
    cat = db.read_catalog()
    targets = [(f"IWF {fid.split('/')[1]}", imf.SDMX_PREFIX + fid) for fid in imf.SDMX_FLOWS]
    if not cat.empty and "data_url" in cat.columns:
        for r in cat[cat["data_url"].fillna("") != ""].itertuples():
            targets.append((r.title, opendata.FILE_PREFIX + r.data_url))
    log.info("--- Explorer-Quellen (%d, Cache max. 7 Tage) ---", len(targets))
    for label, path in targets:
        try:
            state = db.refresh_source(path)
            log.info("  %s %s", "✓" if state == "aktualisiert" else "·", f"{label} ({state})")
            if state == "aktualisiert":
                _time.sleep(1)
        except Exception as e:
            log.error("  ✗ %s — Fehler: %s", label, e)
            errors.append(f"Explorer {label}: {e}")

    # ── Zusammenfassung ───────────────────────────────────────────────────────
    log.info("=" * 60)
    if errors:
        log.warning("Job abgeschlossen mit %d Fehler(n):", len(errors))
        for err in errors:
            log.warning("  - %s", err)
        sys.exit(1)
    else:
        log.info("Job erfolgreich abgeschlossen. Alle Daten aktualisiert.")
        log.info("=" * 60)


if __name__ == "__main__":
    run()
