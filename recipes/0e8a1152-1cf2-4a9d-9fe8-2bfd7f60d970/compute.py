"""מבנים לשימור בבאר שבע — four distinct layers: buildings (polygons, one
centroid each), complexes (מתחמים), fences (גדרות) and heritage elements
(wells and similar).  The other resources are format / projection twins of
these four (CSV, XLSX, ITM, KML, SHP) and are not read.

Everything is aggregate: counts per preservation grade, era bucket, footprint
band, distance from the layer's median centre, survey-card coverage, complex
areas, fence lengths.  Order-independent: counts, medians and fsum over
sorted values only.  The assets are public heritage sites, not people.
"""
import math
import re

import numpy as np
import pandas as pd

STD_ORDER = ["א", "ב1", "ב2", "ג", "ד", "טנטטיבי", "ללא", ""]
ERAS = ["1900-1918", "1918-1935", "1935-1945", "מאוחר מ-1945"]
AREA_EDGES = [0, 50, 100, 200, 500, 2000]
DIST_EDGES = [0, 250, 500, 1000, 2000]
DECLARED_RE = re.compile(r"(הוכרז|מוכרז)")


def fmt(n):
    return f"{int(round(n)):,}"


def pct(x):
    return f"{x * 100:.1f}%"


def std_label(s):
    s = (s or "").strip()
    if s == "":
        return "לא צוינה"
    if s == "ללא":
        return "ללא דרגה"
    if s == "טנטטיבי":
        return "טנטטיבי"
    return f"דרגה {s}"


def std_key(s):
    s = (s or "").strip()
    return (STD_ORDER.index(s), s) if s in STD_ORDER else (len(STD_ORDER), s)


def num(series):
    return pd.to_numeric(series.astype(str).str.replace(",", "", regex=False).str.strip(), errors="coerce")


def era_of(y):
    s = str(y).strip().replace("--", "-")
    for e in ERAS:
        if s.startswith(e):
            return e
    return None


def band_labels(edges, unit_fmt=fmt):
    out = []
    for i, lo in enumerate(edges):
        if i == 0:
            out.append(f"עד {unit_fmt(edges[1])}")
        elif i + 1 < len(edges):
            out.append(f"{unit_fmt(lo)} עד {unit_fmt(edges[i + 1])}")
        else:
            out.append(f"מעל {unit_fmt(lo)}")
    return out


def band_index(v, edges):
    idx = 0
    for i, lo in enumerate(edges):
        if v >= lo:
            idx = i
    return idx


def stack_series(df, band_col, nbands, std_col="std", top=5):
    """stds (ordered) x bands counts; stds beyond `top` merge into 'אחר'."""
    counts = df.groupby(std_col).size()
    order = sorted(counts.index, key=std_key)
    keep = order[:top]
    names, series = [], []
    for s in keep:
        sub = df[df[std_col] == s]
        names.append(std_label(s))
        series.append([int((sub[band_col] == b).sum()) for b in range(nbands)])
    rest = [s for s in order if s not in keep]
    if rest:
        sub = df[df[std_col].isin(rest)]
        names.append("אחר")
        series.append([int((sub[band_col] == b).sum()) for b in range(nbands)])
    return names, series


def compute(frames):
    b = frames["buildings"].copy()
    el = frames["elements"].copy()
    cx = frames["complexes"].copy()
    fe = frames["fences"].copy()

    # ---------- buildings ----------
    b["std"] = b["standard"].str.strip()
    b["area"] = num(b["SHAPE_Area"])
    b["la"] = num(b["lat"])
    b["lo"] = num(b["lon"])
    b["card"] = num(b["cartis"]).fillna(0).astype(int)
    b["era"] = b["year"].map(era_of)
    b["declared"] = b["year"].str.contains(DECLARED_RE)
    nb = len(b)

    # standards
    std_counts = b.groupby("std").size()
    std_order = sorted(std_counts.index, key=std_key)
    std_rows = []
    medians = {}
    for s in std_order:
        sub = b[b["std"] == s]
        med = float(sub["area"].median()) if sub["area"].notna().any() else None
        medians[s] = med
        std_rows.append([std_label(s), fmt(len(sub)), pct(len(sub) / nb), fmt(med) if med is not None else "—"])
    charts = {}
    tables = {}
    charts["standards"] = {"names": [std_label(s) for s in std_order], "values": [int(std_counts[s]) for s in std_order]}
    tables["standards"] = {"headers": ["דרגה", "מבנים", "שיעור", "חציון שטח (מ״ר)"], "rows": std_rows}

    # era
    era_counts = [int((b["era"] == e).sum()) for e in ERAS]
    n_era = sum(era_counts)
    charts["eras"] = {"names": ERAS, "values": era_counts}
    tables["eras"] = {
        "headers": ["תקופה", "מבנים", "שיעור מהמסווגים"],
        "rows": [[e, fmt(c), pct(c / n_era) if n_era else "—"] for e, c in zip(ERAS, era_counts)],
    }
    has_eras = n_era >= 20

    # std x era
    era_df = b[b["era"].notna()].copy()
    era_df["eb"] = era_df["era"].map(ERAS.index)
    se_names, se_series = stack_series(era_df, "eb", len(ERAS)) if len(era_df) else ([], [])
    charts["std_era"] = {"eras": ERAS, "names": se_names, "series": se_series}
    tables["std_era"] = {
        "headers": ["דרגה"] + ERAS,
        "rows": [[n] + [fmt(v) for v in s] for n, s in zip(se_names, se_series)],
    }
    has_std_era = len(era_df) >= 20 and len(se_names) >= 2

    # footprint bands
    ab = b[b["area"].notna()].copy()
    ab["ab"] = ab["area"].map(lambda v: band_index(v, AREA_EDGES))
    area_labels = band_labels(AREA_EDGES)
    a_names, a_series = stack_series(ab, "ab", len(AREA_EDGES))
    charts["areas"] = {"bands": area_labels, "names": a_names, "series": a_series}
    tables["areas"] = {
        "headers": ["דרגה"] + area_labels,
        "rows": [[n] + [fmt(v) for v in s] for n, s in zip(a_names, a_series)],
    }
    med_area = float(ab["area"].median())
    big = int((ab["area"] >= AREA_EDGES[-1]).sum())

    # survey cards
    card_rows, card_names, card_vals = [], [], []
    with_card = int((b["card"] > 0).sum())
    for s in std_order:
        sub = b[b["std"] == s]
        if len(sub) < 5:
            continue
        w = int((sub["card"] > 0).sum())
        card_names.append(std_label(s))
        card_vals.append(round(w / len(sub) * 100, 1))
        card_rows.append([std_label(s), fmt(len(sub)), fmt(w), pct(w / len(sub))])
    charts["cards"] = {"names": card_names, "values": card_vals}
    tables["cards"] = {"headers": ["דרגה", "מבנים", "עם כרטיס סקר", "שיעור"], "rows": card_rows}
    has_cards = len(card_names) >= 2
    cc = b[b["card"] > 0].groupby("card").size()
    cc = cc[cc >= 2]
    cc = cc.reset_index(name="n").sort_values(["n", "card"], ascending=[False, True]).head(10)
    charts["top_cards"] = {"names": [f"כרטיס {int(c)}" for c in cc["card"]], "values": [int(n) for n in cc["n"]]}
    tables["top_cards"] = {
        "headers": ["כרטיס סקר", "מבנים"],
        "rows": [[str(int(c)), fmt(n)] for c, n in zip(cc["card"], cc["n"])],
    }
    has_top_cards = len(cc) >= 3
    n_cards = int(b[b["card"] > 0]["card"].nunique())

    # distance from median centre
    geo = b[b["la"].notna() & b["lo"].notna()].copy()
    la0 = float(geo["la"].median())
    lo0 = float(geo["lo"].median())
    dy = (geo["la"] - la0) * 111320.0
    dx = (geo["lo"] - lo0) * 111320.0 * math.cos(math.radians(la0))
    geo["d"] = np.sqrt(dx * dx + dy * dy)
    geo["db"] = geo["d"].map(lambda v: band_index(v, DIST_EDGES))
    dist_labels = band_labels(DIST_EDGES)
    d_names, d_series = stack_series(geo, "db", len(DIST_EDGES))
    charts["dist"] = {"bands": dist_labels, "names": d_names, "series": d_series}
    tables["dist"] = {
        "headers": ["דרגה"] + dist_labels,
        "rows": [[n] + [fmt(v) for v in s] for n, s in zip(d_names, d_series)],
    }
    med_d = float(geo["d"].median())
    within_1k = float((geo["d"] < 1000).mean())

    # ---------- complexes ----------
    cx["area"] = num(cx["SHAPE_Area"])
    cx["name"] = cx["Taba"].str.strip()
    cx["std"] = cx["shimur"].str.strip()
    cx = cx[cx["area"].notna()].copy()
    ncx = len(cx)
    tot_cx_area = math.fsum(sorted(cx["area"].tolist()))
    cs = cx.assign(nm=cx["name"].where(cx["name"] != "", "ללא שם")).sort_values(
        ["area", "nm", "std"], ascending=[False, True, True]
    ).head(12)
    charts["cx_top"] = {
        "names": [f"{n} ({std_label(s)})" for n, s in zip(cs["nm"], cs["std"])],
        "values": [round(a / 1000, 1) for a in cs["area"]],
    }
    tables["cx_top"] = {
        "headers": ["מתחם", "דרגה", "שטח (דונם)"],
        "rows": [[n, std_label(s), f"{a / 1000:,.1f}"] for n, s, a in zip(cs["nm"], cs["std"], cs["area"])],
    }
    cstd = sorted(cx["std"].unique(), key=std_key)
    cx_counts = [int((cx["std"] == s).sum()) for s in cstd]
    cx_area = [round(math.fsum(sorted(cx[cx["std"] == s]["area"].tolist())) / 1000, 1) for s in cstd]
    charts["cx_std"] = {"names": [std_label(s) for s in cstd], "counts": cx_counts, "areas": cx_area}
    tables["cx_std"] = {
        "headers": ["דרגה", "מתחמים", "שטח כולל (דונם)"],
        "rows": [[std_label(s), fmt(c), f"{a:,.1f}"] for s, c, a in zip(cstd, cx_counts, cx_area)],
    }
    has_cx = ncx >= 5

    # ---------- fences ----------
    fe["len"] = num(fe["SHAPE_Leng"])
    fe["std"] = fe["standard"].str.strip()
    fe = fe[fe["len"].notna()].copy()
    nfe = len(fe)
    tot_fe_len = math.fsum(sorted(fe["len"].tolist()))
    fstd = sorted(fe["std"].unique(), key=std_key)
    f_counts = [int((fe["std"] == s).sum()) for s in fstd]
    f_len = [round(math.fsum(sorted(fe[fe["std"] == s]["len"].tolist())) / 1000, 2) for s in fstd]
    charts["fe_std"] = {"names": [std_label(s) for s in fstd], "counts": f_counts, "km": f_len}
    tables["fe_std"] = {
        "headers": ["דרגה", "קטעי גדר", "אורך כולל (ק״מ)"],
        "rows": [[std_label(s), fmt(c), f"{k:,.2f}"] for s, c, k in zip(fstd, f_counts, f_len)],
    }
    fe_edges = [0, 10, 25, 50, 100]
    fe["fb"] = fe["len"].map(lambda v: band_index(v, fe_edges))
    fe_labels = band_labels(fe_edges)
    fn, fs = stack_series(fe, "fb", len(fe_edges))
    charts["fe_len"] = {"bands": fe_labels, "names": fn, "series": fs}
    tables["fe_len"] = {"headers": ["דרגה"] + fe_labels, "rows": [[n] + [fmt(v) for v in s] for n, s in zip(fn, fs)]}
    has_fe = nfe >= 10
    ungraded_fe = int((fe["std"] == "").sum())

    # ---------- elements ----------
    el["std"] = el["standard"].str.strip()
    el["name"] = el["Taba"].str.strip()
    el["note"] = el["Hakama"].str.strip()
    nel = len(el)
    el_std = sorted(el["std"].unique(), key=std_key)
    charts["el_std"] = {
        "names": [std_label(s) for s in el_std],
        "values": [int((el["std"] == s).sum()) for s in el_std],
    }
    tables["el_std"] = {
        "headers": ["דרגה", "אלמנטים"],
        "rows": [[std_label(s), fmt((el["std"] == s).sum())] for s in el_std],
    }
    has_el = nel >= 5
    txt = el["name"] + " " + el["note"]
    wells = int(txt.str.contains("באר|בור מים").sum())
    el_sorted = el.assign(k=el["name"].where(el["name"] != "", el["note"])).sort_values(
        ["std", "k", "note"], key=lambda s: s.map(std_key) if s.name == "std" else s
    )
    tables["el_list"] = {
        "headers": ["אלמנט", "דרגה", "הערה"],
        "rows": [[(k if k else "ללא שם"), std_label(s), n or "—"] for k, s, n in zip(el_sorted["k"], el_sorted["std"], el_sorted["note"])],
    }

    # layer overview
    layer_names = ["מבנים", "מתחמים", "גדרות", "אלמנטים"]
    layer_vals = [nb, ncx, nfe, nel]
    charts["layers"] = {"names": layer_names, "values": layer_vals}
    tables["layers"] = {
        "headers": ["שכבה", "פריטים"],
        "rows": [[n, fmt(v)] for n, v in zip(layer_names, layer_vals)],
    }

    # ---------- insights ----------
    insights = []

    # 1 leading grade
    lead = max(std_order, key=lambda s: (int(std_counts[s]), -std_order.index(s)))
    lead_share = int(std_counts[lead]) / nb
    if lead != "" and lead_share >= 0.3:
        second = sorted([s for s in std_order if s != lead], key=lambda s: -int(std_counts[s]))[0]
        insights.append({"id": "grade_leader", "text_he": (
            f"{std_label(lead)} היא הדרגה הנפוצה ביותר: {fmt(std_counts[lead])} מתוך {fmt(nb)} מבנים ({pct(lead_share)}), "
            f"ואחריה {std_label(second)} עם {fmt(std_counts[second])}.")})

    # 2 footprint contrast between grades
    big_grades = [s for s in std_order if s != "" and int(std_counts[s]) >= 20 and medians[s] is not None]
    if len(big_grades) >= 2:
        hi = max(big_grades, key=lambda s: (medians[s], s))
        lo = min(big_grades, key=lambda s: (medians[s], s))
        if medians[lo] > 0 and medians[hi] / medians[lo] >= 1.5:
            insights.append({"id": "footprint", "text_he": (
                f"החציון של שטח המבנה בדרגות עם לפחות 20 מבנים מגיע ל־{fmt(medians[hi])} מ״ר ב{std_label(hi)} "
                f"לעומת {fmt(medians[lo])} מ״ר ב{std_label(lo)} — פי {medians[hi] / medians[lo]:.1f}.")})

    # 3 era
    if has_eras:
        li = max(range(len(ERAS)), key=lambda i: (era_counts[i], -i))
        if era_counts[li] / n_era >= 0.3:
            insights.append({"id": "era", "text_he": (
                f"מבין {fmt(n_era)} המבנים שסווגו לתקופה, {ERAS[li]} מובילה עם {fmt(era_counts[li])} ({pct(era_counts[li] / n_era)}). "
                f"עוד {fmt(nb - n_era)} מבנים ללא תקופה ברורה בשדה.")})

    # 4 survey cards
    if nb:
        sh = with_card / nb
        best = None
        for s in std_order:
            sub = b[b["std"] == s]
            if s != "" and len(sub) >= 20:
                r = float((sub["card"] > 0).mean())
                if best is None or r > best[1]:
                    best = (s, r, len(sub))
        txt4 = f"{fmt(with_card)} מבנים ({pct(sh)}) משויכים לכרטיס סקר, מתוך {fmt(n_cards)} כרטיסים שונים"
        if best is not None:
            txt4 += f"; שיעור הכיסוי הגבוה ביותר ב{std_label(best[0])} ({pct(best[1])})"
        insights.append({"id": "cards", "text_he": txt4 + "."})

    # 5 concentration
    if len(geo) >= 50 and within_1k >= 0.5:
        insights.append({"id": "centre", "text_he": (
            f"המבנים מרוכזים סביב מרכז אחד: {pct(within_1k)} מהם במרחק של עד {fmt(DIST_EDGES[3])} מ׳ ממרכז החציון של הקואורדינטות, "
            f"והמרחק החציוני הוא {fmt(med_d)} מ׳.")})

    # 6 declared
    nd = int(b["declared"].sum())
    if nd >= 5:
        insights.append({"id": "declared", "text_he": (
            f"בשדה התקופה מצוינת הכרזה לשימור ב־{fmt(nd)} מבנים ({pct(nd / nb)}); "
            f"שאר המבנים נכללים בשכבה בלי ציון כזה.")})

    # 7 big complex
    if has_cx and tot_cx_area > 0:
        top = cs.iloc[0]
        share = float(top["area"]) / tot_cx_area
        if share >= 0.15 and str(top["nm"]) != "ללא שם":
            insights.append({"id": "complex", "text_he": (
                f"המתחם הגדול ביותר הוא ״{top['nm']}״ בשטח {top['area'] / 1000:,.1f} דונם — "
                f"{pct(share)} מסך שטחם של {fmt(ncx)} המתחמים ({tot_cx_area / 1000:,.1f} דונם).")})

    # 8 fences
    if has_fe:
        gi = [i for i, s_ in enumerate(fstd) if s_ != ""]
        txt8 = (f"שכבת הגדרות כוללת {fmt(nfe)} קטעים באורך כולל של {tot_fe_len / 1000:,.1f} ק״מ")
        if gi:
            ig = max(gi, key=lambda i: (f_len[i], -i))
            txt8 += f"; מבין הקטעים שדורגו, הארוכים ביותר בדרגה {fstd[ig]} ({f_len[ig]:,.1f} ק״מ)"
        if ungraded_fe:
            txt8 += f"; {fmt(ungraded_fe)} קטעים ללא דרגה"
        insights.append({"id": "fences", "text_he": txt8 + "."})

    # 9 wells
    if has_el and wells / nel >= 0.5:
        insights.append({"id": "wells", "text_he": (
            f"{fmt(wells)} מתוך {fmt(nel)} אלמנטי השימור מתוארים (בשם או בהערה) כבאר או בור מים — "
            f"הסיווג לפי הטקסט החופשי בשדות.")})

    # 10 ungraded
    ung = int((b["std"].isin(["", "טנטטיבי"])).sum())
    if nb and ung / nb >= 0.03:
        insights.append({"id": "ungraded", "text_he": (
            f"{fmt(ung)} מבנים ({pct(ung / nb)}) ללא דרגה סופית — {fmt(int((b['std'] == '').sum()))} בלי דרגה כלל "
            f"ו־{fmt(int((b['std'] == 'טנטטיבי').sum()))} בדרגה טנטטיבית.")})

    # ---------- kpis ----------
    ung_tone = "warn" if nb and ung / nb >= 0.05 else "brand"
    kpis = {
        "buildings": {"value": nb, "display": fmt(nb), "tone": "brand", "label": "מבנים לשימור"},
        "complexes": {"value": ncx, "display": fmt(ncx), "tone": "brand", "label": "מתחמי שימור"},
        "fence_km": {"value": round(tot_fe_len / 1000, 1), "display": f"{tot_fe_len / 1000:,.1f}", "tone": "brand", "label": "אורך גדרות לשימור (ק״מ)"},
        "ungraded": {"value": ung, "display": fmt(ung), "tone": ung_tone, "label": "מבנים ללא דרגה סופית"},
    }

    lede = (
        f"ארבע שכבות שימור בעיר: {fmt(nb)} מבנים, {fmt(ncx)} מתחמים, {fmt(nfe)} קטעי גדר ו־{fmt(nel)} אלמנטים. "
        f"שטח המבנה החציוני הוא {fmt(med_area)} מ״ר, ו־{fmt(big)} מבנים נושאים שטח של מעל {fmt(AREA_EDGES[-1])} מ״ר."
    )

    labels = {
        "lede": lede,
        "layers_note": f"מספר הפריטים בכל אחת מארבע השכבות; בסך הכול {fmt(sum(layer_vals))}.",
        "standards_note": f"חלוקת {fmt(nb)} המבנים לפי דרגת השימור.",
        "eras_note": f"תקופת הבנייה כפי שמופיעה בנתונים; רק {fmt(n_era)} מתוך {fmt(nb)} המבנים סווגו לאחת מארבע התקופות.",
        "std_era_note": f"דרגות השימור בכל תקופה, עבור {fmt(n_era)} המבנים שסווגו לתקופה.",
        "areas_note": f"שטח הבסיס של כל מבנה (מ״ר), מחולק לפי דרגה; חציון {fmt(med_area)} מ״ר.",
        "cards_note": f"שיעור המבנים המשויכים לכרטיס סקר בכל דרגה עם לפחות חמישה מבנים.",
        "top_cards_note": "כרטיסי סקר שאליהם משויכים לפחות שניים מהמבנים; עשרת הגדולים.",
        "dist_note": f"מרחק כל מבנה ממרכז החציון של הקואורדינטות ({fmt(len(geo))} מבנים עם מיקום), לפי דרגה.",
        "cx_top_note": "המתחמים הגדולים ביותר לפי שטח, בדונם, עם דרגת השימור שלהם.",
        "cx_std_note": f"מספר המתחמים ושטחם הכולל לפי דרגה; סך השטח {tot_cx_area / 1000:,.1f} דונם.",
        "fe_std_note": f"אורך כולל (ק״מ) של קטעי הגדר בכל דרגה; בסך הכול {tot_fe_len / 1000:,.1f} ק״מ.",
        "fe_len_note": "התפלגות אורכי קטעי הגדר (מטרים), לפי דרגה.",
        "el_std_note": f"{fmt(nel)} אלמנטי שימור לפי דרגה; הרשימה המלאה מתחת לגרף.",
        "map_b_note": "כל נקודה היא מבנה; לחיצה פותחת את הדרגה, התקופה וכרטיס הסקר.",
        "map_c_note": "מרכזי המתחמים; לחיצה פותחת שם ודרגה.",
        "map_f_note": "נקודת מיקום לכל קטע גדר.",
        "map_e_note": "מיקומי אלמנטי השימור.",
    }
    for k, v in [
        ("layers", "מספר פריטים לפי שכבה"), ("standards", "מבנים לפי דרגת שימור"),
        ("eras", "מבנים לפי תקופה"), ("std_era", "דרגות שימור לפי תקופה"),
        ("areas", "מבנים לפי טווח שטח"), ("cards", "שיעור כיסוי כרטיס סקר לפי דרגה"),
        ("top_cards", "כרטיסי סקר עם הכי הרבה מבנים"), ("dist", "מבנים לפי מרחק מהמרכז"),
        ("cx_top", "המתחמים הגדולים ביותר"), ("cx_std", "מתחמים לפי דרגה"),
        ("fe_std", "אורך גדרות לפי דרגה"), ("fe_len", "קטעי גדר לפי טווח אורך"),
        ("el_std", "אלמנטי שימור לפי דרגה"),
    ]:
        labels[k + "_aria"] = v
        labels[k + "_cap"] = v

    return {
        "agent_data": {
            "summary_he": lede,
            "dataset_kind": "map",
            "suggested_tags": ["שימור", "מבנים היסטוריים", "תכנון עירוני", "באר שבע", "מורשת"],
            "related_ids": ["82a30a97-01b0-4281-854c-c7931f3445c0", "bdf28cc0-680a-415c-af64-944a58079b2f", "3c6d4061-41bf-4403-82e9-c8fae5df04dd", "dae759e1-aa71-421a-8649-b8974a82bf2d", "b795e2e0-491e-4040-877e-f3681917f8be"],
            "spatial_coverage": "באר שבע",
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
        "flags": {
            "eras": has_eras, "std_era": has_std_era, "cards": has_cards, "top_cards": has_top_cards,
            "cx": has_cx, "fe": has_fe, "el": has_el,
        },
    }
