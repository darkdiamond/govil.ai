"""נתונים קבועים של נחלים בישראל: Water Authority registry of streams.

One row per stream: id, name, the stream (or water body) it flows into,
its main drainage basin ("תחום התנקזות ראשי") and, for about a third of the
streams, the catchment area in km² ("קמר").

The "flows into" column links rows into a river network: a value that is
another stream's name is a link, a value that is no stream's name is the
receiving water body (הים התיכון, ים המלח, הכנרת, מפרץ אילת, ...), and an
empty value means the outlet is not recorded. compute() walks every chain
to its end to get each stream's receiving water body and the number of
streams downstream of it. Nothing about the network is hardcoded: new
streams, basins or water bodies flow through.
"""
import pandas as pd

C_NAME = "שם נחל"
C_PARENT = "נחל אליו הוא נשפך"
C_BASIN = "תחום התנקזות ראשי"
C_AREA = "שטח אגן היקוות (קמר)"

NO_BASIN = "ללא תחום רשום"
NO_OUTLET = "יעד לא רשום"
OTHER = "אחר"

TOP_BASINS = 15          # bar chart of streams per basin
TOP_LARGEST = 15         # largest catchments
TOP_PARENTS = 15         # streams with most direct tributaries
TOP_WATER = 5            # receiving water bodies shown before "אחר"
COMPLETE_BASINS = 12     # basins on the area-completeness chart
MAX_HOPS_BAR = 6         # chain-length bar: last bucket is "6+"
AREA_BINS = [0, 10, 20, 50, 100, 250, 500, 1000]   # km² bin edges (last open)
LEADER_GAP = 1.2         # a basin "leads" when ≥ 1.2× the runner-up
SMALL_AREA = 50          # "small catchment" threshold for the distribution insight
LOW_COVERAGE = 0.5       # area-field coverage below this is called out


def _int(n):
    return f"{int(n):,}"


def _area(x):
    return f"{x:,.1f}"


def _pct(x, digits=0):
    return f"{x * 100:.{digits}f}%"


def _ranked(series):
    """value_counts with a total order: count desc, then label asc."""
    vc = series.value_counts()
    return vc.sort_index().sort_values(ascending=False, kind="stable")


def _prepare(df):
    out = pd.DataFrame({
        "name": df[C_NAME].str.strip(),
        "parent": df[C_PARENT].str.strip(),
        "basin": df[C_BASIN].str.strip(),
        "area": pd.to_numeric(df[C_AREA].str.replace(",", "", regex=False).str.strip(),
                              errors="coerce"),
    })
    out = out[out["name"] != ""].copy()
    out.loc[~(out["area"] > 0), "area"] = float("nan")
    out = out.sort_values(["name", "parent", "basin", "area"], kind="stable",
                          na_position="last").reset_index(drop=True)
    return out


def _walk(df):
    """Per stream: receiving water body, streams downstream, chain path."""
    pmap = {}
    for n, p in zip(df["name"], df["parent"]):
        pmap.setdefault(n, p)   # first by sorted order if a name repeats
    terms, hops, paths = [], [], []
    for n in df["name"]:
        cur, seen, path = n, {n}, [n]
        while True:
            p = pmap.get(cur, "")
            if p == "":
                term = NO_OUTLET
                break
            if p not in pmap:
                term = p
                break
            if p in seen:
                term = NO_OUTLET
                break
            seen.add(p)
            path.append(p)
            cur = p
        terms.append(term)
        hops.append(len(path) - 1)
        paths.append(path + ([term] if term != NO_OUTLET else []))
    df = df.copy()
    df["water"] = terms
    df["hops"] = hops
    df["path"] = paths
    df["is_link"] = df["parent"].isin(set(pmap))
    return df


def _basin_water(df):
    """Dominant recorded water body of each basin (majority of its streams)."""
    rec = df[(df["water"] != NO_OUTLET) & (df["basin"] != "")]
    out = {}
    for b, g in rec.groupby("basin"):
        out[b] = _ranked(g["water"]).index[0]
    return out


def compute(frames):
    df = _walk(_prepare(frames["main"]))
    n = len(df)
    has_area = df["area"].notna()
    n_area = int(has_area.sum())
    basins = df.loc[df["basin"] != "", "basin"]
    n_basins = int(basins.nunique())
    n_nobasin = int((df["basin"] == "").sum())

    # --- streams per basin ---
    bc = _ranked(df["basin"].replace("", NO_BASIN))
    named = bc[bc.index != NO_BASIN]
    top = named.head(TOP_BASINS)
    rest = int(named.iloc[TOP_BASINS:].sum())
    b_names = list(top.index)
    b_vals = [int(v) for v in top.values]
    if rest:
        b_names.append(f"{OTHER} ({_int(len(named) - TOP_BASINS)} תחומים)")
        b_vals.append(rest)
    if n_nobasin:
        b_names.append(NO_BASIN)
        b_vals.append(n_nobasin)
    basins_chart = {"names": b_names, "values": b_vals}
    basins_table = [{"name": nm, "count": _int(v), "share": _pct(v / n, 1)}
                    for nm, v in zip(b_names, b_vals)]

    # --- receiving water bodies ---
    wc = _ranked(df["water"])
    w_known = wc[wc.index != NO_OUTLET]
    w_top = w_known.head(TOP_WATER)
    w_rest = int(w_known.iloc[TOP_WATER:].sum())
    water_items = [{"name": k, "value": int(v)} for k, v in w_top.items()]
    if w_rest:
        water_items.append({"name": OTHER, "value": w_rest})
    n_noout = int(wc.get(NO_OUTLET, 0))
    if n_noout:
        water_items.append({"name": NO_OUTLET, "value": n_noout})
    water_table = [{"name": it["name"], "count": _int(it["value"]),
                    "share": _pct(it["value"] / n, 1)} for it in water_items]

    # --- treemap: dominant water body -> basin ---
    bw = _basin_water(df)
    tm = {}
    for b, cnt in named.items():
        w = bw.get(b, NO_OUTLET)
        tm.setdefault(w, []).append({"name": b, "value": int(cnt)})
    tm_order = sorted(tm, key=lambda w: (w == NO_OUTLET, -sum(c["value"] for c in tm[w]), w))
    treemap = [{"name": w, "value": sum(c["value"] for c in tm[w]), "children": tm[w]}
               for w in tm_order]
    treemap_table = [{"name": t["name"], "basins": _int(len(t["children"])),
                      "count": _int(t["value"])} for t in treemap]

    # --- largest catchments ---
    la = df[has_area].sort_values(["area", "name"], ascending=[False, True], kind="stable")
    lt = la.head(TOP_LARGEST)
    largest_chart = {"names": list(lt["name"]), "values": [round(float(v), 1) for v in lt["area"]]}
    largest_table = [{"name": r.name, "area": _area(r.area),
                      "parent": r.parent or NO_OUTLET, "basin": r.basin or NO_BASIN}
                     for r in lt.itertuples()]

    # --- catchment-area distribution ---
    ar = df.loc[has_area, "area"]
    dist_names, dist_vals = [], []
    for i, lo in enumerate(AREA_BINS):
        hi = AREA_BINS[i + 1] if i + 1 < len(AREA_BINS) else None
        if hi is None:
            m = ar >= lo
            label = f"{_int(lo)}+"
        else:
            m = (ar >= lo) & (ar < hi)
            label = f"{_int(lo)}-{_int(hi)}" if lo else f"עד {_int(hi)}"
        dist_names.append(label)
        dist_vals.append(int(m.sum()))
    dist_table = [{"name": nm, "count": _int(v), "share": _pct(v / n_area, 1) if n_area else "0%"}
                  for nm, v in zip(dist_names, dist_vals)]

    # --- chain length (streams downstream) ---
    linked = df[df["parent"] != ""]
    hop_names, hop_vals = [], []
    for h in range(MAX_HOPS_BAR + 1):
        if h < MAX_HOPS_BAR:
            m = linked["hops"] == h
            label = "נשפך ישירות לגוף מים" if h == 0 else f"{_int(h)} נחלים במורד"
            if h == 1:
                label = "נחל אחד במורד"
        else:
            m = linked["hops"] >= h
            label = f"{_int(h)}+ נחלים במורד"
        hop_names.append(label)
        hop_vals.append(int(m.sum()))
    while hop_vals and hop_vals[-1] == 0:
        hop_vals.pop()
        hop_names.pop()
    hops_table = [{"name": nm, "count": _int(v), "share": _pct(v / len(linked), 1) if len(linked) else "0%"}
                  for nm, v in zip(hop_names, hop_vals)]

    # --- streams with most direct tributaries ---
    pc = _ranked(df.loc[df["is_link"], "parent"])
    pt = pc.head(TOP_PARENTS)
    parents_chart = {"names": list(pt.index), "values": [int(v) for v in pt.values]}
    basin_by_name = dict(zip(df["name"], df["basin"]))
    parents_table = [{"name": k, "count": _int(v), "basin": basin_by_name.get(k) or NO_BASIN}
                     for k, v in pt.items()]

    # --- area completeness by basin ---
    cb = named.head(COMPLETE_BASINS)
    comp_names, comp_with, comp_without, comp_table = [], [], [], []
    for b, cnt in cb.items():
        w = int((has_area & (df["basin"] == b)).sum())
        comp_names.append(b)
        comp_with.append(w)
        comp_without.append(int(cnt) - w)
        comp_table.append({"name": b, "count": _int(cnt), "with": _int(w),
                           "share": _pct(w / cnt, 0)})
    completeness_chart = {"names": comp_names, "with": comp_with, "without": comp_without}

    # ------------------------------------------------------------------ insights
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    def ins_basin():
        if len(named) < 2:
            return None
        (b1, c1), (b2, c2) = list(named.items())[:2]
        if c1 < LEADER_GAP * c2:
            return (f"שני התחומים הגדולים כמעט שקולים: {b1} ({_int(c1)} נחלים) ו{b2} "
                    f"({_int(c2)}). יחד הם {_pct((c1 + c2) / n)} מהנחלים במאגר.")
        return (f"תחום ההתנקזות של {b1} הוא העשיר ביותר בנחלים: {_int(c1)} נחלים, "
                f"{_pct(c1 / n, 1)} מכלל המאגר, לעומת {_int(c2)} בתחום {b2} שבמקום השני.")
    add("basin_leader", ins_basin())

    def ins_water():
        if len(w_known) < 2:
            return None
        k = int(w_known.sum())
        (w1, c1), (w2, c2) = list(w_known.items())[:2]
        txt = (f"מבין {_int(k)} הנחלים ששרשרת הנשפכים שלהם מגיעה לגוף מים רשום, "
               f"{_int(c1)} ({_pct(c1 / k)}) מתנקזים אל {w1} ו-{_int(c2)} ({_pct(c2 / k)}) אל {w2}.")
        if n_noout:
            txt += f" אצל {_int(n_noout)} נחלים השרשרת נעצרת בנחל שיעדו לא רשום."
        return txt
    add("water", ins_water())

    def ins_largest():
        if len(la) < 3:
            return None
        r1, r2 = la.iloc[0], la.iloc[1]
        med = float(ar.median())
        ratio = r1["area"] / med if med else 0
        return (f"לנחל {r1['name']} אגן ההיקוות הגדול ביותר במאגר, {_area(r1['area'])} קמ״ר, "
                f"ואחריו {r2['name']} עם {_area(r2['area'])} קמ״ר. זה פי {ratio:,.0f} "
                f"מהאגן החציוני ({_area(med)} קמ״ר).")
    add("largest", ins_largest())

    def ins_small():
        if n_area < 10:
            return None
        small = int((ar < SMALL_AREA).sum())
        big = int((ar >= AREA_BINS[-1]).sum())
        share = small / n_area
        if share < 0.5:
            return None
        txt = (f"רוב האגנים קטנים: {_int(small)} מתוך {_int(n_area)} הנחלים ששטח אגנם רשום "
               f"({_pct(share)}) מנקזים פחות מ-{_int(SMALL_AREA)} קמ״ר")
        if big:
            txt += f", ורק {_int(big)} מנקזים {_int(AREA_BINS[-1])} קמ״ר ומעלה."
        else:
            txt += "."
        return txt
    add("small", ins_small())

    def ins_parent():
        if len(pc) < 2:
            return None
        p1, c1 = pc.index[0], int(pc.iloc[0])
        p2, c2 = pc.index[1], int(pc.iloc[1])
        if c1 < 3:
            return None
        if c1 == c2:
            return (f"{p1} ו{p2} הם הנחלים עם מספר היובלים הישירים הגדול ביותר, "
                    f"{_int(c1)} יובלים רשומים לכל אחד.")
        return (f"לנחל {p1} הכי הרבה יובלים ישירים במאגר: {_int(c1)} נחלים נשפכים אליו, "
                f"לעומת {_int(c2)} אל {p2}.")
    add("parent", ins_parent())

    def ins_chain():
        if not len(linked):
            return None
        lk = linked.sort_values(["hops", "name"], ascending=[False, True], kind="stable")
        r = lk.iloc[0]
        if r["hops"] < 3:
            return None
        path = " ← ".join(r["path"])
        end = r["water"] if r["water"] != NO_OUTLET else "סוף השרשרת הרשומה"
        n_deep = int((linked["hops"] >= 3).sum())
        return (f"השרשרת הארוכה ביותר במאגר: מנחל {r['name']} עוברים עוד {_int(r['hops'])} נחלים "
                f"עד {end} ({path}). בסך הכול ל-{_int(n_deep)} נחלים יש שלושה נחלים או יותר במורד הזרם.")
    add("chain", ins_chain())

    def ins_coverage():
        if not n:
            return None
        share = n_area / n
        if share >= LOW_COVERAGE:
            return None
        return (f"שטח אגן ההיקוות רשום רק ל-{_int(n_area)} מתוך {_int(n)} נחלים "
                f"({_pct(share)}), בעיקר לנחלים הראשיים. לכן תרשימי השטח מתארים את "
                f"הנחלים המתועדים ולא את כולם.")
    add("coverage", ins_coverage())

    # ------------------------------------------------------------------ KPIs, labels
    lead_basin = named.index[0] if len(named) else ""
    top_area = la.iloc[0] if len(la) else None
    kpis = {
        "total": {"value": n, "display": _int(n), "tone": "brand",
                  "label": "נחלים רשומים במאגר"},
        "basins": {"value": n_basins, "display": _int(n_basins), "tone": "brand",
                   "label": "תחומי התנקזות ראשיים"},
        "largest": {"value": float(top_area["area"]) if top_area is not None else 0,
                    "display": _area(top_area["area"]) if top_area is not None else "0",
                    "tone": "info",
                    "label": (f"אגן ההיקוות הגדול ביותר, קמ״ר (נחל {top_area['name']})"
                              if top_area is not None else "אגן ההיקוות הגדול ביותר, קמ״ר")},
        "with_area": {"value": n_area, "display": _pct(n_area / n if n else 0),
                      "tone": "warn" if n and n_area / n < LOW_COVERAGE else "ok",
                      "label": f"נחלים עם שטח אגן רשום ({_int(n_area)} נחלים)"},
    }

    med_txt = _area(float(ar.median())) if n_area else "0"
    labels = {
        "lede": (f"המאגר הקבוע של רשות המים לנחלי ישראל: {_int(n)} נחלים, לכל אחד שם, "
                 f"הנחל או גוף המים שאליו הוא נשפך, תחום ההתנקזות הראשי שלו ולחלק מהם "
                 f"גם שטח אגן ההיקוות. מקשרי הנשפכים נבנית רשת הנחלים: איזה נחל יובל של איזה, "
                 f"ולאיזה ים הם מגיעים בסוף."),
        "lookup_title": "איתור נחל לפי שם, נחל יעד או תחום התנקזות ←",
        "lookup_sub": "חיפוש חי בכל רשומות המאגר: שם הנחל, הנחל אליו הוא נשפך, תחום ההתנקזות הראשי ומספר הזיהוי.",
        "basins_note": (f"מספר הנחלים בכל אחד מ-{_int(TOP_BASINS)} התחומים הגדולים מתוך {_int(n_basins)}; "
                        f"שאר התחומים מקובצים תחת \"{OTHER}\""
                        + (f", ו-{_int(n_nobasin)} נחלים ללא תחום רשום מוצגים בנפרד." if n_nobasin else ".")),
        "basins_aria": f"תרשים עמודות: מספר הנחלים לפי תחום התנקזות ראשי. המוביל: {lead_basin}.",
        "water_note": ("לכל נחל עוקבים אחר שרשרת הנשפכים (נחל אל נחל) עד גוף המים שבסופה. "
                       f"\"{NO_OUTLET}\": השרשרת נעצרת בנחל שלא רשום לאן הוא נשפך."),
        "water_aria": "תרשים טבעת: חלוקת הנחלים לפי גוף המים שאליו הם מתנקזים בסוף השרשרת.",
        "treemap_note": ("כל תחום התנקזות משויך לגוף המים הנפוץ ביותר בקרב הנחלים שלו שיעדם רשום; "
                         f"תחום שאף נחל בו לא מגיע ליעד רשום מופיע תחת \"{NO_OUTLET}\". גודל המלבן: מספר הנחלים."),
        "treemap_aria": "מפת עץ: תחומי ההתנקזות מקובצים לפי גוף המים שאליו הם מתנקזים, לפי מספר נחלים.",
        "largest_note": (f"{_int(TOP_LARGEST)} הנחלים עם אגן ההיקוות הגדול ביותר, מתוך {_int(n_area)} "
                         f"נחלים ששטח אגנם רשום. אגן של נחל ראשי כולל גם את אגני היובלים שלו."),
        "largest_aria": "תרשים עמודות אופקי: הנחלים עם אגן ההיקוות הגדול ביותר בקמ״ר.",
        "dist_note": (f"התפלגות שטחי האגן של {_int(n_area)} הנחלים ששטח אגנם רשום, בקמ״ר. "
                      f"האגן החציוני: {med_txt} קמ״ר."),
        "dist_aria": "היסטוגרמה: מספר הנחלים לפי טווח שטח אגן ההיקוות.",
        "hops_note": (f"לכמה נחלים במורד הזרם צריך לעבור עד גוף המים או עד סוף השרשרת הרשומה. "
                      f"כולל {_int(len(linked))} נחלים שיעדם רשום; {_int(n - len(linked))} נחלים בלי נחל יעד לא נכללים."),
        "hops_aria": "תרשים עמודות: מספר הנחלים לפי מספר הנחלים שבמורד הזרם שלהם.",
        "parents_note": f"{_int(TOP_PARENTS)} הנחלים שהכי הרבה נחלים אחרים במאגר נשפכים אליהם ישירות.",
        "parents_aria": "תרשים עמודות אופקי: נחלים לפי מספר היובלים הישירים.",
        "comp_note": (f"ב-{_int(COMPLETE_BASINS)} התחומים עם הכי הרבה נחלים: כמה מהנחלים רשום להם שטח אגן "
                      f"וכמה לא. מראה היכן תרשימי השטח מייצגים את התחום כולו והיכן רק את הנחלים הראשיים."),
        "comp_aria": "תרשים עמודות מוערמות: נחלים עם ובלי שטח אגן רשום, לפי תחום התנקזות.",
    }

    known = int(w_known.sum())
    med_share = (f"{_pct(int(w_known.iloc[0]) / known)} מהנחלים שיעדם רשום מגיעים אל {w_known.index[0]}"
                 if known else "")
    summary = (f"רשימת {_int(n)} נחלי ישראל: איתור נחל לפי שם, הנחל אליו הוא נשפך ותחום ההתנקזות. "
               f"{_int(n_basins)} תחומי התנקזות"
               + (f"; {med_share}." if med_share else "."))
    if len(summary) > 155:
        summary = (f"רשימת {_int(n)} נחלי ישראל: איתור נחל לפי שם, הנחל אליו הוא נשפך ותחום ההתנקזות.")

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "registry",
            "suggested_tags": ["נחלים", "הידרולוגיה", "אגני היקוות", "תחומי התנקזות", "משאבי מים"],
            "related_ids": [
                "096db5d2-dc8b-40c8-9fe7-2b839a435d92",
                "d16214ba-56b3-417d-9342-6a144f215b9b",
                "15072295-27ab-4939-951b-de462adc0ab0",
                "e81d14bd-a81d-4de4-b1de-d7a0541ace02",
                "db8f9bc9-738a-4d83-b3ce-74e8a5f7f844",
            ],
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": {
            "basins": basins_chart,
            "water": water_items,
            "treemap": treemap,
            "largest": largest_chart,
            "dist": {"names": dist_names, "values": dist_vals},
            "hops": {"names": hop_names, "values": hop_vals},
            "parents": parents_chart,
            "completeness": completeness_chart,
        },
        "tables": {
            "basins": basins_table,
            "water": water_table,
            "treemap": treemap_table,
            "largest": largest_table,
            "dist": dist_table,
            "hops": hops_table,
            "parents": parents_table,
            "completeness": comp_table,
        },
        "insights": insights,
        "labels": labels,
    }
