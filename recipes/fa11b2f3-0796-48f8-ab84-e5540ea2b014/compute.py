"""מאגר כוח אדם ברשויות הרווחה — welfare-department staffing standards.

One row per (authority, standard type) allocation of positions co-funded by
the Ministry of Social Affairs: how many standards (FTE, fractional), how many
are filled, how many vacant, and which part are social-worker standards. Rows
are allocations, not people — no individual appears in the data.

The file is a snapshot that is replaced wholesale on each update, so there is
no time axis; growth means new authorities / standard types / districts, which
flow through (top-N + "אחר" caps keep every chart mobile-sized).

All FTE arithmetic is done in integer hundredths (the source carries at most
two decimals) so sums are exact and independent of row order.
"""
import pandas as pd

TOP_ROLES = 15
HEAT_ROLES = 10
TOP_AUTH = 15
LOW_AUTH = 12
LOW_ROLES = 12
MIN_AUTH_FTE = 10        # authorities below this size are too small for a rate ranking
MIN_ROLE_FTE = 30        # standard types below this size are too small for a rate ranking
ROLE_GAP_PP = 15         # "low-staffed" standard type: this many points below the overall rate
RATE_BINS = [(0, 60), (60, 70), (70, 80), (80, 90), (90, 100), (100, None)]
TYPE_ORDER = ["עירייה", "מועצה מקומית", "מועצה אזורית", "אחר"]


def fte(h):
    """Hundredths → display string with one decimal and thousands separators."""
    return f"{h / 100:,.1f}"


def fte0(h):
    return f"{round(h / 100):,}"


def pct(num, den, digits=1):
    return f"{num / den * 100:.{digits}f}%" if den else "—"


def rate(num, den):
    return round(num / den * 100, 1) if den else None


def _h(s):
    v = pd.to_numeric(s.str.replace(",", "", regex=False).str.strip(), errors="coerce")
    return (v.fillna(0) * 100).round().astype("int64")


def auth_type(name):
    s = name.replace(" ", "")
    if s.startswith("ע."):
        return "עירייה"
    if s.startswith("מ.מ"):
        return "מועצה מקומית"
    if s.startswith("מ.א"):
        return "מועצה אזורית"
    return "אחר"


def _prepare(raw):
    df = pd.DataFrame({
        "district": raw["מחוז"].str.strip().replace("", "לא ידוע"),
        "auth": raw["רשות"].str.strip().replace("", "לא ידוע"),
        "role": raw["שם תקן"].str.strip().replace("", "לא ידוע"),
        "tot": _h(raw["מספר תקנים"]),
        "fil": _h(raw["תקן מאויש"]),
        "vac": _h(raw["פנוי"]),
        "sw": _h(raw["מתוכם עוס"]),
        "swf": _h(raw["עוסים מתוך המאויישים"]),
    })
    df = df[df["tot"] > 0].copy()
    df["atype"] = df["auth"].map(auth_type)
    return df


def _agg(df, keys):
    g = df.groupby(keys, sort=True)[["tot", "fil", "vac", "sw", "swf"]].sum().reset_index()
    g["rate"] = g["fil"] / g["tot"]
    return g


def _sorted(g, col, asc, name_cols):
    return g.sort_values([col] + name_cols, ascending=[asc] + [True] * len(name_cols),
                         kind="mergesort").reset_index(drop=True)


# ── insight rules ────────────────────────────────────────────────────────────

def insight_overall(tot, fil, vac, n_auth):
    return (f"בסך הכול {fte0(tot)} תקנים בהשתתפות המשרד ב-{n_auth:,} רשויות רווחה; "
            f"{pct(fil, tot)} מהם מאוישים, ו-{fte0(vac)} תקנים פנויים.")


def insight_district(dist):
    if len(dist) < 2:
        return None
    d = _sorted(dist, "rate", True, ["district"])
    lo, hi = d.iloc[0], d.iloc[-1]
    gap = (hi["rate"] - lo["rate"]) * 100
    if gap < 3:
        return (f"שיעור האיוש דומה בכל המחוזות — בין {pct(lo['fil'], lo['tot'])} "
                f"ל-{pct(hi['fil'], hi['tot'])}.")
    return (f"מחוז {lo['district']} בעל שיעור האיוש הנמוך ביותר ({pct(lo['fil'], lo['tot'])}), "
            f"ומחוז {hi['district']} מוביל ({pct(hi['fil'], hi['tot'])}) — פער של "
            f"{gap:.1f} נקודות אחוז.")


def insight_sw(sw, swf, ns, nsf):
    if sw == 0 or ns == 0:
        return None
    a, b = swf / sw * 100, nsf / ns * 100
    share = sw / (sw + ns) * 100
    head = f"תקני עובדים סוציאליים הם {share:.1f}% מכלל התקנים"
    if abs(a - b) < 2:
        return f"{head}, ושיעור האיוש שלהם ({a:.1f}%) דומה לזה של שאר התקנים ({b:.1f}%)."
    word = "נמוך" if a < b else "גבוה"
    return (f"{head}; שיעור האיוש שלהם ({a:.1f}%) {word} משל שאר התקנים ({b:.1f}%), "
            f"ו-{fte0(sw - swf)} מהתקנים הפנויים הם תקני עו\"ס.")


def insight_role_gaps(roles, overall):
    big = roles[roles["tot"] >= MIN_ROLE_FTE * 100]
    low = _sorted(big[big["rate"] <= overall - ROLE_GAP_PP / 100], "rate", True, ["role"])
    if low.empty:
        return None
    parts = [f"{r.role} ({pct(r.fil, r.tot)})" for r in low.head(3).itertuples()]
    lead = "הנמוכים ביותר" if len(low) > 1 else "זהו"
    return (f"{len(low)} סוגי תקנים (מבין סוגים בהיקף {MIN_ROLE_FTE} תקנים לפחות) מאוישים "
            f"בשיעור נמוך ב-{ROLE_GAP_PP} נקודות אחוז ויותר מהממוצע; {lead}: {', '.join(parts)}.")


def insight_concentration(auth, vac_total, tot_total):
    if len(auth) < 20 or vac_total == 0:
        return None
    v = _sorted(auth, "vac", False, ["auth"]).head(10)
    vs, ts = v["vac"].sum() / vac_total, v["tot"].sum() / tot_total
    if vs < 0.15:
        return None
    lead = v.iloc[0]
    return (f"עשר הרשויות עם מספר התקנים הפנויים הגבוה ביותר מרכזות {vs * 100:.1f}% מכלל "
            f"התקנים הפנויים (ו-{ts * 100:.1f}% מכלל התקנים); בראשן {lead['auth']} "
            f"עם {fte(lead['vac'])} תקנים פנויים.")


def insight_low_auth(auth):
    elig = auth[auth["tot"] >= MIN_AUTH_FTE * 100]
    if len(elig) < 10:
        return None
    low = elig[elig["rate"] < 0.7]
    full = int((auth["vac"] == 0).sum())
    tail = f" מנגד, ב-{full} רשויות כל התקנים מאוישים." if full else ""
    if low.empty:
        return f"בכל הרשויות בהיקף {MIN_AUTH_FTE} תקנים ומעלה שיעור האיוש הוא 70% לפחות.{tail}"
    w = _sorted(low, "rate", True, ["auth"]).iloc[0]
    return (f"ב-{len(low)} מתוך {len(elig)} הרשויות בהיקף {MIN_AUTH_FTE} תקנים ומעלה פחות "
            f"מ-70% מהתקנים מאוישים; הנמוכה ביותר היא {w['auth']} ({pct(w['fil'], w['tot'])})."
            f"{tail}")


def insight_types(types):
    t = types[types["atype"] != "אחר"]
    if len(t) < 2:
        return None
    t = _sorted(t, "rate", True, ["atype"])
    lo, hi = t.iloc[0], t.iloc[-1]
    gap = (hi["rate"] - lo["rate"]) * 100
    if gap < 3:
        return None
    return (f"לפי סוג הרשות, שיעור האיוש הנמוך ביותר הוא בקבוצת \"{lo['atype']}\" "
            f"({pct(lo['fil'], lo['tot'])}) והגבוה ביותר בקבוצת \"{hi['atype']}\" "
            f"({pct(hi['fil'], hi['tot'])}) — פער של {gap:.1f} נקודות אחוז.")


def insight_empty(n_empty, h_empty, n_rows):
    if n_empty == 0 or n_empty / n_rows < 0.05:
        return None
    return (f"{n_empty:,} הקצאות תקן ({n_empty / n_rows * 100:.1f}% מהשורות במאגר) אינן "
            f"מאוישות כלל — {fte(h_empty)} תקנים שאיש אינו ממלא.")


def insight_biggest(auth, tot_total):
    if auth.empty:
        return None
    b = _sorted(auth, "tot", False, ["auth"]).iloc[0]
    share = b["tot"] / tot_total
    if share < 0.05:
        return None
    return (f"{b['auth']} היא רשות הרווחה הגדולה ביותר: {fte0(b['tot'])} תקנים, "
            f"{share * 100:.1f}% מכלל התקנים, בשיעור איוש של {pct(b['fil'], b['tot'])}.")


# ── compute ──────────────────────────────────────────────────────────────────

def _top_other(g, key, k, sort_col="tot"):
    g = _sorted(g, sort_col, False, [key])
    top = g.head(k)
    rest = g.iloc[k:]
    rows = [dict(name=r[key], tot=int(r["tot"]), fil=int(r["fil"]), vac=int(r["vac"]))
            for _, r in top.iterrows()]
    if len(rest):
        rows.append(dict(name="אחר", tot=int(rest["tot"].sum()), fil=int(rest["fil"].sum()),
                         vac=int(rest["vac"].sum())))
    return rows


def _rate_tone(r):
    if r >= 0.9:
        return "ok"
    if r >= 0.8:
        return "warn"
    return "danger"


def compute(frames):
    df = _prepare(frames["main"])
    tot, fil, vac = int(df["tot"].sum()), int(df["fil"].sum()), int(df["vac"].sum())
    sw, swf = int(df["sw"].sum()), int(df["swf"].sum())
    ns, nsf = tot - sw, fil - swf
    overall = fil / tot if tot else 0

    dist = _agg(df, ["district"])
    dist_order = _sorted(dist, "tot", False, ["district"])
    auth = _agg(df, ["auth", "district", "atype"])
    roles = _agg(df, ["role"])
    roles["n_auth"] = roles["role"].map(df.groupby("role")["auth"].nunique())
    types = _agg(df, ["atype"])
    types["n_auth"] = types["atype"].map(auth.groupby("atype").size())
    types["order"] = types["atype"].map({t: i for i, t in enumerate(TYPE_ORDER)})
    types = types.sort_values("order", kind="mergesort")

    # district: filled/vacant stacked + rate
    d_names = list(dist_order["district"])
    ch_district = {
        "names": d_names,
        "fil": [round(v / 100, 2) for v in dist_order["fil"]],
        "vac": [round(v / 100, 2) for v in dist_order["vac"]],
        "rate": [rate(f, t) for f, t in zip(dist_order["fil"], dist_order["tot"])],
    }
    # social-worker vs other standards, per district
    dsw = dist_order.assign(ns=dist_order["tot"] - dist_order["sw"],
                            nsf=dist_order["fil"] - dist_order["swf"])
    ch_sw = {
        "names": d_names + ["כלל המחוזות"],
        "sw": [rate(a, b) for a, b in zip(dsw["swf"], dsw["sw"])] + [rate(swf, sw)],
        "ns": [rate(a, b) for a, b in zip(dsw["nsf"], dsw["ns"])] + [rate(nsf, ns)],
    }
    # authority type
    ch_types = {
        "names": list(types["atype"]),
        "tot": [round(v / 100, 2) for v in types["tot"]],
        "rate": [rate(f, t) for f, t in zip(types["fil"], types["tot"])],
    }
    # roles: top by size, stacked
    role_rows = _top_other(roles, "role", TOP_ROLES)
    named = [r for r in role_rows if r["name"] != "אחר"]
    other = next((r for r in role_rows if r["name"] == "אחר"), None)
    ch_roles = {
        "names": [r["name"] for r in named],
        "fil": [round(r["fil"] / 100, 2) for r in named],
        "vac": [round(r["vac"] / 100, 2) for r in named],
    }
    # roles: lowest fill (size threshold)
    rl = _sorted(roles[roles["tot"] >= MIN_ROLE_FTE * 100], "rate", True, ["role"]).head(LOW_ROLES)
    ch_role_low = {
        "names": list(rl["role"]),
        "rate": [rate(f, t) for f, t in zip(rl["fil"], rl["tot"])],
        "overall": rate(fil, tot),
    }
    # heatmap: district × top roles fill rate
    heat_roles = [r["name"] for r in role_rows if r["name"] != "אחר"][:HEAT_ROLES]
    dr = _agg(df[df["role"].isin(heat_roles)], ["role", "district"])
    dr_idx = {(r.role, r.district): r for r in dr.itertuples()}
    cells, heat_table = [], []
    for yi, role in enumerate(heat_roles):
        row = []
        for xi, d in enumerate(d_names):
            r = dr_idx.get((role, d))
            if r is None:
                row.append("—")
                continue
            v = rate(r.fil, r.tot)
            cells.append([xi, yi, v, round(r.tot / 100, 2)])
            row.append(f"{v:.1f}%")
        heat_table.append({"role": role, "cells": row})
    heat_vals = [c[2] for c in cells] or [0, 100]
    ch_heat = {"x": d_names, "y": heat_roles, "cells": cells,
               "min": float(min(heat_vals)), "max": float(max(heat_vals))}
    # authorities: biggest
    at = _sorted(auth, "tot", False, ["auth"]).head(TOP_AUTH)
    ch_auth_top = {
        "names": list(at["auth"]),
        "fil": [round(v / 100, 2) for v in at["fil"]],
        "vac": [round(v / 100, 2) for v in at["vac"]],
    }
    # authorities: lowest fill
    al = _sorted(auth[auth["tot"] >= MIN_AUTH_FTE * 100], "rate", True, ["auth"]).head(LOW_AUTH)
    ch_auth_low = {
        "names": list(al["auth"]),
        "rate": [rate(f, t) for f, t in zip(al["fil"], al["tot"])],
        "overall": rate(fil, tot),
    }
    # distribution of authority fill rates, stacked by district
    r100 = (auth["fil"] * 100 / auth["tot"])
    bins = []
    for lo, hi in RATE_BINS:
        if hi is None:
            m = auth["fil"] >= auth["tot"]
            label = "100%"
        else:
            m = (r100 >= lo) & (r100 < hi) & (auth["fil"] < auth["tot"])
            label = f"{lo}% עד {hi}%" if lo else f"מתחת ל-{hi}%"
        bins.append((label, m))
    ch_hist = {
        "names": [b[0] for b in bins],
        "series": [{"name": d, "data": [int((m & (auth["district"] == d)).sum()) for _, m in bins]}
                   for d in d_names],
    }
    # scatter: size vs rate per authority
    ch_scatter = {"series": []}
    for d in d_names:
        sub = _sorted(auth[auth["district"] == d], "tot", False, ["auth"])
        ch_scatter["series"].append({
            "name": d,
            "data": [[round(t / 100, 2), rate(f, t), a] for t, f, a in
                     zip(sub["tot"], sub["fil"], sub["auth"])],
        })
    # allocation status (row level)
    full_m = df["fil"] >= df["tot"]
    empty_m = df["fil"] == 0
    part_m = ~full_m & ~empty_m
    status = [("מאוישת במלואה", full_m), ("מאוישת חלקית", part_m), ("לא מאוישת כלל", empty_m)]
    ch_status = {
        "names": [s for s, _ in status],
        "rows": [int(m.sum()) for _, m in status],
        "fte": [round(int(df.loc[m, "tot"].sum()) / 100, 2) for _, m in status],
    }
    n_rows = len(df)

    rules = [
        ("overall", insight_overall(tot, fil, vac, len(auth))),
        ("district", insight_district(dist)),
        ("sw", insight_sw(sw, swf, ns, nsf)),
        ("role_gaps", insight_role_gaps(roles, overall)),
        ("concentration", insight_concentration(auth, vac, tot)),
        ("low_auth", insight_low_auth(auth)),
        ("types", insight_types(types)),
        ("empty", insight_empty(int(empty_m.sum()), int(df.loc[empty_m, "tot"].sum()), n_rows)),
        ("biggest", insight_biggest(auth, tot)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    sw_rate = swf / sw if sw else 0
    kpis = {
        "total": {"value": round(tot / 100, 2), "display": fte0(tot), "tone": "brand"},
        "filled": {"value": round(fil / 100, 2), "display": fte0(fil), "tone": "brand"},
        "vacant": {"value": round(vac / 100, 2), "display": fte0(vac), "tone": _rate_tone(overall)},
        "rate": {"value": rate(fil, tot), "display": pct(fil, tot), "tone": _rate_tone(overall)},
        "sw_share": {"value": rate(sw, tot), "display": pct(sw, tot), "tone": "info"},
        "sw_rate": {"value": rate(swf, sw), "display": pct(swf, sw), "tone": _rate_tone(sw_rate)},
        "authorities": {"value": len(auth), "display": f"{len(auth):,}", "tone": "brand"},
        "roles": {"value": len(roles), "display": f"{len(roles):,}", "tone": "brand"},
    }

    dl = dist_order.iloc[0] if len(dist_order) else None
    big_role = role_rows[0] if role_rows else None
    labels = {
        "lede": (f"תקני כוח האדם במחלקות לשירותים חברתיים ברשויות המקומיות, בהשתתפות משרד "
                 f"הרווחה והביטחון החברתי: {fte0(tot)} תקנים ב-{len(auth):,} רשויות, "
                 f"{len(dist):,} מחוזות ו-{len(roles):,} סוגי תקנים. לכל הקצאה מצוין כמה "
                 f"תקנים מאוישים, כמה פנויים וכמה מהם תקני עובדים סוציאליים. שמות הרשויות "
                 f"כבמאגר: ע. — עירייה, מ.מ — מועצה מקומית, מ.א — מועצה אזורית. "
                 f"תקן יכול להיות חלקי (למשל חצי משרה), ולכן הסכומים אינם בהכרח שלמים."),
        "total_kpi": "תקנים בהשתתפות המשרד (משרות מלאות)",
        "filled_kpi": "תקנים מאוישים",
        "vacant_kpi": f"תקנים פנויים ({pct(vac, tot)} מהתקנים)",
        "rate_kpi": "שיעור האיוש הכולל",
        "sw_share_kpi": "מהתקנים הם תקני עובדים סוציאליים",
        "sw_rate_kpi": "שיעור האיוש בתקני עו\"ס",
        "auth_kpi": "רשויות רווחה",
        "roles_kpi": "סוגי תקנים",
        "district_note": (f"תקנים מאוישים ופנויים בכל מחוז, ושיעור האיוש (קו, ציר ימני). "
                          + (f"המחוז הגדול ביותר: {dl['district']}, עם {fte0(dl['tot'])} תקנים."
                             if dl is not None else "")),
        "district_aria": "גרף עמודות מוערמות: תקנים מאוישים ופנויים לפי מחוז, עם קו שיעור האיוש.",
        "district_caption": "תקנים, תקנים מאוישים, פנויים ושיעור איוש לפי מחוז.",
        "sw_note": (f"שיעור האיוש בתקני עובדים סוציאליים ({fte0(sw)} תקנים) לעומת שאר התקנים "
                    f"({fte0(ns)} — תחשיבנים, מדריכים, רכזים, מזכירות ועוד), בכל מחוז."),
        "sw_aria": "גרף עמודות: שיעור האיוש בתקני עו\"ס ובשאר התקנים, לפי מחוז.",
        "sw_caption": "שיעור איוש בתקני עו\"ס ובשאר התקנים לפי מחוז.",
        "types_note": ("סוג הרשות לפי שמה במאגר: עירייה, מועצה מקומית או מועצה אזורית — היקף "
                       "התקנים (עמודות) ושיעור האיוש (קו)."),
        "types_aria": "גרף עמודות וקו: היקף התקנים ושיעור האיוש לפי סוג רשות.",
        "types_caption": "רשויות, תקנים ושיעור איוש לפי סוג רשות.",
        "roles_note": (f"{len(named)} סוגי התקנים הגדולים, מאוישים ופנויים. "
                       + (f"שאר {len(roles) - len(named):,} הסוגים ({fte0(other['tot'])} תקנים, "
                          f"{pct(other['tot'], tot)}) מרוכזים בשורת \"אחר\" בטבלה ואינם בתרשים. "
                          if other else "")
                       + (f"הגדול ביותר: {big_role['name']}, עם {fte0(big_role['tot'])} תקנים "
                          f"({pct(big_role['tot'], tot)} מכלל התקנים)." if big_role else "")),
        "roles_aria": f"גרף עמודות אופקי מוערם: {TOP_ROLES} סוגי התקנים הגדולים, מאוישים ופנויים.",
        "roles_caption": "תקנים, מאוישים ופנויים לפי סוג תקן.",
        "role_low_note": (f"{LOW_ROLES} סוגי התקנים עם שיעור האיוש הנמוך ביותר, מבין סוגים "
                          f"בהיקף {MIN_ROLE_FTE} תקנים לפחות (ארצי). הקו המקווקו — שיעור "
                          f"האיוש הכולל ({pct(fil, tot)})."),
        "role_low_aria": f"גרף עמודות אופקי: {LOW_ROLES} סוגי התקנים עם שיעור האיוש הנמוך ביותר.",
        "role_low_caption": "שיעור איוש, תקנים ומספר רשויות לסוגי התקנים עם האיוש הנמוך ביותר.",
        "heat_note": (f"שיעור האיוש של {len(heat_roles)} סוגי התקנים הגדולים בכל מחוז. "
                      f"גוון כהה = איוש גבוה; בחלונית: גם היקף התקנים בתא."),
        "heat_aria": "מפת חום: שיעור האיוש לפי סוג תקן ומחוז.",
        "heat_caption": "שיעור איוש לפי סוג תקן ומחוז.",
        "auth_top_note": f"{TOP_AUTH} הרשויות עם מספר התקנים הגדול ביותר, מאוישים ופנויים.",
        "auth_top_aria": f"גרף עמודות אופקי מוערם: {TOP_AUTH} רשויות הרווחה הגדולות, תקנים מאוישים ופנויים.",
        "auth_top_caption": "תקנים, מאוישים, פנויים ושיעור איוש ברשויות הגדולות.",
        "auth_low_note": (f"{LOW_AUTH} הרשויות עם שיעור האיוש הנמוך ביותר, מבין רשויות "
                          f"בהיקף {MIN_AUTH_FTE} תקנים לפחות. הקו המקווקו — שיעור האיוש "
                          f"הכולל ({pct(fil, tot)})."),
        "auth_low_aria": f"גרף עמודות אופקי: {LOW_AUTH} הרשויות עם שיעור האיוש הנמוך ביותר.",
        "auth_low_caption": "שיעור איוש ותקנים ברשויות עם האיוש הנמוך ביותר.",
        "hist_note": (f"כמה רשויות בכל טווח של שיעור איוש, לפי מחוז. "
                      f"{int((auth['fil'] >= auth['tot']).sum()):,} רשויות מאוישות במלואן."),
        "hist_aria": "גרף עמודות מוערמות: מספר הרשויות לפי טווח שיעור איוש ומחוז.",
        "hist_caption": "מספר רשויות לפי טווח שיעור איוש ומחוז.",
        "scatter_note": ("כל נקודה היא רשות: היקף התקנים (ציר אופקי, לוגריתמי) מול שיעור "
                         "האיוש. רשויות קטנות מפוזרות יותר — תקן פנוי אחד משנה אצלן את השיעור "
                         "בהרבה."),
        "scatter_aria": "תרשים פיזור: היקף התקנים מול שיעור האיוש בכל רשות, לפי מחוז.",
        "status_note": (f"מצב האיוש של כל הקצאת תקן במאגר ({n_rows:,} הקצאות של סוג תקן "
                        f"ברשות): מספר ההקצאות והיקף התקנים בהן."),
        "status_aria": "תרשים טבעת: הקצאות תקן מאוישות במלואן, חלקית או לא מאוישות כלל.",
        "status_caption": "מספר הקצאות והיקף תקנים לפי מצב איוש.",
    }

    tables = {
        "district": [{"name": r["district"], "tot": fte(r["tot"]), "fil": fte(r["fil"]),
                      "vac": fte(r["vac"]), "rate": pct(r["fil"], r["tot"])}
                     for _, r in dist_order.iterrows()],
        "sw": [{"name": n, "sw": "—" if a is None else f"{a:.1f}%",
                "ns": "—" if b is None else f"{b:.1f}%"}
               for n, a, b in zip(ch_sw["names"], ch_sw["sw"], ch_sw["ns"])],
        "types": [{"name": r["atype"], "n": f"{int(r['n_auth']):,}", "tot": fte(r["tot"]),
                   "rate": pct(r["fil"], r["tot"])} for _, r in types.iterrows()],
        "roles": [{"name": r["name"], "tot": fte(r["tot"]), "fil": fte(r["fil"]),
                   "vac": fte(r["vac"])} for r in role_rows],
        "role_low": [{"name": r["role"], "rate": pct(r["fil"], r["tot"]), "tot": fte(r["tot"]),
                      "n": f"{int(r['n_auth']):,}"} for _, r in rl.iterrows()],
        "heat": heat_table,
        "auth_top": [{"name": r["auth"], "district": r["district"], "tot": fte(r["tot"]),
                      "vac": fte(r["vac"]), "rate": pct(r["fil"], r["tot"])}
                     for _, r in at.iterrows()],
        "auth_low": [{"name": r["auth"], "district": r["district"], "tot": fte(r["tot"]),
                      "rate": pct(r["fil"], r["tot"])} for _, r in al.iterrows()],
        "hist": [{"name": b, "cells": [f"{s['data'][i]:,}" for s in ch_hist["series"]],
                  "total": f"{sum(s['data'][i] for s in ch_hist['series']):,}"}
                 for i, b in enumerate(ch_hist["names"])],
        "status": [{"name": nm, "rows": f"{r:,}", "fte": f"{f:,.1f}"}
                   for nm, r, f in zip(ch_status["names"], ch_status["rows"], ch_status["fte"])],
    }

    return {
        "agent_data": {
            "summary_he": (f"תקני כוח האדם ברשויות הרווחה בהשתתפות משרד הרווחה: {fte0(tot)} "
                           f"תקנים ב-{len(auth):,} רשויות, {pct(fil, tot)} מהם מאוישים — "
                           f"היקף, איוש ופערים לפי מחוז, רשות וסוג תקן."),
            "dataset_kind": "rankings",
            "related_ids": ["4f361ce6-f30f-4629-b4ba-1ad19039e745",
                            "56639c97-30ba-4307-a768-9f4b1655c68a",
                            "edb5f516-28b1-439e-828a-43ec3a3cc82f",
                            "e941665c-53df-48b0-8a1f-e5ae719cf695"],
            "suggested_tags": ["תקני כוח אדם", "רשויות מקומיות", "עובדים סוציאליים",
                               "מחלקות לשירותים חברתיים", "איוש משרות", "רווחה"],
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": {
            "district": ch_district, "sw": ch_sw, "types": ch_types, "roles": ch_roles,
            "role_low": ch_role_low, "heat": ch_heat, "auth_top": ch_auth_top,
            "auth_low": ch_auth_low, "hist": ch_hist, "scatter": ch_scatter,
            "status": ch_status,
        },
        "tables": tables,
        "insights": insights,
        "labels": labels,
        "districts": d_names,
    }
