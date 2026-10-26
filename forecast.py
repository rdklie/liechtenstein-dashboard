"""
forecast.py — transparente Projektionen mit Unsicherheitsband und Rückwärtstest (rolling origin)
================================================================================================
Läuft im Worker (höchstens wöchentlich, statsmodels wird nur dort importiert); die App liest nur die gespeicherten Ergebnisse (fc_results).

Methoden: Naive Basis (letzter Wert), Drift (mittlere jährliche Veränderung), ETS (Exponentielle Glättung mit/ohne (gedämpftem) Trend, Auswahl nach AICc),
ARIMA (kleine Ordnungs-Suche nach AICc), Theta (θ = 2). Intervalle 80 % und 95 % aus dem jeweiligen Modell.

Güteprüfung: Expanding-Window-Rückwärtstest (ab 60 % der Reihe, Horizont 1–3 Jahre), Mass MASE = mittlerer absoluter Fehler / mittlerer absoluter
Einjahres-Fehler der naiven Prognose in der Anfangsstichprobe (< 1: besser als naive). Gezeigt wird eine Prognose NUR, wenn die Reihe lang genug ist
(n ≥ 15 aufeinanderfolgende Jahre) und die beste Methode im Rückwärtstest die naive Basis klar schlägt (MASE ≤ 0,95 × naive) und absolut brauchbar ist (MASE ≤ 2).
«Projektion, keine Vorhersage»: Strukturbrüche (Krisen, Politik, Statistikumstellungen) sind nicht modelliert; die Intervalle bilden nur die statistische
Unsicherheit des Modells ab.
"""

import json
import logging
import math
import sys
import warnings
from datetime import datetime

import numpy as np
import pandas as pd

import db

log = logging.getLogger("forecast")

MIN_N = 15
BT_START = 0.6          # Anteil der Reihe als Anfangsstichprobe des Rückwärtstests
BT_H = 3                # Horizonte 1..3 Jahre
WIN = 0.95              # Methode muss naive mindestens um 5 % schlagen
MAX_MASE = 2.0          # und absolut brauchbar sein (Mehrjahresfehler höchstens doppelt so gross wie der naive Einjahresfehler)
Z80, Z95 = 1.2815516, 1.959964

# id → (Label, Einheit, Reihen-ID aus correlate.catalog, Horizont in Jahren)
SERIES = {
    "pop_amt":   ("Ständige Wohnbevölkerung (Amt für Statistik)", "Personen", "li|pop", 15),
    "pop_wb":    ("Bevölkerung (Weltbank/UN, Jahresmitte)", "Personen", "wb|SP.POP.TOTL", 15),
    "housing":   ("Wohnungsbestand Liechtenstein (Amt für Statistik)", "Wohnungen", "li|wohnungen", 10),
    "nights":    ("Übernachtungen (Tourismus, Liechtenstein)", "Nächte", "tour|nights", 10),
    "arrivals":  ("Touristische Ankünfte (Liechtenstein)", "Ankünfte", "tour|arr", 10),
    "gdp_usd":   ("BIP, laufende Preise (Weltbank)", "USD", "wb|NY.GDP.MKTP.CD", 10),
    "gdp_pc":    ("BIP pro Kopf, laufende Preise (Weltbank)", "USD", "wb|NY.GDP.PCAP.CD", 10),
    "temp_vaduz": ("Jahresmitteltemperatur Vaduz (ERA5)", "°C", "clim|vaduz|tmean", 10),
}


# ── Hilfen ────────────────────────────────────────────────────────────────────

def contiguous_tail(s: pd.Series) -> pd.Series:
    """Längster aufeinanderfolgender Endabschnitt (jährliche Schritte); Lücken (z. B. Jahrzehnt-Stützpunkte) werden nicht überbrückt."""
    s = s.dropna().sort_index()
    if s.empty:
        return s
    years = s.index.values
    start = len(years) - 1
    while start > 0 and years[start] - years[start - 1] == 1:
        start -= 1
    return s.iloc[start:]


def _aicc(aic: float, k: int, n: int) -> float:
    return aic + (2 * k * (k + 1)) / max(n - k - 1, 1)


class Fit:
    """Ergebnis einer Modellanpassung: forecast(h) → (mean, lo80, hi80, lo95, hi95) und eine Beschreibung der Annahmen."""

    def __init__(self, fn, text):
        self.fn, self.text = fn, text

    def forecast(self, h):
        return self.fn(h)


def _normal(mean, sd):
    mean = np.asarray(mean, float)
    sd = np.asarray(sd, float)
    return mean, mean - Z80 * sd, mean + Z80 * sd, mean - Z95 * sd, mean + Z95 * sd


def fit_naive(y):
    sd1 = float(np.std(np.diff(y), ddof=1)) if len(y) > 2 else 0.0
    return Fit(lambda h: _normal(np.repeat(y[-1], h), sd1 * np.sqrt(np.arange(1, h + 1))),
               "Naive Basis: der letzte beobachtete Wert bleibt konstant; Unsicherheit wächst mit √Horizont (Standardabweichung der Jahresveränderungen).")


def fit_drift(y):
    d = np.diff(y)
    mu = float(np.mean(d))
    sd1 = float(np.std(d, ddof=1)) if len(d) > 2 else 0.0
    return Fit(lambda h: _normal(y[-1] + mu * np.arange(1, h + 1), sd1 * np.sqrt(np.arange(1, h + 1))),
               f"Drift: Fortschreibung der durchschnittlichen jährlichen Veränderung ({mu:+,.4g} pro Jahr).")


def fit_ets(y):
    from statsmodels.tsa.exponential_smoothing.ets import ETSModel
    ys = pd.Series(np.asarray(y, float), index=pd.RangeIndex(len(y)))
    best = None
    for trend, damped in ((None, False), ("add", False), ("add", True)):
        try:
            res = ETSModel(ys, error="add", trend=trend, damped_trend=damped).fit(disp=False)
        except Exception:
            continue
        k = len(res.params)
        sc = _aicc(res.aic, k, len(y))
        if best is None or sc < best[0]:
            best = (sc, res, trend, damped)
    if best is None:
        return None
    _, res, trend, damped = best

    def fn(h):
        out = []
        for alpha in (0.2, 0.05):
            fr = res.get_prediction(start=len(y), end=len(y) + h - 1).summary_frame(alpha=alpha)
            out.append(fr)
        m = out[0]["mean"].values
        return (m, out[0]["pi_lower"].values, out[0]["pi_upper"].values, out[1]["pi_lower"].values, out[1]["pi_upper"].values)
    desc = "ETS (additive Fehler)" + (", Trend" if trend else ", kein Trend") + (" gedämpft" if damped else "") + " — Auswahl nach AICc unter {kein Trend, Trend, gedämpfter Trend}."
    return Fit(fn, desc)


def fit_arima(y):
    from statsmodels.tsa.arima.model import ARIMA
    best = None
    for order, trend in (((0, 1, 0), "t"), ((1, 1, 0), "t"), ((0, 1, 1), "t"), ((1, 1, 1), "t"), ((2, 1, 0), "t"), ((0, 2, 1), "n"), ((0, 1, 0), "n")):
        try:
            res = ARIMA(y, order=order, trend=trend).fit()
        except Exception:
            continue
        sc = _aicc(res.aic, len(res.params), len(y))
        if np.isfinite(sc) and (best is None or sc < best[0]):
            best = (sc, res, order, trend)
    if best is None:
        return None
    _, res, order, trend = best

    def fn(h):
        f80 = res.get_forecast(h).conf_int(alpha=0.2)
        f95 = res.get_forecast(h).conf_int(alpha=0.05)
        m = np.asarray(res.get_forecast(h).predicted_mean)
        f80, f95 = np.asarray(f80), np.asarray(f95)
        return m, f80[:, 0], f80[:, 1], f95[:, 0], f95[:, 1]
    return Fit(fn, f"ARIMA{order}" + (" mit Drift" if trend == "t" else "") + " — Ordnung nach AICc aus einer kleinen Auswahl gewählt.")


def fit_theta(y):
    from statsmodels.tsa.forecasting.theta import ThetaModel
    s = pd.Series(y, index=pd.RangeIndex(len(y)))
    res = ThetaModel(s, period=1, deseasonalize=False).fit()

    def fn(h):
        m = np.asarray(res.forecast(h))
        i80 = np.asarray(res.prediction_intervals(h, alpha=0.2))
        i95 = np.asarray(res.prediction_intervals(h, alpha=0.05))
        return m, i80[:, 0], i80[:, 1], i95[:, 0], i95[:, 1]
    return Fit(fn, "Theta-Methode (θ = 2): Mittel aus linearer Trendfortschreibung und einfacher exponentieller Glättung.")


METHODS = {"naive": ("Naive Basis", fit_naive), "drift": ("Drift", fit_drift), "ets": ("ETS", fit_ets), "arima": ("ARIMA", fit_arima), "theta": ("Theta", fit_theta)}


# ── Rückwärtstest ─────────────────────────────────────────────────────────────

def backtest(y: np.ndarray) -> dict:
    n = len(y)
    n0 = max(10, int(BT_START * n))
    scale = float(np.mean(np.abs(np.diff(y[:n0])))) or float(np.mean(np.abs(np.diff(y)))) or 1.0
    res = {}
    for key, (name, fitter) in METHODS.items():
        errs, in80, in95, cnt = [], 0, 0, 0
        for t in range(n0, n):
            h = min(BT_H, n - t)
            try:
                fit = fitter(y[:t])
                if fit is None:
                    raise ValueError("kein Modell")
                m, l80, h80, l95, h95 = fit.forecast(h)
            except Exception:
                continue
            for j in range(h):
                a = y[t + j]
                errs.append(abs(a - m[j]))
                in80 += int(l80[j] <= a <= h80[j])
                in95 += int(l95[j] <= a <= h95[j])
                cnt += 1
        if cnt:
            res[key] = {"name": name, "mase": float(np.mean(errs) / scale), "mae": float(np.mean(errs)), "cov80": in80 / cnt, "cov95": in95 / cnt,
                        "n_forecasts": cnt, "n_origins": n - n0}
    return res


def compute_series(sid: str, label: str, unit: str, y_series: pd.Series, horizon: int) -> dict:
    out = {"series": sid, "label": label, "unit": unit, "computed_at": datetime.utcnow().strftime("%Y-%m-%d"), "horizon": horizon}
    s = contiguous_tail(y_series)
    out["n"] = int(len(s))
    out["history"] = {"years": [int(i) for i in s.index], "values": [float(v) for v in s.values]}
    if len(s) < MIN_N:
        out.update(decision="none", reason=f"Reihe zu kurz: {len(s)} aufeinanderfolgende Jahreswerte (Minimum {MIN_N}).", methods={})
        return out
    y = s.values.astype(float)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        bt = backtest(y)
        out["methods"] = bt
        cands = {k: v for k, v in bt.items() if k != "naive"}
        if "naive" not in bt or not cands:
            out.update(decision="none", reason="Rückwärtstest nicht berechenbar.")
            return out
        best = min(cands, key=lambda k: cands[k]["mase"])
        out["best"] = best
        if cands[best]["mase"] > WIN * bt["naive"]["mase"]:
            out.update(decision="none", reason=f"Keine Methode schlägt die naive Basis im Rückwärtstest klar (beste: {cands[best]['name']} MASE {cands[best]['mase']:.2f} "
                                               f"vs. naive {bt['naive']['mase']:.2f}). Eine Prognose wäre nicht besser als «bleibt wie zuletzt» und wird deshalb nicht gezeigt.")
            return out
        if cands[best]["mase"] > MAX_MASE:
            out.update(decision="none", reason=f"Prognosegüte zu schlecht: beste Methode ({cands[best]['name']}) hat im Rückwärtstest MASE {cands[best]['mase']:.1f} "
                                               f"(Grenze {MAX_MASE:.0f}); die Reihe ist zu unregelmässig (Schocks, Strukturbrüche) für eine verlässliche Projektion.")
            return out
        fc = {}
        for key in METHODS:
            if key == "naive" and best != "naive":
                continue
            try:
                fit = METHODS[key][1](y)
                m, l80, h80, l95, h95 = fit.forecast(horizon)
            except Exception:
                continue
            last = int(s.index[-1])
            fc[key] = {"years": list(range(last + 1, last + horizon + 1)), "mean": [float(v) for v in m], "lo80": [float(v) for v in l80],
                       "hi80": [float(v) for v in h80], "lo95": [float(v) for v in l95], "hi95": [float(v) for v in h95], "assumptions": fit.text}
        out["forecasts"] = fc
        out.update(decision="forecast", reason="")
    return out


def run_all(max_age_days: float = 7, force: bool = False) -> int:
    """Alle Reihen neu rechnen, wenn die gespeicherten Ergebnisse älter als max_age_days sind. → Anzahl berechneter Reihen"""
    import correlate
    existing = db.read_fc_all()
    now = datetime.utcnow()
    done = 0
    for sid, (label, unit, cid, horizon) in SERIES.items():
        row = existing.get(sid)
        if row and not force and (now - row["computed"]).days < max_age_days:
            continue
        ser = correlate.load_series(cid)
        if ser.empty:
            log.warning("Prognose %s: keine Daten (%s)", sid, cid)
            continue
        res = compute_series(sid, label, unit, ser, horizon)
        db.write_fc(sid, res)
        log.info("Prognose %s: n=%d, Entscheidung %s", sid, res.get("n", 0), res.get("decision"))
        done += 1
    return done


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", handlers=[logging.StreamHandler(sys.stdout)])
    db.init_db()
    run_all(force=True)
