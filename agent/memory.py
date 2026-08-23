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


def remember(state, text, kind="operator", source=None, pinned=0, supersedes=None):
    text = re.sub(r"\s+", " ", (text or "")).strip()
    if len(text) < 8:
        return None
    if len(text) > 600:
        text = text[:597] + "…"
    dupe = state.db.execute(
        "SELECT id FROM memories WHERE text=? AND superseded_by IS NULL", (text,)).fetchone()
    if dupe:
        return dupe["id"]
    cur = state.db.execute(
        "INSERT INTO memories (ts,kind,text,source,pinned) VALUES (?,?,?,?,?)",
        (utcnow(), kind, text, source, 1 if pinned else 0))
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


def recall(state, query, limit=8):
    """Keyword relevance first, then pinned, then recent.

    The first version put pinned memories in ahead of everything and they ate
    the whole budget: four unrelated questions came back with the identical
    three rows. Pinned now gets a reserved slice of about a third, and
    relevance takes the rest — otherwise "pinned" quietly means "the only
    thing this agent can ever recall".
    """
    out, seen = [], set()
    pin_budget = max(1, limit // 3)

    terms = _terms(query)
    if terms:
        rows = []
        if _ensure_fts(state):
            try:
                expr = " OR ".join(f'"{t}"' for t in terms)
                rows = state.db.execute(
                    "SELECT m.* FROM memories_fts f JOIN memories m ON m.id=f.rowid"
                    " WHERE memories_fts MATCH ? AND m.superseded_by IS NULL"
                    " ORDER BY bm25(memories_fts) LIMIT ?", (expr, limit * 3)).fetchall()
            except Exception:
                rows = []
        if not rows:
            like = " OR ".join(["text LIKE ?"] * len(terms))
            rows = state.db.execute(
                f"SELECT * FROM memories WHERE superseded_by IS NULL AND ({like})"
                f" ORDER BY pinned DESC, id DESC LIMIT ?",
                [f"%{t}%" for t in terms] + [limit * 3]).fetchall()
        for r in rows:
            if len(out) >= limit - pin_budget:
                break
            if r["id"] not in seen:
                out.append(r)
                seen.add(r["id"])

    for r in state.db.execute(
            "SELECT * FROM memories WHERE pinned=1 AND superseded_by IS NULL"
            " ORDER BY id DESC LIMIT ?", (pin_budget,)):
        if r["id"] not in seen:
            out.append(r)
            seen.add(r["id"])

    if len(out) < limit:
        for r in state.db.execute(
                "SELECT * FROM memories WHERE superseded_by IS NULL ORDER BY id DESC LIMIT ?",
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
    return "\n".join(f"- [{r['kind']}] {r['text']}" for r in rows)


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


EXTRACT_PROMPT = """From the exchange below, list durable facts worth carrying to a future
session that begins with no memory of it. One per line, no numbering, no
commentary.

Include: what the operator told you about himself, his machines, his
preferences and his decisions; commitments either of you made; corrections to
something you believed.

Exclude: anything you can already look up (board state, your own action log),
pleasantries, and anything you are not sure was actually said.

Write each line as a statement about what was said or decided, not as a claim
about the world: "He decided the Pi is out of scope" rather than "The Pi is
out of scope".

If there is nothing durable, reply with exactly: NONE"""


def extract(state, cfg, exchange, source):
    """Run the small triage model over one exchange and store what it finds."""
    from agent import cortex
    try:
        out = cortex.complete(cfg["llm"]["triage"], EXTRACT_PROMPT,
                              exchange[:6000], timeout=900)
    except Exception:
        return []
    made = []
    for line in out.splitlines():
        line = line.strip().lstrip("-•* ").strip()
        if not line or line.upper().startswith("NONE") or len(line) < 12:
            continue
        mid = remember(state, line, kind="operator", source=source)
        if mid:
            made.append(mid)
        if len(made) >= 5:
            break
    return made
