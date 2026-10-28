"""תיקים בטיפול היחידה לתיאום המאבק בסחר בבני אדם — the case/referral log
of the Ministry of Justice's anti-trafficking coordination unit.

One row per file (תיק): a referral, a court case, a procedure being drafted,
an international report, a conference… with its subject (נושא), type (סוג),
the referring body (הגורם הפונה), case and referral status, and dates.

SENSITIVE: some files are victims' own referrals. The data carries no
personal fields, but the page stays aggregate-only regardless: one-way
category charts fold every category with fewer than MIN_CAT files into a
"נושאים/גורמים נוספים" bucket (so a lone "forced marriage" file is not
spotlighted), and every two-way cross-tab (type × subject, victim-facing
files by subject) suppresses cells with fewer than MIN_CAT files. No free
text exists in the data.

The source uses sentinel dates (01/01/1753, 01/01/1900) for "no date"; any
year before SENTINEL_BEFORE is treated as missing. "~" in the source stands
for gershayim (בינ~ל → בינ״ל).

The unit's structured log starts in a computed "era" year: the first year in
which most files carry a case type (older rows are a migrated legacy list
without types). Trend charts start there; legacy rows are counted and
disclosed. "Now" is the latest creation date in the data; that year is
partial unless it reaches late December.
"""
import pandas as pd

MIN_CAT = 5                 # categories / cells below this are merged or suppressed
SENTINEL_BEFORE = 1990
TOP_TOPICS_TREND = 6
TOP_SOURCES_TREND = 5
HEAT_TYPES = 12
HEAT_TOPICS = 10
ERA_MIN_ROWS = 20           # an era-start year needs at least this many files
SHIFT_PP = 10               # share change (percentage points) worth an insight
FLAT_CHANGE = 0.05          # |yoy change| below this = "ללא שינוי"
VICTIM_TYPES = ["פניות של קרבנות", "בקשות להכרה"]
LAG_BINS = [(None, -1), (0, 0), (1, 7), (8, 30), (31, 90), (91, 365), (366, None)]
STATUS_ORDER = ["פתוח", "במעקב", "סגור"]
NO_TYPE = "ללא סיווג"
MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]
MONTHS_SHORT = ["ינו׳", "פבר׳", "מרץ", "אפר׳", "מאי", "יוני", "יולי",
                "אוג׳", "ספט׳", "אוק׳", "נוב׳", "דצמ׳"]
LRI, PDI = "⁦", "⁩"
RLM = "‏"


def n(v):
    return f"{int(v):,}"


def pct(v, digits=1):
    return f"{LRI}{v * 100:.{digits}f}%{PDI}"


def d_he(ts):
    return f"{ts.day} ב{MONTHS_HE[ts.month - 1]} {ts.year}"


def _clean(s):
    return s.str.strip().str.replace("~", "״", regex=False)


def _date(s):
    d = pd.to_datetime(s.str.strip(), format="%d/%m/%Y", errors="coerce")
    return d.where(d.dt.year >= SENTINEL_BEFORE)


def _vc(s):
    return s.value_counts().sort_index().sort_values(ascending=False, kind="stable")


def _merge_small(vc, other, existing_other=None):
    """Keep categories with ≥ MIN_CAT files; fold the rest (plus any
    existing "אחר" category) into one `other` bucket. If that bucket would
    still hold fewer than MIN_CAT files, the smallest kept categories join
    it until it doesn't — no merged bar below MIN_CAT is ever shown."""
    big = [(k, int(v)) for k, v in vc.items() if v >= MIN_CAT and k != existing_other]
    merged = [k for k, v in vc.items() if v < MIN_CAT and k != existing_other]
    tail = int(vc[[k in merged for k in vc.index]].sum()) + (int(vc.get(existing_other, 0)) if existing_other else 0)
    while 0 < tail < MIN_CAT and big:
        k, v = big.pop()
        merged.append(k)
        tail += v
    items = big + ([(other, tail)] if tail else [])
    return items, merged


def _prepare(df):
    out = pd.DataFrame({
        "status": _clean(df["סטטוס"]).replace("", "לא צוין"),
        "ref_status": _clean(df["סטטוס הפניה"]).replace("", "לא צוין"),
        "type": _clean(df["סוג התיק"]).replace("", NO_TYPE),
        "topic": _clean(df["נושא התיק"]).replace("", "לא צוין"),
        "source": _clean(df["הגורם הפונה"]).replace("", "לא צוין"),
        "created": _date(df["תאריך יצירה"]),
        "opened": _date(df["תאריך פתיחת התיק"]),
        "referred": _date(df["תאריך הפניה"]),
    })
    out = out.dropna(subset=["created"])
    out["year"] = out["created"].dt.year.astype(int)
    return out


def _era_start(df):
    g = (df["type"] != NO_TYPE).groupby(df["year"])
    typed, size = g.mean().sort_index(), g.size().sort_index()
    ok = typed[(typed >= 0.5) & (size >= ERA_MIN_ROWS)]
    return int(ok.index[0]) if len(ok) else int(df["year"].min())


def _share_shift(era, col, first, last, exclude=()):
    """Category with the largest share gain between two full years."""
    a = era[era["year"] == first][col]
    b = era[era["year"] == last][col]
    if len(a) < 30 or len(b) < 30:
        return None
    sa, sb = a.value_counts(normalize=True), b.value_counts(normalize=True)
    rows = []
    for k in sorted(set(sa.index) | set(sb.index)):
        if k in exclude:
            continue
        rows.append((float(sb.get(k, 0) - sa.get(k, 0)), k, float(sa.get(k, 0)), float(sb.get(k, 0)),
                     int((b == k).sum()), len(b)))
    rows.sort(key=lambda r: (-r[0], r[1]))
    return rows[0] if rows else None


# ── insight rules ──────────────────────────────────────────────────────────

def insight_volume(per_year, full, ref, partial, ref_year):
    if full not in per_year.index or (full - 1) not in per_year.index:
        return None
    a, b = int(per_year[full]), int(per_year[full - 1])
    if b < 30:
        return None
    ch = (a - b) / b
    trend = (f"ללא שינוי של ממש לעומת {full - 1} ({n(b)})" if abs(ch) < FLAT_CHANGE
             else f"{'עלייה' if ch > 0 else 'ירידה'} של {pct(abs(ch))} לעומת {full - 1} ({n(b)})")
    s = f"ב-{full} נפתחו ביחידה {n(a)} תיקים — {trend}."
    if partial and ref_year in per_year.index:
        s += f" ב-{ref_year} נרשמו {n(per_year[ref_year])} תיקים עד {d_he(ref)}, התאריך האחרון במאגר."
    return s


def insight_topic_shift(era, first, last):
    r = _share_shift(era, "topic", first, last, exclude=("אחר", "לא צוין"))
    if not r or r[0] * 100 < SHIFT_PP:
        return None
    gain, k, sa, sb, cnt, tot = r
    return (f"הנושא שחלקו גדל יותר מכול הוא {k}: {pct(sb)} מהתיקים ב-{last} ({n(cnt)} מתוך {n(tot)}), "
            f"לעומת {pct(sa)} ב-{first}.")


def insight_type_topic(era):
    tv = _vc(era["type"][era["type"] != NO_TYPE])
    if tv.empty:
        return None
    lead = tv.index[0]
    sub = era[era["type"] == lead]
    if len(sub) < 30:
        return None
    top = _vc(sub["topic"])
    share = top.iloc[0] / len(sub)
    if share < 0.4:
        return None
    return (f"סוג התיק הנפוץ ביותר הוא {lead} ({n(len(sub))} תיקים, {pct(len(sub) / len(era))}); "
            f"{pct(share)} מהם עוסקים ב{top.index[0]}.")


def insight_source_shift(era, first, last):
    r = _share_shift(era, "source", first, last, exclude=("לא צוין",))
    if not r or r[0] * 100 < SHIFT_PP:
        return None
    gain, k, sa, sb, cnt, tot = r
    return (f"הגורם הפונה שחלקו עלה יותר מכול הוא {k}: {pct(sb)} מהתיקים ב-{last} ({n(cnt)}), "
            f"לעומת {pct(sa)} ב-{first}.")


def insight_open(df):
    if len(df) < 50:
        return None
    vc = df["status"].value_counts()
    op = int(vc.get("פתוח", 0))
    cl = int(vc.get("סגור", 0))
    share = op / len(df)
    if share < 0.5:
        return None
    return (f"{pct(share)} מהתיקים במאגר ({n(op)}) רשומים כפתוחים, ורק {n(cl)} מסומנים כסגורים.")


def insight_legacy(df, era_start):
    old = df[df["year"] < era_start]
    if len(old) < MIN_CAT:
        return None
    fol = df[df["status"] == "במעקב"]
    untyped = int((old["type"] == NO_TYPE).sum())
    if untyped / len(old) < 0.8:
        return None
    what = "כולם ללא סוג תיק" if untyped == len(old) else f"{n(untyped)} מהם ללא סוג תיק"
    s = (f"{n(len(old))} תיקים ({pct(len(old) / len(df))}) נרשמו לפני {era_start}, {what} — "
         f"רשימה ותיקה מלפני הרישום הסדיר")
    if len(fol) >= MIN_CAT and (fol["year"] < era_start).mean() >= 0.9:
        allf = (fol["year"] < era_start).all()
        s += f"; {'כל' if allf else 'כמעט כל'} התיקים בסטטוס \"במעקב\" ({n(len(fol))}) שייכים אליה."
    else:
        s += "."
    return s


def insight_lag(lag):
    if len(lag) < 50:
        return None
    med = float(lag.median())
    same = float((lag <= 0).mean())
    long_ = float((lag > 90).mean())
    if same >= 0.5:
        return (f"{pct(same)} מהתיקים נפתחו ביום קבלת הפנייה או לפניו; "
                f"{pct(long_)} נפתחו יותר משלושה חודשים אחריה.")
    return (f"החציון של הזמן בין קבלת הפנייה לפתיחת התיק הוא {n(round(med))} ימים; "
            f"{pct(long_)} נפתחו יותר משלושה חודשים אחריה.")


def insight_victims(vic, era_total):
    if len(vic) < 20:
        return None
    top = _vc(vic["topic"][~vic["topic"].isin(["אחר", "לא צוין"])])
    top = top[top >= MIN_CAT]
    if top.empty:
        return None
    return (f"{n(len(vic))} תיקים הם פניות של קרבנות או בקשות להכרה כקרבן סחר "
            f"({pct(len(vic) / era_total)} מהתיקים מאז שנת הרישום הסדיר); הנושא השכיח בהם הוא "
            f"{top.index[0]} ({n(top.iloc[0])}).")


# ── model ──────────────────────────────────────────────────────────────────

def compute(frames):
    df = _prepare(frames["cases"])
    total = len(df)
    ref = df["created"].max()
    ref_year = int(ref.year)
    partial = not (ref.month == 12 and ref.day >= 24)
    full = ref_year - 1 if partial else ref_year
    era_start = _era_start(df)
    era = df[df["year"] >= era_start]
    legacy_n = total - len(era)
    first_full = era_start if era_start < full else full

    # yearly × status (all years)
    years = list(range(int(df["year"].min()), ref_year + 1))
    per_year = df.groupby("year").size()
    ys = df.groupby(["year", "status"]).size()
    statuses = [s for s in STATUS_ORDER if s in set(df["status"])] + \
        sorted(s for s in set(df["status"]) if s not in STATUS_ORDER)
    yearly = {"x": [str(y) for y in years],
              "series": [{"name": s, "data": [int(ys.get((y, s), 0)) for y in years]} for s in statuses]}

    # month × year heatmap (era)
    era_years = list(range(era_start, ref_year + 1))
    my = era.groupby([era["year"], era["created"].dt.month]).size()
    cells = []
    for yi, y in enumerate(era_years):
        for m in range(1, 13):
            if y == ref_year and m > ref.month:
                continue
            cells.append([m - 1, yi, int(my.get((y, m), 0))])
    vals = sorted(c[2] for c in cells)
    # colour scale tops out at the 95th percentile so one bulk-entry month
    # doesn't wash out the rest (cells above it share the darkest shade)
    vmax = max(vals[int(0.95 * (len(vals) - 1))] if vals else 1, 1)
    mheat = {"x": MONTHS_SHORT, "y": [str(y) for y in era_years], "cells": cells, "max": vmax}
    peak_cell = max(cells, key=lambda c: (c[2], -c[1], -c[0])) if cells else [0, 0, 0]

    # topics (all rows)
    topics, topics_merged = _merge_small(_vc(df["topic"]), "אחר ונושאים נוספים", "אחר")
    sources, sources_merged = _merge_small(_vc(df["source"]), "גורמים נוספים")
    types, types_merged = _merge_small(_vc(df["type"]), "אחר וסוגים נוספים", "אחר")

    # topic trend (era): top-N + אחר, counts
    tv = _vc(era["topic"])
    trend_topics = [k for k in tv.index if k != "אחר"][:TOP_TOPICS_TREND]
    ty = era.groupby(["year", "topic"]).size()
    tt_series = []
    for k in trend_topics:
        tt_series.append({"name": k, "data": [int(ty.get((y, k), 0)) for y in era_years]})
    ey = era.groupby("year").size()
    tt_series.append({"name": "אחר", "data": [int(ey.get(y, 0)) - sum(s["data"][i] for s in tt_series)
                                            for i, y in enumerate(era_years)]})
    topic_trend = {"x": [str(y) for y in era_years], "series": tt_series}

    # source trend (era): share by year
    sv = _vc(era["source"])
    trend_sources = list(sv.index[:TOP_SOURCES_TREND])
    sy = era.groupby(["year", "source"]).size()
    st_series = []
    for k in trend_sources:
        st_series.append({"name": k, "data": [round(int(sy.get((y, k), 0)) / int(ey[y]) * 100, 1)
                                              if ey.get(y, 0) else 0.0 for y in era_years]})
    st_series.append({"name": "אחר", "data": [max(round(100 - sum(s["data"][i] for s in st_series), 1), 0.0)
                                            for i in range(len(era_years))]})
    source_trend = {"x": [str(y) for y in era_years], "series": st_series}

    # type × topic heatmap (era), cells < MIN_CAT suppressed
    etv = _vc(era["type"])
    h_types = list(etv.index[:HEAT_TYPES])
    h_topics = [k for k in tv.index][:HEAT_TOPICS]
    tt = era.groupby(["type", "topic"]).size()
    hcells, hlow = [], []
    for xi, t in enumerate(h_topics):
        for yi, ty_ in enumerate(h_types):
            v = int(tt.get((ty_, t), 0))
            if v >= MIN_CAT:
                hcells.append([xi, yi, v])
            elif v > 0:
                hlow.append([xi, yi])
    theat = {"x": h_topics, "y": h_types, "cells": hcells, "low": hlow, "low_label": f"פחות מ-{MIN_CAT}",
             "max": max((c[2] for c in hcells), default=MIN_CAT)}

    # victim-facing files by topic (era), small topics merged
    vic = era[era["type"].isin(VICTIM_TYPES)]
    vic_items, _ = _merge_small(_vc(vic["topic"]), "אחר ונושאים נוספים", "אחר")
    victims = {"names": [k for k, _ in vic_items], "values": [v for _, v in vic_items]}

    # referral → opening lag
    lag_m = df["referred"].notna() & df["opened"].notna()
    lag = (df.loc[lag_m, "opened"] - df.loc[lag_m, "referred"]).dt.days
    lag_labels, lag_vals = [], []
    for lo, hi in LAG_BINS:
        if lo is None:
            lag_labels.append("לפני הפנייה")
            lag_vals.append(int((lag <= hi).sum()))
        elif hi is None:
            lag_labels.append(f"{RLM}יותר משנה")
            lag_vals.append(int((lag >= lo).sum()))
        elif lo == hi == 0:
            lag_labels.append("באותו יום")
            lag_vals.append(int((lag == 0).sum()))
        else:
            lag_labels.append(f"{RLM}{lo} עד {hi} ימים")
            lag_vals.append(int(((lag >= lo) & (lag <= hi)).sum()))
    no_lag = total - int(lag_m.sum())

    # case vs referral status
    s_case = df["status"].value_counts()
    s_ref = df["ref_status"].value_counts()
    st_names = statuses + sorted(k for k in s_ref.index if k not in statuses)
    status_chart = {"cats": ["סטטוס התיק", "סטטוס הפנייה"],
                    "series": [{"name": k, "data": [int(s_case.get(k, 0)), int(s_ref.get(k, 0))]}
                               for k in st_names]}

    rules = [
        ("volume", insight_volume(per_year, full, ref, partial, ref_year)),
        ("topic_shift", insight_topic_shift(era, first_full, full)),
        ("type_topic", insight_type_topic(era)),
        ("source_shift", insight_source_shift(era, first_full, full)),
        ("victims", insight_victims(vic, len(era))),
        ("lag", insight_lag(lag)),
        ("open", insight_open(df)),
        ("legacy", insight_legacy(df, era_start)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    full_v = int(per_year.get(full, 0))
    prev_v = int(per_year.get(full - 1, 0))
    last_tone = "info" if prev_v and abs(full_v - prev_v) / prev_v >= 0.10 else "brand"
    open_share = float((df["status"] == "פתוח").mean())
    closed_n = int((df["status"] == "סגור").sum())
    # open share likely reflects unrecorded closures, not a backlog — neutral context
    open_tone = "info"
    kpis = {
        "total": {"value": total, "display": n(total), "tone": "brand"},
        "last_year": {"value": full_v, "display": n(full_v), "tone": last_tone},
        "open": {"value": round(open_share * 100, 1), "display": f"{open_share * 100:.1f}%", "tone": open_tone},
        "latest": {"value": ref.strftime("%Y-%m-%d"), "display": ref.strftime("%d.%m.%Y"), "tone": "brand"},
    }

    top_topic = topics[0][0] if topics else ""
    merged_note = (f" נושאים עם פחות מ-{MIN_CAT} תיקים כל אחד ({n(len(topics_merged))} נושאים) "
                   f"מקובצים יחד, כדי לא להבליט תיקים בודדים." if topics_merged else "")
    labels = {
        "lede": (f"{n(total)} תיקים, פניות ואירועים שבטיפול היחידה לתיאום המאבק בסחר בבני אדם "
                 f"במשרד המשפטים, מ-{years[0]} ועד {d_he(ref)} — לפי שנה, נושא, סוג התיק, הגורם הפונה "
                 f"וסטטוס הטיפול. הרישום הסדיר, עם סוג תיק לכל רשומה, מתחיל ב-{era_start}. "
                 f"הדף מציג נתונים מצרפיים בלבד; קטגוריות ותאים קטנים מקובצים או מוסתרים."),
        "last_year_kpi": f"תיקים שנפתחו ב-{full}",
        "open_kpi": "מהתיקים רשומים כפתוחים",
        "latest_kpi": "תאריך הרשומה האחרונה במאגר",
        "yearly_note": (f"מספר התיקים לפי שנת היצירה, ולפי סטטוס הטיפול הנוכחי."
                        + (f" {ref_year} — שנה חלקית, עד {d_he(ref)}." if partial else "")),
        "yearly_aria": (f"גרף עמודות מוערמות: תיקים לפי שנה וסטטוס, {years[0]}–{years[-1]}. "
                        f"השיא ב-{int(per_year.idxmax())}."),
        "yearly_caption": f"תיקים לפי שנת יצירה וסטטוס, {years[0]}–{years[-1]}.",
        "mheat_note": (f"מספר התיקים שנוצרו בכל חודש, מ-{era_start}. החודש העמוס ביותר: "
                       f"{MONTHS_HE[peak_cell[0]]} {era_years[peak_cell[1]]} ({n(peak_cell[2])} תיקים)."
                       + (f" סולם הצבעים נעצר ב-{n(vmax)}; חודשים מעליו בגוון הכהה ביותר."
                          if peak_cell[2] > vmax else "")),
        "mheat_aria": f"מפת חום: תיקים לפי חודש ושנה, {era_start}–{ref_year}.",
        "topics_note": f"כל התקופה. הנושא המוביל: {top_topic}.{merged_note}",
        "topics_aria": "תרשים עמודות: מספר התיקים לפי נושא.",
        "topics_caption": "מספר התיקים לפי נושא התיק.",
        "ttrend_note": (f"מספר התיקים בכל שנה ב-{len(trend_topics)} הנושאים הנפוצים מאז {era_start}; "
                        f"שאר הנושאים מקובצים ב'אחר'."),
        "ttrend_aria": f"גרף עמודות מוערמות: תיקים לפי נושא ושנה, {era_start}–{ref_year}.",
        "ttrend_caption": f"תיקים לפי נושא ושנה, {era_start}–{ref_year}.",
        "types_note": (f"מתיקי בית משפט וניסוח נהלים ועד פניות של קרבנות ודיווחים בינלאומיים. "
                       f"{n(legacy_n)} רשומות ותיקות ללא סוג מוצגות כ'{NO_TYPE}'."),
        "types_aria": "תרשים עמודות: מספר התיקים לפי סוג התיק.",
        "types_caption": "מספר התיקים לפי סוג התיק.",
        "sources_note": (f"מי פנה ליחידה — לאורך כל התקופה."
                         + (f" גורמים עם פחות מ-{MIN_CAT} תיקים מקובצים יחד." if sources_merged else "")),
        "sources_aria": "תרשים עמודות: מספר התיקים לפי הגורם הפונה.",
        "sources_caption": "מספר התיקים לפי הגורם הפונה.",
        "strend_note": (f"חלקו של כל גורם פונה מסך התיקים בכל שנה, באחוזים — {len(trend_sources)} "
                        f"הגורמים המובילים מאז {era_start}; השאר ב'אחר'."),
        "strend_aria": "גרף שטח מוערם: חלקם של הגורמים הפונים בתיקים בכל שנה, באחוזים.",
        "strend_caption": "חלקם של הגורמים הפונים לפי שנה, באחוזים.",
        "theat_note": (f"כמה תיקים מכל סוג עוסקים בכל נושא, מ-{era_start} — {len(h_types)} הסוגים "
                       f"ו-{len(h_topics)} הנושאים הנפוצים. תאים עם פחות מ-{MIN_CAT} תיקים מסומנים "
                       f"באפור, ללא מספר."),
        "theat_aria": "מפת חום: תיקים לפי סוג התיק ונושא.",
        "victims_note": (f"תיקים מסוג פניות של קרבנות ובקשות להכרה כקרבן סחר, מ-{era_start}, לפי נושא. "
                         f"נושאים עם פחות מ-{MIN_CAT} תיקים מקובצים יחד."),
        "victims_aria": "תרשים עמודות: פניות של קרבנות ובקשות להכרה לפי נושא.",
        "victims_caption": "פניות של קרבנות ובקשות להכרה לפי נושא.",
        "lag_note": (f"הזמן שחלף מתאריך הפנייה ועד פתיחת התיק. {n(no_lag)} תיקים ללא אחד התאריכים "
                     f"אינם נכללים."),
        "lag_aria": "תרשים עמודות: תיקים לפי הזמן מהפנייה ועד פתיחת התיק.",
        "lag_caption": "מספר התיקים לפי הזמן מהפנייה ועד פתיחת התיק.",
        "status_note": (f"סטטוס התיק לעומת סטטוס הפנייה שבעקבותיה נפתח. {n(closed_n)} תיקים בלבד "
                        f"רשומים כסגורים."),
        "status_aria": "תרשים עמודות מוערמות: התפלגות סטטוס התיק וסטטוס הפנייה.",
        "status_caption": "מספר התיקים לפי סטטוס התיק וסטטוס הפנייה.",
    }

    def bar(items):
        return {"names": [k for k, _ in items], "values": [v for _, v in items]}

    tables = {
        "yearly": [{"year": str(y), "total": n(per_year.get(y, 0)),
                    "cells": [n(s["data"][i]) for s in yearly["series"]]}
                   for i, y in enumerate(years)],
        "status_names": statuses,
        "topics": [{"name": k, "count": n(v)} for k, v in topics],
        "ttrend_names": [s["name"] for s in tt_series],
        "ttrend": [{"year": str(y), "cells": [n(s["data"][i]) for s in tt_series]}
                   for i, y in enumerate(era_years)],
        "types": [{"name": k, "count": n(v)} for k, v in types],
        "sources": [{"name": k, "count": n(v)} for k, v in sources],
        "strend_names": [s["name"] for s in st_series],
        "strend": [{"year": str(y), "cells": [f"{s['data'][i]:.1f}%" for s in st_series]}
                   for i, y in enumerate(era_years)],
        "victims": [{"name": k, "count": n(v)} for k, v in vic_items],
        "lag": [{"bin": k, "count": n(v)} for k, v in zip(lag_labels, lag_vals)],
        "status": [{"name": s["name"], "case": n(s["data"][0]), "ref": n(s["data"][1])}
                   for s in status_chart["series"]],
    }

    return {
        "agent_data": {
            "summary_he": (f"{n(total)} תיקים, פניות ואירועים של היחידה לתיאום המאבק בסחר בבני אדם "
                           f"במשרד המשפטים, {years[0]}–{ref_year}: לפי נושא (המוביל — {top_topic}), סוג "
                           f"התיק, הגורם הפונה וסטטוס. הרשומה האחרונה מ-{ref.day}/{ref.month}/{ref.year}."),
            "dataset_kind": "timeseries",
            "related_ids": ["13449cdd-9d02-44cf-b298-82f598369cd7",
                            "cf92190d-eec4-4906-beec-26fd2e2bb83d",
                            "176f2727-476e-440e-bc8d-5d3461ea0e76"],
            "suggested_tags": ["סחר בבני אדם", "משרד המשפטים", "פונדקאות", "עובדים זרים",
                               "זכויות אדם", "קרבנות סחר"],
            "temporal_coverage": f"{df['created'].min().strftime('%Y-%m-%d')}/{ref.strftime('%Y-%m-%d')}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": {
            "yearly": yearly,
            "mheat": mheat,
            "topics": bar(topics),
            "ttrend": topic_trend,
            "types": bar(types),
            "sources": bar(sources),
            "strend": source_trend,
            "theat": theat,
            "victims": victims,
            "lag": {"names": lag_labels, "values": lag_vals},
            "status": status_chart,
        },
        "tables": tables,
        "insights": insights,
        "labels": labels,
        "flags": {"victims": len(vic_items) > 0 and len(vic) >= MIN_CAT},
    }
