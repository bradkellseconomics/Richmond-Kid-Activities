# ranker.py
#
# Macaroni KID publishes hundreds of events; the point of this module is to
# turn that pile into "what's actually worth taking these specific kids to."
# That's a qualitative call (age fit, does it match what a kid's into, is the
# timing/cost reasonable) — not something a 0-100 score is well suited for.
# Claude isn't a calibrated scorer, so instead of asking for a number we ask
# for a simple top/good/skip judgment per kid, which is a call it can make
# reliably, plus a one-line reason so the output is easy to sanity-check.
from __future__ import annotations
import json
import os
from datetime import date

import anthropic
from dateutil.relativedelta import relativedelta

from .config import CFG

MODEL = os.getenv("RK_RANK_MODEL", "claude-opus-4-8")
DESC_MAX_CHARS = 400
FIT_LEVELS = ("top", "good", "skip")
TOKENS_PER_EVENT = 200  # output budget per event (uid + per-kid fit + reason, plus JSON overhead)
MIN_OUTPUT_TOKENS = 4000
MAX_OUTPUT_TOKENS = 64000


def _fmt_event(ev: dict) -> dict:
    desc = (ev.get("description") or "")[:DESC_MAX_CHARS]
    age = None
    if ev.get("age_min") is not None or ev.get("age_max") is not None:
        age = f"{ev.get('age_min', '?')}-{ev.get('age_max', '?')}"
    cost = None
    if ev.get("cost_min") is not None or ev.get("cost_max") is not None:
        cost = f"${ev.get('cost_min')}-${ev.get('cost_max')}"
    return {
        "uid": ev["uid"],
        "title": ev.get("title"),
        "when": ev.get("start_dt"),
        "venue": ev.get("venue_name"),
        "category": ev.get("category"),
        "age_range": age,
        "cost": cost,
        "description": desc,
    }


def _age_months(birthdate: str) -> int:
    bd = date.fromisoformat(birthdate)
    delta = relativedelta(date.today(), bd)
    return delta.years * 12 + delta.months


def _kid_desc(kid: dict) -> str:
    birthdate = kid.get("birthdate")
    age_str = f"{_age_months(birthdate)} months old" if birthdate else "age unknown"
    interests = kid.get("interests") or []
    interest_str = ", ".join(interests) if interests else "no particular preferences yet"
    return f"- {kid['name']}: {age_str}. Likes: {interest_str}."


def _system_prompt(kids: tuple[dict, ...]) -> str:
    kid_lines = "\n".join(_kid_desc(k) for k in kids)
    return f"""You are picking family activities from a local Richmond, VA events feed for these kids:
{kid_lines}

Where the family lives: {CFG.home_location}

For every event, judge its fit for EACH kid separately as "top", "good", or "skip":
- "top": a strong, specific fit — the age range clearly includes the kid, or the event matches one of
  their named interests, or it's an obvious toddler/preschool program (storytime, sensory play, parent & me)
  — AND the venue is convenient per the location guidance above.
- "good": plausible and fine to attend, but not a standout — the age range is broad/unclear but not
  exclusionary, it's generically "family friendly" without anything specific to this kid, or it's an
  otherwise strong match at a venue that's a real drive away.
- "skip": not appropriate — age range excludes the kid, explicitly for older kids/teens/adults, or the
  event is adult-oriented (bars, wineries, 21+, lectures, book clubs, teen-only, professional networking).

Use common sense on the practical details too: free/low-cost and daytime or weekend timing nudge toward
"good"/"top"; a late weeknight event nudges toward "skip" for young kids. When genuinely ambiguous, use
"good" rather than guessing "top" or "skip".

Separately, flag at most 5 events (0 is fine most weeks) as `star`: true. A star event is worth taking off
work for or planning the weekend around — a memory-making outing, not a solid everyday activity. Think a
mini Nutcracker or a play staged for kids, a seasonal festival, a limited-run exhibit opening, a real
performance or one-off special event. The bar is "I want to be the kind of parent who takes their kid to
this," not "good activity to suggest to a nanny." Recurring weekly programs (storytime, toddler time, book
babies, generic drop-in family fun) are NOT star events even when they're a great everyday pick — routine
disqualifies it regardless of quality. Only mark star on an event that's already "top" or "good" for at
least one kid.

Also give a one-clause reason (under 12 words) explaining the call, e.g. "storytime for ages 0-2" or
"lecture, adults only".

Call rank_events exactly once with a judgment for every uid you were given — do not skip any."""


def _build_tool(kids: tuple[dict, ...]) -> dict:
    fit_props = {
        kid["name"]: {
            "type": "string",
            "enum": list(FIT_LEVELS),
            "description": f"Fit for {kid['name']}.",
        }
        for kid in kids
    }
    return {
        "name": "rank_events",
        "description": "Judge every candidate event's fit for each kid.",
        "input_schema": {
            "type": "object",
            "properties": {
                "rankings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "uid": {"type": "string"},
                            "fit": {
                                "type": "object",
                                "properties": fit_props,
                                "required": list(fit_props.keys()),
                                "additionalProperties": False,
                            },
                            "star": {
                                "type": "boolean",
                                "description": "True for a rare, memory-making, plan-the-weekend-around event (max 5 per batch). False for routine/recurring programs.",
                            },
                            "reason": {"type": "string"},
                        },
                        "required": ["uid", "fit", "star", "reason"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["rankings"],
            "additionalProperties": False,
        },
        "strict": True,
    }


def rank_events(events: list[dict], kids: tuple[dict, ...] | None = None) -> list[dict]:
    """Attaches `_fit` ({kid_name: "top"|"good"|"skip"}) and `_reason` to each event dict."""
    if not events:
        return events
    if kids is None:
        kids = CFG.kids
    if not CFG.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set — required for event ranking.")

    client = anthropic.Anthropic(api_key=CFG.anthropic_api_key)
    payload = [_fmt_event(ev) for ev in events]
    tool = _build_tool(kids)

    # Scale the output budget with the batch size — a fixed cap silently
    # truncates the tool call once the event count grows, which previously
    # made every event fall back to "skip" with no error. Stream since this
    # can comfortably exceed ~16K tokens.
    max_tokens = min(MAX_OUTPUT_TOKENS, max(MIN_OUTPUT_TOKENS, len(events) * TOKENS_PER_EVENT))
    with client.messages.stream(
        model=MODEL,
        max_tokens=max_tokens,
        system=_system_prompt(kids),
        tools=[tool],
        tool_choice={"type": "tool", "name": "rank_events"},
        messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
    ) as stream:
        response = stream.get_final_message()

    if response.stop_reason == "max_tokens":
        raise RuntimeError(
            f"Claude ranking response was truncated at max_tokens={max_tokens} for "
            f"{len(events)} events — raise TOKENS_PER_EVENT or MAX_OUTPUT_TOKENS in ranker.py."
        )

    tool_use = next((b for b in response.content if b.type == "tool_use"), None)
    if not tool_use:
        raise RuntimeError(f"Claude did not return a ranking (stop_reason={response.stop_reason})")

    default_fit = {kid["name"]: "skip" for kid in kids}
    results = {r["uid"]: r for r in tool_use.input.get("rankings", [])}
    star_count = 0
    for ev in events:
        r = results.get(ev["uid"])
        ev["_fit"] = r["fit"] if r else dict(default_fit)
        ev["_reason"] = r.get("reason", "") if r else ""
        is_star = bool(r.get("star")) if r else False
        # Enforce the "max 5" cap in code too, in case the model overshoots.
        if is_star and star_count < 5:
            star_count += 1
        else:
            is_star = False
        ev["_star"] = is_star
    return events
