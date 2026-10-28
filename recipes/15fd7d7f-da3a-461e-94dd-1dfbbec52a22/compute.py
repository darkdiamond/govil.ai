"""דרישות חוקיות - יבוא ויצוא טובין — legal requirements per customs item.

Four inputs, one per legal instrument family, sharing one schema (the
"other orders" file adds ``IsPersonalImportIncluded``):

- ``free_import``     — צו יבוא חופשי (commercial import)
- ``personal_import`` — צו יבוא אישי (import by individuals)
- ``free_export``     — צו יצוא חופשי
- ``other``           — צווים נוספים: military orders for the Palestinian
  Authority areas (צו אלוף), defence-export and dual-use export control,
  import licences, the customs tariff (מנכ"ל approvals) and a few more.

A row is (customs item × requirement × confirmation). A *requirement*
(``RegularityRequirementID``, unique within its publication) is defined at a
classification level (chapter, heading, …) and fans out to every customs item
below it; it may need one or several confirmations, from one or several
authorities, and ``InterConditionsRelationship`` says whether all of them are
needed or any one (חליפי). The files join on ``CustomsItemFullClassification``
(the same item can be regulated by several orders).

The data is a snapshot (republished with edits), so there is no time axis
beyond ``UpdateDate`` (when each requirement was last edited). "Latest" is the
newest UpdateDate in the data, never the wall clock.
"""
import math
import re

import pandas as pd

LRI, PDI = "⁦", "⁩"
TOP_AUTH = 10
TOP_CONF = 14
TOP_STD = 12
TOP_ITEMS = 10
TOP_TERR_AUTH = 6
MAX_END_BUCKETS = 10
BURDEN_CAP = 5
OPEN_END_YEARS = 30   # an end date this many years past the latest update = open-ended sentinel

GROUPS = [
    ("free_import", "צו יבוא חופשי"),
    ("personal_import", "צו יבוא אישי"),
    ("free_export", "צו יצוא חופשי"),
    ("other", "צווים נוספים"),
]
GROUP_LABEL = dict(GROUPS)
GROUP_ORDER = [g for g, _ in GROUPS]

# HS sections → chapter ranges (fixed international Harmonized System layout;
# chapters 98–99 are the Israeli national annex). Short Hebrew labels.
SECTIONS = [
    ("I", 1, 5, "בעלי חיים ומוצרים מן החי"),
    ("II", 6, 14, "מוצרים מן הצומח"),
    ("III", 15, 15, "שומנים ושמנים"),
    ("IV", 16, 24, "מזון מעובד, משקאות וטבק"),
    ("V", 25, 27, "מוצרים מינרליים ודלקים"),
    ("VI", 28, 38, "כימיקלים"),
    ("VII", 39, 40, "פלסטיק וגומי"),
    ("VIII", 41, 43, "עורות ופרוות"),
    ("IX", 44, 46, "עץ ושעם"),
    ("X", 47, 49, "נייר וקרטון"),
    ("XI", 50, 63, "טקסטיל והלבשה"),
    ("XII", 64, 67, "הנעלה וכיסויי ראש"),
    ("XIII", 68, 70, "אבן, קרמיקה וזכוכית"),
    ("XIV", 71, 71, "אבנים ומתכות יקרות"),
    ("XV", 72, 83, "מתכות פשוטות ומוצריהן"),
    ("XVI", 84, 85, "מכונות וציוד חשמלי"),
    ("XVII", 86, 89, "כלי רכב, טיס ושיט"),
    ("XVIII", 90, 92, "מכשירים אופטיים ורפואיים"),
    ("XIX", 93, 93, "נשק ותחמושת"),
    ("XX", 94, 96, "מוצרים שונים (רהיטים, צעצועים)"),
    ("XXI", 97, 97, "אמנות ועתיקות"),
    ("XXII", 98, 99, "פרקים ישראליים"),
]
SPECIAL_SECTION = "פרטי תוספות"

LEVELS = ["פרק", "פרט", "פרט משנה", "סעיף ישראלי", "פרט תוספת"]
LEVEL_LABELS = {
    "פרק": "פרק (שתי ספרות)",
    "פרט": "פרט (ארבע ספרות)",
    "פרט משנה": "פרט משנה (שש ספרות)",
    "סעיף ישראלי": "סעיף ישראלי (פרט מלא)",
    "פרט תוספת": "פרט תוספת",
}

MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי", "אוגוסט",
             "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]


# ------------------------------------------------------------------ helpers
def n(v):
    return f"{int(v):,}"


def pct(v, digits=1):
    return f"{LRI}{v:.{digits}f}%{PDI}"


def short(s, k=34):
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= k else s[:k].rstrip(" ,;-:") + "…"


def date_he(ts):
    return f"{ts.day}.{ts.month}.{ts.year}"


def section_of(code):
    code = code.strip()
    if code.startswith("-"):
        return SPECIAL_SECTION
    m = re.match(r"(\d{2})", code)
    if not m:
        return ""
    ch = int(m.group(1))
    for s, lo, hi, nm in SECTIONS:
        if lo <= ch <= hi:
            return s
    return ""


SECTION_NAME = {s: nm for s, _, _, nm in SECTIONS}
SECTION_ORDER = [s for s, _, _, _ in SECTIONS] + [SPECIAL_SECTION]


def section_label(s):
    if s == SPECIAL_SECTION:
        return SPECIAL_SECTION
    return f"{SECTION_NAME.get(s, s)} ({s})"


def level_of(code):
    c = code.strip()
    if c.startswith("-"):
        return "פרט תוספת"
    d = re.sub(r"/.*$", "", c)
    if not re.fullmatch(r"\d{10}", d):
        return "סעיף ישראלי"
    if d[2:] == "0" * 8:
        return "פרק"
    if d[4:] == "0" * 6:
        return "פרט"
    if d[6:] == "0" * 4:
        return "פרט משנה"
    return "סעיף ישראלי"


def std_num(s):
    s = s.strip()
    if not s:
        return ""
    try:
        v = float(s)
    except ValueError:
        return s
    if not math.isfinite(v) or v <= 0:
        return ""
    return str(int(v)) if v == int(v) else s


def heading_of(desc):
    return re.split(r"\s+-\s+-->", desc)[0].strip(" -:")


def leaf_of(desc):
    return re.split(r"-->", desc)[-1].strip(" -:")


def _prep(df, group):
    out = pd.DataFrame({
        "grp": group,
        "pub": df["RegularityPublication"].str.strip(),
        "rid": df["RegularityRequirementID"].str.strip(),
        "item": df["CustomsItemFullClassification"].str.strip(),
        "desc": df["FullGoodsDescription"].str.strip(),
        "book": df["CustomsBookType"].str.strip(),
        "rcode": df["RegularityRequirement_CustomsItemFullClassification"].str.strip(),
        "rel": df["InterConditionsRelationship"].str.strip(),
        "inc": df["InceptionCode"].str.strip(),
        "src": df["RegularitySource"].str.strip(),
        "auth": df["RegularityRequirement_Authority"].str.replace(r"\s+", " ", regex=True).str.strip(),
        "conf": df["ConfirmationType"].str.replace(r"\s+", " ", regex=True).str.strip(),
        "carnet": df["IsCarnetIncluded"].str.strip().str.lower() == "true",
        "end": pd.to_datetime(df["EndDate"].str.strip(), errors="coerce", format="%Y-%m-%d"),
        "upd": pd.to_datetime(df["UpdateDate"].str.strip().str[:19], errors="coerce",
                              format="%Y-%m-%d %H:%M:%S"),
        "region": df["AutonomyRegularityRegionType"].str.strip(),
        "tr": df["TrNumber"].map(std_num),
    })
    if "IsPersonalImportIncluded" in df.columns:
        out["personal"] = df["IsPersonalImportIncluded"].str.strip().str.lower() == "true"
    else:
        out["personal"] = False
    out = out[out["item"] != ""]
    out["req"] = out["grp"] + "|" + out["pub"] + "|" + out["rid"]
    out["section"] = out["item"].map(section_of)
    return out


def _ranked(series_counts):
    return sorted(series_counts.items(), key=lambda kv: (-kv[1], kv[0]))


# ------------------------------------------------------------------ compute
def compute(frames):
    parts = [_prep(frames[g], g) for g in GROUP_ORDER]
    a = pd.concat(parts, ignore_index=True)
    by = {g: p for g, p in zip(GROUP_ORDER, parts)}
    present = [g for g in GROUP_ORDER if len(by[g])]

    n_rows = len(a)
    n_items = int(a["item"].nunique())
    n_reqs = int(a["req"].nunique())
    n_auth = int(a["auth"].replace("", pd.NA).dropna().nunique())
    n_conf = int(a["conf"].replace("", pd.NA).dropna().nunique())
    n_pubs = int(a["pub"].nunique())
    latest = a["upd"].max()
    earliest = a["upd"].min()

    # requirement-level frame (one row per requirement)
    rq = (a.sort_values(["req", "rcode", "item", "conf"])
          .groupby("req", sort=True)
          .agg(grp=("grp", "first"), pub=("pub", "first"), rcode=("rcode", "first"),
               src=("src", "first"), inc=("inc", "first"), rel=("rel", "first"),
               upd=("upd", "first"), items=("item", "nunique"),
               auths=("auth", "nunique"), auth=("auth", "first"))
          .reset_index())
    rq["level"] = rq["rcode"].map(level_of)

    # ---------------------------------------------------- 1. by publication
    pub_g = (a.groupby(["pub", "grp", "book"])
             .agg(rows=("item", "size"), reqs=("req", "nunique"), items=("item", "nunique"))
             .reset_index())
    pub_g = pub_g.sort_values(["items", "rows", "pub", "grp", "book"],
                              ascending=[False, False, True, True, True])
    orders_rows = [{"pub": r.pub, "grp": GROUP_LABEL[r.grp], "book": r.book,
                    "rows": n(r.rows), "reqs": n(r.reqs), "goods": n(r.items)}
                   for r in pub_g.itertuples()]
    orders_chart = {"names": [short(r.pub, 30) + (f" ({r.book})" if r.grp == "other" else "")
                              for r in pub_g.itertuples()],
                    "values": [int(r.items) for r in pub_g.itertuples()],
                    "full": [f"{r.pub} · {r.book}" for r in pub_g.itertuples()]}

    # book split
    book_items = a.groupby("book")["item"].nunique()
    book_rows = a.groupby("book").size()
    imp_rows = int(book_rows.get("יבוא", 0))
    exp_rows = int(book_rows.get("יצוא", 0))

    # ---------------------------------------------------- 2. authorities
    auth_items = a[a["auth"] != ""].groupby("auth")["item"].nunique()
    auth_rank = _ranked(auth_items)
    top_auth = [k for k, _ in auth_rank[:TOP_AUTH]]
    rest_auth = [k for k, _ in auth_rank[TOP_AUTH:]]
    ag = a[a["auth"] != ""].groupby(["auth", "grp"])["item"].nunique()
    auth_series = []
    for g in present:
        vals = [int(ag.get((k, g), 0)) for k in top_auth]
        if rest_auth:
            vals.append(int(a[a["auth"].isin(rest_auth) & (a["grp"] == g)]["item"].nunique()))
        auth_series.append({"name": GROUP_LABEL[g], "data": vals})
    auth_names = top_auth + ([f"{len(rest_auth)} גופים נוספים"] if rest_auth else [])
    auth_reqs = a[a["auth"] != ""].groupby("auth")["req"].nunique()
    auth_table = [{"name": k, "goods": n(v), "reqs": n(auth_reqs.get(k, 0)),
                   "grps": n(a[a["auth"] == k]["grp"].nunique())} for k, v in auth_rank[:TOP_AUTH]]
    if rest_auth:
        ra = a[a["auth"].isin(rest_auth)]
        auth_table.append({"name": f"{len(rest_auth)} גופים נוספים", "goods": n(ra["item"].nunique()),
                           "reqs": n(ra["req"].nunique()), "grps": n(ra["grp"].nunique())})

    # ---------------------------------------------------- 3. sections
    sec_present = [s for s in SECTION_ORDER if (a["section"] == s).any()]
    sg = a.groupby(["section", "grp"])["item"].nunique()
    sec_items = a.groupby("section")["item"].nunique()
    sec_series = [{"name": GROUP_LABEL[g], "data": [int(sg.get((s, g), 0)) for s in sec_present]}
                  for g in present]
    sa = a[a["auth"] != ""].groupby(["section", "auth"])["item"].nunique()
    sec_table = []
    for s in sec_present:
        cand = sorted(((k[1], int(v)) for k, v in sa.items() if k[0] == s), key=lambda kv: (-kv[1], kv[0]))
        sec_table.append({"name": section_label(s), "goods": n(sec_items.get(s, 0)),
                          "top": cand[0][0] if cand else "—",
                          "top_n": n(cand[0][1]) if cand else "0"})
    sec_rank = sorted(((s, int(sec_items.get(s, 0))) for s in sec_present), key=lambda kv: (-kv[1], kv[0]))

    # ---------------------------------------------------- 4. heatmap authority × section
    heat_cells = []
    heat_auth = top_auth
    for yi, au in enumerate(heat_auth):
        for xi, s in enumerate(sec_present):
            v = int(sa.get((s, au), 0))
            if v:
                heat_cells.append([xi, yi, v])
    heat_max = max((c[2] for c in heat_cells), default=1)

    # ---------------------------------------------------- 5. confirmation types
    conf_items = a[a["conf"] != ""].groupby("conf")["item"].nunique()
    conf_rank = _ranked(conf_items)[:TOP_CONF]
    conf_auth = (a[a["conf"] != ""].groupby(["conf", "auth"]).size().reset_index(name="c")
                 .sort_values(["conf", "c", "auth"], ascending=[True, False, True])
                 .drop_duplicates("conf").set_index("conf")["auth"])
    conf_grp = a[a["conf"] != ""].groupby("conf")["grp"].nunique()
    conf_chart = {"names": [short(k, 36) for k, _ in conf_rank], "values": [v for _, v in conf_rank],
                  "auth": [conf_auth.get(k, "") for k, _ in conf_rank]}
    conf_table = [{"name": k, "auth": conf_auth.get(k, ""), "goods": n(v),
                   "grps": n(conf_grp.get(k, 0))} for k, v in conf_rank]

    # ---------------------------------------------------- 6. legal source per group
    src_g = rq.groupby(["grp", "src"]).size()
    src_rank = _ranked(rq.groupby("src").size())
    src_names = [k for k, _ in src_rank]
    src_series = []
    for s in src_names:
        vals = []
        for g in present:
            tot = int((rq["grp"] == g).sum())
            vals.append(round(int(src_g.get((g, s), 0)) / tot * 100, 1) if tot else 0)
        src_series.append({"name": s, "data": vals,
                           "counts": [int(src_g.get((g, s), 0)) for g in present]})
    src_table = [{"grp": GROUP_LABEL[g], "cells": [n(src_g.get((g, s), 0)) for s in src_names],
                  "total": n((rq["grp"] == g).sum())} for g in present]
    # licence-type confirmations inside the first addendum
    lic_mask = a["conf"].str.contains("רישיון|רשיון", regex=True)
    a1 = a[a["src"] == "תוספת 1"]
    a1_lic_share = float(lic_mask[a1.index].mean() * 100) if len(a1) else None

    # ---------------------------------------------------- 7. requirement scope
    lv_g = rq.groupby(["grp", "level"]).size()
    lv_present = [lv for lv in LEVELS if (rq["level"] == lv).any()]
    scope_series = [{"name": LEVEL_LABELS[lv],
                     "data": [int(lv_g.get((g, lv), 0)) for g in present]} for lv in lv_present]
    lv_fan = rq.groupby("level")["items"].median()
    lv_cnt = rq.groupby("level").size()
    scope_table = [{"name": LEVEL_LABELS[lv], "reqs": n(lv_cnt.get(lv, 0)),
                    "median": f"{float(lv_fan.get(lv, 0)):g}"} for lv in lv_present]
    widest = rq.sort_values(["items", "req"], ascending=[False, True]).iloc[0] if len(rq) else None

    # ---------------------------------------------------- 8. burden per item
    burden = {}
    burden_x = [str(i) for i in range(1, BURDEN_CAP)] + [f"{BURDEN_CAP}+"]
    burden_series = []
    burden_stats = {}
    for g in present:
        rpi = by[g].groupby("item")["req"].nunique()
        vals = [int((rpi == i).sum()) for i in range(1, BURDEN_CAP)] + [int((rpi >= BURDEN_CAP).sum())]
        burden[g] = rpi
        burden_series.append({"name": GROUP_LABEL[g], "data": vals})
        burden_stats[g] = {"multi": int((rpi >= 2).sum()), "total": int(len(rpi)),
                           "max": int(rpi.max()) if len(rpi) else 0,
                           "mean": float(rpi.mean()) if len(rpi) else 0.0}
    burden_table = [{"name": burden_x[i], "cells": [n(s["data"][i]) for s in burden_series]}
                    for i in range(len(burden_x))]

    # ---------------------------------------------------- 9. standards
    st = a[(a["tr"] != "") & a["grp"].isin(["free_import", "personal_import"])]
    st_items = st.groupby("tr")["item"].nunique()
    st_rank = _ranked(st_items)[:TOP_STD]
    stg = st.groupby(["tr", "grp"])["item"].nunique()
    std_groups = [g for g in ["free_import", "personal_import"] if g in present and (st["grp"] == g).any()]
    std_chart = {"names": [f"ת״י {k}" for k, _ in st_rank],
                 "series": [{"name": GROUP_LABEL[g], "data": [int(stg.get((k, g), 0)) for k, _ in st_rank]}
                            for g in std_groups]}
    std_table = [{"name": f"ת״י {k}", "goods": n(v),
                  "cells": [n(stg.get((k, g), 0)) for g in std_groups]} for k, v in st_rank]
    fi = by["free_import"]
    fi_items = int(fi["item"].nunique())
    fi_std_items = int(fi[fi["tr"] != ""]["item"].nunique())
    n_std = int(st["tr"].nunique())
    std_alt = 0
    std_multi_conf = 0
    std_req_n = 0
    if len(st):
        sr = st.groupby("req").agg(rel=("rel", "first"), confs=("conf", "nunique"))
        std_req_n = len(sr)
        std_alt = int((sr["rel"] == "חליפי").sum())
        std_multi_conf = int((sr["confs"] >= 2).sum())

    # ---------------------------------------------------- 10. territories (other orders)
    oth = by["other"]
    terr = oth[oth["region"] != ""]
    reg_items = terr.groupby("region")["item"].nunique()
    reg_rank = _ranked(reg_items)
    terr_auth_rank = _ranked(terr[terr["auth"] != ""].groupby("auth")["item"].nunique())
    t_auth = [k for k, _ in terr_auth_rank[:TOP_TERR_AUTH]]
    t_rest = [k for k, _ in terr_auth_rank[TOP_TERR_AUTH:]]
    tg = terr.groupby(["region", "auth"])["item"].nunique()
    terr_names = [k for k, _ in reg_rank]
    terr_series = [{"name": au, "data": [int(tg.get((r, au), 0)) for r in terr_names]} for au in t_auth]
    if t_rest:
        terr_series.append({"name": "גופים אחרים",
                            "data": [int(terr[(terr["region"] == r) & terr["auth"].isin(t_rest)]["item"].nunique())
                                     for r in terr_names]})
    terr_table = [{"name": r, "goods": n(v), "reqs": n(terr[terr["region"] == r]["req"].nunique())}
                  for r, v in reg_rank]
    pa_only = terr[terr["region"] != "ישראל ואוטונומיה"]
    pa_items = int(pa_only["item"].nunique())
    pa_pub_rank = _ranked(pa_only.groupby("pub")["item"].nunique())
    pa_conf_rank = _ranked(pa_only[pa_only["conf"] != ""].groupby("conf")["item"].nunique())

    # ---------------------------------------------------- 11. last update year
    rq_valid = rq[rq["upd"].notna()].copy()
    rq_valid["year"] = rq_valid["upd"].dt.year.astype(int)
    yrs = sorted(rq_valid["year"].unique().tolist())
    years = list(range(yrs[0], yrs[-1] + 1)) if yrs else []   # continuous axis, gaps as zero
    yg = rq_valid.groupby(["year", "grp"]).size()
    upd_series = [{"name": GROUP_LABEL[g], "data": [int(yg.get((y, g), 0)) for y in years]} for g in present]
    yt = rq_valid.groupby("year").size()
    upd_table = [{"year": str(y), "cells": [n(yg.get((y, g), 0)) for g in present], "total": n(yt.get(y, 0))}
                 for y in years]
    last_year = years[-1] if years else None
    last_year_reqs = int(yt.get(last_year, 0)) if last_year else 0
    if last_year is not None:
        last_year_months = int(rq_valid[rq_valid["year"] == last_year]["upd"].dt.month.max())
    else:
        last_year_months = 0

    # ---------------------------------------------------- 12. end dates
    # one row per published condition (exact duplicate rows dropped); the end
    # date is set per condition (e.g. per standard), not per requirement
    cond = a.drop_duplicates(subset=["req", "item", "conf", "auth", "tr", "end", "inc", "src"])
    n_pairs = int(len(cond))   # unparseable/out-of-range dates (e.g. year 3000) are open-ended too
    cond = cond[cond["end"].notna()]
    open_cut = latest.year + OPEN_END_YEARS if pd.notna(latest) else 9999
    cond = cond.assign(year=cond["end"].dt.year.astype(int))
    dated = cond[cond["year"] < open_cut]
    n_dated_pairs = int(len(dated))
    passed = dated[dated["end"] < latest] if pd.notna(latest) else dated.iloc[0:0]
    n_passed = int(len(passed))
    n_passed_items = int(passed["item"].nunique())
    end_years = sorted(dated["year"].unique().tolist())
    if len(end_years) > MAX_END_BUCKETS:
        head = end_years[: len(end_years) - MAX_END_BUCKETS + 1]
        bucket = {y: (f"עד {head[-1]}") for y in head}
        keys = [f"עד {head[-1]}"] + [str(y) for y in end_years[len(head):]]
    else:
        bucket = {}
        keys = [str(y) for y in end_years]
    dated = dated.assign(bkt=dated["year"].map(lambda y: bucket.get(y, str(y))),
                         past=dated["end"] < latest if pd.notna(latest) else False)
    eb = dated.groupby(["bkt", "past"]).size()
    end_chart = {"x": keys, "past": [int(eb.get((k, True), 0)) for k in keys],
                 "future": [int(eb.get((k, False), 0)) for k in keys]}
    end_table = [{"year": k, "past": n(end_chart["past"][i]), "future": n(end_chart["future"][i])}
                 for i, k in enumerate(keys)]
    top_passed_date = None
    if len(passed):
        pdv = _ranked(passed.groupby("end").size())
        top_passed_date = (pdv[0][0], int(pdv[0][1]))
        top_passed_auth = _ranked(passed[passed["end"] == pdv[0][0]].groupby("auth").size())
    else:
        top_passed_auth = []

    # ---------------------------------------------------- 13. most regulated items
    it = (a[a["auth"] != ""].groupby("item")
          .agg(auths=("auth", "nunique"), reqs=("req", "nunique"), grps=("grp", "nunique"),
               desc=("desc", "first")).reset_index())
    desc_map = (a.sort_values(["item", "desc"]).drop_duplicates("item").set_index("item")["desc"])
    it["desc"] = it["item"].map(desc_map)
    it = it.sort_values(["auths", "reqs", "grps", "item"], ascending=[False, False, False, True])
    top_items = []
    it = it.assign(head4=it["item"].str.replace("-", "", regex=False).str[:4])
    it_top = it.drop_duplicates("head4")   # one line per heading, so the list is not one heading repeated
    for r in it_top.head(TOP_ITEMS).itertuples():
        h, l = heading_of(r.desc), leaf_of(r.desc)
        d = short(h, 44) if (not l or l == h) else f"{short(h, 34)} · {short(l, 26)}"
        top_items.append({"code": r.item, "desc": d, "auths": n(r.auths), "reqs": n(r.reqs),
                          "grps": n(r.grps)})
    multi_auth_items = int((it["auths"] >= 3).sum())

    # ---------------------------------------------------- personal vs free overlap
    s_free = set(by["free_import"]["item"])
    s_pers = set(by["personal_import"]["item"])
    both = len(s_free & s_pers)
    pers_only = len(s_pers - s_free)

    # ---------------------------------------------------- inc / rel / carnet
    inc_abs = int((rq["inc"] == "מוחלט").sum())
    carnet_g = {g: (float(by[g].groupby("req")["carnet"].max().mean() * 100) if len(by[g]) else 0.0)
                for g in present}
    for row, g in zip(src_table, present):
        row["carnet"] = f"{carnet_g[g]:.1f}%"
    personal_flag = oth[oth["book"] == "יבוא"].groupby("req")["personal"].max()
    personal_share = float(personal_flag.mean() * 100) if len(personal_flag) else None

    # ================================================================ insights
    def ins_leader():
        if len(auth_rank) < 2 or not n_items:
            return None
        (k1, v1), (k2, v2) = auth_rank[0], auth_rank[1]
        if v1 < v2 * 1.1:
            return None
        return (f"{k1} מעורב בדרישות על {n(v1)} פרטי מכס — {pct(v1 / n_items * 100)} מכלל "
                f"{n(n_items)} הפרטים שיש עליהם דרישה כלשהי, ולפני {k2} ({n(v2)} פרטים). "
                f"בסך הכול {n(n_auth)} גופים מוסמכים מופיעים בנתונים.")

    def ins_book():
        if not n_rows or not imp_rows:
            return None
        share = imp_rows / n_rows * 100
        if share < 60:
            return None
        return (f"היבוא מכביד הרבה יותר מהיצוא: {pct(share)} מהשורות ({n(imp_rows)}) נוגעות לספר "
                f"היבוא, לעומת {n(exp_rows)} בלבד לספר היצוא; {n(book_items.get('יבוא', 0))} פרטי "
                f"מכס מוסדרים ביבוא ו-{n(book_items.get('יצוא', 0))} ביצוא.")

    def ins_burden():
        s = burden_stats.get("free_import")
        if not s or not s["total"] or not s["multi"]:
            return None
        share = s["multi"] / s["total"] * 100
        if share < 10:
            return None
        return (f"בצו יבוא חופשי {pct(share)} מהפרטים המוסדרים ({n(s['multi'])} מתוך {n(s['total'])}) "
                f"כפופים לשתי דרישות נפרדות או יותר, ועד {n(s['max'])} דרישות לפרט. "
                f"{n(multi_auth_items)} פרטים בכלל הצווים דורשים מעורבות של שלושה גופים או יותר.")

    def ins_standards():
        if not st_rank or not fi_items or not fi_std_items:
            return None
        k, v = st_rank[0]
        txt = (f"{n(fi_std_items)} מהפרטים בצו יבוא חופשי ({pct(fi_std_items / fi_items * 100)}) "
               f"קשורים לתקן ישראלי רשמי — {n(n_std)} תקנים שונים ביבוא המסחרי והאישי; "
               f"ת״י {k} מכסה לבדו {n(v)} פרטים.")
        if std_req_n and std_alt / std_req_n >= 0.8 and std_multi_conf / std_req_n >= 0.5:
            txt += (f" ב-{pct(std_alt / std_req_n * 100, 0)} מדרישות התקינה התנאים חליפיים — "
                    f"די באחד מכמה אישורים.")
        return txt

    def ins_personal():
        if not s_pers or not s_free:
            return None
        sp = burden_stats.get("personal_import")
        sf = burden_stats.get("free_import")
        txt = (f"צו יבוא אישי מסדיר {n(len(s_pers))} פרטים, לעומת {n(len(s_free))} בצו יבוא חופשי; "
               f"{n(both)} מהם מופיעים בשניהם")
        if pers_only:
            txt += f", ורק {n(pers_only)} מוסדרים ביבוא האישי בלבד"
        txt += "."
        if sp and sf and sf["mean"] > sp["mean"]:
            txt += (f" בממוצע {sp['mean']:.2f} דרישות לפרט ביבוא האישי, לעומת "
                    f"{sf['mean']:.2f} ביבוא המסחרי.")
        return txt

    def ins_licence():
        g = "free_export"
        if g not in present or "free_import" not in present:
            return None
        def share(gr):
            tot = int((rq["grp"] == gr).sum())
            return (int(src_g.get((gr, "תוספת 1"), 0)) / tot * 100) if tot else 0.0
        se, si = share(g), share("free_import")
        if se < 20 or se < si * 1.5 or a1_lic_share is None or a1_lic_share < 80:
            return None
        return (f"ביצוא נפוץ רישיון יותר מביבוא: {pct(se)} מהדרישות בצו יצוא חופשי הן מתוספת 1, "
                f"לעומת {pct(si)} בצו יבוא חופשי; {pct(a1_lic_share, 0)} מהשורות בתוספת 1 דורשות "
                f"רישיון.")

    def ins_expired():
        if not n_passed or top_passed_date is None or pd.isna(latest):
            return None
        d, c = top_passed_date
        txt = (f"{n(n_passed)} תנאים ב-{n(n_passed_items)} פרטי מכס נושאים מועד סיום שכבר חלף לפני "
               f"העדכון האחרון בנתונים ({date_he(latest)}) ועדיין מופיעים בהם; המועד הנפוץ ביניהם "
               f"הוא {date_he(d)} ({n(c)} תנאים)")
        std_share = float((passed["tr"] != "").mean() * 100) if len(passed) else 0.0
        if std_share >= 50:
            txt += f"; {pct(std_share, 0)} מהם תנאים הקשורים לתקן ישראלי"
        elif top_passed_auth and (len(top_passed_auth) == 1 or top_passed_auth[0][1] > top_passed_auth[1][1]) \
                and top_passed_auth[0][1] / c >= 0.5:
            txt += f", בעיקר בדרישות של {top_passed_auth[0][0]}"
        return txt + "."

    def ins_territories():
        if not pa_items or not pa_pub_rank:
            return None
        p, v = pa_pub_rank[0]
        txt = (f"{n(pa_items)} פרטים מוסדרים בדרישות החלות רק על שטחי הרשות הפלסטינית (עזה ו/או "
               f"איו״ש), {n(v)} מהם לפי {p}")
        if pa_conf_rank:
            txt += f"; האישור הנפוץ: {pa_conf_rank[0][0]} ({n(pa_conf_rank[0][1])} פרטים)"
        return txt + "."

    def ins_wide():
        if widest is None or widest["items"] < 50:
            return None
        lv = widest["level"]
        code = re.sub(r"/.*$", "", widest["rcode"])
        where = {"פרק": f"פרק {code[:2]}", "פרט": f"פרט {code[:2]}.{code[2:4]}"}.get(lv, f"סיווג {code}")
        txt = (f"הדרישה הרחבה ביותר, של {widest['auth']} ב{GROUP_LABEL[widest['grp']]}, מוגדרת ברמת "
               f"{where} וחלה על {n(widest['items'])} פרטי מכס"
               + (" — חלקית, רק לטובין שתיאורם מפורט בה." if widest["inc"] == "חלקי" else "."))
        ch = lv_cnt.get("פרק", 0)
        if ch:
            txt += (f" {n(ch)} דרישות מוגדרות ברמת פרק שלם, עם חציון של "
                    f"{float(lv_fan.get('פרק', 0)):g} פרטים לדרישה.")
        return txt

    def ins_updated():
        if last_year is None or not n_reqs or len(years) < 2:
            return None
        share = last_year_reqs / n_reqs * 100
        partial = last_year_months < 12
        txt = (f"{n(last_year_reqs)} דרישות ({pct(share)}) עודכנו לאחרונה ב-{last_year}"
               + (f" (עד {MONTHS_HE[last_year_months - 1]}, שנה חלקית)" if partial else "")
               + f"; בקצה השני, הדרישות הוותיקות ביותר לא עודכנו מאז {years[0]}.")
        return txt

    rules = [
        ("leader", ins_leader()), ("book", ins_book()), ("burden", ins_burden()),
        ("standards", ins_standards()), ("personal", ins_personal()), ("licence", ins_licence()),
        ("wide", ins_wide()), ("territories", ins_territories()), ("expired", ins_expired()),
        ("updated", ins_updated()),
    ]
    insights = [{"id": i, "text_he": x} for i, x in rules if x]

    # ================================================================ kpis
    fs_ = burden_stats.get("free_import", {"multi": 0, "total": 0})
    multi_share = fs_["multi"] / fs_["total"] * 100 if fs_["total"] else 0.0
    passed_share = n_passed / n_pairs * 100 if n_pairs else 0.0
    kpis = {
        "rows": {"value": n_rows, "display": n(n_rows), "tone": "brand"},
        "goods": {"value": n_items, "display": n(n_items), "tone": "brand"},
        "reqs": {"value": n_reqs, "display": n(n_reqs), "tone": "brand"},
        "auth": {"value": n_auth, "display": n(n_auth), "tone": "brand"},
        "conf": {"value": n_conf, "display": n(n_conf), "tone": "brand"},
        "multi": {"value": round(multi_share, 1), "display": f"{multi_share:.1f}%",
                  "tone": "warn" if multi_share >= 25 else "info"},
        "passed": {"value": n_passed, "display": n(n_passed),
                   "tone": "ok" if n_passed == 0 else ("danger" if passed_share >= 10 else "warn")},
        "pa": {"value": pa_items, "display": n(pa_items), "tone": "info"},
    }

    # ================================================================ labels
    grp_counts = ", ".join(f"{GROUP_LABEL[g]} {n(len(by[g]))}" for g in present)
    labels = {
        "lede": (f"אילו אישורים, רישיונות ותקנים נדרשים כדי לייבא או לייצא כל פרט מכס, ומי הגוף "
                 f"המוסמך לתת אותם. {n(n_rows)} שורות בארבעה קבצים ({grp_counts}), המכסות "
                 f"{n(n_items)} פרטי מכס ו-{n(n_reqs)} דרישות של {n(n_auth)} גופים, לפי "
                 f"{n(n_pubs)} צווים וחוקים. כל דרישה מוגדרת ברמת סיווג מסוימת וחלה על כל הפרטים "
                 f"שתחתיה; היא יכולה לדרוש כמה אישורים — כולם או אחד מהם."),
        "multi_kpi": "מהפרטים בצו יבוא חופשי כפופים לשתי דרישות ומעלה",
        "passed_kpi": "תנאים שמועד סיומם חלף",
        "pa_kpi": "פרטים בדרישות החלות רק בשטחי הרשות הפלסטינית",
        "orders_note": (f"מספר פרטי המכס שחלה עליהם דרישה לפי כל צו או חוק. בקובץ הצווים הנוספים "
                        f"מופיע לצד השם גם ספר המכס (יבוא או יצוא)."),
        "orders_aria": f"תרשים עמודות: פרטי מכס לפי צו או חוק, {n(len(orders_rows))} צווים.",
        "orders_caption": "צווים וחוקים: שורות, דרישות ופרטי מכס.",
        "auth_note": (f"{len(top_auth)} הגופים המוסמכים לפי מספר פרטי המכס שבהם הם נדרשים, מפוצלים "
                      f"לפי קובץ הצו. פרט שמוסדר בשני צווים נספר בכל אחד מהם."),
        "auth_aria": f"תרשים עמודות מוערמות: פרטי מכס לפי גוף מוסמך, {len(auth_names)} קטגוריות.",
        "auth_caption": "גופים מוסמכים: פרטי מכס, דרישות ומספר קבצי הצו שבהם מופיעים.",
        "sec_note": (f"פרטי המכס המוסדרים לפי חלק במערכת ההרמוניזציה (לפי שתי הספרות הראשונות של "
                     f"הפרט)."
                     + (f" המוביל: {section_label(sec_rank[0][0])} עם {n(sec_rank[0][1])} פרטים." if sec_rank else "")),
        "sec_aria": f"תרשים עמודות מוערמות: פרטי מכס מוסדרים לפי חלק, {len(sec_present)} חלקים.",
        "sec_caption": "פרטי מכס מוסדרים לפי חלק, והגוף המעורב ביותר בכל חלק.",
        "heat_note": (f"באיזה תחום עוסק כל גוף: מספר פרטי המכס של כל אחד מ-{len(heat_auth)} הגופים "
                      f"המובילים בכל חלק."),
        "heat_aria": "מפת חום: פרטי מכס לפי גוף מוסמך וחלק.",
        "conf_note": (f"{len(conf_rank)} סוגי האישור הנפוצים מתוך {n(n_conf)}, לפי מספר פרטי המכס "
                      f"שבהם הם נדרשים; הקוד שבסוגריים הוא קוד האישור."),
        "conf_aria": f"תרשים עמודות: {len(conf_rank)} סוגי האישור הנפוצים לפי פרטי מכס.",
        "conf_caption": "סוגי אישור: הגוף המנפיק, פרטי מכס ומספר קבצי הצו.",
        "src_note": ("מקור הדרישה בתוך הצו, כאחוז מהדרישות בכל קובץ."
                     + (f" בתוספת 1 {pct(a1_lic_share, 0)} מהשורות הן רישיון." if a1_lic_share is not None else "")),
        "src_aria": "תרשים עמודות מוערמות: מקור הדרישה באחוזים לפי קובץ הצו.",
        "src_caption": "מספר הדרישות לפי מקור, בכל קובץ צו.",
        "scope_note": ("באיזו רמת סיווג מוגדרת כל דרישה. דרישה ברמת פרק חלה על כל הפרטים שבו; "
                       "החציון בטבלה הוא מספר פרטי המכס לדרישה."
                       + (f" {n(inc_abs)} מתוך {n(n_reqs)} הדרישות מוחלטות — חלות על הפרט כולו; "
                          f"השאר חלקיות, רק לטובין שתיאורם מפורט בדרישה." if n_reqs else "")),
        "scope_aria": "תרשים עמודות מוערמות: דרישות לפי רמת הסיווג שבה הוגדרו, בכל קובץ צו.",
        "scope_caption": "דרישות לפי רמת סיווג, וחציון פרטי המכס לדרישה.",
        "burden_note": (f"כמה דרישות נפרדות חלות על כל פרט מכס, בכל קובץ צו (העמודה האחרונה: "
                        f"{BURDEN_CAP} ומעלה)."),
        "burden_aria": "תרשים עמודות: פרטי מכס לפי מספר הדרישות החלות עליהם, בכל קובץ צו.",
        "burden_caption": "פרטי מכס לפי מספר דרישות, בכל קובץ צו.",
        "std_note": (f"{len(st_rank)} התקנים הישראליים הרשמיים הקשורים למספר הפרטים הגדול ביותר, ביבוא "
                     f"המסחרי ובאישי."),
        "std_aria": f"תרשים עמודות: {len(st_rank)} תקנים ישראליים לפי מספר פרטי מכס.",
        "std_caption": "תקנים ישראליים: פרטי מכס לפי צו.",
        "terr_note": ("בקובץ הצווים הנוספים חלק מהדרישות חלות רק בשטחי הרשות הפלסטינית. פרטי המכס לפי "
                      "אזור התחולה והגוף המוסמך."
                      + (f" {pct(personal_share, 0)} מדרישות היבוא בקובץ זה חלות גם על יבוא אישי."
                         if personal_share is not None else "")),
        "terr_aria": "תרשים עמודות מוערמות: פרטי מכס לפי אזור תחולה וגוף מוסמך.",
        "terr_caption": "פרטי מכס ודרישות לפי אזור תחולה, בקובץ הצווים הנוספים.",
        "upd_note": ("מתי עודכנה לאחרונה כל דרישה, לפי שנה."
                     + (f" השנה {last_year} חלקית — עד {MONTHS_HE[last_year_months - 1]}." if last_year and last_year_months < 12 else "")),
        "upd_aria": f"תרשים עמודות מוערמות: דרישות לפי שנת העדכון האחרון, {len(years)} שנים.",
        "upd_caption": "דרישות לפי שנת העדכון האחרון, בכל קובץ צו.",
        "end_note": (f"{n(n_dated_pairs)} מתוך {n(n_pairs)} התנאים (שורה לכל פרט, דרישה ואישור) נושאים מועד סיום; "
                     f"השאר ללא הגבלה (מועד סמלי רחוק, {open_cut} ואילך). מועד שחלף נמדד מול העדכון "
                     f"האחרון בנתונים{(' (' + date_he(latest) + ')') if pd.notna(latest) else ''}."),
        "end_aria": "תרשים עמודות מוערמות: תנאים לפי שנת סיום התוקף.",
        "end_caption": "תנאים לפי שנת סיום, שחלפו ועתידיים.",
        "items_caption": f"{len(top_items)} פרטי המכס עם מספר הגופים המוסמכים הגדול ביותר, פרט אחד לכל פרט ארבע ספרות.",
        "items_note": ("הפרטים שבהם מעורבים הכי הרבה גופים, בכל הצווים יחד — הפרט המוביל בכל פרט "
                       "ארבע ספרות. הקוד הוא פרט המכס המלא עם ספרת הביקורת."),
    }

    charts = {
        "orders": orders_chart,
        "auth": {"names": auth_names, "series": auth_series},
        "sec": {"names": [section_label(s) for s in sec_present], "series": sec_series},
        "heat": {"x": [s if s != SPECIAL_SECTION else "תוספות" for s in sec_present],
                 "xfull": [section_label(s) for s in sec_present],
                 "y": heat_auth, "cells": heat_cells, "max": heat_max},
        "conf": conf_chart,
        "src": {"names": [GROUP_LABEL[g] for g in present], "series": src_series},
        "scope": {"names": [GROUP_LABEL[g] for g in present], "series": scope_series},
        "burden": {"x": burden_x, "series": burden_series},
        "std": std_chart,
        "terr": {"names": terr_names, "series": terr_series},
        "upd": {"x": [str(y) for y in years], "series": upd_series},
        "end": end_chart,
    }
    tables = {
        "orders": orders_rows,
        "auth": auth_table,
        "sec": sec_table,
        "conf": conf_table,
        "src_head": src_names,
        "src": src_table,
        "scope": scope_table,
        "burden_head": [GROUP_LABEL[g] for g in present],
        "burden": burden_table,
        "std_head": [GROUP_LABEL[g] for g in std_groups],
        "std": std_table,
        "terr": terr_table,
        "upd_head": [GROUP_LABEL[g] for g in present],
        "upd": upd_table,
        "end": end_table,
        "top_items": top_items,
    }
    flags = {
        "std": bool(st_rank),
        "terr": bool(terr_names) and len(terr_names) >= 2,
        "end": bool(keys),
        "heat": bool(heat_cells),
    }

    agent_data = {
        "summary_he": (f"הדרישות החוקיות ליבוא וליצוא טובין לפי פרט מכס: {n(n_items)} פרטים, "
                       f"{n(n_reqs)} דרישות ו-{n(n_conf)} סוגי אישור של {n(n_auth)} גופים, לפי צו יבוא "
                       f"חופשי, צו יבוא אישי, צו יצוא חופשי וצווים נוספים."
                       + (f" המעורב ביותר: {auth_rank[0][0]} ({n(auth_rank[0][1])} פרטים)." if auth_rank else "")),
        "dataset_kind": "registry",
        "suggested_tags": ["מכס", "יבוא", "יצוא", "דרישות חוקיות", "צו יבוא חופשי", "רישיונות ואישורים",
                           "תקנים"],
        "related_ids": ["3de0e7f0-03e1-4665-b078-da6e87543ed7",
                        "3e4e79f7-643b-4be6-94c2-e47667d42916",
                        "965b52b6-7267-45d9-bccd-020416fbcfb5"],
        "spatial_coverage": "ישראל ושטחי הרשות הפלסטינית",
    }

    return {
        "agent_data": agent_data,
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
        "flags": flags,
    }
