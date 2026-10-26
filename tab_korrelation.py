"""
tab_korrelation.py — Tab «Korrelations-Labor»
=============================================
Zwei beliebige Jahresreihen aus den vorhandenen Daten vergleichen (Amt für Statistik, Eurostat, Weltbank, IWF, Factbook, Klima, Polizei …):
Pearson/Spearman mit p-Wert und 95-%-Konfidenzintervall, Differenzen/Prozent/Trendbereinigung, Zeitverschiebung ±N Jahre,
Streudiagramm und Zeitreihe mit zwei Achsen. Pflicht-Warnhinweise sind Teil der Auswertung (kleine Stichprobe, gemeinsamer Trend,
viele Tests, keine Kausalität). Die Hypothesen-Galerie ist ausdrücklich keine Beweissammlung.
"""

import dash_bootstrap_components as dbc
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import ALL, Input, Output, callback, clientside_callback, ctx, dcc, html, no_update

import correlate as C
from ui import FL_BLUE, FL_RED, FL_GOLD, ACCENT, GREEN, MUTED, TEXT, BORDER, _card, _kpi, _styled, _empty

HOW = [
    {"label": "Niveau (Rohwerte)", "value": "level"},
    {"label": "Veränderung zum Vorjahr (Δ)", "value": "diff"},
    {"label": "Veränderung in % (Wachstum)", "value": "pct"},
    {"label": "Linearer Trend entfernt", "value": "detrend"},
]
HOW_LABEL = {h["value"]: h["label"] for h in HOW}
MAX_LAG = 8
DEFAULTS = {"a": "li|pop", "b": "li|wohnungen", "how": "level", "lag": 0}

# Kuratierte Hypothesen: ausdrücklich Fragestellungen, keine Belege. (a, b, how, lag, Titel, plausibel, Gegenargument)
HYPOTHESES = [
    ("tour|nights", "clim|vaduz|summer_days", "level", 0, "Tourismusnächte und Sommertage",
     "Warme Sommer könnten mehr Gäste anziehen.", "Beide Reihen haben Trends (Tourismus-Strukturwandel, Klimaerwärmung); Reihenbruch durch Statistikumstellungen."),
    ("tour|nights", "clim|vaduz|prec", "diff", 0, "Tourismusnächte und Jahresniederschlag",
     "Nasse Jahre könnten Übernachtungen dämpfen.", "Niederschlag ist ein Rasterwert für das ganze Jahr; Gäste reagieren auf Saison- und Wochenendwetter."),
    ("li|einwanderung", "li|neuwohn", "level", 1, "Wohnungsbau und Zuzug (Bau läuft voraus)",
     "Bewilligte Wohnungen könnten ein Jahr später mehr Zuzug ermöglichen.", "Nur ~14 Jahre; umgekehrte Richtung (Zuzug → Bau) ebenso plausibel; Wohnungsnachfrage ist ein Dritt-Faktor."),
    ("li|saldo", "li|alq_gesamt", "level", 0, "Wanderungssaldo und Arbeitslosenquote",
     "Konjunktur beeinflusst beides.", "Konjunktur wirkt auf beides gleichzeitig (gemeinsame Ursache); nur ~14 Jahre."),
    ("li|neuwohn", "fb|birth_rate", "level", 0, "Wohnungsbau und Geburtenrate (Factbook)",
     "Mehr Wohnraum könnte Familiengründung erleichtern.", "Geburtenrate sinkt langfristig in ganz Europa; Bewilligungen schwanken konjunkturell."),
    ("pol|straftaten_stgb", "clim|vaduz|hot_days", "level", 0, "Straftaten und Hitzetage",
     "In der Literatur wird ein Zusammenhang von Hitze und bestimmten Delikten diskutiert.", "Anzeigenstatistik, kleine Zahlen, Anzeigeverhalten; Hitzetage in Vaduz sind ein ERA5-Modellwert."),
    ("pol|unfaelle_total", "clim|vaduz|frost_days", "level", 0, "Verkehrsunfälle und Frosttage",
     "Winterliche Strassenverhältnisse könnten Unfälle erhöhen.", "Verkehrsaufkommen und Berichtswesen ändern sich; Frosttage sinken im Trend."),
    ("li|pop", "li|wohnungen", "level", 0, "Warnbeispiel: Bevölkerung und Wohnungsbestand (gemeinsamer Trend)",
     "Beide wachsen seit Jahren.", "Genau das: Niveaus korrelieren fast perfekt, die Veränderungen aber kaum — Scheinkorrelation durch gemeinsamen Trend. Vergleichen Sie die Tabelle der Transformationen."),
    ("wb|NY.GDP.PCAP.CD", "li|auslaender_pct", "level", 0, "BIP pro Kopf und Ausländeranteil",
     "Wirtschaftsstarke Phasen ziehen Arbeitskräfte an.", "Beide steigen langfristig; Wechselkurs (USD) und Definition des Ausländeranteils beeinflussen die Reihen."),
    ("li|asyl", "li|alq_Ausländer", "diff", 0, "Asylgesuche und Arbeitslosenquote der Ausländer",
     "Mehr Schutzsuchende könnten die Arbeitslosenquote der Ausländer erhöhen.", "Nur wenige Jahre, Asylzahlen springen (2015/2022); Arbeitslosenquote folgt der Konjunktur."),
]


# ── Sidebar ───────────────────────────────────────────────────────────────────

def sidebar_section() -> html.Div:
    return html.Div(id="filter-kor", children=[
        html.Div([html.Label("Reihe A", className="filter-label"),
                  dcc.Dropdown(id="kor-a", options=C.label_options(), value=DEFAULTS["a"], clearable=False, searchable=True,
                               className="fl-dropdown", optionHeight=44)], className="filter-section"),
        html.Div([html.Label("Reihe B", className="filter-label"),
                  dcc.Dropdown(id="kor-b", options=C.label_options(), value=DEFAULTS["b"], clearable=False, searchable=True,
                               className="fl-dropdown", optionHeight=44)], className="filter-section"),
        html.Div([html.Label("Transformation", className="filter-label"),
                  dcc.RadioItems(id="kor-how", options=HOW, value=DEFAULTS["how"], className="fl-checklist", labelClassName="checklist-label")],
                 className="filter-section"),
        html.Div([html.Label(f"Zeitverschiebung (Jahre, ±{MAX_LAG})", className="filter-label"),
                  dcc.Slider(id="kor-lag", min=-MAX_LAG, max=MAX_LAG, step=1, value=DEFAULTS["lag"],
                             marks={i: {"label": str(i), "style": {"color": MUTED, "fontSize": "10px"}} for i in range(-MAX_LAG, MAX_LAG + 1, 4)},
                             tooltip={"placement": "bottom", "always_visible": True}, className="fl-slider"),
                  html.Small("> 0: Reihe B läuft voraus (B im Jahr t−Verschiebung vs. A im Jahr t).", style={"color": MUTED, "fontSize": "0.7rem"})],
                 className="filter-section"),
    ])


# ── Hilfen ────────────────────────────────────────────────────────────────────

def _fmt(x, d=2):
    return "–" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:.{d}f}".replace(".", ",")


def _fp(p):
    if p is None or (isinstance(p, float) and np.isnan(p)):
        return "–"
    return "< 0,001" if p < 0.001 else f"{p:.3f}".replace(".", ",")


def _strength(r):
    a = abs(r)
    return "sehr schwach" if a < 0.2 else "schwach" if a < 0.4 else "mässig" if a < 0.6 else "stark" if a < 0.8 else "sehr stark"


def _warn(text, level="warn"):
    color = FL_RED if level == "danger" else FL_GOLD if level == "warn" else ACCENT
    icon = "fa-circle-exclamation" if level == "danger" else "fa-triangle-exclamation" if level == "warn" else "fa-circle-info"
    return html.Div([html.I(className=f"fas {icon}", style={"marginRight": "8px", "color": color}), text],
                    style={"color": TEXT, "fontSize": "0.82rem", "padding": "8px 12px", "marginBottom": "8px", "background": "#161B22",
                           "border": f"1px solid {color}", "borderRadius": "6px"})


def _graph(fig, h=360):
    fig.update_layout(height=h)
    return dcc.Graph(figure=fig, config={"displayModeBar": False})


def how_to_read() -> html.Div:
    def item(t, x):
        return html.Li([html.B(t + ": ", style={"color": TEXT}), x], style={"marginBottom": "4px"})
    return _card([
        html.H6([html.I(className="fas fa-book-open", style={"marginRight": "8px", "color": ACCENT}), "Wie lesen? Grundlagen und Grenzen"], style={"color": TEXT}),
        html.Ul([
            item("Reihen", "Jahreswerte aus den bereits geladenen Daten (Amt für Statistik, Eurostat, Weltbank, IWF-Ist-Werte, CIA Factbook-Archiv, Landespolizei, "
                 "ERA5-Klima). Projektionen werden nie korreliert. Jede Reihe nennt ihre Quelle in der Auswahlliste."),
            item("Pearson / Spearman", "Pearson misst den linearen Zusammenhang der Werte, Spearman den Gleichlauf der Ränge (robuster gegen Ausreisser). "
                 "r liegt zwischen −1 und +1; p ist die Wahrscheinlichkeit, bei fehlendem Zusammenhang und unabhängigen Beobachtungen ein so grosses |r| zu sehen."),
            item("Konfidenzintervall", "95-%-Intervall für r (Fisher-z). Ein breites Intervall heisst: der wahre Zusammenhang ist kaum eingegrenzt."),
            item("Unabhängigkeit", "Jahreswerte benachbarter Jahre sind meist ähnlich (Autokorrelation); die p-Werte sind deshalb zu optimistisch, vor allem bei Trendreihen."),
            item("Transformationen", "Niveau = Rohwerte; Δ und % = Veränderung zum Vorjahr; «Trend entfernt» = Abweichung von der linearen Trendgeraden. "
                 "Wenn die Korrelation der Niveaus verschwindet, sobald der Trend entfernt wird, war sie Scheinkorrelation."),
            item("Zeitverschiebung", "Prüft, ob eine Reihe der anderen um N Jahre vorausläuft. Je mehr Verschiebungen man testet, desto eher findet man zufällig eine «passende»."),
            item("Keine Kausalität", "Korrelation ist keine Kausalität. Ein Zusammenhang kann Zufall, gemeinsamer Trend, gemeinsame Ursache (z. B. Konjunktur) oder "
                 "umgekehrte Richtung sein. Die Hypothesen-Galerie sind Fragen, keine Belege."),
        ], style={"color": MUTED, "fontSize": "0.8rem", "paddingLeft": "18px", "marginBottom": "0"}),
    ])


# ── Auswertung ────────────────────────────────────────────────────────────────

def render_korrelation(data: dict) -> html.Div:
    a_id = data.get("kor_a") or DEFAULTS["a"]
    b_id = data.get("kor_b") or DEFAULTS["b"]
    how = data.get("kor_how") or DEFAULTS["how"]
    lag = int(data.get("kor_lag") or 0)
    cat = C.catalog()
    out = [html.H4("Korrelations-Labor", className="section-title"), how_to_read(), html.Div(style={"height": "12px"})]
    if a_id not in cat or b_id not in cat:
        out += [_empty("Reihe A und B wählen (Seitenleiste)."), _gallery()]
        return html.Div(out)
    la, lb = cat[a_id], cat[b_id]
    sa, sb = C.load_series(a_id), C.load_series(b_id)
    out.append(html.H5(f"{la['label']}  ↔  {lb['label']}", style={"color": TEXT, "fontSize": "1rem"}))
    if len(sa) < 5 or len(sb) < 5:
        out += [_empty("Mindestens eine Reihe hat zu wenige Jahreswerte (< 5)."), _gallery()]
        return html.Div(out)
    if a_id == b_id:
        out.append(_warn("Reihe A und B sind identisch (Korrelation trivial).", "danger"))

    res = C.correlate(sa, sb, how, lag)
    df, pe, sp = res["df"], res["pearson"], res["spearman"]
    n = pe["n"]

    # Warnschilder
    warns = []
    if n < 15:
        warns.append(_warn(f"Kleine Stichprobe: nur n = {n} gemeinsame Jahre (< 15). Korrelationen sind dann sehr unsicher; das Konfidenzintervall ist breit, einzelne Jahre "
                           "bestimmen das Ergebnis.", "danger" if n < 8 else "warn"))
    ta, tb = C.trend_p(sa), C.trend_p(sb)
    both_trend = (not np.isnan(ta)) and (not np.isnan(tb)) and ta < 0.05 and tb < 0.05
    if both_trend:
        warns.append(_warn("Gemeinsamer Trend: Beide Reihen haben einen signifikanten Trend (Mann-Kendall p < 0,05). Die Korrelation der Niveaus kann allein vom gemeinsamen "
                           "Trend stammen (Scheinkorrelation). Prüfen Sie die Zeilen «Veränderung» und «Trend entfernt» in der Tabelle unten.", "danger" if how == "level" else "warn"))
    if how == "level" and (np.isnan(ta) or ta < 0.05 or np.isnan(tb) or tb < 0.05):
        warns.append(_warn("Niveau-Korrelationen von Reihen mit Trend sind besonders anfällig für Scheinzusammenhänge.", "info"))
    warns.append(_warn("Viele getestete Paare: Dieses Labor erlaubt Tausende Kombinationen. Wer viele Paare (und Verschiebungen) ansieht, findet zufällig starke "
                       "Korrelationen — bei 100 Tests ist mit ~5 «signifikanten» Zufallstreffern (p < 0,05) zu rechnen. Ein einzelner Treffer ist keine Entdeckung.", "info"))
    warns.append(_warn("Korrelation ist keine Kausalität.", "info"))
    out += warns

    # Kennzahlen
    kp = [
        dbc.Col(_kpi("fa-chart-line", f"Pearson r ({HOW_LABEL[how]})", _fmt(pe["r"]), FL_BLUE,
                     f"{_strength(pe['r']) if not np.isnan(pe['r']) else '–'} · p {_fp(pe['p'])}"), md=3, sm=6, className="mb-3"),
        dbc.Col(_kpi("fa-arrows-left-right", "95-%-Konfidenzintervall", f"{_fmt(pe['lo'])} … {_fmt(pe['hi'])}", ACCENT, "für Pearson r (Fisher-z)"), md=3, sm=6, className="mb-3"),
        dbc.Col(_kpi("fa-ranking-star", "Spearman ρ", _fmt(sp["r"]), GREEN, f"p {_fp(sp['p'])}"), md=3, sm=6, className="mb-3"),
        dbc.Col(_kpi("fa-hashtag", "Gemeinsame Jahre n", f"{n}", FL_GOLD,
                     f"{int(df.index.min())}–{int(df.index.max())}" if n else "–"), md=3, sm=6, className="mb-3"),
    ]
    out.append(dbc.Row(kp, className="g-3"))
    if n < 3:
        out.append(_empty("Zu wenige gemeinsame Jahre nach Transformation/Verschiebung."))
        out.append(_gallery())
        return html.Div(out)

    # Zeitreihe zwei Achsen (Niveaus, mit Verschiebung)
    lv = C.align(sa, sb, lag)
    f1 = go.Figure()
    f1.add_trace(go.Scatter(x=lv.index, y=lv["a"], name=la["label"][:50], mode="lines+markers", line=dict(color=FL_RED, width=2.4), yaxis="y"))
    f1.add_trace(go.Scatter(x=lv.index, y=lv["b"], name=lb["label"][:50] + (f" (um {lag} J. verschoben)" if lag else ""), mode="lines+markers",
                            line=dict(color=ACCENT, width=2.4, dash="dot"), yaxis="y2"))
    _styled(f1, "Zeitreihen (Niveaus) mit zwei Achsen")
    f1.update_layout(yaxis=dict(title=dict(text=la["unit"] or "A", font=dict(color=FL_RED))), legend=dict(orientation="h", y=-0.25, bgcolor="rgba(0,0,0,0)"),
                     yaxis2=dict(title=dict(text=lb["unit"] or "B", font=dict(color=ACCENT)), overlaying="y", side="right", showgrid=False))
    f1.update_xaxes(tickformat="d")

    # Streudiagramm der gewählten Transformation
    f2 = go.Figure()
    f2.add_trace(go.Scatter(x=df["b"], y=df["a"], mode="markers+text", text=[str(int(i)) for i in df.index], textposition="top center",
                            textfont=dict(size=9, color=MUTED), marker=dict(color=FL_BLUE, size=8), name="Jahre",
                            hovertemplate="%{text}: B %{x:,.2f}, A %{y:,.2f}<extra></extra>"))
    if n >= 3 and np.std(df["b"]) > 0:
        bb, aa = np.polyfit(df["b"].values, df["a"].values, 1)
        xs = np.array([df["b"].min(), df["b"].max()])
        f2.add_trace(go.Scatter(x=xs, y=aa + bb * xs, mode="lines", line=dict(color=FL_GOLD, dash="dash"), name=f"Regressionsgerade (r = {_fmt(pe['r'])})"))
    _styled(f2, f"Streudiagramm ({HOW_LABEL[how]})", legend=False)
    f2.update_layout(hovermode="closest")
    f2.update_xaxes(title=lb["label"][:45])
    f2.update_yaxes(title=la["label"][:45])
    out.append(dbc.Row([dbc.Col(_card(_graph(f1, 380)), md=7, className="mb-3"), dbc.Col(_card(_graph(f2, 380)), md=5, className="mb-3")], className="g-3"))

    # Tabelle aller Transformationen (Scheinkorrelations-Check)
    rows = []
    for h in HOW:
        r = C.correlate(sa, sb, h["value"], lag)
        p_, s_ = r["pearson"], r["spearman"]
        rows.append(html.Tr([html.Td(h["label"], style={"fontWeight": "600" if h["value"] == how else "400"}), html.Td(_fmt(p_["r"])), html.Td(f"{_fmt(p_['lo'])} … {_fmt(p_['hi'])}"),
                             html.Td(_fp(p_["p"])), html.Td(_fmt(s_["r"])), html.Td(_fp(s_["p"])), html.Td(str(p_["n"]))]))
    out.append(_card([
        html.H6("Dieselbe Verschiebung, vier Transformationen — Scheinkorrelations-Check", style={"color": TEXT}),
        html.Div(html.Table([html.Thead(html.Tr([html.Th(h) for h in ("Transformation", "Pearson r", "95-%-KI", "p", "Spearman ρ", "p", "n")])), html.Tbody(rows)], className="od-table"),
                 style={"overflowX": "auto"}),
        html.P("Bleibt die Korrelation nur bei «Niveau» hoch und verschwindet bei Δ/%/Trend entfernt, ist sie sehr wahrscheinlich ein gemeinsamer Trend, kein Zusammenhang "
               "der Schwankungen.", style={"color": MUTED, "fontSize": "0.8rem", "marginBottom": "0", "marginTop": "8px"})]))

    # Lag-Scan
    lags = list(range(-MAX_LAG, MAX_LAG + 1))
    rs, ns = [], []
    for k in lags:
        r = C.correlate(sa, sb, how, k)["pearson"]
        rs.append(r["r"])
        ns.append(r["n"])
    f3 = go.Figure(go.Bar(x=lags, y=rs, marker_color=[FL_RED if k == lag else ACCENT for k in lags],
                          customdata=ns, hovertemplate="Verschiebung %{x}: r = %{y:.2f} (n = %{customdata})<extra></extra>"))
    _styled(f3, f"Pearson r je Zeitverschiebung ({HOW_LABEL[how]}) — {len(lags)} Tests", legend=False)
    f3.update_layout(hovermode="closest")
    f3.update_xaxes(title="Verschiebung in Jahren (> 0: B läuft voraus)", dtick=1)
    f3.update_yaxes(range=[-1, 1])
    out.append(_card(_graph(f3, 300)))
    out.append(html.Div([html.I(className="fas fa-triangle-exclamation", style={"marginRight": "8px", "color": FL_GOLD}),
                         f"Hier wurden {len(lags)} Verschiebungen verglichen. Das Maximum dieser Balken ist wegen der vielen Tests ein optimistisches Ergebnis; "
                         "bei der Wahl der «besten» Verschiebung steigt die Wahrscheinlichkeit eines Zufallstreffers deutlich."],
                        style={"color": MUTED, "fontSize": "0.78rem", "padding": "2px 2px 8px"}))

    out.append(dbc.Row([dbc.Col([
        html.Label("Link zu dieser Auswertung", className="filter-label"),
        dcc.Input(id="kor-share", type="text", readOnly=True, className="share-input", style={"width": "100%"}),
    ], md=8)], className="g-3 mb-3"))
    out.append(html.Div([html.I(className="fas fa-database", style={"marginRight": "6px", "color": MUTED}), html.Span("Quellen: ", style={"color": MUTED}),
                         html.Span(f"A: {la['group']} · B: {lb['group']} — Details und Lizenzen in den jeweiligen Tabs; Jahreswerte, keine Projektionen. "
                                   "Berechnung im Browser-Request aus lokalen Daten (n ≤ ~80), eigene Implementierung (numpy/pandas).", style={"color": MUTED})],
                        className="source-bar"))
    out.append(html.Div(style={"height": "12px"}))
    out.append(_gallery())
    return html.Div(out)


def _gallery() -> html.Div:
    cat = C.catalog()
    cards = []
    for i, (a, b, how, lag, title, why, against) in enumerate(HYPOTHESES):
        if a not in cat or b not in cat:
            continue
        cards.append(dbc.Col(_card([
            html.Div("HYPOTHESE — kein Beleg", style={"fontSize": "0.65rem", "color": FL_GOLD, "letterSpacing": "0.05em", "fontWeight": "700"}),
            html.H6(title, style={"color": TEXT, "fontSize": "0.92rem", "marginTop": "2px"}),
            html.P([html.B("Warum plausibel: ", style={"color": TEXT}), why], style={"color": MUTED, "fontSize": "0.78rem", "marginBottom": "4px"}),
            html.P([html.B("Dagegen spricht: ", style={"color": TEXT}), against], style={"color": MUTED, "fontSize": "0.78rem"}),
            html.Button("im Labor öffnen", id={"type": "kor-hyp", "idx": i}, className="copy-btn", style={"width": "auto", "padding": "3px 12px", "fontSize": "0.75rem"}),
        ]), md=6, className="mb-3"))
    return html.Div([html.H5("Hypothesen-Galerie", className="section-title", style={"marginTop": "10px"}),
                     html.P("Kuratierte Fragestellungen zum Ausprobieren. Sie sind Hypothesen, keine Ergebnisse: Ob eine Korrelation zu sehen ist, sagt nichts über Ursache und Wirkung.",
                            style={"color": MUTED, "fontSize": "0.82rem"}),
                     dbc.Row(cards, className="g-3")])


# ── Callbacks ─────────────────────────────────────────────────────────────────

@callback(Output("kor-a", "value", allow_duplicate=True), Output("kor-b", "value", allow_duplicate=True),
          Output("kor-how", "value", allow_duplicate=True), Output("kor-lag", "value", allow_duplicate=True),
          Input({"type": "kor-hyp", "idx": ALL}, "n_clicks"), prevent_initial_call=True)
def _pick_hypothesis(clicks):
    if not any(c for c in clicks if c) or not isinstance(ctx.triggered_id, dict):
        return no_update, no_update, no_update, no_update
    a, b, how, lag, *_ = HYPOTHESES[ctx.triggered_id["idx"]]
    return a, b, how, lag


clientside_callback(
    """
    function(a, b, how, lag) {
        var q = '?tab=korrelation&ka=' + encodeURIComponent(a || '') + '&kb=' + encodeURIComponent(b || '') +
                '&kh=' + encodeURIComponent(how || 'level') + '&kl=' + encodeURIComponent(lag || 0);
        return window.location.origin + window.location.pathname + q;
    }
    """,
    Output("kor-share", "value"),
    Input("kor-a", "value"), Input("kor-b", "value"), Input("kor-how", "value"), Input("kor-lag", "value"),
)
