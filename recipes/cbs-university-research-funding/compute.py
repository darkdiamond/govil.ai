"""מחקר ופיתוח באוניברסיטאות: CBS's yearly release on university research
with special funding (the "separate budget", תקציב נפרד).

Each edition carries two chart-data sheets, each for ONE year:

  exp   הוצאות למחקרים מתקציב נפרד, לפי סוג הוצאה   thousand NIS per expense type
  fld   מספר מחקרים ... לפי תחום מחקר               number of studies per field

The source keeps three editions (history_releases 3), so the page shows the
last three years side by side. Tables are found by their TITLE text in any
stem (t1..t5, all optional: CBS renumbers sheets between editions), and the
year comes from the end of the title ("..., 2024"): the 2025 edition's
column header still read "2023" for 2024 figures. Of two editions that give
the same year, the newer one wins.

A recognised table whose header labels are gone raises (the layout changed).
An edition with only its title and no rows below it has nothing to read and
is skipped. No exp table at all raises: it is the page's core.
"""
import re
from itertools import pairwise

import pandas as pd
from govlib import cbs, fmt

TITLE = re.compile(r"^(?:תרשים|לוח)\s*\d+[א-ת]?\s*-\s*")
TITLE_YEAR = re.compile(r"((?:19|20)\d\d)\s*$")
RELEASE = re.compile(r"(\d+)\s*/\s*(\d{4})")
HEB = re.compile("[א-ת]")
TOTAL = "סך הכל"
UNDEFINED = "לא מוגדר"
MISC = "שונות"
TABLE_STEMS = ("t1", "t2", "t3", "t4", "t5")
# Insight thresholds.
FLAT_PCT = 1.0          # |change| below this many percent reads as "almost unchanged"
SHARE_PP = 1.0          # a share move below this many points is not worth a sentence
MIN_TYPE_SHARE = 5.0    # growth ranking only among expense types with ≥ this share
MIN_FIELD_MOVE = 50     # a field's change in studies must reach this to be named


def _rel_key(no):
    m = RELEASE.search(str(no))
    return (int(m.group(2)), int(m.group(1))) if m else (0, 0)


def _kind(title):
    if "סוג הוצאה" in title:
        return "exp"
    if "תחום מחקר" in title:
        return "fld"
    return None


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


def _labelled(rows, start, vcol, name):
    """[(label, value)] for rows after `start` with a Hebrew label and a number
    in `vcol`, plus the total row's value (raises when it is missing)."""
    lcol = cbs.best_col(rows[start:], lambda v: bool(HEB.search(v)) and cbs.num(v) is None)
    if lcol is None:
        raise ValueError(f"{name}: no label column")
    items, total = [], None
    for r in rows[start:]:
        lab, v = cbs.cell(r, lcol), cbs.val(r, vcol)
        if not lab or v is None or not HEB.search(lab):
            continue
        if lab == TOTAL:
            total = v
        else:
            items.append((lab, v))
    if total is None:
        raise ValueError(f"{name}: total row {TOTAL!r} not found")
    if not items:
        raise ValueError(f"{name}: no data rows")
    return items, total


def _parse(kind, rows, ti, name):
    """The table below title row `ti`, or None when nothing follows the title."""
    body = rows[ti + 1:]
    if kind == "exp":
        label = 'אלפי ש"ח'
    else:
        label = "מספר מחקרים"
    try:
        h = cbs.row_with(rows, label, ti + 1, name=name)
    except ValueError:
        if _has_number(body):
            raise
        return None
    vcol = cbs.col_after(rows[h], label)
    items, total = _labelled(rows, h + 1, vcol, name)
    return {"items": items, "total": total}


def _collect(frames):
    """{kind: {year: (release_key, table)}}, newest edition per year."""
    out = {"exp": {}, "fld": {}}
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
            m = TITLE_YEAR.search(title)
            if not m:
                raise ValueError(f"{stem} {no}: no year at the end of the title {title!r}")
            year = int(m.group(1))
            tab = _parse(kind, rows, ti, f"{stem} {no}")
            if tab is None:
                continue
            key = _rel_key(no)
            if year not in out[kind] or out[kind][year][0] < key:
                out[kind][year] = (key, tab)
    return {k: {y: v[1] for y, v in sorted(d.items())} for k, d in out.items()}


def _mil(v):
    return round(v / 1000, 1)


def _r1(v):
    return round(v, 1)


def _chg(new, old):
    return (new - old) / old * 100 if old else None


def _pct1(v):
    return f"{v:.1f}%"


def _moved(c):
    """'גדל ב-8.3%' / 'קטן ב-0.9%' / 'כמעט לא השתנה' (a masculine subject)."""
    if abs(c) < FLAT_PCT:
        return "כמעט לא השתנה"
    return f"{'גדל' if c > 0 else 'קטן'} ב-{_pct1(abs(c))}"


def _signed(v):
    return fmt.signed_pct(v / 100) if v is not None else "–"


def compute(frames):
    rel = cbs.latest_release(frames["releases"])
    data = _collect(frames)
    exp, fld = data["exp"], data["fld"]
    if not exp:
        raise ValueError("no expense-type table (סוג הוצאה) in any edition")
    ey = sorted(exp)
    ly, fy = ey[-1], ey[0]
    last = exp[ly]
    tot_last = last["total"]
    insights, kpis, charts, tables, labels, flags = [], {}, {}, {}, {}, {}

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    # ── totals by year ───────────────────────────────────────────────────
    fy_years = sorted(fld)
    years = sorted(set(ey) | set(fy_years))
    charts["total"] = {
        "x": [str(y) for y in years],
        "exp": [_mil(exp[y]["total"]) if y in exp else None for y in years],
        "studies": [int(fld[y]["total"]) if y in fld else None for y in years],
    }
    tables["total"] = []
    for y in years:
        e = exp[y]["total"] if y in exp else None
        n = fld[y]["total"] if y in fld else None
        tables["total"].append([
            str(y),
            fmt.num_he(_mil(e), 1) if e is not None else "–",
            fmt.int_he(n) if n is not None else "–",
            fmt.num_he(_r1(e / n), 1) if e is not None and n else "–",
        ])

    kpis["total"] = {"value": _mil(tot_last), "display": fmt.int_he(tot_last / 1000), "tone": "brand"}
    labels["total_kpi"] = f"הוצאה למחקרים בתקציב נפרד, {ly} (מיליון ש\"ח)"
    prev = ey[-2] if len(ey) > 1 else None
    if prev is not None:
        c = _chg(tot_last, exp[prev]["total"])
        kpis["yoy"] = {"value": _r1(c), "display": _signed(c),
                       "tone": "ok" if c >= FLAT_PCT else ("warn" if c <= -FLAT_PCT else "brand")}
        labels["yoy_kpi"] = f"שינוי בהוצאה לעומת {prev} (מחירים שוטפים)"
        if abs(c) < FLAT_PCT:
            word = f"כמעט ללא שינוי לעומת {prev}"
        else:
            word = f"{'עלייה' if c > 0 else 'ירידה'} של {_pct1(abs(c))} לעומת {prev}"
        txt = (f"ההוצאה של האוניברסיטאות למחקרים בתקציב נפרד הסתכמה ב-{fmt.int_he(tot_last / 1000)} "
               f"מיליון ש\"ח ב-{ly}, {word}")
        totals = [exp[y]["total"] for y in ey]
        if len(ey) >= 3 and all(b > a for a, b in pairwise(totals)):
            txt += (f". ההוצאה עלתה בכל שנה מאז {fy}, ובסך הכל ב-{_pct1(_chg(tot_last, exp[fy]['total']))} "
                    f"(במחירים שוטפים, ללא התאמה לאינפלציה)")
        else:
            txt += " (במחירים שוטפים)"
        add("total", txt + ".")

    # ── expense types ────────────────────────────────────────────────────
    items = sorted(last["items"], key=lambda t: (-t[1], t[0]))
    charts["types"] = {
        "names": [n for n, _ in items],
        "values": [_mil(v) for _, v in items],
        "shares": [_r1(v / tot_last * 100) for _, v in items],
    }
    tables["types"] = [[n, fmt.num_he(_mil(v), 1), _pct1(v / tot_last * 100)] for n, v in items]
    labels["types_aria"] = f"הוצאות למחקרים בתקציב נפרד לפי סוג הוצאה, {ly}"
    labels["types_note"] = (f"על מה הוצאו הכספים ב-{ly}: שכר, מלגות לסטודנטים, ציוד, חומרים, "
                            f"תקורה ועוד, במיליוני ש\"ח ובאחוזים מסך ההוצאה.")
    top_n, top_v = items[0]
    top_share = top_v / tot_last * 100
    txt = f"סעיף ההוצאה הגדול ביותר הוא {top_n}: {_pct1(top_share)} מההוצאה ב-{ly}"
    if len(ey) > 1:
        old = dict(exp[fy]["items"]).get(top_n)
        if old is not None:
            os_ = old / exp[fy]["total"] * 100
            if abs(top_share - os_) >= SHARE_PP:
                txt += f", לעומת {_pct1(os_)} ב-{fy}"
    if len(items) > 1:
        n2, v2 = items[1]
        txt += f". אחריו {n2}, עם {_pct1(v2 / tot_last * 100)}"
    add("top_type", txt + ".")
    kpis["top_share"] = {"value": _r1(top_share), "display": _pct1(top_share), "tone": "info"}
    labels["top_share_kpi"] = f"חלקו של הסעיף הגדול ({top_n}) בהוצאה, {ly}"

    flags["types_years"] = len(ey) > 1
    if flags["types_years"]:
        names = [n for n, _ in items]
        per_year = {y: dict(exp[y]["items"]) for y in ey}
        charts["types_years"] = {
            "names": names,
            "years": [str(y) for y in ey],
            "series": [[_mil(per_year[y][n]) if n in per_year[y] else None for n in names] for y in ey],
        }
        cols = ["סוג הוצאה"] + [str(y) for y in ey] + [f"שינוי {fy}-{ly}"]
        labels["types_years_cols"] = cols
        rows = []
        growth = []
        for n in names:
            vals = [per_year[y].get(n) for y in ey]
            ch = _chg(vals[-1], vals[0]) if vals[0] is not None and vals[-1] is not None else None
            rows.append([n] + [fmt.num_he(_mil(v), 1) if v is not None else "–" for v in vals] + [_signed(ch)])
            if (ch is not None and MISC not in n
                    and per_year[ly][n] / tot_last * 100 >= MIN_TYPE_SHARE):
                growth.append((ch, n, vals[0], vals[-1]))
        tables["types_years"] = rows
        labels["types_years_aria"] = f"הוצאות לפי סוג הוצאה, {fy} עד {ly}"
        labels["types_years_note"] = (f"כל סעיף הוצאה בכל אחת מהשנים {fy} עד {ly}, במיליוני ש\"ח "
                                      f"(מחירים שוטפים).")
        if growth:
            growth.sort(key=lambda t: (-t[0], t[1]))
            g, n, a, b = growth[0]
            if g > 0:
                total_g = _chg(tot_last, exp[fy]["total"])
                add("fast_type",
                    f"ההוצאה על {n} גדלה ב-{_pct1(g)} בין {fy} ל-{ly}, מ-{fmt.int_he(a / 1000)} ל-"
                    f"{fmt.int_he(b / 1000)} מיליון ש\"ח, הגידול המהיר ביותר מבין סעיפי ההוצאה "
                    f"שחלקם {fmt.int_he(MIN_TYPE_SHARE)}% לפחות, לא כולל {MISC} (סך ההוצאה {_moved(total_g)}).")

    # ── research fields ──────────────────────────────────────────────────
    flags["fields"] = bool(fld)
    if fld:
        fly = fy_years[-1]
        fl = fld[fly]
        n_tot = fl["total"]
        fitems = sorted(fl["items"], key=lambda t: (-t[1], t[0]))
        charts["fields"] = {
            "names": [n for n, _ in fitems],
            "values": [int(v) for _, v in fitems],
        }
        tables["fields"] = [[n, fmt.int_he(v), _pct1(v / n_tot * 100)] for n, v in fitems]
        labels["fields_aria"] = f"מספר המחקרים בתקציב נפרד לפי תחום מחקר, {fly}"
        labels["fields_note"] = f"כמה מחקרים בתקציב נפרד התנהלו בכל תחום מחקר ב-{fly}."
        kpis["studies"] = {"value": int(n_tot), "display": fmt.int_he(n_tot), "tone": "brand"}
        labels["studies_kpi"] = f"מחקרים בתקציב נפרד, {fly}"
        if fly in exp:
            avg = exp[fly]["total"] / n_tot
            kpis["avg"] = {"value": _r1(avg), "display": fmt.num_he(_r1(avg), 1), "tone": "brand"}
            labels["avg_kpi"] = f"הוצאה ממוצעת למחקר, {fly} (אלפי ש\"ח)"
            both = [y for y in ey if y in fld]
            if len(both) > 1:
                y0 = both[0]
                a0 = exp[y0]["total"] / fld[y0]["total"]
                c = _chg(avg, a0)
                if abs(c) >= FLAT_PCT:
                    add("avg",
                        f"ההוצאה הממוצעת למחקר {'עלתה' if c > 0 else 'ירדה'} מ-{fmt.num_he(_r1(a0), 1)} "
                        f"אלף ש\"ח ב-{y0} ל-{fmt.num_he(_r1(avg), 1)} אלף ש\"ח ב-{fly} "
                        f"({_signed(c)}): סך ההוצאה {_moved(_chg(exp[fly]['total'], exp[y0]['total']))} "
                        f"ומספר המחקרים {_moved(_chg(n_tot, fld[y0]['total']))}.")
        top3 = fitems[:3]
        if len(top3) == 3:
            s1 = top3[0][1] / n_tot * 100
            s3 = sum(v for _, v in top3) / n_tot * 100
            add("top_field",
                f"התחום עם הכי הרבה מחקרים בתקציב נפרד הוא {top3[0][0]}: {fmt.int_he(top3[0][1])} מחקרים, "
                f"{_pct1(s1)} מכלל המחקרים ב-{fly}. שלושת התחומים המובילים "
                f"({fmt.join_he([n for n, _ in top3])}) מרכזים {_pct1(s3)} מהמחקרים.")
        flags["fields_change"] = len(fy_years) > 1
        if flags["fields_change"]:
            f0 = fy_years[0]
            old = dict(fld[f0]["items"])
            moves = []
            for n, v in fitems:
                if n in old:
                    moves.append((int(v - old[n]), n, old[n], v))
            moves.sort(key=lambda t: (t[0], t[1]))
            charts["fields_change"] = {
                "names": [m[1] for m in moves],
                "values": [m[0] for m in moves],
            }
            labels["fields_change_cols"] = ["תחום מחקר", str(f0), str(fly), "שינוי"]
            tables["fields_change"] = [
                [n, fmt.int_he(a), fmt.int_he(b), (f"+{fmt.int_he(d)}" if d > 0 else
                                                   (f"−{fmt.int_he(-d)}" if d < 0 else "0"))]
                for d, n, a, b in sorted(moves, key=lambda t: (-t[0], t[1]))
            ]
            labels["fields_change_aria"] = f"שינוי במספר המחקרים לפי תחום, {f0} עד {fly}"
            labels["fields_change_note"] = (f"בכמה מחקרים גדל או קטן כל תחום בין {f0} ל-{fly}. "
                                            f"סך המחקרים: {fmt.int_he(fld[f0]['total'])} ב-{f0}, "
                                            f"{fmt.int_he(n_tot)} ב-{fly}.")
            real = [m for m in moves if UNDEFINED not in m[1]]
            up = [m for m in real if m[0] >= MIN_FIELD_MOVE]
            down = [m for m in real if m[0] <= -MIN_FIELD_MOVE]
            parts = []
            if up:
                d, n, a, b = max(up, key=lambda t: (t[0], t[1]))
                parts.append(f"מספר המחקרים בתחום {n} גדל ב-{fmt.int_he(d)} בין {f0} ל-{fly}, "
                             f"מ-{fmt.int_he(a)} ל-{fmt.int_he(b)} ({_signed(_chg(b, a))})")
            if down:
                d, n, a, b = min(down, key=lambda t: (t[0], t[1]))
                if up:
                    parts.append(f"ואילו בתחום {n} נרשמה ירידה של {fmt.int_he(-d)} מחקרים, "
                                 f"מ-{fmt.int_he(a)} ל-{fmt.int_he(b)}")
                else:
                    parts.append(f"מספר המחקרים בתחום {n} קטן ב-{fmt.int_he(-d)} בין {f0} ל-{fly}, "
                                 f"מ-{fmt.int_he(a)} ל-{fmt.int_he(b)}")
            if parts:
                txt = parts[0] + (", " + parts[1] if len(parts) > 1 else "")
                cn = _chg(n_tot, fld[f0]["total"])
                if abs(cn) < FLAT_PCT:
                    txt += ". סך המחקרים כמעט לא השתנה."
                else:
                    txt += f". סך המחקרים {'גדל' if cn > 0 else 'קטן'} ב-{_pct1(abs(cn))}."
                add("field_move", txt)

    # ── text ─────────────────────────────────────────────────────────────
    release = {"title": rel["TITLE"], "headline": rel["HEADLINE"], "url": rel["PAGE_URL"],
               "pdf": rel["REPORT_PDF_URL"], "date": fmt.d_he(pd.Timestamp(rel["RELEASE_DATE"]))}
    span = f"{years[0]} עד {years[-1]}" if len(years) > 1 else str(years[0])
    labels["total_aria"] = f"הוצאות למחקרים בתקציב נפרד, {span}"
    labels["total_note"] = (f"סך ההוצאה למחקרים בתקציב נפרד בכל שנה ({span}), במיליוני ש\"ח במחירים שוטפים, "
                            f"בטבלה גם מספר המחקרים וההוצאה הממוצעת למחקר.")
    studies_txt = (f" ב-{fy_years[-1]} התנהלו {fmt.int_he(fld[fy_years[-1]]['total'])} מחקרים כאלה."
                   if fld else "")
    labels["lede"] = (f"כמה כסף מוציאות האוניברסיטאות בישראל על מחקרים בעלי מימון מיוחד, שמנוהלים בתקציב "
                      f"נפרד מהתקציב הרגיל, על מה הכסף הולך ובאילו תחומים נעשים המחקרים. הנתונים מתוך "
                      f"ההודעה השנתית של הלשכה המרכזית לסטטיסטיקה (הלמ\"ס) ומתעדכנים עם כל הודעה חדשה. "
                      f"ב-{ly} הסתכמה ההוצאה ב-{fmt.int_he(tot_last / 1000)} מיליון ש\"ח.{studies_txt}")
    summary = (f"הוצאות האוניברסיטאות בישראל למחקרים בתקציב נפרד לפי הלמ\"ס: "
               f"{fmt.int_he(tot_last / 1000)} מיליון ש\"ח ב-{ly}"
               + (f" ו-{fmt.int_he(fld[fy_years[-1]]['total'])} מחקרים" if fld else "")
               + ", לפי סוג הוצאה ותחום מחקר.")
    desc = (f"כמה מוציאות האוניברסיטאות בישראל על מחקרים במימון מיוחד: {fmt.int_he(tot_last / 1000)} "
            f"מיליון ש\"ח ב-{ly}"
            + (f", {fmt.int_he(fld[fy_years[-1]]['total'])} מחקרים" if fld else "")
            + ". לפי סוג הוצאה ותחום מחקר.")
    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "misc",
            "temporal_coverage": f"{years[0]}/{years[-1]}",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "מחקר באוניברסיטאות: הוצאות ותחומי מחקר | הלמ\"ס",
                "description": desc,
                "name": "הוצאות האוניברסיטאות למחקרים בתקציב נפרד",
                "alternate_names": ["מחקר ופיתוח באוניברסיטאות בישראל",
                                    "מחקרים בעלי מימון מיוחד באוניברסיטאות",
                                    "תקציב מחקר באוניברסיטאות",
                                    "מימון מחקר באוניברסיטאות"],
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
