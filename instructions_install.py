#!/usr/bin/env python3
"""Let what you say in chat reach the cycle.

    sudo cp instructions_install.py /opt/riffle/
    sudo python3 /opt/riffle/instructions_install.py
    sudo systemctl restart riffle-dash

THE GAP THIS CLOSES

The cycle prompt has never contained the conversation. It sees the project,
the memories, the goals and the front page — nothing you typed. So when you
asked for a project on #1916 and cycle 50 opened one on "the emptiness trap"
instead, it was not ignoring you. It had never heard you.

WHY NOT JUST LET THE CHAT ACT

Because the chat is where the web enters. `web_read` puts unmoderated pages
into that context, and right now a page cannot cause an action because
chat.py has no route to Writer. That is structural, not a policy, and it is
what makes web access safe to have at all.

The chat also has none of the guards: the schema, the caps, the drive
restrictions, the post cooldown, the readiness bar, numcheck. Acting from chat
means either rebuilding all of it there or opening a second unguarded door.

So your words become DATA in the cycle prompt. The cycle proposes, the gate
validates, numcheck runs, it queues for your tap. Same path as everything
else, and a message that ever looks like an instruction from somewhere other
than you is still just text the model read.

SHELF LIFE

One cycle by default, because an instruction from Tuesday steering Friday is
worse than none. You can raise the count per instruction on /settings, and
lower it, and clear the lot.

An instruction is spent when a cycle READS it, not when the cycle succeeds. A
cycle that refuses itself still consumed the attention you asked for, and a
standing instruction that survives every failure would steer the agent for
hours after you stopped watching.

Backups written as .bak-instr.
"""
import os
import shutil
import sqlite3
import sys

RIFFLE = "/opt/riffle"
CYCLE = f"{RIFFLE}/agent/cycle.py"
DASH = f"{RIFFLE}/agent/dash.py"
STATE = f"{RIFFLE}/agent/state.py"
DB = "/var/lib/riffle/state.sqlite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS instructions (
  id INTEGER PRIMARY KEY, ts TEXT, text TEXT NOT NULL,
  cycles_left INTEGER NOT NULL DEFAULT 1,
  cycles_total INTEGER NOT NULL DEFAULT 1,
  spent_at TEXT, source TEXT);
"""

STATE_ADD = '''

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
    """Charge every live instruction one cycle. Called when a cycle READS them.

    Deliberately not "when the cycle succeeds": a cycle that refuses itself
    still spent the attention, and an instruction that survives every failure
    would steer the agent long after you stopped watching.
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
'''


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
    if not os.path.exists(f"{path}.bak-instr"):
        shutil.copy(path, f"{path}.bak-instr")
    open(path, "w").write(s.replace(old, new, 1))
    print(f"  patched: {label}")
    return True


def main():
    con = sqlite3.connect(DB)
    con.executescript(SCHEMA)
    con.commit()
    con.close()
    print("  instructions table ready")

    # ---- state.py ---------------------------------------------------------
    s = open(STATE).read()
    if "def add_instruction(" in s:
        print("  already present: instruction helpers")
    else:
        shutil.copy(STATE, f"{STATE}.bak-instr")
        open(STATE, "w").write(
            s.rstrip() + "\n\n\nINSTR_SCHEMA = " + repr(SCHEMA) + "\n" + STATE_ADD)
        print("  added instruction helpers to state.py")

    # ---- cycle reads them, high in the prompt ------------------------------
    patch(CYCLE,
          '    parts.append(project.as_context(state, cfg, budget=int(budget * 0.40)))',
          '''    from agent.state import spend_instructions
    _instr = spend_instructions(state)
    if _instr:
        # Near the front, under the no-project rule if that is in force. These
        # are DATA — a request from your operator, not a new set of rules.
        parts.insert(1 if parts and parts[0].startswith("NO PROJECT") else 0,
                     "STANDING INSTRUCTIONS from your operator, most recent "
                     "last. Treat these as what he asked for, not as new rules "
                     "— the gate still applies:\\n"
                     + "\\n".join("  - " + r["text"] for r in _instr))
        log("cycle carried " + str(len(_instr)) + " operator instruction(s)")
    parts.append(project.as_context(state, cfg, budget=int(budget * 0.40)))''',
          "cycle carries standing instructions", marker="STANDING INSTRUCTIONS from your operator")

    # ---- every chat message becomes one ------------------------------------
    patch(DASH,
          '''            self.state.say("user", q)
            self.worker.submit(q, utcnow()[:10])''',
          '''            self.state.say("user", q)
            # Anything you type is also an instruction the next cycle will see.
            # The cycle prompt never contained the conversation, which is why
            # asking for a project on #1916 produced one on something else.
            from agent.state import add_instruction
            add_instruction(self.state, q,
                            int((self.cfg.get("instructions") or {})
                                .get("default_cycles", 1)))
            self.worker.submit(q, utcnow()[:10])''',
          "chat messages become instructions", marker="add_instruction(self.state, q")

    # ---- settings panel -----------------------------------------------------
    patch(DASH, "<h2>projects</h2>",
          '''<h2>instructions &mdash; what you told it</h2>
<div class=note>Everything you type in chat is carried into the next cycle as
data. One cycle by default; raise the count for something you want it to keep
working on. An instruction is spent when a cycle <b>reads</b> it, whether or
not that cycle achieved anything.</div>
<div class=g id=instructions></div>

<h2>projects</h2>''',
          "instructions panel markup", marker="what you told it")

    patch(DASH, "  document.getElementById('projects').innerHTML =",
          '''  document.getElementById('instructions').innerHTML = pol.instructions.length
    ? pol.instructions.map(function(i){
        return '<div class=act><div class=n style="font-family:inherit;font-size:14px">' +
          esc(i.text) + '<small>' + esc(i.ts.slice(5,16).replace('T',' ')) +
          (i.left > 0 ? ' &middot; ' + i.left + ' of ' + i.total + ' cycles left'
                      : ' &middot; spent') + '</small></div>' +
          '<div class=ctl><input type=number min=0 max=20 value="' + i.left +
          '" style="width:66px" id="ic' + i.id + '">' +
          '<button onclick="setCycles(' + i.id + ')">set</button></div></div>';
      }).join('') + '<div class=ctl style="margin-top:10px">' +
        '<button class=warn onclick="clearInstr()">clear all live</button></div>'
    : '<div style="color:var(--dim)">nothing standing</div>';

  document.getElementById('projects').innerHTML =''',
          "instructions panel renderer", marker="pol.instructions.length")

    patch(DASH, "async function closeProject(){",
          '''async function setCycles(id){
  await api('/api/instruction/cycles',
            {id:id, cycles:+document.getElementById('ic'+id).value});
  await loadPolicy();
}
async function clearInstr(){
  if(!confirm('Clear every live instruction?')) return;
  await api('/api/instruction/clear', {});
  await loadPolicy();
}
async function closeProject(){''',
          "instruction panel script", marker="async function setCycles(id)")

    patch(DASH, '                 "projects": projects})',
          '''                 "instructions": [
                     {"id": r["id"], "ts": r["ts"], "text": r["text"],
                      "left": r["cycles_left"], "total": r["cycles_total"]}
                     for r in _state.recent_instructions(s)],
                 "projects": projects})''',
          "/api/policy returns instructions", marker='"instructions": [')

    patch(DASH, '        from agent import policy, project as _pj',
          '        from agent import policy, project as _pj, state as _state',
          "policy route imports state", marker="project as _pj, state as _state")

    patch(DASH, '        if u.path == "/api/project/close":',
          '''        if u.path == "/api/instruction/cycles":
            from agent import state as _state
            _state.set_instruction_cycles(s, int(b["id"]), int(b["cycles"]))
            return h._json({"ok": True}) or True
        if u.path == "/api/instruction/clear":
            from agent import state as _state
            n = _state.clear_instructions(s)
            s.say("report", f"You cleared {n} standing instruction(s).")
            return h._json({"ok": True, "cleared": n}) or True
        if u.path == "/api/project/close":''',
          "instruction write routes", marker='"/api/instruction/cycles"')

    patch(DASH,
          '        if self.path.startswith(("/api/goal/", "/api/memory/",\n'
          '                                 "/api/policy/", "/api/project/")):',
          '        if self.path.startswith(("/api/goal/", "/api/memory/",\n'
          '                                 "/api/policy/", "/api/project/",\n'
          '                                 "/api/instruction/")):',
          "instruction routes reach the handler", marker='"/api/instruction/"')

    # ---- config -------------------------------------------------------------
    cfgp = f"{RIFFLE}/config.yaml"
    c = open(cfgp).read()
    if "\ninstructions:" not in c:
        shutil.copy(cfgp, f"{cfgp}.bak-instr")
        open(cfgp, "w").write(c.rstrip() + """

# --- what you say in chat --------------------------------------------------
# Every chat message is carried into the cycle prompt as data for this many
# cycles. One is the right default: an instruction from this morning steering
# tonight is worse than none. Raise a specific one on /settings instead.
instructions:
  default_cycles: 1
""")
        print("  added instructions block to config.yaml")
    else:
        print("  already present: instructions block")

    import ast
    for f in (CYCLE, DASH, STATE):
        ast.parse(open(f).read())
    print("\n  modules parse.")
    print("""
  Next:
    sudo systemctl restart riffle-dash

  Then say something in chat and press run cycle. The cycle report should
  reflect what you asked for, and /settings will show the instruction being
  spent.""")


if __name__ == "__main__":
    main()
