"""Durable state. The agent wakes blank every cycle; this file is its memory.

Two design rules worth stating because they are load-bearing:

1. Every action row records WHICH DRIVE SELECTED IT. A weighted desire table
   that leaves no trace is decoration. Attribution is what lets the dashboard
   show you that "contribute" has not fired in nine days while "vote" fired
   forty times.

2. Caps are counted locally against the UTC day, independently of the server.
   The server enforces its own; if the two ever disagree, that disagreement is
   a finding rather than an inconvenience. The machine has no RTC worth
   trusting, so the UTC day comes from the server's `now_utc` when available.
"""
import datetime as dt
import json
import os
import sqlite3
import threading

SCHEMA = """
CREATE TABLE IF NOT EXISTS cycles (
  id INTEGER PRIMARY KEY, started_at TEXT, ended_at TEXT,
  drive TEXT, outcome TEXT, notes TEXT);

CREATE TABLE IF NOT EXISTS actions (
  id INTEGER PRIMARY KEY, cycle_id INTEGER, created_at TEXT,
  kind TEXT, drive TEXT, payload TEXT, rationale TEXT,
  status TEXT,               -- proposed | queued | approved | rejected | executed | failed | blocked
  numcheck TEXT, executed_at TEXT, response TEXT,
  notified INTEGER DEFAULT 0);

CREATE TABLE IF NOT EXISTS caps (
  day_utc TEXT, kind TEXT, used INTEGER, PRIMARY KEY (day_utc, kind));

CREATE TABLE IF NOT EXISTS journal (
  id INTEGER PRIMARY KEY, ts TEXT, level TEXT, drive TEXT, text TEXT);

CREATE TABLE IF NOT EXISTS heads (
  ts TEXT, chain TEXT, head TEXT, through_id INTEGER);

-- Goals live in the DATABASE, not in config.yaml. config.yaml seeds them on
-- first run and is never written back, because the agent may adjust its own
-- weights and the agent cannot write /opt/riffle. Everything that bounds the
-- agent — caps, autonomy, model, base URL — stays in the file, ssh-only.
CREATE TABLE IF NOT EXISTS drives (
  name TEXT PRIMARY KEY,
  weight REAL NOT NULL,
  locked INTEGER NOT NULL DEFAULT 0,   -- 1 = only you may change it
  description TEXT,
  selects TEXT,                        -- json: action kinds this drive may select
  forbids TEXT,                        -- json: action kinds it may never select
  created_at TEXT, created_by TEXT);

-- Every weight change, by either party, with a reason. A drive table that
-- can move without leaving a trace is not a set of goals, it is a mood.
CREATE TABLE IF NOT EXISTS drive_changes (
  id INTEGER PRIMARY KEY, ts TEXT, name TEXT,
  field TEXT, old TEXT, new TEXT, actor TEXT, reason TEXT);

-- Durable memory. The agent wakes blank; these are the things it chose to
-- carry forward. Retrieval is FTS5 keyword match, which is what this CPU can
-- afford — there is no embedding model in the budget.
CREATE TABLE IF NOT EXISTS memories (
  id INTEGER PRIMARY KEY, ts TEXT,
  kind TEXT,              -- operator | board | self | commitment
  text TEXT NOT NULL,
  source TEXT,            -- 'chat:142', 'cycle:41', 'you'
  pinned INTEGER DEFAULT 0,
  use_count INTEGER DEFAULT 0, last_used TEXT,
  superseded_by INTEGER,
  tier TEXT DEFAULT 'short',   -- short (expires) | long (forever)
  expires_at TEXT,
  expired INTEGER DEFAULT 0);

CREATE TABLE IF NOT EXISTS notes (
  key TEXT PRIMARY KEY, value TEXT, updated_at TEXT);

-- The conversation. One long-running thread between you and the agent.
-- 'report' rows are written by the wake cycle without you asking, so opening
-- the page shows what it has been doing since you last looked.
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY, ts TEXT,
  role TEXT,            -- user | agent | report | proposal | error
  content TEXT,
  meta TEXT,            -- json: action_id, drive, tool calls, elapsed_s
  done INTEGER DEFAULT 1,   -- 0 while a response is still streaming in
  archived_at TEXT);        -- set by the clear button; never deleted

CREATE TABLE IF NOT EXISTS seen (
  kind TEXT, ref TEXT, ts TEXT, PRIMARY KEY (kind, ref));

CREATE INDEX IF NOT EXISTS ix_actions_status ON actions(status);
CREATE INDEX IF NOT EXISTS ix_journal_ts ON journal(ts);
CREATE INDEX IF NOT EXISTS ix_messages_id ON messages(id);
CREATE INDEX IF NOT EXISTS ix_mem_pinned ON memories(pinned, id);
"""


# Set by telemetry.install(). Left as None so state.py imports
# standalone and nothing here depends on telemetry existing.
ERROR_HOOK = None


_OUTCOME_LINE = {
    "queue-full":       "I stopped early — too many proposals are waiting for you.",
    "no-project":       "I could not act: that needed an open project.",
    "not-read":         "Nothing was stored for that thread yet.",
    "fetched":          "I read one of the square's public surfaces.",
    "fetch-failed":     "I tried to read a public surface and could not.",
    "project-opened":   "I opened a project.",
    "project-queued":   "I queued a project behind the running one.",
    "project-closed":   "I closed a project.",
    "numcheck-blocked": "I wrote something carrying figures I could not trace, "
                        "so it was blocked before sending.",
    "executed":         "I acted on the square.",
    "queued":           "I proposed something; it is waiting for your approval.",
    "failed":           "The registry refused what I sent.",
    "refused":          "The gate refused my own proposal.",
    "noop":             "I looked and chose to do nothing.",
    "no-proposal":      "The composer did not return a usable proposal.",
    "busy":             "The composer was busy, so I skipped this wake.",
    "desk-placed":      "I put something on my desk to come back to.",
    "desk-updated":     "I changed something on my desk.",
    "desk-cleared":     "I took something off my desk; it is done.",
    "desk-empty-slot":  "I tried to clear a desk slot that was already empty.",
    "desk-refused":     "The desk refused what I tried to put on it.",
    "built":            "I wrote code and ran it in the sandbox; it worked.",
    "build-error":      "I wrote code and ran it in the sandbox; it failed.",
    "build-failed":     "The sandbox did not answer.",
    "build-refused":    "The sandbox refused the files I gave it.",
    "signed":           "I asked for a signature and got one.",
    "sign-failed":      "The signer did not answer.",
    "sign-refused":     "The signer refused what I asked it to sign.",
    "composer-busy":    "The composer was busy with something else, so I "
                        "skipped this wake rather than queue behind it.",
    "composer-failed":  "The composer did not come back with a usable answer.",
    "cooldown":         "I am in the post cooldown, so I left the square alone.",
    "cap-reached":      "I have spent today's allowance for that action.",
    "extra-capped":     "I have already asked to wake early as often as I may.",
    "cycle-requested":  "I asked to wake again sooner.",
    "blocked":          "What I wrote was blocked before it could be sent.",
    "goal-refused":     "The gate refused a change I proposed to my own goals.",
    "project-refused":  "The gate refused what I proposed for the project.",
    "adjusted":         "I moved one of my own drive weights.",
    "note-added":       "I wrote a note into the open project.",
    "remembered":       "I wrote something down to keep.",
    "not-ready":        "The project is not at the bar yet, so I did not post.",
    "thread-read":      "I read a thread and filed it into the project.",
    "batch-read":       "I took the next batch of replies off a thread.",
    "thread-exhausted": "That thread is fully read.",
    "already-read":     "I had already read that thread; I need a different one.",
    "read-failed":      "I tried to open a thread and could not.",
    "read-no-project":  "I opened a thread with no project to keep it in, so "
                        "most of it is gone.",
}


def utcnow():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class State:
    """Thread-safe by giving each thread its own connection.

    The dashboard is a ThreadingHTTPServer, so a single shared sqlite3
    connection raises ProgrammingError on the second concurrent request. WAL
    mode plus one connection per thread is the simple correct answer; the
    write volume here is a handful of rows per day.
    """

    def __init__(self, path):
        os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
        self.path = path
        self._local = threading.local()
        with self._connect() as c:
            c.executescript(SCHEMA)

    def _connect(self):
        c = sqlite3.connect(self.path, timeout=30)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA busy_timeout=30000")
        return c

    @property
    def db(self):
        c = getattr(self._local, "conn", None)
        if c is None:
            c = self._local.conn = self._connect()
        return c

    # ---- journal ---------------------------------------------------------
    def log(self, text, level="info", drive=None):
        self.db.execute("INSERT INTO journal (ts,level,drive,text) VALUES (?,?,?,?)",
                        (utcnow(), level, drive, text))
        self.db.commit()
        # An error writes a full telemetry dump, without every call site
        # having to remember to ask for one. Registered by telemetry.install()
        # so state.py keeps no dependency on it, and wrapped because a broken
        # watcher must not break the thing it is watching.
        if level in ("error", "alarm") and ERROR_HOOK is not None:
            try:
                ERROR_HOOK(self, level, text)
            except Exception:
                pass

    def recent_journal(self, n=100):
        return self.db.execute(
            "SELECT * FROM journal ORDER BY id DESC LIMIT ?", (n,)).fetchall()

    # ---- cycles ----------------------------------------------------------
    def begin_cycle(self, drive):
        cur = self.db.execute("INSERT INTO cycles (started_at,drive,outcome) VALUES (?,?,?)",
                              (utcnow(), drive, "running"))
        self.db.commit()
        return cur.lastrowid

    def end_cycle(self, cid, outcome, notes=""):
        self.db.execute("UPDATE cycles SET ended_at=?, outcome=?, notes=? WHERE id=?",
                        (utcnow(), outcome, notes, cid))
        self.db.commit()
        # Every cycle leaves a line in the chat, not only the ones that had
        # something eloquent to say. Reflexive outcomes used to end in silence
        # — the journal had them and the chat did not, so the only thing that
        # appeared hourly was the witness pass and the box looked idle when it
        # was working. Skipped when this cycle already spoke for itself, so a
        # real report is never followed by a bland summary of the same thing.
        if outcome == "not-due":
            return
        # Match on the content prefix as well as the meta key. Every report a
        # cycle writes already opens with "Cycle N ·" by convention, but the
        # meta almost all of them pass is {"drive": ...} with no cycle id — so
        # json_extract returned NULL, nothing matched, and a cycle that had
        # just explained itself got a second, blander line underneath:
        #
        #   Cycle 134 · drive earn · read listings. Kept 5000 characters...
        #   Cycle 134 · I read one of the square's public surfaces.
        #
        # Checking both means the dedup works whichever way a call site tags
        # its message, instead of only the way none of them do.
        spoke = self.db.execute(
            "SELECT 1 FROM messages WHERE role IN ('report','error','proposal')"
            " AND (json_extract(meta,'$.cycle') = ? OR content LIKE ?)",
            (cid, f"Cycle {cid} %")).fetchone()
        if spoke:
            return
        self.say("report", f"Cycle {cid} \u00b7 {_OUTCOME_LINE.get(outcome, outcome)}",
                 {"cycle": cid, "outcome": outcome})

    def recent_cycles(self, n=30):
        return self.db.execute("SELECT * FROM cycles ORDER BY id DESC LIMIT ?", (n,)).fetchall()

    # ---- actions ---------------------------------------------------------
    def propose(self, cycle_id, kind, drive, payload, rationale, status, numcheck=None):
        cur = self.db.execute(
            "INSERT INTO actions (cycle_id,created_at,kind,drive,payload,rationale,status,numcheck)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (cycle_id, utcnow(), kind, drive, json.dumps(payload), rationale, status,
             json.dumps(numcheck) if numcheck else None))
        self.db.commit()
        return cur.lastrowid

    def set_status(self, aid, status, response=None):
        self.db.execute(
            "UPDATE actions SET status=?, response=?, executed_at=? WHERE id=?",
            (status, json.dumps(response) if response is not None else None,
             utcnow() if status in ("executed", "failed") else None, aid))
        self.db.commit()

    def queued(self):
        return self.db.execute(
            "SELECT * FROM actions WHERE status='queued' ORDER BY id DESC").fetchall()

    def action(self, aid):
        return self.db.execute("SELECT * FROM actions WHERE id=?", (aid,)).fetchone()

    def recent_actions(self, n=50):
        return self.db.execute("SELECT * FROM actions ORDER BY id DESC LIMIT ?", (n,)).fetchall()

    def drive_histogram(self, days=14):
        cut = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).isoformat()
        rows = self.db.execute(
            "SELECT drive, COUNT(*) n FROM actions WHERE created_at > ? AND status='executed'"
            " GROUP BY drive", (cut,)).fetchall()
        return {r["drive"]: r["n"] for r in rows}

    # ---- caps ------------------------------------------------------------
    def cap_used(self, day, kind):
        r = self.db.execute("SELECT used FROM caps WHERE day_utc=? AND kind=?",
                            (day, kind)).fetchone()
        return r["used"] if r else 0

    def cap_bump(self, day, kind):
        self.db.execute(
            "INSERT INTO caps (day_utc,kind,used) VALUES (?,?,1)"
            " ON CONFLICT(day_utc,kind) DO UPDATE SET used=used+1", (day, kind))
        self.db.commit()

    # ---- heads -----------------------------------------------------------
    def save_head(self, chain, head, through_id):
        self.db.execute("INSERT INTO heads (ts,chain,head,through_id) VALUES (?,?,?,?)",
                        (utcnow(), chain, head, through_id))
        self.db.commit()

    def last_head(self, chain):
        return self.db.execute(
            "SELECT * FROM heads WHERE chain=? ORDER BY rowid DESC LIMIT 1", (chain,)).fetchone()

    # ---- messages --------------------------------------------------------
    def say(self, role, content, meta=None, done=True):
        cur = self.db.execute(
            "INSERT INTO messages (ts,role,content,meta,done) VALUES (?,?,?,?,?)",
            (utcnow(), role, content, json.dumps(meta) if meta else None, 1 if done else 0))
        self.db.commit()
        return cur.lastrowid

    def append_delta(self, mid, text):
        self.db.execute("UPDATE messages SET content = content || ? WHERE id=?", (text, mid))
        self.db.commit()

    def finish(self, mid, meta=None):
        if meta is not None:
            self.db.execute("UPDATE messages SET done=1, meta=? WHERE id=?",
                            (json.dumps(meta), mid))
        else:
            self.db.execute("UPDATE messages SET done=1 WHERE id=?", (mid,))
        self.db.commit()

    def messages(self, after=0, limit=400, include_archived=False):
        """The chat view. Archived rows are hidden here and only here.

        `tail()` below still sees them, because that is what feeds the model's
        recent-turn window, and clearing the screen is not meant to give the
        agent amnesia."""
        q = "SELECT * FROM messages WHERE id > ?"
        if not include_archived:
            q += " AND archived_at IS NULL"
        return self.db.execute(q + " ORDER BY id LIMIT ?", (after, limit)).fetchall()

    def tail(self, n=40):
        rows = self.db.execute(
            "SELECT * FROM messages ORDER BY id DESC LIMIT ?", (n,)).fetchall()
        return list(reversed(rows))

    def pending_generation(self):
        return self.db.execute(
            "SELECT * FROM messages WHERE done=0 AND archived_at IS NULL"
            " ORDER BY id DESC LIMIT 1").fetchone()

    # ---- notes / cursor --------------------------------------------------
    def note(self, key, value=None):
        if value is None:
            r = self.db.execute("SELECT value FROM notes WHERE key=?", (key,)).fetchone()
            return r["value"] if r else None
        self.db.execute(
            "INSERT INTO notes (key,value,updated_at) VALUES (?,?,?)"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, str(value), utcnow()))
        self.db.commit()

    def mark_seen(self, kind, ref):
        self.db.execute("INSERT OR IGNORE INTO seen (kind,ref,ts) VALUES (?,?,?)",
                        (kind, str(ref), utcnow()))
        self.db.commit()

    def is_seen(self, kind, ref):
        return self.db.execute("SELECT 1 FROM seen WHERE kind=? AND ref=?",
                               (kind, str(ref))).fetchone() is not None


INSTR_SCHEMA = '\nCREATE TABLE IF NOT EXISTS instructions (\n  id INTEGER PRIMARY KEY, ts TEXT, text TEXT NOT NULL,\n  cycles_left INTEGER NOT NULL DEFAULT 1,\n  cycles_total INTEGER NOT NULL DEFAULT 1,\n  spent_at TEXT, source TEXT);\n'


# --------------------------------------------------------------- instructions
# What you say in chat, made available to the cycle. Bounded by a cycle count
# rather than a clock: a wake is the unit of attention here, so it is the unit
# an instruction should be spent in.

def add_instruction(state, text, cycles=1, source="chat"):
    text = " ".join((text or "").split())[:1200]
    if len(text) < 4:
        return None
    state.db.executescript(INSTR_SCHEMA)
    cur = state.db.execute(
        "INSERT INTO instructions (ts,text,cycles_left,cycles_total,source)"
        " VALUES (?,?,?,?,?)", (utcnow(), text, max(1, int(cycles)),
                               max(1, int(cycles)), source))
    state.db.commit()
    return cur.lastrowid


def live_instructions(state):
    try:
        return state.db.execute(
            "SELECT * FROM instructions WHERE cycles_left > 0 ORDER BY id"
        ).fetchall()
    except Exception:
        return []


def spend_instructions(state):
    """Charge every live instruction one cycle.

    Called once the composer has ANSWERED, not when the cycle reads them.
    Still deliberately not "when the cycle succeeds": a cycle whose proposal
    the gate refuses has spent the attention, and an instruction that survives
    every refusal would steer the agent long after you stopped watching. But
    a busy composer lock or a failed completion is not the model declining to
    do the thing — it never saw it — and used to burn the instruction anyway.
    """
    rows = live_instructions(state)
    if not rows:
        return []
    state.db.execute(
        "UPDATE instructions SET cycles_left = cycles_left - 1,"
        " spent_at = CASE WHEN cycles_left - 1 <= 0 THEN ? ELSE spent_at END"
        " WHERE cycles_left > 0", (utcnow(),))
    state.db.commit()
    return rows


def set_instruction_cycles(state, iid, cycles):
    state.db.execute(
        "UPDATE instructions SET cycles_left=?, cycles_total=MAX(cycles_total,?),"
        " spent_at=NULL WHERE id=?", (max(0, int(cycles)), max(1, int(cycles)), iid))
    state.db.commit()


def clear_instructions(state):
    cur = state.db.execute(
        "UPDATE instructions SET cycles_left=0, spent_at=? WHERE cycles_left > 0",
        (utcnow(),))
    state.db.commit()
    return cur.rowcount


def recent_instructions(state, n=25):
    try:
        return state.db.execute(
            "SELECT * FROM instructions ORDER BY id DESC LIMIT ?", (n,)).fetchall()
    except Exception:
        return []
