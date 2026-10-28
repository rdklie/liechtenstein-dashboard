"""
bildung.py — Bildungsdaten für den Tab «Bildung» (und das Korrelations-Labor)
============================================================================
Quellen
  * Amt für Statistik Liechtenstein (PXWeb etab.llv.li, opendata.li, CC BY): Schulkinder, Klassen, Schulpersonal, Abschlüsse Sekundarstufe II,
    Lernende, Studierende, Bildungsstand der Bevölkerung, Ausgaben des Staates für das Bildungswesen (COFOG 9).
  * PISA (OECD): Mittelwerte Lesen, Mathematik, Naturwissenschaften je Erhebung, über die Weltbank-Datenbank «Education Statistics» (EdStats,
    Weltbank-API Quelle 12, Stand 2024-06-25), die die OECD-Ergebnisse wiedergibt. Liechtenstein hat nur an den Erhebungen 2000–2012 teilgenommen.
Cache-Schlüssel: «edu:<Name>» in px_cache (vom Worker höchstens wöchentlich gespiegelt, die App liest nur aus SQLite).
"""

import re
import time

import pandas as pd
import requests

PREFIX = "edu:"
PISA_KEY = PREFIX + "pisa"
PAUSE = 0.4
HEADERS = {"User-Agent": "LiechtensteinDashboard/1.0 (https://daten.li)"}
WB_BASE = "https://api.worldbank.org/v2/"

_S = "Bildung/Schulen/"
EDU_PX = {
    "pupils":   (_S + "481.001.px", {"Geschlecht": ["Geschlecht - Total"], "Schulort": ["Schulort - Total"]}),
    "pupils_cit": (_S + "481.002.px", {"Geschlecht": ["Geschlecht - Total"]}),
    "classes":  (_S + "481.003.px", {"Schultyp": ["Schultyp - Total"]}),
    "grads":    (_S + "481.101.px", {"Geschlecht": ["Geschlecht - Total"]}),
    "staff":    (_S + "481.202.px", {"Schultyp": ["Schultyp - Total"], "Schulstufe": ["Schulstufen - Total"], "Geschlecht": ["Geschlecht - Total"]}),
    "students": ("Bildung/Hochschulen/482.007.px", {"Fächergruppe": ["Fächergruppe - Total"], "Geschlecht": ["Geschlecht - Total"], "Studienstufe": ["Studienstufe - Total"]}),
    "apprentices": ("Bildung/Berufliche Grundbildung/483.011.px", {"Bildungsfeld": ["Bildungfeld - Total"], "Geschlecht": ["Geschlecht - Total"]}),
    "attainment": ("Bildung/Bildungsstand/491.002d.px", {"Geschlecht": ["Geschlecht - Total"], "Fünfjahresklassen": ["Fünfjahresklassen - Total"]}),
    "spend":    ("Staat und Politik/Öffentliche Finanzen/501.031.px", {"Funktion": ["Ausgaben", " 9 Bildungswesen"]}),
    "spend_all": ("Staat und Politik/Öffentliche Finanzen/501.031.px", {}),                 # alle Funktionen (COFOG) × Teilsektor, für «Frage zu den Daten»
}

# PISA-Mittelwerte (Weltbank EdStats, OECD-Quelle): Land → ISO3; Indikator → Fach
PISA_INDICATORS = {"LO.PISA.REA": "Lesen", "LO.PISA.MAT": "Mathematik", "LO.PISA.SCI": "Naturwissenschaften"}
PISA_COUNTRIES = {"LIE": "Liechtenstein", "CHE": "Schweiz", "AUT": "Österreich", "DEU": "Deutschland"}
PISA_SOURCE = "OECD PISA, über Weltbank EdStats (Quelle 12, Stand 2024-06-25)"


def edu_id(name: str) -> str:
    return PREFIX + name


def all_sources() -> list[tuple[str, str]]:
    out = [(f"LI PX {EDU_PX[k][0].rsplit('/', 1)[-1]} ({k})", edu_id(k)) for k in EDU_PX]
    out.append(("PISA (OECD via Weltbank EdStats)", PISA_KEY))
    return out


def fetch_pisa() -> tuple[pd.DataFrame, dict]:
    s = requests.Session()
    s.headers.update(HEADERS)
    rows = []
    for ind, fach in PISA_INDICATORS.items():
        for iso in PISA_COUNTRIES:
            time.sleep(PAUSE)
            r = s.get(f"{WB_BASE}country/{iso}/indicator/{ind}", params={"format": "json", "per_page": 100, "date": "2000:2024"}, timeout=60)
            r.raise_for_status()
            j = r.json()
            for x in (j[1] if len(j) > 1 and j[1] else []):
                if x["value"] is not None:
                    rows.append({"iso3": iso, "Land": PISA_COUNTRIES[iso], "Fach": fach, "Jahr": int(x["date"]), "Wert": float(x["value"])})
    df = pd.DataFrame(rows)
    if df.empty:
        raise ValueError("PISA (Weltbank): keine Werte")
    return df, {"path": PISA_KEY, "title": "PISA: Mittelwerte Lesen/Mathematik/Naturwissenschaften (OECD via Weltbank EdStats)", "dims": ["iso3", "Land", "Fach", "Jahr"],
                "unit": "Punkte", "reduced": [], "rows": len(df)}


def fetch_source(path: str) -> tuple[pd.DataFrame, dict]:
    """Einstiegspunkt für db._live_fetch."""
    if path == PISA_KEY:
        return fetch_pisa()
    from opendata import px_fetch
    px_path, select = EDU_PX[path[len(PREFIX):]]
    return px_fetch(px_path, select=select)


# ── Lesehilfen (Tab und Korrelations-Labor) ───────────────────────────────────

def _g(name: str) -> pd.DataFrame:
    import db
    return db.get_px(edu_id(name), max_age_hours=None)[0]


def info(name: str):
    """(Titel, Stand/Abrufzeit) der gespiegelten Tabelle oder (None, None)."""
    import db
    r = db.read_px_cache(edu_id(name))
    if r is None:
        return None, None
    return r[1].get("title"), r[2]


def school_year_end(label: str):
    """«2005/06» → 2006, «2024/2025» → 2025, «2023» → 2023 (Kalenderjahr des Schuljahresendes, PISA-Testung im Frühjahr dieses Jahres)."""
    m = re.match(r"^\s*(\d{4})\s*/\s*(\d{2,4})\s*$", str(label))
    if m:
        a, b = int(m.group(1)), m.group(2)
        return int(b) if len(b) == 4 else (a // 100) * 100 + int(b) + (100 if int(b) < a % 100 else 0)
    m = re.match(r"^\s*(\d{4})\s*$", str(label))
    return int(m.group(1)) if m else None


def clean(s: str) -> str:
    return str(s).lstrip("-. ").strip()


def with_year(df: pd.DataFrame, col: str) -> pd.DataFrame:
    d = df.copy()
    d["year"] = d[col].map(school_year_end)
    return d.dropna(subset=["year", "Wert"]).assign(year=lambda x: x["year"].astype(int))


def pupils_by_stage() -> pd.DataFrame:
    """Schulkinder: year, Schultyp, Stufe (bereinigt), Wert."""
    d = _g("pupils")
    if d.empty:
        return d
    d = with_year(d, "Jahr")
    d["Stufe"] = d["Schulstufe"].map(clean)
    d["Typ"] = d["Schultyp"].map(lambda t: "Total" if "Total" in t else ("Öffentlich" if t.startswith("Öffentl") else "Privat"))
    return d[["year", "Typ", "Stufe", "Wert"]]


def citizenship() -> pd.DataFrame:
    """Schulkinder nach Staatsbürgerschaft: year, Stufe, Bürgerschaft (Total/LI/CH-AT-DE/Übrige), Wert."""
    d = _g("pupils_cit")
    if d.empty:
        return d
    d = with_year(d, "Jahr")
    d["Stufe"] = d["Schulstufe"].map(clean)
    d["Bürgerschaft"] = d["Staatsbürgerschaft"].map(lambda t: "Total" if "Total" in t else ("Liechtenstein" if t.strip() == "LI" else ("CH/AT/DE" if "CH" in t else "Übrige")))
    return d[["year", "Stufe", "Bürgerschaft", "Wert"]]


def nonli_share(stage: str = "Schulstufe - Total") -> pd.Series:
    """Anteil Schulkinder ohne liechtensteinische Staatsbürgerschaft (%) je Schuljahresende. stage: bereinigter Stufenname."""
    d = citizenship()
    if d.empty:
        return pd.Series(dtype=float)
    d = d[d["Stufe"] == clean(stage)]
    p = d.pivot_table(index="year", columns="Bürgerschaft", values="Wert", aggfunc="first")
    if "Total" not in p or "Liechtenstein" not in p:
        return pd.Series(dtype=float)
    return ((1 - p["Liechtenstein"] / p["Total"]) * 100).dropna().sort_index()


def nonli_share_sek1() -> pd.Series:
    """Anteil ohne liechtensteinische Staatsbürgerschaft in der Sekundarstufe I (Stufe der 15-Jährigen bei PISA, die meisten in der 9. Klasse)."""
    return nonli_share("Sekundarstufe I")


def pisa() -> pd.DataFrame:
    import db
    r = db.read_px_cache(PISA_KEY)
    return r[0] if r else pd.DataFrame()


def pisa_series(fach: str, iso: str = "LIE") -> pd.Series:
    d = pisa()
    if d.empty:
        return pd.Series(dtype=float)
    d = d[(d["Fach"] == fach) & (d["iso3"] == iso)]
    return pd.Series(d["Wert"].values, index=d["Jahr"].astype(int).values).sort_index()


def spend() -> pd.DataFrame:
    return _g("spend")
