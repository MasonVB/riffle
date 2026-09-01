"""The goal table, and the rules about who may move it.

Goals moved out of config.yaml and into the database because the agent can now
change its own weights, and the agent deliberately cannot write /opt/riffle.
config.yaml seeds this table once, on first run, and is never written back.

The boundary that matters is unchanged: WEIGHTS are negotiable and live here;
CAPS, AUTONOMY, the model and the base URL are not and stay in the file, which
only you can edit, over ssh.

Three protections on the agent's own hand:

  LOCK        a locked drive is yours alone. `earn` ships locked, because a
              drive that can raise its own priority for money is the one thing
              in here worth being paranoid about.
  BOUNDS      a change is at most `max_delta` in one step, at most
              `max_delta_per_day` in a UTC day, and the result is clamped
              into [min_weight, max_weight]. It can drift; it cannot lunge.
  REASON      every change carries one, is attributed to who made it, and is
              kept forever. You can read the whole history of what it decided
              it wanted and why.

Weights are NORMALISED at selection time, so raising everything is a no-op and
only relative priority is real.
"""
import datetime as dt
import json

from agent.state import utcnow

DEFAULT_POLICY = {
    "agent_may_adjust": True,
    "agent_may_add": False,       # adding a goal is a queued proposal, not an act
    "min_weight": 0.02,
    "max_weight": 0.50,
    "max_delta": 0.05,            # one change
    "max_delta_per_day": 0.10,    # summed across all changes to one drive
}

SEED_META = {
    "understand": ("read, follow a thread, ask a real question", None, None),
    "contribute": ("checkable artifacts, tools, corrections", None, None),
    "witness": ("the daily attest ritual and cross-witnessing", None, None),
    "answer": ("reply to citizens who engaged with you", None, None),
    "deepen": ("add the next increment to the open project — read a source, "
               "draft a paragraph, or argue against yourself", None, None),
    "curate": ("vote and tag what you have actually read — the ranking is "
               "only as good as the citizens who mark it, and a vote is the "
               "only act that moves another citizen's karma", None, None),
    "greet": ("the porch: one line a day, nothing ranked. Say hello, "
              "congratulate, thank, disagree in plain words — the social room, "
              "not the record", None, None),
    # `build` and `sign` join the allow-list. Without them `earn` could only
    # ever propose a listing_submission, which needs an artifact it had no way
    # to make — so every earn cycle noop'd about having nothing to submit,
    # fourteen times, correctly. A drive whose only legal move requires a
    # thing it cannot produce is a drive that does nothing.
    "earn": ("take a row off the docket: read the listing, BUILD the check in "
             "the sandbox until it runs, then submit it. The artifact may be a "
             "post id, a hash or a URL — a post carrying the method and the "
             "output counts. Verifiable work a stranger can re-run",
             ["listing_submission", "build", "sign", "fetch"],
             ["vote", "flag", "tag"]),
}


class Rejected(Exception):
    pass


def policy(cfg):
    p = dict(DEFAULT_POLICY)
    p.update(cfg.get("goal_policy") or {})
    return p


def seed(state, cfg):
    """Populate the table from config.yaml the first time only."""
    if state.db.execute("SELECT COUNT(*) c FROM drives").fetchone()["c"]:
        return
    forb = (cfg.get("constraints") or {}).get("earn_may_not_select", [])
    for name, w in cfg["drives"].items():
        desc, sel, fbd = SEED_META.get(name, ("", None, None))
        if name == "earn":
            fbd = forb or fbd
        state.db.execute(
            "INSERT INTO drives (name,weight,locked,description,selects,forbids,"
            "created_at,created_by) VALUES (?,?,?,?,?,?,?,?)",
            (name, float(w), 1 if name == "earn" else 0, desc,
             json.dumps(sel) if sel else None, json.dumps(fbd) if fbd else None,
             utcnow(), "seed"))
    state.db.commit()
    state.log("goal table seeded from config.yaml; 'earn' is locked by default")


def all_drives(state):
    return state.db.execute("SELECT * FROM drives ORDER BY weight DESC, name").fetchall()


def weights(state):
    return {r["name"]: r["weight"] for r in all_drives(state)}


def normalised(state):
    w = weights(state)
    tot = sum(w.values()) or 1.0
    return {k: v / tot for k, v in w.items()}


def forbids(state, name):
    r = state.db.execute("SELECT forbids FROM drives WHERE name=?", (name,)).fetchone()
    return json.loads(r["forbids"]) if r and r["forbids"] else []


def selects(state, name):
    r = state.db.execute("SELECT selects FROM drives WHERE name=?", (name,)).fetchone()
    return json.loads(r["selects"]) if r and r["selects"] else None


def _record(state, name, field, old, new, actor, reason):
    state.db.execute(
        "INSERT INTO drive_changes (ts,name,field,old,new,actor,reason)"
        " VALUES (?,?,?,?,?,?,?)",
        (utcnow(), name, field, str(old), str(new), actor, reason))
    state.db.commit()


def _spent_today(state, name):
    day = utcnow()[:10]
    rows = state.db.execute(
        "SELECT old,new FROM drive_changes WHERE name=? AND field='weight' AND ts LIKE ?",
        (name, day + "%")).fetchall()
    return sum(abs(float(r["new"]) - float(r["old"])) for r in rows)


def set_weight(state, cfg, name, new_weight, actor, reason):
    """actor is 'you' or 'agent'. Bounds apply only to the agent."""
    row = state.db.execute("SELECT * FROM drives WHERE name=?", (name,)).fetchone()
    if not row:
        raise Rejected(f"no goal named {name!r}")
    try:
        new = round(float(new_weight), 4)
    except (TypeError, ValueError):
        raise Rejected("weight must be a number")
    old = row["weight"]

    if actor == "agent":
        p = policy(cfg)
        if not p["agent_may_adjust"]:
            raise Rejected("agent weight adjustment is disabled in config.yaml")
        if row["locked"]:
            raise Rejected(f"'{name}' is locked. Only the operator may change it.")
        if not (len(reason or "") >= 20):
            raise Rejected("a weight change needs a reason of at least 20 characters")
        if not (p["min_weight"] <= new <= p["max_weight"]):
            raise Rejected(f"weight must stay within "
                           f"[{p['min_weight']}, {p['max_weight']}]; got {new}")
        if abs(new - old) > p["max_delta"] + 1e-9:
            raise Rejected(f"one step may move a weight by at most {p['max_delta']}; "
                           f"you asked for {abs(new - old):.4f}")
        if _spent_today(state, name) + abs(new - old) > p["max_delta_per_day"] + 1e-9:
            raise Rejected(f"'{name}' has already moved "
                           f"{_spent_today(state, name):.4f} today; the daily budget is "
                           f"{p['max_delta_per_day']}")

    state.db.execute("UPDATE drives SET weight=? WHERE name=?", (new, name))
    state.db.commit()
    _record(state, name, "weight", old, new, actor, reason or "")
    return old, new


def set_lock(state, name, locked, actor="you", reason=""):
    if actor != "you":
        raise Rejected("only the operator may lock or unlock a goal")
    row = state.db.execute("SELECT locked FROM drives WHERE name=?", (name,)).fetchone()
    if not row:
        raise Rejected(f"no goal named {name!r}")
    state.db.execute("UPDATE drives SET locked=? WHERE name=?", (1 if locked else 0, name))
    state.db.commit()
    _record(state, name, "locked", row["locked"], 1 if locked else 0, actor, reason)


def add(state, cfg, name, weight, description, actor, reason, forbids_list=None):
    name = (name or "").strip().lower()
    if not name.replace("_", "").replace("-", "").isalnum() or not (2 <= len(name) <= 24):
        raise Rejected("goal name must be 2-24 chars of [a-z0-9_-]")
    if state.db.execute("SELECT 1 FROM drives WHERE name=?", (name,)).fetchone():
        raise Rejected(f"'{name}' already exists")
    if state.db.execute("SELECT COUNT(*) c FROM drives").fetchone()["c"] >= 16:
        raise Rejected("16 goals is enough; a desire table nobody reads is not a desire table")
    p = policy(cfg)
    w = round(float(weight), 4)
    if actor == "agent":
        if not p["agent_may_add"]:
            raise Rejected("the agent proposes new goals; it does not add them. "
                           "This one goes to the queue.")
        if not (p["min_weight"] <= w <= p["max_weight"]):
            raise Rejected(f"weight must be within [{p['min_weight']}, {p['max_weight']}]")
    state.db.execute(
        "INSERT INTO drives (name,weight,locked,description,selects,forbids,created_at,"
        "created_by) VALUES (?,?,0,?,NULL,?,?,?)",
        (name, w, (description or "").strip()[:300],
         json.dumps(forbids_list) if forbids_list else None, utcnow(), actor))
    state.db.commit()
    _record(state, name, "created", "", w, actor, reason or "")
    return name


def remove(state, name, actor="you", reason=""):
    if actor != "you":
        raise Rejected("only the operator may remove a goal")
    row = state.db.execute("SELECT * FROM drives WHERE name=?", (name,)).fetchone()
    if not row:
        raise Rejected(f"no goal named {name!r}")
    if name == "witness":
        raise Rejected("'witness' is the one obligation that is not a desire. "
                       "Set its weight to the floor if you must, but it stays.")
    state.db.execute("DELETE FROM drives WHERE name=?", (name,))
    state.db.commit()
    _record(state, name, "removed", row["weight"], "", actor, reason)


def history(state, n=60, name=None):
    if name:
        return state.db.execute(
            "SELECT * FROM drive_changes WHERE name=? ORDER BY id DESC LIMIT ?",
            (name, n)).fetchall()
    return state.db.execute(
        "SELECT * FROM drive_changes ORDER BY id DESC LIMIT ?", (n,)).fetchall()


def firing(state, days=14):
    """What actually fired, so you can compare intent against behaviour."""
    cut = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).isoformat()
    rows = state.db.execute(
        "SELECT drive, COUNT(*) n FROM actions WHERE created_at > ?"
        " AND status IN ('executed','queued','approved') GROUP BY drive", (cut,)).fetchall()
    return {r["drive"]: r["n"] for r in rows}
