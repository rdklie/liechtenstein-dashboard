"""
tab_lohn.py — Tab «Lohn»
========================
Lohnstatistik des Amts für Statistik Liechtenstein (monatlicher Bruttolohn, Median und Quartile, Erhebungsjahre 2006–2024 alle zwei Jahre) nach Geschlecht,
Wirtschaftszweig, Alter, Unternehmensgrösse, Wohnsitz, Staatsbürgerschaft und Aufenthaltsstatus, Lohnverteilung, Lohnentwicklung (nominal und – als Näherung –
real) und eine Einordnung mit dem Schweizer Zentralwert (BFS Lohnstrukturerhebung). Jede Grafik nennt Quelle, Stand und Definition.
Nicht enthalten (nicht erhoben bzw. nicht frei verfügbar): Ausbildung, Anforderungsniveau, berufliche Stellung, Stundenlöhne, Mittelwerte; siehe Kasten.
"""

import dash_bootstrap_components as dbc
import pandas as pd
import plotly.graph_objects as go
from dash import dcc, html

import lohn as L
from ui import FL_BLUE, FL_RED, FL_GOLD, ACCENT, GREEN, MUTED, TEXT, _card, _kpi, _styled, _empty
from tab_migration import LI_COLOR, _graph, _note, _section, _source

PX_URL = "https://www.opendata.li/de/daten"
LICENSE = "CC BY (Namensnennung)"
YEARS = list(range(2006, 2025, 2))
GENDERS = [{"label": "Alle", "value": "Geschlecht - Total"}, {"label": "Frauen", "value": "Frauen"}, {"label": "Männer", "value": "Männer"}]
G_COLOR = {"Geschlecht - Total": LI_COLOR, "Frauen": FL_RED, "Männer": FL_BLUE}
G_NAME = {"Geschlecht - Total": "Alle", "Frauen": "Frauen", "Männer": "Männer"}
AGE_ORDER = ["20 bis 24 Jahre", "25 bis 29 Jahre", "30 bis 34 Jahre", "35 bis 39 Jahre", "40 bis 44 Jahre", "45 bis 49 Jahre", "50 bis 54 Jahre", "55 bis 59 Jahre",
             "60 bis 64 Jahre", "65 und mehr Jahre"]
STATUS_ORDER = ["Im Land wohnhafte Landesbürger", "Niedergelassene", "Daueraufenthalter", "Jahresaufenthalter", "Kurzaufenthalter", "Personen ohne Aufenthalt"]


# ── Sidebar ───────────────────────────────────────────────────────────────────

def sidebar_section() -> html.Div:
    return html.Div(id="filter-lohn", children=[
        html.Div([html.Label("Erhebungsjahr (Querschnitte)", className="filter-label"),
                  dcc.Dropdown(id="lo-year", options=[{"label": str(y), "value": y} for y in YEARS], value=YEARS[-1], clearable=False, searchable=False, className="fl-dropdown"),
                  html.Small("Die Lohnstatistik liegt für gerade Jahre vor (2006, 2008, …, 2024).", style={"color": MUTED, "fontSize": "0.7rem"})],
                 className="filter-section"),
        html.Div([html.Label("Geschlecht (Branche, Grösse, Wohnort, Zeitreihen nach Gruppe)", className="filter-label"),
                  dcc.RadioItems(id="lo-geschl", options=GENDERS, value="Geschlecht - Total", className="fl-checklist", labelClassName="checklist-label")],
                 className="filter-section"),
    ])


# ── Hilfen ────────────────────────────────────────────────────────────────────

def _num(x, d=0) -> str:
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return "–"
    return f"{x:,.{d}f}".replace(",", "’")


def _sg(x, d=1) -> str:
    return f"{x:+.{d}f}".replace(".", ",")


def _pct(x, d=1) -> str:
    return "–" if x is None or pd.isna(x) else f"{x:.{d}f} %".replace(".", ",")


def _src(*names: str, extra: str = "", bfs: bool = False) -> html.Div:
    stamps, tabs = [], []
    for n in names:
        title, ts = L.info(n)
        if ts:
            stamps.append(ts)
        if n not in (L.CH_KEY, L.CPI_KEY):
            tabs.append((title or "").split(" ")[0])
    tab_txt = ", ".join(sorted({t for t in tabs if t}))
    parts = [(f"{L.SOURCE_TEXT.split(',')[0]}, Lohnstatistik, Tabelle {tab_txt}" if tab_txt else L.SOURCE_TEXT.split(" (")[0], PX_URL), (LICENSE, None)]
    if bfs:
        parts.insert(1, ("BFS Lohnstrukturerhebung (OGD, © BFS)", "https://www.bfs.admin.ch/bfs/de/home/statistiken/arbeit-erwerb/loehne-erwerbseinkommen-arbeitskosten/lohnniveau-schweiz.html"))
    if stamps:
        parts.append((f"Stand: abgerufen {min(stamps):%d.%m.%Y}", None))
    parts.append(("Monatlicher Bruttolohn, Median, auf Vollzeit (100 %) hochgerechnet, Berichtsjahre 2006–2024 alle 2 Jahre", None))
    if extra:
        parts.append((extra, None))
    return _source(*parts)


def _fig(title: str, legend: bool = True, height: int = 360) -> go.Figure:
    f = go.Figure()
    _styled(f, title, legend=legend)
    f.update_layout(legend=dict(orientation="h", y=-0.25, bgcolor="rgba(0,0,0,0)"), height=height)
    return f


def _row(*cols, md=6):
    return dbc.Row([dbc.Col(c, md=md, className="mb-3") for c in cols], className="g-3")


def how_to_read() -> html.Div:
    def item(t, x):
        return html.Li([html.B(t + ": ", style={"color": TEXT}), x], style={"marginBottom": "4px"})
    return _card([
        html.H6([html.I(className="fas fa-book-open", style={"marginRight": "8px", "color": ACCENT}), "Wie lesen? Definitionen und Grenzen"], style={"color": TEXT}),
        html.Ul([
            item("Median statt Durchschnitt", "Der Median (Zentralwert) teilt die Löhne in zwei gleich grosse Hälften: die eine Hälfte verdient mehr, die andere weniger. "
                 "Er ist unempfindlicher gegen sehr hohe oder tiefe Einzelwerte als der Durchschnitt; der arithmetische Mittelwert wird vom Amt nicht ausgewiesen. "
                 "Quartile: ein Viertel der Löhne liegt unter dem 1., ein Viertel über dem 3. Quartil."),
            item("Brutto, pro Monat, auf Vollzeit", "Monatlicher Bruttolohn nach dem steuerrechtlichen Begriff der Lohnmeldungen (inkl. 1/12 des 13. Monatslohns, Zulagen, Boni, "
                 "Arbeitnehmerbeiträge an die Sozialversicherungen; also nicht netto). Teilzeitlöhne werden anhand des Beschäftigungsgrads auf 100 % hochgerechnet "
                 "(«Vollzeitmonatslohn»); die Häufigkeitsverteilung zeigt dagegen die effektiv bezogenen Monatslöhne."),
            item("Datenbasis", "Lohnmeldungen der Arbeitgebenden an die Steuerverwaltung, verknüpft mit dem Unternehmensregister (Verwaltungsdaten, keine Befragung). Berichtsjahr 2024: "
                 "42 585 Löhne nach Bereinigung (Erfassungsgrad 98 % der Arbeitsverhältnisse); ungewöhnlich tiefe und hohe Löhne sowie Löhne unter 19-Jähriger sind ausgeschlossen. "
                 "Werte mit weniger als 50 Beobachtungen werden nicht ausgewiesen (Lücken in den Grafiken)."),
            item("Wer ist erfasst?", "In Liechtenstein beschäftigte Arbeitnehmende, auch Zupendler aus dem Ausland («Wohnsitz» ist der Wohnort der Beschäftigten, nicht der Arbeitsort). "
                 "Selbständige sind nicht enthalten. Die Zahlen beschreiben Löhne von Arbeitsverhältnissen, nicht Haushaltseinkommen oder Lebenshaltungskosten."),
            item("Erhebungsjahre", "Ergebnisse liegen alle zwei Jahre vor (2006, 2008, … 2024; Veröffentlichung 17 Monate nach Jahresende). Veränderungen beziehen sich deshalb auf zwei Jahre."),
            item("Unterschiede sind unbereinigt", "Lohnunterschiede zwischen Gruppen (z. B. Frauen/Männer, Liechtensteiner/Ausländer) sind Rohvergleiche. Sie enthalten Unterschiede in Branche, Alter, Position, "
                 "Arbeitszeit und Erfahrung und sagen nichts über Ursachen oder über einzelne Personen aus. Ein bereinigter Lohnunterschied wird vom Amt nicht ausgewiesen."),
            item("Reale Löhne", "Für Liechtenstein liegt in den genutzten Quellen kein eigener Preisindex vor. Als Näherung wird der Schweizer Konsumentenpreisindex (Weltbank) verwendet; "
                 "die Zollunion macht ähnliche Preisentwicklungen wahrscheinlich, die Reihe ist aber keine amtliche liechtensteinische Teuerung."),
        ], style={"color": MUTED, "fontSize": "0.8rem", "paddingLeft": "18px", "marginBottom": "0"}),
    ])


def _missing() -> html.Div:
    items = [
        ("Ausbildung, Anforderungsniveau, berufliche Stellung", "Die Lohnstatistik beruht auf Verwaltungsdaten ohne diese Merkmale; das Amt weist sie ausdrücklich als nicht möglich aus."),
        ("Stundenlöhne, Arbeitszeit", "Es gibt nur Monatslöhne, hochgerechnet auf 100 %."),
        ("Durchschnittslohn (arithmetisches Mittel), Perzentile ausser Quartilen", "Das Amt veröffentlicht Median, 1. und 3. Quartil und die Häufigkeitsverteilung."),
        ("Bereinigter Lohnunterschied", "Der Unterschied Frauen/Männer wird nur unbereinigt ausgewiesen (Struktureffekte wie Branche, Alter, Position sind nicht herausgerechnet)."),
        ("Preisindex Liechtenstein", "Keine eigene Teuerungsreihe in den genutzten Quellen (eTab, Weltbank). Reale Löhne sind eine Näherung über den Schweizer Konsumentenpreisindex."),
        ("Jahre zwischen den Erhebungen", "Keine Zwischenwerte: Es gibt keine Erhebung für ungerade Jahre, 2024 ist der jüngste Stand."),
        ("Ländervergleich ausser Schweiz", "Vergleichswerte der EU (Eurostat-Verdienststrukturerhebung) wurden nicht eingebunden; die Definitionen unterscheiden sich (Jahresverdienst/12)."),
    ]
    return _card([
        html.H6([html.I(className="fas fa-circle-info", style={"marginRight": "8px", "color": ACCENT}), "Was nicht verfügbar ist"], style={"color": TEXT}),
        html.Ul([html.Li([html.B(t + ": ", style={"color": TEXT}), x], style={"marginBottom": "4px"}) for t, x in items],
                style={"color": MUTED, "fontSize": "0.8rem", "paddingLeft": "18px", "marginBottom": "0"}),
    ])


# ── Auswertung ────────────────────────────────────────────────────────────────

def render_lohn(data: dict) -> html.Div:
    year = int(data.get("lo_year") or YEARS[-1])
    geschl = data.get("lo_geschl") or "Geschlecht - Total"
    out = [html.H4("Lohn", className="section-title"), how_to_read(), html.Div(style={"height": "12px"})]
    br = L.tidy("branche")
    if br.empty:
        out.append(_empty("Lohndaten noch nicht geladen (der Worker spiegelt sie wöchentlich)."))
        return html.Div(out)
    gname = G_NAME[geschl]

    # ── Kennzahlen ───────────────────────────────────────────────────────────
    med, fem, mal = L.median_series(), L.median_series("Frauen"), L.median_series("Männer")
    gap = L.gap_series()
    last = int(med.index.max())
    prev = int(med.index[med.index < last].max())
    chg = (med[last] / med[prev] - 1) * 100
    out.append(dbc.Row([
        dbc.Col(_kpi("fa-money-bill-wave", f"Medianlohn {last}", f"CHF {_num(med[last])}", FL_BLUE, f"{_sg(chg)} % ggü. {prev} (nominal)"), md=3, sm=6, className="mb-3"),
        dbc.Col(_kpi("fa-venus", f"Frauen {last}", f"CHF {_num(fem[last])}", FL_RED, f"{_sg((fem[last] / fem[prev] - 1) * 100)} % ggü. {prev}"), md=3, sm=6, className="mb-3"),
        dbc.Col(_kpi("fa-mars", f"Männer {last}", f"CHF {_num(mal[last])}", GREEN, f"{_sg((mal[last] / mal[prev] - 1) * 100)} % ggü. {prev}"), md=3, sm=6, className="mb-3"),
        dbc.Col(_kpi("fa-scale-unbalanced", f"Lohnunterschied {last}", _pct(gap[last]), FL_GOLD, f"{_sg(gap[last] - gap[prev])} Prozentpunkte ggü. {prev} · unbereinigt"), md=3, sm=6, className="mb-3"),
    ], className="g-3"))

    # ── 1 Entwicklung ────────────────────────────────────────────────────────
    out.append(_section("1 · Lohnentwicklung", "Median des monatlichen Bruttolohns; nominal in laufenden Franken, real als Näherung in Preisen des letzten Erhebungsjahres."))
    q1, q3 = L.median_series(kennzahl="1. Quartil"), L.median_series(kennzahl="3. Quartil")
    f1 = _fig("Medianlohn Liechtenstein (CHF je Monat)")
    f1.add_trace(go.Scatter(x=q3.index, y=q3.values, mode="lines", line=dict(width=0), showlegend=False, hoverinfo="skip"))
    f1.add_trace(go.Scatter(x=q1.index, y=q1.values, mode="lines", line=dict(width=0), fill="tonexty", fillcolor="rgba(240,246,252,0.10)", name="1.–3. Quartil (alle)",
                            hovertemplate="%{x}: 1. Quartil CHF %{y:,.0f}<extra></extra>"))
    for g, s in (("Geschlecht - Total", med), ("Frauen", fem), ("Männer", mal)):
        f1.add_trace(go.Scatter(x=s.index, y=s.values, mode="lines+markers", name=G_NAME[g] + (" (Median)" if g == "Geschlecht - Total" else ""), line=dict(color=G_COLOR[g], width=2.6 if g == "Geschlecht - Total" else 2),
                                hovertemplate=f"{G_NAME[g]} %{{x}}: CHF %{{y:,.0f}}<extra></extra>"))
    f1.update_xaxes(tickformat="d", dtick=2)
    f1.update_yaxes(tickformat=",", rangemode="tozero")
    real = L.real_median(last)
    f2 = _fig(f"Nominal und real (in Preisen {last}), Medianlohn alle")
    f2.add_trace(go.Scatter(x=med.index, y=med.values, mode="lines+markers", name="nominal", line=dict(color=LI_COLOR, width=2.6), hovertemplate="%{x}: CHF %{y:,.0f} nominal<extra></extra>"))
    if not real.empty:
        f2.add_trace(go.Scatter(x=real.index, y=real.values, mode="lines+markers", name="real (Näherung, CH-Konsumentenpreise)", line=dict(color=FL_GOLD, width=2.2, dash="dot"),
                                hovertemplate="%{x}: CHF %{y:,.0f} real<extra></extra>"))
    f2.update_xaxes(tickformat="d", dtick=2)
    f2.update_yaxes(tickformat=",", rangemode="tozero")
    out.append(_row(_card(_graph(f1, 380)), _card(_graph(f2, 380))))
    since = (med[last] / med[med.index.min()] - 1) * 100
    real_txt = ""
    if not real.empty:
        real_txt = f" Real (Näherung): {(real[last] / real[real.index.min()] - 1) * 100:+.0f} % seit {int(real.index.min())}."
    out.append(_note(f"Nominal stieg der Medianlohn von {int(med.index.min())} bis {last} um {since:.0f} % (von CHF {_num(med.iloc[0])} auf CHF {_num(med[last])})." + real_txt +
                     " Die reale Reihe verwendet den Schweizer Konsumentenpreisindex als Deflator (für Liechtenstein liegt kein eigener Index vor) und ist deshalb nur eine Näherung.",
                     "fa-triangle-exclamation", FL_GOLD))
    out.append(_src("branche", "wohnsitz", L.CPI_KEY, extra="Preise: Weltbank FP.CPI.TOTL (Schweiz)"))

    # ── 2 Lohnunterschied ────────────────────────────────────────────────────
    out.append(_section("2 · Lohnunterschied Frauen/Männer", "Unbereinigter Unterschied der Medianlöhne in % des Männerlohns. Er enthält Unterschiede in Branche, Alter, Position und Arbeitszeit."))
    f3 = _fig("Lohnunterschied (Median Frauen gegenüber Männern, %)")
    for lab, vz, col, dash in (("alle Beschäftigten", "Vollzeit/Teilzeit - Total", LI_COLOR, "solid"), ("Vollzeit", "Vollzeit", FL_BLUE, "dot"), ("Teilzeit", "Teilzeit", FL_GOLD, "dot")):
        s = L.gap_series(vz)
        if not s.empty:
            f3.add_trace(go.Scatter(x=s.index, y=s.values, mode="lines+markers", name=lab, line=dict(color=col, width=2.6 if dash == "solid" else 2, dash=dash),
                                    hovertemplate=f"{lab} %{{x}}: %{{y:.1f}} %<extra></extra>"))
    f3.update_xaxes(tickformat="d", dtick=2)
    f3.update_yaxes(ticksuffix=" %", rangemode="tozero")
    vz = L.tidy("vztz")
    f4 = _fig(f"Medianlohn nach Beschäftigungsumfang und Geschlecht, {year} (CHF)")
    if not vz.empty:
        for g in ("Frauen", "Männer"):
            d = L.sel(vz, Jahr=year, Geschlecht=g, Kennzahl="Median")
            d = d.set_index("Vollzeit/Teilzeit")["Wert"].reindex(["Vollzeit/Teilzeit - Total", "Vollzeit", "Teilzeit"])
            f4.add_trace(go.Bar(x=["alle", "Vollzeit", "Teilzeit"], y=d.values, name=g, marker_color=G_COLOR[g], hovertemplate=f"{g} %{{x}}: CHF %{{y:,.0f}}<extra></extra>"))
        f4.update_layout(barmode="group")
        f4.update_yaxes(tickformat=",")
    out.append(_row(_card(_graph(f3)), _card(_graph(f4))))
    out.append(_note("Teilzeitlöhne sind auf 100 % hochgerechnet. Der Unterschied ist bei Vollzeitbeschäftigten und Teilzeitbeschäftigten verschieden gross; "
                     "das Amt weist darauf hin, dass teilzeitbeschäftigte Frauen relativ gesehen mehr verdienen als vollzeitbeschäftigte. Keine Aussage über Ursachen.", "fa-circle-info", ACCENT))
    out.append(_src("vztz", "branche"))

    # ── 3 Branchen ───────────────────────────────────────────────────────────
    out.append(_section("3 · Wirtschaftszweige", f"Medianlohn und 1.–3. Quartil je Wirtschaftszweig, {year}, Gruppe «{gname}». Lücken: weniger als 50 Beobachtungen."))
    b = br[(br["Jahr"] == year) & (br["Geschlecht"] == geschl)]
    piv = b.pivot_table(index="Wirtschaftszweig", columns="Kennzahl", values="Wert", aggfunc="first")
    piv = piv[piv.index.map(lambda x: str(x).startswith("..."))].dropna(subset=["Median"]).sort_values("Median")
    if piv.empty:
        out.append(_empty("Keine Werte für diese Auswahl."))
    else:
        labels = [L.clean(i) for i in piv.index]
        f5 = _fig(f"Medianlohn nach Wirtschaftszweig, {year}, {gname} (CHF je Monat)", legend=False, height=max(420, 22 * len(piv) + 120))
        f5.add_trace(go.Bar(x=piv["Median"], y=labels, orientation="h", marker_color=G_COLOR[geschl] if geschl != "Geschlecht - Total" else FL_BLUE,
                            error_x=dict(type="data", symmetric=False, array=(piv["3. Quartil"] - piv["Median"]).values, arrayminus=(piv["Median"] - piv["1. Quartil"]).values,
                                         color="#8B949E", thickness=1.2, width=3),
                            customdata=piv[["1. Quartil", "3. Quartil"]].values,
                            hovertemplate="%{y}<br>Median CHF %{x:,.0f}<br>1.–3. Quartil: %{customdata[0]:,.0f}–%{customdata[1]:,.0f}<extra></extra>"))
        tot = b[(b["Wirtschaftszweig"] == "Wirtschaftszweig - Total") & (b["Kennzahl"] == "Median")]["Wert"]
        if not tot.empty and pd.notna(tot.iloc[0]):
            f5.add_vline(x=float(tot.iloc[0]), line_dash="dot", line_color=FL_GOLD, annotation_text=f"alle Zweige: {_num(tot.iloc[0])}", annotation_font_color=FL_GOLD, annotation_position="top")
        f5.update_layout(margin=dict(l=250, r=20))
        f5.update_xaxes(tickformat=",")
        out.append(_card(_graph(f5, max(420, 22 * len(piv) + 120))))
    out.append(_note("Die Wirtschaftszweige folgen der NOGA-Klassifikation in der Gruppierung des Amts. Die Löhne hängen von Qualifikation, Alter und Geschlechterzusammensetzung der "
                     "Branche ab; Unterschiede zwischen Branchen sind kein Mass für die «Wertigkeit» der Arbeit.", "fa-circle-info", ACCENT))
    out.append(_src("branche"))

    # ── 4 Alter und Unternehmensgrösse ───────────────────────────────────────
    out.append(_section("4 · Alter und Unternehmensgrösse", f"Medianlohn {year}."))
    al = L.tidy("alter")
    f6 = _fig(f"Medianlohn nach Altersklasse, {year} (CHF je Monat)")
    if not al.empty:
        for g in ("Geschlecht - Total", "Frauen", "Männer"):
            d = L.sel(al, Jahr=year, Geschlecht=g, Kennzahl="Median").set_index("Alter")["Wert"].reindex(AGE_ORDER)
            f6.add_trace(go.Scatter(x=[a.replace(" Jahre", "") for a in AGE_ORDER], y=d.values, mode="lines+markers", name=G_NAME[g], line=dict(color=G_COLOR[g], width=2.6 if g == "Geschlecht - Total" else 2),
                                    hovertemplate=f"{G_NAME[g]} %{{x}}: CHF %{{y:,.0f}}<extra></extra>"))
        f6.update_yaxes(tickformat=",", rangemode="tozero")
    gr = L.tidy("gross")
    f7 = _fig(f"Medianlohn nach Unternehmensgrösse, {year}, {gname} (CHF)", legend=False)
    if not gr.empty:
        d = L.sel(gr, Jahr=year, Geschlecht=geschl, Kennzahl="Median").set_index("Unternehmensgrösse")["Wert"].reindex(["1 - 9", "10 - 49", "50 - 249", "250+"])
        f7.add_trace(go.Bar(x=["1–9", "10–49", "50–249", "250+"], y=d.values, marker_color=FL_BLUE, hovertemplate="%{x} Beschäftigte: CHF %{y:,.0f}<extra></extra>"))
        f7.update_yaxes(tickformat=",", rangemode="tozero")
        f7.update_xaxes(title_text="Beschäftigte im Unternehmen")
    out.append(_row(_card(_graph(f6)), _card(_graph(f7))))
    out.append(_note("Altersklassen sind Querschnitte: Die Kurve zeigt Beschäftigte verschiedenen Alters im selben Jahr, nicht die Lohnlaufbahn einzelner Personen. "
                     "Lohn und Dienstalter hängen eng zusammen; das Dienstalter wird nicht ausgewiesen.", "fa-circle-info", ACCENT))
    out.append(_src("alter", "gross"))

    # ── 5 Wohnsitz, Staatsbürgerschaft, Aufenthaltsstatus, Wohnort ───────────
    out.append(_section("5 · Wohnsitz, Staatsbürgerschaft und Aufenthaltsstatus", f"Gruppe «{gname}». Rohvergleiche ohne Berücksichtigung von Branche, Alter und Position."))
    ws = L.tidy("wohnsitz")
    f8 = _fig(f"Medianlohn nach Wohnsitz der Beschäftigten, {gname} (CHF)")
    if not ws.empty:
        for lab, col in (("Erwerbstätige Einwohner", FL_BLUE), ("Zupendler aus dem Ausland", FL_GOLD)):
            s = L.series(L.sel(ws, Wohnsitz=lab, Geschlecht=geschl, Kennzahl="Median"))
            f8.add_trace(go.Scatter(x=s.index, y=s.values, mode="lines+markers", name=lab.replace("Erwerbstätige Einwohner", "Einwohner Liechtensteins"), line=dict(color=col, width=2.4),
                                    hovertemplate=f"{lab} %{{x}}: CHF %{{y:,.0f}}<extra></extra>"))
        f8.update_xaxes(tickformat="d", dtick=2)
        f8.update_yaxes(tickformat=",", rangemode="tozero")
    st = L.tidy("staat")
    f9 = _fig(f"Medianlohn nach Staatsbürgerschaft, {gname} (CHF)")
    if not st.empty:
        for lab, col in (("Liechtensteiner", FL_BLUE), ("Ausländer", FL_RED)):
            s = L.series(L.sel(st, **{"Staatsbürgerschaft": lab, "Geschlecht": geschl, "Kennzahl": "Median"}))
            f9.add_trace(go.Scatter(x=s.index, y=s.values, mode="lines+markers", name=lab, line=dict(color=col, width=2.4), hovertemplate=f"{lab} %{{x}}: CHF %{{y:,.0f}}<extra></extra>"))
        f9.update_xaxes(tickformat="d", dtick=2)
        f9.update_yaxes(tickformat=",", rangemode="tozero")
    out.append(_row(_card(_graph(f8)), _card(_graph(f9))))
    sts = L.tidy("status")
    f10 = _fig(f"Medianlohn nach Aufenthaltsstatus, {year}, {gname} (CHF)", legend=False)
    if not sts.empty:
        d = L.sel(sts, Jahr=year, Geschlecht=geschl, Kennzahl="Median").set_index("Aufenthaltsstatus")["Wert"].reindex(STATUS_ORDER)
        f10.add_trace(go.Bar(x=[s.replace("Im Land wohnhafte Landesbürger", "Landesbürger (im Land wohnhaft)") for s in STATUS_ORDER], y=d.values, marker_color=FL_BLUE,
                             hovertemplate="%{x}: CHF %{y:,.0f}<extra></extra>"))
        f10.update_yaxes(tickformat=",", rangemode="tozero")
    wo = L.tidy("wohnort")
    f11 = _fig(f"Medianlohn nach Wohnort der Beschäftigten, {year}, {gname} (CHF)", legend=False)
    if not wo.empty:
        d = L.sel(wo, Jahr=year, Geschlecht=geschl, Kennzahl="Median").dropna(subset=["Wert"])
        d = d[d["Wohnort"] != "Wohnort - Total"].sort_values("Wert", ascending=False)
        f11.add_trace(go.Bar(x=d["Wohnort"], y=d["Wert"], marker_color=[FL_GOLD if w == "Ausland" else FL_BLUE for w in d["Wohnort"]], hovertemplate="%{x}: CHF %{y:,.0f}<extra></extra>"))
        f11.update_yaxes(tickformat=",", rangemode="tozero")
    out.append(_row(_card(_graph(f10)), _card(_graph(f11))))
    out.append(_note("Staatsbürgerschaft und Wohnsitz sind keine Merkmale des Lohns selbst: Die Gruppen unterscheiden sich in Alter, Branche, Dienstalter und Funktion (die Lohnstatistik enthält "
                     "keine Angaben zu Ausbildung oder Funktion). Eingebürgerte zählen als Liechtensteiner. "
                     "Kein Urteil über Personengruppen, kein Rückschluss auf Einzelne.", "fa-triangle-exclamation", FL_GOLD))
    out.append(_src("wohnsitz", "staat", "status", "wohnort"))

    # ── 6 Verteilung ─────────────────────────────────────────────────────────
    out.append(_section("6 · Lohnverteilung", f"Anteil der Arbeitsverhältnisse je Lohnklasse (effektive Bruttomonatslöhne, nicht auf Vollzeit hochgerechnet), {year}."))
    vt = L.tidy("verteilung")
    f12 = _fig(f"Häufigkeitsverteilung der effektiven Bruttomonatslöhne, {year} (% der Arbeitsverhältnisse)")
    if not vt.empty:
        classes = [c for c in vt["Lohnhöhenklasse"].unique() if "Total" not in c]
        for g in ("Frauen", "Männer"):
            d = L.sel(vt, Jahr=year, Geschlecht=g).set_index("Lohnhöhenklasse")["Wert"].reindex(classes)
            f12.add_trace(go.Bar(x=[c.replace(" CHF", "").replace(" - ", "–") for c in classes], y=d.values, name=g, marker_color=G_COLOR[g], opacity=0.85,
                                 hovertemplate=f"{g} %{{x}}: %{{y:.1f}} %<extra></extra>"))
        f12.update_layout(barmode="group")
        f12.update_yaxes(ticksuffix=" %")
        f12.update_xaxes(tickangle=-60, title_text="Bruttomonatslohn in CHF")
    out.append(_card(_graph(f12, 400)))
    out.append(_note("Anteile je Geschlecht (Frauen und Männer je 100 %). Teilzeitbeschäftigte erscheinen mit ihrem tatsächlichen, niedrigeren Monatslohn; deshalb unterscheidet sich die "
                     "Verteilung von den auf Vollzeit hochgerechneten Medianlöhnen. Die letzte Klasse «20000+» fasst alle höheren Löhne zusammen.", "fa-circle-info", ACCENT))
    out.append(_src("verteilung"))

    # ── 7 Schweiz ────────────────────────────────────────────────────────────
    out.append(_section("7 · Einordnung: Schweiz", "Zentralwert des monatlichen Bruttolohns, BFS-Lohnstrukturerhebung (Schweiz, alle Branchen), neben dem liechtensteinischen Median."))
    ch = L.ch_median()
    if ch.empty:
        out.append(_empty("Schweizer Vergleichswerte noch nicht geladen."))
    else:
        f13 = _fig("Medianlohn Liechtenstein und Zentralwert Schweiz (CHF je Monat)")
        for g in ("Geschlecht - Total", "Frauen", "Männer"):
            c = L.ch_median(g)
            li = L.median_series(g)
            f13.add_trace(go.Scatter(x=li.index, y=li.values, mode="lines+markers", name=f"Liechtenstein {G_NAME[g]}", line=dict(color=G_COLOR[g], width=2.6 if g == "Geschlecht - Total" else 1.8),
                                     hovertemplate=f"Liechtenstein {G_NAME[g]} %{{x}}: CHF %{{y:,.0f}}<extra></extra>"))
            f13.add_trace(go.Scatter(x=c.index, y=c.values, mode="lines+markers", name=f"Schweiz {G_NAME[g]}", line=dict(color=G_COLOR[g], width=2, dash="dash"),
                                     hovertemplate=f"Schweiz {G_NAME[g]} %{{x}}: CHF %{{y:,.0f}}<extra></extra>"))
        f13.update_xaxes(tickformat="d", dtick=2, range=[2011, 2025])
        f13.update_yaxes(tickformat=",", rangemode="tozero")
        gap_ch = ((L.ch_median("Männer") - L.ch_median("Frauen")) / L.ch_median("Männer") * 100).dropna()
        f14 = _fig("Lohnunterschied Frauen/Männer: Liechtenstein und Schweiz (%, unbereinigt)")
        f14.add_trace(go.Scatter(x=gap.index, y=gap.values, mode="lines+markers", name="Liechtenstein", line=dict(color=LI_COLOR, width=2.6), hovertemplate="Liechtenstein %{x}: %{y:.1f} %<extra></extra>"))
        f14.add_trace(go.Scatter(x=gap_ch.index, y=gap_ch.values, mode="lines+markers", name="Schweiz", line=dict(color=FL_RED, width=2, dash="dash"), hovertemplate="Schweiz %{x}: %{y:.1f} %<extra></extra>"))
        f14.update_xaxes(tickformat="d", dtick=2, range=[2011, 2025])
        f14.update_yaxes(ticksuffix=" %", rangemode="tozero")
        out.append(_row(_card(_graph(f13, 400)), _card(_graph(f14, 400))))
        out.append(_note("Eingeschränkt vergleichbar: Das Amt für Statistik nennt die beiden Definitionen grundsätzlich vergleichbar, sie unterscheiden sich aber. Liechtenstein: Jahreslohnmeldungen "
                         "der Arbeitgebenden (Verwaltungsdaten), durch Beschäftigungsmonate geteilt und auf 100 % hochgerechnet, Beschäftigte in Liechtenstein inkl. Zupendler. Schweiz: "
                         "Stichprobenerhebung, Lohn des Monats Oktober (inkl. 1/12 der Sonderzahlungen) auf eine Standardarbeitszeit (40 Std./Woche) umgerechnet, Beschäftigte in der Schweiz. Die Wirtschaftsstruktur und das "
                         "Preisniveau beider Länder sind verschieden; die Zahlen dienen der Einordnung, nicht als exakter Vergleich.", "fa-triangle-exclamation", FL_GOLD))
        out.append(_src("branche", L.CH_KEY, bfs=True, extra="Schweiz: Zentralwert, Berichtsjahre 2012–2024 alle 2 Jahre"))

    out.append(html.Div(style={"height": "10px"}))
    out.append(_missing())
    out.append(_source(("Methodik und Qualität der Lohnstatistik 2024 (Amt für Statistik)", L.METH_URL), ("Publikation «Löhne 2024» (17.04.2026)", L.PUB_URL)))
    return html.Div(out)
