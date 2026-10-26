"""
tab_prognose.py — Tab «Prognosen»
=================================
Transparente Projektionen mit 80-/95-%-Unsicherheitsband. Die Berechnung (ETS, ARIMA, Theta, Drift, Naive Basis, Rückwärtstest) läuft im Worker
(forecast.py) und liegt in fc_results; dieser Tab liest nur. Eine Projektion wird nur gezeigt, wenn die Reihe lang genug ist und die beste Methode die
naive Basis im Rückwärtstest klar schlägt — sonst steht hier ausdrücklich «keine Projektion» samt Begründung.
Die Szenarien des Amts für Statistik und die IWF-Projektionen stehen getrennt daneben, nie in die eigene Projektion eingerechnet.
"""

import math
import re

import dash_bootstrap_components as dbc
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import dcc, html

import db
import forecast as F
from ui import FL_BLUE, FL_RED, FL_GOLD, ACCENT, GREEN, MUTED, TEXT, BORDER, _card, _kpi, _styled, _empty

DEFAULT_SERIES = "pop_amt"
DEFAULT_THR = 45000
METHOD_COLORS = {"naive": MUTED, "drift": FL_GOLD, "ets": GREEN, "arima": "#BC8CFF", "theta": "#F0883E"}

# Eigene Reihe → IWF-WEO-Indikator (Faktor auf Reihen-Einheit). Nur dort, wo die Grösse inhaltlich dieselbe ist.
IMF_MAP = {
    "pop_wb":  ("LP", 1e6, "Bevölkerung (IWF WEO, Mio. → Personen)"),
    "gdp_usd": ("NGDPD", 1e9, "BIP in laufenden USD (IWF WEO, Mrd. → USD)"),
    "gdp_pc":  ("NGDPDPC", 1.0, "BIP pro Kopf in laufenden USD (IWF WEO)"),
}
SCEN_SERIES = "pop_amt"          # Amt-für-Statistik-Szenarien gelten für die ständige Wohnbevölkerung
SCEN_COLORS = ["#58A6FF", "#CE1126", "#3FB950", "#D4A017", "#BC8CFF", "#F0883E", "#79C0FF", "#FF7B72", "#7EE787"]


# ── Sidebar ───────────────────────────────────────────────────────────────────

def sidebar_section() -> html.Div:
    return html.Div(id="filter-fc", children=[
        html.Div([html.Label("Reihe", className="filter-label"),
                  dcc.Dropdown(id="fc-series", options=[{"label": v[0], "value": k} for k, v in F.SERIES.items()], value=DEFAULT_SERIES, clearable=False,
                               searchable=False, className="fl-dropdown", optionHeight=44)], className="filter-section"),
        html.Div([html.Label("Schwellenwert (Rechner)", className="filter-label"),
                  dcc.Input(id="fc-thr", type="number", value=DEFAULT_THR, debounce=True, min=0, step=500, className="share-input", style={"width": "100%"}),
                  html.Small("«Wann erreicht die Reihe diesen Wert?» — mit Intervall.", style={"color": MUTED, "fontSize": "0.7rem"})], className="filter-section"),
        html.Div([html.Label("Darstellung", className="filter-label"),
                  dcc.Checklist(id="fc-opts", options=[{"label": " Alle Methoden zeigen", "value": "all"}], value=[], className="fl-checklist",
                                labelClassName="checklist-label")], className="filter-section"),
    ])


# ── Hilfen ────────────────────────────────────────────────────────────────────

def _num(x, d=0) -> str:
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "–"
    return f"{x:,.{d}f}".replace(",", "’")


def _warn(text, level="warn"):
    color = FL_RED if level == "danger" else FL_GOLD if level == "warn" else ACCENT
    icon = "fa-circle-exclamation" if level == "danger" else "fa-triangle-exclamation" if level == "warn" else "fa-circle-info"
    return html.Div([html.I(className=f"fas {icon}", style={"marginRight": "8px", "color": color}), text],
                    style={"color": TEXT, "fontSize": "0.82rem", "padding": "8px 12px", "marginBottom": "8px", "background": "#161B22",
                           "border": f"1px solid {color}", "borderRadius": "6px"})


def _graph(fig, h=380):
    fig.update_layout(height=h)
    return dcc.Graph(figure=fig, config={"displayModeBar": False})


def _phi(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def how_to_read() -> html.Div:
    def item(t, x):
        return html.Li([html.B(t + ": ", style={"color": TEXT}), x], style={"marginBottom": "4px"})
    return _card([
        html.H6([html.I(className="fas fa-book-open", style={"marginRight": "8px", "color": ACCENT}), "Wie lesen? Projektion, keine Vorhersage"], style={"color": TEXT}),
        html.Ul([
            item("Projektion, keine Vorhersage", "Die Linien schreiben das statistische Muster der bisherigen Jahreswerte fort. Krisen, Gesetze, Zu- und Abwanderungs-Entscheide, "
                 "Statistikumstellungen oder Pandemien sind nicht modelliert. Was in der Vergangenheit nicht vorkam, kann das Modell nicht «wissen»."),
            item("Unsicherheitsband", "Dunkel = 80 %, hell = 95 %. Das Band bildet nur die statistische Unsicherheit des Modells ab (Schwankungen der bisherigen Jahre), nicht die "
                 "Unsicherheit über Strukturbrüche. Es wird mit dem Horizont breiter. Ob es in der Vergangenheit zutraf, zeigt die Spalte «Abdeckung» im Rückwärtstest."),
            item("Methoden", "Naive Basis (letzter Wert bleibt), Drift (mittlere Jahresveränderung), ETS (exponentielle Glättung, Trend/gedämpft nach AICc), ARIMA (kleine Auswahl nach AICc), "
                 "Theta (θ = 2). Gezeigt wird die Methode mit dem besten Rückwärtstest."),
            item("Rückwärtstest", "Die Methoden werden wiederholt auf einem Ausschnitt der Vergangenheit angepasst und gegen die danach tatsächlich eingetretenen Werte (1–3 Jahre voraus) "
                 "geprüft (rolling origin, ab 60 % der Reihe). MASE = mittlerer Fehler ÷ mittlerer Einjahres-Fehler der naiven Basis in der Anfangsstichprobe: "
                 "< 1 heisst besser als «bleibt wie zuletzt», > 1 schlechter."),
            item("Wann keine Projektion?", f"Wenn weniger als {F.MIN_N} aufeinanderfolgende Jahreswerte vorliegen, oder keine Methode die naive Basis um mindestens 5 % schlägt, oder die beste Methode "
                 f"einen MASE über {F.MAX_MASE:.0f} hat. Dann zeigen wir bewusst nichts — eine Linie mit Intervall würde Genauigkeit vortäuschen, die es nicht gibt."),
            item("Wenige Prüfpunkte", "Der Rückwärtstest hat bei kurzen Reihen nur wenige Startpunkte (siehe «Prüfpunkte»); seine Aussagekraft ist begrenzt."),
            item("Amt für Statistik / IWF", "Die Bevölkerungsszenarien des Amts für Statistik und die IWF-Projektionen sind eigene Rechnungen mit eigenen Annahmen. Sie stehen getrennt daneben und "
                 "sind nie mit der statistischen Projektion vermischt."),
        ], style={"color": MUTED, "fontSize": "0.8rem", "paddingLeft": "18px", "marginBottom": "0"}),
    ])


# ── Schwellenrechner ──────────────────────────────────────────────────────────

def crossing(fc: dict, thr: float, last_val: float) -> dict:
    """Wann überschreitet (bzw. unterschreitet) die zentrale Projektion den Schwellenwert? Punktweise Wahrscheinlichkeit je Jahr aus dem 80-%-Band (Normalnäherung)."""
    up = thr >= last_val
    yrs = fc["years"]
    mean, lo, hi = np.array(fc["mean"]), np.array(fc["lo80"]), np.array(fc["hi80"])
    sd = np.maximum((hi - lo) / (2 * F.Z80), 1e-9)
    p = np.array([_phi((m - thr) / s) if up else _phi((thr - m) / s) for m, s in zip(mean, sd)])
    first = lambda mask: (yrs[int(np.argmax(mask))] if mask.any() else None)
    reached = (mean >= thr) if up else (mean <= thr)
    return {"up": up, "years": yrs, "p": p, "central": first(reached), "early": first(p >= 0.10), "late": first(p >= 0.90), "p_end": float(p[-1]),
            "p50": first(p >= 0.5)}


def calculator(payload: dict, thr, last_val: float, last_year: int, unit: str):
    fc = payload["forecasts"][payload["best"]]
    if thr is None:
        return None
    ex = crossing(fc, float(thr), last_val)
    horizon_end = fc["years"][-1]
    word = "erreicht" if ex["up"] else "unterschreitet"
    if (ex["up"] and last_val >= thr) or (not ex["up"] and last_val <= thr):
        head, sub = "bereits erreicht", f"Der letzte beobachtete Wert ({_num(last_val)} im Jahr {last_year}) liegt schon {'über' if ex['up'] else 'unter'} {_num(thr)}."
    elif ex["central"] is None:
        head = f"nach {horizon_end}"
        sub = (f"Innerhalb des Prognosehorizonts (bis {horizon_end}) erreicht die zentrale Projektion {_num(thr)} nicht; die Wahrscheinlichkeit für {horizon_end} liegt bei "
               f"{ex['p_end'] * 100:.0f} %." + (f" Frühester möglicher Zeitpunkt im 80-%-Band: {ex['early']}." if ex["early"] else ""))
    else:
        head = str(ex["central"])
        early = ex["early"] if ex["early"] is not None else "–"
        late = str(ex["late"]) if ex["late"] is not None else f"nach {horizon_end}"
        sub = (f"Zentrale Projektion {word} {_num(thr)} im Jahr {ex['central']}. 80-%-Bereich: frühestens {early}, spätestens {late} "
               "(Jahr, ab dem der Wert mit ≥ 10 % bzw. ≥ 90 % Wahrscheinlichkeit erreicht ist).")
    rows = []
    for y, p, m in zip(ex["years"], ex["p"], fc["mean"]):
        rows.append(html.Tr([html.Td(str(y)), html.Td(_num(m)), html.Td(f"{p * 100:.0f} %")]))
    return _card([
        html.H6([html.I(className="fas fa-calculator", style={"marginRight": "8px", "color": ACCENT}), f"Schwellenrechner: Wann {word} die Reihe {_num(thr)} {unit}?"], style={"color": TEXT}),
        dbc.Row([dbc.Col(_kpi("fa-calendar-check", "Zentrale Projektion", head, FL_RED, "Methode: " + payload["methods"][payload["best"]]["name"]), md=4, className="mb-2"),
                 dbc.Col(html.P(sub, style={"color": TEXT, "fontSize": "0.85rem", "marginTop": "6px"}), md=8)], className="g-3"),
        html.Details([html.Summary("Wahrscheinlichkeit je Jahr anzeigen", style={"color": ACCENT, "fontSize": "0.8rem", "cursor": "pointer"}),
                      html.Div(html.Table([html.Thead(html.Tr([html.Th("Jahr"), html.Th("Zentralwert"), html.Th(f"P(Wert {'≥' if ex['up'] else '≤'} {_num(thr)})")])), html.Tbody(rows)],
                                          className="od-table"), style={"overflowX": "auto", "maxHeight": "320px", "overflowY": "auto"})]),
        html.P("Die Wahrscheinlichkeiten gelten je einzelnes Jahr (Normalnäherung aus dem 80-%-Band) und setzen voraus, dass das Modell stimmt. Sie sind keine Aussage über "
               "politische oder wirtschaftliche Entwicklungen. Projektion, keine Vorhersage.", style={"color": MUTED, "fontSize": "0.78rem", "marginBottom": "0", "marginTop": "8px"}),
    ])


# ── Diagramme ─────────────────────────────────────────────────────────────────

def _rgba(hexcol: str, a: float) -> str:
    h = hexcol.lstrip("#")
    return f"rgba({int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)},{a})"


def chart(payload: dict, show_all: bool) -> go.Figure:
    hist = payload["history"]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=hist["years"], y=hist["values"], name="Beobachtet", mode="lines+markers", line=dict(color=TEXT, width=2.4), marker=dict(size=5)))
    if payload.get("decision") == "forecast":
        best = payload["best"]
        fcs = payload["forecasts"]
        fc = fcs[best]
        x0, y0 = hist["years"][-1], hist["values"][-1]
        xs = [x0] + fc["years"]
        col = METHOD_COLORS.get(best, FL_RED)
        for lo, hi, a, nm in (("lo95", "hi95", 0.14, "95 %-Band"), ("lo80", "hi80", 0.28, "80 %-Band")):
            fig.add_trace(go.Scatter(x=xs + xs[::-1], y=[y0] + fc[hi] + ([y0] + fc[lo])[::-1], fill="toself", fillcolor=_rgba(col, a), line=dict(width=0),
                                     name=nm, hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=xs, y=[y0] + fc["mean"], name=f"Projektion ({payload['methods'][best]['name']})", mode="lines", line=dict(color=col, width=2.6, dash="dash"),
                                 hovertemplate="%{x}: %{y:,.0f}<extra></extra>"))
        if show_all:
            for k, f in fcs.items():
                if k == best:
                    continue
                fig.add_trace(go.Scatter(x=[x0] + f["years"], y=[y0] + f["mean"], name=payload["methods"].get(k, {}).get("name", k), mode="lines",
                                         line=dict(color=METHOD_COLORS.get(k, MUTED), width=1.4, dash="dot")))
    _styled(fig, payload["label"] + (" — Projektion, keine Vorhersage" if payload.get("decision") == "forecast" else " — keine Projektion"))
    fig.update_layout(legend=dict(orientation="h", y=-0.2, bgcolor="rgba(0,0,0,0)"))
    fig.update_xaxes(tickformat="d")
    fig.update_yaxes(title=payload.get("unit", ""))
    return fig


def quality_table(payload: dict) -> html.Div:
    ms = payload.get("methods") or {}
    if not ms:
        return html.Div()
    best = payload.get("best")
    rows = []
    for k, m in ms.items():
        is_best = k == best
        cov_ok = abs(m["cov80"] - 0.8) <= 0.15
        rows.append(html.Tr([
            html.Td([m["name"], html.Span(" ◀ beste" if is_best else "", style={"color": FL_RED, "fontSize": "0.72rem"}),
                     html.Span(" (Basis)" if k == "naive" else "", style={"color": MUTED, "fontSize": "0.72rem"})], style={"fontWeight": "700" if is_best else "400"}),
            html.Td(f"{m['mase']:.2f}".replace(".", ","), style={"color": GREEN if m["mase"] < 1 else TEXT}),
            html.Td(_num(m["mae"], 0 if m["mae"] > 100 else 2)),
            html.Td(f"{m['cov80'] * 100:.0f} %", style={"color": TEXT if cov_ok else FL_GOLD}),
            html.Td(f"{m['cov95'] * 100:.0f} %"),
            html.Td(f"{m['n_forecasts']} ({m['n_origins']} Startpunkte)"),
        ]))
    return _card([
        html.H6("Rückwärtstest: Wie gut war jede Methode in der Vergangenheit?", style={"color": TEXT}),
        html.Div(html.Table([html.Thead(html.Tr([html.Th(h) for h in ("Methode", "MASE", "Mittl. Fehler", "Abdeckung 80 % (Soll 80)", "Abdeckung 95 % (Soll 95)", "Prüfpunkte")])),
                             html.Tbody(rows)], className="od-table"), style={"overflowX": "auto"}),
        html.P("MASE < 1: besser als die naive Basis (letzter Wert bleibt). Abdeckung = Anteil der tatsächlich eingetretenen Werte im Band; liegt sie deutlich unter dem Soll, "
               "sind die Bänder zu eng. Mittlerer Fehler in der Einheit der Reihe, Horizonte 1–3 Jahre.", style={"color": MUTED, "fontSize": "0.78rem", "marginBottom": "0", "marginTop": "8px"}),
    ])


def overview_table(all_fc: dict) -> html.Div:
    rows = []
    for sid, (label, unit, cid, h) in F.SERIES.items():
        row = all_fc.get(sid)
        if not row:
            rows.append(html.Tr([html.Td(label), html.Td("–"), html.Td("noch nicht berechnet", style={"color": MUTED}), html.Td("–"), html.Td("–")]))
            continue
        p = row["payload"]
        ok = p.get("decision") == "forecast"
        best = p.get("best")
        ms = p.get("methods") or {}
        rows.append(html.Tr([
            html.Td(label), html.Td(str(p.get("n", "–"))),
            html.Td("Projektion" if ok else "keine Projektion", style={"color": GREEN if ok else FL_GOLD, "fontWeight": "600"}),
            html.Td(f"{ms[best]['name']} {ms[best]['mase']:.2f}".replace(".", ",") if best in ms else "–"),
            html.Td(f"{ms['naive']['mase']:.2f}".replace(".", ",") if "naive" in ms else "–"),
        ]))
    return _card([
        html.H6("Alle Reihen im Überblick", style={"color": TEXT}),
        html.Div(html.Table([html.Thead(html.Tr([html.Th(h) for h in ("Reihe", "Jahre (n)", "Ergebnis", "Beste Methode (MASE)", "Naive Basis (MASE)")])), html.Tbody(rows)], className="od-table"),
                 style={"overflowX": "auto"}),
    ])


# ── Amt für Statistik / IWF (getrennt) ────────────────────────────────────────

def scenarios_block(hist: dict, thr) -> html.Div | None:
    df, info = db.get_px("pxs:li_scen", max_age_hours=None)
    if df is None or df.empty:
        return None
    d = df.copy()
    d["Jahr"] = pd.to_numeric(d["Jahr"], errors="coerce")
    d["Wert"] = pd.to_numeric(d["Wert"], errors="coerce")
    d = d.dropna(subset=["Jahr", "Wert"])
    names = list(dict.fromkeys(d["Szenario"]))
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=hist["years"], y=hist["values"], name="Beobachtet", mode="lines", line=dict(color=TEXT, width=2.2)))
    rows = []
    for i, nm in enumerate(names):
        s = d[d["Szenario"] == nm].sort_values("Jahr")
        fig.add_trace(go.Scatter(x=s["Jahr"], y=s["Wert"], name=nm, mode="lines", line=dict(color=SCEN_COLORS[i % len(SCEN_COLORS)], width=1.8, dash="dot" if nm != "Trend" else "solid")))
        cross = None
        if thr is not None:
            hit = s[s["Wert"] >= float(thr)]
            cross = int(hit["Jahr"].iloc[0]) if not hit.empty else None
        rows.append(html.Tr([html.Td(nm), html.Td(_num(s["Wert"].iloc[-1])), html.Td(str(int(s["Jahr"].iloc[-1]))),
                             html.Td(str(cross) if cross else (f"nicht bis {int(s['Jahr'].iloc[-1])}" if thr is not None else "–"))]))
    _styled(fig, "Amt für Statistik: Bevölkerungsszenarien 2023–2060")
    fig.update_layout(legend=dict(orientation="h", y=-0.3, bgcolor="rgba(0,0,0,0)"))
    fig.update_xaxes(tickformat="d")
    return html.Div([
        html.H5("Zum Vergleich: Szenarien des Amts für Statistik", className="section-title", style={"marginTop": "14px"}),
        _warn("Eigene Rechnung des Amts für Statistik mit demografischen Annahmen (Geburten, Lebenserwartung, Wanderung). Sie steht hier getrennt neben der statistischen "
              "Projektion oben und ist nicht mit ihr vermischt. Die Szenarien haben kein Wahrscheinlichkeitsband.", "info"),
        _card(_graph(fig, 400)),
        _card([html.H6(f"Wann erreicht das Szenario {_num(thr)} Personen?" if thr is not None else "Szenarien", style={"color": TEXT}),
               html.Div(html.Table([html.Thead(html.Tr([html.Th(h) for h in ("Szenario", "Endwert", "Letztes Jahr", "Schwelle erreicht")])), html.Tbody(rows)], className="od-table"),
                        style={"overflowX": "auto"})]),
        html.Div([html.I(className="fas fa-database", style={"marginRight": "6px", "color": MUTED}), html.Span("Quelle: ", style={"color": MUTED}),
                  html.A("Amt für Statistik, Bevölkerungsszenarien (opendata.li, 219.004d)", href="https://www.opendata.li/de/daten", target="_blank", rel="noopener noreferrer",
                         className="source-link")], className="source-bar"),
    ])


def _imf_edition_year() -> int:
    src, _ = db.read_imf_info()
    m = re.search(r"(20\d\d)", src or "")
    return int(m.group(1)) if m else 2026


def imf_block(sid: str, hist: dict) -> html.Div | None:
    if sid not in IMF_MAP:
        return None
    ind, factor, label = IMF_MAP[sid]
    d = db.read_imf(ind)
    if d.empty:
        return None
    src, _ = db.read_imf_info()
    ed = _imf_edition_year()
    d = d.dropna()
    act, prj = d[d["year"] < ed], d[d["year"] >= ed]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=act["year"], y=act["value"] * factor, name="IWF Ist-Werte", mode="lines", line=dict(color=ACCENT, width=2.2)))
    if not prj.empty:
        x0 = act["year"].iloc[-1] if not act.empty else prj["year"].iloc[0]
        y0 = act["value"].iloc[-1] * factor if not act.empty else prj["value"].iloc[0] * factor
        fig.add_trace(go.Scatter(x=[x0] + list(prj["year"]), y=[y0] + list(prj["value"] * factor), name="IWF-Projektion", mode="lines+markers",
                                 line=dict(color=FL_RED, width=2.2, dash="dash"), marker=dict(size=5)))
    _styled(fig, label)
    fig.update_xaxes(tickformat="d")
    fig.update_layout(legend=dict(orientation="h", y=-0.2, bgcolor="rgba(0,0,0,0)"))
    return html.Div([
        html.H5("Zum Vergleich: IWF-Projektion", className="section-title", style={"marginTop": "14px"}),
        _warn(f"Die Projektion des IWF ({src or 'World Economic Outlook'}) ist eine eigene Rechnung mit eigenen Annahmen und steht getrennt neben der statistischen Projektion; "
              "Definitionen und Revisionen können von der Weltbank-Reihe abweichen. Ein Unsicherheitsband liefert der IWF nicht.", "info"),
        _card(_graph(fig, 360)),
        html.Div([html.I(className="fas fa-database", style={"marginRight": "6px", "color": MUTED}), html.Span("Quelle: ", style={"color": MUTED}),
                  html.A("IWF World Economic Outlook (DataMapper)", href="https://www.imf.org/external/datamapper", target="_blank", rel="noopener noreferrer", className="source-link")],
                 className="source-bar"),
    ])


# ── Auswertung ────────────────────────────────────────────────────────────────

def render_prognose(data: dict) -> html.Div:
    sid = data.get("fc_series") or DEFAULT_SERIES
    if sid not in F.SERIES:
        sid = DEFAULT_SERIES
    thr = data.get("fc_thr")
    show_all = "all" in (data.get("fc_opts") or [])
    out = [html.H4("Prognosen", className="section-title"), how_to_read(), html.Div(style={"height": "12px"})]
    all_fc = db.read_fc_all()
    row = all_fc.get(sid)
    if not row:
        out += [_empty("Für diese Reihe liegt noch keine Berechnung vor. Der Worker rechnet die Projektionen wöchentlich (Daten fehlen oder erster Lauf steht aus)."),
                overview_table(all_fc)]
        return html.Div(out)
    p = row["payload"]
    out.append(html.H5(p["label"], style={"color": TEXT, "fontSize": "1rem"}))
    hist = p["history"]
    last_val, last_year = hist["values"][-1], hist["years"][-1]
    ok = p.get("decision") == "forecast"

    if ok:
        best = p["best"]
        m = p["methods"][best]
        fc = p["forecasts"][best]
        out.append(_warn("Projektion, keine Vorhersage: fortgeschriebenes Muster der Vergangenheit; Strukturbrüche sind nicht enthalten, das Band zeigt nur statistische Unsicherheit.", "info"))
        if m["cov80"] < 0.65:
            out.append(_warn(f"Im Rückwärtstest lagen nur {m['cov80'] * 100:.0f} % der tatsächlichen Werte im 80-%-Band: Das Band ist vermutlich zu eng. Vorsicht bei der Lesart.", "warn"))
        if m["n_origins"] < 8:
            out.append(_warn(f"Der Rückwärtstest hat nur {m['n_origins']} Startpunkte: Die Gütezahlen sind unsicher.", "warn"))
        kp = [
            dbc.Col(_kpi("fa-chart-line", f"Projektion {fc['years'][-1]}", _num(fc["mean"][-1]), FL_RED, f"{p['unit']} · Methode {m['name']}"), md=3, sm=6, className="mb-3"),
            dbc.Col(_kpi("fa-arrows-up-down", "80-%-Band", f"{_num(fc['lo80'][-1])} … {_num(fc['hi80'][-1])}", ACCENT, f"für {fc['years'][-1]}"), md=3, sm=6, className="mb-3"),
            dbc.Col(_kpi("fa-ranking-star", "MASE (Rückwärtstest)", f"{m['mase']:.2f}".replace(".", ","), GREEN,
                         f"naive Basis {p['methods']['naive']['mase']:.2f}".replace(".", ",")), md=3, sm=6, className="mb-3"),
            dbc.Col(_kpi("fa-hashtag", "Beobachtete Jahre", str(p["n"]), FL_GOLD, f"{hist['years'][0]}–{last_year}"), md=3, sm=6, className="mb-3"),
        ]
        out.append(dbc.Row(kp, className="g-3"))
    else:
        out.append(_warn("Keine Projektion: " + p.get("reason", ""), "danger"))
        out.append(html.P("Ohne belastbare Methode wird bewusst keine Linie in die Zukunft gezogen. Die Reihe der bisherigen Werte ist unten dargestellt.",
                          style={"color": MUTED, "fontSize": "0.82rem"}))

    out.append(_card(_graph(chart(p, show_all), 420)))
    if ok:
        out.append(_card([html.H6("Annahmen der angezeigten Projektion", style={"color": TEXT}),
                          html.P(p["forecasts"][p["best"]]["assumptions"], style={"color": MUTED, "fontSize": "0.82rem", "marginBottom": "2px"}),
                          html.P(f"Angepasst an {p['n']} aufeinanderfolgende Jahreswerte ({hist['years'][0]}–{last_year}); Horizont {p['horizon']} Jahre; "
                                 f"Intervalle aus dem Modell (Normalverteilung der Fehler). Berechnet am {p['computed_at']}.", style={"color": MUTED, "fontSize": "0.8rem", "marginBottom": "0"})]))
        calc = calculator(p, thr, last_val, last_year, p["unit"])
        if calc is not None:
            out.append(html.Div(style={"height": "12px"}))
            out.append(calc)
    out.append(html.Div(style={"height": "12px"}))
    out.append(quality_table(p))
    if sid == SCEN_SERIES:
        sc = scenarios_block(hist, thr)
        if sc is not None:
            out.append(sc)
    im = imf_block(sid, hist)
    if im is not None:
        out.append(im)
    out.append(html.Div(style={"height": "12px"}))
    out.append(overview_table(all_fc))
    out.append(html.Div([html.I(className="fas fa-database", style={"marginRight": "6px", "color": MUTED}), html.Span("Quellen: ", style={"color": MUTED}),
                         html.Span("Datenreihen aus den übrigen Tabs (Amt für Statistik, Weltbank, Landestourismus-Statistik, ERA5/Open-Meteo); Methoden: statsmodels (BSD-3), "
                                   "Berechnung vorab im Worker, wöchentlich aktualisiert.", style={"color": MUTED})], className="source-bar"))
    return html.Div(out)
