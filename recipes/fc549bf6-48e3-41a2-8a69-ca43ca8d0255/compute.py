"""Water Authority boreholes registry (קידוחי רשות המים).

One row per licensed borehole: status, ownership (Mekorot / private
consumer), water group (fresh / brackish / Shafdan / treated + purpose),
aquifer, max hourly capacity, regions, and a national number that encodes
the borehole's 1 km grid square on the old Israeli grid (EEE NNN + serial).

Every number on the page is computed here; insight rules return a sentence
or None when their premise does not hold.
"""
import math
import re

import pandas as pd

COL_STATUS = "סטאטוס"
COL_OWNERSHIP = "בעלות המתקן"
COL_OWNER = "שם צרכן בעל המתקן"
COL_GROUP = "קבוצת מים"
COL_AQUIFER = "אקוויפר"
COL_FLOW = "ספיקה שעתית מקסימלית"
COL_NATIONAL = "מספר ארצי"
COL_PROD = "אזור הפקה"
COL_AGRI = "אזור חקלאי"
COL_ADMIN = "אזור אדמיניסטרטיבי"

UNSPEC = "לא צוין"
OTHER = "שאר הקטגוריות"
ACTIVE = "פעיל"
MEKOROT = "מקורות"
PRIVATE = "צרכן פרטי"
# Known status codes, in reading order; unknown ones follow by count.
STATUS_ORDER = ["פעיל", "לא פעיל", "לא פעיל לצמיתות", "רישיון סתימה", "בקשה"]
OWNERSHIP_ORDER = ["מקורות", "צרכן פרטי"]
WATER_ORDER = ["שפיר", "מליח", "שפד״ן (השבת קולחים)", "מטויב", "לא מסווג"]

TOP_ADMIN = 15
TOP_OWNERS = 12
MIN_OWNER_WELLS = 5
TOP_HEAT_REGIONS = 9
TOP_HEAT_AQUIFERS = 7
MAP_CHUNK = 600
FLOW_BINS = [(0, 50), (50, 100), (100, 150), (150, 200), (200, 300), (300, 500), (500, None)]

# Old Israeli grid (Israeli CS Grid, Cassini-Soldner on Clarke 1880).
_A = 6378300.789
_B = 6356566.435
_E2 = 1 - (_B * _B) / (_A * _A)
_LAT0 = math.radians(31.73409694444445)
_LON0 = math.radians(35.21208055555556)
_X0 = 170251.555
_Y0 = 1126867.909


def _int(n):
    return f"{int(n):,}"


def _pct(x):
    return f"{x * 100:.1f}%"


def _clean(s):
    return s.fillna("").astype(str).str.strip().str.replace(r"\s+", " ", regex=True)


def _sorted_counts(series):
    """Value counts, count desc then label asc (total, row-order free)."""
    vc = series.value_counts()
    return vc.sort_index().sort_values(ascending=False, kind="stable")


def _ordered(labels_counts, known):
    """Known codes first in fixed order, then the rest by count/label."""
    out = [k for k in known if k in labels_counts.index]
    out += [k for k in labels_counts.index if k not in known]
    return out


def _meridian(phi):
    e2, e4, e6 = _E2, _E2 ** 2, _E2 ** 3
    return _A * ((1 - e2 / 4 - 3 * e4 / 64 - 5 * e6 / 256) * phi
                 - (3 * e2 / 8 + 3 * e4 / 32 + 45 * e6 / 1024) * math.sin(2 * phi)
                 + (15 * e4 / 256 + 45 * e6 / 1024) * math.sin(4 * phi)
                 - (35 * e6 / 3072) * math.sin(6 * phi))


def _cass_inverse(x, y):
    """Israeli CS Grid metres -> (lat, lon) degrees (Snyder, ellipsoidal)."""
    e2 = _E2
    m1 = _meridian(_LAT0) + (y - _Y0)
    mu = m1 / (_A * (1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256))
    s = math.sqrt(1 - e2)
    e1 = (1 - s) / (1 + s)
    phi1 = (mu + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * math.sin(2 * mu)
            + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32) * math.sin(4 * mu)
            + (151 * e1 ** 3 / 96) * math.sin(6 * mu)
            + (1097 * e1 ** 4 / 512) * math.sin(8 * mu))
    t1 = math.tan(phi1) ** 2
    sin1 = math.sin(phi1)
    n1 = _A / math.sqrt(1 - e2 * sin1 * sin1)
    r1 = _A * (1 - e2) / (1 - e2 * sin1 * sin1) ** 1.5
    d = (x - _X0) / n1
    phi = phi1 - (n1 * math.tan(phi1) / r1) * (d * d / 2 - (1 + 3 * t1) * d ** 4 / 24)
    lam = _LON0 + (d - t1 * d ** 3 / 3 + (1 + 3 * t1) * t1 * d ** 5 / 15) / math.cos(phi1)
    return math.degrees(phi), math.degrees(lam)


def _grid_cell(code):
    """National number -> (E km, N km short form) or None.

    The number is EEE NNN + two serial digits; some carry a Hebrew letter
    suffix/prefix (a twin borehole), which is stripped.
    """
    digits = re.sub(r"\D", "", code)
    if len(digits) != 8:
        return None
    e, n = int(digits[:3]), int(digits[3:6])
    if not 80 <= e <= 280:
        return None
    return e, n


def _cell_latlon(e, n):
    full_n = n + 1000 if n < 700 else n  # short form drops the thousands
    lat, lon = _cass_inverse((e + 0.5) * 1000.0, (full_n + 0.5) * 1000.0)
    if not (29.3 <= lat <= 33.5 and 34.1 <= lon <= 36.0):
        return None
    return lat, lon


def _water_type(group):
    g = group.replace('"', "״").replace("'", "׳")
    if "שפד" in g:
        return "שפד״ן (השבת קולחים)"
    if "מטויב" in g:
        return "מטויב"
    if "מליח" in g or "מלוח" in g:
        return "מליח"
    if "שפיר" in g:
        return "שפיר"
    return "לא מסווג"


def _status_split(df, key, cats, statuses):
    """{cats, series:[{name, data}], total, active} for a stacked bar."""
    ct = pd.crosstab(df[key], df["status"])
    series = []
    for s in statuses:
        col = ct[s] if s in ct.columns else pd.Series(0, index=ct.index)
        series.append({"name": s, "data": [int(col.get(c, 0)) for c in cats]})
    tot = [int(ct.loc[c].sum()) if c in ct.index else 0 for c in cats]
    act = [int(ct.loc[c, ACTIVE]) if (c in ct.index and ACTIVE in ct.columns) else 0 for c in cats]
    rows = [{"name": c, "total": _int(t), "active": _int(a),
             "share": _pct(a / t) if t else "0.0%"} for c, t, a in zip(cats, tot, act)]
    return {"cats": cats, "series": series, "total": tot, "active": act}, rows


# ── insight rules ────────────────────────────────────────────────────────

def insight_active(total, status_counts):
    if total == 0:
        return None
    act = int(status_counts.get(ACTIVE, 0))
    rest = [(s, int(v)) for s, v in status_counts.items() if s != ACTIVE and v > 0]
    rest_txt = ", ".join(f"{_int(v)} בסטטוס {s}" for s, v in rest[:3])
    tail = f" לצדם {rest_txt}." if rest_txt else ""
    return f"{_int(act)} מתוך {_int(total)} הקידוחים במאגר ({_pct(act / total)}) מסומנים כפעילים.{tail}"


def insight_owner_gap(df):
    m = df[df["ownership"] == MEKOROT]
    p = df[df["ownership"] == PRIVATE]
    if len(m) < 30 or len(p) < 30:
        return None
    rm = (m["status"] == ACTIVE).mean()
    rp = (p["status"] == ACTIVE).mean()
    if abs(rm - rp) < 0.10:
        return (f"שיעור הקידוחים הפעילים דומה אצל מקורות ({_pct(rm)}) ואצל צרכנים פרטיים "
                f"({_pct(rp)}).")
    if rm > rp:
        hi, lo, rhi, rlo, nhi, nlo = "מקורות", "צרכנים פרטיים", rm, rp, len(m), len(p)
    else:
        hi, lo, rhi, rlo, nhi, nlo = "צרכנים פרטיים", "מקורות", rp, rm, len(p), len(m)
    return (f"פער בולט בין בעלי הקידוחים: אצל {hi} פעילים {_pct(rhi)} מהקידוחים "
            f"({_int(nhi)} קידוחים), לעומת {_pct(rlo)} אצל {lo} ({_int(nlo)} קידוחים).")


def insight_aquifer(aq_counts, n_missing):
    known = int(aq_counts.sum())
    if known == 0:
        return None
    name, v = aq_counts.index[0], int(aq_counts.iloc[0])
    share = v / known
    if share < 0.3:
        return None
    miss = f" (מתוך {_int(known)} קידוחים שהאקוויפר שלהם צוין; ל-{_int(n_missing)} לא צוין אקוויפר)" if n_missing else ""
    return f"האקוויפר הנפוץ ביותר הוא {name}: {_int(v)} קידוחים, {_pct(share)}{miss}."


def insight_brackish(df):
    n = len(df)
    b = df[df["water"] == "מליח"]
    if n == 0 or len(b) / n < 0.05:
        return None
    ba = (b["status"] == ACTIVE).mean() if len(b) else 0
    return (f"{_int(len(b))} קידוחים ({_pct(len(b) / n)}) מסווגים כקידוחי מים מליחים, "
            f"ו-{_pct(ba)} מהם פעילים.")


def insight_dewater(df):
    d = df[df["dewater"]]
    if len(d) < 10:
        return None
    act = int((d["status"] == ACTIVE).sum())
    return (f"{_int(len(d))} קידוחים רשומים בקבוצות מים של סילוק (הרחקת מי תהום), "
            f"מתוכם {_int(act)} פעילים.")


def insight_region(reg_counts, total):
    known = reg_counts.drop(labels=[UNSPEC], errors="ignore")
    if known.empty or total == 0:
        return None
    name, v = known.index[0], int(known.iloc[0])
    if v / total < 0.25:
        return None
    second = ""
    if len(known) > 1:
        second = f", ואחריו {known.index[1]} עם {_int(known.iloc[1])}"
    return f"האזור החקלאי {name} מרכז את מספר הקידוחים הגדול ביותר: {_int(v)} ({_pct(v / total)}){second}."


def insight_admin(admin_counts, total):
    if admin_counts.empty or total == 0:
        return None
    # Pseudo-areas ("חסר מעמד מוניציפלי", "יהודה ושומרון") are not authorities.
    real = admin_counts[~admin_counts.index.str.contains("חסר מעמד|יהודה ושומרון", regex=True)]
    if real.empty:
        return None
    name, v = real.index[0], int(real.iloc[0])
    if v < 20 or (len(real) > 1 and int(real.iloc[1]) == v):
        return None
    return (f"הרשות המקומית עם מספר הקידוחים הגדול ביותר היא {name}: {_int(v)} קידוחים "
            f"({_pct(v / total)} מהמאגר).")


def insight_owner_top(owner_counts):
    if owner_counts.empty:
        return None
    name, v = owner_counts.index[0], int(owner_counts.iloc[0])
    if v < 10:
        return None
    return f"בעל הקידוחים הפרטי הגדול ביותר הוא {name}, עם {_int(v)} קידוחים רשומים."


def insight_flow(flow, total):
    if len(flow) < 30:
        return None
    med = flow.median()
    p90 = flow.quantile(0.9)
    return (f"הספיקה השעתית המקסימלית החציונית היא {med:,.0f} מ״ק לשעה, ו-10% מהקידוחים שיש להם נתון "
            f"מגיעים ל-{p90:,.0f} ומעלה (נתון הספיקה מולא ל-{_int(len(flow))} קידוחים בלבד, "
            f"{_pct(len(flow) / total)} מהמאגר).")


def insight_national(df):
    n = len(df)
    nat = int((df["prod"] == "מערכת ארצית").sum())
    if n == 0 or nat / n < 0.1:
        return None
    return (f"{_int(nat)} קידוחים ({_pct(nat / n)}) משויכים לאזור ההפקה של המערכת הארצית; "
            f"ל-{_int(int((df['prod'] == '').sum()))} לא צוין אזור הפקה.")


# ── compute ──────────────────────────────────────────────────────────────

def compute(frames):
    raw = frames["wells"]
    df = pd.DataFrame({
        "status": _clean(raw[COL_STATUS]).replace("", UNSPEC),
        "ownership": _clean(raw[COL_OWNERSHIP]).replace("", UNSPEC),
        "owner": _clean(raw[COL_OWNER]),
        "group": _clean(raw[COL_GROUP]),
        "aquifer": _clean(raw[COL_AQUIFER]),
        "flow": pd.to_numeric(_clean(raw[COL_FLOW]).str.replace(",", ""), errors="coerce"),
        "national": _clean(raw[COL_NATIONAL]),
        "prod": _clean(raw[COL_PROD]),
        "agri": _clean(raw[COL_AGRI]).replace("", UNSPEC),
        "admin": _clean(raw[COL_ADMIN]),
    })
    df["water"] = df["group"].map(_water_type)
    df["dewater"] = df["group"].str.contains("סילוק", regex=False)
    total = len(df)

    # status
    status_counts = _sorted_counts(df["status"])
    statuses = _ordered(status_counts, STATUS_ORDER)
    status_counts = status_counts.reindex(statuses)
    n_active = int(status_counts.get(ACTIVE, 0))
    n_inactive = total - n_active
    status_chart = {"names": statuses, "values": [int(status_counts[s]) for s in statuses]}
    status_rows = [{"name": s, "n": _int(status_counts[s]),
                    "share": _pct(status_counts[s] / total) if total else "0.0%"} for s in statuses]

    # ownership × status
    own_counts = _sorted_counts(df["ownership"])
    owns = _ordered(own_counts, OWNERSHIP_ORDER)
    own_chart, own_rows = _status_split(df, "ownership", owns, statuses)

    # water type × status
    wt_counts = _sorted_counts(df["water"])
    wts = _ordered(wt_counts, WATER_ORDER)
    water_chart, water_rows = _status_split(df, "water", wts, statuses)
    n_dewater = int(df["dewater"].sum())

    # aquifer × status (empty aquifer disclosed, shown last)
    aq = df[df["aquifer"] != ""]
    aq_counts = _sorted_counts(aq["aquifer"])
    n_aq_missing = total - len(aq)
    aq_cats = list(aq_counts.index)
    aq_df = df.assign(aquifer=df["aquifer"].replace("", UNSPEC))
    if n_aq_missing:
        aq_cats = aq_cats + [UNSPEC]
    aq_chart, aq_rows = _status_split(aq_df, "aquifer", aq_cats, statuses)

    # agricultural region × status
    reg_counts = _sorted_counts(df["agri"])
    reg_cats = [c for c in reg_counts.index if c != UNSPEC] + ([UNSPEC] if UNSPEC in reg_counts.index else [])
    reg_chart, reg_rows = _status_split(df, "agri", reg_cats, statuses)

    # region × aquifer heatmap (rows with both known)
    hd = df[(df["agri"] != UNSPEC) & (df["aquifer"] != "")]
    h_reg = list(_sorted_counts(hd["agri"]).index[:TOP_HEAT_REGIONS])
    h_aq = list(_sorted_counts(hd["aquifer"]).index[:TOP_HEAT_AQUIFERS])
    hreg = hd["agri"].where(hd["agri"].isin(h_reg), OTHER)
    haq = hd["aquifer"].where(hd["aquifer"].isin(h_aq), OTHER)
    if (hreg == OTHER).any():
        h_reg = h_reg + [OTHER]
    if (haq == OTHER).any():
        h_aq = h_aq + [OTHER]
    hct = pd.crosstab(hreg, haq)
    cells = []
    hmax = 0
    for yi, r in enumerate(h_reg):
        for xi, a in enumerate(h_aq):
            v = int(hct.loc[r, a]) if (r in hct.index and a in hct.columns) else 0
            if v:
                cells.append([xi, yi, v])
                hmax = max(hmax, v)
    heat_chart = {"x": h_aq, "y": h_reg, "cells": cells, "max": hmax}

    # local authorities
    adm = df[df["admin"] != ""]
    adm_counts = _sorted_counts(adm["admin"])
    adm_top = list(adm_counts.index[:TOP_ADMIN])
    adm_act = adm[adm["status"] == ACTIVE]["admin"].value_counts()
    admin_chart = {"names": adm_top,
                   "total": [int(adm_counts[a]) for a in adm_top],
                   "active": [int(adm_act.get(a, 0)) for a in adm_top]}
    admin_rows = [{"name": a, "total": _int(adm_counts[a]), "active": _int(adm_act.get(a, 0))} for a in adm_top]
    n_admin = int(adm_counts.size)

    # private owners
    priv = df[(df["ownership"] == PRIVATE) & (df["owner"] != "")]
    owner_counts = _sorted_counts(priv["owner"])
    owner_counts = owner_counts[owner_counts >= MIN_OWNER_WELLS]
    own_top = list(owner_counts.index[:TOP_OWNERS])
    own_act = priv[priv["status"] == ACTIVE]["owner"].value_counts()
    owners_chart = {"names": own_top,
                    "total": [int(owner_counts[o]) for o in own_top],
                    "active": [int(own_act.get(o, 0)) for o in own_top]}
    owners_rows = [{"name": o, "total": _int(owner_counts[o]), "active": _int(own_act.get(o, 0))} for o in own_top]
    n_owners = int(df.loc[df["owner"] != "", "owner"].nunique())

    # Mekorot by basin ("חברת מקורות אגן N תא M")
    mk = df[df["ownership"] == MEKOROT]
    basin = mk["owner"].str.extract(r"אגן\s*(\d+)")[0]
    bnum = pd.to_numeric(basin, errors="coerce")
    bdf = pd.DataFrame({"b": bnum, "act": mk["status"] == ACTIVE})
    bk = bdf.dropna(subset=["b"])
    basins = sorted(int(b) for b in bk["b"].unique())
    basin_chart = {"names": [f"אגן {b}" for b in basins],
                   "total": [int((bk["b"] == b).sum()) for b in basins],
                   "active": [int(((bk["b"] == b) & bk["act"]).sum()) for b in basins]}
    n_basin_other = int(bdf["b"].isna().sum())
    basin_rows = [{"name": n, "total": _int(t), "active": _int(a)}
                  for n, t, a in zip(basin_chart["names"], basin_chart["total"], basin_chart["active"])]

    # capacity
    flow = df["flow"].dropna()
    flow = flow[flow > 0]
    fdf = df[df["flow"] > 0]
    flow_labels, flow_act, flow_other = [], [], []
    for lo, hi in FLOW_BINS:
        sel = fdf[(fdf["flow"] >= lo) & ((fdf["flow"] < hi) if hi is not None else True)]
        flow_labels.append(f"{lo}-{hi}" if hi is not None else f"{lo}+")
        flow_act.append(int((sel["status"] == ACTIVE).sum()))
        flow_other.append(int((sel["status"] != ACTIVE).sum()))
    flow_chart = {"labels": flow_labels, "active": flow_act, "other": flow_other}
    flow_rows = [{"name": l, "active": _int(a), "other": _int(o), "total": _int(a + o)}
                 for l, a, o in zip(flow_labels, flow_act, flow_other)]
    has_flow = len(flow) >= 10

    # map: aggregate to 1 km grid cells
    cells_map = {}
    n_located = 0
    for code, st, ad in zip(df["national"], df["status"], df["admin"]):
        g = _grid_cell(code)
        if g is None:
            continue
        rec = cells_map.setdefault(g, [0, 0, {}])
        rec[0] += 1
        rec[1] += 1 if st == ACTIVE else 0
        if ad:
            rec[2][ad] = rec[2].get(ad, 0) + 1
    admin_names = []
    admin_idx = {}
    pts = []
    for g in sorted(cells_map):
        ll = _cell_latlon(*g)
        if ll is None:
            continue
        tot, act, ads = cells_map[g]
        n_located += tot
        if ads:
            top_ad = sorted(ads.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
            if top_ad not in admin_idx:
                admin_idx[top_ad] = len(admin_names)
                admin_names.append(top_ad)
            ai = admin_idx[top_ad]
        else:
            ai = -1
        pts.append([round(ll[0], 4), round(ll[1], 4), tot, act, ai])
    has_map = len(pts) >= 10
    map_chart = None
    if has_map:
        lats = [p[0] for p in pts]
        lons = [p[1] for p in pts]
        map_chart = {
            "chunks": [pts[i:i + MAP_CHUNK] for i in range(0, len(pts), MAP_CHUNK)],
            "admins": admin_names,
            "max": max(p[2] for p in pts),
            "bounds": [[min(lats), min(lons)], [max(lats), max(lons)]],
        }
    n_unlocated = total - n_located

    # KPIs
    active_share = n_active / total if total else 0
    inactive_share = n_inactive / total if total else 0
    kpis = {
        "total": {"value": total, "display": _int(total), "tone": "brand"},
        "active": {"value": n_active, "display": _int(n_active),
                   "tone": "ok" if active_share >= 0.5 else "warn"},
        "active_share": {"value": round(active_share * 100, 1), "display": _pct(active_share),
                         "tone": "ok" if active_share >= 0.5 else "warn"},
        "inactive": {"value": n_inactive, "display": _int(n_inactive),
                     "tone": "warn" if inactive_share >= 0.3 else "brand"},
        "owners": {"value": n_owners, "display": _int(n_owners), "tone": "brand"},
    }
    kpi_order = ["total", "active", "active_share", "inactive", "owners"]
    if has_flow:
        med = float(flow.median())
        kpis["flow_median"] = {"value": med, "display": f"{med:,.0f}", "tone": "info"}
        kpi_order.append("flow_median")

    mk_n = int(own_counts.get(MEKOROT, 0))
    pr_n = int(own_counts.get(PRIVATE, 0))

    rules = [
        ("active", insight_active(total, status_counts)),
        ("owner_gap", insight_owner_gap(df)),
        ("aquifer", insight_aquifer(aq_counts, n_aq_missing)),
        ("brackish", insight_brackish(df)),
        ("dewater", insight_dewater(df)),
        ("region", insight_region(reg_counts, total)),
        ("admin", insight_admin(adm_counts, total)),
        ("owner_top", insight_owner_top(owner_counts)),
        ("flow", insight_flow(flow, total)),
        ("national", insight_national(df)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    top_aq = aq_counts.index[0] if len(aq_counts) else ""
    top_reg = reg_chart["cats"][0] if reg_chart["cats"] else ""
    top_adm = adm_top[0] if adm_top else ""
    top_own = own_top[0] if own_top else ""
    top_wt = wts[0] if wts else ""

    labels = {
        "lede": (f"המאגר מונה {_int(total)} קידוחי מים שרשות המים מנהלת, מעניקה להם רישיון ומפקחת על ההפקה מהם: "
                 f"{_int(mk_n)} של חברת מקורות ו-{_int(pr_n)} של צרכנים פרטיים (קיבוצים, מושבים, תאגידי מים, "
                 f"אגודות מים וחברות). {_int(n_active)} מהם ({_pct(active_share)}) פעילים."),
        "kpi_total": "קידוחים במאגר",
        "kpi_active": "קידוחים פעילים",
        "kpi_active_share": "שיעור הקידוחים הפעילים",
        "kpi_inactive": "קידוחים לא פעילים, סגורים או בבקשה",
        "kpi_owners": "בעלי קידוחים שונים",
        "kpi_flow_median": f"ספיקה שעתית מקסימלית חציונית, מ״ק לשעה ({_int(len(flow))} קידוחים עם נתון)",
        "status_lede": (f"{_int(n_active)} קידוחים פעילים ({_pct(active_share)}) ו-{_int(n_inactive)} בסטטוס אחר: "
                        f"לא פעיל, לא פעיל לצמיתות, רישיון סתימה (אישור לאטום את הקידוח) או בקשה."),
        "status_aria": (f"תרשים עמודות: קידוחים לפי סטטוס. {statuses[0] if statuses else ''}: "
                        f"{_int(status_counts.iloc[0]) if len(status_counts) else 0} קידוחים."),
        "own_lede": (f"מקורות מחזיקה {_int(mk_n)} קידוחים וצרכנים פרטיים {_int(pr_n)}. "
                     f"שיעור הקידוחים הפעילים: " + ", ".join(
                         f"{c} {r['share']}" for c, r in zip(owns, own_rows))) + ".",
        "own_aria": "תרשים עמודות מוערמות: קידוחים לפי סוג בעלות ולפי סטטוס. " + ", ".join(
            f"{c}: {r['total']} קידוחים, {r['active']} פעילים" for c, r in zip(owns, own_rows)) + ".",
        "water_lede": (f"סוג המים נגזר משדה קבוצת המים של כל קידוח ({_int(int(df['group'].nunique()))} קבוצות שונות). "
                       f"הנפוץ: {top_wt}, {water_rows[0]['total'] if water_rows else '0'} קידוחים. "
                       f"{_int(n_dewater)} קידוחים רשומים בקבוצות של סילוק (הרחקת מי תהום)."),
        "water_aria": "תרשים עמודות מוערמות: קידוחים לפי סוג המים ולפי סטטוס. " + ", ".join(
            f"{c}: {r['total']}" for c, r in zip(wts, water_rows)) + ".",
        "aq_lede": (f"{_int(len(aq_counts))} אקוויפרים (שכבות מי תהום) מופיעים במאגר. {top_aq} מוביל עם "
                    f"{_int(aq_counts.iloc[0]) if len(aq_counts) else 0} קידוחים."
                    + (f" ל-{_int(n_aq_missing)} קידוחים לא צוין אקוויפר, והם מוצגים בשורה נפרדת." if n_aq_missing else "")),
        "aq_aria": (f"תרשים עמודות מוערמות: קידוחים לפי אקוויפר ולפי סטטוס. {top_aq}: "
                    f"{_int(aq_counts.iloc[0]) if len(aq_counts) else 0} קידוחים."),
        "reg_lede": (f"פריסת הקידוחים לפי האזור החקלאי של רשות המים. {top_reg} מוביל עם "
                     f"{reg_rows[0]['total'] if reg_rows else '0'} קידוחים."
                     + (f" ל-{_int(int(reg_counts.get(UNSPEC, 0)))} קידוחים לא צוין אזור." if UNSPEC in reg_counts.index else "")),
        "reg_aria": (f"תרשים עמודות מוערמות: קידוחים לפי אזור חקלאי ולפי סטטוס. {top_reg}: "
                     f"{reg_rows[0]['total'] if reg_rows else '0'} קידוחים."),
        "heat_lede": (f"מפת חום של מספר הקידוחים בכל צירוף של אזור ואקוויפר ({_int(len(hd))} קידוחים שבהם "
                      f"צוינו גם אזור וגם אקוויפר). האקוויפרים והאזורים הקטנים מקובצים תחת שאר הקטגוריות."),
        "heat_aria": (f"מפת חום: מספר הקידוחים לפי אזור חקלאי ואקוויפר. התא הגדול ביותר מונה "
                      f"{_int(hmax)} קידוחים."),
        "admin_lede": (f"הקידוחים פרוסים ב-{_int(n_admin)} רשויות מקומיות ושטחים. {top_adm} מובילה עם "
                       f"{admin_rows[0]['total'] if admin_rows else '0'} קידוחים. מוצגות "
                       f"{_int(len(adm_top))} הרשויות עם המספר הגדול ביותר."),
        "admin_aria": (f"תרשים עמודות: {_int(len(adm_top))} הרשויות עם מספר הקידוחים הגדול ביותר. {top_adm}: "
                       f"{admin_rows[0]['total'] if admin_rows else '0'} קידוחים."),
        "owners_lede": (f"בעלי הקידוחים הפרטיים הגדולים (בעלי {_int(MIN_OWNER_WELLS)} קידוחים לפחות): תאגידי מים עירוניים, "
                        f"אגודות מים, קיבוצים ותעשייה. {top_own} מוביל עם "
                        f"{owners_rows[0]['total'] if owners_rows else '0'} קידוחים."),
        "owners_aria": (f"תרשים עמודות: בעלי הקידוחים הפרטיים הגדולים. {top_own}: "
                        f"{owners_rows[0]['total'] if owners_rows else '0'} קידוחים."),
        "basin_lede": (f"קידוחי מקורות רשומים לפי אגן תפעולי. "
                       + (f"אגן עם המספר הגדול ביותר: {basin_chart['names'][basin_chart['total'].index(max(basin_chart['total']))]}, "
                          f"{_int(max(basin_chart['total']))} קידוחים." if basins else "")
                       + (f" {_int(n_basin_other)} קידוחים ללא אגן בשם הצרכן אינם מוצגים." if n_basin_other else "")),
        "basin_aria": "תרשים עמודות: קידוחי מקורות לפי אגן. " + ", ".join(
            f"{n}: {t}" for n, t in zip(basin_chart["names"], basin_chart["total"])) + ".",
        "flow_lede": (f"התפלגות הספיקה השעתית המקסימלית במ״ק לשעה. הנתון מולא ל-{_int(len(flow))} קידוחים בלבד "
                      f"({_pct(len(flow) / total) if total else '0.0%'} מהמאגר), כמעט כולם של צרכנים פרטיים; "
                      f"קידוחים ללא נתון אינם מוצגים."),
        "flow_aria": (f"תרשים עמודות מוערמות: קידוחים לפי טווח ספיקה שעתית מקסימלית. "
                      f"{_int(len(flow))} קידוחים עם נתון, חציון "
                      f"{(f'{float(flow.median()):,.0f}' if len(flow) else '0')} מ״ק לשעה."),
        "map_lede": (f"כל עיגול הוא ריבוע של קילומטר על קילומטר, לפי המיקום המקודד במספר הארצי של הקידוח "
                     f"(רשת ישראל הישנה). גודל העיגול לפי מספר הקידוחים בריבוע; כחול: יש בו קידוח פעיל, אפור: אין. "
                     f"המיקום מקורב לרמת קילומטר. {_int(n_located)} קידוחים ממוקמים על המפה"
                     + (f"; ל-{_int(n_unlocated)} אין מספר ארצי שניתן לפענח." if n_unlocated else ".")),
        "map_aria": (f"מפה אינטראקטיבית של {_int(n_located)} קידוחי רשות המים, מקובצים לריבועי קילומטר. "
                     f"גרסה נגישה: ראו את טבלת הנתונים בתחתית העמוד."),
    }

    summary = (f"איתור קידוחי מים של רשות המים לפי שם, בעלים, אקוויפר או רשות: "
               f"{_int(total)} קידוחים, {_int(n_active)} פעילים, {_int(mk_n)} של מקורות.")
    if len(summary) > 155:
        summary = f"איתור קידוחי מים של רשות המים: {_int(total)} קידוחים, {_int(n_active)} פעילים."

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "registry",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "kpi_order": kpi_order,
        "charts": {
            "status": status_chart,
            "ownership": own_chart,
            "water": water_chart,
            "aquifer": aq_chart,
            "region": reg_chart,
            "heat": heat_chart,
            "admin": admin_chart,
            "owners": owners_chart,
            "basin": basin_chart,
            "flow": flow_chart,
            "map": map_chart,
        },
        "tables": {
            "status": status_rows,
            "ownership": own_rows,
            "water": water_rows,
            "aquifer": aq_rows,
            "region": reg_rows,
            "admin": admin_rows,
            "owners": owners_rows,
            "basin": basin_rows,
            "flow": flow_rows,
        },
        "flags": {
            "map": has_map,
            "flow": has_flow,
            "owners": len(own_top) >= 3,
            "basin": len(basins) >= 2,
            "heat": len(cells) >= 4,
        },
        "insights": insights,
        "labels": labels,
    }
