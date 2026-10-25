"""רשימת חברות ממשלתיות ודירקטורים מכהנים — Ministry of Finance (רשות החברות).

Two tables, joined on COMPANY_NAME (exact string; every name in the
directors file exists in the companies file):

- ``companies`` — one row per government company (~106): name, website,
  free-text main occupation, legal status (ממשלתית / בת ממשלתית / מעורבת /
  עמותה) and the supervising ministry.
- ``directors`` — one row per (company, person, role) (~420). Roles are
  דירקטור, דח"צ (external director), יו"ר, מנכ"ל and מנכ"ל בפועל. A chair
  appears twice — once as יו"ר and once as דירקטור — so a BOARD MEMBER is a
  distinct (company, first+last name) among the board roles {דירקטור, דח"צ,
  יו"ר}. The CEO is management, not a board seat.

Not every company has rows in the directors file; the page says how many
and which ministries/statuses they fall under, rather than treating them as
empty boards.

Gender is ESTIMATED from the first given name against a fixed list of
unambiguous Hebrew/Arabic/foreign names; unisex or unknown names stay
"לא סווג" and every gender figure discloses that count. New names flow into
the unclassified bucket until the lists are extended, and the gender
insights drop when that bucket grows past a threshold.

Directors hold public office and may be named (multi-board directors);
no contact details or identifiers exist in the data.
"""
import re

import pandas as pd

BOARD_ROLES = ("דירקטור", 'דח"צ', 'יו"ר')
CHAIR = 'יו"ר'
EXTERNAL = 'דח"צ'
DIRECTOR = "דירקטור"
CEO_PREFIX = 'מנכ"ל'
ROLE_ORDER = [DIRECTOR, EXTERNAL, CHAIR, 'מנכ"ל', 'מנכ"ל בפועל']
STATUS_ORDER = ["ממשלתית", "בת ממשלתית", "מעורבת", "עמותה"]
STATUS_COLOR = {"ממשלתית": "#0068f5", "בת ממשלתית": "#5b9cf8",
                "מעורבת": "#0b3668", "עמותה": "#9cbcf0"}
W, M, U = "נשים", "גברים", "לא סווג"
G_COLOR = {W: "#0068f5", M: "#0b3668", U: "#c3cfe7"}
TOP_OFFICES = 12
TOP_BOARDS = 15
MAX_UNKNOWN = 0.2       # gender insights need ≥80% of members classified
SIZE_BUCKETS = [(1, 1), (2, 2), (3, 3), (4, 5), (6, 7), (8, 9), (10, 12), (13, None)]
LRI, PDI = "⁦", "⁩"

FEMALE = set("""
אודליה אוה אורטל אורית אורלי אורנה איה איזבל אילת איריס אלה אלונה אליס
אלכסנדרה אסנת אסתי אסתר אפרת אתי בלה גתית דבורה דליה דלית דניאלה דפנה
הדס הדסה הדסי הילה חגית חוה חנה טלי טניה טקלה יודפת יעל יפה כרמית ליאת
לילך לימור מאשה מזל מיה מיכל מריה נוהא נורית נילי נעמי סאלי סופי סיגל
סיגלית עביר עידית עילית עינב עינת עופרה ענת ערין צילה ציפי קטי רבקה רווית
רוית רונית רננה רעות רעיה רקפת שולי שוש שושנה שירלי שרית תמר מירב מיכאלה
אביטל אורנית אילנה גלית דנה הגר ורד זהבה חני יהודית יוכבד לאה מירית מלכה
נגה נטע סמדר עליזה פנינה צביה קרן רחל רינה רותי רות שלומית שרה תהילה תמי
""".split())
MALE = set("""
אבי אביב אביחי אבנר אברהם אבשלום אדמון אהרון אהרן אודי אוהד אורון אורי
אוריאל אורן אורסאן אושיק אייל איל אילן איציק איתי איתמר אלברט אלדד אלון
אלחנן אלי אליהו אליעזר אלכס אלעד אמיתי אמנון אנדריי אסי אסעד אפרים ארז
אריאל אשר בועז בן בני בנימין ברוך בשאר ג'מיל גבריאל גיא גיורא גלעד דאוד
דוד דודו דורון דותן דמיטרי דן דניאל דסליי דרור הנרי הרצל ואיל ויקטור
ולדימיר וסאם זאב חאג חיים חסין טובי יאיר יגאל יואב יואל יובל יוחנן יונתן
יוסי יוסף יוראי יורם יחזקאל יניב יעקב יצחק ירון ישראל כתריאל לוי מאור מאיר
מוחמד מוטי מוני מיכאל מימון מרדכי משה ניב ניסים ניסן נתי סלמאן סמי סעיד
עובדיה עודד עוזי עומרי עזמי עזריאל עזריה עידן עמאד עמוס עמיר ערן פול פיני
פנחס צבי צדוק צחי ציון קובי ראובן ריכאד רישאר רן רפאל רונן שאדי שאול שבתאי
שלמה שמואל שמוליק שמעון שר-שלום תומר תמיר אבירם אברי גדעון דני זיו חגי
יהודה יחיאל ליאב מנחם נחום נתן עזרא עמרי ערד רמי שגיא שחר שמשון אמיר
""".split())


def n(v):
    return f"{int(v):,}"


def pct(v, digits=0):
    return f"{LRI}{v:.{digits}f}%{PDI}"


def pct_plain(v, digits=0):
    return f"{v:.{digits}f}%"


def short_name(s, limit=30):
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r'\s*\(?בע"מ\)?$', "", s).strip()
    s = re.sub(r"\s+-\s*$", "", s)
    return s if len(s) <= limit else s[:limit - 1].rstrip() + "…"


def gender_of(first):
    tok = re.split(r"[\s\-]+", first.strip())
    head = tok[0] if tok else ""
    if first.strip() == "שר-שלום":
        head = "שר-שלום"
    if head in FEMALE:
        return W
    if head in MALE:
        return M
    return U


def join_he(items):
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    last = items[-1]
    vav = "ו" if re.match(r"[\u05d0-\u05ea]", last) else "ו-"
    return ", ".join(items[:-1]) + " " + vav + last


def _order(values, known):
    present = set(values)
    head = [v for v in known if v in present]
    return head + sorted(present - set(head))


def _counts(s):
    return s.value_counts().sort_index().sort_values(ascending=False, kind="stable")


# ── insight rules ────────────────────────────────────────────────────────
def insight_status(st, total):
    if total == 0 or st.empty:
        return None
    lead, lv = st.index[0], int(st.iloc[0])
    if lv / total < 0.4:
        return None
    rest = [f'{n(v)} "{k}"' for k, v in st.iloc[1:].items() if v > 0]
    s = f'{n(lv)} מתוך {n(total)} החברות ({pct(lv / total * 100)}) מוגדרות "{lead}"'
    return s + (f"; לצדן {join_he(rest)}." if rest else ".")


def insight_office(off):
    if len(off) < 3:
        return None
    top = int(off.iloc[0])
    leaders = [k for k, v in off.items() if v == top]
    if len(leaders) > 3:
        return None
    nxt = off[off < top]
    tail = ""
    if len(nxt) >= 2:
        tail = (f"; אחריהם {nxt.index[0]} ({n(nxt.iloc[0])}) ו{nxt.index[1]}"
                f" ({n(nxt.iloc[1])})")
    if len(leaders) == 1:
        head = f"משרד {leaders[0]} מפקח על מספר החברות הגדול ביותר — {n(top)}"
    else:
        head = (f"משרדי {join_he(leaders)} מפקחים על מספר החברות הגדול ביותר —"
                f" {n(top)} כל אחד")
    return head + tail + f". בסך הכול {n(len(off))} משרדים מפקחים על חברות ממשלתיות."


def insight_missing(comp):
    total = len(comp)
    miss = comp[~comp["listed"]]
    if total == 0 or miss.empty:
        return None
    by_off = (comp.groupby("office")["listed"].agg(["size", "sum"])
              .reset_index().sort_values("office"))
    none = by_off[(by_off["sum"] == 0) & (by_off["size"] >= 2)]["office"].tolist()
    by_st = _counts(miss["status"])
    lead = by_st.index[0]
    lead_tot = int((comp["status"] == lead).sum())
    s = (f"ל-{n(len(miss))} מתוך {n(total)} החברות אין דירקטורים ברשימת המכהנים;"
         f' הבולטות הן חברות בסטטוס "{lead}" — {n(by_st.iloc[0])} מתוך {n(lead_tot)}')
    if none:
        s += (f". לחברות של משרד {none[0]} לא רשום אף דירקטור" if len(none) == 1 else
              f". לחברות של משרדי {join_he(none)} לא רשום אף דירקטור")
    return s + "."


def insight_biggest(boards):
    if len(boards) < 5:
        return None
    top = boards.iloc[0]
    second = boards.iloc[1]
    med = float(boards["size"].median())
    if top["size"] < med * 1.5:
        return None
    med_s = f"{med:.1f}".rstrip("0").rstrip(".")
    return (f"הדירקטוריון הגדול ביותר ברשימה הוא של {top['company']} — {n(top['size'])}"
            f" חברים, ואחריו {second['company']} ({n(second['size'])}); החציון בין"
            f" {n(len(boards))} החברות שיש להן דירקטוריון ברשימה הוא {med_s} חברים.")


def insight_small(boards):
    if len(boards) < 5:
        return None
    small = boards[boards["size"] <= 2]
    one = int((boards["size"] == 1).sum())
    if len(small) < 3:
        return None
    return (f"ב-{n(len(small))} חברות ({pct(len(small) / len(boards) * 100)} מהחברות עם"
            f" דירקטוריון ברשימה) רשומים שני דירקטורים לכל היותר, ובהן {n(one)} עם דירקטור"
            " יחיד — ייתכן שחלק מהמושבים פנויים או טרם עודכנו.")


def insight_gaps(boards, ceo_companies):
    if len(boards) < 5:
        return None
    no_chair = int((~boards["has_chair"]).sum())
    if no_chair == 0:
        return None
    ext = int((boards["external"] > 0).sum())
    ceo = int(boards["company_full"].isin(ceo_companies).sum())
    return (f"מתוך {n(len(boards))} הדירקטוריונים שברשימה, ב-{n(no_chair)} לא מסומן יו\"ר;"
            f" ב-{n(ext)} מכהן לפחות דירקטור חיצוני (דח\"צ), וב-{n(ceo)} רשום גם מנכ\"ל.")


def insight_gender(members):
    total = len(members)
    if total < 20:
        return None
    g = members["gender"].value_counts()
    unk = int(g.get(U, 0))
    if unk / total > MAX_UNKNOWN:
        return None
    w, m = int(g.get(W, 0)), int(g.get(M, 0))
    if w + m == 0:
        return None
    share = w / (w + m) * 100
    s = (f"לפי הערכה על בסיס השם הפרטי, {pct(share)} מחברי הדירקטוריונים שסווגו הן נשים"
         f" — {n(w)} נשים ו-{n(m)} גברים")
    if unk:
        s += f"; {n(unk)} שמות שאינם חד-משמעיים לא סווגו"
    return s + "."


def insight_gender_chairs(members):
    chairs = members[members["is_chair"]]
    if len(chairs) < 5 or len(members) < 20:
        return None
    if (members["gender"] == U).mean() > MAX_UNKNOWN:
        return None

    def share(df):
        k = df[df["gender"] != U]
        return (k["gender"] == W).mean() * 100 if len(k) else None

    cs, alls = share(chairs), share(members)
    if cs is None or alls is None or abs(cs - alls) < 5:
        return None
    cw = int((chairs["gender"] == W).sum())
    ck = int((chairs["gender"] != U).sum())
    word = "נמוך" if cs < alls else "גבוה"
    return (f"בראשות הדירקטוריונים שיעור הנשים {word} יותר: {n(cw)} מתוך {n(ck)} יושבי"
            f" הראש שסווגו ({pct(cs)}), לעומת {pct(alls)} מכלל חברי הדירקטוריונים.")


def insight_no_women(gb, min_size=5):
    big = gb[(gb["size"] >= min_size) & (gb[U] == 0)]
    if len(big) < 2:
        return None
    zero = big[big[W] == 0].sort_values(["size", "company"], ascending=[False, True])
    if zero.empty:
        return None
    names = zero["company"].tolist()
    lst = join_he(names[:3]) + (" ועוד" if len(names) > 3 else "")
    return (f"ב-{n(len(zero))} מתוך {n(len(big))} הדירקטוריונים בני {n(min_size)} חברים ומעלה"
            f" שכל חבריהם סווגו אין אף אישה — {lst}.")


def insight_multi(multi):
    if multi.empty:
        return None
    top = int(multi["boards"].max())
    lead = multi[multi["boards"] == top]
    if top >= 3 and len(lead) <= 3:
        who = join_he(lead["person"].tolist())
        return (f"{n(len(multi))} אנשים מכהנים ביותר מדירקטוריון אחד; {who} מכהנים ב-"
                f"{n(top)} דירקטוריונים.") if len(lead) > 1 else (
                f"{n(len(multi))} אנשים מכהנים ביותר מדירקטוריון אחד; {who} מכהן/ת ב-"
                f"{n(top)} דירקטוריונים.")
    return (f"{n(len(multi))} אנשים מכהנים ביותר מדירקטוריון אחד — כל אחד מהם"
            f" בשני דירקטוריונים לכל היותר.") if top == 2 else (
            f"{n(len(multi))} אנשים מכהנים ביותר מדירקטוריון אחד, עד {n(top)} כל אחד.")


# ── main ─────────────────────────────────────────────────────────────────
def compute(frames):
    cdf = frames["companies"]
    ddf = frames["directors"]

    comp = pd.DataFrame({
        "company_full": cdf["COMPANY_NAME"].str.strip(),
        "status": cdf["STATUS"].str.strip().replace("", "לא צוין"),
        "office": cdf["GOVERMENT_OFFICE"].str.strip().replace("", "לא צוין"),
        "site": cdf["COMPANY_SITE"].str.strip() != "",
    })
    comp = comp[comp["company_full"] != ""].drop_duplicates("company_full")
    comp = comp.sort_values("company_full").reset_index(drop=True)

    d = pd.DataFrame({
        "company_full": ddf["COMPANY_NAME"].str.strip(),
        "role": ddf["ROLE"].str.strip(),
        "first": ddf["FIRST_NAME"].map(lambda s: re.sub(r"\s+", " ", s).strip()),
        "last": ddf["LAST_NAME"].map(lambda s: re.sub(r"\s+", " ", s).strip()),
    })
    d = d[(d["company_full"] != "") & (d["role"] != "") & ((d["first"] + d["last"]) != "")]
    d = d.drop_duplicates()
    d["person"] = (d["first"] + " " + d["last"]).str.strip()
    d["gender"] = d["first"].map(gender_of)
    d = d.sort_values(["company_full", "role", "person"]).reset_index(drop=True)

    comp["listed"] = comp["company_full"].isin(set(d["company_full"]))
    total = len(comp)
    listed = int(comp["listed"].sum())

    # Board members: distinct (company, person) among board roles.
    b = d[d["role"].isin(BOARD_ROLES)]
    members = (b.groupby(["company_full", "person"])
               .agg(roles=("role", lambda s: "|".join(sorted(set(s)))),
                    gender=("gender", "first"))
               .reset_index())
    members["is_chair"] = members["roles"].str.contains(CHAIR, regex=False)
    members["is_ext"] = members["roles"].str.contains(EXTERNAL, regex=False)
    members = members.merge(comp[["company_full", "office", "status"]],
                            on="company_full", how="left")
    members["office"] = members["office"].fillna("לא צוין")

    boards = (members.groupby("company_full")
              .agg(size=("person", "size"), has_chair=("is_chair", "any"),
                   external=("is_ext", "sum"))
              .reset_index())
    boards["company"] = boards["company_full"].map(short_name)
    boards = boards.sort_values(["size", "company_full"], ascending=[False, True]).reset_index(drop=True)

    ceo_companies = set(d[d["role"].str.startswith(CEO_PREFIX)]["company_full"])

    # ── status × listed ──
    statuses = _order(comp["status"], STATUS_ORDER)
    st_counts = comp["status"].value_counts().reindex(statuses).fillna(0).astype(int)
    st_sorted = _counts(comp["status"])
    st_listed = comp[comp["listed"]]["status"].value_counts()
    chart_status = {
        "names": statuses,
        "series": [
            {"name": "עם דירקטורים ברשימה", "color": "#0068f5",
             "data": [int(st_listed.get(s, 0)) for s in statuses]},
            {"name": "ללא דירקטורים ברשימה", "color": "#c3cfe7",
             "data": [int(st_counts[s] - st_listed.get(s, 0)) for s in statuses]},
        ],
    }
    tbl_status = [{"name": s, "count": n(st_counts[s]),
                   "listed": n(st_listed.get(s, 0)),
                   "share": pct_plain(st_counts[s] / total * 100, 1)} for s in statuses]

    # ── ministry × status ──
    off = _counts(comp["office"])
    top_off = list(off.index[:TOP_OFFICES])
    other_off = len(off) > TOP_OFFICES
    comp["office_b"] = comp["office"].where(comp["office"].isin(top_off), "אחר")
    off_names = top_off + (["אחר"] if other_off else [])
    ct = pd.crosstab(comp["office_b"], comp["status"]).reindex(index=off_names, columns=statuses).fillna(0).astype(int)
    chart_office = {
        "names": off_names,
        "series": [{"name": s, "color": STATUS_COLOR.get(s), "data": [int(v) for v in ct[s]]}
                   for s in statuses],
    }
    off_listed = comp.groupby("office_b")["listed"].sum()
    tbl_office = [{"name": o, "total": n(ct.loc[o].sum()), "listed": n(off_listed.get(o, 0)),
                   "vals": [n(ct.loc[o, s]) for s in statuses]} for o in off_names]
    other_note = ""
    if other_off:
        k = len(off) - TOP_OFFICES
        other_note = f' "אחר" מאחד {n(k)} משרדים נוספים.'

    # ── roles ──
    roles = _order(d["role"], ROLE_ORDER)
    rc = d["role"].value_counts()
    chart_roles = {"names": roles, "values": [int(rc.get(r, 0)) for r in roles]}
    tbl_roles = [{"name": r, "count": n(rc.get(r, 0))} for r in roles]

    # ── governance completeness ──
    nb = len(boards)
    g_chair = int(boards["has_chair"].sum())
    g_ext = int((boards["external"] > 0).sum())
    g_ceo = int(boards["company_full"].isin(ceo_companies).sum())
    gap_names = ['יו"ר מסומן', 'דירקטור חיצוני (דח"צ)', 'מנכ"ל רשום']
    gap_yes = [g_chair, g_ext, g_ceo]
    chart_gaps = {"names": gap_names, "series": [
        {"name": "יש", "color": "#0068f5", "data": gap_yes},
        {"name": "אין", "color": "#c3cfe7", "data": [nb - v for v in gap_yes]},
    ]}
    tbl_gaps = [{"name": nm, "yes": n(v), "no": n(nb - v)} for nm, v in zip(gap_names, gap_yes)]
    ceo_only = len(ceo_companies - set(boards["company_full"]))

    # ── top boards ──
    tb = boards.head(TOP_BOARDS)
    plain = []
    for _, r in tb.iterrows():
        plain.append(int(r["size"]) - int(r["has_chair"]) - int(r["external"]))
    chart_boards = {
        "names": tb["company"].tolist(), "full": tb["company_full"].tolist(),
        "series": [
            {"name": 'יו"ר', "color": "#0b3668", "data": [int(v) for v in tb["has_chair"]]},
            {"name": 'דח"צ', "color": "#5b9cf8", "data": [int(v) for v in tb["external"]]},
            {"name": "דירקטורים", "color": "#0068f5", "data": plain},
        ],
    }
    tbl_boards = [{"name": r["company"], "size": n(r["size"]), "ext": n(r["external"]),
                   "chair": "כן" if r["has_chair"] else "לא"} for _, r in tb.iterrows()]

    # ── size distribution ──
    size_names, size_vals = [], []
    for lo, hi in SIZE_BUCKETS:
        if hi is None:
            m = boards["size"] >= lo
            lab = f"{lo} ומעלה"
        else:
            m = (boards["size"] >= lo) & (boards["size"] <= hi)
            lab = str(lo) if lo == hi else f"{lo} עד {hi}"
        size_names.append(lab)
        size_vals.append(int(m.sum()))
    chart_size = {"names": [x.replace(" ", "\n", 1) for x in size_names], "values": size_vals}
    tbl_size = [{"name": a, "count": n(v)} for a, v in zip(size_names, size_vals)]

    # ── gender ──
    genders = [W, M, U]

    def gsplit(df):
        vc = df["gender"].value_counts()
        return [int(vc.get(g, 0)) for g in genders]

    role_groups = [('יו"ר', members[members["is_chair"]]),
                   ('דח"צ', members[members["is_ext"]]),
                   ("דירקטורים", members[~members["is_chair"] & ~members["is_ext"]])]
    ceo_rows = d[d["role"].str.startswith(CEO_PREFIX)].drop_duplicates(["company_full", "person"])
    role_groups.append(('מנכ"ל', ceo_rows))
    role_groups = [(nm, df) for nm, df in role_groups if len(df)]
    gr = {nm: gsplit(df) for nm, df in role_groups}
    chart_grole = {"names": [nm for nm, _ in role_groups], "series": [
        {"name": g, "color": G_COLOR[g],
         "data": [round(gr[nm][i] / sum(gr[nm]) * 100, 1) for nm, _ in role_groups],
         "counts": [gr[nm][i] for nm, _ in role_groups]}
        for i, g in enumerate(genders)]}
    tbl_grole = [{"name": nm, "vals": [n(v) for v in gr[nm]],
                  "share": pct_plain(gr[nm][0] / (gr[nm][0] + gr[nm][1]) * 100) if gr[nm][0] + gr[nm][1] else "—"}
                 for nm, _ in role_groups]

    gb = members.pivot_table(index="company_full", columns="gender", values="person",
                             aggfunc="count", fill_value=0)
    for g in genders:
        if g not in gb.columns:
            gb[g] = 0
    gb = gb[genders].reset_index().merge(boards[["company_full", "company", "size"]], on="company_full")
    gtop = gb.set_index("company_full").loc[tb["company_full"]].reset_index()
    chart_gboards = {"names": gtop["company"].tolist(), "series": [
        {"name": g, "color": G_COLOR[g], "data": [int(v) for v in gtop[g]]} for g in genders]}
    tbl_gboards = [{"name": r["company"], "vals": [n(r[g]) for g in genders]}
                   for _, r in gtop.iterrows()]

    go = members.pivot_table(index="office", columns="gender", values="person",
                             aggfunc="count", fill_value=0)
    for g in genders:
        if g not in go.columns:
            go[g] = 0
    go = go[genders]
    go["seats"] = go.sum(axis=1)
    go = go.reset_index().sort_values(["seats", "office"], ascending=[False, True])
    top_go = go.head(TOP_OFFICES)
    rest_go = go.iloc[TOP_OFFICES:]
    go_rows = [(r["office"], [int(r[g]) for g in genders]) for _, r in top_go.iterrows()]
    if len(rest_go):
        go_rows.append(("אחר", [int(rest_go[g].sum()) for g in genders]))
    chart_goffice = {"names": [o for o, _ in go_rows], "series": [
        {"name": g, "color": G_COLOR[g], "data": [v[i] for _, v in go_rows]}
        for i, g in enumerate(genders)]}
    tbl_goffice = [{"name": o, "seats": n(sum(v)), "vals": [n(x) for x in v],
                    "share": pct_plain(v[0] / (v[0] + v[1]) * 100) if v[0] + v[1] else "—"}
                   for o, v in go_rows]

    # ── multi-board directors ──
    pb = (members.groupby("person")
          .agg(boards=("company_full", "nunique"),
               companies=("company_full", lambda s: sorted(set(s)))))
    multi = pb[pb["boards"] > 1].reset_index().sort_values(["boards", "person"], ascending=[False, True])
    tbl_multi = [{"name": r["person"], "boards": n(r["boards"]),
                  "companies": " · ".join(short_name(c, 60) for c in r["companies"])}
                 for _, r in multi.head(20).iterrows()]

    # ── KPIs ──
    seats = len(members)
    people = int(members["person"].nunique())
    gm = members["gender"].value_counts()
    w, m_ = int(gm.get(W, 0)), int(gm.get(M, 0))
    unk = int(gm.get(U, 0))
    wshare = w / (w + m_) * 100 if w + m_ else 0.0
    g_ok = seats > 0 and unk / seats <= MAX_UNKNOWN
    cov = listed / total if total else 0
    kpis = {
        "companies": {"value": total, "display": n(total), "tone": "brand"},
        "listed": {"value": listed, "display": n(listed),
                   "tone": "ok" if cov >= 0.9 else ("warn" if cov >= 0.6 else "danger")},
        "seats": {"value": seats, "display": n(seats), "tone": "brand"},
        "women": {"value": round(wshare, 1), "display": pct_plain(wshare),
                  "tone": ("ok" if wshare >= 40 else ("warn" if wshare >= 25 else "danger")) if g_ok else "info"},
    }

    insights = []
    for iid, txt in [
        ("status", insight_status(st_sorted, total)),
        ("office", insight_office(off)),
        ("missing", insight_missing(comp)),
        ("biggest", insight_biggest(boards)),
        ("small", insight_small(boards)),
        ("gaps", insight_gaps(boards, ceo_companies)),
        ("gender", insight_gender(members)),
        ("chairs", insight_gender_chairs(members)),
        ("nowomen", insight_no_women(gb)),
        ("multi", insight_multi(multi)),
    ]:
        if txt:
            insights.append({"id": iid, "text_he": txt})

    sites = int(comp["site"].sum())
    lede = (f"משרד האוצר מפרסם את רשימת {n(total)} החברות הממשלתיות לפי סטטוס ומשרד מפקח,"
            f" לצד {n(len(d))} רשומות של נושאי משרה מכהנים."
            f" לאחר איחוד יושבי ראש שרשומים גם כדירקטורים, מדובר ב-{n(seats)} מושבי"
            f" דירקטוריון ב-{n(nb)} חברות, שבהם מכהנים {n(people)} אנשים."
            f" ל-{n(sites)} מהחברות רשום אתר אינטרנט.")
    summary = (f"רשימת {n(total)} החברות הממשלתיות בישראל לפי סטטוס ומשרד מפקח, והרכב"
               f" הדירקטוריונים של {n(nb)} מהן: {n(seats)} מושבים, יושבי ראש, דירקטורים"
               f" חיצוניים ושיעור הנשים המוערך ({pct(wshare)}).")

    labels = {
        "lede": lede,
        "listed_kpi": f"חברות עם דירקטורים ברשימה (מתוך {n(total)})",
        "seats_kpi": f"מושבי דירקטוריון ({n(people)} אנשים)",
        "women_kpi": "נשים בדירקטוריונים (הערכה לפי שם)" if g_ok else "נשים בדירקטוריונים (הערכה חלקית)",
        "status_note": (f"{n(total)} החברות לפי סטטוס משפטי, ולכל סטטוס — לכמה מהן רשומים"
                        f" דירקטורים מכהנים ({n(listed)} בסך הכול)."),
        "status_aria": f"תרשים עמודות: {n(total)} חברות לפי סטטוס, עם וללא דירקטורים ברשימה",
        "status_caption": "חברות לפי סטטוס",
        "office_note": (f"{n(len(off))} משרדים מפקחים על החברות; המובילים הם {off.index[0]}"
                        f" ({n(off.iloc[0])}) ו{off.index[1] if len(off) > 1 else ''}"
                        f" ({n(off.iloc[1]) if len(off) > 1 else ''}).{other_note}"),
        "office_aria": f"תרשים עמודות אופקי: חברות לפי {n(len(off))} משרדים, מחולק לפי סטטוס",
        "office_caption": "חברות לפי משרד מפקח וסטטוס",
        "roles_note": (f"{n(len(d))} רשומות לפי תפקיד. יו\"ר רשום גם כדירקטור, ולכן מושבי"
                       f" הדירקטוריון נספרים פעם אחת לכל אדם בחברה."),
        "roles_aria": f"תרשים עמודות: {n(len(d))} רשומות לפי {n(len(roles))} תפקידים",
        "roles_caption": "רשומות לפי תפקיד",
        "gaps_note": (f"בכמה מתוך {n(nb)} הדירקטוריונים שברשימה מסומן יו\"ר, מכהן דירקטור"
                      f" חיצוני ורשום מנכ\"ל." + (f" ל-{n(ceo_only)} חברות נוספות רשום מנכ\"ל"
                                                    " בלבד, ללא דירקטורים." if ceo_only else "")),
        "gaps_aria": f"תרשים עמודות אופקי: שלמות ההרכב ב-{n(nb)} דירקטוריונים",
        "gaps_caption": "שלמות הרכב הדירקטוריון",
        "boards_note": (f"{n(len(tb))} הדירקטוריונים הגדולים ברשימה; הגדול הוא של"
                        f" {tb['company'].iloc[0]} עם {n(tb['size'].iloc[0])} חברים."
                        if len(tb) else ""),
        "boards_aria": f"תרשים עמודות אופקי: {n(len(tb))} הדירקטוריונים הגדולים לפי מספר חברים",
        "boards_caption": "הדירקטוריונים הגדולים",
        "size_note": (f"מספר החברים בדירקטוריון בכל אחת מ-{n(nb)} החברות שיש להן דירקטורים"
                      f" ברשימה; החציון הוא {float(boards['size'].median()):.1f}".rstrip("0").rstrip(".")
                      + " חברים." if nb else ""),
        "size_aria": f"היסטוגרמה: {n(nb)} דירקטוריונים לפי גודל",
        "size_caption": "דירקטוריונים לפי מספר חברים",
        "grole_note": (f"שיעור הנשים לפי תפקיד, בהערכה לפי השם הפרטי; {n(unk)} מחברי"
                       f" הדירקטוריונים בעלי שמות שאינם חד-משמעיים לא סווגו."),
        "grole_aria": "תרשים עמודות אופקי מוערם: התפלגות מגדר לפי תפקיד, באחוזים",
        "grole_caption": "מגדר לפי תפקיד (הערכה)",
        "gboards_note": f"הרכב מגדרי מוערך ב-{n(len(gtop))} הדירקטוריונים הגדולים.",
        "gboards_aria": f"תרשים עמודות אופקי מוערם: נשים וגברים ב-{n(len(gtop))} הדירקטוריונים הגדולים",
        "gboards_caption": "מגדר בדירקטוריונים הגדולים (הערכה)",
        "goffice_note": (f"מושבי הדירקטוריון לפי המשרד המפקח על החברה, ושיעור הנשים בכל"
                         f" משרד (הערכה)." + (' "אחר" מאחד את שאר המשרדים.' if len(rest_go) else "")),
        "goffice_aria": "תרשים עמודות אופקי מוערם: מושבי דירקטוריון לפי משרד ומגדר",
        "goffice_caption": "מושבי דירקטוריון לפי משרד ומגדר (הערכה)",
        "multi_note": (f"{n(len(multi))} אנשים מכהנים ביותר מדירקטוריון אחד ברשימה"
                       + (f"; מוצגים {n(len(tbl_multi))} הראשונים." if len(multi) > len(tbl_multi) else ".")),
    }

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "registry",
            "suggested_tags": ["חברות ממשלתיות", "דירקטורים", "דירקטוריון",
                               "רשות החברות הממשלתיות", "ממשל תאגידי", "ייצוג נשים"],
            "related_ids": ["6b7c7138-0061-4166-96c0-5174cd54510f"],
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": {
            "status": chart_status, "office": chart_office, "roles": chart_roles,
            "gaps": chart_gaps, "boards": chart_boards, "size": chart_size,
            "grole": chart_grole, "gboards": chart_gboards, "goffice": chart_goffice,
        },
        "tables": {
            "status": tbl_status, "office": tbl_office, "status_cols": statuses,
            "roles": tbl_roles, "gaps": tbl_gaps, "boards": tbl_boards, "size": tbl_size,
            "grole": tbl_grole, "gboards": tbl_gboards, "goffice": tbl_goffice,
            "genders": genders, "multi": tbl_multi,
        },
        "flags": {"multi": bool(tbl_multi), "gender": seats > 0},
        "insights": insights,
        "labels": labels,
    }
