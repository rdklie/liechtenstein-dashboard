/**
 * Läuft sofort beim Seitenload, bevor Dash initialisiert wird.
 * Speichert URL-Parameter global – wird vom Dash-Interval-Callback gelesen.
 */
(function () {
    var params = {};
    var search = window.location.search || "";
    search.replace(/^\?/, "").split("&").forEach(function (kv) {
        var i = kv.indexOf("=");
        if (i > 0) {
            params[decodeURIComponent(kv.slice(0, i))] =
                decodeURIComponent(kv.slice(i + 1));
        }
    });
    window._flUrlParams = params;
})();
