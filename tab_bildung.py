"""
tab_bildung.py — Tab «Bildung»
==============================
Schulen, Lernende und Studierende (Amt für Statistik, opendata.li), Staatsbürgerschaft der Schulkinder, Bildungsstand der Bevölkerung,
Staatsausgaben für das Bildungswesen und PISA-Ergebnisse (OECD, über Weltbank EdStats). Jede Grafik nennt Quelle und Stand.
Staatsbürgerschaft ist nicht Migrationshintergrund: Daten zum Migrationshintergrund oder zur Familiensprache liegen nicht vor und werden nicht geschätzt.
"""

import dash_bootstrap_components as dbc
import pandas as pd
import plotly.graph_objects as go
from dash import dcc, html

import bildung as B
from ui import FL_BLUE, FL_RED, FL_GOLD, ACCENT, GREEN, MUTED, TEXT, BORDER, _card, _kpi, _styled, _empty
from tab_migration import LI_COLOR, _graph, _note, _section, _source

PX_URL = "https://www.opendata.li/de/daten"
LICENSE = "CC BY (Namensnennung)"
PALETTE = [FL_RED, FL_GOLD, ACCENT, GREEN, "#BB8FCE", "#F0883E", "#58D68D", "#79C0FF", "#D2A679", "#F85149", "#FBD460"]
TYPES = [{"label": "Alle Schulen", "value": "Total"}, {"label": "Öffentliche Schulen", "value": "Öffentlich"}, {"label": "Private Schulen", "value": "Privat"}]
STAGES = ["Schulstufe - Total", "Kindergarten", "Primarschule", "Sekundarstufe I", "Oberschule", "Realschule", "Gymnasium (1. bis 4. Klasse)", "Sekundarstufe II"]
STAGE_OPTS = [{"label": "Alle Stufen" if s == "Schulstufe - Total" else s, "value": s} for s in STAGES]
STAGE_ORDER = ["Kindergarten", "Primarschule", "Oberschule", "Realschule", "Sekundarstufe I (private)", "Gymnasium (1. bis 4. Klasse)", "Sonderschule",
               "IKDaZ (stufenübergreifend)", "Freiwilliges 10. Schuljahr", "Gymnasium (5. bis 7. Klasse)"]
COUNTRY_OPTS = [{"label": n, "value": c} for c, n in B.PISA_COUNTRIES.items() if c != "LIE"]
PISA_ONLY = {"Lesen": "seit 2000", "Mathematik": "seit 2003", "Naturwissenschaften": "seit 2006"}
SPEND_URL = "https://www.opendata.li/de/daten"
OECD_LI = "https://www.oecd.org/en/about/programmes/pisa/liechtenstein.html"
VN_URL = "https://www.vn.at/vorarlberg/2014/02/18/liechtenstein-nimmt-nicht-mehr-an-pisa-teil.vn"
WB_PISA = "https://data.worldbank.org/indicator/LO.PISA.MAT"


# ── Sidebar ───────────────────────────────────────────────────────────────────

def sidebar_section() -> html.Div:
    return html.Div(id="filter-bildung", children=[
        html.Div([html.Label("Schulstufe (Staatsbürgerschaft)", className="filter-label"),
                  dcc.Dropdown(id="bi-stage", options=STAGE_OPTS, value="Schulstufe - Total", clearable=False, searchable=False, className="fl-dropdown")],
                 className="filter-section"),
        html.Div([html.Label("Schultyp (Schulkinder)", className="filter-label"),
                  dcc.RadioItems(id="bi-type", options=TYPES, value="Total", className="fl-checklist", labelClassName="checklist-label")],
                 className="filter-section"),
        html.Div([html.Label("PISA: Vergleichsländer", className="filter-label"),
                  dcc.Checklist(id="bi-countries", options=COUNTRY_OPTS, value=["CHE", "AUT", "DEU"], className="fl-checklist", labelClassName="checklist-label")],
                 className="filter-section"),
    ])


# ── Hilfen ────────────────────────────────────────────────────────────────────

def _num(x, d=0) -> str:
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return "–"
    return f"{x:,.{d}f}".replace(",", "’")


def _src(*names: str, extra: str = "") -> html.Div:
    """Quellenzeile der gespiegelten Amt-für-Statistik-Tabellen mit Stand (Abrufzeit des Workers)."""
    stamps, tabs = [], []
    for n in names:
        title, ts = B.info(n)
        if ts:
            stamps.append(ts)
        tabs.append((title or "").split(" ")[0])
    tab_txt = ", ".join(t for t in tabs if t)
    parts = [(f"Amt für Statistik Liechtenstein, Tabelle {tab_txt} (opendata.li)" if tab_txt else "Amt für Statistik Liechtenstein (opendata.li)", PX_URL), (LICENSE, None)]
    if stamps:
        parts.append((f"Stand: abgerufen {min(stamps):%d.%m.%Y}", None))
    if extra:
        parts.append((extra, None))
    return _source(*parts)


def _fig(title: str, legend: bool = True) -> go.Figure:
    f = go.Figure()
    _styled(f, title, legend=legend)
    f.update_layout(legend=dict(orientation="h", y=-0.25, bgcolor="rgba(0,0,0,0)"))
    return f


def how_to_read() -> html.Div:
    def item(t, x):
        return html.Li([html.B(t + ": ", style={"color": TEXT}), x], style={"marginBottom": "4px"})
    return _card([
        html.H6([html.I(className="fas fa-book-open", style={"marginRight": "8px", "color": ACCENT}), "Wie lesen? Begriffe und Grenzen"], style={"color": TEXT}),
        html.Ul([
            item("Schuljahr", "«2024/25» steht in den Grafiken als 2025 (Jahr des Schuljahresendes). PISA wird im Frühjahr getestet; das Schuljahr, in dem getestet wurde, endet im selben Jahr."),
            item("Staatsbürgerschaft ≠ Migrationshintergrund", "Die Statistik weist die Staatsbürgerschaft der Schulkinder aus (Liechtenstein, CH/AT/DE, übrige). "
                 "Eingebürgerte Kinder zählen als Liechtensteiner, Kinder mit ausländischem Pass können hier geboren sein. Migrationshintergrund, Familiensprache oder "
                 "Herkunft der Eltern liegen nicht vor und werden nicht geschätzt."),
            item("Schulstufen", "Primarstufe inkl. Kindergarten, Sekundarstufe I (Oberschule, Realschule, private Sekundarstufe I, Gymnasium 1.–4. Klasse), Sekundarstufe II "
                 "(Gymnasium 5.–7. Klasse, Freiwilliges 10. Schuljahr). Die meisten 15-Jährigen (PISA-Zielgruppe) besuchen die Sekundarstufe I."),
            item("PISA", "Mittelwerte je Fach auf der PISA-Skala. Liechtenstein hat nur an den Erhebungen 2000–2012 teilgenommen; pro Erhebung wurden nur wenige hundert "
                 "15-Jährige getestet, daher ist die statistische Unsicherheit der Mittelwerte deutlich grösser als bei grossen Ländern — kleine Unterschiede sind nicht aussagekräftig. "
                 "Trendvergleiche gelten laut OECD-Konvention für Lesen ab 2000, Mathematik ab 2003, Naturwissenschaften ab 2006."),
            item("Lehrpersonal", "Vollzeitäquivalente (VZÄ), nicht Köpfe. Bildungsausgaben: Staatsausgaben nach Funktion «Bildungswesen» (internationale COFOG-Klassifikation), "
                 "Land, Gemeinden und Sozialversicherungen zusammen; Mio. CHF laufende Preise."),
        ], style={"color": MUTED, "fontSize": "0.8rem", "paddingLeft": "18px", "marginBottom": "0"}),
    ])


# ── Auswertung ────────────────────────────────────────────────────────────────

def render_bildung(data: dict) -> html.Div:
    stage = data.get("bi_stage") or "Schulstufe - Total"
    typ = data.get("bi_type") or "Total"
    countries = data.get("bi_countries")
    countries = ["CHE", "AUT", "DEU"] if countries is None else countries
    out = [html.H4("Bildung", className="section-title"), how_to_read(), html.Div(style={"height": "12px"})]
    pup = B.pupils_by_stage()
    if pup.empty:
        out.append(_empty("Bildungsdaten noch nicht geladen (der Worker spiegelt sie täglich/wöchentlich)."))
        return html.Div(out)

    # ── Kennzahlen ───────────────────────────────────────────────────────────
    last = int(pup["year"].max())
    tot = pup[(pup["Typ"] == "Total") & (pup["Stufe"] == "Schulstufe - Total")].set_index("year")["Wert"]
    share = B.nonli_share()
    share_s1 = B.nonli_share_sek1()
    staff = B.with_year(B._g("staff"), "Schuljahr")
    lehr = staff[staff["Personalkategorie"] == "Lehrpersonal (VZÄ)"].set_index("year")["Wert"] if not staff.empty else pd.Series(dtype=float)
    stu = B.with_year(B._g("students"), "Jahr")
    stu_t = stu[stu["Ausbildungsstätte"] == "Ausbildungsstätte - Total"].set_index("year")["Wert"] if not stu.empty else pd.Series(dtype=float)
    app = B.with_year(B._g("apprentices"), "Jahr")
    app_t = app[app["Wohnland"] == "Wohnland - Total"].set_index("year")["Wert"] if not app.empty else pd.Series(dtype=float)
    sp = B.spend()
    spy = pd.DataFrame()
    if not sp.empty:
        sp = sp.assign(F=sp["Funktion"].str.strip(), year=pd.to_numeric(sp["Jahr"], errors="coerce"))
        spy = sp[sp["Teilsektor"].str.startswith("S.13 ")]
    edu_sp = spy[spy["F"].str.contains("Bildungswesen")].set_index("year")["Wert"] if not spy.empty else pd.Series(dtype=float)
    all_sp = spy[spy["F"] == "Ausgaben"].set_index("year")["Wert"] if not spy.empty else pd.Series(dtype=float)

    def lastv(s):
        s = s.dropna().sort_index()
        return (int(s.index[-1]), s.iloc[-1]) if len(s) else (None, None)

    k = []
    y, v = lastv(tot)
    k.append(dbc.Col(_kpi("fa-children", "Schulkinder", _num(v), FL_BLUE, f"Schuljahr {y - 1}/{str(y)[2:]}" if y else ""), md=3, sm=6, className="mb-3"))
    y, v = lastv(share)
    y1, v1 = lastv(share_s1)
    k.append(dbc.Col(_kpi("fa-passport", "Ohne LI-Staatsbürgerschaft", f"{v:.0f} %".replace(".", ",") if v is not None else "–", FL_RED,
                          f"Sekundarstufe I: {v1:.0f} %".replace(".", ",") if v1 is not None else ""), md=3, sm=6, className="mb-3"))
    y, v = lastv(lehr)
    k.append(dbc.Col(_kpi("fa-chalkboard-user", "Lehrpersonal (VZÄ)", _num(v), GREEN, f"Schuljahr {y - 1}/{str(y)[2:]}" if y else ""), md=3, sm=6, className="mb-3"))
    y, v = lastv(edu_sp)
    ya, va = lastv(all_sp)
    k.append(dbc.Col(_kpi("fa-school", "Bildungsausgaben Staat", f"{_num(v, 0)} Mio. CHF" if v is not None else "–", FL_GOLD,
                           f"{v / va * 100:.1f} % der Staatsausgaben ({y})".replace(".", ",") if v and va else ""), md=3, sm=6, className="mb-3"))
    out.append(dbc.Row(k, className="g-3"))
    k2 = []
    y, v = lastv(stu_t)
    k2.append(dbc.Col(_kpi("fa-graduation-cap", "Studierende (Hochschulen FL)", _num(v), ACCENT, f"Studienjahr {y - 1}/{str(y)[2:]}" if y else ""), md=3, sm=6, className="mb-3"))
    y, v = lastv(app_t)
    k2.append(dbc.Col(_kpi("fa-screwdriver-wrench", "Lernende in FL", _num(v), "#BB8FCE", f"Schuljahr {y - 1}/{str(y)[2:]}" if y else ""), md=3, sm=6, className="mb-3"))
    out.append(dbc.Row(k2, className="g-3"))

    # ── Schulkinder nach Stufe ───────────────────────────────────────────────
    out.append(_section("Schulkinder nach Schulstufe", "Alle Schulstufen zusammen, nach Schultyp wählbar (Seitenleiste). Stapel = Schulstufe."))
    d = pup[(pup["Typ"] == typ)]
    f = _fig(f"Schulkinder in Liechtenstein — {dict((t['value'], t['label']) for t in TYPES)[typ]}")
    for i, s in enumerate(STAGE_ORDER):
        x = d[d["Stufe"] == s].sort_values("year")
        if x["Wert"].fillna(0).sum() > 0:
            f.add_trace(go.Bar(x=x["year"], y=x["Wert"], name=s, marker_color=PALETTE[i % len(PALETTE)], hovertemplate="%{y:,.0f}<extra>" + s + "</extra>"))
    f.update_layout(barmode="stack", legend=dict(orientation="h", y=-0.3, bgcolor="rgba(0,0,0,0)"))
    f.update_xaxes(tickformat="d", title="Schuljahresende")
    out += [_card(_graph(f, 400)), _src("pupils"),
            _note("«Sekundarstufe II» umfasst Gymnasium 5.–7. Klasse und das Freiwillige 10. Schuljahr; Kindergarten gehört zur Primarstufe. "
                  "IKDaZ (stufenübergreifender Deutschunterricht) und Sonderschule sind eigene Zeilen. Hinweis: Das Total kann leicht von der Summe der Zeilen abweichen (Rundung/Schultypen).")]

    # ── Staatsbürgerschaft ───────────────────────────────────────────────────
    cit = B.citizenship()
    out.append(_section("Staatsbürgerschaft der Schulkinder",
                        "Anteil nach Staatsbürgerschaft an allen Schulkindern der gewählten Stufe (Seitenleiste). Staatsbürgerschaft, nicht Migrationshintergrund."))
    if not cit.empty:
        c = cit[cit["Stufe"] == B.clean(stage)]
        p = c.pivot_table(index="year", columns="Bürgerschaft", values="Wert", aggfunc="first")
        if "Total" in p:
            f = _fig(f"Anteil nach Staatsbürgerschaft (%) — {B.clean(stage).replace('Schulstufe - Total', 'alle Stufen')}")
            for i, (col, color) in enumerate((("Liechtenstein", LI_COLOR), ("CH/AT/DE", FL_GOLD), ("Übrige", FL_RED))):
                if col in p:
                    sh = (p[col] / p["Total"] * 100).dropna()
                    f.add_trace(go.Scatter(x=sh.index, y=sh.values, name=col, mode="lines+markers", line=dict(color=color, width=2.4),
                                           hovertemplate="%{y:.1f} %<extra>" + col + "</extra>"))
            f.update_yaxes(title="% der Schulkinder", range=[0, 100])
            f.update_xaxes(tickformat="d", title="Schuljahresende")
            out += [_card(_graph(f, 360)), _src("pupils_cit"),
                    _note("Bei kleinen Stufen (z. B. Sonderschule, IKDaZ) sind die Anteile durch kleine Zahlen volatil. «Ohne liechtensteinische Staatsbürgerschaft» = CH/AT/DE plus übrige. "
                          "Der Anteil sagt nichts über Leistung, Herkunft der Eltern oder Sprache.")]

    # ── PISA ─────────────────────────────────────────────────────────────────
    out.append(_section("PISA: Liechtenstein im Vergleich (Erhebungen 2000–2012)",
                        "Mittelwerte der 15-Jährigen. Liechtenstein nahm nur 2000, 2003, 2006, 2009 und 2012 teil; danach gibt es keine Resultate."))
    pis = B.pisa()
    if pis.empty:
        out.append(_empty("PISA-Daten noch nicht geladen."))
    else:
        order = ["LIE"] + [c for c in ("CHE", "AUT", "DEU") if c in countries]
        legend = html.Div([html.Span([html.Span("━" if i == 0 else "┅", style={"color": LI_COLOR if i == 0 else PALETTE[i], "fontWeight": "700", "marginRight": "4px"}),
                                      B.PISA_COUNTRIES[c]], style={"marginRight": "16px", "color": TEXT, "fontSize": "0.82rem"}) for i, c in enumerate(order)],
                          style={"marginBottom": "6px"})
        cols = [dbc.Col(_card(_graph(_pisa_fig(pis, fach, countries), 320)), lg=4, md=12, className="mb-3") for fach in B.PISA_INDICATORS.values()]
        out += [legend, dbc.Row(cols, className="g-3")]
        li = pis[pis["iso3"] == "LIE"].pivot_table(index="Jahr", columns="Fach", values="Wert")
        rows = [html.Tr([html.Td(str(int(y))) ] + [html.Td(_num(li.loc[y, f]) if f in li and pd.notna(li.loc[y, f]) else "–") for f in B.PISA_INDICATORS.values()]) for y in li.index]
        out.append(_card([html.H6("Liechtenstein: PISA-Mittelwerte je Erhebung", style={"color": TEXT}),
                          html.Div(html.Table([html.Thead(html.Tr([html.Th("Erhebung")] + [html.Th(f) for f in B.PISA_INDICATORS.values()])), html.Tbody(rows)], className="od-table"),
                                   style={"overflowX": "auto"})]))
        out.append(_source((B.PISA_SOURCE, WB_PISA), ("OECD-Seite: Liechtenstein als PISA-Teilnehmer 2000–2012", OECD_LI)))
        out.append(_note(
            "Grenzen: (1) Kleine Stichproben — Unterschiede von einigen Punkten sind statistisch nicht von Zufall zu trennen. (2) Die Fachskalen sind nur ab 2000 (Lesen), 2003 (Mathematik) bzw. 2006 "
            "(Naturwissenschaften) zeitlich vergleichbar; frühere Werte stehen zur Vollständigkeit da. (3) Ein OECD-Durchschnitt je Erhebung ist hier nicht eingezeichnet: Die OECD-Mittel "
            "hängen von der jeweiligen Länderzusammensetzung ab; es lag keine einheitliche maschinenlesbare Reihe vor. Zum Vergleich dienen die Nachbarländer. "
            "(4) Seit 2015 hat Liechtenstein nicht mehr teilgenommen (Regierungsentscheid Anfang 2014).", icon="fa-triangle-exclamation", color=FL_GOLD))
        out.append(_source(("Teilnahmeentscheid: Vorarlberger Nachrichten, 18.02.2014", VN_URL)))

    # ── Klassen und Lehrpersonal ─────────────────────────────────────────────
    cl = B.with_year(B._g("classes"), "Jahr")
    out.append(_section("Klassengrösse und Lehrpersonal"))
    left, right = [], []
    if not cl.empty:
        cg = cl[cl["Kennzahl"] == "Klassengrösse"].assign(S=lambda x: x["Schulstufe"].map(B.clean))
        f = _fig("Durchschnittliche Klassengrösse (Schulkinder je Klasse)")
        for i, s in enumerate(["Schulstufe - Total", "Kindergarten", "Primarschule", "Oberschule", "Realschule", "Gymnasium (1. bis 4. Klasse)", "Gymnasium (5. bis 7. Klasse)"]):
            x = cg[cg["S"] == B.clean(s)].sort_values("year")
            if len(x):
                f.add_trace(go.Scatter(x=x["year"], y=x["Wert"], name="Alle Stufen" if "Total" in s else s, mode="lines+markers",
                                       line=dict(color=LI_COLOR if "Total" in s else PALETTE[i % len(PALETTE)], width=2.4 if "Total" in s else 1.6)))
        f.update_xaxes(tickformat="d", title="Schuljahresende")
        f.update_yaxes(title="Schulkinder je Klasse")
        left = [_card(_graph(f, 360)), _src("classes", extra="Klassengrösse = Schulkinder ÷ Anzahl Klassen, ganzzahlig gerundet ausgewiesen")]
    if not staff.empty:
        f = _fig("Schulpersonal (Vollzeitäquivalente)")
        for i, cat in enumerate(("Lehrpersonal (VZÄ)", "Schulleitung (VZÄ)", "Übriges Personal (VZÄ)")):
            x = staff[staff["Personalkategorie"] == cat].sort_values("year")
            f.add_trace(go.Bar(x=x["year"], y=x["Wert"], name=cat.replace(" (VZÄ)", ""), marker_color=PALETTE[i + 2]))
        f.update_layout(barmode="stack")
        f.update_xaxes(tickformat="d", title="Schuljahresende")
        f.update_yaxes(title="VZÄ")
        right = [_card(_graph(f, 360)), _src("staff", extra="alle Schulstufen und Schultypen, ab Schuljahr 2010/11")]
    out.append(dbc.Row([dbc.Col(left, lg=6, md=12), dbc.Col(right, lg=6, md=12)], className="g-3"))

    # ── Abschlüsse Sekundarstufe II ──────────────────────────────────────────
    gr = B._g("grads")
    if not gr.empty:
        out.append(_section("Abschlüsse der Sekundarstufe II (Matura)", "Abschlüsse nach Profil des Gymnasiums. Eine Abschlussquote (Anteil eines Jahrgangs) wird nicht ausgewiesen."))
        gr = gr.assign(year=pd.to_numeric(gr["Jahr"], errors="coerce"), P=gr["Profil"].map(B.clean))
        f = _fig("Abschlüsse Sekundarstufe II nach Profil")
        prof = [p for p in gr["P"].unique() if "Total" not in p and not p.startswith("davon") and "davon" not in p]
        for i, p in enumerate(prof):
            x = gr[gr["P"] == p].sort_values("year")
            f.add_trace(go.Bar(x=x["year"], y=x["Wert"], name=p, marker_color=PALETTE[i % len(PALETTE)]))
        tot_g = gr[gr["P"].str.contains("Total")].sort_values("year")
        f.add_trace(go.Scatter(x=tot_g["year"], y=tot_g["Wert"], name="Total", mode="lines+markers", line=dict(color=LI_COLOR, width=2.2)))
        f.update_layout(barmode="stack")
        f.update_xaxes(tickformat="d", title="Abschlussjahr")
        f.update_yaxes(title="Abschlüsse")
        out += [_card(_graph(f, 360)), _src("grads", extra="«Lingua» und weitere Profile gemäss Tabelle; das Profil «Lingua» wird auch an privaten Schulen angeboten")]

    # ── Berufliche Grundbildung und Hochschulen ──────────────────────────────
    out.append(_section("Berufliche Grundbildung und Hochschulen"))
    cl_, cr_ = [], []
    if not app.empty:
        f = _fig("Lernende in Liechtenstein nach Wohnland")
        a = app[app["Wohnland"] != "Wohnland - Total"]
        for i, w in enumerate(["Liechtenstein", "Schweiz", "Österreich", "Übrige"]):
            x = a[a["Wohnland"] == w].sort_values("year")
            if len(x):
                f.add_trace(go.Bar(x=x["year"], y=x["Wert"], name=w, marker_color=PALETTE[i % len(PALETTE)]))
        f.update_layout(barmode="stack")
        f.update_xaxes(tickformat="d", title="Schuljahresende")
        f.update_yaxes(title="Lernende")
        cl_ = [_card(_graph(f, 340)), _src("apprentices", extra="Lernende in Liechtensteiner Lehrbetrieben/Berufsschulen, ab 2014/15")]
    if not stu.empty:
        f = _fig("Studierende an Hochschulen in Liechtenstein")
        a = stu[stu["Ausbildungsstätte"] != "Ausbildungsstätte - Total"]
        for i, n in enumerate(a["Ausbildungsstätte"].unique()):
            x = a[a["Ausbildungsstätte"] == n].sort_values("year")
            if x["Wert"].fillna(0).sum() > 0:
                f.add_trace(go.Bar(x=x["year"], y=x["Wert"], name=n.replace("Internationale Akademie für Philosophie im Fürstentum Liechtenstein", "Int. Akademie für Philosophie")
                                   .replace("Private Universität im Fürstentum Liechtenstein", "Private Universität (UFL)"), marker_color=PALETTE[i % len(PALETTE)]))
        f.update_layout(barmode="stack")
        f.update_xaxes(tickformat="d", title="Studienjahresende")
        f.update_yaxes(title="Studierende")
        cr_ = [_card(_graph(f, 340)), _src("students", extra="Studierende, die in Liechtenstein studieren (unabhängig vom Wohnland); ohne Liechtensteiner an Hochschulen im Ausland")]
    out.append(dbc.Row([dbc.Col(cl_, lg=6, md=12), dbc.Col(cr_, lg=6, md=12)], className="g-3"))

    # ── Bildungsstand ────────────────────────────────────────────────────────
    at = B._g("attainment")
    if not at.empty:
        out.append(_section("Bildungsstand der Bevölkerung ab 15 Jahren",
                            "Höchste abgeschlossene Ausbildung nach Staatsangehörigkeit. Zusammensetzung (Alter, Zuwanderungsgründe) der beiden Gruppen ist verschieden — kein Vergleich der «Qualität»."))
        at = at.assign(A=at["Höchste abgeschlossene Ausbildung"].map(B.clean), Y=at["Stichtag"].map(lambda s: int(str(s)[-4:])))
        lev = ["Keine Ausbildung", "Obligatorische Schule", "Diplommittelschule", "Berufliche Grundbildung", "Maturität", "Höhere Fach- und Berufsausbildung", "Höhere Fachschule", "Bachelor, Master", "Doktorat"]
        yrs = sorted(at["Y"].unique())
        ylast = yrs[-1]
        f = _fig(f"Höchste abgeschlossene Ausbildung, Stand 31.12.{ylast} (% ohne «Ohne Angabe»)")
        groups = [("Liechtensteiner", "Liechtensteiner"), ("Ausländer", "Ausländer")]
        for i, l in enumerate(lev):
            ys, xs = [], []
            for h, hl in groups:
                d = at[(at["Y"] == ylast) & (at["Heimat"] == h)]
                tot_ = d[d["A"].isin(lev)]["Wert"].sum()
                v = d[d["A"] == l]["Wert"].sum()
                xs.append(hl)
                ys.append(v / tot_ * 100 if tot_ else None)
            f.add_trace(go.Bar(y=xs, x=ys, name=l, orientation="h", marker_color=PALETTE[i % len(PALETTE)], hovertemplate="%{x:.1f} %<extra>" + l + "</extra>"))
        f.update_layout(barmode="stack", legend=dict(orientation="h", y=-0.35, bgcolor="rgba(0,0,0,0)"))
        f.update_xaxes(title="% der Bevölkerung ab 15 Jahren", range=[0, 100])
        left = [_card(_graph(f, 320))]
        f2 = _fig("Anteil mit Tertiärabschluss (Höhere Berufsbildung/Fachschule, Bachelor/Master, Doktorat)")
        for h, hl in groups:
            xs, ys = [], []
            for y in yrs:
                d = at[(at["Y"] == y) & (at["Heimat"] == h)]
                tot_ = d[d["A"].isin(lev)]["Wert"].sum()
                ter = d[d["A"].isin(["Höhere Fach- und Berufsausbildung", "Höhere Fachschule", "Bachelor, Master", "Doktorat"])]["Wert"].sum()
                if tot_:
                    xs.append(f"31.12.{y}")
                    ys.append(ter / tot_ * 100)
            f2.add_trace(go.Scatter(x=xs, y=ys, name=hl, mode="lines+markers", line=dict(width=2.4, color=LI_COLOR if h == "Liechtensteiner" else FL_RED)))
        f2.update_yaxes(title="% der Bevölkerung ab 15 Jahren")
        right = [_card(_graph(f2, 320))]
        out.append(dbc.Row([dbc.Col(left, lg=7, md=12), dbc.Col(right, lg=5, md=12)], className="g-3"))
        out += [_src("attainment", extra="Stichtage 2010, 2015, 2020 (Registerdaten bzw. Volkszählungsauswertung gemäss Amt)")]

    # ── Bildungsausgaben ─────────────────────────────────────────────────────
    if not spy.empty:
        out.append(_section("Staatsausgaben für das Bildungswesen", "Funktion «9 Bildungswesen» der Staatsausgaben (S.13 Staat und Teilsektoren), Mio. CHF laufende Preise."))
        f = _fig("Ausgaben für das Bildungswesen nach Teilsektor (Mio. CHF)")
        edu = sp[sp["F"].str.contains("Bildungswesen")]
        for i, (code, lab) in enumerate((("S.1311", "Landesebene"), ("S.1313", "Gemeindeebene"))):
            x = edu[edu["Teilsektor"].str.startswith(code)].sort_values("year")
            f.add_trace(go.Bar(x=x["year"], y=x["Wert"], name=lab, marker_color=PALETTE[i + 2]))
        f.update_layout(barmode="stack")
        f.update_xaxes(tickformat="d", title="Jahr")
        f.update_yaxes(title="Mio. CHF")
        f2 = _fig("Anteil Bildungswesen an den gesamten Staatsausgaben (%)", legend=False)
        sh = (edu_sp / all_sp * 100).dropna()
        f2.add_trace(go.Scatter(x=sh.index, y=sh.values, mode="lines+markers", line=dict(color=FL_GOLD, width=2.4), hovertemplate="%{y:.1f} %<extra></extra>"))
        f2.update_xaxes(tickformat="d", title="Jahr")
        f2.update_yaxes(title="%", rangemode="tozero")
        out.append(dbc.Row([dbc.Col(_card(_graph(f, 340)), lg=7, md=12), dbc.Col(_card(_graph(f2, 340)), lg=5, md=12)], className="g-3"))
        out.append(_src("spend", extra="Einheit Mio. CHF abgeleitet aus der Grössenordnung (Gesamtausgaben Staat 2024: 1’912), in den PX-Metadaten nicht ausdrücklich ausgewiesen; ab 2011"))
        out.append(_note("Ausgaben pro Schulkind oder pro Studierenden sind nicht berechnet: Ausgaben (Wohnsitz-/Standortprinzip, Hochschulen, Lernende im Ausland) und Schülerzahlen sind nicht deckungsgleich abgegrenzt."))

    # ── Lücken ───────────────────────────────────────────────────────────────
    out.append(_card([
        html.H6([html.I(className="fas fa-circle-question", style={"marginRight": "8px", "color": FL_GOLD}), "Was nicht verfügbar ist"], style={"color": TEXT}),
        html.Ul([
            html.Li("PISA nach 2012: Liechtenstein hat seit 2015 nicht mehr teilgenommen — es gibt keine neueren Ergebnisse. OECD-Durchschnitt je Erhebung: nicht eingezeichnet (siehe Hinweis oben)."),
            html.Li("Migrationshintergrund, Familiensprache oder Herkunft der Eltern der Schulkinder: nicht in den offenen Daten (nur Staatsbürgerschaft)."),
            html.Li("Maturitäts-/Abschlussquote als Anteil eines Jahrgangs: nicht veröffentlicht; gezeigt werden Abschlusszahlen."),
            html.Li("Bildungsausgaben nach Schulstufe oder pro Kopf nach internationaler Abgrenzung (Eurostat/OECD): für Liechtenstein dort nicht enthalten bzw. leer; die Weltbank-Reihe «Staatsausgaben für Bildung» endet 2011 und ist dünn."),
            html.Li("Offene Datensätze des Schulamts: keine maschinenlesbaren Bildungsdaten gefunden (Suche, nicht abschliessend)."),
        ], style={"color": MUTED, "fontSize": "0.8rem", "paddingLeft": "18px", "marginBottom": "0"}),
    ]))
    return html.Div(out)


def _pisa_fig(pis: pd.DataFrame, fach: str, countries: list) -> go.Figure:
    f = _fig(f"PISA {fach}", legend=False)
    order = ["LIE"] + [c for c in ("CHE", "AUT", "DEU") if c in countries]
    for i, iso in enumerate(order):
        d = pis[(pis["Fach"] == fach) & (pis["iso3"] == iso)].sort_values("Jahr")
        if d.empty:
            continue
        li = iso == "LIE"
        f.add_trace(go.Scatter(x=d["Jahr"], y=d["Wert"], name=B.PISA_COUNTRIES[iso], mode="lines+markers",
                               line=dict(color=LI_COLOR if li else PALETTE[i], width=3 if li else 1.6, dash="solid" if li else "dot"),
                               marker=dict(size=9 if li else 5), hovertemplate="%{x}: %{y:.0f}<extra>" + B.PISA_COUNTRIES[iso] + "</extra>"))
    f.update_xaxes(tickvals=[2000, 2003, 2006, 2009, 2012, 2015, 2018], tickformat="d", tickangle=0, tickfont=dict(size=10))
    f.update_yaxes(title="Punkte")
    f.update_layout(title=dict(text=f"PISA {fach} (vergleichbar {PISA_ONLY[fach]})", font=dict(size=13, color=TEXT)))
    return f
