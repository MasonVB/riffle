#!/usr/bin/env python3
"""Stop a killed generation from spinning forever.

    sudo cp unstick_install.py /opt/riffle/
    sudo python3 /opt/riffle/unstick_install.py
    sudo systemctl restart riffle-dash

THE BUG

The thinking indicator was derived from the database: a message row with
done=0 meant "a reply is streaming into this row". That is true while the
process that opened the row is alive. It is false the moment that process is
restarted — the row is still done=0, nothing is writing to it, and the page
spins forever with no way to recover except editing the database.

Restarting riffle-dash mid-answer is not an edge case here. It is what happens
every time a patch is installed, which in this build is often.

THE FIX

Two changes, and the second is the one that matters.

  A startup sweep closes any row left open by a process that is gone. Those
  are marked interrupted rather than deleted, so the transcript records that
  an answer was cut off instead of silently losing it.

  The indicator now reads the WORKER's actual state instead of inferring it
  from a row. `done` goes back to meaning only what it should mean — whether
  this text is still growing — and liveness is answered by the thing that
  would know. Same shape as two earlier bugs here: one fact with two
  representations, kept in sync by hand.

A third guard catches the case in flight: if a row is open but no worker is
running, the next poll closes it.

Backups written as .bak-unstick.
"""
import os
import shutil
import sys

RIFFLE = "/opt/riffle"
CHAT = f"{RIFFLE}/agent/chat.py"
DASH = f"{RIFFLE}/agent/dash.py"


def patch(path, old, new, label, marker):
    s = open(path).read()
    if marker in s:
        print(f"  already present: {label}")
        return False
    if old not in s:
        sys.exit(f"  FAILED: anchor not found in {os.path.basename(path)} "
                 f"({label}). Nothing changed.")
    if not os.path.exists(f"{path}.bak-unstick"):
        shutil.copy(path, f"{path}.bak-unstick")
    open(path, "w").write(s.replace(old, new, 1))
    print(f"  patched: {label}")
    return True


def main():
    # ---- 1. the worker knows whether it is working ------------------------
    patch(CHAT,
          '''    def __init__(self, state, cfg):
        super().__init__(daemon=True)
        self.state, self.cfg = state, cfg
        self.q = []
        self.cv = threading.Condition()''',
          '''    def __init__(self, state, cfg):
        super().__init__(daemon=True)
        self.state, self.cfg = state, cfg
        self.q = []
        self.cv = threading.Condition()
        # Liveness lives here, not in a database row. A row says whether text
        # is still growing; only this object knows whether anything is still
        # writing to it.
        self.busy = False
        self.busy_since = None''',
          "worker tracks its own busy state", marker="self.busy_since = None")

    patch(CHAT,
          '''            try:
                answer(self.state, self.cfg, question, day)
            except Exception as e:
                self.state.say("error", f"chat worker crashed: {e}")''',
          '''            self.busy = True
            self.busy_since = time.time()
            try:
                answer(self.state, self.cfg, question, day)
            except Exception as e:
                self.state.say("error", f"chat worker crashed: {e}")
            finally:
                self.busy = False
                self.busy_since = None''',
          "busy flag set around the answer", marker="self.busy_since = time.time()")

    # ---- 2. startup sweep --------------------------------------------------
    patch(CHAT,
          '''def report(state, text, meta=None):''',
          '''def close_orphans(state, note="interrupted"):
    """Close rows left open by a process that no longer exists.

    Called at startup. Anything still done=0 here was being written by a
    worker in a previous process, and no amount of waiting will finish it.
    """
    rows = state.db.execute(
        "SELECT id, content FROM messages WHERE done=0").fetchall()
    for r in rows:
        tail = ("\\n\\n[" + note + " — the console restarted while this reply was "
                "being written]") if r["content"] else \\
               ("(" + note + " before this reply started)")
        state.db.execute("UPDATE messages SET content = content || ?, done=1 "
                         "WHERE id=?", (tail, r["id"]))
    state.db.commit()
    return len(rows)


def report(state, text, meta=None):''',
          "close_orphans() sweep", marker="def close_orphans(state")

    patch(DASH,
          '''    goals.seed(st, cfg)
    Handler.cfg, Handler.state = cfg, st''',
          '''    goals.seed(st, cfg)
    orphans = chat.close_orphans(st)
    if orphans:
        print(f"closed {orphans} interrupted reply row(s) from a previous run")
        st.log(f"startup: closed {orphans} reply row(s) left open by a restart")
    Handler.cfg, Handler.state = cfg, st''',
          "dash sweeps orphans at startup", marker="chat.close_orphans(st)")

    # ---- 3. the indicator reads the worker --------------------------------
    patch(DASH,
          """    def snapshot(self, after):
        s, cfg = self.state, self.cfg""",
          """    def snapshot(self, after):
        s, cfg = self.state, self.cfg
        # Ask the worker, not the database. A row left open with nobody writing
        # to it is a ghost, and the page used to spin on it forever. Do this
        # BEFORE reading the rows, or this poll still reports the stale one as
        # open and the client waits another cycle for the truth.
        w = self.worker
        generating = bool(getattr(w, "busy", False)) or w.depth() > 0
        if not generating and s.pending_generation() is not None:
            chat.close_orphans(s, "interrupted")""",
          "snapshot derives liveness from the worker, before reading rows",
          marker="Ask the worker, not the database")

    patch(DASH,
          '''                "generating": s.pending_generation() is not None or self.worker.depth() > 0,''',
          '''                "generating": generating,''',
          "generating flag uses the worker", marker='"generating": generating,')

    s = open(CHAT).read()
    if "\nimport time" not in s:
        patch(CHAT, "import threading", "import threading\nimport time",
              "chat imports time", marker="import time")

    import ast
    for f in (CHAT, DASH):
        ast.parse(open(f).read())
    print("\n  modules parse.")
    print("""
  Next:
    sudo systemctl restart riffle-dash

  The restart itself will close the stuck row and the spinner will clear.
  Ask it the #1845 question again once it is back.""")


if __name__ == "__main__":
    main()
