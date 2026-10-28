/**
 * Kraki als schwebendes Overlay unten rechts auf allen Seiten des Dashboards. Klick öffnet ein Chat-Fenster (nicht modal, die Seite dahinter bleibt bedienbar);
 * die Chat-Logik kommt aus assets/chat.js (window.DliChat), die Grafik aus assets/kraki.svg. Ein Link «In eigenem Tab öffnen» führt zur Vollansicht (/?tab=frage).
 * Nur sichtbar, wenn /_chat/status enabled:true meldet; auf dem Chat-Tab selbst ausgeblendet.
 * Gemerkt wird nur per sessionStorage (ob die Sprechblase schon gezeigt wurde, ob Kraki für die Sitzung ausgeblendet ist): keine Cookies, nichts an den Server.
 * Der Verlauf im Fenster liegt nur im Speicher der Seite und bleibt beim Schliessen/Öffnen erhalten.
 */
(function () {
    var KEY_HIDDEN = "dli_kraki_hidden";
    var KEY_BUBBLE = "dli_kraki_bubble";
    var CHAT_URL = "/?tab=frage";
    var FALLBACK_NOTICE = "Fragen werden gekürzt höchstens 30 Tage zur Missbrauchsabwehr gespeichert, ohne IP-Adresse. Die Frage und das Abfrageergebnis werden zur Beantwortung an Anthropic (USA) übermittelt; bitte keine persönlichen Angaben eingeben.";
    var fab = null, link = null, panel = null;
    var cfg = { max_chars: 500, notice: FALLBACK_NOTICE, examples: [] };
    var enabled = false;
    var bubbleTimer = null;

    function store(k, v) { try { if (v === undefined) return window.sessionStorage.getItem(k); window.sessionStorage.setItem(k, v); } catch (e) { return null; } return null; }

    function mk(tag, cls, text) {
        var e = document.createElement(tag);
        if (cls) e.className = cls;
        if (text !== undefined) e.textContent = text;
        return e;
    }

    function onChatTab() { return !!document.getElementById("chat-root"); }
    function panelOpen() { return !!panel && !panel.hidden; }

    // ── Chat-Fenster ─────────────────────────────────────────────────────────
    function buildPanel() {
        panel = mk("section", "kk-panel");
        panel.id = "kk-panel";
        panel.hidden = true;
        panel.setAttribute("role", "dialog");                          // nicht modal und ohne Fokus-Fänger
        panel.setAttribute("aria-label", "Frag Kraki");
        panel.setAttribute("data-chat-root", "panel");

        var head = mk("header", "kk-panel-head");
        var slot = mk("div", "kk-slot kk-slot-sm");
        slot.setAttribute("aria-hidden", "true");
        head.appendChild(slot);
        var title = mk("div", "kk-panel-title");
        title.appendChild(mk("strong", "", "Frag Kraki"));
        title.appendChild(mk("span", "", "Fragen zu den Daten · KI"));
        head.appendChild(title);
        var close = mk("button", "kk-panel-close", "×");
        close.type = "button";
        close.setAttribute("aria-label", "Chatfenster schliessen");
        close.addEventListener("click", function () { closePanel(true); });
        head.appendChild(close);
        panel.appendChild(head);

        var body = mk("div", "kk-panel-body");
        body.appendChild(mk("p", "kk-greet", "Hallo, ich bin Kraki. Frag mich etwas zu den Daten."));
        var chips = mk("div", "chat-chips");
        (cfg.examples || []).forEach(function (e) {
            var c = mk("button", "chat-chip", e);
            c.type = "button";
            c.setAttribute("data-q", e);
            chips.appendChild(c);
        });
        body.appendChild(chips);
        var log = mk("div", "chat-log");
        log.setAttribute("aria-live", "polite");
        body.appendChild(log);
        panel.appendChild(body);

        var foot = mk("footer", "kk-panel-foot");
        var inp = mk("textarea", "chat-input");
        inp.rows = 2;
        inp.maxLength = cfg.max_chars;
        inp.placeholder = "Deine Frage zu den Daten …";
        inp.setAttribute("aria-label", "Deine Frage zu den Daten (Enter sendet, Umschalt+Enter neue Zeile)");
        foot.appendChild(inp);
        var actions = mk("div", "chat-actions");
        var send = mk("button", "chat-send", "Frage stellen");
        send.type = "button";
        actions.appendChild(send);
        var counter = mk("span", "chat-counter", "0 / " + cfg.max_chars);
        counter.setAttribute("data-max", String(cfg.max_chars));
        actions.appendChild(counter);
        var full = mk("a", "kk-panel-full", "In eigenem Tab öffnen");
        full.href = CHAT_URL;
        actions.appendChild(full);
        foot.appendChild(actions);
        var note = mk("p", "kk-panel-note", "KI-Antwort, ungeprüft. " + (cfg.notice || FALLBACK_NOTICE) + " ");
        var more = mk("a", "source-link", "Mehr dazu");
        more.href = CHAT_URL;
        note.appendChild(more);
        foot.appendChild(note);
        panel.appendChild(foot);

        document.body.appendChild(panel);
        if (window.DliChat) window.DliChat.fillSlots();
    }

    function openPanel() {
        if (!panel) buildPanel();
        hideBubble();
        panel.hidden = false;
        fab.classList.add("kk-fab-open");
        link.setAttribute("aria-expanded", "true");
        if (window.DliChat) { window.DliChat.refreshCharts(panel); window.DliChat.setCounter(panel); }
        var inp = panel.querySelector(".chat-input");
        if (inp) inp.focus({ preventScroll: true });
    }

    function closePanel(returnFocus) {
        if (!panelOpen()) return;
        panel.hidden = true;
        fab.classList.remove("kk-fab-open");
        link.setAttribute("aria-expanded", "false");
        if (returnFocus) link.focus();
    }

    // ── Sprechblase ──────────────────────────────────────────────────────────
    function hideBubble() {
        if (bubbleTimer) { clearTimeout(bubbleTimer); bubbleTimer = null; }
        var b = fab && fab.querySelector(".kk-bubble");
        if (!b || b.classList.contains("kk-bubble-off")) return;
        b.classList.add("kk-bubble-off");
        setTimeout(function () { if (b.parentNode) b.parentNode.removeChild(b); }, 400);
    }

    function showBubbleLater() {
        if (store(KEY_BUBBLE) === "1") return;
        setTimeout(function () {
            if (!fab || fab.hidden || panelOpen() || store(KEY_BUBBLE) === "1") return;
            store(KEY_BUBBLE, "1");
            var b = mk("div", "kk-bubble");
            b.setAttribute("aria-hidden", "true");                       // doppelt zum aria-label des Links; kein Fokusfänger
            var t = mk("span", "kk-bubble-text", "Frag mich zu den Daten!");
            t.addEventListener("click", function () { openPanel(); });
            b.appendChild(t);
            var x = mk("span", "kk-bubble-x", "×");                      // nur Maus/Touch; die Blase verschwindet ohnehin nach 8 s
            x.addEventListener("click", hideBubble);
            b.appendChild(x);
            fab.appendChild(b);
            bubbleTimer = setTimeout(hideBubble, 8000);
        }, 3000);
    }

    // ── Overlay ──────────────────────────────────────────────────────────────
    function update() {
        if (!fab) return;
        var show = enabled && store(KEY_HIDDEN) !== "1" && !onChatTab();
        if (!show) closePanel(false);
        if (fab.hidden === show) fab.hidden = !show;
    }

    function build(svg) {
        fab = mk("div", "kk-fab");
        fab.id = "kk-fab";
        fab.hidden = true;
        link = mk("a", "kk-fab-link");
        link.href = CHAT_URL;                                              // ohne JavaScript oder mit Strg/Cmd/Mittelklick: Vollansicht im Tab
        link.setAttribute("aria-label", "Frag Kraki: Fragen zu den Daten");
        link.setAttribute("aria-haspopup", "dialog");
        link.setAttribute("aria-expanded", "false");
        link.setAttribute("aria-controls", "kk-panel");
        var art = mk("span", "kk-fab-art");
        art.setAttribute("aria-hidden", "true");
        art.appendChild(document.importNode(svg, true));
        link.appendChild(art);
        link.addEventListener("click", function (ev) {
            if (ev.ctrlKey || ev.metaKey || ev.shiftKey || ev.altKey || ev.button !== 0 || !window.DliChat) return;
            ev.preventDefault();
            if (panelOpen()) closePanel(false); else openPanel();
        });
        fab.appendChild(link);
        var x = mk("button", "kk-fab-x", "×");
        x.type = "button";
        x.setAttribute("aria-label", "Kraki für diese Sitzung ausblenden");
        x.addEventListener("click", function () { store(KEY_HIDDEN, "1"); hideBubble(); update(); });
        fab.appendChild(x);
        document.body.appendChild(fab);
        update();
        showBubbleLater();
        new MutationObserver(update).observe(document.getElementById("react-entry-point") || document.body, { childList: true, subtree: true });
        document.addEventListener("keydown", function (e) {
            if (e.key !== "Escape" || !panelOpen()) return;
            var a = document.activeElement;
            if (panel.contains(a) || a === link || a === document.body) { e.preventDefault(); closePanel(true); }
        });
    }

    function start() {
        if (store(KEY_HIDDEN) === "1") return;                          // ausgeblendet: nicht einmal laden
        fetch("/_chat/status", { credentials: "same-origin" }).then(function (r) { return r.json(); }).then(function (j) {
            if (!j || j.enabled !== true) return;
            enabled = true;
            if (typeof j.max_chars === "number") cfg.max_chars = j.max_chars;
            if (typeof j.notice === "string") cfg.notice = j.notice;
            if (Array.isArray(j.examples)) cfg.examples = j.examples.filter(function (x) { return typeof x === "string"; });
            if (!window.DliChat) return;
            window.DliChat.krakiSvg(build);
        }).catch(function () {});
    }

    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start); else start();
})();
