#!/usr/bin/env python3
"""Telemetry, a log you can read and download, and three scrolling fixes.

    sudo cp telemetry_install.py agent_telemetry.py /opt/riffle/
    sudo mv /opt/riffle/agent_telemetry.py /opt/riffle/agent/telemetry.py
    sudo python3 /opt/riffle/telemetry_install.py
    sudo systemctl restart riffle-dash

TELEMETRY

  a sample a minute      temps, memory, disk, load, governor, service states,
                         composer health, and what the agent is mid-way
                         through. Kept 24 hours.
  a dump on every error  the above plus the recent journal, cycles, actions,
                         and the tail of three unit logs. Fires from
                         state.log() whenever level is error or alarm, so
                         nothing has to remember to call it.
  /settings              the last 400 entries in a scrollable window, dumps in
                         red, expandable.
  a download button      the whole 24 hours as JSONL, ready to paste here.

Four freezes in two days were unexplainable because nothing was recording. The
next one will have a last-sample-before-the-gap, which is the difference
between "memory was climbing" and "it died mid-stride at normal usage" —
software or hardware, which is the entire question.

THREE SCROLLING FIXES

1. On mobile the page scrolled past the composer and took the header away.
   The body was `height:100%` with the log as a flex child and no
   `min-height:0`, so the flex child refused to shrink, the body grew past the
   viewport, and the whole document scrolled behind a header that only looked
   fixed. Now `100dvh` — which accounts for the browser's collapsing address
   bar, where `100vh` does not — with the document itself unable to scroll and
   only the log doing so.

2. Long output inside a card jumped back to the top while you were reading it.
   The poll re-sends proposal cards every 2.5 seconds so their state can
   change, and render() rebuilt each one's innerHTML unconditionally — which
   throws away the scroll position of any <pre> inside. It now compares a
   signature of what it is about to draw against what is already there and
   leaves the DOM alone when nothing changed.

3. An autoscroll toggle, remembered between visits. Off means the view never
   moves on its own, which is what you want while reading something long as
   the agent keeps talking.

Backups written as .bak-tel.
"""
import os
import shutil
import sys

RIFFLE = "/opt/riffle"
DASH = f"{RIFFLE}/agent/dash.py"
STATE = f"{RIFFLE}/agent/state.py"
CYCLE = f"{RIFFLE}/agent/cycle.py"


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
    if not os.path.exists(f"{path}.bak-tel"):
        shutil.copy(path, f"{path}.bak-tel")
    open(path, "w").write(s.replace(old, new, 1))
    print(f"  patched: {label}")
    return True


LOG_CSS = """
#telbox{max-height:min(60vh,460px);overflow-y:auto;overscroll-behavior:contain;
  background:#0e100b;border:1px solid var(--line);border-radius:8px;padding:0}
.tel{border-bottom:1px solid var(--line);padding:7px 10px;font-size:12px;
  font-family:ui-monospace,Menlo,monospace;line-height:1.45;cursor:pointer}
.tel:last-child{border-bottom:0}
.tel.dump{border-left:3px solid var(--bad)}
.tel .t{color:var(--dim)}
.tel .k{color:var(--sig);text-transform:uppercase;letter-spacing:.06em;
  font-size:10.5px}
.tel.dump .k{color:var(--bad)}
.tel pre{display:none;white-space:pre-wrap;word-break:break-word;margin:7px 0 0;
  background:#12140f;border-radius:6px;padding:9px;font-size:11.5px;
  max-height:340px;overflow:auto;overscroll-behavior:contain}
.tel.open pre{display:block}
"""

LOG_HTML = """
<h2>log &mdash; the last 24 hours</h2>
<div class=note>A sample a minute; a full dump whenever an error or alarm is
written. Tap a row to expand it. Dumps are marked in red. Anything older than
24 hours is deleted, so this is for tracing something that just happened
rather than for keeping.</div>
<div class=ctl style="margin-bottom:9px">
  <a class=link href="/api/telemetry.jsonl" download>download the whole window</a>
  <button class=ghost onclick="loadTel()">refresh</button>
  <span class=tag id=telcount></span>
</div>
<div id=telbox></div>
"""

LOG_JS = """
async function loadTel(){
  const d = await (await fetch('/api/telemetry')).json();
  document.getElementById('telcount').textContent =
    d.entries.length + ' entries, ' + d.dumps + ' dump' + (d.dumps===1?'':'s');
  document.getElementById('telbox').innerHTML = d.entries.map(function(e){
    const m = e.summary || {};
    return '<div class="tel' + (e.kind==='dump'?' dump':'') +
      '" onclick="this.classList.toggle(\\'open\\')">' +
      '<span class=k>' + esc(e.kind) + '</span> ' +
      '<span class=t>' + esc(e.ts.slice(5,19).replace('T',' ')) + '</span> ' +
      esc(e.label) + ' &middot; ' + esc(m.line || '') +
      '<pre>' + esc(e.pretty) + '</pre></div>';
  }).join('') || '<div class=alarmempty>nothing recorded yet</div>';
}
"""

ROUTES = '''    if h.command == "GET" and u.path == "/api/telemetry":
        from agent import telemetry
        rows = telemetry.recent(s, 400)
        ent = []
        for r in rows:
            try:
                body = json.loads(r["payload"])
            except Exception:
                body = {}
            mem = body.get("mem") or {}
            cp = body.get("cpu") or {}
            tp = body.get("temps") or {}
            hot = max([v for v in tp.values() if isinstance(v, (int, float))],
                      default=None)
            line = (f"{mem.get('PctUsed', '?')}% mem, "
                    f"{mem.get('MemAvailable', '?')}MiB free, "
                    f"load {cp.get('load1', '?')}, "
                    f"{cp.get('mhz_avg', '?')}MHz"
                    + (f", {hot}\\u00b0C" if hot is not None else ""))
            ent.append({"id": r["id"], "ts": r["ts"], "kind": r["kind"],
                        "label": r["label"], "summary": {"line": line},
                        "pretty": json.dumps(body, indent=1, default=str)[:12000]})
        h._json({"entries": ent,
                 "dumps": sum(1 for e in ent if e["kind"] == "dump")})
        return True
    if h.command == "GET" and u.path == "/api/telemetry.jsonl":
        from agent import telemetry
        b = telemetry.as_jsonl(s, 24).encode()
        h.send_response(200)
        h.send_header("Content-Type", "application/x-ndjson")
        h.send_header("Content-Disposition",
                      'attachment; filename="riffle-telemetry.jsonl"')
        h.send_header("Content-Length", str(len(b)))
        h.end_headers()
        h.wfile.write(b)
        return True
'''

SAMPLER = '''    _tel_started = False

    @classmethod
    def start_telemetry(cls):
        """A sample a minute, and a prune each hour.

        In the dashboard because it is the only long-lived process. The cycle
        samples at its own start and end, which is what pairs a reading with
        the work that produced it.
        """
        if cls._tel_started:
            return
        cls._tel_started = True
        from agent import telemetry
        telemetry.install(cls.state, cls.cfg)

        def loop():
            import time as _t
            n = 0
            while True:
                try:
                    telemetry.sample(cls.state, cls.cfg, "tick")
                    n += 1
                    if n % 60 == 0:
                        telemetry.prune(cls.state, 24)
                except Exception:
                    pass          # never let the watcher break the watched
                _t.sleep(60)

        _th.Thread(target=loop, daemon=True).start()

    def clear_chat(self):'''


def main():
    if not os.path.exists(f"{RIFFLE}/agent/telemetry.py"):
        sys.exit("  agent/telemetry.py is missing — copy it in first.")

    # ---- 1. the error hook in state.log ------------------------------------
    patch(STATE,
          '''    def log(self, text, level="info", drive=None):
        self.db.execute("INSERT INTO journal (ts,level,drive,text) VALUES (?,?,?,?)",
                        (utcnow(), level, drive, text))
        self.db.commit()''',
          '''    def log(self, text, level="info", drive=None):
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
                pass''',
          "state.log triggers a dump on error", marker="ERROR_HOOK(self, level, text)")

    patch(STATE, "def utcnow():",
          "# Set by telemetry.install(). Left as None so state.py imports\n"
          "# standalone and nothing here depends on telemetry existing.\n"
          "ERROR_HOOK = None\n\n\ndef utcnow():",
          "ERROR_HOOK global", marker="ERROR_HOOK = None")

    # ---- 2. the cycle samples around its own work --------------------------
    patch(CYCLE, "    policy.ensure(state, cfg)",
          '''    policy.ensure(state, cfg)
    try:
        from agent import telemetry
        telemetry.install(state, cfg)
        telemetry.sample(state, cfg, "cycle-start")
    except Exception:
        pass''',
          "cycle samples at start", marker='telemetry.sample(state, cfg, "cycle-start")')

    # ---- 3. dashboard: routes, panel, sampler ------------------------------
    patch(DASH, '    if h.command == "GET" and u.path == "/api/policy":',
          ROUTES + '    if h.command == "GET" and u.path == "/api/policy":',
          "telemetry routes", marker='u.path == "/api/telemetry.jsonl"')

    patch(DASH, "<h2>instructions &mdash; what you told it</h2>",
          LOG_HTML + "\n<h2>instructions &mdash; what you told it</h2>",
          "log panel markup", marker="log &mdash; the last 24 hours")

    patch(DASH, ".mem .k{font-family:ui-monospace,monospace;",
          LOG_CSS + ".mem .k{font-family:ui-monospace,monospace;",
          "log panel styling", marker="#telbox{max-height:")

    patch(DASH, "async function loadPolicy(){", LOG_JS + "\nasync function loadPolicy(){",
          "loadTel()", marker="async function loadTel()")

    # The bootstrap call has no leading indent; anchor on the statement.
    patch(DASH, "\nload(); loadPolicy();\n",
          "\nload(); loadPolicy(); loadTel();\n",
          "settings loads the log", marker="loadPolicy(); loadTel();")

    patch(DASH, "    def clear_chat(self):", SAMPLER,
          "the minute sampler", marker="def start_telemetry(cls):")

    patch(DASH, "    Handler.start_scheduler()",
          "    Handler.start_scheduler()\n    Handler.start_telemetry()",
          "sampler starts with the dashboard", marker="Handler.start_telemetry()")

    # ---- 4. mobile layout ---------------------------------------------------
    patch(DASH, "html,body{height:100%}",
          "/* 100dvh, not 100vh: on mobile the address bar collapses and vh is\n"
          "   measured against the taller viewport, so the page overflows by\n"
          "   exactly the height of the bar. The document itself must not\n"
          "   scroll — only the log does — or the sticky header slides away. */\n"
          "html,body{height:100dvh;overflow:hidden;overscroll-behavior:none}",
          "page cannot scroll behind the header", marker="html,body{height:100dvh")

    patch(DASH, "#log{flex:1;overflow-y:auto;padding:16px 15px 8px;display:flex;",
          "#log{flex:1;min-height:0;overscroll-behavior:contain;\n"
          "  overflow-y:auto;padding:16px 15px 8px;display:flex;",
          "the log is the only scroller", marker="#log{flex:1;min-height:0;")

    # ---- 5. do not rebuild a card that has not changed ----------------------
    patch(DASH,
          "  el.innerHTML = esc(m.content) + (m.done ? '' : '<span class=dot>&#9612;</span>') +",
          "  // Rebuilding innerHTML throws away the scroll position of any <pre>\n"
          "  // inside, and proposal cards are re-sent every poll so their state\n"
          "  // can change. Draw only when what we would draw is different.\n"
          "  const _sig = m.role + '|' + m.done + '|' + m.content.length;\n"
          "  if(el.dataset.sig === _sig) return;\n"
          "  el.dataset.sig = _sig;\n"
          "  el.innerHTML = esc(m.content) + (m.done ? '' : '<span class=dot>&#9612;</span>') +",
          "messages are not redrawn unchanged", marker="el.dataset.sig === _sig")

    patch(DASH,
          "    el.className = 'card';\n    el.innerHTML = '<h4>'",
          "    const _csig = JSON.stringify([p.status, p.sent_at, p.ref, p.error,\n"
          "                                  m.content.length]);\n"
          "    if(el.dataset.sig === _csig) return;\n"
          "    el.dataset.sig = _csig;\n"
          "    el.className = 'card';\n    el.innerHTML = '<h4>'",
          "cards are not redrawn unchanged", marker="el.dataset.sig === _csig")

    # ---- 6. autoscroll toggle ----------------------------------------------
    patch(DASH, '  <button id=send>send</button>',
          '  <label id=autow title="follow new messages">'
          '<input type=checkbox id=autos checked> auto</label>\n'
          '  <button id=send>send</button>',
          "autoscroll checkbox", marker="id=autos")

    patch(DASH, "#send:disabled{opacity:.35}",
          "#send:disabled{opacity:.35}\n"
          "#autow{display:flex;align-items:center;gap:5px;font-size:11.5px;\n"
          "  color:var(--dim);white-space:nowrap;cursor:pointer;user-select:none}\n"
          "#autos{accent-color:var(--sig);width:15px;height:15px}",
          "autoscroll styling", marker="#autow{display:flex")

    patch(DASH, "const nearBottom = () =>",
          "const autos = document.getElementById('autos');\n"
          "try{ autos.checked = localStorage.getItem('riffle.autoscroll') !== '0'; }\n"
          "catch(e){}\n"
          "autos.onchange = function(){\n"
          "  try{ localStorage.setItem('riffle.autoscroll', autos.checked?'1':'0'); }\n"
          "  catch(e){}\n"
          "};\n"
          "const nearBottom = () =>",
          "the toggle is remembered", marker="riffle.autoscroll")

    patch(DASH, "    if(stick) log.scrollTop = log.scrollHeight;",
          "    // Only follow if the toggle is on AND you were already at the\n"
          "    // bottom. Either condition alone would yank the view while you\n"
          "    // are reading something further up.\n"
          "    if(stick && autos.checked) log.scrollTop = log.scrollHeight;",
          "autoscroll respects the toggle", marker="if(stick && autos.checked)")

    import ast
    for f in (DASH, STATE, CYCLE, f"{RIFFLE}/agent/telemetry.py"):
        ast.parse(open(f).read())
    print("\n  modules parse.")
    print("""
  Next:
    sudo systemctl restart riffle-dash
    sudo systemctl start riffle-cycle.service

  Give it a minute, then /settings will have a "log" panel above instructions.

    cd /opt/riffle && git add -A
    git commit -m "telemetry with dumps on error; log panel and download; mobile scroll and autoscroll fixes"
    git push
""")


if __name__ == "__main__":
    main()
