"""
tab_imf.py — Tab «IWF (WEO)»
============================
IWF-Indikatoren für Liechtenstein (World Economic Outlook, DataMapper API), vom Worker höchstens
wöchentlich nach SQLite gespiegelt. Liechtenstein ist kein IWF-Mitglied: die Werte sind IWF-
Schätzungen/-Projektionen. Quelle: International Monetary Fund, World Economic Outlook.
Lizenz: IWF-Datenbedingungen (Quellenangabe, nicht-kommerzielle Nutzung).
"""

from datetime import datetime

import dash_bootstrap_components as dbc
import pandas as pd
import plotly.graph_objects as go
from dash import dcc, html

from db import read_imf, read_imf_info
from imf import INDICATORS
from ui import FL_BLUE, FL_RED, FL_GOLD, ACCENT, GREEN, MUTED, BORDER, _card, _kpi, _styled, _empty

TERMS_URL = "https://www.imf.org/en/About/Copyright-and-Terms"
DATAMAPPER_URL = "https://www.imf.org/external/datamapper"


def _load(code: str) -> pd.DataFrame:
    return read_imf(code)


def _fig(title: str, traces: list[tuple[str, str, str]], unit: str, fmt: str = ",.1f", bars: bool = False):
    """traces: [(Indikator-Code, Name, Farbe)] — Projektionen (ab dem Ausgabejahr) gestrichelt bzw. heller."""
    cut = datetime.utcnow().year           # WEO-Ausgabejahr: ab hier Projektionen
    fig = go.Figure()
    for code, name, color in traces:
        d = _load(code)
        if d.empty:
            continue
        d = d.assign(year=d["year"].astype(int))
        if bars:
            fig.add_trace(go.Bar(x=d["year"], y=d["value"], name=name,
                                 marker_color=[color if y < cut else "rgba(139,148,158,0.55)" for y in d["year"]],
                                 hovertemplate=f"{name} %{{x}}: %{{y:{fmt}}} {unit}<extra></extra>"))
            continue
        hist, proj = d[d["year"] < cut], d[d["year"] >= cut - 1]          # eine Überlappung für lückenlose Linie
        fig.add_trace(go.Scatter(x=hist["year"], y=hist["value"], mode="lines+markers", name=name,
                                 line=dict(color=color, width=2.5), marker=dict(size=5),
                                 hovertemplate=f"{name} %{{x}}: %{{y:{fmt}}} {unit}<extra></extra>"))
        fig.add_trace(go.Scatter(x=proj["year"], y=proj["value"], mode="lines", name=f"{name} (Projektion)",
                                 line=dict(color=color, width=2, dash="dot"), showlegend=False,
                                 hovertemplate=f"{name} %{{x}} (Projektion): %{{y:{fmt}}} {unit}<extra></extra>"))
    if not fig.data:
        return _empty("Keine Daten.")
    _styled(fig, title, legend=len(traces) > 1)
    fig.update_layout(yaxis_title=unit, height=330)
    fig.update_xaxes(tickformat="d")
    fig.add_vrect(x0=cut - 0.5, x1=max(d["year"].max() for d in [_load(c) for c, _, _ in traces] if not d.empty) + 0.5,
                  fillcolor="rgba(139,148,158,0.08)", line_width=0,
                  annotation_text="Projektion", annotation_position="top left", annotation_font_color=MUTED)
    return _card(dcc.Graph(figure=fig, config={"displayModeBar": False}))


def render_imf() -> html.Div:
    gdp = _load("NGDPD")
    if gdp.empty:
        return html.Div([
            html.H4("IWF – World Economic Outlook", className="section-title"),
            _empty("Noch keine IWF-Daten in der Datenbank — der tägliche Datenabruf holt sie (höchstens wöchentlich)."),
        ])
    source, fetched = read_imf_info()
    cut = datetime.utcnow().year

    def last_actual(code):
        d = _load(code)
        d = d[d["year"] < cut]
        return d.iloc[-1] if not d.empty else None

    kpis = []
    for code, icon, label, color, fmt in (
        ("NGDPD", "fa-coins", "BIP", FL_GOLD, lambda v: f"{v:.1f}".replace(".", ",") + " Mrd. USD"),
        ("NGDPDPC", "fa-user-tag", "BIP pro Kopf", FL_BLUE, lambda v: f"USD {v:,.0f}".replace(",", "’")),
        ("PCPIPCH", "fa-arrow-trend-up", "Inflation", FL_RED, lambda v: f"{v:.1f} %".replace(".", ",")),
        ("LUR", "fa-briefcase", "Arbeitslosenquote", GREEN, lambda v: f"{v:.1f} %".replace(".", ",")),
    ):
        r = last_actual(code)
        if r is not None:
            kpis.append(dbc.Col(_kpi(icon, f"{label} ({int(r['year'])})", fmt(r["value"]), color, "IWF-Schätzung"),
                                md=3, sm=6, className="mb-3"))

    notice = dbc.Alert([
        html.I(className="fas fa-circle-info", style={"marginRight": "8px"}),
        html.B("Liechtenstein ist kein IWF-Mitglied. "),
        "Der IWF führt es im World Economic Outlook mit eigenen Schätzungen und Projektionen (grau hinterlegt: ab "
        f"{cut}); es gibt keinen Länderbericht und keine Meldungen aus Liechtenstein. Von 132 DataMapper-Indikatoren liefern "
        f"{len(INDICATORS)} Werte für Liechtenstein. Die Werte können von den amtlichen Zahlen des Amts für Statistik "
        "und der Weltbank abweichen.",
    ], color="secondary", style={"fontSize": "0.8rem", "background": "#161B22", "border": f"1px solid {BORDER}", "color": MUTED})

    charts = [
        _fig("BIP, laufende Preise (Mrd. USD)", [("NGDPD", "BIP", FL_GOLD)], "Mrd. USD", ",.2f"),
        _fig("BIP pro Kopf (USD / int. Dollar)", [("NGDPDPC", "laufende Preise", FL_BLUE), ("PPPPC", "Kaufkraftparität", ACCENT)], "", ",.0f"),
        _fig("Reales BIP-Wachstum (%)", [("NGDP_RPCH", "Wachstum", GREEN)], "%", ".1f", bars=True),
        _fig("Inflation (%)", [("PCPIPCH", "Jahresdurchschnitt", FL_RED), ("PCPIEPCH", "Jahresende", FL_GOLD)], "%", ".1f"),
        _fig("Arbeitslosenquote (%)", [("LUR", "Arbeitslosenquote", FL_BLUE)], "%", ".1f"),
        _fig("Leistungsbilanzsaldo (% des BIP)", [("BCA_NGDPD", "Leistungsbilanz", ACCENT)], "% des BIP", ".1f", bars=True),
        _fig("Staatshaushalt (% des BIP)", [("GGXCNL_NGDP", "Finanzierungssaldo", FL_GOLD), ("GGXWDG_NGDP", "Bruttoverschuldung", FL_RED)], "% des BIP", ".1f"),
        _fig("Bevölkerung (Mio.)", [("LP", "Bevölkerung", FL_BLUE)], "Mio.", ".3f"),
    ]
    rows = [dbc.Row([dbc.Col(c, md=6, className="mb-3") for c in charts[i:i + 2]], className="g-3")
            for i in range(0, len(charts), 2)]

    stand = f" · Stand der Daten: {fetched:%d.%m.%Y}" if fetched else ""
    src = html.Div([
        html.I(className="fas fa-database", style={"marginRight": "6px", "color": MUTED}),
        html.Span("Quelle: ", style={"color": MUTED}),
        html.A("International Monetary Fund, " + (source or "World Economic Outlook"), href=DATAMAPPER_URL, target="_blank",
               rel="noopener noreferrer", className="source-link"),
        html.Span(" · Lizenz: ", style={"color": MUTED}),
        html.A("IWF-Datenbedingungen", href=TERMS_URL, target="_blank", rel="noopener noreferrer", className="source-link"),
        html.Span(f" (Quellenangabe, nicht-kommerziell){stand}", style={"color": MUTED}),
    ], className="source-bar")

    return html.Div([
        html.H4("IWF – World Economic Outlook (Liechtenstein)", className="section-title"),
        dbc.Row(kpis, className="g-3") if kpis else None, notice, html.Div(style={"height": "12px"}),
        *rows, src,
    ])
