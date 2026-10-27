"""
correlate.py — Korrelations-Labor: Reihenkatalog und Statistik (nur numpy/pandas, keine SciPy-Abhängigkeit)
==========================================================================================================
Alle Reihen sind Jahreswerte (Index = Jahr), gelesen aus SQLite (vom Worker gespiegelt); es wird nichts live abgerufen.
Statistik: Pearson-r und Spearman-ρ mit p-Wert (t-Verteilung über die regularisierte unvollständige Betafunktion) und
95-%-Konfidenzintervall (Fisher-z); Transformationen (Veränderung, Prozent, linearer Trend entfernt); Zeitverschiebung ±N Jahre.
Der Rechenaufwand ist klein (n ≤ ~80 Jahre je Reihe).
"""

import math
from functools import lru_cache

import numpy as np
import pandas as pd

import db
from climate import INDICES as CLIM_INDICES, mann_kendall
from data_fetcher import MUNICIPALITIES, WB_INDICATORS
from imf import INDICATORS as IMF_INDICATORS
from opendata import CURATED
from migration import pxs_id, es_id

MAX_YEAR = 2025          # Projektionen (IWF ab 2026) werden nie korreliert
SEP = "|"


# ── Statistik ─────────────────────────────────────────────────────────────────

def _betacf(a: float, b: float, x: float) -> float:
    """Kettenbruch für die unvollständige Betafunktion (Numerical Recipes)."""
    tiny, eps = 1e-30, 3e-12
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 300):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def betainc(a: float, b: float, x: float) -> float:
    """Regularisierte unvollständige Betafunktion I_x(a, b)."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    bt = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1 - x))
    if x < (a + 1) / (a + b + 2):
        return bt * _betacf(a, b, x) / a
    return 1 - bt * _betacf(b, a, 1 - x) / b


def p_from_r(r: float, n: int) -> float:
    """Zweiseitiger p-Wert für eine Korrelation r bei n Paaren (t-Test mit n−2 Freiheitsgraden)."""
    if n < 3 or abs(r) >= 1:
        return 0.0 if abs(r) >= 1 and n >= 3 else float("nan")
    df = n - 2
    t2 = r * r * df / (1 - r * r)
    return betainc(df / 2, 0.5, df / (df + t2))


def ci_r(r: float, n: int, z: float = 1.959964) -> tuple[float, float]:
    if n < 4 or abs(r) >= 1:
        return float("nan"), float("nan")
    fz = math.atanh(r)
    se = 1 / math.sqrt(n - 3)
    return math.tanh(fz - z * se), math.tanh(fz + z * se)


def pearson(x: np.ndarray, y: np.ndarray) -> dict:
    n = len(x)
    if n < 3 or np.std(x) == 0 or np.std(y) == 0:
        return {"r": float("nan"), "p": float("nan"), "n": n, "lo": float("nan"), "hi": float("nan")}
    r = float(np.corrcoef(x, y)[0, 1])
    lo, hi = ci_r(r, n)
    return {"r": r, "p": p_from_r(r, n), "n": n, "lo": lo, "hi": hi}


def spearman(x: np.ndarray, y: np.ndarray) -> dict:
    if len(x) < 3:
        return {"r": float("nan"), "p": float("nan"), "n": len(x), "lo": float("nan"), "hi": float("nan")}
    rx = pd.Series(x).rank().values
    ry = pd.Series(y).rank().values
    return pearson(rx, ry)


def transform(s: pd.Series, how: str) -> pd.Series:
    """level | diff (Veränderung zum Vorjahr) | pct (Veränderung in %) | detrend (Residuen einer linearen Trendgeraden)."""
    s = s.dropna().sort_index()
    if how == "diff":
        return s.diff().dropna()
    if how == "pct":
        out = s.pct_change() * 100
        return out.replace([np.inf, -np.inf], np.nan).dropna()
    if how == "detrend":
        if len(s) < 4:
            return s.iloc[0:0]
        x = s.index.values.astype(float)
        b, a = np.polyfit(x, s.values, 1)
        return pd.Series(s.values - (a + b * x), index=s.index)
    return s


def align(a: pd.Series, b: pd.Series, lag: int = 0) -> pd.DataFrame:
    """Jahresweise Ausrichtung; lag > 0: B des Jahres t−lag wird mit A des Jahres t verglichen (B läuft voraus)."""
    bs = b.copy()
    bs.index = bs.index + lag
    df = pd.concat([a.rename("a"), bs.rename("b")], axis=1, join="inner").dropna()
    return df


def correlate(a: pd.Series, b: pd.Series, how: str = "level", lag: int = 0) -> dict:
    ta, tb = transform(a, how), transform(b, how)
    df = align(ta, tb, lag)
    pe = pearson(df["a"].values, df["b"].values)
    sp = spearman(df["a"].values, df["b"].values)
    return {"df": df, "pearson": pe, "spearman": sp, "how": how, "lag": lag}


def trend_p(s: pd.Series) -> float:
    s = s.dropna().sort_index()
    return mann_kendall(s.values.astype(float))[1] if len(s) >= 8 else float("nan")


# ── Reihenkatalog ─────────────────────────────────────────────────────────────

def _year_series(df: pd.DataFrame, ycol: str, vcol: str = "Wert") -> pd.Series:
    d = df[[ycol, vcol]].dropna()
    d = d.assign(**{ycol: pd.to_numeric(d[ycol], errors="coerce")}).dropna()
    return d.groupby(ycol)[vcol].last().astype(float).rename_axis("year").sort_index().rename(None)


def _g(key: str) -> pd.DataFrame:
    return db.get_px(key, max_age_hours=None)[0]


def _fl(df: pd.DataFrame, **conds) -> pd.DataFrame:
    for k, v in conds.items():
        df = df[df[k] == v]
    return df


def _clean(s: str) -> str:
    return str(s).lstrip("-. ").strip()


def _def(group: str, label: str, loader, unit: str = ""):
    return {"group": group, "label": label, "unit": unit, "loader": loader}


@lru_cache(maxsize=1)
def _catalog_cached(stamp: str) -> dict:
    return _build_catalog()


def catalog() -> dict[str, dict]:
    """{Reihen-ID: {group, label, unit, loader}} — einmal pro Prozess/Minute gebaut (Labels), Reihen werden erst beim Laden gelesen."""
    import time
    return _catalog_cached(str(int(time.time() // 600)))


def _build_catalog() -> dict[str, dict]:
    c: dict[str, dict] = {}

    def add(sid, group, label, loader, unit=""):
        c[sid] = _def(group, label, loader, unit)

    # Weltbank (Liechtenstein)
    for ind, label in WB_INDICATORS.items():
        add(f"wb{SEP}{ind}", "Weltbank", f"{label} (Liechtenstein)", lambda ind=ind: _year_series(db.read_world_bank(ind), "year", "value"))
    # Eurostat Tourismus / BIP (Liechtenstein)
    add(f"tour{SEP}arr", "Tourismus", "Touristische Ankünfte (Liechtenstein)", lambda: _year_series(db.read_eurostat_tourism(), "year", "value"), "Ankünfte")
    add(f"tour{SEP}nights", "Tourismus", "Übernachtungen (Liechtenstein)", lambda: _year_series(db.read_eurostat_tourism_nights(), "year", "value"), "Nächte")
    add(f"tour{SEP}gdp_eur", "Tourismus", "BIP in EUR (Eurostat-Näherung)", lambda: _year_series(db.read_eurostat_gdp_eur(), "year", "value"), "EUR")
    # IWF DataMapper (nur Ist-Werte)
    for code, (label, unit) in IMF_INDICATORS.items():
        add(f"imf{SEP}{code}", "IWF (WEO)", f"{label} [{unit}]", lambda code=code: _year_series(db.read_imf(code), "year", "value").loc[:MAX_YEAR], unit)
    # Factbook (je Bezugsjahr, jüngste Ausgabe gewinnt)
    fb = db.read_factbook_values()
    for ind in (fb["indicator"].unique() if not fb.empty else []):
        def load_fb(ind=ind):
            d = db.read_factbook_values()
            d = d[d["indicator"] == ind].sort_values(["ref_year", "year"]).groupby("ref_year").tail(1)
            return pd.Series(d["value"].values, index=d["ref_year"].astype(int).values).sort_index()
        add(f"fb{SEP}{ind}", "CIA World Factbook (Archiv)", f"Factbook: {ind}", load_fb)
    # Wohnen (Amt für Statistik)
    def wohn(gem):
        return lambda: _year_series(_fl(_g(CURATED["wohnungen"]), Gemeinde=gem), "Jahr")
    add(f"li{SEP}wohnungen", "Liechtenstein (Amt für Statistik)", "Wohnungsbestand Liechtenstein", wohn("Liechtenstein"), "Wohnungen")
    for k, m in MUNICIPALITIES.items():
        add(f"li{SEP}wohnungen_{k}", "Liechtenstein: Gemeinden", f"Wohnungsbestand {m['name']}", wohn(m["name"]), "Wohnungen")

    def pop(gem):
        def f():
            d = _g(CURATED["bevoelkerung"])
            d = d[(d["Geschlecht"] == "Geschlecht - Total") & (d["Wohngemeinde"] == gem)]
            return _year_series(d, "Jahr")
        return f
    add(f"li{SEP}pop", "Liechtenstein (Amt für Statistik)", "Ständige Wohnbevölkerung Liechtenstein", pop("Liechtenstein"), "Personen")
    for k, m in MUNICIPALITIES.items():
        add(f"li{SEP}pop_{k}", "Liechtenstein: Gemeinden", f"Einwohner {m['name']}", pop(m["name"]), "Personen")

    def leer():
        d = _g(CURATED["belegung"])
        base = d[(d["Gebäudeart"] == "Gebäudeart - Total") & (d["Nutzungsart"] == "Nutzungsart - Total") & (d["Gemeinde"] == "Liechtenstein")]
        tot = _year_series(base[base["Belegungsstatus"] == "Belegungsstatus - Total"], "Jahr")
        nb = _year_series(base[base["Belegungsstatus"] == "Am Stichtag nicht bewohnt"], "Jahr")
        return (nb / tot * 100).dropna()
    add(f"li{SEP}leer", "Liechtenstein (Amt für Statistik)", "Anteil am Stichtag nicht bewohnter Wohnungen (%)", leer, "%")

    def bauen(typ):
        return lambda: _year_series(_fl(_g(CURATED["bewilligt"]), **{"Gemeinde": "Liechtenstein", "Bewilligte neue Gebäude und Wohnungen": typ}), "Bewilligungsjahr")
    add(f"li{SEP}neuwohn", "Liechtenstein (Amt für Statistik)", "Bewilligte neue Wohnungen", bauen("Bewilligte neue Wohnungen - Total"), "Wohnungen")
    add(f"li{SEP}abbruch", "Liechtenstein (Amt für Statistik)", "Abbruchbewilligte Wohnungen",
        lambda: _year_series(_fl(_g(CURATED["abbruch"]), **{"Gemeinde": "Liechtenstein", "Gebäude- oder Wohnungstyp": "Abbruchbewilligte Wohnungen"}), "Bewilligungsjahr"), "Wohnungen")
    # Migration (Amt für Statistik)
    def auslaender(share):
        def f():
            d = _g(pxs_id("li_pop_ctz"))
            d = d.assign(lab=d["Staatsbürgerschaft"].map(_clean))
            tot = _year_series(d[d["lab"] == "Staatsbürgerschaft - Total"], "Jahr")
            li = _year_series(d[d["lab"] == "Liechtenstein"], "Jahr")
            a = tot - li
            return (a / tot * 100).dropna() if share else a
        return f
    add(f"li{SEP}auslaender_pct", "Liechtenstein (Amt für Statistik)", "Ausländeranteil Wohnbevölkerung (%)", auslaender(True), "%")
    add(f"li{SEP}auslaender", "Liechtenstein (Amt für Statistik)", "Ausländische Wohnbevölkerung", auslaender(False), "Personen")
    add(f"li{SEP}zupendler", "Liechtenstein (Amt für Statistik)", "Zupendler/Grenzgänger (Beschäftigte mit Wohnort Ausland)",
        lambda: _year_series(_g(pxs_id("li_commuters")).assign(lab=lambda d: d["Wohnland"].map(_clean)).pipe(lambda d: d[d["lab"] == "Ausland"]), "Jahr"), "Personen")

    def migr(rich):
        return lambda: _year_series(_fl(_g(pxs_id("li_migration")), Richtung=rich), "Jahr")
    add(f"li{SEP}einwanderung", "Liechtenstein (Amt für Statistik)", "Einwanderung", migr("Einwanderung"), "Personen")
    add(f"li{SEP}auswanderung", "Liechtenstein (Amt für Statistik)", "Auswanderung", migr("Auswanderung"), "Personen")
    add(f"li{SEP}saldo", "Liechtenstein (Amt für Statistik)", "Wanderungssaldo", lambda: migr("Einwanderung")() - migr("Auswanderung")(), "Personen")
    add(f"li{SEP}einbuergerungen", "Liechtenstein (Amt für Statistik)", "Einbürgerungen",
        lambda: _year_series(_g(pxs_id("li_naturalisation")).assign(lab=lambda d: d["Einbürgerungsart"].map(_clean)).pipe(lambda d: d[d["lab"] == "Einbürgerung - Total"]), "Jahr"), "Personen")
    add(f"li{SEP}asyl", "Liechtenstein (Amt für Statistik)", "Asylgesuche",
        lambda: _year_series(_fl(_g(pxs_id("li_asylum")), Bewilligungstyp="Asylgesuche"), "Jahr"), "Personen")
    try:
        import landesrechnung as LR
        add(f"li{SEP}asyl_aufwand", "Liechtenstein (Landesrechnung)", "Asylwesen: Aufwand brutto, Konto 590 (Mio. CHF)", lambda: LR.series("aufwand") / 1e6, "Mio. CHF")
        add(f"li{SEP}asyl_netto", "Liechtenstein (Landesrechnung)", "Asylwesen: Aufwand netto, Konto 590 (Mio. CHF)", lambda: LR.series("netto") / 1e6, "Mio. CHF")
        add(f"li{SEP}asyl_bestand", "Liechtenstein (Amt für Statistik)", "Bestand Asylbewerber, vorläufig Aufgenommene, Schutzbedürftige (Personen, total)",
            lambda: _year_series(_fl(_g(pxs_id("li_asyl_stock")), Bewilligungstyp="Bewilligungstyp - Total"), "Jahr"), "Personen")
        for col, lab in (("je_person_avg", "Asylwesen: Aufwand netto je Person im Bestand (CHF, Mittelbestand Vorjahr/Jahresende; Näherung)"),
                         ("je_person_end", "Asylwesen: Aufwand netto je Person im Bestand (CHF, Jahresend-Bestand; Näherung)"),
                         ("je_einwohner", "Asylwesen: Aufwand netto je Einwohner (CHF)")):
            add(f"li{SEP}asyl_{col}", "Liechtenstein (Landesrechnung)", lab, lambda col=col: LR.per_capita_live()[col].dropna(), "CHF")
    except Exception:
        pass
    for heimat, lab in (("Heimat - Total", "gesamt"), ("Liechtensteiner", "Liechtensteiner"), ("Ausländer", "Ausländer")):
        add(f"li{SEP}alq_{lab}", "Liechtenstein (Amt für Statistik)", f"Arbeitslosenquote {lab} (%)",
            lambda heimat=heimat: _year_series(_fl(_g(pxs_id("li_unemp")), Heimat=heimat), "Jahr"), "%")
    # Eurostat Migration (Anteile) für LI + Nachbarn
    for iso in ("LIE", "DEU", "AUT", "CHE"):
        for ind, lab in (("cit", "Ausländische Staatsangehörige (%)"), ("birth", "Im Ausland Geborene (%)")):
            def f(iso=iso, ind=ind):
                from tab_migration import share_table
                d = share_table(ind)
                d = d[d["iso3"] == iso]
                return pd.Series(d["share"].values, index=d["year"].astype(int).values).sort_index()
            from migration import COUNTRY_NAMES
            add(f"es{SEP}{ind}_{iso}", "Eurostat Migration", f"{lab} — {COUNTRY_NAMES[iso]}", f, "%")
    # Bildung (Amt für Statistik) und PISA (OECD via Weltbank EdStats): Reihen je Schuljahresende bzw. PISA-Erhebung
    try:
        import bildung as BI
        if not BI.pupils_by_stage().empty:
            G = "Bildung (Amt für Statistik)"
            def _pup():
                d = BI.pupils_by_stage()
                d = d[(d["Typ"] == "Total") & (d["Stufe"] == "Schulstufe - Total")]
                return pd.Series(d["Wert"].values, index=d["year"].values).sort_index()
            add(f"edu{SEP}pupils", G, "Schulkinder total (Jahr des Schuljahresendes)", _pup, "Schulkinder")
            add(f"edu{SEP}nonli_share", G, "Anteil Schulkinder ohne liechtensteinische Staatsbürgerschaft, alle Stufen (%)", lambda: BI.nonli_share(), "%")
            add(f"edu{SEP}nonli_share_s1", G, "Anteil Schulkinder ohne liechtensteinische Staatsbürgerschaft, Sekundarstufe I (%)", lambda: BI.nonli_share_sek1(), "%")

            def _cls():
                d = BI.with_year(BI._g("classes"), "Jahr")
                d = d[(d["Kennzahl"] == "Klassengrösse") & (d["Schulstufe"].map(BI.clean) == "Schulstufe - Total")]
                return pd.Series(d["Wert"].values, index=d["year"].values).sort_index()
            add(f"edu{SEP}class_size", G, "Durchschnittliche Klassengrösse, alle Stufen", _cls, "Schulkinder je Klasse")

            def _staff():
                d = BI.with_year(BI._g("staff"), "Schuljahr")
                d = d[d["Personalkategorie"] == "Lehrpersonal (VZÄ)"]
                return pd.Series(d["Wert"].values, index=d["year"].values).sort_index()
            add(f"edu{SEP}teachers", G, "Lehrpersonal (VZÄ)", _staff, "VZÄ")

            def _grads():
                d = BI._g("grads")
                d = d[d["Profil"].map(BI.clean).str.contains("Total")]
                return pd.Series(d["Wert"].values, index=pd.to_numeric(d["Jahr"]).values).sort_index()
            add(f"edu{SEP}grads", G, "Abschlüsse Sekundarstufe II total", _grads, "Abschlüsse")

            def _app():
                d = BI.with_year(BI._g("apprentices"), "Jahr")
                d = d[d["Wohnland"] == "Wohnland - Total"]
                return pd.Series(d["Wert"].values, index=d["year"].values).sort_index()
            add(f"edu{SEP}apprentices", G, "Lernende in Liechtenstein (Berufliche Grundbildung)", _app, "Lernende")

            def _stu():
                d = BI.with_year(BI._g("students"), "Jahr")
                d = d[d["Ausbildungsstätte"] == "Ausbildungsstätte - Total"]
                return pd.Series(d["Wert"].values, index=d["year"].values).sort_index()
            add(f"edu{SEP}students", G, "Studierende an Hochschulen in Liechtenstein", _stu, "Studierende")

            def _spend(share):
                def f():
                    d = BI.spend()
                    d = d.assign(F=d["Funktion"].str.strip(), y=pd.to_numeric(d["Jahr"], errors="coerce"))
                    d = d[d["Teilsektor"].str.startswith("S.13 ")]
                    e = d[d["F"].str.contains("Bildungswesen")].set_index("y")["Wert"]
                    a = d[d["F"] == "Ausgaben"].set_index("y")["Wert"]
                    return ((e / a * 100) if share else e).dropna().sort_index()
                return f
            add(f"edu{SEP}spend", G, "Staatsausgaben Bildungswesen (Mio. CHF)", _spend(False), "Mio. CHF")
            add(f"edu{SEP}spend_share", G, "Anteil Bildungswesen an den Staatsausgaben (%)", _spend(True), "%")
        if not BI.pisa().empty:
            for fach in BI.PISA_INDICATORS.values():
                add(f"pisa{SEP}LIE{SEP}{fach}", "PISA (OECD, nur Erhebungen 2000–2012)", f"PISA {fach}: Mittelwert Liechtenstein", lambda fach=fach: BI.pisa_series(fach), "Punkte")
    except Exception:
        pass
    # Landespolizei
    pm = db.read_police_metrics()
    if not pm.empty:
        from tab_police import METRIC_LABELS
        for k in pm["metric"].unique():
            add(f"pol{SEP}{k}", "Landespolizei (Jahresberichte)", METRIC_LABELS.get(k, k),
                lambda k=k: pd.Series(db.read_police_metrics().query("metric == @k")["value"].values,
                                      index=db.read_police_metrics().query("metric == @k")["year"].astype(int).values).sort_index())
    # Klima je Gemeinde (ERA5)
    ca = db.read_clim_annual()
    if not ca.empty:
        for k, m in MUNICIPALITIES.items():
            for idx, (lab, unit) in CLIM_INDICES.items():
                def f(k=k, idx=idx):
                    d = db.read_clim_annual()
                    d = d[d["muni"] == k]
                    return pd.Series(d[idx].values.astype(float), index=d["year"].astype(int).values).sort_index()
                add(f"clim{SEP}{k}{SEP}{idx}", f"Klima (ERA5) {m['name']}", f"{lab} — {m['name']}", f, unit)
    return c


def label_options() -> list[dict]:
    cat = catalog()
    opts = []
    for sid, d in sorted(cat.items(), key=lambda kv: (kv[1]["group"], kv[1]["label"])):
        opts.append({"label": f"[{d['group']}] {d['label']}", "value": sid, "search": f"{d['group']} {d['label']}"})
    return opts


def load_series(sid: str) -> pd.Series:
    d = catalog().get(sid)
    if d is None:
        return pd.Series(dtype=float)
    try:
        s = d["loader"]()
    except Exception:
        return pd.Series(dtype=float)
    s = pd.Series(s).astype(float).dropna()
    s = s[(s.index >= 1900) & (s.index <= MAX_YEAR)]
    return s.sort_index()
