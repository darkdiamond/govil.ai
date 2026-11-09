"""Recipe compute for מקוואות טהרה (Ministry of Religious Services).

One row per mikveh: religious council, locality, name, address, opening
hours (summer / winter / Shabbat, free text), accessibility, yes/no service
flags, and the attendant's name and phone. The attendant's name and phone
are private contacts and never reach the page (they stay in the explorer).
"""

import math
import re

import pandas as pd
from govlib import fmt

TOP_CITIES = 15
TOP_COUNCILS = 15
TOP_MEN = 10
ACCESS_COUNCIL_MIN = 8  # councils with at least this many mikvaot get a mix bar
ACCESS_COUNCIL_TOP = 12
ACCESS_GAP_MIN_KNOWN = 5  # reported mikvaot a council needs for the gap insight

YES, NO, UNK = "כן", "לא", "לא צוין"

ACCESS_ORDER = ["full", "partial", "yes", "none", "unknown"]
ACCESS_LABEL = {
    "full": "נגישות מלאה",
    "partial": "נגישות חלקית",
    "yes": "נגיש (ללא פירוט)",
    "none": "ללא נגישות",
    "unknown": "לא צוין",
}
ACCESS_MAP = {"מלאה": "full", "חלקית": "partial", "כן": "yes", "ללא": "none", "לא": "none"}

SERVICES = [
    ("mikveForWomenYesNo", "מקווה לנשים"),
    ("brideRoomYesNo", "חדר כלה"),
    ("armorYesNo", "מקווה ממוגן"),
    ("mikveForDishesYesNo", "טבילת כלים"),
    ("mikveForMenYesNo", "מקווה לגברים"),
    ("onDutyYesNo", "מקווה תורן"),
]

HOURS = [
    ("activityHoursSummer", "ימי חול בקיץ"),
    ("activityHoursWinter", "ימי חול בחורף"),
    ("activityHoursShabat", "שבת"),
]
HOURS_ORDER = ["sun", "clock", "appt", "other"]
HOURS_LABEL = {
    "sun": "לפי השקיעה או צאת הכוכבים",
    "clock": "שעות קבועות",
    "appt": "בתיאום מראש או לפי קריאה",
    "other": "אחר או לא צוין",
}
_SUN = re.compile(r"שקיע|כוכבים|הדלקת|צאת|צה\"כ|כניסת|כניסה")
_CLOCK = re.compile(r"\d{1,2}[:.]\d{2}|\b\d{1,2}\s*(?:-|עד)\s*\d{1,2}\b")
_APPT = re.compile(r"תיאום|תאום|קריאה|דרישה|הזמנה|טלפונ|תיאופ")


def _clean(s: pd.Series) -> pd.Series:
    return s.astype(str).str.replace(r"\s+", " ", regex=True).str.strip()


def _hyphen(s: pd.Series) -> pd.Series:
    """Even out one-sided hyphen spacing ('תל אביב -יפו' → 'תל אביב - יפו')."""
    return (s.str.replace(r"(\S) -(\S)", r"\1 - \2", regex=True)
             .str.replace(r"(\S)- (\S)", r"\1 - \2", regex=True))


def _key(v: str) -> str:
    """Grouping key: spacing around hyphens varies (תל אביב -יפו)."""
    return re.sub(r"[\s\-–]+", " ", v).strip()


def _display_by_key(values: pd.Series) -> dict:
    """Most common spelling per key; ties broken alphabetically."""
    out = {}
    df = pd.DataFrame({"v": values, "k": values.map(_key)})
    cnt = df.groupby(["k", "v"]).size().reset_index(name="n")
    cnt = cnt.sort_values(["k", "n", "v"], ascending=[True, False, True], kind="mergesort")
    for k, g in cnt.groupby("k", sort=True):
        out[k] = g.iloc[0]["v"]
    return out


def _yn(v: str) -> str:
    v = v.strip()
    if v.startswith("כן"):
        return YES
    if v.startswith("לא"):
        return NO
    return UNK


def _hours_class(t: str) -> str:
    if not t or t in ("אין", "-"):
        return "other"
    if _SUN.search(t):
        return "sun"
    if _CLOCK.search(t):
        return "clock"
    if _APPT.search(t):
        return "appt"
    return "other"


def _ranked(series: pd.Series) -> list:
    """(label, count) sorted by count desc then label."""
    vc = series.value_counts()
    items = sorted(vc.items(), key=lambda kv: (-kv[1], kv[0]))
    return [(k, int(v)) for k, v in items]


def _pct(n: int, d: int) -> float:
    return round(100.0 * n / d, 1) if d else 0.0


def _p(n: int, d: int) -> str:
    return fmt.pct_of(_pct(n, d))


def compute(frames):
    df = frames["main"].copy()
    for c in df.columns:
        df[c] = _clean(df[c])
    df = df[(df["mikveCity"] != "") | (df["mikveName"] != "")].copy()
    df["mikveCity"] = _hyphen(df["mikveCity"])
    df["counciName"] = _hyphen(df["counciName"])

    df["city"] = df["mikveCity"].where(df["mikveCity"] != "", df["counciName"])
    city_disp = _display_by_key(df["city"])
    df["city_k"] = df["city"].map(_key)
    df["city_d"] = df["city_k"].map(city_disp)

    df["council"] = df["counciName"].where(df["counciName"] != "", "לא צוין")
    council_disp = _display_by_key(df["council"])
    df["council_k"] = df["council"].map(_key)
    df["council_d"] = df["council_k"].map(council_disp)

    df["access"] = df["accessability"].map(lambda v: ACCESS_MAP.get(v, "unknown"))
    df["access_any"] = df["access"].isin(["full", "partial", "yes"])
    for col, _ in SERVICES:
        df[col + "_n"] = df[col].map(_yn)
    for col, _ in HOURS:
        df[col + "_c"] = df[col].map(_hours_class)

    total = len(df)
    n_cities = int(df["city_k"].nunique())
    n_councils = int(df["council_k"].nunique())

    # --- localities -------------------------------------------------------
    city_rank = _ranked(df["city_d"])
    top_cities = city_rank[:TOP_CITIES]
    per_city = df.groupby("city_d").size()
    buckets = [("1", 1, 1), ("2", 2, 2), ("3-5", 3, 5), ("6-10", 6, 10), ("11+", 11, 10**9)]
    spread_vals = [int(((per_city >= lo) & (per_city <= hi)).sum()) for _, lo, hi in buckets]
    spread_labels = [b[0] for b in buckets]
    singles = spread_vals[0]

    # --- councils ---------------------------------------------------------
    c_m = df.groupby("council_d").size()
    c_l = df.groupby("council_d")["city_k"].nunique()
    council_rank = sorted(((k, int(c_m[k]), int(c_l[k])) for k in c_m.index),
                          key=lambda t: (-t[1], -t[2], t[0]))
    top_councils = council_rank[:TOP_COUNCILS]
    by_reach = sorted(council_rank, key=lambda t: (-t[2], -t[1], t[0]))

    # --- accessibility ----------------------------------------------------
    acc_counts = {k: int((df["access"] == k).sum()) for k in ACCESS_ORDER}
    acc_known = total - acc_counts["unknown"]
    access_rows = [(ACCESS_LABEL[k], acc_counts[k]) for k in ACCESS_ORDER if acc_counts[k] > 0]
    full_n, part_n, none_n = acc_counts["full"], acc_counts["partial"], acc_counts["none"]

    big = [t for t in council_rank if t[1] >= ACCESS_COUNCIL_MIN][:ACCESS_COUNCIL_TOP]
    ac_names, ac_series = [], {k: [] for k in ACCESS_ORDER}
    ac_table = []
    for name, m, _ in big:
        sub = df[df["council_d"] == name]
        ac_names.append(name)
        for k in ACCESS_ORDER:
            ac_series[k].append(_pct(int((sub["access"] == k).sum()), m))
        any_n = int(sub["access_any"].sum())
        ac_table.append([name, f"{m:,}", f"{int((sub['access'] == 'full').sum()):,}",
                         f"{int((sub['access'] == 'partial').sum()):,}", _p(any_n, m)])
    access_council_series = [
        {"name": ACCESS_LABEL[k], "key": k, "data": ac_series[k]}
        for k in ACCESS_ORDER if any(v > 0 for v in ac_series[k])
    ]

    # --- services ---------------------------------------------------------
    svc = []
    for col, label in SERVICES:
        y = int((df[col + "_n"] == YES).sum())
        n = int((df[col + "_n"] == NO).sum())
        u = total - y - n
        svc.append({"label": label, "yes": y, "no": n, "unk": u})
    svc_by = {s["label"]: s for s in svc}

    # --- men's mikvaot ----------------------------------------------------
    men = df[df["mikveForMenYesNo_n"] == YES]
    men_n = len(men)
    men_rank = _ranked(men["city_d"])[:TOP_MEN]

    # --- hours ------------------------------------------------------------
    hours_series = {k: [] for k in HOURS_ORDER}
    hours_table = []
    for col, label in HOURS:
        cnts = {k: int((df[col + "_c"] == k).sum()) for k in HOURS_ORDER}
        for k in HOURS_ORDER:
            hours_series[k].append(_pct(cnts[k], total))
        hours_table.append([label] + [f"{cnts[k]:,}" for k in HOURS_ORDER])
    h_sum = {k: int((df["activityHoursSummer_c"] == k).sum()) for k in HOURS_ORDER}
    h_sab = {k: int((df["activityHoursShabat_c"] == k).sum()) for k in HOURS_ORDER}

    # --- locality index ---------------------------------------------------
    index_rows = []
    for city, g in df.groupby("city_d", sort=True):
        councils = sorted(g["council_d"].unique())
        index_rows.append({
            "city": city,
            "council": ", ".join(councils),
            "n": len(g),
            "access": int(g["access_any"].sum()),
            "men": int((g["mikveForMenYesNo_n"] == YES).sum()),
            "dishes": int((g["mikveForDishesYesNo_n"] == YES).sum()),
        })

    # --- insights ---------------------------------------------------------
    insights = []

    if len(city_rank) >= 2:
        (c1, n1), (c2, n2) = city_rank[0], city_rank[1]
        if n1 >= 1.5 * n2:
            insights.append({"id": "lead_city", "text_he":
                f"{c1} מובילה עם {n1:,} מקוואות ({_p(n1, total)} מכלל המקוואות במאגר), "
                f"פי {math.floor(10 * n1 / n2) / 10:.1f} לפחות מהיישוב הבא, {c2} ({n2:,})."})
        else:
            insights.append({"id": "lead_city", "text_he":
                f"היישובים עם הכי הרבה מקוואות הם {c1} ({n1:,}) {fmt.vav(c2)} ({n2:,})."})

    if n_cities >= 5 and singles > 0:
        multi = n_cities - singles
        insights.append({"id": "singles", "text_he":
            f"ב-{singles:,} מתוך {n_cities:,} היישובים במאגר ({_p(singles, n_cities)}) יש מקווה אחד בלבד, "
            f"ורק ב-{multi:,} יישובים יש שניים או יותר."})

    if acc_known >= 20:
        yes_n = acc_counts["yes"]
        any_n = full_n + part_n + yes_n
        if none_n > 0.55 * acc_known:
            lead = "רוב המקוואות אינם נגישים"
        elif any_n > 0.55 * acc_known:
            lead = "רוב המקוואות נגישים לפחות חלקית"
        else:
            lead = "כמחצית מהמקוואות אינם נגישים"
        insights.append({"id": "access", "text_he":
            f"{lead}: מבין {acc_known:,} המקוואות שדיווחו על נגישות, ב-{full_n:,} ({_p(full_n, acc_known)}) "
            f"נגישות מלאה, ב-{part_n:,} ({_p(part_n, acc_known)}) נגישות חלקית "
            f"וב-{none_n:,} ({_p(none_n, acc_known)}) אין נגישות"
            + (f"; {yes_n:,} ({_p(yes_n, acc_known)}) דווחו כנגישים ללא פירוט רמת הנגישות." if yes_n else ".")})

    if len(big) >= 3:
        shares = []
        for name, m, _ in big:
            sub = df[df["council_d"] == name]
            known = int((sub["access"] != "unknown").sum())
            if known >= ACCESS_GAP_MIN_KNOWN and known * 2 >= m:
                shares.append((_pct(int(sub["access_any"].sum()), known), name, known))
        if len(shares) >= 3:
            hi = min(shares, key=lambda t: (-t[0], t[1]))
            lo = min(shares, key=lambda t: (t[0], t[1]))
            if hi[0] - lo[0] >= 20:
                lo_txt = (f"ובמועצה הדתית {lo[1]} אף אחד מ-{lo[2]:,} המקוואות שדיווחו אינו נגיש"
                          if lo[0] == 0 else f"ובמועצה הדתית {lo[1]} רק {fmt.pct_of(lo[0])}")
                insights.append({"id": "access_gap", "text_he":
                    f"פער גדול בנגישות בין המועצות הדתיות: במועצה הדתית {hi[1]} {fmt.pct_of(hi[0])} מהמקוואות "
                    f"שדיווחו נגישים במלואם או בחלקם, {lo_txt} "
                    f"(מבין המועצות עם {ACCESS_COUNCIL_MIN:,} מקוואות ומעלה שדיווחו על רובם)."})

    if men_n > 0 and men_rank:
        reported = total - svc_by["מקווה לגברים"]["unk"]
        mc, mn = men_rank[0]
        insights.append({"id": "men", "text_he":
            f"{men_n:,} מקוואות ({_p(men_n, reported)} מאלה שדיווחו) משמשים גם לגברים; "
            f"הריכוז הגדול ביותר ב{mc} ({mn:,})."})

    if total >= 20:
        appt, sun = h_sum["appt"], h_sum["sun"]
        insights.append({"id": "hours", "text_he":
            f"שעות הפתיחה אינן אחידות: בימי חול בקיץ {_p(sun, total)} מהמקוואות נפתחים לפי השקיעה או צאת הכוכבים, "
            f"{_p(h_sum['clock'], total)} בשעות קבועות ו-{_p(appt, total)} פועלים בתיאום מראש או לפי קריאה; "
            f"בשבת {_p(h_sab['appt'], total)} פועלים בתיאום (סיווג לפי הטקסט החופשי במאגר)."})

    if by_reach and by_reach[0][2] >= 5:
        name, m, loc = by_reach[0]
        insights.append({"id": "reach", "text_he":
            f"המועצה הדתית {name} פרוסה על פני הכי הרבה יישובים: {m:,} מקוואות ב-{loc:,} יישובים."})

    arm = svc_by["מקווה ממוגן"]
    arm_rep = arm["yes"] + arm["no"]
    if arm_rep >= 20:
        word = "רוב" if arm["yes"] > arm_rep / 2 else "מיעוט"
        insights.append({"id": "armor", "text_he":
            f"{word} המקוואות ממוגנים: {arm['yes']:,} מתוך {arm_rep:,} שדיווחו ({_p(arm['yes'], arm_rep)})."})

    # --- KPIs -------------------------------------------------------------
    full_share = _pct(full_n, acc_known)
    none_share = _pct(none_n, acc_known)
    bride = svc_by["חדר כלה"]
    bride_rep = bride["yes"] + bride["no"]
    kpis = {
        "total": {"value": total, "display": f"{total:,}", "tone": "brand"},
        "cities": {"value": n_cities, "display": f"{n_cities:,}", "tone": "brand"},
        "councils": {"value": n_councils, "display": f"{n_councils:,}", "tone": "brand"},
        "full_access": {"value": full_share, "display": fmt.pct_of(full_share),
                        "tone": "ok" if full_share >= 50 else ("info" if full_share >= 25 else "warn")},
        "no_access": {"value": none_share, "display": fmt.pct_of(none_share),
                      "tone": "danger" if none_share >= 40 else ("warn" if none_share >= 20 else "ok")},
        "men": {"value": men_n, "display": f"{men_n:,}", "tone": "info"},
        "bride": {"value": _pct(bride["yes"], bride_rep), "display": _p(bride["yes"], bride_rep), "tone": "brand"},
        "dishes": {"value": svc_by["טבילת כלים"]["yes"], "display": f"{svc_by['טבילת כלים']['yes']:,}", "tone": "brand"},
    }

    top_city = city_rank[0][0] if city_rank else ""
    summary = (f"רשימת {total:,} מקוואות טהרה ב-{n_cities:,} יישובים וב-{n_councils:,} מועצות דתיות, "
               f"עם כתובות, שעות פתיחה בקיץ, בחורף ובשבת, נגישות ושירותים; הכי הרבה מקוואות ב{top_city}.")
    description = (f"איתור מקווה טהרה לפי יישוב, שם או כתובת: {total:,} מקוואות ב-{n_cities:,} יישובים, "
                   f"עם שעות פתיחה, נגישות, מקוואות לגברים וטבילת כלים.")

    labels = {
        "lede": (f"המאגר של המשרד לשירותי דת מונה {total:,} מקוואות טהרה ב-{n_cities:,} יישובים, "
                 f"באחריות {n_councils:,} מועצות דתיות. לכל מקווה רשומים כתובת, שעות פעילות בימי חול "
                 f"בקיץ ובחורף ובשבת, רמת נגישות, והאם יש בו חדר כלה, מיגון, טבילת כלים ומקווה לגברים. "
                 f"פרטי הבלנית והטלפון מופיעים בטבלת הנתונים שבתחתית העמוד."),
        "cities_note": (f"{TOP_CITIES:,} היישובים עם מספר המקוואות הגדול ביותר, מתוך {n_cities:,} יישובים."),
        "cities_aria": f"מספר המקוואות ב-{min(TOP_CITIES, len(city_rank)):,} היישובים המובילים",
        "spread_note": (f"כמה מקוואות יש בכל יישוב: ב-{singles:,} יישובים ({_p(singles, n_cities)}) יש מקווה אחד בלבד."),
        "spread_aria": "התפלגות היישובים לפי מספר המקוואות ביישוב",
        "councils_note": (f"{min(TOP_COUNCILS, len(council_rank)):,} המועצות הדתיות עם הכי הרבה מקוואות; "
                          f"מועצות אזוריות מפעילות מקוואות בעשרות יישובים קטנים."),
        "councils_aria": "מספר המקוואות לפי מועצה דתית",
        "access_note": (f"רמת הנגישות כפי שדווחה; {acc_counts['unknown']:,} מקוואות ללא דיווח."),
        "access_aria": "התפלגות המקוואות לפי רמת נגישות",
        "access_council_note": (f"שיעור המקוואות בכל רמת נגישות, במועצות הדתיות עם {ACCESS_COUNCIL_MIN:,} מקוואות ומעלה."),
        "access_council_aria": "רמת הנגישות לפי מועצה דתית",
        "services_note": ("מספר המקוואות שדיווחו כן או לא על כל שירות; מקוואות ללא דיווח מסומנים בנפרד."),
        "services_aria": "שירותים במקוואות: חדר כלה, מיגון, טבילת כלים, מקווה לגברים ומקווה תורן",
        "hours_note": ("שעות הפעילות כתובות במאגר כטקסט חופשי. כל רשומה סווגה לפי מה שנכתב בה: "
                       "פתיחה מהשקיעה או מצאת הכוכבים, שעות קבועות, או תיאום מראש."),
        "hours_aria": "אופן קביעת שעות הפעילות בימי חול בקיץ, בחורף ובשבת",
        "men_note": f"{men_n:,} מקוואות מדווחים על טבילה לגברים; היישובים עם הכי הרבה מהם.",
        "men_aria": "מספר המקוואות לגברים לפי יישוב",
        "index_note": (f"כל {n_cities:,} היישובים במאגר, לפי סדר האלף-בית, עם מספר המקוואות, "
                       f"כמה מהם נגישים, וכמה משמשים לגברים ולטבילת כלים."),
    }

    charts = {
        "cities": {"names": [c for c, _ in top_cities], "values": [n for _, n in top_cities]},
        "spread": {"labels": spread_labels, "values": spread_vals},
        "councils": {"names": [t[0] for t in top_councils], "values": [t[1] for t in top_councils],
                     "localities": [t[2] for t in top_councils]},
        "access": {"names": [r[0] for r in access_rows], "values": [r[1] for r in access_rows],
                   "keys": [k for k in ACCESS_ORDER if acc_counts[k] > 0]},
        "access_council": {"names": ac_names, "series": access_council_series},
        "services": {"names": [s["label"] for s in svc], "yes": [s["yes"] for s in svc],
                     "no": [s["no"] for s in svc], "unk": [s["unk"] for s in svc]},
        "hours": {"names": [h[1] for h in HOURS],
                  "series": [{"name": HOURS_LABEL[k], "data": hours_series[k]} for k in HOURS_ORDER]},
        "men": {"names": [c for c, _ in men_rank], "values": [n for _, n in men_rank]},
    }

    tables = {
        "cities": [[c, f"{n:,}"] for c, n in top_cities],
        "spread": [[lab, f"{v:,}"] for lab, v in zip(spread_labels, spread_vals)],
        "councils": [[t[0], f"{t[1]:,}", f"{t[2]:,}"] for t in top_councils],
        "access": [[lab, f"{v:,}", _p(v, total)] for lab, v in access_rows],
        "access_council": ac_table,
        "services": [[s["label"], f"{s['yes']:,}", f"{s['no']:,}", f"{s['unk']:,}"] for s in svc],
        "hours": hours_table,
        "men": [[c, f"{n:,}"] for c, n in men_rank],
        "index": index_rows,
    }

    flags = {
        "access_council": len(big) >= 3,
        "men": len(men_rank) >= 3,
    }

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "registry",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "איתור מקווה לפי יישוב | רשימת מקוואות טהרה",
                "description": description,
                "name": "מקוואות טהרה: רשימת מקוואות לפי יישוב, כתובות ושעות פתיחה",
                "alternate_names": ["מקוואות טהרה", "מקווה טהרה", "רשימת מקוואות",
                                    "מקוואות נשים", "מקוואות המועצות הדתיות"],
            },
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "labels": labels,
        "flags": flags,
        "insights": insights,
        "hours_labels": [HOURS_LABEL[k] for k in HOURS_ORDER],
    }
