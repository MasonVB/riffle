#!/usr/bin/env python3
"""Count a thread once, and say which note is missing.

    sudo cp sources_repair.py /opt/riffle/
    sudo python3 /opt/riffle/sources_repair.py
    sudo systemctl restart riffle-dash

TWO SMALL THINGS THE PROJECT EXPOSED

1. THE SAME THREAD CITED THREE WAYS COUNTS AS THREE SOURCES

   The open project's notes carry `1f916:2224`, `<1f916:2244>` and
   `1F916:2244`. `stats()` counts distinct source strings, and the readiness
   bar asks for a minimum number of them — so citing #2244 twice with
   different punctuation moves the agent closer to being allowed to post
   without it having read anything more.

   That is the failure this whole build is against: a number that goes up
   without the thing it measures going up. Sources are now normalised on the
   way in — case-folded, brackets stripped, `#2244` and `1f916:2244` and
   `<1F916:2244>` all becoming `1f916:2244`. Existing rows are migrated.

2. IT COULD NOT SEE WHICH KIND IT WAS SHORT OF

   Seven notes, four threads, and a genuinely good objection — but no draft,
   which is why cycle 61 declined to post. The readiness text said "it needs a
   draft" only at the end of a sentence about counts. Now the project block
   leads with the single missing kind and says what that kind is for, because
   "you need a draft" is actionable and "not ready" is not.

Backups written as .bak-sources.
"""
import os
import re
import shutil
import sqlite3
import sys

RIFFLE = "/opt/riffle"
PROJECT = f"{RIFFLE}/agent/project.py"
DB = "/var/lib/riffle/state.sqlite"

NORMALISE = '''

def normalise_source(s):
    """One thread, one source string.

    The notes on the first real project cited the same post as `1f916:2224`,
    `<1f916:2244>` and `1F916:2244`. Readiness counts DISTINCT sources, so
    punctuation was inflating the count — a number going up without the thing
    it measures going up, which is the exact failure this agent exists to
    catch. Fixing it here rather than asking the model to be consistent: a
    rule enforced by code holds, a rule in a prompt is a hope.
    """
    if not s:
        return None
    t = str(s).strip().strip("<>[]() ").lower()
    m = re.search(r"(?:1f916[:/#]|#)\\s*(\\d+)", t)
    if m:
        return "1f916:" + m.group(1)
    m = re.match(r"^(\\d{1,7})$", t)
    if m:
        return "1f916:" + m.group(1)
    if t.startswith(("http://", "https://")):
        return t.rstrip("/")
    return t[:300] or None
'''

MISSING_HINT = '''

def missing_kind(state, cfg, pid):
    """The one thing to add next, in the order that makes a post possible.

    Returned as a single instruction rather than a list of deficits: an agent
    told it needs "3 more notes, 1 more source, a draft and an objection" has
    four things to choose between and picks none. One is a task.
    """
    p = cfg.get("projects") or {}
    s = stats(state, pid)
    k = s["by_kind"]
    if k.get("source", 0) < 2 or s["sources"] < int(p.get("min_sources", 2)):
        return ("read another thread and note what it said — you need at least "
                "two distinct sources and you have " + str(s["sources"]))
    if k.get("draft", 0) < int(p.get("min_drafts", 1)):
        return ("write a DRAFT: a paragraph you would actually publish, in your "
                "own words, saying what the sources add up to. You have the "
                "reading and the objection; this is the only kind you are "
                "missing and it is why you cannot post")
    if k.get("objection", 0) < int(p.get("min_objections", 1)):
        return ("write an OBJECTION: the strongest argument against your own "
                "draft. Not a caveat — the thing that would change your mind")
    if s["notes"] < int(p.get("min_notes", 6)):
        return ("add " + str(int(p.get("min_notes", 6)) - s["notes"])
                + " more note(s) of any kind")
    return None
'''


def main():
    s = open(PROJECT).read()

    # project.py imports datetime and json, but not re.
    if "\nimport re\n" not in s:
        anchor = "import json\n"
        if anchor not in s:
            sys.exit("  FAILED: project.py has no json import to anchor on.")
        shutil.copy(PROJECT, f"{PROJECT}.bak-sources")
        s = s.replace(anchor, anchor + "import re\n", 1)
        open(PROJECT, "w").write(s)
        print("  added the missing `import re` to project.py")
    else:
        print("  already present: import re")

    # ---- 1. normalise on the way in ---------------------------------------
    if "def normalise_source(" in s:
        print("  already present: normalise_source")
    else:
        anchor = "def notes(state, pid, limit=60):"
        if anchor not in s:
            sys.exit("  FAILED: could not find notes() in project.py.")
        shutil.copy(PROJECT, f"{PROJECT}.bak-sources")
        s = s.replace(anchor, NORMALISE.strip() + "\n\n\n" + anchor, 1)
        old = ('    c = state.db.execute(\n'
               '        "INSERT INTO project_notes (project_id,cycle_id,ts,kind,text,source)"\n'
               '        " VALUES (?,?,?,?,?,?)", (pid, cycle_id, utcnow(), kind, text, source))')
        if old not in s:
            sys.exit("  FAILED: add_note's INSERT is not what I expected.")
        s = s.replace(old,
                      '    c = state.db.execute(\n'
                      '        "INSERT INTO project_notes (project_id,cycle_id,ts,kind,text,source)"\n'
                      '        " VALUES (?,?,?,?,?,?)", (pid, cycle_id, utcnow(), kind, text,\n'
                      '                                 normalise_source(source)))', 1)
        open(PROJECT, "w").write(s)
        print("  patched: sources normalised as notes are written")

    # ---- 2. the missing-kind hint -----------------------------------------
    s = open(PROJECT).read()
    if "def missing_kind(" in s:
        print("  already present: missing_kind")
    else:
        anchor = "def as_context(state, cfg, budget=5000):"
        if anchor not in s:
            sys.exit("  FAILED: could not find as_context().")
        s = s.replace(anchor, MISSING_HINT.strip() + "\n\n\n" + anchor, 1)
        old = ('    head.append("Add the NEXT increment. Not a restatement of the above — read "')
        if old in s:
            s = s.replace(old,
                          '    _next = missing_kind(state, cfg, proj["id"])\n'
                          '    if _next:\n'
                          '        head.append("THE ONE THING TO DO NEXT ON THIS PROJECT: "\n'
                          '                    + _next + ".")\n'
                          + old, 1)
            print("  patched: the block leads with the single missing kind")
        else:
            print("  NOTE: as_context's closing line differs; missing_kind is\n"
                  "        defined but not wired into the block.")
        open(PROJECT, "w").write(s)

    import ast
    ast.parse(open(PROJECT).read())
    print("  project.py parses")

    # ---- 3. migrate the rows already written -------------------------------
    sys.path.insert(0, RIFFLE)
    from agent.project import normalise_source
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT id, source FROM project_notes WHERE source IS NOT NULL").fetchall()
    changed = 0
    for r in rows:
        n = normalise_source(r["source"])
        if n != r["source"]:
            con.execute("UPDATE project_notes SET source=? WHERE id=?", (n, r["id"]))
            changed += 1
    con.commit()
    print(f"\n  migrated {changed} of {len(rows)} existing source string(s)")
    for r in con.execute(
            "SELECT source, COUNT(*) n FROM project_notes WHERE source IS NOT NULL"
            " GROUP BY source ORDER BY source"):
        print(f"    {r['source']}  x{r['n']}")
    d = con.execute("SELECT COUNT(DISTINCT source) c FROM project_notes"
                    " WHERE source IS NOT NULL").fetchone()
    print(f"  distinct sources now: {d['c']}")
    con.close()

    print("""
  Next:
    sudo systemctl restart riffle-dash
    sudo systemctl start riffle-cycle.service

  The project block should now open with the one thing to do next, which for
  'The emptiness trap' is a draft.""")


if __name__ == "__main__":
    main()
