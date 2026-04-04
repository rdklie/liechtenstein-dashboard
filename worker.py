"""
worker.py — Datenfetcher-Job für das Liechtenstein Dashboard
=============================================================
Wird auf Render als Cron Job täglich ausgeführt.
Holt Daten von allen externen APIs und speichert sie in der PostgreSQL-DB.

Lokal ausführen:
    DATABASE_URL=postgresql://... python worker.py
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

    # ── Klimadaten (alle Gemeinden × letzte 6 Jahre) ──────────────────────────
    from data_fetcher import MUNICIPALITIES, fetch_weather_monthly
    current_year = datetime.utcnow().year
    weather_years = list(range(current_year - 5, current_year + 1))
    log.info("--- Klimadaten (%d Gemeinden × %d Jahre) ---",
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
