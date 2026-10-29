"""מאגר האסדרה — the unified regulation registry (רשות האסדרה).

One row per legislative item (primary law or secondary instrument). The file
is a periodically re-issued snapshot, so every count below is recomputed from
whatever the current snapshot holds. Data quirks handled here:

  * placeholder "42" (an export artefact) in office/tags/URL columns and a few
    fully blank rows — treated as missing, never as a category;
  * multi-office items ("משרד א; משרד ב") — split, each office credited;
  * semicolon-separated topic tags — split, each tag credited;
  * the enactment year is read from the item's name (",התשפ"ג-2023" /
    ", 1940"), which covers ~98% of rows; publication_date covers ~40%.

Insight rules each return a sentence or None when their premise fails.
"""
import re

import pandas as pd

PRIMARY = "חקיקה ראשית"
SECONDARY = "חקיקה משנית"
UNSPEC = "לא צוין"
OTHER = "אחר"

# Instrument form from the first word of the item name. Ordered; first match
# wins. Unknown forms fall into "אחר".
FORMS = [
    (("חוק-יסוד", "חוק יסוד"), "חוק יסוד"),
    (("חוק", "החוק"), "חוק"),
    (("תקנות", "תקנה"), "תקנות"),
    (("צו",), "צו"),
    (("אכרזת", "אכרזות", "אכרזה", "הכרזת", "הכרזה"), "אכרזה"),
    (("הודעת", "הודעה", "הודעות"), "הודעה"),
    (("כללי", "כללים"), "כללים"),
    (("פקודת", "פקודה"), "פקודה"),
    (("תקנון",), "תקנון"),
    (("הוראות", "הוראת"), "הוראות"),
    (("תקציב",), "תקציב"),
]

_YEAR_RE = re.compile(r"(?<!\d)(1[89]\d\d|20\d\d)(?!\d)")
_DATE_FMT = "%Y-%m-%d %H:%M:%S"


def _int(n):
    return f"{int(n):,}"


def _pct(x, d=1):
    return f"{x * 100:.{d}f}%"


def _is_missing(s):
    s = s.strip()
    return s == "" or s.isdigit()


def _clean_ws(s):
    return re.sub(r"\s+", " ", s).strip()


def _form(name):
    first = name.split(" ")[0] if name else ""
    for prefixes, label in FORMS:
        for p in prefixes:
            if first == p or first.startswith(p + "-") or (p.endswith("יסוד") and name.startswith(p)):
                return label
    return OTHER


def _year(name):
    m = _YEAR_RE.findall(name)
    return int(m[-1]) if m else None


def _split_list(s):
    out = []
    for part in s.split(";"):
        p = _clean_ws(part)
        if p and not p.isdigit() and p not in out:
            out.append(p)
    return out


def _ranked(counts):
    """Series of counts -> sorted by count desc, name asc (total order)."""
    return counts.sort_index().sort_values(ascending=False, kind="stable")


def _prepare(df):
    df = df.copy()
    df["name"] = df["legislation_name"].map(_clean_ws)
    df = df[df["name"] != ""].copy()
    lt = df["legislation_type"].map(_clean_ws)
    df["ltype"] = lt.where(lt.isin([PRIMARY, SECONDARY]), UNSPEC)
    reg = df["is_regulation"].map(_clean_ws)
    df["reg"] = reg.map({"כן": "כן", "לא": "לא"}).fillna(UNSPEC)
    df["offices"] = df["office_name"].map(
        lambda s: [] if _is_missing(s) else _split_list(s))
    df["tag_list"] = df["tags"].map(_split_list)
    auth = df["primary_authorizing_legislation"].map(_clean_ws)
    df["auth"] = auth.where(~auth.map(_is_missing), "")
    df["form"] = df["name"].map(_form)
    df["year"] = df["name"].map(_year)
    df["pub"] = pd.to_datetime(df["publication_date"].str.strip(), errors="coerce", format=_DATE_FMT)
    df["upd"] = pd.to_datetime(df["last_update"].str.strip(), errors="coerce", format=_DATE_FMT)
    df["has_wiki"] = df["wikiurl"].str.contains("href=", regex=False)
    df["has_knesset"] = df["knesseturl"].str.contains("href=", regex=False)
    return df


def _type_split(sub):
    return [int((sub["ltype"] == PRIMARY).sum()), int((sub["ltype"] == SECONDARY).sum())]


# ── insight rules ─────────────────────────────────────────────────────────

def insight_regulatory(n_reg, n_known):
    if n_known == 0:
        return None
    share = n_reg / n_known
    word = "רובם המכריע" if share >= 0.75 else ("רובם" if share > 0.5 else "מיעוטם")
    return (f"{word} של הפריטים במאגר מסווגים כאסדרה (רגולציה): {_int(n_reg)} "
            f"מתוך {_int(n_known)} פריטים שסווגו, {_pct(share)}.")


def insight_top_office(office_counts, n_with_office):
    if len(office_counts) < 2 or n_with_office == 0:
        return None
    (n1, v1), (n2, v2) = list(office_counts.items())[:2]
    s1 = v1 / n_with_office
    if s1 < 0.15:
        return None
    s12 = (v1 + v2) / n_with_office
    return (f"{n1} אחראי ל-{_int(v1)} פריטים ({_pct(s1)} מהפריטים עם משרד מזוהה), "
            f"ואחריו {n2} עם {_int(v2)}; יחד הם אחראים ל-{_pct(s12)} מהפריטים האלה.")


def insight_secondary_ratio(n_primary, n_secondary):
    if n_primary == 0:
        return None
    ratio = n_secondary / n_primary
    if ratio < 1.5:
        return None
    return (f"על כל חוק ראשי במאגר רשומים בממוצע {ratio:.1f} פריטי חקיקה משנית "
            f"({_int(n_secondary)} פריטי חקיקה משנית לעומת {_int(n_primary)} חוקים).")


def insight_top_authorizing(auth_counts, n_auth):
    if auth_counts.empty or n_auth == 0:
        return None
    name, v = auth_counts.index[0], int(auth_counts.iloc[0])
    share = v / n_auth
    if share < 0.05:
        return None
    k = min(3, len(auth_counts))
    top_k = int(auth_counts.iloc[:k].sum())
    tail = ""
    if k >= 3:
        tail = (f" שלושת החוקים המסמיכים המובילים מסמיכים יחד {_int(top_k)} פריטים "
                f"({_pct(top_k / n_auth)}).")
    return (f"החוק המסמיך הנפוץ ביותר הוא {name}: {_int(v)} פריטי חקיקה משנית "
            f"({_pct(share)} מהפריטים שצוין להם חוק מסמיך).{tail}")


def insight_peak_decade(decades, max_year):
    if len(decades) < 3:
        return None
    ranked = _ranked(decades)
    d, v = int(ranked.index[0]), int(ranked.iloc[0])
    total = int(decades.sum())
    partial = ""
    if max_year is not None and d == (max_year // 10) * 10:
        partial = " — אף שהעשור טרם הסתיים"
    return (f"העשור שבו נחקקו או הותקנו הכי הרבה פריטים שבתוקף במאגר הוא שנות ה-{d} "
            f"({d}-{d + 9}): {_int(v)} פריטים, {_pct(v / total)} מהפריטים ששנתם ידועה{partial}.")


def insight_top_topic(tag_counts, n_tagged):
    if tag_counts.empty or n_tagged == 0:
        return None
    name, v = tag_counts.index[0], int(tag_counts.iloc[0])
    share = v / n_tagged
    if share < 0.1:
        return None
    return (f"הנושא הנפוץ ביותר הוא {name}: {_int(v)} פריטים, {_pct(share)} "
            f"מהפריטים שתויגו בנושא (פריט יכול להשתייך לכמה נושאים).")


def insight_stale(upd_years):
    if len(upd_years) < 30:
        return None
    ref = int(upd_years.max())
    cutoff = ref - 10
    old = int((upd_years <= cutoff).sum())
    share = old / len(upd_years)
    if share < 0.1:
        return None
    return (f"מתוך {_int(len(upd_years))} פריטים שיש להם תאריך עדכון אחרון, {_int(old)} "
            f"({_pct(share)}) לא עודכנו מאז {cutoff} או קודם לכן — עשור ויותר לפני "
            f"העדכון האחרון שנרשם במאגר ({ref}).")


def insight_amend_gap(gaps):
    if len(gaps) < 30:
        return None
    med = float(gaps.median())
    if med < 1:
        return None
    return (f"בקרב {_int(len(gaps))} פריטים שיש להם גם תאריך פרסום וגם תאריך עדכון, "
            f"החציון של הזמן מהפרסום ועד העדכון האחרון הוא {med:.1f} שנים.")


def insight_unspecified(n_unspec, total):
    if total == 0 or n_unspec / total < 0.01:
        return None
    return (f"ל-{_int(n_unspec)} פריטים ({_pct(n_unspec / total)}) לא צוין משרד אחראי "
            f"בקובץ; הם נספרים בסך המאגר אך אינם מופיעים בדירוג המשרדים.")


def insight_joint(n_joint):
    if n_joint < 5:
        return None
    return (f"{_int(n_joint)} פריטים רשומים בשותפות של שני משרדים או יותר; "
            f"בדירוג המשרדים כל אחד מהמשרדים השותפים נספר.")


# ── compute ───────────────────────────────────────────────────────────────

def compute(frames):
    df = _prepare(frames["main"])
    total = len(df)
    n_primary = int((df["ltype"] == PRIMARY).sum())
    n_secondary = int((df["ltype"] == SECONDARY).sum())
    n_reg = int((df["reg"] == "כן").sum())
    n_reg_known = int((df["reg"] != UNSPEC).sum())
    reg_share = n_reg / n_reg_known if n_reg_known else 0.0

    # ── by legislation type × regulatory flag
    types = [t for t in (PRIMARY, SECONDARY, UNSPEC) if (df["ltype"] == t).any()]
    reg_vals = [r for r in ("כן", "לא", UNSPEC) if (df["reg"] == r).any()]
    reg_names = {"כן": "אסדרה", "לא": "לא אסדרה", UNSPEC: "לא סווג"}
    kind_series = [{"name": reg_names[r],
                    "data": [int(((df["ltype"] == t) & (df["reg"] == r)).sum()) for t in types]}
                   for r in reg_vals]
    kind_rows = [{"name": t, "total": int((df["ltype"] == t).sum()),
                  "values": [s["data"][i] for s in kind_series]} for i, t in enumerate(types)]
    p_reg = int(((df["ltype"] == PRIMARY) & (df["reg"] == "כן")).sum())
    s_reg = int(((df["ltype"] == SECONDARY) & (df["reg"] == "כן")).sum())

    # ── offices (exploded)
    ex_off = df[["offices", "ltype"]].explode("offices").dropna(subset=["offices"])
    office_counts = _ranked(ex_off.groupby("offices").size())
    n_unspec = int((df["offices"].map(len) == 0).sum())
    n_with_office = total - n_unspec
    n_joint = int((df["offices"].map(len) > 1).sum())
    n_offices = int(office_counts.size)
    TOP_OFF = 12
    top_off = list(office_counts.index[:TOP_OFF])
    off_names, off_p, off_s = [], [], []
    for o in top_off:
        sub = ex_off[ex_off["offices"] == o]
        p, s = _type_split(sub)
        off_names.append(o)
        off_p.append(p)
        off_s.append(s)
    rest = ex_off[~ex_off["offices"].isin(top_off)]
    n_rest_offices = n_offices - len(top_off)
    if len(rest):
        p, s = _type_split(rest)
        off_names.append(f"{OTHER} ({_int(n_rest_offices)} גופים)")
        off_p.append(p)
        off_s.append(s)
    off_rows = []
    for i, o in enumerate(off_names):
        tot = off_p[i] + off_s[i]
        if i < len(top_off):
            tot = int(office_counts[o])
        else:
            tot = int(len(rest))
        off_rows.append({"name": o, "primary": off_p[i], "secondary": off_s[i], "total": tot})

    # ── instrument form
    form_counts = _ranked(df.groupby("form").size())
    TOP_FORM = 10
    fnames = [f for f in form_counts.index if f != OTHER][:TOP_FORM]
    form_x = list(fnames)
    form_y = [int(form_counts[f]) for f in fnames]
    other_forms = int(total - sum(form_y))
    if other_forms > 0:
        form_x.append(OTHER)
        form_y.append(other_forms)

    # ── decades & years (from the name)
    yd = df.dropna(subset=["year"]).copy()
    yd["year"] = yd["year"].astype(int)
    n_year = len(yd)
    y_min = int(yd["year"].min()) if n_year else None
    y_max = int(yd["year"].max()) if n_year else None
    yd["decade"] = (yd["year"] // 10) * 10
    decades = yd.groupby("decade").size().sort_index()
    dec_x = [str(int(d)) for d in decades.index]
    dec_p = [int(((yd["decade"] == d) & (yd["ltype"] == PRIMARY)).sum()) for d in decades.index]
    dec_s = [int(((yd["decade"] == d) & (yd["ltype"] == SECONDARY)).sum()) for d in decades.index]
    dec_rows = [{"name": f"{int(d)}-{int(d) + 9}", "primary": dec_p[i], "secondary": dec_s[i],
                 "total": int(decades.iloc[i])} for i, d in enumerate(decades.index)]
    yearly_x, yearly_p, yearly_s = [], [], []
    if n_year:
        yp = yd[yd["ltype"] == PRIMARY].groupby("year").size()
        ys = yd[yd["ltype"] == SECONDARY].groupby("year").size()
        for y in range(y_min, y_max + 1):
            yearly_x.append(str(y))
            yearly_p.append(int(yp.get(y, 0)))
            yearly_s.append(int(ys.get(y, 0)))
    yearly_all = [a + b for a, b in zip(yearly_p, yearly_s)]
    zoom_start = max(0, len(yearly_x) - 50)
    peak_year = yearly_x[yearly_all.index(max(yearly_all))] if yearly_all else ""
    peak_year_v = max(yearly_all) if yearly_all else 0

    # ── authorizing laws
    ad = df[df["auth"] != ""]
    n_auth = len(ad)
    auth_counts = _ranked(ad.groupby("auth").size())
    n_auth_laws = int(auth_counts.size)
    TOP_AUTH = 12
    auth_x = list(auth_counts.index[:TOP_AUTH])
    auth_y = [int(v) for v in auth_counts.iloc[:TOP_AUTH]]

    # ── topics (exploded tags)
    ex_tag = df[["tag_list"]].explode("tag_list").dropna(subset=["tag_list"])
    tag_counts = _ranked(ex_tag.groupby("tag_list").size())
    n_tagged = int((df["tag_list"].map(len) > 0).sum())
    n_tags = int(tag_counts.size)
    TOP_TAG = 15
    tag_x = list(tag_counts.index[:TOP_TAG])
    tag_y = [int(v) for v in tag_counts.iloc[:TOP_TAG]]

    # ── heatmap office × topic
    HEAT_N = 10
    heat_off = top_off[:HEAT_N]
    heat_tag = tag_x[:HEAT_N]
    both = df[["offices", "tag_list"]].explode("offices").explode("tag_list").dropna()
    both = both[both["offices"].isin(heat_off) & both["tag_list"].isin(heat_tag)]
    hc = both.groupby(["offices", "tag_list"]).size()
    cells = []
    for yi, o in enumerate(heat_off):
        for xi, t in enumerate(heat_tag):
            cells.append([xi, yi, int(hc.get((o, t), 0))])
    heat_max = max([c[2] for c in cells] or [0])
    heat_peak = max(cells, key=lambda c: (c[2], -c[1], -c[0])) if cells else None

    # ── last update recency (5-year bins)
    upd_years = df["upd"].dropna().dt.year.astype(int)
    n_upd = int(len(upd_years))
    upd_x, upd_y = [], []
    upd_ref = int(upd_years.max()) if n_upd else None
    recent5 = 0
    if n_upd:
        bins = (upd_years // 5) * 5
        bc = bins.value_counts().sort_index()
        MAX_BINS = 9
        keep = list(bc.index[-MAX_BINS:])
        older = int(bc[~bc.index.isin(keep)].sum())
        if older:
            upd_x.append(f"לפני {int(keep[0])}")
            upd_y.append(older)
        for b in keep:
            hi = min(int(b) + 4, upd_ref)
            upd_x.append(f"{int(b)}-{hi}" if hi > int(b) else str(int(b)))
            upd_y.append(int(bc[b]))
        recent5 = int((upd_years > upd_ref - 5).sum())
    recent5_share = recent5 / n_upd if n_upd else 0.0
    upd_primary = int((df["upd"].notna() & (df["ltype"] == PRIMARY)).sum())
    upd_secondary = int((df["upd"].notna() & (df["ltype"] == SECONDARY)).sum())

    # ── amendment gap (publication → last update), in years
    gd = df.dropna(subset=["pub", "upd"])
    gaps = ((gd["upd"] - gd["pub"]).dt.days / 365.25)
    gaps = gaps[gaps >= 0]

    n_wiki = int(df["has_wiki"].sum())
    n_knesset_primary = int((df["has_knesset"] & (df["ltype"] == PRIMARY)).sum())

    rules = [
        ("regulatory", insight_regulatory(n_reg, n_reg_known)),
        ("top_office", insight_top_office(office_counts, n_with_office)),
        ("secondary_ratio", insight_secondary_ratio(n_primary, n_secondary)),
        ("top_authorizing", insight_top_authorizing(auth_counts, n_auth)),
        ("peak_decade", insight_peak_decade(decades, y_max)),
        ("top_topic", insight_top_topic(tag_counts, n_tagged)),
        ("stale", insight_stale(upd_years)),
        ("amend_gap", insight_amend_gap(gaps)),
        ("joint", insight_joint(n_joint)),
        ("unspecified", insight_unspecified(n_unspec, total)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    lead_off = off_names[0] if off_names else ""
    lead_off_v = off_rows[0]["total"] if off_rows else 0
    lead_tag = tag_x[0] if tag_x else ""
    lead_auth = auth_x[0] if auth_x else ""
    span = f"{y_min}-{y_max}" if n_year else "—"
    span_kpi = f"{y_min}–{y_max}" if n_year else "—"

    summary = (f"מאגר האסדרה האחוד מונה {_int(total)} פריטי חקיקה: {_int(n_primary)} חוקים "
               f"(חקיקה ראשית) ו-{_int(n_secondary)} פריטי חקיקה משנית מ-{_int(n_offices)} "
               f"משרדים וגופים, ש-{_pct(reg_share)} מהם מסווגים כאסדרה. "
               f"הפריטים נחקקו או הותקנו בשנים {span}, והמשרד עם מספר הפריטים הגדול ביותר "
               f"הוא {lead_off}.")

    meta = (f"איתור חוקים, תקנות וצווים במאגר האסדרה לפי שם, משרד או נושא: {_int(total)} פריטים, "
            f"מהם {_int(n_primary)} חוקים ו-{_int(n_secondary)} פריטי חקיקה משנית.")

    return {
        "agent_data": {
            "summary_he": meta,
            "dataset_kind": "registry",
            "suggested_tags": ["רגולציה", "אסדרה", "חקיקה", "תקנות", "חקיקה משנית"],
            "related_ids": ["da426b40-21c8-4b64-81b7-d6ecfd23d99a"],
            "temporal_coverage": f"{y_min}/{y_max}" if n_year else None,
            "spatial_coverage": "ישראל",
        },
        "kpis": {
            "total": {"value": total, "display": _int(total), "tone": "brand"},
            "reg_share": {"value": reg_share, "display": _pct(reg_share),
                          "tone": "info"},
            "primary": {"value": n_primary, "display": _int(n_primary), "tone": "brand"},
            "secondary": {"value": n_secondary, "display": _int(n_secondary), "tone": "brand"},
            "offices": {"value": n_offices, "display": _int(n_offices), "tone": "brand"},
            "span": {"value": [y_min, y_max], "display": span_kpi, "tone": "brand"},
            "recent5": {"value": recent5_share, "display": _pct(recent5_share),
                        "tone": "info"},
            "auth_laws": {"value": n_auth_laws, "display": _int(n_auth_laws), "tone": "brand"},
        },
        "charts": {
            "kind": {"x": types, "series": kind_series},
            "offices": {"x": off_names, "primary": off_p, "secondary": off_s},
            "forms": {"x": form_x, "y": form_y},
            "decades": {"x": dec_x, "primary": dec_p, "secondary": dec_s},
            "yearly": {"x": yearly_x, "primary": yearly_p, "secondary": yearly_s,
                       "zoom_start": zoom_start},
            "authorizing": {"x": auth_x, "y": auth_y},
            "topics": {"x": tag_x, "y": tag_y},
            "heat": {"x": heat_tag, "y": heat_off, "cells": cells, "max": heat_max},
            "updates": {"x": upd_x, "y": upd_y},
        },
        "tables": {
            "kind": kind_rows,
            "kind_cols": [s["name"] for s in kind_series],
            "offices": off_rows,
            "decades": dec_rows,
        },
        "insights": insights,
        "flags": {
            "heat": bool(heat_max > 0 and len(heat_off) >= 3 and len(heat_tag) >= 3),
            "updates": n_upd >= 30,
            "authorizing": len(auth_x) >= 3,
            "yearly": len(yearly_x) >= 5,
        },
        "labels": {
            "lede": summary,
            "reg_kpi": "מהפריטים מסווגים כאסדרה",
            "recent5_kpi": (f"מהפריטים המתוארכים עודכנו בחמש השנים האחרונות במאגר "
                            f"({upd_ref - 4}-{upd_ref})" if n_upd else "עדכון בחמש השנים האחרונות"),
            "kind_lede": (f"מתוך {_int(n_primary)} חוקים, {_int(p_reg)} ({_pct(p_reg / n_primary if n_primary else 0)}) "
                          f"מסווגים כאסדרה; בחקיקה המשנית השיעור הוא "
                          f"{_pct(s_reg / n_secondary if n_secondary else 0)} "
                          f"({_int(s_reg)} מתוך {_int(n_secondary)})."),
            "kind_aria": (f"תרשים עמודות מוערמות: פריטי המאגר לפי סוג חקיקה וסיווג אסדרה. "
                          f"{_int(n_secondary)} פריטי חקיקה משנית ו-{_int(n_primary)} חוקים."),
            "offices_lede": (f"{lead_off} מוביל עם {_int(lead_off_v)} פריטים. מוצגים {len(top_off)} "
                             f"המשרדים המובילים מתוך {_int(n_offices)}; "
                             f"{_int(n_unspec)} פריטים ללא משרד מזוהה אינם מוצגים, "
                             f"ופריט משותף נספר אצל כל משרד שותף."),
            "offices_aria": (f"תרשים עמודות אופקי מוערם: מספר פריטי האסדרה לפי משרד, חקיקה ראשית ומשנית. "
                             f"{lead_off} מוביל עם {_int(lead_off_v)} פריטים."),
            "forms_lede": (f"צורת הדבר נגזרת מהמילה הראשונה בשם הפריט. הצורה הנפוצה היא "
                           f"{form_x[0] if form_x else ''} עם {_int(form_y[0] if form_y else 0)} פריטים "
                           f"({_pct((form_y[0] / total) if total and form_y else 0)})."),
            "forms_aria": (f"תרשים עמודות: פריטי המאגר לפי צורת דבר החקיקה. "
                           f"{form_x[0] if form_x else ''} הנפוצה ביותר עם {_int(form_y[0] if form_y else 0)} פריטים."),
            "decades_lede": (f"שנת החקיקה נלקחת מהשנה שבשם הפריט וידועה ל-{_int(n_year)} מתוך "
                             f"{_int(total)} פריטים. למאגר נכנסים רק פריטים שבתוקף, ולכן עשורים "
                             f"מוקדמים מיוצגים רק בדברי החקיקה ששרדו מהם."),
            "decades_aria": (f"תרשים עמודות מוערמות: פריטי המאגר לפי עשור החקיקה, {span}, "
                             f"חקיקה ראשית ומשנית."),
            "yearly_lede": (f"השנה עם מספר הפריטים הגדול ביותר היא {peak_year} עם {_int(peak_year_v)} פריטים. "
                            f"גררו את הסרגל כדי לראות את כל הטווח."),
            "yearly_aria": (f"גרף קו: מספר פריטי המאגר לפי שנת החקיקה, {span}. "
                            f"השיא ב-{peak_year} עם {_int(peak_year_v)} פריטים."),
            "auth_lede": (f"{_int(n_auth)} פריטי חקיקה משנית הותקנו מכוח {_int(n_auth_laws)} חוקים מסמיכים. "
                          f"המוביל: {lead_auth} עם {_int(auth_y[0] if auth_y else 0)} פריטים."),
            "auth_aria": (f"תרשים עמודות אופקי: {len(auth_x)} החוקים המסמיכים עם מספר פריטי החקיקה המשנית הגדול ביותר. "
                          f"המוביל {lead_auth}."),
            "topics_lede": (f"{_int(n_tagged)} פריטים תויגו ב-{_int(n_tags)} נושאים; פריט יכול להשתייך "
                            f"לכמה נושאים. הנושא הנפוץ: {lead_tag} עם {_int(tag_y[0] if tag_y else 0)} פריטים."),
            "topics_aria": (f"תרשים עמודות אופקי: {len(tag_x)} הנושאים הנפוצים במאגר. "
                            f"{lead_tag} מוביל עם {_int(tag_y[0] if tag_y else 0)} פריטים."),
            "heat_lede": ((f"הצירוף הנפוץ ביותר: {heat_off[heat_peak[1]]} בנושא {heat_tag[heat_peak[0]]}, "
                           f"עם {_int(heat_peak[2])} פריטים. מוצגים {len(heat_off)} המשרדים ו-"
                           f"{len(heat_tag)} הנושאים המובילים.") if heat_peak else ""),
            "heat_aria": (f"מפת חום: מספר הפריטים לכל צירוף של משרד ונושא, {len(heat_off)} משרדים על "
                          f"{len(heat_tag)} נושאים."),
            "updates_lede": (f"תאריך עדכון אחרון קיים ל-{_int(n_upd)} פריטים בלבד: {_int(upd_primary)} "
                             f"מתוך {_int(n_primary)} החוקים ו-{_int(upd_secondary)} מתוך {_int(n_secondary)} "
                             f"פריטי החקיקה המשנית. העדכון המאוחר ביותר שנרשם הוא משנת {upd_ref}."
                             if n_upd else ""),
            "updates_aria": (f"תרשים עמודות: פריטים לפי תקופת העדכון האחרון, עבור {_int(n_upd)} פריטים "
                             f"שיש להם תאריך עדכון."),
            "wiki_note": (f"ל-{_int(n_wiki)} פריטים ({_pct(n_wiki / total if total else 0)}) מצורף "
                          f"קישור לנוסח בוויקיטקסט, ול-{_int(n_knesset_primary)} חוקים קישור לאתר הכנסת."),
        },
    }
