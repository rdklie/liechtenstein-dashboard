"""
chat_data.py — freigegebene Datensätze und Abfrage-Engine für «Frage zu den Daten»
=================================================================================
Das KI-Modell erhält nur EIN Werkzeug, das eine JSON-Beschreibung einer Abfrage liefert. Dieses Modul validiert sie gegen eine feste Whitelist
von Datensätzen (keine freie SQL), führt sie schreibgeschützt auf bereits gespiegelten Daten aus und rechnet selbst (Summen, pro Kopf, Verhältnisse).
Das Modell rechnet nie.

Jeder Datensatz ist eine «tidy»-Tabelle: Dimensionen (Text, «Jahr» als ganze Zahl) und die Spalte «Wert». Viele Quelltabellen enthalten zusätzlich
Summenzeilen («… - Total»); die Engine füllt nicht angegebene Dimensionen deshalb mit dem Total auf und schliesst Totale bei einer Gruppierung aus,
damit nichts doppelt gezählt wird. Mehrdeutige Abfragen (mehrere Werte je Schlüssel) werden abgelehnt statt geraten.
"""

import math
import os
import re
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

import pandas as pd

MAX_RESULT_ROWS = 200
MAX_QUERIES = 4
MAX_DERIVE = 3
MAX_FILTER_VALUES = 40
CACHE_SECONDS = 1800
PER_VALUES = (1, 100, 1000, 100000, 1000000)


class QueryError(ValueError):
    """Fehler in der Abfragebeschreibung; die Meldung geht als Datenzeile an das Modell zurück (mit gültigen Werten), nie als Anweisung."""


@dataclass
class Dataset:
    key: str
    title: str
    unit: str                       # Anzeigeeinheit der Rohwerte
    source: str
    source_url: str
    loader: Callable[[], pd.DataFrame]
    dims: list = field(default_factory=list)        # Reihenfolge der Dimensionen (ohne «Wert»)
    totals: dict = field(default_factory=dict)       # Dimension → Label der Summenzeile (oder None)
    additive: bool = False           # Summieren über Dimensionen sinnvoll (Personen, CHF), nicht bei Median/Quote/Index
    scale: float = 1.0               # Faktor auf die Basiseinheit (Mio. CHF → 1e6)
    base_unit: str = ""              # Basiseinheit für Rechnungen («CHF», «Einwohner»)
    notes: list = field(default_factory=list)
    hint: str = ""                   # kurze Beschreibung für den Katalog


# ── Lesezugriff (schreibgeschützt) ────────────────────────────────────────────

def _ro_conn() -> sqlite3.Connection:
    path = os.environ.get("SQLITE_PATH") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache_data", "liechtenstein.sqlite")
    c = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    c.execute("PRAGMA query_only = ON")
    return c


def _px(key: str) -> pd.DataFrame:
    import db
    c = _ro_conn()
    try:
        r = c.execute("SELECT payload FROM px_cache WHERE path = ?", (key,)).fetchone()
    finally:
        c.close()
    if not r:
        raise LookupError(f"{key} nicht in der Datenbank")
    return db._unpack_df(r[0])


def _sql(sql: str) -> pd.DataFrame:
    c = _ro_conn()
    try:
        return pd.read_sql_query(sql, c)
    finally:
        c.close()


def _tidy(df: pd.DataFrame, dims: list) -> pd.DataFrame:
    out = df[dims + ["Wert"]].copy()
    out["Wert"] = pd.to_numeric(out["Wert"], errors="coerce")
    out = out.dropna(subset=["Wert"])
    if "Jahr" in out.columns:
        out["Jahr"] = pd.to_numeric(out["Jahr"], errors="coerce")
        out = out.dropna(subset=["Jahr"])
        out["Jahr"] = out["Jahr"].astype(int)
    for d in dims:
        if d != "Jahr":
            out[d] = out[d].astype(str).str.lstrip("-. ").str.strip()          # Quelllabels wie «- Deutschland», «... Kindergarten»
    return out.reset_index(drop=True)


def _px_loader(key: str, dims: list, rename: dict | None = None):
    def load():
        df = _px(key)
        if rename:
            df = df.rename(columns=rename)
        return _tidy(df, dims)
    return load


# ── Datensätze ────────────────────────────────────────────────────────────────

def _lohn(name: str, dims: list):
    return _px_loader("lohn:" + name, dims)


def _load_asyl_kosten() -> pd.DataFrame:
    import landesrechnung as LR
    t = LR.table()
    names = {c: "Aufwand: " + c for c in LR.COLS}
    rows = []
    for y, r in t.iterrows():
        rows.append((int(y), NETTO, float(r["netto"])))
        rows.append((int(y), "Aufwand brutto", float(r["aufwand"])))
        rows.append((int(y), "Ertrag", float(r["ertrag"])))
        for c in LR.COLS:
            rows.append((int(y), names[c], float(r[c])))
    return pd.DataFrame(rows, columns=["Jahr", "Position", "Wert"])


def _load_asyl_je_kopf() -> pd.DataFrame:
    import landesrechnung as LR
    d = LR.per_capita_live()
    if d.empty:
        raise LookupError("Bestand/Bevölkerung fehlen")
    labels = {"je_einwohner": "Netto-Aufwand je Einwohner (Wohnbevölkerung Jahresende)",
              "je_person_end": "Netto-Aufwand je Person im Bestand (Jahresende)",
              "je_person_avg": "Netto-Aufwand je Person im Bestand (Mittelbestand)"}
    rows = []
    for y, r in d.iterrows():
        for k, lab in labels.items():
            if pd.notna(r[k]):
                rows.append((int(y), lab, float(r[k])))
    return pd.DataFrame(rows, columns=["Jahr", "Kennzahl", "Wert"])


NETTO = "Netto-Aufwand (Aufwand minus Ertrag)"


def _load_police() -> pd.DataFrame:
    try:
        from tab_police import METRIC_LABELS
    except Exception:
        METRIC_LABELS = {}
    df = _sql("SELECT year AS Jahr, metric, value AS Wert, flag FROM police_metrics")
    df = df[df["flag"].isna() | (df["flag"].astype(str) == "")]
    df["Kennzahl"] = df["metric"].map(lambda m: METRIC_LABELS.get(m, m))
    return _tidy(df, ["Jahr", "Kennzahl"])


def _load_weltbank() -> pd.DataFrame:
    from data_fetcher import WB_INDICATORS
    df = _sql("SELECT year AS Jahr, indicator, value AS Wert FROM world_bank_data")
    df["Indikator"] = df["indicator"].map(lambda i: WB_INDICATORS.get(i, i))
    return _tidy(df, ["Jahr", "Indikator"])


def _load_klima() -> pd.DataFrame:
    df = _sql("SELECT muni AS Gemeinde, year AS Jahr, n_days, tmean, hot_days, summer_days, frost_days, ice_days, snow_days, heavy_rain_days, prec FROM clim_annual")
    df = df[df["n_days"] >= 360]                                  # nur vollständige Jahre
    labels = {"tmean": "Mitteltemperatur (°C)", "hot_days": "Heisse Tage (Tmax ≥ 30 °C)", "summer_days": "Sommertage (Tmax ≥ 25 °C)",
              "frost_days": "Frosttage (Tmin < 0 °C)", "ice_days": "Eistage (Tmax < 0 °C)", "snow_days": "Schneetage",
              "heavy_rain_days": "Starkniederschlagstage", "prec": "Niederschlag (mm)"}
    long = df.melt(id_vars=["Gemeinde", "Jahr"], value_vars=list(labels), var_name="Kennzahl", value_name="Wert")
    long["Kennzahl"] = long["Kennzahl"].map(labels)
    return _tidy(long, ["Jahr", "Gemeinde", "Kennzahl"])


def _load_tourismus() -> pd.DataFrame:
    a = _sql("SELECT year AS Jahr, value AS Wert FROM eurostat_tourism"); a["Kennzahl"] = "Ankünfte"
    n = _sql("SELECT year AS Jahr, value AS Wert FROM eurostat_tourism_nights"); n["Kennzahl"] = "Übernachtungen"
    return _tidy(pd.concat([a, n]), ["Jahr", "Kennzahl"])


def _load_staat_ausgaben() -> pd.DataFrame:
    try:
        df = _px("edu:spend_all")
    except LookupError:
        raise LookupError("Ausgaben nach Funktion noch nicht gespiegelt")
    df["Funktion"] = df["Funktion"].astype(str).str.strip().str.replace(r"^\d+\s+", "", regex=True)
    return _tidy(df, ["Jahr", "Funktion", "Teilsektor"])


def _build_registry() -> dict:
    ds = []
    add = ds.append
    add(Dataset("bevoelkerung", "Ständige Wohnbevölkerung nach Gemeinde, Staatsbürgerschaft und Geschlecht (31. Dezember)", "Personen",
                "Amt für Statistik Liechtenstein, Tabelle 211.002", "https://www.statistikportal.li/", _px_loader(
                    "pxs:li_pop_ctz_gem", ["Jahr", "Staatsbürgerschaft", "Geschlecht", "Wohngemeinde"]),
                ["Jahr", "Staatsbürgerschaft", "Geschlecht", "Wohngemeinde"],
                {"Staatsbürgerschaft": "Staatsbürgerschaft - Total", "Geschlecht": "Geschlecht - Total", "Wohngemeinde": "Liechtenstein"},
                additive=True, scale=1.0, base_unit="Einwohner", hint="Nenner für pro-Kopf-Rechnungen; Wohngemeinde «Liechtenstein» = ganzes Land"))
    for key, name, dim, extra in (
        ("lohn_branche", "branche", "Wirtschaftszweig", "nach Wirtschaftszweig"),
        ("lohn_wohnsitz", "wohnsitz", "Wohnsitz", "nach Wohnsitz (Liechtenstein / Ausland)"),
        ("lohn_alter", "alter", "Alter", "nach Altersklasse"),
        ("lohn_vollzeit_teilzeit", "vztz", "Vollzeit/Teilzeit", "nach Voll-/Teilzeit"),
        ("lohn_staatsbuergerschaft", "staat", "Staatsbürgerschaft", "nach Staatsbürgerschaft"),
        ("lohn_unternehmensgroesse", "gross", "Unternehmensgrösse", "nach Unternehmensgrösse"),
    ):
        base = ["Jahr", dim, "Geschlecht", "Kennzahl"]
        tot = {"Geschlecht": "Geschlecht - Total", dim: None}
        add(Dataset(key, f"Monatlicher Bruttolohn (Median, Quartile) {extra} und Geschlecht, Erhebungsjahre 2006–2024 alle 2 Jahre", "CHF je Monat",
                    "Amt für Statistik Liechtenstein, Lohnstatistik (Tabellen 291.xxx)", "https://www.statistikportal.li/de/publikation/loehne-2024/2024/01/v-1/p46907/pdf",
                    _lohn(name, base), base, tot, additive=False, base_unit="CHF je Monat",
                    notes=["Medianlöhne sind Zentralwerte und lassen sich nicht addieren oder mitteln.",
                           "Die Daten enthalten keine Beschäftigtenzahlen nach Branche und Geschlecht; ein Zerlegungsanteil (Struktureffekt) lässt sich daraus nicht berechnen."],
                    hint="Kennzahl: Median | 1. Quartil | 3. Quartil"))
    add(Dataset("asyl_kosten", "Aufwand des Landes für das Asylwesen (Landesrechnung Konto 590) nach Position", "CHF",
                "Landesrechnung (Rechenschaftsbericht der Regierung), Konto 590 Flüchtlingswesen", "https://www.llv.li/de/landesverwaltung/stabsstelle-regierungskanzlei/rechenschaftsbericht",
                _load_asyl_kosten, ["Jahr", "Position"], {"Position": NETTO}, additive=False, scale=1.0, base_unit="CHF",
                notes=["Nur Konto 590 der Landesrechnung (ohne Investitionsrechnung, ohne Gemeinden); keine Kosten je Gesuch.",
                       "Nicht mit den gesamten Sozialausgaben des Staates vergleichbar: andere Abgrenzung."],
                hint="Position: Netto-Aufwand | Aufwand brutto | Ertrag | Aufwand: <Teilkonto>"))
    add(Dataset("asyl_kosten_je_kopf", "Netto-Aufwand Asylwesen je Einwohner und je Person im Bestand (Näherung)", "CHF",
                "Landesrechnung Konto 590 und Amt für Statistik 233.302/211.002 (Berechnung des Dashboards)", "https://daten.li/?tab=migration",
                _load_asyl_je_kopf, ["Jahr", "Kennzahl"], {}, additive=False, base_unit="CHF",
                notes=["Näherung: Aufwand netto geteilt durch den Bestand zum Jahresende bzw. das Mittel aus zwei Jahresenden; kein Aufwand je einzelner Person."],
                hint="bereits berechnete Kennzahlen je Kopf (Tab Migration)"))
    add(Dataset("asyl_bestand", "Bestand der Asylbewerber, vorläufig Aufgenommenen und Schutzbedürftigen (Jahresende)", "Personen",
                "Amt für Statistik Liechtenstein, Tabelle 233.302", "https://www.statistikportal.li/",
                _px_loader("pxs:li_asyl_stock", ["Jahr", "Staatsbürgerschaft", "Geschlecht", "Bewilligungstyp"]),
                ["Jahr", "Staatsbürgerschaft", "Geschlecht", "Bewilligungstyp"],
                {"Staatsbürgerschaft": "Staatsbürgerschaft - Total", "Geschlecht": "Geschlecht - Total", "Bewilligungstyp": "Bewilligungstyp - Total"},
                additive=True, base_unit="Personen"))
    add(Dataset("staat_ausgaben", "Ausgaben des Staates nach Funktion (COFOG) und Teilsektor", "Mio. CHF",
                "Amt für Statistik Liechtenstein, Tabelle 501.031", "https://www.statistikportal.li/",
                _load_staat_ausgaben, ["Jahr", "Funktion", "Teilsektor"], {"Teilsektor": "S.13 Staat"}, additive=False, scale=1e6, base_unit="CHF",
                notes=["«Soziale Sicherung» (COFOG 10) umfasst auch die Sozialversicherungen (AHV, IV, Krankenversicherung usw.) und ist anders abgegrenzt als der Aufwand für das Asylwesen.",
                       "Die Funktionen sind nicht überschneidungsfrei summierbar mit «Ausgaben» (Total)."],
                hint="Funktion: Ausgaben (Total) | Soziale Sicherung | Bildungswesen | …; Teilsektor: Staat | Landesebene | Gemeindeebene | Sozialversicherungen"))
    add(Dataset("polizei_kennzahlen", "Kennzahlen der Landespolizei aus den Jahresberichten", "gemäss Kennzahl",
                "Landespolizei Liechtenstein, Jahresberichte (PDF)", "https://www.landespolizei.li/", _load_police, ["Jahr", "Kennzahl"], {}, additive=False,
                notes=["Einheit je Kennzahl gemäss Bericht (Fälle, Prozent, Personen); Berichtsjahre vor 2009 fehlen."]))
    add(Dataset("weltbank", "Wirtschafts- und Bevölkerungsindikatoren (Weltbank)", "gemäss Indikator", "Weltbank, World Development Indicators (CC BY 4.0)",
                "https://data.worldbank.org/", _load_weltbank, ["Jahr", "Indikator"], {}, additive=False))
    add(Dataset("klima_jahr", "Klimakennzahlen je Gemeinde und Jahr (ERA5-Gitterdaten, vollständige Jahre)", "gemäss Kennzahl",
                "Open-Meteo / Copernicus ERA5 (CC BY 4.0)", "https://open-meteo.com/", _load_klima, ["Jahr", "Gemeinde", "Kennzahl"], {}, additive=False,
                notes=["Modelldaten (ERA5-Gitter), keine Messungen einer Wetterstation."]))
    add(Dataset("tourismus", "Tourismus Liechtenstein: Ankünfte und Übernachtungen", "Anzahl", "Eurostat (tour_occ)", "https://ec.europa.eu/eurostat",
                _load_tourismus, ["Jahr", "Kennzahl"], {}, additive=False))
    add(Dataset("pisa", "PISA-Mittelwerte (Lesen, Mathematik, Naturwissenschaften); Liechtenstein nur 2000–2012, Vergleichsländer bis 2018", "Punkte", "OECD PISA über Weltbank EdStats",
                "https://data.worldbank.org/", _px_loader("edu:pisa", ["Jahr", "Land", "Fach"]), ["Jahr", "Land", "Fach"], {}, additive=False,
                notes=["Liechtenstein hat nur an den Erhebungen 2000–2012 teilgenommen."]))
    add(Dataset("arbeitslosenquote", "Arbeitslosenquote in % nach Geschlecht, Heimat und Monat", "%", "Amt für Statistik Liechtenstein, Tabelle 284.101",
                "https://www.statistikportal.li/", _px_loader("pxs:li_unemp", ["Jahr", "Geschlecht", "Heimat", "Monat"]),
                ["Jahr", "Geschlecht", "Heimat", "Monat"], {"Geschlecht": "Geschlecht - Total", "Heimat": "Heimat - Total"}, additive=False))
    add(Dataset("beschaeftigte", "Beschäftigte in Liechtenstein nach Wohnland (Zupendler), Staatsbürgerschaft und Geschlecht", "Personen",
                "Amt für Statistik Liechtenstein, Tabelle 281.005", "https://www.statistikportal.li/",
                _px_loader("pxs:li_commuters", ["Jahr", "Wohnland", "Staatsbürgerschaft", "Geschlecht"]),
                ["Jahr", "Wohnland", "Staatsbürgerschaft", "Geschlecht"],
                {"Wohnland": "Wohnland - Total", "Staatsbürgerschaft": "Staatsbürgerschaft - Total", "Geschlecht": "Geschlecht - Total"}, additive=True, base_unit="Personen"))
    return {d.key: d for d in ds}


DATASETS: dict = {}
_cache: dict = {}
_lock = threading.Lock()


def registry() -> dict:
    global DATASETS
    if not DATASETS:
        DATASETS = _build_registry()
    return DATASETS


def get_frame(key: str) -> pd.DataFrame:
    """Gecachter, schreibgeschützt geladener Datensatz."""
    d = registry()[key]
    now = time.time()
    with _lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < CACHE_SECONDS:
            return hit[1]
    df = d.loader()
    with _lock:
        _cache[key] = (now, df)
    return df


def clear_cache():
    with _lock:
        _cache.clear()


# ── Katalog für den System-Prompt ─────────────────────────────────────────────

def _short_vals(vals, n=8):
    vals = list(vals)
    return ", ".join(map(str, vals)) if len(vals) <= n else ", ".join(map(str, vals[:n])) + f", … ({len(vals)} Werte)"


def catalog_text(frames: Callable = get_frame) -> tuple:
    """(Katalogtext, verfügbare Schlüssel). Datensätze, die nicht geladen werden können, fehlen im Katalog."""
    lines, avail = [], []
    for k, d in registry().items():
        try:
            df = frames(k)
        except Exception:
            continue
        if df is None or df.empty:
            continue
        avail.append(k)
        parts = []
        for dim in d.dims:
            if dim == "Jahr":
                parts.append(f"Jahr {int(df['Jahr'].min())}–{int(df['Jahr'].max())}")
            else:
                vals = sorted(df[dim].unique(), key=str)
                tot = total_of(d, df, dim)
                shown = [v for v in vals if v != tot]
                if shown:
                    parts.append(f"{dim}: {_short_vals(shown)}" + (f" [Total: {tot}]" if tot else ""))
        lines.append(f"- {k} — {d.title} ({d.unit}). {'; '.join(parts)}." + (f" {d.hint}." if d.hint else ""))
    return "\n".join(lines), avail


# ── Abfrage-Engine ────────────────────────────────────────────────────────────

_TOTAL_RE = re.compile(r"(^|\s-\s)(total|gesamt)$")


def total_of(d: Dataset, df: pd.DataFrame, dim: str):
    """Label der Summenzeile einer Dimension: aus der Konfiguration, sonst automatisch («… - Total»)."""
    if dim == "Jahr":
        return None
    t = d.totals.get(dim)
    if t is not None and (df[dim] == t).any():
        return t
    hits = [v for v in pd.unique(df[dim]) if _TOTAL_RE.search(norm(v))]
    return hits[0] if len(hits) == 1 else None


def norm(s) -> str:
    s = str(s).casefold().strip()
    s = re.sub(r"^[\d.\s]+(?=[a-zäöü])", "", s)
    s = re.sub(r"\s+", " ", s)
    return s.replace("ß", "ss")


_SAFE = re.compile(r"[^\w .,()%/:+\-·–]")


def safe_text(s, n: int = 70) -> str:
    """Vom Modell gelieferte Beschriftungen (label, title, id): nur harmlose Zeichen. Plotly rendert Pseudo-HTML (<a href=…>), das darf nie ankommen."""
    return _SAFE.sub("", str(s))[:n].strip()


def _resolve(df: pd.DataFrame, dim: str, wanted) -> list:
    """Wunschwerte → tatsächliche Werte; exakt (normalisiert), sonst eindeutige Teilzeichenkette; sonst QueryError mit den gültigen Werten."""
    if not isinstance(wanted, list):
        wanted = [wanted]
    if len(wanted) > MAX_FILTER_VALUES:
        raise QueryError(f"zu viele Filterwerte für {dim} (max. {MAX_FILTER_VALUES})")
    actual = list(pd.unique(df[dim]))
    by_norm = {}
    for a in actual:
        by_norm.setdefault(norm(a), []).append(a)
    out = []
    for w in wanted:
        if dim == "Jahr":
            try:
                out.append(int(w))
            except (TypeError, ValueError, OverflowError):
                raise QueryError(f"Jahr muss eine ganze Zahl sein: {str(w)[:20]!r}")
            continue
        n = norm(w)
        hits = by_norm.get(n)
        if not hits:
            cand = [a for a in actual if n and n in norm(a)]
            non_total = [a for a in cand if "total" not in norm(a)]
            hits = cand if len(cand) == 1 else (non_total if len(non_total) == 1 else None)
        if not hits:
            raise QueryError(f"Wert {str(w)[:60]!r} für {dim} nicht gefunden; gültige Werte: " + "; ".join(map(str, sorted(map(str, actual))[:MAX_FILTER_VALUES])))
        out.extend(hits)
    return out


def run_query(q: dict, frames: Callable = get_frame) -> pd.DataFrame:
    """Eine Einzelabfrage → DataFrame mit group_by-Spalten und «Wert». Die Einheit steht im Dataset."""
    if not isinstance(q, dict):
        raise QueryError("Abfrage muss ein Objekt sein")
    key = q.get("dataset")
    d = registry().get(key)
    if d is None:
        raise QueryError(f"unbekannter Datensatz {str(key)[:40]!r}; erlaubt: " + ", ".join(registry()))
    try:
        df = frames(key)
    except Exception as e:
        raise QueryError(f"Datensatz {key} ist derzeit nicht verfügbar") from e
    filters = q.get("filters") or {}
    group_by = list(q.get("group_by") or [])
    agg = q.get("agg") or "none"
    if not isinstance(filters, dict) or not all(isinstance(g, str) for g in group_by):
        raise QueryError("filters muss ein Objekt, group_by eine Liste von Spaltennamen sein")
    if agg not in ("none", "sum"):
        raise QueryError("agg muss none oder sum sein")
    if agg == "sum" and not d.additive:
        raise QueryError(f"{key} ist nicht additiv (Median, Quote, Index): agg=sum nicht erlaubt")
    for c in list(filters) + group_by:
        if c not in d.dims:
            raise QueryError(f"unbekannte Spalte {str(c)[:40]!r} in {key}; Spalten: " + ", ".join(d.dims))
    if len(group_by) != len(set(group_by)):
        raise QueryError("group_by enthält Duplikate")
    work = df
    explicit_total = set()
    for c, wanted in filters.items():
        vals = _resolve(work, c, wanted)
        work = work[work[c].isin(vals)]
        tot = total_of(d, df, c)
        if tot is not None and tot in vals:
            explicit_total.add(c)
        if work.empty:
            raise QueryError(f"keine Daten für {c} = {vals[:5]}")
    for c in d.dims:
        if c in group_by:
            tot = total_of(d, df, c)
            if tot is not None and c not in explicit_total:
                work = work[work[c] != tot]
        elif c in filters:
            if work[c].nunique() > 1 and not (agg == "sum" and d.additive):
                raise QueryError(f"für {c} sind mehrere Werte gewählt: in group_by aufnehmen")
        else:
            tot = total_of(d, df, c)
            if tot is not None and (work[c] == tot).any():
                work = work[work[c] == tot]
            elif work[c].nunique() > 1:
                if agg == "sum" and d.additive:
                    continue
                raise QueryError(f"{c} muss gefiltert oder in group_by aufgenommen werden; gültige Werte: " + "; ".join(map(str, sorted(map(str, work[c].unique()))[:MAX_FILTER_VALUES])))
    if work.empty:
        raise QueryError("keine Daten für diese Auswahl")
    if group_by:
        grp = work.groupby(group_by, sort=True)["Wert"]
        if agg == "sum":
            res = grp.sum(min_count=1).reset_index()
        else:
            if (grp.size() > 1).any():
                raise QueryError("Abfrage nicht eindeutig (mehrere Werte je Gruppe): weitere Spalten filtern oder gruppieren")
            res = grp.first().reset_index()
    else:
        if agg == "sum":
            res = pd.DataFrame({"Wert": [work["Wert"].sum()]})
        else:
            if len(work) > 1:
                raise QueryError("Abfrage nicht eindeutig (mehrere Zeilen): weitere Spalten filtern oder in group_by aufnehmen")
            res = work[["Wert"]].reset_index(drop=True)
    res = res.dropna(subset=["Wert"])
    if len(res) > MAX_RESULT_ROWS:
        raise QueryError(f"zu viele Ergebniszeilen ({len(res)}, max. {MAX_RESULT_ROWS}): stärker einschränken")
    if res.empty:
        raise QueryError("keine Werte vorhanden")
    return res.reset_index(drop=True)


@dataclass
class Series:
    """Ein benanntes Zwischenergebnis: Tabelle mit Dimensionsspalten und «Wert» in der Einheit `unit` (Basiseinheit, falls `base`)."""
    df: pd.DataFrame
    unit: str
    label: str
    dataset: str = ""
    scale: float = 1.0
    base_unit: str = ""

    @property
    def dims(self) -> list:
        return [c for c in self.df.columns if c != "Wert"]


def _to_base(s: Series) -> Series:
    if s.scale == 1.0 and not s.base_unit:
        return s
    df = s.df.copy()
    df["Wert"] = df["Wert"] * s.scale
    return Series(df, s.base_unit or s.unit, s.label, s.dataset)


def derive(op: str, a: Series, b: Series | None, spec: dict) -> Series:
    label = safe_text(spec.get("label") or f"{op}")
    if op in ("ratio", "diff", "sum"):
        if b is None:
            raise QueryError(f"{op} braucht a und b")
        a2, b2 = _to_base(a), _to_base(b)
        join = list(spec.get("join") or [c for c in b2.dims if c in a2.dims])
        if not join and (a2.dims or b2.dims):
            raise QueryError("join fehlt: gemeinsame Spalten angeben (z. B. [\"Jahr\"])")
        for c in join:
            if c not in a2.dims or c not in b2.dims:
                raise QueryError(f"join-Spalte {str(c)[:30]!r} fehlt in a oder b")
        extra_b = [c for c in b2.dims if c not in join]
        if extra_b:
            raise QueryError(f"b hat zusätzliche Spalten {extra_b}: gleich gruppieren wie join oder filtern")
        if join:
            m = a2.df.merge(b2.df, on=join, suffixes=("_a", "_b"), how="inner")
        else:
            m = pd.DataFrame({"Wert_a": [a2.df["Wert"].iloc[0]], "Wert_b": [b2.df["Wert"].iloc[0]]})
        if m.empty:
            raise QueryError("a und b haben keine gemeinsamen Zeilen (z. B. andere Jahre)")
        per = spec.get("per", 1)
        if per not in PER_VALUES:
            raise QueryError(f"per muss einer von {PER_VALUES} sein")
        if op == "ratio":
            if (m["Wert_b"] == 0).any():
                m = m[m["Wert_b"] != 0]
            val = m["Wert_a"] / m["Wert_b"] * per
            unit = f"{a2.unit} je {'' if per == 1 else str(per) + ' '}{b2.unit}"
        elif op == "diff":
            val = m["Wert_a"] - m["Wert_b"]
            unit = a2.unit
        else:
            val = m["Wert_a"] + m["Wert_b"]
            unit = a2.unit
        out = m[[c for c in m.columns if c not in ("Wert_a", "Wert_b")]].copy()
        out["Wert"] = val
        return Series(out.reset_index(drop=True), unit, label)
    if op in ("compare_diff", "compare_ratio", "compare_pct"):
        col, left, right = spec.get("column"), spec.get("left"), spec.get("right")
        if col not in a.dims:
            raise QueryError(f"column {str(col)[:30]!r} ist keine Spalte des Zwischenergebnisses a")
        lv = _resolve(a.df, col, [left])[0]
        rv = _resolve(a.df, col, [right])[0]
        idx = [c for c in a.dims if c != col]
        piv = a.df.pivot_table(index=idx, columns=col, values="Wert", aggfunc="first") if idx else a.df.set_index(col)["Wert"].to_frame().T
        if lv not in piv.columns or rv not in piv.columns:
            raise QueryError("links/rechts nicht im Ergebnis vorhanden")
        piv = piv[[lv, rv]].dropna()
        if piv.empty:
            raise QueryError("keine Zeilen mit beiden Werten")
        if op == "compare_diff":
            val, unit = piv[lv] - piv[rv], a.unit
        elif op == "compare_ratio":
            val, unit = piv[lv] / piv[rv], f"Verhältnis ({lv} / {rv})"
        else:
            val, unit = (piv[lv] - piv[rv]) / piv[rv] * 100.0, f"% ({lv} gegenüber {rv})"
        out = piv.reset_index(drop=True) if not idx else piv.reset_index()
        out = out.drop(columns=[c for c in (lv, rv) if c in out.columns])
        out["Wert"] = val.values
        return Series(out.reset_index(drop=True), unit, label)
    raise QueryError(f"unbekannte Rechenart {str(op)[:30]!r}; erlaubt: ratio, diff, sum, compare_diff, compare_ratio, compare_pct")


@dataclass
class Result:
    columns: list                   # Dimensionsspalten
    values: list                    # Wertespalten (Anzeigenamen)
    units: dict                     # Wertespalte → Einheit
    rows: list                      # Liste von Dicts (Rohwerte)
    sources: list                   # [(Titel, URL)]
    notes: list
    formulas: list                  # menschenlesbare Beschreibung der Abfragen/Rechnungen
    title: str = ""


def execute(spec: dict, frames: Callable = get_frame) -> Result:
    """Kompletter Tool-Aufruf → Result. Wirft QueryError bei ungültiger Beschreibung."""
    if not isinstance(spec, dict):
        raise QueryError("Eingabe muss ein Objekt sein")
    queries = spec.get("queries")
    if not isinstance(queries, list) or not queries:
        raise QueryError("queries fehlt (Liste mit 1–4 Abfragen)")
    if len(queries) > MAX_QUERIES:
        raise QueryError(f"max. {MAX_QUERIES} Abfragen")
    series: dict = {}
    sources, notes, formulas = [], [], []
    for i, q in enumerate(queries):
        qid = (safe_text(q.get("id"), 12) or f"q{i + 1}") if isinstance(q, dict) else f"q{i + 1}"
        if qid in series:
            raise QueryError(f"doppelte id {qid}")
        df = run_query(q, frames)
        d = registry()[q["dataset"]]
        label = safe_text(q.get("label") or re.split(r" nach | \(|, ", d.title)[0])
        series[qid] = Series(df, d.unit, label, d.key, d.scale, d.base_unit)
        if (d.source, d.source_url) not in sources:
            sources.append((d.source, d.source_url))
        for n in d.notes:
            if n not in notes:
                notes.append(n)
        fl = q.get("filters") or {}
        formulas.append(f"{qid} = {d.key}" + (f" [{', '.join(f'{k}={v}' for k, v in fl.items())}]" if fl else "") + (f", nach {', '.join(q.get('group_by') or [])}" if q.get("group_by") else ""))
    der = spec.get("derive") or []
    if not isinstance(der, list) or len(der) > MAX_DERIVE:
        raise QueryError(f"derive: Liste mit höchstens {MAX_DERIVE} Rechnungen")
    for j, dv in enumerate(der):
        if not isinstance(dv, dict):
            raise QueryError("derive-Eintrag muss ein Objekt sein")
        did = safe_text(dv.get("id"), 12) or f"d{j + 1}"
        if did in series:
            raise QueryError(f"doppelte id {did}")
        a = series.get(dv.get("a"))
        b = series.get(dv.get("b")) if dv.get("b") is not None else None
        if a is None or (dv.get("b") is not None and b is None):
            raise QueryError("a/b müssen ids vorhandener Abfragen oder Rechnungen sein: " + ", ".join(series))
        series[did] = derive(str(dv.get("op")), a, b, dv)
        formulas.append(f"{did} = {dv.get('op')}({dv.get('a')}" + (f", {dv.get('b')}" if dv.get("b") is not None else "") + ")" + (f" je {dv.get('per')}" if dv.get("per") not in (None, 1) else ""))
    out_ids = spec.get("output")
    if not out_ids:
        out_ids = [list(series)[-1]]
    if not isinstance(out_ids, list) or len(out_ids) > 3 or not all(o in series for o in out_ids):
        raise QueryError("output: 1–3 ids aus " + ", ".join(series))
    outs = [series[o] for o in out_ids]
    dims_common = [c for c in outs[0].dims if all(c in o.dims for o in outs)]
    names = []
    merged = None
    for k, o in enumerate(outs):
        name = o.label if o.label not in names else f"{o.label} ({out_ids[k]})"
        names.append(name)
        part = o.df[dims_common + ["Wert"]].rename(columns={"Wert": name}) if dims_common else o.df[["Wert"]].rename(columns={"Wert": name})
        if dims_common:
            extra = [c for c in o.dims if c not in dims_common]
            if extra:
                raise QueryError(f"Ausgaben haben unterschiedliche Spalten ({extra}); gleich gruppieren")
            merged = part if merged is None else merged.merge(part, on=dims_common, how="outer")
        else:
            merged = part if merged is None else pd.concat([merged, part], axis=1)
    if dims_common:
        if "Jahr" in merged.columns:
            merged["Jahr"] = merged["Jahr"].astype(int)
        merged = merged.sort_values(dims_common).reset_index(drop=True)
    if len(merged) > MAX_RESULT_ROWS:
        raise QueryError("zu viele Ergebniszeilen")
    units = {n: o.unit for n, o in zip(names, outs)}
    rows = []
    for _, r in merged.iterrows():
        row = {}
        for c in merged.columns:
            v = r[c]
            if isinstance(v, (float,)) and (math.isnan(v) or math.isinf(v)):
                v = None
            elif hasattr(v, "item"):
                v = v.item()
            row[c] = v
        rows.append(row)
    return Result(dims_common, names, units, rows, sources, notes, formulas, safe_text(spec.get("title") or "", 120))


# ── Formatierung ──────────────────────────────────────────────────────────────

def fmt_number(v) -> str:
    if v is None:
        return "–"
    if isinstance(v, int) or (isinstance(v, float) and float(v).is_integer() and abs(v) >= 100):
        s = f"{int(round(v)):,}".replace(",", "’")
        return s
    a = abs(v)
    dec = 0 if a >= 1000 else 1 if a >= 100 else 2
    s = f"{v:,.{dec}f}".replace(",", "’")
    return s


def numbers_in(result: Result) -> set:
    """Alle Zahlen, die in Tabelle/Diagramm vorkommen (Rohwerte, gerundet, in Tausend/Mio.) plus Jahre, für die Textprüfung der Antwort."""
    out = set()
    for row in result.rows:
        for c, v in row.items():
            if isinstance(v, (int, float)) and v is not None:
                for scale in (1.0, 1e-3, 1e-6):
                    x = v * scale
                    out.add(round(x, 4))
                    for dec in (0, 1, 2, 3):
                        out.add(round(x, dec))
    return out


_NUM = re.compile(r"\d[\d’'`.,]*\d|\d")


def text_numbers(text: str) -> list:
    vals = []
    for m in _NUM.findall(text):
        s = m.replace("’", "").replace("'", "").replace("`", "")
        if s.count(",") == 1 and s.count(".") == 0 and len(s.split(",")[1]) != 3:
            s = s.replace(",", ".")
        else:
            s = s.replace(",", "")
        if s.count(".") > 1:
            s = s.replace(".", "")
        try:
            vals.append(float(s))
        except ValueError:
            continue
    return vals


def answer_numbers_ok(text: str, result: Result) -> bool:
    """Jede Zahl im Antworttext muss im Ergebnis vorkommen (Jahre und kleine Ganzzahlen ≤ 10 ausgenommen)."""
    allowed = numbers_in(result)
    years = {float(r[c]) for r in result.rows for c in result.columns if c == "Jahr" and r.get(c) is not None}
    for x in text_numbers(text):
        if x in years or (x.is_integer() and 0 <= x <= 10) or (x.is_integer() and 1900 <= x <= 2100):
            continue
        if any(abs(x - a) <= max(1e-9, abs(a) * 1e-9) for a in allowed):
            continue
        return False
    return True
