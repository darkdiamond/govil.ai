"""Rabbinical-court fee schedule (תעריפי אגרות של בתי הדין הרבניים).

One flat table: claim subject (נושא תביעה, blank for general requests),
fee name (אגרה) and amount in ₪ (תעריף). The page is a fee lookup first
(grouped by procedure family) plus an analysis of the fee structure.

Families are assigned by keyword on the claim subject, with a fallback
bucket, so new subjects always flow through. The "standard fee" is the
most common non-zero amount in the data (not a constant), so the page
keeps working when the schedule is re-indexed.
"""
import re

import pandas as pd

OPEN_FEE = "אגרת פתיחת תיק"
NO_SUBJECT = "כללי (ללא נושא תביעה)"
OTHER_FAMILY = "הליכים ובקשות אחרים"

# (family, keywords). Order matters: first match wins. Keywords match as
# whole Hebrew tokens or token prefixes (see _kw_match).
FAMILIES = [
    ("ירושה, צוואות ועזבונות", ["עזבון", "עזבונות", "ירושה", "צוואה"]),
    ("הקדשות", ["הקדשות", "הקדש"]),
    ("גיור", ["גיור", "גירות"]),
    ("גירושין וגיטין", ["גירושין", "לגירושין", "גיטין", "גט", "חליצה", "כתובה", "מורד/ת",
                        "עגונות"]),
    ("מזונות, ילדים ואפוטרופסות", ["מזונות", "ילדים", "אפוטרופוס", "אימוץ"]),
    ("צווים וסעדים", ["צו", "צווי", "צווים", "סעד", "עיכוב", "עיקול", "הגבלה"]),
    ("נישואין ומעמד אישי", ["נישואין", "רווקות", "אלמנות", "יוחסין", "יהדות",
                            "מעמד", "אבהות", "מעוברת"]),
    ("רכוש, ממון ובוררות", ["רכוש", "ממון", "כספית", "בוררות", "נכסים"]),
    ("שלום בית ויישוב סכסוך", ["שלום", "סכסוך"]),
]

BANDS = ["ללא אגרה", "מתחת לתעריף הנפוץ", "התעריף הנפוץ", "מעל התעריף הנפוץ"]

_TOKEN_RE = re.compile(r"[א-ת\"״׳'/]+")


def _int(n):
    return f"{int(round(n)):,}"


def _ils(n):
    return f"{_int(n)} ₪"


def _pct(x):
    return f"{x * 100:.1f}%"


def _norm(s):
    return re.sub(r"\s+", " ", str(s)).strip()


def _kw_match(subject, kw):
    tokens = _TOKEN_RE.findall(subject)
    if "/" in kw:
        return kw in tokens
    parts = [p for t in tokens for p in t.split("/") if p]
    return any(p == kw or (len(kw) >= 4 and p.startswith(kw)) for p in parts)


def _family(subject):
    if not subject:
        return OTHER_FAMILY
    for fam, kws in FAMILIES:
        if any(_kw_match(subject, k) for k in kws):
            return fam
    return OTHER_FAMILY


def _prepare(df):
    df = df.copy()
    df["subject"] = df["נושא תביעה"].map(_norm)
    df["fee_name"] = df["אגרה"].map(_norm)
    df["fee"] = pd.to_numeric(df["תעריף"].str.replace(",", "", regex=False)
                              .str.replace("₪", "", regex=False).str.strip(),
                              errors="coerce")
    df = df.dropna(subset=["fee"])
    df = df[(df["fee_name"] != "") | (df["subject"] != "")]
    df = df[df["fee"] >= 0]
    df = df.drop_duplicates(subset=["subject", "fee_name", "fee"])
    df["family"] = df["subject"].map(_family)
    df["subject_disp"] = df["subject"].where(df["subject"] != "", NO_SUBJECT)
    return df.sort_values(["family", "subject", "fee", "fee_name"],
                          kind="stable").reset_index(drop=True)


def _family_order(df):
    known = [f for f, _ in FAMILIES] + [OTHER_FAMILY]
    present = [f for f in known if f in set(df["family"])]
    return present


def _standard_fee(df):
    paid = df[df["fee"] > 0]["fee"]
    if paid.empty:
        return None, 0
    vc = paid.value_counts()
    vc = vc.sort_index().sort_values(ascending=False, kind="stable")
    return float(vc.index[0]), int(vc.iloc[0])


def _band(fee, std):
    if fee == 0:
        return BANDS[0]
    if std is None:
        return BANDS[3]
    if fee < std:
        return BANDS[1]
    if fee == std:
        return BANDS[2]
    return BANDS[3]


# ── insight rules ────────────────────────────────────────────────────────

def insight_standard(df, n, std, std_n):
    if std is None or n == 0:
        return None
    share = std_n / n
    if share < 0.2:
        return None
    fams = df[df["fee"] == std]["family"].value_counts().sort_index().sort_values(
        ascending=False, kind="stable")
    return (f"התעריף הנפוץ ביותר בלוח הוא {_ils(std)} — הוא חל על {_int(std_n)} "
            f"מתוך {_int(n)} סעיפי האגרה ({_pct(share)}); התחום שבו הוא מופיע "
            f"הכי הרבה הוא {fams.index[0]} ({_int(fams.iloc[0])} סעיפים).")


def insight_free(df):
    free = df[df["fee"] == 0]
    if free.empty:
        return None
    subs = sorted(set(free["subject"]) - {""})
    ex = subs[:5]
    tail = f", ובהם {', '.join(ex)}" if ex else ""
    return (f"{_int(len(free))} סעיפים ({_pct(len(free) / len(df))}) פטורים "
            f"מאגרה (0 ₪), ב-{_int(len(subs))} נושאי תביעה{tail}.")


def insight_top(df):
    mx = df["fee"].max()
    if pd.isna(mx) or mx <= 0:
        return None
    top = df[df["fee"] == mx]
    fam = top["family"].value_counts().sort_index().sort_values(
        ascending=False, kind="stable")
    lead, lead_n = fam.index[0], int(fam.iloc[0])
    share = lead_n / len(top)
    if share < 0.5:
        return (f"האגרה הגבוהה ביותר בלוח היא {_ils(mx)}, והיא חלה על "
                f"{_int(len(top))} סעיפים.")
    who = "כולם" if lead_n == len(top) else f"{_int(lead_n)} מהם ({_pct(share)})"
    ex = sorted(set(top[top["family"] == lead]["subject"]) - {""})[:3]
    tail = f", למשל {', '.join(ex)}" if ex else ""
    return (f"האגרה הגבוהה ביותר בלוח היא {_ils(mx)}, והיא חלה על "
            f"{_int(len(top))} סעיפים — {who} בתחום {lead}{tail}.")


def insight_copies(df):
    """Per-copy pricing: '... - N עותקים' rows that equal N × the single copy."""
    rows = df[df["fee_name"].str.contains("העתק", regex=False)]
    if rows.empty:
        return None
    pts = []
    for name, fee in zip(rows["fee_name"], rows["fee"]):
        m = re.search(r"(\d+)\s*עותקים", name)
        pts.append((int(m.group(1)) if m else 1, float(fee), name))
    singles = [f for k, f, nm in pts if k == 1 and "-" not in nm.split("העתק")[-1]]
    multi = [(k, f) for k, f, _ in pts if k > 1]
    if not singles or not multi:
        return None
    base = min(singles)
    if base <= 0 or any(abs(f - k * base) > 0.01 for k, f in multi):
        return None
    kmax = max(k for k, _ in multi)
    return (f"העתק פסק דין או אישור העתק מתומחר לפי עותק: {_ils(base)} לעותק "
            f"אחד, ועד {_ils(kmax * base)} ל-{_int(kmax)} עותקים.")


def insight_open_contrast(df):
    op = df[df["fee_name"] == OPEN_FEE]
    g = op.groupby("family")["fee"].agg(["median", "size"])
    g = g[g["size"] >= 3]
    if len(g) < 2:
        return None
    g = g.sort_index().sort_values("median", ascending=False, kind="stable")
    hi_f, hi = g.index[0], g["median"].iloc[0]
    lo_f, lo = g.index[-1], g["median"].iloc[-1]
    if lo <= 0 or hi / lo < 1.2:
        if hi > 0 and lo == 0:
            return (f"אגרת פתיחת תיק בתחום {hi_f} עומדת בחציון על {_ils(hi)}, "
                    f"ואילו בתחום {lo_f} החציון הוא 0 ₪ — לפחות מחצית מסעיפי פתיחת התיק בו פטורים מאגרה.")
        return None
    return (f"אגרת פתיחת תיק משתנה לפי תחום: בתחום {hi_f} החציון הוא "
            f"{_ils(hi)}, פי {hi / lo:.1f} מהחציון בתחום {lo_f} ({_ils(lo)}) "
            f"(בהשוואה בין תחומים עם {_int(3)} סעיפי פתיחת תיק לפחות).")


def insight_spread(df):
    g = df.groupby("subject")["fee"].agg(["min", "max", "size"])
    g = g[(g.index != "") & (g["size"] >= 3)]
    if g.empty:
        return None
    g["rng"] = g["max"] - g["min"]
    g = g.sort_index().sort_values(["rng", "size"], ascending=False, kind="stable")
    s = g.index[0]
    r = g.iloc[0]
    if r["rng"] <= 0:
        return None
    return (f"בנושא \"{s}\" פער האגרות הגדול ביותר: {_int(r['size'])} סעיפים, "
            f"מ-{_ils(r['min'])} ועד {_ils(r['max'])} — כדאי לבדוק איזו בקשה "
            "בדיוק מגישים.")


def insight_unpriced(df):
    rows = df[df["fee_name"].str.contains("שלא נקבעה לה אגרה", regex=False)]
    if rows.empty:
        return None
    vals = rows["fee"].value_counts().sort_index().sort_values(
        ascending=False, kind="stable")
    if len(vals) == 1:
        return (f"בקשה שלא נקבעה לה אגרה ספציפית מחויבת בתעריף אחיד של "
                f"{_ils(vals.index[0])} ({_int(len(rows))} סעיפים).")
    if len(vals) > 3:
        return None
    parts = []
    for v in vals.index:
        fams = rows[rows["fee"] == v]["family"]
        fam = fams.value_counts().sort_index().sort_values(
            ascending=False, kind="stable").index[0]
        parts.append(f"{_ils(v)} (בעיקר בתחום {fam})")
    return ("בקשה שלא נקבעה לה אגרה ספציפית אינה פטורה: היא מחויבת ב-"
            + " או ב-".join(parts) + ".")


# ── compute ──────────────────────────────────────────────────────────────

def compute(frames):
    df = _prepare(frames["fees"])
    n = len(df)
    std, std_n = _standard_fee(df)
    fams = _family_order(df)
    subjects = sorted(set(df["subject"]) - {""})
    paid = df[df["fee"] > 0]["fee"]
    n_free = int((df["fee"] == 0).sum())
    mx = float(df["fee"].max())
    med_paid = float(paid.median()) if not paid.empty else 0.0
    df["band"] = [_band(f, std) for f in df["fee"]]

    # Tier distribution: every distinct amount, binned if there are too many.
    tiers = df.groupby("fee").size().sort_index()
    if len(tiers) <= 24:
        tier_x = [_int(v) for v in tiers.index]
        tier_y = [int(c) for c in tiers]
        tier_hl = [bool(std is not None and v == std) for v in tiers.index]
        tier_binned = False
    else:
        step = 100
        b = (df["fee"] // step).astype(int)
        t2 = df.groupby(b).size().sort_index()
        tier_x = [f"{_int(k * step)}–{_int(k * step + step - 1)}" for k in t2.index]
        tier_y = [int(c) for c in t2]
        tier_hl = [False] * len(t2)
        tier_binned = True

    # Families: box stats + band mix.
    fam_rows = []
    box = []
    mix = {bnd: [] for bnd in BANDS}
    for f in fams:
        s = df[df["family"] == f]["fee"]
        q = s.quantile([0, 0.25, 0.5, 0.75, 1.0]).tolist()
        box.append([round(float(v), 1) for v in q])
        fam_rows.append({
            "family": f, "n_items": int(len(s)),
            "subjects": int(df[df["family"] == f]["subject"].nunique()),
            "min": _int(q[0]), "median": _int(q[2]), "max": _int(q[4]),
        })
        bc = df[df["family"] == f]["band"].value_counts()
        for bnd in BANDS:
            mix[bnd].append(int(bc.get(bnd, 0)))

    # Fee kinds (אגרה column), top-N + other.
    kinds = df.groupby("fee_name")["fee"].agg(["size", "median"])
    kinds = kinds.sort_index().sort_values("size", ascending=False, kind="stable")
    kinds_multi = kinds[kinds["size"] >= 2]
    top_k = kinds_multi.head(7)
    rest = df[~df["fee_name"].isin(top_k.index)]
    kind_names = list(top_k.index)
    kind_counts = [int(v) for v in top_k["size"]]
    kind_med = [round(float(v), 1) for v in top_k["median"]]
    if len(rest):
        kind_names.append("אגרות אחרות")
        kind_counts.append(int(len(rest)))
        kind_med.append(round(float(rest["fee"].median()), 1))
    open_n = int((df["fee_name"] == OPEN_FEE).sum())
    n_rest_kinds = int(rest["fee_name"].nunique())

    # Lookup: family -> subject -> fee rows.
    lookup = []
    for f in fams:
        sub = df[df["family"] == f]
        groups = []
        for sname in sorted(set(sub["subject"]), key=lambda x: (x == "", x)):
            g = sub[sub["subject"] == sname].sort_values(
                ["fee_name", "fee"], key=None, kind="stable")
            # opening fee first, then by fee then name
            g = g.assign(_o=(g["fee_name"] != OPEN_FEE).astype(int)).sort_values(
                ["_o", "fee", "fee_name"], kind="stable")
            groups.append({
                "subject": g["subject_disp"].iloc[0],
                "rows": [{"name": nm, "fee": _int(v), "free": bool(v == 0)}
                         for nm, v in zip(g["fee_name"], g["fee"])],
            })
        lookup.append({
            "family": f,
            "n_items": int(len(sub)),
            "subjects": len(groups),
            "range": (f"{_int(sub['fee'].min())}–{_int(sub['fee'].max())}"
                      if sub["fee"].min() != sub["fee"].max()
                      else _int(sub["fee"].min())),
            "groups": groups,
        })

    rules = [
        ("standard", insight_standard(df, n, std, std_n)),
        ("top", insight_top(df)),
        ("free", insight_free(df)),
        ("open_contrast", insight_open_contrast(df)),
        ("spread", insight_spread(df)),
        ("unpriced", insight_unpriced(df)),
        ("copies", insight_copies(df)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    std_disp = _int(std) if std is not None else "0"
    top_fam = fam_rows and max(fam_rows, key=lambda r: (r["n_items"], r["family"]))
    mix_lead = None
    if std is not None:
        shares = [(mix[BANDS[2]][i] / fam_rows[i]["n_items"], fams[i])
                  for i in range(len(fams)) if fam_rows[i]["n_items"] >= 3]
        if shares:
            mix_lead = sorted(shares, key=lambda t: (-t[0], t[1]))[0]

    meta = (f"איתור אגרת בית הדין הרבני לפי סוג ההליך: {_int(n)} סעיפי אגרה "
            f"ב-{_int(len(subjects))} נושאי תביעה, מ-0 ועד {_ils(mx)}; "
            f"התעריף הנפוץ {_ils(std or 0)}.")
    summary = (f"לוח תעריפי האגרות של בתי הדין הרבניים: {_int(n)} סעיפי אגרה "
               f"ב-{_int(len(subjects))} נושאי תביעה, מ-0 ₪ ועד {_ils(mx)}. "
               f"התעריף הנפוץ הוא {_ils(std or 0)}, ו-{_int(n_free)} סעיפים "
               "פטורים מאגרה. בעמוד טבלת איתור מהירה של האגרה לפי סוג ההליך.")

    return {
        "agent_data": {
            "summary_he": meta,
            "dataset_kind": "registry",
            "suggested_tags": ["אגרות", "תעריפים", "בתי דין רבניים", "גירושין",
                               "ירושה", "משפט עברי"],
            "related_ids": ["9a462a27-39c1-4c61-ae4c-e7fa3e97bb0d",
                            "b09cc06d-02f7-49ce-a64d-f0d47de15ce1",
                            "093b92d2-b730-420c-a9e6-a81f0ac8a044",
                            "fa494da7-1dd9-4806-a03d-a5ee95babb4a",
                            "d4b95764-3d20-41a2-88a7-bdb553a6951f"],
            "spatial_coverage": "ישראל",
        },
        "kpis": {
            "items": {"value": n, "display": _int(n), "tone": "brand"},
            "subjects": {"value": len(subjects), "display": _int(len(subjects)),
                         "tone": "brand"},
            "standard": {"value": std, "display": std_disp, "tone": "info"},
            "max": {"value": mx, "display": _int(mx), "tone": "warn"},
            "free": {"value": n_free, "display": _int(n_free),
                     "tone": "ok" if n_free > 0 else "brand"},
            "median": {"value": med_paid, "display": _int(med_paid), "tone": "brand"},
        },
        "charts": {
            "tiers": {"x": tier_x, "y": tier_y, "hl": tier_hl},
            "families": {"names": fams, "box": box,
                         "items": [r["n_items"] for r in fam_rows]},
            "mix": {"names": fams, "bands": BANDS,
                    "series": [mix[b] for b in BANDS]},
            "kinds": {"names": kind_names, "counts": kind_counts, "median": kind_med},
        },
        "insights": insights,
        "tables": {
            "families": fam_rows,
            "tiers": [{"x": x, "y": y, "std": h}
                      for x, y, h in zip(tier_x, tier_y, tier_hl)],
            "mix": [{"family": fams[i],
                     "cells": [mix[b][i] for b in BANDS]} for i in range(len(fams))],
            "kinds": [{"name": a, "count": b, "median": _int(c)}
                      for a, b, c in zip(kind_names, kind_counts, kind_med)],
            "lookup": lookup,
        },
        "labels": {
            "lede": summary,
            "items_kpi": "סעיפי אגרה בלוח",
            "subjects_kpi": "נושאי תביעה",
            "standard_kpi": f"התעריף הנפוץ (₪) — {_int(std_n)} סעיפים",
            "max_kpi": "האגרה הגבוהה ביותר (₪)",
            "free_kpi": f"סעיפים ללא אגרה ({_pct(n_free / n) if n else '0%'})",
            "median_kpi": "חציון האגרות בתשלום (₪)",
            "lookup_note": (f"{_int(n)} סעיפי האגרה מקובצים ב-{_int(len(fams))} תחומים "
                            "לפי נושא התביעה. פתחו תחום כדי לראות את האגרה לכל "
                            "בקשה; אגרת פתיחת התיק מופיעה ראשונה בכל נושא. "
                            "הסכומים בשקלים חדשים."),
            "tiers_note": (f"הלוח בנוי ממספר קטן של מדרגות קבועות: {_int(len(tiers))} "
                           f"סכומים שונים בלבד. המדרגה הבולטת, {_ils(std or 0)}, "
                           f"מסומנת בצבע ({_int(std_n)} סעיפים)."
                           + (" הסכומים מקובצים לטווחים." if tier_binned else "")),
            "tiers_aria": (f"תרשים עמודות: מספר סעיפי האגרה בכל סכום, {_int(len(tiers))} "
                           f"סכומים שונים. הנפוץ ביותר {_ils(std or 0)} עם {_int(std_n)} סעיפים."),
            "families_note": (f"טווח האגרות בכל תחום: הקופסה מקיפה את חצי הסעיפים "
                              f"האמצעי, והקו שבתוכה הוא החציון. התחום הגדול ביותר "
                              f"הוא {top_fam['family']} עם {_int(top_fam['n_items'])} סעיפים."
                              if top_fam else ""),
            "families_aria": (f"תרשים קופסה: טווח האגרות ב-{_int(len(fams))} תחומי "
                              f"הליך, מ-0 ₪ ועד {_ils(mx)}."),
            "mix_note": ((f"כמה מסעיפי כל תחום פטורים, זולים מהתעריף הנפוץ ({_ils(std)}), "
                          f"שווים לו או יקרים ממנו. התעריף הנפוץ שולט בתחום "
                          f"{mix_lead[1]} ({_pct(mix_lead[0])} מהסעיפים).")
                         if mix_lead else "כמה מסעיפי כל תחום פטורים, זולים, שווים או יקרים מהתעריף הנפוץ."),
            "mix_aria": (f"תרשים עמודות מוערמות: חלוקת סעיפי האגרה ב-{_int(len(fams))} "
                         f"תחומים לפי רמת האגרה ביחס לתעריף הנפוץ ({_ils(std or 0)})."),
            "kinds_note": (f"\"{OPEN_FEE}\" היא סוג האגרה הנפוץ ביותר — {_int(open_n)} "
                           f"מתוך {_int(n)} סעיפים ({_pct(open_n / n) if n else '0%'}). "
                           + (f"מוצגים {_int(len(top_k))} סוגי האגרה הנפוצים; שאר "
                              f"{_int(n_rest_kinds)} הסוגים מקובצים ב\"אגרות אחרות\"."
                              if n_rest_kinds else "")),
            "kinds_aria": (f"תרשים עמודות: מספר הסעיפים לפי סוג האגרה. הנפוץ: "
                           f"{kind_names[0] if kind_names else ''} עם "
                           f"{_int(kind_counts[0]) if kind_counts else '0'} סעיפים."),
        },
    }
