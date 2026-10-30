"""היסטוריית כלי רכב פרטיים: private vehicles first registered since 2017.

Two tables joined on the vehicle number:
  vehicles: one row per active private vehicle (first registration date,
            odometer at the last test, origin class, four change flags);
  owners:   one row per ownership record (month YYYYMM, ownership type).

Memory: ~2.5M + ~5.6M rows. The str frames are popped from `frames`
and replaced by compact numeric/categorical columns right away, so the
peak stays near the size of the parsed CSVs. Vehicle numbers never leave
compute: everything on the page is an aggregate.
"""
import numpy as np
import pandas as pd

MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני",
             "יולי", "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]

# Ownership types: display order for known codes, unknown ones appended.
OWNER_ORDER = ["פרטי", "החכר", "סוחר", "חברה", "השכרה"]
OWNER_LABEL = {"פרטי": "פרטי", "החכר": "החכר (ליסינג)", "סוחר": "סוחר",
               "חברה": "חברה", "השכרה": "השכרה"}
MIXED = "יותר מסוג אחד בחודש הרישום"

# Origin (mkoriut_nm) display names. Raw values carry stray gershayim.
ORIGIN_EMPTY = "רגיל (ללא סיווג)"
ORIGIN_LABEL = {
    "החכר": "החכר (ליסינג)",
    "ביס לנהיגה\"": "בית ספר לנהיגה",
    "יוש-עזה\"": "יו״ש ועזה",
}
ORIGIN_TOP = 6
OTHER = "אחר"

KM_TESTED = 1000          # odometer at or above: an annual test, not the registration check
KM_COHORT_MIN_SHARE = 0.5  # a registration year needs this share tested to show its median
HANDS_CAP = 10


def _int(n):
    return f"{int(round(n)):,}"


def _pct(x, d=1):
    return f"{x * 100:.{d}f}%"


def _month_name(ym):
    return f"{MONTHS_HE[ym % 100 - 1]} {ym // 100}"


def _origin_label(raw):
    raw = raw.strip()
    if raw == "":
        return ORIGIN_EMPTY
    if raw in ORIGIN_LABEL:
        return ORIGIN_LABEL[raw]
    return raw.replace("\"", "").strip() or ORIGIN_EMPTY


def _owner_types(present):
    known = [t for t in OWNER_ORDER if t in present]
    return known + sorted(t for t in present if t not in OWNER_ORDER)


# ───────────────────────────── preparation ─────────────────────────────

def _prep_vehicles(a):
    veh = pd.to_numeric(a["mispar_rechev"].str.strip(), errors="coerce")
    reg = pd.to_datetime(a["rishum_rishon_dt"].str.strip(), errors="coerce", format="%Y-%m-%d")
    km = pd.to_numeric(a["kilometer_test_aharon"].str.strip().str.replace(",", ""), errors="coerce")
    origin_raw = a["mkoriut_nm"].astype("category")
    cats = list(origin_raw.cat.categories)
    origin = origin_raw.cat.rename_categories([f"__{i}" for i in range(len(cats))])
    labels = {f"__{i}": _origin_label(c) for i, c in enumerate(cats)}
    origin = origin.astype(str).map(labels)
    flags = {}
    for col in ("shinui_mivne_ind", "gapam_ind", "shnui_zeva_ind", "shinui_zmig_ind"):
        flags[col] = (a[col].str.strip() == "1").astype(np.int8)
    v = pd.DataFrame({
        "veh": veh, "reg": reg, "km": km,
        "origin": origin.astype("category"), **flags,
    })
    v = v.dropna(subset=["veh", "reg"])
    v["veh"] = v["veh"].astype(np.int64)
    v["ry"] = v["reg"].dt.year.astype(np.int16)
    v["rm"] = v["reg"].dt.month.astype(np.int8)
    return v


def _prep_owners(b):
    veh = pd.to_numeric(b["mispar_rechev"].str.strip(), errors="coerce")
    ym = pd.to_numeric(b["baalut_dt"].str.strip(), errors="coerce")
    t = b["baalut"].str.strip().astype("category")
    o = pd.DataFrame({"veh": veh, "ym": ym, "t": t})
    o = o.dropna(subset=["veh", "ym"])
    o = o[(o["t"].astype(str) != "") & (o["ym"] % 100 >= 1) & (o["ym"] % 100 <= 12)]
    o["veh"] = o["veh"].astype(np.int64)
    o["ym"] = o["ym"].astype(np.int32)
    o["t"] = o["t"].cat.remove_unused_categories()
    return o


# ───────────────────────────── insights ─────────────────────────────

def insight_reg_ytd(reg_months, latest, partial):
    """Registrations this year so far vs the same months last year."""
    y = latest.year
    if not partial:
        return None
    # Months fully in the data: before the latest month, plus the latest
    # month when its last day is in the data.
    last_full = latest.month if latest.is_month_end else latest.month - 1
    if last_full < 1:
        return None
    cur = reg_months.get(y, {})
    prev = reg_months.get(y - 1)
    if not prev:
        return None
    c = sum(cur.get(m, 0) for m in range(1, last_full + 1))
    p = sum(prev.get(m, 0) for m in range(1, last_full + 1))
    if p == 0:
        return None
    ch = (c - p) / p
    span = MONTHS_HE[0] if last_full == 1 else f"{MONTHS_HE[0]} עד {MONTHS_HE[last_full - 1]}"
    if abs(ch) < 0.03:
        return (f"ב{span} {y} עלו לכביש {_int(c)} רכבים פרטיים שעדיין פעילים, "
                f"כמעט כמו באותה תקופה ב-{y - 1} ({_int(p)}).")
    word = "יותר" if ch > 0 else "פחות"
    return (f"ב{span} {y} עלו לכביש {_int(c)} רכבים פרטיים שעדיין פעילים, "
            f"{_pct(abs(ch))} {word} מאשר באותה תקופה ב-{y - 1} ({_int(p)}).")


def insight_jan(reg_months, full_years):
    if len(full_years) < 2:
        return None
    shares = []
    for y in full_years:
        tot = sum(reg_months[y].values())
        if tot:
            shares.append(reg_months[y].get(1, 0) / tot)
    if not shares:
        return None
    s = float(np.mean(shares))
    if s < 1.3 / 12:
        return None
    # January must also be the busiest month on average, not just above 1.3/12.
    avg = {m: float(np.mean([reg_months[y].get(m, 0) / sum(reg_months[y].values())
                             for y in full_years if sum(reg_months[y].values())]))
           for m in range(1, 13)}
    if max(range(1, 13), key=lambda m: (avg[m], -m)) != 1:
        return None
    return (f"ינואר הוא חודש השיא לעלייה לכביש: בממוצע {_pct(s)} מהרישומים של שנה מלאה "
            f"נעשים בו, לעומת {_pct(1 / 12)} בחלוקה שווה בין החודשים "
            f"({full_years[0]} עד {full_years[-1]}).")


def insight_dip(own_month):
    """The month furthest below its year's median, if it is a real outlier."""
    s = pd.Series(own_month).sort_index()
    if len(s) < 24:
        return None
    best = None
    for ym, v in s.items():
        yr = s[(s.index // 100) == ym // 100]
        if len(yr) < 12:
            continue
        med = float(yr.drop(ym).median())
        if med <= 0:
            continue
        r = v / med
        if best is None or r < best[0]:
            best = (r, ym, v, med)
    if best is None or best[0] >= 0.4:
        return None
    r, ym, v, med = best
    return (f"החודש החריג ביותר ברישומי הבעלות הוא {_month_name(ym)}: {_int(v)} רשומות בלבד, "
            f"{_pct(1 - r, 0)} פחות מהחציון החודשי של אותה שנה ({_int(med)}).")


def insight_dealer(mix_years, full_years):
    yrs = [y for y in full_years if y in mix_years]
    if len(yrs) < 3:
        return None
    a, b = mix_years[yrs[0]].get("סוחר", 0.0), mix_years[yrs[-1]].get("סוחר", 0.0)
    if b - a < 0.03:
        return None
    return (f"חלקם של סוחרי הרכב ברשומות הבעלות עלה מ-{_pct(a)} ב-{yrs[0]} ל-{_pct(b)} ב-{yrs[-1]}, "
            f"ככל שהרכבים במאגר (שעלו לכביש מ-{yrs[0]}) מתבגרים ועוברים לשוק היד השנייה.")


def insight_leasing_origin(origin_share, full_years):
    lab = ORIGIN_LABEL["החכר"]
    yrs = [y for y in full_years if y in origin_share]
    if len(yrs) < 2:
        return None
    a, b = origin_share[yrs[0]].get(lab, 0.0), origin_share[yrs[-1]].get(lab, 0.0)
    if max(a, b) < 0.05:
        return None
    if abs(b - a) < 0.02:
        return (f"כ-{_pct(b, 0)} מהרכבים הפרטיים שעלו לכביש ב-{yrs[-1]} סווגו כרכבי החכר (ליסינג), "
                f"שיעור דומה ל-{yrs[0]} ({_pct(a, 0)}).")
    word = "עלה" if b > a else "ירד"
    return (f"שיעור רכבי ההחכר (ליסינג) בין הרכבים שעלו לכביש {word} מ-{_pct(a)} ב-{yrs[0]} "
            f"ל-{_pct(b)} ב-{yrs[-1]}.")


def insight_hands(hist, n_veh, max_hands):
    if n_veh == 0:
        return None
    one = hist.get(1, 0) / n_veh
    five = sum(v for k, v in hist.items() if k >= 5) / n_veh
    return (f"{_pct(one)} מהרכבים רשומים עם רשומת בעלות אחת בלבד, ו-{_pct(five)} עם חמש רשומות "
            f"ומעלה; השיא הוא {_int(max_hands)} רשומות בעלות לרכב אחד.")


def insight_still_first(still_rows):
    rows = [r for r in still_rows if r["n_lease"] >= 1000 and r["n_reg"] >= 1000]
    if not rows:
        return None
    r = rows[0]
    gap = r["reg_share"] - r["lease_share"]
    if abs(gap) < 0.1:
        return None
    tail = ("רכבי ליסינג מחליפים ידיים מהר יותר" if gap > 0
            else "רכבי ליסינג נשארים אצל הבעלים הראשונים זמן רב יותר")
    return (f"מבין הרכבים שעלו לכביש ב-{r['year']}, {_pct(r['lease_share'])} מרכבי ההחכר עדיין "
            f"אצל הבעלים הראשונים, לעומת {_pct(r['reg_share'])} מהרכבים הרגילים: "
            f"{tail}.")


def insight_km(km_origin_rows):
    rows = [r for r in km_origin_rows if r.get("lease") and r.get("reg")]
    if not rows:
        return None
    r = rows[0]
    ratio = r["lease"] / r["reg"]
    if abs(ratio - 1) < 0.1:
        return None
    word = "גבוה" if ratio > 1 else "נמוך"
    return (f"ברכבים שעלו לכביש ב-{r['year']}, חציון הקילומטראז' במבחן האחרון של רכבי החכר "
            f"({_int(r['lease'])} ק\"מ) {word} ב-{_pct(abs(ratio - 1), 0)} מזה של רכבים רגילים "
            f"({_int(r['reg'])} ק\"מ).")


def insight_mods(mod_rows, n_veh):
    s = next((r for r in mod_rows if r["key"] == "shinui_mivne_ind"), None)
    if not s or n_veh == 0 or s["n"] == 0:
        return None
    return (f"{_int(s['n'])} רכבים ({_pct(s['n'] / n_veh, 2)}) רשומים עם שינוי מבנה, "
            f"השינוי הנפוץ ביותר מבין ארבעת סוגי השינויים שהמאגר מתעד.") if s["rank"] == 0 else (
            f"{_int(s['n'])} רכבים ({_pct(s['n'] / n_veh, 2)}) רשומים עם שינוי מבנה.")


# ───────────────────────────── compute ─────────────────────────────

def compute(frames):
    a = frames.pop("vehicles")
    v = _prep_vehicles(a)
    del a
    b = frames.pop("owners")
    o = _prep_owners(b)
    del b

    n_veh = int(len(v))
    n_own = int(len(o))
    latest = v["reg"].max()
    first_year = int(v["ry"].min())
    last_year = int(latest.year)
    partial = not (latest.month == 12 and latest.day == 31)
    years = list(range(first_year, last_year + 1))
    full_years = [y for y in years if y < last_year or not partial]

    # ── first registrations ──
    rc = v.groupby(["ry", "rm"]).size()
    reg_months = {}
    for (y, m), n in rc.items():
        reg_months.setdefault(int(y), {})[int(m)] = int(n)
    reg_year = [sum(reg_months.get(y, {}).values()) for y in years]
    heat = []
    for yi, y in enumerate(years):
        for m in range(1, 13):
            if y == last_year and m > latest.month:
                continue
            heat.append([m - 1, yi, reg_months.get(y, {}).get(m, 0)])
    heat_max = max((c[2] for c in heat), default=0)

    # ── origin by registration year ──
    oc = v.groupby(["origin", "ry"], observed=True).size()
    origin_tot = v["origin"].value_counts()
    origin_tot = origin_tot[origin_tot > 0]
    origin_tot = origin_tot.sort_index().sort_values(ascending=False, kind="stable")
    top_origin = list(origin_tot.index[:ORIGIN_TOP])
    has_other = len(origin_tot) > ORIGIN_TOP
    origin_series = []
    origin_share = {}
    for name in top_origin + ([OTHER] if has_other else []):
        data = []
        for yi, y in enumerate(years):
            if name == OTHER:
                n = sum(int(oc.get((k, y), 0)) for k in origin_tot.index[ORIGIN_TOP:])
            else:
                n = int(oc.get((name, y), 0))
            data.append(n)
            if reg_year[yi]:
                origin_share.setdefault(y, {})[name] = n / reg_year[yi]
        origin_series.append({"name": name, "data": data})
    origin_table = [{"year": str(y), "total": _int(reg_year[yi]),
                     "cells": [_int(sr["data"][yi]) for sr in origin_series]}
                    for yi, y in enumerate(years)]

    # ── ownership records ──
    types = _owner_types(set(o["t"].astype(str).unique()))
    mc = o.groupby(["ym", "t"], observed=True).size()
    months = sorted(int(x) for x in o["ym"].unique())
    own_month_total = o.groupby("ym").size()
    own_month = {int(k): int(n) for k, n in own_month_total.items()}
    own_series = [{"name": OWNER_LABEL.get(t, t),
                   "data": [int(mc.get((ym, t), 0)) for ym in months]} for t in types]
    own_x = [f"{ym // 100}-{ym % 100:02d}" for ym in months]
    oy = o["ym"] // 100
    yc = o.groupby([oy, "t"], observed=True).size()
    own_years = sorted(int(y) for y in oy.unique())
    mix_years = {}
    mix_table = []
    mix_series = {t: [] for t in types}
    for y in own_years:
        tot = sum(int(yc.get((y, t), 0)) for t in types)
        cells = []
        for t in types:
            n = int(yc.get((y, t), 0))
            sh = n / tot if tot else 0.0
            mix_years.setdefault(y, {})[t] = sh
            mix_series[t].append(round(sh * 100, 2))
            cells.append(_pct(sh))
        mix_table.append({"year": str(y), "total": _int(tot), "cells": cells})
    own_type_tot = o["t"].value_counts()

    # ── per-vehicle ownership ──
    g = o.groupby("veh", sort=True)
    cnt = g.size()
    first_ym = g["ym"].min()
    last_ym = g["ym"].max()
    o["first"] = o["veh"].map(first_ym).astype(np.int32)
    fo = o[o["ym"] == o["first"]]
    fo_n = fo.groupby("veh")["t"].nunique()
    fo_t = fo.groupby("veh", observed=True)["t"].first().astype(str)
    first_type = fo_t.where(fo_n == 1, MIXED)
    del fo, fo_n, fo_t
    o.drop(columns=["first"], inplace=True)

    per = pd.DataFrame({"n": cnt, "changed": (last_ym > first_ym), "ft": first_type})
    v = v.set_index("veh").join(per, how="left")
    v["n"] = v["n"].fillna(0).astype(np.int32)
    v["changed"] = v["changed"].fillna(False).astype(bool)
    v["ft"] = v["ft"].fillna("ללא רשומת בעלות")
    del per, cnt, first_ym, last_ym, first_type

    hv = v["n"].clip(upper=HANDS_CAP).value_counts().sort_index()
    hist = {int(k): int(n) for k, n in hv.items() if k > 0}
    max_hands = int(v["n"].max())
    hands_x = [str(k) if k < HANDS_CAP else f"{HANDS_CAP}+" for k in hist]
    hands_y = list(hist.values())
    with_own = v[v["n"] > 0]
    avg_hands = float(with_own["n"].mean()) if len(with_own) else 0.0

    # first owner type by registration year
    fc = v.groupby(["ft", "ry"]).size()
    ft_present = set(v["ft"].unique())
    ft_order = [t for t in _owner_types(ft_present - {MIXED, "ללא רשומת בעלות"})]
    ft_order += [x for x in (MIXED, "ללא רשומת בעלות") if x in ft_present]
    ft_series = []
    for t in ft_order:
        ft_series.append({"name": OWNER_LABEL.get(t, t),
                          "data": [int(fc.get((t, y), 0)) for y in years]})
    ft_table = []
    for yi, y in enumerate(years):
        tot = reg_year[yi]
        ft_table.append({"year": str(y), "cells": [
            _pct(s["data"][yi] / tot) if tot else "0.0%" for s in ft_series]})
    ft_cols = [s["name"] for s in ft_series]

    # still with the first owner, and records per vehicle, by registration year
    lease_lab = ORIGIN_LABEL["החכר"]
    is_lease = v["origin"].astype(str) == lease_lab
    is_reg = v["origin"].astype(str) == ORIGIN_EMPTY
    still = (~v["changed"]) & (v["n"] > 0)
    still_rows = []
    hands_year_rows = []
    sy = {"lease": [], "reg": [], "all": []}
    avg_by_year = []
    for y in years:
        m = v["ry"] == y
        nl, nr, na = int((m & is_lease).sum()), int((m & is_reg).sum()), int(m.sum())
        ls = float(still[m & is_lease].mean()) if nl else 0.0
        rs = float(still[m & is_reg].mean()) if nr else 0.0
        al = float(still[m].mean()) if na else 0.0
        av = float(v.loc[m & (v["n"] > 0), "n"].mean()) if na else 0.0
        if np.isnan(av):
            av = 0.0
        sy["lease"].append(round(ls * 100, 1))
        sy["reg"].append(round(rs * 100, 1))
        sy["all"].append(round(al * 100, 1))
        avg_by_year.append(round(av, 2))
        still_rows.append({"year": y, "lease_share": ls, "reg_share": rs,
                           "n_lease": nl, "n_reg": nr})
        hands_year_rows.append({"year": str(y), "avg": f"{av:.2f}", "all": _pct(al),
                                "lease": _pct(ls) if nl else "", "reg": _pct(rs) if nr else ""})

    # ── odometer ──
    tested = v["km"] >= KM_TESTED
    km_rows = []
    km_chart = {"x": [], "p25": [], "p50": [], "p75": []}
    tested_years = []
    for y in years:
        m = v["ry"] == y
        na = int(m.sum())
        kt = v.loc[m & tested, "km"]
        share = len(kt) / na if na else 0.0
        if share >= KM_COHORT_MIN_SHARE and len(kt):
            q = kt.quantile([0.25, 0.5, 0.75])
            km_chart["x"].append(str(y))
            km_chart["p25"].append(int(round(q.iloc[0])))
            km_chart["p50"].append(int(round(q.iloc[1])))
            km_chart["p75"].append(int(round(q.iloc[2])))
            tested_years.append(y)
            km_rows.append({"year": str(y), "share": _pct(share), "p25": _int(q.iloc[0]),
                            "p50": _int(q.iloc[1]), "p75": _int(q.iloc[2])})
        else:
            km_rows.append({"year": str(y), "share": _pct(share), "p25": "", "p50": "", "p75": ""})
    km_all = v.loc[tested & v["ry"].isin(tested_years), "km"]
    km_median = float(km_all.median()) if len(km_all) else 0.0

    # km by origin, per tested registration year (origins with enough tested cars)
    km_origin_names = [n for n in (ORIGIN_EMPTY, lease_lab, "השכרה") if n in set(v["origin"].astype(str))]
    km_origin = {"x": [str(y) for y in tested_years], "series": []}
    kt = v.loc[tested, ["ry", "origin", "km"]]
    kq = kt.groupby(["ry", "origin"], observed=True)["km"].agg(["median", "size"])
    for name in km_origin_names:
        data = []
        for y in tested_years:
            if (y, name) in kq.index and kq.loc[(y, name), "size"] >= 500:
                data.append(int(round(kq.loc[(y, name), "median"])))
            else:
                data.append(None)
        km_origin["series"].append({"name": name, "data": data})
    km_origin_table = [{"year": str(y),
                        "cells": [_int(s["data"][i]) if s["data"][i] is not None else ""
                                  for s in km_origin["series"]]}
                       for i, y in enumerate(tested_years)]
    # map series names to keys for the insight
    name_key = {ORIGIN_EMPTY: "reg", lease_lab: "lease", "השכרה": "rent"}
    km_origin_rows = []
    for i, y in enumerate(tested_years):
        row = {"year": y}
        for s in km_origin["series"]:
            row[name_key[s["name"]]] = s["data"][i]
        km_origin_rows.append(row)
    del kt, kq

    # odometer distribution (tested cohorts), 25k bins
    bins = list(range(0, 400001, 25000))
    kb = pd.cut(km_all, bins=bins + [np.inf], right=False, labels=False)
    kbc = kb.value_counts().sort_index()
    km_hist_x = [f"{bins[i] // 1000}-{bins[i + 1] // 1000}" if i + 1 < len(bins) else f"{bins[i] // 1000}+"
                 for i in range(len(bins))]
    km_hist_y = [int(kbc.get(i, 0)) for i in range(len(bins))]
    km_hist_table = [{"bin": x, "n": _int(n)} for x, n in zip(km_hist_x, km_hist_y)]

    # ── vehicle changes ──
    mod_names = {"shinui_mivne_ind": "שינוי מבנה", "shinui_zmig_ind": "שינוי צמיגים",
                 "shnui_zeva_ind": "שינוי צבע", "gapam_ind": "התקנת גפ״מ (גז)"}
    mod_rows = []
    for key, name in mod_names.items():
        n = int(v[key].sum())
        mod_rows.append({"key": key, "name": name, "n": n})
    mod_rows.sort(key=lambda r: (-r["n"], r["name"]))
    for i, r in enumerate(mod_rows):
        r["rank"] = i
    mod_year = {"x": [str(y) for y in years], "series": []}
    rate = v.groupby("ry")[[r["key"] for r in mod_rows]].mean()
    for r in mod_rows:
        mod_year["series"].append({"name": r["name"], "data": [
            round(float(rate.loc[y, r["key"]]) * 100, 3) if y in rate.index else 0.0 for y in years]})
    mod_table = [{"name": r["name"], "count": _int(r["n"]), "share": _pct(r["n"] / n_veh, 2)}
                 for r in mod_rows]
    mod_year_table = [{"year": str(y), "cells": [f"{s['data'][i]:.2f}%" for s in mod_year["series"]]}
                      for i, y in enumerate(years)]

    # ── KPIs ──
    lease_share = float(is_lease.mean()) if n_veh else 0.0
    ytd_text = insight_reg_ytd(reg_months, latest, partial)
    last_full = latest.month if latest.is_month_end else latest.month - 1
    cur = sum(reg_months.get(last_year, {}).get(m, 0) for m in range(1, max(last_full, 0) + 1))
    prev = sum(reg_months.get(last_year - 1, {}).get(m, 0) for m in range(1, max(last_full, 0) + 1))
    if partial and prev and last_full >= 1:
        ch = (cur - prev) / prev
        sign = "+" if ch > 0 else ("−" if ch < 0 else "")
        ytd_kpi = {"value": round(ch * 100, 1), "display": f"{sign}{abs(ch) * 100:.1f}%",
                   "tone": "ok" if ch >= 0.03 else ("danger" if ch <= -0.03 else "brand")}
        span = MONTHS_HE[0] if last_full == 1 else f"{MONTHS_HE[0]} עד {MONTHS_HE[last_full - 1]}"
        ytd_label = f"שינוי בעלייה לכביש, {span} {last_year} לעומת {last_year - 1}"
    else:
        ly, py = full_years[-1], full_years[-2] if len(full_years) > 1 else full_years[-1]
        c, p = reg_year[years.index(ly)], reg_year[years.index(py)]
        ch = (c - p) / p if p else 0.0
        sign = "+" if ch > 0 else ("−" if ch < 0 else "")
        ytd_kpi = {"value": round(ch * 100, 1), "display": f"{sign}{abs(ch) * 100:.1f}%",
                   "tone": "ok" if ch >= 0.03 else ("danger" if ch <= -0.03 else "brand")}
        ytd_label = f"שינוי בעלייה לכביש, {ly} לעומת {py}"

    dealer_share_last = mix_years.get(own_years[-1], {}).get("סוחר", 0.0) if own_years else 0.0

    kpis = {
        "vehicles": {"value": n_veh, "display": _int(n_veh), "tone": "brand"},
        "records": {"value": n_own, "display": _int(n_own), "tone": "brand"},
        "avg_hands": {"value": round(avg_hands, 2), "display": f"{avg_hands:.2f}", "tone": "info"},
        "lease": {"value": round(lease_share * 100, 1), "display": _pct(lease_share), "tone": "brand"},
        "km": {"value": int(round(km_median)), "display": _int(km_median), "tone": "brand"},
        "ytd": ytd_kpi,
        "dealer": {"value": round(dealer_share_last * 100, 1), "display": _pct(dealer_share_last),
                   "tone": "brand"},
        "years": {"value": [first_year, last_year], "display": f"{first_year}–{last_year}", "tone": "brand"},
    }

    # ── insights ──
    rules = [
        ("reg_ytd", ytd_text),
        ("jan_peak", insight_jan(reg_months, full_years)),
        ("leasing_origin", insight_leasing_origin(origin_share, full_years)),
        ("dealer_share", insight_dealer(mix_years, [y for y in own_years if y < (own_years[-1] if partial else own_years[-1] + 1)])),
        ("still_first", insight_still_first(still_rows)),
        ("km_lease", insight_km(km_origin_rows)),
        ("hands", insight_hands(hist, int(len(with_own)), max_hands)),
        # The newest ownership month may be partial: keep it out of the dip search.
        ("dip", insight_dip({k: v for k, v in own_month.items() if k != max(own_month)}
                            if own_month else own_month)),
        ("mods", insight_mods(mod_rows, n_veh)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    # ── labels ──
    lm = months[-1] if months else 0
    peak_reg_i = int(np.argmax(reg_year)) if reg_year else 0
    oldest_still = still_rows[0] if still_rows else None
    km_first = km_rows[0] if km_rows else None
    span_txt = f"{first_year} עד {last_year}"
    partial_note = (f" שנת {last_year} חלקית: הנתונים מגיעים עד {latest.day} ב{MONTHS_HE[latest.month - 1]} {last_year}."
                    if partial else "")
    labels = {
        "notes": "המאגרים מציגים נתונים אודות כלי רכב פרטיים פעילים החל משנת 2017.",
        "lede": (f"המאגר של משרד התחבורה מתעד {_int(n_veh)} כלי רכב פרטיים פעילים שעלו לכביש "
                 f"מ-{first_year} ואילך, ולצדם {_int(n_own)} רשומות בעלות: מתי עבר כל רכב יד ולאיזה סוג "
                 f"בעלים (פרטי, החכר, סוחר, חברה או השכרה). בעמוד: עלייה לכביש לפי חודש, מקוריות הרכב, "
                 f"מספר הידיים, קילומטראז' במבחן הרישוי האחרון ושינויים שנרשמו ברכב."),
        "lookup_title": "בדיקת היסטוריית רכב: בעלויות קודמות וקילומטראז' ←",
        "lookup_sub": ("חיפוש חי בכל רשומות המאגר לפי מספר רכב: תאריך עלייה לכביש, מקוריות, "
                       "קילומטראז' במבחן האחרון, שינויים ורשומות הבעלות."),
        "years_kpi": "שנות עלייה לכביש",
        "vehicles_kpi": "כלי רכב פרטיים פעילים במאגר",
        "records_kpi": "רשומות בעלות",
        "avg_hands_kpi": "רשומות בעלות בממוצע לרכב",
        "lease_kpi": "רכבים שמקוריותם החכר (ליסינג)",
        "km_kpi": f"חציון קילומטראז' במבחן האחרון (רכבים שעברו מבחן שנתי, ק\"מ)",
        "ytd_kpi": ytd_label,
        "dealer_kpi": f"חלק הסוחרים ברשומות הבעלות ({own_years[-1]})" if own_years else "חלק הסוחרים",
        "reg_year_note": (f"מספר הרכבים הפרטיים שעדיין פעילים, לפי שנת העלייה לכביש. "
                          f"השנה הגדולה ביותר: {years[peak_reg_i]} עם {_int(reg_year[peak_reg_i])} רכבים." + partial_note),
        "reg_year_aria": (f"תרשים עמודות: רכבים פרטיים פעילים לפי שנת עלייה לכביש, {span_txt}. "
                          f"השיא ב-{years[peak_reg_i]} עם {_int(reg_year[peak_reg_i])} רכבים."),
        "reg_year_caption": f"רכבים פרטיים פעילים לפי שנת עלייה לכביש, {span_txt}",
        "heat_note": ("כל משבצת היא מספר הרכבים שעלו לכביש באותו חודש. עמודת ינואר בולטת כמעט בכל שנה."
                      ) if insight_jan(reg_months, full_years) else
                     "כל משבצת היא מספר הרכבים שעלו לכביש באותו חודש.",
        "heat_aria": (f"מפת חום: עלייה לכביש לפי חודש ושנה, {span_txt}. "
                      f"החודש העמוס ביותר: {_int(heat_max)} רכבים."),
        "origin_note": (f"מקוריות הרכב כפי שנרשמה במשרד התחבורה, לפי שנת העלייה לכביש. "
                        f"הקבוצה הגדולה: {origin_tot.index[0]} ({_pct(origin_tot.iloc[0] / n_veh) if n_veh else ''}); "
                        f"מקוריות שאינה בין {ORIGIN_TOP} הגדולות מקובצת תחת {OTHER}."),
        "origin_aria": (f"תרשים עמודות מוערמות: מקוריות הרכבים לפי שנת עלייה לכביש, {span_txt}. "
                        f"{_pct(lease_share)} מכלל הרכבים הם רכבי החכר."),
        "origin_caption": "רכבים לפי שנת עלייה לכביש ומקוריות",
        "ft_note": ("סוג הבעלים הראשון של כל רכב, לפי רשומת הבעלות שבחודש העלייה לכביש. "
                    "כשבאותו חודש נרשמו כמה סוגי בעלים, הרכב מסווג בנפרד."),
        "ft_aria": f"תרשים עמודות מוערמות: סוג הבעלים הראשון לפי שנת עלייה לכביש, {span_txt}.",
        "ft_caption": "סוג הבעלים הראשון לפי שנת עלייה לכביש (אחוז מהרכבים)",
        "own_month_note": (f"רשומות הבעלות לפי חודש וסוג בעלים, {own_x[0] if own_x else ''} עד {own_x[-1] if own_x else ''}. "
                           f"כל רשומה היא תחילת בעלות; החודש האחרון ({_month_name(lm) if lm else ''}) עשוי להיות חלקי."),
        "own_month_aria": (f"תרשים עמודות מוערמות: רשומות בעלות לפי חודש וסוג בעלים. "
                           f"סך הכול {_int(n_own)} רשומות."),
        "mix_note": ("התפלגות רשומות הבעלות בכל שנה לפי סוג בעלים. המאגר כולל רק רכבים שעלו לכביש "
                     f"מ-{first_year}, ולכן חלקן של העסקאות ביד שנייה גדל עם השנים."),
        "mix_aria": (f"תרשים שטח מוערם: התפלגות רשומות הבעלות לפי סוג בעלים, {own_years[0] if own_years else ''} "
                     f"עד {own_years[-1] if own_years else ''}. חלק הסוחרים ב-{own_years[-1] if own_years else ''}: {_pct(dealer_share_last)}."),
        "mix_caption": "רשומות בעלות לפי שנה וסוג בעלים",
        "hands_note": (f"מספר רשומות הבעלות של כל רכב, כולל הבעלים הראשונים. "
                       f"בממוצע {avg_hands:.2f} רשומות לרכב; השיא: {_int(max_hands)}."),
        "hands_aria": (f"תרשים עמודות: התפלגות הרכבים לפי מספר רשומות הבעלות. "
                       f"{_pct(hist.get(1, 0) / len(with_own)) if len(with_own) else ''} עם רשומה אחת."),
        "hands_caption": "רכבים לפי מספר רשומות בעלות",
        "still_note": ("שיעור הרכבים שלא נרשמה להם בעלות חדשה אחרי חודש העלייה לכביש, לפי שנת העלייה, "
                       "בנפרד לרכבי החכר ולרכבים רגילים, וממוצע רשומות הבעלות לרכב."),
        "still_aria": ("תרשים קווים: שיעור הרכבים שעדיין אצל הבעלים הראשונים לפי שנת עלייה לכביש. "
                       + (f"מבין שנת {oldest_still['year']}: {_pct(oldest_still['lease_share'])} מרכבי ההחכר "
                          f"ו-{_pct(oldest_still['reg_share'])} מהרכבים הרגילים." if oldest_still else "")),
        "still_caption": "שיעור הרכבים אצל הבעלים הראשונים וממוצע רשומות בעלות, לפי שנת עלייה לכביש",
        "km_note": (f"הקילומטראז' שנמדד במבחן הרישוי האחרון, לפי שנת העלייה לכביש: חציון ורבעונים. "
                    f"מוצגות רק שנים שבהן {_pct(KM_COHORT_MIN_SHARE, 0)} מהרכבים לפחות רשומים עם "
                    f"{_int(KM_TESTED)} ק\"מ ומעלה; ברכבים חדשים יותר נרשמה רק בדיקת הרישום הראשונה."),
        "km_aria": (f"תרשים קו עם רצועה: חציון הקילומטראז' במבחן האחרון לפי שנת עלייה לכביש. "
                    + (f"ברכבים משנת {km_first['year']}: {km_first['p50']} ק\"מ." if km_first and km_first['p50'] else "")),
        "km_caption": "קילומטראז' במבחן האחרון לפי שנת עלייה לכביש (ק\"מ)",
        "km_origin_note": (f"חציון הקילומטראז' במבחן האחרון לפי שנת עלייה לכביש ומקוריות "
                           f"(קבוצות עם {_int(500)} רכבים שנבדקו לפחות)."),
        "km_origin_aria": "תרשים עמודות: חציון קילומטראז' של רכבים רגילים, רכבי החכר ורכבי השכרה לפי שנת עלייה לכביש.",
        "km_origin_caption": "חציון קילומטראז' לפי שנת עלייה לכביש ומקוריות (ק\"מ)",
        "km_hist_note": (f"התפלגות הקילומטראז' של {_int(len(km_all))} רכבים שעלו לכביש ב-"
                         f"{tested_years[0] if tested_years else ''} עד {tested_years[-1] if tested_years else ''}, "
                         f"במדרגות של {_int(25000)} ק\"מ."),
        "km_hist_aria": f"היסטוגרמה: רכבים לפי קילומטראז' במבחן האחרון. החציון: {_int(km_median)} ק\"מ.",
        "km_hist_caption": "רכבים לפי טווח קילומטראז' (אלפי ק\"מ)",
        "mods_note": "ארבעת סוגי השינויים שהמאגר מתעד לכל רכב, ושיעורם לפי שנת העלייה לכביש.",
        "mods_aria": (f"תרשים עמודות: רכבים עם שינויים רשומים. הנפוץ: {mod_rows[0]['name']} "
                      f"עם {_int(mod_rows[0]['n'])} רכבים."),
        "mods_caption": "רכבים לפי סוג שינוי",
        "mods_year_aria": "תרשים קווים: שיעור הרכבים עם כל סוג שינוי לפי שנת עלייה לכביש.",
        "mods_year_caption": "שיעור הרכבים עם שינוי לפי שנת עלייה לכביש",
    }

    summary = (f"בדיקת היסטוריית רכב לפי מספר רכב: בעלויות קודמות, ליסינג וקילומטראז' ב-{_int(n_veh)} "
               f"רכבים פרטיים מ-{first_year}, בממוצע {avg_hands:.2f} רשומות בעלות לרכב.")

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "suggested_tags": ["רכב", "היסטוריית רכב", "בעלות רכב", "ליסינג", "יד שנייה", "קילומטראז'"],
            "related_ids": ["392abd0a-64f6-4c18-9d56-0111001411e6",
                            "1c8e79c5-0ddb-461f-84ea-5bdcbaefaef4",
                            "11369651-1c70-4d8f-8090-ee49354a7c52",
                            "35c791ca-8db2-4657-8c6f-eb092147a6bb",
                            "0f16b39a-6016-408d-805d-31f40d5a0990"],
            "temporal_coverage": f"{first_year}/{last_year}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": {
            "reg_year": {"x": [str(y) for y in years], "y": reg_year,
                         "partial": partial},
            "heat": {"x": MONTHS_HE, "y": [str(y) for y in years], "cells": heat, "max": heat_max},
            "origin": {"x": [str(y) for y in years], "series": origin_series},
            "first_owner": {"x": [str(y) for y in years], "series": ft_series, "totals": reg_year},
            "own_month": {"x": own_x, "series": own_series},
            "own_mix": {"x": [str(y) for y in own_years],
                        "series": [{"name": OWNER_LABEL.get(t, t), "data": mix_series[t]} for t in types]},
            "hands": {"x": hands_x, "y": hands_y},
            "still": {"x": [str(y) for y in years], "lease": sy["lease"], "reg": sy["reg"],
                      "all": sy["all"], "avg": avg_by_year},
            "km": km_chart,
            "km_origin": km_origin,
            "km_hist": {"x": km_hist_x, "y": km_hist_y},
            "mods": {"names": [r["name"] for r in mod_rows], "values": [r["n"] for r in mod_rows]},
            "mods_year": mod_year,
        },
        "tables": {
            "reg_year": [{"year": str(y), "n": _int(n)} for y, n in zip(years, reg_year)],
            "origin": origin_table,
            "origin_cols": [sr["name"] for sr in origin_series],
            "first_owner": ft_table,
            "first_owner_cols": ft_cols,
            "mix": mix_table,
            "mix_cols": [OWNER_LABEL.get(t, t) for t in types],
            "hands": [{"k": x, "n": _int(n)} for x, n in zip(hands_x, hands_y)],
            "still": hands_year_rows,
            "km": km_rows,
            "km_origin": km_origin_table,
            "km_origin_cols": [s["name"] for s in km_origin["series"]],
            "km_hist": km_hist_table,
            "mods": mod_table,
            "mods_year": mod_year_table,
            "mods_cols": [r["name"] for r in mod_rows],
        },
        "insights": insights,
        "labels": labels,
    }
