"""תאונות דרכים עם נפגעים: CBS's yearly "final selected figures" release.

The release is a handful of chart-data sheets ("תרשים N - ..."). CBS
renumbers its tables between editions, so every table input (t1..t7, three
of them spare slots, all optional) is read with `cbs.grid` and each chart is
found by its TITLE text, not by its stem:

  killed  הרוגים בתאונות דרכים <years>        killed per year since 1949
  intl    ... השוואה בין-לאומית                 killed per 100,000 people (or
                                                per billion km) by country
  sshare  תאונות חמורות (קטלניות וקשות)        % of accidents that were severe
  srate   נפגעים באופן חמור                     killed + seriously injured per
                                                100,000 people
  peds    הולכי רגל ... חציית כביש              pedestrians hurt crossing, %
                                                in / not in a crosswalk

`killed` is required (every edition has it). A chart missing from an
edition drops its section; a recognised chart whose header labels are gone
raises (the layout changed: a human should look).
"""
import re

import pandas as pd
from govlib import cbs, fmt

TITLE = re.compile(r"^(?:תרשים|לוח)\s*\d+[א-ת]?\s*-\s*")
HEB = re.compile("[א-ת]")
YEAR_IN = re.compile(r"(?:19|20)\d\d")
ISRAEL = "ישראל"
FLAT_PCT = 0.02      # |year-on-year change| below this reads as "about the same"
FLAT_PP = 1.0        # percentage points, for the severe-share trend
FLAT_RATE = 0.03     # relative change, for per-100,000 rates


# ── locating tables ──────────────────────────────────────────────────────


def _title(rows):
    for r in rows:
        for c in r:
            if TITLE.match(c):
                return c
    return ""


def _kind(t):
    if "הולכי רגל" in t:
        return "peds"
    if "בין-לאומית" in t or "בין לאומית" in t or "בינלאומית" in t:
        return "intl"
    if "תאונות חמורות" in t:
        return "sshare"
    if "נפגעים באופן חמור" in t:
        return "srate"
    if "הרוגים בתאונות דרכים" in t:
        return "killed"
    return None


def _tables(frames):
    """{kind: (title, rows)} over every non-empty table input; the lowest
    stem number wins when two tables share a kind."""
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
            out[k] = (TITLE.sub("", t).strip(), rows)
    return out


def _years_in(text):
    return sorted(int(y) for y in YEAR_IN.findall(text))


# ── table parsers ────────────────────────────────────────────────────────


def _killed(title, rows):
    """{year: killed}. The sheet prints a year only every five rows, so the
    year is counted down from each label; it stops at the title's last year
    (CBS puts a grand total right below the series)."""
    hit = next(((i, j) for i, r in enumerate(rows) for j, c in enumerate(r)
                if c.startswith("הרוגים")), None)
    if hit is None:
        raise ValueError("killed: 'הרוגים' header not found")
    h, vcol = hit
    span = _years_in(title)
    if not span:
        raise ValueError("killed: no year range in the chart title")
    end = span[-1]
    ycol = cbs.best_col(rows[h + 1:], lambda v: bool(cbs.YEAR.match(v)), exclude={vcol})
    if ycol is None:
        raise ValueError("killed: no year column")
    out, year = {}, None
    for r in rows[h + 1:]:
        v = cbs.val(r, vcol)
        if v is None:
            continue
        label = cbs.cell(r, ycol)
        if cbs.YEAR.match(label):
            if year is not None and int(label) != year + 1:
                raise ValueError(f"killed: year label {label} after {year}")
            year = int(label)
        elif year is not None:
            year += 1
        else:
            continue
        if year > end:
            break
        out[year] = v
    return out


def _year_cols(row):
    return sorted((int(c), j) for j, c in enumerate(row) if cbs.YEAR.match(c))


def _series(rows, name):
    """{year: value} from a one-series sheet, laid out either across (a row
    of years and a value row below it) or down (a year column)."""
    for i, r in enumerate(rows):
        ycols = _year_cols(r)
        if len(ycols) >= 3:
            for r2 in rows[i + 1:]:
                vals = {y: cbs.val(r2, j) for y, j in ycols}
                if sum(v is not None for v in vals.values()) >= 2:
                    return {y: v for y, v in vals.items() if v is not None}
            return {}  # a data row, not a header: it may be gone
    ycol = cbs.best_col(rows, lambda v: bool(cbs.YEAR.match(v)))
    if ycol is None:
        raise ValueError(f"{name}: no year row or column")
    body = [r for r in rows if cbs.YEAR.match(cbs.cell(r, ycol))]
    vcol = cbs.best_col(body, lambda v: cbs.num(v) is not None and not cbs.YEAR.match(v),
                        exclude={ycol})
    if vcol is None:
        raise ValueError(f"{name}: no value column")
    out = {}
    for r in body:
        v = cbs.val(r, vcol)
        if v is not None:
            out[int(cbs.cell(r, ycol))] = v
    return out


def _intl(title, rows):
    """(unit, years, [(country, [value per year])]) newest year first in
    `years`."""
    h = next((i for i, r in enumerate(rows) if len(_year_cols(r)) >= 1
              and not any(HEB.search(c) for c in r)), None)
    if h is None:
        raise ValueError("intl: year header row not found")
    ycols = sorted(_year_cols(rows[h]), reverse=True)
    # The Hebrew country name sits first or last, by edition.
    lcol = cbs.best_col(rows[h + 1:], lambda v: bool(HEB.search(v)), exclude={j for _, j in ycols})
    out = []
    for r in rows[h + 1:]:
        label = cbs.cell(r, lcol) if lcol is not None else ""
        if not label or not HEB.search(label):
            continue
        vals = [cbs.val(r, j) for _, j in ycols]
        if any(v is not None for v in vals):
            out.append((label, vals))
    if "מאה אלף" in title or "100,000" in title:
        unit = "pop"
    elif "מיליארד" in title:
        unit = "km"
    else:
        raise ValueError("intl: unit (per 100,000 people / per billion km) not in the title")
    return unit, [y for y, _ in ycols], out


def _peds(title, rows):
    """(year, [(severity, % in crosswalk, % not in crosswalk)])."""
    h = cbs.row_with(rows, "לא במעבר חצייה", name="peds", contains=True)
    out_col = cbs.col_after(rows[h], "לא במעבר חצייה", 0, contains=True)
    in_col = next((j for j, c in enumerate(rows[h]) if "במעבר חצייה" in c and "לא" not in c), None)
    if in_col is None:
        raise ValueError("peds: 'במעבר חצייה' header not found")
    out = []
    for r in rows[h + 1:]:
        label = cbs.cell(r, 0)
        a, b = cbs.val(r, in_col), cbs.val(r, out_col)
        if label and HEB.search(label) and a is not None and b is not None:
            out.append((label, a, b))
    ys = _years_in(title)
    return (ys[-1] if ys else None), out


# ── formatting ───────────────────────────────────────────────────────────


def _r1(v):
    return None if v is None else round(v, 1)


def _r2(v):
    return None if v is None else round(v, 2)


def _chg_tone(chg, flat, up_bad=True):
    if chg is None or abs(chg) < flat:
        return "brand"
    return "danger" if (chg > 0) == up_bad else "ok"


def _decade_rows(killed):
    """[(label, first, last, average, total, years)] per calendar decade."""
    out = []
    for d in sorted({y // 10 * 10 for y in killed}):
        ys = sorted(y for y in killed if d <= y < d + 10)
        vals = [killed[y] for y in ys]
        label = str(ys[0]) if ys[0] == ys[-1] else f"{ys[0]}-{ys[-1]}"
        out.append((label, ys[0], ys[-1], sum(vals) / len(vals), sum(vals), len(ys)))
    return out


# ── compute ──────────────────────────────────────────────────────────────


def compute(frames):
    rel = cbs.latest_release(frames["releases"])
    tabs = _tables(frames)
    if "killed" not in tabs:
        raise ValueError("killed-per-year chart (הרוגים בתאונות דרכים) not found in any table")
    killed = _killed(*tabs["killed"])
    if len(killed) < 2:
        raise ValueError("killed: fewer than two years")
    ky = sorted(killed)
    ly, py = ky[-1], ky[-2]
    if py != ly - 1:
        raise ValueError(f"killed: gap between {py} and {ly}")
    k_last, k_prev = killed[ly], killed[py]
    k_chg = (k_last - k_prev) / k_prev if k_prev else None

    kpis, charts, tables, labels, flags, insights = {}, {}, {}, {}, {}, []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    # ── killed per year ──────────────────────────────────────────────────
    tone = _chg_tone(k_chg, FLAT_PCT)
    kpis["killed"] = {"value": k_last, "display": fmt.int_he(k_last), "tone": tone}
    labels["killed_kpi"] = f"הרוגים בתאונות דרכים ב-{ly}"
    if k_chg is not None:
        kpis["killed_chg"] = {"value": round(k_chg, 4), "display": fmt.signed_pct(k_chg), "tone": tone}
        labels["killed_chg_kpi"] = f"שינוי במספר ההרוגים לעומת {py}"
    charts["killed"] = {"x": [str(y) for y in ky], "y": [killed[y] for y in ky]}
    tables["killed"] = [[str(y), fmt.int_he(killed[y])] for y in reversed(ky)]
    labels["killed_note"] = (f"מספר ההרוגים בתאונות דרכים בכל שנה, {ky[0]} עד {ly}. "
                             f"אפשר להגדיל קטע מהציר בגרירה של המחוון שמתחת לתרשים.")
    labels["killed_aria"] = f"הרוגים בתאונות דרכים לפי שנה, {ky[0]} עד {ly}"

    if k_chg is not None:
        if abs(k_chg) < FLAT_PCT:
            dir_txt = f"כמעט כמו ב-{py} ({fmt.int_he(k_prev)})"
        elif k_chg > 0:
            dir_txt = f"עלייה של {fmt.pct(k_chg)} לעומת {py} ({fmt.int_he(k_prev)})"
        else:
            dir_txt = f"ירידה של {fmt.pct(-k_chg)} לעומת {py} ({fmt.int_he(k_prev)})"
        add("latest", f"בשנת {ly} נהרגו {fmt.int_he(k_last)} בני אדם בתאונות דרכים, {dir_txt}.")

    # Highest / lowest since: the last earlier year at or beyond this level.
    earlier = [y for y in ky if y < ly]
    above = [y for y in earlier if killed[y] >= k_last]
    below = [y for y in earlier if killed[y] <= k_last]
    since = None
    if k_chg is not None and k_chg > 0:
        if not above:
            since = f"זהו מספר ההרוגים הגבוה ביותר מאז תחילת הסדרה ב-{ky[0]}."
        elif ly - max(above) >= 5:
            y0 = max(above)
            since = (f"זהו מספר ההרוגים הגבוה ביותר מאז {y0}, אז נהרגו "
                     + ("גם כן" if killed[y0] == k_last else "")
                     + f" {fmt.int_he(killed[y0])} בני אדם.").replace("  ", " ")
    elif k_chg is not None and k_chg < 0:
        if not below:
            since = f"זהו מספר ההרוגים הנמוך ביותר מאז תחילת הסדרה ב-{ky[0]}."
        elif ly - max(below) >= 5:
            y0 = max(below)
            since = (f"זהו מספר ההרוגים הנמוך ביותר מאז {y0}, אז נהרגו "
                     + ("גם כן" if killed[y0] == k_last else "")
                     + f" {fmt.int_he(killed[y0])} בני אדם.").replace("  ", " ")
    add("since", since)

    peak_y = min(ky, key=lambda y: (-killed[y], y))
    if peak_y != ly and killed[peak_y] > 0:
        drop = (killed[peak_y] - k_last) / killed[peak_y]
        if drop >= 0.1:
            add("peak", f"שיא ההרוגים נרשם ב-{peak_y}: {fmt.int_he(killed[peak_y])} הרוגים. "
                        f"ב-{ly} נהרגו {fmt.pct(drop)} פחות מאשר בשנת השיא.")
    labels["peak_year"] = str(peak_y)

    prev10 = [y for y in ky if ly - 10 <= y < ly]
    if len(prev10) == 10:
        avg10 = sum(killed[y] for y in prev10) / 10
        rel10 = (k_last - avg10) / avg10 if avg10 else 0
        if abs(rel10) >= 0.05:
            word = "יותר" if rel10 > 0 else "פחות"
            add("avg10", f"בעשור {prev10[0]}-{prev10[-1]} נהרגו בממוצע {fmt.int_he(avg10)} בני אדם "
                         f"בשנה. ב-{ly} נהרגו {fmt.pct(abs(rel10))} {word} מהממוצע הזה.")

    # ── decades ──────────────────────────────────────────────────────────
    dec = _decade_rows(killed)
    charts["decades"] = {"x": [d[0] for d in dec], "y": [round(d[3]) for d in dec],
                         "years": [d[5] for d in dec]}
    tables["decades"] = [[d[0], fmt.int_he(d[3]), fmt.int_he(d[4]), str(d[5])] for d in dec]
    labels["decades_note"] = ("ממוצע ההרוגים בשנה בכל עשור"
                              + (f". העשור האחרון חלקי: {dec[-1][0]}." if dec[-1][5] < 10 else "."))
    labels["decades_aria"] = "ממוצע שנתי של הרוגים בתאונות דרכים לפי עשור"
    total = sum(killed.values())
    labels["total_since"] = (f"מאז {ky[0]} ועד {ly} נהרגו בתאונות דרכים בישראל "
                             f"{fmt.int_he(total)} בני אדם.")
    full = [d for d in dec if d[5] == 10]
    if len(full) >= 2:
        worst = min(full, key=lambda d: (-d[3], d[1]))
        add("decade", f"העשור הקטלני ביותר היה {worst[0]}, עם ממוצע של {fmt.int_he(worst[3])} "
                      f"הרוגים בשנה. בסך הכול נהרגו מאז {ky[0]} {fmt.int_he(total)} בני אדם.")

    # ── severe share of accidents ────────────────────────────────────────
    flags["sshare"] = False
    if "sshare" in tabs:
        ss = _series(tabs["sshare"][1], "sshare")
        ssy = sorted(ss)
        if len(ssy) >= 2:
            flags["sshare"] = True
            s0, s1 = ss[ssy[0]], ss[ssy[-1]]
            charts["sshare"] = {"x": [str(y) for y in ssy], "y": [_r2(ss[y]) for y in ssy]}
            tables["sshare"] = [[str(y), fmt.pct_of(ss[y])] for y in ssy]
            up = s1 - ss[ssy[-2]]
            kpis["sshare"] = {"value": _r2(s1), "display": fmt.pct_of(s1),
                              "tone": "warn" if up >= FLAT_PP else ("ok" if up <= -FLAT_PP else "brand")}
            labels["sshare_kpi"] = f"תאונות חמורות מכלל התאונות עם נפגעים, {ssy[-1]}"
            labels["sshare_note"] = (f"איזה חלק מהתאונות עם נפגעים היו חמורות (קטלניות או קשות), "
                                     f"{ssy[0]} עד {ssy[-1]}, באחוזים.")
            labels["sshare_aria"] = f"אחוז התאונות החמורות מכלל התאונות, {ssy[0]} עד {ssy[-1]}"
            d = s1 - s0
            if abs(d) >= FLAT_PP:
                verb = "עלה" if d > 0 else "ירד"
                add("sshare", f"חלקן של התאונות החמורות (קטלניות וקשות) מכלל התאונות עם נפגעים "
                              f"{verb} מ-{fmt.pct_of(s0)} ב-{ssy[0]} ל-{fmt.pct_of(s1)} ב-{ssy[-1]}.")

    # ── seriously hurt per 100,000 people ────────────────────────────────
    flags["srate"] = False
    if "srate" in tabs:
        sr = _series(tabs["srate"][1], "srate")
        sry = sorted(sr)
        if len(sry) >= 2:
            flags["srate"] = True
            r1, r0 = sr[sry[-1]], sr[sry[-2]]
            rchg = (r1 - r0) / r0 if r0 else None
            charts["srate"] = {"x": [str(y) for y in sry], "y": [_r2(sr[y]) for y in sry]}
            tables["srate"] = [[str(y), fmt.num_he(sr[y], 1)] for y in sry]
            kpis["srate"] = {"value": _r2(r1), "display": fmt.num_he(r1, 1),
                             "tone": _chg_tone(rchg, FLAT_RATE)}
            labels["srate_kpi"] = f"הרוגים ופצועים קשה לכל 100,000 תושבים, {sry[-1]}"
            labels["srate_note"] = (f"נפגעים באופן חמור (הרוגים ופצועים קשה) לכל 100,000 תושבים, "
                                    f"{sry[0]} עד {sry[-1]}. שיעור לנפש מנטרל את גידול האוכלוסייה.")
            labels["srate_aria"] = f"נפגעים באופן חמור לכל 100,000 תושבים, {sry[0]} עד {sry[-1]}"
            hi = min(sry, key=lambda y: (-sr[y], y))
            lo = min(sry, key=lambda y: (sr[y], y))
            if rchg is not None:
                if abs(rchg) < FLAT_RATE:
                    t = f"כמעט כמו ב-{sry[-2]} ({fmt.num_he(r0, 1)})"
                else:
                    t = f"לעומת {fmt.num_he(r0, 1)} ב-{sry[-2]}"
                extra = ""
                if hi == sry[-1]:
                    extra = f" זה השיעור הגבוה ביותר בשנים {sry[0]}-{sry[-1]}."
                elif lo != sry[-1]:
                    extra = (f" בשנים {sry[0]}-{sry[-1]} נע השיעור בין {fmt.num_he(sr[lo], 1)} "
                             f"({lo}) ל-{fmt.num_he(sr[hi], 1)} ({hi}).")
                add("srate", f"ב-{sry[-1]} נפגעו באופן חמור (נהרגו או נפצעו קשה) "
                             f"{fmt.num_he(r1, 1)} בני אדם לכל 100,000 תושבים, {t}.{extra}")

    # ── international comparison ─────────────────────────────────────────
    flags["intl"] = False
    if "intl" in tabs:
        unit, iyears, rows_i = _intl(*tabs["intl"])
        latest = [(c, v[0]) for c, v in rows_i if v and v[0] is not None]
        if len(latest) >= 5 and iyears:
            flags["intl"] = True
            iy = iyears[0]
            order = sorted(latest, key=lambda t: (-t[1], t[0]))
            charts["intl"] = {"names": [c for c, _ in order], "values": [_r2(v) for _, v in order],
                              "israel": ISRAEL}
            by_c = dict(rows_i)
            tables["intl"] = [[c] + [("–" if v is None else fmt.num_he(v, 1)) for v in by_c[c]]
                              for c, _ in order]
            labels["intl_cols"] = ["מדינה"] + [str(y) for y in iyears]
            unit_he = "לכל 100,000 תושבים" if unit == "pop" else "למיליארד ק\"מ נסועה"
            labels["intl_unit"] = unit_he
            labels["intl_note"] = (f"הרוגים בתאונות דרכים {unit_he}, בישראל ובמדינות OECD נבחרות, "
                                   f"{iyears[-1]} עד {iy}. התרשים מציג את {iy}.")
            labels["intl_aria"] = f"הרוגים בתאונות דרכים {unit_he} לפי מדינה, {iy}"
            labels["intl_title"] = f"ישראל בהשוואה בין-לאומית: הרוגים {unit_he}"
            isr = next((v for c, v in order if c == ISRAEL), None)
            if isr is not None:
                rank = 1 + sum(1 for _, v in order if v > isr)
                n = len(order)
                vals = sorted(v for _, v in order)
                med = (vals[(n - 1) // 2] + vals[n // 2]) / 2
                kpis["intl"] = {"value": _r2(isr), "display": fmt.num_he(isr, 1), "tone": "info"}
                labels["intl_kpi"] = f"הרוגים {unit_he} בישראל, {iy}"
                rel_med = ("מעל לחציון" if isr > med else
                           ("מתחת לחציון" if isr < med else "בדיוק בחציון"))
                txt = (f"ב-{iy} נהרגו בישראל {fmt.num_he(isr, 1)} בני אדם {unit_he}: המקום ה-{rank} "
                       f"מתוך {n} המדינות בהשוואה (מהשיעור הגבוה לנמוך), {rel_med} ({fmt.num_he(med, 1)}).")
                hist = by_c[ISRAEL]
                if len(hist) >= 2 and hist[1] is not None and hist[1] > 0:
                    ch = (isr - hist[1]) / hist[1]
                    if abs(ch) >= FLAT_RATE:
                        txt += (f" שנה קודם לכן, ב-{iyears[1]}, עמד השיעור בישראל על "
                                f"{fmt.num_he(hist[1], 1)}.")
                add("intl", txt)

    # ── pedestrians crossing ─────────────────────────────────────────────
    flags["peds"] = False
    if "peds" in tabs:
        p_year, prow = _peds(*tabs["peds"])
        if prow:
            flags["peds"] = True
            charts["peds"] = {"cats": [p[0] for p in prow], "inside": [_r1(p[1]) for p in prow],
                              "outside": [_r1(p[2]) for p in prow]}
            tables["peds"] = [[p[0], fmt.pct_of(p[1]), fmt.pct_of(p[2])] for p in prow]
            yr = f" ב-{p_year}" if p_year else ""
            labels["peds_note"] = (f"הולכי רגל שנפגעו בזמן חציית כביש{yr}, לפי חומרת הפגיעה: "
                                   f"איזה חלק נפגע במעבר חצייה ואיזה מחוצה לו, באחוזים.")
            labels["peds_aria"] = f"הולכי רגל שנפגעו בחציית כביש לפי מקום החצייה וחומרה{yr}"
            killed_row = next((p for p in prow if p[0].startswith("הרוג")), None)
            if killed_row and killed_row[1] >= 40:
                add("peds", f"{fmt.pct_of(killed_row[1])} מהולכי הרגל שנהרגו בחציית כביש{yr} "
                            f"נפגעו בתוך מעבר חצייה.")

    # ── text ─────────────────────────────────────────────────────────────
    release = {"no": rel["RELEASE_NO"], "title": rel["TITLE"], "headline": rel["HEADLINE"],
               "url": rel["PAGE_URL"], "pdf": rel["REPORT_PDF_URL"],
               "date": fmt.d_he(pd.Timestamp(rel["RELEASE_DATE"]))}
    labels["lede"] = (f"כמה בני אדם נהרגו בתאונות דרכים בישראל בכל שנה מאז {ky[0]}, כמה מהתאונות "
                      f"חמורות, וכיצד ישראל נראית לעומת מדינות אחרות. הנתונים השנתיים הסופיים "
                      f"מתוך ההודעה של הלשכה המרכזית לסטטיסטיקה (הלמ\"ס), ומתעדכנים עם כל הודעה "
                      f"שנתית חדשה. בשנת {ly} נהרגו {fmt.int_he(k_last)} בני אדם.")
    summary = (f"הרוגים בתאונות דרכים בישראל לפי שנה, {ky[0]}-{ly}, לפי הנתונים הסופיים של הלמ\"ס: "
               f"{fmt.int_he(k_last)} הרוגים ב-{ly}"
               + (f" ({fmt.signed_pct(k_chg)} לעומת {py})" if k_chg is not None else "") + ".")
    desc = (f"כמה נהרגו בתאונות דרכים בישראל: {fmt.int_he(k_last)} הרוגים ב-{ly}, "
            f"{fmt.int_he(k_prev)} ב-{py}. נתונים שנתיים סופיים מאז {ky[0]}, חומרה והשוואה בין-לאומית.")

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{ky[0]}/{ly}",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "הרוגים בתאונות דרכים בישראל לפי שנה | הלמ\"ס",
                "description": desc,
                "name": "תאונות דרכים עם נפגעים: נתונים שנתיים",
                "alternate_names": ["הרוגים בתאונות דרכים בישראל", "מספר ההרוגים בכבישים לפי שנה",
                                    "תאונות דרכים בישראל נתונים סופיים", "תאונות דרכים בשנת " + str(ly)],
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
