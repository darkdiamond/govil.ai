"""תוצרים ודגמים של כלי רכב פרטי ומסחרי — the Ministry of Transport model catalogue.

Two distinct tables, one row per (sug_degem, tozeret_cd, degem_cd, shnat_yitzur):
  specs  — technical specification, safety equipment and emissions per model-year;
  counts — how many vehicles of that model-year are active / no longer active.
They are joined 1:1 on that key, so every figure on the page is weighted by the
number of ACTIVE vehicles (the fleet), not by the number of catalogue rows —
except where a label says "צירופי דגם".

"Latest" means the latest model year in the data. The newest model year keeps
filling while it is on sale, so trend rules use `ref_year`: the latest model
year whose active count reaches REF_MIN_SHARE of the busiest model year.
"""
import math

import pandas as pd

KEY = ["sug_degem", "tozeret_cd", "degem_cd", "shnat_yitzur"]
REF_MIN_SHARE = 0.25
WINDOW = 20          # model years shown in the share-by-year charts
HEAT_WINDOW = 15     # model years in the equipment heatmap
TREND_GAP = 5        # "now vs N model years earlier"
MIN_YEAR_N = 1000    # min vehicles with a value for a per-year median
MIN_COV = 0.25       # CO2 series: share of the year's vehicles that must carry a value
TOP_MAKES = 15
TOP_MODELS = 15
TOP_EV = 10
TOP_BODY = 8
TOP_COUNTRIES = 8
LRI, PDI = "⁦", "⁩"
MINUS = "−"

PT_ORDER = ["בנזין", "דיזל", "היברידי", "פלאג-אין", "חשמלי", "אחר / לא ידוע"]
ELECTRIFIED = ["היברידי", "פלאג-אין", "חשמלי"]
COUNTRY_FIX = {'ארהב"': "ארה״ב", "": "לא ידוע"}
# Blank tozeret_eretz_nm: the plant's country is often the suffix of tozeret_nm
# ("קיה ד. קוריאה", "טויוטה ד. אפרי"). Known suffixes only; the rest stay "לא ידוע".
COUNTRY_FROM_NAME = [("קוריאה", "קוריאה הדרומית"), ("ד. אפר", "דרום אפריקה"), ("ד.אפ", "דרום אפריקה")]


def _country(country, maker_nm):
    if country == "":
        for frag, name in COUNTRY_FROM_NAME:
            if frag in maker_nm:
                return name
    return COUNTRY_FIX.get(country, country)

ADAS = [
    ("bakarat_yatzivut_ind", "בקרת יציבות"),
    ("maarechet_ezer_labalam_ind", "מערכת עזר לבלימה"),
    ("hayshaney_lahatz_avir_batzmigim_ind", "חיישני לחץ אוויר בצמיגים"),
    ("hayshaney_hagorot_ind", "חיישני חגורות בטיחות"),
    ("teura_automatit_benesiya_kadima_ind", "אורות נסיעה אוטומטיים"),
    ("nitur_merhak_milfanim_ind", "ניטור מרחק מלפנים"),
    ("bakarat_stiya_menativ_ind", "התרעת סטייה מנתיב"),
    ("zihuy_holchey_regel_ind", "זיהוי הולכי רגל"),
    ("zihuy_matzav_hitkarvut_mesukenet_ind", "זיהוי התקרבות מסוכנת"),
    ("matzlemat_reverse_ind", "מצלמת רוורס"),
    ("zihuy_rechev_do_galgali", "זיהוי רכב דו־גלגלי"),
    ("zihuy_tamrurey_tnua_ind", "זיהוי תמרורים"),
    ("shlita_automatit_beorot_gvohim_ind", "אור גבוה אוטומטי"),
    ("bakarat_shyut_adaptivit_ind", "בקרת שיוט אדפטיבית"),
    ("zihuy_beshetah_nistar_ind", "זיהוי רכב בשטח מת"),
    ("bakarat_stiya_activ_s", "שמירת נתיב אקטיבית"),
    ("blimat_hirum_lifnei_holhei_regel_ofanaim", "בלימת חירום (הולכי רגל)"),
    ("blima_otomatit_nesia_leahor", "בלימה אוטומטית ברוורס"),
    ("bakarat_mehirut_isa", "בקרת מהירות חכמה"),
    ("hitnagshut_cad_shetah_met", "מניעת התנגשות צד"),
    ("alco_lock", "הכנה למנעול אלכוהול"),
]
LOCAL_SRC = [
    ("bakarat_stiya_menativ_makor_hatkana", "התרעת סטייה מנתיב"),
    ("nitur_merhak_milfanim_makor_hatkana", "ניטור מרחק מלפנים"),
    ("zihuy_holchey_regel_makor_hatkana", "זיהוי הולכי רגל"),
    ("zihuy_tamrurey_tnua_makor_hatkana", "זיהוי תמרורים"),
    ("shlita_automatit_beorot_gvohim_makor_hatkana", "אור גבוה אוטומטי"),
]
COMFORT = [
    ("automatic_ind", "תיבת הילוכים אוטומטית"),
    ("galgaley_sagsoget_kala_ind", "גלגלי סגסוגת קלה"),
    ("halon_bagg_ind", "חלון בגג"),
]
SPECS = [
    ("koah_sus", "hp", "כוח סוס"),
    ("mishkal_kolel", "weight", "משקל כולל (ק״ג)"),
    ("nefah_manoa", "cc", "נפח מנוע (סמ״ק)"),
    ("mispar_kariot_avir", "airbags", "כריות אוויר"),
]
ZIHUM_BINS = [(1, 3, "קבוצות 1 עד 3 (הנקיות)"), (4, 9, "קבוצות 4 עד 9"),
              (10, 14, "קבוצות 10 עד 14"), (15, 15, "קבוצה 15 (המזהמת)")]


def n(v):
    return f"{int(round(v)):,}"


def pct(v, digits=1):
    return f"{LRI}{v:.{digits}f}%{PDI}"


def pts(v):
    return f"{LRI}{abs(v):.1f}{PDI} נקודות אחוז"


def _num(s):
    return pd.to_numeric(s.str.replace(",", "", regex=False).str.strip(), errors="coerce")


def _powertrain(tech, fuel):
    if tech == "רכב חשמלי" or fuel == "חשמל":
        return "חשמלי"
    if tech == "PLUG IN":
        return "פלאג-אין"
    if tech == "היברידי רגיל":
        return "היברידי"
    if fuel == "בנזין":
        return "בנזין"
    if fuel == "דיזל":
        return "דיזל"
    return "אחר / לא ידוע"


def _prepare(specs, counts):
    s = specs.copy()
    for c in KEY:
        s[c] = s[c].str.strip()
    c = counts[KEY].copy()
    for k in KEY:
        c[k] = c[k].str.strip()
    c["act"] = _num(counts["mispar_rechavim_pailim"]).fillna(0)
    c["inact"] = _num(counts["mispar_rechavim_le_pailim"]).fillna(0)
    c = c.groupby(KEY, as_index=False)[["act", "inact"]].sum()
    unmatched = int(c.merge(s[KEY], on=KEY, how="left", indicator=True)["_merge"]
                     .eq("left_only").sum())
    df = s.merge(c, on=KEY, how="left")
    df["act"] = df["act"].fillna(0).astype(int)
    df["inact"] = df["inact"].fillna(0).astype(int)
    df["yr"] = _num(df["shnat_yitzur"])
    df = df[df["yr"].between(1900, 2100)].copy()
    df["yr"] = df["yr"].astype(int)
    df["make"] = df["tozar"].str.strip().replace("", "לא ידוע")
    df["model"] = df["kinuy_mishari"].str.strip()
    df["country"] = [_country(c, t) for c, t in zip(df["tozeret_eretz_nm"].str.strip(),
                                                    df["tozeret_nm"].str.strip())]
    pairs = df[["technologiat_hanaa_nm", "delek_nm"]].apply(lambda col: col.str.strip())
    df["pt"] = [_powertrain(t, f) for t, f in zip(pairs["technologiat_hanaa_nm"], pairs["delek_nm"])]
    df["body"] = df["merkav"].str.strip().replace("", "לא ידוע")
    return df, unmatched


def _wmed_by_year(df, values, mask, years, min_n=0, base=None, min_cov=0.0):
    """Per-model-year weighted median of `values` over rows in `mask` — one groupby.

    With `base` (a row mask), a year is kept only when the vehicles with a value
    are at least `min_cov` of the vehicles in `base` for that year."""
    d = pd.DataFrame({"yr": df["yr"], "v": values, "w": df["act"]})[mask]
    d = d.dropna(subset=["v"])
    d = d[d["w"] > 0]
    g = d.groupby(["yr", "v"])["w"].sum()
    den = df.loc[base, ["yr", "act"]].groupby("yr")["act"].sum() if base is not None else None
    out = {}
    for y, sub in g.groupby(level=0):
        sub = sub.droplevel(0).sort_index()
        if sub.sum() < min_n or sub.sum() == 0:
            continue
        if den is not None and sub.sum() < min_cov * den.get(y, 0):
            continue
        cum = sub.cumsum()
        out[int(y)] = float(sub.index[cum >= cum.iloc[-1] / 2][0])
    return [out.get(y) for y in years]


def _wmean_by_year(df, values, mask, years, min_n=0):
    """Per-model-year vehicle-weighted mean (fsum over sorted products — order-free)."""
    d = pd.DataFrame({"yr": df["yr"], "v": values, "w": df["act"]})[mask].dropna(subset=["v"])
    d = d[d["w"] > 0]
    d["x"] = d["v"] * d["w"]
    out = {}
    for y, g in d.groupby("yr"):
        w = int(g["w"].sum())
        if w >= max(min_n, 1):
            out[int(y)] = round(math.fsum(sorted(g["x"])) / w, 1)
    return [out.get(y) for y in years]


def _share_by_year(df, mask, years):
    num = df.loc[mask, ["yr", "act"]].groupby("yr")["act"].sum()
    den = df.groupby("yr")["act"].sum()
    out = []
    for y in years:
        d = den.get(y, 0)
        out.append(None if d == 0 else round(float(num.get(y, 0) / d * 100), 1))
    return out


def _top(counts, k):
    counts = counts.sort_index().sort_values(ascending=False, kind="stable")
    top = counts.head(k)
    other = int(counts.iloc[k:].sum())
    names = list(top.index) + (["אחר"] if other else [])
    vals = [int(v) for v in top.values] + ([other] if other else [])
    return names, vals


def _signed_pts(v):
    if round(v, 1) == 0:
        return "ללא שינוי"
    return ("עלייה של " if v > 0 else "ירידה של ") + pts(v)


# ---------------------------------------------------------------- insights

def insight_electrified(mix, ref, base):
    if ref not in mix or base not in mix:
        return None
    e1 = sum(mix[ref].get(p, 0) for p in ELECTRIFIED)
    e0 = sum(mix[base].get(p, 0) for p in ELECTRIFIED)
    d1, d0 = mix[ref].get("דיזל", 0), mix[base].get("דיזל", 0)
    if abs(e1 - e0) < 3:
        s = (f"שיעור כלי הרכב המחושמלים (היברידי, פלאג-אין או חשמלי) נותר דומה: "
             f"{pct(e0)} משנת ייצור {base} ו-{pct(e1)} משנת ייצור {ref}.")
    else:
        word = "עלה" if e1 > e0 else "ירד"
        s = (f"שיעור כלי הרכב המחושמלים (היברידי, פלאג-אין או חשמלי) מבין הפעילים {word} "
             f"מ-{pct(e0)} בשנת ייצור {base} ל-{pct(e1)} בשנת ייצור {ref}.")
    if abs(d1 - d0) >= 1:
        s += (f" חלקו של הדיזל {'ירד' if d1 < d0 else 'עלה'} באותה תקופה "
              f"מ-{pct(d0)} ל-{pct(d1)}.")
    return s


def insight_ev(mix, ref, years):
    ev = {y: mix[y].get("חשמלי", 0) for y in years if y <= ref and y in mix}
    if not ev or max(ev.values()) < 2:
        return None
    peak = max(sorted(ev), key=lambda y: (ev[y], -y))
    cur, ph = ev[ref], mix[ref].get("פלאג-אין", 0)
    if peak == ref:
        return (f"שנת ייצור {ref} היא שנת השיא של רכב חשמלי מלא: {pct(cur)} מכלי הרכב "
                f"הפעילים מאותה שנה, ועוד {pct(ph)} פלאג-אין.")
    if ev[peak] - cur < 3:
        return (f"שיעור הרכב החשמלי המלא יציב יחסית: {pct(cur)} בשנת ייצור {ref}, "
                f"לעומת שיא של {pct(ev[peak])} ב-{peak}.")
    s = (f"שיעור הרכב החשמלי המלא הגיע לשיא של {pct(ev[peak])} בשנת ייצור {peak} "
         f"וירד ל-{pct(cur)} בשנת ייצור {ref}")
    ph0 = mix[peak].get("פלאג-אין", 0)
    if ph - ph0 >= 3:
        s += f", בעוד שיעור הפלאג-אין עלה מ-{pct(ph0)} ל-{pct(ph)}"
    return s + "."


def insight_china(origin_share, ref, base):
    if ref not in origin_share or base not in origin_share:
        return None
    sh = origin_share[ref]
    if not sh:
        return None
    lead = max(sorted(sh), key=lambda c: sh[c])
    c1, c0 = sh.get("סין", 0.0), origin_share[base].get("סין", 0.0)
    if lead == "סין" and c1 - c0 >= 5:
        return (f"סין היא ארץ הייצור המובילה של כלי רכב משנת ייצור {ref}: {pct(c1)} מהפעילים, "
                f"לעומת {pct(c0)} בשנת ייצור {base}.")
    if lead == "לא ידוע":
        return None
    return (f"ארץ הייצור המובילה בשנת ייצור {ref} היא {lead} ({pct(sh[lead])} מכלי הרכב הפעילים); "
            f"חלקה של סין: {pct(c1)}.")


def insight_leader(makes, models_top, total):
    if total == 0 or makes.empty:
        return None
    name, v = makes.index[0], makes.iloc[0]
    if v / total < 0.05:
        return None
    top3 = makes.head(3).sum() / total
    s = (f"{name} היא התוצר הנפוץ ביותר בצי הפעיל ({n(v)} כלי רכב, {pct(v / total * 100)}); "
         f"שלושת התוצרים הגדולים מחזיקים יחד {pct(top3 * 100)}.")
    if models_top:
        m = models_top[0]
        s += f" הדגם הנפוץ ביותר: {m['make']} {m['model']} ({n(m['n'])})."
    return s


def insight_survival(surv, ref):
    ys = sorted(y for y in surv if y <= ref)
    if len(ys) < 12:
        return None
    half = None
    for y in reversed(ys):        # earliest year from which EVERY later year is >= 50%
        if surv[y] < 50:
            break
        half = y
    old = ref - 15
    if half is None or old not in surv:
        return None
    return (f"מכלי הרכב משנת ייצור {old} עדיין פעילים {pct(surv[old])}; "
            f"החל משנת ייצור {half} רוב כלי הרכב של כל שנת ייצור עדיין על הכביש.")


def insight_local(local, years_local):
    best = None
    for name, ser in local.items():
        vals = {y: v for y, v in zip(years_local, ser) if v is not None}
        if not vals:
            continue
        pk = max(sorted(vals), key=lambda y: (vals[y], -y))
        last = max(vals)
        if vals[pk] >= 50 and vals[last] < 10 and (best is None or vals[pk] > best[2]):
            best = (name, pk, vals[pk], last, vals[last])
    if best is None:
        return None
    name, pk, v, last, lv = best
    return (f"בשנים הראשונות של מערכות הבטיחות המתקדמות הן הותקנו ברובן בישראל לאחר הייבוא: "
            f"ב-{pct(v)} מכלי הרכב משנת ייצור {pk} שיש בהם {name}, המערכת הותקנה מקומית — "
            f"לעומת {pct(lv)} בשנת ייצור {last}, שבה היא כבר מותקנת בידי היצרן.")


def insight_adas(adas_ref, ref, base_vals, base):
    if not adas_ref:
        return None
    std = [k for k, v in adas_ref.items() if v is not None and v >= 95]
    rare = min(sorted(adas_ref), key=lambda k: (adas_ref[k] if adas_ref[k] is not None else 999))
    s = f"{len(std)} מתוך {len(adas_ref)} מערכות הבטיחות במאגר קיימות ב-95% לפחות מכלי הרכב משנת ייצור {ref}"
    gains = [(k, adas_ref[k] - base_vals[k]) for k in adas_ref
             if adas_ref[k] is not None and base_vals.get(k) is not None]
    if gains:
        k, g = max(sorted(gains), key=lambda t: t[1])
        if g >= 20:
            s += (f"; הקפיצה הגדולה מאז {base}: {k}, מ-{pct(base_vals[k])} ל-{pct(adas_ref[k])}")
    if adas_ref[rare] is not None and adas_ref[rare] < 80:
        s += f". הפחות נפוצה: {rare} ({pct(adas_ref[rare])})"
    return s + "."


def insight_heavier(spec_med, years, ref, base):
    w = dict(zip(years, spec_med["weight"]))
    hp = dict(zip(years, spec_med["hp"]))
    if w.get(ref) is None or w.get(base) is None or w[base] == 0:
        return None
    ch = w[ref] / w[base] - 1
    if abs(ch) < 0.05:
        return None
    s = (f"כלי הרכב {'כבדים' if ch > 0 else 'קלים'} יותר: המשקל הכולל הממוצע "
         f"{'עלה' if ch > 0 else 'ירד'} מ-{n(w[base])} ק״ג בשנת ייצור {base} "
         f"ל-{n(w[ref])} ק״ג בשנת ייצור {ref} ({pct(abs(ch) * 100)})")
    if hp.get(ref) is not None and hp.get(base) is not None:
        s += f", וכוח הסוס הממוצע — מ-{n(hp[base])} ל-{n(hp[ref])}"
    return s + "."


# ---------------------------------------------------------------- compute

def compute(frames):
    df, unmatched = _prepare(frames["specs"], frames["counts"])
    total = int(df["act"].sum())
    inactive = int(df["inact"].sum())
    by_year = df.groupby("yr")["act"].sum().sort_index()
    all_years = [int(y) for y in by_year.index]
    y_max = all_years[-1]
    big = by_year.max()
    ref = max(y for y in all_years if by_year[y] >= big * REF_MIN_SHARE)
    base = ref - TREND_GAP
    win = [y for y in all_years if y > y_max - WINDOW]

    # --- powertrain mix by model year
    pt_y = df.groupby(["yr", "pt"])["act"].sum().unstack(fill_value=0)
    pts_present = [p for p in PT_ORDER if p in pt_y.columns and pt_y[p].sum() > 0]
    mix = {}
    for y in pt_y.index:
        row = pt_y.loc[y]
        tot = row.sum()
        mix[int(y)] = {p: (float(row[p] / tot * 100) if tot else 0.0) for p in pts_present}
    fleet_year = {"x": [str(y) for y in all_years],
                  "series": [{"name": p, "data": [int(pt_y.loc[y, p]) if y in pt_y.index else 0
                                                  for y in all_years]} for p in pts_present]}
    mix_chart = {"x": [str(y) for y in win],
                 "series": [{"name": p, "data": [round(mix[y][p], 1) if y in mix else 0
                                                 for y in win]} for p in pts_present]}

    pt_tot = df.groupby("pt")["act"].sum()
    elec_fleet = float(sum(pt_tot.get(p, 0) for p in ELECTRIFIED) / total * 100) if total else 0.0
    ev_fleet = float(pt_tot.get("חשמלי", 0) / total * 100) if total else 0.0
    ev_ref = mix.get(ref, {}).get("חשמלי", 0.0)

    # --- country of manufacture by model year
    cy = df.groupby(["yr", "country"])["act"].sum().unstack(fill_value=0)
    recent = df[df["yr"] > ref - TREND_GAP].groupby("country")["act"].sum()
    recent = recent.drop("לא ידוע", errors="ignore").sort_index().sort_values(
        ascending=False, kind="stable")
    top_c = list(recent.head(TOP_COUNTRIES).index)
    origin_share = {}
    for y in cy.index:
        row = cy.loc[y]
        tot = row.sum()
        origin_share[int(y)] = {c: float(row[c] / tot * 100) for c in cy.columns if tot}
    origin_chart = {"x": [str(y) for y in win], "series": []}
    for c in top_c:
        origin_chart["series"].append({"name": c, "data": [round(origin_share.get(y, {}).get(c, 0.0), 1)
                                                           for y in win]})
    origin_chart["series"].append({"name": "אחר / לא ידוע", "data": [
        round(100 - sum(origin_share.get(y, {}).get(c, 0.0) for c in top_c), 1) if y in origin_share else 0
        for y in win]})
    china_ref = origin_share.get(ref, {}).get("סין", 0.0)

    # --- makes / models / EV makes
    makes = df.groupby("make")["act"].sum()
    makes = makes[makes > 0].sort_index().sort_values(ascending=False, kind="stable")
    top_makes = list(makes.head(TOP_MAKES).index)
    mk_pt = df[df["make"].isin(top_makes)].groupby(["make", "pt"])["act"].sum().unstack(fill_value=0)
    makes_chart = {"names": top_makes,
                   "series": [{"name": p, "data": [int(mk_pt.loc[m, p]) if p in mk_pt.columns else 0
                                                   for m in top_makes]} for p in pts_present]}
    elec_by_make = {m: (sum(int(mk_pt.loc[m, p]) for p in ELECTRIFIED if p in mk_pt.columns)
                        / makes[m] * 100) for m in top_makes}

    mdl = (df[df["model"] != ""].groupby(["make", "model"])["act"].sum().reset_index(name="n"))
    mdl = mdl[mdl["n"] > 0].sort_values(["n", "make", "model"], ascending=[False, True, True])
    models_top = [{"make": r.make, "model": r.model, "n": int(r.n)}
                  for r in mdl.head(TOP_MODELS).itertuples()]
    models_chart = {"names": [f"{m['make']} {m['model']}" for m in models_top][::1],
                    "values": [m["n"] for m in models_top]}

    ev = df[df["pt"] == "חשמלי"].groupby("make")["act"].sum()
    ev = ev[ev > 0]
    ev_total = int(ev.sum())
    ev_names, ev_vals = _top(ev, TOP_EV)
    ev_ref_df = df[(df["pt"] == "חשמלי") & (df["yr"] == ref)].groupby("make")["act"].sum()

    # --- survival (share of each model year still active)
    yi = df.groupby("yr")[["act", "inact"]].sum()
    surv = {int(y): float(r.act / (r.act + r.inact) * 100) for y, r in yi.iterrows()
            if (r.act + r.inact) > 0}
    survival_chart = {"x": [str(y) for y in all_years],
                      "share": [round(surv[y], 1) if y in surv else None for y in all_years],
                      "inactive": [int(yi.loc[y, "inact"]) for y in all_years]}

    # --- safety equipment heatmap (vehicle-weighted share per model year)
    heat_years = [y for y in all_years if y > y_max - HEAT_WINDOW]
    cells, adas_ref, adas_base = [], {}, {}
    for yi_, (col, label) in enumerate(ADAS):
        flag = df[col].str.strip() == "1"
        ser = _share_by_year(df, flag, heat_years)
        for xi, v in enumerate(ser):
            cells.append([xi, yi_, v if v is not None else 0])
        rb = _share_by_year(df, flag, [ref, base])
        adas_ref[label], adas_base[label] = rb[0], rb[1]
    heat = {"x": [str(y) for y in heat_years], "y": [lbl for _, lbl in ADAS], "cells": cells}

    # --- local (aftermarket) installation share among equipped vehicles
    loc_years = [y for y in all_years if y > y_max - HEAT_WINDOW]
    local = {}
    for col, label in LOCAL_SRC:
        src = df[col].str.strip()
        has = src != ""
        num = df[has & (src == "מקומי")].groupby("yr")["act"].sum()
        den = df[has].groupby("yr")["act"].sum()
        ser = [round(float(num.get(y, 0) / den[y] * 100), 1) if den.get(y, 0) >= MIN_YEAR_N else None
               for y in loc_years]
        if max((v for v in ser if v is not None), default=0) >= 5:
            local[label] = ser
    local_chart = {"x": [str(y) for y in loc_years],
                   "series": [{"name": k, "data": v} for k, v in local.items()]}

    # --- safety equipment level (1..8), among rated vehicles
    lvl = _num(df["ramat_eivzur_betihuty"])
    rated = df.assign(l=lvl).dropna(subset=["l"])
    rated = rated[rated["l"].between(0, 8)]
    rated["l"] = rated["l"].astype(int)
    lv = rated.groupby(["yr", "l"])["act"].sum().unstack(fill_value=0)
    cov = (rated.groupby("yr")["act"].sum() / by_year).fillna(0)
    lvl_years = [y for y in win if cov.get(y, 0) >= 0.5]
    levels = sorted(int(c) for c in lv.columns)
    safety_chart = {"x": [str(y) for y in lvl_years], "series": []}
    for L in levels:
        safety_chart["series"].append({"name": f"רמה {L}", "data": [
            round(float(lv.loc[y, L] / lv.loc[y].sum() * 100), 1) if y in lv.index and lv.loc[y].sum() else 0
            for y in lvl_years]})
    hi_ref = (float(lv.loc[ref, [c for c in lv.columns if c >= 7]].sum() / lv.loc[ref].sum() * 100)
              if ref in lv.index and lv.loc[ref].sum() else None)
    lvl_first = lvl_years[0] if lvl_years else None
    hi_first = (float(lv.loc[lvl_first, [c for c in lv.columns if c >= 7]].sum() / lv.loc[lvl_first].sum() * 100)
                if lvl_first is not None else None)

    # --- pollution group (1 = cleanest, 15 = most polluting)
    zg = _num(df["kvutzat_zihum"])
    zd = df.assign(z=zg).dropna(subset=["z"])
    z_years = [y for y in win if y in set(zd["yr"])]
    z_tot = zd.groupby("yr")["act"].sum()
    zihum_chart = {"x": [], "series": [{"name": lab, "data": []} for _, _, lab in ZIHUM_BINS]}
    zcov = (z_tot / by_year).fillna(0)
    z_years = [y for y in z_years if zcov.get(y, 0) >= 0.5]
    zd["bin"] = -1
    for i, (lo, hi, _) in enumerate(ZIHUM_BINS):
        zd.loc[zd["z"].between(lo, hi), "bin"] = i
    zb = zd.groupby(["yr", "bin"])["act"].sum()
    for y in z_years:
        zihum_chart["x"].append(str(y))
        t = z_tot.get(y, 0)
        for i in range(len(ZIHUM_BINS)):
            v = zb.get((y, i), 0)
            zihum_chart["series"][i]["data"].append(round(float(v / t * 100), 1) if t else 0)
    my = _num(df["madad_yarok"])
    my = my.where(my < 999)        # 999 is the catalogue's "not computed" marker
    green = dict(zip(win, _wmed_by_year(df, my, my.notna(), win)))

    # --- CO2 (WLTP from its first well-covered year; NEDC kamut_CO2 before that)
    co2w, co2n = _num(df["CO2_WLTP"]), _num(df["kamut_CO2"])
    co2_years = list(win)
    co2_series = []
    for label, pt in [("בנזין", "בנזין"), ("היברידי", "היברידי"), ("דיזל", "דיזל")]:
        data = _wmed_by_year(df, co2w, (df["pt"] == pt) & co2w.gt(0), co2_years, MIN_YEAR_N,
                             base=df["pt"] == pt, min_cov=MIN_COV)
        co2_series.append({"name": f"{label} (WLTP)", "data": data})
    ice = df["pt"].isin(["בנזין", "דיזל", "היברידי"])
    nedc = _wmed_by_year(df, co2n, co2n.gt(0) & ice, co2_years, MIN_YEAR_N,
                         base=ice, min_cov=MIN_COV)
    co2_series.append({"name": "כל מנועי הבעירה (NEDC)", "data": nedc})
    co2_chart = {"x": [str(y) for y in co2_years], "series": co2_series}

    # --- NOx WLTP: petrol vs diesel, vehicle-weighted mean
    nox = _num(df["NOX_WLTP"])
    nox_mean = {}
    for key, pt in [("p", "בנזין"), ("d", "דיזל")]:
        msk = (df["pt"] == pt) & nox.notna() & (df["act"] > 0)
        d = pd.DataFrame({"yr": df.loc[msk, "yr"], "x": nox[msk] * df.loc[msk, "act"],
                          "w": df.loc[msk, "act"]})
        res = {}
        for y, g in d.groupby("yr"):
            if g["w"].sum() >= MIN_YEAR_N:
                res[int(y)] = round(math.fsum(sorted(g["x"])) / g["w"].sum(), 1)
        nox_mean[key] = res
    nox_rows = []
    for y in win:
        row = {"year": y, "p": nox_mean["p"].get(y), "d": nox_mean["d"].get(y)}
        if row["p"] is not None or row["d"] is not None:
            nox_rows.append(row)
    nox_chart = {"x": [str(r["year"]) for r in nox_rows],
                 "p": [r["p"] for r in nox_rows], "d": [r["d"] for r in nox_rows]}

    # --- specs: vehicle-weighted medians per model year
    spec_med = {}
    for col, key, _ in SPECS:
        v = _num(df[col])
        v = v.where(v > 0)
        if key == "cc":
            v = v.where(df["pt"] != "חשמלי")
        spec_med[key] = _wmean_by_year(df, v, v.notna(), win, MIN_YEAR_N)
    specs_chart = {"x": [str(y) for y in win],
                   "series": [{"key": k, "name": lab, "data": spec_med[k]} for _, k, lab in SPECS]}

    comfort_chart = {"x": [str(y) for y in win], "series": [
        {"name": lab, "data": _share_by_year(df, df[col].str.strip() == "1", win)} for col, lab in COMFORT]}

    # --- body types, SUV & 4x4 share
    body = df.groupby("body")["act"].sum()
    body = body[body > 0]
    b_names, b_vals = _top(body, TOP_BODY)
    suv_share = _share_by_year(df, df["body"] == "פנאי-שטח", win)
    awd_share = _share_by_year(df, df["hanaa_nm"].str.strip() == "4X4", win)
    body_trend = {"x": [str(y) for y in win], "suv": suv_share, "awd": awd_share}

    # --- licence-fee group (1..7): whole fleet vs latest reference model year
    ag = _num(df["kvuzat_agra_cd"])
    agd = df.assign(g=ag).dropna(subset=["g"])
    agd = agd[agd["g"] > 0]
    agd["g"] = agd["g"].astype(int)
    groups = sorted(set(agd["g"]))
    g_all = agd.groupby("g")["act"].sum()
    g_ref = agd[agd["yr"] == ref].groupby("g")["act"].sum()
    agra_chart = {"names": [f"קבוצה {g}" for g in groups],
                  "all": [round(float(g_all.get(g, 0) / g_all.sum() * 100), 1) if g_all.sum() else 0 for g in groups],
                  "ref": [round(float(g_ref.get(g, 0) / g_ref.sum() * 100), 1) if g_ref.sum() else 0 for g in groups]}

    # --- private vs commercial
    priv = int(df.loc[df["sug_degem"] == "P", "act"].sum())
    comm = int(df.loc[df["sug_degem"] == "M", "act"].sum())

    charts = {
        "fleet_year": fleet_year, "mix": mix_chart, "origin": origin_chart,
        "makes": makes_chart, "models": models_chart,
        "ev": {"names": ev_names, "values": ev_vals},
        "survival": survival_chart, "heat": heat, "local": local_chart,
        "safety": safety_chart, "zihum": zihum_chart, "co2": co2_chart, "nox": nox_chart,
        "specs": specs_chart, "comfort": comfort_chart,
        "body": {"names": b_names, "values": b_vals}, "body_trend": body_trend,
        "agra": agra_chart,
    }

    # --- insights
    rules = [
        ("electrified", insight_electrified(mix, ref, base)),
        ("ev", insight_ev(mix, ref, all_years)),
        ("china", insight_china(origin_share, ref, base)),
        ("leader", insight_leader(makes, models_top, total)),
        ("survival", insight_survival(surv, ref)),
        ("local_install", insight_local(local, loc_years)),
        ("adas", insight_adas(adas_ref, ref, adas_base, base)),
        ("heavier", insight_heavier(spec_med, win, ref, max(win[0], ref - 10))),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    # --- KPIs
    elec_ref = sum(mix.get(ref, {}).get(p, 0) for p in ELECTRIFIED)
    if abs(elec_ref - elec_fleet) < 3:
        elec_tone = "info"
    else:
        elec_tone = "ok" if elec_ref > elec_fleet else "warn"
    n_combos = int(len(df))
    kpis = {
        "active": {"value": total, "tone": "brand",
                   "display": f"{total / 1e6:.2f}" if total >= 1_000_000 else n(total)},
        "combos": {"value": n_combos, "display": n(n_combos), "tone": "brand"},
        "makes": {"value": int(makes.size), "display": n(makes.size), "tone": "brand"},
        "elec_ref": {"value": round(elec_ref, 1), "display": f"{elec_ref:.1f}%", "tone": elec_tone},
        "ev_fleet": {"value": round(ev_fleet, 1), "display": f"{ev_fleet:.1f}%", "tone": "info"},
        "china_ref": {"value": round(china_ref, 1), "display": f"{china_ref:.1f}%", "tone": "info"},
    }

    # --- labels / ledes
    partial = (f" שנות הייצור שאחרי {ref} עדיין מתמלאות ומוצגות חסר." if y_max > ref else
               f" שנת הייצור {y_max} עדיין נמכרת, ולכן עשויה להתעדכן.")
    unmatched_note = (f" {n(unmatched)} צירופים בטבלת הכמויות ללא מפרט אינם נכללים." if unmatched else "")
    e0 = sum(mix.get(base, {}).get(p, 0) for p in ELECTRIFIED)
    last_green = next((y for y in reversed(win) if green.get(y) is not None and y <= ref), None)
    first_green = next((y for y in z_years if green.get(y) is not None), None)
    nox_ref = next((r for r in reversed(nox_rows) if r["year"] <= ref and r["p"] and r["d"]), None)
    ev_ref_top = (ev_ref_df.sort_index().sort_values(ascending=False, kind="stable")
                  if not ev_ref_df.empty else None)
    surv_old = ref - 15
    labels = {
        "lede": (f"קטלוג משרד התחבורה של דגמי הרכב הפרטי והמסחרי, {n(n_combos)} צירופי דגם ושנת "
                 f"ייצור ({all_years[0]} עד {y_max}), עם מפרט טכני, ציוד בטיחות ונתוני פליטה — "
                 f"משולב בטבלת הכמויות: {n(total)} כלי רכב פעילים ({n(priv)} פרטיים, {n(comm)} "
                 f"מסחריים) ועוד {n(inactive)} שכבר אינם פעילים. כל הנתונים בעמוד משוקללים "
                 f"לפי מספר כלי הרכב הפעילים.{unmatched_note}"),
        "active_kpi": "כלי רכב פעילים (מיליונים)" if total >= 1_000_000 else "כלי רכב פעילים",
        "elec_ref_kpi": f"כלי רכב מחושמלים משנת ייצור {ref} (מהפעילים)",
        "ev_fleet_kpi": "רכב חשמלי מלא מכלל הצי הפעיל",
        "china_kpi": f"תוצרת סין משנת ייצור {ref}",
        "fleet_note": (f"מספר כלי הרכב הפעילים מכל שנת ייצור, לפי סוג הנעה. כלי רכב ישנים ירדו "
                       f"מהכביש, ולכן השנים המוקדמות נמוכות.{partial}"),
        "fleet_aria": (f"גרף עמודות מוערמות: כלי רכב פעילים לפי שנת ייצור וסוג הנעה, "
                       f"{all_years[0]} עד {y_max}."),
        "mix_note": (f"חלקו של כל סוג הנעה מבין כלי הרכב הפעילים של כל שנת ייצור. בשנת ייצור {ref}: "
                     f"{pct(elec_ref)} מחושמלים, לעומת {pct(e0)} בשנת ייצור {base}."),
        "mix_aria": (f"גרף שטחים מוערם: התפלגות סוגי ההנעה לפי שנת ייצור, {win[0]} עד {y_max}. "
                     f"בשנת ייצור {ref} — {elec_ref:.1f}% מחושמלים."),
        "origin_note": (f"ארץ הייצור (המפעל, לא מוצא המותג) של כלי הרכב הפעילים מכל שנת ייצור — "
                        f"{len(top_c)} הארצות המובילות ב-{TREND_GAP} שנות הייצור האחרונות. סין בשנת ייצור "
                        f"{ref}: {pct(china_ref)}. כשארץ הייצור חסרה במאגר היא נגזרת משם התוצר "
                        f"(למשל \"קיה ד. קוריאה\")."),
        "origin_aria": f"גרף עמודות מוערמות: התפלגות ארץ הייצור לפי שנת ייצור, {win[0]} עד {y_max}.",
        "makes_note": (f"{TOP_MAKES} התוצרים עם הכי הרבה כלי רכב פעילים, לפי סוג הנעה. "
                       f"התוצר המוביל: {top_makes[0]} ({n(makes.iloc[0])})." if top_makes else ""),
        "makes_aria": f"תרשים עמודות אופקי מוערם: {TOP_MAKES} התוצרים הנפוצים בצי הפעיל, לפי סוג הנעה.",
        "makes_caption": f"{TOP_MAKES} התוצרים הנפוצים: כלי רכב פעילים ושיעור המחושמלים.",
        "models_note": (f"הכינוי המסחרי של הדגם, כל שנות הייצור יחד. המוביל: "
                        f"{models_top[0]['make']} {models_top[0]['model']} ({n(models_top[0]['n'])})."
                        if models_top else ""),
        "models_aria": f"תרשים עמודות אופקי: {TOP_MODELS} הדגמים הנפוצים בצי הפעיל.",
        "models_caption": f"{TOP_MODELS} הדגמים הנפוצים בצי הפעיל.",
        "ev_note": (f"{n(ev_total)} כלי רכב חשמליים מלאים פעילים ({pct(ev_fleet)} מהצי)."
                    + (f" המוביל בשנת ייצור {ref}: {ev_ref_top.index[0]}." if ev_ref_top is not None else "")),
        "ev_aria": f"תרשים עמודות אופקי: {TOP_EV} התוצרים המובילים ברכב חשמלי מלא פעיל.",
        "ev_caption": f"רכב חשמלי מלא פעיל לפי תוצר ({TOP_EV} המובילים ואחר).",
        "survival_note": (f"שיעור כלי הרכב מכל שנת ייצור שעדיין פעילים, מתוך כל מי שנרשם (פעילים ושאינם "
                          f"פעילים)." + (f" משנת ייצור {surv_old}: {pct(surv[surv_old])}." if surv_old in surv else "")),
        "survival_aria": f"גרף משולב: שיעור כלי הרכב הפעילים וכלי הרכב שירדו מהכביש לפי שנת ייצור, {all_years[0]} עד {y_max}.",
        "heat_note": (f"שיעור כלי הרכב הפעילים מכל שנת ייצור שמצוידים בכל מערכת, משנת {heat_years[0]} עד {y_max}. "
                      f"כהה יותר = נפוץ יותר."),
        "heat_aria": f"מפת חום: שיעור כלי הרכב המצוידים ב-{len(ADAS)} מערכות בטיחות לפי שנת ייצור.",
        "local_note": ("מבין כלי הרכב שבהם מותקנת המערכת — כמה הותקנו בישראל (\"מקומי\") ולא בידי היצרן. "
                       f"שנים עם פחות מ-{n(MIN_YEAR_N)} כלי רכב מצוידים אינן מוצגות."),
        "local_aria": "גרף קווים: שיעור ההתקנה המקומית של מערכות בטיחות לפי שנת ייצור.",
        "safety_note": (f"רמת האבזור הבטיחותי (1 עד 8) של כלי הרכב הפעילים שיש להם דירוג, בשנים שבהן "
                        f"לפחות מחציתם מדורגים."
                        + (f" רמה 7 ומעלה בשנת ייצור {ref}: {pct(hi_ref)}, לעומת {pct(hi_first)} ב-{lvl_first}."
                           if hi_ref is not None and hi_first is not None and lvl_first != ref else "")),
        "safety_aria": "גרף עמודות מוערמות: התפלגות רמת האבזור הבטיחותי לפי שנת ייצור.",
        "zihum_note": ("קבוצת הזיהום (1 — הנקייה ביותר, 15 — המזהמת ביותר) של כלי הרכב הפעילים, בשנים "
                       "שבהן לפחות מחציתם מסווגים."
                       + (f" המדד הירוק החציוני ירד מ-{n(green[first_green])} בשנת ייצור {first_green} "
                          f"ל-{n(green[last_green])} בשנת ייצור {last_green} (נמוך = נקי יותר)."
                          if first_green and last_green and first_green != last_green else "")),
        "zihum_aria": "גרף עמודות מוערמות: התפלגות קבוצות הזיהום לפי שנת ייצור.",
        "co2_note": ("חציון פליטת CO₂ (גרם לק״מ) לפי שנת ייצור. בדיקת WLTP הנוכחית מחמירה מבדיקת NEDC "
                     "הישנה, ולכן שתי הסדרות אינן ברות השוואה ישירה. רכב חשמלי אינו נכלל; "
                     f"שנה מוצגת רק כשלפחות {pct(MIN_COV * 100, 0)} מכלי הרכב מאותו סוג (ולפחות "
                     f"{n(MIN_YEAR_N)}) נושאים ערך."),
        "co2_aria": "גרף קווים: חציון פליטת CO₂ לפי שנת ייצור וסוג הנעה.",
        "nox_note": ("ממוצע פליטת תחמוצות חנקן (NOx) בבדיקת WLTP, משוקלל לפי כלי רכב פעילים."
                     + (f" בשנת ייצור {nox_ref['year']}: דיזל {nox_ref['d']:.1f} מול בנזין {nox_ref['p']:.1f}."
                        if nox_ref else "")),
        "nox_aria": "גרף קווים: ממוצע פליטת NOx בבדיקת WLTP, בנזין מול דיזל, לפי שנת ייצור.",
        "nox_caption": "ממוצע פליטת NOx (WLTP) לפי שנת ייצור, בנזין ודיזל.",
        "specs_note": ("ממוצע משוקלל לפי כלי רכב פעילים. ערכים 0 (לא רשום) אינם נכללים; נפח מנוע — "
                       "מנועי בעירה בלבד."),
        "comfort_note": "שיעור כלי הרכב הפעילים מכל שנת ייצור שמצוידים בכל אחד מהפריטים.",
        "comfort_aria": "גרף קווים: שיעור תיבה אוטומטית, גלגלי סגסוגת וחלון בגג לפי שנת ייצור.",
        "body_note": (f"סוג המרכב של כלי הרכב הפעילים ({TOP_BODY} הנפוצים ואחר). פנאי-שטח בשנת ייצור {ref}: "
                      f"{pct(suv_share[win.index(ref)] or 0)}." if ref in win else ""),
        "body_aria": f"תרשים עמודות אופקי: כלי רכב פעילים לפי סוג מרכב ({TOP_BODY} הנפוצים ואחר).",
        "body_caption": "כלי רכב פעילים לפי סוג מרכב.",
        "body_trend_aria": "גרף קווים: שיעור רכבי פנאי-שטח ושיעור ההנעה 4X4 לפי שנת ייצור.",
        "agra_note": (f"קבוצת האגרה (1 עד 7) לפי רישום הדגם — כלל הצי הפעיל לעומת שנת ייצור {ref}."),
        "agra_aria": f"תרשים עמודות: התפלגות קבוצת האגרה, כלל הצי מול שנת ייצור {ref}.",
        "agra_caption": f"התפלגות קבוצת האגרה: כלל הצי ושנת ייצור {ref} (אחוזים).",
        "agra_ref": f"שנת ייצור {ref}",
    }
    for _, k, lab in SPECS:
        labels[f"spec_{k}_aria"] = f"גרף קווים: {lab} — ממוצע לפי שנת ייצור, {win[0]} עד {y_max}."

    tables = {
        "makes": [{"name": m, "count": n(makes[m]), "elec": f"{elec_by_make[m]:.1f}%"} for m in top_makes],
        "models": [{"make": m["make"], "model": m["model"], "count": n(m["n"])} for m in models_top],
        "ev": [{"name": k, "count": n(v)} for k, v in zip(ev_names, ev_vals)],
        "nox": [{"year": str(r["year"]), "p": "—" if r["p"] is None else f"{r['p']:.1f}",
                 "d": "—" if r["d"] is None else f"{r['d']:.1f}"} for r in nox_rows],
        "body": [{"name": k, "count": n(v)} for k, v in zip(b_names, b_vals)],
        "agra": [{"name": nm, "all": f"{a:.1f}%", "ref": f"{r:.1f}%"}
                 for nm, a, r in zip(agra_chart["names"], agra_chart["all"], agra_chart["ref"])],
    }
    flags = {"nox_table": len(nox_rows) <= 20, "local": bool(local), "safety": bool(lvl_years),
             "zihum": bool(z_years)}

    return {
        "agent_data": {
            "summary_he": (f"קטלוג דגמי הרכב הפרטי והמסחרי של משרד התחבורה עם מפרט, ציוד בטיחות ופליטות, "
                           f"משולב במספר כלי הרכב הפעילים: {n(total)} כלי רכב; {elec_ref:.1f}% מכלי הרכב "
                           f"משנת ייצור {ref} מחושמלים."),
            "dataset_kind": "registry",
            "suggested_tags": ["דגמי רכב", "רכב חשמלי", "פליטות", "בטיחות ברכב", "צי הרכב", "משרד התחבורה"],
            "related_ids": ["273c5e33-25ab-4980-8522-a2f7ba0bb62d",
                            "1c8e79c5-0ddb-461f-84ea-5bdcbaefaef4",
                            "392abd0a-64f6-4c18-9d56-0111001411e6",
                            "35c791ca-8db2-4657-8c6f-eb092147a6bb",
                            "0f16b39a-6016-408d-805d-31f40d5a0990"],
            "temporal_coverage": f"{all_years[0]}/{y_max}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
        "flags": flags,
    }
