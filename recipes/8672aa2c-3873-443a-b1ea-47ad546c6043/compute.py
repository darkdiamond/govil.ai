"""מספרי רישוי של כלי רכב לא פעילים וחסרי קוד דגם: a registry snapshot of
vehicles with no model code whose licence lapsed over 13 months ago (not
stolen, not finally cancelled). One row per vehicle, no dates other than the
production year; the file is republished daily as a full snapshot.

- Nothing is anchored to the clock: the page describes the snapshot.
- Production year drives the time views (a handful of placeholder years
  before YEAR_FLOOR, mostly "1900", are excluded from them and disclosed).
- The maker name is truncated to five characters at the source ("סובאר",
  "פולקס"); well-known makers are completed and merged (רנו צרפת + רנו ספרד,
  דימלר + מרצדס), everything else is shown as recorded, so new makers flow in.
- Plates and VINs are never read: everything is aggregated.
"""
import re

import pandas as pd

OTHER = "אחר"
UNKNOWN = "לא ידוע"
YEAR_FLOOR = 1930          # earlier production years are placeholders / too sparse
PRE_YEAR = 1990            # KPI: share produced before this year
TOP_MAKERS = 15
TOP_COUNTRIES = 12
TOP_MODELS = 15
TOP_ISRAEL = 10
TOP_DRIVE = 7
MIX_COUNTRIES = 6          # country mix by decade: top N overall + אחר
MIN_DECADE = 1000          # a decade needs this many rows to be charted
MIN_DECADE_RULE = 10000    # ... and this many to anchor an insight comparison
EV_MIN = 10                # electrified insight needs at least this many vehicles
CC_MAX = 10000             # engine sizes above this (cc) are data errors
TREND_BAND = 0.05          # ±5% counts as "stable"
LEADER_GAP = 1.1           # top maker must beat the runner-up by 10% to "lead"

FAMILY_ORDER = [
    "רכב נוסעים (M1)", "משא ומסחרי (N)", "דו ותלת גלגלי (L)", "גרורים ונגררים (O)",
    "טרקטורים (T)", "אוטובוסים ומיניבוסים (M2-M3)", "לא מסווג",
]
FUEL_GROUPS = {
    "בנזין": "בנזין", "דיזל": "דיזל", 'גפמ"': "גפ״מ", 'גפ"מ': "גפ״מ",
    "חשמל": "חשמלי", "חשמל/בנזין": "היברידי", "חשמל/דיזל": "היברידי",
    "גז טבעי דחוס": "גז טבעי", "נפט": "נפט",
}
ELECTRIFIED = ("חשמלי", "היברידי")
COUNTRY_ALIASES = {
    'ארהב"': "ארה״ב", "ארהב": "ארה״ב", "ד. קוריאה": "דרום קוריאה",
    "קוריאה הדרומית": "דרום קוריאה", "תורקיה": "טורקיה",
}
# tozeret_nm is cut to five characters at the source. Completions for makers
# whose truncated name is unambiguous; matched on the start of the name.
MAKER_PREFIXES = [
    ("סובאר", "סובארו"), ("פולקס", "פולקסווגן"), ("רנו", "רנו"), ("פיאג'", "פיאג'ו"),
    ("סאן י", "סאן יאנג"), ("מיצוב", "מיצובישי"), ("סיטרו", "סיטרואן"),
    ("אוטוק", "אוטוקרס"), ("קואנג", "קואנג יאנג"), ("שברול", "שברולט"),
    ("סוזוק", "סוזוקי"), ("דייהט", "דייהטסו"), ("דימלר", "מרצדס-בנץ"),
    ("מרצדס", "מרצדס-בנץ"), ("ג'י.א", "ג'י.אמ.סי"), ("ווילי", "ויליס"),
    ("פרגוס", "פרגוסון"), ("עצמי", "ייצור עצמי"), ("טויוט", "טויוטה"),
    ("ב מ ו", "ב.מ.וו"), ("פולרי", "פולריס"), ("אינוצ", "אינוצ'נטי"),
    ("אן.אס", "אן.אס.יו"), ("אוסטי", "אוסטין"), ("איסוז", "איסוזו"),
    ("יונדא", "יונדאי"), ("אלפא", "אלפא רומיאו"), ("קוואס", "קוואסאקי"),
    ("ווקסה", "ווקסהול"), ("ב ס א", "ב.ס.א"), ("מאן ג", "מאן"),
    ("קרייז", "קרייזלר"), ("פורדס", "פורדסון"),
]
CC_BINS = [(1, 999, "עד 999"), (1000, 1299, "1,000-1,299"), (1300, 1599, "1,300-1,599"),
           (1600, 1999, "1,600-1,999"), (2000, 2999, "2,000-2,999"),
           (3000, CC_MAX, "3,000 ומעלה")]


def _int(n):
    return f"{int(n):,}"


def _pct(x, digits=1):
    return f"{x * 100:.{digits}f}%"


def _vav(word):
    """Hebrew "and" prefix: glued to a Hebrew word, "ו-" before Latin/digits."""
    w = str(word)
    return f"ו{w}" if w[:1] and "\u05d0" <= w[0] <= "\u05ea" else f"ו-{w}"


def _ranked(series):
    vc = series.value_counts()
    return vc.sort_index().sort_values(ascending=False, kind="stable")


def _top_other(vc, n):
    top = vc.head(n)
    rest = int(vc.iloc[n:].sum())
    names, values = [str(x) for x in top.index], [int(v) for v in top]
    if rest:
        names.append(OTHER)
        values.append(rest)
    return names, values


def _rank_rows(names, values, total):
    return [{"name": nm, "count": _int(v), "share": f"{v / max(total, 1) * 100:.1f}"}
            for nm, v in zip(names, values)]


def _map_unique(series, fn):
    u = series.unique()
    return series.map(dict(zip(u, (fn(x) for x in u))))


def _family(code):
    c = code.strip().upper()
    if c == "M1":
        return FAMILY_ORDER[0]
    if c in ("M2", "M3"):
        return FAMILY_ORDER[5]
    if re.fullmatch(r"N\d", c):
        return FAMILY_ORDER[1]
    if re.fullmatch(r"L\d", c):
        return FAMILY_ORDER[2]
    if re.fullmatch(r"O\d", c):
        return FAMILY_ORDER[3]
    if re.fullmatch(r"T\d", c):
        return FAMILY_ORDER[4]
    return FAMILY_ORDER[6]


def _code(code):
    c = code.strip().upper()
    return c if re.fullmatch(r"[MNLOT]\d", c) else "לא מסווג"


def _maker(name):
    s = name.strip()
    if not s:
        return UNKNOWN
    for prefix, full in MAKER_PREFIXES:
        if s.startswith(prefix):
            return full
    return s


def _country(name):
    s = name.strip()
    if not s:
        return UNKNOWN
    return COUNTRY_ALIASES.get(s, s)


def _drive(name):
    s = name.strip().upper()
    if re.fullmatch(r"\d+X\d+", s):
        return s
    if s.startswith("חסר"):
        return "ללא הנעה (נגרר)"
    if s.startswith("רכב זחל"):
        return "זחל למחצה"
    return UNKNOWN


def _model(name):
    s = re.sub(r"\s+", " ", name.strip())
    return s if re.search(r"[0-9A-Za-zא-ת]", s) else ""


def _decade_label(d):
    return f"שנות ה-{d % 100:02d}" if d < 2000 else f"שנות ה-{d}"


def _prepare(df):
    out = pd.DataFrame({
        "family": _map_unique(df["tkina_EU"], _family),
        "code": _map_unique(df["tkina_EU"], _code),
        "year": pd.to_numeric(df["shnat_yitzur"].str.strip(), errors="coerce"),
        "maker": _map_unique(df["tozeret_nm"], _maker),
        "country": _map_unique(df["tozeret_eretz_nm"], _country),
        "fuel": _map_unique(df["sug_delek_nm"], lambda s: FUEL_GROUPS.get(s.strip(), UNKNOWN)),
        "model": _map_unique(df["degem_nm"], _model),
        "cc": pd.to_numeric(df["nefach_manoa"].str.replace(",", "", regex=False).str.strip(),
                            errors="coerce"),
        "drive": _map_unique(df["hanaa_nm"], _drive),
    })
    return out


# ── Insight rules ─────────────────────────────────────────────────────────


def insight_era(year_vc, n_valid, pre_share):
    if len(year_vc) < 10 or n_valid == 0:
        return None
    peak = year_vc.sort_index().sort_values(ascending=False, kind="stable")
    y, c = int(peak.index[0]), int(peak.iloc[0])
    return (f"שנת הייצור הנפוצה במאגר היא {y} ({_int(c)} כלי רכב, {_pct(c / n_valid)}), "
            f"ו-{_pct(pre_share)} מכלי הרכב יוצרו לפני {PRE_YEAR}"
            + (": רובו של המאגר הוא צי ישן שיצא משימוש מזמן." if pre_share >= 0.5 else "."))


def insight_family(fam_vc, n):
    fam_vc = fam_vc[fam_vc.index != FAMILY_ORDER[6]]  # "לא מסווג" is not a family to lead with
    if len(fam_vc) < 2:
        return None
    top, second = fam_vc.index[0], fam_vc.index[1]
    return (f"{top} הם {_pct(fam_vc.iloc[0] / n)} מהמאגר ({_int(fam_vc.iloc[0])}), "
            f"ואחריהם {second} עם {_pct(fam_vc.iloc[1] / n)} ({_int(fam_vc.iloc[1])}).")


def insight_maker(mvc, n_known):
    if len(mvc) < 3 or n_known == 0:
        return None
    if mvc.iloc[0] < mvc.iloc[1] * LEADER_GAP:
        return (f"אין יצרן דומיננטי: {mvc.index[0]} {_vav(mvc.index[1])} כמעט שווים "
                f"({_int(mvc.iloc[0])} ו-{_int(mvc.iloc[1])} כלי רכב).")
    top3 = mvc.head(3).sum() / n_known
    return (f"{mvc.index[0]} מוביל עם {_int(mvc.iloc[0])} כלי רכב ({_pct(mvc.iloc[0] / n_known)}), "
            f"ושלושת היצרנים הגדולים ({', '.join(mvc.index[:3])}) מרכזים {_pct(top3)} "
            f"מכלי הרכב שיצרנם ידוע.")


def insight_country(cvc, n_known):
    if len(cvc) < 3 or n_known == 0:
        return None
    text = (f"{cvc.index[0]} היא ארץ הייצור המובילה ({_pct(cvc.iloc[0] / n_known)}), "
            f"לפני {cvc.index[1]} ({_pct(cvc.iloc[1] / n_known)}) {_vav(cvc.index[2])} "
            f"({_pct(cvc.iloc[2] / n_known)}).")
    return text


def insight_israel(il_vc, n_il, n_known_c, rank):
    if n_il == 0 or n_known_c == 0 or len(il_vc) < 2:
        return None
    return (f"{_int(n_il)} כלי רכב ({_pct(n_il / n_known_c)}) יוצרו בישראל"
            + (f", ישראל במקום ה-{rank} בין ארצות הייצור" if rank else "")
            + f". בראשם {il_vc.index[0]} ({_int(il_vc.iloc[0])}) {_vav(il_vc.index[1])} "
            f"({_int(il_vc.iloc[1])}).")


def insight_fuel(fvc, n_known_f):
    if n_known_f == 0 or "בנזין" not in fvc.index:
        return None
    text = f"{_pct(fvc['בנזין'] / n_known_f)} מכלי הרכב שסוג הדלק שלהם ידוע מונעים בבנזין"
    if "דיזל" in fvc.index:
        text += f", {_pct(fvc['דיזל'] / n_known_f)} בדיזל"
    ev = int(sum(fvc.get(k, 0) for k in ELECTRIFIED))
    if ev >= EV_MIN:
        text += f", ורק {_int(ev)} חשמליים או היברידיים"
    return text + "."


def insight_cc(cc_dec):
    """cc_dec: list of (decade, median, count); only decades with
    MIN_DECADE_RULE cars anchor the comparison."""
    cc_dec = [r for r in cc_dec if r[2] >= MIN_DECADE_RULE]
    if len(cc_dec) < 3:
        return None
    (d0, m0, _), (d1, m1, _) = cc_dec[0], cc_dec[-1]
    if m0 <= 0:
        return None
    ch = m1 / m0 - 1
    low = min(cc_dec[1:-1], key=lambda r: (r[1], r[0]))
    if low[1] < min(m0, m1) * (1 - TREND_BAND):
        return (f"נפח המנוע החציוני של רכב נוסעים עמד על {_int(m0)} סמ״ק ב{_decade_label(d0)}, "
                f"ירד ל-{_int(low[1])} סמ״ק ב{_decade_label(low[0])} והגיע ל-{_int(m1)} סמ״ק "
                f"ב{_decade_label(d1)}.")
    if abs(ch) < TREND_BAND:
        return (f"נפח המנוע החציוני של רכב נוסעים כמעט לא השתנה: {_int(m0)} סמ״ק "
                f"ב{_decade_label(d0)} ו-{_int(m1)} סמ״ק ב{_decade_label(d1)}.")
    word = "עלה" if ch > 0 else "ירד"
    return (f"נפח המנוע החציוני של רכב נוסעים {word} מ-{_int(m0)} סמ״ק ב{_decade_label(d0)} "
            f"ל-{_int(m1)} סמ״ק ב{_decade_label(d1)} ({_pct(abs(ch), 0)}).")


def insight_shift(mix_rows, d0, d1):
    """Country whose share moved most between the first and last qualifying decade."""
    if not mix_rows or d0 is None or d1 is None or d0 == d1:
        return None
    best = None
    for name, s0, s1 in mix_rows:
        if name == OTHER:
            continue
        diff = s1 - s0
        if best is None or abs(diff) > abs(best[3]) + 1e-12:
            best = (name, s0, s1, diff)
    if best is None or abs(best[3]) < 0.05:
        return None
    name, s0, s1, diff = best
    word = "זינק" if diff > 0 else "צנח"
    return (f"התמהיל השתנה עם השנים: חלקה של {name} {word} מ-{_pct(s0)} מכלי הרכב "
            f"שיוצרו ב{_decade_label(d0)} ל-{_pct(s1)} ב{_decade_label(d1)}.")


def insight_model(model_rows):
    if len(model_rows) < 3:
        return None
    a, b = model_rows[0], model_rows[1]
    return (f"הדגם הנפוץ במאגר הוא {a['name']} ({_int(a['n'])} כלי רכב), ואחריו "
            f"{b['name']} ({_int(b['n'])}).")


# ── compute ───────────────────────────────────────────────────────────────


def compute(frames):
    df = _prepare(frames["main"])
    n = len(df)

    # Families and EU classes
    fam_vc = _ranked(df["family"])
    fam_rows = [{"name": f, "count": _int(fam_vc[f]), "share": f"{fam_vc[f] / n * 100:.1f}"}
                for f in fam_vc.index]
    code_vc = _ranked(df["code"])
    code_fam = (df.groupby("code")["family"].agg(lambda s: _ranked(s).index[0]))
    code_rows = [{"name": c, "family": code_fam[c], "count": _int(code_vc[c]),
                  "share": f"{code_vc[c] / n * 100:.1f}"} for c in code_vc.index]
    fam_names = [f for f in fam_vc.index]

    # Production years
    yv = df[(df["year"] >= YEAR_FLOOR) & (df["year"] <= df["year"].max())].copy()
    yv["year"] = yv["year"].astype(int)
    n_valid = len(yv)
    bad_year = n - n_valid
    year_vc = yv["year"].value_counts()
    y_first, y_last = int(yv["year"].min()), int(yv["year"].max())
    years = list(range(y_first, y_last + 1))
    yf = yv.groupby(["year", "family"]).size()
    year_series = [{"name": f, "data": [int(yf.get((y, f), 0)) for y in years]}
                   for f in fam_names if f in set(yv["family"])]
    pre_share = float((yv["year"] < PRE_YEAR).sum()) / max(n_valid, 1)
    med_year = int(yv["year"].median()) if n_valid else 0
    zoom_start = 0

    # Decades
    yv["decade"] = (yv["year"] // 10) * 10
    dec_vc = yv["decade"].value_counts().sort_index()
    decades = [int(d) for d in dec_vc.index]
    df_dec = yv.groupby(["decade", "family"]).size()
    dec_series = []
    for f in fam_names:
        if f not in set(yv["family"]):
            continue
        dec_series.append({"name": f, "data": [round(df_dec.get((d, f), 0) / dec_vc[d] * 100, 1)
                                               for d in decades],
                           "counts": [int(df_dec.get((d, f), 0)) for d in decades]})
    t_decades = [{"name": _decade_label(d), "count": _int(dec_vc[d]),
                  "cols": [f"{s['data'][i]:.1f}" for s in dec_series]}
                 for i, d in enumerate(decades)]

    # Makers
    known_m = df[df["maker"] != UNKNOWN]
    mvc = _ranked(known_m["maker"])
    n_known_m = len(known_m)
    m_names, m_vals = _top_other(mvc, TOP_MAKERS)
    unknown_m = n - n_known_m

    # Countries
    known_c = df[df["country"] != UNKNOWN]
    cvc = _ranked(known_c["country"])
    n_known_c = len(known_c)
    c_names, c_vals = _top_other(cvc, TOP_COUNTRIES)
    unknown_c = n - n_known_c
    il_rank = (list(cvc.index).index("ישראל") + 1) if "ישראל" in cvc.index else None

    # Country mix by decade (qualifying decades only)
    mix_top = list(cvc.index[:MIX_COUNTRIES])
    kc = known_c[(known_c["year"] >= YEAR_FLOOR)].copy()
    kc["decade"] = (kc["year"] // 10 * 10).astype(int)
    kc["cgrp"] = kc["country"].where(kc["country"].isin(mix_top), OTHER)
    kdec = kc["decade"].value_counts().sort_index()
    mix_decades = [int(d) for d in kdec.index if kdec[d] >= MIN_DECADE]
    kg = kc.groupby(["decade", "cgrp"]).size()
    mix_names = mix_top + ([OTHER] if (kc["cgrp"] == OTHER).any() else [])
    mix_series = [{"name": c, "data": [round(kg.get((d, c), 0) / kdec[d] * 100, 1) for d in mix_decades],
                   "counts": [int(kg.get((d, c), 0)) for d in mix_decades]} for c in mix_names]
    t_mix = [{"name": _decade_label(d), "count": _int(kdec[d]),
              "cols": [f"{s['data'][i]:.1f}" for s in mix_series]} for i, d in enumerate(mix_decades)]
    rule_decades = [d for d in mix_decades if kdec[d] >= MIN_DECADE_RULE]
    d0 = rule_decades[0] if rule_decades else None
    d1 = rule_decades[-1] if rule_decades else None
    mix_rows = []
    if d0 is not None and d1 is not None:
        for c in mix_names:
            mix_rows.append((c, kg.get((d0, c), 0) / kdec[d0], kg.get((d1, c), 0) / kdec[d1]))

    # Israel-made
    il = df[df["country"] == "ישראל"]
    n_il = len(il)
    il_vc = _ranked(il[il["maker"] != UNKNOWN]["maker"])
    il_names, il_vals = _top_other(il_vc, TOP_ISRAEL)
    il_fam = _ranked(il["family"])

    # Fuel
    fuel_known = df[df["fuel"] != UNKNOWN]
    fvc = _ranked(fuel_known["fuel"])
    n_known_f = len(fuel_known)
    f_names, f_vals = [str(x) for x in fvc.index], [int(v) for v in fvc]
    unknown_f = n - n_known_f
    n_ev = int(sum(fvc.get(k, 0) for k in ELECTRIFIED))
    unk_f_fam = _ranked(df.loc[df["fuel"] == UNKNOWN, "family"])
    unk_f_lead = (unk_f_fam.index[0] if len(unk_f_fam) and unk_f_fam.iloc[0] / max(unknown_f, 1) > 0.5
                  else None)

    # Engine size, passenger cars (M1)
    cars = df[(df["code"] == "M1") & (df["cc"] > 0) & (df["cc"] <= CC_MAX)].copy()
    n_cars_cc = len(cars)
    cc_counts = [int(((cars["cc"] >= lo) & (cars["cc"] <= hi)).sum()) for lo, hi, _ in CC_BINS]
    cc_labels = [lab for _, _, lab in CC_BINS]
    med_cc = int(cars["cc"].median()) if n_cars_cc else 0
    cars_y = cars[cars["year"] >= YEAR_FLOOR].copy()
    cars_y["decade"] = (cars_y["year"] // 10 * 10).astype(int)
    cc_g = cars_y.groupby("decade")["cc"]
    cc_med = cc_g.median()
    cc_cnt = cc_g.size()
    cc_dec = [(int(d), float(cc_med[d]), int(cc_cnt[d])) for d in cc_med.index if cc_cnt[d] >= MIN_DECADE]
    cc_dec.sort()
    cc_q1 = cc_g.quantile(0.25)
    cc_q3 = cc_g.quantile(0.75)
    cc_trend = {"x": [_decade_label(d) for d, _, _ in cc_dec],
                "med": [int(m) for _, m, _ in cc_dec],
                "q1": [int(cc_q1[d]) for d, _, _ in cc_dec],
                "q3": [int(cc_q3[d]) for d, _, _ in cc_dec],
                "n": [c for _, _, c in cc_dec]}
    t_cc_trend = [{"name": cc_trend["x"][i], "q1": _int(cc_trend["q1"][i]), "med": _int(cc_trend["med"][i]),
                   "q3": _int(cc_trend["q3"][i]), "count": _int(cc_trend["n"][i])}
                  for i in range(len(cc_dec))]
    no_cc = int((df["code"] == "M1").sum()) - n_cars_cc

    # Drive
    dvc = _ranked(df["drive"])
    d_names, d_vals = _top_other(dvc, TOP_DRIVE)

    # Models (maker + model name)
    mm = df[(df["model"] != "") & (df["maker"] != UNKNOWN)]
    mm_vc = (mm.groupby(["maker", "model"]).size().reset_index(name="n")
             .sort_values(["n", "maker", "model"], ascending=[False, True, True], kind="stable"))
    model_rows = [{"name": f"{r.maker} {r.model}", "n": int(r.n)} for r in mm_vc.head(TOP_MODELS).itertuples()]
    n_mm = len(mm)

    # ── Insights ────────────────────────────────────────────────────────
    rules = [
        ("era", insight_era(year_vc, n_valid, pre_share)),
        ("family", insight_family(fam_vc, n)),
        ("maker", insight_maker(mvc, n_known_m)),
        ("country", insight_country(cvc, n_known_c)),
        ("shift", insight_shift(mix_rows, d0, d1)),
        ("israel", insight_israel(il_vc, n_il, n_known_c, il_rank)),
        ("fuel", insight_fuel(fvc, n_known_f)),
        ("cc", insight_cc(cc_dec)),
        ("model", insight_model(model_rows)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    top_fam = fam_vc.index[0]
    summary = (f"איתור מספר רכב במאגר כלי הרכב הלא פעילים וחסרי קוד הדגם: {_int(n)} כלי רכב, "
               f"לפי יצרן, דגם, שנת ייצור וסוג דלק.")
    if len(summary) > 155:
        summary = f"איתור מספר רכב במאגר כלי הרכב הלא פעילים: {_int(n)} כלי רכב."

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "registry",
            "related_ids": [
                "fe8604fe-2d71-4cb5-a35e-2df97756c5a4",
                "273c5e33-25ab-4980-8522-a2f7ba0bb62d",
                "0f16b39a-6016-408d-805d-31f40d5a0990",
                "0219b34f-43c7-435b-bdfe-e65e944cde50",
                "392abd0a-64f6-4c18-9d56-0111001411e6",
            ],
            "suggested_tags": ["כלי רכב", "רכב לא פעיל", "רישוי רכב", "רכב ישן", "תחבורה"],
            "temporal_coverage": f"{y_first}/{y_last}",
        },
        "kpis": {
            "total": {"value": n, "display": _int(n), "tone": "brand"},
            "med_year": {"value": med_year, "display": str(med_year), "tone": "info"},
            "pre_share": {"value": round(pre_share, 4), "display": _pct(pre_share),
                          "tone": "warn" if pre_share >= 0.5 else "brand"},
            "makers": {"value": int(len(mvc)), "display": _int(len(mvc)), "tone": "brand"},
        },
        "charts": {
            "families": {"names": fam_names, "values": [int(fam_vc[f]) for f in fam_names]},
            "years": {"x": [str(y) for y in years], "series": year_series, "zoom_start": zoom_start},
            "decades": {"x": [_decade_label(d) for d in decades], "series": dec_series},
            "makers": {"names": m_names, "values": m_vals},
            "countries": {"names": c_names, "values": c_vals},
            "mix": {"x": [_decade_label(d) for d in mix_decades], "series": mix_series},
            "israel": {"names": il_names, "values": il_vals},
            "fuel": {"names": f_names, "values": f_vals},
            "cc": {"names": cc_labels, "values": cc_counts},
            "cc_trend": cc_trend,
            "drive": {"names": d_names, "values": d_vals},
            "models": {"names": [r["name"] for r in model_rows], "values": [r["n"] for r in model_rows]},
        },
        "flags": {
            "mix": len(mix_decades) >= 2,
            "israel": len(il_vc) >= 2,
            "cc_trend": len(cc_dec) >= 2,
            "models": len(model_rows) >= 3,
        },
        "tables": {
            "families": fam_rows,
            "codes": code_rows,
            "decade_cols": [s["name"] for s in dec_series],
            "decades": t_decades,
            "makers": _rank_rows(m_names, m_vals, n_known_m),
            "countries": _rank_rows(c_names, c_vals, n_known_c),
            "mix_cols": [s["name"] for s in mix_series],
            "mix": t_mix,
            "israel": _rank_rows(il_names, il_vals, max(int(il_vc.sum()), 1)),
            "fuel": _rank_rows(f_names, f_vals, n_known_f),
            "cc": _rank_rows(cc_labels, cc_counts, n_cars_cc),
            "cc_trend": t_cc_trend,
            "drive": _rank_rows(d_names, d_vals, n),
            "models": _rank_rows([r["name"] for r in model_rows], [r["n"] for r in model_rows], n_mm),
        },
        "insights": insights,
        "labels": {
            "lede": (f"המאגר מונה {_int(n)} כלי רכב שאין להם קוד דגם במשרד התחבורה ושרישיונם "
                     f"אינו בתוקף כבר יותר מ-13 חודשים, אך הם לא דווחו כגנובים ולא בוטלו ביטול סופי. "
                     f"לכל רכב רשומים מספר הרישוי, מספר השלדה, היצרן וארץ הייצור, הדגם, שנת הייצור, "
                     f"קבוצת הרכב האירופית, סוג הדלק, נפח המנוע וההנעה. שנות הייצור משתרעות "
                     f"מ-{y_first} ועד {y_last}, ושנת הייצור החציונית היא {med_year}. "
                     f"המאגר מתעדכן מדי יום, ותמונת המצב שלהלן מחושבת מהגרסה האחרונה."),
            "lookup_title": "בדיקת מספר רכב במאגר כלי הרכב הלא פעילים ←",
            "lookup_sub": ("חיפוש חי בכל רשומות המאגר: מספר רכב (מספר רישוי), מספר שלדה, "
                           "שם יצרן, שם דגם ודגם מנוע."),
            "total_kpi": "כלי רכב לא פעילים במאגר",
            "med_year_kpi": "שנת ייצור חציונית",
            "pre_kpi": f"יוצרו לפני {PRE_YEAR}",
            "makers_kpi": "יצרנים שונים",
            "families_note": (f"חלוקה לפי קבוצת הרכב האירופית (tkina EU): M1 רכב נוסעים, N משא, "
                              f"L דו ותלת גלגלי, O גרורים, T טרקטורים. {top_fam} הם "
                              f"{_pct(fam_vc.iloc[0] / n)} מהמאגר."),
            "families_aria": f"תרשים עמודות: כלי רכב לא פעילים לפי קבוצת רכב, {top_fam} בראש.",
            "years_note": (f"מספר כלי הרכב לפי שנת ייצור ({y_first}-{y_last}), מחולק לפי קבוצת רכב. "
                           f"אפשר לגרור את הסרגל כדי להתמקד בטווח שנים."
                           + (f" לא כולל {_int(bad_year)} רשומות ששנת הייצור שלהן חסרה או מוקדמת "
                              f"מ-{YEAR_FLOOR} (בעיקר ערך ממלא כמו 1900)." if bad_year else "")),
            "years_aria": (f"תרשים עמודות מוערם: כלי רכב לא פעילים לפי שנת ייצור, {y_first}-{y_last}. "
                           f"השנה הנפוצה {int(year_vc.sort_index().sort_values(ascending=False, kind='stable').index[0])}."),
            "decades_note": "חלקה של כל קבוצת רכב מכלי הרכב שיוצרו בכל עשור (באחוזים).",
            "decades_aria": "תרשים עמודות מוערם: תמהיל קבוצות הרכב לפי עשור ייצור.",
            "makers_note": ("שמות היצרנים קטועים במקור לחמישה תווים. יצרנים מוכרים הושלמו ואוחדו "
                            "(למשל רנו צרפת ורנו ספרד, דימלר ומרצדס), והשאר מוצגים כפי שנרשמו."
                            + (f" לא כולל {_int(unknown_m)} רשומות בלי שם יצרן." if unknown_m else "")),
            "makers_aria": f"תרשים עמודות: {TOP_MAKERS} היצרנים הנפוצים במאגר, {m_names[0] if m_names else ''} בראש.",
            "countries_note": ("ארץ הייצור כפי שנרשמה, עם איחוד כתיבים (למשל ד. קוריאה וקוריאה הדרומית)."
                               + (f" לא כולל {_int(unknown_c)} רשומות שארץ הייצור שלהן חסרה או לא ידועה."
                                  if unknown_c else "")),
            "countries_aria": f"תרשים עמודות: {TOP_COUNTRIES} ארצות הייצור הנפוצות, {c_names[0] if c_names else ''} בראש.",
            "mix_note": (f"חלקה של כל ארץ ייצור מכלי הרכב שיוצרו בכל עשור (באחוזים). מוצגות "
                         f"{MIX_COUNTRIES} הארצות המובילות, ועשורים עם {_int(MIN_DECADE)} כלי רכב לפחות."),
            "mix_aria": "תרשים עמודות מוערם: תמהיל ארצות הייצור לפי עשור ייצור.",
            "israel_note": (f"{_int(n_il)} כלי רכב תוצרת ישראל, בעיקר "
                            f"{il_fam.index[0] if len(il_fam) else ''}"
                            f"{(', ובראש היצרנים ' + il_names[0]) if il_names else ''}. "
                            f"שמות יצרנים שלא הושלמו מוצגים קטועים, כפי שנרשמו."
                            if n_il else ""),
            "israel_aria": f"תרשים עמודות: היצרנים הנפוצים בכלי רכב תוצרת ישראל, {il_names[0] if il_names else ''} בראש.",
            "fuel_note": (f"{_int(n_ev)} כלי רכב חשמליים או היברידיים (חשמל/בנזין, חשמל/דיזל)."
                          + (f" לא כולל {_int(unknown_f)} רשומות שסוג הדלק שלהן לא נרשם"
                             + (f", רובן {unk_f_lead}." if unk_f_lead else ".")
                             if unknown_f else "")),
            "fuel_aria": f"תרשים עמודות: כלי רכב לא פעילים לפי סוג דלק, {f_names[0] if f_names else ''} בראש.",
            "cc_note": (f"רכב נוסעים (M1) לפי נפח מנוע בסמ״ק. החציון {_int(med_cc)} סמ״ק."
                        + (f" לא כולל {_int(no_cc)} כלי רכב נוסעים בלי נפח מנוע רשום או עם ערך לא סביר."
                           if no_cc else "")),
            "cc_aria": "תרשים עמודות: רכב נוסעים לא פעיל לפי טווח נפח מנוע.",
            "cc_trend_note": ("נפח המנוע של רכב נוסעים לפי עשור הייצור: הקו הוא החציון, והרצועה "
                              f"נמתחת מהרבעון התחתון לעליון. עשורים עם {_int(MIN_DECADE)} כלי רכב לפחות."),
            "cc_trend_aria": "תרשים קו: נפח מנוע חציוני של רכב נוסעים לפי עשור ייצור.",
            "drive_note": ("תצורת ההנעה: מספר הגלגלים מול מספר הגלגלים המונעים (למשל 4X2). "
                           "לגרורים אין הנעה, ובחלק גדול מהרשומות ההנעה לא ידועה."),
            "drive_aria": f"תרשים עמודות: כלי רכב לא פעילים לפי תצורת הנעה, {d_names[0] if d_names else ''} בראש.",
            "models_note": (f"שם הדגם כפי שנרשם, יחד עם היצרן. כתיבים שונים של אותו דגם נספרים בנפרד. "
                            f"מתוך {_int(n_mm)} רשומות עם שם דגם ויצרן."),
            "models_aria": f"תרשים עמודות: {TOP_MODELS} הדגמים הנפוצים במאגר.",
        },
    }
