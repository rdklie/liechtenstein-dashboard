/**
 * «Frage zu den Daten»: gemeinsames Modul für den Chat-Tab und das Chat-Fenster am Kraki-Overlay (assets/kraki_overlay.js).
 * Ein «Chat-Bereich» ist ein Element mit data-chat-root="tab"|"panel" und den Kindern .chat-log, .chat-input, .chat-send, .chat-counter, .chat-chip, .kk-slot.
 * Alle Bereiche sprechen dieselbe API: POST /_chat/ask (gleiche Domain, CSP: connect-src 'self'). Antwort, Tabelle, Diagramm und Quellen werden ausschliesslich
 * über textContent/DOM-Knoten gebaut (kein innerHTML mit Serverdaten). Kraki (assets/kraki.svg) wird per DOMParser eingesetzt.
 */
(function () {
    var COLORS = ["#58A6FF", "#F0883E", "#3FB950", "#BC8CFF", "#D4A017", "#CE1126", "#39C5CF", "#FF7B72"];
    var states = {};            // data-chat-root → "", "thinking", "sleeping" (bleibt erhalten, wenn Dash den Tab neu aufbaut)
    var busy = {};              // data-chat-root → Frage läuft
    var kkSvg = null;           // geparstes kraki.svg (einmal geladen)
    var kkWaiters = null;

    function mk(tag, cls, text) {
        var e = document.createElement(tag);
        if (cls) e.className = cls;
        if (text !== undefined && text !== null) e.textContent = text;
        return e;
    }

    function rootOf(el) { return el && el.closest ? el.closest("[data-chat-root]") : null; }
    function kind(root) { return root.getAttribute("data-chat-root") || "tab"; }
    function q1(root, sel) { return root.querySelector(sel); }

    // ── Kraki ────────────────────────────────────────────────────────────────
    function krakiSvg(cb) {
        if (kkSvg) { cb(kkSvg); return; }
        if (kkWaiters) { kkWaiters.push(cb); return; }
        kkWaiters = [cb];
        fetch("/assets/kraki.svg", { credentials: "same-origin" }).then(function (r) { return r.ok ? r.text() : ""; }).then(function (t) {
            var doc = t ? new DOMParser().parseFromString(t, "image/svg+xml") : null;
            var el = doc && doc.documentElement && doc.documentElement.nodeName.toLowerCase() === "svg" ? doc.documentElement : null;
            if (el) {
                ["role", "aria-label", "width", "height"].forEach(function (a) { el.removeAttribute(a); });
                el.setAttribute("aria-hidden", "true");           // rein dekorativ: der Titel daneben ist der zugängliche Text
                el.setAttribute("focusable", "false");
                kkSvg = el;
            }
        }).catch(function () {}).then(function () {
            var w = kkWaiters || [];
            kkWaiters = null;
            if (kkSvg) w.forEach(function (f) { f(kkSvg); });
        });
    }

    function setKraki(root, state) {
        states[kind(root)] = state || "";
        var svg = q1(root, ".kk-slot svg.kk");
        if (!svg) return;
        svg.classList.remove("kk-thinking", "kk-sleeping");
        if (state) svg.classList.add("kk-" + state);
    }

    function fillSlots() {
        var slots = document.querySelectorAll(".kk-slot:empty");
        if (!slots.length) return;
        krakiSvg(function (svg) {
            document.querySelectorAll(".kk-slot:empty").forEach(function (slot) {
                var root = rootOf(slot);
                slot.appendChild(document.importNode(svg, true));
                if (!root) return;
                var st = states[kind(root)] || "";
                setKraki(root, st);
                if (st === "") {                                  // beim ersten Zeigen: ist die Funktion gerade abgeschaltet (Kill-Switch/Kontingent)?
                    fetch("/_chat/status", { credentials: "same-origin" }).then(function (r) { return r.json(); })
                        .then(function (j) { if (j && j.enabled === false && !busy[kind(root)]) setKraki(root, "sleeping"); }).catch(function () {});
                }
            });
        });
    }
    new MutationObserver(function () { if (document.querySelector(".kk-slot:empty")) fillSlots(); })
        .observe(document.documentElement, { childList: true, subtree: true });
    fillSlots();

    // ── Anzeige der Antwort ──────────────────────────────────────────────────
    function addMsg(root, cls) {
        var box = mk("div", "chat-msg " + cls);
        var l = q1(root, ".chat-log");
        if (l) l.appendChild(box);                                  // chronologisch: neueste Nachricht unten
        return box;
    }

    function table(t) {
        var wrap = mk("div", "chat-table-wrap");
        var tb = mk("table", "od-table chat-table");
        var head = mk("tr");
        t.columns.forEach(function (c) {
            var th = mk("th", c.numeric ? "num" : "", c.name + (c.unit ? " (" + c.unit + ")" : ""));
            head.appendChild(th);
        });
        var thead = mk("thead"); thead.appendChild(head); tb.appendChild(thead);
        var tbody = mk("tbody");
        t.rows.forEach(function (r) {
            var tr = mk("tr");
            r.forEach(function (v, i) { tr.appendChild(mk("td", t.columns[i].numeric ? "num" : "", v)); });
            tbody.appendChild(tr);
        });
        tb.appendChild(tbody); wrap.appendChild(tb);
        return wrap;
    }

    // Plotly rendert Pseudo-HTML (<a href=…>) in Beschriftungen: Zeichen maskieren, damit nichts als Tag ankommt
    function pt(s) { return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }

    function chart(c, narrow) {
        var div = mk("div", "chat-chart");
        var tries = 0;
        (function draw() {
            if (window.Plotly) {
                var traces = c.series.map(function (s, i) {
                    var t = { x: c.x.map(pt), y: s.y, name: pt(s.name), marker: { color: COLORS[i % COLORS.length] } };
                    if (c.type === "line") { t.type = "scatter"; t.mode = "lines+markers"; t.connectgaps = false; } else { t.type = "bar"; }
                    return t;
                });
                Plotly.newPlot(div, traces, {
                    paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)", font: { color: "#C9D1D9", size: narrow ? 11 : 12 },
                    margin: { l: narrow ? 48 : 60, r: 10, t: 10, b: narrow ? 70 : 60 }, height: narrow ? 260 : 320, barmode: "group", showlegend: c.series.length > 1,
                    legend: { orientation: "h", y: -0.3 }, xaxis: { type: "category", gridcolor: "#21262D" },
                    yaxis: { title: { text: pt(c.yTitle || "") }, gridcolor: "#21262D", tickformat: "," }
                }, { displayModeBar: false, responsive: true });
            } else if (tries++ < 40) {
                setTimeout(draw, 250);
            }
        })();
        return div;
    }

    function details(title, items) {
        if (!items || !items.length) return null;
        var d = mk("details", "chat-details");
        d.appendChild(mk("summary", "", title));
        items.forEach(function (x) { d.appendChild(mk("div", "chat-detail-line", x)); });
        return d;
    }

    function render(box, body, narrow) {
        if (body.answer) box.appendChild(mk("p", "chat-answer", body.answer));
        if (body.title) box.appendChild(mk("div", "chat-title", body.title));
        if (body.table && body.table.rows && body.table.rows.length) box.appendChild(table(body.table));
        if (body.chart) box.appendChild(chart(body.chart, narrow));
        if (body.notes && body.notes.length) {
            var n = mk("div", "chat-notes");
            body.notes.forEach(function (x) { n.appendChild(mk("div", "", "Hinweis: " + x)); });
            box.appendChild(n);
        }
        if (body.sources && body.sources.length) {
            var s = mk("div", "chat-sources", "Quelle: ");
            body.sources.forEach(function (x, i) {
                if (i) s.appendChild(document.createTextNode("; "));
                if (/^https:\/\//.test(x.url)) {
                    var a = mk("a", "source-link", x.title); a.href = x.url; a.target = "_blank"; a.rel = "noopener noreferrer"; s.appendChild(a);
                } else { s.appendChild(document.createTextNode(x.title)); }
            });
            box.appendChild(s);
        }
        var d = details("Wie wurde gerechnet?", body.formulas);
        if (d) box.appendChild(d);
        if (body.disclaimer) box.appendChild(mk("div", "chat-disclaimer", body.disclaimer + (body.session_left_pct !== undefined ? " · Rest-Kontingent dieser Sitzung: " + body.session_left_pct + " %" : "")));
    }

    // ── Frage senden ─────────────────────────────────────────────────────────
    function setCounter(root) {
        var inp = q1(root, ".chat-input"), c = q1(root, ".chat-counter");
        if (inp && c) c.textContent = inp.value.length + " / " + (c.getAttribute("data-max") || "500");
    }

    // Scrollen: beim Senden ans Ende (Frage und «Einen Moment …» sichtbar), bei der Antwort an ihren Anfang (nicht ans Ende einer langen Tabelle)
    function scrollTo(root, el, where) {
        var body = q1(root, ".kk-panel-body");
        if (body) {                                                  // Chat-Fenster: eigener Scrollbereich
            if (where === "end") body.scrollTop = body.scrollHeight;
            else body.scrollTop += el.getBoundingClientRect().top - body.getBoundingClientRect().top - 6;
        } else if (el.scrollIntoView) {                              // Chat-Tab: Seite
            el.scrollIntoView({ block: where === "end" ? "nearest" : "start" });
        }
    }

    // Kurze Ansage für Screenreader (statt den ganzen Verlauf samt Tabelle per aria-live vorlesen zu lassen)
    function announce(root, text) {
        var sr = q1(root, ".chat-sr");
        if (sr) sr.textContent = text || "";
    }

    function ask(root, q) {
        var k = kind(root);
        if (busy[k]) return;
        q = (q || "").trim();
        if (!q) return;
        busy[k] = true;
        var send = q1(root, ".chat-send");
        if (send) send.disabled = true;
        setKraki(root, "thinking");
        var narrow = k === "panel";
        var qb = addMsg(root, "chat-q"); qb.textContent = q;
        var status = 0;
        var box = addMsg(root, "chat-a"); box.appendChild(mk("p", "chat-wait", "Einen Moment …"));
        announce(root, "Einen Moment …");
        scrollTo(root, box, "end");
        fetch("/_chat/ask", {
            method: "POST", credentials: "same-origin",
            headers: { "Content-Type": "application/json", "X-Requested-With": "dli-chat" },
            body: JSON.stringify({ q: q })
        }).then(function (r) {
            status = r.status;
            return r.json().catch(function () { return { ok: false, message: "Unerwartete Antwort des Servers." }; });
        })
          .then(function (body) {
              box.textContent = "";
              if (body && body.ok) render(box, body, narrow);
              else box.appendChild(mk("p", "chat-error", (body && body.message) || "Die Frage konnte nicht beantwortet werden."));
              announce(root, "Antwort: " + ((body && (body.answer || body.message)) || "siehe Verlauf"));
              scrollTo(root, box, "start");
          })
          .catch(function () {
              box.textContent = ""; box.appendChild(mk("p", "chat-error", "Keine Verbindung zum Server."));
              announce(root, "Keine Verbindung zum Server.");
              scrollTo(root, box, "start");
          })
          .then(function () {
              busy[k] = false; if (send) send.disabled = false;
              setKraki(root, status === 503 || status === 429 ? "sleeping" : "");      // nicht verfügbar / Kontingent oder Limit erreicht → Kraki schläft
          });
    }

    function submit(root) {
        var inp = q1(root, ".chat-input");
        if (!inp) return;
        var q = inp.value;
        if (!q.trim() || busy[kind(root)]) return;
        ask(root, q);
        inp.value = "";
        setCounter(root);
    }

    document.addEventListener("click", function (e) {
        var t = e.target;
        if (!t || !t.closest) return;
        var chip = t.closest(".chat-chip");
        if (chip) {
            var root = rootOf(chip), inp = root && q1(root, ".chat-input");
            if (inp) { inp.value = chip.getAttribute("data-q") || ""; setCounter(root); inp.focus(); }
            return;
        }
        var snd = t.closest(".chat-send");
        if (snd) { var r2 = rootOf(snd); if (r2) submit(r2); }
    });
    document.addEventListener("keydown", function (e) {
        var t = e.target;
        if (!t || !t.classList || !t.classList.contains("chat-input") || e.key !== "Enter" || e.isComposing) return;
        if (e.shiftKey) return;                                      // Umschalt+Enter: Zeilenumbruch
        e.preventDefault();                                          // Enter, Strg+Enter, Cmd+Enter: senden
        var root = rootOf(t);
        if (root) submit(root);
    });
    document.addEventListener("input", function (e) {
        if (e.target && e.target.classList && e.target.classList.contains("chat-input")) {
            var root = rootOf(e.target);
            if (root) setCounter(root);
        }
    });

    // Schnittstelle für das Chat-Fenster am Overlay (assets/kraki_overlay.js)
    window.DliChat = {
        refreshCharts: function (root) {
            if (!window.Plotly) return;
            root.querySelectorAll(".chat-chart").forEach(function (c) { try { Plotly.Plots.resize(c); } catch (e) {} });
        },
        setCounter: setCounter,
        fillSlots: fillSlots,
        krakiSvg: krakiSvg
    };
})();
