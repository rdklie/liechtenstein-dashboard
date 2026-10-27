/**
 * Spamschutz für E-Mail-Adresse im Header, in der Fusszeile und auf der Seite «Datenquellen».
 * Die echte Adresse wird erst per JS zusammengesetzt –
 * Bots sehen im Quelltext nur den Platzhalter.
 */
(function () {
    var u = "kontakt";
    var d = "daten.li";
    function fill() {
        var els = document.querySelectorAll("#contact-email, a[data-contact]");
        for (var i = 0; i < els.length; i++) {
            var el = els[i];
            if (el.getAttribute("data-filled")) continue;
            el.href = "mailto:" + u + "@" + d;
            el.textContent = (el.getAttribute("data-contact") && el.className.indexOf("footer-link") >= 0) ? "Kontakt" : u + "@" + d;
            el.setAttribute("data-filled", "1");
        }
    }
    // Inhalte werden von Dash nachgeladen und beim Tabwechsel neu gerendert → regelmässig nachziehen (leichtgewichtig)
    setInterval(fill, 500);
})();
