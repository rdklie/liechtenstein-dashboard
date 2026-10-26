"""
opendata.py — Open-Data-Anbindung (opendata.li) für das Liechtenstein Dashboard
===============================================================================
Quellen
  * Katalog:  EntryStore von opendata.li (DCAT), https://catalog.opendata.li/store/
  * Daten:    PXWeb-API des Amts für Statistik, https://etab.llv.li/PXWeb/api/v1/de/eTab/
Lizenz der Datensätze: Namensnennung (dcat-ap.ch terms_by) — Quelle: Amt für Statistik
Liechtenstein, opendata.li.

Die App ruft diese APIs nie beim Seitenaufbau auf, sondern liest aus SQLite (db.py).
Nur der Daten-Explorer lädt eine einzelne Tabelle bei Bedarf nach (mit Cache).
"""

import json
import logging
import re
import time
import urllib.parse

import pandas as pd
import requests

log = logging.getLogger(__name__)

PX_BASE = "https://etab.llv.li/PXWeb/api/v1/de/eTab/"
PX_WEB_BASE = "https://etab.llv.li/PXWeb/pxweb/de/eTab/"
ES_STORE = "https://catalog.opendata.li/store/"
PORTAL_URL = "https://www.opendata.li/de/daten"
LICENSE_TEXT = "Namensnennung (CC BY, dcat-ap.ch terms_by)"
SOURCE_TEXT = "Amt für Statistik Liechtenstein, opendata.li"
HEADERS = {"User-Agent": "LiechtensteinDashboard/1.0 (https://daten.li)"}

# Pause zwischen Requests (Rücksicht auf die Landesverwaltung, PXWeb limitiert Aufrufe)
PAUSE = 0.4
# PXWeb lehnt Abfragen mit zu vielen Zellen ab; wir bleiben deutlich darunter
MAX_CELLS = 40_000

# Tabellen, die der Worker täglich spiegelt und die der Tab «Wohnen» nutzt
H = "Bauen und Wohnen/"
CURATED = {
    "wohnungen":      H + "Gebäude, Wohnungen/Jahresergebnisse/391.133.px",
    "belegung":       H + "Gebäude, Wohnungen/Jahresergebnisse/391.131.px",
    "gebaeude":       H + "Gebäude, Wohnungen/Jahresergebnisse/391.101.px",
    "miete_netto_zi": H + "Mietpreise/394.001d.px",
    "miete_netto_m2": H + "Mietpreise/394.002d.px",
    "miete_brutto_zi": H + "Mietpreise/394.101d.px",
    "miete_brutto_m2": H + "Mietpreise/394.102d.px",
    "bewilligt":      H + "Bautätigkeit/Jahreszahlen/381.005.px",
    "abbruch":        H + "Bautätigkeit/Jahreszahlen/381.006.px",
    "bevoelkerung":   "Bevölkerung/Bevölkerungsstand/Stichtag 31 Dezember/211.002.px",
}

_session = requests.Session()
_session.headers.update(HEADERS)


def _quote_path(path: str) -> str:
    return "/".join(urllib.parse.quote(p) for p in path.split("/"))


def _request(method: str, url: str, retries: int = 3, **kw):
    """HTTP mit Retries/Backoff (429/5xx), liefert Response oder wirft die letzte Exception."""
    last = None
    for attempt in range(retries):
        try:
            resp = _session.request(method, url, timeout=45, **kw)
            if resp.status_code in (429, 500, 502, 503, 504):
                last = requests.HTTPError(f"{resp.status_code} für {url}")
                time.sleep(5 * (attempt + 1))
                continue
            resp.raise_for_status()
            return resp
        except requests.RequestException as e:
            last = e
            time.sleep(3 * (attempt + 1))
    raise last


# ── PXWeb ─────────────────────────────────────────────────────────────────────

def px_get(path: str = ""):
    """Ordnerliste (list) oder Tabellen-Metadaten (dict) aus der PXWeb-API."""
    return _request("GET", PX_BASE + _quote_path(path) if path else PX_BASE).json()


def px_walk(path: str = "", depth: int = 0) -> dict[str, dict]:
    """Alle Tabellen unterhalb von path: {pfad: {id, text, updated}}."""
    out = {}
    try:
        items = px_get(path)
    except Exception as e:
        log.warning("PX-Ordner %s nicht lesbar: %s", path or "/", e)
        return out
    for it in items:
        sub = f"{path}/{it['id']}" if path else it["id"]
        if it.get("type") == "t":
            out[sub] = {"id": it["id"], "text": it.get("text", ""), "updated": it.get("updated", "")}
        elif it.get("type") == "l" and depth < 6:
            time.sleep(PAUSE / 2)
            out.update(px_walk(sub, depth + 1))
    return out


_TIME_RE = re.compile(r"(jahr|quartal|monat|stichtag|zeit)$|^(jahr|stichtag|monat|quartal|zeit)\b")


def is_time_dim(name: str) -> bool:
    """Zeitachse erkennen (Jahr, Bewilligungsquartal, Stichtag …), aber nicht «Altersjahr»."""
    n = name.strip().lower()
    return "alter" not in n and bool(_TIME_RE.search(n))


def px_fetch(path: str, max_cells: int = MAX_CELLS) -> tuple[pd.DataFrame, dict]:
    """
    Lädt eine PX-Tabelle als Long-DataFrame (Spalten = Dimensionen + 'Wert', ggf. 'Kennzahl').
    Zu grosse Tabellen werden reduziert: Dimensionen mit den meisten Werten (ausser Zeit) auf
    den ersten Wert (meist «Total»). Rückgabe: (df, info).
    """
    meta = px_get(path)
    variables = meta["variables"]
    selected = {v["code"]: list(v["values"]) for v in variables}

    def cells():
        n = 1
        for vals in selected.values():
            n *= max(len(vals), 1)
        return n

    reduced = []
    while cells() > max_cells:
        cand = [v for v in variables
                if len(selected[v["code"]]) > 1 and not is_time_dim(v["text"])]
        if not cand:
            cand = [v for v in variables if len(selected[v["code"]]) > 1]
        if not cand:
            break
        biggest = max(cand, key=lambda v: len(selected[v["code"]]))
        selected[biggest["code"]] = selected[biggest["code"]][:1]
        reduced.append(biggest["text"])

    query = {
        "query": [{"code": c, "selection": {"filter": "item", "values": vals}}
                  for c, vals in selected.items()],
        "response": {"format": "json"},
    }
    time.sleep(PAUSE)
    resp = _request("POST", PX_BASE + _quote_path(path), json=query)
    data = json.loads(resp.content.decode("utf-8-sig"))

    dims = [c for c in data["columns"] if c["type"] != "c"]
    contents = [c for c in data["columns"] if c["type"] == "c"]
    # Code → Text je Dimension
    text_of = {v["code"]: dict(zip(v["values"], v["valueTexts"])) for v in variables}
    rows = []
    for rec in data["data"]:
        base = {d["text"]: text_of[d["code"]].get(k, k) for d, k in zip(dims, rec["key"])}
        for c, val in zip(contents, rec["values"]):
            row = dict(base)
            if len(contents) > 1:
                row["Kennzahl"] = c["text"]
            row["Wert"] = pd.to_numeric(val, errors="coerce")
            rows.append(row)
    df = pd.DataFrame(rows)
    info = {
        "path": path,
        "title": meta.get("title", ""),
        "dims": [d["text"] for d in dims] + (["Kennzahl"] if len(contents) > 1 else []),
        "unit": contents[0]["text"] if len(contents) == 1 else "",
        "reduced": reduced,
        "rows": len(df),
    }
    return df, info


def px_web_url(path: str) -> str:
    """Link auf die Tabelle im PXWeb-Frontend (für Quellenangabe/Download)."""
    parts = path.split("/")
    folder = "__".join(["etab"] + parts[:-1]) if len(parts) > 1 else "etab"
    return PX_WEB_BASE + urllib.parse.quote(folder) + "/" + urllib.parse.quote(parts[-1])


# ── Katalog (EntryStore / DCAT) ───────────────────────────────────────────────

_DCT = "http://purl.org/dc/terms/"
_DCAT = "http://www.w3.org/ns/dcat#"


def _search(rdf_type: str) -> list[dict]:
    """Alle Einträge eines RDF-Typs aus dem EntryStore (paginiert)."""
    query = urllib.parse.quote("rdfType:" + rdf_type.replace(":", "\\:", 1), safe=":/")
    out, offset = [], 0
    while True:
        url = f"{ES_STORE}search?type=solr&query={query}&limit=100&offset={offset}"
        d = _request("GET", url, headers={"Accept": "application/json"}).json()
        out += d["resource"]["children"]
        offset += 100
        if offset >= d.get("results", 0):
            return out
        time.sleep(PAUSE)


def _lit(md: dict, key: str, lang: str = "de") -> str:
    vals = md.get(key, [])
    for x in vals:
        if x.get("lang") == lang:
            return x["value"].strip()
    return vals[0]["value"].strip() if vals else ""


def _fix(s: str) -> str:
    """Der Katalog liefert teils doppelt kodiertes UTF-8 (Ã¶ statt ö)."""
    if "Ã" in s or "Â" in s:
        try:
            return s.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            return s
    return s


def fetch_catalog() -> list[dict]:
    """
    Liest den kompletten Katalog (Datensätze + Distributionen) und gibt flache Records zurück:
    key, title, description, modified, kind ('px'|'geo'|'file'|'other'), px_path, formats,
    license, landing_url, catalog_url, publisher.
    """
    datasets = _search("http://www.w3.org/ns/dcat#Dataset")
    time.sleep(PAUSE)
    dists = {}
    for e in _search("http://www.w3.org/ns/dcat#Distribution"):
        dists[next(iter(e["metadata"]))] = next(iter(e["metadata"].values()))

    records = []
    for e in datasets:
        md = next(iter(e["metadata"].values()))
        uri = next(iter(e["metadata"]))
        title = _fix(_lit(md, _DCT + "title"))
        if not title:
            continue  # Platzhalter-Einträge ohne Metadaten
        formats, px_path, license_ = set(), "", ""
        for ref in md.get(_DCAT + "distribution", []):
            d = dists.get(ref["value"], {})
            fmt = (d.get(_DCT + "format") or [{}])[0].get("value", "")
            fmt = fmt.rsplit("/", 1)[-1].lower() if fmt else ""
            if fmt:
                formats.add(fmt)
            if not license_:
                license_ = (d.get(_DCT + "license") or [{}])[0].get("value", "")
            url = (d.get(_DCAT + "accessURL") or [{}])[0].get("value", "")
            m = re.search(r"/api/v1/de/eTab/+(.+)$", url, re.I)
            if fmt == "json" and m and not px_path:
                px_path = urllib.parse.unquote(m.group(1))
        page = (md.get("http://xmlns.com/foaf/0.1/page") or [{}])[0].get("value", "")
        landing = (md.get(_DCAT + "landingPage") or [{}])[0].get("value", "")
        modified = (md.get(_DCT + "modified") or [{}])[0].get("value", "")[:10]
        if px_path:
            kind = "px"
        elif formats & {"wms_xml", "zip", "xml"} or "wms" in " ".join(formats):
            kind = "geo"
        elif formats:
            kind = "file"
        else:
            kind = "other"
        records.append({
            "key": _lit(md, _DCT + "identifier") or uri,
            "title": title,
            "description": _fix(_lit(md, _DCT + "description")),
            "modified": modified,
            "kind": kind,
            "px_path": px_path,
            "formats": ",".join(sorted(formats)),
            "license": license_.rsplit("/", 1)[-1],
            "landing_url": landing,
            "catalog_url": page or uri,
            "theme": px_path.split("/")[0] if px_path else "",
            "subtheme": px_path.split("/")[1] if px_path.count("/") >= 2 else "",
        })
    return records
