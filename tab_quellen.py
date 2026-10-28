"""
tab_quellen.py — Seite «Datenquellen» (erreichbar über den Fuss jeder Seite und unter ?tab=quellen)
===================================================================================================
Je Bereich (Tab) die Quellen mit Link, Herausgeber, Lizenz/Nutzung, Aktualisierungsrhythmus und dem Stand des letzten Abrufs aus der Datenbank.
Die Liste steht in REGISTRY; Links und Kennzahlen kommen, wo es sie gibt, aus den Konstanten der Module (opendata, imf, police, landesrechnung, lohn, ui).
Zusätzlich: Zustand der automatischen Nachführungen (Tabelle auto_status), Hinweise zu KI/Statistik, Kontakt.
"""

from datetime import datetime

import pandas as pd
from dash import html

import db
import imf
import landesrechnung as LR
import lohn
import opendata
import police
from ui import FL_BLUE, FL_RED, FL_GOLD, GREEN, MUTED, TEXT, BORDER, SOURCES, _card

PX_WEB = opendata.PX_WEB_BASE
OD_PORTAL = opendata.PORTAL_URL
OD_CATALOG = "https://catalog.opendata.li/"

CC_BY4 = "CC BY 4.0 (Namensnennung)"
LI_LICENSE = "CC BY (Namensnennung), «Amt für Statistik Liechtenstein, opendata.li»"
DAILY = "Worker täglich 06:00 UTC (Cache höchstens 7 Tage)"

# (Bereich, [Quelle …]); Quelle = dict(name, url, publisher, license, rhythm, use, fetch=Schlüssel für den Abrufzeitpunkt)
REGISTRY: list[tuple[str, list[dict]]] = [
    ("Übersicht · Wirtschaft", [
        dict(name="Weltbank – World Development Indicators", url=SOURCES["worldbank"][1], publisher="Weltbank (World Bank Group)", license=CC_BY4,
             rhythm=DAILY, use="BIP, Bevölkerung und weitere Indikatoren für Liechtenstein", fetch="wb_data"),
        dict(name="Eurostat – BIP", url=SOURCES["eurostat"][1], publisher="Europäische Kommission, Eurostat", license="© Europäische Union, CC BY 4.0",
             rhythm=DAILY, use="BIP in EUR (EWR)", fetch="eurostat"),
        dict(name="Amt für Statistik Liechtenstein (PXWeb/opendata.li)", url=OD_PORTAL, publisher="Amt für Statistik Liechtenstein", license=LI_LICENSE,
             rhythm=DAILY, use="Sektoren, Bevölkerung, Arbeitslosigkeit u. a.", fetch="px_li"),
    ]),
    ("Klima", [
        dict(name="Open-Meteo Historical Weather API (ERA5)", url="https://open-meteo.com/en/docs/historical-weather-api", publisher="Open-Meteo.com; Modell ERA5: ECMWF/Copernicus Climate Change Service",
             license="CC BY 4.0 – «Weather data by Open-Meteo.com»; ERA5 © ECMWF/Copernicus (CC BY 4.0)", rhythm="Monatswerte: abgeschlossene Jahre einmalig; Worker täglich 06:00 UTC prüft auf fehlende Jahre",
             use="Temperaturen und Niederschlag der 11 Gemeinden (Rasterwerte ≈ 25–30 km, keine Messstation)", fetch="weather"),
    ]),
    ("Tourismus", [
        dict(name="Eurostat – Tourismus (Ankünfte, Übernachtungen)", url=SOURCES["eurostat"][1], publisher="Europäische Kommission, Eurostat", license="© Europäische Union, CC BY 4.0",
             rhythm=DAILY, use="Ankünfte und Übernachtungen in Beherbergungsbetrieben", fetch="eurostat"),
        dict(name="OpenStreetMap (Overpass API)", url=SOURCES["osm"][1], publisher="OpenStreetMap-Mitwirkende", license="ODbL 1.0 – «© OpenStreetMap-Mitwirkende» (Namensnennung, Weitergabe unter gleichen Bedingungen)",
             rhythm=DAILY, use="Points of Interest in Liechtenstein (Anzahl je Kategorie)", fetch="osm"),
    ]),
    ("Wohnen", [
        dict(name="Amt für Statistik – Wohnen, Mieten, Bautätigkeit (PXWeb eTab)", url=PX_WEB, publisher="Amt für Statistik Liechtenstein (etab.llv.li)", license=LI_LICENSE,
             rhythm=DAILY, use="Wohnungsbestand, Mieten, Bautätigkeit", fetch="px_li"),
    ]),
    ("Open Data", [
        dict(name="opendata.li – Portal und Katalog (EntryStore)", url=OD_CATALOG, publisher="Amt für Statistik Liechtenstein / Landesverwaltung", license="je Datensatz im Katalog angegeben (meist CC BY)",
             rhythm="Katalog-Abgleich sonntags 05:30 UTC (Discovery, nur Meldungen – nichts wird automatisch veröffentlicht); Dateien im Explorer Cache höchstens 7 Tage",
             use="Explorer für ca. 460 Tabellen (PXWeb) und Dateien (CSV/JSON) des Katalogs", fetch="catalog"),
        dict(name="FMA Liechtenstein und weitere Dateien aus dem Katalog", url=OD_PORTAL, publisher="Herausgeber je Datensatz (im Explorer angezeigt)", license="je Datensatz",
             rhythm=DAILY, use="verwaltetes Vermögen, Solvenz, Prämien u. a.", fetch="file"),
    ]),
    ("Factbook (Archiv, abgeschlossen)", [
        dict(name="CIA World Factbook – Archiv 1990–2025", url="https://github.com/MilkMp/CIA-World-Factbooks-Archive-1990-2025", publisher="CIA (Original, eingestellt am 4. Februar 2026); Archiv-Datenbestand: MilkMp (GitHub, MIT)",
             license="gemeinfrei (US-Regierungspublikation)", rhythm="abgeschlossen – einmaliger Import, keine Nachführung nötig", use="Liechtenstein in allen Ausgaben 1990–2025", fetch="factbook"),
    ]),
    ("IWF", [
        dict(name="IWF – World Economic Outlook (DataMapper)", url="https://www.imf.org/external/datamapper", publisher="Internationaler Währungsfonds", license=f"Quellenangabe, nicht-kommerzielle Nutzung ({imf.TERMS_URL_IMF})",
             rhythm="Worker höchstens wöchentlich; WEO erscheint zweimal jährlich (April, Oktober)", use="15 Indikatoren für Liechtenstein (Schätzungen/Projektionen)", fetch="imf"),
        dict(name="IWF – SDMX-Datenflüsse", url="https://data.imf.org/", publisher="Internationaler Währungsfonds", license=f"Quellenangabe, nicht-kommerzielle Nutzung ({imf.TERMS_URL_IMF})",
             rhythm=DAILY, use="weitere IWF-Datenflüsse im Explorer", fetch="px_imf"),
    ]),
    ("Migration", [
        dict(name="Amt für Statistik – Bevölkerung, Einbürgerungen, Asylwesen", url=OD_PORTAL, publisher="Amt für Statistik Liechtenstein", license=LI_LICENSE,
             rhythm=DAILY, use="Wohnbevölkerung nach Staatsbürgerschaft, Asylgesuche, Bestand (233.302)", fetch="px_pxs"),
        dict(name="Eurostat – Migration, Asyl, Straffälligkeit", url=SOURCES["eurostat"][1], publisher="Europäische Kommission, Eurostat", license="© Europäische Union, CC BY 4.0",
             rhythm=DAILY, use="Ländervergleich (Anteile, Einbürgerungen, Asyl, Verdächtige nach Staatsangehörigkeit)", fetch="px_es"),
        dict(name="Weltbank/UN DESA – Internationaler Migrantenbestand", url="https://data.worldbank.org/indicator/SM.POP.TOTL.ZS", publisher="UN DESA (Original), Weltbank (WDI)", license=CC_BY4,
             rhythm=DAILY, use="Anteil im Ausland Geborener", fetch="px_wb"),
        dict(name="Landesrechnung – Konto 590 «Flüchtlingswesen»", url=LR.LISTING + "rechenschaftsbericht-2025", publisher="Regierung des Fürstentums Liechtenstein, Stabsstelle Regierungskanzlei / Amt für Finanzen (Rechenschaftsbericht, Teil IV)",
             license="amtliche Publikation, keine ausdrückliche Lizenz – nur Zahlen mit Dokument- und Seitenangabe", rhythm="jährlich (Bericht erscheint April/Mai); Worker prüft ab 1. März automatisch, Übernahme nur nach Summen- und Vorjahresprüfung",
             use="Aufwand des Landes für das Asylwesen 2009 bis heute", fetch="lr"),
    ]),
    ("Bildung", [
        dict(name="Amt für Statistik – Schulen, Lernende, Studierende, Bildungsausgaben", url=OD_PORTAL, publisher="Amt für Statistik Liechtenstein", license=LI_LICENSE,
             rhythm=DAILY, use="Tabellen 481.xxx u. a.", fetch="px_edu"),
        dict(name="OECD PISA (über Weltbank EdStats)", url="https://datacatalog.worldbank.org/search/dataset/0038480/Education-Statistics", publisher="OECD (Original), Weltbank EdStats (Bereitstellung)",
             license="Quellenangabe OECD (Bedingungen der Originalquelle massgeblich); der Weltbank-Katalog führt EdStats unter CC BY 4.0", rhythm="Liechtenstein nahm 2000–2012 teil; keine neuen Erhebungen", use="PISA-Ergebnisse 2000–2012 im Länder­vergleich", fetch="px_edu"),
    ]),
    ("Lohn", [
        dict(name="Amt für Statistik – Lohnstatistik (Tabellen 291.xxx)", url=lohn.PUB_URL, publisher="Amt für Statistik Liechtenstein", license=LI_LICENSE,
             rhythm="Erhebung alle zwei Jahre (2006–2024); Worker wöchentlich", use="Medianlohn, Quartile, Lohnunterschied, Branchen, Alter, Wohnsitz", fetch="px_lohn"),
        dict(name="BFS – Schweizerische Lohnstrukturerhebung", url="https://www.bfs.admin.ch/bfs/de/home/statistiken/arbeit-erwerb/loehne-erwerbseinkommen-arbeitskosten/lohnniveau-schweiz.html",
             publisher="Bundesamt für Statistik (BFS)", license="Open Government Data: freie Nutzung mit Quellenangabe «© BFS»", rhythm="alle zwei Jahre", use="Zentralwert Schweiz (Einordnung)", fetch="px_lohn"),
        dict(name="Weltbank – Konsumentenpreisindex Schweiz (FP.CPI.TOTL)", url="https://data.worldbank.org/indicator/FP.CPI.TOTL?locations=CH", publisher="Weltbank (Original: nationale Statistikämter)", license=CC_BY4,
             rhythm="Worker wöchentlich", use="Näherung für reale Löhne (Deflator)", fetch="px_lohn"),
    ]),
    ("Polizeistatistik", [
        dict(name="Landespolizei Liechtenstein – Jahresberichte", url=police.LIST_URL, publisher="Landespolizei des Fürstentums Liechtenstein", license="öffentlich zugängliche amtliche Publikation, keine ausdrückliche Lizenz – nur Kennzahlen mit Quellen- und Seitenangabe",
             rhythm="jährlich; Worker prüft monatlich auf neue PDFs, Übernahme nur nach Plausibilitätsprüfung", use="Kriminalität, Verkehrsunfälle, Untersuchungshaft, Notrufe", fetch="police"),
        dict(name="Eurostat – Kriminalität nach Staatsangehörigkeit", url=SOURCES["eurostat"][1], publisher="Europäische Kommission, Eurostat", license="© Europäische Union, CC BY 4.0",
             rhythm=DAILY, use="Verdächtige, Strafverfolgte, Verurteilte im Ländervergleich", fetch="px_es"),
    ]),
    ("Klimawandel (experimentell)", [
        dict(name="Open-Meteo Historical Weather API (ERA5), Tageswerte ab 1950", url="https://open-meteo.com/en/docs/historical-weather-api", publisher="Open-Meteo.com; ERA5: ECMWF/Copernicus Climate Change Service",
             license="CC BY 4.0 – «Weather data by Open-Meteo.com»; ERA5 © ECMWF/Copernicus (CC BY 4.0)", rhythm="Erstladung abgeschlossen; Worker ergänzt jährlich ab 15. Januar das neue Jahr",
             use="Hitzetage, Frosttage, Niederschlag, Trends je Gemeinde", fetch="klima"),
    ]),
    ("Korrelations-Labor · Prognosen (experimentell)", [
        dict(name="Reihen aus allen oben genannten Quellen", url=None, publisher="eigene statistische Auswertung (Korrelationskoeffizienten, ARIMA/ETS-Projektionen)", license="Ergebnisse sind Statistik, keine Vorhersagen und keine Aussagen über Ursachen",
             rhythm="Projektionen: Worker höchstens wöchentlich", use="Zusammenhänge und Projektionen auf Basis der gespeicherten Reihen", fetch="fc"),
    ]),
]

STATE_COLOR = {"ok": GREEN, "wartet": FL_GOLD, "pruefung": FL_GOLD, "fehler": FL_RED}
STATE_LABEL = {"ok": "aktuell", "wartet": "wartet", "pruefung": "wartet auf Prüfung", "fehler": "Fehler beim letzten Lauf"}


def _day(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)) or v == "":
        return ""
    try:
        return pd.to_datetime(v).strftime("%d.%m.%Y")
    except Exception:
        return str(v)[:10]


def fetch_times() -> dict[str, str]:
    """Stand des letzten Abrufs je Quellengruppe (aus den Zeitstempeln der DB; leer = nicht ermittelbar)."""
    def mx(sql):
        d = db._read(sql)
        return _day(d.iloc[0, 0]) if not d.empty else ""
    out = {
        "wb_data": mx("SELECT MAX(fetched_at) FROM world_bank_data"),
        "weather": mx("SELECT MAX(fetched_at) FROM weather_monthly"),
        "eurostat": mx("SELECT MAX(fetched_at) FROM eurostat_tourism"),
        "osm": mx("SELECT MAX(fetched_at) FROM osm_poi_counts"),
        "imf": mx("SELECT MAX(fetched_at) FROM imf_data"),
        "catalog": mx("SELECT MAX(last_seen) FROM od_catalog"),
        "police": mx("SELECT MAX(retrieved) FROM police_reports"),
        "fc": mx("SELECT MAX(computed_at) FROM fc_results"),
        "factbook": "",
    }
    px = db._read("SELECT path, fetched_at FROM px_cache")
    if not px.empty:
        px["t"] = pd.to_datetime(px["fetched_at"], errors="coerce")
        groups = {"px_lohn": "lohn:", "px_edu": "edu:", "px_pxs": "pxs:", "px_es": "es:", "px_wb": "wb:", "px_imf": "imf:", "file": "file:"}
        for k, pref in groups.items():
            s = px[px["path"].str.startswith(pref)]["t"]
            out[k] = _day(s.max()) if len(s) else ""
        plain = px[~px["path"].str.contains(":", regex=False)]["t"]
        out["px_li"] = _day(plain.max()) if len(plain) else ""
    st = db.read_auto_status()
    for k, name in (("lr", "landesrechnung"), ("klima", "klima")):
        r = st[st["key"] == name] if not st.empty else st
        out[k] = _day(r.iloc[0]["last_ok"]) if not r.empty and r.iloc[0]["last_ok"] else ""
    try:
        out["lr"] = (out["lr"] + " · " if out["lr"] else "") + f"enthält Rechnungsjahre bis {int(LR.table().index.max())}"
    except Exception:
        pass
    out["factbook"] = "abgeschlossen"
    return out


def _link(label, url):
    return html.A(label, href=url, target="_blank", rel="noopener noreferrer", className="source-link") if url else html.Span(label)


def _table(sources: list[dict], times: dict) -> html.Div:
    head = html.Tr([html.Th(h) for h in ("Quelle", "Herausgeber", "Lizenz / Nutzung", "Aktualisierung", "Letzter Abruf")])
    rows = []
    for s in sources:
        rows.append(html.Tr([
            html.Td([_link(s["name"], s["url"]), html.Div(s["use"], style={"color": MUTED, "fontSize": "0.74rem"})]),
            html.Td(s["publisher"]), html.Td(s["license"]), html.Td(s["rhythm"]),
            html.Td(times.get(s.get("fetch", ""), "") or "–", style={"whiteSpace": "nowrap"}),
        ]))
    return html.Div(html.Table([html.Thead(head), html.Tbody(rows)], className="od-table"), style={"overflowX": "auto"})


def _auto_rows(st: pd.DataFrame) -> list:
    def stat(key):
        r = st[st["key"] == key] if not st.empty else st
        return r.iloc[0] if not r.empty else None

    def cell(key, fallback):
        r = stat(key)
        if r is None:
            return html.Td(fallback, style={"color": MUTED}), html.Td("–")
        return (html.Td([html.Span("● ", style={"color": STATE_COLOR.get(r["state"], MUTED)}), html.B(STATE_LABEL.get(r["state"], r["state"]) + ": ", style={"color": TEXT}), r["message"]]),
                html.Td(_day(r["last_check"]) + (f" {r['last_check'][11:]} UTC" if r["last_check"] else "")))
    items = [
        ("Weltbank, Eurostat, OpenStreetMap, IWF, Amt für Statistik, BFS", "täglich 06:00 UTC (Worker); Tabellen aus dem Explorer-Cache höchstens alle 7 Tage", None),
        ("Klimaarchiv (ERA5, ab 1950)", "täglich 06:00 UTC bis vollständig, danach jährlich ab 15. Januar; bei HTTP 429/Tageslimit am nächsten Tag weiter", "klima"),
        ("Polizei-Jahresberichte", "monatlich (Worker prüft die Berichtsseite; robots.txt und 2 s Pause beachtet)", "polizei"),
        ("Landesrechnung Konto 590 (Asylwesen)", "jährlich: ab 1. März des Folgejahres, danach wöchentlich bis der Bericht gefunden und geprüft ist", "landesrechnung"),
        ("Projektionen", "wöchentlich neu berechnet (Rückwärtstest und Intervalle)", None),
        ("opendata.li Discovery (neue/entfernte Datensätze)", "sonntags 05:30 UTC – erzeugt nur Meldungen im Tab «Open Data», veröffentlicht nichts automatisch", None),
        ("CIA World Factbook (Archiv)", "abgeschlossen – die CIA hat das Factbook eingestellt, nichts mehr nachzuführen", None),
    ]
    out = []
    for name, rhythm, key in items:
        c, t = cell(key, "läuft nach dem Rhythmus links ohne gesonderte Statusmeldung") if key else (html.Td("–", style={"color": MUTED}), html.Td("–"))
        out.append(html.Tr([html.Td(html.B(name, style={"color": TEXT})), html.Td(rhythm), c, t]))
    return out


def _ai_note() -> list:
    """KI-Hinweis; ändert sich, sobald die Funktion «Frage zu den Daten» eingeschaltet ist."""
    import chat_budget
    if chat_budget.load_config().enabled:
        return [html.B("KI nur in «Frage zu den Daten»: ", style={"color": TEXT}),
                "Dort übersetzt ein KI-Modell (Anthropic Claude Haiku) eine Frage in eine Abfrage; Abfrage, Rechnung, Tabelle, Diagramm und Quelle erzeugt der Server aus den Daten dieses Dashboards. "
                "Die Frage und das Abfrageergebnis werden dafür an Anthropic (USA) übermittelt. Fragen werden gekürzt höchstens 30 Tage zur Missbrauchsabwehr gespeichert, ohne IP-Adresse. "
                "Sonst werden zur Laufzeit keine KI-Dienste aufgerufen; alle anderen Werte werden mit festen Rechenregeln aufbereitet. "]
    return [html.B("Keine KI auf daten.li: ", style={"color": TEXT}),
            "Es werden zur Laufzeit keine KI-Dienste aufgerufen und keine Texte oder Zahlen von einer KI erzeugt. Die Werte werden aus den Quellen gelesen und mit festen Rechenregeln "
            "aufbereitet. "]


def render_quellen() -> list:
    times = fetch_times()
    st = db.read_auto_status()
    out = [
        html.H4("Datenquellen", className="section-title"),
        _card([html.P([
            "Alle Zahlen auf diesem Dashboard stammen aus den unten genannten öffentlichen Quellen. Bei jeder Grafik steht die Quelle, hier steht sie je Bereich mit Herausgeber, "
            "Lizenz bzw. Nutzungsbedingung, Aktualisierungsrhythmus und dem Datum des letzten Abrufs in der Datenbank dieses Dashboards. ",
            *_ai_note(),
            html.B("Prognosen und Korrelationen sind Statistik: ", style={"color": TEXT}),
            "Projektionen (ARIMA/ETS) und Korrelationskoeffizienten beschreiben Muster in vergangenen Daten, sie sind keine Vorhersagen und sagen nichts über Ursachen. "
            "Dies ist keine offizielle Seite, sondern ein unabhängiges Hobby- und Freizeitprojekt ohne Verbindung zu den genannten Stellen."],
            style={"color": MUTED, "fontSize": "0.85rem", "marginBottom": "0", "lineHeight": "1.55"})]),
        html.Div(style={"height": "14px"}),
    ]
    out.append(_card([
        html.H6("Was ist automatisch, was nicht?", style={"color": TEXT}),
        html.P("Nichts muss von Hand nachgeführt werden. Neue Jahre aus PDF-Berichten (Polizei, Landesrechnung) werden nur übernommen, wenn die Prüfungen bestehen; "
               "sonst bleibt der alte Stand sichtbar und das neue Jahr erscheint hier und im jeweiligen Tab als «wartet auf Prüfung».",
               style={"color": MUTED, "fontSize": "0.8rem"}),
        html.Div(html.Table([html.Thead(html.Tr([html.Th(h) for h in ("Bereich", "Rhythmus", "Zustand", "Letzte Prüfung")])), html.Tbody(_auto_rows(st))],
                            className="od-table"), style={"overflowX": "auto"}),
    ]))
    out.append(html.Div(style={"height": "14px"}))
    for area, sources in REGISTRY:
        out.append(_card([html.H6(area, style={"color": TEXT}), _table(sources, times)]))
        out.append(html.Div(style={"height": "12px"}))
    out.append(_card([
        html.H6("Kontakt", style={"color": TEXT}),
        html.P(["Fragen, Korrekturen und Hinweise zu Quellen: ",
                html.A("kontakt [at] daten.li", href="#", className="disclaimer-link", **{"data-contact": "1"}),
                ". Daten werden aus den Quellen übernommen; Rechenschritte und Einschränkungen sind im jeweiligen Tab erklärt."],
               style={"color": MUTED, "fontSize": "0.85rem", "marginBottom": "0"}),
    ]))
    return out
