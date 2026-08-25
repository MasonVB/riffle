#!/usr/bin/env python3
"""Post once, then work for a day.

    sudo cp project_install.py agent_project.py /opt/riffle/
    sudo mv /opt/riffle/agent_project.py /opt/riffle/agent/project.py
    sudo python3 /opt/riffle/project_install.py
    sudo systemctl restart riffle-dash

WHAT CHANGES

  post cooldown   after a post lands, posting is illegal for 24 hours
  readiness bar   even after the cooldown, a post is refused unless the open
                  project has enough behind it: notes, more than one source,
                  a draft, and an objection to its own argument
  deepen drive    a new goal, weighted up while the cooldown runs, whose only
                  job is adding the next increment to the project
  three actions   open_project, project_note, close_project

WHY THE READINESS BAR MATTERS MORE THAN THE COOLDOWN

A cooldown on its own just changes the rhythm of thin posts from hourly to
daily. What makes the waiting count is that the post has to come out of
something. Requiring an objection is the specific part worth keeping: it is
the one note kind that cannot be produced by restating the thesis, so it forces
at least one pass of adversarial thought before anything is published.

TUNING, in config.yaml under `projects:`

  cooldown_hours   24
  min_notes        6      raise if posts are still thin
  min_sources      2      raise to force more reading
  min_objections   1      the load-bearing one
  cooldown_focus   3.0    how far `deepen` is weighted up during cooldown

Backups written as .bak-project.
"""
import json
import os
import shutil
import sys

RIFFLE = "/opt/riffle"
CYCLE = f"{RIFFLE}/agent/cycle.py"
DRIVES = f"{RIFFLE}/agent/drives.py"
GOALS = f"{RIFFLE}/agent/goals.py"
CORTEX = f"{RIFFLE}/agent/cortex.py"
CFG = f"{RIFFLE}/config.yaml"
SCHEMA_JSON = f"{RIFFLE}/proposal_schema.json"

CONFIG_BLOCK = """
# --- working between posts ------------------------------------------------
# After a post lands, posting is closed for cooldown_hours and the `deepen`
# drive is weighted up. When it reopens, a post is still refused unless the
# open project clears the bar below. The objection requirement is the one that
# does the work: it cannot be satisfied by restating the thesis.
projects:
  cooldown_hours: 24
  min_notes: 6
  min_sources: 2
  min_drafts: 1
  min_objections: 1
  cooldown_focus: 3.0
"""

NEW_PAYLOADS = {
    "open_project": {"type": "object", "properties": {
        "title": {"type": "string"}, "question": {"type": "string"}},
        "required": ["title", "question"], "additionalProperties": False},
    "project_note": {"type": "object", "properties": {
        "kind": {"type": "string",
                 "enum": ["observation", "source", "draft", "objection",
                          "correction"]},
        "text": {"type": "string"},
        "source": {"type": ["string", "null"]}},
        "required": ["kind", "text"], "additionalProperties": False},
    "close_project": {"type": "object", "properties": {
        "reason": {"type": "string"}},
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
    if not os.path.exists(f"{path}.bak-project"):
        shutil.copy(path, f"{path}.bak-project")
    open(path, "w").write(s.replace(old, new, 1))
    print(f"  patched: {label}")
    return True


def main():
    if not os.path.exists(f"{RIFFLE}/agent/project.py"):
        sys.exit("  agent/project.py is missing — copy it in first.")

    # ---- config -----------------------------------------------------------
    cfg = open(CFG).read()
    if "\nprojects:" not in cfg:
        shutil.copy(CFG, f"{CFG}.bak-project")
        open(CFG, "w").write(cfg.rstrip() + "\n" + CONFIG_BLOCK)
        print("  appended projects block to config.yaml")
    else:
        print("  already present: projects block")

    # ---- constrained decoding schema --------------------------------------
    if os.path.exists(SCHEMA_JSON):
        sch = json.load(open(SCHEMA_JSON))
        have = {b["properties"]["action"]["const"] for b in sch["oneOf"]}
        added = 0
        for name, payload in NEW_PAYLOADS.items():
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
            shutil.copy(SCHEMA_JSON, f"{SCHEMA_JSON}.bak-project")
            json.dump(sch, open(SCHEMA_JSON, "w"), indent=1)
            print(f"  added {added} action(s) to proposal_schema.json "
                  f"({len(sch['oneOf'])} branches, "
                  f"{len(json.dumps(sch))} bytes)")
        else:
            print("  already present: project actions in the schema")
    else:
        print("  NOTE: proposal_schema.json not found; constrained decoding is\n"
              "        presumably off, so nothing to update there.")

    # ---- gate -------------------------------------------------------------
    patch(DRIVES,
          '''    "remember": (["text"], ["pinned"],''',
          '''    "open_project": (["title", "question"], [],
                     lambda p: {"title": _s(p["title"], 8, 160, "title"),
                                "question": _s(p["question"], 20, 600, "question")}),
    "project_note": (["kind", "text"], ["source"],
                     lambda p: {"kind": _enum(p["kind"],
                                              ("observation", "source", "draft",
                                               "objection", "correction")),
                                "text": _s(p["text"], 20, 1200, "text"),
                                "source": (_s(p["source"], 1, 300, "source")
                                           if p.get("source") else None)}),
    "close_project": (["reason"], [],
                      lambda p: {"reason": _s(p["reason"], 20, 600, "reason")}),
    "remember": (["text"], ["pinned"],''',
          "project actions in the gate schema", marker='"open_project": (')

    # ---- cycle ------------------------------------------------------------
    patch(CYCLE,
          "from agent import chat, cortex, drives, goals, memory, notify",
          "from agent import chat, cortex, drives, goals, memory, notify, project",
          "cycle imports project", marker="notify, project")

    patch(CYCLE, "    goals.seed(state, cfg)",
          '''    goals.seed(state, cfg)
    project.ensure(state)
    # `deepen` is a goal like any other, seeded once, editable on /goals.
    if not state.db.execute("SELECT 1 FROM drives WHERE name='deepen'").fetchone():
        state.db.execute(
            "INSERT INTO drives (name,weight,locked,description,created_at,created_by)"
            " VALUES ('deepen',0.25,0,?,?,'seed')",
            ("add the next increment to the open project — read a source, draft "
             "a paragraph, or argue against yourself", state.note("x") or "seed"))
        state.db.commit()
        state.log("seeded the 'deepen' goal at 0.25")''',
          "seed the deepen goal", marker="seeded the 'deepen' goal")

    patch(CYCLE,
          '''    drive = drives.pick_drive(cfg, available, weights_override=live_weights) or "understand"''',
          '''    cooling, _until, hours_left = project.in_cooldown(state)
    if project.active(state):
        available.add("deepen")
    # While posting is closed there is one useful thing to do, so weight it that
    # way rather than relying on the model to notice.
    if cooling and "deepen" in available:
        live_weights = dict(live_weights)
        focus = float((cfg.get("projects") or {}).get("cooldown_focus", 3.0))
        live_weights["deepen"] = live_weights.get("deepen", 0.25) * focus
    drive = drives.pick_drive(cfg, available, weights_override=live_weights) or "understand"''',
          "deepen becomes available and is weighted up during cooldown",
          marker="cooldown_focus")

    patch(CYCLE,
          '''    recalled = memory.recall(state,''',
          '''    parts.append(project.as_context(state, cfg,
                                    budget=int(budget * 0.45)))
    recalled = memory.recall(state,''',
          "project block enters the cycle prompt", marker="project.as_context(state, cfg")

    # post gating: cooldown + readiness, checked before caps
    patch(CYCLE,
          '''    ok, why = drives.caps_ok(state, day, kind, cfg)''',
          '''    if kind == "post":
        cooling, until, left = project.in_cooldown(state)
        if cooling:
            msg = (f"posting is closed for another {left:.1f}h after your last "
                   f"post. Work the project instead.")
            state.propose(cid, kind, drive, payload, rationale, "blocked")
            log(f"post refused: {msg}", level="info", drive=drive)
            state.say("report", f"Cycle {cid} \\u00b7 I wanted to post and could "
                                f"not: {msg}", {"drive": drive})
            state.end_cycle(cid, "cooldown")
            return 0
        rdy, why_r = project.ready(state, cfg)
        if not rdy:
            state.propose(cid, kind, drive, payload, rationale, "blocked")
            log(f"post refused: {why_r}", level="info", drive=drive)
            state.say("report", f"Cycle {cid} \\u00b7 I wanted to post and could "
                                f"not: {why_r}", {"drive": drive})
            state.end_cycle(cid, "not-ready")
            return 0

    ok, why = drives.caps_ok(state, day, kind, cfg)''',
          "post is gated by cooldown and readiness", marker="posting is closed for another")

    # reflexive handling for the three project actions
    patch(CYCLE,
          '''    if kind in ("adjust_drive", "add_goal", "remember"):''',
          '''    if kind in ("open_project", "project_note", "close_project"):
        return apply_project(state, cfg, cid, kind, payload, drive, rationale)

    if kind in ("adjust_drive", "add_goal", "remember"):''',
          "cycle routes project actions", marker="apply_project(state, cfg, cid")

    patch(CYCLE, "def apply_reflexive(state, cfg, cid, kind, p, drive, rationale):",
          '''def apply_project(state, cfg, cid, kind, p, drive, rationale):
    """Work on the thing between posts. Never touches the registry."""
    try:
        if kind == "open_project":
            pid = project.open_project(state, p["title"], p["question"])
            state.log(f"opened project {pid}: {p['title']}", drive=drive)
            state.say("report", f"Cycle {cid} \\u00b7 opened a project: "
                                f"{p['title']}\\n{p['question']}", {"drive": drive})
            state.end_cycle(cid, "project-opened")
            return 0
        proj = project.active(state)
        if not proj:
            state.log(f"{kind} with no open project", level="warn", drive=drive)
            state.end_cycle(cid, "no-project")
            return 0
        if kind == "project_note":
            nid = project.add_note(state, proj["id"], cid, p["kind"], p["text"],
                                   p.get("source"))
            s = project.stats(state, proj["id"])
            state.log(f"note {nid} ({p['kind']}) on '{proj['title']}' — "
                      f"now {s['notes']} notes from {s['sources']} sources",
                      drive=drive)
            state.say("report", f"Cycle {cid} \\u00b7 {p['kind']} on "
                                f"'{proj['title']}' ({s['notes']} notes, "
                                f"{s['sources']} sources): {p['text'][:300]}",
                      {"drive": drive})
            state.end_cycle(cid, "note-added")
            return 0
        if kind == "close_project":
            project.close_project(state, proj["id"], "abandoned")
            state.log(f"closed project {proj['id']}: {p['reason'][:120]}", drive=drive)
            state.say("report", f"Cycle {cid} \\u00b7 closed '{proj['title']}'. "
                                f"{p['reason']}", {"drive": drive})
            state.end_cycle(cid, "project-closed")
            return 0
    except ValueError as e:
        state.log(f"{kind} refused: {e}", level="warn", drive=drive)
        state.say("error", f"Cycle {cid} \\u00b7 {kind} refused: {e}")
        state.end_cycle(cid, "project-refused", str(e)[:300])
        return 0
    return 0


def apply_reflexive(state, cfg, cid, kind, p, drive, rationale):''',
          "apply_project handler", marker="def apply_project(")

    # start the cooldown when a post actually lands
    patch(CYCLE,
          '''        state.cap_bump(day, kind)
        if kind in ("comment", "vote", "tag", "flag"):''',
          '''        state.cap_bump(day, kind)
        if kind == "post":
            until = project.start_cooldown(
                state, int((cfg.get("projects") or {}).get("cooldown_hours", 24)))
            proj = project.active(state)
            if proj:
                project.close_project(state, proj["id"], "posted", aid)
            log(f"posted; posting closed until {until:%Y-%m-%d %H:%M}Z",
                drive=drive)
        if kind in ("comment", "vote", "tag", "flag"):''',
          "a post starts the cooldown and closes the project",
          marker="posting closed until")

    # ---- the contract the model reads -------------------------------------
    patch(CORTEX, '''  remember            {"text": <=600 chars, "pinned": bool}''',
          '''  remember            {"text": <=600 chars, "pinned": bool}
  open_project        {"title": string, "question": string}
  project_note        {"kind": "observation"|"source"|"draft"|"objection"
                                |"correction", "text": string, "source": string|null}
  close_project       {"reason": string}

A POST COMES OUT OF A PROJECT, not out of one cycle's thinking. You wake with
about two minutes; nothing worth a whole day's post can be built in that. So
keep one question open and add to it: read a source and note what it said,
draft a paragraph, or find the strongest objection to your own argument. The
project block above shows what you have.

After you post, posting is closed for a day. That is not a punishment. It is
the time in which the next post gets built.

A note that restates something already in the project is refused. Add what is
not there yet.''',
          "output contract explains projects", marker="A POST COMES OUT OF A PROJECT")

    # ---- goals page description ------------------------------------------
    patch(GOALS, '''    "earn": ("listings only''',
          '''    "deepen": ("add the next increment to the open project — read a source, "
               "draft a paragraph, or argue against yourself", None, None),
    "earn": ("listings only''',
          "deepen described on the goals page", marker='"deepen": (')

    import ast
    for f in (CYCLE, DRIVES, GOALS, CORTEX, f"{RIFFLE}/agent/project.py"):
        ast.parse(open(f).read())
    print("\n  all modules parse.")
    print("""
  Next:
    sudo systemctl restart riffle-dash
    sudo systemctl start riffle-cycle.service

  Watch for: an open_project proposal within a cycle or two, then notes
  accumulating. Check progress with

    sudo sqlite3 -header -column /var/lib/riffle/state.sqlite \\
      "SELECT kind, substr(text,1,70), source FROM project_notes ORDER BY id;"
""")


if __name__ == "__main__":
    main()
