"""Cadastre update notice to local authorities (Survey of Israel).

One row per (TZR plan, locality). A TZR plan ("תצ״ר", a plan for
registration purposes) is identified by its number + year; the same number
is reused across years, so the key is the pair. Each plan sits on one block
(גוש) and may touch several localities / municipal areas.

Plan status: "סופי" = registered in the Land Registry (טאבו);
"כשר לרישום" = approved by the Survey of Israel, not yet registered.
Every number on the page is computed here; insight rules return None when
their premise does not hold.
"""
import re

import pandas as pd

REGISTERED = "סופי"
APPROVED = "כשר לרישום"
STATUS_ORDER = [REGISTERED, APPROVED]
STATUS_DISPLAY = {REGISTERED: "סופי: נרשמה בטאבו", APPROVED: "כשר לרישום: טרם נרשמה"}
OPEN_AREA_PREFIX = "שטח כללי"
NO_VALUE = "לא צוין"
OTHER = "אחר"

TOP_MUNI = 12
TOP_ORDERER = 8
MIN_ORDERER_PLANS = 4

FINALS = "ךםןףץ"
_FINAL_MID = re.compile(f"[{FINALS}][א-ת]")


def _int(n):
    return f"{int(n):,}"


def _pct(x):
    return f"{x * 100:.1f}%"


def _clean(s):
    return re.sub(r"\s+", " ", str(s)).strip()


def _garbled(name):
    """Orderer names in the source are often letter-reversed with spaces
    dropped (e.g. a final letter at the start of a word, or one 30-letter
    'word'). Such names are not shown individually."""
    if not name:
        return True
    if _FINAL_MID.search(name):
        return True
    return any(len(w) > 16 for w in name.split(" "))


def _prepare(df):
    df = df.copy()
    for c in df.columns:
        df[c] = df[c].map(_clean)
    df["num"] = pd.to_numeric(df["מספר תצר"], errors="coerce")
    df["year"] = pd.to_numeric(df["שנת תצר"], errors="coerce")
    df["block"] = pd.to_numeric(df["גוש"], errors="coerce")
    df = df.dropna(subset=["num", "year"])
    df["num"] = df["num"].astype(int)
    df["year"] = df["year"].astype(int)
    df = df[(df["year"] >= 1900) & (df["year"] <= 2100)]
    df["status"] = df["סטטוס תצר"].replace("", NO_VALUE)
    df["block_status"] = df["סטטוס גוש"].replace("", NO_VALUE)
    df["locality"] = df["שם ישוב"].replace("", NO_VALUE)
    df["muni"] = df["שם אזור מוניציפלי"].replace("", NO_VALUE)
    df["orderer"] = df["מזמין עבודה"]
    df["plan"] = df["num"].astype(str) + "/" + df["year"].astype(str)
    return df


def _plans(df):
    """One row per plan; per-plan attributes taken deterministically
    (first in a total sort) in case a plan's rows ever disagree."""
    s = df.sort_values(["plan", "status", "block_status", "orderer", "muni", "locality"],
                       kind="stable")
    p = s.groupby("plan", sort=True).agg(
        num=("num", "first"), year=("year", "first"), status=("status", "first"),
        block=("block", "first"), block_status=("block_status", "first"),
        orderer=("orderer", "first"),
        n_muni=("muni", "nunique"), n_loc=("locality", "nunique"),
    ).reset_index()
    return p


def _status_list(p):
    counts = p["status"].value_counts()
    known = [s for s in STATUS_ORDER if s in counts.index]
    rest = sorted([s for s in counts.index if s not in STATUS_ORDER],
                  key=lambda s: (-int(counts[s]), s))
    return known + rest


def _ranked(series_counts):
    return series_counts.sort_index().sort_values(ascending=False, kind="stable")


def _stack(p, key, names, statuses):
    out = {}
    for st in statuses:
        sub = p[p["status"] == st]
        c = sub.groupby(key).size()
        out[st] = [int(c.get(n, 0)) for n in names]
    return out


# ---------------------------------------------------------------- insights

def insight_peak(yearly, total):
    if len(yearly) < 3 or total == 0:
        return None
    peak_y = int(yearly.sort_index().idxmax())
    peak_v = int(yearly.max())
    if peak_v < 2 or (yearly == peak_v).sum() > 1:
        return None
    share = peak_v / total
    prev = yearly[yearly.index < peak_y]
    if prev.empty:
        return None
    prev_y = int(prev.index.max())
    prev_v = int(prev.iloc[-1])
    if prev_v == 0:
        return None
    ratio = peak_v / prev_v
    if ratio >= 1.5:
        tail = f"פי {ratio:.1f} מבשנת {prev_y} ({_int(prev_v)})"
    else:
        tail = f"לעומת {_int(prev_v)} בשנת {prev_y}"
    return (f"שנת {peak_y} היא שנת השיא: {_int(peak_v)} תוכניות תצ״ר במאגר "
            f"({_pct(share)} מכלל התוכניות), {tail}.")


def insight_backlog(p, yearly_pending):
    n = len(p)
    pend = p[p["status"] == APPROVED]
    if n == 0 or pend.empty:
        return None
    share = len(pend) / n
    years = sorted(pend["year"].unique())
    last2 = [y for y in sorted(p["year"].unique())][-2:]
    in_last2 = int(pend["year"].isin(last2).sum())
    oldest = int(years[0])
    text = (f"{_int(len(pend))} תוכניות ({_pct(share)}) אושרו ככשרות לרישום אך טרם נרשמו בטאבו. ")
    if len(last2) == 2 and in_last2 / len(pend) >= 0.5:
        text += (f"{_int(in_last2)} מהן ({_pct(in_last2 / len(pend))}) הן משנות "
                 f"{last2[0]} ו-{last2[1]}, ")
        text += f"והוותיקה שבהן משנת {oldest}."
    else:
        text += f"הוותיקה שבהן משנת {oldest}."
    return text


def insight_registered_old(p):
    """Older plans are almost all registered; recent ones mostly pending."""
    years = sorted(p["year"].unique())
    if len(years) < 4:
        return None
    last = years[-1]
    old = p[p["year"] <= years[-4]]
    new = p[p["year"] == last]
    if len(old) < 5 or len(new) < 3:
        return None
    r_old = (old["status"] == REGISTERED).mean()
    r_new = (new["status"] == REGISTERED).mean()
    if r_old - r_new < 0.3:
        return None
    return (f"ככל שהתוכנית ותיקה יותר, גדל הסיכוי שכבר נרשמה: {_pct(r_old)} מהתוכניות "
            f"עד שנת {years[-4]} רשומות בטאבו, לעומת {_pct(r_new)} מתוכניות שנת {last}.")


def insight_orderer(p, ranked, total):
    if ranked.empty or total == 0:
        return None
    name, v = ranked.index[0], int(ranked.iloc[0])
    share = v / total
    if share < 0.1:
        return None
    if len(ranked) > 1 and int(ranked.iloc[1]) == v:
        return None
    text = f"המזמין המוביל הוא {name}, עם {_int(v)} תוכניות ({_pct(share)} מכלל תוכניות התצ״ר במאגר)"
    if len(ranked) >= 3:
        top3 = int(ranked.iloc[:3].sum())
        text += (f". יחד עם {ranked.index[1]} ו{ranked.index[2]}, שלושת המזמינים הגדולים "
                 f"אחראים ל-{_pct(top3 / total)} מהתוכניות")
    return text + "."


def insight_muni(muni_counts, total_plans):
    if muni_counts.empty:
        return None
    name, v = muni_counts.index[0], int(muni_counts.iloc[0])
    if v < 3:
        return None
    if len(muni_counts) > 1 and int(muni_counts.iloc[1]) == v:
        return None
    second = muni_counts.index[1] if len(muni_counts) > 1 else None
    v2 = int(muni_counts.iloc[1]) if len(muni_counts) > 1 else 0
    text = (f"{name} הוא האזור המוניציפלי עם הכי הרבה תוכניות ({_int(v)}), "
            f"מתוך {_int(len(muni_counts))} אזורים מוניציפליים שבהם יש תוכנית אחת לפחות")
    if second is not None:
        text += f"; אחריו {second} ({_int(v2)})"
    return text + "."


def insight_cross(p):
    n = len(p)
    multi = p[p["n_muni"] > 1]
    if n == 0 or len(multi) / n < 0.05:
        return None
    return (f"{_int(len(multi))} תוכניות ({_pct(len(multi) / n)}) חוצות גבול מוניציפלי ונוגעות "
            f"ביותר מאזור מוניציפלי אחד, כך שהעדכון עליהן נוגע לכמה רשויות.")


def insight_open(df):
    n = len(df)
    if n == 0:
        return None
    is_open = df["locality"].str.startswith(OPEN_AREA_PREFIX)
    k = int(is_open.sum())
    if k / n < 0.05:
        return None
    munis = df[is_open].groupby("muni").size()
    munis = _ranked(munis)
    lead = munis.index[0]
    return (f"{_pct(k / n)} מהרשומות ({_int(k)}) הן ב\"שטח כללי\" מחוץ לגבולות יישוב; "
            f"האזור המוניציפלי המוביל בהן הוא {lead} ({_int(int(munis.iloc[0]))} רשומות).")


def insight_block_status(p):
    c = p["block_status"].value_counts()
    c = c[c.index != NO_VALUE]
    if c.empty:
        return None
    c = _ranked(c)
    total = int(c.sum())
    lead, v = c.index[0], int(c.iloc[0])
    if v / total < 0.4:
        return None
    text = f"{_pct(v / total)} מהתוכניות שסטטוס הגוש שלהן ידוע נמצאות בגוש בסטטוס \"{lead}\""
    if "חדש רשום" in c.index and lead != "חדש רשום":
        nv = int(c["חדש רשום"])
        text += f", ו-{_pct(nv / total)} בגוש בסטטוס \"חדש רשום\""
    return text + "."


# ---------------------------------------------------------------- compute

def compute(frames):
    df = _prepare(frames["main"])
    p = _plans(df)
    n_plans = len(p)
    statuses = _status_list(p)

    # Years: continuous axis from first to last year.
    y_min, y_max = int(p["year"].min()), int(p["year"].max())
    years = list(range(y_min, y_max + 1))
    yearly = p.groupby("year").size().reindex(years, fill_value=0)
    year_stack = _stack(p, "year", years, statuses)
    pend_share = []
    for y in years:
        tot = int(yearly[y])
        pend_share.append(round(year_stack.get(APPROVED, [0] * len(years))[years.index(y)] / tot * 100, 1)
                          if tot else None)

    # Municipal areas: plans counted once per area they touch.
    pm = df[["plan", "muni"]].drop_duplicates().merge(p[["plan", "status"]], on="plan")
    muni_counts = _ranked(pm.groupby("muni").size())
    muni_top = list(muni_counts.index[:TOP_MUNI])
    muni_stack = _stack(pm, "muni", muni_top, statuses)
    muni_rest = int(pm["plan"][~pm["muni"].isin(muni_top)].nunique())

    # Orderers: clean names with enough plans; the rest grouped.
    p["orderer_c"] = p["orderer"].where(~p["orderer"].map(_garbled), "")
    oc = p[p["orderer_c"] != ""].groupby("orderer_c").size()
    oc = _ranked(oc[oc >= MIN_ORDERER_PLANS])
    ord_top = list(oc.index[:TOP_ORDERER])
    p["ord_bucket"] = p["orderer_c"].where(p["orderer_c"].isin(ord_top), OTHER)
    ord_names = ord_top + ([OTHER] if (p["ord_bucket"] == OTHER).any() else [])
    ord_stack = _stack(p, "ord_bucket", ord_names, statuses)
    ord_totals = [sum(ord_stack[s][i] for s in statuses) for i in range(len(ord_names))]
    garbled_n = int((p["orderer_c"] == "").sum())

    # Block status × plan status.
    bs = p.groupby("block_status").size()
    bs_names = [n for n in _ranked(bs[bs.index != NO_VALUE]).index] + \
        ([NO_VALUE] if NO_VALUE in bs.index else [])
    bs_stack = _stack(p, "block_status", bs_names, statuses)
    n_blocks = int(df["block"].dropna().nunique())
    blocks_new = int(p[p["block_status"] == "חדש רשום"]["block"].nunique())

    # Plan reach: how many municipal areas each plan touches.
    reach = p.groupby("n_muni").size().sort_index()
    multi = int((p["n_muni"] > 1).sum())

    # Localities (excluding open areas outside localities).
    loc = df[~df["locality"].str.startswith(OPEN_AREA_PREFIX) & (df["locality"] != NO_VALUE)]
    lc = _ranked(loc[["plan", "locality"]].drop_duplicates().groupby("locality").size())
    n_loc = int(lc.size)

    n_reg = int((p["status"] == REGISTERED).sum())
    n_app = int((p["status"] == APPROVED).sum())
    reg_share = n_reg / n_plans if n_plans else 0
    n_muni = int(muni_counts.size)

    rules = [
        ("backlog", insight_backlog(p, pend_share)),
        ("peak", insight_peak(yearly, n_plans)),
        ("age", insight_registered_old(p)),
        ("orderer", insight_orderer(p, oc, n_plans)),
        ("muni", insight_muni(muni_counts, n_plans)),
        ("cross", insight_cross(p)),
        ("open", insight_open(df)),
        ("block", insight_block_status(p)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    peak_y = int(yearly.idxmax())
    summary = (f"איתור תוכנית תצ״ר לפי מספר, גוש, יישוב או רשות: {_int(n_plans)} תוכניות לצרכי "
               f"רישום, {_int(n_reg)} רשומות בטאבו ו-{_int(n_app)} כשרות לרישום.")

    lede = (f"המרכז למיפוי ישראל (מפ״י) מודיע לרשויות המקומיות על עדכוני קדסטר: תוכניות לצרכי "
            f"רישום (תצ״ר) שנרשמו בטאבו או שאושרו ככשרות לרישום, וגושים שהוסדרו. המאגר כולל "
            f"{_int(n_plans)} תוכניות משנות {y_min} עד {y_max}, ב-{_int(n_blocks)} גושים "
            f"וב-{_int(n_muni)} אזורים מוניציפליים.")

    def tbl_rows(names, stack):
        return [{"name": str(n), "cells": [_int(stack[s][i]) for s in statuses],
                 "total": _int(sum(stack[s][i] for s in statuses))}
                for i, n in enumerate(names)]

    year_rows = [{"name": str(y), "cells": [_int(year_stack[s][i]) for s in statuses],
                  "total": _int(int(yearly[y])),
                  "pend": (f"{pend_share[i]:.1f}%" if pend_share[i] is not None else "")}
                 for i, y in enumerate(years)]

    muni_lede = (f"{muni_counts.index[0]} מוביל עם {_int(int(muni_counts.iloc[0]))} תוכניות. "
                 f"מוצגים {len(muni_top)} האזורים המובילים מתוך {_int(n_muni)}; תוכנית שחוצה גבול "
                 f"נספרת בכל אזור שהיא נוגעת בו.")
    if muni_rest:
        muni_lede += f" בשאר האזורים יש {_int(muni_rest)} תוכניות."

    ord_lede = (f"מוצגים מזמינים עם {MIN_ORDERER_PLANS} תוכניות לפחות. "
                f"שמות המזמינים במקור רבים משובשים (אותיות בסדר הפוך וללא רווחים) או של אנשים "
                f"פרטיים; {_int(garbled_n)} תוכניות שזוהה בהן שם מזמין משובש, וכל שאר המזמינים הקטנים, "
                f"מקובצים תחת \"{OTHER}\".")

    bs_known = int(sum(bs[n] for n in bs.index if n != NO_VALUE))
    bs_lede = (f"סטטוס הגוש שעליו יושבת התוכנית: גוש מוסדר, גוש חדש שנרשם, גוש שטרם נרשם או "
               f"הסדר שבוטל. ל-{_int(bs_known)} מתוך {_int(n_plans)} התוכניות הסטטוס ידוע.")

    reach_names = [f"{int(k)} אזורים" if int(k) > 1 else "אזור אחד" for k in reach.index]
    reach_lede = (f"{_int(multi)} תוכניות ({_pct(multi / n_plans if n_plans else 0)}) נוגעות ביותר "
                  f"מאזור מוניציפלי אחד, וההודעה עליהן רלוונטית לכמה רשויות.")

    loc_top = list(lc.index[:TOP_MUNI])
    open_rows = int(df["locality"].str.startswith(OPEN_AREA_PREFIX).sum())
    loc_lede = (f"{_int(n_loc)} יישובים מופיעים במאגר. {_int(open_rows)} רשומות נוספות הן ב\"שטח "
                f"כללי\" מחוץ לגבולות יישוב ואינן נכללות בתרשים.")

    years_lede = (f"מספר התוכניות לפי שנת התצ״ר, ובקו: שיעור התוכניות בכל שנה שעדיין "
                  f"ממתינות לרישום בטאבו. שנת השיא היא {peak_y} עם {_int(int(yearly.max()))} תוכניות.")

    tone_reg = "ok" if reg_share >= 0.5 else "warn"

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "registry",
            "suggested_tags": ["קדסטר", "טאבו", "תצ״ר", "גושים", "רישום מקרקעין", "הסדר קרקעות"],
            "related_ids": [
                "65dafbb0-1fbe-4a4c-bd59-71eadcac3995",
                "1d2d0ec1-bcdb-41dd-a8bc-0d1189cbcf78",
                "200b7541-b11b-4b35-b350-a90e4d7fe25c",
                "04027bcc-4d4c-4289-8088-0ecccede57f5",
            ],
            "temporal_coverage": f"{y_min}/{y_max}",
            "spatial_coverage": "ישראל",
        },
        "kpis": {
            "plans": {"value": n_plans, "display": _int(n_plans), "tone": "brand"},
            "registered": {"value": round(reg_share, 4), "display": _pct(reg_share), "tone": tone_reg},
            "pending": {"value": n_app, "display": _int(n_app), "tone": "info"},
            "blocks": {"value": n_blocks, "display": _int(n_blocks), "tone": "brand"},
            "munis": {"value": n_muni, "display": _int(n_muni), "tone": "brand"},
            "years": {"value": [y_min, y_max], "display": f"{y_min}–{y_max}", "tone": "brand"},
        },
        "charts": {
            "years": {"x": [str(y) for y in years],
                      "series": [{"name": STATUS_DISPLAY.get(s, s), "data": year_stack[s]} for s in statuses],
                      "pend": pend_share},
            "muni": {"names": muni_top,
                     "series": [{"name": STATUS_DISPLAY.get(s, s), "data": muni_stack[s]} for s in statuses]},
            "orderer": {"names": ord_names,
                        "series": [{"name": STATUS_DISPLAY.get(s, s), "data": ord_stack[s]} for s in statuses]},
            "block": {"names": bs_names,
                      "series": [{"name": STATUS_DISPLAY.get(s, s), "data": bs_stack[s]} for s in statuses]},
            "reach": {"names": reach_names, "values": [int(v) for v in reach]},
            "loc": {"names": loc_top, "values": [int(lc[n]) for n in loc_top]},
        },
        "tables": {
            "statuses": [STATUS_DISPLAY.get(s, s) for s in statuses],
            "years": year_rows,
            "muni": tbl_rows(muni_top, muni_stack),
            "orderer": [dict(r, total=_int(ord_totals[i])) for i, r in
                        enumerate(tbl_rows(ord_names, ord_stack))],
            "block": tbl_rows(bs_names, bs_stack),
            "reach": [{"name": reach_names[i], "n": _int(int(v))} for i, v in enumerate(reach)],
            "loc": [{"name": n, "n": _int(int(lc[n]))} for n in loc_top],
        },
        "insights": insights,
        "labels": {
            "lede": lede,
            "kpi_plans": "תוכניות תצ״ר במאגר",
            "kpi_registered": "שיעור התוכניות שנרשמו בטאבו",
            "kpi_pending": "תוכניות כשרות לרישום שטרם נרשמו",
            "kpi_blocks": "גושים",
            "kpi_munis": "אזורים מוניציפליים",
            "kpi_years": "שנות התצ״ר במאגר",
            "years_lede": years_lede,
            "years_aria": (f"תרשים עמודות מוערמות: תוכניות תצ״ר לפי שנה ולפי סטטוס, {y_min} עד {y_max}. "
                           f"השיא בשנת {peak_y} עם {_int(int(yearly.max()))} תוכניות."),
            "muni_lede": muni_lede,
            "muni_aria": (f"תרשים עמודות אופקי: {len(muni_top)} האזורים המוניציפליים עם הכי הרבה "
                          f"תוכניות, בראשם {muni_counts.index[0]}."),
            "orderer_lede": ord_lede,
            "orderer_aria": (f"תרשים עמודות אופקי: תוכניות לפי מזמין העבודה ולפי סטטוס. המזמין "
                             f"המוביל: {ord_names[0] if ord_names else NO_VALUE}."),
            "block_lede": bs_lede,
            "block_aria": f"תרשים עמודות מוערמות: תוכניות לפי סטטוס הגוש ולפי סטטוס התוכנית, {len(bs_names)} סטטוסים.",
            "reach_lede": reach_lede,
            "reach_aria": f"תרשים עמודות: מספר התוכניות לפי מספר האזורים המוניציפליים שהן נוגעות בהם. {_int(multi)} תוכניות חוצות גבול.",
            "loc_lede": loc_lede,
            "loc_aria": (f"תרשים עמודות אופקי: {len(loc_top)} היישובים עם הכי הרבה תוכניות"
                         + (f", בראשם {loc_top[0]}." if loc_top else ".")),
        },
        "flags": {"loc": len(loc_top) >= 3, "orderer": len(ord_top) >= 2},
    }
