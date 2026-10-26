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
  px_cache              — Tabellen des Amts für Statistik (PXWeb/opendata.li), komprimiert als JSON
  od_catalog            — Katalog von opendata.li (Discovery-Crawler)
  od_discovery_log      — Funde des Discovery-Crawlers (neu/entfernt/geändert)
"""

import base64
import json
import os
import logging
import zlib
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

CREATE TABLE IF NOT EXISTS px_cache (
    path        TEXT PRIMARY KEY,
    title       TEXT,
    unit        TEXT,
    dims        TEXT,
    reduced     TEXT,
    n_rows      INTEGER,
    payload     TEXT,
    fetched_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS od_catalog (
    key         TEXT PRIMARY KEY,
    title       TEXT,
    description TEXT,
    modified    TEXT,
    kind        TEXT,
    px_path     TEXT,
    formats     TEXT,
    license     TEXT,
    landing_url TEXT,
    catalog_url TEXT,
    theme       TEXT,
    subtheme    TEXT,
    first_seen  TEXT,
    last_seen   TEXT
);

CREATE TABLE IF NOT EXISTS od_discovery_log (
    run_at      TEXT,
    event       TEXT,
    ref         TEXT,
    title       TEXT,
    detail      TEXT
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


# ── Open Data: PX-Tabellen, Katalog, Discovery-Log ────────────────────────────

def _pack_df(df: pd.DataFrame) -> str:
    """DataFrame → komprimierter JSON-String (Strings bleiben Strings, NaN → null)."""
    cols = list(df.columns)
    rows = df.astype(object).where(df.notna(), None).values.tolist()
    return base64.b64encode(zlib.compress(json.dumps({"c": cols, "r": rows}).encode(), 6)).decode()


def _unpack_df(payload: str) -> pd.DataFrame:
    d = json.loads(zlib.decompress(base64.b64decode(payload)))
    return pd.DataFrame(d["r"], columns=d["c"])


def write_px_cache(path: str, df: pd.DataFrame, info: dict):
    engine = _get_engine()
    if engine is None or df.empty:
        return
    row = {
        "path": path, "title": info.get("title", ""), "unit": info.get("unit", ""),
        "dims": json.dumps(info.get("dims", []), ensure_ascii=False),
        "reduced": json.dumps(info.get("reduced", []), ensure_ascii=False),
        "n_rows": len(df), "payload": _pack_df(df), "fetched_at": datetime.utcnow(),
    }
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM px_cache WHERE path = :path"), {"path": path})
        conn.execute(text(
            "INSERT INTO px_cache (path, title, unit, dims, reduced, n_rows, payload, fetched_at) "
            "VALUES (:path, :title, :unit, :dims, :reduced, :n_rows, :payload, :fetched_at)"), row)
        conn.commit()
    log.info("px_cache geschrieben: %s (%d Zeilen)", path, len(df))


def read_px_cache(path: str):
    """→ (DataFrame, info-dict, fetched_at: datetime) oder None."""
    engine = _get_engine()
    if engine is None:
        return None
    try:
        with engine.connect() as conn:
            r = conn.execute(text(
                "SELECT title, unit, dims, reduced, payload, fetched_at FROM px_cache WHERE path = :p"),
                {"p": path}).fetchone()
    except Exception as e:
        log.warning("px_cache-Lesefehler: %s", e)
        return None
    if not r:
        return None
    fetched = r[5] if isinstance(r[5], datetime) else pd.to_datetime(r[5]).to_pydatetime()
    info = {"path": path, "title": r[0], "unit": r[1], "dims": json.loads(r[2] or "[]"),
            "reduced": json.loads(r[3] or "[]"), "fetched_at": fetched}
    return _unpack_df(r[4]), info, fetched


def get_px(path: str, max_age_hours: float | None = 24 * 7, allow_live: bool = False):
    """
    PX-Tabelle aus dem SQLite-Cache. Mit allow_live=True wird bei fehlendem/veraltetem Cache
    live nachgeladen (nur für den Daten-Explorer); bei Fehlern gilt veralteter Cache als Fallback.
    → (df, info) oder (leerer DataFrame, {}).
    """
    cached = read_px_cache(path)
    fresh = (cached is not None and (max_age_hours is None or
             (datetime.utcnow() - cached[2]).total_seconds() < max_age_hours * 3600))
    if fresh or not allow_live:
        return (cached[0], cached[1]) if cached else (pd.DataFrame(), {})
    try:
        from opendata import px_fetch
        df, info = px_fetch(path)
        write_px_cache(path, df, info)
        info["fetched_at"] = datetime.utcnow()
        return df, info
    except Exception as e:
        log.warning("PX-Live-Abruf fehlgeschlagen (%s): %s", path, e)
        return (cached[0], cached[1]) if cached else (pd.DataFrame(), {})


CATALOG_COLS = ["key", "title", "description", "modified", "kind", "px_path", "formats",
                "license", "landing_url", "catalog_url", "theme", "subtheme"]


def write_catalog(records: list[dict]):
    """Ersetzt den Katalog; first_seen bleibt für bekannte Einträge erhalten."""
    engine = _get_engine()
    if engine is None or not records:
        return
    now = datetime.utcnow().strftime("%Y-%m-%d")
    old = read_catalog()
    first = dict(zip(old["key"], old["first_seen"])) if not old.empty else {}
    rows, seen = [], set()
    for r in records:
        if r["key"] in seen:
            continue
        seen.add(r["key"])
        rows.append({**{c: r.get(c, "") for c in CATALOG_COLS},
                     "first_seen": first.get(r["key"], now), "last_seen": now})
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM od_catalog"))
        conn.commit()
    pd.DataFrame(rows).to_sql("od_catalog", engine, if_exists="append", index=False, method="multi")
    log.info("od_catalog geschrieben (%d Einträge)", len(rows))


def read_catalog() -> pd.DataFrame:
    return _read("SELECT * FROM od_catalog ORDER BY theme, subtheme, key")


def write_discovery_log(events: list[dict]):
    engine = _get_engine()
    if engine is None or not events:
        return
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
    df = pd.DataFrame([{"run_at": now, "event": e["event"], "ref": e.get("ref", ""),
                        "title": e.get("title", ""), "detail": e.get("detail", "")} for e in events])
    df.to_sql("od_discovery_log", engine, if_exists="append", index=False, method="multi")


def read_discovery_log(limit: int = 50) -> pd.DataFrame:
    return _read("SELECT * FROM od_discovery_log ORDER BY run_at DESC LIMIT :n", {"n": limit})


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
