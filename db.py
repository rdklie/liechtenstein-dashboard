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
  factbook_fields       — CIA World Factbook (Archiv 1990–2025), Rohtext je Jahr/Feld, Liechtenstein
  factbook_values       — daraus geparste Kennzahlen je Jahr (Zeitreihen)
  police_metrics        — Kennzahlen aus den Jahresberichten der Landespolizei (mit Seite und Quelltext je Wert)
  police_delikte        — Deliktsgruppen-Tabelle (soweit als Text lesbar)
  police_reports        — Berichtsdateien (URL, SHA-256, Abrufdatum, Fehler)
  clim_daily            — ERA5-Tageswerte je Gemeinde und Jahr (Open-Meteo), komprimiert
  clim_annual           — daraus berechnete Jahreskennzahlen (Hitzetage, Frosttage, …)
  fc_results            — Projektionen je Reihe (Rückwärtstest, Intervalle), vom Worker berechnet
  imf_data              — IWF DataMapper: Indikatoren für Liechtenstein (falls vorhanden)
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
from sqlalchemy import create_engine, event, inspect, text

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
    publisher   TEXT,
    publisher_source TEXT,
    data_url    TEXT,
    data_format TEXT,
    first_seen  TEXT,
    last_seen   TEXT
);

CREATE TABLE IF NOT EXISTS od_orgs (
    name        TEXT PRIMARY KEY,
    homepage    TEXT,
    email       TEXT
);

CREATE TABLE IF NOT EXISTS factbook_fields (
    year        INTEGER,
    category    TEXT,
    field       TEXT,
    content     TEXT
);

CREATE TABLE IF NOT EXISTS factbook_values (
    year        INTEGER NOT NULL,
    indicator   TEXT    NOT NULL,
    ref_year    INTEGER NOT NULL,
    value       FLOAT,
    unit        TEXT,
    PRIMARY KEY (year, indicator, ref_year)
);

CREATE TABLE IF NOT EXISTS imf_data (
    indicator   TEXT    NOT NULL,
    year        INTEGER NOT NULL,
    value       FLOAT,
    fetched_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (indicator, year)
);

CREATE TABLE IF NOT EXISTS police_metrics (
    year        INTEGER NOT NULL,
    metric      TEXT    NOT NULL,
    value       FLOAT,
    prev        FLOAT,
    page        INTEGER,
    source_text TEXT,
    flag        TEXT,
    PRIMARY KEY (year, metric)
);

CREATE TABLE IF NOT EXISTS police_delikte (
    year        INTEGER NOT NULL,
    grp         TEXT    NOT NULL,
    page        INTEGER,
    offences    INTEGER,
    offences_prev INTEGER,
    tv_total    INTEGER,
    tv_under18  INTEGER,
    tv_foreign  INTEGER,
    source_text TEXT,
    PRIMARY KEY (year, grp)
);

CREATE TABLE IF NOT EXISTS police_reports (
    year        INTEGER PRIMARY KEY,
    file        TEXT,
    url         TEXT,
    sha256      TEXT,
    bytes       INTEGER,
    pages       INTEGER,
    retrieved   TEXT,
    error       TEXT
);

CREATE TABLE IF NOT EXISTS clim_daily (
    muni        TEXT    NOT NULL,
    year        INTEGER NOT NULL,
    elevation   FLOAT,
    payload     TEXT,
    PRIMARY KEY (muni, year)
);

CREATE TABLE IF NOT EXISTS clim_annual (
    muni        TEXT    NOT NULL,
    year        INTEGER NOT NULL,
    elevation   FLOAT,
    n_days      INTEGER,
    tmean       FLOAT,
    tmax_mean   FLOAT,
    tmin_mean   FLOAT,
    hot_days    INTEGER,
    summer_days INTEGER,
    frost_days  INTEGER,
    ice_days    INTEGER,
    snow_days   INTEGER,
    heavy_rain_days INTEGER,
    prec        FLOAT,
    snow        FLOAT,
    PRIMARY KEY (muni, year)
);

CREATE TABLE IF NOT EXISTS fc_results (
    series      TEXT PRIMARY KEY,
    payload     TEXT,
    computed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS imf_meta (
    indicator   TEXT PRIMARY KEY,
    source      TEXT
);

CREATE TABLE IF NOT EXISTS od_discovery_log (
    run_at      TEXT,
    event       TEXT,
    ref         TEXT,
    title       TEXT,
    detail      TEXT
);
"""


# Spalten, die nach dem ersten Release dazukamen (CREATE IF NOT EXISTS ändert bestehende Tabellen nicht)
_ADDED_COLUMNS = {
    "od_catalog": [("publisher", "TEXT"), ("publisher_source", "TEXT"), ("data_url", "TEXT"), ("data_format", "TEXT")],
}


def _create_tables(engine):
    with engine.connect() as conn:
        for stmt in DDL.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                conn.execute(text(stmt))
        conn.commit()
    insp = inspect(engine)
    with engine.connect() as conn:
        for table, cols in _ADDED_COLUMNS.items():
            have = {c["name"] for c in insp.get_columns(table)}
            for name, typ in cols:
                if name not in have:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {typ}"))
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


def _live_fetch(path: str):
    """Quelle nach Präfix: «file:<URL>» (CSV/JSON aus dem Katalog), «imf:<Agentur/Fluss/Version>», sonst PXWeb-Pfad."""
    if path.startswith("file:"):
        from opendata import fetch_file
        return fetch_file(path[5:])
    if path.startswith("imf:"):
        from imf import fetch_sdmx
        return fetch_sdmx(path[4:])
    if path.startswith(("es:", "wb:", "pxs:")):
        from migration import fetch_source
        return fetch_source(path)
    if path.startswith("edu:"):
        from bildung import fetch_source
        return fetch_source(path)
    if path.startswith("lohn:"):
        from lohn import fetch_source
        return fetch_source(path)
    from opendata import px_fetch
    return px_fetch(path)


def get_px(path: str, max_age_hours: float | None = 24 * 7, allow_live: bool = False):
    """
    Tabelle aus dem SQLite-Cache (PXWeb-Pfad, «file:<URL>» oder «imf:<Fluss>»). Mit allow_live=True wird bei
    fehlendem/veraltetem Cache live nachgeladen (Explorer); bei Fehlern gilt veralteter Cache als Fallback.
    → (df, info) oder (leerer DataFrame, {"error": Meldung} bzw. {}).
    """
    cached = read_px_cache(path)
    fresh = (cached is not None and (max_age_hours is None or
             (datetime.utcnow() - cached[2]).total_seconds() < max_age_hours * 3600))
    if fresh or not allow_live:
        return (cached[0], cached[1]) if cached else (pd.DataFrame(), {})
    try:
        df, info = _live_fetch(path)
        write_px_cache(path, df, info)
        info["fetched_at"] = datetime.utcnow()
        return df, info
    except Exception as e:
        log.warning("Live-Abruf fehlgeschlagen (%s): %s", path, e)
        if cached:
            return cached[0], cached[1]
        return pd.DataFrame(), {"error": str(e)[:200]}


def refresh_source(path: str, max_age_days: float = 7) -> str:
    """Explorer-Quelle (file:/imf:/PXWeb) höchstens alle max_age_days neu laden → 'frisch' | 'aktualisiert'.
    Fehler werden als Exception weitergegeben (Worker sammelt sie)."""
    cached = read_px_cache(path)
    if cached is not None and (datetime.utcnow() - cached[2]).total_seconds() < max_age_days * 86400:
        return "frisch"
    df, info = _live_fetch(path)
    write_px_cache(path, df, info)
    return "aktualisiert"


CATALOG_COLS = ["key", "title", "description", "modified", "kind", "px_path", "formats",
                "license", "landing_url", "catalog_url", "theme", "subtheme", "publisher", "publisher_source",
                "data_url", "data_format"]


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


def write_orgs(orgs: list[dict]):
    engine = _get_engine()
    if engine is None or not orgs:
        return
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM od_orgs"))
        conn.commit()
    pd.DataFrame(orgs).drop_duplicates("name").to_sql("od_orgs", engine, if_exists="append", index=False, method="multi")


def read_orgs() -> pd.DataFrame:
    return _read("SELECT name, homepage, email FROM od_orgs ORDER BY name")


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


def write_factbook(fields: pd.DataFrame, values: pd.DataFrame):
    """Ersetzt den kompletten Factbook-Archivbestand (einmaliger Import, siehe factbook_import.py)."""
    engine = _get_engine()
    if engine is None or fields.empty:
        return
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM factbook_fields"))
        conn.execute(text("DELETE FROM factbook_values"))
        conn.commit()
    fields.to_sql("factbook_fields", engine, if_exists="append", index=False, method="multi", chunksize=500)
    if not values.empty:
        values.to_sql("factbook_values", engine, if_exists="append", index=False, method="multi", chunksize=500)


def read_factbook_values() -> pd.DataFrame:
    return _read("SELECT year, indicator, ref_year, value, unit FROM factbook_values ORDER BY indicator, ref_year, year")


def read_factbook_fields(field: str | None = None) -> pd.DataFrame:
    if field:
        return _read("SELECT year, category, field, content FROM factbook_fields WHERE field = :f ORDER BY year", {"f": field})
    return _read("SELECT year, category, field, content FROM factbook_fields ORDER BY year")


def write_police(metrics: pd.DataFrame, delikte: pd.DataFrame, reports: pd.DataFrame):
    """Ersetzt den kompletten Polizeistatistik-Bestand (einmaliger Import, police.py)."""
    engine = _get_engine()
    if engine is None or metrics.empty:
        return
    with engine.connect() as conn:
        for t in ("police_metrics", "police_delikte", "police_reports"):
            conn.execute(text(f"DELETE FROM {t}"))
        conn.commit()
    metrics.to_sql("police_metrics", engine, if_exists="append", index=False, method="multi", chunksize=200)
    if not delikte.empty:
        delikte.to_sql("police_delikte", engine, if_exists="append", index=False, method="multi", chunksize=200)
    if not reports.empty:
        reports.to_sql("police_reports", engine, if_exists="append", index=False, method="multi", chunksize=200)


def read_police_metrics() -> pd.DataFrame:
    return _read("SELECT year, metric, value, prev, page, source_text, flag FROM police_metrics ORDER BY metric, year")


def read_police_delikte() -> pd.DataFrame:
    return _read("SELECT * FROM police_delikte ORDER BY year, grp")


def read_police_reports() -> pd.DataFrame:
    return _read("SELECT * FROM police_reports ORDER BY year")


def read_clim_years() -> set:
    d = _read("SELECT muni, year FROM clim_daily")
    return set(zip(d["muni"], d["year"].astype(int))) if not d.empty else set()


def write_clim_daily(df: pd.DataFrame):
    engine = _get_engine()
    if engine is None or df.empty:
        return
    with engine.connect() as conn:
        for r in df.itertuples():
            conn.execute(text("DELETE FROM clim_daily WHERE muni = :m AND year = :y"), {"m": r.muni, "y": int(r.year)})
        conn.commit()
    df.to_sql("clim_daily", engine, if_exists="append", index=False, method="multi", chunksize=50)


def read_clim_daily_all() -> pd.DataFrame:
    return _read("SELECT muni, year, elevation, payload FROM clim_daily ORDER BY muni, year")


def read_clim_daily(muni: str) -> pd.DataFrame:
    return _read("SELECT year, payload FROM clim_daily WHERE muni = :m ORDER BY year", {"m": muni})


def write_clim_annual(df: pd.DataFrame):
    engine = _get_engine()
    if engine is None or df.empty:
        return
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM clim_annual"))
        conn.commit()
    df.to_sql("clim_annual", engine, if_exists="append", index=False, method="multi", chunksize=200)


def read_clim_annual() -> pd.DataFrame:
    return _read("SELECT * FROM clim_annual ORDER BY muni, year")


def write_fc(series: str, payload: dict):
    engine = _get_engine()
    if engine is None:
        return
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM fc_results WHERE series = :s"), {"s": series})
        conn.execute(text("INSERT INTO fc_results (series, payload, computed_at) VALUES (:s, :p, :t)"),
                     {"s": series, "p": json.dumps(payload), "t": datetime.utcnow()})
        conn.commit()


def read_fc_all() -> dict:
    """{Reihen-ID: {payload: dict, computed: datetime}}"""
    d = _read("SELECT series, payload, computed_at FROM fc_results")
    out = {}
    for r in d.itertuples():
        out[r.series] = {"payload": json.loads(r.payload), "computed": pd.to_datetime(r.computed_at).to_pydatetime()}
    return out


def write_imf(df: pd.DataFrame, indicator: str):
    """df: Spalten year, value."""
    if df.empty:
        return
    d = df[["year", "value"]].copy()
    d["indicator"] = indicator
    _upsert_dataframe(d, "imf_data", ["indicator", "year"])


def read_imf(indicator: str) -> pd.DataFrame:
    return _read("SELECT year, value FROM imf_data WHERE indicator = :i ORDER BY year", {"i": indicator})


def write_imf_meta(indicator: str, source: str):
    engine = _get_engine()
    if engine is None:
        return
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM imf_meta WHERE indicator = :i"), {"i": indicator})
        conn.execute(text("INSERT INTO imf_meta (indicator, source) VALUES (:i, :s)"), {"i": indicator, "s": source})
        conn.commit()


def read_imf_info() -> tuple[str, datetime | None]:
    """→ (Quelle/WEO-Ausgabe, ältester Abrufzeitpunkt) aus imf_meta/imf_data."""
    meta = _read("SELECT source FROM imf_meta LIMIT 1")
    ts = _read("SELECT MIN(fetched_at) AS t FROM imf_data")
    src = meta["source"].iloc[0] if not meta.empty else ""
    t = pd.to_datetime(ts["t"].iloc[0]).to_pydatetime() if not ts.empty and pd.notna(ts["t"].iloc[0]) else None
    return src, t


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
