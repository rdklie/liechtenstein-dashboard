"""
Liechtenstein Dashboard
=======================
Lokales Dash-Dashboard mit Wirtschafts- und Klimadaten für Liechtenstein.

Starten:
    pip install -r requirements.txt
    python app.py

URL-Parameter:
    ?tab=wirtschaft&indicators=NY.GDP.MKTP.CD,SP.POP.TOTL&year_start=2000&year_end=2023
    ?tab=klima&weather_year=2022&weather_vars=temp_max,temp_min,precipitation
"""

import json
from urllib.parse import urlencode

import dash
import dash_bootstrap_components as dbc
import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, State, dcc, html, no_update

from data_fetcher import (
    WB_INDICATORS,
    VADUZ_LAT,
    VADUZ_LON,
    MUNICIPALITIES,
    OSM_CATEGORIES,
)
from db import (
    get_world_bank,
    get_weather_monthly,
    get_eurostat_tourism,
    get_eurostat_tourism_nights,
    get_eurostat_gdp_eur,
    get_osm_poi_counts,
)

# ── Constants ────────────────────────────────────────────────────────────────
FL_BLUE   = "#002B7F"
FL_RED    = "#CE1126"
FL_GOLD   = "#D4A017"

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

DEFAULT_INDICATORS   = ["NY.GDP.MKTP.CD", "NY.GDP.PCAP.CD"]
DEFAULT_YEAR         = [2000, 2023]
DEFAULT_WEATHER_Y    = 2024
DEFAULT_WEATHER_V    = ["temp_max", "temp_min"]
DEFAULT_MUNICIPALITY = ["vaduz"]

# Farb-Palette für Gemeinde-Vergleich (bis zu 11 Gemeinden)
MUNI_PALETTE = [
    FL_BLUE, FL_RED, FL_GOLD, ACCENT, GREEN,
    "#BB8FCE", "#F0883E", "#58D68D", "#F85149", "#79C0FF", "#D2A679",
]
WEATHER_YEARS        = list(range(2020, 2026))

# Wirtschaftssektoren Liechtenstein (Quelle: Amt für Statistik FL)
SECTOR_DATA = [
    {"sektor": "Verarbeitendes Gewerbe",       "bip": 40, "beschaeftigung": 37, "color": FL_BLUE},
    {"sektor": "Finanzdienstleistungen",        "bip": 25, "beschaeftigung": 17, "color": FL_RED},
    {"sektor": "Handel & Gastgewerbe",          "bip": 12, "beschaeftigung": 14, "color": FL_GOLD},
    {"sektor": "Öffentl. Verwaltung & Bildung", "bip": 8,  "beschaeftigung": 10, "color": ACCENT},
    {"sektor": "Baugewerbe",                    "bip": 6,  "beschaeftigung": 8,  "color": GREEN},
    {"sektor": "Sonstige Dienstleistungen",     "bip": 9,  "beschaeftigung": 14, "color": "#BB8FCE"},
]

WEATHER_VAR_OPTS = [
    {"label": "Temp. Max (°C)",    "value": "temp_max"},
    {"label": "Temp. Min (°C)",    "value": "temp_min"},
    {"label": "Temp. Mittel (°C)", "value": "temp_mean"},
    {"label": "Niederschlag (mm)", "value": "precipitation"},
    {"label": "Wind max (km/h)",   "value": "wind_max"},
]
WEATHER_COLORS = {
    "temp_max":      FL_RED,
    "temp_min":      ACCENT,
    "temp_mean":     FL_GOLD,
    "precipitation": "#58D68D",
    "wind_max":      "#BB8FCE",
}
WEATHER_LABELS = {
    "temp_max":      "Temp. Max (°C)",
    "temp_min":      "Temp. Min (°C)",
    "temp_mean":     "Temp. Mittel (°C)",
    "precipitation": "Niederschlag (mm)",
    "wind_max":      "Wind max (km/h)",
}

# ── App init ─────────────────────────────────────────────────────────────────
app = dash.Dash(
    __name__,
    external_stylesheets=[
        dbc.themes.DARKLY,
        "https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap",
        "https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css",
    ],
    title="Liechtenstein Dashboard",
    suppress_callback_exceptions=True,
    meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1"}],
)
server = app.server


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


def _build_url(store: dict) -> str:
    if not store:
        return ""
    p = {
        "tab":          store.get("tab", "uebersicht"),
        "year_start":   store["year"][0],
        "year_end":     store["year"][1],
        "indicators":   json.dumps(store.get("indicators", DEFAULT_INDICATORS)),
        "weather_year": store.get("weather_year", DEFAULT_WEATHER_Y),
        "weather_vars": json.dumps(store.get("weather_vars", DEFAULT_WEATHER_V)),
        "municipality": json.dumps(store.get("municipality", DEFAULT_MUNICIPALITY)),
    }
    return "?" + urlencode(p)


# ── Layout ───────────────────────────────────────────────────────────────────

INDICATOR_OPTS = [
    {"label": label, "value": key}
    for key, label in WB_INDICATORS.items()
]

HEADER = html.Div(
    [
        html.Div(className="header-flag-blue"),
        html.Div(className="header-flag-red"),
        html.Div(
            [
                html.Div([
                    html.Span("🇱🇮", style={"fontSize": "2rem", "marginRight": "12px"}),
                    html.Div([
                        html.H1("Liechtenstein Dashboard", className="header-title"),
                        html.P("Wirtschaft · Bevölkerung · Klima · Tourismus", className="header-sub"),
                    ]),
                ], className="header-left"),
                html.Div([
                    html.Div("Datenquellen: World Bank · Open-Meteo · Eurostat · OSM", className="header-badge"),
                ], className="header-right"),
            ],
            className="header-content",
        ),
        # ── Disclaimer ───────────────────────────────────────────────────────
        html.Div(
            [
                html.I(className="fas fa-info-circle", style={"marginRight": "6px", "opacity": "0.7"}),
                "Dies ist keine offizielle Seite — Hobby- & Freizeitprojekt. · Für Fragen: ",
                html.A(
                    "kontakt [at] daten.li",   # Platzhalter; JS setzt echte Adresse
                    id="contact-email",
                    href="#",
                    className="disclaimer-link",
                ),
            ],
            className="header-disclaimer",
        ),
    ],
    className="app-header",
)


def _build_sidebar() -> html.Div:
    """Baut die Sidebar mit Default-Filterwerten.
    URL-Parameter werden nach Dash-Start via dcc.Interval + clientside callback gesetzt."""
    return html.Div(
        [
            html.Div(className="sidebar-flag"),
            html.Div(
                [
                    html.H6("Filter", className="sidebar-title"),

                    # ── Tab switcher ────────────────────────────────────────
                    html.Div([
                        html.Label("Bereich", className="filter-label"),
                        dcc.Tabs(
                            id="tab-select",
                            value="uebersicht",
                            vertical=False,
                            className="sidebar-tabs",
                            children=[
                                dcc.Tab(label="Übersicht",  value="uebersicht", className="stab", selected_className="stab-selected"),
                                dcc.Tab(label="Wirtschaft", value="wirtschaft", className="stab", selected_className="stab-selected"),
                                dcc.Tab(label="Klima",      value="klima",      className="stab", selected_className="stab-selected"),
                                dcc.Tab(label="Tourismus",  value="tourismus",  className="stab", selected_className="stab-selected"),
                            ],
                        ),
                    ], className="filter-section"),

                    html.Hr(className="filter-hr"),

                    # ── Economy filters ──────────────────────────────────────
                    html.Div(id="filter-economy", children=[
                        html.Div([
                            html.Label("Zeitraum (Jahr)", className="filter-label"),
                            dcc.RangeSlider(
                                id="year-slider",
                                min=1990, max=2023,
                                value=DEFAULT_YEAR,
                                marks={y: {"label": str(y), "style": {"color": MUTED, "fontSize": "10px"}}
                                       for y in range(1990, 2024, 5)},
                                step=1,
                                tooltip={"placement": "bottom", "always_visible": True},
                                className="fl-slider",
                            ),
                        ], className="filter-section"),
                        html.Div([
                            html.Label("Indikator(en)", className="filter-label"),
                            dcc.Dropdown(
                                id="indicator-select",
                                options=INDICATOR_OPTS,
                                value=DEFAULT_INDICATORS,
                                multi=True,
                                placeholder="Indikator wählen…",
                                className="fl-dropdown",
                            ),
                        ], className="filter-section"),
                    ]),

                    # ── Tourism filters ──────────────────────────────────────
                    html.Div(id="filter-tourism", children=[
                        html.Div([
                            html.Label("Zeitraum (Jahr)", className="filter-label"),
                            dcc.RangeSlider(
                                id="tourism-year-slider",
                                min=1995, max=2024,
                                value=[1995, 2024],
                                marks={y: {"label": str(y), "style": {"color": MUTED, "fontSize": "10px"}}
                                       for y in range(1995, 2025, 5)},
                                step=1,
                                tooltip={"placement": "bottom", "always_visible": True},
                                className="fl-slider",
                            ),
                        ], className="filter-section"),
                    ]),

                    # ── Climate filters ──────────────────────────────────────
                    html.Div(id="filter-climate", children=[
                        html.Div([
                            html.Label("Gemeinde", className="filter-label"),
                            dcc.Dropdown(
                                id="municipality-select",
                                options=[
                                    {"label": f"{m['name']} ({m['elev']} m)", "value": k}
                                    for k, m in MUNICIPALITIES.items()
                                ],
                                value=DEFAULT_MUNICIPALITY,
                                multi=True,
                                clearable=False,
                                placeholder="Gemeinde wählen…",
                                className="fl-dropdown",
                            ),
                        ], className="filter-section"),
                        html.Div([
                            html.Label("Jahr", className="filter-label"),
                            dcc.Dropdown(
                                id="weather-year",
                                options=[{"label": str(y), "value": y} for y in WEATHER_YEARS],
                                value=DEFAULT_WEATHER_Y,
                                clearable=False,
                                className="fl-dropdown",
                            ),
                        ], className="filter-section"),
                        html.Div([
                            html.Label("Klimavariablen", className="filter-label"),
                            dcc.Checklist(
                                id="weather-vars",
                                options=WEATHER_VAR_OPTS,
                                value=DEFAULT_WEATHER_V,
                                className="fl-checklist",
                                labelClassName="checklist-label",
                            ),
                        ], className="filter-section"),
                    ]),

                    html.Hr(className="filter-hr"),

                    # ── Share URL ────────────────────────────────────────────
                    html.Div([
                        html.Label("Dashboard-Link", className="filter-label"),
                        html.Div([
                            dcc.Input(
                                id="share-url-input",
                                type="text",
                                readOnly=True,
                                className="share-input",
                            ),
                            html.Button(
                                html.I(className="fas fa-copy"),
                                id="copy-btn",
                                className="copy-btn",
                                title="URL kopieren",
                            ),
                        ], className="share-row"),
                        html.Small(id="copy-feedback", className="copy-feedback"),
                    ], className="filter-section"),
                ],
                className="sidebar-inner",
            ),
        ],
        className="sidebar",
    )


app.layout = html.Div(
    [
        dcc.Location(id="url", refresh=False),
        # Einmaliger Trigger für URL-Parameter-Initialisierung.
        # max_intervals=1 → feuert exakt einmal nach Dash-Start.
        # Wird NIEMALS als Output geschrieben → kein Zyklus möglich.
        dcc.Interval(id="init-interval", interval=50, n_intervals=0, max_intervals=1),
        HEADER,
        dbc.Container(
            dbc.Row(
                [
                    dbc.Col(_build_sidebar(), width=3, className="p-0"),
                    dbc.Col(
                        html.Div(id="tab-content", className="tab-content-area"),
                        width=9,
                    ),
                ],
                className="g-0 main-row",
            ),
            fluid=True,
            className="main-container",
        ),
    ],
    className="app-wrapper",
)


# ── Callbacks ─────────────────────────────────────────────────────────────────
# Zyklus-freie Architektur für Dash 4:
#
#   dcc.Interval (max_intervals=1, feuert einmalig nach ~50ms)
#     → clientside callback liest window._flUrlParams (gesetzt von url_init.js)
#     → setzt Filter-Komponenten EINMALIG mit URL-Parametern
#
#   Filter-Komponenten → url.search   (Output ONLY — niemals Input)
#   Filter-Komponenten → Inhalt
#   Filter-Komponenten → Sidebar-Sicht
#
#   Kein Pfad von url.search zurück zu irgendeinem Filter → kein Zyklus.
# ─────────────────────────────────────────────────────────────────────────────

# 1. Einmaliger Seitenload: Interval → URL-Params → Filter-Komponenten
#    Funktioniert weil dcc.Interval NIEMALS Output ist → kein Zyklus möglich.
app.clientside_callback(
    """
    function(n) {
        var p = window._flUrlParams || {};
        if (!p || Object.keys(p).length === 0) {
            return [
                'uebersicht',
                [2000, 2023],
                ['NY.GDP.MKTP.CD', 'NY.GDP.PCAP.CD'],
                2024,
                ['temp_max', 'temp_min'],
                'vaduz'
            ];
        }
        var tab  = p['tab']  || 'uebersicht';
        var y0   = parseInt(p['year_start'])   || 2000;
        var y1   = parseInt(p['year_end'])     || 2023;
        var muni;
        try { muni = JSON.parse(p['municipality']); } catch(e) { muni = p['municipality'] ? [p['municipality']] : ['vaduz']; }
        if (!Array.isArray(muni)) muni = [muni];
        var wy   = parseInt(p['weather_year']) || 2024;
        var ind, wv;
        try { ind = JSON.parse(p['indicators']); }   catch(e) { ind = ['NY.GDP.MKTP.CD','NY.GDP.PCAP.CD']; }
        try { wv  = JSON.parse(p['weather_vars']); } catch(e) { wv  = ['temp_max','temp_min']; }
        return [tab, [y0, y1], ind, wy, wv, muni];

    }
    """,
    Output("tab-select",          "value"),
    Output("year-slider",         "value"),
    Output("indicator-select",    "value"),
    Output("weather-year",        "value"),
    Output("weather-vars",        "value"),
    Output("municipality-select", "value"),
    Input("init-interval", "n_intervals"),
    prevent_initial_call=False,
)


# 2. Filter-Komponenten → URL + Share-Link
#    url.search ist Output-only → kein Zyklus
@app.callback(
    Output("url",             "search"),
    Output("share-url-input", "value"),
    Input("tab-select",          "value"),
    Input("year-slider",         "value"),
    Input("indicator-select",    "value"),
    Input("weather-year",        "value"),
    Input("weather-vars",        "value"),
    Input("municipality-select", "value"),
    State("url", "href"),
    prevent_initial_call=True,
)
def filters_to_url(tab, year, indicators, weather_year, weather_vars, municipality, href):
    store = {
        "tab":          tab          or "uebersicht",
        "year":         year         or DEFAULT_YEAR,
        "indicators":   indicators   or DEFAULT_INDICATORS,
        "weather_year": weather_year or DEFAULT_WEATHER_Y,
        "weather_vars": weather_vars or DEFAULT_WEATHER_V,
        "municipality": (municipality if isinstance(municipality, list) else [municipality]) if municipality else DEFAULT_MUNICIPALITY,
    }
    new_search = _build_url(store)
    base = (href or "http://localhost:8050").split("?")[0]
    return new_search, base + new_search


# 2. Filter-Komponenten → Inhalt
@app.callback(
    Output("tab-content", "children"),
    Input("tab-select",            "value"),
    Input("year-slider",           "value"),
    Input("indicator-select",      "value"),
    Input("weather-year",          "value"),
    Input("weather-vars",          "value"),
    Input("municipality-select",   "value"),
    Input("tourism-year-slider",   "value"),
)
def render_content(tab, year, indicators, weather_year, weather_vars, municipality, tourism_year):
    data = {
        "tab":          tab          or "uebersicht",
        "year":         year         or DEFAULT_YEAR,
        "indicators":   indicators   or DEFAULT_INDICATORS,
        "weather_year": weather_year or DEFAULT_WEATHER_Y,
        "weather_vars": weather_vars or DEFAULT_WEATHER_V,
        "municipality": (municipality if isinstance(municipality, list) else [municipality]) if municipality else DEFAULT_MUNICIPALITY,
        "tourism_year": tourism_year or [1995, 2024],
    }
    if data["tab"] == "wirtschaft":
        return _render_economy(data)
    elif data["tab"] == "klima":
        return _render_climate(data)
    elif data["tab"] == "tourismus":
        return _render_tourism(data)
    else:
        return _render_overview(data)


# 3. Tab-Auswahl → Sidebar-Sektionen ein-/ausblenden
@app.callback(
    Output("filter-economy",  "style"),
    Output("filter-tourism",  "style"),
    Output("filter-climate",  "style"),
    Input("tab-select", "value"),
)
def toggle_filters(tab):
    show, hide = {"display": "block"}, {"display": "none"}
    if tab == "wirtschaft": return show, hide, hide
    if tab == "tourismus":  return hide, show, hide
    if tab == "klima":      return hide, hide, show
    return hide, hide, hide


# 4. Copy-Button Feedback
app.clientside_callback(
    """
    function(n) {
        if (!n) return '';
        var el = document.getElementById('share-url-input');
        if (el) { el.select(); document.execCommand('copy'); }
        return '✓ Kopiert!';
    }
    """,
    Output("copy-feedback", "children"),
    Input("copy-btn",       "n_clicks"),
    prevent_initial_call=True,
)


# ── Tab renderers ─────────────────────────────────────────────────────────────

def _render_overview(data: dict):
    # Fetch latest values for KPI cards
    def _latest(ind):
        df = get_world_bank(ind)
        if df.empty:
            return None, None
        row = df.dropna(subset=["value"]).iloc[-1]
        prev = df.dropna(subset=["value"]).iloc[-2] if len(df) > 1 else None
        return row["value"], (row["value"] - prev["value"]) / abs(prev["value"]) * 100 if prev is not None else None

    gdp_v, gdp_d    = _latest("NY.GDP.MKTP.CD")
    pop_v, pop_d    = _latest("SP.POP.TOTL")
    gdppc_v, _      = _latest("NY.GDP.PCAP.CD")
    inf_v, _        = _latest("FP.CPI.TOTL.ZG")
    uem_v, _        = _latest("SL.UEM.TOTL.ZS")

    def _fmt_gdp(v):
        if v is None: return "–"
        if v >= 1e9: return f"${v/1e9:.1f} Mrd."
        return f"${v/1e6:.0f} Mio."

    def _fmt_delta(d):
        if d is None: return ""
        sign = "▲" if d >= 0 else "▼"
        return f"{sign} {abs(d):.1f}% zum Vorjahr"

    kpi_row = dbc.Row([
        dbc.Col(_kpi("fa-dollar-sign", "BIP (gesamt)",     _fmt_gdp(gdp_v),                   FL_BLUE, _fmt_delta(gdp_d)), md=4, className="mb-3"),
        dbc.Col(_kpi("fa-users",       "Bevölkerung",      f"{pop_v:,.0f}".replace(",", " ") if pop_v else "–",
                                                                                                FL_RED,  _fmt_delta(pop_d)), md=4, className="mb-3"),
        dbc.Col(_kpi("fa-chart-line",  "BIP pro Kopf",     f"${gdppc_v:,.0f}".replace(",", " ") if gdppc_v else "–",
                                                                                                FL_GOLD, ""), md=4, className="mb-3"),
    ], className="g-3")

    kpi_row2 = dbc.Row([
        dbc.Col(_kpi("fa-fire",        "Inflation",        f"{inf_v:.1f}%" if inf_v is not None else "–",
                                                                                                FL_RED,  ""), md=4, className="mb-3"),
        dbc.Col(_kpi("fa-briefcase",   "Arbeitslosigkeit", f"{uem_v:.1f}%" if uem_v is not None else "–",
                                                                                                GREEN,   ""), md=4, className="mb-3"),
        dbc.Col(_kpi("fa-map-marker-alt", "Hauptstadt",    "Vaduz",                            ACCENT,  "47.14°N · 9.52°E"), md=4, className="mb-3"),
    ], className="g-3")

    # Mini time series (population)
    pop_df = get_world_bank("SP.POP.TOTL")
    gdp_df = get_world_bank("NY.GDP.MKTP.CD")

    pop_fig = go.Figure()
    if not pop_df.empty:
        pop_fig.add_trace(go.Scatter(
            x=pop_df["year"], y=pop_df["value"],
            mode="lines+markers",
            line=dict(color=FL_BLUE, width=2),
            marker=dict(size=4),
            fill="tozeroy", fillcolor=FL_BLUE_13,
            name="Bevölkerung",
            hovertemplate="%{y:,.0f}<extra></extra>",
        ))
    _styled(pop_fig, "Bevölkerungsentwicklung")

    gdp_fig = go.Figure()
    if not gdp_df.empty:
        gdp_fig.add_trace(go.Scatter(
            x=gdp_df["year"], y=gdp_df["value"] / 1e9,
            mode="lines+markers",
            line=dict(color=FL_RED, width=2),
            marker=dict(size=4),
            fill="tozeroy", fillcolor=FL_RED_13,
            name="BIP",
            hovertemplate="%{y:.2f} Mrd. USD<extra></extra>",
        ))
    _styled(gdp_fig, "BIP-Entwicklung (Mrd. USD)")

    info = _card([
        html.H5("Über Liechtenstein", className="info-title"),
        html.Div([
            _info_row("fa-ruler-combined", "Fläche",           "160 km²"),
            _info_row("fa-money-bill",     "Währung",          "Schweizer Franken (CHF)"),
            _info_row("fa-landmark",       "Regierungsform",   "Konstitutionelle Monarchie"),
            _info_row("fa-industry",       "Hauptbranchen",    "Finanzdienstleistungen, Präzisionsfertigung, Zahnmedizin"),
            _info_row("fa-flag",           "UN-Mitglied",      "Seit 1990"),
            _info_row("fa-handshake",      "EWR-Mitglied",     "Seit 1995"),
            _info_row("fa-university",     "Weltbank-Gruppe",  "Nicht Mitglied (Wirtschaftsdaten teils via Eurostat)"),
        ], className="info-list"),
    ], "info-card")

    # ── OSM Points of Interest ────────────────────────────────────────────────
    poi_counts = get_osm_poi_counts()
    poi_section = None
    if poi_counts:
        sorted_pois = sorted(poi_counts.items(), key=lambda x: x[1], reverse=True)
        cats   = [c for c, _ in sorted_pois]
        counts = [n for _, n in sorted_pois]
        poi_colors = [FL_BLUE, FL_RED, FL_GOLD, ACCENT, GREEN,
                      "#BB8FCE", "#F0883E", "#58D68D", "#F85149",
                      "#79C0FF", "#D2A679", "#3FB950", "#E879F9",
                      "#FBD460", "#FF6B6B"]
        poi_fig = go.Figure(go.Bar(
            x=counts, y=cats,
            orientation="h",
            marker_color=poi_colors[:len(cats)],
            hovertemplate="<b>%{y}</b>: %{x}<extra></extra>",
        ))
        _styled(poi_fig, "Points of Interest in Liechtenstein (OpenStreetMap)", legend=False)
        poi_fig.update_layout(
            yaxis=dict(autorange="reversed", tickfont=dict(size=11, color=TEXT)),
            xaxis_title="Anzahl",
            margin=dict(l=160, r=20, t=50, b=40),
        )
        poi_section = dbc.Row([
            dbc.Col(_card(dcc.Graph(figure=poi_fig, config={"displayModeBar": False})), md=12, className="mb-3"),
        ], className="g-3")

    chart_row = dbc.Row([
        dbc.Col(_card(dcc.Graph(figure=pop_fig, config={"displayModeBar": False})), md=6, className="mb-3"),
        dbc.Col(_card(dcc.Graph(figure=gdp_fig, config={"displayModeBar": False})), md=6, className="mb-3"),
    ], className="g-3")

    # Datenquellen-Übersichtskarte
    sources_card = _card([
        html.H5("Datenquellen", className="info-title"),
        html.Div([
            _source_info_row("fa-globe",       "World Bank Open Data",            "https://data.worldbank.org/country/LI",         "Wirtschafts- & Bevölkerungsdaten"),
            _source_info_row("fa-cloud-sun",   "Open-Meteo Archive API",          "https://open-meteo.com/",                       "Historische Klimadaten aller 11 Gemeinden"),
            _source_info_row("fa-chart-bar",   "Amt für Statistik Liechtenstein", "https://www.llv.li/de/landesverwaltung/amt-fuer-statistik", "Tourismus, Sektoren, Bevölkerung"),
            _source_info_row("fa-university",  "Eurostat",                        "https://ec.europa.eu/eurostat",                 "BIP & Wirtschaftsstatistik (EWR)"),
            _source_info_row("fa-map-marked-alt", "OpenStreetMap / Overpass API", "https://www.openstreetmap.org/",               "Points of Interest in Liechtenstein"),
        ], className="info-list"),
        html.Small(
            "Alle Daten werden täglich automatisch aktualisiert. "
            "Dieses Dashboard ist ein unabhängiges Freizeitprojekt ohne Verbindung zu offiziellen Stellen.",
            style={"color": MUTED, "display": "block", "marginTop": "10px", "lineHeight": "1.5"},
        ),
    ], "info-card")

    rows = [
        html.H4("Liechtenstein im Überblick", className="section-title"),
        kpi_row,
        kpi_row2,
        chart_row,
        _source_bar("worldbank", extra="Bevölkerung & BIP · letzte verfügbare Jahreswerte"),
        dbc.Row([dbc.Col(info, md=8), dbc.Col(sources_card, md=4)], className="g-3 mt-1"),
    ]
    if poi_section:
        rows += [
            html.H4("Infrastruktur & Sehenswürdigkeiten", className="section-title mt-3"),
            poi_section,
            _source_bar("osm", "overpass", extra="Liechtenstein Bounding Box"),
        ]
    return html.Div(rows)


def _info_row(icon, label, value):
    return html.Div([
        html.I(className=f"fas {icon}", style={"color": FL_BLUE, "width": "18px"}),
        html.Span(label + ":", className="info-label"),
        html.Span(value, className="info-value"),
    ], className="info-row")


def _source_info_row(icon, name, url, description):
    return html.Div([
        html.I(className=f"fas {icon}", style={"color": ACCENT, "width": "18px"}),
        html.A(name, href=url, target="_blank", rel="noopener noreferrer",
               className="source-link", style={"marginRight": "6px"}),
        html.Span(f"— {description}", style={"color": MUTED, "fontSize": "0.8rem"}),
    ], className="info-row")


def _render_economy(data: dict):
    year_range = data.get("year", DEFAULT_YEAR)
    indicators = data.get("indicators", DEFAULT_INDICATORS)

    if not indicators:
        return _empty("Bitte mindestens einen Indikator auswählen.")

    y0, y1 = year_range

    # ── Time series ──────────────────────────────────────────────────────────
    ts_fig = go.Figure()
    palette = [FL_BLUE, FL_RED, FL_GOLD, ACCENT, "#3FB950", "#BB8FCE", "#F0883E", "#58D68D"]

    for i, ind in enumerate(indicators):
        df = get_world_bank(ind)
        if df.empty:
            continue
        df = df[(df["year"] >= y0) & (df["year"] <= y1)]
        if df.empty:
            continue
        label = WB_INDICATORS.get(ind, ind)
        # Scale GDP values to Mrd.
        y_vals = df["value"] / 1e9 if "MKTP" in ind else df["value"]
        y_label = label + (" (Mrd.)" if "MKTP" in ind else "")
        ts_fig.add_trace(go.Scatter(
            x=df["year"], y=y_vals,
            mode="lines+markers",
            name=label,
            line=dict(color=palette[i % len(palette)], width=2.5),
            marker=dict(size=5),
            hovertemplate=f"<b>{label}</b><br>Jahr: %{{x}}<br>Wert: %{{y:,.2f}}<extra></extra>",
        ))

    if not ts_fig.data:
        ts_chart = _empty("Keine Daten für den gewählten Zeitraum.")
    else:
        _styled(ts_fig, f"Zeitreihe {y0}–{y1}", legend=True)
        ts_chart = dcc.Graph(figure=ts_fig, config={"displayModeBar": False})

    # ── Bar: last 10 years for first indicator ───────────────────────────────
    bar_fig = go.Figure()
    if indicators:
        ind0 = indicators[0]
        df0 = get_world_bank(ind0)
        if not df0.empty:
            df0 = df0[(df0["year"] >= y0) & (df0["year"] <= y1)].tail(10)
            y_vals = df0["value"] / 1e9 if "MKTP" in ind0 else df0["value"]
            label0 = WB_INDICATORS.get(ind0, ind0)
            bar_fig.add_trace(go.Bar(
                x=df0["year"].astype(str),
                y=y_vals,
                marker_color=[FL_BLUE if v < y_vals.max() else FL_RED for v in y_vals],
                name=label0,
                hovertemplate=f"<b>{label0}</b><br>Jahr: %{{x}}<br>Wert: %{{y:,.2f}}<extra></extra>",
            ))
            _styled(bar_fig, f"{label0} — letzte Jahre", legend=False)

    if not bar_fig.data:
        bar_chart = _empty()
    else:
        bar_chart = dcc.Graph(figure=bar_fig, config={"displayModeBar": False})

    # ── Sector charts ────────────────────────────────────────────────────────
    sector_df = pd.DataFrame(SECTOR_DATA)

    # Donut: BIP-Anteile
    donut_fig = go.Figure(go.Pie(
        labels=sector_df["sektor"],
        values=sector_df["bip"],
        hole=0.55,
        marker=dict(colors=sector_df["color"].tolist(), line=dict(color=BG, width=2)),
        textinfo="label+percent",
        textfont=dict(color=TEXT, size=11),
        hovertemplate="<b>%{label}</b><br>BIP-Anteil: %{value}%<extra></extra>",
        insidetextorientation="radial",
    ))
    donut_fig.update_layout(
        title=dict(text="Wirtschaftssektoren nach BIP-Anteil (%)", font=dict(size=15, color=TEXT), x=0.0),
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color=TEXT, family="Inter, sans-serif"),
        showlegend=False,
        margin=dict(l=20, r=20, t=50, b=20),
        annotations=[dict(text="BIP", x=0.5, y=0.5, font=dict(size=16, color=MUTED), showarrow=False)],
    )

    # Grouped bar: BIP vs. Beschäftigung
    group_fig = go.Figure()
    group_fig.add_trace(go.Bar(
        name="BIP-Anteil (%)",
        x=sector_df["sektor"],
        y=sector_df["bip"],
        marker_color=FL_BLUE,
        hovertemplate="<b>BIP-Anteil</b>: %{y}%<extra></extra>",
    ))
    group_fig.add_trace(go.Bar(
        name="Beschäftigung (%)",
        x=sector_df["sektor"],
        y=sector_df["beschaeftigung"],
        marker_color=FL_RED,
        hovertemplate="<b>Beschäftigung</b>: %{y}%<extra></extra>",
    ))
    group_fig.update_layout(barmode="group")
    _styled(group_fig, "Sektoren: BIP-Anteil vs. Beschäftigungsanteil (%)", legend=True)
    group_fig.update_xaxes(tickangle=-30)

    return html.Div([
        html.H4("Wirtschaftliche Indikatoren", className="section-title"),
        dbc.Row([
            dbc.Col(_card(ts_chart), md=12, className="mb-3"),
        ], className="g-3"),
        dbc.Row([
            dbc.Col(_card(bar_chart), md=12, className="mb-3"),
        ], className="g-3"),
        html.H4("Wirtschaftssektoren Liechtenstein", className="section-title mt-3"),
        dbc.Row([
            dbc.Col(_card(dcc.Graph(figure=donut_fig, config={"displayModeBar": False})), md=5, className="mb-3"),
            dbc.Col(_card(dcc.Graph(figure=group_fig, config={"displayModeBar": False})), md=7, className="mb-3"),
        ], className="g-3"),
        _source_bar("worldbank", "amtstat", extra="Sektordaten: Amt für Statistik FL, ca. 2022"),
    ])


def _render_climate(data: dict):
    year         = data.get("weather_year", DEFAULT_WEATHER_Y)
    vars_sel     = data.get("weather_vars", DEFAULT_WEATHER_V)
    munis        = data.get("municipality", DEFAULT_MUNICIPALITY)
    if not isinstance(munis, list):
        munis = [munis]
    if not munis:
        munis = DEFAULT_MUNICIPALITY

    temp_vars  = [v for v in vars_sel if v in ("temp_max", "temp_min", "temp_mean")]
    precip_sel = "precipitation" in vars_sel
    wind_sel   = "wind_max" in vars_sel
    multi      = len(munis) > 1

    # Lade Daten für alle gewählten Gemeinden
    dfs = {}
    for key in munis:
        info = MUNICIPALITIES.get(key, MUNICIPALITIES["vaduz"])
        df = get_weather_monthly(key, year, lat=info["lat"], lon=info["lon"])
        if not df.empty:
            dfs[key] = df

    if not dfs:
        return html.Div([
            html.H4("Klimadaten – Liechtenstein", className="section-title"),
            _empty(f"Keine Wetterdaten für {year} verfügbar."),
        ])

    months = list(dfs.values())[0]["month_name"].tolist()

    # Gemeinde-Label und Farbe je Gemeinde
    def muni_color(i):
        return MUNI_PALETTE[i % len(MUNI_PALETTE)]

    def muni_label(key):
        return MUNICIPALITIES[key]["name"]

    # ── Temperatur-Chart ──────────────────────────────────────────────────────
    temp_fig = go.Figure()
    for mi, key in enumerate(dfs):
        df   = dfs[key]
        col  = muni_color(mi)
        name = muni_label(key)
        if multi:
            # Im Vergleichsmodus: pro Gemeinde eine Linie pro Temp-Variable
            # Wähle nur eine Haupt-Variable um den Chart lesbar zu halten;
            # falls mehrere gewählt, zeige alle, aber mit Gemeinden-Suffix
            for var in temp_vars:
                if var in df.columns:
                    # Linientyp variiert je Variable: solid / dash / dot
                    dash = {"temp_max": "solid", "temp_min": "dash", "temp_mean": "dot"}.get(var, "solid")
                    temp_fig.add_trace(go.Scatter(
                        x=months, y=df[var].round(1),
                        mode="lines+markers",
                        name=f"{name} – {WEATHER_LABELS[var]}",
                        line=dict(color=col, width=2, dash=dash),
                        marker=dict(size=5),
                        legendgroup=key,
                        hovertemplate=f"<b>{name}</b> {WEATHER_LABELS[var]}: %{{y:.1f}} °C<extra></extra>",
                    ))
        else:
            # Einzelne Gemeinde: eine Linie pro Variable, Schattenband
            for var in temp_vars:
                if var in df.columns:
                    temp_fig.add_trace(go.Scatter(
                        x=months, y=df[var].round(1),
                        mode="lines+markers",
                        name=WEATHER_LABELS[var],
                        line=dict(color=WEATHER_COLORS[var], width=2.5),
                        marker=dict(size=6),
                        hovertemplate=f"<b>{WEATHER_LABELS[var]}</b>: %{{y:.1f}} °C<extra></extra>",
                    ))
            if "temp_max" in temp_vars and "temp_min" in temp_vars:
                df = list(dfs.values())[0]
                temp_fig.add_trace(go.Scatter(
                    x=months + months[::-1],
                    y=list(df["temp_max"].round(1)) + list(df["temp_min"].round(1))[::-1],
                    fill="toself", fillcolor=FL_BLUE_10,
                    line=dict(color="rgba(0,0,0,0)"),
                    showlegend=False, hoverinfo="skip",
                ))

    title_munis = " vs. ".join(muni_label(k) for k in dfs) if multi else muni_label(list(dfs.keys())[0])
    if temp_fig.data:
        _styled(temp_fig, f"Temperatur {year} – {title_munis} (°C)", legend=True)
        temp_chart = dcc.Graph(figure=temp_fig, config={"displayModeBar": False})
    else:
        temp_chart = _empty("Keine Temperaturvariable gewählt.")

    # ── Niederschlag-Chart ────────────────────────────────────────────────────
    if precip_sel:
        prc_fig = go.Figure()
        if multi:
            # Gruppiertes Balkendiagramm
            for mi, key in enumerate(dfs):
                df = dfs[key]
                if "precipitation" in df.columns:
                    prc_fig.add_trace(go.Bar(
                        x=months, y=df["precipitation"].round(1),
                        name=muni_label(key),
                        marker_color=muni_color(mi),
                        hovertemplate=f"<b>{muni_label(key)}</b>: %{{y:.1f}} mm<extra></extra>",
                    ))
            prc_fig.update_layout(barmode="group")
            _styled(prc_fig, f"Niederschlag {year} – Vergleich (mm)", legend=True)
        else:
            df = list(dfs.values())[0]
            if "precipitation" in df.columns:
                prc_fig.add_trace(go.Bar(
                    x=months, y=df["precipitation"].round(1),
                    marker_color=WEATHER_COLORS["precipitation"],
                    name="Niederschlag (mm)",
                    hovertemplate="<b>Niederschlag</b>: %{y:.1f} mm<extra></extra>",
                ))
            _styled(prc_fig, f"Niederschlag {year} – {title_munis} (mm)", legend=False)
        precip_chart = dcc.Graph(figure=prc_fig, config={"displayModeBar": False}) if prc_fig.data else None
    else:
        precip_chart = None

    # ── Wind-Chart ────────────────────────────────────────────────────────────
    if wind_sel:
        wind_fig = go.Figure()
        if multi:
            for mi, key in enumerate(dfs):
                df = dfs[key]
                if "wind_max" in df.columns:
                    wind_fig.add_trace(go.Scatter(
                        x=months, y=df["wind_max"].round(1),
                        mode="lines+markers",
                        name=muni_label(key),
                        line=dict(color=muni_color(mi), width=2),
                        marker=dict(size=5),
                        hovertemplate=f"<b>{muni_label(key)}</b>: %{{y:.1f}} km/h<extra></extra>",
                    ))
            _styled(wind_fig, f"Max. Wind {year} – Vergleich (km/h)", legend=True)
        else:
            df = list(dfs.values())[0]
            if "wind_max" in df.columns:
                wind_fig.add_trace(go.Bar(
                    x=months, y=df["wind_max"].round(1),
                    marker_color=WEATHER_COLORS["wind_max"],
                    name="Max. Wind (km/h)",
                    hovertemplate="<b>Max. Wind</b>: %{y:.1f} km/h<extra></extra>",
                ))
            _styled(wind_fig, f"Max. Wind {year} – {title_munis} (km/h)", legend=False)
        wind_chart = dcc.Graph(figure=wind_fig, config={"displayModeBar": False}) if wind_fig.data else None
    else:
        wind_chart = None

    # ── KPI-Karten (erste / einzige Gemeinde als Referenz) ────────────────────
    ref_df   = list(dfs.values())[0]
    ref_name = muni_label(list(dfs.keys())[0])
    kpi_prefix = f"{ref_name}: " if multi else ""

    kpi_row = dbc.Row([
        dbc.Col(_kpi("fa-thermometer-three-quarters", "Jahres-Ø Temp.",
                     f"{kpi_prefix}{ref_df['temp_mean'].mean():.1f} °C" if "temp_mean" in ref_df.columns else "–",
                     FL_BLUE), md=3, className="mb-3"),
        dbc.Col(_kpi("fa-sun", "Heißester Monat",
                     f"{kpi_prefix}{ref_df.loc[ref_df['temp_max'].idxmax(), 'month_name']} ({ref_df['temp_max'].max():.1f}°C)" if "temp_max" in ref_df.columns else "–",
                     FL_RED), md=3, className="mb-3"),
        dbc.Col(_kpi("fa-snowflake", "Kältester Monat",
                     f"{kpi_prefix}{ref_df.loc[ref_df['temp_min'].idxmin(), 'month_name']} ({ref_df['temp_min'].min():.1f}°C)" if "temp_min" in ref_df.columns else "–",
                     ACCENT), md=3, className="mb-3"),
        dbc.Col(_kpi("fa-cloud-rain", "Jahres-Niederschlag",
                     f"{kpi_prefix}{ref_df['precipitation'].sum():.0f} mm" if "precipitation" in ref_df.columns else "–",
                     GREEN), md=3, className="mb-3"),
    ], className="g-3")

    charts = [dbc.Row([dbc.Col(_card(temp_chart), md=12, className="mb-3")], className="g-3")]
    if precip_chart or wind_chart:
        cols = []
        if precip_chart:
            cols.append(dbc.Col(_card(precip_chart), md=6 if wind_chart else 12, className="mb-3"))
        if wind_chart:
            cols.append(dbc.Col(_card(wind_chart),   md=6 if precip_chart else 12, className="mb-3"))
        charts.append(dbc.Row(cols, className="g-3"))

    # Quellenangabe mit allen Gemeinden
    source_parts = "; ".join(
        f"{muni_label(k)}: {MUNICIPALITIES[k]['lat']:.4f}°N · {MUNICIPALITIES[k]['elev']} m"
        for k in dfs
    )

    return html.Div([
        html.H4(f"Klimadaten – {title_munis} ({year})", className="section-title"),
        kpi_row,
        *charts,
        _source_bar("openmeteo", extra=source_parts),
    ])


def _render_tourism(data: dict):
    y0, y1 = data.get("tourism_year", [1995, 2024])

    # ── Fetch data ────────────────────────────────────────────────────────────
    arr_df    = get_eurostat_tourism()
    nights_df = get_eurostat_tourism_nights()
    gdp_df    = get_eurostat_gdp_eur()

    def _filter_years(df):
        if df.empty:
            return df
        return df[(df["year"] >= y0) & (df["year"] <= y1)]

    arr_df    = _filter_years(arr_df)
    nights_df = _filter_years(nights_df)
    gdp_df    = _filter_years(gdp_df)

    # ── KPI cards ─────────────────────────────────────────────────────────────
    def _latest_val(df, col="value"):
        if df.empty or col not in df.columns:
            return None
        row = df.dropna(subset=[col])
        return row[col].iloc[-1] if not row.empty else None

    arr_latest    = _latest_val(arr_df)
    nights_latest = _latest_val(nights_df)
    gdp_latest    = _latest_val(gdp_df)

    kpi_row = dbc.Row([
        dbc.Col(_kpi("fa-plane-arrival", "Ankünfte (letztes Jahr)",
                     f"{arr_latest:,.0f}".replace(",", " ") if arr_latest else "–", FL_BLUE), md=4, className="mb-3"),
        dbc.Col(_kpi("fa-moon", "Übernachtungen (letztes Jahr)",
                     f"{nights_latest:,.0f}".replace(",", " ") if nights_latest else "–", FL_RED), md=4, className="mb-3"),
        dbc.Col(_kpi("fa-euro-sign", "BIP in EUR (letztes Jahr)",
                     f"€ {gdp_latest/1e6:.1f} Mrd.".replace(".", ",") if gdp_latest else "–", FL_GOLD), md=4, className="mb-3"),
    ], className="g-3")

    # ── Arrivals time series ──────────────────────────────────────────────────
    arr_fig = go.Figure()
    if not arr_df.empty:
        arr_fig.add_trace(go.Scatter(
            x=arr_df["year"], y=arr_df["value"],
            mode="lines+markers",
            line=dict(color=FL_BLUE, width=2.5),
            marker=dict(size=6),
            fill="tozeroy", fillcolor=FL_BLUE_13,
            name="Ankünfte",
            hovertemplate="<b>%{x}</b>: %{y:,.0f} Ankünfte<extra></extra>",
        ))
    _styled(arr_fig, f"Touristische Ankünfte in Liechtenstein {y0}–{y1}")
    if not arr_df.empty:
        # Annotate COVID dip
        covid_row = arr_df[arr_df["year"] == 2020]
        if not covid_row.empty:
            arr_fig.add_annotation(
                x=2020, y=covid_row["value"].iloc[0],
                text="COVID-19", showarrow=True, arrowhead=2,
                arrowcolor=FL_RED, font=dict(color=FL_RED, size=11),
                ax=40, ay=-40,
            )
    arr_chart = _card(dcc.Graph(figure=arr_fig, config={"displayModeBar": False})) if arr_fig.data else _empty("Keine Ankunftsdaten.")

    # ── Overnight stays bar chart ─────────────────────────────────────────────
    nights_fig = go.Figure()
    if not nights_df.empty:
        nights_fig.add_trace(go.Bar(
            x=nights_df["year"].astype(str),
            y=nights_df["value"],
            marker_color=[FL_RED if v == nights_df["value"].max() else FL_BLUE for v in nights_df["value"]],
            name="Übernachtungen",
            hovertemplate="<b>%{x}</b>: %{y:,.0f} Nächte<extra></extra>",
        ))
    _styled(nights_fig, f"Übernachtungen {y0}–{y1}", legend=False)
    nights_chart = _card(dcc.Graph(figure=nights_fig, config={"displayModeBar": False})) if nights_fig.data else _empty("Keine Übernachtungsdaten.")

    # ── GDP EUR time series ───────────────────────────────────────────────────
    gdp_eur_fig = go.Figure()
    if not gdp_df.empty:
        gdp_eur_fig.add_trace(go.Scatter(
            x=gdp_df["year"], y=gdp_df["value"] / 1e6,
            mode="lines+markers",
            line=dict(color=FL_GOLD, width=2.5),
            marker=dict(size=6),
            fill="tozeroy", fillcolor="rgba(212,160,23,0.12)",
            name="BIP EUR",
            hovertemplate="<b>%{x}</b>: € %{y:.2f} Mrd.<extra></extra>",
        ))
    _styled(gdp_eur_fig, f"BIP Liechtenstein in EUR (Mrd.) {y0}–{y1}")
    gdp_eur_chart = _card(dcc.Graph(figure=gdp_eur_fig, config={"displayModeBar": False})) if gdp_eur_fig.data else _empty("Keine BIP-Daten.")

    return html.Div([
        html.H4("Tourismus & Wirtschaft – Liechtenstein", className="section-title"),
        kpi_row,
        dbc.Row([
            dbc.Col(arr_chart,     md=12, className="mb-3"),
        ], className="g-3"),
        dbc.Row([
            dbc.Col(nights_chart,  md=6,  className="mb-3"),
            dbc.Col(gdp_eur_chart, md=6,  className="mb-3"),
        ], className="g-3"),
        _source_bar("amtstat", "eurostat", extra="Tourismus- & Wirtschaftsstatistik (Eurostat wo verfügbar)"),
    ])


# ── Run ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=8050)
