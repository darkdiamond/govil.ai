"""מאגר תקנים רשמיים — Israel's register of official (mandatory) standards.

Five related files:
  standards — the register itself: one row per standard EDITION in force
              (a standard in transition has two editions listed). Joined on
              `standard_number`; we keep the newest edition per number.
  routes    — import routes under the international-standard (CASSIS)
              track: one row per route, keyed by `index` (the edition key of
              `standards`); a standard can have more than one route.
  gazette   — publications in Reshumot (the official gazette): declarations,
              revisions, amendment sheets, removals, exemptions, laws/orders.
  reform    — a separate, older list "updated for the 'what's good for
              Europe' reform" with the register's schema; compared to the
              current register by standard number.
  eu        — European regulations / directives adopted, with entry dates.

"Latest" is always latest in the data (never the wall clock).
"""
import re

import pandas as pd

MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]
IN_FORCE = "התקן בתוקף"
TOP_TOPICS = 12
TOP_GAZ_STD = 12
TOP_ROUTES = 8
BODIES = ["EN", "IEC", "CISPR", "ISO", "EC/EU", "UL", "ANSI", "ASTM", "CFR", "BS",
          "DIN", "AS/NZS", "ECE", "CSA", "NSF", "JIS", "SAE", "ASME", "NFPA"]
BODY_RE = re.compile(r"(?<![A-Za-z/])(AS/NZS|EN|IEC|CISPR|ISO|EC|EU|UL|ANSI|ASTM|CFR|BS|DIN|ECE|CSA|NSF|JIS|SAE|ASME|NFPA)(?![A-Za-z/])")
STD_RE = re.compile(r'ת"י\s*(\d+)(?:\s*חלק\s*(\d+(?:\.\d+)*))?')
ACTION_ORDER = ["החלפת תקן (רביזיה)", "גיליון תיקון", "הסרת רשמיות", "הכרזה על תקן רשמי",
                "דחייה והארכת מועדים", "פטור", "חקיקה, צווים וכללים", "תיקון טעות", "אחר"]
PROCESS_ORDER = ["רביזיה", "פרסום גיליון תיקון", "הסרת רשמיות", "פטור"]
GROUP_NA = "לא רלוונטי"


def n(v):
    return f"{int(v):,}"


def pct(v, digits=1):
    return f"{v * 100:.{digits}f}%"


def d_he(ts):
    return f"{ts.day} ב{MONTHS_HE[ts.month - 1]} {ts.year}"


def clean(s):
    return s.fillna("").astype(str).str.replace(r"\s+", " ", regex=True).str.strip()


def year_of_edition(edition, index):
    y = pd.to_numeric(edition.str.extract(r"((?:19|20)\d{2})")[0], errors="coerce")
    alt = pd.to_numeric(index.str[-6:-2], errors="coerce")
    y = y.fillna(alt)
    return y.where(y.between(1900, 2100))


def classify_action(s):
    if "ביטול רשמיות" in s or "הסרת רשמיות" in s:
        return "הסרת רשמיות"
    if "רביזיה" in s or s.startswith("החלפה"):
        return "החלפת תקן (רביזיה)"
    if "גליון תיקון" in s or "גליונות תיקון" in s or "גיליון תיקון" in s:
        return "גיליון תיקון"
    if "תקן רשמי" in s or "סעיפים רשמיים" in s or s == "אכרזת רשמיות":
        return "הכרזה על תקן רשמי"
    if "דחי" in s or "הארכת תקופת" in s or "חפיפה" in s:
        return "דחייה והארכת מועדים"
    if "פטור" in s:
        return "פטור"
    if "תיקון טעות" in s:
        return "תיקון טעות"
    if any(k in s for k in ("חוק", "צו ", "צו", "פקודת", "כללי", "תוספת", "תו תקן", "הרשימה")):
        return "חקיקה, צווים וכללים"
    return "אחר"


def classify_process(item):
    if item == "" or item == "לא בתהליך":
        return None
    if "רביזיה" in item:
        return "רביזיה"
    if "גיליון תיקון" in item or "גליון תיקון" in item:
        return "פרסום גיליון תיקון"
    if "הסרת רשמיות" in item or "ביטול רשמיות" in item:
        return "הסרת רשמיות"
    if "פטור" in item:
        return "פטור"
    return item


def amend_count(s):
    if s in ("", "אין"):
        return 0
    return max(1, len(re.findall(r"תיקון", s)))


def eu_kind(he, en):
    if he.startswith("דירקטיבה"):
        return "דירקטיבה"
    if he.startswith("רגולציה"):
        return "רגולציה"
    if en.startswith("Directive") or en.startswith("Council Directive"):
        return "דירקטיבה"
    if "Regulation" in en.split(" of ")[0]:
        return "רגולציה"
    return "אחר"


def short(s, k=48):
    return s if len(s) <= k else s[: k - 1].rstrip() + "…"


def norm_std(num, part):
    return f'ת"י {int(num)}' + (f" חלק {part}" if part else "")


def sorted_counts(series):
    vc = series.value_counts()
    return vc.sort_index().sort_values(ascending=False, kind="stable")


def top_other(vc, k):
    top = vc.head(k)
    other = int(vc.iloc[k:].sum())
    names = [str(x) for x in top.index] + (["אחר"] if other else [])
    vals = [int(v) for v in top.values] + ([other] if other else [])
    return names, vals


# --------------------------------------------------------------- prepare

def prep_standards(df):
    out = pd.DataFrame({
        "index": clean(df["index"]),
        "num": clean(df["standard_number"]),
        "name": clean(df["standard_name"]),
        "edition": clean(df["standard_edition"]),
        "vfrom": clean(df["validity_from"]),
        "vto": clean(df["validity_to"]),
        "amend": clean(df["amendments"]),
        "sections": clean(df["mandatory_sections"]),
        "process": clean(df["standard_process"]),
        "orig": clean(df["standard_originality"]),
        "groups": clean(df["standard_import_groups"]),
        "conds": clean(df["standard_import_conditions"]),
        "mand": clean(df["is_standard_mandatory"]),
        "cassis": clean(df["is_in_cassis"]),
        "eu": clean(df["is_in_international_regulations"]),
    })
    out = out[out["num"] != ""].copy()
    out["year"] = year_of_edition(out["edition"], out["index"])
    out["vto_d"] = pd.to_datetime(out["vto"], errors="coerce", format="%d/%m/%Y")
    out["vfrom_d"] = pd.to_datetime(out["vfrom"], errors="coerce", format="%d/%m/%Y")
    out["ym"] = out["index"].str[-6:]
    return out


def newest_per_number(ed):
    s = ed.sort_values(["num", "ym", "index"], ascending=[True, False, False], kind="stable")
    return s.drop_duplicates("num", keep="first").sort_values("num", kind="stable").reset_index(drop=True)


def prep_gazette(df):
    out = pd.DataFrame({
        "pub": clean(df["publication"]),
        "date": pd.to_datetime(df["date"].astype(str).str[:10], errors="coerce", format="%Y-%m-%d"),
        "kind": clean(df["summary_full"]),
        "kind_short": clean(df["summary"]),
        "stds": clean(df["standards"]),
    })
    out["kind"] = out["kind"].where(out["kind"] != "", out["kind_short"])
    out["action"] = out["kind"].map(classify_action)
    out["venue"] = out["pub"].str.extract(r"^(קובץ ה?תקנות|ילקוט הפרסומים|ילקוט פרסומים|ספר החוקים)")[0]
    out["venue"] = out["venue"].replace({"קובץ התקנות": "קובץ תקנות", "ילקוט הפרסומים": "ילקוט פרסומים"}).fillna("אחר")
    out["refs"] = out["stds"].map(lambda s: sorted({norm_std(a, b) for a, b in STD_RE.findall(s)}))
    return out


# --------------------------------------------------------------- insights

def insight_adoption(std, recent_from):
    known = std.dropna(subset=["year"])
    adopted = std["orig"] != "מקורי"
    a = known[known["year"] >= recent_from]
    b = known[known["year"] < recent_from]
    s = f"{pct(adopted.mean())} מהתקנים הרשמיים בתוקף ({n(adopted.sum())} מתוך {n(len(std))}) מאומצים מתקינה בין-לאומית או זרה; השאר מקוריים."
    if len(a) >= 20 and len(b) >= 20:
        ra, rb = (a["orig"] != "מקורי").mean(), (b["orig"] != "מקורי").mean()
        if abs(ra - rb) >= 0.05:
            word = "עולה" if ra > rb else "יורד"
            s += (f" השיעור {word} במהדורות החדשות: {pct(ra)} מהמהדורות מ-{recent_from} ואילך, "
                  f"לעומת {pct(rb)} במהדורות שקדמו להן.")
        else:
            s += f" השיעור דומה במהדורות מ-{recent_from} ואילך ({pct(ra)}) ובמהדורות שקדמו להן ({pct(rb)})."
    return s


def insight_routes(routes_counts, total):
    both, eu_only, cas_only, neither = routes_counts
    if total == 0:
        return None
    eu = both + eu_only
    return (f"{n(eu)} תקנים ({pct(eu / total)}) כלולים במסלול ההתאמה לאסדרה האירופית ו-{n(both + cas_only)} "
            f"({pct((both + cas_only) / total)}) במסלול התקינה הבין-לאומית (קסיס); "
            f"{n(neither)} תקנים ({pct(neither / total)}) אינם כלולים באף אחד מהשניים.")


def insight_gazette(per_year, last_full, partial_year):
    full = per_year[per_year.index <= last_full]
    if len(full) < 5:
        return None
    peak_y = int(full.sort_index().idxmax())
    peak_v = int(full.max())
    s = f"שנת השיא בפרסומי התקינה ברשומות היא {peak_y}, עם {n(peak_v)} פרסומים"
    prev = full[(full.index < last_full) & (full.index >= last_full - 5)]
    if last_full in full.index and len(prev) >= 3:
        v = int(full[last_full])
        med = float(prev.median())
        if med > 0:
            chg = v / med - 1
            if abs(chg) < 0.1:
                s += f". ב-{last_full} פורסמו {n(v)} — בדומה לחציון חמש השנים שקדמו לה ({med:g})"
            else:
                word = "מעל ל" if chg > 0 else "מתחת ל"
                s += f". ב-{last_full} פורסמו {n(v)} — {word}חציון חמש השנים שקדמו לה ({med:g})"
    if partial_year is not None:
        s += f"; {partial_year[0]} חלקית ({n(partial_year[1])} פרסומים עד {d_he(partial_year[2])})"
    return s + "."


def insight_actions(actions, total):
    if total == 0 or actions.empty:
        return None
    name, v = actions.index[0], int(actions.iloc[0])
    if v / total < 0.2:
        return None
    s = f"הפעולה הנפוצה ברשומות היא {name}: {n(v)} מתוך {n(total)} הפרסומים ({pct(v / total)})"
    if len(actions) > 1:
        s += f", ואחריה {actions.index[1]} ({n(actions.iloc[1])})"
    return s + "."


def insight_top_std(ref_counts, std_names):
    if len(ref_counts) < 2:
        return None
    top, v = ref_counts.index[0], int(ref_counts.iloc[0])
    if v < 5 or int(ref_counts.iloc[1]) == v:
        return None
    nm = std_names.get(top)
    label = f"{top} ({nm})" if nm else top
    return f"התקן שהוזכר במספר הפרסומים הרב ביותר ברשומות הוא {label} — {n(v)} פרסומים."


def insight_topic(topics, total):
    if topics.empty:
        return None
    name, v = topics.index[0], int(topics.iloc[0])
    if v < 10:
        return None
    return (f"הנושא עם מספר החלקים הרב ביותר הוא \"{name}\" — {n(v)} תקנים רשמיים "
            f"({pct(v / total)} מהמאגר).")


def insight_transition(trans, dup_numbers):
    if trans.empty:
        return None
    first, last = trans["vto_d"].min(), trans["vto_d"].max()
    s = (f"{n(len(trans))} מהדורות תקן רשומות עם תאריך סיום תוקף, בין {d_he(first)} ל-{d_he(last)}")
    if dup_numbers:
        s += f"; ל-{n(dup_numbers)} תקנים רשומות כעת שתי מהדורות במקביל (תקופת מעבר)"
    return s + "."


def insight_eu(eu):
    if len(eu) < 5:
        return None
    eco = int(eu["eco"].sum())
    s = f"{n(len(eu))} אסדרות אירופיות אומצו"
    if eco >= 5:
        s += f", מהן {n(eco)} ({pct(eco / len(eu))}) בתחום העיצוב האקולוגי וסימון האנרגיה"
    d = eu["date"].dropna()
    if not d.empty:
        first = d.min()
        at_first = int((d == first).sum())
        s += (f". מועדי הכניסה לתוקף נפרסים מ{MONTHS_HE[first.month - 1]} {first.year} "
              f"({n(at_first)} אסדרות) עד {MONTHS_HE[d.max().month - 1]} {d.max().year}")
    return s + "."


def insight_age(std, ref_year):
    y = std["year"].dropna()
    if len(y) < 20:
        return None
    old_cut = ref_year - 20
    old = (y < old_cut).mean()
    return (f"חציון שנת המהדורה של התקנים בתוקף הוא {int(y.median())}; {pct(old)} מהם "
            f"במהדורה שפורסמה לפני {old_cut}, והוותיקה ביותר מ-{int(y.min())}.")


def insight_process(proc_counts, total, revising):
    if total == 0 or revising == 0:
        return None
    s = f"{n(revising)} תקנים ({pct(revising / total)}) נמצאים בתהליך עדכון כלשהו"
    parts = [f"{k} — {n(v)}" for k, v in proc_counts]
    if parts:
        s += ": " + "; ".join(parts[:3])
    return s + "."


# --------------------------------------------------------------- compute

def compute(frames):
    ed = prep_standards(frames["standards"])
    std = newest_per_number(ed)
    total = len(std)
    editions = len(ed)

    gz = prep_gazette(frames["gazette"])
    gz_dated = gz.dropna(subset=["date"])
    gz_ref = gz_dated["date"].max()
    gz_year = int(gz_ref.year)
    gz_partial = not (gz_ref.month == 12)
    gz_last_full = gz_year - 1 if gz_partial else gz_year

    # ---- composition: adoption type, edition year buckets
    orig_vc = sorted_counts(std["orig"].replace("", "לא צוין"))
    ref_year = int(std["year"].max())
    recent_from = ref_year - 9
    y = std["year"]
    lo = int(y.min()) // 5 * 5
    buckets = list(range(lo, ref_year + 1, 5))
    is_orig = std["orig"] == "מקורי"
    ed_rows = []
    for b in buckets:
        m = (y >= b) & (y < b + 5)
        ed_rows.append({"label": f"{b}–{min(b + 4, ref_year)}" if b + 4 != b else str(b),
                        "orig": int((m & is_orig).sum()), "adopt": int((m & ~is_orig).sum())})
    no_year = int(y.isna().sum())

    # ---- topics (name before the first colon)
    topic = std["name"].str.split(":").str[0].str.strip()
    topics = sorted_counts(topic[topic != ""])
    multi = topics[topics >= 2]
    t_top = topics.head(TOP_TOPICS)
    t_cover = int(t_top.sum())

    # ---- routes matrix (EU regulation × CASSIS)
    eu_f = std["eu"] == "כן"
    cas_f = std["cassis"] == "כן"
    rc = (int((eu_f & cas_f).sum()), int((eu_f & ~cas_f).sum()),
          int((~eu_f & cas_f).sum()), int((~eu_f & ~cas_f).sum()))
    route_names = ["שני המסלולים", "אסדרה אירופית בלבד", "קסיס בלבד", "אף מסלול"]

    # ---- import groups (multi-valued)
    toks = []
    for s in std["groups"]:
        for t in re.split(r"[,;]", s):
            t = t.strip()
            if t:
                toks.append(t)
    gvc = pd.Series(toks, dtype=str).value_counts()
    g_num = sorted([k for k in gvc.index if k.isdigit()], key=int)
    g_other = sorted([k for k in gvc.index if not k.isdigit()])
    g_names = [f"קבוצה {k}" for k in g_num] + g_other
    g_vals = [int(gvc[k]) for k in g_num] + [int(gvc[k]) for k in g_other]
    multi_group = int(std["groups"].str.contains(",").sum())
    with_conds = int((~std["conds"].isin(["", "אין"])).sum())

    # ---- CASSIS route file
    rt = frames["routes"]
    rt_idx = clean(rt["index"])
    rt_name = clean(rt["adoption_route_name"]).replace("", "לא צוין")
    rt_vc = sorted_counts(rt_name)
    r_names, r_vals = top_other(rt_vc, TOP_ROUTES)
    rt_std = int(rt_idx[rt_idx != ""].nunique())
    rt_multi = int((rt_idx[rt_idx != ""].value_counts() > 1).sum())
    docs = clean(rt["documents_combination"])
    body_cnt = {}
    for s in docs:
        found = {("EC/EU" if t in ("EC", "EU") else t) for t in BODY_RE.findall(s)}
        for t in found:
            body_cnt[t] = body_cnt.get(t, 0) + 1
    bodies = sorted([(b, c) for b, c in body_cnt.items()], key=lambda x: (-x[1], BODIES.index(x[0])))[:10]
    rt_total = len(rt)
    rt_exempt = int(clean(rt["detailed_comments"]).str.contains("פטור מבדיקת יבוא").sum())
    rt_conds = int((clean(rt["conditions"]) != "").sum())
    rt_extra = int((clean(rt["additional_documents_for_specific_products"]) != "").sum())

    # ---- process and amendments
    proc_cnt = {}
    revising = 0
    for s in std["process"]:
        cats = {c for c in (classify_process(x.strip()) for x in s.split(";")) if c}
        if cats:
            revising += 1
        for c in cats:
            proc_cnt[c] = proc_cnt.get(c, 0) + 1
    proc = sorted(proc_cnt.items(), key=lambda kv: (-kv[1], PROCESS_ORDER.index(kv[0]) if kv[0] in PROCESS_ORDER else 99, kv[0]))
    am = std["amend"].map(amend_count)
    am_labels = ["ללא", "1", "2", "3", "4+"]
    am_vals = [int((am == 0).sum()), int((am == 1).sum()), int((am == 2).sum()),
               int((am == 3).sum()), int((am >= 4).sum())]
    am_max = int(am.max()) if len(am) else 0
    all_sections = int(std["sections"].str.startswith("כל הסעיפים").sum())
    partial_sections = total - all_sections

    # ---- editions in transition (have an end date)
    trans = ed.dropna(subset=["vto_d"]).sort_values(["vto_d", "num", "index"], kind="stable")
    dup_numbers = int((ed["num"].value_counts() > 1).sum())
    by_num = {k: g for k, g in ed.groupby("num", sort=True)}
    trans_rows = []
    for _, r in trans.head(20).iterrows():
        others = by_num[r["num"]]
        others = others[(others["index"] != r["index"]) & others["vto_d"].isna()]
        newer = others.sort_values(["ym", "index"], ascending=False, kind="stable")
        trans_rows.append({
            "num": r["num"], "name": r["name"], "edition": r["edition"] or "—",
            "until": r["vto_d"].strftime("%d.%m.%Y"),
            "new": newer.iloc[0]["edition"] if len(newer) else "—",
            "new_from": (newer.iloc[0]["vfrom_d"].strftime("%d.%m.%Y")
                         if len(newer) and pd.notna(newer.iloc[0]["vfrom_d"]) else "—"),
        })

    # ---- gazette
    gz_total = len(gz)
    per_year = gz_dated.groupby(gz_dated["date"].dt.year).size()
    per_year.index = per_year.index.astype(int)
    # chart starts at the first year from which every year has a publication
    years_all = list(range(int(per_year.index.min()), gz_year + 1))
    start = gz_year
    for yv in reversed(years_all):
        if yv in per_year.index:
            start = yv
        else:
            break
    early = int(per_year[per_year.index < start].sum())
    first_year = int(per_year.index.min())
    yrs = list(range(start, gz_year + 1))
    sub = gz_dated[gz_dated["date"].dt.year >= start]
    by = sub.groupby([sub["date"].dt.year, "action"]).size().unstack(fill_value=0)
    actions_all = sorted_counts(gz["action"])
    act_present = [a for a in ACTION_ORDER if a in actions_all.index]
    gz_series = [{"name": a, "data": [int(by.loc[yv, a]) if (yv in by.index and a in by.columns) else 0 for yv in yrs]}
                 for a in act_present]
    gz_year_totals = [int(per_year.get(yv, 0)) for yv in yrs]
    partial_info = (gz_year, int(per_year.get(gz_year, 0)), gz_ref) if gz_partial else None
    venue = sorted_counts(gz["venue"])
    no_std = int((gz["refs"].str.len() == 0).sum())
    ref_counts = sorted_counts(pd.Series([r for lst in gz["refs"] for r in lst], dtype=str))
    names_by_num = dict(zip(std["num"], std["name"]))
    ed_names = dict(zip(ed["num"], ed["name"]))
    gtop = ref_counts.head(TOP_GAZ_STD)
    gtop_rows = [{"num": k, "name": names_by_num.get(k, ed_names.get(k, "")) or "אינו במאגר הנוכחי",
                  "count": int(v), "in_force": k in names_by_num} for k, v in gtop.items()]

    # ---- EU regulations
    euf = frames["eu"]
    eu = pd.DataFrame({
        "he": clean(euf["directive_hebrew_name"]),
        "en": clean(euf["directive_en_name"]),
        "date": pd.to_datetime(euf["directive_date"].astype(str).str[:10], errors="coerce", format="%Y-%m-%d"),
        "terms": clean(euf["terms"]),
        "comments": clean(euf["comments"]),
    })
    eu["kind"] = [eu_kind(h, e) for h, e in zip(eu["he"], eu["en"])]
    eu["eco"] = eu["he"].str.contains("עיצוב אקולוגי|סימון אנרגטי", regex=True)
    eu_years = sorted(int(v) for v in eu["date"].dropna().dt.year.unique())
    eu_kinds = [k for k in ["רגולציה", "דירקטיבה", "אחר"] if (eu["kind"] == k).any()]
    eu_series = [{"name": k, "data": [int(((eu["kind"] == k) & (eu["date"].dt.year == yv)).sum()) for yv in eu_years]}
                 for k in eu_kinds]
    eu_terms = int((~eu["terms"].isin(["", "אין"])).sum())
    eu_comments = int((~eu["comments"].isin(["", "אין"])).sum())

    # ---- reform list vs current register
    rf = frames["reform"]
    rf_nums = set(clean(rf["standard_number"])) - {""}
    rf_year = year_of_edition(clean(rf["standard_edition"]), clean(rf["index"]))
    rf_latest = int(rf_year.max()) if rf_year.notna().any() else None
    cur_nums = set(std["num"])
    both_n = len(rf_nums & cur_nums)
    only_rf = len(rf_nums - cur_nums)
    only_cur = len(cur_nums - rf_nums)

    # ---- insights
    rules = [
        ("adoption", insight_adoption(std, recent_from)),
        ("routes", insight_routes(rc, total)),
        ("gazette", insight_gazette(per_year, gz_last_full, partial_info)),
        ("actions", insight_actions(actions_all, gz_total)),
        ("top_std", insight_top_std(ref_counts, names_by_num)),
        ("topic", insight_topic(topics, total)),
        ("transition", insight_transition(trans, dup_numbers)),
        ("eu", insight_eu(eu)),
        ("age", insight_age(std, ref_year)),
        ("process", insight_process(proc, total, revising)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    # ---- KPIs
    adopted_share = float((std["orig"] != "מקורי").mean()) if total else 0.0
    eu_share = (rc[0] + rc[1]) / total if total else 0.0
    gz_last_v = int(per_year.get(gz_last_full, 0))
    gz_prev = per_year[(per_year.index < gz_last_full) & (per_year.index >= gz_last_full - 5)]
    gz_med = float(gz_prev.median()) if len(gz_prev) else None
    if gz_med is None or gz_med == 0 or abs(gz_last_v / gz_med - 1) < 0.1:
        gz_tone = "brand"
    else:
        gz_tone = "info"
    kpis = {
        "total": {"value": total, "display": n(total), "tone": "brand"},
        "adopted": {"value": round(adopted_share * 100, 1), "display": f"{adopted_share * 100:.1f}%", "tone": "info"},
        "eu": {"value": round(eu_share * 100, 1), "display": f"{eu_share * 100:.1f}%", "tone": "info"},
        "cassis": {"value": rc[0] + rc[2], "display": n(rc[0] + rc[2]), "tone": "brand"},
        "revising": {"value": revising, "display": n(revising),
                     "tone": "warn" if total and revising / total >= 0.15 else "brand"},
        "transition": {"value": len(trans), "display": n(len(trans)), "tone": "warn" if len(trans) else "ok"},
        "gazette": {"value": gz_last_v, "display": n(gz_last_v), "tone": gz_tone},
        "eu_regs": {"value": len(eu), "display": n(len(eu)), "tone": "brand"},
    }

    # ---- charts
    charts = {
        "orig": {"names": [str(k) for k in orig_vc.index], "values": [int(v) for v in orig_vc.values]},
        "editions": {"x": [r["label"] for r in ed_rows],
                     "orig": [r["orig"] for r in ed_rows], "adopt": [r["adopt"] for r in ed_rows]},
        "topics": {"names": [str(k) for k in t_top.index], "short": [short(str(k)) for k in t_top.index],
                   "values": [int(v) for v in t_top.values]},
        "routes": {"names": route_names, "values": list(rc)},
        "groups": {"names": g_names, "values": g_vals},
        "cassis": {"names": r_names, "values": r_vals},
        "bodies": {"names": [b for b, _ in bodies], "values": [c for _, c in bodies]},
        "process": {"names": [k for k, _ in proc], "values": [v for _, v in proc]},
        "amend": {"names": am_labels, "values": am_vals},
        "gazette": {"x": [str(v) for v in yrs], "series": gz_series},
        "actions": {"names": [str(k) for k in actions_all.index], "values": [int(v) for v in actions_all.values]},
        "gaz_std": {"names": [r["num"] for r in gtop_rows], "full": [r["name"] for r in gtop_rows],
                    "values": [r["count"] for r in gtop_rows]},
        "eu": {"x": [str(v) for v in eu_years], "series": eu_series},
        "reform": {"names": ["בשתי הרשימות", "ברשימת הרפורמה בלבד", "במאגר הנוכחי בלבד"],
                   "values": [both_n, only_rf, only_cur]},
    }

    tables = {
        "orig": [{"name": k, "count": n(v)} for k, v in zip(charts["orig"]["names"], charts["orig"]["values"])],
        "editions": [{"label": r["label"], "orig": n(r["orig"]), "adopt": n(r["adopt"])} for r in ed_rows],
        "topics": [{"name": k, "count": n(v)} for k, v in zip(charts["topics"]["names"], charts["topics"]["values"])],
        "routes": [{"name": k, "count": n(v)} for k, v in zip(route_names, rc)],
        "groups": [{"name": k, "count": n(v)} for k, v in zip(g_names, g_vals)],
        "cassis": [{"name": k, "count": n(v)} for k, v in zip(r_names, r_vals)],
        "bodies": [{"name": b, "count": n(c)} for b, c in bodies],
        "process": [{"name": k, "count": n(v)} for k, v in proc],
        "amend": [{"name": k, "count": n(v)} for k, v in zip(am_labels, am_vals)],
        "actions": [{"name": k, "count": n(v)} for k, v in zip(charts["actions"]["names"], charts["actions"]["values"])],
        "gaz_std": [{"num": r["num"], "name": r["name"], "count": n(r["count"])} for r in gtop_rows],
        "eu": [{"year": str(yv), "cells": [n(s["data"][i]) for s in eu_series]} for i, yv in enumerate(eu_years)],
        "eu_kinds": eu_kinds,
        "reform": [{"name": k, "count": n(v)} for k, v in zip(charts["reform"]["names"], charts["reform"]["values"])],
        "transition": trans_rows,
    }

    venue_txt = "; ".join(f"{k} — {n(v)}" for k, v in venue.items())
    early_txt = (f" {n(early)} פרסומים מוקדמים יותר ({first_year}–{start - 1}) אינם מוצגים בתרשים."
                 if early else "")
    partial_txt = (f" {gz_year} — שנה חלקית, עד {d_he(gz_ref)}." if gz_partial else "")
    labels = {
        "lede": (f"מאגר התקנים הרשמיים של משרד הכלכלה והתעשייה: {n(total)} תקנים רשמיים בתוקף "
                 f"({n(editions)} מהדורות, כולל מהדורות במקביל בתקופת מעבר), מסלולי היבוא שלהם, "
                 f"{n(gz_total)} פרסומי תקינה ברשומות מאז {first_year} ו-{n(len(eu))} אסדרות אירופיות שאומצו. "
                 f"הפרסום האחרון ברשומות במאגר: {d_he(gz_ref)}."),
        "total_kpi": "תקנים רשמיים בתוקף",
        "adopted_kpi": "מאומצים מתקינה בין-לאומית או זרה",
        "eu_kpi": "במסלול ההתאמה לאסדרה האירופית",
        "cassis_kpi": "תקנים במסלול קסיס (תקינה בין-לאומית)",
        "revising_kpi": f"תקנים בתהליך עדכון ({pct(revising / total) if total else '0%'})",
        "transition_kpi": "מהדורות עם תאריך סיום תוקף",
        "gazette_kpi": (f"פרסומים ברשומות ב-{gz_last_full}"
                        + (f" (חציון חמש השנים הקודמות: {gz_med:g})" if gz_med is not None else "")),
        "eu_regs_kpi": "אסדרות אירופיות שאומצו",
        "orig_note": (f"אופן אימוץ המהדורה העדכנית של כל תקן. {n(int(is_orig.sum()))} תקנים מקוריים (ישראליים), "
                      f"השאר מאומצים מתקן בין-לאומי או זר — עם שינויים או בלעדיהם. "
                      f"{n(int((std['mand'] == 'כן').sum()))} תקנים מסומנים במאגר כ\"תקן מחייב\"."),
        "orig_aria": f"תרשים עמודות: {n(total)} תקנים רשמיים לפי אופן האימוץ. הנפוץ: {orig_vc.index[0]} ({n(orig_vc.iloc[0])}).",
        "orig_caption": "מספר תקנים רשמיים לפי אופן האימוץ.",
        "editions_note": (f"התקנים בתוקף לפי שנת המהדורה העדכנית, בקבוצות של חמש שנים, מקוריים מול מאומצים."
                          + (f" {n(no_year)} תקנים ללא שנת מהדורה אינם נכללים." if no_year else "")),
        "editions_aria": f"גרף עמודות מוערמות: תקנים בתוקף לפי שנת המהדורה, {lo} עד {ref_year}, מקוריים ומאומצים.",
        "editions_caption": "מספר תקנים בתוקף לפי תקופת המהדורה, מקוריים ומאומצים.",
        "topics_note": (f"הנושא הוא שם התקן עד הנקודתיים — תקן רב-חלקי נספר לפי מספר חלקיו בתוקף. "
                        f"{n(len(multi))} נושאים כוללים יותר מחלק אחד; {TOP_TOPICS} הנושאים המוצגים "
                        f"מכסים {n(t_cover)} מתוך {n(total)} התקנים."),
        "topics_aria": f"תרשים עמודות: {TOP_TOPICS} הנושאים עם מספר התקנים הרשמיים הרב ביותר. בראש: {topics.index[0]} ({n(topics.iloc[0])}).",
        "topics_caption": "מספר תקנים רשמיים בתוקף לפי נושא.",
        "routes_note": (f"שני מסלולי יבוא לצד עמידה בתקן הישראלי: התאמה לאסדרה האירופית שאומצה, "
                        f"ואישור לפי תקינה בין-לאומית (קסיס). {n(rc[0])} תקנים כלולים בשניהם."),
        "routes_aria": f"תרשים עמודות: תקנים לפי מסלולי היבוא. בשני המסלולים {n(rc[0])}, באף מסלול {n(rc[3])}.",
        "routes_caption": "מספר תקנים לפי מסלולי היבוא החלופיים.",
        "groups_note": (f"קבוצת היבוא של התקן בצו היבוא החופשי. תקן יכול להשתייך ליותר מקבוצה אחת "
                        f"({n(multi_group)} תקנים); ל-{n(with_conds)} תקנים נקבעו תנאים לחלוקה לקבוצות."),
        "groups_aria": "תרשים עמודות: מספר תקנים בכל קבוצת יבוא (תקן יכול להופיע ביותר מקבוצה אחת).",
        "groups_caption": "מספר תקנים לפי קבוצת יבוא.",
        "cassis_note": (f"{n(rt_total)} מסלולי אישור ל-{n(rt_std)} תקנים (ל-{n(rt_multi)} מהם יותר ממסלול אחד), "
                        f"לפי סוג המסמך הזר שעל פיו מאושר היבוא."),
        "cassis_aria": f"תרשים עמודות: {n(rt_total)} מסלולי תקינה בין-לאומית לפי סוג המסמך. הנפוץ: {r_names[0] if r_names else ''}.",
        "cassis_caption": "מספר מסלולי אישור לפי סוג המסמך הזר.",
        "bodies_note": (f"גופי התקינה שמסמכיהם נדרשים בצירוף המסמכים של כל מסלול (מסלול יכול לדרוש מסמכים מכמה גופים). "
                        f"{n(rt_conds)} מסלולים כוללים תנאי תחולה, {n(rt_extra)} דורשים מסמכים נוספים למוצרים מסוימים, "
                        f"ו-{n(rt_exempt)} מסומנים כפטורים מבדיקת יבוא."),
        "bodies_aria": "תרשים עמודות: מספר מסלולי האישור המפנים למסמכי כל גוף תקינה.",
        "bodies_caption": "מספר מסלולי אישור לפי גוף התקינה המוזכר.",
        "process_note": (f"{n(total - revising)} תקנים אינם בתהליך. תקן יכול להיות ביותר מתהליך אחד. "
                         f"{n(partial_sections)} תקנים רשמיים רק בחלק מסעיפיהם."),
        "process_aria": f"תרשים עמודות: {n(revising)} תקנים בתהליך עדכון לפי סוג התהליך.",
        "process_caption": "מספר תקנים לפי תהליך העדכון שבו הם נמצאים.",
        "amend_note": f"מספר גיליונות התיקון שפורסמו למהדורה העדכנית של כל תקן; המרבי — {n(am_max)}.",
        "amend_aria": f"תרשים עמודות: תקנים לפי מספר גיליונות התיקון. {n(am_vals[0])} תקנים ללא גיליון תיקון.",
        "amend_caption": "מספר תקנים לפי מספר גיליונות התיקון.",
        "transition_caption": "מהדורות תקן עם תאריך סיום תוקף, והמהדורה שמחליפה אותן במאגר.",
        "transition_note": (f"{n(len(trans))} מהדורות רשומות עם תאריך סיום תוקף (מוצגות עד עשרים, לפי התאריך)."
                            f" כשהמהדורה החדשה של אותו תקן כבר במאגר — היא מוצגת לצידה."),
        "gazette_note": (f"פרסומי התקינה ברשומות לפי שנה וסוג פעולה, מ-{start}.{early_txt}{partial_txt}"),
        "gazette_aria": f"גרף עמודות מוערמות: פרסומי תקינה ברשומות לפי שנה וסוג פעולה, {start} עד {gz_year}.",
        "actions_note": f"כל {n(gz_total)} הפרסומים לפי סוג הפעולה. לפי סוג הפרסום: {venue_txt}.",
        "actions_aria": f"תרשים עמודות: פרסומי תקינה ברשומות לפי סוג פעולה. הנפוץ: {actions_all.index[0]} ({n(actions_all.iloc[0])}).",
        "actions_caption": "מספר פרסומים ברשומות לפי סוג הפעולה.",
        "gaz_std_note": (f"מספר הפרסומים שבהם הוזכר כל תקן (לפי מספר וחלק). {n(no_std)} פרסומים אינם חלים על תקן ספציפי "
                         f"(חוקים, צווים וכללים)."),
        "gaz_std_aria": f"תרשים עמודות: {TOP_GAZ_STD} התקנים שהוזכרו במספר הפרסומים הרב ביותר ברשומות.",
        "gaz_std_caption": "התקנים שהוזכרו במספר הפרסומים הרב ביותר ברשומות.",
        "eu_note": (f"האסדרות האירופיות שאומצו, לפי שנת הכניסה לתוקף וסוג (דירקטיבה או רגולציה). "
                    f"ל-{n(eu_terms)} אסדרות נקבעו תנאים לתחולה, ול-{n(eu_comments)} הערות על מועדים שונים למוצרים מסוימים."),
        "eu_aria": f"גרף עמודות מוערמות: {n(len(eu))} אסדרות אירופיות לפי שנת הכניסה לתוקף.",
        "eu_caption": "מספר אסדרות אירופיות לפי שנת הכניסה לתוקף וסוג.",
        "reform_note": (f"קובץ נפרד במאגר — \"מאגר תקנים מעודכן לרפורמת מה שטוב לאירופה\" — כולל {n(len(rf_nums))} מספרי תקן"
                        + (f" (המהדורה המאוחרת בו מ-{rf_latest})" if rf_latest else "")
                        + f". השוואתו למאגר הנוכחי לפי מספר התקן."),
        "reform_aria": f"תרשים עמודות: {n(both_n)} תקנים בשתי הרשימות, {n(only_rf)} ברשימת הרפורמה בלבד, {n(only_cur)} במאגר הנוכחי בלבד.",
        "reform_caption": "השוואת רשימת הרפורמה למאגר הנוכחי לפי מספר תקן.",
    }

    return {
        "agent_data": {
            "summary_he": (f"התקנים הרשמיים בתוקף בישראל: {n(total)} תקנים, {pct(adopted_share)} מהם מאומצים "
                           f"מתקינה בין-לאומית, עם מסלולי היבוא, {n(gz_total)} פרסומי תקינה ברשומות "
                           f"ו-{n(len(eu))} אסדרות אירופיות שאומצו."),
            "dataset_kind": "registry",
            "suggested_tags": ["תקנים", "תקינה", "יבוא", "רגולציה", "מה שטוב לאירופה", "רשומות"],
            "related_ids": ["ed8ce28e-ae7f-4588-b3f9-59485960d521",
                            "12c7457c-a9f0-40f8-9ed6-b4689d3d3fa4",
                            "013bf5b9-c7ff-4282-b402-73ed20deeacc"],
            "temporal_coverage": f"{first_year}/{gz_ref.strftime('%Y-%m-%d')}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
    }
