"""Recipe: רשימת המודדים (המרכז למיפוי ישראל).

One row per licensed surveyor: name, licence number, licence status, whether
the surveyor is an inspecting surveyor (מודד מבקר), and, for surveyors who
agreed to publish them, contact details packed as HTML in `information`.
The page reads only aggregate facts from `information` (office name, year
the licence was granted); phones, e-mails and addresses never reach the page.
"""

import math
import re

import pandas as pd
from govlib import fmt, frame

NO_INFO = "אין מידע נוסף עבור מודד זה"
VALID = "בתוקף"
NOT_VALID = "לא בתוקף"
REVOKED = "רישיון שלול"
MAX_BANDS = 20
TOP_NAMES = 10
TOP_FIRMS = 10
RECENT_N = 12
INSPECTORS_MAX = 60
COHORT_GAP_PTS = 10.0  # valid-share gap between oldest and newest third
CONTACT_GAP_PTS = 5.0  # contact-publishing gap between the thirds
MIN_LEADER = 3  # a firm/surname "leads" only with at least this many rows

_TAG = re.compile(r"</?p\s*>", re.IGNORECASE)
_BR = re.compile(r"<br\s*/?>", re.IGNORECASE)


def _parse_info(s: str) -> dict:
    s = str(s or "")
    if s.strip() in ("", NO_INFO) or "<br" not in s.lower():
        return {}
    out = {}
    for part in _BR.split(_TAG.sub("", s)):
        if ":" in part:
            k, v = part.split(":", 1)
            out[frame.clean(k)] = frame.clean(v)
    return out


def _norm_status(s: str) -> str:
    s = frame.clean(s)
    if s == VALID:
        return VALID
    if "שלילה" in s:
        return REVOKED
    if s.startswith(NOT_VALID):
        return NOT_VALID
    return s or "לא צוין"


def _firm_key(s: str) -> str:
    return frame.clean(str(s).replace("''", '"').replace("״", '"'))


def _share(a, b) -> float:
    return float(a) / float(b) if b else 0.0


def _plural(n: int, one: str, many: str) -> str:
    return one if n == 1 else f"{fmt.int_he(n)} {many}"


def compute(frames):
    df = frames["main"].copy()
    df["first"] = frame.clean_series(df["name1"])
    df["family"] = frame.clean_series(df["family_name"])
    df["full"] = (df["first"] + " " + df["family"]).map(frame.clean)
    df["num"] = pd.to_numeric(frame.clean_series(df["number"]), errors="coerce")
    df["st"] = df["status"].map(_norm_status)
    df["valid"] = df["st"] == VALID
    df["inspector"] = frame.clean_series(df["measurs"]) == "כן"
    info = df["information"].map(_parse_info)
    df["has_info"] = info.map(bool)
    df["firm"] = info.map(lambda d: _firm_key(d.get("שם משרד", "")))
    df["lic_year"] = pd.to_numeric(info.map(lambda d: d.get("שנת קבלת רישיון", "")), errors="coerce")
    df.loc[(df["lic_year"] < 1900) | (df["lic_year"] > 2100), "lic_year"] = float("nan")
    # Total order for every list below.
    df = df.sort_values(["num", "family", "first", "st"], kind="stable", na_position="first").reset_index(drop=True)

    total = len(df)
    n_valid = int(df["valid"].sum())
    n_not = total - n_valid
    n_revoked = int((df["st"] == REVOKED).sum())
    n_insp = int(df["inspector"].sum())
    n_insp_valid = int((df["inspector"] & df["valid"]).sum())
    n_info = int(df["has_info"].sum())
    valid_share = _share(n_valid, total)

    kpis = {
        "total": {"value": total, "display": fmt.int_he(total), "tone": "brand"},
        "valid": {"value": n_valid, "display": fmt.int_he(n_valid), "tone": "ok"},
        "not_valid": {"value": n_not, "display": fmt.int_he(n_not), "tone": "warn" if n_not else "brand"},
        "valid_share": {
            "value": round(valid_share * 100, 1),
            "display": fmt.pct(valid_share),
            "tone": "ok" if valid_share >= 0.7 else "warn",
        },
        "inspectors": {"value": n_insp, "display": fmt.int_he(n_insp), "tone": "info"},
        "contact": {"value": n_info, "display": fmt.int_he(n_info), "tone": "brand"},
    }

    # ---- status split
    st_counts = frame.ranked(df["st"])
    status_chart = {"names": [str(k) for k in st_counts.index], "values": [int(v) for v in st_counts]}
    status_table = [[str(k), fmt.int_he(v), fmt.pct(_share(v, total))] for k, v in st_counts.items()]

    # ---- licence-number cohorts
    nums = df["num"].dropna()
    width = 100
    if len(nums):
        lo, hi = int(nums.min()) // 100, int(nums.max()) // 100
        width = 100 * max(1, math.ceil((hi - lo + 1) / MAX_BANDS))
    bands = df.dropna(subset=["num"]).copy()
    bands["band"] = (bands["num"] // width).astype(int) * width
    g = bands.groupby("band", sort=True).agg(
        n=("valid", "size"), v=("valid", "sum"), info=("has_info", "sum"), insp=("inspector", "sum")
    )
    band_labels = [f"{b}-{b + width - 1}" for b in g.index]
    cohort_chart = {
        "labels": band_labels,
        "valid": [int(x) for x in g["v"]],
        "not_valid": [int(n - v) for n, v in zip(g["n"], g["v"])],
        "share": [round(_share(v, n) * 100, 1) for n, v in zip(g["n"], g["v"])],
    }
    cohort_table = [
        [lab, fmt.int_he(n), fmt.int_he(v), fmt.pct(_share(v, n))]
        for lab, n, v in zip(band_labels, g["n"], g["v"])
    ]
    contact_chart = {
        "labels": band_labels,
        "share": [round(_share(i, n) * 100, 1) for n, i in zip(g["n"], g["info"])],
        "count": [int(i) for i in g["info"]],
    }
    contact_table = [
        [lab, fmt.int_he(n), fmt.int_he(i), fmt.pct(_share(i, n))]
        for lab, n, i in zip(band_labels, g["n"], g["info"])
    ]

    # thirds by licence-number rank
    ranked_nums = bands.sort_values(["num", "family", "first"], kind="stable").reset_index(drop=True)
    third = len(ranked_nums) // 3
    old_t = ranked_nums.iloc[:third]
    new_t = ranked_nums.iloc[len(ranked_nums) - third:] if third else ranked_nums.iloc[0:0]

    # ---- licence year (only surveyors who published details)
    years = df["lic_year"].dropna().astype(int)
    dec = (years // 10 * 10).value_counts().sort_index()
    year_chart = {"labels": [f"{d}-{d + 9}" for d in dec.index], "values": [int(v) for v in dec]}
    year_table = [[f"{d}-{d + 9}", fmt.int_he(v)] for d, v in dec.items()]

    # ---- firms (offices) among published details
    firms = frame.ranked(df.loc[df["firm"] != "", "firm"])
    multi = firms[firms >= 2]
    top_f = multi.iloc[:TOP_FIRMS]
    firm_chart = {"names": [str(k) for k in top_f.index][::-1], "values": [int(v) for v in top_f][::-1]}
    firm_table = [[str(k), fmt.int_he(v)] for k, v in top_f.items()]

    # ---- names
    fam = frame.ranked(df.loc[df["family"] != "", "family"]).iloc[:TOP_NAMES]
    fst = frame.ranked(df.loc[df["first"] != "", "first"]).iloc[:TOP_NAMES]
    fam_chart = {"names": [str(k) for k in fam.index][::-1], "values": [int(v) for v in fam][::-1]}
    fst_chart = {"names": [str(k) for k in fst.index][::-1], "values": [int(v) for v in fst][::-1]}
    fam_table = [[str(k), fmt.int_he(v)] for k, v in fam.items()]
    fst_table = [[str(k), fmt.int_he(v)] for k, v in fst.items()]

    # ---- people lists (names only; licence numbers stay in the explorer)
    insp = df[df["inspector"]].sort_values(["family", "first", "num"], kind="stable")
    inspectors = [{"name": r.full, "status": r.st} for r in insp.head(INSPECTORS_MAX).itertuples()]
    recent = df.dropna(subset=["num"]).sort_values(["num", "family", "first"], ascending=[False, True, True], kind="stable")
    recent_rows = [[r.full, r.st] for r in recent.head(RECENT_N).itertuples()]

    # ---- insights
    insights = []
    if total:
        insights.append({
            "id": "valid",
            "text_he": (
                f"{fmt.int_he(n_valid)} מתוך {fmt.int_he(total)} המודדים ברשימה ({fmt.pct(valid_share)}) "
                f"מחזיקים ברישיון בתוקף. הרשימה כוללת גם {fmt.int_he(n_not)} מודדים שרישיונם אינו בתוקף, "
                "ולכן לפני הזמנת מדידה כדאי לבדוק את סטטוס הרישיון."
            ),
        })
    if third >= 10:
        a, b = old_t["valid"].mean(), new_t["valid"].mean()
        if abs(b - a) * 100 >= COHORT_GAP_PTS:
            hi_old = int(old_t["num"].max())
            lo_new = int(new_t["num"].min())
            insights.append({
                "id": "cohort",
                "text_he": (
                    f"תוקף הרישיון תלוי בוותק: בשליש הוותיק של הרשימה (מספרי רישיון עד {hi_old}) "
                    f"{fmt.pct(a)} בלבד בתוקף, לעומת {fmt.pct(b)} בשליש החדש (מספר {lo_new} ומעלה)."
                    if b > a else
                    f"בשליש הוותיק של הרשימה (מספרי רישיון עד {hi_old}) {fmt.pct(a)} מהרישיונות בתוקף, "
                    f"לעומת {fmt.pct(b)} בלבד בשליש החדש (מספר {lo_new} ומעלה)."
                ),
            })
        ia, ib = old_t["has_info"].mean(), new_t["has_info"].mean()
        if n_info and abs(ia - ib) * 100 >= CONTACT_GAP_PTS:
            more, less = ("הוותיק", "החדש") if ia > ib else ("החדש", "הוותיק")
            insights.append({
                "id": "contact",
                "text_he": (
                    f"{fmt.int_he(n_info)} מודדים ({fmt.pct(_share(n_info, total))}) אישרו לפרסם פרטי קשר ברשימה. "
                    f"השיעור גבוה יותר בשליש {more} של מספרי הרישיון ({fmt.pct(max(ia, ib))}) "
                    f"מאשר בשליש {less} ({fmt.pct(min(ia, ib))})."
                ),
            })
    if n_insp:
        tail = "כולם בעלי רישיון בתוקף" if n_insp_valid == n_insp else f"{fmt.int_he(n_insp_valid)} מהם בעלי רישיון בתוקף"
        insights.append({
            "id": "inspectors",
            "text_he": (
                f"{_plural(n_insp, 'מודד מבקר אחד', 'מודדים מבקרים')} ברשימה, "
                f"שמנהל המרכז למיפוי ישראל האציל עליהם סמכות לבקר מפות קדסטר ({tail})."
            ),
        })
    if len(firms) and int(firms.iloc[0]) >= MIN_LEADER and (len(firms) == 1 or firms.iloc[0] > firms.iloc[1]):
        insights.append({
            "id": "firm",
            "text_he": (
                f"בקרב המודדים שפרסמו פרטים, המשרד עם מספר המודדים הגדול ביותר הוא {firms.index[0]} "
                f"({fmt.int_he(int(firms.iloc[0]))} מודדים)."
            ),
        })
    if len(dec) >= 2:
        top_dec = dec.sort_index().sort_values(ascending=False, kind="stable")
        d0 = int(top_dec.index[0])
        insights.append({
            "id": "years",
            "text_he": (
                f"מבין {fmt.int_he(len(years))} המודדים שציינו את שנת קבלת הרישיון, הוותיק קיבל אותו ב-{int(years.min())} "
                f"והעשור הנפוץ הוא {d0}-{d0 + 9} ({fmt.int_he(int(top_dec.iloc[0]))} מודדים)."
            ),
        })
    if n_revoked:
        insights.append({
            "id": "revoked",
            "text_he": (
                "רישיון אחד ברשימה מסומן כשלילת רישיון." if n_revoked == 1
                else f"{fmt.int_he(n_revoked)} רישיונות ברשימה מסומנים כשלילת רישיון."
            ),
        })
    if len(fam) >= 2 and int(fam.iloc[0]) >= MIN_LEADER and fam.iloc[0] > fam.iloc[1]:
        insights.append({
            "id": "surname",
            "text_he": f"שם המשפחה הנפוץ ביותר ברשימה הוא {fam.index[0]} ({fmt.int_he(int(fam.iloc[0]))} מודדים).",
        })

    # ---- labels
    newest_band = band_labels[-1] if band_labels else ""
    labels = {
        "lede": (
            f"רשימת המודדים המוסמכים של המרכז למיפוי ישראל כוללת {fmt.int_he(total)} מודדים: "
            f"{fmt.int_he(n_valid)} בעלי רישיון מודד בתוקף ו-{fmt.int_he(n_not)} שרישיונם אינו בתוקף. "
            f"ברשימה מסומנים {fmt.int_he(n_insp)} מודדים מבקרים, ו-{fmt.int_he(n_info)} מודדים פרסמו פרטי קשר. "
            "מודדים שנפטרו אינם מופיעים ברשימה."
        ),
        "status_aria": (
            f"תרשים טבעת: מודדים לפי סטטוס רישיון. {fmt.int_he(n_valid)} בתוקף ({fmt.pct(valid_share)})."
        ),
        "status_note": f"סטטוס הרישיון של כל {fmt.int_he(total)} המודדים ברשימה.",
        "cohort_note": (
            f"המודדים מקובצים לפי מספר הרישיון, קבוצות של {width} מספרים. מספר רישיון נמוך פירושו רישיון ותיק יותר. "
            f"הקו מציג את שיעור הרישיונות בתוקף בכל קבוצה (הקבוצה {newest_band} עדיין מתמלאת)."
        ),
        "cohort_aria": (
            f"גרף עמודות מוערמות: מודדים בתוקף ושלא בתוקף לפי קבוצת מספר רישיון, מ-{band_labels[0] if band_labels else ''} "
            f"ועד {newest_band}."
        ),
        "contact_note": (
            "שיעור המודדים בכל קבוצת מספרי רישיון שאישרו את פרסום פרטי הקשר שלהם. "
            "הפרטים עצמם מופיעים בעיון בנתונים בתחתית העמוד."
        ),
        "contact_aria": (
            f"גרף עמודות: שיעור המודדים שפרסמו פרטי קשר לפי קבוצת מספר רישיון. בסך הכול {fmt.int_he(n_info)} מודדים."
        ),
        "year_note": (
            f"שנת קבלת הרישיון לפי עשור, רק עבור {fmt.int_he(len(years))} המודדים שפרסמו פרטים "
            f"(מתוך {fmt.int_he(total)}). מודדים חדשים מפרסמים פרטים לעיתים רחוקות, ולכן העשורים האחרונים חסרים כאן."
        ),
        "year_aria": f"גרף עמודות: מודדים לפי עשור קבלת הרישיון, מתוך {fmt.int_he(len(years))} שפרסמו את השנה.",
        "firm_note": (
            f"משרדים שלפחות שני מודדים ציינו אותם כמשרדם, מתוך {fmt.int_he(n_info)} המודדים שפרסמו פרטים"
            + (f" ({fmt.int_he(len(top_f))} המובילים מתוך {fmt.int_he(len(multi))} משרדים כאלה)." if len(multi) > len(top_f) else ".")
        ),
        "firm_aria": "גרף עמודות אופקי: משרדי מדידה עם מספר המודדים הגדול ביותר בקרב מי שפרסמו פרטים.",
        "fam_aria": (
            f"גרף עמודות אופקי: שמות המשפחה הנפוצים ברשימה. המוביל: {fam.index[0]}." if len(fam) else "גרף עמודות אופקי: שמות משפחה נפוצים."
        ),
        "fst_aria": (
            f"גרף עמודות אופקי: השמות הפרטיים הנפוצים ברשימה. המוביל: {fst.index[0]}." if len(fst) else "גרף עמודות אופקי: שמות פרטיים נפוצים."
        ),
        "names_note": f"{TOP_NAMES} השמות הנפוצים ביותר בכל {fmt.int_he(total)} הרשומות.",
        "inspectors_note": (
            f"{_plural(n_insp, 'מודד מבקר אחד', 'מודדים מבקרים')}, לפי שם משפחה. מודד מבקר מוסמך לבצע ביקורת של מפות קדסטר."
        ),
        "recent_note": f"{fmt.int_he(len(recent_rows))} בעלי מספרי הרישיון הגבוהים ביותר ברשימה, כלומר המודדים שהוסמכו לאחרונה.",
    }

    summary = (
        f"רשימת המודדים המוסמכים של המרכז למיפוי ישראל: {fmt.int_he(total)} מודדים, "
        f"מהם {fmt.int_he(n_valid)} בעלי רישיון בתוקף ו-{fmt.int_he(n_insp)} מודדים מבקרים."
    )
    agent_data = {
        "summary_he": summary,
        "dataset_kind": "registry",
        "spatial_coverage": "ישראל",
        "seo": {
            "title": "איתור מודד מוסמך לפי שם או מספר רישיון | רשימת המודדים",
            "description": (
                f"איתור מודד מוסמך לפי שם או מספר רישיון ובדיקת תוקף הרישיון: {fmt.int_he(total)} מודדים ברשימה, "
                f"{fmt.int_he(n_valid)} מהם בעלי רישיון בתוקף."
            ),
            "name": "רשימת המודדים המוסמכים",
            "alternate_names": ["רשימת המודדים", "פנקס המודדים", "מודד מוסמך", "בדיקת רישיון מודד", "מודדים מבקרים"],
        },
    }
    if len(years):
        agent_data["temporal_coverage"] = f"{int(years.min())}/{int(years.max())}"

    return {
        "agent_data": agent_data,
        "kpis": kpis,
        "charts": {
            "status": status_chart,
            "cohort": cohort_chart,
            "contact": contact_chart,
            "years": year_chart,
            "firms": firm_chart,
            "family": fam_chart,
            "first": fst_chart,
        },
        "tables": {
            "status": status_table,
            "cohort": cohort_table,
            "contact": contact_table,
            "years": year_table,
            "firms": firm_table,
            "family": fam_table,
            "first": fst_table,
            "recent": recent_rows,
        },
        "inspectors": inspectors,
        "flags": {
            "years": len(dec) >= 2,
            "firms": len(top_f) >= 2,
            "inspectors": bool(inspectors),
            "recent": bool(recent_rows),
        },
        "insights": insights,
        "labels": labels,
    }
