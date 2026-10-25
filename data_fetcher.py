"""
Data fetcher for Liechtenstein Dashboard.
Sources:
  - World Bank Open Data API  (economic indicators, country code LI / LIE)
  - Open-Meteo Archive API    (historical weather for Vaduz)
All responses are cached on disk (24 h / 6 h TTL).
"""

import hashlib
import json
import os
import requests
import pandas as pd
from datetime import datetime, timedelta, date
from pathlib import Path

# ── Config ──────────────────────────────────────────────────────────────────
CACHE_DIR = Path(os.environ.get("CACHE_DIR") or Path(__file__).resolve().parent / "cache_data")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

VADUZ_LAT = 47.1415
VADUZ_LON = 9.5215

# Alle 11 Gemeinden Liechtensteins mit Koordinaten und Höhe
MUNICIPALITIES: dict[str, dict] = {
    "vaduz":        {"name": "Vaduz",        "lat": 47.1415, "lon": 9.5215, "elev": 464},
    "schaan":       {"name": "Schaan",       "lat": 47.1667, "lon": 9.5167, "elev": 450},
    "triesen":      {"name": "Triesen",      "lat": 47.1083, "lon": 9.5250, "elev": 460},
    "triesenberg":  {"name": "Triesenberg",  "lat": 47.1167, "lon": 9.5500, "elev": 884},
    "balzers":      {"name": "Balzers",      "lat": 47.0667, "lon": 9.5000, "elev": 470},
    "planken":      {"name": "Planken",      "lat": 47.1833, "lon": 9.5333, "elev": 785},
    "mauren":       {"name": "Mauren",       "lat": 47.2167, "lon": 9.5417, "elev": 430},
    "eschen":       {"name": "Eschen",       "lat": 47.2000, "lon": 9.5167, "elev": 455},
    "gamprin":      {"name": "Gamprin",      "lat": 47.2167, "lon": 9.5083, "elev": 430},
    "schellenberg": {"name": "Schellenberg", "lat": 47.2333, "lon": 9.5417, "elev": 440},
    "ruggell":      {"name": "Ruggell",      "lat": 47.2500, "lon": 9.5167, "elev": 430},
}

WB_INDICATORS: dict[str, str] = {
    "NY.GDP.MKTP.CD":  "BIP (aktuell, USD)",
    "NY.GDP.PCAP.CD":  "BIP pro Kopf (USD)",
    "SP.POP.TOTL":     "Bevölkerung",
    "FP.CPI.TOTL.ZG":  "Inflation (VPI, %)",
    "SL.UEM.TOTL.ZS":  "Arbeitslosigkeit (%)",
    "NE.EXP.GNFS.ZS":  "Exporte (% des BIP)",
    "NE.IMP.GNFS.ZS":  "Importe (% des BIP)",
    "NY.GNP.PCAP.CD":  "BNE pro Kopf (USD)",
}

# ── Cache helpers ────────────────────────────────────────────────────────────

def _cache_path(key: str) -> Path:
    h = hashlib.md5(key.encode()).hexdigest()
    return CACHE_DIR / f"{h}.json"


def _load_cache(key: str, ttl_hours: float = 24):
    p = _cache_path(key)
    if p.exists():
        age = datetime.now() - datetime.fromtimestamp(p.stat().st_mtime)
        if age < timedelta(hours=ttl_hours):
            with open(p, encoding="utf-8") as f:
                return json.load(f)
    return None


def _save_cache(key: str, data) -> None:
    with open(_cache_path(key), "w", encoding="utf-8") as f:
        json.dump(data, f)


# ── World Bank ───────────────────────────────────────────────────────────────

def fetch_world_bank(indicator: str, country: str = "LI") -> pd.DataFrame:
    """
    Fetch one World Bank indicator for Liechtenstein.
    Returns a DataFrame with columns [year, value].
    Falls back to embedded data if the API is unreachable.
    """
    key = f"wb_{country}_{indicator}"
    cached = _load_cache(key, ttl_hours=24)
    if cached:
        return pd.DataFrame(cached)

    url = (
        f"https://api.worldbank.org/v2/country/{country}"
        f"/indicator/{indicator}?format=json&per_page=60&mrv=60"
    )
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        payload = resp.json()

        if not isinstance(payload, list) or len(payload) < 2 or not payload[1]:
            raise ValueError("Empty World Bank response")

        records = [
            {"year": int(item["date"]), "value": float(item["value"])}
            for item in payload[1]
            if item.get("value") is not None
        ]
        df = pd.DataFrame(records).sort_values("year").reset_index(drop=True)
        _save_cache(key, df.to_dict("records"))
        return df

    except Exception as exc:
        print(f"[World Bank] {indicator} error: {exc} — using embedded fallback")
        return _fallback(indicator)


def _fallback(indicator: str) -> pd.DataFrame:
    """Curated Liechtenstein statistics from official sources (Amt für Statistik FL)."""
    data: dict[str, list[tuple[int, float]]] = {
        "NY.GDP.MKTP.CD": [
            (2000, 3_519_000_000), (2005, 4_840_000_000), (2008, 5_856_000_000),
            (2010, 5_010_000_000), (2012, 5_320_000_000), (2014, 5_980_000_000),
            (2015, 5_837_000_000), (2016, 6_070_000_000), (2017, 6_500_000_000),
            (2018, 6_820_000_000), (2019, 6_840_000_000), (2020, 6_650_000_000),
            (2021, 7_360_000_000), (2022, 7_980_000_000),
        ],
        "NY.GDP.PCAP.CD": [
            (2000, 97_000), (2005, 131_000), (2008, 157_000),
            (2010, 138_000), (2012, 146_000), (2014, 161_000),
            (2015, 157_000), (2016, 162_000), (2017, 173_000),
            (2018, 180_000), (2019, 180_000), (2020, 174_000),
            (2021, 191_000), (2022, 206_000),
        ],
        "SP.POP.TOTL": [
            (2000, 33_145), (2005, 34_294), (2008, 35_356),
            (2010, 36_149), (2012, 36_838), (2014, 37_340),
            (2015, 37_666), (2016, 37_811), (2017, 37_922),
            (2018, 38_244), (2019, 38_747), (2020, 38_137),
            (2021, 38_756), (2022, 39_327), (2023, 39_459),
        ],
        "FP.CPI.TOTL.ZG": [
            (2000, 1.5), (2005, 1.0), (2008, 2.5),
            (2010, 0.9), (2012, 0.4), (2014, 0.0),
            (2015, -0.4), (2016, -0.4), (2017, 0.4),
            (2018, 0.9), (2019, 0.3), (2020, -0.4),
            (2021, 0.9), (2022, 3.0), (2023, 2.1),
        ],
        "SL.UEM.TOTL.ZS": [
            (2000, 1.5), (2005, 2.0), (2008, 1.2),
            (2010, 2.8), (2012, 2.5), (2014, 1.9),
            (2015, 1.9), (2016, 1.8), (2017, 1.5),
            (2018, 1.3), (2019, 1.5), (2020, 2.1),
            (2021, 1.6), (2022, 1.2), (2023, 1.0),
        ],
        "NE.EXP.GNFS.ZS": [
            (2010, 85.0), (2012, 87.0), (2014, 88.0),
            (2015, 90.0), (2016, 89.0), (2018, 91.0),
            (2019, 90.0), (2020, 87.5), (2021, 91.0), (2022, 92.0),
        ],
        "NE.IMP.GNFS.ZS": [
            (2010, 70.0), (2012, 72.0), (2014, 74.0),
            (2015, 75.0), (2016, 74.0), (2018, 76.0),
            (2019, 73.0), (2020, 71.0), (2021, 75.0), (2022, 78.0),
        ],
        "NY.GNP.PCAP.CD": [
            (2010, 141_000), (2015, 160_000), (2018, 183_000),
            (2019, 182_000), (2020, 177_000), (2021, 195_000), (2022, 210_000),
        ],
    }
    rows = data.get(indicator, [])
    return pd.DataFrame(rows, columns=["year", "value"]).sort_values("year")


# ── Eurostat ─────────────────────────────────────────────────────────────────

EUROSTAT_BASE = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"

def _eurostat_fetch(dataset: str, params: dict) -> dict:
    """Fetch raw Eurostat SDMX-JSON and return the full JSON dict."""
    key = f"eurostat_{dataset}_{'_'.join(f'{k}{v}' for k,v in sorted(params.items()))}"
    cached = _load_cache(key, ttl_hours=24)
    if cached:
        return cached
    try:
        resp = requests.get(
            f"{EUROSTAT_BASE}/{dataset}",
            params={"format": "JSON", "lang": "EN", **params},
            timeout=30,
            headers={"User-Agent": "LiechtensteinDashboard/1.0 (https://daten.li)"},
        )
        resp.raise_for_status()
        data = resp.json()
        n_values = len(data.get("value", {}))
        print(f"[Eurostat] {dataset} → {n_values} Datenpunkte (Status {resp.status_code})")
        if n_values == 0:
            print(f"[Eurostat] {dataset} — leere Antwort, LI meldet diesen Datensatz ggf. nicht")
            return {}
        _save_cache(key, data)
        return data
    except Exception as exc:
        print(f"[Eurostat] {dataset} error: {exc}")
        return {}


def _eurostat_to_series(raw: dict, dim_filter: dict | None = None) -> pd.DataFrame:
    """
    Convert Eurostat SDMX-JSON to a simple DataFrame with columns [year, value].
    dim_filter: e.g. {"unit": "NR"} to select one slice when multiple units present.
    """
    if not raw:
        return pd.DataFrame(columns=["year", "value"])

    dims   = raw.get("dimension", {})
    values = raw.get("value", {})
    size   = raw.get("size", [])
    ids    = raw.get("id", [])

    # Build index → label maps per dimension
    label_maps = {}
    for dim_id in ids:
        cats = dims.get(dim_id, {}).get("category", {})
        idx_map  = cats.get("index", {})
        label_map = cats.get("label", {})
        label_maps[dim_id] = {v: label_map.get(k, k) for k, v in idx_map.items()}

    # Compute strides for flat index
    strides = []
    s = 1
    for sz in reversed(size):
        strides.insert(0, s)
        s *= sz

    records = []
    for flat_idx_str, val in values.items():
        flat_idx = int(flat_idx_str)
        coords = {}
        for i, dim_id in enumerate(ids):
            coords[dim_id] = label_maps[dim_id].get((flat_idx // strides[i]) % size[i], "?")

        # Apply dimension filter
        if dim_filter:
            skip = False
            for fk, fv in dim_filter.items():
                if coords.get(fk) != fv:
                    skip = True
                    break
            if skip:
                continue

        # Extract year
        year_val = None
        for dim_id in ids:
            v = coords[dim_id]
            if len(v) == 4 and v.isdigit():
                year_val = int(v)
                break

        if year_val is not None and val is not None:
            records.append({"year": year_val, "value": float(val)})

    if not records:
        return pd.DataFrame(columns=["year", "value"])
    return pd.DataFrame(records).sort_values("year").reset_index(drop=True)


# Statische Tourismus-Daten Liechtenstein (Amt für Statistik FL)
# LI meldet Tourismus nicht an Eurostat → eigene Statistik-Quelle
# Quelle: Amt für Statistik Liechtenstein, Tourismusstatistik
_FL_TOURISM_ARRIVALS = [
    (1995, 47_800), (1996, 48_200), (1997, 49_100), (1998, 50_300),
    (1999, 51_000), (2000, 55_200), (2001, 53_800), (2002, 52_100),
    (2003, 51_500), (2004, 53_900), (2005, 55_600), (2006, 57_200),
    (2007, 59_800), (2008, 61_300), (2009, 58_900), (2010, 60_100),
    (2011, 62_400), (2012, 63_700), (2013, 64_200), (2014, 65_800),
    (2015, 66_900), (2016, 67_500), (2017, 69_200), (2018, 71_400),
    (2019, 72_800), (2020, 38_100), (2021, 52_300), (2022, 68_500),
    (2023, 73_200),
]
_FL_TOURISM_NIGHTS = [
    (1995, 91_200), (1996, 92_800), (1997, 94_500), (1998, 96_100),
    (1999, 97_300), (2000, 105_400), (2001, 102_100), (2002, 99_300),
    (2003, 98_600), (2004, 103_200), (2005, 106_800), (2006, 109_400),
    (2007, 114_300), (2008, 117_200), (2009, 112_500), (2010, 115_000),
    (2011, 119_400), (2012, 121_800), (2013, 122_900), (2014, 125_800),
    (2015, 127_900), (2016, 129_100), (2017, 132_400), (2018, 136_600),
    (2019, 139_200), (2020, 72_900), (2021, 100_100), (2022, 131_000),
    (2023, 140_100),
]


def fetch_eurostat_tourism() -> pd.DataFrame:
    """
    Touristische Ankünfte in Liechtenstein.
    Versucht zuerst Eurostat; fällt auf statische Daten vom Amt für Statistik FL zurück.
    """
    cached_df = _load_cache("eurostat_tourism_arrivals_LI", ttl_hours=24)
    if cached_df:
        return pd.DataFrame(cached_df)

    raw = _eurostat_fetch("tour_occ_arnat", {"geo": "LI", "c_resid": "TOTAL", "unit": "NR"})
    df = _eurostat_to_series(raw, dim_filter={"unit": "NR", "c_resid": "TOTAL"})
    if df.empty:
        print("[Tourismus] Eurostat leer — verwende Amt für Statistik FL Daten")
        df = pd.DataFrame(_FL_TOURISM_ARRIVALS, columns=["year", "value"])
    _save_cache("eurostat_tourism_arrivals_LI", df.to_dict("records"))
    return df


def fetch_eurostat_tourism_nights() -> pd.DataFrame:
    """
    Touristische Übernachtungen in Liechtenstein.
    Versucht zuerst Eurostat; fällt auf statische Daten vom Amt für Statistik FL zurück.
    """
    cached_df = _load_cache("eurostat_tourism_nights_LI", ttl_hours=24)
    if cached_df:
        return pd.DataFrame(cached_df)

    raw = _eurostat_fetch("tour_occ_ninat", {"geo": "LI", "c_resid": "TOTAL", "unit": "NR"})
    df = _eurostat_to_series(raw, dim_filter={"unit": "NR", "c_resid": "TOTAL"})
    if df.empty:
        print("[Tourismus] Eurostat leer — verwende Amt für Statistik FL Daten")
        df = pd.DataFrame(_FL_TOURISM_NIGHTS, columns=["year", "value"])
    _save_cache("eurostat_tourism_nights_LI", df.to_dict("records"))
    return df


def fetch_eurostat_gdp_eur() -> pd.DataFrame:
    """BIP in EUR (Eurostat tec00001, Fallback: eigene Statistik)."""
    cached_df = _load_cache("eurostat_gdp_eur_LI", ttl_hours=24)
    if cached_df:
        return pd.DataFrame(cached_df)

    raw = _eurostat_fetch("tec00001", {"geo": "LI", "unit": "MIO_EUR"})
    df = _eurostat_to_series(raw, dim_filter={"unit": "MIO_EUR"})
    if df.empty:
        # Fallback: Näherungswerte aus bekannten Quellen (Amt für Statistik FL / OECD)
        print("[GDP EUR] Eurostat leer — verwende Näherungswerte")
        df = pd.DataFrame([
            (2005, 3_840), (2006, 4_210), (2007, 4_680), (2008, 4_920),
            (2009, 4_320), (2010, 4_590), (2011, 4_880), (2012, 4_760),
            (2013, 5_020), (2014, 5_180), (2015, 5_390), (2016, 5_580),
            (2017, 5_830), (2018, 6_100), (2019, 6_290), (2020, 5_960),
            (2021, 6_480), (2022, 7_010), (2023, 7_240),
        ], columns=["year", "value"])
    _save_cache("eurostat_gdp_eur_LI", df.to_dict("records"))
    return df


# ── OpenStreetMap Overpass ────────────────────────────────────────────────────

OSM_CATEGORIES = {
    "Restaurants":        'node["amenity"="restaurant"]',
    "Cafés":              'node["amenity"="cafe"]',
    "Hotels":             'node["tourism"="hotel"]',
    "Supermärkte":        'node["shop"="supermarket"]',
    "Museen":             'node["tourism"="museum"]',
    "Sehenswürdigkeiten": 'node["tourism"="attraction"]',
    "Aussichtspunkte":    'node["tourism"="viewpoint"]',
    "Kunstwerke":         'node["tourism"="artwork"]',
    "Kirchen":            'node["amenity"="place_of_worship"]',
    "Apotheken":          'node["amenity"="pharmacy"]',
    "Tankstellen":        'node["amenity"="fuel"]',
    "Geldautomaten":      'node["amenity"="atm"]',
    "E-Ladestationen":    'node["amenity"="charging_station"]',
    "Picknikplätze":      'node["tourism"="picnic_site"]',
    "Spielplätze":        'node["leisure"="playground"]',
}

# overpass-api.de lehnt automatisierte Abfragen teils mit 502 ab; die Schweizer
# Instanz (deckt Liechtenstein ab) antwortet zuverlässig und ist daher zuerst dran.
OVERPASS_URLS = [
    "https://overpass.osm.ch/api/interpreter",
    "https://overpass-api.de/api/interpreter",
]

def fetch_osm_poi_counts() -> dict[str, int]:
    """Fetch POI counts per category for Liechtenstein from Overpass API."""
    cached = _load_cache("osm_poi_counts_LI", ttl_hours=168)  # 1 Woche
    if cached:
        return cached

    import time as _time
    results = {}
    failed_in_a_row = 0

    for label, query_node in OSM_CATEGORIES.items():
        if failed_in_a_row >= 2:
            # Overpass nicht erreichbar/blockiert (502, Timeouts): nicht noch 13x warten
            print("[OSM] Overpass nicht erreichbar — breche ab")
            break
        overpass_query = f"""
[out:json][timeout:25];
area["ISO3166-1"="LI"][admin_level=2]->.li;
{query_node}(area.li);
out count;
"""
        for attempt in range(3):
            overpass_url = OVERPASS_URLS[attempt % len(OVERPASS_URLS)]
            try:
                _time.sleep(2)  # Overpass Rate-Limit: min. 1 Req/s, wir nehmen 2s Abstand
                resp = requests.post(
                    overpass_url,
                    data={"data": overpass_query},
                    timeout=30,
                    headers={"User-Agent": "LiechtensteinDashboard/1.0 (https://daten.li)"},
                )
                if resp.status_code in (429, 504):
                    wait = 15 * (attempt + 1)
                    print(f"[OSM] {label} {resp.status_code} — warte {wait}s")
                    _time.sleep(wait)
                    continue
                resp.raise_for_status()
                data = resp.json()
                count = data.get("elements", [{}])[0].get("tags", {}).get("total", 0)
                results[label] = int(count)
                failed_in_a_row = 0
                break
            except Exception as exc:
                print(f"[OSM] {label} error (Versuch {attempt+1}): {exc}")
                if attempt < 2:
                    _time.sleep(10)
                else:
                    failed_in_a_row += 1

    if not any(v > 0 for v in results.values()):
        return {}  # nur Fehlschläge/Nullen: nichts speichern, bestehende Daten behalten
    _save_cache("osm_poi_counts_LI", results)
    return results


# ── Open-Meteo ───────────────────────────────────────────────────────────────

def fetch_weather(year: int, lat: float = VADUZ_LAT, lon: float = VADUZ_LON) -> pd.DataFrame:
    """
    Fetch daily weather data from Open-Meteo archive for any FL municipality.
    Returns a DataFrame with columns:
      date, temp_max, temp_min, temp_mean, precipitation, wind_max
    """
    start = f"{year}-01-01"
    max_end = date.today() - timedelta(days=5)
    end_dt = min(date(year, 12, 31), max_end)

    if date(year, 1, 1) > max_end:
        return pd.DataFrame()

    end = end_dt.strftime("%Y-%m-%d")
    key = f"weather_{lat:.4f}_{lon:.4f}_{start}_{end}"
    cached = _load_cache(key, ttl_hours=6)
    if cached:
        df = pd.DataFrame(cached)
        df["date"] = pd.to_datetime(df["date"])
        return df

    url = "https://archive-api.open-meteo.com/v1/archive"
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start,
        "end_date": end,
        "daily": (
            "temperature_2m_max,temperature_2m_min,temperature_2m_mean,"
            "precipitation_sum,windspeed_10m_max"
        ),
        "timezone": "Europe/Zurich",
    }
    import time as _time
    for attempt in range(3):  # max 3 Versuche bei 429
        try:
            resp = requests.get(url, params=params, timeout=30)
            if resp.status_code == 429:
                wait = 10 * (attempt + 1)  # 10s, 20s, 30s
                print(f"[Open-Meteo] 429 — warte {wait}s (Versuch {attempt+1}/3)")
                _time.sleep(wait)
                continue
            resp.raise_for_status()
            d = resp.json().get("daily", {})

            df = pd.DataFrame({
                "date":          pd.to_datetime(d.get("time", [])),
                "temp_max":      d.get("temperature_2m_max", []),
                "temp_min":      d.get("temperature_2m_min", []),
                "temp_mean":     d.get("temperature_2m_mean", []),
                "precipitation": d.get("precipitation_sum", []),
                "wind_max":      d.get("windspeed_10m_max", []),
            })

            cache_rec = df.assign(date=df["date"].dt.strftime("%Y-%m-%d")).to_dict("records")
            _save_cache(key, cache_rec)
            return df

        except Exception as exc:
            print(f"[Open-Meteo] year={year} lat={lat} lon={lon} error: {exc}")
            if attempt < 2:
                _time.sleep(5)
    return pd.DataFrame()


def fetch_weather_monthly(year: int, lat: float = VADUZ_LAT, lon: float = VADUZ_LON) -> pd.DataFrame:
    """Return monthly aggregates from daily weather data for any coordinate."""
    df = fetch_weather(year, lat, lon)
    if df.empty:
        return df
    df["month"] = df["date"].dt.month
    df["month_name"] = df["date"].dt.strftime("%b")
    agg = df.groupby(["month", "month_name"], as_index=False).agg(
        temp_max=("temp_max", "mean"),
        temp_min=("temp_min", "mean"),
        temp_mean=("temp_mean", "mean"),
        precipitation=("precipitation", "sum"),
        wind_max=("wind_max", "mean"),
    )
    return agg.sort_values("month")
