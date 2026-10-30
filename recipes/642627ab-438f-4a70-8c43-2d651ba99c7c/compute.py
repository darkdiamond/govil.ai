"""מרשם אוכלוסין באר שבע: עיריית באר שבע.

Three snapshot tables, one row per statistical area (אג"ס), refreshed in
place every month from the population registry:

- `status`: residents by marital status, single-parent families, and a
  ready-made index ("גרוש-אלמן-משפחות שבראשן עומד הורה") that is
  (divorced + widowed + single-parent families) / residents * 100.
- `olim`: residents, immigrants by origin (Russia, Ethiopia, USA, South
  Africa, other countries), total immigrants and their share. The origin
  columns overlap a little: they sum to slightly more than the total
  immigrant column, so the page shows them as counts per category and
  never as shares of a whole.
- `ages`: residents in 16 age bands. The 6-12 band arrives Excel-mangled as
  "06-דצמ" (6-Dec); the parser maps month-name upper bounds back to numbers
  and accepts a fixed "6-12" header too.

Code 0 is a large block of residents with no statistical area (and no
neighbourhood in the municipality's conversion table); it is shown as its
own row and excluded from neighbourhood rankings, which the text says.

Neighbourhood names come from the municipality's static conversion table
(dataset 947814b2, "טבלת המרה שכונות - אזורים סטטיסטיים"), embedded below;
a code missing from it falls back to "אג״ס <code>" so new areas still flow
through.

Growth: no time dimension, the files are overwritten; new areas and new age
bands flow through. Every per-area ranking requires MIN_POP residents
(disclosed in the ledes).
"""
import re

import pandas as pd

LRI, PDI = "⁦", "⁩"
MIN_POP = 500          # areas / neighbourhoods below this are not ranked on shares
LEAD_RATIO = 1.3       # "well above the city" threshold for share insights
UNASSIGNED = "ללא שיוך לשכונה (קוד 0)"

# Municipality conversion table: statistical area -> neighbourhood key.
AREA_NEIGH = {
    111: "ד", 112: "ד", 113: "ד", 121: "ד", 122: "ד", 123: "ד", 131: "ד", 132: "ד", 133: "ד",
    211: "ו", 212: "ו", 213: "ו", 214: "ו", 215: "ו", 216: "ו",
    221: "יא", 222: "יא", 223: "יא", 224: "יא", 225: "יא", 226: "יא",
    234: "נחל עשן", 311: "נחל עשן", 312: "נחל עשן", 313: "נחל עשן",
    314: "כלניות", 411: "סיגליות",
    412: "נווה זאב", 413: "נווה זאב", 414: "נווה זאב", 415: "נווה זאב",
    421: "נאות לון", 422: "ט", 423: "ט",
    431: "ה", 432: "ה", 433: "ה", 434: "ה",
    511: "ב", 512: "ב", 513: "ב", 521: "א", 522: "א", 523: "א",
    611: "עיר עתיקה", 612: "עיר עתיקה", 613: "נווה נוי", 614: "נחל בקע",
    621: "עמק שרה", 624: "מרכז אזרחי",
    631: "ג", 632: "ג", 633: "ג",
    634: "רמות", 641: "רמות", 642: "רמות", 643: "רמות", 644: "רמות",
    645: "רמות", 646: "רמות", 647: "רמות",
}
NEIGH_NAME = {
    "א": "שכונה א׳", "ב": "שכונה ב׳", "ג": "שכונה ג׳", "ד": "שכונה ד׳",
    "ה": "שכונה ה׳", "ו": "שכונה ו׳", "ט": "שכונה ט׳", "יא": "שכונה י״א",
    "עיר עתיקה": "העיר העתיקה", "מרכז אזרחי": "המרכז האזרחי",
    "עמק שרה": "עמק שרה, קריית יהודית ואזור התעשייה",
}
AREA_NOTE = {642: "קריית ההייטק"}
ARTICLE_NAMES = {"העיר העתיקה", "המרכז האזרחי"}

MONTHS = {"ינו": 1, "פבר": 2, "מרץ": 3, "אפר": 4, "מאי": 5, "יונ": 6,
          "יול": 7, "אוג": 8, "ספט": 9, "אוק": 10, "נוב": 11, "דצמ": 12}

MARITAL = [("נשואים/נשואות", "נשואים"), ("רווקים/רווקות", "רווקים"),
           ("גרושים/גרושות", "גרושים"), ("אלמנים/אלמנות", "אלמנים")]
ORIGINS = [("עולים משאר הארצות", "שאר הארצות"), ("עולים מרוסיה", "רוסיה"),
           ("עולים מאתיופיה", "אתיופיה"), ("עולים מארה''ב", "ארה״ב"),
           ("עולים מדרא''פ", "דרום אפריקה")]
BROAD = [("ילדים 0-17", 0, 17), ("צעירים 18-34", 18, 34),
         ("בני 35-64", 35, 64), ("בני 65 ומעלה", 65, 200)]


def n(v):
    return f"{int(round(v)):,}"


def pct(v, digits=1):
    return f"{LRI}{v * 100:.{digits}f}%{PDI}"


def kpct(v, digits=1):
    return f"{v * 100:.{digits}f}%"


def num(s):
    return pd.to_numeric(s.astype(str).str.replace(",", "", regex=False).str.strip(),
                         errors="coerce")


def area_col(df):
    for c in df.columns:
        if re.sub(r"[\"'״׳]", "", c).strip() == "אגס":
            return c
    raise KeyError("אג״ס")


def find_col(df, name):
    want = re.sub(r"[\"'״׳]", "", name)
    for c in df.columns:
        if re.sub(r"[\"'״׳]", "", c).strip() == want:
            return c
    return None


def parse_band(col):
    c = col.strip()
    m = re.fullmatch(r"0*(\d+)\s*-\s*0*(\d+)", c)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.fullmatch(r"0*(\d+)\s*-\s*(\S+)", c)
    if m and m.group(2)[:3] in MONTHS:
        return int(m.group(1)), MONTHS[m.group(2)[:3]]
    m = re.fullmatch(r"0*(\d+)\s*\+", c)
    if m:
        return int(m.group(1)), 200
    return None


def band_label(lo, hi):
    return f"{lo}+" if hi >= 100 else f"{lo}-{hi}"


def keyed(df):
    df = df.copy()
    df["_code"] = num(df[area_col(df)])
    df = df[df["_code"].notna()].copy()
    df["_code"] = df["_code"].astype(int)
    return df.groupby("_code", sort=True)


def neigh_key(code):
    if code == 0:
        return "__unassigned__"
    return AREA_NEIGH.get(code, f"__area_{code}")


def neigh_name(key):
    if key == "__unassigned__":
        return UNASSIGNED
    if key.startswith("__area_"):
        return f"אג״ס {key[7:]}"
    return NEIGH_NAME.get(key, key)


def area_name(code):
    if code == 0:
        return UNASSIGNED
    key = neigh_key(code)
    if key.startswith("__area_"):
        return "לא מופיע בטבלת ההמרה"
    base = neigh_name(key)
    return f"{base} ({AREA_NOTE[code]})" if code in AREA_NOTE else base


def be(name):
    """"ב" + name, contracting the definite article (במרכז האזרחי)."""
    if name in ARTICLE_NAMES:
        return "ב" + name[1:]
    return "ב" + name


def share(a, b):
    return (a / b) if b else None


def compute(frames):
    st, ol, ag = frames["status"], frames["olim"], frames["ages"]

    # ---- per-area tables -------------------------------------------------
    sg = keyed(st)
    s = pd.DataFrame({"total": sg[find_col(st, "סה״כ")].apply(lambda x: num(x).sum())})
    for col, key in MARITAL:
        s[key] = sg[col].apply(lambda x: num(x).sum())
    s["single_parent"] = sg["משפחות שבראשן עומד הורה עצמאי"].apply(lambda x: num(x).sum())
    s["index_src"] = sg["גרוש-אלמן-משפחות שבראשן עומד הורה"].apply(lambda x: num(x).max())

    og = keyed(ol)
    o = pd.DataFrame({"total_o": og[find_col(ol, "סה״כ")].apply(lambda x: num(x).sum())})
    for col, key in ORIGINS:
        o[key] = og[col].apply(lambda x: num(x).sum())
    o["olim"] = og[find_col(ol, "סה״כ עולים")].apply(lambda x: num(x).sum())
    o["olim_pct_src"] = og["עולים %"].apply(lambda x: num(x).max())

    bands = []
    for c in ag.columns:
        b = parse_band(c)
        if b and c != area_col(ag):
            bands.append((b[0], b[1], c))
    bands.sort()
    # The bands must tile the age range from 0 with no gap: a renamed or
    # dropped band would otherwise vanish from every age figure silently.
    expect = 0
    for lo, hi, c in bands:
        if lo != expect:
            raise ValueError(f"age bands are not contiguous at {lo} (column {c!r})")
        expect = hi + 1
    gg = keyed(ag)
    a = pd.DataFrame(index=sorted(gg.groups.keys()))
    for lo, hi, c in bands:
        a[band_label(lo, hi)] = gg[c].apply(lambda x: num(x).sum())
    a = a.fillna(0)
    band_labels = [band_label(lo, hi) for lo, hi, _ in bands]
    a["age_total"] = a[band_labels].sum(axis=1)
    for name, lo, hi in BROAD:
        cols = [band_label(b0, b1) for b0, b1, _ in bands if b0 >= lo and b0 <= hi]
        a[name] = a[cols].sum(axis=1) if cols else 0

    df = s.join(o, how="outer").join(a, how="outer").sort_index()
    df.index.name = "code"
    df = df.fillna(0)
    df["pop"] = df["total"].where(df["total"] > 0, df["age_total"])
    df["neigh"] = [neigh_key(c) for c in df.index]

    total = float(df["pop"].sum())
    age_total = float(df["age_total"].sum())
    kids_name, young_name, mid_name, old_name = [b[0] for b in BROAD]

    # ---- neighbourhood aggregates ---------------------------------------
    sum_cols = ["pop", "total", "total_o", "age_total", "olim", "single_parent"] + \
        [k for _, k in MARITAL] + [k for _, k in ORIGINS] + [b[0] for b in BROAD]
    ng = df.groupby("neigh", sort=True)[sum_cols].sum()
    ng["areas"] = df.groupby("neigh", sort=True).size()
    rows = []
    for key, r in ng.iterrows():
        rows.append({
            "key": key, "name": neigh_name(key), "pop": float(r["pop"]),
            "areas": int(r["areas"]),
            "kids": share(r[kids_name], r["age_total"]),
            "old": share(r[old_name], r["age_total"]),
            "young": share(r[young_name], r["age_total"]),
            "mid": share(r[mid_name], r["age_total"]),
            "olim": share(r["olim"], r["total_o"]),
            "family": share(r["גרושים"] + r["אלמנים"] + r["single_parent"], r["total"]),
            "unassigned": key == "__unassigned__",
            "counts": {b[0]: float(r[b[0]]) for b in BROAD},
        })
    rows.sort(key=lambda x: (-x["pop"], x["name"]))
    named = [r for r in rows if not r["unassigned"]]
    ranked = [r for r in named if r["pop"] >= MIN_POP]

    def fmt_or_dash(v):
        return "-" if v is None else f"{v * 100:.1f}%"

    neigh_table = [{
        "name": r["name"], "areas": r["areas"], "residents": n(r["pop"]),
        "share": f"{r['pop'] / total * 100:.1f}%" if total else "-",
        "kids": fmt_or_dash(r["kids"]), "old": fmt_or_dash(r["old"]),
        "olim": fmt_or_dash(r["olim"]), "family": fmt_or_dash(r["family"]),
        "unassigned": r["unassigned"],
    } for r in rows]

    chart_neigh = {"names": [r["name"] for r in rows], "values": [int(r["pop"]) for r in rows],
                   "flag": [r["unassigned"] for r in rows]}

    # ---- city age profile ------------------------------------------------
    age_vals = [int(df[b].sum()) for b in band_labels]
    peak_i = max(range(len(age_vals)), key=lambda i: (age_vals[i], -i)) if age_vals else 0
    widths = [(hi - lo + 1) if hi < 100 else None for lo, hi, _ in bands]
    chart_age = {"labels": band_labels, "values": age_vals, "widths": widths,
                 "shares": [round(v / age_total * 100, 2) if age_total else 0 for v in age_vals]}
    age_table = [{"band": b, "count": n(v), "share": f"{v / age_total * 100:.1f}%" if age_total else "-"}
                 for b, v in zip(band_labels, age_vals)]
    city_broad = {b[0]: float(df[b[0]].sum()) for b in BROAD}
    kids_share = share(city_broad[kids_name], age_total) or 0.0
    old_share = share(city_broad[old_name], age_total) or 0.0

    # ---- broad age mix per neighbourhood --------------------------------
    mix_rows = sorted(ranked, key=lambda r: (-(r["kids"] or 0), r["name"]))
    unassigned_row = next((r for r in rows if r["unassigned"]), None)
    mix_src = mix_rows + ([unassigned_row] if unassigned_row and unassigned_row["pop"] >= MIN_POP else [])
    chart_mix = {
        "names": [r["name"] for r in mix_src],
        "series": [{"name": b[0], "values": [round((r[k] or 0) * 100, 1) for r in mix_src]}
                   for b, k in zip(BROAD, ["kids", "young", "mid", "old"])],
    }
    mix_table = [{"name": r["name"], "kids": fmt_or_dash(r["kids"]), "young": fmt_or_dash(r["young"]),
                  "mid": fmt_or_dash(r["mid"]), "old": fmt_or_dash(r["old"])} for r in mix_src]

    # ---- per-area scatter + heatmap -------------------------------------
    areas = []
    for code, r in df.iterrows():
        at = r["age_total"]
        areas.append({
            "code": int(code), "name": area_name(int(code)), "pop": float(r["pop"]),
            "kids": share(r[kids_name], at), "old": share(r[old_name], at),
            "olim": share(r["olim"], r["total_o"]) if r["total_o"] else None,
            "family": share(r["גרושים"] + r["אלמנים"] + r["single_parent"], r["total"]),
            "olim_src": None if pd.isna(r["olim_pct_src"]) else float(r["olim_pct_src"]),
            "index_src": None if pd.isna(r["index_src"]) else float(r["index_src"]),
        })
    big_areas = [x for x in areas if x["pop"] >= MIN_POP and x["kids"] is not None]
    small_areas = [x for x in areas if x["pop"] < MIN_POP]
    chart_scatter = {"points": [[round(x["kids"] * 100, 1), round(x["old"] * 100, 1), int(x["pop"]),
                                 str(x["code"]), x["name"]] for x in big_areas]}

    nb = df.groupby("neigh", sort=True)[band_labels + ["age_total"]].sum()
    heat_rows = [r for r in mix_src]
    heat_cells = []
    heat_table = []
    heat_max = 0.0
    for yi, r in enumerate(heat_rows):
        at = float(nb.loc[r["key"], "age_total"])
        vals = []
        for xi, b in enumerate(band_labels):
            v = round(float(nb.loc[r["key"], b]) / at * 100, 1) if at else 0.0
            heat_max = max(heat_max, v)
            heat_cells.append([xi, yi, v])
            vals.append(f"{v:.1f}%")
        heat_table.append({"name": r["name"], "values": vals})
    chart_heat = {"x": band_labels, "y": [r["name"] for r in heat_rows],
                  "cells": heat_cells, "max": round(heat_max + 0.05, 1)}

    def src_or_calc(src, calc):
        if src is not None:
            return f"{src:.1f}%"
        return fmt_or_dash(calc)

    area_table = [{
        "code": str(x["code"]), "name": x["name"], "residents": n(x["pop"]),
        "kids": fmt_or_dash(x["kids"]), "old": fmt_or_dash(x["old"]),
        "olim": src_or_calc(x["olim_src"], x["olim"]),
        "family": src_or_calc(x["index_src"], x["family"]),
    } for x in sorted(areas, key=lambda x: x["code"])]

    # ---- marital status --------------------------------------------------
    mar_total = float(df["total"].sum())
    mar_vals = [(lab, float(df[lab].sum())) for _, lab in MARITAL]
    chart_marital = {"names": [k for k, _ in mar_vals], "values": [int(v) for _, v in mar_vals]}
    marital_table = [{"name": k, "count": n(v), "share": f"{v / mar_total * 100:.1f}%" if mar_total else "-"}
                     for k, v in mar_vals]
    city_family = share(float(df["גרושים"].sum() + df["אלמנים"].sum() + df["single_parent"].sum()), mar_total) or 0.0
    single_parent_total = float(df["single_parent"].sum())

    fam_rows = sorted([r for r in ranked if r["family"] is not None], key=lambda r: (-r["family"], r["name"]))
    chart_family = {"names": [r["name"] for r in fam_rows],
                    "values": [round(r["family"] * 100, 1) for r in fam_rows],
                    "city": round(city_family * 100, 1)}
    family_table = [{"name": r["name"], "value": f"{r['family'] * 100:.1f}%"} for r in fam_rows]

    # ---- immigrants ------------------------------------------------------
    olim_total = float(df["olim"].sum())
    olim_base = float(df["total_o"].sum())
    olim_share = share(olim_total, olim_base) or 0.0
    origin_vals = sorted([(lab, float(df[lab].sum())) for _, lab in ORIGINS], key=lambda t: (-t[1], t[0]))
    chart_origin = {"names": [k for k, _ in origin_vals], "values": [int(v) for _, v in origin_vals]}
    origin_table = [{"name": k, "count": n(v)} for k, v in origin_vals]
    origin_overlap = sum(v for _, v in origin_vals) - olim_total

    olim_rows = sorted([r for r in ranked if r["olim"] is not None], key=lambda r: (-r["olim"], r["name"]))
    chart_olim = {"names": [r["name"] for r in olim_rows],
                  "values": [round(r["olim"] * 100, 1) for r in olim_rows],
                  "city": round(olim_share * 100, 1)}
    olim_table = [{"name": r["name"], "value": f"{r['olim'] * 100:.1f}%"} for r in olim_rows]

    # ---- KPIs ------------------------------------------------------------
    n_named = len(named)
    n_areas = len([x for x in areas if x["code"] != 0])
    kpis = {
        "total": {"value": int(total), "display": n(total), "tone": "brand"},
        "neigh": {"value": n_named, "display": n(n_named), "tone": "brand"},
        "kids": {"value": round(kids_share * 100, 1), "display": kpct(kids_share), "tone": "info"},
        "old": {"value": round(old_share * 100, 1), "display": kpct(old_share), "tone": "info"},
        "olim": {"value": round(olim_share * 100, 1), "display": kpct(olim_share), "tone": "info"},
        "family": {"value": round(city_family * 100, 1), "display": kpct(city_family),
                   "tone": "warn" if city_family >= 0.2 else "brand"},
    }
    kpi_order = ["total", "neigh", "kids", "old", "olim", "family"]

    # ---- insights --------------------------------------------------------
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    def ins_largest():
        if len(ranked) < 2 or not total:
            return None
        a1, a2 = ranked[0], ranked[1]
        if a1["pop"] <= a2["pop"]:
            return None
        return (f"{a1['name']} היא השכונה המאוכלסת ביותר בעיר, עם {n(a1['pop'])} תושבים "
                f"({pct(a1['pop'] / total)} מכלל {n(total)} התושבים), ואחריה {a2['name']} "
                f"עם {n(a2['pop'])} תושבים.")

    def ins_age_gap():
        rs = [r for r in ranked if r["kids"] is not None and r["old"] is not None]
        if len(rs) < 3:
            return None
        young = max(rs, key=lambda r: (r["kids"], r["name"]))
        old = max(rs, key=lambda r: (r["old"], r["name"]))
        if young["key"] == old["key"] or young["kids"] < kids_share * LEAD_RATIO:
            return None
        return (f"הפער הגילי בין השכונות גדול: {be(young['name'])} {pct(young['kids'])} מהתושבים "
                f"הם ילדים עד גיל {BROAD[0][2]}, לעומת {pct(kids_share)} בכלל העיר, ואילו {be(old['name'])} "
                f"{pct(old['old'])} הם בני {BROAD[3][1]} ומעלה (בעיר כולה {pct(old_share)}).")

    def ins_age_peak():
        dens = [(age_vals[i] / (bands[i][1] - bands[i][0] + 1), i)
                for i in range(len(bands)) if bands[i][1] < 100 and bands[i][1] >= bands[i][0]]
        if not dens or not city_broad[old_name]:
            return None
        v, i = max(dens, key=lambda t: (t[0], -t[1]))
        return (f"שכבת הגיל הצפופה בעיר היא {band_labels[i]}, עם ממוצע של {n(v)} תושבים לכל שנתון. "
                f"על כל תושב בן {BROAD[3][1]} ומעלה יש בעיר "
                f"{city_broad[kids_name] / city_broad[old_name]:.1f} ילדים עד גיל {BROAD[0][2]}.")

    def ins_olim():
        if not olim_rows or not olim_base:
            return None
        top = olim_rows[0]
        if top["olim"] < olim_share * LEAD_RATIO:
            return None
        return (f"{n(olim_total)} עולים רשומים בעיר ({pct(olim_share)} מהתושבים). "
                f"הריכוז הגבוה ביותר הוא {be(top['name'])}, שבה {pct(top['olim'])} מהתושבים עולים.")

    def ins_origin():
        named_o = [(k, v) for k, v in origin_vals if k != "שאר הארצות" and v > 0]
        if not named_o:
            return None
        k, v = named_o[0]
        rest = dict(origin_vals).get("שאר הארצות", 0)
        tail = (f" רוב העולים ({n(rest)}) מסווגים תחת \"שאר הארצות\"." if rest > v else "")
        return f"מבין ארצות המוצא המפורטות בנתונים, {k} מובילה עם {n(v)} עולים.{tail}"

    def ins_family():
        if not fam_rows or not mar_total:
            return None
        top = fam_rows[0]
        if top["family"] < city_family * LEAD_RATIO:
            return None
        return (f"מדד הגרושים, האלמנים והמשפחות שבראשן הורה עצמאי עומד על {pct(city_family)} בכלל העיר, "
                f"ומגיע ל-{pct(top['family'])} {be(top['name'])}. בעיר רשומות {n(single_parent_total)} "
                f"משפחות שבראשן הורה עצמאי.")

    def ins_unassigned():
        if not unassigned_row or not total:
            return None
        sh = unassigned_row["pop"] / total
        if sh < 0.02:
            return None
        txt = (f"{n(unassigned_row['pop'])} תושבים ({pct(sh)}) רשומים בקוד 0, ללא שיוך לאזור סטטיסטי או לשכונה")
        if unassigned_row["kids"] is not None and unassigned_row["kids"] >= kids_share * LEAD_RATIO:
            txt += f"; זו קבוצה צעירה במיוחד, {pct(unassigned_row['kids'])} מהם ילדים"
        return txt + "."

    add("largest", ins_largest())
    add("age_gap", ins_age_gap())
    add("age_peak", ins_age_peak())
    add("olim", ins_olim())
    add("origin", ins_origin())
    add("family", ins_family())
    add("unassigned", ins_unassigned())

    # ---- labels / summary ------------------------------------------------
    top_name = ranked[0]["name"] if ranked else ""
    summary = (f"כמה תושבים גרים בכל שכונה בבאר שבע: {n(total)} תושבים ב-{n_named} שכונות "
               f"ו-{n(n_areas)} אזורים סטטיסטיים, לפי גיל, מצב משפחתי ועלייה.")
    if len(summary) > 155:
        summary = f"תושבי באר שבע לפי שכונה: {n(total)} תושבים ב-{n_named} שכונות, לפי גיל, מצב משפחתי ועלייה."

    min_pop = n(MIN_POP)
    small_note = (f" {len(small_areas)} אזורים עם פחות מ-{min_pop} תושבים אינם מוצגים." if small_areas else "")
    fixed_w = [w for w in widths if w]
    wmin, wmax = (min(fixed_w), max(fixed_w)) if fixed_w else (0, 0)
    labels = {
        "lede": (f"מרשם האוכלוסין של עיריית באר שבע מונה {n(total)} תושבים, בפילוח ל-{n(n_areas)} "
                 f"אזורים סטטיסטיים (אג״ס) שמקובצים ל-{n_named} שכונות לפי טבלת ההמרה של העירייה. "
                 f"לכל אזור יש התפלגות גילים, מצב משפחתי ומספר העולים לפי ארץ מוצא. "
                 f"הנתונים מתעדכנים מדי חודש ומציגים תמונת מצב עדכנית, ללא היסטוריה."),
        "kpi_total": "תושבים רשומים בעיר",
        "broad": [b[0] for b in BROAD],
        "kpi_neigh": "שכונות בטבלת ההמרה",
        "kpi_kids": f"ילדים עד גיל {BROAD[0][2]}",
        "kpi_old": f"בני {BROAD[3][1]} ומעלה",
        "kpi_olim": "עולים מכלל התושבים",
        "kpi_family": "מדד גרושים, אלמנים והורים עצמאיים",
        "neigh_lede": (f"{top_name} מובילה במספר התושבים. הטבלה מציגה לכל שכונה את מספר התושבים, "
                       f"שיעור הילדים והמבוגרים, שיעור העולים ומדד הגרושים, האלמנים וההורים העצמאיים."
                       if top_name else "מספר התושבים בכל שכונה."),
        "neigh_aria": (f"גרף עמודות: מספר התושבים בכל שכונה בבאר שבע. המובילה: {top_name}, "
                       f"{n(ranked[0]['pop'])} תושבים." if ranked else "גרף עמודות: מספר התושבים בכל שכונה."),
        "neigh_caption": "מספר התושבים ומאפייניהם בכל שכונה",
        "age_lede": (f"הקבוצה הגדולה בגרף היא {band_labels[peak_i]} ({n(age_vals[peak_i])} תושבים), אך רוחב "
                     f"הקבוצות שונה ({wmin} עד {wmax} שנים), ולכן בריחוף מוצג גם ממוצע התושבים לשנתון. ילדים עד גיל {BROAD[0][2]} הם {pct(kids_share)} מהתושבים, ובני {BROAD[3][1]} ומעלה "
                     f"{pct(old_share)}." if age_vals else ""),
        "age_aria": (f"גרף עמודות: מספר התושבים בבאר שבע לפי קבוצת גיל. הגדולה: {band_labels[peak_i]}."
                     if age_vals else "גרף עמודות: תושבים לפי קבוצת גיל."),
        "age_caption": "תושבים לפי קבוצת גיל",
        "mix_lede": (f"חלוקת התושבים בכל שכונה לארבע קבוצות גיל, ממוינת לפי שיעור הילדים. "
                     f"מוצגות שכונות עם {min_pop} תושבים לפחות."),
        "mix_aria": (f"גרף עמודות מוערמות: שיעור הילדים, הצעירים, בני הביניים והמבוגרים בכל שכונה. "
                     f"שיעור הילדים הגבוה ביותר: {mix_rows[0]['name']}." if mix_rows else
                     "גרף עמודות מוערמות: הרכב הגילים בכל שכונה."),
        "mix_caption": "שיעור קבוצות הגיל בכל שכונה",
        "scatter_lede": (f"כל נקודה היא אזור סטטיסטי: ציר אופקי שיעור הילדים, ציר אנכי שיעור בני "
                         f"{BROAD[3][1]} ומעלה, וגודל הנקודה לפי מספר התושבים. מוצגים {len(big_areas)} "
                         f"אזורים עם {min_pop} תושבים לפחות.{small_note}"),
        "scatter_aria": (f"גרף פיזור: {len(big_areas)} אזורים סטטיסטיים לפי שיעור הילדים ושיעור המבוגרים."),
        "heat_lede": (f"שיעור כל קבוצת גיל מתושבי השכונה, בשכונות עם {min_pop} תושבים לפחות. "
                      f"צבע כהה יותר מסמן שיעור גבוה יותר; השורות ממוינות לפי שיעור הילדים."),
        "heat_aria": f"מפת חום: שיעור כל קבוצת גיל ב-{len(heat_rows)} שכונות בבאר שבע.",
        "heat_caption": "שיעור קבוצות הגיל המפורטות בכל שכונה",
        "marital_lede": (f"מצב משפחתי של כלל {n(mar_total)} התושבים, ילדים כלולים (ולכן נמנים עם הרווקים)."),
        "marital_aria": ("גרף עמודות: תושבי באר שבע לפי מצב משפחתי. "
                         f"הקבוצה הגדולה: {max(mar_vals, key=lambda t: (t[1], t[0]))[0]}." if mar_vals else ""),
        "marital_caption": "תושבים לפי מצב משפחתי",
        "family_lede": (f"שיעור הגרושים, האלמנים והמשפחות שבראשן הורה עצמאי מכלל תושבי השכונה. "
                        f"הקו המקווקו הוא הממוצע העירוני ({pct(city_family)}). שכונות עם {min_pop} תושבים לפחות."),
        "family_aria": (f"גרף עמודות: מדד הגרושים, האלמנים וההורים העצמאיים בכל שכונה. הגבוה ביותר: "
                        f"{fam_rows[0]['name']}." if fam_rows else "גרף עמודות: מדד משפחות לפי שכונה."),
        "family_caption": "מדד גרושים, אלמנים והורים עצמאיים לפי שכונה",
        "origin_lede": (f"{n(olim_total)} עולים רשומים בעיר. קטגוריות ארץ המוצא חופפות חלקית בנתוני "
                        f"המקור, ולכן סכומן ({n(olim_total + origin_overlap)}) גבוה מסך העולים."
                        if origin_overlap > 0 else f"{n(olim_total)} עולים רשומים בעיר, לפי ארץ מוצא."),
        "origin_aria": (f"גרף עמודות: עולים בבאר שבע לפי ארץ מוצא. הקטגוריה הגדולה: {origin_vals[0][0]}."
                        if origin_vals else "גרף עמודות: עולים לפי ארץ מוצא."),
        "origin_caption": "עולים לפי ארץ מוצא",
        "olim_lede": (f"שיעור העולים מתושבי כל שכונה. הקו המקווקו הוא הממוצע העירוני ({pct(olim_share)}). "
                      f"שכונות עם {min_pop} תושבים לפחות."),
        "olim_aria": (f"גרף עמודות: שיעור העולים בכל שכונה. הגבוה ביותר: {olim_rows[0]['name']}, "
                      f"{pct(olim_rows[0]['olim'])}." if olim_rows else "גרף עמודות: שיעור העולים לפי שכונה."),
        "olim_caption": "שיעור העולים לפי שכונה",
        "area_caption": "נתוני כל אזור סטטיסטי",
        "area_summary": f"הצג את כל {n(len(areas))} האזורים הסטטיסטיים",
    }

    agent_data = {
        "summary_he": summary,
        "dataset_kind": "rankings",
        "suggested_tags": ["דמוגרפיה", "אוכלוסייה", "באר שבע", "שכונות", "עולים", "קבוצות גיל"],
        "related_ids": ["947814b2-f2a8-4f4b-a8ec-a5f4bd2f0abe", "3c6d4061-41bf-4403-82e9-c8fae5df04dd",
                        "82a30a97-01b0-4281-854c-c7931f3445c0"],
        "spatial_coverage": "באר שבע",
    }

    return {
        "agent_data": agent_data,
        "kpis": kpis,
        "kpi_order": kpi_order,
        "insights": insights,
        "labels": labels,
        "charts": {
            "neigh": chart_neigh, "age": chart_age, "mix": chart_mix,
            "scatter": chart_scatter, "heat": chart_heat, "marital": chart_marital,
            "family": chart_family, "origin": chart_origin, "olim": chart_olim,
        },
        "tables": {
            "neigh": neigh_table, "age": age_table, "mix": mix_table, "heat": heat_table, "marital": marital_table,
            "family": family_table, "origin": origin_table, "olim": olim_table, "areas": area_table,
        },
        "flags": {
            "mix": len(mix_src) >= 2, "scatter": len(big_areas) >= 3, "heat": len(heat_rows) >= 3,
            "family": len(fam_rows) >= 2, "olim": len(olim_rows) >= 2,
        },
    }
