#!/usr/bin/env python3
"""Break the no-project loop.

    sudo cp loop_fix.py /opt/riffle/
    sudo python3 /opt/riffle/loop_fix.py
    sudo systemctl restart riffle-dash

WHAT I GOT WRONG

My last fix made a read with no open project print an explanation and end the
cycle. An explanation is not a constraint. The model read #2115, got the same
paragraph, and did it again — eight cycles, identical text, no progress. I
replaced a loop that wasted a cycle with a loop that wasted a cycle and
lectured about it.

Telling a model what it should have done, in a message it will not remember,
does not change what it does next.

THE FIX IS DETERMINISTIC, NOT PERSUASIVE

When no project is open:

  the prompt says so in its FIRST line, before anything else it reads, and
  states that open_project is the only action that will succeed;

  the gate refuses everything except open_project and noop, with a message
  naming the thread it just read as the obvious subject.

So the loop cannot run. Either it opens a project or it declines the cycle,
and both of those are progress in a way that reading the same thread nine
times is not.

A NOTE ON THE OTHER LOOP

Cycles 35, 37, 40 and 47 refused `deepen` because `selects` on that drive was
["open_project"], which I cleared twice and which came back. I still do not
know what sets it. The audit trigger is now installed, and the settings page
shows it in red — so the next occurrence should be attributable instead of
mysterious. This patch does not paper over it.

Backups written as .bak-loop.
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
    if s.count(old) != 1:
        sys.exit(f"  FAILED: anchor matched {s.count(old)} times ({label}).")
    if not os.path.exists(f"{path}.bak-loop"):
        shutil.copy(path, f"{path}.bak-loop")
    open(path, "w").write(s.replace(old, new, 1))
    print(f"  patched: {label}")
    return True


def main():
    # ---- 1. the prompt leads with it --------------------------------------
    patch(CYCLE,
          '    parts.append(project.as_context(state, cfg, budget=int(budget * 0.40)))',
          '''    if not project.active(state):
        # First line of the prompt, before the board, the memories or the
        # goals. A constraint stated after three thousand characters of other
        # material is a suggestion.
        parts.insert(0,
            "NO PROJECT IS OPEN. This cycle, open_project is the only action "
            "that will be accepted — everything else is refused before it "
            "reaches the square. Pick the question you most want to settle "
            "from what you have read and open a project on it. A rough "
            "question you can sharpen later beats another cycle spent "
            "re-reading something you cannot keep.")
    parts.append(project.as_context(state, cfg, budget=int(budget * 0.40)))''',
          "prompt leads with the constraint", marker="NO PROJECT IS OPEN. This cycle")

    # ---- 2. the gate enforces it ------------------------------------------
    patch(CYCLE,
          '''    if kind == "read_more":''',
          '''    # A constraint, not advice. The previous version explained itself and
    # was ignored eight cycles running, because an explanation the model will
    # not remember cannot change what it does next.
    if kind not in ("open_project", "noop") and not project.active(state):
        state.propose(cid, kind, drive, payload, rationale, "blocked")
        log(f"{kind} refused: no project is open", level="info", drive=drive)
        _last = state.db.execute(
            "SELECT text FROM memories WHERE kind='board' ORDER BY id DESC"
            " LIMIT 1").fetchone()
        hint = (" You last read " + _last["text"][:70] + "…"
                if _last else "")
        state.say("report", "Cycle " + str(cid) + " : refused " + kind
                  + " because no project is open. Open one and everything you "
                  "read afterwards is kept." + hint, {"drive": drive})
        state.end_cycle(cid, "no-project")
        return 0

    if kind == "read_more":''',
          "gate refuses everything but open_project when none is open",
          marker="A constraint, not advice")

    # ---- 3. drop the paragraph that was being repeated ---------------------
    s = open(CYCLE).read()
    old = '''    else:
        # Reading with nowhere to put it is a wasted cycle, and it happened
        # twice in a row on #2115. Refuse, and say exactly what to do instead.'''
    if old in s:
        new = '''    else:
        # Unreachable now: the gate above refuses read_thread when no project
        # is open. Kept as a belt-and-braces path rather than deleted.'''
        if not os.path.exists(f"{CYCLE}.bak-loop"):
            shutil.copy(CYCLE, f"{CYCLE}.bak-loop")
        open(CYCLE, "w").write(s.replace(old, new, 1))
        print("  patched: the repeated paragraph is now unreachable")
    else:
        print("  already present: no-project read path")

    import ast
    ast.parse(open(CYCLE).read())
    print("\n  cycle.py parses.")
    print("""
  Next:
    sudo systemctl restart riffle-dash
    sudo systemctl start riffle-cycle.service

  The next cycle should propose open_project or noop. Nothing else can pass.""")


if __name__ == "__main__":
    main()
