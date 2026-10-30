"""מערכת בטיחות ברכב: the licence plates of vehicles that qualify for a
licence-fee (אגרת רישוי) discount after installing a safety system.

The file is a full snapshot (every row carries the same update timestamp
today) with two columns: the plate and the update time. Plates are lookup
identifiers, so the page never shows one: it aggregates them by length
(7 vs 8 digits), by leading digit (the plate "series") and by blocks of
100,000 numbers. "As of" is the latest update time in the data.
"""
import pandas as pd

MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]
BLOCK = 100_000          # fine-histogram block size, 7-digit plates
MIN_BLOCKS = 10          # fewer populated blocks: no density insight
MIN_SERIES = 3           # fewer series: no leader/laggard insight


def _int(n):
    return f"{int(n):,}"


def _pct(x):
    """Percent with enough decimals that a share below 100% never shows as
    100.0% (and a non-zero one never as 0.0%)."""
    for digits in (1, 2, 3, 4):
        s = f"{x * 100:.{digits}f}"
        if (x < 1 and float(s) >= 100) or (x > 0 and float(s) == 0):
            continue
        return s + "%"
    return f"{x * 100:.4f}%"


def _d_he(ts):
    return f"{ts.day} ב{MONTHS_HE[ts.month - 1]} {ts.year}"


def _prepare(df):
    raw = df["mispar_rechev"].str.strip().str.replace(r"[\s\-]", "", regex=True)
    num = pd.to_numeric(raw.where(raw.str.fullmatch(r"\d+")), errors="coerce")
    upd = pd.to_datetime(df["updated_dt"].str.strip().str.slice(0, 19),
                         format="%Y-%m-%d %H:%M:%S", errors="coerce")
    out = pd.DataFrame({"n": num, "upd": upd})
    bad = int(out["n"].isna().sum() + (out["n"] <= 0).sum())
    out = out[out["n"] > 0].copy()
    out["n"] = out["n"].astype("int64")
    out["len"] = out["n"].astype(str).str.len()
    return out.reset_index(drop=True), bad


def _series_range(length, lead):
    step = 10 ** (length - 1)
    return lead * step, (lead + 1) * step - 1


def _series_axis(length, lead):
    lo, hi = _series_range(length, lead)
    if lo >= 1_000_000 or (hi + 1) >= 1_000_000:
        return f"{lo / 1e6:g}-{(hi + 1) / 1e6:g} מיליון"
    return f"{lo:,}-{hi:,}"


def insight_volume(vehicles, as_of):
    when = f", נכון לעדכון מ-{_d_he(as_of)}" if as_of is not None else ""
    return (f"ברשימה {_int(vehicles)} כלי רכב שעומדים בתנאים להנחה באגרת הרישוי "
            f"בזכות התקנת מערכת בטיחות{when}.")


def insight_series(series_rows, length):
    rows = [r for r in series_rows if r["length"] == length]
    if len(rows) < MIN_SERIES:
        return None
    top = max(rows, key=lambda r: (r["count"], -r["lead"]))
    low = min(rows, key=lambda r: (r["count"], r["lead"]))
    if top["count"] == low["count"]:
        return None
    total = sum(r["count"] for r in rows)
    return (f"מבין מספרי הרישוי בני {length} ספרות, הסדרה הגדולה ברשימה היא "
            f"{top['lo']:,} עד {top['hi']:,} ({_int(top['count'])} רכבים, "
            f"{_pct(top['count'] / total)}), והקטנה היא {low['lo']:,} עד {low['hi']:,} "
            f"({_int(low['count'])}, {_pct(low['count'] / total)}).")


def insight_blocks(counts):
    populated = counts[counts > 0]
    if len(populated) < MIN_BLOCKS:
        return None
    med = float(populated.median())
    top_b = int(populated.sort_index().idxmax())
    low_b = int(populated.sort_index().idxmin())
    if med <= 0 or populated.max() == populated.min():
        return None
    ratio = populated.max() / med
    return (f"הצפוף ביותר הוא גוש המספרים {top_b * BLOCK:,} עד {(top_b + 1) * BLOCK - 1:,} "
            f"עם {_int(populated.max())} רכבים, פי {ratio:.1f} מהגוש החציוני "
            f"({_int(round(med))}); הדליל ביותר, {low_b * BLOCK:,} עד "
            f"{(low_b + 1) * BLOCK - 1:,}, מונה {_int(populated.min())} בלבד.")


def insight_eight(by_len, vehicles):
    n8 = int(by_len.get(8, 0))
    if n8 == 0:
        return None
    share = n8 / vehicles
    if n8 == 1:
        return (f"רק רכב אחד ברשימה ({_pct(share)}) נושא מספר רישוי בן 8 ספרות, "
                "שניתן לרכבים שנרשמו בשנים האחרונות; כמעט כל הזכאים הם רכבים "
                "עם מספר רישוי ותיק בן 7 ספרות.")
    if share < 0.01:
        return (f"רק {_int(n8)} מהרכבים ברשימה ({_pct(share)}) נושאים מספר רישוי בן 8 ספרות, "
                "שניתן לרכבים שנרשמו בשנים האחרונות; כמעט כל הזכאים הם רכבים "
                "עם מספר רישוי ותיק בן 7 ספרות.")
    return (f"{_int(n8)} מהרכבים ברשימה ({_pct(share)}) נושאים מספר רישוי בן 8 ספרות, "
            "שניתן לרכבים שנרשמו בשנים האחרונות.")


def insight_dupes(rows, vehicles):
    extra = rows - vehicles
    if extra <= 0:
        return None
    return (f"{_int(extra)} שורות ברשימה חוזרות על מספר רישוי שכבר מופיע בה; "
            f"הנתונים בדף סופרים כל רכב פעם אחת ({_int(vehicles)} רכבים).")


def insight_updates(df):
    d = df["upd"].dropna().dt.normalize()
    if d.empty:
        return None
    days = d.value_counts()
    if len(days) == 1:
        return (f"לכל {_int(len(df))} הרשומות אותו מועד עדכון, {_d_he(days.index[0])}: "
                "הרשימה מתפרסמת כתמונת מצב מלאה ולא כתוספות.")
    last = d.max()
    return (f"הרשומות נושאות {_int(len(days))} מועדי עדכון שונים, מ-{_d_he(d.min())} "
            f"עד {_d_he(last)}; {_pct(int(days[last]) / len(d))} מהן עודכנו במועד האחרון.")


def compute(frames):
    src = frames["eligible"]
    df, bad = _prepare(src)
    rows = len(df)
    uniq = df.drop_duplicates("n").sort_values("n", kind="mergesort").reset_index(drop=True)
    vehicles = len(uniq)
    as_of = df["upd"].max() if df["upd"].notna().any() else None

    # Plate length.
    by_len = uniq["len"].value_counts().sort_index()
    len_rows = [{"name": f"{int(L)} ספרות", "count": _int(c), "share": _pct(c / vehicles)}
                for L, c in by_len.items()]
    length_chart = {"names": [f"{int(L)} ספרות" for L in by_len.index],
                    "values": [int(c) for c in by_len.values]}

    # Series: plate length x leading digit.
    lead = uniq["n"] // (10 ** (uniq["len"] - 1))
    grp = (pd.DataFrame({"len": uniq["len"], "lead": lead}).groupby(["len", "lead"]).size()
           .sort_index())
    series_rows = []
    for (L, d), c in grp.items():
        lo, hi = _series_range(int(L), int(d))
        series_rows.append({"length": int(L), "lead": int(d), "lo": lo, "hi": hi,
                            "count": int(c)})
    series_chart = {"names": [_series_axis(r["length"], r["lead"]) for r in series_rows],
                    "values": [r["count"] for r in series_rows]}
    series_table = [{"name": f"{r['lo']:,} עד {r['hi']:,}", "len": f"{r['length']} ספרות",
                     "count": _int(r["count"]), "share": _pct(r["count"] / vehicles)}
                    for r in series_rows]

    # 100,000-number blocks of 7-digit plates.
    seven = uniq.loc[uniq["len"] == 7, "n"]
    blk = (seven // BLOCK).value_counts()
    blk = blk.reindex(range(10, 100), fill_value=0)   # 1,000,000..9,999,999
    blocks_chart = {"x": [f"{b * BLOCK / 1e6:.1f}" for b in blk.index],
                    "y": [int(v) for v in blk.values],
                    "starts": [f"{b * BLOCK:,}" for b in blk.index]}
    main_len = int(by_len.idxmax()) if len(by_len) else 7

    n7 = int(by_len.get(7, 0))
    n8 = int(by_len.get(8, 0))
    seven_share = n7 / vehicles if vehicles else 0.0

    rules = [
        ("volume", insight_volume(vehicles, as_of)),
        ("series", insight_series(series_rows, main_len)),
        ("blocks", insight_blocks(blk)),
        ("eight", insight_eight(by_len, vehicles)),
        ("dupes", insight_dupes(rows, vehicles)),
        ("updates", insight_updates(df)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    main_rows = [r for r in series_rows if r["length"] == main_len]
    main_total = sum(r["count"] for r in main_rows)
    series_lede = (f"הספרה הראשונה במספר הרישוי קובעת את הסדרה. הרכבים עם מספר בן "
                   f"{main_len} ספרות מתחלקים בין {_int(len(main_rows))} סדרות, בממוצע "
                   f"{_int(round(main_total / len(main_rows)))} רכבים לסדרה; סך הכול "
                   f"{_int(len(series_rows))} סדרות בכל האורכים."
                   if main_rows else "אין ברשימה מספרי רישוי תקינים.")
    populated = int((blk > 0).sum())
    if len(seven):
        half_block = int(seven.quantile(0.5, interpolation="lower")) // BLOCK * BLOCK
        blocks_lede = (f"כל עמודה היא גוש של מאה אלף מספרי רישוי בני שבע ספרות; "
                       f"{_int(populated)} מתוך {_int(len(blk))} הגושים מאוכלסים. "
                       f"כמחצית מהרכבים האלה נמצאים בגושים שמתחת ל-{half_block + BLOCK:,}.")
    else:
        blocks_lede = "אין ברשימה מספרי רישוי בני שבע ספרות."
    length_lede = (f"ברשימה {_int(n7)} רכבים עם מספר רישוי בן שבע ספרות ו-{_int(n8)} "
                   "עם מספר בן שמונה ספרות, הניתן לרכבים שנרשמו בשנים האחרונות.")

    as_of_txt = _d_he(as_of) if as_of is not None else None
    dropped = (f" {_int(bad)} שורות ללא מספר רישוי תקין אינן נספרות." if bad else "")
    lede = (f"משרד התחבורה מפרסם את רשימת מספרי הרישוי של {_int(vehicles)} כלי רכב "
            "שעומדים בתנאים לקבלת הנחה באגרת הרישוי (האגרה השנתית לחידוש רישיון הרכב) בגין התקנת מערכת "
            "בטיחות" + (f", נכון לעדכון מ-{as_of_txt}." if as_of_txt else ".")
            + " הדף מציג את הרשימה במצטבר בלבד, לפי אורך מספר הרישוי וסדרת המספרים; "
            "לבדיקת רכב מסוים חפשו את מספר הרישוי שלו בחיפוש שבהמשך הדף." + dropped)

    summary = (f"בדיקת זכאות להנחה באגרת הרישוי בזכות מערכת בטיחות ברכב, לפי מספר רישוי: "
               f"{_int(vehicles)} רכבים זכאים"
               + (f", עדכון {as_of.strftime('%d.%m.%Y')}." if as_of is not None else "."))

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "registry",
            "related_ids": [
                "273c5e33-25ab-4980-8522-a2f7ba0bb62d",
                "0f16b39a-6016-408d-805d-31f40d5a0990",
                "11369651-1c70-4d8f-8090-ee49354a7c52",
                "1c8e79c5-0ddb-461f-84ea-5bdcbaefaef4",
                "35c791ca-8db2-4657-8c6f-eb092147a6bb",
            ],
            "suggested_tags": ["כלי רכב", "בטיחות בדרכים", "אגרת רישוי", "הנחות",
                               "מערכות בטיחות"],
            "spatial_coverage": "ישראל",
        },
        "kpis": {
            "vehicles": {"value": vehicles, "display": _int(vehicles), "tone": "brand"},
            "seven_share": {"value": round(seven_share, 6), "display": _pct(seven_share),
                            "tone": "brand"},
            "eight": {"value": n8, "display": _int(n8), "tone": "info"},
            "as_of": {"value": as_of.strftime("%Y-%m-%d") if as_of is not None else None,
                      "display": as_of.strftime("%d.%m.%Y") if as_of is not None else "לא צוין",
                      "tone": "brand"},
        },
        "charts": {
            "series": series_chart,
            "blocks": blocks_chart,
            "length": length_chart,
        },
        "tables": {
            "series": series_table,
            "length": len_rows,
        },
        "insights": insights,
        "labels": {
            "lede": lede,
            "series_lede": series_lede,
            "series_aria": "תרשים עמודות: רכבים זכאים לפי סדרת מספר הרישוי (הספרה הראשונה).",
            "blocks_lede": blocks_lede,
            "blocks_aria": ("תרשים עמודות: רכבים זכאים עם מספר רישוי בן שבע ספרות, "
                            "לפי גושים של מאה אלף מספרים."),
            "length_lede": length_lede,
            "length_aria": "תרשים עמודות: רכבים זכאים לפי אורך מספר הרישוי.",
        },
    }
