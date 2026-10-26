"""
factbook_import.py — Einmaliger Import: CIA World Factbook, Archiv 1990–2025, nur Liechtenstein
==============================================================================================
Das CIA World Factbook wurde am 4. Feb. 2026 eingestellt. Die Daten sind gemeinfrei (US-Regierungs-
publikation). Als Quelle dient der Open-Source-Datenbestand «CIA World Factbook Archive 1990–2025»
(MilkMp, MIT-Lizenz für den Code; Daten gemeinfrei), den das Projekt als SQL-Dumps auf GitHub
veröffentlicht: https://github.com/MilkMp/CIA-World-Factbooks-Archive-1990-2025 (Ordner data/).
Die Webseite worldfactbookarchive.org selbst wird NICHT abgerufen (robots.txt sperrt KI-Crawler).

Ablauf (einmalig, nicht Teil des täglichen Workers):
    python factbook_import.py            # lädt data/countries.sql, categories.sql und 36 Jahresdateien
                                         # (zusammen ~60 MB, sequentiell mit Pause), filtert Liechtenstein
Ergebnis
  * Rohdaten:  <Datenordner>/archive/factbook/liechtenstein_<Jahr>.json  (+ manifest.json mit URLs/SHA-256)
  * SQLite:    factbook_fields (Rohtext je Jahr/Feld) und factbook_values (geparste Kennzahlen je Jahr)
Bereits geladene Jahre werden übersprungen (Rohdatei vorhanden), der Abruf wiederholt sich also nicht.
"""

import gzip
import hashlib
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests

import db

log = logging.getLogger("factbook_import")

REPO_RAW = "https://raw.githubusercontent.com/MilkMp/CIA-World-Factbooks-Archive-1990-2025/HEAD/data"
HEADERS = {"User-Agent": "LiechtensteinDashboard/1.0 (https://daten.li; einmaliger Import, Rate-Limit 1 Req/s)"}
YEARS = range(1990, 2026)
PAUSE = 1.0
LI_CODE = "ls"          # FIPS 10-4
SOURCE_NOTE = ("CIA World Factbook (gemeinfrei, 1990–2025; eingestellt am 4.2.2026), "
               "via Archiv-Datenbestand github.com/MilkMp/CIA-World-Factbooks-Archive-1990-2025")

_ROW2 = re.compile(r"\((\d+), (\d+), N'((?:[^']|'')*)'\)")                                   # categories
_ROW5 = re.compile(r"\((\d+), (\d+), (\d+), N'((?:[^']|'')*)', N'((?:[^']|'')*)'\)", re.S)  # fields
_ROWC = re.compile(r"\((\d+), (\d+), N'([^']*)', N'((?:[^']|'')*)', N'([^']*)', (\d+)\)")   # countries


def archive_dir() -> Path:
    sqlite = os.environ.get("SQLITE_PATH")
    base = Path(sqlite).parent if sqlite else db.DEFAULT_SQLITE_PATH.parent
    d = base / "archive" / "factbook"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _get(url: str) -> bytes:
    time.sleep(PAUSE)
    r = requests.get(url, headers=HEADERS, timeout=120)
    r.raise_for_status()
    return r.content


def _unq(s: str) -> str:
    return s.replace("''", "'")


# ── Kennzahlen aus dem Rohtext ────────────────────────────────────────────────
# Jede Ausgabe nennt Werte mit Bezugsjahr, z. B. «$7.172 billion (2024 est.) $7.031 billion (2023 est.)».
# Das Bezugsjahr ist NICHT das Ausgabejahr (viele Werte bleiben über Jahre stehen) → wir speichern beides.

_MULT = {"trillion": 1e12, "billion": 1e9, "million": 1e6, "thousand": 1e3}
_YEAR = r"\((?:[A-Za-z]+\.? )?(\d{4,5})(?: est\.)?\)"          # (2024 est.) | (July 2003 est.) | (37256)
_RE_MONEY = re.compile(r"\$\s*([\d,]*\.?\d+)\s*(trillion|billion|million|thousand)?\s*" + _YEAR, re.I)
_RE_PCT = re.compile(r"(-?\d+(?:\.\d+)?)%\s*" + _YEAR)
_RE_COUNT = re.compile(r"(?<![\d,\.\$])(\d{1,3}(?:,\d{3})+|\d{3,})\s*" + _YEAR)
_RE_ANYYEAR = re.compile(_YEAR)


def _num(s: str) -> float | None:
    try:
        return float(s.replace(",", "").strip())
    except ValueError:
        return None


def _year(y: str) -> int | None:
    """'2024' → 2024; Excel-Datumsseriennummern aus alten Editionen (37256 = 2001-12-31) → Jahr."""
    n = int(y)
    if 1900 <= n <= 2100:
        return n
    if 20000 <= n <= 60000:
        return (datetime(1899, 12, 30) + timedelta(days=n)).year
    return None


def _pairs(text: str, regex: re.Pattern, money: bool = False) -> list[tuple[int, float]]:
    out = []
    for m in regex.finditer(text):
        v = _num(m.group(1))
        y = _year(m.group(3 if money else 2))
        if v is None or y is None:
            continue
        if money:
            v *= _MULT.get((m.group(2) or "").lower(), 1)
        out.append((y, v))
    return out


def _first_year(text: str) -> int | None:
    m = _RE_ANYYEAR.search(re.split(r"note\s*:", text, flags=re.I)[0])      # Jahre in Fussnoten zählen nicht
    return _year(m.group(1)) if m else None


def _single(text: str, pattern: str) -> float | None:
    m = re.search(pattern, text, re.I)
    if not m:
        return None
    g = next((x for x in m.groups() if x is not None), None)    # Muster mit Alternativen
    return _num(g) if g is not None else None


def parse_values(edition: int, fields: dict[str, str]) -> list[dict]:
    """
    Feldtexte einer Ausgabe → Zeilen {indicator, ref_year, value, unit}.
    Mehrfachangaben (Zeitreihen im Text) ergeben mehrere Zeilen, Einzelwerte eine Zeile.
    """
    low = {k.lower().strip(): v for k, v in fields.items()}
    rows: list[dict] = []

    def get(*names):
        for n in names:
            if n in low:
                return low[n]
        return ""

    def series(key, text, regex, unit, money=False):
        for y, v in _pairs(text, regex, money):
            rows.append({"indicator": key, "ref_year": y, "value": v, "unit": unit})

    def single(key, text, pattern, unit):
        v = _single(text, pattern)
        if v is not None:
            rows.append({"indicator": key, "ref_year": _first_year(text) or edition, "value": v, "unit": unit})

    series("gdp_ppp", get("gdp (purchasing power parity)", "gdp - purchasing power parity", "gdp"), _RE_MONEY, "USD", True)
    series("gdp_ppp_real", get("real gdp (purchasing power parity)"), _RE_MONEY, "USD (Preise 2015)", True)
    series("gdp_per_capita_ppp", get("gdp - per capita (ppp)", "gdp - per capita"), _RE_MONEY, "USD", True)
    series("gdp_per_capita_ppp_real", get("real gdp per capita"), _RE_MONEY, "USD (Preise 2015)", True)
    series("gdp_nominal", get("gdp (official exchange rate)"), _RE_MONEY, "USD", True)
    series("gdp_growth", get("gdp - real growth rate", "real gdp growth rate"), _RE_PCT, "%")
    series("inflation", get("inflation rate (consumer prices)"), _RE_PCT, "%")
    series("unemployment", get("unemployment rate"), _RE_PCT, "%")
    series("exports", get("exports"), _RE_MONEY, "USD", True)
    series("imports", get("imports"), _RE_MONEY, "USD", True)
    series("labor_force", get("labor force"), _RE_COUNT, "Personen")
    internet = get("internet users")
    series("internet_users", internet, _RE_COUNT, "Personen")

    t = get("population")
    v = _single(t, r"total\s*:\s*([\d,]{4,})") or _single(t, r"^[^\d]*([\d,]{4,})")
    if v is not None:
        rows.append({"indicator": "population", "ref_year": _first_year(t) or edition, "value": v, "unit": "Personen"})
    t = get("area")
    v = _single(t, r"total\s*:\s*([\d,\.]+)\s*sq km") or _single(t, r"^\s*([\d,\.]+)\s*sq km")
    if v is not None:
        rows.append({"indicator": "area_total", "ref_year": edition, "value": v, "unit": "km²"})
    single("life_expectancy", get("life expectancy at birth"), r"total population:\s*([\d\.]+)|^\s*([\d\.]+)\s*years", "Jahre")
    single("median_age", get("median age"), r"total\s*:\s*([\d\.]+)", "Jahre")
    single("birth_rate", get("birth rate"), r"^\s*([\d\.]+)\s*births", "je 1000 Einw.")
    single("death_rate", get("death rate"), r"^\s*([\d\.]+)\s*deaths", "je 1000 Einw.")
    single("net_migration", get("net migration rate"), r"(-?[\d\.]+)\s*migrant", "je 1000 Einw.")
    single("population_growth", get("population growth rate"), r"(-?[\d\.]+)%", "%")
    single("fertility_rate", get("total fertility rate"), r"^\s*([\d\.]+)\s*children", "Kinder je Frau")
    single("infant_mortality", get("infant mortality rate"), r"total:\s*([\d\.]+)|^\s*([\d\.]+)\s*deaths", "je 1000 Geburten")
    return rows


# ── Import ────────────────────────────────────────────────────────────────────

def run() -> int:
    out = archive_dir()
    manifest_path = out / "manifest.json"
    manifest = json.loads(manifest_path.read_text("utf-8")) if manifest_path.exists() else {"files": {}, "source": SOURCE_NOTE}

    todo = [y for y in YEARS if not (out / f"liechtenstein_{y}.json").exists()]
    log.info("Liechtenstein-Rohdateien vorhanden: %d, zu laden: %d", len(YEARS) - len(todo), len(todo))

    if todo:
        # 1. Länderliste (CountryID je Jahr) und Kategorien
        countries_raw = _get(f"{REPO_RAW}/countries.sql")
        manifest["files"]["countries.sql"] = hashlib.sha256(countries_raw).hexdigest()
        li_ids = {}
        for m in _ROWC.finditer(countries_raw.decode("utf-8")):
            cid, year, code, name, _src, _master = m.groups()
            if code.lower() == LI_CODE:
                li_ids[int(cid)] = int(year)
        log.info("Liechtenstein-Einträge im Archiv: %d (Jahre %s–%s)", len(li_ids), min(li_ids.values()), max(li_ids.values()))

        cats_raw = _get(f"{REPO_RAW}/categories.sql")
        manifest["files"]["categories.sql"] = hashlib.sha256(cats_raw).hexdigest()
        cat_title = {}   # (CategoryID) → Titel, nur für Liechtenstein-CountryIDs
        for m in _ROW3.finditer(cats_raw.decode("utf-8")):
            cat_id, country_id, title = m.groups()
            if int(country_id) in li_ids:
                cat_title[int(cat_id)] = _unq(title)

        # 2. Felder je Jahr
        for year in todo:
            ids = {cid for cid, y in li_ids.items() if y == year}
            if not ids:
                log.warning("%d: kein Liechtenstein-Eintrag im Archiv", year)
                continue
            url = f"{REPO_RAW}/fields/country_fields_{year}.sql.gz"
            try:
                raw = _get(url)
            except requests.RequestException as e:
                log.error("%d: Download fehlgeschlagen: %s", year, e)
                continue
            text = gzip.decompress(raw).decode("utf-8")
            rows = []
            for m in _ROW5.finditer(text):
                field_id, cat_id, country_id, name, content = m.groups()
                if int(country_id) in ids:
                    rows.append({"category": cat_title.get(int(cat_id), ""), "field": _unq(name), "content": _unq(content)})
            (out / f"liechtenstein_{year}.json").write_text(
                json.dumps({"year": year, "source": SOURCE_NOTE, "url": url, "fields": rows}, ensure_ascii=False, indent=1),
                encoding="utf-8")
            manifest["files"][f"country_fields_{year}.sql.gz"] = hashlib.sha256(raw).hexdigest()
            log.info("%d: %d Felder", year, len(rows))
        manifest["retrieved"] = datetime.utcnow().strftime("%Y-%m-%d")
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")

    return load_into_db(out)


_ROW3 = _ROW2  # (CategoryID, CountryID, 'Titel')


def load_into_db(out: Path) -> int:
    """Liest die Rohdateien und schreibt factbook_fields / factbook_values neu (idempotent)."""
    import pandas as pd
    field_rows, value_rows = [], []
    for f in sorted(out.glob("liechtenstein_*.json")):
        d = json.loads(f.read_text("utf-8"))
        year = d["year"]
        fields = {}
        for r in d["fields"]:
            field_rows.append({"year": year, "category": r["category"], "field": r["field"], "content": r["content"]})
            fields.setdefault(r["field"], r["content"])
        seen = set()
        for r in parse_values(year, fields):
            k = (r["indicator"], r["ref_year"])
            if k in seen:                      # erster Treffer pro Bezugsjahr gilt
                continue
            seen.add(k)
            value_rows.append({"year": year, **r})
    if not field_rows:
        log.error("Keine Rohdaten gefunden")
        return 1
    db.write_factbook(pd.DataFrame(field_rows), pd.DataFrame(value_rows))
    log.info("SQLite: %d Felder, %d Kennzahlen (%d Jahre)", len(field_rows), len(value_rows),
             len({r['year'] for r in field_rows}))
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                        handlers=[logging.StreamHandler(sys.stdout)])
    sys.exit(run())
