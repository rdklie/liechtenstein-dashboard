"""
police.py — Jahresberichte der Landespolizei Liechtenstein (2009–2025): Download, Textextraktion, Kennzahlen
============================================================================================================
Quelle: https://www.landespolizei.li/ueber-uns/jahresberichte (öffentliche PDFs; robots.txt erlaubt den Abruf).
Einmaliger, höflicher Import (2 s Pause, ein Request je Bericht); Rohdateien unter <Datenordner>/archive/police/.

Kennzahlen werden per Regeln aus dem PDF-Text gezogen. Zu jedem Wert werden Seitenzahl und Textausschnitt der Quelle
gespeichert; was sich nicht eindeutig finden lässt, bleibt leer (keine Schätzungen). Plausibilitätsprüfungen
(Vorjahreswerte im selben Bericht, Summen, Wertebereiche) markieren auffällige Werte in der Spalte «flag».

Definitionen (laut Berichten): Kriminalstatistik = «Anzeigenstatistik» (Straftaten mit Tatort Liechtenstein, Hellfeld), seit
2020 als «Straftaten- und keine Fallstatistik» bezeichnet; Tatverdächtige = ermittelte Personen (inkl. Personen ohne Wohnsitz in
Liechtenstein). Die Deliktsgruppen-Tabelle («Interpretierte Kriminalstatistik») hat sich mehrfach geändert (siehe DEF_NOTES).
"""

import hashlib
import json
import logging
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

import db

log = logging.getLogger("police")

LIST_URL = "https://www.landespolizei.li/ueber-uns/jahresberichte"
BASE = "https://www.landespolizei.li"
HEADERS = {"User-Agent": "LiechtensteinDashboard/1.0 (https://daten.li; einmaliger Abruf der Jahresberichte)"}
PAUSE = 2.0
SOURCE_NOTE = "Landespolizei Fürstentum Liechtenstein, Jahresberichte (landespolizei.li/ueber-uns/jahresberichte)"

# Hinweise zu Definitionswechseln, die im Tab angezeigt werden (nur belegte Beobachtungen aus den Berichten)
DEF_NOTES: dict[str, str] = {}


def archive_dir() -> Path:
    sqlite = os.environ.get("SQLITE_PATH")
    base = Path(sqlite).parent if sqlite else db.DEFAULT_SQLITE_PATH.parent
    d = base / "archive" / "police"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── Download ──────────────────────────────────────────────────────────────────

def list_reports() -> dict[int, str]:
    """{Jahr: PDF-URL} aus der Berichtsseite der Landespolizei."""
    r = requests.get(LIST_URL, headers=HEADERS, timeout=45)
    r.raise_for_status()
    out = {}
    for m in re.finditer(r'<a[^>]+href="([^"]*download_file[^"]*)"[^>]*>(.*?)</a>', r.text, re.S):
        label = re.sub(r"<[^>]+>|&nbsp;", " ", m.group(2))
        y = re.search(r"Jahresbericht\s+(20\d\d)", label)
        if y:
            href = m.group(1)
            out[int(y.group(1))] = href if href.startswith("http") else BASE + href
    return out


def download_all(only_missing: bool = True) -> tuple[dict[int, Path], dict[int, str]]:
    """Lädt fehlende Berichte (2 s Pause) → ({Jahr: Pfad}, {Jahr: Fehlermeldung})."""
    d = archive_dir()
    manifest_path = d / "manifest.json"
    manifest = json.loads(manifest_path.read_text("utf-8")) if manifest_path.exists() else {"files": {}, "source": SOURCE_NOTE}
    reports = list_reports()
    paths, errors = {}, {}
    for year in sorted(reports):
        pdf = d / f"jahresbericht_{year}.pdf"
        if pdf.exists() and only_missing:
            paths[year] = pdf
            continue
        time.sleep(PAUSE)
        try:
            r = requests.get(reports[year], headers=HEADERS, timeout=120)
            r.raise_for_status()
            if not r.content.startswith(b"%PDF"):
                raise ValueError("keine PDF-Datei")
            pdf.write_bytes(r.content)
            manifest["files"][pdf.name] = {"url": reports[year], "sha256": hashlib.sha256(r.content).hexdigest(),
                                           "bytes": len(r.content), "retrieved": datetime.utcnow().strftime("%Y-%m-%d")}
            paths[year] = pdf
            log.info("%d: %s (%.1f MB)", year, pdf.name, len(r.content) / 1e6)
        except Exception as e:
            errors[year] = str(e)[:150]
            log.error("%d: Download fehlgeschlagen: %s", year, e)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), "utf-8")
    return paths, errors


def read_pages(pdf: Path) -> list[str]:
    import logging as _l
    _l.getLogger("pypdf").setLevel(_l.ERROR)
    import pypdf
    return [(p.extract_text() or "") for p in pypdf.PdfReader(str(pdf)).pages]


# ── Text-Normalisierung ───────────────────────────────────────────────────────

def _norm(s: str) -> str:
    s = s.replace("’", "").replace("‘", "").replace("'", "").replace(" ", " ")
    s = s.replace("‐", "-").replace("‑", "-").replace("−", "-").replace("–", "-")
    return s


def _join(page: str) -> str:
    """Seitentext als Fliesstext: Trennstriche am Zeilenende entfernen, Zeilen mit Leerzeichen verbinden."""
    t = _norm(page)
    t = re.sub(r"(\w)\s?-\s*\n\s*(\w)", r"\1\2", t)
    return re.sub(r"\s+", " ", t)


def _int(s: str) -> int:
    return int(re.sub(r"[^\d]", "", s))


class Hit:
    __slots__ = ("value", "page", "text")

    def __init__(self, value, page, text):
        self.value, self.page, self.text = value, page, text[:240]


def _first(pages_joined: list[str], patterns: list[str], group: int = 1, conv=_int, lo=None, hi=None,
           from_page: int = 0) -> Hit | None:
    """Erster Treffer eines der Muster (in Reihenfolge) mit plausiblem Wertebereich; from_page: Suche erst ab dieser Seite (0-basiert)."""
    for pat in patterns:
        rx = re.compile(pat, re.I)
        for i, t in enumerate(pages_joined):
            if i < from_page:
                continue
            for m in rx.finditer(t):
                try:
                    v = conv(m.group(group))
                except (ValueError, TypeError):
                    continue
                if (lo is not None and v < lo) or (hi is not None and v > hi):
                    continue
                s = max(0, m.start() - 40)
                return Hit(v, i + 1, t[s:m.end() + 40])
    return None


def _row(pages: list[str], label: str, ncols: int = 2, min_cols: int | None = None) -> Hit | None:
    """Tabellenzeile «Label  a  b»: Zeile beginnt mit Label, danach ncols Zahlen → value = [Zahlen]."""
    rx = re.compile(r"^\s*" + label + r"\s+(-?[\d ]+?(?:\s+-?[\d ]+?){%d})\s*$" % ((min_cols or ncols) - 1), re.I)
    for i, p in enumerate(pages):
        for line in _norm(p).split("\n"):
            m = rx.match(line.strip())
            if m:
                nums = re.findall(r"-?\d+", m.group(1))
                if len(nums) >= (min_cols or ncols):
                    return Hit([int(x) for x in nums], i + 1, line.strip())
    return None


# ── Kennzahlen ────────────────────────────────────────────────────────────────

def parse_report(year: int, pages: list[str]) -> dict[str, Hit]:
    """Alle auffindbaren Kennzahlen eines Berichts: {Kennzahl: Hit(value, page, text)}."""
    J = [_join(p) for p in pages]
    out: dict[str, Hit] = {}

    def put(key, hit):
        if hit is not None:
            out[key] = hit

    # Kriminalkapitel steht im hinteren Berichtsteil (Vorwort/Kurzüberblick nennen teils Teilquoten)
    chapter = max(0, len(J) // 3)

    # Gesamtkriminalität (Straftatbestände nach StGB)
    put("straftaten_stgb", _first(J, [
        r"total ([\d]{3,5}) StGB-Straftatbest",
        r"([\d]{3,5}) Straftaten registriert",
        r"wurden (?:noch )?([\d]{3,5}) Straftaten (?:begangen|registriert)",
        r"(?:auf|um) [\d]+% auf ([\d]{3,5}) Straftatbest",
        r"auf ([\d]{3,5}) Straftatbest[äa]nde (?:zugenommen|abgenommen|zur[üu]ckgegangen)",
        r"([\d]{3,5}) Straftatbest[äa]nde zugenommen",
    ], lo=500, hi=3000, from_page=chapter))
    # Aufklärungsquote «bezogen auf die Gesamtkriminalität» (ab Bericht 2017 mit StGB + BMG, siehe DEF_NOTES)
    put("aufklaerungsquote_pct", _first(J, [
        r"Aufkl[äa]rungsrate ist (?:im Berichtsjahr )?mit (\d{2}) ?%",
        r"Aufkl[äa]rungsrate (?:ist )?[^.%]{0,80}?(?:auf|mit) (\d{2}) ?%",
        r"Aufkl[äa]rungsquote (?:ist )?[^.%]{0,80}?(?:auf|mit) (\d{2}) ?%",
        r"Aufkl[äa]rungsquote von (\d{2}) ?%",
        r"Aufkl[äa]rungsrate [^.]{0,120}?\(20\d\d: ?(\d{2}) ?%;",
    ], lo=20, hi=100, from_page=chapter))
    # 2009/2010: Quote «ohne Wirtschafts- und Betäubungsmitteldelikte» (andere Definition, nicht mit der obigen Reihe verbinden)
    put("aufklaerungsquote_alt_pct", _first(J, [r"Mit (\d{2}) ?% liegt die Aufkl[äa]rungsquote"], lo=20, hi=100, from_page=chapter))
    put("tatverdaechtige_stgb", _first(J, [
        r"(\d{3}) Personen (?:setzten|begingen|haben)[^.]{0,40}Tatbest[äa]nde nach dem Strafgesetzbuch",
        r"(\d{3}) Personen Straftaten nach dem Strafgesetzbuch begangen",
        r"(\d{3}) tatverd[äa]chtige Personen registriert",
        r"Berichtsjahr (?:setzten )?(\d{3}) Personen",
        r"(\d{3}) (?:Personen|Tatverd[äa]chtige) (?:wurden )?ermittelt",
    ], lo=100, hi=1500, from_page=chapter))
    pct = r"(\d{2}) ?(?:%|Prozent)"
    put("tv_anteil_li_pct", _first(J, [
        pct + r" der (?:ermittelten )?Tatverd[äa]chtigen (?:hatten )?die Liechten",
        r"hatten insgesamt " + pct + r" der ermittelten Tatverd[äa]chtigen die Liechten",
        pct + r" der ermittelten[^.]{0,40}Liechtensteiner",
        pct + r" der ermittelten Tatverd[äa]chtigen[^.]{0,60}?die liechtensteinische",
        pct + r" davon hatten die Liechten",
    ], lo=5, hi=95, from_page=chapter))
    put("tv_anteil_auslaender_pct", _first(J, [
        r"restlichen (?:gut |knapp |rund )?" + pct + r" (?:waren |besassen |hatten |[üu]ber |mit )?(?:eine |einer )?(?:ausl|Ausl)",
        pct + r" (?:\(20\d\d: ?\d+ ?%\) )?der ermittelten Tatverd[äa]chtigen (?:hatten |besassen )?eine ausl",
        pct + r" der tatverd[äa]chtigen Personen waren Ausl",
        r"mit (\d{2}) ?% auch der Prozentsatz der ermittelten Tatverd[äa]chtigen mit einer ausl",
        r"\((\d{2}) ?%\) eine ausl",
    ], lo=5, hi=95, from_page=chapter))
    put("tv_weiblich_pct", _first(J, [
        r"Anteil der weiblichen Tatverd[äa]chtigen[^.%]{0,160}?(?:mit|bei) (\d{1,2}) ?%",
    ], lo=5, hi=50, from_page=chapter))
    put("tv_minderjaehrig", _first(J, [
        r"wurden (\d{1,3}) \([^)]*\d{4}: ?\d+\) minderj[äa]hrige Tatverd",
        r"(\d{1,3}) minderj[äa]hrige Tatverd[äa]chtige",
    ], lo=1, hi=400, from_page=chapter))

    # Deliktsgruppen («Interpretierte Kriminalstatistik», Fliesstext je Unterkapitel 8.7.x/9.7.x): Wert (+ Vorjahreswert)
    def sections(header: str):
        for i, t in enumerate(J):
            for m in re.finditer(r"(\d+\.\d+\.\d+\.?) (?:" + header + r")\b", t):
                nxt = J[i + 1][:700] if i + 1 < len(J) else ""
                rest = t[m.end():] + " " + nxt
                n = re.search(r" \d+\.\d+\.\d+\.? [A-ZÄÖÜ]", rest)
                yield i, (rest[:n.start()] if n else rest[:1600]), t[max(0, m.start() - 10):m.end() + 60]

    def delikt(key, header, pats, lo, hi):
        """pats: (Regex, Gruppe Wert, Gruppe Vorjahr | None, Vorjahr steht VOR dem Wert?)"""
        for i, txt, head in sections(header):
            for pat, g_cur, g_prev in pats:
                m = re.search(pat, txt, re.I)
                if not m:
                    continue
                cur = int(m.group(g_cur))
                prev = int(m.group(g_prev)) if g_prev and m.group(g_prev) else None
                if lo <= cur <= hi:
                    out[key] = Hit([cur, prev], i + 1, (head + " … " + txt[max(0, m.start() - 20):m.end() + 30]))
                    return

    PV = r"(?: ?\(20\d\d: ?(\d+)\))?"
    delikt("delikt_wirtschaft", r"Wirtschaftsdelikte", [(r"auf (\d{2,4}) Tatbest[äa]nde[n]?" + PV, 1, 2)], 50, 800)
    delikt("delikt_vermoegen", r"Verm[öo]gens- und Eigentumsdelikte",
           [(r"von (\d{2,4}) auf (\d{2,4})\b", 2, 1), (r"auf (\d{2,4})" + PV + r"(?=[ .,])", 1, 2)], 100, 1500)
    delikt("delikt_gewalt", r"Gewalt- und Sexualdelikte|Gewaltdelikte",
           [(r"Gewaltdelikte[^.]{0,160}?(?:mit|auf) (\d{2,4}) Tatbest[a-zäöü]*[^.(]{0,30}" + PV, 1, 2)], 20, 800)
    delikt("delikt_sexual", r"Gewalt- und Sexualdelikte|Sexualdelikte",
           [(r"Sexualdelikte[^.]{0,120}?(?:mit|auf) (\d{1,3}) Tatbest[a-zäöü]*[^.(]{0,90}" + PV, 1, 2)], 1, 300)
    delikt("delikt_drogen", r"Bet[äa]ubungsmitteldelikte|Drogendelikte",
           [(r"(?:insgesamt |wurden )(\d{2,4}) Straftatbest[äa]nde" + PV, 1, 2)], 20, 2500)
    delikt("delikt_migration", r"Migrationsdelikte", [(r"(\d{1,3}) Tatbest[äa]nde[n]?" + PV, 1, 2)], 1, 400)

    # Notrufe / Einsätze
    put("notrufe", _first(J, [
        r"insgesamt ([\d]{4,6}) Notrufe",
        r"insgesamt ([\d]{4,6}) Meldungen entgegen",
        r"([\d]{4,6}) Notrufe (?:und|registriert)",
    ], lo=3000, hi=40000))
    put("einsaetze_lnez", _first(J, [
        r"(?:auf|insgesamt) ([\d]{4,6}) Eins[äa]tze (?:zugenommen|disponiert|abgenommen)",
        r"([\d]{4,6}) disponierte Eins[äa]tze",
    ], lo=1500, hi=20000))

    # Verkehrsunfälle: Tabelle «Verkehrsunfallstatistik» (2009–2023), ab 2024 nur noch Fliesstext
    for key, label in (("unfaelle_total", r"Verkehrsunf[äa]lle total[^\d]*?"),
                       ("unfaelle_sachschaden", r"davon Verkehrsunf[äa]lle mit Sachschaden[^\d]*?"),
                       ("unfaelle_verletzte_ereignisse", r"davon Verkehrsunf[äa]lle mit Verletzten[^\d]*?"),
                       ("verletzte", r"dabei verletzte Personen"),
                       ("unfaelle_toedlich", r"davon Verkehrsunf[äa]lle mit t[öo]dlichem Ausgang"),
                       ("verkehrstote", r"dabei Verkehrstote")):
        put(key, _row(pages, label, 2))
    # Fliesstext-Rückfall: «Die Anzahl Verkehrsunfälle ... auf 460 (2024: 442)», «Unfälle mit Verletzten ... auf 93 (2024: 98)»
    if "unfaelle_total" not in out:
        put("unfaelle_total", _first(J, [r"Anzahl Verkehrsunf[äa]lle[^.]{0,90}? auf (\d{3}) \(20\d\d: ?\d+\)"], lo=150, hi=900))
    if "unfaelle_verletzte_ereignisse" not in out:
        put("unfaelle_verletzte_ereignisse", _first(J, [r"Unf[äa]lle mit Verletzten[^.]{0,60}? auf (\d{2,3}) \(20\d\d: ?\d+\)"], lo=20, hi=300))
    if "verletzte" not in out:
        put("verletzte", _first(J, [r"verletzten Personen[^.]{0,50}? auf (\d{2,3})\b"], lo=20, hi=400))
    words = {"ein": 1, "eine": 1, "zwei": 2, "drei": 3, "vier": 4, "fünf": 5, "sechs": 6}
    if "verkehrstote" not in out:
        h = _first(J, [r"\b(zwei|drei|vier|fünf|sechs|eine|ein) Personen bei Verkehrsunf[äa]llen ums Leben",
                       r"\b(zwei|drei|vier|fünf|sechs) (?:Personen )?t[öo]dlich verletzt"], conv=lambda x: words[x.lower()])
        if h:
            out["verkehrstote"] = Hit([h.value, None], h.page, h.text)

    # Untersuchungshaften (Tabelle; ab 2024 mit mehrzeiligen Beschriftungen → Fliesstext)
    put("uhaft_total", _row(pages, r"Untersuchungshaften total", 2))
    for key, pat in (("uhaft_li", r"davon Liechtensteinische Staatsangeh[öo]rige (\d+) (\d+)"),
                     ("uhaft_ausl_fl", r"davon ausl\.? Staatsangeh[öo]rige mit Wohnsitz in FL (\d+) (\d+)"),
                     ("uhaft_ausl_ausland", r"davon ausl\.? Staatsangeh[öo]rige mit Wohnsitz im Ausland (\d+) (\d+)")):
        rx = re.compile(pat, re.I)
        for i, t in enumerate(J):
            m = rx.search(t)
            if m and "Untersuchungshaft" in " ".join(J[max(0, i - 1):i + 1]):
                out[key] = Hit([int(m.group(1)), int(m.group(2))], i + 1, t[max(0, m.start() - 30):m.end()])
                break
    return out


# Hauptgruppen der «Interpretierten Kriminalstatistik» (Reihenfolge der Berichte)
DELIKT_GROUPS = [
    ("Wirtschaftsdelikte", r"1\.?\s*Wirtschaftsdelikte"),
    ("Vermögens- und Eigentumsdelikte", r"2\.?\s*Verm[öo]gens\S* (?:u\.|und)\s*Eink?ommens?delikte|2\.?\s*Verm[öo]gens- ?und Eigentumsdelikte|2\.?\s*Verm[öo]gensdelikte"),
    ("Gewaltdelikte", r"3\.?\s*Gewaltdelikte"),
    ("Sexualdelikte", r"4\.?\s*Sexualdelikte"),
    ("Migrationsdelikte", r"5\.?\s*Migrationsdelikte"),
    ("Betäubungsmitteldelikte", r"(?:10|6|7|8)\.?\s*Bet[äa]ubungsmitteldelikte"),
]


def parse_delikte(year: int, pages: list[str]) -> list[dict]:
    """
    Zeilen der Deliktsgruppen-Tabelle mit ≥ 9 Zahlen: Tatbestände (Jahr, Vorjahr), Veränderung, geklärt, Tatverdächtige
    (total, unter 18, Ausländer). Nur Zeilen, deren Spaltenanordnung dem aktuellen Format entspricht; sonst keine Werte.
    """
    rows = []
    for name, rx in DELIKT_GROUPS:
        pat = re.compile(r"^\s*(?:" + rx + r")\s+(.*)$", re.I)
        for i, p in enumerate(pages):
            for line in _norm(p).split("\n"):
                m = pat.match(line.strip())
                if not m:
                    continue
                nums = [int(x) for x in re.findall(r"\d+", m.group(1).replace("- ", "-"))]
                if len(nums) >= 9:
                    rows.append({"year": year, "group": name, "page": i + 1, "text": line.strip()[:200],
                                 "offences": nums[0], "offences_prev": nums[1],
                                 "tv_total": nums[-3], "tv_under18": nums[-2], "tv_foreign": nums[-1]})
                    break
            else:
                continue
            break
    return rows


# ── Plausibilität ─────────────────────────────────────────────────────────────

def checks(year: int, vals: dict[str, Hit]) -> dict[str, str]:
    """Markiert auffällige Werte (Schlüssel → Hinweis)."""
    flags = {}
    v = lambda k: vals[k].value if k in vals else None
    li, ausl = v("tv_anteil_li_pct"), v("tv_anteil_auslaender_pct")
    if li is not None and ausl is not None and abs(li + ausl - 100) > 2:
        flags["tv_anteil_li_pct"] = flags["tv_anteil_auslaender_pct"] = f"Summe {li + ausl} % ≠ 100 %"
    if "unfaelle_total" in vals and "unfaelle_sachschaden" in vals and "unfaelle_verletzte_ereignisse" in vals:
        a, b, c = (vals[k].value[0] for k in ("unfaelle_total", "unfaelle_sachschaden", "unfaelle_verletzte_ereignisse"))
        if b + c > a + 2:
            flags["unfaelle_total"] = "Sachschaden + Verletzte > Total"
    if "uhaft_total" in vals and all(k in vals for k in ("uhaft_li", "uhaft_ausl_fl", "uhaft_ausl_ausland")):
        s = sum(vals[k].value[0] for k in ("uhaft_li", "uhaft_ausl_fl", "uhaft_ausl_ausland"))
        if s != vals["uhaft_total"].value[0]:
            flags["uhaft_total"] = f"Teilsummen {s} ≠ Total {vals['uhaft_total'].value[0]}"
    return flags


TABLE_TO_METRIC = {"Wirtschaftsdelikte": "delikt_wirtschaft", "Vermögens- und Eigentumsdelikte": "delikt_vermoegen",
                   "Gewaltdelikte": "delikt_gewalt", "Sexualdelikte": "delikt_sexual",
                   "Migrationsdelikte": "delikt_migration", "Betäubungsmitteldelikte": "delikt_drogen"}


def run(download: bool = True) -> int:
    """Download (nur fehlende), parsen, Querprüfung gegen Vorjahreswerte, in SQLite schreiben. → Exitcode"""
    import pandas as pd
    if download:
        paths, errors = download_all()
    else:
        paths = {int(re.search(r"(\d{4})", p.name).group(1)): p for p in archive_dir().glob("jahresbericht_*.pdf")}
        errors = {}
    manifest = json.loads((archive_dir() / "manifest.json").read_text("utf-8")).get("files", {}) \
        if (archive_dir() / "manifest.json").exists() else {}
    vals_by_year: dict[int, dict[str, Hit]] = {}
    delikte, reports = [], []
    for year in sorted(paths):
        pages = read_pages(paths[year])
        vals = parse_report(year, pages)
        rows = parse_delikte(year, pages)
        for r in rows:                                     # Tabellenzeilen füllen Lücken (v. a. 2024/2025)
            key = TABLE_TO_METRIC.get(r["group"])
            if key and key not in vals:
                vals[key] = Hit([r["offences"], r["offences_prev"]], r["page"], r["text"])
        vals_by_year[year] = vals
        delikte += [{"year": year, "grp": r["group"], "page": r["page"], "offences": r["offences"],
                     "offences_prev": r["offences_prev"], "tv_total": r["tv_total"], "tv_under18": r["tv_under18"],
                     "tv_foreign": r["tv_foreign"], "source_text": r["text"]} for r in rows]
        m = manifest.get(paths[year].name, {})
        reports.append({"year": year, "file": paths[year].name, "url": m.get("url", ""), "sha256": m.get("sha256", ""),
                        "bytes": paths[year].stat().st_size, "pages": len(pages), "retrieved": m.get("retrieved", ""), "error": ""})
        log.info("%d: %d Kennzahlen, %d Tabellenzeilen, %d Seiten", year, len(vals), len(rows), len(pages))
    for y, e in errors.items():
        reports.append({"year": y, "file": "", "url": "", "sha256": "", "bytes": 0, "pages": 0, "retrieved": "", "error": e})

    metrics = []
    for year, vals in vals_by_year.items():
        flags = checks(year, vals)
        for k, h in vals.items():
            value = h.value[0] if isinstance(h.value, list) else h.value
            prev = h.value[1] if isinstance(h.value, list) and len(h.value) > 1 else None
            flag = flags.get(k, "")
            # Querprüfung: nennt der Bericht einen Vorjahreswert, muss er zum Wert im Vorjahresbericht passen
            before = vals_by_year.get(year - 1, {}).get(k)
            if prev is not None and before is not None:
                bv = before.value[0] if isinstance(before.value, list) else before.value
                if abs(bv - prev) > 0.5:
                    flag = (flag + "; " if flag else "") + f"Vorjahreswert hier {prev:g}, im Bericht {year - 1}: {bv:g} (Korrektur/anderer Zählstand)"
            metrics.append({"year": year, "metric": k, "value": float(value), "prev": prev, "page": h.page,
                            "source_text": h.text, "flag": flag})
    if not metrics:
        log.error("Keine Kennzahlen gelesen")
        return 1
    db.write_police(pd.DataFrame(metrics), pd.DataFrame(delikte), pd.DataFrame(reports))
    return 0 if not errors else 2


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", handlers=[logging.StreamHandler(sys.stdout)])
    sys.exit(run(download="--no-download" not in sys.argv))
