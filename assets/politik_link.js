/**
 * Tab «Politik» ist ein externer Link (faktencheck.li), kein Dashboard-Inhalt:
 * Klick/Enter öffnet die Seite in einem neuen Tab (noopener) und wählt den Tab nicht aus.
 */
(function () {
    var URL = "https://faktencheck.li";
    function open() { window.open(URL, "_blank", "noopener,noreferrer"); }
    function hit(e) {
        var t = e.target && e.target.closest ? e.target.closest(".stab-politik") : null;
        if (!t) return false;
        e.preventDefault();
        e.stopPropagation();
        return true;
    }
    document.addEventListener("click", function (e) { if (hit(e)) open(); }, true);
    document.addEventListener("keydown", function (e) {
        if ((e.key === "Enter" || e.key === " ") && hit(e)) open();
    }, true);
    // Zugänglichkeit: als Link kennzeichnen
    setInterval(function () {
        document.querySelectorAll(".stab-politik").forEach(function (el) {
            if (el.getAttribute("data-ext") !== "1") {
                el.setAttribute("data-ext", "1");
                el.setAttribute("role", "link");
                el.setAttribute("title", "Externer Link: faktencheck.li (öffnet in neuem Tab)");
            }
        });
    }, 1000);
})();
