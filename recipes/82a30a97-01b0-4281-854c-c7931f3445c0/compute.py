"""Be'er Sheva street names — registry of streets, squares, parks by theme group,
neighbourhood and type. Every number is computed here; rules return None when
their premise does not hold."""
import re
import pandas as pd

TOP_GROUPS = 12
TOP_HOODS = 15
MIX_HOODS = 12
MIX_GROUPS = 6
TOP_TYPES = 8
TOP_TITLES = 8
MIN_GROUP_N = 20
MIN_HOOD_N = 20
PREFIX = re.compile(r"^[א-ת]{1,3}\.\s*")
ALIAS = {"תרבות": "תרבות ומדע"}
OTHER = "אחר"


def _int(n):
    return f"{int(n):,}"


def _pct(x):
    return f"{x * 100:.1f}%"


def _group(v):
    v = PREFIX.sub("", str(v).strip())
    if v.startswith("מועצה"):  # approval-note text, not a theme group
        return ""
    return ALIAS.get(v, v)


def _hood(v):
    v = str(v).strip()
    if re.fullmatch(r"[א-ת]{1,2}", v):
        return f"שכונה {v}"
    return v


def _title(v):
    return re.sub(r"\s+", " ", str(v).replace("’", "'").strip())


def _counts(s):
    vc = s.value_counts()
    return vc.sort_index().sort_values(ascending=False, kind="stable")


def _top_other(vc, n):
    top = vc.iloc[:n]
    names = list(top.index)
    vals = [int(v) for v in top]
    rest = int(vc.iloc[n:].sum())
    if rest > 0:
        names.append(OTHER)
        vals.append(rest)
    return names, vals


def _prepare(df):
    d = pd.DataFrame({
        "name": df["שם ראשי"].str.strip(),
        "title": df["תואר"].map(_title),
        "second": df["שם מישני"].str.strip(),
        "group": df["קבוצה"].map(_group),
        "extra": df["קבוצה נוספת"].map(_group),
        "type": df["סוג"].str.strip().replace("", "לא צוין"),
        "code": pd.to_numeric(df["קוד"].str.replace(",", ""), errors="coerce"),
        "hood": df["שכונה"].map(_hood),
    })
    d = d[d["name"] != ""]
    d["group"] = d["group"].replace("", "לא צוין")
    d["hood"] = d["hood"].replace("", "לא צוין")
    return d.sort_values(["hood", "group", "type", "name", "second", "title"],
                         kind="stable").reset_index(drop=True)


def compute(frames):
    d = _prepare(frames["streets"])
    n = len(d)
    groups = _counts(d["group"])
    hoods = _counts(d["hood"])
    types = _counts(d["type"])
    has_title = d["title"] != ""
    titles = _counts(d.loc[has_title, "title"])
    extras = _counts(d.loc[d["extra"] != "", "extra"])
    nocode = int(d["code"].isna().sum())
    uniq = int(d["name"].nunique())

    g_names, g_vals = _top_other(groups, TOP_GROUPS)
    h_names, h_vals = _top_other(hoods, TOP_HOODS)
    t_names, t_vals = _top_other(types, TOP_TYPES)
    ti_names, ti_vals = _top_other(titles, TOP_TITLES)
    e_names = list(extras.index[:10])
    e_vals = [int(v) for v in extras.iloc[:10]]

    # neighbourhood x group mix (counts and shares)
    mix_hoods = list(hoods.index[:MIX_HOODS])
    mix_groups = list(groups.index[:MIX_GROUPS])
    sub = d[d["hood"].isin(mix_hoods)].copy()
    sub["g"] = sub["group"].where(sub["group"].isin(mix_groups), OTHER)
    ct = pd.crosstab(sub["hood"], sub["g"]).reindex(index=mix_hoods)
    series_names = mix_groups + ([OTHER] if OTHER in ct.columns else [])
    ct = ct.reindex(columns=series_names, fill_value=0).fillna(0)
    tot = ct.sum(axis=1)
    mix_series = [[round(float(ct.loc[h, g]) / float(tot[h]) * 100, 1) if tot[h] else 0
                   for h in mix_hoods] for g in series_names]

    # share with a title, per group
    gt = d.groupby("group").agg(n=("name", "size"), t=("title", lambda s: int((s != "").sum())))
    gt = gt[gt["n"] >= MIN_GROUP_N].copy()
    gt["share"] = gt["t"] / gt["n"]
    gt = gt.sort_index().sort_values("share", ascending=False, kind="stable")
    tg = {"names": list(gt.index), "share": [round(float(v) * 100, 1) for v in gt["share"]],
          "n": [int(v) for v in gt["n"]]}

    # ---- insights
    ins = []
    if len(groups) >= 3 and groups.iloc[0] / n >= 0.15:
        ins.append(("group_leader",
                    f"הקבוצה הנושאית הגדולה ביותר היא ״{groups.index[0]}״ עם {_int(groups.iloc[0])} שמות "
                    f"({_pct(groups.iloc[0] / n)}), לפני ״{groups.index[1]}״ ({_int(groups.iloc[1])})."))
    if len(hoods) >= 3 and hoods.iloc[0] / n >= 0.1:
        ins.append(("hood_leader",
                    f"{hoods.index[0]} היא השכונה עם מספר השמות הגדול ביותר: {_int(hoods.iloc[0])} "
                    f"({_pct(hoods.iloc[0] / n)} מהרשומות), ואחריה {hoods.index[1]} ({_int(hoods.iloc[1])})."))
    # strongest group concentration in a sizable neighbourhood
    best = None
    big = hoods[hoods >= MIN_HOOD_N]
    if len(big):
        cx = pd.crosstab(d[d["hood"].isin(big.index)]["hood"], d["group"])
        for h in sorted(cx.index):
            for g in sorted(cx.columns):
                s = cx.loc[h, g] / cx.loc[h].sum()
                if best is None or s > best[0]:
                    best = (s, h, g, int(cx.loc[h, g]), int(cx.loc[h].sum()))
    if best and best[0] >= 0.3:
        ins.append(("hood_mix",
                    f"באזור ״{best[1]}״ בולטת קבוצת ״{best[2]}״: {_int(best[3])} מתוך {_int(best[4])} השמות "
                    f"בשכונה ({_pct(best[0])})."))
    t_share = has_title.sum() / n
    if t_share >= 0.1 and len(titles):
        ins.append(("titles",
                    f"{_pct(t_share)} מהרשומות ({_int(has_title.sum())}) כוללות תואר לפני השם; "
                    f"התואר השכיח הוא ״{titles.index[0]}״ ({_int(titles.iloc[0])})."))
    if len(gt) >= 2 and gt["share"].iloc[0] >= 0.2:
        ins.append(("title_group",
                    f"שיעור הרשומות עם תואר הגבוה ביותר הוא בקבוצה ״{gt.index[0]}״: {_pct(gt['share'].iloc[0])} "
                    f"({_int(gt['t'].iloc[0])} מתוך {_int(gt['n'].iloc[0])}), לעומת {_pct(t_share)} בכלל המאגר."))
    dual = int((d["extra"] != "").sum())
    if n and dual / n >= 0.05:
        ins.append(("dual",
                    f"ל-{_int(dual)} שמות ({_pct(dual / n)}) יש גם קבוצה נוספת, כלומר שם אחד המשתייך לשני נושאים; "
                    f"הנפוצה בהן: ״{extras.index[0]}״ ({_int(extras.iloc[0])})."))
    nobel = int(extras[[k for k in extras.index if "נובל" in k]].sum()) if len(extras) else 0
    prize = int(extras[[k for k in extras.index if "פרס ישראל" in k]].sum()) if len(extras) else 0
    if nobel + prize > 0:
        ins.append(("awards",
                    f"{_int(prize)} שמות מסווגים גם כחתני פרס ישראל ו-{_int(nobel)} כזוכי פרס נובל."))
    if len(types) >= 2 and types.index[0] != "לא צוין" and types.iloc[0] / n >= 0.5:
        ins.append(("type_leader",
                    f"רוב המקומות הם מסוג ״{types.index[0]}״: {_int(types.iloc[0])} ({_pct(types.iloc[0] / n)}); "
                    f"אחריו ״{types.index[1]}״ ({_int(types.iloc[1])})."))
    if nocode > 0:
        tt = _counts(d.loc[d["code"].isna(), "type"])
        ins.append(("nocode",
                    f"ל-{_int(nocode)} רשומות ({_pct(nocode / n)}) אין קוד רחוב; "
                    f"הנפוץ שבהן הוא סוג ״{tt.index[0]}״ ({_int(tt.iloc[0])})."))
    sec = int((d["second"] != "").sum())
    if n and 0.2 <= sec / n <= 0.9:
        ins.append(("secondary",
                    f"ל-{_int(sec)} שמות ({_pct(sec / n)}) מצוין גם שם פרטי או שם משני, והשאר נושאים שם ראשי בלבד."))
    dups = int(n - uniq)
    if dups > 0:
        ins.append(("duplicates",
                    f"{_int(n)} רשומות נושאות {_int(uniq)} שמות ראשיים שונים: {_int(dups)} רשומות חוזרות על שם שכבר מופיע "
                    f"(למשל באותו שם בשכונות שונות)."))

    kp = {
        "total": {"value": n, "display": _int(n), "tone": "brand"},
        "hoods": {"value": int(len(hoods)), "display": _int(len(hoods)), "tone": "brand"},
        "groups": {"value": int(len(groups)), "display": _int(len(groups)), "tone": "brand"},
        "types": {"value": int(len(types)), "display": _int(len(types)), "tone": "brand"},
        "unique": {"value": uniq, "display": _int(uniq), "tone": "info"},
        "nocode": {"value": nocode, "display": _int(nocode),
                   "tone": "warn" if n and nocode / n >= 0.05 else "brand"},
    }

    def tbl(names, vals):
        return [{"name": a, "n": b, "share": _pct(b / n)} for a, b in zip(names, vals)]

    top_g = g_names[0]
    return {
        "agent_data": {
            "summary_he": (f"{_int(n)} שמות רחובות, כיכרות וגנים בבאר שבע ב-{_int(len(hoods))} שכונות ואזורים, "
                           f"מחולקים ל-{_int(len(groups))} קבוצות נושא. הקבוצה הגדולה: ״{top_g}״; "
                           f"סוג המקום הנפוץ: ״{types.index[0]}״."),
            "dataset_kind": "registry",
            "suggested_tags": ["שמות רחובות", "באר שבע", "שכונות", "הנצחה"],
            "related_ids": ["727e865d-25b1-43ce-9dcb-af297851f87b", "bdf28cc0-680a-415c-af64-944a58079b2f",
                            "947814b2-f2a8-4f4b-a8ec-a5f4bd2f0abe", "3c6d4061-41bf-4403-82e9-c8fae5df04dd",
                            "0e8a1152-1cf2-4a9d-9fe8-2bfd7f60d970"],
            "spatial_coverage": "באר שבע",
        },
        "kpis": kp,
        "charts": {
            "groups": {"names": g_names, "values": g_vals},
            "extra": {"names": e_names, "values": e_vals},
            "hoods": {"names": h_names, "values": h_vals},
            "mix": {"hoods": mix_hoods, "names": series_names, "series": mix_series},
            "types": {"names": t_names, "values": t_vals},
            "titles": {"names": ti_names, "values": ti_vals},
            "title_group": tg,
        },
        "tables": {
            "groups": tbl(g_names, g_vals),
            "extra": [{"name": a, "n": b} for a, b in zip(e_names, e_vals)],
            "hoods": tbl(h_names, h_vals),
            "types": tbl(t_names, t_vals),
            "titles": [{"name": a, "n": b, "share": _pct(b / max(int(has_title.sum()), 1))}
                       for a, b in zip(ti_names, ti_vals)],
            "title_group": [{"name": a, "n": b, "share": f"{s:.1f}%"}
                            for a, b, s in zip(tg["names"], tg["n"], tg["share"])],
        },
        "flags": {"has_extra": len(e_names) > 0, "has_titles": len(ti_names) > 0,
                  "has_title_group": len(tg["names"]) >= 2},
        "labels": {
            "groups_aria": f"תרשים עמודות אופקי: מספר השמות לפי קבוצת נושא. המובילה: {top_g} עם {_int(g_vals[0])}.",
            "extra_aria": "תרשים עמודות אופקי: מספר השמות לפי קבוצה נוספת.",
            "hoods_aria": f"תרשים עמודות אופקי: מספר השמות לפי שכונה. המובילה: {h_names[0]} עם {_int(h_vals[0])}.",
            "mix_aria": f"תרשים עמודות מוערמות ב-100 אחוז: הרכב קבוצות הנושא ב-{_int(len(mix_hoods))} השכונות הגדולות.",
            "types_aria": f"תרשים עמודות: מספר המקומות לפי סוג. הנפוץ: {t_names[0]} עם {_int(t_vals[0])}.",
            "titles_aria": "תרשים עמודות: התארים הנפוצים לפני שם הרחוב.",
            "title_group_aria": "תרשים עמודות אופקי: שיעור הרשומות עם תואר בכל קבוצת נושא.",
        },
        "insights": [{"id": i, "text_he": t} for i, t in ins],
    }
