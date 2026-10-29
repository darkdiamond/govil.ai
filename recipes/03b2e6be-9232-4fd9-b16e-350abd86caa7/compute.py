"""רשימת מט"שים (מתקני טיפול בשפכים): הרשות הממשלתית למים ולביוב.

One row per (facility, licence owner): a WWTP (`מספר מתקן`, `שם המטש`) holds
one supply licence (`רישיון מטש`, `שם רישיון`) that can list several owners
(`בעלים`), so a facility repeats once per owner. Facility-level attributes
(effluent quality `איכות מים`, treatment type `סוג טיפול`, operator `מפעיל`)
are constant within a facility; the recipe still takes the most frequent
non-empty value (alphabetical tie-break) so a stray inconsistent row can't
make the output order-dependent. `שנה` is the licence year (one value today).

The data carries no coordinates, capacity, district or effluent volumes, so
the page is a lookup + composition view: quality mix, treatment types and
their quality, operators, ownership structure, and a directory grouped by
effluent quality.

Growth: the file is replaced yearly. If several years ever appear, only the
latest is shown (disclosed in the lede). Category axes are top-N + "אחר",
unknown quality grades flow through after the known ones, the directory is
capped at DIR_MAX rows.
"""
import re

import pandas as pd

TOP_TREAT = 10
TOP_OPER = 12
DIR_MAX = 400
TERT_MIN = 5            # min facilities on each side for the tertiary contrast
TERT_GAP = 0.20         # min gap in unrestricted share to state the contrast
POOR_MIN_N = 5          # min facilities in a treatment type for the poor-share rule
POOR_MIN_SHARE = 0.40
TOP3_MIN_SHARE = 0.25
LRI, PDI = "⁦", "⁩"
OTHER = "אחר"
NA_Q = "לא צוינה"

# Known effluent-quality grades, best first: (key, label, colour).
QUALITY = [
    ("ללא מגבלות השקייה ולהזרמה לנחל", "ללא מגבלות השקייה ולהזרמה לנחל", "#198754"),
    ("ללא מגבלות השקייה", "ללא מגבלות השקייה", "#5fb88a"),
    ("בסיסי", "בסיסי", "#0068f5"),
    ("ירוד", "ירוד", "#dc3545"),
]
UNRESTRICTED = {"ללא מגבלות השקייה ולהזרמה לנחל", "ללא מגבלות השקייה"}
POOR = "ירוד"
EXTRA_COLORS = ["#ffc107", "#0dcaf0", "#6f42c1", "#fd7e14"]
NA_COLOR = "#c3cfe7"

TERT_RX = re.compile(r"שלישוני|ממברנה")
SLUDGE_RX = re.compile(r"בוצה\s*מש")

OWNER_KINDS = [
    ("קיבוץ", re.compile(r"קיבוץ|קבוץ|קבוצת")),
    ("תאגיד מים וביוב", re.compile(r"תאגיד|מים וביוב|ביוב ומים|^מי[\s\-]")),
    ("חברה", re.compile(r"בעמ|בע\"מ|חברה|החברה|חב'|אגשח|אג'")),
    ("רשות מקומית או איגוד ערים", re.compile(r"עיריה|עירייה|מועצה|מ\.א|איגוד ערים|אגוד ערים")),
]
OWNER_OTHER = "גוף אחר"


def n(v):
    return f"{int(v):,}"


def pct(v, digits=1):
    return f"{LRI}{v * 100:.{digits}f}%{PDI}"


def pct_plain(v, digits=1):
    return f"{v * 100:.{digits}f}%"


def clean(s):
    return " ".join(str(s).replace(" ", " ").split())


def wwtp(k):
    return 'מט"ש אחד' if k == 1 else f'{n(k)} מט"שים'


def norm_quality(s):
    s = clean(s).replace("השקיה", "השקייה")
    return s


def join_he(items):
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    last = items[-1]
    conj = " ו-" if last[:1].isdigit() else " ו"
    return ", ".join(items[:-1]) + conj + last


def mode(values):
    vals = [v for v in values if v]
    if not vals:
        return ""
    vc = pd.Series(vals).value_counts()
    best = max(vc.tolist())
    return sorted(k for k, c in vc.items() if c == best)[0]


def owner_kind(s):
    for name, rx in OWNER_KINDS:
        if rx.search(s):
            return name
    return OWNER_OTHER


def _prepare(df):
    out = pd.DataFrame({
        "fac": df["מספר מתקן"].map(clean),
        "name": df["שם המטש"].map(clean),
        "quality": df["איכות מים"].map(norm_quality),
        "oper": df["מפעיל"].map(clean),
        "year_raw": df["שנה"].map(clean),
        "owner": df["בעלים"].map(clean),
        "treat": df["סוג טיפול"].map(clean),
    })
    out["key"] = [f if f else ("name:" + nm) for f, nm in zip(out["fac"], out["name"])]
    out = out[out["key"] != "name:"].copy()
    out["year"] = pd.to_numeric(out["year_raw"], errors="coerce")
    years = sorted(int(y) for y in out["year"].dropna().unique())
    latest = years[-1] if years else None
    dropped = 0
    if latest is not None:
        keep = out["year"] == latest
        dropped = int((~keep).sum())
        out = out[keep].copy()
    out = out.sort_values(["key", "owner", "name", "quality", "oper", "treat"],
                          kind="mergesort").reset_index(drop=True)
    return out, latest, years, dropped


def _facilities(df):
    rows = []
    for key, g in df.groupby("key", sort=True):
        owners = sorted(set(o for o in g["owner"] if o))
        rows.append({
            "key": key,
            "name": mode(g["name"]) or key,
            "quality": mode(g["quality"]) or NA_Q,
            "treat": mode(g["treat"]) or "לא צוין",
            "oper": mode(g["oper"]) or "לא צוין",
            "owners": owners,
        })
    f = pd.DataFrame(rows)
    f = f.sort_values(["name", "key"], kind="mergesort").reset_index(drop=True)
    return f


def _quality_levels(f):
    present = set(f["quality"])
    levels = []
    for key, label, color in QUALITY:
        if key in present:
            levels.append((key, label, color))
    known = {q[0] for q in QUALITY}
    extras = sorted(q for q in present if q not in known and q != NA_Q)
    for i, q in enumerate(extras):
        levels.append((q, q, EXTRA_COLORS[i % len(EXTRA_COLORS)]))
    if NA_Q in present:
        levels.append((NA_Q, NA_Q, NA_COLOR))
    return levels


def _top_cats(series, top):
    vc = series.value_counts()
    order = sorted(vc.items(), key=lambda kv: (-kv[1], kv[0]))
    names = [k for k, _ in order[:top]]
    rest = len(order) - len(names)
    return names, rest


def _stacked(f, col, top, levels):
    names, rest = _top_cats(f[col], top)
    bucket = f[col].where(f[col].isin(names), OTHER)
    cats = names + ([OTHER] if rest > 0 else [])
    ct = pd.crosstab(bucket, f["quality"])
    series = []
    for key, label, color in levels:
        data = [int(ct.at[c, key]) if (c in ct.index and key in ct.columns) else 0 for c in cats]
        series.append({"name": label, "color": color, "data": data})
    totals = [int((bucket == c).sum()) for c in cats]
    table = []
    for i, c in enumerate(cats):
        table.append({"name": c, "total": n(totals[i]),
                      "cells": [n(s["data"][i]) for s in series]})
    return {"names": cats, "series": series, "totals": totals}, table, rest


def compute(frames):
    df, year, years, dropped = _prepare(frames["main"])
    f = _facilities(df)
    total = len(f)
    levels = _quality_levels(f)
    qcount = f["quality"].value_counts()

    # ---- quality mix
    q_names = [lab for _, lab, _ in levels]
    q_values = [int(qcount.get(k, 0)) for k, _, _ in levels]
    q_colors = [c for _, _, c in levels]
    q_table = [{"name": lab, "count": n(v), "share": pct_plain(v / total) if total else "0%"}
               for lab, v in zip(q_names, q_values)]

    unres = int(f["quality"].isin(UNRESTRICTED).sum())
    stream = int((f["quality"] == "ללא מגבלות השקייה ולהזרמה לנחל").sum())
    poor = int((f["quality"] == POOR).sum())
    na_q = f[f["quality"] == NA_Q]
    graded = total - len(na_q)

    # ---- treatment / operator cross-tabs
    treat_chart, treat_table, treat_rest = _stacked(f, "treat", TOP_TREAT, levels)
    oper_chart, oper_table, oper_rest = _stacked(f, "oper", TOP_OPER, levels)
    n_treat = int(f["treat"].nunique())
    n_oper = int(f.loc[f["oper"] != "לא צוין", "oper"].nunique())

    # ---- ownership
    f["n_owners"] = f["owners"].map(len)
    max_owners = int(f["n_owners"].max()) if total else 0
    cap = 5
    own_names, own_values = [], []
    for k in range(1, min(max_owners, cap - 1) + 1):
        own_names.append("בעלים אחד" if k == 1 else f"{k} בעלים")
        own_values.append(int((f["n_owners"] == k).sum()))
    if max_owners >= cap:
        own_names.append(f"{cap} בעלים ומעלה")
        own_values.append(int((f["n_owners"] >= cap).sum()))
    own_table = [{"name": a, "count": n(b)} for a, b in zip(own_names, own_values)]

    pairs = sorted(set((k, o) for k, os_ in zip(f["key"], f["owners"]) for o in os_))
    owner_records = len(pairs)
    distinct_owners = len(set(o for _, o in pairs))
    kinds = pd.Series([owner_kind(o) for _, o in pairs], dtype=object)
    kc = kinds.value_counts()
    kind_order = sorted(kc.items(), key=lambda kv: (kv[0] == OWNER_OTHER, -kv[1], kv[0]))
    kind_names = [k for k, _ in kind_order]
    kind_values = [int(v) for _, v in kind_order]
    kind_table = [{"name": k, "count": n(v),
                   "share": pct_plain(v / owner_records) if owner_records else "0%"}
                  for k, v in kind_order]

    # ---- directory grouped by quality
    directory = []
    shown = 0
    for key, label, color in levels:
        g = f[f["quality"] == key]
        rows = []
        for _, r in g.iterrows():
            if shown >= DIR_MAX:
                break
            rows.append({"name": r["name"], "treat": r["treat"], "oper": r["oper"],
                         "owners": "، ".join(r["owners"]) if r["owners"] else "לא צוינו"})
            shown += 1
        directory.append({"label": label, "count": wwtp(len(g)), "rows": rows,
                          "truncated": len(rows) < len(g)})
    dir_truncated = shown < total

    # ---- insights
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    def ins_quality():
        if graded < 1:
            return None
        parts = [f'{n(unres)} מתוך {n(total)} המט"שים ({pct(unres / total)}) מספקים קולחים '
                 f'באיכות ללא מגבלות השקייה']
        if stream:
            parts[0] += f" (מהם {wwtp(stream)} גם באיכות להזרמה לנחל)"
        if poor:
            parts.append(f"ו-{wwtp(poor)} ({pct(poor / total)}) באיכות ירודה")
        return ", ".join(parts) + "."

    def ins_tertiary():
        tert = f["treat"].map(lambda s: bool(TERT_RX.search(s)))
        gf = f["quality"] != NA_Q
        t, o = f[tert & gf], f[~tert & gf]
        if len(t) < TERT_MIN or len(o) < TERT_MIN:
            return None
        ut = int(t["quality"].isin(UNRESTRICTED).sum())
        uo = int(o["quality"].isin(UNRESTRICTED).sum())
        rt, ro = ut / len(t), uo / len(o)
        if rt - ro < TERT_GAP:
            return None
        return (f'הטיפול השלישוני מכריע את איכות הקולחים: {n(ut)} מתוך {n(len(t))} המט"שים '
                f"שסוג הטיפול שלהם כולל טיפול שלישוני או ממברנה ({pct(rt)}) מגיעים לאיכות "
                f"ללא מגבלות השקייה, לעומת {n(uo)} מתוך {n(len(o))} ({pct(ro)}) בשאר המט\"שים.")

    def ins_treat():
        names, _ = _top_cats(f["treat"], 1)
        if not names or total < 2:
            return None
        lead = names[0]
        k = int((f["treat"] == lead).sum())
        s = f"סוג הטיפול הנפוץ ביותר הוא {lead}: {wwtp(k)} ({pct(k / total)})"
        sl = int(f["treat"].map(lambda v: bool(SLUDGE_RX.search(v))).sum())
        if sl > k:
            s += f'. בסך הכול {wwtp(sl)} ({pct(sl / total)}) מבוססים על בוצה משופעלת בגרסה כלשהי'
        return s + f". ברשימה {n(n_treat)} סוגי טיפול שונים."

    def ins_poor_treat():
        best = None
        for t, g in f[f["quality"] != NA_Q].groupby("treat", sort=True):
            if len(g) < POOR_MIN_N:
                continue
            k = int((g["quality"] == POOR).sum())
            sh = k / len(g)
            cand = (sh, len(g), t, k)
            if best is None or (cand[0], cand[1]) > (best[0], best[1]) or \
                    ((cand[0], cand[1]) == (best[0], best[1]) and t < best[2]):
                best = cand
        if best is None or best[0] < POOR_MIN_SHARE:
            return None
        sh, cnt, t, k = best
        return (f"שיעור הקולחים באיכות ירודה הגבוה ביותר הוא במט\"שים מסוג {t}: "
                f"{n(k)} מתוך {n(cnt)} ({pct(sh)}).")

    def ins_oper():
        vc = f.loc[f["oper"] != "לא צוין", "oper"].value_counts()
        order = sorted(vc.items(), key=lambda kv: (-kv[1], kv[0]))
        if len(order) < 4 or total < 1:
            return None
        top = order[:3]
        s = sum(v for _, v in top)
        if s / total < TOP3_MIN_SHARE:
            return None
        named = join_he(f"{k} ({n(v)})" for k, v in top)
        return (f"שלושת המפעילים הגדולים, {named}, מפעילים יחד {n(s)} מתוך {n(total)} "
                f"המט\"שים ({pct(s / total)}). ברשימה {n(len(order))} מפעילים שונים.")

    def ins_owners():
        multi = int((f["n_owners"] >= 2).sum())
        if multi < 1 or max_owners < 2:
            return None
        tops = f[f["n_owners"] == max_owners]["name"].tolist()
        lead = join_he(tops[:3]) + (" ואחרים" if len(tops) > 3 else "")
        head = (f"ל-{wwtp(multi)} ({pct(multi / total)}) רשומים ברישיון יותר מבעלים אחד"
                if multi > 1 else "למט\"ש אחד רשומים ברישיון יותר מבעלים אחד")
        noun = "למט\"ש" if len(tops) == 1 else "למט\"שים"
        return f"{head}; {noun} {lead} רשומים {n(max_owners)} בעלים, המספר הגבוה ביותר ברשימה."

    def ins_kinds():
        if owner_records < 5 or not kind_order:
            return None
        k1, v1 = kind_order[0]
        if k1 == OWNER_OTHER:
            return None
        s = f"בין {n(owner_records)} רשומות הבעלות, הקבוצה הגדולה היא {k1} ({n(v1)}, {pct(v1 / owner_records)})"
        kib = int(kc.get("קיבוץ", 0))
        if kib >= 3 and k1 != "קיבוץ":
            s += f"; {n(kib)} מבעלי הרישיונות הם קיבוצים"
        return s + ". הסיווג נעשה לפי מילות מפתח בשם הבעלים."

    def ins_missing():
        if len(na_q) < 1:
            return None
        names = na_q["name"].tolist()
        lead = join_he(names[:5]) + (" ואחרים" if len(names) > 5 else "")
        verb = "לא צוינה איכות הקולחים"
        return f"ל-{wwtp(len(names))} ({lead}) {verb}, והם מוצגים בנפרד בתרשימים ובטבלה."

    add("quality", ins_quality())
    add("tertiary", ins_tertiary())
    add("treat", ins_treat())
    add("poor_treat", ins_poor_treat())
    add("oper", ins_oper())
    add("owners", ins_owners())
    add("kinds", ins_kinds())
    add("missing", ins_missing())

    # ---- labels
    year_txt = f" נכון לשנת {year}" if year is not None else ""
    lede = (f'רשימת מתקני הטיפול בשפכים (מט"שים, מכוני טיהור שפכים) שבעליהם מחזיקים ברישיון '
            f'אספקת קולחים מהרשות הממשלתית למים ולביוב{year_txt}: {wwtp(total)}, '
            f"{n(n_oper)} מפעילים ו-{n(distinct_owners)} בעלים שונים. לכל מט\"ש מופיעים סוג הטיפול, "
            f"איכות הקולחים שהוא מספק (מירוד ועד ללא מגבלות השקייה), המפעיל והבעלים ברישיון.")
    if dropped:
        lede += f" מוצגת השנה העדכנית בלבד; {n(dropped)} שורות משנים קודמות אינן נכללות."

    q_lead = max(range(len(q_values)), key=lambda i: (q_values[i], -i)) if q_values else None
    labels = {
        "lede": lede,
        "year_note": f"נכון לשנת {year}" if year is not None else "",
        "total_kpi": f'מט"שים ברשימה' + (f" ({year})" if year is not None else ""),
        "oper_kpi": "מפעילים שונים",
        "unres_kpi": 'מט"שים עם קולחים ללא מגבלות השקייה',
        "poor_kpi": 'מט"שים עם קולחים באיכות ירודה',
        "quality_note": (f'האיכות הנפוצה היא "{q_names[q_lead]}": {wwtp(q_values[q_lead])} '
                         f"מתוך {n(total)}." if q_lead is not None and total else ""),
        "quality_aria": "התפלגות המט\"שים לפי איכות הקולחים: " + ", ".join(
            f"{a} {b}" for a, b in zip(q_names, q_values)),
        "treat_note": (f"{n(n_treat)} סוגי טיפול; מוצגים {n(min(TOP_TREAT, n_treat))} הנפוצים"
                       + (f' והשאר תחת "{OTHER}"' if treat_rest > 0 else "")
                       + ". כל עמודה מחולקת לפי איכות הקולחים שהמט\"ש מספק."),
        "treat_aria": "מט\"שים לפי סוג טיפול ואיכות קולחים: " + ", ".join(
            f"{a} {b}" for a, b in zip(treat_chart["names"], treat_chart["totals"])),
        "oper_note": (f"{n(n_oper)} מפעילים; מוצגים {n(min(TOP_OPER, len(oper_chart['names'])))} "
                      f"הגדולים לפי מספר מט\"שים" + (f' והשאר תחת "{OTHER}"' if oper_rest > 0 else "")
                      + ", מחולקים לפי איכות הקולחים."),
        "oper_aria": "מט\"שים לפי מפעיל: " + ", ".join(
            f"{a} {b}" for a, b in zip(oper_chart["names"], oper_chart["totals"])),
        "own_note": (f"מספר הבעלים הרשומים ברישיון של כל מט\"ש. "
                     f"{wwtp(own_values[0])} עם בעלים אחד בלבד." if own_values else ""),
        "own_aria": "מט\"שים לפי מספר הבעלים ברישיון: " + ", ".join(
            f"{a} {b}" for a, b in zip(own_names, own_values)),
        "kind_note": (f"{n(owner_records)} רשומות בעלות ({n(distinct_owners)} בעלים שונים), "
                      "מסווגות לפי מילות מפתח בשם הבעלים (עירייה, מועצה, תאגיד, קיבוץ, חברה)."),
        "kind_aria": "רשומות בעלות לפי סוג הבעלים: " + ", ".join(
            f"{a} {b}" for a, b in zip(kind_names, kind_values)),
        "dir_note": (f"כל {wwtp(total)} ברשימה, מקובצים לפי איכות הקולחים וממוינים לפי שם."
                     + (f" מוצגים {n(shown)} הראשונים; לשאר השתמשו בחיפוש בתחתית העמוד."
                        if dir_truncated else "")),
    }

    unres_share = unres / total if total else 0.0
    poor_share = poor / total if total else 0.0
    kpis = {
        "total": {"value": total, "display": n(total), "tone": "brand"},
        "oper": {"value": n_oper, "display": n(n_oper), "tone": "brand"},
        "unres": {"value": round(unres_share, 4), "display": pct_plain(unres_share),
                  "tone": "ok" if unres_share >= 0.5 else "info"},
        "poor": {"value": round(poor_share, 4), "display": pct_plain(poor_share),
                 "tone": "danger" if poor_share >= 0.35 else ("warn" if poor_share >= 0.15 else "ok")},
    }

    summary = (f'איתור מט"ש (מתקן טיפול בשפכים) לפי שם, מפעיל או בעלים: {n(total)} מט"שים, '
               f"סוג הטיפול ואיכות הקולחים" + (f", נכון ל-{year}." if year is not None else "."))

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "registry",
            "suggested_tags": ['מט"ש', "טיפול בשפכים", "מכוני טיהור", "קולחים", "איכות מים", "ביוב"],
            "related_ids": [
                "5de14d12-d5d7-475d-ade1-5dbd0ef9d086",
                "db8f9bc9-738a-4d83-b3ce-74e8a5f7f844",
                "87514149-a73c-424d-89b4-80d3c9058f7a",
            ],
            **({"temporal_coverage": str(year)} if year is not None else {}),
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": {
            "quality": {"names": q_names, "values": q_values, "colors": q_colors},
            "treat": treat_chart,
            "oper": oper_chart,
            "owners": {"names": own_names, "values": own_values},
            "kinds": {"names": kind_names, "values": kind_values},
        },
        "tables": {
            "quality": q_table,
            "levels": q_names,
            "treat": treat_table,
            "oper": oper_table,
            "owners": own_table,
            "kinds": kind_table,
        },
        "directory": directory,
        "insights": insights,
        "labels": labels,
    }
