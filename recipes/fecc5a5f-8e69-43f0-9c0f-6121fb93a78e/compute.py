"""מדבירים מורשים — the Ministry of Environmental Protection's register of
licensed exterminators, one row per licence (a person holding two licence
types under one licence number appears twice).

The page is about licences, not people: licence type, where the holders
live (settlement only), when licences expire, and how licence numbers spread
across types. Names, phone numbers and licence numbers never reach the page;
the licence number is used only in aggregate (bands, medians).

No wall clock: expiry dates are described as a distribution, never as
"expired" or "expiring soon" relative to today.
"""
import re

import pandas as pd

LIC = "LicenseNumber"
CITY = "settlement"
TYPE = "LicenseType"
STATUS = "Status"
EXPIRY = "PermitExpirationDate"
SUSP_START = "suspension_start_date"
CANCEL = "Cancel_date"
SANCTION = "FinancialSanction"

UNSPEC = "לא צוין"
OTHER = "אחר"
IN_FORCE = "בתוקף"
CANCELLED = "מבוטל"

F_FULL = "מבנים ושטח פתוח"
F_APT = "דירות"
F_FUM = "איוד"
F_LIM = "מבנים ושטח פתוח (מוגבל)"
F_SPEC = "היתרים מיוחדים"
F_MIL = "צבאי"

TOP_CITIES = 15
MIN_CITY_MIX = 30          # a settlement needs this many licences for the mix insight
MIN_FAMILY_SENIORITY = 20  # a family needs this many licences for the seniority insight
LEAD_TYPE_SHARE = 0.30
WAVE_SHARE = 0.10
TOP10_SHARE = 0.20
MIX_SPREAD = 0.20
SENIORITY_RATIO = 0.67
BUCKETS = [(1, 1), (2, 4), (5, 9), (10, 24), (25, 49), (50, None)]
BAND_WIDTHS = [250, 500, 1000, 2000, 5000, 10000]
MAX_BANDS = 12
FAM_PAL = [0, 1, 2, 6, 5, 9, 3, 7, 4, 8]   # GOVIL_PALETTE indices, alternating light/dark

LRI, PDI = "⁦", "⁩"
MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]
MONTHS_SHORT = ["ינו׳", "פבר׳", "מרץ", "אפר׳", "מאי", "יוני", "יולי",
                "אוג׳", "ספט׳", "אוק׳", "נוב׳", "דצמ׳"]


def n(v):
    return f"{int(v):,}"


def pct(v, digits=1):
    return f"{LRI}{pct_bare(v, digits)}{PDI}"


def pct_bare(v, digits=1):
    """A share that is not exactly 0 or 1 never rounds to '0%' / '100%'."""
    s = f"{v * 100:.{digits}f}"
    while 0 < v < 1 and float(s) in (0.0, 100.0) and digits < 4:
        digits += 1
        s = f"{v * 100:.{digits}f}"
    return f"{s}%"


def lics(k, pre=""):
    """'רישיון אחד' / '12 רישיונות', optional ב/ל prefix (hyphen before digits)."""
    if int(k) == 1:
        return f"{pre}רישיון אחד"
    return f"{pre}{'-' if pre else ''}{n(k)} רישיונות"


def ranked(counts):
    """Descending by value, ties by label — a total, shuffle-proof order."""
    return counts.sort_index().sort_values(ascending=False, kind="stable")


def norm_city(raw):
    s = re.sub(r"\s+", " ", raw.strip())
    s = re.sub(r"\s*-\s*", "-", s)
    return s or UNSPEC


def short_type(raw):
    s = re.sub(r"\s+", " ", raw.strip())
    if not s:
        return UNSPEC
    s = re.sub(r"^רישיון\s+", "", s)
    m = re.match(r"^מדביר במבנים ובשטח פתוח מוגבל ל(.+)$", s)
    if m:
        return f"{F_FULL}, מוגבל ל{m.group(1)}"
    s = re.sub(r"\s+-\s+", ": ", s)
    return s


def family(raw):
    s = raw.strip()
    if not s:
        return UNSPEC
    if "מוגבל" in s:
        return F_LIM
    if "היתר מיוחד" in s:
        return F_SPEC
    if "צבאי" in s:
        return F_MIL
    if "איוד" in s:
        return F_FUM
    if "דירות" in s:
        return F_APT
    if "מבנים" in s:
        return F_FULL
    return OTHER


def month_he(period):
    return f"{MONTHS_HE[period.month - 1]} {period.year}"


def stacked(df, col, names, fams):
    ct = df.groupby([col, "fam"]).size()
    return {"names": list(names),
            "series": [{"name": f, "data": [int(ct.get((nm, f), 0)) for nm in names]} for f in fams]}


def median_int(s):
    v = s.sort_values(kind="stable").reset_index(drop=True)
    if not len(v):
        return None
    k = len(v)
    return int(v.iloc[(k - 1) // 2]) if k % 2 else int(round((v.iloc[k // 2 - 1] + v.iloc[k // 2]) / 2))


# ── insights ──────────────────────────────────────────────────────────────

def insight_status(total, in_force, cancelled, suspended, sanctioned, cancel_dated_active):
    if total == 0:
        return None
    parts = [f"{n(in_force)} מתוך {n(total)} הרישיונות במאגר ({pct(in_force / total)}) בתוקף"]
    if cancelled == 0:
        parts.append("אף רישיון אינו מסומן כמבוטל")
    elif cancelled == 1:
        parts.append("רישיון אחד מסומן כמבוטל")
    else:
        parts.append(f"{n(cancelled)} מסומנים כמבוטלים")
    parts.append("אין רישיונות מושעים" if suspended == 0 else
                 ("רישיון אחד מושעה" if suspended == 1 else f"{n(suspended)} מושעים"))
    txt = ", ".join(parts[:-1]) + " ו" + parts[-1]
    if sanctioned:
        txt += f"; {lics(sanctioned, 'ל')} מצוין עיצום כספי"
    if cancel_dated_active:
        txt += (f"; {lics(cancel_dated_active, 'ל')} שבתוקף רשום גם תאריך ביטול קודם"
                if cancel_dated_active > 1 else "; לרישיון אחד שבתוקף רשום גם תאריך ביטול קודם")
    return txt + "."


def insight_types(type_counts, total):
    if total == 0 or type_counts.empty:
        return None
    r = ranked(type_counts)
    lead, cnt = r.index[0], int(r.iloc[0])
    if cnt / total < LEAD_TYPE_SHARE:
        return None
    rest = ""
    if len(r) >= 3:
        rest = (f"; אחריו \"{r.index[1]}\" ({n(r.iloc[1])}) ו\"{r.index[2]}\" ({n(r.iloc[2])})")
    elif len(r) == 2:
        rest = f"; אחריו \"{r.index[1]}\" ({n(r.iloc[1])})"
    return (f"סוג הרישיון הנפוץ ביותר הוא \"{lead}\": {n(cnt)} רישיונות ({pct(cnt / total)}){rest}.")


def insight_wave(months, dated, df_dated, fam_order):
    if dated < 20 or len(months) < 2:
        return None
    r = ranked(months)
    peak, cnt = r.index[0], int(r.iloc[0])
    if cnt / dated < WAVE_SHARE:
        return None
    second, c2 = r.index[1], int(r.iloc[1])
    fam_c = ranked(df_dated.loc[df_dated["ym"] == peak, "fam"].value_counts())
    fam_txt = ""
    if len(fam_c):
        f0, k0 = fam_c.index[0], int(fam_c.iloc[0])
        fam_txt = f", רובם ({n(k0)}) רישיונות {f0}" if k0 / cnt > 0.5 else f", בעיקר רישיונות {f0} ({n(k0)})"
    ratio = cnt / c2 if c2 else None
    rtxt = f", פי {ratio:.1f} מהחודש השני בגודלו ({month_he(second)}, {n(c2)})" if ratio and ratio >= 1.5 else ""
    return (f"גל פקיעה מרוכז: {n(cnt)} רישיונות ({pct(cnt / dated)} מהרישיונות עם תאריך תקין) פוקעים ב{month_he(peak)}"
            f"{fam_txt}{rtxt}. זה עומס חידוש צפוי סביב אותו חודש.")


def insight_concentration(city_counts, total):
    named = ranked(city_counts.drop(labels=[UNSPEC], errors="ignore"))
    if len(named) < 10 or total == 0:
        return None
    top10 = int(named.iloc[:10].sum())
    if top10 / total < TOP10_SHARE:
        return None
    single = int((named == 1).sum())
    t3 = ", ".join(f"{c} ({n(v)})" for c, v in named.iloc[:3].items())
    return (f"ריכוז גיאוגרפי: שלושת היישובים המובילים הם {t3}, ועשרת המובילים יחד מחזיקים "
            f"{pct(top10 / total)} מהרישיונות, בעוד {n(single)} מתוך {n(len(named))} יישובים מונים רישיון אחד בלבד.")


def insight_city_mix(df, fam_counts, total):
    vc = df[CITY].value_counts()
    big = sorted(c for c, v in vc.items() if v >= MIN_CITY_MIX and c != UNSPEC)
    if len(big) < 3 or total == 0:
        return None
    sub = df[df[CITY].isin(big)]
    ct = sub.groupby([CITY, "fam"]).size()
    tot = sub.groupby(CITY).size()
    best = None
    for f in sorted(fam_counts.index):
        if f in (OTHER, UNSPEC) or fam_counts[f] / total < 0.10:
            continue
        shares = {c: ct.get((c, f), 0) / tot[c] for c in big}
        order = sorted(big, key=lambda c: (-shares[c], -int(tot[c]), c))
        hi, lo = order[0], order[-1]
        spread = shares[hi] - shares[lo]
        key = (-spread, f)
        if best is None or key < best[0]:
            best = (key, f, hi, lo, shares[hi], shares[lo])
    if best is None or -best[0][0] < MIX_SPREAD:
        return None
    _, f, hi, lo, sh, sl = best
    return (f"התמהיל משתנה בין הערים: רישיונות {f} הם {pct(sh, 0)} מהרישיונות של תושבי {hi} "
            f"לעומת {pct(sl, 0)} ב{lo} (בין {n(len(big))} היישובים עם {n(MIN_CITY_MIX)} רישיונות לפחות).")


def insight_seniority(df):
    ln = df.dropna(subset=["ln"])
    fc = ln["fam"].value_counts()
    elig = sorted(f for f, v in fc.items() if v >= MIN_FAMILY_SENIORITY and f not in (OTHER, UNSPEC))
    if len(elig) < 2:
        return None
    med = {f: median_int(ln.loc[ln["fam"] == f, "ln"]) for f in elig}
    order = sorted(elig, key=lambda f: (med[f], f))
    lo, hi = order[0], order[-1]
    if med[hi] == 0 or med[lo] / med[hi] > SENIORITY_RATIO:
        return None
    s = ln["ln"].sort_values(kind="stable").reset_index(drop=True)
    q = int(s.iloc[(3 * (len(s) - 1)) // 4])
    top = ln[ln["ln"] > q]
    if not len(top):
        return None
    tf = ranked(top["fam"].value_counts())
    tname, tcnt = tf.index[0], int(tf.iloc[0])
    return (f"רישיונות {lo} נושאים את מספרי הרישיון הנמוכים ביותר (חציון {n(med[lo])}), ורישיונות {hi} "
            f"את הגבוהים ביותר (חציון {n(med[hi])}). ברבע העליון של מספרי הרישיון (מעל {n(q)}), "
            f"{pct(tcnt / len(top), 0)} הם רישיונות {tname}. אם המספרים מוקצים בסדר עולה, "
            f"זה מסלול הכניסה העיקרי של המצטרפים החדשים.")


def insight_multi(df):
    g = df[df["ln"].notna()].groupby("ln")["stype"].apply(lambda s: tuple(sorted(set(s))))
    multi = g[g.map(len) >= 2]
    if len(multi) < 2:
        return None
    combos = ranked(multi.map(lambda t: " + ".join(t)).value_counts())
    c0, k0 = combos.index[0], int(combos.iloc[0])
    tail = (", כולם באותו צירוף" if k0 == len(multi) else f"; הצירוף הנפוץ ({n(k0)}): {c0}")
    lead = f"{n(len(multi))} מדבירים מחזיקים יותר מסוג רישיון אחד תחת אותו מספר רישיון"
    if k0 == len(multi):
        return f"{lead}: {c0}{tail}."
    return f"{lead}{tail}."


# ── compute ───────────────────────────────────────────────────────────────

def compute(frames):
    df = frames["main"].copy()
    for c in [LIC, CITY, TYPE, STATUS, EXPIRY, SUSP_START, CANCEL, SANCTION]:
        df[c] = df[c].astype(str).str.strip()
    df = df.sort_values([LIC, TYPE, CITY, EXPIRY, STATUS, CANCEL], kind="stable").reset_index(drop=True)
    total = len(df)

    df[CITY] = df[CITY].map(norm_city)
    df["stype"] = df[TYPE].map(short_type)
    df["fam"] = df[TYPE].map(family)
    df["ln"] = pd.to_numeric(df[LIC].str.replace(",", "", regex=False), errors="coerce")

    fam_counts = df["fam"].value_counts()
    fams = [f for f in ranked(fam_counts).index if f not in (OTHER, UNSPEC)]
    fams += [f for f in (OTHER, UNSPEC) if f in fam_counts]
    type_counts = df["stype"].value_counts()
    type_order = list(ranked(type_counts).index)
    type_fam = {t: ranked(df.loc[df["stype"] == t, "fam"].value_counts()).index[0] for t in type_order}
    type_chart = {"names": type_order, "values": [int(type_counts[t]) for t in type_order],
                  "fam_idx": [fams.index(type_fam[t]) for t in type_order]}

    # status
    in_force = int((df[STATUS] == IN_FORCE).sum())
    cancelled = int((df[STATUS] == CANCELLED).sum())
    suspended = int((df[SUSP_START] != "").sum())
    sanctioned = int((df[SANCTION] != "").sum())
    cancel_dated_active = int(((df[CANCEL] != "") & (df[STATUS] == IN_FORCE)).sum())

    # expiry
    exp = pd.to_datetime(df[EXPIRY], format="%d/%m/%Y", errors="coerce")
    exp = exp.where(exp.dt.year < 2200)
    df["exp"] = exp
    dated_df = df[df["exp"].notna()].copy()
    dated = len(dated_df)
    no_date = total - dated
    bad_date = int(((df[EXPIRY] != "") & df["exp"].isna()).sum())
    dated_df["ym"] = dated_df["exp"].dt.to_period("M")
    dated_df["y"] = dated_df["exp"].dt.year.astype(int)
    months = dated_df["ym"].value_counts()
    if dated:
        y0, y1 = int(dated_df["y"].min()), int(dated_df["y"].max())
        ycount = dated_df["y"].value_counts()
        years = sorted(int(y) for y in ycount.index)   # years present (an outlier year leaves no empty run)
        exp_year = stacked(dated_df, "y", years, fams)
        exp_year["names"] = [str(y) for y in years]
        exp_year["totals"] = [int(ycount.get(y, 0)) for y in years]
        peak_year = int(ranked(ycount).index[0])
        peak_year_n = int(ycount[peak_year])
        heat_years = sorted(int(y) for y in ycount.index)
        mc = dated_df.groupby(["y", dated_df["exp"].dt.month]).size()
        cells = [[m - 1, yi, int(mc[(y, m)])] for yi, y in enumerate(heat_years)
                 for m in range(1, 13) if (y, m) in mc.index]
        heat = {"x": MONTHS_SHORT, "y": [str(y) for y in heat_years], "cells": cells,
                "max": max((c[2] for c in cells), default=1)}
        first_m = months.sort_index().index[0]
        last_m = months.sort_index().index[-1]
    else:
        y0 = y1 = peak_year = None
        peak_year_n = 0
        exp_year = {"names": [], "series": [], "totals": []}
        heat = {"x": MONTHS_SHORT, "y": [], "cells": [], "max": 1}
        first_m = last_m = None

    # settlements
    city_counts = df[CITY].value_counts()
    named_c = ranked(city_counts.drop(labels=[UNSPEC], errors="ignore"))
    n_cities = len(named_c)
    top_c = list(named_c.index[:TOP_CITIES])
    city_chart = stacked(df, CITY, top_c, fams)
    top_c_share = int(named_c.iloc[:TOP_CITIES].sum()) / total if total else 0
    single_cities = int((named_c == 1).sum())

    bucket_rows = []
    for lo, hi in BUCKETS:
        sel = named_c[(named_c >= lo) & ((named_c <= hi) if hi is not None else True)]
        if lo == hi:
            lab = "רישיון אחד" if lo == 1 else f"{lo} רישיונות"
        elif hi is None:
            lab = f"{lo} ומעלה"
        else:
            lab = f"{lo} עד {hi}"
        bucket_rows.append({"name": lab, "cities": int(len(sel)), "lics": int(sel.sum())})
    spread_chart = {"names": [b["name"] for b in bucket_rows],
                    "cities": [b["cities"] for b in bucket_rows],
                    "lics": [b["lics"] for b in bucket_rows]}

    # licence-number bands
    ln_ok = df[df["ln"].notna() & (df["ln"] > 0)]
    if len(ln_ok):
        lmax = int(ln_ok["ln"].max())
        width = next((w for w in BAND_WIDTHS if lmax // w + 1 <= MAX_BANDS), BAND_WIDTHS[-1])
        nb = lmax // width + 1
        b = (ln_ok["ln"] // width).astype(int)
        band_names = [f"{max(i * width, 1):,} עד {(i + 1) * width - 1:,}" for i in range(nb)]
        ln_ok = ln_ok.assign(band=b.map(lambda i: band_names[i]))
        band_chart = stacked(ln_ok, "band", band_names, fams)
    else:
        width = None
        band_chart = {"names": [], "series": []}
    fam_median = {f: median_int(ln_ok.loc[ln_ok["fam"] == f, "ln"]) for f in fams
                  if (ln_ok["fam"] == f).any()}

    # licence-holders
    n_holders = int(df["ln"].dropna().nunique()) + int(df["ln"].isna().sum())
    multi = df[df["ln"].notna()].groupby("ln")["stype"].nunique()
    n_multi = int((multi >= 2).sum())

    # ── KPIs
    peak_share = peak_year_n / dated if dated else 0
    in_share = in_force / total if total else 0
    kpis = {
        "licences": {"value": total, "display": n(total), "tone": "brand"},
        "holders": {"value": n_holders, "display": n(n_holders), "tone": "brand"},
        "in_force": {"value": in_force, "display": n(in_force),
                     "tone": "ok" if in_share >= 0.98 else ("warn" if in_share >= 0.9 else "danger")},
        "cities": {"value": n_cities, "display": n(n_cities), "tone": "brand"},
        "single": {"value": single_cities, "display": n(single_cities), "tone": "info"},
        "peak_year": {"value": peak_year_n, "display": n(peak_year_n),
                      "tone": "warn" if peak_share >= 0.4 else "brand"},
    }

    insights = []
    for iid, txt in [
        ("status", insight_status(total, in_force, cancelled, suspended, sanctioned, cancel_dated_active)),
        ("types", insight_types(type_counts, total)),
        ("wave", insight_wave(months, dated, dated_df, fams)),
        ("concentration", insight_concentration(city_counts, total)),
        ("city_mix", insight_city_mix(df, fam_counts, total)),
        ("seniority", insight_seniority(df)),
        ("multi", insight_multi(df)),
    ]:
        if txt:
            insights.append({"id": iid, "text_he": txt})

    # ── labels
    date_note = ""
    if no_date:
        date_note = (f" {lics(no_date, 'ל')} אין תאריך תוקף תקין"
                     + (f" (בהם {n(bad_date)} עם שנה שגויה, כמו 3030)" if bad_date else "")
                     + " והם אינם מוצגים.")
    lead_type = type_order[0] if type_order else None
    labels = {
        "lede": (f"מרשם המדבירים המורשים של המשרד להגנת הסביבה מונה {n(total)} רישיונות של {n(n_holders)} מדבירים, "
                 f"תושבי {n(n_cities)} יישובים. {n(in_force)} מהרישיונות בתוקף. העמוד מפרק את המרשם לפי סוג הרישיון, "
                 f"יישוב המגורים, מועד פקיעת התוקף ומספרי הרישיון; פרטי הקשר של כל מדביר זמינים בטבלת הנתונים "
                 f"שבתחתית העמוד."),
        "licences_kpi": "רישיונות במאגר",
        "holders_kpi": "מדבירים (מספרי רישיון)",
        "in_force_kpi": "רישיונות בתוקף",
        "cities_kpi": "יישובים",
        "single_kpi": "יישובים עם מדביר יחיד",
        "peak_year_kpi": (f"רישיונות שפוקעים ב-{peak_year}" if peak_year else "רישיונות בשנת הפקיעה המובילה"),
        "types_note": (f"{n(len(type_order))} סוגי רישיון. "
                       + (f"הנפוץ: \"{lead_type}\" ({n(type_counts[lead_type])}). " if lead_type else "")
                       + "רישיון מבנים ושטח פתוח הוא הרחב; רישיון דירות מוגבל להדברה בתוך דירות מגורים; "
                         "רישיון איוד מתיר הדברה בגזים."),
        "types_aria": f"תרשים עמודות של מספר הרישיונות לפי סוג רישיון, {n(len(type_order))} סוגים",
        "types_caption": "רישיונות לפי סוג",
        "year_note": ((f"שנת פקיעת התוקף של כל רישיון לפי משפחת רישיון (מוצגות השנים שבהן פוקע רישיון אחד לפחות). "
                       f"הפקיעה המוקדמת במאגר: {month_he(first_m)}; המאוחרת: {month_he(last_m)}." if dated else "")
                      + date_note),
        "year_aria": (f"תרשים עמודות מוערמות של מספר הרישיונות לפי שנת פקיעה, {y0}–{y1}" if dated
                      else "תרשים עמודות של שנת פקיעת הרישיון"),
        "year_caption": "רישיונות לפי שנת פקיעה ומשפחת רישיון",
        "heat_note": (f"מספר הרישיונות שפוקעים בכל חודש; חודשים כהים הם גלי חידוש."
                      + (f" החודש העמוס: {month_he(ranked(months).index[0])} "
                         f"({n(ranked(months).iloc[0])} רישיונות)." if dated else "")),
        "heat_aria": f"מפת חום של פקיעת רישיונות לפי חודש ושנה, {n(len(heat['y']))} שנים",
        "cities_note": (f"{n(len(top_c))} היישובים עם מספר הרישיונות הגדול ביותר, לפי יישוב המגורים של המדביר, "
                        f"מתוך {n(n_cities)}; יחד {pct(top_c_share)} מהרישיונות."),
        "cities_aria": f"תרשים עמודות מוערמות של מספר הרישיונות ב-{n(len(top_c))} היישובים המובילים לפי משפחת רישיון",
        "cities_caption": "רישיונות לפי יישוב ומשפחת רישיון",
        "spread_note": (f"כמה יישובים יש בכל גודל (לפי מספר הרישיונות של תושביהם), וכמה רישיונות הם מחזיקים יחד. "
                        f"{n(single_cities)} יישובים מונים רישיון אחד בלבד."),
        "spread_aria": f"תרשים עמודות של מספר היישובים ומספר הרישיונות לפי גודל יישוב, {n(len(bucket_rows))} קבוצות",
        "spread_caption": "יישובים ורישיונות לפי מספר הרישיונות ביישוב",
        "bands_note": ((f"התפלגות מספרי הרישיון בטווחים של {n(width)}, לפי משפחת רישיון. "
                        f"מספר נמוך מעיד ככל הנראה על רישיון ותיק יותר (בהנחה שהמספרים מוקצים בסדר עולה). "
                        + "חציון מספר הרישיון: "
                        + ", ".join(f"{f} {n(v)}" for f, v in fam_median.items() if v is not None) + ".")
                       if width else ""),
        "bands_aria": f"תרשים עמודות מוערמות של מספר הרישיונות לפי טווח מספר רישיון, {n(len(band_chart['names']))} טווחים",
        "bands_caption": "רישיונות לפי טווח מספר רישיון ומשפחת רישיון",
    }

    def stacked_table(ch):
        return [{"name": nm, "cells": [n(s["data"][i]) for s in ch["series"]],
                 "total": n(sum(s["data"][i] for s in ch["series"]))} for i, nm in enumerate(ch["names"])]

    tables = {
        "fams": fams,
        "types": [{"name": t, "fam": type_fam[t], "count": n(type_counts[t]),
                   "share": pct_bare(type_counts[t] / total if total else 0)} for t in type_order],
        "year": stacked_table(exp_year),
        "cities": stacked_table(city_chart),
        "spread": [{"name": b["name"], "cities": n(b["cities"]), "lics": n(b["lics"])} for b in bucket_rows],
        "bands": stacked_table(band_chart),
    }

    charts = {
        "types": type_chart,
        "year": exp_year,
        "heat": heat,
        "cities": city_chart,
        "spread": spread_chart,
        "bands": band_chart,
        "fam_pal": [FAM_PAL[i % len(FAM_PAL)] for i in range(len(fams))],
    }
    flags = {"expiry": dated > 0, "bands": bool(width)}

    agent_data = {
        "summary_he": (f"רשימת מדבירים מורשים של המשרד להגנת הסביבה: {n(n_holders)} מדבירים ב-{n(n_cities)} יישובים, "
                       f"{n(in_force)} רישיונות בתוקף. בדיקת רישיון לפי שם או מספר רישיון."),
        "dataset_kind": "registry",
        "related_ids": ["a37765ea-d407-42e8-b757-9b70a8cf574f",
                        "7a6cbf55-8178-4d40-8613-a38909c7e96f",
                        "14b7572d-c8f1-427a-8ef8-8069b197225d",
                        "005fe7c5-be59-42de-91ea-0ce3cdece35c"],
        "suggested_tags": ["מדבירים", "הדברה", "מזיקים", "רישוי", "אנשי מקצוע", "איכות הסביבה"],
        "spatial_coverage": "ישראל",
    }

    return {
        "agent_data": agent_data,
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
        "flags": flags,
    }
