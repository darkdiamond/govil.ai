"""רמת ההשכלה של בני 25-66: CBS's multi-year release from its education register.

The release is a set of chart-data sheets ("תרשים N - ..."), and both their
order and their set change between editions (2024: 14 sheets, Feb 2025: 18,
Dec 2025: 27). Every table input (t1..t30, three spare, all optional) is read
with `cbs.grid` and recognised by its TITLE alone, never by its stem; the
reader below is generic:

  title row   the first cell starting "תרשים N" / "לוח N"
  header row  the first row after it with two or more filled cells
  label col   the leftmost column filled on every data row
  value cols  later columns with a header cell

Shares come both as percents (0-100) and as fractions (0-1): a table whose
values are all <= 1 is scaled by 100. Level labels are mapped to four levels
(academic / post-secondary / secondary or bagrut / lower) by keyword, and a
table's level axis is whichever axis carries those labels, so a transposed
sheet reads the same.

Only the overall table (four levels by year) is required, and only its
academic row. Every other kind drops its section when the edition lacks it.
A recognised table with no usable rows drops its section too: the grid's
bottom rows can be cut, and a header-only grid means the table is gone.
"""
import re

import pandas as pd
from govlib import cbs, fmt

TITLE = re.compile(r"^(?:תרשים|לוח)\s*\d+")
YEAR = re.compile(r"^(?:19|20)\d\d$")
# "בני 66-25" (printed high-low in RTL sheets): the age range of the population.
AGES = re.compile(r"בני\s*(\d{2})\s*-\s*(\d{2})")
LEVELS = ("academic", "post", "secondary", "low")
FLAGS = ("detail", "sex", "groups", "gtrend", "stream", "religion", "muslim", "yrs", "income", "incd",
         "incgap", "employ")
LEVEL_HE = {
    "academic": "השכלה אקדמית",
    "post": "על-תיכונית לא אקדמית",
    "secondary": "תיכונית או בגרות",
    "low": "נמוכה מתיכון או לא ידועה",
}
# Detailed levels, top to bottom; keyword order matters (first match wins).
DETAIL = (
    ("phd", "תואר שלישי", ("שלישי",)),
    ("ma", "תואר שני", ("שני",)),
    ("ba", "תואר ראשון", ("ראשון",)),
    ("post", "על-תיכונית לא אקדמית", ("על תיכונית", "על-תיכונית")),
    ("bagrut", "תעודת בגרות", ("בגרות",)),
    ("hs_cert", "תעודת סיום תיכון", ("תעודת סיום",)),
    ("hs", "השכלה תיכונית (ללא תעודה)", ("השכלה תיכונית",)),
    ("primary", "יסודית או חטיבת ביניים", ("יסודית",)),
    ("none", "ללא השכלה", ("חסרי",)),
    ("unknown", "אין מידע", ("אין מידע",)),
)
# Short level names for category axes (the tables keep the full names).
LEVEL_SHORT = {"academic": "אקדמית", "post": "על-תיכונית", "secondary": "תיכון/בגרות", "low": "נמוכה"}
DETAIL_HE = {k: he for k, he, _ in DETAIL}
RELIGION = (("נוצר", "נוצרים"), ("דרוז", "דרוזים"), ("מוסלמ", "מוסלמים"))
STREAM = (("ממלכתי דתי", "ממלכתי-דתי"), ("חרדי", "חרדי"), ("ממלכתי", "ממלכתי"))
STREAM_ORDER = ("ממלכתי", "ממלכתי-דתי", "חרדי")
# Row-label keyword → income type; "משולבת" first (its label also names both).
INCOME = (("משולבת", "mixed"), ("שכירה", "salaried"), ("עצמאית", "self"))
INC_ORDER = ("salaried", "self", "mixed")
INC_HE = {"salaried": "שכירים", "self": "עצמאים", "mixed": "הכנסה משולבת"}


# ── generic sheet reader ─────────────────────────────────────────────────


def _filled(r):
    return [j for j, c in enumerate(r) if c]


def _read(rows):
    """(title, label header, [col headers], [(label, [values])]) of one
    chart sheet, or None when it has no title or no data rows."""
    t = None
    for i, r in enumerate(rows):
        for c in r:
            if TITLE.match(c):
                t = i
                break
        if t is not None:
            break
    if t is None:
        return None
    title = next(c for c in rows[t] if TITLE.match(c))
    h = next((i for i in range(t + 1, len(rows)) if len(_filled(rows[i])) >= 2), None)
    if h is None:
        return None
    body = rows[h + 1:]
    body = [r for r in body if any(cbs.num(c) is not None for c in r)]
    if not body:
        return None
    width = max(len(r) for r in [rows[h]] + body)
    lab = next((j for j in range(width) if all(cbs.cell(r, j) for r in body)), None)
    if lab is None:
        return None
    vcols = [j for j in range(lab + 1, width) if cbs.cell(rows[h], j)]
    if not vcols:
        return None
    heads = [cbs.cell(rows[h], j) for j in vcols]
    data = []
    for r in body:
        vals = [cbs.val(r, j) for j in vcols]
        if any(v is not None for v in vals):
            data.append((cbs.cell(r, lab), vals))
    if not data:
        return None
    return title, cbs.cell(rows[h], lab), heads, data


def _lvl(s):
    if "נמוכה" in s:
        return "low"
    if "על תיכונית" in s or "על-תיכונית" in s:
        return "post"
    if "אקדמי" in s:
        return "academic"
    if "תיכונית או" in s or "תיכון או" in s or "בגרות או" in s:
        return "secondary"
    return None


def _detail(s):
    for k, _he, keys in DETAIL:
        if any(w in s for w in keys):
            return k
    return None


def _scaled(data):
    """Values ×100 when every one is a fraction (<= 1)."""
    vals = [v for _l, vs in data for v in vs if v is not None]
    f = 100.0 if vals and max(vals) <= 1.0 else 1.0
    return [(lab, [None if v is None else v * f for v in vs]) for lab, vs in data]


def _matrix(tbl, keyf=_lvl):
    """{category: {level: value}} with levels on whichever axis carries them
    (columns or rows); category labels as printed."""
    _title, _lh, heads, data = tbl
    data = _scaled(data)
    col_lv = [keyf(h) for h in heads]
    row_lv = [keyf(lab) for lab, _ in data]
    out = {}
    if sum(1 for x in col_lv if x) >= sum(1 for x in row_lv if x):
        for lab, vs in data:
            for lv, v in zip(col_lv, vs):
                if lv and v is not None:
                    out.setdefault(lab, {}).setdefault(lv, v)
    else:
        for lv, (_lab, vs) in zip(row_lv, data):
            if not lv:
                continue
            for h, v in zip(heads, vs):
                if v is not None:
                    out.setdefault(h, {}).setdefault(lv, v)
    return out


def _years(m):
    """A matrix keyed by year → {int year: row}, ascending."""
    return {int(k): v for k, v in sorted(m.items()) if YEAR.match(k)}


def _sex(s):
    if "גבר" in s or "זכר" in s:
        return "m"
    if "נש" in s or "נקב" in s:
        return "f"
    return None


def _norm(s, table):
    for key, he in table:
        if key in s:
            return he
    return None


# ── table kinds (by title) ───────────────────────────────────────────────


def _kind(title):
    t = title
    if "הכנסה" in t:
        if "מפורטת" in t:
            return "inc_detail"
        if "ערבים" in t and "מין" in t:
            return "inc_arab_sex"
        if "מין" in t:
            return "inc_sex"
        if "קבוצת אוכלוסייה" in t:
            return "inc_group"
        return "inc_level"
    if any(w in t for w in ("ישיבה", "בני 30", "בנות 30", "בחו\"ל", "יישוב", "ערים", "רשויות")):
        return None
    if "שנות לימוד" in t:
        if "קבוצת אוכלוסייה" in t:
            return "yrs_group"
        if "מין" in t:
            return "yrs_sex"
        return None
    if "מועסקים" in t:
        return "employ"
    if "פיקוח" in t:
        if "גברים" in t:
            return "stream_m"
        if "נשים" in t:
            return "stream_f"
        return "stream"
    if "מפורטת" in t:
        return "detail"
    if "מוסלמים" in t and "מין" in t:
        return "muslim_sex"
    if "ערבים" in t or "ערביות" in t:
        if "דת" in t:
            if "גברים" in t:
                return "rel_m"
            if "נשים" in t:
                return "rel_f"
            return "rel"
        if "מין" in t:
            return "arab_sex"
        if "בשנים" in t:
            return "arab_years"
        return None
    if "יהודים" in t:
        if "מין" in t:
            return "jew_sex"
        if "בשנים" in t:
            return "jew_years"
        return None
    if "קבוצת אוכלוסייה" in t:
        return "group"
    if "בשנים" in t and ("גברים" in t or "נשים" in t):
        if "מין" in t:
            return None  # a two-level men/women header (2024 edition)
        return "men_years" if "גברים" in t else "women_years"
    if "רמת השכלה" in t and "בשנים" in t and "מין" not in t:
        return "overall"
    return None


def _tables(frames):
    """{kind: table} over every non-empty table input; of two tables of one
    kind, the lower stem wins."""
    out = {}
    names = sorted((n for n in frames if re.fullmatch(r"t\d+", n)), key=lambda n: int(n[1:]))
    for n in names:
        df = frames[n]
        if df.empty:
            continue
        tbl = _read(cbs.grid(df, n))
        if tbl is None:
            continue
        k = _kind(tbl[0])
        if k and k not in out:
            out[k] = tbl
    return out


# ── formatting helpers ───────────────────────────────────────────────────


def _r1(v):
    return None if v is None else round(v, 1)


def _r0(v):
    return None if v is None else round(v)


def _p(v):
    return fmt.pct_of(v, 1)


def _pp(v):
    return fmt.num_he(abs(v), 1)


def _cell(v, d=1):
    return "–" if v is None else fmt.num_he(v, d)


def _nis(v):
    return "–" if v is None else fmt.int_he(v)


# ── sections ─────────────────────────────────────────────────────────────


def _overall(tbl):
    ys = _years(_matrix(tbl))
    ys = {y: r for y, r in ys.items() if "academic" in r}
    if not ys:
        raise ValueError("overall: no year with an academic share")
    return ys


def _detail_sec(tbl):
    ys = _years(_matrix(tbl, _detail))
    ys = {y: r for y, r in ys.items() if r}
    return ys or None


def _cats(m, normf=None):
    """[(label, row)] of a group matrix in printed order, labels normalised."""
    out = []
    for lab, row in m.items():
        if YEAR.match(lab):
            continue
        name = normf(lab) if normf else lab
        if name and "academic" in row:
            out.append((name, row))
    return out


def _income(tbl, keyf=_lvl):
    """{row label: {level: NIS}} (no scaling: shekels)."""
    _title, _lh, heads, data = tbl
    lv = [keyf(h) for h in heads]
    out = {}
    for lab, vs in data:
        for k, v in zip(lv, vs):
            if k and v is not None:
                out.setdefault(lab, {}).setdefault(k, v)
    return out


def _dist(tbl):
    """Years-of-schooling distribution: [years...], {series: [pct...]}.

    No mean is derived from it: the top bin and the unknowns make a computed
    mean differ from CBS's published one (13.8 vs 13.9), so the page shows
    only shares that are sums of the published percentages."""
    _title, _lh, heads, data = tbl
    xs = []
    series = {h: [] for h in heads}
    for lab, vs in data:
        if not re.fullmatch(r"\d{1,2}", lab):
            continue
        xs.append(int(lab))
        for h, v in zip(heads, vs):
            series[h].append(v)
    if len(xs) < 5:
        return None
    return xs, series


# ── compute ──────────────────────────────────────────────────────────────


def compute(frames):
    T = _tables(frames)
    if "overall" not in T:
        raise ValueError("overall table (education level by year) not found")
    rel = cbs.latest_release(frames["releases"])
    ov = _overall(T["overall"])
    years = sorted(ov)
    y0, y1 = years[0], years[-1]
    am = AGES.search(T["overall"][0])
    ages = f"{min(int(am.group(1)), int(am.group(2)))}-{max(int(am.group(1)), int(am.group(2)))}" if am else "25-66"
    a0, a1 = ov[y0]["academic"], ov[y1]["academic"]

    kpis, labels, charts, tables, ins = {}, {}, {}, {}, []
    flags = dict.fromkeys(FLAGS, False)
    yr_range = f"{y0}-{y1}" if y0 != y1 else str(y1)

    # 1. overall mix
    charts["mix"] = {"x": [str(y) for y in years],
                     "names": [LEVEL_HE[k] for k in LEVELS],
                     "series": [[_r1(ov[y].get(k)) for y in years] for k in LEVELS]}
    tables["mix"] = [[str(y)] + [_cell(ov[y].get(k)) for k in LEVELS] for y in years]
    labels["mix_cols"] = ["שנה"] + [LEVEL_HE[k] + " (%)" for k in LEVELS]
    labels["mix_aria"] = f"התפלגות רמת ההשכלה של בני {ages} בשנים {fmt.join_he([str(y) for y in years])}"
    kpis["academic"] = {"value": round(a1, 1), "display": _p(a1), "tone": "brand"}
    labels["academic_kpi"] = f"בעלי השכלה אקדמית בקרב בני {ages} ({y1})"
    if y0 != y1:
        d = a1 - a0
        kpis["academic_chg"] = {"value": round(d, 1),
                                "display": ("+" if d >= 0 else "−") + _pp(d),
                                "tone": "ok" if d > 0 else ("danger" if d < 0 else "brand")}
        labels["academic_chg_kpi"] = f"שינוי בנקודות אחוז בשיעור האקדמאים, {y0}-{y1}"
        if abs(d) >= 0.5:
            s = (f"שיעור בעלי ההשכלה האקדמית בקרב בני {ages} {'עלה' if d > 0 else 'ירד'} "
                 f"מ-{_p(a0)} בשנת {y0} ל-{_p(a1)} בשנת {y1}")
            l0, l1 = ov[y0].get("low"), ov[y1].get("low")
            if l0 is not None and l1 is not None and abs(l1 - l0) >= 0.5:
                s += (f", ושיעור בעלי השכלה נמוכה מסיום תיכון (או ללא מידע) "
                      f"{'ירד' if l1 < l0 else 'עלה'} מ-{_p(l0)} ל-{_p(l1)}")
            ins.append({"id": "trend", "text_he": s + "."})
    labels["mix_note"] = (f"התעודה הגבוהה ביותר של בני {ages}, באחוזים מכלל בני הגיל, בשנים שהלמ\"ס "
                          f"מציגה בהודעה ({fmt.join_he([str(y) for y in years])}).")

    # 2. detailed levels
    det = _detail_sec(T["detail"]) if "detail" in T else None
    if det:
        dy = sorted(det)
        keys = [k for k, _he, _w in DETAIL if any(k in det[y] for y in dy)]
        flags["detail"] = True
        charts["detail"] = {"names": [DETAIL_HE[k] for k in keys], "years": [str(y) for y in dy],
                            "series": [[_r1(det[y].get(k)) for k in keys] for y in dy]}
        tables["detail"] = [[DETAIL_HE[k]] + [_cell(det[y].get(k)) for y in dy] for k in keys]
        labels["detail_cols"] = ["תעודה גבוהה ביותר"] + [f"{y} (%)" for y in dy]
        labels["detail_aria"] = f"רמת השכלה מפורטת של בני {ages} בשנים {fmt.join_he([str(y) for y in dy])}"
        d0, d1 = det[dy[0]], det[dy[-1]]
        if len(dy) >= 2 and "ma" in d0 and "ma" in d1 and d1["ma"] - d0["ma"] >= 0.5:
            s = (f"שיעור בעלי תואר שני עלה מ-{_p(d0['ma'])} בשנת {dy[0]} ל-{_p(d1['ma'])} בשנת {dy[-1]}")
            if "ba" in d0 and "ba" in d1:
                s += f", ושיעור בעלי תואר ראשון כתעודה הגבוהה ביותר נע מ-{_p(d0['ba'])} ל-{_p(d1['ba'])}"
            ins.append({"id": "ma", "text_he": s + "."})
        labels["detail_note"] = "פירוט התעודה הגבוהה ביותר, מתואר שלישי ועד חסרי השכלה, בשנה הראשונה והאחרונה שבהודעה."

    # 3. men vs women over years
    if "men_years" in T and "women_years" in T:
        mm = _years(_matrix(T["men_years"]))
        ww = _years(_matrix(T["women_years"]))
        sy = sorted(y for y in mm if y in ww and "academic" in mm[y] and "academic" in ww[y])
        if sy:
            flags["sex"] = True
            charts["sex"] = {"x": [str(y) for y in sy],
                             "m": [_r1(mm[y]["academic"]) for y in sy],
                             "f": [_r1(ww[y]["academic"]) for y in sy],
                             "m_low": [_r1(mm[y].get("low")) for y in sy],
                             "f_low": [_r1(ww[y].get("low")) for y in sy]}
            tables["sex"] = [[str(y), _cell(mm[y]["academic"]), _cell(ww[y]["academic"]),
                              _cell(mm[y].get("low")), _cell(ww[y].get("low"))] for y in sy]
            labels["sex_aria"] = f"שיעור בעלי השכלה אקדמית ובעלי השכלה נמוכה, גברים ונשים בני {ages}, לפי שנה"
            m1, f1 = mm[sy[-1]]["academic"], ww[sy[-1]]["academic"]
            kpis["women"] = {"value": round(f1, 1), "display": _p(f1), "tone": "brand"}
            labels["women_kpi"] = f"נשים בנות {ages} בעלות השכלה אקדמית ({sy[-1]})"
            kpis["men"] = {"value": round(m1, 1), "display": _p(m1), "tone": "brand"}
            labels["men_kpi"] = f"גברים בני {ages} בעלי השכלה אקדמית ({sy[-1]})"
            g1 = f1 - m1
            if abs(g1) >= 1:
                lead, lag = ("נשים", "גברים") if g1 > 0 else ("גברים", "נשים")
                s = (f"בשנת {sy[-1]} שיעור האקדמאים בקרב {lead} ({_p(max(f1, m1))}) גבוה מזה שבקרב "
                     f"{lag} ({_p(min(f1, m1))}) ב-{_pp(g1)} נקודות אחוז")
                if len(sy) >= 2:
                    g0 = ww[sy[0]]["academic"] - mm[sy[0]]["academic"]
                    if (g0 > 0) == (g1 > 0) and abs(abs(g1) - abs(g0)) >= 1:
                        s += (f". הפער {'התרחב' if abs(g1) > abs(g0) else 'הצטמצם'} מאז {sy[0]}, "
                              f"אז עמד על {_pp(g0)} נקודות")
                ins.append({"id": "gender", "text_he": s + "."})
            labels["sex_note"] = "שיעור בעלי ההשכלה האקדמית (עמודות) ובעלי השכלה נמוכה מסיום תיכון או ללא מידע (קווים), לפי מין."

    # 4. population groups
    gm = _cats(_matrix(T["group"])) if "group" in T else []
    rows = list(gm)
    for kind, grp in (("jew_sex", "יהודים ואחרים"), ("arab_sex", "ערבים")):
        if kind in T:
            for lab, r in _matrix(T[kind]).items():
                sx = _sex(lab)
                if sx and "academic" in r:
                    rows.append((f"{grp}: {'גברים' if sx == 'm' else 'נשים'}", r))
    if len(rows) >= 2:
        flags["groups"] = True
        charts["groups"] = {"cats": [n for n, _ in rows], "names": [LEVEL_HE[k] for k in LEVELS],
                            "series": [[_r1(r.get(k)) for _n, r in rows] for k in LEVELS]}
        tables["groups"] = [[n] + [_cell(r.get(k)) for k in LEVELS] for n, r in rows]
        labels["groups_cols"] = ["קבוצה"] + [LEVEL_HE[k] + " (%)" for k in LEVELS]
        labels["groups_aria"] = f"רמת ההשכלה של בני {ages} לפי קבוצת אוכלוסייה ומין"
        labels["groups_note"] = f"התפלגות התעודה הגבוהה ביותר לפי קבוצת אוכלוסייה, ובכל קבוצה לפי מין (נתוני {y1} או השנה האחרונה בהודעה)."
    jews = next((r for n, r in gm if "יהודים" in n), None)
    arabs = next((r for n, r in gm if n.startswith("ערבים")), None)
    if arabs:
        kpis["arab"] = {"value": round(arabs["academic"], 1), "display": _p(arabs["academic"]), "tone": "brand"}
        labels["arab_kpi"] = f"ערבים בני {ages} בעלי השכלה אקדמית"
    # trend per group
    jy = _years(_matrix(T["jew_years"])) if "jew_years" in T else {}
    ay = _years(_matrix(T["arab_years"])) if "arab_years" in T else {}
    gy = sorted(set(jy) | set(ay))
    gy = [y for y in gy if "academic" in jy.get(y, {}) or "academic" in ay.get(y, {})]
    if len(gy) >= 2 and jy and ay:
        flags["gtrend"] = True
        charts["gtrend"] = {"x": [str(y) for y in gy],
                            "jews": [_r1(jy.get(y, {}).get("academic")) for y in gy],
                            "arabs": [_r1(ay.get(y, {}).get("academic")) for y in gy],
                            "arabs_low": [_r1(ay.get(y, {}).get("low")) for y in gy]}
        tables["gtrend"] = [[str(y), _cell(jy.get(y, {}).get("academic")),
                             _cell(ay.get(y, {}).get("academic")), _cell(ay.get(y, {}).get("low"))] for y in gy]
        labels["gtrend_aria"] = "שיעור בעלי השכלה אקדמית בקרב יהודים ואחרים ובקרב ערבים, לפי שנה"
        ya = [y for y in gy if "academic" in ay.get(y, {})]
        if len(ya) >= 2:
            b0, b1 = ay[ya[0]]["academic"], ay[ya[-1]]["academic"]
            if b1 - b0 >= 1:
                s = f"בקרב הערבים שיעור האקדמאים עלה מ-{_p(b0)} בשנת {ya[0]} ל-{_p(b1)} בשנת {ya[-1]}"
                ja = [y for y in gy if "academic" in jy.get(y, {})]
                if ja and ja[0] == ya[0] and ja[-1] == ya[-1]:
                    c0, c1 = jy[ja[0]]["academic"], jy[ja[-1]]["academic"]
                    s += f", לעומת עלייה מ-{_p(c0)} ל-{_p(c1)} בקרב יהודים ואחרים"
                    gap0, gap1 = c0 - b0, c1 - b1
                    if abs(gap1 - gap0) >= 1:
                        s += (f". הפער בין הקבוצות {'הצטמצם' if gap1 < gap0 else 'התרחב'} "
                              f"מ-{_pp(gap0)} ל-{_pp(gap1)} נקודות אחוז")
                ins.append({"id": "groups", "text_he": s + "."})
        labels["gtrend_note"] = "שיעור בעלי ההשכלה האקדמית בכל קבוצת אוכלוסייה, ושיעור בעלי השכלה נמוכה מסיום תיכון בקרב ערבים."
    elif jews and arabs:
        ins.append({"id": "groups", "text_he": (
            f"שיעור בעלי ההשכלה האקדמית בקרב יהודים ואחרים בני {ages} הוא {_p(jews['academic'])}, "
            f"ובקרב ערבים {_p(arabs['academic'])}.")})

    # 5. stream (פיקוח) among Jews
    st = {}
    for kind, col in (("stream", "all"), ("stream_m", "m"), ("stream_f", "f")):
        if kind in T:
            for lab, r in _matrix(T[kind]).items():
                name = _norm(lab, STREAM)
                if name and "academic" in r:
                    st.setdefault(name, {})[col] = r
    if len(st) >= 2:
        names = [he for he in STREAM_ORDER if he in st]
        cols = [c for c in ("all", "m", "f") if any(c in st[n] for n in names)]
        col_he = {"all": "כלל", "m": "גברים", "f": "נשים"}
        flags["stream"] = True
        charts["stream"] = {"cats": names, "names": [col_he[c] for c in cols],
                            "series": [[_r1(st[n].get(c, {}).get("academic")) for n in names] for c in cols]}
        tables["stream"] = [[n] + [_cell(st[n].get(c, {}).get("academic")) for c in cols]
                            + [_cell(st[n].get("all", {}).get("low"))] for n in names]
        labels["stream_cols"] = (["פיקוח"] + [f"אקדמית, {col_he[c]} (%)" for c in cols]
                                 + ["השכלה נמוכה, כלל (%)"])
        labels["stream_aria"] = "שיעור בעלי השכלה אקדמית לפי פיקוח בית הספר ומין"
        labels["stream_note"] = ("בוגרי בתי הספר בחינוך העברי לפי פיקוח בית הספר (ממלכתי, ממלכתי-דתי, חרדי): "
                                 "שיעור בעלי ההשכלה האקדמית לפי מין. הנתון מכסה רק את מי שיש עליו מידע על "
                                 "פיקוח בית הספר במרשם, ולא את כלל האוכלוסייה.")
        h = st.get("חרדי", {})
        s_ = st.get("ממלכתי", {})
        if "all" in h and "all" in s_:
            s = (f"בקרב מי שלמדו בפיקוח החרדי, {_p(h['all']['academic'])} בעלי השכלה אקדמית, "
                 f"לעומת {_p(s_['all']['academic'])} בפיקוח הממלכתי")
            if "m" in h and "f" in h:
                s += (f". בפיקוח החרדי שיעור האקדמאיות בקרב הנשים ({_p(h['f']['academic'])}) "
                      f"{'גבוה' if h['f']['academic'] > h['m']['academic'] else 'נמוך'} מזה שבקרב הגברים "
                      f"({_p(h['m']['academic'])})")
            ins.append({"id": "stream", "text_he": s + "."})

    # 6. Arab population by religion
    rl = {}
    for kind, col in (("rel", "all"), ("rel_m", "m"), ("rel_f", "f")):
        if kind in T:
            for lab, r in _matrix(T[kind]).items():
                name = _norm(lab, RELIGION)
                if name and "academic" in r:
                    rl.setdefault(name, {})[col] = r
    if len(rl) >= 2:
        names = [he for _k, he in RELIGION if he in rl]
        cols = [c for c in ("all", "m", "f") if any(c in rl[n] for n in names)]
        col_he = {"all": "כלל", "m": "גברים", "f": "נשים"}
        flags["religion"] = True
        charts["religion"] = {"cats": names, "names": [col_he[c] for c in cols],
                              "series": [[_r1(rl[n].get(c, {}).get("academic")) for n in names] for c in cols]}
        tables["religion"] = [[n] + [_cell(rl[n].get(c, {}).get("academic")) for c in cols]
                              + [_cell(rl[n].get("all", {}).get("low"))] for n in names]
        labels["religion_cols"] = (["דת"] + [f"אקדמית, {col_he[c]} (%)" for c in cols]
                                   + ["השכלה נמוכה, כלל (%)"])
        labels["religion_aria"] = "שיעור בעלי השכלה אקדמית בקרב ערבים לפי דת ומין"
        labels["religion_note"] = f"בני {ages} בחברה הערבית, שיעור בעלי ההשכלה האקדמית לפי דת ומין."
        alls = [(n, rl[n]["all"]["academic"]) for n in names if "all" in rl[n]]
        if len(alls) >= 2:
            top = max(alls, key=lambda x: (x[1], x[0]))
            low = min(alls, key=lambda x: (x[1], x[0]))
            if top[1] - low[1] >= 2:
                ins.append({"id": "religion", "text_he": (
                    f"בחברה הערבית, שיעור האקדמאים הגבוה ביותר הוא בקרב ה{top[0]} ({_p(top[1])}), "
                    f"והנמוך ביותר בקרב ה{low[0]} ({_p(low[1])}).")})

    # Muslim men vs women, academic share over years
    if "muslim_sex" in T:
        _t, _lh, heads, data = T["muslim_sex"]
        data = _scaled(data)
        sx = [_sex(h) for h in heads]
        mu = {}
        for lab, vs in data:
            if YEAR.match(lab):
                for s, v in zip(sx, vs):
                    if s and v is not None:
                        mu.setdefault(int(lab), {})[s] = v
        my = sorted(y for y in mu if "m" in mu[y] and "f" in mu[y])
        if len(my) >= 2:
            flags["muslim"] = True
            charts["muslim"] = {"x": [str(y) for y in my], "m": [_r1(mu[y]["m"]) for y in my],
                                "f": [_r1(mu[y]["f"]) for y in my]}
            tables["muslim"] = [[str(y), _cell(mu[y]["m"]), _cell(mu[y]["f"])] for y in my]
            labels["muslim_aria"] = "שיעור בעלי השכלה אקדמית בקרב גברים ונשים מוסלמים, לפי שנה"
            e, z = mu[my[0]], mu[my[-1]]
            if e["f"] < e["m"] and z["f"] > z["m"]:
                ins.append({"id": "muslim", "text_he": (
                    f"בשנת {my[0]} שיעור האקדמאיות בקרב נשים מוסלמיות ({_p(e['f'])}) היה נמוך מזה של גברים "
                    f"מוסלמים ({_p(e['m'])}). עד {my[-1]} הוא עלה ל-{_p(z['f'])} ועקף את שיעור הגברים "
                    f"({_p(z['m'])}).")})
            elif z["f"] - e["f"] >= 2:
                ins.append({"id": "muslim", "text_he": (
                    f"שיעור האקדמאיות בקרב נשים מוסלמיות עלה מ-{_p(e['f'])} בשנת {my[0]} ל-{_p(z['f'])} "
                    f"בשנת {my[-1]}; בקרב גברים מוסלמים מ-{_p(e['m'])} ל-{_p(z['m'])}.")})

    # 7. years of schooling
    dist = {}
    for kind in ("yrs_group", "yrs_sex"):
        if kind in T:
            r = _dist(T[kind])
            if r:
                dist[kind] = r
    if dist:
        xs = sorted({x for r in dist.values() for x in r[0]})
        series, names, over12 = [], [], []
        for kind in ("yrs_group", "yrs_sex"):
            if kind not in dist:
                continue
            kx, ks = dist[kind]
            for h in ks:
                pos = dict(zip(kx, ks[h]))
                names.append(h)
                series.append([_r1(pos.get(x)) for x in xs])
                tot = sum(v for v in ks[h] if v is not None)
                # a whole distribution only (percent); a cut one gives no share
                over12.append(sum(v for x, v in zip(kx, ks[h]) if v is not None and x > 12)
                              if 97 <= tot <= 103 else None)
        flags["yrs"] = True
        charts["yrs"] = {"x": [str(x) for x in xs], "names": names, "series": series}
        tables["yrs"] = [[str(x)] + [_cell(s[i], 2) for s in series] for i, x in enumerate(xs)]
        labels["yrs_cols"] = ["שנות לימוד"] + [f"{n} (%)" for n in names]
        labels["yrs_aria"] = f"התפלגות מספר שנות הלימוד של בני {ages}"
        jm = next((m for n, m in zip(names, over12) if "יהודים" in n and m is not None), None)
        am = next((m for n, m in zip(names, over12) if n.startswith("ערבים") and m is not None), None)
        gy = re.findall(r"(?:19|20)\d\d", T["yrs_group"][0]) if "yrs_group" in dist else []
        when = f"בשנת {gy[-1]} " if gy else ""
        if jm is not None and am is not None and abs(jm - am) >= 3:
            ins.append({"id": "yrs", "text_he": (
                f"{when}למדו יותר מ-12 שנות לימוד {_p(jm)} מבני {ages} היהודים והאחרים, "
                f"לעומת {_p(am)} מהערבים.")})
        labels["yrs_note"] = "התפלגות בני הגיל לפי מספר שנות הלימוד, באחוזים מכל קבוצה."

    # 8. income by level and type
    if "inc_level" in T:
        inc = {}
        for lab, r in _income(T["inc_level"]).items():
            name = next((k for w, k in INCOME if w in lab), None)
            if name:
                inc.setdefault(name, r)
        if inc:
            types = [k for k in INC_ORDER if k in inc]
            flags["income"] = True
            charts["income"] = {"cats": [LEVEL_SHORT[k] for k in LEVELS], "names": [INC_HE[t] for t in types],
                                "series": [[_r0(inc[t].get(k)) for k in LEVELS] for t in types]}
            tables["income"] = [[LEVEL_HE[k]] + [_nis(inc[t].get(k)) for t in types] for k in LEVELS]
            labels["income_cols"] = ["רמת השכלה"] + [f"{INC_HE[t]} (ש\"ח)" for t in types]
            labels["income_aria"] = "הכנסה ממוצעת לחודש מעבודה לפי רמת השכלה וסוג הכנסה"
            sal = inc.get("salaried")
            if sal and "academic" in sal and "low" in sal and sal["low"] > 0:
                ratio = sal["academic"] / sal["low"]
                kpis["income_acad"] = {"value": round(sal["academic"]), "display": fmt.int_he(sal["academic"]),
                                       "tone": "brand"}
                labels["income_acad_kpi"] = "הכנסה חודשית ממוצעת של שכירים אקדמאים (ש\"ח)"
                if ratio >= 1.2:
                    ins.append({"id": "income", "text_he": (
                        f"שכיר בעל השכלה אקדמית מרוויח בממוצע {fmt.int_he(sal['academic'])} ש\"ח לחודש, "
                        f"פי {fmt.num_he(ratio, 1)} משכיר בעל השכלה נמוכה מסיום תיכון "
                        f"({fmt.int_he(sal['low'])} ש\"ח).")})
            labels["income_note"] = ("הכנסה ממוצעת לחודש עבודה, בש\"ח, לפי התעודה הגבוהה ביותר וסוג ההכנסה: "
                                     "שכירים, עצמאים ובעלי הכנסה משולבת.")

    # 9. income by detailed level (salaried)
    if "inc_detail" in T:
        incd = {}
        for lab, r in _income(T["inc_detail"], _detail).items():
            name = next((k for w, k in INCOME if w in lab), None)
            if name:
                incd.setdefault(name, r)
        sal = incd.get("salaried")
        if sal and len(sal) >= 3:
            keys = [k for k, _he, _w in DETAIL if k in sal]
            flags["incd"] = True
            charts["incd"] = {"cats": [DETAIL_HE[k] for k in keys], "values": [_r0(sal[k]) for k in keys]}
            tcols = [k for k in INC_ORDER if k in incd]
            tables["incd"] = [[DETAIL_HE[k]] + [_nis(incd[t].get(k)) for t in tcols] for k in keys]
            labels["incd_cols"] = ["תעודה גבוהה ביותר"] + [f"{INC_HE[t]} (ש\"ח)" for t in tcols]
            labels["incd_aria"] = "הכנסה חודשית ממוצעת של שכירים לפי רמת השכלה מפורטת"
            labels["incd_note"] = "הכנסה ממוצעת לחודש של שכירים לפי התעודה הגבוהה ביותר, בש\"ח. בטבלה גם ההכנסה של עצמאים ושל בעלי הכנסה משולבת."
            if "phd" in sal and "ma" in sal and "ba" in sal:
                ins.append({"id": "incd", "text_he": (
                    f"בקרב השכירים, בעלי תואר שלישי מרוויחים בממוצע {fmt.int_he(sal['phd'])} ש\"ח לחודש, "
                    f"בעלי תואר שני {fmt.int_he(sal['ma'])} ש\"ח ובעלי תואר ראשון {fmt.int_he(sal['ba'])} ש\"ח.")})

    # 10. income gaps by sex and population group
    gap_rows = []
    for kind, pref in (("inc_sex", ""), ("inc_group", ""), ("inc_arab_sex", "ערבים: ")):
        if kind in T:
            for lab, r in _income(T[kind]).items():
                if kind == "inc_group":
                    name = lab
                else:
                    sx = _sex(lab)
                    if not sx:
                        continue
                    name = pref + ("גברים" if sx == "m" else "נשים")
                if r:
                    gap_rows.append((name, r))
    if len(gap_rows) >= 2:
        flags["incgap"] = True
        main = [(n, r) for n, r in gap_rows if not n.startswith("ערבים: ")][:4]
        charts["incgap"] = {"cats": [LEVEL_SHORT[k] for k in LEVELS], "names": [n for n, _ in main],
                            "series": [[_r0(r.get(k)) for k in LEVELS] for _n, r in main]}
        tables["incgap"] = [[n] + [_nis(r.get(k)) for k in LEVELS] for n, r in gap_rows]
        labels["incgap_cols"] = ["קבוצה"] + [f"{LEVEL_HE[k]} (ש\"ח)" for k in LEVELS]
        labels["incgap_aria"] = "הכנסה חודשית ממוצעת מעבודה לפי רמת השכלה, מין וקבוצת אוכלוסייה"
        labels["incgap_note"] = "הכנסה ממוצעת לחודש מעבודה (כל סוגי ההכנסה), בש\"ח, לפי התעודה הגבוהה ביותר."
        gd = dict(gap_rows)
        m, f = gd.get("גברים"), gd.get("נשים")
        if m and f and "academic" in m and "academic" in f and m["academic"] > f["academic"]:
            g = m["academic"] - f["academic"]
            s = (f"גברים בעלי השכלה אקדמית מרוויחים מעבודה {fmt.int_he(m['academic'])} ש\"ח לחודש בממוצע, "
                 f"לעומת {fmt.int_he(f['academic'])} ש\"ח לנשים אקדמאיות, פער של {fmt.int_he(g)} ש\"ח")
            if "post" in m and m["post"] > f["academic"]:
                s += (f". הכנסתם של גברים בעלי השכלה על-תיכונית לא אקדמית ({fmt.int_he(m['post'])} ש\"ח) "
                      f"גבוהה מזו של נשים אקדמאיות")
            ins.append({"id": "incgap", "text_he": s + "."})

    # 11. employed vs not employed
    if "employ" in T:
        em = _matrix(T["employ"])
        rowsE = []
        for lab, r in em.items():
            if "אינם" in lab or "בלתי" in lab or "לא " in lab:
                rowsE.append(("אינם מועסקים", r))
            elif "מועסק" in lab:
                rowsE.append(("מועסקים", r))
        rowsE.sort(key=lambda x: x[0] != "מועסקים")
        if len(rowsE) == 2:
            flags["employ"] = True
            charts["employ"] = {"cats": [n for n, _ in rowsE], "names": [LEVEL_HE[k] for k in LEVELS],
                                "series": [[_r1(r.get(k)) for _n, r in rowsE] for k in LEVELS]}
            tables["employ"] = [[n] + [_cell(r.get(k)) for k in LEVELS] for n, r in rowsE]
            labels["employ_cols"] = ["מצב תעסוקה"] + [LEVEL_HE[k] + " (%)" for k in LEVELS]
            labels["employ_aria"] = "רמת ההשכלה של מועסקים ושל מי שאינם מועסקים"
            labels["employ_note"] = f"התפלגות התעודה הגבוהה ביותר בקרב בני {ages} המועסקים ובקרב אלה שאינם מועסקים."
            e, n = rowsE[0][1], rowsE[1][1]
            if "academic" in e and "academic" in n and abs(e["academic"] - n["academic"]) >= 2:
                s = (f"בקרב המועסקים {_p(e['academic'])} בעלי השכלה אקדמית, לעומת {_p(n['academic'])} "
                     f"בקרב מי שאינם מועסקים")
                if "low" in e and "low" in n:
                    s += f"; שיעור בעלי ההשכלה הנמוכה הוא {_p(e['low'])} ו-{_p(n['low'])}, בהתאמה"
                ins.append({"id": "employ", "text_he": s + "."})

    # ── text ──
    lede = (f"בשנת {y1} היו {_p(a1)} מבני {ages} בישראל בעלי השכלה אקדמית"
            + (f", לעומת {_p(a0)} בשנת {y0}" if y0 != y1 else "") + ". ")
    if "women" in kpis:
        lede += f"בקרב הנשים השיעור הוא {kpis['women']['display']} ובקרב הגברים {kpis['men']['display']}. "
    lede += ("העמוד מציג את רמת ההשכלה לפי מרשם ההשכלה של הלשכה המרכזית לסטטיסטיקה (הלמ\"ס): "
             "לפי מין, קבוצת אוכלוסייה, פיקוח ודת, שנות לימוד, והקשר בין השכלה להכנסה מעבודה.")
    labels["lede"] = lede
    labels["ages"] = ages
    summary = (f"רמת ההשכלה של בני {ages} בישראל לפי מרשם ההשכלה של הלמ\"ס: {_p(a1)} בעלי השכלה אקדמית "
               f"בשנת {y1}" + (f" (לעומת {_p(a0)} בשנת {y0})" if y0 != y1 else "")
               + ", עם פילוח לפי מין, קבוצת אוכלוסייה, פיקוח, דת והכנסה.")
    desc = (f"כמה אקדמאים יש בישראל? {_p(a1)} מבני {ages} בעלי תואר אקדמי ({y1}). "
            f"רמת ההשכלה לפי מין, מגזר והכנסה, מנתוני הלמ\"ס.")
    if len(desc) > 150:
        desc = f"{_p(a1)} מבני {ages} בישראל בעלי השכלה אקדמית ({y1}). רמת ההשכלה לפי מין, מגזר והכנסה, מנתוני הלמ\"ס."

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{y0}/{y1}",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "רמת ההשכלה בישראל: אחוז האקדמאים לפי מין ומגזר",
                "description": desc,
                "name": "רמת ההשכלה בישראל",
                "alternate_names": ["רמת ההשכלה של בני 25-66", "מרשם ההשכלה של הלמ\"ס", "אחוז בעלי תואר אקדמי בישראל",
                                    "רמת השכלה של האוכלוסייה", "השכלה והכנסה בישראל"],
            },
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "flags": flags,
        "labels": labels,
        "insights": ins,
        "release": {
            "title": str(rel["TITLE"]),
            "date": fmt.d_he(pd.Timestamp(str(rel["RELEASE_DATE"]))),
            "headline": str(rel.get("HEADLINE") or "").strip(),
            "url": str(rel["PAGE_URL"]),
            "pdf": str(rel.get("REPORT_PDF_URL") or "").strip(),
            "years": yr_range,
        },
    }
