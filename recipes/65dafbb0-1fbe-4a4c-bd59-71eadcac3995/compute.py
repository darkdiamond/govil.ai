"""גבולות תצ"ר (המרכז למיפוי ישראל): every registration plan (תצ"ר) since
the late 1990s, one polygon each.

~37,000 polygons can't be drawn on a page, so compute reduces each plan to
its centroid. The lookup and the dot map carry the plans of the last
LOOKUP_YEARS plan years (the ones people still track); everything else is
aggregated from the attribute table: plans per year and status, the time
from the end of the survey to "כשר לרישום", who orders them, where, and how
large they are.
"""
import itertools
import json
import math
import re

import pandas as pd
from govlib import fmt, frame

SCALE = 1000            # lookup coordinates in 1/SCALE degrees (~100 m)
CHUNK = 44_000          # characters per lookup island (check.py caps a <script> at 51,200)
LOOKUP_YEARS = 5        # plan years in the lookup, counting back from the newest
LOOKUP_CAP = 12_000     # the newest plans first if those years ever hold more
TOP_ORDERERS = 12
TOP_PLACES = 15
TOP_GUSH = 12
AREA_BINS = [(0, 1), (1, 5), (5, 25), (25, 100), (100, 500), (500, 2000), (2000, None)]  # dunam
FINAL = "סופי"

_MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6, "JUL": 7, "AUG": 8,
    "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
    "ינואר": 1, "פברואר": 2, "מרץ": 3, "מרס": 3, "אפריל": 4, "מאי": 5, "יוני": 6, "יולי": 7,
    "אוגוסט": 8, "ספטמבר": 9, "אוקטובר": 10, "נובמבר": 11, "דצמבר": 12,
}
_ISO = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")
_DMY = re.compile(r"^(\d{1,2})-\s*([A-Za-z]+|[א-ת]+)\s*-\s*(\d{2}|\d{4})$")
_SLASH = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")

# Known spellings of the same body (renames, abbreviations); anything not
# matched keeps its own (cleaned) name.
_ALIASES = [
    (re.compile(r"מקרקעיישראל|^ממי$|^רמי$|^mmi$"), "רשות מקרקעי ישראל (ומינהל מקרקעי ישראל)"),
    (re.compile(r"נתיביישראל"), "נתיבי ישראל"),
    (re.compile(r"^מפי$|המרכזלמיפויישראל"), "המרכז למיפוי ישראל"),
    (re.compile(r"משרדהבינויוהשיכון|משרדהשיכון"), "משרד הבינוי והשיכון"),
    (re.compile(r"רכבתישראל"), "רכבת ישראל"),
]


def _date(s: str):
    s = (s or "").strip()
    if not s:
        return None
    y = mo = d = None
    if m := _ISO.match(s):
        y, mo, d = int(m[1]), int(m[2]), int(m[3])
    elif m := _DMY.match(s):
        mo = _MONTHS.get(m[2].upper() if m[2].isascii() else m[2])
        d, y = int(m[1]), int(m[3])
        if y < 100:
            y += 2000 if y < 70 else 1900
    elif m := _SLASH.match(s):
        d, mo, y = int(m[1]), int(m[2]), int(m[3])
    if not mo or not (1990 <= (y or 0) <= 2100):
        return None
    try:
        return pd.Timestamp(year=y, month=mo, day=d)
    except ValueError:
        return None


_WORDS = ("ישראל", "רשות", "משרד", "עיריית", "מקרקעי", "חברת", "מועצה", "לפיתוח", "הבינוי",
          "השיכון", "ירושלים", "הבעלים", "מינהל", "מנהל", "נתיבי", "רכבת", "התיישבות", "אזורית")


def _hits(s: str) -> int:
    return sum(w in s for w in _WORDS)


def _key(s: str) -> str:
    return re.sub(r"[\s\"'״׳.\-–,()]", "", s).lower()


def _orderers(raw: pd.Series) -> pd.Series:
    """Clean orderer names: a name stored reversed (letter by letter, as some
    rows are) maps to the forward spelling another row uses, then known
    spellings of the same body merge."""
    s = frame.clean_series(raw).str.replace(r"\s*בע\"?מ$", "", regex=True)
    s = s.str.replace(r"^עירית ", "עיריית ", regex=True)
    # A name stored reversed with no forward twin elsewhere: reverse it when
    # the reversed text holds more common words of these names.
    s = s.map(lambda v: v[::-1] if _hits(v[::-1]) > _hits(v) else v)
    counts = frame.ranked(s[s != ""])
    by_key: dict[str, str] = {}
    for name in counts.index:  # most frequent spelling first
        by_key.setdefault(_key(name), name)
    spaced: dict[str, str] = {}  # per key, the spelling with the most word breaks
    for name in counts.index:
        k = _key(name)
        if name.count(" ") > spaced.get(k, "").count(" ") or k not in spaced:
            spaced[k] = name
    out = {}
    for name in counts.index:
        k = _key(name)
        rk = k[::-1]
        fwd = name
        if rk != k and rk in by_key and counts[by_key[rk]] > 0:
            # Of a pair that reads backwards to each other, the forward one is
            # the spelling a final letter (ךםןףץ) never starts a word in.
            cand = by_key[rk]
            if re.search(r"(^|\s)[ךםןףץ]", name) or (not re.search(r"(^|\s)[ךםןףץ]", cand)
                                                    and counts[cand] > counts[name]):
                fwd = cand
        fk = _key(fwd)
        fwd = spaced.get(fk, fwd)  # "עירייתירושלים" → "עיריית ירושלים"
        for rx, canon in _ALIASES:
            if rx.search(fk) or rx.search(fk[::-1]):
                fwd = canon
                break
        out[name] = fwd
    return s.map(lambda v: out.get(v, v))


def _centroid(geom: str):
    try:
        g = json.loads(geom)
    except (TypeError, ValueError):
        return None
    t = g.get("type") if isinstance(g, dict) else None
    polys = [g.get("coordinates") or []] if t == "Polygon" else (g.get("coordinates") or []) if t == "MultiPolygon" else []
    a = cx = cy = 0.0
    pts = []
    for p in polys:
        if not p:
            continue
        ring = p[0]
        pts += ring
        for (x1, y1), (x2, y2) in itertools.pairwise(ring):
            c = x1 * y2 - x2 * y1
            a += c
            cx += (x1 + x2) * c
            cy += (y1 + y2) * c
    if not pts:
        return None
    if abs(a) < 1e-12:
        return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
    return cx / (3 * a), cy / (3 * a)


def _prepare(df):
    d = pd.DataFrame({
        "name": frame.clean_series(df["NAME"]),
        "num": pd.to_numeric(df["TALAR_NUM"], errors="coerce"),
        "year": pd.to_numeric(df["TALAR_YEAR"], errors="coerce"),
        "status": frame.clean_series(df["STATUS_TEX"]).str.replace("''", "\"", regex=False),
        "place": frame.clean_series(df["PLACE"]),
        "gush": pd.to_numeric(df["GUSH_NUM"], errors="coerce"),
        "dunam": pd.to_numeric(df["Shape_Area"], errors="coerce") / 1000,
        "finish": df["FINISH_DAT"].map(_date),
        "kosher": df["UPDATE_REG"].map(_date),
        "orderer": _orderers(df["ORDERER"]),
        "recid": frame.clean_series(df["RECID"]),
    })
    d["status"] = d["status"].where(d["status"] != "", "לא צוין")
    d["place"] = d["place"].where(~d["place"].isin(["0", "-"]), "")
    d.loc[(d["year"] < 1990) | (d["year"] > 2100), "year"] = math.nan
    c = df["__geometry"].map(_centroid)
    d["lon"] = c.map(lambda v: v[0] if v else math.nan)
    d["lat"] = c.map(lambda v: v[1] if v else math.nan)
    # One plan can be several polygons (rows): a plan is its name, else its row.
    d["plan"] = d["name"].where(d["name"] != "", "#" + d["recid"])
    return d.sort_values(["year", "num", "plan", "recid"], kind="stable", na_position="first").reset_index(drop=True)


def _plans(d):
    """One row per plan: the first polygon's attributes, the polygons' total area."""
    g = d.groupby("plan", sort=False)
    p = g.first()
    p["dunam"] = g["dunam"].sum(min_count=1)
    return p.reset_index()


def _lookup(p, statuses, years):
    sidx = {s: i for i, s in enumerate(statuses)}
    sel = p[p["year"].isin(years) & p["lon"].notna() & p["num"].notna()]
    sel = sel.sort_values(["year", "num", "plan"], ascending=[False, False, True]).head(LOOKUP_CAP)
    sel = sel.sort_values(["year", "num", "plan"])
    y0 = int(min(years))
    ox = math.floor(sel["lon"].min() * SCALE) if len(sel) else 0
    oy = math.floor(sel["lat"].min() * SCALE) if len(sel) else 0
    recs = []
    for r in sel.to_dict("records"):
        gush = "" if pd.isna(r["gush"]) or r["gush"] <= 0 else str(int(r["gush"]))
        vals = [str(int(r["year"]) - y0), str(int(r["num"])), gush, str(sidx[r["status"]]),
                str(round(r["lon"] * SCALE) - ox), str(round(r["lat"] * SCALE) - oy)]
        recs.append(",".join(vals))
    chunks, cur, size = [], [], 0
    for rec in recs:
        if cur and size + len(rec) + 1 > CHUNK:
            chunks.append(";".join(cur))
            cur, size = [], 0
        cur.append(rec)
        size += len(rec) + 1
    if cur:
        chunks.append(";".join(cur))
    bounds = ([[float(sel["lat"].min()), float(sel["lon"].min())],
               [float(sel["lat"].max()), float(sel["lon"].max())]] if len(sel) else None)
    return {"chunks": chunks, "origin": [ox, oy], "scale": SCALE, "y0": y0, "n": len(recs),
            "bounds": bounds, "first": y0, "last": int(max(years))}


def _area_bins(p):
    names, counts = [], []
    for lo, hi in AREA_BINS:
        m = (p["dunam"] >= lo) & (p["dunam"] < hi) if hi else (p["dunam"] >= lo)
        names.append(f"{lo:,}-{hi:,}" if hi else f"{lo:,}+")
        counts.append(int(m.sum()))
    return names, counts


def _partial(per_year):
    """Is the newest plan year partial? It is when it holds under half the
    median of the three years before it."""
    if len(per_year) < 4:
        return False
    return per_year.iloc[-1] < 0.5 * per_year.iloc[-4:-1].median()


# ── insights ─────────────────────────────────────────────────────────────


def insight_final(p):
    m = p["status"] == FINAL
    if not m.any():
        return None
    return (f"{fmt.pct(m.mean())} מהתצ\"רים בשכבה ({fmt.int_he(m.sum())} מתוך {fmt.int_he(len(p))}) "
            f"בסטטוס \"{FINAL}\"; השאר עדיין בדרך לרישום, או בוטלו.")


def insight_backlog(p, full_year):
    if full_year is None:
        return None
    cohort = p[p["year"] == full_year]
    if len(cohort) < 50:
        return None
    done = (cohort["status"] == FINAL).mean()
    top_open = frame.ranked(cohort.loc[cohort["status"] != FINAL, "status"])
    if top_open.empty:
        return None
    return (f"מתצ\"רי {full_year} ({fmt.int_he(len(cohort))}), {fmt.pct(done)} כבר סופיים, "
            f"והסטטוס הנפוץ בשאר הוא \"{top_open.index[0]}\" ({fmt.int_he(top_open.iloc[0])}).")


def insight_growth(per_year, full_year):
    if full_year is None:
        return None
    recent = per_year[(per_year.index > full_year - 5) & (per_year.index <= full_year)]
    early = per_year[(per_year.index > full_year - 15) & (per_year.index <= full_year - 10)]
    if len(recent) < 5 or len(early) < 5 or early.mean() == 0:
        return None
    ratio = recent.mean() / early.mean()
    if 0.8 < ratio < 1.25:
        return None
    word = "יותר" if ratio > 1 else "פחות"
    return (f"בחמש שנות התצ\"ר {int(recent.index[0])}-{int(recent.index[-1])} נרשמו בממוצע "
            f"{fmt.int_he(recent.mean())} תצ\"רים בשנה, {word} מ-{fmt.int_he(early.mean())} בשנים "
            f"{int(early.index[0])}-{int(early.index[-1])}.")


def insight_wait(wait):
    if len(wait) < 6:
        return None
    first, last = wait.iloc[:3], wait.iloc[-3:]
    a, b = float(first.mean()), float(last.mean())
    if a <= 0:
        return None
    ch = b / a - 1
    if abs(ch) < 0.2:
        return (f"החציון מסיום המדידה ועד \"כשר לרישום\" יציב סביב {fmt.int_he(b)} חודשים "
                f"בתצ\"רי {int(last.index[0])}-{int(last.index[-1])}.")
    word = "התארך" if ch > 0 else "התקצר"
    return (f"הזמן מסיום המדידה ועד \"כשר לרישום\" {word}: חציון של {fmt.int_he(b)} חודשים בתצ\"רי "
            f"{int(last.index[0])}-{int(last.index[-1])}, לעומת {fmt.int_he(a)} בתצ\"רי "
            f"{int(first.index[0])}-{int(first.index[-1])}.")


def insight_orderer(p):
    o = frame.ranked(p.loc[p["orderer"] != "", "orderer"])
    if o.empty:
        return None
    share = o.iloc[0] / len(p)
    if share < 0.1:
        return None
    return (f"{o.index[0]} הזמינה {fmt.pct(share)} מהתצ\"רים ({fmt.int_he(o.iloc[0])}), "
            f"המזמינה הגדולה ביותר בשכבה.")


def insight_gush(p):
    g = frame.ranked(p.loc[p["gush"] > 0, "gush"].astype(int))
    if g.empty or g.iloc[0] < 10:
        return None
    places = frame.ranked(p.loc[(p["gush"] == g.index[0]) & (p["place"] != ""), "place"])
    where = f" ({places.index[0]})" if not places.empty else ""
    return f"בגוש {g.index[0]}{where} נרשמו הכי הרבה תצ\"רים: {fmt.int_he(g.iloc[0])}."


def insight_largest(p):
    s = p[p["dunam"].notna()].sort_values(["dunam", "plan"], ascending=[False, True])
    if s.empty or s["dunam"].median() <= 0:
        return None
    r = s.iloc[0]
    return (f"התצ\"ר הגדול בשכבה, {r['name'] or r['plan']}, משתרע על {fmt.int_he(r['dunam'])} דונם; "
            f"תצ\"ר חציוני הוא {fmt.num_he(s['dunam'].median())} דונם.")


# ── model ────────────────────────────────────────────────────────────────


def compute(frames):
    d = _prepare(frames["geo"])
    p = _plans(d)
    n = len(p)
    statuses = list(frame.ranked(p["status"]).index)
    per_year = p[p["year"].notna()].groupby(p["year"].astype("Int64")).size().sort_index()
    years = [int(y) for y in per_year.index]
    partial = _partial(per_year)
    full_years = years[:-1] if partial else years
    full_year = full_years[-1] if full_years else None
    lookup_years = years[-LOOKUP_YEARS:]
    ct = pd.crosstab(p["year"].astype("Int64"), p["status"]).reindex(index=per_year.index, columns=statuses,
                                                                     fill_value=0)
    st = frame.ranked(p["status"])

    p["wait"] = (p["kosher"] - p["finish"]).map(lambda v: v.days / 30.4375 if pd.notna(v) else math.nan)
    ok = p[(p["wait"] >= 0) & p["year"].notna()]
    wait = ok.groupby(ok["year"].astype(int))["wait"].median()
    wait_n = ok.groupby(ok["year"].astype(int)).size()
    wait = wait[wait_n.reindex(wait.index) >= 30]
    if partial and len(wait) and years and wait.index[-1] == years[-1]:
        wait = wait.iloc[:-1]

    orders = frame.ranked(p.loc[p["orderer"] != "", "orderer"])
    o_names, o_vals = frame.top_other(orders, TOP_ORDERERS)
    places = frame.ranked(p.loc[p["place"] != "", "place"])
    pl_names, pl_vals = list(places.index[:TOP_PLACES]), [int(v) for v in places.iloc[:TOP_PLACES]]
    gush = frame.ranked(p.loc[p["gush"] > 0, "gush"].astype(int))
    g_names = [str(g) for g in gush.index[:TOP_GUSH]]
    g_vals = [int(v) for v in gush.iloc[:TOP_GUSH]]
    a_names, a_vals = _area_bins(p)
    lookup = _lookup(p, statuses, lookup_years) if lookup_years else None

    final_share = float((p["status"] == FINAL).mean())
    review = [s for s in statuses if "ביקורת" in s]
    n_review = int(p["status"].isin(review).sum())
    last_wait = float(wait.iloc[-3:].mean()) if len(wait) else None

    insights = []
    for iid, text in [
        ("final", insight_final(p)),
        ("backlog", insight_backlog(p, full_year)),
        ("growth", insight_growth(per_year, full_year)),
        ("wait", insight_wait(wait)),
        ("orderer", insight_orderer(p)),
        ("gush", insight_gush(p)),
        ("largest", insight_largest(p)),
    ]:
        if text:
            insights.append({"id": iid, "text_he": text})

    first_year, last_year = (years[0], years[-1]) if years else (None, None)
    summary = (f"גבולות {fmt.int_he(n)} תכניות לצורכי רישום (תצ\"ר) של המרכז למיפוי ישראל, "
               f"שנות התצ\"ר {first_year}-{last_year}; {fmt.pct(final_share, 0)} מהן בסטטוס סופי.")
    description = (f"איתור תצ\"ר לפי מספר או גוש: סטטוס, שנה ומיקום במפה. "
                   f"{fmt.int_he(n)} תצ\"רים מאז {first_year}, {fmt.pct(final_share, 0)} מהם סופיים "
                   f"ו-{fmt.int_he(n_review)} בביקורת.")
    lede = (f"תצ\"ר (תכנית לצורכי רישום) היא המפה שעל פיה נרשמות חלקות חדשות בטאבו. "
            f"השכבה של המרכז למיפוי ישראל כוללת את גבולות {fmt.int_he(n)} תצ\"רים משנות {first_year}-{last_year}. "
            f"חפשו תצ\"ר לפי מספר (למשל {lookup_example(p, lookup_years)}) או לפי מספר גוש, "
            f"וראו את הסטטוס שלו ואת מיקומו.")
    partial_note = (f" שנת {years[-1]} חלקית ({fmt.int_he(per_year.iloc[-1])} תצ\"רים עד כה)." if partial else "")

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "map",
            "temporal_coverage": f"{first_year}/{last_year}" if years else None,
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "איתור תצ\"ר: גבולות תצ\"ר, סטטוס ומיקום במפה",
                "description": description,
                "name": "גבולות תצ\"ר (תכניות לצורכי רישום)",
                "alternate_names": ["איתור תצ\"ר", "תצר", "תכנית לצורכי רישום", "שכבת גבולות תצ\"ר"],
            },
        },
        "kpis": {
            "plans": {"value": n, "display": fmt.int_he(n), "tone": "brand"},
            "final": {"value": round(final_share * 100, 1), "display": fmt.pct(final_share),
                      "tone": "ok" if final_share >= 0.5 else "warn"},
            "review": {"value": n_review, "display": fmt.int_he(n_review), "tone": "info"},
            "wait": ({"value": round(last_wait, 1), "display": fmt.int_he(last_wait), "tone": "info"}
                     if last_wait is not None else {"value": None, "display": "–", "tone": "brand"}),
        },
        "labels": {
            "lede": lede,
            "review_kpi": "תצ\"רים בביקורת",
            "wait_kpi": "חודשים מסיום המדידה ל\"כשר לרישום\" (חציון, שלוש השנים האחרונות)",
            "lookup_note": (f"{fmt.int_he(lookup['n'] if lookup else 0)} תצ\"רים משנות התצ\"ר "
                            f"{lookup['first'] if lookup else ''}-{lookup['last'] if lookup else ''}, כל אחד כנקודה במרכזו "
                            "(דיוק של כ-100 מ׳). חפשו מספר תצ\"ר (מספר/שנה) או מספר גוש."),
            "map_aria": f"מפת {fmt.int_he(lookup['n'] if lookup else 0)} התצ\"רים של השנים האחרונות לפי סטטוס",
            "year_note": f"תצ\"רים לפי שנת התצ\"ר והסטטוס הנוכחי שלהם.{partial_note}",
            "year_aria": f"תצ\"רים לפי שנה וסטטוס, {first_year}-{last_year}",
            "status_note": f"{fmt.int_he(len(statuses))} סטטוסים. \"{FINAL}\" הוא {fmt.pct(final_share)} מהתצ\"רים.",
            "status_aria": f"תצ\"רים לפי סטטוס, {fmt.int_he(len(statuses))} סטטוסים",
            "wait_note": (f"חציון החודשים מתאריך סיום המדידה עד התאריך שבו התצ\"ר קיבל \"כשר לרישום\", לפי שנת התצ\"ר "
                          f"({fmt.int_he(len(ok))} תצ\"רים עם שני התאריכים; שנים עם פחות מ-30 תצ\"רים הושמטו)."),
            "wait_aria": "חציון החודשים מסיום המדידה עד כשר לרישום, לפי שנת תצ\"ר",
            "orderer_note": (f"מי הזמין את התצ\"רים. שמות של אותו גוף (מינהל ורשות מקרקעי ישראל, שמות הפוכים) אוחדו; "
                             f"{fmt.int_he((p['orderer'] == '').sum())} תצ\"רים ללא מזמין."),
            "orderer_aria": f"{fmt.int_he(len(o_names))} המזמינים עם הכי הרבה תצ\"רים",
            "place_note": (f"היישוב שצוין בתצ\"ר. רק ל-{fmt.pct((p['place'] != '').mean())} מהתצ\"רים "
                           "יש יישוב בשדה הזה."),
            "place_aria": f"{fmt.int_he(len(pl_names))} היישובים עם הכי הרבה תצ\"רים",
            "gush_note": "הגושים שבהם נרשמו הכי הרבה תצ\"רים.",
            "gush_aria": f"{fmt.int_he(len(g_names))} הגושים עם הכי הרבה תצ\"רים",
            "area_note": f"שטח תצ\"ר חציוני: {fmt.num_he(p['dunam'].median())} דונם.",
            "area_aria": "התפלגות שטח התצ\"רים בדונם",
        },
        "charts": {
            "year": {"names": [str(y) for y in years], "statuses": statuses,
                     "series": [[int(v) for v in ct[s]] for s in statuses]},
            "status": {"names": list(st.index), "values": [int(v) for v in st]},
            "wait": {"names": [str(y) for y in wait.index], "values": [round(float(v), 1) for v in wait]},
            "orderer": {"names": o_names, "values": [int(v) for v in o_vals]},
            "place": {"names": pl_names, "values": pl_vals},
            "gush": {"names": g_names, "values": g_vals},
            "area": {"names": a_names, "values": a_vals},
        },
        "tables": {
            "year": [[str(y), fmt.int_he(per_year.loc[y]), fmt.int_he(ct.loc[y, FINAL]) if FINAL in ct else "–"]
                     for y in per_year.index],
            "status": [[s, fmt.int_he(v), fmt.pct(v / n)] for s, v in st.items()],
            "wait": [[str(y), fmt.num_he(v), fmt.int_he(wait_n[y])] for y, v in wait.items()],
            "orderer": [[nm, fmt.int_he(v)] for nm, v in zip(o_names, o_vals)],
            "place": [[nm, fmt.int_he(v)] for nm, v in zip(pl_names, pl_vals)],
            "gush": [[nm, fmt.int_he(v)] for nm, v in zip(g_names, g_vals)],
            "area": [[nm, fmt.int_he(v), fmt.pct(v / n)] for nm, v in zip(a_names, a_vals)],
        },
        "lookup": {**lookup, "statuses": statuses} if lookup else None,
        "insights": insights,
    }


def lookup_example(p, years):
    """A real plan name from the lookup years, for the lede's example."""
    s = p[p["year"].isin(years) & (p["name"] != "")].sort_values(["year", "num", "name"])
    return s["name"].iloc[-1] if len(s) else "123/2024"
