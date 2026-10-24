"""אתרי בנייה פעילים — the current register of active construction sites.

A snapshot, not a log: one row per active site (work_id), no dates. Every
refresh describes the register as it stands, so insights compare places,
contractors and enforcement, never "change since last time" (compute() is
pure and never sees an older version).

Executors are grouped by `executor_id` (names vary in spelling). Rankings
name only executors identifiable as corporate (בע"מ / עמותה / Ltd …);
`foreman_name` holds private individuals and is never used.
"""
import re

import pandas as pd

TYPES = ["מגורים", "ציבורי", "תעשייה", "מסחר"]
UNSPECIFIED = "לא צוין"
CORPORATE_RE = re.compile(
    r'בע"מ|בע״מ|בעמ|ע"ר|ע״ר|עמותה|\bLTD\b|Ltd|לימיטד|אל טי די|שותפות|חברה'
)
TOP_N = 15
MIN_CITY_SITES = 100   # cities compared on rates need at least this many sites
ORDER_BUCKETS = ["0", "1", "2", "3", "4+"]


def _int(n):
    return f"{int(round(n)):,}"


def _pct(x):
    return f"{x * 100:.0f}%"


def ils(v):
    v = float(v)
    if v >= 1_000_000:
        return f"{v / 1_000_000:,.1f} מיליון ₪"
    return f"{v:,.0f} ₪"


def _types(raw):
    parts = {p.strip() for p in re.split(r"[-,]", raw) if p.strip()}
    return sorted(parts) or [UNSPECIFIED]


def _num(s):
    return pd.to_numeric(s.str.replace(",", "").str.strip(), errors="coerce").fillna(0)


def _prepare(df):
    out = pd.DataFrame({
        "work": df["work_id"].str.strip(),
        "city": df["city_name"].str.strip().map(lambda c: re.sub(r"\s*-\s*", " - ", c)),
        "exec_id": df["executor_id"].str.strip(),
        "exec_name": df["executor_name"].str.strip(),
        "cranes": _num(df["has_cranes"]) > 0,
        "orders": _num(df["safety_warrents"]).astype(int),
        "sanctions": _num(df["sanctions"]).astype(int),
        "sanctions_sum": _num(df["sanctions_sum"]),
        "types": df["build_types"].fillna("").map(_types),
    })
    out = out[out["work"] != ""].drop_duplicates("work")
    return out.sort_values(list(out.columns.drop("types")), kind="stable").reset_index(drop=True)


def _top(series, n=TOP_N):
    return series.sort_index().sort_values(ascending=False, kind="stable").head(n)


def _executor_names(df):
    """One display name per executor_id: its most frequent spelling,
    ties broken alphabetically."""
    counts = df[df["exec_id"] != ""].groupby(["exec_id", "exec_name"]).size().reset_index(name="n")
    counts = counts.sort_values(["exec_id", "n", "exec_name"], ascending=[True, False, True])
    return counts.drop_duplicates("exec_id").set_index("exec_id")["exec_name"]


def insight_city(df, cities):
    name, n = cities.index[0], cities.iloc[0]
    share = n / len(df)
    rest = ", ".join(f"{c} ({_int(v)})" for c, v in cities.iloc[1:3].items())
    return (f"{name} מובילה עם {_int(n)} אתרי בנייה פעילים ({_pct(share)} מהאתרים)"
            + (f", ואחריה {rest}." if rest else "."))


def insight_orders(df):
    with_order = int((df["orders"] > 0).sum())
    if with_order == 0:
        return "אף אחד מאתרי הבנייה הפעילים לא קיבל צו בטיחות."
    many = int((df["orders"] >= 3).sum())
    return (f"{_int(with_order)} מהאתרים הפעילים ({_pct(with_order / len(df))}) קיבלו לפחות "
            f"צו בטיחות אחד; {_int(many)} אתרים קיבלו 3 צווים או יותר.")


def insight_cranes(df):
    n = int(df["cranes"].sum())
    if n == 0:
        return None
    top = _top(df.loc[df["cranes"], "city"].value_counts(), 1)
    return (f"ב-{_int(n)} אתרים ({_pct(n / len(df))}) פועלים עגורנים — הכי הרבה ב{top.index[0]} "
            f"({_int(top.iloc[0])} אתרים).")


def insight_sanctions(df):
    sites = int((df["sanctions"] > 0).sum())
    if sites == 0:
        return None
    return (f"על {_int(sites)} אתרים הוטלו עיצומים כספיים, בסך כולל של "
            f"{ils(df['sanctions_sum'].sum())}.")


def insight_concentration(df, names):
    by = df[df["exec_id"] != ""].groupby("exec_id").size()
    if by.empty:
        return None
    n_exec = by.size
    top10 = _top(by, 10).sum()
    lead_id = _top(by, 1).index[0]
    lead = names.get(lead_id, "")
    lead_txt = (f"; הגדול שבהם, {lead}, מבצע {_int(by[lead_id])} אתרים"
                if CORPORATE_RE.search(lead) else "")
    return (f"{_int(n_exec)} מבצעי בנייה מפעילים את האתרים; עשרת הגדולים מחזיקים "
            f"{_pct(top10 / len(df))} מהאתרים{lead_txt}.")


def insight_city_rate(rates):
    if rates.empty:
        return None
    hi_c, hi = rates.index[0], rates.iloc[0]
    lo_c, lo = rates.index[-1], rates.iloc[-1]
    if hi - lo < 0.05:
        return None
    return (f"בין היישובים עם {MIN_CITY_SITES} אתרים פעילים לפחות, שיעור האתרים שקיבלו צו בטיחות "
            f"הגבוה ביותר ב{hi_c} ({_pct(hi)}) והנמוך ביותר ב{lo_c} ({_pct(lo)}).")


def insight_types(type_counts, n_sites):
    spec = type_counts.drop(UNSPECIFIED, errors="ignore")
    if spec.empty:
        return None
    unspec = int(type_counts.get(UNSPECIFIED, 0))
    total_spec = n_sites - unspec
    if total_spec < 50:
        return None
    return (f"מבין {_int(total_spec)} האתרים שסוג הבנייה בהם צוין, {spec.index[0]} הוא הסוג הנפוץ "
            f"({_pct(spec.iloc[0] / total_spec)}); ב-{_pct(unspec / n_sites)} מהאתרים הסוג לא צוין.")


def compute(frames):
    df = _prepare(frames["sites"])
    names = _executor_names(df)

    cities = _top(df.loc[df["city"] != "", "city"].value_counts())
    type_counts = _top(df["types"].explode().value_counts(), 20)

    buckets = df["orders"].clip(upper=4).map(lambda v: ORDER_BUCKETS[int(v)])
    order_dist = buckets.value_counts().reindex(ORDER_BUCKETS, fill_value=0)

    big = df.groupby("city").filter(lambda g: len(g) >= MIN_CITY_SITES and g.name != "")
    rates = _top(big.groupby("city")["orders"].apply(lambda s: (s > 0).mean()), 1000)
    rates_chart = rates.head(TOP_N)

    ex = df[df["exec_id"] != ""].groupby("exec_id").agg(
        sites=("work", "size"), orders=("orders", "sum"), cranes=("cranes", "sum"))
    ex["name"] = names.reindex(ex.index).fillna("")
    ex = ex[ex["name"].str.contains(CORPORATE_RE)]
    ex = ex.sort_values(["sites", "name"], ascending=[False, True], kind="stable").head(12)
    executors = {"names": list(ex["name"]), "sites": [int(v) for v in ex["sites"]],
                 "orders": [int(v) for v in ex["orders"]]}

    cranes = _top(df.loc[df["cranes"] & (df["city"] != ""), "city"].value_counts(), 10)

    rules = [
        ("city", insight_city(df, cities)),
        ("orders", insight_orders(df)),
        ("city_rate", insight_city_rate(rates)),
        ("cranes", insight_cranes(df)),
        ("sanctions", insight_sanctions(df)),
        ("concentration", insight_concentration(df, names)),
        ("types", insight_types(type_counts, len(df))),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    n = len(df)
    with_orders = int((df["orders"] > 0).sum())
    kpis = {
        "sites": {"value": n, "display": _int(n)},
        "cities": {"value": int(df.loc[df["city"] != "", "city"].nunique()),
                   "display": _int(df.loc[df["city"] != "", "city"].nunique())},
        "cranes": {"value": int(df["cranes"].sum()), "display": _int(df["cranes"].sum())},
        "with_orders": {"value": with_orders, "display": _pct(with_orders / n) if n else "—"},
    }

    order_table = [{"bucket": b, "n": _int(v)} for b, v in order_dist.items()]
    labels = {
        "lede": (f"{_int(n)} אתרי בנייה פעילים שעליהם התקבלה הודעה על פעולות בנייה, "
                 f"ב-{kpis['cities']['display']} יישובים. המאגר מתאר את המצב הנוכחי ומתעדכן "
                 f"כשאתרים נפתחים ונסגרים."),
        "cities_aria": f"תרשים עמודות אופקי: {len(cities)} היישובים עם מספר אתרי הבנייה הפעילים הגבוה ביותר.",
        "types_aria": "תרשים עמודות: אתרי בנייה לפי סוג הבנייה.",
        "types_note": "אתר עם כמה סוגי בנייה נספר בכל אחד מהם.",
        "orders_aria": "תרשים עמודות: מספר האתרים לפי מספר צווי הבטיחות שקיבלו.",
        "rates_aria": (f"תרשים עמודות אופקי: שיעור האתרים שקיבלו צו בטיחות, ביישובים עם "
                       f"{MIN_CITY_SITES} אתרים לפחות."),
        "rates_note": f"יישובים עם {MIN_CITY_SITES} אתרים פעילים לפחות, מהשיעור הגבוה לנמוך.",
        "exec_aria": f"תרשים עמודות אופקי: {len(executors['names'])} החברות עם מספר האתרים הפעילים הגבוה ביותר.",
        "exec_note": ("חברות ותאגידים בלבד, לפי מספר האתרים הפעילים, לצד מספר צווי הבטיחות "
                      "באתרים אלה. מבצעים שהם אנשים פרטיים אינם מדורגים."),
        "cranes_aria": f"תרשים עמודות אופקי: {len(cranes)} היישובים עם מספר האתרים עם עגורנים הגבוה ביותר.",
        "orders_caption": "מספר האתרים לפי מספר צווי הבטיחות שקיבלו.",
    }

    return {
        "agent_data": {
            "summary_he": (f"{_int(n)} אתרי בנייה פעילים בישראל — לפי יישוב, מבצע, סוג בנייה, "
                           f"עגורנים וצווי בטיחות."),
            "dataset_kind": "registry",
            "suggested_tags": ["אתרי בנייה", "בטיחות בעבודה", "בנייה", "עגורנים", "צווי בטיחות"],
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": {
            "cities": {"names": list(cities.index), "values": [int(v) for v in cities]},
            "types": {"names": list(type_counts.index), "values": [int(v) for v in type_counts]},
            "orders": {"names": ORDER_BUCKETS, "values": [int(v) for v in order_dist]},
            "rates": {"names": list(rates_chart.index),
                      "values": [round(float(v) * 100, 1) for v in rates_chart]},
            "executors": executors,
            "cranes": {"names": list(cranes.index), "values": [int(v) for v in cranes]},
        },
        "tables": {"orders": order_table},
        "insights": insights,
        "labels": labels,
    }
