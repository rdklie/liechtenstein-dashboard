/**
 * «Frage zu den Daten»: schickt die Frage per POST an /_chat/ask (gleiche Domain, CSP: connect-src 'self') und zeigt Antwort, Tabelle, Diagramm
 * und Quellen an. Alles wird über textContent/DOM-Knoten gebaut (kein innerHTML mit Serverdaten).
 */
(function () {
    var busy = false;
    var kkState = "";          // "" = bereit, "thinking", "sleeping"; bleibt erhalten, wenn Dash den Tab neu aufbaut
    var kkSvg = null;          // geparstes kraki.svg (einmal geladen)
    var kkLoading = false;

    // Kraki: Zustand als Klasse am <svg class="kk">; Grafik rein dekorativ (der Titel daneben ist der zugängliche Text)
    function setKraki(state) {
        kkState = state || "";
        var svg = document.querySelector("#kk-slot svg.kk");
        if (!svg) return;
        svg.classList.remove("kk-thinking", "kk-sleeping");
        if (kkState) svg.classList.add("kk-" + kkState);
    }

    function fillKraki() {
        var slot = document.getElementById("kk-slot");
        if (!slot || slot.querySelector("svg")) return;
        if (!kkSvg) {
            if (kkLoading) return;
            kkLoading = true;
            fetch("/assets/kraki.svg", { credentials: "same-origin" }).then(function (r) { return r.ok ? r.text() : ""; }).then(function (t) {
                var doc = t ? new DOMParser().parseFromString(t, "image/svg+xml") : null;
                var el = doc && doc.documentElement && doc.documentElement.nodeName.toLowerCase() === "svg" ? doc.documentElement : null;
                if (el) {
                    el.removeAttribute("role"); el.removeAttribute("aria-label"); el.removeAttribute("width"); el.removeAttribute("height");
                    el.setAttribute("aria-hidden", "true"); el.setAttribute("focusable", "false");
                    kkSvg = el;
                }
            }).catch(function () {}).then(function () { kkLoading = false; fillKraki(); });
            return;
        }
        slot.appendChild(document.importNode(kkSvg, true));
        if (kkState === "" ) {                                  // beim ersten Zeigen: ist die Funktion gerade abgeschaltet (Kill-Switch/Kontingent)?
            fetch("/_chat/status", { credentials: "same-origin" }).then(function (r) { return r.json(); })
                .then(function (j) { if (j && j.enabled === false && !busy) setKraki("sleeping"); }).catch(function () {});
        }
        setKraki(kkState);
    }
    new MutationObserver(function () { if (document.getElementById("kk-slot") && !document.querySelector("#kk-slot svg")) fillKraki(); })
        .observe(document.documentElement, { childList: true, subtree: true });
    fillKraki();

    var COLORS = ["#58A6FF", "#F0883E", "#3FB950", "#BC8CFF", "#D4A017", "#CE1126", "#39C5CF", "#FF7B72"];

    function mk(tag, cls, text) {
        var e = document.createElement(tag);
        if (cls) e.className = cls;
        if (text !== undefined && text !== null) e.textContent = text;
        return e;
    }

    function log() { return document.getElementById("chat-log"); }

    function addMsg(cls) {
        var box = mk("div", "chat-msg " + cls);
        var l = log();
        if (l) l.insertBefore(box, l.firstChild);
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

    function chart(c) {
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
                    paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)", font: { color: "#C9D1D9", size: 12 },
                    margin: { l: 60, r: 10, t: 10, b: 60 }, height: 320, barmode: "group", showlegend: c.series.length > 1,
                    legend: { orientation: "h", y: -0.25 }, xaxis: { type: "category", gridcolor: "#21262D" },
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

    function render(box, body) {
        if (body.answer) box.appendChild(mk("p", "chat-answer", body.answer));
        if (body.title) box.appendChild(mk("div", "chat-title", body.title));
        if (body.table && body.table.rows && body.table.rows.length) box.appendChild(table(body.table));
        if (body.chart) box.appendChild(chart(body.chart));
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

    function ask(q) {
        if (busy) return;
        q = (q || "").trim();
        if (!q) return;
        busy = true;
        var send = document.getElementById("chat-send");
        if (send) send.disabled = true;
        setKraki("thinking");
        var qb = addMsg("chat-q"); qb.textContent = q;
        var status = 0;
        var box = addMsg("chat-a"); box.appendChild(mk("p", "chat-wait", "Einen Moment …"));
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
              if (body && body.ok) render(box, body);
              else box.appendChild(mk("p", "chat-error", (body && body.message) || "Die Frage konnte nicht beantwortet werden."));
          })
          .catch(function () { box.textContent = ""; box.appendChild(mk("p", "chat-error", "Keine Verbindung zum Server.")); })
          .then(function () {
              busy = false; if (send) send.disabled = false;
              setKraki(status === 503 || status === 429 ? "sleeping" : "");      // nicht verfügbar / Kontingent oder Limit erreicht → Kraki schläft
          });
    }

    document.addEventListener("click", function (e) {
        var t = e.target;
        if (!t || !t.closest) return;
        var chip = t.closest(".chat-chip");
        if (chip) { var inp = document.getElementById("chat-input"); if (inp) { inp.value = chip.getAttribute("data-q") || ""; inp.dispatchEvent(new Event("input", { bubbles: true })); inp.focus(); } return; }
        if (t.closest("#chat-send")) { var i2 = document.getElementById("chat-input"); if (i2) { ask(i2.value); i2.value = ""; i2.dispatchEvent(new Event("input", { bubbles: true })); } }
    });
    document.addEventListener("keydown", function (e) {
        if (e.target && e.target.id === "chat-input" && e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
            e.preventDefault(); ask(e.target.value); e.target.value = ""; e.target.dispatchEvent(new Event("input", { bubbles: true }));
        }
    });
    document.addEventListener("input", function (e) {
        if (e.target && e.target.id === "chat-input") {
            var c = document.getElementById("chat-counter");
            if (c) c.textContent = e.target.value.length + " / " + (c.getAttribute("data-max") || "500");
        }
    });
})();
