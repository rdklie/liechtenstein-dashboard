/**
 * Kraki als schwebendes Overlay unten rechts auf allen Seiten des Dashboards: Klick öffnet den Chat («Frage zu den Daten»).
 * Nur sichtbar, wenn /_chat/status enabled:true meldet; auf dem Chat-Tab selbst ausgeblendet. Die Grafik (assets/kraki.svg) wird per DOMParser eingesetzt.
 * Gemerkt wird nur per sessionStorage (ob die Sprechblase schon gezeigt wurde, ob Kraki für die Sitzung ausgeblendet ist): keine Cookies, nichts an den Server.
 */
(function () {
    var KEY_HIDDEN = "dli_kraki_hidden";
    var KEY_BUBBLE = "dli_kraki_bubble";
    var CHAT_URL = "/?tab=frage";
    var fab = null;
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

    function openChat(ev) {
        // Vorhandener Tab (kein Neuladen): der Tab «… Frag Kraki» der Tab-Leiste; sonst folgt der Link /?tab=frage wie bei den Bereichskarten.
        var tabs = document.querySelectorAll(".stab");
        for (var i = 0; i < tabs.length; i++) {
            if ((tabs[i].textContent || "").indexOf("Frag Kraki") >= 0) {
                ev.preventDefault();
                tabs[i].click();
                var root = document.getElementById("tab-content");
                if (root && root.scrollIntoView) root.scrollIntoView({ behavior: "auto", block: "start" });
                return;
            }
        }
    }

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
            if (!fab || fab.hidden || store(KEY_BUBBLE) === "1") return;
            store(KEY_BUBBLE, "1");
            var b = mk("div", "kk-bubble");
            b.setAttribute("aria-hidden", "true");                       // doppelt zum aria-label des Links; kein Fokusfänger
            b.appendChild(mk("span", "kk-bubble-text", "Frag mich zu den Daten!"));
            var x = mk("span", "kk-bubble-x", "×");                      // nur Maus/Touch; die Blase verschwindet ohnehin nach 8 s
            x.addEventListener("click", hideBubble);
            b.appendChild(x);
            fab.appendChild(b);
            bubbleTimer = setTimeout(hideBubble, 8000);
        }, 3000);
    }

    function update() {
        if (!fab) return;
        var show = enabled && store(KEY_HIDDEN) !== "1" && !onChatTab();
        if (fab.hidden === show) fab.hidden = !show;
    }

    function build(svg) {
        fab = mk("div", "kk-fab");
        fab.id = "kk-fab";
        fab.hidden = true;
        var link = mk("a", "kk-fab-link");
        link.href = CHAT_URL;
        link.setAttribute("aria-label", "Frag Kraki: Fragen zu den Daten");
        var art = mk("span", "kk-fab-art");
        art.setAttribute("aria-hidden", "true");
        art.appendChild(document.importNode(svg, true));
        link.appendChild(art);
        link.addEventListener("click", function (ev) { hideBubble(); openChat(ev); });
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
    }

    function start() {
        if (store(KEY_HIDDEN) === "1") return;                          // ausgeblendet: nicht einmal laden
        fetch("/_chat/status", { credentials: "same-origin" }).then(function (r) { return r.json(); }).then(function (j) {
            if (!j || j.enabled !== true) return;
            enabled = true;
            return fetch("/assets/kraki.svg", { credentials: "same-origin" }).then(function (r) { return r.ok ? r.text() : ""; }).then(function (t) {
                var doc = t ? new DOMParser().parseFromString(t, "image/svg+xml") : null;
                var el = doc && doc.documentElement && doc.documentElement.nodeName.toLowerCase() === "svg" ? doc.documentElement : null;
                if (!el) return;
                ["role", "aria-label", "width", "height"].forEach(function (a) { el.removeAttribute(a); });
                el.setAttribute("aria-hidden", "true");
                el.setAttribute("focusable", "false");
                build(el);
            });
        }).catch(function () {});
    }

    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start); else start();
})();
