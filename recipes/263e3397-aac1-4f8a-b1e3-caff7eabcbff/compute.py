"""חניוני חנה וסע: the Ministry of Transport's GIS layer of park-and-ride lots
on the public-transport priority network, one row per lot (~186).

The layer is a slowly edited registry: a lot is added, re-counted or has its
amenities filled in, and D_UPDATE moves for the rows that changed. Every
count, share, leader and name below is computed from the current file.

Conventions found in the data and handled here:
- PARK_N is the number of parking spaces counted (mostly from 2023 aerial
  photographs, SOURCE). Some lots carry 0: an unmarked or uncountable lot
  (two-storey, under a bridge). Those count as lots but are left out of the
  per-lot size figures (median, density), and the page says how many.
- DUNAM is the lot's area (it equals Shape_Area / 1000). Spaces per dunam is
  computed only where both are positive.
- PAY is כן / לא / blank: blanks are "not recorded" and are shown as such,
  never folded into free.
- ELECTRIC / BIC_PARK (EV charging points, bicycle spaces) are filled for a
  handful of lots only: they are summarised over the lots that report them.
- RAIL_MAKAT is the Israel Railways station code (0 = none). Distinct
  non-zero codes give the number of stations the lots serve.
- X / Y are ITM; the map (GovMap) reads them from the datastore directly.
"""
import pandas as pd
from govlib import fmt, frame

ID = "ID"
NAME = "NAME"
AUTH = "AUTHORITY"
TRAF = "TRAFAUTH"
DIST = "DISTRICT"
PARK = "PARK_N"
DUNAM = "DUNAM"
SOURCE = "SOURCE"
UPDATED = "D_UPDATE"
RAIL = "RAIL_MAKAT"
STATUS = "STATUS"
BUS = "BUS_SERV"
TRAIN = "TRAIN_SERV"
LRT = "LRT_SERV"
PAY = "PAY"
BIKE = "BIC_PARK"
EV = "ELECTRIC"

YES = "כן"
NO = "לא"
EXISTING = "קיים"
OTHER = "אחר"
NO_DISTRICT = "ללא מחוז"
NO_AUTH = "לא צוין"

TOP_LOTS = 15
TOP_AUTH = 12
TOP_TRAF = 10
RECENT_N = 10
CONC_TOP = 10            # "the N largest lots hold X% of the spaces"
CONC_MIN_SHARE = 0.25    # state the concentration only above this share
LEAD_MIN_SHARE = 0.25    # a district "leads" only with at least this share of spaces
TRAIN_RATIO_MIN = 1.25   # median size gap (train vs no train) worth a sentence
MIN_GROUP = 5            # lots needed on each side of a comparison
SIZE_BINS = [(1, 49), (50, 99), (100, 199), (200, 499), (500, 999), (1000, None)]


def _num(s):
    return frame.num(s)


def _size_label(lo, hi):
    if hi is None:
        return f"{lo:,} ומעלה"
    return f"{lo:,}-{hi:,}"


def _tone_share(share, good=0.5):
    return "ok" if share >= good else "brand"


def compute(frames):
    df = frames["main"].copy()
    for c in (ID, NAME, AUTH, TRAF, DIST, PARK, DUNAM, SOURCE, UPDATED, RAIL,
              STATUS, BUS, TRAIN, LRT, PAY, BIKE, EV):
        df[c] = frame.clean_series(df[c])
    df = df[df[NAME] != ""].copy()
    df["id"] = _num(df[ID])
    df["spaces"] = _num(df[PARK]).clip(lower=0).fillna(0)
    df["dunam"] = _num(df[DUNAM])
    df["district"] = df[DIST].where(df[DIST] != "", NO_DISTRICT)
    df["auth"] = df[AUTH].where(df[AUTH] != "", NO_AUTH)
    df["traf"] = df[TRAF].where(df[TRAF] != "", NO_AUTH)
    df["train"] = df[TRAIN] == YES
    df["lrt"] = df[LRT] == YES
    df["bus"] = df[BUS] == YES
    df["ev"] = _num(df[EV])
    df["bike"] = _num(df[BIKE])
    df["upd"] = pd.to_datetime(df[UPDATED].str.slice(0, 10), format="%d/%m/%Y", errors="coerce")
    # Total order for every per-lot listing: spaces desc, then name, then id.
    df = df.sort_values(["spaces", NAME, "id"], ascending=[False, True, True], kind="stable")
    df = df.reset_index(drop=True)

    n = len(df)
    total = float(df["spaces"].sum())
    counted = df[df["spaces"] > 0]
    n_zero = n - len(counted)
    median = float(counted["spaces"].median()) if len(counted) else 0.0

    # ---- districts --------------------------------------------------------------
    g = df.groupby("district")
    d_rows = sorted(((k, len(s), float(s["spaces"].sum())) for k, s in g),
                    key=lambda r: (-r[2], -r[1], r[0]))
    chart_district = {"names": [r[0] for r in d_rows],
                      "lots": [r[1] for r in d_rows],
                      "spaces": [int(r[2]) for r in d_rows]}
    t_district = [[r[0], fmt.int_he(r[1]), fmt.int_he(r[2]),
                   fmt.pct(r[2] / total) if total else "–"] for r in d_rows]

    # ---- largest lots --------------------------------------------------------------
    top = counted.head(TOP_LOTS)
    chart_top = {"names": top[NAME].tolist(),
                 "values": [int(v) for v in top["spaces"]],
                 "auth": top["auth"].tolist(),
                 "train": [bool(v) for v in top["train"]]}
    t_top = [[r[NAME], r["auth"], fmt.int_he(r["spaces"]), YES if r["train"] else NO]
             for _, r in top.iterrows()]

    # ---- size distribution ----------------------------------------------------------
    size_names, size_lots, size_spaces, t_size = [], [], [], []
    for lo, hi in SIZE_BINS:
        m = df["spaces"] >= lo
        if hi is not None:
            m &= df["spaces"] <= hi
        lab = _size_label(lo, hi)
        size_names.append(lab)
        size_lots.append(int(m.sum()))
        size_spaces.append(int(df.loc[m, "spaces"].sum()))
        t_size.append([lab, fmt.int_he(m.sum()), fmt.int_he(df.loc[m, "spaces"].sum())])
    chart_size = {"names": size_names, "lots": size_lots, "spaces": size_spaces}

    # ---- connections (modes) ------------------------------------------------------
    modes = [("רכבת ישראל", "train"), ("רכבת קלה", "lrt"), ("אוטובוס", "bus")]
    chart_modes = {"names": [m[0] for m in modes],
                   "lots": [int(df[c].sum()) for _, c in modes],
                   "spaces": [int(df.loc[df[c], "spaces"].sum()) for _, c in modes]}
    t_modes = [[name, fmt.int_he(df[c].sum()), fmt.pct(df[c].mean()) if n else "–",
                fmt.int_he(df.loc[df[c], "spaces"].sum())] for name, c in modes]

    # ---- payment ------------------------------------------------------------------
    pay_cats = [("חינם", df[PAY] == NO), ("בתשלום", df[PAY] == YES),
                ("לא צוין", ~df[PAY].isin([YES, NO]))]
    chart_pay = [{"name": k, "lots": int(m.sum()), "spaces": int(df.loc[m, "spaces"].sum())}
                 for k, m in pay_cats if m.any()]
    t_pay = [[r["name"], fmt.int_he(r["lots"]), fmt.int_he(r["spaces"])] for r in chart_pay]
    n_paid = int((df[PAY] == YES).sum())
    n_free = int((df[PAY] == NO).sum())
    n_pay_known = n_paid + n_free

    # ---- local authorities ---------------------------------------------------------
    a_sum = df.groupby("auth")["spaces"].sum()
    a_cnt = df.groupby("auth").size()
    a_order = sorted(a_sum.index, key=lambda k: (-float(a_sum[k]), -int(a_cnt[k]), k))
    a_top = a_order[:TOP_AUTH]
    a_rest = a_order[TOP_AUTH:]
    auth_rows = [(k, int(a_cnt[k]), float(a_sum[k])) for k in a_top]
    if len(a_rest) == 1:
        auth_rows.append((a_rest[0], int(a_cnt[a_rest[0]]), float(a_sum[a_rest[0]])))
    elif a_rest:
        auth_rows.append((f"{OTHER} ({len(a_rest):,} רשויות)",
                          int(sum(int(a_cnt[k]) for k in a_rest)),
                          float(sum(float(a_sum[k]) for k in a_rest))))
    chart_auth = {"names": [r[0] for r in auth_rows],
                  "spaces": [int(r[2]) for r in auth_rows],
                  "lots": [r[1] for r in auth_rows]}
    t_auth = [[r[0], fmt.int_he(r[1]), fmt.int_he(r[2])] for r in auth_rows]
    n_auth = int(df.loc[df["auth"] != NO_AUTH, "auth"].nunique())

    # ---- traffic authority (who signs the lot) -----------------------------------
    t_cnt = frame.ranked(df["traf"])
    t_labels, t_values = frame.top_other(t_cnt, TOP_TRAF)
    chart_traf = {"names": t_labels, "values": [int(v) for v in t_values]}
    t_traf = [[k, fmt.int_he(v), fmt.pct(v / n) if n else "–"] for k, v in zip(t_labels, t_values)]

    # ---- area vs spaces (density) ----------------------------------------------------
    dens = df[(df["spaces"] > 0) & (df["dunam"] > 0)].copy()
    dens["per_dunam"] = dens["spaces"] / dens["dunam"]
    scatter = [[round(float(r["dunam"]), 2), int(r["spaces"]), r[NAME], bool(r["train"])]
               for _, r in dens.iterrows()]
    med_density = float(dens["per_dunam"].median()) if len(dens) else None

    # ---- recent updates -------------------------------------------------------------
    dated = df[df["upd"].notna()]
    mode_date = None
    mode_n = 0
    recent_rows = []
    if len(dated):
        dc = frame.ranked(dated["upd"])
        mode_date = dc.index[0]
        mode_n = int(dc.iloc[0])
        later = dated[dated["upd"] > mode_date].sort_values(
            ["upd", NAME, "id"], ascending=[False, True, True], kind="stable")
        for _, r in later.head(RECENT_N).iterrows():
            recent_rows.append([r[NAME], r["auth"], r["upd"].strftime("%d/%m/%Y"),
                                fmt.int_he(r["spaces"]) if r["spaces"] > 0 else "–"])
    n_later = int((dated["upd"] > mode_date).sum()) if mode_date is not None else 0
    last_date = dated["upd"].max() if len(dated) else None

    def mode_phrase():
        d = mode_date.strftime("%d/%m/%Y")
        if mode_n / n > 0.5:
            return (f"{fmt.int_he(mode_n)} מתוך {fmt.int_he(n)} הרשומות ({fmt.pct(mode_n / n)}) "
                    f"עודכנו לאחרונה ב-{d}")
        return f"תאריך העדכון הנפוץ ביותר הוא {d}, עם {fmt.int_he(mode_n)} רשומות"

    # ---- KPIs -------------------------------------------------------------------------
    train_spaces = float(df.loc[df["train"], "spaces"].sum())
    train_share = train_spaces / total if total else 0.0
    paid_share = n_paid / n_pay_known if n_pay_known else 0.0
    ev_rep = df[df["ev"].notna()]
    ev_total = float(ev_rep["ev"].sum()) if len(ev_rep) else 0.0
    kpis = {
        "lots": {"value": n, "display": fmt.int_he(n), "tone": "brand"},
        "spaces": {"value": int(total), "display": fmt.int_he(total), "tone": "brand"},
        "median": {"value": median, "display": fmt.int_he(median), "tone": "info"},
        "train_share": {"value": round(train_share, 4), "display": fmt.pct(train_share),
                        "tone": _tone_share(train_share)},
        "paid": {"value": n_paid, "display": fmt.int_he(n_paid),
                 "tone": "warn" if paid_share >= 0.2 else "brand"},
        "authorities": {"value": n_auth, "display": fmt.int_he(n_auth), "tone": "brand"},
    }

    # ---- insights ----------------------------------------------------------------------
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    def ins_concentration():
        if len(counted) < CONC_TOP * 2 or not total:
            return None
        share = float(counted.head(CONC_TOP)["spaces"].sum()) / total
        if share < CONC_MIN_SHARE:
            return None
        big = counted.iloc[0]
        return (f"החניונים גדולים באופן לא אחיד: {CONC_TOP:,} החניונים הגדולים מחזיקים "
                f"{fmt.pct(share)} מכלל {fmt.int_he(total)} המקומות. הגדול ביותר, "
                f"{big[NAME]} ({big['auth']}), רשום עם {fmt.int_he(big['spaces'])} מקומות, "
                f"{fmt.pct(big['spaces'] / total)} מהסך הכול.")

    def ins_district():
        if not d_rows or not total:
            return None
        k, lots, sp = d_rows[0]
        share = sp / total
        if share < LEAD_MIN_SHARE or len(d_rows) < 2:
            return None
        k2, sp2 = d_rows[1][0], d_rows[1][2]
        head = (f"מחוז {k} מוביל עם {fmt.int_he(lots)} חניונים ו-{fmt.int_he(sp)} מקומות "
                f"({fmt.pct(share)} מהמקומות)")
        if sp2 and sp / sp2 >= 1.5:
            return head + f", פי {sp / sp2:.1f} ממחוז {k2} שאחריו ({fmt.int_he(sp2)} מקומות)."
        return head + f". אחריו מחוז {k2} עם {fmt.int_he(sp2)} מקומות."

    def ins_train():
        tr = counted[counted["train"]]
        nt = counted[~counted["train"]]
        if len(tr) < MIN_GROUP or len(nt) < MIN_GROUP:
            return None
        m_tr, m_nt = float(tr["spaces"].median()), float(nt["spaces"].median())
        n_tr = int(df["train"].sum())
        stations = df.loc[df["train"] & (_num(df[RAIL]) > 0), RAIL].nunique()
        base = (f"{fmt.int_he(n_tr)} מתוך {fmt.int_he(n)} החניונים ({fmt.pct(n_tr / n)}) "
                f"צמודים לתחנת רכבת ישראל, ומשרתים {fmt.int_he(stations)} תחנות שונות")
        if m_nt and m_tr / m_nt >= TRAIN_RATIO_MIN:
            return (base + f". החניון החציוני ליד רכבת גדול יותר: {fmt.int_he(m_tr)} מקומות "
                    f"לעומת {fmt.int_he(m_nt)} בחניון שאינו ליד רכבת.")
        if m_tr and m_nt / m_tr >= TRAIN_RATIO_MIN:
            return (base + f". דווקא החניון החציוני שאינו ליד רכבת גדול יותר: {fmt.int_he(m_nt)} "
                    f"מקומות לעומת {fmt.int_he(m_tr)} ליד רכבת.")
        return base + "."

    def ins_pay():
        if n_pay_known < MIN_GROUP:
            return None
        unknown = n - n_pay_known
        tail = (f" ב-{fmt.int_he(unknown)} חניונים נוספים לא צוין אם החניה בתשלום."
                if unknown else "")
        if n_paid == 0:
            return f"בכל {fmt.int_he(n_pay_known)} החניונים שבהם הדבר צוין, החניה חינם." + tail
        paid = df[df[PAY] == YES]
        free = df[df[PAY] == NO]
        mp = float(paid.loc[paid["spaces"] > 0, "spaces"].median()) if (paid["spaces"] > 0).any() else None
        mf = float(free.loc[free["spaces"] > 0, "spaces"].median()) if (free["spaces"] > 0).any() else None
        size = ""
        if mp and mf and mp / mf >= TRAIN_RATIO_MIN:
            size = (f" החניונים בתשלום גדולים יותר (חציון {fmt.int_he(mp)} מקומות לעומת "
                    f"{fmt.int_he(mf)} בחינם).")
        return (f"החניה חינם ב-{fmt.int_he(n_free)} מתוך {fmt.int_he(n_pay_known)} החניונים "
                f"שבהם צוין אופן התשלום ({fmt.pct(n_free / n_pay_known)}), ובתשלום "
                f"ב-{fmt.int_he(n_paid)}.{size}{tail}")

    def ins_density():
        if med_density is None or len(dens) < MIN_GROUP:
            return None
        m2 = 1000 / med_density
        return (f"בחניון החציוני יש {fmt.num_he(med_density)} מקומות לדונם, כלומר כ-{fmt.int_he(m2)} מ\"ר "
                f"לכל מקום חניה כולל מעברים (מחושב על {fmt.int_he(len(dens))} חניונים עם שטח "
                f"ומספר מקומות רשומים).")

    def ins_zero():
        if not n_zero:
            return None
        return (f"ב-{fmt.int_he(n_zero)} חניונים מספר המקומות רשום כאפס (לא נספרו מקומות). "
                f"הם נכללים בספירת החניונים, אך לא בגודל החציוני ובצפיפות.")

    def ins_status():
        other = df[df[STATUS] != EXISTING]
        if not len(other):
            return None
        vc = frame.ranked(other[STATUS].where(other[STATUS] != "", "ללא סטטוס"))
        parts = fmt.join_he([f"{fmt.int_he(v)} במעמד \"{k}\"" for k, v in vc.items()])
        names = fmt.join_he(sorted(other[NAME].tolist())[:3])
        more = " ועוד" if len(other) > 3 else ""
        return (f"{fmt.int_he((df[STATUS] == EXISTING).sum())} חניונים רשומים כקיימים, "
                f"ו-{parts} ({names}{more}).")

    def ins_lrt():
        n_lrt = int(df["lrt"].sum())
        if not n_lrt:
            return None
        cities = sorted(df.loc[df["lrt"], "auth"].unique())
        return (f"{fmt.int_he(n_lrt)} חניונים מחוברים לרכבת הקלה, עם {fmt.int_he(df.loc[df['lrt'], 'spaces'].sum())} "
                f"מקומות בסך הכול ({fmt.join_he(cities)}).")

    def ins_ev():
        if len(ev_rep) < 3:
            return None
        pos = ev_rep[ev_rep["ev"] > 0].sort_values(["ev", NAME], ascending=[False, True], kind="stable")
        if not len(pos):
            return None
        lead = pos.iloc[0]
        where = "הרוב" if lead["ev"] / ev_total >= 0.5 else "המספר הגבוה ביותר"
        return (f"נתוני עמדות טעינה לרכב חשמלי מולאו ל-{fmt.int_he(len(ev_rep))} חניונים בלבד, "
                f"ובהם {fmt.int_he(ev_total)} עמדות בסך הכול; {where} בחניון {lead[NAME]} "
                f"({fmt.int_he(lead['ev'])} עמדות).")

    def ins_source():
        src = frame.ranked(df[SOURCE].where(df[SOURCE] != "", "לא צוין"))
        if not len(src):
            return None
        k, v = src.index[0], int(src.iloc[0])
        if v / n < 0.5:
            return None
        tail = ""
        if mode_date is not None:
            tail = f" {mode_phrase()}."
            if n_later and last_date is not None:
                tail += (f" {fmt.int_he(n_later)} חניונים עודכנו אחרי תאריך זה, האחרון "
                         f"ב-{last_date.strftime('%d/%m/%Y')}.")
        return (f"{fmt.int_he(v)} מתוך {fmt.int_he(n)} החניונים ({fmt.pct(v / n)}) נספרו "
                f"מאותו מקור (\"{k}\").{tail}")

    add("concentration", ins_concentration())
    add("district", ins_district())
    add("train", ins_train())
    add("pay", ins_pay())
    add("lrt", ins_lrt())
    add("density", ins_density())
    add("status", ins_status())
    add("zero", ins_zero())
    add("ev", ins_ev())
    add("source", ins_source())

    # ---- labels ---------------------------------------------------------------------------
    lead_d = d_rows[0][0] if d_rows else ""
    big = counted.iloc[0] if len(counted) else None
    a_lead = auth_rows[0] if auth_rows else None
    lede = (f"המאגר של משרד התחבורה מפרט {fmt.int_he(n)} חניוני חנה וסע ברשת נתיבי ההעדפה "
            f"עם {fmt.int_he(total)} מקומות חניה ב-{fmt.int_he(n_auth)} רשויות. "
            f"{fmt.pct(train_share)} מהמקומות נמצאים בחניונים הצמודים לתחנת רכבת. "
            f"לכל חניון רשומים מיקום, מספר מקומות, שטח, חיבור לרכבת, לרכבת הקלה ולאוטובוס, והאם החניה בתשלום.")
    labels = {
        "lede": lede,
        "spaces_kpi": "מקומות חניה בסך הכול",
        "median_kpi": "מקומות בחניון החציוני",
        "train_kpi": "מהמקומות בחניונים ליד תחנת רכבת",
        "paid_kpi": f"חניונים בתשלום (מתוך {fmt.int_he(n_pay_known)} שצוין בהם)",
        "map_note": (f"כל נקודה היא חניון. לחיצה על נקודה מציגה את שמו, הרשות, מספר המקומות "
                     f"והחיבורים לתחבורה ציבורית. המפה מציגה את כל {fmt.int_he(n)} החניונים."),
        "district_note": (f"מחוז {lead_d} מחזיק {fmt.pct(d_rows[0][2] / total)} מהמקומות. "
                          f"העמודות מראות את מספר המקומות, והקו את מספר החניונים." if d_rows and total else ""),
        "district_aria": (f"גרף עמודות: מקומות חניה וחניונים לפי מחוז. המוביל: {lead_d} "
                          f"עם {fmt.int_he(d_rows[0][2])} מקומות." if d_rows else "גרף מקומות לפי מחוז"),
        "top_note": (f"{TOP_LOTS:,} החניונים עם מספר המקומות הגבוה ביותר. כחול כהה: צמוד לתחנת רכבת. "
                     f"הגדול ביותר: {big[NAME]} עם {fmt.int_he(big['spaces'])} מקומות." if big is not None else ""),
        "top_aria": (f"גרף עמודות אופקי: {TOP_LOTS:,} חניוני חנה וסע הגדולים. הגדול: {big[NAME]}, "
                     f"{fmt.int_he(big['spaces'])} מקומות." if big is not None else "גרף החניונים הגדולים"),
        "size_note": (f"החניון החציוני מחזיק {fmt.int_he(median)} מקומות. "
                      f"{fmt.int_he(n_zero)} חניונים ללא מספר מקומות רשום אינם בגרף." if n_zero else
                      f"החניון החציוני מחזיק {fmt.int_he(median)} מקומות."),
        "size_aria": f"גרף עמודות: התפלגות החניונים לפי מספר מקומות. חציון {fmt.int_he(median)} מקומות.",
        "modes_note": (f"חניון יכול להיות מחובר לכמה אמצעים. {fmt.int_he(df['bus'].sum())} מתוך "
                       f"{fmt.int_he(n)} החניונים משורתים באוטובוס, {fmt.int_he(df['train'].sum())} ברכבת ישראל "
                       f"ו-{fmt.int_he(df['lrt'].sum())} ברכבת הקלה."),
        "modes_aria": (f"גרף עמודות: חניונים לפי חיבור לתחבורה ציבורית. רכבת ישראל "
                       f"{fmt.int_he(df['train'].sum())}, רכבת קלה {fmt.int_he(df['lrt'].sum())}, "
                       f"אוטובוס {fmt.int_he(df['bus'].sum())}."),
        "pay_note": (f"{fmt.int_he(n_free)} חניונים חינם ו-{fmt.int_he(n_paid)} בתשלום; "
                     f"ב-{fmt.int_he(n - n_pay_known)} לא צוין."),
        "pay_aria": (f"תרשים טבעת: חניונים לפי תשלום. חינם {fmt.int_he(n_free)}, בתשלום "
                     f"{fmt.int_he(n_paid)}, לא צוין {fmt.int_he(n - n_pay_known)}."),
        "auth_note": (f"{a_lead[0]} מובילה עם {fmt.int_he(a_lead[2])} מקומות ב-{fmt.int_he(a_lead[1])} חניונים."
                      if a_lead else ""),
        "auth_aria": (f"גרף עמודות אופקי: מקומות חניה לפי רשות מקומית. המובילה: {a_lead[0]}, "
                      f"{fmt.int_he(a_lead[2])} מקומות." if a_lead else "גרף מקומות לפי רשות"),
        "traf_note": (f"רשות התמרור היא הגוף שאחראי על הסדרי התנועה בחניון. {t_labels[0]} רשומה "
                      f"ב-{fmt.int_he(t_values[0])} חניונים ({fmt.pct(t_values[0] / n)})." if t_labels else ""),
        "traf_aria": (f"גרף עמודות אופקי: חניונים לפי רשות התמרור. המובילה: {t_labels[0]}, "
                      f"{fmt.int_he(t_values[0])} חניונים." if t_labels else "גרף לפי רשות תמרור"),
        "density_note": (f"כל נקודה היא חניון: שטח בדונם מול מספר המקומות. החציון הוא "
                         f"{fmt.num_he(med_density)} מקומות לדונם. נקודות גבוהות מהקו מרמזות על חניון "
                         f"רב-קומתי או על ספירה חריגה." if med_density else ""),
        "density_aria": (f"תרשים פיזור: שטח החניון מול מספר המקומות, {fmt.int_he(len(dens))} חניונים. "
                         f"חציון {fmt.num_he(med_density)} מקומות לדונם." if med_density else "תרשים פיזור"),
        "recent_note": (f"{mode_phrase()}. {fmt.int_he(n_later)} חניונים עודכנו אחרי תאריך זה; "
                        f"אלה האחרונים שבהם."
                        if mode_date is not None else ""),
    }

    summary = (f"{fmt.int_he(n)} חניוני חנה וסע ברשת נתיבי ההעדפה עם {fmt.int_he(total)} מקומות חניה; "
               f"{fmt.pct(train_share)} מהמקומות ליד תחנת רכבת, והמחוז המוביל הוא {lead_d}.")
    desc = (f"מפה ורשימה של {fmt.int_he(n)} חניוני חנה וסע בישראל: איתור חניון לפי עיר או תחנת רכבת, "
            f"מספר מקומות ({fmt.int_he(total)} בסך הכול) והאם החניה בתשלום.")

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "map",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "חניוני חנה וסע: מפה ורשימת חניונים לפי עיר",
                "description": desc,
                "name": "חניוני חנה וסע",
                "alternate_names": ["חנה וסע", "חניוני חנה-וסע", "חניון חנה וסע ליד תחנת רכבת",
                                    "חניוני חנה וסע של משרד התחבורה"],
            },
        },
        "kpis": kpis,
        "charts": {
            "district": chart_district,
            "top": chart_top,
            "size": chart_size,
            "modes": chart_modes,
            "pay": chart_pay,
            "auth": chart_auth,
            "traf": chart_traf,
            "density": {"points": scatter, "median": round(med_density, 2) if med_density else None},
        },
        "tables": {
            "district": t_district,
            "top": t_top,
            "size": t_size,
            "modes": t_modes,
            "pay": t_pay,
            "auth": t_auth,
            "traf": t_traf,
            "recent": recent_rows,
        },
        "flags": {
            "density": bool(med_density) and len(dens) >= MIN_GROUP,
            "recent": bool(recent_rows),
            "top": len(top) > 0,
        },
        "insights": insights,
        "labels": labels,
    }
