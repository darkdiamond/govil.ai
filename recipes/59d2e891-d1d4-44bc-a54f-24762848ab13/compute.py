"""Israel Dialing Plan, within Israel: the Ministry of Communications' list of
national service numbers (emergency short numbers, other short numbers,
service dialing areas such as 1599/1700/1800/1900, international dialing
prefixes and star/hash network codes), each with the licensed provider it is
allocated to.

One small table (~330 rows). Searchers come with a lookup question ("של מי
קידומת 1801", "מה זה 1599", "מספר חירום 118"), so the page leads with the
explorer callout and with lookup tables, then the allocation picture:
which service dialing area is split between how many providers, who holds
how much of each range (capacity from the X-pattern of the block), and which
numbers are flagged for cancellation.

Growth: the ministry edits rows in place. New types, codes and providers
flow through (no hardcoded lists beyond keyword matches on the type and the
notes, each with a neutral fallback); provider axes are capped top-N.
"""
import re
from collections import Counter

import pandas as pd

C_TYPE = "סוג"
C_NET = "רשתי"
C_DIGITS = "מספר ספרות לאחר הקידומת"
C_CODE = "קידומת חיוג (קוד גישה)"
C_PROV = "מוקצה לספק מורשה במשרד התקשורת"
C_NOTE = "הערות"

UNTYPED = "ללא סיווג"
OTHER = "אחר"
TOP_PROVIDERS = 14
HEAT_PROVIDERS = 22
CAP_TOP = 3
SUMMARY_MAX = 155
LEAD_SHARE = 0.5

STATUS_CANCEL = "מתוכנן לביטול או לא בשימוש"
STATUS_FUTURE = "עתידי"
STATUS_ACTIVE = "פעיל"
_CANCEL_RE = re.compile(r"יבוטל|לא בשימוש|בוטל")
_FUTURE_RE = re.compile(r"עתידי")
_PATTERN_RE = re.compile(r"^([0-9]*)(X+)$")
_SUFFIX_RE = re.compile(r'\s*(?:בע"מ|ש\.מ\.|בע״מ)\s*$')


def _clean(s):
    return re.sub(r"\s+", " ", str(s)).strip()


def _short(name):
    s = name
    for _ in range(2):
        s = _SUFFIX_RE.sub("", s).strip()
    return s or name


def _code_key(code):
    """Sort key: plain digit codes numerically by length then value; others after."""
    kind = 0 if code[:1].isdigit() else 1
    return (kind, len(code), code)


def _is_service_area(t):
    return "חיוג לשירות" in t


def _is_emergency(t):
    return "חירום" in t


def _is_intl(t):
    return "בינלאומית" in t and "קידומת" in t


def _status(note):
    if _CANCEL_RE.search(note):
        return STATUS_CANCEL
    if _FUTURE_RE.search(note):
        return STATUS_FUTURE
    return STATUS_ACTIVE


def _mode(values):
    vals = [v for v in values if v]
    if not vals:
        return ""
    c = Counter(vals)
    best = max(c.values())
    return sorted([v for v, n in c.items() if n == best], key=lambda v: (len(v), v))[0]


def _fmt_int(n):
    return f"{int(n):,}"


def _pct(x):
    return f"{x * 100:.0f}%"


def _prepare(df):
    out = pd.DataFrame({
        "type": df[C_TYPE].map(_clean),
        "net": df[C_NET].map(_clean),
        "digits": df[C_DIGITS].map(_clean).str.upper(),
        "code": df[C_CODE].map(_clean),
        "prov": df[C_PROV].map(_clean),
        "note": df[C_NOTE].map(_clean),
    })
    out = out[out["code"] != ""].copy()
    out["type"] = out["type"].where(out["type"] != "", UNTYPED)
    out["status"] = out["note"].map(_status)
    out["is_net"] = out["net"] == "כן"
    out["_k"] = out["code"].map(lambda c: "{}|{:03d}|{}".format(*_code_key(c)))
    out = out.sort_values(["_k", "digits", "prov", "type", "note", "net"],
                          kind="stable").reset_index(drop=True)
    return out


# ------------------------------------------------------------ capacity

def _capacity(rows):
    """Per service code: provider blocks with a digits+X pattern -> capacity.

    Returns None when the patterned rows don't share one width (no common
    number space to compare). Blocks nested inside a wider block of the same
    code are not double counted.
    """
    pats = []
    for _, r in rows.iterrows():
        m = _PATTERN_RE.match(r["digits"])
        if not m or not r["prov"]:
            continue
        pats.append((m.group(1), len(r["digits"]), r["prov"]))
    if not pats:
        return None
    widths = {w for _, w, _ in pats}
    if len(widths) != 1:
        return None
    width = widths.pop()
    if any(fixed == "" for fixed, _, _ in pats):
        return None
    pats = sorted(set(pats), key=lambda p: (len(p[0]), p[0], p[2]))
    kept = []
    for fixed, w, prov in pats:
        if any(fixed.startswith(k[0]) for k in kept):
            continue
        kept.append((fixed, w, prov))
    space = 10 ** width
    by_prov = Counter()
    for fixed, w, prov in kept:
        by_prov[prov] += 10 ** (w - len(fixed))
    return {"space": space, "width": width, "by_prov": by_prov,
            "allocated": sum(by_prov.values())}


# ------------------------------------------------------------ compute

def compute(frames):
    df = _prepare(frames["main"])
    n_rows = int(len(df))

    alloc = df[df["prov"] != ""]
    providers = sorted(alloc["prov"].unique())
    n_prov = len(providers)

    # ---- by type
    type_counts = df.groupby("type").size()
    type_order = sorted(type_counts.index, key=lambda t: (-int(type_counts[t]), t))
    type_alloc = alloc.groupby("type").size()
    types_tbl = [{
        "name": t,
        "rows": _fmt_int(type_counts[t]),
        "alloc": _fmt_int(type_alloc.get(t, 0)),
        "codes": _fmt_int(df[df["type"] == t]["code"].nunique()),
    } for t in type_order]
    chart_types = {
        "names": type_order,
        "alloc": [int(type_alloc.get(t, 0)) for t in type_order],
        "general": [int(type_counts[t] - type_alloc.get(t, 0)) for t in type_order],
    }

    # ---- service dialing areas, per access code
    sa = df[df["type"].map(_is_service_area)]
    codes = []
    for code, g in sa.groupby("code"):
        blocks = g[g["prov"] != ""]
        codes.append({
            "code": code,
            "purpose": _mode(list(g["note"])),
            "blocks": int(len(blocks)),
            "providers": int(blocks["prov"].nunique()),
            "general": bool((g["prov"] == "").any()),
            "cap": _capacity(g),
        })
    codes.sort(key=lambda c: _code_key(c["code"]))
    chart_codes = {
        "codes": [c["code"] for c in codes],
        "purpose": [c["purpose"] for c in codes],
        "blocks": [c["blocks"] for c in codes],
        "providers": [c["providers"] for c in codes],
    }
    codes_tbl = [{
        "code": c["code"], "purpose": c["purpose"] or "–",
        "blocks": _fmt_int(c["blocks"]), "providers": _fmt_int(c["providers"]),
    } for c in codes]

    # ---- capacity share per code (only codes with >=2 providers and a common width)
    cap_codes = [c for c in codes if c["cap"] and c["providers"] >= 2]
    cap_rows, cap_tbl = [], []
    for c in cap_codes:
        cap = c["cap"]
        ranked = sorted(cap["by_prov"].items(), key=lambda kv: (-kv[1], kv[0]))
        top = ranked[:CAP_TOP]
        rest = sum(v for _, v in ranked[CAP_TOP:])
        free = max(cap["space"] - cap["allocated"], 0)
        segs = [{"name": _short(p), "full": p, "value": round(v / cap["space"] * 100, 2),
                 "count": int(v)} for p, v in top]
        if rest:
            segs.append({"name": "ספקים אחרים", "full": f"{len(ranked) - CAP_TOP:,} ספקים אחרים",
                         "value": round(rest / cap["space"] * 100, 2), "count": int(rest)})
        cap_rows.append({"code": c["code"], "segs": segs,
                         "free": round(free / cap["space"] * 100, 2),
                         "free_count": int(free), "space": int(cap["space"])})
        cap_tbl.append({
            "code": c["code"],
            "leader": _short(top[0][0]),
            "leader_share": _pct(top[0][1] / cap["space"]),
            "allocated": _pct(cap["allocated"] / cap["space"]),
            "space": _fmt_int(cap["space"]),
        })
    # flatten into stacked series by rank slot (1st/2nd/3rd/rest/free)
    slots = [f"ספק מוביל {i + 1}" for i in range(CAP_TOP)] + ["ספקים אחרים", "לא מוקצה לספק ברשימה"]
    chart_cap = {"codes": [r["code"] for r in cap_rows], "slots": slots, "series": []}
    for si in range(CAP_TOP + 2):
        data = []
        for r in cap_rows:
            if si < CAP_TOP:
                seg = r["segs"][si] if si < len(r["segs"]) and r["segs"][si]["name"] != "ספקים אחרים" else None
                data.append({"value": seg["value"], "name": seg["full"], "count": seg["count"]}
                            if seg else {"value": 0, "name": "", "count": 0})
            elif si == CAP_TOP:
                seg = next((s for s in r["segs"] if s["name"] == "ספקים אחרים"), None)
                data.append({"value": seg["value"], "name": seg["full"], "count": seg["count"]}
                            if seg else {"value": 0, "name": "", "count": 0})
            else:
                data.append({"value": r["free"], "name": "לא מוקצה לספק ברשימה", "count": r["free_count"]})
        chart_cap["series"].append(data)

    # ---- providers: allocations stacked by type
    pc = alloc.groupby("prov").size()
    prov_order = sorted(pc.index, key=lambda p: (-int(pc[p]), p))
    top_prov = prov_order[:TOP_PROVIDERS]
    rest_prov = prov_order[TOP_PROVIDERS:]
    alloc_types = sorted(alloc["type"].unique(),
                         key=lambda t: (-int(type_alloc.get(t, 0)), t))
    prov_labels = [_short(p) for p in top_prov] + ([f"{OTHER} ({len(rest_prov):,})"] if rest_prov else [])
    prov_series = []
    for t in alloc_types:
        sub = alloc[alloc["type"] == t].groupby("prov").size()
        vals = [int(sub.get(p, 0)) for p in top_prov]
        if rest_prov:
            vals.append(int(sum(sub.get(p, 0) for p in rest_prov)))
        prov_series.append({"name": t, "data": vals})
    chart_prov = {"labels": prov_labels,
                  "full": list(top_prov) + ([", ".join(_short(p) for p in rest_prov)] if rest_prov else []),
                  "series": prov_series}
    prov_tbl = []
    for p in top_prov:
        g = alloc[alloc["prov"] == p]
        prov_tbl.append({"name": p, "n": _fmt_int(len(g)),
                         "codes": ", ".join(sorted(g["code"].unique(), key=_code_key)[:8])
                         + (" …" if g["code"].nunique() > 8 else "")})
    if rest_prov:
        g = alloc[alloc["prov"].isin(rest_prov)]
        prov_tbl.append({"name": f"{OTHER} ({len(rest_prov):,} ספקים)", "n": _fmt_int(len(g)),
                         "codes": ", ".join(sorted(g["code"].unique(), key=_code_key)[:8])
                         + (" …" if g["code"].nunique() > 8 else "")})

    # ---- heatmap provider x service code
    sa_alloc = sa[sa["prov"] != ""]
    hp = sa_alloc.groupby("prov").size()
    heat_prov = sorted(hp.index, key=lambda p: (-int(hp[p]), p))[:HEAT_PROVIDERS]
    heat_codes = [c["code"] for c in codes if c["blocks"] > 0]
    cells = []
    cnt = sa_alloc.groupby(["prov", "code"]).size()
    for yi, p in enumerate(heat_prov):
        for xi, c in enumerate(heat_codes):
            v = int(cnt.get((p, c), 0))
            if v:
                cells.append([xi, yi, v])
    chart_heat = {"x": heat_codes, "y": [_short(p) for p in heat_prov], "full": heat_prov,
                  "cells": cells, "max": max([c[2] for c in cells], default=1),
                  "n_prov": int(sa_alloc["prov"].nunique())}

    # ---- lookup tables
    em = df[df["type"].map(_is_emergency)]
    em_tbl = [{"code": r["code"], "name": r["note"] or "–", "status": r["status"]}
              for _, r in em.iterrows()]
    intl = df[df["type"].map(_is_intl)]
    intl_tbl = [{"code": r["code"], "prov": r["prov"] or (r["note"] or "–")}
                for _, r in intl.iterrows()]
    net = df[df["is_net"]]
    net_tbl = [{"code": r["code"], "name": r["note"] or "–", "type": r["type"]}
               for _, r in net.iterrows()]
    short = df[df["type"].map(lambda t: t.startswith("מספר מקוצר") and not _is_emergency(t))]
    short_tbl = [{"code": r["code"], "name": r["note"] or "–",
                  "prov": _short(r["prov"]) if r["prov"] else "–"}
                 for _, r in short.iterrows()]

    # ---- status
    st = df["status"].value_counts()
    n_cancel = int(st.get(STATUS_CANCEL, 0))
    n_future = int(st.get(STATUS_FUTURE, 0))

    # ---------------------------------------------------------- insights
    def ins_codes():
        withp = [c for c in codes if c["providers"] >= 2]
        if not withp:
            return None
        top = sorted(withp, key=lambda c: (-c["providers"], -c["blocks"], _code_key(c["code"])))[0]
        s = (f"אזור החיוג לשירות {top['code']}"
             + (f" ({top['purpose']})" if top["purpose"] else "")
             + f" מחולק ל-{top['blocks']:,} גושי מספרים בין {top['providers']:,} ספקים, "
             f"יותר מכל קידומת שירות אחרת")
        others = sorted([c for c in withp if c is not top],
                        key=lambda c: (-c["providers"], _code_key(c["code"])))[:2]
        if others:
            s += "; אחריו " + " ו-".join(f"{c['code']} ({c['providers']:,} ספקים)" for c in others)
        return s + "."

    def ins_provider():
        if n_prov < 3:
            return None
        p = prov_order[0]
        n = int(pc[p])
        share = n / len(alloc)
        k = len(alloc[alloc["prov"] == p]["code"].unique())
        second = prov_order[1]
        return (f"{_short(p)} מחזיקה ב-{n:,} הקצאות ({_pct(share)} מ-{len(alloc):,} השורות "
                f"שמוקצות לספק), ב-{k:,} קודי גישה שונים; אחריה {_short(second)} "
                f"עם {int(pc[second]):,}. בסך הכול {n_prov:,} ספקים מורשים ברשימה.")

    def ins_capacity():
        best = None
        for c in cap_codes:
            cap = c["cap"]
            p, v = sorted(cap["by_prov"].items(), key=lambda kv: (-kv[1], kv[0]))[0]
            share = v / cap["space"]
            key = (-share, _code_key(c["code"]))
            if share >= LEAD_SHARE and (best is None or key < best[0]):
                best = (key, c, p, v, share)
        if best is None:
            return None
        _, c, p, v, share = best
        return (f"באזור החיוג {c['code']}"
                + (f" ({c['purpose']})" if c["purpose"] else "")
                + f" מחזיקה {_short(p)} לבדה {_pct(share)} מטווח המספרים "
                f"({v:,} מתוך {c['cap']['space']:,} מספרים אפשריים), "
                f"אף שהקידומת מחולקת בין {c['providers']:,} ספקים.")

    def ins_emergency():
        if em.empty:
            return None
        three = em[em["code"].str.fullmatch(r"\d{3}")]
        s = f"ברשימה {len(em):,} מספרים מקוצרים לחירום, מצוקה ורווחה"
        if len(three):
            pick = three.head(3)
            s += (", בהם " + ", ".join(f"{r['code']} ({r['note']})" for _, r in pick.iterrows()
                                       if r["note"]))
        four = em[em["code"].str.fullmatch(r"\d{4}")]
        if len(four):
            s += f"; {len(four):,} מהם בני ארבע ספרות, כמו {four.iloc[0]['code']} ({four.iloc[0]['note']})"
        return s + "."

    def ins_status():
        if n_cancel == 0 and n_future == 0:
            return None
        parts = []
        if n_cancel:
            cs = df[df["status"] == STATUS_CANCEL]["code"]
            lst = ", ".join(list(cs)[:6]) + (" ועוד" if len(cs) > 6 else "")
            parts.append((f"{n_cancel:,} מספרים מסומנים" if n_cancel > 1 else "מספר אחד מסומן")
                         + f" בהערות כמיועד{'ים' if n_cancel > 1 else ''} לביטול או כלא בשימוש ({lst})")
        if n_future:
            fs = df[df["status"] == STATUS_FUTURE]["code"]
            parts.append((f"{n_future:,} מסומנים כעתידיים" if n_future > 1 else "מספר אחד מסומן כעתידי")
                         + f" ({', '.join(list(fs)[:4])})")
        return "; ".join(parts) + ". לפני חיוג או פרסום מספר כזה כדאי לבדוק את מצבו העדכני."

    def ins_intl():
        if len(intl) < 3:
            return None
        held = intl[intl["prov"] != ""]
        if held.empty:
            return None
        lens = held["code"].str.len()
        parts = []
        for L in sorted(lens.unique()):
            cs = sorted(held[lens == L]["code"], key=_code_key)
            parts.append(f"{len(cs):,} קידומות בנות {L} ספרות (בטווח {cs[0]} עד {cs[-1]})"
                         if len(cs) > 1 else f"קידומת אחת בת {L} ספרות ({cs[0]})")
        return (f"{len(held):,} ספקים מחזיקים קידומת חיוג בינלאומית משלהם: "
                + " ו-".join(parts) + ".")

    def ins_free_premium():
        free = sa[sa["note"].str.contains("חינם") & (sa["prov"] != "")]
        prem = sa[sa["note"].str.contains("פרימיום") & (sa["prov"] != "")]
        if free.empty or prem.empty:
            return None
        fc = ", ".join(sorted(free["code"].unique(), key=_code_key))
        pcs = ", ".join(sorted(prem["code"].unique(), key=_code_key))
        return (f"מספרי חינם ({fc}) מוקצים ב-{len(free):,} גושים ל-{free['prov'].nunique():,} ספקים, "
                f"ומספרי פרימיום ({pcs}) ב-{len(prem):,} גושים ל-{prem['prov'].nunique():,} ספקים.")

    rules = [("codes", ins_codes()), ("provider", ins_provider()), ("capacity", ins_capacity()),
             ("free_premium", ins_free_premium()), ("emergency", ins_emergency()),
             ("intl", ins_intl()), ("status", ins_status())]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    # ---------------------------------------------------------- KPIs
    kpis = {
        "total": {"value": n_rows, "display": _fmt_int(n_rows), "tone": "brand"},
        "emergency": {"value": int(len(em)), "display": _fmt_int(len(em)), "tone": "brand"},
        "codes": {"value": len(codes), "display": _fmt_int(len(codes)), "tone": "brand"},
        "providers": {"value": n_prov, "display": _fmt_int(n_prov), "tone": "brand"},
        "cancel": {"value": n_cancel, "display": _fmt_int(n_cancel),
                   "tone": "warn" if n_cancel else "ok"},
    }

    # ---------------------------------------------------------- summary / labels
    fam = Counter()
    fam_rep = {}
    for c in codes:
        if c["blocks"] and c["code"].isdigit() and len(c["code"]) == 4:
            f = c["code"][:2]
            fam[f] += c["blocks"]
            fam_rep[f] = min(fam_rep.get(f, c["code"]), c["code"], key=_code_key)
    top_fams = sorted(fam, key=lambda f: (-fam[f], f))[:3]
    rep_codes = sorted((fam_rep[f] for f in top_fams), key=_code_key)
    lead = "איתור מספר חירום, מספר מקוצר או קידומת שירות"
    if rep_codes:
        lead += f" ({', '.join(rep_codes)})"
    lead += " ומי הספק שמחזיק בה"
    tail = f": {n_rows:,} מספרים וקידומות, {n_prov:,} ספקים מורשים."
    summary = lead + tail
    if len(summary) > SUMMARY_MAX:
        summary = lead + "."

    lede = (f"תכנית המספור של משרד התקשורת לשירותים ארציים: {n_rows:,} מספרים וקידומות, "
            f"מהמספרים המקוצרים לחירום ועד אזורי החיוג לשירות"
            + (f" ({', '.join(rep_codes)} ועוד)" if rep_codes else "")
            + f" וקידומות החיוג הבינלאומיות. {len(alloc):,} מהשורות מוקצות לאחד מ-{n_prov:,} ספקי תקשורת מורשים, "
            "והשאר הם שירותים כלליים שאינם שייכים לספק אחד.")

    top_type = type_order[0] if type_order else ""
    labels = {
        "lede": lede,
        "kpi_total": "מספרים וקידומות ברשימה",
        "kpi_emergency": "מספרים מקוצרים לחירום ורווחה",
        "kpi_codes": "קידומות של אזורי חיוג לשירות",
        "kpi_providers": "ספקי תקשורת מורשים עם הקצאה",
        "kpi_cancel": "מספרים שמסומנים לביטול או לא בשימוש",
        "types_lede": (f"{top_type} הוא הסוג הנפוץ ({int(type_counts[top_type]):,} שורות, "
                       f"{_pct(type_counts[top_type] / n_rows)}), כי כל קידומת שירות נחלקת לגושים לפי ספק. "
                       "החלק הכהה הוא שורות שמוקצות לספק מסוים." if top_type else ""),
        "types_aria": (f"תרשים עמודות אופקי מוערם: מספר השורות לפי סוג, {len(type_order):,} סוגים, "
                       f"מחולק למוקצה לספק ולשירות כללי. המוביל: {top_type}." if top_type else ""),
        "types_caption": "שורות ברשימה לפי סוג: סך הכול, מוקצות לספק ומספר קודי גישה.",
        "codes_lede": (f"{len(codes):,} קידומות של אזורי חיוג לשירות. לכל קידומת ייעוד אחד "
                       "(מספרי חינם, חיוב מפוצל, פרימיום ועוד), וטווח המספרים שאחריה מחולק לגושים בין הספקים."),
        "codes_aria": (f"תרשים עמודות: מספר הספקים ומספר גושי המספרים בכל אחת מ-{len(codes):,} "
                       "קידומות השירות."),
        "codes_caption": "קידומות אזורי החיוג לשירות: ייעוד, גושי מספרים מוקצים ומספר ספקים.",
        "cap_lede": ("חלק כל ספק בטווח המספרים של כל קידומת, לפי מספר הספרות הפנויות בגוש שהוקצה לו "
                     "(למשל גוש של ספרה קבועה אחת ואחריה חמש ספרות פנויות). "
                     "שלושת הספקים הגדולים בכל קידומת מוצגים בנפרד."),
        "cap_aria": (f"תרשים עמודות מוערם באחוזים: חלוקת טווח המספרים בין הספקים ב-{len(cap_rows):,} "
                     "קידומות שירות, כולל החלק שלא הוקצה."),
        "cap_caption": "לכל קידומת: הספק המחזיק בטווח הגדול ביותר, חלקו, והחלק המוקצה מכלל הטווח.",
        "prov_lede": (f"כל השורות שמוקצות לספק, לפי ספק וסוג. מוצגים {len(top_prov):,} הספקים עם הכי הרבה הקצאות"
                      + (f", ו-{len(rest_prov):,} נוספים מאוחדים תחת {OTHER}." if rest_prov else ".")),
        "prov_aria": (f"תרשים עמודות אופקי מוערם: מספר ההקצאות לכל ספק, לפי סוג. "
                      f"המוביל: {_short(prov_order[0])} עם {int(pc[prov_order[0]]):,}." if prov_order else ""),
        "prov_caption": "הקצאות לפי ספק, וקודי הגישה שמוקצים לו.",
        "heat_lede": (f"מי מחזיק גוש בכל קידומת שירות: {len(heat_prov):,} ספקים מול {len(heat_codes):,} קידומות. "
                      "מספר בתא הוא מספר הגושים של הספק בקידומת."),
        "heat_aria": (f"מפת חום: {len(heat_prov):,} ספקים מול {len(heat_codes):,} קידומות שירות, "
                      "מספר גושי המספרים בכל צירוף."),
        "em_caption": f"{len(em):,} מספרים מקוצרים לחירום, מצוקה ורווחה, עם הגוף ומצב המספר לפי ההערות.",
        "short_caption": f"{len(short):,} מספרים מקוצרים נוספים, עם השירות והספק.",
        "intl_caption": f"{len(intl):,} קידומות חיוג בינלאומיות והספק המחזיק בכל אחת.",
        "net_caption": f"{len(net):,} קודים רשתיים, אחידים אצל כל המפעילים.",
    }

    agent_data = {
        "summary_he": summary,
        "dataset_kind": "registry",
        "suggested_tags": ["תכנית מספור", "מספרי חירום", "מספרים מקוצרים", "קידומות חיוג",
                           "ספקי תקשורת", "משרד התקשורת"],
        "related_ids": ["df60d73b-aa60-46dc-bb76-f183d6bf055c",
                        "a6c90661-7a18-4773-9553-7d26b4db4cb1",
                        "7ae4a3da-1c40-410b-bffb-d89f81709d12"],
        "spatial_coverage": "ישראל",
    }

    return {
        "agent_data": agent_data,
        "kpis": kpis,
        "charts": {"types": chart_types, "codes": chart_codes, "cap": chart_cap,
                   "prov": chart_prov, "heat": chart_heat},
        "insights": insights,
        "tables": {"types": types_tbl, "codes": codes_tbl, "cap": cap_tbl, "prov": prov_tbl,
                   "emergency": em_tbl, "short": short_tbl, "intl": intl_tbl, "net": net_tbl},
        "flags": {"codes": len(codes) >= 2, "cap": len(cap_rows) >= 1,
                  "prov": len(top_prov) >= 2, "heat": len(heat_prov) >= 2 and len(heat_codes) >= 2,
                  "emergency": len(em_tbl) > 0, "short": len(short_tbl) > 0,
                  "intl": len(intl_tbl) > 0, "net": len(net_tbl) > 0},
        "labels": labels,
    }
