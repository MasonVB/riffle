#!/usr/bin/env python3
"""Add hourly cycles, a manual run button, and Pushover notifications.

    sudo cp hourly_notify_install.py agent_notify.py /opt/riffle/
    sudo mv /opt/riffle/agent_notify.py /opt/riffle/agent/notify.py
    sudo python3 /opt/riffle/hourly_notify_install.py

FOUR CHANGES

1. HOURLY TIMER. 24 wakes a day at ~2.5 min each is about an hour of CPU.

2. QUEUE DEPTH GUARD — the change hourly cadence makes necessary. If the
   queue already holds `max_queued` proposals, the cycle still runs its
   witness pass and still notifies, but does not wake the composer. Without
   this, twenty-four cycles a day against an unread queue produces twenty-four
   near-identical cards and a pile you stop reading, which defeats the point
   of approving each one.

3. RUN BUTTON in the dashboard header. This does NOT breach the rule that a
   cycle cannot be triggered from conversation. The model has no way to reach
   localhost:8917 — its only outbound calls are the three read-only board
   lookups. A POST from your browser is you, not it.

4. PUSHOVER, inside your waking hours, deferred rather than dropped outside
   them. Witness alarms ignore the window: a chain that no longer hashes to
   what you witnessed is not a convenience notification.

Backups are written as .bak-notify next to each file.
"""
import os
import re
import shutil
import sqlite3
import subprocess
import sys

RIFFLE = "/opt/riffle"
CFG = f"{RIFFLE}/config.yaml"
CYCLE = f"{RIFFLE}/agent/cycle.py"
STATE = f"{RIFFLE}/agent/state.py"
DASH = f"{RIFFLE}/agent/dash.py"
DB = "/var/lib/riffle/state.sqlite"

CONFIG_BLOCK = """
# --- notifications --------------------------------------------------------
# Get both keys from pushover.net: user_key from your dashboard, api_token by
# registering an application. Leave enabled: false until both are filled in.
notify:
  enabled: false
  timezone: America/Los_Angeles
  dash_host: riffle          # used to build the tap-through link
  windows:
    weekday: [7, 22]         # Mon-Fri, local
    weekend: [10, 22]        # Sat-Sun, local
  user_key: ""
  api_token: ""

# With an hourly timer, an unread queue would otherwise grow all day. When the
# queue is this deep the cycle still witnesses and still notifies, but does not
# wake the composer.
max_queued: 5
"""

TIMER = """[Unit]
Description=wake riffle every hour

[Timer]
OnCalendar=hourly
RandomizedDelaySec=300
Persistent=true

[Install]
WantedBy=timers.target
"""


def backup(p, tag="bak-notify"):
    shutil.copy(p, f"{p}.{tag}")


def patch(path, old, new, label, marker, required=True):
    """`marker` must be text unique to the REPLACEMENT.

    The first version tested the leading characters of `new`, but several
    replacements begin by repeating their own anchor — so the check matched
    before anything had been applied and three patches were skipped in
    silence. An idempotency test has to look at what the change ADDS.
    """
    s = open(path).read()
    if marker in s:
        print(f"  already present: {label}")
        return False
    if old not in s:
        if required:
            sys.exit(f"  FAILED: anchor not found in {path} ({label}). Nothing changed.")
        print(f"  skipped (anchor absent): {label}")
        return False
    if not os.path.exists(f"{path}.bak-notify"):
        backup(path)
    open(path, "w").write(s.replace(old, new, 1))
    print(f"  patched: {label}")
    return True


def main():
    # --- 0. database column ------------------------------------------------
    con = sqlite3.connect(DB)
    cols = [r[1] for r in con.execute("PRAGMA table_info(actions)")]
    if "notified" not in cols:
        con.execute("ALTER TABLE actions ADD COLUMN notified INTEGER DEFAULT 0")
        con.commit()
        print("  added actions.notified column")
    else:
        print("  already present: actions.notified")
    con.close()

    # The ALTER above fixes an EXISTING database. The schema itself must also
    # carry the column, or a fresh install has no `notified` and every
    # announce_pending raises. Found by creating a clean database in test.
    patch(STATE,
          "  numcheck TEXT, executed_at TEXT, response TEXT);",
          "  numcheck TEXT, executed_at TEXT, response TEXT,\n"
          "  notified INTEGER DEFAULT 0);",
          "notified column in the schema itself",
          marker="notified INTEGER DEFAULT 0);")

    # --- 1. config ---------------------------------------------------------
    cfg = open(CFG).read()
    if "notify:" not in cfg:
        backup(CFG)
        open(CFG, "w").write(cfg.rstrip() + "\n" + CONFIG_BLOCK)
        print("  appended notify + max_queued to config.yaml")
    else:
        print("  already present: notify block")

    # --- 2. cycle.py -------------------------------------------------------
    patch(CYCLE,
          "from agent import chat, cortex, drives, goals, memory  # noqa: E402",
          "from agent import chat, cortex, drives, goals, memory, notify  # noqa: E402",
          "cycle imports notify",
          marker="goals, memory, notify")

    # queue depth guard, placed before the composer is woken
    patch(CYCLE,
          '    # --- think ---------------------------------------------------------------',
          '''    # Announce anything already waiting, including a backlog held overnight.
    notify.announce_pending(state, cfg, log)

    # With hourly wakes an unread queue would grow all day and stop being read.
    depth = len(state.queued())
    cap = int(cfg.get("max_queued", 5))
    if depth >= cap:
        log(f"queue holds {depth} unread proposal(s) (cap {cap}); witnessing only, "
            f"not waking the composer", drive=drive)
        state.say("report", f"Cycle {cid} \\u00b7 {depth} proposals are still waiting on "
                            f"you, so I did not write another one.", {"drive": drive})
        state.end_cycle(cid, "queue-full")
        return 0

    # --- think ---------------------------------------------------------------''',
          "queue depth guard + pending announcement",
          marker="not waking the composer")

    # notify on a fresh queue entry
    patch(CYCLE,
          '''        state.say("proposal", rationale,
                  {"kind": kind, "drive": drive, "action_id": aid, "status": "queued",
                   "payload": json.dumps(payload, indent=2)})''',
          '''        state.say("proposal", rationale,
                  {"kind": kind, "drive": drive, "action_id": aid, "status": "queued",
                   "payload": json.dumps(payload, indent=2)})
        notify.announce_pending(state, cfg, log)''',
          "notify when a proposal is queued",
          marker="notify.announce_pending(state, cfg, log)\n    # --- reflexive")

    # alarms bypass the window
    patch(CYCLE,
          '''                    log(f"ALARM on {name}: status={st} expect_matches={em} through={vt}. "''',
          '''                    notify.alarm(state, _CFG or {}, f"{name} chain: status={st}, "
                                 f"expect_matches={em}, through={vt}", log)
                    log(f"ALARM on {name}: status={st} expect_matches={em} through={vt}. "''',
          "witness alarms notify regardless of hour",
          marker="notify.alarm(state, _CFG", required=False)

    # do_witness has no cfg in scope; give it one via a module global
    patch(CYCLE, "HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))",
          "HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))\n"
          "_CFG = None  # set in main(); do_witness needs it for alarm notifications",
          "module-level _CFG",
          marker="_CFG = None  # set in main()")
    patch(CYCLE, "    cfg = load_config(a.config)\n    data = os.path.expanduser",
          "    cfg = load_config(a.config)\n    global _CFG\n    _CFG = cfg\n"
          "    data = os.path.expanduser",
          "main() publishes cfg for do_witness",
          marker="global _CFG")

    # --- 3. dash.py --------------------------------------------------------
    patch(DASH, "from agent import chat, goals, memory  # noqa: E402",
          "from agent import chat, goals, memory  # noqa: E402\n"
          "import subprocess  # noqa: E402\n"
          "import threading as _th  # noqa: E402",
          "dash imports subprocess",
          marker="import threading as _th")

    patch(DASH, '  <a class="pill link" href="/goals">goals</a>',
          '  <button id=runbtn class=pillbtn onclick="runCycle()">run cycle</button>\n'
          '  <a class="pill link" href="/goals">goals</a>',
          "run button in header",
          marker="id=runbtn")

    patch(DASH, ".pill.bad{color:var(--bad);border-color:var(--bad)}",
          ".pill.bad{color:var(--bad);border-color:var(--bad)}\n"
          ".pillbtn{font:inherit;font-size:11.5px;background:transparent;color:var(--sig);\n"
          "  border:1px solid var(--sig);border-radius:99px;padding:3px 11px;cursor:pointer}\n"
          ".pillbtn:disabled{opacity:.35;cursor:default}",
          "run button styling",
          marker=".pillbtn{")

    patch(DASH, "send.onclick = submit;",
          '''async function runCycle(){
  const b = document.getElementById('runbtn');
  b.disabled = true; b.textContent = 'running…';
  await fetch('/api/run-cycle', {method:'POST', headers:{'Content-Type':'application/json'},
                                 body:'{}'});
}
send.onclick = submit;''',
          "runCycle() in the page script",
          marker="async function runCycle()")

    patch(DASH,
          "    busy = d.generating; send.disabled = busy;",
          "    busy = d.generating; send.disabled = busy;\n"
          "    const rb = document.getElementById('runbtn');\n"
          "    rb.disabled = !!d.cycle_running;\n"
          "    rb.textContent = d.cycle_running ? 'cycle running…' : 'run cycle';",
          "run button reflects cycle state",
          marker="rb.textContent = d.cycle_running")

    patch(DASH,
          '''        if u.path == "/api/decide":''',
          '''        if u.path == "/api/run-cycle":
            return self._json(self.run_cycle())
        if u.path == "/api/decide":''',
          "run-cycle route",
          marker='u.path == "/api/run-cycle"')

    patch(DASH,
          '''    def decide(self, aid, verdict):''',
          '''    _cycle_lock = __import__("threading").Lock()
    _cycle_running = False

    def run_cycle(self):
        """Start a wake cycle out of band.

        Reachable only from this page, which is on your LAN behind
        IPAddressAllow. The model cannot call it: its outbound reach is the
        three read-only board lookups in chat.py and nothing else. A POST here
        is you pressing a button, not the agent deciding to act.
        """
        cls = type(self)
        with cls._cycle_lock:
            if cls._cycle_running:
                return {"error": "a cycle is already running"}
            cls._cycle_running = True

        def run():
            try:
                subprocess.run(
                    [sys.executable, "-m", "agent.cycle", "--config",
                     os.path.join("/opt/riffle", "config.yaml")],
                    cwd="/opt/riffle", timeout=2700,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception as e:
                self.state.say("error", f"manual cycle failed to run: {e}")
            finally:
                cls._cycle_running = False

        _th.Thread(target=run, daemon=True).start()
        self.state.log("you started a cycle from the dashboard")
        return {"ok": True}

    def decide(self, aid, verdict):''',
          "run_cycle handler",
          marker="def run_cycle(self):")

    patch(DASH,
          '''        return {"messages": out, "queued": len(s.queued()),''',
          '''        return {"messages": out, "queued": len(s.queued()),
                "cycle_running": type(self)._cycle_running,''',
          "expose cycle_running to the page",
          marker='"cycle_running": type(self)._cycle_running')

    # --- 4. timer ----------------------------------------------------------
    for p in (f"{RIFFLE}/systemd/riffle-cycle.timer",
              "/etc/systemd/system/riffle-cycle.timer"):
        if os.path.exists(p):
            if not os.path.exists(p + ".bak-notify"):
                backup(p)
            open(p, "w").write(TIMER)
            print(f"  rewrote {p} to hourly")

    import ast
    for f in (CYCLE, DASH, STATE, f"{RIFFLE}/agent/notify.py"):
        ast.parse(open(f).read())
    print("\n  all modules parse.")
    print("""
  Next:
    1. put your Pushover keys in /opt/riffle/config.yaml and set enabled: true
    2. sudo systemctl daemon-reload
    3. sudo systemctl restart riffle-dash riffle-cycle.timer
    4. systemctl list-timers riffle-cycle --no-pager""")


if __name__ == "__main__":
    main()
