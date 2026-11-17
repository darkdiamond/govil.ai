"""עובדי הוראה במערכת החינוך: CBS's yearly release on teaching staff.

The release's Excel file holds only the data behind its charts ("תרשים N -
..."), and the set changes between editions: the change since 1999/00 in
pupils, classes, teachers and full-time posts by school level (2023, 2025,
2026), the same by sector (2024), and in 2023 also subject-match rates of
Hebrew, maths and English teachers, by level and by the pupils'
socio-economic index. The window holds the last 4 editions; every chart sheet
of every edition is classified by its title text (CBS renumbers sheets), and
each subject is read from the newest edition that carries it. A missing
subject drops its section; a recognised sheet whose header labels are gone
raises.
"""
import re

import pandas as pd
from govlib import cbs, fmt

STEMS = ("t1", "t2", "t3", "t4")
LEVEL_ORDER = ("יסודי", "חטיבת ביניים", "חטיבה עליונה")
SES_ORDER = ("נמוך", "בינוני", "גבוה")
SUBJECTS = ("עברית", "מתמטיקה", "אנגלית")
MEASURES = (  # (key, label in the sheet (contained), Hebrew name)
    ("pupils", "תלמידים", "תלמידים"),
    ("classes", "כיתות", "כיתות"),
    ("teachers", "מורים", "מורים"),
    ("fte", "משר", "משרות מלאות"),
    ("hours", "שעות עבודה", "שעות עבודה"),
)
SCHOOL_YEAR = re.compile(r"(\d{4})/(\d{2})")
# Definite forms after a preposition ("בחטיבת הביניים").
DEF = {"יסודי": "חינוך היסודי", "חטיבת ביניים": "חטיבת הביניים", "חטיבה עליונה": "חטיבה העליונה"}


def _in(level):
    return "ב" + DEF.get(level, level)


def _rkey(no):
    m = re.fullmatch(r"\s*(\d+)\s*/\s*(\d{4})\s*", str(no))
    return (int(m.group(2)), int(m.group(1))) if m else (0, 0)


def _editions(df):
    """[(release_no, release_date, rows)] for one stem, newest first."""
    if df.empty:
        return []
    out = []
    for no in df["RELEASE_NO"].unique():
        sub = df[df["RELEASE_NO"] == no]
        out.append((no, str(sub["RELEASE_DATE"].iloc[0]), cbs.grid(sub, "edition")))
    out.sort(key=lambda e: (e[1], _rkey(e[0]), e[0]), reverse=True)
    return out


def _title(rows):
    for r in rows[:8]:
        for c in r:
            if c.startswith(("תרשים", "לוח")):
                return c
    return ""


def _kind(title):
    if "אחוז השינוי" in title and "שלב חינוך" in title:
        return "level"
    if "אחוז השינוי" in title and "מגזר" in title:
        return "sector"
    if "התאמה למקצוע" in title and "עשירון" in title:
        for s in SUBJECTS:
            if f"להוראת {s}" in title:
                return f"ses:{s}"
        return None
    if "התאמה למקצוע" in title and "שלב חינוך" in title:
        return "match"
    return None


def _span(title):
    """("1999/00", "2023/24") from the title's school-year range."""
    ys = sorted(SCHOOL_YEAR.findall(title))
    if len(ys) < 2:
        raise ValueError(f"no school-year range in {title!r}")
    return f"{ys[0][0]}/{ys[0][1]}", f"{ys[-1][0]}/{ys[-1][1]}"


def _end_year(sy):
    """"2023/24" → 2024 (the calendar year the school year ends)."""
    return int(sy[:4]) + 1


def _pct_scale(vals):
    """Older editions print the change as a fraction (0.88), newer as percent."""
    vals = [v for v in vals if v is not None]
    return 100.0 if vals and max(abs(v) for v in vals) < 5 else 1.0


def _level(rows, title):
    h = None
    for i, r in enumerate(rows):
        if "מורים" in r and "תלמידים" in r:
            h = i
            break
    if h is None:
        raise ValueError("level change: header 'מורים'/'תלמידים' not found")
    cols = {}
    for key, lab, _ in MEASURES:
        for j, c in enumerate(rows[h]):
            if lab in c:
                cols[key] = j
                break
    data = {}
    for r in rows[h + 1:]:
        lab = cbs.cell(r, 0)
        if not lab or lab.startswith(("מקור", "הערה")):
            continue
        vals = {k: cbs.val(r, j) for k, j in cols.items()}
        if all(v is None for v in vals.values()):
            continue
        data[lab] = vals
    if not data:
        return None
    scale = _pct_scale([v for d in data.values() for v in d.values()])
    for d in data.values():
        for k in d:
            d[k] = None if d[k] is None else round(d[k] * scale, 1)
    levels = [lv for lv in LEVEL_ORDER if lv in data] + sorted(lv for lv in data if lv not in LEVEL_ORDER)
    y0, y1 = _span(title)
    return {"levels": levels, "data": data, "measures": [k for k, _, _ in MEASURES if k in cols],
            "y0": y0, "y1": y1}


def _sector(rows, title):
    data, measure = {}, None
    for r in rows:
        m = cbs.cell(r, 0)
        if m:
            measure = next((k for k, lab, _ in MEASURES if lab in m), None)
        sec = cbs.cell(r, 1)
        v = cbs.val(r, 2)
        if measure and sec.startswith("חינוך") and v is not None:
            data.setdefault(sec, {})[measure] = v
    if not data:
        return None
    scale = _pct_scale([v for d in data.values() for v in d.values()])
    for d in data.values():
        for k in d:
            d[k] = round(d[k] * scale, 1)
    sectors = sorted(data, key=lambda s: (0 if "עברי" in s else 1, s))
    present = [k for k, _, _ in MEASURES if any(k in data[s] for s in sectors)]
    y0, y1 = _span(title)
    return {"sectors": sectors, "data": data, "measures": present, "y0": y0, "y1": y1}


def _blocks(rows, header_labels, name):
    """Level blocks of a (level, year, values...) sheet: {level: {year: [v...]}}."""
    h = None
    for i, r in enumerate(rows):
        if all(lab in r for lab in header_labels[:1]) and sum(lab in r for lab in header_labels) >= 2:
            h = i
            break
    if h is None:
        raise ValueError(f"{name}: header {header_labels!r} not found")
    heads = [(j, c) for j, c in enumerate(rows[h]) if c in header_labels]
    out, level = {}, None
    for r in rows[h + 1:]:
        if cbs.cell(r, 0):
            level = cbs.cell(r, 0).replace("חינוך ", "")
        y = cbs.cell(r, 1)
        if level is None or not cbs.YEAR.match(y):
            continue
        vals = {c: cbs.val(r, j) for j, c in heads}
        if all(v is None for v in vals.values()):
            continue
        out.setdefault(level, {})[int(y)] = vals
    return out, [c for _, c in heads]


def _order_levels(levels):
    return [lv for lv in LEVEL_ORDER if lv in levels] + sorted(lv for lv in levels if lv not in LEVEL_ORDER)


def _p1(v):
    return f"{v:.1f}%"


def _signed(v):
    return ("+" if v >= 0 else "−") + f"{abs(v):.1f}%"


def compute(frames):
    rel = cbs.latest_release(frames["releases"])

    # newest edition per kind
    found = {}
    for stem in STEMS:
        for no, date, rows in _editions(frames[stem]):
            kind = _kind(_title(rows))
            if kind is None:
                continue
            title = _title(rows)
            if kind == "level":
                parsed = _level(rows, title)
            elif kind == "sector":
                parsed = _sector(rows, title)
            else:
                labels = SES_ORDER if kind.startswith("ses:") else SUBJECTS
                blocks, heads = _blocks(rows, labels, kind)
                parsed = {"blocks": blocks, "heads": heads} if blocks else None
            if parsed is None:
                continue
            parsed["release"] = no
            parsed["year"] = int(date[:4])
            key = (date, _rkey(no), no)
            if kind not in found or key > found[kind][0]:
                found[kind] = (key, parsed)
    found = {k: v[1] for k, v in found.items()}
    if "level" not in found and "sector" not in found:
        raise ValueError("no change-since-1999/00 sheet in any edition")

    kpis, charts, tables, labels, insights, flags = {}, {}, {}, {}, [], {}
    kpi_order = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    names = {k: n for k, _, n in MEASURES}

    # ── change by level ─────────────────────────────────────────────────
    lv = found.get("level")
    flags["level"] = lv is not None
    if lv:
        levels, d = lv["levels"], lv["data"]
        ms = lv["measures"]
        span = f"{_end_year(lv['y0'])}-{_end_year(lv['y1'])}"
        charts["level"] = {"levels": levels,
                           "series": [{"name": names[m], "data": [d[x].get(m) for x in levels]} for m in ms]}
        tables["level"] = [[x] + [("" if d[x].get(m) is None else _p1(d[x][m])) for m in ms] for x in levels]
        labels["level_cols"] = ["שלב חינוך"] + [names[m] for m in ms]
        labels["level_note"] = (f"אחוז השינוי בין שנת הלימודים {lv['y0']} לשנת הלימודים {lv['y1']}, "
                                f"לפי הודעת {lv['year']}.")
        labels["level_aria"] = (f"תרשים עמודות: אחוז השינוי במספר התלמידים, הכיתות, המורים והמשרות "
                                f"המלאות לפי שלב חינוך, {span}")
        for i, x in enumerate(levels[:3]):
            t = d[x].get("teachers")
            if t is None:
                continue
            k = f"lvl{i}"
            kpis[k] = {"value": t, "display": _p1(t), "tone": "brand"}
            labels[f"{k}_kpi"] = f"גידול במספר המורים {_in(x)}, {span}"
            kpi_order.append(k)

        both = [x for x in levels if d[x].get("teachers") is not None and d[x].get("pupils") is not None]
        if both:
            faster = [x for x in both if d[x]["teachers"] > d[x]["pupils"]]
            if len(faster) == len(both) and len(both) >= 2:
                parts = [f"{_in(x)} {_p1(d[x]['teachers'])} לעומת {_p1(d[x]['pupils'])}"
                         for x in both]
                add("faster", f"בין {lv['y0']} ל-{lv['y1']} גדל מספר המורים מהר יותר ממספר התלמידים "
                              f"בכל שלבי החינוך (גידול המורים לעומת גידול התלמידים): " + ", ".join(parts) + ".")
            top = max(both, key=lambda x: (d[x]["teachers"] - d[x]["pupils"], x))
            ratio = (1 + d[top]["pupils"] / 100) / (1 + d[top]["teachers"] / 100) - 1
            if ratio < -0.05:
                add("ratio", ("הפער הגדול ביותר " if len(both) > 1 else "") + f"{_in(top)}: מספר המורים גדל ב-{_p1(d[top]['teachers'])} "
                             f"ומספר התלמידים ב-{_p1(d[top]['pupils'])}, כך שמספר התלמידים למורה "
                             f"ירד בכ-{_p1(-ratio * 100)}.")
        fte = [x for x in levels if d[x].get("fte") is not None and d[x].get("teachers") is not None]
        less = [x for x in fte if d[x]["fte"] < d[x]["teachers"] - 5]
        if less:
            x = max(less, key=lambda x: (d[x]["teachers"] - d[x]["fte"], x))
            add("fte", f"{_in(x)} גדל מספר המשרות המלאות ב-{_p1(d[x]['fte'])} בלבד, פחות מהגידול במספר "
                       f"המורים ({_p1(d[x]['teachers'])}), כלומר היקף המשרה הממוצע למורה קטן.")

    # ── change by sector ────────────────────────────────────────────────
    sc = found.get("sector")
    flags["sector"] = sc is not None
    if sc:
        secs, d, ms = sc["sectors"], sc["data"], sc["measures"]
        charts["sector"] = {"measures": [names[m] for m in ms],
                            "series": [{"name": s, "data": [d[s].get(m) for m in ms]} for s in secs]}
        tables["sector"] = [[names[m]] + [("" if d[s].get(m) is None else _p1(d[s][m])) for s in secs]
                            for m in ms]
        labels["sector_cols"] = ["מדד"] + secs
        labels["sector_note"] = (f"אחוז השינוי בין שנת הלימודים {sc['y0']} לשנת הלימודים {sc['y1']}, "
                                 f"לפי הודעת {sc['year']}.")
        labels["sector_aria"] = (f"תרשים עמודות: אחוז השינוי לפי מגזר, {_end_year(sc['y0'])}-"
                                 f"{_end_year(sc['y1'])}")
        heb = next((s for s in secs if "עברי" in s), None)
        arb = next((s for s in secs if "ערבי" in s), None)
        if heb and arb and d[heb].get("teachers") is not None and d[arb].get("teachers") is not None:
            a, h = d[arb]["teachers"], d[heb]["teachers"]
            if a > h * 1.2:
                add("sector", f"בחינוך הערבי גדל מספר המורים ב-{_p1(a)} בין {sc['y0']} ל-{sc['y1']}, "
                              f"לעומת {_p1(h)} בחינוך העברי.")
            elif h > a * 1.2:
                add("sector", f"בחינוך העברי גדל מספר המורים ב-{_p1(h)} בין {sc['y0']} ל-{sc['y1']}, "
                              f"לעומת {_p1(a)} בחינוך הערבי.")

    # ── subject match by level ──────────────────────────────────────────
    mt = found.get("match")
    flags["match"] = False
    if mt:
        blocks, subs = mt["blocks"], mt["heads"]
        levels = _order_levels(blocks)
        years = sorted({y for b in blocks.values() for y in b})
        if len(years) >= 2:
            flags["match"] = True
            charts["match"] = {"years": years, "subjects": subs, "panels": [
                {"level": x, "series": [{"name": s, "data": [blocks[x].get(y, {}).get(s) for y in years]}
                                        for s in subs]} for x in levels]}
            rows = []
            for x in levels:
                ys = sorted(blocks[x])
                for s in subs:
                    a, b = blocks[x][ys[0]].get(s), blocks[x][ys[-1]].get(s)
                    rows.append([f"{x}, {s}", "" if a is None else _p1(a), "" if b is None else _p1(b),
                                 "" if a is None or b is None else _signed(b - a).replace("%", "")])
            tables["match"] = rows
            labels["match_cols"] = ["שלב חינוך ומקצוע", str(years[0]), str(years[-1]), "שינוי (נקודות אחוז)"]
            labels["match_note"] = (f"אחוז המורים שמלמדים עברית, מתמטיקה או אנגלית ושהוכשרו להוראת המקצוע, "
                                    f"{years[0]}-{years[-1]}, לפי הודעת {mt['year']}.")
            labels["match_aria"] = f"תרשימי קו: שיעורי התאמה למקצוע לפי שלב חינוך, {years[0]}-{years[-1]}"
            # biggest rise, lowest level
            moves = []
            for x in levels:
                ys = sorted(blocks[x])
                for s in subs:
                    a, b = blocks[x][ys[0]].get(s), blocks[x][ys[-1]].get(s)
                    if a is not None and b is not None:
                        moves.append((b - a, x, s, a, b, ys[0], ys[-1]))
            if moves:
                up = max(moves, key=lambda m: (m[0], m[1], m[2]))
                if up[0] >= 5:
                    add("match_up", f"שיעור ההתאמה למקצוע בקרב המורים ל{up[2]} {_in(up[1])} עלה מ-{_p1(up[3])} "
                                    f"ב-{up[5]} ל-{_p1(up[4])} ב-{up[6]}.")
                low = min(moves, key=lambda m: (m[4], m[1], m[2]))
                if low[4] < 50:
                    add("match_low", f"השיעור הנמוך ביותר: רק {_p1(low[4])} מהמורים המלמדים {low[2]} "
                                     f"{_in(low[1])} הוכשרו להוראת המקצוע ({low[6]}).")

    # ── subject match by socio-economic index ───────────────────────────
    ses = []
    for s in SUBJECTS:
        t = found.get(f"ses:{s}")
        if not t:
            continue
        blocks, groups = t["blocks"], t["heads"]
        levels = _order_levels(blocks)
        ly = max(y for b in blocks.values() for y in b)
        fy = min(y for b in blocks.values() for y in b)
        if ly == fy:
            continue
        ses.append({"subject": s, "subject_in": f"ל{s}", "groups": groups, "levels": levels,
                    "fy": fy, "ly": ly,
                    "aria": f"תרשים עמודות: שיעור ההתאמה למקצוע בהוראת {s} לפי שלב חינוך ואשכול "
                            f"חברתי-כלכלי, {ly}",
                    "series": [{"name": f"אשכול {g}", "data": [blocks[x].get(ly, {}).get(g) for x in levels]}
                               for g in groups],
                    "rows": [[f"{x}, {g}",
                              "" if blocks[x].get(fy, {}).get(g) is None else _p1(blocks[x][fy][g]),
                              "" if blocks[x].get(ly, {}).get(g) is None else _p1(blocks[x][ly][g])]
                             for x in levels for g in groups],
                    "year": t["year"]})
        lo, hi = groups[0], groups[-1]
        gaps = []
        for x in levels:
            a0, b0 = blocks[x].get(fy, {}).get(lo), blocks[x].get(fy, {}).get(hi)
            a1, b1 = blocks[x].get(ly, {}).get(lo), blocks[x].get(ly, {}).get(hi)
            if None not in (a0, b0, a1, b1):
                gaps.append((abs((b0 - a0)) - abs((b1 - a1)), x, b0 - a0, b1 - a1))
        if gaps:
            g = max(gaps, key=lambda m: (m[0], m[1]))
            if g[0] >= 3 and g[2] > 0 and g[3] >= 0:
                add(f"ses_{s}", f"בהוראת {s} {_in(g[1])}, הפער בשיעור ההתאמה למקצוע בין תלמידים ממעמד חברתי-כלכלי "
                                f"{hi} ל{lo} הצטמצם מ-{g[2]:.1f} נקודות אחוז ב-{fy} ל-{g[3]:.1f} ב-{ly}.")
    charts["ses"] = ses
    flags["ses"] = bool(ses)

    if lv:
        lead = max(lv["levels"], key=lambda x: (lv["data"][x].get("teachers") or -1e9, x))
        t = lv["data"][lead].get("teachers")
        fact = f"בין {lv['y0']} ל-{lv['y1']} גדל מספר המורים {_in(lead)} ב-{_p1(t)}" if t is not None else ""
    else:
        fact = ""
    period = (f"{lv['y0']}-{lv['y1']}" if lv else f"{sc['y0']}-{sc['y1']}")
    labels["lede"] = ("כמה מורים מלמדים במערכת החינוך, ואיך השתנה מספרם לעומת מספר התלמידים והכיתות. "
                      "הנתונים מתוך ההודעה השנתית של הלשכה המרכזית לסטטיסטיקה (הלמ\"ס) על עובדי ההוראה, "
                      "ומתעדכנים עם כל הודעה חדשה." + (f" {fact}." if fact else ""))
    summary = (f"עובדי ההוראה במערכת החינוך לפי הלמ\"ס: השינוי במספר המורים, התלמידים והמשרות "
               f"לפי שלב חינוך, {period}." + (f" {fact}." if fact else ""))
    desc = ("מספר המורים במערכת החינוך לעומת התלמידים והכיתות, לפי שלב חינוך ומגזר."
            + (f" {fact}." if fact else f" נתוני הלמ\"ס, {period}."))
    if len(desc) > 150:
        desc = f"מספר המורים במערכת החינוך לעומת התלמידים והכיתות לפי שלב חינוך, {period}. נתוני הלמ\"ס."

    release = {"no": rel["RELEASE_NO"], "title": rel["TITLE"], "headline": rel["HEADLINE"],
               "url": rel["PAGE_URL"], "pdf": rel["REPORT_PDF_URL"],
               "date": fmt.d_he(pd.Timestamp(rel["RELEASE_DATE"]))}
    y_from = _end_year((lv or sc)["y0"])
    y_to = max(_end_year((lv or sc)["y1"]), _end_year(sc["y1"]) if sc else 0)
    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "misc",
            "temporal_coverage": f"{y_from}/{y_to}",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "עובדי הוראה במערכת החינוך | מורים בישראל, נתוני הלמ\"ס",
                "description": desc,
                "name": "עובדי הוראה במערכת החינוך",
                "alternate_names": ["מספר המורים בישראל", "מורים במערכת החינוך",
                                    "עובדי הוראה", "התאמה למקצוע בקרב מורים"],
            },
        },
        "kpis": kpis,
        "kpi_order": kpi_order,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
        "release": release,
        "flags": flags,
    }
