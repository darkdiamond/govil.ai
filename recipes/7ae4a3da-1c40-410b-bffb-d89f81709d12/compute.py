"""PLMN codes in Israel (MCC/MNC registry), Ministry of Communications.

One small table: Operator, MCC, MNC. The page is a lookup: which operator
holds each mobile network code, plus a code map that shows which numbers in
the range are not on the list, and how the codes split between operators.
"""

import re

import pandas as pd

# Known operators: a Hebrew display name for the well-known brands, matched
# on a substring of the normalised English legal name. Anything else keeps
# its legal name as written in the data.
KNOWN = [
    ("PARTNER COMMUNICATIONS", "פרטנר", False),
    ("CELLCOM", "סלקום", False),
    ("PELEPHONE", "פלאפון", False),
    ("HOT MOBILE", "הוט מובייל", False),
    ("RAMI LEVY", "רמי לוי תקשורת", False),
    ("BEZEQ", "בזק", False),
    ("TELZAR 019", "019 טלזר", False),
    ("XPHONE 018", "018 אקספון", False),
    ("JAWWAL", "ג׳וואל", True),
    ("OOREDOO PALESTINE", "אורדו פלסטין", True),
]
IMOD = "IMOD"

TOP_N = 24
BLANK_LABEL = "ללא שם מפעיל"


def _norm(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def _key(s):
    return _norm(s).upper()


def _he_name(name_en):
    k = _key(name_en)
    if k == IMOD:
        return "משרד הביטחון", False
    for needle, he, pal in KNOWN:
        if needle in k:
            return he, pal
    return "", False


def _code_int(s):
    s = _norm(s).replace(",", "")
    if re.fullmatch(r"\d+(\.0+)?", s):
        return int(float(s))
    return None


def _mnc_str(s):
    n = _code_int(s)
    if n is None:
        return _norm(s)
    return f"{n:02d}"


def _join_he(items):
    items = list(items)
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    last = items[-1]
    conj = " ו" if re.match(r"[\u05d0-\u05ea]", last) else " ו-"
    return ", ".join(items[:-1]) + conj + last


def _codes_he(n):
    return "קוד אחד" if n == 1 else f"{n:,} קודים"


def _ops_he(n):
    return "מפעיל אחד" if n == 1 else f"{n:,} מפעילים"


def _label(op):
    """Short label for charts/insights: Hebrew name if known, else legal name."""
    return op["he"] or op["en"]


# ---------------------------------------------------------------- insights

def insight_structure(mccs, rows, main_mcc, lo, hi):
    n = len(rows)
    if not n:
        return None
    if len(mccs) == 1:
        rng = f"מ-{lo} עד {hi}" if lo and hi and lo != hi else ""
        tail = f", {rng}" if rng else ""
        lead = "הקוד היחיד במאגר רשום" if n == 1 else f"כל {n:,} הקודים במאגר רשומים"
        return (f"{lead} תחת קוד המדינה {main_mcc} (MCC) של ישראל, "
                f"וקוד הרשת (MNC) הוא שמבדיל בין המפעילים{tail}. "
                f"מזהה הרשת המלא (PLMN) הוא צירוף השניים, למשל {rows[0]['plmn']}.")
    parts = [f"{m} ({_codes_he(c)})" for m, c in mccs]
    return f"הקודים במאגר מתחלקים בין {len(mccs)} קודי מדינה (MCC): {_join_he(parts)}."


def insight_multi(ops):
    multi = [o for o in ops if o["n"] > 1]
    if not multi:
        return None
    parts = [f"{_label(o)} ({o['n']}: {', '.join(o['codes'])})" for o in multi[:5]]
    more = f" ועוד {len(multi) - 5}" if len(multi) > 5 else ""
    held = sum(o["n"] for o in multi)
    lead = ("מפעיל אחד מחזיק" if len(multi) == 1 else f"{len(multi)} מפעילים מחזיקים")
    return (f"{lead} יותר מקוד רשת אחד, ויחד {held:,} קודים: "
            f"{_join_he(parts)}{more}.")


def insight_single(ops):
    n_ops = len(ops)
    single = sum(1 for o in ops if o["n"] == 1)
    if n_ops < 3 or single * 2 <= n_ops:
        return None
    return (f"רוב המפעילים מחזיקים קוד רשת יחיד: {single:,} מתוך {n_ops:,}.")


def insight_gaps(gaps, lo, hi):
    if not gaps:
        return None
    if len(gaps) == 1:
        return f"בטווח {lo}-{hi} לא מופיע ברשימה קוד רשת אחד: {gaps[0]}."
    shown = gaps[:10]
    more = f" ועוד {len(gaps) - 10}" if len(gaps) > 10 else ""
    return (f"בטווח {lo}-{hi} לא מופיעים ברשימה {len(gaps):,} קודי רשת: "
            f"{_join_he(shown)}{more}.")


def insight_blank(blank_codes):
    if not blank_codes:
        return None
    if len(blank_codes) == 1:
        return f"הקוד {blank_codes[0]} מופיע ברשימה ללא שם מפעיל."
    return (f"{len(blank_codes):,} קודים מופיעים ברשימה ללא שם מפעיל: "
            f"{_join_he(blank_codes)}.")


def insight_pal(ops):
    pal = [o for o in ops if o["pal"]]
    if not pal:
        return None
    codes = [c for o in pal for c in o["plmn"]]
    parts = [f"{o['he']} ({', '.join(o['plmn'])})" for o in pal]
    if len(pal) == 1:
        return (f"גם מפעילה סלולרית פלסטינית רשומה תחת קוד המדינה הישראלי: {parts[0]}.")
    return (f"{_codes_he(len(codes))} ברשימה רשומים למפעילות סלולר פלסטיניות, "
            f"תחת קוד המדינה הישראלי: {_join_he(parts)}.")


def insight_dups(dups):
    if not dups:
        return None
    if len(dups) == 1:
        return f"הקוד {dups[0]} מופיע ברשימה יותר מפעם אחת."
    return f"{len(dups):,} קודים מופיעים ברשימה יותר מפעם אחת: {_join_he(dups)}."


# ---------------------------------------------------------------- compute

def compute(frames):
    df = frames["codes"].copy()
    df["op"] = df["Operator"].map(_norm)
    df["mcc"] = df["MCC"].map(_norm)
    df["mnc_raw"] = df["MNC"].map(_norm)
    df = df[(df["mcc"] != "") & (df["mnc_raw"] != "")].copy()
    df["mcc_i"] = df["mcc"].map(_code_int)
    df["mnc_i"] = df["mnc_raw"].map(_code_int)
    df["mnc"] = df["mnc_raw"].map(_mnc_str)
    df["plmn"] = df["mcc"] + "-" + df["mnc"]
    # Total sort: MCC, MNC numeric (non-numeric last), then text keys.
    df["s1"] = df["mcc_i"].fillna(10**9)
    df["s2"] = df["mnc_i"].fillna(10**9)
    df["opk"] = df["op"].map(_key)
    df = df.sort_values(["s1", "mcc", "s2", "mnc", "opk", "op"], kind="mergesort")
    df = df.reset_index(drop=True)

    # Operators (named only), keyed by normalised name.
    ops_map = {}
    for r in df.itertuples():
        if not r.op:
            continue
        k = r.opk
        if k not in ops_map:
            he, pal = _he_name(r.op)
            ops_map[k] = {"key": k, "en": r.op, "he": he, "pal": pal,
                          "codes": [], "plmn": []}
        ops_map[k]["codes"].append(r.mnc)
        ops_map[k]["plmn"].append(r.plmn)
    ops = list(ops_map.values())
    for o in ops:
        o["n"] = len(o["codes"])
    ops.sort(key=lambda o: (-o["n"], o["key"]))

    # Rows for the full table.
    rows = []
    for r in df.itertuples():
        o = ops_map.get(r.opk) if r.op else None
        rows.append({
            "plmn": r.plmn,
            "mcc": r.mcc,
            "mnc": r.mnc,
            "he": o["he"] if o else "",
            "en": r.op if r.op else BLANK_LABEL,
            "blank": not bool(r.op),
            "n_op": o["n"] if o else 0,
        })

    # MCCs.
    mcc_counts = df.groupby("mcc", sort=False).size()
    mccs = sorted(((m, int(c)) for m, c in mcc_counts.items()),
                  key=lambda t: (-t[1], t[0]))
    main_mcc = mccs[0][0] if mccs else ""

    # Code map over the main MCC: every number from 1 to the highest listed.
    main = df[(df["mcc"] == main_mcc) & df["mnc_i"].notna()]
    nums = sorted(set(int(v) for v in main["mnc_i"]))
    grid, gaps, lo, hi = [], [], "", ""
    if nums:
        top = nums[-1]
        lo, hi = f"{1:02d}", f"{top:02d}"
        by_num = {}
        for r in main.itertuples():
            by_num.setdefault(int(r.mnc_i), []).append(r)
        if top <= 120:
            for i in range(1, top + 1):
                code = f"{i:02d}"
                if i in by_num:
                    names = []
                    for r in by_num[i]:
                        if r.op:
                            o = ops_map[r.opk]
                            names.append(_label(o))
                        else:
                            names.append(BLANK_LABEL)
                    grid.append({"code": code, "plmn": f"{main_mcc}-{code}",
                                 "label": " / ".join(names),
                                 "state": "blank" if all(not r.op for r in by_num[i]) else "used"})
                else:
                    grid.append({"code": code, "plmn": f"{main_mcc}-{code}",
                                 "label": "לא ברשימה", "state": "gap"})
                    gaps.append(code)
        else:
            gaps = [f"{i:02d}" for i in range(1, top + 1) if i not in by_num]

    blank_codes = [r["plmn"] for r in rows if r["blank"]]
    dup_series = df.groupby("plmn", sort=False).size()
    dups = sorted(p for p, c in dup_series.items() if c > 1)
    n_codes = int(df["plmn"].nunique())
    n_ops = len(ops)
    multi = [o for o in ops if o["n"] > 1]

    # Chart: codes per operator, top-N + "אחר".
    shown = ops[:TOP_N]
    rest = ops[TOP_N:]
    ch_names = [_label(o) for o in shown]
    ch_full = [o["en"] for o in shown]
    ch_vals = [o["n"] for o in shown]
    ch_codes = [", ".join(o["codes"]) for o in shown]
    if rest:
        ch_names.append(f"אחר ({_ops_he(len(rest))})")
        ch_full.append(f"{len(rest):,} מפעילים נוספים עם קוד אחד או יותר")
        ch_vals.append(sum(o["n"] for o in rest))
        ch_codes.append("")
    if blank_codes:
        ch_names.append(BLANK_LABEL)
        ch_full.append(BLANK_LABEL)
        ch_vals.append(len(blank_codes))
        ch_codes.append(", ".join(c.split("-", 1)[1] for c in blank_codes))
    by_op_table = [{"name": n, "full": f, "n": v, "codes": c}
                   for n, f, v, c in zip(ch_names, ch_full, ch_vals, ch_codes)]

    # Insights.
    ins = [
        ("structure", insight_structure(mccs, rows, main_mcc, lo, hi)),
        ("multi", insight_multi(ops)),
        ("single", insight_single(ops)),
        ("gaps", insight_gaps(gaps, lo, hi)),
        ("pal", insight_pal(ops)),
        ("blank", insight_blank(blank_codes)),
        ("dups", insight_dups(dups)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in ins if t]

    # KPIs.
    kpis = {
        "codes": {"value": n_codes, "display": f"{n_codes:,}", "tone": "brand"},
        "operators": {"value": n_ops, "display": f"{n_ops:,}", "tone": "brand"},
        "multi": {"value": len(multi), "display": f"{len(multi):,}",
                  "tone": "info" if multi else "brand"},
        "gaps": {"value": len(gaps), "display": f"{len(gaps):,}",
                 "tone": "warn" if gaps else "ok"},
    }
    if len(mccs) == 1:
        kpis["mcc"] = {"value": main_mcc, "display": main_mcc, "tone": "brand"}
        mcc_label = "קוד המדינה (MCC)"
        kpi_order = ["mcc", "codes", "operators", "multi", "gaps"]
    else:
        kpis["mcc"] = {"value": len(mccs), "display": f"{len(mccs):,}", "tone": "brand"}
        mcc_label = "קודי מדינה (MCC) במאגר"
        kpi_order = ["mcc", "codes", "operators", "multi", "gaps"]

    top_op = ops[0] if ops else None
    if top_op and top_op["n"] > 1:
        n_single = n_ops - len(multi)
        single_txt = ("מפעיל אחד מחזיק קוד אחד בלבד" if n_single == 1
                      else f"{n_single:,} מפעילים מחזיקים קוד אחד בלבד")
        lede_ops = (f"המספר הגדול ביותר של קודים: {_label(top_op)} ({top_op['n']:,}: "
                    f"{', '.join(top_op['codes'])}). {single_txt}.")
        aria_ops = (f"גרף עמודות אופקי: מספר קודי הרשת לכל מפעיל. "
                    f"{_label(top_op)} מוביל עם {_codes_he(top_op['n'])}.")
    else:
        lede_ops = f"כל אחד מ-{_ops_he(n_ops)} במאגר מחזיק קוד רשת אחד."
        aria_ops = "גרף עמודות אופקי: מספר קודי הרשת לכל מפעיל, קוד אחד לכל מפעיל."
    if rest:
        lede_ops += (f" בגרף מוצגים {len(shown):,} המפעילים המובילים; "
                     f"{_ops_he(len(rest))} נוספים מקובצים תחת \"אחר\".")

    if grid:
        n_used = sum(1 for g in grid if g["state"] != "gap")
        grid_lede = (f"כל המספרים מ-{lo} עד {hi} תחת קוד המדינה {main_mcc}: "
                     f"{n_used:,} מופיעים ברשימה")
        grid_lede += (f", ואילו {_join_he(gaps)} לא מופיעים בה." if len(gaps) > 1
                      else (f", ואילו {gaps[0]} לא מופיע בה." if gaps else "."))
    else:
        grid_lede = ""

    temporal = None
    if len(mccs) == 1:
        summary = (f"איתור המפעיל לפי קוד רשת סלולרית PLMN בישראל (MCC {main_mcc} ו-MNC): "
                   f"טבלה מלאה של {_codes_he(n_codes)} ו-{_ops_he(n_ops)}.")
    else:
        summary = (f"איתור המפעיל לפי קוד רשת סלולרית PLMN בישראל (MCC ו-MNC): "
                   f"טבלה מלאה של {_codes_he(n_codes)} ו-{_ops_he(n_ops)}.")

    agent_data = {
        "summary_he": summary,
        "dataset_kind": "registry",
        "suggested_tags": ["קודי רשת", "PLMN", "תקשורת סלולרית", "מפעילי סלולר",
                           "מספור טלפוניה"],
        "related_ids": [
            "df60d73b-aa60-46dc-bb76-f183d6bf055c",
            "59d2e891-d1d4-44bc-a54f-24762848ab13",
            "a6c90661-7a18-4773-9553-7d26b4db4cb1",
        ],
        "spatial_coverage": "ישראל",
    }
    if temporal:
        agent_data["temporal_coverage"] = temporal

    return {
        "agent_data": agent_data,
        "kpis": kpis,
        "kpi_order": kpi_order,
        "charts": {
            "by_op": {"names": ch_names, "full": ch_full, "values": ch_vals,
                      "codes": ch_codes},
        },
        "grid": grid,
        "tables": {"codes": rows, "by_op": by_op_table},
        "insights": insights,
        "labels": {
            "kpi_mcc": mcc_label,
            "kpi_codes": "קודי רשת (PLMN) ברשימה",
            "kpi_operators": "מפעילים ברשימה",
            "kpi_multi": "מפעילים עם יותר מקוד אחד",
            "kpi_gaps": f"מספרים בטווח {lo}-{hi} שאינם ברשימה" if lo else "מספרים חסרים בטווח",
            "lookup_title": f"איזה מפעיל מחזיק בקוד {main_mcc}-XX? איתור לפי קוד MNC או שם מפעיל ←"
            if len(mccs) == 1 else "איתור מפעיל לפי קוד MCC/MNC או שם מפעיל ←",
            "codes_lede": (f"{'הקוד' if n_codes == 1 else f'כל {n_codes:,} הקודים'} ברשימה, ממוינים לפי קוד הרשת. "
                           "השם הרשמי של המפעיל מופיע כפי שנרשם במאגר; לצדו השם המוכר בעברית, כשיש."),
            "codes_caption": f"טבלת קודי PLMN בישראל: {_codes_he(n_codes)}, קוד מדינה, קוד רשת ומפעיל.",
            "ops_lede": lede_ops,
            "ops_aria": aria_ops,
            "grid_lede": grid_lede,
            "grid_aria": (f"מפת קודי הרשת {lo}-{hi}: {len(gaps):,} מספרים אינם ברשימה." if len(gaps) > 1
                          else f"מפת קודי הרשת {lo}-{hi}: מספר אחד אינו ברשימה.") if gaps
            else f"מפת קודי הרשת {lo}-{hi}: כל המספרים בטווח מופיעים ברשימה.",
        },
        "flags": {
            "has_grid": bool(grid),
            "has_chart": len(ch_vals) >= 2,
        },
    }
