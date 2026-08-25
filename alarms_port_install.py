#!/usr/bin/env python3
"""Alarm dropdown, and move the console to http://riffle (port 80).

    sudo cp alarms_port_install.py /opt/riffle/
    sudo python3 /opt/riffle/alarms_port_install.py

TWO CHANGES

1. ALARM DROPDOWN. Hover previews the alarms; click pins the panel open and
   inverts the pill; click again closes it. The panel scrolls, and a clear
   button sits at the bottom.

   CLEARING ACKNOWLEDGES, IT DOES NOT DELETE. The journal is append-only and
   stays that way — clearing writes a watermark (the highest journal id you
   have seen) into the notes table, and the badge counts alarms above it. The
   history of what went wrong survives being dismissed, which is the same
   reason the square keeps retractions and the same reason memory corrections
   supersede rather than delete.

2. PORT 80, so the console is at http://riffle with no port.

   Port 80 is privileged and riffle-dash runs unprivileged. The fix is one
   capability, CAP_NET_BIND_SERVICE, which allows binding low ports and
   nothing else — not root, not file access, not process control. The unit's
   CapabilityBoundingSet goes from empty to exactly that one, so it remains
   the only capability the service can ever hold.

   Your browser may try https:// first and fail, since there is no TLS here.
   Type http:// explicitly the first time.

Backups are written as .bak-alarms.
"""
import os
import shutil
import sys

RIFFLE = "/opt/riffle"
DASH = f"{RIFFLE}/agent/dash.py"
NOTIFY = f"{RIFFLE}/agent/notify.py"
CFG = f"{RIFFLE}/config.yaml"
UNITS = [f"{RIFFLE}/systemd/riffle-dash.service",
         "/etc/systemd/system/riffle-dash.service"]


def patch(path, old, new, label, marker, required=True):
    s = open(path).read()
    if marker in s:
        print(f"  already present: {label}")
        return False
    if old not in s:
        if required:
            sys.exit(f"  FAILED: anchor not found in {path} ({label}). Nothing changed.")
        print(f"  skipped: {label}")
        return False
    if not os.path.exists(f"{path}.bak-alarms"):
        shutil.copy(path, f"{path}.bak-alarms")
    open(path, "w").write(s.replace(old, new, 1))
    print(f"  patched: {label}")
    return True


CSS = """
.alarmwrap{position:relative;display:inline-block}
.alarmpanel{display:none;position:absolute;top:26px;left:0;z-index:40;
  min-width:min(78vw,440px);max-width:min(92vw,520px);max-height:min(56vh,340px);
  overflow-y:auto;background:var(--panel);border:1px solid var(--bad);
  border-radius:9px;padding:0;box-shadow:0 10px 34px rgba(0,0,0,.6);
  -webkit-overflow-scrolling:touch}
.alarmwrap:hover .alarmpanel,.alarmwrap.pinned .alarmpanel{display:block}
.pill.bad.pinned{background:var(--bad);color:var(--bg);font-weight:600}
.alarmrow{padding:9px 12px;border-bottom:1px solid var(--line);font-size:13px;
  line-height:1.5;word-break:break-word}
.alarmrow:last-of-type{border-bottom:0}
.alarmrow .m{color:var(--dim);font-family:ui-monospace,Menlo,monospace;font-size:10.5px;
  letter-spacing:.05em;text-transform:uppercase;display:block;margin-bottom:3px}
.alarmrow.lvl-alarm .m{color:var(--bad)}
.clearbar{position:sticky;bottom:0;background:var(--panel);border-top:1px solid var(--line);
  padding:8px;display:flex;justify-content:flex-end}
.clearbtn{font:inherit;font-size:12px;font-weight:600;background:transparent;
  color:var(--bad);border:1px solid var(--bad);border-radius:7px;padding:5px 14px;
  cursor:pointer}
.alarmempty{padding:12px;color:var(--dim);font-size:13px}"""

HEADER_OLD = '  <span class=pill id=p-state>&mdash;</span>'
HEADER_NEW = '''  <span class=alarmwrap id=alarmwrap>
    <span class=pill id=p-state onclick="toggleAlarms(event)">&mdash;</span>
    <div class=alarmpanel id=alarmpanel>
      <div id=alarmlist></div>
      <div class=clearbar><button class=clearbtn onclick="clearAlarms(event)">clear</button></div>
    </div>
  </span>'''

JS = '''function toggleAlarms(e){
  e.stopPropagation();
  const w = document.getElementById('alarmwrap');
  if(!w.dataset.has) return;              // nothing to show, nothing to pin
  w.classList.toggle('pinned');
  document.getElementById('p-state').classList.toggle('pinned',
    w.classList.contains('pinned'));
}
document.addEventListener('click', function(e){
  const w = document.getElementById('alarmwrap');
  if(w && w.classList.contains('pinned') && !w.contains(e.target)){
    w.classList.remove('pinned');
    document.getElementById('p-state').classList.remove('pinned');
  }
});
async function clearAlarms(e){
  e.stopPropagation();
  await fetch('/api/clear-alarms', {method:'POST',
    headers:{'Content-Type':'application/json'}, body:'{}'});
  const w = document.getElementById('alarmwrap');
  w.classList.remove('pinned');
  document.getElementById('p-state').classList.remove('pinned');
}
function renderAlarms(list){
  const w = document.getElementById('alarmwrap');
  w.dataset.has = list && list.length ? '1' : '';
  if(!list || !list.length){
    if(w.classList.contains('pinned')){
      w.classList.remove('pinned');
      document.getElementById('p-state').classList.remove('pinned');
    }
    document.getElementById('alarmlist').innerHTML =
      '<div class=alarmempty>nothing outstanding</div>';
    return;
  }
  document.getElementById('alarmlist').innerHTML = list.map(a =>
    '<div class="alarmrow lvl-' + esc(a.level) + '"><span class=m>' +
    esc(a.level) + ' &middot; ' + esc((a.ts||'').slice(5,16).replace('T',' ')) +
    (a.drive ? ' &middot; ' + esc(a.drive) : '') + '</span>' +
    esc(a.text) + '</div>').join('');
}
'''


def main():
    # ---- 1. dashboard ----------------------------------------------------
    patch(DASH, ".pill.bad{color:var(--bad);border-color:var(--bad)}",
          ".pill.bad{color:var(--bad);border-color:var(--bad)}" + CSS,
          "alarm panel CSS", marker=".alarmpanel{")

    patch(DASH, HEADER_OLD, HEADER_NEW, "alarm panel markup",
          marker="id=alarmpanel")

    patch(DASH, "function render(m){", JS + "\nfunction render(m){",
          "alarm panel script", marker="function renderAlarms(")

    patch(DASH,
          "    const st = document.getElementById('p-state');",
          "    renderAlarms(d.alarms_list);\n"
          "    const st = document.getElementById('p-state');",
          "poll renders the alarm list", marker="renderAlarms(d.alarms_list)")

    # count and list both respect the acknowledgement watermark
    patch(DASH,
          '        alarms = sum(1 for j in s.recent_journal(120) '
          'if j["level"] in ("alarm", "error"))',
          '''        # Acknowledged alarms stay in the journal; the badge just stops
        # counting them. Clearing is a watermark, not a delete.
        seen = int(s.note("alarms_acked_to") or 0)
        arows = s.db.execute(
            "SELECT id, ts, level, drive, text FROM journal"
            " WHERE level IN ('alarm','error') AND id > ?"
            " ORDER BY id DESC LIMIT 100", (seen,)).fetchall()
        alarms = len(arows)
        alarm_list = [{"id": r["id"], "ts": r["ts"], "level": r["level"],
                       "drive": r["drive"], "text": r["text"]} for r in arows]''',
          "alarm count honours the watermark", marker="alarms_acked_to")

    patch(DASH,
          '        return {"messages": out, "queued": len(s.queued()),',
          '        return {"messages": out, "queued": len(s.queued()),\n'
          '                "alarms_list": alarm_list,',
          "snapshot returns the alarm list", marker='"alarms_list": alarm_list')

    patch(DASH,
          '        if u.path == "/api/run-cycle":',
          '''        if u.path == "/api/clear-alarms":
            return self._json(self.clear_alarms())
        if u.path == "/api/run-cycle":''',
          "clear-alarms route", marker='"/api/clear-alarms"')

    patch(DASH, "    def decide(self, aid, verdict):",
          '''    def clear_alarms(self):
        """Acknowledge every alarm up to now. The journal itself is untouched."""
        s = self.state
        row = s.db.execute(
            "SELECT MAX(id) m FROM journal WHERE level IN ('alarm','error')").fetchone()
        top = row["m"] or 0
        s.note("alarms_acked_to", top)
        s.log(f"you cleared the alarm badge up to journal id {top}; "
              f"the entries themselves are still on record")
        return {"ok": True, "acked_to": top}

    def decide(self, aid, verdict):''',
          "clear_alarms handler", marker="def clear_alarms(self)")

    # ---- 2. port 80 ------------------------------------------------------
    cfg = open(CFG).read()
    if "port: 8917" in cfg:
        if not os.path.exists(CFG + ".bak-alarms"):
            shutil.copy(CFG, CFG + ".bak-alarms")
        open(CFG, "w").write(cfg.replace("port: 8917", "port: 80", 1))
        print("  config.yaml: dash port 8917 -> 80")
    else:
        print("  already present: dash port 80")

    for u in UNITS:
        if not os.path.exists(u):
            continue
        s = open(u).read()
        if "AmbientCapabilities" in s:
            print(f"  already present: capability in {os.path.basename(u)}")
            continue
        if not os.path.exists(u + ".bak-alarms"):
            shutil.copy(u, u + ".bak-alarms")
        s = s.replace(
            "CapabilityBoundingSet=",
            "# Binding port 80 unprivileged. CAP_NET_BIND_SERVICE permits low\n"
            "# ports and nothing else — no root, no file access, no process\n"
            "# control — and the bounding set holds it to exactly that one.\n"
            "AmbientCapabilities=CAP_NET_BIND_SERVICE\n"
            "CapabilityBoundingSet=CAP_NET_BIND_SERVICE")
        open(u, "w").write(s)
        print(f"  granted CAP_NET_BIND_SERVICE in {os.path.basename(u)}")

    # notification links should not read http://riffle:80/
    patch(NOTIFY,
          '    return f"http://{host}:{cfg.get(\'dash\', {}).get(\'port\', 8917)}/"',
          '    port = cfg.get("dash", {}).get("port", 8917)\n'
          '    return f"http://{host}/" if int(port) == 80 else f"http://{host}:{port}/"',
          "notification link omits :80", marker='if int(port) == 80', required=False)

    import ast
    for f in (DASH, NOTIFY):
        ast.parse(open(f).read())
    print("\n  modules parse.")
    print("""
  Next:
    sudo systemctl daemon-reload
    sudo systemctl restart riffle-dash
    sudo ss -tlnp | grep ':80 '
  then open  http://riffle   (type http:// explicitly — there is no TLS)""")


if __name__ == "__main__":
    main()
