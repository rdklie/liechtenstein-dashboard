"""
tab_opendata.py — Tab «Open Data»
=================================
Daten-Explorer für den Katalog von opendata.li (Amt für Statistik, ~460 PXWeb-Tabellen):
Tabelle wählen → Achsen/Filter → Diagramm + Datenvorschau + CSV-Download.

Der Katalog (od_catalog) kommt aus dem wöchentlichen Discovery-Crawler (discover.py), die
Tabellendaten aus SQLite (px_cache). Nur wenn eine Tabelle dort fehlt oder älter als 7 Tage ist,
wird sie beim Aufruf einmalig live von der PXWeb-API nachgeladen und gespeichert.
Lizenz: Namensnennung (CC BY) — Quelle: Amt für Statistik Liechtenstein, opendata.li.
"""

import logging
from datetime import datetime

import dash_bootstrap_components as dbc
import pandas as pd
import plotly.graph_objects as go
from dash import ALL, Input, Output, State, callback, ctx, dcc, html, no_update

from db import get_px, read_catalog, read_discovery_log
from opendata import LICENSE_TEXT, PORTAL_URL, SOURCE_TEXT, is_time_dim, px_web_url
from ui import FL_BLUE, FL_RED, FL_GOLD, ACCENT, GREEN, MUTED, TEXT, BORDER, MUNI_PALETTE, _card, _kpi, _styled, _empty

log = logging.getLogger(__name__)

DEFAULT_TABLE_ID = "391.133"          # Wohnungen nach Gemeinde seit 1980
NO_GROUP = "(keine)"
MAX_SERIES = 10
PREVIEW_ROWS = 40


# ── Katalog-Helfer ────────────────────────────────────────────────────────────

def _px_catalog() -> pd.DataFrame:
    cat = read_catalog()
    if cat.empty:
        return cat
    return cat[(cat["kind"] == "px") & (cat["px_path"] != "")].copy()


def _table_options(cat: pd.DataFrame, theme: str | None) -> list[dict]:
    if cat.empty:
        return []
    if theme and theme != "Alle":
        cat = cat[cat["theme"] == theme]
    cat = cat.sort_values(["theme", "subtheme", "key"])
    return [{"label": f"{r.key} · {r.title}", "value": r.px_path, "search": f"{r.key} {r.title} {r.subtheme}"}
            for r in cat.itertuples()]


def _default_path(cat: pd.DataFrame) -> str | None:
    if cat.empty:
        return None
    hit = cat[cat["key"] == DEFAULT_TABLE_ID]
    return (hit if not hit.empty else cat).iloc[0]["px_path"]


# ── Layout ────────────────────────────────────────────────────────────────────

def render_opendata() -> html.Div:
    cat_all = read_catalog()
    cat = _px_catalog()
    if cat_all.empty:
        return html.Div([
            html.H4("Open Data – opendata.li", className="section-title"),
            _empty("Der Katalog ist noch nicht geladen — der wöchentliche Discovery-Lauf (discover.py) füllt ihn."),
        ])

    n_px, n_other = len(cat), len(cat_all) - len(cat)
    last_seen = cat_all["last_seen"].max()
    log_df = read_discovery_log(200)
    last_run = log_df["run_at"].max() if not log_df.empty else None
    n_events = int((log_df["run_at"] == last_run).sum()) if last_run else 0

    kpis = dbc.Row([
        dbc.Col(_kpi("fa-table", "Statistik-Tabellen (PXWeb)", f"{n_px}", FL_BLUE, "Amt für Statistik"), md=3, sm=6, className="mb-3"),
        dbc.Col(_kpi("fa-map", "Geodaten & Dateien", f"{n_other}", FL_RED, "WMS, ZIP, CSV/JSON"), md=3, sm=6, className="mb-3"),
        dbc.Col(_kpi("fa-rotate", "Katalog-Abgleich", last_seen or "–", FL_GOLD, "wöchentlich (Discovery)"), md=3, sm=6, className="mb-3"),
        dbc.Col(_kpi("fa-bell", "Funde im letzten Lauf", f"{n_events}" if last_run else "–", GREEN,
                     "neu / geändert / entfernt" if last_run else "noch kein Vergleich"), md=3, sm=6, className="mb-3"),
    ], className="g-3")

    themes = ["Alle"] + sorted(t for t in cat["theme"].unique() if t)
    default_path = _default_path(cat)

    explorer = _card([
        html.H6("Daten-Explorer", style={"color": TEXT, "marginBottom": "12px"}),
        dbc.Row([
            dbc.Col([
                html.Label("Thema", className="filter-label"),
                dcc.Dropdown(id="od-theme", options=themes, value="Alle", clearable=False, className="fl-dropdown"),
            ], md=4),
            dbc.Col([
                html.Label("Tabelle (Suche nach Titel oder Nummer)", className="filter-label"),
                dcc.Dropdown(id="od-table", options=_table_options(cat, "Alle"), value=default_path,
                             clearable=False, searchable=True, className="fl-dropdown", optionHeight=44),
            ], md=8),
        ], className="g-3 mb-3"),
        dbc.Row([
            dbc.Col([html.Label("X-Achse", className="filter-label"),
                     dcc.Dropdown(id="od-x", clearable=False, className="fl-dropdown")], md=4),
            dbc.Col([html.Label("Gruppierung (Linien/Balken)", className="filter-label"),
                     dcc.Dropdown(id="od-group", clearable=False, className="fl-dropdown")], md=4),
            dbc.Col([html.Label(" ", className="filter-label"),
                     html.Div(html.Button([html.I(className="fas fa-download", style={"marginRight": "6px"}), "CSV"],
                                          id="od-download-btn", className="copy-btn",
                                          style={"width": "auto", "padding": "6px 14px"}))], md=4),
        ], className="g-3 mb-2"),
        html.Div(id="od-filters", className="mb-2"),
        dcc.Loading(html.Div(id="od-output"), type="dot", color=ACCENT),
        dcc.Download(id="od-download"),
    ])

    # Weitere Datensätze (Geodaten, Dateien): Link-Liste
    other = cat_all[cat_all["kind"] != "px"].sort_values(["kind", "title"])
    rows = []
    for r in other.itertuples():
        link = r.landing_url or r.catalog_url
        rows.append(html.Tr([
            html.Td(r.kind), html.Td(html.A(r.title, href=link, target="_blank", rel="noopener noreferrer",
                                            className="source-link") if link else r.title),
            html.Td(r.formats), html.Td(r.modified or "–"),
        ]))
    other_card = _card([
        html.H6(f"Weitere Datensätze im Katalog ({len(other)})", style={"color": TEXT}),
        html.P("Geodaten (WMS, Shapefiles), Karten und Dateien — nicht als Diagramm darstellbar, aber verlinkt.",
               style={"color": MUTED, "fontSize": "0.8rem"}),
        html.Div(html.Table([html.Thead(html.Tr([html.Th(h) for h in ("Art", "Titel", "Formate", "Geändert")])),
                             html.Tbody(rows)], className="od-table"),
                 style={"maxHeight": "320px", "overflowY": "auto"}),
    ])

    # Discovery-Funde (nur Hinweise)
    disc_rows = []
    if not log_df.empty:
        for r in log_df[log_df["run_at"] == last_run].head(30).itertuples():
            disc_rows.append(html.Tr([html.Td(r.event), html.Td(f"{r.ref}"), html.Td(r.title), html.Td(r.detail)]))
    disc_card = _card([
        html.H6("Discovery-Crawler: Funde des letzten Laufs", style={"color": TEXT}),
        html.P("Der Crawler prüft wöchentlich Katalog und PXWeb-Baum und meldet Neues. Er veröffentlicht nichts "
               "automatisch — neue Datensätze erscheinen im Explorer, kuratierte Tabs bleiben manuell.",
               style={"color": MUTED, "fontSize": "0.8rem"}),
        html.Div(html.Table([html.Thead(html.Tr([html.Th(h) for h in ("Ereignis", "Nr.", "Titel", "Detail")])),
                             html.Tbody(disc_rows)], className="od-table")) if disc_rows
        else html.P(f"Keine Änderungen seit dem vorherigen Lauf ({last_run or 'noch kein Lauf'}).",
                    style={"color": MUTED, "fontSize": "0.85rem"}),
    ])

    src = html.Div([
        html.I(className="fas fa-database", style={"marginRight": "6px", "color": MUTED}),
        html.Span("Quelle: ", style={"color": MUTED}),
        html.A("opendata.li", href=PORTAL_URL, target="_blank", rel="noopener noreferrer", className="source-link"),
        html.Span(f" · {SOURCE_TEXT} · Lizenz: {LICENSE_TEXT}", style={"color": MUTED}),
    ], className="source-bar")

    return html.Div([
        html.H4("Open Data – opendata.li", className="section-title"),
        kpis, explorer,
        html.Div(style={"height": "16px"}),
        dbc.Row([dbc.Col(disc_card, md=6), dbc.Col(other_card, md=6)], className="g-3 mb-3"),
        src,
    ])


# ── Callbacks ─────────────────────────────────────────────────────────────────

@callback(Output("od-table", "options"), Output("od-table", "value"),
          Input("od-theme", "value"), State("od-table", "value"), prevent_initial_call=True)
def _tables_for_theme(theme, current):
    cat = _px_catalog()
    opts = _table_options(cat, theme)
    values = {o["value"] for o in opts}
    if current in values:
        return opts, no_update
    return opts, (opts[0]["value"] if opts else None)


def _pick_defaults(df: pd.DataFrame, dims: list[str]) -> tuple[str, str]:
    x = next((d for d in dims if is_time_dim(d)), dims[0])
    others = [d for d in dims if d != x]
    group = NO_GROUP
    for d in others:
        if d in ("Gemeinde", "Wohngemeinde"):
            group = d
            break
    else:
        for d in others:
            if 2 <= df[d].nunique() <= 12:
                group = d
                break
    return x, group


@callback(Output("od-x", "options"), Output("od-x", "value"),
          Output("od-group", "options"), Output("od-group", "value"),
          Input("od-table", "value"))
def _table_changed(path):
    if not path:
        return [], None, [], None
    df, info = get_px(path, allow_live=True)
    dims = [c for c in df.columns if c != "Wert"] if not df.empty else []
    if not dims:
        return [], None, [], None
    x, group = _pick_defaults(df, dims)
    return dims, x, [NO_GROUP] + dims, group


@callback(Output("od-filters", "children"),
          Input("od-table", "value"), Input("od-x", "value"), Input("od-group", "value"))
def _filter_controls(path, x, group):
    """Je übrige Dimension ein Dropdown (Standard: erster Wert, meist «Total»)."""
    if not path or not x:
        return []
    df, _ = get_px(path)
    if df.empty or x not in df.columns:
        return []
    rest = [c for c in df.columns if c not in ("Wert", x, group)]
    ctrls = []
    have = df.dropna(subset=["Wert"])
    for d in rest:
        vals = list(dict.fromkeys(df[d]))
        # Standard: erster Wert mit den meisten Datenpunkten (meist «Total»; leere Kombinationen vermeiden)
        counts = have.groupby(d).size()
        best = counts.max() if not counts.empty else 0
        default = next((v for v in vals if counts.get(v, 0) == best), vals[0])
        ctrls.append(dbc.Col([
            html.Label(d, className="filter-label"),
            dcc.Dropdown(id={"type": "od-flt", "dim": d}, options=vals, value=default, clearable=False,
                         className="fl-dropdown", optionHeight=40),
        ], md=4, className="mb-2"))
    return dbc.Row(ctrls, className="g-3") if ctrls else []


def _order_x(values: list[str]) -> list[str]:
    """Zeitachsen sortieren (Jahr, Quartal '2015-Q1', Stichtag 'dd.mm.yyyy'); sonst Reihenfolge der Daten."""
    vals = list(dict.fromkeys(values))
    try:
        return sorted(vals, key=lambda v: float(str(v).replace("/", ".")))
    except ValueError:
        pass
    try:
        return sorted(vals, key=lambda v: datetime.strptime(v, "%d.%m.%Y"))
    except ValueError:
        pass
    if all(isinstance(v, str) and v[:4].isdigit() for v in vals):
        return sorted(vals)
    return vals


def _figure(sub: pd.DataFrame, info: dict, x: str, group: str) -> go.Figure:
    unit = info.get("unit") or "Wert"
    use_group = group and group != NO_GROUP and group != x and group in sub.columns
    fig = go.Figure()
    xs = _order_x(sub[x].tolist())
    as_lines = is_time_dim(x)
    numeric_x = all(str(v).isdigit() for v in xs)          # Jahre → echte Zahlenachse
    xvals = [int(v) for v in xs] if numeric_x else xs
    if use_group:
        series = sub.groupby(group, sort=False)["Wert"].mean().sort_values(ascending=False)
        names = list(series.index[:MAX_SERIES])
    else:
        names = [None]
    for i, name in enumerate(names):
        d = sub if name is None else sub[sub[group] == name]
        d = d.groupby(x, sort=False)["Wert"].sum(min_count=1).reindex(xs)
        col = MUNI_PALETTE[i % len(MUNI_PALETTE)] if name is not None else FL_BLUE
        label = str(name if name is not None else unit)
        if as_lines:
            fig.add_trace(go.Scatter(x=xvals, y=d.values, mode="lines+markers", name=label,
                                     line=dict(color=col, width=2.5), connectgaps=False,
                                     hovertemplate="%{x}: %{y:,.2f}<extra>" + label + "</extra>"))
        else:
            fig.add_trace(go.Bar(x=xvals, y=d.values, name=label, marker_color=col,
                                 hovertemplate="%{x}: %{y:,.2f}<extra>" + label + "</extra>"))
    _styled(fig, info.get("title", ""), legend=use_group)
    fig.update_layout(barmode="group", height=420, yaxis_title=unit)
    if numeric_x:
        fig.update_xaxes(type="linear", tickformat="d", gridcolor=BORDER)
    else:
        fig.update_xaxes(type="category", gridcolor=BORDER)
    if use_group and len(series) > MAX_SERIES:
        fig.add_annotation(text=f"Es werden die {MAX_SERIES} grössten von {len(series)} Gruppen gezeigt",
                           xref="paper", yref="paper", x=1, y=1.12, showarrow=False,
                           font=dict(color=MUTED, size=11))
    return fig


def _preview(sub: pd.DataFrame) -> html.Div:
    head = sub.head(PREVIEW_ROWS)
    cols = list(head.columns)
    body = [html.Tr([html.Td("" if pd.isna(v) else (f"{v:,.2f}".rstrip("0").rstrip(".") if isinstance(v, float) else str(v)))
                     for v in row]) for row in head.itertuples(index=False)]
    return html.Div(html.Table([html.Thead(html.Tr([html.Th(c) for c in cols])), html.Tbody(body)],
                               className="od-table"),
                    style={"maxHeight": "300px", "overflowY": "auto"})


@callback(Output("od-output", "children"),
          Input("od-table", "value"), Input("od-x", "value"), Input("od-group", "value"),
          Input({"type": "od-flt", "dim": ALL}, "value"), State({"type": "od-flt", "dim": ALL}, "id"))
def _render_table(path, x, group, flt_values, flt_ids):
    if not path or not x:
        return _empty("Tabelle wählen.")
    df, info = get_px(path, allow_live=True)
    if df.empty:
        return _empty("Tabelle konnte nicht geladen werden (PXWeb nicht erreichbar?).")
    if x not in df.columns:
        return no_update  # Zwischenzustand beim Tabellenwechsel
    sub = df
    for fid, val in zip(flt_ids, flt_values):
        d = fid["dim"]
        if d in sub.columns and d not in (x, group) and val is not None:
            sub = sub[sub[d] == val]
    if sub.dropna(subset=["Wert"]).empty:
        return _empty("Für diese Auswahl gibt es keine Werte (Filter ändern).")

    fig = _figure(sub, info, x, group)
    fetched = info.get("fetched_at")
    stand = f" · Stand der Daten: {fetched:%d.%m.%Y}" if fetched else ""
    notes = []
    if info.get("reduced"):
        notes.append(html.P("Die Tabelle ist gross; für diese Ansicht wurden Dimensionen auf den ersten Wert "
                            f"(meist «Total») reduziert: {', '.join(info['reduced'])}. Vollständig auf opendata.li/PXWeb.",
                            style={"color": FL_GOLD, "fontSize": "0.8rem"}))
    link = html.Div([
        html.I(className="fas fa-database", style={"marginRight": "6px", "color": MUTED}),
        html.Span("Quelle: ", style={"color": MUTED}),
        html.A("PXWeb-Tabelle beim Amt für Statistik", href=px_web_url(path), target="_blank",
               rel="noopener noreferrer", className="source-link"),
        html.Span(f" · {SOURCE_TEXT} · Lizenz: {LICENSE_TEXT}{stand}", style={"color": MUTED}),
    ], className="source-bar")
    return html.Div([
        dcc.Graph(figure=fig, config={"displayModeBar": False}),
        *notes,
        html.H6("Datenvorschau (gefilterte Auswahl)", style={"color": TEXT, "fontSize": "0.85rem", "marginTop": "8px"}),
        _preview(sub), link,
    ])


@callback(Output("od-download", "data"), Input("od-download-btn", "n_clicks"),
          State("od-table", "value"), prevent_initial_call=True)
def _download(n, path):
    if not n or not path:
        return no_update
    df, info = get_px(path)
    if df.empty:
        return no_update
    name = path.rsplit("/", 1)[-1].replace(".px", "")
    return dcc.send_data_frame(df.to_csv, f"opendata-li-{name}.csv", index=False, sep=";")
