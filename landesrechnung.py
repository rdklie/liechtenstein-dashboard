"""
landesrechnung.py — Ausgaben des Landes für das Asylwesen (Landesrechnung, Konto 590 «Flüchtlingswesen»)
==========================================================================================================
Die Zahlen stammen aus den Konten der Erfolgsrechnung der Landesrechnung (Teil IV des jährlichen Rechenschaftsberichts der
Regierung, Regierungskanzlei / Amt für Finanzen). Es gibt dafür keine maschinenlesbare Reihe; die Werte wurden aus den
PDF-Berichten übernommen und gegen die Vorjahresspalte des jeweils folgenden Berichts und gegen die Summe der Teilkonten
abgeglichen (siehe Test unten: `check()`). Nichts ist geschätzt; Lücken bleiben Lücken.

Konten (Aufwand = brutto, Ertrag = Rückerstattungen):
  590.318.01 (bis 2010: 590.318.03) Betreuung Aufnahmezentrum (bis 2010 «Betreuung Flüchtlingszentrum»)
  590.318.03 Verfahrenskosten
  590.318.04 Rechtsberatungen, Verwaltungskosten der Hilfswerke
  590.366.00 Sozialhilfe für Asylsuchende / Rückkehrhilfe (bis 2010 «Sozialhilfe für Flüchtlinge / Rückkehrhilfe»)
  590.436.00 Rückerstattungen Lohnverwaltung Asylsuchende (Ertrag)
Investitionsrechnung: 590.503.00 «Wohnraum für Schutzbedürftige» (nur 2023–2025 vorhanden, getrennt ausgewiesen).

Nicht Teil dieses Kontos: Personal- und Sachaufwand der Amtsstellen (z. B. Ausländer- und Passamt, Landespolizei, Gerichte),
Schul-, Gesundheits- und Sozialleistungen ausserhalb von Konto 590 sowie Ausgaben der Gemeinden. Die «Internationale Flüchtlings- und
Migrationshilfe» (Konto 591.367.09, Hilfe im Ausland) steht separat und ist hier nicht enthalten.
"""

import pandas as pd

BUA = "https://bua.regierung.li/bua/Services/pdf/bua{y}_{n:03d}.pdf?nr={n}&year={y}&a=1"
LLV = "https://www.llv.li/serviceportal2/amtsstellen/stabstelle-regierungskanzlei/"

# Rechnungsjahr → (Dokument, URL, Seite im Rechenschaftsbericht, Hinweis)
SOURCES = {
    2025: ("Rechenschaftsbericht 2025, IV. Landesrechnung", LLV + "rb_2025_iv-landesrechnung-2025.pdf", 556, ""),
    2024: ("Rechenschaftsbericht 2024, IV. Landesrechnung", LLV + "iv-landesrechnung-2024.pdf", 574, ""),
    2023: ("Rechenschaftsbericht 2023, IV. Landesrechnung", LLV + "iv-landesrechnung-2023.pdf", 551, ""),
    2022: ("Rechenschaftsbericht 2022, IV. Landesrechnung", LLV + "iv_landesrechnung_v_antrag-web.pdf", 540, ""),
    2021: ("Rechenschaftsbericht 2021, IV. Landesrechnung", "https://www.llv.li/import/srk/rechenschaftsberichte/archiv-2021/iv_landesrechnung.pdf", 501, ""),
    2020: ("Rechenschaftsbericht 2020 (BuA Nr. 30/2021)", BUA.format(y=2021, n=30), 517, ""),
    2019: ("Rechenschaftsbericht 2019 (BuA Nr. 29/2020)", BUA.format(y=2020, n=29), 487, ""),
    2018: ("Rechenschaftsbericht 2018 (BuA Nr. 32/2019)", BUA.format(y=2019, n=32), 472, ""),
    2017: ("Rechenschaftsbericht 2017 (BuA Nr. 24/2018)", BUA.format(y=2018, n=24), 457, ""),
    2016: ("Rechenschaftsbericht 2016 (BuA Nr. 17/2017)", BUA.format(y=2017, n=17), 459, ""),
    2015: ("Rechenschaftsbericht 2015 (BuA Nr. 30/2016)", BUA.format(y=2016, n=30), 459, ""),
    2014: ("Rechenschaftsbericht 2014 (BuA Nr. 33/2015)", BUA.format(y=2015, n=33), 457, ""),
    2013: ("Rechenschaftsbericht 2013 (BuA Nr. 41/2014)", BUA.format(y=2014, n=41), 433, "Ertrag 2013 in der Rechnungsspalte leer (kein Ertrag ausgewiesen)"),
    2012: ("Rechenschaftsbericht 2012 (BuA Nr. 12/2013)", BUA.format(y=2013, n=12), 435, ""),
    2011: ("Rechenschaftsbericht 2011 (BuA Nr. 45/2012)", BUA.format(y=2012, n=45), 443, ""),
    2010: ("Rechenschaftsbericht 2010 (BuA Nr. 46/2011)", BUA.format(y=2011, n=46), 388, ""),
    2009: ("Vorjahresspalte im Rechenschaftsbericht 2010 (BuA Nr. 46/2011)", BUA.format(y=2011, n=46), 388,
           "nur als Vorjahreswert dieses Berichts übernommen; der Bericht zu 2009 selbst wurde nicht ausgewertet"),
}

# Rechnungsjahr: (Betreuung Aufnahmezentrum, Verfahrenskosten, Rechtsberatungen/Verwaltungskosten, Sozialhilfe/Rückkehrhilfe,
#                 Aufwand Total laut Bericht, Ertrag Rückerstattungen) — CHF
ROWS = {
    2009: (377564.30, 77343.73, 50086.25, 680914.93, 1185909.21, 33924.30),
    2010: (399861.30, 38964.57, 35821.45, 492908.30, 967555.62, 5739.25),
    2011: (432473.95, 48990.21, 43672.05, 459161.42, 984297.63, 125709.06),
    2012: (427000.00, 32232.33, 23666.70, 393293.30, 876192.33, 241964.79),
    2013: (420000, 40379, 24942, 283560, 768881, 0),
    2014: (418647, 33692, 23251, 289986, 765575, 51140),
    2015: (441818, 42158, 11355, 766613, 1261943, 23457),
    2016: (584344, 70155, 44430, 1083602, 1782530, 90425),
    2017: (761497, 43301, 28359, 1048976, 1882132, 21803),
    2018: (817729, 53994, 37296, 1314512, 2223531, 23954),
    2019: (799025, 48325, 40159, 788075, 1675584, 74341),
    2020: (887059, 28214, 37016, 615788, 1568077, 0),
    2021: (908504, 40899, 46480, 507391, 1503274, 331712),
    2022: (1299654, 68893, 36736, 3015833, 4421116, 62196),
    2023: (2035366, 74908, 47662, 6070024, 8227960, 184134),
    2024: (2457411, 60767, 48992, 8375078, 10942249, 348580),
    2025: (2498347, 56135, 56525, 10020449, 12631455, 272035),
}
COLS = ["Betreuung Aufnahmezentrum", "Verfahrenskosten", "Rechtsberatungen, Verwaltungskosten der Hilfswerke",
        "Sozialhilfe für Asylsuchende / Rückkehrhilfe"]

# Investitionsrechnung, Konto 590.503.00 «Wohnraum für Schutzbedürftige» (CHF); 2024 ohne Buchung, 2010–2022 kein solches Konto
INVEST = {2023: 1179681, 2024: 0, 2025: 214151}
INVEST_SRC = {2023: (SOURCES[2023][1], 565), 2024: (SOURCES[2024][1], 588), 2025: (SOURCES[2025][1], 570)}


def table() -> pd.DataFrame:
    """Index Rechnungsjahr; Spalten COLS, aufwand (brutto), ertrag, netto (CHF)."""
    d = pd.DataFrame({y: v for y, v in ROWS.items()}, index=COLS + ["aufwand", "ertrag"]).T.astype(float)
    d["netto"] = d["aufwand"] - d["ertrag"]
    d.index.name = "year"
    return d.sort_index()


def series(kind: str = "netto") -> pd.Series:
    """kind: aufwand | ertrag | netto | sozialhilfe | betreuung (CHF je Rechnungsjahr)."""
    d = table()
    col = {"sozialhilfe": COLS[3], "betreuung": COLS[0]}.get(kind, kind)
    return d[col].rename(None)


def check(tol: float = 2.0) -> list[str]:
    """Summe der Teilkonten gegen Aufwand Total laut Bericht; leer = in Ordnung."""
    bad = []
    for y, v in ROWS.items():
        if abs(sum(v[:4]) - v[4]) > tol:
            bad.append(f"{y}: Teilkonten {sum(v[:4]):,.2f} ≠ Total {v[4]:,.2f}")
    return bad


def sources_table() -> pd.DataFrame:
    return pd.DataFrame([{"year": y, "Dokument": s[0], "url": s[1], "Seite": s[2], "Hinweis": s[3]} for y, s in sorted(SOURCES.items(), reverse=True)])
