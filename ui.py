"""
ui.py — gemeinsame Farben und UI-Helfer (Diagramm-Stil, Karten, KPI, Quellenzeile)
==================================================================================
Von app.py und den Tab-Modulen (tab_wohnen.py, tab_opendata.py) genutzt.
"""

import plotly.graph_objects as go
from dash import dcc, html

# ── Constants ────────────────────────────────────────────────────────────────
FL_BLUE   = "#002B7F"
FL_RED    = "#CE1126"
FL_GOLD   = "#D4A017"
EXP_ORANGE = "#F0883E"   # «experimentell»-Akzent (gleiche Familie wie die Palette)

# rgba-Varianten für Plotly-fillcolor (Plotly 6 akzeptiert kein 8-stelliges Hex)
FL_BLUE_10 = "rgba(0,43,127,0.10)"
FL_BLUE_13 = "rgba(0,43,127,0.13)"
FL_RED_13  = "rgba(206,17,38,0.13)"
BG        = "#0D1117"
SURFACE   = "#161B22"
SURFACE2  = "#1C2128"
BORDER    = "#30363D"
TEXT      = "#E6EDF3"
MUTED     = "#8B949E"
GREEN     = "#3FB950"
ACCENT    = "#58A6FF"

# Farb-Palette für Gemeinde-Vergleich (bis zu 11 Gemeinden)
MUNI_PALETTE = [
    FL_BLUE, FL_RED, FL_GOLD, ACCENT, GREEN,
    "#BB8FCE", "#F0883E", "#58D68D", "#F85149", "#79C0FF", "#D2A679",
]


# ── Chart helpers ─────────────────────────────────────────────────────────────

def _styled(fig: go.Figure, title: str = "", legend: bool = True) -> go.Figure:
    fig.update_layout(
        title=dict(text=title, font=dict(size=15, color=TEXT), x=0.0, xanchor="left"),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=TEXT, family="Inter, sans-serif", size=12),
        xaxis=dict(gridcolor=BORDER, zerolinecolor=BORDER, tickfont=dict(color=MUTED)),
        yaxis=dict(gridcolor=BORDER, zerolinecolor=BORDER, tickfont=dict(color=MUTED)),
        legend=dict(
            bgcolor="rgba(22,27,34,0.92)",
            bordercolor=BORDER,
            font=dict(color=TEXT),
        ) if legend else dict(visible=False),
        hoverlabel=dict(
            bgcolor=SURFACE2,
            bordercolor=BORDER,
            font=dict(color=TEXT, family="Inter, sans-serif", size=12),
        ),
        margin=dict(l=50, r=20, t=50 if title else 30, b=50),
        hovermode="x unified",
    )
    return fig


def _card(children, className=""):
    return html.Div(children, className=f"dash-card {className}")


def _kpi(icon, title, value, color=FL_BLUE, subtitle=""):
    return _card(
        [
            html.Div(
                html.I(className=f"fas {icon} fa-lg"),
                className="kpi-icon",
                style={"background": f"{color}28", "color": color},
            ),
            html.Div([
                html.P(title, className="kpi-label"),
                html.H4(value, className="kpi-value"),
                html.Small(subtitle, className="kpi-sub") if subtitle else None,
            ]),
        ],
        "kpi-card",
    )


def _empty(msg="Keine Daten verfügbar"):
    return html.Div(
        [html.I(className="fas fa-chart-bar fa-2x mb-3", style={"color": MUTED}),
         html.P(msg, style={"color": MUTED})],
        className="empty-state",
    )


# Bekannte Datenquellen mit URLs
SOURCES = {
    "worldbank":   ("World Bank Open Data",           "https://data.worldbank.org/country/LI"),
    "openmeteo":   ("Open-Meteo Archive API",         "https://open-meteo.com/"),
    "amtstat":     ("Amt für Statistik Liechtenstein","https://www.llv.li/de/landesverwaltung/amt-fuer-statistik"),
    "eurostat":    ("Eurostat",                       "https://ec.europa.eu/eurostat"),
    "osm":         ("OpenStreetMap",                  "https://www.openstreetmap.org/"),
    "overpass":    ("Overpass API",                   "https://overpass-api.de/"),
    "opendata":    ("opendata.li (Amt für Statistik)", "https://www.opendata.li/de/daten"),
}


def _source_bar(*source_keys: str, extra: str = "") -> html.Div:
    """
    Rendert eine einheitliche Quellenzeile mit klickbaren Links.
    Beispiel: _source_bar("worldbank", "amtstat")
    """
    parts = []
    for i, key in enumerate(source_keys):
        name, url = SOURCES[key]
        if i > 0:
            parts.append(html.Span(" · ", style={"color": BORDER}))
        parts.append(html.A(
            name, href=url, target="_blank", rel="noopener noreferrer",
            className="source-link",
        ))
    if extra:
        parts.append(html.Span(f" · {extra}", style={"color": MUTED}))
    return html.Div(
        [html.I(className="fas fa-database", style={"marginRight": "6px", "color": MUTED}),
         html.Span("Quelle: ", style={"color": MUTED}),
         *parts],
        className="source-bar",
    )
