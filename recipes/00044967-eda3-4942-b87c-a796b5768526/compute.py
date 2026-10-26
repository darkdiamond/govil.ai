"""תקנות הירושה — בתי הדין השרעיים (inheritance-order notices, Arabic).

One table, one row per published notice of a request for an inheritance
order (حصر إرث) at a Sharia court: court, file number, applicant, deceased
(name, ID, address = settlement, date of death) and publication date. Notices
go out in weekly batches, mostly on Thursdays.

Personal-status data, aggregate only: NOTHING about any person is shown — no
names, no ID numbers, no file numbers (those columns are not even read). A
file can carry several deceased (spouses, parent and child), so the unit
throughout is the notice (one deceased), not the file.

The source is Arabic and the page Hebrew: courts and settlements go through
the lookup tables below after spelling normalisation; unknown values fall
into an "other" bucket and are counted, never printed in Arabic.

Structure follows the Druze-courts sibling (da374239) so the two pages read
alike: monthly by court, yearly by court, weekday, settlement map, top
settlements, death→notice lag, year and month of death.

"Now" is the latest publication date in the data, never the wall clock.
A publication date far past the weekly cadence (a future-year typo) is
excluded and disclosed.
"""
import math

import pandas as pd

LRI, PDI = "⁦", "⁩"
MINUS = "−"
MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]
MONTHS_SHORT = ["ינו׳", "פבר׳", "מרץ", "אפר׳", "מאי", "יוני", "יולי",
                "אוג׳", "ספט׳", "אוק׳", "נוב׳", "דצמ׳"]
WEEKDAYS_HE = ["שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון"]  # pandas 0=Mon
WEEK_ORDER = [6, 0, 1, 2, 3, 4, 5]   # Sunday → Saturday

MAX_GAP_DAYS = 31        # a publication date this far past the previous one is a typo
MONTHLY_MAX = 60         # months on the monthly chart before switching to quarters
STACK_COURTS = 6         # courts shown separately on the monthly chart
TOP_PLACES = 15
TREE_PLACES = 6          # settlements per court in the treemap
MIN_LAG_COURT = 40       # notices with a valid death date for a court to enter the lag chart
MIN_LAG_N = 100
DEATH_YEARS = 15         # yearly bars for death year; earlier years pooled
SEASON_MIN_N = 300

LAG_BUCKETS = [  # (upper bound in days, inclusive, label) — as the Druze sibling, + 20y split
    (30, "עד חודש"),
    (91, "חודש עד שלושה"),
    (182, "שלושה עד שישה חודשים"),
    (365, "חצי שנה עד שנה"),
    (730, "שנה עד שנתיים"),
    (1826, "שנתיים עד חמש שנים"),
    (3652, "חמש עד עשר שנים"),
    (7305, "עשר עד עשרים שנה"),
    (None, "יותר מעשרים שנה"),
]
LAG_GROUPS = [(365, "עד שנה"), (1826, "שנה עד חמש שנים"), (3652, "חמש עד עשר שנים"),
              (None, "יותר מעשר שנים")]

OTHER_COURT = "בית דין אחר"
NO_COURT = "לא צוין"
OTHER_PLACE = "יישוב אחר"
OTHER_REGION = "לא זוהה"
ABROAD = "חו״ל"
NO_PLACE = "לא צוין"
OTHER_TRIBE = "שבט אחר"

# normalised Arabic court name → Hebrew
COURTS = {
    "القدس": "ירושלים", "عكا": "עכו", "الطيبه": "טייבה", "بئرالسبع": "באר שבע",
    "باقه": "באקה אל-גרבייה", "باقهالغربيه": "באקה אל-גרבייה", "سخنين": "סח׳נין",
    "الناصره": "נצרת", "يافا": "יפו", "حيفا": "חיפה", "الاستئناف": "ערעורים",
    "استئناف": "ערעורים", "محكمهالاستئناف": "ערעורים",
}

JLM, TRI, GAL, NEG, MIX = "ירושלים", "המשולש ואדי עארה", "הגליל והעמקים", "הנגב", "ערים מעורבות"
REGION_ORDER = [JLM, GAL, TRI, NEG, MIX, ABROAD, OTHER_REGION]

# normalised Arabic settlement → (Hebrew name, region, lat, lng)
SETTLEMENTS = {
    "القدس": ("ירושלים", JLM, 31.785, 35.235),
    "ابوغوش": ("אבו גוש", JLM, 31.806, 35.109),
    "عيننقوبا": ("עין נקובא", JLM, 31.795, 35.120),
    "الطيبه": ("טייבה", TRI, 32.266, 35.009),
    "الطيره": ("טירה", TRI, 32.234, 34.950),
    "باقهالغربيه": ("באקה אל-גרבייה", TRI, 32.418, 35.042),
    "امالفحم": ("אום אל-פחם", TRI, 32.519, 35.153),
    "كفرقاسم": ("כפר קאסם", TRI, 32.114, 34.976),
    "قلنسوه": ("קלנסווה", TRI, 32.285, 34.981),
    "كفرقرع": ("כפר קרע", TRI, 32.505, 35.054),
    "زيمر": ("זמר", TRI, 32.369, 35.035),
    "جتالمثلث": ("ג׳ת", TRI, 32.402, 35.043),
    "عرعره": ("ערערה", TRI, 32.496, 35.100),
    "عاره": ("ערה", TRI, 32.497, 35.085),
    "جلجوليه": ("ג׳לג׳וליה", TRI, 32.153, 34.954),
    "جسرالزرقاء": ("ג׳סר א-זרקא", TRI, 32.538, 34.912),
    "برطعه": ("ברטעה", TRI, 32.476, 35.075),
    "كفربرا": ("כפר ברא", TRI, 32.131, 34.972),
    "مصمص": ("מוסמוס", TRI, 32.540, 35.150),
    "زلفه": ("זלפה", TRI, 32.462, 35.115),
    "الفريديس": ("פוריידיס", TRI, 32.597, 34.951),
    "ميسر": ("מייסר", TRI, 32.445, 35.045),
    "معاويه": ("מועאוויה", TRI, 32.540, 35.105),
    "عينالسهله": ("עין א-סהלה", TRI, 32.474, 35.090),
    "سالم": ("סאלם", TRI, 32.555, 35.205),
    "مشيرفه": ("משירפה", TRI, 32.528, 35.124),
    "رهط": ("רהט", NEG, 31.393, 34.754),
    "كسيفه": ("כסייפה", NEG, 31.244, 35.090),
    "تلالسبع": ("תל שבע", NEG, 31.247, 34.861),
    "حوره": ("חורה", NEG, 31.300, 34.937),
    "اللقيه": ("לקיה", NEG, 31.327, 34.861),
    "عرعرهالنقب": ("ערערה-בנגב", NEG, 31.155, 35.016),
    "شقيبالسلام": ("שגב-שלום", NEG, 31.198, 34.836),
    "بئرالسبع": ("באר שבע", NEG, 31.252, 34.791),
    "امبطين": ("אום בטין", NEG, 31.302, 34.855),
    "بيرهداج": ("ביר הדאג׳", NEG, 31.020, 34.729),
    "قصرالسر": ("קסר א-סר", NEG, 31.080, 34.980),
    "مكحول": ("מכחול", NEG, 31.180, 35.010),
    "ابوقرينات": ("אבו קרינאת", NEG, 31.120, 34.960),
    "ابوتلول": ("אבו תלול", NEG, 31.200, 34.890),
    "عراد": ("ערד", NEG, 31.259, 35.214),
    "طمره": ("טמרה", GAL, 32.853, 35.199),
    "سخنين": ("סח׳נין", GAL, 32.864, 35.297),
    "كابول": ("כאבול", GAL, 32.869, 35.211),
    "عرابه": ("עראבה", GAL, 32.851, 35.336),
    "كفرمندا": ("כפר מנדא", GAL, 32.810, 35.260),
    "جديدهالمكر": ("ג׳דיידה-מכר", GAL, 32.928, 35.153),
    "مجدالكروم": ("מג׳ד אל-כרום", GAL, 32.920, 35.250),
    "الناصره": ("נצרת", GAL, 32.701, 35.303),
    "طرعان": ("טורעאן", GAL, 32.776, 35.373),
    "شفاعمرو": ("שפרעם", GAL, 32.806, 35.170),
    "نحف": ("נחף", GAL, 32.934, 35.316),
    "شعب": ("שעב", GAL, 32.886, 35.236),
    "ديرالاسد": ("דייר אל-אסד", GAL, 32.935, 35.270),
    "ديرحنا": ("דייר חנא", GAL, 32.862, 35.364),
    "البعنه": ("בענה", GAL, 32.946, 35.262),
    "كفرياسيف": ("כפר יאסיף", GAL, 32.954, 35.162),
    "ابوسنان": ("אבו סנאן", GAL, 32.958, 35.170),
    "المشهد": ("משהד", GAL, 32.740, 35.320),
    "كوكب": ("כאוכב אבו אל-היג׳א", GAL, 32.832, 35.250),
    "اعبلين": ("אעבלין", GAL, 32.822, 35.191),
    "كفركنا": ("כפר כנא", GAL, 32.746, 35.341),
    "كفركما": ("כפר כמא", GAL, 32.721, 35.441),
    "اكسال": ("אכסאל", GAL, 32.681, 35.318),
    "بسمهطبعون": ("בסמת טבעון", GAL, 32.738, 35.157),
    "الرينه": ("ריינה", GAL, 32.724, 35.312),
    "بيرالمكسور": ("ביר אל-מכסור", GAL, 32.776, 35.220),
    "دبوريه": ("דבוריה", GAL, 32.693, 35.372),
    "المزرعه": ("מזרעה", GAL, 32.983, 35.098),
    "ابطن": ("אבטין", GAL, 32.761, 35.110),
    "عيلوط": ("עילוט", GAL, 32.715, 35.272),
    "صندله": ("סנדלה", GAL, 32.527, 35.336),
    "عينماهل": ("עין מאהל", GAL, 32.718, 35.350),
    "يافهالناصره": ("יפיע", GAL, 32.689, 35.277),
    "المغار": ("מע׳אר", GAL, 32.890, 35.408),
    "ترشيحا": ("מעלות-תרשיחא", GAL, 33.016, 35.272),
    "طمرهالزعبيه": ("טמרה (הזועבייה)", GAL, 32.643, 35.414),
    "المقيبله": ("מוקייבלה", GAL, 32.522, 35.325),
    "كفرمصر": ("כפר מצר", GAL, 32.645, 35.420),
    "الزرازير": ("זרזיר", GAL, 32.732, 35.214),
    "الكمانه": ("כמאנה", GAL, 32.906, 35.330),
    "العفوله": ("עפולה", GAL, 32.608, 35.289),
    "الناعوره": ("נאעורה", GAL, 32.614, 35.394),
    "عيلبون": ("עיילבון", GAL, 32.836, 35.400),
    "الجش": ("ג׳ש", GAL, 33.023, 35.448),
    "طوباالزنغريه": ("טובא-זנגרייה", GAL, 32.968, 35.608),
    "الشبلي": ("שבלי-אום אל-ע׳נם", GAL, 32.703, 35.418),
    "كعبيه": ("כעביה-טבאש-חג׳אג׳רה", GAL, 32.750, 35.200),
    "البعينهنجيدات": ("בועיינה-נוג׳ידאת", GAL, 32.807, 35.371),
    "العرامشه": ("ערב אל-עראמשה", GAL, 33.070, 35.210),
    "واديسلامه": ("ואדי סלאמה", GAL, 32.870, 35.420),
    "عكا": ("עכו", MIX, 32.927, 35.082),
    "يافا": ("יפו", MIX, 32.050, 34.755),
    "اللد": ("לוד", MIX, 31.951, 34.895),
    "الرمله": ("רמלה", MIX, 31.928, 34.866),
    "حيفا": ("חיפה", MIX, 32.794, 34.990),
}
# spelling variants → canonical key
ALIASES = {
    "طيبه": "الطيبه", "طيره": "الطيره", "بافهالغربيه": "باقهالغربيه", "كفرثرع": "كفرقرع",
    "جتالمثاث": "جتالمثلث", "جت": "جتالمثلث", "جلجوليا": "جلجوليه", "جلوجليه": "جلجوليه",
    "الجديدهالمكر": "جديدهالمكر", "جديدهالمكلر": "جديدهالمكر", "جديده": "جديدهالمكر",
    "اجديده": "جديدهالمكر", "المكر": "جديدهالمكر", "عبلين": "اعبلين", "لقيه": "اللقيه",
    "تلالسبغ": "تلالسبع", "بيرالسبع": "بئرالسبع", "بئرهداج": "بيرهداج", "المشهده": "المشهد",
    "مشهد": "المشهد", "كوكبابوالهيجا": "كوكب", "كوكبابوالهيجاء": "كوكب",
    "مجداالكروم": "مجدالكروم", "تلابيبيافا": "يافا", "يافاتلابيب": "يافا",
    "الكبابيرحيفا": "حيفا", "اللدبئريعقوب": "اللد", "عارهعرعره": "عرعره",
    "طوبا": "طوباالزنغريه", "عربالشبلي": "الشبلي", "شبليامالغنم": "الشبلي",
    "كعبيهطباشحجاجره": "كعبيه", "كعبيهطباش": "كعبيه", "بعينهالنجيدات": "البعينهنجيدات",
    "نجيدات": "البعينهنجيدات", "عرامشه": "العرامشه", "زرازير": "الزرازير",
    "الزازير": "الزرازير", "قريهسالم": "سالم", "كفركمدا": "كفركما",
    "بيرالمكسورالمكمان": "بيرالمكسور", "معلوتترشيحا": "ترشيحا",
}
# Negev Bedouin tribes (عشيرة …) → Hebrew; no single map point
TRIBES = {
    "العزازمه": "שבט עזאזמה", "مسعودينالعزازمه": "שבט עזאזמה", "عزازمه": "שבט עזאזמה",
    "ابورقيق": "שבט אבו רקייק", "ابوربيعه": "שבט אבו רביעה", "الاعسم": "שבט אל-אעסם",
    "اعسم": "שבט אל-אעסם", "الاطرش": "שבט אל-אטרש", "اطرش": "שבט אל-אטרש",
    "ترابينالصانع": "שבט תראבין א-צאנע", "ابوجويعد": "שבט אבו ג׳ווייעד",
    "قبوعه": "שבט קבועה", "السيد": "שבט א-סייד", "القواعين": "שבט אל-קוואעין",
    "الهزيل": "שבט אל-הוזייל", "قديراتالصانع": "שבט קודייראת א-צאנע",
    "ابوقرينات": "שבט אבו קרינאת",
}
COUNTRIES = {
    "الولاياتالمتحدهالامريكيه", "الولاياتالمتحده", "الولاياتالمتنحدهالامريكيه", "امريكا",
    "الاردن", "عمان", "السعوديه", "المملكهالعربيهالسعوديه", "هولندا", "كولومبيه", "السودان",
    "الفلبين", "سوريا", "فرنسا", "الارجنتين", "الزرقاءالاردن", "اوتواكندا", "مولداه",
    "كندا", "المانيا", "تركيا", "مصر", "بريطانيا", "روسيا", "اوكرانيا",
}

_TRANS = str.maketrans("أإآٱةى", "ااااهي")


# ---------------------------------------------------------------- helpers
def n(v):
    return f"{int(round(v)):,}"


def pct(v, digits=1):
    return f"{LRI}{v:.{digits}f}%{PDI}"


def notices(k):
    return "הודעה אחת" if k == 1 else f"{n(k)} הודעות"


def d_dot(ts):
    return f"{ts.day:02d}.{ts.month:02d}.{ts.year}"


def d_he(ts):
    return f"{ts.day} ב{MONTHS_HE[ts.month - 1]} {ts.year}"


def norm_ar(s):
    s = str(s).strip().translate(_TRANS)
    return "".join(ch for ch in s if "ء" <= ch <= "ي")


def court_he(raw):
    k = norm_ar(raw)
    if not k:
        return NO_COURT
    return COURTS.get(k, OTHER_COURT)


def place_info(raw):
    """→ (name, region, lat, lng). Unknown → OTHER_PLACE, never the Arabic text."""
    k = norm_ar(raw)
    if not k:
        return (NO_PLACE, OTHER_REGION, None, None)
    if k.startswith("عشيره"):
        return (TRIBES.get(k[5:], OTHER_TRIBE), NEG, None, None)
    if k in COUNTRIES:
        return (ABROAD, ABROAD, None, None)
    k = ALIASES.get(k, k)
    hit = SETTLEMENTS.get(k)
    if hit is None and k.startswith("قريه"):
        hit = SETTLEMENTS.get(ALIASES.get(k[4:], k[4:]))
    if hit is None and k in TRIBES:
        return (TRIBES[k], NEG, None, None)
    return hit if hit else (OTHER_PLACE, OTHER_REGION, None, None)


def parse_dates(s):
    """dd/mm/YYYY, also with '.', '\\' or '-' separators; anything else → NaT."""
    u = pd.Series(sorted(s.unique()))
    norm = u.str.strip().str.replace(r"[.\\\-]", "/", regex=True)
    return s.map(dict(zip(u, pd.to_datetime(norm, format="%d/%m/%Y", errors="coerce"))))


def lag_label(days, buckets):
    for ub, lab in buckets:
        if ub is None or days <= ub:
            return lab
    return buckets[-1][1]


def signed_pct(v):
    r = round(v, 1)
    if r == 0:
        return "0%"
    return f"+{r:.1f}%" if r > 0 else f"{MINUS}{abs(r):.1f}%"


def court_phrase(c):
    if c in (NO_COURT, OTHER_COURT):
        return c
    return f"בית הדין ב{c}"


def _top(counts, exclude=()):
    keys = [k for k in counts.index if k not in exclude]
    return sorted(keys, key=lambda k: (-int(counts[k]), k))


# ---------------------------------------------------------------- compute
def compute(frames):
    raw = frames["main"]
    n_rows_raw = len(raw)
    raw = raw.drop_duplicates()
    n_exact_dups = n_rows_raw - len(raw)

    df = pd.DataFrame({
        "court": raw["court_name"].map(court_he),
        "pub": parse_dates(raw["published_date"]),
        "death": parse_dates(raw["deaceased_date"]),
    })
    info = raw["deaceased_address"].map(place_info)
    df["place"] = info.map(lambda t: t[0])
    df["region"] = info.map(lambda t: t[1])
    df["lat"] = info.map(lambda t: t[2])
    df["lng"] = info.map(lambda t: t[3])

    n_bad_pub = int(df["pub"].isna().sum())
    df = df[df["pub"].notna()].copy()
    # A publication date more than MAX_GAP_DAYS past the previous one breaks the
    # weekly cadence: a typo (e.g. a future year). Walk the sorted dates.
    days = sorted(df["pub"].unique())
    cut = days[0]
    for i in range(1, len(days)):
        if (days[i] - days[i - 1]) / pd.Timedelta(days=1) > MAX_GAP_DAYS:
            break
        cut = days[i]
    n_future = int((df["pub"] > cut).sum())
    df = df[df["pub"] <= cut].copy()
    total = len(df)

    last = df["pub"].max()
    first = df["pub"].min()
    last_year = int(last.year)

    # ----------------------------------------------- courts
    court_counts = df["court"].value_counts()
    courts = _top(court_counts)
    named_courts = [c for c in courts if c not in (NO_COURT, OTHER_COURT)]

    # ----------------------------------------------- monthly / quarterly publications
    months = pd.period_range(first.to_period("M"), last.to_period("M"), freq="M")
    quarterly = len(months) > MONTHLY_MAX
    if quarterly:
        periods = pd.period_range(first.to_period("Q"), last.to_period("Q"), freq="Q")
        df["per"] = df["pub"].dt.to_period("Q")
        per_labels = [f"רבעון {p.quarter} {p.year}" for p in periods]
    else:
        periods = months
        df["per"] = df["pub"].dt.to_period("M")
        per_labels = [f"{MONTHS_SHORT[p.month - 1]} {p.year}" for p in periods]
    stack = courts[:STACK_COURTS]
    other_c = "בתי דין אחרים"
    df["court_s"] = df["court"].where(df["court"].isin(stack), other_c)
    stack_names = stack + ([other_c] if len(courts) > STACK_COURTS else [])
    m_ct = df.groupby(["per", "court_s"]).size()
    monthly_series = [{"name": c if c == other_c else court_phrase(c),
                       "data": [int(m_ct.get((p, c), 0)) for p in periods]} for c in stack_names]
    m_tot = df.groupby("per").size().reindex(periods, fill_value=0)
    full = m_tot.iloc[1:-1] if len(m_tot) > 2 else m_tot
    peak_p = max(full.index, key=lambda p: (int(full[p]), -p.ordinal))
    low_p = min(full.index, key=lambda p: (int(full[p]), p.ordinal))
    peak_v, low_v = int(full[peak_p]), int(full[low_p])
    med_month = float(full.median())
    zoom_start = per_labels[max(0, len(per_labels) - 24)]

    def per_he(p):
        return f"רבעון {p.quarter} {p.year}" if quarterly else f"{MONTHS_HE[p.month - 1]} {p.year}"

    # ----------------------------------------------- month × year heatmap
    df["y"] = df["pub"].dt.year
    years = list(range(int(first.year), last_year + 1))
    hm = df.groupby(["y", df["pub"].dt.month]).size()
    heat = {"x": MONTHS_SHORT, "y": [str(y) for y in years], "cells": [], "max": 0}
    for yi, y in enumerate(years):
        for m in range(1, 13):
            if (y, m) < (first.year, first.month) or (y, m) > (last.year, last.month):
                continue
            v = int(hm.get((y, m), 0))
            heat["cells"].append([m - 1, yi, v])
            heat["max"] = max(heat["max"], v)

    # ----------------------------------------------- yearly publications
    y_ct = df.groupby(["y", "court"]).size()
    year_partial = not (last.month == 12 and last.day >= 24)
    first_partial = not (first.month == 1 and first.day <= 10)
    year_labels = []
    for y in years:
        lab = str(y)
        if y == last_year and year_partial:
            lab = f"{y} (עד {d_dot(last)[:5]})"
        elif y == years[0] and first_partial and y != last_year:
            lab = f"{y} (מ־{d_dot(first)[:5]})"
        year_labels.append(lab)
    years_chart = {"x": [court_phrase(c) for c in courts],
                   "series": [{"name": year_labels[i],
                               "data": [int(y_ct.get((y, c), 0)) for c in courts]}
                              for i, y in enumerate(years)]}
    years_table = [{"court": court_phrase(c), "cells": [n(y_ct.get((y, c), 0)) for y in years],
                    "total": n(court_counts[c])} for c in courts]

    def upto(ts, y):
        return ((ts.dt.year == y) & ((ts.dt.month < last.month) |
                                     ((ts.dt.month == last.month) & (ts.dt.day <= last.day))))
    ytd = int(upto(df["pub"], last_year).sum())
    prev_ytd = int(upto(df["pub"], last_year - 1).sum())
    ytd_chg = (ytd - prev_ytd) / prev_ytd * 100 if prev_ytd >= 50 else None

    # ----------------------------------------------- weekday / batches
    wd = df["pub"].dt.dayofweek.value_counts()
    batches = df.groupby("pub").size()
    n_batches = len(batches)
    wd_dates = pd.Series(batches.index).dt.dayofweek.value_counts()
    weekday_chart = {"x": [WEEKDAYS_HE[i] for i in WEEK_ORDER],
                     "y": [int(wd.get(i, 0)) for i in WEEK_ORDER]}
    weekday_table = [{"day": WEEKDAYS_HE[i], "notices": n(wd.get(i, 0)),
                      "dates": n(wd_dates.get(i, 0))} for i in WEEK_ORDER]
    top_wd = max(range(7), key=lambda i: (int(wd.get(i, 0)), -i))
    top_wd_share = int(wd.get(top_wd, 0)) / total if total else 0
    batch_med = float(batches.median())
    batch_max = int(batches.max())

    # ----------------------------------------------- settlements / regions
    p_ct = df["place"].value_counts()
    buckets = (OTHER_PLACE, NO_PLACE, ABROAD, OTHER_TRIBE)
    known_places = _top(p_ct, exclude=buckets)
    n_places = len(known_places)
    n_abroad = int(p_ct.get(ABROAD, 0))
    n_unknown = int(p_ct.get(OTHER_PLACE, 0)) + int(p_ct.get(OTHER_TRIBE, 0))
    region_of = dict(sorted(zip(df["place"], df["region"])))
    pc = (df.groupby(["place", "court"]).size().reset_index(name="k")
          .sort_values(["place", "k", "court"], ascending=[True, False, True], kind="mergesort")
          .drop_duplicates("place"))
    main_court = dict(zip(pc["place"], pc["court"]))

    top = known_places[:TOP_PLACES]
    rest = total - int(sum(int(p_ct[p]) for p in top))
    regions_present = [r for r in REGION_ORDER if r in set(df["region"])]
    place_rows = list(reversed(top))   # bottom→top for a horizontal bar
    # the "rest" bucket stays in the table only — as a bar it would dwarf the ranking
    places_chart = {"y": place_rows, "series": []}
    for r in regions_present:
        if r in (OTHER_REGION, ABROAD):
            continue
        data = [int(p_ct[p]) if region_of.get(p) == r else 0 for p in place_rows]
        if any(data):
            places_chart["series"].append({"name": r, "data": data})
    places_table = [{"place": p, "region": region_of.get(p, OTHER_REGION),
                     "court": court_phrase(main_court.get(p, NO_COURT)),
                     "count": n(p_ct[p]), "share": pct(int(p_ct[p]) / total * 100)} for p in top]
    if rest:
        places_table.append({"place": "שאר היישובים", "region": "—", "court": "—",
                             "count": n(rest), "share": pct(rest / total * 100)})

    r_ct = df["region"].value_counts()
    r_places = df[~df["place"].isin(buckets)].groupby("region")["place"].nunique()
    rc = (df.groupby(["region", "court"]).size().reset_index(name="k")
          .sort_values(["region", "k", "court"], ascending=[True, False, True], kind="mergesort")
          .drop_duplicates("region"))
    r_main_court = dict(zip(rc["region"], rc["court"]))
    regions_table = [{"region": r, "places": n(r_places.get(r, 0)), "count": n(r_ct.get(r, 0)),
                      "share": pct(int(r_ct.get(r, 0)) / total * 100),
                      "court": court_phrase(r_main_court.get(r, NO_COURT))}
                     for r in regions_present]

    pts = df[df["lat"].notna()].groupby("place").agg(lat=("lat", "first"), lng=("lng", "first"),
                                                     k=("court", "size"))
    map_points = [[float(pts.at[p, "lat"]), float(pts.at[p, "lng"]), int(pts.at[p, "k"]), p,
                   region_of.get(p, OTHER_REGION), court_phrase(main_court.get(p, NO_COURT))]
                  for p in _top(pts["k"])]
    n_mapped = int(sum(pt[2] for pt in map_points))

    # ----------------------------------------------- court catchment (treemap)
    cp = df.groupby(["court", "place"]).size()
    tree, catch_rows = [], []
    for c in courts:
        sub = cp.loc[c]
        named = sub[[p for p in sub.index if p not in buckets]]
        order = _top(named)
        kids = [{"name": p, "value": int(named[p])} for p in order[:TREE_PLACES]]
        rest_c = int(sub.sum()) - sum(k["value"] for k in kids)
        if rest_c:
            kids.append({"name": "שאר היישובים", "value": rest_c})
        tree.append({"name": court_phrase(c), "value": int(sub.sum()), "children": kids})
        if order:
            catch_rows.append({"court": c, "count": int(sub.sum()), "places": len(order),
                               "top": order[0], "top_share": int(named[order[0]]) / int(sub.sum())})
    catch_table = [{"court": court_phrase(r["court"]), "count": n(r["count"]),
                    "places": n(r["places"]), "top": r["top"], "share": pct(r["top_share"] * 100)}
                   for r in catch_rows]

    # ----------------------------------------------- lag death → notice
    lagdf = df[df["death"].notna()].copy()
    lagdf["lag"] = (lagdf["pub"] - lagdf["death"]).dt.days
    n_neg = int((lagdf["lag"] < 0).sum())
    n_bad_death = int(df["death"].isna().sum())
    lagdf = lagdf[lagdf["lag"] >= 0].copy()
    n_lag = len(lagdf)
    lagdf["b"] = lagdf["lag"].map(lambda d: lag_label(d, LAG_BUCKETS))
    b_ct = lagdf["b"].value_counts()
    lag_chart = {"x": [lab for _, lab in LAG_BUCKETS],
                 "y": [int(b_ct.get(lab, 0)) for _, lab in LAG_BUCKETS]}
    lag_table = [{"bucket": lab, "count": n(b_ct.get(lab, 0)),
                  "share": pct(int(b_ct.get(lab, 0)) / n_lag * 100 if n_lag else 0)}
                 for _, lab in LAG_BUCKETS]
    lag_med_days = float(lagdf["lag"].median()) if n_lag else None
    lag_med_months = lag_med_days / 30.4375 if lag_med_days is not None else None
    within_half = int((lagdf["lag"] <= 182).sum())
    over10 = int((lagdf["lag"] > 3652).sum())
    over20 = int((lagdf["lag"] > 7305).sum())

    # lag mix per court
    lagdf["g"] = lagdf["lag"].map(lambda d: lag_label(d, LAG_GROUPS))
    lc = lagdf.groupby("court").size()
    g_ct = lagdf.groupby(["court", "g"]).size()
    c_med = lagdf.groupby("court")["lag"].median()
    lag_courts = [c for c in named_courts if int(lc.get(c, 0)) >= MIN_LAG_COURT]
    lag_courts.sort(key=lambda c: (float(c_med[c]), c))
    lag_court_rows = [{"court": c, "n": int(lc[c]), "median": float(c_med[c])} for c in lag_courts]
    lag_court_chart = {
        "y": [court_phrase(c) for c in lag_courts],
        "series": [{"name": lab,
                    "data": [round(int(g_ct.get((c, lab), 0)) / int(lc[c]) * 100, 1)
                             for c in lag_courts]} for _, lab in LAG_GROUPS],
    }
    lag_court_table = [{"court": court_phrase(c), "count": n(lc[c]),
                        "cells": [pct(int(g_ct.get((c, lab), 0)) / int(lc[c]) * 100)
                                  for _, lab in LAG_GROUPS],
                        "median": f"{float(c_med[c]) / 30.4375:.1f}"} for c in lag_courts]

    # ----------------------------------------------- year of death
    dy = lagdf["death"]
    max_dy = int(dy.dt.year.max()) if len(dy) else last_year
    dcut = max_dy - DEATH_YEARS + 1
    dyc = dy.dt.year.value_counts()
    older = int(dyc[dyc.index < dcut].sum())
    death_x, death_y = [], []
    if older:
        death_x.append(f"לפני {dcut}")
        death_y.append(older)
    for y in range(dcut, max_dy + 1):
        death_x.append(str(y))
        death_y.append(int(dyc.get(y, 0)))
    oldest_year = int(dy.dt.year.min()) if len(dy) else None
    death_table = [{"year": death_x[i], "count": n(death_y[i])} for i in range(len(death_x))]

    # ----------------------------------------------- month of death (seasonality)
    ds = lagdf["death"]
    placeholder = (ds.dt.month == 1) & (ds.dt.day == 1)
    n_placeholder = int(placeholder.sum())
    ds = ds[~placeholder]
    n_season = len(ds)
    mc = ds.dt.month.value_counts()
    winter_months = [12, 1, 2]
    season_chart = {"x": MONTHS_HE, "y": [int(mc.get(m, 0)) for m in range(1, 13)],
                    "winter": [m in winter_months for m in range(1, 13)]}
    season_table = [{"month": MONTHS_HE[m - 1], "count": n(mc.get(m, 0))} for m in range(1, 13)]
    winter_share = sum(int(mc.get(m, 0)) for m in winter_months) / n_season if n_season else 0
    summer_share = sum(int(mc.get(m, 0)) for m in (6, 7, 8)) / n_season if n_season else 0

    # ================================================= insights
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    # 1. same-period comparison
    def ins_ytd():
        if ytd_chg is None:
            return None
        period = f"מתחילת {last_year} ועד {d_he(last)}"
        if abs(ytd_chg) < 5:
            trend = (f"דומה לתקופה המקבילה ב־{last_year - 1} ({n(prev_ytd)}"
                     + (", ללא שינוי" if round(ytd_chg, 1) == 0 else f", {LRI}{signed_pct(ytd_chg)}{PDI}")
                     + ")")
        else:
            word = "עלייה" if ytd_chg > 0 else "ירידה"
            trend = (f"{word} של {pct(abs(ytd_chg), 0)} לעומת התקופה המקבילה ב־{last_year - 1} "
                     f"({n(prev_ytd)})")
        return f"{period} פורסמו {n(ytd)} הודעות על בקשות לצו ירושה — {trend}."
    add("ytd", ins_ytd())

    # 2. which court carries the load
    def ins_court():
        if len(named_courts) < 2 or total < 50:
            return None
        c1, c2 = named_courts[0], named_courts[1]
        v1, v2 = int(court_counts[c1]), int(court_counts[c2])
        if v1 / total < 0.2 or v1 < 1.2 * v2:
            return None
        return (f"{court_phrase(c1)} מוביל: {n(v1)} הודעות, {pct(v1 / total * 100, 0)} מכלל "
                f"ההודעות — פי {v1 / v2:.1f} מ{court_phrase(c2)} שאחריו ({n(v2)}).")
    add("court_lead", ins_court())

    # 3. time from death to notice
    def ins_lag():
        if n_lag < MIN_LAG_N:
            return None
        txt = (f"החציון בין הפטירה לפרסום הבקשה הוא {lag_med_months:.1f} חודשים, "
               f"ו־{pct(within_half / n_lag * 100, 0)} מהבקשות פורסמו בתוך חצי שנה.")
        if over20 / n_lag >= 0.05:
            txt += (f" מנגד, {pct(over20 / n_lag * 100, 0)} ({n(over20)} הודעות) נוגעות לפטירות "
                    f"של לפני יותר מעשרים שנה — ירושות שמוסדרות רק אחרי דור.")
        elif over10 / n_lag >= 0.1:
            txt += (f" מנגד, {pct(over10 / n_lag * 100, 0)} ({n(over10)} הודעות) נוגעות לפטירות "
                    f"של לפני יותר מעשר שנים.")
        return txt
    add("lag", ins_lag())

    # 4. court contrast in lag
    def ins_lag_courts():
        if len(lag_court_rows) < 3:
            return None
        fast, slow = lag_court_rows[0], lag_court_rows[-1]
        if fast["median"] <= 0 or slow["median"] / fast["median"] < 1.5:
            return None
        return (f"הפער בין בתי הדין: ב{court_phrase(slow['court'])} עוברים בחציון "
                f"{slow['median'] / 30.4375:.1f} חודשים מהפטירה ועד פרסום הבקשה, לעומת "
                f"{fast['median'] / 30.4375:.1f} חודשים ב{court_phrase(fast['court'])}.")
    add("lag_courts", ins_lag_courts())

    # 5. settlement concentration
    def ins_places():
        if len(known_places) < 3 or total < 50:
            return None
        t1 = known_places[0]
        s1 = int(p_ct[t1]) / total
        s5 = sum(int(p_ct[p]) for p in known_places[:5]) / total
        if s5 < 0.25:
            return None
        return (f"הנפטרים התגוררו ב־{n(n_places)} יישובים ושבטים לפחות. {t1} לבדה — "
                f"{pct(s1 * 100, 0)} מההודעות ({n(p_ct[t1])}); חמשת היישובים המובילים יחד — "
                f"{pct(s5 * 100, 0)}.")
    add("places", ins_places())

    # 6. catchment breadth
    def ins_catch():
        rows = [r for r in catch_rows if r["count"] >= 100]
        if len(rows) < 3:
            return None
        wide = max(rows, key=lambda r: (r["places"], r["court"]))
        narrow = min(rows, key=lambda r: (r["places"], r["court"]))
        if wide["places"] < 2 * narrow["places"]:
            return None
        return (f"אזורי השיפוט שונים מאוד: ל{court_phrase(wide['court'])} הגיעו בקשות מ־"
                f"{n(wide['places'])} יישובים ושבטים, ול{court_phrase(narrow['court'])} — מ־"
                f"{n(narrow['places'])} בלבד; {pct(narrow['top_share'] * 100, 0)} מהבקשות בו הן "
                f"של תושבי {narrow['top']}.")
    add("catchment", ins_catch())

    # 7. publication rhythm
    def ins_weekday():
        if total < 50 or top_wd_share < 0.5:
            return None
        return (f"ההודעות מתפרסמות במנות שבועיות: {pct(top_wd_share * 100, 0)} מהן פורסמו ביום "
                f"{WEEKDAYS_HE[top_wd]}, ובחציון {batch_med:.0f} הודעות בכל מועד פרסום.")
    add("weekday", ins_weekday())

    # 8. winter deaths
    def ins_winter():
        if n_season < SEASON_MIN_N:
            return None
        thr = 0.25 + 2.5 * math.sqrt(0.25 * 0.75 / n_season)
        if winter_share < thr:
            return None
        return (f"{pct(winter_share * 100, 0)} מהפטירות שתאריכן ידוע אירעו בחודשי החורף "
                f"(דצמבר עד פברואר), לעומת {pct(summer_share * 100, 0)} בחודשי הקיץ "
                f"(יוני עד אוגוסט) — יותר מרבע שהיה צפוי בפיזור אחיד.")
    add("winter", ins_winter())

    # ================================================= KPIs
    kpis = {
        "total": {"value": total, "display": n(total), "tone": "brand"},
        "ytd": {"value": ytd, "display": n(ytd), "tone": "brand"},
        "ytd_change": {
            "value": None if ytd_chg is None else round(ytd_chg, 1),
            "display": "—" if ytd_chg is None else signed_pct(ytd_chg),
            "tone": "brand" if ytd_chg is None or abs(ytd_chg) < 10 else "info",
        },
        "lag": {"value": None if lag_med_months is None else round(lag_med_months, 1),
                "display": "—" if lag_med_months is None else f"{lag_med_months:.1f}",
                "tone": "info"},
        "old": {"value": round(over10 / n_lag * 100, 1) if n_lag else None,
                "display": f"{over10 / n_lag * 100:.1f}%" if n_lag else "—",
                "tone": "warn" if n_lag and over10 / n_lag >= 0.2 else "brand"},
        "places": {"value": n_places, "display": n(n_places), "tone": "brand"},
        "courts": {"value": len(named_courts), "display": n(len(named_courts)), "tone": "brand"},
    }

    # ================================================= labels
    span = f"{d_he(first)} עד {d_he(last)}"
    excl = []
    if n_future:
        excl.append(f"{notices(n_future)} שתאריך הפרסום שלהן חורג מרצף הפרסומים (כנראה שגיאת הקלדה)")
    if n_bad_pub:
        excl.append(f"{notices(n_bad_pub)} ללא תאריך פרסום תקין")
    dups_txt = (" לא נכללו " + " ו־".join(excl) + "." if excl else "")
    if n_exact_dups:
        dups_txt += f" {n(n_exact_dups)} שורות כפולות זהות הוסרו."
    lead_c = named_courts[0]
    lede = (f"הודעות שמפרסמים בתי הדין השרעיים על בקשות לצו ירושה, כדי שמי שמתנגד יוכל להגיש "
            f"התנגדות. במאגר {n(total)} הודעות שפורסמו בערבית מ־{span}, ב־{n(len(named_courts))} "
            f"בתי דין, על עזבונות של נפטרים מ־{n(n_places)} יישובים ושבטים. "
            f"{court_phrase(lead_c)} מפרסם {pct(court_counts[lead_c] / total * 100, 0)} "
            f"מההודעות. העמוד מציג נתונים מצרפיים בלבד — ללא שמות הנפטרים, היורשים או המבקשים, וללא "
            f"מספרי זהות ומספרי תיקים." + dups_txt)

    lm = last.to_period("M")
    period_word = "רבעון" if quarterly else "חודש"
    monthly_note = (f"מספר ההודעות שפורסמו בכל {period_word}, לפי בית הדין. בחציון {med_month:.0f} "
                    f"הודעות ב{period_word}; השיא — {per_he(peak_p)} ({n(peak_v)}), השפל — "
                    f"{per_he(low_p)} ({n(low_v)}), ללא ה{period_word} הראשון והאחרון שאינם מלאים. "
                    f"ה{period_word} האחרון כולל פרסומים עד {d_he(last)}.")
    years_note = (f"הודעות לפי בית דין ושנת פרסום."
                  + (f" {last_year} חלקית — עד {d_he(last)}." if year_partial else "")
                  + (f" {years[0]} — מ־{d_he(first)} בלבד." if first_partial and len(years) > 1 else ""))
    heat_note = (f"הודעות לפי חודש ושנת פרסום, {MONTHS_HE[first.month - 1]} {first.year} עד "
                 f"{MONTHS_HE[lm.month - 1]} {lm.year}. התא האחרון כולל פרסומים עד {d_he(last)}.")
    weekday_note = (f"באיזה יום בשבוע מתפרסמות ההודעות. {n(n_batches)} מועדי פרסום; בחציון "
                    f"{batch_med:.0f} הודעות במועד, ובמועד הגדול ביותר {n(batch_max)}.")
    map_note = (f"כל עיגול הוא יישוב מגוריו של הנפטר; גודלו לפי מספר ההודעות. במפה {n(n_mapped)} "
                f"הודעות; שבטים בנגב, תושבי חו״ל ויישובים שלא זוהו אינם מוצגים בה.")
    places_note = (f"הודעות לפי יישוב המגורים של הנפטר ({n(TOP_PLACES)} המובילים, אחרי איחוד צורות "
                   f"כתיב שונות של אותו יישוב), בצבע לפי אזור. "
                   f"שאר היישובים ({n(rest)} הודעות) מופיעים בטבלה בלבד"
                   + (f"; ביניהן {n(n_unknown)} מיישובים ושבטים שלא זוהו ו־{n(n_abroad)} של תושבי "
                      f"חו״ל" if n_unknown or n_abroad else "") + ".")
    tree_note = (f"מאילו יישובים מגיעות הבקשות לכל בית דין: {n(TREE_PLACES)} היישובים המובילים "
                 f"בכל בית דין, והשאר מאוגדים. לחיצה על בית דין מתמקדת בו.")
    lag_note = (f"הזמן שחלף מיום הפטירה ועד פרסום ההודעה, ב־{n(n_lag)} הודעות שבהן שני התאריכים "
                f"תקינים"
                + (f"; {notices(n_bad_death)} בלי תאריך פטירה תקין" if n_bad_death else "")
                + (f" ו־{n(n_neg)} שבהן תאריך הפטירה מאוחר מהפרסום (שגיאת הקלדה) לא נכללו"
                   if n_neg else (" לא נכללו" if n_bad_death else ""))
                + ".")
    lag_court_note = (f"חלוקת ההודעות בכל בית דין לפי הזמן שחלף מהפטירה, באחוזים, מהמהיר לאיטי "
                      f"לפי החציון (בתי דין עם {n(MIN_LAG_COURT)} הודעות לפחות שבהן תאריך פטירה תקין).")
    death_note = (f"שנת הפטירה של הנפטרים שעזבונם נדון; השנים שלפני {dcut} מקובצות"
                  + (f" (הוותיקה ביותר: {oldest_year})" if oldest_year and older else "") + ".")
    season_note = (f"חודש הפטירה, ב־{n(n_season)} הודעות עם תאריך פטירה מלא"
                   + (f" (ללא {n(n_placeholder)} תאריכים של הראשון בינואר, שנראים כתאריך משוער)"
                      if n_placeholder else "")
                   + ". חודשי החורף מודגשים.")

    top_place = known_places[0] if known_places else ""
    labels = {
        "lede": lede,
        "ytd_kpi": f"הודעות ב־{last_year} (עד {d_dot(last)})",
        "ytd_change_kpi": f"שינוי לעומת התקופה המקבילה ב־{last_year - 1}",
        "lag_median_kpi": "חציון חודשים מהפטירה ועד ההודעה",
        "old_kpi": "בקשות על פטירות של יותר מעשר שנים",
        "places_kpi": "יישובים ושבטים במאגר",
        "notice_count": "הודעות במאגר",
        "courts_kpi": "בתי דין שרעיים",
        "monthly_note": monthly_note,
        "monthly_aria": (f"גרף עמודות מוערמות: הודעות ירושה לפי {period_word} ובית דין. שיא "
                         f"ב{per_he(peak_p)} עם {n(peak_v)} הודעות."),
        "years_note": years_note,
        "years_aria": f"גרף עמודות: הודעות לפי בית דין ושנה. {court_phrase(lead_c)} מוביל.",
        "years_caption": "הודעות לפי בית דין ושנת פרסום",
        "heat_note": heat_note,
        "heat_aria": "מפת חום: הודעות לפי חודש ושנת פרסום.",
        "weekday_note": weekday_note,
        "weekday_aria": (f"גרף עמודות: הודעות לפי יום בשבוע. יום {WEEKDAYS_HE[top_wd]} מוביל עם "
                         f"{pct(top_wd_share * 100, 0)} מההודעות."),
        "weekday_caption": "הודעות ומועדי פרסום לפי יום בשבוע",
        "map_note": map_note,
        "map_aria": "מפה אינטראקטיבית של יישובי הנפטרים לפי מספר ההודעות. גרסה נגישה: ראו טבלה למטה.",
        "regions_caption": "הודעות לפי אזור",
        "places_note": places_note,
        "places_aria": (f"גרף עמודות אופקי: הודעות לפי יישוב. {top_place} מובילה עם "
                        f"{n(p_ct[top_place]) if top_place else '0'} הודעות."),
        "places_caption": "הודעות לפי יישוב המגורים של הנפטר",
        "tree_note": tree_note,
        "tree_aria": "מפת עץ: הודעות לפי בית דין ויישוב המגורים של הנפטר.",
        "catch_caption": "מספר היישובים והיישוב המוביל בכל בית דין",
        "lag_note": lag_note,
        "lag_aria": (f"היסטוגרמה: הזמן מהפטירה ועד פרסום ההודעה. החציון "
                     f"{'—' if lag_med_months is None else f'{lag_med_months:.1f}'} חודשים."),
        "lag_caption": "הודעות לפי הזמן מהפטירה ועד הפרסום",
        "lag_court_note": lag_court_note,
        "lag_court_aria": "גרף עמודות אופקיות מוערמות באחוזים: חלוקת ההודעות בכל בית דין לפי הזמן מהפטירה.",
        "lag_court_caption": "הזמן מהפטירה לפי בית דין",
        "death_note": death_note,
        "death_aria": "גרף עמודות: הודעות לפי שנת הפטירה.",
        "death_caption": "הודעות לפי שנת הפטירה",
        "season_note": season_note,
        "season_aria": f"גרף עמודות: פטירות לפי חודש. {pct(winter_share * 100, 0)} בחודשי החורף.",
        "season_caption": "פטירות לפי חודש",
    }

    summary = (f"{n(total)} הודעות על בקשות לצו ירושה שפרסמו בתי הדין השרעיים בין {first.year} "
               f"ל־{last.year}, על עזבונות מ־{n(n_places)} יישובים ושבטים"
               + (f"; החציון בין הפטירה להודעה הוא {lag_med_months:.1f} חודשים" if lag_med_months else "")
               + ". נתונים מצרפיים בלבד, ללא שמות.")

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "suggested_tags": ["ירושה", "צווי ירושה", "בתי דין שרעיים", "מעמד אישי",
                               "משרד המשפטים"],
            "related_ids": ["da374239-7f83-43bc-a60f-36fc8380a093",
                            "cdf9391c-e51d-48d7-aacc-2dade6e63c09",
                            "eda6d5e4-b6ed-478e-a92b-71e0baab84b6",
                            "ecae900d-a67a-4a65-ad4d-7cf452e8c6a4",
                            "7368d9de-e3ea-43e9-9e7d-03ffffe79b5f"],
            "temporal_coverage": f"{first.year}/{last.year}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": {
            "monthly": {"x": per_labels, "series": monthly_series, "zoom_start": zoom_start},
            "years": years_chart,
            "heat": heat,
            "weekday": weekday_chart,
            "map": {"points": map_points},
            "places": places_chart,
            "tree": tree,
            "lag": lag_chart,
            "lag_court": lag_court_chart,
            "death": {"x": death_x, "y": death_y},
            "season": season_chart,
        },
        "tables": {
            "year_labels": year_labels,
            "courts": years_table,
            "weekday": weekday_table,
            "regions": regions_table,
            "places": places_table,
            "catch": catch_table,
            "lag": lag_table,
            "lag_groups": [lab for _, lab in LAG_GROUPS],
            "lag_court": lag_court_table,
            "death": death_table,
            "season": season_table,
        },
        "insights": insights,
        "labels": labels,
        "flags": {
            "map": len(map_points) >= 3,
            "lag_court": len(lag_courts) >= 2,
            "season": n_season >= SEASON_MIN_N,
            "death": bool(death_x),
        },
    }
