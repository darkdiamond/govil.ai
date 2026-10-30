"""מערכת מידע פסולת: נספחים (רשימות אתרי טיפול, סוגי פסולת, רשויות).

The dataset is a set of small lookup tables that sites reporting to the
Ministry's waste information system use: nine site lists (one per facility
kind x waste stream, each `name, company number, site id`), the waste-type
code list, the local-authority code list, and a contact directory of mixed-
waste facilities by district.

Everything on the page is computed here. Operator company numbers are used
only to group facilities by operator and to classify the operator's legal
form by its number prefix; the numbers themselves never reach the page (a
sole trader's number is a personal ID).
"""
import pandas as pd

# Site lists: input name -> (facility kind, waste stream, column prefix).
SITE_LISTS = [
    ("landfill_build", "מטמנה", "פסולת בניין"),
    ("landfill_mixed", "מטמנה", "פסולת מעורבת"),
    ("recycle_build", "מפעל מחזור", "פסולת בניין"),
    ("recycle_mixed", "מפעל מחזור", "פסולת מעורבת"),
    ("organic", "מפעל מחזור", "פסולת אורגנית"),
    ("transfer_build", "תחנת מעבר", "פסולת בניין"),
    ("transfer_mixed", "תחנת מעבר", "פסולת מעורבת"),
    ("transfer_prune", "תחנת מעבר", "גזם"),
    ("energy", "השבת אנרגיה", "פסולת מעורבת"),
]
KIND_ORDER = ["מטמנה", "מפעל מחזור", "תחנת מעבר", "השבת אנרגיה"]
STREAM_ORDER = ["פסולת מעורבת", "פסולת בניין", "גזם", "פסולת אורגנית"]

# Legal form from the Israeli corporation-number prefix. Anything else
# (8-9 digits outside these ranges) is a personal ID: a sole trader.
FORM_BY_PREFIX = [
    ("50", "רשות מקומית או גוף ציבורי"),
    ("51", "חברה"),
    ("52", "חברה"),
    ("55", "שותפות"),
    ("54", "אגודה שיתופית או עמותה"),
    ("57", "אגודה שיתופית או עמותה"),
    ("58", "אגודה שיתופית או עמותה"),
]
FORM_SOLE = "עוסק יחיד"
FORM_ORDER = ["חברה", "רשות מקומית או גוף ציבורי", "שותפות",
              "אגודה שיתופית או עמותה", FORM_SOLE]

# Waste-type families by keyword; first match wins, unknown -> "אחר".
FAMILIES = [
    ("פיקדון", ["פקדון", "פיקדון"]),
    ("אסבסט וקרקע מזוהמת", ["אסבסט", "מזוהמת"]),
    ("פלסטיק", ["פלסטיק", "קלקר"]),
    ("זכוכית", ["זכוכית"]),
    ("מתכות", ["מתכ", "פחיות"]),
    ("נייר וקרטון", ["נייר", "קרטון", "קרטונ"]),
    ("שאריות ופסולת מעורבת", ["שאריות", "מעורבת", "טיאוט", "יבש", "RDF", "פסדים"]),
    ("אורגני, גזם וחקלאי", ["אורגני", "ביולוגית", "גזם", "קומפוסט", "זבל", "פגרים",
                             "פרי", "שמן", "שומני", "עץ"]),
    ("בנייה, עפר וחומרים ממוחזרים", ["בניה", "בנייה", "עפר", "מצע", "חול", "טיט",
                                      "בטון", "בטקל", "צמנט", "אגרגט", "מילוי", "מדה",
                                      "CLSM", "כיסוי", "תשתית", "גושית"]),
    ("מיוחדת ותעשייתית", ["רפואית", "אלקטרונית", "בוצה", "צמיגים", "תעשייתית",
                           "תשטיפים", "תסנין", "טקסטיל", "גניזה"]),
]
FAMILY_OTHER = "אחר"
FLAG_ORDER = ["פסולת (לא חומר)", "חומר או תוצר", "לא סווג"]

DISTRICT_ALIASES = {"ירושליים": "ירושלים"}


def _int(n):
    return f"{int(n):,}"


def _pct(x):
    return f"{x * 100:.1f}%"


def _digits(s):
    return "".join(ch for ch in str(s) if ch.isdigit())


def _col(df, key):
    """Column of a site list by role, whatever its spelling (space/underscore)."""
    for c in df.columns:
        norm = c.replace("_", " ").strip().lower()
        if norm.endswith(key):
            return c
    return None


def _site_rows(frames):
    """All site-list rows as one frame: list, kind, stream, name, corp, site.

    Some lists have the company-number and site-id columns swapped. The
    company number is the 8-9 digit one, so the roles are assigned per list
    by digit length rather than by header; `swapped` records which lists.
    """
    rows, swapped = [], []
    for name, kind, stream in SITE_LISTS:
        df = frames.get(name)
        if df is None:
            continue
        c_name, c_corp, c_id = _col(df, "name"), _col(df, "company"), _col(df, "id")
        if not (c_name and c_corp and c_id):
            continue
        a = df[c_corp].map(_digits)
        b = df[c_id].map(_digits)
        long_a = int((a.str.len() >= 8).sum())
        long_b = int((b.str.len() >= 8).sum())
        if long_b > long_a:
            a, b = b, a
            swapped.append(name)
        for nm, corp, site in zip(df[c_name], a, b):
            nm = " ".join(str(nm).split())
            if not nm:
                continue
            rows.append({"list": name, "kind": kind, "stream": stream,
                         "name": nm, "corp": corp, "site": site})
    out = pd.DataFrame(rows, columns=["list", "kind", "stream", "name", "corp", "site"])
    return out, swapped


def _list_label(name):
    for n, kind, stream in SITE_LISTS:
        if n == name:
            if kind == "השבת אנרגיה":
                return "השבת אנרגיה"
            return f"{kind}: {stream}"
    return name


def _form(corp):
    if len(corp) < 8:
        return None
    c = corp.zfill(9)
    for p, label in FORM_BY_PREFIX:
        if c.startswith(p):
            return label
    return FORM_SOLE


def _family(name):
    for fam, keys in FAMILIES:
        for k in keys:
            if k in name:
                return fam
    return FAMILY_OTHER


def _flag(v):
    v = str(v).strip()
    if v == "כן":
        return "חומר או תוצר"
    if v == "לא":
        return "פסולת (לא חומר)"
    return "לא סווג"


# ---------------------------------------------------------------- insights

def ins_largest_list(by_list, total):
    if by_list.empty or total == 0:
        return None
    lst, n = by_list.index[0], int(by_list.iloc[0])
    share = n / total
    if share < 0.15 or (len(by_list) > 1 and int(by_list.iloc[1]) == n):
        return None
    return (f"הרשימה הגדולה היא {_list_label(lst)} עם {_int(n)} אתרים, "
            f"{_pct(share)} מכל {_int(total)} הרישומים ברשימות האתרים.")


def ins_top_operator(ops):
    if ops.empty:
        return None
    top = ops.iloc[0]
    if top["entries"] < 3 or (len(ops) > 1 and ops.iloc[1]["entries"] == top["entries"]):
        return None
    return (f"המפעיל עם הכי הרבה רישומים (לפי מספר תאגיד) מופיע {_int(top['entries'])} פעמים "
            f"ב-{_int(top['lists'])} רשימות שונות, ובהם האתר {top['label']}.")



def ins_forms(form_counts, n_ops):
    if n_ops == 0 or form_counts.empty:
        return None
    lead, n = form_counts.index[0], int(form_counts.iloc[0])
    share = n / n_ops
    if share < 0.5:
        return None
    rest = [f"{k}: {_int(v)}" for k, v in form_counts.iloc[1:].items() if v > 0]
    tail = f" ({', '.join(rest)})" if rest else ""
    if not rest:
        return f"כל המפעילים רשומים כ{lead}, לפי קידומת מספר התאגיד."
    return (f"{_pct(share)} מהמפעילים רשומים כ{lead}, לפי קידומת מספר התאגיד; "
            f"השאר{tail}.")



def ins_swapped(swapped, sizes):
    if not swapped:
        return None
    names = ", ".join(_list_label(s) for s in swapped)
    n = sum(sizes.get(s, 0) for s in swapped)
    return (f"ברשימת {names} ({_int(n)} אתרים) עמודות מספר החברה ומזהה האתר "
            f"מוחלפות; בעמוד זה הן זוהו לפי אורך המספר.")



def ins_unflagged(types):
    if types.empty:
        return None
    unf = types[types["flag"] == "לא סווג"]
    if unf.empty:
        return None
    flagged = types[types["flag"] != "לא סווג"]
    n = len(unf)
    base = f"{_int(n)} סוגי פסולת ({_pct(n / len(types))}) לא סווגו כחומר או כפסולת"
    ids_u = unf["id"].dropna()
    ids_f = flagged["id"].dropna()
    if not ids_u.empty and not ids_f.empty and ids_u.min() > ids_f.max():
        base += f"; כולם בעלי הקודים החדשים ביותר ({_int(ids_u.min())} ומעלה)"
    fam = unf["family"].value_counts().sort_index().sort_values(ascending=False, kind="stable")
    if len(unf) >= 3 and int(fam.iloc[0]) / len(unf) >= 0.5:
        base += f", רובם ({_int(fam.iloc[0])}) במשפחת {fam.index[0]}"
    return base + "."


def ins_materials(types):
    mat = int((types["flag"] == "חומר או תוצר").sum())
    if mat < 2:
        return None
    sub = types[types["flag"] == "חומר או תוצר"]
    fam = sub["family"].value_counts().sort_index().sort_values(ascending=False, kind="stable")
    lead, n = fam.index[0], int(fam.iloc[0])
    if n / mat < 0.4:
        return f"{_int(mat)} קודים מסומנים כחומר או תוצר (לא כפסולת)."
    part = "כולם" if n == mat else f"{_int(n)} מהם"
    return (f"{_int(mat)} קודים מסומנים כחומר או תוצר ולא כפסולת, "
            f"{part} במשפחת {lead}: התוצרים שמפעלי המחזור מוציאים.")


def ins_directory(dir_df):
    if dir_df.empty:
        return None
    named = dir_df.loc[dir_df["district"] != "לא צוין", "district"]
    if named.empty:
        return None
    by_d = named.value_counts().sort_index().sort_values(ascending=False, kind="stable")
    by_t = dir_df["type"].value_counts().sort_index().sort_values(ascending=False, kind="stable")
    d, dn = by_d.index[0], int(by_d.iloc[0])
    t, tn = by_t.index[0], int(by_t.iloc[0])
    if len(by_d) > 1 and int(by_d.iloc[1]) == dn:
        lead = f"מחוזות {d} ו{by_d.index[1]} מובילים עם {_int(dn)} אתרים כל אחד"
    else:
        lead = f"מחוז {d} מוביל עם {_int(dn)} אתרים"
    n_closed = int(dir_df["closed"].sum())
    tail = f" {_int(n_closed)} אתרים במדריך מסומנים כסגורים." if n_closed else ""
    return (f"במדריך אתרי הפסולת המעורבת {_int(len(dir_df))} אתרים; {lead}, "
            f"והסוג הנפוץ הוא {t} ({_int(tn)}).{tail}")



def ins_contacts(dir_df):
    n = len(dir_df)
    if n == 0:
        return None
    no_phone = int((~dir_df["has_phone"]).sum())
    no_any = int((~dir_df["has_phone"] & ~dir_df["has_email"]).sum())
    if no_phone / n < 0.1:
        return None
    return (f"ל-{_int(no_phone)} אתרים במדריך ({_pct(no_phone / n)}) אין מספר טלפון, "
            f"ול-{_int(no_any)} מהם אין גם כתובת דוא״ל.")


# ---------------------------------------------------------------- compute

def compute(frames):
    sites, swapped = _site_rows(frames)

    # ---- site lists: kind x stream
    by_list = (sites.groupby("list").size().sort_index()
               .sort_values(ascending=False, kind="stable"))
    total_entries = int(len(sites))
    kinds = [k for k in KIND_ORDER if k in set(sites["kind"])]
    streams = [s for s in STREAM_ORDER if s in set(sites["stream"])]
    lists_series = []
    for s in streams:
        lists_series.append({
            "name": s,
            "data": [int(((sites["kind"] == k) & (sites["stream"] == s)).sum()) for k in kinds],
        })
    lists_table = []
    for name, kind, stream in SITE_LISTS:
        n = int(by_list.get(name, 0))
        lists_table.append({"kind": kind, "stream": stream, "count": _int(n)})

    # ---- operators (grouped by company number; numbers never shown)
    ops_src = sites[sites["corp"].str.len() >= 8].copy()
    op_rows = []
    for corp, g in ops_src.groupby("corp", sort=True):
        names = sorted(set(g["name"]))
        label = sorted(names, key=lambda x: (len(x), x))[0]
        op_rows.append({
            "corp": corp,
            "entries": int(len(g)),
            "lists": int(g["list"].nunique()),
            "label": label,
            "names": names,
            "form": _form(corp),
        })
    ops = pd.DataFrame(op_rows, columns=["corp", "entries", "lists", "label", "names", "form"])
    if not ops.empty:
        ops = ops.sort_values(["entries", "lists", "label", "corp"],
                              ascending=[False, False, True, True], kind="stable").reset_index(drop=True)
    n_ops = int(len(ops))
    multi = ops[ops["entries"] >= 2] if n_ops else ops
    n_multi = int(len(multi))
    top_ops = multi.head(10)
    ops_chart = {
        "names": [r["label"] if len(r["label"]) <= 28 else r["label"][:27] + "…"
                  for _, r in top_ops.iterrows()][::-1],
        "values": [int(v) for v in top_ops["entries"]][::-1],
        "lists": [int(v) for v in top_ops["lists"]][::-1],
    }
    ops_table = [{"label": r["label"], "entries": _int(r["entries"]), "lists": _int(r["lists"]),
                  "names": "; ".join(r["names"])} for _, r in top_ops.iterrows()]

    # ---- legal form
    if n_ops:
        fc = ops["form"].value_counts()
    else:
        fc = pd.Series(dtype=int)
    forms = [(f, int(fc.get(f, 0))) for f in FORM_ORDER if int(fc.get(f, 0)) > 0]
    forms.sort(key=lambda x: (-x[1], FORM_ORDER.index(x[0])))
    form_counts = pd.Series({k: v for k, v in forms}, dtype=int)
    forms_chart = [{"name": k, "value": v} for k, v in forms]
    forms_table = [{"name": k, "count": _int(v), "share": _pct(v / n_ops) if n_ops else "0.0%"}
                   for k, v in forms]

    # ---- shared sites between lists
    site_valid = sites[sites["site"].str.len() >= 3]
    site_lists = site_valid.groupby("site")["list"].apply(lambda s: sorted(set(s)))
    n_sites = int(len(site_lists))
    shared = site_lists[site_lists.map(len) >= 2]
    n_shared = int(len(shared))
    list_names = [n for n, _, _ in SITE_LISTS if n in set(sites["list"])]
    idx = {n: i for i, n in enumerate(list_names)}
    pair_counts = {}
    for lsts in shared:
        for i in range(len(lsts)):
            for j in range(i + 1, len(lsts)):
                a, b = sorted([lsts[i], lsts[j]], key=lambda x: idx[x])
                pair_counts[(a, b)] = pair_counts.get((a, b), 0) + 1
    pairs_sorted = sorted(pair_counts.items(), key=lambda kv: (-kv[1], idx[kv[0][0]], idx[kv[0][1]]))
    overlap_table = [{"a": _list_label(a), "b": _list_label(b), "count": _int(v)}
                     for (a, b), v in pairs_sorted[:20]]
    top_pairs = pairs_sorted[:10]
    overlap_chart = {
        "names": [f"{_list_label(a)} + {_list_label(b)}" for (a, b), _ in top_pairs][::-1],
        "values": [int(v) for _, v in top_pairs][::-1],
    }

    # ---- waste types
    t = frames["types"].copy()
    t["name"] = t["שם"].map(lambda x: " ".join(str(x).split()))
    t = t[t["name"] != ""].copy()
    t["id"] = pd.to_numeric(t["מזהה"].map(_digits).replace("", None), errors="coerce")
    t["flag"] = t["האם חומר?"].map(_flag)
    t["family"] = t["name"].map(_family)
    n_types = int(len(t))
    fam_tbl = (t.groupby("family").size().rename("n").reset_index()
               .sort_values(["n", "family"], ascending=[False, True], kind="stable"))
    fam_order = list(fam_tbl["family"])
    flags_present = [f for f in FLAG_ORDER if f in set(t["flag"])]
    types_series = [{"name": f, "data": [int(((t["family"] == fam) & (t["flag"] == f)).sum())
                                          for fam in fam_order[::-1]]} for f in flags_present]
    types_table = []
    for fam in fam_order:
        row = {"family": fam, "vals": [_int(((t["family"] == fam) & (t["flag"] == f)).sum())
                                         for f in flags_present],
               "total": _int((t["family"] == fam).sum())}
        types_table.append(row)
    n_material = int((t["flag"] == "חומר או תוצר").sum())
    n_unflagged = int((t["flag"] == "לא סווג").sum())

    # ---- local authorities
    au = frames["authorities"]
    n_auth = int((au["Authority"].map(lambda x: str(x).strip()) != "").sum())

    # ---- directory of mixed-waste facilities
    d = frames["directory"].copy()
    d["site_name"] = d["שם האתר"].map(lambda x: " ".join(str(x).split()))
    d = d[d["site_name"] != ""].copy()
    d["district"] = d["מחוז"].map(lambda x: " ".join(str(x).split())).map(
        lambda x: DISTRICT_ALIASES.get(x, x) or "לא צוין")
    d["type"] = d["סוג מתקן"].map(lambda x: " ".join(str(x).split()) or "לא צוין")
    d["loc"] = d["מיקום"].map(lambda x: " ".join(str(x).split()))
    d["closed"] = d["רשות מקומית"].map(lambda x: "סגור" in str(x))
    d["has_phone"] = d["פרטי קשר - טלפון"].map(lambda x: len(_digits(x)) >= 7)
    d["has_email"] = d["כתובת מייל"].map(lambda x: "@" in str(x))
    d["has_owner"] = d["בעל האתר"].map(lambda x: str(x).strip() != "")
    n_dir = int(len(d))
    n_closed = int(d["closed"].sum())

    dist_tot = d["district"].value_counts().sort_index().sort_values(ascending=False, kind="stable")
    dist_order = list(dist_tot.index)
    type_tot = d["type"].value_counts().sort_index().sort_values(ascending=False, kind="stable")
    type_order = list(type_tot.index)
    dir_series = [{"name": ty, "data": [int(((d["district"] == di) & (d["type"] == ty)).sum())
                                         for di in dist_order]} for ty in type_order]
    dir_table = [{"name": di, "vals": [_int(((d["district"] == di) & (d["type"] == ty)).sum())
                                        for ty in type_order],
                  "total": _int(dist_tot[di])} for di in dist_order]

    contact_rows = []
    for ty in type_order:
        g = d[d["type"] == ty]
        n = len(g)
        contact_rows.append({
            "type": ty, "n": n,
            "phone": round(100 * g["has_phone"].mean(), 1) if n else 0.0,
            "email": round(100 * g["has_email"].mean(), 1) if n else 0.0,
            "owner": round(100 * g["has_owner"].mean(), 1) if n else 0.0,
        })
    contact_chart = {
        "types": [r["type"] for r in contact_rows],
        "phone": [r["phone"] for r in contact_rows],
        "email": [r["email"] for r in contact_rows],
        "owner": [r["owner"] for r in contact_rows],
    }
    contact_table = [{"type": r["type"], "n": _int(r["n"]), "phone": f"{r['phone']:.1f}%",
                      "email": f"{r['email']:.1f}%", "owner": f"{r['owner']:.1f}%"}
                     for r in contact_rows]

    loc_cnt = d[d["loc"] != ""]["loc"].value_counts().sort_index().sort_values(
        ascending=False, kind="stable")
    hubs = loc_cnt[loc_cnt >= 2].head(12)
    hubs_chart = {"names": list(hubs.index)[::-1], "values": [int(v) for v in hubs.values][::-1]}
    hubs_table = []
    for loc, v in hubs.items():
        tys = sorted(set(d[d["loc"] == loc]["type"]))
        hubs_table.append({"loc": loc, "count": _int(v), "types": ", ".join(tys)})

    # ---- insights
    sizes = {k: int(v) for k, v in by_list.items()}
    rules = [
        ("largest_list", ins_largest_list(by_list, total_entries)),
        ("top_operator", ins_top_operator(ops) if n_ops else None),
        ("forms", ins_forms(form_counts, n_ops)),
        ("materials", ins_materials(t)),
        ("unflagged", ins_unflagged(t)),
        ("directory", ins_directory(d)),
        ("contacts", ins_contacts(d)),
        ("swapped", ins_swapped(swapped, sizes)),
    ]
    insights = [{"id": i, "text_he": s} for i, s in rules if s]

    # ---- KPIs
    kpis = {
        "entries": {"value": total_entries, "display": _int(total_entries), "tone": "brand"},
        "operators": {"value": n_ops, "display": _int(n_ops), "tone": "brand"},
        "types": {"value": n_types, "display": _int(n_types), "tone": "brand"},
        "authorities": {"value": n_auth, "display": _int(n_auth), "tone": "brand"},
        "directory": {"value": n_dir, "display": _int(n_dir), "tone": "info"},
        "closed": {"value": n_closed, "display": _int(n_closed),
                   "tone": "warn" if n_closed > 0 else "ok"},
    }

    # ---- labels / ledes
    top_list = by_list.index[0] if len(by_list) else None
    lbl = {}
    lbl["lede"] = (
        f"נספחי המדריך לחיבור למערכת מידע פסולת של המשרד להגנת הסביבה: "
        f"{_int(len(by_list))} רשימות אתרי טיפול ({_int(total_entries)} רישומים של מטמנות, "
        f"מפעלי מחזור, תחנות מעבר ומפעל השבת אנרגיה), {_int(n_types)} קודי סוגי פסולת, "
        f"{_int(n_auth)} קודי רשויות מקומיות ומדריך פרטי קשר של {_int(n_dir)} אתרי טיפול "
        f"בפסולת מעורבת. הרשימות משמשות את אתרי הפסולת בדיווח השקילות למערכת, "
        f"ואינן רשימה רשמית ומלאה של אתרי הפסולת בישראל.")
    lbl["entries_kpi"] = "רישומים ברשימות האתרים"
    lbl["operators_kpi"] = "מפעילים שונים (לפי מספר תאגיד)"
    lbl["types_kpi"] = "קודי סוגי פסולת"
    lbl["auth_kpi"] = "קודי רשויות מקומיות"
    lbl["dir_kpi"] = "אתרים במדריך הקשר"
    lbl["closed_kpi"] = "אתרים סגורים במדריך"
    lbl["lists_note"] = (
        f"מספר האתרים בכל אחת מ-{_int(len(by_list))} רשימות האתרים, לפי סוג המתקן וזרם הפסולת."
        + (f" הרשימה הגדולה: {_list_label(top_list)} ({_int(by_list.iloc[0])})." if top_list else ""))
    lbl["lists_aria"] = (f"גרף עמודות מוערמות: {_int(total_entries)} רישומי אתרים לפי סוג מתקן וזרם פסולת"
                         + (f"; הרשימה הגדולה {_list_label(top_list)} עם {_int(by_list.iloc[0])} אתרים."
                            if top_list else "."))
    if len(top_ops):
        lbl["ops_note"] = (
            f"{_int(n_multi)} מפעילים רשומים יותר מפעם אחת. המפעילים קובצו לפי מספר התאגיד, "
            f"וכל עמודה נקראת על שם האתר הקצר ביותר שלהם; כל שמות האתרים בטבלה.")
        lbl["ops_aria"] = (f"גרף עמודות אופקי: {_int(len(top_ops))} המפעילים עם הכי הרבה רישומים; "
                           f"המוביל {top_ops.iloc[0]['label']} עם {_int(top_ops.iloc[0]['entries'])} רישומים.")
    else:
        lbl["ops_note"] = ""
        lbl["ops_aria"] = ""
    lbl["forms_note"] = (f"צורת ההתאגדות של {_int(n_ops)} המפעילים, לפי קידומת מספר התאגיד "
                         f"(חברה, רשות, שותפות, אגודה או עמותה; מספר שאינו בטווחים אלה הוא של עוסק יחיד).")
    lbl["forms_aria"] = ("גרף טבעת: צורת ההתאגדות של המפעילים"
                         + (f"; הנפוצה {forms[0][0]} עם {_int(forms[0][1])}." if forms else "."))
    lbl["overlap_note"] = (
        f"{_int(n_shared)} מתוך {_int(n_sites)} האתרים (לפי מזהה אתר) מופיעים ביותר מרשימה אחת. "
        f"כל עמודה מראה כמה אתרים משותפים לזוג רשימות"
        + (f" ({_int(len(top_pairs))} הזוגות הגדולים)." if len(pairs_sorted) > len(top_pairs) else "."))
    lbl["overlap_aria"] = ("גרף עמודות אופקי: אתרים המשותפים לזוגות של רשימות"
                           + (f"; הזוג הגדול {overlap_chart['names'][-1]} עם {_int(overlap_chart['values'][-1])} אתרים."
                              if top_pairs else "."))
    fam_lead = fam_order[0] if fam_order else ""
    lbl["types_note"] = (
        f"{_int(n_types)} קודי סוגי הפסולת שבהם מדווחים, מקובצים למשפחות לפי שם הסוג. "
        f"{_int(n_material)} מסומנים כחומר או תוצר, {_int(n_unflagged)} עדיין לא סווגו.")
    lbl["types_aria"] = (f"גרף עמודות מוערמות: {_int(n_types)} סוגי פסולת לפי משפחה וסיווג חומר; "
                         f"המשפחה הגדולה {fam_lead}.")
    lbl["dir_note"] = (f"{_int(n_dir)} אתרי טיפול בפסולת מעורבת במדריך פרטי הקשר, לפי מחוז וסוג מתקן"
                       + (f"; {_int(n_closed)} מהם מסומנים כסגורים." if n_closed else "."))
    lbl["dir_aria"] = (f"גרף עמודות מוערמות: {_int(n_dir)} אתרים במדריך לפי מחוז וסוג מתקן"
                       + (f"; המחוז המוביל {dist_order[0]} עם {_int(dist_tot.iloc[0])}." if dist_order else "."))
    lbl["contact_note"] = ("שיעור האתרים במדריך שיש להם מספר טלפון, כתובת דוא״ל ושם בעל אתר, לפי סוג מתקן. "
                           "הפרטים עצמם זמינים בטבלת הנתונים בתחתית העמוד.")
    lbl["contact_aria"] = "גרף עמודות: שלמות פרטי הקשר במדריך לפי סוג מתקן, באחוזים."
    lbl["hubs_note"] = (f"יישובים ואזורים שבהם רשומים שני אתרים או יותר במדריך ({_int(len(hubs))} מקומות).")
    lbl["hubs_aria"] = ("גרף עמודות אופקי: מקומות עם כמה אתרי טיפול"
                        + (f"; המוביל {hubs.index[0]} עם {_int(hubs.iloc[0])} אתרים." if len(hubs) else "."))

    summary = (f"איתור אתר טיפול בפסולת, קוד סוג פסולת או קוד רשות לדיווח למערכת מידע פסולת: "
               f"{_int(total_entries)} רישומי אתרים ו-{_int(n_types)} סוגי פסולת.")

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "registry",
            "suggested_tags": ["פסולת", "אתרי טיפול בפסולת", "מחזור", "מטמנות",
                               "תחנות מעבר", "רשויות מקומיות"],
            "related_ids": [
                "892135f3-cf6b-400a-8876-bfc80f3c9143",
                "7f1a7496-c3d9-498f-ade2-2ebb8e602916",
                "04931a88-336c-4d95-8a13-9dc631c3e2d1",
                "0628822c-1640-4212-a357-d71b8fb68023",
            ],
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": {
            "lists": {"kinds": kinds, "series": lists_series},
            "operators": ops_chart,
            "forms": forms_chart,
            "overlap": overlap_chart,
            "types": {"families": fam_order[::-1], "series": types_series},
            "directory": {"districts": dist_order, "series": dir_series},
            "contact": contact_chart,
            "hubs": hubs_chart,
        },
        "tables": {
            "lists": lists_table,
            "operators": ops_table,
            "forms": forms_table,
            "overlap": overlap_table,
            "types": types_table,
            "flag_cols": flags_present,
            "directory": dir_table,
            "dir_cols": type_order,
            "contact": contact_table,
            "hubs": hubs_table,
        },
        "flags": {
            "has_ops": bool(len(top_ops)),
            "has_overlap": bool(pair_counts),
            "has_hubs": bool(len(hubs)),
            "has_dir": n_dir > 0,
        },
        "insights": insights,
        "labels": lbl,
    }
