"""סקר ביטחון אישי: CBS's yearly "first findings" release of the personal
security survey (people aged 20+ and households).

The release is a set of chart-data sheets ("תרשים N - ..."), one value per
cell, for ONE survey year. The source reads three editions
(`history_releases: 3`), so each table grid stacks the 2022, 2024 and 2025
surveys. Chart NUMBERS MOVE between editions (reporting to the police was
chart 3 in 2022 and chart 4 since), so every table input (t1..t16, the last
three spare, all optional) is split by edition and each chart is found by
its TITLE text, never by its stem:

  types     נפגעי עבריינות בקרב בני 20 ומעלה, לפי סוג עבירה   % victims by offense
  jews      ... בקרב יהודים ואחרים ...                        same, Jews and others
  sex       ... לפי מין וסוג עבירה                             offense x men/women
  report    דיווח ואי-דיווח למשטרה ... בני 20 ומעלה             reported / not
  preport   דיווח ואי-דיווח למשטרה ... רכוש של משק הבית         household property
  vharm     שנפגעו מאלימות ... סוג הנזק                        harm from violence
  online    נפגעי עבירה מקוונת ... לפי סוג עבירה               online offense types
  property  משקי בית שנפגעו מעבירות רכוש                       household property
  children  משקי בית עם ילדים נפגעי עבריינות                   offenses vs children
  safety    תחושת ביטחון אישי ... בשעות החשכה                  feel safe, by group
  fear      חשש להיפגע ...                                     fear of crime / terror
  district  שינוי בתחושת הביטחון ... לפי מחוז                  worse / same / better

The page shows the newest edition; older editions only add a survey-year
comparison. A chart missing from the newest edition drops its section. A
recognised chart that has data rows but whose header labels are gone raises
(the layout changed: a human should look).
"""
import re

import pandas as pd
from govlib import cbs, fmt

TITLE = re.compile(r"^תרשים\s*\d+[א-ת]?\s*-\s*")
SURVEY = re.compile(r"סקר\s+((?:19|20)\d\d)")
REL = re.compile(r"(\d+)\s*/\s*(\d{4})")
HEB = re.compile("[א-ת]")
STEM = re.compile(r"t\d+")
GROUPS = ("סך הכל", "גברים", "נשים", "יהודים ואחרים", "ערבים")
# Two survey readings closer than this (percentage points) are "about the same".
FLAT_PP = 0.5
# The insights card keeps the strongest few, in `order` (see compute).
MAX_INSIGHTS = 8


# ── editions and tables ─────────────────────────────────────────────────


def _rel_key(no):
    m = REL.search(str(no))
    return (int(m.group(2)), int(m.group(1))) if m else (0, 0)


def _int(v):
    try:
        return int(str(v).strip())
    except ValueError:
        return 0


def _cells(df):
    cols = sorted((c for c in df.columns if re.fullmatch(r"C\d+", c)), key=lambda c: int(c[1:]))
    return cols


def _title(rows):
    for r in rows:
        for c in r:
            if TITLE.match(c):
                return c
    return ""


def _kind(t):
    if "דיווח" in t and "למשטרה" in t:
        return "preport" if "רכוש" in t else "report"
    if "שינוי בתחושת הביטחון" in t:
        return "district" if "מחוז" in t else None
    if "חשש" in t:
        return "fear"
    if "תחושת ביטחון" in t or "תחושת בטחון" in t:
        return "safety"
    if "משקי בית עם ילדים" in t:
        return "children"
    if "משקי בית" in t and "רכוש" in t:
        return "property"
    if "עבירה מקוונת" in t and "סוג עבירה" in t:
        return "online"
    if "אלימות" in t and "נזק" in t:
        return "vharm"
    if "לפי מין" in t and "סוג עבירה" in t:
        return "sex"
    if "נפגעי עבריינות" in t and "סוג עבירה" in t:
        return "jews" if "בקרב יהודים" in t else "types"
    return None


def _editions(frames):
    """{release key: {"year": survey year, "no": release no, "tables": {kind: rows}}}
    over every non-empty table input; the first stem (by number) to hold a
    kind in an edition wins."""
    out = {}
    names = sorted((n for n in frames if STEM.fullmatch(n)), key=lambda n: int(n[1:]))
    for n in names:
        df = frames[n]
        if df.empty:
            continue
        cols = _cells(df)
        for no in sorted(df["RELEASE_NO"].unique(), key=lambda x: (_rel_key(x), str(x))):
            g = df[df["RELEASE_NO"] == no]
            g = g.assign(_s=g["SHEET_NO"].map(_int), _r=g["ROW"].map(_int))
            g = g.sort_values(["_s", "_r"], kind="stable")
            rows = [[cbs.clean(v) for v in r] for r in g[cols].itertuples(index=False)]
            t = _title(rows)
            k = _kind(t)
            if not k:
                continue
            m = SURVEY.search(t)
            if not m:
                continue
            ed = out.setdefault(_rel_key(no), {"year": int(m.group(1)), "no": no, "tables": {}})
            if k not in ed["tables"]:
                ed["tables"][k] = rows
    return out


# ── generic parsing ─────────────────────────────────────────────────────


def _is_num(c):
    return cbs.num(c) is not None


def _is_note(c):
    return c.startswith(("(", "מקור"))


def _data_rows(rows):
    return [i for i, r in enumerate(rows) if any(_is_num(c) for c in r)]


def _matrix(rows, name):
    """(header [(col, label)], [(row label, {label: value})]) for a chart
    sheet with one header row of column labels and data rows below it.
    None when the sheet has no data rows (a cut-off sheet); raises when it
    has data but no header row."""
    data = _data_rows(rows)
    if not data:
        return None
    first = data[0]
    head = None
    for i in range(first - 1, -1, -1):
        r = rows[i]
        cells = [(j, c) for j, c in enumerate(r) if c]
        if any(TITLE.match(c) for _, c in cells):
            break
        if len(cells) >= 1 and all(HEB.search(c) and not _is_num(c) and not _is_note(c)
                                   for _, c in cells):
            head = cells
            break
    if head is None:
        raise ValueError(f"{name}: header row not found")
    out = []
    for i in data:
        r = rows[i]
        lab = cbs.cell(r, 0)
        lab = "" if (_is_num(lab) or lab in cbs.MISSING) else lab
        if _is_note(lab):
            continue
        out.append((lab, {c: cbs.val(r, j) for j, c in head}))
    return head, out


def _norm(label):
    s = label.replace("ו/או", "או").replace("גניבה", "גנבה").replace("עבירת מין", "עבירות מין")
    s = s.replace("\u2013", "-").replace("\u2014", "-")
    return re.sub(r"\s+", " ", s).strip()


def _sections(rows, name, keys):
    """For the two-measure group sheets (safety, fear): {measure: {group: value}}.
    `keys` maps a measure id to a word its top header must contain."""
    data = _data_rows(rows)
    if not data:
        return None
    first = data[0]
    top = None
    for i in range(first - 1, -1, -1):
        cells = [(j, c) for j, c in enumerate(rows[i]) if c]
        if any(TITLE.match(c) for _, c in cells):
            break
        if any(any(w in c for w in keys.values()) for _, c in cells):
            top = i
            break
    if top is None:
        raise ValueError(f"{name}: measure header row not found")
    starts = []
    for j, c in enumerate(rows[top]):
        for k, w in keys.items():
            if c and w in c and k not in [s[1] for s in starts]:
                starts.append((j, k))
    if len(starts) != len(keys):
        raise ValueError(f"{name}: expected {len(keys)} measures, found {len(starts)}")
    starts.sort()
    sub = None
    for i in range(top + 1, first):
        if any(c in ("גברים", "נשים") for c in rows[i]):
            sub = rows[i]
    if sub is None:
        raise ValueError(f"{name}: group header row (גברים/נשים) not found")
    vr = rows[first]
    out = {}
    for n, (j0, k) in enumerate(starts):
        j1 = starts[n + 1][0] if n + 1 < len(starts) else len(vr)
        vals = {"סך הכל": cbs.val(vr, j0)}
        for j in range(j0 + 1, j1):
            g = cbs.cell(sub, j)
            if g in GROUPS:
                vals[g] = cbs.val(vr, j)
        out[k] = vals
    return out


# ── kind parsers ────────────────────────────────────────────────────────


def _offense_row(rows, name, want=("סך הכל", "")):
    """{offense: %} from the first data row whose label is in `want`."""
    m = _matrix(rows, name)
    if m is None:
        return None, {}
    _, data = m
    groups = {}
    main = None
    for lab, vals in data:
        v = {_norm(k): x for k, x in vals.items()}
        if lab in want and main is None:
            main = v
        elif lab:
            groups[lab] = v
    return main, groups


def _sex(rows):
    m = _matrix(rows, "sex")
    if m is None:
        return None
    head, data = m
    labels = [c for _, c in head]
    for need in ("גברים", "נשים"):
        if need not in labels:
            raise ValueError(f"sex: header {need!r} not found")
    out = {}
    for lab, vals in data:
        if lab:
            out[_norm(lab)] = vals
    return out


def _report(rows, name):
    m = _matrix(rows, name)
    if m is None:
        return None
    head, data = m
    labels = [c for _, c in head]
    if "דיווחו למשטרה" not in labels:
        raise ValueError(f"{name}: header 'דיווחו למשטרה' not found")
    out = []
    for lab, vals in data:
        if lab:
            out.append((_norm(lab), vals.get("דיווחו למשטרה"), vals.get("לא דיווחו למשטרה"),
                        vals.get("שיעור ההיפגעות")))
    return out


def _one_row(rows, name, total_word):
    """(total, [(label, %)]) for a sheet of labels over one value row; the
    column whose label contains `total_word` is the total."""
    m = _matrix(rows, name)
    if m is None:
        return None
    head, data = m
    if not data:
        return None
    vals = data[0][1]
    total, items = None, []
    for _, c in head:
        if total_word in c:
            total = vals.get(c)
        elif vals.get(c) is not None:
            items.append((_norm(c), vals.get(c)))
    return total, items


def _property(rows):
    """{"total", "home", "home_theft", "home_burglary", "car", "car_parts", "car_theft"}."""
    data = _data_rows(rows)
    if not data:
        return None
    first = data[0]
    grp = sub = None
    for i in range(first - 1, -1, -1):
        r = rows[i]
        if any(TITLE.match(c) for c in r):
            break
        if sub is None and any(c == "סך הכל" for c in r):
            sub = r
        elif any("דירת" in c for c in r):
            grp = r
            break
    if grp is None or sub is None:
        raise ValueError("property: header rows not found")
    home = next((j for j, c in enumerate(grp) if "דירת" in c), None)
    car = next((j for j, c in enumerate(grp) if "מכונית" in c or c.endswith("רכב")), None)
    if home is None or car is None:
        raise ValueError("property: home / car header not found")
    vr = rows[first]
    out = {"total": cbs.val(vr, 0)}
    for j, c in enumerate(sub):
        v = cbs.val(vr, j)
        if c == "סך הכל":
            out["home" if home <= j < car else "car"] = v
        elif "גנבה מדירה" in c:
            out["home_theft"] = v
        elif "פריצה" in c:
            out["home_burglary"] = v
        elif "חלקי רכב" in c:
            out["car_parts"] = v
        elif "גנבת מכונית" in c:
            out["car_theft"] = v
    return out


def _children(rows):
    m = _matrix(rows, "children")
    if m is None:
        return None
    head, data = m
    tot = next((c for _, c in head if c.startswith("סך כל")), None)
    if tot is None:
        raise ValueError("children: total header not found")
    out = {}
    for lab, vals in data:
        if lab:
            out[lab] = {("סך הכל" if k == tot else _norm(k)): v for k, v in vals.items()}
    return out


def _district(rows):
    m = _matrix(rows, "district")
    if m is None:
        return None
    _, data = m
    out = {}
    for lab, vals in data:
        key = ("worse" if "לרעה" in lab else "better" if "לטובה" in lab
               else "same" if "לא חל" in lab else None)
        if key:
            out[key] = {_norm(k): v for k, v in vals.items()}
    if "worse" not in out:
        return None
    return out


# ── formatting ──────────────────────────────────────────────────────────


def _p(v, d=1):
    return "–" if v is None else fmt.pct_of(v, d)


def _r(v, d=1):
    return None if v is None else round(v, d)


def _pp(a, b):
    """'1.2 נקודות אחוז' for a difference of two percents."""
    return f"{fmt.num_he(abs(a - b), 1)} נקודות אחוז"


def _ratio(a, b):
    return a / b if (a is not None and b) else None


def _where(d):
    return f"ב{d}" if d.startswith("אזור") else f"במחוז {d}"


def _short(label):
    return {"אזור יהודה והשומרון": "יהודה ושומרון", "אלימות או איום באלימות": "אלימות או איום"}.get(
        label, label)


# ── compute ─────────────────────────────────────────────────────────────


def compute(frames):
    rel = cbs.latest_release(frames["releases"])
    eds = _editions(frames)
    if not eds:
        raise ValueError("no survey chart recognised in any table")
    keys = sorted(eds)
    latest = eds[keys[-1]]
    ly = latest["year"]
    years = [eds[k]["year"] for k in keys]

    kpis, labels, charts, tables, flags = {}, {}, {}, {}, {}
    cands = []

    def add(iid, text):
        if text:
            cands.append({"id": iid, "text_he": text})

    # parse every edition's tables once
    parsed = {}
    for k in keys:
        tb = eds[k]["tables"]
        p = {}
        if "types" in tb:
            p["types"], p["types_groups"] = _offense_row(tb["types"], "types")
        if "jews" in tb:
            main, groups = _offense_row(tb["jews"], "jews", want=("יהודים ואחרים", ""))
            p["jews"] = main or groups.get("יהודים ואחרים")
        if "sex" in tb:
            p["sex"] = _sex(tb["sex"])
        if "report" in tb:
            p["report"] = _report(tb["report"], "report")
        if "preport" in tb:
            p["preport"] = _report(tb["preport"], "preport")
        if "vharm" in tb:
            p["vharm"] = _one_row(tb["vharm"], "vharm", "סך הכל")
        if "online" in tb:
            p["online"] = _one_row(tb["online"], "online", "סך הכל")
        if "property" in tb:
            p["property"] = _property(tb["property"])
        if "children" in tb:
            p["children"] = _children(tb["children"])
        if "safety" in tb:
            p["safety"] = _sections(tb["safety"], "safety", {"general": "באופן כללי", "dark": "החשכה"})
        if "fear" in tb:
            p["fear"] = _sections(tb["fear"], "fear", {"crime": "פשיעה", "terror": "טרור"})
        if "district" in tb:
            p["district"] = _district(tb["district"])
        parsed[k] = {kk: vv for kk, vv in p.items() if vv}
    L = parsed[keys[-1]]

    def history(kind):
        """[(year, parsed)] over editions holding `kind`, oldest first."""
        return [(eds[k]["year"], parsed[k][kind]) for k in keys if parsed[k].get(kind)]

    # ── overall victimisation rate ──
    overall = None
    sex = L.get("sex")
    if sex and "סך הכל" in sex:
        overall = sex["סך הכל"].get("סך כולל")
    if overall is None and L.get("report"):
        overall = next((r[3] for r in L["report"] if r[0] == "סך הכל"), None)
    headline = str(rel.get("HEADLINE") or "")
    if overall is None:
        m = re.search(r"\((\d+(?:\.\d+)?)%\)", headline)
        overall = float(m.group(1)) if m else None
    if overall is not None:
        kpis["rate"] = {"value": round(overall, 1), "display": fmt.pct_of(overall), "tone": "brand"}
    m = re.search(r"כ-?\s*(\d[\d,]*(?:\.\d+)?)\s*אלף", headline)
    persons = float(m.group(1).replace(",", "")) if m else None
    if persons is not None:
        kpis["persons"] = {"value": persons, "display": fmt.int_he(persons), "tone": "brand"}

    # ── 1. offense types by survey year ──
    th = history("types")
    last_types = th[-1][1] if th and th[-1][0] == ly else None
    sex = L.get("sex")
    if last_types:
        base = last_types
    elif sex:
        base = {o: v.get("סך כולל") for o, v in sex.items() if o != "סך הכל"}
    else:
        base = {}
    offs = [o for o, v in sorted(base.items(), key=lambda kv: (-(kv[1] or -1), kv[0]))
            if v is not None]
    top = offs[0] if offs else None
    if last_types and offs:
        flags["types"] = True
        charts["types"] = {"x": [_short(o) for o in offs],
                           "series": [{"name": f"סקר {y}", "data": [_r(d.get(o)) for o in offs]}
                                      for y, d in th]}
        labels["types_cols"] = ["סוג עבירה"] + [f"סקר {y}" for y, _ in th]
        tables["types"] = [[o] + [_p(d.get(o)) for _, d in th] for o in offs]
        labels["types_note"] = (f"אחוז בני 20 ומעלה שנפגעו מכל סוג עבירה בשנה שקדמה לסקר. בסקר {ly} "
                                f"הנפוצה ביותר: {top}, {_p(last_types[top])}"
                                + (f". סך הכל נפגעו {_p(overall)} מבני 20 ומעלה." if overall is not None else "."))
        labels["types_aria"] = ("תרשים עמודות: אחוז הנפגעים לפי סוג עבירה, סקרי "
                                + fmt.join_he([str(y) for y, _ in th]))
    if last_types and len(offs) >= 2:
        second = offs[1]
        r = _ratio(last_types[top], last_types[second])
        if r and r >= 1.5:
            add("top", f"{top} היא העבירה הנפוצה ביותר: {_p(last_types[top])} מבני 20 ומעלה נפגעו ממנה "
                f"בסקר {ly}, פי {fmt.num_he(r, 1)} מ{second} ({_p(last_types[second])}).")
        else:
            add("top", f"העבירה הנפוצה ביותר בסקר {ly} היא {top} ({_p(last_types[top])} מבני 20 ומעלה), "
                f"ואחריה {second} ({_p(last_types[second])}).")
    if last_types and len(th) >= 2:
        py, prev = th[-2]
        ups, downs = [], []
        for o in offs:
            a, b = last_types.get(o), prev.get(o)
            if a is None or b is None:
                continue
            if a - b >= FLAT_PP:
                ups.append((a - b, o, a, b))
            elif b - a >= FLAT_PP:
                downs.append((b - a, o, a, b))
        parts = []
        if downs:
            d, o, a, b = max(downs)
            parts.append(f"שיעור הנפגעים מ{o} ירד מ-{_p(b)} ל-{_p(a)}")
        if ups:
            d, o, a, b = max(ups)
            parts.append(f"שיעור הנפגעים מ{o} עלה מ-{_p(b)} ל-{_p(a)}")
        if parts:
            add("change", f"בין סקר {py} לסקר {ly} " + ", ו".join(parts) + ".")
        else:
            add("change", f"שיעורי הנפגעים מכל סוגי העבירות בסקר {ly} דומים לאלה של סקר {py} "
                f"(הפרש של פחות מ-{fmt.num_he(FLAT_PP, 1)} נקודות אחוז).")

    # ── 2. by sex and population group ──
    gser = []
    if sex and offs:
        for g in ("גברים", "נשים"):
            gser.append({"name": g, "data": [_r(sex.get(o, {}).get(g)) for o in offs]})
    jews = L.get("jews")
    if not jews:
        jews = (L.get("types_groups") or {}).get("יהודים ואחרים")
    if jews and offs:
        gser.append({"name": "יהודים ואחרים", "data": [_r(jews.get(o)) for o in offs]})
    arabs = (L.get("types_groups") or {}).get("ערבים")
    if arabs and offs:
        gser.append({"name": "ערבים", "data": [_r(arabs.get(o)) for o in offs]})
    if gser and any(v is not None for s in gser for v in s["data"]):
        flags["groups"] = True
        charts["groups"] = {"x": [_short(o) for o in offs], "series": gser}
        labels["groups_cols"] = ["סוג עבירה"] + [s["name"] for s in gser]
        tables["groups"] = [[o] + [_p(s["data"][i]) for s in gser] for i, o in enumerate(offs)]
        labels["groups_aria"] = f"תרשים עמודות: אחוז הנפגעים לפי סוג עבירה, מין וקבוצת אוכלוסייה, סקר {ly}"
        labels["groups_note"] = (f"אחוז הנפגעים מכל סוג עבירה בכל קבוצה, סקר {ly}. "
                                 "תא ריק: הלמ\"ס אינה מפרסמת את הנתון בשל מיעוט מקרים.")
    if sex:
        hm = next((o for o in sex if "הטרדה" in o), None)
        if hm:
            w, mn = sex[hm].get("נשים"), sex[hm].get("גברים")
            r = _ratio(w, mn)
            if r and r >= 2:
                add("harass", f"נשים נפגעות מהטרדה מינית הרבה יותר מגברים: {_p(w)} מהנשים לעומת "
                    f"{_p(mn)} מהגברים (פי {fmt.num_he(r, 1)}), סקר {ly}.")
            elif w is not None and mn is None:
                add("harass", f"{_p(w)} מהנשים בנות 20 ומעלה נפגעו מהטרדה מינית בסקר {ly}. "
                    "שיעור הגברים נמוך מכדי שהלמ\"ס תפרסם אותו.")
        vm = next((o for o in sex if o.startswith("אלימות")), None)
        if vm:
            w, mn = sex[vm].get("נשים"), sex[vm].get("גברים")
            if w is not None and mn is not None and mn - w >= FLAT_PP:
                add("violence_sex", f"גברים נפגעים מאלימות או מאיום באלימות יותר מנשים: {_p(mn)} "
                    f"לעומת {_p(w)}, סקר {ly}.")

    # ── 3. reporting to the police ──
    rep = L.get("report")
    rep_total = None
    if rep:
        rep_total = next((r for r in rep if r[0] == "סך הכל"), None)
        rows_r = [r for r in rep if r[0] != "סך הכל" and (r[1] is not None or r[2] is not None)]
        rows_r.sort(key=lambda r: (-(r[1] if r[1] is not None else (100 - r[2] if r[2] is not None else 0)), r[0]))
        if rep_total:
            rows_r = [rep_total] + rows_r
        if rows_r:
            flags["report"] = True
            charts["report"] = {"x": [_short(r[0]) for r in rows_r],
                                "yes": [_r(r[1]) for r in rows_r], "no": [_r(r[2]) for r in rows_r]}
            rh = history("report")
            labels["report_cols"] = ["סוג עבירה", f"לא דיווחו (סקר {ly})"] + [f"דיווחו (סקר {y})" for y, _ in rh]
            tables["report"] = []
            for r in rows_r:
                row = [r[0], _p(r[2])]
                for _, d in rh:
                    hit = next((x for x in d if x[0] == r[0]), None)
                    row.append(_p(hit[1] if hit else None))
                tables["report"].append(row)
            labels["report_aria"] = f"תרשים עמודות נערמות: אחוז הנפגעים שדיווחו למשטרה לפי סוג עבירה, סקר {ly}"
            labels["report_note"] = (f"מתוך מי שנפגעו מכל סוג עבירה, כמה דיווחו למשטרה, סקר {ly}. "
                                     "תא ריק: הנתון אינו מתפרסם בשל מיעוט מקרים.")
            if rep_total and rep_total[1] is not None:
                kpis["reported"] = {"value": _r(rep_total[1]), "display": _p(rep_total[1]),
                                    "tone": "warn" if rep_total[1] < 30 else "brand"}
            known = [r for r in rows_r if r[0] != "סך הכל" and r[1] is not None]
            if len(known) >= 2:
                hi, lo = known[0], known[-1]
                txt = (f"שיעור הדיווח למשטרה הגבוה ביותר הוא על {hi[0]} ({_p(hi[1])} מהנפגעים) "
                       f"והנמוך ביותר על {lo[0]} ({_p(lo[1])}), סקר {ly}.")
                if rep_total and rep_total[1] is not None:
                    txt = f"רק {_p(rep_total[1])} מהנפגעים מעבירות דיווחו למשטרה. " + txt
                add("report", txt)

    # ── 4. harm from violence ──
    vh = L.get("vharm")
    if vh and vh[1]:
        vtot, items = vh
        items = sorted(items, key=lambda kv: (-kv[1], kv[0]))
        hist = history("vharm")
        flags["vharm"] = True
        names = [n for n, _ in items]
        charts["vharm"] = {"x": names,
                           "series": [{"name": f"סקר {y}", "data": [_r(dict(d[1]).get(n)) for n in names]}
                                      for y, d in hist]}
        labels["vharm_cols"] = ["סוג הנזק"] + [f"סקר {y}" for y, _ in hist]
        tables["vharm"] = [[n] + [_p(dict(d[1]).get(n)) for _, d in hist] for n in names]
        labels["vharm_aria"] = f"תרשים עמודות: סוגי הנזק שנגרם לנפגעי אלימות, סקר {ly}"
        labels["vharm_note"] = ((f"{_p(vtot)} מנפגעי האלימות או האיום באלימות סבלו מנזק כלשהו (סקר {ly}). "
                                 if vtot is not None else "")
                                + "התרשים מראה כמה מהם סבלו מכל סוג נזק. אפשר לסבול מכמה סוגי נזק, "
                                "ולכן הסכום גדול ממאה אחוז.")
        if vtot is not None:
            add("vharm", f"{_p(vtot)} מנפגעי האלימות או האיום באלימות סבלו מנזק, והנפוץ ביותר הוא "
                f"{names[0]}: {_p(items[0][1])} מהם, סקר {ly}.")

    # ── 5. online offenses ──
    on = L.get("online")
    if on and on[1]:
        items = sorted(on[1], key=lambda kv: (-kv[1], kv[0]))
        items = [kv for kv in items if kv[0] != "אחר"] + [kv for kv in items if kv[0] == "אחר"]
        hist = history("online")
        names = [n for n, _ in items]
        flags["online"] = True
        charts["online"] = {"x": names,
                            "series": [{"name": f"סקר {y}", "data": [_r(dict(d[1]).get(n)) for n in names]}
                                       for y, d in hist]}
        labels["online_cols"] = ["סוג העבירה המקוונת"] + [f"סקר {y}" for y, _ in hist]
        tables["online"] = [[n] + [_p(dict(d[1]).get(n)) for _, d in hist] for n in names]
        labels["online_aria"] = f"תרשים עמודות: נפגעי עבירה מקוונת לפי סוג העבירה, סקר {ly}"
        labels["online_note"] = ("מתוך מי שנפגעו מעבירה מקוונת, כמה נפגעו מכל סוג. אפשר להיפגע מכמה "
                                 "סוגים, ולכן הסכום גדול ממאה אחוז.")
        t0 = items[0]
        txt = f"מבין נפגעי העבירות המקוונות, {_p(t0[1])} נפגעו מ{t0[0]}"
        if len(items) >= 2:
            txt += f" ו-{_p(items[1][1])} מ{items[1][0]}"
        add("online", txt + f", סקר {ly}.")

    # ── 6. household property ──
    PROP = (("total", "כל עבירות הרכוש"), ("home", "כל העבירות כלפי הדירה"),
            ("home_theft", "גנבה מדירה"), ("home_burglary", "פריצה לדירה ללא גנבה"),
            ("car", "כל העבירות כלפי המכונית"), ("car_parts", "גנבת חלקי רכב וחפצים ממכונית"),
            ("car_theft", "גנבת מכונית"))
    pr = L.get("property")
    if pr and pr.get("total") is not None:
        hist = history("property")
        keys_p = [(k, n) for k, n in PROP if pr.get(k) is not None]
        flags["property"] = True
        charts["property"] = {"x": [n for _, n in keys_p],
                              "series": [{"name": f"סקר {y}", "data": [_r(d.get(k)) for k, _ in keys_p]}
                                         for y, d in hist]}
        labels["property_cols"] = ["סוג עבירה"] + [f"סקר {y}" for y, _ in hist]
        tables["property"] = [[n] + [_p(d.get(k)) for _, d in hist] for k, n in keys_p]
        labels["property_aria"] = f"תרשים עמודות: משקי בית שנפגעו מעבירות רכוש לפי סוג, סקר {ly}"
        labels["property_note"] = (f"אחוז משקי הבית שנפגעו מכל סוג עבירת רכוש בשנה שקדמה לסקר. "
                                   f"בסקר {ly}: {_p(pr['total'])} מכלל משקי הבית.")
        kpis["household"] = {"value": _r(pr["total"]), "display": _p(pr["total"]), "tone": "brand"}
        if len(hist) >= 2:
            fy, first = hist[0]
            a, b = pr["total"], first.get("total")
            if b is not None:
                if b - a >= FLAT_PP:
                    add("property", f"שיעור משקי הבית שנפגעו מעבירות רכוש ירד מ-{_p(b)} בסקר {fy} "
                        f"ל-{_p(a)} בסקר {ly}.")
                elif a - b >= FLAT_PP:
                    add("property", f"שיעור משקי הבית שנפגעו מעבירות רכוש עלה מ-{_p(b)} בסקר {fy} "
                        f"ל-{_p(a)} בסקר {ly}.")
                else:
                    add("property", f"{_p(a)} ממשקי הבית נפגעו מעבירות רכוש בסקר {ly}, בדומה לסקר {fy} ({_p(b)}).")

    # ── 7. reporting of property offenses ──
    prep = L.get("preport")
    if prep:
        tot = next((r for r in prep if r[0] == "סך הכל"), None)
        rest = [r for r in prep if r[0] != "סך הכל" and (r[1] is not None or r[2] is not None)]
        rest.sort(key=lambda r: (-(r[1] if r[1] is not None else 100 - r[2]), r[0]))
        rows_p = ([tot] if tot else []) + rest
        if rows_p:
            flags["preport"] = True
            charts["preport"] = {"x": [r[0] for r in rows_p],
                                 "yes": [_r(r[1]) for r in rows_p], "no": [_r(r[2]) for r in rows_p]}
            tables["preport"] = [[r[0], _p(r[1]), _p(r[2]), _p(r[3])] for r in rows_p]
            labels["preport_aria"] = f"תרשים עמודות נערמות: דיווח למשטרה על עבירות רכוש לפי סוג, סקר {ly}"
            known = [r for r in rest if r[1] is not None]
            if tot and tot[1] is not None and len(known) >= 2:
                add("preport", f"{_p(tot[1])} ממשקי הבית שנפגעו מעבירות רכוש דיווחו למשטרה. על "
                    f"{known[0][0]} דיווחו {_p(known[0][1])}, ועל {known[-1][0]} רק {_p(known[-1][1])}, סקר {ly}.")

    # ── 8. children ──
    ch = L.get("children")
    if ch:
        allh = next((v for k, v in ch.items() if k.startswith("כלל")), None)
        if allh and allh.get("סך הכל") is not None:
            cats = [k for k, v in sorted(allh.items(), key=lambda kv: (-(kv[1] or -1), kv[0]))
                    if k != "סך הכל" and v is not None]
            cats = ["סך הכל"] + cats
            rows_c = sorted(ch.items(), key=lambda kv: (0 if kv[0].startswith("כלל") else 1, kv[0]))
            flags["children"] = True
            charts["children"] = {"x": [("כל העבירות" if c == "סך הכל" else _short(c)) for c in cats],
                                  "series": [{"name": n, "data": [_r(v.get(c)) for c in cats]} for n, v in rows_c]}
            labels["children_cols"] = ["סוג עבירה"] + [n for n, _ in rows_c]
            tables["children"] = [[("כל העבירות כלפי ילדים" if c == "סך הכל" else c)]
                                  + [_p(v.get(c)) for _, v in rows_c] for c in cats]
            labels["children_aria"] = f"תרשים עמודות: משקי בית עם ילדים שילד בהם נפגע מעבירה, לפי סוג עבירה, סקר {ly}"
            hist = history("children")
            prev_tot = None
            if len(hist) >= 2:
                pv = next((v for k, v in hist[-2][1].items() if k.startswith("כלל")), None)
                prev_tot = (hist[-2][0], pv.get("סך הכל")) if pv else None
            labels["children_note"] = (f"אחוז משקי הבית שילד בהם נפגע מעבירה, מתוך משקי הבית עם ילדים בגיל "
                                       f"הרלוונטי לכל עבירה. בסקר {ly}: {_p(allh['סך הכל'])} מכלל משקי הבית"
                                       + (f" ({_p(prev_tot[1])} בסקר {prev_tot[0]})." if prev_tot and prev_tot[1] is not None else "."))
            bully = next((c for c in cats if "בריונות" in c), None)
            if bully and allh.get(bully) is not None:
                add("children", f"בריונות ברשת וביוש פוגעים בילדים ב-{_p(allh[bully])} ממשקי הבית עם ילדים, "
                    f"מתוך {_p(allh['סך הכל'])} שילד בהם נפגע מעבירה כלשהי, סקר {ly}.")

    # ── 9-10. sense of safety and fear ──
    def group_section(kind, measures, title_he):
        cur = L.get(kind)
        if not cur:
            return None
        hist = history(kind)
        flags[kind] = True
        charts[kind] = {"x": list(GROUPS),
                        "series": [{"name": n, "data": [_r(cur.get(m, {}).get(g)) for g in GROUPS]}
                                   for m, n in measures]}
        cols = ["קבוצה"]
        for m, n in measures:
            for y, _ in hist:
                cols.append(f"{n} (סקר {y})")
        labels[f"{kind}_cols"] = cols
        tables[kind] = [[g] + [_p(d.get(m, {}).get(g)) for m, _ in measures for _, d in hist] for g in GROUPS]
        labels[f"{kind}_aria"] = f"תרשים עמודות: {title_he} לפי מין וקבוצת אוכלוסייה, סקר {ly}"
        return cur, hist

    sres = group_section("safety", (("general", "באזור המגורים באופן כללי"),
                                    ("dark", "ללכת לבד בחשכה")), "תחושת ביטחון אישי")
    if sres:
        cur, hist = sres
        dk = cur.get("dark", {})
        gen = cur.get("general", {})
        if dk.get("סך הכל") is not None:
            v = dk["סך הכל"]
            pv = hist[-2][1].get("dark", {}).get("סך הכל") if len(hist) >= 2 else None
            tone = ("brand" if pv is None or abs(v - pv) < FLAT_PP else "ok" if v > pv else "warn")
            kpis["safe_dark"] = {"value": _r(v), "display": _p(v), "tone": tone}
        labels["safety_note"] = (f"אחוז בני 20 ומעלה שמרגישים בטוחים במידה רבה או רבה מאוד, סקר {ly}"
                                 + (f": {_p(gen.get('סך הכל'))} באזור המגורים באופן כללי ו-{_p(dk.get('סך הכל'))} "
                                    "כשהם הולכים לבד בשעות החשכה." if gen.get("סך הכל") is not None
                                    and dk.get("סך הכל") is not None else "."))
        m, w = dk.get("גברים"), dk.get("נשים")
        if m is not None and w is not None and m - w >= FLAT_PP:
            add("dark", f"{_p(m)} מהגברים מרגישים בטוחים ללכת לבד באזור המגורים בשעות החשכה, לעומת "
                f"{_p(w)} מהנשים, פער של {_pp(m, w)} (סקר {ly}).")
        if len(hist) >= 2:
            py, pd_ = hist[-2]
            a, b = gen.get("סך הכל"), pd_.get("general", {}).get("סך הכל")
            if a is not None and b is not None:
                word = ("עלה" if a - b >= FLAT_PP else "ירד" if b - a >= FLAT_PP else None)
                if word:
                    add("safety_trend", f"שיעור המרגישים בטוחים באזור המגורים באופן כללי {word} מ-{_p(b)} "
                        f"בסקר {py} ל-{_p(a)} בסקר {ly}.")
        j, ar = gen.get("יהודים ואחרים"), gen.get("ערבים")
        if j is not None and ar is not None and j - ar >= 3:
            add("safety_arab", f"בחברה הערבית {_p(ar)} מרגישים בטוחים באזור המגורים, לעומת {_p(j)} "
                f"בקרב יהודים ואחרים (סקר {ly}).")

    fres = group_section("fear", (("crime", "חשש מפשיעה או אלימות"), ("terror", "חשש מטרור")),
                         "חשש להיפגע")
    if fres:
        cur, hist = fres
        cr, te = cur.get("crime", {}), cur.get("terror", {})
        if te.get("סך הכל") is not None:
            kpis["fear_terror"] = {"value": _r(te["סך הכל"]), "display": _p(te["סך הכל"]), "tone": "warn"}
        labels["fear_note"] = (f"אחוז בני 20 ומעלה שחוששים במידה רבה או רבה מאוד להיפגע באזור המגורים, סקר {ly}"
                               + (f": {_p(cr.get('סך הכל'))} מפשיעה או מאלימות ו-{_p(te.get('סך הכל'))} מטרור."
                                  if cr.get("סך הכל") is not None and te.get("סך הכל") is not None else "."))
        j, ar = cr.get("יהודים ואחרים"), cr.get("ערבים")
        r = _ratio(ar, j)
        if r and r >= 1.3:
            add("fear_arab", f"בחברה הערבית {_p(ar)} חוששים להיפגע מפשיעה או מאלימות באזור המגורים, "
                f"פי {fmt.num_he(r, 1)} מיהודים ואחרים ({_p(j)}), סקר {ly}.")
        jt, at = te.get("יהודים ואחרים"), te.get("ערבים")
        if jt is not None and at is not None and jt - at >= 3:
            add("fear_terror", f"החשש מטרור הפוך: {_p(jt)} מהיהודים והאחרים חוששים מטרור באזור המגורים, "
                f"לעומת {_p(at)} בחברה הערבית (סקר {ly}).")

    # ── 11. change in sense of security by district ──
    di = L.get("district")
    if di:
        dists = [d for d, v in di["worse"].items() if v is not None]
        dists.sort(key=lambda d: (-di["worse"][d], d))
        flags["district"] = True
        charts["district"] = {"x": [_short(d) for d in dists],
                              "worse": [_r(di["worse"].get(d)) for d in dists],
                              "same": [_r(di.get("same", {}).get(d)) for d in dists],
                              "better": [_r(di.get("better", {}).get(d)) for d in dists]}
        tables["district"] = [[d, _p(di["worse"].get(d)), _p(di.get("same", {}).get(d)),
                               _p(di.get("better", {}).get(d))] for d in dists]
        labels["district_aria"] = f"תרשים עמודות נערמות: שינוי בתחושת הביטחון לעומת השנה הקודמת לפי מחוז, סקר {ly}"
        hist = history("district")
        labels["district_note"] = (f"האם תחושת הביטחון האישי השתנתה לעומת השנה הקודמת, לפי מחוז המגורים, סקר {ly}. "
                                   "המחוזות ממוינים לפי שיעור המדווחים על שינוי לרעה.")
        top_d = dists[0]
        add("district", f"{_where(top_d)} הדיווח הגבוה ביותר על שינוי לרעה בתחושת הביטחון לעומת השנה "
            f"הקודמת: {_p(di['worse'][top_d])}, לעומת {_p(di['worse'][dists[-1]])} {_where(dists[-1])} (סקר {ly}).")
        if len(hist) >= 2:
            flags["district_trend"] = True
            charts["district_trend"] = {"x": [_short(d) for d in dists],
                                        "series": [{"name": f"סקר {y}", "data": [_r(v["worse"].get(d)) for d in dists]}
                                                   for y, v in hist]}
            labels["district_trend_cols"] = ["מחוז"] + [f"סקר {y}" for y, _ in hist]
            tables["district_trend"] = [[d] + [_p(v["worse"].get(d)) for _, v in hist] for d in dists]
            labels["district_trend_aria"] = ("תרשים עמודות: אחוז המדווחים על שינוי לרעה בתחושת הביטחון לפי מחוז, "
                                             f"סקרי {fmt.join_he([str(y) for y, _ in hist])}")
            py, pv = hist[-2]
            both = [d for d in dists if pv["worse"].get(d) is not None]
            if both:
                avg_now = sum(di["worse"][d] for d in both) / len(both)
                avg_prev = sum(pv["worse"][d] for d in both) / len(both)
                if abs(avg_now - avg_prev) >= FLAT_PP:
                    word = "ירד" if avg_now < avg_prev else "עלה"
                    add("district_trend", f"שיעור המדווחים על שינוי לרעה בתחושת הביטחון {word} בכל המחוזות, "
                        f"ובממוצע המחוזות מ-{_p(avg_prev)} בסקר {py} ל-{_p(avg_now)} בסקר {ly}."
                        if all((di["worse"][d] < pv["worse"][d]) == (avg_now < avg_prev) for d in both) else
                        f"בממוצע המחוזות, שיעור המדווחים על שינוי לרעה בתחושת הביטחון {word} "
                        f"מ-{_p(avg_prev)} בסקר {py} ל-{_p(avg_now)} בסקר {ly}.")

    # ── insights order ──
    order = ("top", "change", "harass", "report", "dark", "fear_arab", "district_trend", "property",
             "online", "vharm", "children", "fear_terror", "district", "safety_trend", "safety_arab",
             "preport", "violence_sex")
    insights = sorted(cands, key=lambda i: order.index(i["id"]) if i["id"] in order else len(order))
    insights = insights[:MAX_INSIGHTS]

    # ── release card, lede, SEO ──
    release = {"no": rel["RELEASE_NO"], "title": rel["TITLE"], "headline": headline,
               "url": rel["PAGE_URL"], "pdf": rel["REPORT_PDF_URL"],
               "date": fmt.d_he(pd.Timestamp(rel["RELEASE_DATE"]))}
    yrs = sorted(set(years))
    labels["lede"] = ("כמה אנשים בישראל נפגעים מעבירות, מאילו עבירות, כמה מהם מדווחים למשטרה, ועד כמה "
                      "מרגישים בטוחים באזור המגורים. הנתונים מתוך סקר ביטחון אישי של הלשכה המרכזית "
                      f"לסטטיסטיקה (הלמ\"ס), ממצאים ראשונים מסקר {ly}"
                      + (f" בהשוואה לסקרי {fmt.join_he([str(y) for y in yrs[:-1]])}" if len(yrs) > 1 else "")
                      + (f". {_p(overall)} מבני 20 ומעלה נפגעו מעבירה כלשהי בשנה שקדמה לסקר."
                         if overall is not None else "."))
    labels["survey_years"] = fmt.join_he([str(y) for y in yrs])
    labels["latest_year"] = str(ly)

    summary = (f"סקר ביטחון אישי של הלמ\"ס, ממצאי סקר {ly}: "
               + (f"{_p(overall)} מבני 20 ומעלה נפגעו מעבירה, " if overall is not None else "")
               + (f"הנפוצה ביותר {top} ({_p(base[top])})" if top else "נתוני היפגעות מעבירות")
               + (f", ורק {_p(rep_total[1])} מהנפגעים דיווחו למשטרה" if rep_total and rep_total[1] is not None else "")
               + ". נתונים על עבירות רכוש, עבירות מקוונות, תחושת ביטחון וחשש מפשיעה ומטרור.")
    desc = (f"סקר ביטחון אישי {ly} של הלמ\"ס: "
            + (f"{_p(overall)} מבני 20 ומעלה נפגעו מעבירה" if overall is not None else "נפגעי עבירה")
            + (f", {_p(rep_total[1])} דיווחו למשטרה" if rep_total and rep_total[1] is not None else "")
            + ". סוגי עבירות, תחושת ביטחון וחשש מפשיעה לפי מין, אוכלוסייה ומחוז.")
    agent_data = {
        "summary_he": summary,
        "dataset_kind": "misc",
        "temporal_coverage": f"{yrs[0]}/{yrs[-1]}" if len(yrs) > 1 else str(ly),
        "spatial_coverage": "ישראל",
        "seo": {
            "title": "סקר ביטחון אישי: נפגעי עבירות ותחושת ביטחון",
            "description": desc,
            "name": "סקר ביטחון אישי של הלמ\"ס",
            "alternate_names": ["סקר ביטחון אישי", "סקר נפגעי עבירה", "נפגעי עבריינות בישראל",
                                "תחושת ביטחון אישי", "דיווח למשטרה על עבירות"],
        },
    }
    return {"agent_data": agent_data, "kpis": kpis, "charts": charts, "insights": insights,
            "labels": labels, "tables": tables, "flags": flags, "release": release}
