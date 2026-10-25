"""רופאים וטרינריים רשותיים — which municipal vet serves which settlement.

One row per (settlement, authority): settlement code + name, the local
authority (regional council / town association / local council / city), the
municipal vet (a licensed official — named on the page), the vet's licence
number, office contact details, and the Ministry's regional veterinary bureau
(לשכה). The whole table is republished on each update, so the page is a
snapshot: workload per vet, concentration, bureaus, authority types.

Not on the page: licence numbers (individual registration ids; also
inconsistent upstream — several names share one number), office emails and
phones (contact details), fax (always empty), bureau URL (constant per bureau).
"""
import pandas as pd

TOP_VETS = 15
TOP_AUTH = 15
UNASSIGNED = "ללא לשכה"
# (label, lo, hi) settlement-count buckets for the workload histogram.
BUCKETS = [("יישוב אחד", 1, 1), ("2–5", 2, 5), ("6–10", 6, 10), ("11–25", 11, 25),
           ("26–50", 26, 50), ("51–100", 51, 100), ("מעל 100", 101, None)]
TYPE_ORDER = ["מועצה אזורית", "איגוד ערים", "מועצה מקומית", "עירייה", "אחר"]
MILESTONES = [5, 10, 20, 50]


def _int(n):
    return f"{int(n):,}"


def _pct(x):
    return f"{x * 100:.1f}%"


def _auth_type(name):
    if name.startswith("מועצה אזורית"):
        return "מועצה אזורית"
    if name.startswith("איגוד ערים"):
        return "איגוד ערים"
    if name.startswith("מועצה מקומית"):
        return "מועצה מקומית"
    if name.startswith("עירי"):
        return "עירייה"
    return "אחר"


def _clean_auth(name):
    """Drop the doubled type prefix the export carries ('עירית עיריית נתניה')."""
    if name.startswith("מועצה אזורית מ. א. "):
        return "מועצה אזורית " + name[len("מועצה אזורית מ. א. "):]
    for p in ("עירית", "איגוד ערים"):
        rest = name[len(p) + 1:]
        if name.startswith(p + " ") and (rest.startswith("עירי") or rest.startswith(p)):
            return rest
    return name


def _prepare(raw):
    df = pd.DataFrame({
        "code": raw["סמל_ישוב"].str.strip(),
        "place": raw["ישוב"].str.strip(),
        "auth": raw["אזור"].str.strip(),
        "vet": raw["רופא"].str.strip(),
        "bureau": raw["לשכה"].str.strip(),
    })
    df["key"] = df["code"].where(df["code"] != "", "n:" + df["place"])
    df["type"] = df["auth"].map(_auth_type)
    df["auth_he"] = df["auth"].map(_clean_auth)
    df["bureau_he"] = df["bureau"].where(df["bureau"] != "", UNASSIGNED)
    return df


def _ranked(s):
    """Series -> sorted desc by value, ties by index name (total order)."""
    return s.sort_index().sort_values(ascending=False, kind="stable")


def insight_concentration(per_vet):
    n = len(per_vet)
    if n < 20:
        return None
    tot = per_vet.sum()
    top = per_vet.head(10).sum() / tot
    if top < 0.25:
        return None
    half = int((per_vet.cumsum() < tot / 2).sum()) + 1
    return (f"העומס מרוכז: 10 הרופאים המובילים אחראים ל-{_pct(top)} מהיישובים, ומחצית מהיישובים "
            f"מכוסים על ידי {_int(half)} רופאים בלבד מתוך {_int(n)}.")


def insight_single(df, per_vet):
    singles = per_vet[per_vet == 1].index
    if len(singles) / len(per_vet) < 0.2:
        return None
    sub = df[df["vet"].isin(singles)].drop_duplicates("vet")
    urban = int(sub["type"].isin(["עירייה", "מועצה מקומית"]).sum())
    who = ("כולם" if urban == len(sub) else f"{_int(urban)} מהם") + " בעירייה או במועצה מקומית"
    return (f"{_int(len(singles))} רופאים ({_pct(len(singles) / len(per_vet))}) משרתים יישוב אחד בלבד — "
            f"{who}; חציון היישובים לרופא הוא {_int(per_vet.median())}.")


def insight_leader(df, per_vet):
    if len(per_vet) < 2:
        return None
    a, b = per_vet.iloc[0], per_vet.iloc[1]
    if a < b * 1.25:
        return None
    name = per_vet.index[0]
    sub = df[df["vet"] == name]
    na, nb = sub["auth"].nunique(), sub["bureau"].replace("", pd.NA).dropna().nunique()
    where = f"ב-{_int(na)} רשויות" if na > 1 else "ברשות אחת"
    bur = f" ובתחומי {_int(nb)} לשכות" if nb > 1 else ""
    return (f"העומס הגבוה ביותר: {_int(a)} יישובים {where}{bur} באחריות {name}, "
            f"לעומת {_int(b)} אצל {per_vet.index[1]} במקום השני.")


def insight_bureau(bt):
    named = [r for r in bt if r["name"] != UNASSIGNED and r["vets"]]
    if len(named) < 3:
        return None
    big = max(named, key=lambda r: (r["places"], r["name"]))
    hi = max(named, key=lambda r: (r["ratio"], r["name"]))
    lo = min(named, key=lambda r: (r["ratio"], r["name"]))
    if hi["ratio"] < lo["ratio"] * 1.5:
        return None
    return (f"לשכת {big['name']} מכסה את מספר היישובים הגדול ביותר ({_int(big['places'])}). "
            f"העומס הממוצע הגבוה ביותר בלשכת {hi['name']} — {hi['ratio']:.1f} יישובים לרופא, "
            f"לעומת {lo['ratio']:.1f} בלשכת {lo['name']}.")


def insight_multi(df):
    named = df[df["vet"] != ""]
    per_auth = named.groupby("auth")["vet"].nunique()
    n_auth = df["auth"].nunique()
    multi = named.groupby("vet")["auth"].nunique()
    m = int((multi > 1).sum())
    if m < 3:
        return None
    lead = (f"בכל אחת מ-{_int(n_auth)} הרשויות רשום רופא וטרינרי רשותי אחד לכל היותר. "
            if int(per_auth.max()) == 1 else "")
    return (f"{lead}{_int(m)} רופאים ({_pct(m / len(multi))}) משרתים יותר מרשות אחת; "
            f"הרופא המשרת הכי הרבה רשויות אחראי על {_int(multi.max())}.")


def insight_types(tt):
    rc = next((r for r in tt if r["name"] == "מועצה אזורית"), None)
    if not rc:
        return None
    tp = sum(r["places"] for r in tt)
    ta = sum(r["auths"] for r in tt)
    sp, sa = rc["places"] / tp, rc["auths"] / ta
    if sp - sa < 0.2:
        return None
    urb = [r for r in tt if r["name"] in ("עירייה", "מועצה מקומית")]
    ua, up = sum(r["auths"] for r in urb), sum(r["places"] for r in urb)
    tail = (f", לעומת {up / ua:.1f} בעיריות ובמועצות המקומיות" if ua else "")
    return (f"המועצות האזוריות הן {_pct(sa)} מהרשויות במאגר אך כוללות {_pct(sp)} מהיישובים — "
            f"בממוצע {rc['places'] / rc['auths']:.1f} יישובים למועצה{tail}.")


def insight_gaps(df):
    nv = int(df.loc[df["vet"] == "", "key"].nunique())
    nb = int(df.loc[df["bureau"] == "", "key"].nunique())
    if not nv and not nb:
        return None
    parts = []
    if nv:
        parts.append(f"ל-{_int(nv)} יישובים לא רשום רופא וטרינרי רשותי")
    if nb:
        parts.append(f"{_int(nb)} יישובים אינם משויכים ללשכה וטרינרית")
    return "פערים ברישום: " + "; ".join(parts) + "."


def compute(frames):
    df = _prepare(frames["vets"])
    named = df[df["vet"] != ""]

    n_places = int(df["key"].nunique())
    n_auth = int(df["auth"].nunique())
    per_vet = _ranked(named.groupby("vet")["key"].nunique())
    n_vets = len(per_vet)
    bureaus = sorted(b for b in df["bureau"].unique() if b)

    # workload histogram
    load = {"names": [], "values": []}
    for label, lo, hi in BUCKETS:
        m = (per_vet >= lo) if hi is None else ((per_vet >= lo) & (per_vet <= hi))
        load["names"].append(label)
        load["values"].append(int(m.sum()))

    # top vets
    top = per_vet.head(TOP_VETS)
    auths_of = named.groupby("vet")["auth"].nunique()
    top_vets = {"names": list(top.index), "values": [int(v) for v in top.values],
                "auths": [int(auths_of[v]) for v in top.index]}

    # concentration curve
    cum = (per_vet.cumsum() / per_vet.sum() * 100).round(1)
    conc = {"x": [str(i) for i in range(1, n_vets + 1)], "y": [float(v) for v in cum.values]}
    conc_rows = [{"name": f"{k} הרופאים המובילים", "pct": f"{cum.iloc[k - 1]:.1f}%"}
                 for k in MILESTONES if k < n_vets]

    # bureaus × type
    types = [t for t in TYPE_ORDER if (df["type"] == t).any()]
    b_order = bureaus + ([UNASSIGNED] if (df["bureau"] == "").any() else [])
    bp = df.groupby(["bureau_he", "type"])["key"].nunique()
    btable = []
    for b in b_order:
        sub = df[df["bureau_he"] == b]
        v = sub.loc[sub["vet"] != "", "vet"].nunique()
        p = sub["key"].nunique()
        btable.append({"name": b, "places": int(p), "auths": int(sub["auth"].nunique()), "vets": int(v),
                       "ratio": round(p / v, 1) if v else 0.0})
    btable.sort(key=lambda r: (r["name"] == UNASSIGNED, -r["places"], r["name"]))
    btype_sorted = [r["name"] for r in btable]
    btype = {"names": btype_sorted,
             "series": [{"name": t, "data": [int(bp.get((b, t), 0)) for b in btype_sorted]} for t in types]}

    # authority types
    ttable = []
    for t in types:
        sub = df[df["type"] == t]
        ttable.append({"name": t, "auths": int(sub["auth"].nunique()), "places": int(sub["key"].nunique())})
    tchart = {"names": [r["name"] for r in ttable],
              "auths": [r["auths"] for r in ttable], "places": [r["places"] for r in ttable]}

    # top authorities
    pa = _ranked(df.groupby("auth_he")["key"].nunique())
    auth_top = {"names": list(pa.head(TOP_AUTH).index), "values": [int(v) for v in pa.head(TOP_AUTH).values]}

    # vets by number of authorities served
    ac = named.groupby("vet")["auth"].nunique().value_counts().sort_index()
    multi = {"names": [f"{k} רשויות" if k > 1 else "רשות אחת" for k in ac.index],
             "values": [int(v) for v in ac.values]}

    rules = [
        ("concentration", insight_concentration(per_vet)),
        ("leader", insight_leader(df, per_vet)),
        ("single", insight_single(df, per_vet)),
        ("bureau", insight_bureau(btable)),
        ("multi", insight_multi(df)),
        ("types", insight_types(ttable)),
        ("gaps", insight_gaps(df)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    one_per_auth = int(named.groupby("auth")["vet"].nunique().max()) == 1
    gap_places = int(df.loc[(df["vet"] == "") | (df["bureau"] == ""), "key"].nunique())
    median = float(per_vet.median())
    top10 = float(per_vet.head(10).sum() / per_vet.sum())
    lead_b = btable[0]

    return {
        "agent_data": {
            "summary_he": (f"שיבוץ הרופאים הווטרינריים הרשותיים ליישובים: {_int(n_vets)} רופאים מכסים "
                           f"{_int(n_places)} יישובים ב-{_int(n_auth)} רשויות מקומיות, תחת "
                           f"{_int(len(bureaus))} לשכות וטרינריות של משרד החקלאות."),
            "dataset_kind": "registry",
            "suggested_tags": ["וטרינריה", "רופאים וטרינריים", "רשויות מקומיות", "בעלי חיים"],
            "related_ids": ["28954732-da33-48d0-b22c-1c0c279aadca", "72662d34-ce69-4990-8504-ee0860529e7d",
                            "83cdc927-2bcf-4db2-b9d6-9f674cd52222", "b4c32de1-627c-4b93-8d20-e58f6d44f733",
                            "8379fa95-2b82-4f03-9a9b-650178de1ea8"],
            "spatial_coverage": "ישראל",
        },
        "kpis": {
            "vets": {"value": n_vets, "display": _int(n_vets), "tone": "brand"},
            "places": {"value": n_places, "display": _int(n_places), "tone": "brand"},
            "auths": {"value": n_auth, "display": _int(n_auth), "tone": "brand"},
            "bureaus": {"value": len(bureaus), "display": _int(len(bureaus)), "tone": "brand"},
            # Share of settlements held by the ten busiest vets: ≥40% reads as a
            # concentration worth flagging.
            "top10": {"value": round(top10 * 100, 1), "display": _pct(top10),
                      "tone": "warn" if top10 >= 0.4 else "info"},
            "gaps": {"value": gap_places, "display": _int(gap_places),
                     "tone": "warn" if gap_places else "ok"},
        },
        "charts": {
            "load": load,
            "top_vets": top_vets,
            "conc": conc,
            "btype": btype,
            "types": tchart,
            "auth_top": auth_top,
            "multi": multi,
        },
        "tables": {"bureaus": btable, "types": ttable, "conc": conc_rows},
        "insights": insights,
        "labels": {
            "lede": (f"{_int(n_vets)} רופאים וטרינריים רשותיים משובצים ל-{_int(n_places)} יישובים ב-"
                     f"{_int(n_auth)} רשויות מקומיות. חציון העומס הוא {_int(median)} יישובים לרופא, "
                     f"ו-10 הרופאים המובילים מכסים {_pct(top10)} מהיישובים. לשכת {lead_b['name']} "
                     f"היא הגדולה ביותר."),
            "top10_kpi": "מהיישובים בטיפול 10 הרופאים המובילים",
            "load_aria": (f"תרשים עמודות: {_int(n_vets)} הרופאים לפי מספר היישובים שבאחריותם; "
                          f"{_int(load['values'][0])} משרתים יישוב אחד."),
            "top_aria": (f"תרשים עמודות: {TOP_VETS} הרופאים עם מספר היישובים הגבוה ביותר; "
                         f"בראש {top_vets['names'][0]} עם {_int(top_vets['values'][0])}."),
            "top_note": f"{TOP_VETS} הרופאים עם מספר היישובים הגבוה ביותר, ומספר הרשויות שכל אחד משרת.",
            "conc_aria": (f"גרף קו: אחוז מצטבר של היישובים לפי הרופאים מהעמוס ביותר; "
                          f"10 הראשונים מכסים {_pct(top10)}."),
            "btype_aria": (f"תרשים עמודות מוערמות: יישובים לפי לשכה וטרינרית וסוג רשות; "
                           f"לשכת {lead_b['name']} מובילה עם {_int(lead_b['places'])}."),
            "types_aria": "תרשים עמודות: רשויות ויישובים לפי סוג הרשות המקומית.",
            "auth_aria": (f"תרשים עמודות: {TOP_AUTH} הרשויות עם מספר היישובים הגבוה ביותר; "
                          f"בראש {auth_top['names'][0]} עם {_int(auth_top['values'][0])}."),
            "auth_note": (f"{TOP_AUTH} הרשויות עם מספר היישובים הרב ביותר."
                          + (" בכל רשות — רופא רשותי אחד." if one_per_auth else "")),
            "multi_aria": "תרשים עמודות: הרופאים לפי מספר הרשויות המקומיות שהם משרתים.",
        },
    }
