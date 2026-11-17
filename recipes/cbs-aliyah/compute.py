"""העלייה לישראל: CBS's yearly immigration report ("העלייה לישראל <year>").

Inputs are CBS grid tables from the newest edition (history_releases 1):
  t1   immigrants by period of immigration (1948-1951 ... ) and by year
       since 1990: absolute numbers, percent of all, rate per 1,000 residents
  t2   immigrants by continent and last country of residence, last two years
  t3   immigrants by age group, last two years, plus the median age
  t4   immigrants aged 15+ by marital status, sex and age group (latest year)
  t5   first residence by district, for the leading countries (latest year)
  t6   first locality of residence by leading country (latest year)
  t7   chart 1 data: immigrants and rate per 1,000 residents, every year
       since 1948
  t8..t12  the data of the report's other charts. Their subjects move
       between editions (monthly arrivals, the former USSR since 2000,
       years of schooling, academic occupations, localities), so each is
       classified by its title and header and drawn when recognised.
  releases  the edition list (number, date, headline, link)

Header rows and columns are found by their labels (govlib.cbs) and raise
when missing; data rows (years, countries, localities, age groups) are
found by pattern, so a missing one only shortens a list.
"""
import re

import pandas as pd
from govlib import cbs, fmt

TOTAL_NAMES = ("סך הכל", "סה\"כ", "סך כולל", "סך עולים")
# t2's continent rows, by the English label CBS prints beside them.
CONTINENTS = {"Asia": "אסיה", "Africa": "אפריקה", "Europe": "אירופה",
              "America and Oceania": "אמריקה ואוקיאניה"}
OTHER_EN = "Other countries"
UNKNOWN_EN = "Not known"
RANGE = re.compile(r"^((?:19|20)\d\d)\s*-\s*((?:19|20)\d\d)$")
AGE = re.compile(r"^(\d+)\s*-\s*(\d+)$|^(\d+)\s*\+$|^\+\s*(\d+)$")
SCHOOL = re.compile(r"^(\d+)\s*-+\s*(\d+)$|^(\d+)\s*\+$")
YEAR_HEAD = re.compile(r"^((?:19|20)\d\d)\b")
TOP_COUNTRIES = 12
STACK_N = 3             # stacked district/locality bars: leading countries + the rest
REST = "שאר הארצות"
PER1000 = "לכל 1,000 תושבים"
PER1000_PERIOD = "שיעור שנתי ממוצע לכל 1,000 תושבים"
YOY_FLAT = 0.03          # a change under 3% reads as stable
RISER_MIN = 200          # a country needs this many immigrants to be a riser/faller
CONCENTRATED = 0.4       # a country whose district share reaches 40% "prefers" it


def _int(v):
    return None if v is None else round(v)


def _n(v):
    return fmt.int_he(v)


def _is_total(label):
    return label in TOTAL_NAMES


# ── t1: periods and years since 1990 ─────────────────────────────────────


def _t1(rows):
    h = cbs.row_with(rows, "Absolute numbers", name="t1")
    c_abs = cbs.col_after(rows[h], "Absolute numbers")
    c_pct = cbs.col_after(rows[h], "Percent")
    c_rate = cbs.col_after(rows[h], "Rates", contains=True)
    c_lab = cbs.col_after(rows[h], "Period/Year", contains=True)
    total, periods, years = None, [], []
    for r in rows[h + 1:]:
        lab = cbs.cell(r, c_lab)
        v = cbs.val(r, c_abs)
        if v is None:
            continue
        rec = {"abs": v, "pct": cbs.val(r, c_pct), "rate": cbs.val(r, c_rate)}
        m = RANGE.match(lab)
        if _is_total(lab):
            total = v
        elif m:
            periods.append({"label": f"{m.group(1)}-{m.group(2)}", "start": int(m.group(1)), **rec})
        elif cbs.YEAR.match(lab):
            years.append({"year": int(lab), **rec})
    if total is None:
        raise ValueError("t1: grand-total row not found")
    periods.sort(key=lambda p: p["start"])
    years.sort(key=lambda y: y["year"])
    return total, periods, years


# ── t7: every year since 1948 ────────────────────────────────────────────


def _t7(rows):
    h = cbs.row_with(rows, "מספר עולים", name="t7")
    c_n = cbs.col_after(rows[h], "מספר עולים")
    c_rate = cbs.col_after(rows[h], "שיעור עולים")
    body = rows[h + 1:]
    ycol = cbs.best_col(body, lambda v: bool(cbs.YEAR.match(v)), exclude={c_n, c_rate})
    out = {}
    if ycol is None:
        return []
    for r in body:
        y, v = cbs.cell(r, ycol), cbs.val(r, c_n)
        if cbs.YEAR.match(y) and v is not None:
            out[int(y)] = {"year": int(y), "abs": v, "rate": cbs.val(r, c_rate)}
    return [out[y] for y in sorted(out)]


# ── t2: continents and countries, last two years ─────────────────────────


def _two_year_cols(rows, h, label, name):
    """Columns holding `label` in header row h, and the year printed above
    each (the nearest row above with a year in that column)."""
    cols = [j for j, c in enumerate(rows[h]) if c == label]
    if len(cols) < 2:
        raise ValueError(f"{name}: two {label!r} columns not found")
    years = []
    for j in cols:
        y = None
        for i in range(h - 1, -1, -1):
            if cbs.YEAR.match(cbs.cell(rows[i], j)):
                y = int(cbs.cell(rows[i], j))
                break
        if y is None:
            raise ValueError(f"{name}: no year above column {j}")
        years.append(y)
    pairs = sorted(zip(years, cols))
    return pairs[-2], pairs[-1]


def _t2(rows):
    h = cbs.row_with(rows, "Absolute numbers", name="t2")
    (py, pc), (cy, cc) = _two_year_cols(rows, h, "Absolute numbers", "t2")
    hh = cbs.row_with(rows, "Last country of residence", name="t2")
    c_en = cbs.col_after(rows[hh], "Last country of residence")
    total, continents, countries, unknown = None, [], [], None
    cont = None
    for r in rows[h + 1:]:
        en, he = cbs.cell(r, c_en), cbs.cell(r, 0)
        prev, cur = cbs.val(r, pc), cbs.val(r, cc)
        if prev is None and cur is None:
            continue
        rec = {"prev": prev or 0, "cur": cur or 0}
        if en == "GRAND TOTAL" or _is_total(he):
            total = rec
        elif en in CONTINENTS:
            cont = CONTINENTS[en]
            continents.append({"name": he or cont, **rec})
        elif en == UNKNOWN_EN:
            unknown = rec
            cont = None
        elif cont is not None and he:
            countries.append({"name": he, "continent": cont, "other": en == OTHER_EN, **rec})
    if total is None:
        raise ValueError("t2: grand-total row not found")
    return {"prev_year": py, "year": cy, "total": total, "continents": continents,
            "countries": countries, "unknown": unknown}


# ── t3: age groups ───────────────────────────────────────────────────────


def _age_label(s):
    m = AGE.match(s)
    if not m:
        return None, None
    if m.group(1):
        a, b = sorted((int(m.group(1)), int(m.group(2))))
        return f"{a}-{b}", a
    lo = int(m.group(3) or m.group(4))
    return f"{lo} ומעלה", lo


def _t3(rows):
    h = cbs.row_with(rows, "מספרים מוחלטים", name="t3")
    (py, pc), (cy, cc) = _two_year_cols(rows, h, "מספרים מוחלטים", "t3")
    groups, median, total = [], {}, None
    for r in rows[h + 1:]:
        labels = [c for c in r if c]
        if not labels:
            continue
        en = labels[-1]
        if en == "Median age" or "חציון" in r[0]:
            median = {"prev": cbs.val(r, pc), "cur": cbs.val(r, cc)}
            continue
        prev, cur = cbs.val(r, pc), cbs.val(r, cc)
        if cur is None:
            continue
        if en == "Total" or _is_total(r[0]):
            total = {"prev": prev, "cur": cur}
            continue
        lab, lo = _age_label(en)
        if lab:
            groups.append({"label": lab, "lo": lo, "prev": prev or 0, "cur": cur})
    groups.sort(key=lambda g: g["lo"])
    return {"prev_year": py, "year": cy, "groups": groups, "median": median, "total": total}


# ── t4: marital status by sex and age (15+) ──────────────────────────────

STATUS_M = ["רווקים", "נשואים", "גרושים", "אלמנים"]
STATUS_F = ["רווקות", "נשואות", "גרושות", "אלמנות"]
STATUS_NAMES = ["רווקים", "נשואים", "גרושים", "אלמנים"]


def _t4(rows):
    h = cbs.row_with(rows, "רווקים", name="t4")
    hr = rows[h]
    m_cols = [cbs.col_after(hr, s) for s in STATUS_M]
    f_cols = [cbs.col_after(hr, s) for s in STATUS_F]
    m_tot = cbs.col_after(hr, "סך הכל")
    f_tot = cbs.col_after(hr, "סך הכל", max(m_cols) + 1)
    year = None
    for i in range(h - 1, -1, -1):
        ys = [c for c in rows[i] if cbs.YEAR.match(c)]
        if ys:
            year = int(ys[0])
            break
    start = cbs.row_with(rows, "מספרים מוחלטים", h, name="t4", contains=True)
    try:
        stop = cbs.row_with(rows, "אחוזים", start + 1, name="t4")
    except ValueError:
        stop = len(rows)
    ages, total = [], None
    for r in rows[start + 1:stop]:
        lab = r[0]
        men, women = cbs.val(r, m_tot), cbs.val(r, f_tot)
        if men is None and women is None:
            continue
        rec = {"men": men or 0, "women": women or 0,
               "m": [cbs.val(r, j) or 0 for j in m_cols],
               "f": [cbs.val(r, j) or 0 for j in f_cols]}
        if _is_total(lab):
            total = rec
            continue
        a, lo = _age_label(lab)
        if a:
            ages.append({"label": a, "lo": lo, **rec})
    ages.sort(key=lambda g: g["lo"])
    return {"year": year, "ages": ages, "total": total}


# ── t5: districts ────────────────────────────────────────────────────────


def _t5(rows):
    h = cbs.row_with(rows, "Total", name="t5")
    c_tot = cbs.col_after(rows[h], "Total")
    # The Hebrew district names sit in the nearest row above with "סך הכל"
    # in the same column.
    hh = None
    for i in range(h - 1, -1, -1):
        if _is_total(cbs.cell(rows[i], c_tot)):
            hh = i
            break
    if hh is None:
        raise ValueError("t5: Hebrew district header not found")
    dcols = [j for j in range(c_tot + 1, len(rows[h])) if rows[h][j] and cbs.cell(rows[hh], j)]
    names = [rows[hh][j] for j in dcols]
    if not dcols:
        raise ValueError("t5: no district columns")
    start = cbs.row_with(rows, "מספרים מוחלטים", h, name="t5", contains=True)
    try:
        stop = cbs.row_with(rows, "אחוזים", start + 1, name="t5", contains=True)
    except ValueError:
        stop = len(rows)
    total, countries = None, []
    for r in rows[start + 1:stop]:
        t = cbs.val(r, c_tot)
        if t is None:
            continue
        vals = [cbs.val(r, j) or 0 for j in dcols]
        if _is_total(r[0]):
            total = {"total": t, "vals": vals}
        elif r[0]:
            countries.append({"name": r[0], "total": t, "vals": vals})
    if total is None:
        raise ValueError("t5: total row not found")
    return {"districts": names, "total": total, "countries": countries}


# ── t6: localities ───────────────────────────────────────────────────────


def _t6(rows):
    h = cbs.row_with(rows, "Total", name="t6")
    c_tot = cbs.col_after(rows[h], "Total")
    ccols = [j for j in range(c_tot + 1, len(rows[h])) if re.search(r"[א-ת]", rows[h][j])]
    names = [rows[h][j] for j in ccols]
    total, locs = None, []
    for r in rows[h + 1:]:
        t = cbs.val(r, c_tot)
        if t is None:
            continue
        vals = [cbs.val(r, j) for j in ccols]
        if _is_total(r[0]):
            total = t
        elif r[0] and r[0] != "מזה:":
            locs.append({"name": re.sub(r"\s*-\s*", "-", r[0]), "total": t, "vals": vals})
    locs.sort(key=lambda x: (-x["total"], x["name"]))
    return {"countries": names, "total": total, "locs": locs}


# ── t8..t12: the report's other charts, classified by content ────────────


def _title(rows):
    for r in rows[:8]:
        for c in r:
            if "תרשים" in c:
                return c
    return ""


def _monthly(rows):
    """{year: {month: n}}, provisional years, or None when this is not a
    month-by-year table (months down, one column a year)."""
    for i, r in enumerate(rows):
        if "חודש עלייה" not in r:
            continue
        lab = r.index("חודש עלייה")
        ycols = [(j, int(YEAR_HEAD.match(c).group(1)), "ארעי" in c)
                 for j, c in enumerate(r) if j != lab and YEAR_HEAD.match(c)]
        if len(ycols) < 2:
            continue
        data = {y: {} for _, y, _ in ycols}
        for rr in rows[i + 1:]:
            m = cbs.cell(rr, lab)
            if not re.fullmatch(r"\d{1,2}", m) or not 1 <= int(m) <= 12:
                continue
            for j, y, _ in ycols:
                v = cbs.val(rr, j)
                if v is not None:
                    data[y][int(m)] = v
        prov = sorted(y for _, y, p in ycols if p)
        data = {y: d for y, d in data.items() if d}
        return (data, prov) if len(data) >= 2 else None
    return None


def _fsu(rows):
    """[{year, total, series...}] for a by-year table of all immigrants and
    the former USSR / its countries, or None."""
    for i, r in enumerate(rows):
        if "סך עולים" not in r or not any("בריה" in c for c in r):
            continue
        c_tot = r.index("סך עולים")
        cols = [(j, c) for j, c in enumerate(r) if j > c_tot and c]
        out = []
        for k, year, month, _ in cbs.periods(rows, i + 1, len(rows)):
            if month is not None:
                continue
            rr = rows[k]
            t = cbs.val(rr, c_tot)
            if t is None:
                continue
            out.append({"year": year, "total": t, "vals": [cbs.val(rr, j) for j, _ in cols]})
        out.sort(key=lambda x: x["year"])
        return ({"names": [c for _, c in cols], "rows": out}) if len(out) >= 3 else None
    return None


def _label_values(rows, head_pred, label_pred):
    for i, r in enumerate(rows):
        if not any(head_pred(c) for c in r):
            continue
        out = []
        for rr in rows[i + 1:]:
            cells = [c for c in rr if c]
            if len(cells) != 2:
                continue
            lab, v = cells[0], cbs.num(cells[1])
            if v is None or not label_pred(lab):
                continue
            out.append((lab, v))
        return out or None
    return None


def _education(rows):
    # Older editions print no "שנות לימוד" header, only the title row.
    got = _label_values(rows, lambda c: "שנות לימוד" in c, lambda s: bool(SCHOOL.match(s)))
    if not got:
        return None
    out = []
    for lab, v in got:
        m = SCHOOL.match(lab)
        if m.group(1):
            a, b = sorted((int(m.group(1)), int(m.group(2))))
            out.append({"label": f"{a}-{b}", "lo": a, "n": v})
        else:
            out.append({"label": f"{m.group(3)} ומעלה", "lo": int(m.group(3)), "n": v})
    out.sort(key=lambda x: x["lo"])
    return out


def _occupations(rows):
    got = _label_values(rows, lambda c: "משלח יד אקדמי" in c or c == "תחומי העיסוק",
                        lambda s: bool(re.search(r"[א-ת]", s)) and "תרשים" not in s)
    if not got:
        return None
    out = [{"label": lab, "n": v} for lab, v in got]
    out.sort(key=lambda x: (-x["n"], x["label"]))
    return out


def _extras(frames):
    found = {}
    for k in ("t8", "t9", "t10", "t11", "t12"):
        df = frames.get(k)
        if df is None or df.empty:
            continue
        rows = cbs.grid(df, k)
        title = _title(rows)
        if "monthly" not in found and "חודש עלייה" in title:
            got = _monthly(rows)
            if got:
                found["monthly"] = got
                continue
        if "fsu" not in found and "בריה" in title:
            got = _fsu(rows)
            if got:
                found["fsu"] = got
                continue
        if "education" not in found and "שנות לימוד" in title:
            got = _education(rows)
            if got:
                found["education"] = got
                continue
        if "occupations" not in found and "משלח יד אקדמי" in title:
            got = _occupations(rows)
            if got:
                found["occupations"] = got
    return found


# ── insights ─────────────────────────────────────────────────────────────


def _change_txt(ch):
    """'גידול של 12.5%', 'גידול של פי 2.9' (at least a doubling), 'ירידה של 40.0%'.
    "גידול", not "עלייה": on this page עלייה means immigration."""
    if ch >= 1:
        return f"גידול של פי {fmt.num_he(ch + 1)}"
    return f"{'גידול' if ch > 0 else 'ירידה'} של {fmt.pct(abs(ch))}"


def _change_word(ch):
    if abs(ch) < YOY_FLAT:
        return None
    return "גידול" if ch > 0 else "ירידה"


def _ins_yoy(years):
    if len(years) < 2:
        return None
    a, b = years[-2], years[-1]
    if not a["abs"]:
        return None
    ch = b["abs"] / a["abs"] - 1
    word = _change_word(ch)
    if word is None:
        return (f"בשנת {b['year']} עלו לישראל {_n(b['abs'])} עולים, כמעט כמו בשנת "
                f"{a['year']} ({_n(a['abs'])}).")
    return (f"בשנת {b['year']} עלו לישראל {_n(b['abs'])} עולים, {_change_txt(ch)} "
            f"לעומת {a['year']} ({_n(a['abs'])}).")


def _ins_decade(years):
    """The latest year against the average of the ten years before it."""
    if len(years) < 11:
        return None
    last = years[-1]
    base = years[-11:-1]
    avg = sum(y["abs"] for y in base) / len(base)
    ch = last["abs"] / avg - 1
    if abs(ch) < 0.1:
        return (f"מספר העולים בשנת {last['year']} קרוב לממוצע של עשר השנים שקדמו לה "
                f"({base[0]['year']}-{base[-1]['year']}): כ-{_n(avg)} עולים בשנה.")
    if ch >= 1:
        how = f"גבוה פי {fmt.num_he(ch + 1)}"
    else:
        how = f"{'גבוה' if ch > 0 else 'נמוך'} ב-{fmt.pct(abs(ch))}"
    return (f"מספר העולים בשנת {last['year']} {how} מהממוצע של עשר "
            f"השנים שקדמו לה ({base[0]['year']}-{base[-1]['year']}), כ-{_n(avg)} עולים בשנה.")


def _ins_period(total, periods, first_year):
    if not periods or not total:
        return None
    big = max(periods, key=lambda p: (p["abs"], -p["start"]))
    share = big["abs"] / total
    return (f"התקופה שבה עלו הכי הרבה עולים היא {big['label']}: {_n(big['abs'])} עולים, "
            f"{fmt.pct(share)} מכל {_n(total)} העולים מאז {first_year}.")



def _ins_leader(t2):
    named = sorted((c for c in t2["countries"] if not c["other"]),
                   key=lambda c: (-c["cur"], c["name"]))
    tot = t2["total"]["cur"]
    if len(named) < 3 or not tot:
        return None
    a, b, c = named[:3]
    share = a["cur"] / tot
    if share < 0.2:
        return None
    return (f"{a['name']} היא ארץ המגורים האחרונה של רוב העולים בשנת {t2['year']}: "
            f"{_n(a['cur'])} עולים ({fmt.pct(share)}). אחריה {b['name']} ({_n(b['cur'])}) "
            f"ו{c['name']} ({_n(c['cur'])}).") if share >= 0.5 else (
            f"{a['name']} היא ארץ המגורים האחרונה הנפוצה ביותר בקרב העולים בשנת {t2['year']}: "
            f"{_n(a['cur'])} עולים ({fmt.pct(share)}). אחריה {b['name']} ({_n(b['cur'])}) "
            f"ו{c['name']} ({_n(c['cur'])}).")


def _ins_movers(t2):
    named = [c for c in t2["countries"] if not c["other"] and c["prev"] > 0
             and max(c["prev"], c["cur"]) >= RISER_MIN]
    if not named:
        return None
    up = max(named, key=lambda c: (c["cur"] - c["prev"], c["name"]))
    down = min(named, key=lambda c: (c["cur"] - c["prev"], c["name"]))
    parts = []
    if up["cur"] - up["prev"] > 0 and up["cur"] / up["prev"] - 1 >= 0.2:
        r = up["cur"] / up["prev"]
        how = f"פי {fmt.num_he(r)}" if r >= 2 else fmt.signed_pct(r - 1)
        parts.append(f"הגידול הגדול ביותר במספר העולים נרשם מ{up['name']}: {_n(up['cur'])} "
                     f"עולים בשנת {t2['year']} לעומת {_n(up['prev'])} בשנת {t2['prev_year']} "
                     f"({how})")
    if down["cur"] - down["prev"] < 0 and 1 - down["cur"] / down["prev"] >= 0.2:
        parts.append(f"הירידה הגדולה ביותר נרשמה בעולים מ{down['name']}: {_n(down['cur'])} לעומת "
                     f"{_n(down['prev'])} ({fmt.signed_pct(down['cur'] / down['prev'] - 1)})")
    if not parts:
        return None
    return ". ".join(parts) + "."



def _ins_women(t4):
    t = t4["total"]
    if not t or not (t["men"] + t["women"]):
        return None
    share = t["women"] / (t["men"] + t["women"])
    widow_f, widow_m = t["f"][3], t["m"][3]
    s = (f"בקרב העולים בני 15 ומעלה בשנת {t4['year']}, {fmt.pct(share)} הן נשים "
         f"({_n(t['women'])} נשים ו-{_n(t['men'])} גברים)")
    if widow_m and widow_f >= 2 * widow_m:
        s += (f". האלמנות רבות פי {fmt.num_he(widow_f / widow_m)} מהאלמנים "
              f"({_n(widow_f)} לעומת {_n(widow_m)})")
    return s + "."


def _district(name):
    """'מחוז ירושלים', but 'אזור יהודה והשומרון' as printed."""
    return name if name.startswith(("אזור", "מחוז")) else f"מחוז {name}"


def _ins_district(t5, year):
    best = None
    for c in t5["countries"]:
        if not c["total"] or c["total"] < RISER_MIN:
            continue
        k = max(range(len(c["vals"])), key=lambda j: (c["vals"][j], -j))
        share = c["vals"][k] / c["total"]
        if share >= CONCENTRATED and (best is None or share > best[2]):
            best = (c, k, share)
    tot = t5["total"]
    k0 = max(range(len(tot["vals"])), key=lambda j: (tot["vals"][j], -j))
    s = (f"{_district(t5['districts'][k0])} קלט את מספר העולים הגדול ביותר בשנת {year}: "
         f"{_n(tot['vals'][k0])} ({fmt.pct(tot['vals'][k0] / tot['total'])})")
    if best:
        c, k, share = best
        s += (f". עולי {c['name']} מרוכזים במיוחד: {fmt.pct(share)} מהם השתקעו ב"
              f"{_district(t5['districts'][k])}")
    return s + "."



def _ins_monthly(monthly):
    data, prov = monthly
    ys = sorted(data)
    y = ys[-1]
    prev = ys[-2]
    months = sorted(data[y])
    if len(months) >= 12 or not months:
        return None
    if any(m not in data[prev] for m in months):
        return None
    cur = sum(data[y][m] for m in months)
    old = sum(data[prev][m] for m in months)
    if not old:
        return None
    span = (fmt.MONTHS_HE[months[0] - 1] if len(months) == 1 else
            f"{fmt.MONTHS_HE[months[0] - 1]} עד {fmt.MONTHS_HE[months[-1] - 1]}")
    ch = cur / old - 1
    word = _change_word(ch)
    note = " (נתונים ארעיים)" if y in prov else ""
    trend = (f"כמעט כמו באותם חודשים בשנת {prev} ({_n(old)})" if word is None else
             f"{_change_txt(ch)} לעומת אותם חודשים בשנת {prev} ({_n(old)})")
    return f"בחודשים {span} {y}{note} עלו {_n(cur)} עולים, {trend}."


def _ins_fsu(fsu, year):
    rows = [r for r in fsu["rows"] if r["year"] == year]
    if not rows or not fsu["names"]:
        return None
    r = rows[0]
    v = r["vals"][0]
    if v is None or not r["total"]:
        return None
    share = v / r["total"]
    first = fsu["rows"][0]
    s = (f"{fmt.pct(share)} מהעולים בשנת {year} הגיעו מ{fsu['names'][0]}: "
         f"{_n(v)} עולים")
    if first["vals"][0] is not None and first["total"] and first["year"] < year:
        s += f", לעומת {fmt.pct(first['vals'][0] / first['total'])} בשנת {first['year']}"
    return s + "."



# ── model ────────────────────────────────────────────────────────────────


def compute(frames):
    total, periods, years = _t1(cbs.grid(frames["t1"], "t1"))
    series = _t7(cbs.grid(frames["t7"], "t7"))
    t2 = _t2(cbs.grid(frames["t2"], "t2"))
    t3 = _t3(cbs.grid(frames["t3"], "t3"))
    t4 = _t4(cbs.grid(frames["t4"], "t4"))
    t5 = _t5(cbs.grid(frames["t5"], "t5"))
    t6 = _t6(cbs.grid(frames["t6"], "t6"))
    ex = _extras(frames)
    rel = cbs.latest_release(frames["releases"])

    if not years:
        raise ValueError("t1: no yearly rows")
    last = years[-1]
    ly = last["year"]
    prev = years[-2] if len(years) >= 2 else None
    first_year = periods[0]["start"] if periods else (series[0]["year"] if series else ly)

    # ── KPIs
    kpis = {"latest": {"value": _int(last["abs"]), "display": _n(last["abs"]), "tone": "brand"}}
    labels = {"latest_kpi": f"עולים בשנת {ly}"}
    if prev and prev["abs"]:
        ch = last["abs"] / prev["abs"] - 1
        tone = "brand" if abs(ch) < YOY_FLAT else ("ok" if ch > 0 else "warn")
        kpis["yoy"] = {"value": round(ch * 100, 1), "display": fmt.signed_pct(ch), "tone": tone}
        labels["yoy_kpi"] = f"שינוי לעומת {prev['year']}"
    if last["rate"] is not None:
        kpis["rate"] = {"value": round(last["rate"], 1), "display": fmt.num_he(last["rate"]),
                        "tone": "info"}
        labels["rate_kpi"] = f"עולים לכל 1,000 תושבים ({ly})"
    kpis["total"] = {"value": _int(total), "display": _n(total), "tone": "brand"}
    labels["total_kpi"] = f"סך העולים מאז {first_year}"
    named = sorted((c for c in t2["countries"] if not c["other"]),
                   key=lambda c: (-c["cur"], c["name"]))
    if named and t2["total"]["cur"]:
        lead = named[0]
        kpis["lead"] = {"value": round(lead["cur"] / t2["total"]["cur"] * 100, 1),
                        "display": fmt.pct(lead["cur"] / t2["total"]["cur"]), "tone": "brand"}
        labels["lead_kpi"] = f"מהעולים הגיעו מ{lead['name']} ({t2['year']})"
    if t3["median"].get("cur") is not None:
        kpis["median"] = {"value": t3["median"]["cur"], "display": fmt.num_he(t3["median"]["cur"]),
                          "tone": "brand"}
        labels["median_kpi"] = f"חציון גיל העולים ({t3['year']})"

    charts, tables = {}, {}
    flags = dict.fromkeys(("years", "periods", "fsu", "months", "age", "t4", "localities",
                           "education", "occupations"), False)
    labels["per1000"] = PER1000
    labels["per1000_period"] = PER1000_PERIOD
    labels["rate_about"] = ("שיעור העולים הוא מספר העולים לכל 1,000 תושבים באוכלוסייה הממוצעת "
                            "של ישראל באותה שנה.")

    # ── long series
    if series:
        charts["years"] = {"x": [str(s["year"]) for s in series],
                           "n": [_int(s["abs"]) for s in series],
                           "rate": [s["rate"] for s in series], "per": PER1000}
        tables["years"] = [[str(s["year"]), _n(s["abs"]),
                            fmt.num_he(s["rate"]) if s["rate"] is not None else "–"]
                           for s in reversed(series)]
        peak = max(series, key=lambda y: (y["abs"], -y["year"]))
        labels["years_note"] = (
            f"מספר העולים בכל שנה מאז {series[0]['year']} (עמודות) ושיעור העולים לכל 1,000 "
            f"תושבים בישראל (קו). השיא: {_n(peak['abs'])} עולים בשנת {peak['year']}. "
            f"גררו את הפס שמתחת לתרשים כדי להתמקד בתקופה.")
        labels["years_aria"] = f"עולים לישראל בכל שנה, {series[0]['year']} עד {series[-1]['year']}"
        flags["years"] = True

    # ── periods
    if periods:
        charts["periods"] = {"x": [p["label"] for p in periods],
                             "n": [_int(p["abs"]) for p in periods],
                             "rate": [p["rate"] for p in periods], "per": PER1000_PERIOD}
        tables["periods"] = [[p["label"], _n(p["abs"]),
                              fmt.pct(p["abs"] / total) if total else "–",
                              fmt.num_he(p["rate"]) if p["rate"] is not None else "–"]
                             for p in periods]
        labels["periods_note"] = (
            "סך העולים בכל תקופת עלייה, כפי שהלמ\"ס מקבצת אותן. התקופות אינן שוות באורכן, "
            "ולכן השיעור השנתי הממוצע לכל 1,000 תושבים (בריחוף ובטבלה) עוזר להשוות ביניהן.")
        labels["periods_aria"] = f"עולים לפי תקופת עלייה, {periods[0]['label']} עד {periods[-1]['label']}"
        flags["periods"] = True

    # ── continents
    py, cy = t2["prev_year"], t2["year"]
    conts = sorted(t2["continents"], key=lambda c: (-c["cur"], c["name"]))
    if t2["unknown"]:
        conts = conts + [{"name": "לא ידוע", **t2["unknown"]}]
    charts["continents"] = {"x": [c["name"] for c in conts], "prev": [_int(c["prev"]) for c in conts],
                            "cur": [_int(c["cur"]) for c in conts], "years": [str(py), str(cy)]}
    tables["continents"] = [[c["name"], _n(c["prev"]), _n(c["cur"]),
                             fmt.pct(c["cur"] / t2["total"]["cur"]) if t2["total"]["cur"] else "–"]
                            for c in conts]
    labels["years_pair"] = [str(py), str(cy)]
    labels["continents_note"] = (f"עולים לפי יבשת של ארץ המגורים האחרונה, {py} מול {cy}.")
    labels["continents_aria"] = f"עולים לפי יבשת, {py} ו-{cy}"

    # ── countries
    top = named[:TOP_COUNTRIES]
    charts["countries"] = {"x": [c["name"] for c in top], "prev": [_int(c["prev"]) for c in top],
                           "cur": [_int(c["cur"]) for c in top], "years": [str(py), str(cy)]}
    tables["countries"] = [[c["name"], _n(c["prev"]), _n(c["cur"]),
                            fmt.signed_pct(c["cur"] / c["prev"] - 1) if c["prev"] else "–"]
                           for c in top]
    labels["countries_note"] = (
        f"{len(top)} הארצות שמהן עלו הכי הרבה עולים בשנת {cy}, לפי ארץ המגורים האחרונה, "
        f"לצד מספרם בשנת {py}. הלמ\"ס מפרטת ארץ רק כשעלו ממנה לפחות 10 עולים.")
    labels["countries_aria"] = f"עולים לפי ארץ מגורים אחרונה, {py} ו-{cy}"

    # ── FSU (optional chart table)
    fsu = ex.get("fsu")
    if fsu:
        charts["fsu"] = {"x": [str(r["year"]) for r in fsu["rows"]],
                         "total": [_int(r["total"]) for r in fsu["rows"]],
                         "names": fsu["names"],
                         "series": [[_int(r["vals"][k]) for r in fsu["rows"]]
                                    for k in range(len(fsu["names"]))]}
        tables["fsu"] = [[str(r["year"]), _n(r["total"])] +
                         [_n(v) if v is not None else "–" for v in r["vals"]]
                         for r in reversed(fsu["rows"])]
        labels["fsu_cols"] = ["שנה", "סך עולים"] + fsu["names"]
        labels["fsu_note"] = (f"סך העולים בכל שנה מאז {fsu['rows'][0]['year']}, ומתוכם העולים מ"
                              f"{fmt.join_he(fsu['names'])}.")
        labels["fsu_aria"] = f"עולים מ{fsu['names'][0]}, {fsu['rows'][0]['year']} עד {fsu['rows'][-1]['year']}"
        flags["fsu"] = True

    # ── monthly (optional chart table)
    monthly = ex.get("monthly")
    if monthly:
        data, prov = monthly
        ys = sorted(data)
        names = [f"{y} (ארעי)" if y in prov else str(y) for y in ys]
        charts["months"] = {"x": fmt.MONTHS_SHORT_HE, "years": names,
                            "series": [[_int(data[y].get(m)) if m in data[y] else None
                                        for m in range(1, 13)] for y in ys]}
        tables["months"] = [[fmt.MONTHS_HE[m - 1]] +
                            [_n(data[y][m]) if m in data[y] else "–" for y in ys]
                            for m in range(1, 13)]
        labels["months_cols"] = ["חודש"] + names
        labels["months_note"] = (f"מספר העולים בכל חודש, {ys[0]} עד {ys[-1]}. "
                                 + ("נתוני השנה האחרונה ארעיים וחלקיים." if prov else ""))
        labels["months_aria"] = f"עולים לפי חודש עלייה, {ys[0]} עד {ys[-1]}"
        flags["months"] = True

    # ── age
    if t3["groups"]:
        tot3 = t3["total"] or {}
        charts["age"] = {"x": [g["label"] for g in t3["groups"]],
                         "prev": [_int(g["prev"]) for g in t3["groups"]],
                         "cur": [_int(g["cur"]) for g in t3["groups"]],
                         "years": [str(t3["prev_year"]), str(t3["year"])]}
        tables["age"] = [[g["label"], _n(g["prev"]), _n(g["cur"]),
                          fmt.pct(g["cur"] / tot3["cur"]) if tot3.get("cur") else "–"]
                         for g in t3["groups"]]
        if t3["median"].get("cur") is not None:
            tables["age"].append(["חציון הגיל",
                                  fmt.num_he(t3["median"]["prev"]) if t3["median"].get("prev") is not None else "–",
                                  fmt.num_he(t3["median"]["cur"]), "–"])
        labels["age_years"] = [str(t3["prev_year"]), str(t3["year"])]
        labels["age_note"] = f"עולים לפי קבוצת גיל, {t3['prev_year']} מול {t3['year']}."
        labels["age_aria"] = f"עולים לפי קבוצת גיל, {t3['prev_year']} ו-{t3['year']}"
        flags["age"] = True

    # ── pyramid + marital status (t4)
    if t4["ages"]:
        ages = t4["ages"]
        charts["pyramid"] = {"x": [a["label"] for a in ages],
                             "men": [_int(a["men"]) for a in ages],
                             "women": [_int(a["women"]) for a in ages]}
        tables["pyramid"] = [[a["label"], _n(a["men"]), _n(a["women"])] for a in ages]
        labels["pyramid_note"] = (f"העולים בני 15 ומעלה בשנת {t4['year']} לפי מין וקבוצת גיל: "
                                  "גברים משמאל, נשים מימין.")
        labels["pyramid_aria"] = f"עולים בני 15 ומעלה לפי מין וגיל, {t4['year']}"

        def _shares(a):
            both = [a["m"][k] + a["f"][k] for k in range(4)]
            s = sum(both)
            return [round(v / s * 100, 1) if s else 0 for v in both]

        sh = [_shares(a) for a in ages]
        charts["marital"] = {"x": [a["label"] for a in ages], "names": STATUS_NAMES,
                             "series": [[sh[i][k] for i in range(len(ages))] for k in range(4)]}
        tables["marital"] = [[a["label"]] + [fmt.pct_of(v) for v in sh[i]]
                             for i, a in enumerate(ages)]
        labels["marital_note"] = (f"התפלגות המצב המשפחתי בכל קבוצת גיל, גברים ונשים יחד, "
                                  f"בשנת {t4['year']}.")
        labels["marital_aria"] = f"עולים בני 15 ומעלה לפי מצב משפחתי וגיל, {t4['year']}"
        flags["t4"] = True

    # ── districts (stacks: the STACK_N leading countries + the rest)
    dn = t5["districts"]
    tc5 = sorted(t5["countries"], key=lambda c: (-c["total"], c["name"]))[:STACK_N]
    order = sorted(range(len(dn)), key=lambda j: (-t5["total"]["vals"][j], j))
    d_series = [{"name": c["name"], "data": [_int(c["vals"][j]) for j in order]} for c in tc5]
    other = [max(t5["total"]["vals"][j] - sum(c["vals"][j] for c in tc5), 0) for j in order]
    d_series.append({"name": REST, "data": [_int(v) for v in other]})
    charts["districts"] = {"x": [dn[j] for j in order], "series": d_series}
    tables["districts"] = [[dn[j], _n(t5["total"]["vals"][j]),
                            fmt.pct(t5["total"]["vals"][j] / t5["total"]["total"]) if t5["total"]["total"] else "–"]
                           + [_n(sr["data"][i]) for sr in d_series]
                           for i, j in enumerate(order)]
    labels["districts_cols"] = ["מחוז", "עולים", "חלק מהעולים"] + [sr["name"] for sr in d_series]
    labels["districts_note"] = (f"מחוז ההשתקעות הראשונה של העולים בשנת {cy}, ולכל מחוז הפירוט לפי "
                                f"{len(tc5)} ארצות המגורים האחרונות הגדולות.")
    labels["districts_aria"] = f"עולים לפי מחוז השתקעות ראשונה, {cy}"

    # ── localities
    locs = t6["locs"]
    flags["localities"] = bool(locs)
    if locs:
        ks = sorted(range(len(t6["countries"])),
                    key=lambda k: (-sum(x["vals"][k] or 0 for x in locs), k))[:STACK_N]
        l_series = [{"name": t6["countries"][k], "data": [_int(x["vals"][k] or 0) for x in locs]}
                    for k in ks]
        rest = [max(x["total"] - sum(x["vals"][k] or 0 for k in ks), 0) for x in locs]
        l_series.append({"name": REST, "data": [_int(v) for v in rest]})
        charts["localities"] = {"x": [x["name"] for x in locs], "series": l_series}
        tables["localities"] = [[x["name"], _n(x["total"])] +
                                [_n(v) if v is not None else "–" for v in x["vals"]]
                                for x in locs]
        labels["localities_cols"] = ["יישוב", "סך העולים"] + t6["countries"]
        labels["localities_note"] = (
            f"היישובים העיקריים שבהם השתקעו העולים בשנת {cy}, לפי ארץ המגורים האחרונה. "
            "תאים שהלמ\"ס לא פרסמה נכללים בשאר הארצות. הטבלה מפרטת את כל הארצות שבלוח.")
        labels["localities_aria"] = f"עולים לפי יישוב מגורים ראשון, {cy}"

    edu = ex.get("education")
    if edu:
        tot_e = sum(x["n"] for x in edu)
        charts["education"] = {"x": [x["label"] for x in edu], "n": [_int(x["n"]) for x in edu]}
        tables["education"] = [[x["label"], _n(x["n"]), fmt.pct(x["n"] / tot_e) if tot_e else "–"]
                               for x in edu]
        labels["education_note"] = "עולים בני 15 ומעלה לפי מספר שנות הלימוד שלמדו בחוץ לארץ."
        labels["education_aria"] = "עולים בני 15 ומעלה לפי שנות לימוד"
        flags["education"] = True
    occ = ex.get("occupations")
    if occ:
        tot_o = sum(x["n"] for x in occ)
        charts["occupations"] = {"x": [x["label"] for x in occ], "n": [_int(x["n"]) for x in occ]}
        tables["occupations"] = [[x["label"], _n(x["n"]), fmt.pct(x["n"] / tot_o) if tot_o else "–"]
                                 for x in occ]
        labels["occupations_note"] = ("עולים בני 15 ומעלה בעלי משלח יד אקדמי, לפי תחום העיסוק "
                                      "שבו עבדו לפני העלייה.")
        labels["occupations_aria"] = "עולים בעלי משלח יד אקדמי לפי תחום עיסוק"
        flags["occupations"] = True

    # ── insights (each None when its premise fails)
    ins = [
        ("yoy", _ins_yoy(years)),
        ("monthly", _ins_monthly(monthly) if monthly else None),
        ("decade", _ins_decade(years)),
        ("leader", _ins_leader(t2) if t2["year"] == ly else None),
        ("movers", _ins_movers(t2)),
        ("fsu", _ins_fsu(fsu, ly) if fsu else None),
        ("period", _ins_period(total, periods, first_year)),
        ("women", _ins_women(t4)),
        ("district", _ins_district(t5, cy)),
    ]
    insights = [{"id": k, "text_he": t} for k, t in ins if t]

    yoy_txt = (f", {fmt.signed_pct(last['abs'] / prev['abs'] - 1)} לעומת {prev['year']}"
               if prev and prev["abs"] else "")
    labels["lede"] = (
        f"נתוני העלייה לישראל מהפרסום השנתי של הלשכה המרכזית לסטטיסטיקה (הלמ\"ס): בשנת {ly} עלו "
        f"לישראל {_n(last['abs'])} עולים{yoy_txt}. מאז {first_year} עלו {_n(total)} עולים. "
        "העמוד מציג את מספר העולים לפי שנים, תקופות, ארץ המגורים האחרונה, גיל ומין, מצב משפחתי "
        "ומקום ההשתקעות הראשון בישראל, ומתעדכן עם כל פרסום חדש.")

    release = {"no": rel["RELEASE_NO"], "title": rel["TITLE"], "headline": rel["HEADLINE"],
               "url": rel["PAGE_URL"], "pdf": rel["REPORT_PDF_URL"],
               "date": fmt.d_he(pd.Timestamp(rel["RELEASE_DATE"]))}
    summary = (f"העלייה לישראל לפי שנים מאז {first_year}, ארץ מגורים אחרונה, גיל ויישוב, מנתוני "
               f"הלמ\"ס. בשנת {ly}: {_n(last['abs'])} עולים{yoy_txt}.")
    lead_txt = (f", הרוב מ{named[0]['name']}" if named and t2["year"] == ly
                and named[0]["cur"] * 2 > t2["total"]["cur"] else "")
    desc = (f"כמה עולים עלו לישראל בכל שנה מאז {first_year}: בשנת {ly} עלו {_n(last['abs'])} "
            f"עולים{lead_txt}. עולים חדשים לפי ארץ, גיל ויישוב.")
    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{first_year}/{ly}",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "העלייה לישראל לפי שנים: נתוני עולים חדשים | הלמ\"ס",
                "description": desc,
                "name": "העלייה לישראל לפי שנים",
                "alternate_names": ["עולים חדשים לישראל", "נתוני עלייה",
                                    "מספר העולים לישראל בכל שנה", "עלייה לישראל לפי ארץ מוצא"],
            },
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
        "release": release,
        "flags": flags,
    }
