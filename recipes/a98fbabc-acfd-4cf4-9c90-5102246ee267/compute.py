"""מטרו - קווים במטרופולין ירושלים (משרד התחבורה, צוות חצב).

The datastore CSV is the attribute table of a small GIS line layer: one row per
planned metro segment, with `LINE_ID`, `LINE_NAME` (X_1, X_2, X_Extension1,
X_Extension2 in the 2026 file), a target `YEAR` (2050), the measured
`Shape_Length` in metres (ITM projection) and `LENGT`, the same length rounded
to whole km. `OID` is a constant -1 export artefact. The route geometry itself
lives only in the SHP/KML ZIPs (no datastore), and the XLSX resource is a
metadata sheet, not a twin, so the page is honest about what it can show:
segment lengths, main lines versus extensions, and the planning horizon.

Growth: the layer is replaced in place when the plan changes. More segments
flow through (bar chart capped at TOP_SEG + "אחר"), a segment is classed as an
extension by its name (case-insensitive "extension"/"ext"), new years are
listed rather than assumed, and a missing measured length falls back to the
rounded `LENGT`.
"""
import re

import pandas as pd

TOP_SEG = 15            # bars before an "אחר" bucket
LEAD_SHARE = 0.30       # the longest segment is called out from this share
ROUND_GAP_KM = 0.3      # rounded-vs-measured gap worth a note
LRI, PDI = "⁦", "⁩"
EXT_RX = re.compile(r"ext", re.IGNORECASE)


def iso(s):
    return f"{LRI}{s}{PDI}"


def km(v):
    return f"{v:,.1f}"


def pct(v):
    return f"{v * 100:.0f}%"


def clean(s):
    return " ".join(str(s).replace(" ", " ").split())


def _num(s):
    return pd.to_numeric(s.map(clean).str.replace(",", "", regex=False), errors="coerce")


def _prepare(df):
    out = pd.DataFrame({
        "name": df["LINE_NAME"].map(clean),
        "line_id": df["LINE_ID"].map(clean),
        "year": _num(df["YEAR"]),
        "shape_m": _num(df["Shape_Length"]),
        "lengt": _num(df["LENGT"]),
    })
    out = out[out["name"] != ""].copy()
    out["km"] = (out["shape_m"] / 1000.0).where(out["shape_m"] > 0, out["lengt"])
    out = out[out["km"].notna() & (out["km"] > 0)].copy()
    out["ext"] = out["name"].map(lambda s: bool(EXT_RX.search(s)))
    out["kind"] = out["ext"].map(lambda e: "הארכה" if e else "קטע ראשי")
    out["km_r"] = out["km"].round(1)
    out = out.sort_values(["km", "name", "line_id"], ascending=[False, True, True],
                          kind="mergesort").reset_index(drop=True)
    return out


def join_he(items):
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    last = items[-1]
    return ", ".join(items[:-1]) + " ו" + ("-" if last[:1].isdigit() or last[:1] == LRI else "") + last


def compute(frames):
    df = _prepare(frames["main"])
    n_seg = len(df)
    total = float(df["km"].sum())
    mains = df[~df["ext"]]
    exts = df[df["ext"]]
    main_km = float(mains["km"].sum())
    ext_km = float(exts["km"].sum())
    years = sorted(int(y) for y in df["year"].dropna().unique())
    lengt_sum = float(df["lengt"].sum()) if df["lengt"].notna().all() else None

    # ---- chart: length per segment -------------------------------------
    top = df.head(TOP_SEG)
    rest = df.iloc[TOP_SEG:]
    seg_names = list(top["name"])
    seg_km = [float(v) for v in top["km_r"]]
    seg_kind = list(top["kind"])
    if len(rest):
        seg_names.append(f"אחר ({len(rest):,} קטעים)")
        seg_km.append(round(float(rest["km"].sum()), 1))
        seg_kind.append("אחר")
    chart_seg = {"names": seg_names, "km": seg_km, "kind": seg_kind,
                 "share": [round(v / total * 100, 1) for v in seg_km]}
    tbl_seg = [{
        "name": r.name, "line_id": r.line_id or "-", "kind": r.kind,
        "km": km(r.km), "lengt": (f"{int(r.lengt):,}" if pd.notna(r.lengt) else "-"),
        "year": (str(int(r.year)) if pd.notna(r.year) else "-"),
        "share": pct(r.km / total),
    } for r in df.itertuples()]

    # ---- chart: main lines vs extensions --------------------------------
    kind_rows = [(k, float(df.loc[df["kind"] == k, "km"].sum()), int((df["kind"] == k).sum()))
                 for k in ("קטע ראשי", "הארכה") if (df["kind"] == k).any()]
    chart_kind = {"names": [k for k, _, _ in kind_rows],
                  "km": [round(v, 1) for _, v, _ in kind_rows],
                  "count": [c for _, _, c in kind_rows]}
    tbl_kind = [{"name": k, "count": f"{c:,}", "km": km(v), "share": pct(v / total)}
                for k, v, c in kind_rows]

    # ---- insights -------------------------------------------------------
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    def ins_longest():
        if n_seg < 2:
            return None
        a, b = df.iloc[0], df.iloc[1]
        share = a.km / total
        if share < LEAD_SHARE or a.km_r == b.km_r:
            return None
        return (f"הקטע הארוך ביותר הוא {iso(a['name'])}: {km(a.km)} ק\"מ, "
                f"כ-{pct(share)} מאורך הרשת. אחריו {iso(b['name'])} עם {km(b.km)} ק\"מ.")
    add("longest", ins_longest())

    def ins_split():
        if mains.empty or exts.empty:
            return None
        lead_txt = f"{len(mains):,} קטעים ראשיים" if len(mains) > 1 else "קטע ראשי אחד"
        return (f"{lead_txt} "
                f"({join_he(iso(s) for s in sorted(mains['name']))}) "
                f"{'מצטברים' if len(mains) > 1 else 'משתרע'} ל-{km(main_km)} ק\"מ, {pct(main_km / total)} מהרשת; "
                f"{'ההארכות מוסיפות' if len(exts) > 1 else 'ההארכה מוסיפה'} {km(ext_km)} ק\"מ "
                f"({pct(ext_km / total)}).")
    add("split", ins_split())

    def ins_shortest():
        if n_seg < 3:
            return None
        z = df.iloc[-1]
        return (f"הקטע הקצר ביותר הוא {iso(z['name'])}, באורך {km(z.km)} ק\"מ בלבד "
                f"({pct(z.km / total)} מהרשת).")
    add("shortest", ins_shortest())

    def ins_horizon():
        if not years:
            return None
        if len(years) == 1:
            all_txt = "שני הקטעים" if n_seg == 2 else f"כל {n_seg:,} הקטעים"
            return (f"{all_txt} מסומנים לשנת היעד {years[0]}: זהו מצב מתוכנן, "
                    "ולא תיאור של קווים פעילים או בביצוע.")
        by = df.dropna(subset=["year"]).groupby("year")["km"].sum().sort_index()
        parts = [f"{km(v)} ק\"מ לשנת {int(y)}" for y, v in by.items()]
        return "הקטעים מתחלקים לפי שנת יעד: " + join_he(parts) + "."
    add("horizon", ins_horizon())

    def ins_rounding():
        if lengt_sum is None or abs(total - lengt_sum) < ROUND_GAP_KM:
            return None
        return (f"שדה האורך המעוגל בקובץ מסתכם ב-{lengt_sum:,.0f} ק\"מ, אך האורך המדוד "
                f"של התוואים בשכבת ה-GIS הוא {km(total)} ק\"מ; העמוד מציג את האורך המדוד.")
    add("rounding", ins_rounding())

    # ---- KPIs -----------------------------------------------------------
    year_disp = (str(years[0]) if len(years) == 1
                 else (f"{years[0]}–{years[-1]}" if years else "-"))
    kpis = {
        "segments": {"value": n_seg, "display": f"{n_seg:,}", "tone": "brand"},
        "length": {"value": round(total, 1), "display": km(total), "tone": "brand"},
        "year": {"value": years[-1] if years else None, "display": year_disp, "tone": "info"},
        "main": {"value": round(main_km / total * 100, 1), "display": pct(main_km / total),
                 "tone": "brand"},
    }

    lead = df.iloc[0]
    year_txt = (f"לשנת היעד {years[0]}" if len(years) == 1
                else (f"לשנים {years[0]}-{years[-1]}" if years else ""))
    labels = {
        "lede": (f"שכבת ה-GIS של משרד התחבורה מתארת את קווי המטרו המתוכננים במטרופולין ירושלים: "
                 f"{n_seg:,} קטעים באורך מדוד כולל של {km(total)} ק\"מ {year_txt}. "
                 f"הקטע הארוך ביותר הוא {iso(lead['name'])} ({km(lead.km)} ק\"מ). "
                 "המאגר הוא מצב תכנוני ולא לוח זמנים לביצוע; תוואי הקווים עצמם נמצאים בקובצי ה-SHP וה-KML להורדה."),
        "segments_kpi": "קטעי מטרו מתוכננים",
        "length_kpi": "אורך כולל (ק\"מ, לפי GIS)",
        "year_kpi": "שנת היעד בתכנון",
        "main_kpi": "מהאורך בקטעים הראשיים",
        "seg_note": (f"אורך כל קטע בק\"מ, לפי האורך המדוד בשכבת ה-GIS. "
                     f"{iso(lead['name'])} מוביל עם {km(lead.km)} ק\"מ."
                     + (f" מוצגים {TOP_SEG:,} הקטעים הארוכים; השאר תחת \"אחר\"." if len(rest) else "")),
        "seg_aria": (f"גרף עמודות אופקי: אורך {n_seg:,} קטעי המטרו המתוכננים בירושלים בק\"מ. "
                     f"הארוך ביותר: {lead['name']} עם {km(lead.km)} ק\"מ."),
        "seg_caption": "קטעי המטרו המתוכננים במטרופולין ירושלים: אורך ושנת יעד",
        "kind_note": (f"קטעים ראשיים מול קטעי הארכה: {km(main_km)} ק\"מ מול {km(ext_km)} ק\"מ."
                      if len(kind_rows) == 2 else
                      f"כל {n_seg:,} הקטעים מסווגים כ{kind_rows[0][0]}."),
        "kind_aria": ("גרף עמודה מוערמת: חלוקת אורך רשת המטרו בין קטעים ראשיים להארכות, "
                      f"{km(main_km)} ק\"מ מול {km(ext_km)} ק\"מ."),
        "kind_caption": "אורך רשת המטרו לפי סוג קטע",
    }

    summary = (f"מטרו ירושלים: {n_seg:,} קטעי קווי מטרו מתוכננים במטרופולין ירושלים, "
               f"{km(total)} ק\"מ" + (f" לשנת {years[-1]}" if years else "")
               + f". אורך כל קטע, קטעים ראשיים והארכות.")

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "misc",
            "suggested_tags": ["מטרו", "ירושלים", "הסעת המונים", "תחבורה ציבורית", "תכנון תחבורה"],
            "related_ids": ["5ecf0587-21e6-411a-8f04-9f4f44a43956",
                            "068ff53c-ad54-4848-8a29-bd9b178d9174",
                            "b65ae5cf-8aab-4b8e-ae08-de941368fff0",
                            "f10f7f97-7a1a-4516-9549-3f7025af5768"],
            "spatial_coverage": "מטרופולין ירושלים",
        },
        "kpis": kpis,
        "charts": {"seg": chart_seg, "kind": chart_kind},
        "tables": {"seg": tbl_seg, "kind": tbl_kind},
        "flags": {"kind": len(kind_rows) == 2},
        "insights": insights,
        "labels": labels,
        "links": {
            "jlm2050": "/datasets/5ecf0587-21e6-411a-8f04-9f4f44a43956/",
            "jlm2040": "/datasets/068ff53c-ad54-4848-8a29-bd9b178d9174/",
            "lrt": "/datasets/b65ae5cf-8aab-4b8e-ae08-de941368fff0/",
            "tlv_metro": "/datasets/f10f7f97-7a1a-4516-9549-3f7025af5768/",
        },
    }
