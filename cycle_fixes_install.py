#!/usr/bin/env python3
"""Four fixes for what 21 cycles exposed.

    sudo cp cycle_fixes_install.py /opt/riffle/
    sudo python3 /opt/riffle/cycle_fixes_install.py
    sudo systemctl restart riffle-dash

THE RECORD THIS IS RESPONDING TO

  21 cycles: 7 queued, 6 numcheck-blocked, 3 composer-failed, 2 gate-blocked,
  3 noop. Zero projects opened. Zero memories stored.

1. DEEPEN WITH NO PROJECT

The `deepen` drive exists to add increments to an open project. It was
available whether or not one existed, because of this line I wrote:

    available = {n for n in live_weights
                 if n in known or n not in ("answer", "contribute", "earn")}

meant to let goals YOU add pass through without a precondition — but `deepen`
falls through it too. So cycle 20 drew "work on the project" with no project,
and wrote a comment instead.

Now: when `deepen` is drawn and nothing is open, the only legal actions are
open_project and noop. "I have nothing to work on" stops being a conclusion
and becomes an instruction. That also explains 21 cycles with no project —
nothing ever made opening one the obvious move.

2. NUMCHECK BLOCKED SIX CYCLES, MOSTLY WRONGLY

The blocked figures were things like `1611` and `17,000` — post ids and counts
the agent READ ON THE BOARD. They were untraceable only because the sources
block is assembled by the model, and it does not think to copy back numbers it
just read.

But the cycle knows exactly what it showed the model. That material is now
passed to numcheck as a second source, so anything the agent read is
traceable by construction and only INVENTED figures fail. That is what the
check was always for; requiring the model to re-declare what it was handed
was my mistake.

3. THE REPORT OVER-COUNTED

"10 figures I could not trace: L1 three; L1 1611; L1 17,000; L3 three" — but
spelled numerals do not block in agent mode. The message listed every finding
while the decision used a filtered set, so it named blockers that were not
blockers. The two now use the same list.

4. THE noop CEILING

Two cycles died writing a 668-character `why` against a 500 limit. The limit
was arbitrary; the reasoning was not too long, the box was too small.

Backups written as .bak-cyclefix.
"""
import os
import shutil
import sys

RIFFLE = "/opt/riffle"
CYCLE = f"{RIFFLE}/agent/cycle.py"
DRIVES = f"{RIFFLE}/agent/drives.py"


def patch(path, old, new, label, marker):
    s = open(path).read()
    if marker in s:
        print(f"  already present: {label}")
        return False
    if old not in s:
        sys.exit(f"  FAILED: anchor not found in {os.path.basename(path)} "
                 f"({label}). Nothing changed.")
    if not os.path.exists(f"{path}.bak-cyclefix"):
        shutil.copy(path, f"{path}.bak-cyclefix")
    open(path, "w").write(s.replace(old, new, 1))
    print(f"  patched: {label}")
    return True


def main():
    # ---- 1. deepen must open a project if none exists ----------------------
    patch(CYCLE,
          '''    cooling, _until, hours_left = project.in_cooldown(state)
    if project.active(state):
        available.add("deepen")''',
          '''    cooling, _until, hours_left = project.in_cooldown(state)
    # `deepen` is always available, but what it may DO depends on whether
    # there is anything to deepen. Without this it drew "work on the project"
    # with no project and wrote a comment instead.
    available.add("deepen")''',
          "deepen is always available", marker="what it may DO depends on")

    patch(CYCLE,
          '''    cid = state.begin_cycle(drive)''',
          '''    # With nothing open, deepen has exactly one sensible move. Narrowing the
    # legal set turns "I have nothing to work on" from a conclusion the model
    # can settle for into an instruction it has to follow.
    if drive == "deepen" and not project.active(state):
        cfg.setdefault("_selects", {})["deepen"] = ["open_project"]

    cid = state.begin_cycle(drive)''',
          "deepen with no project may only open one",
          marker='cfg.setdefault("_selects", {})["deepen"]')

    # ---- 2. what the agent read counts as a source -------------------------
    patch(CYCLE,
          '''def run_numcheck(body, sources):''',
          '''def run_numcheck(body, sources, context=None):''',
          "run_numcheck takes the context it was given", marker="sources, context=None")

    patch(CYCLE,
          '''        json.dump(sources or {}, open(os.path.join(src, "sources.json"), "w"))''',
          '''        json.dump(sources or {}, open(os.path.join(src, "sources.json"), "w"))
        # Everything the agent was shown this cycle is, by definition, traceable.
        # Requiring the model to copy figures back out of its own prompt was
        # asking it to re-declare what it had just been handed, and it blocked
        # six cycles over post ids read straight off the front page.
        if context:
            open(os.path.join(src, "context.txt"), "w").write(context)''',
          "board context becomes a numcheck source", marker="context.txt")

    patch(CYCLE,
          '''        passed, report = run_numcheck(body, proposal.get("sources"))''',
          '''        passed, report = run_numcheck(body, proposal.get("sources"), material)''',
          "cycle passes its material to numcheck", marker="proposal.get(\"sources\"), material")

    # ---- 3. report only what actually blocked ------------------------------
    patch(CYCLE,
          '''            bad = [f for f in report.get("findings", [])
                   if f.get("status") in ("UNBACKED", "MALFORMED")]''',
          '''            # Match the message to the decision. Spelled numerals do not block
            # in agent mode, but the report listed them anyway, so it named
            # blockers that were not blockers.
            bad = [f for f in report.get("findings", [])
                   if f.get("status") in ("UNBACKED", "MALFORMED")
                   and not f.get("low")]''',
          "report lists only real blockers", marker="Match the message to the decision")

    # ---- 4. room to explain a noop ----------------------------------------
    patch(DRIVES,
          '''    "noop": ([], ["why"], lambda p: {"why": _s(p.get("why", "nothing worth doing"), 0, 500, "why")}),''',
          '''    # 1200 rather than 500: two cycles were spent producing reasoning that was
    # then thrown away for being 168 characters over an arbitrary ceiling. A
    # declining-to-act explanation is the one output worth reading in full.
    "noop": ([], ["why"], lambda p: {"why": _s(p.get("why", "nothing worth doing"), 0, 1200, "why")}),''',
          "noop why limit raised to 1200", marker="1200 rather than 500")

    import ast
    for f in (CYCLE, DRIVES):
        ast.parse(open(f).read())
    print("\n  modules parse.")
    print("""
  Next:
    sudo systemctl restart riffle-dash
    sudo systemctl start riffle-cycle.service

  Expect an open_project within a cycle or two — with no project open,
  roughly a fifth of cycles now draw deepen and deepen can only do one thing.

  Also worth clearing the backlog: max_queued is 5 and you have 7 queued, so
  cycles are witnessing without waking the composer at all.
    sudo sqlite3 -header -column /var/lib/riffle/state.sqlite \\
      "SELECT id,kind,drive,substr(rationale,1,60) FROM actions WHERE status='queued';"
""")


if __name__ == "__main__":
    main()
