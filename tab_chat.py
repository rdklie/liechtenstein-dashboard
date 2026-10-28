"""
tab_chat.py — Tab «Frage zu den Daten» (nur sichtbar, wenn AI_CHAT_ENABLED=1 beim Start der App gesetzt ist)
=========================================================================================================
Die Oberfläche ist reines HTML; Eingabe, Anzeige von Antwort/Tabelle/Diagramm erledigt assets/chat.js gegen /_chat/ask (gleiche Domain, CSP-konform).
Alle Zahlen, Tabellen, Diagramme und Quellen kommen vom Server (chat_data), nicht von der KI.
"""

from dash import dcc, html

import chat_budget as B
from ui import MUTED, TEXT, _card

EXAMPLES = [
    "Stelle die Sozialleistungskosten je Einwohner den Kosten der Asylbewerber pro Kopf gegenüber",
    "Warum ist der Median der Männer höher als bei den Frauen?",
    "Wie hat sich die Wohnbevölkerung von Vaduz seit 2010 entwickelt?",
    "Wie viele Straftaten wurden in den letzten Jahren registriert?",
]


def chat_notice_text() -> str:
    return ("Fragen werden gekürzt höchstens 30 Tage zur Missbrauchsabwehr gespeichert, ohne IP-Adresse. Die Frage und das Abfrageergebnis werden zur "
            "Beantwortung an Anthropic (USA) übermittelt; bitte keine persönlichen Angaben eingeben.")


def render_chat():
    cfg = B.load_config()
    small = {"color": MUTED, "fontSize": "0.82rem", "lineHeight": "1.55"}
    return html.Div([
        html.H4(["Frage zu den Daten ", html.Span("KI", className="exp-badge")], className="section-title"),
        _card([
            html.P(["Stelle eine Frage in einem Satz. Eine KI (Anthropic Claude Haiku) übersetzt sie in eine Abfrage der Datensätze auf daten.li. ",
                    html.B("Der Server führt Abfrage und Rechnung aus", style={"color": TEXT}),
                    " und zeigt Tabelle, Diagramm und Quelle. Die Zahlen stammen nie von der KI; der Text wird nur angezeigt, wenn jede darin genannte Zahl im Ergebnis steht."], style=small),
            html.Ul([
                html.Li("Möglich: Abfragen, Summen, pro Kopf, Verhältnisse, Vergleiche über die Datensätze der Tabs (Löhne, Bevölkerung, Asylwesen, Staatsausgaben, Polizei, Klima, …)."),
                html.Li("Nicht möglich: Ursachen erklären, Prognosen, Meinungen, allgemeine Fragen, Programmieren. «Warum»-Fragen werden nur als Zerlegung der vorhandenen Zahlen beantwortet."),
                html.Li(f"Grenzen: höchstens {cfg.max_input_chars} Zeichen je Frage, {cfg.questions_per_session} Fragen und {cfg.session_budget_urp / B.URP:g} Rappen Kosten je Sitzung; "
                        "ist das Monatskontingent erschöpft, pausiert die Funktion."),
                html.Li("Antworten sind KI-Antworten und ungeprüft. Massgebend sind Tabelle und Quelle."),
            ], style={**small, "paddingLeft": "1.2rem", "marginBottom": "6px"}),
            html.P(chat_notice_text(), style={**small, "marginBottom": "0"}),
        ]),
        html.Div(style={"height": "12px"}),
        _card([
            html.Div([html.Button(e, className="chat-chip", **{"data-q": e}) for e in EXAMPLES], className="chat-chips"),
            html.Textarea(id="chat-input", className="chat-input", rows=3, maxLength=cfg.max_input_chars, placeholder="Deine Frage zu den Daten …"),
            html.Div([
                html.Button("Frage stellen", id="chat-send", className="chat-send"),
                html.Span(f"0 / {cfg.max_input_chars}", id="chat-counter", className="chat-counter", **{"data-max": str(cfg.max_input_chars)}),
            ], className="chat-actions"),
        ]),
        html.Div(style={"height": "12px"}),
        html.Div(id="chat-log", className="chat-log", **{"aria-live": "polite"}),
        dcc.Graph(figure={}, style={"display": "none"}, config={"staticPlot": True}),         # lädt plotly.js für die Diagramme der Antworten
    ], id="chat-root")
