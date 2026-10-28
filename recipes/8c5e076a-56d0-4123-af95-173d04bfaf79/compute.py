"""פרטי קופות לצורך העברת כספים בין גופים מוסדיים — Capital Market Authority.

The registry institutional bodies use to move savings between one another:
for every investment track of every provident fund, study fund, pension fund
and participating life-insurance policy, the managing company, the operating
company, the bank account that receives (incoming) or sends (outgoing)
transfers, the transfer desk's contact channels and the record's last update.

Grain: one row per (track, direction). A track appears once when a single
account serves both directions ("נכנסות ויוצאות") or twice (one "נכנסות"
row, one "יוצאות" row). A handful of non-life insurers are listed at company
level, without a track and without a bank account. Everything here counts
distinct TRACKS (domain + company + track number), never rows, unless a label
says otherwise. "Now" is the latest update date in the data, never the clock.

Contact names, e-mails, phones, addresses and the account numbers themselves
stay off the page (they are in the explorer below it); only aggregates of them
are shown.
"""
import re

import pandas as pd

DOMAINS = ["גמל", "פנסיה", "ביטוח"]
DOMAIN_LABEL = {"גמל": "גמל והשתלמות", "פנסיה": "פנסיה", "ביטוח": "ביטוח"}
TOP_COMPANIES = 15
TOP_TYPES = 14
TOP_SPEC = 12
TOP_OPERATORS = 10
HEAT_COMPANIES = 12
TOP_FUNDS = 10
TOP_CITIES = 8
FRESH_DAYS = 365
POOL_BUCKETS = [(1, 1, "מסלול אחד"), (2, 5, "2 עד 5 מסלולים"), (6, 20, "6 עד 20 מסלולים"),
                (21, None, "21 מסלולים ומעלה")]
SELF_OP = "ניהול עצמי"
NO_OP = "ללא חברה מתפעלת רשומה"
CITY_ALIAS = {"ת\"א": "תל אביב", "תל אביב יפו": "תל אביב", "תל אביב-יפו": "תל אביב",
              "פתח-תקווה": "פתח תקווה", "פתח תקוה": "פתח תקווה"}
# Leading words that name a legal form, not a brand — never a group key.
GENERIC_TOKENS = {"החברה", "חברה", "חברת", "קרן", "קרנות", "קופת", "קופת\"ג", "התאגיד",
                  "תגמולים", "ביטוח", "מבטחים"}
COMBINED = "נכנסות ויוצאות"
LRI, PDI = "⁦", "⁩"
MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]


def n(v):
    return f"{int(v):,}"


def pct(v, digits=1):
    return f"{LRI}{v:.{digits}f}%{PDI}"


def d_he(ts):
    return f"{ts.day} ב{MONTHS_HE[ts.month - 1]} {ts.year}"


def _clean(s):
    return s.astype(str).str.strip().str.replace(r"\s+", " ", regex=True)


def _sorted_counts(s):
    """value_counts with a total, deterministic order (count desc, name asc)."""
    c = s.value_counts()
    return c.sort_index().sort_values(ascending=False, kind="stable")


def _top(counts, k, other="אחר"):
    top = counts.head(k)
    rest = int(counts.iloc[k:].sum())
    names = list(top.index) + ([other] if rest else [])
    vals = [int(v) for v in top.values] + ([rest] if rest else [])
    return names, vals


def _city(c):
    c = c.replace("־", "-").strip()
    return CITY_ALIAS.get(c, c)


def _group_token(name):
    tok = re.split(r"[\s\-–]+", name.strip())[0] if name.strip() else ""
    tok = tok.strip(".,'\"")
    return tok if len(tok) >= 2 and tok not in GENERIC_TOKENS else ""


def _prepare(df):
    out = pd.DataFrame({
        "domain": _clean(df["תחום"]),
        "company": _clean(df["שם חברה"]).str.replace("''", "\"", regex=False),
        "fund_no": _clean(df["מספר קופה -אישור מס הכנסה"]),
        "fund": _clean(df["שם קופה / קרן"]),
        "track": _clean(df["מספר מסלול השקעה"]),
        "type": _clean(df["סוג מסלול השקעה"]),
        "spec1": _clean(df["התמחות ראשית של מסלול"]),
        "spec2": _clean(df["התמחות משנית של מסלול"]),
        "operator": _clean(df["שם חברה מתפעלת"]),
        "email": _clean(df["דואר אלקטרוני"]),
        "fax": _clean(df["פקס"]),
        "city": _clean(df["עיר"]).map(_city),
        "direction": _clean(df["העברות נכנסות / יוצאות"]),
        "bank_code": _clean(df["קוד בנק"]),
        "bank": _clean(df["שם בנק"]),
        "branch": _clean(df["מספר סניף"]),
        "account": _clean(df["מספר חשבון"]),
        "updated": pd.to_datetime(_clean(df["תאריך עדכון אחרון"]), errors="coerce",
                                  format="%Y-%m-%dT%H:%M:%S"),
    })
    out["key"] = out["domain"] + "|" + out["company"] + "|" + out["track"]
    op = out["operator"]
    out["op_mode"] = "חברה מתפעלת חיצונית"
    out.loc[op.eq("") , "op_mode"] = NO_OP
    out.loc[op.eq(SELF_OP) | op.eq(out["company"]), "op_mode"] = "תפעול עצמי"
    has_acc = out["account"].ne("") & out["bank_code"].ne("")
    out["acc_id"] = (out["bank_code"] + "-" + out["branch"] + "-" + out["account"]).where(has_acc, "")
    return out


def _per_track(rows):
    """One row per track (rows carrying a track number)."""
    tr = rows[rows["track"].ne("")]
    first = (tr.sort_values(["key", "direction", "acc_id"], kind="stable")
               .drop_duplicates("key").set_index("key"))
    last = tr.groupby("key")["updated"].max()
    first["updated"] = last
    dirs = tr.groupby("key")["direction"].agg(lambda s: tuple(sorted(set(s))))
    accs = tr[tr["acc_id"].ne("")].groupby("key")["acc_id"].nunique()
    first["dirs"] = dirs
    first["n_acc"] = accs.reindex(first.index).fillna(0).astype(int)
    banks = tr[tr["bank"].ne("")].groupby("key")["bank"].nunique()
    first["n_bank"] = banks.reindex(first.index).fillna(0).astype(int)
    return first.sort_index()


def _structure(row):
    if row["dirs"] == (COMBINED,):
        return "חשבון אחד לשני הכיוונים"
    if set(row["dirs"]) >= {"נכנסות", "יוצאות"}:
        return "חשבונות נפרדים לנכנסות וליוצאות" if row["n_acc"] >= 2 else "אותו חשבון, רישום נפרד לכל כיוון"
    return "אחר"


# ---------------------------------------------------------------- insights

def insight_concentration(comp_counts, total):
    if len(comp_counts) < 6 or total == 0:
        return None
    top5 = comp_counts.head(5)
    share = top5.sum() / total
    lead, lead_v = comp_counts.index[0], comp_counts.iloc[0]
    tail = int((comp_counts <= 3).sum())
    s = (f"חמש החברות המנהלות הגדולות מחזיקות {pct(share * 100)} ממסלולי ההשקעה במאגר; "
         f"בראשן {lead} עם {n(lead_v)} מסלולים.")
    if tail >= 10:
        s += (f" מנגד, {n(tail)} מתוך {n(len(comp_counts))} החברות שמנהלות מסלולים מחזיקות שלושה מסלולים או פחות — "
              f"בעיקר קופות ענפיות וקרנות השתלמות מקצועיות.")
    return s


def insight_groups(tracks):
    tok = tracks["company"].map(_group_token)
    t = tracks.assign(tok=tok)[tok.ne("")]
    dom = t.groupby("tok")["domain"].nunique()
    full = sorted(dom[dom >= len(DOMAINS)].index)
    if len(full) < 2:
        return None
    share = t["tok"].isin(full).sum() / len(tracks)
    return (f"{n(len(full))} קבוצות פועלות בכל שלושת התחומים — גמל, פנסיה וביטוח — באמצעות "
            f"חברות נפרדות: {', '.join(full)}. יחד הן מנהלות {pct(share * 100)} מהמסלולים "
            f"(הקבוצה מזוהה לפי המילה הפותחת המשותפת בשם החברה).")


def insight_index(tracks):
    parts = []
    for d in DOMAINS:
        sub = tracks[tracks["domain"].eq(d)]
        if len(sub) < 30:
            continue
        parts.append((d, sub["spec1"].eq("עוקבי מדדים").mean()))
    if len(parts) < 2:
        return None
    allv = tracks["spec1"].eq("עוקבי מדדים").mean()
    if allv < 0.05:
        return None
    hi = max(parts, key=lambda p: (p[1], p[0]))
    lo = min(parts, key=lambda p: (p[1], p[0]))
    s = f"{pct(allv * 100)} מהמסלולים מוגדרים \"עוקבי מדדים\" בהתמחות הראשית."
    if hi[1] - lo[1] >= 0.03:
        s += (f" השיעור הגבוה ביותר הוא בתחום ה{DOMAIN_LABEL[hi[0]]} ({pct(hi[1] * 100)}) "
              f"והנמוך ביותר בתחום ה{DOMAIN_LABEL[lo[0]]} ({pct(lo[1] * 100)}).")
    return s


def insight_sp500(tracks):
    m = tracks["spec2"].str.lower().str.contains("s&p 500", regex=False)
    k = int(m.sum())
    if k < 10:
        return None
    comps = tracks.loc[m, "company"].nunique()
    s = (f"{n(k)} מסלולים מוגדרים \"עוקב מדד S&P 500\" בהתמחות המשנית, אצל {n(comps)} "
         f"חברות מנהלות")
    idx = tracks[tracks["spec2"].str.contains("עוקב", regex=False)]
    lead = _sorted_counts(idx["spec2"]).index[0] if len(idx) else ""
    if "s&p 500" in lead.lower():
        s += " — ההתמחות המשנית הנפוצה ביותר מבין מסלולי המדדים"
    return s + "."


def insight_banks(bank_counts, n_tracks_bank):
    if bank_counts.empty or n_tracks_bank == 0:
        return None
    lead, v = bank_counts.index[0], bank_counts.iloc[0]
    share = v / n_tracks_bank
    if share < 0.3:
        return None
    return (f"חשבונות ההעברה מתנהלים ב-{n(len(bank_counts))} בנקים בלבד; בבנק {lead} "
            f"מתנהלים חשבונות של {pct(share * 100)} מהמסלולים שצוין להם בנק.")


def insight_split_bank(tracks):
    two = tracks[tracks["dirs"].map(lambda d: set(d) >= {"נכנסות", "יוצאות"})]
    if len(two) < 20:
        return None
    diff = int((two["n_bank"] >= 2).sum())
    diff_acc = int((two["n_acc"] >= 2).sum())
    if diff_acc == 0:
        return None
    s = (f"ב-{n(len(two))} מסלולים יש רישום נפרד להעברות נכנסות ויוצאות; ב-{n(diff_acc)} מהם "
         f"({pct(diff_acc / len(two) * 100)}) מדובר בשני חשבונות שונים")
    if diff:
        s += f", וב-{n(diff)} אף בשני בנקים שונים"
    return s + "."


def insight_operators(tracks):
    g = tracks[tracks["domain"].eq("גמל")]
    if len(g) < 30:
        return None
    ext = g[g["op_mode"].eq("חברה מתפעלת חיצונית")]
    share = len(ext) / len(g)
    if ext.empty:
        return None
    ops = _sorted_counts(ext["operator"])
    other = tracks[~tracks["domain"].eq("גמל")]
    other_ext = other["op_mode"].eq("חברה מתפעלת חיצונית").mean() if len(other) else 0
    s = (f"{pct(share * 100)} ממסלולי הגמל וההשתלמות מתופעלים בידי חברה חיצונית; "
         f"המתפעלת הגדולה היא {ops.index[0]} ({n(ops.iloc[0])} מסלולים).")
    if other_ext < share / 2:
        s += f" בפנסיה ובביטוח השיעור {pct(other_ext * 100)} בלבד."
    return s


def insight_fresh(tracks, ref):
    u = tracks["updated"].dropna()
    if len(u) < 50:
        return None
    fresh = (u >= ref - pd.Timedelta(days=FRESH_DAYS)).mean()
    old = u.min()
    stale_years = int((u.dt.year <= ref.year - 5).sum())
    s = (f"{pct(fresh * 100)} מהמסלולים עודכנו בשנה שקדמה לעדכון האחרון במאגר ({d_he(ref)}).")
    if stale_years:
        s += (f" {n(stale_years)} מסלולים עודכנו לאחרונה ב-{ref.year - 5} או לפני כן; "
              f"העדכון המוקדם ביותר מ-{old.year}.")
    return s


def insight_pool(acc_tracks, comp_of_acc):
    if acc_tracks.empty:
        return None
    shared = int((acc_tracks > 1).sum())
    if shared == 0:
        return None
    big = acc_tracks.sort_index().sort_values(ascending=False, kind="stable")
    top_acc, top_v = big.index[0], int(big.iloc[0])
    covered = int(acc_tracks[acc_tracks > 1].sum())
    s = (f"{n(len(acc_tracks))} חשבונות בנק משרתים את המסלולים; {n(shared)} מהם משותפים "
         f"לכמה מסלולים ומשרתים יחד {n(covered)} מסלולים.")
    if top_v >= 10:
        s += f" החשבון המשותף הגדול ביותר, של {comp_of_acc[top_acc]}, משמש {n(top_v)} מסלולים."
    return s


def insight_fax(tracks):
    if len(tracks) < 50:
        return None
    fax = tracks["fax"].ne("").mean()
    mail = tracks["email"].ne("").mean()
    if fax < 0.2:
        return None
    return (f"לצד דואר אלקטרוני (מצוין ב-{pct(mail * 100)} מהמסלולים), {pct(fax * 100)} "
            f"מהמסלולים עדיין מפרטים גם מספר פקס למחלקת ההעברות.")


# ---------------------------------------------------------------- compute

def compute(frames):
    rows = _prepare(frames["funds"])
    tracks = _per_track(rows)
    n_tracks = len(tracks)
    company_only = rows[rows["track"].eq("")].drop_duplicates(["domain", "company"])
    ref = rows["updated"].max()

    companies = sorted(set(rows["company"]) - {""})
    funds = tracks.loc[tracks["fund_no"].ne(""), ["company", "fund_no"]].drop_duplicates()
    accounts = rows.loc[rows["acc_id"].ne(""), "acc_id"].unique()

    # 1. domains
    dom_rows = []
    for d in DOMAINS + sorted(set(rows["domain"]) - set(DOMAINS) - {""}):
        t = tracks[tracks["domain"].eq(d)]
        r = rows[rows["domain"].eq(d)]
        if r.empty:
            continue
        dom_rows.append({"name": DOMAIN_LABEL.get(d, d), "code": d,
                         "companies": int(r["company"].nunique()),
                         "funds": int(t.loc[t["fund_no"].ne(""), "fund_no"].nunique()),
                         "tracks": int(len(t))})
    dom_names = [r["name"] for r in dom_rows]
    dom_codes = [r["code"] for r in dom_rows]

    def by_domain(frame, col, names):
        ct = pd.crosstab(frame[col], frame["domain"])
        return [{"name": DOMAIN_LABEL.get(d, d),
                 "data": [int(ct.at[x, d]) if (x in ct.index and d in ct.columns) else 0
                          for x in names]} for d in dom_codes]

    # 2. companies
    comp_counts = _sorted_counts(tracks["company"])
    c_names = list(comp_counts.head(TOP_COMPANIES).index)
    comp_rest = tracks[~tracks["company"].isin(c_names)]
    comp_series = by_domain(tracks, "company", c_names)
    comp_funds = funds.groupby("company")["fund_no"].nunique()
    comp_table = [{"name": c, "tracks": n(comp_counts[c]), "funds": n(comp_funds.get(c, 0)),
                   "domains": " · ".join(DOMAIN_LABEL.get(d, d) for d in dom_codes
                                         if ((tracks["company"] == c) & (tracks["domain"] == d)).any())}
                  for c in c_names]

    # 3. track types
    typ = tracks[tracks["type"].ne("")]
    type_counts = _sorted_counts(typ["type"])
    t_names = list(type_counts.head(TOP_TYPES).index)
    type_series = by_domain(typ, "type", t_names)
    if len(type_counts) > TOP_TYPES:
        rest = typ[~typ["type"].isin(t_names)]["domain"].value_counts()
        t_names = t_names + ["יתר הסוגים"]
        for s, d in zip(type_series, dom_codes):
            s["data"].append(int(rest.get(d, 0)))
    type_dom = typ.groupby("type")["domain"].agg(lambda s: _sorted_counts(s).index[0])

    # 4. primary specialisation
    sp = tracks[tracks["spec1"].ne("")]
    spec_counts = _sorted_counts(sp["spec1"])
    s_names = list(spec_counts.head(TOP_SPEC).index)
    spec_series = by_domain(sp, "spec1", s_names)
    if len(spec_counts) > TOP_SPEC:
        rest = sp[~sp["spec1"].isin(s_names)]["domain"].value_counts()
        s_names = s_names + ["יתר ההתמחויות"]
        for s, d in zip(spec_series, dom_codes):
            s["data"].append(int(rest.get(d, 0)))
    spec_missing = int(tracks["spec1"].eq("").sum())

    # 5. treemap primary -> secondary
    tm = tracks.assign(s1=tracks["spec1"].replace("", "לא צוינה"),
                       s2=tracks["spec2"].replace("", "לא צוינה"))
    tm_counts = tm.groupby(["s1", "s2"]).size()
    tree = []
    for s1 in _sorted_counts(tm["s1"]).index:
        kids = tm_counts.loc[s1].sort_index().sort_values(ascending=False, kind="stable")
        tree.append({"name": s1, "value": int(kids.sum()),
                     "children": [{"name": k, "value": int(v)} for k, v in kids.items()]})
    spec2_counts = _sorted_counts(tracks.loc[tracks["spec2"].ne(""), "spec2"])

    # 6. banks (distinct track × bank pairs)
    tb = rows[rows["track"].ne("") & rows["bank"].ne("")].drop_duplicates(["key", "bank"])
    bank_counts = _sorted_counts(tb["bank"])
    b_names = list(bank_counts.index)
    bank_series = by_domain(tb, "bank", b_names)
    n_tracks_bank = int(tb["key"].nunique())
    bank_acc = rows[rows["acc_id"].ne("")].groupby("bank")["acc_id"].nunique()
    bank_table = [{"name": b, "tracks": n(bank_counts[b]),
                   "share": f"{bank_counts[b] / n_tracks_bank * 100:.1f}%",
                   "accounts": n(bank_acc.get(b, 0))} for b in b_names]

    # 7. heatmap company × bank
    h_comp = list(comp_counts.head(HEAT_COMPANIES).index)
    hb = pd.crosstab(tb["company"], tb["bank"])
    cells, heat_rows = [], []
    for yi, c in enumerate(h_comp):
        vals = []
        for xi, b in enumerate(b_names):
            v = int(hb.at[c, b]) if (c in hb.index and b in hb.columns) else 0
            cells.append([xi, yi, v])
            vals.append(n(v))
        heat_rows.append({"name": c, "cells": vals})

    # 8. operation mode per domain + external operators
    modes = ["חברה מתפעלת חיצונית", "תפעול עצמי", NO_OP]
    mode_ct = pd.crosstab(tracks["domain"], tracks["op_mode"])
    mode_series, mode_table = [], []
    for m in modes:
        data = []
        for d in dom_codes:
            tot = int(mode_ct.loc[d].sum()) if d in mode_ct.index else 0
            v = int(mode_ct.at[d, m]) if (d in mode_ct.index and m in mode_ct.columns) else 0
            data.append(round(v / tot * 100, 1) if tot else 0)
        mode_series.append({"name": m, "data": data})
    for d, nm in zip(dom_codes, dom_names):
        r = {"name": nm}
        for i, m in enumerate(modes):
            v = int(mode_ct.at[d, m]) if (d in mode_ct.index and m in mode_ct.columns) else 0
            r[f"m{i}"] = n(v)
        mode_table.append(r)
    ext = tracks[tracks["op_mode"].eq("חברה מתפעלת חיצונית")]
    op_counts = _sorted_counts(ext["operator"])
    o_names, o_vals = _top(op_counts, TOP_OPERATORS)
    op_clients = ext.groupby("operator")["company"].nunique()
    op_table = [{"name": k, "tracks": n(v),
                 "clients": n(op_clients.get(k, 0)) if k != "אחר" else
                 n(ext[~ext["operator"].isin(o_names)]["company"].nunique())}
                for k, v in zip(o_names, o_vals)]

    # 9. transfer-account structure per domain
    tracks["structure"] = tracks.apply(_structure, axis=1)
    structs = ["חשבון אחד לשני הכיוונים", "אותו חשבון, רישום נפרד לכל כיוון",
               "חשבונות נפרדים לנכנסות וליוצאות"]
    structs += sorted(set(tracks["structure"]) - set(structs))
    st_ct = pd.crosstab(tracks["domain"], tracks["structure"])
    st_series, st_table = [], []
    for s_ in structs:
        data = []
        for d in dom_codes:
            tot = int(st_ct.loc[d].sum()) if d in st_ct.index else 0
            v = int(st_ct.at[d, s_]) if (d in st_ct.index and s_ in st_ct.columns) else 0
            data.append(round(v / tot * 100, 1) if tot else 0)
        st_series.append({"name": s_, "data": data})
    for d, nm in zip(dom_codes, dom_names):
        st_table.append({"name": nm, "cells": [
            n(st_ct.at[d, s_]) if (d in st_ct.index and s_ in st_ct.columns) else "0"
            for s_ in structs]})

    # 10. last update year
    up = tracks[tracks["updated"].notna()]
    years = list(range(int(up["updated"].dt.year.min()), int(ref.year) + 1)) if len(up) else []
    up_ct = pd.crosstab(up["updated"].dt.year, up["domain"])
    up_series = [{"name": DOMAIN_LABEL.get(d, d),
                  "data": [int(up_ct.at[y, d]) if (y in up_ct.index and d in up_ct.columns) else 0
                           for y in years]} for d in dom_codes]
    up_table = [{"year": str(y), "count": n(sum(s["data"][i] for s in up_series))}
                for i, y in enumerate(years)]
    fresh_share = float((up["updated"] >= ref - pd.Timedelta(days=FRESH_DAYS)).mean()) if len(up) else 0.0
    partial_year = not (ref.month == 12 and ref.day >= 24)

    # 11. pooled accounts
    ra = rows[rows["acc_id"].ne("") & rows["track"].ne("")]
    acc_tracks = ra.groupby("acc_id")["key"].nunique()
    comp_of_acc = (ra.sort_values(["acc_id", "company"], kind="stable")
                     .drop_duplicates("acc_id").set_index("acc_id")["company"])
    pool_names, pool_acc, pool_tr = [], [], []
    for lo, hi, lab in POOL_BUCKETS:
        m = acc_tracks >= lo
        if hi is not None:
            m &= acc_tracks <= hi
        pool_names.append(lab)
        pool_acc.append(int(m.sum()))
        pool_tr.append(int(acc_tracks[m].sum()))

    # 12. cities (distinct companies)
    cc = rows[rows["city"].ne("")].drop_duplicates(["company", "city"])
    city_counts = _sorted_counts(cc["city"])
    ci_names, ci_vals = _top(city_counts, TOP_CITIES)
    no_city = len(set(rows["company"]) - set(cc["company"]))

    # funds table
    ft = tracks[tracks["fund_no"].ne("")]
    fcount = ft.groupby(["fund", "company", "domain"]).size().reset_index(name="k")
    fcount = fcount.sort_values(["k", "fund", "company", "domain"],
                                ascending=[False, True, True, True]).head(TOP_FUNDS)
    tracks_per_fund = ft.groupby(["company", "fund_no"]).size()
    single_track_funds = int((tracks_per_fund == 1).sum())

    rules = [
        ("concentration", insight_concentration(comp_counts, n_tracks)),
        ("groups", insight_groups(tracks)),
        ("index", insight_index(tracks)),
        ("sp500", insight_sp500(tracks)),
        ("banks", insight_banks(bank_counts, n_tracks_bank)),
        ("split_bank", insight_split_bank(tracks)),
        ("operators", insight_operators(tracks)),
        ("pool", insight_pool(acc_tracks, comp_of_acc)),
        ("fresh", insight_fresh(tracks, ref)),
        ("fax", insight_fax(tracks)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    kpis = {
        "tracks": {"value": n_tracks, "display": n(n_tracks), "tone": "brand"},
        "funds": {"value": int(len(funds)), "display": n(len(funds)), "tone": "brand"},
        "companies": {"value": len(companies), "display": n(len(companies)), "tone": "brand"},
        "accounts": {"value": int(len(accounts)), "display": n(len(accounts)), "tone": "brand"},
        "fresh": {"value": round(fresh_share * 100, 1), "display": f"{fresh_share * 100:.1f}%",
                  "tone": "ok" if fresh_share >= 0.5 else "warn"},
    }

    dom_txt = ", ".join(f"{n(r['tracks'])} ב{r['name']}" for r in dom_rows)
    lead_type = type_counts.index[0] if len(type_counts) else ""
    lead_spec = spec_counts.index[0] if len(spec_counts) else ""
    labels = {
        "lede": (f"רשימת הקופות והמסלולים שגופים מוסדיים משתמשים בה כדי להעביר ביניהם כספי חיסכון: "
                 f"{n(n_tracks)} מסלולי השקעה ב-{n(len(funds))} קופות וקרנות של {n(len(companies))} "
                 f"חברות — {dom_txt}. לכל מסלול מצוינים החברה המנהלת והמתפעלת, חשבון הבנק להעברות "
                 f"נכנסות ויוצאות ופרטי מחלקת ההעברות. העדכון האחרון במאגר: {d_he(ref)}."),
        "scope_note": (f"הספירה בעמוד היא של מסלולים ולא של רשומות: מסלול מופיע פעם אחת כשחשבון אחד "
                       f"משמש לשני הכיוונים, ופעמיים כשיש רישום נפרד להעברות נכנסות ויוצאות. "
                       f"{n(len(company_only))} חברות ביטוח רשומות ברמת החברה בלבד, ללא מסלול וללא "
                       f"חשבון, ואינן נכללות בספירת המסלולים."),
        "fresh_kpi": f"מהמסלולים עודכנו בשנה האחרונה (עד {d_he(ref)})",
        "domain_note": (f"מספר החברות, הקופות והמסלולים בכל תחום. בביטוח אין מספר קופה, ולכן "
                        f"נספרים בו רק מסלולים."),
        "domain_aria": "תרשים עמודות מקובצות: חברות, קופות ומסלולים בכל תחום.",
        "domain_caption": "חברות, קופות וקרנות ומסלולי השקעה לפי תחום.",
        "comp_note": (f"מספר המסלולים של כל חברה מנהלת, לפי תחום. מוצגות {len(c_names)} החברות "
                      f"הגדולות" + (f"; שאר {n(len(comp_counts) - len(c_names))} החברות "
                                    f"({n(len(comp_rest))} מסלולים) אינן מוצגות." if len(comp_rest) else ".")),
        "comp_aria": f"תרשים עמודות מוערמות: מסלולים של {len(c_names)} החברות המנהלות הגדולות, לפי תחום.",
        "comp_caption": f"{len(c_names)} החברות המנהלות הגדולות: מסלולים, קופות ותחומי פעילות.",
        "type_note": (f"סוג המסלול כפי שהוא מוגדר בכל תחום; הנפוץ ביותר: {lead_type} "
                      f"({n(type_counts.iloc[0]) if len(type_counts) else 0} מסלולים)."),
        "type_aria": "תרשים עמודות אופקיות: מסלולים לפי סוג מסלול השקעה ותחום.",
        "type_caption": "מסלולים לפי סוג מסלול השקעה, והתחום שבו הסוג נפוץ.",
        "spec_note": (f"ההתמחות הראשית של מדיניות ההשקעה; הנפוצה ביותר: {lead_spec}. "
                      + (f"{n(spec_missing)} מסלולים ללא התמחות רשומה אינם נכללים." if spec_missing else "")),
        "spec_aria": "תרשים עמודות אופקיות מוערמות: מסלולים לפי התמחות ראשית ותחום.",
        "spec_caption": "מסלולים לפי התמחות ראשית ותחום.",
        "tree_note": (f"כל מלבן הוא התמחות ראשית, ובתוכו ההתמחויות המשניות שלה ({n(len(spec2_counts))} "
                      f"ערכים שונים). גודל המלבן לפי מספר המסלולים. לחיצה על מלבן מתמקדת בו."),
        "tree_aria": "מפת עץ: מסלולים לפי התמחות ראשית ומשנית.",
        "bank_note": (f"מספר המסלולים שיש להם חשבון העברות בכל בנק (מסלול שחשבונותיו בשני בנקים "
                      f"נספר בשניהם), לפי תחום. {n(n_tracks - n_tracks_bank)} מסלולים ללא בנק רשום."),
        "bank_aria": "תרשים עמודות מוערמות: מסלולים לפי בנק החשבון ותחום.",
        "bank_caption": "מסלולים, שיעור מהמסלולים וחשבונות שונים בכל בנק.",
        "heat_note": f"באילו בנקים מנהלות {len(h_comp)} החברות הגדולות את חשבונות ההעברה, במספר מסלולים.",
        "heat_aria": f"מפת חום: מספר מסלולים לפי חברה מנהלת ({len(h_comp)} הגדולות) ובנק.",
        "heat_caption": f"מסלולים לפי חברה מנהלת ובנק, {len(h_comp)} החברות הגדולות.",
        "mode_note": ("שיעור המסלולים בכל תחום לפי אופן התפעול: חברה מתפעלת חיצונית, תפעול בידי החברה "
                      "המנהלת עצמה (\"ניהול עצמי\" או שם החברה עצמה), או ללא חברה מתפעלת רשומה."),
        "mode_aria": "תרשים עמודות מוערמות באחוזים: אופן תפעול המסלולים בכל תחום.",
        "mode_caption": "מספר המסלולים לפי אופן תפעול ותחום.",
        "op_note": (f"החברות המתפעלות החיצוניות לפי מספר המסלולים שהן מתפעלות "
                    f"({n(len(ext))} מסלולים, {n(len(op_counts))} מתפעלות)."),
        "op_aria": f"תרשים עמודות אופקיות: {TOP_OPERATORS} החברות המתפעלות הגדולות, מספר מסלולים.",
        "op_caption": "חברות מתפעלות: מספר מסלולים ומספר חברות מנהלות לקוחות.",
        "struct_note": ("כיצד רשום חשבון ההעברות של כל מסלול: חשבון אחד לשני הכיוונים, רישום נפרד "
                        "להעברות נכנסות ויוצאות לאותו חשבון, או שני חשבונות שונים. באחוזים מהמסלולים בכל תחום."),
        "struct_aria": "תרשים עמודות מוערמות באחוזים: מבנה חשבונות ההעברה בכל תחום.",
        "struct_caption": "מספר המסלולים לפי מבנה חשבונות ההעברה ותחום.",
        "up_note": (f"שנת העדכון האחרון של רשומות כל מסלול, לפי תחום."
                    + (f" {n(n_tracks - len(up))} מסלולים ללא תאריך עדכון אינם נכללים."
                       if n_tracks > len(up) else "")
                    + (f" {ref.year} — שנה חלקית, עד {d_he(ref)}." if partial_year else "")),
        "up_aria": "תרשים עמודות מוערמות: מסלולים לפי שנת העדכון האחרון ותחום.",
        "up_caption": "מספר המסלולים לפי שנת העדכון האחרון.",
        "pool_note": (f"חשבון בנק אחד יכול לשמש מסלולים רבים. {n(len(acc_tracks))} החשבונות לפי מספר "
                      f"המסלולים שהם משרתים."),
        "pool_aria": "תרשים עמודות: חשבונות בנק ומסלולים לפי מספר המסלולים לחשבון.",
        "pool_caption": "חשבונות ומסלולים לפי מספר המסלולים שכל חשבון משרת.",
        "city_note": (f"העיר שבה נמצאת מחלקת ההעברות, במספר חברות מנהלות."
                      + (f" ל-{n(no_city)} חברות לא צוינה עיר." if no_city else "")),
        "city_aria": "תרשים עמודות אופקיות: חברות מנהלות לפי עיר מחלקת ההעברות.",
        "city_caption": "מספר חברות מנהלות לפי עיר.",
        "funds_caption": f"{TOP_FUNDS} הקופות והקרנות עם מספר המסלולים הגדול ביותר.",
        "funds_note": (f"{n(single_track_funds)} מתוך {n(len(funds))} הקופות והקרנות פועלות עם מסלול "
                       f"השקעה אחד בלבד. בטבלה — הקופות והקרנות עם מספר המסלולים הגדול ביותר."),
    }

    charts = {
        "domains": {"names": dom_names,
                    "companies": [r["companies"] for r in dom_rows],
                    "funds": [r["funds"] for r in dom_rows],
                    "tracks": [r["tracks"] for r in dom_rows]},
        "companies": {"names": c_names, "series": comp_series},
        "types": {"names": t_names, "series": type_series},
        "spec": {"names": s_names, "series": spec_series},
        "tree": tree,
        "banks": {"names": b_names, "series": bank_series},
        "heat": {"x": b_names, "y": h_comp, "cells": cells,
                 "max": max([c[2] for c in cells] or [1])},
        "modes": {"names": dom_names, "series": mode_series},
        "operators": {"names": o_names, "values": o_vals},
        "structure": {"names": dom_names, "series": st_series},
        "updated": {"x": [str(y) for y in years], "series": up_series},
        "pool": {"names": pool_names, "accounts": pool_acc, "tracks": pool_tr},
        "cities": {"names": ci_names, "values": ci_vals},
    }
    tables = {
        "domains": [{"name": r["name"], "companies": n(r["companies"]), "funds": n(r["funds"]),
                     "tracks": n(r["tracks"])} for r in dom_rows],
        "companies": comp_table,
        "types": [{"name": k, "count": n(sum(s["data"][i] for s in type_series)),
                   "domain": DOMAIN_LABEL.get(type_dom.get(k, ""), "") if k != "יתר הסוגים" else "—"}
                  for i, k in enumerate(t_names)],
        "spec": [{"name": k, "cells": [n(s["data"][i]) for s in spec_series]}
                 for i, k in enumerate(s_names)],
        "spec2": [{"name": k, "count": n(v)} for k, v in spec2_counts.head(TOP_SPEC).items()],
        "banks": bank_table,
        "heat": heat_rows,
        "modes": mode_table,
        "mode_names": modes,
        "operators": op_table,
        "structure": st_table,
        "struct_names": structs,
        "updated": up_table,
        "pool": [{"name": a, "accounts": n(b), "tracks": n(c)}
                 for a, b, c in zip(pool_names, pool_acc, pool_tr)],
        "cities": [{"name": k, "count": n(v)} for k, v in zip(ci_names, ci_vals)],
        "funds": [{"fund": r["fund"], "company": r["company"],
                   "domain": DOMAIN_LABEL.get(r["domain"], r["domain"]), "count": n(r["k"])}
                  for _, r in fcount.iterrows()],
        "dom_names": dom_names,
    }

    return {
        "agent_data": {
            "summary_he": (f"פרטי ההעברה של {n(n_tracks)} מסלולי השקעה בקופות גמל, קרנות השתלמות, "
                           f"קרנות פנסיה ופוליסות ביטוח של {n(len(companies))} חברות: חברה מנהלת "
                           f"ומתפעלת, חשבון בנק להעברות נכנסות ויוצאות, התמחות המסלול ומועד העדכון."),
            "dataset_kind": "registry",
            "related_ids": ["5265b154-c2e2-4f3d-a22e-fba593240d9a",
                            "3a1ca8fa-738b-4890-b52f-e8f7ce1e6145",
                            "b5dd1f5e-0566-42fd-8db9-ae12e10c445b",
                            "32348d0b-dc49-4bd0-a931-860e55709689",
                            "75989c99-3122-4656-943c-3b758262cbf4"],
            "suggested_tags": ["גופים מוסדיים", "קופות גמל", "קרנות פנסיה", "קרנות השתלמות",
                               "העברת כספים", "מסלולי השקעה", "רשות שוק ההון"],
            "temporal_coverage": (f"{up['updated'].min().strftime('%Y-%m-%d')}/{ref.strftime('%Y-%m-%d')}"
                                  if len(up) else None),
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
    }
