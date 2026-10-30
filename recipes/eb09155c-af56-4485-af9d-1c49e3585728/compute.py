"""כמות כלי רכב חשמליים לפי נפה — Ministry of Transport.

One snapshot table (~90 rows): ownership type (baalut: פרטי / חברה / ליסינג /
סוחר / השכרה), district (mahoz_nm), sub-district (nafa_nm) and the number of
active electric vehicles (car_num) in that cell. Some rows carry an empty
district and/or nafa: they are counted in every total and shown as a
"לא צוין" bucket, never silently dropped.

The data is replaced in place (a new snapshot, same resource). New ownership
types and new nafot flow through: nothing below hardcodes a category list.
Every number on the page is computed here.
"""
import pandas as pd

UNKNOWN = "לא צוין"
PRIVATE = "פרטי"
TOP_NAFOT = 30          # nafa axis cap (Israel has ~22 + J&S); the rest -> "נפות אחרות"
OTHER_NAFOT = "נפות אחרות"
FLEET_MIN_CARS = 1000   # nafot below this are too small for a stable ownership-mix rate
CONC_TOP = 3            # "top-3 nafot hold X% of type T"
CONC_MIN_CARS = 1000    # only rate concentration of a type with at least this many cars


def _int(n):
    return f"{int(round(n)):,}"


def _pct(x, d=1):
    return f"{x * 100:.{d}f}%"


def _ranked(series):
    """Sort by value desc, ties broken by label (total, order-independent)."""
    return series.sort_index(kind="stable").sort_values(ascending=False, kind="stable")


def _prepare(df):
    df = df.copy()
    df["owner"] = df["baalut"].astype(str).str.strip().replace("", UNKNOWN)
    df["district"] = df["mahoz_nm"].astype(str).str.strip()
    df["nafa"] = df["nafa_nm"].astype(str).str.strip()
    df["n"] = pd.to_numeric(df["car_num"].astype(str).str.replace(",", "").str.strip(),
                            errors="coerce")
    df = df.dropna(subset=["n"])
    df = df[df["n"] >= 0]
    return df


# Hebrew phrase "held as <type>" per known ownership code; unknown codes fall
# back to the generic "בבעלות <code>" so new types still read correctly.
OWNER_PHRASE = {
    "פרטי": "בבעלות פרטית",
    "חברה": "בבעלות חברה",
    "ליסינג": "בליסינג",
    "סוחר": "בבעלות סוחר",
    "השכרה": "בבעלות חברת השכרה",
}


def _own(o):
    return OWNER_PHRASE.get(o, f"בבעלות {o}")


def _dist(d):
    """'מחוז X', except names that are already a region noun (אזור …)."""
    return d if d.startswith("אזור") or d == UNKNOWN else f"מחוז {d}"


def _in_nafot(k):
    """ "in k nafot" with the Hebrew feminine number word."""
    words = {1: "בנפה אחת", 2: "בשתי נפות", 3: "בשלוש נפות", 4: "בארבע נפות", 5: "בחמש נפות"}
    return words.get(k, f"ב-{_int(k)} נפות")


def _join(names):
    names = list(names)
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " ו" + names[-1]


# ── insight rules ────────────────────────────────────────────────────────────

def insight_top_nafa(nafa_tot, total):
    if len(nafa_tot) < 2 or total == 0:
        return None
    (n1, v1), (n2, v2) = list(nafa_tot.items())[:2]
    s1 = v1 / total
    if s1 < 0.08:
        return None
    gap = (v1 - v2) / v2 if v2 else None
    tail = ""
    if gap is not None and gap < 0.1:
        tail = f", ובצמוד אליה נפת {n2} עם {_int(v2)}"
    else:
        tail = f", לפני נפת {n2} ({_int(v2)})"
    return (f"נפת {n1} מובילה עם {_int(v1)} רכבים חשמליים פעילים, "
            f"{_pct(s1)} מכלל הרכבים במאגר{tail}.")


def insight_concentration(nafa_tot, total):
    k = 5
    if len(nafa_tot) <= k or total == 0:
        return None
    top = nafa_tot.iloc[:k]
    share = top.sum() / total
    if share < 0.3:
        return None
    return (f"חמש הנפות הגדולות ({_join(top.index)}) מרכזות {_pct(share)} "
            f"מהרכבים החשמליים, מתוך {len(nafa_tot)} נפות במאגר.")


def insight_private_leader(nafa_tot, nafa_priv):
    if nafa_tot.empty or nafa_priv.empty:
        return None
    t_lead, p_lead = nafa_tot.index[0], nafa_priv.index[0]
    p_val = nafa_priv.iloc[0]
    if t_lead == p_lead:
        if len(nafa_priv) < 2:
            return None
        n2, v2 = nafa_priv.index[1], nafa_priv.iloc[1]
        return (f"נפת {p_lead} מובילה גם ברכבים חשמליים בבעלות פרטית: {_int(p_val)} רכבים, "
                f"לעומת {_int(v2)} בנפת {n2} שבמקום השני.")
    t_priv = int(nafa_priv.get(t_lead, 0))
    return (f"בבעלות פרטית מובילה נפת {p_lead} עם {_int(p_val)} רכבים, אף שבסך הכול "
            f"מובילה נפת {t_lead}, שבה רק {_int(t_priv)} מהרכבים בבעלות פרטית.")


def insight_owner_concentration(conc):
    """The non-private ownership type whose cars sit most in a few nafot."""
    cand = [c for c in conc if c["owner"] != PRIVATE and c["total"] >= CONC_MIN_CARS]
    if not cand:
        return None
    best = cand[0]
    for c in cand[1:]:
        if c["share"] > best["share"]:
            best = c
    if best["share"] < 0.6:
        return None
    priv = next((c for c in conc if c["owner"] == PRIVATE), None)
    tail = ""
    if priv is not None:
        tail = f", לעומת {_pct(priv['share'])} בלבד מהרכבים הפרטיים"
    return (f"רכבים {_own(best['owner'])} מרוכזים מאוד: {_pct(best['share'])} מתוך "
            f"{_int(best['total'])} רכבים כאלה רשומים {_in_nafot(len(best['top']))} ({_join(best['top'])}){tail}.")


def insight_fleet_heavy(fleet_rows, national_np):
    if not fleet_rows or national_np <= 0:
        return None
    heavy = [r for r in fleet_rows if r["np"] >= 2 * national_np]
    if not heavy:
        return None
    heavy = heavy[:3]
    parts = [f"{r['name']} ({_pct(r['np'])})" for r in heavy]
    word = "בנפות" if len(parts) > 1 else "בנפת"
    return (f"{word} {_join(parts)} שיעור הרכבים שאינם בבעלות פרטית גבוה לפחות פי שניים "
            f"מהממוצע הארצי ({_pct(national_np)}). ייתכן שהדבר משקף את כתובת הרישום של "
            f"החברות הבעלים, ולא בהכרח את מקום השימוש ברכב.")


def insight_private_share(owner_tot, total):
    if total == 0 or PRIVATE not in owner_tot.index:
        return None
    s = owner_tot[PRIVATE] / total
    second = [(k, v) for k, v in owner_tot.items() if k != PRIVATE]
    tail = ""
    if second:
        k2, v2 = second[0]
        tail = f"; אחריהם רכבים {_own(k2)}: {_int(v2)} ({_pct(v2 / total)})"
    if s >= 0.5:
        return f"{_pct(s)} מהרכבים החשמליים הפעילים ({_int(owner_tot[PRIVATE])}) הם בבעלות פרטית{tail}."
    return f"רק {_pct(s)} מהרכבים החשמליים הפעילים הם בבעלות פרטית{tail}."


def insight_district(dist_tot, total):
    if len(dist_tot) < 2 or total == 0:
        return None
    (d1, v1), (d2, v2) = list(dist_tot.items())[:2]
    if v2 == 0:
        return None
    ratio = v1 / v2
    if ratio < 1.5:
        return (f"{_dist(d1)} מוביל עם {_int(v1)} רכבים ({_pct(v1 / total)}), "
                f"ו{_dist(d2)} קרוב אליו עם {_int(v2)}.")
    return (f"{_dist(d1)} לבדו מחזיק {_int(v1)} רכבים חשמליים ({_pct(v1 / total)}), "
            f"פי {ratio:.1f} מ{_dist(d2)} שבמקום השני.")


def insight_unknown(unknown_nafa, total):
    if unknown_nafa <= 0 or total == 0:
        return None
    return (f"{_int(unknown_nafa)} רכבים ({_pct(unknown_nafa / total, 2)}) רשומים ללא נפה. "
            f"הם נכללים בכל הסכומים ומופיעים בתרשימים תחת \"{UNKNOWN}\".")


# ── main ─────────────────────────────────────────────────────────────────────

def compute(frames):
    df = _prepare(frames["main"])
    total = int(df["n"].sum())

    owner_tot = _ranked(df.groupby("owner")["n"].sum())
    owners = list(owner_tot.index)

    known = df[df["nafa"] != ""]
    unknown_nafa = int(df.loc[df["nafa"] == "", "n"].sum())
    nafa_tot = _ranked(known.groupby("nafa")["n"].sum())
    nafa_priv = _ranked(known[known["owner"] == PRIVATE].groupby("nafa")["n"].sum())
    nafa_district = (known.groupby("nafa")["district"]
                     .agg(lambda s: sorted(v for v in set(s) if v)[0] if any(s) else UNKNOWN))
    pivot = (df.assign(nafa_l=df["nafa"].where(df["nafa"] != "", UNKNOWN))
             .pivot_table(index="nafa_l", columns="owner", values="n",
                          aggfunc="sum", fill_value=0))

    knownd = df[df["district"] != ""]
    unknown_dist = int(df.loc[df["district"] == "", "n"].sum())
    dist_tot = _ranked(knownd.groupby("district")["n"].sum())
    dpivot = knownd.pivot_table(index="district", columns="owner", values="n",
                                aggfunc="sum", fill_value=0)

    # ── nafa axis (top-N + other + unknown) ──
    shown = list(nafa_tot.index[:TOP_NAFOT])
    rest = list(nafa_tot.index[TOP_NAFOT:])
    axis = list(shown)
    if rest:
        axis.append(OTHER_NAFOT)
    if unknown_nafa > 0:
        axis.append(UNKNOWN)

    def nafa_row(label):
        if label == OTHER_NAFOT:
            sub = pivot.loc[rest]
            return {o: int(sub[o].sum()) if o in sub else 0 for o in owners}
        return {o: int(pivot.at[label, o]) if o in pivot.columns else 0 for o in owners}

    rows = {lab: nafa_row(lab) for lab in axis}
    nafot_chart = {
        "names": axis,
        "owners": owners,
        "series": [[rows[lab][o] for lab in axis] for o in owners],
        "totals": [sum(rows[lab].values()) for lab in axis],
    }
    nafot_table = [{"name": lab,
                    "district": (nafa_district.get(lab, "") if lab in nafa_tot.index else ""),
                    "total": sum(rows[lab].values()),
                    "private": rows[lab].get(PRIVATE, 0),
                    "share": _pct(sum(rows[lab].values()) / total) if total else "0.0%"}
                   for lab in axis]

    # ── districts ──
    d_axis = list(dist_tot.index) + ([UNKNOWN] if unknown_dist > 0 else [])
    d_vals = [int(dist_tot[d]) for d in dist_tot.index] + ([unknown_dist] if unknown_dist > 0 else [])
    d_nafot = known.groupby("district")["nafa"].nunique()
    districts_chart = {"names": d_axis, "values": d_vals,
                       "shares": [round(v / total * 100, 1) if total else 0 for v in d_vals]}
    districts_table = [{"name": d, "total": v, "share": _pct(v / total) if total else "0.0%",
                        "nafot": int(d_nafot.get(d, 0))}
                       for d, v in zip(d_axis, d_vals)]

    # ── ownership donut ──
    owner_chart = {"names": owners, "values": [int(v) for v in owner_tot],
                   "shares": [round(v / total * 100, 1) if total else 0 for v in owner_tot]}
    owner_table = [{"name": o, "total": int(v), "share": _pct(v / total) if total else "0.0%"}
                   for o, v in owner_tot.items()]

    # ── ownership mix per district (100%) ──
    mix_names = list(dist_tot.index)
    mix_series = []
    for o in owners:
        vals = []
        for d in mix_names:
            dt = float(dist_tot[d])
            v = float(dpivot.at[d, o]) if o in dpivot.columns else 0.0
            vals.append(round(v / dt * 100, 1) if dt else 0)
        mix_series.append(vals)
    mix_chart = {"names": mix_names, "owners": owners, "series": mix_series}
    mix_table = [{"name": d, "cells": [f"{mix_series[i][j]:.1f}%" for i in range(len(owners))]}
                 for j, d in enumerate(mix_names)]
    national_np = (1 - owner_tot.get(PRIVATE, 0) / total) if total else 0.0
    nonpriv_by_district = []
    for d in mix_names:
        dt = float(dist_tot[d])
        p = float(dpivot.at[d, PRIVATE]) if PRIVATE in dpivot.columns else 0.0
        nonpriv_by_district.append((d, 1 - p / dt if dt else 0.0))

    # ── heatmap: share of each ownership type within each nafa ──
    heat_names = list(nafa_tot.index)
    cells = []
    for yi, nf in enumerate(heat_names):
        nt = float(nafa_tot[nf])
        for xi, o in enumerate(owners):
            v = int(pivot.at[nf, o]) if o in pivot.columns else 0
            cells.append([xi, yi, round(v / nt * 100, 1) if nt else 0, v])
    heat_chart = {"names": heat_names, "owners": owners, "cells": cells}

    # ── pareto ──
    cum, acc = [], 0
    for v in nafa_tot:
        acc += v
        cum.append(round(acc / total * 100, 1) if total else 0)
    pareto_chart = {"names": list(nafa_tot.index), "values": [int(v) for v in nafa_tot], "cum": cum}
    pareto_table = [{"rank": i + 1, "name": n, "total": int(v), "cum": f"{c:.1f}%"}
                    for i, (n, v, c) in enumerate(zip(nafa_tot.index, nafa_tot, cum))]
    half_k = next((i + 1 for i, c in enumerate(cum) if c >= 50), len(cum))

    # ── non-private share per nafa (nafot ≥ FLEET_MIN_CARS) ──
    fleet_rows = []
    for nf, v in nafa_tot.items():
        if v < FLEET_MIN_CARS:
            continue
        p = float(pivot.at[nf, PRIVATE]) if PRIVATE in pivot.columns else 0.0
        fleet_rows.append({"name": nf, "total": int(v), "np": 1 - p / v, "nonpriv": int(v - p)})
    fleet_rows.sort(key=lambda r: (-r["np"], r["name"]))
    fleet_chart = {"names": [r["name"] for r in fleet_rows],
                   "values": [round(r["np"] * 100, 1) for r in fleet_rows],
                   "nonpriv": [r["nonpriv"] for r in fleet_rows],
                   "totals": [r["total"] for r in fleet_rows],
                   "national": round(national_np * 100, 1),
                   "heavy": [bool(r["np"] >= 2 * national_np) for r in fleet_rows]}
    fleet_table = [{"name": r["name"], "total": r["total"], "nonpriv": r["nonpriv"],
                    "share": _pct(r["np"])} for r in fleet_rows]
    small_nafot = int((nafa_tot < FLEET_MIN_CARS).sum())

    # ── concentration of each ownership type in its top-3 nafot ──
    conc = []
    for o in owners:
        s = (_ranked(known[known["owner"] == o].groupby("nafa")["n"].sum())
             if o in set(known["owner"]) else pd.Series(dtype=float))
        ot = float(owner_tot[o])
        top = s.iloc[:CONC_TOP]
        conc.append({"owner": o, "total": int(ot),
                     "share": float(top.sum() / ot) if ot else 0.0,
                     "top": list(top.index), "n_nafot": int((s > 0).sum())})
    conc_chart = {"names": [c["owner"] for c in conc],
                  "values": [round(c["share"] * 100, 1) for c in conc],
                  "tops": [" / ".join(c["top"]) for c in conc],
                  "totals": [c["total"] for c in conc]}
    conc_table = [{"name": c["owner"], "total": c["total"], "share": _pct(c["share"]),
                   "top": ", ".join(c["top"]),
                   "n_nafot": c["n_nafot"]} for c in conc]

    # ── insights ──
    rules = [
        ("top_nafa", insight_top_nafa(nafa_tot, total)),
        ("private_share", insight_private_share(owner_tot, total)),
        ("private_leader", insight_private_leader(nafa_tot, nafa_priv)),
        ("concentration", insight_concentration(nafa_tot, total)),
        ("owner_concentration", insight_owner_concentration(conc)),
        ("fleet_heavy", insight_fleet_heavy(fleet_rows, national_np)),
        ("district", insight_district(dist_tot, total)),
        ("unknown", insight_unknown(unknown_nafa, total)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    top_name = nafa_tot.index[0] if len(nafa_tot) else UNKNOWN
    top_val = int(nafa_tot.iloc[0]) if len(nafa_tot) else 0
    top_share = top_val / total if total else 0.0
    priv_share = owner_tot.get(PRIVATE, 0) / total if total else 0.0
    n_nafot = int(len(nafa_tot))
    n_dist = int(len(dist_tot))

    summary = (f"כמה רכבים חשמליים יש בכל נפה? {_int(total)} רכבים חשמליים פעילים "
               f"ב-{n_nafot} נפות, לפי סוג בעלות. נפת {top_name} מובילה עם {_int(top_val)}.")
    if len(summary) > 155:
        summary = f"רכבים חשמליים פעילים לפי נפה ובעלות: {_int(total)} רכבים ב-{n_nafot} נפות."

    np_top_d = max(nonpriv_by_district, key=lambda t: (t[1], t[0])) if nonpriv_by_district else (UNKNOWN, 0)
    np_low_d = min(nonpriv_by_district, key=lambda t: (t[1], t[0])) if nonpriv_by_district else (UNKNOWN, 0)
    second_owner = owners[1] if len(owners) > 1 else (owners[0] if owners else UNKNOWN)
    heavy_names = [r["name"] for r in fleet_rows if r["np"] >= 2 * national_np]
    conc_np = [c for c in conc if c["owner"] != PRIVATE and c["total"] >= CONC_MIN_CARS]
    conc_max = max(conc_np, key=lambda c: (c["share"], c["owner"])) if conc_np else None
    conc_priv = next((c for c in conc if c["owner"] == PRIVATE), None)

    labels = {
        "lede": (f"מאגר משרד התחבורה מונה {_int(total)} כלי רכב חשמליים פעילים בישראל, "
                 f"מפולחים לפי {n_dist} מחוזות, {n_nafot} נפות וסוג הבעלות "
                 f"({_join(owners)}). {_pct(priv_share)} מהם בבעלות פרטית, ונפת {top_name} "
                 f"היא הגדולה ביותר עם {_pct(top_share)} מכלל הרכבים. "
                 f"העמוד מציג כמה רכבים חשמליים יש בכל נפה ובכל מחוז, ומי מחזיק בהם."),
        "total_kpi": "רכבים חשמליים פעילים",
        "nafot_kpi": "נפות במאגר",
        "districts_kpi": "מחוזות",
        "private_kpi": "בבעלות פרטית",
        "fleet_kpi": "שאינם בבעלות פרטית (חברה, ליסינג ועוד)",
        "top_kpi": f"חלקה של נפת {top_name}, הגדולה ביותר",
        "nafot_note": (f"הנפות מדורגות לפי סך הרכבים החשמליים, וכל עמודה מחולקת לפי סוג הבעלות. "
                       f"נפת {top_name} מובילה עם {_int(top_val)} רכבים."
                       + (f" {_int(unknown_nafa)} רכבים ללא נפה מוצגים בסוף, תחת \"{UNKNOWN}\"."
                          if unknown_nafa > 0 else "")
                       + (f" נפות שמעבר ל-{TOP_NAFOT} הגדולות מאוחדות תחת \"{OTHER_NAFOT}\"."
                          if rest else "")),
        "nafot_aria": (f"תרשים עמודות אופקי מוערם: רכבים חשמליים לפי נפה וסוג בעלות. "
                       f"נפת {top_name} מובילה עם {_int(top_val)} רכבים."),
        "dist_note": (f"{_dist(dist_tot.index[0])} מחזיק {_pct(dist_tot.iloc[0] / total)} מהרכבים."
                      if len(dist_tot) else "")
                     + (f" {_int(unknown_dist)} רכבים ללא מחוז מוצגים תחת \"{UNKNOWN}\"."
                        if unknown_dist > 0 else ""),
        "dist_aria": (f"תרשים עמודות: רכבים חשמליים לפי מחוז. {_dist(dist_tot.index[0])} מוביל "
                      f"עם {_int(dist_tot.iloc[0])} רכבים." if len(dist_tot) else
                      "תרשים עמודות: רכבים חשמליים לפי מחוז."),
        "owner_note": (f"{_pct(owner_tot.iloc[0] / total)} מהרכבים {_own(owners[0])}, "
                       f"ואחריהם {_pct(owner_tot[second_owner] / total)} {_own(second_owner)}."
                       if len(owners) > 1 and total else ""),
        "owner_aria": (f"תרשים טבעת: התפלגות הרכבים החשמליים לפי סוג בעלות. "
                       f"{_pct(owner_tot.iloc[0] / total)} {_own(owners[0])}." if owners and total
                       else "תרשים טבעת: התפלגות הרכבים החשמליים לפי סוג בעלות."),
        "mix_note": (f"חלקו של כל סוג בעלות בתוך כל מחוז. השיעור הגבוה ביותר של רכבים שאינם "
                     f"בבעלות פרטית נמצא ב{_dist(np_top_d[0])} ({_pct(np_top_d[1])}), "
                     f"והנמוך ביותר ב{_dist(np_low_d[0])} ({_pct(np_low_d[1])})."
                     + (f" רכבים ללא מחוז אינם נכללים בתרשים זה." if unknown_dist > 0 else "")),
        "mix_aria": (f"תרשים עמודות מוערם באחוזים: הרכב הבעלות בכל מחוז. ב{_dist(np_top_d[0])} "
                     f"{_pct(np_top_d[1])} מהרכבים אינם בבעלות פרטית."),
        "heat_note": (f"כל תא מראה איזה חלק מהרכבים בנפה שייך לכל סוג בעלות (הצבע לפי האחוז, "
                      f"המספר המלא בחלון המידע). רוב הנפות כמעט פרטיות לגמרי, וחריגות בולטות "
                      f"מופיעות כתאים כהים בעמודות שאינן פרטיות."
                      + (f" רכבים ללא נפה אינם נכללים." if unknown_nafa > 0 else "")),
        "heat_aria": (f"מפת חום: שיעור כל סוג בעלות מתוך הרכבים החשמליים בכל אחת "
                      f"מ-{n_nafot} הנפות."),
        "pareto_note": (f"העמודות הן מספר הרכבים בכל נפה, והקו הוא החלק המצטבר מכלל הרכבים. "
                        f"{half_k} הנפות הגדולות מרכזות יחד מחצית מהרכבים החשמליים או יותר."),
        "pareto_aria": (f"תרשים פארטו: ריכוז הרכבים החשמליים בנפות. {half_k} נפות מרכזות "
                        f"מחצית מהרכבים."),
        "fleet_note": (f"שיעור הרכבים שבבעלות חברה, ליסינג, סוחר או השכרה בכל נפה, בנפות עם "
                       f"{_int(FLEET_MIN_CARS)} רכבים לפחות ({small_nafot} נפות קטנות יותר אינן "
                       f"מוצגות). הקו המקווקו הוא הממוצע הארצי, {_pct(national_np)}."
                       + (f" נפות בצבע כהה ({_join(heavy_names)}) עוברות פי שניים מהממוצע."
                          if heavy_names else "")),
        "fleet_aria": (f"תרשים עמודות אופקי: שיעור הרכבים שאינם בבעלות פרטית בכל נפה. "
                       f"הממוצע הארצי {_pct(national_np)}"
                       + (f", והגבוה ביותר בנפת {fleet_rows[0]['name']} ({_pct(fleet_rows[0]['np'])})."
                          if fleet_rows else ".")),
        "conc_note": (f"איזה חלק מכל סוג בעלות רשום בשלוש הנפות שבהן הוא נפוץ ביותר."
                      + (f" הרכבים {_own(conc_max['owner'])} הם המרוכזים ביותר (מבין סוגי בעלות עם "
                         f"{_int(CONC_MIN_CARS)} רכבים לפחות): {_pct(conc_max['share'])} מהם {_in_nafot(len(conc_max['top']))}"
                         if conc_max else "")
                      + (f", לעומת {_pct(conc_priv['share'])} מהרכבים הפרטיים." if conc_max and conc_priv
                         else ("." if conc_max else ""))),
        "conc_aria": (f"תרשים עמודות: החלק של כל סוג בעלות שרשום בשלוש הנפות המובילות שלו."
                      + (f" רכבים {_own(conc_max['owner'])}: {_pct(conc_max['share'])}." if conc_max else "")),
    }

    kpis = {
        "total": {"value": total, "display": _int(total), "tone": "brand"},
        "nafot": {"value": n_nafot, "display": _int(n_nafot), "tone": "brand"},
        "districts": {"value": n_dist, "display": _int(n_dist), "tone": "brand"},
        "private": {"value": round(priv_share, 4), "display": _pct(priv_share), "tone": "info"},
        "fleet": {"value": round(national_np, 4), "display": _pct(national_np), "tone": "brand"},
        "top": {"value": round(top_share, 4), "display": _pct(top_share), "tone": "brand"},
    }

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "rankings",
            "suggested_tags": ["רכב חשמלי", "כלי רכב", "תחבורה", "נפות", "בעלות על רכב"],
            "related_ids": [
                "273c5e33-25ab-4980-8522-a2f7ba0bb62d",
                "392abd0a-64f6-4c18-9d56-0111001411e6",
                "0f16b39a-6016-408d-805d-31f40d5a0990",
                "11369651-1c70-4d8f-8090-ee49354a7c52",
            ],
            "spatial_coverage": "ישראל ואזור יהודה ושומרון, לפי נפה",
        },
        "kpis": kpis,
        "charts": {
            "nafot": nafot_chart,
            "districts": districts_chart,
            "owner": owner_chart,
            "mix": mix_chart,
            "heat": heat_chart,
            "pareto": pareto_chart,
            "fleet": fleet_chart,
            "conc": conc_chart,
        },
        "tables": {
            "nafot": nafot_table,
            "districts": districts_table,
            "owner": owner_table,
            "mix": mix_table,
            "pareto": pareto_table,
            "fleet": fleet_table,
            "conc": conc_table,
        },
        "flags": {"fleet": bool(fleet_rows), "heat": bool(heat_names)},
        "insights": insights,
        "labels": labels,
    }
