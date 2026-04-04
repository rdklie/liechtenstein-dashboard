/**
 * Spamschutz für E-Mail-Adresse im Header.
 * Die echte Adresse wird erst per JS zusammengesetzt –
 * Bots sehen im Quelltext nur den Platzhalter.
 */
(function () {
    var interval = setInterval(function () {
        var el = document.getElementById("contact-email");
        if (el) {
            var u = "kontakt";
            var d = "daten.li";
            el.href = "mailto:" + u + "@" + d;
            el.textContent = u + "@" + d;
            clearInterval(interval);
        }
    }, 200);
})();
