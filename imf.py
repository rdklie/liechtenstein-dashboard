"""
imf.py — IWF-Daten für Liechtenstein (IMF DataMapper API, World Economic Outlook)
================================================================================
Liechtenstein ist kein IWF-Mitglied; der IWF führt es im WEO-Datenbestand mit Schätzungen
und Projektionen (kein Länderreport). Von 132 DataMapper-Indikatoren liefern 15 Werte für LIE
(Prüfung am 2026-10-26); sie stehen in INDICATORS. discover.py prüft wöchentlich, ob weitere
dazukommen.

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
