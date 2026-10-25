"""ציי רכב אוטובוסים — the public-transport bus fleet register.

One row per bus (~15k) with operator, operating cluster, size/type,
seats, production year/country, propulsion and cumulative odometer.
"Now" is the latest production year in the register (its data vintage),
never the wall clock. That year is still filling (new deliveries land
daily), so it is labelled and kept out of year-over-year comparisons.
Licence numbers are never surfaced — aggregates only.
"""
import pandas as pd

TOP_OPS = 15
TOP_COUNTRIES = 8
TOP_CLUSTERS = 15
YEAR_WINDOW = 18          # production years shown individually; older lumped
SCATTER_MIN = 100         # operators with at least this many buses in the scatter
SCATTER_MAX = 20
LEADER_MIN = 300          # operator size for the "electric leader" rule
MIN_YEAR_N = 50           # minimum buses in a production year for share rules
ANNUAL_CAP = 250_000      # km/year above this is treated as an odometer error
ANNUAL_BUCKETS = [(0, 20), (20, 40), (40, 60), (60, 80), (80, 100), (100, 120), (120, None)]  # thousand km
PROP_ORDER = ["דיזל", "חשמל", "גז טבעי דחוס"]
OTHER_PROP = "לא ידוע"
TYPE_ORDER = ["עירוני", "בינעירוני"]
LRI, PDI = "⁦", "⁩"


def n(v):
    return f"{int(round(v)):,}"


def pct(v, digits=1):
    return f"{LRI}{v:.{digits}f}%{PDI}"


def _clean(s):
    s = s.str.strip()
    return s.where(~s.isin(["", "לא ידוע"]) & ~s.str.startswith("לא ידוע"), OTHER_PROP)


def _prepare(df):
    out = pd.DataFrame({
        "op": df["operator_nm"].str.strip().replace("", OTHER_PROP),
        "cluster": df["cluster_nm"].str.strip().replace("", OTHER_PROP),
        "stone": df["stone_proof_nm"].str.strip(),
        "bullet": df["bullet_proof_nm"].str.strip(),
        "size": _clean(df["BusSize_nm"]),
        "btype": _clean(df["BusType_nm"]),
        "seats": pd.to_numeric(df["SeatsNum"].str.replace(",", ""), errors="coerce"),
        "year": pd.to_numeric(df["production_year"], errors="coerce"),
        "country": _clean(df["production_country"]),
        "prop": _clean(df["PropulsionType_nm"]),
        "km": pd.to_numeric(df["total_kilometer"].str.replace(",", ""), errors="coerce"),
    })
    out.loc[~out["year"].between(1980, 2100), "year"] = float("nan")
    out.loc[out["seats"] <= 0, "seats"] = float("nan")
    out.loc[out["km"] < 0, "km"] = float("nan")
    return out


def _sorted_counts(s):
    return s.value_counts().sort_index().sort_values(ascending=False, kind="stable")


def _props(df):
    present = set(df["prop"])
    extra = sorted(p for p in present if p not in PROP_ORDER and p != OTHER_PROP)
    return [p for p in PROP_ORDER if p in present] + extra + ([OTHER_PROP] if OTHER_PROP in present else [])


def _q(s, q):
    return float(s.quantile(q))


# ---------------------------------------------------------------- insights

def insight_young(df, ref_year):
    y = df["year"].dropna()
    if y.empty:
        return None
    lo = ref_year - 4
    recent = (y >= lo).mean()
    return (f"הצי צעיר: {pct(recent * 100)} מהאוטובוסים יוצרו בשנים {lo}–{ref_year}, "
            f"ושנת הייצור החציונית היא {int(y.median())}.")


def _elec_share(df, y):
    sub = df[df["year"] == y]
    if len(sub) < MIN_YEAR_N:
        return None
    return (sub["prop"] == "חשמל").mean()


def insight_electric(df, last_full):
    base = last_full - 4
    s1, s0 = _elec_share(df, last_full), _elec_share(df, base)
    if s1 is None or s0 is None:
        return None
    fleet = (df["prop"] == "חשמל").mean()
    tail = f"; בכלל הצי שיעורם {pct(fleet * 100)}"
    if abs(s1 - s0) < 0.03:
        return (f"שיעור האוטובוסים החשמליים נותר דומה בין שנות הייצור {base} ({pct(s0 * 100)}) "
                f"ו-{last_full} ({pct(s1 * 100)}){tail}.")
    word = "זינק" if s1 - s0 >= 0.2 else ("עלה" if s1 > s0 else "ירד")
    lead = " — רוב האוטובוסים החדשים חשמליים" if s1 > 0.5 else ""
    return (f"שיעור האוטובוסים החשמליים {word} מ-{pct(s0 * 100)} בשנת הייצור {base} "
            f"ל-{pct(s1 * 100)} בשנת {last_full}{lead}{tail}.")


def insight_country(df):
    known = df[df["country"] != OTHER_PROP]
    if known.empty:
        return None
    c = _sorted_counts(known["country"])
    name, v = c.index[0], c.iloc[0]
    share = v / len(known)
    if share < 0.25:
        return None
    el = known[known["prop"] == "חשמל"]
    s = f"{name} היא מדינת הייצור המובילה — {n(v)} אוטובוסים ({pct(share * 100)})"
    if len(el) >= 50:
        el_share = (el["country"] == name).mean()
        s += f", ו-{pct(el_share * 100)} מהאוטובוסים החשמליים יוצרו בה"
    if len(c) > 1:
        s += f". אחריה {c.index[1]} ({n(c.iloc[1])})"
    return s + "."


def insight_concentration(ops, total):
    if len(ops) < 3:
        return None
    top1 = ops.iloc[0] / total
    top3 = ops.head(3).sum() / total
    if top1 < 0.1:
        return None
    names = ", ".join(ops.index[:3])
    return (f"{ops.index[0]} מפעילה את הצי הגדול ביותר — {n(ops.iloc[0])} אוטובוסים "
            f"({pct(top1 * 100)}); שלושת הגדולים ({names}) מחזיקים יחד {pct(top3 * 100)} מהצי, "
            f"מתוך {len(ops)} מפעילים.")


def insight_elec_leader(df):
    fleet = (df["prop"] == "חשמל").mean()
    g = df.groupby("op").agg(nb=("prop", "size"), el=("prop", lambda s: (s == "חשמל").mean()))
    g = g[g["nb"] >= LEADER_MIN].reset_index().sort_values(["el", "nb", "op"], ascending=[False, False, True])
    if g.empty or fleet == 0:
        return None
    top = g.iloc[0]
    if top["el"] < 1.5 * fleet:
        return None
    s = (f"{top['op']} מובילה בחשמול: {pct(top['el'] * 100)} מ-{n(top['nb'])} האוטובוסים שלה "
         f"חשמליים, לעומת {pct(fleet * 100)} בכלל הצי")
    zero = g[g["el"] == 0]["op"].tolist()
    if zero:
        who = f" ({', '.join(zero)})" if len(zero) <= 3 else ""
        cnt = "לאחד מהם" if len(zero) == 1 else f"ל-{len(zero)} מהם"
        s += f". מבין המפעילים עם {n(LEADER_MIN)} אוטובוסים ומעלה, {cnt}{who} אין אף אוטובוס חשמלי"
    return s + "."


def insight_protection(df, total):
    st = df[df["stone"] == "ממוגן אבנים"]
    if st.empty:
        return None
    by = _sorted_counts(st["op"])
    k = min(3, len(by))
    share = by.head(k).sum() / len(st)
    bl = int((df["bullet"] == "ממוגן ירי").sum())
    names = ", ".join(by.index[:k])
    s = (f"מיגון נדיר: {n(len(st))} אוטובוסים ממוגני אבנים ({pct(len(st) / total * 100)} מהצי) "
         f"ו-{n(bl)} ממוגני ירי. ")
    if share >= 0.8:
        lead = "כל הממוגנים באבנים" if share == 1 else f"{pct(share * 100)} מהממוגנים באבנים"
        s += f"{lead} שייכים ל{'מפעיל' if k == 1 else 'מפעילים'} {names}."
    else:
        s += f"הם מפוזרים בין {len(by)} מפעילים."
    return s


def insight_mileage(ann):
    med = ann.groupby("btype")["ak"].median()
    if not set(TYPE_ORDER) <= set(med.index):
        return None
    u, i = med["עירוני"], med["בינעירוני"]
    if u <= 0 or i / u < 1.2:
        return None
    return (f"אוטובוס בינעירוני נוסע כ-{n(i)} ק״מ בשנה (חציון), פי {i / u:.1f} מאוטובוס עירוני "
            f"(כ-{n(u)} ק״מ) — הערכה לפי ק״מ מצטבר חלקי גיל.")


def insight_zero(df, total, ref_year):
    z = df[df["km"] == 0]
    if len(z) / total < 0.01:
        return None
    newest = (z["year"] == ref_year).mean()
    if newest < 0.5:
        return None
    return (f"{n(len(z))} אוטובוסים רשומים עם 0 ק״מ — {pct(newest * 100)} מהם משנת הייצור "
            f"{ref_year}, ככל הנראה אוטובוסים חדשים שטרם נכנסו לשירות.")


# ---------------------------------------------------------------- compute

def compute(frames):
    df = _prepare(frames["fleet"])
    total = len(df)
    ref_year = int(df["year"].max())
    last_full = ref_year - 1
    props = _props(df)
    df["age"] = ref_year - df["year"]
    missing = int(df["year"].isna().sum())

    ops = _sorted_counts(df["op"])
    clusters = df.groupby(["op", "cluster"]).size().reset_index(name="nb")

    # 1. production year × propulsion (older years lumped)
    first = ref_year - YEAR_WINDOW + 1
    yr = df.dropna(subset=["year"]).copy()
    has_old = bool((yr["year"] < first).any())
    yr["ylab"] = yr["year"].map(lambda v: str(int(v)) if v >= first else f"עד {first - 1}")
    years = list(range(max(first, int(yr["year"].min())), ref_year + 1))
    xlabs = ([f"עד {first - 1}"] if has_old else []) + [str(y) for y in years]
    ct = yr.groupby(["ylab", "prop"]).size().unstack(fill_value=0).reindex(index=xlabs, fill_value=0)
    by_year = {"x": xlabs, "series": [{"name": p, "data": [int(v) for v in ct.get(p, pd.Series(0, index=xlabs))]}
                                      for p in props if p in ct.columns]}
    year_tot = ct.sum(axis=1)
    by_year_rows = [{"year": x, "cells": [n(ct.at[x, p]) if p in ct.columns else "0" for p in props],
                     "total": n(year_tot[x])} for x in xlabs]

    # 2. propulsion share per production year (years with >= MIN_YEAR_N buses)
    share_years = [str(y) for y in years if year_tot.get(str(y), 0) >= MIN_YEAR_N]
    share_props = [p for p in props if p != OTHER_PROP]
    mix = {"x": share_years, "series": [
        {"name": p, "data": [round(float(ct.at[y, p] / year_tot[y] * 100), 1) if p in ct.columns else 0.0
                             for y in share_years]} for p in share_props]}
    mix_rows = [{"year": y, "cells": [f"{d['data'][i]:.1f}%" for d in mix["series"]]}
                for i, y in enumerate(share_years)]

    # 3. operators × propulsion
    top_ops = list(ops.index[:TOP_OPS])
    df["op_g"] = df["op"].where(df["op"].isin(top_ops), "אחר")
    op_names = top_ops + (["אחר"] if len(ops) > TOP_OPS else [])
    oc = df.groupby(["op_g", "prop"]).size().unstack(fill_value=0).reindex(index=op_names, fill_value=0)
    operators = {"names": op_names, "series": [{"name": p, "data": [int(v) for v in oc[p]]}
                                               for p in props if p in oc.columns]}
    op_rows = [{"name": o, "total": n(oc.loc[o].sum()),
                "elec": pct(oc.loc[o].get("חשמל", 0) / max(oc.loc[o].sum(), 1) * 100)} for o in op_names]

    # 4. operator scatter: median age × electric share
    g = df.groupby("op").agg(nb=("prop", "size"), el=("prop", lambda s: (s == "חשמל").mean()),
                             age=("age", "mean")).reset_index()
    g = g[(g["nb"] >= SCATTER_MIN) & g["age"].notna()]
    g = g.sort_values(["nb", "op"], ascending=[False, True]).head(SCATTER_MAX)
    scatter = {"points": [[round(float(r.age), 1), round(float(r.el) * 100, 1), int(r.nb), r.op] for r in g.itertuples()]}
    scatter_rows = [{"name": r.op, "n": n(r.nb), "age": f"{r.age:.1f}", "el": pct(r.el * 100)} for r in g.itertuples()]

    # 5. production country × propulsion
    cc = _sorted_counts(df.loc[df["country"] != OTHER_PROP, "country"])
    top_c = list(cc.index[:TOP_COUNTRIES])
    df["c_g"] = df["country"].where(df["country"].isin(top_c) | (df["country"] == OTHER_PROP), "אחר")
    c_names = top_c + (["אחר"] if len(cc) > TOP_COUNTRIES else [])
    kc = df[df["c_g"] != OTHER_PROP].groupby(["c_g", "prop"]).size().unstack(fill_value=0)
    kc = kc.reindex(index=c_names, fill_value=0)
    countries = {"names": c_names, "series": [{"name": p, "data": [int(v) for v in kc[p]]}
                                              for p in props if p in kc.columns]}
    c_rows = [{"name": c, "total": n(kc.loc[c].sum()),
               "elec": n(kc.loc[c].get("חשמל", 0))} for c in c_names]

    # 6. size × type
    sz = df[df["size"] != OTHER_PROP]
    sizes = list(_sorted_counts(sz["size"]).index)
    types = [t for t in TYPE_ORDER if t in set(sz["btype"])] + sorted(
        t for t in set(sz["btype"]) if t not in TYPE_ORDER and t != OTHER_PROP)
    st = sz.groupby(["size", "btype"]).size().unstack(fill_value=0).reindex(index=sizes, fill_value=0)
    size_type = {"names": sizes, "series": [{"name": t, "data": [int(v) for v in st[t]]}
                                            for t in types if t in st.columns]}
    size_rows = [{"name": s_, "cells": [n(st.at[s_, t]) if t in st.columns else "0" for t in types],
                  "total": n(st.loc[s_].sum())} for s_ in sizes]

    # 7. seats boxplot per size
    seat_sizes = [s_ for s_ in sizes if sz.loc[sz["size"] == s_, "seats"].notna().sum() >= 10]
    boxes, seat_rows = [], []
    for s_ in seat_sizes:
        v = sz.loc[sz["size"] == s_, "seats"].dropna()
        b = [_q(v, 0), _q(v, .25), _q(v, .5), _q(v, .75), _q(v, 1)]
        boxes.append([round(x, 1) for x in b])
        seat_rows.append({"name": s_, "n": n(len(v)), "q": [f"{x:g}" for x in [round(x, 1) for x in b]]})
    seats = {"names": seat_sizes, "boxes": boxes}

    # 8. median cumulative km by production year, urban vs intercity
    kmy = df[df["km"].notna() & df["year"].between(first, ref_year) & df["btype"].isin(TYPE_ORDER)]
    med = kmy.groupby([kmy["year"].astype(int), "btype"])["km"].median().unstack()
    med_n = kmy.groupby([kmy["year"].astype(int), "btype"]).size().unstack(fill_value=0)

    def mval(y, t):
        if t not in med.columns or y not in med.index or med_n.at[y, t] < 10 or pd.isna(med.at[y, t]):
            return None
        return int(round(med.at[y, t]))

    km_year = {"x": [str(y) for y in years],
               "series": [{"name": t, "data": [mval(y, t) for y in years]} for t in TYPE_ORDER]}
    km_rows = [{"year": str(y), "cells": [n(mval(y, t)) if mval(y, t) is not None else "—" for t in TYPE_ORDER]}
               for y in years]

    # 9. estimated annual km
    ann = df[(df["year"] < ref_year) & (df["km"] > 0) & df["btype"].isin(TYPE_ORDER)].copy()
    ann["ak"] = ann["km"] / (ref_year - ann["year"] + 0.5)
    n_err = int((ann["ak"] > ANNUAL_CAP).sum())
    ann = ann[ann["ak"] <= ANNUAL_CAP]

    def blabel(lo, hi):
        return f"{lo}+" if hi is None else f"{lo}–{hi}"

    a_names = [blabel(lo, hi) for lo, hi in ANNUAL_BUCKETS]
    a_series = []
    for t in TYPE_ORDER:
        v = ann.loc[ann["btype"] == t, "ak"] / 1000
        data = []
        for lo, hi in ANNUAL_BUCKETS:
            m = v >= lo
            if hi is not None:
                m &= v < hi
            data.append(int(m.sum()))
        a_series.append({"name": t, "data": data})
    annual = {"names": a_names, "series": a_series}
    annual_rows = [{"bucket": a_names[i], "cells": [n(s["data"][i]) for s in a_series]} for i in range(len(a_names))]

    # 10. protection by operator
    pr = df.assign(st=df["stone"] == "ממוגן אבנים", bl=df["bullet"] == "ממוגן ירי")
    pg = pr.groupby("op")[["st", "bl"]].sum()
    pg = pg[(pg["st"] + pg["bl"]) > 0].reset_index().sort_values(["st", "bl", "op"], ascending=[False, False, True])
    protection = {"names": pg["op"].tolist(),
                  "stone": [int(v) for v in pg["st"]], "bullet": [int(v) for v in pg["bl"]]}
    prot_rows = [{"name": r.op, "st": n(r.st), "bl": n(r.bl), "of": n(ops[r.op])} for r in pg.itertuples()]

    # 11. operator → cluster treemap
    tm = []
    for o in ops.index:
        sub = clusters[clusters["op"] == o].sort_values(["nb", "cluster"], ascending=[False, True])
        tm.append({"name": o, "value": int(sub["nb"].sum()),
                   "children": [{"name": r.cluster, "value": int(r.nb)} for r in sub.itertuples()]})
    cl = clusters.sort_values(["nb", "cluster", "op"], ascending=[False, True, True])
    cl_rows = [{"cluster": r.cluster, "op": r.op, "n": n(r.nb)} for r in cl.head(TOP_CLUSTERS).itertuples()]
    n_clusters = int(df["cluster"].nunique())

    # ------------------------------------------------------------ KPIs
    elec = int((df["prop"] == "חשמל").sum())
    fleet_share = elec / total * 100
    new_share = _elec_share(df, last_full)
    if new_share is None or abs(new_share * 100 - fleet_share) < 3:
        elec_tone = "info"
    else:
        elec_tone = "ok" if new_share * 100 > fleet_share else "warn"
    med_age = float(df["age"].median())
    age_tone = "ok" if med_age <= 5 else ("warn" if med_age >= 10 else "brand")
    km_known = df["km"].dropna()
    stone_n = int((df["stone"] == "ממוגן אבנים").sum())
    bullet_n = int((df["bullet"] == "ממוגן ירי").sum())
    ann_med = float(ann["ak"].median()) if len(ann) else 0.0
    kpis = {
        "total": {"value": total, "display": n(total), "tone": "brand"},
        "operators": {"value": int(len(ops)), "display": n(len(ops)), "tone": "brand"},
        "clusters": {"value": n_clusters, "display": n(n_clusters), "tone": "brand"},
        "electric": {"value": elec, "display": f"{fleet_share:.1f}%", "tone": elec_tone},
        "age": {"value": med_age, "display": f"{med_age:g}", "tone": age_tone},
        "km_total": {"value": float(km_known.sum()), "display": f"{km_known.sum() / 1e9:.2f}", "tone": "brand"},
        "annual": {"value": ann_med, "display": n(ann_med), "tone": "brand"},
        "stone": {"value": stone_n, "display": n(stone_n), "tone": "info"},
    }

    rules = [
        ("young", insight_young(df, ref_year)),
        ("electric", insight_electric(df, last_full)),
        ("country", insight_country(df)),
        ("concentration", insight_concentration(ops, total)),
        ("elec_leader", insight_elec_leader(df)),
        ("mileage", insight_mileage(ann)),
        ("protection", insight_protection(df, total)),
        ("zero_km", insight_zero(df, total, ref_year)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    partial = f"שנת הייצור {ref_year} עדיין מתעדכנת — אוטובוסים חדשים נקלטים במאגר לאורך השנה."
    missing_note = f" {n(missing)} רשומות ללא שנת ייצור אינן נכללות." if missing else ""
    old_note = f" שנים מוקדמות מ-{first} מקובצות יחד." if has_old else ""
    elec_label = "מהצי בהנעה חשמלית"
    if new_share is not None:
        elec_label += f" ({new_share * 100:.1f}% משנת הייצור {last_full})"
    labels = {
        "lede": (f"מרשם האוטובוסים של מפעילי התחבורה הציבורית: "
                 f"{n(total)} אוטובוסים של {len(ops)} מפעילים ב-{n_clusters} אשכולות הפעלה — "
                 f"גודל וסוג, מקומות ישיבה, שנת ומדינת ייצור, סוג הנעה, קילומטראז' ומיגון. שנת הייצור האחרונה במאגר: {ref_year}."),
        "electric_kpi": elec_label,
        "age_kpi": f"גיל חציוני בשנים (ביחס ל-{ref_year})",
        "annual_kpi": "ק״מ בשנה לאוטובוס (חציון, הערכה)",
        "year_note": f"מספר האוטובוסים בצי לפי שנת ייצור וסוג הנעה. {partial}{old_note}{missing_note}",
        "year_aria": f"גרף עמודות מוערמות: אוטובוסים לפי שנת ייצור וסוג הנעה, עד {ref_year}.",
        "year_caption": "מספר אוטובוסים לפי שנת ייצור וסוג הנעה.",
        "mix_note": (f"חלקו של כל סוג הנעה מבין האוטובוסים שיוצרו בכל שנה (שנים עם {MIN_YEAR_N} "
                     f"אוטובוסים לפחות). {partial}"),
        "mix_aria": "גרף קווים: שיעור כל סוג הנעה מבין האוטובוסים לפי שנת ייצור.",
        "mix_caption": "שיעור סוגי ההנעה לפי שנת ייצור.",
        "ops_note": f"{TOP_OPS} המפעילים הגדולים לפי מספר אוטובוסים, בחלוקה לסוג הנעה; השאר מקובצים כ״אחר״.",
        "ops_aria": f"תרשים עמודות אופקי מוערם: {TOP_OPS} המפעילים הגדולים לפי סוג הנעה.",
        "ops_caption": "מספר אוטובוסים ושיעור החשמליים לפי מפעיל.",
        "scatter_note": (f"כל עיגול הוא מפעיל עם {SCATTER_MIN} אוטובוסים לפחות (עד {SCATTER_MAX} הגדולים): "
                         f"גיל ממוצע של הצי מול שיעור האוטובוסים החשמליים; גודל העיגול — גודל הצי."),
        "scatter_aria": "תרשים פיזור: גיל צי ממוצע מול שיעור אוטובוסים חשמליים, לפי מפעיל.",
        "scatter_caption": "גיל ממוצע ושיעור חשמליים לפי מפעיל.",
        "country_note": f"{TOP_COUNTRIES} מדינות הייצור הנפוצות, בחלוקה לסוג הנעה.",
        "country_aria": "תרשים עמודות אופקי מוערם: אוטובוסים לפי מדינת ייצור וסוג הנעה.",
        "country_caption": "מספר אוטובוסים ואוטובוסים חשמליים לפי מדינת ייצור.",
        "size_aria": "תרשים עמודות מוערם: אוטובוסים לפי גודל וסוג שירות.",
        "size_caption": "מספר אוטובוסים לפי גודל וסוג שירות.",
        "seats_aria": "תרשים קופסה: התפלגות מספר מקומות הישיבה לפי גודל אוטובוס.",
        "seats_caption": "מקומות ישיבה לפי גודל: מינימום, רבעון תחתון, חציון, רבעון עליון ומקסימום.",
        "km_note": (f"הקילומטראז' המצטבר החציוני לפי שנת ייצור — אוטובוסים בינעירוניים מול עירוניים. "
                    f"נקודות עם פחות מעשרה אוטובוסים אינן מוצגות."),
        "km_aria": "גרף קווים: קילומטראז' מצטבר חציוני לפי שנת ייצור, עירוני ובינעירוני.",
        "km_caption": "קילומטראז' מצטבר חציוני לפי שנת ייצור וסוג שירות.",
        "annual_note": (f"הערכה: ק״מ מצטבר חלקי גיל האוטובוס (מאמצע שנת הייצור עד {ref_year}). "
                        f"לא נכללו אוטובוסים משנת {ref_year}, אוטובוסים עם 0 ק״מ או ללא נתון, "
                        f"ו-{n(n_err)} רשומות עם יותר מ-{n(ANNUAL_CAP)} ק״מ בשנה (שגיאת מונה סבירה)."),
        "annual_aria": "תרשים עמודות: אוטובוסים לפי ק״מ שנתי משוער (אלפי ק״מ), עירוני ובינעירוני.",
        "annual_caption": "מספר אוטובוסים לפי ק״מ שנתי משוער בשנה (באלפים).",
        "prot_note": (f"מפעילים שבציהם אוטובוסים ממוגני אבנים או ירי. בכלל הצי: "
                      f"{n(stone_n)} ממוגני אבנים ו-{n(bullet_n)} ממוגני ירי."),
        "prot_aria": "תרשים עמודות אופקי: אוטובוסים ממוגנים לפי מפעיל.",
        "prot_caption": "אוטובוסים ממוגני אבנים וממוגני ירי לפי מפעיל.",
        "tree_note": (f"כל מלבן הוא מפעיל, ובתוכו אשכולות ההפעלה שלו; השטח יחסי למספר האוטובוסים. "
                      f"לחיצה על מפעיל מתמקדת בו."),
        "tree_aria": f"מפת עץ: {len(ops)} מפעילים ו-{n_clusters} אשכולות הפעלה לפי מספר אוטובוסים.",
        "tree_caption": f"{TOP_CLUSTERS} האשכולות הגדולים לפי מספר אוטובוסים.",
    }
    tables = {
        "props": props, "types": types, "share_props": share_props,
        "by_year": by_year_rows, "mix": mix_rows, "ops": op_rows, "scatter": scatter_rows,
        "countries": c_rows, "sizes": size_rows, "seats": seat_rows, "km": km_rows,
        "annual": annual_rows, "protection": prot_rows, "clusters": cl_rows,
    }
    charts = {"by_year": by_year, "mix": mix, "operators": operators, "scatter": scatter,
              "countries": countries, "size_type": size_type, "seats": seats, "km_year": km_year,
              "annual": annual, "protection": protection, "tree": tm}

    return {
        "agent_data": {
            "summary_he": (f"ציי האוטובוסים בתחבורה הציבורית: {n(total)} אוטובוסים של {len(ops)} מפעילים, "
                           f"{fleet_share:.1f}% מהם חשמליים — לפי מפעיל, שנת ומדינת ייצור, הנעה וקילומטראז'."),
            "dataset_kind": "registry",
            "related_ids": ["27047419-e1fc-4f1d-bb15-7f5f0805d226",
                            "1e9d4542-97af-47ac-a780-f2a6b291b1f5",
                            "30cc4889-9bd7-4888-a66d-51ab39eb579a",
                            "0219b34f-43c7-435b-bdfe-e65e944cde50",
                            "273c5e33-25ab-4980-8522-a2f7ba0bb62d"],
            "suggested_tags": ["אוטובוסים", "תחבורה ציבורית", "צי רכב", "רכב חשמלי", "מפעילי תחבורה", "מיגון"],
            "temporal_coverage": f"{int(df['year'].min())}/{ref_year}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
    }
