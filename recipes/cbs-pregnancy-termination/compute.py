"""פניות לוועדות להפסקת היריון: CBS's yearly release on applications to the
pregnancy-termination committees.

Each edition is a set of chart-data sheets ("תרשים N - ..."). Most of them
already hold a long series (1988 onward, 2000 onward, 2004 onward), so the
source reads only the newest edition (`history_releases: 1`). CBS renumbers
the charts between editions (grounds-for-approval was chart 12, 13, then 14),
so every table input (t1..t23, the last three spare, all optional) is
classified by its TITLE text, never by its stem:

  trend      שיעור הפניות לוועדות ... (no "לפי")        rate per 1,000 + count, by year
  approved   אחוז האישורים ...                          % approved, by year
  ratio      ... ל-100 הריונות ידועים (no "לפי")         per 100 known pregnancies, by year
  ratio_grp  ... ל-100 הריונות ידועים לפי קבוצת אוכלוסייה  same, by population group
  religion   שיעורי הפניות ... לפי דת                    rate by religion, by year
  age        שיעורי הפניות ... לפי גיל וקבוצת אוכלוסייה    rate by age x group
  marital    הנשואות והרווקות                            % married / single, by year
  marital_g  ... לפי מצב משפחתי וקבוצת אוכלוסייה           same, by group
  grounds    ... לפי סעיף החוק                            approvals by legal ground, by year
  grounds_g  ... סעיפי החוק וקבוצת אוכלוסייה               same, by group
  grounds_w  ... סעיפי החוק ושבוע היריון                   same, by gestation week band
  weeks      ... לפי שבוע היריון ודת                       week band by religion, two years
  edu        שיעורי פניות ... השכלה                       rate by education x group
  intl       ... במדינות נבחרות                          rate per 1,000, selected countries

A chart missing from the newest edition drops its section. A recognised
chart whose header labels are gone raises (the layout changed: a human
should look). Wording is neutral and descriptive: the page reports the
figures CBS publishes and draws no causal conclusions.
"""
import re

import pandas as pd
from govlib import cbs, fmt

STEM = re.compile(r"t\d+[a-z]?")
TITLE = re.compile("^תרשים\\s*\\d+[א-ת]?\\s*[-\u2013\u2014]\\s*(.+)$")
YEAR = re.compile(r"^(19|20)\d\d$")
TITLE_YEAR = re.compile(r"((?:19|20)\d\d)\s*$")
# Two readings closer than this are "about the same" (rate points / pp).
FLAT_RATE = 0.2
FLAT_PP = 1.0


# ── tables ──────────────────────────────────────────────────────────────


def _kind(t):
    if "במדינות" in t:
        return "intl" if "1,000" in t or "1000" in t else None
    if "לידות חי" in t:
        return None
    if "אחוז האישורים" in t:
        return "approved"
    if "הריונות ידועים" in t:
        if "לפי" not in t:
            return "ratio"
        if "לפי קבוצת אוכלוסייה" in t:
            return "ratio_grp"
        return None
    if "סעיף החוק" in t and "לפי" in t and "וקבוצת" not in t and "ושבוע" not in t:
        return "grounds"
    if "סעיפי החוק" in t and "וקבוצת אוכלוסייה" in t:
        return "grounds_g"
    if "סעיפי החוק" in t and "שבוע" in t:
        return "grounds_w"
    if "שבוע היריון" in t and "דת" in t:
        return "weeks"
    if "הנשואות והרווקות" in t:
        return "marital"
    if "מצב משפחתי" in t and "קבוצת אוכלוסייה" in t:
        return "marital_g"
    if "השכלה" in t and "שיעורי" in t:
        return "edu"
    if "ילידות" in t:
        return None
    if "שיעורי הפניות" in t and "לפי דת" in t:
        return "religion"
    if "שיעורי הפניות" in t and "לפי גיל וקבוצת אוכלוסייה" in t:
        return "age"
    if "שיעור הפניות לוועדות" in t and "לפי" not in t:
        return "trend"
    return None


def _tables(frames):
    """{kind: (rows, title_row_index, title_text)}; the first stem (by number)
    that holds a kind wins."""
    out = {}
    names = sorted((n for n in frames if STEM.fullmatch(n)),
                   key=lambda n: (int(re.sub(r"\D", "", n)), n))
    for n in names:
        df = frames[n]
        if df.empty:
            continue
        rows = cbs.grid(df, n)
        for i, r in enumerate(rows):
            m = next((TITLE.match(c) for c in r if TITLE.match(c)), None)
            if m:
                k = _kind(m.group(1))
                if k and k not in out:
                    out[k] = (rows, i, m.group(1))
                break
    return out


def _is_num(c):
    return cbs.num(c) is not None


def _header(rows, start, name):
    """Index of the first row after `start` with at least two non-empty cells."""
    for i in range(start + 1, len(rows)):
        if sum(1 for c in rows[i] if c) >= 2:
            return i
    raise ValueError(f"{name}: no header row")


def _matrix(rows, start, name, years=False):
    """(columns, [(label, [values])]) of a simple chart-data block.

    Data rows hold a label (a year when `years`, else non-numeric text) in
    the label column and at least one number right of it; the label column
    is the one most such rows use. The header is the nearest row above the
    first data row with a name over a value column; value columns are the
    columns with a header name and a number in some data row."""
    body = rows[start + 1:]

    def is_lab(c):
        return bool(YEAR.match(c)) if years else bool(c) and not _is_num(c)

    cand = [r for r in body if any(is_lab(c) for c in r) and any(_is_num(c) for c in r)]
    lcol = cbs.best_col(cand, lambda c: is_lab(c) and not (years is False and YEAR.match(c)))
    if lcol is None:
        return [], []
    di = [k for k, r in enumerate(body)
          if is_lab(cbs.cell(r, lcol)) and any(_is_num(c) for c in r[lcol + 1:])]
    if not di:
        return [], []
    numeric = {j for k in di for j, c in enumerate(body[k]) if j > lcol and _is_num(c)}
    hdr = None
    for k in range(di[0] - 1, -1, -1):
        if any(cbs.cell(body[k], j) for j in numeric):
            hdr = body[k]
            break
    if hdr is None:
        raise ValueError(f"{name}: no header row")
    cols = [j for j in sorted(numeric) if cbs.cell(hdr, j)]
    out = []
    for k in di:
        r = body[k]
        vals = [cbs.val(r, j) for j in cols]
        if any(v is not None for v in vals):
            out.append((r[lcol], vals))
    return [hdr[j] for j in cols], out


def _col(cols, label, name):
    for k, c in enumerate(cols):
        if label in c:
            return k
    raise ValueError(f"{name}: header label {label!r} not found")


def _title_year(title):
    m = TITLE_YEAR.search(title)
    return int(m.group(1)) if m else None


def _date(v):
    ts = pd.to_datetime(str(v), errors="coerce", format="%Y-%m-%d")
    return "" if pd.isna(ts) else fmt.d_he(ts)


def _r(v, d=1):
    return None if v is None else round(v, d)


def _f(v, d=1):
    return "–" if v is None else fmt.num_he(v, d)


# ── sections ────────────────────────────────────────────────────────────


def _year_series(tab, name, need, optional=()):
    """{year: [values]} for a year-labelled block, with column indexes found
    by the `need` labels (raises when one is gone); an `optional` label that
    is absent gives None values."""
    rows, i, _ = tab
    cols, data = _matrix(rows, i, name, years=True)
    if not data:
        return {}
    idx = [_col(cols, lab, name) for lab in need]
    idx += [next((k for k, c in enumerate(cols) if lab in c), None) for lab in optional]
    by = {}
    for lab, vals in data:
        by[int(lab)] = [None if k is None else vals[k] for k in idx]
    return dict(sorted(by.items()))


def _wide(tab, name):
    """(years, [(label, [values per year])]) for a block whose header row
    holds years and whose rows are categories."""
    rows, i, _ = tab
    cols, data = _matrix(rows, i, name)
    if not data:
        return [], []
    yidx = [(k, int(c)) for k, c in enumerate(cols) if YEAR.match(c)]
    if not yidx:
        raise ValueError(f"{name}: no year columns")
    years = [y for _, y in yidx]
    out = [(cbs.clean(lab).rstrip("*").strip(), [vals[k] for k, _ in yidx]) for lab, vals in data]
    return years, out


def _cats(tab, name):
    rows, i, _ = tab
    return _matrix(rows, i, name)


def _weeks(tab, name):
    """Two-level header: a year row (year on its first column only) above a
    religion row; rows are week bands. → (columns 'group year', rows)."""
    rows, i, _ = tab
    h = _header(rows, i, name)
    yr = rows[h]
    sub = None
    for k in range(h + 1, len(rows)):
        if any(c and not _is_num(c) for c in rows[k]) and not any(_is_num(c) for c in rows[k]):
            sub = k
            break
    if sub is None:
        return [], []
    labels, year = {}, None
    width = max(len(yr), len(rows[sub]))
    for k in range(1, width):
        y = cbs.cell(yr, k)
        if YEAR.match(y):
            year = y
        g = cbs.cell(rows[sub], k)
        if g and year:
            labels[k] = (g, int(year))
    if not labels:
        raise ValueError(f"{name}: no group columns")
    out = []
    for r in rows[sub + 1:]:
        lab = cbs.cell(r, 0)
        if not lab or _is_num(lab):
            continue
        vals = [cbs.val(r, k) for k in labels]
        if any(v is not None for v in vals):
            out.append((lab, vals))
    return [labels[k] for k in labels], out


# ── compute ─────────────────────────────────────────────────────────────


def compute(frames):
    T = _tables(frames)
    if "trend" not in T:
        raise ValueError("trend chart (rate per 1,000 and count by year) not found")
    rel = cbs.latest_release(frames["releases"])

    charts, tables, labels, flags, kpis, ins = {}, {}, {}, {}, {}, {}

    # trend: rate per 1,000 women + count
    tr = _year_series(T["trend"], "trend", ["שיעור"], optional=["מספרים"])
    tr = {y: v for y, v in tr.items() if v[0] is not None or v[1] is not None}
    if not tr:
        raise ValueError("trend: no year rows")
    years = list(tr)
    y0, y1 = years[0], years[-1]
    rate1, cnt1 = tr[y1]
    rate0, cnt0 = tr[y0]
    charts["trend"] = {"x": years, "rate": [_r(tr[y][0], 2) for y in years],
                       "count": [None if tr[y][1] is None else round(tr[y][1]) for y in years]}
    tables["trend"] = [[str(y), _f(tr[y][0], 1), "–" if tr[y][1] is None else fmt.int_he(tr[y][1])]
                       for y in reversed(years)]
    labels["latest_year"] = str(y1)
    labels["span"] = f"{y0}-{y1}"
    if cnt1 is not None:
        kpis["count"] = {"value": round(cnt1), "display": fmt.int_he(cnt1), "tone": "brand"}
    if rate1 is not None:
        kpis["rate"] = {"value": round(rate1, 2), "display": fmt.num_he(rate1, 1), "tone": "brand"}
    prev = years[-2] if len(years) > 1 else None
    if rate0 is not None and rate1 is not None and len(years) >= 5:
        d = rate1 - rate0
        if abs(d) < FLAT_RATE:
            w = f"נותר יציב סביב {_f(rate1)}"
        else:
            w = f"{'ירד' if d < 0 else 'עלה'} מ-{_f(rate0)} בשנת {y0} ל-{_f(rate1)} בשנת {y1}"
        cnt_part = ""
        if cnt0 is not None and cnt1 is not None:
            cnt_part = (f" במספרים מוחלטים נרשמו {fmt.int_he(cnt1)} פניות בשנת {y1}, "
                        f"לעומת {fmt.int_he(cnt0)} בשנת {y0}.")
        ins["trend"] = f"שיעור הפניות לוועדות ל-1,000 נשים {w}.{cnt_part}"
    if prev is not None and cnt1 is not None and tr[prev][1] and "trend" in ins:
        ch = cnt1 / tr[prev][1] - 1
        if abs(ch) >= 0.005:
            ins["trend"] += (f" לעומת {prev} ({fmt.int_he(tr[prev][1])} פניות) נרשמה "
                             f"{'ירידה' if ch < 0 else 'עלייה'} של {fmt.num_he(abs(ch) * 100, 1)}%.")
    labels["trend_aria"] = f"שיעור הפניות ל-1,000 נשים ומספר הפניות לפי שנה, {y0}-{y1}"
    labels["trend_note"] = (f"מספר הפניות לוועדות בכל שנה (עמודות) ושיעורן ל-1,000 נשים (קו), "
                            f"{y0}-{y1}.")

    # approvals
    if "approved" in T:
        ap = _year_series(T["approved"], "approved", ["אישורים"])
        ap = {y: v[0] for y, v in ap.items() if v[0] is not None}
        if ap:
            ay = list(ap)
            charts["approved"] = {"x": ay, "y": [_r(ap[y], 2) for y in ay]}
            tables["approved"] = [[str(y), fmt.num_he(ap[y], 1) + "%"] for y in reversed(ay)]
            flags["approved"] = True
            kpis["approved"] = {"value": round(ap[ay[-1]], 2),
                                "display": fmt.num_he(ap[ay[-1]], 1) + "%", "tone": "brand"}
            labels["approved_year"] = str(ay[-1])
            labels["approved_aria"] = f"אחוז הפניות שאושרו לפי שנה, {ay[0]}-{ay[-1]}"
            if len(ay) >= 5:
                d = ap[ay[-1]] - ap[ay[0]]
                if abs(d) < FLAT_PP:
                    tail = f", בדומה ל-{fmt.num_he(ap[ay[0]], 1)}% בשנת {ay[0]}"
                else:
                    tail = f" (לעומת {fmt.num_he(ap[ay[0]], 1)}% בשנת {ay[0]})"
                ins["approved"] = (f"הוועדות אישרו {fmt.num_he(ap[ay[-1]], 1)}% מהפניות "
                                   f"בשנת {ay[-1]}{tail}.")

    # per 100 known pregnancies
    if "ratio" in T:
        ra = _year_series(T["ratio"], "ratio", ["100"])
        ra = {y: v[0] for y, v in ra.items() if v[0] is not None}
        if ra:
            ry = list(ra)
            groups = []
            if "ratio_grp" in T:
                gy, gdata = _wide(T["ratio_grp"], "ratio_grp")
                for lab, vals in gdata:
                    m = dict(zip(gy, vals))
                    groups.append({"name": lab, "data": [_r(m.get(y), 2) for y in ry]})
            charts["ratio"] = {"x": ry, "total": [_r(ra[y], 2) for y in ry], "groups": groups}
            gnames = [g["name"] for g in groups]
            labels["ratio_cols"] = ["שנה", "סך הכל"] + gnames
            tables["ratio"] = [[str(y), _f(ra[y])] + [_f(g["data"][k]) for g in groups]
                               for k, y in reversed(list(enumerate(ry)))]
            flags["ratio"] = True
            kpis["ratio"] = {"value": round(ra[ry[-1]], 2), "display": fmt.num_he(ra[ry[-1]], 1),
                             "tone": "brand"}
            labels["ratio_year"] = str(ry[-1])
            labels["ratio_aria"] = f"פניות לוועדות ל-100 הריונות ידועים לפי שנה, {ry[0]}-{ry[-1]}"
            lastg = [(g["name"], g["data"][-1]) for g in groups if g["data"][-1] is not None]
            if len(lastg) >= 2:
                hi = max(lastg, key=lambda t: (t[1], t[0]))
                lo = min(lastg, key=lambda t: (t[1], t[0]))
                ins["ratio"] = (f"בשנת {ry[-1]} נרשמו {fmt.num_he(ra[ry[-1]], 1)} פניות לכל 100 הריונות "
                                f"ידועים. היחס הגבוה ביותר בקבוצת \"{hi[0]}\" ({fmt.num_he(hi[1], 1)}) "
                                f"והנמוך ביותר בקבוצת \"{lo[0]}\" ({fmt.num_he(lo[1], 1)}).")

    # religion
    if "religion" in T:
        ry, rdata = _wide(T["religion"], "religion")
        series = [{"name": lab, "data": [_r(v, 2) for v in vals]} for lab, vals in rdata]
        if series:
            charts["religion"] = {"x": ry, "series": series}
            labels["religion_cols"] = ["שנה"] + [s["name"] for s in series]
            tables["religion"] = [[str(y)] + [_f(s["data"][k]) for s in series]
                                  for k, y in reversed(list(enumerate(ry)))]
            flags["religion"] = True
            labels["religion_aria"] = f"שיעור הפניות ל-1,000 נשים לפי דת, {ry[0]}-{ry[-1]}"
            labels["religion_note"] = (f"שיעור הפניות ל-1,000 נשים בכל קבוצת דת, {ry[0]}-{ry[-1]}. "
                                       "לחיצה על שם בסדרה מסתירה או מציגה אותה.")
            moves = []
            for s in series:
                pts = [(ry[k], v) for k, v in enumerate(s["data"]) if v is not None]
                if len(pts) >= 5 and "סה\"כ" not in s["name"]:
                    moves.append((s["name"], pts[0], pts[-1]))
            if len(moves) >= 2:
                last = sorted(moves, key=lambda t: (-t[2][1], t[0]))
                parts = [f"{n} {fmt.num_he(b[1], 1)}" for n, _, b in last]
                ins["religion"] = (f"בשנת {last[0][2][0]} שיעור הפניות ל-1,000 נשים לפי דת: "
                                   f"{', '.join(parts)}.")

    # age x population group
    if "age" in T:
        cols, data = _cats(T["age"], "age")
        ages = [c for c in cols]
        series = [{"name": lab, "data": [_r(v, 2) for v in vals]} for lab, vals in data]
        if series:
            yr = _title_year(T["age"][2]) or y1
            charts["age"] = {"x": ages, "series": series}
            labels["age_cols"] = ["גיל"] + [s["name"] for s in series]
            tables["age"] = [[a] + [_f(s["data"][k]) for s in series] for k, a in enumerate(ages)]
            flags["age"] = True
            labels["age_year"] = str(yr)
            labels["age_aria"] = f"שיעור הפניות ל-1,000 נשים לפי קבוצת גיל וקבוצת אוכלוסייה, {yr}"
            peaks = []
            for s in series:
                pts = [(ages[k], v) for k, v in enumerate(s["data"]) if v is not None]
                if pts:
                    a, v = max(pts, key=lambda t: t[1])
                    peaks.append(f"בקרב {s['name']} בגילים {fmt.isolate(a)} ({fmt.num_he(v, 1)})")
            if len(peaks) >= 2:
                ins["age"] = (f"בשנת {yr} שיעור הפניות הגבוה ביותר ל-1,000 נשים בכל קבוצה: "
                              f"{fmt.join_he(peaks)}.")

    # marital status
    if "marital" in T:
        ms = _year_series(T["marital"], "marital", ["נשואות", "רווקות"])
        ms = {y: v for y, v in ms.items() if v[0] is not None or v[1] is not None}
        if ms:
            my = list(ms)
            charts["marital"] = {"x": my, "married": [_r(ms[y][0], 2) for y in my],
                                 "single": [_r(ms[y][1], 2) for y in my]}
            tables["marital"] = [[str(y), _f(ms[y][0]) + "%", _f(ms[y][1]) + "%"] for y in reversed(my)]
            flags["marital"] = True
            labels["marital_aria"] = f"אחוז הנשואות והרווקות מבין הפונות לפי שנה, {my[0]}-{my[-1]}"
            a, b = ms[my[-1]]
            if a is not None and b is not None and len(my) >= 5:
                lead = "נשואות" if a > b else "רווקות"
                since = my[-1]
                for y in reversed(my):
                    m0, s0 = ms[y]
                    if m0 is None or s0 is None or (m0 > s0) != (a > b):
                        break
                    since = y
                txt = (f"בשנת {my[-1]} היו {fmt.num_he(a, 1)}% מהפונות נשואות ו-{fmt.num_he(b, 1)}% "
                       f"רווקות (השאר גרושות, אלמנות או במצב משפחתי לא ידוע).")
                if since > my[0]:
                    txt += f" מאז {since} שיעור ה{lead} מבין הפונות גבוה יותר."
                ins["marital"] = txt
    if "marital_g" in T:
        cols, data = _cats(T["marital_g"], "marital_g")
        if data:
            im, isg = _col(cols, "נשואות", "marital_g"), _col(cols, "רווקות", "marital_g")
            charts["marital_g"] = {"x": [lab for lab, _ in data],
                                   "married": [_r(v[im], 2) for _, v in data],
                                   "single": [_r(v[isg], 2) for _, v in data]}
            tables["marital_g"] = [[lab, _f(v[im]) + "%", _f(v[isg]) + "%"] for lab, v in data]
            flags["marital_g"] = True
            labels["marital_g_year"] = str(_title_year(T["marital_g"][2]) or y1)

    # legal grounds
    if "grounds" in T:
        gy, gdata = _wide(T["grounds"], "grounds")
        series = [{"name": lab, "data": [_r(v, 2) for v in vals]} for lab, vals in gdata]
        if series:
            charts["grounds"] = {"x": gy, "series": series}
            labels["grounds_cols"] = ["שנה"] + [s["name"] for s in series]
            tables["grounds"] = [[str(y)] + [_f(s["data"][k]) + "%" for s in series]
                                 for k, y in reversed(list(enumerate(gy)))]
            flags["grounds"] = True
            labels["grounds_aria"] = f"התפלגות האישורים לפי סעיף החוק, באחוזים, {gy[0]}-{gy[-1]}"
            last = [(s["name"], s["data"][-1], s["data"][0]) for s in series if s["data"][-1] is not None]
            if last:
                top = max(last, key=lambda t: (t[1], t[0]))
                txt = (f"בשנת {gy[-1]} {fmt.num_he(top[1], 1)}% מהאישורים ניתנו לפי הסעיף "
                       f"\"{top[0]}\", הסעיף השכיח ביותר")
                if top[2] is not None and len(gy) >= 5 and abs(top[1] - top[2]) >= FLAT_PP:
                    txt += f" (לעומת {fmt.num_he(top[2], 1)}% בשנת {gy[0]})"
                ins["grounds"] = txt + "."
                movers = [(n, v - v0) for n, v, v0 in last if v0 is not None and n != top[0]]
                if movers and len(gy) >= 5:
                    n, d = max(movers, key=lambda t: (abs(t[1]), t[0]))
                    if abs(d) >= 3:
                        v = next(v for nn, v, _ in last if nn == n)
                        v0 = next(v0 for nn, _, v0 in last if nn == n)
                        ins["grounds_move"] = (f"חלקו של הסעיף \"{n}\" באישורים "
                                               f"{'עלה' if d > 0 else 'ירד'} מ-{fmt.num_he(v0, 1)}% "
                                               f"בשנת {gy[0]} ל-{fmt.num_he(v, 1)}% בשנת {gy[-1]}.")
    if "grounds_g" in T:
        cols, data = _cats(T["grounds_g"], "grounds_g")
        if data:
            charts["grounds_g"] = {"x": [lab for lab, _ in data],
                                   "series": [{"name": c, "data": [_r(v[k], 2) for _, v in data]}
                                              for k, c in enumerate(cols)]}
            labels["grounds_g_cols"] = ["קבוצה"] + cols
            tables["grounds_g"] = [[lab] + [_f(x) + "%" for x in v] for lab, v in data]
            flags["grounds_g"] = True
            labels["grounds_g_year"] = str(_title_year(T["grounds_g"][2]) or y1)
    if "grounds_w" in T:
        cols, data = _cats(T["grounds_w"], "grounds_w")
        if data:
            charts["grounds_w"] = {"x": [lab for lab, _ in data],
                                   "series": [{"name": c, "data": [_r(v[k], 2) for _, v in data]}
                                              for k, c in enumerate(cols)]}
            labels["grounds_w_cols"] = ["שבוע היריון"] + cols
            tables["grounds_w"] = [[lab] + [_f(x) + "%" for x in v] for lab, v in data]
            flags["grounds_w"] = True
            yr = _title_year(T["grounds_w"][2]) or y1
            labels["grounds_w_year"] = str(yr)
            labels["grounds_w_aria"] = f"התפלגות האישורים לפי סעיף החוק בכל טווח שבועות היריון, {yr}"
            k = next((k for k, c in enumerate(cols) if "מום" in c), None)
            if k is not None:
                lastrow = data[-1]
                if lastrow[1][k] is not None and lastrow[1][k] >= 50:
                    ins["weeks"] = (f"בשנת {yr}, מבין האישורים בשבועות {fmt.isolate(lastrow[0])} "
                                    f"ניתנו {fmt.num_he(lastrow[1][k], 1)}% לפי הסעיף \"{cols[k]}\". "
                                    f"בשבועות {fmt.isolate(data[0][0])} חלקו {fmt.num_he(data[0][1][k], 1)}%.")
    if "weeks" in T:
        cols, data = _weeks(T["weeks"], "weeks")
        if data:
            x = [f"{g} {y}" for g, y in cols]
            charts["weeks"] = {"x": x, "series": [{"name": lab, "data": [_r(v, 2) for v in vals]}
                                                  for lab, vals in data]}
            labels["weeks_cols"] = ["קבוצה ושנה"] + [lab for lab, _ in data]
            tables["weeks"] = [[x[k]] + [_f(vals[k]) + "%" for _, vals in data] for k in range(len(x))]
            flags["weeks"] = True
            ys = sorted({y for _, y in cols})
            labels["weeks_years"] = fmt.join_he([str(y) for y in ys])

    # education
    if "edu" in T:
        cols, data = _cats(T["edu"], "edu")
        if data:
            charts["edu"] = {"x": [lab for lab, _ in data],
                             "series": [{"name": c, "data": [_r(v[k], 2) for _, v in data]}
                                        for k, c in enumerate(cols) if "שיעור" not in c]}
            keep = [k for k, c in enumerate(cols) if "שיעור" not in c]
            if keep:
                labels["edu_cols"] = ["השכלה"] + [cols[k] for k in keep]
                tables["edu"] = [[lab] + [_f(v[k]) for k in keep] for lab, v in data]
                flags["edu"] = True
                labels["edu_year"] = str(_title_year(T["edu"][2]) or y1)
                ages = re.search(r"בנות\s*(\d+)-(\d+)", T["edu"][2])
                labels["edu_ages"] = (f"בנות {min(ages.groups(), key=int)}-{max(ages.groups(), key=int)}"
                                      if ages else "")

    # international comparison
    if "intl" in T:
        iy, idata = _wide(T["intl"], "intl")
        pts = []
        for lab, vals in idata:
            last = [(iy[k], v) for k, v in enumerate(vals) if v is not None]
            if last:
                pts.append((lab, last[-1][0], last[-1][1]))
        if len(pts) >= 3:
            pts.sort(key=lambda t: (-t[2], t[0]))
            charts["intl"] = {"x": [p[0] for p in pts], "y": [_r(p[2], 2) for p in pts],
                              "years": [p[1] for p in pts]}
            tables["intl"] = [[p[0], fmt.num_he(p[2], 1), str(p[1])] for p in pts]
            flags["intl"] = True
            labels["intl_aria"] = "שיעור הפניות להפסקת היריון ל-1,000 נשים במדינות נבחרות, בשנה האחרונה שפורסמה"
            isr = next((k for k, p in enumerate(pts) if p[0] == "ישראל"), None)
            if isr is not None:
                p = pts[isr]
                hi = sum(1 for q in pts if q[2] > p[2])
                lo = sum(1 for q in pts if q[2] < p[2])
                cmp = [f"נמוך מזה של {hi} ממדינות ההשוואה" if hi else "",
                       (f"גבוה מזה של {lo} מהן" if hi else f"גבוה מזה של {lo} ממדינות ההשוואה") if lo else ""]
                cmp = " ו".join(c for c in cmp if c)
                if cmp:
                    ins["intl"] = (f"השיעור בישראל, {fmt.num_he(p[2], 1)} פניות ל-1,000 נשים בשנת {p[1]}, "
                                   f"{cmp} ({len(pts) - 1} מדינות, לפי השנה האחרונה שפורסמה לכל אחת; "
                                   f"טווחי הגילים שעליהם מחושב השיעור שונים בין המדינות).")

    order = ["trend", "approved", "ratio", "age", "grounds", "grounds_move", "weeks", "intl",
             "marital", "religion"]
    insights = [{"id": k, "text_he": ins[k]} for k in order if k in ins][:8]

    rate_txt = f"{_f(rate1)} ל-1,000 נשים" if rate1 is not None else ""
    if cnt1 is not None:
        head = f"{fmt.int_he(cnt1)} פניות בשנת {y1}" + (f", {rate_txt}" if rate_txt else "")
    else:
        head = f"שיעור הפניות בשנת {y1}: {rate_txt}"
    summary = (f"נתוני הלמ\"ס על פניות לוועדות להפסקת היריון בישראל, {y0}-{y1}: {head}. "
               f"פילוח לפי גיל, דת, מצב משפחתי, סעיף האישור ושבוע ההיריון.")
    desc = (f"פניות לוועדות להפסקת היריון בישראל לפי נתוני הלמ\"ס: {head}. "
            f"מגמה מאז {y0}, לפי גיל, דת וסעיף אישור.")
    labels["lede"] = (f"הלשכה המרכזית לסטטיסטיקה (הלמ\"ס) מפרסמת בכל שנה נתונים על הפניות לוועדות "
                      f"לאישור הפסקת היריון, על סמך טופסי הבקשה שהוועדות מעבירות אליה. {head}. "
                      f"העמוד מציג את המגמה מאז {y0}, את שיעור האישורים ואת הפילוח לפי גיל, "
                      f"קבוצת אוכלוסייה, מצב משפחתי, סעיף החוק ושבוע ההיריון.")

    release = {"title": rel["TITLE"], "date": _date(rel["RELEASE_DATE"]),
               "headline": (rel.get("HEADLINE") or "").strip(), "url": rel["PAGE_URL"],
               "pdf": (rel.get("REPORT_PDF_URL") or "").strip()}

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{y0}/{y1}",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "פניות לוועדות להפסקת היריון: נתונים ומגמות",
                "description": desc,
                "name": "פניות לוועדות להפסקת היריון",
                "alternate_names": ["הפסקות היריון בישראל", "פניות לוועדות להפסקת הריון",
                                    "נתוני הפלות בישראל", "ועדות להפסקת היריון"],
            },
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "labels": labels,
        "flags": flags,
        "insights": insights,
        "release": release,
    }
