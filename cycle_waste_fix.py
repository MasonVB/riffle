#!/usr/bin/env python3
"""Three ways a cycle currently dies that it should not.

    sudo cp cycle_waste_fix.py /opt/riffle/
    sudo python3 /opt/riffle/cycle_waste_fix.py
    sudo systemctl restart riffle-dash

Cycles 63, 65 and 66 all did real work and threw it away.

  63  composer-failed: no JSON object carrying an 'action' key
      Eleven minutes of generation, discarded. Constrained decoding makes a
      malformed object impossible, so the only way to get an unparseable one
      is to be cut off before the closing brace — max_tokens at 1800 while
      the context is now 20480. The grammar guarantees the prefix is valid;
      it cannot conjure the rest.

  66  text must be 20-1200 chars, got 1226
      A project note refused for twenty-six characters over. That is a whole
      wake spent, and the fix costs one line: over-long prose gets trimmed,
      not rejected. LIMITS THAT PROTECT SOMETHING GET ENFORCED; limits that
      exist because a column has a width get satisfied.

      post_id, weights, hashes and action names are still refused outright —
      a wrong id is wrong, and truncating it would be worse than refusing.

  63 again  main() returns 1, so systemd logs a red FAILURE for what is
      really "the model wrote something odd". A cycle that ends without
      acting is a normal outcome and should not look like a crash — you
      cannot spot the real failures in a log where everything is red.

WHAT THIS DOES NOT DO

It does not retry the composer. Eleven minutes is too expensive to spend
twice on a hunch, and if truncation is the cause the retry produces the same
truncation. Raising the ceiling addresses the cause; a retry would only hide
it.

Backups written as .bak-waste.
"""
import os
import shutil
import sys

RIFFLE = "/opt/riffle"
DRIVES = f"{RIFFLE}/agent/drives.py"
CYCLE = f"{RIFFLE}/agent/cycle.py"
CFG = f"{RIFFLE}/config.yaml"

TRIM = '''

def _trim(v, lo, hi, name):
    """Like _s, but trims prose that runs long instead of refusing it.

    Cycle 66 lost a whole wake because a project note was 1,226 characters
    against a 1,200 limit. That limit exists to keep the prompt bounded, not
    to protect anything — so it should be satisfied rather than enforced. A
    model that writes twenty-six characters too many has not made a mistake
    worth spending a cycle on.

    Only prose gets this. Ids, weights and hashes still go through _s: a
    truncated post_id is a wrong post_id, which is worse than a refusal.
    """
    if not isinstance(v, str):
        raise Rejected(f"{name} must be a string")
    v = v.strip()
    if len(v) < lo:
        raise Rejected(f"{name} must be at least {lo} chars, got {len(v)}")
    if len(v) > hi:
        ell = " […]"
        room = hi - len(ell)          # the marker counts toward the limit
        cut = v[:room]
        sp = cut.rfind(" ")
        # Only honour a word boundary if it is NEAR THE END. Falling back to
        # the last space anywhere turned a 1,233-character note into 86, since
        # a long unbroken run leaves the nearest space back at the start.
        if sp >= int(room * 0.9):
            cut = cut[:sp]
        cut = cut.rstrip()
        return cut + ell if len(cut) >= lo else v[:room].rstrip() + ell
    return v
'''


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
    if not os.path.exists(f"{path}.bak-waste"):
        shutil.copy(path, f"{path}.bak-waste")
    open(path, "w").write(s.replace(old, new, 1))
    print(f"  patched: {label}")
    return True


def main():
    # ---- 1. prose is trimmed, not refused ---------------------------------
    s = open(DRIVES).read()
    if "def _trim(" in s:
        print("  already present: _trim")
    else:
        anchor = "def _i(v, name):"
        if anchor not in s:
            sys.exit("  FAILED: could not find _i() in drives.py.")
        shutil.copy(DRIVES, f"{DRIVES}.bak-waste")
        open(DRIVES, "w").write(s.replace(anchor, TRIM.strip() + "\n\n\n" + anchor, 1))
        print("  added _trim() to drives.py")

    # the prose fields, one at a time so a miss is visible
    prose = [
        ('"body": _s(p["body"], 1, 8000, "body"),',
         '"body": _trim(p["body"], 1, 8000, "body"),', "post body"),
        ('"body": _s(p["body"], 1, 8000, "body"),\n'
         '                           "parent_id"',
         '"body": _trim(p["body"], 1, 8000, "body"),\n'
         '                           "parent_id"', "comment body"),
        ('"text": _s(p["text"], 20, 1200, "text"),',
         '"text": _trim(p["text"], 20, 1200, "text"),', "project note text"),
        ('"reason": _s(p["reason"], 20, 600, "reason")}),',
         '"reason": _trim(p["reason"], 20, 600, "reason")}),', "a reason field"),
        ('"note": _s(p["note"], 1, 2000, "note")}),',
         '"note": _trim(p["note"], 1, 2000, "note")}),', "listing note"),
        ('"question": _s(p["question"], 20, 600, "question")}),',
         '"question": _trim(p["question"], 20, 600, "question")}),',
         "project question"),
    ]
    s = open(DRIVES).read()
    done = 0
    for old, new, what in prose:
        if new in s:
            continue
        if old in s:
            s = s.replace(old, new, 1)
            done += 1
        else:
            print(f"    note: could not find the {what} field; left as-is")
    open(DRIVES, "w").write(s)
    print(f"  {done} prose field(s) now trim instead of refusing")

    # rationale is prose too, and its floor is what usually bites
    s = open(DRIVES).read()
    old_r = ('    if not isinstance(rationale, str) or len(rationale.strip()) < 10:\n'
             '        raise Rejected("a proposal must carry a rationale of at '
             'least 10 characters")')
    if "rationale[:2000]" in s and "_trim(rationale" not in s and old_r in s:
        s = s.replace(old_r,
                      '    if not isinstance(rationale, str) or len(rationale.strip()) < 10:\n'
                      '        raise Rejected("a proposal must carry a rationale of at '
                      'least 10 characters")\n'
                      '    # The 2000 cap below already truncates silently; keeping it.', 1)
        open(DRIVES, "w").write(s)
        print("  rationale already truncated rather than refused")

    # ---- 2. room to finish the object -------------------------------------
    c = open(CFG).read()
    if "max_tokens: 1800" in c:
        shutil.copy(CFG, f"{CFG}.bak-waste")
        open(CFG, "w").write(c.replace("max_tokens: 1800", "max_tokens: 3000", 1))
        print("  composer max_tokens 1800 -> 3000")
        print("    (the context is 20480 now; 1800 was set when it was 12288,")
        print("     and a grammar-constrained object cut off mid-write is")
        print("     still unparseable)")
    elif "max_tokens: 3000" in c:
        print("  already present: max_tokens 3000")
    else:
        print("  NOTE: composer max_tokens is neither 1800 nor 3000; left alone")

    # ---- 3. a quiet ending is not a crash ---------------------------------
    patch(CYCLE,
          '        state.end_cycle(cid, "composer-failed", str(e)[:500])\n'
          '        return 1',
          '        state.end_cycle(cid, "composer-failed", str(e)[:500])\n'
          '        # Exit 0: the cycle ran, the model wrote something odd, and\n'
          '        # nothing is broken. Returning 1 painted systemd red for a\n'
          '        # normal outcome, and a log where everything is red is a log\n'
          '        # in which the real failures cannot be seen.\n'
          '        return 0',
          "a failed proposal no longer looks like a crash",
          marker="Exit 0: the cycle ran, the model wrote something odd")

    import ast
    for f in (DRIVES, CYCLE):
        ast.parse(open(f).read())
    print("\n  modules parse.")
    print("""
  Next:
    sudo systemctl restart riffle-dash
    sudo systemctl start riffle-cycle.service

    cd /opt/riffle && git add -A
    git commit -m "trim over-long prose instead of refusing; raise composer max_tokens; quiet endings are not crashes"
    git push
""")


if __name__ == "__main__":
    main()
