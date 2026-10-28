"""מבקשים לבקשות פטנט — applicants (owners) named on Israeli patent applications.

One row per (application, applicant). As in the sibling inventors and CPC
recipes there is no date column: Israeli application numbers are issued in
ascending order, so bands of 10,000 application numbers serve as the time
axis (higher band = later filings). The newest band is partial while it
fills up; it is labelled and kept out of trend rules.

Applicant identity is the English name upper-cased with punctuation and a
trailing legal-form suffix folded (LTD / INC / AG / GMBH …), so "QUALCOMM
INC." and "QUALCOMM INCORPORATED" merge; it falls back to the Hebrew name
when the English one is empty. Affiliates with different names (e.g. a
group's national subsidiaries) stay separate — the page says the ranking is
by name. Israeli applicants are shown by their Hebrew name when the register
holds one consistently.

The oldest applications carry a placeholder applicant ("APPLICANT pp", a
fixed dummy address) instead of a real name; those rows are excluded and
the exclusion is disclosed.

Applicant type (company / academia & research / government / individual) is
a heuristic on the name's form: legal-form suffixes and organisation words
mark companies, university / institute / R&D-company words mark academia,
state / ministry / secretary words mark government, and a short name of
2–5 plain words with none of those markers is read as an individual. The
page calls it an estimate.

Country: only the country token after the last comma of the English
address is used — street addresses never reach the page. Addresses are
systematic from a point in the number sequence ("address era", bands where
at least ADDR_ERA_MIN of the records carry one); country views use only
that era and say so.
"""
import re

import pandas as pd

BAND = 10_000
MAX_BANDS = 20          # bands shown individually; earlier ones collapse
PARTIAL_RATIO = 0.5     # last band below this share of the previous = partial
ADDR_ERA_MIN = 0.8
TOP_APPLICANTS = 15
TOP_ACAD = 12
TOP_COUNTRIES = 12
TOP_IN_BAND = 10        # concentration: share of a band's apps held by its top filers

PLACEHOLDER_RE = re.compile(r"^APPLICANT\s*PP$", re.I)

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
    "Hungary": "הונגריה", "Luxembourg": "לוקסמבורג", "Mexico": "מקסיקו",
    "Greece": "יוון", "Ukraine": "אוקראינה", "Croatia": "קרואטיה",
    "United Arab Emirates": "איחוד האמירויות", "Cyprus": "קפריסין",
    "Bermuda": "ברמודה", "British Virgin Islands": "איי הבתולה הבריטיים",
    "Liechtenstein": "ליכטנשטיין", "Cayman Islands": "איי קיימן",
    "Hong Kong": "הונג קונג", "Barbados": "ברבדוס", "Malta": "מלטה",
    "Netherlands Antilles": "האנטילים ההולנדיים", "Czechoslovakia": "צ׳כוסלובקיה",
    "Chile": "צ׳ילה", "Malaysia": "מלזיה", "Lithuania": "ליטא", "Latvia": "לטביה",
    "Romania": "רומניה", "Slovak Republic": "סלובקיה",
    "Republic of Slovenia": "סלובניה",
}
ISRAEL = "ישראל"
OTHER_COUNTRY = "מדינות אחרות"

# ---- applicant-type heuristic (definitions of name forms, not data) ----
SUFFIXES = {"LTD", "LIMITED", "INC", "INCORPORATED", "CORP", "CORPORATION", "CO", "LLC",
            "AG", "GMBH", "SA", "SE", "BV", "NV", "AB", "PLC", "SPA", "SAS", "SRL", "KK",
            "AS", "OY", "OYJ", "LP", "LLP", "ULC", "PTY", "PTE", "KG", "KGAA", "SARL",
            "COMPANY", "THE"}
ACAD_RE = re.compile(
    r"UNIVERSIT|COLLEGE|INSTITUTE|\bINSTITUT|TECHNION|YEDA RESEARCH|YISSUM|RAMOT|"
    r"BEN[- ]GURION|BAR[- ]ILAN|WEIZMANN|HADASIT|MEDICAL CENT|HOSPITAL|"
    r"RESEARCH (?:AND |& )?DEVELOPMENT|REGENTS|TRUSTEES|SCHOOL|ACADEM|CNRS|"
    r"CENTRE NATIONAL DE LA RECHERCHE|INSERM|FRAUNHOFER|MAX[- ]PLANCK|COMMISSARIAT|"
    r"FOUNDATION|FONDAZIONE|FONDATION|STIFTUNG|CANCER CENT|CLINIC\b|RESEARCH ORGANI[SZ]ATION|"
    r"RICERCHE|LABORATORY\b|KAROLINSKA|\bETH\b|RIKEN|\bVIB\b")
GOV_RE = re.compile(
    r"STATE OF ISRAEL|MINISTRY|MINITRY|GOVERNMENT|UNITED STATES OF AMERICA|SECRETARY|"
    r"DEPARTMENT OF|\bCOUNCIL\b|ATOMIC ENERGY|\bAUTHORITY\b")
ORG_RE = re.compile(
    r"\b(?:LTD|LIMITED|INC|INCORPORATED|CORP|CORPORATION|COMPANY|CO|LLC|L\.L\.C|LLP|L\.P|LP|"
    r"AG|A\.G|GMBH|MBH|S\.A|SA|S\.P\.A|SPA|B\.V|BV|N\.V|NV|AB|A/S|AS|ASA|OY|OYJ|PLC|KG|KGAA|"
    r"SE|SAS|SRL|S\.R\.L|KK|K\.K|PTY|PTE|ULC|UC|VZW|NYRT|RT|ZRT|SARL|BHD|ETS|E\.V)\b|"
    r"HOLDING|INDUSTR|TECHN|PHARMA|LABORATOIRE|LABS?\b|SYSTEM|ENTERPRISE|GROUP|INTERNATIONAL|"
    r"PRODUCT|SOLUTION|THERAP|BIO|MEDIC|ELECTR|PARTNERS|TRUST|ASSOCIATES|KABUSHIKI|KAISHA|"
    r"AKTIE|GESELLSCHAFT|SOCIET|ORGANI[SZ]ATION|FRANCE|EUROPE|AMERICA|ISRAEL|NATIONAL|"
    r"CHEMI|MOTOR|AUTO|DEVICE|INSTRUMENT|OPTIC|PHOTON|ROBOT|GENETIC|HEALTH|FOOD|NUTRI|"
    r"AGRI|AGRO|FARM|DESIGN|MOBILE|DATA|DIGITAL|SECUR|POWER|SOLAR|WATER|AQUA|ENERG|"
    r"DEFEN[CS]E|AIRCRAFT|ENGINE|AVIONI|HELICOPTER|LICENSING|OPERATIONS|ESTABLISHMENT|"
    r"WORKS|SOHN|SERVICE|CENT(?:ER|RE)|DIAGNOST|CONSULT|DEVELOP|NETWORK|SOFTWARE|"
    r"VENTURE|CAPITAL|INVEST|MANUFACTUR|MACHIN|FABRI|WERK|ERICSSON|PASTEUR|LUCENT|"
    r"SURGICAL|IMAGIN|COSMET|INGENI|INGÉNI|ABRASI|CITY OF|PUBLIQUE|HOPITA|"
    r"\b(?:ET|DE|DES|DU|LA|LE|LES|DER|AND|OF|THE|FOR)\b|&|[0-9]")
HE_ORG_RE = re.compile(r"בע[~\"״]?מ|חברה|חברת|אגודה|מכון|אוניברסיט|תעשיות|מערכות|טכנולוגי|"
                       r"מדינת ישראל|משרד|מרכז רפואי|בית חולים|קיבוץ|שותפות|עמותה")
HE_ACAD_RE = re.compile(r"אוניברסיט|מכון|טכניון|מחקר|בית חולים|מרכז רפואי")
HE_GOV_RE = re.compile(r"מדינת ישראל|משרד")

TYPES = [("corp", "חברות"), ("acad", "אקדמיה ומחקר"), ("gov", "ממשלות ורשויות"),
         ("ind", "אנשים פרטיים")]
TYPE_HE = dict(TYPES)
SHORT_HE = {"corp": "חברה", "acad": "אקדמיה", "gov": "ממשלה", "ind": "אדם פרטי"}
SOLE_HE = {"corp": "חברות", "acad": "אקדמיה", "gov": "ממשלות", "ind": "אנשים פרטיים"}

PROLIFIC_BUCKETS = [(1, 1, "1"), (2, 2, "2"), (3, 5, "3–5"), (6, 10, "6–10"),
                    (11, 50, "11–50"), (51, 200, "51–200"), (201, 10**9, "מעל 200")]


def _int(n):
    return f"{int(n):,}"


def _pct(x, d=1):
    return f"{x * 100:.{d}f}%"


def _en_key(s):
    u = s.upper().replace("&", " AND ")
    toks = re.sub(r"[^A-Z0-9 ]", " ", u.replace(".", "")).split()
    while len(toks) > 1 and toks[-1] in SUFFIXES:
        toks.pop()
    while len(toks) > 1 and toks[0] == "THE":
        toks.pop(0)
    return "".join(toks)


def _type_of(en, he):
    if en:
        u = en.upper()
        if ACAD_RE.search(u):
            return "acad"
        if GOV_RE.search(u):
            return "gov"
        if ORG_RE.search(u):
            return "corp"
        toks = [t for t in re.split(r"[\s,]+", u) if t]
        return "ind" if 2 <= len(toks) <= 5 else "corp"
    if HE_ACAD_RE.search(he):
        return "acad"
    if HE_GOV_RE.search(he):
        return "gov"
    if HE_ORG_RE.search(he):
        return "corp"
    return "ind" if 2 <= len(he.split()) <= 4 else "corp"


def _prepare(raw):
    df = raw.apply(lambda c: c.str.strip())
    n_raw = len(df)
    df = df.drop_duplicates()
    dups = n_raw - len(df)
    # total order so every "first row per application/applicant" pick is order-free
    df = df.sort_values(list(df.columns), kind="stable").reset_index(drop=True)
    df = df.assign(app=pd.to_numeric(df["מספר בקשה"].str.replace(",", "", regex=False),
                                      errors="coerce"))
    df = df[df["app"].notna()].copy()
    df["app"] = df["app"].astype(int)
    en = df["שם מבקש באנגלית"].str.replace(r"\s+", " ", regex=True)
    he = df["שם מבקש בעברית"].str.replace("~", "״", regex=False).str.replace(r"\s+", " ", regex=True)
    ph = en.str.match(PLACEHOLDER_RE)
    placeholder = df[ph]
    df, en, he = df[~ph].copy(), en[~ph], he[~ph]
    en_key = en.map(_en_key)
    he_key = he.str.replace(r"[^א-ת]", "", regex=True)
    df["key"] = en_key.where(en_key != "", "H:" + he_key)
    df.loc[(en_key == "") & (he_key == ""), "key"] = ""
    df["en"] = en
    df["he"] = he
    addr = df["כתובת מבקש באנגלית"]
    tok = addr.str.split(",").str[-1].str.strip()
    df["has_addr"] = addr != ""
    df["country"] = tok.map(COUNTRY_HE).where(tok != "", "")
    df.loc[(tok != "") & df["country"].isna(), "country"] = OTHER_COUNTRY
    df["country"] = df["country"].fillna("")
    df["band"] = df["app"] // BAND
    return df, dups, placeholder


def _display_names(people, il_keys):
    """key -> display name. Israeli applicants: their most common Hebrew
    spelling when ≥60% of their rows carry a Hebrew name; everyone else (and
    the fallback): the most common English spelling."""
    def top_variant(frame, col):
        c = frame.groupby(["key", col]).size().rename("n").reset_index()
        c = c.sort_values(["key", "n", col], ascending=[True, False, True], kind="stable")
        return c.drop_duplicates("key").set_index("key")[col]
    en = top_variant(people[people["en"] != ""], "en")
    hr = people[people["he"] != ""]
    he = top_variant(hr, "he")
    he_share = (hr.groupby("key").size() / people.groupby("key").size()).fillna(0)
    out = {}
    for k in people["key"].unique():
        name = en.get(k, "")
        if k in he.index and ((k in il_keys and he_share.get(k, 0) >= 0.6) or not name):
            name = he[k]
        out[k] = name
    return out


def _band_label(b):
    return f"{b * BAND // 1000} אלף"


def _band_range(b):
    return f"{_int(b * BAND)}–{_int(b * BAND + BAND - 1)}"


def compute(frames):
    df, dups, placeholder = _prepare(frames["applicants"])
    n_rows = len(df)
    people = df[df["key"] != ""].drop_duplicates(["app", "key"]).copy()
    people["type"] = [_type_of(e, h) for e, h in zip(people["en"], people["he"])]
    n_ph_apps = int(placeholder["app"].nunique())
    ph_max = int(placeholder["app"].max()) if n_ph_apps else 0
    apps = people.drop_duplicates("app")[["app", "band"]].sort_values("app")
    n_apps = len(apps)
    n_appl = int(people["key"].nunique())
    per_app = people.groupby("app").size()

    # applicant-level attributes: most common type / country (deterministic ties)
    def mode_of(col, frame):
        c = (frame.groupby(["key", col]).size().rename("n").reset_index()
             .sort_values(["key", "n", col], ascending=[True, False, True], kind="stable"))
        return c.drop_duplicates("key").set_index("key")[col]
    key_type = mode_of("type", people)
    key_country = mode_of("country", people[people["country"] != ""])
    il_keys = set(key_country[key_country == ISRAEL].index)
    names = _display_names(people, il_keys)

    # ---------------- bands (time proxy) ----------------
    all_bands = sorted(apps["band"].unique().tolist())
    shown = all_bands[-MAX_BANDS:]
    first_shown = shown[0]
    early = [b for b in all_bands if b < first_shown]
    app_band = apps["band"].where(apps["band"] >= first_shown, first_shown - 1)
    people["vband"] = people["band"].where(people["band"] >= first_shown, first_shown - 1)
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

    def idx(b):
        return band_keys.index(b)

    # ---------------- applicant types ----------------
    tcount = people["type"].value_counts()
    types = {"names": [lbl for k, lbl in TYPES], "values": [int(tcount.get(k, 0)) for k, _ in TYPES]}
    n_rec = int(len(people))
    type_rows = [{"name": lbl, "n": _int(tcount.get(k, 0)),
                  "share": f"{tcount.get(k, 0) / n_rec * 100:.1f}",
                  "appl": _int((key_type == k).sum())} for k, lbl in TYPES]
    tb = people.groupby(["vband", "type"]).size().unstack(fill_value=0)
    tb = tb.reindex(index=band_keys, columns=[k for k, _ in TYPES], fill_value=0)
    tshare = tb.div(tb.sum(axis=1).replace(0, 1), axis=0) * 100
    type_mix = {"x": labels, "series": [{"name": lbl, "data": [round(float(v), 1) for v in tshare[k]]}
                                        for k, lbl in TYPES]}
    type_mix_rows = [{"band": r, "vals": [f"{tshare.at[b, k]:.1f}" for k, _ in TYPES]}
                     for r, b in zip(ranges, band_keys)]

    # ---------------- top applicants ----------------
    per_key = people.groupby("key")["app"].nunique()
    per_key = per_key.sort_index().sort_values(ascending=False, kind="stable")

    def top_list(sub, n):
        s = sub.head(n)
        return ({"names": [names[k] for k in s.index], "values": [int(v) for v in s],
                 "il": [k in il_keys for k in s.index]},
                [{"name": names[k], "n": _int(v), "country": key_country.get(k, "—"),
                  "type": TYPE_HE[key_type[k]]} for k, v in s.items()])
    top, top_rows = top_list(per_key, TOP_APPLICANTS)
    il_per = per_key[per_key.index.isin(il_keys)]
    top_il, top_il_rows = top_list(il_per, TOP_APPLICANTS)
    top_il["il"] = []          # every bar is Israeli — no highlight needed
    ac_per = per_key[per_key.index.map(key_type) == "acad"]
    top_acad, top_acad_rows = top_list(ac_per, TOP_ACAD)

    # ---------------- concentration & newcomers ----------------
    top10_share = float(per_key.head(10).sum()) / n_apps if n_apps else 0
    n_top1pct = max(1, n_appl // 100)
    top1pct_share = float(people[people["key"].isin(per_key.head(n_top1pct).index)]["app"].nunique()) / n_apps
    p_counts = [int(((per_key >= lo) & (per_key <= hi)).sum()) for lo, hi, _ in PROLIFIC_BUCKETS]
    prolific = {"names": [b[2] for b in PROLIFIC_BUCKETS], "values": p_counts}
    p_apps = [int(people[people["key"].isin(per_key[(per_key >= lo) & (per_key <= hi)].index)]["app"].nunique())
              for lo, hi, _ in PROLIFIC_BUCKETS]
    prolific_rows = [{"name": b[2], "n": _int(v), "share": f"{v / max(n_appl, 1) * 100:.1f}",
                      "apps": _int(a)} for b, v, a in zip(PROLIFIC_BUCKETS, p_counts, p_apps)]

    first_band = people.groupby("key")["band"].min()
    people["new"] = people["band"] == people["key"].map(first_band)
    conc_y, new_y, ret_y, new_share = [], [], [], []
    for b in band_keys:
        sub = people[people["vband"] == b]
        n_b = sub["app"].nunique()
        ks = sub.groupby("key")["app"].nunique()
        ks = ks.sort_index().sort_values(ascending=False, kind="stable")
        topk = ks.head(TOP_IN_BAND).index
        conc_y.append(round(float(sub[sub["key"].isin(topk)]["app"].nunique()) / n_b * 100, 1) if n_b else 0)
        kk = sub.drop_duplicates("key")
        nn = int(kk["new"].sum()) if b != first_shown - 1 else int(len(kk))
        new_y.append(nn)
        ret_y.append(int(len(kk)) - nn)
        new_share.append(round(nn / len(kk) * 100, 1) if len(kk) else 0)
    conc = {"x": labels, "y": conc_y}
    sk = [i for i, b in enumerate(band_keys) if b >= first_shown]   # collapsed band: all "new"
    newcomers = {"x": [labels[i] for i in sk], "new": [new_y[i] for i in sk],
                 "ret": [ret_y[i] for i in sk]}
    conc_rows = [{"band": r, "conc": f"{c:.1f}"} for r, c in zip(ranges, conc_y)]
    new_rows = [{"band": ranges[i], "new": _int(new_y[i]), "ret": _int(ret_y[i]),
                 "share": f"{new_share[i]:.1f}"} for i in sk]
    bands_chart = {"x": labels, "y": band_apps, "partial": bool(partial)}

    # ---------------- co-filing ----------------
    multi = per_app[per_app >= 2]
    multi_share = len(multi) / n_apps if n_apps else 0
    mp = people[people["app"].isin(multi.index)]
    combo = (mp.groupby("app")["type"].agg(lambda s: "+".join(sorted(set(s)))))
    combo_c = combo.value_counts()
    combo_c = combo_c.sort_index().sort_values(ascending=False, kind="stable")

    def combo_label(c):
        parts = c.split("+")
        if len(parts) == 1:
            return f"{SOLE_HE[parts[0]]} בלבד"
        order = [k for k, _ in TYPES]
        return " + ".join(SHORT_HE[p] for p in sorted(parts, key=order.index))
    co = {"names": [combo_label(c) for c in combo_c.index[:8]], "values": [int(v) for v in combo_c.values[:8]]}
    co_rows = [{"name": n, "n": _int(v), "share": f"{v / max(len(multi), 1) * 100:.1f}"}
               for n, v in zip(co["names"], co["values"])]
    acad_corp = int(sum(v for c, v in combo_c.items() if "acad" in c and "corp" in c))

    # ---------------- address era & countries ----------------
    addr_share = people.groupby("band")["has_addr"].mean()
    era_bands = []
    for b in sorted(addr_share.index, reverse=True):
        if addr_share[b] >= ADDR_ERA_MIN:
            era_bands.append(b)
        else:
            break
    era_bands = sorted(era_bands)
    has_era = len(era_bands) >= 1
    era = people[people["band"].isin(era_bands)]
    era_known = era[era["country"] != ""]
    era_start = era_bands[0] * BAND if has_era else 0
    era_from_start = has_era and era_bands[0] == all_bands[0]
    countries = comp = il_types = None
    country_rows, comp_rows, il_type_rows = [], [], []
    comp_tot, comp_n, comp_series_idx = {}, 0, {}
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
        # per-application composition: Israeli only / foreign only / joint
        g = (era.assign(k=era["country"] != "", i=era["country"] == ISRAEL)
             .groupby("app").agg(n=("key", "size"), known=("k", "sum"), il=("i", "sum"),
                                 band=("vband", "first")))
        g = g[(g["known"] == g["n"]) & (g["n"] > 0)]
        g["kind"] = "mixed"
        g.loc[g["il"] == g["n"], "kind"] = "il"
        g.loc[g["il"] == 0, "kind"] = "foreign"
        kinds = [("il", "מבקשים מישראל בלבד"), ("mixed", "משותפת: ישראל וחו״ל"),
                 ("foreign", "מבקשים מחו״ל בלבד")]
        comp_keys = [b for b in band_keys if b in set(g["band"])]
        comp_labels = [labels[idx(b)] for b in comp_keys]
        comp = {"x": comp_labels, "series": []}
        for k, lbl in kinds:
            data = []
            for b in comp_keys:
                sub = g[g["band"] == b]
                data.append(round(float((sub["kind"] == k).mean()) * 100, 1) if len(sub) else 0)
            comp_series_idx[k] = len(comp["series"])
            comp["series"].append({"name": lbl, "data": data})
        comp["keys"] = comp_keys
        comp_tot = {k: int((g["kind"] == k).sum()) for k, _ in kinds}
        comp_n = int(len(g))
        comp_rows = [{"band": ranges[idx(b)], "vals": [f"{s['data'][j]:.1f}" for s in comp["series"]]}
                     for j, b in enumerate(comp_keys)]
        # applicant-type profile: Israeli vs foreign records
        prof = []
        for flag, lbl in [(True, "מבקשים מישראל"), (False, "מבקשים מחו״ל")]:
            sub = era_known[(era_known["country"] == ISRAEL) == flag]
            vc = sub["type"].value_counts()
            prof.append({"name": lbl, "n": len(sub),
                         "data": [round(float(vc.get(k, 0)) / max(len(sub), 1) * 100, 1) for k, _ in TYPES]})
        il_types = {"cats": [lbl for _, lbl in TYPES], "series": [{"name": p["name"], "data": p["data"]} for p in prof]}
        il_type_rows = [{"name": lbl, "il": f"{prof[0]['data'][i]:.1f}", "fr": f"{prof[1]['data'][i]:.1f}"}
                        for i, (_, lbl) in enumerate(TYPES)]
    era_partial = has_era and partial and era_bands[-1] == last

    # ---------------- insights ----------------
    def ins_leader():
        if len(per_key) < 2 or per_key.iloc[0] < 20:
            return None
        k0, v0 = per_key.index[0], int(per_key.iloc[0])
        k1, v1 = per_key.index[1], int(per_key.iloc[1])
        if v0 == v1:
            return None
        where = f" ({key_country[k0]})" if k0 in key_country.index else ""
        tail = (f", כמעט כמו {names[k1]} ({_int(v1)})" if v1 >= 0.9 * v0
                else f"; אחריו {names[k1]} ({_int(v1)})")
        return f"המבקש עם מספר הבקשות הגדול ביותר הוא {names[k0]}{where}, עם {_int(v0)} בקשות{tail}."

    def ins_conc():
        if n_appl < 100:
            return None
        once = p_counts[0] / n_appl
        return (f"הבקשות מרוכזות בידי מעטים: {_int(n_top1pct)} המבקשים הגדולים (האחוז העליון) "
                f"מחזיקים {_pct(top1pct_share, 0)} מהבקשות, ואילו {_pct(once, 0)} מ-{_int(n_appl)} "
                f"המבקשים הגישו בקשה אחת בלבד.")

    def ins_conc_trend():
        if len(full_shown) < 4:
            return None
        a, z = full_shown[0], full_shown[-1]
        c0, c1 = conc_y[idx(a)], conc_y[idx(z)]
        if abs(c1 - c0) < 2:
            return (f"הריכוזיות יציבה: עשרת המבקשים הגדולים בכל טווח מחזיקים כ-{c1:.1f}% מבקשותיו "
                    f"(בטווח {_band_range(z)}), לעומת {c0:.1f}% בטווח {_band_range(a)}.")
        word = "עלה" if c1 > c0 else "ירד"
        return (f"חלקם של עשרת המבקשים הגדולים בכל טווח {word} מ-{c0:.1f}% מהבקשות בטווח "
                f"{_band_range(a)} ל-{c1:.1f}% בטווח {_band_range(z)}.")

    def ins_ind():
        if len(full_shown) < 4:
            return None
        a, z = full_shown[0], full_shown[-1]
        s0, s1 = float(tshare.at[a, "ind"]), float(tshare.at[z, "ind"])
        c1 = float(tshare.at[z, "corp"])
        if abs(s1 - s0) < 2:
            return None
        word = "ירד" if s1 < s0 else "עלה"
        return (f"לפי צורת השם, שיעור האנשים הפרטיים מבין המבקשים {word} מ-{s0:.1f}% בטווח "
                f"{_band_range(a)} ל-{s1:.1f}% בטווח {_band_range(z)}; חברות הן {c1:.1f}% מהמבקשים בטווח האחרון.")

    def ins_il():
        if not comp or len(comp["keys"]) < 2:
            return None
        ck = [b for b in comp["keys"] if b in full_keys and b >= first_shown]
        if len(ck) < 4:
            return None
        il_s = comp["series"][comp_series_idx["il"]]["data"]
        mx_s = comp["series"][comp_series_idx["mixed"]]["data"]
        i0, i1 = comp["keys"].index(ck[0]), comp["keys"].index(ck[-1])
        v0, v1 = il_s[i0] + mx_s[i0], il_s[i1] + mx_s[i1]
        tot = comp_tot["il"] + comp_tot["mixed"]
        head = (f"{_pct(tot / comp_n, 0)} מהבקשות שמספרן {_int(era_start)} ומעלה הוגשו בידי מבקש "
                f"ישראלי לפחות; כל השאר — בידי מבקשים מחו״ל בלבד.")
        if abs(v1 - v0) < 2:
            return head + f" השיעור יציב: {v1:.1f}% בטווח {_band_range(ck[-1])}."
        word = "עלה" if v1 > v0 else "ירד"
        return head + (f" השיעור {word} מ-{v0:.1f}% בטווח {_band_range(ck[0])} ל-{v1:.1f}% "
                       f"בטווח {_band_range(ck[-1])}.")

    def ins_country():
        if not countries:
            return None
        tot = sum(countries["values"])
        d = dict(zip(countries["names"], countries["values"]))
        lead = countries["names"][0]
        if lead == OTHER_COUNTRY:
            return None
        second = next((n for n in countries["names"][1:] if n != OTHER_COUNTRY), None)
        if not second:
            return None
        txt = (f"{lead} היא מקור המבקשים הגדול: {_pct(d[lead] / tot, 0)} מרשומות המבקשים, לפני "
               f"{second} ({_pct(d[second] / tot, 0)})")
        if ISRAEL not in (lead, second) and ISRAEL in d:
            txt += f"; ישראל — {_pct(d[ISRAEL] / tot, 0)}"
        return txt + "."

    def ins_il_type():
        if not il_types:
            return None
        ii = [k for k, _ in TYPES].index("ind")
        a, b = il_types["series"][0]["data"][ii], il_types["series"][1]["data"][ii]
        if a < 2 * b or a < 5:
            return None
        return (f"אנשים פרטיים בולטים בקרב המבקשים הישראליים: {a:.1f}% מהם, לעומת {b:.1f}% בלבד "
                f"מהמבקשים מחו״ל (לפי צורת השם).")

    def ins_il_top():
        if len(il_per) < 3 or il_per.iloc[0] < 20:
            return None
        ks = list(il_per.index[:10])
        ac = [k for k in ks if key_type[k] == "acad"]
        k0 = ks[0]
        txt = f"המבקש הישראלי הגדול הוא {names[k0]} עם {_int(il_per.iloc[0])} בקשות"
        if len(ac) >= 2:
            txt += f"; {len(ac)} מעשרת המבקשים הישראליים הגדולים הם גופי אקדמיה ומחקר"
            other = [k for k in ac if k != k0]
            if ac[0] == k0:
                txt += f", בהם הוא עצמו וכן {names[other[0]]} ({_int(il_per[other[0]])})"
            else:
                txt += f", ובראשם {names[ac[0]]} ({_int(il_per[ac[0]])})"
        return txt + "."

    def ins_acad():
        if not len(ac_per) or tcount.get("acad", 0) / n_rec < 0.03:
            return None
        il_ac = ac_per[ac_per.index.isin(il_keys)]
        il_ac_apps = int(people[people["key"].isin(il_ac.index)]["app"].nunique())
        ac_apps = int(people[people["type"] == "acad"]["app"].nunique())
        return (f"אקדמיה ומחקר מופיעים ב-{_int(ac_apps)} בקשות ({_pct(ac_apps / n_apps, 1)}); "
                f"{_pct(il_ac_apps / max(ac_apps, 1), 0)} מהן של מוסדות ישראליים.")

    def ins_co():
        if n_apps < 1000 or not len(multi):
            return None
        txt = (f"{_pct(multi_share, 1)} מהבקשות הוגשו בידי שני מבקשים או יותר")
        if acad_corp >= 20:
            txt += f"; {_int(acad_corp)} מהן משלבות חברה עם מוסד אקדמי או מחקרי"
        return txt + "."

    def ins_new():
        if len(full_shown) < 4:
            return None
        z = full_shown[-1]
        return (f"בטווח {_band_range(z)} הופיעו {_int(new_y[idx(z)])} מבקשים לראשונה — "
                f"{new_share[idx(z)]:.1f}% מהמבקשים בטווח.")

    def ins_placeholder():
        if not n_ph_apps:
            return None
        return (f"ב-{_int(n_ph_apps)} בקשות ותיקות (מספרים עד {_int(ph_max)}) רשום מבקש כללי "
                f"(״APPLICANT pp״) ללא שם; הן אינן נכללות בניתוח.")

    rules = [("leader", ins_leader()), ("conc", ins_conc()), ("conc_trend", ins_conc_trend()),
             ("il", ins_il()), ("country", ins_country()), ("il_top", ins_il_top()),
             ("ind", ins_ind()), ("il_type", ins_il_type()), ("acad", ins_acad()),
             ("co", ins_co()), ("new", ins_new()), ("placeholder", ins_placeholder())]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    # ---------------- KPIs ----------------
    il_share = None
    if comp_n:
        il_share = (comp_tot["il"] + comp_tot["mixed"]) / comp_n
    lz = full_shown[-1] if full_shown else band_keys[-1]
    la = full_shown[0] if full_shown else band_keys[0]
    conc_last = conc_y[idx(lz)]
    conc_tone = ("warn" if conc_last - conc_y[idx(la)] >= 2 else
                 "ok" if conc_y[idx(la)] - conc_last >= 2 else "brand")
    kpis = {
        "apps": {"value": n_apps, "display": _int(n_apps), "tone": "brand"},
        "applicants": {"value": n_appl, "display": _int(n_appl), "tone": "brand"},
        "il_share": {"value": il_share, "display": "—" if il_share is None else _pct(il_share, 0),
                     "tone": "info" if il_share is not None and il_share < 0.5 else "brand"},
        "conc_last": {"value": conc_last, "display": f"{conc_last:.1f}%", "tone": conc_tone},
    }

    lo_app, hi_app = int(apps["app"].min()), int(apps["app"].max())
    lede = (f"{_int(n_rows)} רשומות מבקשים על {_int(n_apps)} בקשות פטנט ישראליות "
            f"(מספרי בקשה {_int(lo_app)}–{_int(hi_app)}), עם {_int(n_appl)} מבקשים שונים — "
            f"בעלי הזכויות בבקשה: חברות, מוסדות מחקר, ממשלות ואנשים פרטיים. "
            f"למאגר אין עמודת תאריך; מספרי הבקשה מוקצים ברצף לפי סדר ההגשה, ולכן הדף מציג "
            f"שינויים לאורך זמן לפי טווחים של {_int(BAND)} מספרי בקשה.")
    if dups:
        lede += f" {_int(dups)} שורות כפולות זהות הוסרו."
    if n_ph_apps:
        lede += f" {_int(n_ph_apps)} בקשות ותיקות שבהן רשום מבקש כללי ללא שם אינן נכללות."
    summary = (f"{_int(n_apps)} בקשות פטנט ישראליות ו-{_int(n_appl)} מבקשים: המבקשים הגדולים מחו״ל "
               f"ומישראל, חברות מול אקדמיה ואנשים פרטיים, מדינות המבקשים והריכוזיות. "
               f"עשרת המבקשים הגדולים מחזיקים {_pct(top10_share, 1)} מהבקשות.")

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "rankings",
            "suggested_tags": ["פטנטים", "מבקשי פטנט", "קניין רוחני", "חדשנות", "רשות הפטנטים"],
            "related_ids": ["029b6747-551b-47ad-9a05-ef7f7868fcd0",
                            "247efc75-31f2-4b19-bd4e-e670b1bf2783",
                            "6e207fff-abef-4f4d-aac7-61e669ba9ad5",
                            "1806c96c-9cc4-47bf-98b3-80a18f061f98"],
        },
        "kpis": kpis,
        "charts": {"bands": bands_chart, "types": types, "type_mix": type_mix, "top": top,
                   "top_il": top_il, "acad": top_acad, "prolific": prolific, "conc": conc,
                   "newcomers": newcomers, "co": co, "countries": countries, "comp": comp,
                   "il_types": il_types},
        "tables": {"bands": [{"range": r, "apps": _int(a)} for r, a in zip(ranges, band_apps)],
                   "types": type_rows, "type_mix": type_mix_rows, "top": top_rows,
                   "top_il": top_il_rows, "acad": top_acad_rows, "prolific": prolific_rows,
                   "conc": conc_rows, "new": new_rows, "co": co_rows, "countries": country_rows, "comp": comp_rows,
                   "il_types": il_type_rows},
        "flags": {"countries": bool(countries), "partial": bool(partial)},
        "insights": insights,
        "labels": {
            "lede": lede,
            "conc_last_kpi": f"מהבקשות בידי עשרת המבקשים הגדולים בטווח {_band_range(lz)}",
            "il_share_kpi": (f"מהבקשות עם מבקש ישראלי לפחות (מספרי בקשה {_int(era_start)} ומעלה)"
                             if has_era and not era_from_start else "מהבקשות עם מבקש ישראלי לפחות"),
            "bands_note": ("מספר הבקשות במאגר בכל טווח של מספרי בקשה; טווח מאוחר יותר = בקשות "
                           "שהוגשו מאוחר יותר." + (f" הטווח האחרון ({_band_range(last)}) עדיין מתמלא."
                                                    if partial else "")
                           + (f" הטווחים שלפני {_int(first_shown * BAND)} אוחדו." if early else "")),
            "types_note": (f"{_int(n_rec)} רשומות מבקשים לפי סוג המבקש. הסוג מוערך לפי צורת השם: "
                           "סיומת תאגיד או מילים כמו טכנולוגיות ותעשיות — חברה; אוניברסיטה, מכון או "
                           "חברת מחקר ופיתוח — אקדמיה ומחקר; מדינה, משרד או מזכיר — ממשלה; "
                           "שם קצר של אדם בלי סממנים כאלה — אדם פרטי."),
            "type_mix_note": ("שיעור כל סוג מבקש מבין רשומות המבקשים בכל טווח של מספרי בקשה."
                              + (" הטווח האחרון חלקי." if partial else "")),
            "top_note": (f"{TOP_APPLICANTS} המבקשים עם מספר הבקשות הגדול ביותר. זיהוי לפי שם (באיחוד "
                         "כתיב וסיומות כמו בע״מ או INC), כך שחברות בנות בשמות שונים נספרות בנפרד. "
                         "מבקשים ישראליים מודגשים בגוון כהה."),
            "top_il_note": (f"{TOP_APPLICANTS} המבקשים הרשומים בכתובת בישראל עם מספר הבקשות הגדול ביותר."),
            "acad_note": (f"{TOP_ACAD} האוניברסיטאות, מכוני המחקר וחברות היישום האקדמיות עם מספר הבקשות "
                          "הגדול ביותר. מוסדות ישראליים מודגשים בגוון כהה."),
            "prolific_note": f"{_int(n_appl)} המבקשים לפי מספר הבקשות שכל אחד מהם הגיש (סקלה לוגריתמית).",
            "conc_note": (f"שיעור הבקשות בכל טווח שהוגשו בידי {TOP_IN_BAND} המבקשים הגדולים של אותו טווח."),
            "new_note": "מבקשים שונים בכל טווח: מי שמופיע בו לראשונה במאגר לעומת מבקשים שכבר הגישו קודם.",
            "co_note": (f"{_int(len(multi))} בקשות שהוגשו בידי שני מבקשים או יותר ({_pct(multi_share, 1)}), "
                        "לפי צירוף סוגי המבקשים."),
            "countries_note": (f"רשומות מבקשים בבקשות שמספרן {_int(era_start)} ומעלה, לפי המדינה שבכתובת. "
                               f"{_int(len(era) - len(era_known))} רשומות ללא כתובת לא נכללו."
                               if has_era else ""),
            "comp_note": (f"{_int(comp_n)} בקשות שלכל מבקשיהן רשומה מדינה, לפי מוצא המבקשים."
                          + (" הטווח האחרון חלקי." if era_partial else "") if comp_n else ""),
            "il_types_note": ("סוג המבקש בקרב רשומות המבקשים מישראל לעומת אלה מחו״ל, באחוזים מכל קבוצה."),
            "bands_aria": f"עמודות: {_int(n_apps)} בקשות לפי טווח מספרי בקשה.",
            "types_aria": "עמודות אופקיות: רשומות מבקשים לפי סוג המבקש.",
            "type_mix_aria": "עמודות מוערמות באחוזים: סוגי המבקשים לפי טווח מספרי בקשה.",
            "top_aria": f"עמודות אופקיות: {TOP_APPLICANTS} המבקשים עם מספר הבקשות הגבוה ביותר.",
            "top_il_aria": f"עמודות אופקיות: {TOP_APPLICANTS} המבקשים הישראליים הגדולים.",
            "acad_aria": f"עמודות אופקיות: {TOP_ACAD} גופי האקדמיה והמחקר הגדולים.",
            "prolific_aria": "עמודות: מבקשים לפי מספר הבקשות שהגישו.",
            "conc_aria": (f"קו: שיעור הבקשות בידי עשרת המבקשים הגדולים בכל טווח; "
                          f"בטווח האחרון המלא {conc_last:.1f}%."),
            "new_aria": "עמודות מוערמות: מבקשים חדשים וחוזרים לפי טווח מספרי בקשה.",
            "co_aria": "עמודות אופקיות: בקשות משותפות לפי צירוף סוגי המבקשים.",
            "countries_aria": "עמודות אופקיות: רשומות מבקשים לפי מדינה.",
            "comp_aria": "עמודות מוערמות באחוזים: בקשות לפי מוצא המבקשים (ישראל, חו״ל, משותף) לפי טווח.",
            "il_types_aria": "עמודות מקובצות: סוגי המבקשים מישראל ומחו״ל באחוזים.",
        },
    }
