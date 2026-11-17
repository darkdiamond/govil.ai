"""מורשים לנהוג בישראל: CBS's yearly release on driving-licence holders.

The release is a set of chart-data sheets ("תרשים N - ..."). Each input
(t1..t9, the last three spare slots, all optional) is read with `cbs.grid`
and each chart is found by its TITLE text, not by its stem, since CBS may
renumber them:

  trend    מורשים לנהוג, כלי רכב מנועיים ואוכלוסייה   thousands, 1995-
  sex      מורשים לנהוג, לפי מין                       thousands, 2005-
  rate     ... אחוז מתוך בני 16 ומעלה                  % licensed by sex/age/group
  vehicle  מספר מורשים לנהוג לכל כלי רכב               holders per vehicle, by type
  work     אחוז בעלי רישיון ... תעסוקה והכנסה          % licensed, ages 25-64 (survey)
  freq     ... לפי תדירות נהיגה                        % by driving frequency (survey)

`trend` is required (every edition has it); a missing other chart drops its
section. A chart whose title is found but whose header labels are gone
raises (the layout changed: a human should look). Values in `trend` and
`sex` are thousands of people.
"""
import re
from itertools import pairwise

import pandas as pd
from govlib import cbs, fmt

TITLE = re.compile(r"^(?:תרשים|לוח)\s*\d+[א-ת]?\s*[-.:]\s*")
HEB = re.compile("[א-ת]")
YEAR_IN = re.compile(r"(?:19|20)\d\d")
PRIORITY = ("growth", "faster", "women", "rate_sex", "rate_age", "work_income", "freq_old",
            "per1000", "rate_pop", "vehicle", "work_emp", "freq_sex", "net")
MAX_TOP = 7


# ── locating tables ──────────────────────────────────────────────────────


def _title(rows):
    for r in rows:
        for c in r:
            if TITLE.match(c):
                return c
    return ""


def _kind(t):
    if "תדירות נהיגה" in t:
        return "freq"
    if "תעסוקה" in t or "הכנסה" in t:
        return "work"
    if "לכל כלי רכב" in t:
        return "vehicle"
    if "אחוז" in t and "גיל" in t:
        return "rate"
    if "כלי רכב" in t and "אוכלוסייה" in t:
        return "trend"
    if "לפי מין" in t:
        return "sex"
    return None


def _tables(frames):
    """{kind: (title, rows)} over every non-empty table input; the lowest
    stem number wins a kind."""
    out = {}
    names = sorted((n for n in frames if re.fullmatch(r"t\d+", n)), key=lambda n: int(n[1:]))
    for n in names:
        df = frames[n]
        if df.empty:
            continue
        rows = cbs.grid(df, n)
        t = _title(rows)
        k = _kind(t)
        if k and k not in out:
            out[k] = (t, rows)
    return out


def _title_year(t):
    ys = YEAR_IN.findall(TITLE.sub("", t))
    return int(ys[-1]) if ys else None


def _r1(v):
    return None if v is None else round(v, 1)


def _p(v):
    return fmt.pct_of(v)


def _hundreds(thousands):
    """A count given in thousands, as people rounded to the hundred (the
    yearly differences mix rounded and exact CBS figures)."""
    return fmt.int_he(round(thousands * 10) * 100)


RANGE = re.compile(r"(\d[\d,]*)\s*[" + "\u2013" + r"-]\s*(\d[\d,]*)")


def _range(label):
    """A numeric range low-high with an ASCII hyphen. CBS writes some
    ranges high-first with an en dash ("7\u20135", read right to left), others
    low-first ("20\u201344"); an en dash between digits renders reversed in
    RTL, a hyphen does not."""
    def fix(m):
        a, b = m.group(1), m.group(2)
        lo, hi = sorted((a, b), key=lambda s: float(s.replace(",", "")))
        return f"{lo}-{hi}"
    return RANGE.sub(fix, label)


# ── readers ──────────────────────────────────────────────────────────────


def _year_series(rows, h, cols):
    """{year: [values per col]} for the year rows below header row h."""
    ycol = cbs.best_col(rows[h + 1:], lambda c: bool(cbs.YEAR.match(c)))
    out = {}
    if ycol is None:
        return out
    for r in rows[h + 1:]:
        c = cbs.cell(r, ycol)
        if not cbs.YEAR.match(c):
            continue
        y = int(c)
        vals = [cbs.val(r, j) for j in cols]
        if y not in out and any(v is not None for v in vals):
            out[y] = vals
    return out


def _grouped(rows, start):
    """[(group, label, [numbers by column index])] for labelled data rows
    after `start`: one or two text cells (group, label) then numbers. The
    group is carried down from the last row that named one."""
    out = []
    group = ""
    for r in rows[start:]:
        texts = [(j, c) for j, c in enumerate(r) if c and cbs.num(c) is None]
        nums = {j: cbs.num(c) for j, c in enumerate(r) if c and cbs.num(c) is not None}
        if not nums or not texts or len(texts) > 2:
            continue
        if any(TITLE.match(c) or c.startswith("(") for _, c in texts):
            continue
        if len(texts) == 2:
            group = _range(texts[0][1])
        label = _range(texts[-1][1])
        out.append((group, label, texts[-1][0], nums))
    return out


def _find(items, group_has, label):
    for g, lb, v in items:
        if group_has in g and lb == label:
            return v
    return None


# ── compute ──────────────────────────────────────────────────────────────


def compute(frames):
    tabs = _tables(frames)
    if "trend" not in tabs:
        raise ValueError("no 'מורשים לנהוג, כלי רכב מנועיים ואוכלוסייה' table in any input")
    rel = cbs.latest_release(frames["releases"])

    kpis, charts, tables, labels, flags, insights = {}, {}, {}, {}, {}, []

    def add(i, text):
        if text:
            insights.append({"id": i, "text_he": text})

    # ── trend: holders, vehicles, population ─────────────────────────────
    _, rows = tabs["trend"]
    h = cbs.row_with(rows, "מורשים לנהוג", name="trend")
    c_hold = cbs.col_after(rows[h], "מורשים לנהוג")
    c_pop = cbs.col_after(rows[h], "אוכלוסייה", contains=True)
    c_veh = cbs.col_after(rows[h], "כלי רכב", contains=True)
    ser = _year_series(rows, h, [c_hold, c_pop, c_veh])
    years = sorted(y for y, v in ser.items() if v[0] is not None)
    if len(years) < 2:
        raise ValueError("trend: fewer than two years of licence holders")
    hold = [ser[y][0] for y in years]
    pop = [ser[y][1] for y in years]
    veh = [ser[y][2] for y in years]
    y0, ly = years[0], years[-1]
    last, prev = hold[-1], hold[-2]
    per1000 = [None if p in (None, 0) else h_ / p * 1000 for h_, p in zip(hold, pop)]
    net = [None] + [None if years[k] - years[k - 1] != 1 else hold[k] - hold[k - 1]
                    for k in range(1, len(years))]

    charts["trend"] = {"x": [str(y) for y in years], "hold": [_r1(v) for v in hold],
                       "pop": [_r1(v) for v in pop], "veh": [_r1(v) for v in veh]}
    tables["trend"] = [[str(y), fmt.int_he(a * 1000),
                        fmt.int_he(b * 1000) if b is not None else "–",
                        fmt.int_he(c * 1000) if c is not None else "–"]
                       for y, a, b, c in reversed(list(zip(years, hold, pop, veh)))]
    charts["ratio"] = {"x": [str(y) for y in years], "per1000": [_r1(v) for v in per1000],
                       "net": [_r1(v) for v in net]}
    tables["ratio"] = [[str(y), fmt.int_he(p) if p is not None else "–",
                        _hundreds(n) if n is not None else "–"]
                       for y, p, n in reversed(list(zip(years, per1000, net)))]

    yoy = last / prev - 1 if prev else None
    kpis["holders"] = {"value": round(last / 1000, 2), "display": fmt.num_he(last / 1000, 2),
                       "tone": "brand"}
    labels["holders_kpi"] = f"מורשים לנהוג בסוף {ly} (מיליונים)"
    if yoy is not None and years[-2] == ly - 1:
        kpis["yoy"] = {"value": round(yoy * 100, 1), "display": fmt.signed_pct(yoy),
                       "tone": "ok" if yoy > 0.0005 else ("danger" if yoy < -0.0005 else "brand")}
        labels["yoy_kpi"] = f"שינוי במספר המורשים לנהוג, {ly} לעומת {ly - 1}"
        if abs(yoy) < 0.0005:
            add("growth", f"בסוף {ly} היו בישראל {fmt.int_he(last * 1000)} מורשים לנהוג, "
                          f"כמעט ללא שינוי לעומת {ly - 1}.")
        else:
            word = "עלייה" if yoy > 0 else "ירידה"
            diff = abs(last - prev) * 1000
            add("growth", f"בסוף {ly} היו בישראל {fmt.int_he(last * 1000)} מורשים לנהוג, {word} של "
                          f"{fmt.pct(abs(yoy))} ({fmt.int_he(diff)} איש) לעומת סוף {ly - 1}.")
    if per1000[-1] is not None:
        kpis["per1000"] = {"value": round(per1000[-1]), "display": fmt.int_he(per1000[-1]),
                           "tone": "brand"}
        labels["per1000_kpi"] = f"מורשים לנהוג לכל 1,000 תושבים ({ly})"
        if per1000[0] is not None and abs(per1000[-1] - per1000[0]) >= 10:
            word = "עלה" if per1000[-1] > per1000[0] else "ירד"
            add("per1000", f"מספר המורשים לנהוג לכל 1,000 תושבים {word} מ-{fmt.int_he(per1000[0])} "
                           f"ב-{y0} ל-{fmt.int_he(per1000[-1])} ב-{ly}. החישוב כולל את כל האוכלוסייה, "
                           f"גם ילדים שאינם בגיל נהיגה.")
    if pop[0] and pop[-1] and ly - y0 >= 5:
        gh, gp = last / hold[0] - 1, pop[-1] / pop[0] - 1
        tail = ""
        if veh[0] and veh[-1]:
            tail = f", ומספר כלי הרכב המנועיים גדל ב-{fmt.pct(veh[-1] / veh[0] - 1, 0)}"
        if gh - gp >= 0.05:
            add("faster", f"מאז {y0} מספר המורשים לנהוג גדל ב-{fmt.pct(gh, 0)}, מהר יותר מהאוכלוסייה, "
                          f"שגדלה ב-{fmt.pct(gp, 0)}{tail}.")
        elif gp - gh >= 0.05:
            add("faster", f"מאז {y0} מספר המורשים לנהוג גדל ב-{fmt.pct(gh, 0)}, לאט יותר מהאוכלוסייה, "
                          f"שגדלה ב-{fmt.pct(gp, 0)}{tail}.")
        else:
            add("faster", f"מאז {y0} מספר המורשים לנהוג והאוכלוסייה גדלו בקצב דומה: "
                          f"{fmt.pct(gh, 0)} ו-{fmt.pct(gp, 0)}{tail}.")
    nets = [(n, y) for n, y in zip(net, years) if n is not None]
    if len(nets) >= 5:
        big = max(nets, key=lambda ny: (ny[0], ny[1]))
        recent = nets[-1]
        add("net", f"בשנת {recent[1]} נוספו {_hundreds(recent[0])} מורשים לנהוג (גידול נטו). "
                   f"הגידול הגדול ביותר בתקופה היה ב-{big[1]}: {_hundreds(big[0])}.")
    labels["trend_note"] = (f"מספר המורשים לנהוג בסוף כל שנה מאז {y0}, לצד מספר כלי הרכב המנועיים "
                            f"והאוכלוסייה הקבועה, באלפים.")
    labels["trend_aria"] = f"מורשים לנהוג, כלי רכב מנועיים ואוכלוסייה, {y0} עד {ly}"
    labels["ratio_note"] = ("מורשים לנהוג לכל 1,000 תושבים (קו), והגידול נטו במספר המורשים בכל שנה "
                            "(עמודות, באלפים).")
    labels["ratio_aria"] = f"מורשים לנהוג לכל 1,000 תושבים וגידול שנתי, {y0} עד {ly}"

    # ── by sex ───────────────────────────────────────────────────────────
    flags["sex"] = False
    if "sex" in tabs:
        _, rows = tabs["sex"]
        h = cbs.row_with(rows, "נשים", name="sex")
        cm, cw = cbs.col_after(rows[h], "גברים"), cbs.col_after(rows[h], "נשים")
        s = _year_series(rows, h, [cm, cw])
        sy = sorted(y for y, v in s.items() if v[0] is not None and v[1] is not None)
        if len(sy) >= 2:
            flags["sex"] = True
            men = [s[y][0] for y in sy]
            wom = [s[y][1] for y in sy]
            share = [w / (m + w) * 100 for m, w in zip(men, wom)]
            charts["sex"] = {"x": [str(y) for y in sy], "men": [_r1(v) for v in men],
                             "women": [_r1(v) for v in wom], "share": [_r1(v) for v in share]}
            tables["sex"] = [[str(y), fmt.int_he(m * 1000), fmt.int_he(w * 1000), _p(sh)]
                             for y, m, w, sh in reversed(list(zip(sy, men, wom, share)))]
            kpis["women"] = {"value": round(share[-1], 1), "display": _p(share[-1]), "tone": "info"}
            labels["women_kpi"] = f"נשים מתוך המורשים לנהוג ({sy[-1]})"
            labels["sex_note"] = f"מורשים לנהוג לפי מין בסוף כל שנה מאז {sy[0]}, באלפים."
            labels["sex_aria"] = f"מורשים לנהוג לפי מין, {sy[0]} עד {sy[-1]}"
            gm, gw = men[-1] / men[0] - 1, wom[-1] / wom[0] - 1
            if share[-1] - share[0] >= 1:
                add("women", f"חלקן של הנשים בין המורשים לנהוג עלה מ-{_p(share[0])} ב-{sy[0]} "
                             f"ל-{_p(share[-1])} ב-{sy[-1]}: מספר הנשים המורשות לנהוג גדל ב-{fmt.pct(gw, 0)}, "
                             f"ומספר הגברים ב-{fmt.pct(gm, 0)}.")
            elif share[0] - share[-1] >= 1:
                add("women", f"חלקן של הנשים בין המורשים לנהוג ירד מ-{_p(share[0])} ב-{sy[0]} "
                             f"ל-{_p(share[-1])} ב-{sy[-1]}.")
            else:
                add("women", f"הנשים הן {_p(share[-1])} מהמורשים לנהוג ב-{sy[-1]}, "
                             f"בדומה ל-{sy[0]} ({_p(share[0])}).")

    # ── % licensed by sex, age, population group ─────────────────────────
    flags["rate"] = False
    if "rate" in tabs:
        r_title, rows = tabs["rate"]
        ry = _title_year(r_title)
        items = [(g, lb, nums[min(nums)]) for g, lb, _, nums in _grouped(rows, 0)]
        if len(items) >= 2:
            flags["rate"] = True
            charts["rate"] = {"names": [lb for _, lb, _ in items], "groups": [g for g, _, _ in items],
                              "values": [_r1(v) for _, _, v in items]}
            tables["rate"] = [[lb, g, _p(v)] for g, lb, v in items]
            yr = f", {ry}" if ry else ""
            labels["rate_note"] = (f"איזה אחוז מבני 16 ומעלה בכל קבוצה מורשים לנהוג{yr}: לפי מין, "
                                   f"קבוצת גיל וקבוצת אוכלוסייה.")
            labels["rate_aria"] = f"אחוז המורשים לנהוג מתוך בני 16 ומעלה, לפי מין, גיל וקבוצת אוכלוסייה{yr}"
            inyr = f" ב-{ry}" if ry else ""
            m, w = _find(items, "מין", "גברים"), _find(items, "מין", "נשים")
            if m is not None and w is not None and abs(m - w) >= 3:
                add("rate_sex", f"{_p(m)} מהגברים בני 16 ומעלה מורשים לנהוג, לעומת {_p(w)} מהנשים{inyr}.")
            ages = [(lb, v) for g, lb, v in items if "גיל" in g]
            if len(ages) >= 3:
                lo = min(ages, key=lambda a: (a[1], a[0]))
                hi = max(ages, key=lambda a: (a[1], a[0]))
                add("rate_age", f"שיעור המורשים לנהוג הגבוה ביותר הוא בגילי {fmt.isolate(hi[0])} "
                                f"({_p(hi[1])}), והנמוך ביותר בגילי {fmt.isolate(lo[0])} ({_p(lo[1])}).")
            pops = [(lb, v) for g, lb, v in items if "אוכלוסייה" in g]
            if len(pops) == 2:
                (a, va), (b, vb) = pops
                gap = abs(va - vb)
                if gap < 3:
                    add("rate_pop", f"שיעור המורשים לנהוג דומה בקרב {a} ({_p(va)}) ובקרב {b} ({_p(vb)}).")
                else:
                    add("rate_pop", f"שיעור המורשים לנהוג בקרב {a} הוא {_p(va)}, ובקרב {b} {_p(vb)}.")

    # ── holders per vehicle, by vehicle type ─────────────────────────────
    flags["vehicle"] = False
    if "vehicle" in tabs:
        v_title, rows = tabs["vehicle"]
        vy = _title_year(v_title)
        h = cbs.row_with(rows, "רכב פרטי", name="vehicle")
        head = rows[h]
        data = next((r for r in rows[h + 1:] if sum(1 for c in r if cbs.num(c) is not None) >= 2), None)
        if data is not None:
            pairs = [(head[j], cbs.val(data, j)) for j in range(len(head))
                     if head[j] and cbs.val(data, j) is not None]
            total = next((v for n, v in pairs if n == "סך כולל"), None)
            types = sorted([(n, v) for n, v in pairs if n != "סך כולל"], key=lambda nv: (-nv[1], nv[0]))
            if len(types) >= 2:
                flags["vehicle"] = True
                charts["vehicle"] = {"names": [n for n, _ in types], "values": [v for _, v in types]}
                tables["vehicle"] = [[n, fmt.num_he(v)] for n, v in types]
                if total is not None:
                    tables["vehicle"].append(["סך כולל", fmt.num_he(total)])
                yr = f", {vy}" if vy else ""
                labels["vehicle_note"] = ("מספר המורשים לנהוג בכל סוג רכב, מחולק במספר כלי הרכב מאותו סוג"
                                          f"{yr}. ככל שהמספר גבוה יותר, יותר נהגים מורשים על כל רכב.")
                labels["vehicle_aria"] = f"מורשים לנהוג לכל כלי רכב, לפי סוג רכב{yr}"
                priv = next((v for n, v in types if n == "רכב פרטי"), None)
                top = types[0]
                tied = [n for n, v in types if v == top[1]]
                if priv is not None and "רכב פרטי" not in tied and top[1] >= priv * 2:
                    add("vehicle", f"על כל רכב פרטי יש בממוצע {fmt.num_he(priv)} מורשים לנהוג ברכב פרטי. "
                                   f"היחס הגבוה ביותר הוא ב{'סוגי הרכב' if len(tied) > 1 else 'סוג הרכב'} "
                                   f"{fmt.join_he(tied)}: {fmt.num_he(top[1])} מורשים לנהוג על כל רכב.")

    # ── % licensed by employment and income (survey) ─────────────────────
    flags["work"] = False
    if "work" in tabs:
        w_title, rows = tabs["work"]
        wy = _title_year(w_title)
        items = [(g, lb, nums[min(nums)]) for g, lb, _, nums in _grouped(rows, 0)]
        if len(items) >= 2:
            flags["work"] = True
            charts["work"] = {"names": [lb for _, lb, _ in items], "groups": [g for g, _, _ in items],
                              "values": [_r1(v) for _, _, v in items]}
            tables["work"] = [[lb, g, _p(v)] for g, lb, v in items]
            yr = f" ({wy})" if wy else ""
            labels["work_note"] = (f"אחוז בעלי רישיון נהיגה בקרב בני 25 עד 64, לפי מצב תעסוקה ולפי הכנסה "
                                   f"חודשית מעבודה{yr}.")
            labels["work_aria"] = f"אחוז בעלי רישיון נהיגה לפי מצב תעסוקה והכנסה מעבודה{yr}"
            inc = [(lb, v) for g, lb, v in items if "הכנסה" in g]
            if len(inc) >= 3 and inc[-1][1] - inc[0][1] >= 5:
                rising = all(b[1] >= a[1] for a, b in pairwise(inc))
                verb = "עולה עם ההכנסה" if rising else "גבוה יותר בהכנסה הגבוהה"
                add("work_income", f"בקרב בני 25 עד 64, שיעור בעלי הרישיון {verb}: "
                                   f"{_p(inc[0][1])} בקבוצת ההכנסה הנמוכה ({fmt.isolate(inc[0][0])} ש\"ח) "
                                   f"לעומת {_p(inc[-1][1])} בגבוהה ({fmt.isolate(inc[-1][0])} ש\"ח).")
            emp = _find(items, "תעסוקה", "מועסקים")
            out = _find(items, "תעסוקה", "אינם בכוח העבודה")
            if emp is not None and out is not None and emp - out >= 5:
                add("work_emp", f"{_p(emp)} מהמועסקים בני 25 עד 64 מחזיקים ברישיון נהיגה, לעומת {_p(out)} "
                                f"ממי שאינם בכוח העבודה.")

    # ── driving frequency (survey) ───────────────────────────────────────
    flags["freq"] = False
    if "freq" in tabs:
        f_title, rows = tabs["freq"]
        fy = _title_year(f_title)
        h = cbs.row_with(rows, "אין רישיון נהיגה", name="freq")
        cats = [(j, _range(c)) for j, c in enumerate(rows[h]) if c]
        items = []
        for g, lb, _, nums in _grouped(rows, h + 1):
            items.append((g, lb, [nums.get(j) for j, _ in cats]))
        if len(items) >= 2:
            flags["freq"] = True
            charts["freq"] = {"names": [lb for _, lb, _ in items], "cats": [c for _, c in cats],
                              "series": [[_r1(v[k]) for _, _, v in items] for k in range(len(cats))]}
            tables["freq"] = [[lb] + [_p(x) if x is not None else "–" for x in v] for _, lb, v in items]
            labels["freq_cols"] = ["קבוצה"] + [c for _, c in cats]
            yr = f", הסקר החברתי {fy}" if fy else ""
            labels["freq_note"] = f"בני 20 ומעלה לפי תדירות הנהיגה, לפי מין וגיל, באחוזים{yr}."
            labels["freq_aria"] = f"תדירות נהיגה לפי מין וגיל{yr}"
            k_none = next(k for k, (_, c) in enumerate(cats) if c == "אין רישיון נהיגה")
            k_daily = 0
            m = _find(items, "מין", "גברים")
            w = _find(items, "מין", "נשים")
            if m and w and m[k_none] is not None and w[k_none] is not None and w[k_none] - m[k_none] >= 3:
                add("freq_sex", f"{_p(w[k_none])} מהנשים בנות 20 ומעלה אינן מחזיקות ברישיון נהיגה, "
                                f"לעומת {_p(m[k_none])} מהגברים. {_p(m[k_daily])} מהגברים ו-{_p(w[k_daily])} "
                                f"מהנשים נוהגים {cats[k_daily][1]}.")
            ages = [(lb, v) for g, lb, v in items if "גיל" in g and v[k_none] is not None]
            if len(ages) >= 3:
                old = ages[-1]
                young = ages[0]
                if old[1][k_none] - young[1][k_none] >= 5:
                    add("freq_old", f"בקרב בני {fmt.isolate(old[0])}, {_p(old[1][k_none])} אינם מחזיקים "
                                    f"ברישיון נהיגה, לעומת {_p(young[1][k_none])} בקרב בני {fmt.isolate(young[0])}.")

    # The insight card holds the strongest findings; the rest show as a
    # callout in their own chart section.
    by_id = {i["id"]: i for i in insights}
    top = [by_id[k] for k in PRIORITY if k in by_id][:MAX_TOP]
    top_ids = {i["id"] for i in top}
    callouts = {i["id"]: i["text_he"] for i in insights if i["id"] not in top_ids}

    release = {"title": rel["TITLE"], "url": rel["PAGE_URL"], "pdf": rel["REPORT_PDF_URL"],
               "date": fmt.d_he(pd.Timestamp(rel["RELEASE_DATE"]))}
    mil = fmt.num_he(last / 1000, 2)
    labels["lede"] = (f"כמה מורשים לנהוג יש בישראל, איך המספר גדל לעומת האוכלוסייה ומספר כלי הרכב, "
                      f"ומי מחזיק ברישיון נהיגה לפי מין, גיל, תעסוקה והכנסה. הנתונים מתוך ההודעה השנתית "
                      f"של הלשכה המרכזית לסטטיסטיקה (הלמ\"ס) ומתעדכנים עם כל הודעה חדשה. בסוף {ly} היו "
                      f"בישראל {mil} מיליון בעלי רישיון נהיגה.")
    summary = (f"בעלי רישיון נהיגה בישראל לפי נתוני הלמ\"ס: {mil} מיליון מורשים לנהוג בסוף {ly}"
               + (f", {_p(kpis['women']['value'])} מהם נשים" if "women" in kpis else "")
               + ". מגמה מאז " + str(y0) + ", ופילוח לפי מין, גיל ותדירות נהיגה.")
    desc = (f"כמה בעלי רישיון נהיגה יש בישראל: {mil} מיליון מורשים לנהוג בסוף {ly}"
            + (f" ({fmt.signed_pct(yoy)} בשנה)" if "yoy" in kpis else "")
            + ". פילוח לפי מין, גיל, הכנסה ותדירות נהיגה.")
    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{y0}/{ly}",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "מורשים לנהוג בישראל: בעלי רישיון נהיגה | הלמ\"ס",
                "description": desc,
                "name": "מורשים לנהוג בישראל",
                "alternate_names": ["בעלי רישיון נהיגה בישראל", "מספר בעלי רישיון נהיגה",
                                    "רישיונות נהיגה בישראל", "נהגים בישראל"],
            },
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": top,
        "callouts": callouts,
        "labels": labels,
        "release": release,
        "flags": flags,
    }
