"""כתב העת "חברה ורווחה" — article index of the Welfare Ministry journal.

One row per published item (full article, abstract, book review, editorial,
full-issue PDF, ...). Every number, series and sentence on the page is
computed here; insight rules return None when their premise doesn't hold.

Growth: new issues are appended as rows (a new year ≈ one new volume of ~4
issues). Year axis is continuous from the first to the latest year (gap years
shown as zero and disclosed), decades are derived from the data, item types
are capped to top-N + "אחר", and the latest year is flagged partial when it
has fewer issues than the typical year so far.
"""
import re

import pandas as pd

FULL = "מאמר מלא"
NOTES = ("כתב העת \"חברה ורווחה\" החל לצאת לאור בשנת 1978 ונועד להרחיב ולהעמיק את הידע "
         "התאורטי, המחקרי והיישומי של עובדים סוציאליים ושל אנשי מקצועות רווחה אחרים כגון: "
         "פסיכולוגים, קרימינולוגים, עובדי בריאות הציבור וסוציולוגים.")
TOP_TYPES = 6
TOP_AUTHORS = 15
MAX_AUTHOR_BUCKET = 4  # 1, 2, 3, 4+ authors per article

HEB_NUM = {"א": 1, "ב": 2, "ג": 3, "ד": 4, "ה": 5, "ו": 6, "ז": 7, "ח": 8,
           "ט": 9, "י": 10, "כ": 20, "ך": 20, "ל": 30, "מ": 40, "ם": 40,
           "נ": 50, "ן": 50, "ס": 60, "ע": 70, "פ": 80, "ף": 80, "צ": 90,
           "ץ": 90, "ק": 100, "ר": 200, "ש": 300, "ת": 400}
ISSUE_RE = re.compile(r"חוברת\s+([א-ת\"״']+)\s*/\s*([0-9]+(?:\s*[-–]\s*[0-9]+)?)")
REVIEWER_RE = re.compile(r"[,،]?\s*סוקר(?:ת|ים|ות)?\s*:")
HONORIFIC_RE = re.compile(r"^(?:ד\"ר|ד״ר|פרופ'|פרופ׳|פרופסור|מר|גב')\s+")
PREFIXES = set("ובהלמשכ")

# Title themes: word stems matched at the start of a title word, after
# stripping up to two Hebrew prefix letters. "=" marks an exact-word stem.
THEMES = [
    ("ילדים ונוער", ["ילד", "נוער", "נער", "מתבגר", "צעיר", "פנימי", "תלמיד"]),
    ("משפחה והורות", ["משפח", "הורים", "הורות", "הורי", "=הורה", "אימה", "אמהות",
                      "אבות", "אבהות", "זוג", "גירוש", "גרוש", "אלמנ"]),
    ("נשים ומגדר", ["נשים", "=אישה", "=אשה", "מגדר", "פמיניס", "גברים"]),
    ("זקנה", ["זקנ", "זיקנ", "קשיש", "מזדקנ", "גמלא", "פרישה"]),
    ("מוגבלות ושיקום", ["מוגבל", "נכות", "נכים", "פיגור", "אוטיז", "אוטיסט",
                        "לקות", "לקויות", "שיקום"]),
    ("אלימות והתעללות", ["אלימ", "התעלל", "הזנח", "בריונות", "תקיפ", "פגיעה"]),
    ("טראומה, מלחמה ומשבר", ["טראומ", "פוסט-טראומ", "מלחמ", "חוסן", "אסון", "טרור",
                              "חירום", "קורונה", "מגפ", "אוקטובר", "שכול", "חטופ"]),
    ("עוני ותעסוקה", ["עוני", "עניים", "כלכל", "הכנס", "מצוק", "אבטל", "תעסוק"]),
    ("עולים ומיעוטים", ["עולים", "עולי", "הגיר", "מהגר", "ערבי", "ערבים", "אתיופ",
                        "בדוא", "חרדי", "פליט", "מיעוט", "דרוז"]),
    ("בריאות ובריאות הנפש", ["בריאות", "נפש", "דיכאו", "חרדה", "פסיכיאטר", "התמכר",
                             "סמים", "אלכוהול", "סרטן", "חולי", "חולים", "מחל"]),
    ("מדיניות ושירותים", ["מדיניות", "שירות", "ממשל", "חקיק", "=חוק", "=חוקי",
                          "=חוקים", "זכויות", "רשוי", "הפרט"]),
    ("קהילה והתנדבות", ["קהיל", "מתנדב", "התנדב"]),
    ("הכשרה, הדרכה ומקצוע", ["סטודנט", "הדרכ", "הכשר", "מקצוע", "השתלמ"]),
]


def _int(n):
    return f"{int(n):,}"


def _pct(x, digits=0):
    return f"{x * 100:.{digits}f}%"


def _heb_num(s):
    s = s.replace('"', "").replace("״", "").replace("'", "").replace("׳", "")
    total = sum(HEB_NUM.get(c, 0) for c in s)
    return total or None


def split_authors(raw):
    """Author string → list of names. Book-review strings keep the reviewed
    book's authors only up to the 'סוקר/ת:' marker; editors in parentheses
    are dropped. ' ו' joins two names only when both sides have ≥2 words."""
    s = re.sub(r"\([^)]*\)", " ", raw)
    s = REVIEWER_RE.split(s)[0]
    out = []
    for piece in re.split(r"\s*[,;]\s*|\s+-\s+", s):
        toks = piece.split()
        while True:
            cut = None
            for i in range(len(toks) - 2, 1, -1):
                if toks[i].startswith("ו") and len(toks[i]) > 2:
                    cut = i
                    break
            if cut is None:
                break
            out.append(" ".join(toks[:cut]))
            toks = [toks[cut][1:]] + toks[cut + 1:]
        if toks:
            out.append(" ".join(toks))
    names = []
    for a in out:
        a = HONORIFIC_RE.sub("", a.strip()).strip(" .")
        if len(a) >= 2:
            names.append(a)
    return names


def _word_variants(w):
    vs = [w]
    for k in (1, 2):
        if len(w) > k + 1 and all(c in PREFIXES for c in w[:k]):
            vs.append(w[k:])
    return vs


def _themes_of(title):
    words = re.findall(r"[א-ת][א-ת\-\"״']*", title)
    variants = [v for w in words for v in _word_variants(w)]
    hit = []
    for name, stems in THEMES:
        for st in stems:
            if st.startswith("="):
                ok = st[1:] in variants
            else:
                ok = any(v.startswith(st) for v in variants)
            if ok:
                hit.append(name)
                break
    return hit


def _prepare(df):
    df = df.copy()
    for c in ["article_name", "magazine_name", "publication_year", "author",
              "publication_type"]:
        df[c] = df[c].astype(str).str.strip()
    df["year"] = pd.to_numeric(df["publication_year"], errors="coerce")
    df = df.dropna(subset=["year"])
    df = df[(df["year"] >= 1900) & (df["year"] <= 2200)]
    df["year"] = df["year"].astype(int)
    df["ptype"] = df["publication_type"].where(df["publication_type"] != "", "לא צוין")
    m = df["magazine_name"].str.extract(ISSUE_RE)
    df["vol_he"] = m[0].fillna("")
    df["iss"] = m[1].fillna("").str.replace(r"\s", "", regex=True).str.replace("–", "-")
    df["vol"] = df["vol_he"].map(lambda v: _heb_num(v) if v else None)
    df["issue"] = df.apply(
        lambda r: f"{r['vol_he']}/{r['iss']}" if r["vol_he"] else r["magazine_name"],
        axis=1)
    df["decade"] = (df["year"] // 10) * 10
    # Total order before any dedupe so results don't depend on row order.
    df = df.sort_values(["year", "magazine_name", "ptype", "article_name", "author"],
                        kind="stable").reset_index(drop=True)
    return df


def _decade_label(d, y_min, y_max):
    lo, hi = max(d, y_min), min(d + 9, y_max)
    return f"{lo}-{hi}" if lo != hi else f"{lo}"


# ---------------------------------------------------------------- insights

def insight_coauthor(dec_rows):
    rows = [r for r in dec_rows if r["n"] >= 20]
    if len(rows) < 2:
        return None
    a, b = rows[0], rows[-1]
    diff = b["solo"] - a["solo"]
    if abs(diff) < 0.10:
        return (f"שיעור המאמרים בכתיבת יחיד נותר דומה: {_pct(a['solo'])} ב-{a['label']} "
                f"ו-{_pct(b['solo'])} ב-{b['label']}.")
    word = "ירד" if diff < 0 else "עלה"
    return (f"שיעור המאמרים שנכתבו בידי כותב/ת יחיד/ה {word} מ-{_pct(a['solo'])} "
            f"ב-{a['label']} ל-{_pct(b['solo'])} ב-{b['label']}; ממוצע הכותבים למאמר "
            f"השתנה מ-{a['mean']:.1f} ל-{b['mean']:.1f}.")


def insight_top_author(top):
    if len(top) < 2:
        return None
    (n1, c1), (n2, c2) = top[0], top[1]
    if c1 < 5:
        return None
    if c1 == c2:
        return (f"{n1} ו{n2} הם הכותבים הפורים ביותר בכתב העת, עם {_int(c1)} מאמרים "
                f"מלאים כל אחד.")
    return (f"הכותבת/הכותב הפורה ביותר בכתב העת: {n1}, עם {_int(c1)} מאמרים מלאים "
            f"(ובמקום השני {n2} עם {_int(c2)}).")


def insight_theme_rise(theme_rows, dec_labels, dec_n):
    if len(dec_labels) < 3 or dec_n[-1] < 30:
        return None
    best = None
    for t in theme_rows:
        earlier = t["shares"][:-1]
        base = sum(earlier) / len(earlier)
        rise = t["shares"][-1] - base
        if best is None or rise > best[0] + 1e-12:
            best = (rise, t["name"], base, t["shares"][-1])
    if best is None or best[0] < 0.05:
        return None
    rise, name, base, last = best
    return (f"הנושא שצמח יותר מכל אחר בכותרות המאמרים הוא \"{name}\": {_pct(last)} מהמאמרים "
            f"ב-{dec_labels[-1]}, לעומת ממוצע של {_pct(base)} בעשורים הקודמים.")


def insight_per_issue(issue_rows):
    rows = [r for r in issue_rows if r["issues"] >= 5]
    if len(rows) < 2:
        return None
    a, b = rows[0], rows[-1]
    diff = b["mean"] - a["mean"]
    if abs(diff) < 1:
        return (f"מספר המאמרים המלאים בחוברת יציב יחסית: {a['mean']:.1f} בממוצע "
                f"ב-{a['label']} ו-{b['mean']:.1f} ב-{b['label']}.")
    if diff < 0:
        return (f"החוברות רזות יותר משהיו: בממוצע {b['mean']:.1f} מאמרים מלאים לחוברת "
                f"ב-{b['label']}, לעומת {a['mean']:.1f} ב-{a['label']}.")
    return (f"החוברות התרחבו: בממוצע {b['mean']:.1f} מאמרים מלאים לחוברת ב-{b['label']}, "
            f"לעומת {a['mean']:.1f} ב-{a['label']}.")


def insight_colon(title_rows):
    rows = [r for r in title_rows if r["n"] >= 20]
    if len(rows) < 2:
        return None
    a, b = rows[0], rows[-1]
    if b["colon"] - a["colon"] < 0.15:
        return None
    return (f"סגנון הכותרות השתנה: {_pct(b['colon'])} מכותרות המאמרים ב-{b['label']} "
            f"בנויות כ\"כותרת: כותרת משנה\", לעומת {_pct(a['colon'])} ב-{a['label']}.")


def insight_peak_year(years, counts, partial_year):
    pairs = [(c, y) for y, c in zip(years, counts) if c > 0]
    if len(pairs) < 3:
        return None
    c, y = max(pairs, key=lambda p: (p[0], -p[1]))
    note = " (נתוני השנה חלקיים)" if y == partial_year else ""
    return f"השנה עם מספר הפריטים הגדול ביותר היא {y}, עם {_int(c)} פריטים{note}."


def insight_gaps(gap_years):
    if not gap_years:
        return None
    ys = ", ".join(str(y) for y in gap_years)
    if len(gap_years) == 1:
        return f"במאגר אין פריטים משנת {ys} — שנה ללא חוברות ברצף ההוצאה לאור."
    return f"במאגר אין פריטים מ-{_int(len(gap_years))} שנים ברצף ההוצאה לאור: {ys}."


def insight_partial(partial_year, partial_issues, typical_issues):
    if partial_year is None:
        return None
    return (f"נתוני {partial_year} חלקיים: עד כה נכללו {_int(partial_issues)} חוברות, "
            f"לעומת {_int(typical_issues)} חוברות בשנה טיפוסית.")


# ---------------------------------------------------------------- compute

def compute(frames):
    df = _prepare(frames["main"])
    total = len(df)
    y_min, y_max = int(df["year"].min()), int(df["year"].max())
    years = list(range(y_min, y_max + 1))
    present = set(df["year"].unique().tolist())
    gap_years = [y for y in years if y not in present]

    # --- issues per year, partial latest year
    issues_per_year = df.groupby("year")["issue"].nunique().sort_index()
    typical_issues = int(issues_per_year.iloc[:-1].median()) if len(issues_per_year) > 1 else 0
    latest_issues = int(issues_per_year.iloc[-1])
    partial_year = y_max if (len(issues_per_year) > 3 and latest_issues < typical_issues) else None

    # --- types
    type_counts = df.groupby("ptype").size().sort_index().sort_values(
        ascending=False, kind="stable")
    top_types = list(type_counts.index[:TOP_TYPES])
    df["ptype_c"] = df["ptype"].where(df["ptype"].isin(top_types), "אחר")
    type_order = top_types + (["אחר"] if (df["ptype_c"] == "אחר").any() else [])
    ct = (pd.crosstab(df["year"], df["ptype_c"]).reindex(index=years, fill_value=0)
          .reindex(columns=type_order, fill_value=0))
    year_totals = ct.sum(axis=1)
    type_series = [{"name": t, "data": [int(v) for v in ct[t]]} for t in type_order]
    types_table = [{"name": t, "count": _int(type_counts[t]),
                    "share": _pct(type_counts[t] / total, 1)} for t in type_counts.index]

    # --- full articles (deduped within an issue)
    full = df[df["ptype"] == FULL].drop_duplicates(["article_name", "issue"]).copy()
    n_full = len(full)
    full["authors"] = full["author"].map(split_authors)
    full["n_auth"] = full["authors"].map(len)
    decades = sorted(full["decade"].unique().tolist())
    dec_labels = [_decade_label(d, y_min, y_max) for d in decades]
    dec_n = [int((full["decade"] == d).sum()) for d in decades]

    # co-authorship by decade (articles with a parsed author only)
    fa = full[full["n_auth"] > 0]
    dec_rows = []
    buckets = [str(i) for i in range(1, MAX_AUTHOR_BUCKET)] + [f"{MAX_AUTHOR_BUCKET}+"]
    bucket_series = {b: [] for b in buckets}
    for d, lab in zip(decades, dec_labels):
        sub = fa[fa["decade"] == d]
        n = len(sub)
        cl = sub["n_auth"].clip(upper=MAX_AUTHOR_BUCKET)
        shares = [((cl == i).sum() / n if n else 0.0) for i in range(1, MAX_AUTHOR_BUCKET + 1)]
        for b, s in zip(buckets, shares):
            bucket_series[b].append(round(s * 100, 1))
        dec_rows.append({"label": lab, "n": n, "solo": shares[0],
                         "mean": float(sub["n_auth"].mean()) if n else 0.0})
    coauthor_table = [{"label": r["label"], "n": _int(r["n"]),
                       "cells": [f"{bucket_series[b][i]:.1f}%" for b in buckets],
                       "mean": f"{r['mean']:.2f}"} for i, r in enumerate(dec_rows)]

    # authors: top + first appearances
    ex = fa[["decade", "year", "authors"]].explode("authors").rename(columns={"authors": "name"})
    ex = ex[ex["name"].astype(str) != ""]
    n_authors = int(ex["name"].nunique())
    auth_counts = ex.groupby("name").size().sort_index().sort_values(
        ascending=False, kind="stable")
    top = [(n, int(c)) for n, c in auth_counts.head(TOP_AUTHORS).items()]
    first_dec = ex.groupby("name")["decade"].min()
    first_year = ex.groupby("name")["year"].min()
    last_year = ex.groupby("name")["year"].max()
    top_table = [{"name": n, "count": _int(c),
                  "span": (f"{int(first_year[n])}-{int(last_year[n])}"
                           if first_year[n] != last_year[n] else f"{int(first_year[n])}")}
                 for n, c in top]
    new_rows = []
    for d, lab in zip(decades, dec_labels):
        names = ex.loc[ex["decade"] == d, "name"].unique()
        n_all = len(names)
        n_new = int((first_dec.reindex(names) == d).sum())
        new_rows.append({"label": lab, "all": n_all, "new": n_new, "ret": n_all - n_new,
                         "share": n_new / n_all if n_all else 0.0})
    latest_solo = dec_rows[-1]["solo"] if dec_rows else 0.0

    # --- issues: full articles per issue, by decade
    per_issue = full.groupby("issue").agg(n=("article_name", "size"), year=("year", "min"))
    per_issue["decade"] = (per_issue["year"] // 10) * 10
    issue_rows = []
    for d, lab in zip(decades, dec_labels):
        s = per_issue.loc[per_issue["decade"] == d, "n"]
        issue_rows.append({"label": lab, "issues": int(s.size),
                           "mean": float(s.mean()) if s.size else 0.0,
                           "max": int(s.max()) if s.size else 0})
    n_issues = int(df["issue"].nunique())
    vols = df["vol"].dropna()
    n_vols = int(vols.nunique())
    latest_vol = int(vols.max()) if len(vols) else None

    # --- themes by decade (share of full articles whose title touches the theme)
    full["themes"] = full["article_name"].map(_themes_of)
    theme_rows = []
    for name, _ in THEMES:
        hit = full["themes"].map(lambda ts, nm=name: nm in ts)
        shares = []
        for d in decades:
            m = full["decade"] == d
            shares.append(float(hit[m].mean()) if m.any() else 0.0)
        theme_rows.append({"name": name, "total": int(hit.sum()), "shares": shares})
    theme_rows.sort(key=lambda t: (-t["total"], t["name"]))
    heat_cells = [[xi, yi, round(t["shares"][xi] * 100, 1)]
                  for yi, t in enumerate(theme_rows) for xi in range(len(decades))]
    heat_max = max([c[2] for c in heat_cells] + [1])
    themes_table = [{"name": t["name"], "cells": [_pct(s) for s in t["shares"]],
                     "total": _int(t["total"])} for t in theme_rows]
    any_theme = float(full["themes"].map(bool).mean()) if n_full else 0.0

    # --- title style by decade
    full["colon"] = full["article_name"].str.contains(":", regex=False)
    full["words"] = full["article_name"].map(lambda t: len(t.split()))
    title_rows = []
    for d, lab in zip(decades, dec_labels):
        sub = full[full["decade"] == d]
        title_rows.append({"label": lab, "n": len(sub),
                           "colon": float(sub["colon"].mean()) if len(sub) else 0.0,
                           "words": float(sub["words"].mean()) if len(sub) else 0.0})

    # --- insights
    rules = [
        ("coauthor", insight_coauthor(dec_rows)),
        ("top_author", insight_top_author(top)),
        ("theme_rise", insight_theme_rise(theme_rows, dec_labels, dec_n)),
        ("per_issue", insight_per_issue(issue_rows)),
        ("colon", insight_colon(title_rows)),
        ("peak_year", insight_peak_year(years, [int(v) for v in year_totals], partial_year)),
        ("gaps", insight_gaps(gap_years)),
        ("partial", insight_partial(partial_year, latest_issues, typical_issues)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    # --- labels
    peak_y = int(year_totals.idxmax())
    gaps_note = (f" שנים ללא פריטים במאגר: {', '.join(str(y) for y in gap_years)}."
                 if gap_years else "")
    partial_note = (f" נתוני {partial_year} חלקיים ({_int(latest_issues)} חוברות עד כה)."
                    if partial_year else "")
    top_type = type_counts.index[0]
    lede = (f"מפתח הפרסומים של כתב העת המקצועי \"חברה ורווחה\" של משרד הרווחה והביטחון "
            f"החברתי: {_int(total)} פריטים מ-{_int(n_issues)} חוברות בשנים {y_min}-{y_max}, "
            f"ובהם {_int(n_full)} מאמרים מלאים של {_int(n_authors)} כותבים וכותבות. "
            f"העמוד מנתח את היקף הפרסום לאורך השנים, את המעבר לכתיבה משותפת ואת "
            f"הנושאים שעולים מכותרות המאמרים.")
    summary = (f"חיפוש מאמרים בכתב העת \"חברה ורווחה\" לפי שם מאמר, כותב, חוברת או שנה: "
               f"{_int(n_full)} מאמרים מלאים מ-{_int(n_issues)} חוברות, {y_min}-{y_max}.")

    first_r, last_r = dec_rows[0], dec_rows[-1]
    first_i, last_i = issue_rows[0], issue_rows[-1]
    first_t, last_t = title_rows[0], title_rows[-1]
    lead_theme = theme_rows[0]
    newest = new_rows[-1]

    labels = {
        "lede": lede,
        "total_kpi": "פריטים במפתח",
        "full_kpi": "מאמרים מלאים",
        "span_kpi": "שנות פרסום",
        "issues_kpi": (f"חוברות ({_int(n_vols)} כרכים)" if n_vols else "חוברות"),
        "authors_kpi": "כותבים וכותבות של מאמרים מלאים",
        "solo_kpi": f"מאמרים בכתיבת יחיד ב-{last_r['label']}",
        "yearly_note": (f"מספר הפריטים בכל שנה לפי סוג הפרסום. השיא ב-{peak_y} "
                        f"({_int(year_totals.max())} פריטים).{gaps_note}{partial_note}"),
        "yearly_aria": (f"תרשים עמודות מוערמות: פריטים בכתב העת לפי שנה וסוג, {y_min} עד "
                        f"{y_max}. השיא ב-{peak_y} עם {_int(year_totals.max())} פריטים."),
        "types_note": (f"{top_type} הוא סוג הפריט הנפוץ: {_pct(type_counts.iloc[0] / total, 1)} "
                       f"מכלל {_int(total)} הפריטים. תקצירי מאמרים וחוברות מלאות הם עותקים "
                       f"נוספים של אותם פרסומים."),
        "types_aria": (f"תרשים עמודות: פריטים לפי סוג פרסום. המוביל: {top_type} עם "
                       f"{_int(type_counts.iloc[0])} פריטים."),
        "issues_note": (f"ממוצע המאמרים המלאים בחוברת בכל עשור (חוברת כפולה או מפוצלת "
                        f"לחלקים נספרת כחוברת אחת): {first_i['mean']:.1f} ב-{first_i['label']} "
                        f"לעומת {last_i['mean']:.1f} ב-{last_i['label']}."),
        "issues_aria": (f"תרשים עמודות: ממוצע מאמרים מלאים לחוברת לפי עשור, מ-{first_i['mean']:.1f} "
                        f"ב-{first_i['label']} ל-{last_i['mean']:.1f} ב-{last_i['label']}."),
        "coauthor_note": (f"התפלגות מספר הכותבים למאמר מלא בכל עשור (לפי שדה הכותבים; "
                          f"{_int(len(full) - len(fa))} מאמרים ללא שם כותב לא נכללו). "
                          f"כותב/ת יחיד/ה: {_pct(first_r['solo'])} ב-{first_r['label']}, "
                          f"{_pct(last_r['solo'])} ב-{last_r['label']}."),
        "coauthor_aria": (f"תרשים עמודות מוערמות באחוזים: מספר הכותבים למאמר לפי עשור. "
                          f"ממוצע הכותבים עלה מ-{first_r['mean']:.1f} ל-{last_r['mean']:.1f}."),
        "bucket_names": [f"{b} כותבים" if b != "1" else "כותב/ת יחיד/ה" for b in buckets],
        "authors_note": (f"הכותבים עם המספר הגדול ביותר של מאמרים מלאים, כולל מאמרים "
                         f"משותפים. שמות נספרים לפי הכתיב במאגר, כך שכתיב שונה של אותו "
                         f"שם נספר בנפרד."),
        "authors_aria": (f"תרשים עמודות אופקי: {_int(len(top))} הכותבים הפורים ביותר. "
                         f"במקום הראשון {top[0][0]} עם {_int(top[0][1])} מאמרים."
                         if top else "תרשים עמודות אופקי: הכותבים הפורים ביותר."),
        "new_note": (f"כמה כותבים וכותבות פרסמו מאמר מלא בכל עשור, וכמה מהם הופיעו בכתב העת "
                     f"לראשונה. ב-{newest['label']}: {_int(newest['new'])} חדשים מתוך "
                     f"{_int(newest['all'])} ({_pct(newest['share'])})."),
        "new_aria": (f"תרשים עמודות מוערמות: כותבים חדשים וחוזרים לפי עשור. "
                     f"ב-{newest['label']} {_int(newest['all'])} כותבים, מהם {_int(newest['new'])} חדשים."),
        "themes_note": (f"שיעור המאמרים המלאים בכל עשור שכותרתם כוללת מילה מתחום הנושא "
                        f"(התאמת מילים בכותרת; מאמר יכול להשתייך לכמה נושאים, ו-"
                        f"{_pct(1 - any_theme)} מהכותרות לא שויכו לאף נושא). הנושא הנפוץ "
                        f"בסך הכול: {lead_theme['name']}."),
        "themes_aria": (f"מפת חום: שיעור המאמרים לפי נושא ועשור, {_int(len(theme_rows))} נושאים. "
                        f"הנפוץ: {lead_theme['name']} עם {_int(lead_theme['total'])} מאמרים."),
        "titles_note": (f"שיעור הכותרות במבנה \"כותרת: כותרת משנה\" ואורך הכותרת הממוצע "
                        f"במילים: {_pct(first_t['colon'])} ו-{first_t['words']:.1f} מילים "
                        f"ב-{first_t['label']}, לעומת {_pct(last_t['colon'])} ו-"
                        f"{last_t['words']:.1f} מילים ב-{last_t['label']}."),
        "titles_aria": (f"תרשים קו: שיעור כותרות עם נקודתיים ואורך כותרת לפי עשור, מ-"
                        f"{_pct(first_t['colon'])} ל-{_pct(last_t['colon'])}."),
        "notes": NOTES,
        "decade_partial": (f"העשור האחרון ({dec_labels[-1]}) עדיין לא הסתיים."
                           if decades and decades[-1] + 9 > y_max else ""),
    }

    solo_tone = "info"
    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "suggested_tags": ["רווחה", "עבודה סוציאלית", "כתב עת", "מחקר",
                               "מאמרים אקדמיים"],
            "related_ids": ["1ba21c94-c45e-4d45-a29f-49da77e8d2b8",
                            "4f361ce6-f30f-4629-b4ba-1ad19039e745",
                            "fa11b2f3-0796-48f8-ab84-e5540ea2b014"],
            "temporal_coverage": f"{y_min}/{y_max}",
        },
        "kpis": {
            "total": {"value": total, "display": _int(total), "tone": "brand"},
            "full": {"value": n_full, "display": _int(n_full), "tone": "brand"},
            "span": {"value": [y_min, y_max], "display": f"{y_min}–{y_max}", "tone": "brand"},
            "issues": {"value": n_issues, "display": _int(n_issues), "tone": "brand"},
            "authors": {"value": n_authors, "display": _int(n_authors), "tone": "brand"},
            "solo": {"value": round(latest_solo, 4), "display": _pct(latest_solo, 1),
                     "tone": solo_tone},
        },
        "charts": {
            "yearly": {"x": [str(y) for y in years], "series": type_series,
                       "partial": str(partial_year) if partial_year else None,
                       "zoom": len(years) > 30},
            "types": {"names": list(type_counts.index),
                      "values": [int(v) for v in type_counts]},
            "issues": {"x": dec_labels, "mean": [round(r["mean"], 1) for r in issue_rows],
                       "issues": [r["issues"] for r in issue_rows]},
            "coauthor": {"x": dec_labels, "names": labels["bucket_names"],
                         "series": [bucket_series[b] for b in buckets],
                         "mean": [round(r["mean"], 2) for r in dec_rows]},
            "authors": {"names": [n for n, _ in top], "values": [c for _, c in top]},
            "newauthors": {"x": dec_labels, "new": [r["new"] for r in new_rows],
                           "ret": [r["ret"] for r in new_rows]},
            "themes": {"x": dec_labels, "y": [t["name"] for t in theme_rows],
                       "cells": heat_cells, "max": heat_max},
            "titles": {"x": dec_labels,
                       "colon": [round(r["colon"] * 100, 1) for r in title_rows],
                       "words": [round(r["words"], 1) for r in title_rows]},
        },
        "tables": {
            "types": types_table,
            "issues": [{"label": r["label"], "issues": _int(r["issues"]),
                        "mean": f"{r['mean']:.1f}", "max": _int(r["max"])} for r in issue_rows],
            "coauthor": coauthor_table,
            "buckets": labels["bucket_names"],
            "authors": top_table,
            "newauthors": [{"label": r["label"], "all": _int(r["all"]), "new": _int(r["new"]),
                            "share": _pct(r["share"])} for r in new_rows],
            "themes": themes_table,
            "decades": dec_labels,
            "titles": [{"label": r["label"], "n": _int(r["n"]), "colon": _pct(r["colon"]),
                        "words": f"{r['words']:.1f}"} for r in title_rows],
        },
        "insights": insights,
        "labels": labels,
    }
