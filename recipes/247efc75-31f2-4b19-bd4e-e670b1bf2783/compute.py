"""ממציאים לבקשות פטנטים — inventors named on Israeli patent applications.

One row per (application, inventor). There is no date column, but Israeli
application numbers are assigned sequentially as applications are filed, so
the recipe uses bands of 10,000 application numbers as its time axis (higher
band = later filings). The newest band is partial while it fills up; it is
labelled and excluded from trend rules.

Inventor identity is the English name with case, spaces and punctuation
folded (the English name is filled on 99.6% of rows; the Hebrew one on ~21%),
falling back to the Hebrew name. Two different people sharing a name merge —
the page says the ranking is by name.

Addresses: before a point in the number sequence the register mostly kept an
address only for Israeli inventors; from there on it records nearly every
inventor's country. Country views use only the "address era" — the run of
latest bands where at least ADDR_ERA_MIN of the rows carry an address — and
say so. Personal addresses never reach the page: only the country token.
"""
import pandas as pd

BAND = 10_000
MAX_BANDS = 16          # bands shown individually; earlier ones collapse
PARTIAL_RATIO = 0.5     # last band below this share of the previous = partial
ADDR_ERA_MIN = 0.5
TOP_INVENTORS = 15
TOP_PAIRS = 10
TOP_COUNTRIES = 12
MIX_COUNTRIES = 5       # named series in the country-mix chart
PAIR_MAX_TEAM = 20

COUNTRY_HE = {
    "Israel": "ישראל", "U.S.A.": "ארה״ב", "USA": "ארה״ב", "United States": "ארה״ב",
    "China": "סין", "Germany": "גרמניה", "United Kingdom": "בריטניה",
    "Switzerland": "שווייץ", "Japan": "יפן", "The Netherlands": "הולנד",
    "Netherlands": "הולנד", "Canada": "קנדה", "Italy": "איטליה", "France": "צרפת",
    "Republic of Korea": "דרום קוריאה", "Korea": "דרום קוריאה", "India": "הודו",
    "Denmark": "דנמרק", "Belgium": "בלגיה", "Sweden": "שוודיה",
    "Australia": "אוסטרליה", "Spain": "ספרד", "Russia": "רוסיה",
    "Ireland": "אירלנד", "Poland": "פולין", "Taiwan R.O.C.": "טייוואן",
    "Taiwan": "טייוואן", "Finland": "פינלנד", "Czech Republic": "צ׳כיה",
    "Austria": "אוסטריה", "Singapore": "סינגפור", "Portugal": "פורטוגל",
    "Norway": "נורווגיה", "Brazil": "ברזיל", "Argentina": "ארגנטינה",
    "Turkey": "טורקיה", "New Zealand": "ניו זילנד", "South Africa": "דרום אפריקה",
    "Republic of Slovenia": "סלובניה", "Hungary": "הונגריה",
    "Slovak Republic": "סלובקיה", "Mexico": "מקסיקו", "Greece": "יוון",
    "Ukraine": "אוקראינה", "Croatia": "קרואטיה", "Latvia": "לטביה",
    "Romania": "רומניה", "United Arab Emirates": "איחוד האמירויות",
    "Luxembourg": "לוקסמבורג", "Chile": "צ׳ילה", "Malaysia": "מלזיה",
    "Lithuania": "ליטא", "Cyprus": "קפריסין",
}
ISRAEL = "ישראל"
OTHER_COUNTRY = "מדינות אחרות"

# Invention type from the first word of the Hebrew title.
TYPE_WORDS = [
    ("מערכת", ["מערכת", "מערכות"]),
    ("שיטה ותהליך", ["שיטה", "שיטות", "שיטת", "תהליך", "תהליכים", "תהליכי", "זיהוי",
                     "גילוי", "ייצור", "עיבוד", "ניהול", "בקרת", "קביעת", "יצירת", "הערכת",
                     "הפחתת", "הכנת", "מיפוי", "ניתוח", "שיפור", "שליטה", "הרכבת"]),
    ("מכשיר, התקן ורכיב", ["מכשיר", "מכשירים", "התקן", "התקנים", "התקני", "מתקן", "מתקנים",
                          "כלי", "מכלול", "מנגנון", "צנתר", "יחידת", "מבנה", "מבנים", "אביזר",
                          "מיכל", "שסתום", "שתל", "מחבר", "חיישן", "רכיב", "מערך", "מודול",
                          "משאבת", "מחסנית", "מנוע", "צינור", "אלמנט", "מוצר", "גלאי", "רכב",
                          "ממשק", "מתאם", "מכונה", "מכונת", "לוח", "ראש", "מעגל", "מנעול",
                          "מגן", "מזרק", "משאף", "ציוד", "אמצעים", "אמצעי", "כיסוי", "סידור"]),
    ("תכשיר, הרכב ותערובת", ["תכשיר", "תכשירים", "תכשירי", "הרכב", "הרכבים", "הרכבי",
                            "פורמולציה", "פורמולציות", "חומר", "חומרים", "חומרי", "תערובת",
                            "תערובות", "ציפוי", "קומפוזיציות", "שילוב", "שילובים"]),
    ("תרכובת כימית", ["תרכובת", "תרכובות", "נגזרות", "נגזרת", "תולדות", "מולקולות",
                      "מעכבי", "מעכב", "מעכבים", "צורות", "מלחים", "מלח", "אנלוגים",
                      "חומצות", "אנטגוניסטים", "מודולטורים", "תצמידים"]),
    ("נוגדנים, חלבונים ותאים", ["נוגדן", "נוגדנים", "נוגדני", "פפטיד", "פפטידים",
                                         "פוליפפטידים", "חלבון", "חלבונים", "חלבוני", "תא",
                                         "תאי", "תאים", "חיסון", "חיסונים", "וקטורי", "סמנים",
                                         "קולטני", "וריאנטים"]),
    ("שימוש וטיפול", ["שימוש", "טיפול", "טיפולים", "מתן"]),
]
TYPE_OF = {w: t for t, ws in TYPE_WORDS for w in ws}
TYPE_ORDER = [t for t, _ in TYPE_WORDS] + ["אחר"]

TEAM_BUCKETS = [(1, 1, "1"), (2, 2, "2"), (3, 3, "3"), (4, 4, "4"), (5, 5, "5"),
                (6, 6, "6"), (7, 10, "7–10"), (11, 20, "11–20"), (21, 10**9, "21 ומעלה")]
PROLIFIC_BUCKETS = [(1, 1, "בקשה אחת"), (2, 2, "2"), (3, 5, "3–5"), (6, 10, "6–10"),
                    (11, 20, "11–20"), (21, 50, "21–50"), (51, 10**9, "51 ומעלה")]


def _int(n):
    return f"{int(n):,}"


def _pct(x, d=1):
    return f"{x * 100:.{d}f}%"


def _prepare(raw):
    df = raw.apply(lambda c: c.str.strip())
    n_raw = len(df)
    df = df.drop_duplicates()
    dups = n_raw - len(df)
    df = df.assign(app=pd.to_numeric(df["מספר בקשה"].str.replace(",", "", regex=False),
                                      errors="coerce"))
    df = df[df["app"].notna()].copy()
    df["app"] = df["app"].astype(int)
    en = df["שם ממציא באנגלית"]
    he = df["שם ממציא בעברית"].str.replace("~", "״", regex=False)
    en_key = en.str.upper().str.replace(r"[^A-Z]", "", regex=True)
    he_key = he.str.replace(r"[^א-ת]", "", regex=True)
    df["key"] = en_key.where(en_key != "", "H:" + he_key)
    df.loc[(en_key == "") & (he_key == ""), "key"] = ""
    df["en"] = en
    df["he"] = he
    addr = df["כתובת ממציא באנגלית"]
    tok = addr.str.split(",").str[-1].str.strip()
    df["has_addr"] = addr != ""
    df["country"] = tok.map(COUNTRY_HE).where(tok != "", "")
    df.loc[(tok != "") & df["country"].isna(), "country"] = OTHER_COUNTRY
    df["country"] = df["country"].fillna("")
    df["band"] = df["app"] // BAND
    return df, dups


def _display_names(people):
    """key -> display name: a consistent Hebrew name when the register has one
    (≥2 rows and ≥60% of the key's Hebrew rows, spelling variants folded),
    else the most common English spelling."""
    def top_variant(frame, col):
        c = frame.groupby(["key", col]).size().rename("n").reset_index()
        c = c.sort_values(["key", "n", col], ascending=[True, False, True], kind="stable")
        return c.drop_duplicates("key").set_index("key")
    en = top_variant(people[people["en"] != ""], "en")["en"]
    hr = people[people["he"] != ""].assign(hf=lambda d: d["he"].str.replace(r"[^א-ת ]", "", regex=True))
    hf = top_variant(hr, "hf")
    tot = hr.groupby("key").size()
    win = hr[hr["hf"] == hr["key"].map(hf["hf"])]
    he_disp = top_variant(win, "he")["he"]
    out = {}
    for k in people["key"].unique():
        name = en.get(k, "")
        if k in hf.index:
            c = int(hf.at[k, "n"])
            if (c >= 2 and c / int(tot[k]) >= 0.6) or not name:
                name = he_disp[k]
        out[k] = name
    return out


def _band_label(b):
    return f"{b * BAND // 1000} אלף"


def _band_range(b):
    return f"{_int(b * BAND)}–{_int(b * BAND + BAND - 1)}"


def compute(frames):
    df, dups = _prepare(frames["inventors"])
    n_rows = len(df)
    people = df[df["key"] != ""].drop_duplicates(["app", "key"])
    apps = df.drop_duplicates("app")[["app", "band", "שם האמצאה בעברית"]].sort_values("app")
    n_apps = len(apps)
    team = people.groupby("app").size().reindex(apps["app"], fill_value=0)
    apps = apps.assign(team=team.values)
    n_inventors = int(people["key"].nunique())

    # ---------------- bands (time proxy) ----------------
    all_bands = sorted(apps["band"].unique().tolist())
    shown = all_bands[-MAX_BANDS:]
    first_shown = shown[0]
    early = [b for b in all_bands if b < first_shown]
    app_band = apps["band"].where(apps["band"] >= first_shown, first_shown - 1)
    people_band = people["band"].where(people["band"] >= first_shown, first_shown - 1)
    band_keys = ([first_shown - 1] if early else []) + shown
    labels = [f"עד {first_shown * BAND // 1000} אלף" if b == first_shown - 1 else _band_label(b)
              for b in band_keys]
    ranges = [f"עד {_int(first_shown * BAND - 1)}" if b == first_shown - 1 else _band_range(b)
              for b in band_keys]
    apps_per = apps.groupby(app_band).size()
    band_apps = [int(apps_per.get(b, 0)) for b in band_keys]
    last = shown[-1]
    partial = len(shown) >= 2 and band_apps[-1] < PARTIAL_RATIO * band_apps[-2]
    if partial:
        labels[-1] += " (חלקי)"
    full_keys = band_keys[:-1] if partial else band_keys
    full_shown = [b for b in full_keys if b >= first_shown]

    # mean team & solo share per band
    team_mean = apps.groupby(app_band)["team"].mean()
    solo = apps.assign(s=apps["team"] == 1).groupby(app_band)["s"].mean()
    team_trend = {
        "x": labels,
        "mean": [round(float(team_mean.get(b, 0)), 2) for b in band_keys],
        "solo": [round(float(solo.get(b, 0)) * 100, 1) for b in band_keys],
    }
    bands_chart = {"x": labels, "y": band_apps, "partial": bool(partial)}
    bands_rows = [{"range": r, "apps": _int(a), "mean": f"{m:.2f}", "solo": f"{s:.1f}"}
                  for r, a, m, s in zip(ranges, band_apps, team_trend["mean"], team_trend["solo"])]

    # ---------------- team size distribution ----------------
    t_counts = [int(((apps["team"] >= lo) & (apps["team"] <= hi)).sum()) for lo, hi, _ in TEAM_BUCKETS]
    team_dist = {"names": [b[2] for b in TEAM_BUCKETS], "values": t_counts}
    team_rows = [{"name": b[2], "n": _int(v), "share": f"{v / n_apps * 100:.1f}"}
                 for b, v in zip(TEAM_BUCKETS, t_counts)]
    team_median = float(apps["team"][apps["team"] > 0].median())
    team_max = int(apps["team"].max())

    # ---------------- inventors ----------------
    names = _display_names(people)
    per_inv = people.groupby("key")["app"].nunique()
    per_inv = per_inv.sort_index().sort_values(ascending=False, kind="stable")
    top = per_inv.head(TOP_INVENTORS)
    ic = (people[people["country"] != ""].groupby(["key", "country"]).size()
          .rename("n").reset_index()
          .sort_values(["key", "n", "country"], ascending=[True, False, True], kind="stable"))
    inv_country = ic.drop_duplicates("key").set_index("key")["country"]
    top_inv = {"names": [names[k] for k in top.index], "values": [int(v) for v in top]}
    top_rows = [{"name": names[k], "n": _int(v), "country": inv_country.get(k, "—")}
                for k, v in top.items()]
    p_counts = [int(((per_inv >= lo) & (per_inv <= hi)).sum()) for lo, hi, _ in PROLIFIC_BUCKETS]
    prolific = {"names": [b[2] for b in PROLIFIC_BUCKETS], "values": p_counts}
    prolific_rows = [{"name": b[2], "n": _int(v), "share": f"{v / max(n_inventors, 1) * 100:.1f}"}
                     for b, v in zip(PROLIFIC_BUCKETS, p_counts)]

    # ---------------- co-inventor pairs ----------------
    small = people[people["app"].map(people.groupby("app").size()) <= PAIR_MAX_TEAM][["app", "key"]]
    pm = small.merge(small, on="app")
    pm = pm[pm["key_x"] < pm["key_y"]]
    pc = pm.groupby(["key_x", "key_y"]).size().rename("n").reset_index()
    pc = pc.sort_values(["n", "key_x", "key_y"], ascending=[False, True, True], kind="stable")
    top_pairs = pc.head(TOP_PAIRS)
    pairs = {"names": [f"{names[a]} ו{names[b]}" if names[b][:1].isalpha() and not names[b][:1].isascii()
                       else f"{names[a]} ו-{names[b]}"
                       for a, b in zip(top_pairs["key_x"], top_pairs["key_y"])],
             "values": [int(v) for v in top_pairs["n"]]}
    pair_rows = [{"a": names[a], "b": names[b], "n": _int(n)}
                 for a, b, n in zip(top_pairs["key_x"], top_pairs["key_y"], top_pairs["n"])]
    n_pair_apps = int(small["app"].nunique())
    n_big_apps = int((apps["team"] > PAIR_MAX_TEAM).sum())

    # ---------------- address era & countries ----------------
    addr_share = people.groupby("band")["has_addr"].mean()
    era_bands = []
    for b in sorted(addr_share.index, reverse=True):
        if addr_share[b] >= ADDR_ERA_MIN:
            era_bands.append(b)
        else:
            break
    era_bands = sorted(era_bands)
    has_era = len(era_bands) >= 1 and era_bands[0] > all_bands[0]
    countries = mix = comp = None
    country_rows = mix_rows = comp_rows = []
    era = people[people["band"].isin(era_bands)] if has_era else people.iloc[0:0]
    era_known = era[era["country"] != ""]
    pre = people[~people["band"].isin(era_bands)]
    pre_addr = float(pre["has_addr"].mean()) if len(pre) else None
    era_addr = float(era["has_addr"].mean()) if len(era) else None
    era_start = era_bands[0] * BAND if has_era else None
    era_labels = [labels[band_keys.index(b)] if b in band_keys else _band_label(b) for b in era_bands]
    era_partial = has_era and partial and era_bands[-1] == last
    era_full = [b for b in era_bands if not (era_partial and b == last)]
    if has_era and len(era_known) >= 200:
        cc = era_known["country"].value_counts()
        cc = cc.sort_index().sort_values(ascending=False, kind="stable")
        named = cc.drop(OTHER_COUNTRY, errors="ignore")
        topc = named.head(TOP_COUNTRIES)
        rest = int(cc.sum() - topc.sum())
        c_names = list(topc.index) + ([OTHER_COUNTRY] if rest else [])
        c_vals = [int(v) for v in topc] + ([rest] if rest else [])
        countries = {"names": c_names, "values": c_vals}
        country_rows = [{"name": n, "n": _int(v), "share": f"{v / cc.sum() * 100:.1f}"}
                        for n, v in zip(c_names, c_vals)]
        # mix by band
        mix_named = list(named.head(MIX_COUNTRIES).index)
        series = []
        shares = {}
        for c in mix_named + ["אחר"]:
            data = []
            for b in era_bands:
                sub = era_known[era_known["band"] == b]
                if c == "אחר":
                    v = (~sub["country"].isin(mix_named)).mean() if len(sub) else 0
                else:
                    v = (sub["country"] == c).mean() if len(sub) else 0
                data.append(round(float(v) * 100, 1))
            shares[c] = data
            series.append({"name": "מדינות אחרות" if c == "אחר" else c, "data": data})
        mix = {"x": era_labels, "series": series}
        mix_rows = [{"band": lbl, "vals": [f"{shares[c][j]:.1f}" for c in mix_named + ["אחר"]]}
                    for j, lbl in enumerate(era_labels)]
        mix_heads = [s["name"] for s in series]
        # team composition, apps whose inventors all have a known country
        g = (era.assign(k=era["country"] != "", i=era["country"] == ISRAEL)
             .groupby("app").agg(n=("key", "size"), known=("k", "sum"), il=("i", "sum")))
        g = g[(g["known"] == g["n"]) & (g["n"] > 0)]
        g["kind"] = "mixed"
        g.loc[g["il"] == g["n"], "kind"] = "il"
        g.loc[g["il"] == 0, "kind"] = "foreign"
        band_of = era.drop_duplicates("app").set_index("app")["band"]
        g["band"] = band_of.reindex(g.index).values
        kinds = [("il", "ממציאים מישראל בלבד"), ("mixed", "צוות משותף: ישראל וחו״ל"),
                 ("foreign", "ממציאים מחו״ל בלבד")]
        comp = {"x": era_labels, "series": []}
        for k, lbl in kinds:
            data = []
            for b in era_bands:
                sub = g[g["band"] == b]
                data.append(round(float((sub["kind"] == k).mean()) * 100, 1) if len(sub) else 0)
            comp["series"].append({"name": lbl, "data": data})
        comp_tot = {k: int((g["kind"] == k).sum()) for k, _ in kinds}
        comp_n = int(len(g))
        comp_band_rows = [{"band": lbl, "vals": [f"{sr['data'][j]:.1f}" for sr in comp["series"]]}
                          for j, lbl in enumerate(era_labels)]
        comp_rows = [{"name": lbl, "n": _int(comp_tot[k]),
                      "share": f"{comp_tot[k] / max(comp_n, 1) * 100:.1f}"} for k, lbl in kinds]
    else:
        mix_heads = []
        comp_tot, comp_n = {}, 0
        comp_band_rows = []

    # ---------------- invention type ----------------
    fw = apps["שם האמצאה בעברית"].str.split().str[0].fillna("").str.strip("\"'״׳()-.,")
    apps = apps.assign(kind=fw.map(TYPE_OF).fillna("אחר"))
    tc = apps["kind"].value_counts()
    types = {"names": [t for t in TYPE_ORDER if tc.get(t, 0)],
             "values": [int(tc[t]) for t in TYPE_ORDER if tc.get(t, 0)]}
    type_rows = [{"name": n, "n": _int(v), "share": f"{v / n_apps * 100:.1f}"}
                 for n, v in zip(types["names"], types["values"])]
    named_types = [t for t in types["names"] if t != "אחר"]
    cells = []
    for yi, t in enumerate(named_types):
        for xi, b in enumerate(band_keys):
            sub = apps[app_band == b]
            v = round(float((sub["kind"] == t).mean()) * 100, 1) if len(sub) else 0
            cells.append([xi, yi, v])
    type_mix = {"x": labels, "types": named_types, "cells": cells,
                "max": max((c[2] for c in cells), default=1)}
    team_by_type = apps[apps["team"] > 0].groupby("kind")["team"].mean()

    # ---------------- insights ----------------
    def idx(b):
        return band_keys.index(b)

    def ins_team():
        if len(full_shown) < 4:
            return None
        a, z = full_shown[0], full_shown[-1]
        m0, m1 = team_trend["mean"][idx(a)], team_trend["mean"][idx(z)]
        if not m0:
            return None
        ch = (m1 - m0) / m0
        if abs(ch) < 0.1:
            return (f"גודל צוות הממציאים יציב: בממוצע {m1:.1f} ממציאים לבקשה בטווח "
                    f"{_band_range(z)}, לעומת {m0:.1f} בטווח {_band_range(a)}.")
        word = "גדל" if ch > 0 else "קטן"
        return (f"צוות הממציאים {word} לאורך הזמן: מ-{m0:.1f} ממציאים בממוצע לבקשה בטווח "
                f"{_band_range(a)} ל-{m1:.1f} בטווח {_band_range(z)} — טווח מאוחר יותר משמעו בקשות חדשות יותר.")

    def ins_solo():
        if len(full_shown) < 4:
            return None
        a, z = full_shown[0], full_shown[-1]
        s0, s1 = team_trend["solo"][idx(a)], team_trend["solo"][idx(z)]
        if abs(s1 - s0) < 3:
            return None
        word = "ירד" if s1 < s0 else "עלה"
        return (f"שיעור הבקשות בעלות ממציא יחיד {word} מ-{s0:.1f}% בטווח {_band_range(a)} "
                f"ל-{s1:.1f}% בטווח {_band_range(z)}.")

    def ins_leader():
        if len(per_inv) < 2 or per_inv.iloc[0] < 20:
            return None
        k0, v0 = per_inv.index[0], int(per_inv.iloc[0])
        k1, v1 = per_inv.index[1], int(per_inv.iloc[1])
        if v0 == v1:
            return None
        gap = f" — פי {v0 / v1:.1f} מהבא אחריו, {names[k1]} ({_int(v1)})" if v0 >= 1.5 * v1 \
            else f"; אחריו {names[k1]} ({_int(v1)})"
        return f"הממציא הפורה ביותר במאגר הוא {names[k0]}, החתום על {_int(v0)} בקשות{gap}."

    def ins_pair():
        if top_pairs.empty or int(top_pairs["n"].iloc[0]) < 10:
            return None
        a, b, n = top_pairs.iloc[0]["key_x"], top_pairs.iloc[0]["key_y"], int(top_pairs.iloc[0]["n"])
        return (f"שיתוף הפעולה הקבוע ביותר: {names[a]} ו{names[b]} " if not names[b][:1].isascii()
                else f"שיתוף הפעולה הקבוע ביותר: {names[a]} ו-{names[b]} ") + \
            f"חתומים יחד על {_int(n)} בקשות."

    def ins_prolific():
        if n_inventors < 100:
            return None
        once = p_counts[0] / n_inventors
        many = int((per_inv >= 21).sum())
        rows_many = int(people[people["key"].isin(per_inv[per_inv >= 21].index)]["app"].nunique())
        return (f"{_pct(once, 0)} מ-{_int(n_inventors)} הממציאים מופיעים בבקשה אחת בלבד; "
                f"{_int(many)} ממציאים חתומים על יותר מעשרים בקשות כל אחד, ומופיעים יחד "
                f"ב-{_pct(rows_many / n_apps, 0)} מהבקשות.")

    def ins_countries():
        if not countries:
            return None
        tot = sum(countries["values"])
        il = dict(zip(countries["names"], countries["values"])).get(ISRAEL, 0)
        lead = next((n for n in countries["names"] if n not in (ISRAEL, OTHER_COUNTRY)), None)
        if not lead:
            return None
        lv = dict(zip(countries["names"], countries["values"]))[lead]
        head = (f"בבקשות שמספרן {_int(era_start)} ומעלה, {_pct(il / tot, 0)} מהממציאים רשומים "
                f"בישראל")
        if lv > il:
            return head + f" — פחות מ{lead}, שממנה {_pct(lv / tot, 0)} מהממציאים."
        return head + f"; {lead} מובילה מבין מדינות חו״ל עם {_pct(lv / tot, 0)}."

    def ins_rising():
        if not mix or len(era_full) < 2:
            return None
        i0, i1 = era_bands.index(era_full[0]), era_bands.index(era_full[-1])
        best = None
        for c in mix_named:
            if c == ISRAEL:
                continue
            d = shares[c][i1] - shares[c][i0]
            if best is None or d > best[1]:
                best = (c, d)
        if not best or best[1] < 2:
            return None
        c = best[0]
        return (f"חלקה של {c} בקרב הממציאים עלה מ-{shares[c][i0]:.1f}% בטווח "
                f"{_band_range(era_full[0])} ל-{shares[c][i1]:.1f}% בטווח {_band_range(era_full[-1])}.")

    def ins_comp():
        if comp_n < 200:
            return None
        mixed = comp_tot["mixed"] / comp_n
        return (f"צוותים משותפים לישראלים ולממציאים מחו״ל נדירים: {_pct(mixed, 1)} בלבד מתוך "
                f"{_int(comp_n)} בקשות שכל ממציאיהן רשומים עם מדינה; "
                f"{_pct(comp_tot['il'] / comp_n, 0)} ישראליות לגמרי.")

    def ins_type():
        named_types = [(n, v) for n, v in zip(types["names"], types["values"]) if n != "אחר"]
        if not named_types:
            return None
        n, v = max(named_types, key=lambda t: (t[1], t[0]))
        if v / n_apps < 0.1:
            return None
        bio = [t for t in team_by_type.index if t != "אחר"]
        if not bio:
            return None
        hi = max(bio, key=lambda t: (team_by_type[t], t))
        lo = min(bio, key=lambda t: (team_by_type[t], t))
        other = dict(zip(types["names"], types["values"])).get("אחר", 0)
        return (f"לפי המילה הפותחת את שם האמצאה, הסוג הנפוץ הוא {n} ({_pct(v / n_apps, 0)} מהבקשות; "
                f"{_pct(other / n_apps, 0)} לא סווגו). "
                f"הצוותים הגדולים ביותר בקטגוריה {hi} ({team_by_type[hi]:.1f} ממציאים בממוצע), "
                f"והקטנים ביותר בקטגוריה {lo} ({team_by_type[lo]:.1f}).")

    def ins_addr():
        if not has_era or pre_addr is None or pre_addr > 0.35 or era_addr is None:
            return None
        pk = pre[pre["country"] != ""]
        il_pre = float((pk["country"] == ISRAEL).mean()) if len(pk) else 0
        who = f", {_pct(il_pre, 0)} מהן בישראל" if il_pre >= 0.6 else ""
        return (f"רישום הכתובות השתנה: לפני בקשה {_int(era_start)} רק {_pct(pre_addr, 0)} מרשומות "
                f"הממציאים כוללות כתובת{who}; מאז — {_pct(era_addr, 0)}. "
                "לכן פילוח המדינות מבוסס רק על הבקשות החדשות.")

    rules = [("team", ins_team()), ("solo", ins_solo()), ("leader", ins_leader()),
             ("pair", ins_pair()), ("prolific", ins_prolific()), ("countries", ins_countries()),
             ("rising", ins_rising()), ("comp", ins_comp()), ("type", ins_type()),
             ("addr", ins_addr())]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    # ---------------- KPIs ----------------
    last_full_key = full_shown[-1] if full_shown else band_keys[-1]
    first_full_key = full_shown[0] if full_shown else band_keys[0]
    m_last = team_trend["mean"][idx(last_full_key)]
    m_first = team_trend["mean"][idx(first_full_key)]
    # Larger teams vs the earliest band read as notable context (info), not good/bad.
    team_tone = "info" if m_first and abs(m_last - m_first) / m_first >= 0.1 else "brand"
    il_share = None
    if countries:
        il_share = dict(zip(countries["names"], countries["values"])).get(ISRAEL, 0) / sum(countries["values"])
    kpis = {
        "apps": {"value": n_apps, "display": _int(n_apps), "tone": "brand"},
        "inventors": {"value": n_inventors, "display": _int(n_inventors), "tone": "brand"},
        "team_last": {"value": m_last, "display": f"{m_last:.1f}", "tone": team_tone},
        "il_share": {"value": il_share,
                     "display": "—" if il_share is None else _pct(il_share, 0),
                     "tone": "brand"},
    }

    lo_app, hi_app = int(apps["app"].min()), int(apps["app"].max())
    lede = (f"{_int(n_rows)} רשומות ממציאים על {_int(n_apps)} בקשות פטנט ישראליות "
            f"(מספרי בקשה {_int(lo_app)}–{_int(hi_app)}), עם {_int(n_inventors)} שמות ממציאים שונים. "
            f"למאגר אין עמודת תאריך; מספרי הבקשה מוקצים ברצף לפי סדר ההגשה, ולכן הדף מציג "
            f"שינויים לאורך זמן לפי טווחים של {_int(BAND)} מספרי בקשה.")
    if dups:
        lede += f" {_int(dups)} שורות כפולות זהות הוסרו."
    summary = (f"{_int(n_apps)} בקשות פטנט ישראליות ו-{_int(n_inventors)} ממציאים: גודל הצוותים, "
               f"הממציאים הפוריים, שיתופי הפעולה והמדינות שמהן מגיעים הממציאים. "
               f"בבקשות האחרונות {m_last:.1f} ממציאים בממוצע לבקשה.")

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "rankings",
            "suggested_tags": ["פטנטים", "ממציאים", "קניין רוחני", "חדשנות", "רשות הפטנטים"],
            "related_ids": ["029b6747-551b-47ad-9a05-ef7f7868fcd0",
                            "6e207fff-abef-4f4d-aac7-61e669ba9ad5",
                            "8687fefe-51af-4e0b-af54-701929c40102",
                            "1806c96c-9cc4-47bf-98b3-80a18f061f98"],
        },
        "kpis": kpis,
        "charts": {"bands": bands_chart, "team_dist": team_dist, "team_trend": team_trend,
                   "top": top_inv, "prolific": prolific, "pairs": pairs,
                   "countries": countries, "mix": mix, "comp": comp,
                   "types": types, "type_mix": type_mix},
        "tables": {"bands": bands_rows, "team": team_rows, "top": top_rows,
                   "prolific": prolific_rows, "pairs": pair_rows, "countries": country_rows,
                   "mix": mix_rows, "mix_heads": mix_heads, "comp": comp_rows,
                   "comp_bands": comp_band_rows, "types": type_rows},
        "flags": {"countries": bool(countries), "partial": bool(partial)},
        "insights": insights,
        "labels": {
            "lede": lede,
            "team_last_kpi": f"ממציאים בממוצע לבקשה (טווח {_band_range(last_full_key)})",
            "il_share_kpi": (f"מהממציאים רשומים בישראל (בקשות {_int(era_start)} ומעלה)"
                             if has_era else "מהממציאים רשומים בישראל"),
            "bands_note": ("מספר הבקשות במאגר בכל טווח של מספרי בקשה; טווח מאוחר יותר = בקשות "
                           "שהוגשו מאוחר יותר." + (f" הטווח האחרון ({_band_range(last)}) עדיין מתמלא."
                                                    if partial else "")
                           + (f" הטווחים שלפני {_int(first_shown * BAND)} אוחדו." if early else "")),
            "team_note": (f"מספר הממציאים בכל בקשה. החציון {team_median:.0f} ממציאים; "
                          f"בבקשה הגדולה ביותר {_int(team_max)} ממציאים."),
            "trend_note": "ממוצע הממציאים לבקשה ושיעור הבקשות בעלות ממציא יחיד, לפי טווח מספרי בקשה.",
            "top_note": (f"{TOP_INVENTORS} הממציאים החתומים על מספר הבקשות הגדול ביותר. זיהוי לפי "
                         "שם (באיחוד כתיב אותיות גדולות וקטנות), כך ששני אנשים בעלי שם זהה נספרים יחד."),
            "prolific_note": f"{_int(n_inventors)} הממציאים לפי מספר הבקשות שכל אחד מהם חתום עליהן.",
            "pairs_note": (f"צמדי הממציאים שחתומים יחד על מספר הבקשות הגדול ביותר. נספרו "
                           f"{_int(n_pair_apps)} בקשות עם עד {PAIR_MAX_TEAM} ממציאים"
                           + (f"; {_int(n_big_apps)} בקשות עם צוות גדול יותר לא נכללו." if n_big_apps else ".")),
            "countries_note": (f"רשומות ממציאים בבקשות שמספרן {_int(era_start)} ומעלה, לפי המדינה "
                               f"שבכתובת. {_int(len(era) - len(era_known))} רשומות ללא כתובת לא נכללו."
                               if has_era else ""),
            "mix_note": ("שיעור כל מדינה מבין הממציאים בכל טווח, מאז שהכתובות נרשמות באופן שיטתי."
                         + (" הטווח האחרון חלקי." if era_partial else "")),
            "comp_note": (f"{_int(comp_n)} בקשות שכל ממציאיהן רשומים עם מדינה, לפי הרכב הצוות."
                          if comp_n else ""),
            "types_note": ("סוג האמצאה לפי המילה הפותחת את שמה בעברית (מערכת, שיטה, מכשיר, תכשיר…). "
                           "שמות שאינם נפתחים במילה מוכרת נספרים כ״אחר״."),
            "type_mix_note": "שיעור כל סוג אמצאה מבין הבקשות בכל טווח של מספרי בקשה (ללא ״אחר״). גוון כהה יותר = שיעור גבוה יותר.",
            "bands_aria": f"עמודות: {_int(n_apps)} בקשות לפי טווח מספרי בקשה.",
            "team_aria": f"עמודות: בקשות לפי מספר הממציאים בבקשה; החציון {team_median:.0f}.",
            "trend_aria": (f"קווים: ממוצע הממציאים לבקשה ושיעור בקשות הממציא היחיד לפי טווח; "
                           f"בטווח האחרון המלא {m_last:.1f} ממציאים בממוצע."),
            "top_aria": f"עמודות אופקיות: {TOP_INVENTORS} הממציאים עם מספר הבקשות הגבוה ביותר.",
            "prolific_aria": "עמודות: ממציאים לפי מספר הבקשות שהם חתומים עליהן.",
            "pairs_aria": f"עמודות אופקיות: {TOP_PAIRS} צמדי הממציאים הקבועים ביותר.",
            "countries_aria": "עמודות אופקיות: רשומות ממציאים לפי מדינה.",
            "mix_aria": "עמודות מוערמות באחוזים: מדינות הממציאים לפי טווח מספרי בקשה.",
            "comp_aria": "עמודות מוערמות באחוזים: הרכב צוות הממציאים (ישראל, חו״ל, משותף) לפי טווח.",
            "types_aria": f"עמודות אופקיות: {_int(n_apps)} בקשות לפי סוג האמצאה.",
            "type_mix_aria": "מפת חום: שיעור כל סוג אמצאה לפי טווח מספרי בקשה.",
        },
    }
