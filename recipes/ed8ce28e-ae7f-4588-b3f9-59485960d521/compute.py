"""משקלות ומידות — approved models of measuring instruments (Ministry of Economy).

One row per approved instrument MODEL (a type approval, "אישור דגם"): an
equipment group (counter scale, bridge scale, fuel-station meter, bathroom
scale …), a capacity/range, the manufacturer, the model designation, the
approval certificate number, its validity date and an is-valid flag. A single
certificate can cover several models. Manufacturers are businesses and are
named; there are no private persons in the data.

Certificate numbers end in a two-digit year ("IL 104-99", "WM 0623/4-15ks"):
that is the approval year. "IL" certificates are for trade (commercial) use
and run ~10 years; "WM" are household/personal scales and run ~5 years.

"Now" is never the wall clock: the reference year is inferred from the
upstream is_valid flag — the day after the latest expiry date among models
flagged NOT valid. Approvals in that year are partial and labelled so.
"""
import re

import pandas as pd

TOP_GROUPS = 12
TOP_MAKERS = 15
LRI, PDI = "⁦", "⁩"
SEG_COM, SEG_HOME, SEG_UNK = "שימוש מסחרי", "שימוש ביתי ואישי", "לא צוין"
SEG_ORDER = [SEG_COM, SEG_HOME, SEG_UNK]
PLACEHOLDER_MAKERS = {"", "כללי"}       # not a real manufacturer
HOME_PREFIX = re.compile(r"^מאזניים לשימוש אישי וביתי\s*[–-]\s*")
CERT_YEAR = re.compile(r"^\s*([A-Za-z]{2})\s*[^-]*-\s*(\d{2})(?!\d)")
TONS = re.compile(r"^0*(\d+)\s*טון")
SIZE_BUCKETS = [(1, 1), (2, 5), (6, 20), (21, None)]


def n(v):
    return f"{int(v):,}"


def pct(v, digits=1):
    return f"{LRI}{v:.{digits}f}%{PDI}"


def short_group(g):
    s = HOME_PREFIX.sub("", g)
    return s if s == g else f"{s} (ביתי)"


def _sorted_counts(s):
    vc = s.value_counts()
    return vc.sort_index().sort_values(ascending=False, kind="stable")


def _prepare(df):
    out = pd.DataFrame({
        "group": df["equipment_group"].str.strip().replace("", "לא צוין"),
        "dtype": df["device_type"].str.strip(),
        "maker_id": df["manufacter_id"].str.strip(),
        "maker": df["manufacter_name"].str.strip(),
        "model_id": df["model_id"].str.strip(),
        "cert": df["eqitf_confirmation_number"].str.strip(),
        "exp": pd.to_datetime(df["eqitf_confirmation_validity"].str.strip(),
                              format="%d/%m/%Y", errors="coerce"),
        "valid": df["is_valid"].str.strip() == "כן",
    })
    com = df["eqitf_is_commercial"].str.strip().str.upper()
    out["seg"] = com.map({"Y": SEG_COM, "N": SEG_HOME}).fillna(SEG_UNK)
    m = out["cert"].str.extract(CERT_YEAR)
    yy = pd.to_numeric(m[1], errors="coerce")
    out["prefix"] = m[0].str.upper()
    out["ay"] = (yy + 2000).where(yy < 50, yy + 1900)
    out["ey"] = out["exp"].dt.year
    out["maker_key"] = out["maker_id"].where(out["maker_id"] != "", "name:" + out["maker"])
    return out


def _as_of(df):
    """Reference date implied by the upstream is_valid flag."""
    exp_inv = df.loc[~df["valid"], "exp"].dropna()
    exp_val = df.loc[df["valid"], "exp"].dropna()
    if len(exp_inv):
        return exp_inv.max() + pd.Timedelta(days=1)
    if len(exp_val):
        return exp_val.min()
    return None


# ── insight rules ───────────────────────────────────────────────────────
def insight_valid(df, total, valid_n, seg_valid):
    if total == 0:
        return None
    s = f"רק {n(valid_n)} מתוך {n(total)} הדגמים במאגר ({pct(valid_n / total * 100)}) מסומנים כבעלי אישור בתוקף; השאר הם אישורים שפגו ונשמרים במאגר."
    parts = []
    for seg in (SEG_COM, SEG_HOME):
        tot, v = seg_valid.get(seg, (0, 0))
        if tot >= 20:
            parts.append(f"ב{seg} {pct(v / tot * 100)} בתוקף ({n(v)} מתוך {n(tot)})")
    if len(parts) == 2:
        s += " " + "; ".join(parts) + "."
    return s


def insight_legacy(df, grp_stats):
    """A big group with (almost) no valid models — usually a retired classification."""
    cand = grp_stats[(grp_stats["n"] >= 100) & (grp_stats["v"] / grp_stats["n"] <= 0.02)]
    if cand.empty:
        return None
    g = cand.index[0]
    r = cand.loc[g]
    vtxt = "אף אחד מהם אינו בתוקף" if r["v"] == 0 else f"רק {n(r['v'])} מהם בתוקף"
    s = f"הקבוצה \"{g}\" מונה {n(r['n'])} דגמים — {vtxt}."
    if pd.notna(r["last_exp"]):
        s += f" האישורים שפגו בה פקעו עד {int(r['last_exp'])}"
        succ = grp_stats[grp_stats.index.str.match(HOME_PREFIX) & (grp_stats["v"] > 0)]
        if len(succ) >= 2 and r["seg"] == SEG_HOME:
            s += (f", ואת מקומה תפסו {n(len(succ))} קבוצות משנה של מאזניים לשימוש אישי וביתי "
                  f"עם {n(succ['v'].sum())} דגמים בתוקף")
        s += "."
    return s


def insight_empty_groups(grp_stats):
    zero = grp_stats[grp_stats["v"] == 0]
    if len(zero) < 2:
        return None
    names = list(zero.sort_values("n", ascending=False, kind="stable").index[:3])
    return (f"ב-{n(len(zero))} מתוך {n(len(grp_stats))} קבוצות הציוד אין כיום אף דגם בתוקף "
            f"(למשל {', '.join(names)}), אף שבמאגר רשומים בהן יחד {n(zero['n'].sum())} דגמים.")


def insight_term(df):
    t = df[(df["term"] >= 0) & (df["term"] <= 20)]
    parts = []
    for seg in (SEG_COM, SEG_HOME):
        x = t[t["seg"] == seg]["term"]
        if len(x) >= 30:
            parts.append((seg, int(x.median()), (x == x.median()).mean()))
    if len(parts) < 2 or parts[0][1] == parts[1][1]:
        return None
    (s1, m1, f1), (s2, m2, f2) = parts
    return (f"משך האישור שונה בין המגזרים: אישור ל{s1} תקף בדרך כלל {n(m1)} שנים "
            f"({pct(f1 * 100, 0)} מהדגמים), ואישור ל{s2} — {n(m2)} שנים ({pct(f2 * 100, 0)}); "
            f"לפי שנת האישור שבמספר התעודה ושנת פקיעתו.")


def insight_makers(valid, mk_names):
    vm = _sorted_counts(valid[~valid["maker"].isin(PLACEHOLDER_MAKERS)]["maker_key"])
    if len(vm) < 3:
        return None
    total_v = int(vm.sum())
    (k1, v1), (k2, v2), (k3, v3) = list(vm.head(3).items())
    if v1 / total_v < 0.03:
        return None
    single = int((vm == 1).sum())
    return (f"{n(len(vm))} יצרנים מחזיקים כיום דגם בתוקף. המובילים: {mk_names[k1]} ({n(v1)} דגמים), "
            f"{mk_names[k2]} ({n(v2)}) ו-{mk_names[k3]} ({n(v3)}); "
            f"ל-{n(single)} יצרנים ({pct(single / len(vm) * 100)}) יש דגם בתוקף אחד בלבד.")


def insight_trend(df, ref_year):
    a = df.dropna(subset=["ay"])
    last = ref_year - 1
    if last not in set(a["ay"]):
        return None
    win = 5
    rec = a[(a["ay"] > last - win) & (a["ay"] <= last)]
    prev = a[(a["ay"] > last - 2 * win) & (a["ay"] <= last - win)]
    if len(prev) < 50:
        return None
    r1, r0 = len(rec) / win, len(prev) / win
    chg = r1 / r0 - 1
    seg_rec = rec["seg"].value_counts()
    home_share = seg_rec.get(SEG_HOME, 0) / len(rec) if len(rec) else 0
    span1 = f"{last - win + 1}–{last}"
    span0 = f"{last - 2 * win + 1}–{last - win}"
    if abs(chg) < 0.05:
        s = f"קצב האישורים יציב: כ-{n(round(r1))} דגמים בשנה ב-{span1}, בדומה ל-{span0} ({n(round(r0))})."
    else:
        word = "עלה" if chg > 0 else "ירד"
        s = (f"קצב אישורי הדגמים {word}: כ-{n(round(r1))} דגמים בשנה ב-{span1}, לעומת כ-{n(round(r0))} "
             f"ב-{span0} ({pct(abs(chg) * 100, 0)} {'יותר' if chg > 0 else 'פחות'}).")
    if home_share >= 0.5:
        s += f" {pct(home_share * 100, 0)} מהדגמים שאושרו ב-{span1} הם מאזניים לשימוש ביתי ואישי."
    return s


def insight_expiry(valid, ref_year):
    ev = valid.dropna(subset=["ey"])
    if len(ev) < 20:
        return None
    per = ev["ey"].astype(int).value_counts().sort_index()
    soon = int(per[per.index <= ref_year + 1].sum())
    peak_y = int(per.sort_index().idxmax())
    s = (f"מבין {n(len(ev))} הדגמים שבתוקף, {n(soon)} ({pct(soon / len(ev) * 100)}) יפקעו עד סוף "
         f"{ref_year + 1} אם לא יחודשו.")
    if peak_y > ref_year + 1:
        s += f" גל הפקיעה הגדול ביותר צפוי ב-{peak_y}, עם {n(per[peak_y])} דגמים."
    return s


def insight_certs(df):
    c = df[df["cert"].str.len() >= 3].groupby("cert").size()
    if len(c) < 20:
        return None
    multi = c[c > 1]
    if multi.empty:
        return None
    covered = int(multi.sum())
    return (f"{n(len(df))} הדגמים נשענים על {n(len(c))} תעודות אישור בלבד: {n(len(multi))} תעודות "
            f"מכסות כל אחת כמה דגמים (יחד {n(covered)} דגמים), והגדולה שבהן — {n(multi.max())} דגמים.")


def insight_missing(df):
    miss = df[df["exp"].isna()]
    if len(miss) < 10:
        return None
    vmiss = int(miss["valid"].sum())
    no_cert = int((miss["cert"] == "").sum())
    tail = "כולם מסומנים כלא בתוקף" if vmiss == 0 else f"{n(vmiss)} מהם מסומנים כבתוקף"
    return (f"ל-{n(len(miss))} דגמים לא רשום תאריך תוקף ({n(no_cert)} מהם גם ללא מספר תעודה), ו{tail}; "
            f"הם נספרים בסיכומים אך לא בגרפי השנים.")


def compute(frames):
    df = _prepare(frames["main"])
    total = len(df)
    as_of = _as_of(df)
    ref_year = int(as_of.year) if as_of is not None else int(df["ay"].max())
    df["term"] = df["ey"] - df["ay"]
    valid = df[df["valid"]]
    valid_n = len(valid)

    # maker display names (first non-empty name per key, deterministic)
    nm = df[["maker_key", "maker"]].sort_values(["maker_key", "maker"], kind="stable")
    mk_names = nm.groupby("maker_key")["maker"].max().replace("", "לא צוין").to_dict()

    seg_valid = {}
    for seg in SEG_ORDER:
        x = df[df["seg"] == seg]
        if len(x):
            seg_valid[seg] = (len(x), int(x["valid"].sum()))

    # group stats
    g = df.groupby("group")
    grp_stats = pd.DataFrame({
        "n": g.size(),
        "v": g["valid"].sum().astype(int),
        "makers": g["maker_key"].nunique(),
        "vmakers": valid.groupby("group")["maker_key"].nunique(),
        "seg": g["seg"].agg(lambda s: s.value_counts().sort_index().idxmax()),
        "last_exp": df[~df["valid"]].groupby("group")["ey"].max(),
    }).fillna({"vmakers": 0})
    grp_stats["vmakers"] = grp_stats["vmakers"].astype(int)
    grp_stats = grp_stats.sort_index().sort_values("n", ascending=False, kind="stable")

    # 1. groups: valid vs expired, top-N + other
    top = grp_stats.head(TOP_GROUPS)
    rest = grp_stats.iloc[TOP_GROUPS:]
    gnames = [short_group(x) for x in top.index]
    gv = [int(v) for v in top["v"]]
    ge = [int(a - b) for a, b in zip(top["n"], top["v"])]
    if len(rest):
        gnames.append(f"אחר ({n(len(rest))} קבוצות)")
        gv.append(int(rest["v"].sum()))
        ge.append(int(rest["n"].sum() - rest["v"].sum()))
    groups_chart = {"names": gnames, "full": list(top.index) + (["אחר"] if len(rest) else []),
                    "valid": gv, "expired": ge}
    groups_table = [{"name": x, "n": n(r["n"]), "v": n(r["v"]), "vmakers": n(r["vmakers"])}
                    for x, r in grp_stats.iterrows()]

    # 2. treemap of valid models: segment → group
    tree = []
    vg = valid.groupby(["seg", "group"]).size()
    for seg in SEG_ORDER:
        if seg not in vg.index.get_level_values(0):
            continue
        kids = vg[seg].sort_index().sort_values(ascending=False, kind="stable")
        tree.append({"name": seg, "value": int(kids.sum()), "seg": SEG_ORDER.index(seg),
                     "children": [{"name": short_group(k), "value": int(v)} for k, v in kids.items()]})
    tree_table = [{"seg": seg, "group": short_group(k), "v": n(v)}
                  for seg in SEG_ORDER if seg in vg.index.get_level_values(0)
                  for k, v in vg[seg].sort_index().sort_values(ascending=False, kind="stable").items()]

    # 3. approvals by certificate year, by segment
    a = df.dropna(subset=["ay"]).copy()
    a["ay"] = a["ay"].astype(int)
    a = a[a["ay"] <= ref_year]
    years = list(range(int(a["ay"].min()), ref_year + 1)) if len(a) else []
    ylab = [f"{y} (חלקית)" if y == ref_year else str(y) for y in years]
    segs_a = [s for s in SEG_ORDER if s in set(a["seg"])]
    ay = a.groupby(["ay", "seg"]).size().unstack(fill_value=0).reindex(years, fill_value=0)
    av = a[a["valid"]].groupby("ay").size().reindex(years, fill_value=0)
    approvals_chart = {"x": ylab, "series": [{"name": s, "data": [int(v) for v in ay[s]]} for s in segs_a]}
    approvals_table = [{"year": ylab[i], "cells": [n(ay[s].iloc[i]) for s in segs_a],
                        "valid": n(av.iloc[i])} for i in range(len(years))]
    unparsed = total - len(a)
    last_full = ref_year - 1
    lf_n = int(ay.loc[last_full].sum()) if last_full in ay.index else 0
    pv_n = int(ay.loc[last_full - 1].sum()) if (last_full - 1) in ay.index else 0

    # 4. expiry of currently valid models, by year and segment
    ev = valid.dropna(subset=["ey"]).copy()
    ev["ey"] = ev["ey"].astype(int)
    eyears = list(range(int(ev["ey"].min()), int(ev["ey"].max()) + 1)) if len(ev) else []
    segs_e = [s for s in SEG_ORDER if s in set(ev["seg"])]
    ex = ev.groupby(["ey", "seg"]).size().unstack(fill_value=0).reindex(eyears, fill_value=0)
    expiry_chart = {"x": [str(y) for y in eyears],
                    "series": [{"name": s, "data": [int(v) for v in ex[s]]} for s in segs_e]}
    expiry_table = [{"year": str(y), "cells": [n(ex[s].loc[y]) for s in segs_e],
                     "total": n(ex.loc[y].sum())} for y in eyears]
    exp_this = int(ex.loc[ref_year].sum()) if ref_year in ex.index else 0
    exp_next = int(ex.loc[ref_year + 1].sum()) if (ref_year + 1) in ex.index else 0

    # 5. approval term (expiry year − certificate year)
    t = df.dropna(subset=["term"]).copy()
    t["term"] = t["term"].astype(int)
    t_ok = t[(t["term"] >= 0) & (t["term"] <= 20)]
    t_bad = len(t) - len(t_ok)
    terms = list(range(int(t_ok["term"].min()), int(t_ok["term"].max()) + 1)) if len(t_ok) else []
    segs_t = [s for s in SEG_ORDER if s in set(t_ok["seg"])]
    tt = t_ok.groupby(["term", "seg"]).size().unstack(fill_value=0).reindex(terms, fill_value=0)
    term_chart = {"x": [str(x) for x in terms],
                  "series": [{"name": s, "data": [int(v) for v in tt[s]]} for s in segs_t]}
    term_table = [{"term": str(x), "cells": [n(tt[s].loc[x]) for s in segs_t]} for x in terms]

    # 6. manufacturers (placeholder names excluded)
    real = df[~df["maker"].isin(PLACEHOLDER_MAKERS)]
    rv = real[real["valid"]]
    vm = _sorted_counts(rv["maker_key"])
    allm = real.groupby("maker_key").size()
    top_m = list(vm.head(TOP_MAKERS).index)
    mseg = rv.groupby(["maker_key", "seg"]).size()
    makers_chart = {"names": [mk_names[k] for k in top_m],
                    "series": [{"name": s, "data": [int(mseg.get((k, s), 0)) for k in top_m]}
                               for s in SEG_ORDER if s in set(rv["seg"])]}
    mgroups = rv.groupby("maker_key")["group"].nunique()
    makers_table = [{"name": mk_names[k], "v": n(vm[k]), "all": n(allm[k]), "groups": n(mgroups[k])}
                    for k in top_m]
    placeholder_n = total - len(real)

    # 7. portfolio size distribution (all models vs valid models)
    def buckets(counts):
        out = []
        for lo, hi in SIZE_BUCKETS:
            m = counts >= lo
            if hi is not None:
                m &= counts <= hi
            out.append((int(m.sum()), int(counts[m].sum())))
        return out
    blabels = ["דגם יחיד" if hi == lo == 1 else (f"{lo} ומעלה" if hi is None else f"{lo} עד {hi}")
               for lo, hi in SIZE_BUCKETS]
    b_all, b_val = buckets(allm), buckets(vm)
    size_chart = {"x": blabels, "all": [x[0] for x in b_all], "valid": [x[0] for x in b_val]}
    size_table = [{"bucket": blabels[i], "all": n(b_all[i][0]), "all_models": n(b_all[i][1]),
                   "valid": n(b_val[i][0]), "valid_models": n(b_val[i][1])} for i in range(len(blabels))]

    # 8. bridge scales by capacity (tons)
    br = df[df["group"].str.contains("גשר")].copy()
    br["tons"] = pd.to_numeric(br["dtype"].str.extract(TONS)[0], errors="coerce")
    br = br.dropna(subset=["tons"])
    bridge = None
    if len(br) >= 20:
        tons = sorted(int(x) for x in br["tons"].unique())
        bv = br[br["valid"]].groupby("tons").size()
        ball = br.groupby("tons").size()
        bridge = {"x": [str(x) for x in tons],
                  "valid": [int(bv.get(x, 0)) for x in tons],
                  "expired": [int(ball.get(x, 0) - bv.get(x, 0)) for x in tons]}
        bridge_table = [{"tons": str(x), "v": n(bv.get(x, 0)), "all": n(ball.get(x, 0))} for x in tons]
        bt = br.groupby("tons").size()
        b_mode = int(bt.sort_index().idxmax())
        bvt = br[br["valid"]]
        b_valid_max = int(bvt["tons"].max()) if len(bvt) else None
    else:
        bridge_table = []

    # KPIs
    v_share = valid_n / total * 100 if total else 0.0
    n_vm = int(len(vm))
    n_certs = int(df.loc[df["cert"].str.len() >= 3, "cert"].nunique())
    lf_tone = "brand" if pv_n == 0 else ("ok" if lf_n > pv_n * 1.1 else ("warn" if lf_n < pv_n * 0.9 else "brand"))
    kpis = {
        "total": {"value": total, "display": n(total), "tone": "brand"},
        "valid": {"value": valid_n, "display": n(valid_n), "tone": "ok"},
        "share": {"value": round(v_share, 1), "display": f"{v_share:.1f}%",
                  "tone": "warn" if v_share < 50 else "ok"},
        "makers": {"value": n_vm, "display": n(n_vm), "tone": "brand"},
        "last_full": {"value": lf_n, "display": n(lf_n), "tone": lf_tone},
        "certs": {"value": n_certs, "display": n(n_certs), "tone": "brand"},
        "exp_this": {"value": exp_this, "display": n(exp_this), "tone": "warn" if exp_this else "brand"},
        "exp_next": {"value": exp_next, "display": n(exp_next), "tone": "info" if exp_next else "brand"},
    }

    rules = [
        ("valid", insight_valid(df, total, valid_n, seg_valid)),
        ("legacy", insight_legacy(df, grp_stats)),
        ("empty_groups", insight_empty_groups(grp_stats)),
        ("makers", insight_makers(valid, mk_names)),
        ("trend", insight_trend(df, ref_year)),
        ("expiry", insight_expiry(valid, ref_year)),
        ("term", insight_term(df)),
        ("certs", insight_certs(df)),
        ("missing", insight_missing(df)),
    ]
    insights = [{"id": i, "text_he": x} for i, x in rules if x]

    lead_g = grp_stats.index[0]
    vtop = grp_stats.sort_values("v", ascending=False, kind="stable")
    lead_v = vtop.index[0]
    n_groups = len(grp_stats)
    ylo = years[0] if years else ref_year
    labels = {
        "lede": (f"מרשם הדגמים של מכשירי מדידה שקיבלו אישור דגם ממחלקת משקלות ומידות במשרד הכלכלה — "
                 f"מאזני דלפק, מאזני גשר, מאזניים מדויקים, מוני דלק ומים, ומאזניים לשימוש ביתי. "
                 f"כל שורה היא דגם של יצרן מסוים, עם קבוצת הציוד, מספר תעודת האישור ותוקפה. "
                 f"במאגר {n(total)} דגמים ב-{n(n_groups)} קבוצות ציוד, של {n(allm.size)} יצרנים; "
                 f"{n(valid_n)} מהם בתוקף כיום."),
        "last_full_kpi": f"דגמים שאושרו ב-{last_full}" + (f" (לעומת {n(pv_n)} ב-{last_full - 1})" if pv_n else ""),
        "exp_this_kpi": f"דגמים בתוקף שאישורם פוקע עד סוף {ref_year}",
        "exp_next_kpi": f"דגמים בתוקף שאישורם פוקע ב-{ref_year + 1}",
        "groups_note": (f"מספר הדגמים בכל קבוצת ציוד, בתוקף ושפג תוקפם. הקבוצה הגדולה במאגר היא "
                        f"\"{lead_g}\" ({n(grp_stats.loc[lead_g, 'n'])} דגמים), אך הגדולה בדגמים "
                        f"בתוקף היא \"{lead_v}\" ({n(vtop.loc[lead_v, 'v'])}). "
                        f"מוצגות {TOP_GROUPS} הקבוצות הגדולות; הטבלה כוללת את כל {n(n_groups)} הקבוצות "
                        f"ואת מספר היצרנים שלהם דגם בתוקף בכל אחת."),
        "groups_aria": (f"תרשים עמודות אופקי מוערם: דגמים בתוקף ושפג תוקפם לפי קבוצת ציוד; "
                        f"בראש {lead_g} עם {n(grp_stats.loc[lead_g, 'n'])} דגמים."),
        "groups_caption": "דגמים, דגמים בתוקף ויצרנים עם דגם בתוקף, לפי קבוצת ציוד.",
        "tree_note": (f"{n(valid_n)} הדגמים שבתוקף, לפי ייעוד השימוש וקבוצת הציוד. גודל כל מלבן "
                      f"יחסי למספר הדגמים."),
        "tree_aria": (f"מפת שטחים: {n(valid_n)} דגמים בתוקף לפי ייעוד וקבוצת ציוד; הגדולה "
                      f"{lead_v} עם {n(vtop.loc[lead_v, 'v'])} דגמים."),
        "tree_caption": "דגמים בתוקף לפי ייעוד השימוש וקבוצת ציוד.",
        "approvals_note": (f"מספר הדגמים לפי שנת האישור, כפי שהיא מופיעה בסוף מספר התעודה, ולפי ייעוד "
                           f"השימוש. רק דגמים שעדיין רשומים במאגר נספרים, כך שהשנים המוקדמות חסרות בחלקן. "
                           f"{ref_year} חלקית."
                           + (f" ל-{n(unparsed)} דגמים אין שנה תקינה במספר התעודה והם אינם מוצגים." if unparsed else "")),
        "approvals_aria": (f"גרף עמודות מוערמות: דגמים לפי שנת אישור וייעוד, {ylo}–{ref_year}; "
                           f"ב-{last_full} אושרו {n(lf_n)} דגמים."),
        "approvals_caption": f"דגמים לפי שנת אישור וייעוד, {ylo}–{ref_year}.",
        "expiry_note": (f"מתי יפקעו האישורים של {n(len(ev))} הדגמים שבתוקף, לפי שנה וייעוד. "
                        f"דגם שאישורו לא יחודש ייצא מרשימת המאושרים."),
        "expiry_aria": (f"גרף עמודות מוערמות: דגמים בתוקף לפי שנת פקיעת האישור; עד סוף {ref_year + 1} "
                        f"פוקעים {n(exp_this + exp_next)} דגמים."),
        "expiry_caption": "דגמים בתוקף לפי שנת פקיעת האישור וייעוד.",
        "term_note": ("משך האישור בשנים — שנת הפקיעה פחות שנת האישור שבמספר התעודה — לפי ייעוד השימוש."
                      + (("" if not t_bad else " דגם אחד עם הפרש שלילי או חריג אינו מוצג." if t_bad == 1
                         else f" {n(t_bad)} דגמים עם הפרש שלילי או חריג אינם מוצגים."))),
        "term_aria": "גרף עמודות מוערמות: דגמים לפי משך האישור בשנים וייעוד השימוש.",
        "term_caption": "דגמים לפי משך האישור (שנים) וייעוד.",
        "makers_note": (f"{TOP_MAKERS} היצרנים עם מספר הדגמים הגבוה ביותר שבתוקף, לפי ייעוד. "
                        + (f"{n(placeholder_n)} דגמים הרשומים תחת יצרן \"כללי\" או ללא שם יצרן אינם נכללים." if placeholder_n else "")),
        "makers_aria": (f"תרשים עמודות אופקי: {TOP_MAKERS} היצרנים עם הכי הרבה דגמים בתוקף; "
                        f"בראש {mk_names[top_m[0]]} עם {n(vm.iloc[0])}." if top_m else "תרשים יצרנים."),
        "makers_caption": "היצרנים המובילים: דגמים בתוקף, כלל הדגמים במאגר וקבוצות ציוד.",
        "size_note": (f"כמה דגמים יש לכל יצרן — בכלל המאגר ({n(allm.size)} יצרנים) ובדגמים שבתוקף "
                      f"({n(n_vm)} יצרנים). רוב היצרנים מחזיקים דגמים בודדים."),
        "size_aria": (f"גרף עמודות: יצרנים לפי מספר הדגמים שלהם; {n(b_all[0][0])} יצרנים עם דגם יחיד במאגר."),
        "size_caption": "יצרנים לפי מספר הדגמים: בכלל המאגר ובדגמים בתוקף.",
    }
    if bridge:
        labels.update({
            "bridge_note": (f"מאזני גשר לשקילת משאיות לפי כושר השקילה המרבי בטונות. הכושר הנפוץ במאגר: "
                            f"{n(b_mode)} טון"
                            + (f"; הדגם הגדול שבתוקף שוקל עד {n(b_valid_max)} טון." if b_valid_max else ".")),
            "bridge_aria": f"גרף עמודות מוערמות: דגמי מאזני גשר לפי כושר שקילה בטונות; הנפוץ {n(b_mode)} טון.",
            "bridge_caption": "דגמי מאזני גשר לפי כושר שקילה: בתוקף ובסך הכול.",
        })

    tables = {
        "groups": groups_table, "tree": tree_table,
        "segs_a": segs_a, "approvals": approvals_table,
        "segs_e": segs_e, "expiry": expiry_table,
        "segs_t": segs_t, "term": term_table,
        "makers": makers_table, "size": size_table, "bridge": bridge_table,
    }
    charts = {
        "groups": groups_chart, "tree": tree, "approvals": approvals_chart,
        "expiry": expiry_chart, "term": term_chart, "makers": makers_chart,
        "size": size_chart, "bridge": bridge,
    }
    exp_all = df["ey"].dropna()
    return {
        "agent_data": {
            "summary_he": (f"מרשם דגמי מכשירי המדידה המאושרים בישראל (משקלות ומידות, משרד הכלכלה): "
                           f"{n(total)} דגמים של {n(allm.size)} יצרנים ב-{n(n_groups)} קבוצות ציוד — "
                           f"מאזניים מסחריים וביתיים, מאזני גשר ומוני דלק — מהם {n(valid_n)} בתוקף, "
                           f"עם תעודת האישור ותוקפה."),
            "dataset_kind": "registry",
            "related_ids": ["dda8f0aa-8901-473d-a4d6-8b361aa51417",
                            "89fbf87e-6bc0-4e26-acc7-a288c31b12a1",
                            "12c7457c-a9f0-40f8-9ed6-b4689d3d3fa4"],
            "suggested_tags": ["משקלות ומידות", "מכשירי מדידה", "מאזניים", "אישור דגם",
                               "הגנת הצרכן", "משרד הכלכלה"],
            "temporal_coverage": (f"{ylo}/{int(exp_all.max())}" if len(exp_all) else None),
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
        "show_bridge": bool(bridge),
    }
