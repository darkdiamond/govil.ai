"""דרישות בטיחות אש לרישוי עסקים: the fire-safety requirements that the Israel
Fire and Rescue Authority (כבאות והצלה לישראל) attaches to each licensing item of
צו רישוי עסקים.

The dataset publishes a full snapshot roughly monthly as a NEW resource
("... נכון ליום DD-MM-YYYY"); 41 snapshots exist (2018 onward). They are the same
table at different dates, not parts of one table, so the recipe reads ONE
snapshot (`pick: "latest"`: the newest resource that has the table's columns)
and never concatenates them. Earlier
snapshots also differ in number formatting (leading zeros dropped), so a
snapshot-to-snapshot diff would mostly measure formatting noise.

One row = one requirement attached to one classification path:
group (CategoryCode1, 10 groups) -> licensing item (CategoryCode2, e.g. 1.01
בית מרקחת) -> sub-item (CategoryCode3, e.g. "01.01 א") -> optional deeper splits
by size/occupancy (CategoryCode4..7). A requirement is identified by its number
plus its text (a few numbers carry two texts). Requirements whose text starts
with "אישור" are certificates the business submits (inspections, lab reports);
the rest are installations / arrangements. Topics come from a keyword map over
the requirement text, first match wins, unmatched -> "אחר".

Everything here aggregates; no row reaches the page. No people are named (the
data holds none).
"""
import re

import pandas as pd

MINUS = "−"

TOPICS = [
    ("מטפים", ["מטפה", "מטפים"]),
    ("ספרינקלרים וכיבוי אוטומטי", [
        "ספרינקלר", "מתזי", "מתזים", "מתז ", "כיבוי אוטומטי", "כיבוי אש אוטומטי",
        "אוטומטית לכיבוי", "מערכת כיבוי", "כיבוי במים", "קצף"]),
    ("עמדות כיבוי, ברזים ומים", [
        "גלגילון", "עמדת כיבוי", "עמדות כיבוי", "ברז כיבוי", "ברזי כיבוי", "ארון כיבוי",
        "הסנקה", "זרנוק", "מאגר מים", "תותח מים", "טבעת היקפית", "רשת מים", "רשת המים",
        "משאבות", "משאבה", "אספקת המים", "כמויות המים"]),
    ("גילוי אש, התרעה וכריזה", [
        "גילוי", "גלאי", "כריזה", "כריזת", "אזעקה", "התרעה", "לוח פיקוד", "משטר הפעלות",
        "אינטגרציה", "טלפון כבאים"]),
    ("שליטה בעשן, אוורור ומנדפים", [
        "עשן", "מנדפ", "פליטה", "מיזוג", "אוורור", "ארובה", "ארובות", "יניקת אוויר"]),
    ("חשמל וגנרטור", ["חשמל", "גנרטור", "מפסק", "מוגן התפוצצות", "ציוד חימום"]),
    ("גז, דלק וחומרים מסוכנים", [
        "גז", "גפ\"מ", "גפ''מ", "גט\"ד", "חומרים מסוכנים", "רעלים", "אמוניה", "דלק",
        "נוזלים דליקים", "מפעלים מסוכנים", "תיק מפעל", "מיכל", "מכלים", "מאצרה",
        "זיקוק", "פירוטכני", "צמיג"]),
    ("שילוט ותאורת חירום", ["שילוט", "שלטים", "שלט ", "תאורת חירום", "תאורה"]),
    ("יציאות, דלתות ודרכי גישה", [
        "יציאה", "יציאות", "דלת", "פתחים", "פתח ", "דרך גישה", "דרכי גישה", "ידית בהלה",
        "מעלית", "חילוץ", "מעבר", "מדרגות", "תפוסה", "מילוט", "פינוי"]),
    ("הפרדות אש וחומרי בנייה", [
        "הפרדה", "הפרדות", "יופרד", "אגף אש", "חומרי בניה", "חומרי בנייה", "חומרי ציפוי",
        "921", "דליקות", "עמידות אש", "יריעה", "אוהל", "קירות", "מחיצות"]),
    ("תיק שטח, הדרכה ונהלים", [
        "תיק שטח", "תיק השטח", "הדרכה", "הדרכת", "סקר", "צוות חירום", "צוות החרום", "נוהל",
        "נהלים", "ממונה", "נאמן", "תוכנית", "תכנית", "עשבים", "פסולת דליקה", "נקי מצמחים"]),
]
OTHER = "אחר"
TOPIC_ORDER = [t for t, _ in TOPICS] + [OTHER]
KIND_REQ, KIND_CERT = "דרישת התקנה או הסדר", "אישור להגשה"

NO_SOURCE = "מקור לא צוין"
TOP_SOURCES = 10
TOP_ITEMS = 15
TOP_PATHS = 12
TOP_COMMON = 12
SHORT = 44                      # chart category labels are cut to this many characters
DIR_DESC = 90                   # directory item names are cut to this many characters
HIST_BINS = [(1, 5), (6, 10), (11, 15), (16, 20), (21, 30), (31, 40), (41, 50), (51, 60), (61, 80)]
LEADER_GAP = 1.15               # leading group must exceed the runner-up by this factor
LIFT_MIN = 1.8                  # a topic counts as typical of a group at this multiple of its overall share
LIFT_MIN_SHARE = 0.10           # ... and when it is at least this share of the group's rows
REMARK_GAP_PP = 5.0             # remark-share spread below this many points reads as uniform
NO_SOURCE_MIN = 0.10            # mention unattributed rows when at least this share

_WS = re.compile(r"\s+")
_NUM = re.compile(r"\d+")
_TI = re.compile("ת['\"׳״]{1,2}י\\s*")


def _clean(s):
    return _WS.sub(" ", s or "").strip()


def _int(v):
    return f"{int(v):,}"


def _pct(v, d=1):
    return f"{v * 100:.{d}f}%"


def _short(s, n=SHORT):
    s = _clean(s)
    if len(s) <= n:
        return s
    cut = s[:n].rsplit(" ", 1)[0]
    return (cut if len(cut) >= n // 2 else s[:n]).rstrip(" ,.-:;") + "…"


def _pad_item(code):
    """CategoryCode2 is numeric in the datastore, so "10.10" arrives as "10.1"."""
    return code + "0" if re.fullmatch(r"\d+\.\d", code) else code


def _req_label(desc):
    """Requirement text for a label: the part before an inline note, Hebrew gershayim."""
    head = _clean(desc.split("הערה:")[0]) or _clean(desc)
    return head.replace('"', "\u05f4").rstrip(" .")


def _code_key(code):
    nums = tuple(int(x) for x in _NUM.findall(code))
    return (nums, code)


def _topic(text):
    for name, kws in TOPICS:
        for k in kws:
            if k in text:
                return name
    return OTHER


def _source(s):
    s = _clean(s)
    if s in ("", "NULL"):
        return NO_SOURCE
    if len(s) > 60 or '"' in s:
        return OTHER          # CSV-quoting debris that spilled requirement text into this column
    s = _clean(_TI.sub("", s))
    s = s.replace("תקן ישראלי / תקן זר מוכר", "תקן ישראלי או תקן זר מוכר")
    s = s.replace("תקן ישראלי/ תקן זר מוכר", "תקן ישראלי או תקן זר מוכר")
    return s


def _ranked(series):
    vc = series.value_counts()
    return vc.sort_index().sort_values(ascending=False, kind="stable")


def _mode_name(frame, key, val):
    """Most frequent (cleaned) description per code, ties broken alphabetically."""
    g = frame[frame[val] != ""].groupby([key, val]).size().reset_index(name="n")
    g = g.sort_values([key, "n", val], ascending=[True, False, True], kind="stable")
    return dict(zip(g.drop_duplicates(key)[key], g.drop_duplicates(key)[val]))


def _group_short(desc):
    s = re.sub(r"^קבוצה\s*\d+\s*-\s*", "", desc)
    return _clean(s.split(",")[0]) or desc


def _plural(n, one, many):
    return one if n == 1 else f"{_int(n)} {many}"


# ── preparation ──────────────────────────────────────────────────────────


def _prepare(raw):
    df = raw.copy()
    for c in df.columns:
        df[c] = df[c].map(_clean)
    df = df[df["RequirementDesc"] != ""].copy()
    df["CategoryCode2"] = df["CategoryCode2"].map(_pad_item)
    for c in [f"CategoryDesc{i}" for i in range(1, 8)]:
        df[c] = df[c].str.rstrip(" -").str.strip()
    codes = [f"CategoryCode{i}" for i in range(1, 8)]
    df["path"] = df[codes].apply(lambda r: "|".join(x for x in r if x), axis=1)
    df["depth"] = (df[codes[1:]] != "").sum(axis=1)
    descs = [f"CategoryDesc{i}" for i in range(3, 8)]
    leaf = df["CategoryDesc2"].copy()
    for c in descs:
        leaf = leaf.where(df[c] == "", df[c])
    df["leaf_desc"] = leaf
    df["req"] = df["RequirementNumber"] + "\u0001" + df["RequirementDesc"]
    df["topic"] = df["RequirementDesc"].map(_topic)
    df["kind"] = [KIND_CERT if d.startswith("אישור") else KIND_REQ for d in df["RequirementDesc"]]
    df["has_remark"] = ~df["Remarks"].isin(["", "NULL"])
    df["source"] = df["REQUIREMENT_SOURCE_DESC"].map(_source)
    df["g"] = df["CategoryCode1"]
    return df


# ── insight rules ────────────────────────────────────────────────────────


def insight_leader(grp):
    if len(grp) < 2:
        return None
    a, b = grp.iloc[0], grp.iloc[1]
    if a["rows"] < b["rows"] * LEADER_GAP:
        return None
    return (f"{a['name']} מרכזת את מספר שיוכי הדרישות הגדול ביותר: {_int(a['rows'])} "
            f"({_pct(a['share'])} מכלל המאגר), ב-{_int(a['items'])} פריטי רישוי. "
            f"אחריה {b['name']} עם {_int(b['rows'])}.")


def insight_certs(df):
    n = len(df)
    c = int((df["kind"] == KIND_CERT).sum())
    if n == 0 or c == 0:
        return None
    share = c / n
    return (f"{_pct(share)} מהשיוכים ({_int(c)}) אינם התקנה אלא אישור שבעל העסק מגיש, "
            f"כמו אישור חברה בתו תקן או אישור מעבדה מוכרת על תקינות מערכת.")


def insight_common(common, n_paths):
    if not common or n_paths < 20:
        return None
    top = common[0]
    share = top["paths"] / n_paths
    if share < 0.2:
        return None
    return (f"הדרישה הנפוצה ביותר, \"{_short(top['full'], 60)}\", מופיעה ב-{_int(top['paths'])} "
            f"מתוך {_int(n_paths)} סיווגי עסק ({_pct(share)}).")


def insight_top_item(items):
    if len(items) < 5:
        return None
    top = items.iloc[0]
    med = float(items["reqs"].median())
    if top["reqs"] < med * 1.5:
        return None
    return (f"פריט הרישוי עם מגוון הדרישות הרחב ביותר הוא {top['code']} ({_short(top['name'], 50)}): "
            f"{_int(top['reqs'])} דרישות שונות על פני {_plural(int(top['paths']), 'סיווג אחד', 'סיווגים')}, "
            f"לעומת חציון של {med:,.0f} לפריט.")


def insight_topic_lift(df, gnames):
    overall = df["topic"].value_counts(normalize=True)
    best = None
    for g, sub in df.groupby("g", sort=True):
        if len(sub) < 200:
            continue
        sh = sub["topic"].value_counts(normalize=True)
        for t, v in sh.items():
            if t == OTHER or v < LIFT_MIN_SHARE:
                continue
            lift = v / overall[t]
            key = (lift, v, g, t)
            if lift >= LIFT_MIN and (best is None or key > best[0]):
                best = (key, g, t, v, overall[t])
    if best is None:
        return None
    _, g, t, v, o = best
    return (f"ב{gnames[g]} נושא \"{t}\" מהווה {_pct(v)} מהדרישות, "
            f"פי {v / o:.1f} מחלקו בכלל המאגר ({_pct(o)}).")


def insight_remarks(df, gnames):
    n = len(df)
    if n == 0:
        return None
    share = float(df["has_remark"].mean())
    by = df.groupby("g")["has_remark"].agg(["mean", "size"])
    by = by[by["size"] >= 100]
    if share < 0.05:
        return None
    text = (f"ל-{_pct(share)} מהשיוכים מצורפת הערה שמסייגת את הדרישה, למשל לפי שטח העסק "
            f"או מועד התקנת המערכת.")
    if len(by) >= 2:
        by = by.reset_index().sort_values(["mean", "g"], ascending=[False, True], kind="stable")
        hi, lo = by.iloc[0], by.iloc[-1]
        if (hi["mean"] - lo["mean"]) * 100 >= REMARK_GAP_PP:
            text += (f" השיעור הגבוה ביותר ב{gnames[hi['g']]} ({_pct(hi['mean'])}) והנמוך "
                     f"ביותר ב{gnames[lo['g']]} ({_pct(lo['mean'])}).")
    return text


def insight_sources(src, n):
    named = src[(src.index != NO_SOURCE) & (src.index != OTHER)]
    if named.empty or n == 0:
        return None
    top, v = named.index[0], int(named.iloc[0])
    text = f"המקור הנורמטיבי הנפוץ ביותר לדרישות הוא {top}, עם {_int(v)} שיוכים ({_pct(v / n)})."
    miss = int(src.get(NO_SOURCE, 0))
    if miss / n >= NO_SOURCE_MIN:
        text += f" ל-{_pct(miss / n)} מהשיוכים לא צוין מקור."
    return text


def insight_depth(path_depth):
    n = len(path_depth)
    if n < 20:
        return None
    deep = int((path_depth >= 3).sum())
    if deep == 0:
        return None
    return (f"{_int(deep)} מתוך {_int(n)} הסיווגים ({_pct(deep / n)}) מפוצלים מתחת לרמת תת-הפריט, "
            f"בדרך כלל לפי שטח העסק, תפוסה או סוג המבנה, ולכל פיצול רשימת דרישות משלו.")


# ── compute ──────────────────────────────────────────────────────────────


def compute(frames):
    df = _prepare(frames["main"])
    n = int(len(df))

    gdesc = _mode_name(df, "g", "CategoryDesc1")
    gcodes = sorted(df["g"].unique(), key=_code_key)
    gnames = {g: _clean(re.sub(r"\s*-\s*", ": ", gdesc.get(g, f"קבוצה {g}"), count=1)) for g in gcodes}
    gshort = {g: _group_short(gdesc.get(g, g)) for g in gcodes}
    inames = _mode_name(df, "CategoryCode2", "CategoryDesc2")

    paths = df.drop_duplicates("path")
    n_paths = int(len(paths))
    n_items = int(df.loc[df["CategoryCode2"] != "", "CategoryCode2"].nunique())
    n_reqs = int(df["req"].nunique())
    n_groups = len(gcodes)
    kinds = [KIND_REQ, KIND_CERT]

    # ---- by group (stacked by kind)
    grows = []
    for g in gcodes:
        sub = df[df["g"] == g]
        grows.append({
            "g": g, "name": gnames[g], "short": gshort[g], "rows": int(len(sub)),
            "share": len(sub) / n if n else 0.0,
            "items": int(sub.loc[sub["CategoryCode2"] != "", "CategoryCode2"].nunique()),
            "paths": int(sub["path"].nunique()), "reqs": int(sub["req"].nunique()),
            "certs": int((sub["kind"] == KIND_CERT).sum()),
            "remark": float(sub["has_remark"].mean()) if len(sub) else 0.0,
        })
    grp = pd.DataFrame(grows).sort_values(["rows", "g"], ascending=[False, True], kind="stable")
    grp["gk"] = grp["g"].map(_code_key)
    rg = grows[::-1]          # horizontal bars draw bottom-up: group 1 on top
    by_group = {
        "y": [r["short"] for r in rg],
        "full": [r["name"] for r in rg],
        "series": [
            {"name": KIND_REQ, "data": [r["rows"] - r["certs"] for r in rg]},
            {"name": KIND_CERT, "data": [r["certs"] for r in rg]},
        ],
    }
    t_group = [{"name": r["name"], "rows": _int(r["rows"]), "n_items": _int(r["items"]),
                "paths": _int(r["paths"]), "reqs": _int(r["reqs"]), "certs": _pct(r["certs"] / r["rows"] if r["rows"] else 0),
                "remark": _pct(r["remark"])} for r in grows]

    # ---- licensing items
    it = df[df["CategoryCode2"] != ""].groupby("CategoryCode2").agg(
        g=("g", "first"), rows=("req", "size"), reqs=("req", "nunique"), paths=("path", "nunique"),
        certs=("kind", lambda s: int((s == KIND_CERT).sum())),
    ).reset_index().rename(columns={"CategoryCode2": "code"})
    it["name"] = it["code"].map(lambda c: inames.get(c, c))
    it["ck"] = it["code"].map(_code_key)
    items = it.sort_values(["reqs", "ck"], ascending=[False, True], kind="stable").reset_index(drop=True)
    top_items = items.head(TOP_ITEMS)
    ch_items = {
        "y": [f"{r.code} {_short(r.name, 34)}" for r in top_items.itertuples()][::-1],
        "full": [f"{r.code} {r.name}" for r in top_items.itertuples()][::-1],
        "reqs": [int(v) for v in top_items["reqs"]][::-1],
        "paths": [int(v) for v in top_items["paths"]][::-1],
    }
    t_items = [{"name": f"{r.code} {_short(r.name, 70)}", "reqs": _int(r.reqs), "paths": _int(r.paths)}
               for r in top_items.itertuples()]

    directory = []
    for g in gcodes:
        sub = it[it["g"] == g].sort_values("ck", kind="stable")
        if sub.empty:
            continue
        directory.append({
            "group": gnames[g],
            "rows": [{"code": r.code, "name": _short(r.name, DIR_DESC), "paths": _int(r.paths),
                       "reqs": _int(r.reqs), "certs": _int(r.certs)} for r in sub.itertuples()],
        })

    # ---- per-classification counts (distribution + most demanding)
    pp = df.groupby("path").agg(reqs=("req", "nunique"), depth=("depth", "first"),
                                code2=("CategoryCode2", "first"), leaf=("leaf_desc", "first"),
                                g=("g", "first")).reset_index()
    med_path = float(pp["reqs"].median()) if len(pp) else 0.0
    hist_x, hist_y = [], []
    top_bin = HIST_BINS[-1][1]
    for lo, hi in HIST_BINS:
        hist_x.append(f"{lo}-{hi}")
        hist_y.append(int(((pp["reqs"] >= lo) & (pp["reqs"] <= hi)).sum()))
    over = int((pp["reqs"] > top_bin).sum())
    if over:
        hist_x.append(f"{top_bin + 1}+")
        hist_y.append(over)
    hist_mode = hist_x[max(range(len(hist_y)), key=lambda i: (hist_y[i], -i))] if hist_y else ""
    t_hist = [{"name": x, "n": _int(y)} for x, y in zip(hist_x, hist_y)]

    pp["key"] = pp["path"].map(lambda p: tuple(_code_key(c) for c in p.split("|")))
    tp = pp.sort_values(["reqs", "key"], ascending=[False, True], kind="stable").head(TOP_PATHS)
    tp_last = [p.split("|")[-1] for p in tp["path"]]
    ch_paths = {
        "y": [f"{c} {_short(l, 30)}" for c, l in zip(tp_last, tp["leaf"])][::-1],
        "full": [f"{c}: {inames.get(i, '')} / {_short(l, 120)}" for c, i, l in zip(tp_last, tp["code2"], tp["leaf"])][::-1],
        "reqs": [int(v) for v in tp["reqs"]][::-1],
    }
    t_paths = [{"name": f"{c} {_short(l, 70)}", "reqs": _int(r)}
               for c, l, r in zip(tp_last, tp["leaf"], tp["reqs"])]

    # ---- topics x kind
    tk = df.groupby(["topic", "kind"]).size()
    topic_tot = df["topic"].value_counts()
    torder = sorted([t for t in TOPIC_ORDER if t in topic_tot.index and t != OTHER],
                    key=lambda t: (-int(topic_tot[t]), TOPIC_ORDER.index(t)))
    if OTHER in topic_tot.index:
        torder.append(OTHER)
    tr = torder[::-1]
    ch_topics = {
        "y": tr,
        "series": [{"name": k, "data": [int(tk.get((t, k), 0)) for t in tr]} for k in kinds],
    }
    t_topics = [{"name": t, "rows": _int(topic_tot[t]), "share": _pct(topic_tot[t] / n),
                 "certs": _int(tk.get((t, KIND_CERT), 0))} for t in torder]

    # ---- heatmap: topic share within each group
    cells, t_heat = [], []
    gt = df.groupby(["g", "topic"]).size()
    gsize = df.groupby("g").size()
    hmax = 0.0
    for xi, g in enumerate(gcodes):
        for yi, t in enumerate(tr):
            c = int(gt.get((g, t), 0))
            v = round(c / int(gsize[g]) * 100, 1) if int(gsize[g]) else 0.0
            hmax = max(hmax, v)
            cells.append([xi, yi, v, c])
    for g in gcodes:
        t_heat.append({"name": gshort[g], "vals": [_pct(int(gt.get((g, t), 0)) / int(gsize[g])) for t in torder]})
    ch_heat = {"x": [gshort[g] for g in gcodes], "xfull": [gnames[g] for g in gcodes],
               "y": tr, "cells": cells, "max": round(hmax, 1)}

    # ---- most common requirements (by classifications reached)
    cr = df.groupby("req").agg(paths=("path", "nunique"), desc=("RequirementDesc", "first"),
                               num=("RequirementNumber", "first")).reset_index()
    cr = cr.sort_values(["paths", "num", "desc"], ascending=[False, True, True], kind="stable").head(TOP_COMMON)
    common = [{"full": _req_label(d), "num": m, "paths": int(p)} for d, m, p in zip(cr["desc"], cr["num"], cr["paths"])]
    ch_common = {
        "y": [_short(c["full"], 36) for c in common][::-1],
        "full": [_short(c["full"], 160) for c in common][::-1],
        "num": [c["num"] for c in common][::-1],
        "share": [round(c["paths"] / n_paths * 100, 1) if n_paths else 0 for c in common][::-1],
        "paths": [c["paths"] for c in common][::-1],
    }
    t_common = [{"name": _short(c["full"], 90), "num": c["num"], "paths": _int(c["paths"]),
                 "share": _pct(c["paths"] / n_paths if n_paths else 0)} for c in common]

    # ---- sources
    src = _ranked(df["source"])
    named = [s for s in src.index if s not in (NO_SOURCE, OTHER)]
    keep = named[:TOP_SOURCES]
    rest = int(src[[s for s in src.index if s not in keep and s != NO_SOURCE]].sum())
    s_rows = [{"name": s, "value": int(src[s])} for s in keep]
    if rest:
        s_rows.append({"name": OTHER, "value": rest})
    if NO_SOURCE in src.index:
        s_rows.append({"name": NO_SOURCE, "value": int(src[NO_SOURCE])})
    ch_src = {"y": [r["name"] for r in s_rows][::-1], "v": [r["value"] for r in s_rows][::-1],
              "muted": [r["name"] in (OTHER, NO_SOURCE) for r in s_rows][::-1]}
    t_src = [{"name": r["name"], "rows": _int(r["value"]), "share": _pct(r["value"] / n if n else 0)} for r in s_rows]
    n_named_sources = len(named)

    # ---- insights
    grp_r = grp.reset_index(drop=True)
    path_depth = pp["depth"]
    rules = [
        ("leader", insight_leader(grp_r)),
        ("certs", insight_certs(df)),
        ("common", insight_common(common, n_paths)),
        ("top_item", insight_top_item(items)),
        ("topic_lift", insight_topic_lift(df, gnames)),
        ("depth", insight_depth(path_depth)),
        ("remarks", insight_remarks(df, gnames)),
        ("sources", insight_sources(src, n)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    # ---- KPIs
    cert_share = (df["kind"] == KIND_CERT).mean() if n else 0.0
    kpis = {
        "n_items": {"value": n_items, "display": _int(n_items), "tone": "brand"},
        "paths": {"value": n_paths, "display": _int(n_paths), "tone": "brand"},
        "reqs": {"value": n_reqs, "display": _int(n_reqs), "tone": "brand"},
        "median": {"value": med_path, "display": f"{med_path:,.0f}" if med_path == int(med_path) else f"{med_path:,.1f}", "tone": "info"},
        "rows": {"value": n, "display": _int(n), "tone": "brand"},
        "certs": {"value": round(float(cert_share), 4), "display": _pct(cert_share), "tone": "info"},
    }

    top_t = torder[0] if torder else OTHER
    lede = (f"המאגר של הרשות הארצית לכבאות והצלה מפרט אילו דרישות בטיחות אש חלות על עסק טעון רישוי, "
            f"לפי פריט הרישוי בצו רישוי עסקים: {_int(n)} שיוכים של {_int(n_reqs)} דרישות שונות "
            f"ל-{_int(n_paths)} סיווגי עסק, ב-{_int(n_items)} פריטי רישוי ו-{_plural(n_groups, 'קבוצה אחת', 'קבוצות')}. "
            f"כל שורה היא דרישה אחת לסיווג אחד, עם מספר הסעיף, ההערה המסייגת ומקור הדרישה (תקן, תקנה או הוראת נציב). "
            f"הנושא השכיח ביותר: {top_t}.")

    summary = (f"איתור דרישות בטיחות אש לרישוי עסק לפי סוג העסק ופריט הרישוי: {_int(n_reqs)} דרישות "
               f"ל-{_int(n_paths)} סיווגי עסק, כבאות והצלה.")
    if len(summary) > 155:
        summary = f"איתור דרישות בטיחות אש לרישוי עסק לפי סוג העסק ופריט הרישוי: {_int(n_reqs)} דרישות, כבאות והצלה."

    top_g = grp_r.iloc[0] if len(grp_r) else None
    top_item = items.iloc[0] if len(items) else None
    top_path = tp.iloc[0] if len(tp) else None
    top_src = keep[0] if keep else NO_SOURCE
    top_common = common[0] if common else None
    heat_peak = max(cells, key=lambda c: (c[2], -c[0], -c[1])) if cells else None

    labels = {
        "lede": lede,
        "items_kpi": "פריטי רישוי",
        "paths_kpi": "סיווגי עסק (תת-פריטים ופיצולים)",
        "reqs_kpi": "דרישות בטיחות אש שונות",
        "median_kpi": "חציון דרישות לסיווג עסק",
        "rows_kpi": "שיוכי דרישה לסיווג (שורות)",
        "certs_kpi": "מהשיוכים הם אישורים להגשה",
        "dir_note": (f"{_int(n_items)} פריטי הרישוי לפי קבוצה, עם מספר הסיווגים בכל פריט, מספר הדרישות "
                     f"השונות שחלות על סיווגיו ומספר שיוכי האישורים. את נוסח הדרישות עצמן מוצאים בחיפוש בטבלת הנתונים."),
        "dir_caption": "פריטי רישוי: סיווגים, דרישות ואישורים",
        "group_note": (f"{top_g['name']} מובילה עם {_int(top_g['rows'])} שיוכים ({_pct(top_g['share'])}). "
                       f"הפס מחולק בין דרישות התקנה והסדר לבין אישורים שבעל העסק מגיש." if top_g is not None else ""),
        "group_aria": (f"גרף עמודות אופקי מוערם: שיוכי דרישות לפי קבוצת עסקים. המובילה {top_g['name']} עם {_int(top_g['rows'])}."
                       if top_g is not None else "גרף עמודות: שיוכי דרישות לפי קבוצת עסקים."),
        "items_note": (f"פריט {top_item['code']} מוביל עם {_int(top_item['reqs'])} דרישות שונות. "
                       f"הספירה היא של דרישות שונות על פני כל הסיווגים שבפריט." if top_item is not None else ""),
        "items_aria": (f"גרף עמודות אופקי: {_int(len(top_items))} פריטי הרישוי עם מספר הדרישות השונות הגבוה ביותר. "
                       f"המוביל {top_item['code']} עם {_int(top_item['reqs'])}." if top_item is not None else "גרף עמודות: פריטי רישוי."),
        "items_title": f"{_int(len(top_items))} פריטי הרישוי עם הכי הרבה דרישות",
        "paths_title": f"{_int(len(tp))} סיווגי העסק עם רשימת הדרישות הארוכה ביותר",
        "paths_note": (f"בראש: {tp_last[0]} עם {_int(top_path['reqs'])} דרישות. סיווג הוא הרמה המפורטת ביותר "
                       f"שאליה משויכת דרישה, למשל תת-פריט לפי שטח." if top_path is not None else ""),
        "paths_aria": (f"גרף עמודות אופקי: סיווגי העסק עם מספר הדרישות הגבוה ביותר. בראש {tp_last[0]} עם {_int(top_path['reqs'])}."
                       if top_path is not None else "גרף עמודות: סיווגי עסק."),
        "hist_note": (f"החציון הוא {kpis['median']['display']} דרישות לסיווג עסק, והטווח השכיח הוא {hist_mode} דרישות. "
                      + (f"בקצה העליון: {_short(top_path['leaf'], 40)} ({tp_last[0]}) עם {_int(top_path['reqs'])} דרישות." if top_path is not None else "")),
        "hist_aria": f"היסטוגרמה: מספר סיווגי העסק לפי מספר הדרישות. החציון {kpis['median']['display']}, הטווח השכיח {hist_mode}.",
        "topics_note": (f"סיווג הדרישות לנושאים לפי מילות מפתח בנוסח הדרישה. הנושא הגדול: {top_t} "
                        f"עם {_int(topic_tot[top_t])} שיוכים." if torder else ""),
        "topics_aria": f"גרף עמודות אופקי מוערם: שיוכי דרישות לפי נושא, מחולקים לדרישות ולאישורים. המוביל {top_t}.",
        "heat_note": ("כל עמודה היא קבוצת עסקים, והתא מראה איזה חלק מהשיוכים בקבוצה עוסק בכל נושא. "
                      + (f"התא הבולט: {ch_heat['y'][heat_peak[1]]} ב{gshort[gcodes[heat_peak[0]]]} ({heat_peak[2]}%)." if heat_peak else "")),
        "heat_aria": (f"מפת חום: חלק כל נושא מהשיוכים בכל קבוצת עסקים. השיא {ch_heat['y'][heat_peak[1]]} ב{gshort[gcodes[heat_peak[0]]]}, {heat_peak[2]}%."
                      if heat_peak else "מפת חום: נושאים לפי קבוצה."),
        "common_note": (f"הדרישה הנפוצה ביותר מופיעה ב-{_int(top_common['paths'])} מתוך {_int(n_paths)} הסיווגים. "
                        f"האחוז הוא חלק סיווגי העסק שהדרישה חלה עליהם." if top_common else ""),
        "common_aria": (f"גרף עמודות אופקי: הדרישות הנפוצות ביותר לפי אחוז סיווגי העסק שהן חלות עליהם. המובילה ב-{_int(top_common['paths'])} סיווגים."
                        if top_common else "גרף עמודות: דרישות נפוצות."),
        "common_title": f"{_int(len(common))} הדרישות הנפוצות ביותר",
        "src_note": (f"{_int(n_named_sources)} מקורות שונים מצוינים במאגר. המוביל: {top_src}. "
                     f"מוצגים {_int(len(keep))} המקורות הגדולים, והשאר תחת \"אחר\"."),
        "src_aria": f"גרף עמודות אופקי: שיוכי דרישות לפי מקור הדרישה. המוביל {top_src}.",
    }

    agent_data = {
        "summary_he": summary,
        "dataset_kind": "registry",
        "suggested_tags": ["בטיחות אש", "רישוי עסקים", "כבאות והצלה", "צו רישוי עסקים", "תקינה"],
        "related_ids": [
            "40593d42-f3c9-4c1d-a9e9-67d72c1e7714",
            "d0ebccda-eb09-49cb-b9d3-09bd2c50592a",
            "a725b698-e7e2-4452-9c74-2e8d1a546d7f",
            "c83c8080-2ff5-4706-9708-246222c3d9ca",
            "8b3d9aa2-3eed-4204-9c32-0764773e9b6f",
        ],
        "spatial_coverage": "ישראל",
    }

    return {
        "agent_data": agent_data,
        "kpis": kpis,
        "charts": {
            "by_group": by_group, "top_items": ch_items, "paths": ch_paths,
            "hist": {"x": hist_x, "y": hist_y}, "topics": ch_topics, "heat": ch_heat,
            "common": ch_common, "src": ch_src,
        },
        "tables": {
            "group": t_group, "top_items": t_items, "paths": t_paths, "hist": t_hist,
            "topics": t_topics, "heat": t_heat, "heat_cols": torder, "common": t_common, "src": t_src,
        },
        "directory": directory,
        "insights": insights,
        "labels": labels,
    }
