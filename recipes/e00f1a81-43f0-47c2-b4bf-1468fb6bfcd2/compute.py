"""בתים מאזנים למניעת אשפוז פסיכיאטרי: the Ministry of Health's list of
supervised "balancing houses" (one row per house: name, city, district,
type, operator, HMO agreements, facility phone/email, free-text notes).

Searchers want to find a house near them, who runs it, which HMO funds it and
how to contact it, so the page leads with a by-district directory and the
lookup callout. Everything is institutional (facility name, operator, the
facility's published phone/email); no patient data exists in the file.

Growth: a small registry edited in place. New districts, types, payers and
operators flow through (codes only order known values; unknowns sort after).
Operators are capped at top-N + "אחר". The directory is plain HTML (no
script), so it stays well under the per-script cap at any realistic size.
"""
import re

import pandas as pd

NO_AGREEMENT_MARK = "אין"
MOD = "משרד הביטחון"
FOUR_HMOS = ("כללית", "מכבי", "מאוחדת", "לאומית")
TOP_OPERATORS = 10
SUMMARY_MAX = 155

PALETTE = ["#0068f5", "#0b3668", "#0dcaf0", "#ffc107", "#198754", "#6c757d",
           "#dc3545", "#7aa7e8"]

_TAG_RE = re.compile(r"<[^>]+>")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def _clean(s):
    return re.sub(r"\s+", " ", str(s)).strip()


def _n(n, one, many):
    return one if n == 1 else f"{n:,} {many}"


def _pre(prefix, n, one, many):
    """Prefix letter + count: 'ביישוב אחד' / 'ב-27 יישובים'."""
    return f"{prefix}{one}" if n == 1 else f"{prefix}-{n:,} {many}"


def _houses(n):
    return _n(n, "בית אחד", "בתים")


def _pct(part, whole):
    return f"{(part / whole * 100):.1f}%" if whole else "0.0%"


def _join(names):
    names = list(names)
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " ו" + names[-1]


def _phones(raw):
    text = _TAG_RE.sub(" ", str(raw))
    out = []
    for part in re.split(r"[,;/\n]", text):
        disp = _clean(part)
        if not disp:
            continue
        digits = re.sub(r"[^\d*]", "", disp)
        if len(digits.replace("*", "")) < 3:
            continue
        if digits.endswith("*") and not digits.startswith("*"):
            digits = "*" + digits.rstrip("*")
        if digits not in [p["tel"] for p in out]:
            disp_clean = re.sub(r"[^\d*\-+ ]", "", disp).strip()
            if disp_clean.endswith("*"):
                disp_clean = "*" + disp_clean.rstrip("*").strip()
            out.append({"tel": digits, "display": disp_clean or digits})
    return out


def _emails(raw):
    text = _TAG_RE.sub(" ", str(raw))
    out = []
    for m in _EMAIL_RE.finditer(text):
        e = m.group(0).strip(".")
        if e.lower() not in [x.lower() for x in out]:
            out.append(e)
    return out


def _payers(raw):
    s = _clean(raw)
    if not s:
        return [], False
    if s.startswith(NO_AGREEMENT_MARK):
        return [], True
    parts = [_clean(p) for p in s.split(",")]
    return sorted({p for p in parts if p}, key=_payer_rank), False


def _payer_rank(name):
    """HMOs in their usual order, then the MoD, then anything new by name."""
    if name in FOUR_HMOS:
        return (FOUR_HMOS.index(name), name)
    return (len(FOUR_HMOS) if name == MOD else 99, name)


def _gender(comment):
    c = comment
    has_w = "נשים" in c
    has_m = "גברים" in c
    if "מעורב" in c or (has_w and has_m):
        return "mixed"
    if has_w:
        return "women"
    if has_m:
        return "men"
    return "unknown"


GENDER_LABELS = {"mixed": "נשים וגברים", "women": "נשים בלבד",
                 "men": "גברים בלבד", "unknown": "לא צוין בהערות"}
GENDER_ORDER = ["mixed", "women", "men", "unknown"]

AUDIENCES = [
    ("trauma", "טראומה ופוסט טראומה", ("טראומה", "PTSD")),
    ("religious", "מותאם לקהל דתי או חרדי", ("דתי", "חרדי")),
    ("arabic", "לדוברי ערבית", ("ערבית",)),
]


def _code(v):
    x = pd.to_numeric(str(v).strip(), errors="coerce")
    return float(x) if pd.notna(x) else 1e9


def _prepare(df):
    d = pd.DataFrame({
        "title": df["title"].map(_clean),
        "city": df["city"].map(_clean),
        "district": df["district_name"].map(_clean),
        "district_code": df["district"].map(_code),
        "type": df["type_name"].map(_clean),
        "type_code": df["type"].map(_code),
        "operator": df["operator"].map(_clean),
        "comments": df["comments"].map(_clean),
        "kupa_raw": df["kupa"].map(_clean),
        "phone_raw": df["phone"],
        "email_raw": df["email"],
    })
    d = d[d["title"] != ""].copy()
    d.loc[d["district"] == "", "district"] = "לא צוין"
    d.loc[d["type"] == "", "type"] = "לא צוין"
    d.loc[d["city"] == "", "city"] = "לא צוין"
    d.loc[d["operator"] == "", "operator"] = "לא צוין"
    pay = d["kupa_raw"].map(_payers)
    d["payers"] = pay.map(lambda t: t[0])
    d["no_agreement"] = pay.map(lambda t: t[1])
    d["gender"] = d["comments"].map(_gender)
    d = d.sort_values(["district_code", "district", "city", "title", "operator"],
                      kind="stable").reset_index(drop=True)
    return d


def _ordered(d, name_col, code_col):
    g = (d.groupby(name_col).agg(n=("title", "size"), code=(code_col, "min"))
         .reset_index().sort_values(["code", name_col], kind="stable"))
    return list(g[name_col])


def _counts(series):
    vc = series.value_counts()
    items = sorted(vc.items(), key=lambda kv: (-kv[1], kv[0]))
    return [(k, int(v)) for k, v in items]


# ------------------------------------------------------------------ insights

def ins_district(d, total):
    c = _counts(d["district"])
    if len(c) < 2:
        return None
    (top, n1), (second, n2) = c[0], c[1]
    if n1 == n2:
        tied = [k for k, v in c if v == n1]
        return (f"המחוזות {_join(tied)} מובילים יחד, עם {_houses(n1)} כל אחד "
                f"מתוך {total:,} בתים מאזנים ברשימה.")
    last, nl = c[-1]
    s = (f"מחוז {top} מוביל עם {_houses(n1)} ({_pct(n1, total)} מהרשימה), "
         f"ואחריו מחוז {second} עם {_houses(n2)}")
    if len(c) > 2 and nl < n2:
        lows = [k for k, v in c if v == nl]
        if len(lows) == 1:
            s += f"; במחוז {last} יש {_houses(nl)} בלבד"
        else:
            s += f"; במחוזות {_join(lows)} יש {_houses(nl)} בלבד בכל אחד"
    return s + "."


def ins_no_agreement(d, total):
    n = int(d["no_agreement"].sum())
    if n == 0:
        return None
    mod_only = int(d["payers"].map(lambda p: p == [MOD]).sum())
    s = (f"ל{_houses(n) if n == 1 else f'-{n:,} בתים'} ({_pct(n, total)}) "
         f"אין עדיין הסכם עם קופות החולים")
    if mod_only:
        s += (f", ו{'בית אחד נוסף עובד' if mod_only == 1 else f'-{mod_only:,} בתים נוספים עובדים'} "
              f"רק מול משרד הביטחון")
    return s + ": כדאי לברר מול הבית את מסלול המימון לפני פנייה."


def ins_hmos(d, total):
    four = [h for h in FOUR_HMOS]
    counts = {h: int(d["payers"].map(lambda p, h=h: h in p).sum()) for h in four}
    if not any(counts.values()):
        return None
    best = sorted(counts.items(), key=lambda kv: (-kv[1], four.index(kv[0])))
    top, nt = best[0]
    if nt == best[1][1]:
        return None
    s = f"קופת {top} חתומה על ההסכמים הרבים ביותר: {_houses(nt)} ({_pct(nt, total)})"
    all4 = int(d["payers"].map(lambda p: all(h in p for h in four)).sum())
    if all4:
        s += f"; {_houses(all4)} בהסכם עם כל ארבע קופות החולים"
    return s + "."


def ins_operators(d, total):
    c = _counts(d["operator"])
    if len(c) < 3:
        return None
    n_ops = len(c)
    top_n = c[0][1]
    if top_n < 2:
        return None
    leaders = [k for k, v in c if v == top_n]
    singles = sum(1 for _, v in c if v == 1)
    lead = (f"המפעיל הגדול הוא {leaders[0]}, עם {_houses(top_n)}"
            if len(leaders) == 1 else
            f"המפעילים הגדולים הם {_join(leaders)}, עם {_houses(top_n)} כל אחד")
    s = f"את הבתים מפעילים {_n(n_ops, 'גוף אחד', 'גופים')}. {lead}"
    if singles:
        s += f"; {'גוף אחד מפעיל' if singles == 1 else f'{singles:,} גופים מפעילים'} בית אחד בלבד"
    return s + "."


def ins_types(d, total):
    c = _counts(d["type"])
    if not c:
        return None
    top, n1 = c[0]
    if n1 / total < 0.5:
        return None
    rest = [f"{k} ({v:,})" for k, v in c[1:]]
    s = f"{n1:,} מתוך {total:,} הבתים ({_pct(n1, total)}) הם מסוג {top}"
    if rest:
        s += f"; השאר: {', '.join(rest)}"
    return s + "."


def ins_eating(d):
    ed = d[d["type"].str.contains("אכילה")]
    if len(ed) < 2:
        return None
    if not (ed["gender"] == "women").all():
        return None
    return (f"כל {len(ed):,} הבתים להפרעות אכילה מיועדים לנשים בלבד "
            f"(לפי שדה ההערות), ואין ברשימה בית מאזן להפרעות אכילה לגברים.")


def ins_youth(d, districts):
    y = d[d["type"].str.contains("ילדים|נוער")]
    if y.empty:
        return None
    have = set(y["district"])
    missing = [x for x in districts if x not in have and x != "לא צוין"]
    s = f"בתים מאזנים לילדים ונוער: {_houses(len(y))}"
    s += f" {_pre('ב', len(have), 'מחוז אחד', 'מחוזות')}"
    if missing:
        s += (f"; במחוז {missing[0]} אין בית כזה" if len(missing) == 1 else
              f"; במחוזות {_join(missing)} אין בית כזה")
    return s + "."


def ins_cities(d, total):
    c = _counts(d["city"])
    if len(c) < 2:
        return None
    top, n1 = c[0]
    if n1 < 2:
        return None
    leaders = [k for k, v in c if v == n1]
    one = sum(1 for _, v in c if v == 1)
    s = f"הבתים פזורים {_pre('ב', len(c), 'יישוב אחד', 'יישובים')}. "
    s += (f"ב{leaders[0]} יש הכי הרבה בתים ({n1:,})" if len(leaders) == 1 else
          f"ב{_join(leaders)} יש הכי הרבה בתים ({n1:,} בכל אחד)")
    if one:
        s += f", {_pre('וב', one, 'יישוב אחד', 'יישובים')} יש בית יחיד"
    return s + "."


# -------------------------------------------------------------------- main

def compute(frames):
    d = _prepare(frames["houses"])
    total = int(len(d))
    districts = _ordered(d, "district", "district_code")
    types = _ordered(d, "type", "type_code")
    n_ops = int(d["operator"].nunique())
    n_cities = int(d["city"].nunique())
    n_noagr = int(d["no_agreement"].sum())
    youth = int(d["type"].str.contains("ילדים|נוער").sum())

    # chart: district x type (stacked)
    by_dt = {"x": districts, "totals": [], "series": []}
    for t_i, t in enumerate(types):
        data = [int(((d["district"] == ds) & (d["type"] == t)).sum()) for ds in districts]
        by_dt["series"].append({"name": t, "data": data,
                                "color": PALETTE[t_i % len(PALETTE)]})
    by_dt["totals"] = [int((d["district"] == ds).sum()) for ds in districts]

    # chart: type split
    by_type = [{"name": t, "value": int((d["type"] == t).sum()),
                "share": round(int((d["type"] == t).sum()) / total * 100, 1),
                "color": PALETTE[i % len(PALETTE)]} for i, t in enumerate(types)]

    # chart: payers
    payer_counts = {}
    for p in d["payers"]:
        for x in p:
            payer_counts[x] = payer_counts.get(x, 0) + 1

    payers = sorted(payer_counts.items(), key=lambda kv: _payer_rank(kv[0]))
    pay_names = [k for k, _ in payers]
    pay_vals = [int(v) for _, v in payers]
    if n_noagr:
        pay_names.append("אין עדיין הסכם")
        pay_vals.append(n_noagr)
    by_payer = {"names": pay_names, "values": pay_vals,
                "shares": [round(v / total * 100, 1) for v in pay_vals],
                "noagr": bool(n_noagr)}

    # chart: operators top-N + other
    oc = _counts(d["operator"])
    ops_names = [k for k, _ in oc[:TOP_OPERATORS]]
    ops_vals = [v for _, v in oc[:TOP_OPERATORS]]
    rest = oc[TOP_OPERATORS:]
    if rest:
        ops_names.append(f"אחר ({len(rest):,} מפעילים)")
        ops_vals.append(int(sum(v for _, v in rest)))
    by_op = {"names": ops_names, "values": ops_vals, "other": bool(rest)}

    # chart: audiences (non-exclusive)
    aud_names, aud_vals = [], []
    for g in GENDER_ORDER:
        n = int((d["gender"] == g).sum())
        if n and g != "unknown":
            aud_names.append(GENDER_LABELS[g])
            aud_vals.append(n)
    for key, label, words in AUDIENCES:
        n = int(d["comments"].map(lambda c, w=words: any(x in c for x in w)).sum())
        if n:
            aud_names.append(label)
            aud_vals.append(n)
    if youth:
        aud_names.append("ילדים ונוער")
        aud_vals.append(youth)
    unknown_g = int((d["gender"] == "unknown").sum())
    by_aud = {"names": aud_names, "values": aud_vals}

    # directory grouped by district
    directory = []
    for ds in districts:
        rows = d[d["district"] == ds]
        items = []
        for _, r in rows.iterrows():
            items.append({
                "title": r["title"], "city": r["city"], "type": r["type"],
                "operator": r["operator"],
                "payers": ("אין עדיין הסכם עם קופות חולים" if r["no_agreement"]
                           else ", ".join(r["payers"]) or "לא צוין"),
                "notes": r["comments"],
                "phones": _phones(r["phone_raw"]),
                "emails": _emails(r["email_raw"]),
            })
        directory.append({"district": ds, "count_label": _houses(len(items)),
                          "items": items})

    insights = []
    for iid, fn in (("district", lambda: ins_district(d, total)),
                    ("no_agreement", lambda: ins_no_agreement(d, total)),
                    ("hmos", lambda: ins_hmos(d, total)),
                    ("types", lambda: ins_types(d, total)),
                    ("youth", lambda: ins_youth(d, districts)),
                    ("eating", lambda: ins_eating(d)),
                    ("operators", lambda: ins_operators(d, total)),
                    ("cities", lambda: ins_cities(d, total))):
        t = fn()
        if t:
            insights.append({"id": iid, "text_he": t})

    top_dist = _counts(d["district"])[0]
    labels = {
        "lede": (f"משרד הבריאות מפקח על {_houses(total)} מאזנים: מסגרות טיפול "
                 f"קהילתיות למשבר נפשי חריף, המשמשות חלופה לאשפוז במחלקה "
                 f"פסיכיאטרית. הבתים פועלים {_pre('ב', n_cities, 'יישוב אחד', 'יישובים')} "
                 f"{_pre('ב', len(districts), 'מחוז אחד', 'מחוזות')}, ומופעלים בידי "
                 f"{_n(n_ops, 'מפעיל אחד', 'מפעילים')}. למטה: רשימת הבתים לפי מחוז, "
                 f"עם המפעיל, קופות החולים שבהסכם, טלפון ודואר אלקטרוני."),
        "dir_note": (f"{_houses(total)} לפי מחוז ויישוב. הטלפון והדואר האלקטרוני "
                     f"הם פרטי הקשר של הבית כפי שפורסמו ברשימת משרד הבריאות."),
        "district_note": (f"מחוז {top_dist[0]} מוביל עם {_houses(top_dist[1])}. "
                          f"כל עמודה מחולקת לפי סוג הבית."),
        "district_aria": "מספר הבתים המאזנים בכל מחוז, לפי סוג הבית",
        "type_note": (f"{by_type[0]['name']}: {_houses(by_type[0]['value'])}. "
                      f"שאר הבתים מתמחים בקהל או בבעיה מסוימת."
                      if by_type else ""),
        "type_aria": "התפלגות הבתים המאזנים לפי סוג",
        "payer_note": ("מספר הבתים שיש להם הסכם עם כל גורם מממן. בית יכול להיות "
                       "בהסכם עם כמה גורמים, ולכן הסכום גבוה ממספר הבתים."
                       + (f" ל{'בית אחד' if n_noagr == 1 else f'-{n_noagr:,} בתים'} "
                          f"אין עדיין הסכם." if n_noagr else "")),
        "payer_aria": "מספר הבתים המאזנים בהסכם עם כל קופת חולים ועם משרד הביטחון",
        "op_note": (f"{_n(n_ops, 'מפעיל אחד', 'מפעילים')}. "
                    + (f"בגרף מוצגים {TOP_OPERATORS:,} הגדולים; בטבלה גם שאר "
                       f"{len(rest):,} המפעילים, מקובצים תחת אחר ({sum(v for _, v in rest):,} בתים)."
                       if by_op["other"] else "כולם מוצגים.")),
        "op_aria": "מספר הבתים המאזנים לפי מפעיל",
        "aud_note": ("קהלי יעד כפי שמופיעים בשדה ההערות ובסוג הבית. "
                     "בית יכול להופיע ביותר מקבוצה אחת."
                     + (f" ב{'בית אחד' if unknown_g == 1 else f'-{unknown_g:,} בתים'} "
                        f"ההערות אינן מציינות מגדר." if unknown_g else "")),
        "aud_aria": "מספר הבתים המאזנים לפי קהל יעד",
    }

    kpis = {
        "total": {"value": total, "display": f"{total:,}", "tone": "brand"},
        "cities": {"value": n_cities, "display": f"{n_cities:,}", "tone": "brand"},
        "operators": {"value": n_ops, "display": f"{n_ops:,}", "tone": "brand"},
        "no_agreement": {"value": n_noagr, "display": f"{n_noagr:,}",
                         "tone": "warn" if n_noagr else "ok"},
    }

    summary = (f"איתור בית מאזן לפי מחוז, יישוב, מפעיל וקופת חולים, עם טלפון ודוא\"ל: "
               f"{_houses(total)} מאזנים בפיקוח משרד הבריאות {_pre('ב', n_cities, 'יישוב אחד', 'יישובים')}.")
    if len(summary) > SUMMARY_MAX:
        summary = (f"איתור בית מאזן לפי מחוז, יישוב וקופת חולים: "
                   f"{_houses(total)} מאזנים בפיקוח משרד הבריאות.")

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "registry",
            "suggested_tags": ["בתים מאזנים", "בריאות הנפש", "חלופה לאשפוז",
                               "קופות חולים", "שיקום בקהילה"],
            "related_ids": ["5c8651bc-5288-4d46-a3f5-2ebfbe5c9615",
                            "b08ed183-2c26-490f-aa13-f1a7529c3aca",
                            "b54ae5a7-1bd5-4e7f-8b9d-f367f8eefd65"],
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": {"district": by_dt, "types": by_type, "payers": by_payer,
                   "operators": by_op, "audience": by_aud},
        "directory": directory,
        "insights": insights,
        "labels": labels,
    }
