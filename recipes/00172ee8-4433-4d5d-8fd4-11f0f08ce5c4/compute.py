"""תושבים בישראל לפי ישובים וקבוצות גיל — Population and Immigration Authority.

One row per locality (~1.3k): locality code and name, sub-district (נפה), the
Authority bureau (לשכת מנא), regional council (code 0 / empty = none), the total
number of registered residents (סהכ) and six age bands that partition it
(0–5, 6–18, 19–45, 46–55, 56–64, 65+). The population register counts living
residents whether or not they are in the country, so these are not CBS
population estimates. The whole table is republished on each update; there is
no date column, so the page is a snapshot of the current registry counts.

Inputs
- `main`: the updating file (64edd0ee).
- `snapshot`: the frozen archive files of the same table in the old column
  layout, matched by the `גיל_0_6` column only the old layout has (today three
  files: a5e7080d, 578c8312, c90083dd — published April, May and November 2019
  per their CKAN descriptions; four more same-named archive copies collapse
  into a5e7080d as format/name twins and are never fetched). Each file is one
  snapshot (rows grouped by `_resource_name`); a group whose locality codes are
  not unique (two files sharing a name) is ignored. The baseline is the
  snapshot with the smallest registered total — the earliest, since the
  register only grows — so "change" spans the longest available interval.
  The old youngest band is labelled 0_6 (next band 6_18); the bands still
  partition the total, and the label difference is shown on the page.

Handling
- Locality code 0 ("לא רשום") holds residents with no registered locality. It
  is excluded from every per-locality and per-district view and disclosed.
- Counts are coerced to numbers; a row whose total does not parse or whose
  bands do not parse is dropped and the count is disclosed.
- Share-based rankings use minimum sizes stated on the page (MIN_POP_RANK,
  MIN_POP_SCATTER, MIN_BASE_GROWTH).
- Districts come from the first digit of the sub-district code (1 Jerusalem …
  7 Judea and Samaria); an unknown digit falls into "אחר". Mirrored
  parentheses in names (")שבט(") are fixed.
- Dependency ratio = (0–18 + 65+) per 100 residents aged 19–64 (the bands
  this file has; the international convention uses 0–14 / 15–64).

Growth: new localities, sub-districts and councils flow through; category
axes are top-N or fixed band lists; the scatter keeps the MAX_SCATTER largest
localities.
"""
import math
import re

import pandas as pd

LRI, PDI = "⁦", "⁩"
MINUS = "−"

BANDS = ["גיל_0_5", "גיל_6_18", "גיל_19_45", "גיל_46_55", "גיל_56_64", "גיל_65_פלוס"]
OLD_BANDS = ["גיל_0_6", "גיל_6_18", "גיל_19_45", "גיל_46_55", "גיל_56_64", "גיל_65_פלוס"]
KID_IDX = (0, 1)        # 0–18
WORK_IDX = (2, 3, 4)    # 19–64
OLD_IDX = (5,)          # 65+

MIN_POP_RANK = 1000
MIN_POP_SCATTER = 2000
MAX_SCATTER = 400
MIN_BASE_GROWTH = 1000
TOP_EXT = 12
TOP_CITIES = 15
TOP_GROWTH = 15
SIZE_BINS = [0, 500, 1000, 2000, 5000, 20000, 100000]
DISTRICT_GAP_PP = 3.0
AGING_GAP_PP = 2.0
SIZE_GAP_PP = 3.0
DENSITY_GAP = 0.10

DISTRICTS = {
    "1": "ירושלים",
    "2": "הצפון",
    "3": "חיפה",
    "4": "המרכז",
    "5": "תל אביב",
    "6": "הדרום",
    "7": "יהודה והשומרון",
}
OTHER = "אחר"
DISTRICT_ORDER = list(DISTRICTS.values()) + [OTHER]
D_IDX = {d: i for i, d in enumerate(DISTRICT_ORDER)}
TRIBE_TAG = "(שבט)"
_FLIP = str.maketrans("()", ")(")


# ---------------------------------------------------------------- helpers

def n(v):
    return f"{int(v):,}"


def pct(v, digits=1):
    return f"{LRI}{v:.{digits}f}%{PDI}"


def r1(v):
    return round(float(v), 1)


def signed_pct(v):
    """Signed percentage for prose; "ללא שינוי" when it rounds to 0."""
    r = round(v, 1)
    if r == 0:
        return "ללא שינוי"
    sign = "+" if r > 0 else MINUS
    return f"{LRI}{sign}{abs(r):.1f}%{PDI}"


def _clean(s):
    s = re.sub(r"\s+", " ", str(s)).strip()
    m = re.search(r"[()]", s)
    if m and m.group(0) == ")":
        s = s.translate(_FLIP)
    s = re.sub(r"(\S)\(", r"\1 (", s)
    return s


def _num(s):
    return pd.to_numeric(s.astype(str).str.replace(",", "").str.strip(), errors="coerce")


def _district_of(code):
    c = str(code).strip()
    return DISTRICTS.get(c[:1], OTHER) if c and c != "0" else OTHER


def _band_label(col):
    """'גיל_0_5' → '0 עד 5', 'גיל_65_פלוס' → '65 ומעלה'."""
    parts = col.split("_")[1:]
    if len(parts) == 2 and parts[1] == "פלוס":
        return f"{parts[0]} ומעלה"
    if len(parts) == 2:
        return f"{parts[0]} עד {parts[1]}"
    return col


def _band_width(col):
    parts = col.split("_")[1:]
    if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
        return int(parts[1]) - int(parts[0]) + 1
    return None


def _size_label(lo, hi):
    if lo == 0:
        return f"פחות מ-{hi:,}"
    if hi is None:
        return f"{lo:,} ומעלה"
    return f"{lo:,} עד {hi - 1:,}"


def _prepare(raw, bands):
    df = pd.DataFrame({
        "code": _num(raw["סמל_ישוב"]).values,
        "name": raw["שם_ישוב"].map(_clean).values,
        "nafa_code": raw["סמל_נפה"].astype(str).str.strip().values,
        "total": _num(raw["סהכ"]).values,
    })
    for i, b in enumerate(bands):
        df[f"b{i}"] = _num(raw[b]).values
    return df


def _split_placeholder(df):
    ph_mask = df["code"].fillna(-1) <= 0
    ph = df[ph_mask]
    df = df[~ph_mask & df["code"].notna()].copy()
    bcols = [f"b{i}" for i in range(len(BANDS))]
    bad = df["total"].isna() | df[bcols].isna().any(axis=1) | (df["total"] <= 0)
    n_bad = int(bad.sum())
    df = df[~bad].copy()
    df["code"] = df["code"].astype(int)
    for c in ["total"] + bcols:
        df[c] = df[c].astype(int)
    df = df.sort_values("code", kind="stable").drop_duplicates("code").reset_index(drop=True)
    phd = None
    if len(ph):
        phd = {"total": int(ph["total"].fillna(0).sum()),
               "bands": [int(ph[c].fillna(0).sum()) for c in bcols]}
    return df, phd, n_bad


def _groups(row_bands):
    kids = sum(row_bands[i] for i in KID_IDX)
    work = sum(row_bands[i] for i in WORK_IDX)
    old = sum(row_bands[i] for i in OLD_IDX)
    return kids, work, old


def _add_derived(df):
    bcols = [f"b{i}" for i in range(len(BANDS))]
    df["kids"] = df[[bcols[i] for i in KID_IDX]].sum(axis=1)
    df["work"] = df[[bcols[i] for i in WORK_IDX]].sum(axis=1)
    df["old"] = df[[bcols[i] for i in OLD_IDX]].sum(axis=1)
    df["kid_s"] = df["kids"] / df["total"] * 100
    df["old_s"] = df["old"] / df["total"] * 100
    return df


def _pool(sub):
    t = int(sub["total"].sum())
    bands = [int(sub[f"b{i}"].sum()) for i in range(len(BANDS))]
    kids, work, old = _groups(bands)
    return {
        "total": t, "bands": bands, "kids": kids, "work": work, "old": old,
        "kid_s": kids / t * 100 if t else 0.0,
        "old_s": old / t * 100 if t else 0.0,
        "dep_y": kids / work * 100 if work else 0.0,
        "dep_o": old / work * 100 if work else 0.0,
    }


def _band_shares(p):
    t = p["total"]
    return [r1(b / t * 100) if t else 0.0 for b in p["bands"]]


# ---------------------------------------------------------------- insights

def insight_structure(nat, labels):
    return (f"מתוך {n(nat['total'])} התושבים הרשומים בישובים, {pct(nat['kid_s'])} הם ילדים ובני נוער "
            f"(עד גיל {labels['kid_top']}) ו-{pct(nat['old_s'])} בני {labels['old_band']}. על כל 100 "
            f"תושבים בגיל העבודה ({labels['work_band']}) יש {nat['dep_y'] + nat['dep_o']:.0f} תלויים "
            f"— {nat['dep_y']:.0f} צעירים ו-{nat['dep_o']:.0f} מבוגרים.")


def insight_density(dens):
    if len(dens) < 3:
        return None
    first = dens[0]
    mid = max(dens[1:], key=lambda r: (r["width"], -r["i"]))
    if mid["per_year"] <= 0:
        return None
    gap = first["per_year"] / mid["per_year"] - 1
    if gap < DENSITY_GAP:
        return None
    return (f"השנתונים הצעירים גדולים יותר: בכל שנת גיל בטווח {first['label']} רשומים בממוצע "
            f"{n(first['per_year'])} תושבים, לעומת {n(mid['per_year'])} בכל שנת גיל בטווח "
            f"{mid['label']} — יותר ב-{pct(gap * 100, 0)}.")


def insight_district(dist_rows):
    rows = [r for r in dist_rows if r["name"] != OTHER and r["total"] > 0]
    if len(rows) < 3:
        return None
    young = sorted(rows, key=lambda r: (-r["kid_v"], D_IDX[r["name"]]))[0]
    old = sorted(rows, key=lambda r: (-r["old_v"], D_IDX[r["name"]]))[0]
    lo_kid = sorted(rows, key=lambda r: (r["kid_v"], D_IDX[r["name"]]))[0]
    if young["kid_v"] - lo_kid["kid_v"] < DISTRICT_GAP_PP:
        return None
    return (f"מחוז {young['name']} הוא הצעיר ביותר — {pct(young['kid_v'])} מתושביו בני 18 ומטה ורק "
            f"{pct(young['old_v'])} בני 65 ומעלה. מחוז {old['name']} הוא המבוגר ביותר: "
            f"{pct(old['old_v'])} בני 65 ומעלה ו-{pct(old['kid_v'])} ילדים ובני נוער.")


def insight_oldest(rows, n_big):
    if len(rows) < 3:
        return None
    a, b = rows[0], rows[1]
    return (f"מבין {n(n_big)} הישובים שבהם {n(MIN_POP_RANK)} תושבים ומעלה, השיעור הגבוה ביותר של בני "
            f"65 ומעלה נמצא ב{a['name']} — {pct(a['old_v'])} ({n(a['old'])} מתוך {n(a['total'])}), "
            f"ואחריו {b['name']} ({pct(b['old_v'])}).")


def insight_youngest(rows):
    if len(rows) < 3:
        return None
    a = rows[0]
    tr = sum(1 for r in rows if r["tribe"])
    tail = ""
    if tr * 4 >= len(rows):
        tail = f" {n(tr)} מתוך {n(len(rows))} הישובים בראש הדירוג הם שבטים בדואיים."
    return (f"בקצה השני, ב{a['name']} {pct(a['kid_v'])} מהתושבים הם בני 18 ומטה "
            f"({n(a['kids'])} מתוך {n(a['total'])}) — השיעור הגבוה ביותר בין הישובים שבהם {n(MIN_POP_RANK)} "
            f"תושבים ומעלה.{tail}")


def insight_cities(rows):
    if len(rows) < 5:
        return None
    hi = sorted(rows, key=lambda r: (-r["kid_v"], r["code"]))[0]
    lo = sorted(rows, key=lambda r: (r["kid_v"], r["code"]))[0]
    if hi["kid_v"] < 2 * lo["kid_v"]:
        return None
    return (f"בין {n(len(rows))} הישובים הגדולים הפער עצום: ב{hi['name']} {pct(hi['kid_v'])} מהתושבים "
            f"הם ילדים ובני נוער, פי {hi['kid_v'] / lo['kid_v']:.1f} מאשר ב{lo['name']} "
            f"({pct(lo['kid_v'])}), שבה {pct(lo['old_v'])} בני 65 ומעלה.")


def insight_size(size_rows):
    rows = [r for r in size_rows if r["count"] >= 10]
    if len(rows) < 3:
        return None
    hi = sorted(rows, key=lambda r: (-r["old_v"], r["i"]))[0]
    lo = sorted(rows, key=lambda r: (r["old_v"], r["i"]))[0]
    if hi["old_v"] - lo["old_v"] < SIZE_GAP_PP:
        return None
    return (f"לפי גודל הישוב, שיעור בני 65 ומעלה הגבוה ביותר הוא בישובים של {hi['label']} תושבים "
            f"({pct(hi['old_v'])}), והנמוך ביותר בישובים של {lo['label']} תושבים ({pct(lo['old_v'])}).")


def insight_aging(ch):
    if not ch:
        return None
    t, o, k = ch["g_total"], ch["g_old"], ch["g_kids"]
    if o - t >= AGING_GAP_PP:
        verb = "מהר יותר מכלל האוכלוסייה"
    elif t - o >= AGING_GAP_PP:
        verb = "לאט יותר מכלל האוכלוסייה"
    else:
        verb = "בקצב דומה לכלל האוכלוסייה"
    return (f"לעומת {ch['base_name']}, מספר התושבים הרשומים בישובים השתנה ב-{signed_pct(t)} "
            f"(מ-{n(ch['base_total'])} ל-{n(ch['cur_total'])}), ומספר בני 65 ומעלה ב-{signed_pct(o)} — "
            f"{verb}. מספר בני 18 ומטה השתנה ב-{signed_pct(k)}.")


def insight_growth(rows, abs_top):
    if len(rows) < 3 or not abs_top:
        return None
    a = rows[0]
    if a["g_v"] <= 0:
        return None
    head = (f"הישוב שגדל הכי מהר מאז קובץ הארכיון הוא {a['name']}: מ-{n(a['base'])} ל-{n(a['cur'])} "
            f"תושבים ({signed_pct(a['g_v'])})")
    if abs_top["name"] == a["name"]:
        return head + " — גם הגידול המוחלט הגדול ביותר."
    return (head + f". בגידול המוחלט מוביל הישוב {abs_top['name']} "
            f"(תוספת של {n(abs_top['diff'])} תושבים).")


def insight_placeholder(ph, labels):
    if not ph or ph["total"] <= 0:
        return None
    old = sum(ph["bands"][i] for i in OLD_IDX)
    return (f"{n(ph['total'])} תושבים רשומים ללא ישוב (שורת ״לא רשום״), ו-{pct(old / ph['total'] * 100)} "
            f"מהם בני {labels['old_band']}. שורה זו אינה נכללת בנתוני הישובים והמחוזות בעמוד.")


# ---------------------------------------------------------------- change

def _change(snap, cur, cur_nat):
    """Compare the current table with the earliest archive snapshot."""
    if snap is None or not len(snap) or "_resource_name" not in snap.columns:
        return None
    best = None
    for name, g in snap.groupby("_resource_name", sort=True):
        df = _prepare(g, OLD_BANDS)
        df, _, _ = _split_placeholder_old(df)
        if not len(df):
            continue
        tot = int(df["total"].sum())
        key = (tot, str(name))
        if best is None or key < best[0]:
            best = (key, df)
    if best is None:
        return None
    base = _add_derived(best[1])
    bp = _pool(base)
    rows = []
    for i, (c_old, c_new) in enumerate(zip(OLD_BANDS, BANDS)):
        b0, b1 = bp["bands"][i], cur_nat["bands"][i]
        lbl = _band_label(c_new)
        lbl_old = _band_label(c_old)
        rows.append({"label": lbl, "label_old": lbl_old, "base": b0, "cur": b1,
                     "g_v": r1((b1 / b0 - 1) * 100) if b0 else 0.0,
                     "g": signed_pct((b1 / b0 - 1) * 100) if b0 else "—"})
    base["district"] = base["nafa_code"].map(_district_of)
    m = cur[["code", "name", "total"]].merge(
        base[["code", "total"]].rename(columns={"total": "base"}), on="code", how="inner")
    m = m.sort_values("code", kind="stable")
    m["g"] = (m["total"] / m["base"] - 1) * 100
    m["diff"] = m["total"] - m["base"]
    elig = m[m["base"] >= MIN_BASE_GROWTH]
    gr = elig.sort_values(["g", "total", "code"], ascending=[False, False, True], kind="stable").head(TOP_GROWTH)
    growth_rows = [{"name": r["name"], "base": int(r["base"]), "cur": int(r["total"]),
                    "g_v": r1(r["g"]), "g": signed_pct(r["g"]), "diff": int(r["diff"])}
                   for _, r in gr.iterrows()]
    ab = m.sort_values(["diff", "code"], ascending=[False, True], kind="stable").head(1)
    abs_top = ({"name": ab.iloc[0]["name"], "diff": int(ab.iloc[0]["diff"])}
               if len(ab) and ab.iloc[0]["diff"] > 0 else None)
    new_codes = set(cur["code"]) - set(base["code"])
    gone_codes = set(base["code"]) - set(cur["code"])
    new_pop = int(cur.loc[cur["code"].isin(new_codes), "total"].sum())
    # Districts.
    d_rows = []
    for d in DISTRICT_ORDER:
        s0 = base[base["district"] == d]
        s1 = cur[cur["district"] == d]
        if not len(s0) or not len(s1):
            continue
        p0, p1 = _pool(s0), _pool(s1)
        if not p0["total"]:
            continue

        def g(a, b):
            return (b / a - 1) * 100 if a else 0.0
        d_rows.append({"name": d, "base": p0["total"], "cur": p1["total"],
                       "g_t": r1(g(p0["total"], p1["total"])), "g_k": r1(g(p0["kids"], p1["kids"])),
                       "g_o": r1(g(p0["old"], p1["old"])),
                       "g_t_d": signed_pct(g(p0["total"], p1["total"])),
                       "g_k_d": signed_pct(g(p0["kids"], p1["kids"])),
                       "g_o_d": signed_pct(g(p0["old"], p1["old"]))})
    cur_total = cur_nat["total"]
    return {
        "base_name": "קובץ הארכיון",
        "base_total": bp["total"], "cur_total": cur_total,
        "g_total": (cur_total / bp["total"] - 1) * 100 if bp["total"] else 0.0,
        "g_old": (cur_nat["old"] / bp["old"] - 1) * 100 if bp["old"] else 0.0,
        "g_kids": (cur_nat["kids"] / bp["kids"] - 1) * 100 if bp["kids"] else 0.0,
        "base_old_s": bp["old_s"], "base_kid_s": bp["kid_s"],
        "band_rows": rows, "growth_rows": growth_rows, "abs_top": abs_top,
        "n_new": len(new_codes), "n_gone": len(gone_codes), "new_pop": new_pop,
        "n_matched": int(len(m)), "n_elig": int(len(elig)), "d_rows": d_rows,
        "label_diff": rows[0]["label"] != rows[0]["label_old"],
    }


def _split_placeholder_old(df):
    """Like _split_placeholder, but a snapshot with duplicate codes is unusable."""
    ph_mask = df["code"].fillna(-1) <= 0
    body = df[~ph_mask & df["code"].notna()]
    if body["code"].duplicated().any():
        return body.iloc[0:0], None, 0
    return _split_placeholder(df)


# ---------------------------------------------------------------- compute

def compute(frames):
    raw = frames["main"]
    df = _prepare(raw, BANDS)
    df["nafa"] = raw["נפה"].map(_clean).values
    df["council_code"] = _num(raw["קוד_מועצה_אזורית"]).fillna(0).values
    df["council"] = raw["מועצה_אזורית"].map(_clean).values
    df, ph, n_bad = _split_placeholder(df)
    df = _add_derived(df)
    df["district"] = df["nafa_code"].map(_district_of)
    df.loc[df["nafa"] == "", "nafa"] = "לא ידוע"
    df["in_council"] = (df["council"] != "") & (df["council_code"] > 0)
    df["tribe"] = df["name"].str.contains(TRIBE_TAG, regex=False)
    nat = _pool(df)
    n_loc = len(df)
    band_labels = [_band_label(b) for b in BANDS]
    lab = {
        "kid_top": BANDS[KID_IDX[-1]].split("_")[-1],
        "old_band": band_labels[OLD_IDX[0]],
        "work_band": f"{BANDS[WORK_IDX[0]].split('_')[1]} עד {BANDS[WORK_IDX[-1]].split('_')[-1]}",
    }

    # National structure.
    shares = _band_shares(nat)
    dens = []
    for i, b in enumerate(BANDS):
        w = _band_width(b)
        if w:
            dens.append({"i": i, "label": band_labels[i], "width": w,
                         "per_year": int(round(nat["bands"][i] / w))})
    struct_rows = []
    for i, b in enumerate(BANDS):
        w = _band_width(b)
        struct_rows.append({"label": band_labels[i], "count": nat["bands"][i],
                            "share": f"{shares[i]:.1f}%",
                            "per_year": n(round(nat["bands"][i] / w)) if w else "—"})
    struct_chart = {"labels": band_labels, "counts": nat["bands"], "shares": shares,
                    "per_year": [int(round(nat["bands"][i] / _band_width(b))) if _band_width(b) else None
                                 for i, b in enumerate(BANDS)]}

    # Districts — age mix.
    order = [d for d in DISTRICT_ORDER if d in set(df["district"])]
    dist_rows = []
    for d in order:
        p = _pool(df[df["district"] == d])
        dist_rows.append({"name": d, "count": int((df["district"] == d).sum()), "total": p["total"],
                          "shares": _band_shares(p), "kid_v": r1(p["kid_s"]), "old_v": r1(p["old_s"]),
                          "kid": f"{p['kid_s']:.1f}%", "old": f"{p['old_s']:.1f}%",
                          "dep": f"{p['dep_y'] + p['dep_o']:.0f}"})
    dist_chart = {"names": [r["name"] for r in dist_rows],
                  "series": [[r["shares"][i] for r in dist_rows] for i in range(len(BANDS))],
                  "bands": band_labels}

    # Sub-districts — dependency ratios.
    nafa_rows = []
    for nf, sub in df.groupby("nafa", sort=True):
        p = _pool(sub)
        nafa_rows.append({"name": nf, "total": p["total"], "dep_y": r1(p["dep_y"]), "dep_o": r1(p["dep_o"]),
                          "dep_v": p["dep_y"] + p["dep_o"],
                          "dep": f"{p['dep_y'] + p['dep_o']:.1f}",
                          "dep_y_d": f"{p['dep_y']:.1f}", "dep_o_d": f"{p['dep_o']:.1f}"})
    nafa_rows.sort(key=lambda r: (-r["dep_v"], r["name"]))
    for r in nafa_rows:
        r["dep_v"] = r1(r["dep_v"])
    nafa_chart = {"names": [r["name"] for r in nafa_rows], "dep_y": [r["dep_y"] for r in nafa_rows],
                  "dep_o": [r["dep_o"] for r in nafa_rows],
                  "nat": r1(nat["dep_y"] + nat["dep_o"])}

    # Oldest / youngest localities (MIN_POP_RANK+).
    def lrow(r):
        return {"name": r["name"], "code": int(r["code"]), "total": int(r["total"]),
                "kids": int(r["kids"]), "old": int(r["old"]),
                "kid_v": r1(r["kid_s"]), "old_v": r1(r["old_s"]),
                "kid": f"{r['kid_s']:.1f}%", "old_d": f"{r['old_s']:.1f}%",
                "tribe": bool(r["tribe"]), "district": r["district"]}

    big = df[df["total"] >= MIN_POP_RANK]
    oldest = [lrow(r) for _, r in big.sort_values(["old_s", "total", "code"], ascending=[False, False, True],
                                                    kind="stable").head(TOP_EXT).iterrows()]
    youngest = [lrow(r) for _, r in big.sort_values(["kid_s", "total", "code"], ascending=[False, False, True],
                                                      kind="stable").head(TOP_EXT).iterrows()]

    def ext_chart(rows, key):
        return {"names": [r["name"] for r in rows], "v": [r[key] for r in rows],
                "total": [r["total"] for r in rows]}

    # Largest localities — age mix.
    by_t = df.sort_values(["total", "code"], ascending=[False, True], kind="stable")
    cities = []
    for _, r in by_t.head(TOP_CITIES).iterrows():
        row = lrow(r)
        row["shares"] = [r1(r[f"b{i}"] / r["total"] * 100) for i in range(len(BANDS))]
        cities.append(row)
    cities_sorted = sorted(cities, key=lambda r: (-r["kid_v"], r["code"]))
    cities_chart = {"names": [r["name"] for r in cities_sorted],
                    "series": [[r["shares"][i] for r in cities_sorted] for i in range(len(BANDS))],
                    "total": [r["total"] for r in cities_sorted], "bands": band_labels}

    # Size bands.
    size_rows = []
    for i, lo in enumerate(SIZE_BINS):
        hi = SIZE_BINS[i + 1] if i + 1 < len(SIZE_BINS) else None
        m = df["total"] >= lo
        if hi is not None:
            m &= df["total"] < hi
        sub = df[m]
        if not len(sub):
            continue
        p = _pool(sub)
        size_rows.append({"i": i, "label": _size_label(lo, hi), "count": int(len(sub)), "total": p["total"],
                          "kid_v": r1(p["kid_s"]), "old_v": r1(p["old_s"]),
                          "kid": f"{p['kid_s']:.1f}%", "old": f"{p['old_s']:.1f}%",
                          "pop_share": f"{p['total'] / nat['total'] * 100:.1f}%"})
    size_chart = {"labels": [r["label"] for r in size_rows], "kid": [r["kid_v"] for r in size_rows],
                  "old": [r["old_v"] for r in size_rows]}

    # Regional councils vs the rest.
    pc = _pool(df[df["in_council"]]) if df["in_council"].any() else None
    po = _pool(df[~df["in_council"]]) if (~df["in_council"]).any() else None
    n_councils = int(df.loc[df["in_council"], "council"].nunique())
    council_rows = []
    if pc and po:
        council_rows = [
            {"name": "ישובי המועצות האזוריות", "count": int(df["in_council"].sum()), "total": pc["total"],
             "shares": _band_shares(pc), "kid": f"{pc['kid_s']:.1f}%", "old": f"{pc['old_s']:.1f}%"},
            {"name": "שאר הישובים", "count": int((~df["in_council"]).sum()), "total": po["total"],
             "shares": _band_shares(po), "kid": f"{po['kid_s']:.1f}%", "old": f"{po['old_s']:.1f}%"},
            {"name": "כל הישובים", "count": n_loc, "total": nat["total"],
             "shares": _band_shares(nat), "kid": f"{nat['kid_s']:.1f}%", "old": f"{nat['old_s']:.1f}%"},
        ]
    council_chart = {"names": [r["name"] for r in council_rows],
                     "series": [[r["shares"][i] for r in council_rows] for i in range(len(BANDS))],
                     "bands": band_labels}
    # Oldest / youngest regional council (by pooled 65+ share).
    crow = []
    for c, sub in df[df["in_council"]].groupby("council", sort=True):
        p = _pool(sub)
        crow.append({"name": c, "old_v": p["old_s"], "kid_v": p["kid_s"], "total": p["total"]})
    c_old = sorted(crow, key=lambda r: (-r["old_v"], r["name"]))[0] if crow else None
    c_young = sorted(crow, key=lambda r: (-r["kid_v"], r["name"]))[0] if crow else None

    # Scatter.
    sc = by_t[by_t["total"] >= MIN_POP_SCATTER].head(MAX_SCATTER)
    scatter = []
    for d in order:
        sub = sc[sc["district"] == d].sort_values("code", kind="stable")
        if len(sub):
            scatter.append({"name": d, "ci": D_IDX[d],
                            "data": [[r1(k), r1(o), int(t), nm] for k, o, t, nm in
                                     zip(sub["kid_s"], sub["old_s"], sub["total"], sub["name"])]})
    n_scatter = int(len(sc))

    # Change since the archive snapshot.
    ch = _change(frames.get("snapshot"), df, nat)
    change_bands_chart = growth_chart = change_dist_chart = None
    if ch:
        change_bands_chart = {"labels": [r["label"] for r in ch["band_rows"]],
                              "base": [r["base"] for r in ch["band_rows"]],
                              "cur": [r["cur"] for r in ch["band_rows"]],
                              "g": [r["g_v"] for r in ch["band_rows"]]}
        growth_chart = {"names": [r["name"] for r in ch["growth_rows"]],
                        "g": [r["g_v"] for r in ch["growth_rows"]],
                        "base": [r["base"] for r in ch["growth_rows"]],
                        "cur": [r["cur"] for r in ch["growth_rows"]]}
        change_dist_chart = {"names": [r["name"] for r in ch["d_rows"]],
                             "t": [r["g_t"] for r in ch["d_rows"]],
                             "k": [r["g_k"] for r in ch["d_rows"]],
                             "o": [r["g_o"] for r in ch["d_rows"]]}

    # KPIs.
    dep = nat["dep_y"] + nat["dep_o"]
    kpis = {
        "total": {"value": nat["total"], "display": n(nat["total"]), "tone": "brand"},
        "localities": {"value": n_loc, "display": n(n_loc), "tone": "brand"},
        "kids": {"value": r1(nat["kid_s"]), "display": f"{nat['kid_s']:.1f}%", "tone": "info"},
        "old": {"value": r1(nat["old_s"]), "display": f"{nat['old_s']:.1f}%", "tone": "info"},
        "dep": {"value": r1(dep), "display": f"{dep:.1f}", "tone": "brand"},
    }
    if ch:
        g = ch["g_total"]
        gr = round(g, 1)
        kpis["growth"] = {"value": gr,
                          "display": ("0.0%" if gr == 0 else f"{'+' if gr > 0 else MINUS}{abs(gr):.1f}%"),
                          "tone": "ok" if gr > 0 else ("danger" if gr < 0 else "brand")}

    insights = []
    for iid, txt in [
        ("structure", insight_structure(nat, lab)),
        ("density", insight_density(dens)),
        ("district", insight_district(dist_rows)),
        ("cities", insight_cities(cities)),
        ("oldest", insight_oldest(oldest, len(big))),
        ("youngest", insight_youngest(youngest)),
        ("size", insight_size(size_rows)),
        ("aging", insight_aging(ch)),
        ("growth", insight_growth(ch["growth_rows"], ch["abs_top"]) if ch else None),
        ("placeholder", insight_placeholder(ph, lab)),
    ]:
        if txt:
            insights.append({"id": iid, "text_he": txt})

    ph_t = (f" שורת ״לא רשום״ ({n(ph['total'])} תושבים ללא ישוב) אינה נכללת בנתוני הישובים." if ph else "")
    bad_t = (f" {n(n_bad)} שורות עם ערך חסר או לא תקין הושמטו." if n_bad else "")
    first_d, mid_d = (dens[0], max(dens[1:], key=lambda r: (r["width"], -r["i"]))) if len(dens) >= 2 else (None, None)
    young_d = sorted(dist_rows, key=lambda r: (-r["kid_v"], D_IDX[r["name"]]))[0] if dist_rows else None
    old_d = sorted(dist_rows, key=lambda r: (-r["old_v"], D_IDX[r["name"]]))[0] if dist_rows else None
    top_nafa = nafa_rows[0] if nafa_rows else None
    low_nafa = nafa_rows[-1] if nafa_rows else None
    c_hi = cities_sorted[0] if cities_sorted else None
    c_lo = cities_sorted[-1] if cities_sorted else None

    arch_t = ", ואת השינוי מאז קובץ הארכיון של המאגר" if ch else ""
    labels = {
        "lede": (f"רשות האוכלוסין וההגירה מפרסמת, לכל ישוב במרשם האוכלוסין, את מספר התושבים הרשומים "
                 f"בשש קבוצות גיל. ברשימה {n(n_loc)} ישובים עם {n(nat['total'])} תושבים: "
                 f"{pct(nat['kid_s'])} בני 18 ומטה ו-{pct(nat['old_s'])} בני 65 ומעלה. העמוד מציג את "
                 f"מבנה הגילים במחוזות, בנפות ובערים הגדולות, את הישובים המבוגרים והצעירים ביותר ואת "
                 f"יחס התלות{arch_t}. המרשם כולל גם תושבים השוהים "
                 f"בחו״ל, ולכן המספרים שונים מאומדני הלשכה המרכזית לסטטיסטיקה.{ph_t}{bad_t}"),
        "total_kpi": "תושבים רשומים בישובים",
        "localities_kpi": "ישובים ברשימה",
        "kids_kpi": f"בני 18 ומטה (אחוז מהתושבים)",
        "old_kpi": f"בני {lab['old_band']} (אחוז מהתושבים)",
        "dep_kpi": f"יחס תלות: צעירים ומבוגרים לכל 100 בני {lab['work_band']}",
        "growth_kpi": "שינוי במספר התושבים מאז קובץ הארכיון",
        "struct_note": ((f"מספר התושבים בכל קבוצת גיל. הקבוצות ברוחב שונה, ולכן הקו מראה את הממוצע לכל "
                         f"שנת גיל: בטווח {first_d['label']} — {n(first_d['per_year'])} לשנה, ובטווח "
                         f"{mid_d['label']} — {n(mid_d['per_year'])} לשנה. לקבוצה הפתוחה "
                         f"({lab['old_band']}) אין ממוצע לשנה.") if first_d else
                        "מספר התושבים בכל קבוצת גיל."),
        "struct_aria": (f"גרף עמודות: תושבים לפי קבוצת גיל. הקבוצה הגדולה היא "
                        f"{band_labels[max(range(len(BANDS)), key=lambda i: (nat['bands'][i], -i))]}."),
        "struct_caption": "תושבים לפי קבוצת גיל",
        "dist_note": ((f"הרכב הגילים בכל מחוז (המחוז נגזר מסמל הנפה). מחוז {young_d['name']} הצעיר ביותר "
                       f"({pct(young_d['kid_v'])} בני 18 ומטה), ומחוז {old_d['name']} המבוגר ביותר "
                       f"({pct(old_d['old_v'])} בני 65 ומעלה).") if young_d else ""),
        "dist_aria": "גרף עמודות מוערמות אופקי: התפלגות קבוצות הגיל בכל מחוז, באחוזים.",
        "dist_caption": "הרכב הגילים לפי מחוז",
        "nafa_note": ((f"יחס התלות בכל אחת מ-{n(len(nafa_rows))} הנפות: מספר בני 18 ומטה ובני 65 ומעלה "
                       f"לכל 100 בני {lab['work_band']}. בנפת {top_nafa['name']} היחס הגבוה ביותר "
                       f"({top_nafa['dep']}), ובנפת {low_nafa['name']} הנמוך ביותר ({low_nafa['dep']}). "
                       f"הקו המקווקו הוא היחס בכל הישובים ({dep:.1f}).") if nafa_rows else ""),
        "nafa_aria": (f"גרף עמודות מוערמות אופקי: יחס התלות של צעירים ומבוגרים בכל אחת מ-"
                      f"{n(len(nafa_rows))} הנפות."),
        "nafa_caption": "יחס התלות לפי נפה",
        "oldest_note": (f"שיעור בני 65 ומעלה, מבין {n(len(big))} הישובים שבהם {n(MIN_POP_RANK)} תושבים "
                        f"ומעלה. הקו המקווקו: השיעור בכל הישובים ({pct(nat['old_s'])})."),
        "oldest_aria": ("גרף עמודות אופקי: הישובים עם השיעור הגבוה ביותר של בני 65 ומעלה."
                        + (f" {oldest[0]['name']} מוביל עם {pct(oldest[0]['old_v'])}." if oldest else "")),
        "oldest_caption": "הישובים עם השיעור הגבוה ביותר של בני 65 ומעלה",
        "youngest_note": (f"שיעור בני 18 ומטה באותה קבוצת ישובים ({n(MIN_POP_RANK)} תושבים ומעלה). הקו "
                          f"המקווקו: השיעור בכל הישובים ({pct(nat['kid_s'])})."),
        "youngest_aria": ("גרף עמודות אופקי: הישובים עם השיעור הגבוה ביותר של ילדים ובני נוער."
                          + (f" {youngest[0]['name']} מוביל עם {pct(youngest[0]['kid_v'])}." if youngest else "")),
        "youngest_caption": "הישובים עם השיעור הגבוה ביותר של בני 18 ומטה",
        "cities_note": ((f"הרכב הגילים ב-{n(len(cities))} הישובים הגדולים, מהצעיר למבוגר (לפי שיעור בני 18 "
                         f"ומטה): מ{c_hi['name']} ({pct(c_hi['kid_v'])}) ועד {c_lo['name']} "
                         f"({pct(c_lo['kid_v'])}).") if cities else ""),
        "cities_aria": f"גרף עמודות מוערמות אופקי: הרכב הגילים ב-{n(len(cities))} הישובים הגדולים.",
        "cities_caption": "הרכב הגילים בישובים הגדולים",
        "size_note": ("שיעור בני 18 ומטה ובני 65 ומעלה לפי גודל הישוב (מספר התושבים)."),
        "size_aria": "גרף עמודות: שיעור הילדים והמבוגרים לפי גודל הישוב.",
        "size_caption": "הרכב הגילים לפי גודל הישוב",
        "council_note": ((f"ישובי {n(n_councils)} המועצות האזוריות לעומת שאר הישובים (ערים, מועצות מקומיות "
                          f"וישובים שאינם במועצה)."
                          + (f" המועצה המבוגרת ביותר היא {c_old['name']} ({pct(c_old['old_v'])} בני 65 ומעלה), "
                             f"והצעירה ביותר {c_young['name']} ({pct(c_young['kid_v'])} בני 18 ומטה)."
                             if c_old and c_young else "")) if council_rows else ""),
        "council_aria": "גרף עמודות מוערמות אופקי: הרכב הגילים בישובי המועצות האזוריות לעומת שאר הישובים.",
        "council_caption": "הרכב הגילים: מועצות אזוריות ושאר הישובים",
        "scatter_note": (f"כל נקודה היא ישוב ({n(n_scatter)} הישובים שבהם {n(MIN_POP_SCATTER)} תושבים "
                         f"ומעלה), צבועה לפי מחוז: שיעור בני 18 ומטה מול שיעור בני 65 ומעלה. ישובים "
                         f"צעירים בצד אחד, מבוגרים בצד השני. לחיצה על מחוז במקרא מסתירה אותו."),
        "scatter_aria": f"תרשים פיזור: שיעור הילדים מול שיעור המבוגרים ב-{n(n_scatter)} ישובים.",
    }
    if ch:
        lr0 = ch["band_rows"][0]
        labels.update({
            "change_lede": (f"השוואה לקובץ הארכיון המוקדם ביותר במאגר (הקובץ עם הסך הנמוך ביותר מבין "
                            f"קובצי המבנה הישן): {n(ch['base_total'])} תושבים בישובים אז, "
                            f"{n(ch['cur_total'])} היום ({signed_pct(ch['g_total'])}). "
                            + (f"בקובץ הישן קבוצת הגיל הראשונה מסומנת {lr0['label_old']} (ובקובץ הנוכחי "
                               f"{lr0['label']}); הקבוצות מחלקות את הסך בשני הקבצים. " if ch["label_diff"] else "")
                            + (f"{n(ch['n_new'])} סמלי ישוב חדשים ({n(ch['new_pop'])} תושבים) מופיעים רק "
                               f"בקובץ הנוכחי, בין היתר ישובים שנפרדו מישוב קיים." if ch["n_new"] else "")),
            "cb_note": (f"מספר התושבים בכל קבוצת גיל בקובץ הארכיון ובקובץ הנוכחי. מספר בני 65 ומעלה השתנה "
                        f"ב-{signed_pct(ch['g_old'])}, לעומת {signed_pct(ch['g_total'])} בכלל התושבים."),
            "cb_aria": "גרף עמודות: תושבים לפי קבוצת גיל בקובץ הארכיון ובקובץ הנוכחי.",
            "cb_caption": "תושבים לפי קבוצת גיל — קובץ הארכיון מול הקובץ הנוכחי",
            "cd_note": "השינוי באחוזים בכל מחוז: בכלל התושבים, בבני 18 ומטה ובבני 65 ומעלה.",
            "cd_aria": "גרף עמודות: שינוי באחוזים במספר התושבים לפי מחוז וקבוצת גיל.",
            "cd_caption": "השינוי לפי מחוז מאז קובץ הארכיון",
            "gr_note": (f"הישובים שגדלו בשיעור הגבוה ביותר, מבין {n(ch['n_elig'])} הישובים שהיו בהם "
                        f"{n(MIN_BASE_GROWTH)} תושבים ומעלה בקובץ הארכיון (התאמה לפי סמל ישוב). שינוי חד "
                        f"יכול לנבוע גם משינוי גבולות או מפיצול ישוב."),
            "gr_aria": ("גרף עמודות אופקי: הישובים שגדלו בשיעור הגבוה ביותר מאז קובץ הארכיון."
                        + (f" {ch['growth_rows'][0]['name']} מוביל." if ch["growth_rows"] else "")),
            "gr_caption": "הישובים שגדלו בשיעור הגבוה ביותר",
        })

    agent_data = {
        "summary_he": (f"מבנה הגילים של {n(nat['total'])} התושבים הרשומים ב-{n(n_loc)} ישובים לפי מרשם "
                       f"האוכלוסין: {pct(nat['kid_s'])} בני 18 ומטה, {pct(nat['old_s'])} בני 65 ומעלה, "
                       f"והשוואה בין מחוזות, נפות, ערים וגודלי ישוב"
                       + (f", ושינוי של {signed_pct(ch['g_total'])} מאז קובץ הארכיון." if ch else ".")),
        "dataset_kind": "rankings",
        "suggested_tags": ["אוכלוסייה", "קבוצות גיל", "דמוגרפיה", "ישובים", "מרשם האוכלוסין",
                           "יחס תלות", "קשישים"],
        "related_ids": [
            "9d86c8a9-9240-4fc4-86a3-834c539f9488",
            "3fc54b81-25b3-4ac7-87db-248c3e1602de",
            "d2581732-eca4-4988-b986-df8e791a1d60",
            "785ad9fb-6da6-426d-b5ea-b8e36febbc8a",
        ],
        "spatial_coverage": "ישראל ויהודה והשומרון",
    }

    return {
        "agent_data": agent_data,
        "kpis": kpis,
        "charts": {
            "struct": struct_chart,
            "districts": dist_chart,
            "nafot": nafa_chart,
            "oldest": ext_chart(oldest, "old_v"),
            "youngest": ext_chart(youngest, "kid_v"),
            "nat_old": r1(nat["old_s"]),
            "nat_kid": r1(nat["kid_s"]),
            "cities": cities_chart,
            "size": size_chart,
            "council": council_chart,
            "scatter": scatter,
            "change_bands": change_bands_chart,
            "change_dist": change_dist_chart,
            "growth": growth_chart,
        },
        "insights": insights,
        "labels": labels,
        "tables": {
            "struct": struct_rows,
            "districts": dist_rows,
            "nafot": nafa_rows,
            "oldest": oldest,
            "youngest": youngest,
            "cities": cities_sorted,
            "size": size_rows,
            "council": council_rows,
            "change_bands": ch["band_rows"] if ch else [],
            "change_dist": ch["d_rows"] if ch else [],
            "growth": ch["growth_rows"] if ch else [],
        },
        "bands": band_labels,
        "flags": {
            "extremes": len(oldest) >= 3 and len(youngest) >= 3,
            "council": bool(council_rows),
            "scatter": bool(scatter),
            "change": bool(ch),
            "growth": bool(ch and ch["growth_rows"]),
        },
    }
