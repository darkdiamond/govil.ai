"""Courts and labour tribunals registry (הרשות השופטת).

One row per court: name, judicial district (code + name), court type
(code + name) and an HTML link to the court's gov.il page. The page is a
directory: how the courts split by district and type, which towns host
which kinds of court, where a town has a peace court but not the matching
family / youth / traffic court, plus a full linked list grouped by district.

The town of each court is parsed from its name ("<type> - <town>"); the
parse is documented in the page copy as "the location in the court's name".
Every number on the page is computed here.
"""
import re

import pandas as pd

# Short labels for the known court-type codes (court_activity). Unknown
# codes fall back to the dataset's own type name, so new types flow through.
TYPE_SHORT = {
    1: "עליון",
    2: "מחוזי",
    3: "שלום",
    4: "משפחה",
    5: "תעבורה",
    6: "נוער",
    7: "תביעות קטנות",
    8: "עבודה",
}
PEACE = 3
# Types that normally sit next to a peace court in a town; used for the
# "town has a peace court but no X" coverage view.
LOCAL_TYPES = [4, 5, 6, 7]

TOWN_ALIASES = {
    "תל אביב": "תל אביב יפו",
    "תל אביב-יפו": "תל אביב יפו",
}

HREF_RE = re.compile(r"""href\s*=\s*["'](https://www\.gov\.il/[^"'\s<>]+)["']""")


def _int(n):
    return f"{int(n):,}"


def _pct(x):
    return f"{x * 100:.1f}%"


def _clean_space(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def _clean_name(s):
    s = _clean_space(s)
    # One row lost its leading "בי" ("ת המשפט לתביעות קטנות - ...").
    if s.startswith("ת המשפט"):
        s = "בי" + s
    return s


def _town(name):
    parts = re.split(r"\s+-\s+", name)
    if len(parts) < 2:
        return ""
    t = parts[-1]
    if "," in t:
        t = t.split(",")[-1]
    t = re.sub(r"\([^)]*\)", "", t)
    t = t.replace("...", "").replace("…", "")
    t = _clean_space(t)
    t = re.sub(r"^קרית ", "קריית ", t)
    return TOWN_ALIASES.get(t, t)


def _url(s):
    m = HREF_RE.search(str(s or ""))
    return m.group(1) if m else ""


def _short_type(code, name):
    if code in TYPE_SHORT:
        return TYPE_SHORT[code]
    n = re.sub(r"^(בתי|בית)\s+(המשפט|משפט|הדין)\s*", "", name).strip()
    return n or name


def _prepare(df):
    df = df.copy()
    df["name"] = df["court_name"].map(_clean_name)
    df["dcode"] = pd.to_numeric(df["court_district"], errors="coerce")
    df["district"] = df["מחוז"].map(_clean_space)
    df["tcode"] = pd.to_numeric(df["court_activity"], errors="coerce")
    df["tname"] = df["תחום"].map(_clean_space)
    df = df[(df["name"] != "") & (df["district"] != "") & (df["tname"] != "")]
    df = df.dropna(subset=["dcode", "tcode"])
    df["dcode"] = df["dcode"].astype(int)
    df["tcode"] = df["tcode"].astype(int)
    df["town"] = df["name"].map(_town)
    df["url"] = df["court_details"].map(_url)
    df["national"] = df["district"] == "ארצי"
    df = df.drop_duplicates(subset=["name", "district", "tcode"])
    return df.sort_values(["dcode", "tcode", "name"], kind="stable").reset_index(drop=True)


def _orders(df):
    dist = (df.groupby("district")["dcode"].min().reset_index()
            .sort_values(["dcode", "district"], kind="stable"))
    types = (df.groupby("tcode")["tname"].agg(lambda s: sorted(s)[0]).reset_index()
             .sort_values("tcode", kind="stable"))
    types["short"] = [_short_type(c, n) for c, n in zip(types["tcode"], types["tname"])]
    return dist, types


# ---------------------------------------------------------------- insights

def ins_largest(by_dist_local, total_local, dist_towns):
    if len(by_dist_local) < 2 or total_local == 0:
        return None
    top_n, top_v = by_dist_local.index[0], int(by_dist_local.iloc[0])
    low_n, low_v = by_dist_local.index[-1], int(by_dist_local.iloc[-1])
    if top_v == low_v or top_v == int(by_dist_local.iloc[1]):
        return None
    share = top_v / total_local
    return (f"מחוז {top_n} מרכז את מספר בתי המשפט הגדול ביותר: {_int(top_v)} "
            f"({_pct(share)} מבתי המשפט ובתי הדין שבמחוזות, מלבד הארציים), לעומת {_int(low_v)} "
            f"בלבד במחוז {low_n}. בתי המשפט של מחוז {top_n} פזורים ב-{_int(dist_towns.get(top_n, 0))} "
            f"יישובים, לעומת {_int(dist_towns.get(low_n, 0))} במחוז {low_n}.")


def ins_peace_small_claims(town_types):
    peace = {t for t, s in town_types.items() if PEACE in s}
    small = {t for t, s in town_types.items() if 7 in s}
    if len(peace) < 3 or not small:
        return None
    both = peace & small
    if both == peace and both == small:
        return (f"בתי משפט השלום ובתי המשפט לתביעות קטנות פועלים באותם {_int(len(peace))} "
                f"יישובים בדיוק: בכל יישוב שיש בו בית משפט שלום יש גם בית משפט לתביעות קטנות.")
    missing = len(peace - small)
    if missing == 0:
        return None
    return (f"ב-{_int(missing)} מתוך {_int(len(peace))} היישובים שיש בהם בית משפט שלום "
            f"אין בית משפט לתביעות קטנות ברשימה.")


def ins_family_gap(town_types):
    peace = sorted(t for t, s in town_types.items() if PEACE in s)
    if len(peace) < 3:
        return None
    no_fam = [t for t in peace if 4 not in town_types[t]]
    if not no_fam:
        return (f"בכל {_int(len(peace))} היישובים שיש בהם בית משפט שלום פועל גם "
                f"בית משפט לענייני משפחה.")
    share = len(no_fam) / len(peace)
    if share < 0.15:
        return None
    ex = ", ".join(no_fam[:4])
    return (f"ב-{_int(len(no_fam))} מתוך {_int(len(peace))} היישובים שיש בהם בית משפט שלום "
            f"({_pct(share)}) אין בית משפט לענייני משפחה, למשל {ex}.")


def ins_hub(town_rank):
    if town_rank.empty:
        return None
    top = int(town_rank["types"].iloc[0])
    leaders = town_rank[town_rank["types"] == top]["town"].tolist()
    if top < 4 or len(leaders) > 6:
        return None
    names = (", ".join(leaders[:-1]) + " ו" + ("" if "א" <= leaders[-1][:1] <= "ת" else "-")
             + leaders[-1]) if len(leaders) > 1 else leaders[0]
    if len(leaders) == 1:
        return (f"{names} היא מרכז השיפוט המגוון ביותר ברשימה: פועלים בה {_int(top)} "
                f"סוגים שונים של בתי משפט ובתי דין.")
    return (f"היישובים עם המגוון הגדול ביותר של בתי משפט הם {names}: בכל אחד מהם "
            f"פועלים {_int(top)} סוגים שונים של בתי משפט ובתי דין.")


def ins_single(town_rank, town_types):
    n = len(town_rank)
    if n < 5:
        return None
    single = town_rank[town_rank["types"] <= 2]["town"].tolist()
    if not single:
        return None
    share = len(single) / n
    if share < 0.1:
        return None
    basic = [t for t in single if town_types[t] <= {PEACE, 7}]
    text = (f"{_int(len(single))} מתוך {_int(n)} היישובים ({_pct(share)}) מארחים "
            f"סוג אחד או שניים בלבד של בית משפט")
    if len(basic) == len(single):
        return text + ": בכולם מדובר רק בבית משפט שלום ו/או בבית משפט לתביעות קטנות."
    if len(basic) * 2 > len(single):
        return text + f", ו-{_int(len(basic))} מהם מחזיקים רק בית משפט שלום ו/או בית משפט לתביעות קטנות."
    return text + "."


def ins_labour(df, dist):
    lab = df[(df["tcode"] == 8) & (~df["national"])]
    if lab.empty:
        return None
    local_d = [d for d in dist["district"] if d != "ארצי"]
    without = [d for d in local_d if d not in set(lab["district"])]
    reg = len(lab)
    if without:
        names = ", ".join(without)
        return (f"ברשימה {_int(reg)} בתי דין אזוריים לעבודה. ל{'מחוזות' if len(without) > 1 else 'מחוז'} "
                f"{names} אין בית דין אזורי לעבודה משלו ברשימה.")
    return f"בכל אחד מ-{_int(len(local_d))} המחוזות פועל בית דין אזורי לעבודה ({_int(reg)} בסך הכול)."


def ins_youth(town_types):
    peace = [t for t, s in town_types.items() if PEACE in s]
    youth = [t for t, s in town_types.items() if 6 in s]
    if len(peace) < 3 or not youth:
        return None
    ratio = len(youth) / len(peace)
    if ratio < 0.65:
        return None
    return (f"בתי המשפט לנוער פרוסים כמעט כמו בתי משפט השלום: הם פועלים ב-{_int(len(youth))} "
            f"יישובים, לעומת {_int(len(peace))} יישובים עם בית משפט שלום ({_pct(ratio)}).")


# ---------------------------------------------------------------- compute

def compute(frames):
    df = _prepare(frames["main"])
    dist, types = _orders(df)
    total = len(df)
    local = df[~df["national"]]
    d_names = dist["district"].tolist()
    t_codes = types["tcode"].tolist()
    t_short = types["short"].tolist()
    t_full = types["tname"].tolist()

    # district x type matrix
    ct = df.groupby(["district", "tcode"]).size()
    matrix = [[int(ct.get((d, c), 0)) for c in t_codes] for d in d_names]
    dist_tot = [sum(r) for r in matrix]

    by_dist_local = (local.groupby("district").size().sort_index()
                     .sort_values(ascending=False, kind="stable"))
    total_local = int(len(local))

    # towns (local courts only: national courts sit in Jerusalem but serve all)
    lt = local[local["town"] != ""]
    town_types = {}
    town_dist = {}
    for t, grp in lt.groupby("town"):
        town_types[t] = set(int(c) for c in grp["tcode"])
        town_dist[t] = sorted(grp["district"].unique().tolist())[0]
    town_rank = pd.DataFrame({
        "town": list(town_types.keys()),
        "types": [len(s) for s in town_types.values()],
        "courts": [int((lt["town"] == t).sum()) for t in town_types],
    })
    if not town_rank.empty:
        town_rank = town_rank.sort_values(["types", "courts", "town"],
                                          ascending=[False, False, True], kind="stable")
    n_towns = len(town_rank)
    multi = int((town_rank["types"] >= 3).sum()) if n_towns else 0
    dist_towns = {d: int(g["town"].nunique()) for d, g in lt.groupby("district")}

    # by type: courts and distinct towns
    type_courts = [int((df["tcode"] == c).sum()) for c in t_codes]
    type_towns = [int(lt[lt["tcode"] == c]["town"].nunique()) for c in t_codes]

    # breadth histogram: towns by number of court types
    breadth_x, breadth_y = [], []
    if n_towns:
        mx = int(town_rank["types"].max())
        for k in range(1, mx + 1):
            breadth_x.append(str(k))
            breadth_y.append(int((town_rank["types"] == k).sum()))

    # gaps: peace-court towns lacking each local type
    peace_towns = sorted(t for t, s in town_types.items() if PEACE in s)
    gap_rows = []
    for c in LOCAL_TYPES:
        if c not in t_codes or not peace_towns:
            continue
        missing = sorted(t for t in peace_towns if c not in town_types[t])
        gap_rows.append({
            "type": t_short[t_codes.index(c)],
            "have": len(peace_towns) - len(missing),
            "missing": len(missing),
            "share_display": _pct(len(missing) / len(peace_towns)),
            "examples": ", ".join(missing[:6]) + (" ועוד" if len(missing) > 6 else ""),
        })

    # top towns chart
    TOP = 15
    top = town_rank.head(TOP)
    top_series = []
    for c, s in zip(t_codes, t_short):
        top_series.append([int(((lt["town"] == t) & (lt["tcode"] == c)).sum()) for t in top["town"]])

    # town x type matrix table, grouped by district order then name
    d_order = {d: i for i, d in enumerate(d_names)}
    town_table = []
    for t in sorted(town_types, key=lambda x: (d_order.get(town_dist[x], 99), x)):
        town_table.append({
            "town": t,
            "district": town_dist[t],
            "cells": [c in town_types[t] for c in t_codes],
            "n": len(town_types[t]),
        })
    local_code_idx = [i for i, c in enumerate(t_codes) if c not in (1,)]

    # directory grouped by district
    directory = []
    for d in d_names:
        sub = df[df["district"] == d]
        items = [{"name": r.name, "type": _short_type(r.tcode, r.tname), "url": r.url}
                 for r in sub.itertuples()]
        directory.append({"district": d, "n": len(items), "courts": items})
    n_links = int((df["url"] != "").sum())

    # ------------------------------------------------ insights
    rules = [
        ("largest", ins_largest(by_dist_local, total_local, dist_towns)),
        ("hub", ins_hub(town_rank)),
        ("family_gap", ins_family_gap(town_types)),
        ("peace_small", ins_peace_small_claims(town_types)),
        ("labour", ins_labour(df, dist)),
        ("youth", ins_youth(town_types)),
        ("single", ins_single(town_rank, town_types)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    # ------------------------------------------------ KPIs
    top_d = by_dist_local.index[0] if len(by_dist_local) else ""
    top_dv = int(by_dist_local.iloc[0]) if len(by_dist_local) else 0
    top_unique = len(by_dist_local) == 1 or (len(by_dist_local) > 1 and top_dv > int(by_dist_local.iloc[1]))
    kpis = {
        "total": {"value": total, "display": _int(total), "tone": "brand"},
        "types": {"value": len(t_codes), "display": _int(len(t_codes)), "tone": "brand"},
        "towns": {"value": n_towns, "display": _int(n_towns), "tone": "info"},
        "districts": {"value": len(by_dist_local), "display": _int(len(by_dist_local)), "tone": "brand"},
        "top_district": {"value": top_dv, "display": _int(top_dv), "tone": "brand"},
    }
    peace_n = len(peace_towns)

    # ------------------------------------------------ labels
    def dist_line():
        if not len(by_dist_local):
            return ""
        parts = [f"{d} {_int(v)}" for d, v in by_dist_local.items()]
        return "; ".join(parts)

    top_town = town_rank["town"].iloc[0] if n_towns else ""
    top_types = int(town_rank["types"].iloc[0]) if n_towns else 0
    big_type_i = max(range(len(t_codes)), key=lambda i: (type_courts[i], -i)) if t_codes else 0
    big_unique = bool(t_codes) and sum(1 for v in type_courts if v == type_courts[big_type_i]) == 1

    labels = {
        "lede": (f"רשימת {_int(total)} בתי המשפט ובתי הדין לעבודה של הרשות השופטת, "
                 f"לפי {_int(len(by_dist_local))} מחוזות שיפוט ו-{_int(len(t_codes))} תחומי פעילות: "
                 f"מבית המשפט העליון ובתי המשפט המחוזיים ועד בתי משפט השלום, משפחה, נוער, תעבורה, "
                 f"תביעות קטנות ובתי הדין לעבודה. בתי המשפט פועלים ב-{_int(n_towns)} יישובים, "
                 f"ולכל בית משפט מצורף קישור לדף שלו באתר gov.il עם כתובת, שעות קבלת קהל ודרכי פנייה."),
        "kpi_total": "בתי משפט ובתי דין ברשימה",
        "kpi_types": "תחומי פעילות (סוגי בתי משפט)",
        "kpi_towns": "יישובים שבהם פועל בית משפט",
        "kpi_districts": "מחוזות שיפוט (מלבד הארצי)",
        "kpi_top_district": (f"בתי משפט במחוז {top_d}, המחוז הגדול ברשימה" if top_unique
                             else f"בתי משפט במחוז {top_d}, מהמחוזות הגדולים ברשימה"),
        "dt_lede": (f"מספר בתי המשפט בכל מחוז, בחלוקה לפי סוג. {dist_line()}. "
                    f"\"ארצי\" כולל את בית המשפט העליון ואת בית הדין הארצי לעבודה."),
        "dt_aria": (f"גרף עמודות מוערמות: בתי משפט לפי מחוז וסוג. " +
                    (f"המחוז עם הכי הרבה בתי משפט: {top_d} ({_int(top_dv)})." if top_unique else "")),
        "types_lede": (f"לכל סוג בית משפט: כמה בתי משפט יש ברשימה, ובכמה יישובים שונים הם פועלים. " +
                       (f"הסוג הנפוץ ביותר: {t_full[big_type_i]} "
                        f"({_int(type_courts[big_type_i])})." if big_unique else "")),
        "types_aria": (f"גרף עמודות: מספר בתי המשפט ומספר היישובים לכל אחד מ-{_int(len(t_codes))} סוגי בתי המשפט. " +
                       (f"הנפוץ ביותר: {t_full[big_type_i]}." if big_unique else "")),
        "top_lede": (f"היישובים עם המגוון הגדול ביותר של בתי משפט, לפי מספר הסוגים השונים "
                     f"שפועלים בהם ({_int(len(top))} המובילים מתוך {_int(n_towns)}). "
                     f"בראש הרשימה: {top_town}, עם {_int(top_types)} סוגים. "
                     f"היישוב נלקח מהמיקום שבשם בית המשפט; בתי המשפט הארציים אינם נכללים."),
        "top_aria": (f"גרף עמודות מוערמות: {_int(len(top))} היישובים עם הכי הרבה סוגי בתי משפט. "
                     f"בראש: {top_town} עם {_int(top_types)} סוגים."),
        "breadth_lede": (f"כמה סוגים של בתי משפט יש בכל יישוב. ב-{_int(n_towns)} היישובים שבהם פועל בית משפט, "
                         f"ב-{_int(multi)} מהם ({_pct(multi / n_towns) if n_towns else ''}) פועלים שלושה סוגים או יותר."),
        "breadth_aria": (f"גרף עמודות: התפלגות {_int(n_towns)} היישובים לפי מספר סוגי בתי המשפט שפועלים בהם."),
        "gap_lede": (f"מתוך {_int(peace_n)} היישובים שיש בהם בית משפט שלום: בכמה מהם פועל גם בית משפט "
                     f"מכל אחד מהסוגים המקומיים האחרים, ובכמה לא."),
        "gap_aria": (f"גרף עמודות מוערמות: לכל סוג בית משפט מקומי, כמה מתוך {_int(peace_n)} יישובי בית משפט השלום "
                     f"מארחים גם אותו וכמה לא."),
        "town_lede": (f"טבלת {_int(n_towns)} היישובים וסוגי בתי המשפט שפועלים בכל אחד, לפי מחוז. "
                      f"סימן וי מציין שיש ביישוב בית משפט מאותו סוג."),
        "dir_lede": (f"כל {_int(total)} בתי המשפט ובתי הדין, לפי מחוז. "
                     f"ל-{_int(n_links)} מהם מצורף קישור לדף בית המשפט באתר gov.il."),
        "town_caption": "יישובים וסוגי בתי המשפט הפועלים בהם",
        "dt_caption": "בתי משפט לפי מחוז וסוג",
        "types_caption": "בתי משפט ויישובים לפי סוג בית משפט",
        "top_caption": "היישובים עם הכי הרבה סוגי בתי משפט",
        "breadth_caption": "יישובים לפי מספר סוגי בתי המשפט",
        "gap_caption": "יישובי בית משפט שלום לפי קיום בית משפט מכל סוג מקומי",
    }

    # ------------------------------------------------ summary
    summary = (f"איתור בית משפט או בית דין לעבודה לפי מחוז, סוג ויישוב: {_int(total)} בתי משפט "
               f"ב-{_int(n_towns)} יישובים, עם קישור לדף כל בית משפט.")

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "registry",
            "suggested_tags": ["בתי משפט", "מערכת המשפט", "בתי דין לעבודה", "מחוזות שיפוט", "הרשות השופטת"],
            "related_ids": [
                "3c2be3d7-1924-4208-8eef-07e2cfb4b747",
                "7571aa64-9970-44d1-be04-190ba9fc386c",
                "432ee66d-0e62-43f0-b0e6-2ff66e961a02",
                "80189fff-17da-4ee5-994d-be68ce8ce2b1",
                "7137b607-9254-4158-9508-a156101625db",
            ],
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "kpi_order": ["total", "towns", "types", "districts", "top_district"],
        "charts": {
            "dist_type": {"districts": d_names, "types": t_short, "full": t_full,
                          "series": [[matrix[i][j] for i in range(len(d_names))] for j in range(len(t_codes))],
                          "totals": dist_tot},
            "types": {"labels": t_short, "full": t_full, "courts": type_courts, "towns": type_towns},
            "top": {"towns": top["town"].tolist(), "types": t_short, "series": top_series,
                    "n_types": [int(v) for v in top["types"]]},
            "breadth": {"x": breadth_x, "y": breadth_y},
            "gaps": {"labels": [g["type"] for g in gap_rows],
                     "have": [g["have"] for g in gap_rows],
                     "missing": [g["missing"] for g in gap_rows]},
        },
        "tables": {
            "dist_type": [{"district": d, "cells": matrix[i], "total": dist_tot[i]}
                          for i, d in enumerate(d_names)],
            "types": [{"type": t_full[i], "courts": type_courts[i], "towns": type_towns[i]}
                      for i in range(len(t_codes))],
            "top": [{"town": r.town, "types": int(r.types), "courts": int(r.courts)} for r in top.itertuples()],
            "breadth": [{"k": breadth_x[i], "n": breadth_y[i]} for i in range(len(breadth_x))],
            "gaps": gap_rows,
            "towns": town_table,
            "town_types": [t_short[i] for i in local_code_idx],
            "town_idx": local_code_idx,
        },
        "directory": directory,
        "flags": {
            "has_top": n_towns >= 3,
            "has_breadth": len(breadth_x) >= 2,
            "has_gaps": len(gap_rows) >= 1 and peace_n >= 3,
            "has_towns": n_towns >= 3,
        },
        "insights": insights,
        "labels": labels,
    }
