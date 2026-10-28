"""מאגר החברות המיועדות למחיקה — Companies Registrar (רשות התאגידים).

A rolling list, refreshed daily: a company enters when the Registrar
publishes it as slated for deletion under chapter 3A of part 9 of the
Companies Law (the usual trigger is unpaid annual fees / unfiled reports)
and leaves once it is struck off or the proceeding is cancelled. Each row
carries the publication date and the expected deletion date if no
objection is filed (publication + a fixed objection window).

Publication happens in waves: one mass publication carries almost the whole
list, plus a trickle of single publications. "Now" is the latest
publication date in the file — never the wall clock. Rows whose expected
deletion date already precedes it are "past the window": the objection
period is over but the company is still listed (deletion not yet
executed).

Companies are businesses and may be named; the company number is the
public corporate identifier and appears only beside the name in the
named tables. There are no addresses or c/o names in this file.
"""
import re

import pandas as pd

MAX_WAVE_ROWS = 20      # above this many distinct publication dates → months
TOP_WORDS = 15
TOP_FLAGS = 8
RECENT_DAYS = 30
RECENT_MAX = 15
REVIVAL_MAX = 15
YEAR_BIN = 5
MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]
STATUS_ORDER = ["פעילה", "בפרוק מרצון", "מחוסלת מרצון", "חיסול ע״י בימ״ש", "מחוקה"]
BASE_SUB = "בהליכי מחיקה"
REVIVAL_KEY = "החייאה"
FAST_TRACK = "בפרוק מרצון בהליך מזורז"
LAND_RE = re.compile(r"גוש|חלקה")
YEAR_RE = re.compile(r"\((\d{4})\)")
WORD_RE = re.compile(r"[א-ת][א-ת״׳'\"]*")
# Words that carry no theme: legal suffixes, "company", land-parcel words
# (counted on their own) and Hebrew transliterations of Latin letters.
STOP = {"בע״מ", "בעמ", "חברה", "חברת", "החברה", "גוש", "בגוש", "חלקה", "בחלקה",
        "איי", "אי", "אס", "סי", "די", "טי", "בי", "אר", "אם", "אל", "ג׳י", "אן",
        "אף", "וי", "קיי", "פי", "אמ", "ג׳יי", "אנד", "של", "את", "עם", "על"}
LRI, PDI = "⁦", "⁩"


def n(v):
    return f"{int(v):,}"


def pct(v, digits=1):
    return f"{LRI}{v:.{digits}f}%{PDI}"


def d_he(ts):
    return f"{ts.day} ב{MONTHS_HE[ts.month - 1]} {ts.year}"


def d_short(ts):
    return f"{ts.day:02d}.{ts.month:02d}.{ts.year}"


def clean(s):
    # The registry export writes gershayim as "~" (בע~מ, ע~י, בימ~ש) and
    # sometimes wraps a quoted name part in ~…~.
    return " ".join(s.replace("~", "״").split())


def _vc(s):
    return s.value_counts().sort_index().sort_values(ascending=False, kind="stable")


def _top(counts, k):
    counts = counts.sort_index().sort_values(ascending=False, kind="stable")
    top = counts.head(k)
    other = int(counts.iloc[k:].sum())
    names = list(top.index) + (["אחר"] if other else [])
    vals = [int(v) for v in top.values] + ([other] if other else [])
    return names, vals


def _prepare(df):
    out = pd.DataFrame({
        "num": df["מספר התאגיד"].str.strip(),
        "name": df["שם התאגיד"].map(clean),
        "en": df["שם התאגיד באנגלית"].str.strip(),
        "kind": df["סוג תאגיד"].str.strip().replace("", "לא צוין"),
        "status": df["סטטוס התאגיד"].map(clean).replace("", "לא ידוע"),
        "sub": df["תת סטטוס התאגיד"].map(clean),
        "pub": pd.to_datetime(df["מועד פרסום סטטוס ~מיועדת למחיקה~"].str.strip(),
                              format="%d/%m/%Y", errors="coerce"),
        "exp": pd.to_datetime(df["מועד המחיקה הצפוי אם לא תוגש התנגד"].str.strip(),
                              format="%d/%m/%Y", errors="coerce"),
    })
    # Sub-status is a "~"-joined list (now "״"); keep the extra flags beside
    # the base "בהליכי מחיקה" one, de-duplicated.
    out["flags"] = df["תת סטטוס התאגיד"].map(
        lambda s: sorted({clean(p) for p in s.split("~") if clean(p)} - {BASE_SUB}))
    # Company numbers are allocated in sequence: the 3-digit prefix is a
    # coarse registration-era band (higher = registered later).
    pre = out["num"].str[:3]
    out["series"] = pre.where(pre.str.fullmatch(r"\d{3}"), "אחר")
    out["land"] = out["name"].str.contains(LAND_RE)
    return out


# ---------------------------------------------------------------- insights

def insight_wave(waves, total):
    if waves.empty or total == 0:
        return None
    day = waves.sort_index().sort_values(ascending=False, kind="stable").index[0]
    v = int(waves[day])
    share = v / total
    if share < 0.5:
        return None
    rest = total - v
    others = len(waves) - 1
    tail = ""
    if rest:
        tail = (f"; {n(rest)} החברות האחרות פורסמו ב-{n(others)} "
                f"{'מועד נוסף' if others == 1 else 'מועדים נוספים'}")
    return (f"הרשימה היא בעיקר גל פרסום אחד: {n(v)} חברות ({pct(share * 100)}) פורסמו כמיועדות "
            f"למחיקה ביום אחד, {d_he(day)}{tail}.")


def insight_window(gaps):
    g = gaps.dropna()
    if g.empty:
        return None
    mode = int(_vc(g).index[0])
    share = (g == mode).mean()
    if share < 0.9:
        return None
    every = "בכל החברות" if share == 1 else f"ב-{pct(share * 100)} מהחברות"
    return (f"{every} מועד המחיקה הצפוי נקבע {mode} ימים בדיוק לאחר הפרסום — זה חלון הזמן "
            f"להגשת התנגדות למחיקה.")


def insight_overdue(past, total, ref):
    k = len(past)
    if k == 0 or total == 0:
        return None
    lag = int((ref - past["exp"].max()).days)
    first = past["exp"].min()
    s = (f"ל-{n(k)} חברות ({pct(k / total * 100)}) חלף כבר מועד המחיקה הצפוי — המוקדם "
         f"שבמועדים {d_he(first)} — והן עדיין ברשימה")
    if lag > 0:
        s += (f"; גם המאוחר שבמועדים האלה קדם ב-{n(lag)} ימים לפרסום האחרון במאגר "
              f"({d_he(ref)})")
    return s + ". חלון ההתנגדות שלהן הסתיים, אך המחיקה עצמה טרם בוצעה."


def insight_active(status, total):
    active = int(status.get("פעילה", 0))
    if total == 0 or active / total < 0.5:
        return None
    rest = total - active
    tail = f"; {n(rest)} האחרות כבר בהליך יציאה אחר — פירוק או חיסול" if rest else ""
    return (f"{pct(active / total * 100)} מהחברות ברשימה עדיין רשומות במעמד ״פעילה״ — "
            f"ההליך מסמן אותן למחיקה אך טרם שינה את מעמדן{tail}.")


def insight_liq(df):
    fast = df["flags"].map(lambda f: FAST_TRACK in f)
    vol = df["status"].isin(["בפרוק מרצון", "מחוסלת מרצון"])
    k = int((fast | vol).sum())
    if k == 0:
        return None
    s = (f"{n(k)} חברות ברשימה נמצאות במקביל גם במסלול של פירוק מרצון (לפי המעמד או "
         f"תת-הסטטוס) — סגירה ביוזמת בעלי החברה, לצד הליך המחיקה של הרשם")
    if int(fast.sum()):
        s += f"; {n(int(fast.sum()))} מהן מסומנות ״{FAST_TRACK}״"
    return s + "."


def insight_revival(df):
    rev = df[df["flags"].map(lambda f: any(REVIVAL_KEY in x for x in f))]
    if rev.empty:
        return None
    return (f"ל-{n(len(rev))} חברות ברשימה רשום בתת-הסטטוס גם ״הוגשה בקשה להחייאה״ — "
            f"רשימתן בטבלה בהמשך.")


def insight_land(df):
    land = df[df["land"]]
    if len(land) < 20:
        return None
    ser = _vc(land["series"])
    top_s, top_v = ser.index[0], int(ser.iloc[0])
    share_in = top_v / len(land)
    base = (df["series"] == top_s).mean()
    if share_in < 0.5 or share_in < 2 * base:
        return None
    return (f"{n(len(land))} חברות נושאות בשמן ״גוש״ או ״חלקה״ — חברות שהוקמו להחזקת חלקת "
            f"קרקע; {pct(share_in * 100)} מהן בסדרת המספרים הוותיקה {top_s}, לעומת "
            f"{pct(base * 100)} מכלל הרשימה.")


def insight_english(df):
    ser = df[df["series"] != "אחר"].groupby("series")["en"].agg(
        count="size", en=lambda s: (s != "").mean()).sort_index()
    ser = ser[ser["count"] >= 100]
    if len(ser) < 3:
        return None
    old, new = ser.iloc[0], ser.iloc[-1]
    if new["en"] - old["en"] < 0.2:
        return None
    total_share = (df["en"] != "").mean()
    return (f"{pct(total_share * 100)} מהחברות רשומות גם בשם לועזי, והשיעור גבוה יותר "
            f"בחברות הצעירות: {pct(old['en'] * 100)} בסדרה {ser.index[0]} לעומת {pct(new['en'] * 100)} "
            f"בסדרה {ser.index[-1]}.")


def insight_words(words, total):
    if not words or total == 0:
        return None
    w, v = words[0]
    if v / total < 0.02:
        return None
    top3 = "״, ״".join(x for x, _ in words[:3])
    return (f"המילים הנפוצות בשמות החברות הן ״{top3}״; ״{w}״ לבדה מופיעה ב-{n(v)} שמות "
            f"({pct(v / total * 100)}).")


# ------------------------------------------------------------------ helpers

def _words(names):
    """Theme words in names; a leading ו/ל/ה is folded into the bare word when
    the bare word itself occurs (והשקעות → השקעות)."""
    per_name = [set(WORD_RE.findall(s)) for s in names]
    vocab = set().union(*per_name) if per_name else set()
    counts = {}
    for toks in per_name:
        seen = set()
        for t in toks:
            if len(t) > 3 and t[0] in "ולה" and t[1:] in vocab:
                t = t[1:]
            if t in STOP or len(t) < 3:
                continue
            seen.add(t)
        for t in seen:
            counts[t] = counts.get(t, 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


def compute(frames):
    df = _prepare(frames["main"])
    df = df[df["pub"].notna()].copy()
    total = len(df)
    ref = df["pub"].max()
    df["gap"] = (df["exp"] - df["pub"]).dt.days
    past = df[df["exp"].notna() & (df["exp"] < ref)]

    # ---- publication waves (by day, or by month if they ever get many)
    by_day = df.groupby("pub").agg(count=("num", "size"), exp=("exp", "max"),
                                   lo=("pub", "min")).sort_index()
    by_month = len(by_day) > MAX_WAVE_ROWS
    if by_month:
        per = df["pub"].dt.to_period("M")
        g = df.groupby(per).agg(count=("num", "size"), lo=("pub", "min"),
                                exp=("exp", "max")).sort_index()
        w_labels = [f"{MONTHS_HE[p.month - 1]} {p.year}" for p in g.index]
    else:
        g = by_day
        w_labels = [d_short(d) for d in g.index]
    w_counts = [int(v) for v in g["count"]]
    w_lo = [d.strftime("%Y-%m-%d") for d in g["lo"]]
    w_exp = [d.strftime("%Y-%m-%d") if pd.notna(d) else None for d in g["exp"]]
    w_open = [bool(pd.notna(e) and e >= ref) for e in g["exp"]]
    waves_chart = {"x": w_labels, "y": w_counts}
    gantt = {"labels": w_labels, "start": w_lo, "end": w_exp, "count": w_counts,
             "open": w_open, "ref": ref.strftime("%Y-%m-%d")}
    waves_table = [{"label": lab, "count": n(c),
                    "exp": d_short(e) if pd.notna(e) else "—",
                    "state": "פתוח" if o else "חלף"}
                   for lab, c, e, o in zip(w_labels, w_counts, g["exp"], w_open)]

    # ---- status + extra sub-status flags
    st = df["status"].value_counts()
    st_names = [s for s in STATUS_ORDER if s in st.index] + sorted(
        s for s in st.index if s not in STATUS_ORDER)
    st_vals = [int(st[s]) for s in st_names]
    status_series = pd.Series(st_vals, index=st_names, dtype="int64")
    flag_counts = pd.Series([f for lst in df["flags"] for f in lst], dtype=str).value_counts()
    f_names, f_vals = _top(flag_counts, TOP_FLAGS)
    no_flag = int((df["flags"].map(len) == 0).sum())

    # ---- company-number series × English name share × land companies
    ser = df.groupby("series").agg(count=("num", "size"),
                                   en=("en", lambda s: int((s != "").sum())),
                                   land=("land", "sum")).sort_index()
    series_chart = {
        "x": list(ser.index),
        "count": [int(v) for v in ser["count"]],
        "en": [round(e / c * 100, 1) for e, c in zip(ser["en"], ser["count"])],
    }

    # ---- theme words in names
    words = _words(df.sort_values("num", kind="stable")["name"].tolist())
    top_words = words[:TOP_WORDS]
    words_chart = {"names": [w for w, _ in top_words], "values": [v for _, v in top_words]}

    # ---- year written in the name, e.g. "(1998)"
    yr = pd.to_numeric(df["name"].str.extract(YEAR_RE)[0], errors="coerce")
    yr = yr[(yr >= 1948) & (yr <= ref.year)]
    years_chart, years_table = {"x": [], "labels": [], "tips": [], "y": []}, []
    if len(yr):
        b = (yr // YEAR_BIN * YEAR_BIN).astype(int)
        bins = range(int(b.min()), int(b.max()) + 1, YEAR_BIN)
        bc = b.value_counts().reindex(bins, fill_value=0).sort_index()
        years_chart = {"x": [f"{s}–{s + YEAR_BIN - 1}" for s in bc.index],
                       # canvas axis shows the bin's first year (a range string
                       # renders reversed on the RTL canvas); tooltip gets the range
                       "labels": [str(s) for s in bc.index],
                       "tips": [f"{s} עד {s + YEAR_BIN - 1}" for s in bc.index],
                       "y": [int(v) for v in bc.values]}
        years_table = [{"label": x, "count": n(v)} for x, v in zip(years_chart["x"], years_chart["y"])]
    yr_peak = (years_chart["x"][max(range(len(years_chart["y"])),
                                    key=lambda i: (years_chart["y"][i], -i))]
               if years_chart["y"] else "")

    # ---- named tables
    recent = df[df["pub"] > ref - pd.Timedelta(days=RECENT_DAYS)]
    recent_rows = [{"name": r["name"], "num": r["num"], "pub": d_short(r["pub"]),
                    "exp": d_short(r["exp"]) if pd.notna(r["exp"]) else "—",
                    "status": r["status"]}
                   for _, r in recent.sort_values(["pub", "num"], ascending=[False, True],
                                                  kind="stable").head(RECENT_MAX).iterrows()]
    rev = df[df["flags"].map(lambda f: any(REVIVAL_KEY in x for x in f))]
    revival_rows = [{"name": r["name"], "num": r["num"], "status": r["status"],
                     "flags": "; ".join(r["flags"]), "pub": d_short(r["pub"])}
                    for _, r in rev.sort_values(["pub", "num"], kind="stable")
                    .head(REVIVAL_MAX).iterrows()]

    # ---- KPIs
    active = int(status_series.get("פעילה", 0))
    active_share = active / total * 100 if total else 0.0
    kpis = {
        "total": {"value": total, "display": n(total), "tone": "brand"},
        "active": {"value": round(active_share, 1), "display": f"{active_share:.1f}%",
                   "tone": "info"},
        "past": {"value": len(past), "display": n(len(past)),
                 "tone": "warn" if len(past) else "ok"},
        "recent": {"value": len(recent), "display": n(len(recent)), "tone": "info"},
    }

    rules = [
        ("wave", insight_wave(by_day["count"], total)),
        ("overdue", insight_overdue(past, total, ref)),
        ("window", insight_window(df["gap"])),
        ("active", insight_active(status_series, total)),
        ("liq", insight_liq(df)),
        ("revival", insight_revival(df)),
        ("land", insight_land(df)),
        ("english", insight_english(df)),
        ("words", insight_words(words, total)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    gap_mode = int(_vc(df["gap"].dropna()).index[0]) if df["gap"].notna().any() else None
    gap_txt = f"{gap_mode} ימים" if gap_mode is not None else "פרק זמן קבוע"
    kinds = _vc(df["kind"])
    kind_txt = (f"כל החברות ברשימה הן {kinds.index[0]}" if len(kinds) == 1
                else f"רוב החברות ברשימה ({n(kinds.iloc[0])}) הן {kinds.index[0]}")
    big_i = max(range(len(w_counts)), key=lambda i: (w_counts[i], -i)) if w_counts else 0
    unit = "חודש" if by_month else "מועד"
    land_n = int(df["land"].sum())
    yr_n = len(yr)
    flags_total = total - no_flag

    labels = {
        "lede": (f"רשימת החברות שרשם החברות פרסם כמיועדות למחיקה מהמרשם לפי פרק שלישי א׳ לחלק "
                 f"התשיעי בחוק החברות: {n(total)} חברות. {kind_txt}. אם לא תוגש התנגדות, החברה "
                 f"נמחקת {gap_txt} לאחר הפרסום, ואז היא יוצאת מהרשימה. הנתונים נכונים לפרסום "
                 f"האחרון במאגר, {d_he(ref)}."),
        "total_kpi": "חברות ברשימה",
        "active_kpi": "עדיין במעמד ״פעילה״",
        "past_kpi": f"חלף מועד המחיקה הצפוי (נכון ל-{d_short(ref)})",
        "recent_kpi": f"פורסמו ב-{RECENT_DAYS} הימים האחרונים",
        "waves_note": (f"מספר החברות שפורסמו בכל {unit} פרסום. ציר אנכי לוגריתמי — אחרת גל הפרסום "
                       f"הגדול ({n(w_counts[big_i]) if w_counts else 0} חברות ב-{w_labels[big_i] if w_labels else ''}) "
                       f"מסתיר את הפרסומים הבודדים."),
        "waves_aria": (f"גרף עמודות: חברות שפורסמו כמיועדות למחיקה לפי {unit} פרסום, "
                       f"{n(len(w_labels))} {'חודשים' if by_month else 'מועדים'}. הגדול: "
                       f"{w_labels[big_i] if w_labels else ''}, {n(w_counts[big_i]) if w_counts else 0} חברות."),
        "waves_caption": f"מספר החברות שפורסמו בכל {unit} פרסום, מועד המחיקה הצפוי ומצב חלון ההתנגדות.",
        "waves_col": "חודש פרסום" if by_month else "מועד פרסום",
        "gantt_note": (f"לכל {unit} פרסום: מהפרסום ועד מועד המחיקה הצפוי ({gap_txt}). הקו האנכי הוא "
                       f"הפרסום האחרון במאגר, {d_he(ref)}; חלון שהסתיים לפניו צבוע כהה — החברות "
                       f"שבו עדיין ברשימה אף שתקופת ההתנגדות תמה."),
        "gantt_aria": (f"תרשים ציר זמן: חלון ההתנגדות של כל {unit} פרסום, מהפרסום ועד מועד המחיקה הצפוי, "
                       f"ביחס לפרסום האחרון ב-{d_he(ref)}. {n(len(past))} חברות בחלונות שהסתיימו."),
        "status_note": (f"מעמד החברה במרשם. כל החברות נושאות את תת-הסטטוס ״{BASE_SUB}״; "
                        f"{n(active)} עדיין ״פעילה״."),
        "status_aria": (f"תרשים עמודות: חברות לפי מעמד במרשם. {st_names[0]}: {n(st_vals[0])}."
                        if st_names else "תרשים מעמד."),
        "status_caption": "מספר החברות לפי מעמד במרשם.",
        "flags_note": (f"הליכים נוספים הרשומים בתת-הסטטוס לצד ״{BASE_SUB}״ — ל-{n(flags_total)} חברות "
                       f"יש לפחות אחד. חברה יכולה לשאת יותר מסימון אחד."),
        "flags_aria": (f"תרשים עמודות: סימוני תת-סטטוס נוספים. הנפוץ: {f_names[0]}, {n(f_vals[0])} חברות."
                       if f_names else "תרשים סימונים."),
        "flags_caption": "מספר החברות הנושאות כל סימון תת-סטטוס נוסף.",
        "series_note": (f"מספרי חברה מוקצים ברצף, כך שסדרה גבוהה יותר (שלוש הספרות הראשונות) מציינת "
                        f"חברה שנרשמה מאוחר יותר. עמודות: מספר החברות בכל סדרה; קו: שיעור הרשומות גם "
                        f"בשם לועזי. {n(land_n)} חברות נושאות בשמן ״גוש״ או ״חלקה״."),
        "series_aria": ("גרף משולב: מספר החברות לפי סדרת מספר החברה (עמודות) ושיעור החברות הרשומות "
                        "גם בשם לועזי בכל סדרה (קו)."),
        "series_caption": "מספר החברות, שיעור הרשומות בשם לועזי וחברות ״גוש/חלקה״ לפי סדרת מספר החברה.",
        "words_note": (f"{TOP_WORDS} המילים הנפוצות בשמות החברות (מספר השמות שבהם מופיעה כל מילה), "
                       f"ללא ״בע״מ״, ״חברה״, ״גוש״/״חלקה״ ואותיות לועזיות בתעתיק. ״והשקעות״ או ״להשקעות״ נספרות "
                       f"כ״השקעות״."),
        "words_aria": (f"תרשים עמודות: המילים הנפוצות בשמות החברות. מובילה: {words_chart['names'][0]}, "
                       f"{n(words_chart['values'][0])} שמות." if top_words else "תרשים מילים."),
        "words_caption": "מספר שמות החברות שבהם מופיעה כל מילה.",
        "years_note": (f"{n(yr_n)} חברות ({pct(yr_n / total * 100 if total else 0)}) נושאות שנה "
                       f"בסוגריים בשמן, למשל ״(1998)״ — לרוב שנת ההקמה או הארגון מחדש. "
                       f"התפלגות השנים בקבוצות של {YEAR_BIN} (כל עמודה מסומנת בשנה הראשונה שלה); השיא: {LRI}{yr_peak}{PDI}."),
        "years_aria": (f"גרף עמודות: שנים המופיעות בסוגריים בשמות החברות, בקבוצות של {YEAR_BIN} שנים. "
                       f"השיא: {yr_peak}."),
        "years_caption": "מספר החברות לפי השנה הכתובה בשמן, בקבוצות שנים.",
        "recent_note": (f"החברות שפורסמו כמיועדות למחיקה ב-{RECENT_DAYS} הימים שעד {d_he(ref)}"
                        + (f" (מוצגות {RECENT_MAX} האחרונות מתוך {n(len(recent))})."
                           if len(recent) > RECENT_MAX else ".")),
        "recent_caption": "החברות שפורסמו לאחרונה כמיועדות למחיקה.",
        "revival_note": (f"חברות שהוגשה לגביהן בקשה להחייאה בזמן שהן ברשימה"
                         + (f" (מוצגות {REVIVAL_MAX} הראשונות מתוך {n(len(rev))})."
                            if len(rev) > REVIVAL_MAX else ".")),
        "revival_caption": "חברות ברשימה שהוגשה לגביהן בקשה להחייאה.",
    }

    tables = {
        "waves": waves_table,
        "status": [{"name": k, "count": n(v)} for k, v in zip(st_names, st_vals)],
        "flags": [{"name": k, "count": n(v)} for k, v in zip(f_names, f_vals)],
        "series": [{"series": x, "count": n(c), "en": f"{e:.1f}%", "land": n(l)}
                   for x, c, e, l in zip(series_chart["x"], series_chart["count"],
                                         series_chart["en"], ser["land"])],
        "words": [{"name": w, "count": n(v)} for w, v in top_words],
        "years": years_table,
        "recent": recent_rows,
        "revival": revival_rows,
    }

    charts = {
        "waves": waves_chart,
        "gantt": gantt,
        "status": {"names": st_names, "values": st_vals},
        "flags": {"names": f_names, "values": f_vals},
        "series": series_chart,
        "words": words_chart,
        "years": years_chart,
    }

    return {
        "agent_data": {
            "summary_he": (f"{n(total)} חברות פרטיות שפורסמו כמיועדות למחיקה מרשם החברות; "
                           f"{pct(active_share)} עדיין במעמד ״פעילה״, ול-{n(len(past))} כבר חלף "
                           f"מועד המחיקה הצפוי. נכון לפרסום האחרון, {d_he(ref)}."),
            "dataset_kind": "registry",
            "related_ids": ["246d949c-a253-4811-8a11-41a137d3d613",
                            "01aeaf5c-59a2-4ddc-a616-31b85621bfe2",
                            "6397d78e-f00f-4657-a03a-3868f845d3c0",
                            "3111ae54-790a-4d02-9750-d51e1134b405"],
            "suggested_tags": ["מחיקת חברות", "רשם החברות", "רשות התאגידים", "חוק החברות",
                               "חברות"],
            "temporal_coverage": f"{df['pub'].min().strftime('%Y-%m-%d')}/{ref.strftime('%Y-%m-%d')}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
        "flags": {"flags": bool(f_names), "years": len(years_chart["y"]) >= 2,
                  "recent": bool(recent_rows), "revival": bool(revival_rows)},
    }
