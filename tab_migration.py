"""
tab_migration.py — Tab «Migration»
==================================
Sachlich und quellenbasiert: amtliche/internationale Quellen (Eurostat, Weltbank/UN DESA, Amt für Statistik
Liechtenstein, Landespolizei Liechtenstein), jeweils mit Definition, Quelle, Lizenz und Stand.
Daten kommen aus SQLite (vom Worker höchstens wöchentlich gespiegelt, siehe migration.py).

Kosten: nur die in der Landesrechnung ausgewiesenen Ausgaben des Landes für das Asylwesen (Konto 590, siehe landesrechnung.py).
Bewusst NICHT enthalten: Ausgaben je Migrant (keine belastbare, vergleichbare Statistik — siehe Hinweiskasten), Kosten je Gesuch
und alles, was auf Schätzungen aus dritten Quellen beruhen würde.
"""

import dash_bootstrap_components as dbc
import pandas as pd
import plotly.graph_objects as go

import landesrechnung as LR
from dash import Input, Output, callback, ctx, dcc, html, no_update

from db import get_px, read_px_cache
from migration import (COUNTRY_NAMES, EFTA, EU27, GROUPS, MIG_PX, ES_SPECS, WB_KEY, es_id, pxs_id)
from ui import FL_BLUE, FL_RED, FL_GOLD, ACCENT, GREEN, MUTED, TEXT, BORDER, MUNI_PALETTE, _card, _kpi, _styled, _empty

LI = "LIE"
DEFAULT_COUNTRIES = ["LIE", "DEU", "AUT", "CHE"]
DEFAULT_GROUPS = ["EU27", "DACHL"]
INDICATORS = [
    {"label": "Ausländische Staatsangehörige (Eurostat)", "value": "cit"},
    {"label": "Im Ausland Geborene (Eurostat)", "value": "birth"},
    {"label": "Internationaler Migrantenbestand (UN DESA/Weltbank)", "value": "stock"},
]
IND_TITLE = {"cit": "Anteil ausländischer Staatsangehöriger", "birth": "Anteil im Ausland Geborener",
             "stock": "Anteil internationaler Migranten (UN DESA)"}
STAGES = [{"label": "Tatverdächtige", "value": "PER_SUSP"}, {"label": "Strafverfolgte", "value": "PER_PRSC"},
          {"label": "Verurteilte", "value": "PER_CNV"}]
STAGE_NAME = {v["value"]: v["label"] for v in STAGES}
DEFAULT_YEAR = 2024
COUNTRY_OPTS = [{"label": COUNTRY_NAMES[c], "value": c} for c in
                sorted(COUNTRY_NAMES, key=lambda c: (c not in ("LIE", "DEU", "AUT", "CHE"), COUNTRY_NAMES[c]))]

ES_LICENSE = "Eurostat, © Europäische Union, CC BY 4.0"
WB_LICENSE = "Weltbank WDI / UN DESA, CC BY 4.0"
LI_LICENSE = "Amt für Statistik Liechtenstein, opendata.li, Namensnennung (CC BY)"
URL = {
    "es": "https://ec.europa.eu/eurostat/databrowser/view/{}/default/table",
    "wb": "https://data.worldbank.org/indicator/SM.POP.TOTL.ZS",
    "li": "https://www.opendata.li/de/daten",
    "lp": "https://www.landespolizei.li/",
}


# ── Sidebar ───────────────────────────────────────────────────────────────────

def sidebar_section() -> html.Div:
    btn = {"width": "auto", "padding": "3px 10px", "fontSize": "0.72rem", "marginRight": "4px", "marginBottom": "4px"}
    return html.Div(id="filter-migration", children=[
        html.Div([
            html.Label("Kennzahl (Anteil)", className="filter-label"),
            dcc.RadioItems(id="mig-ind", options=INDICATORS, value="cit", className="fl-checklist",
                           labelClassName="checklist-label"),
        ], className="filter-section"),
        html.Div([
            html.Label("Länder", className="filter-label"),
            dcc.Dropdown(id="mig-countries", options=COUNTRY_OPTS, value=DEFAULT_COUNTRIES, multi=True, clearable=False,
                         placeholder="Land hinzufügen…", className="fl-dropdown"),
            html.Div([
                html.Button("EU27", id="mig-btn-eu", className="copy-btn", style=btn),
                html.Button("EWR", id="mig-btn-ewr", className="copy-btn", style=btn),
                html.Button("D-A-CH-L", id="mig-btn-dachl", className="copy-btn", style=btn),
                html.Button("+ USA, China, Russland", id="mig-btn-world", className="copy-btn", style=btn),
                html.Button("Zurücksetzen", id="mig-btn-reset", className="copy-btn", style=btn),
            ], style={"marginTop": "6px"}),
        ], className="filter-section"),
        html.Div([
            html.Label("Gruppenwerte anzeigen", className="filter-label"),
            dcc.Checklist(id="mig-groups", options=[{"label": v[0], "value": k} for k, v in GROUPS.items()],
                          value=DEFAULT_GROUPS, className="fl-checklist", labelClassName="checklist-label"),
            html.Small("Gruppenwert = Summe der Betroffenen / Summe der Bevölkerung der Mitgliedsländer mit Daten "
                       "(nach Bevölkerung gewichtet).", style={"color": MUTED, "fontSize": "0.7rem"}),
        ], className="filter-section"),
        html.Div([
            html.Label("Jahr (Ländervergleich)", className="filter-label"),
            dcc.Slider(id="mig-year", min=1990, max=2025, step=1, value=DEFAULT_YEAR,
                       marks={y: {"label": str(y), "style": {"color": MUTED, "fontSize": "10px"}} for y in range(1990, 2026, 5)},
                       tooltip={"placement": "bottom", "always_visible": True}, className="fl-slider"),
        ], className="filter-section"),
    ])


@callback(Output("mig-countries", "value"),
          Input("mig-btn-eu", "n_clicks"), Input("mig-btn-ewr", "n_clicks"), Input("mig-btn-dachl", "n_clicks"),
          Input("mig-btn-world", "n_clicks"), Input("mig-btn-reset", "n_clicks"), prevent_initial_call=True)
def _shortcut(*_):
    t = ctx.triggered_id
    if t == "mig-btn-eu":
        return ["LIE"] + GROUPS["EU27"][1]
    if t == "mig-btn-ewr":
        return GROUPS["EWR"][1] + ["CHE"]
    if t == "mig-btn-dachl":
        return GROUPS["DACHL"][1]
    if t == "mig-btn-world":
        return DEFAULT_COUNTRIES + ["USA", "CHN", "RUS"]
    if t == "mig-btn-reset":
        return DEFAULT_COUNTRIES
    return no_update


# ── Daten ─────────────────────────────────────────────────────────────────────

def _g(key: str) -> pd.DataFrame:
    return get_px(key, max_age_hours=None)[0]


def _stand(*keys: str):
    ts = [c[2] for c in (read_px_cache(k) for k in keys) if c]
    return min(ts) if ts else None


def _clean(label: str) -> str:
    return str(label).lstrip("-. ").strip()


def share_table(ind: str) -> pd.DataFrame:
    """Alle Länder: iso3, year, share (%), numer, denom, name — je nach Kennzahl."""
    if ind in ("cit", "birth"):
        key, dim, nat = ("es:pop_cit", "citizen", "NAT") if ind == "cit" else ("es:pop_birth", "c_birth", "NAT")
        d = _g(key)
        if d.empty:
            return d
        d = d[d["iso3"].notna()]
        p = d.pivot_table(index=["iso3", "time"], columns=dim, values="Wert").reset_index()
        denom = p["TOTAL"]
        numer = (p["TOTAL"] - p[nat]) if ind == "cit" else p["FOR"]
        out = pd.DataFrame({"iso3": p["iso3"], "year": p["time"].astype(int), "numer": numer, "denom": denom})
    else:
        w = _g(WB_KEY)
        if w.empty:
            return w
        p = w.pivot_table(index=["iso3", "year"], columns="indicator", values="Wert").reset_index()
        pp = w[w["indicator"] == "SP.POP.TOTL"][["iso3", "year", "Wert"]].rename(columns={"Wert": "pop"})
        p = p.merge(pp, on=["iso3", "year"], how="left")
        out = pd.DataFrame({"iso3": p["iso3"], "year": p["year"].astype(int), "numer": p["SM.POP.TOTL"], "denom": p["pop"],
                            "share_wb": p["SM.POP.TOTL.ZS"]})
    out = out.dropna(subset=["numer", "denom"])
    out["share"] = out["numer"] / out["denom"] * 100
    if ind == "stock":
        out["share"] = out["share"].where(out["share"].notna(), out.get("share_wb"))
    out["name"] = out["iso3"].map(lambda c: COUNTRY_NAMES.get(c, c))
    return out


def group_series(df: pd.DataFrame, members: list[str], min_members: int = 3) -> pd.DataFrame:
    """Gruppenwert je Jahr: Σ Betroffene / Σ Bevölkerung der Länder mit Daten; n = Anzahl Länder."""
    sub = df[df["iso3"].isin(members)]
    g = sub.groupby("year").agg(numer=("numer", "sum"), denom=("denom", "sum"), n=("iso3", "nunique")).reset_index()
    g = g[g["n"] >= min(min_members, len(members))]
    g["share"] = g["numer"] / g["denom"] * 100
    return g


def _name(c: str) -> str:
    return COUNTRY_NAMES.get(c, c)


LI_COLOR = "#F0F6FC"                      # Liechtenstein hell hervorgehoben (dunkles Blau ist auf dem dunklen Grund schlecht lesbar)
_PALETTE = [FL_RED, FL_GOLD, ACCENT, GREEN, "#BB8FCE", "#F0883E", "#58D68D", "#79C0FF", "#D2A679", "#F85149", "#FBD460"]
GROUP_STYLE = {"EU27": ("#8B949E", "dot"), "EWR": ("#B1BAC4", "dash"), "DACHL": ("#F0883E", "dot")}


def _col(i: int, c: str) -> str:
    return LI_COLOR if c == LI else _PALETTE[i % len(_PALETTE)]


def _graph(fig: go.Figure, height: int = 340):
    fig.update_layout(height=height)
    return dcc.Graph(figure=fig, config={"displayModeBar": False})


def _note(text, icon="fa-circle-info", color=ACCENT):
    return html.Div([html.I(className=f"fas {icon}", style={"marginRight": "8px", "color": color}), text],
                    style={"color": MUTED, "fontSize": "0.78rem", "padding": "2px 2px 8px"})


def _source(*parts) -> html.Div:
    """parts: (Text, URL|None) — Quelle · Lizenz · Stand."""
    items = [html.I(className="fas fa-database", style={"marginRight": "6px", "color": MUTED}),
             html.Span("Quelle: ", style={"color": MUTED})]
    for i, (text, url) in enumerate(parts):
        if i:
            items.append(html.Span(" · ", style={"color": BORDER}))
        items.append(html.A(text, href=url, target="_blank", rel="noopener noreferrer", className="source-link") if url
                     else html.Span(text, style={"color": MUTED}))
    return html.Div(items, className="source-bar")


def _section(title: str, intro: str | None = None):
    return html.Div([html.H5(title, className="section-title", style={"marginTop": "18px"}),
                     html.P(intro, style={"color": MUTED, "fontSize": "0.82rem"}) if intro else None])


# ── Hinweiskasten ─────────────────────────────────────────────────────────────

def how_to_read() -> html.Div:
    def item(title, text):
        return html.Li([html.B(title + ": ", style={"color": TEXT}), text], style={"marginBottom": "4px"})
    return _card([
        html.H6([html.I(className="fas fa-book-open", style={"marginRight": "8px", "color": ACCENT}), "Wie lesen? Begriffe und Grenzen"],
                style={"color": TEXT}),
        html.Ul([
            item("Ausländische Staatsangehörige", "Personen ohne die Staatsbürgerschaft des Wohnlands (Eurostat: Total minus Staatsangehörige des "
                 "Berichtslands, inkl. Staatenlose). Wer eingebürgert wird, zählt danach nicht mehr dazu — Länder mit leichter Einbürgerung "
                 "haben deshalb niedrigere Anteile."),
            item("Im Ausland Geborene", "Personen, deren Geburtsland nicht das Wohnland ist, unabhängig von der heutigen Staatsbürgerschaft "
                 "(Eurostat migr_pop3ctb). Umfasst Eingebürgerte, aber auch z. B. Kinder von Auslandsaufenthalten."),
            item("Internationaler Migrantenbestand", "UN DESA, für alle Länder vergleichbar (Weltbank SM.POP.TOTL.ZS): im Ausland Geborene "
                 "inkl. Flüchtlinge, Mitte des Jahres, nur alle 5 Jahre (zuletzt 2024); teils aus Volkszählungen, teils modelliert."),
            item("Ausländer ≠ Migrant", "Keine der Kennzahlen misst «Migrationshintergrund» oder Zuwanderung insgesamt; die drei Zahlen "
                 "unterscheiden sich systematisch (siehe Abweichungs-Diagramm für Liechtenstein)."),
            item("Liechtenstein", "Kleine Bevölkerung (rund 41 000) mit hohem Anteil Nichtansässiger in der Arbeitswelt: Grenzgänger wohnen "
                 "im Ausland und sind NICHT in der Wohnbevölkerung enthalten; sie werden separat ausgewiesen."),
            item("Gruppenwerte", "Σ Betroffene / Σ Gesamtbevölkerung der Mitgliedsländer mit Daten im jeweiligen Jahr (nach Bevölkerung gewichtet, "
                 "kein einfacher Länder-Mittelwert). Fehlende Länder verändern den Wert; die Zahl der berücksichtigten Länder steht im Tooltip."),
            item("Kein Rückschluss auf Einzelne", "Alle Zahlen sind Gruppenstatistiken. Sie sagen nichts über einzelne Personen aus."),
        ], style={"color": MUTED, "fontSize": "0.8rem", "paddingLeft": "18px", "marginBottom": "0"}),
    ])


# ── Abschnitt A: Anteil ───────────────────────────────────────────────────────

def section_share(ind: str, countries: list[str], groups: list[str], year: int):
    df = share_table(ind)
    if df.empty:
        return [_empty("Keine Daten in der Datenbank — der wöchentliche Abruf füllt sie.")]
    out = []
    have = set(df["iso3"])
    missing = [c for c in countries if c not in have]
    fig = go.Figure()
    for i, c in enumerate(countries):
        d = df[df["iso3"] == c].sort_values("year")
        if d.empty:
            continue
        fig.add_trace(go.Scatter(x=d["year"], y=d["share"], mode="lines+markers", name=_name(c),
                                 line=dict(color=_col(i, c), width=3 if c == LI else 2),
                                 hovertemplate=f"<b>{_name(c)}</b> %{{x}}: %{{y:.1f}} %<extra></extra>"))
    for gkey in groups:
        label, members = GROUPS[gkey]
        g = group_series(df, members)
        if g.empty:
            continue
        fig.add_trace(go.Scatter(x=g["year"], y=g["share"], mode="lines", name=label.split(" (")[0] + " (Gruppe)",
                                 line=dict(dash=GROUP_STYLE[gkey][1], width=2.2, color=GROUP_STYLE[gkey][0]), customdata=g["n"],
                                 hovertemplate=f"<b>{label}</b> %{{x}}: %{{y:.1f}} %<br>%{{customdata}} Länder mit Daten<extra></extra>"))
    _styled(fig, f"{IND_TITLE[ind]} (% der Bevölkerung)")
    fig.update_yaxes(ticksuffix=" %")
    fig.update_xaxes(tickformat="d")
    out.append(_card(_graph(fig, 380)) if fig.data else _empty("Für die gewählten Länder gibt es bei dieser Kennzahl keine Daten."))
    if missing:
        out.append(_note("Keine Daten für: " + ", ".join(_name(c) for c in missing) + ". "
                         + ("Eurostat führt nur EU- und EFTA-Länder; für USA, China und Russland gibt es den internationalen "
                            "Migrantenbestand (UN DESA/Weltbank)." if ind != "stock" else ""), "fa-triangle-exclamation", FL_GOLD))

    # Ländervergleich Balken
    years = sorted(df["year"].unique())
    use = max([y for y in years if y <= year] or [years[0]])
    d = df[df["year"] == use].copy()
    if ind == "stock":
        pool = set(COUNTRY_NAMES)                         # Balken nur für die wählbaren Länder (übersichtlich)
        d = d[d["iso3"].isin(pool | set(countries))]
    elif ind in ("cit", "birth"):
        d = d[d["iso3"].isin(COUNTRY_NAMES)]
    d = d.sort_values("share")
    bars = go.Figure(go.Bar(
        x=d["share"], y=d["name"], orientation="h",
        marker_color=[FL_RED if c == LI else (ACCENT if c in countries else FL_BLUE) for c in d["iso3"]],
        customdata=list(zip(d["numer"], d["denom"])),
        hovertemplate="<b>%{y}</b>: %{x:.1f} %<br>%{customdata[0]:,.0f} von %{customdata[1]:,.0f}<extra></extra>"))
    _styled(bars, f"Ländervergleich {use} (Liechtenstein rot, Auswahl hellblau)", legend=False)
    bars.update_layout(hovermode="closest", height=max(340, 17 * len(d) + 80), margin=dict(l=110, r=20, t=50, b=40))
    bars.update_xaxes(ticksuffix=" %")
    out.append(_card(_graph(bars, max(340, 17 * len(d) + 80))))
    if use != year:
        out.append(_note(f"Für {year} liegen keine Werte vor; gezeigt wird das letzte verfügbare Jahr {use}."))
    src = {"cit": [("Eurostat migr_pop1ctz", URL["es"].format("migr_pop1ctz")), (ES_LICENSE, None)],
           "birth": [("Eurostat migr_pop3ctb", URL["es"].format("migr_pop3ctb")), (ES_LICENSE, None)],
           "stock": [("UN DESA International Migrant Stock via Weltbank SM.POP.TOTL.ZS", URL["wb"]), (WB_LICENSE, None)]}[ind]
    st = _stand(es_id("pop_cit") if ind == "cit" else es_id("pop_birth") if ind == "birth" else WB_KEY)
    out.append(_source(*src, (f"Stand der Daten: {st:%d.%m.%Y}" if st else "Stand unbekannt", None)))
    return out


# ── Abschnitt: Liechtenstein amtlich ──────────────────────────────────────────

def section_li():
    out = []
    pop = _g(pxs_id("li_pop_ctz"))
    if pop.empty:
        return [_empty("Keine Daten des Amts für Statistik in der Datenbank.")]
    pop = pop.assign(lab=pop["Staatsbürgerschaft"].map(_clean), Jahr=pop["Jahr"].astype(int))
    tot = pop[pop["lab"] == "Staatsbürgerschaft - Total"].set_index("Jahr")["Wert"]
    lie = pop[pop["lab"] == "Liechtenstein"].set_index("Jahr")["Wert"]
    nonperm = _g(pxs_id("li_nonperm"))
    npm = nonperm.assign(Jahr=nonperm["Jahr"].astype(int)).set_index("Jahr")["Wert"] if not nonperm.empty else pd.Series(dtype=float)
    years = sorted(tot.index)
    ausl = tot - lie

    kpis = []
    y = years[-1]
    kpis.append(dbc.Col(_kpi("fa-users", f"Ständige Wohnbevölkerung ({y})", f"{tot[y]:,.0f}".replace(",", "’"), FL_BLUE,
                             "31. Dezember, Amt für Statistik"), md=3, sm=6, className="mb-3"))
    kpis.append(dbc.Col(_kpi("fa-passport", f"Ausländische Staatsangehörige ({y})", f"{ausl[y] / tot[y] * 100:.1f} %".replace(".", ","),
                             FL_RED, f"{ausl[y]:,.0f} Personen".replace(",", "’")), md=3, sm=6, className="mb-3"))
    comm = _g(pxs_id("li_commuters"))
    cm = None
    if not comm.empty:
        c = comm[comm["Wohnland"].map(_clean) == "Ausland"]
        c = c[c["Wohnland"] == c["Wohnland"].iloc[0]] if not c.empty else c
        if not c.empty:
            cm = c.assign(Jahr=c["Jahr"].astype(int)).set_index("Jahr")["Wert"].dropna()
            yy = cm.index.max()
            kpis.append(dbc.Col(_kpi("fa-van-shuttle", f"Grenzgänger/Zupendler ({yy})", f"{cm[yy]:,.0f}".replace(",", "’"), GREEN,
                                     "Beschäftigte mit Wohnort im Ausland — nicht in der Wohnbevölkerung"), md=3, sm=6, className="mb-3"))
    if len(npm):
        yn = npm.index.max()
        kpis.append(dbc.Col(_kpi("fa-suitcase-rolling", f"Nichtständige Bevölkerung ({yn})", f"{npm[yn]:,.0f}".replace(",", "’"), FL_GOLD,
                                 "z. B. Kurzaufenthalter, Schutzsuchende"), md=3, sm=6, className="mb-3"))
    out.append(dbc.Row(kpis, className="g-3"))

    # (a) Bevölkerung nach Staatsangehörigkeit
    f1 = go.Figure()
    f1.add_trace(go.Bar(x=years, y=[lie[y] for y in years], name="Liechtensteiner", marker_color=FL_BLUE,
                        hovertemplate="%{x}: %{y:,.0f} Liechtensteiner<extra></extra>"))
    f1.add_trace(go.Bar(x=years, y=[ausl[y] for y in years], name="Ausländische Staatsangehörige", marker_color=FL_RED,
                        hovertemplate="%{x}: %{y:,.0f} Ausländer<extra></extra>"))
    _styled(f1, "Ständige Wohnbevölkerung nach Staatsangehörigkeit")
    f1.update_layout(barmode="stack")
    f1.update_xaxes(tickformat="d")
    f2 = go.Figure()
    f2.add_trace(go.Scatter(x=years, y=[ausl[y] / tot[y] * 100 for y in years], mode="lines+markers", name="Anteil Ausländer",
                            line=dict(color=FL_RED, width=2.8),
                            hovertemplate="%{x}: %{y:.1f} %<extra></extra>"))
    _styled(f2, "Ausländeranteil an der ständigen Wohnbevölkerung (%)", legend=False)
    f2.update_yaxes(ticksuffix=" %")
    f2.update_xaxes(tickformat="d")
    out.append(dbc.Row([dbc.Col(_card(_graph(f1)), md=6, className="mb-3"), dbc.Col(_card(_graph(f2)), md=6, className="mb-3")], className="g-3"))

    # (b) Abweichung der Definitionen
    f3 = go.Figure()
    f3.add_trace(go.Scatter(x=years, y=[ausl[y] / tot[y] * 100 for y in years], mode="lines+markers", name="Amt für Statistik: Staatsangehörigkeit (31.12.)",
                            line=dict(color=FL_RED, width=2.5)))
    for ind, name, col, dash in (("cit", "Eurostat: Staatsangehörigkeit (1.1.)", FL_GOLD, "dot"), ("birth", "Eurostat: im Ausland geboren (1.1.)", ACCENT, "solid"),
                                 ("stock", "UN DESA: internationaler Migrantenbestand (Jahresmitte)", GREEN, "dot")):
        d = share_table(ind)
        d = d[d["iso3"] == LI].sort_values("year") if not d.empty else d
        if not d.empty:
            f3.add_trace(go.Scatter(x=d["year"], y=d["share"], mode="lines+markers", name=name, line=dict(color=col, dash=dash, width=2)))
    _styled(f3, "Liechtenstein: dieselbe Bevölkerung, vier Definitionen (%)")
    f3.update_yaxes(ticksuffix=" %")
    f3.update_xaxes(tickformat="d", range=[1999, years[-1] + 1])
    out.append(_card(_graph(f3, 380)))
    out.append(_note("Warum die Linien auseinanderliegen: «Ausländer» zählt nur aktuelle Staatsbürgerschaften; «im Ausland geboren» "
                     "enthält Eingebürgerte; die UN-Reihe hat andere Stichtage und Modellierungen. Eurostat zählt zum 1. Januar, das Amt "
                     "zum 31. Dezember des Vorjahres (Abweichung durch Stichtag und Fortschreibung)."))

    # (c) Herkunft, Gemeinden
    last = pop[(pop["Jahr"] == y) & pop["Staatsbürgerschaft"].str.startswith("...")]
    last = last[last["lab"] != "Liechtenstein"].dropna(subset=["Wert"]).sort_values("Wert", ascending=False).head(12).sort_values("Wert")
    f4 = go.Figure(go.Bar(x=last["Wert"], y=last["lab"], orientation="h", marker_color=FL_BLUE,
                          hovertemplate="<b>%{y}</b>: %{x:,.0f}<extra></extra>"))
    _styled(f4, f"Häufigste Staatsangehörigkeiten der Wohnbevölkerung {y}", legend=False)
    f4.update_layout(hovermode="closest", margin=dict(l=130, r=20, t=50, b=40))
    gem = _g(pxs_id("li_pop_ctz_gem"))
    f5 = _empty("Keine Gemeindedaten.")
    if not gem.empty:
        gem = gem.assign(lab=gem["Staatsbürgerschaft"].map(_clean), Jahr=gem["Jahr"].astype(int))
        gg = gem[(gem["Jahr"] == y) & (gem["Wohngemeinde"] != "Liechtenstein")]
        pv = gg.pivot_table(index="Wohngemeinde", columns="lab", values="Wert")
        if "Liechtenstein" in pv.columns and "Staatsbürgerschaft - Total" in pv.columns:
            pv["share"] = (1 - pv["Liechtenstein"] / pv["Staatsbürgerschaft - Total"]) * 100
            pv = pv.sort_values("share")
            f5 = go.Figure(go.Bar(x=pv["share"], y=pv.index, orientation="h", marker_color=FL_RED,
                                  hovertemplate="<b>%{y}</b>: %{x:.1f} %<extra></extra>"))
            _styled(f5, f"Ausländeranteil je Gemeinde {y} (%)", legend=False)
            f5.update_layout(hovermode="closest", margin=dict(l=110, r=20, t=50, b=40))
            f5.update_xaxes(ticksuffix=" %")
            f5 = _card(_graph(f5))
    out.append(dbc.Row([dbc.Col(_card(_graph(f4)), md=6, className="mb-3"), dbc.Col(f5, md=6, className="mb-3")], className="g-3"))

    # (d) Grenzgänger
    if cm is not None and not comm.empty:
        c_all = comm.assign(Jahr=comm["Jahr"].astype(int), lab=comm["Wohnland"].map(_clean))
        f6 = go.Figure()
        for lab, col in (("Liechtenstein", FL_BLUE), ("Ausland", FL_RED)):
            d = c_all[(c_all["lab"] == lab) & (~c_all["Wohnland"].str.startswith("-"))].dropna(subset=["Wert"]).sort_values("Jahr")
            if not d.empty:
                f6.add_trace(go.Bar(x=d["Jahr"], y=d["Wert"], name=f"Wohnort {lab}", marker_color=col,
                                    hovertemplate=f"%{{x}}: %{{y:,.0f}} Beschäftigte, Wohnort {lab}<extra></extra>"))
        _styled(f6, "Beschäftigte in Liechtenstein nach Wohnland (Grenzgänger separat)")
        f6.update_layout(barmode="stack")
        f6.update_xaxes(tickformat="d")
        out.append(_card(_graph(f6)))
        out.append(_note("Grenzgänger/Zupendler arbeiten in Liechtenstein, wohnen aber im Ausland (v. a. Schweiz, Österreich, Deutschland). "
                         "Sie sind weder in der Wohnbevölkerung noch in den Ausländeranteilen oben enthalten."))
    # (e) Altersstruktur
    age = _g(pxs_id("li_age"))
    if not age.empty:
        a = age.assign(Jahr=age["Jahr"].astype(int))
        a = a[(a["Jahr"] == y) & (a["Altersjahr"] != "Altersjahr - Total")]
        a["age"] = pd.to_numeric(a["Altersjahr"], errors="coerce")
        a = a.dropna(subset=["age"])
        bands = [(0, 14, "0–14"), (15, 39, "15–39"), (40, 64, "40–64"), (65, 200, "65+")]
        rows = []
        for lo, hi, lab in bands:
            b = a[(a["age"] >= lo) & (a["age"] <= hi)]
            tot_b = b[b["Staatsbürgerschaft"] == "Staatsbürgerschaft - Total"]["Wert"].sum()
            lie_b = b[b["Staatsbürgerschaft"] == "Liechtenstein"]["Wert"].sum()
            rows.append((lab, tot_b, lie_b, tot_b - lie_b))
        if rows and sum(r[1] for r in rows):
            T, L_, A_ = sum(r[1] for r in rows), sum(r[2] for r in rows), sum(r[3] for r in rows)
            f7 = go.Figure()
            f7.add_trace(go.Bar(x=[r[0] for r in rows], y=[r[2] / L_ * 100 for r in rows], name="Liechtensteiner", marker_color=FL_BLUE))
            f7.add_trace(go.Bar(x=[r[0] for r in rows], y=[r[3] / A_ * 100 for r in rows], name="Ausländische Staatsangehörige", marker_color=FL_RED))
            _styled(f7, f"Altersstruktur nach Staatsangehörigkeit {y} (% der jeweiligen Gruppe)")
            f7.update_layout(barmode="group")
            f7.update_yaxes(ticksuffix=" %")
            f8 = go.Figure(go.Bar(x=[r[0] for r in rows], y=[r[3] / r[1] * 100 for r in rows], marker_color=FL_RED,
                                  hovertemplate="%{x}: %{y:.1f} % Ausländer<extra></extra>"))
            _styled(f8, f"Ausländeranteil nach Altersgruppe {y} (%)", legend=False)
            f8.update_yaxes(ticksuffix=" %")
            out.append(dbc.Row([dbc.Col(_card(_graph(f7)), md=6, className="mb-3"), dbc.Col(_card(_graph(f8)), md=6, className="mb-3")], className="g-3"))
            out.append(_note("Die Altersstruktur unterscheidet sich zwischen den Gruppen (Zugewanderte sind häufiger im Erwerbsalter). "
                             "Das beeinflusst jeden Vergleich von Raten (z. B. Straffälligkeit, Arbeitslosigkeit)."))
    st = _stand(pxs_id("li_pop_ctz"), pxs_id("li_commuters"))
    out.append(_source(("Amt für Statistik Liechtenstein: 211.002, 211.101, 211.006, 281.005 (opendata.li)", URL["li"]), (LI_LICENSE, None),
                       (f"Stand der Daten: {st:%d.%m.%Y}" if st else "Stand unbekannt", None)))
    return out


# ── Abschnitt: Wanderung, Einbürgerung, Asyl, Arbeitslosigkeit ───────────────

def _pop_total() -> pd.DataFrame:
    d = _g(es_id("pop_cit"))
    if d.empty:
        return d
    t = d[d["citizen"] == "TOTAL"]
    return t[["iso3", "time", "Wert"]].rename(columns={"Wert": "pop", "time": "year"}).assign(year=lambda x: x["year"].astype(int))


def _foreign_pop() -> pd.DataFrame:
    d = _g(es_id("pop_cit"))
    if d.empty:
        return d
    p = d.pivot_table(index=["iso3", "time"], columns="citizen", values="Wert").reset_index()
    p["foreign"] = p["TOTAL"] - p["NAT"]
    return p[["iso3", "time", "foreign", "NAT", "TOTAL"]].assign(year=lambda x: x["time"].astype(int))


def section_flows(countries: list[str]):
    out = []
    # LI Wanderung + Einbürgerungen
    mig = _g(pxs_id("li_migration"))
    nat = _g(pxs_id("li_naturalisation"))
    f1 = f2 = _empty("Keine Daten.")
    if not mig.empty:
        m = mig.assign(Jahr=mig["Jahr"].astype(int)).pivot_table(index="Jahr", columns="Richtung", values="Wert")
        if {"Einwanderung", "Auswanderung"} <= set(m.columns):
            f = go.Figure()
            f.add_trace(go.Bar(x=m.index, y=m["Einwanderung"], name="Einwanderung", marker_color=FL_BLUE))
            f.add_trace(go.Bar(x=m.index, y=-m["Auswanderung"], name="Auswanderung", marker_color=FL_RED,
                               customdata=m["Auswanderung"], hovertemplate="%{x}: %{customdata:,.0f} Auswanderung<extra></extra>"))
            f.add_trace(go.Scatter(x=m.index, y=m["Einwanderung"] - m["Auswanderung"], mode="lines+markers", name="Wanderungssaldo",
                                   line=dict(color=FL_GOLD, width=2.5)))
            _styled(f, "Liechtenstein: Zu- und Wegzüge (Personen)")
            f.update_layout(barmode="relative")
            f.update_xaxes(tickformat="d")
            f1 = _card(_graph(f))
    if not nat.empty:
        n = nat.assign(Jahr=nat["Jahr"].astype(int))
        n = n[n["Einbürgerungsart"].map(_clean) == "Einbürgerung - Total"].dropna(subset=["Wert"]).sort_values("Jahr")
        n = n[n["Jahr"] >= 1990]
        if not n.empty:
            f = go.Figure(go.Bar(x=n["Jahr"], y=n["Wert"], marker_color=GREEN, hovertemplate="%{x}: %{y:,.0f} Einbürgerungen<extra></extra>"))
            _styled(f, "Liechtenstein: Einbürgerungen (Personen)", legend=False)
            f.update_xaxes(tickformat="d")
            f2 = _card(_graph(f))
    out.append(dbc.Row([dbc.Col(f1, md=6, className="mb-3"), dbc.Col(f2, md=6, className="mb-3")], className="g-3"))
    out.append(_source(("Amt für Statistik Liechtenstein: 231.101, 232.001", URL["li"]), (LI_LICENSE, None)))

    # Eurostat: Einbürgerungen je 100 Ausländer, Asyl je 100 000
    fp = _foreign_pop()
    acq = _g(es_id("acq"))
    asy = _g(es_id("asylum"))
    pt = _pop_total()
    ca = go.Figure()
    cb = go.Figure()
    for i, c in enumerate(countries):
        col = _col(i, c)
        if not acq.empty and not fp.empty:
            a = acq[acq["iso3"] == c].assign(year=lambda x: x["time"].astype(int)).merge(fp[fp["iso3"] == c][["year", "foreign"]], on="year")
            if not a.empty:
                a = a.sort_values("year")
                ca.add_trace(go.Scatter(x=a["year"], y=a["Wert"] / a["foreign"] * 100, mode="lines+markers", name=_name(c),
                                        line=dict(color=col, width=2.8 if c == LI else 2),
                                        hovertemplate=f"<b>{_name(c)}</b> %{{x}}: %{{y:.2f}} %<extra></extra>"))
        if not asy.empty and not pt.empty:
            s = asy[asy["iso3"] == c].assign(year=lambda x: x["time"].astype(int)).merge(pt[pt["iso3"] == c][["year", "pop"]], on="year")
            if not s.empty:
                s = s.sort_values("year")
                cb.add_trace(go.Scatter(x=s["year"], y=s["Wert"] / s["pop"] * 1e5, mode="lines+markers", name=_name(c),
                                        line=dict(color=col, width=2.8 if c == LI else 2),
                                        hovertemplate=f"<b>{_name(c)}</b> %{{x}}: %{{y:,.0f}} je 100 000<extra></extra>"))
    _styled(ca, "Einbürgerungen je 100 ausländische Einwohner (%)")
    ca.update_yaxes(ticksuffix=" %")
    ca.update_xaxes(tickformat="d")
    _styled(cb, "Asylanträge je 100 000 Einwohner")
    cb.update_xaxes(tickformat="d")
    out.append(dbc.Row([dbc.Col(_card(_graph(ca)) if ca.data else _empty("Keine Daten."), md=6, className="mb-3"),
                        dbc.Col(_card(_graph(cb)) if cb.data else _empty("Keine Daten."), md=6, className="mb-3")], className="g-3"))
    out.append(_note("Einbürgerungsrate = Einbürgerungen eines Jahres / ausländische Wohnbevölkerung (1.1.); sie hängt von den "
                     "Voraussetzungen des Landes ab (Aufenthaltsdauer, Doppelbürgerschaft). Asylanträge: Erst- und Folgeanträge "
                     "je Jahr (Eurostat migr_asyappctza), Werte kleiner Länder schwanken stark."))
    st = _stand(es_id("acq"), es_id("asylum"), es_id("pop_cit"))
    out.append(_source(("Eurostat migr_acq, migr_asyappctza, migr_pop1ctz", URL["es"].format("migr_acq")), (ES_LICENSE, None),
                       (f"Stand der Daten: {st:%d.%m.%Y}" if st else "Stand unbekannt", None)))

    # Asyl LI + Arbeitslosigkeit nach Heimat
    asl = _g(pxs_id("li_asylum"))
    un = _g(pxs_id("li_unemp"))
    g1 = g2 = _empty("Keine Daten.")
    if not asl.empty:
        a = asl.assign(Jahr=asl["Jahr"].astype(int)).dropna(subset=["Wert"])
        f = go.Figure()
        for typ, col in (("Asylgesuche", FL_BLUE), ("Schutzgesuche", FL_GOLD)):
            d = a[a["Bewilligungstyp"] == typ].sort_values("Jahr")
            if not d.empty:
                f.add_trace(go.Bar(x=d["Jahr"], y=d["Wert"], name=typ, marker_color=col))
        if f.data:
            _styled(f, "Liechtenstein: Asyl- und Schutzgesuche (Personen)")
            f.update_layout(barmode="stack")
            f.update_xaxes(tickformat="d")
            g1 = _card(_graph(f))
    if not un.empty:
        u = un.assign(Jahr=un["Jahr"].astype(int))
        f = go.Figure()
        for heimat, col in (("Liechtensteiner", FL_BLUE), ("Ausländer", FL_RED), ("Heimat - Total", MUTED)):
            d = u[u["Heimat"] == heimat].dropna(subset=["Wert"]).sort_values("Jahr")
            if not d.empty:
                f.add_trace(go.Scatter(x=d["Jahr"], y=d["Wert"], mode="lines+markers", name=heimat.replace("Heimat - ", ""),
                                       line=dict(color=col, width=2.2)))
        if f.data:
            _styled(f, "Liechtenstein: Arbeitslosenquote nach Heimat (Jahresdurchschnitt, %)")
            f.update_yaxes(ticksuffix=" %")
            f.update_xaxes(tickformat="d")
            g2 = _card(_graph(f))
    out.append(dbc.Row([dbc.Col(g1, md=6, className="mb-3"), dbc.Col(g2, md=6, className="mb-3")], className="g-3"))
    out.append(_note("Arbeitslosenquote nach Heimat: registrierte Arbeitslose (Amt für Statistik) im Verhältnis zu den Beschäftigten; "
                     "Altersstruktur und Branchen unterscheiden sich zwischen den Gruppen. Eurostat-Reihen nach Geburtsland "
                     "(lfsa_urgacob) und Armutsgefährdung nach Geburtsland (ilc_li32) enthalten für Liechtenstein keine Werte "
                     "und werden deshalb nicht gezeigt.", "fa-triangle-exclamation", FL_GOLD))
    out.append(_source(("Amt für Statistik Liechtenstein: 233.201, 284.101", URL["li"]), (LI_LICENSE, None)))
    return out


# ── Abschnitt: Straffälligkeit ────────────────────────────────────────────────

CRIME_CAVEATS = [
    "Zähler und Nenner passen nicht zusammen: «Ausland» im Zähler enthält auch Personen ohne Wohnsitz (Touristen, Durchreisende, Grenzgänger, "
    "Pendler), der Nenner nur die ausländische Wohnbevölkerung. Die Rate für «Ausland» wird dadurch überschätzt — besonders in Liechtenstein, Luxemburg "
    "und anderen Ländern mit starkem Grenzverkehr.",
    "Alters- und Geschlechtsstruktur: Straftaten werden überwiegend von jungen Männern begangen; Gruppen mit anderem Alters-/Geschlechtsprofil "
    "haben deshalb auch bei gleichem Verhalten andere Raten. Die Raten sind nicht standardisiert.",
    "Anzeigeverhalten und Kontrollen: Es zählen angezeigte bzw. ermittelte Personen, nicht begangene Taten; Anzeigebereitschaft und "
    "Kontrollintensität können je nach Gruppe verschieden sein.",
    "Definitionen unterscheiden sich je Land (Verdächtige, Strafverfolgte, Verurteilte; Zählung von Personen/Fällen; Delikte, Jugendstrafrecht). "
    "Die Zahlen sind für Länder untereinander nur eingeschränkt vergleichbar; Trends im selben Land sind aussagekräftiger.",
    "«Ausländer» ist nicht «Migrant»: Eingebürgerte zählen als Inländer, Personen ohne Staatsangehörigkeitsangabe fehlen.",
    "Keine Aussage über Einzelne: Gruppenstatistiken erlauben keinen Rückschluss auf einzelne Personen.",
]


def section_crime_pointer():
    return _card([
        html.H6([html.I(className="fas fa-arrow-right", style={"marginRight": "8px", "color": ACCENT}),
                 "Straffälligkeit nach Staatsangehörigkeit: eigener Tab «Polizeistatistik»"], style={"color": TEXT}),
        html.P(["Kriminalitätszahlen (Landespolizei Liechtenstein, Eurostat-Ländervergleich mit Raten je Gruppe) stehen mit allen methodischen Hinweisen im Tab ",
                html.A("Polizeistatistik", href="?tab=polizei", className="source-link"),
                ". Sie werden dort einmalig gepflegt und hier nicht wiederholt."],
               style={"color": MUTED, "fontSize": "0.85rem", "marginBottom": "0"}),
    ])


# ── Abschnitt: Ausgaben ───────────────────────────────────────────────────────

def _chf(x, d=0) -> str:
    return f"{x:,.{d}f}".replace(",", "’")


def _mio(x) -> str:
    return f"{x / 1e6:,.1f}".replace(",", "’")


def _per_capita_block(d: pd.DataFrame) -> list:
    """Aufwand netto je Person im Bestand und je Einwohner (Näherungswerte, mit Hinweiskasten)."""
    pc = LR.per_capita_live()
    if pc.empty:
        return []
    last = int(pc.index.max())
    r = pc.loc[last]
    li = lambda *a: html.Li([html.B(a[0], style={"color": TEXT}), a[1]], style={"marginBottom": "4px"})
    out = [html.Div(style={"height": "6px"}), _card([
        html.H6([html.I(className="fas fa-triangle-exclamation", style={"marginRight": "8px", "color": FL_GOLD}),
                 "Je Person: Näherungswerte — bitte mit den Einschränkungen lesen"], style={"color": TEXT}),
        html.Ul([
            li("Zähler: ", "Aufwand netto auf Konto 590 (siehe oben). Er enthält nur dieses Konto — ohne Ämter, Gemeinden, Investitionen und ohne die Hilfe im Ausland."),
            li("Nenner je Person im Bestand: ",
               "Mittel aus dem Bestand am Ende des Vorjahres und am Ende des Berichtsjahres (Amt für Statistik 233.302, alle drei Status zusammen). "
               "Das ist die sauberste verfügbare Näherung an die durchschnittliche Zahl betreuter Personen über das Jahr, weil die Ausgaben laufend anfallen. "
               "Als zweite Linie ist der reine Jahresend-Bestand gezeigt. Die PX-Metadaten nennen den Stichtag nicht; der Wert für 2025 (939) entspricht "
               "der Mitteilung der Regierung von Ende Dezember 2025 (938 Personen) und wird deshalb als Jahresendstand gelesen."),
            li("Warum nur eine Näherung: ",
               "Ausgaben fallen auch für Personen an, die im Laufe des Jahres kamen oder gingen und am Stichtag nicht im Bestand waren; "
               "die Kosten enthalten ausserdem Teile (Verfahrens- und Verwaltungskosten, Rückkehrhilfe), die nicht je betreute Person entstehen. "
               "Bei stark wachsendem oder sinkendem Bestand weichen die beiden Nenner deutlich ab (etwa 2022)."),
            li("Sprung 2022: ",
               "Ab 2022 ist der Status «Schutzbedürftige» im Bestand enthalten (2022: 399 von 448 Personen). Die Landesrechnung weist keine Aufteilung nach Status "
               "oder Herkunft aus; deshalb gibt es die Kennzahl nur für den Gesamtbestand, nicht je Kategorie. Die Reihe vor und nach 2022 ist nicht direkt vergleichbar."),
            li("Je Einwohner: ",
               "Aufwand netto geteilt durch die ständige Wohnbevölkerung am Jahresende (Amt für Statistik 211.002). Damit ist «pro Kopf» der Gesamtbevölkerung gemeint, "
               "nicht der Asylsuchenden. Keine Wertung: Die Zahlen beschreiben Ausgaben, nicht deren Angemessenheit."),
        ], style={"color": MUTED, "fontSize": "0.8rem", "paddingLeft": "18px", "marginBottom": "0"}),
    ]), html.Div(style={"height": "10px"})]
    out.append(dbc.Row([
        dbc.Col(_kpi("fa-user", f"Je Person im Bestand {last}", f"CHF {_chf(r['je_person_avg'])}", FL_RED,
                     f"Mittelbestand {_chf(r['bestand_avg'])} Pers. · mit Jahresende-Bestand: CHF {_chf(r['je_person_end'])}"), md=6, sm=6, className="mb-3"),
        dbc.Col(_kpi("fa-people-group", f"Je Einwohner {last}", f"CHF {_chf(r['je_einwohner'])}", FL_BLUE,
                     f"Wohnbevölkerung {_chf(r['pop'])}"), md=6, sm=6, className="mb-3"),
    ], className="g-3"))
    f = go.Figure()
    q = pc.dropna(subset=["je_person_avg"])
    f.add_trace(go.Scatter(x=q.index, y=q["je_person_avg"], mode="lines+markers", name="Nenner: Mittel Vorjahr/Jahresende", line=dict(color=FL_RED, width=2.6),
                           hovertemplate="%{x}: CHF %{y:,.0f} je Person<extra>Mittelbestand</extra>"))
    f.add_trace(go.Scatter(x=q.index, y=q["je_person_end"], mode="lines+markers", name="Nenner: Bestand am Jahresende", line=dict(color=FL_GOLD, width=2, dash="dot"),
                           hovertemplate="%{x}: CHF %{y:,.0f} je Person<extra>Jahresende</extra>"))
    f.add_vline(x=2021.5, line_dash="dot", line_color=MUTED, annotation_text="ab 2022: Schutzbedürftige", annotation_font_color=MUTED, annotation_position="top left")
    _styled(f, "Netto je Person im Bestand (CHF)")
    f.update_layout(legend=dict(orientation="h", y=-0.28, bgcolor="rgba(0,0,0,0)"))
    f.update_xaxes(tickformat="d", dtick=2)
    f.update_yaxes(rangemode="tozero")
    f2 = go.Figure(go.Bar(x=pc.index, y=pc["je_einwohner"], marker_color=FL_BLUE, hovertemplate="%{x}: CHF %{y:,.0f} je Einwohner<extra></extra>"))
    _styled(f2, "Netto je Einwohner (CHF)", legend=False)
    f2.update_xaxes(tickformat="d", dtick=2)
    out.append(dbc.Row([dbc.Col(_card(_graph(f, 380)), md=6, className="mb-3"), dbc.Col(_card(_graph(f2, 380)), md=6, className="mb-3")], className="g-3"))
    out.append(_source(("Aufwand: Landesrechnung Konto 590 (siehe Tabelle unten)", None),
                       ("Bestand: Amt für Statistik 233.302, Bevölkerung: 211.002 (opendata.li), CC BY", URL["li"]),
                       ("Eigene Berechnung (Division), Näherung", None)))
    return out


def section_asyl_costs():
    """Ausgaben des Landes für das Asylwesen (Landesrechnung, Konto 590) und Bestand der Schutz- und Asylsuchenden."""
    d = LR.table()
    last = int(d.index.max())
    out = []
    for p in LR.pending():                                    # vom Worker gelesen, Prüfung nicht bestanden: nicht veröffentlicht
        out.append(_note(f"Neues Jahr wartet auf Prüfung: Der Rechenschaftsbericht zum Rechnungsjahr {int(p['year'])} wurde automatisch gelesen, die Werte sind aber nicht "
                         f"übernommen, weil die Prüfung nicht bestanden wurde ({p['note']}). Bis zur Sichtprüfung gelten die Zahlen bis {last}.", "fa-hourglass-half", FL_GOLD))
    # Abgrenzung
    out.append(_card([
        html.H6([html.I(className="fas fa-scale-balanced", style={"marginRight": "8px", "color": ACCENT}),
                 "Was ist in den Zahlen enthalten — und was nicht?"], style={"color": TEXT}),
        html.Ul([
            html.Li([html.B("Enthalten (Konto 590 «Flüchtlingswesen», Erfolgsrechnung): ", style={"color": TEXT}),
                     "Betreuung im Aufnahmezentrum, Verfahrenskosten, Rechtsberatungen und Verwaltungskosten der Hilfswerke sowie die "
                     "Sozialhilfe für Asylsuchende / Rückkehrhilfe. «Brutto» ist der Aufwand; «netto» ist der Aufwand abzüglich der "
                     "Rückerstattungen aus der Lohnverwaltung Asylsuchender (Ertrag)."], style={"marginBottom": "4px"}),
            html.Li([html.B("Nicht enthalten: ", style={"color": TEXT}),
                     "Personal- und Sachaufwand der Amtsstellen (z. B. Ausländer- und Passamt, Landespolizei, Gerichte), sonstige Leistungen "
                     "ausserhalb von Konto 590 (z. B. Schulen, Gesundheit, Prämienverbilligung), Ausgaben der Gemeinden sowie die "
                     "«Internationale Flüchtlings- und Migrationshilfe» (Konto 591.367.09, Hilfe im Ausland). Die Zahlen zeigen deshalb "
                     "nicht die gesamten öffentlichen Kosten des Asylbereichs, sondern die Ausgaben auf diesem Konto."], style={"marginBottom": "4px"}),
            html.Li([html.B("Investitionen getrennt: ", style={"color": TEXT}),
                     "«Wohnraum für Schutzbedürftige» (Investitionsrechnung, Konto 590.503.00) steht nicht im Aufwand: "
                     + ", ".join(f"{y}: CHF {_chf(v)}" for y, v in LR.INVEST.items()) + ". In den übrigen geprüften Jahren (2010–2022) gibt es dieses Konto nicht."
                    + (" Die Investitionsrechnung wird bei neuen, automatisch gelesenen Jahren nicht mitgelesen." if last > max(LR.INVEST) else "")],
                    style={"marginBottom": "4px"}),
            html.Li([html.B("Seit 2022 mit Schutzbedürftigen: ", style={"color": TEXT}),
                     "Die Bestandszahlen zeigen ab 2022 zusätzlich den Status «Schutzbedürftige» (Amt für Statistik). Die Landesrechnung "
                     "weist die Sozialhilfe aber unter derselben Bezeichnung aus; eine Aufteilung nach Status oder Herkunft gibt es dort nicht."],
                    style={"marginBottom": "0"}),
        ], style={"color": MUTED, "fontSize": "0.8rem", "paddingLeft": "18px", "marginBottom": "0"}),
    ]))
    out.append(html.Div(style={"height": "10px"}))
    # KPIs
    r = d.loc[last]
    p = d.loc[last - 1]
    out.append(dbc.Row([
        dbc.Col(_kpi("fa-file-invoice-dollar", f"Aufwand brutto {last}", f"CHF {_mio(r['aufwand'])} Mio.", FL_BLUE,
                     f"Vorjahr {_mio(p['aufwand'])} Mio. · 2020: {_mio(d.loc[2020, 'aufwand'])} Mio."), md=3, sm=6, className="mb-3"),
        dbc.Col(_kpi("fa-scale-balanced", f"Aufwand netto {last}", f"CHF {_mio(r['netto'])} Mio.", FL_GOLD, "nach Rückerstattungen Lohnverwaltung"), md=3, sm=6, className="mb-3"),
        dbc.Col(_kpi("fa-hand-holding-heart", "Sozialhilfe / Rückkehrhilfe", f"CHF {_mio(r[LR.COLS[3]])} Mio.", FL_RED,
                     f"{r[LR.COLS[3]] / r['aufwand'] * 100:.0f} % des Aufwands {last}"), md=3, sm=6, className="mb-3"),
        dbc.Col(_kpi("fa-house-user", "Betreuung Aufnahmezentrum", f"CHF {_mio(r[LR.COLS[0]])} Mio.", GREEN,
                     f"{r[LR.COLS[0]] / r['aufwand'] * 100:.0f} % des Aufwands {last}"), md=3, sm=6, className="mb-3"),
    ], className="g-3"))

    # Grafik 1: Aufwand nach Konto
    colors = [FL_BLUE, MUTED, ACCENT, FL_RED]
    f = go.Figure()
    for c, col in zip(LR.COLS, colors):
        f.add_trace(go.Bar(x=d.index, y=d[c] / 1e6, name=c, marker_color=col,
                           hovertemplate="%{x}: CHF %{y:.2f} Mio.<extra>" + c + "</extra>"))
    f.add_trace(go.Scatter(x=d.index, y=d["netto"] / 1e6, mode="lines+markers", name="Aufwand netto", line=dict(color=FL_GOLD, width=2.4),
                           hovertemplate="%{x}: CHF %{y:.2f} Mio. netto<extra></extra>"))
    f.update_layout(barmode="stack", legend=dict(orientation="h", y=-0.28, bgcolor="rgba(0,0,0,0)"))
    _styled(f, "Asylwesen: Aufwand des Landes, Konto 590 (Mio. CHF)")
    f.update_layout(legend=dict(orientation="h", y=-0.28, bgcolor="rgba(0,0,0,0)"))
    f.update_xaxes(tickformat="d", dtick=2)
    f.update_yaxes(ticksuffix="")
    g1 = _card(_graph(f, 400))

    # Grafik 2: Bestand + Gesuche
    st = _g(pxs_id("li_asyl_stock"))
    g2 = _empty("Keine Daten.")
    if not st.empty:
        s = st.assign(Jahr=st["Jahr"].astype(int)).dropna(subset=["Wert"])
        f2 = go.Figure()
        for typ, col in (("Asylbewerber/innen", FL_BLUE), ("Vorläufig Aufgenommene", FL_GOLD), ("Schutzbedürftige", FL_RED)):
            q = s[s["Bewilligungstyp"] == typ].sort_values("Jahr")
            q = q[q["Jahr"] >= 2009]
            if not q.empty:
                f2.add_trace(go.Bar(x=q["Jahr"], y=q["Wert"], name=typ, marker_color=col,
                                    hovertemplate="%{x}: %{y:,.0f} Personen<extra>" + typ + "</extra>"))
        if f2.data:
            f2.update_layout(barmode="stack", legend=dict(orientation="h", y=-0.28, bgcolor="rgba(0,0,0,0)"))
            _styled(f2, "Bestand Asyl- und Schutzbereich (Personen)")
            f2.update_layout(legend=dict(orientation="h", y=-0.28, bgcolor="rgba(0,0,0,0)"))
            f2.update_xaxes(tickformat="d", dtick=2)
            g2 = _card(_graph(f2, 400))
    out.append(dbc.Row([dbc.Col(g1, md=7, className="mb-3"), dbc.Col(g2, md=5, className="mb-3")], className="g-3"))
    out.append(_note("Kosten je Gesuch werden nicht gerechnet: Die Ausgaben fallen für den Bestand an Personen im Verfahren oder unter Schutz an "
                     "(über mehrere Jahre), nicht je neues Gesuch. Die Gesuchszahlen stehen oben in Abschnitt 3. Kennzahlen je Person im Bestand und "
                     "je Einwohner folgen als Näherung.", "fa-circle-info", ACCENT))
    out += _per_capita_block(d)

    # Tabelle mit Quellen je Jahr
    rows = []
    for y in sorted(d.index, reverse=True):
        v = d.loc[y]
        src = LR.all_sources()[y]
        rows.append(html.Tr([html.Td(str(y)), html.Td(_chf(v["aufwand"])), html.Td(_chf(v["ertrag"]) if v["ertrag"] else "–"), html.Td(_chf(v["netto"])),
                             html.Td(_chf(v[LR.COLS[3]])), html.Td(_chf(v[LR.COLS[0]])),
                             html.Td(html.A(f"{src[0]}, S. {src[2]}", href=src[1], target="_blank", rel="noopener noreferrer", className="source-link")),
                             html.Td(src[3], style={"color": FL_GOLD})]))
    out.append(_card([
        html.H6("Zahlen und Fundstellen je Rechnungsjahr (CHF)", style={"color": TEXT}),
        html.Div(html.Table([html.Thead(html.Tr([html.Th(h) for h in ("Jahr", "Aufwand brutto", "Ertrag", "Aufwand netto", "Sozialhilfe / Rückkehrhilfe",
                                                                       "Betreuung Aufnahmezentrum", "Fundstelle (Landesrechnung, Konto 590)", "Hinweis")])),
                             html.Tbody(rows)], className="od-table"), style={"maxHeight": "420px", "overflowY": "auto", "overflowX": "auto"}),
    ]))
    out.append(_note("Seitenzahlen beziehen sich auf den Rechenschaftsbericht (Teil IV Landesrechnung, «Konten der Erfolgsrechnung»). Die Jahre bis 2025 wurden von Hand mit der "
                     "Vorjahresspalte des folgenden Berichts und mit der Summe der Teilkonten verglichen; neuere Jahre liest der Worker automatisch und übernimmt sie nur nach "
                     f"bestandener Summen- und Vorjahresprüfung (jüngstes Rechnungsjahr: {last}). Vor 2009 wurde nicht ausgewertet. Kontoname bis 2010: «Betreuung Flüchtlingszentrum», «Sozialhilfe für Flüchtlinge / Rückkehrhilfe».",
                     "fa-file-pdf", MUTED))
    st_ts = _stand(pxs_id("li_asyl_stock"))
    out.append(_source(("Landesrechnung des Fürstentums Liechtenstein (Regierungskanzlei / Amt für Finanzen), Konto 590", "https://www.llv.li/de/landesverwaltung/amt-fuer-finanzen/wissenswertes/landesrechnung"),
                       ("Amtliche Publikation, Quellenangabe je Jahr in der Tabelle", None),
                       ("Bestand: Amt für Statistik 233.302 (opendata.li), CC BY", URL["li"]),
                       (f"Stand Bestand: {st_ts:%d.%m.%Y}" if st_ts else "Stand Bestand unbekannt", None)))
    return out


def section_costs():
    return _card([
        html.H6([html.I(className="fas fa-circle-info", style={"marginRight": "8px", "color": ACCENT}),
                 "Ausgaben je Migrant: keine belastbaren, vergleichbaren Daten"], style={"color": TEXT}),
        html.P("Geprüft wurden Eurostat (keine Sozialschutzausgaben nach Staatsangehörigkeit oder Geburtsland), die OECD (International "
               "Migration Outlook: fiskalische Effekte als modellbasierte Einzelstudien mit länderspezifischen Annahmen, ohne einheitliche "
               "Datenreihe) und Liechtenstein (die Ausgaben für das Asylwesen sind oben aus der Landesrechnung als Gesamtbeträge je Konto gezeigt; "
               "Sozialhilfe und übrige Leistungen liegen ohne Aufteilung nach Herkunft oder Staatsangehörigkeit vor). Wirkungen von Zuwanderung auf "
               "öffentliche Haushalte hängen zudem von Alter, Aufenthaltsdauer, Qualifikation und Berechnungsmethode ab und lassen sich nicht "
               "aus Einzelzahlen ableiten. Deshalb zeigt dieser Tab dazu bewusst keine Zahlen und rechnet nicht mit Schätzwerten aus dritten "
               "Quellen.", style={"color": MUTED, "fontSize": "0.85rem", "marginBottom": "0"}),
    ])


# ── Render ────────────────────────────────────────────────────────────────────

def render_migration(data: dict) -> html.Div:
    ind = data.get("mig_ind") or "cit"
    countries = [c for c in (data.get("mig_countries") or DEFAULT_COUNTRIES) if c in COUNTRY_NAMES] or DEFAULT_COUNTRIES
    groups = [g for g in (data.get("mig_groups") or []) if g in GROUPS]
    year = int(data.get("mig_year") or DEFAULT_YEAR)
    if _g(es_id("pop_cit")).empty and _g(WB_KEY).empty:
        return html.Div([html.H4("Migration", className="section-title"),
                         _empty("Noch keine Daten in der Datenbank — der wöchentliche Abruf füllt sie.")])
    return html.Div([
        html.H4("Migration – Zahlen, Definitionen, Quellen", className="section-title"),
        how_to_read(),
        _section("1 · Anteil an der Bevölkerung", "Liechtenstein im Vergleich; Länder und Gruppen in der Seitenleiste wählbar."),
        *section_share(ind, countries, groups, year),
        _section("2 · Liechtenstein im Detail (Amt für Statistik)",
                 "Amtliche Zahlen zur Wohnbevölkerung nach Staatsangehörigkeit, Grenzgänger getrennt ausgewiesen."),
        *section_li(),
        _section("3 · Wanderung, Einbürgerung, Asyl, Arbeitsmarkt"),
        *section_flows(countries),
        _section("4 · Straffälligkeit nach Staatsangehörigkeit"),
        section_crime_pointer(),
        _section("5 · Kosten", "Ausgaben des Landes für das Asylwesen (Landesrechnung) und warum es keine Ausgaben je Migrant gibt."),
        *section_asyl_costs(),
        html.Div(style={"height": "10px"}),
        section_costs(),
    ])
