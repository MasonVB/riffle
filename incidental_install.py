#!/usr/bin/env python3
"""Remember some things for no reason.

    sudo cp incidental_install.py /opt/riffle/
    sudo python3 /opt/riffle/incidental_install.py
    sudo systemctl restart riffle-dash

WHAT THIS ADDS

On top of everything the agent judges worth keeping, 5-10% more is kept at
random — at both shelves.

  SHORT TERM   extraction now returns two lists. DURABLE is what it judges
               worth keeping, as before. PASSING is everything else that came
               up — details, asides, specifics that would normally be dropped.
               All of DURABLE is written; a random sample of PASSING is too.

  LONG TERM    after the daily pass promotes its three, one of the candidates
               it passed over may be promoted anyway, chosen at random.

WHAT "5 TO 10 PERCENT MORE" MEANS HERE

A rate p is drawn uniformly from [0.05, 0.10] each time, and the expected
number of extra items is p times the number retained. Concretely: floor(p*n)
items, plus one more with probability equal to the remainder. With four
durable items and p=0.08 that is a 32% chance of one extra — which averages
out to 8% more over many exchanges, rather than 8% of nothing every time.

WHY DELIBERATELY KEEP JUNK

Two reasons, and the first is the honest one.

The agent's judgement about what will matter is a guess made before knowing
what it will be asked. A store containing only what it predicted would be
useful can only ever confirm its own model of what is useful; nothing arrives
to contradict it. The random sample is the only material in there that its
judgement did not select, which makes it the only material that can surprise
it.

The second is that this is how the thing being imitated works. People
remember the important parts of a conversation and also, unaccountably, what
someone was wearing. The odd detail is sometimes the one that connects two
things later.

It also fills the store with noise. That is contained rather than solved: the
noise lands in short term where it expires in a week, and the daily pass has a
hard cap on what reaches long term. Incidental items are marked as such and
show on /goals, so if they turn out to be worthless you can see it and set
`incidental_rate_max: 0` — the mechanism admits it might be a bad idea.

Backups written as .bak-incidental.
"""
import os
import shutil
import sys

RIFFLE = "/opt/riffle"
MEM = f"{RIFFLE}/agent/memory.py"
CON = f"{RIFFLE}/agent/consolidate.py"
CFG = f"{RIFFLE}/config.yaml"

CONFIG_ADD = """  # On top of what it judges worth keeping, this fraction more is kept at
  # random — the only material in the store its own judgement did not select.
  # Set incidental_rate_max to 0 to turn it off.
  incidental_rate_min: 0.05
  incidental_rate_max: 0.10
  incidental_max_per_exchange: 2
"""

NEW_PROMPT = '''EXTRACT_PROMPT = """From the exchange below, write TWO lists of short notes.

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
'''

NEW_EXTRACT = '''def extract(state, cfg, exchange, source):
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
'''


def patch(path, old, new, label, marker):
    s = open(path).read()
    if marker in s:
        print(f"  already present: {label}")
        return False
    if old not in s:
        sys.exit(f"  FAILED: anchor not found in {os.path.basename(path)} "
                 f"({label}). Nothing changed.")
    if not os.path.exists(f"{path}.bak-incidental"):
        shutil.copy(path, f"{path}.bak-incidental")
    open(path, "w").write(s.replace(old, new, 1))
    print(f"  patched: {label}")
    return True


def main():
    # ---- config -----------------------------------------------------------
    cfg = open(CFG).read()
    if "incidental_rate_min" in cfg:
        print("  already present: incidental rates")
    else:
        anchor = "  recall_long_slots: 3"
        if anchor not in cfg:
            sys.exit("  FAILED: could not find the memory block in config.yaml.")
        shutil.copy(CFG, f"{CFG}.bak-incidental")
        open(CFG, "w").write(cfg.replace(
            anchor, anchor + "\n" + CONFIG_ADD.rstrip(), 1))
        print("  added incidental rates to config.yaml")

    # ---- extraction prompt + helpers --------------------------------------
    s = open(MEM).read()
    if "def extra_count(" in s:
        print("  already present: two-list extraction")
    else:
        a = s.index('EXTRACT_PROMPT = """')
        b = s.index("def extract(state, cfg, exchange, source):")
        if not os.path.exists(f"{MEM}.bak-incidental"):
            shutil.copy(MEM, f"{MEM}.bak-incidental")
        s = s[:a] + NEW_PROMPT + "\n\n" + s[b:]
        # replace extract() wholesale
        a2 = s.index("def extract(state, cfg, exchange, source):")
        open(MEM, "w").write(s[:a2] + NEW_EXTRACT)
        print("  patched: two-list extraction with a random sample of PASSING")

    # ---- incidental promotion at consolidation ----------------------------
    patch(CON,
          '''    state.db.commit()
    state.note("last_consolidation", utcnow())''',
          '''    # One of the candidates it passed over may go up anyway. This is the only
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
    state.note("last_consolidation", utcnow())''',
          "random promotion at consolidation", marker="passed over may go up anyway")

    patch(CON,
          '''    if dropped:
        parts.append(f"dropped {len(dropped)} as wrong")''',
          '''    if dropped:
        parts.append(f"dropped {len(dropped)} as wrong")
    if lucky:
        parts.append(f"kept {len(lucky)} at random")''',
          "summary counts the random ones", marker="kept {len(lucky)} at random")

    patch(CON,
          '''        for mid, why in dropped:
            lines.append(f"  \\u2717 dropped [{mid}]: {why[:120]}")''',
          '''        for mid, text in lucky:
            lines.append(f"  \\u2191 long (at random, not chosen): {text[:150]}")
        for mid, why in dropped:
            lines.append(f"  \\u2717 dropped [{mid}]: {why[:120]}")''',
          "report shows the random promotions", marker="at random, not chosen")

    import ast
    for f in (MEM, CON):
        ast.parse(open(f).read())
    print("\n  modules parse.")
    print("""
  Next:
    sudo systemctl restart riffle-dash

  Incidental memories show as kind 'incidental' at the bottom of /goals.
  To see the rate in practice after a few days:

    sudo sqlite3 -header -column /var/lib/riffle/state.sqlite \\
      "SELECT kind, tier, COUNT(*) FROM memories GROUP BY kind, tier;"
""")


if __name__ == "__main__":
    main()
