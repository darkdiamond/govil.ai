"""פרטי שינויים בחברות ושותפויות — רשם החברות: a rolling one-year change log.

One row per change (request type) the Companies Registrar recorded for a
corporation over the last year; the file is regenerated daily and older rows
drop off, so the frame is always ~one year wide. Companies and partnerships
are businesses and may be named; the corporation number (an identifier) is
used only for grouping, never shown.

"Now" is the latest status date in the data. Both edge months of the window
are normally partial (the window starts and ends mid-month) — they are
labelled and excluded from month-to-month comparisons.
"""
import pandas as pd

FAMILIES = [
    ("annual", "דוח שנתי"),
    ("charge", "שעבודים ועיקולים"),
    ("viol", "הפרות וחיובים"),
    ("officers", "בעלי תפקידים ודירקטורים"),
    ("capital", "הון ומניות"),
    ("liq", "פירוק, חיסול ומיזוג"),
    ("ident", "שם, כתובת ותקנון"),
    ("other", "אחר"),
]
FAM_NAME = dict(FAMILIES)
LIQ_KEYS = ["פירוק", "חיסול", "מיזוג", "החייא", "הליכים", "שיקום", "פשרה", "כינוס", "גריעה",
            "ביטול אישור", "כושר פרעון"]
OFFICER_KEYS = ["תפקיד", "דירקטור", "מנהלים", "פרטי גורמים"]
CAPITAL_KEYS = ["מניות", "הון"]
IDENT_KEYS = ["שם", "כתובת", "תקנון", "מטרה", "סיווג", "מען"]
# First two digits of the 9-digit corporation number mark the register.
PREFIX = {"51": "חברות", "52": "חברות", "53": "שותפויות", "54": "שותפויות", "55": "שותפויות",
          "56": "חברות חוץ"}
WEEKDAYS = ["ראשון", "שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת"]  # Sunday first
WEEKDAYS_SHORT = ["א׳", "ב׳", "ג׳", "ד׳", "ה׳", "ו׳", "ש׳"]
TOP_TYPES = 15
TOP_SUB = 10
TOP_CORPS = 10
PER_CORP_BINS = [(1, 1, "1"), (2, 2, "2"), (3, 5, "3–5"), (6, 10, "6–10"), (11, 50, "11–50"),
                 (51, None, "51 ומעלה")]
MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי", "אוגוסט", "ספטמבר",
             "אוקטובר", "נובמבר", "דצמבר"]
HEAVY_CHARGES = 100  # charge rows per corporation that mark a heavy, revolving user
DAILY_MAX_DAYS = 400  # beyond this span the timeline switches to weekly points


def _int(n):
    return f"{int(n):,}"


def _pct(x):
    return f"{x * 100:.1f}%"


def _date_he(ts):
    return f"{ts.day}.{ts.month}.{ts.year}"


def _month_he(p):
    return f"{MONTHS_HE[p.month - 1]} {p.year}"


def _clean(s):
    # Registrar export: '~' stands for '"' inside abbreviations (בע~מ, דו~ח, חל~צ).
    return s.str.replace("~", "״", regex=False).str.replace(r"\s+", " ", regex=True).str.strip()


def _family(name):
    if name.startswith("דו״ח שנתי"):
        return "annual"
    if "שעבוד" in name or "עיקול" in name:
        return "charge"
    if "הפרה" in name or "חיובים" in name:
        return "viol"
    if any(k in name for k in LIQ_KEYS):
        return "liq"
    if any(k in name for k in OFFICER_KEYS):
        return "officers"
    if any(k in name for k in CAPITAL_KEYS):
        return "capital"
    if any(k in name for k in IDENT_KEYS):
        return "ident"
    return "other"


def _vc(s):
    """value_counts with a total order: count desc, then key asc."""
    return s.value_counts().sort_index().sort_values(ascending=False, kind="stable")


def _top(vc, n, other="אחר"):
    head = [(k, int(v)) for k, v in vc.head(n).items()]
    rest = int(vc.iloc[n:].sum())
    if rest:
        head.append((other, rest))
    return head


def _bar(items):
    return {"names": [k for k, _ in items], "values": [v for _, v in items]}


def _prepare(raw):
    df = pd.DataFrame({
        "corp": raw["מספר תאגיד"].str.strip(),
        "name": _clean(raw["שם תאגיד"]),
        "type": _clean(raw["סוג בקשה"]),
        "date": pd.to_datetime(raw["תאריך עדכון סטטוס"].str.strip(), format="%d/%m/%Y",
                               errors="coerce"),
        "charge_id": raw["מזהה השיעבוד"].str.strip(),
    })
    df = df[df["date"].notna() & (df["corp"] != "")].copy()
    types = pd.Series(df["type"].unique())
    fam = dict(zip(types, types.map(_family)))
    df["fam"] = df["type"].map(fam)
    df["month"] = df["date"].dt.to_period("M")
    return df


def _months(df):
    """Every month in the window, flagged partial when the data does not span it."""
    lo, hi = df["date"].min(), df["date"].max()
    months = pd.period_range(lo.to_period("M"), hi.to_period("M"), freq="M")
    out = []
    for p in months:
        full = lo <= p.start_time and hi >= p.end_time.normalize()
        out.append((p, full))
    return out


# ---------------------------------------------------------------- insights

def insight_family(fam_vc, total):
    lead, n = fam_vc.index[0], int(fam_vc.iloc[0])
    if n / total < 0.2:
        return None
    second, n2 = fam_vc.index[1], int(fam_vc.iloc[1])
    return (f"{FAM_NAME[lead]} הוא סוג השינוי הנפוץ ביותר — {_int(n)} רשומות, {_pct(n / total)} "
            f"מכלל השינויים בשנה; אחריו {FAM_NAME[second]} ({_pct(n2 / total)}).")


def insight_charges(reg, dis):
    if reg + dis < 200:
        return None
    diff = (dis - reg) / max(reg, 1)
    if abs(diff) < 0.03:
        state = "כמעט באותו היקף"
    elif diff > 0:
        state = f"{_int(dis - reg)} יותר שעבודים סולקו מאשר נרשמו"
    else:
        state = f"{_int(reg - dis)} יותר שעבודים נרשמו מאשר סולקו"
    return (f"בשנה האחרונה נרשמו {_int(reg)} שעבודים וסולקו {_int(dis)} — {state}.")


def insight_charge_conc(df):
    ch = df[df["fam"] == "charge"]
    if len(ch) < 500:
        return None
    per = _vc(ch["corp"])
    heavy = per[per > HEAVY_CHARGES]
    if len(heavy) < 5:
        return None
    name = ch.loc[ch["corp"] == per.index[0], "name"].iloc[0]
    return (f"בראש פעילות השעבודים {name} עם {_int(per.iloc[0])} רשומות רישום, סילוק ועדכון. "
            f"{_int(len(heavy))} תאגידים צברו יותר מ-{HEAVY_CHARGES} רשומות שעבוד כל אחד, ויחד הם "
            f"{_pct(heavy.sum() / len(ch))} מכלל רשומות השעבוד.")


def insight_viol_wave(df):
    v = df[df["type"] == "עדכון הפרה"]
    if len(v) < 1000:
        return None
    by_day = _vc(v["date"])
    day, n = by_day.index[0], int(by_day.iloc[0])
    share = n / len(v)
    if share < 0.1:
        return None
    return (f"עדכוני ההפרה מגיעים בגלים: ב-{_date_he(day)} לבדו נרשמו {_int(n)} עדכוני הפרה — "
            f"{_pct(share)} מכל {_int(len(v))} עדכוני ההפרה בשנה.")


def insight_peak_month(df, months):
    full = [p for p, f in months if f]
    if len(full) < 6:
        return None
    vc = df["month"].value_counts()
    vals = pd.Series({p: int(vc.get(p, 0)) for p in full})
    peak = vals.idxmax()
    med = float(vals.median())
    if med <= 0 or vals[peak] / med < 1.3:
        return None
    sub = df[df["month"] == peak]
    fv = _vc(sub["fam"])
    return (f"החודש העמוס ביותר היה {_month_he(peak)} עם {_int(vals[peak])} שינויים — פי "
            f"{vals[peak] / med:.1f} מהחודש החציוני ({_int(med)}); המשפחה הגדולה בו: "
            f"{FAM_NAME[fv.index[0]]} ({_pct(fv.iloc[0] / len(sub))}). חודשים חלקיים בקצות החלון לא נכללו בהשוואה.")


def insight_tail(per_corp):
    one = int((per_corp == 1).sum())
    n = len(per_corp)
    if n < 100:
        return None
    many = int((per_corp > 50).sum())
    return (f"{_int(n)} תאגידים עברו שינוי אחד לפחות בשנה; ל-{_pct(one / n)} מהם נרשם שינוי "
            f"יחיד, ואילו ל-{_int(many)} תאגידים נרשמו יותר מ-{PER_CORP_BINS[-1][0] - 1} שינויים.")


def insight_directors(df):
    add = int(df["type"].str.contains("הוספת דירקטור").sum())
    rem = int(df["type"].str.contains("הסרת דירקטור").sum())
    if add + rem < 200:
        return None
    diff = (add - rem) / max(rem, 1)
    if abs(diff) < 0.03:
        state = "כמעט באותו מספר"
    elif diff > 0:
        state = f"{_pct(diff)} יותר הוספות מהסרות"
    else:
        state = f"{_pct(-diff)} פחות הוספות מהסרות"
    return (f"נרשמו {_int(add)} הוספות דירקטור ו-{_int(rem)} הסרות (כולל דרך הדוח השנתי) — {state}.")


def insight_fast_liq(df):
    start = df[df["type"] == "פירוק מרצון מזורז"]["corp"].nunique()
    done = df[df["type"].str.contains("חיסול מרצון מזורז")]["corp"].nunique()
    if start + done < 100:
        return None
    liq = df[df["fam"] == "liq"]["corp"].nunique()
    return (f"{_int(liq)} תאגידים היו בהליך פירוק, חיסול או מיזוג במהלך השנה; {_int(start)} מהם פתחו "
            f"בפירוק מרצון מזורז, ו-{_int(done)} חוסלו אוטומטית במסלול המזורז.")


def insight_weekday(df):
    dow = (df["date"].dt.dayofweek + 1) % 7  # 0 = Sunday
    work = int((dow <= 4).sum())
    share = work / len(df)
    if share < 0.8:
        return None
    return (f"{_pct(share)} מהשינויים נרשמו בימים ראשון עד חמישי; בשישי ובשבת נרשמו "
            f"{_int(len(df) - work)} בלבד.")


# ---------------------------------------------------------------- compute

def compute(frames):
    df = _prepare(frames.pop("main"))
    total = len(df)
    lo, hi = df["date"].min(), df["date"].max()
    months = _months(df)
    fam_vc = _vc(df["fam"])
    fams = [k for k, _ in FAMILIES if k in fam_vc.index]

    # timeline: daily while the window is ~a year, weekly if it ever grows longer
    span = (hi - lo).days + 1
    if span <= DAILY_MAX_DAYS:
        dv = df["date"].value_counts()
        days = pd.date_range(lo, hi, freq="D")
        timeline = {"x": [d.strftime("%Y-%m-%d") for d in days],
                    "y": [int(dv.get(d, 0)) for d in days], "unit": "יום"}
    else:
        wk = df["date"].dt.to_period("W-SAT")
        wv = wk.value_counts()
        weeks = pd.period_range(wk.min(), wk.max(), freq="W-SAT")
        timeline = {"x": [w.start_time.strftime("%Y-%m-%d") for w in weeks],
                    "y": [int(wv.get(w, 0)) for w in weeks], "unit": "שבוע"}

    day_vc = _vc(df["date"])
    peak_day, peak_n = day_vc.index[0], int(day_vc.iloc[0])
    peak_fams = _vc(df.loc[df["date"] == peak_day, "fam"])
    peak_fam, peak_share = peak_fams.index[0], peak_fams.iloc[0] / peak_n

    # month × family
    mf = df.groupby(["month", "fam"]).size()
    mlabels = [_month_he(p) + ("" if f else " (חלקי)") for p, f in months]
    monthly = {"x": mlabels,
               "series": [{"name": FAM_NAME[k], "data": [int(mf.get((p, k), 0)) for p, _ in months]}
                          for k in fams],
               "totals": [int(sum(mf.get((p, k), 0) for k in fams)) for p, _ in months]}
    monthly_rows = [{"month": lab, "values": [s["data"][i] for s in monthly["series"]],
                     "total": monthly["totals"][i]} for i, lab in enumerate(mlabels)]

    families = _bar([(FAM_NAME[k], int(fam_vc[k])) for k in fam_vc.index])
    types = _bar(_top(_vc(df["type"]), TOP_TYPES, "שאר סוגי השינויים"))
    annual = df[(df["fam"] == "annual") & (df["type"] != "דו״ח שנתי")]
    annual_sub = _bar(_top(_vc(annual["type"].str.replace("דו״ח שנתי-", "", regex=False)),
                           TOP_SUB, "שאר העדכונים"))
    liq_df = df[df["fam"] == "liq"]
    liq = _bar(_top(_vc(liq_df["type"]), TOP_SUB, "שאר ההליכים"))

    # charges registered vs discharged per month
    reg_m = df[df["type"] == "רישום שעבוד"]["month"].value_counts()
    dis_m = df[df["type"] == "סילוק שעבוד"]["month"].value_counts()
    charges = {"x": mlabels,
               "reg": [int(reg_m.get(p, 0)) for p, _ in months],
               "dis": [int(dis_m.get(p, 0)) for p, _ in months]}
    reg, dis = int(reg_m.sum()), int(dis_m.sum())
    dis_peak = max(range(len(months)), key=lambda i: (charges["dis"][i], -i))
    ch_rows = df[(df["fam"] == "charge") & (df["charge_id"] != "")]
    n_charges = int(ch_rows[["corp", "charge_id"]].drop_duplicates().shape[0])

    # weekday
    dow = (df["date"].dt.dayofweek + 1) % 7
    dvc = dow.value_counts()
    weekday = {"names": WEEKDAYS, "values": [int(dvc.get(i, 0)) for i in range(7)]}

    # changes per corporation
    per_corp = df["corp"].value_counts()
    bins = []
    for a, b, label in PER_CORP_BINS:
        m = (per_corp >= a) if b is None else ((per_corp >= a) & (per_corp <= b))
        bins.append((label, int(m.sum())))
    per = _bar(bins)

    # top corporations by number of changes (named: companies are businesses)
    corp_vc = _vc(df["corp"])
    top_ids = list(corp_vc.index[:TOP_CORPS])
    sub = df[df["corp"].isin(top_ids)]
    names = (sub.sort_values(["corp", "date", "name"], kind="stable")
             .groupby("corp")["name"].last())
    tc = sub.groupby(["corp", "fam"]).size()
    tfams = [k for k in fams if any(tc.get((c, k), 0) for c in top_ids)]
    top_corps = {"names": [names[c] for c in top_ids],
                 "series": [{"name": FAM_NAME[k], "data": [int(tc.get((c, k), 0)) for c in top_ids]}
                            for k in tfams],
                 "values": [int(corp_vc[c]) for c in top_ids]}

    # register (companies / partnerships / foreign companies) from the number prefix
    reg_kind = df["corp"].str[:2].map(PREFIX).fillna("אחר")
    kinds_c = _vc(reg_kind.groupby(df["corp"]).first())
    kinds_r = reg_kind.value_counts()
    kinds = {"names": list(kinds_c.index), "corps": [int(v) for v in kinds_c.values],
             "rows": [int(kinds_r.get(k, 0)) for k in kinds_c.index]}

    rules = [
        ("family", insight_family(fam_vc, total)),
        ("charges", insight_charges(reg, dis)),
        ("charge_conc", insight_charge_conc(df)),
        ("viol_wave", insight_viol_wave(df)),
        ("peak_month", insight_peak_month(df, months)),
        ("tail", insight_tail(per_corp)),
        ("directors", insight_directors(df)),
        ("fast_liq", insight_fast_liq(df)),
        ("weekday", insight_weekday(df)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    n_corps = int(per_corp.shape[0])
    n_types = int(df["type"].nunique())
    avg = total / n_corps
    partial = [_month_he(p) for p, f in months if not f]
    partial_txt = (" החודשים " + " ו".join(partial) + " חלקיים." if len(partial) > 1
                   else f" החודש {partial[0]} חלקי." if partial else "")
    window = f"{_date_he(lo)} עד {_date_he(hi)}"
    liq_corps = int(liq_df["corp"].nunique())

    return {
        "agent_data": {
            "summary_he": (f"יומן השינויים של רשם החברות לשנה האחרונה (מ-{window}): {_int(total)} שינויים "
                           f"ב-{_int(n_corps)} חברות ושותפויות — דוחות שנתיים, שעבודים, הפרות, בעלי "
                           f"תפקידים, הון ופירוקים. מתעדכן מדי יום."),
            "dataset_kind": "timeseries",
            "related_ids": ["246d949c-a253-4811-8a11-41a137d3d613",
                            "01aeaf5c-59a2-4ddc-a616-31b85621bfe2",
                            "3111ae54-790a-4d02-9750-d51e1134b405"],
            "suggested_tags": ["רשם החברות", "שינויים בתאגידים", "חברות ושותפויות", "שעבודים",
                               "דוחות שנתיים", "פירוק חברות"],
            "temporal_coverage": f"{lo.strftime('%Y-%m-%d')}/{hi.strftime('%Y-%m-%d')}",
            "spatial_coverage": "ישראל",
        },
        "kpis": {
            "total": {"value": total, "display": _int(total), "tone": "brand"},
            "corps": {"value": n_corps, "display": _int(n_corps), "tone": "brand"},
            "avg": {"value": round(avg, 2), "display": f"{avg:.1f}", "tone": "brand"},
            "reg": {"value": reg, "display": _int(reg), "tone": "brand"},
            # Net discharges (more charges removed than created) read as easing
            # credit pressure; net registrations as caution.
            "dis": {"value": dis, "display": _int(dis),
                    "tone": "ok" if dis >= reg * 1.03 else "warn" if dis <= reg * 0.97 else "brand"},
            "liq": {"value": liq_corps, "display": _int(liq_corps), "tone": "info"},
        },
        "charts": {
            "timeline": timeline,
            "monthly": monthly,
            "families": families,
            "types": types,
            "annual": annual_sub,
            "charges": charges,
            "liq": liq,
            "weekday": weekday,
            "weekday_short": WEEKDAYS_SHORT,
            "per_corp": per,
            "top_corps": top_corps,
            "kinds": kinds,
        },
        "insights": insights,
        "tables": {
            "monthly": monthly_rows,
            "charges": [{"month": lab, "reg": charges["reg"][i], "dis": charges["dis"][i]}
                        for i, lab in enumerate(mlabels)],
            "top_corps": [{"name": n, "total": v} for n, v in zip(top_corps["names"],
                                                                  top_corps["values"])],
        },
        "labels": {
            "lede": (f"{_int(total)} שינויים שרשם החברות רשם ב-{_int(n_corps)} חברות ושותפויות בין "
                     f"{_date_he(lo)} ל-{_date_he(hi)} — בממוצע {avg:.1f} שינויים לתאגיד. הקובץ מתחדש מדי יום ומכסה שנה "
                     f"אחורה; תאגיד שלא השתנה בשנה האחרונה אינו מופיע בו. {_int(n_types)} סוגי "
                     f"שינויים מקובצים כאן ל-{len(fams)} משפחות."),
            "window": window,
            "timeline_note": (f"מספר השינויים שנרשמו בכל {timeline['unit']}, מ-{window}. היום העמוס ביותר: "
                              f"{_date_he(peak_day)}, עם {_int(peak_n)} שינויים — {_pct(peak_share)} "
                              f"מהם {FAM_NAME[peak_fam]}. גררו את הסרגל כדי להתמקד בתקופה."),
            "timeline_aria": f"גרף קו: שינויים בכל {timeline['unit']}, מ-{window}.",
            "monthly_note": f"השינויים בכל חודש לפי משפחת השינוי.{partial_txt}",
            "monthly_aria": "גרף עמודות מוערמות: שינויים בכל חודש לפי משפחת שינוי.",
            "families_aria": f"תרשים עמודות: {_int(total)} השינויים לפי משפחת שינוי.",
            "types_note": (f"{TOP_TYPES} סוגי הבקשות הנפוצים מתוך {_int(n_types)}; השאר מקובצים "
                           f"יחד."),
            "types_aria": f"תרשים עמודות: {TOP_TYPES} סוגי השינויים הנפוצים.",
            "annual_note": (f"דוח שנתי שמביא עמו שינוי בפרטי התאגיד נרשם גם כשורה נפרדת לכל שינוי. "
                            f"{_int(len(annual))} שורות כאלה, לפי סוג העדכון."),
            "annual_aria": "תרשים עמודות: העדכונים שהוגשו במסגרת הדוח השנתי.",
            "charges_note": (f"רישום מול סילוק של שעבודים בכל חודש. {_int(n_charges)} שעבודים נפרדים "
                             f"(לפי מזהה השעבוד בכל תאגיד) הופיעו ברשומות השנה. חודש השיא בסילוקים: "
                             f"{charges['x'][dis_peak]} ({_int(charges['dis'][dis_peak])})."),
            "charges_aria": "גרף עמודות: שעבודים שנרשמו ושעבודים שסולקו בכל חודש.",
            "liq_note": f"{_int(liq_corps)} תאגידים עם רשומת פירוק, חיסול או מיזוג; לפי סוג ההליך.",
            "liq_aria": "תרשים עמודות: הליכי פירוק, חיסול ומיזוג לפי סוג.",
            "weekday_aria": "תרשים עמודות: שינויים לפי יום בשבוע.",
            "per_corp_note": (f"כמה שינויים נרשמו לכל תאגיד בשנה. החציון הוא "
                              f"{_int(per_corp.median())}; המקסימום {_int(per_corp.max())}."),
            "per_corp_aria": "תרשים עמודות: תאגידים לפי מספר השינויים שנרשמו להם בשנה.",
            "top_corps_note": (f"{TOP_CORPS} התאגידים עם מספר השינויים הגבוה ביותר, לפי משפחת "
                               f"השינוי."),
            "top_corps_aria": f"גרף עמודות מוערמות: {TOP_CORPS} התאגידים עם הכי הרבה שינויים.",
            "kinds_note": ("לפי הספרות הראשונות של מספר התאגיד: חברות (51/52), שותפויות (53–55) "
                           "וחברות חוץ (56)."),
            "kinds_aria": "תרשים עמודות: תאגידים ושינויים לפי סוג המרשם.",
        },
    }
