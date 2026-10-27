"""
landesrechnung.py — Ausgaben des Landes für das Asylwesen (Landesrechnung, Konto 590 «Flüchtlingswesen»)
==========================================================================================================
Die Zahlen stammen aus den Konten der Erfolgsrechnung der Landesrechnung (Teil IV des jährlichen Rechenschaftsberichts der
Regierung, Regierungskanzlei / Amt für Finanzen). Es gibt dafür keine maschinenlesbare Reihe; die Werte wurden aus den
PDF-Berichten übernommen und gegen die Vorjahresspalte des jeweils folgenden Berichts und gegen die Summe der Teilkonten
abgeglichen (siehe Test unten: `check()`). Nichts ist geschätzt; Lücken bleiben Lücken.

Konten (Aufwand = brutto, Ertrag = Rückerstattungen):
  590.318.01 (bis 2010: 590.318.03) Betreuung Aufnahmezentrum (bis 2010 «Betreuung Flüchtlingszentrum»)
  590.318.03 Verfahrenskosten
  590.318.04 Rechtsberatungen, Verwaltungskosten der Hilfswerke
  590.366.00 Sozialhilfe für Asylsuchende / Rückkehrhilfe (bis 2010 «Sozialhilfe für Flüchtlinge / Rückkehrhilfe»)
  590.436.00 Rückerstattungen Lohnverwaltung Asylsuchende (Ertrag)
Investitionsrechnung: 590.503.00 «Wohnraum für Schutzbedürftige» (nur 2023–2025 vorhanden, getrennt ausgewiesen).

Nicht Teil dieses Kontos: Personal- und Sachaufwand der Amtsstellen (z. B. Ausländer- und Passamt, Landespolizei, Gerichte),
Schul-, Gesundheits- und Sozialleistungen ausserhalb von Konto 590 sowie Ausgaben der Gemeinden. Die «Internationale Flüchtlings- und
Migrationshilfe» (Konto 591.367.09, Hilfe im Ausland) steht separat und ist hier nicht enthalten.
"""

import hashlib
import logging
import re
from datetime import date, datetime

import pandas as pd

log = logging.getLogger("landesrechnung")

BUA = "https://bua.regierung.li/bua/Services/pdf/bua{y}_{n:03d}.pdf?nr={n}&year={y}&a=1"
LLV = "https://www.llv.li/serviceportal2/amtsstellen/stabstelle-regierungskanzlei/"

# Rechnungsjahr → (Dokument, URL, Seite im Rechenschaftsbericht, Hinweis)
SOURCES = {
    2025: ("Rechenschaftsbericht 2025, IV. Landesrechnung", LLV + "rb_2025_iv-landesrechnung-2025.pdf", 556, ""),
    2024: ("Rechenschaftsbericht 2024, IV. Landesrechnung", LLV + "iv-landesrechnung-2024.pdf", 574, ""),
    2023: ("Rechenschaftsbericht 2023, IV. Landesrechnung", LLV + "iv-landesrechnung-2023.pdf", 551, ""),
    2022: ("Rechenschaftsbericht 2022, IV. Landesrechnung", LLV + "iv_landesrechnung_v_antrag-web.pdf", 540, ""),
    2021: ("Rechenschaftsbericht 2021, IV. Landesrechnung", "https://www.llv.li/import/srk/rechenschaftsberichte/archiv-2021/iv_landesrechnung.pdf", 501, ""),
    2020: ("Rechenschaftsbericht 2020 (BuA Nr. 30/2021)", BUA.format(y=2021, n=30), 517, ""),
    2019: ("Rechenschaftsbericht 2019 (BuA Nr. 29/2020)", BUA.format(y=2020, n=29), 487, ""),
    2018: ("Rechenschaftsbericht 2018 (BuA Nr. 32/2019)", BUA.format(y=2019, n=32), 472, ""),
    2017: ("Rechenschaftsbericht 2017 (BuA Nr. 24/2018)", BUA.format(y=2018, n=24), 457, ""),
    2016: ("Rechenschaftsbericht 2016 (BuA Nr. 17/2017)", BUA.format(y=2017, n=17), 459, ""),
    2015: ("Rechenschaftsbericht 2015 (BuA Nr. 30/2016)", BUA.format(y=2016, n=30), 459, ""),
    2014: ("Rechenschaftsbericht 2014 (BuA Nr. 33/2015)", BUA.format(y=2015, n=33), 457, ""),
    2013: ("Rechenschaftsbericht 2013 (BuA Nr. 41/2014)", BUA.format(y=2014, n=41), 433, "Ertrag 2013 in der Rechnungsspalte leer (kein Ertrag ausgewiesen)"),
    2012: ("Rechenschaftsbericht 2012 (BuA Nr. 12/2013)", BUA.format(y=2013, n=12), 435, ""),
    2011: ("Rechenschaftsbericht 2011 (BuA Nr. 45/2012)", BUA.format(y=2012, n=45), 443, ""),
    2010: ("Rechenschaftsbericht 2010 (BuA Nr. 46/2011)", BUA.format(y=2011, n=46), 388, ""),
    2009: ("Vorjahresspalte im Rechenschaftsbericht 2010 (BuA Nr. 46/2011)", BUA.format(y=2011, n=46), 388,
           "nur als Vorjahreswert dieses Berichts übernommen; der Bericht zu 2009 selbst wurde nicht ausgewertet"),
}

# Rechnungsjahr: (Betreuung Aufnahmezentrum, Verfahrenskosten, Rechtsberatungen/Verwaltungskosten, Sozialhilfe/Rückkehrhilfe,
#                 Aufwand Total laut Bericht, Ertrag Rückerstattungen) — CHF
ROWS = {
    2009: (377564.30, 77343.73, 50086.25, 680914.93, 1185909.21, 33924.30),
    2010: (399861.30, 38964.57, 35821.45, 492908.30, 967555.62, 5739.25),
    2011: (432473.95, 48990.21, 43672.05, 459161.42, 984297.63, 125709.06),
    2012: (427000.00, 32232.33, 23666.70, 393293.30, 876192.33, 241964.79),
    2013: (420000, 40379, 24942, 283560, 768881, 0),
    2014: (418647, 33692, 23251, 289986, 765575, 51140),
    2015: (441818, 42158, 11355, 766613, 1261943, 23457),
    2016: (584344, 70155, 44430, 1083602, 1782530, 90425),
    2017: (761497, 43301, 28359, 1048976, 1882132, 21803),
    2018: (817729, 53994, 37296, 1314512, 2223531, 23954),
    2019: (799025, 48325, 40159, 788075, 1675584, 74341),
    2020: (887059, 28214, 37016, 615788, 1568077, 0),
    2021: (908504, 40899, 46480, 507391, 1503274, 331712),
    2022: (1299654, 68893, 36736, 3015833, 4421116, 62196),
    2023: (2035366, 74908, 47662, 6070024, 8227960, 184134),
    2024: (2457411, 60767, 48992, 8375078, 10942249, 348580),
    2025: (2498347, 56135, 56525, 10020449, 12631455, 272035),
}
COLS = ["Betreuung Aufnahmezentrum", "Verfahrenskosten", "Rechtsberatungen, Verwaltungskosten der Hilfswerke",
        "Sozialhilfe für Asylsuchende / Rückkehrhilfe"]

# Investitionsrechnung, Konto 590.503.00 «Wohnraum für Schutzbedürftige» (CHF); 2024 ohne Buchung, 2010–2022 kein solches Konto
INVEST = {2023: 1179681, 2024: 0, 2025: 214151}
INVEST_SRC = {2023: (SOURCES[2023][1], 565), 2024: (SOURCES[2024][1], 588), 2025: (SOURCES[2025][1], 570)}


def _db_years() -> pd.DataFrame:
    try:
        import db
        return db.read_lr_asyl()
    except Exception:
        return pd.DataFrame()


def all_rows() -> dict:
    """ROWS (von Hand geprüfte Konstante, hat immer Vorrang) plus die vom Worker gelesenen und geprüften neuen Jahre (lr_asyl, status ok)."""
    out = {}
    d = _db_years()
    if not d.empty:
        for r in d[d["status"] == "ok"].itertuples():
            out[int(r.year)] = (r.betreuung, r.verfahren, r.rechtsberatung, r.sozialhilfe, r.aufwand, r.ertrag)
    out.update(ROWS)
    return dict(sorted(out.items()))


def all_sources() -> dict:
    """SOURCES plus die automatisch gelesenen Jahre: Rechnungsjahr → (Dokument, URL, Seite, Hinweis)."""
    out = {}
    d = _db_years()
    if not d.empty:
        for r in d[d["status"] == "ok"].itertuples():
            out[int(r.year)] = (r.doc, r.url, int(r.page) if pd.notna(r.page) else None,
                                f"automatisch gelesen am {r.retrieved}; Summenprüfung und Abgleich mit der Vorjahresspalte bestanden")
    out.update(SOURCES)
    return dict(sorted(out.items()))


def pending() -> list[dict]:
    """Jahre, die der Worker gelesen hat, die aber die Prüfung nicht bestanden haben (warten auf Sichtprüfung, nicht veröffentlicht)."""
    d = _db_years()
    return [] if d.empty else d[d["status"] == "hold"].to_dict("records")


def table() -> pd.DataFrame:
    """Index Rechnungsjahr; Spalten COLS, aufwand (brutto), ertrag, netto (CHF)."""
    d = pd.DataFrame({y: v for y, v in all_rows().items()}, index=COLS + ["aufwand", "ertrag"]).T.astype(float)
    d["netto"] = d["aufwand"] - d["ertrag"]
    d.index.name = "year"
    return d.sort_index()


def series(kind: str = "netto") -> pd.Series:
    """kind: aufwand | ertrag | netto | sozialhilfe | betreuung (CHF je Rechnungsjahr)."""
    d = table()
    col = {"sozialhilfe": COLS[3], "betreuung": COLS[0]}.get(kind, kind)
    return d[col].rename(None)


def check(tol: float = 2.0) -> list[str]:
    """Summe der Teilkonten gegen Aufwand Total laut Bericht; leer = in Ordnung."""
    bad = []
    for y, v in all_rows().items():
        if abs(sum(v[:4]) - v[4]) > tol:
            bad.append(f"{y}: Teilkonten {sum(v[:4]):,.2f} ≠ Total {v[4]:,.2f}")
    return bad


def sources_table() -> pd.DataFrame:
    return pd.DataFrame([{"year": y, "Dokument": s[0], "url": s[1], "Seite": s[2], "Hinweis": s[3]} for y, s in sorted(all_sources().items(), reverse=True)])


def per_capita(bestand: pd.Series, pop: pd.Series) -> pd.DataFrame:
    """Kennzahlen je Person aus Aufwand netto (Konto 590) und Bestandsreihe/Bevölkerung (beide Index Jahr, Stichtag 31.12.).

    bestand_end  Bestand zum Jahresende t; bestand_avg  Mittel aus Bestand Jahresende t−1 und t (nur wenn beide vorhanden);
    je_person_end / je_person_avg  Aufwand netto / Nenner (CHF); je_einwohner  Aufwand netto / Wohnbevölkerung Jahresende (CHF).
    """
    d = table()[["netto"]].copy()
    b = bestand.astype(float)
    d["bestand_end"] = b.reindex(d.index)
    prev = b.copy()
    prev.index = prev.index + 1                       # Wert des Vorjahres auf das Folgejahr legen
    d["bestand_avg"] = ((b + prev.reindex(b.index)) / 2).reindex(d.index)
    d["pop"] = pop.astype(float).reindex(d.index)
    d["je_person_end"] = d["netto"] / d["bestand_end"]
    d["je_person_avg"] = d["netto"] / d["bestand_avg"]
    d["je_einwohner"] = d["netto"] / d["pop"]
    return d


def per_capita_live() -> pd.DataFrame:
    """per_capita() mit Bestand (Amt für Statistik 233.302, Total aller Bewilligungstypen) und ständiger Wohnbevölkerung (211.002) aus der Datenbank."""
    import db
    from migration import pxs_id
    st = db.get_px(pxs_id("li_asyl_stock"), max_age_hours=None)[0]
    pp = db.get_px(pxs_id("li_pop_ctz"), max_age_hours=None)[0]
    if st.empty or pp.empty:
        return pd.DataFrame()
    st = st[st["Bewilligungstyp"] == "Bewilligungstyp - Total"].dropna(subset=["Wert"])
    pp = pp[pp["Staatsbürgerschaft"].astype(str).str.contains("Total")].dropna(subset=["Wert"])
    b = pd.Series(st["Wert"].values, index=st["Jahr"].astype(int).values).sort_index()
    p = pd.Series(pp["Wert"].values, index=pp["Jahr"].astype(int).values).sort_index()
    return per_capita(b, p)


# ── Automatische Nachführung (Worker, jährlich) ────────────────────────────────
# Grenze der Automatik: Gelesen wird nur das bekannte Layout (Konten 590.318.01/.03/.04, 590.366.00, 590.436.00 mit je genau drei Zahlen
# Rechnung/Voranschlag/Vorjahr). Übernommen wird ein Jahr nur, wenn (1) die Teilkonten das Total ergeben, (2) die Vorjahresspalte
# des neuen Berichts mit unseren bereits geprüften Vorjahreswerten übereinstimmt und (3) das Berichtsjahr im Spaltenkopf stimmt.
# Alles andere bleibt als «hold» in lr_asyl und erscheint im Tab als «wartet auf Prüfung» — nichts wird veröffentlicht.
# Die Investitionsrechnung (590.503.00) wird nicht automatisch gelesen (INVEST bleibt von Hand).

LISTING = "https://www.llv.li/de/landesverwaltung/stabsstelle-regierungskanzlei/rechenschaftsbericht/"
LLV_BASE = "https://www.llv.li"
HEADERS = {"User-Agent": "LiechtensteinDashboard/1.0 (https://daten.li; jaehrliche Pruefung auf neuen Rechenschaftsbericht)"}
SUB_ROLES = {"590.318.01": 0, "590.318.03": 1, "590.318.04": 2, "590.366.00": 3, "590.436.00": "ertrag"}
_NUM = r"-?\d{1,3}(?:'\d{3})+|-?\d+"


def _amounts(txt: str) -> list[int]:
    return [int(x.replace("'", "")) for x in re.findall(_NUM, txt)]


def parse_konto590(pages: list[str], year: int) -> dict:
    """
    Konto 590 aus den Seitentexten des Berichts «IV. Landesrechnung» lesen.
    → {"page": gedruckte Seite, "cur": (b, v, r, s, aufwand, ertrag), "prev": (… dasselbe, Vorjahresspalte), "pdf_page": Index}
    Wirft ValueError mit lesbarer Begründung, wenn etwas nicht eindeutig ist.
    """
    hit = None
    for i, t in enumerate(pages):
        if "590.318.01" in t and "590.436.00" in t and re.search(r"590\s+Fl.chtlingswesen", t):
            hit = (i, t)
            break
    if hit is None:
        raise ValueError("Seite mit Konto 590 (Erfolgsrechnung) nicht gefunden")
    i, t = hit
    if f"Rechnung {year}" not in t or f"Rechnung {year - 1}" not in t:
        raise ValueError(f"Spaltenkopf «Rechnung {year} … Rechnung {year - 1}» nicht gefunden")
    m = re.search(r"^\s*(\d{3,4})\s*\|", t) or re.search(r"\|\s*(\d{3,4})\s*$", t.strip(), re.M)
    page = int(m.group(1)) if m else None
    lines = [ln.strip() for ln in t.replace("\r", "").split("\n")]
    start = next((k for k, ln in enumerate(lines) if re.match(r"590\s+Fl.chtlingswesen\b", ln)), None)
    if start is None:
        raise ValueError("Kopfzeile «590 Flüchtlingswesen» nicht gefunden")
    head = _amounts(re.sub(r"^590\s+Fl.chtlingswesen", "", lines[start]))
    if len(head) != 6:
        raise ValueError(f"Kopfzeile 590 hat {len(head)} statt 6 Zahlen")
    cur, prev = [None] * 6, [None] * 6
    cur[4], cur[5], prev[4], prev[5] = head[0], head[1], head[4], head[5]
    seen = set()
    for ln in lines[start + 1:]:
        if re.match(r"591\b", ln):
            break
        mm = re.match(r"(590\.\d{3}\.\d{2})\b(.*)$", ln)
        if not mm:
            continue
        code = mm.group(1)
        if code not in SUB_ROLES:
            raise ValueError(f"unbekanntes Teilkonto {code}")
        nums = _amounts(re.sub(r"\.{2,}", " ", mm.group(2)))
        if len(nums) != 3:
            raise ValueError(f"{code}: {len(nums)} statt 3 Zahlen (Spalte leer oder Layout geändert)")
        role = SUB_ROLES[code]
        k = 5 if role == "ertrag" else role
        cur[k], prev[k] = nums[0], nums[2]
        seen.add(code)
    if seen != set(SUB_ROLES):
        raise ValueError("Teilkonten fehlen: " + ", ".join(sorted(set(SUB_ROLES) - seen)))
    return {"page": page, "cur": tuple(cur), "prev": tuple(prev), "pdf_page": i + 1}


def validate(parsed: dict, year: int, known: dict, tol: float = 2.0) -> list[str]:
    """Prüfungen vor der Übernahme; leere Liste = bestanden."""
    bad = []
    cur, prev = parsed["cur"], parsed["prev"]
    if abs(sum(cur[:4]) - cur[4]) > tol:
        bad.append(f"Teilkonten {sum(cur[:4]):,} ≠ Total {cur[4]:,}")
    if abs(sum(prev[:4]) - prev[4]) > tol:
        bad.append(f"Vorjahresspalte: Teilkonten {sum(prev[:4]):,} ≠ Total {prev[4]:,}")
    if (year - 1) not in known:
        bad.append(f"kein geprüfter Vorjahreswert {year - 1} zum Abgleich")
    else:
        k = known[year - 1]
        diffs = [f"{n}: Bericht {p:,} ≠ gespeichert {float(kv):,.0f}" for n, p, kv in zip(COLS + ["Aufwand", "Ertrag"], prev, k) if abs(p - float(kv)) > 1]
        if diffs:
            bad.append("Vorjahresspalte weicht von den gespeicherten Werten ab (Korrektur oder Layoutwechsel?): " + "; ".join(diffs))
    if not parsed.get("page"):
        bad.append("gedruckte Seitenzahl nicht lesbar")
    if min(cur[:5]) < 0 or cur[4] > 100_000_000:
        bad.append("Werte ausserhalb des plausiblen Bereichs")
    return bad


def _robots_allows(url: str) -> bool:
    import requests
    from urllib import robotparser
    try:
        r = requests.get(LLV_BASE + "/robots.txt", headers=HEADERS, timeout=30)
        rp = robotparser.RobotFileParser()
        rp.parse(r.text.splitlines())
        return rp.can_fetch(HEADERS["User-Agent"], url)
    except Exception:
        return False                      # robots.txt nicht lesbar → vorsichtshalber nichts abrufen


def find_pdf_urls(year: int) -> list[str]:
    """PDF-Links mit «landesrechnung» auf der Berichtsseite des Rechnungsjahres (aktuelle Seite oder Archivseite)."""
    import time
    import requests
    out = []
    for slug in (f"rechenschaftsbericht-{year}", f"archiv-{year}"):
        url = LISTING + slug
        if not _robots_allows(url):
            continue
        time.sleep(2)
        r = requests.get(url, headers=HEADERS, timeout=45)
        if r.status_code != 200:
            continue
        for h in re.findall(r'href="([^"]*\.pdf[^"]*)"', r.text, re.I):
            if "landesrechnung" in h.lower():
                u = h if h.startswith("http") else LLV_BASE + h
                if u not in out:
                    out.append(u)
        if out:
            break
    return out


def pdf_pages(content: bytes) -> list[str]:
    import io
    import logging as _l
    _l.getLogger("pypdf").setLevel(_l.ERROR)
    import pypdf
    return [(p.extract_text() or "") for p in pypdf.PdfReader(io.BytesIO(content)).pages]


def auto_update(today: date | None = None, force: bool = False) -> str:
    """
    Jährliche Prüfung auf den neuen Rechenschaftsbericht (Teil IV Landesrechnung) und Übernahme von Konto 590.
    Täglich vom Worker aufgerufen; ruft erst ab 1. März des Folgejahres die llv.li-Berichtsseite ab und prüft bei offener Prüfung nur wöchentlich.
    → Zustand: ok | wartet | pruefung | fehler
    """
    import time
    import requests
    import db
    today = today or date.today()
    known = all_rows()
    target = max(known) + 1
    key = "landesrechnung"
    if target > today.year - 1 or today < date(target + 1, 3, 1):
        db.write_auto_status(key, "ok", f"Rechnungsjahr {max(known)} ist enthalten; der Bericht zu {target} erscheint üblicherweise im April/Mai {target + 1} "
                                         f"(Prüfung ab 1. März {target + 1}).", ok=True)
        return "ok"
    st = db.read_auto_status()
    prev = st[st["key"] == key]
    if not force and not prev.empty and prev.iloc[0]["state"] == "pruefung" and prev.iloc[0]["last_check"]:
        age = (datetime.utcnow() - datetime.strptime(prev.iloc[0]["last_check"], "%Y-%m-%d %H:%M")).days
        if age < 7:
            return "pruefung"
    try:
        urls = find_pdf_urls(target)
        if not urls:
            db.write_auto_status(key, "wartet", f"Bericht zum Rechnungsjahr {target} auf llv.li noch nicht gefunden.")
            return "wartet"
        errs = []
        for url in urls:
            if not _robots_allows(url):
                errs.append(f"{url}: robots.txt untersagt den Abruf")
                continue
            time.sleep(2)
            r = requests.get(url, headers=HEADERS, timeout=180)
            r.raise_for_status()
            if not r.content.startswith(b"%PDF"):
                errs.append(f"{url}: keine PDF-Datei")
                continue
            sha = hashlib.sha256(r.content).hexdigest()
            try:
                parsed = parse_konto590(pdf_pages(r.content), target)
            except ValueError as e:
                errs.append(f"{url}: {e}")
                continue
            bad = validate(parsed, target, known)
            c = parsed["cur"]
            row = {"year": target, "betreuung": c[0], "verfahren": c[1], "rechtsberatung": c[2], "sozialhilfe": c[3], "aufwand": c[4], "ertrag": c[5],
                   "doc": f"Rechenschaftsbericht {target}, IV. Landesrechnung", "url": url, "page": parsed["page"], "sha256": sha,
                   "retrieved": today.isoformat()}
            if bad:
                db.write_lr_asyl({**row, "status": "hold", "note": "; ".join(bad)})
                db.write_auto_status(key, "pruefung", f"Rechnungsjahr {target} gelesen, aber nicht übernommen: " + "; ".join(bad))
                log.warning("Landesrechnung %d wartet auf Prüfung: %s", target, bad)
                return "pruefung"
            db.write_lr_asyl({**row, "status": "ok", "note": ""})
            db.write_auto_status(key, "ok", f"Rechnungsjahr {target} übernommen (Seite {parsed['page']}, Summen- und Vorjahresprüfung bestanden).", ok=True)
            log.info("Landesrechnung %d übernommen: Aufwand %s, Ertrag %s", target, c[4], c[5])
            return "ok"
        db.write_auto_status(key, "pruefung", f"Bericht zum Rechnungsjahr {target} gefunden, Konto 590 aber nicht lesbar: " + "; ".join(errs))
        return "pruefung"
    except Exception as e:
        db.write_auto_status(key, "fehler", f"Abruf fehlgeschlagen: {str(e)[:300]}")
        log.error("Landesrechnung: %s", e)
        return "fehler"


def approve(year: int) -> None:
    """Von Hand nach Sichtprüfung: ein wartendes Jahr (status hold) freigeben. Aufruf: python -c "import landesrechnung as L; L.approve(2026)"."""
    import db
    d = db.read_lr_asyl()
    r = d[(d["year"] == year) & (d["status"] == "hold")]
    if r.empty:
        raise SystemExit(f"Kein wartendes Jahr {year}")
    row = r.iloc[0].to_dict()
    row["status"], row["note"] = "ok", "von Hand nach Sichtprüfung freigegeben"
    db.write_lr_asyl(row)
    db.write_auto_status("landesrechnung", "ok", f"Rechnungsjahr {year} nach Sichtprüfung freigegeben.", ok=True)
