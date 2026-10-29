"""אזהרות מסע — travel warnings by country and government body.

One table, a snapshot republished in place: a row is one notice for one
country from one body —
- מל"ל (National Security Council): the terror threat level, 1–4, written in
  free text ("רמת איום מזדמן (2)", "רמה 4/ איום גבוה", "רמת איום משולבת (2/4)",
  "(רמה 2) ... (רמה 1)"). The recipe parses every level the text names; a
  country whose text names several levels is "combined" (a region at a higher
  level than the rest). The page headline per country is the HIGHEST level
  named anywhere in it (disclosed). A text naming no digit falls back to the
  threat words (גבוה=4, בינוני=3, מזדמן=2, "אין אזהרה"/"זהירות רגילים"=1);
  a country with no parsable text is "לא צוין".
- חוץ (Foreign Ministry): consular notes. The most common text (the standing
  "stay alert" line) is "generic"; "אין המלצות/אזהרות" is "none"; anything else
  is a specific notice. A country can have several MFA rows.
- בריאות (Health Ministry): a link to the travellers' health page; the text is
  empty, so only coverage is shown.

Country positions on the map are approximate capital coordinates (the
dataset has no geometry; no world-boundary file is preloaded). A country the
table does not know is left off the map and the count is disclosed.

`logo` is a per-body logo image and `date` is empty in every row; both skipped.
"""
import re

import pandas as pd

NSC, MFA, MOH = 'מל"ל', "חוץ", "בריאות"
BODY_LABEL = {NSC: "המטה לביטחון לאומי", MFA: "משרד החוץ", MOH: "משרד הבריאות"}
BODY_ORDER = [NSC, MFA, MOH]
NA = "לא צוין"
LEVELS = [4, 3, 2, 1]
LEVEL_NAME = {4: "איום גבוה", 3: "איום בינוני", 2: "איום מזדמן", 1: "ללא אזהרה"}
LEVEL_ADVICE = {4: "להימנע מהגעה", 3: "להימנע מנסיעות שאינן חיוניות",
                2: "אמצעי זהירות מוגברים", 1: "אמצעי זהירות רגילים"}
LEVEL_COLOR = {4: "#dc3545", 3: "#9a6700", 2: "#ffc107", 1: "#198754", 0: "#6c757d"}
TOP_COMBINED = 20
LEADER_GAP_PP = 10          # continent lead in high-level share worth stating
THEME_MIN_SHARE = 0.10

# Regexes that read a threat level from the NSC free text.
_LV_PATTERNS = [
    re.compile(r"\((?:רמה\s*)?([1-4])\s*(?:/\s*([1-4]))?\s*\)"),
    re.compile(r"רמ[הת](?:\s*(?:איום|סיכון))?\s*(?:[א-ת]+\s*)?[,(]?\s*([1-4])(?:\s*(?:/|ו-?)\s*([1-4]))?(?!\d)"),
    re.compile(r"(?:גבוהה?|בינונית?|מזדמן)\s*,?\s*([1-4])\s*\)"),
]
_LV_WORDS = [(re.compile(r"איום גבוה|רמת איום גבוהה"), 4), (re.compile(r"איום בינוני"), 3),
             (re.compile(r"איום מזדמן"), 2), (re.compile(r"אין אזהר|זהירות רגילים"), 1)]

# Themes named in the NSC texts (keyword families; a text counts once per theme).
THEMES = [
    ("טרור", r"טרור"),
    ("עוינות והסתה כלפי ישראלים", r"עוינות|הסתה"),
    ("מחאות והפגנות", r"מחא|הפגנ"),
    ("מלחמה ולחימה", r"מלחמ|לחימ|חרבות ברזל"),
    ("טיסות מעבר ומעל שטח המדינה", r"קונקשיין|טיסות מעבר|מעל שט"),
    ("אזורי גבול", r"גבול"),
    ("איסור הגעה", r"איסור|אסור"),
]

# Hebrew country name (as spelled in this dataset, plus variants) -> approx. capital (lat, lon).
COORD = {
    # Europe
    "אלבניה": (41.33, 19.82), "אנדורה": (42.51, 1.52), "אוסטריה": (48.21, 16.37), "בלארוס": (53.90, 27.57),
    "בלגיה": (50.85, 4.35), "בוסניה הרצגובינה": (43.86, 18.41), "בוסניה והרצגובינה": (43.86, 18.41),
    "בולגריה": (42.70, 23.32), "קרואטיה": (45.81, 15.98), "קפריסין": (35.17, 33.36), "צ'כיה": (50.08, 14.44),
    "דנמרק": (55.68, 12.57), "אסטוניה": (59.44, 24.75), "פינלנד": (60.17, 24.94), "צרפת": (48.86, 2.35),
    "גרמניה": (52.52, 13.40), "יוון": (37.98, 23.73), "ואטיקאן-הכס הקדוש": (41.90, 12.45),
    "הוותיקן": (41.90, 12.45), "הונגריה": (47.50, 19.04), "איסלנד": (64.15, -21.94), "אירלנד": (53.35, -6.26),
    "איטליה": (41.90, 12.50), "קוסובו": (42.66, 21.17), "לטביה": (56.95, 24.11), "ליכטנשטיין": (47.14, 9.52),
    "ליטא": (54.69, 25.28), "לוקסמבורג": (49.61, 6.13), "מלטה": (35.90, 14.51), "מולדובה": (47.01, 28.86),
    "מונקו": (43.74, 7.42), "מונטנגרו": (42.44, 19.26), "הולנד": (52.37, 4.90), "מקדוניה": (42.00, 21.43),
    "צפון מקדוניה": (42.00, 21.43), "מקדוניה הצפונית": (42.00, 21.43), "נורבגיה": (59.91, 10.75),
    "פולין": (52.23, 21.01), "פורטוגל": (38.72, -9.14), "רומניה": (44.43, 26.10), "רוסיה": (55.76, 37.62),
    "צ'צניה": (43.32, 45.69), "סן מרינו": (43.94, 12.45), "סרביה": (44.79, 20.45), "סלובקיה": (48.15, 17.11),
    "סלובניה": (46.06, 14.51), "ספרד": (40.42, -3.70), "שבדיה": (59.33, 18.07), "שווייץ": (46.95, 7.45),
    "שוויץ": (46.95, 7.45), "תורכיה": (39.93, 32.86), "טורקיה": (39.93, 32.86), "אוקראינה": (50.45, 30.52),
    "בריטניה": (51.51, -0.13), "גיאורגיה": (41.72, 44.79), "ארמניה": (40.18, 44.51),
    "אזרביג'אן": (40.41, 49.87), "אזרבייג'ן": (40.41, 49.87),
    # Central Asia
    "תורכמניסטאן": (37.96, 58.33), "קירגיסטאן": (42.87, 74.59), "טג'קיסטאן": (38.56, 68.79),
    "טג'יקיסטאן": (38.56, 68.79), "קזחסטאן": (51.17, 71.45), "אוזבקיסטאן": (41.30, 69.24),
    "אפגניסטן": (34.53, 69.17), "פקיסטאן": (33.68, 73.05),
    # Americas
    "אנטיגואה-ברבודה": (17.12, -61.85), "אנטיגואה וברבודה": (17.12, -61.85), "ארגנטינה": (-34.60, -58.38),
    "איי הבהאמס": (25.05, -77.35), "ברבדוס": (13.10, -59.62), "בליז": (17.25, -88.77), "בוליביה": (-16.50, -68.15),
    "ברזיל": (-15.79, -47.88), "קנדה": (45.42, -75.70), "צ'ילה": (-33.45, -70.67), "קולומביה": (4.71, -74.07),
    "קוסטה ריקה": (9.93, -84.08), "קובה": (23.11, -82.37), "דומיניקה": (15.30, -61.39),
    "הרפובליקה הדומיניקנית": (18.49, -69.93), "אקוואדור": (-0.18, -78.47), "אל סלבדור": (13.69, -89.22),
    "גרנדה": (12.06, -61.75), "גואטמלה": (14.63, -90.51), "גויאנה": (6.80, -58.16), "גיאנה": (6.80, -58.16),
    "האיטי": (18.54, -72.34), "הונדורס": (14.07, -87.19), "ג'מאיקה": (18.02, -76.80), "מקסיקו": (19.43, -99.13),
    "ניקרגואה": (12.11, -86.24), "פנמה": (8.98, -79.52), "פרגוואי": (-25.26, -57.58), "פרו": (-12.05, -77.04),
    "סט' קיטס ונביס": (17.30, -62.72), "סנט קיטס ונוויס": (17.30, -62.72), "סט' לוציה": (14.01, -60.99),
    "סנט לוסיה": (14.01, -60.99), "סט' וינסנט והגרנדינים": (13.16, -61.23),
    "סנט וינסנט והגרנדינס": (13.16, -61.23), "סורינם": (5.85, -55.20), "טרינידד וטובגו": (10.65, -61.51),
    "ארצות הברית": (38.90, -77.04), "אורוגואי": (-34.90, -56.16), "ונצואלה": (10.48, -66.90),
    # Africa
    "אלג'יריה": (36.75, 3.06), "אנגולה": (-8.84, 13.23), "בנין": (6.50, 2.60), "בוטסואנה": (-24.65, 25.91),
    "בורקינה פאסו": (12.37, -1.52), "בורונדי": (-3.38, 29.36), "קמרון": (3.85, 11.50), "קייפ ורדה": (14.93, -23.51),
    "הרפובליקה המרכז אפריקנית": (4.39, 18.56), "רפובליקה מרכז אפריקנית": (4.39, 18.56), "צ'אד": (12.13, 15.06),
    "קומורוס": (-11.70, 43.26), "הרפובליקה של קונגו": (-4.27, 15.28),
    "הרפובליקה הדמוקרטית של קונגו": (-4.33, 15.31), "חוף השנהב (קוט דיוואר)": (6.83, -5.29),
    "ג'יבוטי": (11.59, 43.15), "מצרים": (30.04, 31.24), "גינאה המשוונית": (3.75, 8.78), "אריתריאה": (15.32, 38.93),
    "אסוואטיני": (-26.31, 31.14), "סוואזילנד": (-26.31, 31.14), "אתיופיה": (9.03, 38.74), "גאבון": (0.42, 9.47),
    "גמביה": (13.45, -16.58), "גאנה": (5.60, -0.19), "גינאה": (9.64, -13.58), "גינאה-ביסאו": (11.86, -15.60),
    "קניה": (-1.29, 36.82), "לסוטו": (-29.31, 27.48), "ליבריה": (6.30, -10.80), "לוב": (32.89, 13.19),
    "מדגסקר": (-18.88, 47.51), "מלאווי": (-13.96, 33.79), "מאלי": (12.64, -8.00), "מאוריטניה": (18.08, -15.98),
    "מאוריציוס": (-20.16, 57.50), "מרוקו": (34.02, -6.84), "מוזמביק": (-25.97, 32.57), "נמיביה": (-22.56, 17.08),
    "ניז'ר": (13.51, 2.11), "ניגריה": (9.08, 7.40), "רואנדה": (-1.95, 30.06), "סאו תומה ופרינציפה": (0.34, 6.73),
    "סנגל": (14.72, -17.47), "איי סיישל": (-4.62, 55.45), "סיירה ליאונה": (8.48, -13.23), "סומליה": (2.05, 45.32),
    "סומלילנד": (9.56, 44.06), "דרום אפריקה": (-25.75, 28.19), "דרום סודאן": (4.86, 31.57), "סודאן": (15.50, 32.56),
    "טנזניה": (-6.16, 35.75), "טוגו": (6.13, 1.22), "תוניסיה": (36.81, 10.18), "אוגנדה": (0.35, 32.58),
    "זמביה": (-15.39, 28.32), "זימבאבווה": (-17.83, 31.05),
    # Middle East & Asia
    "בחריין": (26.23, 50.59), "בנגלדש": (23.81, 90.41), "בהוטן": (27.47, 89.64), "ברוניי": (4.90, 114.94),
    "קמבודיה": (11.56, 104.92), "סין": (39.90, 116.41), "הונג קונג": (22.32, 114.17), "מזרח טימור": (-8.56, 125.57),
    "הודו": (28.61, 77.21), "אינדונזיה": (-6.21, 106.85), "איראן": (35.69, 51.39), "עיראק": (33.31, 44.37),
    "יפן": (35.68, 139.69), "ירדן": (31.95, 35.93), "כווית": (29.38, 47.99),
    "לאוס, רפובליקה דמוקרטית עממית": (17.98, 102.63), "לאוס": (17.98, 102.63), "לבנון": (33.89, 35.50),
    "מלזיה": (3.14, 101.69), "האיים המלדיביים": (4.18, 73.51), "מונגוליה": (47.89, 106.91),
    "מיאנמר": (19.76, 96.08), "נפאל": (27.72, 85.32), "קוריאה הצפונית": (39.04, 125.76),
    "קוריאה הדרומית": (37.57, 126.98), "עומאן": (23.59, 58.41), "פיליפינים": (14.60, 120.98),
    "הפיליפינים": (14.60, 120.98), "קטר": (25.29, 51.53), "קטאר": (25.29, 51.53), "ערב הסעודית": (24.71, 46.68),
    "סינגפור": (1.35, 103.82), "סרי לנקה": (6.93, 79.86), "סוריה": (33.51, 36.29), "טייואן": (25.03, 121.57),
    "תאילנד": (13.76, 100.50), "איחוד האמירויות הערביות": (24.45, 54.38), "וייטנאם": (21.03, 105.85),
    "תימן": (15.37, 44.19),
    # Pacific
    "אוסטרליה": (-35.28, 149.13), "איי קוק": (-21.21, -159.78), "פיג'י": (-18.14, 178.44), "קיריבטי": (1.45, 173.03),
    "איי מרשל": (7.09, 171.38), "מיקרונזיה": (6.92, 158.16), "נאורו": (-0.55, 166.92), "ניו זילנד": (-41.29, 174.78),
    "פפואה ניו גיני": (-9.44, 147.18), "פלאו": (7.50, 134.62), "סמואה": (-13.83, -171.76),
    "איי שלמה": (-9.43, 159.95), "טונגה": (-21.14, -175.20), "טובלו": (-8.52, 179.20), "ונואטו": (-17.73, 168.32),
}


def n(v):
    return f"{int(v):,}"


def pct(v, digits=0):
    return f"{v * 100:.{digits}f}%"


def _join(items):
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    return "، ".join(items[:-1]).replace("، ", ", ") + " ו" + items[-1]


def _levels(text):
    found = set()
    for p in _LV_PATTERNS:
        for groups in p.findall(text):
            for g in (groups if isinstance(groups, tuple) else (groups,)):
                if g:
                    found.add(int(g))
    if not found:
        for p, lv in _LV_WORDS:
            if p.search(text):
                found.add(lv)
    return found


def _href(html):
    m = re.search(r'href="([^"]+)"', html or "")
    return m.group(1).strip() if m else ""


def _norm(t):
    return re.sub(r"\s+", " ", (t or "").strip()).rstrip(".").strip()


def level_label(lv):
    return f"רמה {lv}: {LEVEL_NAME[lv]}" if lv in LEVEL_NAME else NA


def compute(frames):
    df = frames["main"].copy()
    for c in ["continent", "country", "recommendations", "details", "משרד"]:
        df[c] = df[c].astype(str).str.strip()
    df = df[df["country"] != ""]
    df["continent"] = df["continent"].where(df["continent"] != "", NA)
    df = df.sort_values(["country", "משרד", "recommendations", "details"], kind="mergesort").reset_index(drop=True)

    countries = sorted(df["country"].unique())
    n_c = len(countries)
    cont_of = (df.groupby("country")["continent"]
               .agg(lambda s: s.value_counts().sort_index().sort_values(ascending=False, kind="mergesort").index[0]))

    # ---- NSC threat level per country -------------------------------------------
    nsc = df[df["משרד"] == NSC]
    lv_sets = {}
    nsc_text = {}
    nsc_url = {}
    for c, t, d in zip(nsc["country"], nsc["recommendations"], nsc["details"]):
        lv_sets.setdefault(c, set()).update(_levels(t))
        if t:
            nsc_text.setdefault(c, []).append(t)
        u = _href(d)
        if u:
            nsc_url.setdefault(c, set()).add(u)
    max_lv = {c: (max(lv_sets[c]) if lv_sets.get(c) else 0) for c in countries}
    min_lv = {c: (min(lv_sets[c]) if lv_sets.get(c) else 0) for c in countries}
    combined = sorted([c for c in countries if max_lv[c] and min_lv[c] < max_lv[c]],
                      key=lambda c: (-max_lv[c], -(max_lv[c] - min_lv[c]), c))
    cnt = {lv: sum(1 for c in countries if max_lv[c] == lv) for lv in LEVELS + [0]}
    n_rated = n_c - cnt[0]
    hi = cnt[4] + cnt[3]

    level_cats = [lv for lv in LEVELS + [0] if cnt[lv] or lv != 0]
    levels_chart = {"cats": [level_label(lv) for lv in level_cats],
                    "data": [{"value": cnt[lv], "color": LEVEL_COLOR[lv]} for lv in level_cats]}
    levels_table = [{"level": level_label(lv), "advice": LEVEL_ADVICE.get(lv, "–"), "n": n(cnt[lv]),
                     "share": pct(cnt[lv] / n_c, 1) if n_c else "–"} for lv in level_cats]

    # ---- continent x level ------------------------------------------------------
    cont_counts = pd.Series([cont_of[c] for c in countries]).value_counts()
    conts = sorted(cont_counts.index, key=lambda k: (-int(cont_counts[k]), k))
    cont_rows = []
    for k in conts:
        cs = [c for c in countries if cont_of[c] == k]
        row = {"cont": k, "total": len(cs)}
        for lv in level_cats:
            row[lv] = sum(1 for c in cs if max_lv[c] == lv)
        rated = sum(1 for c in cs if max_lv[c])
        row["hi_share"] = (row.get(4, 0) + row.get(3, 0)) / rated if rated else 0.0
        cont_rows.append(row)
    cont_chart = {"conts": conts,
                  "series": [{"name": level_label(lv), "color": LEVEL_COLOR[lv],
                              "data": [r[lv] for r in cont_rows],
                              "pct": [round(r[lv] / r["total"] * 100, 1) if r["total"] else 0 for r in cont_rows]}
                             for lv in level_cats]}
    cont_table = [{"cont": r["cont"], "total": n(r["total"]), "cells": [n(r[lv]) for lv in level_cats],
                   "hi": pct(r["hi_share"])} for r in cont_rows]

    # ---- map --------------------------------------------------------------------
    pts = []
    off_map = []
    for c in sorted(countries, key=lambda c: (max_lv[c], c)):
        if c not in COORD:
            off_map.append(c)
            continue
        lat, lon = COORD[c]
        rng = f"{min_lv[c]}-{max_lv[c]}" if c in combined else ""
        pts.append([lat, lon, c, max_lv[c], (f"רמה משולבת: {rng}" if rng else ""), cont_of[c],
                    LEVEL_COLOR[max_lv[c]], level_label(max_lv[c])])
    legend = [{"label": level_label(lv), "color": LEVEL_COLOR[lv]} for lv in level_cats]

    # ---- level lists (chips) -----------------------------------------------------
    level_lists = []
    for lv in level_cats:
        cs = [c for c in countries if max_lv[c] == lv]
        if not cs:
            continue
        level_lists.append({"level": level_label(lv), "advice": LEVEL_ADVICE.get(lv, ""), "n": n(len(cs)),
                            "tone": {4: "danger", 3: "warn", 2: "warn", 1: "ok"}.get(lv, "subtle"),
                            "open": lv == 4,
                            "items": [{"name": c, "combined": c in combined} for c in cs]})

    # ---- combined (regional) levels ----------------------------------------------
    comb_top = combined[:TOP_COMBINED]
    comb_chart = {"names": list(reversed(comb_top)),
                  "lo": [min_lv[c] for c in reversed(comb_top)],
                  "hi": [max_lv[c] for c in reversed(comb_top)],
                  "axis": {str(lv): f"רמה {lv}" for lv in LEVELS},
                  "lo_label": [level_label(min_lv[c]) for c in reversed(comb_top)],
                  "hi_label": [level_label(max_lv[c]) for c in reversed(comb_top)]}
    comb_table = [{"name": c, "cont": cont_of[c], "lo": level_label(min_lv[c]), "hi": level_label(max_lv[c])}
                  for c in comb_top]

    # ---- NSC themes -------------------------------------------------------------
    n_nsc_txt = len(nsc_text)
    themes = []
    for label, pat in THEMES:
        rx = re.compile(pat)
        k = sum(1 for c, ts in nsc_text.items() if any(rx.search(t) for t in ts))
        themes.append((label, k))
    themes.sort(key=lambda x: (-x[1], x[0]))
    themes = [t for t in themes if t[1] > 0]
    themes_chart = {"labels": [t[0] for t in reversed(themes)], "values": [t[1] for t in reversed(themes)]}
    themes_table = [{"label": t[0], "n": n(t[1]), "share": pct(t[1] / n_nsc_txt) if n_nsc_txt else "–"}
                    for t in themes]
    hostile_rx = re.compile(r"עוינות|הסתה")
    hostile = [c for c, ts in nsc_text.items() if any(hostile_rx.search(t) for t in ts)]

    # ---- MFA notices ------------------------------------------------------------
    mfa = df[df["משרד"] == MFA]
    first_lines = mfa["recommendations"].map(lambda t: _norm(t.split("\n")[0]) if t else "")
    fl_counts = first_lines[first_lines != ""].value_counts()
    fl_counts = fl_counts.sort_index().sort_values(ascending=False, kind="mergesort")
    generic = fl_counts.index[0] if len(fl_counts) and fl_counts.iloc[0] >= max(3, 0.1 * len(mfa)) else None
    none_rx = re.compile(r"^אין (?:המלצות|אזהרות)$")
    mfa_kind = {}
    rank = {"specific": 3, "generic": 2, "none": 1}
    n_specific_rows = 0
    for c, t in zip(mfa["country"], mfa["recommendations"]):
        lines = [_norm(x) for x in t.split("\n") if _norm(x)]
        if not lines or (len(lines) == 1 and none_rx.match(lines[0])):
            k = "none"
        elif generic is not None and len(lines) == 1 and lines[0] == generic:
            k = "generic"
        else:
            k = "specific"
            n_specific_rows += 1
        if rank[k] > rank.get(mfa_kind.get(c), 0):
            mfa_kind[c] = k
    MFA_CATS = [("specific", "הודעה ייעודית למדינה"), ("generic", "המלצה כללית בלבד"),
                ("none", "אין המלצות"), ("missing", "אין רשומה של משרד החוץ")]
    mfa_cnt = {k: sum(1 for c in countries if mfa_kind.get(c, "missing") == k) for k, _ in MFA_CATS}
    mfa_cats = [(k, lab) for k, lab in MFA_CATS if mfa_cnt[k]]
    mfa_chart = {"conts": conts,
                 "series": [{"name": lab, "data": [sum(1 for c in countries if cont_of[c] == ct and
                                                       mfa_kind.get(c, "missing") == k) for ct in conts]}
                            for k, lab in mfa_cats]}
    mfa_table = [{"label": lab, "n": n(mfa_cnt[k]), "share": pct(mfa_cnt[k] / n_c) if n_c else "–"}
                 for k, lab in mfa_cats]
    multi_mfa = mfa.groupby("country").size()
    n_multi_mfa = int((multi_mfa > 1).sum())

    # ---- body coverage ----------------------------------------------------------
    bodies_present = [b for b in BODY_ORDER if (df["משרד"] == b).any()] + sorted(
        set(df["משרד"]) - set(BODY_ORDER) - {""})
    body_label = {b: BODY_LABEL.get(b, b) for b in bodies_present}
    has = {b: set(df.loc[df["משרד"] == b, "country"]) for b in bodies_present}
    cov_chart = {"conts": conts,
                 "series": [{"name": body_label[b],
                             "data": [sum(1 for c in has[b] if cont_of[c] == ct) for ct in conts]}
                            for b in bodies_present],
                 "totals": [int(cont_counts[ct]) for ct in conts]}
    cov_table = [{"cont": ct, "total": n(cont_counts[ct]),
                  "cells": [n(sum(1 for c in has[b] if cont_of[c] == ct)) for b in bodies_present]}
                 for ct in conts]
    all3 = [c for c in countries if all(c in has[b] for b in bodies_present)]
    no_moh = [c for c in countries if MOH in has and c not in has[MOH]]

    # ---- duplicates: two country names sharing one NSC page ----------------------
    by_url = {}
    for c, us in nsc_url.items():
        for u in us:
            by_url.setdefault(u, set()).add(c)
    dup_groups = sorted([sorted(v) for v in by_url.values() if len(v) > 1])

    # ---- insights -----------------------------------------------------------------
    insights = []

    def add(i, text):
        if text:
            insights.append({"id": i, "text_he": text})

    def ins_high():
        if not cnt[4] or not n_rated:
            return None
        l4 = [c for c in countries if max_lv[c] == 4]
        by_cont = pd.Series([cont_of[c] for c in l4]).value_counts()
        by_cont = by_cont.sort_index().sort_values(ascending=False, kind="mergesort")
        lead = by_cont.index[0]
        tail = ""
        if len(by_cont) == 1 or by_cont.iloc[0] > by_cont.iloc[1]:
            tail = f" הריכוז הגדול ביותר ב{lead}: {n(by_cont.iloc[0])} מדינות."
        return (f"{n(cnt[4])} מדינות ({pct(cnt[4] / n_rated)} מהמדינות המדורגות) נמצאות ברמת איום גבוהה (רמה 4) "
                f"לפחות בחלק משטחן, והמלצת המל\"ל היא להימנע מהגעה.{tail}")

    def ins_cont():
        rows = [r for r in cont_rows if r["cont"] != NA and r["total"] >= 5]
        if len(rows) < 2:
            return None
        rows = sorted(rows, key=lambda r: (-r["hi_share"], r["cont"]))
        a, b = rows[0], rows[1]
        if (a["hi_share"] - b["hi_share"]) * 100 < LEADER_GAP_PP:
            return None
        low = rows[-1]
        return (f"ב{a['cont']} {pct(a['hi_share'])} מהמדינות ברמת איום בינונית או גבוהה (רמה 3 ומעלה), "
                f"לעומת {pct(b['hi_share'])} ב{b['cont']} ו-{pct(low['hi_share'])} ב{low['cont']}.")

    def ins_none():
        if not cnt[1] or not n_rated:
            return None
        rows = [r for r in cont_rows if r["cont"] != NA and r["total"] >= 5]
        if not rows:
            return None
        best = sorted(rows, key=lambda r: (-(r.get(1, 0) / r["total"]), r["cont"]))[0]
        return (f"ל-{n(cnt[1])} מדינות ({pct(cnt[1] / n_rated)}) אין אזהרת מסע כלל (רמה 1, אמצעי זהירות רגילים); "
                f"השיעור הגבוה ביותר ב{best['cont']}: {n(best.get(1, 0))} מתוך {n(best['total'])} מדינות.")

    def ins_combined():
        if len(combined) < 3:
            return None
        to4 = [c for c in combined if max_lv[c] == 4]
        ex = _join(to4[:3] if to4 else combined[:3])
        part = f"; ב-{n(len(to4))} מהן אזור מסוים מגיע לרמה 4 (למשל {ex})" if to4 else f" (למשל {ex})"
        return (f"ב-{n(len(combined))} מדינות רמת האיום משולבת: אזור אחד מסוכן מהשאר{part}. "
                f"במפה ובגרפים מוצגת הרמה הגבוהה שבהן.")

    def ins_hostile():
        if not n_nsc_txt or len(hostile) / n_nsc_txt < THEME_MIN_SHARE:
            return None
        low = [c for c in hostile if 0 < max_lv[c] <= 2]
        tail = (f", {n(len(low))} מהן ברמת איום נמוכה (רמה 1 או 2)" if len(low) >= 3 else "")
        return (f"ב-{n(len(hostile))} מתוך {n(n_nsc_txt)} הודעות המל\"ל ({pct(len(hostile) / n_nsc_txt)}) מוזכרת "
                f"עוינות או הסתה כלפי ישראלים ויהודים{tail}.")

    def ins_mfa():
        if not mfa_cnt["specific"]:
            return None
        multi = f"; ל-{n(n_multi_mfa)} מדינות יש יותר מהודעה אחת" if n_multi_mfa else ""
        return (f"משרד החוץ פרסם הודעה ייעודית ל-{n(mfa_cnt['specific'])} "
                f"מדינות{multi}. ל-{n(mfa_cnt['generic'])} מדינות מופיעה רק ההמלצה הכללית.")

    def ins_cover():
        if len(bodies_present) < 2 or not n_c:
            return None
        s = f"{n(len(all3))} מתוך {n(n_c)} המדינות ({pct(len(all3) / n_c)}) מופיעות אצל כל {n(len(bodies_present))} הגופים"
        if no_moh:
            s += f"; ל-{n(len(no_moh))} מדינות אין רשומה של משרד הבריאות"
        return s + "."

    def ins_dup():
        if not dup_groups:
            return None
        parts = []
        for g in dup_groups[:3]:
            lv_txt = " / ".join(f"{c} (רמה {max_lv[c]})" if max_lv[c] else f"{c} ({NA})" for c in g)
            parts.append(lv_txt)
        head = ("מדינה אחת מופיעה" if len(dup_groups) == 1 else f"{n(len(dup_groups))} מדינות מופיעות")
        return (f"{head} בשני שמות שונים המפנים לאותו דף המלצה של המל\"ל: "
                f"{'; '.join(parts)}. כל שם נספר בנפרד.")

    add("high", ins_high())
    add("continent", ins_cont())
    add("none", ins_none())
    add("combined", ins_combined())
    add("hostile", ins_hostile())
    add("mfa", ins_mfa())
    add("coverage", ins_cover())
    add("duplicates", ins_dup())

    # ---- KPIs ---------------------------------------------------------------------
    kpis = {
        "countries": {"value": n_c, "display": n(n_c), "tone": "brand"},
        "l4": {"value": cnt[4], "display": n(cnt[4]), "tone": "danger" if cnt[4] else "ok"},
        "l3": {"value": cnt[3], "display": n(cnt[3]), "tone": "warn" if cnt[3] else "ok"},
        "l2": {"value": cnt[2], "display": n(cnt[2]), "tone": "brand"},
        "l1": {"value": cnt[1], "display": n(cnt[1]), "tone": "ok"},
        "combined": {"value": len(combined), "display": n(len(combined)), "tone": "info"},
    }

    top_hi_cont = sorted([r for r in cont_rows if r["cont"] != NA], key=lambda r: (-r["hi_share"], r["cont"]))
    labels = {
        "lede": (f"אזהרות המסע של ממשלת ישראל ל-{n(n_c)} מדינות ב-{n(len(conts))} יבשות, משלושה גופים: "
                 f"רמת איום הטרור של המטה לביטחון לאומי (מל\"ל), הודעות קונסולריות של משרד החוץ והפניה "
                 f"למידע בריאותי של משרד הבריאות. {n(cnt[4])} מדינות ברמה 4 (איום גבוה), {n(cnt[3])} ברמה 3, "
                 f"{n(cnt[2])} ברמה 2 ו-{n(cnt[1])} ללא אזהרה."),
        "countries_kpi": "מדינות ושטחים במאגר",
        "l4_kpi": "רמה 4: איום גבוה (להימנע מהגעה)",
        "l3_kpi": "רמה 3: איום בינוני",
        "l2_kpi": "רמה 2: איום מזדמן",
        "l1_kpi": "רמה 1: ללא אזהרת מסע",
        "combined_kpi": "מדינות עם רמת איום משולבת (לפי אזור)",
        "map_note": (f"כל נקודה היא מדינה, בצבע רמת האיום הגבוהה ביותר שהמל\"ל קבע בה (גם אם רק לאזור מסוים). "
                     f"מיקום הנקודה משוער (עיר הבירה). לחצו על נקודה לפרטים."
                     + (f" {n(len(off_map))} מדינות לא מוצגות במפה כי מיקומן אינו ידוע לעמוד: {_join(off_map)}."
                        if off_map else "")),
        "map_aria": (f"מפה אינטראקטיבית של אזהרות המסע לפי מדינה: {n(cnt[4])} מדינות ברמה 4, {n(cnt[3])} ברמה 3, "
                     f"{n(cnt[2])} ברמה 2 ו-{n(cnt[1])} ברמה 1. גרסה נגישה: ראו רשימת המדינות לפי רמה למטה."),
        "lists_note": ("המדינות מקובצות לפי רמת האיום הגבוהה ביותר שנקבעה בהן. מדינה עם סימון * היא בעלת רמה משולבת: "
                       "רק חלק משטחה ברמה זו."),
        "levels_note": (f"מתוך {n(n_rated)} מדינות מדורגות, {n(hi)} ({pct(hi / n_rated) if n_rated else '–'}) "
                        f"ברמה 3 או 4." + (f" ל-{n(cnt[0])} מדינות לא נמצאה רמה בטקסט ההמלצה." if cnt[0] else "")),
        "levels_aria": (f"גרף עמודות: מספר המדינות לפי רמת אזהרת המסע. {n(cnt[4])} ברמה 4, {n(cnt[3])} ברמה 3, "
                        f"{n(cnt[2])} ברמה 2, {n(cnt[1])} ברמה 1."),
        "levels_caption": "מספר המדינות לפי רמת אזהרת המסע (הרמה הגבוהה בכל מדינה).",
        "cont_note": ((f"שיעור המדינות ברמה 3 ומעלה הגבוה ביותר ב{top_hi_cont[0]['cont']} "
                       f"({pct(top_hi_cont[0]['hi_share'])}) והנמוך ביותר ב{top_hi_cont[-1]['cont']} "
                       f"({pct(top_hi_cont[-1]['hi_share'])}). העמודות מנורמלות ל-100%; במעבר עכבר מוצג גם המספר.")
                      if top_hi_cont else ""),
        "cont_aria": "גרף עמודות מוערמות מנורמל: התפלגות רמות האזהרה בכל יבשה.",
        "cont_caption": "מספר המדינות בכל רמת אזהרה לפי יבשה.",
        "comb_note": ((f"מדינות שבהן המל\"ל קבע רמות שונות לאזורים שונים: הנקודה הבהירה היא הרמה בשאר המדינה, "
                       f"והנקודה הכהה היא הרמה באזור המסוכן." +
                       (f" מוצגות {n(len(comb_top))} מתוך {n(len(combined))}, לפי הרמה הגבוהה."
                        if len(combined) > len(comb_top) else "")) if combined else ""),
        "comb_aria": f"תרשים משקולות: {n(len(combined))} מדינות עם רמת איום משולבת, הרמה הנמוכה והגבוהה בכל אחת.",
        "comb_caption": "מדינות עם רמת איום משולבת: הרמה בשאר המדינה והרמה באזור המסוכן.",
        "themes_note": (f"נושאים שמוזכרים בטקסט ההמלצה של המל\"ל, מתוך {n(n_nsc_txt)} הודעות. "
                        f"הודעה יכולה להזכיר כמה נושאים."),
        "themes_aria": (f"גרף עמודות אופקי: נושאים בהודעות המל\"ל. המוביל: {themes[0][0]} ({n(themes[0][1])})."
                        if themes else "גרף עמודות אופקי: נושאים בהודעות המל\"ל."),
        "themes_caption": "מספר הודעות המל\"ל שמזכירות כל נושא.",
        "mfa_note": (f"סוג ההודעה של משרד החוץ לכל מדינה. „המלצה כללית” היא הנוסח החוזר "
                     f"„{generic}”." if generic else "סוג ההודעה של משרד החוץ לכל מדינה.")
                    + (f" {n(n_specific_rows)} הודעות ייעודיות בסך הכול." if n_specific_rows else ""),
        "mfa_aria": (f"גרף עמודות מוערמות: סוג הודעת משרד החוץ לפי יבשה. {n(mfa_cnt['specific'])} מדינות "
                     f"עם הודעה ייעודית."),
        "mfa_caption": "מספר המדינות לפי סוג הודעת משרד החוץ.",
        "hi_head": "רמה 3 ומעלה",
        "cov_note": (f"בכמה מדינות בכל יבשה יש רשומה של כל גוף. {n(len(all3))} מדינות מכוסות בידי כל הגופים."),
        "cov_aria": "גרף עמודות מקובצות: מספר המדינות בכל יבשה שבהן יש רשומה לכל גוף ממשלתי.",
        "cov_caption": "מספר המדינות עם רשומה לכל גוף, לפי יבשה.",
    }

    agent_data = {
        "summary_he": (f"מפת אזהרות מסע: רמת האיום של המל\"ל בכל מדינה, לצד המלצות משרד החוץ ומשרד הבריאות. "
                       f"{n(cnt[4])} מדינות ברמה 4 ו-{n(cnt[3])} ברמה 3 מתוך {n(n_c)}."),
        "dataset_kind": "registry",
        "suggested_tags": ["אזהרות מסע", "נסיעות לחו\"ל", "מטה לביטחון לאומי", "משרד החוץ", "תיירות", "ביטחון אישי"],
        "related_ids": [],
        "spatial_coverage": "עולם",
    }

    return {
        "agent_data": agent_data,
        "kpis": kpis,
        "charts": {"map": {"points": pts, "legend": legend}, "levels": levels_chart, "continents": cont_chart,
                   "combined": comb_chart, "themes": themes_chart, "mfa": mfa_chart, "coverage": cov_chart},
        "tables": {"levels": levels_table, "level_heads": [level_label(lv) for lv in level_cats],
                   "continents": cont_table, "combined": comb_table, "themes": themes_table, "mfa": mfa_table,
                   "coverage": cov_table, "bodies": [body_label[b] for b in bodies_present],
                   "lists": level_lists},
        "flags": {"has_map": bool(pts), "has_combined": bool(combined), "has_themes": bool(themes),
                  "has_mfa": bool(mfa_cats)},
        "insights": insights,
        "labels": labels,
    }
