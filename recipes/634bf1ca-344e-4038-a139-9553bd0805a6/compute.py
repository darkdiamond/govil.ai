"""רשימת משרדי חקירות: the Justice Ministry's register of licensed private
investigators (licence number, first name, surname).

The table is thin (three columns), so the page aggregates what it carries:
licence-number series and numbering blocks, the most common surnames and first
names, and how names are built (compound first names, double surnames). No
individual licence number is ever printed; numbers appear only as block counts.
Every rule returns a sentence or None when its premise does not hold.
"""
import re

import pandas as pd

TOP_N = 12           # top surnames / first names on the bar charts
MAX_BLOCKS = 20      # numbering blocks shown; coarser blocks when exceeded
LEAD_MIN = 3         # a "most common name" needs at least this many holders


def _int(n):
    return f"{int(n):,}"


def _pct(x, digits=1):
    return f"{x * 100:.{digits}f}%"


def _norm(s):
    s = str(s).replace("׳", "'").replace("’", "'").replace("`", "'")
    s = s.replace("״", '"')
    s = re.sub(r"\s*-\s*", "-", s)
    return re.sub(r"\s+", " ", s).strip()


def _prepare(df):
    df = df.copy()
    df["lic"] = df["מספר רישיון"].astype(str).str.replace(r"\D", "", regex=True)
    df["first"] = df["שם פרטי"].map(_norm)
    df["last"] = df["שם משפחה"].map(_norm)
    return df


def _counts(series):
    """Value counts with a total, deterministic order: count desc, then name."""
    s = series[series != ""]
    vc = s.value_counts()
    return vc.sort_index().sort_values(ascending=False, kind="stable")


def _blocks(lic):
    """Numbering blocks: a licence's digits minus the last 4 (coarsened if many).

    Returns (DataFrame[len, prefix, label, count], series table, divisor).
    """
    lic = lic[lic != ""].str.lstrip("0")
    lic = lic[lic != ""]
    if lic.empty:
        return pd.DataFrame(columns=["len", "prefix", "label", "count"]), 4
    lens = lic.str.len()
    tail = 4
    while True:
        rows = []
        for ln in sorted(lens.unique()):
            sub = lic[lens == ln]
            keep = max(ln - tail, 1)
            pre = sub.str[:keep]
            for p, c in pre.value_counts().sort_index().items():
                rows.append({"len": int(ln), "prefix": p,
                             "label": p + "x" * (int(ln) - keep), "count": int(c)})
        if len(rows) <= MAX_BLOCKS or tail >= 8:
            break
        tail += 1
    out = pd.DataFrame(rows).sort_values(["len", "prefix"], kind="stable").reset_index(drop=True)
    return out, tail


def _names_he(names):
    names = list(names)
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " ו" + names[-1]


def insight_series(series_tbl, total_valid):
    if series_tbl.empty or total_valid == 0:
        return None
    if len(series_tbl) == 1:
        ln = int(series_tbl.index[0])
        return f"כל {_int(total_valid)} מספרי הרישיון במאגר הם בני {ln} ספרות."
    parts = [f"{_int(c)} בני {int(ln)} ספרות ({_pct(c / total_valid)})"
             for ln, c in series_tbl.items()]
    return (f"מספרי הרישיון שייכים ל-{len(series_tbl)} סדרות מספור באורך שונה: "
            + ", ".join(parts) + ".")


def insight_top_name(vc, kind_he, kind_pl, total):
    if vc.empty or vc.iloc[0] < LEAD_MIN:
        return None
    top = int(vc.iloc[0])
    tied = [n for n, c in vc.items() if c == top]
    if len(tied) > 3:
        return None
    rest = vc[vc < top]
    if len(tied) == 1:
        s = f"{kind_he} הנפוץ ביותר ברשימה הוא {tied[0]} ({_int(top)} בעלי רישיון, {_pct(top / total)})"
    else:
        s = f"{kind_pl} הנפוצים ביותר ברשימה הם {_names_he(tied)}, {_int(top)} בעלי רישיון כל אחד"
    if not rest.empty and rest.iloc[0] >= 2:
        r = int(rest.iloc[0])
        r_names = [n for n, c in rest.items() if c == r]
        if len(r_names) <= 3:
            after = "ואחריו" if len(tied) == 1 else "ואחריהם"
            each = "" if len(r_names) == 1 else " כל אחד"
            s += f", {after} {_names_he(r_names)} ({_int(r)}{each})"
    return s + "."


def insight_diversity(vc_last, total):
    if vc_last.empty or total < 20:
        return None
    distinct = int(vc_last.size)
    single = int((vc_last == 1).sum())
    s = (f"ברשימה {_int(distinct)} שמות משפחה שונים ל-{_int(total)} בעלי רישיון; "
         f"{_int(single)} מהם ({_pct(single / distinct)}) מופיעים פעם אחת בלבד")
    if single / distinct >= 0.7:
        s += ", כך שאין ריכוז משפחתי ניכר בענף"
    return s + "."


def insight_compound(n_compound_first, n_double_last, total):
    if total == 0:
        return None
    share_f = n_compound_first / total
    if share_f < 0.05:
        return None
    s = f"ל-{_int(n_compound_first)} בעלי רישיון ({_pct(share_f)}) יש שם פרטי כפול"
    if n_double_last >= 3:
        s += f", ול-{_int(n_double_last)} ({_pct(n_double_last / total)}) שם משפחה כפול או מחובר במקף"
    return s + "."


def insight_block(blocks, total_valid):
    if len(blocks) < 3 or total_valid == 0:
        return None
    b = blocks.sort_values(["count", "len", "prefix"], ascending=[False, True, True],
                           kind="stable").iloc[0]
    share = b["count"] / total_valid
    avg = total_valid / len(blocks)
    if b["count"] < 1.5 * avg:
        return None
    return (f"גוש המספור הגדול ביותר הוא {b['label']}, עם {_int(b['count'])} רישיונות "
            f"({_pct(share)} מהרישיונות), פי {b['count'] / avg:.1f} מהממוצע לגוש "
            f"({len(blocks)} גושים).")


def compute(frames):
    df = _prepare(frames["investigators"])
    total = int(len(df))

    valid_lic = df.loc[df["lic"] != "", "lic"].drop_duplicates()
    total_valid = int(valid_lic.size)
    no_lic = int((df["lic"] == "").sum())
    blocks, tail = _blocks(valid_lic)
    series_tbl = (blocks.groupby("len")["count"].sum().sort_index()
                  if not blocks.empty else pd.Series(dtype=int))

    vc_last = _counts(df["last"])
    vc_first = _counts(df["first"])

    first_words = df["first"].str.split(" ").str.len().where(df["first"] != "", 0)
    n_compound_first = int((first_words >= 2).sum())
    double_last = (df["last"].str.contains(" ", regex=False)
                   | df["last"].str.contains("-", regex=False)) & (df["last"] != "")
    n_double_last = int(double_last.sum())
    n_hyphen_last = int(df["last"].str.contains("-", regex=False).sum())
    n_space_last = n_double_last - n_hyphen_last

    # --- surname frequency distribution -----------------------------------
    freq_buckets = []
    for k in (1, 2, 3, 4):
        names = int((vc_last == k).sum())
        freq_buckets.append({"name": str(k), "names": names, "people": names * k})
    big = vc_last[vc_last >= 5]
    if not big.empty:
        freq_buckets.append({"name": "5+", "names": int(big.size), "people": int(big.sum())})
    freq_buckets = [b for b in freq_buckets if b["names"] > 0]

    top_last = vc_last[vc_last >= 2].head(TOP_N)
    top_first = vc_first[vc_first >= 2].head(TOP_N)

    rules = [
        ("series", insight_series(series_tbl, total_valid)),
        ("top_surname", insight_top_name(vc_last, "שם המשפחה", "שמות המשפחה", total)),
        ("top_first", insight_top_name(vc_first, "השם הפרטי", "השמות הפרטיים", total)),
        ("diversity", insight_diversity(vc_last, total)),
        ("compound", insight_compound(n_compound_first, n_double_last, total)),
        ("block", insight_block(blocks, total_valid)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    distinct_last = int(vc_last.size)
    distinct_first = int(vc_first.size)

    # Largest block KPI
    if not blocks.empty:
        lb = blocks.sort_values(["count", "len", "prefix"], ascending=[False, True, True],
                                kind="stable").iloc[0]
        largest_label, largest_count = str(lb["label"]), int(lb["count"])
    else:
        largest_label, largest_count = "", 0

    summary = (f"איתור חוקר פרטי או משרד חקירות מורשה לפי שם או מספר רישיון: "
               f"{_int(total)} בעלי רישיון ברשימת משרד המשפטים, "
               f"{_int(distinct_last)} שמות משפחה שונים.")

    series_names = [f"{int(ln)} ספרות" for ln in series_tbl.index]
    lede = (f"רשימת בעלי רישיון לחוקר פרטי (משרד חקירות) שמפרסם משרד המשפטים: "
            f"{_int(total)} רשומות, כל אחת עם מספר רישיון, שם פרטי ושם משפחה. "
            f"העמוד מסכם את מבנה המספור ואת השמות הנפוצים; לבדיקה אם חוקר מסוים "
            f"מחזיק ברישיון יש לחפש את שמו או את מספר הרישיון בטבלה שבתחתית העמוד.")

    blocks_note = (f"כל גוש מאגד מספרי רישיון בעלי אותה תחילית (הספרות {tail} האחרונות "
                   f"מוחלפות ב-x). הגושים מסודרים לפי אורך המספר ואז לפי התחילית.")
    if no_lic:
        blocks_note += f" {_int(no_lic)} רשומות ללא מספר רישיון אינן נכללות."

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "registry",
            "suggested_tags": ["חוקרים פרטיים", "משרדי חקירות", "רישוי", "משרד המשפטים"],
            "related_ids": [
                "669b2652-f75b-4de3-8e6b-0dfa17accef5",
                "1806c96c-9cc4-47bf-98b3-80a18f061f98",
                "176f2727-476e-440e-bc8d-5d3461ea0e76",
            ],
            "spatial_coverage": "ישראל",
        },
        "kpis": {
            "total": {"value": total, "display": _int(total), "tone": "brand"},
            "surnames": {"value": distinct_last, "display": _int(distinct_last), "tone": "brand"},
            "compound": {"value": n_compound_first,
                         "display": _pct(n_compound_first / total) if total else "0%",
                         "tone": "info"},
            "largest_block": {"value": largest_count, "display": _int(largest_count),
                              "tone": "info"},
        },
        "charts": {
            "series": {"names": series_names, "values": [int(v) for v in series_tbl.values]},
            "blocks": {"names": blocks["label"].tolist(),
                       "values": [int(v) for v in blocks["count"]],
                       "series": [f"{int(v)} ספרות" for v in blocks["len"]]},
            "surnames": {"names": list(top_last.index), "values": [int(v) for v in top_last]},
            "firsts": {"names": list(top_first.index), "values": [int(v) for v in top_first]},
            "structure": {
                "names": ["שם פרטי כפול", "שם משפחה מחובר במקף", "שם משפחה בן שתי מילים"],
                "values": [n_compound_first, n_hyphen_last, n_space_last],
            },
            "freq": {"names": [b["name"] for b in freq_buckets],
                     "names_count": [b["names"] for b in freq_buckets],
                     "people": [b["people"] for b in freq_buckets]},
        },
        "tables": {
            "series": [{"name": n, "count": _int(v), "share": _pct(v / total_valid) if total_valid else ""}
                       for n, v in zip(series_names, series_tbl.values)],
            "blocks": [{"name": r["label"], "count": _int(r["count"])} for _, r in blocks.iterrows()],
            "surnames": [{"name": n, "count": _int(v)} for n, v in top_last.items()],
            "firsts": [{"name": n, "count": _int(v)} for n, v in top_first.items()],
            "structure": [
                {"name": "שם פרטי כפול", "count": _int(n_compound_first),
                 "share": _pct(n_compound_first / total) if total else ""},
                {"name": "שם משפחה מחובר במקף", "count": _int(n_hyphen_last),
                 "share": _pct(n_hyphen_last / total) if total else ""},
                {"name": "שם משפחה בן שתי מילים", "count": _int(n_space_last),
                 "share": _pct(n_space_last / total) if total else ""},
            ],
            "freq": [{"name": b["name"], "names": _int(b["names"]), "people": _int(b["people"])}
                     for b in freq_buckets],
        },
        "insights": insights,
        "labels": {
            "lede": lede,
            "compound_kpi": "בעלי שם פרטי כפול",
            "largest_block_kpi": f"רישיונות בגוש המספור הגדול ({largest_label})",
            "series_note": (f"{len(series_tbl)} סדרות מספור, לפי מספר הספרות במספר הרישיון "
                            f"({_int(total_valid)} מספרים שונים)."),
            "series_aria": ("תרשים טבעת: מספרי הרישיון לפי אורך המספר. "
                            + ", ".join(f"{n}: {_int(v)}" for n, v in zip(series_names, series_tbl.values)) + "."),
            "blocks_note": blocks_note,
            "blocks_aria": (f"תרשים עמודות: מספר הרישיונות ב-{len(blocks)} גושי מספור. "
                            f"הגדול ביותר {largest_label} עם {_int(largest_count)} רישיונות."),
            "surnames_note": (f"{len(top_last)} שמות המשפחה הנפוצים ביותר (שמות שמופיעים פעמיים לפחות), "
                              f"מתוך {_int(distinct_last)} שמות שונים."),
            "surnames_aria": (f"תרשים עמודות אופקי: {len(top_last)} שמות המשפחה הנפוצים בקרב בעלי רישיון חוקר פרטי."
                              + (f" בראש: {top_last.index[0]} ({_int(top_last.iloc[0])})." if len(top_last) else "")),
            "firsts_note": (f"{len(top_first)} השמות הפרטיים הנפוצים ביותר (שמות שמופיעים פעמיים לפחות), "
                            f"מתוך {_int(distinct_first)} שמות שונים."),
            "firsts_aria": (f"תרשים עמודות אופקי: {len(top_first)} השמות הפרטיים הנפוצים בקרב בעלי רישיון חוקר פרטי."
                            + (f" בראש: {top_first.index[0]} ({_int(top_first.iloc[0])})." if len(top_first) else "")),
            "structure_note": f"מספר בעלי הרישיון לפי מבנה השם, מתוך {_int(total)}.",
            "structure_aria": (f"תרשים עמודות: {_int(n_compound_first)} בעלי שם פרטי כפול, "
                               f"{_int(n_hyphen_last)} שמות משפחה במקף, {_int(n_space_last)} שמות משפחה בני שתי מילים."),
            "freq_note": ("כמה שמות משפחה מופיעים פעם אחת, פעמיים וכן הלאה, "
                          "וכמה בעלי רישיון נושאים אותם."),
            "freq_aria": ("תרשים עמודות: שמות משפחה לפי מספר המופעים ברשימה. "
                          + (f"{_int(freq_buckets[0]['names'])} שמות מופיעים פעם אחת." if freq_buckets else "")),
        },
    }
