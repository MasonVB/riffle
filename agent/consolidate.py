"""The daily decision about what to carry forward.

Once per UTC day the agent reviews what it learned and sorts it into two
shelves.

  SHORT TERM  seven days, then gone. The bar is low: anything that might
              matter this week. Most of what it notices lands here and most
              of it should quietly expire, which is the point — a memory
              store where nothing ever leaves is a log, and a log that is
              injected into every prompt is a tax.

  LONG TERM   no expiry, and a deliberately hard bar. Something belongs here
              only if it will still be true and still matter in a month.

WHY A DAILY PASS RATHER THAN DECIDING AS IT GOES

At the moment a thing is learned, everything feels worth keeping. A day later
almost none of it does. The delay is the filter, and it is the only one
available that does not need a judgement the agent cannot yet make.

THE PROMOTION CAP IS THE LOAD-BEARING PART

Without a cap the agent promotes everything, because each item argues well for
itself in isolation. Three a day forces comparison: not "is this worth
keeping" but "is this among the three most worth keeping today". That is a
question with a wrong answer, which is what makes it a real decision.

WHAT EXPIRY DOES NOT DO

Expired memories are marked, not deleted. They stop reaching the prompt but
remain on record, so "what did I once believe about this" is still answerable.
Same reason corrections supersede rather than overwrite.
"""
import datetime as dt
import json

from agent import cortex, memory
from agent.state import utcnow

SCHEMA = {
    "type": "object",
    "properties": {
        "promote": {"type": "array", "items": {
            "type": "object",
            "properties": {"id": {"type": "integer", "minimum": 1},
                           "why": {"type": "string"}},
            "required": ["id", "why"], "additionalProperties": False}},
        "write": {"type": "array", "items": {
            "type": "object",
            "properties": {"text": {"type": "string"},
                           "tier": {"type": "string", "enum": ["short", "long"]},
                           "why": {"type": "string"}},
            "required": ["text", "tier", "why"], "additionalProperties": False}},
        "drop": {"type": "array", "items": {
            "type": "object",
            "properties": {"id": {"type": "integer", "minimum": 1},
                           "why": {"type": "string"}},
            "required": ["id", "why"], "additionalProperties": False}},
        "note": {"type": "string"},
    },
    "required": ["promote", "write", "drop"],
    "additionalProperties": False,
}

PROMPT = """You are riffle, deciding once a day what to carry forward. You wake with no
memory; this is the only mechanism by which anything survives.

TWO SHELVES

  short term   expires in {ttl} days. The bar is low. Most of what you notice
               belongs here, and most of it should be allowed to expire.
  long term    never expires. The bar is high and you may promote at most
               {cap} items today.

PROMOTE to long term only if it will still be true AND still matter in a month:

  - something your operator told you about himself, his machines, or his
    decisions
  - a commitment either of you made
  - a correction to something you believed, which is worth more than the
    original belief
  - a fact about your own circumstances that will not change

DO NOT PROMOTE:

  - anything you can look up: board state, your own action log, your goals
  - a thought you had once and have not returned to
  - something true today that will be false next week
  - a restatement of something already in long term

The cap is not a suggestion. If you have four candidates, the fourth is the
one you are wrong about; leave it in short term and it will come back tomorrow
if it mattered.

WRITE is for a memory that does not exist yet: usually one durable sentence
standing in for several short-term ones you would otherwise promote
separately. Consolidating three observations into the thing they add up to is
better than promoting all three.

DROP is for short-term items that are already wrong, not merely unimportant.
Unimportant things expire on their own; you do not need to act.

Reply with ONE JSON object and nothing else:

{{"promote": [{{"id": 12, "why": "..."}}],
  "write":   [{{"text": "...", "tier": "long", "why": "..."}}],
  "drop":    [{{"id": 31, "why": "..."}}],
  "note":    "one sentence on what today amounted to"}}

Empty arrays are the right answer on a quiet day."""


def due(state, cfg):
    """Once per UTC day, at the first cycle after the configured hour."""
    m = cfg.get("memory") or {}
    if not m.get("consolidate", True):
        return False
    hour = int(m.get("consolidate_after_hour_utc", 9))
    now = dt.datetime.now(dt.timezone.utc)
    if now.hour < hour:
        return False
    return (state.note("last_consolidation") or "")[:10] != now.date().isoformat()


def candidates(state, cfg, limit=40):
    """Short-term, unexpired, not yet long — the things eligible for promotion."""
    return state.db.execute(
        "SELECT id, ts, kind, text, use_count FROM memories"
        " WHERE COALESCE(tier,'short')='short' AND superseded_by IS NULL"
        "   AND COALESCE(expired,0)=0"
        " ORDER BY use_count DESC, id DESC LIMIT ?", (limit,)).fetchall()


def long_term(state, limit=40):
    return state.db.execute(
        "SELECT id, ts, text FROM memories WHERE tier='long'"
        " AND superseded_by IS NULL ORDER BY id DESC LIMIT ?", (limit,)).fetchall()


def run(state, cfg, log, say=None):
    """The daily pass. Returns a short summary string, or None if not due."""
    m = cfg.get("memory") or {}
    ttl = int(m.get("short_ttl_days", 7))
    cap = int(m.get("max_promotions_per_day", 3))

    cands = candidates(state, cfg)
    if not cands:
        state.note("last_consolidation", utcnow())
        log("consolidation: nothing in short term to consider")
        return "nothing to consolidate"

    have = long_term(state)
    body = [
        "SHORT TERM, eligible for promotion (id, age, times recalled):",
        *[f"  [{r['id']}] {r['ts'][:10]} recalled {r['use_count']}x — {r['text']}"
          for r in cands],
        "",
        "ALREADY IN LONG TERM — do not promote a restatement of any of these:",
        *([f"  [{r['id']}] {r['text']}" for r in have] or ["  (nothing yet)"]),
    ]
    prompt = PROMPT.format(ttl=ttl, cap=cap)
    try:
        raw = cortex.complete(cfg["llm"]["composer"], prompt, "\n".join(body),
                              schema=SCHEMA)
        plan = cortex.parse_proposal(raw) if '"action"' in raw else json.loads(
            raw[raw.index("{"):raw.rindex("}") + 1])
    except Exception as e:
        log(f"consolidation failed: {e}", level="warn")
        return None

    valid = {r["id"] for r in cands}
    promoted, written, dropped, refused = [], [], [], []

    for item in (plan.get("promote") or [])[:cap]:
        mid = item.get("id")
        if mid not in valid:
            refused.append(f"id {mid} is not a short-term candidate")
            continue
        state.db.execute(
            "UPDATE memories SET tier='long', expires_at=NULL WHERE id=?", (mid,))
        promoted.append((mid, item.get("why", "")[:200]))
    if len(plan.get("promote") or []) > cap:
        refused.append(f"{len(plan['promote'])} promotions proposed, cap is {cap}")

    for item in (plan.get("write") or [])[:cap]:
        tier = item.get("tier", "short")
        mid = memory.remember(state, item["text"], kind="self",
                              source="consolidation")
        if mid:
            exp = None if tier == "long" else _expiry(ttl)
            state.db.execute("UPDATE memories SET tier=?, expires_at=? WHERE id=?",
                             (tier, exp, mid))
            written.append((mid, tier, item["text"][:120]))

    for item in (plan.get("drop") or []):
        mid = item.get("id")
        if mid in valid:
            state.db.execute("UPDATE memories SET expired=1 WHERE id=?", (mid,))
            dropped.append((mid, item.get("why", "")[:160]))

    # One of the candidates it passed over may go up anyway. This is the only
    # thing in long term that its own judgement did not choose, which is the
    # entire reason for keeping it.
    import random as _r
    from agent.memory import extra_count
    passed = [r["id"] for r in cands
              if r["id"] not in {m for m, _ in promoted}
              and r["id"] not in {m for m, _ in dropped}]
    lucky = []
    for mid in _r.sample(passed, min(extra_count(len(promoted), cfg), len(passed))):
        state.db.execute(
            "UPDATE memories SET tier='long', expires_at=NULL WHERE id=?", (mid,))
        row = state.db.execute("SELECT text FROM memories WHERE id=?",
                               (mid,)).fetchone()
        lucky.append((mid, row["text"]))

    state.db.commit()
    state.note("last_consolidation", utcnow())

    parts = []
    if promoted:
        parts.append(f"promoted {len(promoted)} to long term")
    if written:
        parts.append(f"wrote {len(written)} new")
    if dropped:
        parts.append(f"dropped {len(dropped)} as wrong")
    if lucky:
        parts.append(f"kept {len(lucky)} at random")
    summary = ", ".join(parts) or "kept everything in short term"
    log(f"consolidation: {summary}. {plan.get('note', '')[:200]}")

    if say:
        lines = [f"Daily memory pass — {summary}."]
        if plan.get("note"):
            lines.append(plan["note"][:400])
        for mid, why in promoted:
            row = state.db.execute("SELECT text FROM memories WHERE id=?",
                                   (mid,)).fetchone()
            lines.append(f"  \u2191 long: {row['text'][:150]}\n    ({why[:120]})")
        for mid, tier, text in written:
            lines.append(f"  + {tier}: {text}")
        for mid, text in lucky:
            lines.append(f"  \u2191 long (at random, not chosen): {text[:150]}")
        for mid, why in dropped:
            lines.append(f"  \u2717 dropped [{mid}]: {why[:120]}")
        for r in refused:
            lines.append(f"  refused: {r}")
        say("report", "\n".join(lines), {"drive": "memory"})
    return summary


def _expiry(ttl_days):
    return (dt.datetime.now(dt.timezone.utc)
            + dt.timedelta(days=ttl_days)).isoformat()


def sweep(state, cfg, log=None):
    """Expire short-term memories past their date. Cheap; run every cycle."""
    now = utcnow()
    cur = state.db.execute(
        "UPDATE memories SET expired=1 WHERE COALESCE(tier,'short')='short'"
        " AND COALESCE(expired,0)=0 AND pinned=0"
        " AND expires_at IS NOT NULL AND expires_at < ?", (now,))
    n = cur.rowcount
    # Hard-delete only what has been expired a long time. Keeping the record of
    # what it once believed is worth more than the bytes.
    keep = int((cfg.get("memory") or {}).get("purge_expired_after_days", 30))
    cutoff = (dt.datetime.now(dt.timezone.utc)
              - dt.timedelta(days=keep)).isoformat()
    state.db.execute(
        "DELETE FROM memories WHERE expired=1 AND pinned=0 AND expires_at < ?",
        (cutoff,))
    state.db.commit()
    if n and log:
        log(f"{n} short-term memory(ies) expired")
    return n
