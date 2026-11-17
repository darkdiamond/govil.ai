"""אקזיטים בישראל: CBS's yearly release on exit deals of Israeli companies.

The release is one table ("לוח 1") plus chart-data sheets ("תרשים N: ..."),
and the sheet NUMBERS MOVE between editions (the Israeli-acquirers chart was
t9 in 2023-2024 and t10 in 2025; an ownership chart was added in 2025). So
every table input (t1..t14, three of them spare slots, all optional) is read
with `cbs.grid`, and each table is found by its TITLE text, not its stem:

  annual   לוח ... לפי סוג                  deals and $M by type, by year
  chart1   תרשים ... (לפי סוג) ... הממוצע   the same as a chart (fallback)
  size     לפי גודל עסקה                    deals by deal size, by year
  district לפי מחוז                         deals by district, by year
  israeli  על ידי גורמים ישראלים            deals made by Israeli buyers, by year
  geo      פילוח גאוגרפי (no ownership)     buyers' location, latest year
  owner    ... ולפי סוג בעלות               Israeli vs foreign ownership share
  sector   לפי תחום פעילות                  deals and $M by field, latest year
  age      לפי שנות הפעילות של החברה        company age at exit, latest year
  closure  ... עד לשנת הסגירה               years from exit to closure
  wages    שכר חודשי ממוצע                  jobs and wage by company size

A title that is found but whose header labels are gone raises (the layout
changed: a human should look). A table missing from an edition drops its
section. The yearly deal series (annual, else chart1) is required.
"""
import re

import pandas as pd
from govlib import cbs, fmt

TITLE = re.compile(r"^(?:תרשים|לוח)\s*\d+[א-ת]?\s*[-:–]\s*")
HEB = re.compile("[א-ת]")
YEAR_IN = re.compile(r"(?:19|20)\d\d")
NUMS = re.compile(r"\d+(?:\.\d+)?")
GEO = re.compile(r"ג(?:י)?אוגרפי")
# Insight-card order; at most MAX_TOP there, the others go to their section.
PRIORITY = ("trend", "value", "big", "ipo", "geo", "sector", "district", "wages",
            "israeli", "age", "closure", "owner", "peak")
MAX_TOP = 8


# ── locating tables ──────────────────────────────────────────────────────


def _title(rows):
    """(title text, row index) of the sheet's "לוח N - ..." / "תרשים N: ..." line."""
    for i, r in enumerate(rows):
        for c in r:
            if TITLE.match(c):
                return c, i
    return "", -1


def _kind(t):
    if "שכר" in t:
        return "wages"
    if "סגירה" in t:
        return "closure"
    if "שנות הפעילות של החברה" in t:
        return "age"
    if "תחום פעילות" in t:
        return "sector"
    if "סוג בעלות" in t:
        return "owner"
    if GEO.search(t):
        return "geo"
    if "גורמים ישראלים" in t:
        return "israeli"
    if "מחוז" in t:
        return "district"
    if "גודל עסקה" in t:
        return "size"
    if "לפי סוג" in t and t.startswith("לוח"):
        return "annual"
    if "סוג" in t and "ממוצע" in t:
        return "chart1"
    return None


def _tables(frames):
    """{kind: (title, rows)} over every non-empty table input, first match
    by stem number wins."""
    out = {}
    names = sorted((n for n in frames if re.fullmatch(r"t\d+", n)), key=lambda n: int(n[1:]))
    for n in names:
        df = frames[n]
        if df.empty:
            continue
        rows = cbs.grid(df, n)
        t, ti = _title(rows)
        k = _kind(t)
        if k and k not in out:
            # header lookups start below the title, which repeats their words
            out[k] = (t, rows[ti + 1:])
    return out


# ── small helpers ────────────────────────────────────────────────────────


def _year(c):
    return int(c) if cbs.YEAR.match(c) else None


def _title_year(title):
    ys = [int(y) for y in YEAR_IN.findall(title)]
    return max(ys) if ys else None


def _labelled(rows, start, ranges=False):
    """(label, row) for rows after `start` with a Hebrew label in column 0
    (or, with `ranges`, a bare range like "5-0" / "+15") and at least one
    number; "סך הכל" rows are returned too (callers skip)."""
    out = []
    for r in rows[start:]:
        label = cbs.cell(r, 0)
        if not label or cbs.YEAR.match(label):
            continue
        if not (HEB.search(label) or (ranges and NUMS.search(label))):
            continue
        if not any(cbs.num(c) is not None for c in r[1:]):
            continue
        out.append((label, r))
    return out


def _is_total(label):
    return label.replace(" ", "") in ("סךהכל", "סךכל")


def _range_label(label, unit=""):
    """CBS writes ranges right-to-left ("5-0", "10-6", "+15", "יותר מ-250").
    Returns (sort key, display label)."""
    ns = sorted(float(x) for x in NUMS.findall(label))
    tail = f" {unit}" if unit else ""
    if not ns:
        return (float("inf"), label)
    if "+" in label or "יותר" in label or "מעל" in label:
        return (ns[-1] + 0.5, f"מעל {_n(ns[-1])}{tail}")
    if label.startswith("עד") or len(ns) == 1:
        return (ns[0] - 0.5 if len(ns) == 1 else ns[0], f"עד {_n(ns[-1])}{tail}")
    lo, hi = ns[0], ns[-1]
    if lo == 0:
        return (lo, f"עד {_n(hi)}{tail}")
    return (lo, f"{_n(lo)} עד {_n(hi)}{tail}")


def _n(v):
    return str(int(v)) if float(v).is_integer() else str(v)


def _r1(v):
    return None if v is None else round(v, 1)


def _r2(v):
    return None if v is None else round(v, 2)


def _usd(m):
    """$ million → display: '16.8 מיליארד דולר' / '545 מיליון דולר'."""
    if m is None:
        return ""
    if m >= 1000:
        return f"{fmt.num_he(m / 1000)} מיליארד דולר"
    return f"{fmt.int_he(m)} מיליון דולר"


def _m(v):
    return "" if v is None else fmt.int_he(v)


# ── table parsers ────────────────────────────────────────────────────────


def _annual(rows):
    """{year: {count, sum, ma_n, ma_sum, ipo_n, ipo_sum}} from לוח 1."""
    h = cbs.row_with(rows, "רכישה או מיזוג", name="annual", contains=True)
    g_tot = cbs.col_after(rows[h], "סך הכל", 0, contains=True)
    g_ma = cbs.col_after(rows[h], "רכישה או מיזוג", 0, contains=True)
    g_ipo = cbs.col_after(rows[h], "הנפקה", 0, contains=True)
    s = h + 1
    sub = rows[s] if s < len(rows) else []
    cols = {}
    for key, g in (("", g_tot), ("ma_", g_ma), ("ipo_", g_ipo)):
        cols[key + "n"] = cbs.col_after(sub, "מספר", g, contains=True)
        cols[key + "sum"] = cbs.col_after(sub, "סכום", g, contains=True)
    out = {}
    for r in rows[s + 1:]:
        y = _year(cbs.cell(r, 0))
        if y is None:
            continue
        v = {k: cbs.val(r, j) for k, j in cols.items()}
        if v["n"] is not None:
            out[y] = {"count": v["n"], "sum": v["sum"], "ma_n": v["ma_n"], "ma_sum": v["ma_sum"],
                      "ipo_n": v["ipo_n"], "ipo_sum": v["ipo_sum"]}
    return out


def _chart1(rows):
    """The same series from the chart sheet: count + $M by type, no counts by type."""
    h = cbs.row_with(rows, "מספר עסקאות", name="chart1", contains=True)
    n = cbs.col_after(rows[h], "מספר עסקאות", 0, contains=True)
    ma = cbs.col_after(rows[h], "רכישה או מיזוג", 0, contains=True)
    ipo = cbs.col_after(rows[h], "הנפקה", 0, contains=True)
    out = {}
    for r in rows[h + 1:]:
        y = _year(cbs.cell(r, 0))
        if y is None or cbs.val(r, n) is None:
            continue
        a, b = cbs.val(r, ma), cbs.val(r, ipo)
        out[y] = {"count": cbs.val(r, n), "sum": (a or 0) + (b or 0) if a is not None or b is not None else None,
                  "ma_n": None, "ma_sum": a, "ipo_n": None, "ipo_sum": b}
    return out


def _size(rows):
    """(years, [(sort, label, [counts by year])])."""
    h = cbs.row_with(rows, "גודל עסקה", name="size", contains=True)
    ycols = [(j, int(c)) for j, c in enumerate(rows[h]) if cbs.YEAR.match(c)]
    if len(ycols) < 2:
        raise ValueError("size: year header columns not found")
    out = []
    for label, r in _labelled(rows, h + 1, ranges=True):
        if _is_total(label):
            continue
        key, disp = _range_label(label)
        out.append((key, disp, [cbs.val(r, j) for j, _ in ycols]))
    out.sort(key=lambda t: (t[0], t[1]))
    return [y for _, y in ycols], out


def _district(rows):
    """(names, {year: [counts]})."""
    first = None
    for i, r in enumerate(rows):
        if _year(cbs.cell(r, 0)) is not None and any(cbs.num(c) is not None for c in r[1:]):
            first = i
            break
    if first is None:
        return [], {}
    hdr = None
    for i in range(first - 1, -1, -1):
        cells = [(j, c) for j, c in enumerate(rows[i]) if j > 0 and c and HEB.search(c) and c != "מחוז"]
        if len(cells) >= 2:
            hdr = cells
            break
    if hdr is None:
        raise ValueError("district: district header row not found")
    out = {}
    for r in rows[first:]:
        y = _year(cbs.cell(r, 0))
        if y is None:
            continue
        vals = [cbs.val(r, j) for j, _ in hdr]
        if any(v is not None for v in vals):
            out[y] = vals
    return [c for _, c in hdr], out


def _yearly_n_sum(rows, name):
    h = cbs.row_with(rows, "מספר עסקאות", name=name, contains=True)
    n = cbs.col_after(rows[h], "מספר עסקאות", 0, contains=True)
    s = cbs.col_after(rows[h], "סכום", 0, contains=True)
    out = {}
    for r in rows[h + 1:]:
        y = _year(cbs.cell(r, 0))
        if y is not None and cbs.val(r, n) is not None:
            out[y] = (cbs.val(r, n), cbs.val(r, s))
    return out


def _cat_n_sum(rows, header, name):
    """[(label, count, $M)] under the header row holding `header`."""
    h = cbs.row_with(rows, header, name=name, contains=True)
    n = cbs.col_after(rows[h], "מספר עסקאות", 0, contains=True)
    s = cbs.col_after(rows[h], "סכום של", 0, contains=True)
    out = []
    for label, r in _labelled(rows, h + 1):
        if _is_total(label):
            continue
        if cbs.val(r, n) is not None:
            out.append((label, cbs.val(r, n), cbs.val(r, s)))
    return out


def _owner(rows):
    """([(label, israeli share 0-100, foreign share 0-100)])."""
    h = cbs.row_with(rows, "בעלות ישראלית", name="owner", contains=True)
    isr = cbs.col_after(rows[h], "בעלות ישראלית", 0, contains=True)
    frn = cbs.col_after(rows[h], "בעלות זרה", 0, contains=True)
    out = []
    for label, r in _labelled(rows, h + 1):
        a, b = cbs.val(r, isr), cbs.val(r, frn)
        if a is None or b is None:
            continue
        tot = a + b
        if tot <= 0:
            continue
        out.append((label, a / tot * 100, b / tot * 100))
    return out


def _dist(rows, header, count_label, name, ranges=False):
    """([(label, count)], total) for a one-column distribution table."""
    h = cbs.row_with(rows, header, name=name, contains=True)
    n = cbs.col_after(rows[h], count_label, 0, contains=True)
    out, total = [], None
    for label, r in _labelled(rows, h + 1, ranges):
        if _is_total(label):
            total = cbs.val(r, n)
            continue
        if cbs.val(r, n) is not None:
            out.append((label, cbs.val(r, n)))
    # CBS's own total row when the sheet has one, else the sum of the rows
    return out, (total if total is not None else sum(v for _, v in out))


def _wages(rows):
    h = cbs.row_with(rows, "שכר חודשי ממוצע למשרת שכיר", name="wages", contains=True)
    jobs = cbs.col_after(rows[h], "משרות שכיר", 0)
    wage = cbs.col_after(rows[h], "שכר חודשי ממוצע למשרת שכיר", 0)
    allc = cbs.col_after(rows[h], "בכלל החברות", 0, contains=True)
    econ = cbs.col_after(rows[h], "במשק", 0, contains=True)
    out, all_w, econ_w = [], None, None
    for r in rows[h + 1:]:
        label = cbs.cell(r, 0)
        if not label or cbs.val(r, wage) is None:
            continue
        out.append((label, cbs.val(r, jobs), cbs.val(r, wage)))
        all_w = all_w if all_w is not None else cbs.val(r, allc)
        econ_w = econ_w if econ_w is not None else cbs.val(r, econ)
    return out, all_w, econ_w


# ── compute ──────────────────────────────────────────────────────────────


def compute(frames):
    tabs = _tables(frames)
    rel = cbs.latest_release(frames["releases"])

    if "annual" in tabs:
        annual = _annual(tabs["annual"][1])
    elif "chart1" in tabs:
        annual = _chart1(tabs["chart1"][1])
    else:
        raise ValueError("no yearly exit-deals table (לוח ... לפי סוג) in the release")
    if not annual:
        raise ValueError("annual: no year rows")
    years = sorted(annual)
    ly = years[-1]
    last = annual[ly]
    prev = annual.get(ly - 1)

    kpis, charts, tables, labels, flags, insights = {}, {}, {}, {}, {}, []

    def add(key, text):
        if text:
            insights.append({"id": key, "text_he": text})

    def avg(rec):
        return rec["sum"] / rec["count"] if rec["sum"] is not None and rec["count"] else None

    # ── yearly series ────────────────────────────────────────────────────
    charts["annual"] = {"x": [str(y) for y in years],
                        "count": [int(annual[y]["count"]) for y in years],
                        "avg": [_r1(avg(annual[y])) for y in years]}
    tables["annual"] = [[str(y), fmt.int_he(annual[y]["count"]), _m(annual[y]["sum"]), _m(avg(annual[y]))]
                        for y in years]
    labels["annual_aria"] = f"מספר עסקאות האקזיט והסכום הממוצע לעסקה, {years[0]} עד {ly}"
    labels["annual_note"] = (f"כמה עסקאות אקזיט של חברות ישראליות נרשמו בכל שנה מאז {years[0]} (עמודות), "
                             f"ומה היה הסכום הממוצע לעסקה במיליוני דולרים (קו).")

    kpis["count"] = {"value": int(last["count"]), "display": fmt.int_he(last["count"]), "tone": "brand"}
    labels["count_kpi"] = f"עסקאות אקזיט ב-{ly}"
    if last["sum"] is not None:
        kpis["sum"] = {"value": round(last["sum"], 1), "display": fmt.num_he(last["sum"] / 1000),
                       "tone": "info"}
        labels["sum_kpi"] = f"מיליארד דולר, סכום העסקאות ב-{ly}"
        a = avg(last)
        kpis["avg"] = {"value": round(a, 1), "display": fmt.int_he(a), "tone": "info"}
        labels["avg_kpi"] = f"מיליון דולר, הסכום הממוצע לעסקה ב-{ly}"

    peak_y = max(years, key=lambda y: (annual[y]["count"], y))
    if prev:
        ch = last["count"] / prev["count"] - 1
        if abs(ch) < 0.03:
            txt = f"ב-{ly} נרשמו {fmt.int_he(last['count'])} עסקאות אקזיט, כמעט כמו ב-{ly - 1} ({fmt.int_he(prev['count'])})"
        else:
            word = "עלייה" if ch > 0 else "ירידה"
            txt = (f"ב-{ly} נרשמו {fmt.int_he(last['count'])} עסקאות אקזיט, {word} של "
                   f"{fmt.pct(abs(ch), 0)} לעומת {fmt.int_he(prev['count'])} ב-{ly - 1}")
        if peak_y == ly - 1:
            txt += ", שנת השיא"
        elif peak_y != ly:
            txt += f". השיא היה ב-{peak_y}, עם {fmt.int_he(annual[peak_y]['count'])} עסקאות"
        else:
            txt += f", השיא של התקופה מאז {years[0]}"
        add("trend", txt + ".")

    sums = [y for y in years if annual[y]["sum"] is not None]
    if last["sum"] is not None and len(sums) >= 3:
        rank = 1 + sum(1 for y in sums if annual[y]["sum"] > last["sum"])
        top_y = max(sums, key=lambda y: (annual[y]["sum"], y))
        txt = f"סכום עסקאות האקזיט ב-{ly} הגיע ל-{_usd(last['sum'])}"
        if prev and prev["sum"]:
            ch = last["sum"] / prev["sum"] - 1
            if abs(ch) >= 0.03:
                txt += f", {'עלייה' if ch > 0 else 'ירידה'} של {fmt.pct(abs(ch), 0)} לעומת {ly - 1}"
        if rank in (2, 3):
            txt += f", הסכום {'השני' if rank == 2 else 'השלישי'} בגובהו מאז {years[0]}"
        if top_y != ly:
            txt += f". הסכום הגבוה ביותר נרשם ב-{top_y}: {_usd(annual[top_y]['sum'])}"
        else:
            txt += f", הגבוה ביותר מאז {years[0]}"
        add("value", txt + ".")

    avgs = [(y, avg(annual[y])) for y in years if avg(annual[y]) is not None]
    if len(avgs) >= 5 and avg(last) is not None:
        first5 = avgs[:5]
        base = sum(a for _, a in first5) / len(first5)
        if base > 0 and avg(last) / base >= 1.3:
            add("peak", f"הסכום הממוצע לעסקה ב-{ly} היה {fmt.int_he(avg(last))} מיליון דולר, "
                        f"לעומת ממוצע של {fmt.int_he(base)} מיליון דולר בשנים {first5[0][0]}-{first5[-1][0]}.")

    # ── by type ──────────────────────────────────────────────────────────
    t_years = [y for y in years if annual[y]["ma_sum"] is not None or annual[y]["ipo_sum"] is not None]
    flags["type"] = len(t_years) >= 3
    has_n = any(annual[y]["ipo_n"] is not None for y in years)
    if flags["type"]:
        charts["type"] = {"x": [str(y) for y in years],
                          "ma": [_r1(annual[y]["ma_sum"]) for y in years],
                          "ipo": [_r1(annual[y]["ipo_sum"]) for y in years]}
        cols = ["שנה"]
        if has_n:
            cols += ["רכישה או מיזוג: עסקאות"]
        cols += ["רכישה או מיזוג: מיליון דולר"]
        if has_n:
            cols += ["הנפקה לציבור: עסקאות"]
        cols += ["הנפקה לציבור: מיליון דולר"]
        rows_ = []
        for y in years:
            a = annual[y]
            r = [str(y)]
            if has_n:
                r.append(_m(a["ma_n"]) or "לא פורסם")
            r.append(_m(a["ma_sum"]) or "לא פורסם")
            if has_n:
                r.append(_m(a["ipo_n"]) or "לא פורסם")
            r.append(_m(a["ipo_sum"]) or "לא פורסם")
            rows_.append(r)
        tables["type"] = rows_
        labels["type_cols"] = cols
        missing = [str(y) for y in years if y not in t_years]
        labels["type_note"] = ("סכום עסקאות האקזיט בכל שנה במיליוני דולרים, לפי סוג העסקה: רכישה או מיזוג, "
                               "או הנפקה ראשונה לציבור."
                               + (f" הפילוח לשנת {fmt.join_he(missing)} לא פורסם בשל מספר קטן של הנפקות."
                                  if missing else ""))
        labels["type_aria"] = f"סכום עסקאות האקזיט לפי סוג, {years[0]} עד {ly}"
        n_years = [y for y in years if annual[y]["ipo_n"] is not None and annual[y]["count"]]
        if n_years and ly in n_years:
            share = annual[ly]["ipo_n"] / annual[ly]["count"]
            top = max(n_years, key=lambda y: (annual[y]["ipo_n"] / annual[y]["count"], y))
            txt = (f"רוב האקזיטים הם רכישות ומיזוגים: ב-{ly} רק {fmt.int_he(annual[ly]['ipo_n'])} מתוך "
                   f"{fmt.int_he(annual[ly]['count'])} העסקאות ({fmt.pct(share, 0)}) היו הנפקות ראשונות לציבור")
            if top != ly:
                ts = annual[top]["ipo_n"] / annual[top]["count"]
                txt += (f", לעומת {fmt.int_he(annual[top]['ipo_n'])} ({fmt.pct(ts, 0)}) ב-{top}, "
                        f"שנת השיא של ההנפקות")
            if share < 0.5:
                add("ipo", txt + ".")
        if has_n:
            kpis["ipo"] = {"value": int(annual[ly]["ipo_n"] or 0), "display": _m(annual[ly]["ipo_n"]) or "-",
                           "tone": "info"}
            labels["ipo_kpi"] = f"הנפקות ראשונות לציבור ב-{ly}"

    # ── by deal size ─────────────────────────────────────────────────────
    flags["size"] = False
    if "size" in tabs:
        s_years, buckets = _size(tabs["size"][1])
        if buckets and s_years:
            flags["size"] = True
            charts["size"] = {"x": [str(y) for y in s_years], "names": [b[1] for b in buckets],
                              "series": [[None if v is None else int(v) for v in b[2]] for b in buckets]}
            tables["size"] = [[str(y)] + [_m(b[2][k]) for b in buckets] for k, y in enumerate(s_years)]
            labels["size_cols"] = ["שנה"] + [b[1] for b in buckets]
            labels["size_aria"] = f"עסקאות האקזיט לפי גודל העסקה, {s_years[0]} עד {s_years[-1]}"
            labels["size_note"] = ("מספר עסקאות האקזיט בכל שנה לפי גודל העסקה, במיליוני דולרים. "
                                   "העסקאות הקטנות הן הרוב, אבל הגדולות קובעות את הסכום הכולל.")
            big = buckets[-1]
            vals = [(s_years[k], v) for k, v in enumerate(big[2]) if v is not None]
            if len(vals) >= 3 and vals[-1][0] == s_years[-1]:
                yb, vb = vals[-1]
                rank = 1 + sum(1 for _, v in vals if v > vb)
                tot_k = sum(b[2][-1] or 0 for b in buckets)
                if rank <= 2 and vb > 0:
                    txt = f"ב-{yb} נרשמו {fmt.int_he(vb)} עסקאות אקזיט בהיקף של {big[1]} מיליון דולר"
                    if tot_k:
                        txt += f" ({fmt.pct(vb / tot_k, 0)} מהעסקאות)"
                    if rank == 1:
                        txt += f", המספר הגבוה ביותר מאז {s_years[0]}"
                    else:
                        top_y, top_v = max(vals, key=lambda t: (t[1], t[0]))
                        txt += f", המספר השני בגובהו מאז {s_years[0]}, אחרי {top_y} ({fmt.int_he(top_v)})"
                    add("big", txt + ".")

    # ── by district ──────────────────────────────────────────────────────
    flags["district"] = False
    if "district" in tabs:
        d_names, d_rows = _district(tabs["district"][1])
        d_years = sorted(d_rows)
        if d_names and d_years:
            flags["district"] = True
            order = sorted(range(len(d_names)), key=lambda k: (-(d_rows[d_years[-1]][k] or 0), d_names[k]))
            charts["district"] = {"x": [str(y) for y in d_years], "names": [d_names[k] for k in order],
                                  "series": [[None if d_rows[y][k] is None else int(d_rows[y][k]) for y in d_years]
                                             for k in order]}
            tables["district"] = [[str(y)] + [_m(d_rows[y][k]) for k in order] for y in d_years]
            labels["district_cols"] = ["שנה"] + [d_names[k] for k in order]
            labels["district_aria"] = f"עסקאות האקזיט לפי מחוז, {d_years[0]} עד {d_years[-1]}"
            labels["district_note"] = "מספר עסקאות האקזיט בכל שנה לפי המחוז שבו פועלת החברה."
            k0 = order[0]
            yl, yf = d_years[-1], d_years[0]
            tl = sum(v or 0 for v in d_rows[yl])
            tf = sum(v or 0 for v in d_rows[yf])
            if tl and tf and len(d_years) >= 3:
                sl = (d_rows[yl][k0] or 0) / tl
                sf = (d_rows[yf][k0] or 0) / tf
                if sl >= 0.3:
                    txt = f"מחוז {d_names[k0]} מוביל: {fmt.pct(sl, 0)} מעסקאות האקזיט ב-{yl}"
                    if sl - sf >= 0.05:
                        txt += f", לעומת {fmt.pct(sf, 0)} ב-{yf}"
                    elif sf - sl >= 0.05:
                        txt += f", פחות מ-{fmt.pct(sf, 0)} ב-{yf}"
                    add("district", txt + ".")

    # ── Israeli buyers ───────────────────────────────────────────────────
    flags["israeli"] = False
    if "israeli" in tabs:
        isr = _yearly_n_sum(tabs["israeli"][1], "israeli")
        i_years = sorted(isr)
        if i_years:
            flags["israeli"] = True
            charts["israeli"] = {"x": [str(y) for y in i_years], "count": [int(isr[y][0]) for y in i_years],
                                 "sum": [_r1(isr[y][1]) for y in i_years]}
            tables["israeli"] = [[str(y), fmt.int_he(isr[y][0]), _m(isr[y][1]),
                                  fmt.pct(isr[y][0] / annual[y]["count"], 0) if y in annual and annual[y]["count"] else ""]
                                 for y in i_years]
            labels["israeli_aria"] = f"עסקאות אקזיט של רוכשים ישראלים, {i_years[0]} עד {i_years[-1]}"
            labels["israeli_note"] = ("עסקאות אקזיט שבהן הרוכש (או הבורסה, בהנפקה) ישראלי: מספר העסקאות "
                                      "(עמודות) והסכום במיליוני דולרים (קו).")
            yi = i_years[-1]
            if yi in annual and annual[yi]["count"] and isr[yi][1] is not None and annual[yi]["sum"]:
                sn = isr[yi][0] / annual[yi]["count"]
                ss = isr[yi][1] / annual[yi]["sum"]
                if sn > ss:
                    add("israeli", f"גורמים ישראלים ביצעו {fmt.int_he(isr[yi][0])} מעסקאות האקזיט ב-{yi} "
                                   f"({fmt.pct(sn, 0)}), אבל רק {fmt.pct(ss, 0)} מסכום העסקאות: "
                                   f"{_usd(isr[yi][1])}.")

    # ── buyers' location ─────────────────────────────────────────────────
    flags["geo"] = False
    if "geo" in tabs:
        t, rows = tabs["geo"]
        geo = _cat_n_sum(rows, "מיקום", "geo")
        if len(geo) >= 2:
            flags["geo"] = True
            gy = _title_year(t)
            geo.sort(key=lambda g: (-g[1], g[0]))
            tn = sum(g[1] for g in geo)
            ts = sum(g[2] or 0 for g in geo)
            charts["geo"] = {"names": [g[0] for g in geo], "count": [int(g[1]) for g in geo],
                             "sum": [_r1(g[2]) for g in geo]}
            tables["geo"] = [[g[0], fmt.int_he(g[1]), fmt.pct(g[1] / tn, 0) if tn else "", _m(g[2]),
                              fmt.pct(g[2] / ts, 0) if ts and g[2] is not None else ""] for g in geo]
            labels["geo_aria"] = "עסקאות האקזיט לפי מיקום הרוכש" + (f", {gy}" if gy else "")
            labels["geo_note"] = ("מאיפה הגיעו הרוכשים (ובהנפקות, איפה הונפקה החברה)"
                                  + (f" בעסקאות של {gy}" if gy else "") + ": מספר העסקאות והסכום במיליוני דולרים.")
            g0 = geo[0]
            if tn and ts and g0[2] is not None and g0[1] / tn >= 0.35:
                add("geo", f"{g0[0]} היא מקור הרוכשים הגדול: {fmt.int_he(g0[1])} מעסקאות האקזיט"
                           + (f" ב-{gy}" if gy else "")
                           + f" ({fmt.pct(g0[1] / tn, 0)}) ו-{fmt.pct(g0[2] / ts, 0)} מסכומן, {_usd(g0[2])}.")

    flags["owner"] = False
    if "owner" in tabs:
        t, rows = tabs["owner"]
        own = _owner(rows)
        if len(own) >= 2:
            flags["owner"] = True
            oy = _title_year(t)
            charts["owner"] = {"names": [o[0] for o in own], "isr": [_r1(o[1]) for o in own],
                               "frn": [_r1(o[2]) for o in own]}
            tables["owner"] = [[o[0], fmt.pct_of(o[1], 0), fmt.pct_of(o[2], 0)] for o in own]
            labels["owner_aria"] = "בעלות על החברות שנרכשו, לפי מיקום הרוכש" + (f", {oy}" if oy else "")
            labels["owner_note"] = ("איזה חלק מהחברות שעשו אקזיט היה בבעלות ישראלית ואיזה בבעלות זרה, "
                                    "לפי מיקום הרוכש" + (f", {oy}" if oy else "") + ".")
            lo = min(own, key=lambda o: (o[1], o[0]))
            if all(o[1] > 50 for o in own):
                add("owner", "רוב החברות שעשו אקזיט" + (f" ב-{oy}" if oy else "")
                             + " היו בבעלות ישראלית, בכל מיקום של הרוכש. החלק הנמוך ביותר: "
                             f"{fmt.pct_of(lo[1], 0)} בבעלות ישראלית כשהרוכש "
                             + ("ממדינה אחרת" if lo[0].strip() in ("אחר", "אחרות", "אחרים", "אחרת")
                                else f"מ{lo[0]}") + ".")

    # ── by field ─────────────────────────────────────────────────────────
    flags["sector"] = False
    if "sector" in tabs:
        t, rows = tabs["sector"]
        sec = _cat_n_sum(rows, "תחום פעילות", "sector")
        if len(sec) >= 2:
            flags["sector"] = True
            sy = _title_year(t)
            sec.sort(key=lambda g: (-(g[2] or 0), -g[1], g[0]))
            charts["sector"] = {"names": [g[0] for g in sec], "count": [int(g[1]) for g in sec],
                                "sum": [_r1(g[2]) for g in sec]}
            tables["sector"] = [[g[0], fmt.int_he(g[1]), _m(g[2]),
                                 _m(g[2] / g[1]) if g[2] is not None and g[1] else ""] for g in sec]
            labels["sector_aria"] = "עסקאות האקזיט לפי תחום פעילות" + (f", {sy}" if sy else "")
            labels["sector_note"] = ("סכום עסקאות האקזיט במיליוני דולרים לפי תחום הפעילות של החברה"
                                     + (f", {sy}" if sy else "")
                                     + ". מספר העסקאות והסכום הממוצע לעסקה בטבלה. תחומים קטנים מאוחדים בהודעה.")
            by_n = max(sec, key=lambda g: (g[1], g[0]))
            by_s = sec[0]
            tn = sum(g[1] for g in sec)
            ts = sum(g[2] or 0 for g in sec)
            if tn and ts:
                txt = ("התחום המוביל"
                       + (f" ב-{sy}" if sy else "")
                       + f" הוא {by_n[0]}: {fmt.int_he(by_n[1])} עסקאות ({fmt.pct(by_n[1] / tn, 0)})")
                if by_s[0] == by_n[0]:
                    txt += f" ו-{_usd(by_s[2])} ({fmt.pct(by_s[2] / ts, 0)} מהסכום)"
                else:
                    txt += (f". בסכום מוביל {by_s[0]}, עם {_usd(by_s[2])} ב-{fmt.int_he(by_s[1])} עסקאות")
                add("sector", txt + ".")

    # ── company age at exit ──────────────────────────────────────────────
    flags["age"] = False
    if "age" in tabs:
        t, rows = tabs["age"]
        age, age_tot = _dist(rows, "שנות פעילות", "מספר עסקאות", "age", ranges=True)
        if age:
            flags["age"] = True
            ay = _title_year(t)
            items = sorted((_range_label(lab, "שנים") + (v,) for lab, v in age), key=lambda x: (x[0], x[1]))
            tot = age_tot
            charts["age"] = {"names": [x[1] for x in items], "values": [int(x[2]) for x in items]}
            tables["age"] = [[x[1], fmt.int_he(x[2]), fmt.pct(x[2] / tot, 0) if tot else ""] for x in items]
            labels["age_aria"] = "עסקאות האקזיט לפי גיל החברה" + (f", {ay}" if ay else "")
            labels["age_note"] = ("כמה שנים פעלה החברה עד עסקת האקזיט" + (f", בעסקאות של {ay}" if ay else "") + ".")
            if tot and len(items) >= 2:
                young = items[0]
                old = items[-1]
                add("age", f"{fmt.pct(young[2] / tot, 0)} מהחברות שעשו אקזיט"
                           + (f" ב-{ay}" if ay else "")
                           + f" פעלו {young[1]}, ו-{fmt.pct(old[2] / tot, 0)} פעלו {old[1]}.")

    # ── years from exit to closure ───────────────────────────────────────
    flags["closure"] = False
    if "closure" in tabs:
        t, rows = tabs["closure"]
        clo, clo_tot = _dist(rows, "מספר חברות", "מספר חברות", "closure")
        if clo:
            flags["closure"] = True
            yrs = [int(y) for y in YEAR_IN.findall(t)]
            span = f"{min(yrs)}-{max(yrs)}" if len(yrs) >= 2 else ""
            tot = clo_tot
            charts["closure"] = {"names": [c[0] for c in clo], "values": [int(c[1]) for c in clo]}
            tables["closure"] = [[c[0], fmt.int_he(c[1]), fmt.pct(c[1] / tot, 0) if tot else ""] for c in clo]
            labels["closure_aria"] = "חברות שנסגרו אחרי עסקת אקזיט, לפי הזמן עד הסגירה"
            labels["closure_note"] = (f"{fmt.int_he(tot)} חברות שעשו אקזיט"
                                      + (f" בשנים {span}" if span else "")
                                      + " נסגרו מאז. כמה זמן אחרי העסקה נסגרה כל אחת: רבות נבלעות ברוכש כבר בשנת העסקה.")
            first = clo[0]
            if tot and "בשנת האקזיט" in first[0]:
                add("closure", f"{fmt.int_he(tot)} חברות שעשו אקזיט"
                               + (f" בשנים {span}" if span else "")
                               + f" נסגרו מאז, ו-{fmt.pct(first[1] / tot, 0)} מהן ({fmt.int_he(first[1])}) "
                                 f"נסגרו כבר בשנת העסקה.")

    # ── jobs and wages ───────────────────────────────────────────────────
    flags["wages"] = False
    if "wages" in tabs:
        t, rows = tabs["wages"]
        w_rows, all_w, econ_w = _wages(rows)
        if w_rows:
            flags["wages"] = True
            wy = _title_year(t)
            items = sorted((_range_label(lab) + (j, w) for lab, j, w in w_rows), key=lambda x: (x[0], x[1]))
            charts["wages"] = {"names": [x[1] for x in items], "wage": [_r1(x[3]) for x in items],
                               "all": _r1(all_w), "econ": _r1(econ_w)}
            tables["wages"] = [[x[1], fmt.int_he(x[2]) if x[2] is not None else "", fmt.int_he(x[3])]
                               for x in items]
            labels["wages_aria"] = "שכר חודשי ממוצע בחברות שעשו אקזיט, לפי גודל החברה" + (f", {wy}" if wy else "")
            labels["wages_note"] = ("שכר חודשי ממוצע למשרת שכיר (בשקלים) בחברות שעשו אקזיט"
                                    + (f" ב-{wy}" if wy else "")
                                    + ", לפי גודל החברה, מול הממוצע בכל החברות האלה ובכל המשק.")
            if all_w and econ_w:
                kpis["wage"] = {"value": round(all_w), "display": fmt.int_he(all_w), "tone": "info"}
                labels["wage_kpi"] = "ש\"ח, שכר חודשי ממוצע בחברות שעשו אקזיט" + (f" ב-{wy}" if wy else "")
                ratio = all_w / econ_w
                if ratio >= 1.2:
                    add("wages", "השכר החודשי הממוצע למשרת שכיר בחברות שעשו אקזיט"
                                 + (f" ב-{wy}" if wy else "")
                                 + f" היה {fmt.int_he(all_w)} ש\"ח, פי {fmt.num_he(ratio)} מהממוצע במשק "
                                   f"({fmt.int_he(econ_w)} ש\"ח).")
            jobs = sum(x[2] or 0 for x in items)
            if jobs:
                labels["wages_jobs"] = f"בחברות האלה היו {fmt.int_he(jobs)} משרות שכיר."

    # Insight card holds the strongest findings; the rest show in their section.
    by_id = {i["id"]: i for i in insights}
    top = [by_id[k] for k in PRIORITY if k in by_id][:MAX_TOP]
    top_ids = {i["id"] for i in top}
    callouts = {i["id"]: i["text_he"] for i in insights if i["id"] not in top_ids}

    release = {"no": rel["RELEASE_NO"], "title": rel["TITLE"], "headline": rel["HEADLINE"],
               "url": rel["PAGE_URL"], "pdf": rel["REPORT_PDF_URL"],
               "date": fmt.d_he(pd.Timestamp(rel["RELEASE_DATE"]))}

    sum_txt = f", בסכום כולל של {_usd(last['sum'])}" if last["sum"] is not None else ""
    labels["lede"] = (f"כמה חברות ישראליות נמכרו או הונפקו בכל שנה, בכמה כסף, מי קנה אותן ובאילו תחומים. "
                      f"הנתונים מתוך ההודעה השנתית של הלשכה המרכזית לסטטיסטיקה (הלמ\"ס), על בסיס הנתונים "
                      f"על אקזיטים בישראל, ומתעדכנים עם כל הודעה חדשה. הנתון האחרון הוא לשנת {ly}: "
                      f"{fmt.int_he(last['count'])} עסקאות אקזיט{sum_txt}.")
    summary = (f"עסקאות אקזיט של חברות ישראליות לפי נתוני הלמ\"ס, {years[0]}-{ly}: ב-{ly} "
               f"{fmt.int_he(last['count'])} עסקאות{sum_txt}.")
    desc = (f"כמה אקזיטים היו בישראל ובכמה כסף: {fmt.int_he(last['count'])} עסקאות ב-{ly}"
            + (f", {_usd(last['sum'])}" if last["sum"] is not None else "")
            + ". רכישות, הנפקות, תחומים ורוכשים, נתוני הלמ\"ס.")
    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{years[0]}/{ly}",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "אקזיטים בישראל: מספר העסקאות ושוויין | הלמ\"ס",
                "description": desc,
                "name": "אקזיטים בישראל",
                "alternate_names": ["עסקאות אקזיט בישראל", "אקזיטים בהייטק הישראלי",
                                    "רכישות ומיזוגים של חברות ישראליות",
                                    "בסיס הנתונים על אקזיטים בישראל"],
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
