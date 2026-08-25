#!/usr/bin/env python3
"""Read a thread properly, and keep the reading somewhere it fits.

    sudo cp thread_install.py /opt/riffle/
    sudo python3 /opt/riffle/thread_install.py
    sudo systemctl restart riffle-dash

WHAT WAS WRONG

read_thread worked — /api/post/<id> really does return `comments` as a list of
dicts — but it kept 12 of them at 300 characters each, then squeezed the whole
reply section into 900. On #1916, which has 109 comments, that is the first
three replies in posting order and no indication the other 106 exist.

Raising the cap alone would have done nothing. The digest became a project
note, and add_note truncates every note to 1,200 characters. The read needed
somewhere other than a note to live.

WHAT CHANGES

  A thread_reads table. The full read — post body plus the highest-voted
  replies — is stored there, not squeezed into a note.

  The project block carries the MOST RECENT read in full, and older ones as
  one-line references. So the cycle right after a read sees the whole thread,
  and later cycles see that it happened without paying for it again. Prefill
  is more than half the wall clock here; a thread cannot sit in every prompt
  forever.

  Replies are chosen BY VOTES, not by arrival. Twelve arbitrary early comments
  on a 109-comment thread is a worse sample than the twelve the square itself
  ranked highest, and on a governance thread the difference is the argument.

  The digest states `showing 20 of 109`. A partial read that says so can be
  reasoned about; one that does not is just wrong quietly.

Backups written as .bak-thread.
"""
import os
import shutil
import sys

RIFFLE = "/opt/riffle"
CYCLE = f"{RIFFLE}/agent/cycle.py"
PROJECT = f"{RIFFLE}/agent/project.py"


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
    if not os.path.exists(f"{path}.bak-thread"):
        shutil.copy(path, f"{path}.bak-thread")
    open(path, "w").write(s.replace(old, new, 1))
    print(f"  patched: {label}")
    return True


PROJECT_ADD = '''

# ---------------------------------------------------------------- thread reads
# A thread read does not fit in a note. add_note caps text at 1,200 characters,
# and a governance thread with a hundred replies is worth more than that on the
# cycle after it is read — but not worth carrying in every prompt forever. So
# reads live here, the newest appears in full, and the rest become one line.

READS_SCHEMA = """
CREATE TABLE IF NOT EXISTS thread_reads (
  id INTEGER PRIMARY KEY, project_id INTEGER, cycle_id INTEGER, ts TEXT,
  post_id INTEGER, title TEXT, author TEXT,
  comments_total INTEGER, comments_shown INTEGER,
  -- Body and replies are kept apart on purpose. Stored as one blob, a long
  -- post consumes the whole render budget and the replies never appear —
  -- which on a governance thread drops the actual argument. Split, each gets
  -- its own share, and the full text stays here whatever the block can show.
  body TEXT, replies TEXT, digest TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_reads_project ON thread_reads(project_id, id);
"""


def record_read(state, pid, cycle_id, post_id, title, author,
                total, shown, body, replies, digest):
    state.db.executescript(READS_SCHEMA)
    state.db.execute(
        "INSERT INTO thread_reads (project_id,cycle_id,ts,post_id,title,author,"
        "comments_total,comments_shown,body,replies,digest)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (pid, cycle_id, utcnow(), post_id, title[:200], author[:80],
         total, shown, body, replies, digest))
    state.db.commit()


def render_read(r, budget):
    """Fit one read into `budget`, giving the replies the larger share.

    The post says what someone proposed; the replies say what the square
    thinks of it. When only one fits, the replies are the more informative
    half, so they get 60% of the room and the body 40%.
    """
    NL = chr(10)
    Q = chr(34)
    head = (str(r["post_id"]).join(["#", " "]) + Q + str(r["title"]) + Q
            + " by " + str(r["author"]) + " ("
            + str(r["comments_shown"]) + " of " + str(r["comments_total"])
            + " replies, highest-voted first)" + NL + NL)
    room = max(400, budget - len(head))
    body, reps = (r["body"] or ""), (r["replies"] or "")
    if not reps:
        return head + body[:room] + (" [...]" if len(body) > room else "")
    b_room, r_room = int(room * 0.40), int(room * 0.60)
    if len(body) < b_room:
        r_room += b_room - len(body)
    elif len(reps) < r_room:
        b_room += r_room - len(reps)
    out = head + body[:b_room]
    if len(body) > b_room:
        out += NL + "[body cut at " + str(b_room) + " of " + str(len(body)) + " chars]"
    out += NL + NL + "REPLIES:" + NL + reps[:r_room]
    if len(reps) > r_room:
        out += NL + "[replies cut at " + str(r_room) + " of " + str(len(reps)) + " chars]"
    return out


def reads(state, pid, limit=20):
    try:
        return state.db.execute(
            "SELECT * FROM thread_reads WHERE project_id=? ORDER BY id DESC"
            " LIMIT ?", (pid, limit)).fetchall()
    except Exception:
        return []


def already_read(state, pid, post_id):
    try:
        return state.db.execute(
            "SELECT 1 FROM thread_reads WHERE project_id=? AND post_id=?",
            (pid, post_id)).fetchone() is not None
    except Exception:
        return False
'''

AS_CONTEXT_ADD = '''    rs = reads(state, proj["id"])
    if rs:
        newest = rs[0]
        head.append("THE THREAD YOU READ MOST RECENTLY:\\n"
                    + render_read(newest, read_budget))
        if len(rs) > 1:
            head.append("THREADS YOU HAVE ALREADY READ — do not read them "
                        "again, what mattered is in your notes:\\n"
                        + "\\n".join(f"  #{r['post_id']} {r['title'][:70]}"
                                    for r in rs[1:]))

'''

NEW_READ = '''def apply_read_thread(state, cfg, cid, p, drive):
    """Open a post properly and keep what it said.

    The front page is an index. Without this the agent could see that a thread
    existed and never read it, which is what it kept apologising for.

    Replies are taken by VOTES rather than by arrival. On a thread with a
    hundred comments the first dozen chronologically are close to a random
    sample; the dozen the square voted up are the argument.
    """
    pid = p["post_id"]
    try:
        data = Reader(cfg["base"]).post(pid)
    except HttpError as e:
        state.log(f"could not read post {pid}: {e}", level="warn", drive=drive)
        state.say("error", f"Cycle {cid} · could not open #{pid}: {e}")
        state.end_cycle(cid, "read-failed")
        return 0

    tcfg = cfg.get("threads") or {}
    max_c = int(tcfg.get("max_comments", 20))
    per_c = int(tcfg.get("comment_chars", 400))
    body_c = int(tcfg.get("body_chars", 4000))

    post = data.get("post") or data
    title = str(post.get("title") or "")[:200]
    body = str(post.get("body") or "")
    author = post.get("author") or "?"
    raw = data.get("comments")
    raw = raw if isinstance(raw, list) else []
    comments = [c for c in raw if isinstance(c, dict)]
    total = data.get("comments_total")
    if not isinstance(total, int):
        total = len(comments)

    ranked = sorted(comments, key=lambda c: (c.get("votes") or 0), reverse=True)
    picked = ranked[:max_c]
    lines = [f"  [{c.get('ref') or c.get('id')}] {c.get('author', '?')} "
             f"({c.get('votes', 0)} votes): {str(c.get('body', ''))[:per_c]}"
             for c in picked]

    body_part = body[:body_c]
    replies_part = "\\n".join(lines)
    digest = (f"#{pid} \\"{title}\\" by {author} ({post.get('votes', 0)} votes)\\n\\n"
              + body_part
              + (f"\\n\\nREPLIES — {len(picked)} of {total}, highest-voted "
                 f"first:\\n" + replies_part if picked else "\\n\\n(no replies)"))

    proj = project.active(state)
    if proj:
        if project.already_read(state, proj["id"], pid):
            state.log(f"#{pid} was already read on this project", drive=drive)
            state.say("report", f"Cycle {cid} · #{pid} is already in this "
                                f"project's reading. Read something else, or "
                                f"write a note about what it said.",
                      {"drive": drive})
            state.end_cycle(cid, "already-read")
            return 0
        project.record_read(state, proj["id"], cid, pid, title, str(author),
                            total, len(picked), body_part, replies_part, digest)
        try:
            project.add_note(
                state, proj["id"], cid, "source",
                f"Read #{pid} \\"{title[:90]}\\" by {author}: {len(body)} chars, "
                f"{total} replies. Full text is in your project block this "
                f"cycle — write down what mattered before it drops to a "
                f"reference.", source=f"1f916:{pid}")
        except ValueError:
            pass
        s = project.stats(state, proj["id"])
        where = (f"filed into '{proj['title']}' — {s['notes']} notes from "
                 f"{s['sources']} sources")
    else:
        memory.remember(state, digest[:600], kind="board", source=f"1f916:{pid}")
        where = ("no project is open, so only a fragment went to short-term "
                 "memory. Open a project if this thread is worth returning to.")

    state.log(f"read #{pid}: {len(body)} chars, {len(picked)} of {total} "
              f"replies; {where}", drive=drive)
    state.say("report", f"Cycle {cid} · read #{pid} \\"{title[:80]}\\" — "
                        f"{len(body)} chars, {len(picked)} of {total} replies "
                        f"by votes. {where}", {"drive": drive})
    state.end_cycle(cid, "thread-read")
    return 0
'''


def main():
    # ---- project.py: reads table -----------------------------------------
    s = open(PROJECT).read()
    if "thread_reads" not in s:
        shutil.copy(PROJECT, f"{PROJECT}.bak-thread")
        open(PROJECT, "w").write(s.rstrip() + "\n" + PROJECT_ADD)
        print("  added thread_reads to project.py")
    else:
        print("  already present: thread_reads")

    patch(PROJECT,
          '''def as_context(state, cfg, budget=5000):
    """The project block for the cycle prompt."""''',
          '''def as_context(state, cfg, budget=5000):
    """The project block for the cycle prompt.

    Split three ways: the newest thread read in full, the note list, and a
    line per thread already read. The full read gets the largest share because
    it is the thing the next cycle has to act on.
    """
    read_budget = int(budget * 0.55)
    budget = budget - read_budget''',
          "as_context reserves room for the newest read",
          marker="read_budget = int(budget * 0.55)")

    patch(PROJECT,
          '''    lines, used = [], 0
    for r in notes(state, proj["id"]):''',
          AS_CONTEXT_ADD + '''    lines, used = [], 0
    for r in notes(state, proj["id"]):''',
          "newest read appears in full, older ones as references",
          marker="THE THREAD YOU READ MOST RECENTLY")

    # ---- cycle.py: the new handler ---------------------------------------
    s = open(CYCLE).read()
    if "highest-voted first" in s:
        print("  already present: vote-ranked read_thread")
    else:
        start = s.index("def apply_read_thread(state, cfg, cid, p, drive):")
        end = s.index("def apply_project(state, cfg, cid, kind, p, drive, rationale):")
        if not os.path.exists(f"{CYCLE}.bak-thread"):
            shutil.copy(CYCLE, f"{CYCLE}.bak-thread")
        open(CYCLE, "w").write(s[:start] + NEW_READ + "\n\n" + s[end:])
        print("  patched: read_thread ranks replies by votes and stores the "
              "full read")

    # ---- config -----------------------------------------------------------
    cfgp = f"{RIFFLE}/config.yaml"
    c = open(cfgp).read()
    if "\nthreads:" not in c:
        shutil.copy(cfgp, f"{cfgp}.bak-thread")
        open(cfgp, "w").write(c.rstrip() + """

# --- how much of a thread to take ------------------------------------------
# Replies are taken highest-voted first, and the digest says how many of how
# many. Raising these costs prefill on the cycle after each read, which is
# already more than half the wall clock — so raise them when a thread is
# genuinely worth it, not by default.
threads:
  max_comments: 20
  comment_chars: 400
  body_chars: 4000
""")
        print("  appended threads block to config.yaml")
    else:
        print("  already present: threads block")

    import ast
    for f in (CYCLE, PROJECT):
        ast.parse(open(f).read())
    print("\n  modules parse.")
    print("\n  Next:  sudo systemctl restart riffle-dash")


if __name__ == "__main__":
    main()
