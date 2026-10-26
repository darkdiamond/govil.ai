"""המדרך — verified environmental product declarations (EPD) reported to the
Ministry of Environmental Protection.

One row per catalogue item (SKU): a product's sizes and pack variants each get
their own row, all carrying the same EPD values. The page therefore works at
the PRODUCT level — rows grouped by (producer, commercial name) — and counts
the rows only as "items". Within a product the values are identical today;
the per-product value is the median over its rows, which is order-independent
should variants ever diverge.

Impact values are per declared (functional) unit, which differs between
products (1 m² of board, 1 kg of plaster or aluminium). Absolute values are
only compared inside a comparison group = material classification × unit.
Unit-free views (stage shares, carbon per MJ of energy) are compared across
the whole register.

Modules follow EN 15804: A1 raw materials, A2 transport to plant, A3
manufacturing, A4 transport to site, A5 installation, B use stage, C1–C4 end
of life, D benefits beyond the system boundary (credit, usually negative).
The upstream column "עמודה1" is the tropospheric-ozone module D (mislabelled
upstream) and is not used. "Now" is never the wall clock: the expiry insight
quotes the earliest validity date in the data, without comparing to today.
"""
import math
import re

import pandas as pd

GROUP_TOP = 15        # products per comparison-group chart
MAX_GROUPS = 6        # comparison-group charts
SUB_TOP = 10          # subclassifications in the stage-share chart
HEAT_MAX = 30         # products in the heatmap
SPREAD_MIN = 1.5      # max/min ratio for the "spread" insight
EOL_MIN = 0.20        # end-of-life share for the end-of-life insight
OUTLIER_X = 10        # x group median for the outlier insight
LEADER_MIN = 0.40     # share of items for the producer-concentration insight
VARIANT_MIN = 5       # items per product for the variants insight
INTENSITY_GAP = 1.3   # ratio between classifications for the intensity insight
LRI, PDI = "⁦", "⁩"
MINUS = "−"

STAGES = [  # (key, label, columns)
    ("A1", "A1 חומרי גלם", ["GWP_A1"]),
    ("A2", "A2 הובלה למפעל", ["GWP_A2"]),
    ("A3", "A3 ייצור", ["GWP_A3"]),
    ("A4", "A4 הובלה לאתר", ["GWP_A4"]),
    ("A5", "A5 התקנה", ["GWP_A5"]),
    ("B", "B שלב השימוש", [f"GWP_B{i}" for i in range(1, 8)]),
    ("C1", "C1 פירוק והריסה", ["GWP_C1"]),
    ("C2", "C2 הובלה לטיפול", ["GWP_C2"]),
    ("C3", "C3 עיבוד פסולת", ["GWP_C3"]),
    ("C4", "C4 סילוק", ["GWP_C4"]),
]
EOL_KEYS = ["C1", "C2", "C3", "C4"]
SCATTER_CI = [0, 4, 2, 7, 5, 3, 1, 6]   # high-contrast palette indices for scatter series
# index into window.GOVIL_PALETTE per stage: neighbours in the stack stay distinct
STAGE_CI = {"A1": 1, "A2": 5, "A3": 0, "A4": 6, "A5": 7, "B": 4, "C1": 2, "C2": 8, "C3": 3, "C4": 9}
PROD_KEYS = ["A1", "A2", "A3"]

# (key, column (A1–A3 sum), short label, unit column or fixed unit)
INDICATORS = [
    ("gwp", "GWP_total_A1_A3", "התחממות גלובלית", None, "ק\"ג CO₂ שו\"ע"),
    ("odp", "ozone_depletion_sum_A1-A3", "דלדול אוזון", None, "ק\"ג CFC-11 שו\"ע"),
    ("ap", "acidification_sum_A1-A3", "החמצה", "AC_unit_of_measure", "mol H+ eq."),
    ("erd", "nonrenewable_energy_resources_depletion_sum_A1-A3", "אנרגיה לא מתחדשת", None, "MJ"),
    ("meu", "marine_eutrophication_sum_A1-A3", "אאוטרופיקציה ימית", "MEU_unit_of_measure", "kg N eq."),
    ("feu", "freshwater_eutrophication_sum_A1-A3", "אאוטרופיקציה במים מתוקים", "FEU_unit_of_measure", "kg P eq."),
    ("teu", "terrestrial_eutrophication_sum_A1-A3", "אאוטרופיקציה יבשתית", "TEU_unit_of_measure", "mol N eq."),
    ("pocp", "tropospheric_ozone_sum_A1-A3", "יצירת אוזון קרקעי", None, "ק\"ג NMVOC שו\"ע"),
]

HEB = re.compile(r"[֐-׿]")
LAT = re.compile(r"[A-Za-z]")


def n(v):
    return f"{int(v):,}"


def pct(v, digits=1):
    return f"{LRI}{v * 100:.{digits}f}%{PDI}"


def num_disp(v, sig=3):
    """Significant-figure display with a real minus sign."""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    if v == 0:
        return "0"
    a = abs(v)
    if a >= 1000:
        s = f"{a:,.0f}"
    elif a >= 0.01:
        digits = max(0, sig - 1 - int(math.floor(math.log10(a))))
        s = f"{a:.{digits}f}"
    else:
        s = f"{a:.{sig - 1}e}"
    return (MINUS + s) if v < 0 else s


def to_num(s):
    s = s.astype(str).str.strip().str.replace(",", "", regex=False)
    s = s.str.replace("0.00+00", "0", regex=False)
    return pd.to_numeric(s, errors="coerce")


def norm_space(s):
    return re.sub(r"\s+", " ", str(s)).strip()


def short_name(name):
    """Hebrew part of a bilingual commercial name; Latin-only names stay whole."""
    if not HEB.search(name):
        return name
    for sep in (" - ", " -  ", "- "):
        if sep in name:
            head = name.split(sep, 1)[0].strip()
            if HEB.search(head):
                return head
    toks = name.split(" ")
    last = max(i for i, t in enumerate(toks) if HEB.search(t))
    keep = toks[: last + 1]
    for t in toks[last + 1:]:
        if LAT.search(t):
            break
        keep.append(t)
    return " ".join(keep)


def unit_of(fu):
    s = norm_space(fu).lower()
    if "ק\"ג" in s or "קג" in s or "kg" in s or "ק״ג" in s:
        return "ק\"ג"
    if "מ\"ר" in s or "מ״ר" in s or "m2" in s or "m²" in s:
        return "מ\"ר"
    if "מ\"ק" in s or "m3" in s:
        return "מ\"ק"
    return s or "לא צוין"


def parse_date(s):
    return pd.to_datetime(s.astype(str).str.strip(), errors="coerce", format="%d.%m.%Y")


def d_disp(ts):
    return f"{ts.day}.{ts.month}.{ts.year}"


def fsum(vals):
    return math.fsum(sorted(float(v) for v in vals))


def _mode(series):
    vc = series.value_counts()
    top = vc.max()
    return sorted(vc[vc == top].index)[0]


# ── preparation ─────────────────────────────────────────────────────────
def _products(df):
    df = df.copy()
    df["producer"] = df["producers_name"].map(norm_space)
    df["name"] = df["commercial_name"].map(norm_space)
    df = df[(df["producer"] != "") & (df["name"] != "")]
    df["unit"] = df["functional_unit"].map(unit_of)
    df["cls"] = df["material_classification"].map(norm_space).replace("", "לא מסווג")
    df["sub"] = df["material_subclassification"].map(norm_space).replace("", "לא מסווג")
    df["site"] = df["producing_site"].map(norm_space)
    df["vdate"] = parse_date(df["verification_date"])
    df["valid"] = parse_date(df["verification_validity"])
    df["pub"] = parse_date(df["publishing_date"])
    df["fu_qty"] = df["functional_unit"].map(lambda s: norm_space(s).split(" ")[0])

    stage_cols = sorted({c for _, _, cols in STAGES for c in cols if c in df.columns})
    num_cols = stage_cols + ["GWP_D", "gwp_total_sum"] + [c for _, c, *_ in INDICATORS]
    for c in num_cols:
        df["n_" + c] = to_num(df[c])

    rows = []
    for (prod, name), g in df.groupby(["producer", "name"], sort=True):
        r = {"producer": prod, "name": name, "items": int(len(g)),
             "unit": _mode(g["unit"]), "cls": _mode(g["cls"]), "sub": _mode(g["sub"]),
             "site": _mode(g["site"])}
        for c in num_cols:
            v = g["n_" + c].dropna()
            r[c] = float(v.median()) if len(v) else float("nan")
        for key, label, cols in STAGES:
            vals = [r[c] for c in cols if c in r and not pd.isna(r[c])]
            r["st_" + key] = fsum(vals) if vals else 0.0
        r["st_D"] = 0.0 if pd.isna(r["GWP_D"]) else float(r["GWP_D"])
        r["gross"] = fsum(r["st_" + k] for k, _, _ in STAGES)
        r["net"] = r["gwp_total_sum"] if not pd.isna(r["gwp_total_sum"]) else r["gross"] + r["st_D"]
        for col, unit_col in [(c, u) for _, c, _, u, _ in INDICATORS]:
            if unit_col:
                r["u_" + col] = _mode(g[unit_col].map(norm_space).replace("", "—"))
        rows.append(r)
    p = pd.DataFrame(rows)
    # display names: Hebrew part, full name where the short form collides
    p["disp"] = p["name"].map(short_name)
    dup = p.duplicated(["disp"], keep=False)
    paren = p["name"].str.extract(r"(\([^()]*\))\s*$")[0].fillna("")
    p.loc[dup, "disp"] = (p.loc[dup, "disp"] + " " + paren[dup]).str.strip()
    dup = p.duplicated(["disp"], keep=False)
    p.loc[dup, "disp"] = p.loc[dup, "name"]
    p["grp"] = p["cls"] + " · ל-1 " + p["unit"]
    subs = p.groupby("grp")["sub"].agg(lambda s: sorted(set(s)))
    p["glabel"] = [subs[g][0] if len(subs[g]) == 1 else c for g, c in zip(p["grp"], p["cls"])]
    csubs = p.groupby("cls")["sub"].agg(lambda s: sorted(set(s)))
    p["clabel"] = [csubs[c][0] if len(csubs[c]) == 1 else c for c in p["cls"]]
    odd_units = sorted({norm_space(fu) for fu, q in zip(df["functional_unit"], df["fu_qty"])
                        if q not in ("1", "")})
    return df, p, odd_units


# ── insights ────────────────────────────────────────────────────────────
def insight_leader(df, p):
    items = df.groupby("producer").size().sort_index().sort_values(ascending=False, kind="mergesort")
    if len(items) < 2:
        return None
    top, cnt = items.index[0], int(items.iloc[0])
    share = cnt / len(df)
    if share < LEADER_MIN or cnt == int(items.iloc[1]):
        return None
    np_ = int((p["producer"] == top).sum())
    return (f"{top} מחזיקה {n(cnt)} מתוך {n(len(df))} הפריטים במאגר ({pct(share)}), "
            f"ב-{n(np_)} מתוך {n(len(p))} המוצרים"
            + (f" — הדיווח הוולונטרי נשען עד כה על {n(len(items))} יצרנים בלבד." if len(items) <= 5 else "."))


def insight_variants(df, p):
    s = p.sort_values(["items", "name"], ascending=[False, True], kind="mergesort")
    top = s.iloc[0]
    if top["items"] < VARIANT_MIN:
        return None
    multi = int((p["items"] > 1).sum())
    return (f"{n(len(df))} הרשומות מייצגות {n(len(p))} מוצרים בלבד: מידות ואריזות של אותו מוצר "
            f"מופיעות כפריטים נפרדים עם נתוני השפעה זהים. ל{top['disp']} לבדו {n(top['items'])} פריטים, "
            f"ול-{n(multi)} מוצרים יש יותר מפריט אחד.")


def insight_spread(groups):
    best = None
    for g in groups:
        if len(g["rows"]) < 3:
            continue
        vals = [(r["net"], r["disp"]) for r in g["rows"] if r["net"] > 0]
        if len(vals) < 3:
            continue
        lo, hi = min(vals), max(vals)
        ratio = hi[0] / lo[0]
        if best is None or ratio > best[0]:
            best = (ratio, g, lo, hi)
    if best is None or best[0] < SPREAD_MIN:
        return None
    ratio, g, lo, hi = best
    return (f"בקבוצת {g['cls']} (ל-1 {g['unit']}) טביעת הרגל הפחמנית נעה בין {num_disp(lo[0])} "
            f"({lo[1]}) ל-{num_disp(hi[0])} ק\"ג CO₂ שו\"ע ({hi[1]}) — פער של פי {ratio:.1f} "
            f"בין מוצרים מאותו סוג.")


def insight_eol(stage_rows):
    cand = [r for r in stage_rows if r["n"] >= 2]
    if not cand:
        return None
    top = sorted(cand, key=lambda r: (-r["eol"], r["name"]))[0]
    if top["eol"] < EOL_MIN:
        return None
    return (f"ב{top['name']} סוף החיים (C1–C4) אחראי בממוצע ל-{pct(top['eol'])} מהפליטות הגולמיות, "
            f"ומתוכו הפירוק וההריסה (C1) ל-{pct(top['c1'])} — "
            f"לעומת {pct(top['prod'])} בשלבי הייצור A1–A3.")


def insight_credit(p):
    cr = p[(p["st_D"] < 0) & (p["gross"] > 0)].copy()
    if len(cr) < 2:
        return None
    cr["rel"] = -cr["st_D"] / cr["gross"]
    cr = cr.sort_values(["rel", "name"], ascending=[False, True], kind="mergesort")
    top = cr.iloc[0]
    if top["rel"] < 0.05:
        return None
    return (f"ל-{n(len(cr))} מתוך {n(len(p))} המוצרים יש זיכוי מודול D (מיחזור ושימוש חוזר מעבר "
            f"לגבולות המערכת). הגדול ביותר — {top['disp']}: זיכוי של {num_disp(-top['st_D'])} ק\"ג CO₂ שו\"ע, "
            f"{pct(top['rel'])} מהפליטות הגולמיות.")


def insight_outlier(p):
    best = None
    for key, col, label, _, _ in INDICATORS:
        for grp, g in p.groupby("grp", sort=True):
            v = g[col].dropna()
            if len(v) < 3:
                continue
            med = v.median()
            if med <= 0:
                continue
            for _, r in g.iterrows():
                if pd.isna(r[col]):
                    continue
                x = r[col] / med
                if x >= OUTLIER_X and (best is None or x > best[0]):
                    others = []
                    for _, c2, *_ in INDICATORS:
                        if c2 == col or pd.isna(r[c2]):
                            continue
                        m2 = g[c2].dropna().median()
                        if m2 > 0:
                            others.append(r[c2] / m2)
                    best = (x, label, r, int(len(v)), max(others) if others else None)
    if best is None:
        return None
    x, label, r, k, other_max = best
    tail = (f", בעוד ביתר המדדים הוא לכל היותר פי {other_max:.1f} מהחציון — ייתכן שגיאה בהזנת הערך"
            if other_max is not None and other_max < 3 else "")
    return (f"חריג בנתונים: במדד {label} (שלבי A1–A3) הערך של {r['disp']} גבוה פי {x:,.0f} "
            f"מהחציון של {n(k)} המוצרים בקבוצת {r['glabel']}{tail}.")


def insight_intensity(intens):
    cand = [r for r in intens if r["n"] >= 2]
    if len(cand) < 2:
        return None
    cand = sorted(cand, key=lambda r: (-r["median"], r["name"]))
    hi, lo = cand[0], cand[-1]
    if lo["median"] <= 0 or hi["median"] / lo["median"] < INTENSITY_GAP:
        return None
    return (f"ביחס לאנרגיה הלא מתחדשת שהם צורכים, ל{hi['name']} עוצמת הפחמן הגבוהה ביותר — "
            f"חציון {hi['median'] * 1000:.0f} גרם CO₂ שו\"ע ל-MJ, לעומת {lo['median'] * 1000:.0f} גרם ב{lo['name']} "
            f"(פי {hi['median'] / lo['median']:.1f}; מדד שאינו תלוי ביחידה ההצהרתית).")


def insight_expiry(df, decl):
    if not decl:
        return None
    first = sorted(decl, key=lambda r: (r["valid_ts"], r["producer"]))[0]
    last = sorted(decl, key=lambda r: (r["valid_ts"], r["producer"]))[-1]
    txt = (f"כל ההצהרות אומתו לתקופה של {first['years']} שנים. התוקף המוקדם ביותר במאגר — "
           f"{d_disp(first['valid_ts'])}, להצהרות של {first['producer']} ({n(first['items'])} פריטים)")
    if last["valid_ts"] != first["valid_ts"]:
        txt += f"; המאוחר ביותר — {d_disp(last['valid_ts'])} ({last['producer']})."
    else:
        txt += "."
    return txt


# ── main ────────────────────────────────────────────────────────────────
def compute(frames):
    raw = frames["main"]
    df, p, odd_units = _products(raw)
    total_rows, total_prod = int(len(df)), int(len(p))
    producers = sorted(p["producer"].unique())

    # comparison groups
    gsize = p.groupby("grp").size()
    order = sorted(gsize.index, key=lambda k: (-int(gsize[k]), k))
    multi = [k for k in order if gsize[k] >= 2]
    singles = [k for k in order if gsize[k] < 2]
    shown, hidden = multi[:MAX_GROUPS], multi[MAX_GROUPS:]
    groups = []
    for gi, k in enumerate(shown):
        g = p[p["grp"] == k].sort_values(["net", "name"], ascending=[False, True], kind="mergesort")
        allrows = g.to_dict("records")
        rows = allrows[:GROUP_TOP]
        cnt = len(rows)
        h = "h-64 md:h-80" if cnt <= 5 else ("h-80 md:h-[420px]" if cnt <= 10 else "h-[520px] md:h-[600px]")
        lo, hi = min(r["net"] for r in allrows), max(r["net"] for r in allrows)
        prods = sorted({r["producer"] for r in allrows})
        groups.append({
            "id": f"chart-grp-{gi + 1}", "cls": rows[0]["glabel"], "unit": rows[0]["unit"],
            "title": f"{rows[0]['glabel']} — ל-1 {rows[0]['unit']}", "height": h, "rows": allrows,
            "chart": {
                "names": [r["disp"] for r in rows],
                "producers": [r["producer"] for r in rows],
                "series": [{"name": lab, "ci": STAGE_CI[key], "data": [round(r["st_" + key], 5) for r in rows]}
                           for key, lab, _ in STAGES if any(r["st_" + key] != 0 for r in rows)]
                          + ([{"name": "D זיכוי מעבר לגבולות המערכת", "credit": True,
                               "data": [round(r["st_D"], 5) for r in rows]}]
                             if any(r["st_D"] != 0 for r in rows) else []),
                "net": [round(r["net"], 5) for r in rows],
                "unit": f"ק\"ג CO₂ שו\"ע ל-1 {rows[0]['unit']}",
            },
            "table": [{"name": r["disp"], "producer": r["producer"], "skus": n(r["items"]),
                       "prod": num_disp(fsum(r["st_" + k2] for k2 in PROD_KEYS)),
                       "eol": num_disp(fsum(r["st_" + k2] for k2 in EOL_KEYS)),
                       "d": num_disp(r["st_D"]), "net": num_disp(r["net"])} for r in rows],
            "note": (f"{n(len(allrows))} מוצרים של {' ו'.join(prods) if len(prods) <= 2 else n(len(prods)) + ' יצרנים'}. "
                     f"טביעת הרגל נטו נעה בין {num_disp(lo)} ל-{num_disp(hi)} ק\"ג CO₂ שו\"ע ל-1 {rows[0]['unit']}"
                     + (f"; מוצגים {n(GROUP_TOP)} הגבוהים מתוך {n(len(allrows))}." if len(allrows) > GROUP_TOP else ".")),
            "aria": (f"תרשים עמודות מוערמות של טביעת הרגל הפחמנית לפי שלב מחזור חיים, {n(cnt)} מוצרים בקבוצת "
                     f"{rows[0]['glabel']}; הגבוה: {rows[0]['disp']} עם {num_disp(rows[0]['net'])} ק\"ג CO₂ שו\"ע נטו."),
        })
    single_names = [f"{r['disp']} ({r['glabel']}, ל-1 {r['unit']})"
                    for r in (p[p["grp"] == k].iloc[0] for k in singles)]
    hidden_n = int(sum(int(gsize[k]) for k in hidden))

    # stage shares by subclassification (mean of product shares)
    pp = p[p["gross"] > 0].copy()
    for key, _, _ in STAGES:
        pp["sh_" + key] = pp["st_" + key] / pp["gross"]
    pp["sh_D"] = pp["st_D"] / pp["gross"]
    ssize = pp.groupby("sub").size()
    sorder = sorted(ssize.index, key=lambda k: (-int(ssize[k]), k))
    top_subs = sorder[:SUB_TOP]
    pp["sub2"] = pp["sub"].where(pp["sub"].isin(top_subs), "אחר")
    sub_names = top_subs + (["אחר"] if len(sorder) > SUB_TOP else [])
    stage_rows = []
    for s in sub_names:
        g = pp[pp["sub2"] == s]
        r = {"name": s, "n": int(len(g))}
        for key, _, _ in STAGES + [("D", None, None)]:
            r[key] = fsum(g["sh_" + key]) / len(g)
        r["prod"] = sum(r[k] for k in PROD_KEYS)
        r["eol"] = sum(r[k] for k in EOL_KEYS)
        eol_abs = fsum(fsum(row["st_" + k] for k in EOL_KEYS) for _, row in g.iterrows())
        r["c1"] = (fsum(g["st_C1"]) / eol_abs) if eol_abs > 0 else 0.0
        stage_rows.append(r)
    active_stages = [(k, lab) for k, lab, _ in STAGES if any(abs(r[k]) > 0 for r in stage_rows)]
    stages_chart = {
        "names": [r["name"] for r in stage_rows],
        "series": [{"name": lab, "ci": STAGE_CI[k], "data": [round(r[k] * 100, 1) for r in stage_rows]}
                   for k, lab in active_stages]
                  + [{"name": "D זיכוי (שלילי)", "data": [round(r["D"] * 100, 1) for r in stage_rows], "credit": True}],
        "counts": [r["n"] for r in stage_rows],
        "xmin": int(math.floor(min([0.0] + [r["D"] * 100 for r in stage_rows]) / 10.0) * 10),
    }
    stages_table = [{"name": r["name"], "n": n(r["n"]), "prod": pct(r["prod"]),
                     "a45": pct(r.get("A4", 0) + r.get("A5", 0)), "eol": pct(r["eol"]),
                     "d": pct(r["D"]).replace("-", MINUS)} for r in stage_rows]
    all_prod_share = float(pp[[f"sh_{k}" for k in PROD_KEYS]].sum(axis=1).median()) if len(pp) else 0.0
    eol_cand = [r for r in stage_rows if r["n"] >= 2] or stage_rows
    eol_top = sorted(eol_cand, key=lambda r: (-r["eol"], r["name"]))[0] if eol_cand else None

    # carbon intensity per MJ (A1–A3; unit-free)
    gcol, ecol = "GWP_total_A1_A3", "nonrenewable_energy_resources_depletion_sum_A1-A3"
    ip = p[(p[gcol] > 0) & (p[ecol] > 0)].copy()
    ip["int"] = ip[gcol] / ip[ecol]
    csize = ip.groupby("clabel").size()
    corder = sorted(csize.index, key=lambda k: (-int(csize[k]), k))
    intens = []
    scatter = []
    for c in corder:
        g = ip[ip["clabel"] == c].sort_values(["name"], kind="mergesort")
        intens.append({"name": c, "n": int(len(g)), "median": float(g["int"].median()),
                       "min": float(g["int"].min()), "max": float(g["int"].max())})
        scatter.append({"name": c, "ci": SCATTER_CI[len(scatter) % len(SCATTER_CI)], "data": [[round(r[ecol], 6), round(r[gcol], 6), r["disp"], r["unit"]]
                                            for _, r in g.iterrows()]})
    by_med = sorted(intens, key=lambda r: (-r["median"], r["name"]))
    int_hi, int_lo = (by_med[0], by_med[-1]) if by_med else (None, None)
    intens_table = [{"name": r["name"], "n": n(r["n"]), "median": f"{r['median'] * 1000:.0f}",
                     "range": f"{r['min'] * 1000:.0f}–{r['max'] * 1000:.0f}"} for r in intens]

    # heatmap: A1–A3 indicators relative to group max
    hp = p[p["grp"].isin(multi)].copy()
    hp["gorder"] = hp["grp"].map({k: i for i, k in enumerate(multi)})
    hp = hp.sort_values(["gorder", "net", "name"], ascending=[True, False, True], kind="mergesort").head(HEAT_MAX)
    heat_y = list(hp["disp"])
    cells = []
    gmax = {}
    for key, col, *_ in INDICATORS:
        gmax[key] = p[p["grp"].isin(multi)].groupby("grp")[col].max()
    for yi, (_, r) in enumerate(hp.iterrows()):
        for xi, (key, col, label, ucol, ufix) in enumerate(INDICATORS):
            v = r[col]
            mx = gmax[key].get(r["grp"])
            if pd.isna(v) or mx is None or pd.isna(mx) or mx <= 0:
                continue
            unit = r.get("u_" + col, ufix) if ucol else ufix
            cells.append([xi, yi, round(max(v, 0) / mx * 100), num_disp(v), unit if isinstance(unit, str) else ufix])
    heat = {"x": [lab for _, _, lab, _, _ in INDICATORS], "y": heat_y, "cells": cells,
            "groups": [r["glabel"] for _, r in hp.iterrows()]}

    # declarations: producer × verification window
    dd = df.dropna(subset=["vdate", "valid"])
    decl = []
    for (prod, vd, va), g in dd.groupby(["producer", "vdate", "valid"], sort=True):
        decl.append({"producer": prod, "vdate_ts": vd, "valid_ts": va, "items": int(len(g)),
                     "products": int(g["name"].nunique()),
                     "site": _mode(g["site"]), "years": int(round((va - vd).days / 365.25))})
    decl = sorted(decl, key=lambda r: (r["vdate_ts"], r["producer"]))
    years_set = sorted({r["years"] for r in decl})
    if len(years_set) != 1:
        for r in decl:
            r["years"] = None
    valid_chart = {
        "names": [f"{r['producer']} · {r['vdate_ts'].year}" for r in decl],
        "start": [round(r["vdate_ts"].year + (r["vdate_ts"].dayofyear - 1) / 365.25, 3) for r in decl],
        "len": [round((r["valid_ts"] - r["vdate_ts"]).days / 365.25, 3) for r in decl],
        "from": [d_disp(r["vdate_ts"]) for r in decl],
        "to": [d_disp(r["valid_ts"]) for r in decl],
        "items": [r["items"] for r in decl],
        "min": int(min(r["vdate_ts"].year for r in decl)) if decl else 0,
        "max": int(max(r["valid_ts"].year for r in decl)) + 1 if decl else 1,
    }
    decl_table = [{"producer": r["producer"], "site": r["site"], "products": n(r["products"]),
                   "skus": n(r["items"]), "from": d_disp(r["vdate_ts"]), "to": d_disp(r["valid_ts"])}
                  for r in decl]

    # catalogue composition by subclassification
    cat = (p.groupby("sub").agg(products=("name", "size"), items=("items", "sum"),
                                cls=("cls", lambda s: _mode(s)),
                                producer=("producer", lambda s: _mode(s))).reset_index())
    cat = cat.sort_values(["items", "products", "sub"], ascending=[False, False, True], kind="mergesort")
    cat_chart = {"names": list(cat["sub"]), "items": [int(v) for v in cat["items"]],
                 "products": [int(v) for v in cat["products"]]}
    cat_table = [{"name": r["sub"], "cls": r["cls"], "producer": r["producer"], "products": n(r["products"]),
                  "skus": n(r["items"])} for _, r in cat.iterrows()]

    # insights
    insights = []
    for iid, txt in [
        ("leader", insight_leader(df, p)),
        ("variants", insight_variants(df, p)),
        ("spread", insight_spread(groups)),
        ("eol", insight_eol(stage_rows)),
        ("credit", insight_credit(p)),
        ("intensity", insight_intensity(intens)),
        ("outlier", insight_outlier(p)),
        ("expiry", insight_expiry(df, decl) if len(years_set) == 1 else None),
    ]:
        if txt:
            insights.append({"id": iid, "text_he": txt})

    # KPIs
    earliest = min((r["valid_ts"] for r in decl), default=None)
    latest_v = max((r["vdate_ts"] for r in decl), default=None)
    # vintage-relative, never the wall clock: an expiry within a year of the newest
    # verification in the data is flagged.
    expiry_tone = ("warn" if earliest is not None and (earliest - latest_v).days <= 365 else "brand")
    n_cls = int(p["cls"].nunique())
    kpis = {
        "products": {"value": total_prod, "display": n(total_prod), "tone": "brand"},
        "skus": {"value": total_rows, "display": n(total_rows), "tone": "brand"},
        "producers": {"value": len(producers), "display": n(len(producers)),
                      "tone": "brand"},
        "classes": {"value": n_cls, "display": n(n_cls), "tone": "brand"},
        "prod_share": {"value": round(all_prod_share * 100, 1), "display": f"{all_prod_share * 100:.0f}%",
                       "tone": "brand"},
        "expiry": {"value": earliest.strftime("%Y-%m-%d") if earliest is not None else None,
                   "display": d_disp(earliest) if earliest is not None else "—", "tone": expiry_tone},
    }

    pub_years = sorted({int(t.year) for t in df["pub"].dropna()})
    years_span = (f"{pub_years[0]}–{pub_years[-1]}" if len(pub_years) > 1 else (str(pub_years[0]) if pub_years else ""))
    lede = (f"המדרך מרכז הצהרות סביבתיות מאומתות (EPD) שיצרנים מדווחים באופן וולונטרי: {n(total_prod)} מוצרים "
            f"של {n(len(producers))} יצרנים, ב-{n(total_rows)} פריטי קטלוג, "
            + (f"שפורסמו בשנים {years_span}. " if len(pub_years) > 1 else (f"שפורסמו ב-{years_span}. " if pub_years else ""))
            + "לכל מוצר נמדדו בניתוח מחזור חיים (LCA) טביעת הרגל הפחמנית ושבעה מדדי השפעה נוספים, "
            "לפי שלבי התקן EN 15804 — מחומרי הגלם ועד סוף החיים. הערכים מוצהרים ליחידה תפקודית "
            "(מ\"ר או ק\"ג), ולכן ההשוואות בעמוד נעשות בתוך קבוצות של אותו סוג חומר ואותה יחידה.")

    labels = {
        "lede": lede,
        "products_kpi": "מוצרים מוצהרים",
        "skus_kpi": "פריטי קטלוג (רשומות)",
        "producers_kpi": "יצרנים מדווחים",
        "classes_kpi": "סוגי חומר",
        "prod_share_kpi": "חציון חלק שלבי הייצור (A1–A3) בפליטות",
        "expiry_kpi": "תוקף ההצהרה המוקדם ביותר",
        "cat_note": (f"{n(total_rows)} הפריטים מתחלקים ל-{n(len(cat))} תת-סוגי חומר. "
                     f"{cat.iloc[0]['sub']} מוביל עם {n(cat.iloc[0]['items'])} פריטים "
                     f"({n(cat.iloc[0]['products'])} מוצרים) — רוב הפריטים הם מידות ואריזות של אותו מוצר."),
        "cat_aria": (f"תרשים עמודות של פריטים ומוצרים לפי תת-סוג חומר; המוביל: {cat.iloc[0]['sub']} עם "
                     f"{n(cat.iloc[0]['items'])} פריטים."),
        "cat_caption": "פריטים ומוצרים לפי תת-סוג חומר",
        "groups_note": ("כל עמודה מפרקת את טביעת הרגל הפחמנית של מוצר לשלבי מחזור החיים; הזיכוי (D) מוצג "
                        "שלילי, והנקודה מסמנת את הסך נטו כפי שהוצהר."
                        + (f" מוצרים בודדים בקבוצתם אינם מוצגים: {'; '.join(single_names)}." if single_names else "")
                        + (f" {n(len(hidden))} קבוצות נוספות ({n(hidden_n)} מוצרים) אינן מוצגות." if hidden else "")
                        + (f" ברשומות מסוימות היחידה התפקודית מצוינת ככמות שונה מ-1 ({', '.join(odd_units)}); "
                           "הן מקובצות לפי סוג היחידה." if odd_units else "")),
        "stages_note": ((f"החלק הממוצע של כל שלב מהפליטות הגולמיות (A–C), לפי תת-סוג חומר — מדד שאינו תלוי ביחידה. "
                         f"בחציון המוצרים שלבי הייצור A1–A3 אחראים ל-{all_prod_share * 100:.0f}% מהפליטות; "
                         f"ב{eol_top['name']} סוף החיים מגיע ל-{eol_top['eol'] * 100:.0f}%.")
                        if eol_top else ""),
        "stages_aria": (f"תרשים עמודות מוערמות של חלק כל שלב מחזור חיים בפליטות, לפי תת-סוג חומר; "
                        f"חציון חלק הייצור {all_prod_share * 100:.0f}%."),
        "stages_caption": "חלק שלבי מחזור החיים בפליטות לפי תת-סוג חומר",
        "int_note": ((f"כל נקודה היא מוצר: אנרגיה לא מתחדשת (MJ) מול טביעת רגל פחמנית בשלבי A1–A3, באותה יחידה תפקודית "
                      f"(צירים לוגריתמיים). היחס ביניהם — גרם CO₂ שו\"ע ל-MJ — אינו תלוי ביחידה: "
                      f"מ-{int_lo['median'] * 1000:.0f} ב{int_lo['name']} ועד {int_hi['median'] * 1000:.0f} "
                      f"ב{int_hi['name']} (חציון).")
                     if intens else ""),
        "int_aria": (f"תרשים פיזור של אנרגיה לא מתחדשת מול טביעת רגל פחמנית ל-{n(len(ip))} מוצרים, "
                     f"צבוע לפי סוג חומר."),
        "int_caption": "עוצמת פחמן ביחס לאנרגיה לפי סוג חומר",
        "heat_note": (f"שמונת מדדי ההשפעה בשלבי הייצור A1–A3, כאחוז מהערך הגבוה ביותר בקבוצת ההשוואה של המוצר "
                      f"(סוג חומר × יחידה). תא כהה = המוצר הכבד בקבוצתו באותו מדד. {n(len(hp))} מוצרים"
                      + (f" (מוצגים {n(HEAT_MAX)} הראשונים)." if len(p[p['grp'].isin(multi)]) > HEAT_MAX else ".")),
        "heat_aria": (f"מפת חום של {n(len(INDICATORS))} מדדי השפעה סביבתית ל-{n(len(hp))} מוצרים, "
                      f"יחסית לערך הגבוה בקבוצת ההשוואה."),
        "valid_note": (f"חלון התוקף של כל הצהרה, מתאריך האימות ועד פקיעתה. "
                       + (f"כל ההצהרות במאגר תקפות ל-{years_set[0]} שנים." if len(years_set) == 1 else "")),
        "valid_aria": (f"תרשים ציר זמן של {n(len(decl))} חלונות תוקף הצהרה; התוקף המוקדם פג ב-"
                       f"{d_disp(earliest) if earliest is not None else '—'}."),
        "valid_caption": "הצהרות לפי יצרן ותקופת תוקף",
        "th_prod": "ייצור A1–A3",
        "th_a45": "הובלה והתקנה A4–A5",
        "th_eol": "סוף חיים C1–C4",
        "th_d": "זיכוי D",
    }

    temporal = f"{pub_years[0]}/{pub_years[-1]}" if pub_years else None
    agent_data = {
        "summary_he": (f"הצהרות סביבתיות מאומתות (EPD) של {n(total_prod)} מוצרי בנייה מתוצרת ישראל "
                       f"({n(total_rows)} פריטי קטלוג, {n(len(producers))} יצרנים): טביעת רגל פחמנית ושבעה מדדי "
                       f"השפעה לפי שלבי מחזור החיים."),
        "dataset_kind": "rankings",
        "suggested_tags": ["טביעת רגל פחמנית", "ניתוח מחזור חיים", "חומרי בנייה", "הצהרה סביבתית",
                           "המשרד להגנת הסביבה"],
        "related_ids": ["04931a88-336c-4d95-8a13-9dc631c3e2d1",
                        "5fc5c912-4fa5-4474-93c1-326e505e22cf",
                        "6b991a56-c209-4b02-a52e-ba1c69091a4c"],
        "spatial_coverage": "ישראל",
    }
    if temporal:
        agent_data["temporal_coverage"] = temporal

    return {
        "agent_data": agent_data,
        "kpis": kpis,
        "charts": {"catalog": cat_chart, "stages": stages_chart, "scatter": scatter,
                   "heat": heat, "valid": valid_chart},
        "groups": [{k: v for k, v in g.items() if k != "rows"} for g in groups],
        "tables": {"catalog": cat_table, "stages": stages_table, "intensity": intens_table,
                   "declarations": decl_table},
        "insights": insights,
        "labels": labels,
    }
