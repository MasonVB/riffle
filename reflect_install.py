#!/usr/bin/env python3
"""Remember the cycles, not just the conversations.

    sudo cp reflect_install.py /opt/riffle/
    sudo python3 /opt/riffle/reflect_install.py
    sudo systemctl restart riffle-dash

WHY THERE WERE ZERO MEMORIES AFTER 21 CYCLES

Extraction only ever ran after a chat turn, and there had been one completed
chat turn, and it was "hello". Nothing was broken. The mechanism was simply
pointed at the rarest thing riffle does.

Almost everything it experiences happens in cycles: reading the front page,
proposing something, being refused by the gate, having a figure blocked,
deciding not to act and writing down why. None of that reached memory.

WHAT THIS ADDS

Each cycle reflects on the PREVIOUS one, using the small triage model, on a
separate server from the composer so it costs no lock and a few seconds.

The material is what actually happened: which drive was drawn, what was on
the board, what it proposed and why, and what became of it. Refusals are the
most valuable part — "I was blocked for citing a figure I invented" is a
thing worth knowing about yourself next time, and it is exactly the sort of
thing that was being thrown away.

REFLECTING ON THE PREVIOUS CYCLE RATHER THAN THIS ONE

One call site instead of eleven — a cycle exits from a dozen places and
threading a reflection through all of them would guarantee some paths lose
it. It also gives an hour's distance, which is the same reason the memory
consolidation pass waits a day: judgement about what mattered improves once
you know what happened next.

ON VOLUME

Two durable notes per cycle at 24 cycles a day is a lot, and most of it is
noise. That is contained rather than avoided: everything lands in short term
and expires in seven days, the model is shown what it already remembers and
told not to restate it, and the daily pass promotes at most three. If the
store still bloats, lower `reflect_max_per_cycle` to 1 or set it to 0.

Backups written as .bak-reflect.
"""
import os
import shutil
import sys

RIFFLE = "/opt/riffle"
MEM = f"{RIFFLE}/agent/memory.py"
CYCLE = f"{RIFFLE}/agent/cycle.py"
CFG = f"{RIFFLE}/config.yaml"

CONFIG_ADD = """  # Each cycle writes notes about the previous one — what it read, what it
  # proposed, what was refused. Set to 0 to turn cycle reflection off and keep
  # memory limited to conversations.
  reflect_max_per_cycle: 2
"""

REFLECT = '''

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
        material.append("WHAT WAS ON THE BOARD:\\n" + front[:2500])
    for a in acts:
        line = f"YOU PROPOSED: {a['kind']} — {a['rationale']}"
        if a["status"] != "executed":
            line += f"\\n  and it was {a['status']}"
        material.append(line)
    if jrn:
        material.append("LOG:\\n" + "\\n".join(
            f"  [{j['level']}] {j['text'][:220]}" for j in jrn))

    known = recent(state, 25)
    material.append("ALREADY REMEMBERED — do not restate any of these:\\n"
                    + ("\\n".join(f"  - {r['text']}" for r in known)
                       or "  (nothing yet)"))

    from agent import cortex
    try:
        out = cortex.complete(cfg["llm"]["triage"], REFLECT_PROMPT,
                              "\\n\\n".join(material)[:7000], timeout=900)
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
'''


def patch(path, old, new, label, marker):
    s = open(path).read()
    if marker in s:
        print(f"  already present: {label}")
        return False
    if old not in s:
        sys.exit(f"  FAILED: anchor not found in {os.path.basename(path)} "
                 f"({label}). Nothing changed.")
    if not os.path.exists(f"{path}.bak-reflect"):
        shutil.copy(path, f"{path}.bak-reflect")
    open(path, "w").write(s.replace(old, new, 1))
    print(f"  patched: {label}")
    return True


def main():
    cfg = open(CFG).read()
    if "reflect_max_per_cycle" in cfg:
        print("  already present: reflect_max_per_cycle")
    else:
        anchor = "  incidental_max_per_exchange: 2"
        if anchor not in cfg:
            sys.exit("  FAILED: memory block not found in config.yaml.")
        shutil.copy(CFG, f"{CFG}.bak-reflect")
        open(CFG, "w").write(cfg.replace(anchor, anchor + "\n"
                                         + CONFIG_ADD.rstrip(), 1))
        print("  added reflect_max_per_cycle to config.yaml")

    s = open(MEM).read()
    if "def reflect(state, cfg" in s:
        print("  already present: reflect()")
    else:
        if not os.path.exists(f"{MEM}.bak-reflect"):
            shutil.copy(MEM, f"{MEM}.bak-reflect")
        open(MEM, "w").write(s.rstrip() + "\n" + REFLECT)
        print("  patched: reflect() added to memory.py")

    # remember what was on the board, so the reflection has something to read
    patch(CYCLE,
          '''    front = reader.front(limit=15).get("posts", [])''',
          '''    front = reader.front(limit=15).get("posts", [])
    # Keep a digest of what was actually on the board this cycle. Next cycle's
    # reflection needs to know what it read, and the front page will have moved
    # by then.
    state.note("last_front_digest", "\\n".join(
        f"  #{p.get('id')} \\"{str(p.get('title'))[:90]}\\" by {p.get('author')}"
        f" ({p.get('votes', 0)} votes, {p.get('comments', 0)} comments)"
        for p in front[:12]))''',
          "cycle records what it read", marker="last_front_digest")

    patch(CYCLE,
          '''    consolidate.sweep(state, cfg, log)''',
          '''    # Reflect on the PREVIOUS cycle: one call site rather than one per exit
    # path, and an hour's distance on what mattered. Uses the small model on
    # its own server, so it costs no composer lock.
    try:
        memory.reflect(state, cfg, log)
    except Exception as e:
        log(f"reflection error: {e}", level="warn")
    memory.prune(state, keep=1200)

    consolidate.sweep(state, cfg, log)''',
          "cycle reflects on the previous one", marker="memory.reflect(state, cfg, log)")

    import ast
    for f in (MEM, CYCLE):
        ast.parse(open(f).read())
    print("\n  modules parse.")
    print("""
  Next:
    sudo systemctl restart riffle-dash
    sudo systemctl start riffle-cycle.service   # then again, to reflect on it

  The first run has no completed previous cycle to reflect on, so run it twice.
  Then:
    sudo sqlite3 -header -column /var/lib/riffle/state.sqlite \\
      "SELECT id,kind,tier,source,substr(text,1,64) FROM memories ORDER BY id DESC LIMIT 12;"
""")


if __name__ == "__main__":
    main()
