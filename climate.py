"""
climate.py — Klimawandel je Gemeinde: ERA5-Tageswerte (Open-Meteo Archive API), Archiv, Jahreskennzahlen, Trends
=================================================================================================================
Quelle: Open-Meteo Historical Weather API (https://open-meteo.com/en/docs/historical-weather-api), Modell ERA5
(ECMWF Reanalyse, Copernicus Climate Change Service; Rasterweite ~0.25°, ≈ 25–30 km). Lizenz: Open-Meteo CC BY 4.0
(Namensnennung «Weather data by Open-Meteo.com»), ERA5 © ECMWF/Copernicus (Lizenz CC BY 4.0).

Ablauf
  * Einmalige Ladung 1950–Vorjahr für alle 11 Gemeinden in 5-Jahres-Abschnitten (176 Abrufe), mit Pause und Backoff bei
    HTTP 429. Der Fortschritt steht in clim_daily (Gemeinde, Jahr): abgebrochene Läufe setzen dort fort.
  * Jährlich ergänzt der tägliche Worker fehlende abgeschlossene Jahre (wenige Abrufe je Lauf).
  * Rohantworten werden als <Datenordner>/archive/climate/<gemeinde>_<von>-<bis>.json.gz abgelegt.
  * Jahreskennzahlen (Hitzetage, Frosttage, …) und Trends (Theil-Sen, Mann-Kendall) werden aus den Tageswerten berechnet.

Ehrlicher Hinweis zur Auflösung: ERA5 hat ein grobes Raster. Open-Meteo gibt zu jedem Abruf die Höhe seines Höhenmodells am
Koordinatenpunkt zurück (z. B. Triesenberg 1042 m, die Gemeinde-Höhe in data_fetcher ist 884 m), und die Temperaturen unterscheiden sich
zwischen den Gemeinden etwa im Mass der Höhenunterschiede (rund 5–6 K pro km) — das spricht für eine Höhenkorrektur der Temperatur durch
Open-Meteo. Niederschlag/Schnee gelten als Rasterwerte ohne belegte Korrektur. Wir verändern die Werte nicht; Unterschiede zwischen Gemeinden sind
überwiegend Höhenunterschiede, keine lokalen Beobachtungen.
"""

import gzip
import json
import logging
import os
import sys
import time
import zlib
import base64
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import requests

import db
from data_fetcher import MUNICIPALITIES

log = logging.getLogger("climate")

API = "https://archive-api.open-meteo.com/v1/archive"
HEADERS = {"User-Agent": "LiechtensteinDashboard/1.0 (https://daten.li; Klimaarchiv, wenige Abrufe mit Pause)"}
START_YEAR = 1950
CHUNK_YEARS = 5
DAILY = ["temperature_2m_mean", "temperature_2m_max", "temperature_2m_min", "precipitation_sum", "snowfall_sum"]
COLS = ["tmean", "tmax", "tmin", "prec", "snow"]
REF_PERIOD = (1991, 2020)               # WMO-Normalperiode
VALLEY_MAX_ELEV = 600                   # Gemeindehöhe (data_fetcher): darunter «Talgemeinde», darüber «Berggemeinde»

# Schwellen der Kennzahlen (MeteoSchweiz-übliche Definitionen)
INDICES = {
    "tmean": ("Jahresmitteltemperatur", "°C"),
    "hot_days": ("Hitzetage (Tmax ≥ 30 °C)", "Tage"),
    "summer_days": ("Sommertage (Tmax ≥ 25 °C)", "Tage"),
    "frost_days": ("Frosttage (Tmin < 0 °C)", "Tage"),
    "ice_days": ("Eistage (Tmax < 0 °C)", "Tage"),
    "snow_days": ("Schneefalltage (Schneefall ≥ 1 cm)", "Tage"),
    "heavy_rain_days": ("Starkregentage (Niederschlag ≥ 20 mm)", "Tage"),
    "prec": ("Jahresniederschlag", "mm"),
    "snow": ("Jahres-Schneefallsumme", "cm"),
}


def archive_dir() -> Path:
    sqlite = os.environ.get("SQLITE_PATH")
    base = Path(sqlite).parent if sqlite else db.DEFAULT_SQLITE_PATH.parent
    d = base / "archive" / "climate"
    d.mkdir(parents=True, exist_ok=True)
    return d


class RateLimited(Exception):
    pass


def last_complete_year() -> int:
    return date.today().year - 1


# ── Abruf ─────────────────────────────────────────────────────────────────────

def fetch_chunk(lat: float, lon: float, y0: int, y1: int) -> dict:
    params = {"latitude": lat, "longitude": lon, "start_date": f"{y0}-01-01", "end_date": f"{y1}-12-31",
              "daily": ",".join(DAILY), "timezone": "Europe/Zurich", "models": "era5"}
    r = requests.get(API, params=params, headers=HEADERS, timeout=120)
    if r.status_code == 429:
        raise RateLimited(r.text[:120])
    r.raise_for_status()
    return r.json()


def missing_chunks() -> list[tuple[str, int, int]]:
    """[(Gemeinde, von, bis)] aller fehlenden abgeschlossenen Jahre, in Abschnitten zu höchstens CHUNK_YEARS."""
    have = db.read_clim_years()
    out = []
    for key in MUNICIPALITIES:
        years = [y for y in range(START_YEAR, last_complete_year() + 1) if (key, y) not in have]
        i = 0
        while i < len(years):
            j = i
            while j + 1 < len(years) and years[j + 1] == years[j] + 1 and years[j + 1] - years[i] < CHUNK_YEARS:
                j += 1
            out.append((key, years[i], years[j]))
            i = j + 1
    return out


def store_chunk(key: str, y0: int, y1: int, data: dict):
    """Rohdaten archivieren und je Jahr in clim_daily schreiben."""
    raw = archive_dir() / f"{key}_{y0}-{y1}.json.gz"
    raw.write_bytes(gzip.compress(json.dumps(data).encode("utf-8"), 6))
    daily = data["daily"]
    df = pd.DataFrame({"date": pd.to_datetime(daily["time"])})
    for api, col in zip(DAILY, COLS):
        df[col] = daily[api]
    rows = []
    for year, g in df.groupby(df["date"].dt.year):
        arr = {c: [None if pd.isna(v) else round(float(v), 2) for v in g[c]] for c in COLS}
        arr["d0"] = g["date"].iloc[0].strftime("%Y-%m-%d")
        rows.append({"muni": key, "year": int(year), "elevation": float(data.get("elevation", np.nan)),
                     "payload": base64.b64encode(zlib.compress(json.dumps(arr).encode(), 6)).decode()})
    db.write_clim_daily(pd.DataFrame(rows))


def load_missing(max_requests: int | None = None, pause: float = 20.0, patient: bool = False) -> tuple[int, int]:
    """
    Fehlende Abschnitte laden. patient=True (Importskript): bei HTTP 429 lange warten und weitermachen;
    sonst (Worker): beim ersten 429 abbrechen und am nächsten Tag fortsetzen. → (geladen, noch fehlend)
    """
    todo = missing_chunks()
    done = 0
    for key, y0, y1 in todo:
        if max_requests is not None and done >= max_requests:
            break
        m = MUNICIPALITIES[key]
        waited = 0
        while True:
            try:
                data = fetch_chunk(m["lat"], m["lon"], y0, y1)
                break
            except RateLimited as e:
                if not patient:
                    log.warning("Open-Meteo 429 — Abbruch, Fortsetzung beim nächsten Lauf")
                    return done, len(todo) - done
                waited += 1
                wait = min(900, 120 * waited)
                log.warning("429 (%s) — warte %d s", str(e)[:60], wait)
                time.sleep(wait)
                if waited > 40:
                    return done, len(todo) - done
        store_chunk(key, y0, y1, data)
        done += 1
        log.info("%s %d–%d geladen (%d/%d)", m["name"], y0, y1, done, len(todo))
        time.sleep(pause)
    if done:
        rebuild_annual()
    return done, max(0, len(todo) - done)


# ── Jahreskennzahlen ──────────────────────────────────────────────────────────

def _unpack(payload: str) -> dict:
    return json.loads(zlib.decompress(base64.b64decode(payload)))


def rebuild_annual():
    """clim_annual aus clim_daily neu berechnen (nur vollständige Jahre, ≥ 360 gültige Tage)."""
    daily = db.read_clim_daily_all()
    rows = []
    for r in daily.itertuples():
        a = _unpack(r.payload)
        s = {c: np.array([np.nan if v is None else v for v in a[c]], dtype=float) for c in COLS}
        n = int(np.sum(~np.isnan(s["tmean"])))
        if n < 360:
            continue
        valid = lambda x: x[~np.isnan(x)]
        rows.append({
            "muni": r.muni, "year": int(r.year), "elevation": r.elevation, "n_days": n,
            "tmean": float(np.nanmean(s["tmean"])), "tmax_mean": float(np.nanmean(s["tmax"])), "tmin_mean": float(np.nanmean(s["tmin"])),
            "hot_days": int(np.sum(s["tmax"] >= 30)), "summer_days": int(np.sum(s["tmax"] >= 25)),
            "frost_days": int(np.sum(s["tmin"] < 0)), "ice_days": int(np.sum(s["tmax"] < 0)),
            "snow_days": int(np.sum(s["snow"] >= 1.0)), "heavy_rain_days": int(np.sum(s["prec"] >= 20.0)),
            "prec": float(np.nansum(s["prec"])), "snow": float(np.nansum(s["snow"])),
        })
    db.write_clim_annual(pd.DataFrame(rows))
    log.info("clim_annual: %d Gemeinde-Jahre", len(rows))


# ── Trends ────────────────────────────────────────────────────────────────────

def _norm_cdf(z: float) -> float:
    import math
    return 0.5 * math.erfc(-z / math.sqrt(2))


def theil_sen(x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    """Steigung (Median aller Paarsteigungen) und Achsenabschnitt (Median von y − b·x)."""
    i, j = np.triu_indices(len(x), 1)
    dx = x[j] - x[i]
    ok = dx != 0
    slopes = (y[j] - y[i])[ok] / dx[ok]
    b = float(np.median(slopes))
    a = float(np.median(y - b * x))
    return b, a


def mann_kendall(y: np.ndarray) -> tuple[float, float]:
    """Mann-Kendall-Trendtest (zweiseitig, Normalapproximation mit Korrektur für Bindungen) → (S, p)."""
    n = len(y)
    if n < 8:
        return float("nan"), float("nan")
    s = 0
    for k in range(n - 1):
        s += int(np.sum(np.sign(y[k + 1:] - y[k])))
    _, counts = np.unique(y, return_counts=True)
    var = (n * (n - 1) * (2 * n + 5) - np.sum(counts * (counts - 1) * (2 * counts + 5))) / 18.0
    if var <= 0:
        return float(s), float("nan")
    z = (s - np.sign(s)) / np.sqrt(var) if s != 0 else 0.0
    return float(s), float(2 * (1 - _norm_cdf(abs(z))))


def trend(years: np.ndarray, values: np.ndarray) -> dict:
    """Trend einer Jahresreihe: Steigung je Jahrzehnt (Theil-Sen), p (Mann-Kendall), n."""
    ok = ~np.isnan(values)
    x, y = years[ok].astype(float), values[ok]
    if len(x) < 10:
        return {"n": int(len(x)), "slope_decade": float("nan"), "p": float("nan"), "intercept": float("nan")}
    b, a = theil_sen(x, y)
    _, p = mann_kendall(y)
    return {"n": int(len(x)), "slope_decade": b * 10, "p": p, "intercept": a}


def run(patient: bool = True, max_requests: int | None = None) -> int:
    db.init_db()
    done, left = load_missing(max_requests=max_requests, patient=patient)
    log.info("Fertig: %d Abschnitte geladen, %d fehlen noch", done, left)
    return 0 if left == 0 else 2


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", handlers=[logging.StreamHandler(sys.stdout)])
    sys.exit(run(patient="--worker" not in sys.argv))
