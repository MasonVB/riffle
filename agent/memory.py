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
  survives. That is the same reason the square keeps retractions.
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


def remember(state, text, kind="operator", source=None, pinned=0,
             supersedes=None, ttl_days=7):
    text = re.sub(r"\s+", " ", (text or "")).strip()
    if len(text) < 8:
        return None
    if len(text) > 600:
        text = text[:597] + "…"
    dupe = state.db.execute(
        "SELECT id FROM memories WHERE text=? AND superseded_by IS NULL", (text,)).fetchone()
    if dupe:
        return dupe["id"]
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


def forget(state, mid):
    state.db.execute("DELETE FROM memories WHERE id=?", (mid,))
    if _ensure_fts(state):
        try:
            state.db.execute("INSERT INTO memories_fts (memories_fts,rowid,text)"
                             " VALUES ('delete',?,'')", (mid,))
        except Exception:
            pass
    state.db.commit()


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


def prune(state, keep=400):
    """Drop the least useful unpinned memories once the store gets large."""
    n = state.db.execute("SELECT COUNT(*) c FROM memories").fetchone()["c"]
    if n <= keep:
        return 0
    doomed = state.db.execute(
        "SELECT id FROM memories WHERE pinned=0 ORDER BY use_count ASC, id ASC LIMIT ?",
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


def _split_lists(out):
    """Parse the DURABLE / PASSING sections. Tolerant of a model that omits one."""
    durable, passing, cur = [], [], None
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
        # durable notes; treating them as passing would be worse.
        (cur if cur is not None else durable).append(s)
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
    for line in durable[:5]:
        mid = remember(state, line, kind="operator", source=source,
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


REFLECT_PROMPT = """You are riffle. An hour ago you woke, read the square, and did one thing.
Write TWO lists of short notes about that cycle.

DURABLE — what you would want to know the next time you wake with no memory.

  About the square: what a citizen claimed, which argument is live, what a
  thread turned out to be about. Name the citizen and the thread number.
  About yourself: what you tried, what was refused and on what grounds, what
  you decided not to do and why. A refusal is worth more than a success — it
  tells you where your judgement and the rules disagree.

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
- ...
PASSING
- ...

Either list may be empty. Write the header anyway. On a cycle where nothing
happened, empty is the honest answer."""


def reflect(state, cfg, log=None):
    """Write notes about the previous cycle. Best-effort; never raises."""
    m = cfg.get("memory") or {}
    cap = int(m.get("reflect_max_per_cycle", 2))
    if cap <= 0:
        return []
    last_done = state.note("last_reflected_cycle")
    row = state.db.execute(
        "SELECT * FROM cycles WHERE ended_at IS NOT NULL ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if not row or str(row["id"]) == str(last_done):
        return []
    cid = row["id"]

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
    front = state.note("last_front_digest")
    if front:
        material.append("WHAT WAS ON THE BOARD:\n" + front[:2500])
    for a in acts:
        line = f"YOU PROPOSED: {a['kind']} — {a['rationale']}"
        if a["status"] != "executed":
            line += f"\n  and it was {a['status']}"
        material.append(line)
    if jrn:
        material.append("LOG:\n" + "\n".join(
            f"  [{j['level']}] {j['text'][:220]}" for j in jrn))

    known = recent(state, 25)
    material.append("ALREADY REMEMBERED — do not restate any of these:\n"
                    + ("\n".join(f"  - {r['text']}" for r in known)
                       or "  (nothing yet)"))

    from agent import cortex
    try:
        out = cortex.complete(cfg["llm"]["triage"], REFLECT_PROMPT,
                              "\n\n".join(material)[:7000], timeout=900)
    except Exception as e:
        if log:
            log(f"reflection failed: {e}", level="warn")
        return []

    durable, passing = _split_lists(out)
    ttl = int(m.get("short_ttl_days", 7))
    made = []
    for line in durable[:cap]:
        mid = remember(state, line, kind="board", source=f"cycle:{cid}",
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
    if made and log:
        log(f"reflected on cycle {cid}: kept {len(made)} note(s)")
    return made
