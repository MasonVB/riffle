"""Something to work on between posts.

THE PROBLEM THIS SOLVES

Every cycle wakes blank, holds the board for about two minutes, and is asked
for one action. Nothing carries a half-formed idea from one wake to the next.
So the only post it can ever write is one it can think of in two minutes from
a cold start — which is exactly what a surface-level post is. Better prompts
do not fix that; a bigger model barely does. What fixes it is somewhere to
put an unfinished thought.

A PROJECT is one question the agent is working on. Cycles append NOTES to it:
an observation, a source it read, a draft paragraph, an objection to its own
argument, a correction. Each cycle sees the question and everything noted so
far, and is asked for the next increment rather than a fresh take.

THE COOLDOWN makes this the default rather than an option. After a post lands,
posting is illegal for 24 hours. There is nowhere for the urge to go except
into the project, and 24 hours of increments is a different artifact from two
minutes of improvisation.

READINESS is the second half, and the part that actually bites. When the
cooldown lifts, a post is still refused unless the active project has enough
behind it — some minimum of notes, and more than one source. Without that the
agent would simply resume posting thin things on a 24-hour cycle instead of an
hourly one. The bar is what makes the waiting mean something.

None of this makes a post GOOD. It makes a thin one harder to produce than a
considered one, which is the only lever a design has.
"""
import datetime as dt
import json
import re

from agent.state import utcnow

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
  id INTEGER PRIMARY KEY, opened_at TEXT, closed_at TEXT,
  title TEXT NOT NULL, question TEXT NOT NULL,
  status TEXT DEFAULT 'active',      -- queued | active | posted | abandoned
  posted_action_id INTEGER);

CREATE TABLE IF NOT EXISTS project_notes (
  id INTEGER PRIMARY KEY, project_id INTEGER, cycle_id INTEGER, ts TEXT,
  kind TEXT,        -- observation | source | draft | objection | correction
  text TEXT NOT NULL,
  source TEXT);     -- a url, a thread id, or null for the agent's own thinking

CREATE INDEX IF NOT EXISTS ix_notes_project ON project_notes(project_id, id);
"""

KINDS = ("observation", "source", "draft", "objection", "correction")


def ensure(state):
    state.db.executescript(SCHEMA)
    state.db.commit()


# ------------------------------------------------------------------ cooldown
def cooldown_until(state):
    v = state.note("post_cooldown_until")
    if not v:
        return None
    try:
        return dt.datetime.fromisoformat(v)
    except ValueError:
        return None


def start_cooldown(state, hours=24):
    until = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=hours)
    state.note("post_cooldown_until", until.isoformat())
    return until


def in_cooldown(state):
    """Returns (bool, until, hours_left)."""
    u = cooldown_until(state)
    if not u:
        return False, None, 0.0
    left = (u - dt.datetime.now(dt.timezone.utc)).total_seconds() / 3600
    return (left > 0), u, max(0.0, left)


# ------------------------------------------------------------------ projects
def active(state):
    return state.db.execute(
        "SELECT * FROM projects WHERE status='active' ORDER BY id DESC LIMIT 1"
    ).fetchone()


def queue(state):
    """Projects waiting their turn, the next one first."""
    return state.db.execute(
        "SELECT * FROM projects WHERE status='queued' ORDER BY id"
    ).fetchall()


def open_project(state, title, question):
    """Open a project, or queue it if one is already running.

    Returns (id, status). This used to raise when a project was open, which
    made "open a project on X" an instruction that could not be carried out
    at the moment you gave it — you had to notice a project was running,
    close it, and ask again. Queueing keeps one project active at a time,
    which is what the readiness bar and the prompt budget are built around,
    while making the request always land somewhere.

    One active project is a deliberate constraint, not a limitation waiting
    to be lifted: a note carries no project id, so with two running the model
    would have to name a target on every note, and a note filed against the
    wrong project is silent and corrupts the bar it lands in.
    """
    title, question = title.strip()[:160], question.strip()[:600]
    status = "queued" if active(state) else "active"
    c = state.db.execute(
        "INSERT INTO projects (opened_at,title,question,status) VALUES (?,?,?,?)",
        (utcnow(), title, question, status))
    state.db.commit()
    return c.lastrowid, status


def promote_next(state):
    """Start the next queued project, if nothing is running. Returns it or None.

    opened_at is reset on promotion so `age_hours` measures how long the
    project has been WORKED, not how long it sat in the queue. ready() reads
    that number, and a project that waited three days has not thereby earned
    anything.
    """
    if active(state):
        return None
    nxt = state.db.execute(
        "SELECT * FROM projects WHERE status='queued' ORDER BY id LIMIT 1").fetchone()
    if not nxt:
        return None
    state.db.execute("UPDATE projects SET status='active', opened_at=? WHERE id=?",
                     (utcnow(), nxt["id"]))
    state.db.commit()
    return state.db.execute("SELECT * FROM projects WHERE id=?",
                            (nxt["id"],)).fetchone()


def drop_queued(state, pid):
    """Remove a project from the queue. Only ever touches a queued row."""
    c = state.db.execute(
        "UPDATE projects SET status='abandoned', closed_at=? "
        "WHERE id=? AND status='queued'", (utcnow(), pid))
    state.db.commit()
    return c.rowcount > 0


def on_posted(state, cfg, action_id, log=None):
    """A post went out. Close the project it came from and start the next one.

    Called from BOTH paths that can send a post: the cycle's own execute, and
    the dashboard when you approve a queued one. It used to live only in the
    cycle — and `post` is `queue`, so the cycle path never runs. Every post
    riffle has ever made was approved by hand, which meant no project was ever
    marked `posted`, the cooldown never started, and the queue never promoted.
    Two projects sit in the database as `abandoned` because they were closed
    by hand afterwards, having each produced a post.

    A project that produced a post is finished, and it should not matter which
    button sent it.
    """
    until = start_cooldown(state, int((cfg.get("projects") or {})
                                      .get("cooldown_hours", 24)))
    proj = active(state)
    nxt = close_project(state, proj["id"], "posted", action_id) if proj else None
    if log:
        if proj:
            log(f"closed '{proj['title']}' as posted")
        log(f"posted; posting closed until {until:%Y-%m-%d %H:%M}Z")
        if nxt:
            log(f"started the next queued project: {nxt['title']}")
    if nxt:
        state.say("report", f"'{proj['title']}' produced its post and is closed. "
                            f"Started the next one in the queue: {nxt['title']}\n"
                            f"{nxt['question']}")
    elif proj:
        state.say("report", f"'{proj['title']}' produced its post and is closed. "
                            f"Nothing is queued behind it.")
    return until, proj, nxt


def close_project(state, pid, status="abandoned", action_id=None):
    """Close a project and start whatever was waiting behind it."""
    state.db.execute(
        "UPDATE projects SET status=?, closed_at=?, posted_action_id=? WHERE id=?",
        (status, utcnow(), action_id, pid))
    state.db.commit()
    return promote_next(state)


def add_note(state, pid, cycle_id, kind, text, source=None,
             cfg_hint=None):
    if kind not in KINDS:
        raise ValueError(f"note kind must be one of {KINDS}")
    text = " ".join(text.split())[:1200]
    # A fourth rewording of one idea is not a fourth increment. add_note
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

    dupe = state.db.execute(
        "SELECT id FROM project_notes WHERE project_id=? AND text=?",
        (pid, text)).fetchone()
    if dupe:
        # A cycle restating an earlier note is the failure mode this whole
        # mechanism exists to prevent. Refuse it loudly rather than let the
        # project fill with the same thought worded differently.
        raise ValueError("that note is already recorded verbatim; add something "
                         "the project does not already contain")
    c = state.db.execute(
        "INSERT INTO project_notes (project_id,cycle_id,ts,kind,text,source)"
        " VALUES (?,?,?,?,?,?)", (pid, cycle_id, utcnow(), kind, text,
                                 normalise_source(source)))
    state.db.commit()
    return c.lastrowid


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
    m = re.search(r"(?:1f916[:/#]|#)\s*(\d+)", t)
    if m:
        return "1f916:" + m.group(1)
    m = re.match(r"^(\d{1,7})$", t)
    if m:
        return "1f916:" + m.group(1)
    if t.startswith(("http://", "https://")):
        return t.rstrip("/")
    return t[:300] or None


def notes(state, pid, limit=60):
    return state.db.execute(
        "SELECT * FROM project_notes WHERE project_id=? ORDER BY id LIMIT ?",
        (pid, limit)).fetchall()


def stats(state, pid):
    rows = notes(state, pid, limit=500)
    srcs = {r["source"] for r in rows if r["source"]}
    by_kind = {}
    for r in rows:
        by_kind[r["kind"]] = by_kind.get(r["kind"], 0) + 1
    p = state.db.execute("SELECT opened_at FROM projects WHERE id=?", (pid,)).fetchone()
    age_h = 0.0
    if p and p["opened_at"]:
        try:
            age_h = (dt.datetime.now(dt.timezone.utc)
                     - dt.datetime.fromisoformat(p["opened_at"].replace("Z", "+00:00"))
                     ).total_seconds() / 3600
        except ValueError:
            pass
    return {"notes": len(rows), "sources": len(srcs), "by_kind": by_kind,
            "age_hours": round(age_h, 1)}


def ready(state, cfg, pid=None):
    """Is there enough behind the active project to be worth a post?

    Returns (ok, reason). The reason is written for the agent to read.
    """
    p = cfg.get("projects") or {}
    min_notes = int(p.get("min_notes", 6))
    min_sources = int(p.get("min_sources", 2))
    min_drafts = int(p.get("min_drafts", 1))
    min_objections = int(p.get("min_objections", 1))

    proj = active(state) if pid is None else state.db.execute(
        "SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
    if not proj:
        return False, ("no project is open. Open one with open_project before "
                       "trying to post — a post should come out of something "
                       "you have been working on.")
    s = stats(state, proj["id"])
    missing = []
    if s["notes"] < min_notes:
        missing.append(f"{min_notes - s['notes']} more note(s)")
    if s["sources"] < min_sources:
        missing.append(f"{min_sources - s['sources']} more distinct source(s)")
    if s["by_kind"].get("draft", 0) < min_drafts:
        missing.append("a draft")
    if s["by_kind"].get("objection", 0) < min_objections:
        missing.append("an objection to your own argument")
    if missing:
        return False, (f"'{proj['title']}' is not ready: it needs "
                       + ", ".join(missing)
                       + f". It currently has {s['notes']} note(s) from "
                         f"{s['sources']} source(s) over {s['age_hours']}h.")
    return True, (f"'{proj['title']}' has {s['notes']} notes from "
                  f"{s['sources']} sources over {s['age_hours']}h, including a "
                  f"draft and an objection. It is ready.")


def missing_kind(state, cfg, pid):
    """The one thing to add next, in the order that makes a post possible.

    Returned as a single instruction rather than a list of deficits: an agent
    told it needs "3 more notes, 1 more source, a draft and an objection" has
    four things to choose between and picks none. One is a task.
    """
    p = cfg.get("projects") or {}
    s = stats(state, pid)
    k = s["by_kind"]
    # DISTINCT SOURCES, counted the way ready() counts them.
    #
    # This used to also require two notes of KIND 'source'. ready() has always
    # counted distinct source strings across every kind, so a project whose
    # second source arrived on an `observation` note satisfied ready() and
    # failed here — and the prompt then said "READY" in one line and, four
    # lines later, "read another thread, you need at least two distinct
    # sources and you have 2".
    #
    # A sentence that contradicts itself inside its own clause, printed under
    # a line saying the project was finished. This was the first thing I
    # diagnosed on this project on 2026-08-28, agreed as the likely reason
    # riffle was not posting, and then never fixed — it went behind the
    # project queue and stayed there for eleven days while the same
    # contradiction printed every cycle.
    #
    # Two lessons, and the second is the useful one. A check and the bar it
    # climbs toward must read the same number from the same place. And a bug
    # you diagnosed but did not fix is worth less than one you never found,
    # because you stop looking.
    if s["sources"] < int(p.get("min_sources", 2)):
        return ("read another thread and note what it said — you need "
                + str(int(p.get("min_sources", 2))) + " distinct sources and "
                "you have " + str(s["sources"]))
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


def as_context(state, cfg, budget=5000):
    """The project block for the cycle prompt.

    Split three ways: the newest thread read in full, the note list, and a
    line per thread already read. The full read gets the largest share because
    it is the thing the next cycle has to act on.
    """
    read_budget = int(budget * 0.55)
    budget = budget - read_budget
    cooling, until, left = in_cooldown(state)
    head = []
    if cooling:
        head.append(f"POSTING IS CLOSED for another {left:.1f}h "
                    f"(until {until:%Y-%m-%d %H:%M}Z). You posted recently. Put "
                    f"the time into the project below instead.")
    proj = active(state)
    if not proj:
        head.append("NO PROJECT IS OPEN. If something on the board is worth more "
                    "than one cycle of thought, open one: a question you cannot "
                    "answer today and can work at.")
        return "\n\n".join(head)

    s = stats(state, proj["id"])
    ok, why = ready(state, cfg)
    # DO NOT SAY "READY" WHILE POSTING IS CLOSED.
    #
    # The cooldown line said posting was shut for another 13 hours and then,
    # four lines later, the same prompt said "It is ready" and the next-step
    # block said "STOP ADDING NOTES AND WRITE THE POST". riffle spent hours
    # trying to post every cycle and refusing to do anything else, which is
    # not obsession — it is a prompt that gives one instruction and forbids
    # it in the same breath. Same shape as the very first bug in this file,
    # where ready() and missing_kind() disagreed.
    #
    # While cooling, `ready` is true but IRRELEVANT, and the prompt should say
    # so plainly rather than leaving the model to reconcile it.
    if cooling and ok:
        head.append(f"YOUR PROJECT: {proj['title']}\n"
                    f"The question: {proj['question']}\n"
                    f"{s['notes']} note(s), {s['sources']} source(s), "
                    f"{s['age_hours']}h old.\n"
                    f"It clears the bar, AND YOU CANNOT POST IT FOR ANOTHER "
                    f"{left:.1f}h. Do not propose a post this cycle; it will be "
                    f"refused and the cycle wasted. The draft keeps. Spend this "
                    f"cycle on something that is not this post: read a thread, "
                    f"answer someone, vote on work you have actually read, say "
                    f"something on the porch, or build.")
    else:
        head.append(f"YOUR PROJECT: {proj['title']}\n"
                    f"The question: {proj['question']}\n"
                    f"{s['notes']} note(s), {s['sources']} source(s), "
                    f"{s['age_hours']}h old. {'READY' if ok else 'NOT READY'} — {why}")

    # ENDING one. The prompt has always said, every cycle and in a whole
    # sentence, when a project is ready to POST. It has never once said what a
    # finished project looks like — so `close_project` existed as a payload
    # shape and nothing else, projects stayed open indefinitely, and this one
    # has reached 17 notes from 15 sources while the same post gets refused
    # again and again. A question you can no longer answer is not a question
    # you should keep answering.
    _q = int((cfg.get("projects") or {}).get("close_after_notes", 24))
    _h = float((cfg.get("projects") or {}).get("close_after_hours", 96))
    _stale = s["notes"] >= _q or s["age_hours"] >= _h
    close_note = (
        "CLOSING IT IS A MOVE YOU HAVE. `close_project` takes a reason and it "
        "is kept. Close when:\n"
        "  - the question is answered, whether by you or by someone else on "
        "the board — say who answered it;\n"
        "  - the question turned out to be the wrong one, and you can say what "
        "the right one is. Close this and open that;\n"
        "  - you have posted what it was for. Then it is done, even if you "
        "could keep reading.\n"
        "Closing is not failure and an abandoned project is not a wasted one: "
        "the notes and the reads are kept either way. Leaving a question open "
        "that you have stopped being able to move is worse than ending it, "
        "because it takes every cycle you would have spent on the next one.")
    if _stale and not cooling:
        close_note = (
            f"THIS PROJECT IS OVERDUE A DECISION: {s['notes']} note(s) over "
            f"{s['age_hours']}h. Either post it or close it this cycle. "
            "Reading one more thread is the answer that has already been "
            "given " + str(len(reads(state, proj["id"]))) + " time(s).\n"
            + close_note)
    head.append(close_note)

    rs = reads(state, proj["id"])
    if rs:
        newest = rs[0]
        head.append("THE THREAD YOU READ MOST RECENTLY:\n"
                    + render_read(newest, read_budget)
                    + _unread_hint(state, newest))
        if len(rs) > 1:
            head.append("THREADS YOU HAVE ALREADY READ — do not read them "
                        "again, what mattered is in your notes:\n"
                        + "\n".join(f"  #{r['post_id']} {r['title'][:70]}"
                                    for r in rs[1:]))

    lines, used = [], 0
    for r in notes(state, proj["id"]):
        line = (f"  [{r['id']}] {r['kind']}"
                + (f" <{r['source']}>" if r["source"] else "") + f": {r['text']}")
        if used + len(line) > budget:
            lines.append(f"  … {s['notes'] - len(lines)} earlier note(s) omitted")
            break
        lines.append(line)
        used += len(line)
    head.append("WHAT YOU HAVE SO FAR:\n" + "\n".join(lines))
    # Muted while cooling. missing_kind returns "STOP ADDING NOTES AND WRITE
    # THE POST" once a project clears the bar, and that is exactly the thing
    # that cannot be done during a cooldown. Printing it under a line saying
    # posting is closed is how riffle came to spend a whole afternoon
    # proposing a post it was forbidden to make.
    _next = None if cooling and ok else missing_kind(state, cfg, proj["id"])
    if _next:
        head.append("THE ONE THING TO DO NEXT ON THIS PROJECT: "
                    + _next + ".")
    if cooling and ok:
        head.append("The project is finished and waiting on the clock. It "
                    "needs nothing more from you today. Anything you add to it "
                    "now is padding, and a cycle spent on a post you cannot "
                    "send is a cycle the square never sees.")
    else:
        head.append("Add the NEXT increment. Not a restatement of the above — "
                    "read a source you have not read, draft a paragraph, or "
                    "find the strongest objection to what you have written. If "
                    "the project is ready and posting is open, promote it.")
    return "\n\n".join(head)


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
  body TEXT, replies TEXT, digest TEXT NOT NULL,
  comments_json TEXT, cursor INTEGER DEFAULT 0);
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
