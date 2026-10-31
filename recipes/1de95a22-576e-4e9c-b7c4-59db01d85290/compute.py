"""Urban-renewal GIS layers (Ministry of Construction and Housing).

Two committed map snapshots, no datastore:
  declared     – declared urban-renewal compounds (polygons + attributes)
  masterplans  – municipal urban-renewal master plans (polygons + status)

Units: yachadKaya = existing housing units, yachadMutz = proposed units,
YachadTosa = added units (proposed − existing). taarichTok = the date the
compound's plan came into force (YYYYMMDD; empty = not yet in force).
TeurSugMas = declaration track (tax track / local-authority track / not
yet declared). Shape_STAr = polygon area in m² (ITM).
"""
from __future__ import annotations

import json
import math
import re

import pandas as pd

TOP_N = 12          # category bars (mobile-friendly)
MIN_CITY_N = 10     # compounds a city needs for the median-multiplier chart
YEARS_SHOWN = 15    # yearly approvals: last N years, older ones bucketed
MAP_CHUNK = 250     # points per JSON island (~30KB each)
POLY_CHUNK_CHARS = 40000
EMPTY_LABEL = "לא צוין"


# ── helpers ──────────────────────────────────────────────────────────────

def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.astype(str).str.replace(",", "", regex=False).str.strip(),
                         errors="coerce")


def _fmt(v) -> str:
    return f"{int(round(v)):,}"


def _pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def _city_key(name: str) -> str:
    """Join key across the two layers ('גבעתים' vs 'גבעתיים', 'פרדס חנה-כרכור')."""
    k = re.sub(r"[\s\-־]", "", name or "")
    return k.replace("יי", "י")


def _ring_area_centroid(ring):
    a = cx = cy = 0.0
    n = len(ring)
    for i in range(n - 1):
        x1, y1 = ring[i][0], ring[i][1]
        x2, y2 = ring[i + 1][0], ring[i + 1][1]
        cr = x1 * y2 - x2 * y1
        a += cr
        cx += (x1 + x2) * cr
        cy += (y1 + y2) * cr
    return a / 2.0, cx, cy


def _outer_rings(geom: dict):
    t = geom.get("type")
    if t == "Polygon":
        return [geom["coordinates"][0]] if geom.get("coordinates") else []
    if t == "MultiPolygon":
        return [p[0] for p in geom.get("coordinates") or [] if p]
    return []


def _centroid(geoms: list[dict]):
    """Area-weighted centroid (lon, lat) over every outer ring of every part."""
    rings = []
    for g in geoms:
        rings.extend(_outer_rings(g))
    rings.sort(key=lambda r: json.dumps(r))
    A = SX = SY = 0.0
    for r in rings:
        a, cx, cy = _ring_area_centroid(r)
        A += a
        SX += cx
        SY += cy
    if abs(A) > 1e-14:
        return SX / (6.0 * A), SY / (6.0 * A)
    pts = [p for r in rings for p in r]
    if not pts:
        return None
    return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)


def _parse_geom(s: str):
    try:
        g = json.loads(s) if s else None
    except (ValueError, TypeError):
        return None
    return g if isinstance(g, dict) else None


def _round_geom(g: dict, nd: int = 4) -> dict:
    def r(c):
        if isinstance(c, list) and c and isinstance(c[0], (int, float)):
            return [round(c[0], nd), round(c[1], nd)]
        return [r(x) for x in c]
    return {"type": g["type"], "coordinates": r(g["coordinates"])}


def _bucket_label(lo, hi):
    if hi is None:
        return f"{lo:,}+"
    return f"{lo:,}-{hi:,}"


# ── loading ──────────────────────────────────────────────────────────────

def _load_declared(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for c in ["MisparProj", "ShemMitcha", "Yeshuv", "plan_name", "TeurMaslul",
              "TeurSugMas", "taarichTok"]:
        df[c] = df[c].astype(str).str.strip()
    df["kaya"] = _num(df["yachadKaya"]).fillna(0)
    df["mutz"] = _num(df["yachadMutz"]).fillna(0)
    df["tosa"] = _num(df["YachadTosa"]).fillna(0)
    df["area"] = _num(df["Shape_STAr"]).fillna(0)
    df["date"] = pd.to_datetime(df["taarichTok"], format="%Y%m%d", errors="coerce")
    df["geom"] = df["__geometry"].map(_parse_geom)
    df = df[df["Yeshuv"] != ""]
    # The same project can appear as several features (one per polygon part,
    # attributes repeated): one compound per MisparProj, geometry merged.
    df["proj"] = df["MisparProj"].where(df["MisparProj"] != "",
                                        df["ShemMitcha"] + "|" + df["Yeshuv"])
    attr_cols = ["proj", "ShemMitcha", "Yeshuv", "plan_name", "TeurMaslul",
                 "TeurSugMas", "taarichTok", "kaya", "mutz", "tosa", "area"]
    df = df.sort_values(attr_cols, kind="mergesort")
    geoms = df.groupby("proj", sort=True)["geom"].agg(
        lambda s: [g for g in s if g])
    first = df.drop_duplicates("proj", keep="first").set_index("proj")
    first["geoms"] = geoms
    first = first.reset_index().sort_values("proj", kind="mergesort").reset_index(drop=True)
    first["track"] = first["TeurSugMas"].replace("", EMPTY_LABEL)
    first["maslul"] = first["TeurMaslul"].replace("", EMPTY_LABEL)
    first["approved"] = first["date"].notna()
    return first


def _load_masterplans(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for c in ["MisparProj", "ShemMitcha", "Yeshuv", "statusTich"]:
        df[c] = df[c].astype(str).str.strip()
    df["area"] = _num(df["Shape_STAr"]).fillna(0)
    df["geom"] = df["__geometry"].map(_parse_geom)
    df["proj"] = df["MisparProj"].where(df["MisparProj"] != "",
                                        df["ShemMitcha"] + "|" + df["Yeshuv"])
    df = df.sort_values(["proj", "ShemMitcha", "Yeshuv", "statusTich", "area"],
                        kind="mergesort")
    geoms = df.groupby("proj", sort=True)["geom"].agg(lambda s: [g for g in s if g])
    first = df.drop_duplicates("proj", keep="first").set_index("proj")
    first["geoms"] = geoms
    first = first.reset_index().sort_values(["Yeshuv", "ShemMitcha", "proj"],
                                            kind="mergesort").reset_index(drop=True)
    first["status"] = first["statusTich"].replace("", EMPTY_LABEL)
    return first


# ── main ─────────────────────────────────────────────────────────────────

def compute(frames):
    d = _load_declared(frames["declared"])
    mp = _load_masterplans(frames["masterplans"])
    n = len(d)
    n_raw = len(frames["declared"])
    if n == 0:
        raise ValueError("no declared compounds")

    labels: dict = {}
    charts: dict = {}
    tables: dict = {}
    flags: dict = {}
    insights: list = []

    n_cities = d["Yeshuv"].nunique()
    sum_kaya = float(d["kaya"].sum())
    sum_mutz = float(d["mutz"].sum())
    sum_tosa = float(d["tosa"].sum())
    n_appr = int(d["approved"].sum())
    appr_share = n_appr / n
    n_mp = len(mp)
    mp_cities = mp["Yeshuv"].nunique() if n_mp else 0

    # Track order: by count desc, then name.
    tc = d.groupby("track").size().reset_index(name="n")
    tc = tc.sort_values(["n", "track"], ascending=[False, True], kind="mergesort")
    tracks = tc["track"].tolist()

    # ── KPIs ────────────────────────────────────────────────────────────
    kpis = {
        "compounds": {"value": n, "display": _fmt(n), "tone": "brand"},
        "cities": {"value": int(n_cities), "display": _fmt(n_cities), "tone": "brand"},
        "planned": {"value": int(sum_mutz), "display": _fmt(sum_mutz), "tone": "brand"},
        "added": {"value": int(sum_tosa), "display": _fmt(sum_tosa), "tone": "ok" if sum_tosa > 0 else "brand"},
        "approved": {"value": round(appr_share, 4), "display": _pct(appr_share),
                     "tone": "ok" if appr_share >= 0.5 else "warn"},
    }
    kpi_order = ["compounds", "cities", "planned", "added", "approved"]
    labels["kpi_compounds"] = "מתחמי התחדשות עירונית בשכבה"
    labels["kpi_cities"] = "יישובים עם מתחם"
    labels["kpi_planned"] = "יחידות דיור מוצעות"
    labels["kpi_added"] = "תוספת יחידות דיור (מוצע פחות קיים)"
    labels["kpi_approved"] = "מהמתחמים עם תוכנית בתוקף"
    if n_mp:
        kpis["masterplans"] = {"value": n_mp, "display": _fmt(n_mp), "tone": "info"}
        kpi_order.append("masterplans")
        labels["kpi_masterplans"] = "תוכניות מתאר להתחדשות עירונית"

    # ── per-city aggregates ─────────────────────────────────────────────
    city = d.groupby("Yeshuv").agg(n=("proj", "size"), kaya=("kaya", "sum"),
                                   mutz=("mutz", "sum"), tosa=("tosa", "sum"),
                                   appr=("approved", "sum")).reset_index()
    city = city.sort_values(["n", "mutz", "Yeshuv"], ascending=[False, False, True],
                            kind="mergesort").reset_index(drop=True)

    # Chart: compounds per city, stacked by declaration track.
    top = city.head(TOP_N)
    rest = city.iloc[TOP_N:]
    names = top["Yeshuv"].tolist()
    ct = d.groupby(["Yeshuv", "track"]).size()
    series = []
    for t in tracks:
        vals = [int(ct.get((c, t), 0)) for c in names]
        if len(rest):
            vals.append(int(sum(ct.get((c, t), 0) for c in rest["Yeshuv"])))
        series.append({"name": t, "data": vals})
    cats = names + ([f"שאר היישובים ({len(rest):,})"] if len(rest) else [])
    charts["cities"] = {"names": cats, "series": series}
    tables["cities"] = []
    for i, c in enumerate(cats):
        row = {"name": c, "n": _fmt(sum(s["data"][i] for s in series))}
        row["by"] = [_fmt(s["data"][i]) for s in series]
        tables["cities"].append(row)
    labels["track_names"] = tracks
    lead = city.iloc[0]
    top5 = city.head(5)
    labels["cities_lede"] = (
        f"{lead['Yeshuv']} מובילה עם {_fmt(lead['n'])} מתחמים ({_pct(lead['n'] / n)} מכלל המתחמים). "
        f"חמשת היישובים המובילים מרכזים {_pct(top5['n'].sum() / n)} מהמתחמים."
    )
    labels["cities_aria"] = (
        f"גרף עמודות מוערמות: מספר מתחמי ההתחדשות העירונית ב-{len(names)} היישובים המובילים, לפי מסלול הכרזה. "
        f"בראש: {lead['Yeshuv']} עם {_fmt(lead['n'])} מתחמים."
    )
    if lead["n"] / n >= 0.1 and len(city) >= 3:
        insights.append({"id": "concentration", "text_he": (
            f"{lead['Yeshuv']} מרכזת {_fmt(lead['n'])} מתוך {_fmt(n)} המתחמים ({_pct(lead['n'] / n)}), "
            f"וחמשת היישובים המובילים ({', '.join(top5['Yeshuv'])}) מרכזים יחד {_pct(top5['n'].sum() / n)} מהם."
        )})

    # Chart: housing units per city (existing vs added), top by proposed units.
    cu = city.sort_values(["mutz", "n", "Yeshuv"], ascending=[False, False, True],
                          kind="mergesort").head(TOP_N)
    charts["units_city"] = {
        "names": cu["Yeshuv"].tolist(),
        "kaya": [int(v) for v in cu["kaya"]],
        "tosa": [int(v) for v in cu["tosa"]],
        "mutz": [int(v) for v in cu["mutz"]],
    }
    tables["units_city"] = [
        {"name": r.Yeshuv, "kaya": _fmt(r.kaya), "tosa": _fmt(r.tosa), "mutz": _fmt(r.mutz),
         "mult": f"{r.mutz / r.kaya:.1f}" if r.kaya > 0 else "–"}
        for r in cu.itertuples()
    ]
    u0 = cu.iloc[0]
    labels["units_lede"] = (
        f"ב{u0['Yeshuv']} מתוכננות {_fmt(u0['mutz'])} יחידות דיור במתחמים, במקום {_fmt(u0['kaya'])} קיימות. "
        f"בכלל המתחמים: {_fmt(sum_mutz)} יחידות מוצעות במקום {_fmt(sum_kaya)} קיימות."
    )
    labels["units_aria"] = (
        f"גרף עמודות מוערמות: יחידות דיור קיימות ותוספת מתוכננת ב-{len(cu)} היישובים עם הכי הרבה יחידות מוצעות. "
        f"בראש: {u0['Yeshuv']} עם {_fmt(u0['mutz'])} יחידות מוצעות."
    )
    if sum_kaya > 0:
        insights.append({"id": "units", "text_he": (
            f"המתחמים מחליפים {_fmt(sum_kaya)} יחידות דיור קיימות ב-{_fmt(sum_mutz)} מוצעות: "
            f"תוספת של {_fmt(sum_tosa)} יחידות, פי {sum_mutz / sum_kaya:.1f} מהמצב הקיים."
        )})

    # Chart: declaration track (donut) — count + units.
    tr = d.groupby("track").agg(n=("proj", "size"), mutz=("mutz", "sum"),
                                appr=("approved", "sum")).reindex(tracks)
    charts["track"] = [{"name": t, "value": int(tr.loc[t, "n"])} for t in tracks]
    tables["track"] = [
        {"name": t, "n": _fmt(tr.loc[t, "n"]), "share": _pct(tr.loc[t, "n"] / n),
         "mutz": _fmt(tr.loc[t, "mutz"]), "appr": _pct(tr.loc[t, "appr"] / tr.loc[t, "n"])}
        for t in tracks
    ]
    labels["track_lede"] = "; ".join(
        f"{t}: {_fmt(tr.loc[t, 'n'])} מתחמים ({_pct(tr.loc[t, 'n'] / n)})" for t in tracks) + "."
    labels["track_aria"] = (
        f"גרף טבעת: חלוקת המתחמים לפי מסלול הכרזה. הגדול ביותר: {tracks[0]} עם {_fmt(tr.loc[tracks[0], 'n'])} מתחמים."
    )
    declared_tracks = [t for t in tracks if t not in ("טרם הוכרז", EMPTY_LABEL)]
    if len(declared_tracks) >= 2:
        a, b = declared_tracks[0], declared_tracks[1]
        na, nb = int(tr.loc[a, "n"]), int(tr.loc[b, "n"])
        not_yet = int(tr.loc["טרם הוכרז", "n"]) if "טרם הוכרז" in tr.index else 0
        txt = (f"מסלול {a} הוא הנפוץ ({_fmt(na)} מתחמים, {_pct(na / n)}), "
               f"לעומת {_fmt(nb)} במסלול {b} ({_pct(nb / n)}).")
        if not_yet:
            txt += f" עוד {_fmt(not_yet)} מתחמים ({_pct(not_yet / n)}) מסומנים כטרם הוכרזו."
        insights.append({"id": "track", "text_he": txt})

    # Chart: renewal type (TeurMaslul).
    ms = d.groupby("maslul").agg(n=("proj", "size"), mutz=("mutz", "sum")).reset_index()
    ms = ms.sort_values(["n", "maslul"], ascending=[False, True], kind="mergesort")
    charts["maslul"] = {"names": ms["maslul"].tolist(), "n": [int(v) for v in ms["n"]]}
    tables["maslul"] = [{"name": r.maslul, "n": _fmt(r.n), "share": _pct(r.n / n), "mutz": _fmt(r.mutz)}
                        for r in ms.itertuples()]
    stated = ms[ms["maslul"] != EMPTY_LABEL]
    n_stated = int(stated["n"].sum())
    n_unst = n - n_stated
    labels["maslul_lede"] = (
        (f"מבין {_fmt(n_stated)} המתחמים שסוג ההתחדשות בהם צוין, הנפוץ הוא {stated.iloc[0]['maslul']} "
         f"({_fmt(stated.iloc[0]['n'])} מתחמים). " if n_stated else "")
        + (f"ב-{_fmt(n_unst)} מתחמים סוג ההתחדשות לא צוין." if n_unst else "")
    ).strip()
    labels["maslul_aria"] = (
        f"גרף עמודות: מספר המתחמים לפי סוג ההתחדשות. הנפוץ: {ms.iloc[0]['maslul']} עם {_fmt(ms.iloc[0]['n'])} מתחמים."
    )
    if n_stated:
        s0 = stated.iloc[0]
        if s0["n"] / n_stated >= 0.5:
            insights.append({"id": "maslul", "text_he": (
                f"{s0['maslul']} הוא סוג ההתחדשות השולט: {_fmt(s0['n'])} מתוך {_fmt(n_stated)} המתחמים שסוגם צוין "
                f"({_pct(s0['n'] / n_stated)}). ב-{_fmt(n_unst)} מתחמים נוספים הסוג לא צוין."
                if n_unst else
                f"{s0['maslul']} הוא סוג ההתחדשות השולט: {_fmt(s0['n'])} מתוך {_fmt(n_stated)} המתחמים ({_pct(s0['n'] / n_stated)})."
            )})

    # Chart: plans coming into force per year.
    ap = d[d["approved"]].copy()
    flags["years"] = len(ap) > 0
    if len(ap):
        ap["year"] = ap["date"].dt.year.astype(int)
        y0, y1 = int(ap["year"].min()), int(ap["year"].max())
        last_date = ap["date"].max()
        partial = int(last_date.month) < 12
        first_shown = max(y0, y1 - YEARS_SHOWN + 1)
        by = ap.groupby("year").agg(n=("proj", "size"), tosa=("tosa", "sum"))
        xs, ns, ts, notes = [], [], [], []
        if first_shown > y0:
            old = by[by.index < first_shown]
            xs.append(f"עד {first_shown - 1}")
            ns.append(int(old["n"].sum()))
            ts.append(int(old["tosa"].sum()))
            notes.append(f"{y0}-{first_shown - 1}")
        for y in range(first_shown, y1 + 1):
            xs.append(str(y))
            ns.append(int(by["n"].get(y, 0)))
            ts.append(int(by["tosa"].get(y, 0)))
            notes.append(f"חלקית, עד {last_date.day}.{last_date.month}.{y}" if (y == y1 and partial) else "")
        charts["years"] = {"x": xs, "n": ns, "tosa": ts, "partial": partial}
        tables["years"] = [{"year": x, "n": _fmt(a), "tosa": _fmt(b), "note": nt}
                           for x, a, b, nt in zip(xs, ns, ts, notes)]
        full = by[(by.index < y1) | (not partial)]
        labels["years_lede"] = (
            f"{_fmt(len(ap))} מתחמים ({_pct(appr_share)}) נמצאים בתוכנית שנכנסה לתוקף, הראשונה ב-{y0}. "
            + (f"השנה האחרונה, {y1}, חלקית: הנתונים בה מגיעים עד {last_date.day}.{last_date.month}.{y1}." if partial else "")
        ).strip()
        labels["years_aria"] = (
            f"גרף עמודות וקו: מספר המתחמים שתוכניתם נכנסה לתוקף בכל שנה, ותוספת יחידות הדיור בהם, מ-{y0} עד {y1}."
        )
        # Trend rule over full years only.
        fy = [y for y in range(y0, y1 + 1) if not (y == y1 and partial)]
        if len(fy) >= 4:
            last = fy[-1]
            prev = fy[-4:-1]
            v_last = int(by["n"].get(last, 0))
            v_prev = sum(int(by["n"].get(y, 0)) for y in prev) / 3
            peak_y = int(full["n"].idxmax()) if len(full) else last
            if v_prev > 0:
                ch = v_last / v_prev - 1
                if ch >= 0.15:
                    word = f"עלייה של {_pct(ch)}"
                elif ch <= -0.15:
                    word = f"ירידה של {_pct(-ch)}"
                else:
                    word = "יציבות"
                txt = (f"ב-{last} נכנסו לתוקף תוכניות ל-{_fmt(v_last)} מתחמים, {word} לעומת ממוצע של "
                       f"{v_prev:.1f} בשנים {prev[0]}-{prev[-1]}.")
                if peak_y == last and v_last > 0:
                    txt += " זו השנה עם המספר הגבוה ביותר בשכבה."
                if partial:
                    txt += f" (שנת {y1} חלקית ואינה נכללת בהשוואה.)"
                insights.append({"id": "years", "text_he": txt})
    insights.append({"id": "approved", "text_he": (
        f"ל-{_fmt(n_appr)} מתוך {_fmt(n)} המתחמים ({_pct(appr_share)}) יש תאריך כניסה לתוקף של התוכנית; "
        f"ביתר {_fmt(n - n_appr)} התוכנית עדיין לא בתוקף או שהתאריך לא דווח."
    )})

    # Chart: approved vs not, per track.
    charts["appr_track"] = {
        "names": tracks,
        "yes": [int(tr.loc[t, "appr"]) for t in tracks],
        "no": [int(tr.loc[t, "n"] - tr.loc[t, "appr"]) for t in tracks],
    }
    labels["appr_aria"] = (
        f"גרף עמודות מוערמות: מתחמים עם תוכנית בתוקף ובלי, לפי מסלול הכרזה. "
        f"סך הכול {_fmt(n_appr)} מתחמים עם תוכנית בתוקף."
    )
    best_t = max(tracks, key=lambda t: (tr.loc[t, "appr"] / tr.loc[t, "n"], t))
    worst_t = min(tracks, key=lambda t: (tr.loc[t, "appr"] / tr.loc[t, "n"], t))
    labels["appr_lede"] = (
        f"שיעור המתחמים עם תוכנית בתוקף הגבוה ביותר הוא במסלול {best_t} ({_pct(tr.loc[best_t, 'appr'] / tr.loc[best_t, 'n'])}), "
        f"והנמוך ביותר במסלול {worst_t} ({_pct(tr.loc[worst_t, 'appr'] / tr.loc[worst_t, 'n'])})."
    )

    # Chart: compound size (proposed units) buckets.
    edges = [(0, 100), (101, 250), (251, 500), (501, 1000), (1001, 2000), (2001, None)]
    sz_names, sz_n = [], []
    for lo, hi in edges:
        m = (d["mutz"] >= lo) & ((d["mutz"] <= hi) if hi is not None else True)
        sz_names.append(_bucket_label(lo, hi))
        sz_n.append(int(m.sum()))
    med_mutz = float(d["mutz"].median())
    charts["size"] = {"names": sz_names, "n": sz_n}
    tables["size"] = [{"name": a, "n": _fmt(b), "share": _pct(b / n)} for a, b in zip(sz_names, sz_n)]
    big = d.sort_values(["mutz", "proj"], ascending=[False, True], kind="mergesort").iloc[0]
    labels["size_lede"] = (
        f"המתחם החציוני מתכנן {_fmt(med_mutz)} יחידות דיור. הגדול ביותר: {big['ShemMitcha']} ב{big['Yeshuv']}, "
        f"עם {_fmt(big['mutz'])} יחידות מוצעות."
    )
    labels["size_aria"] = (
        f"גרף עמודות: התפלגות המתחמים לפי מספר יחידות הדיור המוצעות. החציון: {_fmt(med_mutz)} יחידות."
    )
    insights.append({"id": "biggest", "text_he": (
        f"המתחם הגדול ביותר בשכבה הוא {big['ShemMitcha']} ב{big['Yeshuv']}: {_fmt(big['mutz'])} יחידות דיור מוצעות "
        f"במקום {_fmt(big['kaya'])} קיימות. המתחם החציוני מתכנן {_fmt(med_mutz)} יחידות."
    )})

    # Chart: density multiplier (proposed / existing) buckets.
    mk = d[d["kaya"] > 0].copy()
    mk["mult"] = mk["mutz"] / mk["kaya"]
    n_zero = n - len(mk)
    medges = [(0, 2), (2, 3), (3, 4), (4, 5), (5, 7), (7, None)]
    mnames, mn = [], []
    for lo, hi in medges:
        m = (mk["mult"] >= lo) & ((mk["mult"] < hi) if hi is not None else True)
        mnames.append(f"פי {lo} עד {hi}" if hi is not None else f"פי {lo} ומעלה")
        if lo == 0:
            mnames[-1] = f"עד פי {hi}"
        mn.append(int(m.sum()))
    flags["mult"] = len(mk) > 0
    if len(mk):
        med_mult = float(mk["mult"].median())
        charts["mult"] = {"names": mnames, "n": mn}
        tables["mult"] = [{"name": a, "n": _fmt(b), "share": _pct(b / len(mk))} for a, b in zip(mnames, mn)]
        labels["mult_lede"] = (
            f"מכפיל הציפוף (יחידות מוצעות חלקי קיימות) החציוני הוא פי {med_mult:.1f}."
            + (f" לא כולל {_fmt(n_zero)} מתחמים בלי יחידות דיור קיימות." if n_zero else "")
        )
        labels["mult_aria"] = (
            f"גרף עמודות: התפלגות המתחמים לפי מכפיל הציפוף. החציון: פי {med_mult:.1f}."
        )
        mode_i = max(range(len(mn)), key=lambda i: (mn[i], -i))
        insights.append({"id": "mult", "text_he": (
            f"מכפיל הציפוף החציוני במתחמים הוא פי {med_mult:.1f}; הטווח הנפוץ הוא {mnames[mode_i]} "
            f"({_fmt(mn[mode_i])} מתחמים, {_pct(mn[mode_i] / len(mk))})."
            + (f" החישוב לא כולל {_fmt(n_zero)} מתחמים בלי יחידות קיימות." if n_zero else "")
        )})

        # Chart: median multiplier per city (cities with enough compounds).
        cm = mk.groupby("Yeshuv").agg(n=("proj", "size"), med=("mult", "median")).reset_index()
        cm = cm[cm["n"] >= MIN_CITY_N]
        cm = cm.sort_values(["med", "Yeshuv"], ascending=[False, True], kind="mergesort").head(15)
        flags["mult_city"] = len(cm) >= 3
        if flags["mult_city"]:
            charts["mult_city"] = {"names": cm["Yeshuv"].tolist(),
                                   "med": [round(float(v), 2) for v in cm["med"]],
                                   "n": [int(v) for v in cm["n"]], "overall": round(med_mult, 2)}
            tables["mult_city"] = [{"name": r.Yeshuv, "med": f"{r.med:.1f}", "n": _fmt(r.n)} for r in cm.itertuples()]
            hi_c, lo_c = cm.iloc[0], cm.iloc[-1]
            labels["mult_city_lede"] = (
                f"ביישובים עם {MIN_CITY_N} מתחמים לפחות: המכפיל החציוני הגבוה ביותר ב{hi_c['Yeshuv']} (פי {hi_c['med']:.1f}), "
                f"והנמוך ביותר ב{lo_c['Yeshuv']} (פי {lo_c['med']:.1f})."
            )
            labels["mult_city_title"] = f"מכפיל ציפוף חציוני לפי יישוב (יישובים עם {MIN_CITY_N} מתחמים לפחות)"
            labels["mult_city_aria"] = (
                f"גרף עמודות: מכפיל הציפוף החציוני ב-{len(cm)} יישובים עם {MIN_CITY_N} מתחמים לפחות. "
                f"הגבוה: {hi_c['Yeshuv']}, פי {hi_c['med']:.1f}."
            )
            if hi_c["med"] / max(lo_c["med"], 1e-9) >= 1.5:
                insights.append({"id": "mult_city", "text_he": (
                    f"הציפוף משתנה מאוד בין יישובים: המכפיל החציוני ב{hi_c['Yeshuv']} הוא פי {hi_c['med']:.1f}, "
                    f"לעומת פי {lo_c['med']:.1f} ב{lo_c['Yeshuv']} (יישובים עם {MIN_CITY_N} מתחמים לפחות)."
                )})
    else:
        flags["mult_city"] = False

    # ── master plans ────────────────────────────────────────────────────
    flags["mp"] = n_mp > 0
    if n_mp:
        d_city_n = {}
        for c, v in zip(city["Yeshuv"], city["n"]):
            d_city_n[_city_key(c)] = d_city_n.get(_city_key(c), 0) + int(v)
        st = mp.groupby("status").size().reset_index(name="n")
        st = st.sort_values(["n", "status"], ascending=[False, True], kind="mergesort")
        charts["mp_status"] = [{"name": r.status, "value": int(r.n)} for r in st.itertuples()]
        tables["mp_status"] = [{"name": r.status, "n": _fmt(r.n), "share": _pct(r.n / n_mp)} for r in st.itertuples()]
        tables["mp"] = [
            {"city": r.Yeshuv, "name": r.ShemMitcha or EMPTY_LABEL, "status": r.status,
             "dunam": _fmt(r.area / 1000), "decl": _fmt(d_city_n.get(_city_key(r.Yeshuv), 0))}
            for r in mp.itertuples()
        ]
        s0 = st.iloc[0]
        labels["mp_lede"] = (
            f"{_fmt(n_mp)} תוכניות מתאר להתחדשות עירונית ב-{_fmt(mp_cities)} יישובים, על שטח כולל של "
            f"{_fmt(mp['area'].sum() / 1000)} דונם. הסטטוס הנפוץ: {s0['status']} ({_fmt(s0['n'])} תוכניות)."
        )
        labels["mp_aria"] = (
            f"גרף טבעת: תוכניות המתאר להתחדשות עירונית לפי סטטוס תכנון. הנפוץ: {s0['status']} עם {_fmt(s0['n'])} תוכניות."
        )
        no_decl = sorted({r.Yeshuv for r in mp.itertuples() if d_city_n.get(_city_key(r.Yeshuv), 0) == 0})
        mp_top = mp.groupby("Yeshuv").size().reset_index(name="n").sort_values(
            ["n", "Yeshuv"], ascending=[False, True], kind="mergesort")
        txt = (f"בשכבת תוכניות המתאר {_fmt(n_mp)} תוכניות ב-{_fmt(mp_cities)} יישובים; "
               f"{_fmt(s0['n'])} מהן ({_pct(s0['n'] / n_mp)}) בסטטוס {s0['status']}.")
        if int(mp_top.iloc[0]["n"]) >= 2:
            txt += f" הכי הרבה תוכניות: {mp_top.iloc[0]['Yeshuv']} ({_fmt(mp_top.iloc[0]['n'])})."
        insights.append({"id": "mp", "text_he": txt})
        if no_decl and len(no_decl) <= 6:
            insights.append({"id": "mp_nodecl", "text_he": (
                f"ב{', '.join(no_decl)} יש תוכנית מתאר להתחדשות עירונית, אבל אין אף מתחם מוכרז בשכבת המתחמים."
            )})

    # ── all-cities table ────────────────────────────────────────────────
    tables["all_cities"] = [
        {"name": r.Yeshuv, "n": _fmt(r.n), "kaya": _fmt(r.kaya), "mutz": _fmt(r.mutz), "appr": _fmt(r.appr)}
        for r in city.sort_values(["Yeshuv"], kind="mergesort").itertuples()
    ]
    labels["all_cities_summary"] = f"הצג את כל {_fmt(len(city))} היישובים"

    # ── map ─────────────────────────────────────────────────────────────
    pts = []
    city_names = sorted(d["Yeshuv"].unique())
    cidx = {c: i for i, c in enumerate(city_names)}
    tidx = {t: i for i, t in enumerate(tracks)}
    lats, lons = [], []
    for r in d.itertuples():
        c = _centroid(r.geoms)
        if c is None:
            continue
        lon, lat = c
        if not (29 < lat < 34 and 34 < lon < 36.5):
            continue
        lats.append(lat)
        lons.append(lon)
        pts.append([round(lat, 5), round(lon, 5), r.ShemMitcha or EMPTY_LABEL, cidx[r.Yeshuv],
                    tidx[r.track], r.maslul, int(r.kaya), int(r.mutz), r.plan_name,
                    r.date.strftime("%d.%m.%Y") if r.approved else "",
                    round(r.area / 1000, 1)])
    polys = []
    for r in mp.itertuples():
        for g in r.geoms:
            if not g or g.get("type") not in ("Polygon", "MultiPolygon"):
                continue
            polys.append({"g": _round_geom(g), "n": r.ShemMitcha or EMPTY_LABEL, "c": r.Yeshuv, "s": r.status})
            for ring in _outer_rings(g):
                for p in ring:
                    lons.append(p[0])
                    lats.append(p[1])
    poly_chunks, cur, size = [], [], 0
    for p in polys:
        ln = len(json.dumps(p, ensure_ascii=False))
        if cur and size + ln > POLY_CHUNK_CHARS:
            poly_chunks.append(cur)
            cur, size = [], 0
        cur.append(p)
        size += ln
    if cur:
        poly_chunks.append(cur)
    flags["map"] = len(pts) > 0
    if pts:
        charts["map"] = {
            "chunks": [pts[i:i + MAP_CHUNK] for i in range(0, len(pts), MAP_CHUNK)],
            "polys": poly_chunks,
            "cities": city_names,
            "tracks": tracks,
            "bounds": [[round(min(lats), 4), round(min(lons), 4)], [round(max(lats), 4), round(max(lons), 4)]],
        }
        labels["map_lede"] = (
            f"{_fmt(len(pts))} מתחמים מוכרזים מסומנים לפי מסלול הכרזה"
            + (f", ועליהם {_fmt(n_mp)} תחומי תוכניות מתאר להתחדשות עירונית" if n_mp else "")
            + ". לחיצה על מתחם מציגה את שמו, היישוב, מספר התוכנית ויחידות הדיור."
        )
        labels["map_aria"] = (
            f"מפה אינטראקטיבית של {_fmt(len(pts))} מתחמי התחדשות עירונית ב-{_fmt(n_cities)} יישובים. "
            "גרסה נגישה: טבלת היישובים בהמשך העמוד."
        )

    dup_note = n_raw - n
    mp_dup = len(frames["masterplans"]) - n_mp
    labels["lede"] = (
        f"השכבה כוללת {_fmt(n)} מתחמי התחדשות עירונית ב-{_fmt(n_cities)} יישובים, ובהם {_fmt(sum_mutz)} יחידות דיור מוצעות "
        f"במקום {_fmt(sum_kaya)} קיימות"
        + (f", לצד {_fmt(n_mp)} תוכניות מתאר להתחדשות עירונית ב-{_fmt(mp_cities)} יישובים" if n_mp else "")
        + "."
    )
    dup_parts = []
    if dup_note > 0:
        dup_parts.append(f"{_fmt(dup_note)} רשומות כפולות בשכבת המתחמים")
    if mp_dup > 0:
        dup_parts.append(f"{_fmt(mp_dup)} בשכבת תוכניות המתאר")
    labels["dup_note"] = (
        "רשומות שחוזרות על אותו מספר פרויקט אוחדו לרשומה אחת: " + " ו-".join(dup_parts) + "."
        if dup_parts else "")

    temporal = None
    if len(ap):
        temporal = f"{int(ap['date'].dt.year.min())}/{int(ap['date'].dt.year.max())}"
    summary = (
        f"מפת מתחמי התחדשות עירונית (פינוי בינוי) לפי יישוב: {_fmt(n)} מתחמים ב-{_fmt(n_cities)} יישובים, "
        f"{_fmt(sum_mutz)} יחידות דיור מוצעות, ו-{_fmt(n_mp)} תוכניות מתאר."
    )
    if len(summary) > 155:
        summary = (f"מפת מתחמי התחדשות עירונית לפי יישוב: {_fmt(n)} מתחמים ב-{_fmt(n_cities)} יישובים, "
                   f"{_fmt(sum_mutz)} יחידות דיור מוצעות.")

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "map",
            "temporal_coverage": temporal,
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "kpi_order": kpi_order,
        "charts": charts,
        "tables": tables,
        "labels": labels,
        "flags": flags,
        "insights": insights,
    }
