"""רשימת פריטים ליבוא מסחרי שאישורם בתוקף לצורך הגשת אישור על סמך אישור:
the Ministry of Communications' list of wireless items whose type approval is
still valid, so a commercial importer of the same model can file an
"approval based on an existing approval". One row per approval: approval
number, validity date, model code, manufacturer.

The page is a lookup page first (does my model appear, under which approval
number, until when), then what the list says about itself: when the valid
approvals expire, which manufacturers dominate, how long the tail of
one-approval manufacturers is, which models were approved more than once,
and how much of the list is toy factories (remote-control toys).

Manufacturer names are free text with many spellings of one company
("VISONIC LTD" / "Visonic Ltd"), so they are grouped by a normalized key
(case, punctuation and legal suffixes like Ltd/Inc/GmbH removed); the label
is the group's most common spelling. Disclosed on the page.

Growth: the resource is replaced in place with the current valid list. All
category axes are top-N; the expiry axis switches from months to quarters
once the span passes MONTHS_MAX months, and the fallback table follows.
No clock: "earliest" and "latest" mean in the data.
"""
import re

import pandas as pd

TOP_MAKERS = 15
TOP_MODELS = 12
HEAT_MAKERS = 10
MONTHS_MAX = 30
TABLE_MAX = 24
SUMMARY_MAX = 155
TOY_MIN_SHARE = 0.03
PARETO_POINTS = 200

C_NUM = "מספר אישור"
C_VALID = "תוקף"
C_MODEL = "קוד דגם"
C_MAKER = "יצרן"

HE_MONTHS = ["ינו׳", "פבר׳", "מרץ", "אפר׳", "מאי", "יוני",
             "יולי", "אוג׳", "ספט׳", "אוק׳", "נוב׳", "דצמ׳"]
HE_MONTHS_FULL = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני",
                  "יולי", "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]

NONE_LABEL = "לא צוין"

# Legal-form words stripped from the end of a manufacturer name (repeatedly).
SUFFIXES = {
    "CO", "COMPANY", "LTD", "LIMITED", "INC", "INCORPORATED", "CORP",
    "CORPORATION", "GMBH", "LLC", "PLC", "SA", "AG", "AB", "BV", "NV", "SRL",
    "SPA", "PTE", "KG", "OY", "AS", "SAS", "SL", "KK", "PTY", "THE",
}

BUCKETS = [(1, 1, "אישור אחד"), (2, 4, "2-4 אישורים"), (5, 9, "5-9 אישורים"),
           (10, 19, "10-19 אישורים"), (20, None, "20 אישורים ומעלה")]


def _clean(s):
    return re.sub(r"\s+", " ", str(s)).strip()


def _maker_key(name):
    s = _clean(name).upper()
    s = re.sub(r"[^\w]+", " ", s)
    s = s.replace("_", " ")
    words = s.split()
    while len(words) > 1 and words[-1] in SUFFIXES:
        words.pop()
    return " ".join(words)


def _model_key(code):
    return re.sub(r"\s+", "", _clean(code).upper())


def _pct(part, whole, digits=1):
    if not whole:
        return "0%"
    v = part / whole * 100
    floor = 10 ** -digits
    if 0 < v < floor:  # never round a non-zero count down to zero
        return f"<{floor:g}%"
    return f"{v:.{digits}f}%"


def _date(ts):
    return f"{ts.day:02d}.{ts.month:02d}.{ts.year}"


def _month_label(p):
    return f"{HE_MONTHS[p.month - 1]} {p.year}"


def _month_full(p):
    return f"{HE_MONTHS_FULL[p.month - 1]} {p.year}"


def _quarter_label(p):
    return f"רבעון {p.quarter} {p.year}"


def _display_names(df, key_col, raw_col):
    """key -> most common raw spelling (ties: alphabetical)."""
    g = (df.groupby([key_col, raw_col]).size().reset_index(name="n")
         .sort_values([key_col, "n", raw_col], ascending=[True, False, True], kind="mergesort"))
    return dict(zip(*g.drop_duplicates(key_col)[[key_col, raw_col]].T.values))


def compute(frames):
    df = frames["items"].copy()
    for c in (C_NUM, C_VALID, C_MODEL, C_MAKER):
        df[c] = df[c].map(_clean)
    df = df[(df[C_NUM] != "") | (df[C_MODEL] != "")].copy()
    total = int(len(df))
    if total == 0:
        raise ValueError("no approvals in the list")

    df["maker_raw"] = df[C_MAKER].where(df[C_MAKER] != "", NONE_LABEL)
    df["mk"] = df["maker_raw"].map(_maker_key)
    df.loc[df["maker_raw"] == NONE_LABEL, "mk"] = "\u0000none"
    names = _display_names(df, "mk", "maker_raw")
    df["maker"] = df["mk"].map(names)
    df["model_k"] = df[C_MODEL].map(_model_key)
    df["valid"] = pd.to_datetime(df[C_VALID].str[:10], format="%Y-%m-%d", errors="coerce")

    n_makers = int(df["mk"].nunique())
    n_raw_makers = int(df["maker_raw"].nunique())
    n_models = int(df.loc[df["model_k"] != "", "model_k"].nunique())

    # ── manufacturers ────────────────────────────────────────────────
    mc = (df.groupby("mk").size().reset_index(name="n")
          .assign(name=lambda x: x["mk"].map(names))
          .sort_values(["n", "name", "mk"], ascending=[False, True, True], kind="mergesort")
          .reset_index(drop=True))
    top = mc.head(TOP_MAKERS)
    makers_rows = [{"name": r.name, "n": int(r.n), "pct": _pct(int(r.n), total)}
                   for r in top.itertuples()]
    makers_chart = {"names": [r["name"] for r in makers_rows],
                    "values": [r["n"] for r in makers_rows]}

    # Pareto: cumulative share by manufacturer rank
    cum = mc["n"].cumsum().tolist()
    nm = len(cum)
    if nm <= PARETO_POINTS:
        ranks = list(range(1, nm + 1))
    else:
        head = list(range(1, 51))
        step = max(1, (nm - 50) // (PARETO_POINTS - 50))
        ranks = sorted(set(head + list(range(51, nm + 1, step)) + [nm]))
    pareto = {"x": ranks, "y": [round(cum[r - 1] / total * 100, 1) for r in ranks], "n": nm}
    milestones = []
    for r in (1, 5, 10, 20, 50, 100):
        if r < nm:
            milestones.append({"name": f"{r:,} היצרנים המובילים" if r > 1 else "היצרן המוביל",
                               "n": int(cum[r - 1]), "pct": _pct(cum[r - 1], total)})
    milestones.append({"name": f"כל {nm:,} היצרנים", "n": total, "pct": "100.0%"})

    # Size buckets
    bucket_rows = []
    for lo, hi, label in BUCKETS:
        m = (mc["n"] >= lo) & ((mc["n"] <= hi) if hi is not None else True)
        bucket_rows.append({"name": label, "makers": int(m.sum()),
                            "n": int(mc.loc[m, "n"].sum()),
                            "pct": _pct(int(mc.loc[m, "n"].sum()), total)})
    buckets_chart = {"names": [b["name"] for b in bucket_rows],
                     "makers": [b["makers"] for b in bucket_rows],
                     "approvals": [b["n"] for b in bucket_rows]}
    singles = bucket_rows[0]["makers"]

    # ── repeated models (same model + same manufacturer) ────────────
    dm = df[df["model_k"] != ""]
    model_names = _display_names(dm.assign(_k=dm["mk"] + "\u0001" + dm["model_k"]), "_k", C_MODEL)
    mg = (dm.assign(_k=dm["mk"] + "\u0001" + dm["model_k"]).groupby(["_k", "mk"]).size()
          .reset_index(name="n"))
    mg["model"] = mg["_k"].map(model_names)
    mg["maker"] = mg["mk"].map(names)
    rep = mg[mg["n"] >= 2].sort_values(["n", "model", "maker", "_k"],
                                       ascending=[False, True, True, True], kind="mergesort")
    n_rep_models = int(len(rep))
    n_rep_approvals = int(rep["n"].sum())
    rep_top = rep.head(TOP_MODELS)
    models_rows = [{"name": f"{r.model} ({r.maker})", "model": r.model, "maker": r.maker,
                    "n": int(r.n)} for r in rep_top.itertuples()]
    models_chart = {"names": [r["name"] for r in models_rows],
                    "values": [r["n"] for r in models_rows]}
    has_models = n_rep_models >= 3

    # ── expiry timeline ──────────────────────────────────────────────
    dv = df[df["valid"].notna()].copy()
    n_valid = int(len(dv))
    n_bad_date = total - n_valid
    has_expiry = n_valid > 0
    expiry_chart = {"x": [], "y": []}
    expiry_rows = []
    gran = "month"
    first_ts = last_ts = None
    peak = None
    year_rows = []
    if has_expiry:
        first_ts, last_ts = dv["valid"].min(), dv["valid"].max()
        dv["m"] = dv["valid"].dt.to_period("M")
        span = (last_ts.year - first_ts.year) * 12 + last_ts.month - first_ts.month + 1
        if span > MONTHS_MAX:
            gran = "quarter"
            dv["p"] = dv["valid"].dt.to_period("Q")
            lab = _quarter_label
        else:
            dv["p"] = dv["m"]
            lab = _month_label
        cnt = dv.groupby("p").size()
        rng = pd.period_range(cnt.index.min(), cnt.index.max(), freq=cnt.index.min().freq)
        cnt = cnt.reindex(rng, fill_value=0)
        expiry_chart = {"x": [lab(p) for p in cnt.index], "y": [int(v) for v in cnt.values]}
        expiry_rows = [{"name": lab(p), "n": int(v), "pct": _pct(int(v), n_valid)}
                       for p, v in zip(cnt.index, cnt.values)]
        # peak (ties: earliest)
        mcnt = dv.groupby("m").size()
        pmax = int(mcnt.max())
        pm = sorted(p for p, v in mcnt.items() if int(v) == pmax)[0]
        peak = (pm, pmax)
        yc = dv.groupby(dv["valid"].dt.year).size().sort_index()
        year_rows = [{"year": int(y), "n": int(v)} for y, v in yc.items()]
    expiry_table_ok = len(expiry_rows) <= TABLE_MAX

    # ── heatmap: top manufacturers × expiry quarter ─────────────────
    heat = None
    if has_expiry and n_makers >= 3:
        hm = mc.head(HEAT_MAKERS)
        dq = dv[dv["mk"].isin(set(hm["mk"]))].copy()
        dq["q"] = dq["valid"].dt.to_period("Q")
        qs = pd.period_range(dv["valid"].dt.to_period("Q").min(),
                             dv["valid"].dt.to_period("Q").max(), freq="Q")
        cnt = dq.groupby(["mk", "q"]).size()
        cells = []
        for yi, mk in enumerate(hm["mk"]):
            for xi, q in enumerate(qs):
                v = int(cnt.get((mk, q), 0))
                cells.append([xi, yi, v])
        heat = {"x": [_quarter_label(q) for q in qs], "y": [names[k] for k in hm["mk"]],
                "cells": cells, "max": max([c[2] for c in cells] + [1])}

    # ── toys ─────────────────────────────────────────────────────────
    toy_mask = df["mk"].str.contains(r"\bTOYS?\b", regex=True)
    n_toy = int(toy_mask.sum())
    n_toy_makers = int(df.loc[toy_mask, "mk"].nunique())
    toy_share = n_toy / total

    # ── KPIs ─────────────────────────────────────────────────────────
    kpis = {
        "total": {"value": total, "display": f"{total:,}", "tone": "brand"},
        "makers": {"value": n_makers, "display": f"{n_makers:,}", "tone": "brand"},
        "models": {"value": n_models, "display": f"{n_models:,}", "tone": "brand"},
    }
    if has_expiry:
        kpis["first"] = {"value": _date(first_ts), "display": _date(first_ts), "tone": "warn"}
        kpis["last"] = {"value": _date(last_ts), "display": _date(last_ts), "tone": "info"}

    # ── insights ─────────────────────────────────────────────────────
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    def i_leader():
        if len(mc) < 2:
            return None
        a, b = mc.iloc[0], mc.iloc[1]
        if int(a["n"]) <= int(b["n"]):
            return None
        return (f"היצרן עם מספר האישורים הגדול ביותר ברשימה הוא {a['name']}, "
                f"עם {int(a['n']):,} אישורים ({_pct(int(a['n']), total)}), "
                f"ואחריו {b['name']} עם {int(b['n']):,}.")

    def i_concentration():
        if nm < 20:
            return None
        top10 = cum[9] / total
        if top10 < 0.3:
            head = f"הרשימה מפוזרת: עשרת היצרנים המובילים מחזיקים רק {_pct(cum[9], total)} מהאישורים"
        elif top10 > 0.5:
            head = f"הרשימה מרוכזת: עשרת היצרנים המובילים מחזיקים {_pct(cum[9], total)} מהאישורים"
        else:
            head = f"עשרת היצרנים המובילים מחזיקים {_pct(cum[9], total)} מהאישורים"
        return (f"{head}, "
                f"ו-{singles:,} יצרנים ({_pct(singles, nm)} מהיצרנים) מופיעים באישור אחד בלבד.")

    def i_toys():
        if toy_share < TOY_MIN_SHARE or n_toy_makers < 2:
            return None
        return (f"{n_toy:,} אישורים ({_pct(n_toy, total)}) שייכים ל-{n_toy_makers:,} יצרנים "
                f"שבשמם מופיעה המילה TOY או TOYS, כלומר מפעלי צעצועים.")

    def i_models():
        if n_rep_models < 3 or not models_rows:
            return None
        t = models_rows[0]
        return (f"{n_rep_models:,} דגמים מופיעים ביותר מאישור אחד אצל אותו יצרן "
                f"(יחד {n_rep_approvals:,} אישורים). הבולט הוא {t['model']} של {t['maker']}, "
                f"עם {t['n']:,} אישורים.")

    def i_peak():
        if not peak or n_valid < 50:
            return None
        pm, pv = peak
        return (f"החודש שבו פוקעים הכי הרבה אישורים הוא {_month_full(pm)}: "
                f"{pv:,} אישורים ({_pct(pv, n_valid)} מהאישורים שתאריך התוקף שלהם ידוע).")

    def i_first_year():
        if len(year_rows) < 2:
            return None
        y0 = year_rows[0]
        yl = year_rows[-1]
        if y0["n"] / n_valid >= 0.1 or yl["n"] / n_valid <= 0.5:
            return None
        return (f"רק {y0['n']:,} אישורים פוקעים כבר בשנת {y0['year']}, הראשון שבהם ב-{_date(first_ts)}. "
                f"רוב האישורים ({_pct(yl['n'], n_valid)}) פוקעים רק בשנת {yl['year']}.")

    add("leader", i_leader())
    add("concentration", i_concentration())
    add("toys", i_toys())
    add("models", i_models())
    add("peak", i_peak())
    add("first_year", i_first_year())

    # ── summary / labels ─────────────────────────────────────────────
    summary = (f"בדיקה אם דגם ציוד אלחוטי מאושר ליבוא מסחרי במסלול אישור על סמך אישור, "
               f"לפי קוד דגם, יצרן או מספר אישור: {total:,} אישורים בתוקף של {n_makers:,} יצרנים.")
    if len(summary) > SUMMARY_MAX:
        summary = (f"בדיקת דגם ציוד אלחוטי מאושר ליבוא מסחרי (אישור על סמך אישור) לפי דגם, "
                   f"יצרן או מספר אישור: {total:,} אישורים בתוקף.")

    first_s = _date(first_ts) if has_expiry else ""
    last_s = _date(last_ts) if has_expiry else ""
    gran_he = "חודש" if gran == "month" else "רבעון"
    top1 = makers_rows[0] if makers_rows else None

    labels = {
        "kpi_total": "אישורים בתוקף ברשימה",
        "kpi_makers": "יצרנים (אחרי איחוד איותים)",
        "kpi_models": "קודי דגם שונים",
        "kpi_first": "תאריך התוקף המוקדם ביותר",
        "kpi_last": "תאריך התוקף המאוחר ביותר",
        "expiry_lede": (
            f"מספר האישורים לפי {gran_he} פקיעת התוקף, מ-{first_s} עד {last_s}. "
            + (f"השיא ב{_month_full(peak[0])}, עם {peak[1]:,} אישורים. " if peak else "")
            + (f"{n_bad_date:,} אישורים ללא תאריך תוקף תקין לא נכללו." if n_bad_date else "")
        ).strip() if has_expiry else "",
        "expiry_aria": (f"גרף עמודות: אישורים לפי {gran_he} פקיעת התוקף, {first_s} עד {last_s}"
                        + (f". השיא ב{_month_full(peak[0])} עם {peak[1]:,} אישורים." if peak else "."))
                       if has_expiry else "",
        "expiry_col": gran_he,
        "makers_lede": (
            f"{TOP_MAKERS} היצרנים עם מספר האישורים הגדול ביותר. שמות היצרנים ברשימה נכתבו בכמה איותים, "
            f"ולכן אוחדו לפי שם (בלי הבדלי אותיות גדולות וקטנות, סימני פיסוק וסיומות כמו Ltd, Inc או GmbH): "
            f"{n_raw_makers:,} איותים שונים הפכו ל-{n_makers:,} יצרנים."),
        "makers_aria": (f"גרף עמודות אופקי: {len(makers_rows)} היצרנים עם הכי הרבה אישורים בתוקף. "
                        f"מוביל: {top1['name']} עם {top1['n']:,} אישורים.") if top1 else "",
        "pareto_lede": (
            f"כמה מהאישורים מרוכזים אצל היצרנים הגדולים: הקו מראה את השיעור המצטבר של האישורים "
            f"ככל שמוסיפים יצרנים לפי סדר גודלם. עשרת הראשונים מחזיקים {_pct(cum[min(9, nm - 1)], total)}."),
        "pareto_aria": (f"גרף קו: שיעור מצטבר של אישורים לפי דירוג {nm:,} היצרנים. "
                        f"עשרת היצרנים המובילים מחזיקים {_pct(cum[min(9, nm - 1)], total)} מהאישורים."),
        "buckets_lede": (
            (f"רוב היצרנים ברשימה קטנים: " if singles * 2 > nm else "")
            + f"{singles:,} מתוך {nm:,} יצרנים מופיעים באישור אחד בלבד, "
            f"ויחד הם מחזיקים {bucket_rows[0]['pct']} מהאישורים."),
        "buckets_aria": (f"גרף עמודות: יצרנים ואישורים לפי גודל היצרן. {singles:,} יצרנים "
                         f"עם אישור אחד בלבד."),
        "models_lede": (
            f"{n_rep_models:,} דגמים (אותו קוד דגם אצל אותו יצרן) מופיעים ביותר מאישור אחד, "
            f"כל אחד מהם רשום תחת כמה מספרי אישור. אלה {len(models_rows)} הדגמים שחוזרים הכי הרבה פעמים."),
        "models_aria": (f"גרף עמודות אופקי: דגמים עם יותר מאישור אחד. "
                        f"מוביל: {models_rows[0]['name']} עם {models_rows[0]['n']:,} אישורים.")
                       if models_rows else "",
        "heat_lede": (
            f"מתי פוקעים האישורים של {HEAT_MAKERS} היצרנים הגדולים, לפי רבעון. "
            f"צבע כהה יותר הוא יותר אישורים שפוקעים באותו רבעון."),
        "heat_aria": (f"מפת חום: אישורים של {HEAT_MAKERS} היצרנים המובילים לפי רבעון פקיעת התוקף, "
                      f"עד {heat['max']:,} אישורים בתא.") if heat else "",
    }

    temporal = f"{first_ts.year}/{last_ts.year}" if has_expiry else None
    agent_data = {"summary_he": summary, "dataset_kind": "registry"}
    if temporal:
        agent_data["temporal_coverage"] = temporal

    return {
        "agent_data": agent_data,
        "kpis": kpis,
        "charts": {
            "expiry": expiry_chart,
            "makers": makers_chart,
            "pareto": pareto,
            "buckets": buckets_chart,
            "models": models_chart,
            "heat": heat,
        },
        "insights": insights,
        "tables": {
            "expiry": expiry_rows if expiry_table_ok else [],
            "makers": makers_rows,
            "milestones": milestones,
            "buckets": bucket_rows,
            "models": models_rows,
        },
        "labels": labels,
        "flags": {
            "has_expiry": has_expiry,
            "expiry_table": has_expiry and expiry_table_ok,
            "has_models": has_models,
            "has_heat": heat is not None,
            "has_pareto": nm >= 20,
        },
    }
