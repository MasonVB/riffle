#!/usr/bin/env python3
"""Repair cycle.py, and stop it claiming actions it did not take.

    sudo cp deepen_repair.py /opt/riffle/
    sudo python3 /opt/riffle/deepen_repair.py
    sudo systemctl restart riffle-dash

URGENT: cycle.py DOES NOT PARSE

My sed left `if drive == "deepen" and not project.active(state):` with its
only statement commented out, which is an IndentationError. Every cycle since
has died at import. That is my fault twice over — the line number I gave was
one off, and a sed that comments out a block body is the wrong tool for it.

This removes the whole block properly, and works whether or not the sed ran.

WHAT THE BLOCK WAS DOING

It set `_selects["deepen"] = ["open_project"]` in memory on every cycle where
`deepen` was drawn with no project open. Not in the database — which is why
the audit trigger never fired, why clearing the column twice changed nothing,
and why we spent a day looking for a writer that did not exist.

It is now redundant. loop_fix added a gate that refuses everything except
open_project and noop when no project is open, for every drive, with a message
that says what to do instead. The old block only produced a worse error.

SECOND FIX: CLAIMING ACTIONS

Three times riffle has written "I will open this project now" or "I have now
corrected this by opening the project" in chat. The chat path has no route to
Writer and cannot open a project. Each time you reasonably believed something
had happened that had not.

The prompt already said it cannot act. It did not say the thing that matters:
never write a sentence describing an action as done or underway. Saying "I
cannot" and then narrating an action anyway is not a contradiction the model
notices, so the rule has to be about the SENTENCE, not the capability.

Backups written as .bak-repair.
"""
import os
import shutil
import sys

RIFFLE = "/opt/riffle"
CYCLE = f"{RIFFLE}/agent/cycle.py"
CHAT = f"{RIFFLE}/agent/chat.py"

REPLACEMENT = '''    # A `deepen` draw with no open project used to be narrowed here to
    # open_project alone, by writing _selects in memory. That is now handled
    # by the gate below, which refuses every action but open_project and noop
    # when nothing is open, for every drive, and says why. The old version set
    # a restriction that existed only in memory — so the drives table always
    # looked clean, the audit trigger never fired, and clearing the column
    # changed nothing. A rule you cannot see is a rule you cannot debug.
'''

ACTION_CLAIM = '''You cannot post, comment, vote, open a project or otherwise act from this
conversation. Nothing you say here reaches the square or changes any record.

So never write a sentence that describes an action as done, being done, or
about to be done by you. Not "I will open this project now", not "I have
opened it", not "Action: open_project". You have written all three, and each
time he believed something had happened that had not.

Saying you cannot act and then narrating an action is not a contradiction you
will notice, so the rule is about the sentence rather than the capability:
describe what you would PROPOSE and stop there.

  wrong: "I will open a project on #1916."
  right: "I would propose open_project with this title and question. Send it
          with the send-to-cycle button and the next cycle can act on it."

If he asks you to do something on the square, say what you would propose and
tell him it will appear in the queue on the next cycle, or that he can force a
cycle with `systemctl start riffle-cycle`, or press the run cycle button at
the top of this page.'''


def main():
    s = open(CYCLE).read()

    broken = '''    if drive == "deepen" and not project.active(state):
    # superseded by the no-project gate in loop_fix; left as a comment
    #         cfg.setdefault("_selects", {})["deepen"] = ["open_project"]
'''
    intact = '''    if drive == "deepen" and not project.active(state):
        cfg.setdefault("_selects", {})["deepen"] = ["open_project"]
'''
    header = '''    # With nothing open, deepen has exactly one sensible move. Narrowing the
    # legal set turns "I have nothing to work on" from a conclusion the model
    # can settle for into an instruction it has to follow.
'''

    if "A `deepen` draw with no open project used to be narrowed here" in s:
        print("  already present: deepen block removed")
    else:
        target = broken if broken in s else (intact if intact in s else None)
        if target is None:
            sys.exit("  FAILED: could not find the deepen block in either form.\n"
                     "  Paste `sed -n '282,292p' /opt/riffle/agent/cycle.py`.")
        shutil.copy(CYCLE, f"{CYCLE}.bak-repair")
        out = s.replace(header + target, REPLACEMENT, 1)
        if out == s:                      # header missing or reflowed
            out = s.replace(target, REPLACEMENT, 1)
        open(CYCLE, "w").write(out)
        print(f"  removed the deepen block ({'broken' if target is broken else 'intact'} form)")

    import ast
    try:
        ast.parse(open(CYCLE).read())
        print("  cycle.py parses")
    except (SyntaxError, IndentationError) as e:
        shutil.copy(f"{CYCLE}.bak-repair", CYCLE)
        sys.exit(f"  FAILED: still broken at line {e.lineno}: {e.msg}\n"
                 f"  restored the backup; nothing changed.")

    # ---- the chat prompt ---------------------------------------------------
    c = open(CHAT).read()
    old = '''You cannot post, comment, vote or otherwise act from this conversation. If he
asks you to do something on the square, say what you would propose and tell
him it will appear in the queue on the next cycle, or that he can force a
cycle with `systemctl start riffle-cycle`, or press the run cycle button
at the top of this page.'''
    if "never write a sentence that describes an action as done" in c:
        print("  already present: action-claim rule")
    elif old not in c:
        print("  NOTE: the chat prompt does not match what I expected; skipping\n"
              "        that half. cycle.py is repaired either way.")
    else:
        shutil.copy(CHAT, f"{CHAT}.bak-repair")
        open(CHAT, "w").write(c.replace(old, ACTION_CLAIM, 1))
        ast.parse(open(CHAT).read())
        print("  patched: it may say what it would propose, never what it did")

    print("""
  Next:
    sudo systemctl restart riffle-dash
    sudo systemctl start riffle-cycle.service
    sudo journalctl -u riffle-cycle -n 20 --no-pager

  Cycles have been dying at import since the sed. The first one after this
  should get as far as picking a drive.""")


if __name__ == "__main__":
    main()
