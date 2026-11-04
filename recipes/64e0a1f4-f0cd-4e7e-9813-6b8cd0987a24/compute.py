"""אתרי כרייה וחציבה בישראל: the Ministry of Energy's list of quarries and
mines holding a valid licence under the Mines Ordinance (one row per site).

Columns: site number, site name, operating company, ITM northing ("(אורך) Y")
and easting ("(רוחב) X"; the column labels swap the Hebrew words, the values
are northing/easting), rock type and Ministry of Interior district.

Rock types can be compound ("גיר ודולומיט"); the mineral view splits them into
components. Company names are normalised (quote styles, spaces) so one
operator written two ways counts once. Everything is a count over the current
snapshot: the file is a full list, not a time series.
"""
import re

import pandas as pd
from govlib import fmt, frame

COL_NO = "מס' מחצבה"
COL_NAME = "שם מחצבה"
COL_CO = "חברה"
COL_Y = "(אורך) Y"
COL_X = "(רוחב) X"
COL_ROCK = "מסלע"
COL_DIST = "מחוז משרד הפנים"

UNKNOWN = "לא צוין"
TOP_ROCKS = 9          # rock-type bars before "אחר"
TOP_COMPANIES = 12     # operator bars before "אחר"
STACK_ROCKS = 6        # rock groups in the district × rock stack
STACK_DISTRICTS = 6    # district groups in the company × district stack
LEAD_SHARE = 0.30      # a district/rock "leads" only above this share
LEAD_MARGIN = 1.25     # ... and at least this many times the runner-up
TOP_CO_MIN = 3         # an operator insight needs at least this many sites
EXCLUSIVE_MIN = 2      # a rock confined to one district needs ≥ this many sites
ITM_X = (100_000, 300_000)
ITM_Y = (350_000, 820_000)

_COMPONENT_SPLIT = re.compile(r"\s*[,/]\s*|\s+ו(?=\S)")


def _company(s: str) -> str:
    s = frame.clean(s).replace("''", '"').replace("״", '"')
    s = re.sub(r'\s*\(\s*', " (", s)
    s = re.sub(r'\s*\)\s*', ") ", s).strip()
    return re.sub(r"\s+", " ", s)


def _components(rock: str) -> list:
    if rock == UNKNOWN:
        return [UNKNOWN]
    parts = [frame.clean(p) for p in _COMPONENT_SPLIT.split(rock)]
    return sorted({p for p in parts if p})


def _prepare(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame({
        "no": frame.clean_series(df[COL_NO]),
        "name": frame.clean_series(df[COL_NAME]),
        "company": df[COL_CO].map(_company),
        "rock": frame.clean_series(df[COL_ROCK]),
        "district": frame.clean_series(df[COL_DIST]),
        "x": frame.num(df[COL_X]),
        "y": frame.num(df[COL_Y]),
    })
    out = out[(out["name"] != "") | (out["no"] != "")].copy()
    for c in ("company", "rock", "district"):
        out.loc[out[c] == "", c] = UNKNOWN
    ok = out["x"].between(*ITM_X) & out["y"].between(*ITM_Y)
    out["mapped"] = ok
    out["no_num"] = pd.to_numeric(out["no"], errors="coerce")
    return out.sort_values(["no_num", "no", "name", "company"], kind="stable",
                           na_position="last").reset_index(drop=True)


def _kpi(value, display, tone="brand"):
    return {"value": value, "display": display, "tone": tone}


def _rank_rows(counts: pd.Series, total: int, n: int):
    labels, values = frame.top_other(counts, n)
    rows = [[lab, fmt.int_he(v), fmt.pct(v / total)] for lab, v in zip(labels, values)]
    return {"names": labels, "values": values}, rows


def _stack(df, row_col, row_order, grp_col, grp_counts, n_groups):
    labels, _ = frame.top_other(grp_counts, n_groups)
    named = set(labels) - {frame.OTHER}
    grp = df[grp_col].where(df[grp_col].isin(named), frame.OTHER)
    ct = pd.crosstab(df[row_col], grp)
    ct = ct.reindex(index=row_order, columns=labels, fill_value=0)
    series = [{"name": g, "data": [int(v) for v in ct[g].tolist()]} for g in labels]
    rows = [[r] + [str(int(v)) for v in ct.loc[r].tolist()] + [str(int(ct.loc[r].sum()))]
            for r in row_order]
    return {"names": list(row_order), "series": series}, {"cols": labels, "rows": rows}


# ---------------------------------------------------------------- insights

def _lead_sentence(counts, total, noun_he, what_he):
    if len(counts) < 2:
        return None
    top, second = counts.index[0], counts.index[1]
    v, v2 = int(counts.iloc[0]), int(counts.iloc[1])
    if top == UNKNOWN or second == UNKNOWN or v / total < LEAD_SHARE or v < v2 * LEAD_MARGIN:
        return None
    return (f"{noun_he} {top} מרכז {fmt.int_he(v)} מתוך {fmt.int_he(total)} {what_he} "
            f"({fmt.pct(v / total, 0)}), לעומת {fmt.int_he(v2)} ב{noun_he} {second}, השני בגודלו.")


def _ins_district(dist_counts, total):
    return _lead_sentence(dist_counts, total, "מחוז", "האתרים המורשים")


def _ins_component(comp_counts, total):
    if comp_counts.empty:
        return None
    top = comp_counts.index[0]
    v = int(comp_counts.iloc[0])
    if top == UNKNOWN or v / total < LEAD_SHARE:
        return None
    second = ""
    if len(comp_counts) > 1 and comp_counts.index[1] != UNKNOWN:
        second = (f" אחריו {comp_counts.index[1]}, "
                  f"ב-{fmt.int_he(int(comp_counts.iloc[1]))} אתרים.")
    return (f"{top} הוא חומר הגלם הנפוץ ביותר: הוא מופיע במסלע של "
            f"{fmt.int_he(v)} מתוך {fmt.int_he(total)} אתרים ({fmt.pct(v / total, 0)}), "
            f"לבד או בשילוב עם חומר אחר.{second}")


def _ins_operator(co_counts, total):
    if co_counts.empty or co_counts.index[0] == UNKNOWN:
        return None
    v = int(co_counts.iloc[0])
    if v < TOP_CO_MIN or (len(co_counts) > 1 and v == int(co_counts.iloc[1])):
        return None
    head = (f"החברה המפעילה הגדולה היא {co_counts.index[0]}, עם {fmt.int_he(v)} אתרים "
            f"({fmt.pct(v / total, 0)} מכלל האתרים).")
    if len(co_counts) < 2:
        return head
    v2 = int(co_counts.iloc[1])
    tied = int((co_counts.iloc[1:] == v2).sum())
    if tied > 1:
        return (f"{head} אחריה {fmt.int_he(tied)} חברות עם {fmt.int_he(v2)} "
                f"אתרים כל אחת.")
    return f"{head} אחריה {co_counts.index[1]}, עם {fmt.int_he(v2)} אתרים."


def _ins_exclusive(df):
    out = []
    for rock, g in df.groupby("rock", sort=True):
        if rock == UNKNOWN or len(g) < EXCLUSIVE_MIN:
            continue
        dists = g["district"].unique()
        if len(dists) == 1 and dists[0] != UNKNOWN:
            out.append((-len(g), rock, dists[0], len(g)))
    if not out:
        return None
    out.sort()
    parts = [f"{r} ({fmt.int_he(n)} אתרים, {'שניהם' if n == 2 else 'כולם'} במחוז {d})"
             for _, r, d, n in out[:3]]
    lead = "חומר גלם שנחצב רק במחוז אחד" if len(parts) == 1 else "חומרי גלם שנחצבים רק במחוז אחד"
    return f"{lead}: {fmt.join_he(parts)}."


def _ins_span(df):
    m = df[df["mapped"]]
    if len(m) < 2:
        return None
    m = m.sort_values(["y", "no", "name"], kind="stable")
    s, n = m.iloc[0], m.iloc[-1]
    km = (n["y"] - s["y"]) / 1000
    if km < 50:
        return None
    return (f"האתרים פרוסים לאורך כ-{fmt.int_he(km)} ק\"מ מצפון לדרום: הצפוני ביותר הוא "
            f"{n['name']}, במחוז {n['district']}, והדרומי ביותר הוא {s['name']}, "
            f"במחוז {s['district']}, שבו נחצב {s['rock']}.")


def _ins_footprint(df, n_companies):
    known = df[df["company"] != UNKNOWN]
    if n_companies < 3:
        return None
    per = known.groupby("company")["district"].nunique().sort_index()
    widest = per.sort_values(ascending=False, kind="stable")
    singles = int((known.groupby("company").size() == 1).sum())
    multi = int((per >= 2).sum())
    if multi == 0:
        head = "כל חברה פועלת במחוז אחד בלבד. "
    elif len(widest) > 1 and int(widest.iloc[0]) > int(widest.iloc[1]):
        head = (f"{fmt.int_he(multi)} חברות פועלות ביותר ממחוז אחד, ו{widest.index[0]} "
                f"פרוסה על פני {fmt.int_he(int(widest.iloc[0]))} מחוזות. ")
    else:
        head = f"{fmt.int_he(multi)} חברות פועלות ביותר ממחוז אחד. "
    return (f"{head}{fmt.int_he(singles)} מתוך {fmt.int_he(n_companies)} "
            f"החברות מפעילות אתר יחיד.")


def compute(frames: dict) -> dict:
    df = _prepare(frames["sites"])
    total = len(df)
    if total == 0:
        raise ValueError("no sites")

    dist_counts = frame.ranked(df["district"])
    rock_counts = frame.ranked(df["rock"])
    co_counts = frame.ranked(df["company"])
    comp_series = df["rock"].map(_components).explode()
    comp_counts = frame.ranked(comp_series)
    n_companies = int((co_counts.index != UNKNOWN).sum())
    n_rocks = int((rock_counts.index != UNKNOWN).sum())
    n_comps = int((comp_counts.index != UNKNOWN).sum())
    n_dist = int((dist_counts.index != UNKNOWN).sum())
    n_mapped = int(df["mapped"].sum())

    dist_chart, dist_rows = _rank_rows(dist_counts, total, 10)
    rock_chart, rock_rows = _rank_rows(rock_counts, total, TOP_ROCKS)
    comp_chart, comp_rows = _rank_rows(comp_counts, total, TOP_ROCKS)
    co_labels, co_values = frame.top_other(co_counts, TOP_COMPANIES)
    co_rows = [[lab, fmt.int_he(v), fmt.pct(v / total)] for lab, v in zip(co_labels, co_values)]

    dist_order = list(dist_counts.index)
    dr_chart, dr_table = _stack(df, "district", dist_order, "rock", rock_counts, STACK_ROCKS)

    co_named = [c for c in co_counts.index[:TOP_COMPANIES]]
    co_df = df[df["company"].isin(co_named)]
    cd_chart, cd_table = _stack(co_df, "company", co_named, "district", dist_counts, STACK_DISTRICTS)

    insights = []
    for iid, text in [
        ("district", _ins_district(dist_counts, total)),
        ("component", _ins_component(comp_counts, total)),
        ("operator", _ins_operator(co_counts, total)),
        ("exclusive", _ins_exclusive(df)),
        ("span", _ins_span(df)),
        ("footprint", _ins_footprint(df, n_companies)),
    ]:
        if text:
            insights.append({"id": iid, "text_he": text})

    top_d = dist_counts.index[0]
    top_c = co_counts.index[0]

    def _strict(counts):
        """The leader, if it is a real value strictly ahead of the runner-up."""
        if counts.index[0] == UNKNOWN:
            return None
        if len(counts) > 1 and int(counts.iloc[0]) == int(counts.iloc[1]):
            return None
        return counts.index[0]

    lead_d, lead_comp = _strict(dist_counts), _strict(comp_counts)
    lede = (f"רשימת אתרי הכרייה והחציבה בישראל שיש להם רישיון בתוקף מטעם המפקח על המכרות "
            f"במשרד האנרגיה והתשתיות: {fmt.int_he(total)} מחצבות ומכרות, שמפעילות "
            f"{fmt.int_he(n_companies)} חברות ב-{fmt.int_he(n_dist)} מחוזות. "
            f"לכל אתר רשומים שם, חברה מפעילה, סוג המסלע ומיקום."
            + (f" החלק הגדול ביותר במחוז {lead_d} ({fmt.int_he(int(dist_counts.iloc[0]))} אתרים)."
               if lead_d else "")
            + (f" חומר הגלם הנפוץ הוא {lead_comp}." if lead_comp else ""))
    summary = (f"{fmt.int_he(total)} אתרי כרייה וחציבה מורשים בישראל, שמפעילות "
               f"{fmt.int_he(n_companies)} חברות: מיקום, חברה מפעילה וסוג מסלע."
               + (f" מחוז {lead_d} מוביל עם {fmt.int_he(int(dist_counts.iloc[0]))} אתרים."
                  if lead_d else ""))
    seo_desc = (f"מפת {fmt.int_he(total)} המחצבות והמכרות בעלי רישיון בתוקף בישראל: "
                f"איתור לפי שם מחצבה, חברה מפעילה או סוג מסלע. "
                f"המפעילה הגדולה: {top_c}.")
    if len(seo_desc) > 150:
        seo_desc = (f"מפת {fmt.int_he(total)} המחצבות והמכרות בעלי רישיון בתוקף בישראל: "
                    f"איתור לפי שם מחצבה, חברה מפעילה או סוג מסלע.")

    dist_top_rock = []
    for d in dist_order[:4]:
        rc = frame.ranked(df.loc[df["district"] == d, "rock"])
        dist_top_rock.append(f"{d}: {rc.index[0]}")
    dr_lede = ("אילו סוגי מסלע נחצבים בכל מחוז. הנפוץ בכל אחד מהמחוזות הגדולים: "
               + "; ".join(dist_top_rock) + ".")

    unmapped = total - n_mapped
    map_note = ("כל אתר מסומן לפי נקודת הציון שלו. לחיצה על נקודה מציגה את שם האתר, "
                "החברה המפעילה וסוג המסלע.")
    if unmapped:
        map_note += f" {fmt.int_he(unmapped)} אתרים בלי נקודת ציון תקינה אינם מופיעים במפה."

    labels = {
        "lede": lede,
        "map_note": map_note,
        "dist_lede": (f"מספר האתרים בכל מחוז של משרד הפנים. מחוז {top_d} מרכז "
                      f"{fmt.pct(int(dist_counts.iloc[0]) / total, 0)} מהאתרים."),
        "rock_lede": (f"סוג המסלע כפי שהוא רשום לכל אתר ({fmt.int_he(n_rocks)} סוגים). "
                      f"הנפוץ: {rock_counts.index[0]}, "
                      f"ב-{fmt.int_he(int(rock_counts.iloc[0]))} אתרים."),
        "comp_lede": (f"פירוק המסלע המשולב (למשל גיר ודולומיט) לרכיביו: בכמה אתרים מופיע "
                      f"כל חומר גלם ({fmt.int_he(n_comps)} חומרים). אתר עם שני חומרים "
                      f"נספר בשניהם, ולכן הסכום גדול ממספר האתרים."),
        "dr_lede": dr_lede,
        "co_lede": (f"החברות לפי מספר האתרים שהן מפעילות, בחלוקה למחוזות. "
                    f"{top_c} מפעילה {fmt.int_he(int(co_counts.iloc[0]))} אתרים."),
        "dist_aria": f"תרשים עמודות: מספר אתרי הכרייה והחציבה בכל מחוז, {fmt.int_he(n_dist)} מחוזות",
        "rock_aria": f"תרשים עמודות: מספר האתרים לפי סוג המסלע, {fmt.int_he(n_rocks)} סוגים",
        "comp_aria": f"תרשים עמודות: מספר האתרים שבהם מופיע כל חומר גלם, {fmt.int_he(n_comps)} חומרים",
        "dr_aria": "תרשים עמודות מוערמות: סוגי המסלע בכל מחוז",
        "co_aria": (f"תרשים עמודות מוערמות: {fmt.int_he(len(co_named))} החברות המפעילות "
                    f"הגדולות לפי מספר אתרים ומחוז"),
        "co_caption": "החברות המפעילות לפי מספר אתרים",
        "cd_caption": "אתרי החברות המפעילות לפי מחוז",
        "dr_caption": "סוגי המסלע בכל מחוז",
        "map_aria": f"מפת {fmt.int_he(n_mapped)} אתרי הכרייה והחציבה המורשים",
    }

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "map",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "אתרי כרייה וחציבה בישראל: מפת המחצבות המורשות",
                "description": seo_desc,
                "name": "אתרי כרייה וחציבה בישראל",
                "alternate_names": [
                    "מחצבות בישראל",
                    "רשימת המחצבות הפעילות",
                    "מכרות ומחצבות מורשים",
                    "אתרי חציבה וכרייה מורשים לפי פקודת המכרות",
                ],
            },
        },
        "kpis": {
            "sites": _kpi(total, fmt.int_he(total)),
            "companies": _kpi(n_companies, fmt.int_he(n_companies)),
            "rocks": _kpi(n_comps, fmt.int_he(n_comps), "info"),
            "top_share": _kpi(round(int(dist_counts.iloc[0]) / total, 4),
                              fmt.pct(int(dist_counts.iloc[0]) / total, 0)),
        },
        "kpi_labels": {
            "top_share": f"מהאתרים במחוז {top_d}",
        },
        "charts": {
            "districts": dist_chart,
            "rocks": rock_chart,
            "components": comp_chart,
            "dist_rock": dr_chart,
            "co_dist": cd_chart,
        },
        "tables": {
            "districts": dist_rows,
            "rocks": rock_rows,
            "components": comp_rows,
            "companies": co_rows,
            "dist_rock": dr_table,
            "co_dist": cd_table,
        },
        "insights": insights,
        "labels": labels,
    }
