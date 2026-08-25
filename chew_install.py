#!/usr/bin/env python3
"""Chew through a thread, and ask for the time to do it.

    sudo cp chew_install.py /opt/riffle/
    sudo python3 /opt/riffle/chew_install.py
    sudo systemctl restart riffle-dash

TWO THINGS

1. THE WHOLE THREAD IS KEPT, AND READ IN BATCHES

   /api/post/<id> returns every comment in one response — all 109 of #1916.
   Nothing was paginated; we were simply discarding 89 of them. So the full
   set is now stored on first read and a cursor walks it, highest-voted first,
   a batch per cycle. The project block says how many remain unread, and
   `read_more <post_id>` advances.

   That makes reading a thread take several cycles by construction, which is
   the behaviour you wanted: not a skim that decides the thread is
   "fragmented", but a slow pass that can notice something in reply 60.

2. IT CAN ASK FOR MORE CYCLES

   `request_cycle <reason>` schedules another wake within a few minutes
   instead of waiting for the hour. Bounded three ways, because an agent that
   can summon its own compute will:

     max_extra_cycles_per_day   12 by default
     min_gap_seconds            300, so it cannot thrash
     a reason of 20+ characters, recorded in the journal

   The scheduler lives in the dashboard process, which already knows how to
   start a cycle and already refuses to start a second one concurrently. The
   model cannot reach it — it writes a request into the database and something
   else decides.

   If it burns the daily budget on nothing, the journal will show twelve
   requests with twelve reasons and you can read what it thought it was doing.

Backups written as .bak-chew.
"""
import json
import os
import shutil
import sqlite3
import sys

RIFFLE = "/opt/riffle"
CYCLE = f"{RIFFLE}/agent/cycle.py"
PROJECT = f"{RIFFLE}/agent/project.py"
DRIVES = f"{RIFFLE}/agent/drives.py"
CORTEX = f"{RIFFLE}/agent/cortex.py"
DASH = f"{RIFFLE}/agent/dash.py"
CFG = f"{RIFFLE}/config.yaml"
SCHEMA_JSON = f"{RIFFLE}/proposal_schema.json"
DB = "/var/lib/riffle/state.sqlite"

NEW_ACTIONS = {
    "read_more": {"type": "object",
                  "properties": {"post_id": {"type": "integer", "minimum": 1}},
                  "required": ["post_id"], "additionalProperties": False},
    "request_cycle": {"type": "object",
                      "properties": {"reason": {"type": "string"}},
                      "required": ["reason"], "additionalProperties": False},
}


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
    if not os.path.exists(f"{path}.bak-chew"):
        shutil.copy(path, f"{path}.bak-chew")
    open(path, "w").write(s.replace(old, new, 1))
    print(f"  patched: {label}")
    return True


PROJECT_ADD = '''

# ------------------------------------------------------- reading a thread down
# The API hands over every comment at once. Keeping only the first twenty was
# throwing away the other eighty-nine, so the whole set is stored and a cursor
# walks it, highest-voted first, a batch per cycle. Reading a busy thread
# properly is then several cycles of work rather than one skim.

def store_comments(state, read_id, comments):
    import json as _j
    state.db.execute("UPDATE thread_reads SET comments_json=?, cursor=0"
                     " WHERE id=?", (_j.dumps(comments), read_id))
    state.db.commit()


def all_comments(state, read_id):
    import json as _j
    r = state.db.execute("SELECT comments_json FROM thread_reads WHERE id=?",
                         (read_id,)).fetchone()
    if not r or not r["comments_json"]:
        return []
    try:
        return _j.loads(r["comments_json"])
    except Exception:
        return []


def read_row(state, pid, post_id):
    return state.db.execute(
        "SELECT * FROM thread_reads WHERE project_id=? AND post_id=?"
        " ORDER BY id DESC LIMIT 1", (pid, post_id)).fetchone()


def unread_count(state, read_id):
    r = state.db.execute("SELECT cursor, comments_total FROM thread_reads"
                         " WHERE id=?", (read_id,)).fetchone()
    if not r:
        return 0
    return max(0, len(all_comments(state, read_id)) - (r["cursor"] or 0))


def next_batch(state, read_id, n, chars):
    """The next n comments by vote rank, and the text for them."""
    r = state.db.execute("SELECT cursor FROM thread_reads WHERE id=?",
                         (read_id,)).fetchone()
    cur = (r["cursor"] if r else 0) or 0
    cs = all_comments(state, read_id)
    batch = cs[cur:cur + n]
    NL = chr(10)
    lines = []
    for c in batch:
        ref = c.get("ref") or ("#" + str(c.get("id")))
        lines.append("  [" + str(ref) + "] " + str(c.get("author", "?"))
                     + " (" + str(c.get("votes", 0)) + " votes): "
                     + str(c.get("body", ""))[:chars])
    return cur, len(batch), NL.join(lines)


def _unread_hint(state, row):
    """Tell it what it has not seen. A partial read that says so can be acted
    on; one that stays quiet just looks like the thread was short."""
    left = unread_count(state, row["id"])
    if not left:
        return ""
    NL = chr(10)
    return (NL + NL + str(left) + " replies on this thread you have NOT seen. "
            "`read_more " + str(row["post_id"]) + "` takes the next batch. "
            "Something in reply sixty is worth more than a second skim of the "
            "front page.")


def advance(state, read_id, n):
    state.db.execute("UPDATE thread_reads SET cursor = COALESCE(cursor,0) + ?"
                     " WHERE id=?", (n, read_id))
    state.db.commit()
'''

READ_MORE_HANDLER = '''def apply_read_more(state, cfg, cid, p, drive):
    """Take the next batch of replies off a thread already opened."""
    pid_post = p["post_id"]
    proj = project.active(state)
    if not proj:
        state.say("error", "Cycle " + str(cid) + " : read_more needs an open "
                  "project. The batches are stored against it.")
        state.end_cycle(cid, "no-project")
        return 0
    row = project.read_row(state, proj["id"], pid_post)
    if not row:
        state.say("report", "Cycle " + str(cid) + " : nothing stored for #"
                  + str(pid_post) + " yet. Use read_thread first.",
                  {"drive": drive})
        state.end_cycle(cid, "not-read")
        return 0

    tcfg = cfg.get("threads") or {}
    n = int(tcfg.get("batch_comments", 20))
    chars = int(tcfg.get("comment_chars", 400))
    cur, got, text = project.next_batch(state, row["id"], n, chars)
    if not got:
        state.say("report", "Cycle " + str(cid) + " : #" + str(pid_post)
                  + " is fully read. Write down what it amounted to.",
                  {"drive": drive})
        state.end_cycle(cid, "thread-exhausted")
        return 0

    project.advance(state, row["id"], got)
    left = project.unread_count(state, row["id"])
    state.db.execute("UPDATE thread_reads SET replies=? WHERE id=?",
                     (text, row["id"]))
    state.db.commit()
    state.log("read replies " + str(cur + 1) + "-" + str(cur + got) + " of #"
              + str(pid_post) + "; " + str(left) + " left", drive=drive)
    state.say("report", "Cycle " + str(cid) + " : replies "
              + str(cur + 1) + "-" + str(cur + got) + " of #" + str(pid_post)
              + ", " + str(left) + " still unread.", {"drive": drive})
    state.end_cycle(cid, "batch-read")
    return 0


def apply_request_cycle(state, cfg, cid, p, drive):
    """Ask to wake again sooner than the hour.

    Writes a request; the dashboard decides. Bounded by a daily count and a
    minimum gap, because an agent that can summon compute will.
    """
    import datetime as _dt
    e = cfg.get("extra_cycles") or {}
    cap = int(e.get("max_per_day", 12))
    day = utcnow()[:10]
    used = int(state.note("extra_cycles_" + day) or 0)
    if used >= cap:
        state.log("extra cycle refused: " + str(used) + "/" + str(cap)
                  + " used today", level="info", drive=drive)
        state.say("report", "Cycle " + str(cid) + " : I asked to wake again "
                  "and have already used " + str(used) + " of " + str(cap)
                  + " extra cycles today.", {"drive": drive})
        state.end_cycle(cid, "extra-capped")
        return 0
    state.note("extra_cycles_" + day, used + 1)
    state.note("cycle_requested_at", _dt.datetime.now(_dt.timezone.utc).isoformat())
    state.note("cycle_requested_why", p["reason"][:400])
    state.log("asked for another cycle (" + str(used + 1) + "/" + str(cap)
              + "): " + p["reason"][:200], drive=drive)
    state.say("report", "Cycle " + str(cid) + " : asked to wake again soon ("
              + str(used + 1) + "/" + str(cap) + " today). " + p["reason"][:300],
              {"drive": drive})
    state.end_cycle(cid, "cycle-requested")
    return 0


'''

SCHEDULER = '''    _sched_started = False

    @classmethod
    def start_scheduler(cls):
        """Honour the agent's requests for extra cycles.

        Deliberately here rather than in the cycle: the agent writes a request
        into the database and something outside it decides whether to act. It
        cannot reach this loop, and it cannot start a cycle directly.
        """
        if cls._sched_started:
            return
        cls._sched_started = True

        def loop():
            import datetime as _dt
            import time as _t
            while True:
                _t.sleep(30)
                try:
                    st = cls.state
                    req = st.note("cycle_requested_at")
                    if not req:
                        continue
                    e = (cls.cfg.get("extra_cycles") or {})
                    gap = int(e.get("min_gap_seconds", 300))
                    last = st.note("extra_cycle_ran_at")
                    now = _dt.datetime.now(_dt.timezone.utc)
                    if last:
                        try:
                            if (now - _dt.datetime.fromisoformat(last)
                                    ).total_seconds() < gap:
                                continue
                        except ValueError:
                            pass
                    if cls._cycle_running or getattr(cls.worker, "busy", False):
                        continue
                    st.note("cycle_requested_at", "")
                    st.note("extra_cycle_ran_at", now.isoformat())
                    why = st.note("cycle_requested_why") or ""
                    st.log("starting the extra cycle it asked for: " + why[:160])
                    cls().run_cycle() if False else _run_cycle_detached(cls)
                except Exception as exc:
                    try:
                        cls.state.log("scheduler error: " + str(exc)[:200],
                                      level="warn")
                    except Exception:
                        pass

        _th.Thread(target=loop, daemon=True).start()

    def clear_chat(self):'''

RUN_DETACHED = '''

def _run_cycle_detached(cls):
    """Start a cycle without an HTTP request behind it."""
    with cls._cycle_lock:
        if cls._cycle_running:
            return
        cls._cycle_running = True

    def run():
        try:
            subprocess.run(
                [sys.executable, "-m", "agent.cycle", "--config",
                 "/opt/riffle/config.yaml"],
                cwd="/opt/riffle", timeout=2700,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            cls.state.say("error", "extra cycle failed: " + str(e)[:200])
        finally:
            cls._cycle_running = False

    _th.Thread(target=run, daemon=True).start()
'''


def main():
    con = sqlite3.connect(DB)
    cols = [r[1] for r in con.execute("PRAGMA table_info(thread_reads)")] \
        if con.execute("SELECT name FROM sqlite_master WHERE name='thread_reads'"
                       ).fetchone() else []
    if cols:
        for c, d in (("comments_json", "TEXT"), ("cursor", "INTEGER DEFAULT 0")):
            if c not in cols:
                con.execute(f"ALTER TABLE thread_reads ADD COLUMN {c} {d}")
                print(f"  added thread_reads.{c}")
        con.commit()
    else:
        print("  thread_reads not created yet; it will carry the new columns")
    con.close()

    patch(PROJECT,
          "CREATE INDEX IF NOT EXISTS ix_reads_project ON thread_reads(project_id, id);",
          "  comments_json TEXT, cursor INTEGER DEFAULT 0);\n"
          "CREATE INDEX IF NOT EXISTS ix_reads_project ON thread_reads(project_id, id);",
          "cursor columns in the schema", marker="comments_json TEXT, cursor INTEGER")
    # the line above must close the table; drop the old terminator
    s = open(PROJECT).read()
    s = s.replace("  body TEXT, replies TEXT, digest TEXT NOT NULL);\n"
                  "  comments_json TEXT, cursor INTEGER DEFAULT 0);",
                  "  body TEXT, replies TEXT, digest TEXT NOT NULL,\n"
                  "  comments_json TEXT, cursor INTEGER DEFAULT 0);")
    open(PROJECT, "w").write(s)

    if "def store_comments" not in open(PROJECT).read():
        open(PROJECT, "a").write(PROJECT_ADD)
        print("  added batch-reading helpers to project.py")
    else:
        print("  already present: batch-reading helpers")

    # unread count surfaces in the project block. Anchor on the call, not the
    # string beside it — that string carries an escape and matching it through
    # three layers of quoting is how the last two of these went wrong.
    patch(PROJECT,
          "                    + render_read(newest, read_budget))",
          "                    + render_read(newest, read_budget)\n"
          "                    + _unread_hint(state, newest))",
          "unread count in the project block", marker="_unread_hint(state, newest)")

    patch(CYCLE, '    if kind == "read_thread":',
          '''    if kind == "read_more":
        return apply_read_more(state, cfg, cid, payload, drive)

    if kind == "request_cycle":
        return apply_request_cycle(state, cfg, cid, payload, drive)

    if kind == "read_thread":''',
          "cycle routes read_more and request_cycle",
          marker="apply_read_more(state, cfg, cid")

    patch(CYCLE, "def apply_read_thread(state, cfg, cid, p, drive):",
          READ_MORE_HANDLER + "def apply_read_thread(state, cfg, cid, p, drive):",
          "read_more and request_cycle handlers", marker="def apply_read_more(")

    patch(CYCLE,
          '        project.record_read(state, proj["id"], cid, pid, title, str(author),\n'
          '                            total, len(picked), body_part, replies_part, digest)',
          '        project.record_read(state, proj["id"], cid, pid, title, str(author),\n'
          '                            total, len(picked), body_part, replies_part, digest)\n'
          '        # Keep every comment, not the batch that fits. The API gave\n'
          '        # them all; discarding them meant a second read cost another\n'
          '        # fetch and could never reach reply sixty.\n'
          '        _row = project.read_row(state, proj["id"], pid)\n'
          '        if _row:\n'
          '            project.store_comments(state, _row["id"], ranked)\n'
          '            project.advance(state, _row["id"], len(picked))',
          "first read stores every comment", marker="Keep every comment, not the batch")

    patch(DRIVES, '    "read_thread": (["post_id"], [],',
          '''    "read_more": (["post_id"], [],
                  lambda p: {"post_id": _i(p["post_id"], "post_id")}),
    "request_cycle": (["reason"], [],
                      lambda p: {"reason": _s(p["reason"], 20, 400, "reason")}),
    "read_thread": (["post_id"], [],''',
          "read_more and request_cycle in the gate", marker='"read_more": (')

    patch(CORTEX, '  read_thread         {"post_id": int}',
          '''  read_thread         {"post_id": int}
  read_more           {"post_id": int}
  request_cycle       {"reason": >=20 chars}''',
          "contract lists the new actions", marker='read_more           {"post_id"')

    patch(CORTEX, "THE FRONT PAGE IS AN INDEX.",
          '''A BUSY THREAD IS SEVERAL CYCLES OF WORK. read_thread stores every reply and
shows you the highest-voted batch; `read_more` takes the next. Your project
block says how many you have not seen. Working down a hundred replies over six
cycles is worth more than reading six threads once each.

If you are mid-way through something and the hour is too long to wait, ask:
`request_cycle` schedules another wake in a few minutes. There is a daily
budget and your reason goes in the journal, so spend them on work you are
actually in the middle of.

THE FRONT PAGE IS AN INDEX.''',
          "contract explains chewing and asking", marker="A BUSY THREAD IS SEVERAL CYCLES")

    patch(DASH, "    def clear_chat(self):", SCHEDULER,
          "extra-cycle scheduler", marker="def start_scheduler(cls):")

    patch(DASH, "\n\ndef _goals_routes(h):", RUN_DETACHED + "\n\ndef _goals_routes(h):",
          "_run_cycle_detached", marker="def _run_cycle_detached(cls):")

    patch(DASH, "    Handler.worker.start()",
          "    Handler.worker.start()\n    Handler.start_scheduler()",
          "scheduler starts with the dashboard", marker="Handler.start_scheduler()")

    c = open(CFG).read()
    if "\nextra_cycles:" not in c:
        shutil.copy(CFG, f"{CFG}.bak-chew")
        open(CFG, "w").write(c.rstrip() + """

# --- cycles it asks for itself ---------------------------------------------
# request_cycle schedules another wake within min_gap_seconds instead of
# waiting for the hour. Every request carries a reason and lands in the
# journal, so a wasted budget is readable after the fact.
extra_cycles:
  max_per_day: 12
  min_gap_seconds: 300
""")
        print("  appended extra_cycles to config.yaml")
    else:
        print("  already present: extra_cycles")

    c = open(CFG).read()
    if "batch_comments" not in c:
        open(CFG, "w").write(c.replace("  max_comments: 20",
                                       "  max_comments: 20\n  batch_comments: 20"))
        print("  added threads.batch_comments")
    # Match the autonomy LINE, not the bare word — "request_cycle" also
    # appears in the extra_cycles comment written a moment ago, and a
    # substring check silently skipped the entry.
    # Match the autonomy LINE, not the bare word — "request_cycle" also
    # appears in the extra_cycles comment written a moment ago, and a
    # substring check silently skipped the entry. And verify the write landed:
    # a .replace() whose anchor is missing is a no-op that reports success.
    for a in ("read_more: auto", "request_cycle: auto"):
        key = a.split(":")[0]
        c = open(CFG).read()
        if ("\n  " + key + ":") in c:
            print(f"  already present: autonomy {key}")
            continue
        anchor = None
        for cand in ("  read_thread: auto", "  remember: auto", "  seal: auto"):
            if cand in c:
                anchor = cand
                break
        if not anchor:
            sys.exit(f"  FAILED: no autonomy entry to insert {key} after. "
                     f"Add `  {a}` under `autonomy:` by hand.")
        open(CFG, "w").write(c.replace(anchor, anchor + "\n  " + a, 1))
        if ("\n  " + key + ":") not in open(CFG).read():
            sys.exit(f"  FAILED: could not add autonomy {key}.")
        print(f"  added autonomy {a} (after {anchor.strip()})")

    if os.path.exists(SCHEMA_JSON):
        sch = json.load(open(SCHEMA_JSON))
        have = {b["properties"]["action"]["const"] for b in sch["oneOf"]}
        added = 0
        for name, payload in NEW_ACTIONS.items():
            if name in have:
                continue
            sch["oneOf"].append({
                "type": "object",
                "properties": {"action": {"const": name}, "payload": payload,
                               "rationale": {"type": "string"},
                               "sources": {"type": "object"}},
                "required": ["action", "payload", "rationale"],
                "additionalProperties": False})
            added += 1
        if added:
            shutil.copy(SCHEMA_JSON, f"{SCHEMA_JSON}.bak-chew")
            json.dump(sch, open(SCHEMA_JSON, "w"), indent=1)
            print(f"  added {added} action(s) to the schema "
                  f"({len(sch['oneOf'])} branches)")
        else:
            print("  already present: new actions in the schema")

    import ast
    for f in (CYCLE, PROJECT, DRIVES, CORTEX, DASH):
        ast.parse(open(f).read())
    print("\n  modules parse.")
    print("\n  Next:  sudo systemctl restart riffle-dash")


if __name__ == "__main__":
    main()
