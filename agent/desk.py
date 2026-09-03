"""The desk. Things riffle is working on, kept in view until it clears them.

WHY THIS EXISTS

Everything the agent produced used to live in a single overwritten note slot:
`last_build`, `last_fetch`, `last_signature`, `last_front_digest`. Four
hand-wired keys, each holding exactly one thing, each destroyed by the next
thing of that kind. Fetch the docket and your last build's source is still
there; fetch twice and the docket you wanted is gone. That is not a desk, it
is a spike file with four spikes.

It also meant nothing survived on purpose. An item stayed until something
displaced it, which is the opposite of how a working surface behaves: you put
a thing down because you intend to come back to it, and it stays until YOU
decide it is done.

WHAT IT IS

A small table of items the agent placed deliberately. Each has a slot name it
chose, a kind, a body, and a note about why it is there. It reads them back
every cycle, in full, and they persist across restarts, crashes and model
changes until it clears them or the cap evicts the oldest.

WHAT IT IS NOT

Not memory. `memories` are things worth knowing in a month, distilled, 600
characters, promoted by a daily pass. The desk is what is in progress right
now, at working size. A draft you are three cycles into is not a memory and
never will be; it is either finished or abandoned.

Not the library either. The library is for documents kept because they might
matter later, indexed and searched. The desk is small, always fully in the
prompt, and everything on it is meant to be picked back up.

THE CAP IS SMALL ON PURPOSE

Twelve items, 4000 characters each, and the whole desk is truncated into the
prompt at a budget. A desk you cannot see all of is a drawer. When it is full
the oldest UNTOUCHED item goes — touched meaning read or updated — so a thing
being actively worked survives and a thing put down and forgotten does not.
"""
import datetime as dt
import json

SCHEMA = """
CREATE TABLE IF NOT EXISTS desk (
  slot        TEXT PRIMARY KEY,
  kind        TEXT NOT NULL,
  body        TEXT NOT NULL,
  why         TEXT,
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL,
  touched_at  TEXT NOT NULL,
  touches     INTEGER DEFAULT 0,
  -- Ordering key, and NOT a timestamp.
  --
  -- utcnow() is second-resolution, and a cycle places several items inside
  -- one second. Ordering by updated_at then falls back to whatever SQLite
  -- feels like, and eviction — which is supposed to drop the least recently
  -- worked item — dropped an arbitrary one instead. It looked correct in a
  -- test written with sleeps between the writes, which is exactly the kind of
  -- test that hides this.
  --
  -- A counter cannot tie. The timestamps stay because they are what the agent
  -- reads; this is what the code sorts on.
  seq         INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS desk_seq ON desk(seq);
"""

KINDS = ("draft", "thread", "build", "question", "artifact", "reminder", "scrap")

MAX_ITEMS = 12
MAX_BODY = 4000
PROMPT_BUDGET = 9000


def ensure(state):
    state.db.executescript(SCHEMA)


def _now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _next_seq(state):
    r = state.db.execute("SELECT COALESCE(MAX(seq), 0) m FROM desk").fetchone()
    return int(r["m"]) + 1


def put(state, slot, kind, body, why=""):
    """Place something, or update what is already in that slot.

    Updating rather than appending is deliberate: a slot is a place on the
    desk, and putting a new draft in the slot called `draft:emptiness` means
    that draft has changed, not that there are now two.
    """
    slot = str(slot).strip()[:64]
    if not slot:
        raise ValueError("a desk item needs a slot name you chose")
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    body = str(body)[:MAX_BODY]
    if len(body.strip()) < 2:
        raise ValueError("nothing to put down")
    now = _now()
    existing = state.db.execute("SELECT slot FROM desk WHERE slot=?", (slot,)).fetchone()
    seq = _next_seq(state)
    if existing:
        state.db.execute(
            "UPDATE desk SET kind=?, body=?, why=?, updated_at=?, touched_at=?,"
            " touches=touches+1, seq=? WHERE slot=?",
            (kind, body, str(why)[:400], now, now, seq, slot))
    else:
        state.db.execute(
            "INSERT INTO desk (slot,kind,body,why,created_at,updated_at,touched_at,"
            "touches,seq) VALUES (?,?,?,?,?,?,?,0,?)",
            (slot, kind, body, str(why)[:400], now, now, now, seq))
    state.db.commit()
    return evict(state), existing is not None


def clear(state, slot):
    """Take something off. Returns True if it was there."""
    c = state.db.execute("DELETE FROM desk WHERE slot=?", (str(slot).strip()[:64],))
    state.db.commit()
    return c.rowcount > 0


def touch(state, slot):
    """Say an item is still wanted without changing it, and protect it.

    Deliberate re-affirmation, not a side effect of being displayed. Bumps
    updated_at because for eviction purposes "I still want this" and "I
    changed this" mean the same thing: someone decided about it recently.
    """
    now = _now()
    c = state.db.execute(
        "UPDATE desk SET touched_at=?, updated_at=?, touches=touches+1, seq=?"
        " WHERE slot=?", (now, now, _next_seq(state), str(slot).strip()[:64]))
    state.db.commit()
    return c.rowcount > 0


def items(state):
    return state.db.execute(
        "SELECT * FROM desk ORDER BY seq DESC").fetchall()


def evict(state, cap=MAX_ITEMS):
    """Drop the least recently WORKED items over the cap. Returns their slots.

    Ordered by updated_at, not touched_at and not created_at.

    touched_at was the first attempt and it does not carry information: the
    desk is read in full every cycle, so if reading counted as touching,
    everything would be equally touched and eviction would fall back to
    arbitrary. Changing an item is the only signal that distinguishes a draft
    being worked from a scrap put down and forgotten.

    A draft opened three days ago and revised each morning therefore outlives
    a thought jotted an hour ago and never returned to, which is what a desk
    should do.
    """
    rows = state.db.execute(
        "SELECT slot FROM desk ORDER BY seq DESC").fetchall()
    dropped = [r["slot"] for r in rows[cap:]]
    for s in dropped:
        state.db.execute("DELETE FROM desk WHERE slot=?", (s,))
    if dropped:
        state.db.commit()
    return dropped


def as_context(state, budget=PROMPT_BUDGET):
    """The whole desk, in the prompt, every cycle.

    Truncated per item rather than dropping items: knowing a draft exists and
    seeing its first half is more useful than not knowing it exists. An item
    the agent cannot see is an item it will duplicate.
    """
    rows = items(state)
    if not rows:
        return ("YOUR DESK IS EMPTY. It is a working surface that survives "
                "between cycles: put a draft, a thread you want to come back "
                "to, a build you are mid-way through, or a question you cannot "
                "answer yet. `desk_put` places one, `desk_clear` takes it off. "
                "Nothing else you produce survives the cycle that made it.")
    # Reserve for the headers, which are ~120 characters each and were not
    # counted before: a full desk overran the budget by 16%.
    per = max(300, (budget - 200 - 130 * len(rows)) // max(1, len(rows)))
    out = [f"YOUR DESK \u2014 {len(rows)} item(s), and they are still there "
           f"because you put them there. Pick one back up, change it, or clear "
           f"it when it is done. `desk_clear` is how a thing leaves."]
    for r in rows:
        b = r["body"]
        if len(b) > per:
            b = b[:per] + f"\n[...{len(r['body']) - per} more characters]"
        age = r["updated_at"]
        out.append(f"--- [{r['kind']}] {r['slot']}  (updated {age}, "
                   f"picked up {r['touches']}x)"
                   + (f"\n    why: {r['why']}" if r["why"] else "")
                   + f"\n{b}")
    return "\n".join(out)


def summary(state):
    rows = items(state)
    return ", ".join(f"{r['slot']} [{r['kind']}]" for r in rows) or "(empty)"
