"""רשימת מוצרי מזון וחומרי גלם מיובאים: imported food products and raw
materials approved as kosher by the Chief Rabbinate of Israel.

The resource is a full snapshot of the current list ("... DD.MM.YYYY" in its
name), re-published as a whole; the recipe reads the newest matching resource
(`pick: "latest"`).

One row = one product on one import-kashrut certificate. Columns are opaque
(name1..name15); their meaning, from the values:
  name1 importer, name2 country of origin, name3 kashrut body abroad,
  name4 product (Hebrew), name5 product (foreign), name6 manufacturer
  ("עברית | LATIN"), name7 certificate number, name8 certificate expiry,
  name9 certificate issue date, name10 kashrut attributes (pipe-separated:
  פרווה / חלבי / כשר לפסח / השגחה צמודה ...), name11 lot code, name14
  production date, name12 serial / lot-number range, name15 product expiry,
  description label wording + certificate notes.

A handful of rows arrive column-shifted (a date in name3, garbage in name10);
dates that don't parse are left out of the date views, and junk attribute
tokens are filtered by a minimum frequency.

"Now" is the newest issue date in the data (no clock): a certificate whose
expiry is before it is counted as expired in this snapshot.

Everything is aggregated. Importers, manufacturers and kashrut bodies are
businesses/organisations and are named; no person data is present.
"""
import pandas as pd

MINUS = "−"
OTHER = "אחר"
MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני",
             "יולי", "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]

TOP_COUNTRY = 15
TOP_BODY = 12
TOP_IMPORTER = 15
TOP_MAKER = 15
HEAT_BODIES = 8
HEAT_COUNTRIES = 10
MIX_COUNTRIES = 12
TAG_MIN = 20          # an attribute token must appear this often to be a real label
TAG_TOP = 14
ISSUE_MONTHS = 48     # issue-date timeline window (months back from the newest issue)
HORIZON = 12          # expiry horizon in months
RECENT_MONTHS = 3

KIND_ORDER = ["פרווה", "חלבי", "בשרי", "לא צוין"]


def _int(n):
    return f"{int(n):,}"


def _pct(x, d=1):
    return f"{x * 100:.{d}f}%"


def _signed(v, d=1):
    s = f"{abs(v):.{d}f}"
    return (MINUS + s) if v < 0 else s


def _date(ts):
    return ts.strftime("%d/%m/%Y")


def _month_label(p):
    return f"{MONTHS_HE[p.month - 1]} {p.year}"


def _kpi(value, display, tone="brand"):
    return {"value": value, "display": display, "tone": tone}


def _counts(s):
    """value_counts with a total, deterministic order (count desc, name asc)."""
    vc = s.value_counts()
    df = vc.rename_axis("k").reset_index(name="n")
    df = df.sort_values(["n", "k"], ascending=[False, True], kind="mergesort")
    return df


def _tags(v):
    out = []
    for t in str(v).split("|"):
        t = t.strip()
        if t and t not in out:
            out.append(t)
    return out


def _kind(tags):
    if "בשרי" in tags:
        return "בשרי"
    if "חלבי" in tags or any("חלב" in t or "חמאת" in t for t in tags):
        return "חלבי"
    if "פרווה" in tags:
        return "פרווה"
    return "לא צוין"


def _pesach(tags):
    if "כשר לפסח קטניות" in tags:
        return "כשר לפסח (קטניות)"
    if "כשר לפסח" in tags:
        return "כשר לפסח"
    return "לא לפסח"


UNKNOWN = "לא צוין"
_DATE_RE = r"\d{1,2}/\d{1,2}/\d{4}"
_TAG_LEAK_RE = r"השגחה צמודה|לימות השנה"


def _plausible_name(s, allow_pipe=True):
    """A column-shifted row leaves dates, digit strings, lot codes or a tag list
    in the country/body cell; only a value with letters and none of those counts."""
    ok = (s.str.contains(r"[A-Za-z\u0590-\u05FF]", regex=True)
          & ~s.str.contains(_DATE_RE, regex=True)
          & ~s.str.contains(_TAG_LEAK_RE, regex=True)
          & ~s.str.startswith("|"))
    if not allow_pipe:
        ok &= ~s.str.contains("|", regex=False)
    return ok


def _prepare(df):
    df = df.copy()
    for c in df.columns:
        df[c] = df[c].astype(str).str.strip()
    df["importer"] = df["name1"]
    c_ok = _plausible_name(df["name2"], allow_pipe=False)
    b_ok = _plausible_name(df["name3"])
    df["country_bad"] = ~c_ok & (df["name2"] != "")
    df["body_bad"] = ~b_ok & (df["name3"] != "")
    df["country"] = df["name2"].where(c_ok, UNKNOWN)
    df["body"] = df["name3"].where(b_ok, UNKNOWN)
    df["maker"] = df["name6"].str.replace(r"\s+", " ", regex=True).str.strip()
    df["cert"] = df["name7"]
    df["issued"] = pd.to_datetime(df["name9"], format="%d/%m/%Y", errors="coerce")
    df["expires"] = pd.to_datetime(df["name8"], format="%d/%m/%Y", errors="coerce")
    df["taglist"] = df["name10"].map(_tags)
    df["kind"] = df["taglist"].map(_kind)
    df["pesach"] = df["taglist"].map(_pesach)
    df["lot"] = df["name11"] != ""
    df["prod_date"] = pd.to_datetime(df["name14"], format="%d/%m/%Y", errors="coerce")
    df["serial"] = df["name12"] != ""
    df["best_before"] = pd.to_datetime(df["name15"], format="%d/%m/%Y", errors="coerce")
    df["batch"] = df["lot"] | df["serial"] | df["prod_date"].notna() | df["best_before"].notna()
    desc = df["description"]
    df["label_text"] = desc.str.contains("נוסח תווית", regex=False)
    df["symbol_req"] = desc.str.contains("סמל הכשרות חייב", regex=False)
    df["origin_req"] = desc.str.contains("שם היצרן וארץ הייצור", regex=False)
    return df


def _topn(cnt, n):
    """Top-n rows of a _counts frame plus an "אחר" bucket (if anything left)."""
    head = cnt.head(n)
    rest = int(cnt["n"].iloc[n:].sum()) if len(cnt) > n else 0
    names = list(head["k"])
    vals = [int(v) for v in head["n"]]
    if rest:
        names.append(OTHER)
        vals.append(rest)
    return names, vals


def _maker_short(m):
    """Manufacturer cells are "עברית | LATIN": show the Hebrew half on axes."""
    part = m.split("|")[0].strip()
    return part or m


# ---------------------------------------------------------------- insights

def insight_country(country_cnt, total):
    if len(country_cnt) < 3 or total == 0:
        return None
    top = country_cnt.head(3)
    a, b, c = list(top["k"])
    va = int(top["n"].iloc[0])
    share3 = top["n"].sum() / total
    return (f"{a} היא ארץ המקור הגדולה ברשימה עם {_int(va)} מוצרים ({_pct(va / total)}). "
            f"יחד עם {b} ו{c} היא מרכזת {_pct(share3)} מהמוצרים, מתוך {_int(len(country_cnt))} מדינות מקור.")


def insight_body(body_cnt, total):
    if body_cnt.empty or total == 0:
        return None
    name, v = body_cnt["k"].iloc[0], int(body_cnt["n"].iloc[0])
    share = v / total
    if share < 0.15:
        return None
    second = body_cnt["n"].iloc[1] if len(body_cnt) > 1 else 0
    ratio = v / second if second else 0
    tail = f", פי {ratio:.1f} מהגוף השני בגודלו" if ratio >= 1.5 else ""
    return (f"גוף הכשרות המוביל הוא {name}: {_int(v)} מוצרים, {_pct(share)} מהרשימה{tail}. "
            f"בסך הכול פועלים ברשימה {_int(len(body_cnt))} גופי כשרות.")


def insight_importers(imp_cnt, total):
    if len(imp_cnt) < 20 or total == 0:
        return None
    top10 = imp_cnt["n"].head(10).sum() / total
    leader, lv = imp_cnt["k"].iloc[0], int(imp_cnt["n"].iloc[0])
    return (f"{_int(len(imp_cnt))} יבואנים רשומים, ועשרת הגדולים מחזיקים {_pct(top10)} מהמוצרים. "
            f"בראש: {leader} עם {_int(lv)} מוצרים.")


def insight_kind(kind_cnt, total):
    if total == 0:
        return None
    m = dict(zip(kind_cnt["k"], kind_cnt["n"]))
    pareve = m.get("פרווה", 0) / total
    dairy = m.get("חלבי", 0) / total
    meat = int(m.get("בשרי", 0))
    if pareve < 0.5:
        return None
    meat_txt = f" ורק {_int(meat)} מוצרים בשריים" if meat else " ואין ברשימה מוצרים בשריים"
    return (f"{_pct(pareve)} מהמוצרים המיובאים מסומנים פרווה, {_pct(dairy)} חלביים"
            f"{meat_txt}.")


def insight_pesach(pes_cnt, total):
    if total == 0:
        return None
    m = dict(zip(pes_cnt["k"], pes_cnt["n"]))
    p = int(m.get("כשר לפסח", 0))
    k = int(m.get("כשר לפסח (קטניות)", 0))
    if (p + k) / total < 0.05:
        return None
    return (f"{_int(p + k)} מוצרים ({_pct((p + k) / total)}) מאושרים כשרים לפסח, "
            f"מהם {_int(k)} לאוכלי קטניות בלבד.")


def insight_expired(n_expired, n_dated, anchor):
    if n_dated == 0 or anchor is None:
        return None
    share = n_expired / n_dated
    if share < 0.01:
        return None
    return (f"ל-{_int(n_expired)} מוצרים ({_pct(share)}) רשום תוקף אישור שהסתיים לפני "
            f"{_date(anchor)}, מועד האישור החדש ביותר ברשימה. מומלץ לבדוק את תוקף התעודה לפני הסתמכות עליה.")


def insight_wave(horizon_labels, horizon_vals, n_future):
    if not horizon_vals or n_future == 0:
        return None
    i = max(range(len(horizon_vals)), key=lambda j: (horizon_vals[j], -j))
    v = horizon_vals[i]
    if v / n_future < 0.08:
        return None
    return (f"החודש העמוס ביותר בחידושים ב-{_int(len(horizon_vals))} החודשים הקרובים: "
            f"ב{horizon_labels[i]} פג תוקף האישור של {_int(v)} מוצרים, "
            f"{_pct(v / n_future)} מהאישורים שעדיין בתוקף.")


def insight_recent(n_recent, n_dated, start, anchor):
    if n_dated == 0 or anchor is None:
        return None
    share = n_recent / n_dated
    if share < 0.1:
        return None
    return (f"הרשימה מתעדכנת ברציפות: {_pct(share)} מהמוצרים ({_int(n_recent)}) קיבלו את אישורם "
            f"בין {_date(start)} ל-{_date(anchor)}.")


def insight_dairy_country(mix_rows, overall_dairy):
    cand = [r for r in mix_rows if r["n"] >= 300]
    if not cand:
        return None
    best = sorted(cand, key=lambda r: (-r["dairy_share"], r["name"]))[0]
    if best["dairy_share"] < max(0.25, overall_dairy * 1.5):
        return None
    return (f"{best['name']} בולטת במוצרי חלב: {_pct(best['dairy_share'])} ממוצריה מסומנים חלביים, "
            f"לעומת {_pct(overall_dairy)} בכלל הרשימה.")


def insight_certs(n_certs, multi_share, max_items):
    if n_certs == 0:
        return None
    return (f"המוצרים רשומים על {_int(n_certs)} תעודות כשרות. {_pct(multi_share)} מהתעודות "
            f"מכסות יותר ממוצר אחד, ועד {_int(max_items)} מוצרים לתעודה.")


def insight_batch(n_batch, total):
    if total == 0:
        return None
    share = n_batch / total
    if share < 0.1:
        return None
    return (f"ב-{_pct(share)} מהרשומות ({_int(n_batch)}) האישור מפרט אצווה מסוימת: קוד אצווה, "
            f"תאריך ייצור או תפוגה, כלומר האישור מתייחס לאצווה מוגדרת.")


# ---------------------------------------------------------------- compute

def compute(frames):
    df = _prepare(frames["main"])
    total = len(df)

    # ---- country
    country_cnt = _counts(df["country"])
    real_country = country_cnt[country_cnt["k"] != UNKNOWN]
    n_countries = len(real_country)
    n_country_bad = int(df["country_bad"].sum())
    certs_by_country = df.groupby("country")["cert"].nunique()
    c_names, c_vals = _topn(country_cnt, TOP_COUNTRY)
    c_certs = []
    top_c = list(country_cnt["k"].head(TOP_COUNTRY))
    for nm in c_names:
        if nm == OTHER:
            c_certs.append(int(df.loc[~df["country"].isin(top_c), "cert"].nunique()))
        else:
            c_certs.append(int(certs_by_country.get(nm, 0)))
    country_table = [{"name": n, "n": _int(v), "share": _pct(v / total), "certs": _int(k)}
                     for n, v, k in zip(c_names, c_vals, c_certs)]

    # ---- kashrut body
    body_cnt = _counts(df["body"])
    real_body = body_cnt[body_cnt["k"] != UNKNOWN]
    n_bodies = len(real_body)
    n_body_bad = int(df["body_bad"].sum())
    b_names, b_vals = _topn(body_cnt, TOP_BODY)
    top_b = list(body_cnt["k"].head(TOP_BODY))
    b_countries = []
    for nm in b_names:
        sub = df[~df["body"].isin(top_b)] if nm == OTHER else df[df["body"] == nm]
        b_countries.append(int(sub["country"].nunique()))
    body_table = [{"name": n, "n": _int(v), "share": _pct(v / total), "countries": _int(k)}
                  for n, v, k in zip(b_names, b_vals, b_countries)]

    # ---- heat: body x country (share of each country's products)
    hb = list(real_body["k"].head(HEAT_BODIES))
    hc = list(real_country["k"].head(HEAT_COUNTRIES))
    cells, heat_rows, hmax = [], [], 0.0
    sub = df[df["country"].isin(hc)]
    ct = pd.crosstab(sub["body"], sub["country"])
    for yi, b in enumerate(hb):
        vals = []
        for xi, c in enumerate(hc):
            n = int(ct.at[b, c]) if (b in ct.index and c in ct.columns) else 0
            den = int(country_cnt.loc[country_cnt["k"] == c, "n"].iloc[0])
            sh = round(n / den * 100, 1) if den else 0.0
            hmax = max(hmax, sh)
            cells.append([xi, yi, sh, n])
            vals.append(f"{sh:.1f}%")
        heat_rows.append({"name": b, "vals": vals})
    # strongest body-country tie for the lede
    heat_lede = ""
    if cells:
        best = sorted(cells, key=lambda c: (-c[2], c[0], c[1]))[0]
        heat_lede = (f"החיבור החזק ביותר: {hb[best[1]]} משגיח על {best[2]:.1f}% מהמוצרים שמקורם ב{hc[best[0]]}. "
                     "כל תא מציג את שיעור המוצרים של המדינה שבפיקוח הגוף.")

    # ---- importers
    imp_cnt = _counts(df.loc[df["importer"] != "", "importer"])
    certs_by_imp = df.groupby("importer")["cert"].nunique()
    ctry_by_imp = df.groupby("importer")["country"].nunique()
    top_imp = imp_cnt.head(TOP_IMPORTER)
    importer_chart = {"y": list(top_imp["k"]), "n": [int(v) for v in top_imp["n"]],
                      "certs": [int(certs_by_imp.get(k, 0)) for k in top_imp["k"]],
                      "countries": [int(ctry_by_imp.get(k, 0)) for k in top_imp["k"]]}
    importer_table = [{"name": k, "n": _int(n), "certs": _int(c), "countries": _int(cc)}
                      for k, n, c, cc in zip(importer_chart["y"], importer_chart["n"],
                                             importer_chart["certs"], importer_chart["countries"])]

    # ---- manufacturers
    mk = df[df["maker"] != ""]
    maker_cnt = _counts(mk["maker"])
    ctry_by_maker = mk.groupby("maker")["country"].agg(
        lambda s: sorted(s.value_counts().items(), key=lambda kv: (-kv[1], kv[0]))[0][0])
    top_mk = maker_cnt.head(TOP_MAKER)
    maker_chart = {"y": [_maker_short(k) for k in top_mk["k"]], "full": list(top_mk["k"]),
                   "n": [int(v) for v in top_mk["n"]],
                   "country": [str(ctry_by_maker.get(k, "")) for k in top_mk["k"]]}
    maker_table = [{"name": f, "n": _int(n), "country": c}
                   for f, n, c in zip(maker_chart["full"], maker_chart["n"], maker_chart["country"])]

    # ---- kashrut kind + pesach
    kind_cnt = _counts(df["kind"])
    kmap = dict(zip(kind_cnt["k"], kind_cnt["n"]))
    kind_names = [k for k in KIND_ORDER if kmap.get(k, 0) > 0]
    kind_chart = {"data": [{"name": k, "value": int(kmap[k])} for k in kind_names]}
    pes_cnt = _counts(df["pesach"])
    pmap = dict(zip(pes_cnt["k"], pes_cnt["n"]))
    pes_order = [k for k in ["כשר לפסח", "כשר לפסח (קטניות)", "לא לפסח"] if pmap.get(k, 0) > 0]
    kind_table = ([{"group": "סוג", "name": k, "n": _int(kmap[k]), "share": _pct(kmap[k] / total)} for k in kind_names]
                  + [{"group": "פסח", "name": k, "n": _int(pmap[k]), "share": _pct(pmap[k] / total)} for k in pes_order])
    pes_chart = {"data": [{"name": k, "value": int(pmap[k])} for k in pes_order]}

    # ---- attribute tags
    tag_series = df["taglist"].explode()
    tag_series = tag_series[tag_series.notna() & (tag_series != "")]
    tag_cnt = _counts(tag_series)
    tag_cnt = tag_cnt[(tag_cnt["n"] >= TAG_MIN) & tag_cnt["k"].str.contains(r"[֐-׿]", regex=True)]
    tag_top = tag_cnt.head(TAG_TOP)
    tag_chart = {"y": list(tag_top["k"]), "n": [int(v) for v in tag_top["n"]],
                 "share": [round(v / total * 100, 1) for v in tag_top["n"]]}
    tag_table = [{"name": k, "n": _int(n), "share": f"{s:.1f}%"}
                 for k, n, s in zip(tag_chart["y"], tag_chart["n"], tag_chart["share"])]
    close = dict(zip(tag_cnt["k"], tag_cnt["n"])).get("השגחה צמודה", 0)

    # ---- dairy / pareve mix by country
    mix_c = list(real_country["k"].head(MIX_COUNTRIES))
    mix_series = {k: [] for k in KIND_ORDER}
    mix_rows = []
    for c in mix_c:
        s = df.loc[df["country"] == c, "kind"].value_counts()
        n = int(s.sum())
        for k in KIND_ORDER:
            mix_series[k].append(round(int(s.get(k, 0)) / n * 100, 1) if n else 0.0)
        mix_rows.append({"name": c, "n": n, "dairy_share": int(s.get("חלבי", 0)) / n if n else 0.0,
                         "pareve": _pct(int(s.get("פרווה", 0)) / n if n else 0),
                         "dairy": _pct(int(s.get("חלבי", 0)) / n if n else 0),
                         "pesach": _pct(int(((df["country"] == c) & (df["pesach"] != "לא לפסח")).sum()) / n if n else 0)})
    mix_kinds = [k for k in KIND_ORDER if any(v > 0 for v in mix_series[k])]
    mix_chart = {"y": mix_c, "series": [{"name": k, "data": mix_series[k]} for k in mix_kinds]}
    mix_table = [{"name": r["name"], "n": _int(r["n"]), "pareve": r["pareve"], "dairy": r["dairy"],
                  "pesach": r["pesach"]} for r in mix_rows]
    overall_dairy = kmap.get("חלבי", 0) / total if total else 0.0

    # ---- dates
    dated = df[df["issued"].notna()]
    anchor = dated["issued"].max() if len(dated) else None
    n_dated = len(dated)
    issue_chart = {"x": [], "n": [], "certs": []}
    n_before_window = 0
    recent_start = None
    n_recent = 0
    if anchor is not None:
        ap = anchor.to_period("M")
        first = max(dated["issued"].min().to_period("M"), ap - (ISSUE_MONTHS - 1))
        months = pd.period_range(first, ap, freq="M")
        per = dated["issued"].dt.to_period("M")
        by_m = per.value_counts()
        cert_m = dated.groupby(per)["cert"].nunique()
        issue_chart = {"x": [_month_label(p) for p in months],
                       "n": [int(by_m.get(p, 0)) for p in months],
                       "certs": [int(cert_m.get(p, 0)) for p in months]}
        n_before_window = int((per < first).sum())
        recent_start = (anchor - pd.DateOffset(months=RECENT_MONTHS)) + pd.Timedelta(days=1)
        n_recent = int((dated["issued"] >= recent_start).sum())
    issue_year = []
    if n_dated:
        yc = dated["issued"].dt.year.value_counts()
        yk = dated.groupby(dated["issued"].dt.year)["cert"].nunique()
        issue_year = [{"name": str(int(y)), "n": _int(yc[y]), "certs": _int(yk.get(y, 0))}
                      for y in sorted(yc.index)]
    peak_i = (max(range(len(issue_chart["n"])), key=lambda j: (issue_chart["n"][j], -j))
              if issue_chart["n"] else None)

    exp_ok = df[df["expires"].notna()]
    n_expired = int((exp_ok["expires"] < anchor).sum()) if anchor is not None else 0
    horizon_labels, horizon_vals = [], []
    n_later = 0
    n_future = 0
    if anchor is not None:
        fut = exp_ok[exp_ok["expires"] >= anchor]
        n_future = len(fut)
        ap = anchor.to_period("M")
        fper = fut["expires"].dt.to_period("M")
        months = pd.period_range(ap, ap + (HORIZON - 1), freq="M")
        fc = fper.value_counts()
        horizon_labels = [_month_label(p) for p in months]
        horizon_vals = [int(fc.get(p, 0)) for p in months]
        n_later = int((fper > months[-1]).sum())
    exp_chart = {"x": ["כבר פג"] + horizon_labels + ["מאוחר יותר"],
                 "n": [n_expired] + horizon_vals + [n_later]}
    exp_table = [{"name": x, "n": _int(v)} for x, v in zip(exp_chart["x"], exp_chart["n"])]

    # validity length (months between issue and expiry)
    both = df[df["issued"].notna() & df["expires"].notna()]
    days = (both["expires"] - both["issued"]).dt.days
    bad_dur = int(((days < 0) | (days > 365 * 5)).sum())
    days = days[(days >= 0) & (days <= 365 * 5)]
    bins = [(0, 182, "עד חצי שנה"), (183, 273, "6 עד 9 חודשים"), (274, 365, "9 עד 12 חודשים"),
            (366, 456, "12 עד 15 חודשים"), (457, 547, "15 עד 18 חודשים"), (548, 730, "18 עד 24 חודשים"),
            (731, 365 * 5, "מעל שנתיים")]
    dur_chart = {"x": [], "n": []}
    for lo, hi, lab in bins:
        dur_chart["x"].append(lab)
        dur_chart["n"].append(int(((days >= lo) & (days <= hi)).sum()))
    dur_table = [{"name": x, "n": _int(v), "share": _pct(v / len(days)) if len(days) else "0.0%"}
                 for x, v in zip(dur_chart["x"], dur_chart["n"])]
    med_months = float(days.median()) / 30.44 if len(days) else 0.0

    # products per certificate
    per_cert = df[df["cert"] != ""].groupby("cert").size()
    n_certs = int(len(per_cert))
    cbins = [(1, 1, "מוצר אחד"), (2, 2, "2"), (3, 3, "3"), (4, 5, "4 עד 5"), (6, 9, "6 עד 9"), (10, 10 ** 9, "10 ומעלה")]
    cert_chart = {"x": [], "n": []}
    for lo, hi, lab in cbins:
        cert_chart["x"].append(lab)
        cert_chart["n"].append(int(((per_cert >= lo) & (per_cert <= hi)).sum()))
    cert_table = [{"name": x, "n": _int(v), "share": _pct(v / n_certs) if n_certs else "0.0%"}
                  for x, v in zip(cert_chart["x"], cert_chart["n"])]
    multi_share = float((per_cert > 1).mean()) if n_certs else 0.0
    max_items = int(per_cert.max()) if n_certs else 0

    # batch-specific fields + certificate notes
    n_batch = int(df["batch"].sum())
    fields = [("קוד אצווה", int(df["lot"].sum())), ("תאריך ייצור", int(df["prod_date"].notna().sum())),
              ("תאריך תפוגה של המוצר", int(df["best_before"].notna().sum())),
              ("טווח מספרי אצווה", int(df["serial"].sum())),
              ("נוסח תווית מחייב", int(df["label_text"].sum())),
              ("חובת סמל הכשרות על האריזה", int(df["symbol_req"].sum())),
              ("חובת שם היצרן וארץ הייצור", int(df["origin_req"].sum()))]
    req_chart = {"y": [f[0] for f in fields], "n": [f[1] for f in fields],
                 "share": [round(f[1] / total * 100, 1) if total else 0.0 for f in fields],
                 "group": ["אצווה"] * 4 + ["הערות"] * 3}
    req_table = [{"name": f[0], "n": _int(f[1]), "share": f"{s:.1f}%"} for f, s in zip(fields, req_chart["share"])]

    # ---- KPIs
    exp_share = n_expired / len(exp_ok) if len(exp_ok) else 0.0
    exp_tone = "danger" if exp_share >= 0.2 else ("warn" if exp_share >= 0.05 else "ok")
    kpis = {
        "rows": _kpi(total, _int(total)),
        "countries": _kpi(n_countries, _int(n_countries)),
        "importers": _kpi(len(imp_cnt), _int(len(imp_cnt))),
        "bodies": _kpi(n_bodies, _int(n_bodies)),
        "makers": _kpi(len(maker_cnt), _int(len(maker_cnt))),
        "certs": _kpi(n_certs, _int(n_certs)),
        "expired": _kpi(round(exp_share * 100, 1), _pct(exp_share), exp_tone),
        "recent": _kpi(n_recent, _int(n_recent), "info"),
    }

    # ---- insights
    rules = [
        ("country", insight_country(real_country, total)),
        ("body", insight_body(real_body, total)),
        ("kind", insight_kind(kind_cnt, total)),
        ("pesach", insight_pesach(pes_cnt, total)),
        ("expired", insight_expired(n_expired, len(exp_ok), anchor)),
        ("wave", insight_wave(horizon_labels, horizon_vals, n_future)),
        ("recent", insight_recent(n_recent, n_dated, recent_start, anchor) if recent_start is not None else None),
        ("importers", insight_importers(imp_cnt, total)),
        ("dairy_country", insight_dairy_country(mix_rows, overall_dairy)),
        ("certs", insight_certs(n_certs, multi_share, max_items)),
        ("batch", insight_batch(n_batch, total)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    # ---- labels / ledes
    anchor_txt = _date(anchor) if anchor is not None else ""
    top_country = real_country["k"].iloc[0] if len(real_country) else ""
    top_body = real_body["k"].iloc[0] if len(real_body) else ""
    c_rest = max(len(country_cnt) - TOP_COUNTRY, 0)
    b_rest = max(len(body_cnt) - TOP_BODY, 0)
    labels = {
        "lede": (f"רשימת הרבנות הראשית לישראל של מוצרי מזון וחומרי גלם מיובאים בעלי אישור כשרות: "
                 f"{_int(total)} מוצרים מ-{_int(n_countries)} מדינות, של {_int(len(imp_cnt))} יבואנים, "
                 f"בפיקוח {_int(n_bodies)} גופי כשרות בחו״ל. לכל מוצר רשומים היבואן, היצרן, ארץ הייצור, "
                 f"גוף הכשרות, מספר התעודה ותוקפה."
                 + (f" האישור החדש ביותר ברשימה ניתן ב-{anchor_txt}." if anchor_txt else "")),
        "rows_kpi": "מוצרים ברשימה",
        "countries_kpi": "מדינות מקור",
        "importers_kpi": "יבואנים",
        "bodies_kpi": "גופי כשרות בחו״ל",
        "makers_kpi": "יצרנים",
        "certs_kpi": "תעודות כשרות",
        "expired_kpi": (f"מהמוצרים עם תוקף אישור שהסתיים לפני {anchor_txt}" if anchor_txt
                        else "מהמוצרים עם תוקף אישור שהסתיים"),
        "recent_kpi": f"מוצרים שאושרו בשלושת החודשים האחרונים (עד {anchor_txt})",
        "country_note": (f"{top_country} מובילה. המדינות מוצגות לפי מספר המוצרים"
                         + (f"; שאר {_int(c_rest)} המדינות מקובצות תחת אחר." if c_rest else ".")
                         + (f" {_int(n_country_bad)} רשומות שבהן שדה ארץ המקור אינו שם מדינה (למשל תאריך או מספר) "
                            "נספרות תחת לא צוין." if n_country_bad else "")),
        "country_aria": f"מספר המוצרים המיובאים לפי ארץ מקור, {_int(min(TOP_COUNTRY, len(country_cnt)))} המדינות המובילות",
        "body_note": (f"{top_body} מוביל. גוף הכשרות הוא הגוף בחו״ל שמשגיח על הייצור; הרבנות הראשית מאשרת את השגחתו."
                      + (f" שאר {_int(b_rest)} הגופים מקובצים תחת אחר." if b_rest else "")
                      + (f" {_int(n_body_bad)} רשומות שבהן שדה גוף הכשרות אינו שם גוף (למשל תאריך או מספר) "
                         "נספרות תחת לא צוין." if n_body_bad else "")),
        "body_aria": f"מספר המוצרים לפי גוף הכשרות, {_int(min(TOP_BODY, len(body_cnt)))} הגופים המובילים",
        "heat_note": heat_lede,
        "heat_aria": "מפת חום: שיעור המוצרים של כל מדינת מקור לפי גוף הכשרות",
        "importer_note": (f"{importer_chart['y'][0] if importer_chart['y'] else ''} מוביל עם "
                          f"{_int(importer_chart['n'][0]) if importer_chart['n'] else '0'} מוצרים. "
                          "בתיבת המידע: מספר התעודות ומספר מדינות המקור של כל יבואן."),
        "importer_aria": "היבואנים עם מספר המוצרים הגדול ביותר ברשימה",
        "maker_note": (f"היצרן הגדול ברשימה הוא {maker_chart['y'][0] if maker_chart['y'] else ''} "
                       f"({maker_chart['country'][0] if maker_chart['country'] else ''}) עם "
                       f"{_int(maker_chart['n'][0]) if maker_chart['n'] else '0'} מוצרים."),
        "maker_aria": "היצרנים בחו״ל עם מספר המוצרים הגדול ביותר",
        "kind_note": (f"{_pct(kmap.get('פרווה', 0) / total) if total else '0.0%'} מהמוצרים פרווה. "
                      "מוצר המסומן לאוכלי אבקת חלב נוכרי או חמאת נוכרי נספר כחלבי."),
        "kind_aria": "התפלגות המוצרים לפי סוג הכשרות: פרווה, חלבי, בשרי",
        "pes_aria": "התפלגות המוצרים לפי כשרות לפסח",
        "tag_note": (f"כל מוצר נושא כמה סימונים. השגחה צמודה מופיעה ב-{_pct(close / total) if total else '0.0%'} "
                     "מהמוצרים. מוצגים הסימונים הנפוצים בלבד."),
        "tag_aria": "שיעור המוצרים הנושאים כל סימון כשרות",
        "mix_note": (f"שיעור החלבי, הפרווה והבשרי בכל אחת מ-{_int(len(mix_c))} מדינות המקור הגדולות. "
                     f"בכלל הרשימה {_pct(overall_dairy)} מהמוצרים חלביים."),
        "mix_aria": "תמהיל סוגי הכשרות בכל מדינת מקור",
        "issue_note": ((f"מועד ההנפקה של האישורים שברשימה, לפי חודש. החודש העמוס: {issue_chart['x'][peak_i]} "
                        f"עם {_int(issue_chart['n'][peak_i])} מוצרים. הרשימה כוללת רק אישורים שעדיין רשומים, "
                        "ולכן החודשים המוקדמים דלילים.")
                       if peak_i is not None else "")
                      + (f" {_int(n_before_window)} מוצרים שאושרו לפני תחילת הציר אינם מוצגים." if n_before_window else ""),
        "issue_aria": "מספר המוצרים לפי חודש הנפקת אישור הכשרות",
        "exp_note": (f"מתי פג תוקף האישורים, ביחס ל-{anchor_txt}, מועד האישור החדש ביותר ברשימה. "
                     f"{_int(n_expired)} מוצרים רשומים עם תוקף שכבר עבר." if anchor_txt else ""),
        "exp_aria": "מספר המוצרים לפי חודש פקיעת תוקף האישור",
        "dur_note": (f"משך התוקף החציוני של אישור הוא {med_months:.1f} חודשים."
                     + (f" {_int(bad_dur)} רשומות עם תאריכים לא סבירים הושמטו." if bad_dur else "")),
        "dur_aria": "התפלגות משך התוקף של אישורי הכשרות",
        "cert_note": (f"{_int(n_certs)} תעודות. {_pct(multi_share)} מהן מכסות יותר ממוצר אחד, "
                      f"והגדולה מכסה {_int(max_items)} מוצרים."),
        "cert_aria": "התפלגות התעודות לפי מספר המוצרים שהן מכסות",
        "req_note": (f"{_pct(n_batch / total) if total else '0.0%'} מהרשומות כוללות פרט אצווה אחד לפחות, "
                     "כלומר האישור מתייחס לאצווה מוגדרת. השורות התחתונות: דרישות מתוך הערות התעודה."),
        "req_aria": "שיעור הרשומות הכוללות פרטי אצווה ודרישות סימון",
        "anchor": anchor_txt,
    }

    summary = (f"איתור מוצר מזון מיובא כשר לפי שם, יבואן, יצרן או מספר תעודה: "
               f"{_int(total)} מוצרים מ-{_int(n_countries)} מדינות באישור הרבנות הראשית.")
    if len(summary) > 155:
        summary = f"איתור מוצר מזון מיובא כשר לפי שם, יבואן או יצרן: {_int(total)} מוצרים באישור הרבנות."

    temporal = None
    if anchor is not None and len(dated):
        temporal = f"{dated['issued'].min().year}/{anchor.year}"

    agent_data = {
        "summary_he": summary,
        "dataset_kind": "registry",
        "suggested_tags": ["כשרות", "מזון כשר", "יבוא", "מוצרי מזון", "חומרי גלם"],
        "related_ids": ["6a8f3548-f991-4f8b-ab52-80240324ab4d", "e6ef4310-746f-4504-867b-804520401755"],
    }
    if temporal:
        agent_data["temporal_coverage"] = temporal

    return {
        "agent_data": agent_data,
        "kpis": kpis,
        "charts": {
            "country": {"y": c_names, "n": c_vals, "certs": c_certs},
            "body": {"y": b_names, "n": b_vals, "countries": b_countries},
            "heat": {"x": hc, "y": hb, "cells": cells, "max": round(hmax, 1)},
            "importer": importer_chart,
            "maker": maker_chart,
            "kind": kind_chart,
            "pesach": pes_chart,
            "tags": tag_chart,
            "mix": mix_chart,
            "issue": issue_chart,
            "expiry": exp_chart,
            "dur": dur_chart,
            "certs": cert_chart,
            "req": req_chart,
        },
        "tables": {
            "country": country_table, "body": body_table, "heat": heat_rows, "heat_cols": hc,
            "importer": importer_table, "maker": maker_table, "issue_year": issue_year, "kind": kind_table,
            "tags": tag_table, "mix": mix_table, "expiry": exp_table, "dur": dur_table,
            "certs": cert_table, "req": req_table,
        },
        "insights": insights,
        "labels": labels,
    }
