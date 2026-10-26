"""
discover.py — Discovery-Crawler für opendata.li
===============================================
Läuft wöchentlich (Cron, siehe deploy/server/crontab.txt) oder manuell:
    python discover.py

Prüft, ob es neue, entfernte oder geänderte Datensätze/Quellen gibt:
  1. Katalog von opendata.li (EntryStore/DCAT) → od_catalog, Vergleich mit dem letzten Stand
  2. PXWeb-Baum des Amts für Statistik → Tabellen, die im Katalog fehlen (oder umgekehrt)
  3. Erreichbarkeit bekannter Portale (nur Status, keine Daten)

Der Crawler MELDET nur: Funde landen in der Tabelle od_discovery_log, im Bericht
(<Datenordner>/discovery-report.md) und im Log. Neue Datensätze werden nicht automatisch im
Dashboard ausgespielt — kuratierte Tabs/Diagramme bleiben Handarbeit; der Daten-Explorer
zeigt lediglich den aktuellen Katalogstand.
"""

import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

import db
import opendata

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout)])
log = logging.getLogger("discover")

# Bekannte Portale/Schnittstellen: nur Erreichbarkeit prüfen (HEAD), Änderungen melden
PROBES = {
    "opendata.li (Portal)": "https://www.opendata.li/de/daten",
    "opendata.li (EntryStore-Katalog)": opendata.ES_STORE,
    "etab.llv.li (PXWeb-API)": opendata.PX_BASE,
    "service.geo.llv.li (Geodienste)": "https://service.geo.llv.li/",
    "statistikportal.li": "https://www.statistikportal.li/de",
}
# Anteil, um den der Katalog schrumpfen darf, bevor wir von einer Störung statt einer
# Löschung ausgehen und nichts überschreiben
MAX_SHRINK = 0.2


def _report_path() -> Path:
    sqlite = os.environ.get("SQLITE_PATH")
    base = Path(sqlite).parent if sqlite else db.DEFAULT_SQLITE_PATH.parent
    base.mkdir(parents=True, exist_ok=True)
    return base / "discovery-report.md"


def probe_portals() -> list[tuple[str, str]]:
    out = []
    for name, url in PROBES.items():
        try:
            r = requests.get(url, headers=opendata.HEADERS, timeout=20, stream=True)
            status = str(r.status_code)
            r.close()
        except requests.RequestException as e:
            status = f"Fehler ({type(e).__name__})"
        out.append((name, status))
        time.sleep(0.5)
    return out


def run() -> int:
    log.info("Discovery gestartet")
    db.init_db()
    old = db.read_catalog()
    old_by_key = {r["key"]: r for r in old.to_dict("records")} if not old.empty else {}

    try:
        records = opendata.fetch_catalog()
    except Exception as e:
        log.error("Katalog nicht lesbar: %s", e)
        return 1
    new_by_key = {r["key"]: r for r in records}
    if old_by_key and len(new_by_key) < len(old_by_key) * (1 - MAX_SHRINK):
        log.error("Katalog auffällig klein (%d statt %d) — vermutlich Störung, nichts überschrieben",
                  len(new_by_key), len(old_by_key))
        return 1

    events = []
    first_run = not old_by_key
    if not first_run:
        for k, r in new_by_key.items():
            o = old_by_key.get(k)
            if o is None:
                events.append({"event": "neu", "ref": k, "title": r["title"],
                               "detail": f"{r['kind']} · {r['theme'] or '–'}/{r['subtheme'] or '–'}"})
            elif (r["modified"] and r["modified"] != o["modified"]) or r["title"] != o["title"]:
                events.append({"event": "geändert", "ref": k, "title": r["title"],
                               "detail": f"modified {o['modified'] or '–'} → {r['modified'] or '–'}"})
        for k, o in old_by_key.items():
            if k not in new_by_key:
                events.append({"event": "entfernt", "ref": k, "title": o["title"], "detail": ""})

    # PXWeb-Baum vs. Katalog
    tree = opendata.px_walk()
    cat_paths = {r["px_path"] for r in records if r["px_path"]}
    if len(tree) > 50:
        # Pfade vergleichen ohne Gross-/Kleinschreibung (Katalog nutzt teils «PXWEb»)
        tree_l = {p.lower(): p for p in tree}
        cat_l = {p.lower() for p in cat_paths}
        for pl, p in sorted(tree_l.items()):
            if pl not in cat_l:
                events.append({"event": "px-nicht-im-katalog", "ref": tree[p]["id"],
                               "title": tree[p]["text"], "detail": p})
        for p in sorted(cat_paths):
            if p.lower() not in tree_l:
                events.append({"event": "katalog-link-defekt", "ref": p, "title": "", "detail": "PX-Tabelle nicht gefunden"})
    else:
        log.warning("PX-Baum unvollständig (%d Tabellen) — Vergleich übersprungen", len(tree))

    probes = probe_portals()

    db.write_catalog(records)
    db.write_discovery_log(events)

    # Bericht
    kinds = {}
    for r in records:
        kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
    lines = [f"# opendata.li — Discovery-Bericht {datetime.utcnow():%Y-%m-%d %H:%M} UTC", "",
             f"Katalog: **{len(records)}** Datensätze ({', '.join(f'{k}: {v}' for k, v in sorted(kinds.items()))}); "
             f"PXWeb-Tabellen: **{len(tree)}**.", ""]
    if first_run:
        lines += ["Erster Lauf: Katalog als Ausgangsstand gespeichert, kein Vergleich möglich.", ""]
    lines += ["## Funde", ""]
    if events:
        for e in events:
            lines.append(f"- **{e['event']}** `{e['ref']}` {e['title']} {('— ' + e['detail']) if e['detail'] else ''}")
    else:
        lines.append("Keine Änderungen seit dem letzten Lauf.")
    lines += ["", "## Erreichbarkeit", ""] + [f"- {n}: {s}" for n, s in probes] + [""]
    report = "\n".join(lines)
    _report_path().write_text(report, encoding="utf-8")
    log.info("\n%s", report)
    log.info("Discovery beendet (%d Funde)", len(events))
    return 0


if __name__ == "__main__":
    sys.exit(run())
