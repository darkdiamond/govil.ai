"""Stage 4: one brief → one checked article (or a recorded rejection).

The writer is an agent loop over `tools.Toolbox` (prompts/writer.md + the
style guide). Its submission goes through `gates.check` (deterministic) and
`gates.critique` (copy chief). Either kind of problem sends it back with
the list. The two have separate budgets: CRITIC_REVISIONS rounds for the
copy chief's judgement, GATE_REVISIONS for mechanical misses (a bare year, a
missing stat block, a banned phrase). A rewrite for the critic often slips
one of those, and with one shared budget that slip killed a draft the critic
was about to pass (2026-11-13: two of three explainers). Running out of
either, a "kill", or running out of tool calls rejects the story. Nothing is
ever published "anyway".

From its second round the copy chief sees its own previous review and checks
that first, raising new issues only when substantive: reviewing every round
from scratch produced fresh style notes each time, and most rejected drafts
(2026-11-09..15) died on the last round that way. On that last round a
"revise" whose scores all clear the bar (>= 4) and whose open notes are
style only (`blocking: false`) passes (`gates.critique` `final`). A brief on a recurring release's new period tells the critic so
(`RELEASE:`): the new figure is the news, however small the move.

The writer sees three of the six example passages in prompts/exemplars/,
rotated per brief (`exemplars`), and the desk's current stock phrases
(`stock`). With NEWS_LINE_EDIT on, an accepted story gets a delete-only line
edit (`line_edit.py`) that must pass the gates and the critic again.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from services.shared.states import ArticleKind

from . import gates, line_edit
from .registry import REGISTRY_FLAGS
from .signals import is_release
from .tools import SUBMIT_SPEC, TOOL_SPECS, Toolbox

log = logging.getLogger(__name__)
PROMPTS = Path(__file__).with_name("prompts")
CRITIC_REVISIONS = 2
GATE_REVISIONS = 3
MAX_TURNS = 45            # model calls per article, whatever they contain
WEB_TOOLS = {"web_search", "fetch_url"}
DATA_ONLY_KINDS = {ArticleKind.FEATURE, ArticleKind.DIGEST}


@dataclass
class Outcome:
    status: str                       # accepted | rejected
    core: dict | None = None
    reason: str | None = None
    problems: list[str] = field(default_factory=list)
    critic: dict | None = None
    tool_calls: int = 0
    line_edit: dict | None = None     # what the delete-only line edit did (`line_edit.py`)


EXEMPLARS = 3


def exemplars(kind: str = ArticleKind.NEWS, seed: str = "") -> list[str]:
    """`EXEMPLARS` example passages from prompts/exemplars/: two of the
    brief's kind (`news-*` / `feature-*`; a digest reads news ones) and one of
    the other, rotated by `seed`. One fixed set of examples is copied, phrase
    and shape: the old style guide's three were, and "אחד ההסברים האפשריים"
    ended up in half the articles (2026-11-26)."""
    files = sorted((PROMPTS / "exemplars").glob("*.md"))
    own = "feature" if kind == ArticleKind.FEATURE else "news"
    mine = [f for f in files if f.name.startswith(own + "-")]
    other = [f for f in files if not f.name.startswith(own + "-")]
    n = int(hashlib.sha256(seed.encode()).hexdigest(), 16)

    def turn(xs, k):
        return [xs[(n + i) % len(xs)] for i in range(min(k, len(xs)))] if xs else []

    pick = turn(mine, EXEMPLARS - 1)
    pick += turn(other, EXEMPLARS - len(pick))
    return [f.read_text(encoding="utf-8").strip() for f in pick]


def system_prompt(kind: str = ArticleKind.NEWS, seed: str = "") -> str:
    out = ((PROMPTS / "writer.md").read_text(encoding="utf-8") + "\n\n# Style guide\n\n"
           + (PROMPTS / "style_he.md").read_text(encoding="utf-8"))
    ex = exemplars(kind, seed)
    if ex:
        out += ("\n\n# Examples of the target voice\n\n"
                "Each shows a different kind of story. Learn the voice and the choices (what is "
                "left out, how a hedge is said, how it ends), never the wording: don't copy their "
                "phrases or their shape. Their numbers are illustrations typed as digits; yours "
                "are fact tokens.\n\n" + "\n\n---\n\n".join(ex))
    return out


def seed_facts(tb: Toolbox, brief: dict) -> list[dict]:
    """Register the brief's signals as facts up front, so the lead's numbers
    are citable before any tool call."""
    out = []
    for sig in brief["signals"]:
        s = next((x for x in tb.series.get(sig.dataset_id, []) if x.path == sig.series_path), None)
        entry = {"key": sig.key, "dataset_id": sig.dataset_id, "series_path": sig.series_path,
                 "period": sig.period, "flags": sig.flags}
        if s is not None:
            pts = {p.label: (p, v) for p, v in s.points}
            for name, lbl in (("latest", sig.period),
                              ("previous", (sig.facts.get("previous") or {}).get("period")),
                              ("year_ago", (sig.facts.get("year_ago") or {}).get("period"))):
                if lbl in pts:
                    p, v = pts[lbl]
                    entry[name] = {"period": lbl, "value": v, "fact": tb.point_fact(s, p, v)}
        elif set(sig.flags) & REGISTRY_FLAGS:
            entry.update(_registry_seeds(tb, sig))
        for k in ("change_pct", "yoy_pct", "yoy", "change", "change_pp"):
            v = sig.facts.get(k)
            if isinstance(v, int | float) and not isinstance(v, bool):
                entry[k] = {"value": v, "fact": tb.ledger.add(
                    v, label=f"{k} · {sig.label or sig.series_path} · {sig.period}",
                    provenance=f"signal:{sig.key}:{k}",
                    unit="pct" if k.endswith(("pct", "pp")) else None,
                    period=sig.period, dataset_id=sig.dataset_id).id}
        for k in ("high_since", "low_since", "record_high", "record_low", "streak",
                  "rank_high", "rank_low", "n_periods", "first_period", "suspect_incomplete",
                  "follows_article"):
            if k in sig.facts:
                entry[k] = sig.facts[k]
        if isinstance(entry.get("streak"), int):
            entry["streak_fact"] = tb.ledger.add(abs(entry["streak"]), label="streak length",
                                                 provenance=f"signal:{sig.key}:streak").id
        entry["linked"] = sig.links
        out.append(entry)
    return out


def _registry_seeds(tb: Toolbox, sig) -> dict:
    """Facts for a snapshot-diff signal (`registry.py`), which has no series
    to read its numbers from: the KPI now and at the comparison render, and
    each named entrant's, leaver's or leader's count."""
    f, out = sig.facts, {}
    pct = "pct" if f.get("unit") == "pct_points" else None

    def add(v, label, tag, unit=None):
        return tb.ledger.add(v, label=label, provenance=f"signal:{sig.key}:{tag}", unit=unit,
                             period=sig.period, dataset_id=sig.dataset_id).id

    if "kpi_move" in sig.flags:
        prev = f.get("previous") or {}
        out["latest"] = {"date": sig.period, "value": sig.value,
                         "fact": add(sig.value, f"{sig.label} · {sig.period}", "latest", pct)}
        if isinstance(prev.get("value"), int | float):
            out["previous"] = {"date": prev.get("period"), "value": prev["value"],
                               "fact": add(prev["value"], f"{sig.label} · {prev.get('period')}",
                                           "previous", pct)}
    for group, vkey in (("entrants", "value"), ("exits", "value_then")):
        if f.get(group):
            out[group] = [e | ({"fact": add(e[vkey], f"{sig.label} · {e['name']}", f"{group}:{e['name']}")}
                               if isinstance(e.get(vkey), int | float) else {})
                          for e in f[group]]
    if f.get("leader"):
        ld, pl = f["leader"], f.get("previous_leader") or {}
        out["leader"] = ld | {"fact": add(ld["value"], f"{sig.label} · {ld['name']}", "leader")}
        if isinstance(pl.get("value_now"), int | float):
            out["previous_leader"] = pl | {"fact": add(pl["value_now"], f"{sig.label} · {pl['name']}",
                                                       "previous_leader")}
    for k in ("chart", "kpi", "display", "compared_to", "top_n_list", "n_categories"):
        if k in f:
            out[k] = f[k]
    return out


def release_name(brief: dict, catalog: dict) -> str | None:
    """The release's name when the brief reports a new period of a recurring
    official release (a CBS or BoI monthly/quarterly series, `signals.is_release`,
    unusual or not), else None. Only a news story's lead dataset counts: a
    digest pools many datasets, and a CBS series linked into another
    dataset's story doesn't make that story a release."""
    if str(brief.get("kind") or ArticleKind.NEWS) != ArticleKind.NEWS:
        return None
    sigs = brief.get("signals") or []
    lead = sigs[0].dataset_id if sigs else None
    for sig in sigs:
        if sig.dataset_id == lead and is_release(sig):
            return (catalog.get(sig.dataset_id) or {}).get("title") or sig.dataset_id
    return None


def write(llm, tb: Toolbox, brief: dict, *, catalog: dict, vocab: set[str], today: str,
          max_tool_calls: int = 25, stock: list[str] | None = None) -> Outcome:
    seeds = seed_facts(tb, brief)
    kind = str(brief.get("kind") or ArticleKind.NEWS)
    # Explainers and digests are told from our data alone: in dry runs web
    # fetches were nearly all refused and ate the tool budget (2026-11-11).
    specs = [t for t in TOOL_SPECS if kind not in DATA_ONLY_KINDS
             or t["function"]["name"] not in WEB_TOOLS]
    user = {
        "today": today,
        "kind": kind,
        "brief": {k: brief[k] for k in ("angle_he", "why_now_he", "questions", "dataset_ids")},
        "signals": seeds,
        "datasets": {d: {"title": (catalog.get(d) or {}).get("title"),
                         "publisher": (catalog.get(d) or {}).get("organization")}
                     for d in brief["dataset_ids"]},
        # The datasets' own canonical tags first; the whole vocabulary (a few
        # hundred short names) only when they have none.
        "tag_vocabulary": sorted({t for d in brief["dataset_ids"]
                                  for t in (catalog.get(d) or {}).get("tags", []) if t in vocab})
                          or sorted(vocab),
    }
    if stock:
        # Phrases many of our recent articles share (`stock.py`): once at most.
        user["stock_phrases"] = stock
    seed = ",".join(map(str, brief.get("signal_keys") or brief.get("dataset_ids") or []))
    messages = [{"role": "system", "content": system_prompt(kind, seed)},
                {"role": "user", "content": json.dumps(user, ensure_ascii=False, default=str)}]
    calls = 0
    over = 0                  # calls refused in a turn that still offered tools
    critic_rounds = gate_rounds = 0
    critic = None
    last_review = None        # the copy chief's previous {issues, fixes}, kept across gate rounds
    release = release_name(brief, catalog)
    nudged = False
    turns = 0
    while True:
        turns += 1
        if turns > MAX_TURNS:
            # Turns that don't count as tool calls (bad JSON, repeated bad
            # submissions) must still end: every turn is a paid model call.
            return Outcome("rejected", reason="turn_limit", tool_calls=calls)
        tools = specs + [SUBMIT_SPEC] if calls < max_tool_calls else [SUBMIT_SPEC]
        offered = {t["function"]["name"] for t in tools}
        msg = llm.chat(messages, tools=tools, temperature=0.6)
        # Keep reasoning_details: reasoning models want them back on every
        # tool-calling turn (Gemini 3 400s without its thought signatures).
        messages.append({k: msg[k] for k in ("tool_calls", "reasoning", "reasoning_details")
                         if msg.get(k) is not None}
                        | {"role": "assistant", "content": msg.get("content") or ""})
        tcs = msg.get("tool_calls") or []
        if not tcs:
            if nudged:
                return Outcome("rejected", reason="no_submission", tool_calls=calls)
            nudged = True
            messages.append({"role": "user", "content": "Submit the article with submit_article."})
            continue
        draft = None
        for tc in tcs:
            fn = tc.get("function") or {}
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = None
            if fn.get("name") == "submit_article" and isinstance(args, dict):
                draft = args.get("article") if isinstance(args.get("article"), dict) else args
                result = '{"received": true}'
            elif args is None:
                result = '{"error": "arguments were not valid JSON"}'
            elif fn.get("name") not in offered:
                result = '{"error": "tool budget used up: only submit_article is available"}'
            elif calls >= max_tool_calls:
                # The budget holds per call: one turn can ask for many at once.
                over += 1
                result = '{"error": "tool budget used up: only submit_article is available"}'
            else:
                calls += 1
                result = tb.call(fn.get("name") or "", args)
            messages.append({"role": "tool", "tool_call_id": tc.get("id"), "content": result})
        if calls >= max_tool_calls and draft is None:
            messages.append({"role": "user", "content": "Tool budget used up. Submit now with what you have."})
        if draft is None:
            if calls + over > max_tool_calls + 3:
                return Outcome("rejected", reason="tool_budget", tool_calls=calls)
            continue

        core, problems = gates.check(draft, ledger=tb.ledger, series_by_ds=tb.series,
                                     catalog=catalog, vocab=vocab, article_kind=kind, stock=stock)
        if not problems:
            critic = gates.critique(llm, core, kind=kind, ledger=tb.ledger, previous=last_review,
                                    release=release, final=critic_rounds >= CRITIC_REVISIONS)
            if critic["verdict"] == "pass":
                out = Outcome("accepted", core=core, critic=critic, tool_calls=calls)
                if line_edit.enabled():
                    edited, out.line_edit, recheck = line_edit.edit(
                        llm, draft,
                        check=lambda d: gates.check(d, ledger=tb.ledger, series_by_ds=tb.series,
                                                    catalog=catalog, vocab=vocab, article_kind=kind,
                                                    stock=stock),
                        # the cut version against the same bar, with no round left
                        critique=lambda c: gates.critique(llm, c, kind=kind, ledger=tb.ledger,
                                                          release=release, final=True))
                    if edited is not None:
                        # what is stored with the story is the verdict on the text it prints
                        out.core, out.critic = edited, recheck
                    log.info("news line edit %s: %s", brief.get("signal_keys"), out.line_edit)
                return out
            if critic["verdict"] == "kill":
                return Outcome("rejected", core=core, reason="critic_kill", critic=critic, tool_calls=calls)
            problems = [f"copy chief: {x}" for x in critic["issues"] + critic["fixes"]]
            last_review = {"issues": critic["issues"], "fixes": critic["fixes"]}
        by_critic = critic is not None
        log.info("news writer %s: %s round %d: %s", brief.get("signal_keys"),
                 "critic" if by_critic else "gates", (critic_rounds if by_critic else gate_rounds) + 1,
                 "; ".join(p[:160] for p in problems)[:1200])
        if by_critic:
            if critic_rounds >= CRITIC_REVISIONS:
                return Outcome("rejected", core=core, reason="critic_revise",
                               problems=problems, critic=critic, tool_calls=calls)
            critic_rounds += 1
        else:
            if gate_rounds >= GATE_REVISIONS:
                return Outcome("rejected", core=core, reason="gates",
                               problems=problems, critic=critic, tool_calls=calls)
            gate_rounds += 1
        ask = ("The article was not accepted. Fix every problem and submit again "
               "(you may use a few more tool calls):" if by_critic else
               "The article failed the mechanical checks. Fix exactly these problems, keep "
               "everything else as it is, and submit again:")
        messages.append({"role": "user", "content": ask + "\n- " + "\n- ".join(problems)})
        max_tool_calls = calls + 6
        over = 0
        critic = None
