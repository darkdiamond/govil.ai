"""דרישות בטיחות אש להיתרי בניה: the fire-safety requirements that the Israel
Fire and Rescue Authority (כבאות והצלה לישראל) sets for a building permit, per
building use and building type.

The dataset publishes a full snapshot roughly monthly as a NEW resource
("... נכון ליום DD-MM-YYYY"); 41 snapshots exist (2018 onward). They are the
same table at different dates, so the recipe reads ONE snapshot
(`pick: "latest"`) and never concatenates them. One old snapshot
(01-04-2025) carries the business-licensing table by mistake (CategoryTypeDesc
"עסקים (טעוני רישוי)"); only rows whose CategoryTypeDesc is construction are
read, and a snapshot without any fails the refresh instead of publishing the
wrong table.

One row = one requirement attached to one classification path:
group of use (CategoryCode1, e.g. 6 / 106 מוסדות בריאות) -> building type
(CategoryCode2, e.g. 106.04 בית אבות) -> condition (CategoryCode3, e.g. beds)
-> height / addition splits (CategoryCode4..7). Requirements set at a higher
level (the whole group, the whole building type) apply to every
classification under it, so the requirements of a building classification
(a leaf path) are the union of its own rows and its ancestors' rows.

Since 2024 the table carries two parallel series of groups: 1-46 and 101-143
(same uses, a different classification). The recipe splits them on the group
number (>= 100) and pairs the same use across the series by a normalised
group name.

A few rows have CSV-quoting debris spilled into CategoryCode6/7; a path stops
at the first value that is not a dotted code. Everything here aggregates; no
row reaches the page. No people are named (the data holds none).
"""
import re

import pandas as pd

from govlib import fmt, frame

TOPICS = [
    ("מטפים", ["מטפה", "מטפים"]),
    ("ספרינקלרים וכיבוי אוטומטי", [
        "ספרינקלר", "מתזי", "מתזים", "מתז ", "כיבוי אוטומטי", "כיבוי אש אוטומטי",
        "כיבוי האש האוטומטית", "מערכת כיבוי", "מערכות כיבוי", "כיבוי בגז", "גז כיבוי",
        "ארוסול", "קצף", "כימיקלים יבשים"]),
    ("עמדות כיבוי, ברזים ואספקת מים", [
        "גלגילון", "גלגילונ", "עמדת כיבוי", "עמדות כיבוי", "ברז כיבוי", "ברזי כיבוי", "הסנקה",
        "הסנקת", "זרנוק", "מאגר מים", "מאגר המים", "אספקת מים", "אספקת המים", "משאבות",
        "משאבה", "רשת מים", "הידרנט", "תותח מים"]),
    ("גילוי אש, התרעה וכריזה", [
        "גילוי", "גלאי", "התרעת", "התרעה", "כריזה", "כריזת", "אזעקה", "משטר הפעלות",
        "אינטגרציה", "לוח פיקוד", "טלפון כבאים"]),
    ("שליטה בעשן ואוורור", ["עשן", "אוורור", "מיזוג", "מנדפ", "פליטה", "ארובה", "ארובות"]),
    ("גישת כבאים וחילוץ", [
        "דרך גישה", "דרך הגישה", "דרכי גישה", "רחבת היערכות", "רחבת ההיערכות", "רחבה להצבת",
        "הרחבה להצבת", "חילוץ", "מנוף", "רכב כיבוי"]),
    ("הפרדות אש וחומרי בנייה", [
        "הפרדה", "הפרדת", "הפרדות", "יופרד", "אגף אש", "אגפי אש", "חומרי בניה", "חומרי בנייה",
        "ציפוי", "חיפוי", "חומרי גמר", "921", "931", "1733", "עמידות אש", "עמידות בהצתה",
        "חסימת אש", "מחסומי אש", "2174", "דליקות", "5419", "צנרת חודרת", "מרחק מבניין",
        "קירות המגן"]),
    ("דרכי מוצא ומילוט", [
        "מוצא", "פרוזדור", "מילוט", "יציאה", "יציאות", "מרחקי הליכה", "מהלך משותף", "מדרגות",
        "דלת", "אזור מחסה", "גג מוגן", "מעלית", "מרפסת", "גלריה", "יציע", "במה", "תפוסה",
        "מקומות ישיבה", "אזור ישיבה", "מעבר", "מושבים", "פתח", "מרחק הליכה", "כניסות חירום",
        "מעלי"]),
    ("שילוט ותאורת חירום", ["שילוט", "שלטים", "תאורת חירום", "תאורת חרום", "תאורה"]),
    ("חשמל, גנרטור ופוטוולטאי", ["חשמל", "גנרטור", "מפסק", "פוטוולט", "שנאי"]),
    ("גז, דלק וחומרים מסוכנים", [
        "גפ\"מ", "גפ''מ", "גט\"ד", "גז טבעי", "גז ", "גז,", "גז.", "בגז", "הגז", "דלק",
        "חומרים מסוכנים", "חומ\"ס", "מיכל", "מכלים", "תדלוק", "מאצרה", "זיקוק"]),
    ("מסמכים, נספחים והוראות כלליות", [
        "נספח", "הוראות כלליות", "סידורי בטיחות", "אישור אדריכל", "עורך הבקשה", "יועץ",
        "הצהרת", "מערכות בטיחות אש ב", "תיק שטח", "הדרכה", "נוהל", "תכנית", "תוכנית",
        "שימוש מעורב", "סקר בטיחות", "שינוי בבניין", "יחולו הדרישות"]),
]
OTHER = "אחר"
TOPIC_ORDER = [t for t, _ in TOPICS] + [OTHER]
KIND_REQ, KIND_CERT = "דרישת תכנון או התקנה", "אישור להגשה"
NO_SOURCE = "מקור לא צוין"

SERIES_SPLIT = 100              # group numbers from here on form the second series
TOP_FAMILIES = 14
TOP_PAIRS = 15
TOP_LEAVES = 12
TOP_COMMON = 12
TOP_SOURCES = 10
HEAT_FAMILIES = 10
HIST_STEP = 10
MIN_TIER = 5                    # a height tier is shown with at least this many classifications
MIN_PAIRS = 5                   # the two-series comparison needs this many paired uses
LEADER_X = 1.5                  # the longest list must be this multiple of the median to be news
HEIGHT_DIFF = 0.10              # tier medians this far apart read as a real rise
LIFT_MIN = 1.8                  # topic typical of a use at this multiple of its overall share
LIFT_MIN_SHARE = 0.12           # ... and at least this share of the use's rows
LIFT_MIN_ROWS = 300
NO_SOURCE_MIN = 0.02
SHORT = 40

_WS = re.compile(r"\s+")
_CODE = re.compile(r"^_?\d+(\.\d+)*( ?[א-ת]['׳]?)?$")
_BARE = re.compile(r"^\d+$")
_NUM = re.compile(r"\d+")
_GROUP_PREFIX = re.compile(r"^\s*קבוצה\s*\d+\s*-?\s*")
_HEIGHT = re.compile(r"(עד|מעל)\s+(\d+)\s*(?:מטר|מ['׳](?![\"״]))")
_TI = re.compile("ת['\"׳״]{1,2}י\\s*")
_ADD = re.compile(r"\s*-?\s*תוספת בני")


def _clean(s):
    return _WS.sub(" ", s or "").strip()


def _int(v):
    return fmt.int_he(v)


def _plural(n, one, many):
    return one if n == 1 else f"{_int(n)} {many}"


def _short(s, n=SHORT):
    s = _clean(s)
    if len(s) <= n:
        return s
    cut = s[:n].rsplit(" ", 1)[0]
    return (cut if len(cut) >= n // 2 else s[:n]).rstrip(" ,.-:;(") + "…"


def _label(s):
    """Text for a chart label: Hebrew gershayim instead of ASCII quotes."""
    return _clean(s).replace('""', '"').replace('"', "״").replace("''", "״")


def _code_show(c):
    return c.lstrip("_")


def _code_key(code):
    return (tuple(int(x) for x in _NUM.findall(code)), code)


def _path_key(p):
    return tuple(_code_key(c) for c in p.split("|"))


def _topic(text):
    for name, kws in TOPICS:
        for k in kws:
            if k in text:
                return name
    return OTHER


def _kind(text):
    if text.startswith("אישור") or "להגיש אישור" in text or "הגשת אישור" in text:
        return KIND_CERT
    return KIND_REQ


def _source(s):
    s = _clean(s)
    if s in ("", "NULL"):
        return NO_SOURCE
    if len(s) > 60 or '"' in s or not re.search(r"[א-תA-Za-z]", s) or s.startswith("יתגלה"):
        return OTHER              # CSV-quoting debris spilled into this column
    s = _clean(_TI.sub("", s))
    s = s.replace("תקן ישראלי/ תקן זר מוכר", "תקן ישראלי או תקן זר מוכר")
    s = s.replace("תקן ישראלי / תקן זר מוכר", "תקן ישראלי או תקן זר מוכר")
    s = re.sub(r"הוראת נציב\s+", "הוראת נציב ", s)
    return s


def _group_name(desc):
    return _clean(_GROUP_PREFIX.sub("", desc)).strip(" -") or _clean(desc)


def _family_key(desc):
    s = _group_name(desc)
    s = re.split(r"[,(]| ולרבות", s)[0]
    s = re.sub(r"[^א-ת ]", "", s)
    s = s.replace("י", "").replace("ו", "")
    return _WS.sub(" ", s).strip()


def _family_label(desc):
    s = _group_name(desc)
    s = re.split(r",| ולרבות", s)[0]
    return _clean(s)


def _mode(series):
    """Most frequent value, ties alphabetical (shuffle-proof)."""
    vc = frame.ranked(series[series != ""])
    return str(vc.index[0]) if len(vc) else ""


def _path(row):
    out, col = [], 0
    for i, v in enumerate(row):
        if v == "":
            continue
        if not _CODE.match(v) or (out and _BARE.match(v) and i >= 2):
            break               # CSV debris (a bare "1" deep in the path, spilled text)
        out.append(v)
        col = i
    return "|".join(out), col


# ── preparation ──────────────────────────────────────────────────────────


def _prepare(raw):
    df = raw.copy()
    for c in df.columns:
        df[c] = df[c].map(_clean)
    df = df[df["CategoryTypeDesc"].str.contains("בני", regex=False)].copy()
    if df.empty:
        raise ValueError("snapshot holds no construction (בנייה) rows: wrong table picked")
    df = df[df["RequirementDesc"] != ""].copy()
    codes = [f"CategoryCode{i}" for i in range(1, 8)]
    descs = [f"CategoryDesc{i}" for i in range(1, 8)]
    pc = [_path(r) for r in df[codes].itertuples(index=False, name=None)]
    df["path"] = [p for p, _ in pc]
    dv = df[descs].to_numpy()
    df["leaf_desc"] = [dv[i][c] for i, (_, c) in enumerate(pc)]
    df = df[df["path"] != ""].copy()
    df["g"] = df["path"].str.split("|").str[0]
    df["gnum"] = [int(_NUM.findall(g)[0]) for g in df["g"]]
    df["series"] = (df["gnum"] >= SERIES_SPLIT).astype(int)
    df["req"] = df["RequirementNumber"] + "\u0001" + df["RequirementDesc"]
    df["topic"] = df["RequirementDesc"].map(_topic)
    df["kind"] = df["RequirementDesc"].map(_kind)
    df["source"] = df["REQUIREMENT_SOURCE_DESC"].map(_source)
    return df


def _leaves(df):
    """Leaf classifications with the union of their own and ancestors' requirements."""
    own = {p: set(s) for p, s in df.groupby("path")["req"]}
    paths = sorted(own, key=_path_key)
    prefixes = set()
    for p in paths:
        parts = p.split("|")
        for i in range(1, len(parts)):
            prefixes.add("|".join(parts[:i]))
    leaf_desc = {p: _mode(s) for p, s in df.groupby("path")["leaf_desc"]}
    rows = []
    for p in paths:
        if p in prefixes:
            continue
        parts = p.split("|")
        reqs = set()
        for i in range(1, len(parts) + 1):
            reqs |= own.get("|".join(parts[:i]), set())
        rows.append({"path": p, "g": parts[0], "code": _code_show(parts[-1]),
                     "code2": parts[1] if len(parts) > 1 else "", "depth": len(parts),
                     "desc": leaf_desc.get(p, ""), "reqs": reqs, "n": len(reqs)})
    return rows


# ── insight rules ────────────────────────────────────────────────────────


def insight_series(sr, pairs):
    if len(sr) < 2 or len(pairs) < MIN_PAIRS:
        return None
    a, b = sr
    more = sum(1 for p in pairs if p["b"] > p["a"])
    less = sum(1 for p in pairs if p["b"] < p["a"])
    text = (f"המאגר מפרסם במקביל שתי סדרות של קבוצות שימוש: {a['range']} ({_int(a['rows'])} שורות) "
            f"ו-{b['range']} ({_int(b['rows'])} שורות). {_int(len(pairs))} שימושים מופיעים בשתיהן")
    if more > less:
        text += f", ובסדרה {b['range']} יש יותר דרישות שונות ב-{_int(more)} מהם (פחות ב-{_int(less)})."
    elif less > more:
        text += f", ובסדרה {b['range']} יש פחות דרישות שונות ב-{_int(less)} מהם (יותר ב-{_int(more)})."
    else:
        text += "."
    return text


def insight_leader(leaves, med, gnames):
    if len(leaves) < 20 or med <= 0:
        return None
    top = leaves[0]
    if top["n"] < med * LEADER_X:
        return None
    return (f"סוג המבנה עם רשימת הדרישות הארוכה ביותר הוא {top['code']} ({_short(_label(top['desc']), 70)}, "
            f"{_short(gnames.get(top['g'], top['g']), 45)}): {_int(top['n'])} דרישות, פי {top['n'] / med:.1f} "
            f"מהחציון לסוג מבנה ({fmt.num_he(med, 0) if med == int(med) else fmt.num_he(med)}).")


def insight_height(tiers):
    if len(tiers) < 2:
        return None
    lo, hi = tiers[0], tiers[-1]
    if lo["median"] <= 0:
        return None
    diff = (hi["median"] - lo["median"]) / lo["median"]
    base = (f"בסוגי המבנים המוגדרים לפי גובה, החציון הוא {fmt.num_he(lo['median'], 0)} דרישות "
            f"ב\"{lo['name']}\" ({_int(lo['n'])} סיווגים) ו-{fmt.num_he(hi['median'], 0)} ב\"{hi['name']}\" "
            f"({_int(hi['n'])} סיווגים)")
    if diff >= HEIGHT_DIFF:
        return base + f": מבנה גבוה יותר נדרש לכ-{fmt.pct(diff, 0)} יותר דרישות."
    if diff <= -HEIGHT_DIFF:
        return base + f": דווקא במבנים הגבוהים הרשימה קצרה יותר, ב-{fmt.pct(-diff, 0)}."
    return base + ", כלומר רשימות באורך דומה."


def insight_additions(add_pairs):
    n = len(add_pairs)
    if n < MIN_PAIRS:
        return None
    same = sum(1 for p in add_pairs if p["same"])
    share = same / n
    if share >= 0.5:
        return (f"ל-{_int(n)} סוגי מבנים מוגדר גם סיווג נפרד של תוספת בנייה למבנה קיים, אבל ב-{_int(same)} "
                f"מהם ({fmt.pct(share)}) רשימת הדרישות לתוספת זהה לחלוטין לזו של מבנה חדש מאותו סוג.")
    return (f"ל-{_int(n)} סוגי מבנים מוגדר גם סיווג נפרד של תוספת בנייה למבנה קיים, וב-{_int(n - same)} "
            f"מהם ({fmt.pct(1 - share)}) רשימת הדרישות לתוספת שונה מזו של מבנה חדש מאותו סוג.")


def insight_common(common, n_leaves):
    if not common or n_leaves < 20:
        return None
    top = common[0]
    share = top["leaves"] / n_leaves
    if share < 0.2:
        return None
    return (f"הדרישה הנפוצה ביותר, \"{_short(top['full'], 70)}\", חלה על {_int(top['leaves'])} "
            f"מתוך {_int(n_leaves)} סוגי המבנים ({fmt.pct(share)}).")


def insight_certs(df):
    n = len(df)
    c = int((df["kind"] == KIND_CERT).sum())
    if n == 0 or c == 0:
        return None
    return (f"{fmt.pct(c / n)} מהשורות ({_int(c)}) אינן דרישת תכנון אלא אישור שמגישים לרשות הכבאות, "
            f"בדרך כלל אישור מעבדה מוכרת או מהנדס על תכנון והתקנה של מערכת לפי תקן.")


def insight_topic_lift(df, fam_of, fam_label):
    overall = df["topic"].value_counts(normalize=True)
    best = None
    for f, sub in df.groupby(df["g"].map(fam_of), sort=True):
        if len(sub) < LIFT_MIN_ROWS:
            continue
        sh = sub["topic"].value_counts(normalize=True)
        for t, v in sh.items():
            if t == OTHER or v < LIFT_MIN_SHARE:
                continue
            lift = v / overall[t]
            key = (round(lift, 9), round(v, 9), f, t)
            if lift >= LIFT_MIN and (best is None or key > best[0]):
                best = (key, f, t, v, overall[t])
    if best is None:
        return None
    _, f, t, v, o = best
    return (f"בשימוש \"{fam_label[f]}\" הנושא \"{t}\" מהווה {fmt.pct(v)} מהדרישות, "
            f"פי {v / o:.1f} מחלקו בכלל המאגר ({fmt.pct(o)}).")


def insight_sources(src, n):
    named = src[(src.index != NO_SOURCE) & (src.index != OTHER)]
    if named.empty or n == 0:
        return None
    top, v = named.index[0], int(named.iloc[0])
    text = f"רוב הדרישות נשענות על {top}: {_int(v)} שורות ({fmt.pct(v / n)})." if v / n >= 0.5 else \
        f"המקור הנפוץ ביותר לדרישות הוא {top}, עם {_int(v)} שורות ({fmt.pct(v / n)})."
    miss = int(src.get(NO_SOURCE, 0))
    if miss / n >= NO_SOURCE_MIN:
        text += f" ל-{fmt.pct(miss / n)} מהשורות לא צוין מקור."
    return text


# ── compute ──────────────────────────────────────────────────────────────


def compute(frames):
    df = _prepare(frames["main"])
    n = int(len(df))

    gcodes = sorted(df["g"].unique(), key=_code_key)
    gdesc = {g: _mode(s) for g, s in df.groupby("g")["CategoryDesc1"]}
    gnames = {}
    for g in gcodes:
        nm = _group_name(gdesc.get(g, ""))
        gnames[g] = f"קבוצה {_code_show(g)}: {_short(nm, 60)}" if nm else f"קבוצה {_code_show(g)}"

    # ---- families: the same use across the two series
    fam_of = {g: (_family_key(gdesc.get(g, "")) or g) for g in gcodes}
    fam_label = {}
    for g in gcodes:
        f = fam_of[g]
        lab = _family_label(gdesc.get(g, "")) or _code_show(g)
        if f not in fam_label or (len(lab), lab) < (len(fam_label[f]), fam_label[f]):
            fam_label[f] = lab
    df["fam"] = df["g"].map(fam_of)

    leaves = _leaves(df)
    leaves.sort(key=lambda r: (-r["n"], _path_key(r["path"])))
    n_leaves = len(leaves)
    lens = pd.Series([r["n"] for r in leaves], dtype=float)
    med = float(lens.median()) if n_leaves else 0.0
    n_reqs = int(df["req"].nunique())
    n_types = int(df.loc[df["path"].str.count(r"\|") >= 1, "path"].str.split("|").str[1].nunique())
    n_groups = len(gcodes)

    # ---- series
    sr = []
    for s in (0, 1):
        sub = df[df["series"] == s]
        if sub.empty:
            continue
        nums = sorted(sub["gnum"].unique())
        sr.append({"s": s, "rows": int(len(sub)), "range": f"{nums[0]}-{nums[-1]}",
                   "groups": len(sub["g"].unique())})
    fam_series = df.groupby(["fam", "series"])["req"].nunique()
    pairs = []
    if len(sr) == 2:
        for f in sorted(set(df["fam"])):
            if (f, 0) in fam_series.index and (f, 1) in fam_series.index:
                pairs.append({"f": f, "name": fam_label[f], "a": int(fam_series[(f, 0)]),
                              "b": int(fam_series[(f, 1)])})
    pairs.sort(key=lambda p: (-(p["a"] + p["b"]), p["name"]))
    top_pairs = pairs[:TOP_PAIRS]
    rp = top_pairs[::-1]
    ch_pairs = {
        "y": [_short(p["name"], 28) for p in rp], "full": [p["name"] for p in rp],
        "names": [f"קבוצות {s['range']}" for s in sr],
        "a": [p["a"] for p in rp], "b": [p["b"] for p in rp],
    }
    t_pairs = [{"name": p["name"], "a": _int(p["a"]), "b": _int(p["b"]),
                "d": (f"+{_int(p['b'] - p['a'])}" if p["b"] > p["a"] else
                      (f"{fmt.MINUS}{_int(p['a'] - p['b'])}" if p["b"] < p["a"] else "0"))}
               for p in top_pairs]

    # ---- rows by family, stacked by kind
    fam_rows = frame.ranked(df["fam"])
    fk = df.groupby(["fam", "kind"]).size()
    head = list(fam_rows.index[:TOP_FAMILIES])
    rest = [f for f in fam_rows.index if f not in head]
    fam_entries = [(fam_label[f], [f]) for f in head]
    if len(rest) == 1:
        fam_entries.append((fam_label[rest[0]], rest))
    elif rest:
        fam_entries.append((f"אחר ({_int(len(rest))} שימושים)", rest))
    fr = fam_entries[::-1]
    kinds = [KIND_REQ, KIND_CERT]
    ch_fam = {
        "y": [_short(lab, 26) for lab, _ in fr], "full": [lab for lab, _ in fr],
        "series": [{"name": k, "data": [int(sum(int(fk.get((f, k), 0)) for f in fs)) for _, fs in fr]}
                   for k in kinds],
    }
    t_fam = []
    for lab, fs in fam_entries:
        sub = df[df["fam"].isin(fs)]
        t_fam.append({"name": lab, "rows": _int(len(sub)), "share": fmt.pct(len(sub) / n),
                      "groups": _int(sub["g"].nunique()), "certs": fmt.pct((sub["kind"] == KIND_CERT).mean())})
    top_fam_label = fam_label[head[0]] if head else ""
    top_fam_rows = int(fam_rows.iloc[0]) if len(fam_rows) else 0

    # ---- distribution of requirements per building classification
    top_n = int(lens.max()) if n_leaves else 0
    hist_x, hist_y = [], []
    lo = 1
    while lo <= top_n:
        hi = lo + HIST_STEP - 1
        hist_x.append(f"{lo}-{hi}")
        hist_y.append(int(((lens >= lo) & (lens <= hi)).sum()))
        lo += HIST_STEP
    hist_mode = hist_x[max(range(len(hist_y)), key=lambda i: (hist_y[i], -i))] if hist_y else ""
    t_hist = [{"name": x, "n": _int(y)} for x, y in zip(hist_x, hist_y)]
    med_disp = fmt.num_he(med, 0) if med == int(med) else fmt.num_he(med)

    # ---- most demanding classifications
    tnames = {c: _mode(s) for c, s in df.groupby("CategoryCode2")["CategoryDesc2"] if c}

    def _leaf_name(r, n):
        t, d = _label(tnames.get(r["code2"], "")), _label(r["desc"])
        if t and d and t != d:
            return f"{_short(t, n // 2)} / {_short(d, n // 2)}"
        return _short(d or t, n)

    tl = [r for r in leaves if not _ADD.search(r["desc"])][:TOP_LEAVES]
    ch_leaves = {
        "y": [f"{r['code']} {_short(_label(r['desc']), 26)}" for r in tl][::-1],
        "full": [f"{r['code']}: {_leaf_name(r, 160)} ({_short(gnames.get(r['g'], ''), 60)})" for r in tl][::-1],
        "v": [r["n"] for r in tl][::-1],
    }
    t_leaves = [{"code": r["code"], "name": _leaf_name(r, 100), "group": _short(gnames.get(r["g"], ""), 50),
                 "n": _int(r["n"])} for r in tl]

    # ---- height tiers (boxplot)
    tier_vals = {}
    for r in leaves:
        m = _HEIGHT.search(r["desc"])
        if not m:
            continue
        tier_vals.setdefault((int(m.group(2)), 0 if m.group(1) == "עד" else 1), []).append(r["n"])
    tiers = []
    for (h, op), vals in sorted(tier_vals.items()):
        if len(vals) < MIN_TIER:
            continue
        s = pd.Series(vals, dtype=float)
        tiers.append({"name": f"{'עד' if op == 0 else 'מעל'} {h} מ׳", "n": len(vals),
                      "min": float(s.min()), "q1": float(s.quantile(0.25)), "median": float(s.median()),
                      "q3": float(s.quantile(0.75)), "max": float(s.max())})
    ch_height = {"x": [t["name"] for t in tiers],
                 "box": [[round(t["min"], 1), round(t["q1"], 1), round(t["median"], 1),
                          round(t["q3"], 1), round(t["max"], 1)] for t in tiers],
                 "n": [t["n"] for t in tiers]}
    t_height = [{"name": t["name"], "n": _int(t["n"]), "min": fmt.num_he(t["min"], 0),
                 "q1": fmt.num_he(t["q1"], 1), "median": fmt.num_he(t["median"], 1),
                 "q3": fmt.num_he(t["q3"], 1), "max": fmt.num_he(t["max"], 0)} for t in tiers]
    n_height = sum(t["n"] for t in tiers)

    # ---- additions to an existing building vs a new one
    by_path = {r["path"]: r for r in leaves}
    base = {}
    for r in leaves:
        if not _ADD.search(r["desc"]):
            parent = r["path"].rsplit("|", 1)[0] if "|" in r["path"] else ""
            base.setdefault((parent, r["desc"]), r["path"])
    add_pairs = []
    for r in leaves:
        m = _ADD.search(r["desc"])
        if not m or m.start() == 0:
            continue
        parent = r["path"].rsplit("|", 1)[0] if "|" in r["path"] else ""
        k = (parent, _clean(r["desc"][:m.start()]))
        if k in base:
            b = by_path[base[k]]
            add_pairs.append({"d": r["n"] - b["n"], "same": r["reqs"] == b["reqs"]})

    # ---- topics x kind
    tk = df.groupby(["topic", "kind"]).size()
    topic_tot = df["topic"].value_counts()
    torder = sorted([t for t in TOPIC_ORDER if t in topic_tot.index and t != OTHER],
                    key=lambda t: (-int(topic_tot[t]), TOPIC_ORDER.index(t)))
    if OTHER in topic_tot.index:
        torder.append(OTHER)
    tr = torder[::-1]
    ch_topics = {"y": tr, "series": [{"name": k, "data": [int(tk.get((t, k), 0)) for t in tr]} for k in kinds]}
    t_topics = [{"name": t, "rows": _int(topic_tot[t]), "share": fmt.pct(topic_tot[t] / n),
                 "certs": _int(tk.get((t, KIND_CERT), 0))} for t in torder]
    top_t = torder[0] if torder else OTHER

    # ---- heatmap: topic share within the largest uses
    hf = list(fam_rows.index[:HEAT_FAMILIES])
    ft = df.groupby(["fam", "topic"]).size()
    cells, t_heat, hmax = [], [], 0.0
    for xi, f in enumerate(hf):
        tot = int(fam_rows[f])
        for yi, t in enumerate(tr):
            c = int(ft.get((f, t), 0))
            v = round(c / tot * 100, 1) if tot else 0.0
            hmax = max(hmax, v)
            cells.append([xi, yi, v, c])
        t_heat.append({"name": fam_label[f], "vals": [fmt.pct(int(ft.get((f, t), 0)) / tot) for t in torder]})
    ch_heat = {"x": [_short(fam_label[f], 16) for f in hf], "xfull": [fam_label[f] for f in hf],
               "y": tr, "cells": cells, "max": round(hmax, 1)}
    heat_peak = max(cells, key=lambda c: (c[2], -c[0], -c[1])) if cells else None

    # ---- most common requirements (share of building classifications)
    reach = {}
    for r in leaves:
        for q in r["reqs"]:
            reach[q] = reach.get(q, 0) + 1
    common_keys = sorted(reach, key=lambda q: (-reach[q], q))[:TOP_COMMON]
    common = []
    for q in common_keys:
        num, desc = q.split("\u0001", 1)
        head_txt = _clean(desc.split("הערה:")[0]) or _clean(desc)
        common.append({"full": _label(head_txt).rstrip(" ."), "num": num, "leaves": reach[q]})
    ch_common = {
        "y": [_short(c["full"], 32) for c in common][::-1],
        "full": [_short(c["full"], 160) for c in common][::-1],
        "num": [c["num"] for c in common][::-1],
        "share": [round(c["leaves"] / n_leaves * 100, 1) if n_leaves else 0 for c in common][::-1],
        "leaves": [c["leaves"] for c in common][::-1],
    }
    t_common = [{"name": _short(c["full"], 90), "num": c["num"], "leaves": _int(c["leaves"]),
                 "share": fmt.pct(c["leaves"] / n_leaves if n_leaves else 0)} for c in common]

    # ---- sources
    src = frame.ranked(df["source"])
    named = [s for s in src.index if s not in (NO_SOURCE, OTHER)]
    keep = named[:TOP_SOURCES]
    rest_src = int(src[[s for s in src.index if s not in keep and s != NO_SOURCE]].sum())
    s_rows = [{"name": s, "value": int(src[s])} for s in keep]
    if rest_src:
        s_rows.append({"name": OTHER, "value": rest_src})
    if NO_SOURCE in src.index:
        s_rows.append({"name": NO_SOURCE, "value": int(src[NO_SOURCE])})
    ch_src = {"y": [r["name"] for r in s_rows][::-1], "v": [r["value"] for r in s_rows][::-1],
              "muted": [r["name"] in (OTHER, NO_SOURCE) for r in s_rows][::-1]}
    t_src = [{"name": r["name"], "rows": _int(r["value"]), "share": fmt.pct(r["value"] / n)} for r in s_rows]
    top_src = keep[0] if keep else NO_SOURCE

    # ---- group directory
    gl = {}
    for r in leaves:
        gl.setdefault(r["g"], []).append(r["n"])
    directory = []
    for g in gcodes:
        sub = df[df["g"] == g]
        types = sub.loc[sub["path"].str.contains("|", regex=False), "path"].str.split("|").str[1].nunique()
        ln = pd.Series(gl.get(g, []), dtype=float)
        directory.append({"code": _code_show(g), "name": _short(_group_name(gdesc.get(g, "")), 90),
                          "types": _int(types), "leaves": _int(len(ln)), "reqs": _int(sub["req"].nunique()),
                          "max": _int(ln.max()) if len(ln) else "0"})

    # ---- insights
    rules = [
        ("series", insight_series(sr, pairs)),
        ("leader", insight_leader(leaves, med, gnames)),
        ("height", insight_height(tiers)),
        ("additions", insight_additions(add_pairs)),
        ("common", insight_common(common, n_leaves)),
        ("certs", insight_certs(df)),
        ("topic_lift", insight_topic_lift(df, fam_of, fam_label)),
        ("sources", insight_sources(src, n)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    # ---- KPIs
    cert_share = float((df["kind"] == KIND_CERT).mean()) if n else 0.0
    top_len = leaves[0]["n"] if leaves else 0
    kpis = {
        "leaves": {"value": n_leaves, "display": _int(n_leaves), "tone": "brand"},
        "groups": {"value": n_groups, "display": _int(n_groups), "tone": "brand"},
        "reqs": {"value": n_reqs, "display": _int(n_reqs), "tone": "brand"},
        "median": {"value": med, "display": med_disp, "tone": "info"},
        "max": {"value": top_len, "display": _int(top_len), "tone": "brand"},
        "certs": {"value": round(cert_share, 4), "display": fmt.pct(cert_share), "tone": "info"},
    }

    two = len(sr) == 2
    series_txt = (f" הטבלה כוללת במקביל שתי סדרות של קבוצות שימוש, {sr[0]['range']} ו-{sr[1]['range']}."
                  if two else "")
    lede = (f"דרישות הבטיחות מאש שהרשות הארצית לכבאות והצלה מציבה כתנאי להיתר בנייה (היתר בניה), לפי שימוש "
            f"המבנה וסוגו: {_int(n_reqs)} דרישות שונות ל-{_int(n_leaves)} סוגי מבנים ב-{_plural(n_groups, 'קבוצת שימוש אחת', 'קבוצות שימוש')}, "
            f"מבית מגורים ועד מנהרת תשתית. כל שורה היא דרישה אחת לסיווג אחד, עם מספר הסעיף, הערה מסייגת "
            f"ומקור הדרישה (תקנות התכנון והבנייה, תקן ישראלי או הוראת נציב).{series_txt} "
            f"דרישה שנקבעה לקבוצה כולה חלה על כל סוגי המבנים שבה, ולכן ספירת הדרישות לסוג מבנה כוללת "
            f"גם אותן. הנושא השכיח ביותר: {top_t}.")

    summary = (f"איתור דרישות בטיחות אש להיתר בנייה לפי שימוש וסוג המבנה: {_int(n_reqs)} דרישות "
               f"ל-{_int(n_leaves)} סוגי מבנים, כבאות והצלה.")
    if len(summary) > 155:
        summary = f"איתור דרישות בטיחות אש להיתר בנייה לפי שימוש וסוג המבנה: {_int(n_reqs)} דרישות, כבאות והצלה."

    top_leaf = tl[0] if tl else None
    top_common = common[0] if common else None
    labels = {
        "lede": lede,
        "leaves_kpi": "סוגי מבנים (סיווגים מפורטים)",
        "groups_kpi": "קבוצות שימוש (בשתי הסדרות)" if two else "קבוצות שימוש",
        "reqs_kpi": "דרישות בטיחות אש שונות",
        "median_kpi": "חציון דרישות לסוג מבנה",
        "max_kpi": "דרישות לסוג המבנה התובעני ביותר",
        "certs_kpi": "מהשורות הן אישורים להגשה",
        "fam_note": (f"בראש: {top_fam_label}, עם {_int(top_fam_rows)} שורות ({fmt.pct(top_fam_rows / n)}). "
                     f"שימוש שמופיע בשתי סדרות הקבוצות נספר כאן פעם אחת, והפס מחולק בין דרישות תכנון והתקנה "
                     f"לבין אישורים להגשה." if head else ""),
        "fam_aria": (f"גרף עמודות אופקי מוערם: שורות דרישה לפי שימוש המבנה. המוביל {top_fam_label} עם {_int(top_fam_rows)}."
                     if head else "גרף עמודות: שורות לפי שימוש."),
        "pairs_note": (f"{_int(len(pairs))} שימושים מופיעים בשתי הסדרות. לכל שימוש: מספר הדרישות השונות בקבוצה "
                       f"מסדרה {sr[0]['range']} לעומת הקבוצה המקבילה מסדרה {sr[1]['range']}. מוצגים "
                       f"{_int(len(top_pairs))} השימושים עם הרשימות הארוכות. הזיווג לפי שם הקבוצה."
                       if two and pairs else ""),
        "pairs_aria": (f"גרף עמודות אופקי כפול: מספר הדרישות השונות לכל שימוש בשתי סדרות הקבוצות, "
                       f"{_int(len(top_pairs))} שימושים." if pairs else ""),
        "pairs_title": "אותו שימוש בשתי סדרות הקבוצות",
        "hist_note": (f"החציון הוא {med_disp} דרישות לסוג מבנה, והטווח השכיח הוא {hist_mode} דרישות "
                      f"({_int(n_leaves)} סוגי מבנים בסך הכל)."),
        "hist_aria": f"היסטוגרמה: מספר סוגי המבנים לפי מספר הדרישות החלות עליהם. החציון {med_disp}, הטווח השכיח {hist_mode}.",
        "leaves_title": f"{_int(len(tl))} סוגי המבנים עם רשימת הדרישות הארוכה ביותר",
        "leaves_note": (f"בראש: {top_leaf['code']} ({_short(_label(top_leaf['desc']), 60)}) עם {_int(top_leaf['n'])} דרישות, "
                        f"כולל הדרישות שנקבעו לקבוצה ולסוג המבנה שמעליו. סיווגי תוספת בנייה למבנה קיים אינם מוצגים כאן, "
                        f"כי רשימתם בדרך כלל זהה לזו של המבנה החדש." if top_leaf else ""),
        "leaves_aria": (f"גרף עמודות אופקי: סוגי המבנים עם מספר הדרישות הגבוה ביותר. בראש {top_leaf['code']} עם {_int(top_leaf['n'])}."
                        if top_leaf else "גרף עמודות: סוגי מבנים."),
        "height_note": (f"{_int(n_height)} סוגי מבנים מוגדרים לפי גובה (\"עד\" או \"מעל\" גובה במטרים). לכל מדרגת גובה: "
                        f"טווח מספר הדרישות, הרבעונים והחציון. מוצגות מדרגות עם {_int(MIN_TIER)} סוגי מבנים לפחות."
                        if tiers else ""),
        "height_aria": (f"תרשים קופסה: מספר הדרישות לסוג מבנה לפי מדרגת גובה, {_int(len(tiers))} מדרגות. "
                        f"החציון ב\"{tiers[0]['name']}\" {fmt.num_he(tiers[0]['median'], 0)} וב\"{tiers[-1]['name']}\" {fmt.num_he(tiers[-1]['median'], 0)}."
                        if tiers else ""),
        "topics_note": (f"שיוך כל דרישה לנושא לפי מילות מפתח בנוסח שלה. הנושא הגדול: {top_t} "
                        f"עם {_int(topic_tot[top_t])} שורות." if torder else ""),
        "topics_aria": f"גרף עמודות אופקי מוערם: שורות דרישה לפי נושא, מחולקות לדרישות ולאישורים. המוביל {top_t}.",
        "heat_note": (f"כל עמודה היא אחד מ-{_int(len(hf))} השימושים הגדולים, והתא מראה איזה חלק מהשורות בו עוסק בכל נושא. "
                      + (f"התא הבולט: {tr[heat_peak[1]]} ב{fam_label[hf[heat_peak[0]]]} ({heat_peak[2]}%)." if heat_peak else "")),
        "heat_aria": (f"מפת חום: חלק כל נושא מהשורות בכל שימוש. השיא {tr[heat_peak[1]]} ב{fam_label[hf[heat_peak[0]]]}, {heat_peak[2]}%."
                      if heat_peak else "מפת חום: נושאים לפי שימוש."),
        "common_title": f"{_int(len(common))} הדרישות הנפוצות ביותר",
        "common_note": (f"הדרישה הנפוצה ביותר חלה על {_int(top_common['leaves'])} מתוך {_int(n_leaves)} סוגי המבנים. "
                        f"האחוז הוא חלק סוגי המבנים שהדרישה חלה עליהם." if top_common else ""),
        "common_aria": (f"גרף עמודות אופקי: הדרישות הנפוצות ביותר לפי אחוז סוגי המבנים שהן חלות עליהם. המובילה ב-{_int(top_common['leaves'])} סוגי מבנים."
                        if top_common else "גרף עמודות: דרישות נפוצות."),
        "src_note": (f"{_int(len(named))} מקורות שונים מצוינים במאגר. המוביל: {top_src}. "
                     f"מוצגים {_int(len(keep))} המקורות הגדולים, והשאר תחת \"אחר\"."),
        "src_aria": f"גרף עמודות אופקי: שורות דרישה לפי מקור הדרישה. המוביל {top_src}.",
        "dir_note": (f"כל {_int(n_groups)} קבוצות השימוש: מספר סוגי המבנים בכל קבוצה, הסיווגים המפורטים, הדרישות השונות "
                     f"והרשימה הארוכה ביותר לסיווג אחד. את נוסח הדרישות מוצאים בחיפוש בטבלת הנתונים."),
        "dir_summary": f"הצג את כל {_int(n_groups)} הקבוצות",
    }

    agent_data = {
        "summary_he": summary,
        "dataset_kind": "registry",
        "spatial_coverage": "ישראל",
    }

    return {
        "agent_data": agent_data,
        "kpis": kpis,
        "charts": {
            "fam": ch_fam, "pairs": ch_pairs, "hist": {"x": hist_x, "y": hist_y}, "leaves": ch_leaves,
            "height": ch_height, "topics": ch_topics, "heat": ch_heat, "common": ch_common, "src": ch_src,
        },
        "tables": {
            "fam": t_fam, "pairs": t_pairs, "pair_cols": ch_pairs["names"], "hist": t_hist, "leaves": t_leaves,
            "height": t_height, "topics": t_topics, "heat": t_heat, "heat_cols": torder,
            "common": t_common, "src": t_src,
        },
        "flags": {"pairs": bool(two and len(pairs) >= MIN_PAIRS), "height": len(tiers) >= 2},
        "directory": directory,
        "insights": insights,
        "labels": labels,
    }
