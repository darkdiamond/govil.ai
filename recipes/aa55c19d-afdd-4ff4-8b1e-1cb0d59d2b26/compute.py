"""מורי דרך — the Ministry of Tourism list of licensed tour guides.

One row per guide (~8.5k): licence number, full name, a language field and a
vehicle field (both empty in every row today), an e-mail address and up to
three phone numbers, each wrapped by upstream in an <a href> tag. The English
resource is a translated twin (same licence numbers, same contacts, names
transliterated) and is not read.

Privacy: licence numbers, e-mail addresses and phone numbers are individual
identifiers / private contacts and never reach the page. They are used only
in aggregate: licence numbers grouped into fixed numeric ranges (range edges
are round multiples of the bin width, never a specific number; the range that
holds the highest number is flagged partial and gets no fill rate), e-mail
addresses reduced to a provider (only well-known public providers are named —
any other domain is pooled as "own / organisational domain"), phones reduced
to their prefix / area code. Names are used only as aggregate counts of first
names and surnames (licensed professionals, but no individual is singled out).

There is no date column. Licence numbers are issued in sequence, so numeric
ranges are the only "age" axis; the page never translates them into years.

Growth: the list is republished whole. Bin widths are picked from the highest
licence number so the axes stay bounded; providers/prefixes/names are top-N
with an "אחר" bucket; if the language or vehicle field starts being filled
(>= FILL_MIN of rows), a language chart / vehicle insight appears.
"""
import re

import pandas as pd

TOP_NAMES = 15
TOP_PROVIDERS = 10
TOP_LANGS = 12
FILL_MIN = 0.05
FINE_WIDTHS = [250, 500, 1000, 2000, 5000]
FINE_MAX_BINS = 50
COARSE_WIDTHS = [1000, 2000, 2500, 5000, 10000]
COARSE_MAX_BINS = 12
MIN_GAP_BINS = 2

# Known public providers → Hebrew display name and kind. Anything else is
# pooled as an own / organisational domain (never named on the page).
INTL, ISP, ACAD, OWN = "דואר בינלאומי", "ספקית ישראלית", "אקדמי", "דומיין פרטי או ארגוני"
KIND_ORDER = [INTL, ISP, ACAD, OWN]
PROVIDERS = {
    "gmail.com": ("ג׳ימייל", INTL), "googlemail.com": ("ג׳ימייל", INTL),
    "hotmail.com": ("הוטמייל ואאוטלוק", INTL), "hotmail.co.il": ("הוטמייל ואאוטלוק", INTL),
    "hotmail.co.uk": ("הוטמייל ואאוטלוק", INTL), "hotmail.fr": ("הוטמייל ואאוטלוק", INTL),
    "outlook.com": ("הוטמייל ואאוטלוק", INTL), "outlook.co.il": ("הוטמייל ואאוטלוק", INTL),
    "live.com": ("הוטמייל ואאוטלוק", INTL), "msn.com": ("הוטמייל ואאוטלוק", INTL),
    "yahoo.com": ("יאהו", INTL), "yahoo.co.uk": ("יאהו", INTL), "yahoo.fr": ("יאהו", INTL),
    "yahoo.de": ("יאהו", INTL), "yahoo.es": ("יאהו", INTL), "yahoo.it": ("יאהו", INTL),
    "icloud.com": ("אפל", INTL), "me.com": ("אפל", INTL), "mac.com": ("אפל", INTL),
    "mail.ru": ("מייל.רו", INTL), "list.ru": ("מייל.רו", INTL), "bk.ru": ("מייל.רו", INTL),
    "inbox.ru": ("מייל.רו", INTL), "yandex.ru": ("יאנדקס", INTL), "yandex.com": ("יאנדקס", INTL),
    "aol.com": ("איי או אל", INTL), "gmx.de": ("ג׳י אם אקס", INTL), "gmx.net": ("ג׳י אם אקס", INTL),
    "gmx.com": ("ג׳י אם אקס", INTL), "web.de": ("ווב.דה", INTL),
    "protonmail.com": ("פרוטון", INTL), "proton.me": ("פרוטון", INTL),
    "walla.com": ("וואלה", ISP), "walla.co.il": ("וואלה", ISP),
    "netvision.net.il": ("נטוויז׳ן", ISP), "bezeqint.net": ("בזק בינלאומי", ISP),
    "zahav.net.il": ("זהב", ISP), "012.net.il": ("קווי זהב", ISP),
    "013.net": ("בזק ונטוויז׳ן", ISP), "013net.net": ("בזק ונטוויז׳ן", ISP),
    "013.net.il": ("בזק ונטוויז׳ן", ISP), "inter.net.il": ("אינטרנט זהב", ISP),
    "smile.net.il": ("סמייל", ISP), "actcom.co.il": ("אקטקום", ISP),
    "actcom.net.il": ("אקטקום", ISP), "barak.net.il": ("ברק", ISP),
    "nana.co.il": ("נענע", ISP), "nana10.co.il": ("נענע", ISP), "014.net.il": ("בזק בינלאומי", ISP),
    "bezeqint.co.il": ("בזק בינלאומי", ISP), "017.net.il": ("ספקית ישראלית אחרת", ISP),
    "orange.net.il": ("ספקית ישראלית אחרת", ISP), "internet-zahav.net": ("אינטרנט זהב", ISP),
}

AREA = {"2": "ירושלים והסביבה (02)", "3": "תל אביב וגוש דן (03)", "4": "חיפה והצפון (04)",
        "8": "הדרום והשפלה (08)", "9": "השרון (09)"}
VOIP = "מספר וירטואלי (07)"
MOBILE_PREFIXES = {"50", "51", "52", "53", "54", "55", "56", "58"}
TITLE_RE = re.compile(r'^\s*(ד["״]ר|דר[\'׳]|פרופ[\'׳]?|פרופסור)(?=\s|$)')
PAREN_RE = re.compile(r"\([^)]*\)")
TAG_RE = re.compile(r"<[^>]+>")
PHONE_RE = re.compile(r"^\+(\d{1,3})-(\d{1,3})-(\d{5,8})$")
SPLIT_RE = re.compile(r"[,;/|\n]+")


def _n(v):
    return f"{int(v):,}"


def _pct(part, whole, nd=1):
    return f"{(part / whole * 100 if whole else 0):.{nd}f}%"


LRI, PDI = "\u2066", "\u2069"


def _range_label(lo, hi):
    """Range for prose / HTML tooltips: bidi-isolated so it reads low→high in RTL."""
    return f"{LRI}{lo:,}–{hi:,}{PDI}"


def _plain_range(lo, hi):
    return f"{lo:,}–{hi:,}"


def _text(v):
    return TAG_RE.sub("", v or "").strip()


def _phone(raw):
    t = _text(raw).replace(" ", "")
    if t in ("", "+"):
        return None
    m = PHONE_RE.match(t)
    if not m:
        return ("other", "")
    cc, pre, _ = m.groups()
    if cc != "972":
        return ("foreign", cc)
    if pre in MOBILE_PREFIXES:
        return ("mobile", pre)
    if pre in AREA:
        return ("landline", pre)
    if pre.startswith("7") and len(pre) == 2:
        return ("voip", pre)
    return ("other", pre)


def _pick_width(top, widths, max_bins):
    for w in widths:
        if top // w + 1 <= max_bins:
            return w
    return widths[-1]


def _clean_name(v):
    s = PAREN_RE.sub(" ", v or "")
    s = re.sub(r"\s*-\s*", "-", s)
    title = None
    m = TITLE_RE.match(s)
    if m:
        title = "פרופ׳" if m.group(1).startswith("פרופ") else "ד״ר"
        s = s[m.end():]
    toks = [t for t in s.split() if t.strip("-'׳\"״")]
    return title, toks


def _top_counts(series, n):
    vc = series.value_counts()
    df = pd.DataFrame({"k": vc.index, "v": vc.values}).sort_values(["v", "k"], ascending=[False, True])
    return [(r.k, int(r.v)) for r in df.head(n).itertuples()]


def compute(frames):
    df = frames["guides"].copy()
    df["lic"] = pd.to_numeric(df["TGLicense"].str.replace(",", "").str.strip(), errors="coerce")
    bad_lic = int(df["lic"].isna().sum())
    total = len(df)

    # --- contacts -------------------------------------------------------------
    emails = df["EmailAddress"].map(_text).str.lower()
    df["has_email"] = emails.str.contains("@", regex=False)
    df["domain"] = emails.where(df["has_email"], "").str.rsplit("@", n=1).str[-1].str.strip()
    p1 = df["new_tour_guide_phone_1"].map(_phone)
    p2 = df["new_tour_guide_phone_2"].map(_phone)
    p3 = df["new_tourguide_telephone3"].map(_phone)
    df["n_phones"] = p1.notna().astype(int) + p2.notna().astype(int) + p3.notna().astype(int)
    df["has_phone"] = df["n_phones"] > 0
    has_e, has_p = df["has_email"], df["has_phone"]
    multi = df["n_phones"] >= 2
    contact_all = [
        ("דוא״ל וטלפון אחד", int((has_e & has_p & ~multi).sum())),
        ("דוא״ל ושני טלפונים או יותר", int((has_e & multi).sum())),
        ("טלפון בלבד", int((~has_e & has_p).sum())),
        ("דוא״ל בלבד", int((has_e & ~has_p).sum())),
        ("ללא פרטי קשר", int((~has_e & ~has_p).sum())),
    ]
    contact_cats = [kv for kv in contact_all if kv[1] > 0]
    both = int((has_e & has_p).sum())
    with_contact = int((has_e | has_p).sum())
    no_contact = total - with_contact
    multi_phone = int((df["n_phones"] >= 2).sum())
    p2_count, p3_count = int(p2.notna().sum()), int(p3.notna().sum())

    # shared e-mail addresses (two or more guides listing the same address)
    em_valid = emails[df["has_email"]]
    shared_email_rows = int(em_valid.duplicated(keep=False).sum())

    # --- providers ------------------------------------------------------------
    def prov(d):
        if not d:
            return None
        if d in PROVIDERS:
            return PROVIDERS[d]
        if d.endswith(".ac.il") or d.endswith(".edu"):
            return ("מוסד אקדמי", ACAD)
        return ("דומיין פרטי או ארגוני", OWN)

    pk = df["domain"].map(prov)
    df["prov"] = pk.map(lambda x: x[0] if x else "")
    df["kind"] = pk.map(lambda x: x[1] if x else "")
    n_email = int(df["has_email"].sum())
    prov_counts = _top_counts(df.loc[df["has_email"], "prov"], 10 ** 6)
    named = [(k, v) for k, v in prov_counts if k not in ("דומיין פרטי או ארגוני", "מוסד אקדמי")]
    pooled = [(k, v) for k, v in prov_counts if k in ("דומיין פרטי או ארגוני", "מוסד אקדמי")]
    top_prov = named[:TOP_PROVIDERS]
    rest = sum(v for _, v in named[TOP_PROVIDERS:])
    prov_rows = top_prov + ([("ספקים אחרים", rest)] if rest else []) + sorted(pooled, key=lambda kv: (-kv[1], kv[0]))
    providers = {"names": [k for k, _ in prov_rows], "values": [v for _, v in prov_rows]}
    kind_counts = {k: int((df["kind"] == k).sum()) for k in KIND_ORDER}
    gmail = dict(prov_counts).get("ג׳ימייל", 0)

    # --- phone prefixes / area codes ---------------------------------------
    pre_lab = []
    for v in p1:
        if v is None:
            pre_lab.append("")
        elif v[0] == "mobile":
            pre_lab.append(f"נייד 0{v[1]}")
        elif v[0] == "landline":
            pre_lab.append("קווי")
        elif v[0] == "voip":
            pre_lab.append(VOIP)
        elif v[0] == "foreign":
            pre_lab.append("מספר בחו״ל")
        else:
            pre_lab.append("אחר")
    pre_s = pd.Series(pre_lab, index=df.index)
    pre_counts = _top_counts(pre_s[pre_s != ""], 10 ** 6)
    n_p1 = int((pre_s != "").sum())
    mob = [(k, v) for k, v in pre_counts if k.startswith("נייד")]
    non_mob = [(k, v) for k, v in pre_counts if not k.startswith("נייד")]
    prefix_rows = mob[:8] + ([("נייד — קידומת אחרת", sum(v for _, v in mob[8:]))] if mob[8:] else []) + non_mob
    prefixes = {"names": [k for k, _ in prefix_rows], "values": [v for _, v in prefix_rows]}
    mobile_total = sum(v for _, v in mob)

    # region from any landline (phone 1–3), one per guide (first landline wins)
    reg = pd.Series("", index=df.index)
    for ser in (p3, p2, p1):
        lab = ser.map(lambda v: AREA[v[1]] if v and v[0] == "landline" else "")
        reg = lab.where(lab != "", reg)
    reg_counts = sorted(((AREA[k], int((reg == AREA[k]).sum())) for k in sorted(AREA)),
                        key=lambda kv: (-kv[1], kv[0]))
    reg_counts = [kv for kv in reg_counts if kv[1] > 0]
    n_land = sum(v for _, v in reg_counts)
    regions = {"names": [k for k, _ in reg_counts], "values": [v for _, v in reg_counts]}

    # --- licence-number ranges ---------------------------------------------
    lic = df["lic"].dropna().astype(int)
    top = int(lic.max()) if len(lic) else 0
    fw = _pick_width(top, FINE_WIDTHS, FINE_MAX_BINS)
    nb = top // fw + 1
    fine_cnt = (lic // fw).value_counts()
    fine = {"x": [], "ranges": [], "counts": [], "fill": [], "partial": []}
    for b in range(nb):
        lo, hi = b * fw, b * fw + fw - 1
        c = int(fine_cnt.get(b, 0))
        part = b == nb - 1
        fine["x"].append(f"{lo:,}")
        fine["ranges"].append(_range_label(lo, hi))
        fine["counts"].append(c)
        fine["fill"].append(None if part else round(c / fw * 100, 1))
        fine["partial"].append(part)
    # longest run of empty fine bins
    best, cur, best_start = 0, 0, None
    for b in range(nb):
        if fine["counts"][b] == 0:
            cur += 1
            if cur > best:
                best, best_start = cur, b - cur + 1
        else:
            cur = 0
    gap = None
    if best >= MIN_GAP_BINS:
        gap = (best_start * fw, (best_start + best) * fw - 1)

    cw = _pick_width(top, COARSE_WIDTHS, COARSE_MAX_BINS)
    df["cband"] = (df["lic"] // cw)
    bands = []
    for b in sorted(int(v) for v in df["cband"].dropna().unique()):
        sub = df[df["cband"] == b]
        n = len(sub)
        part = b == top // cw
        ne = int(sub["has_email"].sum())
        kinds = {k: int((sub["kind"] == k).sum()) for k in KIND_ORDER}
        titled = int(sub["TGName"].map(lambda v: _clean_name(v)[0] is not None).sum())
        bands.append({
            "b": b, "range": _range_label(b * cw, b * cw + cw - 1),
            "plain": _plain_range(b * cw, b * cw + cw - 1), "start": f"{b * cw:,}", "n": n, "partial": part,
            "fill": None if part else n / cw,
            "none": int((~sub["has_email"] & ~sub["has_phone"]).sum()), "ne": ne,
            "kinds": kinds, "titled": titled,
        })

    # --- names ----------------------------------------------------------------
    cleaned = df["TGName"].map(_clean_name)
    titles = cleaned.map(lambda x: x[0])
    toks = cleaned.map(lambda x: x[1])
    n_dr, n_prof = int((titles == "ד״ר").sum()), int((titles == "פרופ׳").sum())
    n_titled = n_dr + n_prof
    named_rows = toks[toks.map(len) >= 2]
    firsts = _top_counts(named_rows.map(lambda t: t[0]), TOP_NAMES)
    lasts = _top_counts(named_rows.map(lambda t: t[-1]), TOP_NAMES)
    n_named = len(named_rows)
    distinct_last = int(named_rows.map(lambda t: t[-1]).nunique())
    full = df["TGName"].str.split().str.join(" ")
    shared_names = int(full[full != ""].duplicated(keep=False).sum())

    # --- language / vehicle (empty today) -------------------------------------
    lang_raw = df["TGLanguage"].str.strip()
    lang_fill = float((lang_raw != "").mean()) if total else 0.0
    veh_raw = df["new_tour_guide_rechev_echkol"].str.strip()
    veh_fill = float((veh_raw != "").mean()) if total else 0.0
    langs = None
    if lang_fill >= FILL_MIN:
        ex = lang_raw[lang_raw != ""].map(lambda v: sorted({t.strip() for t in SPLIT_RE.split(v) if t.strip()}))
        flat = pd.Series([t for lst in ex for t in lst], dtype=str)
        tl = _top_counts(flat, TOP_LANGS)
        langs = {"names": [k for k, _ in tl], "values": [v for _, v in tl], "n": int(len(ex))}

    # --- insights --------------------------------------------------------------
    insights = []
    full_bands = [b for b in bands if not b["partial"] and b["n"] > 0]

    def ins_fill():
        if len(full_bands) < 3:
            return None
        old = full_bands[0]
        hi = max(full_bands, key=lambda b: (b["fill"], b["b"]))
        if hi["b"] == old["b"] or hi["fill"] < old["fill"] * 1.5:
            return None
        return (f"הרשימה דלילה בטווחי מספרי הרישיון הנמוכים: "
                f"מתוך {cw:,} המספרים בטווח {old['range']} מופיעים ברשימה רק {_n(old['n'])} "
                f"({old['fill']*100:.1f}%), לעומת {_n(hi['n'])} ({hi['fill']*100:.1f}%) בטווח {hi['range']}.")

    def ins_gap():
        if not gap:
            return None
        return (f"ברצף המספרים יש קפיצה: בטווח {_range_label(*gap)} אין ברשימה אף מספר רישיון, "
                f"ומעליו נמשכת הספירה בטווח החדש.")

    def ins_contact():
        if not total:
            return None
        txt = (f"{_n(with_contact)} מתוך {_n(total)} מורי הדרך ({_pct(with_contact, total)}) מפורסמים עם "
               f"דרך התקשרות כלשהי, ו־{_n(no_contact)} ({_pct(no_contact, total)}) ללא דוא״ל וללא טלפון.")
        if len(full_bands) >= 3:
            o, nw = full_bands[0], full_bands[-1]
            ro, rn = o["none"] / o["n"], nw["none"] / nw["n"]
            if abs(ro - rn) * 100 >= 3:
                word = "יורד" if rn < ro else "עולה"
                txt += (f" השיעור ללא פרטי קשר {word} מ־{ro*100:.1f}% בטווח {o['range']} "
                        f"ל־{rn*100:.1f}% בטווח {nw['range']}.")
        return txt

    def ins_providers():
        if n_email < 100 or not gmail:
            return None
        txt = f"ג׳ימייל היא ספקית הדוא״ל של {_n(gmail)} מורי דרך ({_pct(gmail, n_email)} מבעלי הדוא״ל)."
        ed = df[df["has_email"] & df["lic"].notna()]
        if len(ed) >= 200:
            med = float(ed["lic"].median())
            lo_h, hi_h = ed[ed["lic"] <= med], ed[ed["lic"] > med]
            so = float((lo_h["kind"] == ISP).mean()) if len(lo_h) else 0.0
            sn = float((hi_h["kind"] == ISP).mean()) if len(hi_h) else 0.0
            if so >= 0.05 and so >= sn * 1.5:
                txt += (f" כתובות בספקיות ובפורטלים ישראליים (וואלה, נטוויז׳ן, בזק בינלאומי ועוד) הן "
                        f"{so*100:.1f}% מהכתובות במחצית הוותיקה של מספרי הרישיון, לעומת "
                        f"{sn*100:.1f}% במחצית החדשה.")
        return txt

    def ins_titles():
        if n_titled < 10:
            return None
        return (f"{_n(n_titled)} מורי דרך ({_pct(n_titled, total)}) רשומים עם תואר אקדמי בשמם — "
                f"{_n(n_dr)} עם התואר ד״ר ו־{_n(n_prof)} עם התואר פרופ׳.")

    def ins_surname():
        if len(lasts) < 2 or not n_named:
            return None
        (s1, c1), (s2, c2) = lasts[0], lasts[1]
        if c1 < 20:
            return None
        return (f"שם המשפחה הנפוץ ביותר הוא {s1} — {_n(c1)} מורי דרך ({_pct(c1, n_named)}), "
                f"פי {c1 / c2:.1f} מ{s2} שבמקום השני ({_n(c2)}); ברשימה {_n(distinct_last)} "
                f"שמות משפחה שונים.")

    def ins_prefix():
        if n_p1 < 100 or not mob:
            return None
        k, v = mob[0]
        land = dict(pre_counts).get("קווי", 0)
        return (f"{_pct(mobile_total, n_p1)} מהטלפונים הראשיים הם ניידים, והקידומת הנפוצה היא "
                f"{k.replace('נייד ', '')} ({_n(v)} מורי דרך, {_pct(v, n_p1)}); רק {_n(land)} "
                f"רשמו קו קווי כטלפון הראשי.")

    def ins_region():
        if n_land < 30 or not reg_counts:
            return None
        k, v = reg_counts[0]
        if v / n_land < 0.25:
            return None
        return (f"בקרב {_n(n_land)} מורי הדרך שרשמו מספר קווי, אזור החיוג הנפוץ הוא {k} — "
                f"{_n(v)} ({_pct(v, n_land)}). זהו מדד חלקי למקום המגורים: רוב מורי הדרך רשמו נייד בלבד.")

    def ins_fields():
        if langs:
            k, v = langs["names"][0], langs["values"][0]
            return (f"שפת ההדרכה מופיעה אצל {_n(langs['n'])} מורי דרך ({_pct(langs['n'], total)}); "
                    f"השפה הנפוצה היא {k} ({_n(v)}).")
        empty_l = (1 - lang_fill) * 100
        empty_v = (1 - veh_fill) * 100
        if empty_l < 95 or empty_v < 95:
            return None
        third = ("ושדה הטלפון השלישי ריק בכל הרשומות" if p3_count == 0
                 else f"ושדה הטלפון השלישי מלא אצל {_n(p3_count)} בלבד")
        both_empty = (f"שדות שפת ההדרכה והרכב ריקים בכל הרשומות"
                      if lang_fill == 0 and veh_fill == 0 else
                      f"שדות שפת ההדרכה והרכב ריקים ב־{empty_l:.1f}% וב־{empty_v:.1f}% מהרשומות")
        return f"{both_empty}, {third} — אי אפשר ללמוד מהרשימה באילו שפות מדריך כל מורה דרך."

    for iid, fn in [("fill", ins_fill), ("gap", ins_gap), ("contact", ins_contact),
                    ("providers", ins_providers), ("titles", ins_titles), ("surname", ins_surname),
                    ("prefix", ins_prefix), ("region", ins_region), ("fields", ins_fields)]:
        t = fn()
        if t:
            insights.append({"id": iid, "text_he": t})

    # --- KPIs ------------------------------------------------------------------
    cshare = with_contact / total if total else 0
    ctone = "ok" if cshare >= 0.9 else ("warn" if cshare >= 0.75 else "danger")
    newest = full_bands[-1] if full_bands else None
    kpis = {
        "total": {"value": total, "display": _n(total), "tone": "brand"},
        "contact": {"value": round(cshare * 100, 1), "display": _pct(with_contact, total), "tone": ctone},
        "multi": {"value": multi_phone, "display": _n(multi_phone), "tone": "brand"},
        "titled": {"value": n_titled, "display": _n(n_titled), "tone": "info" if n_titled else "brand"},
    }

    # --- charts / tables ------------------------------------------------------
    band_rows = [b for b in bands if b["n"] > 0]
    contact_band = {
        "x": [b["start"] for b in band_rows],
        "ranges": [b["range"] for b in band_rows],
        "none": [round(b["none"] / b["n"] * 100, 1) for b in band_rows],
        "counts": [b["n"] for b in band_rows],
    }
    kind_band = {
        "x": [b["start"] for b in band_rows],
        "series": [{"name": k, "data": [round(b["kinds"][k] / b["ne"] * 100, 1) if b["ne"] else 0
                                        for b in band_rows]} for k in KIND_ORDER],
    }

    charts = {
        "fine": fine,
        "contact": {"names": [k for k, _ in contact_cats], "values": [v for _, v in contact_cats]},
        "contact_band": contact_band,
        "providers": providers,
        "kind_band": kind_band,
        "prefixes": prefixes,
        "regions": regions,
        "firsts": {"names": [k for k, _ in firsts], "values": [v for _, v in firsts]},
        "lasts": {"names": [k for k, _ in lasts], "values": [v for _, v in lasts]},
        "langs": langs,
    }
    tables = {
        "contact": [{"name": k, "count": _n(v), "share": _pct(v, total)} for k, v in contact_cats],
        "bands": [{"range": b["plain"] + (" (חלקי)" if b["partial"] else ""), "count": _n(b["n"]),
                   "fill": "—" if b["partial"] else f"{b['fill']*100:.1f}%",
                   "none": _pct(b["none"], b["n"]), "titled": _pct(b["titled"], b["n"])}
                  for b in band_rows],
        "kinds": [{"range": b["plain"], "vals": [_pct(b["kinds"][k], b["ne"]) for k in KIND_ORDER]}
                  for b in band_rows],
        "providers": [{"name": k, "count": _n(v), "share": _pct(v, n_email)} for k, v in prov_rows],
        "prefixes": [{"name": k, "count": _n(v), "share": _pct(v, n_p1)} for k, v in prefix_rows],
        "regions": [{"name": k, "count": _n(v), "share": _pct(v, n_land)} for k, v in reg_counts],
        "firsts": [{"name": k, "count": _n(v)} for k, v in firsts],
        "lasts": [{"name": k, "count": _n(v)} for k, v in lasts],
        "langs": ([{"name": k, "count": _n(v)} for k, v in zip(langs["names"], langs["values"])]
                  if langs else []),
        "kind_cols": KIND_ORDER,
    }

    fine_nonzero = [i for i, c in enumerate(fine["counts"]) if c > 0]
    peak_i = max(range(nb), key=lambda i: (fine["counts"][i], -i)) if nb else 0
    o = full_bands[0] if full_bands else None
    lede = (f"רשימת מורי הדרך המורשים של משרד התיירות כוללת {_n(total)} מורי דרך. לכל אחד מופיעים "
            f"מספר רישיון, שם ופרטי התקשרות; {_pct(with_contact, total)} מהם מפורסמים עם דוא״ל או טלפון. "
            f"אין ברשימה תאריכי רישוי, ולכן העמוד משתמש בטווחי מספרי הרישיון כציר — בהנחה שהמספרים ניתנים לפי סדר, מספר נמוך מעיד על רישיון ותיק יותר. "
            f"מספרי רישיון, כתובות דוא״ל ומספרי טלפון אינם מוצגים כאן, אלא רק בסיכום.")
    labels = {
        "lede": lede,
        "total_kpi": "מורי דרך ברשימה",
        "contact_kpi": "שיעור המפורסמים עם דוא״ל או טלפון",
        "multi_kpi": "מורי דרך עם יותר ממספר טלפון אחד",
        "titled_kpi": "מורי דרך עם תואר ד״ר או פרופ׳ בשמם",
        "fine_note": (f"מספר מורי הדרך בכל טווח של {fw:,} מספרי רישיון. הטווח {fine['ranges'][peak_i]} "
                      f"הוא הצפוף ביותר עם {_n(fine['counts'][peak_i])} מורי דרך"
                      + (f"; בטווח {_range_label(*gap)} אין אף מספר." if gap else ".")
                      + " גררו את הסרגל שמתחת לגרף כדי להתמקד בטווח."),
        "fine_aria": (f"גרף עמודות: מורי דרך לפי טווחי מספר רישיון של {fw:,}. "
                      f"השיא בטווח {fine['ranges'][peak_i]} עם {_n(fine['counts'][peak_i])} מורי דרך."),
        "contact_note": (f"{_n(both)} מורי דרך ({_pct(both, total)}) מפורסמים עם "
                         f"דוא״ל וגם טלפון; {_n(no_contact)} ללא אף פרט. טלפון שני רשום אצל {_n(p2_count)}, "
                         f"שלישי אצל {_n(p3_count)}."),
        "contact_aria": (f"גרף טבעת: זמינות פרטי קשר. {_n(both)} עם דוא״ל וטלפון, "
                         f"{_n(no_contact)} ללא פרטי קשר."),
        "contact_caption": "זמינות פרטי הקשר של מורי הדרך",
        "cband_note": (f"שיעור מורי הדרך ללא דוא״ל וללא טלפון בכל טווח של {cw:,} מספרי רישיון"
                       + (f" — מ־{o['none']/o['n']*100:.1f}% בטווח הוותיק ביותר ({o['range']})"
                          f" ל־{newest['none']/newest['n']*100:.1f}% בטווח {newest['range']}."
                          if o and newest and o is not newest else ".")),
        "cband_aria": f"גרף עמודות: שיעור מורי הדרך ללא פרטי קשר לפי טווחי מספר רישיון של {cw:,}.",
        "bands_caption": "מורי דרך, שיעור מילוי, היעדר פרטי קשר ותארים לפי טווח מספרי רישיון",
        "prov_note": (f"ספקית הדוא״ל של {_n(n_email)} מורי הדרך שרשמו כתובת. ג׳ימייל לבדה מחזיקה "
                      f"{_pct(gmail, n_email)}; כתובות בדומיין פרטי או ארגוני ({_n(kind_counts[OWN])}) מאוגדות "
                      f"יחד ואינן מוצגות בשמן."),
        "prov_aria": (f"גרף עמודות אופקי: ספקיות הדוא״ל של מורי הדרך. ג׳ימייל מובילה עם {_n(gmail)} כתובות."),
        "prov_caption": "ספקיות הדוא״ל של מורי הדרך",
        "kind_note": (f"תמהיל סוגי הכתובות בכל טווח מספרי רישיון (באחוזים מבעלי דוא״ל בטווח). "
                      f"בכלל הרשימה: {_pct(kind_counts[INTL], n_email)} בשירותי דואר בינלאומיים, "
                      f"{_pct(kind_counts[ISP], n_email)} בספקיות ישראליות."),
        "kind_aria": "גרף עמודות מוערמות: סוג ספקית הדוא״ל לפי טווח מספרי רישיון, באחוזים.",
        "kind_caption": "סוג ספקית הדוא״ל לפי טווח מספרי רישיון",
        "prefix_note": (f"סוג הטלפון הראשי של {_n(n_p1)} מורי דרך: {_pct(mobile_total, n_p1)} ניידים. "
                        f"הקידומת אינה מעידה בהכרח על החברה הנוכחית, בשל ניוד מספרים."),
        "prefix_aria": (f"גרף עמודות: קידומות הטלפון הראשי. {prefix_rows[0][0] if prefix_rows else ''} "
                        f"בראש עם {_n(prefix_rows[0][1]) if prefix_rows else 0}."),
        "prefix_caption": "קידומות הטלפון הראשי של מורי הדרך",
        "region_note": (f"אזור החיוג של {_n(n_land)} מורי הדרך ({_pct(n_land, total)}) שרשמו מספר קווי באחד "
                        f"משדות הטלפון. מדד חלקי בלבד — רוב מורי הדרך רשמו נייד."),
        "region_aria": (f"גרף עמודות: אזורי חיוג של מספרים קוויים. "
                        + (f"{reg_counts[0][0]} מוביל עם {_n(reg_counts[0][1])}." if reg_counts else "")),
        "region_caption": "אזורי חיוג של מורי דרך שרשמו מספר קווי",
        "names_note": (f"מבוסס על {_n(n_named)} שמות בני שתי מילים לפחות, לאחר הסרת תארים וכינויים בסוגריים; "
                       f"שם המשפחה הוא המילה האחרונה בשם. {_n(shared_names)} מורי דרך חולקים שם מלא זהה עם "
                       f"מורה דרך אחר."),
        "firsts_aria": (f"גרף עמודות אופקי: השמות הפרטיים הנפוצים בקרב מורי הדרך. "
                        + (f"{firsts[0][0]} מוביל עם {_n(firsts[0][1])}." if firsts else "")),
        "lasts_aria": (f"גרף עמודות אופקי: שמות המשפחה הנפוצים בקרב מורי הדרך. "
                       + (f"{lasts[0][0]} מוביל עם {_n(lasts[0][1])}." if lasts else "")),
        "firsts_caption": "השמות הפרטיים הנפוצים בקרב מורי הדרך",
        "lasts_caption": "שמות המשפחה הנפוצים בקרב מורי הדרך",
        "langs_note": (f"שפות ההדרכה של {_n(langs['n'])} מורי הדרך שהשדה מלא אצלם." if langs else ""),
        "langs_aria": (f"גרף עמודות: שפות ההדרכה. {langs['names'][0]} מובילה." if langs else ""),
        "langs_caption": "שפות ההדרכה של מורי הדרך",
        "excluded": (f"{_n(bad_lic)} רשומות ללא מספר רישיון תקין אינן נכללות בטווחים." if bad_lic else ""),
    }

    summary = (f"{_n(total)} מורי דרך מורשים מטעם משרד התיירות; {_pct(with_contact, total)} מפורסמים עם "
               f"דוא״ל או טלפון, {_n(n_titled)} רשומים עם תואר ד״ר או פרופ׳, ושם המשפחה הנפוץ הוא "
               f"{lasts[0][0] if lasts else '—'}.")
    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "registry",
            "suggested_tags": ["מורי דרך", "תיירות", "רישוי מקצועי", "הדרכת טיולים"],
            "related_ids": ["0d51bcd2-aa52-4c7c-8e5f-96d0d193a1fb", "a416609e-f68a-4fea-b278-657f92bfbe73",
                            "b1f49721-9af5-412a-97ae-c9493564e3ec", "0914a18b-b2c9-4e2f-bc25-0a8dfc912acf"],
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
        "flags": {"langs": bool(langs), "regions": bool(reg_counts), "excluded": bool(bad_lic)},
    }
