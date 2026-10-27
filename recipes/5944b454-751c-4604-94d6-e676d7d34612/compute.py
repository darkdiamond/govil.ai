"""עצים באר שבע — one row per tree location: WGS84/ITM position plus, for the
documented part of the inventory, a tag number, species, street and
neighbourhood.  Most rows are bare coordinates, so the page is about WHERE the
trees are (density map) and what the documented part reveals (species mix,
neighbourhoods, streets, diversity) and how much is documented at all.

The CSV, XLSX and ITM resources are twins of one table; only the CSV is read.
Order-independent: integer counts and sorted aggregates only.
"""
import math

import pandas as pd

LAT_RANGE = (29.0, 34.0)
LON_RANGE = (34.0, 36.0)
CELL_DEG = 0.002
TOP_SPECIES = 15
TOP_GENUS = 10
TOP_NEIGH = 15
TOP_STREETS = 15
MIX_NEIGH = 8
MIX_SPECIES = 5
RICH_MIN_TREES = 30
RICH_TOP = 12
LEAD_SHARE = 0.05
CONC_TOP = 5
CONC_SHARE = 0.30
GENUS_SHARE = 0.10
NEIGH_SHARE = 0.08
STREET_SHARE = 0.02
DENSE_CELL_PCT = 0.10
DENSE_SHARE = 0.40
NO_SPECIES = {"", "לא קיים"}
OTHER = "אחר"

# Spelling variants of the same species / place in the source, merged on read.
SPECIES_ALIAS = {
    "סיגלון עלה מימוזה": "סיגלון עלי מימוסה",
    "אלביציה וורודה": "אלביציה ורודה",
    "אקליפטוס טורלי": "אקליפטוס טורל",
    "אקליפטוס צווארון": "אקליפטוס הצווארון",
    "בוהניה ססגונית": "בוהיניה מגוונת",
    "פיקוס בנימונה": "פיקוס בנימינה",
    "זית אירופי": "זית אירופאי",
    "קופניון אנקרדי": "קופיניון אנרקדי",
    "בונגה": "מיש בונגה",
}
NEIGH_ALIAS = {"פארק נחל באר ש": "פארק נחל בש"}
NEIGH_DISPLAY = {"פארק נחל בש": "פארק נחל באר שבע"}


def _int(n):
    return f"{int(n):,}"


def _pct(x, digits=0):
    return f"{x * 100:.{digits}f}%"


def _norm_species(s):
    s = " ".join(s.split()).replace("ברכיכיטון", "ברכיכטון")
    return SPECIES_ALIAS.get(s, s)


def _prepare(df):
    out = pd.DataFrame(index=df.index)
    out["latf"] = pd.to_numeric(df["lat"].str.strip(), errors="coerce")
    out["lonf"] = pd.to_numeric(df["lon"].str.strip(), errors="coerce")
    raw_sp = df["tree_speci"].map(lambda s: " ".join(s.split()))
    out["sp"] = raw_sp.map(_norm_species)
    out["nb"] = df["neighborho"].map(lambda s: " ".join(s.split())).map(lambda s: NEIGH_ALIAS.get(s, s))
    out["st"] = df["street_nam"].map(lambda s: " ".join(s.split()))
    out["tag"] = pd.to_numeric(df["plate_num"].str.strip(), errors="coerce").fillna(0) > 0
    ok = out["latf"].between(*LAT_RANGE) & out["lonf"].between(*LON_RANGE)
    n_bad = int((~ok).sum())
    out = out[ok].copy()
    out["spk"] = ~out["sp"].isin(NO_SPECIES)
    out["spelling_merged"] = (raw_sp[ok].map(lambda s: s != _norm_species(s)) & ~raw_sp[ok].isin(NO_SPECIES))
    out["genus"] = out["sp"].map(lambda s: s.split(" ")[0] if s else "")
    out["nbk"] = out["nb"] != ""
    out["stk"] = out["st"] != ""
    return out.reset_index(drop=True), n_bad


def _ranked(series, top=None):
    vc = series.value_counts()
    items = sorted(((k, int(v)) for k, v in vc.items()), key=lambda kv: (-kv[1], kv[0]))
    return items[:top] if top else items


def _rows(items, total):
    return [{"name": k, "count": _int(v), "share": _pct(v / total, 1)} for k, v in items]


def _neigh_name(n):
    return NEIGH_DISPLAY.get(n, n)


def compute(frames):
    df, n_bad = _prepare(frames["trees"])
    total = len(df)
    sp = df[df["spk"]]
    n_sp_rows = len(sp)
    nb = df[df["nbk"]]
    st = df[df["stk"]]

    species_all = _ranked(sp["sp"])
    genus_all = _ranked(sp["genus"])
    neigh_all = _ranked(nb["nb"])
    street_all = _ranked(st["st"])

    # --- species chart (+ cumulative share in the table)
    top_sp = species_all[:TOP_SPECIES]
    cum = 0
    t_species = []
    for k, v in top_sp:
        cum += v
        t_species.append({"name": k, "count": _int(v), "share": _pct(v / n_sp_rows, 1),
                          "cum": _pct(cum / n_sp_rows, 1)})
    species_chart = {"names": [k for k, _ in top_sp], "values": [v for _, v in top_sp]}

    top_ge = genus_all[:TOP_GENUS]
    genus_chart = {"names": [k for k, _ in top_ge], "values": [v for _, v in top_ge]}
    t_genus = _rows(top_ge, n_sp_rows)

    # --- neighbourhoods (all trees with a neighbourhood)
    top_nb = neigh_all[:TOP_NEIGH]
    rest = sum(v for _, v in neigh_all[TOP_NEIGH:])
    nb_items = [(_neigh_name(k), v) for k, v in top_nb] + ([(OTHER, rest)] if rest else [])
    neigh_chart = {"names": [k for k, _ in nb_items], "values": [v for _, v in nb_items]}
    t_neigh = _rows(nb_items, len(nb))

    # --- streets
    top_st = street_all[:TOP_STREETS]
    streets_chart = {"names": [k for k, _ in top_st], "values": [v for _, v in top_st]}
    t_streets = _rows(top_st, len(st))

    # --- species mix by neighbourhood (100% stacked)
    sn = sp[sp["nbk"]]
    nb_sp_tot = _ranked(sn["nb"])
    mix_nb = [k for k, _ in nb_sp_tot[:MIX_NEIGH]]
    mix_sp = [k for k, _ in _ranked(sn["sp"], MIX_SPECIES)]
    piv = sn.groupby(["nb", "sp"]).size()
    nb_tot = {k: v for k, v in nb_sp_tot}
    mix_series = []
    for s in mix_sp:
        mix_series.append({"name": s, "data": [round(int(piv.get((n, s), 0)) / nb_tot[n] * 100, 1) for n in mix_nb]})
    other = [round((nb_tot[n] - sum(int(piv.get((n, s), 0)) for s in mix_sp)) / nb_tot[n] * 100, 1) for n in mix_nb]
    mix_series.append({"name": OTHER, "data": other})
    mix_names = [_neigh_name(n) for n in mix_nb]
    mix_chart = {"names": mix_names, "series": mix_series}
    t_mix = {"cols": mix_sp + [OTHER],
             "rows": [{"name": mix_names[i], "vals": [f"{s['data'][i]:.1f}%" for s in mix_series]}
                      for i in range(len(mix_nb))]}

    # --- species richness by neighbourhood
    rich = []
    for n, cnt in nb_sp_tot:
        if cnt >= RICH_MIN_TREES:
            sub = sn[sn["nb"] == n]
            rich.append((n, int(sub["sp"].nunique()), cnt))
    rich.sort(key=lambda r: (-r[1], -r[2], r[0]))
    rich = rich[:RICH_TOP]
    rich_chart = {"names": [_neigh_name(r[0]) for r in rich], "values": [r[1] for r in rich]}
    t_rich = [{"name": _neigh_name(r[0]), "species": _int(r[1]), "trees": _int(r[2])} for r in rich]

    # --- completeness
    fields = [("מספר תג", int(df["tag"].sum())), ("מין העץ", n_sp_rows),
              ("שכונה", len(nb)), ("רחוב", len(st))]
    fields_chart = {"names": [k for k, _ in fields], "values": [v for _, v in fields],
                    "pct": [round(v / total * 100, 1) for _, v in fields]}
    t_fields = _rows(fields, total)

    # --- density map on a fixed-degree grid
    ci = (df["latf"] // CELL_DEG).astype(int)
    cj = (df["lonf"] // CELL_DEG).astype(int)
    grp = df.assign(ci=ci, cj=cj).groupby(["ci", "cj"]).agg(n=("tag", "size"), doc=("spk", "sum"))
    cells = []
    for (a, b), r in sorted(grp.iterrows(), key=lambda kv: kv[0]):
        cells.append([round((a + 0.5) * CELL_DEG, 4), round((b + 0.5) * CELL_DEG, 4), int(r["n"]), int(r["doc"])])
    max_cell = max(c[2] for c in cells)
    map_chart = {"cells": cells, "max": max_cell, "cell_deg": CELL_DEG,
                 "bounds": [[min(c[0] for c in cells) - CELL_DEG / 2, min(c[1] for c in cells) - CELL_DEG / 2],
                            [max(c[0] for c in cells) + CELL_DEG / 2, max(c[1] for c in cells) + CELL_DEG / 2]]}
    counts_sorted = sorted((c[2] for c in cells), reverse=True)
    n_top = max(1, math.ceil(len(cells) * DENSE_CELL_PCT))
    top_share = sum(counts_sorted[:n_top]) / total
    cell_m = int(round(CELL_DEG * math.radians(1) * 6371008.8))

    # --- insights
    insights = []

    def add(i, t):
        if t:
            insights.append({"id": i, "text_he": t})

    doc_share = n_sp_rows / total
    add("docs", f"רק {_pct(doc_share, 1)} מהמיקומים במאגר ({_int(n_sp_rows)} מתוך {_int(total)}) כוללים מין עץ; "
        f"ביתר ({_int(total - n_sp_rows)}) מתועד המיקום בלבד." if doc_share < 0.5 else
        f"{_pct(doc_share, 1)} מהמיקומים במאגר ({_int(n_sp_rows)} מתוך {_int(total)}) כוללים מין עץ." if n_sp_rows else None)
    if species_all and species_all[0][1] / n_sp_rows >= LEAD_SHARE:
        (a, av) = species_all[0]
        second = (f", לפני ״{species_all[1][0]}״ עם {_int(species_all[1][1])}" if len(species_all) > 1 else "")
        add("leader", f"המין הנפוץ ביותר בין העצים המתועדים הוא ״{a}״: {_int(av)} עצים "
            f"({_pct(av / n_sp_rows, 1)}){second}.")
    if len(species_all) > CONC_TOP:
        top_n = sum(v for _, v in species_all[:CONC_TOP])
        if top_n / n_sp_rows >= CONC_SHARE:
            add("concentration", f"{_int(CONC_TOP)} המינים הנפוצים ביותר מהווים {_pct(top_n / n_sp_rows, 1)} "
                f"מהעצים המתועדים, מתוך {_int(len(species_all))} מינים שונים במאגר.")
    if genus_all and genus_all[0][1] / n_sp_rows >= GENUS_SHARE:
        g, gv = genus_all[0]
        n_var = len({k for k, _ in species_all if k.split(" ")[0] == g})
        if n_var > 1:
            add("genus", f"כשמאחדים לפי המילה הראשונה בשם, הקבוצה הגדולה היא ״{g}״: {_int(gv)} עצים "
                f"({_pct(gv / n_sp_rows, 1)}) בתוך {_int(n_var)} שמות מין.")
    if neigh_all and neigh_all[0][1] / len(nb) >= NEIGH_SHARE:
        (a, av) = neigh_all[0]
        add("neigh", f"מבין העצים עם שכונה ({_int(len(nb))}), הריכוז הגדול ביותר הוא ב״{_neigh_name(a)}״: "
            f"{_int(av)} עצים ({_pct(av / len(nb), 1)}).")
    if street_all and street_all[0][1] / len(st) >= STREET_SHARE:
        (a, av) = street_all[0]
        add("street", f"הרחוב עם הכי הרבה עצים רשומים הוא ״{a}״ עם {_int(av)} עצים "
            f"({_pct(av / len(st), 1)} מהעצים שיש להם רחוב).")
    if len(rich) >= 3:
        add("richness", f"השכונה עם מגוון המינים הגדול ביותר היא ״{_neigh_name(rich[0][0])}״: "
            f"{_int(rich[0][1])} מינים בין {_int(rich[0][2])} עצים מתועדים (שכונות עם לפחות "
            f"{_int(RICH_MIN_TREES)} עצים מתועדים).")
    if top_share >= DENSE_SHARE:
        add("dense", f"{_pct(top_share, 1)} מהעצים נמצאים בעשירית הצפופה ביותר מתאי המפה "
            f"({_int(n_top)} תאים בגודל של כ-{_int(cell_m)} מטרים); התא הצפוף ביותר מכיל {_int(max_cell)} עצים.")
    n_merge = int(df["spelling_merged"].sum())
    if n_merge:
        add("spelling", f"במאגר נכתבים חלק מהמינים בכמה איותים; "
            f"איחדנו {_int(n_merge)} רשומות לשם אחד, כך שכל מין נספר פעם אחת.")

    kpis = {
        "total": {"value": total, "display": _int(total), "tone": "brand",
                  "label": "מיקומי עצים במאגר"},
        "documented": {"value": n_sp_rows, "display": _int(n_sp_rows),
                       "tone": "ok" if doc_share >= 0.5 else "warn",
                       "label": f"עצים עם מין מתועד ({_pct(doc_share)} מהמאגר)"},
        "species": {"value": len(species_all), "display": _int(len(species_all)), "tone": "info",
                    "label": "מינים שונים"},
        "neigh": {"value": len(neigh_all), "display": _int(len(neigh_all)), "tone": "brand",
                  "label": "שכונות ואזורים עם עצים מתועדים"},
    }

    lede = (f"המאגר ממפה {_int(total)} מיקומי עצים בעיר. לכ-{_pct(doc_share)} מהם מתועדים גם מין, שכונה ורחוב; "
            f"שאר הרשומות כוללות קואורדינטות בלבד. שמות מין שנכתבו בכמה איותים אוחדו.")
    labels = {
        "lede": lede,
        "map_note": (f"כל עיגול הוא תא של כ-{_int(cell_m)} מטרים; גודלו וצבעו לפי מספר העצים בו. "
                     f"לחיצה על עיגול מציגה את מספר העצים ואת מספר העצים עם מין מתועד."),
        "species_note": f"{_int(len(top_sp))} המינים הנפוצים בין {_int(n_sp_rows)} העצים עם מין מתועד.",
        "species_aria": "תרשים עמודות אופקי של המינים הנפוצים ביותר",
        "species_caption": "המינים הנפוצים ביותר, מספר עצים ושיעור מצטבר",
        "genus_note": "איחוד לפי המילה הראשונה בשם המין (למשל כל מיני האקליפטוס יחד).",
        "genus_aria": "תרשים עמודות אופקי של קבוצות המינים הגדולות",
        "genus_caption": "קבוצות מינים לפי המילה הראשונה בשם",
        "neigh_note": f"עצים שלהם שכונה רשומה ({_int(len(nb))} מתוך {_int(total)}).",
        "neigh_aria": "תרשים עמודות אופקי של מספר העצים לפי שכונה",
        "neigh_caption": "מספר העצים לפי שכונה",
        "mix_note": f"הרכב המינים ב-{_int(len(mix_nb))} השכונות עם הכי הרבה עצים מתועדים, באחוזים מכלל העצים המתועדים בשכונה.",
        "mix_aria": "תרשים עמודות מוערמות של הרכב המינים בשכונות",
        "mix_caption": "הרכב המינים בשכונות, באחוזים",
        "rich_note": f"מספר המינים השונים בשכונות עם לפחות {_int(RICH_MIN_TREES)} עצים מתועדים.",
        "rich_aria": "תרשים עמודות של מספר המינים השונים בכל שכונה",
        "rich_caption": "מספר מינים ועצים מתועדים בשכונה",
        "streets_note": f"הרחובות עם הכי הרבה עצים רשומים, מתוך {_int(len(st))} עצים שיש להם רחוב.",
        "streets_aria": "תרשים עמודות אופקי של הרחובות עם הכי הרבה עצים",
        "streets_caption": "הרחובות עם הכי הרבה עצים",
        "fields_note": "כמה מהמיקומים כוללים כל שדה; ההפרש מ-100% הוא רשומות עם קואורדינטות בלבד.",
        "fields_aria": "תרשים עמודות אופקי של שיעור המילוי של כל שדה",
        "fields_caption": "שיעור המילוי של כל שדה",
    }

    summary = (f"מאגר של {_int(total)} מיקומי עצים בבאר שבע; לכ-{_pct(doc_share)} מהם מתועד מין "
               f"({_int(len(species_all))} מינים שונים), שכונה ורחוב.")
    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "map",
            "suggested_tags": ["עצים", "באר שבע", "גינון עירוני", "סביבה", "תכנון עיר וגיאוגרפיה"],
            "related_ids": ["b795e2e0-491e-4040-877e-f3681917f8be",
                            "82a30a97-01b0-4281-854c-c7931f3445c0",
                            "bdf28cc0-680a-415c-af64-944a58079b2f"],
            "spatial_coverage": "באר שבע",
        },
        "kpis": kpis,
        "charts": {"map": map_chart, "species": species_chart, "genus": genus_chart, "neigh": neigh_chart,
                   "mix": mix_chart, "rich": rich_chart, "streets": streets_chart, "fields": fields_chart},
        "tables": {"species": t_species, "genus": t_genus, "neigh": t_neigh, "mix": t_mix,
                   "rich": t_rich, "streets": t_streets, "fields": t_fields},
        "flags": {"has_species": bool(species_all), "has_genus": len(genus_all) > 1,
                  "has_neigh": bool(neigh_all), "has_mix": len(mix_nb) >= 2, "has_rich": len(rich) >= 3,
                  "has_streets": bool(street_all)},
        "insights": insights,
        "labels": labels,
    }
