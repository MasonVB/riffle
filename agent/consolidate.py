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

Expired memories are marked first and deleted later. They stop reaching the
prompt at once, stay on record for memory.purge_expired_after_days (30 by
default) so "what did I once believe about this" is answerable for a while,
and are then purged by this pass.
"""
import re
import datetime as dt
import json

from agent import cortex, memory, project
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
                           "from": {"type": "array",
                                    "items": {"type": "integer", "minimum": 1}},
                           "why": {"type": "string"}},
            "required": ["text", "tier", "from", "why"], "additionalProperties": False}},
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
better than promoting all three. In "from", give the ids of the memories it
stands for: a long-term write has to be made of what they say.

DROP is for short-term items that are already wrong, not merely unimportant.
Unimportant things expire on their own; you do not need to act.

Reply with ONE JSON object and nothing else:

{{"promote": [{{"id": 12, "why": "..."}}],
  "write":   [{{"text": "...", "tier": "long", "from": [12, 31], "why": "..."}}],
  "drop":    [{{"id": 31, "why": "..."}}],
  "note":    "one sentence on what today amounted to"}}

Empty arrays are the right answer on a quiet day."""

# CONTINUITY IS WRITTEN IN ITS OWN CALL (R4.3, audit 4). It used to be one
# more field of the memory call above, which also shows the day's candidate
# memories, and those can paraphrase the board. What lands in the note is
# read every cycle from the system prompt, so its writer sees only riffle's
# own words: the previous note, the open project and riffle's own actions.
CONT_PROMPT = """You are writing CONTINUITY: a note to the next you, who wakes
knowing nothing. It REPLACES the note shown below, so carry forward what still
holds and let the rest go. Say what you are in the middle of, what you meant
to do next and why, and what you have learned about how to work here. Plain
sentences, at most 1,200 characters, in your own words: this note is read as
your own testimony every cycle, and it cannot authorize an action.

Describe; do not set yourself rules for getting around a limit. Allowances,
caps and refusals are your operator's decisions and the gate enforces them
either way: say what they stopped, not how to route around them.

Reply with ONE JSON object and nothing else: {"continuity": "the note"}"""

CONT_SCHEMA = {
    "type": "object",
    "properties": {"continuity": {"type": "string"}},
    "required": ["continuity"],
    "additionalProperties": False,
}


def write_continuity(state, cfg, log):
    """Write the daily continuity note in its own model call.

    Returns the stored note, or None if nothing was stored (a failed call or
    an empty note), in which case yesterday's stays, still carrying its date.
    A failure here is logged and does not count against the memory pass.
    """
    try:
        cortex.set_purpose("continuity note")
        raw = cortex.complete(cfg["llm"]["composer"], CONT_PROMPT,
                              "\n".join(_continuity_context(state)),
                              schema=CONT_SCHEMA)
        cont = _clean_continuity(
            json.loads(raw[raw.index("{"):raw.rindex("}") + 1]).get("continuity"))
    except Exception as e:
        log(f"continuity not written: {type(e).__name__}: {e}; yesterday's "
            f"note stays", level="warn")
        return None
    if not cont:
        log("continuity came back empty; yesterday's note stays", level="warn")
        return None
    state.note("continuity", cont)
    state.note("continuity_at", utcnow())
    return cont


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
    """Short-term, unexpired, not yet long, not pinned — the things eligible
    for promotion. A pinned memory is permanent already (audit F42)."""
    return state.db.execute(
        "SELECT id, ts, kind, text, use_count FROM memories"
        " WHERE COALESCE(tier,'short')='short' AND superseded_by IS NULL"
        "   AND COALESCE(expired,0)=0 AND COALESCE(pinned,0)=0"
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
    # DROPS ARE CAPPED TOO (audit F42). Promotions had a cap of 3 a day and
    # drops none: on 2026-11-08 the pass dropped 39 at once.
    drop_cap = int(m.get("max_drops_per_day", 8))
    # PINNED MEANS LONG TERM. The dashboard's pin used to set pinned and
    # leave the memory in short term, where this pass could drop it. The pin
    # route now moves it; this moves any pinned before that fix.
    state.db.execute("UPDATE memories SET tier='long', expires_at=NULL"
                     " WHERE COALESCE(pinned,0)=1 AND COALESCE(tier,'short')='short'"
                     " AND COALESCE(expired,0)=0")
    state.db.commit()
    # The search index, rebuilt once and whenever it drifts (audit F39).
    try:
        _ix = memory.repair_index(state)
        if _ix:
            log(f"memory pass: search index rebuilt: it had {_ix[0]} rows "
                f"for {_ix[1]} memories")
    except Exception as e:
        log(f"memory pass: the search index could not be rebuilt: {e}", level="warn")

    cands = candidates(state, cfg)
    # A QUIET DAY skips the memory call again (continuity, which needed it to
    # run, has its own call now) but still writes the note.
    if not cands:
        cont = write_continuity(state, cfg, log)
        state.note("last_consolidation", utcnow())
        state.note("consolidation_fails_today", "")
        log("consolidation: nothing in short term to consider"
            + (f"; continuity written ({len(cont)} chars)" if cont else ""))
        if say and cont:
            say("report", f"Daily memory pass \u00b7 nothing to sort today.\n"
                f"  continuity ({len(cont)} chars): {cont[:300]}"
                + ("\u2026" if len(cont) > 300 else ""), {"drive": "memory"})
        return "nothing to consolidate"
    have = long_term(state)
    body = [
        "SHORT TERM, eligible for promotion (id, age, times recalled):",
        *([f"  [{r['id']}] {r['ts'][:10]} recalled {r['use_count']}x — {r['text']}"
           for r in cands] or ["  (nothing in short term today)"]),
        "",
        "ALREADY IN LONG TERM — do not promote a restatement of any of these:",
        *([f"  [{r['id']}] {r['text']}" for r in have] or ["  (nothing yet)"]),
    ]
    prompt = PROMPT.format(ttl=ttl, cap=cap)
    try:
        cortex.set_purpose("memory pass")
        raw = cortex.complete(cfg["llm"]["composer"], prompt, "\n".join(body),
                              schema=SCHEMA)
        # json.loads ONLY. The old line routed to cortex.parse_proposal
        # whenever the string '"action"' appeared anywhere in the output —
        # including inside a memory's own text, since the candidate list is
        # echoed back. parse_proposal expects an action proposal and has no
        # idea what a consolidation plan is, so it failed, and the failure
        # repeated every wake for the rest of the day.
        plan = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
    except Exception as e:
        # BACK OFF. A failure used to return without marking anything, and
        # due() only looks at last_consolidation — so a pass that cannot
        # succeed retried on every wake, each costing up to 900 seconds of
        # composer-lock wait plus a generation. One bad day of output could
        # occupy the machine until midnight.
        #
        # THE COUNT CARRIES ITS DATE. It used to be a bare number reset only
        # by a success, so after one bad day the next day's first failure
        # was "4 of 3" and gave up at once; every later day got one attempt
        # until something succeeded. Stored as "YYYY-MM-DD:n" and restarted
        # when the day changes. A bare number left by the old code has no
        # date, so it reads as another day and starts again at 1.
        _day = utcnow()[:10]
        _d, _, _c = (state.note("consolidation_fails_today") or "").partition(":")
        _n = (int(_c) if _d == _day and _c.isdigit() else 0) + 1
        state.note("consolidation_fails_today", f"{_day}:{_n}")
        log(f"consolidation failed ({_n} of 3): {e}", level="warn")
        if _n >= 3:
            state.note("last_consolidation", utcnow())
            log("three failures today; not trying again until tomorrow",
                level="warn")
        return None

    valid = {r["id"] for r in cands}
    promoted, written, dropped, refused = [], [], [], []
    # Untrusted as the prompt treats them (cycle.py: only self and operator
    # memories go before <board>): board and incidental.
    _write_kind = ("board" if any(r["kind"] not in ("self", "operator") for r in cands)
                   else "self")

    # A MECHANICAL FILTER, not another line in the prompt.
    #
    # The prompt already says "DO NOT PROMOTE: anything you can look up:
    # board state, your own action log". On 2026-09-25 it promoted three
    # memories, all of them action log:
    #
    #   "I proposed reading the full thread of #6189 to understand..."
    #   "I proposed reading #6349 to see the full thread of..."
    #   "I proposed building a model for coupled detector stasis..."
    #
    # Those will be read every cycle forever and teach nothing. Long term is
    # the only store with no expiry, so anything wrong in it is wrong until
    # someone notices — and it is prompt weight in a prompt that has already
    # overflowed the context window three times.
    #
    # An instruction the model has ignored twice does not get a third
    # phrasing. It gets a check.
    _EVENT = re.compile(
        r"^\s*(i|you)\s+(proposed|read|tried|attempted|wanted|started|"
        r"selected|chose|decided to (read|propose))\b", re.I)

    for item in (plan.get("promote") or [])[:cap]:
        mid = item.get("id")
        if mid not in valid:
            refused.append(f"id {mid} is not a short-term candidate")
            continue
        _row = state.db.execute(
            "SELECT text FROM memories WHERE id=?", (mid,)).fetchone()
        if _row and _EVENT.match(_row["text"] or ""):
            refused.append(
                f"id {mid} is a record of what you did, not what you learned: "
                f"{' '.join((_row['text'] or '').split())[:70]}... Your action "
                f"log already has it. Long term is for what you would want to "
                f"know in a month without it.")
            continue
        state.db.execute(
            "UPDATE memories SET tier='long', expires_at=NULL WHERE id=?", (mid,))
        promoted.append((mid, item.get("why", "")[:200]))
    if len(plan.get("promote") or []) > cap:
        refused.append(f"{len(plan['promote'])} promotions proposed, cap is {cap}")

    # WRITES OBEY THE SAME RULES AS PROMOTIONS (H7c/d, audit 2026-10-27).
    # A long-term write went straight up, past the daily cap and the action-
    # log filter. And remember() returns an EXISTING id for a duplicate, which
    # this then re-tiered: a long-term memory worded like the new note was set
    # to short term with a 7-day expiry, and the report listed text that was
    # never stored. Now only a row remember() actually created is tiered, and
    # a long-term write must pass _EVENT and fit the cap, or goes to short term.
    # A LESSON STANDS ON WHAT IT CITES (2026-11-23). Two of the wrong
    # memories the operator retired by hand on 11-22 were written here, into
    # long term, which never expires: "The Marrow project is complete but
    # blocked by the 8-character minimum artifact name requirement; I must
    # rename the artifact" (1540), and its twin (1643). They stood on
    # refusal notes whose reasons were borrowed (memory.unfounded now keeps
    # those out), and a write carried no record of what it came from, so
    # nothing could check it. Now each write names its sources in "from".
    # A long-term one must cite at least one of today's candidates, and at
    # least half its words must be theirs, or it stays short term; it may
    # not repeat this prompt's own instructions; its sources go in `source`;
    # and memory.forget / a drop takes long term away from a lesson whose
    # source was found wrong (memory.demote_citing).
    _texts = {r["id"]: r["text"] or "" for r in cands}
    _prompt_runs = memory._word_runs(re.sub(r'"[^"]*"', " ", PROMPT))
    _long_written = 0
    for item in (plan.get("write") or [])[:cap]:
        tier = item.get("tier", "short")
        text = item.get("text") or ""
        _from = [i for i in (item.get("from") or []) if i in valid]
        if memory._word_runs(text) & _prompt_runs:
            refused.append(f"not written, it repeats this prompt's own words: "
                           f"{' '.join(text.split())[:70]}")
            continue
        if tier == "long":
            _cited = " ".join(_texts[i] for i in _from).lower()
            _w = {w for w in re.findall(r"[a-z0-9'#-]{4,}", text.lower())
                  if w not in memory._REASON_STOP}
            if _EVENT.match(text):
                refused.append(f"not written to long term, a record of what "
                               f"you did: {' '.join(text.split())[:70]}...; "
                               f"kept in short term")
                tier = "short"
            # By stem (the first five letters): "answers" stands on "answer".
            elif not _from or (_w and len({w for w in _w if w[:5] in _cited}) * 2 < len(_w)):
                refused.append(
                    f"not written to long term, it does not stand on what it "
                    f"cites ({_from or 'nothing'}): {' '.join(text.split())[:70]}; "
                    f"kept in short term")
                tier = "short"
            elif len(promoted) + _long_written >= cap:
                refused.append(f"long term is full for today (cap {cap}); "
                               f"kept in short term: "
                               f"{' '.join(text.split())[:70]}")
                tier = "short"
        _newest = state.db.execute(
            "SELECT COALESCE(MAX(id), 0) AS m FROM memories").fetchone()["m"]
        # NOT `self` WHEN A STRANGER'S WORDS WERE IN FRONT OF IT (audit F14).
        # Every write was stored as riffle's own, whatever it was distilled
        # from, so one board memory quoting a stranger came back as a long-
        # term `self` memory, shown before <board> where riffle's own words
        # are trusted. A write made while any board memory was a candidate
        # is filed as `board`, and is shown inside the board tags.
        # (Incidental notes count as a stranger's words here too.)
        mid = memory.remember(state, text, kind=_write_kind,
                              source=("consolidation:" + ",".join(map(str, _from))
                                      if _from else "consolidation"))
        if not mid:
            continue
        if mid <= _newest:
            refused.append(f"already memory {mid}, left as it was: "
                           f"{' '.join(text.split())[:70]}")
            continue
        exp = None if tier == "long" else _expiry(ttl)
        state.db.execute("UPDATE memories SET tier=?, expires_at=? WHERE id=?",
                         (tier, exp, mid))
        if tier == "long":
            _long_written += 1
        written.append((mid, tier, text[:120]))

    # NOT YOUR WORDS, AND NOT MORE THAN A HANDFUL (audit F42). A memory of
    # kind `operator` is what you told riffle; the pass may promote it but not
    # drop it. A pinned one is not a candidate at all (above).
    _kinds = {r["id"]: r["kind"] for r in cands}
    for item in (plan.get("drop") or []):
        mid = item.get("id")
        if mid not in valid:
            continue
        if _kinds.get(mid) == "operator":
            refused.append(f"id {mid} is your operator's own words; not dropped")
            continue
        if len(dropped) >= drop_cap:
            refused.append(f"more than {drop_cap} drops proposed; id {mid} and any "
                           f"after it kept for today")
            break
        _t = (state.db.execute("SELECT text FROM memories WHERE id=?",
                               (mid,)).fetchone() or {"text": ""})["text"] or ""
        state.db.execute("UPDATE memories SET expired=1 WHERE id=?", (mid,))
        memory.demote_citing(state, mid, ttl)
        dropped.append((mid, item.get("why", "")[:160], _t))

    # One of the candidates it passed over may go up anyway. This is the only
    # thing in long term that its own judgement did not choose, which is the
    # entire reason for keeping it.
    import random as _r
    from agent.memory import extra_count
    passed = [r["id"] for r in cands
              if r["id"] not in {m for m, _ in promoted}
              and r["id"] not in {d[0] for d in dropped}]
    # THE SAME TWO RULES APPLY HERE.
    #
    # These picks went straight to long term with neither check: they
    # bypassed `cap`, so a day could promote more than max_promotions_per_day
    # between the two paths, and they bypassed _EVENT, so the action-log
    # memories the filter exists to keep out went up anyway — by lottery.
    # The cap is load-bearing (a long-term shelf only stays worth reading if
    # it stays small) and the filter was written because this exact kind of
    # memory had already filled it once.
    #
    # Randomness is the point of this path, so it keeps it. It just cannot
    # outrank the rules the chosen promotions obey.
    lucky = []
    _room = max(0, cap - len(promoted) - _long_written)
    _eligible = [m for m in passed if not _EVENT.match(
        (state.db.execute("SELECT text FROM memories WHERE id=?",
                          (m,)).fetchone() or {"text": ""})["text"] or "")]
    for mid in _r.sample(_eligible,
                         min(extra_count(len(promoted), cfg), _room,
                             len(_eligible))):
        state.db.execute(
            "UPDATE memories SET tier='long', expires_at=NULL WHERE id=?", (mid,))
        row = state.db.execute("SELECT text FROM memories WHERE id=?",
                               (mid,)).fetchone()
        lucky.append((mid, row["text"]))

    # COMMITTED BEFORE THE MODEL CALL (audit F13). The promotions, drops and
    # writes above were left open across write_continuity, a composer call of
    # minutes (453 s on the box on 2026-11-14), and for all of it no other
    # connection could write: the dashboard's 30-second busy timeout ran out
    # and a chat message, an approval or a telemetry sample failed with
    # "database is locked". No model call with a write open.
    state.db.commit()
    # The continuity note, in its own call (see CONT_PROMPT).
    cont = write_continuity(state, cfg, log)
    state.note("last_consolidation", utcnow())
    state.note("consolidation_fails_today", "")

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
        # THE TEXT, NOT ONLY THE ID (F42): "dropped [812]: wrong", 39 times,
        # gave nothing to judge by.
        for mid, why, text in dropped:
            lines.append(f"  \u2717 dropped [{mid}] {' '.join(text.split())[:140]}"
                         f"\n    ({why[:120]})")
        for r in refused:
            lines.append(f"  refused: {r}")
        if cont:
            lines.append(f"  continuity ({len(cont)} chars): {cont[:300]}"
                         + ("\u2026" if len(cont) > 300 else ""))
        say("report", "\n".join(lines), {"drive": "memory"})
    return summary


def _continuity_context(state):
    """Everything the continuity writer reads, in its own call.

    Its previous note, so it revises rather than starts over; the open
    project; and its own last fifteen actions, newest first. Riffle's own
    words only, no board text: what lands in the note is read every cycle
    from the system prompt, so it should come from riffle, not from strangers.
    """
    out = ["YOUR CONTINUITY NOTE NOW:",
           "  " + cortex.render_continuity(state.note("continuity"),
                                           state.note("continuity_at"))
           .replace("\n", "\n  "), ""]
    try:
        p = project.active(state)        # a sqlite3.Row or None
    except Exception:
        p = None
    out.append("YOUR OPEN PROJECT: " + (f"{p['title']} \u2014 {p['question']}"
                                        if p else "none"))
    out += ["", "WHAT YOU DID RECENTLY, newest first:"]
    try:
        rows = state.recent_actions(15)
    except Exception:
        rows = []
    for r in rows:
        try:
            pl = json.loads(r["payload"] or "{}")
        except (ValueError, TypeError):
            pl = {}
        what = (pl.get("title") or pl.get("body") or r["rationale"] or "")
        out.append(f"  {(r['created_at'] or '')[:16]} {r['kind']} "
                   f"{r['status']} \u2014 {' '.join(str(what).split())[:110]}")
    if not rows:
        out.append("  (nothing yet)")
    return out


# Tag-shaped text could make the note look like structure in the system
# prompt (a stray <board> or </rules>). It is stripped, not escaped.
_TAG = re.compile(r"</?\s*[A-Za-z][^<>]{0,60}>")


def _clean_continuity(text):
    """The note as stored: tags removed, at most cortex.CONTINUITY_MAX chars.

    An over-long note is cut at a sentence end where one is near and marked,
    so a reader can tell a cut note from a short one.
    """
    t = _TAG.sub("", str(text or "")).strip()
    t = re.sub(r"\n{3,}", "\n\n", t)
    mark = " [cut to fit]"
    cap = cortex.CONTINUITY_MAX
    if len(t) > cap:
        cut = t[:cap - len(mark)]
        brk = cut.rfind(". ")
        if brk > len(cut) * 0.6:
            cut = cut[:brk + 1]
        t = cut.rstrip() + mark
    return t


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
    # Through forget(), not a raw DELETE (L13, audit 2026-10-27): the search
    # index is contentless and needs a row's text to drop its words, so the
    # purged memories' words stayed searchable, the bug forget() exists for.
    for (_mid,) in state.db.execute(
            "SELECT id FROM memories WHERE expired=1 AND pinned=0 AND expires_at < ?",
            (cutoff,)).fetchall():
        memory.forget(state, _mid)
    state.db.commit()
    if n and log:
        log(f"{n} short-term memory(ies) expired")
    return n
