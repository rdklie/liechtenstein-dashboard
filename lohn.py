"""
lohn.py — Lohndaten für den Tab «Lohn» (und das Korrelations-Labor)
===================================================================
Quellen
  * Amt für Statistik Liechtenstein, Lohnstatistik (PXWeb etab.llv.li, opendata.li, CC BY): monatlicher Bruttolohn (Median, 1./3. Quartil),
    Berichtsjahre 2006–2024 alle zwei Jahre, nach Wirtschaftszweig, Geschlecht, Voll-/Teilzeit, Wohnsitz, Staatsbürgerschaft, Aufenthaltsstatus,
    Alter, Unternehmensgrösse, Wohnort; Häufigkeitsverteilung der Bruttomonatslöhne (Tabellen 291.001 … 291.081).
  * Bundesamt für Statistik (BFS), Schweizerische Lohnstrukturerhebung (LSE): Zentralwert des monatlichen Bruttolohns der Schweiz, 2012–2024 (PXWeb-API, OGD).
  * Weltbank (FP.CPI.TOTL, Schweiz): Konsumentenpreisindex als Deflator für die Näherung «reale Löhne» (für Liechtenstein liegt in den genutzten Quellen kein
    eigener Preisindex vor).
Cache-Schlüssel «lohn:<Name>» in px_cache (vom Worker höchstens wöchentlich gespiegelt, die App liest nur aus SQLite).
"""

import time

import pandas as pd
import requests

PREFIX = "lohn:"
PAUSE = 0.4
HEADERS = {"User-Agent": "LiechtensteinDashboard/1.0 (https://daten.li)"}
BFS_URL = "https://www.pxweb.bfs.admin.ch/api/v1/de/px-x-0304010000_201/px-x-0304010000_201.px"
WB_URL = "https://api.worldbank.org/v2/country/CHE/indicator/FP.CPI.TOTL"
CH_KEY = PREFIX + "ch"
CPI_KEY = PREFIX + "cpi_ch"

_L = "Arbeit und Erwerb/Löhne/"
_VT = "Vollzeit/Teilzeit - Total"
LOHN_PX = {
    "branche":    (_L + "291.001.px", {"Vollzeit/Teilzeit": [_VT], "Wohnsitz": ["Wohnsitz - Total"]}),
    "wohnsitz":   (_L + "291.001.px", {"Vollzeit/Teilzeit": [_VT], "Wirtschaftszweig": ["Wirtschaftszweig - Total"]}),
    "vztz":       (_L + "291.001.px", {"Wohnsitz": ["Wohnsitz - Total"], "Wirtschaftszweig": ["Wirtschaftszweig - Total"]}),
    "staat":      (_L + "291.002.px", {"Vollzeit/Teilzeit": [_VT], "Wirtschaftszweig": ["Wirtschaftszweig - Total"]}),
    "gross":      (_L + "291.011.px", {"Vollzeit/Teilzeit": [_VT], "Wirtschaftssektor": ["Wirtschaftssektor - Total"]}),
    "alter":      (_L + "291.022.px", {"Vollzeit/Teilzeit": [_VT]}),
    "status":     (_L + "291.031.px", {"Vollzeit/Teilzeit": [_VT]}),
    "wohnort":    (_L + "291.041.px", {}),
    "verteilung": (_L + "291.081.px", {"Vollzeit/Teilzeit": [_VT]}),
}
SOURCE_TEXT = "Amt für Statistik Liechtenstein, Lohnstatistik (opendata.li, CC BY)"
BFS_TEXT = "Bundesamt für Statistik (BFS), Schweizerische Lohnstrukturerhebung (OGD, © BFS)"
PUB_URL = "https://www.statistikportal.li/de/publikation/loehne-2024/2024/01/v-1/p46907/pdf"
METH_URL = "https://www.statistikportal.li/statistikportal/publications/291-loehne/2024/01/1/291.2024.01.1_02_lohnstatistik-methodik-qualitaet.pdf"


def lohn_id(name: str) -> str:
    return PREFIX + name


def all_sources() -> list[tuple[str, str]]:
    out = [(f"LI PX {LOHN_PX[k][0].rsplit('/', 1)[-1]} ({k})", lohn_id(k)) for k in LOHN_PX]
    out.append(("BFS Lohnstrukturerhebung (Zentralwert Schweiz)", CH_KEY))
    out.append(("Weltbank FP.CPI.TOTL Schweiz", CPI_KEY))
    return out


def fetch_ch() -> tuple[pd.DataFrame, dict]:
    """BFS-LSE: Zentralwert des monatlichen Bruttolohns, Schweiz, Total aller Branchen und beruflichen Stellungen, nach Geschlecht."""
    q = {"query": [
        {"code": "Grossregion", "selection": {"filter": "item", "values": ["-1"]}},
        {"code": "Wirtschaftsabteilung", "selection": {"filter": "item", "values": ["-1"]}},
        {"code": "Berufliche Stellung", "selection": {"filter": "item", "values": ["-1"]}},
        {"code": "Zentralwert und andere Perzentile", "selection": {"filter": "item", "values": ["1"]}},
    ], "response": {"format": "json-stat2"}}
    time.sleep(PAUSE)
    r = requests.post(BFS_URL, json=q, headers=HEADERS, timeout=60)
    r.raise_for_status()
    j = r.json()
    years = list(j["dimension"]["Jahr"]["category"]["label"].values())
    sexes = list(j["dimension"]["Geschlecht"]["category"]["label"].values())
    vals = j["value"]
    rows = []
    i = 0
    for y in years:
        for s in sexes:
            rows.append({"Jahr": int(y), "Geschlecht": s, "Wert": float(vals[i]) if vals[i] is not None else None})
            i += 1
    df = pd.DataFrame(rows).dropna(subset=["Wert"])
    if df.empty:
        raise ValueError("BFS LSE: keine Werte")
    return df, {"path": CH_KEY, "title": j.get("label", "BFS Lohnstrukturerhebung"), "dims": ["Jahr", "Geschlecht"], "unit": "CHF je Monat", "reduced": [], "rows": len(df),
                "updated": j.get("updated", "")}


def fetch_cpi() -> tuple[pd.DataFrame, dict]:
    time.sleep(PAUSE)
    r = requests.get(WB_URL, params={"format": "json", "per_page": 100, "date": "2000:2025"}, headers=HEADERS, timeout=60)
    r.raise_for_status()
    j = r.json()
    rows = [{"Jahr": int(x["date"]), "Wert": float(x["value"])} for x in (j[1] if len(j) > 1 and j[1] else []) if x["value"] is not None]
    df = pd.DataFrame(rows)
    if df.empty:
        raise ValueError("Weltbank CPI Schweiz: keine Werte")
    return df, {"path": CPI_KEY, "title": "Konsumentenpreisindex Schweiz (Weltbank FP.CPI.TOTL, 2010 = 100)", "dims": ["Jahr"], "unit": "Index 2010=100", "reduced": [], "rows": len(df)}


def fetch_source(path: str) -> tuple[pd.DataFrame, dict]:
    """Einstiegspunkt für db._live_fetch."""
    if path == CH_KEY:
        return fetch_ch()
    if path == CPI_KEY:
        return fetch_cpi()
    from opendata import px_fetch
    px_path, select = LOHN_PX[path[len(PREFIX):]]
    return px_fetch(px_path, select=select)


# ── Lesehilfen ────────────────────────────────────────────────────────────────

def _g(name: str) -> pd.DataFrame:
    import db
    return db.get_px(lohn_id(name) if name not in (CH_KEY, CPI_KEY) else name, max_age_hours=None)[0]


def info(name: str):
    """(Titel, Stand/Abrufzeit) der gespiegelten Tabelle oder (None, None)."""
    import db
    r = db.read_px_cache(lohn_id(name) if name not in (CH_KEY, CPI_KEY) else name)
    if r is None:
        return None, None
    return r[1].get("title"), r[2]


def clean(s: str) -> str:
    return str(s).lstrip("-. ").strip()


def tidy(name: str) -> pd.DataFrame:
    """Gespiegelte Tabelle mit numerischem 'Jahr' und bereinigten Textspalten (ausser 'Wert')."""
    d = _g(name)
    if d.empty:
        return d
    d = d.copy()
    d["Jahr"] = pd.to_numeric(d["Jahr"], errors="coerce")
    return d.dropna(subset=["Jahr"]).assign(Jahr=lambda x: x["Jahr"].astype(int))


def sel(d: pd.DataFrame, **cond) -> pd.DataFrame:
    for k, v in cond.items():
        d = d[d[k] == v]
    return d


def series(d: pd.DataFrame) -> pd.Series:
    """Index Jahr, Werte; NaN (unterdrückt, <50 Beobachtungen) entfernt."""
    d = d.dropna(subset=["Wert"])
    return pd.Series(d["Wert"].values.astype(float), index=d["Jahr"].values).sort_index()


def median_series(geschlecht: str = "Geschlecht - Total", kennzahl: str = "Median") -> pd.Series:
    d = tidy("branche")
    if d.empty:
        return pd.Series(dtype=float)
    return series(sel(d, Wirtschaftszweig="Wirtschaftszweig - Total", Geschlecht=geschlecht, Kennzahl=kennzahl))


def gap_series(vztz: str = "Vollzeit/Teilzeit - Total") -> pd.Series:
    """Lohnunterschied Frauen/Männer in % des Männerlohns (Amt: «Lohn der Frauen liegt um x % tiefer»)."""
    if vztz == "Vollzeit/Teilzeit - Total":
        f, m = median_series("Frauen"), median_series("Männer")
    else:
        d = tidy("vztz")
        if d.empty:
            return pd.Series(dtype=float)
        base = sel(d, **{"Vollzeit/Teilzeit": vztz, "Kennzahl": "Median"})
        f, m = series(sel(base, Geschlecht="Frauen")), series(sel(base, Geschlecht="Männer"))
    return ((m - f) / m * 100).dropna()


def cpi_ch() -> pd.Series:
    d = _g(CPI_KEY)
    return pd.Series(d["Wert"].values, index=d["Jahr"].astype(int).values).sort_index() if not d.empty else pd.Series(dtype=float)


def real_median(base_year: int | None = None) -> pd.Series:
    """Medianlohn in Preisen des Basisjahres (Näherung: Deflator = Schweizer Konsumentenpreisindex)."""
    m, c = median_series(), cpi_ch()
    if m.empty or c.empty:
        return pd.Series(dtype=float)
    base_year = base_year or int(m.index.max())
    idx = c.reindex(m.index)
    return (m / idx * c[base_year]).dropna()


def ch_median(geschlecht: str = "Geschlecht - Total") -> pd.Series:
    d = _g(CH_KEY)
    if d.empty:
        return pd.Series(dtype=float)
    d = d[d["Geschlecht"] == geschlecht]
    return pd.Series(d["Wert"].values, index=d["Jahr"].astype(int).values).sort_index()
