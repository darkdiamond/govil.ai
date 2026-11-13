"""דירות הדיור הציבורי (משרד הבינוי והשיכון): three tables about the public
housing stock.

- `vacant`: one row per habitable apartment vacant for over three months
  (city, rooms in halves, floor, area, managing company, the date its status
  last changed, the report date `ValidityDate`, property type). Months vacant
  are counted from the status-change date to the row's report date, never to
  a clock.
- `stock`: the whole stock, one row per (city, floor) with a count column per
  room count (NoRooms .. MoreRooms). An empty floor is "not stated".
- `purchases`: apartments bought into the stock, one row per (city, year):
  counts and average price of 3-room and 4+-room purchases. The national
  average price per year is weighted by the counts. When the newest purchase
  year is the report year (or later) it is treated as a year in progress:
  labelled partial and left out of the trend and price rules (disclosed).
  The two resources update separately, so the newest purchase year is also
  treated as partial when its count is below PARTIAL_FRAC of the median of
  the earlier years (a conservative rule: a genuinely weak full year is
  only left out of the trend sentences, never misstated).
- Half-room units (2.5, 1.5) exist only in the vacant table; the stock table
  has whole-room columns and doesn't say how it bins halves, so half-room
  units are left out of the rooms comparison and the area-by-rooms view
  (disclosed).
"""
import pandas as pd
from govlib import fmt, frame

TOP_CITIES = 15
RATE_MIN_STOCK = 200       # vacancy-rate ranking only for cities with this stock
DUR_EDGES = [0, 6, 12, 24, 36, 60]   # months; last bucket open-ended
FLOOR_EDGES = [(None, 0), (1, 1), (2, 2), (3, 3), (4, 4), (5, 7), (8, None)]
ROOM_COLS = ["NoRooms", "OneRooms", "TwoRooms", "ThreeRooms", "FourRooms",
             "FiveRooms", "SixRooms", "SevenRooms", "EightRooms", "NineRooms",
             "TenRooms", "MoreRooms"]
ROOM_N = {c: i for i, c in enumerate(ROOM_COLS)}   # MoreRooms counts as 11+
ROOM_CATS = [1, 2, 3, 4, 5]                        # 5 = five or more
ROOM_GAP_PTS = 5.0       # rooms/floor insight: a share gap of at least this
LONG_MONTHS = 24
VERY_LONG_MONTHS = 60
PARTIAL_FRAC = 0.25      # newest purchase year below this share of the median: partial
DATE_MIN_PARSED = 0.5    # fail when fewer status dates than this parse
C3 = "3 rooms apartments"
P3 = "average price (NIS) 3 rooms apartments"
C4 = "4+ rooms apartments"
P4 = "average price (NIS) 4+ rooms apartments"


def _room_label(k: int) -> str:
    if k == ROOM_CATS[-1]:
        return f"{k}+ חדרים"
    return "חדר אחד" if k == 1 else f"{k} חדרים"


def _room_cat(v: float) -> int:
    return max(ROOM_CATS[0], min(int(v), ROOM_CATS[-1]))


def _floor_label(lo, hi) -> str:
    if hi is not None and hi <= 0:
        return "קרקע ומרתף"
    if hi is None:
        return f"{lo}+"
    if lo == hi:
        return str(lo)
    return f"{lo}-{hi}"


def _floor_bucket(v: float) -> str | None:
    if pd.isna(v):
        return None
    for lo, hi in FLOOR_EDGES:
        if (lo is None or v >= lo) and (hi is None or v <= hi):
            return _floor_label(lo, hi)
    return None


def _dur_label(i: int) -> str:
    lo = DUR_EDGES[i]
    if i == len(DUR_EDGES) - 1:
        return f"מעל {lo}"
    hi = DUR_EDGES[i + 1]
    return f"עד {hi}" if lo == 0 else f"{lo}-{hi}"


def _share(part, whole) -> float:
    return float(part) / float(whole) if whole else 0.0


def compute(frames: dict[str, pd.DataFrame]) -> dict:
    v = frames["vacant"].copy()
    st = frames["stock"].copy()
    pu = frames["purchases"].copy()

    # ---- vacant apartments ---------------------------------------------
    v["city"] = frame.clean_series(v["CityLmsName"])
    v = v[v["city"] != ""]
    v["rooms"] = pd.to_numeric(v["NumOfRooms"], errors="coerce")
    v["floor"] = pd.to_numeric(v["Floor"], errors="coerce")
    v["area"] = pd.to_numeric(v["TotalArea"], errors="coerce")
    v["company"] = frame.clean_series(v["CompanyName"]).replace("", "לא צוין")
    v["ptype"] = frame.clean_series(v["PropertyTypeName"]).replace("", "לא צוין")
    v["since"] = pd.to_datetime(v["StatusChangeDate"], errors="coerce", format="%Y-%m-%d")
    v["asof"] = pd.to_datetime(v["ValidityDate"], errors="coerce", format="%Y-%m-%d")
    asof = v["asof"].max()
    if pd.isna(asof):
        raise ValueError("ValidityDate: no parseable report date")
    if v["since"].notna().mean() < DATE_MIN_PARSED:
        raise ValueError("StatusChangeDate: most dates don't parse")
    v["months"] = (v["asof"] - v["since"]).dt.days / 30.44
    n_vac = len(v)
    if n_vac == 0:
        raise ValueError("no vacant apartments")

    # ---- stock ---------------------------------------------------------
    st["city"] = frame.clean_series(st["CityLMSName"])
    st = st[st["city"] != ""]
    for c in ROOM_COLS:
        st[c] = pd.to_numeric(st[c], errors="coerce").fillna(0)
    st["tot"] = st[ROOM_COLS].sum(axis=1)
    st["floor"] = pd.to_numeric(st["Floor"], errors="coerce")
    n_stock = int(st["tot"].sum())
    if n_stock == 0:
        raise ValueError("empty stock")
    stock_city = st.groupby("city")["tot"].sum()
    stock_city = stock_city[stock_city > 0]
    n_stock_cities = len(stock_city)

    # ---- purchases -----------------------------------------------------
    pu["city"] = frame.clean_series(pu["Lamas_name"])
    pu["year"] = pd.to_numeric(pu["year"], errors="coerce")
    pu = pu[(pu["city"] != "") & pu["year"].notna()].copy()
    pu["year"] = pu["year"].astype(int)
    for c in [C3, P3, C4, P4]:
        pu[c] = frame.num(pu[c])
    pu["n3"] = pu[C3].fillna(0)
    pu["n4"] = pu[C4].fillna(0)
    pu["v3"] = (pu[C3] * pu[P3]).where(pu[C3].notna() & pu[P3].notna(), 0)
    pu["w3"] = pu[C3].where(pu[C3].notna() & pu[P3].notna(), 0)
    pu["v4"] = (pu[C4] * pu[P4]).where(pu[C4].notna() & pu[P4].notna(), 0)
    pu["w4"] = pu[C4].where(pu[C4].notna() & pu[P4].notna(), 0)
    py = pu.groupby("year")[["n3", "n4", "v3", "w3", "v4", "w4"]].sum().sort_index()
    years = [int(y) for y in py.index]
    n_purch = int(py["n3"].sum() + py["n4"].sum())
    partial_year = None
    partial_why = None
    if years:
        last = years[-1]
        earlier = [float(py.loc[y, "n3"] + py.loc[y, "n4"]) for y in years[:-1]]
        last_n = float(py.loc[last, "n3"] + py.loc[last, "n4"])
        if last >= asof.year:
            partial_year, partial_why = last, "report"
        elif len(earlier) >= 3 and last_n < PARTIAL_FRAC * float(pd.Series(earlier).median()):
            partial_year, partial_why = last, "low"
    full_years = [y for y in years if y != partial_year]

    def avg_price(y, k):
        w = py.loc[y, f"w{k}"]
        return float(py.loc[y, f"v{k}"] / w) if w > 0 else None

    insights = []
    labels = {}
    tables = {}
    charts = {}
    kpis = {}

    # ---- vacancy by city ------------------------------------------------
    vac_city = frame.ranked(v["city"])
    n_vac_cities = len(vac_city)
    top = vac_city.iloc[:TOP_CITIES]
    charts["vac_city"] = {
        "names": [str(k) for k in top.index],
        "vac": [int(x) for x in top],
        "stock": [int(stock_city.get(k, 0)) for k in top.index],
    }
    tables["vac_city"] = [
        [k, fmt.int_he(c), fmt.int_he(stock_city.get(k, 0)),
         fmt.pct(_share(c, stock_city.get(k, 0)), 1) if stock_city.get(k, 0) else "–"]
        for k, c in top.items()
    ]
    top5_share = _share(vac_city.iloc[:5].sum(), n_vac)
    labels["vac_city_lede"] = (
        f"הדירות הפנויות מפוזרות ב-{fmt.int_he(n_vac_cities)} יישובים. "
        f"בראש הרשימה {vac_city.index[0]} עם {fmt.int_he(vac_city.iloc[0])} דירות, "
        f"וחמשת היישובים הראשונים מרכזים {fmt.pct(top5_share)} מכלל הדירות הפנויות."
    )
    labels["vac_city_aria"] = f"דירות פנויות לפי יישוב, {len(top)} היישובים המובילים"

    # vacancy rate per city
    rate = pd.DataFrame({"vac": vac_city, "stock": stock_city}).fillna(0)
    rate = rate[rate["stock"] >= RATE_MIN_STOCK]
    rate["r"] = rate["vac"] / rate["stock"]
    rate = rate[rate["vac"] > 0].reset_index().rename(columns={"index": "city"})
    rate = rate.sort_values(["r", "city"], ascending=[False, True], kind="stable")
    rtop = rate.head(TOP_CITIES)
    charts["vac_rate"] = {
        "names": rtop["city"].tolist(),
        "rate": [round(float(x) * 100, 2) for x in rtop["r"]],
        "vac": [int(x) for x in rtop["vac"]],
        "stock": [int(x) for x in rtop["stock"]],
        "avg": round(_share(n_vac, n_stock) * 100, 2),
    }
    tables["vac_rate"] = [[r.city, fmt.pct(r.r, 1), fmt.int_he(r.vac), fmt.int_he(r.stock)]
                          for r in rtop.itertuples()]
    labels["vac_rate_lede"] = (
        f"שיעור הדירות הפנויות מתוך המלאי בכל יישוב שיש בו לפחות {fmt.int_he(RATE_MIN_STOCK)} "
        f"דירות דיור ציבורי. הממוצע הארצי הוא {fmt.pct(_share(n_vac, n_stock), 1)}."
    )
    if len(rtop):
        labels["vac_rate_lede"] += (
            f" ב{rtop.iloc[0]['city']} עומדות ריקות {fmt.pct(rtop.iloc[0]['r'], 1)} מהדירות."
        )
    labels["vac_rate_aria"] = "שיעור הדירות הפנויות מתוך מלאי הדיור הציבורי לפי יישוב"

    # ---- duration --------------------------------------------------------
    m = v["months"].dropna()
    m = m[m >= 0]
    vm = v.loc[m.index]
    dur_counts = []
    for i, lo in enumerate(DUR_EDGES):
        hi = DUR_EDGES[i + 1] if i + 1 < len(DUR_EDGES) else None
        sel = (m > lo) if lo > 0 else (m >= lo)
        if hi is not None:
            sel &= m <= hi
        dur_counts.append(int(sel.sum()))
    charts["duration"] = {"x": [_dur_label(i) for i in range(len(DUR_EDGES))], "y": dur_counts,
                          "long_from": next(i for i, e in enumerate(DUR_EDGES) if e >= LONG_MONTHS)}
    tables["duration"] = [[_dur_label(i), fmt.int_he(c), fmt.pct(_share(c, len(m)))]
                          for i, c in enumerate(dur_counts)]
    med_months = float(m.median()) if len(m) else None
    long_share = _share((m > LONG_MONTHS).sum(), len(m))
    very_long = int((m > VERY_LONG_MONTHS).sum())
    labels["dur_lede"] = (
        f"כמה זמן הדירה עומדת ריקה, מתאריך שינוי הסטטוס שלה ועד תאריך הדוח "
        f"({fmt.d_he(asof)})."
    )
    if med_months is not None:
        labels["dur_lede"] += (
            f" החציון הוא {fmt.num_he(med_months, 1)} חודשים, ו-{fmt.pct(long_share)} "
            f"מהדירות פנויות יותר משנתיים."
        )
    labels["dur_aria"] = "התפלגות הדירות הפנויות לפי משך הזמן שהן פנויות, בחודשים"

    # ---- company ---------------------------------------------------------
    comp = frame.ranked(v["company"])
    comp_med = vm.groupby("company")["months"].median()
    comp_cities = v.groupby("company")["city"].nunique()
    charts["company"] = {
        "names": [str(k) for k in comp.index],
        "vac": [int(x) for x in comp],
        "med": [round(float(comp_med.get(k)), 1) if pd.notna(comp_med.get(k)) else None
                for k in comp.index],
    }
    tables["company"] = [
        [k, fmt.int_he(c), fmt.pct(_share(c, n_vac)), fmt.int_he(comp_cities.get(k, 0)),
         fmt.num_he(comp_med.get(k), 1) if pd.notna(comp_med.get(k)) else "–"]
        for k, c in comp.items()
    ]
    labels["company_lede"] = (
        f"החברות המנהלות את הדירות. {comp.index[0]} מנהלת {fmt.int_he(comp.iloc[0])} "
        f"מהדירות הפנויות ({fmt.pct(_share(comp.iloc[0], n_vac))})."
    )
    labels["company_aria"] = "דירות פנויות לפי חברה מנהלת וחציון חודשי הפנייה"

    # ---- rooms: stock vs vacant -----------------------------------------
    st_rooms = {k: 0.0 for k in ROOM_CATS}
    for c in ROOM_COLS:
        n = ROOM_N[c]
        if n == 0:
            continue
        st_rooms[_room_cat(n)] += float(st[c].sum())
    no_rooms = int(st["NoRooms"].sum())
    st_rooms_tot = sum(st_rooms.values())
    vr = v["rooms"].dropna()
    n_half = int(((vr % 1) != 0).sum())
    vr = vr[(vr >= 1) & ((vr % 1) == 0)]
    vc_rooms = vr.map(_room_cat).value_counts()
    vac_rooms = {k: int(vc_rooms.get(k, 0)) for k in ROOM_CATS}
    vr_tot = sum(vac_rooms.values())
    charts["rooms"] = {
        "x": [_room_label(k) for k in ROOM_CATS],
        "stock": [round(_share(st_rooms[k], st_rooms_tot) * 100, 1) for k in ROOM_CATS],
        "vac": [round(_share(vac_rooms[k], vr_tot) * 100, 1) for k in ROOM_CATS],
        "stock_n": [int(st_rooms[k]) for k in ROOM_CATS],
        "vac_n": [int(vac_rooms[k]) for k in ROOM_CATS],
    }
    tables["rooms"] = [[_room_label(k), fmt.int_he(st_rooms[k]), fmt.pct(_share(st_rooms[k], st_rooms_tot)),
                        fmt.int_he(vac_rooms[k]), fmt.pct(_share(vac_rooms[k], vr_tot))] for k in ROOM_CATS]
    lead_room = max(ROOM_CATS, key=lambda k: (st_rooms[k], -k))
    labels["rooms_lede"] = (
        f"הרכב החדרים במלאי כולו לעומת הדירות הפנויות. במלאי שולטות דירות של "
        f"{_room_label(lead_room)} ({fmt.pct(_share(st_rooms[lead_room], st_rooms_tot))})."
    )
    if n_half:
        labels["rooms_lede"] += (f" {fmt.int_he(n_half)} דירות פנויות עם חצי חדר אינן בהשוואה, "
                                 "כי טבלת המלאי סופרת חדרים שלמים בלבד.")
    if no_rooms:
        labels["rooms_lede"] += f" {fmt.int_he(no_rooms)} דירות במלאי רשומות בלי חדרים ואינן בתרשים."
    labels["rooms_aria"] = "התפלגות מספר החדרים: מלאי הדיור הציבורי מול הדירות הפנויות, באחוזים"

    # ---- floors: stock vs vacant -----------------------------------------
    fl_labels = [_floor_label(lo, hi) for lo, hi in FLOOR_EDGES]
    st["fb"] = st["floor"].map(_floor_bucket)
    v["fb"] = v["floor"].map(_floor_bucket)
    st_fl = st.groupby("fb")["tot"].sum()
    v_fl = v["fb"].value_counts()
    st_fl_tot = float(st_fl.sum())
    v_fl_tot = float(v_fl.sum())
    charts["floor"] = {
        "x": fl_labels,
        "stock": [round(_share(st_fl.get(k, 0), st_fl_tot) * 100, 1) for k in fl_labels],
        "vac": [round(_share(v_fl.get(k, 0), v_fl_tot) * 100, 1) for k in fl_labels],
        "stock_n": [int(st_fl.get(k, 0)) for k in fl_labels],
        "vac_n": [int(v_fl.get(k, 0)) for k in fl_labels],
    }
    tables["floor"] = [[k, fmt.int_he(st_fl.get(k, 0)), fmt.pct(_share(st_fl.get(k, 0), st_fl_tot)),
                        fmt.int_he(v_fl.get(k, 0)), fmt.pct(_share(v_fl.get(k, 0), v_fl_tot))]
                       for k in fl_labels]
    no_floor = int(st.loc[st["fb"].isna(), "tot"].sum())
    hi_st = _share(st.loc[st["floor"] >= 3, "tot"].sum(), st_fl_tot)
    hi_v = _share((v["floor"] >= 3).sum(), v_fl_tot)
    max_floor = st.loc[st["tot"] > 0, "floor"].max()
    labels["floor_lede"] = (
        f"באיזו קומה נמצאות הדירות. מהקומה השלישית ומעלה נמצאות {fmt.pct(hi_st)} מהמלאי "
        f"ו-{fmt.pct(hi_v)} מהדירות הפנויות."
    )
    if pd.notna(max_floor):
        labels["floor_lede"] += f" הקומה הגבוהה ביותר במלאי היא {fmt.int_he(max_floor)}."
    if no_floor:
        labels["floor_lede"] += f" ל-{fmt.int_he(no_floor)} דירות במלאי לא צוינה קומה."
    labels["floor_aria"] = "התפלגות הקומות: מלאי הדיור הציבורי מול הדירות הפנויות, באחוזים"

    # ---- area by rooms (vacant) ------------------------------------------
    box_x, box_d, box_n, area_rows = [], [], [], []
    va = v[v["area"].notna() & (v["area"] > 0) & v["rooms"].notna() & (v["rooms"] >= 1)
           & ((v["rooms"] % 1) == 0)].copy()
    va["rc"] = va["rooms"].map(_room_cat)
    for k in ROOM_CATS:
        a = va.loc[va["rc"] == k, "area"]
        if len(a) == 0:
            continue
        q = [float(a.min()), float(a.quantile(0.25)), float(a.median()),
             float(a.quantile(0.75)), float(a.max())]
        box_x.append(_room_label(k))
        box_d.append([round(x, 1) for x in q])
        box_n.append(len(a))
        area_rows.append([_room_label(k), fmt.int_he(len(a)), fmt.num_he(q[2], 0),
                          f"{fmt.num_he(q[1], 0)}-{fmt.num_he(q[3], 0)}",
                          f"{fmt.num_he(q[0], 0)}-{fmt.num_he(q[4], 0)}"])
    charts["area"] = {"x": box_x, "data": box_d, "n": box_n}
    tables["area"] = area_rows
    med_area = float(va["area"].median()) if len(va) else None
    labels["area_lede"] = "שטח הדירות הפנויות לפי מספר החדרים: חציון, רבעונים וטווח (דירות עם חצי חדר אינן כלולות)."
    if med_area is not None:
        labels["area_lede"] += f" השטח החציוני של דירה פנויה הוא {fmt.num_he(med_area, 0)} מ\"ר."
    labels["area_aria"] = "שטח הדירות הפנויות במ\"ר לפי מספר חדרים, תרשים קופסה"

    # ---- property type ----------------------------------------------------
    ptype = frame.ranked(v["ptype"])
    tables["ptype"] = [[k, fmt.int_he(c), fmt.pct(_share(c, n_vac))] for k, c in ptype.items()]
    labels["ptype_lede"] = (f"הדירות הפנויות לפי סוג הנכס ברישום. הסוג הנפוץ הוא {ptype.index[0]}: "
                            f"{fmt.int_he(ptype.iloc[0])} דירות ({fmt.pct(_share(ptype.iloc[0], n_vac))}).")
    if len(ptype) > 1:
        labels["ptype_lede"] += f" ברשימה {fmt.int_he(len(ptype))} סוגי נכס."

    # ---- stock by city ----------------------------------------------------
    sc = stock_city.sort_index().sort_values(ascending=False, kind="stable")
    s_lab, s_val = frame.top_other(sc, TOP_CITIES)
    charts["stock_city"] = {"names": s_lab, "y": [int(x) for x in s_val],
                            "other_idx": len(s_lab) - 1 if s_lab and s_lab[-1] == frame.OTHER else -1}
    tables["stock_city"] = [[k, fmt.int_he(x), fmt.pct(_share(x, n_stock))] for k, x in zip(s_lab, s_val)]
    top_n_share = _share(sc.iloc[:TOP_CITIES].sum(), n_stock)
    labels["stock_city_lede"] = (
        f"המלאי פרוס על פני {fmt.int_he(n_stock_cities)} יישובים. {sc.index[0]} מחזיקה "
        f"{fmt.int_he(sc.iloc[0])} דירות ({fmt.pct(_share(sc.iloc[0], n_stock))}), "
        f"ו-{min(TOP_CITIES, len(sc))} היישובים הגדולים מחזיקים יחד {fmt.pct(top_n_share)} מהמלאי."
    )
    labels["stock_city_aria"] = "מלאי דירות הדיור הציבורי לפי יישוב"

    # ---- purchases by year ------------------------------------------------
    def ylab(y):
        return f"{y} (חלקי)" if y == partial_year else str(y)

    charts["purch_year"] = {"x": [ylab(y) for y in years],
                            "n3": [int(py.loc[y, "n3"]) for y in years],
                            "n4": [int(py.loc[y, "n4"]) for y in years]}
    tables["purch_year"] = [[ylab(y), fmt.int_he(py.loc[y, "n3"]), fmt.int_he(py.loc[y, "n4"]),
                             fmt.int_he(py.loc[y, "n3"] + py.loc[y, "n4"])] for y in years]
    labels["purch_lede"] = f"דירות שנרכשו למלאי בכל שנה, לפי גודל. בסך הכול {fmt.int_he(n_purch)} דירות"
    if years:
        labels["purch_lede"] += f" בשנים {years[0]}-{years[-1]}"
    labels["purch_lede"] += "."
    if partial_year is not None:
        labels["purch_lede"] += (f" שנת {partial_year} עדיין לא הסתיימה בתאריך הדוח." if partial_why == "report"
                                 else f" שנת {partial_year} נראית חלקית: נרשמו בה הרבה פחות רכישות משנים קודמות.")
    labels["purch_aria"] = "דירות שנרכשו למלאי הדיור הציבורי לפי שנה ומספר חדרים"

    # ---- price by year -----------------------------------------------------
    p3 = [avg_price(y, 3) for y in years]
    p4 = [avg_price(y, 4) for y in years]
    charts["price"] = {"x": [ylab(y) for y in years],
                       "p3": [round(x / 1e6, 3) if x is not None else None for x in p3],
                       "p4": [round(x / 1e6, 3) if x is not None else None for x in p4]}
    tables["price"] = [[ylab(y), fmt.num_he(a / 1e6, 2) if a is not None else "–",
                        fmt.num_he(b / 1e6, 2) if b is not None else "–"] for y, a, b in zip(years, p3, p4)]
    labels["price_lede"] = "המחיר הממוצע של דירה שנרכשה, משוקלל לפי מספר הדירות בכל יישוב."
    labels["price_aria"] = "מחיר ממוצע של דירה שנרכשה למלאי לפי שנה, במיליוני שקלים"

    # ---- purchases by city ----------------------------------------------
    pc = pu.groupby("city")[["n3", "n4"]].sum()
    pc["n"] = pc["n3"] + pc["n4"]
    pc = pc[pc["n"] > 0].reset_index().sort_values(["n", "city"], ascending=[False, True], kind="stable")
    ptop = pc.head(TOP_CITIES)
    charts["purch_city"] = {"names": ptop["city"].tolist(),
                            "n3": [int(x) for x in ptop["n3"]], "n4": [int(x) for x in ptop["n4"]]}
    tables["purch_city"] = [[r.city, fmt.int_he(r.n3), fmt.int_he(r.n4), fmt.int_he(r.n)]
                            for r in ptop.itertuples()]
    n_purch_cities = len(pc)
    labels["purch_city_lede"] = f"הרכישות נעשו ב-{fmt.int_he(n_purch_cities)} יישובים."
    if len(ptop):
        labels["purch_city_lede"] += (
            f" {ptop.iloc[0]['city']} מובילה עם {fmt.int_he(ptop.iloc[0]['n'])} דירות "
            f"({fmt.pct(_share(ptop.iloc[0]['n'], n_purch))})."
        )
    labels["purch_city_aria"] = "דירות שנרכשו למלאי לפי יישוב ומספר חדרים"

    # ---- KPIs ----------------------------------------------------------
    vac_share = _share(n_vac, n_stock)
    kpis["stock"] = {"value": n_stock, "display": fmt.int_he(n_stock), "tone": "brand"}
    kpis["vacant"] = {"value": n_vac, "display": fmt.int_he(n_vac), "tone": "brand"}
    kpis["share"] = {"value": round(vac_share * 100, 2), "display": fmt.pct(vac_share),
                     "tone": "warn" if vac_share >= 0.03 else "info"}
    if med_months is not None:
        kpis["months"] = {"value": round(med_months, 1), "display": fmt.num_he(med_months, 1),
                          "tone": "danger" if med_months >= 24 else ("warn" if med_months >= 12 else "ok")}
    else:
        kpis["months"] = {"value": None, "display": "–", "tone": "brand"}
    kpis["cities"] = {"value": n_stock_cities, "display": fmt.int_he(n_stock_cities), "tone": "brand"}
    kpis["purch"] = {"value": n_purch, "display": fmt.int_he(n_purch), "tone": "brand"}
    labels["purch_kpi"] = (f"דירות שנרכשו למלאי ({years[0]}-{years[-1]})" if years
                           else "דירות שנרכשו למלאי")
    labels["asof"] = fmt.d_he(asof)
    labels["partial_note"] = (
        f"שנת רכש נחשבת חלקית כשהיא שנת הדוח או מאוחרת לה, או כשמספר הרכישות בה נמוך מ-{fmt.pct(PARTIAL_FRAC, 0)} "
        f"מהחציון של השנים הקודמות. שנה כזו מסומנת בתרשים ואינה נכללת במשפטי המגמה והמחיר.")
    labels["half_note"] = (f"בטבלת המלאי החדרים נספרים בשלמים, ולכן {fmt.int_he(n_half)} דירות פנויות עם חצי חדר "
                           "אינן בהשוואת החדרים ובתרשים השטח." if n_half else
                           "בטבלת המלאי החדרים נספרים בשלמים; דירות עם חצי חדר אינן בהשוואת החדרים.")

    # ---- insights -------------------------------------------------------
    def add(i, t):
        if t:
            insights.append({"id": i, "text_he": t})

    add("share", f"מתוך {fmt.int_he(n_stock)} דירות במלאי הדיור הציבורי, {fmt.int_he(n_vac)} "
        f"({fmt.pct(vac_share)}) ראויות למגורים ועומדות פנויות יותר משלושה חודשים.")

    def ins_rate():
        if len(rate) < 3:
            return None
        r0 = rate.iloc[0]
        if r0["r"] < 2 * vac_share:
            return None
        return (f"שיעור הפנייה הגבוה ביותר הוא ב{r0['city']}: {fmt.int_he(r0['vac'])} דירות פנויות "
                f"מתוך {fmt.int_he(r0['stock'])} ({fmt.pct(r0['r'])}), פי {fmt.num_he(r0['r'] / vac_share, 1)} "
                f"מהממוצע הארצי (בין יישובים עם {fmt.int_he(RATE_MIN_STOCK)} דירות לפחות).")
    add("rate", ins_rate())

    def ins_dur():
        if med_months is None or len(m) < 10:
            return None
        t = (f"חציון משך הפנייה הוא {fmt.num_he(med_months, 1)} חודשים, ו-{fmt.int_he((m > LONG_MONTHS).sum())} "
             f"דירות ({fmt.pct(long_share)}) פנויות יותר משנתיים.")
        if very_long:
            t += (f" {fmt.int_he(very_long)} דירות ({fmt.pct(_share(very_long, len(m)))}) "
                  f"פנויות יותר מחמש שנים.")
        return t
    add("duration", ins_dur())

    def ins_floor():
        gap = (hi_v - hi_st) * 100
        if abs(gap) < ROOM_GAP_PTS or v_fl_tot < 20:
            return None
        word = "גבוה" if gap > 0 else "נמוך"
        return (f"דירות בקומה השלישית ומעלה הן {fmt.pct(hi_v)} מהדירות הפנויות, לעומת {fmt.pct(hi_st)} "
                f"מהמלאי כולו: שיעור {word} ב-{fmt.num_he(abs(gap), 1)} נקודות אחוז.")
    add("floor", ins_floor())

    def ins_rooms():
        if vr_tot < 20 or st_rooms_tot == 0:
            return None
        gaps = {k: _share(vac_rooms[k], vr_tot) - _share(st_rooms[k], st_rooms_tot) for k in ROOM_CATS}
        k = max(ROOM_CATS, key=lambda x: (gaps[x], -x))
        if gaps[k] * 100 < ROOM_GAP_PTS:
            return None
        return (f"דירות של {_room_label(k)} בולטות בין הפנויות: {fmt.pct(_share(vac_rooms[k], vr_tot))} "
                f"מהדירות הפנויות לעומת {fmt.pct(_share(st_rooms[k], st_rooms_tot))} מהמלאי.")
    add("rooms", ins_rooms())

    def ins_mismatch():
        bought = set(pc["city"])
        vc = vac_city[[c not in bought for c in vac_city.index]]
        if len(vc) == 0 or not len(pc):
            return None
        share = _share(vc.sum(), n_vac)
        if share < 0.25:
            return None
        names = fmt.join_he([str(x) for x in vc.index[:3]])
        return (f"{fmt.pct(share)} מהדירות הפנויות נמצאות ביישובים שלא נרכשה בהם אף דירה בטבלת הרכש "
                f"(בהם {names}). מספר הרכישות הגבוה ביותר היה ב{ptop.iloc[0]['city']}.")
    add("mismatch", ins_mismatch())

    def ins_purch():
        if len(full_years) < 3:
            return None
        tot = {y: float(py.loc[y, "n3"] + py.loc[y, "n4"]) for y in full_years}
        peak = max(full_years, key=lambda y: (tot[y], -y))
        last = full_years[-1]
        if last == peak:
            return f"{last} הייתה שנת השיא ברכישת דירות למלאי, עם {fmt.int_he(tot[last])} דירות."
        if tot[last] <= 0.5 * tot[peak]:
            t = (f"שנת השיא ברכש הייתה {peak} עם {fmt.int_he(tot[peak])} דירות. ב-{last}, "
                 f"השנה המלאה האחרונה, נרכשו {fmt.int_he(tot[last])} בלבד "
                 f"({fmt.pct(_share(tot[last], tot[peak]))} מהשיא).")
        else:
            t = (f"שנת השיא ברכש הייתה {peak} עם {fmt.int_he(tot[peak])} דירות. ב-{last}, "
                 f"השנה המלאה האחרונה, נרכשו {fmt.int_he(tot[last])} דירות.")
        if partial_year is not None:
            t += f" שנת {partial_year} חלקית ואינה בהשוואה."
        return t
    add("purch", ins_purch())

    def ins_price():
        ys = [y for y in full_years if avg_price(y, 4) is not None]
        if len(ys) < 3:
            return None
        a, b = avg_price(ys[0], 4), avg_price(ys[-1], 4)
        ch = b / a - 1
        if abs(ch) < 0.05:
            return None
        word = "עלה" if ch > 0 else "ירד"
        return (f"המחיר הממוצע של דירות ארבעה חדרים ומעלה שנרכשו למלאי באותה שנה {word} מ-{fmt.num_he(a / 1e6, 2)} "
                f"מיליון ₪ ב-{ys[0]} ל-{fmt.num_he(b / 1e6, 2)} מיליון ₪ ב-{ys[-1]} ({fmt.signed_pct(ch)}). "
                f"הממוצע מושפע גם מתמהיל היישובים שבהם נרכשו הדירות בכל שנה.")
    add("price", ins_price())

    def ins_company():
        if len(comp) < 2:
            return None
        s = _share(comp.iloc[0], n_vac)
        if s < 0.5:
            return None
        return (f"{comp.index[0]} מנהלת {fmt.pct(s)} מהדירות הפנויות ({fmt.int_he(comp.iloc[0])}), "
                f"ב-{fmt.int_he(comp_cities.get(comp.index[0], 0))} יישובים.")
    add("company", ins_company())

    # ---- text ----------------------------------------------------------
    span = f"{years[0]}/{years[-1]}" if years else None
    summary = (f"מלאי הדיור הציבורי: {fmt.int_he(n_stock)} דירות ב-{fmt.int_he(n_stock_cities)} יישובים, "
               f"מהן {fmt.int_he(n_vac)} ראויות למגורים ופנויות יותר משלושה חודשים ({fmt.pct(vac_share)}), "
               f"ו-{fmt.int_he(n_purch)} דירות שנרכשו למלאי.")
    labels["lede"] = (
        f"המאגר של משרד הבינוי והשיכון מתאר את דירות הדיור הציבורי (שיכון ציבורי) בשלוש טבלאות: "
        f"המלאי כולו, {fmt.int_he(n_stock)} דירות לפי יישוב, קומה ומספר חדרים; "
        f"{fmt.int_he(n_vac)} דירות ראויות למגורים שעומדות פנויות יותר משלושה חודשים, נכון ל-{labels['asof']}; "
        f"ורכש דירות חדשות למלאי לפי יישוב ושנה."
    )
    desc = (f"איתור דירות דיור ציבורי פנויות לפי עיר, חדרים וקומה: {fmt.int_he(n_vac)} דירות פנויות "
            f"מתוך {fmt.int_he(n_stock)} במלאי, והרכש למלאי לפי שנה.")

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "rankings",
            **({"temporal_coverage": span} if span else {}),
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "דירות דיור ציבורי פנויות ומלאי הדירות לפי עיר",
                "description": desc,
                "name": "דירות הדיור הציבורי: מלאי, דירות פנויות ורכש",
                "alternate_names": ["דירות הדיור הציבורי", "דירות פנויות בדיור הציבורי",
                                    "מלאי דירות שיכון ציבורי", "דירות עמידר פנויות",
                                    "רכש דירות לדיור הציבורי"],
            },
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "labels": labels,
        "insights": insights,
    }
