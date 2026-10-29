"""אפוטרופוס הכללי - נכסים עזובים - רשימת נעדרים.

One CSV, one row per (absentee owner name, case): case number, last name,
first name, a case date (dd/mm/yyyy, with a "00/00/00" placeholder for
unknown), asset type (money / real estate / rights and combinations, with
irregular inner whitespace) and a handling status.

The people listed are private individuals (absentee owners, many likely
deceased), so the page never names, ranks or counts individual names: every
figure is an aggregate by date, asset type, status or case size. The rows
themselves are reachable through the shell's explorer (lookup callout).

Growth: the list is republished in place; new cases append with recent dates.
Years and decades are derived from the data (no fixed axis), new asset types
and statuses flow through (top-N + "אחר" for asset types), and a latest year
whose last record is before December is flagged partial and kept out of the
peak rule.
"""
import re

import pandas as pd

STATE_YEAR = 1948          # dates before this are shown apart (likely typos)
EARLY_BUCKET_END = 1949    # decade charts fold everything up to here
MODERN_SPLIT = 2000        # transferred-before-2000 rule
RECENT_YEARS = 10          # "recent cases" window for the status-shift rule
TOP_ASSETS = 7
SUMMARY_MAX = 155

STATUS_COLORS = {
    "transferred": "#0b3668",
    "pending": "#0068f5",
    "managed": "#6c9fd8",
}
OTHER_COLORS = ["#b7d2f7", "#3d70b0", "#2658a0", "#0c1f3d", "#0053c4"]
MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי", "אוגוסט",
             "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]


def _clean(s):
    return re.sub(r"\s+", " ", str(s)).strip()


def _status_kind(s):
    if "הועבר" in s:
        return "transferred"
    if "לקראת העברה" in s:
        return "pending"
    if "בניהול" in s:
        return "managed"
    return "other"


def _asset_label(a):
    """'מקרקעין כספים' -> 'מקרקעין + כספים'; 'כספים או מקרקעין' stays as is."""
    if not a:
        return "לא צוין"
    if " או " in f" {a} ":
        return a
    parts = a.split(" ")
    return " + ".join(parts) if len(parts) > 1 else a


def _pct(x, digits=1):
    return f"{x * 100:.{digits}f}%"


def _decade_label(y):
    if y <= EARLY_BUCKET_END:
        return f"עד {EARLY_BUCKET_END}"
    d = (y // 10) * 10
    return f"{d}-{d + 9}"


def _decade_key(y):
    return 0 if y <= EARLY_BUCKET_END else (y // 10) * 10


def _prepare(df):
    d = pd.DataFrame({
        "case": df["case"].map(_clean),
        "asset": df["asset"].map(_clean).map(_asset_label),
        "status": df["status"].map(_clean),
    })
    d["status"] = d["status"].where(d["status"] != "", "לא צוין")
    d["date"] = pd.to_datetime(df["date"].str.strip(), format="%d/%m/%Y",
                               errors="coerce")
    d["year"] = d["date"].dt.year
    d["kind"] = d["status"].map(_status_kind)
    return d


def _status_order(d):
    vc = d.groupby("status").size().reset_index(name="n")
    vc = vc.sort_values(["n", "status"], ascending=[False, True], kind="stable")
    names = list(vc["status"])
    colors, k = {}, 0
    for n in names:
        kind = _status_kind(n)
        if kind in STATUS_COLORS and kind not in [_status_kind(x) for x in colors]:
            colors[n] = STATUS_COLORS[kind]
        else:
            colors[n] = OTHER_COLORS[k % len(OTHER_COLORS)]
            k += 1
    return names, [int(v) for v in vc["n"]], colors


def _asset_order(d):
    vc = d.groupby("asset").size().reset_index(name="n")
    vc = vc.sort_values(["n", "asset"], ascending=[False, True], kind="stable")
    names = list(vc["asset"])
    if len(names) > TOP_ASSETS:
        keep = names[:TOP_ASSETS - 1]
        mapping = {n: (n if n in keep else "אחר") for n in names}
        names = keep + ["אחר"]
    else:
        mapping = {n: n for n in names}
    return names, mapping


# ---------------------------------------------------------------- insights

def insight_pending(d, n):
    p = d[d["kind"] == "pending"]
    if p.empty or len(p) / n < 0.2:
        return None
    vc = p.groupby("status").size().reset_index(name="n")
    name = vc.sort_values(["n", "status"], ascending=[False, True], kind="stable").iloc[0]["status"]
    return (f"{_pct(len(p) / n)} מהרשומות ({len(p):,}) מסומנות בסטטוס "
            f"\"{name}\": הנכסים עדיין מנוהלים, אך התיק נבדק לקראת העברה לקניין המדינה. "
            f"מי שמזהה קרוב משפחה ברשימה יכול לפנות לאפוטרופוס הכללי עם מספר התיק.")


def insight_transferred(d, n):
    t = d[d["kind"] == "transferred"]
    if t.empty:
        return None
    dated = t[t["year"].notna()]
    s = f"{len(t):,} רשומות ({_pct(len(t) / n)}) כבר הועברו לקניין המדינה"
    if len(dated) >= 20:
        old = (dated["year"] < MODERN_SPLIT).mean()
        if old >= 0.6:
            s += f", ו-{_pct(old, 0)} מהן מתיקים שתאריכם לפני {MODERN_SPLIT}"
    return s + "."


def insight_shift(d):
    dated = d[d["year"].notna()]
    full = _full_years(dated)
    if not full:
        return None
    last = max(full)
    first = last - RECENT_YEARS + 1
    recent = dated[(dated["year"] >= first) & (dated["year"] <= last)]
    older = dated[dated["year"] < first]
    if len(recent) < 100 or len(older) < 100:
        return None
    r = (recent["kind"] == "managed").mean()
    o = (older["kind"] == "managed").mean()
    if r - o < 0.2 or o >= 0.5:
        return None
    return (f"בתיקים מהשנים {first}-{last}, {_pct(r, 0)} מהרשומות בסטטוס ניהול שוטף "
            f"של האפוטרופוס הכללי, לעומת {_pct(o, 0)} בלבד בתיקים ישנים יותר, "
            f"שרובם כבר בבדיקה לקראת העברה או שהועברו.")


def insight_assets(d, n):
    money_only = (d["asset"] == "כספים").sum()
    land_any = d["asset"].str.contains("מקרקעין") & ~d["asset"].str.contains(" או ")
    rights_any = d["asset"].str.contains("זכויות")
    if money_only / n < 0.4:
        return None
    s = (f"רוב הנכסים העזובים הם כספים: {_pct(money_only / n)} מהרשומות ({money_only:,}) "
         f"הן כספים בלבד, ו-{int(land_any.sum()):,} רשומות ({_pct(land_any.mean())}) "
         f"כוללות מקרקעין (לבד או יחד עם נכס אחר)")
    if rights_any.sum():
        s += f"; {int(rights_any.sum()):,} כוללות זכויות"
    return s + "."


def insight_uniform(d):
    """An asset category whose records all share one status (min 50 rows)."""
    g = d.groupby(["asset", "status"]).size().reset_index(name="n")
    tot = d.groupby("asset").size()
    best = None
    for _, r in g.iterrows():
        t = int(tot[r["asset"]])
        if t < 50:
            continue
        share = r["n"] / t
        if share >= 0.95:
            key = (-t, r["asset"])
            if best is None or key < best[0]:
                best = (key, r["asset"], r["status"], t, share)
    if best is None:
        return None
    _, asset, status, t, share = best
    lead = "כל" if share == 1 else f"{_pct(share)} מתוך"
    s = f"{lead} {t:,} הרשומות מסוג \"{asset}\" נמצאות בסטטוס \"{status}\""
    yrs = d.loc[(d["asset"] == asset) & d["year"].notna(), "year"]
    if len(yrs) >= 20:
        old = (yrs < MODERN_SPLIT).mean()
        if old >= 0.8:
            s += f"; {_pct(old, 0)} מהן מתיקים שתאריכם לפני {MODERN_SPLIT}"
    return s + "."


def _full_years(dated):
    years = sorted(set(int(y) for y in dated["year"]))
    if not years:
        return []
    last = years[-1]
    last_month = int(dated.loc[dated["year"] == last, "date"].dt.month.max())
    if last_month < 12:
        years = years[:-1]
    return [y for y in years if y >= STATE_YEAR]


def insight_peak(by_year, partial_year):
    rows = [(y, v) for y, v in by_year if y != partial_year]
    if len(rows) < 10:
        return None
    top = sorted(rows, key=lambda r: (-r[1], r[0]))[0]
    vals = [v for _, v in rows]
    med = sorted(vals)[len(vals) // 2]
    if top[1] < 1.5 * med:
        return None
    s = (f"שנת השיא בתאריכי התיקים היא {top[0]}, עם {top[1]:,} רשומות, "
         f"פי {top[1] / med:.1f} מהחציון השנתי ({med:,})")
    return s + "."


def insight_multi(d):
    sizes = d.groupby("case").size()
    multi = sizes[sizes > 1]
    if multi.empty or len(sizes) < 50:
        return None
    rows_in = int(multi.sum())
    return (f"{len(multi):,} תיקים ({_pct(len(multi) / len(sizes))} מהתיקים) רשומים על יותר "
            f"מבעלים אחד, ובהם {rows_in:,} שמות; בתיק הגדול ביותר רשומים "
            f"{int(sizes.max()):,} בעלים. כשמחפשים קרוב משפחה, כדאי לבדוק גם שמות "
            f"נוספים באותו מספר תיק.")


def insight_quality(n_bad, n_early, early_mode):
    if not n_bad and not n_early:
        return None
    parts = []
    if n_bad:
        parts.append(f"{n_bad:,} רשומות ללא תאריך תקין")
    if n_early:
        e = f"{n_early:,} רשומות עם תאריך לפני {STATE_YEAR}"
        if early_mode:
            e += f" (רובן בשנת {early_mode}, ייתכן שגיאת הקלדה)"
        parts.append(e)
    return ("במאגר " + " ו-".join(parts)
            + "; הן נספרות בסיכומים אך אינן מוצגות בגרף השנתי.")


# ---------------------------------------------------------------- compute

def compute(frames):
    d = _prepare(frames["main"])
    n = int(len(d))
    n_cases = int(d["case"].nunique())
    dated = d[d["year"].notna()].copy()
    dated["year"] = dated["year"].astype(int)
    n_bad = n - int(len(dated))
    early = dated[dated["year"] < STATE_YEAR]
    n_early = int(len(early))
    early_mode = None
    if n_early:
        vc = early["year"].value_counts()
        vc = vc.sort_index()
        top = int(vc.idxmax())
        if vc.max() / n_early >= 0.5:
            early_mode = top
    main = dated[dated["year"] >= STATE_YEAR]

    statuses, status_counts, status_colors = _status_order(d)
    asset_names, asset_map = _asset_order(d)
    d["asset_g"] = d["asset"].map(asset_map)

    # ---- yearly, stacked by status
    full = _full_years(dated)
    partial_year = None
    if len(main):
        y0, y1 = int(main["year"].min()), int(main["year"].max())
        if y1 not in full:
            partial_year = y1
        years = list(range(y0, y1 + 1))
    else:
        years = []
    ys = main.groupby(["year", "status"]).size()
    yearly_series = []
    for s in statuses:
        yearly_series.append({
            "name": s, "color": status_colors[s],
            "data": [int(ys.get((y, s), 0)) for y in years],
        })
    yt = main.groupby("year").size()
    by_year = [(y, int(yt.get(y, 0))) for y in years]

    # ---- decades
    dated["dkey"] = dated["year"].map(_decade_key)
    dated["asset_g"] = dated["asset"].map(asset_map)
    dkeys = sorted(set(dated["dkey"]))
    dlabels = []
    for k in dkeys:
        sub = dated[dated["dkey"] == k]
        dlabels.append(_decade_label(int(sub["year"].min())) if k == 0
                       else _decade_label(k))
    dec_tot = dated.groupby("dkey").size()
    dec_st = dated.groupby(["dkey", "status"]).size()
    dec_as = dated.groupby(["dkey", "asset_g"]).size()

    def share_rows(tab, keys):
        out = []
        for s in keys:
            row = []
            for k in dkeys:
                t = int(dec_tot.get(k, 0))
                row.append(round(100 * int(tab.get((k, s), 0)) / t, 1) if t else 0)
            out.append(row)
        return out

    dec_status = {
        "x": dlabels,
        "totals": [int(dec_tot.get(k, 0)) for k in dkeys],
        "series": [{"name": s, "color": status_colors[s], "data": r}
                   for s, r in zip(statuses, share_rows(dec_st, statuses))],
    }
    dec_assets = {
        "x": dlabels,
        "totals": [int(dec_tot.get(k, 0)) for k in dkeys],
        "series": [{"name": a, "data": r}
                   for a, r in zip(asset_names, share_rows(dec_as, asset_names))],
    }
    dec_table = []
    for i, k in enumerate(dkeys):
        dec_table.append({
            "label": dlabels[i], "total": int(dec_tot.get(k, 0)),
            "status": [dec_status["series"][j]["data"][i] for j in range(len(statuses))],
            "assets": [dec_assets["series"][j]["data"][i] for j in range(len(asset_names))],
        })

    # ---- assets and status overall
    ac = d.groupby("asset_g").size()
    assets_chart = {"names": asset_names,
                    "values": [int(ac.get(a, 0)) for a in asset_names],
                    "shares": [round(100 * int(ac.get(a, 0)) / n, 1) if n else 0
                               for a in asset_names]}
    status_chart = [{"name": s, "value": c, "color": status_colors[s],
                     "share": round(100 * c / n, 1) if n else 0}
                    for s, c in zip(statuses, status_counts)]

    # ---- status by asset type (100% rows per asset)
    asst = d.groupby(["asset_g", "status"]).size()
    asset_status = {
        "names": asset_names,
        "totals": [int(ac.get(a, 0)) for a in asset_names],
        "series": [{"name": s, "color": status_colors[s],
                    "data": [round(100 * int(asst.get((a, s), 0)) / int(ac.get(a, 1)), 1)
                             for a in asset_names]}
                   for s in statuses],
    }

    # ---- names per case
    sizes = d.groupby("case").size()
    bands = [("1", 1, 1), ("2", 2, 2), ("3", 3, 3), ("4", 4, 4),
             ("5-9", 5, 9), ("10+", 10, 10 ** 9)]
    owners = {"names": [], "cases": [], "rows": []}
    for label, lo, hi in bands:
        m = (sizes >= lo) & (sizes <= hi)
        owners["names"].append(label)
        owners["cases"].append(int(m.sum()))
        owners["rows"].append(int(sizes[m].sum()))
    multi_cases = int((sizes > 1).sum())

    # ---- insights
    rules = [
        ("pending", insight_pending(d, n)),
        ("transferred", insight_transferred(d, n)),
        ("shift", insight_shift(dated)),
        ("assets", insight_assets(d, n)),
        ("uniform", insight_uniform(d)),
        ("peak", insight_peak(by_year, partial_year)),
        ("multi", insight_multi(d)),
        ("quality", insight_quality(n_bad, n_early, early_mode)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    # ---- KPIs
    kpis, labels, order = {}, {}, []

    def add(key, value, display, label, tone="brand"):
        kpis[key] = {"value": value, "display": display, "tone": tone}
        labels[f"kpi_{key}"] = label
        order.append(key)

    add("total", n, f"{n:,}", "שמות בעלי רכוש ברשימה")
    add("cases", n_cases, f"{n_cases:,}", "תיקים שונים")
    kinds = d["kind"].value_counts()
    pend = int(kinds.get("pending", 0))
    if pend:
        add("pending", pend, f"{pend:,}", "רשומות בבדיקה לקראת העברה לקניין המדינה", "warn")
    tr = int(kinds.get("transferred", 0))
    if tr:
        add("transferred", round(tr / n, 4), f"{tr / n * 100:.1f}%",
            f"מהרשומות כבר הועברו לקניין המדינה ({tr:,})", "info")
    money = int((d["asset"] == "כספים").sum())
    add("money", round(money / n, 4), f"{money / n * 100:.1f}%",
        "מהרשומות הן כספים בלבד")
    if len(dated):
        lo_y = int(dated["year"].min())
        hi_y = int(dated["year"].max())
        add("span", f"{lo_y}/{hi_y}", f"{lo_y}–{hi_y}", "טווח התאריכים בתיקים")

    # ---- summary (meta description)
    parts = [
        "איתור נכסים עזובים של נעדרים לפי שם משפחה, שם פרטי או מספר תיק.",
        f"{n:,} שמות ב-{n_cases:,} תיקים של האפוטרופוס הכללי",
    ]
    if len(dated):
        parts[1] += f", {lo_y}-{hi_y}."
    else:
        parts[1] += "."
    summary = " ".join(parts)
    if len(summary) > SUMMARY_MAX:
        summary = parts[0]

    agent_data = {
        "summary_he": summary,
        "dataset_kind": "registry",
        "suggested_tags": ["נכסים עזובים", "נעדרים", "אפוטרופוס כללי",
                           "ירושה", "רכוש מדינה", "משרד המשפטים"],
        "related_ids": ["3111ae54-790a-4d02-9750-d51e1134b405",
                        "10288bf1-b6d5-4855-a633-6c650c277bd3",
                        "83372c35-23ce-4ddf-829f-1067b5ef3409"],
        "spatial_coverage": "ישראל",
    }
    if len(dated):
        agent_data["temporal_coverage"] = f"{lo_y}/{hi_y}"

    # ---- labels / ledes
    top_status = statuses[0] if statuses else ""
    peak = sorted([r for r in by_year if r[0] != partial_year],
                  key=lambda r: (-r[1], r[0]))
    peak_txt = f"השיא: {peak[0][0]} עם {peak[0][1]:,} רשומות." if peak else ""
    excl = []
    if n_bad:
        excl.append(f"{n_bad:,} ללא תאריך תקין")
    if n_early:
        excl.append(f"{n_early:,} עם תאריך לפני {STATE_YEAR}")
    excl_txt = (" לא מוצגות: " + ", ".join(excl) + ".") if excl else ""
    partial_txt = ""
    if partial_year:
        lm = int(dated.loc[dated["year"] == partial_year, "date"].dt.month.max())
        partial_txt = (f" שנת {partial_year} חלקית (הרשומה האחרונה מחודש "
                       f"{MONTHS_HE[lm - 1]}) ומוצגת בגוון בהיר.")

    first_dec = dec_status["x"][0] if dec_status["x"] else ""
    last_dec = dec_status["x"][-1] if dec_status["x"] else ""
    ac_sorted = sorted(zip(asset_names, assets_chart["values"]), key=lambda r: (-r[1], r[0]))
    owners_multi_share = multi_cases / len(sizes) if len(sizes) else 0

    labels.update({
        "lede": (f"האפוטרופוס הכללי במשרד המשפטים מנהל נכסים עזובים: כספים, דירות, קרקעות וזכויות "
                 f"של בעלים שמקום הימצאם אינו ידוע (נעדרים). כדי לאתר את הבעלים או את יורשיהם "
                 f"מתפרסמת רשימת הנעדרים: {n:,} שמות ב-{n_cases:,} תיקים"
                 + (f", עם תאריכים מ-{lo_y} עד {hi_y}" if len(dated) else "")
                 + ". הדף מציג את הרשימה בסיכומים בלבד, לפי סוג הנכס, סטטוס הטיפול ותאריך התיק; "
                   "החיפוש לפי שם נעשה בטבלת הנתונים שבתחתית הדף."),
        "yearly_lede": (f"מספר הרשומות לפי שנת התאריך הרשום בתיק, מחולק לפי סטטוס הטיפול. "
                        f"{peak_txt}{partial_txt}{excl_txt}"),
        "yearly_aria": (f"גרף עמודות מוערמות: רשומות ברשימת הנעדרים לפי שנה וסטטוס, "
                        f"{years[0] if years else ''}-{years[-1] if years else ''}. {peak_txt}"),
        "status_lede": (f"הסטטוס הנפוץ: \"{top_status}\", "
                        f"{_pct(status_counts[0] / n) if n else ''} מהרשומות."),
        "status_aria": ("תרשים טבעת: התפלגות הרשומות לפי סטטוס הטיפול. "
                        + "; ".join(f"{s}: {c:,}" for s, c in zip(statuses, status_counts))),
        "decstat_lede": ("איך מתחלק כל עשור לפי סטטוס, באחוזים מרשומות העשור"
                         + (f"; העמודה הראשונה מאגדת את כל התיקים שתאריכם {first_dec}."
                            if dkeys and dkeys[0] == 0 else ".")
                         if len(dkeys) >= 2 else "התפלגות הסטטוס לפי עשור."),
        "decstat_aria": (f"גרף עמודות מוערמות באחוזים: סטטוס הטיפול לפי עשור, "
                         f"{len(dkeys):,} עשורים עד {last_dec}."),
        "assets_lede": ("סוג הנכס כפי שנרשם בתיק. "
                        + (f"הנפוץ: {ac_sorted[0][0]}, {ac_sorted[0][1]:,} רשומות." if ac_sorted else "")),
        "assets_aria": ("תרשים עמודות אופקי: רשומות לפי סוג הנכס. "
                        + "; ".join(f"{a}: {v:,}" for a, v in ac_sorted[:4])),
        "asset_status_lede": "לכל סוג נכס, איזה חלק מהרשומות נמצא בכל סטטוס.",
        "asset_status_aria": "גרף עמודות אופקיות מוערמות באחוזים: סטטוס הטיפול לפי סוג הנכס.",
        "decassets_lede": "תמהיל סוגי הנכסים בכל עשור, באחוזים מרשומות העשור.",
        "decassets_aria": (f"גרף עמודות מוערמות באחוזים: סוגי הנכסים לפי עשור, "
                           f"{len(dkeys):,} עשורים עד {last_dec}."),
        "owners_lede": (f"בתיק אחד יכולים להופיע כמה בעלים, למשל בני משפחה או שותפים בנכס. "
                        f"{multi_cases:,} תיקים ({_pct(owners_multi_share)}) כוללים יותר משם אחד."),
        "owners_aria": ("גרף עמודות: מספר התיקים לפי מספר הבעלים הרשומים בתיק. "
                        + f"{owners['cases'][0]:,} תיקים עם בעלים יחיד."),
    })

    return {
        "agent_data": agent_data,
        "kpis": kpis,
        "kpi_order": order,
        "charts": {
            "yearly": {"x": [str(y) for y in years], "series": yearly_series,
                       "partial": str(partial_year) if partial_year else None},
            "status": status_chart,
            "dec_status": dec_status,
            "assets": assets_chart,
            "asset_status": asset_status,
            "dec_assets": dec_assets,
            "owners": owners,
        },
        "tables": {"decades": dec_table, "statuses": statuses, "assets": asset_names},
        "insights": insights,
        "flags": {"has_years": len(years) >= 3, "has_decades": len(dkeys) >= 2},
        "labels": labels,
    }
