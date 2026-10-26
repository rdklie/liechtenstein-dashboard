"""
tab_wohnen.py — Tab «Wohnen & Immobilien»
=========================================
Daten: Amt für Statistik Liechtenstein via opendata.li (PXWeb), täglich vom Worker nach
SQLite gespiegelt (px_cache). Lizenz: Namensnennung (CC BY).

Was es gibt: Wohnungsbestand, nicht bewohnte Wohnungen (Leerstand am Stichtag), Mietpreise
(Volkszählung 2010/2015/2020), Bautätigkeit — jeweils je Gemeinde.
Was es nicht gibt: Kaufpreise / durchschnittlicher m²-Preis (keine offizielle Quelle).
"""

import dash_bootstrap_components as dbc
import pandas as pd
import plotly.graph_objects as go
from dash import dcc, html

from data_fetcher import MUNICIPALITIES
from db import get_px
from opendata import CURATED, LICENSE_TEXT, SOURCE_TEXT, px_web_url
from ui import (
    FL_BLUE, FL_RED, FL_GOLD, ACCENT, GREEN, MUTED, TEXT, BORDER, MUNI_PALETTE,
    _styled, _card, _kpi, _empty, _source_bar,
)

TOTAL = "Liechtenstein"
GEMEINDEN = [TOTAL] + [m["name"] for m in MUNICIPALITIES.values()]
DEFAULT_HOUSING_MUNI = [TOTAL]
RENT_TYPES = [{"label": "Nettomiete", "value": "netto"}, {"label": "Bruttomiete", "value": "brutto"}]
COORDS = {m["name"]: (m["lat"], m["lon"]) for m in MUNICIPALITIES.values()}


# ── Sidebar-Filter ────────────────────────────────────────────────────────────

def sidebar_section() -> html.Div:
    return html.Div(id="filter-housing", children=[
        html.Div([
            html.Label("Gemeinde (Zeitreihen)", className="filter-label"),
            dcc.Dropdown(
                id="housing-muni",
                options=[{"label": g, "value": g} for g in GEMEINDEN],
                value=DEFAULT_HOUSING_MUNI,
                multi=True, clearable=False,
                placeholder="Gemeinde wählen…", className="fl-dropdown",
            ),
        ], className="filter-section"),
        html.Div([
            html.Label("Mietpreise", className="filter-label"),
            dcc.RadioItems(
                id="housing-rent",
                options=RENT_TYPES, value="netto",
                className="fl-checklist", labelClassName="checklist-label",
            ),
        ], className="filter-section"),
    ])


# ── Daten-Helfer ──────────────────────────────────────────────────────────────

def _load(key: str) -> pd.DataFrame:
    df, _ = get_px(CURATED[key], max_age_hours=None)
    return df


def _fetched(*keys: str):
    """Ältester Abrufzeitpunkt der beteiligten Tabellen (für «Stand»)."""
    from db import read_px_cache
    ts = []
    for k in keys:
        c = read_px_cache(CURATED[k])
        if c:
            ts.append(c[2])
    return min(ts) if ts else None


def _fmt(x, digits: int = 0) -> str:
    if x is None or pd.isna(x):
        return "–"
    return f"{x:,.{digits}f}".replace(",", "’")


def _ts(df: pd.DataFrame, col: str, value: str, gemeinden: list[str], year_col: str = "Jahr",
        gem_col: str = "Gemeinde") -> dict[str, pd.DataFrame]:
    """{Gemeinde: DataFrame(x=Jahr (int), y=Wert)} für eine Kennzahl."""
    sub = df[df[col] == value] if col else df
    out = {}
    for g in gemeinden:
        d = sub[sub[gem_col] == g][[year_col, "Wert"]].dropna()
        if not d.empty:
            d = d.assign(**{year_col: pd.to_numeric(d[year_col], errors="coerce")}).dropna().sort_values(year_col)
            out[g] = d
    return out


def _vacancy(belegung: pd.DataFrame) -> pd.DataFrame:
    """Je Jahr/Gemeinde: Wohnungen total, nicht bewohnt am Stichtag, nicht dauernd bewohnt (+ Quoten)."""
    b = belegung
    tot_g = "Gebäudeart - Total"
    base = b[b["Gebäudeart"] == tot_g]
    total = base[(base["Nutzungsart"] == "Nutzungsart - Total") &
                 (base["Belegungsstatus"] == "Belegungsstatus - Total")]
    empty = base[(base["Nutzungsart"] == "Nutzungsart - Total") &
                 (base["Belegungsstatus"] == "Am Stichtag nicht bewohnt")]
    nondauer = base[(base["Nutzungsart"] == "Nicht dauernd bewohnt") &
                    (base["Belegungsstatus"] == "Belegungsstatus - Total")]
    out = total[["Jahr", "Gemeinde", "Wert"]].rename(columns={"Wert": "total"})
    out = out.merge(empty[["Jahr", "Gemeinde", "Wert"]].rename(columns={"Wert": "nicht_bewohnt"}),
                    on=["Jahr", "Gemeinde"], how="left")
    out = out.merge(nondauer[["Jahr", "Gemeinde", "Wert"]].rename(columns={"Wert": "nicht_dauernd"}),
                    on=["Jahr", "Gemeinde"], how="left")
    out["Jahr"] = pd.to_numeric(out["Jahr"], errors="coerce")
    out["quote"] = out["nicht_bewohnt"] / out["total"] * 100
    out["quote_nd"] = out["nicht_dauernd"] / out["total"] * 100
    return out.dropna(subset=["Jahr"])


def _graph(fig: go.Figure, height: int | None = None):
    if height:
        fig.update_layout(height=height)
    return dcc.Graph(figure=fig, config={"displayModeBar": False})


def _note(text: str, icon: str = "fa-info-circle", color: str = ACCENT):
    return html.Div([html.I(className=f"fas {icon}", style={"marginRight": "8px", "color": color}), text],
                    style={"color": MUTED, "fontSize": "0.8rem", "padding": "4px 2px"})


# ── Render ────────────────────────────────────────────────────────────────────

def render_wohnen(data: dict) -> html.Div:
    munis = [g for g in (data.get("housing_muni") or DEFAULT_HOUSING_MUNI) if g in GEMEINDEN] or DEFAULT_HOUSING_MUNI
    rent_type = data.get("housing_rent") or "netto"

    wohnungen = _load("wohnungen")
    belegung = _load("belegung")
    if wohnungen.empty and belegung.empty:
        return html.Div([
            html.H4("Wohnen & Immobilien – Liechtenstein", className="section-title"),
            _empty("Noch keine Daten in der Datenbank — der tägliche Datenabruf (06:00 UTC) füllt sie."),
        ])

    vac = _vacancy(belegung) if not belegung.empty else pd.DataFrame()
    pop = _load("bevoelkerung")
    gebaeude_mix = belegung
    bewilligt = _load("bewilligt")
    abbruch = _load("abbruch")
    miete_zi = _load(f"miete_{rent_type}_zi")
    miete_m2 = _load(f"miete_{rent_type}_m2")
    rent_label = "Nettomiete" if rent_type == "netto" else "Bruttomiete"

    # ── KPI-Karten ────────────────────────────────────────────────────────────
    w_fl = _ts(wohnungen, "", "", [TOTAL]).get(TOTAL) if not wohnungen.empty else None
    kpi_w = kpi_v = kpi_m = kpi_b = None
    if w_fl is not None and not w_fl.empty:
        y, v = int(w_fl["Jahr"].iloc[-1]), w_fl["Wert"].iloc[-1]
        past = w_fl[w_fl["Jahr"] <= y - 10]
        sub = ""
        if not past.empty:
            sub = f"{(v / past['Wert'].iloc[-1] - 1) * 100:+.1f} % seit {int(past['Jahr'].iloc[-1])}"
        kpi_w = _kpi("fa-house", f"Wohnungen ({y})", _fmt(v), FL_BLUE, sub)
    if not vac.empty:
        fl = vac[vac["Gemeinde"] == TOTAL].sort_values("Jahr")
        if not fl.empty:
            r = fl.iloc[-1]
            kpi_v = _kpi("fa-door-open", f"Nicht bewohnt am Stichtag ({int(r['Jahr'])})",
                         f"{r['quote']:.1f} %".replace(".", ","), FL_RED,
                         f"{_fmt(r['nicht_bewohnt'])} von {_fmt(r['total'])} Wohnungen")
    if not miete_zi.empty:
        m = miete_zi[(miete_zi["Gemeinde"] == TOTAL) & (miete_zi["Zimmerzahl der Wohnungen"].str.endswith("Total"))
                     & (miete_zi["Stichtag"] == "31.12.2020")]
        if not m.empty:
            kpi_m = _kpi("fa-money-bill-wave", f"Ø {rent_label} (Monat)",
                         f"CHF {_fmt(m['Wert'].iloc[0])}", FL_GOLD, "Volkszählung 31.12.2020")
    if not bewilligt.empty:
        nb = bewilligt[(bewilligt["Gemeinde"] == TOTAL) &
                       (bewilligt["Bewilligte neue Gebäude und Wohnungen"] == "Bewilligte neue Wohnungen - Total")]
        nb = nb.dropna(subset=["Wert"])
        if not nb.empty:
            kpi_b = _kpi("fa-hammer", f"Bewilligte neue Wohnungen ({nb['Bewilligungsjahr'].iloc[-1]})",
                         _fmt(nb["Wert"].iloc[-1]), GREEN, "Neubau + Veränderungsprojekte")
    kpis = [k for k in (kpi_w, kpi_v, kpi_m, kpi_b) if k is not None]
    kpi_row = dbc.Row([dbc.Col(k, md=3, sm=6, className="mb-3") for k in kpis], className="g-3")

    # ── Karte + Balken: nicht bewohnte Wohnungen je Gemeinde ──────────────────
    map_card = bar_card = _empty("Keine Belegungsdaten.")
    latest_year = None
    if not vac.empty:
        latest_year = int(vac["Jahr"].max())
        cur = vac[(vac["Jahr"] == latest_year) & (vac["Gemeinde"] != TOTAL)].dropna(subset=["quote"])
        if not cur.empty:
            lat = [COORDS[g][0] for g in cur["Gemeinde"]]
            lon = [COORDS[g][1] for g in cur["Gemeinde"]]
            size = (cur["total"] / cur["total"].max() * 38 + 10).tolist()
            fig = go.Figure(go.Scattermap(
                lat=lat, lon=lon, mode="markers+text",
                text=cur["Gemeinde"], textposition="top center",
                textfont=dict(color=TEXT, size=11),
                marker=dict(size=size, color=cur["quote"], colorscale="YlOrRd", opacity=0.85,
                            colorbar=dict(title=dict(text="% nicht<br>bewohnt", font=dict(color=TEXT)),
                                          tickfont=dict(color=TEXT), len=0.7)),
                customdata=list(zip(cur["total"], cur["nicht_bewohnt"], cur["quote"])),
                hovertemplate="<b>%{text}</b><br>Wohnungen: %{customdata[0]:,.0f}<br>"
                              "Nicht bewohnt: %{customdata[1]:,.0f} (%{customdata[2]:.1f} %)<extra></extra>",
            ))
            fig.update_layout(
                map=dict(style="carto-darkmatter", center=dict(lat=47.155, lon=9.535), zoom=9.6),
                margin=dict(l=0, r=0, t=40, b=0), height=380,
                paper_bgcolor="rgba(0,0,0,0)", font=dict(color=TEXT),
                title=dict(text=f"Nicht bewohnte Wohnungen {latest_year} (Blase = Wohnungen)",
                           font=dict(size=14, color=TEXT), x=0.0),
            )
            map_card = _card(_graph(fig))
            s = cur.sort_values("quote")
            bar = go.Figure(go.Bar(
                x=s["quote"], y=s["Gemeinde"], orientation="h",
                marker_color=[FL_RED if q == s["quote"].max() else FL_BLUE for q in s["quote"]],
                customdata=list(zip(s["nicht_bewohnt"], s["total"])),
                hovertemplate="<b>%{y}</b>: %{x:.1f} %<br>%{customdata[0]:,.0f} von %{customdata[1]:,.0f}<extra></extra>",
            ))
            fl_q = vac[(vac["Jahr"] == latest_year) & (vac["Gemeinde"] == TOTAL)]["quote"]
            if not fl_q.empty:
                bar.add_vline(x=float(fl_q.iloc[0]), line_dash="dot", line_color=FL_GOLD,
                              annotation_text="Liechtenstein", annotation_font_color=FL_GOLD)
            _styled(bar, f"Anteil nicht bewohnter Wohnungen {latest_year} (%)", legend=False)
            bar.update_layout(hovermode="closest", height=380, margin=dict(l=100, r=20, t=50, b=40))
            bar_card = _card(_graph(bar))

    # ── Zeitreihen (gewählte Gemeinden) ───────────────────────────────────────
    ts_w = ts_v = _empty("Keine Daten.")
    if not wohnungen.empty:
        fig = go.Figure()
        for i, (g, d) in enumerate(_ts(wohnungen, "", "", munis).items()):
            fig.add_trace(go.Scatter(x=d["Jahr"], y=d["Wert"], mode="lines+markers", name=g,
                                     line=dict(color=MUNI_PALETTE[i % len(MUNI_PALETTE)], width=2.5),
                                     hovertemplate=f"<b>{g}</b> %{{x}}: %{{y:,.0f}}<extra></extra>"))
        if fig.data:
            _styled(fig, "Wohnungsbestand seit 1980")
            ts_w = _card(_graph(fig))
    if not vac.empty:
        fig = go.Figure()
        for i, g in enumerate(munis):
            d = vac[vac["Gemeinde"] == g].sort_values("Jahr").dropna(subset=["quote"])
            if d.empty:
                continue
            col = MUNI_PALETTE[i % len(MUNI_PALETTE)]
            fig.add_trace(go.Scatter(x=d["Jahr"], y=d["quote"], mode="lines+markers", name=f"{g}: nicht bewohnt",
                                     line=dict(color=col, width=2.5),
                                     hovertemplate=f"<b>{g}</b> %{{x}}: %{{y:.1f}} %<extra>nicht bewohnt</extra>"))
            fig.add_trace(go.Scatter(x=d["Jahr"], y=d["quote_nd"], mode="lines", name=f"{g}: nicht dauernd bewohnt",
                                     line=dict(color=col, width=1.5, dash="dot"),
                                     hovertemplate=f"<b>{g}</b> %{{x}}: %{{y:.1f}} %<extra>nicht dauernd bewohnt</extra>"))
        if fig.data:
            _styled(fig, "Nicht (dauernd) bewohnte Wohnungen, % des Bestands")
            fig.update_yaxes(ticksuffix=" %")
            ts_v = _card(_graph(fig))

    # ── Einwohner je Wohnung + Gebäudeart ─────────────────────────────────────
    per_card = mix_card = _empty("Keine Daten.")
    if not pop.empty and not wohnungen.empty:
        p = pop[(pop["Geschlecht"] == "Geschlecht - Total")][["Jahr", "Wohngemeinde", "Wert"]]
        p = p.rename(columns={"Wohngemeinde": "Gemeinde", "Wert": "pop"})
        w = wohnungen[["Jahr", "Gemeinde", "Wert"]].rename(columns={"Wert": "wohn"})
        m = w.merge(p, on=["Jahr", "Gemeinde"])
        m = m[m["Gemeinde"] != TOTAL].dropna()
        if not m.empty:
            y = m["Jahr"].astype(int).max()
            c = m[m["Jahr"].astype(int) == y].copy()
            c["ratio"] = c["pop"] / c["wohn"]
            c = c.sort_values("ratio")
            fig = go.Figure(go.Bar(
                x=c["ratio"], y=c["Gemeinde"], orientation="h", marker_color=ACCENT,
                customdata=list(zip(c["pop"], c["wohn"])),
                hovertemplate="<b>%{y}</b>: %{x:.2f} Einw./Wohnung<br>%{customdata[0]:,.0f} Einw., "
                              "%{customdata[1]:,.0f} Wohnungen<extra></extra>"))
            _styled(fig, f"Einwohner je Wohnung {y}", legend=False)
            fig.update_layout(hovermode="closest", margin=dict(l=100, r=20, t=50, b=40))
            per_card = _card(_graph(fig))
    if not gebaeude_mix.empty and latest_year:
        g = gebaeude_mix[(gebaeude_mix["Jahr"] == str(latest_year)) & (gebaeude_mix["Gemeinde"] == TOTAL) &
                         (gebaeude_mix["Nutzungsart"] == "Nutzungsart - Total") &
                         (gebaeude_mix["Belegungsstatus"] == "Belegungsstatus - Total")]
        parts = {"Einfamilienhäuser": "... Einfamilienhäuser", "Zweifamilienhäuser": "... Zweifamilienhäuser",
                 "Mehrfamilienhäuser": "... Mehrfamilienhäuser", "Andere Wohngebäude": "- Andere Wohngebäude",
                 "Sonstige Gebäude": "Sonstige Gebäude"}
        vals = {k: g[g["Gebäudeart"] == v]["Wert"] for k, v in parts.items()}
        vals = {k: float(v.iloc[0]) for k, v in vals.items() if not v.empty and pd.notna(v.iloc[0])}
        if vals:
            fig = go.Figure(go.Pie(labels=list(vals), values=list(vals.values()), hole=0.55,
                                   marker=dict(colors=[FL_BLUE, ACCENT, FL_RED, FL_GOLD, MUTED]),
                                   textinfo="label+percent", sort=False,
                                   hovertemplate="<b>%{label}</b>: %{value:,.0f} Wohnungen<extra></extra>"))
            _styled(fig, f"Wohnungen nach Gebäudeart {latest_year}", legend=False)
            fig.update_layout(hovermode="closest")
            mix_card = _card(_graph(fig))

    # ── Mieten ────────────────────────────────────────────────────────────────
    rent_bar = rent_ts = rent_zi = rent_m2 = _empty("Keine Mietdaten.")
    if not miete_zi.empty:
        tot = miete_zi[miete_zi["Zimmerzahl der Wohnungen"].str.endswith("Total")]
        cur = tot[(tot["Stichtag"] == "31.12.2020") & (tot["Gemeinde"] != TOTAL)].dropna(subset=["Wert"]).sort_values("Wert")
        if not cur.empty:
            fl = tot[(tot["Stichtag"] == "31.12.2020") & (tot["Gemeinde"] == TOTAL)]["Wert"]
            fig = go.Figure(go.Bar(x=cur["Wert"], y=cur["Gemeinde"], orientation="h",
                                   marker_color=[FL_RED if v == cur["Wert"].max() else FL_BLUE for v in cur["Wert"]],
                                   hovertemplate="<b>%{y}</b>: CHF %{x:,.0f} pro Monat<extra></extra>"))
            if not fl.empty:
                fig.add_vline(x=float(fl.iloc[0]), line_dash="dot", line_color=FL_GOLD,
                              annotation_text="Liechtenstein", annotation_font_color=FL_GOLD)
            _styled(fig, f"Ø {rent_label} je Gemeinde, 2020 (CHF/Monat)", legend=False)
            fig.update_layout(hovermode="closest", margin=dict(l=100, r=20, t=50, b=40))
            rent_bar = _card(_graph(fig))
        fig = go.Figure()
        for i, g in enumerate(munis):
            d = tot[tot["Gemeinde"] == g].copy()
            d["t"] = pd.to_datetime(d["Stichtag"], format="%d.%m.%Y", errors="coerce")
            d = d.dropna(subset=["t", "Wert"]).sort_values("t")
            if not d.empty:
                fig.add_trace(go.Scatter(x=d["t"].dt.year, y=d["Wert"], mode="lines+markers", name=g,
                                         line=dict(color=MUNI_PALETTE[i % len(MUNI_PALETTE)], width=2.5),
                                         hovertemplate=f"<b>{g}</b> %{{x}}: CHF %{{y:,.0f}}<extra></extra>"))
        if fig.data:
            _styled(fig, f"Ø {rent_label} 2010 · 2015 · 2020 (CHF/Monat)")
            fig.update_xaxes(tickvals=[2010, 2015, 2020])
            rent_ts = _card(_graph(fig))
        sel = munis[0]
        fig = go.Figure()
        for stichtag, col in (("31.12.2010", MUTED), ("31.12.2015", ACCENT), ("31.12.2020", FL_BLUE)):
            d = miete_zi[(miete_zi["Gemeinde"] == sel) & (miete_zi["Stichtag"] == stichtag) &
                         (~miete_zi["Zimmerzahl der Wohnungen"].str.endswith("Total"))].dropna(subset=["Wert"])
            if not d.empty:
                fig.add_trace(go.Bar(x=d["Zimmerzahl der Wohnungen"], y=d["Wert"], name=stichtag[-4:],
                                     marker_color=col,
                                     hovertemplate="%{x}: CHF %{y:,.0f}<extra>" + stichtag[-4:] + "</extra>"))
        if fig.data:
            _styled(fig, f"Ø {rent_label} nach Zimmerzahl — {sel}")
            fig.update_layout(barmode="group", yaxis_title="CHF pro Monat")
            rent_zi = _card(_graph(fig))
    if not miete_m2.empty:
        sel = munis[0]
        fig = go.Figure()
        for stichtag, col in (("31.12.2010", MUTED), ("31.12.2015", ACCENT), ("31.12.2020", FL_BLUE)):
            d = miete_m2[(miete_m2["Gemeinde"] == sel) & (miete_m2["Stichtag"] == stichtag) &
                         (~miete_m2["Wohnungsfläche"].str.contains("Total"))].dropna(subset=["Wert"])
            if not d.empty:
                fig.add_trace(go.Bar(x=d["Wohnungsfläche"], y=d["Wert"], name=stichtag[-4:], marker_color=col,
                                     hovertemplate="%{x}: CHF %{y:,.0f}<extra>" + stichtag[-4:] + "</extra>"))
        if fig.data:
            _styled(fig, f"Ø {rent_label} nach Wohnungsfläche — {sel}")
            fig.update_layout(barmode="group", yaxis_title="CHF pro Monat")
            rent_m2 = _card(_graph(fig))

    # ── Bautätigkeit ──────────────────────────────────────────────────────────
    build_ts = build_heat = _empty("Keine Bautätigkeitsdaten.")
    if not bewilligt.empty:
        nb = bewilligt[bewilligt["Bewilligte neue Gebäude und Wohnungen"] == "Bewilligte neue Wohnungen - Total"]
        fl = nb[nb["Gemeinde"] == TOTAL].dropna(subset=["Wert"])
        fig = go.Figure()
        fig.add_trace(go.Bar(x=fl["Bewilligungsjahr"], y=fl["Wert"], name="Bewilligte neue Wohnungen",
                             marker_color=FL_BLUE,
                             hovertemplate="%{x}: %{y:,.0f} neue Wohnungen<extra></extra>"))
        if not abbruch.empty:
            ab = abbruch[(abbruch["Gebäude- oder Wohnungstyp"] == "Abbruchbewilligte Wohnungen") &
                         (abbruch["Gemeinde"] == TOTAL)].dropna(subset=["Wert"])
            fig.add_trace(go.Bar(x=ab["Bewilligungsjahr"], y=-ab["Wert"], name="Abbruchbewilligte Wohnungen",
                                 marker_color=FL_RED, customdata=ab["Wert"],
                                 hovertemplate="%{x}: %{customdata:,.0f} Wohnungen abgebrochen<extra></extra>"))
        if fig.data:
            _styled(fig, "Baubewilligungen Wohnungen — Liechtenstein")
            fig.update_layout(barmode="relative")
            build_ts = _card(_graph(fig))
        h = nb[nb["Gemeinde"] != TOTAL].dropna(subset=["Wert"])
        if not h.empty:
            pv = h.pivot_table(index="Gemeinde", columns="Bewilligungsjahr", values="Wert", aggfunc="sum")
            pv = pv.loc[pv.sum(axis=1).sort_values().index]
            fig = go.Figure(go.Heatmap(z=pv.values, x=pv.columns, y=pv.index, colorscale="Blues",
                                       hovertemplate="<b>%{y}</b> %{x}: %{z:,.0f} neue Wohnungen<extra></extra>",
                                       colorbar=dict(tickfont=dict(color=TEXT))))
            _styled(fig, "Bewilligte neue Wohnungen je Gemeinde und Jahr", legend=False)
            fig.update_layout(hovermode="closest", margin=dict(l=100, r=20, t=50, b=40))
            build_heat = _card(_graph(fig))

    # ── Hinweis Kaufpreise ────────────────────────────────────────────────────
    gap = _card([
        html.H6([html.I(className="fas fa-triangle-exclamation", style={"color": FL_GOLD, "marginRight": "8px"}),
                 "Kaufpreise & Quadratmeterpreise: keine offizielle Datenquelle"], style={"color": TEXT}),
        html.P("Für Liechtenstein veröffentlicht das Amt für Statistik keine Kauf-, Boden- oder "
               "Quadratmeterpreise (weder auf opendata.li noch bei Eurostat oder der Weltbank). "
               "Angebotspreise kommerzieller Immobilienportale werden hier bewusst nicht ausgewertet "
               "(Nutzungsbedingungen, nicht amtlich). Die Mietpreise stammen aus der Volkszählung "
               "und liegen nur für die Stichtage 2010, 2015 und 2020 vor — es sind Durchschnittswerte "
               "in CHF pro Wohnung und Monat, keine Preise pro m².",
               style={"color": MUTED, "fontSize": "0.85rem", "marginBottom": "0"}),
    ])

    fetched = _fetched("wohnungen", "belegung", "miete_netto_zi", "bewilligt")
    stand = f" · Stand der Daten: {fetched:%d.%m.%Y}" if fetched else ""
    src_links = html.Div([
        html.I(className="fas fa-link", style={"marginRight": "6px", "color": MUTED}),
        html.Span("Tabellen: ", style={"color": MUTED}),
        *[html.Span([html.A(label, href=px_web_url(CURATED[k]), target="_blank", rel="noopener noreferrer",
                            className="source-link"), html.Span(" · ", style={"color": BORDER})])
          for k, label in (("wohnungen", "391.133 Wohnungen"), ("belegung", "391.131 Belegung"),
                           ("miete_netto_zi", "394 Mietpreise"), ("bewilligt", "381 Bautätigkeit"))],
    ], className="source-bar")

    return html.Div([
        html.H4("Wohnen & Immobilien – Liechtenstein", className="section-title"),
        kpi_row,
        dbc.Row([dbc.Col(map_card, md=7, className="mb-3"), dbc.Col(bar_card, md=5, className="mb-3")], className="g-3"),
        _note("Leerstand: Die amtliche Statistik weist Wohnungen aus, die am Stichtag «nicht bewohnt» bzw. «nicht dauernd "
              "bewohnt» waren. Das kann auch Ferien-/Zweitwohnungen enthalten und ist nicht gleichbedeutend mit "
              "marktwirksamem Leerstand."),
        dbc.Row([dbc.Col(ts_w, md=6, className="mb-3"), dbc.Col(ts_v, md=6, className="mb-3")], className="g-3"),
        dbc.Row([dbc.Col(per_card, md=6, className="mb-3"), dbc.Col(mix_card, md=6, className="mb-3")], className="g-3"),
        html.H5("Mietpreise", className="section-title", style={"marginTop": "8px"}),
        dbc.Row([dbc.Col(rent_bar, md=6, className="mb-3"), dbc.Col(rent_ts, md=6, className="mb-3")], className="g-3"),
        dbc.Row([dbc.Col(rent_zi, md=6, className="mb-3"), dbc.Col(rent_m2, md=6, className="mb-3")], className="g-3"),
        html.H5("Bautätigkeit", className="section-title", style={"marginTop": "8px"}),
        dbc.Row([dbc.Col(build_ts, md=6, className="mb-3"), dbc.Col(build_heat, md=6, className="mb-3")], className="g-3"),
        gap,
        html.Div(style={"height": "12px"}),
        _source_bar("opendata", extra=f"{SOURCE_TEXT} · Lizenz: {LICENSE_TEXT}{stand}"),
        src_links,
    ])
