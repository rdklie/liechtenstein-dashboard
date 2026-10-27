"""
tab_factbook.py — Tab «World Factbook (Archiv)»
===============================================
Liechtenstein in allen Ausgaben des CIA World Factbook 1990–2025 (eingestellt am 4. Feb. 2026).
Daten: einmaliger Import (factbook_import.py) aus dem Archiv-Datenbestand auf GitHub
(MilkMp/CIA-World-Factbooks-Archive-1990-2025); Rohdateien unter <Datenordner>/archive/factbook/.
Das Factbook ist gemeinfrei (US-Regierungspublikation). Kein laufender Abruf, keine Aktualisierung.
"""

import dash_bootstrap_components as dbc
import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, callback, dcc, html

from db import read_factbook_fields, read_factbook_values
from ui import FL_BLUE, FL_RED, FL_GOLD, ACCENT, GREEN, MUTED, TEXT, BORDER, _card, _kpi, _styled, _empty

SOURCE_URL = "https://github.com/MilkMp/CIA-World-Factbooks-Archive-1990-2025"
FACTBOOK_URL = "https://www.cia.gov/the-world-factbook/"
MODES = [{"label": "Nach Bezugsjahr (Zeitreihe)", "value": "ref"},
         {"label": "Nach Ausgabe (wie damals genannt)", "value": "edition"}]
DEFAULT_MODE = "ref"


def sidebar_section() -> html.Div:
    return html.Div(id="filter-factbook", children=[
        html.Div([
            html.Label("Zeitachse", className="filter-label"),
            dcc.RadioItems(id="factbook-mode", options=MODES, value=DEFAULT_MODE,
                           className="fl-checklist", labelClassName="checklist-label"),
            html.Small("Bezugsjahr: Jahr, auf das sich der Wert bezieht (neueste Ausgabe gewinnt). "
                       "Ausgabe: Jahr der Factbook-Ausgabe.", style={"color": MUTED, "fontSize": "0.7rem"}),
        ], className="filter-section"),
    ])


def _series(vals: pd.DataFrame, indicator: str, mode: str, scale: float = 1.0) -> pd.DataFrame:
    """Spalten x, y — je Bezugsjahr den Wert der jüngsten Ausgabe bzw. je Ausgabe den jüngsten Bezugswert."""
    d = vals[vals["indicator"] == indicator]
    if d.empty:
        return d.assign(x=[], y=[])
    if mode == "edition":
        d = d.sort_values(["year", "ref_year"]).groupby("year").tail(1)
        return pd.DataFrame({"x": d["year"].astype(int), "y": d["value"] / scale})
    d = d.sort_values(["ref_year", "year"]).groupby("ref_year").tail(1)
    return pd.DataFrame({"x": d["ref_year"].astype(int), "y": d["value"] / scale}).sort_values("x")


def _fig(vals, mode, title, traces, yaxis="", suffix="", fmt=",.0f"):
    """traces: [(Indikator, Name, Farbe, Skalierung, dash)]"""
    fig = go.Figure()
    for ind, name, color, scale, dash in traces:
        s = _series(vals, ind, mode, scale)
        if s.empty:
            continue
        fig.add_trace(go.Scatter(x=s["x"], y=s["y"], mode="lines+markers", name=name,
                                 line=dict(color=color, width=2.5, dash=dash or "solid"), marker=dict(size=5),
                                 hovertemplate=f"{name} %{{x}}: %{{y:{fmt}}}{suffix}<extra></extra>"))
    if not fig.data:
        return _empty("Keine Daten.")
    _styled(fig, title, legend=len(fig.data) > 1)
    fig.update_layout(yaxis_title=yaxis, height=340)
    fig.update_xaxes(tickformat="d")
    return _card(dcc.Graph(figure=fig, config={"displayModeBar": False}))


def _latest(vals: pd.DataFrame, indicator: str):
    d = vals[vals["indicator"] == indicator].sort_values(["year", "ref_year"])
    return d.iloc[-1] if not d.empty else None


def render_factbook(data: dict) -> html.Div:
    mode = data.get("factbook_mode") or DEFAULT_MODE
    vals = read_factbook_values()
    if vals.empty:
        return html.Div([
            html.H4("World Factbook (Archiv) – Liechtenstein", className="section-title"),
            _empty("Das Archiv wurde noch nicht importiert (factbook_import.py)."),
        ])
    editions = sorted(vals["year"].unique())

    def kpi(icon, label, ind, fmt, color, unit_fmt=None):
        r = _latest(vals, ind)
        if r is None:
            return None
        v = r["value"]
        text = fmt(v)
        return dbc.Col(_kpi(icon, f"{label} ({int(r['ref_year'])})", text, color, f"Ausgabe {int(r['year'])}"),
                       md=3, sm=6, className="mb-3")

    kpis = [k for k in (
        kpi("fa-users", "Bevölkerung", "population", lambda v: f"{v:,.0f}".replace(",", "’"), FL_BLUE),
        kpi("fa-ruler-combined", "Fläche", "area_total", lambda v: f"{v:,.0f} km²".replace(",", "’"), FL_RED),
        kpi("fa-coins", "BIP (nominal)", "gdp_nominal", lambda v: f"{v / 1e9:.2f}".replace(".", ",") + " Mrd. USD", FL_GOLD),
        kpi("fa-heart-pulse", "Lebenserwartung", "life_expectancy", lambda v: f"{v:.1f} Jahre".replace(".", ","), GREEN),
    ) if k is not None]

    notice = dbc.Alert([
        html.I(className="fas fa-box-archive", style={"marginRight": "8px"}),
        html.B("Archiv – abgeschlossen, wird nicht mehr aktualisiert (nichts nachzuführen). "),
        f"Das CIA World Factbook wurde am 4. Februar 2026 eingestellt; die letzte Ausgabe ist 2025 "
        f"({len(editions)} Ausgaben, {editions[0]}–{editions[-1]}). Werte stehen so, wie die CIA sie veröffentlicht hat: "
        "Bezugsjahre liegen oft Jahre vor der Ausgabe, und Definitionen wechseln (ab 2021 «Real GDP» in Preisen von 2015). "
        "Handelsdaten ohne Handel mit der Schweiz.",
    ], color="secondary", style={"fontSize": "0.8rem", "background": "#161B22", "border": f"1px solid {BORDER}", "color": MUTED})

    charts = [
        _fig(vals, mode, "Bevölkerung", [("population", "Bevölkerung", FL_BLUE, 1, None)], "Personen"),
        _fig(vals, mode, "Geburten-, Sterbe- und Wanderungsrate (je 1000 Einw.)",
             [("birth_rate", "Geburtenrate", GREEN, 1, None), ("death_rate", "Sterberate", FL_RED, 1, None),
              ("net_migration", "Nettomigration", ACCENT, 1, "dot")], "je 1000 Einwohner", fmt=".1f"),
        _fig(vals, mode, "Lebenserwartung & Medianalter (Jahre)",
             [("life_expectancy", "Lebenserwartung", GREEN, 1, None), ("median_age", "Medianalter", FL_GOLD, 1, None)],
             "Jahre", fmt=".1f"),
        _fig(vals, mode, "Fertilität & Säuglingssterblichkeit",
             [("fertility_rate", "Kinder je Frau", FL_BLUE, 1, None), ("infant_mortality", "Säuglingssterblichkeit (je 1000)", FL_RED, 1, None)],
             "", fmt=".2f"),
        _fig(vals, mode, "BIP (Mrd. USD)",
             [("gdp_nominal", "nominal (Wechselkurs)", FL_GOLD, 1e9, None), ("gdp_ppp", "Kaufkraftparität", FL_BLUE, 1e9, None),
              ("gdp_ppp_real", "Kaufkraftparität, real (Preise 2015)", ACCENT, 1e9, "dot")], "Mrd. USD", fmt=".2f"),
        _fig(vals, mode, "BIP pro Kopf, Kaufkraftparität (USD)",
             [("gdp_per_capita_ppp", "Kaufkraftparität", FL_BLUE, 1, None),
              ("gdp_per_capita_ppp_real", "real (Preise 2015)", ACCENT, 1, "dot")], "USD"),
        _fig(vals, mode, "Inflation, Arbeitslosigkeit & Wachstum (%)",
             [("inflation", "Inflation", FL_RED, 1, None), ("unemployment", "Arbeitslosigkeit", FL_BLUE, 1, None),
              ("gdp_growth", "reales BIP-Wachstum", GREEN, 1, "dot")], "%", suffix=" %", fmt=".1f"),
        _fig(vals, mode, "Exporte & Importe (Mrd. USD, ohne Handel mit der Schweiz)",
             [("exports", "Exporte", GREEN, 1e9, None), ("imports", "Importe", FL_RED, 1e9, None)], "Mrd. USD", fmt=".2f"),
        _fig(vals, mode, "Erwerbspersonen & Internetnutzer",
             [("labor_force", "Erwerbspersonen", FL_BLUE, 1, None), ("internet_users", "Internetnutzer", ACCENT, 1, None)], "Personen"),
    ]
    rows = [dbc.Row([dbc.Col(c, md=6, className="mb-3") for c in charts[i:i + 2]], className="g-3")
            for i in range(0, len(charts), 2)]

    fields = read_factbook_fields()
    counts = fields.groupby("field")["year"].nunique().sort_values(ascending=False)
    options = [{"label": f"{f} ({n} Ausgaben)", "value": f} for f, n in counts.items()]
    history = _card([
        html.H6("Text-Chronik: Was stand wann im Factbook?", style={"color": TEXT}),
        html.P("Feld wählen — gezeigt werden nur die Ausgaben, in denen sich der Text geändert hat.",
               style={"color": MUTED, "fontSize": "0.8rem"}),
        dcc.Dropdown(id="fb-field", options=options,
                     value="Government type" if "Government type" in counts.index else options[0]["value"],
                     clearable=False, searchable=True, className="fl-dropdown"),
        html.Div(id="fb-history", style={"marginTop": "12px"}),
    ])

    src = html.Div([
        html.I(className="fas fa-database", style={"marginRight": "6px", "color": MUTED}),
        html.Span("Quelle: ", style={"color": MUTED}),
        html.A("CIA World Factbook", href=FACTBOOK_URL, target="_blank", rel="noopener noreferrer", className="source-link"),
        html.Span(" (gemeinfrei, US-Regierungspublikation) · Archiv-Datenbestand: ", style={"color": MUTED}),
        html.A("MilkMp/CIA-World-Factbooks-Archive-1990-2025", href=SOURCE_URL, target="_blank",
               rel="noopener noreferrer", className="source-link"),
        html.Span(" (MIT) · einmaliger Import, kein laufender Abruf.", style={"color": MUTED}),
    ], className="source-bar")

    return html.Div([
        html.H4("World Factbook (Archiv) – Liechtenstein", className="section-title"),
        dbc.Row(kpis, className="g-3") if kpis else None,
        notice, html.Div(style={"height": "12px"}),
        *rows, history, html.Div(style={"height": "12px"}), src,
    ])


@callback(Output("fb-history", "children"), Input("fb-field", "value"))
def _history(field):
    if not field:
        return None
    d = read_factbook_fields(field)
    if d.empty:
        return _empty("Keine Daten.")
    d = d.sort_values("year")
    d = d[d["content"].shift() != d["content"]]            # nur Änderungen
    body = [html.Tr([html.Td(str(int(r.year)), style={"whiteSpace": "nowrap"}), html.Td(r.content)])
            for r in d.itertuples()]
    return html.Div(html.Table([html.Thead(html.Tr([html.Th("Ausgabe"), html.Th("Text")])), html.Tbody(body)],
                               className="od-table"), style={"maxHeight": "420px", "overflowY": "auto"})
