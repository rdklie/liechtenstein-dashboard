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
from dash import ALL, Input, Output, State, callback, clientside_callback, ctx, dcc, html, no_update

from db import get_px, read_catalog, read_discovery_log, read_orgs
from imf import SDMX_FLOWS, SDMX_PREFIX, TERMS_URL_IMF
from opendata import FILE_PREFIX, LICENSE_TEXT, PORTAL_URL, SOURCE_TEXT, is_time_dim, px_web_url
from ui import FL_BLUE, FL_RED, FL_GOLD, ACCENT, GREEN, MUTED, TEXT, BORDER, MUNI_PALETTE, _card, _kpi, _styled, _empty

log = logging.getLogger(__name__)

DEFAULT_TABLE_ID = "391.133"          # Wohnungen nach Gemeinde seit 1980
NO_GROUP = "(keine)"
MAX_SERIES = 10
PREVIEW_ROWS = 40


# ── Katalog-Helfer ────────────────────────────────────────────────────────────

ALLE = "Alle"
KIND_LABELS = {"px": "Statistik-Tabelle", "geo": "Geodaten", "file": "Datei", "other": "Sonstiges", "imf": "IWF-Datenfluss"}
IMF_PUBLISHER = "Internationaler Währungsfonds (IWF)"
IMF_PORTAL = "https://data.imf.org/"
LIST_LIMIT = 80


def _explore_id(r) -> str:
    """Kennung für den Explorer: PXWeb-Pfad, «file:<URL>» (CSV/JSON) oder «imf:<Fluss>»; leer = nicht darstellbar."""
    if r["kind"] == "px" and r["px_path"]:
        return r["px_path"]
    if r["kind"] == "imf":
        return r["px_path"]
    if r.get("data_url") and r.get("data_format") in ("csv", "json"):
        return FILE_PREFIX + r["data_url"]
    return ""


def _catalog_all() -> pd.DataFrame:
    """Katalog von opendata.li plus die IWF-SDMX-Datenflüsse (als Pseudo-Einträge) mit Spalte explore_id."""
    cat = read_catalog()
    if cat.empty:
        return cat
    for col in ("publisher", "data_url", "data_format"):
        if col not in cat.columns:
            cat[col] = ""
    cat["publisher"] = cat["publisher"].fillna("Nicht zuordenbar")
    imf_rows = pd.DataFrame([{
        "key": f"IWF {fid}", "title": f"{name} — Liechtenstein", "description": "", "modified": "", "kind": "imf",
        "px_path": SDMX_PREFIX + flow, "formats": "json", "license": "IMF Terms", "landing_url": IMF_PORTAL,
        "catalog_url": IMF_PORTAL, "theme": "", "subtheme": "IWF", "publisher": IMF_PUBLISHER,
        "publisher_source": "extern (IWF SDMX-API)", "data_url": "", "data_format": "",
        "first_seen": "", "last_seen": "",
    } for flow, name in SDMX_FLOWS.items() for fid in [flow.split("/")[1]]])
    cat = pd.concat([cat, imf_rows], ignore_index=True)
    cat["explore_id"] = [_explore_id(r) for r in cat.to_dict("records")]
    return cat


def _px_catalog() -> pd.DataFrame:
    """Alle im Explorer darstellbaren Einträge (PXWeb, CSV/JSON, IWF)."""
    cat = _catalog_all()
    if cat.empty:
        return cat
    return cat[cat["explore_id"] != ""].copy()


def _publisher_counts(cat_all: pd.DataFrame) -> list[tuple[str, int]]:
    """Datensätze je Amtsstelle (auch Ämter ohne Datensätze, sofern der Katalog sie als Organisation führt)."""
    counts = cat_all["publisher"].fillna("Nicht zuordenbar").value_counts().to_dict() if "publisher" in cat_all else {}
    orgs = read_orgs()
    for name in (orgs["name"] if not orgs.empty else []):
        counts.setdefault(name, 0)
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


def _org_options(cat_all: pd.DataFrame) -> list[dict]:
    pubs = _publisher_counts(cat_all)
    return [{"label": f"Alle Amtsstellen ({len(cat_all)})", "value": ALLE}] + \
           [{"label": f"{name} ({n})", "value": name} for name, n in pubs]


def _filter_catalog(cat_all: pd.DataFrame, org: str | None, kind: str | None, theme: str | None,
                    query: str | None) -> pd.DataFrame:
    """Alle Filter kombinierbar: Amtsstelle, Art, Thema (nur Statistik-Tabellen haben eins), Suchtext."""
    d = cat_all
    if org and org != ALLE:
        d = d[d["publisher"] == org]
    if kind and kind != ALLE:
        d = d[d["kind"] == kind]
    if theme and theme != ALLE:
        d = d[d["theme"] == theme]
    if query and query.strip():
        for word in query.lower().split():
            hay = (d["key"].fillna("") + " " + d["title"].fillna("") + " " + d["description"].fillna("") + " "
                   + d["subtheme"].fillna("") + " " + d["formats"].fillna(""))
            d = d[hay.str.lower().str.contains(word, regex=False)]
    return d


def _table_options(cat: pd.DataFrame) -> list[dict]:
    """Optionen des Tabellen-Dropdowns: alle darstellbaren Einträge (PXWeb, CSV/JSON, IWF) des gefilterten Katalogs."""
    cat = cat[cat["explore_id"] != ""]
    if cat.empty:
        return []
    cat = cat.sort_values(["kind", "theme", "subtheme", "key"])
    prefix = {"px": "", "file": "[Datei] ", "imf": "[IWF] "}
    def name(r):
        key = r.key if len(str(r.key)) <= 16 else ""          # lange Hash-Kennungen weglassen
        return f"{prefix.get(r.kind, '')}{key + ' · ' if key else ''}{r.title}"

    return [{"label": name(r), "value": r.explore_id,
             "search": f"{r.key} {r.title} {r.subtheme} {r.publisher}"} for r in cat.itertuples()]


def _default_path(cat: pd.DataFrame) -> str | None:
    if cat.empty:
        return None
    hit = cat[cat["key"] == DEFAULT_TABLE_ID]
    return (hit if not hit.empty else cat).iloc[0]["explore_id"]


def _catalog_list(d: pd.DataFrame) -> html.Div:
    """Trefferliste (alle Arten); Statistik-Tabellen haben einen «öffnen»-Knopf für den Explorer."""
    if d.empty:
        return html.P("Keine Datensätze für diese Filterkombination.", style={"color": MUTED, "fontSize": "0.85rem"})
    d = d.sort_values(["publisher", "kind", "title"])
    rows = []
    for r in d.head(LIST_LIMIT).itertuples():
        link = r.landing_url or r.catalog_url
        title = html.A(r.title, href=link, target="_blank", rel="noopener noreferrer", className="source-link") if link else r.title
        action = (html.Button("öffnen", id={"type": "od-open", "path": r.explore_id}, className="copy-btn",
                              style={"width": "auto", "padding": "2px 10px", "fontSize": "0.72rem"})
                  if r.explore_id else "")
        rows.append(html.Tr([html.Td(KIND_LABELS.get(r.kind, r.kind)), html.Td(title), html.Td(r.publisher or "–"),
                             html.Td(r.formats or "–"), html.Td(r.modified or "–"), html.Td(action)]))
    more = (html.P(f"Es werden die ersten {LIST_LIMIT} von {len(d)} Treffern gezeigt — Filter einschränken.",
                   style={"color": FL_GOLD, "fontSize": "0.78rem"}) if len(d) > LIST_LIMIT else None)
    return html.Div([
        html.Div(html.Table([html.Thead(html.Tr([html.Th(h) for h in ("Art", "Titel", "Amtsstelle", "Formate", "Geändert", "")])),
                             html.Tbody(rows)], className="od-table"),
                 style={"maxHeight": "420px", "overflowY": "auto"}),
        more,
    ])


# ── Layout ────────────────────────────────────────────────────────────────────

def render_opendata() -> html.Div:
    cat_all = _catalog_all()
    cat = _px_catalog()
    if cat_all.empty:
        return html.Div([
            html.H4("Open Data – opendata.li", className="section-title"),
            _empty("Der Katalog ist noch nicht geladen — der wöchentliche Discovery-Lauf (discover.py) füllt ihn."),
        ])

    n_px = int((cat_all["kind"] == "px").sum())
    n_files = int((cat["kind"] == "file").sum())
    n_imf = int((cat_all["kind"] == "imf").sum())
    n_other = int((~cat_all["kind"].isin(["px", "imf"])).sum())
    last_seen = cat_all["last_seen"].max()
    log_df = read_discovery_log(200)
    last_run = log_df["run_at"].max() if not log_df.empty else None
    n_events = int((log_df["run_at"] == last_run).sum()) if last_run else 0
    pubs = _publisher_counts(cat_all)

    kpis = dbc.Row([
        dbc.Col(_kpi("fa-table", "Statistik-Tabellen (PXWeb)", f"{n_px}", FL_BLUE,
                     f"+ {n_files} CSV/JSON-Dateien, {n_imf} IWF-Datenflüsse darstellbar"), md=3, sm=6, className="mb-3"),
        dbc.Col(_kpi("fa-map", "Geodaten & Sonstiges", f"{n_other}", FL_RED, "WMS, ZIP — verlinkt"), md=3, sm=6, className="mb-3"),
        dbc.Col(_kpi("fa-building-columns", "Amtsstellen mit Daten", f"{sum(1 for _, n in pubs if n)}", FL_GOLD,
                     f"{len(pubs)} im Katalog geführt"), md=3, sm=6, className="mb-3"),
        dbc.Col(_kpi("fa-bell", "Funde im letzten Lauf", f"{n_events}" if last_run else "–", GREEN,
                     f"Katalog-Abgleich {last_seen}" if last_run else "noch kein Vergleich"), md=3, sm=6, className="mb-3"),
    ], className="g-3")

    themes = [ALLE] + sorted(t for t in cat["theme"].unique() if t)
    kinds = [{"label": "Alle Arten", "value": ALLE}] + [
        {"label": f"{KIND_LABELS[k]} ({int((cat_all['kind'] == k).sum())})", "value": k}
        for k in ("px", "file", "imf", "geo", "other") if (cat_all["kind"] == k).any()]
    default_path = _default_path(cat)

    pub_chips = html.Div([
        html.Span([html.B(f"{n}", style={"color": TEXT, "marginRight": "4px"}), name],
                  style={"display": "inline-block", "margin": "0 8px 6px 0", "padding": "3px 10px", "borderRadius": "12px",
                         "background": "#1C2128", "border": f"1px solid {BORDER}", "fontSize": "0.75rem", "color": MUTED})
        for name, n in pubs], style={"marginBottom": "8px"})

    filters = _card([
        html.H6("Katalog filtern", style={"color": TEXT, "marginBottom": "4px"}),
        html.P("Datensätze je Amtsstelle (Herausgeber laut Katalog; die IWF-Datenflüsse kommen direkt vom IWF). Alle Filter lassen "
               "sich kombinieren und gelten für die Tabellenliste im Explorer und die Trefferliste darunter — auch für Geodaten und "
               "Dateien. CSV/JSON-Dateien und IWF-Datenflüsse lassen sich wie Statistik-Tabellen als Diagramm darstellen.",
               style={"color": MUTED, "fontSize": "0.78rem"}),
        pub_chips,
        dbc.Row([
            dbc.Col([html.Label("Amtsstelle", className="filter-label"),
                     dcc.Dropdown(id="od-org", options=_org_options(cat_all), value=ALLE, clearable=False,
                                  className="fl-dropdown")], md=3),
            dbc.Col([html.Label("Art", className="filter-label"),
                     dcc.Dropdown(id="od-kind", options=kinds, value=ALLE, clearable=False, className="fl-dropdown")], md=3),
            dbc.Col([html.Label("Thema (Statistik)", className="filter-label"),
                     dcc.Dropdown(id="od-theme", options=themes, value=ALLE, clearable=False, className="fl-dropdown")], md=3),
            dbc.Col([html.Label("Suche", className="filter-label"),
                     dcc.Input(id="od-search", type="text", debounce=True, placeholder="Titel, Nummer, Stichwort…",
                               className="share-input", style={"width": "100%", "height": "38px"})], md=3),
        ], className="g-3"),
    ])

    explorer = _card([
        html.Div(id="od-explorer"),
        html.H6("Daten-Explorer", style={"color": TEXT, "marginBottom": "12px"}),
        dbc.Row([
            dbc.Col([
                html.Label("Tabelle (Suche nach Titel oder Nummer)", className="filter-label"),
                dcc.Dropdown(id="od-table", options=_table_options(cat), value=default_path,
                             clearable=False, searchable=True, className="fl-dropdown", optionHeight=44),
            ], md=12),
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

    list_card = _card([
        html.H6(id="od-list-title", children=f"Treffer im Katalog ({len(cat_all)})", style={"color": TEXT}),
        html.Div(id="od-list", children=_catalog_list(cat_all)),
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
        html.Span(f" · Herausgeber je Datensatz laut Katalog · Statistik-Tabellen: {SOURCE_TEXT} · Lizenz: {LICENSE_TEXT} · "
                  "IWF-Datenflüsse: International Monetary Fund, SDMX-API (Quellenangabe, nicht-kommerziell)", style={"color": MUTED}),
    ], className="source-bar")

    return html.Div([
        html.H4("Open Data – opendata.li", className="section-title"),
        kpis, filters, html.Div(style={"height": "12px"}), explorer,
        html.Div(style={"height": "16px"}), list_card,
        html.Div(style={"height": "16px"}), disc_card, src,
    ])


# ── Callbacks ─────────────────────────────────────────────────────────────────

@callback(Output("od-table", "options"), Output("od-table", "value"),
          Output("od-list", "children"), Output("od-list-title", "children"),
          Input("od-org", "value"), Input("od-kind", "value"), Input("od-theme", "value"), Input("od-search", "value"),
          State("od-table", "value"), prevent_initial_call=True)
def _apply_filters(org, kind, theme, query, current):
    cat_all = _catalog_all()
    d = _filter_catalog(cat_all, org, kind, theme, query)
    opts = _table_options(d)
    values = {o["value"] for o in opts}
    value = no_update if current in values else (opts[0]["value"] if opts else None)
    return opts, value, _catalog_list(d), f"Treffer im Katalog ({len(d)} von {len(cat_all)})"


@callback(Output("od-table", "value", allow_duplicate=True),
          Input({"type": "od-open", "path": ALL}, "n_clicks"), prevent_initial_call=True)
def _open_from_list(clicks):
    """«öffnen» in der Trefferliste lädt die Tabelle in den Explorer."""
    if not any(c for c in clicks if c) or not isinstance(ctx.triggered_id, dict):
        return no_update
    return ctx.triggered_id["path"]


clientside_callback(
    """
    function(clicks) {
        if (clicks && clicks.some(function(c) { return c; })) {
            var el = document.getElementById('od-explorer');
            if (el) { el.scrollIntoView({behavior: 'smooth', block: 'start'}); }
        }
        return window.dash_clientside.no_update;
    }
    """,
    Output("od-explorer", "title"),
    Input({"type": "od-open", "path": ALL}, "n_clicks"),
    prevent_initial_call=True,
)


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
            if d.lower() not in ("frequency", "frequenz") and 2 <= df[d].nunique() <= 12:
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


def _source_line(path: str, stand: str) -> html.Div:
    """Quellenzeile je Art der Quelle (PXWeb, CSV/JSON-Datei aus dem Katalog, IWF)."""
    icon = html.I(className="fas fa-database", style={"marginRight": "6px", "color": MUTED})
    if path.startswith(SDMX_PREFIX):
        return html.Div([icon, html.Span("Quelle: ", style={"color": MUTED}),
                         html.A("International Monetary Fund, SDMX-API (" + path[len(SDMX_PREFIX):].split("/")[1] + ")",
                                href=IMF_PORTAL, target="_blank", rel="noopener noreferrer", className="source-link"),
                         html.Span(" · Lizenz: ", style={"color": MUTED}),
                         html.A("IWF-Datenbedingungen", href=TERMS_URL_IMF, target="_blank", rel="noopener noreferrer",
                                className="source-link"),
                         html.Span(f" (Quellenangabe, nicht-kommerziell){stand}", style={"color": MUTED})],
                        className="source-bar")
    if path.startswith(FILE_PREFIX):
        row = _px_catalog()
        row = row[row["explore_id"] == path]
        publisher = row["publisher"].iloc[0] if not row.empty else "opendata.li"
        page = (row["catalog_url"].iloc[0] if not row.empty else "") or PORTAL_URL
        return html.Div([icon, html.Span("Quelle: ", style={"color": MUTED}),
                         html.A(f"{publisher} via opendata.li", href=page, target="_blank", rel="noopener noreferrer",
                                className="source-link"),
                         html.Span(f" · Datei: {path[len(FILE_PREFIX):]} · Lizenz: {LICENSE_TEXT}{stand}",
                                   style={"color": MUTED})], className="source-bar")
    return html.Div([icon, html.Span("Quelle: ", style={"color": MUTED}),
                     html.A("PXWeb-Tabelle beim Amt für Statistik", href=px_web_url(path), target="_blank",
                            rel="noopener noreferrer", className="source-link"),
                     html.Span(f" · {SOURCE_TEXT} · Lizenz: {LICENSE_TEXT}{stand}", style={"color": MUTED})],
                    className="source-bar")


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
        msg = info.get("error") or "Tabelle konnte nicht geladen werden (Quelle nicht erreichbar?)."
        return _empty(f"Datei/Tabelle nicht darstellbar: {msg}")
    if x not in df.columns:
        return no_update  # Zwischenzustand beim Tabellenwechsel
    sub = df
    for fid, val in zip(flt_ids, flt_values):
        d = fid["dim"]
        if d in sub.columns and d not in (x, group) and val is not None:
            sub = sub[sub[d] == val]
    if sub.dropna(subset=["Wert"]).empty:
        return _empty("Für diese Auswahl gibt es keine Werte (Filter ändern).")

    if not info.get("title"):
        row = _px_catalog()
        row = row[row["explore_id"] == path]
        info = {**info, "title": row["title"].iloc[0] if not row.empty else ""}
    fig = _figure(sub, info or {}, x, group)
    fetched = info.get("fetched_at")
    stand = f" · Stand der Daten: {fetched:%d.%m.%Y}" if fetched else ""
    notes = []
    if info.get("reduced"):
        notes.append(html.P("Die Tabelle ist gross; für diese Ansicht wurden Dimensionen auf den ersten Wert "
                            f"(meist «Total») reduziert: {', '.join(info['reduced'])}. Vollständig auf opendata.li/PXWeb.",
                            style={"color": FL_GOLD, "fontSize": "0.8rem"}))
    link = _source_line(path, stand)
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
    if path.startswith(SDMX_PREFIX):
        name = "imf-" + path[len(SDMX_PREFIX):].split("/")[1].lower()
    elif path.startswith(FILE_PREFIX):
        name = path.rsplit("/", 1)[-1].split("?")[0] or "datei"
    else:
        name = path.rsplit("/", 1)[-1].replace(".px", "")
    return dcc.send_data_frame(df.to_csv, f"opendata-li-{name}.csv", index=False, sep=";")
