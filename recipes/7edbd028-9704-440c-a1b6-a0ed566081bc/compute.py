"""עמודי תאורה בבאר שבע — one row per street-light pole: pole number, the
switchboard (מרכזייה) that feeds it, LED-upgrade status, the nearest address
and a WGS84 point.

The page shows where the city stands on the LED replacement, how poles spread
over switchboards and streets, where they are dense, and where the register
itself has gaps.  Everything is an exact count (integers), so the output does
not depend on row order.  Pole numbers and addresses are asset data, not
personal data.
"""
import math
import re

import numpy as np
import pandas as pd

LAT_RANGE = (29.0, 34.0)
LON_RANGE = (34.0, 36.0)
PLACEHOLDER_MIN = 9999       # switchboard codes 0 and >= this are placeholders
TOP_BOARDS = 14              # bars on the per-switchboard LED chart
MIN_BOARD = 20               # poles a switchboard needs to count in board insights
TOP_STREETS = 12
TOP_STATUS = 8               # status labels shown; the rest become "אחר"
SIZE_BIN = 25                # poles per switchboard histogram bin
SIZE_BINS = 9                # last bin open-ended
GRID_STEP = 0.005            # degrees (~500 m) for the density grid
MAX_GRID = 40                # widen the step if a side would exceed this
MAX_BANDS = 10
BAND_SCALE = 100             # latitude bands of 0.01 degree (~1 km)
DONE_KEYS = ("קיים", "ששודרג", "שהוחלף")
PENDING_KEYS = ("להחלפה", "מתוכנן")
LEAD_MARGIN = 0.02           # street leader must beat runner-up by this share
GAP_MIN_SHARE = 0.01         # data gaps worth a sentence
NS_GAP_PTS = 0.10            # north/south LED-share gap needed to report
MIN_BAND = 200               # poles a latitude band needs to be compared
GROUP_LABELS = {"done": "LED קיים", "pend": "ממתין להחלפה", "oth": "פנסים אחרים",
                "unk": "ללא סטטוס"}
GROUP_COLORS = {"done": "#198754", "pend": "#9a6700", "oth": "#6c757d", "unk": "#c3cfe7"}


def _int(n):
    return f"{int(n):,}"


def _pct(x, digits=0):
    return f"{x * 100:.{digits}f}%"


def _group(label):
    s = label.strip()
    if not s:
        return "unk"
    if any(k in s for k in PENDING_KEYS):
        return "pend"
    if any(k in s for k in DONE_KEYS):
        return "done"
    return "oth"


def _street(addr):
    s = re.sub(r"[\s\d/\-\.]+$", "", addr.strip()).strip()
    return s


def _ranked(series):
    vc = series.value_counts()
    return vc.sort_index().sort_values(ascending=False, kind="stable")


def _prepare(df):
    out = df.copy()
    out["latf"] = pd.to_numeric(out["lat"].str.strip(), errors="coerce")
    out["lonf"] = pd.to_numeric(out["lon"].str.strip(), errors="coerce")
    ok = out["latf"].between(*LAT_RANGE) & out["lonf"].between(*LON_RANGE)
    n_bad = int((~ok).sum())
    out = out[ok].copy()
    out["pole"] = out["Lampost"].str.strip()
    out["status"] = out["LED"].str.strip()
    out["group"] = out["status"].map(_group)
    out["street"] = out["NearAddres"].map(_street)
    code = pd.to_numeric(out["centerligh"].str.strip(), errors="coerce")
    out["board"] = code
    out["real_board"] = code.notna() & (code > 0) & (code < PLACEHOLDER_MIN)
    out = out.sort_values(["board", "pole", "street", "status", "latf", "lonf"],
                          kind="stable")
    return out.reset_index(drop=True), n_bad


def _bands(values):
    idx = np.floor(np.asarray(values) * BAND_SCALE + 1e-9).astype(int)
    lo, hi = int(idx.min()), int(idx.max())
    w = max(1, math.ceil((hi - lo + 1) / MAX_BANDS))
    lo = (lo // w) * w
    edges = []
    for a in range(lo, hi + 1, w):
        edges.append((a, a + w, f"{a / BAND_SCALE:.2f}-{(a + w) / BAND_SCALE:.2f}"))
    return edges, idx


def _grid(df):
    """Counts per ~500 m cell. Returns (xs labels, ys labels north-first, cells,
    max count, densest cell info)."""
    lat, lon = df["latf"].to_numpy(), df["lonf"].to_numpy()
    step = GRID_STEP
    while (math.ceil((lat.max() - lat.min()) / step) + 1 > MAX_GRID
           or math.ceil((lon.max() - lon.min()) / step) + 1 > MAX_GRID):
        step *= 2
    la0, lo0 = math.floor(lat.min() / step) * step, math.floor(lon.min() / step) * step
    iy = np.floor((lat - la0) / step + 1e-9).astype(int)
    ix = np.floor((lon - lo0) / step + 1e-9).astype(int)
    ny, nx = int(iy.max()) + 1, int(ix.max()) + 1
    counts = np.zeros((ny, nx), dtype=int)
    np.add.at(counts, (iy, ix), 1)
    xs = [f"{lo0 + i * step:.3f}" for i in range(nx)]
    ys = [f"{la0 + j * step:.3f}" for j in range(ny)]
    cells = [[i, j, int(counts[j, i])] for j in range(ny) for i in range(nx) if counts[j, i]]
    best = None
    for j in range(ny):
        for i in range(nx):
            c = int(counts[j, i])
            if c and (best is None or c > best[0]):
                best = (c, j, i)
    return xs, ys, cells, step, best, int((counts > 0).sum())


def insight_led_share(g, total):
    done, pend = g.get("done", 0), g.get("pend", 0)
    if total == 0 or done == 0:
        return None
    return (f"{_pct(done / total, 1)} מעמודי התאורה ({_int(done)} מתוך {_int(total)}) כבר עם פנס LED, "
            f"ואילו {_int(pend)} עמודים ({_pct(pend / total, 1)}) ממתינים להחלפה.")


def insight_stage(status_counts):
    pend = [(s, c) for s, c in status_counts.items() if _group(s) == "pend"]
    if len(pend) < 2:
        return None
    pend.sort(key=lambda r: (-r[1], r[0]))
    tot = sum(c for _, c in pend)
    top = pend[0]
    if top[1] / tot < 0.4:
        return None
    return (f"בין העמודים הממתינים להחלפה, הקבוצה הגדולה ביותר היא {top[0]}, "
            f"עם {_int(top[1])} עמודים ({_pct(top[1] / tot)} מכלל הממתינים).")


def insight_board_top(boards, total_real):
    if len(boards) < 3 or total_real == 0:
        return None
    code, n = boards[0]
    return (f"המרכזייה הגדולה ביותר היא {code}: {_int(n)} עמודים, {_pct(n / total_real, 1)} "
            f"מהעמודים ששויכו למרכזייה, מתוך {_int(len(boards))} מרכזיות.")


def insight_board_done(big):
    if len(big) < 5:
        return None
    full = [b for b in big if b["done"] == b["n"]]
    if not full:
        return None
    return (f"{_int(len(full))} מתוך {_int(len(big))} המרכזיות עם {_int(MIN_BOARD)} עמודים ומעלה "
            f"כבר עברו הסבה מלאה ל-LED: בכל עמוד שלהן יש פנס LED.")


def insight_board_pending(big):
    cand = [b for b in big if b["pend"] > 0]
    if len(big) < 5 or not cand:
        return None
    w = sorted(cand, key=lambda b: (-b["pend"], b["code"]))[0]
    if w["pend"] / w["n"] < 0.5:
        return None
    return (f"במרכזייה {w['code']} {_int(w['pend'])} מתוך {_int(w['n'])} עמודים ({_pct(w['pend'] / w['n'])}) "
            f"עדיין ממתינים להחלפה — המספר הגדול ביותר של עמודים ממתינים במרכזייה אחת.")


def insight_street_top(streets, total_streeted):
    if len(streets) < 2:
        return None
    a, b = streets.iloc[0], streets.iloc[1]
    if (a - b) / max(total_streeted, 1) < LEAD_MARGIN:
        return None
    return (f"ברחוב {streets.index[0]} הכי הרבה עמודים: {_int(a)} ({_pct(a / total_streeted, 1)} "
            f"מהעמודים עם כתובת קרובה), לעומת {_int(b)} ברחוב {streets.index[1]}.")


def insight_street_share(streets, total_streeted):
    if len(streets) < TOP_STREETS:
        return None
    top = int(streets.iloc[:10].sum())
    return (f"עשרת הרחובות עם הכי הרבה עמודים מכילים {_pct(top / total_streeted)} מהעמודים "
            f"שיש להם כתובת קרובה, מתוך {_int(len(streets))} רחובות.")


def insight_density(best, step_m, cells_n):
    if best is None or cells_n < 5:
        return None
    return (f"התאים הצפופים ביותר במפה הם ריבועים של כ-{_int(step_m)} מטרים עם עד {_int(best[0])} עמודים, "
            f"בעוד שבסך הכול {_int(cells_n)} תאים מכילים עמודים.")


def insight_north_south(rows):
    ok = [r for r in rows if r["n"] >= MIN_BAND]
    if len(ok) < 3:
        return None
    hi = sorted(ok, key=lambda r: (-r["share"], r["label"]))[0]
    lo = sorted(ok, key=lambda r: (r["share"], r["label"]))[0]
    if hi["share"] - lo["share"] < NS_GAP_PTS:
        return None
    return (f"שיעור ה-LED שונה בין אזורי העיר: ברצועת קו הרוחב {hi['label']} הוא {_pct(hi['share'])}, "
            f"וברצועה {lo['label']} רק {_pct(lo['share'])}.")


def insight_quality(n_nopole, n_noaddr, n_dup, total):
    parts = []
    if n_nopole / total >= GAP_MIN_SHARE:
        parts.append(f"{_int(n_nopole)} בלי מספר עמוד")
    if n_noaddr / total >= GAP_MIN_SHARE:
        parts.append(f"{_int(n_noaddr)} בלי כתובת קרובה")
    if n_dup / total >= GAP_MIN_SHARE:
        parts.append(f"{_int(n_dup)} עם מספר עמוד שחוזר באותה מרכזייה")
    if not parts:
        return None
    return "פערים במאגר עצמו: " + "; ".join(parts) + "."


def insight_placeholder(n_ph, total):
    if n_ph / total < GAP_MIN_SHARE:
        return None
    return (f"{_int(n_ph)} עמודים ({_pct(n_ph / total, 1)}) רשומים עם קוד מרכזייה זמני "
            f"(אפס או {_int(PLACEHOLDER_MIN)} ומעלה) ולכן אינם משויכים למרכזייה אמיתית; "
            f"הם לא נכללים בניתוחי המרכזיות.")


def compute(frames):
    df, n_bad = _prepare(frames["poles"])
    total = len(df)
    g = df["group"].value_counts().to_dict()
    done, pend = int(g.get("done", 0)), int(g.get("pend", 0))
    n_oth, n_unk = int(g.get("oth", 0)), int(g.get("unk", 0))

    # ---- status chart
    sc = _ranked(df["status"].replace("", "ללא סטטוס"))
    top = sc.head(TOP_STATUS)
    rest = int(sc.iloc[TOP_STATUS:].sum())
    s_names = list(top.index)
    s_vals = [int(v) for v in top]
    s_cols = [GROUP_COLORS[_group("" if n == "ללא סטטוס" else n)] for n in s_names]
    if rest:
        s_names.append("סטטוסים אחרים")
        s_vals.append(rest)
        s_cols.append(GROUP_COLORS["oth"])
    t_status = [{"name": n, "count": _int(v), "share": _pct(v / total, 1)}
                for n, v in zip(s_names, s_vals)]
    status_counts = {k: int(v) for k, v in df.loc[df["status"] != "", "status"].value_counts().items()}

    # ---- switchboards
    rb = df[df["real_board"]]
    n_ph = int((~df["real_board"]).sum())
    per = rb.groupby("board").agg(n=("pole", "size")).reset_index()
    gcounts = rb.groupby(["board", "group"]).size().unstack(fill_value=0)
    boards = []
    for _, r in per.iterrows():
        code = int(r["board"])
        row = gcounts.loc[r["board"]]
        boards.append({"code": code, "n": int(r["n"]),
                       "done": int(row.get("done", 0)), "pend": int(row.get("pend", 0)),
                       "other": int(row.get("oth", 0) + row.get("unk", 0))})
    boards.sort(key=lambda b: (-b["n"], b["code"]))
    big = [b for b in boards if b["n"] >= MIN_BOARD]
    tb = boards[:TOP_BOARDS]
    boards_chart = {"names": [f"מרכזייה {b['code']}" for b in tb],
                    "done": [b["done"] for b in tb], "pend": [b["pend"] for b in tb],
                    "other": [b["other"] for b in tb]}
    t_boards = [{"name": f"מרכזייה {b['code']}", "n": _int(b["n"]), "done": _int(b["done"]),
                 "pend": _int(b["pend"]), "share": _pct(b["done"] / b["n"])} for b in tb]
    sizes = np.array([b["n"] for b in boards]) if boards else np.array([], dtype=int)
    if len(sizes):
        bi = np.minimum(sizes // SIZE_BIN, SIZE_BINS - 1)
        size_vals = [int((bi == i).sum()) for i in range(SIZE_BINS)]
        size_names = [f"{i * SIZE_BIN + 1}-{(i + 1) * SIZE_BIN}" for i in range(SIZE_BINS - 1)]
        size_names.append(f"מעל {(SIZE_BINS - 1) * SIZE_BIN}")
        median_board = int(round(float(np.median(sizes))))
    else:
        size_vals, size_names, median_board = [], [], 0
    t_size = [{"name": n, "count": _int(v), "share": _pct(v / len(boards), 1)}
              for n, v in zip(size_names, size_vals)] if boards else []

    # ---- streets
    st = df.loc[df["street"] != "", "street"]
    streets = _ranked(st)
    ts = streets.head(TOP_STREETS)
    streets_chart = {"names": list(ts.index), "values": [int(v) for v in ts]}
    t_streets = [{"name": n, "count": _int(v), "share": _pct(v / max(len(st), 1), 1)}
                 for n, v in zip(streets_chart["names"], streets_chart["values"])]

    # ---- density grid
    xs, ys, cells, step, best, cells_n = _grid(df)
    step_m = int(round(step * 111320 / 50.0) * 50)
    grid_chart = {"x": xs, "y": ys[::-1],
                  "cells": [[i, len(ys) - 1 - j, c] for i, j, c in cells],
                  "max": max([c[2] for c in cells], default=0)}

    # ---- latitude bands (north first) with LED mix
    edges, idx = _bands(df["latf"].to_numpy())
    grp = df["group"].to_numpy()
    lat_rows = []
    for a, b, label in edges:
        m = (idx >= a) & (idx < b)
        n = int(m.sum())
        d_ = int((m & (grp == "done")).sum())
        p_ = int((m & (grp == "pend")).sum())
        lat_rows.append({"label": label, "n": n, "done": d_, "pend": p_,
                         "other": n - d_ - p_, "share": d_ / n if n else 0.0})
    lat_rows = lat_rows[::-1]
    lat_chart = {"names": [r["label"] for r in lat_rows], "done": [r["done"] for r in lat_rows],
                 "pend": [r["pend"] for r in lat_rows], "other": [r["other"] for r in lat_rows]}
    t_lat = [{"name": r["label"], "n": _int(r["n"]), "done": _int(r["done"]),
              "share": _pct(r["share"])} for r in lat_rows]

    # ---- data quality
    pole_blank = df["pole"] == ""
    n_nopole = int(pole_blank.sum())
    n_noaddr = int((df["street"] == "").sum())
    keyed = df[df["real_board"] & ~pole_blank]
    n_dup = int(keyed.duplicated(["board", "pole"]).sum())
    quality = [("בלי מספר עמוד", n_nopole), ("בלי כתובת קרובה", n_noaddr),
               ("בלי סטטוס LED", n_unk), ("קוד מרכזייה זמני", n_ph),
               ("מספר עמוד שחוזר במרכזייה", n_dup)]
    quality.sort(key=lambda r: (-r[1], r[0]))
    quality_chart = {"names": [n for n, _ in quality], "values": [v for _, v in quality]}
    t_quality = [{"name": n, "count": _int(v), "share": _pct(v / total, 1)} for n, v in quality]

    rules = [
        ("led-share", insight_led_share(g, total)),
        ("stage", insight_stage(status_counts)),
        ("board-top", insight_board_top([(b["code"], b["n"]) for b in boards], len(rb))),
        ("board-done", insight_board_done(big)),
        ("board-pending", insight_board_pending(big)),
        ("street-top", insight_street_top(streets, len(st))),
        ("street-share", insight_street_share(streets, len(st))),
        ("density", insight_density(best, step_m, cells_n)),
        ("north-south", insight_north_south(lat_rows)),
        ("quality", insight_quality(n_nopole, n_noaddr, n_dup, total)),
        ("placeholder", insight_placeholder(n_ph, total)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    share = done / total if total else 0
    kpis = {
        "total": {"value": total, "display": _int(total), "tone": "brand",
                  "label": "עמודי תאורה במאגר"},
        "led-share": {"value": share, "display": _pct(share, 1),
                      "tone": "ok" if share >= 0.75 else "info" if share >= 0.5 else "warn",
                      "label": "מהעמודים כבר עם פנס LED"},
        "pending": {"value": pend, "display": _int(pend),
                    "tone": "warn" if pend / max(total, 1) >= 0.25 else "brand",
                    "label": "עמודים הממתינים להחלפה ל-LED"},
        "boards": {"value": len(boards), "display": _int(len(boards)), "tone": "brand",
                   "label": "מרכזיות תאורה"},
        "streets": {"value": int(streets.size), "display": _int(streets.size), "tone": "brand",
                    "label": "רחובות שונים בכתובות הקרובות"},
    }

    bad_note = f" {_int(n_bad)} רשומות בלי קואורדינטות תקינות לא נכללו." if n_bad else ""
    labels = {
        "lede": (f"{_int(total)} עמודי תאורה ברחבי באר שבע, כל אחד עם מרכזייה, כתובת קרובה, סטטוס שדרוג "
                 f"לפנס LED ונקודה על המפה. {_pct(share, 1)} מהם כבר עם LED.{bad_note}"),
        "map_note": (f"כל {_int(total)} העמודים על המפה. לחצו על אשכול כדי להתקרב, ועל סמן כדי "
                     f"לראות את מספר העמוד, המרכזייה והסטטוס."),
        "status_note": "מספר העמודים בכל סטטוס שדרוג. ירוק הוא פנס LED קיים, צהוב ממתין להחלפה, אפור פנסים אחרים.",
        "status_aria": f"תרשים עמודות אופקי: עמודים לפי סטטוס LED, {len(s_names)} סטטוסים.",
        "status_caption": "מספר עמודי התאורה לפי סטטוס LED.",
        "boards_note": (f"{_int(len(tb))} המרכזיות הגדולות ביותר, עם חלוקה לעמודים שכבר עם LED, ממתינים "
                        f"ואחרים. סך הכול {_int(len(boards))} מרכזיות."),
        "boards_aria": f"תרשים עמודות אופקי מוערם: מצב ה-LED ב-{len(tb)} המרכזיות הגדולות.",
        "boards_caption": "עמודים ושיעור LED בכל אחת מהמרכזיות הגדולות.",
        "size_note": (f"כמה מרכזיות יש לפי מספר העמודים שלהן, בקבוצות של {_int(SIZE_BIN)}. "
                      f"החציון הוא {_int(median_board)} עמודים למרכזייה."),
        "size_aria": f"תרשים עמודות: התפלגות גודל המרכזיות, {len(size_names)} קבוצות.",
        "size_caption": "מספר המרכזיות לפי מספר העמודים.",
        "streets_note": (f"הרחובות בעלי המספר הגדול ביותר של עמודים, לפי הכתובת הקרובה בלי מספר הבית. "
                         f"{_int(len(st))} עמודים כוללים כתובת."),
        "streets_aria": f"תרשים עמודות אופקי: {len(ts)} הרחובות עם הכי הרבה עמודי תאורה.",
        "streets_caption": "עמודי תאורה לפי רחוב.",
        "density_note": (f"מפת חום של צפיפות העמודים בריבועים של כ-{_int(step_m)} מטרים. "
                         f"{_int(cells_n)} ריבועים מכילים עמודים; הכהים צפופים יותר."),
        "density_aria": f"מפת חום: צפיפות עמודי התאורה ב-{_int(cells_n)} ריבועים.",
        "lat_note": "מצב ה-LED בכל רצועת קו רוחב, מהצפון (למעלה) לדרום.",
        "lat_aria": f"תרשים עמודות אופקי מוערם: מצב LED ב-{len(lat_rows)} רצועות קו רוחב.",
        "lat_caption": "עמודים ושיעור LED לפי רצועת קו רוחב, מצפון לדרום.",
        "quality_note": "כמה רשומות חסרות שדה או חשודות כמשוכפלות. ככל שהעמודה קצרה, המאגר מלא יותר.",
        "quality_aria": f"תרשים עמודות אופקי: {len(quality)} סוגי פערים במאגר.",
        "quality_caption": "מספר הרשומות לפי סוג הפער.",
    }

    return {
        "agent_data": {
            "summary_he": (f"{_int(total)} עמודי תאורה בבאר שבע, {_pct(share, 1)} מהם עם פנס LED, "
                           f"ב-{_int(len(boards))} מרכזיות, עם מפה ומצב השדרוג בכל אזור."),
            "dataset_kind": "map",
            "suggested_tags": ["תאורה", "תאורת רחוב", "LED", "באר שבע", "תשתיות עירוניות"],
            "spatial_coverage": "באר שבע",
            "related_ids": ["82a30a97-01b0-4281-854c-c7931f3445c0",
                            "bdf28cc0-680a-415c-af64-944a58079b2f",
                            "727e865d-25b1-43ce-9dcb-af297851f87b",
                            "57a5938f-65cc-48a8-bcfb-8d383e646aaa",
                            "5944b454-751c-4604-94d6-e676d7d34612"],
        },
        "kpis": kpis,
        "charts": {"status": {"names": s_names, "values": s_vals, "colors": s_cols},
                   "boards": boards_chart,
                   "size": {"names": size_names, "values": size_vals},
                   "streets": streets_chart, "density": grid_chart,
                   "lat": lat_chart, "quality": quality_chart},
        "tables": {"status": t_status, "boards": t_boards, "size": t_size,
                   "streets": t_streets, "lat": t_lat, "quality": t_quality},
        "insights": insights,
        "has_boards": bool(tb),
        "has_size": bool(size_vals),
        "has_streets": bool(len(ts)),
        "has_density": bool(cells),
        "labels": labels,
    }
