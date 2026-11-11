"""אמנות משרד החוץ: Israel's bilateral treaties and agreements since 1948.

One row per instrument (folder_number is unique; a letter suffix such as
"311-A" marks a supplementary instrument to folder 311). Columns are typed by
hand at the ministry, so compute() normalises them:

- Parties: one counterpart per row, in English with variant spellings
  ("%26" for "&", "UNITED KINGDOM", three Serbia-and-Montenegro spellings).
  PARTIES maps each known spelling to a Hebrew name and a region; an unknown
  name is shown as typed, in region "לא מסווג".
- Subject_main: comma-separated subjects, sometimes repeated in one cell.
  Each instrument counts once per distinct subject.
- Language1: comma-separated languages of the linked text files, in English
  or Hebrew, with placeholders ("document", "Double/multiple", "לא ידוע")
  that are not languages.
- The chronology year is the signature year, or the entry-into-force year
  when no signature date was recorded (disclosed on the page).
- Treaty_Name is an English (rarely Hebrew or French) title; its instrument
  word (AGREEMENT, CONVENTION, EXCHANGE OF NOTES, ...) gives the form. The
  earliest such word in the title wins, typos included.
"""
import re
from collections import Counter

import pandas as pd
from govlib.fmt import int_he, join_he, pct
from govlib.frame import clean_series, ranked, top_other

ORGS = "ארגונים בין-לאומיים"
EUROPE = "אירופה"
ASIA = "אסיה"
AFRICA = "אפריקה"
MENA = "המזרח התיכון וצפון אפריקה"
NAMERICA = "צפון אמריקה"
LATAM = "אמריקה הלטינית והקריביים"
OCEANIA = "אוקיאניה"
UNCLASSIFIED = "לא מסווג"
REGION_ORDER = [EUROPE, NAMERICA, LATAM, ASIA, AFRICA, MENA, OCEANIA, ORGS, UNCLASSIFIED]

# Lower-cased, whitespace-collapsed spelling -> (Hebrew name, region).
PARTIES = {
    "albania": ("אלבניה", EUROPE), "angola": ("אנגולה", AFRICA),
    "argentina": ("ארגנטינה", LATAM), "armenia": ("ארמניה", ASIA),
    "australia": ("אוסטרליה", OCEANIA), "austria": ("אוסטריה", EUROPE),
    "azerbaijan": ("אזרבייג׳ן", ASIA), "bahamas": ("איי בהאמה", LATAM),
    "bahrain": ("בחריין", MENA), "barbados": ("ברבדוס", LATAM),
    "belarus": ("בלארוס", EUROPE), "belgium": ("בלגיה", EUROPE),
    "belize": ("בליז", LATAM), "bolivia": ("בוליביה", LATAM),
    "bosnia & herzegovina": ("בוסניה והרצגובינה", EUROPE),
    "brazil": ("ברזיל", LATAM), "bulgaria": ("בולגריה", EUROPE),
    "burkina faso": ("בורקינה פאסו", AFRICA), "cameroon": ("קמרון", AFRICA),
    "canada": ("קנדה", NAMERICA), "cape verde": ("כף ורדה", AFRICA),
    "central african republic": ("הרפובליקה המרכז-אפריקאית", AFRICA),
    "chad": ("צ׳אד", AFRICA), "chile": ("צ׳ילה", LATAM), "china": ("סין", ASIA),
    "colombia": ("קולומביה", LATAM), "congo": ("קונגו", AFRICA),
    "congo (democratic republic)": ("הרפובליקה הדמוקרטית של קונגו", AFRICA),
    "costa rica": ("קוסטה ריקה", LATAM), "cote divoire": ("חוף השנהב", AFRICA),
    "cote d'ivoire": ("חוף השנהב", AFRICA), "croatia": ("קרואטיה", EUROPE),
    "cyprus": ("קפריסין", EUROPE), "czech republic": ("צ׳כיה", EUROPE),
    "denmark": ("דנמרק", EUROPE), "dominica": ("דומיניקה", LATAM),
    "dominican republic": ("הרפובליקה הדומיניקנית", LATAM),
    "ecuador": ("אקוודור", LATAM), "egypt": ("מצרים", MENA),
    "el salvador": ("אל סלבדור", LATAM), "estonia": ("אסטוניה", EUROPE),
    "ethiopia": ("אתיופיה", AFRICA), "european union": ("האיחוד האירופי", ORGS),
    "fiji": ("פיג׳י", OCEANIA), "finland": ("פינלנד", EUROPE),
    "france": ("צרפת", EUROPE), "gabon": ("גבון", AFRICA),
    "gambia": ("גמביה", AFRICA), "georgia": ("גאורגיה", ASIA),
    "germany": ("גרמניה", EUROPE), "ghana": ("גאנה", AFRICA),
    "greece": ("יוון", EUROPE), "guatemala": ("גואטמלה", LATAM),
    "guinea-bissau": ("גינאה-ביסאו", AFRICA), "guyana": ("גיאנה", LATAM),
    "haiti": ("האיטי", LATAM), "holland- the netherlands": ("הולנד", EUROPE),
    "netherlands": ("הולנד", EUROPE), "holy see": ("הכס הקדוש", EUROPE),
    "honduras": ("הונדורס", LATAM), "hong kong": ("הונג קונג", ASIA),
    "hungary": ("הונגריה", EUROPE), "iceland": ("איסלנד", EUROPE),
    "india": ("הודו", ASIA), "international organizations": ("ארגונים בין-לאומיים", ORGS),
    "int": ("ארגונים בין-לאומיים", ORGS), "ireland": ("אירלנד", EUROPE),
    "italy": ("איטליה", EUROPE), "jamaica": ("ג׳מייקה", LATAM),
    "japan": ("יפן", ASIA), "jordan": ("ירדן", MENA),
    "kazakhstan": ("קזחסטן", ASIA), "kenya": ("קניה", AFRICA),
    "kosovo": ("קוסובו", EUROPE), "latvia": ("לטביה", EUROPE),
    "lesotho": ("לסוטו", AFRICA), "liberia": ("ליבריה", AFRICA),
    "lithuania": ("ליטא", EUROPE), "luxembourg": ("לוקסמבורג", EUROPE),
    "macedonia (fyrom)": ("מקדוניה הצפונית", EUROPE),
    "madagascar": ("מדגסקר", AFRICA), "malawi": ("מלאווי", AFRICA),
    "mali": ("מאלי", AFRICA), "malta": ("מלטה", EUROPE),
    "marshall islands": ("איי מרשל", OCEANIA), "mauritius": ("מאוריציוס", AFRICA),
    "mexico": ("מקסיקו", LATAM), "micronesia": ("מיקרונזיה", OCEANIA),
    "moldova": ("מולדובה", EUROPE), "mongolia": ("מונגוליה", ASIA),
    "montenegro": ("מונטנגרו", EUROPE), "morocco": ("מרוקו", MENA),
    "myanmar": ("מיאנמר", ASIA), "nauru": ("נאורו", OCEANIA),
    "nepal": ("נפאל", ASIA), "new zealand": ("ניו זילנד", OCEANIA),
    "nicaragua": ("ניקרגואה", LATAM), "niger": ("ניז׳ר", AFRICA),
    "nigeria": ("ניגריה", AFRICA), "norway": ("נורווגיה", EUROPE),
    "palau": ("פלאו", OCEANIA), "panama": ("פנמה", LATAM),
    "paraguay": ("פרגוואי", LATAM), "peru": ("פרו", LATAM),
    "philippines": ("הפיליפינים", ASIA), "poland": ("פולין", EUROPE),
    "portugal": ("פורטוגל", EUROPE), "republic of korea": ("דרום קוריאה", ASIA),
    "romania": ("רומניה", EUROPE), "russian federation": ("רוסיה", EUROPE),
    "rwanda": ("רואנדה", AFRICA), "san marino": ("סן מרינו", EUROPE),
    "senegal": ("סנגל", AFRICA), "serbia": ("סרביה", EUROPE),
    "sierra leone": ("סיירה לאון", AFRICA), "singapore": ("סינגפור", ASIA),
    "slovakia": ("סלובקיה", EUROPE), "slovenia": ("סלובניה", EUROPE),
    "south africa": ("דרום אפריקה", AFRICA), "spain": ("ספרד", EUROPE),
    "sri lanka": ("סרי לנקה", ASIA), "st. kitts and nevis": ("סנט קיטס ונוויס", LATAM),
    "st. lucia": ("סנט לוסיה", LATAM), "suriname": ("סורינאם", LATAM),
    "swaziland": ("אסוואטיני", AFRICA), "sweden": ("שוודיה", EUROPE),
    "switzerland": ("שווייץ", EUROPE), "taiwan": ("טאיוואן", ASIA),
    "thailand": ("תאילנד", ASIA), "togo": ("טוגו", AFRICA),
    "trinidad & tobago": ("טרינידד וטובגו", LATAM), "turkey": ("טורקיה", MENA),
    "turkmenistan": ("טורקמניסטן", ASIA), "tuvalu": ("טובאלו", OCEANIA),
    "un": ("האו״ם", ORGS), "united kingdom": ("בריטניה", EUROPE),
    "uganda": ("אוגנדה", AFRICA), "ukraine": ("אוקראינה", EUROPE),
    "united arab emirates": ("איחוד האמירויות", MENA),
    "united states of america": ("ארצות הברית", NAMERICA),
    "uruguay": ("אורוגוואי", LATAM), "uzbekistan": ("אוזבקיסטן", ASIA),
    "vanuatu": ("ונואטו", OCEANIA), "venezuela": ("ונצואלה", LATAM),
    "viet nam": ("וייטנאם", ASIA), "zambia": ("זמביה", AFRICA),
}
YUGO = ("סרביה ומונטנגרו (יוגוסלביה)", EUROPE)

SUBJECTS = {
    "economic and fiscal matters": "כלכלה ומיסוי",
    "consular matters": "עניינים קונסולריים",
    "culture. education. science": "תרבות, חינוך ומדע",
    "diplomatic cooperation": "שיתוף פעולה דיפלומטי",
    "transportation": "תחבורה",
    "trade": "סחר",
    "intl. development (mashav)": "סיוע בין-לאומי (מש״ב)",
    "agriculture": "חקלאות",
    "research and development": "מחקר ופיתוח",
    "communications": "תקשורת",
    "tourism": "תיירות",
    "social matters": "עניינים חברתיים",
    "health": "בריאות",
    "public security": "ביטחון הפנים",
    "criminal legal matters": "משפט פלילי",
    "environment": "איכות הסביבה",
    "civil legal matters": "משפט אזרחי",
    "space": "חלל",
    "infrastructure and energy": "תשתיות ואנרגיה",
    "labor": "עבודה",
    "maritime law": "משפט ימי",
    "peace process": "תהליך השלום",
    "international organizations": "ארגונים בין-לאומיים",
    "religious affairs": "ענייני דת",
    "security": "ביטחון",
    "water": "מים",
    "military service": "שירות צבאי",
    "intellectual property": "קניין רוחני",
    "terrorism": "טרור",
    "nuclear": "גרעין",
    "human rights": "זכויות אדם",
}

LANGS = {
    "english": "אנגלית", "אנגלית": "אנגלית", "hebrew": "עברית", "עברית": "עברית",
    "spanish": "ספרדית", "french": "צרפתית", "russian": "רוסית",
    "german": "גרמנית", "arabic": "ערבית", "chinese": "סינית", "greek": "יוונית",
    "ukrainian": "אוקראינית", "polish": "פולנית", "פולנית": "פולנית",
    "bulgarian": "בולגרית", "turkish": "טורקית", "hindi": "הינדית",
    "indian": "הינדית", "הודית": "הינדית", "romanian": "רומנית",
    "italian": "איטלקית", "latvian": "לטבית", "korean": "קוריאנית",
    "קוראנית": "קוריאנית", "portuguese": "פורטוגזית", "czech": "צ׳כית",
    "kazach": "קזחית", "croatian": "קרואטית", "קרואטית": "קרואטית",
    "uzbek": "אוזבקית", "flemish": "פלמית", "פלמית": "פלמית",
    "albanian": "אלבנית", "slovene": "סלובנית", "lithuanian": "ליטאית",
    "ליטאית": "ליטאית", "georgian": "גאורגית", "גרוזינית": "גאורגית",
    "serbian": "סרבית", "סרבית": "סרבית", "vietnamese": "וייטנאמית",
    "hungarian": "הונגרית", "slovak": "סלובקית", "סלובקית": "סלובקית",
    "azeri": "אזרית", "אזרית": "אזרית", "finnish": "פינית",
    "turkmen": "טורקמנית", "estonian": "אסטונית", "אסטונית": "אסטונית",
    "thai": "תאית", "תאית": "תאית", "japanese": "יפנית",
    "nepali": "נפאלית", "נפאלית": "נפאלית", "armenian": "ארמנית",
    "swahili": "סוואהילית", "סוהלית": "סוואהילית", "norwegian": "נורווגית",
    "dutch": "הולנדית", "swedish": "שוודית", "mongolian": "מונגולית",
    "kurdish": "כורדית", "belarusian": "בלארוסית", "danish": "דנית",
}
# Placeholders in Language1 that name no language.
NOT_A_LANGUAGE = {"document", "double/multiple", "לא ידוע", ""}

# Instrument form: the earliest matching word in the title wins.
FORMS = [
    ("חילופי איגרות", r"EXCHANGES? OF (?:DIPLOMATIC )?(?:NOTES?|LETTERS)|חילופי אגרות|חילופי איגרות"),
    ("מזכר הבנות", r"MEMO?R?ANDUM|M\.?O\.?U\b|UNDERSTANDI"),
    ("פרוטוקול", r"PROTOCOL|AGREED MINUTES"),
    ("אמנה", r"CONVE?N?TION|TRE?A?TY|TRETY|אמנה"),
    ("הסכם", r"AGR+E+[A-Z]*M[A-Z]*N[A-Z]*T|AGREEMENT|ACCORD|ARRANGE?MENT|ENTENTE|הסכם"),
    ("הצהרה, מכתב או הודעה", r"LETTER|NOTIFICATION|\bNOTE\b|STATEMENT|DECLARATION|COMMUNIQUE"),
    ("תיקון", r"AMEND"),
    ("תוכנית שיתוף פעולה", r"PROGRAMM?E?\b|\bPLAN\b|FRAMEWORK"),
]
OTHER_FORM = "אחר"

# Signature to entry-into-force lag, in days (upper bound inclusive).
LAG_BUCKETS = [
    ("באותו יום", 0), ("עד חודש", 30), ("חודש עד חצי שנה", 182),
    ("חצי שנה עד שנה", 365), ("שנה עד שלוש שנים", 1095), ("יותר משלוש שנים", None),
]

TOP_PARTNERS = 15
TOP_SUBJECTS = 12
HEAT_SUBJECTS = 8
TOP_LANGS = 10
RECENT_ROWS = 10
RECENT_WINDOW = 10  # years, for "who leads lately"


def _key(s):
    s = re.sub(r"\s+", " ", str(s).replace("%26", "&")).strip().lower()
    return s


def _party(raw):
    k = _key(raw)
    if not k:
        return ("לא צוין", UNCLASSIFIED)
    if k.startswith("servia"):
        return YUGO
    return PARTIES.get(k, (re.sub(r"\s+", " ", str(raw).replace("%26", "&")).strip(), UNCLASSIFIED))


def _split(cell):
    out = []
    for t in str(cell).split(","):
        t = re.sub(r"\s+", " ", t).strip()
        if t and t not in out:
            out.append(t)
    return out


def _subject(t):
    return SUBJECTS.get(t.lower(), t)


def _form(name):
    n = str(name).upper()
    best = None
    for label, pat in FORMS:
        m = re.search(pat, n)
        if m and (best is None or m.start() < best[0]):
            best = (m.start(), label)
    return best[1] if best else OTHER_FORM


def _decade_label(d):
    d = int(d)
    if d < 2000:
        return f"שנות ה-{d % 100}"
    return f"שנות ה-{d}"


def _date(ts):
    return f"{ts.day:02d}.{ts.month:02d}.{ts.year}"


def _lag_bucket(days):
    for label, hi in LAG_BUCKETS:
        if hi is None or days <= hi:
            return label
    return LAG_BUCKETS[-1][0]


def compute(frames):
    df = frames["treaties"].copy()
    for c in df.columns:
        df[c] = clean_series(df[c])
    n = len(df)

    parties = df["Parties"].map(_party)
    df["party"] = parties.map(lambda p: p[0])
    df["region"] = parties.map(lambda p: p[1])
    df["subjects"] = df["Subject_main"].map(lambda c: [_subject(t) for t in _split(c)])
    df["form"] = df["Treaty_Name"].map(_form)
    df["supplement"] = df["folder_number"].str.contains(r"\d\s*[-/]?\s*[A-Za-z]", regex=True)

    # ISO8601 accepts "1955-08-01 00:00:00", "1955-08-01" and "1955-08-01T00:00:00".
    sig = pd.to_datetime(df["Date_of_Signature"], errors="coerce", format="ISO8601")
    eif = pd.to_datetime(df["Entry_into_force"], errors="coerce", format="ISO8601")
    df["sig"] = sig
    df["eif"] = eif
    df["year"] = sig.dt.year.fillna(eif.dt.year)
    dated = df[df["year"].notna()].copy()
    dated["year"] = dated["year"].astype(int)
    dated["decade"] = (dated["year"] // 10) * 10
    n_dated = len(dated)
    n_undated = n - n_dated
    n_eif_fallback = int((sig.isna() & eif.notna()).sum())
    if dated.empty:
        raise ValueError("no row has a parseable signature or entry-into-force date")
    y_min, y_max = int(dated["year"].min()), int(dated["year"].max())

    # --- years / decades ---
    yc = dated.groupby("year").size()
    years = list(range(y_min, y_max + 1))
    year_vals = [int(yc.get(y, 0)) for y in years]
    decades = sorted(dated["decade"].unique().tolist())
    dc = dated.groupby("decade").size()
    last_dec = decades[-1]
    partial_last = y_max < last_dec + 9
    dec_labels = []
    for d in decades:
        lab = _decade_label(d)
        if d == last_dec and partial_last:
            lab += " (חלקי)"
        dec_labels.append(lab)
    dec_vals = [int(dc.get(d, 0)) for d in decades]
    peak_i = max(range(len(decades)), key=lambda i: (dec_vals[i], -i))
    peak_year_i = max(range(len(years)), key=lambda i: (year_vals[i], -i))
    peak_dec_tied = dec_vals.count(dec_vals[peak_i]) > 1
    peak_year_tied = year_vals.count(year_vals[peak_year_i]) > 1

    # --- partners ---
    pc = ranked(df["party"])
    n_partners = int(df.loc[~df["region"].eq(ORGS), "party"].nunique())
    n_orgs_rows = int(df["region"].eq(ORGS).sum())
    p_labels = [str(k) for k in pc.index[:TOP_PARTNERS]]
    p_vals = [int(v) for v in pc.iloc[:TOP_PARTNERS]]
    top_party, top_party_n = p_labels[0], p_vals[0]

    # --- regions by decade ---
    regions_present = [r for r in REGION_ORDER if (dated["region"] == r).any()]
    rd = dated.groupby(["region", "decade"]).size()
    region_series = []
    for r in regions_present:
        region_series.append({"name": r, "data": [int(rd.get((r, d), 0)) for d in decades]})
    reg_tot = ranked(df["region"])

    # --- new partners by decade (first dated instrument), orgs excluded ---
    states = dated[~dated["region"].eq(ORGS)]
    first = states.groupby("party")["year"].min()
    first_dec = (first // 10) * 10
    newc = first_dec.value_counts()
    new_vals = [int(newc.get(d, 0)) for d in decades]
    new_peak_i = max(range(len(decades)), key=lambda i: (new_vals[i], -i))
    new_peak_tied = new_vals.count(new_vals[new_peak_i]) > 1

    # --- subjects ---
    sub_rows = df[["subjects"]].explode("subjects")
    sub_rows = sub_rows[sub_rows["subjects"].notna() & sub_rows["subjects"].ne("")]
    sc = ranked(sub_rows["subjects"])
    n_subjects = len(sc)
    s_labels, s_vals = top_other(sc, TOP_SUBJECTS)
    multi_subject = int(df["subjects"].map(len).gt(1).sum())

    # subject x decade heatmap
    ds = dated[["decade", "subjects"]].explode("subjects")
    ds = ds[ds["subjects"].notna() & ds["subjects"].ne("")]
    heat_subs = [str(k) for k in ranked(ds["subjects"]).index[:HEAT_SUBJECTS]]
    hx = ds.groupby(["subjects", "decade"]).size()
    heat_data, heat_max, heat_rows = [], 0, []
    for yi, s in enumerate(heat_subs):
        vals = []
        for xi, d in enumerate(decades):
            v = int(hx.get((s, d), 0))
            heat_data.append([xi, yi, v])
            heat_max = max(heat_max, v)
            vals.append(int_he(v))
        heat_rows.append([s] + vals)

    # --- forms ---
    fc = ranked(df["form"])
    if OTHER_FORM in fc.index:
        fc = pd.concat([fc.drop(OTHER_FORM), fc[[OTHER_FORM]]])
    f_labels = [str(k) for k in fc.index]
    f_vals = [int(v) for v in fc]

    # --- lag ---
    both = df[df["sig"].notna() & df["eif"].notna()].copy()
    both["lag"] = (both["eif"] - both["sig"]).dt.days
    neg = int((both["lag"] < 0).sum())
    lagd = both[both["lag"] >= 0].copy()
    lagd["bucket"] = lagd["lag"].map(_lag_bucket)
    lb = lagd["bucket"].value_counts()
    lag_labels = [b for b, _ in LAG_BUCKETS]
    lag_vals = [int(lb.get(b, 0)) for b in lag_labels]
    n_lag = len(lagd)
    lag_median = float(lagd["lag"].median()) if n_lag else None
    same_day = lag_vals[0]

    # --- languages ---
    lang_sets = []
    for cell in df["Language1"]:
        ls = []
        for t in _split(cell):
            k = t.lower()
            if k in NOT_A_LANGUAGE:
                continue
            name = LANGS.get(k, t)
            if name not in ls:
                ls.append(name)
        lang_sets.append(ls)
    df["langs"] = lang_sets
    with_lang = df[df["langs"].map(len) > 0]
    n_with_lang = len(with_lang)
    lc = ranked(with_lang["langs"].explode())
    l_labels = [str(k) for k in lc.index[:TOP_LANGS]]
    l_vals = [int(v) for v in lc.iloc[:TOP_LANGS]]
    heb_n = int(with_lang["langs"].map(lambda ls: "עברית" in ls).sum())
    heb_share = heb_n / n_with_lang if n_with_lang else 0.0
    third_lang = int(with_lang["langs"].map(lambda ls: any(x not in ("עברית", "אנגלית") for x in ls)).sum())

    # --- documents ---
    links = df["treaty"].str.findall(r'href="([^"]+)"')
    files = [u for lst in links for u in lst]
    n_files = len(files)
    n_no_doc = int(links.map(len).eq(0).sum())
    exts = Counter(re.sub(r"[?#].*$", "", u).rsplit(".", 1)[-1].lower() for u in files if "." in u)
    tif_share = (exts.get("tif", 0) + exts.get("tiff", 0)) / n_files if n_files else 0.0
    n_supp = int(df["supplement"].sum())

    # --- recent ---
    rec = dated.copy()
    rec["sortdate"] = rec["sig"].fillna(rec["eif"])
    rec = rec.sort_values(["sortdate", "party", "folder_number"], ascending=[False, True, True], kind="mergesort")
    recent_rows = []
    for _, r in rec.head(RECENT_ROWS).iterrows():
        recent_rows.append([
            _date(r["sig"]) if pd.notna(r["sig"]) else "–",
            _date(r["eif"]) if pd.notna(r["eif"]) else "–",
            r["party"],
            join_he(r["subjects"]) if r["subjects"] else "–",
            r["form"],
        ])

    # ---------------- insights ----------------
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    # peak decade
    # Skipped when two decades share the maximum; the peak-year clause is
    # dropped when two years share theirs.
    if len(decades) >= 3 and dec_vals[peak_i] > 0 and not peak_dec_tied:
        share = dec_vals[peak_i] / n_dated
        year_clause = ""
        if not peak_year_tied:
            year_clause = (f" השנה עם הכי הרבה מסמכים היא {years[peak_year_i]} "
                           f"({int_he(year_vals[peak_year_i])}).")
        add("peak_decade",
            f"העשור העמוס ביותר היה {_decade_label(decades[peak_i])}: {int_he(dec_vals[peak_i])} מסמכים, "
            f"{pct(share)} מכל המסמכים המתוארכים.{year_clause}")

    # top partner
    if len(pc) >= 2 and pc.iloc[0] > pc.iloc[1]:
        second = [str(k) for k in pc.index[1:3]]
        add("top_partner",
            f"{top_party} היא השותפה עם הכי הרבה אמנות והסכמים: {int_he(top_party_n)} מסמכים, "
            f"לפני {join_he(second)} ({join_he([int_he(v) for v in pc.iloc[1:3]])}).")

    # new partners in a decade
    if new_vals and max(new_vals) >= 5 and not new_peak_tied:
        ni = new_peak_i
        newcomers = first_dec[first_dec == decades[ni]].index
        ex = [str(k) for k in pc[pc.index.isin(newcomers)].index[:3]]
        add("new_partners",
            f"ב{_decade_label(decades[ni])} חתמו {int_he(new_vals[ni])} מדינות על המסמך הראשון שלהן עם ישראל במאגר, "
            f"יותר מבכל עשור אחר; הבולטות שבהן לפי מספר המסמכים: {join_he(ex)}.")

    # decade trend (last full decade vs the one before it)
    full = [i for i, d in enumerate(decades) if not (d == last_dec and partial_last)]
    if len(full) >= 2:
        a, b = full[-2], full[-1]
        va, vb = dec_vals[a], dec_vals[b]
        if va > 0:
            ch = (vb - va) / va
            if ch <= -0.15:
                word = f"ירידה של {pct(-ch, 0)}"
            elif ch >= 0.15:
                word = f"עלייה של {pct(ch, 0)}"
            else:
                word = "רמה דומה"
            add("decade_trend",
                f"ב{_decade_label(decades[b])} נחתמו {int_he(vb)} מסמכים לעומת {int_he(va)} ב{_decade_label(decades[a])}: {word}.")

    # recent leader
    recent = dated[dated["year"] > y_max - RECENT_WINDOW]
    if len(recent) >= 10:
        rc = ranked(recent["party"])
        if len(rc) >= 2 and rc.iloc[0] > rc.iloc[1] and rc.iloc[0] >= 3:
            add("recent_leader",
                f"בעשר השנים האחרונות במאגר ({y_max - RECENT_WINDOW + 1} עד {y_max}) נרשמו {int_he(len(recent))} מסמכים; "
                f"השותפה המובילה בהן היא {rc.index[0]} עם {int_he(rc.iloc[0])}.")

    # top subject
    if len(sc) >= 2 and sc.iloc[0] > sc.iloc[1]:
        add("top_subject",
            f"הנושא הנפוץ ביותר הוא {sc.index[0]} ({int_he(sc.iloc[0])} מסמכים, {pct(sc.iloc[0] / n)}), "
            f"ואחריו {sc.index[1]} ({int_he(sc.iloc[1])}). {int_he(multi_subject)} מסמכים משויכים ליותר מנושא אחד.")

    # lag
    if n_lag >= 30 and lag_median is not None:
        months = lag_median / 30.44
        add("lag",
            f"בחציון עוברים {int_he(lag_median)} ימים (כ-{int_he(months)} חודשים) מהחתימה ועד הכניסה לתוקף; "
            f"{int_he(same_day)} מסמכים ({pct(same_day / n_lag)}) נכנסו לתוקף ביום החתימה.")

    # hebrew version
    if n_with_lang >= 30:
        add("hebrew",
            f"ל-{pct(heb_share)} מהמסמכים ששפת הנוסח שלהם ידועה ({int_he(n_with_lang)}) קיים נוסח עברי, "
            f"ול-{int_he(third_lang)} מסמכים יש נוסח בשפה נוספת מלבד עברית ואנגלית.")

    # supplements
    if n_supp >= 10:
        add("supplements",
            f"{int_he(n_supp)} מהמסמכים ({pct(n_supp / n)}) הם מסמכים נלווים, למשל תיקונים ופרוטוקולים, "
            f"הרשומים כמסמכי המשך בתיק של מסמך קודם (מספר התיק מסתיים באות).")

    # ---------------- KPIs ----------------
    kpis = {
        "total": {"value": n, "display": int_he(n), "tone": "brand"},
        "partners": {"value": n_partners, "display": int_he(n_partners), "tone": "brand"},
        "span": {"value": y_max - y_min, "display": f"{y_min}–{y_max}", "tone": "info"},
        "hebrew": {"value": round(heb_share * 100, 1), "display": pct(heb_share),
                   "tone": "ok" if heb_share >= 0.6 else "warn"},
    }

    # ---------------- labels ----------------
    undated_note = ""
    if n_undated:
        undated_note = f" {int_he(n_undated)} מסמכים בלי תאריך כלל אינם נכללים."
    fallback_note = ""
    if n_eif_fallback:
        fallback_note = f" ל-{int_he(n_eif_fallback)} מסמכים בלי תאריך חתימה נלקחה שנת הכניסה לתוקף."

    labels = {
        "lede": (f"המאגר מונה {int_he(n)} אמנות, הסכמים ומסמכים בילטרליים שישראל צד להם, "
                 f"מ-{y_min} ועד {y_max}, מול {int_he(n_partners)} מדינות"
                 + (f" ועוד {int_he(n_orgs_rows)} מסמכים מול ארגונים בין-לאומיים" if n_orgs_rows else "") + ". "
                 f"המסמכים עוסקים ב-{int_he(n_subjects)} נושאים, ובראשם {join_he([str(k) for k in sc.index[:3]])}. "
                 f"הדף מתרגם את שמות המדינות והנושאים לעברית; שם כל אמנה נשמר בטבלת הנתונים בשפת המקור."),
        "total_kpi": "אמנות והסכמים במאגר",
        "partners_kpi": "מדינות שותפות",
        "span_kpi": "טווח שנות החתימה",
        "hebrew_kpi": "עם נוסח עברי, מהמסמכים ששפת הנוסח ידועה",
        "decade_note": (f"מספר המסמכים לפי עשור החתימה.{fallback_note}{undated_note}"
                        + (" העשור האחרון עדיין לא הסתיים." if partial_last else "")),
        "decade_aria": (f"גרף עמודות: אמנות והסכמים לפי עשור. השיא ב{_decade_label(decades[peak_i])} עם "
                        f"{int_he(dec_vals[peak_i])} מסמכים."),
        "years_note": f"כל שנה בנפרד, {y_min} עד {y_max}. אפשר להתמקד בטווח בעזרת המחוון שמתחת לגרף.",
        "years_aria": (f"גרף עמודות: אמנות והסכמים לפי שנה, {y_min} עד {y_max}. השיא ב-{years[peak_year_i]} עם "
                       f"{int_he(year_vals[peak_year_i])} מסמכים."),
        "partners_note": (f"{TOP_PARTNERS} המדינות והגופים עם הכי הרבה מסמכים, מתוך {int_he(len(pc))} שותפים בסך הכול."),
        "partners_aria": f"גרף עמודות אופקי: השותפים עם הכי הרבה אמנות. בראש {top_party} עם {int_he(top_party_n)} מסמכים.",
        "regions_note": ("מספר המסמכים לפי אזור השותפה ועשור החתימה. אפשר להסתיר אזור בלחיצה על המקרא."),
        "regions_aria": (f"גרף עמודות מוערם: אמנות לפי אזור ועשור. האזור עם הכי הרבה מסמכים: {reg_tot.index[0]} "
                         f"({int_he(reg_tot.iloc[0])})."),
        "new_note": "מספר המדינות שחתמו על המסמך הראשון שלהן עם ישראל במאגר בכל עשור (ארגונים בין-לאומיים אינם נכללים).",
        "new_aria": (f"גרף עמודות: מדינות שותפות חדשות לפי עשור. השיא ב{_decade_label(decades[new_peak_i])} "
                     f"עם {int_he(new_vals[new_peak_i])} מדינות."),
        "subjects_note": (f"מסמך עם כמה נושאים נספר בכל אחד מהם. {TOP_SUBJECTS} הנושאים הנפוצים, והשאר תחת \"אחר\"."),
        "subjects_aria": f"גרף עמודות אופקי: אמנות לפי נושא. הנושא הנפוץ: {sc.index[0]} עם {int_he(sc.iloc[0])} מסמכים.",
        "heat_note": f"{HEAT_SUBJECTS} הנושאים הנפוצים לאורך העשורים: כמה מסמכים בכל נושא בכל עשור.",
        "heat_aria": f"מפת חום: {HEAT_SUBJECTS} הנושאים הנפוצים לפי עשור החתימה. התא הכהה ביותר: {int_he(heat_max)} מסמכים.",
        "forms_note": "סוג המסמך לפי המילה המגדירה אותו בשם האמנה (הסכם, אמנה, חילופי איגרות וכדומה).",
        "forms_aria": f"גרף עמודות: אמנות לפי סוג מסמך. הסוג הנפוץ: {f_labels[0]} עם {int_he(f_vals[0])} מסמכים.",
        "lag_note": (f"הזמן מהחתימה ועד הכניסה לתוקף, ב-{int_he(n_lag)} מסמכים שיש להם שני התאריכים"
                     + (f" ({int_he(neg)} מסמכים שתאריך הכניסה לתוקף שלהם קודם לחתימה אינם נכללים)." if neg else ".")),
        "lag_aria": (f"גרף עמודות: הזמן מחתימה לכניסה לתוקף. החציון {int_he(lag_median or 0)} ימים."),
        "langs_note": (f"השפות שבהן מצורף נוסח המסמך, ב-{int_he(n_with_lang)} מסמכים ששפת הנוסח שלהם ידועה. "
                       f"מסמך בכמה שפות נספר בכל אחת מהן."),
        "langs_aria": f"גרף עמודות אופקי: נוסחי האמנות לפי שפה. בראש {l_labels[0] if l_labels else ''} עם {int_he(l_vals[0] if l_vals else 0)} מסמכים.",
        "recent_note": f"{RECENT_ROWS} המסמכים האחרונים לפי תאריך החתימה (או הכניסה לתוקף, כשאין תאריך חתימה).",
        "docs_note": (f"{'לרוב המסמכים' if n_no_doc < n / 2 else 'לחלק מהמסמכים'} מצורפים סריקות של הנוסח החתום: {int_he(n_files)} קבצים בסך הכול, "
                      f"{pct(tif_share)} מהם תמונות סרוקות בפורמט TIF."
                      + (f" ל-{int_he(n_no_doc)} מסמכים לא צורף קובץ." if n_no_doc else "")),
    }

    temporal = f"{y_min}/{y_max}"
    orgs_tail = " ומול ארגונים בין-לאומיים" if n_orgs_rows else ""
    summary = (f"{int_he(n)} אמנות והסכמים בילטרליים שישראל צד להם, {y_min} עד {y_max}, מול {int_he(n_partners)} מדינות"
               f"{orgs_tail}, ב-{int_he(n_subjects)} נושאים. השותפה המובילה: {top_party} ({int_he(top_party_n)}).")
    seo = {
        "title": "מאגר האמנות וההסכמים של ישראל | משרד החוץ",
        "description": (f"איתור אמנה או הסכם של ישראל לפי מדינה, נושא או שנה: {int_he(n)} מסמכים מול "
                        f"{int_he(n_partners)} מדינות, {y_min} עד {y_max}."),
        "name": "מאגר האמנות וההסכמים הבילטרליים של ישראל",
        "alternate_names": ["אמנות משרד החוץ", "רשימת האמנות של ישראל", "הסכמים בילטרליים של ישראל",
                            "כתבי אמנה", "אמנות בינלאומיות"],
    }

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "registry",
            "temporal_coverage": temporal,
            "spatial_coverage": "ישראל ומדינות העולם",
            "seo": seo,
        },
        "kpis": kpis,
        "charts": {
            "decades": {"x": dec_labels, "y": dec_vals, "peak": peak_i},
            "years": {"x": [str(y) for y in years], "y": year_vals},
            "partners": {"names": p_labels, "values": p_vals},
            "regions": {"x": dec_labels, "series": region_series},
            "newp": {"x": dec_labels, "y": new_vals},
            "subjects": {"names": s_labels, "values": s_vals},
            "heat": {"x": dec_labels, "y": heat_subs, "data": heat_data, "max": heat_max},
            "forms": {"names": f_labels, "values": f_vals},
            "lag": {"names": lag_labels, "values": lag_vals},
            "langs": {"names": l_labels, "values": l_vals},
        },
        "insights": insights,
        "labels": labels,
        "tables": {
            "decades": [[dec_labels[i], int_he(dec_vals[i]), pct(dec_vals[i] / n_dated)] for i in range(len(decades))],
            "partners": [[p_labels[i], int_he(p_vals[i])] for i in range(len(p_labels))],
            "regions": [[s["name"]] + [int_he(v) for v in s["data"]] for s in region_series],
            "newp": [[dec_labels[i], int_he(new_vals[i])] for i in range(len(decades))],
            "subjects": [[s_labels[i], int_he(s_vals[i]), pct(s_vals[i] / n)] for i in range(len(s_labels))],
            "heat": heat_rows,
            "forms": [[f_labels[i], int_he(f_vals[i]), pct(f_vals[i] / n)] for i in range(len(f_labels))],
            "lag": [[lag_labels[i], int_he(lag_vals[i]), pct(lag_vals[i] / n_lag) if n_lag else "–"] for i in range(len(lag_labels))],
            "langs": [[l_labels[i], int_he(l_vals[i]), pct(l_vals[i] / n_with_lang)] for i in range(len(l_labels))],
            "recent": recent_rows,
        },
    }
