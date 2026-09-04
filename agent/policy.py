"""What each action is allowed to do, and which drive may select it.

WHY THIS MOVED OUT OF config.yaml

The same reason the goal table did: the dashboard cannot write /opt/riffle,
and it should not be able to. So anything you need to change from a page has
to live in the database, with the file seeding it once.

The boundary that matters is unchanged. The AGENT still cannot reach any of
this — it has no route to the console, and nothing in the cycle writes these
tables. You can change them from a page you reach on your tailnet; it cannot.

THREE KNOBS

  MODE      per action: auto, queue, never.
  ONLY      per drive: if set, that drive may propose nothing else. Ships set
            on `earn` alone — money must not be able to select a social act.
  NEVER     per drive: actions that drive may not propose, whatever else it
            can.

`only` is a loaded gun. A drive with `only: [open_project]` can do exactly one
thing and will report every other cycle as a refusal, which is what happened
to `deepen` for three days. The page shows it in red for that reason.
"""
import json

from agent.state import utcnow

# noop is deliberately absent: declining to act is always permitted, and an
# agent that cannot decline will act.
ACTION_KINDS = [
    "post", "comment", "vote", "tag", "flag", "seal", "listing_submission",
    "porch", "knock", "attestation", "fetch", "build", "sign",
    "desk_put", "desk_clear",
    "library_put", "library_find", "library_read", "read_page", "ask_operator",
    "read_thread", "read_more", "request_cycle",
    "open_project", "project_note", "close_project",
    "adjust_drive", "add_goal", "remember",
]

# A new kind seeds as `queue` in ensure() below, so adding one here is enough:
# it appears on the settings page on the next load and waits for you until you
# say otherwise. No config.yaml edit, and the failure mode of forgetting is
# "waiting for you" rather than "already sent".

REACHES_THE_SQUARE = {"post", "comment", "vote", "tag", "flag",
                      "listing_submission", "seal", "porch", "attestation"}

# `build` runs code and `sign` produces a signature. Neither reaches the
# square by itself, and both are more consequential than anything that does.
# They are listed separately so the settings page can mark them rather than
# leaving them looking like the reflexive actions they sit beside.
CONSEQUENTIAL = {"build", "sign"}

MODES = ("auto", "queue", "never")

SCHEMA = """
CREATE TABLE IF NOT EXISTS action_policy (
  kind TEXT PRIMARY KEY, mode TEXT NOT NULL,
  updated_at TEXT, updated_by TEXT);

CREATE TABLE IF NOT EXISTS policy_changes (
  id INTEGER PRIMARY KEY, ts TEXT, kind TEXT, field TEXT,
  old TEXT, new TEXT, actor TEXT);
"""


def ensure(state, cfg):
    state.db.executescript(SCHEMA)
    have = {r["kind"] for r in state.db.execute("SELECT kind FROM action_policy")}
    seeded = 0
    file_modes = cfg.get("autonomy") or {}
    for k in ACTION_KINDS:
        if k in have:
            continue
        # A new action defaults to queue rather than auto. If I add one and
        # forget to set it, the failure should be "waiting for you", not
        # "already sent".
        mode = file_modes.get(k, "queue")
        if mode not in MODES:
            mode = "queue"
        state.db.execute(
            "INSERT INTO action_policy (kind,mode,updated_at,updated_by)"
            " VALUES (?,?,?,'seed')", (k, mode, utcnow()))
        seeded += 1
    if seeded:
        state.db.commit()
    return seeded


def modes(state):
    return {r["kind"]: r["mode"]
            for r in state.db.execute("SELECT kind, mode FROM action_policy")}


def set_mode(state, kind, mode, actor="you"):
    if kind not in ACTION_KINDS:
        raise ValueError(f"unknown action {kind!r}")
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    row = state.db.execute("SELECT mode FROM action_policy WHERE kind=?",
                           (kind,)).fetchone()
    old = row["mode"] if row else None
    state.db.execute(
        "INSERT INTO action_policy (kind,mode,updated_at,updated_by) VALUES (?,?,?,?)"
        " ON CONFLICT(kind) DO UPDATE SET mode=excluded.mode,"
        " updated_at=excluded.updated_at, updated_by=excluded.updated_by",
        (kind, mode, utcnow(), actor))
    state.db.execute(
        "INSERT INTO policy_changes (ts,kind,field,old,new,actor)"
        " VALUES (?,?,'mode',?,?,?)", (utcnow(), kind, old or "", mode, actor))
    state.db.commit()
    return old, mode


def restrictions(state):
    """{drive: {'only': [...], 'never': [...]}}"""
    out = {}
    for r in state.db.execute("SELECT name, selects, forbids FROM drives"):
        out[r["name"]] = {
            "only": json.loads(r["selects"]) if r["selects"] else [],
            "never": json.loads(r["forbids"]) if r["forbids"] else [],
        }
    return out


def set_restrictions(state, drive, only, never, actor="you"):
    only = [k for k in (only or []) if k in ACTION_KINDS]
    never = [k for k in (never or []) if k in ACTION_KINDS]
    overlap = set(only) & set(never)
    if overlap:
        raise ValueError(f"{sorted(overlap)} cannot be both the only thing "
                         f"allowed and forbidden")
    row = state.db.execute("SELECT selects, forbids FROM drives WHERE name=?",
                           (drive,)).fetchone()
    if not row:
        raise ValueError(f"no drive named {drive!r}")
    state.db.execute("UPDATE drives SET selects=?, forbids=? WHERE name=?",
                     (json.dumps(only) if only else None,
                      json.dumps(never) if never else None, drive))
    state.db.commit()   # the audit triggers on `drives` record the detail
    return only, never


def effective(state, cfg):
    """The autonomy map the gate should use: database over file."""
    m = dict(cfg.get("autonomy") or {})
    m.update(modes(state))
    return m


def history(state, n=30):
    return state.db.execute(
        "SELECT * FROM policy_changes ORDER BY id DESC LIMIT ?", (n,)).fetchall()
