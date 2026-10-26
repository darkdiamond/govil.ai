"""סניפים לסליקה — Bank of Israel registry of clearing branch codes.

One row per (entity, branch code) that can send or receive interbank
transfers: commercial banks, the Postal Bank, the Bank of Israel, the
clearing house, and non-bank payment firms (branch_type "חוץ בנקאי").
The Hebrew resource is the input; the English resource is a translated
twin of the same rows.

A code with a close_date is closed (the registry keeps it). A code with a
merge_branch but no close_date is still listed but routed to another
branch of the same entity ("redirected"). Counts are of ACTIVE codes
(no close_date) unless a sentence says otherwise.

open_date quirks: some codes carry a placeholder year before 1950 (original
opening unknown), and some dates were stamped on dozens of codes at once
(bulk re-registration). Both are detected from the data and disclosed.
"""
import re

import pandas as pd

TOP_BANKS = 12            # rows of the bank × type chart
TOP_CITIES = 15
PRESENCE_CITIES = 10      # heatmap rows
PRESENCE_BANKS = 8        # heatmap columns
PLACEHOLDER_BEFORE = 1950  # open years before this are placeholders
BULK_MIN = 40             # one exact open_date on ≥ this many codes = bulk registration
TABLE_YEARS = 20
RECENT_FULL_YEARS = 3
HUB_MIN_CODES = 20
HUB_MIN_SHARE = 0.6
SHARED_MIN = 5
SMALL_MAX = 2
REGULAR = "רגיל"
NON_BANK = "חוץ בנקאי"
EXEC = "יחידת ביצוע"
SPECIAL = "מיוחד"
DIGITAL = "סניף דיגיטלי"
TYPE_ORDER = [REGULAR, SPECIAL, EXEC, DIGITAL, NON_BANK]
OTHER = "גופים אחרים"


def _int(n):
    return f"{int(n):,}"


def _pct(x, digits=0):
    return f"{x * 100:.{digits}f}%"


def short_name(name):
    """'בנק הפועלים בע"מ' → 'בנק הפועלים' (labels only)."""
    s = re.sub(r'\s*בע["״]?מ\s*$', "", name.strip())
    return s or name.strip()


def _ranked(series):
    vc = series.value_counts()
    return vc.sort_index().sort_values(ascending=False, kind="stable")


def _types(series):
    seen = set(series)
    known = [t for t in TYPE_ORDER if t in seen]
    return known + sorted(seen - set(TYPE_ORDER))


def _prepare(df):
    out = df.copy()
    for c in ["id", "name", "branch_code", "branch_name", "city", "branch_type",
              "open_date", "close_date", "merge_branch"]:
        out[c] = out[c].str.strip()
    out["bank"] = out["name"].map(short_name)
    out["city"] = out["city"].replace("", "לא צוין")
    out["branch_type"] = out["branch_type"].replace("", "לא צוין")
    out["opened"] = pd.to_datetime(out["open_date"], format="%d/%m/%Y", errors="coerce")
    out["closed"] = pd.to_datetime(out["close_date"], format="%d/%m/%Y", errors="coerce")
    out["active"] = out["close_date"] == ""
    out["redirected"] = out["active"] & (out["merge_branch"] != "")
    return out


# ── insights ────────────────────────────────────────────────────────────────

def insight_top_banks(act):
    banks = _ranked(act["bank"])
    if len(banks) < 4 or len(act) == 0:
        return None
    top = banks.head(3)
    share = top.sum() / len(act)
    names = ", ".join(f"{n} ({_int(v)})" for n, v in top.items())
    return (f"שלושת הגופים הגדולים — {names} — מחזיקים {_pct(share)} מ-{_int(len(act))} "
            f"קודי הסליקה הפעילים, מתוך {_int(banks.size)} גופים במאגר.")


def insight_regular_leader(act):
    """Leader by all codes vs leader by regular (customer) branches."""
    if act.empty:
        return None
    all_rank = _ranked(act["bank"])
    reg = act[act["branch_type"] == REGULAR]
    if reg.empty:
        return None
    reg_rank = _ranked(reg["bank"])
    lead = all_rank.index[0]
    if lead == reg_rank.index[0]:
        return None
    sub = act[act["bank"] == lead]
    non = int((sub["branch_type"] != REGULAR).sum())
    return (f"{lead} מוביל במספר הקודים ({_int(all_rank.iloc[0])}), אבל {_int(non)} מהם "
            f"אינם סניפים רגילים (יחידות ביצוע, סניפים מיוחדים ודיגיטליים). בסניפים רגילים "
            f"מוביל {reg_rank.index[0]} עם {_int(reg_rank.iloc[0])}, לעומת "
            f"{_int(reg_rank.get(lead, 0))} ב{lead}.")


def insight_exec(act):
    """Concentration of execution units (back-office codes) in one entity."""
    ex = act[act["branch_type"] == EXEC]
    if len(ex) < 10:
        return None
    banks = _ranked(ex["bank"])
    share = banks.iloc[0] / len(ex)
    if share < 0.3:
        return None
    lead = banks.index[0]
    own = int((act["bank"] == lead).sum())
    return (f"{_pct(len(ex) / len(act))} מהקודים הפעילים ({_int(len(ex))}) הם יחידות ביצוע, "
            f"ו-{_pct(share)} מהן ({_int(banks.iloc[0])}) של {lead} — "
            f"{_int(banks.iloc[0])} מתוך {_int(own)} הקודים הפעילים שלו.")


def insight_non_bank(act):
    nb = act[act["branch_type"] == NON_BANK]
    if nb.empty:
        return None
    ents = _ranked(nb["bank"])
    if ents.size == 1:
        return (f"גוף חוץ־בנקאי אחד, {ents.index[0]}, רשום במאגר עם {_int(len(nb))} קודי סליקה.")
    return (f"{_int(ents.size)} גופים חוץ־בנקאיים רשומים במאגר עם {_int(len(nb))} קודי סליקה; "
            f"הגדול שבהם, {ents.index[0]}, מחזיק {_int(ents.iloc[0])} מהם.")


def insight_hub(act, top_cities):
    """A large city where most codes are not regular customer branches."""
    best = None
    for rank, city in enumerate(top_cities):
        sub = act[act["city"] == city]
        if len(sub) < HUB_MIN_CODES:
            continue
        share = float((sub["branch_type"] != REGULAR).mean())
        key = (share, -rank)
        if share >= HUB_MIN_SHARE and (best is None or key > best[0]):
            best = (key, city, sub)
    if best is None:
        return None
    _, city, sub = best
    non = sub[sub["branch_type"] != REGULAR]
    banks = _ranked(non["bank"])
    lead = (f", רובם של {banks.index[0]} ({_int(banks.iloc[0])})"
            if banks.iloc[0] / len(non) > 0.5 else "")
    n_reg = len(sub) - len(non)
    head = (f"באף אחד מ-{_int(len(sub))} הקודים הפעילים ב{city} אין סניף רגיל"
            if n_reg == 0 else
            f"ב{city} רק {_int(n_reg)} מתוך {_int(len(sub))} הקודים הפעילים הם סניפים רגילים")
    return (f"{head} — {_pct(len(non) / len(sub))} הם יחידות ביצוע, סניפים מיוחדים או "
            f"דיגיטליים{lead}.")


def insight_redirected(act):
    red = act[act["redirected"]]
    if len(red) < 3:
        return None
    banks = _ranked(red["bank"])
    lead = (f"; {_int(banks.iloc[0])} מהם של {banks.index[0]}"
            if banks.iloc[0] / len(red) >= 0.4 else "")
    return (f"{_int(len(red))} קודים פעילים ({_pct(len(red) / len(act), 1)}) רשומים כממוזגים "
            f"לסניף ממשיך אף שאין להם תאריך סגירה{lead}.")


def insight_closures(df):
    cl = df[~df["active"]]
    if cl.empty:
        return None
    banks = _ranked(cl["bank"])
    last = cl["closed"].max()
    tail = f" תאריך הסגירה המאוחר ביותר במאגר: {last.strftime('%d/%m/%Y')}." if pd.notna(last) else ""
    top_n = int(banks.iloc[0])
    leaders = list(banks[banks == top_n].index)
    if top_n < 3 or len(leaders) > 2:
        lead = ""
    elif len(leaders) == 2:
        lead = f", בעיקר ב{leaders[0]} וב{leaders[1]} ({_int(top_n)} בכל אחד)"
    else:
        lead = f", בעיקר ב{leaders[0]} ({_int(top_n)})"
    return f"{_int(len(cl))} קודים במאגר נושאים תאריך סגירה{lead}.{tail}"


def shared_pairs(df):
    """Pairs of entities that list the same (branch_code, branch_name)."""
    sub = df[["branch_code", "branch_name", "bank"]].drop_duplicates()
    groups = sub.groupby(["branch_code", "branch_name"])["bank"].apply(lambda s: sorted(set(s)))
    counts = {}
    for banks in groups:
        if len(banks) < 2:
            continue
        for i in range(len(banks)):
            for j in range(i + 1, len(banks)):
                counts[(banks[i], banks[j])] = counts.get((banks[i], banks[j]), 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


def insight_shared(pairs, df):
    if not pairs or pairs[0][1] < SHARED_MIN:
        return None
    (a, b), n = pairs[0]
    na, nb = int((df["bank"] == a).sum()), int((df["bank"] == b).sum())
    small, big, n_small = (a, b, na) if na <= nb else (b, a, nb)
    return (f"{_int(n)} מתוך {_int(n_small)} הקודים של {small} רשומים גם תחת {big}, "
            f"באותו מספר סניף ובאותו שם סניף.")


def insight_openings(df, bulk_dates):
    op = df[df["opened"].notna() & (df["opened"].dt.year >= PLACEHOLDER_BEFORE)
            & ~df["open_date"].isin(bulk_dates)]
    if op.empty:
        return None
    last = op["opened"].max()
    last_full = last.year if last.month == 12 else last.year - 1
    first = last_full - RECENT_FULL_YEARS + 1
    rec = op[op["opened"].dt.year.between(first, last_full)]
    if len(rec) < 5:
        return None
    banks = _ranked(rec["bank"])
    partial = ("" if last_full == last.year else
               f" שנת {last.year} חלקית במאגר ואינה נכללת (נרשמו בה "
               f"{_int((op['opened'].dt.year == last.year).sum())} קודים).")
    return (f"בשנים {first} עד {last_full} נפתחו {_int(len(rec))} קודי סליקה חדשים, "
            f"המספר הגדול ביותר ב{banks.index[0]} ({_int(banks.iloc[0])}); לא נכללו "
            f"רישומים מרוכזים.{partial}")


def insight_small(act):
    banks = _ranked(act["bank"])
    small = banks[banks <= SMALL_MAX]
    if len(small) < 3:
        return None
    return (f"{_int(len(small))} מתוך {_int(banks.size)} הגופים מחזיקים עד {SMALL_MAX} קודי "
            f"סליקה פעילים כל אחד — יחד {_int(small.sum())} קודים, "
            f"{_pct(small.sum() / len(act), 1)} מהמאגר.")


# ── compute ─────────────────────────────────────────────────────────────────

def compute(frames):
    df = _prepare(frames["branches"])
    act = df[df["active"]]
    n_all, n_act = len(df), len(act)
    n_closed = n_all - n_act
    n_red = int(act["redirected"].sum())

    banks = _ranked(act["bank"])
    cities = _ranked(act["city"])
    types = _types(act["branch_type"])

    # 1. Codes by entity × type (top entities + others).
    top_banks = list(banks.index[:TOP_BANKS])
    rest = act[~act["bank"].isin(top_banks)]
    by_bt = act.groupby(["bank", "branch_type"]).size()
    rest_t = rest["branch_type"].value_counts()
    banks_chart = {
        "names": top_banks + ([OTHER] if len(rest) else []),
        "series": [{"name": t,
                    "data": [int(by_bt.get((b, t), 0)) for b in top_banks]
                    + ([int(rest_t.get(t, 0))] if len(rest) else [])}
                   for t in types],
    }
    n_cities_by_bank = act.groupby("bank")["city"].nunique()
    main_type = (act.groupby(["bank", "branch_type"]).size().reset_index(name="n")
                 .sort_values(["bank", "n", "branch_type"], ascending=[True, False, True], kind="stable")
                 .drop_duplicates("bank").set_index("bank")["branch_type"])
    t_banks = [{"name": b, "count": _int(v), "share": _pct(v / n_act, 1),
                "cities": _int(n_cities_by_bank.get(b, 0)), "main": main_type.get(b, "")}
               for b, v in banks.items()]

    # 2. Type split overall.
    type_counts = act["branch_type"].value_counts()
    types_chart = [{"name": t, "value": int(type_counts.get(t, 0))} for t in types]
    t_types = [{"name": t, "count": _int(type_counts.get(t, 0)),
                "share": _pct(type_counts.get(t, 0) / n_act, 1),
                "banks": _int(act.loc[act["branch_type"] == t, "bank"].nunique())} for t in types]

    # 3. Footprint: distinct cities per entity (top entities).
    fp = [(b, int(n_cities_by_bank.get(b, 0)), int(banks[b])) for b in top_banks]
    fp.sort(key=lambda r: (-r[1], -r[2], r[0]))
    footprint_chart = {"names": [r[0] for r in fp], "cities": [r[1] for r in fp],
                       "codes": [r[2] for r in fp]}
    t_footprint = [{"name": r[0], "cities": _int(r[1]), "codes": _int(r[2]),
                    "per_city": f"{r[2] / r[1]:.1f}" if r[1] else "—"} for r in fp]

    # 4. Top cities × type.
    top_cities = list(cities.index[:TOP_CITIES])
    by_ct = act.groupby(["city", "branch_type"]).size()
    cities_chart = {"names": top_cities,
                    "series": [{"name": t, "data": [int(by_ct.get((c, t), 0)) for c in top_cities]}
                               for t in types]}
    t_cities = [{"name": c, "count": _int(cities[c]), "share": _pct(cities[c] / n_act, 1),
                 "regular": _int(by_ct.get((c, REGULAR), 0))} for c in top_cities]

    # 5. Presence heatmap: top cities × top banks.
    p_cities = list(cities.index[:PRESENCE_CITIES])
    p_banks = list(banks.index[:PRESENCE_BANKS])
    by_cb = act.groupby(["city", "bank"]).size()
    presence = {"cities": p_cities, "banks": p_banks,
                "cells": [[bi, ci, int(by_cb.get((c, b), 0))]
                          for ci, c in enumerate(p_cities) for bi, b in enumerate(p_banks)]}
    presence["max"] = max((c[2] for c in presence["cells"]), default=0)
    t_presence = {"cols": p_banks,
                  "rows": [{"name": c, "vals": [_int(by_cb.get((c, b), 0)) for b in p_banks]}
                           for c in p_cities]}

    # 6. Openings / closures by year.
    date_counts = df.loc[df["opened"].notna(), "open_date"].value_counts()
    bulk_dates = sorted(d for d, n in date_counts.items()
                        if n >= BULK_MIN and pd.to_datetime(d, format="%d/%m/%Y").year >= PLACEHOLDER_BEFORE)
    valid = df[df["opened"].notna() & (df["opened"].dt.year >= PLACEHOLDER_BEFORE)]
    n_placeholder = int((df["opened"].notna() & (df["opened"].dt.year < PLACEHOLDER_BEFORE)).sum())
    n_no_date = int(df["opened"].isna().sum())
    is_bulk = valid["open_date"].isin(bulk_dates)
    org_y = valid.loc[~is_bulk, "opened"].dt.year.value_counts()
    bulk_y = valid.loc[is_bulk, "opened"].dt.year.value_counts()
    cl_y = df.loc[df["closed"].notna(), "closed"].dt.year.value_counts()
    yrs = set(valid["opened"].dt.year) | set(cl_y.index)
    years = list(range(min(yrs), max(yrs) + 1)) if yrs else []
    flow_chart = {"x": [str(y) for y in years],
                  "opened": [int(org_y.get(y, 0)) for y in years],
                  "bulk": [int(bulk_y.get(y, 0)) for y in years],
                  "closed": [int(cl_y.get(y, 0)) for y in years]}
    zoom_from = max(0, len(years) - TABLE_YEARS)
    flow_chart["zoom_start"] = round(zoom_from / max(len(years) - 1, 1) * 100, 1)
    t_flow = [{"year": str(y), "opened": _int(org_y.get(y, 0)), "bulk": _int(bulk_y.get(y, 0)),
               "closed": _int(cl_y.get(y, 0))} for y in years[-TABLE_YEARS:]]
    bulk_desc = ", ".join(f"{d} ({_int(date_counts[d])})" for d in
                          sorted(bulk_dates, key=lambda d: pd.to_datetime(d, format="%d/%m/%Y")))

    # 7. Closed and redirected codes by entity.
    st = df[~df["active"] | df["redirected"]]
    st_banks = _ranked(st["bank"])
    status_chart = {
        "names": list(st_banks.index),
        "series": [
            {"name": "מופנה לסניף אחר (פעיל)",
             "data": [int((act["redirected"] & (act["bank"] == b)).sum()) for b in st_banks.index]},
            {"name": "נסגר",
             "data": [int(((~df["active"]) & (df["bank"] == b)).sum()) for b in st_banks.index]},
        ],
    }
    t_status = [{"name": b, "redirected": _int(status_chart["series"][0]["data"][i]),
                 "closed": _int(status_chart["series"][1]["data"][i]),
                 "active": _int(banks.get(b, 0))} for i, b in enumerate(st_banks.index)]
    closed_rows = df[~df["active"]].sort_values(
        ["closed", "bank", "branch_code", "branch_name"], na_position="first", kind="stable")
    t_closed = [{"date": (r["closed"].strftime("%d/%m/%Y") if pd.notna(r["closed"]) else r["close_date"]),
                 "bank": r["bank"], "branch": r["branch_name"], "city": r["city"],
                 "type": r["branch_type"]}
                for _, r in closed_rows.tail(15).iloc[::-1].iterrows()]

    # 8. Codes listed under two entities.
    pairs = shared_pairs(df)
    t_shared = [{"a": a, "b": b, "count": _int(n)} for (a, b), n in pairs if n >= SHARED_MIN][:10]

    rules = [
        ("top_banks", insight_top_banks(act)),
        ("regular_leader", insight_regular_leader(act)),
        ("exec", insight_exec(act)),
        ("hub", insight_hub(act, top_cities)),
        ("non_bank", insight_non_bank(act)),
        ("redirected", insight_redirected(act)),
        ("closures", insight_closures(df)),
        ("shared", insight_shared(pairs, df)),
        ("openings", insight_openings(df, bulk_dates)),
        ("small", insight_small(act)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    regular_share = float((act["branch_type"] == REGULAR).mean()) if n_act else 0.0
    kpis = {
        "active": {"value": n_act, "display": _int(n_act), "tone": "brand",
                   "label": "קודי סליקה פעילים"},
        "banks": {"value": int(banks.size), "display": _int(banks.size), "tone": "brand",
                  "label": "בנקים וגופים משתתפים"},
        "cities": {"value": int(cities.size), "display": _int(cities.size), "tone": "brand",
                   "label": "יישובים"},
        "regular": {"value": regular_share, "display": _pct(regular_share), "tone": "info",
                    "label": "מהקודים הפעילים הם סניפים רגילים"},
        "redirected": {"value": n_red, "display": _int(n_red), "tone": "info" if n_red else "brand",
                       "label": "קודים פעילים המופנים לסניף אחר"},
        "closed": {"value": n_closed, "display": _int(n_closed),
                   "tone": "warn" if n_closed else "brand",
                   "label": "קודים שנסגרו ונשמרו במאגר"},
    }

    span = (f"{years[0]} עד {years[-1]}" if years else "")
    labels = {
        "lede": (f"מאגר בנק ישראל של קודי הסניפים המשמשים לסליקה — העברות כספיות בין "
                 f"בנקים וגופים פיננסיים. {_int(n_act)} קודים פעילים של {_int(banks.size)} גופים "
                 f"ב-{_int(cities.size)} יישובים, ועוד {_int(n_closed)} קודים סגורים שנשמרו במאגר. "
                 f"קוד סליקה אינו בהכרח סניף קבלת קהל: לצד סניפים רגילים רשומים יחידות ביצוע, "
                 f"סניפים מיוחדים, סניפים דיגיטליים וגופים חוץ־בנקאיים."),
        "banks_note": (f"קודים פעילים לפי גוף וסוג. {len(top_banks)} הגופים הגדולים; "
                       f"{_int(banks.size - len(top_banks))} הקטנים מקובצים ב\"{OTHER}\"."
                       if len(rest) else "קודים פעילים לפי גוף וסוג."),
        "banks_aria": (f"תרשים עמודות אופקי מוערם: קודי סליקה פעילים לפי גוף וסוג סניף, "
                       f"{len(top_banks)} הגופים הגדולים."),
        "banks_caption": "קודי סליקה פעילים לכל גוף: מספר, שיעור, יישובים וסוג הסניף הנפוץ.",
        "types_aria": f"תרשים טבעת: חלוקת {_int(n_act)} הקודים הפעילים ל-{len(types)} סוגי סניף.",
        "types_caption": "קודי סליקה פעילים לפי סוג סניף.",
        "footprint_note": (f"מספר היישובים שבהם יש לכל אחד מ-{len(fp)} הגופים הגדולים לפחות "
                           f"קוד פעיל אחד."),
        "footprint_aria": f"תרשים עמודות אופקי: מספר היישובים לכל גוף, {len(fp)} הגופים הגדולים.",
        "footprint_caption": "פריסה גאוגרפית לכל גוף: יישובים, קודים וממוצע קודים ליישוב.",
        "cities_note": (f"{len(top_cities)} היישובים עם הכי הרבה קודים פעילים, לפי סוג סניף — "
                        f"מתוך {_int(cities.size)} יישובים."),
        "cities_aria": (f"תרשים עמודות אופקי מוערם: {len(top_cities)} היישובים עם הכי הרבה "
                        f"קודי סליקה פעילים, לפי סוג סניף."),
        "cities_caption": f"{len(top_cities)} היישובים עם הכי הרבה קודים פעילים.",
        "presence_note": (f"קודים פעילים של {len(p_banks)} הגופים הגדולים ב-{len(p_cities)} "
                          f"היישובים המובילים. גוון כהה = יותר קודים."),
        "presence_aria": (f"מפת חום: קודים פעילים של {len(p_banks)} הגופים הגדולים "
                          f"ב-{len(p_cities)} היישובים עם הכי הרבה קודים."),
        "presence_caption": f"קודים פעילים לפי יישוב וגוף — {len(p_cities)} יישובים, {len(p_banks)} גופים.",
        "flow_note": (f"קודים לפי שנת הפתיחה ושנת הסגירה הרשומות, {span}. "
                      + (f"לא מוצגים {_int(n_placeholder)} קודים עם שנת פתיחה סמלית לפני "
                         f"{PLACEHOLDER_BEFORE} (תאריך הפתיחה המקורי אינו ידוע)"
                         if n_placeholder else "")
                      + (f" ו-{_int(n_no_date)} ללא תאריך פתיחה" if n_no_date else "")
                      + ". "
                      + (f"תאריך פתיחה אחד שנרשם על {BULK_MIN} קודים או יותר מסומן כ\"רישום מרוכז\": "
                         f"{bulk_desc}." if bulk_dates else "")),
        "flow_aria": f"תרשים עמודות: קודי סליקה שנפתחו ונסגרו בכל שנה, {span}.",
        "flow_caption": f"קודים שנפתחו ונסגרו לפי שנה, {len(t_flow)} השנים האחרונות.",
        "status_note": (f"{_int(n_red)} קודים פעילים המופנים לסניף ממשיך ו-{_int(n_closed)} "
                        f"קודים שנסגרו, לפי גוף."),
        "status_aria": "תרשים עמודות אופקי מוערם: קודים מופנים וקודים סגורים לפי גוף.",
        "status_caption": "קודים מופנים, קודים סגורים וקודים פעילים לפי גוף.",
        "closed_caption": "הקודים שנסגרו לאחרונה, לפי תאריך הסגירה.",
        "closed_summary": f"הקודים שנסגרו ({_int(len(t_closed))} האחרונים)",
        "shared_caption": "זוגות גופים הרושמים את אותו מספר סניף ואותו שם סניף.",
        "shared_note": (f"זוגות גופים שרושמים את אותו מספר סניף עם אותו שם סניף, וכמה קודים כאלה "
                        f"יש לכל זוג (זוגות עם {SHARED_MIN} קודים משותפים לפחות)."),
    }

    return {
        "agent_data": {
            "summary_he": (f"{_int(n_act)} קודי סליקה פעילים של {_int(banks.size)} בנקים וגופים "
                           f"פיננסיים ב-{_int(cities.size)} יישובים — לפי גוף, סוג סניף, יישוב, "
                           f"פתיחות וסגירות, וקודים המופנים לסניף אחר."),
            "dataset_kind": "registry",
            "suggested_tags": ["בנקאות", "סניפי בנק", "סליקה", "העברות כספיות", "תאגידים בנקאיים"],
            "related_ids": ["32348d0b-dc49-4bd0-a931-860e55709689",
                            "75989c99-3122-4656-943c-3b758262cbf4",
                            "67759a6a-4167-439b-af53-0eb792321264"],
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": {
            "banks": banks_chart,
            "types": types_chart,
            "footprint": footprint_chart,
            "cities": cities_chart,
            "presence": presence,
            "flow": flow_chart,
            "status": status_chart,
        },
        "tables": {"banks": t_banks, "types": t_types, "footprint": t_footprint,
                   "cities": t_cities, "presence": t_presence, "flow": t_flow,
                   "status": t_status, "closed": t_closed, "shared": t_shared},
        "flags": {"shared": bool(t_shared), "closed": bool(t_closed),
                  "status": bool(status_chart["names"])},
        "insights": insights,
        "labels": labels,
    }
