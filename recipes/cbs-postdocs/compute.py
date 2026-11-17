"""חוקרים בבתר-דוקטורט: CBS's yearly release on holders of a doctorate doing
postdoctoral research at Israel's universities.

Each edition carries nine chart-data sheets. They are found by their TITLE
text in any stem (t1..t12, all optional: CBS renumbers sheets between
editions), never by stem:

  trend   מספר חוקרים וחוקרות ...           women/men/foreign/Israeli/total per year
  change  שינוי במספר ... במספרים מוחלטים     change vs the year before, by citizenship x sex
  uni     ... לפי אוניברסיטה, אחוזים          share per university (one year)
  origin  ... זרים ... לפי ארץ מוצא           foreign researchers' country of origin (one year)
  fields  ... וחוקרים זרים לפי תחום מחקר      share of research per field + foreign share in it
  place   ... לפי מקום קבלת התואר השלישי      PhD from Israel / abroad per field
  gap     הפער בין חוקרים לחוקרות (ישראלים)    the published gender gap per field
  us      מינויים למשרת בתר-דוקטורט בארה"ב    US postdoc appointees by citizenship (NSF)

The 2022 edition's "שיעור השינוי" sheet and the Israel-US citizenship sheet
(whose shares the trend and US tables already give) are not read.

The source keeps three editions (history_releases 3): the university and
origin shares are shown for each year they cover. Every other table comes
from the newest edition that has it. The fields and gap sheets changed
their definitions between editions, so they are never mixed across years.

A recognised table whose header labels are gone raises (the layout changed).
No trend table in any edition raises: it is the page's core.
"""
import re

import pandas as pd
from govlib import cbs, fmt

TITLE = re.compile(r"^(?:תרשים|לוח)\s*\d+[א-ת]?\s*-\s*")
TITLE_YEARS = re.compile(r"(?<!\d)((?:19|20)\d\d)(?!\d)")
YEAR = re.compile(r"^((?:19|20)\d\d)")
RELEASE = re.compile(r"(\d+)\s*/\s*(\d{4})")
HEB = re.compile("[א-ת]")
TABLE_STEMS = tuple(f"t{i}" for i in range(1, 13))
OTHER = "ארצות אחרות"
# Insight thresholds.
FLAT_PCT = 1.0      # |change| below this many percent reads as "almost unchanged"
SHARE_PP = 1.0      # a share move below this many points is not worth a sentence
MAJORITY = 50.0     # "most" needs more than half


def _rel_key(no):
    m = RELEASE.search(str(no))
    return (int(m.group(2)), int(m.group(1))) if m else (0, 0)


def _kind(title):
    if "שיעור השינוי" in title:
        return None
    if "שינוי במספר" in title:
        return "change"
    if "מספר חוקרים וחוקרות" in title:
        return "trend"
    if "ארץ מוצא" in title:
        return "origin"
    if "לפי אוניברסיטה" in title:
        return "uni"
    if "מקום קבלת התואר" in title:
        return "place"
    if "הפער בין חוקרים לחוקרות" in title:
        return "gap"
    if "חוקרים זרים לפי תחום" in title:
        return "fields"
    if 'בארה"ב' in title and "ותושבות" in title:
        return "us"
    return None


def _is_total(lab):
    return lab.startswith(("סך הכל", 'סה"כ'))


def _has_number(rows):
    return any(cbs.num(c) is not None for r in rows for c in r)


def _edition_rows(df):
    """{release_no: rows} for every edition in a stacked grid."""
    out = {}
    cols = sorted((c for c in df.columns if re.fullmatch(r"C\d+", c)), key=lambda c: int(c[1:]))
    for no in sorted(df["RELEASE_NO"].unique(), key=lambda n: (_rel_key(n), n)):
        part = df[df["RELEASE_NO"] == no].sort_values(["SHEET_NO", "ROW"], kind="stable")
        out[no] = [[cbs.clean(v) for v in r] for r in part[cols].itertuples(index=False)]
    return out


def _label_values(row):
    """(label, [numbers]) of a data row: the first Hebrew text cell and the
    numbers to its left (the sheets read right to left from C01)."""
    lab, j0 = None, None
    for j, c in enumerate(row):
        if c and HEB.search(c) and cbs.num(c) is None:
            lab, j0 = c, j
            break
    if lab is None:
        return None, []
    return lab, [v for v in (cbs.num(c) for c in row[j0 + 1:]) if v is not None]


def _pairs(rows, start, name):
    """[(label, value)] for rows after `start` with a label and a number."""
    out = []
    for r in rows[start:]:
        lab, vals = _label_values(r)
        if lab and vals and not _is_total(lab):
            out.append((lab, vals[0]))
    if not out and _has_number(rows[start:]):
        raise ValueError(f"{name}: numbers but no labelled rows")
    return out


def _trend(rows, ti, name):
    h = cbs.row_with(rows, "שנה", ti + 1, name=name)
    hdr = rows[h]
    cols = {k: cbs.col_after(hdr, k) for k in ("נשים", "גברים", "זרים", "ישראלים")}
    out = {}
    for r in rows[h + 1:]:
        y = cbs.cell(r, 0)
        if not YEAR.match(y):
            y = next((c for c in r if YEAR.fullmatch(c)), "")
        if not YEAR.fullmatch(y):
            continue
        vals = {k: cbs.val(r, j) for k, j in cols.items()}
        if any(v is None for v in vals.values()):
            continue
        out[int(y)] = {k: int(v) for k, v in vals.items()}
    return out or None


def _change(rows, ti, name):
    """{(group, sex): value} with sex '' for a group total. The sex rows of a
    group come before its 'סה"כ <group>' row; some editions also label the
    group on its first row, others don't, so the total row names the group."""
    out, pending = {}, []
    for r in rows[ti + 1:]:
        texts = [c for c in r if c and cbs.num(c) is None]
        nums = [cbs.num(c) for c in r if cbs.num(c) is not None]
        if not nums:
            continue
        texts = [t for t in texts if t not in ("זרים", "ישראלים")]
        if not texts:
            continue
        lab = texts[0]
        if lab.startswith('סה"כ חוקרים'):
            out[("כולם", "")] = nums[0]
        elif _is_total(lab):
            group = next((g for g in ("זרים", "ישראלים") if g in lab), None)
            if group is None:
                raise ValueError(f"{name}: unknown total row {lab!r}")
            out[(group, "")] = nums[0]
            for sex, v in pending:
                out[(group, sex)] = v
            pending = []
        elif lab in ("גברים", "נשים"):
            pending.append((lab, nums[0]))
    if not out:
        if _has_number(rows[ti + 1:]):
            raise ValueError(f"{name}: change rows not recognised")
        return None
    for g in ("זרים", "ישראלים"):
        for s in ("גברים", "נשים"):
            if (g, s) not in out:
                raise ValueError(f"{name}: change row {g}/{s} not found")
    return out


def _uni(rows, ti, name):
    h = cbs.row_with(rows, "אוניברסיטה", ti + 1, name=name)
    return _pairs(rows, h + 1, name) or None


def _origin(rows, ti, name):
    items = _pairs(rows, ti + 1, name)
    return items or None


def _fields(rows, ti, name):
    h = cbs.row_with(rows, "חוקרים זרים", ti + 1, name=name)
    fcol = cbs.col_after(rows[h], "חוקרים זרים")
    scol = cbs.col_after(rows[h], "סך הכל מחקרים")
    lcol = cbs.best_col(rows[h + 1:], lambda v: bool(HEB.search(v)) and cbs.num(v) is None)
    out = []
    for r in rows[h + 1:]:
        lab, f, s = cbs.cell(r, lcol), cbs.val(r, fcol), cbs.val(r, scol)
        if not lab or f is None or s is None or _is_total(lab):
            continue
        out.append((lab, s, f))
    return out or None


def _place(rows, ti, name):
    h = cbs.row_with(rows, "בישראל", ti + 1, name=name)
    icol = cbs.col_after(rows[h], "בישראל")
    acol = cbs.col_after(rows[h], 'בחו"ל')
    lcol = cbs.best_col(rows[h + 1:], lambda v: bool(HEB.search(v)) and cbs.num(v) is None)
    out = []
    for r in rows[h + 1:]:
        lab, i, a = cbs.cell(r, lcol), cbs.val(r, icol), cbs.val(r, acol)
        if not lab or i is None or a is None or _is_total(lab):
            continue
        out.append((lab, i, a))
    return out or None


def _gap(rows, ti, name):
    """[(field, 'גברים'|'נשים', value)]: the sex column carries down. CBS
    lists the men's block first; one edition printed only the נשים label,
    so rows above a first נשים label are the men's block."""
    sex, out, before = None, [], []
    for r in rows[ti + 1:]:
        texts = [c for c in r if c and cbs.num(c) is None]
        nums = [cbs.num(c) for c in r if cbs.num(c) is not None]
        if texts and texts[0] in ("גברים", "נשים"):
            if sex is None and before:
                if texts[0] != "נשים":
                    raise ValueError(f"{name}: gap rows above a {texts[0]!r} label")
                out.extend((f, "גברים", v) for f, v in before)
                before = []
            sex = texts[0]
            texts = texts[1:]
        if not nums or not texts:
            continue
        if sex is None:
            before.append((texts[0], nums[0]))
        else:
            out.append((texts[0], sex, nums[0]))
    if before:
        raise ValueError(f"{name}: no גברים/נשים label in the gap table")
    return out or None


def _us(rows, ti, name):
    """{year: (total, temporary visa holders)} of US postdoc appointees, or
    None when the edition has the chart only (no data sheet)."""
    try:
        h = cbs.row_with(rows, "Postdoctoral appointees", ti + 1, name=name)
    except ValueError:
        if any(YEAR.fullmatch(c) for r in rows[ti + 1:] for c in r):
            raise
        return None
    pcol = cbs.col_after(rows[h], "Postdoctoral appointees")
    tcol = None
    for r in rows[h + 1:h + 3]:
        for lab in ("Temporary visa holders", "מחזיקי ויזה זמנית"):
            try:
                tcol = cbs.col_after(r, lab, pcol)
                break
            except ValueError:
                continue
        if tcol is not None:
            break
    if tcol is None:
        raise ValueError(f"{name}: 'Temporary visa holders' not found under the postdoc block")
    ycol = cbs.best_col(rows[h + 1:], lambda v: bool(YEAR.match(v)) and len(v) <= 12)
    out = {}
    for r in rows[h + 1:]:
        m = YEAR.match(cbs.cell(r, ycol))
        tot, tmp = cbs.val(r, pcol), cbs.val(r, tcol)
        if m and tot and tmp is not None:
            out[int(m.group(1))] = (tot, tmp)
    return out or None


PARSERS = {"trend": _trend, "change": _change, "uni": _uni, "origin": _origin,
           "fields": _fields, "place": _place, "gap": _gap, "us": _us}


def _collect(frames):
    """{kind: {year: (release_key, table)}}, newest edition per year."""
    out = {k: {} for k in PARSERS}
    for stem in TABLE_STEMS:
        df = frames.get(stem)
        if df is None or df.empty:
            continue
        for no, rows in _edition_rows(df).items():
            ti = next((i for i, r in enumerate(rows) if any(TITLE.match(c) for c in r)), None)
            if ti is None:
                continue
            title = next(c for c in rows[ti] if TITLE.match(c))
            kind = _kind(title)
            if kind is None:
                continue
            ys = [int(y) for y in TITLE_YEARS.findall(title)]
            if not ys:
                raise ValueError(f"{stem} {no}: no year in the title {title!r}")
            year = max(ys)  # "2025-2024" and "2017-2025" both mean the 2025 edition
            if not _has_number(rows[ti + 1:]):
                continue  # only the title (a cut-off sheet): nothing to read
            tab = PARSERS[kind](rows, ti, f"{stem} {no}")
            if tab is None:
                continue
            key = _rel_key(no)
            if year not in out[kind] or out[kind][year][0] < key:
                out[kind][year] = (key, tab)
    return out


def _newest(d):
    """(year, table) from the newest edition in {year: (key, table)}."""
    if not d:
        return None, None
    y = max(d, key=lambda k: (d[k][0], k))
    return y, d[y][1]


def _pct1(v):
    return f"{v:.1f}%"


def _r1(v):
    return round(v, 1)


def _chg(new, old):
    return (new - old) / old * 100 if old else None


def _signed_int(v):
    v = round(v)
    return f"+{fmt.int_he(v)}" if v > 0 else (f"−{fmt.int_he(-v)}" if v < 0 else "0")


def compute(frames):
    rel = cbs.latest_release(frames["releases"])
    data = _collect(frames)
    _, trend = _newest(data["trend"])
    if not trend:
        raise ValueError("no trend table (מספר חוקרים וחוקרות) in any edition")
    years = sorted(trend)
    ly, fy = years[-1], years[0]
    cur = trend[ly]

    def tot(y):
        return trend[y]["זרים"] + trend[y]["ישראלים"]

    total = tot(ly)
    insights, kpis, charts, tables, labels, flags = [], {}, {}, {}, {}, {}

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    # ── trend ────────────────────────────────────────────────────────────
    charts["trend"] = {
        "x": [str(y) for y in years],
        "foreign": [trend[y]["זרים"] for y in years],
        "israeli": [trend[y]["ישראלים"] for y in years],
        "women": [trend[y]["נשים"] for y in years],
        "men": [trend[y]["גברים"] for y in years],
        "total": [tot(y) for y in years],
    }
    tables["trend"] = [[str(y), fmt.int_he(tot(y)), fmt.int_he(trend[y]["ישראלים"]),
                        fmt.int_he(trend[y]["זרים"]), fmt.int_he(trend[y]["נשים"]),
                        fmt.int_he(trend[y]["גברים"])] for y in years]
    span = f"{fy}-{ly}"
    labels["trend_aria"] = f"מספר החוקרים בבתר-דוקטורט לפי אזרחות, {span}"
    labels["gender_aria"] = f"מספר החוקרים והחוקרות בבתר-דוקטורט, {span}"
    labels["trend_note"] = (f"כמה בעלי תואר שלישי עסקו במחקר בתר-דוקטורט באוניברסיטאות בכל שנה "
                            f"({fy} עד {ly}), ישראלים וזרים.")
    labels["gender_note"] = f"מספר הנשים והגברים בבתר-דוקטורט בכל שנה, {fy} עד {ly}."

    kpis["total"] = {"value": total, "display": fmt.int_he(total), "tone": "brand"}
    labels["total_kpi"] = f"חוקרים בבתר-דוקטורט, {ly}"
    fshare = cur["זרים"] / total * 100
    wshare = cur["נשים"] / (cur["נשים"] + cur["גברים"]) * 100
    kpis["foreign"] = {"value": _r1(fshare), "display": _pct1(fshare), "tone": "info"}
    labels["foreign_kpi"] = f"שיעור החוקרים הזרים, {ly}"
    kpis["women"] = {"value": _r1(wshare), "display": _pct1(wshare), "tone": "brand"}
    labels["women_kpi"] = f"שיעור הנשים, {ly}"

    if len(years) > 1:
        py = years[-2]
        c = _chg(total, tot(py))
        kpis["yoy"] = {"value": _r1(c), "display": fmt.signed_pct(c / 100),
                       "tone": "ok" if c >= FLAT_PCT else ("warn" if c <= -FLAT_PCT else "brand")}
        labels["yoy_kpi"] = f"שינוי במספר החוקרים לעומת {py}"
        peak_y = max(years, key=lambda y: (tot(y), y))
        txt = f"ב-{ly} עסקו {fmt.int_he(total)} בעלי תואר שלישי במחקר בתר-דוקטורט באוניברסיטאות"
        if abs(c) < FLAT_PCT:
            txt += f", כמעט ללא שינוי לעומת {py}"
        else:
            txt += f", {'עלייה' if c > 0 else 'ירידה'} של {_pct1(abs(c))} לעומת {py}"
        if peak_y != ly:
            txt += (f". השיא בשנים שבנתונים היה ב-{peak_y}, עם {fmt.int_he(tot(peak_y))} חוקרים, "
                    f"ומאז המספר {'ירד' if total < tot(peak_y) else 'עלה'} ב-"
                    f"{fmt.int_he(abs(tot(peak_y) - total))}")
        else:
            txt += f". זה המספר הגבוה ביותר בשנים שבנתונים ({fy} עד {ly})"
        add("trend", txt + ".")

        # Israelis vs foreign researchers.
        di = cur["ישראלים"] - trend[py]["ישראלים"]
        df_ = cur["זרים"] - trend[py]["זרים"]
        lead = "ישראלים" if cur["ישראלים"] > cur["זרים"] else "זרים"
        earlier = [y for y in years[:-1]
                   if (trend[y]["ישראלים"] > trend[y]["זרים"]) == (lead == "ישראלים")]
        parts = []
        if di * df_ < 0:
            up, dn = ("הישראלים", "הזרים") if di > 0 else ("הזרים", "הישראלים")
            parts.append(f"בין {py} ל-{ly} גדל מספר החוקרים {up} ב-{fmt.int_he(abs(di if di > 0 else df_))}, "
                         f"ואילו מספר החוקרים {dn} קטן ב-{fmt.int_he(abs(df_ if di > 0 else di))}")
        if not earlier and len(years) > 2:
            who = "ישראלים מזרים" if lead == "ישראלים" else "זרים מישראלים"
            parts.append(f"ב-{ly} היו לראשונה בשנים שבנתונים ({fy} עד {ly}) יותר חוקרים {who}: "
                         f"{fmt.int_he(cur['ישראלים'])} ישראלים ו-{fmt.int_he(cur['זרים'])} זרים")
        if parts:
            add("citizenship", ". ".join(parts) + ".")

    w0 = trend[fy]["נשים"] / (trend[fy]["נשים"] + trend[fy]["גברים"]) * 100
    if len(years) > 1:
        if abs(wshare - w0) >= SHARE_PP:
            add("women", f"שיעור הנשים בקרב החוקרים בבתר-דוקטורט {'עלה' if wshare > w0 else 'ירד'} מ-"
                         f"{_pct1(w0)} ב-{fy} ל-{_pct1(wshare)} ב-{ly}: {fmt.int_he(cur['נשים'])} נשים "
                         f"ו-{fmt.int_he(cur['גברים'])} גברים.")
        else:
            add("women", f"הנשים הן {_pct1(wshare)} מהחוקרים בבתר-דוקטורט ב-{ly} "
                         f"({fmt.int_he(cur['נשים'])} נשים ו-{fmt.int_he(cur['גברים'])} גברים), "
                         f"כמעט כמו ב-{fy} ({_pct1(w0)}).")

    # ── change by citizenship and sex ────────────────────────────────────
    cy, change = _newest(data["change"])
    flags["change"] = bool(change) and cy == ly
    if flags["change"]:
        order = [("זרים", "גברים", "גברים זרים"), ("זרים", "נשים", "נשים זרות"),
                 ("ישראלים", "גברים", "גברים ישראלים"), ("ישראלים", "נשים", "נשים ישראליות")]
        charts["change"] = {"names": [o[2] for o in order],
                            "values": [int(change[(g, s)]) for g, s, _ in order]}
        tables["change"] = [[o[2], _signed_int(change[(o[0], o[1])])] for o in order]
        for g, lab in (("זרים", 'סה"כ זרים'), ("ישראלים", 'סה"כ ישראלים'), ("כולם", 'סה"כ חוקרים')):
            if (g, "") in change:
                tables["change"].append([lab, _signed_int(change[(g, "")])])
        labels["change_aria"] = f"שינוי במספר החוקרים בבתר-דוקטורט לפי אזרחות ומין, {years[-2] if len(years) > 1 else ly} עד {ly}"
        labels["change_note"] = (f"בכמה גדל או קטן מספר החוקרים בכל קבוצה בין {years[-2] if len(years) > 1 else ly} "
                                 f"ל-{ly}, במספרים מוחלטים, כפי שפרסמה הלמ\"ס.")

    # ── universities ─────────────────────────────────────────────────────
    uni = {y: v[1] for y, v in data["uni"].items()}
    flags["uni"] = bool(uni)
    if uni:
        uy = sorted(uni)
        u_last = sorted(uni[uy[-1]], key=lambda t: (-t[1], t[0]))
        names = [n for n, _ in u_last]
        per = {y: dict(uni[y]) for y in uy}
        charts["uni"] = {"names": names, "years": [str(y) for y in uy],
                         "series": [[_r1(per[y][n]) if n in per[y] else None for n in names] for y in uy]}
        labels["uni_cols"] = ["אוניברסיטה"] + [str(y) for y in uy]
        tables["uni"] = [[n] + [_pct1(per[y][n]) if n in per[y] else "–" for y in uy] for n in names]
        labels["uni_aria"] = f"חלוקת החוקרים בבתר-דוקטורט לפי אוניברסיטה, {uy[0]} עד {uy[-1]}"
        labels["uni_note"] = (f"באיזו אוניברסיטה עובדים החוקרים: אחוז מכלל החוקרים בבתר-דוקטורט בכל "
                              f"שנה ({', '.join(str(y) for y in uy)}).")
        if len(u_last) >= 3:
            (n1, v1), (n2, v2) = u_last[0], u_last[1]
            top3 = sum(v for _, v in u_last[:3])
            txt = (f"{n1} מעסיקה את החלק הגדול ביותר של החוקרים בבתר-דוקטורט: {_pct1(v1)} ב-{uy[-1]}, "
                   f"ואחריה {n2} עם {_pct1(v2)}. שלוש האוניברסיטאות המובילות מרכזות {_pct1(top3)} מהחוקרים")
            if len(uy) > 1:
                y0 = uy[0]
                moves = [(per[uy[-1]][n] - per[y0][n], n) for n in names if n in per[y0]]
                if moves:
                    d, n = max(moves, key=lambda t: (abs(t[0]), t[1]))
                    if abs(d) >= SHARE_PP * 2:
                        txt += (f". השינוי הבולט מאז {y0}: חלקה של {n} {'עלה' if d > 0 else 'ירד'} מ-"
                                f"{_pct1(per[y0][n])} ל-{_pct1(per[uy[-1]][n])}")
            add("uni", txt + ".")

    # ── foreign researchers' origin ──────────────────────────────────────
    origin = {y: v[1] for y, v in data["origin"].items()}
    flags["origin"] = bool(origin)
    if origin:
        oy = sorted(origin)
        o_last = origin[oy[-1]]
        named = sorted([t for t in o_last if t[0] != OTHER], key=lambda t: (-t[1], t[0]))
        rest = [t for t in o_last if t[0] == OTHER]
        names = [n for n, _ in named] + [n for n, _ in rest]
        per = {y: dict(origin[y]) for y in oy}
        charts["origin"] = {"names": names, "years": [str(y) for y in oy],
                            "series": [[_r1(per[y][n]) if n in per[y] else None for n in names] for y in oy]}
        labels["origin_cols"] = ["ארץ מוצא"] + [str(y) for y in oy]
        tables["origin"] = [[n] + [_pct1(per[y][n]) if n in per[y] else "–" for y in oy] for n in names]
        labels["origin_aria"] = f"החוקרים הזרים בבתר-דוקטורט לפי ארץ מוצא, {oy[0]} עד {oy[-1]}"
        labels["origin_note"] = (f"מאילו ארצות מגיעים החוקרים הזרים: אחוז מכלל החוקרים הזרים בכל שנה. "
                                 f"ארצות קטנות יותר מקובצות ב\"{OTHER}\".")
        if named:
            n1, v1 = named[0]
            txt = f"{n1} היא ארץ המוצא של {_pct1(v1)} מהחוקרים הזרים בבתר-דוקטורט ב-{oy[-1]}"
            if v1 > MAJORITY:
                txt = f"יותר ממחצית החוקרים הזרים בבתר-דוקטורט מגיעים מ{n1}: {_pct1(v1)} ב-{oy[-1]}"
            if len(oy) > 1 and n1 in per[oy[0]] and abs(v1 - per[oy[0]][n1]) >= SHARE_PP:
                txt += f", לעומת {_pct1(per[oy[0]][n1])} ב-{oy[0]}"
            if len(named) > 1:
                txt += f". במקום השני {named[1][0]}, עם {_pct1(named[1][1])}"
            add("origin", txt + ".")
            kpis["origin_top"] = {"value": _r1(v1), "display": _pct1(v1), "tone": "info"}
            labels["origin_top_kpi"] = f"שיעור החוקרים מ{n1} מבין הזרים, {oy[-1]}"

    # ── fields ───────────────────────────────────────────────────────────
    fyr, fields = _newest(data["fields"])
    flags["fields"] = bool(fields)
    if fields:
        fl = sorted(fields, key=lambda t: (-t[1], t[0]))
        charts["fields"] = {"names": [n for n, _, _ in fl], "share": [_r1(s) for _, s, _ in fl],
                            "foreign": [_r1(f) for _, _, f in fl]}
        tables["fields"] = [[n, _pct1(s), _pct1(f)] for n, s, f in fl]
        labels["fields_aria"] = f"החוקרים בבתר-דוקטורט לפי תחום מחקר ושיעור הזרים בכל תחום, {fyr}"
        labels["fields_note"] = (f"באילו תחומים נעשה המחקר: אחוז מכלל מחקרי הבתר-דוקטורט בכל תחום, ולצדו "
                                 f"שיעור החוקרים הזרים בתחום, {fyr}.")
        n1, s1, _ = fl[0]
        hi = max(fl, key=lambda t: (t[2], t[0]))
        lo = min(fl, key=lambda t: (t[2], t[0]))
        txt = f"התחום הגדול ביותר הוא {n1}, עם {_pct1(s1)} ממחקרי הבתר-דוקטורט ב-{fyr}"
        if len(fl) > 1:
            txt += f", ואחריו {fl[1][0]} ({_pct1(fl[1][1])})"
        txt += (f". שיעור החוקרים הזרים הגבוה ביותר הוא ב{hi[0]}: {_pct1(hi[2])}, והנמוך ביותר ב{lo[0]}: "
                f"{_pct1(lo[2])}.")
        add("fields", txt)

    # ── place of PhD ─────────────────────────────────────────────────────
    pyr, place = _newest(data["place"])
    flags["place"] = bool(place)
    if place:
        pl = sorted(place, key=lambda t: (-t[2], t[0]))
        charts["place"] = {"names": [n for n, _, _ in pl], "israel": [_r1(i) for _, i, _ in pl],
                           "abroad": [_r1(a) for _, _, a in pl]}
        tables["place"] = [[n, _pct1(i), _pct1(a)] for n, i, a in pl]
        labels["place_aria"] = f"החוקרים בבתר-דוקטורט לפי מקום קבלת התואר השלישי ותחום מחקר, {pyr}"
        labels["place_note"] = (f"היכן קיבלו החוקרים את התואר השלישי, במוסד אקדמי בישראל או בחו\"ל, "
                                f"באחוזים מהחוקרים בכל תחום, {pyr}.")
        top, bot = pl[0], pl[-1]
        abroad_major = [n for n, _, a in pl if a > MAJORITY]
        txt = (f"ב{top[0]} קיבלו {_pct1(top[2])} מהחוקרים בבתר-דוקטורט את התואר השלישי בחו\"ל, "
               f"השיעור הגבוה ביותר מבין התחומים ב-{pyr}; ב{bot[0]} {_pct1(bot[2])} בלבד")
        if abroad_major:
            txt += (f". ב-{fmt.int_he(len(abroad_major))} מתוך {fmt.int_he(len(pl))} התחומים רוב החוקרים "
                    f"קיבלו את התואר בחו\"ל")
        add("place", txt + ".")

    # ── gender gap by field (Israelis) ───────────────────────────────────
    gyr, gap = _newest(data["gap"])
    flags["gap"] = bool(gap)
    if gap:
        g = sorted(gap, key=lambda t: ((t[2] if t[1] == "גברים" else -t[2]), t[0]))
        charts["gap"] = {"names": [n for n, _, _ in g],
                         "values": [_r1(v if s == "גברים" else -v) for _, s, v in g]}
        tables["gap"] = [[n, "גברים" if s == "גברים" else "נשים", _pct1(v)]
                         for n, s, v in sorted(gap, key=lambda t: (t[1], -t[2], t[0]))]
        labels["gap_aria"] = f"הפער בין חוקרים לחוקרות ישראלים בבתר-דוקטורט לפי תחום מחקר, {gyr}"
        labels["gap_note"] = (f"בכל תחום, בקרב החוקרים הישראלים: לטובת מי הפער בין גברים לנשים, ובכמה "
                              f"אחוזים, כפי שפרסמה הלמ\"ס, {gyr}.")
        men = [t for t in gap if t[1] == "גברים"]
        women = [t for t in gap if t[1] == "נשים"]
        if men and women:
            m1 = max(men, key=lambda t: (t[2], t[0]))
            w1 = max(women, key=lambda t: (t[2], t[0]))
            add("gap", f"בקרב החוקרים הישראלים בבתר-דוקטורט ב-{gyr}, ב-{fmt.int_he(len(women))} תחומים יש יותר "
                       f"נשים וב-{fmt.int_he(len(men))} תחומים יותר גברים. הפער הגדול ביותר לטובת הגברים הוא "
                       f"ב{m1[0]} ({_pct1(m1[2])}), והגדול ביותר לטובת הנשים ב{w1[0]} ({_pct1(w1[2])}).")

    # ── United States comparison ─────────────────────────────────────────
    _, us = _newest(data["us"])
    flags["us"] = bool(us)
    if us:
        uys = sorted(us)
        all_y = sorted(set(uys) | set(years))
        charts["us"] = {
            "x": [str(y) for y in all_y],
            "us": [_r1(us[y][1] / us[y][0] * 100) if y in us else None for y in all_y],
            "il": [_r1(trend[y]["זרים"] / tot(y) * 100) if y in trend else None for y in all_y],
        }
        tables["us"] = [[str(y), fmt.int_he(us[y][0]), fmt.int_he(us[y][1]),
                         _pct1(us[y][1] / us[y][0] * 100),
                         _pct1(trend[y]["זרים"] / tot(y) * 100) if y in trend else "–"]
                        for y in sorted((y for y in uys if y >= fy), reverse=True)]
        labels["us_aria"] = f"שיעור הזרים בבתר-דוקטורט בארה\"ב ובישראל, {uys[0]} עד {all_y[-1]}"
        labels["us_note"] = (f"שיעור מחזיקי ויזה זמנית מבין המינויים לבתר-דוקטורט בארה\"ב במדע, הנדסה "
                             f"ובריאות ({uys[0]} עד {uys[-1]}, נתוני NSF), לצד שיעור החוקרים הזרים "
                             f"באוניברסיטאות בישראל ({fy} עד {ly}). בטבלה השנים שיש בהן נתונים לשתי המדינות.")
        common = [y for y in uys if y in trend]
        if common:
            y = common[-1]
            us_s = us[y][1] / us[y][0] * 100
            il_s = trend[y]["זרים"] / tot(y) * 100
            if abs(us_s - il_s) >= SHARE_PP:
                rel_ = "גבוה" if us_s > il_s else "נמוך"
                add("us", f"ב-{y} היו {_pct1(us_s)} מהמינויים לבתר-דוקטורט בארה\"ב (במדע, הנדסה ובריאות) "
                          f"של מחזיקי ויזה זמנית, שיעור {rel_} משיעור החוקרים הזרים באוניברסיטאות בישראל "
                          f"באותה שנה ({_pct1(il_s)}).")
            else:
                add("us", f"ב-{y} שיעור מחזיקי הוויזה הזמנית בבתר-דוקטורט בארה\"ב ({_pct1(us_s)}) היה "
                          f"קרוב לשיעור החוקרים הזרים באוניברסיטאות בישראל ({_pct1(il_s)}).")

    # ── text ─────────────────────────────────────────────────────────────
    release = {"title": rel["TITLE"], "headline": rel["HEADLINE"], "url": rel["PAGE_URL"],
               "pdf": rel["REPORT_PDF_URL"], "date": fmt.d_he(pd.Timestamp(rel["RELEASE_DATE"]))}
    labels["lede"] = (f"כמה בעלי תואר שלישי עוסקים במחקר בתר-דוקטורט (פוסט-דוקטורט) באוניברסיטאות בישראל, "
                      f"מי הם ובאילו תחומים הם חוקרים. הנתונים מתוך ההודעה השנתית של הלשכה המרכזית לסטטיסטיקה "
                      f"(הלמ\"ס) ומתעדכנים עם כל הודעה חדשה. ב-{ly} עסקו במחקר בתר-דוקטורט "
                      f"{fmt.int_he(total)} חוקרים וחוקרות, {_pct1(fshare)} מהם זרים.")
    summary = (f"חוקרים בבתר-דוקטורט (פוסט-דוקטורט) באוניברסיטאות בישראל לפי הלמ\"ס: {fmt.int_he(total)} "
               f"ב-{ly}, {_pct1(fshare)} זרים ו-{_pct1(wshare)} נשים, לפי תחום, אוניברסיטה וארץ מוצא.")
    desc = (f"כמה חוקרים בפוסט-דוקטורט יש באוניברסיטאות בישראל: {fmt.int_he(total)} ב-{ly}, "
            f"{_pct1(fshare)} זרים. לפי תחום, אוניברסיטה, מין וארץ מוצא.")
    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{fy}/{ly}",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "פוסט-דוקטורט באוניברסיטאות בישראל | הלמ\"ס",
                "description": desc,
                "name": "חוקרים בבתר-דוקטורט (פוסט-דוקטורט) באוניברסיטאות",
                "alternate_names": ["בעלי תואר שלישי שעסקו במחקר בתר-דוקטורט",
                                    "פוסטדוקים בישראל",
                                    "פוסט דוקטורט באוניברסיטאות",
                                    "חוקרים זרים בבתר-דוקטורט"],
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
