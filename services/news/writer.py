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
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from services.shared.states import ArticleKind

from . import gates
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


def system_prompt() -> str:
    return ((PROMPTS / "writer.md").read_text(encoding="utf-8") + "\n\n# Style guide\n\n"
            + (PROMPTS / "style_he.md").read_text(encoding="utf-8"))


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
        for k in ("change_pct", "yoy_pct", "yoy", "change"):
            v = sig.facts.get(k)
            if isinstance(v, int | float) and not isinstance(v, bool):
                entry[k] = {"value": v, "fact": tb.ledger.add(
                    v, label=f"{k} · {sig.label or sig.series_path} · {sig.period}",
                    provenance=f"signal:{sig.key}:{k}", unit="pct" if k.endswith("pct") else None,
                    period=sig.period, dataset_id=sig.dataset_id).id}
        for k in ("high_since", "low_since", "record_high", "record_low", "streak",
                  "rank_high", "rank_low", "n_periods", "first_period", "suspect_incomplete"):
            if k in sig.facts:
                entry[k] = sig.facts[k]
        if isinstance(entry.get("streak"), int):
            entry["streak_fact"] = tb.ledger.add(abs(entry["streak"]), label="streak length",
                                                 provenance=f"signal:{sig.key}:streak").id
        entry["linked"] = sig.links
        out.append(entry)
    return out


def write(llm, tb: Toolbox, brief: dict, *, catalog: dict, vocab: set[str], today: str,
          max_tool_calls: int = 25) -> Outcome:
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
    messages = [{"role": "system", "content": system_prompt()},
                {"role": "user", "content": json.dumps(user, ensure_ascii=False, default=str)}]
    calls = 0
    over = 0                  # calls refused in a turn that still offered tools
    critic_rounds = gate_rounds = 0
    critic = None
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
                                     catalog=catalog, vocab=vocab, article_kind=kind)
        if not problems:
            critic = gates.critique(llm, core, kind=kind, ledger=tb.ledger)
            if critic["verdict"] == "pass":
                return Outcome("accepted", core=core, critic=critic, tool_calls=calls)
            if critic["verdict"] == "kill":
                return Outcome("rejected", core=core, reason="critic_kill", critic=critic, tool_calls=calls)
            problems = [f"copy chief: {x}" for x in critic["issues"] + critic["fixes"]]
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
