"""
migration.py — Datenschicht für den Tab «Migration»
===================================================
Quellen (nur amtlich/international, jeweils mit Definition, Lizenz und Stand):
  * Eurostat (Dissemination-API, JSON-stat 2.0): Bevölkerung nach Staatsangehörigkeit (migr_pop1ctz) und
    Geburtsland (migr_pop3ctb), Einbürgerungen (migr_acq), Asylanträge (migr_asyappctza), Zu-/Abwanderung
    (migr_imm1ctz, migr_emi1ctz), Verdächtige/Verfolgte/Verurteilte nach Staatsangehörigkeit (crim_just_ctz),
    Erwerbslosenquote nach Geburtsland (lfsa_urgacob). Lizenz: CC BY 4.0 (© Europäische Union).
  * Weltbank, World Development Indicators: Internationaler Migrantenbestand (SM.POP.TOTL.ZS / SM.POP.TOTL, UN DESA)
    und Bevölkerung (SP.POP.TOTL). Lizenz: CC BY 4.0.
  * Amt für Statistik Liechtenstein (PXWeb, opendata.li): Wohnbevölkerung nach Staatsbürgerschaft, Grenzgänger,
    Wanderung, Einbürgerungen, Asyl, Arbeitslosigkeit. Lizenz: Namensnennung.
Alles wird vom Worker höchstens wöchentlich nach SQLite (px_cache) gespiegelt; die App ruft die APIs nicht auf.
Cache-Schlüssel: «es:<Datensatz>», «wb:migration», «pxs:<Name>» (PXWeb-Tabelle mit Auswahl, siehe MIG_PX).
"""

import json
import logging
import time
import urllib.parse

import pandas as pd
import requests

log = logging.getLogger(__name__)

ES_BASE = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/"
WB_BASE = "https://api.worldbank.org/v2/"
HEADERS = {"User-Agent": "LiechtensteinDashboard/1.0 (https://daten.li)"}
PAUSE = 1.0

_session = requests.Session()
_session.headers.update(HEADERS)

# ── Länder ────────────────────────────────────────────────────────────────────
# ISO3 → (Name, Eurostat-Code); die Länderauswahl im Tab nutzt durchgängig ISO3.
EU27 = {
    "BEL": ("Belgien", "BE"), "BGR": ("Bulgarien", "BG"), "CZE": ("Tschechien", "CZ"), "DNK": ("Dänemark", "DK"),
    "DEU": ("Deutschland", "DE"), "EST": ("Estland", "EE"), "IRL": ("Irland", "IE"), "GRC": ("Griechenland", "EL"),
    "ESP": ("Spanien", "ES"), "FRA": ("Frankreich", "FR"), "HRV": ("Kroatien", "HR"), "ITA": ("Italien", "IT"),
    "CYP": ("Zypern", "CY"), "LVA": ("Lettland", "LV"), "LTU": ("Litauen", "LT"), "LUX": ("Luxemburg", "LU"),
    "HUN": ("Ungarn", "HU"), "MLT": ("Malta", "MT"), "NLD": ("Niederlande", "NL"), "AUT": ("Österreich", "AT"),
    "POL": ("Polen", "PL"), "PRT": ("Portugal", "PT"), "ROU": ("Rumänien", "RO"), "SVN": ("Slowenien", "SI"),
    "SVK": ("Slowakei", "SK"), "FIN": ("Finnland", "FI"), "SWE": ("Schweden", "SE"),
}
EFTA = {"ISL": ("Island", "IS"), "LIE": ("Liechtenstein", "LI"), "NOR": ("Norwegen", "NO"), "CHE": ("Schweiz", "CH")}
OTHERS = {"USA": "USA", "CHN": "China", "RUS": "Russland"}
GROUPS = {
    "EU27": ("EU27", list(EU27)),
    "EWR": ("EWR (EU27 + Island, Liechtenstein, Norwegen)", list(EU27) + ["ISL", "LIE", "NOR"]),
    "DACHL": ("D-A-CH-L (Deutschland, Österreich, Schweiz, Liechtenstein)", ["DEU", "AUT", "CHE", "LIE"]),
}
ES_GEO = {iso: code for iso, (_, code) in {**EU27, **EFTA}.items()}
ISO3_OF_ES = {code: iso for iso, code in ES_GEO.items()}
COUNTRY_NAMES = {**{k: v[0] for k, v in EU27.items()}, **{k: v[0] for k, v in EFTA.items()}, **OTHERS}

# ── Eurostat-Datensätze ───────────────────────────────────────────────────────
# key → (Eurostat-Code, feste Filter). Geo = EU27 + EFTA wird immer gesetzt.
ES_SPECS = {
    "pop_cit":    ("migr_pop1ctz", {"citizen": ["TOTAL", "FOR", "NAT", "EU27_2020_FOR"], "age": "TOTAL", "sex": "T", "unit": "NR"}),
    "pop_birth":  ("migr_pop3ctb", {"c_birth": ["TOTAL", "FOR", "NAT", "EU27_2020_FOR"], "age": "TOTAL", "sex": "T", "unit": "NR"}),
    "acq":        ("migr_acq", {"citizen": "TOTAL", "age": "TOTAL", "sex": "T", "unit": "NR", "agedef": "COMPLET"}),
    "asylum":     ("migr_asyappctza", {"citizen": "TOTAL", "applicant": "TOTAL", "age": "TOTAL", "sex": "T", "unit": "PER"}),
    "imm":        ("migr_imm1ctz", {"citizen": "TOTAL", "age": "TOTAL", "sex": "T", "unit": "NR", "agedef": "COMPLET"}),
    "emi":        ("migr_emi1ctz", {"citizen": "TOTAL", "age": "TOTAL", "sex": "T", "unit": "NR", "agedef": "COMPLET"}),
    "crime":      ("crim_just_ctz", {}),
    "unemp_birth": ("lfsa_urgacob", {"c_birth": ["TOTAL", "NAT", "FOR", "EU27_2020_FOR"], "age": "Y15-64", "sex": "T", "unit": "PC"}),
}
ES_PREFIX = "es:"

WB_PREFIX = "wb:"
WB_KEY = "wb:migration"
WB_INDICATORS = ["SM.POP.TOTL.ZS", "SM.POP.TOTL", "SP.POP.TOTL"]

# ── PXWeb-Tabellen Liechtenstein (Amt für Statistik) mit fester Auswahl ───────
PXS_PREFIX = "pxs:"
_B = "Bevölkerung/Bevölkerungsstand/Stichtag 31 Dezember/"
MIG_PX = {
    "li_pop_ctz":      (_B + "211.002.px", {"Geschlecht": ["Geschlecht - Total"], "Wohngemeinde": ["Liechtenstein"]}),
    "li_pop_ctz_gem":  (_B + "211.002.px", {"Geschlecht": ["Geschlecht - Total"],
                                             "Staatsbürgerschaft": ["Staatsbürgerschaft - Total", "... Liechtenstein"]}),
    "li_nonperm":      (_B + "211.101.px", {"Geschlecht": ["Geschlecht - Total"], "Staatsbürgerschaft": ["Staatsbürgerschaft - Total"],
                                             "Bewilligungskategorie": ["Bewilligungskategorie - Total"]}),
    "li_age":          (_B + "211.006.px", {"Geschlecht": ["Geschlecht - Total"]}),
    "li_commuters":    ("Arbeit und Erwerb/Beschäftigung/281.005.px",
                        {"Voll-/ Teilzeit": ["Voll- und Teilzeit - Total"], "Geschlecht": ["Geschlecht - Total"],
                         "Staatsbürgerschaft": ["Staatsbürgerschaft - Total"]}),
    "li_migration":    ("Bevölkerung/Migration, Binnenwanderung/231.101.px",
                        {"Geschlecht": ["Geschlecht - Total"], "Altersklasse": ["Altersklasse - Total"],
                         "Staatsbürgerschaft": ["Staatsbürgerschaft - Total"]}),
    "li_naturalisation": ("Bevölkerung/Einbürgerungen, Registrierungen/232.001.px", {"Wohnsitz": ["Wohnsitz - Total"]}),
    "li_asylum":       ("Bevölkerung/Asylwesen/233.201.px",
                        {"Geschlecht": ["Geschlecht - Total"], "Staatsbürgerschaft": ["Staatsbürgerschaft - Total"],
                         "Monat": ["Jahr"]}),
    "li_asyl_stock":   ("Bevölkerung/Asylwesen/233.302.px", {"Geschlecht": ["Geschlecht - Total"], "Staatsbürgerschaft": ["Staatsbürgerschaft - Total"]}),
    "li_unemp":        ("Arbeit und Erwerb/Arbeitslosigkeit/284.101.px", {"Geschlecht": ["Geschlecht - Total"], "Monat": ["Durchschnitt"]}),
    # Amt für Statistik: eigene Bevölkerungsszenarien 2023–2060 (Prognosen-Tab, nie mit eigenen Projektionen vermischt)
    "li_scen":         ("Bevölkerung/Bevölkerungsszenarien/219.004d.px",
                        {"Heimat": ["Heimat - Total"], "Geschlecht": ["Geschlecht - Total"], "Altersklasse": ["Altersklasse - Total"]}),
}


def pxs_id(name: str) -> str:
    return PXS_PREFIX + name


def es_id(key: str) -> str:
    return ES_PREFIX + key


def all_sources() -> list[tuple[str, str]]:
    """(Bezeichnung, Cache-Schlüssel) aller Migrations-Quellen — der Worker spiegelt sie höchstens wöchentlich."""
    out = [(f"Eurostat {ES_SPECS[k][0]}", es_id(k)) for k in ES_SPECS]
    out.append(("Weltbank Migration", WB_KEY))
    out += [(f"LI PX {MIG_PX[k][0].rsplit('/', 1)[-1]} ({k})", pxs_id(k)) for k in MIG_PX]
    return out


# ── Eurostat ──────────────────────────────────────────────────────────────────

def fetch_es(key: str) -> tuple[pd.DataFrame, dict]:
    """Eurostat-Datensatz (JSON-stat 2.0) als Long-DataFrame: Dimensionscodes + 'Wert'; ISO3 in Spalte 'iso3'."""
    code, flt = ES_SPECS[key]
    params = [("format", "JSON"), ("lang", "EN")] + [("geo", g) for g in ES_GEO.values()]
    for k, v in flt.items():
        params += [(k, x) for x in (v if isinstance(v, list) else [v])]
    time.sleep(PAUSE)
    r = _session.get(ES_BASE + code, params=params, timeout=120)
    r.raise_for_status()
    d = r.json()
    ids, sizes = d["id"], d["size"]
    cats = {i: list(d["dimension"][i]["category"]["index"]) for i in ids}
    strides = [1] * len(sizes)
    for i in range(len(sizes) - 2, -1, -1):
        strides[i] = strides[i + 1] * sizes[i + 1]
    rows = []
    for k, v in d.get("value", {}).items():
        k = int(k)
        row = {ids[i]: cats[ids[i]][(k // strides[i]) % sizes[i]] for i in range(len(ids)) if ids[i] != "freq"}
        row["Wert"] = float(v)
        rows.append(row)
    df = pd.DataFrame(rows)
    if df.empty:
        raise ValueError(f"Eurostat {code}: keine Werte")
    df["iso3"] = df["geo"].map(ISO3_OF_ES)
    df["time"] = df["time"].astype(str)
    return df, {"path": es_id(key), "title": d.get("label", code), "dims": [c for c in df.columns if c != "Wert"],
                "unit": "", "reduced": [], "rows": len(df), "updated": d.get("updated", "")}


# ── Weltbank ──────────────────────────────────────────────────────────────────

def fetch_wb() -> tuple[pd.DataFrame, dict]:
    """Internationaler Migrantenbestand + Bevölkerung, alle Länder (ohne Aggregate): iso3, name, year, indicator, Wert."""
    time.sleep(PAUSE)
    meta = _session.get(WB_BASE + "country?format=json&per_page=400", timeout=60).json()[1]
    countries = {c["id"]: c["name"] for c in meta if c["region"]["id"] != "NA"}
    rows = []
    for ind in WB_INDICATORS:
        time.sleep(PAUSE)
        r = _session.get(f"{WB_BASE}country/all/indicator/{ind}?format=json&per_page=20000&date=1990:2025", timeout=120)
        r.raise_for_status()
        for x in r.json()[1] or []:
            if x["value"] is not None and x["countryiso3code"] in countries:
                rows.append({"iso3": x["countryiso3code"], "name": countries[x["countryiso3code"]],
                             "year": int(x["date"]), "indicator": ind, "Wert": float(x["value"])})
    df = pd.DataFrame(rows)
    if df.empty:
        raise ValueError("Weltbank: keine Werte")
    return df, {"path": WB_KEY, "title": "Weltbank WDI: Migrantenbestand und Bevölkerung", "dims": ["iso3", "name", "year", "indicator"],
                "unit": "", "reduced": [], "rows": len(df)}


def fetch_source(path: str) -> tuple[pd.DataFrame, dict]:
    """Einstiegspunkt für db._live_fetch."""
    if path.startswith(ES_PREFIX):
        return fetch_es(path[len(ES_PREFIX):])
    if path == WB_KEY:
        return fetch_wb()
    if path.startswith(PXS_PREFIX):
        from opendata import px_fetch
        px_path, select = MIG_PX[path[len(PXS_PREFIX):]]
        return px_fetch(px_path, select=select)
    raise KeyError(path)
