"""
db.py — Datenbankschicht für das Liechtenstein Dashboard
=========================================================
Standard ist eine SQLite-Datei (Pfad aus SQLITE_PATH, sonst data/liechtenstein.sqlite
neben dem Code). Optional kann DATABASE_URL (z. B. PostgreSQL) gesetzt werden und
hat dann Vorrang. Sind noch keine Daten vorhanden, fällt das Dashboard automatisch
auf direkte API-Aufrufe zurück.

Tabellen:
  world_bank_data       — World Bank Indikatoren
  weather_monthly       — Monatliche Klimadaten pro Gemeinde & Jahr
  eurostat_tourism      — Touristische Ankünfte (Eurostat)
  eurostat_tourism_nights — Übernachtungen (Eurostat)
  eurostat_gdp_eur      — BIP in EUR (Eurostat)
  osm_poi_counts        — Points of Interest (OpenStreetMap)
"""

import os
import logging
from datetime import datetime
from functools import lru_cache
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, event, text

log = logging.getLogger(__name__)

DEFAULT_SQLITE_PATH = Path(__file__).resolve().parent / "data" / "liechtenstein.sqlite"

# ── Engine ────────────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _get_engine():
    url = os.environ.get("DATABASE_URL", "")
    try:
        if url:
            # Heroku/Render-Stil postgres:// → postgresql://
            if url.startswith("postgres://"):
                url = url.replace("postgres://", "postgresql://", 1)
            engine = create_engine(url, pool_pre_ping=True)
        else:
            path = Path(os.environ.get("SQLITE_PATH") or DEFAULT_SQLITE_PATH)
            path.parent.mkdir(parents=True, exist_ok=True)
            engine = create_engine(f"sqlite:///{path.as_posix()}",
                                   connect_args={"timeout": 30})

            @event.listens_for(engine, "connect")
            def _sqlite_pragmas(dbapi_conn, _):
                # WAL: Web liest, während der Worker schreibt
                dbapi_conn.execute("PRAGMA journal_mode=WAL")
                dbapi_conn.execute("PRAGMA synchronous=NORMAL")

        _create_tables(engine)
        return engine
    except Exception as e:
        log.error("DB-Engine Fehler: %s", e)
        return None


# ── Schema-Init ───────────────────────────────────────────────────────────────

DDL = """
CREATE TABLE IF NOT EXISTS world_bank_data (
    indicator   TEXT    NOT NULL,
    year        INTEGER NOT NULL,
    value       FLOAT,
    fetched_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (indicator, year)
);

CREATE TABLE IF NOT EXISTS weather_monthly (
    municipality  TEXT    NOT NULL,
    year          INTEGER NOT NULL,
    month         INTEGER NOT NULL,
    month_name    TEXT,
    temp_max      FLOAT,
    temp_min      FLOAT,
    temp_mean     FLOAT,
    precipitation FLOAT,
    wind_max      FLOAT,
    fetched_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (municipality, year, month)
);

CREATE TABLE IF NOT EXISTS eurostat_tourism (
    year        INTEGER PRIMARY KEY,
    value       FLOAT,
    fetched_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS eurostat_tourism_nights (
    year        INTEGER PRIMARY KEY,
    value       FLOAT,
    fetched_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS eurostat_gdp_eur (
    year        INTEGER PRIMARY KEY,
    value       FLOAT,
    fetched_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS osm_poi_counts (
    category    TEXT PRIMARY KEY,
    count       INTEGER,
    fetched_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


def _create_tables(engine):
    with engine.connect() as conn:
        for stmt in DDL.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                conn.execute(text(stmt))
        conn.commit()


def init_db():
    """Erstellt alle Tabellen falls noch nicht vorhanden."""
    if _get_engine() is None:
        log.error("Keine DB-Engine — DB-Init fehlgeschlagen.")
        return
    log.info("DB initialisiert.")


# ── Write-Funktionen (nur vom worker.py verwendet) ────────────────────────────

def _upsert_dataframe(df: pd.DataFrame, table: str, pk_cols: list[str]):
    """Löscht bestehende Zeilen anhand der PK-Spalten und fügt neue ein."""
    engine = _get_engine()
    if engine is None or df.empty:
        return
    df = df.copy()
    df["fetched_at"] = datetime.utcnow()
    # WHERE-Clause für DELETE aus PK-Werten
    where_clauses = " AND ".join(f"{c} = :{c}" for c in pk_cols)
    # Eindeutige PK-Kombinationen
    pk_vals = df[pk_cols].drop_duplicates().to_dict(orient="records")
    with engine.connect() as conn:
        for row in pk_vals:
            conn.execute(text(f"DELETE FROM {table} WHERE {where_clauses}"), row)
        conn.commit()
    df.to_sql(table, engine, if_exists="append", index=False, method="multi")


def write_world_bank(df: pd.DataFrame, indicator: str):
    if df.empty:
        return
    d = df[["year", "value"]].copy()
    d["indicator"] = indicator
    _upsert_dataframe(d, "world_bank_data", ["indicator", "year"])
    log.info("world_bank_data geschrieben: %s (%d Zeilen)", indicator, len(d))


def write_weather_monthly(df: pd.DataFrame, municipality: str, year: int):
    if df.empty:
        return
    cols = ["month", "month_name", "temp_max", "temp_min", "temp_mean",
            "precipitation", "wind_max"]
    avail = [c for c in cols if c in df.columns]
    d = df[avail].copy()
    d["municipality"] = municipality
    d["year"] = year
    _upsert_dataframe(d, "weather_monthly", ["municipality", "year"])
    log.info("weather_monthly geschrieben: %s %d (%d Zeilen)", municipality, year, len(d))


def _write_simple(df: pd.DataFrame, table: str):
    """Für Tabellen mit nur (year, value) — ersetzt den gesamten Inhalt."""
    engine = _get_engine()
    if engine is None or df.empty:
        return
    d = df[["year", "value"]].copy()
    d["fetched_at"] = datetime.utcnow()
    with engine.connect() as conn:
        conn.execute(text(f"DELETE FROM {table}"))
        conn.commit()
    d.to_sql(table, engine, if_exists="append", index=False, method="multi")
    log.info("%s geschrieben (%d Zeilen)", table, len(d))


def write_eurostat_tourism(df: pd.DataFrame):
    _write_simple(df, "eurostat_tourism")


def write_eurostat_tourism_nights(df: pd.DataFrame):
    _write_simple(df, "eurostat_tourism_nights")


def write_eurostat_gdp_eur(df: pd.DataFrame):
    _write_simple(df, "eurostat_gdp_eur")


def write_osm_poi_counts(counts: dict[str, int]):
    engine = _get_engine()
    if engine is None or not counts:
        return
    now = datetime.utcnow()
    rows = [{"category": k, "count": v, "fetched_at": now} for k, v in counts.items()]
    df = pd.DataFrame(rows)
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM osm_poi_counts"))
        conn.commit()
    df.to_sql("osm_poi_counts", engine, if_exists="append", index=False, method="multi")
    log.info("osm_poi_counts geschrieben (%d Kategorien)", len(counts))


# ── Read-Funktionen (nur von app.py verwendet) ────────────────────────────────

def _read(sql: str, params: dict | None = None) -> pd.DataFrame:
    engine = _get_engine()
    if engine is None:
        return pd.DataFrame()
    try:
        with engine.connect() as conn:
            return pd.read_sql_query(text(sql), conn, params=params)
    except Exception as e:
        log.warning("DB-Lesefehler: %s", e)
        return pd.DataFrame()


def read_world_bank(indicator: str) -> pd.DataFrame:
    return _read(
        "SELECT year, value FROM world_bank_data WHERE indicator = :ind ORDER BY year",
        {"ind": indicator},
    )


def read_weather_monthly(municipality: str, year: int) -> pd.DataFrame:
    return _read(
        """SELECT month, month_name, temp_max, temp_min, temp_mean,
                  precipitation, wind_max
           FROM weather_monthly
           WHERE municipality = :muni AND year = :year
           ORDER BY month""",
        {"muni": municipality, "year": year},
    )


def read_eurostat_tourism() -> pd.DataFrame:
    return _read("SELECT year, value FROM eurostat_tourism ORDER BY year")


def read_eurostat_tourism_nights() -> pd.DataFrame:
    return _read("SELECT year, value FROM eurostat_tourism_nights ORDER BY year")


def read_eurostat_gdp_eur() -> pd.DataFrame:
    return _read("SELECT year, value FROM eurostat_gdp_eur ORDER BY year")


def read_osm_poi_counts() -> dict[str, int]:
    df = _read("SELECT category, count FROM osm_poi_counts ORDER BY count DESC")
    if df.empty:
        return {}
    return dict(zip(df["category"], df["count"]))


# ── Wrapper mit Fallback auf direkte API-Aufrufe ──────────────────────────────
# Wenn Daten in der DB vorhanden → DB
# Sonst → direkt API (z. B. vor dem ersten Worker-Lauf)

def get_world_bank(indicator: str) -> pd.DataFrame:
    df = read_world_bank(indicator)
    if not df.empty:
        return df
    from data_fetcher import fetch_world_bank
    return fetch_world_bank(indicator)


def get_weather_monthly(municipality: str, year: int,
                        lat: float | None = None,
                        lon: float | None = None) -> pd.DataFrame:
    df = read_weather_monthly(municipality, year)
    if not df.empty:
        return df
    from data_fetcher import fetch_weather_monthly, MUNICIPALITIES
    info = MUNICIPALITIES.get(municipality, MUNICIPALITIES["vaduz"])
    return fetch_weather_monthly(year, lat=lat or info["lat"], lon=lon or info["lon"])


def get_eurostat_tourism() -> pd.DataFrame:
    df = read_eurostat_tourism()
    if not df.empty:
        return df
    from data_fetcher import fetch_eurostat_tourism
    return fetch_eurostat_tourism()


def get_eurostat_tourism_nights() -> pd.DataFrame:
    df = read_eurostat_tourism_nights()
    if not df.empty:
        return df
    from data_fetcher import fetch_eurostat_tourism_nights
    return fetch_eurostat_tourism_nights()


def get_eurostat_gdp_eur() -> pd.DataFrame:
    df = read_eurostat_gdp_eur()
    if not df.empty:
        return df
    from data_fetcher import fetch_eurostat_gdp_eur
    return fetch_eurostat_gdp_eur()


def get_osm_poi_counts() -> dict[str, int]:
    # Kein Live-Fallback: Overpass braucht über eine Minute (und ist oft nicht
    # erreichbar) — das würde das Rendern der Seite blockieren. Der Worker füllt die DB.
    return read_osm_poi_counts()
