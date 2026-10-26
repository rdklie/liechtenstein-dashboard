"""
tab_klima.py — Tab «Klimawandel»
================================
ERA5-Langzeitreihen (ab 1950) je Gemeinde aus der Open-Meteo-Archiv-API: Warming Stripes, Kennzahlen (Hitze-/Sommer-/Frost-/Eis-/Schneefall-/
Starkregentage), Trends (Theil-Sen, Mann-Kendall) und Talgemeinden vs. Berggemeinden. Details und Grenzen: climate.py.
"""

import dash_bootstrap_components as dbc
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import dcc, html

from climate import INDICES, REF_PERIOD, START_YEAR, VALLEY_MAX_ELEV, last_complete_year, trend
from data_fetcher import MUNICIPALITIES
from db import read_clim_annual
from ui import FL_BLUE, FL_RED, FL_GOLD, ACCENT, GREEN, MUTED, TEXT, BORDER, MUNI_PALETTE, _card, _kpi, _styled, _empty

DEFAULT_MUNI = ["vaduz", "triesenberg"]
DEFAULT_INDEX = "hot_days"
INDEX_OPTS = [{"label": v[0], "value": k} for k, v in INDICES.items()]
MUNI_OPTS = [{"label": f"{m['name']} ({m['elev']} m)", "value": k} for k, m in sorted(MUNICIPALITIES.items(), key=lambda kv: kv[1]["elev"])]
OPEN_METEO_URL = "https://open-meteo.com/en/docs/historical-weather-api"
ERA5_URL = "https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels"


def sidebar_section() -> html.Div:
    return html.Div(id="filter-klima2", children=[
        html.Div([
            html.Label("Gemeinden (Zeitreihen)", className="filter-label"),
            dcc.Dropdown(id="kl-muni", options=MUNI_OPTS, value=DEFAULT_MUNI, multi=True, clearable=False, className="fl-dropdown"),
        ], className="filter-section"),
        html.Div([
            html.Label("Kennzahl", className="filter-label"),
            dcc.Dropdown(id="kl-index", options=INDEX_OPTS, value=DEFAULT_INDEX, clearable=False, className="fl-dropdown"),
        ], className="filter-section"),
        html.Div([
            html.Label("Zeitraum für Trends", className="filter-label"),
            dcc.RangeSlider(id="kl-years", min=START_YEAR, max=2025, step=1, value=[START_YEAR, 2025],
                            marks={y: {"label": str(y), "style": {"color": MUTED, "fontSize": "10px"}} for y in range(1950, 2026, 25)},
                            tooltip={"placement": "bottom", "always_visible": True}, className="fl-slider"),
        ], className="filter-section"),
    ])


def _name(k: str) -> str:
    return MUNICIPALITIES[k]["name"]


def _graph(fig, h=360):
    fig.update_layout(height=h)
    return dcc.Graph(figure=fig, config={"displayModeBar": False})


def _note(text, icon="fa-circle-info", color=ACCENT):
    return html.Div([html.I(className=f"fas {icon}", style={"marginRight": "8px", "color": color}), text],
                    style={"color": MUTED, "fontSize": "0.78rem", "padding": "2px 2px 8px"})


def _fmt_p(p):
    if p is None or np.isnan(p):
        return "–"
    return "< 0,001" if p < 0.001 else f"{p:.3f}".replace(".", ",")


def how_to_read() -> html.Div:
    def item(t, x):
        return html.Li([html.B(t + ": ", style={"color": TEXT}), x], style={"marginBottom": "4px"})
    return _card([
        html.H6([html.I(className="fas fa-book-open", style={"marginRight": "8px", "color": ACCENT}), "Wie lesen? Daten, Auflösung und Grenzen"], style={"color": TEXT}),
        html.Ul([
            item("Daten", "Tageswerte der ERA5-Reanalyse (ECMWF/Copernicus) über die Open-Meteo-Archiv-API, ab 1950, für den Koordinatenpunkt jeder Gemeinde. "
                 "Das sind modellierte Werte, keine Messungen einer Wetterstation."),
            item("Auflösung (wichtig)", "ERA5 hat ein Raster von rund 25–30 km; ganz Liechtenstein liegt in 2–3 Rasterzellen. Open-Meteo nennt zu jedem Punkt die Höhe seines "
                 "Höhenmodells (z. B. Triesenberg 1042 m statt der Gemeindehöhe 884 m), und die Temperaturen der Gemeinden unterscheiden sich ungefähr im Mass der "
                 "Höhenunterschiede (etwa 5–6 K pro km). Das spricht für eine Höhenkorrektur der Temperatur durch Open-Meteo. Niederschlag und Schnee gelten als "
                 "Rasterwerte. Die Unterschiede zwischen den Gemeinden sind daher überwiegend Höhenunterschiede, keine lokalen Beobachtungen. "
                 "Die Werte wurden von uns nicht verändert oder nachkorrigiert; in den Tabellen steht die Rasterpunkt-Höhe."),
            item("Referenzperiode", f"Anomalien (Warming Stripes) beziehen sich auf den Mittelwert {REF_PERIOD[0]}–{REF_PERIOD[1]} der jeweiligen Gemeinde "
                 "(WMO-Normalperiode)."),
            item("Kennzahlen", "Hitzetag: Tmax ≥ 30 °C · Sommertag: Tmax ≥ 25 °C · Frosttag: Tmin < 0 °C · Eistag: Tmax < 0 °C · Schneefalltag: Schneefall ≥ 1 cm · "
                 "Starkregentag: Niederschlag ≥ 20 mm/Tag. Gezählt werden Kalendertage; nur vollständige Jahre (≥ 360 gültige Tage)."),
            item("Trends", "Steigung nach Theil-Sen (Median aller Paarsteigungen, robust gegen Ausreisser) je Jahrzehnt; Signifikanz mit dem Mann-Kendall-Test "
                 "(zweiseitig, p < 0,05 = «signifikant»). Bei vielen Gemeinden/Kennzahlen entstehen zufällig auch einzelne «signifikante» Trends; "
                 "die Gemeinden liegen im selben Raster und sind keine unabhängigen Stichproben."),
            item("Grenzen", "Reanalysen können vor ca. 1970 (wenige Beobachtungen) Unsicherheiten haben; Schnee- und Starkregenwerte sind besonders "
                 "modellabhängig. Das laufende Jahr fehlt (unvollständig)."),
        ], style={"color": MUTED, "fontSize": "0.8rem", "paddingLeft": "18px", "marginBottom": "0"}),
    ])


def _anomaly(a: pd.DataFrame) -> pd.DataFrame:
    ref = a[(a["year"] >= REF_PERIOD[0]) & (a["year"] <= REF_PERIOD[1])].groupby("muni")["tmean"].mean().rename("ref")
    a = a.join(ref, on="muni")
    a["anom"] = a["tmean"] - a["ref"]
    return a


def _valley(muni: str) -> bool:
    return MUNICIPALITIES[muni]["elev"] < VALLEY_MAX_ELEV


def render_klima(data: dict) -> html.Div:
    a = read_clim_annual()
    if a.empty:
        return html.Div([html.H4("Klimawandel je Gemeinde", className="section-title"), how_to_read(),
                         _empty("Die Langzeitdaten werden gerade geladen (Open-Meteo, einmalige Ladung 1950–Vorjahr, mehrere Abrufe mit Pause). Bitte später erneut öffnen.")])
    a = _anomaly(a)
    munis = [m for m in (data.get("kl_muni") or DEFAULT_MUNI) if m in MUNICIPALITIES] or DEFAULT_MUNI
    idx = data.get("kl_index") or DEFAULT_INDEX
    y0, y1 = data.get("kl_years") or [START_YEAR, 2025]
    label, unit = INDICES[idx]
    n_have = a.groupby("muni")["year"].nunique()
    n_total = len(MUNICIPALITIES) * (last_complete_year() - START_YEAR + 1)
    incomplete = len(a) < n_total
    out = [how_to_read()]
    if incomplete:
        out.append(html.Div(style={"height": "8px"}))
        out.append(_note(f"Ladestand: {len(a)} von {n_total} Gemeinde-Jahren (Open-Meteo-Ladung läuft/wird ergänzt; fehlende Jahre/Gemeinden bleiben leer, es wird nichts geschätzt).",
                         "fa-triangle-exclamation", FL_GOLD))

    # KPIs
    first = munis[0]
    s = a[a["muni"] == first].sort_values("year")
    kp = []
    if len(s) >= 10:
        t = trend(s["year"].values, s["tmean"].values)
        kp.append(dbc.Col(_kpi("fa-temperature-arrow-up", f"{_name(first)}: Trend Jahresmittel", f"{t['slope_decade']:+.2f} °C/Jz".replace(".", ","), FL_RED,
                               f"{s['year'].min()}–{s['year'].max()}, p {_fmt_p(t['p'])}"), md=3, sm=6, className="mb-3"))
        last10 = s[s["year"] > s["year"].max() - 10]["anom"].mean()
        kp.append(dbc.Col(_kpi("fa-fire", f"{_name(first)}: Ø letzte 10 Jahre", f"{last10:+.1f} °C".replace(".", ","), FL_GOLD,
                               f"gegenüber Mittel {REF_PERIOD[0]}–{REF_PERIOD[1]}"), md=3, sm=6, className="mb-3"))
        early = s[(s["year"] >= 1950) & (s["year"] <= 1979)]["hot_days"].mean()
        late = s[s["year"] >= s["year"].max() - 29]["hot_days"].mean()
        kp.append(dbc.Col(_kpi("fa-sun", "Hitzetage pro Jahr", f"{late:.1f} ({early:.1f})".replace(".", ","), FL_BLUE,
                               f"Ø letzte 30 Jahre (Klammer: 1950–1979), {_name(first)}"), md=3, sm=6, className="mb-3"))
        fr_e = s[(s["year"] >= 1950) & (s["year"] <= 1979)]["frost_days"].mean()
        fr_l = s[s["year"] >= s["year"].max() - 29]["frost_days"].mean()
        kp.append(dbc.Col(_kpi("fa-snowflake", "Frosttage pro Jahr", f"{fr_l:.0f} ({fr_e:.0f})", ACCENT,
                               f"Ø letzte 30 Jahre (Klammer: 1950–1979), {_name(first)}"), md=3, sm=6, className="mb-3"))
    out.append(dbc.Row(kp, className="g-3"))

    # Warming stripes: alle Gemeinden nach Höhe
    order = sorted(MUNICIPALITIES, key=lambda k: -MUNICIPALITIES[k]["elev"])
    pv = a.pivot_table(index="muni", columns="year", values="anom").reindex([k for k in order if k in set(a["muni"])])
    fig = go.Figure(go.Heatmap(z=pv.values, x=pv.columns, y=[f"{_name(k)} ({MUNICIPALITIES[k]['elev']} m)" for k in pv.index],
                               colorscale="RdBu_r", zmin=-2.5, zmax=2.5, xgap=0,
                               colorbar=dict(title=dict(text="°C", font=dict(color=TEXT)), tickfont=dict(color=TEXT)),
                               hovertemplate="<b>%{y}</b> %{x}: %{z:+.2f} °C vs. Referenz<extra></extra>"))
    _styled(fig, f"Warming Stripes: Jahresmitteltemperatur, Abweichung vom Mittel {REF_PERIOD[0]}–{REF_PERIOD[1]}", legend=False)
    fig.update_layout(hovermode="closest", margin=dict(l=150, r=20, t=50, b=40))
    fig.update_xaxes(tickformat="d")
    out.append(_card(_graph(fig, 120 + 38 * len(pv))))
    sel = a[a["muni"] == first].sort_values("year")
    if not sel.empty:
        f2 = go.Figure(go.Bar(x=sel["year"], y=[1] * len(sel), marker=dict(color=sel["anom"], colorscale="RdBu_r", cmin=-2.5, cmax=2.5, line=dict(width=0)),
                              customdata=sel["anom"], hovertemplate="%{x}: %{customdata:+.2f} °C<extra></extra>"))
        _styled(f2, f"Warming Stripes {_name(first)}", legend=False)
        f2.update_layout(bargap=0, yaxis=dict(visible=False), hovermode="closest", margin=dict(l=20, r=20, t=50, b=40))
        f2.update_xaxes(tickformat="d")
        out.append(_card(_graph(f2, 200)))
    out.append(_note("Jeder Streifen ist ein Jahr; Blau = kühler, Rot = wärmer als das Mittel 1991–2020 der jeweiligen Gemeinde. Die Streifen aller Gemeinden "
                     "sehen ähnlich aus, weil sie aus denselben 2–3 ERA5-Rasterzellen stammen."))

    # Kennzahl-Zeitreihe + Trend
    f3 = go.Figure()
    rows = []
    for i, k in enumerate(munis):
        d = a[(a["muni"] == k) & (a["year"] >= y0) & (a["year"] <= y1)].sort_values("year")
        if d.empty:
            continue
        col = MUNI_PALETTE[i % len(MUNI_PALETTE)]
        f3.add_trace(go.Scatter(x=d["year"], y=d[idx], mode="lines+markers", name=_name(k), line=dict(color=col, width=2), marker=dict(size=4),
                                hovertemplate=f"<b>{_name(k)}</b> %{{x}}: %{{y:,.1f}} {unit}<extra></extra>"))
        t = trend(d["year"].values, d[idx].values)
        if not np.isnan(t["slope_decade"]):
            xs = np.array([d["year"].min(), d["year"].max()])
            f3.add_trace(go.Scatter(x=xs, y=t["intercept"] + t["slope_decade"] / 10 * xs, mode="lines", line=dict(color=col, dash="dash", width=1.5),
                                    showlegend=False, hoverinfo="skip"))
    _styled(f3, f"{label}: Jahreswerte und Theil-Sen-Trend ({y0}–{y1})")
    f3.update_yaxes(title=unit)
    f3.update_xaxes(tickformat="d")
    out.append(_card(_graph(f3, 400)) if f3.data else _empty("Keine Daten im gewählten Zeitraum."))

    # Trendtabelle alle Gemeinden
    body = []
    for k in sorted(MUNICIPALITIES, key=lambda k: MUNICIPALITIES[k]["elev"]):
        d = a[(a["muni"] == k) & (a["year"] >= y0) & (a["year"] <= y1)].sort_values("year")
        if d.empty:
            continue
        t = trend(d["year"].values, d[idx].values)
        sig = (not np.isnan(t["p"])) and t["p"] < 0.05
        body.append(html.Tr([html.Td(_name(k)), html.Td(f"{MUNICIPALITIES[k]['elev']} m"), html.Td(f"{d['elevation'].iloc[0]:.0f} m"),
                             html.Td(f"{t['slope_decade']:+.2f} {unit}/Jz".replace(".", ",") if not np.isnan(t["slope_decade"]) else "–"),
                             html.Td(_fmt_p(t["p"])), html.Td("ja" if sig else "nein", style={"color": GREEN if sig else MUTED}), html.Td(str(t["n"]))]))
    out.append(_card([
        html.H6(f"Trends aller Gemeinden: {label} ({y0}–{y1})", style={"color": TEXT}),
        html.Div(html.Table([html.Thead(html.Tr([html.Th(h) for h in ("Gemeinde", "Höhe Gemeinde", "Höhe Rasterpunkt (Open-Meteo)", "Steigung (Theil-Sen)", "p (Mann-Kendall)", "p < 0,05", "Jahre")])),
                             html.Tbody(body)], className="od-table"), style={"overflowX": "auto"}),
        _note("Steigung in Einheiten pro Jahrzehnt (Jz). Gemeinden teilen sich Rasterzellen — die Trends sind nicht unabhängig.")]))

    # Tal vs Berg
    valley = [k for k in MUNICIPALITIES if _valley(k)]
    mount = [k for k in MUNICIPALITIES if not _valley(k)]
    g = a.assign(group=a["muni"].map(lambda k: "Talgemeinden" if _valley(k) else "Berggemeinden"))
    gm = g.groupby(["group", "year"])[idx].mean().reset_index()
    f4 = go.Figure()
    for grp, col in (("Talgemeinden", FL_BLUE), ("Berggemeinden", FL_RED)):
        d = gm[(gm["group"] == grp) & (gm["year"] >= y0) & (gm["year"] <= y1)]
        if not d.empty:
            f4.add_trace(go.Scatter(x=d["year"], y=d[idx], mode="lines", name=grp, line=dict(color=col, width=2.4)))
    _styled(f4, f"{label}: Talgemeinden vs. Berggemeinden (Gruppenmittel)")
    f4.update_yaxes(title=unit)
    f4.update_xaxes(tickformat="d")
    trows = []
    for key in ("tmean", "frost_days", "ice_days", "snow_days", "hot_days", "heavy_rain_days"):
        cells = [html.Td(INDICES[key][0])]
        for grp in ("Talgemeinden", "Berggemeinden"):
            d = gm_for(a, key, grp, y0, y1)
            t = trend(d["year"].values, d[key].values) if len(d) else {"slope_decade": np.nan, "p": np.nan}
            cells.append(html.Td("–" if np.isnan(t["slope_decade"]) else f"{t['slope_decade']:+.2f} (p {_fmt_p(t['p'])})".replace(".", ",")))
        mean_diff = (gm_for(a, key, "Berggemeinden", y0, y1)[key].mean() - gm_for(a, key, "Talgemeinden", y0, y1)[key].mean())
        cells.append(html.Td("–" if np.isnan(mean_diff) else f"{mean_diff:+.1f}".replace(".", ",")))
        trows.append(html.Tr(cells))
    out.append(dbc.Row([
        dbc.Col(_card(_graph(f4, 380)), md=7, className="mb-3"),
        dbc.Col(_card([html.H6("Trend je Jahrzehnt", style={"color": TEXT}),
                       html.Table([html.Thead(html.Tr([html.Th(h) for h in ("Kennzahl", "Tal", "Berg", "Berg − Tal Ø")])), html.Tbody(trows)], className="od-table"),
                       _note(f"Tal = Gemeindehöhe < {VALLEY_MAX_ELEV} m ({len(valley)} Gemeinden), Berg = Triesenberg, Planken ({len(mount)}). "
                             "Der Höhenunterschied wirkt direkt auf Frost-/Eis-/Schneetage; ob die Trends in den Berggemeinden stärker sind, "
                             "hängt von der ERA5-Höhenkorrektur ab und ist keine Messung.")]), md=5, className="mb-3")], className="g-3"))

    st = f"Daten bis {int(a['year'].max())}"
    out.append(html.Div([
        html.I(className="fas fa-database", style={"marginRight": "6px", "color": MUTED}), html.Span("Quelle: ", style={"color": MUTED}),
        html.A("Open-Meteo Historical Weather API", href=OPEN_METEO_URL, target="_blank", rel="noopener noreferrer", className="source-link"),
        html.Span(" (Weather data by Open-Meteo.com, CC BY 4.0) · Modell ", style={"color": MUTED}),
        html.A("ERA5, ECMWF/Copernicus", href=ERA5_URL, target="_blank", rel="noopener noreferrer", className="source-link"),
        html.Span(f" (CC BY 4.0) · {st} · Rohdaten im Archiv, jährliche Ergänzung", style={"color": MUTED})], className="source-bar"))
    return html.Div([html.H4("Klimawandel je Gemeinde – ERA5, 1950 bis heute", className="section-title"), *out])


def gm_for(a: pd.DataFrame, key: str, grp: str, y0: int, y1: int) -> pd.DataFrame:
    members = [k for k in MUNICIPALITIES if (grp == "Talgemeinden") == _valley(k)]
    d = a[a["muni"].isin(members) & (a["year"] >= y0) & (a["year"] <= y1)]
    return d.groupby("year")[key].mean().reset_index()
