"""
imf.py — IWF-Daten für Liechtenstein (IMF DataMapper API, World Economic Outlook)
================================================================================
Liechtenstein ist seit dem 21.10.2024 IWF-Mitglied (191. Mitglied, imf.org/en/countries/lie).
Der WEO-Datenbestand enthält Schätzungen/Projektionen des IWF. Von 132 DataMapper-Indikatoren liefern
15 Werte für LIE (Prüfung am 2026-10-26, auch nach dem Beitritt unverändert); sie stehen in INDICATORS.
Die neuere SDMX-API (api.imf.org) liefert Liechtenstein-Reihen in 15 weiteren/umfassenderen Datenflüssen
(SDMX_FLOWS, im Open-Data-Explorer). discover.py prüft wöchentlich beide Wege auf Neues.

Quelle:  International Monetary Fund, World Economic Outlook (DataMapper),
         https://www.imf.org/external/datamapper
Lizenz:  IWF-Datenbedingungen — Nutzung mit Quellenangabe, nicht-kommerziell frei
         (https://www.imf.org/en/About/Copyright-and-Terms). Keine automatisierten Massen-
         downloads: 15 Abrufe, höchstens wöchentlich, mit Pause.
"""

import logging
import time

import pandas as pd
import requests

log = logging.getLogger(__name__)

BASE = "https://www.imf.org/external/datamapper/api/v1"
TERMS_URL_IMF = "https://www.imf.org/en/About/Copyright-and-Terms"
COUNTRY = "LIE"
HEADERS = {"User-Agent": "LiechtensteinDashboard/1.0 (https://daten.li)"}
PAUSE = 1.0
REFRESH_DAYS = 7          # WEO erscheint zweimal pro Jahr; wöchentlich reicht

# code → (Bezeichnung, Einheit)
INDICATORS = {
    "NGDP_RPCH":    ("Reales BIP-Wachstum", "% ggü. Vorjahr"),
    "NGDPD":        ("BIP, laufende Preise", "Mrd. USD"),
    "NGDPDPC":      ("BIP pro Kopf, laufende Preise", "USD"),
    "PPPGDP":       ("BIP, Kaufkraftparität", "Mrd. int. Dollar"),
    "PPPPC":        ("BIP pro Kopf, Kaufkraftparität", "int. Dollar"),
    "PPPSH":        ("Anteil am Welt-BIP (KKP)", "% der Welt"),
    "PPPEX":        ("Kaufkraftparitäts-Umrechnungskurs", "CHF je int. Dollar"),
    "PCPIPCH":      ("Inflation, Jahresdurchschnitt", "% ggü. Vorjahr"),
    "PCPIEPCH":     ("Inflation, Jahresende", "% ggü. Vorjahr"),
    "LP":           ("Bevölkerung", "Mio. Personen"),
    "BCA":          ("Leistungsbilanzsaldo", "Mrd. USD"),
    "BCA_NGDPD":    ("Leistungsbilanzsaldo", "% des BIP"),
    "LUR":          ("Arbeitslosenquote", "%"),
    "GGXCNL_NGDP":  ("Staatshaushalt, Finanzierungssaldo", "% des BIP"),
    "GGXWDG_NGDP":  ("Staatsverschuldung, brutto", "% des BIP"),
}

# IWF-SDMX-Datenflüsse mit Werten für Liechtenstein (geprüft 2026-10-26; discover.py meldet Änderungen; ANEA liefert für LIE nur leere Reihen)
SDMX_BASE = "https://api.imf.org/external/sdmx/2.1"
SDMX_PREFIX = "imf:"
SDMX_FLOWS = {
    "IMF.RES/WEO/9.0.0":        "World Economic Outlook (WEO)",
    "IMF.STA/FSIBSIS/18.0.0":   "Financial Soundness Indicators: Bilanz, Erfolgsrechnung (FSI)",
    "IMF.STA/ER/4.0.1":         "Wechselkurse (ER)",
    "IMF.STA/FAS/8.0.0":        "Financial Access Survey (FAS)",
    "IMF.STA/UNFCCC/3.0.0":     "Treibhausgasemissionen (UNFCCC)",
    "IMF.STA/CCI/4.0.1":        "Klimawandel-Indikatoren (CCI)",
    "IMF.FAD/WORLD/3.0.1":      "World Revenue Longitudinal Database (WoRLD)",
    "IMF.STA/DIP/12.0.1":       "Direktinvestitionspositionen nach Gegenpartei (DIP, ehem. CDIS)",
    "IMF.STA/PIP/5.0.0":        "Portfolioinvestitionspositionen nach Gegenpartei (PIP, ehem. CPIS)",
    "IMF.STA/NDGAIN/1.0.1":     "ND-GAIN-Index (Klimaanpassung)",
    "IMF.STA/INFORMRISK/1.0.4": "INFORM-Klimarisiko",
    "IMF.STA/GS_HEALTH/5.0.0":  "Gender Statistics: Gesundheit",
    "IMF.STA/GS_ED/3.0.0":      "Gender Statistics: Bildung",
    "IMF.STA/GS_CGI/3.0.0":     "Gender Statistics: Composite Gender Indices",
    "IMF.STA/GS_LEPM/2.0.0":    "Gender Statistics: Führung und Mitbestimmung",
}

_session = requests.Session()
_session.headers.update(HEADERS)


def _get(path: str):
    for attempt in range(3):
        try:
            r = _session.get(f"{BASE}/{path}", timeout=30)
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(5 * (attempt + 1))
                continue
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            log.warning("IWF %s: %s", path, e)
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"IWF-API nicht erreichbar: {path}")


def fetch_indicator(code: str) -> pd.DataFrame:
    """Spalten year, value (inkl. Projektionen)."""
    d = _get(f"{code}/{COUNTRY}")
    vals = d.get("values", {}).get(code, {}).get(COUNTRY, {})
    df = pd.DataFrame([{"year": int(y), "value": float(v)} for y, v in vals.items() if v is not None])
    return df.sort_values("year") if not df.empty else df


def fetch_meta(code: str) -> dict:
    """Quelle/WEO-Ausgabe laut API (z. B. «World Economic Outlook (October 2026)»)."""
    m = _get("indicators").get("indicators", {}).get(code, {})
    return {"source": m.get("source", ""), "dataset": m.get("dataset", "")}


def probe_all_indicators() -> dict[str, tuple[str, int]]:
    """Alle DataMapper-Indikatoren auf Werte für Liechtenstein prüfen → {code: (Label, Anzahl Jahre)}.
    ~130 Abrufe mit Pause — nur für den wöchentlichen Discovery-Lauf."""
    ind = _get("indicators").get("indicators", {})
    hits = {}
    for code, m in ind.items():
        time.sleep(0.5)
        try:
            d = _get(f"{code}/{COUNTRY}")
        except RuntimeError:
            continue
        vals = d.get("values", {}).get(code, {}).get(COUNTRY, {})
        if vals:
            hits[code] = ((m.get("label") or "").strip(), len(vals))
    return hits


# ── SDMX-API (api.imf.org) ─────────────────────────────────────────────────────

def sdmx_url_id(flow: str) -> str:
    return SDMX_PREFIX + flow


def fetch_sdmx(flow: str) -> tuple[pd.DataFrame, dict]:
    """
    Alle Reihen eines IWF-Datenflusses für Liechtenstein (SDMX-JSON, inkl. Bezeichnungen) als Long-DataFrame:
    Spalten = Dimensionen (Klartext) + «Zeit» + «Wert», dazu info im Format von opendata.px_fetch.
    flow: «Agentur/Fluss/Version», z. B. IMF.STA/FSIBSIS/18.0.0
    """
    agency, fid, ver = flow.split("/")
    time.sleep(PAUSE)
    r = _session.get(f"{SDMX_BASE}/data/{agency},{fid},{ver}/{COUNTRY}", headers={"Accept": "application/json"}, timeout=120)
    r.raise_for_status()
    d = r.json()
    st = d["structure"]["dimensions"]
    sdims = st["series"]
    times = st["observation"][0]["values"]
    rows = []
    for key, ser in d["dataSets"][0]["series"].items():
        idx = [int(i) for i in key.split(":")]
        labels = {sd.get("name") or sd["id"]: sd["values"][i].get("name") or sd["values"][i]["id"]
                  for sd, i in zip(sdims, idx) if sd["id"] != "COUNTRY"}
        for t, obs in ser.get("observations", {}).items():
            v = obs[0]
            if v is None:
                continue
            rows.append({**labels, "Zeit": times[int(t)]["id"], "Wert": float(v)})
    df = pd.DataFrame(rows)
    if df.empty:
        raise ValueError(f"Keine Werte für {COUNTRY} in {fid}")
    dims = [c for c in df.columns if c != "Wert"]
    # Frequenz und konstante Dimensionen bleiben als Filter erhalten (ein Wert → Dropdown mit einem Eintrag)
    info = {"path": sdmx_url_id(flow), "title": SDMX_FLOWS.get(flow, fid), "dims": dims, "unit": "", "reduced": [],
            "rows": len(df)}
    return df, info


def list_sdmx_flows_with_data() -> dict[str, tuple[str, int]]:
    """Alle aktuellen (nicht-VINTAGE) SDMX-Datenflüsse auf Werte für LIE prüfen → {Agentur/Fluss/Version: (Name, Reihen)}.
    ~100 Abrufe mit Pause, nur für den wöchentlichen Discovery-Lauf."""
    import re
    import xml.etree.ElementTree as ET
    r = _session.get(f"{SDMX_BASE}/dataflow/all", timeout=60)
    r.raise_for_status()
    ns = {"str": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/structure",
          "com": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/common"}
    flows = []
    for f in ET.fromstring(r.content).iter("{%s}Dataflow" % ns["str"]):
        if "VINTAGE" in f.get("id", ""):
            continue
        name = f.find("com:Name", ns)
        flows.append((f.get("agencyID"), f.get("id"), f.get("version"), name.text if name is not None else ""))
    hits = {}
    for agency, fid, ver, name in flows:
        time.sleep(0.7)
        try:
            x = _session.get(f"{SDMX_BASE}/data/{agency},{fid},{ver}/{COUNTRY}?startPeriod=2022", timeout=90).text
        except requests.RequestException:
            continue
        n = len(re.findall(r"<Series[ >]", x)) if re.search(r"<Obs[ >]", x) else 0     # nur Reihen mit Beobachtungen
        if n:
            hits[f"{agency}/{fid}/{ver}"] = (name, n)
    return hits
