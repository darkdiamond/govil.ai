"""מכשירים אוטומטיים (ATMs) — Bank of Israel register of bank ATMs.

One row per ATM listing; an ATM attached to two branches can appear twice,
so the unit is the (bank, ATM number) pair. Coordinates are WGS84 with the
axes swapped (X = latitude) — a few rows are in ITM or unswapped and are
disclosed rather than silently fixed (GovMap plots the raw resource).
"""
import pandas as pd

SERVICES = [
    ("Casd_Withdrawal", "משיכת מזומן"),
    ("Cash_Deposit", "הפקדת מזומן"),
    ("Cheque_Deposit", "הפקדת שיקים"),
    ("Envelope_Deposit", "הפקדה במעטפה"),
    ("Forex_Transaction", "מט״ח"),
    ("Additional_Transactions", "פעולות נוספות"),
]
LOCATION_ORDER = ["בתוך הסניף", "על קיר הסניף", "במרחק עד 500 מטר מהסניף",
                  "במרחק של יותר מ- 500 מטר מהסניף", "אינו סמוך לסניף"]
LOCATION_LABEL = {
    "בתוך הסניף": "בתוך הסניף", "על קיר הסניף": "על קיר הסניף",
    "במרחק עד 500 מטר מהסניף": "עד 500 מ׳ מהסניף",
    "במרחק של יותר מ- 500 מטר מהסניף": "מעל 500 מ׳ מהסניף",
    "אינו סמוך לסניף": "לא צמוד לסניף",
}
OFF_BRANCH = {"במרחק עד 500 מטר מהסניף", "במרחק של יותר מ- 500 מטר מהסניף", "אינו סמוך לסניף"}
TOP_CITIES = 15


def _int(n):
    return f"{int(n):,}"


def _pct(x, d=0):
    return f"{x * 100:.{d}f}%"


def _bank_short(name):
    return (name.replace(" בע\"מ", "").replace("בע\"מ", "").replace("לישראל", "")
            .replace("בנק ", "").replace("  ", " ").strip())


def _prepare(df):
    out = df.copy()
    for c in out.columns:
        out[c] = out[c].str.strip()
    out["City"] = out["City"].str.replace(r"\s*-\s*", "-", regex=True).str.replace(r"\s+", " ", regex=True)
    out = out.sort_values(list(out.columns), kind="stable")
    out = out.drop_duplicates(["Bank_Code", "Atm_Num"]).reset_index(drop=True)
    out["bank"] = out["Bank_Name"].map(_bank_short)
    x = pd.to_numeric(out["X_Coordinate"], errors="coerce")
    y = pd.to_numeric(out["Y_Coordinate"], errors="coerce")
    out["geo_ok"] = x.between(29, 34) & y.between(34, 36)
    return out


def _yes(s):
    return s.eq("כן")


def compute(frames):
    raw_rows = len(frames["atms"])
    df = _prepare(frames["atms"])
    n = len(df)
    banks = df["bank"].value_counts().sort_index().sort_values(ascending=False, kind="stable")
    bank_order = list(banks.index)

    # By bank
    by_bank = {"names": bank_order, "values": [int(v) for v in banks]}

    # Cities
    cities = df["City"].value_counts().sort_index().sort_values(ascending=False, kind="stable")
    top_c = cities.head(TOP_CITIES)
    rest_c = int(cities.iloc[TOP_CITIES:].sum())
    by_city = {"names": list(top_c.index) + (["יישובים אחרים"] if rest_c else []),
               "values": [int(v) for v in top_c] + ([rest_c] if rest_c else [])}

    # Services availability
    svc = {"names": [lbl for _, lbl in SERVICES],
           "values": [round(float(_yes(df[c]).mean()) * 100, 1) for c, _ in SERVICES],
           "counts": [int(_yes(df[c]).sum()) for c, _ in SERVICES]}

    # Bank × service heatmap (% of the bank's ATMs)
    cells = []
    for bi, b in enumerate(bank_order):
        sub = df[df["bank"] == b]
        for si, (c, _) in enumerate(SERVICES):
            cells.append([si, bi, round(float(_yes(sub[c]).mean()) * 100, 1), int(len(sub))])
    svc_heat = {"services": [lbl for _, lbl in SERVICES], "banks": bank_order, "cells": cells}

    # Location relative to branch, by bank (stacked %)
    loc_series = []
    for loc in LOCATION_ORDER:
        vals = []
        for b in bank_order:
            sub = df[df["bank"] == b]
            vals.append(round(float((sub["ATM_Location"] == loc).mean()) * 100, 1))
        loc_series.append({"name": LOCATION_LABEL[loc], "data": vals})
    loc_total = [{"name": LOCATION_LABEL[l], "n": _int((df["ATM_Location"] == l).sum()),
                  "share": f"{(df['ATM_Location'] == l).mean() * 100:.1f}"} for l in LOCATION_ORDER]

    # Commission + accessibility by bank (share)
    comm = [round(float(_yes(df[df["bank"] == b]["Commission"]).mean()) * 100, 1) for b in bank_order]
    acc_no = [round(float((~_yes(df[df["bank"] == b]["Handicap_Access"])).mean()) * 100, 1) for b in bank_order]
    bank_rows = [{
        "name": b, "n": _int(banks[b]), "comm": f"{comm[i]:.1f}", "acc_no": f"{acc_no[i]:.1f}",
        "cities": _int(df[df["bank"] == b]["City"].nunique()),
        "off": f"{df[df['bank'] == b]['ATM_Location'].isin(OFF_BRANCH).mean() * 100:.1f}",
    } for i, b in enumerate(bank_order)]

    # Full-service share by city (top cities): withdrawal + cash deposit + cheque
    full = _yes(df["Casd_Withdrawal"]) & _yes(df["Cash_Deposit"]) & _yes(df["Cheque_Deposit"])
    df["full"] = full
    city_full = [round(float(df[df["City"] == c]["full"].mean()) * 100, 1) for c in top_c.index]
    city_rows = [{"name": c, "n": _int(v), "full": f"{city_full[i]:.1f}"}
                 for i, (c, v) in enumerate(top_c.items())]

    # Insights ------------------------------------------------------------
    def ins_banks():
        if len(banks) < 2:
            return None
        a, b = banks.index[0], banks.index[1]
        share = (banks.iloc[0] + banks.iloc[1]) / n
        return (f"בנק {a} ובנק {b} מפעילים יחד {_int(banks.iloc[0] + banks.iloc[1])} מכשירים — "
                f"{_pct(share)} מכלל {_int(n)} הכספומטים במרשם.")

    def ins_cities():
        if len(cities) < 3:
            return None
        top3 = cities.head(3)
        share = top3.sum() / n
        return (f"{top3.index[0]} מובילה עם {_int(top3.iloc[0])} מכשירים, ואחריה {top3.index[1]} "
                f"ו{top3.index[2]}; שלוש הערים מרכזות {_pct(share)} מהמכשירים, "
                f"והשאר פרוסים ב-{_int(len(cities) - 3)} יישובים.")

    def ins_commission():
        c = _yes(df["Commission"])
        if c.sum() < 20:
            return None
        lead = df[c]["bank"].value_counts().sort_index().sort_values(ascending=False, kind="stable")
        return (f"{_int(c.sum())} מכשירים ({_pct(c.mean())}) גובים עמלה; "
                f"{_pct(lead.iloc[0] / c.sum())} מהם של בנק {lead.index[0]}.")

    def ins_forex():
        f = _yes(df["Forex_Transaction"])
        if f.sum() < 20:
            return None
        rate = df.groupby("bank")["Forex_Transaction"].apply(lambda s: _yes(s).mean())
        rate = rate[banks.reindex(rate.index) >= 50]
        if rate.empty:
            return None
        rate = rate.sort_index().sort_values(ascending=False, kind="stable")
        only = "רק " if f.mean() < 0.5 else ""
        return (f"{only}{_pct(f.mean())} מהמכשירים מציעים פעולות מט״ח; השיעור הגבוה ביותר "
                f"בבנק {rate.index[0]} ({_pct(rate.iloc[0])}).")

    def ins_offbranch():
        off = df["ATM_Location"].isin(OFF_BRANCH)
        if off.sum() < 20:
            return None
        lead = df[off]["bank"].value_counts().sort_index().sort_values(ascending=False, kind="stable")
        return (f"{_int(off.sum())} מכשירים ({_pct(off.mean())}) אינם צמודים לסניף; "
                f"לבנק {lead.index[0]} הכי הרבה מהם ({_int(lead.iloc[0])}).")

    def ins_deposit():
        d = _yes(df["Cash_Deposit"])
        w = _yes(df["Casd_Withdrawal"])
        return (f"{_pct(w.mean())} מהמכשירים מאפשרים משיכת מזומן ו-{_pct(d.mean())} הפקדת מזומן; "
                f"{_pct(full.mean())} מציעים משיכה, הפקדת מזומן והפקדת שיקים יחד.")

    def ins_access():
        a = ~_yes(df["Handicap_Access"])
        if a.sum() == 0:
            return "כל המכשירים במרשם מסומנים כנגישים."
        return f"{_int(a.sum())} מכשירים ({_pct(a.mean(), 1)}) אינם מסומנים כנגישים לאנשים עם מוגבלות."

    rules = [("banks", ins_banks()), ("cities", ins_cities()), ("deposit", ins_deposit()),
             ("commission", ins_commission()), ("forex", ins_forex()),
             ("offbranch", ins_offbranch()), ("access", ins_access())]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    bad_geo = int((~df["geo_ok"]).sum())
    return {
        "agent_data": {
            "summary_he": (f"מרשם הכספומטים של הבנקים בישראל: {_int(n)} מכשירים של {len(banks)} בנקים "
                           f"ב-{_int(len(cities))} יישובים — מיקום, שירותים, עמלה ונגישות."),
            "dataset_kind": "map",
            "suggested_tags": ["בנקאות", "כספומטים", "שירותים פיננסיים", "נגישות"],
            "related_ids": ["32348d0b-dc49-4bd0-a931-860e55709689", "9f357b63-99f6-4b52-8c9e-fa53c86e63e4",
                            "75989c99-3122-4656-943c-3b758262cbf4"],
            "spatial_coverage": "ישראל",
        },
        "kpis": {
            "atms": {"value": n, "display": _int(n)},
            "banks": {"value": int(len(banks)), "display": _int(len(banks))},
            "cities": {"value": int(len(cities)), "display": _int(len(cities))},
            "deposit": {"value": float(_yes(df["Cash_Deposit"]).mean()),
                        "display": _pct(_yes(df["Cash_Deposit"]).mean())},
        },
        "charts": {"banks": by_bank, "cities": by_city, "services": svc, "svc_heat": svc_heat,
                   "location": {"banks": bank_order, "series": loc_series},
                   "commission": {"banks": bank_order, "comm": comm, "acc_no": acc_no},
                   "city_full": {"names": list(top_c.index), "values": city_full}},
        "tables": {"banks": bank_rows, "cities": city_rows, "location": loc_total,
                   "services": [{"name": svc["names"][i], "n": _int(svc["counts"][i]),
                                 "share": f"{svc['values'][i]:.1f}"} for i in range(len(SERVICES))]},
        "insights": insights,
        "labels": {
            "lede": (f"{_int(n)} כספומטים של {len(banks)} בנקים ב-{_int(len(cities))} יישובים "
                     f"({_int(raw_rows)} שורות במרשם; מכשיר שמשויך לשני סניפים נספר פעם אחת)."),
            "map_note": (f"כל המכשירים על המפה; לחיצה על נקודה מציגה את הבנק, הכתובת והשירותים. "
                         f"{_int(bad_geo)} מכשירים רשומים בקואורדינטות בפורמט אחר ומוצגים במיקום שגוי."),
            "banks_aria": f"עמודות אופקיות: מספר הכספומטים של כל אחד מ-{len(banks)} הבנקים.",
            "cities_aria": f"עמודות אופקיות: {TOP_CITIES} היישובים עם הכי הרבה כספומטים.",
            "services_aria": "עמודות: שיעור המכשירים שמציעים כל שירות.",
            "heat_aria": "מפת חום: שיעור המכשירים שמציעים כל שירות, לפי בנק.",
            "location_aria": "עמודות מוערמות באחוזים: מיקום המכשיר ביחס לסניף, לפי בנק.",
            "commission_aria": "עמודות: שיעור המכשירים שגובים עמלה ושיעור המכשירים שאינם נגישים, לפי בנק.",
            "city_full_aria": f"עמודות: שיעור המכשירים עם משיכה, הפקדת מזומן והפקדת שיקים ב-{TOP_CITIES} היישובים הגדולים.",
        },
    }
