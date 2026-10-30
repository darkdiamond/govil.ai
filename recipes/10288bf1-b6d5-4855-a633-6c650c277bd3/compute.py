"""סוג בעלות בנכסים הרשומים בפנקסי המקרקעין (טאבו).

One row per registered unit: a whole parcel (תת חלקה == 0) or a sub-parcel
(a unit in a registered condominium, תת חלקה > 0), with the block (גוש),
parcel (חלקה), the registration method and the ownership type.

Everything on the page is aggregated here. Insight rules return a sentence or
None; their wording follows the data (argmax, sign of a gap), never the clock.
"""
import pandas as pd

# Known ownership types, in display order. Anything new flows through after
# them (by count, then name); an empty value is "לא צוין" and goes last.
KNOWN_OWNERS = ["פרטית", "מדינה", "רשות מקומית", "מעורב", "אחר"]
UNSPECIFIED_OWNER = "לא צוין"
UNSPECIFIED_METHOD = "לא צוינה שיטה"
OTHER = "אחר"

STATE = "מדינה"
PRIVATE = "פרטית"
LOCAL = "רשות מקומית"

# Condominium size buckets: (label, low, high) on the number of sub-parcels.
SIZE_BUCKETS = [
    ("1", 1, 1), ("2-4", 2, 4), ("5-9", 5, 9), ("10-19", 10, 19),
    ("20-49", 20, 49), ("50-99", 50, 99), ("100-199", 100, 199),
]
SIZE_TOP_LABEL = "200 ומעלה"
SIZE_TOP_LOW = 200

BAND_WIDTH = 5000
BAND_REGULAR_MAX = 40000      # bands of BAND_WIDTH below this block number
BAND_MID_MAX = 100000         # one band [BAND_REGULAR_MAX, BAND_MID_MAX)

TOP_METHODS = 6
TOP_BLOCKS = 12
MIN_BAND_ROWS = 20000         # a band must be this big to lead an insight


OWN_PHRASE = {
    "פרטית": "בעלות פרטית", "מדינה": "בעלות המדינה",
    "רשות מקומית": "בעלות רשות מקומית", "מעורב": "בעלות מעורבת",
    "אחר": "סוג בעלות אחר", UNSPECIFIED_OWNER: "סוג בעלות שלא צוין",
}


def _ph(owner):
    """Owner type as a Hebrew noun phrase ("בעלות המדינה")."""
    return OWN_PHRASE.get(owner, f"סוג הבעלות \"{owner}\"")


def _int(n):
    return f"{int(n):,}"


def _pct(x, digits=1):
    return f"{x * 100:.{digits}f}%"


def _share(a, b):
    return (a / b) if b else 0.0


def _prepare(df):
    out = pd.DataFrame({
        "block": pd.to_numeric(df["גוש"].str.replace(",", "").str.strip(), errors="coerce"),
        "parcel": pd.to_numeric(df["חלקה"].str.replace(",", "").str.strip(), errors="coerce"),
        "sub": pd.to_numeric(df["תת חלקה"].str.replace(",", "").str.strip(), errors="coerce"),
    })
    own = df["סוג בעלות"].str.strip()
    out["owner"] = own.where(own != "", UNSPECIFIED_OWNER)
    meth = df["תיאור שיטה"].str.strip().str.replace("~", "״", regex=False)
    out["method"] = meth.where(meth != "", UNSPECIFIED_METHOD)
    return out


def _owner_order(counts):
    """KNOWN_OWNERS that occur, then unknown types by count desc + name."""
    present = [o for o in KNOWN_OWNERS if counts.get(o, 0) > 0]
    rest = [(-int(v), k) for k, v in counts.items()
            if k not in KNOWN_OWNERS and k != UNSPECIFIED_OWNER and v > 0]
    present += [k for _, k in sorted(rest)]
    if counts.get(UNSPECIFIED_OWNER, 0) > 0:
        present.append(UNSPECIFIED_OWNER)
    return present


def _stack(table, cats, owners):
    """table: DataFrame index=cats, columns=owners (counts)."""
    counts = [[int(table.at[c, o]) if (c in table.index and o in table.columns) else 0
               for c in cats] for o in owners]
    totals = [sum(counts[i][j] for i in range(len(owners))) for j in range(len(cats))]
    shares = [[round(_share(counts[i][j], totals[j]) * 100, 1) for j in range(len(cats))]
              for i in range(len(owners))]
    return {"cats": cats, "owners": owners, "counts": counts,
            "shares": shares, "totals": totals}


def _band_label(block):
    if block < BAND_REGULAR_MAX:
        lo = int(block // BAND_WIDTH) * BAND_WIDTH
        return lo, f"{lo:,}-{lo + BAND_WIDTH - 1:,}"
    if block < BAND_MID_MAX:
        return BAND_REGULAR_MAX, f"{BAND_REGULAR_MAX:,}-{BAND_MID_MAX - 1:,}"
    return BAND_MID_MAX, f"{BAND_MID_MAX:,} ומעלה"


def _size_label(n):
    for label, lo, hi in SIZE_BUCKETS:
        if lo <= n <= hi:
            return label
    return SIZE_TOP_LABEL


# ── insight rules ──────────────────────────────────────────────────────────

def insight_overall(by_owner, total):
    if total == 0 or len(by_owner) < 2:
        return None
    (o1, v1), (o2, v2) = list(by_owner.items())[:2]
    s1, s2 = _share(v1, total), _share(v2, total)
    if s1 < 0.3 or v1 == v2:
        return None
    return (f"{_ph(o1)} היא הנפוצה במאגר: {_int(v1)} מתוך {_int(total)} "
            f"הנכסים הרשומים ({_pct(s1)}). אחריה {_ph(o2)}, עם {_int(v2)} נכסים ({_pct(s2)}).")


def insight_unit_contrast(whole, subs):
    """Leader among whole parcels vs among sub-parcels."""
    wt, st = int(whole.sum()), int(subs.sum())
    if wt == 0 or st == 0:
        return None
    w_lead, s_lead = whole.index[0], subs.index[0]
    if ((len(whole) > 1 and whole.iloc[0] == whole.iloc[1])
            or (len(subs) > 1 and subs.iloc[0] == subs.iloc[1])):
        return None
    ws, ss = _share(whole.iloc[0], wt), _share(subs.iloc[0], st)
    if w_lead != s_lead:
        return (f"התמונה משתנה לפי סוג היחידה: בחלקות השלמות ({_int(wt)}) מובילה "
                f"{_ph(w_lead)} עם {_pct(ws)}, ואילו בתתי-החלקות, היחידות בבתים משותפים "
                f"({_int(st)}), מובילה {_ph(s_lead)} עם {_pct(ss)}.")
    gap = ss - ws
    if abs(gap) < 0.1:
        return None
    word = "גבוה" if gap > 0 else "נמוך"
    return (f"{_ph(s_lead)} מובילה הן בחלקות השלמות ({_pct(ws)}) והן בתתי-החלקות "
            f"בבתים משותפים, אך שיעורה בתתי-החלקות {word} יותר: {_pct(ss)}.")


def insight_local(whole, subs):
    wt, st = int(whole.sum()), int(subs.sum())
    if wt == 0 or st == 0 or LOCAL not in whole.index:
        return None
    w = _share(whole.get(LOCAL, 0), wt)
    s = _share(subs.get(LOCAL, 0), st)
    if w < 0.03 or w < 3 * s:
        return None
    return (f"רשויות מקומיות רשומות כבעלים של {_int(whole.get(LOCAL, 0))} חלקות שלמות "
            f"({_pct(w)} מהחלקות השלמות), אך רק של {_pct(s)} מתתי-החלקות בבתים משותפים.")


def insight_blocks(dominant, n_blocks, homogeneous):
    if n_blocks == 0 or dominant.empty:
        return None
    lead, v = dominant.index[0], int(dominant.iloc[0])
    if len(dominant) > 1 and v == int(dominant.iloc[1]):
        return None
    s = _share(v, n_blocks)
    if s < 0.4:
        return None
    return (f"ב-{_int(v)} מתוך {_int(n_blocks)} הגושים ({_pct(s)}) {_ph(lead)} היא "
            f"הנפוצה ביותר. ב-{_int(homogeneous)} גושים ({_pct(_share(homogeneous, n_blocks))}) "
            f"כל הנכסים רשומים תחת סוג בעלות אחד.")


def insight_condo_size(sizes, top_condo):
    if sizes.empty or top_condo is None:
        return None
    med = float(sizes.median())
    big = int((sizes >= 50).sum())
    blk, prc, n = top_condo
    med_txt = _int(med) if med == int(med) else f"{med:.1f}"
    return (f"ב-{_int(len(sizes))} חלקות רשום בית משותף. החציון הוא {med_txt} תתי-חלקות "
            f"לחלקה, ב-{_int(big)} חלקות יש {_int(50)} תתי-חלקות או יותר, והגדולה ביותר "
            f"(גוש {blk}, חלקה {prc}) כוללת {_int(n)} תתי-חלקות.")


def insight_condo_mix(n_condos, all_private, any_state, mixed):
    if n_condos == 0:
        return None
    sp = _share(all_private, n_condos)
    if sp < 0.2:
        return None
    return (f"ב-{_pct(sp)} מהבתים המשותפים כל תתי-החלקות בבעלות פרטית. ב-{_int(any_state)} "
            f"בתים משותפים ({_pct(_share(any_state, n_condos))}) לפחות תת-חלקה אחת רשומה "
            f"בבעלות המדינה, וב-{_int(mixed)} ({_pct(_share(mixed, n_condos))}) מופיע יותר מסוג בעלות אחד.")


def insight_method(method_tab, overall_lead, overall_share, n_total):
    """The registration method whose leader-share departs most from the whole."""
    best = None
    for m, row in method_tab.iterrows():
        if m == UNSPECIFIED_METHOD:
            continue
        n = int(row.sum())
        if n < 5000:
            continue
        s = _share(int(row.get(overall_lead, 0)), n)
        dev = s - overall_share
        key = (-abs(dev), m)
        if best is None or key < best[0]:
            best = (key, m, n, s, dev)
    if best is None:
        return None
    _, m, n, s, dev = best
    if abs(dev) < 0.1:
        return None
    word = "נמוך" if dev < 0 else "גבוה"
    return (f"בנכסים הרשומים בשיטת \"{m}\" ({_int(n)} נכסים) שיעור {_ph(overall_lead)} "
            f"{word} במובהק מהממוצע: {_pct(s)}, לעומת {_pct(overall_share)} בכלל המאגר.")


def insight_bands(band_stack, regular):
    """Contrast between the most-state and most-private block-number ranges
    (regular ranges only: the wide catch-all ranges are not comparable)."""
    cats, owners = band_stack["cats"], band_stack["owners"]
    if STATE not in owners or PRIVATE not in owners:
        return None
    si, pi = owners.index(STATE), owners.index(PRIVATE)
    big = [j for j, t in enumerate(band_stack["totals"])
           if t >= MIN_BAND_ROWS and cats[j] in regular]
    if len(big) < 3:
        return None
    js = max(big, key=lambda j: (band_stack["shares"][si][j], -j))
    jp = max(big, key=lambda j: (band_stack["shares"][pi][j], -j))
    if js == jp:
        return None
    s_state = band_stack["shares"][si][js]
    s_priv = band_stack["shares"][pi][jp]
    if s_state < 50 or s_priv < 50:
        return None
    return (f"בטווח הגושים {cats[js]} רשומים {s_state:.1f}% מהנכסים בבעלות המדינה, "
            f"ובטווח {cats[jp]} {s_priv:.1f}% מהנכסים הם בבעלות פרטית "
            f"(מבין טווחי הגושים שמתחת ל-{_int(BAND_REGULAR_MAX)} עם {_int(MIN_BAND_ROWS)} נכסים לפחות).")


# ── compute ────────────────────────────────────────────────────────────────

def compute(frames):
    df = _prepare(frames["main"])
    total = len(df)

    by_owner_raw = df["owner"].value_counts()
    owners = _owner_order(by_owner_raw.to_dict())
    # Owner ranking for insights: count desc, then name (total order).
    by_owner = (by_owner_raw.sort_index()
                .sort_values(ascending=False, kind="stable"))

    struct = df.dropna(subset=["block", "parcel", "sub"]).copy()
    struct["block"] = struct["block"].astype("int64")
    struct["parcel"] = struct["parcel"].astype("int64")
    struct["sub"] = struct["sub"].astype("int64")
    is_sub = struct["sub"] > 0

    # 1. overall donut
    owners_chart = {"names": owners,
                    "nums": [int(by_owner_raw.get(o, 0)) for o in owners],
                    "shares": [round(_share(by_owner_raw.get(o, 0), total) * 100, 1) for o in owners]}

    # 2. whole parcels vs sub-parcels
    unit_lbl = pd.Series("חלקות שלמות", index=struct.index)
    unit_lbl[is_sub] = "תתי-חלקות (בתים משותפים)"
    unit_tab = pd.crosstab(unit_lbl, struct["owner"])
    unit_cats = [c for c in ["חלקות שלמות", "תתי-חלקות (בתים משותפים)"] if c in unit_tab.index]
    unit_stack = _stack(unit_tab, unit_cats, owners)
    whole = (struct.loc[~is_sub, "owner"].value_counts().sort_index()
             .sort_values(ascending=False, kind="stable"))
    subs = (struct.loc[is_sub, "owner"].value_counts().sort_index()
            .sort_values(ascending=False, kind="stable"))

    # 3. registration method
    meth_counts = (df["method"].value_counts().sort_index()
                   .sort_values(ascending=False, kind="stable"))
    keep = list(meth_counts.index[:TOP_METHODS])
    meth = df["method"].where(df["method"].isin(keep), OTHER + " (שיטות נוספות)")
    meth_tab = pd.crosstab(meth, df["owner"])
    meth_cats = keep + ([OTHER + " (שיטות נוספות)"] if len(meth_counts) > TOP_METHODS else [])
    meth_stack = _stack(meth_tab, meth_cats, owners)
    method_full_tab = pd.crosstab(df["method"], df["owner"]).sort_index()

    # 4-5. condominiums (parcels with sub-parcels)
    sp = struct[is_sub]
    condo_size = sp.groupby(["block", "parcel"]).size().sort_index()
    size_labels = [b[0] for b in SIZE_BUCKETS] + [SIZE_TOP_LABEL]
    size_of = condo_size.map(_size_label)
    size_counts = size_of.value_counts()
    size_chart = {"cats": size_labels,
                  "nums": [int(size_counts.get(l, 0)) for l in size_labels]}
    sp_size = sp.join(size_of.rename("bucket"), on=["block", "parcel"])
    size_tab = pd.crosstab(sp_size["bucket"], sp_size["owner"])
    size_cats = [l for l in size_labels if l in size_tab.index]
    size_stack = _stack(size_tab, size_cats, owners)
    top_condo = None
    if len(condo_size):
        tc = condo_size.reset_index(name="n").sort_values(
            ["n", "block", "parcel"], ascending=[False, True, True], kind="stable").iloc[0]
        top_condo = (int(tc["block"]), int(tc["parcel"]), int(tc["n"]))

    # condo ownership composition
    cnt = sp.groupby(["block", "parcel", "owner"]).size().unstack(fill_value=0)
    n_condos = len(cnt)
    n_types = (cnt > 0).sum(axis=1)
    priv_col = cnt[PRIVATE] if PRIVATE in cnt.columns else pd.Series(0, index=cnt.index)
    state_col = cnt[STATE] if STATE in cnt.columns else pd.Series(0, index=cnt.index)
    all_private = int(((n_types == 1) & (priv_col > 0)).sum())
    all_state = int(((n_types == 1) & (state_col > 0)).sum())
    all_other = int((n_types == 1).sum()) - all_private - all_state
    priv_state = int(((n_types == 2) & (priv_col > 0) & (state_col > 0)).sum())
    mixed = int((n_types > 1).sum())
    other_mix = mixed - priv_state
    any_state = int((state_col > 0).sum())
    mix_chart = {
        "cats": ["כולן בבעלות פרטית", "כולן בבעלות המדינה", "כולן מסוג בעלות יחיד אחר",
                 "פרטית ומדינה יחד", "שילוב אחר של סוגי בעלות"],
        "nums": [all_private, all_state, all_other, priv_state, other_mix],
    }

    # 6. blocks: dominant ownership type and homogeneity
    bo = struct.groupby(["block", "owner"]).size().reset_index(name="n")
    bo = bo.sort_values(["block", "n", "owner"], ascending=[True, False, True], kind="stable")
    first = bo.drop_duplicates("block", keep="first").set_index("block")
    second_n = (bo[bo.duplicated("block", keep="first")]
                .drop_duplicates("block", keep="first").set_index("block")["n"])
    tied = first["n"] == second_n.reindex(first.index).fillna(-1)
    n_ties = int(tied.sum())
    dom_all = first["owner"]
    dom = dom_all[~tied]          # blocks with a strict leader only
    n_types_blk = bo.groupby("block")["owner"].nunique()
    n_blocks = int(len(dom_all))
    homogeneous = int((n_types_blk == 1).sum())
    homog_by = dom_all[n_types_blk == 1].value_counts()
    dom_counts = dom.value_counts()
    dominant = dom_counts.sort_index().sort_values(ascending=False, kind="stable")
    block_chart = {"names": owners,
                   "dominant": [int(dom_counts.get(o, 0)) for o in owners],
                   "homogeneous": [int(homog_by.get(o, 0)) for o in owners]}

    # 7. block-number ranges
    b = struct["block"]
    band_lo = ((b // BAND_WIDTH) * BAND_WIDTH).where(
        b < BAND_REGULAR_MAX, BAND_REGULAR_MAX).where(b < BAND_MID_MAX, BAND_MID_MAX)
    names = {int(lo): _band_label(int(lo))[1] for lo in band_lo.unique()}
    band_name = band_lo.map(names)
    band_tab = pd.crosstab(band_name, struct["owner"])
    band_order = (pd.DataFrame({"lo": band_lo, "name": band_name})
                  .drop_duplicates().sort_values(["lo", "name"]))
    band_stack = _stack(band_tab, list(band_order["name"]), owners)
    regular_bands = set(band_order.loc[band_order["lo"] < BAND_REGULAR_MAX, "name"])

    # 8. biggest blocks
    blk_size = struct.groupby("block").size()
    top_blocks = (blk_size.reset_index(name="n")
                  .sort_values(["n", "block"], ascending=[False, True], kind="stable")
                  .head(TOP_BLOCKS)["block"].tolist())
    tb = struct[struct["block"].isin(top_blocks)]
    tb_tab = pd.crosstab(tb["block"], tb["owner"])
    top_stack = _stack(tb_tab, top_blocks, owners)
    top_stack["cats"] = [f"גוש {b}" for b in top_blocks]

    n_parcels = int(struct[["block", "parcel"]].drop_duplicates().shape[0])
    n_sub = int(is_sub.sum())

    # ── insights ──
    lead_owner = by_owner.index[0] if len(by_owner) else None
    lead_share = _share(by_owner.iloc[0], total) if len(by_owner) else 0.0
    rules = [
        ("overall", insight_overall(by_owner, total)),
        ("unit_contrast", insight_unit_contrast(whole, subs)),
        ("local", insight_local(whole, subs)),
        ("condo_mix", insight_condo_mix(n_condos, all_private, any_state, mixed)),
        ("condo_size", insight_condo_size(condo_size, top_condo)),
        ("blocks", insight_blocks(dominant, n_blocks, homogeneous)),
        ("bands", insight_bands(band_stack, regular_bands)),
        ("method", insight_method(method_full_tab, lead_owner, lead_share, total)
         if lead_owner else None),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    # ── KPIs ──
    def kpi(v, tone="brand"):
        return {"value": v, "display": _int(v), "tone": tone}

    priv_share = _share(by_owner_raw.get(PRIVATE, 0), total)
    state_share = _share(by_owner_raw.get(STATE, 0), total)
    kpis = {
        "total": kpi(total),
        "blocks": kpi(n_blocks),
        "parcels": kpi(n_parcels),
        "subs": kpi(n_sub),
        "private": {"value": round(priv_share * 100, 1), "display": _pct(priv_share), "tone": "brand"},
        "state": {"value": round(state_share * 100, 1), "display": _pct(state_share), "tone": "info"},
    }

    # ── ledes / aria ──
    top_name = owners_chart["names"][owners_chart["nums"].index(max(owners_chart["nums"]))] if total else ""
    lbl = {}
    lbl["owners_aria"] = (f"תרשים טבעת: התפלגות {_int(total)} הנכסים הרשומים לפי סוג בעלות. "
                          f"הסוג הנפוץ: {top_name}.")
    lbl["owners_lede"] = (f"כל שורה במאגר היא נכס רשום: חלקה שלמה או תת-חלקה בבית משותף. "
                          f"סך הכול {_int(total)} נכסים ב-{_int(n_blocks)} גושים.")
    if unit_cats and len(whole) and len(subs):
        lbl["unit_lede"] = (f"{_int(int(whole.sum()))} חלקות שלמות לעומת {_int(int(subs.sum()))} "
                            f"תתי-חלקות. בחלקות השלמות מובילה {_ph(whole.index[0])} "
                            f"({_pct(_share(whole.iloc[0], whole.sum()))}), ובתתי-החלקות "
                            f"{_ph(subs.index[0])} ({_pct(_share(subs.iloc[0], subs.sum()))}).")
    else:
        lbl["unit_lede"] = f"חלוקת {_int(total)} הנכסים לפי סוג היחידה וסוג הבעלות."
    lbl["unit_aria"] = "תרשים עמודות מוערמות באחוזים: סוג הבעלות בחלקות שלמות לעומת תתי-חלקות. " + lbl["unit_lede"]
    m0 = meth_counts.index[0] if len(meth_counts) else ""
    n_unspec = int(meth_counts.get(UNSPECIFIED_METHOD, 0))
    if n_unspec:
        lbl["method_lede"] = (f"שיטת הרישום מצוינת רק לחלק מהנכסים: {_int(n_unspec)} "
                              f"נכסים ({_pct(_share(n_unspec, total))}) רשומים ללא ציון שיטה. "
                              f"השיטות האחרות הן רישומים מיוחדים, כמו גוש שומה ופנקסי ספר-דף.")
    else:
        lbl["method_lede"] = f"שיטת הרישום מצוינת לכל {_int(total)} הנכסים במאגר."
    lbl["method_aria"] = (f"תרשים עמודות מוערמות באחוזים: סוג הבעלות לפי שיטת הרישום, "
                          f"{_int(len(meth_cats))} קטגוריות. השיטה הנפוצה: {m0}.")
    med = float(condo_size.median()) if len(condo_size) else 0.0
    med_txt = _int(med) if med == int(med) else f"{med:.1f}"
    peak_size = size_labels[size_chart["nums"].index(max(size_chart["nums"]))] if n_condos else ""
    lbl["size_lede"] = (f"{_int(n_condos)} חלקות כוללות תתי-חלקות. החציון: {med_txt} תתי-חלקות לחלקה, "
                        f"והקבוצה הגדולה ביותר היא בתים של {peak_size} תתי-חלקות.")
    lbl["size_aria"] = "תרשים עמודות: מספר הבתים המשותפים לפי מספר תתי-החלקות בחלקה. " + lbl["size_lede"]
    lbl["size_own_aria"] = "תרשים עמודות מוערמות באחוזים: סוג הבעלות בתתי-החלקות לפי גודל הבית המשותף."
    st_i = owners.index(STATE) if STATE in owners else None
    if st_i is not None and size_stack["cats"]:
        sh = size_stack["shares"][st_i]
        jmax = max(range(len(sh)), key=lambda j: (sh[j], -j))
        lbl["size_own_lede"] = (f"שיעור תתי-החלקות בבעלות המדינה נע בין {min(sh):.1f}% ל-{max(sh):.1f}% "
                                f"לפי גודל הבית, והגבוה ביותר בבתים של {size_stack['cats'][jmax]} תתי-חלקות.")
    else:
        lbl["size_own_lede"] = "סוג הבעלות בתתי-החלקות לפי מספר תתי-החלקות בבית המשותף."
    lbl["mix_lede"] = (f"מתוך {_int(n_condos)} בתים משותפים, ב-{_int(all_private)} ({_pct(_share(all_private, n_condos))}) "
                       f"כל תתי-החלקות פרטיות, וב-{_int(mixed)} ({_pct(_share(mixed, n_condos))}) מופיע יותר מסוג בעלות אחד.")
    lbl["mix_aria"] = "תרשים עמודות: הרכב סוגי הבעלות בבתים המשותפים. " + lbl["mix_lede"]
    dlead = dominant.index[0] if len(dominant) else ""
    lbl["blocks_lede"] = (f"בכל גוש נבדק סוג הבעלות הנפוץ ביותר. ב-{_int(int(dominant.iloc[0]) if len(dominant) else 0)} "
                          f"מתוך {_int(n_blocks)} גושים מובילה {_ph(dlead)}, ו-{_int(homogeneous)} גושים "
                          f"הומוגניים לחלוטין (סוג בעלות אחד לכל הנכסים)."
                          + (f" ב-{_int(n_ties)} גושים יש שוויון בין שני סוגים מובילים, והם אינם נספרים כאן." if n_ties else ""))
    lbl["blocks_aria"] = "תרשים עמודות: מספר הגושים לפי סוג הבעלות המוביל בגוש, ומספר הגושים ההומוגניים. " + lbl["blocks_lede"]
    lbl["bands_lede"] = (f"הנכסים מקובצים לפי טווחי מספרי גוש ברוחב {_int(BAND_WIDTH)}. גושים במספור קרוב "
                         f"נוטים להימצא באותו אזור, אך הטווחים אינם מחוזות. גושים שמספרם {_int(BAND_REGULAR_MAX)} "
                         f"ומעלה מקובצים בשני טווחים רחבים, כי המספור בהם דליל.")
    lbl["bands_aria"] = (f"תרשים עמודות מוערמות באחוזים: סוג הבעלות לפי טווח מספרי גוש, "
                         f"{_int(len(band_stack['cats']))} טווחים.")
    if top_blocks:
        b0 = top_stack["cats"][0]
        lbl["top_lede"] = (f"{_int(TOP_BLOCKS if len(top_blocks) >= TOP_BLOCKS else len(top_blocks))} הגושים עם "
                           f"מספר הנכסים הרשומים הגדול ביותר. בראש: {b0} עם {_int(top_stack['totals'][0])} נכסים.")
    else:
        lbl["top_lede"] = "הגושים עם מספר הנכסים הרשומים הגדול ביותר."
    lbl["top_aria"] = "תרשים עמודות מוערמות: הגושים הגדולים לפי מספר נכסים וסוג בעלות. " + lbl["top_lede"]
    lbl["total_kpi"] = "נכסים רשומים (חלקות ותתי-חלקות)"
    lbl["private_kpi"] = "בבעלות פרטית"
    lbl["state_kpi"] = "בבעלות המדינה"

    # summary (meta description) ≤155 chars
    top2 = list(by_owner.items())[:2]
    parts = ", ".join(f"{_pct(_share(v, total), 0)} ב{_ph(o)}" for o, v in top2)
    summary = (f"איתור סוג הבעלות בנכס לפי גוש, חלקה ותת-חלקה: {_int(total)} נכסים בפנקסי "
               f"המקרקעין (טאבו), {parts}.")

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "registry",
            "suggested_tags": ["מקרקעין", "טאבו", "בעלות על קרקע", "פנקסי המקרקעין", "בתים משותפים"],
            "related_ids": ["669b2652-f75b-4de3-8e6b-0dfa17accef5",
                            "3111ae54-790a-4d02-9750-d51e1134b405"],
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": {
            "owners": owners_chart,
            "unit": unit_stack,
            "method": meth_stack,
            "size": size_chart,
            "size_own": size_stack,
            "mix": mix_chart,
            "blocks": block_chart,
            "bands": band_stack,
            "top": top_stack,
        },
        "insights": insights,
        "labels": lbl,
    }
