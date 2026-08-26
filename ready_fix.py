#!/usr/bin/env python3
"""A ready project should be told to post, not left to redraft.

    sudo cp ready_fix.py /opt/riffle/
    sudo python3 /opt/riffle/ready_fix.py
    sudo systemctl restart riffle-dash
    sudo systemctl start riffle-cycle.service

    cd /opt/riffle && git add -A
    git commit -m "a ready project is told to post; cap redrafts"
    git push

WHAT CYCLES 71, 72 AND 73 WERE DOING

Three consecutive drafts on the same project, each saying the same thing in
different words — provenance, then signatures, then receipts. Notes went 10,
11, 12; sources stayed at 5. The bar had already been cleared.

It was doing what it was told. `missing_kind` returns the next deficit while
one exists and then returns **None**, so the "ONE THING TO DO NEXT" line
vanishes at the exact moment the project becomes postable. What is left is the
generic closing instruction: *"Add the NEXT increment... draft a paragraph."*
So it drafted a paragraph. Three times.

The rung was missing at the top of the ladder.

TWO CHANGES

1. When a project is ready, `missing_kind` now says so and says to post — with
   the note count and source count in the sentence, because a specific
   instruction is acted on and a general one is agreed with.

2. A cap on drafts. Beyond `max_drafts` (3 by default) another one is refused
   with a reason. `add_note` already refuses a verbatim repeat, but three
   rewordings of one idea are not verbatim and were passing straight through.
   A fourth rewording is not a fourth increment.

WHAT THIS DELIBERATELY DOES NOT DO

It does not post. The instruction goes into the prompt; the model still has to
propose it, the gate still has to pass it, numcheck still has to clear every
figure, and it still lands in your queue. This adds a sentence, not an action.

Backups written as .bak-ready.
"""
import os
import shutil
import sys

RIFFLE = "/opt/riffle"
PROJECT = f"{RIFFLE}/agent/project.py"
CFG = f"{RIFFLE}/config.yaml"

READY_BRANCH = '''    if s["notes"] < int(p.get("min_notes", 6)):
        return ("add " + str(int(p.get("min_notes", 6)) - s["notes"])
                + " more note(s) of any kind")

    # The rung that was missing. Returning None here left the prompt with only
    # its generic closing line — "add the next increment, draft a paragraph" —
    # so a finished project was redrafted instead of published. Three cycles
    # went that way before anyone noticed.
    return ("STOP ADDING NOTES AND WRITE THE POST. This project has "
            + str(s["notes"]) + " notes from " + str(s["sources"])
            + " sources, including a draft and an objection, over "
            + str(s["age_hours"]) + "h. It has cleared the bar. Propose a "
            "`post` that draws the notes together — every figure in it must "
            "appear in your `sources` block. Another draft is not progress; "
            "you already have "
            + str(s["by_kind"].get("draft", 0)) + ".")
'''

DRAFT_CAP = '''    # A fourth rewording of one idea is not a fourth increment. add_note
    # already refuses a verbatim repeat, but three drafts saying the same
    # thing in different words are not verbatim, and that is exactly what
    # cycles 71 to 73 produced.
    if kind == "draft":
        cap = int(((cfg_hint or {}).get("projects") or {}).get("max_drafts", 3))
        have = state.db.execute(
            "SELECT COUNT(*) c FROM project_notes WHERE project_id=?"
            " AND kind='draft'", (pid,)).fetchone()["c"]
        if have >= cap:
            raise ValueError(
                "this project already has " + str(have) + " drafts, which is "
                "the limit. Rewriting the same paragraph is not progress — "
                "either read a source you have not read, write the objection "
                "that would change your mind, or propose the post.")

'''


def main():
    s = open(PROJECT).read()

    # ---- 1. the missing rung ---------------------------------------------
    if "STOP ADDING NOTES AND WRITE THE POST" in s:
        print("  already present: the ready instruction")
    else:
        old = ('    if s["notes"] < int(p.get("min_notes", 6)):\n'
               '        return ("add " + str(int(p.get("min_notes", 6)) - s["notes"])\n'
               '                + " more note(s) of any kind")\n'
               '    return None\n')
        if old not in s:
            sys.exit("  FAILED: missing_kind does not end the way I expected.\n"
                     "  Paste the tail of it and I will re-anchor.")
        shutil.copy(PROJECT, f"{PROJECT}.bak-ready")
        s = s.replace(old, READY_BRANCH, 1)
        open(PROJECT, "w").write(s)
        print("  patched: a ready project is told to post")

    # ---- 2. the draft cap -------------------------------------------------
    s = open(PROJECT).read()
    if "already has " in s and "which is \n" not in s and "max_drafts" in s:
        print("  already present: the draft cap")
    else:
        old_sig = "def add_note(state, pid, cycle_id, kind, text, source=None):"
        if old_sig not in s:
            sys.exit("  FAILED: add_note's signature is not what I expected.")
        s = s.replace(
            old_sig,
            "def add_note(state, pid, cycle_id, kind, text, source=None,\n"
            "             cfg_hint=None):", 1)
        anchor = '    if kind not in KINDS:\n        raise ValueError('
        if anchor not in s:
            sys.exit("  FAILED: could not find add_note's kind check.")
        i = s.index(anchor)
        j = s.index("\n", s.index('raise ValueError(', i))
        j = s.index("\n", j + 1) + 1
        s = s[:j] + DRAFT_CAP + s[j:]
        if not os.path.exists(f"{PROJECT}.bak-ready"):
            shutil.copy(PROJECT, f"{PROJECT}.bak-ready")
        open(PROJECT, "w").write(s)
        print("  patched: draft cap in add_note")

    # the cycle passes cfg so the cap can read it
    cyc = f"{RIFFLE}/agent/cycle.py"
    c = open(cyc).read()
    old_call = ('            nid = project.add_note(state, proj["id"], cid, p["kind"], '
                'p["text"],\n                                   p.get("source"))')
    new_call = ('            nid = project.add_note(state, proj["id"], cid, p["kind"], '
                'p["text"],\n                                   p.get("source"), cfg_hint=cfg)')
    if "cfg_hint=cfg" in c:
        print("  already present: cycle passes cfg to add_note")
    elif old_call in c:
        shutil.copy(cyc, f"{cyc}.bak-ready")
        open(cyc, "w").write(c.replace(old_call, new_call, 1))
        print("  patched: cycle passes cfg to add_note")
    else:
        print("  NOTE: could not find add_note's call site in cycle.py.\n"
              "        The cap will use its default of 3 regardless.")

    # ---- 3. the knob ------------------------------------------------------
    cfg = open(CFG).read()
    if "max_drafts" in cfg:
        print("  already present: max_drafts")
    else:
        shutil.copy(CFG, f"{CFG}.bak-ready")
        open(CFG, "w").write(cfg.replace(
            "  min_drafts: 1",
            "  min_drafts: 1\n"
            "  # Beyond this, another draft is refused. Rewriting one paragraph\n"
            "  # is not the same as making progress.\n"
            "  max_drafts: 3", 1))
        print("  added projects.max_drafts: 3")

    import ast
    ast.parse(open(PROJECT).read())
    ast.parse(open(cyc).read())
    print("\n  modules parse.")

    sys.path.insert(0, RIFFLE)
    from agent.state import State
    from agent.cycle import load_config
    from agent import project
    try:
        conf = load_config(CFG)
        st = State("/var/lib/riffle/state.sqlite")
        pr = project.active(st)
        if pr:
            s_ = project.stats(st, pr["id"])
            ok, why = project.ready(st, conf)
            print(f"\n  '{pr['title'][:56]}'")
            print(f"    {s_['notes']} notes, {s_['sources']} sources, "
                  f"{s_['by_kind']}")
            print(f"    ready: {ok}")
            print(f"    next cycle will be told:\n      "
                  + str(project.missing_kind(st, conf, pr["id"]))[:300])
        else:
            print("\n  no project is open")
    except Exception as e:
        print(f"\n  (could not read the live project: {type(e).__name__}: {e})")
        print("  run as riffle if this says permission denied")

    print("""
  Next:
    sudo systemctl restart riffle-dash
    sudo systemctl start riffle-cycle.service

    cd /opt/riffle && git add -A
    git commit -m "a ready project is told to post; cap redrafts"
    git push
""")


if __name__ == "__main__":
    main()
