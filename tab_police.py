"""
tab_police.py — Tab «Polizeistatistik»
======================================
1. Landespolizei Liechtenstein: Kennzahlen aus den Jahresberichten ab 2009 (Erstimport und monatliche Prüfung auf neue Berichte, police.py).
   Jeder Wert ist mit Berichtsjahr, Seite und Textausschnitt belegt; Definitionswechsel sind markiert.
2. Eurostat crim_just_ctz (Verdächtige/Strafverfolgte/Verurteilte nach Staatsangehörigkeit, Ländervergleich) mit
   Raten je Gruppe und den methodischen Hinweisen (vorher im Tab «Migration»).
Keine Schätzungen: was sich aus den Berichten nicht eindeutig lesen liess, bleibt leer und ist unter «Abdeckung» aufgeführt.
"""

import dash_bootstrap_components as dbc
import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, callback, dcc, html, no_update

from db import read_police_delikte, read_police_metrics, read_police_reports
from migration import COUNTRY_NAMES, es_id
from tab_migration import (CRIME_CAVEATS, LI, LI_COLOR, DEFAULT_COUNTRIES, ES_LICENSE, STAGES, STAGE_NAME, URL, _col, _foreign_pop,
                           _g, _graph, _name, _note, _section, _source, _stand)
from ui import FL_BLUE, FL_RED, FL_GOLD, ACCENT, GREEN, MUTED, TEXT, BORDER, _card, _kpi, _styled, _empty

POLICE_URL = "https://www.landespolizei.li/ueber-uns/jahresberichte"


def _span() -> str:
    """«2009–2025» aus den tatsächlich gespeicherten Berichten (wächst mit der automatischen Nachführung)."""
    r = read_police_reports()
    if r.empty:
        return "ab 2009"
    r = r[r["error"].fillna("") == ""]
    return f"{int(r['year'].min())}–{int(r['year'].max())}" if not r.empty else "ab 2009"
COUNTRY_OPTS = [{"label": COUNTRY_NAMES[c], "value": c} for c in COUNTRY_NAMES if c not in ("USA", "CHN", "RUS")]

METRIC_LABELS = {
    "straftaten_stgb": "Straftatbestände nach StGB", "aufklaerungsquote_pct": "Aufklärungsquote (%)",
    "aufklaerungsquote_alt_pct": "Aufklärungsquote 2009/2010 (ohne Wirtschafts-/BMG-Delikte, %)",
    "tatverdaechtige_stgb": "Tatverdächtige Personen (StGB)", "tv_anteil_li_pct": "Tatverdächtige: Anteil Liechtensteiner (%)",
    "tv_anteil_auslaender_pct": "Tatverdächtige: Anteil Ausländer (%)", "tv_weiblich_pct": "Tatverdächtige: Anteil weiblich (%)",
    "tv_minderjaehrig": "Minderjährige Tatverdächtige (Jugendgewalt)", "notrufe": "Notrufe/Meldungen (LNEZ)",
    "einsaetze_lnez": "Disponierte Einsätze (LNEZ)", "unfaelle_total": "Verkehrsunfälle total",
    "unfaelle_sachschaden": "Verkehrsunfälle mit Sachschaden", "unfaelle_verletzte_ereignisse": "Verkehrsunfälle mit Verletzten",
    "verletzte": "Verletzte Personen (Verkehrsunfälle)", "unfaelle_toedlich": "Verkehrsunfälle mit tödlichem Ausgang",
    "verkehrstote": "Verkehrstote", "uhaft_total": "Untersuchungshaften total",
    "uhaft_li": "U-Haft: Liechtensteiner", "uhaft_ausl_fl": "U-Haft: Ausländer mit Wohnsitz in FL",
    "uhaft_ausl_ausland": "U-Haft: Ausländer mit Wohnsitz im Ausland",
    "delikt_wirtschaft": "Wirtschaftsdelikte (Tatbestände)", "delikt_vermoegen": "Vermögens- und Eigentumsdelikte (Tatbestände)",
    "delikt_gewalt": "Gewaltdelikte (Tatbestände)", "delikt_sexual": "Sexualdelikte (Tatbestände)",
    "delikt_drogen": "Betäubungsmitteldelikte (Tatbestände)", "delikt_migration": "Migrationsdelikte (Tatbestände)",
}

# Belegte Definitionshinweise aus den Berichten (siehe police.py für Herleitung)
DEF_NOTES = [
    ("Straftaten", "Die Kriminalstatistik ist eine «Anzeigenstatistik» (Berichte 2019–2024) bzw. «Straftaten- und keine Fallstatistik» (2025): "
     "alle angezeigten Straftaten mit Tatort Liechtenstein, Hellfeld (Dunkelfeld nicht erfasst). Personen ohne Wohnsitz in Liechtenstein sind eingeschlossen."),
    ("Aufklärungsquote 2009/2010", "Quote «ohne Wirtschafts- und Betäubungsmitteldelikte» (2009: 38 %, 2010: 38 %) — andere Definition als ab 2014; "
     "deshalb nicht mit der Reihe ab 2014 verbunden."),
    ("Aufklärungsquote 2011–2013", "In den Berichten nicht als Zahl im Text ausgewiesen (nur Grafik/qualitativ) — Lücke, nicht geschätzt."),
    ("Aufklärungsquote 2014–2016", "Wert genannt, Berechnungsbasis nicht beschrieben; ab Bericht 2017 ausdrücklich «Straftatbestände des StGB und des "
     "Betäubungsmittelgesetzes». Ob 2014–2016 gleich gerechnet wurde, geht aus den Berichten nicht hervor."),
    ("Tatverdächtige Personen", "Ermittelte Personen mit Straftaten nach StGB; Mehrfachzählung in der Deliktsgruppen-Tabelle möglich (Summe ≠ Total)."),
    ("Notrufe", "Zählweise nicht über alle Jahre gleich beschrieben (bis 2013 «Notrufe», ab 2018 «Meldungen» über 112/117/118/144) — "
     "Reihe nur mit Vorsicht über die Jahre lesen."),
    ("Verkehrsunfälle ab 2024", "Bis 2023 stammen die Werte aus der Tabelle «Verkehrsunfallstatistik», 2024/2025 aus dem Berichtstext "
     "(gleiche Grössen, aber Tabelle fehlt)."),
    ("Deliktsgruppen", "Es gilt die «interpretierte Kriminalstatistik» (verdichtete Auswahl von Tatbeständen); Vergleich mit Zahlen vor 2007 nur begrenzt möglich."),
]


def sidebar_section() -> html.Div:
    return html.Div(id="filter-police", children=[
        html.Div([
            html.Label("Länder (Eurostat-Vergleich)", className="filter-label"),
            dcc.Dropdown(id="pol-countries", options=COUNTRY_OPTS, value=DEFAULT_COUNTRIES, multi=True, clearable=False,
                         className="fl-dropdown"),
        ], className="filter-section"),
        html.Div([
            html.Label("Stufe (Eurostat)", className="filter-label"),
            dcc.RadioItems(id="pol-stage", options=STAGES, value="PER_SUSP", className="fl-checklist", labelClassName="checklist-label"),
        ], className="filter-section"),
        html.Div([
            html.Label("Jahr (Ländervergleich)", className="filter-label"),
            dcc.Slider(id="pol-year", min=2008, max=2025, step=1, value=2023,
                       marks={y: {"label": str(y), "style": {"color": MUTED, "fontSize": "10px"}} for y in range(2010, 2026, 5)},
                       tooltip={"placement": "bottom", "always_visible": True}, className="fl-slider"),
        ], className="filter-section"),
    ])


# ── Hilfen ────────────────────────────────────────────────────────────────────

def _series(m: pd.DataFrame, key: str) -> pd.DataFrame:
    d = m[m["metric"] == key].sort_values("year")
    return d


def _bad(d: pd.DataFrame) -> pd.Series:
    """Werte mit Querprüf-Hinweis (Vorjahr abweichend) werden hohl dargestellt."""
    return d["flag"].fillna("").str.len() > 0


def _bar(m, key, title, color, fmt=",.0f", suffix=""):
    d = _series(m, key)
    if d.empty:
        return _empty(f"{METRIC_LABELS[key]}: keine Werte gelesen.")
    fig = go.Figure(go.Bar(x=d["year"], y=d["value"], marker_color=color,
                           hovertemplate=f"%{{x}}: %{{y:{fmt}}}{suffix}<extra></extra>", customdata=d["page"]))
    _styled(fig, title, legend=False)
    fig.update_xaxes(tickformat="d", dtick=1 if len(d) < 12 else 2)
    return _card(_graph(fig))


def _lines(m, items, title, unit="", fmt=",.0f", bars=False):
    """items: [(Kennzahl, Name, Farbe, dash)] — gestrichelt/hohl bei Querprüf-Hinweis."""
    fig = go.Figure()
    for key, name, color, dash in items:
        d = _series(m, key)
        if d.empty:
            continue
        bad = _bad(d)
        trace = go.Bar if bars else go.Scatter
        kw = dict(x=d["year"], y=d["value"], name=name, hovertemplate=f"<b>{name}</b> %{{x}}: %{{y:{fmt}}}{unit}<extra></extra>")
        if bars:
            fig.add_trace(trace(marker_color=color, **kw))
        else:
            fig.add_trace(trace(mode="lines+markers", line=dict(color=color, width=2.4, dash=dash or "solid"),
                                marker=dict(size=7, symbol=["circle-open" if b else "circle" for b in bad]), **kw))
    if not fig.data:
        return _empty("Keine Werte gelesen.")
    _styled(fig, title, legend=len(fig.data) > 1)
    fig.update_xaxes(tickformat="d")
    if bars:
        fig.update_layout(barmode="stack")
    return _card(_graph(fig))


# ── Abschnitt 1: Landespolizei ────────────────────────────────────────────────

def section_police():
    m = read_police_metrics()
    out = []
    if m.empty:
        return [_empty("Die Jahresberichte wurden noch nicht importiert (police.py, einmaliger Import).")]
    reports = read_police_reports()
    years = sorted(m["year"].unique())

    def last(key):
        d = _series(m, key)
        return d.iloc[-1] if not d.empty else None

    kpis = []
    for key, icon, label, color, fmt in (
        ("straftaten_stgb", "fa-scale-balanced", "Straftatbestände StGB", FL_BLUE, lambda v: f"{v:,.0f}".replace(",", "’")),
        ("aufklaerungsquote_pct", "fa-magnifying-glass", "Aufklärungsrate", GREEN, lambda v: f"{v:.0f} %"),
        ("tatverdaechtige_stgb", "fa-user-secret", "Tatverdächtige Personen", FL_RED, lambda v: f"{v:,.0f}".replace(",", "’")),
        ("verkehrstote", "fa-car-burst", "Verkehrstote", FL_GOLD, lambda v: f"{v:.0f}"),
    ):
        r = last(key)
        if r is not None:
            kpis.append(dbc.Col(_kpi(icon, f"{label} ({int(r['year'])})", fmt(r["value"]), color, "Landespolizei, Jahresbericht"),
                                md=3, sm=6, className="mb-3"))
    out.append(dbc.Row(kpis, className="g-3"))

    out.append(dbc.Row([
        dbc.Col(_bar(m, "straftaten_stgb", "Straftatbestände nach StGB", FL_BLUE), md=6, className="mb-3"),
        dbc.Col(_aufklaerung(m), md=6, className="mb-3")], className="g-3"))
    out.append(dbc.Row([
        dbc.Col(_lines(m, [("tatverdaechtige_stgb", "Tatverdächtige Personen (StGB)", FL_RED, None),
                           ("tv_minderjaehrig", "davon minderjährig (Jugendgewalt)¹", ACCENT, "dot")],
                       "Tatverdächtige Personen"), md=6, className="mb-3"),
        dbc.Col(_lines(m, [("tv_anteil_auslaender_pct", "Anteil Ausländer", FL_RED, None), ("tv_anteil_li_pct", "Anteil Liechtensteiner", FL_BLUE, None)],
                       "Tatverdächtige: Staatsangehörigkeit (%)", unit=" %", fmt=".0f"),
                md=6, className="mb-3")], className="g-3"))
    out.append(_note("¹ «Minderjährige Tatverdächtige»: Tatverdächtige im Zusammenhang mit Jugendgewalt (Gewaltdelikte), nicht alle minderjährigen Tatverdächtigen. "
                     "Der Ausländeranteil bezieht sich auf alle ermittelten Tatverdächtigen mit Tatort Liechtenstein — er enthält Personen OHNE Wohnsitz in "
                     "Liechtenstein und ist daher nicht mit dem Anteil an der Wohnbevölkerung (rund 35 %) vergleichbar. 2009: nur «67 % Ausländer» genannt; "
                     "2009/2011/2012 ohne Liechtensteiner-Anteil im Text."))
    out.append(dbc.Row([
        dbc.Col(_lines(m, [("delikt_wirtschaft", "Wirtschaft", FL_GOLD, None), ("delikt_vermoegen", "Vermögen/Eigentum", FL_BLUE, None),
                           ("delikt_gewalt", "Gewalt", FL_RED, None), ("delikt_drogen", "Betäubungsmittel", GREEN, None),
                           ("delikt_sexual", "Sexualdelikte", ACCENT, "dot"), ("delikt_migration", "Migration", MUTED, "dot")],
                       "Tatbestände nach Deliktsgruppen"), md=12, className="mb-3")], className="g-3"))
    out.append(_note("Deliktsgruppen: Werte stehen nur in den Jahren, in denen sie im Berichtstext/in der Tabelle eindeutig lesbar waren; hohle Marker = "
                     "Vorjahreswert im Folgebericht weicht ab (Korrektur/anderer Zählstand). Drogendelikte schwanken stark mit Kontrolltätigkeit "
                     "(Eigenkonsum)."))
    out.append(dbc.Row([
        dbc.Col(_lines(m, [("unfaelle_total", "Verkehrsunfälle total", FL_BLUE, None), ("unfaelle_verletzte_ereignisse", "mit Verletzten", FL_GOLD, None),
                           ("verletzte", "verletzte Personen", FL_RED, "dot")], "Verkehrsunfälle (Landespolizei)"), md=6, className="mb-3"),
        dbc.Col(_lines(m, [("verkehrstote", "Verkehrstote", FL_RED, None), ("unfaelle_toedlich", "Unfälle mit tödlichem Ausgang", MUTED, "dot")],
                       "Verkehrstote und tödliche Unfälle", fmt=".0f"), md=6, className="mb-3")], className="g-3"))
    out.append(dbc.Row([
        dbc.Col(_lines(m, [("uhaft_li", "Liechtensteiner", FL_BLUE, None), ("uhaft_ausl_fl", "Ausländer, Wohnsitz in FL", ACCENT, None),
                           ("uhaft_ausl_ausland", "Ausländer, Wohnsitz im Ausland", FL_RED, None)],
                       "Neue Untersuchungshaften nach Herkunft", fmt=".0f", bars=True), md=6, className="mb-3"),
        dbc.Col(_lines(m, [("notrufe", "Notrufe/Meldungen", FL_GOLD, None), ("einsaetze_lnez", "Disponierte Einsätze", FL_BLUE, None)],
                       "Notrufzentrale LNEZ"), md=6, className="mb-3")], className="g-3"))
    out.append(_note("Untersuchungshaften: kleine Zahlen (≈ 7–24 pro Jahr), starke Schwankungen sind normal; die Wohnsitz-Aufteilung wird nicht in allen Jahren "
                     "ausgewiesen. LNEZ: Zählweise nicht über alle Jahre gleich beschrieben."))

    # Abdeckung
    keys = [k for k in METRIC_LABELS if k in set(m["metric"])]
    have = {(r.year, r.metric) for r in m.itertuples()}
    head = html.Tr([html.Th("Kennzahl")] + [html.Th(str(y), style={"textAlign": "center"}) for y in years])
    rows = []
    for k in METRIC_LABELS:
        cells = []
        for y in years:
            ok = (y, k) in have
            cells.append(html.Td("●" if ok else "–", style={"textAlign": "center", "color": GREEN if ok else BORDER}))
        rows.append(html.Tr([html.Td(METRIC_LABELS[k])] + cells))
    err = reports["error"].fillna("") if not reports.empty else pd.Series(dtype=str)
    wait = reports[err.str.startswith("wartet auf Prüfung")] if not reports.empty else reports
    miss = reports[(err != "") & ~err.str.startswith("wartet auf Prüfung")] if not reports.empty else reports
    ok_n = int((err == "").sum()) if not reports.empty else 0
    hold = html.Div([html.I(className="fas fa-hourglass-half", style={"marginRight": "6px", "color": FL_GOLD}),
                     html.B("Neues Jahr wartet auf Prüfung: ", style={"color": TEXT}),
                     "; ".join(f"Bericht {int(r.year)} ist abgerufen, aber nicht veröffentlicht ({r.error.replace('wartet auf Prüfung: ', '')})" for r in wait.itertuples()),
                     ". Die automatische Übernahme gibt ein neues Jahr nur frei, wenn alle Kernkennzahlen gefunden werden und keine Abweichung zum Vorjahr auftritt."],
                    style={"color": MUTED, "fontSize": "0.8rem", "marginBottom": "8px", "padding": "8px 10px", "border": f"1px solid {FL_GOLD}", "borderRadius": "6px"}) \
        if not wait.empty else None
    cov = _card([
        html.H6("Abdeckung: welche Kennzahlen in welchem Jahresbericht gefunden wurden", style={"color": TEXT}),
        hold,
        html.P("● = Wert im Bericht eindeutig gelesen (mit Seite und Quelltext belegt); – = nicht gefunden/nicht maschinenlesbar (kein Schätzwert). "
               + ("Fehlende Berichte: " + ", ".join(str(y) for y in miss["year"]) + ". " if not miss.empty else "")
               + f"Berichte {_span()} ({ok_n} Dateien) ausgewertet; die Seite der Landespolizei wird monatlich automatisch auf neue Jahresberichte geprüft.",
               style={"color": MUTED, "fontSize": "0.8rem"}),
        html.Div(html.Table([html.Thead(head), html.Tbody(rows)], className="od-table"), style={"overflowX": "auto"}),
    ])
    out.append(cov)

    # Belege je Kennzahl
    out.append(_card([
        html.H6("Beleg je Wert: Seite und Quelltext im Jahresbericht", style={"color": TEXT}),
        dcc.Dropdown(id="pol-trace-metric", options=[{"label": METRIC_LABELS[k], "value": k} for k in keys], value=keys[0] if keys else None,
                     clearable=False, className="fl-dropdown"),
        html.Div(id="pol-trace", style={"marginTop": "10px"}),
    ]))
    notes = _card([
        html.H6("Definitionen und Definitionswechsel (belegt aus den Berichten)", style={"color": TEXT}),
        html.Ul([html.Li([html.B(t + ": ", style={"color": TEXT}), x], style={"marginBottom": "3px"}) for t, x in DEF_NOTES],
                style={"color": MUTED, "fontSize": "0.8rem", "paddingLeft": "18px", "marginBottom": "0"})])
    out.append(notes)
    st = reports["retrieved"].max() if not reports.empty else ""
    out.append(_source(("Landespolizei Fürstentum Liechtenstein, Jahresberichte {}".format(_span()), POLICE_URL),
                       ("öffentlich zugängliche amtliche Publikation, keine ausdrückliche Lizenz angegeben — hier nur Kennzahlen mit Quellen- und Seitenangabe", None),
                       (f"Abruf: {st}" if st else "Abruf unbekannt", None)))
    return out


def _aufklaerung(m):
    a = _series(m, "aufklaerungsquote_pct")
    b = _series(m, "aufklaerungsquote_alt_pct")
    fig = go.Figure()
    if not b.empty:
        fig.add_trace(go.Scatter(x=b["year"], y=b["value"], mode="markers", name="2009/10: andere Definition",
                                 marker=dict(color=MUTED, size=9, symbol="diamond")))
    if not a.empty:
        fig.add_trace(go.Scatter(x=a["year"], y=a["value"], mode="lines+markers", name="Aufklärungsrate",
                                 line=dict(color=GREEN, width=2.6)))
        fig.add_vline(x=2016.5, line_dash="dot", line_color=MUTED, annotation_text="ab 2017: StGB + BMG",
                      annotation_font_color=MUTED, annotation_position="bottom left")
    if not fig.data:
        return _empty("Keine Werte gelesen.")
    _styled(fig, "Aufklärungsquote (%)")
    fig.update_yaxes(ticksuffix=" %", range=[0, 100])
    fig.update_xaxes(tickformat="d")
    fig.update_layout(legend=dict(orientation="h", y=-0.2, bgcolor="rgba(0,0,0,0)"))
    return _card(_graph(fig))


@callback(Output("pol-trace", "children"), Input("pol-trace-metric", "value"))
def _trace(metric):
    m = read_police_metrics()
    d = m[m["metric"] == metric].sort_values("year")
    if d.empty:
        return _empty("Keine Werte.")
    rows = [html.Tr([html.Td(str(int(r.year))), html.Td(f"{r.value:,.0f}".replace(",", "’") if r.value == int(r.value) else f"{r.value:g}"),
                     html.Td("" if pd.isna(r.prev) else f"{r.prev:g}"), html.Td(str(int(r.page))), html.Td(r.source_text or ""),
                     html.Td(r.flag or "", style={"color": FL_GOLD})]) for r in d.itertuples()]
    return html.Div(html.Table([html.Thead(html.Tr([html.Th(h) for h in ("Jahr", "Wert", "Vorjahr lt. Bericht", "Seite", "Quelltext (Ausschnitt)", "Hinweis")])),
                                html.Tbody(rows)], className="od-table"), style={"maxHeight": "360px", "overflowY": "auto"})


# ── Abschnitt 2: Eurostat-Ländervergleich (aus dem Tab Migration verschoben) ──

def section_eurostat(countries: list[str], stage: str, year: int):
    out = [_card([
        html.H6([html.I(className="fas fa-triangle-exclamation", style={"marginRight": "8px", "color": FL_GOLD}),
                 "Wie lesen? Methodische Hinweise zu den Kennzahlen"], style={"color": TEXT}),
        html.Ul([html.Li(t, style={"marginBottom": "3px"}) for t in CRIME_CAVEATS],
                style={"color": MUTED, "fontSize": "0.8rem", "paddingLeft": "18px", "marginBottom": "0"})]),
        html.Div(style={"height": "10px"}),
        _note("Vergleichbarkeit: Eurostat sammelt die Zahlen nach einheitlicher Meldevorgabe, die nationalen Definitionen (Zählung von Personen/Fällen, Stufe der "
              "Strafverfolgung, Jugendstrafrecht, Behandlung von Nichtansässigen) unterscheiden sich aber. Gezeigt wird deshalb je Land die eigene Zeitreihe und "
              "der Vergleich INNERHALB eines Landes (Bevölkerungs- vs. Tatverdächtigenanteil); ein Ranking der Länder nach Raten wäre nicht belastbar und "
              "wird nicht dargestellt.", "fa-scale-balanced", ACCENT)]
    cr = _g(es_id("crime"))
    fp = _foreign_pop()
    if cr.empty or fp.empty:
        return out + [_empty("Keine Eurostat-Daten in der Datenbank.")]
    c = cr[(cr["unit"] == "NR") & (cr["leg_stat"] == stage) & cr["iso3"].notna()].copy()
    c["year"] = c["time"].astype(int)
    pv = c.pivot_table(index=["iso3", "year"], columns="citizen", values="Wert").reset_index()
    pv = pv.merge(fp[["iso3", "year", "foreign", "NAT", "TOTAL"]].rename(columns={"NAT": "pop_nat", "TOTAL": "pop_total"}), on=["iso3", "year"], how="inner")
    pv["rate_for"] = pv["FOR"] / pv["foreign"] * 1e5
    pv["rate_nat"] = pv["NAT"] / pv["pop_nat"] * 1e5
    pv["share_for"] = pv["FOR"] / (pv["FOR"] + pv["NAT"]) * 100
    name = STAGE_NAME[stage]

    fig = go.Figure()
    for i, cc in enumerate(countries):
        d = pv[pv["iso3"] == cc].sort_values("year")
        if d.empty:
            continue
        col = _col(i, cc)
        fig.add_trace(go.Scatter(x=d["year"], y=d["rate_nat"], mode="lines+markers", name=f"{_name(cc)}: Staatsangehörige", line=dict(color=col, width=2),
                                 hovertemplate=f"<b>{_name(cc)}</b> Inländer %{{x}}: %{{y:,.0f}} je 100 000<extra></extra>"))
        fig.add_trace(go.Scatter(x=d["year"], y=d["rate_for"], mode="lines+markers", name=f"{_name(cc)}: Ausländer*", line=dict(color=col, width=2, dash="dot"),
                                 hovertemplate=f"<b>{_name(cc)}</b> Ausländer* %{{x}}: %{{y:,.0f}} je 100 000<extra></extra>"))
    _styled(fig, f"{name} je 100 000 der Gruppe (*Zähler inkl. Nichtansässige)")
    fig.update_xaxes(tickformat="d")
    out.append(_card(_graph(fig, 400)) if fig.data else _empty("Für die gewählten Länder liegen bei dieser Stufe keine Daten vor."))
    nodata = [cc for cc in countries if pv[pv["iso3"] == cc].empty]
    if nodata:
        out.append(_note("Keine Daten (Eurostat crim_just_ctz) für: " + ", ".join(_name(x) for x in nodata), "fa-triangle-exclamation", FL_GOLD))
    yrs = sorted(pv["year"].unique())
    use = max([y for y in yrs if y <= year] or [yrs[0]])
    d = pv[(pv["year"] == use) & (pv["iso3"].isin(countries))].dropna(subset=["share_for"]).copy()
    if not d.empty:
        d["pop_share"] = d["foreign"] / d["pop_total"] * 100
        d = d.sort_values("share_for")
        f2 = go.Figure()
        f2.add_trace(go.Bar(y=[_name(x) for x in d["iso3"]], x=d["pop_share"], orientation="h", name="Anteil an der Wohnbevölkerung", marker_color=FL_BLUE))
        f2.add_trace(go.Bar(y=[_name(x) for x in d["iso3"]], x=d["share_for"], orientation="h", name=f"Anteil an den {name}*", marker_color=FL_RED))
        _styled(f2, f"Ausländeranteil: Bevölkerung vs. {name}, {use} (%)")
        f2.update_layout(barmode="group", hovermode="closest", margin=dict(l=100, r=20, t=50, b=40))
        f2.update_xaxes(ticksuffix=" %")
        out.append(_card(_graph(f2, max(300, 70 * len(d) + 100))))
        out.append(_note(f"Gezeigt wird {use}" + ("" if use == year else f" (letztes verfügbares Jahr bis {year})") +
                         ". Ein höherer Anteil bei den Personen als in der Bevölkerung ist NICHT als Neigung einer Gruppe zu lesen — siehe methodische Hinweise."))
    st = _stand(es_id("crime"), es_id("pop_cit"))
    out.append(_source(("Eurostat crim_just_ctz (Verdächtige/Strafverfolgte/Verurteilte nach Staatsangehörigkeit), Bevölkerung migr_pop1ctz",
                        URL["es"].format("crim_just_ctz")), (ES_LICENSE, None),
                       ("Raten je Gruppe: eigene Berechnung (Personen / Wohnbevölkerung der Gruppe am 1.1.)", None),
                       (f"Stand der Daten: {st:%d.%m.%Y}" if st else "Stand unbekannt", None)))
    return out


def render_police(data: dict) -> html.Div:
    countries = [c for c in (data.get("pol_countries") or DEFAULT_COUNTRIES) if c in COUNTRY_NAMES] or DEFAULT_COUNTRIES
    stage = data.get("pol_stage") or "PER_SUSP"
    year = int(data.get("pol_year") or 2023)
    return html.Div([
        html.H4("Polizeistatistik – Liechtenstein und Eurostat-Vergleich", className="section-title"),
        _card([html.P("Zahlen sind Gruppenstatistiken ohne Rückschluss auf Einzelne. Kriminalstatistiken zählen angezeigte bzw. ermittelte Personen, nicht begangene "
                      "Taten (Hellfeld); Kennzahlen unterschiedlicher Jahre und Länder sind nur bei gleicher Definition vergleichbar. "
                      "Quellenbasierte Auswertung, keine politische Einordnung.", style={"color": MUTED, "fontSize": "0.82rem", "marginBottom": "0"})]),
        _section(f"1 · Landespolizei Liechtenstein: Jahresberichte {_span()}",
                 "Kennzahlen aus den PDF-Berichten, jeweils mit Seite und Quelltext belegt; Definitionswechsel markiert, Lücken nicht geschätzt."),
        *section_police(),
        _section("2 · Eurostat: Verdächtige, Strafverfolgte und Verurteilte nach Staatsangehörigkeit",
                 "Ländervergleich mit Raten je Gruppe (Methodik und Grenzen direkt dabei)."),
        *section_eurostat(countries, stage, year),
    ])
