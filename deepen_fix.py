#!/usr/bin/env python3
"""Clear the deepen restriction, catch whatever keeps setting it, and stop the
re-read loop.

    sudo cp deepen_fix.py /opt/riffle/
    sudo python3 /opt/riffle/deepen_fix.py
    sudo systemctl restart riffle-dash

THREE THINGS

1. `selects` on the drives table is a whitelist: if it is set, that drive may
   propose nothing else. It ships set on `earn` alone, deliberately — money
   must not be able to select a social act. Nothing should be setting it on
   `deepen`, and I cannot find the code that does.

   So this clears it on every drive except earn, and installs a SQLite trigger
   that records any future change to `selects` or `forbids` into
   drive_changes. Next time it happens there will be a timestamp to correlate
   against the journal, instead of two of us guessing.

   I would rather say plainly that I do not know than invent a cause.

2. Cycles 38 and 39 both read #2115 and both threw it away, because the
   already-read check only applies when a project is open. Reading a thread
   with nowhere to put it is a cycle spent on nothing, twice. Now a read
   without a project is refused with a specific instruction: open a project
   first, and here is the title to use.

3. `open_project` is nudged when the agent has read something and has nowhere
   to keep it, which is the state it kept ending up in.

Backups written as .bak-deepen.
"""
import os
import shutil
import sqlite3
import sys

RIFFLE = "/opt/riffle"
CYCLE = f"{RIFFLE}/agent/cycle.py"
DB = "/var/lib/riffle/state.sqlite"

TRIGGERS = """
-- Whatever writes `selects` will now leave a trace. drive_changes already
-- records weight and lock edits with an actor; these two extend that to the
-- columns nothing was supposed to touch.
DROP TRIGGER IF EXISTS trg_drives_selects;
CREATE TRIGGER trg_drives_selects AFTER UPDATE OF selects ON drives
WHEN IFNULL(OLD.selects,'') <> IFNULL(NEW.selects,'')
BEGIN
  INSERT INTO drive_changes (ts, name, field, old, new, actor, reason)
  VALUES (strftime('%Y-%m-%dT%H:%M:%SZ','now'), NEW.name, 'selects',
          IFNULL(OLD.selects,''), IFNULL(NEW.selects,''), 'unknown',
          'recorded by trigger; nothing in the code should write this');
END;

DROP TRIGGER IF EXISTS trg_drives_forbids;
CREATE TRIGGER trg_drives_forbids AFTER UPDATE OF forbids ON drives
WHEN IFNULL(OLD.forbids,'') <> IFNULL(NEW.forbids,'')
BEGIN
  INSERT INTO drive_changes (ts, name, field, old, new, actor, reason)
  VALUES (strftime('%Y-%m-%dT%H:%M:%SZ','now'), NEW.name, 'forbids',
          IFNULL(OLD.forbids,''), IFNULL(NEW.forbids,''), 'unknown',
          'recorded by trigger');
END;
"""

NO_PROJECT = '''    else:
        # Reading with nowhere to put it is a wasted cycle, and it happened
        # twice in a row on #2115. Refuse, and say exactly what to do instead.
        memory.remember(state, digest[:600], kind="board", source=f"1f916:{pid}")
        state.log(f"read #{pid} with no project open; refusing to do it again",
                  level="info", drive=drive)
        state.say("report", "Cycle " + str(cid) + " : I opened #" + str(pid)
                  + " with no project to keep it in, so almost all of it is "
                  "gone. Before reading anything else, open a project — "
                  "something like: open_project title=\\"" + title[:70]
                  + "\\" question=<what you actually want to settle about it>. "
                  "Then read it again and it will stay.", {"drive": drive})
        state.end_cycle(cid, "read-no-project")
        return 0
'''


def main():
    # ---- 1. clear and audit ----------------------------------------------
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    before = con.execute("SELECT name, selects, forbids FROM drives").fetchall()
    print("  drives before:")
    for r in before:
        print(f"    {r['name']:<12} selects={r['selects'] or '-'}  "
              f"forbids={(r['forbids'] or '-')[:44]}")

    n = con.execute("UPDATE drives SET selects=NULL WHERE name<>'earn'"
                    " AND selects IS NOT NULL").rowcount
    con.commit()
    print(f"\n  cleared `selects` on {n} drive(s) other than earn")

    con.executescript(TRIGGERS)
    con.commit()
    trigs = [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='trigger'")]
    print(f"  audit triggers installed: {', '.join(trigs)}")

    print("\n  drives after:")
    for r in con.execute("SELECT name, selects FROM drives"):
        print(f"    {r['name']:<12} selects={r['selects'] or '-'}")
    con.close()

    # ---- 2. no-project read -----------------------------------------------
    s = open(CYCLE).read()
    if "refusing to do it again" in s:
        print("\n  already present: no-project read refusal")
    else:
        old = '''    else:
        memory.remember(state, digest[:600], kind="board", source=f"1f916:{pid}")
        where = ("no project is open, so only a fragment went to short-term "
                 "memory. Open a project if this thread is worth returning to.")
'''
        if old not in s:
            print("\n  NOTE: could not find the no-project branch; skipping "
                  "that fix. The trigger and the clear above still applied.")
        else:
            shutil.copy(CYCLE, f"{CYCLE}.bak-deepen")
            open(CYCLE, "w").write(s.replace(old, NO_PROJECT, 1))
            import ast
            ast.parse(open(CYCLE).read())
            print("\n  patched: a read with no project is refused, with the "
                  "title to use")

    print("""
  Next:
    sudo systemctl restart riffle-dash
    sudo systemctl start riffle-cycle.service

  If 'deepen' gets restricted again, this will now say when and to what:

    sudo sqlite3 -header -column /var/lib/riffle/state.sqlite \\
      "SELECT ts, name, field, old, new, actor FROM drive_changes
         WHERE field IN ('selects','forbids') ORDER BY id DESC LIMIT 10;"
""")


if __name__ == "__main__":
    main()
