"""תכשירי הדברה מורשים לשימוש — the Ministry of Environmental Protection's
register of household / public-health pesticide products (against insects,
rodents and other domestic pests), one row per registered product.

Multi-valued cells are exploded here: `active_ingredients` is a list of
"<name> <conc>%" joined by commas (chemical names themselves contain commas,
so the split is only on a comma that follows a percent sign); `purpose` is a
comma list of target pests; `authorized` is a comma list of who may use the
product (the general public and/or licensed exterminators).

Ingredient names are normalised to a common name (lower case, "(ISO)" and
";"-trailing IUPAC synonyms dropped, a few IUPAC-only spellings mapped to
their common name) and grouped into chemical classes through a fixed map;
an unmapped ingredient falls into "אחר", so new ingredients flow through.

No wall clock: registration expiry dates are described as a distribution,
never as "expired" relative to today.
"""
import re

import pandas as pd

PRODUCT = "product"
HOLDER = "holder"
FORM = "formulation"
EXPIRY = "expiration_date"
AI = "active_ingredients"
PURPOSE = "purpose"
AUTH = "authorized"
LABEL = "label"

UNSPEC = "לא צוין"
OTHER = "אחר"
PUBLIC = "הקהל הרחב"
PROS = "מדבירים"
BOTH = "הקהל הרחב ומדבירים"
AUD_ORDER = [PUBLIC, BOTH, PROS]

TOP_PESTS = 14
TOP_AI = 15
TOP_HOLDERS = 10
TOP_CONC = 12
TOP_PRODUCTS = 10
HEAT_PESTS = 12
MIN_PEST_PRODUCTS = 5      # a pest needs this many products for the audience-share insight
LEAD_CLASS_SHARE = 0.30
TOP2_SHARE = 0.25
LABEL_GAP_SHARE = 0.10

LRI, PDI = "⁦", "⁩"
MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]

SPLIT_AI = re.compile(r"(?<=%)\s*,\s*")
CONC_RE = re.compile(r"\s*([\d.]*)\s*%\s*$")
LEGAL_RE = re.compile(r"\s*(?:בע\"מ|בע״מ|בעיימ|בעמ)(?=\s|-|$)\s*")
BRANCH_RE = re.compile(r"\s+-\s*|\s*-\s+")
HREF_RE = re.compile(r"href\s*=\s*['\"]([^'\"]*)['\"]")
MISSING_AI = {"", "(חסר)", "חסר"}

# IUPAC-only spellings that appear in the register → common name.
SYNONYMS = [
    ("n-[[(4-chlorophenyl)amino]carbonyl]-2,6-difluorobenzamide", "diflubenzuron"),
    ("n-(4-(3-chloro-5-trifluoromethyl-2-pyridinyl-oxy)", "chlorfluazuron"),
    ("α-cyano-3-phenoxybenzyl 2,2-dimethyl-3-(2-methylprop-1-enyl)", "cyphenothrin"),
    ("m-phenoxybenzyl 3-(2,2-dichlorovinyl)", "permethrin"),
    ("2-(2-butoxyethoxy)ethyl 6-propylpiperonyl ether", "piperonyl butoxide"),
    ("1r-trans-phenothrin", "phenothrin"),
    ("d-phenothrin", "phenothrin"),
    ("s-bioallethrin", "bioallethrin"),
    ("beta-cyfluthrin", "cyfluthrin"),
    ("perfume citronella", "citronella oil"),
    ("dipentene", "d-limonene"),
]

CLS_PYR = "פירתרואידים ופירתרינים"
CLS_SYN = "מגבירי פעולה (סינרגיסטים)"
CLS_FIP = "פניל-פירזולים (פיפרוניל)"
CLS_NEO = "ניאוניקוטינואידים"
CLS_ANT = "נוגדי קרישה (מכרסמים)"
CLS_IGR = "מווסתי גדילה של חרקים"
CLS_BIO = "ביולוגיים"
CLS_FUM = "גזי חיטוי (פוספידים)"
CLS_OIL = "שמנים, תמציות ובשמים"
CLASS_MAP = {
    "cypermethrin": CLS_PYR, "prallethrin": CLS_PYR, "bifenthrin": CLS_PYR,
    "tetramethrin": CLS_PYR, "deltamethrin": CLS_PYR, "lambda-cyhalothrin": CLS_PYR,
    "permethrin": CLS_PYR, "cyfluthrin": CLS_PYR, "bioallethrin": CLS_PYR,
    "esbiothrin": CLS_PYR, "imiprothrin": CLS_PYR, "transfluthrin": CLS_PYR,
    "phenothrin": CLS_PYR, "cyphenothrin": CLS_PYR, "pyrethrum": CLS_PYR,
    "pyrethrins": CLS_PYR, "allethrin": CLS_PYR, "d-allethrin": CLS_PYR,
    "metofluthrin": CLS_PYR, "alpha-cypermethrin": CLS_PYR, "etofenprox": CLS_PYR,
    "piperonyl butoxide": CLS_SYN, "mgk 264": CLS_SYN,
    "fipronil": CLS_FIP,
    "imidacloprid": CLS_NEO, "dinotefuran": CLS_NEO, "thiamethoxam": CLS_NEO,
    "acetamiprid": CLS_NEO, "clothianidin": CLS_NEO,
    "brodifacoum": CLS_ANT, "bromadiolone": CLS_ANT, "difenacoum": CLS_ANT,
    "difethialone": CLS_ANT, "flocoumafen": CLS_ANT,
    "pyriproxyfen": CLS_IGR, "novaluron": CLS_IGR, "diflubenzuron": CLS_IGR,
    "chlorfluazuron": CLS_IGR, "methoprene": CLS_IGR, "s-methoprene": CLS_IGR,
    "hexaflumuron": CLS_IGR, "triflumuron": CLS_IGR, "lufenuron": CLS_IGR,
    "bacillus thuringiensis var israelensis": CLS_BIO, "bacillus sphaericus": CLS_BIO,
    "beauveria bassiana": CLS_BIO,
    "aluminium phosphide": CLS_FUM, "magnesium phosphide": CLS_FUM,
    "d-limonene": CLS_OIL, "citronella oil": CLS_OIL, "perfume": CLS_OIL,
    "white mineral oil (petroleum)": CLS_OIL,
}

FORM_FAMILIES = [
    ("פיתיונות", ("פיתיון", "פתיון", "בלוק")),
    ("אירוסולים", ("אירוסול",)),
    ("תרכיזים לדילול", ("תרכיז",)),
    ("אידוי, עשן וסלילים", ("אידוי", "סליל", "עשן", "אדים")),
    ("ג'לים", ("ג'ל",)),
    ("אבקות וגרגרים", ("אבקה", "גרגר")),
    ("נוזלים, תמיסות ותרסיסים", ("נוזל", "תמיסה", "תרסיס", "תחליב", "אמולסיה", "תרחיף", "שמן")),
]


def n(v):
    return f"{int(v):,}"


def prods(k, pre=""):
    """'תכשיר אחד' / '12 תכשירים', with an optional ב/ל prefix (hyphen before digits)."""
    if int(k) == 1:
        return f"{pre}תכשיר אחד"
    return f"{pre}{'-' if pre else ''}{n(k)} תכשירים"


def pct(v, digits=1):
    return f"{LRI}{v * 100:.{digits}f}%{PDI}"


def pct_bare(v, digits=1):
    return f"{v * 100:.{digits}f}%"


def conc_s(v):
    s = f"{v:.3f}".rstrip("0").rstrip(".")
    return f"{s}%"


def ranked(counts):
    """Descending by value, ties by label — a total, shuffle-proof order."""
    return counts.sort_index().sort_values(ascending=False, kind="stable")


def aud_key(raw):
    toks = sorted({t.strip() for t in raw.split(",") if t.strip()})
    if not toks:
        return UNSPEC
    if toks == [PROS]:
        return PROS
    if toks == [PUBLIC]:
        return PUBLIC
    if set(toks) == {PUBLIC, PROS}:
        return BOTH
    return " ו".join(toks)


def aud_order(keys):
    known = [a for a in AUD_ORDER if a in keys]
    rest = sorted(k for k in keys if k not in AUD_ORDER and k != UNSPEC)
    return known + rest + ([UNSPEC] if UNSPEC in keys else [])


def ai_name(part):
    name = CONC_RE.sub("", part).strip()
    name = name.split(";")[0]
    name = re.sub(r"\(iso\)", "", name, flags=re.I)
    name = re.sub(r"\s+", " ", name).strip().lower().rstrip("%").strip()
    name = re.sub(r"\s+cis/trans.*$", "", name)
    name = re.sub(r"^([a-z0-9]+)-\s+", r"\1-", name)
    for prefix, common in SYNONYMS:
        if name.startswith(prefix):
            return common
    return name


def parse_ai(cell):
    out = []
    for part in SPLIT_AI.split(cell.strip()):
        part = part.strip()
        if not part:
            continue
        m = CONC_RE.search(part)
        c = None
        if m and m.group(1):
            try:
                c = float(m.group(1))
            except ValueError:
                c = None
        name = ai_name(part)
        out.append((UNSPEC if name in MISSING_AI else name, c))
    return out


def form_family(raw):
    s = raw.strip()
    if not s:
        return UNSPEC
    for fam, keys in FORM_FAMILIES:
        if any(k in s for k in keys):
            return fam
    return OTHER


def holder_parts(raw):
    s = raw.strip()
    if not s:
        return UNSPEC, UNSPEC
    base = LEGAL_RE.sub(" ", s).strip()
    base = BRANCH_RE.split(base)[0].strip() or base
    key = re.sub(r"[\s.\"״'׳-]", "", base)
    return key, base


def stacked(df, col, order_names, auds):
    """{names, series:[{name,data}]} counting distinct products per (col, audience)."""
    ct = df.groupby([col, "aud"]).size()
    series = []
    for a in auds:
        series.append({"name": a, "data": [int(ct.get((nm, a), 0)) for nm in order_names]})
    return {"names": list(order_names), "series": series}


def top_names(counts, k):
    counts = ranked(counts)
    names = list(counts.index[:k])
    return names, len(counts) > k


def d_he(ts):
    return f"{MONTHS_HE[ts.month - 1]} {ts.year}"


# ── insights ──────────────────────────────────────────────────────────────

def insight_audience(aud_counts, total):
    pros = int(aud_counts.get(PROS, 0))
    pub = int(aud_counts.get(PUBLIC, 0)) + int(aud_counts.get(BOTH, 0))
    if total == 0 or (pros == 0 and pub == 0):
        return None
    both = int(aud_counts.get(BOTH, 0))
    tail = ("" if not both else ", ואחד מהם מותר גם למדבירים" if both == 1
            else f", מתוכם {n(both)} מותרים גם למדבירים")
    if abs(pros - pub) / total < 0.05:
        lead = "החלוקה כמעט שווה"
    elif pros > pub:
        lead = "רוב התכשירים שמורים לאנשי מקצוע"
    else:
        lead = "רוב התכשירים זמינים לציבור"
    return (f"{lead}: {n(pros)} תכשירים ({pct(pros / total)}) מורשים למדבירים בלבד, "
            f"ו-{n(pub)} ({pct(pub / total)}) מותרים לשימוש הקהל הרחב{tail}.")


def insight_conc(conc_rows):
    if len(conc_rows) < 3:
        return None
    higher = [r for r in conc_rows if r["pro"] > r["pub"]]
    if len(higher) / len(conc_rows) < 0.6:
        return None
    top = conc_rows[0]
    return (f"אותו חומר פעיל, ריכוז אחר: מבין {n(len(conc_rows))} חומרים פעילים שמופיעים גם בתכשירים "
            f"לציבור וגם בתכשירים למדבירים בלבד, ב-{n(len(higher))} הריכוז המרבי בתכשירי המדבירים גבוה יותר. "
            f"הפער הגדול ביותר — {LRI}{top['name']}{PDI}: עד {LRI}{conc_s(top['pub'])}{PDI} לציבור "
            f"לעומת עד {LRI}{conc_s(top['pro'])}{PDI} למדבירים (פי {top['ratio_s']}).")


def insight_pest_audience(pest_aud, pest_tot):
    elig = [p for p, t in pest_tot.items() if t >= MIN_PEST_PRODUCTS and p != UNSPEC]
    if len(elig) < 3:
        return None
    share = {p: pest_aud.get((p, PROS), 0) / pest_tot[p] for p in elig}
    order = sorted(elig, key=lambda p: (-share[p], -pest_tot[p], p))
    hi, lo = order[0], order[-1]
    if share[hi] - share[lo] < 0.3:
        return None
    lo_n = pest_aud.get((lo, PROS), 0)
    lo_txt = (f"ואף לא אחד מ-{n(pest_tot[lo])} התכשירים נגד {lo}" if lo_n == 0 else
              f"לעומת {pct(share[lo], 0)} ({n(lo_n)} מתוך {n(pest_tot[lo])}) בתכשירים נגד {lo}")
    return (f"הקהל המורשה תלוי במזיק: מבין התכשירים נגד {hi}, {pct(share[hi], 0)} "
            f"({n(pest_aud.get((hi, PROS), 0))} מתוך {n(pest_tot[hi])}) מיועדים למדבירים בלבד, "
            f"{lo_txt} (מזיקים עם {n(MIN_PEST_PRODUCTS)} תכשירים לפחות).")


def insight_class(cls_counts, total):
    real = cls_counts.drop(labels=[CLS_SYN, UNSPEC], errors="ignore")
    if real.empty or total == 0:
        return None
    real = ranked(real)
    lead, cnt = real.index[0], int(real.iloc[0])
    if cnt / total < LEAD_CLASS_SHARE:
        return None
    second = ""
    if len(real) > 1:
        second = f"; אחריהם {real.index[1]} עם {n(real.iloc[1])} תכשירים"
    return (f"{lead} הם המשפחה הכימית הנפוצה: {n(cnt)} תכשירים ({pct(cnt / total)}) "
            f"מכילים לפחות חומר פעיל אחד מהמשפחה{second}.")


def insight_mix(n_ai_per, syn_products, total, top_syn):
    multi = int((n_ai_per >= 2).sum())
    if total == 0 or multi / total < 0.15:
        return None
    syn_txt = ""
    if syn_products and top_syn:
        syn_txt = (f"; {prods(syn_products, 'ב')} משולב מגביר פעולה "
                   f"(הנפוץ — {LRI}{top_syn}{PDI}) שאינו קוטל בעצמו אך מעצים את החומר הקוטל")
    return (f"{n(multi)} תכשירים ({pct(multi / total)}) הם תערובות של שני חומרים פעילים או יותר"
            f"{syn_txt}.")


def insight_holders(h_counts, h_display, total):
    named = ranked(h_counts.drop(labels=[UNSPEC], errors="ignore"))
    if len(named) < 3 or total == 0:
        return None
    k1, k2 = named.index[0], named.index[1]
    top2 = int(named.iloc[0]) + int(named.iloc[1])
    if top2 / total < TOP2_SHARE:
        return None
    unspec = int(h_counts.get(UNSPEC, 0))
    tail = f" עבור {prods(unspec)} לא צוין בעל הרישום." if unspec else ""
    return (f"שוק מרוכז: {h_display[k1]} ({n(named.iloc[0])} תכשירים) ו{h_display[k2]} "
            f"({n(named.iloc[1])}) מחזיקות יחד {pct(top2 / total)} מהרישומים, "
            f"מתוך {n(len(named))} בעלי רישום.{tail}")


def insight_label(no_label, total):
    if total == 0 or no_label / total < LABEL_GAP_SHARE:
        return None
    return (f"{prods(no_label, 'ל')} ({pct(no_label / total)}) אין במאגר קישור לתווית התכשיר — "
            f"ואת הוראות התווית חובה לקרוא לפני השימוש.")


def insight_expiry(exp):
    if len(exp) < 10:
        return None
    s = exp.sort_values(kind="stable").reset_index(drop=True)
    med = s.iloc[(len(s) - 1) // 2]
    yrs = s.dt.year.value_counts()
    peak = ranked(yrs).index[0]
    return (f"תוקף הרישומים פרוס עד {s.iloc[-1].year}: חציון מועד הפקיעה הוא {d_he(med)}, "
            f"והשנה שבה פוקעים הכי הרבה רישומים היא {peak} ({n(yrs[peak])} תכשירים).")


# ── compute ───────────────────────────────────────────────────────────────

def compute(frames):
    df = frames["main"].copy()
    for c in [PRODUCT, HOLDER, FORM, EXPIRY, AI, PURPOSE, AUTH, LABEL]:
        df[c] = df[c].astype(str).str.strip()
    df = df[df[PRODUCT] != ""].copy()
    df = df.sort_values([PRODUCT, HOLDER, AI, PURPOSE, AUTH, FORM, EXPIRY], kind="stable")
    df = df.reset_index(drop=True)
    df["pid"] = range(len(df))
    total = len(df)

    df["aud"] = df[AUTH].map(aud_key)
    auds = aud_order(set(df["aud"]))
    aud_counts = df["aud"].value_counts()

    # pests
    pest_rows = []
    for pid, aud, cell in zip(df["pid"], df["aud"], df[PURPOSE]):
        toks = sorted({t.strip() for t in cell.split(",") if t.strip()})
        for t in toks:
            pest_rows.append((pid, aud, t))
    pests = pd.DataFrame(pest_rows, columns=["pid", "aud", "pest"])
    no_pest = total - pests["pid"].nunique()
    pest_tot = pests["pest"].value_counts()
    pest_names, pest_more = top_names(pest_tot, TOP_PESTS)
    pest_chart = stacked(pests, "pest", pest_names, auds)
    pest_aud = pests.groupby(["pest", "aud"]).size().to_dict()
    n_pests_per = pests.groupby("pid").size()

    # active ingredients
    ai_rows = []
    for pid, aud, cell in zip(df["pid"], df["aud"], df[AI]):
        for name, c in parse_ai(cell):
            ai_rows.append((pid, aud, name, c))
    ais = pd.DataFrame(ai_rows, columns=["pid", "aud", "ai", "conc"])
    ais_named = ais[ais["ai"] != UNSPEC]
    n_ai_missing = int(df["pid"].isin(ais.loc[ais["ai"] == UNSPEC, "pid"]).sum())
    ai_prod = ais_named.drop_duplicates(["pid", "ai"])
    ai_tot = ai_prod["ai"].value_counts()
    ai_names, _ = top_names(ai_tot, TOP_AI)
    ai_chart = stacked(ai_prod, "ai", ai_names, auds)
    ai_chart["cls"] = [CLASS_MAP.get(a, OTHER) for a in ai_names]
    n_ai_per = ais.groupby("pid").size().reindex(df["pid"], fill_value=0)

    # chemical classes (distinct products per class)
    ai_prod = ai_prod.assign(cls=ai_prod["ai"].map(lambda a: CLASS_MAP.get(a, OTHER)))
    cls_prod = ai_prod.drop_duplicates(["pid", "cls"])
    cls_tot = cls_prod["cls"].value_counts()
    cls_names = [c for c in ranked(cls_tot).index if c != OTHER] + ([OTHER] if OTHER in cls_tot else [])
    cls_chart = stacked(cls_prod, "cls", cls_names, auds)
    syn_products = int(cls_tot.get(CLS_SYN, 0))
    syn_ai = ranked(ai_tot[[a for a in ai_tot.index if CLASS_MAP.get(a) == CLS_SYN]]) \
        if syn_products else pd.Series(dtype=int)
    top_syn = syn_ai.index[0] if len(syn_ai) else None

    # pest × class heatmap
    heat_pests = pest_names[:HEAT_PESTS]
    pc = pests[pests["pest"].isin(heat_pests)].merge(cls_prod[["pid", "cls"]], on="pid")
    pc_ct = pc.groupby(["pest", "cls"]).size()
    cells = []
    for yi, p in enumerate(heat_pests):
        for xi, c in enumerate(cls_names):
            v = int(pc_ct.get((p, c), 0))
            if v:
                cells.append([xi, yi, v])
    heat_max = max([c[2] for c in cells], default=1)
    heat = {"x": cls_names, "y": heat_pests, "cells": cells, "max": heat_max}
    heat_table = [{"name": p, "cells": [n(pc_ct.get((p, c), 0)) if pc_ct.get((p, c), 0) else "–"
                                         for c in cls_names]} for p in heat_pests]

    # concentration: public-accessible vs exterminator-only
    cn = ais_named.dropna(subset=["conc"])
    cn = cn[cn["conc"] > 0]
    pub_mask = cn["aud"].isin([PUBLIC, BOTH])
    pub_max = cn[pub_mask].groupby("ai")["conc"].max()
    pro_max = cn[cn["aud"] == PROS].groupby("ai")["conc"].max()
    common = sorted(set(pub_max.index) & set(pro_max.index))
    conc_rows = []
    for a in common:
        pu, pr = float(pub_max[a]), float(pro_max[a])
        conc_rows.append({"name": a, "pub": pu, "pro": pr, "ratio": pr / pu})
    conc_rows.sort(key=lambda r: (-r["ratio"], r["name"]))
    for r in conc_rows:
        r["ratio_s"] = f"{r['ratio']:,.0f}" if r["ratio"] >= 10 else f"{r['ratio']:,.1f}"
    conc_top = conc_rows[:TOP_CONC]
    conc_chart = {"names": [r["name"] for r in conc_top],
                  "pub": [r["pub"] for r in conc_top],
                  "pro": [r["pro"] for r in conc_top],
                  "ratio": [r["ratio_s"] for r in conc_top]}

    # formulation families
    df["fam"] = df[FORM].map(form_family)
    fam_tot = df["fam"].value_counts()
    fam_names = [f for f in ranked(fam_tot).index if f not in (OTHER, UNSPEC)]
    fam_names += [f for f in (OTHER, UNSPEC) if f in fam_tot]
    form_chart = stacked(df, "fam", fam_names, auds)
    fam_examples = {}
    for fam in fam_names:
        raws = ranked(df.loc[(df["fam"] == fam) & (df[FORM] != ""), FORM].value_counts())
        fam_examples[fam] = ", ".join(list(raws.index[:3])) if len(raws) else "–"

    # mixtures
    df["mix"] = n_ai_per.values
    df["mix_b"] = df["mix"].map(lambda k: "חומר פעיל אחד" if k == 1 else (
        f"{int(k)} חומרים פעילים" if 1 < k < 5 else ("5 חומרים פעילים ומעלה" if k >= 5 else UNSPEC)))
    mix_order = sorted(df["mix_b"].unique(), key=lambda s: (s == UNSPEC, int(df.loc[df["mix_b"] == s, "mix"].min())))
    mix_chart = stacked(df, "mix_b", mix_order, auds)

    # holders
    hp = df[HOLDER].map(holder_parts)
    df["hkey"] = [k for k, _ in hp]
    df["hbase"] = [b for _, b in hp]
    h_counts = df["hkey"].value_counts()
    h_display = {}
    for key, g in df.groupby("hkey"):
        v = ranked(g["hbase"].value_counts())
        h_display[key] = v.index[0]
    named_h = ranked(h_counts.drop(labels=[UNSPEC], errors="ignore"))
    h_keys = list(named_h.index[:TOP_HOLDERS])
    df["hbucket"] = df["hkey"].where(df["hkey"].isin(h_keys) | (df["hkey"] == UNSPEC), OTHER)
    hb_order = h_keys + [k for k in (OTHER, UNSPEC) if (df["hbucket"] == k).any()]
    holder_chart = stacked(df, "hbucket", hb_order, auds)
    holder_chart["names"] = [h_display.get(k, k) if k not in (OTHER, UNSPEC) else k for k in hb_order]
    n_holders = len(named_h)
    variants = int(df.loc[df["hkey"] != UNSPEC].groupby("hkey")[HOLDER].nunique().gt(1).sum())

    # expiry
    exp = pd.to_datetime(df[EXPIRY], format="%d/%m/%Y", errors="coerce")
    exp_ok = exp.dropna()
    if len(exp_ok):
        y0, y1 = int(exp_ok.dt.year.min()), int(exp_ok.dt.year.max())
        yc = exp_ok.dt.year.value_counts()
        exp_years = list(range(y0, y1 + 1))
        exp_chart = {"x": [str(y) for y in exp_years], "y": [int(yc.get(y, 0)) for y in exp_years]}
    else:
        y0 = y1 = None
        exp_chart = {"x": [], "y": []}
    exp_bad = total - len(exp_ok)

    # labels
    hrefs = df[LABEL].map(lambda s: (HREF_RE.search(s).group(1).strip() if HREF_RE.search(s) else ""))
    has_label = hrefs.str.len() > 0
    n_label = int(has_label.sum())
    no_label = total - n_label

    # broadest-spectrum products
    df["npest"] = n_pests_per.reindex(df["pid"], fill_value=0).values
    bp = df.sort_values(["npest", PRODUCT, "pid"], ascending=[False, True, True], kind="stable")
    bp = bp[bp["npest"] > 0].head(TOP_PRODUCTS)
    pest_lists = pests.groupby("pid")["pest"].apply(lambda s: ", ".join(sorted(s)))
    top_products = [{"name": r[PRODUCT], "holder": h_display.get(r["hkey"], UNSPEC) if r["hkey"] != UNSPEC else UNSPEC,
                     "aud": r["aud"], "npest": n(r["npest"]), "pests": pest_lists.get(r["pid"], "")}
                    for _, r in bp.iterrows()]

    # ── KPIs
    pro_only = int(aud_counts.get(PROS, 0))
    pub_ok = int(aud_counts.get(PUBLIC, 0)) + int(aud_counts.get(BOTH, 0))
    label_share = n_label / total if total else 0
    kpis = {
        "products": {"value": total, "display": n(total), "tone": "brand"},
        "public": {"value": pub_ok, "display": n(pub_ok), "tone": "info"},
        "pros": {"value": pro_only, "display": n(pro_only), "tone": "brand"},
        "ai": {"value": int(ai_tot.size), "display": n(ai_tot.size), "tone": "brand"},
        "holders": {"value": n_holders, "display": n(n_holders), "tone": "brand"},
        "label": {"value": round(label_share, 4), "display": pct_bare(label_share, 0),
                  "tone": "ok" if label_share >= 0.9 else ("warn" if label_share >= 0.7 else "danger")},
    }

    insights = []
    for iid, txt in [
        ("audience", insight_audience(aud_counts, total)),
        ("conc", insight_conc(conc_rows)),
        ("pest_audience", insight_pest_audience(pest_aud, pest_tot)),
        ("class", insight_class(cls_tot, total)),
        ("mix", insight_mix(n_ai_per, syn_products, total, top_syn)),
        ("holders", insight_holders(h_counts, h_display, total)),
        ("label", insight_label(no_label, total)),
        ("expiry", insight_expiry(exp_ok)),
    ]:
        if txt:
            insights.append({"id": iid, "text_he": txt})

    # ── labels
    aud_parts = ", ".join(f"{a}: {n(aud_counts.get(a, 0))}" for a in auds)
    lead_pest = pest_names[0] if pest_names else None
    lead_cls = ranked(cls_tot.drop(labels=[CLS_SYN], errors="ignore")).index[0] if len(cls_tot) else None
    labels = {
        "lede": (f"המרשם של המשרד להגנת הסביבה מונה {n(total)} תכשירי הדברה לשימוש ביתי ותברואתי — "
                 f"נגד חרקים, מכרסמים ומזיקים אחרים — של {n(n_holders)} בעלי רישום, "
                 f"המבוססים על {n(ai_tot.size)} חומרים פעילים. {n(pub_ok)} מהם מותרים לשימוש הקהל הרחב "
                 f"ו-{n(pro_only)} למדבירים מורשים בלבד. העמוד מפרק את המרשם לפי מזיק, משפחה כימית, "
                 f"ריכוז, תוארית ובעל רישום."),
        "products_kpi": "תכשירים רשומים",
        "public_kpi": "מותרים לקהל הרחב",
        "pros_kpi": "למדבירים בלבד",
        "ai_kpi": "חומרים פעילים",
        "holders_kpi": "בעלי רישום",
        "label_kpi": "עם קישור לתווית",
        "audience_note": f"חלוקת התכשירים לפי מי שרשאי להשתמש בהם — {aud_parts}.",
        "audience_aria": f"תרשים טבעת: {aud_parts}",
        "audience_caption": "תכשירים לפי קהל מורשה",
        "pests_note": (f"מספר התכשירים שנרשמו נגד כל מזיק, לפי קהל מורשה. תכשיר אחד יכול להיות רשום נגד כמה מזיקים "
                       f"(בממוצע {sum(n_pests_per) / max(len(n_pests_per), 1):.1f}), ולכן הסכום עולה על מספר התכשירים."
                       + (f" המזיק הנפוץ ביותר: {lead_pest} ({n(pest_tot[lead_pest])} תכשירים)." if lead_pest else "")
                       + (f" מוצגים {n(len(pest_names))} המזיקים הנפוצים מתוך {n(len(pest_tot))}." if pest_more else "")
                       + (f" עבור {prods(no_pest)} לא צוין ייעוד." if no_pest else "")),
        "pests_aria": f"תרשים עמודות מוערמות של מספר התכשירים לכל מזיק לפי קהל מורשה, {n(len(pest_names))} מזיקים",
        "pests_caption": "תכשירים לפי מזיק וקהל מורשה",
        "class_note": (f"החומרים הפעילים קובצו למשפחות כימיות; תכשיר נספר בכל משפחה שיש בו חומר ממנה."
                       + (f" המשפחה הנפוצה: {lead_cls} ({n(cls_tot[lead_cls])} תכשירים)." if lead_cls else "")
                       + " מגבירי פעולה אינם קוטלים בעצמם אלא מעכבים את פירוק החומר הקוטל בגוף המזיק."
                       + (f" עבור {prods(n_ai_missing)} שם החומר הפעיל חסר במקור." if n_ai_missing else "")),
        "class_aria": f"תרשים עמודות מוערמות של מספר התכשירים לפי משפחה כימית וקהל מורשה, {n(len(cls_names))} משפחות",
        "class_caption": "תכשירים לפי משפחה כימית וקהל מורשה",
        "heat_note": (f"איזו משפחה כימית משמשת נגד איזה מזיק — מספר התכשירים בכל צירוף, "
                      f"עבור {n(len(heat_pests))} המזיקים הנפוצים."),
        "heat_aria": f"מפת חום של מזיקים מול משפחות כימיות, {n(len(heat_pests))} מזיקים ו-{n(len(cls_names))} משפחות",
        "heat_caption": "תכשירים לפי מזיק ומשפחה כימית",
        "ai_note": (f"{n(len(ai_names))} החומרים הפעילים הנפוצים מתוך {n(ai_tot.size)}, לפי מספר התכשירים שמכילים אותם. "
                    f"השמות מאוחדים לשם המקובל (למשל איזומרים וכתיב כימי מלא)."),
        "ai_aria": f"תרשים עמודות מוערמות של {n(len(ai_names))} החומרים הפעילים הנפוצים לפי קהל מורשה",
        "ai_caption": "החומרים הפעילים הנפוצים",
        "conc_note": (f"לכל חומר פעיל שמופיע גם בתכשירים לקהל הרחב וגם בתכשירים למדבירים בלבד — הריכוז המרבי "
                      f"בכל ערוץ ({n(len(conc_rows))} חומרים; ציר לוגריתמי). התכשירים למדבירים הם לרוב תרכיזים "
                      f"שמדוללים לפני השימוש, ולכן הפער משקף גם את צורת התכשיר."),
        "conc_aria": f"תרשים משקולות של הריכוז המרבי לציבור מול מדבירים עבור {n(len(conc_top))} חומרים פעילים",
        "conc_caption": "ריכוז מרבי לפי ערוץ",
        "forms_note": (f"התואריות ({n(df.loc[df[FORM] != '', FORM].nunique())} שמות שונים במקור) קובצו לקבוצות. "
                       f"פיתיונות ואירוסולים מוכנים לשימוש; תרכיזים מדוללים לפני הריסוס."),
        "forms_aria": f"תרשים עמודות מוערמות של מספר התכשירים לפי קבוצת תוארית וקהל מורשה, {n(len(fam_names))} קבוצות",
        "forms_caption": "תכשירים לפי קבוצת תוארית",
        "mix_note": "מספר החומרים הפעילים בכל תכשיר: חומר יחיד או תערובת, לפי קהל מורשה.",
        "mix_aria": f"תרשים עמודות של מספר החומרים הפעילים בתכשיר לפי קהל מורשה, {n(len(mix_order))} קבוצות",
        "mix_caption": "תכשירים לפי מספר החומרים הפעילים",
        "holders_note": (f"{n(len(h_keys))} בעלי הרישום הגדולים מתוך {n(n_holders)}."
                         + (f" שמות שנרשמו בכמה כתיבים או עם שם סניף אוחדו ({n(variants)} בעלי רישום)." if variants else "")
                         + (f" עבור {prods(h_counts.get(UNSPEC, 0))} לא צוין בעל הרישום." if h_counts.get(UNSPEC, 0) else "")),
        "holders_aria": f"תרשים עמודות מוערמות של מספר התכשירים לפי בעל רישום וקהל מורשה, {n(len(hb_order))} שורות",
        "holders_caption": "תכשירים לפי בעל רישום",
        "expiry_note": ((f"שנת פקיעת תוקף הרישום של כל תכשיר, {y0}–{y1}." if y0 is not None else "")
                        + (f" עבור {prods(exp_bad)} אין תאריך תקין." if exp_bad else "")
                        + " לפני שימוש כדאי לוודא שהרישום עדיין בתוקף."),
        "expiry_aria": (f"תרשים עמודות של מספר התכשירים לפי שנת פקיעת הרישום, {y0}–{y1}" if y0 is not None
                        else "תרשים עמודות של שנת פקיעת הרישום"),
        "expiry_caption": "תכשירים לפי שנת פקיעת הרישום",
        "products_caption": (f"{n(len(top_products))} התכשירים הרשומים נגד המספר הגדול ביותר של מזיקים."),
    }

    def stacked_table(ch):
        return [{"name": nm, "cells": [n(s["data"][i]) for s in ch["series"]],
                 "total": n(sum(s["data"][i] for s in ch["series"]))} for i, nm in enumerate(ch["names"])]

    tables = {
        "auds": auds,
        "audience": [{"name": a, "count": n(aud_counts.get(a, 0)),
                      "share": pct_bare(aud_counts.get(a, 0) / total if total else 0)} for a in auds],
        "pests": stacked_table(pest_chart),
        "classes": stacked_table(cls_chart),
        "heat": heat_table,
        "ai": [dict(r, cls=c) for r, c in zip(stacked_table(ai_chart), ai_chart["cls"])],
        "conc": [{"name": r["name"], "pub": conc_s(r["pub"]), "pro": conc_s(r["pro"]), "ratio": r["ratio_s"]}
                 for r in conc_top],
        "forms": [dict(r, ex=fam_examples.get(r["name"], "–")) for r in stacked_table(form_chart)],
        "mix": stacked_table(mix_chart),
        "holders": stacked_table(holder_chart),
        "expiry": [{"year": x, "count": n(y)} for x, y in zip(exp_chart["x"], exp_chart["y"])],
        "products": top_products,
    }

    pal_fixed = {PUBLIC: 0, BOTH: 2, PROS: 1, UNSPEC: 8}
    extra = iter([5, 3, 7, 4, 9, 6])
    aud_pal = [pal_fixed[a] if a in pal_fixed else next(extra, 6) for a in auds]
    charts = {
        "aud_pal": aud_pal,
        "audience": {"names": auds, "values": [int(aud_counts.get(a, 0)) for a in auds]},
        "pests": pest_chart,
        "classes": cls_chart,
        "heat": heat,
        "ai": ai_chart,
        "conc": conc_chart,
        "forms": form_chart,
        "mix": mix_chart,
        "holders": holder_chart,
        "expiry": exp_chart,
    }
    flags = {"conc": len(conc_top) >= 2, "expiry": len(exp_chart["x"]) > 0,
             "products": len(top_products) > 0}

    agent_data = {
        "summary_he": (f"מרשם תכשירי ההדברה לשימוש ביתי ותברואתי של המשרד להגנת הסביבה: {n(total)} תכשירים, "
                       f"{n(ai_tot.size)} חומרים פעילים ו-{n(n_holders)} בעלי רישום; {n(pub_ok)} מותרים לקהל הרחב "
                       f"ו-{n(pro_only)} למדבירים בלבד, עם ייעוד לפי מזיק, תוארית ותוקף רישום."),
        "dataset_kind": "registry",
        "related_ids": ["7a6cbf55-8178-4d40-8613-a38909c7e96f",
                        "14b7572d-c8f1-427a-8ef8-8069b197225d"],
        "suggested_tags": ["חומרי הדברה", "מדבירים", "מזיקים", "בריאות הציבור", "חומרים פעילים", "רישוי"],
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
