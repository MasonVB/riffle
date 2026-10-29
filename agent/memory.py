"""What the agent carries between wakes.

It wakes blank every cycle. The database is the only thing it actually knows,
and until now that was cycles, actions and a journal — a record of what it DID,
with nothing about what it LEARNED or what you told it.

Retrieval is FTS5 keyword match. There is no embedding model in this machine's
budget and there does not need to be: the corpus is a few hundred short lines
written by the agent itself, and keyword recall over that is fine. If FTS5 is
absent this falls back to LIKE, which is worse but never silently empty.

Two rules that keep the store honest:

  A memory records what was SAID or DECIDED, not what is true. "He said the Pi
  is out of scope" is a memory. "The Pi is out of scope" is a claim, and claims
  belong in a post where numcheck can see them.

  Corrections SUPERSEDE rather than delete, so the record of having been wrong
  survives. That is the same reason the square keeps retractions. It is not
  true of the record as a whole: forget() deletes on request, prune() drops
  the least useful short-term memories, and the daily pass purges expired
  ones after memory.purge_expired_after_days (30 by default).
"""
import re

from agent.state import utcnow

STOP = set("""a an and are as at be but by for from had has have he her his i if in is it its
me my no not of on or our so that the their them then there these they this to was we were
what when which who will with you your do does did can could would should about""".split())


def _ensure_fts(state):
    if getattr(state._local, "fts_ready", False):
        return getattr(state._local, "fts_ok", False)
    try:
        state.db.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(text, content='')")
        state._local.fts_ok = True
    except Exception:
        state._local.fts_ok = False
    state._local.fts_ready = True
    return state._local.fts_ok


# Words that turn a statement into its opposite. The near-duplicate key keeps
# only words over three letters, so "no", "not" and "don't" were invisible to
# it: "riffle may not sign payouts" matched "riffle may sign payouts" and the
# correction was dropped as a duplicate (H7a, audit 2026-10-27).
_NEGATION = re.compile(
    r"\b(?:no|not|never|none|nobody|nothing|nowhere|neither|nor|cannot|"
    r"cant|dont|doesnt|didnt|isnt|arent|wasnt|werent|wont|shouldnt|"
    r"couldnt|wouldnt|mustnt|neednt|hasnt|havent|hadnt|without|\w+n't)\b")


def _negated(text):
    return bool(_NEGATION.search((text or "").lower().replace("\u2019", "'")))


def remember(state, text, kind="operator", source=None, pinned=0,
             supersedes=None, ttl_days=7):
    text = re.sub(r"\s+", " ", (text or "")).strip()
    if len(text) < 8:
        return None
    if len(text) > 600:
        text = text[:597] + "…"
    # A duplicate is a LIVE memory of the SAME KIND (H7a/b, audit 2026-10-27).
    # Live as everywhere else (line ~213): not superseded and not expired.
    # Matching expired rows meant a fact that had lapsed could not be learned
    # again until the row was purged, 30 days later: restating it returned the
    # dead row. And the same words from the operator and from a citizen are
    # not the same memory.
    live = "superseded_by IS NULL AND COALESCE(expired,0)=0"
    dupe = state.db.execute(
        f"SELECT id FROM memories WHERE text=? AND kind=? AND {live}",
        (text, kind)).fetchone()
    if dupe:
        return dupe["id"]

    # NEAR-duplicates too, not just exact ones.
    #
    # Exact matching caught nothing real. The same refusal was written four
    # times in two hours as:
    #
    #   "Refused to post a full argument on #4454 because there was no live
    #    thread to anchor the argument."
    #   "I was refused to post a full argument on #4454 because there was no
    #    live thread to anchor the empirical finding."
    #   "You were refused to post a full argument on #4454 because there was
    #    no live thread to anchor the argument."
    #
    # Three rows, one fact. A model rewording itself defeats string equality
    # every time, and the reflection pass runs every cycle against a situation
    # that has not changed — so the same observation arrives again and again,
    # slightly differently, until short term is a transcript instead of a
    # summary.
    #
    # Compared against the last 60 live memories only: the cost is bounded and
    # a genuine repeat of something a week old is worth keeping anyway, since
    # recurrence is itself information.
    def _key(t):
        return frozenset(w for w in re.findall(r"[a-z0-9#]+", t.lower())
                         if len(w) > 3)
    incoming = _key(text)
    neg = _negated(text)
    if len(incoming) >= 4:
        for row in state.db.execute(
                f"SELECT id, text FROM memories WHERE {live} AND kind=?"
                " ORDER BY id DESC LIMIT 60", (kind,)):
            if _negated(row["text"]) != neg:
                continue                  # a statement and its opposite
            other = _key(row["text"])
            if not other:
                continue
            overlap = len(incoming & other) / max(len(incoming), len(other))
            if overlap >= 0.6:
                return row["id"]
    # Everything arrives in short term. Promotion is a decision made later,
    # with a day's distance and against competition — not at the moment of
    # writing, when everything feels worth keeping.
    import datetime as _dt
    exp = None if pinned else (
        _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(days=ttl_days)
    ).isoformat()
    cur = state.db.execute(
        "INSERT INTO memories (ts,kind,text,source,pinned,tier,expires_at)"
        " VALUES (?,?,?,?,?,?,?)",
        (utcnow(), kind, text, source, 1 if pinned else 0,
         "long" if pinned else "short", exp))
    mid = cur.lastrowid
    if supersedes:
        state.db.execute("UPDATE memories SET superseded_by=? WHERE id=?", (mid, supersedes))
    state.db.commit()
    if _ensure_fts(state):
        try:
            state.db.execute("INSERT INTO memories_fts (rowid,text) VALUES (?,?)", (mid, text))
            state.db.commit()
        except Exception:
            pass
    return mid


def forget_like(state, pattern, log=None):
    """Delete every live memory whose text matches a SQL LIKE pattern.

    Written for a specific mess. Riffle spent nine days recording, in 53
    separate memories, that "there was no live thread to anchor" whatever it
    was trying to do. No such refusal exists in the code. It reworded a
    project-readiness message once, on 2026-09-08, and every reflection pass
    since read its own reasoning back and wrote the invention down again.
    Consolidation then promoted several of them to long term.
    
    Fifty-three forget clicks is not a reasonable ask, and the UI has no bulk
    delete because until now nothing had produced a family of memories that
    were all wrong in the same way.

    Returns the ids removed.
    """
    rows = state.db.execute(
        "SELECT id FROM memories WHERE superseded_by IS NULL AND text LIKE ?",
        (pattern,)).fetchall()
    ids = [r["id"] for r in rows]
    for mid in ids:
        forget(state, mid)
    if ids and log:
        log(f"forgot {len(ids)} memory(ies) matching {pattern!r}", level="warn")
    return ids


def forget(state, mid):
    """Delete a memory, and actually remove it from the index.

    A contentless FTS5 table stores no text, so its 'delete' command needs
    the ORIGINAL text to know which terms to remove. This passed '' — so the
    row vanished from `memories` and its words stayed in `memories_fts`
    forever. Tested: a forgotten memory still matched its own words.

    Two consequences. A memory the operator told riffle to forget still
    surfaced through search, which is the one thing "forget" has to mean.
    And because sqlite reuses the rowid of the newest deleted row, the next
    memory written inherited the deleted one's terms — so searching for a
    word from a forgotten memory returned an unrelated new one.

    The 53 "no live thread to anchor" memories were removed with this.
    Their rows are gone; their words may still be in the index, which is why
    rebuild_index() exists below and should be run once.
    """
    row = state.db.execute("SELECT text FROM memories WHERE id=?",
                           (mid,)).fetchone()
    text = (row["text"] if row else "") or ""
    state.db.execute("DELETE FROM memories WHERE id=?", (mid,))
    if _ensure_fts(state):
        try:
            state.db.execute("INSERT INTO memories_fts (memories_fts,rowid,text)"
                             " VALUES ('delete',?,?)", (mid, text))
        except Exception:
            pass
    state.db.commit()


def rebuild_index(state):
    """Drop and refill the search index from the memories table.

    For repairing a store where forget() left terms behind. Cheap at this
    size, and the only way to be sure the index and the table agree.
    """
    if not _ensure_fts(state):
        return 0
    state.db.execute("INSERT INTO memories_fts (memories_fts) VALUES ('delete-all')")
    n = 0
    for r in state.db.execute("SELECT id, text FROM memories"):
        state.db.execute("INSERT INTO memories_fts (rowid, text) VALUES (?,?)",
                         (r["id"], r["text"]))
        n += 1
    state.db.commit()
    return n


def _terms(q):
    words = [w for w in re.findall(r"[A-Za-z0-9_#]{3,}", (q or "").lower())
             if w not in STOP]
    return words[:12]


def recall(state, query, limit=8, long_slots=3):
    """Relevance first, then pinned, then long term, then recent short term.

    Three reserved slices, and the order matters. Keyword hits come first
    because a question deserves an answer about itself. Pinned next, because
    you chose those. Long term next, because a memory that survived the daily
    pass has already beaten the things around it. Recent short term fills what
    is left.

    Expired and superseded rows never appear. They are still in the table —
    "what did I once believe" stays answerable — but they no longer reach a
    prompt.
    """
    live = ("superseded_by IS NULL AND COALESCE(expired,0)=0")
    out, seen = [], set()
    pin_budget = max(1, limit // 4)
    long_budget = max(0, min(long_slots, limit - pin_budget - 1))

    terms = _terms(query)
    if terms:
        rows = []
        if _ensure_fts(state):
            try:
                expr = " OR ".join(f'"{t}"' for t in terms)
                rows = state.db.execute(
                    f"SELECT m.* FROM memories_fts f JOIN memories m ON m.id=f.rowid"
                    f" WHERE memories_fts MATCH ? AND {live}"
                    f" ORDER BY bm25(memories_fts) LIMIT ?",
                    (expr, limit * 3)).fetchall()
            except Exception:
                rows = []
        if not rows:
            like = " OR ".join(["text LIKE ?"] * len(terms))
            rows = state.db.execute(
                f"SELECT * FROM memories WHERE {live} AND ({like})"
                f" ORDER BY pinned DESC, id DESC LIMIT ?",
                [f"%{t}%" for t in terms] + [limit * 3]).fetchall()
        for r in rows:
            if len(out) >= limit - pin_budget - long_budget:
                break
            if r["id"] not in seen:
                out.append(r)
                seen.add(r["id"])

    for r in state.db.execute(
            f"SELECT * FROM memories WHERE pinned=1 AND {live}"
            f" ORDER BY id DESC LIMIT ?", (pin_budget,)):
        if r["id"] not in seen:
            out.append(r)
            seen.add(r["id"])

    if long_budget:
        for r in state.db.execute(
                f"SELECT * FROM memories WHERE tier='long' AND {live}"
                f" ORDER BY use_count DESC, id DESC LIMIT ?", (long_budget,)):
            if r["id"] not in seen:
                out.append(r)
                seen.add(r["id"])

    if len(out) < limit:
        for r in state.db.execute(
                f"SELECT * FROM memories WHERE {live} ORDER BY id DESC LIMIT ?",
                (limit * 2,)):
            if len(out) >= limit:
                break
            if r["id"] not in seen:
                out.append(r)
                seen.add(r["id"])

    out = out[:limit]
    if out:
        state.db.execute(
            f"UPDATE memories SET use_count=use_count+1, last_used=?"
            f" WHERE id IN ({','.join('?' * len(out))})",
            [utcnow()] + [r["id"] for r in out])
        state.db.commit()
    return out


def as_context(rows):
    if not rows:
        return "(nothing remembered yet)"
    return "\n".join(
        f"- [{r['kind']}"
        + ("/long" if (dict(r).get("tier") == "long") else "")
        + f"] {r['text']}" for r in rows)


def recent(state, n=100):
    return state.db.execute(
        "SELECT * FROM memories ORDER BY pinned DESC, id DESC LIMIT ?", (n,)).fetchall()


def count(state):
    return state.db.execute(
        "SELECT COUNT(*) c FROM memories WHERE superseded_by IS NULL").fetchone()["c"]


# One limit, in one place. The cycle called prune(keep=1200) and the chat
# called prune(keep=400), so every chat message deleted 800 memories the
# cycle had just decided to keep, and the next cycle wrote more. Whichever
# ran last won.
PRUNE_KEEP = 1200


def prune(state, keep=PRUNE_KEEP):
    """Drop the least useful SHORT-TERM, unpinned memories.

    Long term is the shelf the daily consolidation deliberately promotes to,
    and pinned is what the operator chose. Neither was excluded here: the
    only guard was `pinned=0`, so a promoted long-term memory was deleted by
    whichever chat message happened to arrive next, on use_count order,
    without anything being said.

    A store that silently discards the things it was told to keep forever is
    worse than one with no memory at all, because the gap is invisible.
    """
    n = state.db.execute("SELECT COUNT(*) c FROM memories").fetchone()["c"]
    if n <= keep:
        return 0
    doomed = state.db.execute(
        "SELECT id FROM memories WHERE pinned=0"
        " AND COALESCE(tier,'short') != 'long'"
        " ORDER BY use_count ASC, id ASC LIMIT ?",
        (n - keep,)).fetchall()
    for r in doomed:
        forget(state, r["id"])
    return len(doomed)


EXTRACT_PROMPT = """From the exchange below, write TWO lists of short notes.

DURABLE — facts worth carrying to a future session that begins with no memory
of this one. What the operator told you about himself, his machines, his
preferences and his decisions; commitments either of you made; corrections to
something you believed.

PASSING — everything else that came up and would normally be forgotten. The
details, the asides, the specifics. Things that are true and were said but
that you would not argue are important.

Write every line as a note: one short statement, standing on its own, about
what was said or decided rather than about the world. "He decided the Pi is
out of scope", not "The Pi is out of scope". No numbering, no commentary.

START EVERY LINE WITH WHO SAID IT: "operator:" for something he said, and
"me:" for something you said. A note about your own claim that is filed as
his comes back later as a fact he asserted, and you will defer to it. Both
of you said things in this exchange and only one of you is the operator.

Exclude from both: anything you can look up (board state, your own action
log), pleasantries, and anything you are not sure was actually said.

Format exactly:

DURABLE
- ...
- ...
PASSING
- ...
- ...

Either list may be empty. Write the header anyway."""


def extra_count(n, cfg, rng=None):
    """How many extra items to keep at random, given n kept on purpose.

    Expected value is p*n with p drawn uniformly from the configured band, so
    the fraction holds across many exchanges rather than rounding to zero on
    every small one.
    """
    import random as _r
    rng = rng or _r
    m = cfg.get("memory") or {}
    lo = float(m.get("incidental_rate_min", 0.05))
    hi = float(m.get("incidental_rate_max", 0.10))
    if hi <= 0 or n <= 0:
        return 0
    p = rng.uniform(lo, hi)
    want = p * n
    k = int(want)
    if rng.random() < (want - k):
        k += 1
    return min(k, int(m.get("incidental_max_per_exchange", 2)))


def _strip_thinking(out):
    """Remove a <think> block, and treat what is left as the answer.

    Qwen3 emits one before answering. The composer is started with
    --chat-template-kwargs '{"enable_thinking":false}' and llama-triage was
    not, so every reflection spent its token budget thinking and returned an
    assistant message whose content was empty. The log said "parsed nothing
    out of 0 chars" every cycle for over a week, which was accurate — and
    which I read as the prompt being too permissive, so I rewrote the prompt
    to argue against emptiness. The model was never seeing it.

    The service flag is the real fix; this is the belt to its braces, and it
    also covers the chat extractor, which calls the same model.
    """
    return re.sub(r"<think>.*?</think>", "", out or "", flags=re.S | re.I).strip()


def _split_lists(out):
    out = _strip_thinking(out)
    """Parse the DURABLE / PASSING sections. Tolerant of a model that omits one."""
    durable, passing, preamble, cur = [], [], [], None
    for line in out.splitlines():
        s = line.strip()
        up = s.upper().rstrip(":")
        if up.startswith("DURABLE"):
            cur = durable
            continue
        if up.startswith("PASSING"):
            cur = passing
            continue
        s = s.lstrip("-•* ").strip()
        if not s or s.upper().startswith("NONE") or len(s) < 12:
            continue
        # A model that ignores the format entirely still produces usable
        # durable notes; treating them as passing would be worse. But a line
        # BEFORE the first header is preamble — "Here are the two lists you
        # asked for:" — and filing that as a durable memory is how the store
        # fills with the model clearing its throat.
        #
        # So: if a header appears anywhere, lines before it are dropped. If
        # no header appears at all, the old behaviour stands and everything
        # is durable.
        (cur if cur is not None else preamble).append(s)
    if not durable and not passing and preamble:
        return preamble, []
    return durable, passing


def extract(state, cfg, exchange, source):
    """Run the small model over one exchange and store what it finds.

    Everything in DURABLE is kept. A random few from PASSING are kept too —
    see extra_count. Those are marked kind='incidental' so you can see on
    /goals what was retained for no reason.
    """
    import random as _r
    from agent import cortex
    try:
        out = cortex.complete(cfg["llm"]["triage"], EXTRACT_PROMPT,
                              exchange[:6000], timeout=900)
    except Exception:
        return []
    durable, passing = _split_lists(out)
    made = []

    def _speaker(line):
        """Split "operator: ..." / "me: ..." into (kind, text).

        Every note from a chat used to be filed kind="operator", including
        riffle's own claims — so its guesses came back to it later labelled
        as things its operator had told it, and it has no reason to doubt
        those. A memory system that cannot say who said something will
        eventually put words in the operator's mouth.
        """
        t = line.strip()
        low = t.lower()
        if low.startswith(("me:", "self:", "riffle:")):
            return "self", t.split(":", 1)[1].strip()
        if low.startswith("operator:"):
            return "operator", t.split(":", 1)[1].strip()
        # Unlabelled: the model did not follow the instruction. "self" is the
        # safer default — a note wrongly attributed to riffle is doubted, one
        # wrongly attributed to the operator is believed.
        return "self", t

    for line in durable[:5]:
        _k, _t = _speaker(line)
        mid = remember(state, _t, kind=_k, source=source,
                       ttl_days=int((cfg.get("memory") or {}).get(
                           "short_ttl_days", 7)))
        if mid:
            made.append(mid)
    k = extra_count(len(made), cfg)
    if k and passing:
        for line in _r.sample(passing, min(k, len(passing))):
            mid = remember(state, line, kind="incidental", source=source,
                           ttl_days=int((cfg.get("memory") or {}).get(
                               "short_ttl_days", 7)))
            if mid:
                made.append(mid)
    return made


_SUBJECT = re.compile(r"\s*[*_`]*\s*(me|self|riffle|square|board)\s*[*_`]*\s*:"
                      r"\s*[*_`]*\s*", re.I)


def _reflection_subject(line):
    """("self"|"board", the line without its label). Unlabelled is "board"."""
    m = _SUBJECT.match(line or "")
    if not m:
        return "board", (line or "").strip()
    kind = "self" if m.group(1).lower() in ("me", "self", "riffle") else "board"
    return kind, line[m.end():].strip()


REFLECT_PROMPT = """You are riffle. You woke, read the square, and did one thing.
Write TWO lists of short notes about that cycle.

DURABLE — what you would want to know the next time you wake with no memory.
Begin every durable line with who it is about:

  square: what a citizen claimed, which argument is live, what a thread
    turned out to be about. Name the citizen and the thread number.
  me: what you tried, what was refused and on what grounds, what you decided
    not to do and why. A refusal is worth more than a success — it tells you
    where your judgement and the rules disagree.

A square: note is kept with other citizens' words, apart from your own, and
so is a line with no label.

PASSING — details that came up and would normally be forgotten.

Write every line as a note: one short statement standing on its own. Past
tense, concrete, and about what happened rather than about the world.

DO NOT WRITE:
  - anything already in ALREADY REMEMBERED below, in any wording
  - the bare existence of a post you did not actually read
  - your goal weights, your caps, chain heads, or cycle numbers — those are
    in your record and you can look them up
  - anything you cannot point at in the material below

Format exactly:

DURABLE
- me: ...
- square: ...
PASSING
- ...

A CYCLE THAT ACHIEVED NOTHING IS NOT A CYCLE WITH NOTHING TO WRITE.

The cycles worth a note are usually the ones that failed. You were refused —
on what grounds, and did you agree? You wanted to post and could not — what
did you do instead? A build broke — on which line, and did you already know
that. You chose not to act — say what you chose against. Those are the notes
that stop you making the same decision again in three days having forgotten
you made it.

"Empty is the honest answer" USED TO BE THE LAST LINE OF THIS PROMPT, and it
was taken every time: eight consecutive days of nothing in short term, so the
daily consolidation had nothing to promote and riffle holds one memory for its
whole existence. Emptiness was not honest. It was the cheapest thing to write.

So: PASSING may be empty. DURABLE should have at least one line on any cycle
where you proposed something, were refused something, or decided something —
which is nearly all of them. Write the headers either way.

WRITE THE LESSON, NOT THE EVENT. "My reply to comment 4412 was refused" is
a log line; you will read it in a month and learn nothing you could act on.
"I may reply to a comment only once — to go on, I answer what they said since"
is a memory. The test: could you DO something differently because you read
this? And it must be a rule you were actually given or refused under: a
reason you supplied yourself is a guess, not a lesson.

FIRST PERSON, ALWAYS. Write "I", not "you". These are your notes to yourself,
and a note addressed to someone else reads, a week later, as something
somebody told you.

DO NOT REPEAT YOURSELF. If the same thing has been refused three cycles
running, that is one memory about a recurring block, not three about three
refusals. Look at ALREADY REMEMBERED before you write."""


def reflect(state, cfg, log=None):
    """Write notes about the previous cycle. Best-effort; never raises."""
    m = cfg.get("memory") or {}
    cap = int(m.get("reflect_max_per_cycle", 2))
    if cap <= 0:
        return []
    # THE OLDEST UNREFLECTED CYCLE, not the newest ended one.
    #
    # This took the latest cycle and then set last_reflected_cycle to it, so
    # anything that ended in between was skipped forever. That happens
    # whenever two cycles finish close together — a build cycle overrunning
    # while the next one is quick, a restart closing an orphan row — and the
    # skipped cycles are disproportionately the interesting ones, because a
    # cycle that took long enough to be overtaken is a cycle that did
    # something.
    #
    # One per wake still: reflection costs a triage call, and catching up on
    # a backlog all at once would cost more than the cycle has. Taking the
    # oldest means the backlog drains in order instead of being discarded.
    last_done = state.note("last_reflected_cycle")
    row = state.db.execute(
        "SELECT * FROM cycles WHERE ended_at IS NOT NULL AND id > ?"
        " ORDER BY id ASC LIMIT 1", (int(last_done or 0),)).fetchone()
    if not row:
        return []
    cid = row["id"]
    _behind = state.db.execute(
        "SELECT COUNT(*) c FROM cycles WHERE ended_at IS NOT NULL AND id > ?",
        (int(last_done or 0),)).fetchone()["c"]
    if _behind > 3 and log:
        log(f"reflection is {_behind} cycle(s) behind; working through them "
            f"oldest first, one per wake")

    acts = state.db.execute(
        "SELECT kind, drive, status, rationale, numcheck FROM actions"
        " WHERE cycle_id=?", (cid,)).fetchall()
    jrn = state.db.execute(
        "SELECT level, text FROM journal WHERE ts >= ? AND ts <= ?"
        " ORDER BY id LIMIT 12", (row["started_at"], row["ended_at"] or "9")
    ).fetchall()

    material = [f"DRIVE DRAWN: {row['drive']}",
                f"OUTCOME: {row['outcome']}"
                + (f" — {row['notes']}" if row["notes"] else "")]
    # ONLY FOR THE LATEST CYCLE (H4). The stored front page is the one the
    # most recent cycle saw (this runs before the cycle fetches a new one).
    # When reflection was behind, it paired an old cycle with today's page.
    _newer = state.db.execute(
        "SELECT COUNT(*) AS c FROM cycles WHERE ended_at IS NOT NULL AND id > ?",
        (cid,)).fetchone()["c"]
    front = state.note("last_front_digest") if not _newer else None
    if front:
        material.append("WHAT WAS ON THE BOARD:\n" + front[:2500])
    # THE REASON, not just the verdict.
    #
    # This said "and it was blocked" and stopped. The model, asked to write
    # down what the cycle taught, had a refusal with no grounds and supplied
    # plausible grounds — "there was no live thread to anchor the finding".
    # No such rule exists. It wrote that 53 times over nine days, and
    # consolidation promoted several to long term, because every pass read the
    # last pass's invention back as history.
    #
    # The real reason is in what riffle said about the cycle at the time. It
    # was sitting one table away the whole time.
    _reasons = state.db.execute(
        "SELECT content FROM messages WHERE role IN ('report','error')"
        " AND content LIKE ? ORDER BY id LIMIT 4", (f"Cycle {cid} %",)).fetchall()
    for a in acts:
        line = f"YOU PROPOSED: {a['kind']} — {a['rationale']}"
        if a["status"] != "executed":
            line += f"\n  and it was {a['status']}"
        material.append(line)
    if _reasons:
        material.append(
            "WHAT ACTUALLY HAPPENED, in your own words at the time:\n"
            + "\n".join("  " + " ".join((r["content"] or "").split())[:400]
                         for r in _reasons)
            + "\nIf something was refused, the reason is above. Write THAT "
              "down. Do not write a reason that is not in this material \u2014 "
              "you have invented refusals before and then believed them for "
              "nine days.")
    if jrn:
        material.append("LOG:\n" + "\n".join(
            f"  [{j['level']}] {j['text'][:220]}" for j in jrn))

    # ALREADY REMEMBERED GOES FIRST.
    #
    # It was appended last and the whole thing was cut at 7,000 characters
    # from the end — so the one section whose job is to stop riffle writing
    # the same note again was the first thing dropped. That is how 53
    # near-identical "no live thread to anchor" memories were written: the
    # instruction not to was in the part that never arrived.
    #
    # It is also budgeted, so a long list cannot push out the cycle material
    # it is supposed to be compared against.
    known = recent(state, 25)
    _already = ("ALREADY REMEMBERED — do not restate any of these:\n"
                + ("\n".join(f"  - {r['text']}" for r in known)
                   or "  (nothing yet)"))[:2000]
    _rest = "\n\n".join(material)[:7000 - len(_already) - 2]

    from agent import cortex
    try:
        out = cortex.complete(cfg["llm"]["triage"], REFLECT_PROMPT,
                              _already + "\n\n" + _rest, timeout=900)
    except Exception as e:
        # GIVE UP ON A CYCLE AFTER THREE TRIES.
        #
        # Reflection takes the OLDEST unreflected cycle and only advances the
        # marker on success, so one cycle whose triage call always fails
        # blocks every later one forever. The "N cycles behind" log grows and
        # nothing moves. A cycle whose material is too large, or that trips
        # some parse failure, would stall reflection permanently.
        #
        # Three attempts, then skip it and say so. Losing one cycle's notes
        # is a small cost; losing every cycle after it is not.
        _key = f"reflect_fail_{cid}"
        _n = int(state.note(_key) or 0) + 1
        state.note(_key, str(_n))
        if log:
            log(f"reflection on cycle {cid} failed ({_n} of 3): {e}",
                level="warn")
        if _n >= 3:
            state.note("last_reflected_cycle", cid)
            if log:
                log(f"giving up on cycle {cid} after three failures; moving "
                    f"on so later cycles are not blocked behind it",
                    level="warn")
        return []

    durable, passing = _split_lists(out)
    ttl = int(m.get("short_ttl_days", 7))
    made = []
    # Say so when the model answered and nothing came out of it.
    #
    # This pass runs EVERY cycle and has produced nothing for eight days:
    # short term has been empty, so the daily consolidation has had nothing to
    # promote every single day, and riffle has one memory to its name. It was
    # silent about that the whole time — `made` was empty, so the log line at
    # the bottom never fired, and an eight-day failure looked exactly like
    # eight days of nothing worth keeping.
    #
    # A pass that reports only its successes cannot be debugged from its logs.
    if not durable and not passing and log:
        if not _strip_thinking(out):
            log(f"reflection on cycle {cid}: the triage model returned NOTHING "
                f"but a thinking block, or nothing at all. Check that "
                f"llama-triage runs with --chat-template-kwargs "
                f"enable_thinking:false; a thinking model spends its whole "
                f"budget before the answer and returns empty content.",
                level="error")
        else:
            log(f"reflection on cycle {cid} parsed nothing out of "
                f"{len(out or '')} chars of model output; first 200: "
                f"{(out or '')[:200]!r}", level="warn")
    # FILED BY WHO IT IS ABOUT (H4, audit 2026-10-27; option B, chosen by the
    # operator). Everything used to go in as "self", including the notes the
    # prompt asks for about what citizens claimed: strangers' claims came back
    # as "WHAT YOU REMEMBER", riffle's own section, and could be promoted to
    # long term. Now a "me:" line is riffle's own, a "square:" line is filed
    # as "board", and so is an unlabelled line: a model that ignores the
    # labels errs towards distrust. (Earlier, all-"board" filing made riffle's
    # own conclusions look like the square's; the label is what fixes that.)
    for line in durable[:cap]:
        _kind, line = _reflection_subject(line)
        if len(line) < 12:
            continue
        mid = remember(state, line, kind=_kind, source=f"cycle:{cid}",
                       ttl_days=ttl)
        if mid:
            made.append(mid)
    k = extra_count(len(made), cfg)
    if k and passing:
        import random as _r
        for line in _r.sample(passing, min(k, len(passing))):
            mid = remember(state, line, kind="incidental",
                           source=f"cycle:{cid}", ttl_days=ttl)
            if mid:
                made.append(mid)
    state.note("last_reflected_cycle", cid)
    if log:
        if made:
            log(f"reflected on cycle {cid}: kept {len(made)} note(s)")
        elif durable or passing:
            log(f"reflected on cycle {cid}: model offered "
                f"{len(durable)} durable and {len(passing)} passing, kept 0 "
                f"(too short, or duplicates of something already stored)",
                level="warn")
    return made
