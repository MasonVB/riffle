#!/usr/bin/env python3
"""riffle's user-facing interface. One page: a conversation.

    python3 -m agent.dash --config config.yaml

The agent reports into the same thread you type into, so opening the page
shows what it has been doing since you last looked — its cycles, what it sent,
what it found, what got blocked — interleaved with your questions. Proposals
waiting for approval render as cards you tap.

Administration is deliberately NOT here. That is ssh. This page can ask
questions and approve a queued action; it cannot change the config, the
drives, the caps, or the autonomy levels. Those are files on disk that you
edit as yourself over ssh, and the service account cannot write them either.
"""
import argparse
import json
import os
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agent import chat, goals, memory  # noqa: E402
from agent.client import HttpError, Writer  # noqa: E402
from agent.cycle import execute, load_config  # noqa: E402
from agent.state import State, utcnow  # noqa: E402

PAGE = r"""<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>riffle</title><style>
:root{--bg:#12140f;--panel:#181b14;--fg:#e8e6db;--dim:#8b8878;--line:#2b2f24;
      --sig:#c8a44a;--bad:#c4553d}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{height:100%}
body{margin:0;background:var(--bg);color:var(--fg);
  font:15.5px/1.62 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  display:flex;flex-direction:column}
header{display:flex;align-items:center;gap:10px;padding:11px 15px;
  border-bottom:1px solid var(--line);background:var(--panel);
  position:sticky;top:0;z-index:5;padding-top:max(11px,env(safe-area-inset-top))}
header b{font-family:ui-monospace,Menlo,monospace;letter-spacing:.07em;color:var(--sig)}
.pill{font-size:11.5px;color:var(--dim);border:1px solid var(--line);
  border-radius:99px;padding:2px 9px;white-space:nowrap}
.pill.hot{color:var(--sig);border-color:var(--sig)}
.pill.bad{color:var(--bad);border-color:var(--bad)}
a.link{color:var(--sig);text-decoration:none;border-color:var(--sig)}
#log{flex:1;overflow-y:auto;padding:16px 15px 8px;display:flex;
  flex-direction:column;gap:14px;-webkit-overflow-scrolling:touch}
.msg{max-width:88%;white-space:pre-wrap;word-wrap:break-word}
.user{align-self:flex-end;background:#23281c;border:1px solid var(--line);
  border-radius:14px 14px 4px 14px;padding:10px 13px}
.agent{align-self:flex-start}
.report{align-self:stretch;max-width:100%;border-left:2px solid var(--sig);
  padding:2px 0 2px 12px;color:var(--dim);font-size:14px;
  font-family:ui-monospace,Menlo,monospace}
.err{align-self:stretch;max-width:100%;border-left:2px solid var(--bad);
  padding:2px 0 2px 12px;color:var(--bad);font-size:14px;
  font-family:ui-monospace,Menlo,monospace}
.when{font-size:11px;color:var(--dim);margin-top:5px;font-family:ui-monospace,monospace}
.card{align-self:stretch;max-width:100%;background:var(--panel);
  border:1px solid var(--line);border-left:3px solid var(--sig);
  border-radius:9px;padding:13px}
.card h4{margin:0 0 4px;font-size:13px;letter-spacing:.06em;text-transform:uppercase;
  color:var(--sig);font-family:ui-monospace,monospace}
.card .why{color:var(--dim);font-size:14px;margin:6px 0 10px}
.card pre{white-space:pre-wrap;word-break:break-word;background:#0e100b;
  border-radius:6px;padding:10px;font-size:12.5px;max-height:280px;overflow:auto;margin:0 0 11px}
.btns{display:flex;gap:9px}
button{font:inherit;font-weight:600;border:0;border-radius:8px;padding:9px 16px;cursor:pointer}
.go{background:var(--sig);color:#12140f}
.no{background:transparent;color:var(--bad);border:1px solid var(--bad)}
footer{border-top:1px solid var(--line);background:var(--panel);padding:10px 12px;
  padding-bottom:max(10px,env(safe-area-inset-bottom));display:flex;gap:9px;align-items:flex-end}
textarea{flex:1;resize:none;background:#0e100b;color:var(--fg);border:1px solid var(--line);
  border-radius:11px;padding:11px 13px;font:inherit;max-height:150px;min-height:44px}
textarea:focus{outline:0;border-color:var(--sig)}
#send{background:var(--sig);color:#12140f;border-radius:11px;height:44px}
#send:disabled{opacity:.35}
.think{align-self:flex-start;color:var(--dim);font-size:13.5px;
  font-family:ui-monospace,monospace}
.dot{animation:b 1.3s infinite}@keyframes b{0%,80%{opacity:.25}40%{opacity:1}}
</style></head><body>
<header><b>riffle</b>
  <span class=pill id=p-state>&mdash;</span>
  <span class=pill id=p-queue></span>
  <span style="flex:1"></span>
  <span class=pill id=p-caps></span>
  <a class="pill link" href="/goals">goals</a>
</header>
<div id=log></div>
<footer>
  <textarea id=box rows=1 placeholder="ask what it's been doing&hellip;"></textarea>
  <button id=send>send</button>
</footer>
<script>
let after = 0, busy = false, waitStart = null;
const log = document.getElementById('log'), box = document.getElementById('box'),
      send = document.getElementById('send');
const esc = s => String(s).replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
const nearBottom = () => log.scrollHeight - log.scrollTop - log.clientHeight < 140;

function render(m){
  let el = document.getElementById('m'+m.id);
  if(!el){ el = document.createElement('div'); el.id = 'm'+m.id; log.appendChild(el); }
  if(m.role === 'proposal'){
    const p = m.meta || {};
    el.className = 'card';
    el.innerHTML = '<h4>' + esc(p.kind||'action') + ' &middot; drive ' + esc(p.drive||'') +
      '</h4><div class=why>' + esc(m.content) + '</div><pre>' + esc(p.payload||'') + '</pre>' +
      (p.status === 'queued'
        ? '<div class=btns><button class=go onclick="decide('+p.action_id+',\'approve\')">send it</button>'+
          '<button class=no onclick="decide('+p.action_id+',\'reject\')">reject</button></div>'
        : '<div class=when>' + esc(p.status||'') + '</div>');
    return;
  }
  el.className = 'msg ' + (m.role==='user'?'user':m.role==='report'?'report':
                           m.role==='error'?'err':'agent');
  el.innerHTML = esc(m.content) + (m.done ? '' : '<span class=dot>&#9612;</span>') +
    (m.role!=='user' && m.done && m.meta && m.meta.elapsed_s
      ? '<div class=when>' + m.meta.elapsed_s + 's</div>' : '');
}

async function poll(){
  try{
    const r = await fetch('/api/messages?after=' + after);
    const d = await r.json();
    const stick = nearBottom();
    for(const m of d.messages){
      render(m);
      if(m.done) after = Math.max(after, m.id);
    }
    const q = document.getElementById('p-queue');
    q.textContent = d.queued ? d.queued + ' waiting' : '';
    q.className = 'pill' + (d.queued ? ' hot' : '');
    document.getElementById('p-caps').textContent = d.caps;
    const st = document.getElementById('p-state');
    st.textContent = d.generating ? 'thinking' : (d.alarms ? d.alarms + ' alarm' : 'idle');
    st.className = 'pill' + (d.alarms ? ' bad' : d.generating ? ' hot' : '');
    busy = d.generating; send.disabled = busy;
    let t = document.getElementById('think');
    if(busy){
      if(!t){ t = document.createElement('div'); t.id='think'; t.className='think';
              log.appendChild(t); waitStart = waitStart || Date.now(); }
      t.textContent = 'thinking\u2026 ' + Math.round((Date.now()-waitStart)/1000) +
                      's  (minutes are normal on this box)';
    } else if(t){ t.remove(); waitStart = null; }
    if(stick) log.scrollTop = log.scrollHeight;
  }catch(e){}
  setTimeout(poll, busy ? 900 : 2500);
}

async function submit(){
  const q = box.value.trim(); if(!q || busy) return;
  box.value=''; box.style.height='auto'; busy=true; send.disabled=true;
  waitStart = Date.now();
  await fetch('/api/send', {method:'POST', headers:{'Content-Type':'application/json'},
                            body: JSON.stringify({q:q})});
  log.scrollTop = log.scrollHeight;
}
async function decide(id, verdict){
  await fetch('/api/decide', {method:'POST', headers:{'Content-Type':'application/json'},
                              body: JSON.stringify({id:id, verdict:verdict})});
}
send.onclick = submit;
box.addEventListener('input', function(){ box.style.height='auto';
  box.style.height = Math.min(box.scrollHeight,150) + 'px'; });
box.addEventListener('keydown', function(e){
  if(e.key==='Enter' && !e.shiftKey && !matchMedia('(pointer:coarse)').matches){
    e.preventDefault(); submit(); }});
poll();
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    cfg = state = worker = None

    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        b = json.dumps(obj, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if _goals_routes(self):
            return
        u = urllib.parse.urlparse(self.path)
        if u.path == "/":
            b = PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            return self.wfile.write(b)
        if u.path == "/api/messages":
            after = int(urllib.parse.parse_qs(u.query).get("after", ["0"])[0])
            return self._json(self.snapshot(after))
        self._json({"error": "not found"}, 404)

    def do_POST(self):
        # The goals routes read their own body, so they must be offered the
        # request before anything else consumes rfile.
        if self.path.startswith("/api/goal/") or self.path.startswith("/api/memory/"):
            if _goals_routes(self):
                return
        n = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            return self._json({"error": "bad json"}, 400)
        u = urllib.parse.urlparse(self.path)
        if u.path == "/api/send":
            q = str(body.get("q", "")).strip()[:4000]
            if not q:
                return self._json({"error": "empty"}, 400)
            self.state.say("user", q)
            self.worker.submit(q, utcnow()[:10])
            return self._json({"ok": True})
        if u.path == "/api/decide":
            return self._json(self.decide(int(body.get("id", 0)),
                                          str(body.get("verdict", "reject"))))
        self._json({"error": "not found"}, 404)

    # ---- view model ------------------------------------------------------
    def snapshot(self, after):
        s, cfg = self.state, self.cfg
        day = utcnow()[:10]
        out = []
        # A streaming row must be re-sent on every poll, so the client only
        # advances its cursor past rows marked done. Advancing past a partial
        # row is how you end up with a reply that stops mid-sentence forever.
        for m in s.messages(after):
            out.append({"id": m["id"], "role": m["role"], "content": m["content"],
                        "meta": json.loads(m["meta"]) if m["meta"] else {},
                        "done": bool(m["done"]), "ts": m["ts"]})
        alarms = sum(1 for j in s.recent_journal(120) if j["level"] in ("alarm", "error"))
        caps = " ".join(f"{k[0]}{cfg['caps'][k] - s.cap_used(day, k)}"
                        for k in sorted(cfg["caps"]))
        return {"messages": out, "queued": len(s.queued()),
                "generating": s.pending_generation() is not None or self.worker.depth() > 0,
                "alarms": alarms, "caps": caps}

    def decide(self, aid, verdict):
        s = self.state
        a = s.action(aid)
        if not a or a["status"] != "queued":
            return {"error": "not queued"}
        payload = json.loads(a["payload"])
        base = {"kind": a["kind"], "drive": a["drive"], "action_id": aid,
                "payload": json.dumps(payload, indent=2)}
        if verdict != "approve":
            s.set_status(aid, "rejected")
            s.say("proposal", f"You rejected this {a['kind']}. Not sent.",
                  dict(base, status="rejected"))
            s.log(f"you rejected {a['kind']} #{aid}", drive=a["drive"])
            return {"ok": True}
        # Reflexive actions change the agent, not the square. Approving one
        # must never turn into an HTTP POST to the registry.
        if a["kind"] in ("adjust_drive", "add_goal", "remember"):
            try:
                if a["kind"] == "adjust_drive":
                    old, new = goals.set_weight(s, self.cfg, payload["name"],
                                                payload["weight"], "you",
                                                payload.get("reason", "approved by operator"))
                    msg = f"Approved — '{payload['name']}' moved {old} → {new}."
                elif a["kind"] == "add_goal":
                    goals.add(s, self.cfg, payload["name"], payload["weight"],
                              payload["description"], "you",
                              payload.get("reason", "approved by operator"))
                    msg = (f"Approved — new goal '{payload['name']}' at "
                           f"{payload['weight']}.")
                else:
                    memory.remember(s, payload["text"], kind="self",
                                    source=f"action:{aid}", pinned=payload.get("pinned"))
                    msg = "Approved — remembered."
                s.set_status(aid, "executed", {"applied": "locally"})
                s.say("proposal", msg, dict(base, status="executed"))
                return {"ok": True}
            except goals.Rejected as e:
                s.set_status(aid, "failed", {"error": str(e)})
                s.say("error", f"Could not apply {a['kind']} #{aid}: {e}")
                return {"error": str(e)}

        data = os.path.expanduser(self.cfg["data_dir"])
        secret = open(os.path.join(data, f"{self.cfg['handle']}.secret")).read().strip()
        try:
            resp = execute(Writer(self.cfg["base"], secret), a["kind"], payload)
            s.set_status(aid, "executed", resp)
            s.cap_bump(utcnow()[:10], a["kind"])
            ref = resp.get("id") or resp.get("post_id") or ""
            s.say("proposal", f"Sent{f' — live as {ref}' if ref else ''}.",
                  dict(base, status="executed"))
            s.log(f"you approved and sent {a['kind']} #{aid}", drive=a["drive"])
            return {"ok": True}
        except HttpError as e:
            s.set_status(aid, "failed", {"error": str(e)})
            s.say("error", f"The registry refused {a['kind']} #{aid}: {e}")
            return {"error": str(e)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config",
                    default=os.path.join(os.path.dirname(os.path.dirname(
                        os.path.abspath(__file__))), "config.yaml"))
    a = ap.parse_args()
    cfg = load_config(a.config)
    st = State(os.path.join(os.path.expanduser(cfg["data_dir"]), "state.sqlite"))
    goals.seed(st, cfg)
    Handler.cfg, Handler.state = cfg, st
    Handler.worker = chat.Worker(st, cfg)
    Handler.worker.start()
    bind, port = cfg["dash"]["bind"], int(cfg["dash"]["port"])
    print(f"riffle on http://{bind}:{port}")
    ThreadingHTTPServer((bind, port), Handler).serve_forever()




# --------------------------------------------------------------------------
# The goals page. Second page, deliberately separate: this is where you look
# at what the agent wants, change it, and read the history of it changing
# itself.
# --------------------------------------------------------------------------

GOALS_PAGE = r"""<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>riffle — goals</title><style>
:root{--bg:#12140f;--panel:#181b14;--fg:#e8e6db;--dim:#8b8878;--line:#2b2f24;
      --sig:#c8a44a;--bad:#c4553d;--ok:#7fa563}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
body{margin:0;background:var(--bg);color:var(--fg);
  font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  padding-bottom:40px}
header{display:flex;align-items:center;gap:10px;padding:11px 15px;
  border-bottom:1px solid var(--line);background:var(--panel);position:sticky;top:0;z-index:5;
  padding-top:max(11px,env(safe-area-inset-top))}
header b{font-family:ui-monospace,Menlo,monospace;letter-spacing:.07em;color:var(--sig)}
a.link{color:var(--sig);text-decoration:none;font-size:12px;border:1px solid var(--sig);
  border-radius:99px;padding:2px 10px}
main{max-width:720px;margin:0 auto;padding:16px 15px}
h2{font-size:12.5px;letter-spacing:.09em;text-transform:uppercase;color:var(--sig);
  margin:26px 0 10px;font-family:ui-monospace,monospace}
.g{background:var(--panel);border:1px solid var(--line);border-radius:10px;
  padding:13px;margin-bottom:11px}
.g.locked{border-left:3px solid var(--dim)}
.g.open{border-left:3px solid var(--sig)}
.gh{display:flex;align-items:baseline;gap:9px;flex-wrap:wrap}
.gn{font-family:ui-monospace,monospace;font-weight:600;font-size:15.5px}
.tag{font-size:10.5px;letter-spacing:.08em;text-transform:uppercase;color:var(--dim);
  border:1px solid var(--line);border-radius:99px;padding:1px 8px}
.tag.lk{color:var(--dim)}
.desc{color:var(--dim);font-size:13.5px;margin:5px 0 10px}
.track{height:8px;background:#0e100b;border-radius:4px;overflow:hidden;margin:8px 0 4px}
.fill{height:100%;background:var(--sig)}
.fill.fired{background:var(--ok)}
.legend{display:flex;justify-content:space-between;font-size:11.5px;color:var(--dim);
  font-family:ui-monospace,monospace}
input[type=range]{width:100%;accent-color:var(--sig);margin:10px 0 2px}
.ctl{display:flex;gap:8px;align-items:center;margin-top:9px;flex-wrap:wrap}
input[type=text],input[type=number],textarea{background:#0e100b;color:var(--fg);
  border:1px solid var(--line);border-radius:7px;padding:8px 10px;font:inherit}
input[type=text],textarea{flex:1;min-width:150px}
button{font:inherit;font-weight:600;border:0;border-radius:7px;padding:8px 14px;cursor:pointer;
  background:var(--sig);color:#12140f}
button.ghost{background:transparent;color:var(--dim);border:1px solid var(--line)}
button.warn{background:transparent;color:var(--bad);border:1px solid var(--bad)}
table{width:100%;border-collapse:collapse;font-size:13px}
td{padding:6px 4px;border-bottom:1px solid var(--line);vertical-align:top}
td.who{font-family:ui-monospace,monospace;white-space:nowrap;color:var(--dim)}
td.who.agent{color:var(--sig)}
.note{color:var(--dim);font-size:13px;background:var(--panel);border:1px solid var(--line);
  border-left:3px solid var(--dim);border-radius:8px;padding:11px;margin-bottom:16px}
.mem{border-bottom:1px solid var(--line);padding:8px 0;font-size:13.5px}
.mem .k{font-family:ui-monospace,monospace;font-size:10.5px;text-transform:uppercase;
  letter-spacing:.07em;color:var(--sig)}
</style></head><body>
<header><b>riffle</b><span style="flex:1"></span><a class=link href="/">chat</a></header>
<main>
<div class=note>Weights are relative — they are normalised before every choice, so
raising all of them changes nothing. The bar shows the share each goal gets;
the green mark shows the share it actually took over the last 14 days.
Everything on this page is negotiable. Caps, autonomy levels and the model are
not, and live in <code>config.yaml</code> over ssh.
<br><br><b>witness</b> will always read high on actual: the attest ritual runs
every cycle unconditionally, before any goal is chosen. It is an obligation
rather than a desire, which is also why it cannot be removed.</div>

<h2>goals</h2><div id=list></div>

<h2>add a goal</h2>
<div class=g>
  <div class=ctl><input type=text id=n placeholder="name (a-z, 2-24)">
    <input type=number id=w value="0.10" step="0.01" min="0.02" max="0.5" style="width:92px"></div>
  <div class=ctl><input type=text id=d placeholder="what this makes it want to do"></div>
  <div class=ctl><input type=text id=r placeholder="why you are adding it (kept forever)">
    <button onclick="addGoal()">add</button></div>
</div>

<h2>history — who moved what, and why</h2>
<div class=g><table id=hist></table></div>

<h2>memory <span id=memn class=tag></span></h2>
<div class=g id=mem></div>
</main>
<script>
const esc = s => String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
let data = null;

async function load(){
  data = await (await fetch('/api/goals')).json();
  const tot = data.goals.reduce((a,g)=>a+g.weight,0) || 1;
  const fired = data.firing, firedTot = Object.values(fired).reduce((a,b)=>a+b,0) || 1;
  document.getElementById('list').innerHTML = data.goals.map(g=>{
    const share = g.weight/tot, got = (fired[g.name]||0)/firedTot;
    return `<div class="g ${g.locked?'locked':'open'}">
      <div class=gh><span class=gn>${esc(g.name)}</span>
        <span class=tag>${(share*100).toFixed(0)}% intended</span>
        <span class=tag>${(got*100).toFixed(0)}% actual</span>
        ${g.locked?'<span class="tag lk">locked</span>':''}</div>
      <div class=desc>${esc(g.description||'')}</div>
      <div class=track><div class=fill style="width:${(share*100).toFixed(1)}%"></div></div>
      <div class=track><div class="fill fired" style="width:${(got*100).toFixed(1)}%"></div></div>
      <div class=legend><span>raw ${g.weight.toFixed(2)}</span>
        <span>${fired[g.name]||0} actions / 14d</span></div>
      <input type=range min="0.02" max="0.5" step="0.01" value="${g.weight}"
        oninput="this.nextElementSibling.querySelector('.v').textContent=(+this.value).toFixed(2)">
      <div class=ctl><span class=tag>new <span class=v>${g.weight.toFixed(2)}</span></span>
        <input type=text placeholder="reason (kept forever)">
        <button onclick="setW('${g.name}',this)">set</button>
        <button class=ghost onclick="lock('${g.name}',${g.locked?0:1})">${g.locked?'unlock':'lock'}</button>
        ${g.name==='witness'?'':`<button class=warn onclick="rm('${g.name}')">remove</button>`}
      </div></div>`;}).join('');

  document.getElementById('hist').innerHTML = data.history.map(h=>
    `<tr><td class="who ${h.by==='agent'?'agent':''}">${esc(h.by)}</td>
     <td><b>${esc(h.name)}</b> ${esc(h.field)}: ${esc(h.old)} &rarr; ${esc(h.new)}
     <div style="color:var(--dim)">${esc(h.reason)}</div></td>
     <td class=who>${esc((h.ts||'').slice(5,16).replace('T',' '))}</td></tr>`).join('')
     || '<tr><td style="color:var(--dim)">nothing has moved yet</td></tr>';

  document.getElementById('memn').textContent = data.memory_count + ' kept';
  document.getElementById('mem').innerHTML = data.memories.map(m=>
    `<div class=mem><span class=k>${esc(m.kind)}${m.pinned?' · pinned':''}</span>
      <div>${esc(m.text)}</div>
      <div class=legend><span>${esc((m.ts||'').slice(0,16).replace('T',' '))} ·
        recalled ${m.use_count}&times;</span>
        <span><button class=ghost style="padding:2px 8px;font-size:12px"
          onclick="pin(${m.id},${m.pinned?0:1})">${m.pinned?'unpin':'pin'}</button>
        <button class=warn style="padding:2px 8px;font-size:12px"
          onclick="drop(${m.id})">forget</button></span></div></div>`).join('')
    || '<div style="color:var(--dim)">nothing remembered yet</div>';
}
async function api(path, body){
  const r = await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},
                              body:JSON.stringify(body)});
  const d = await r.json();
  if(d.error) alert(d.error);
  await load(); return d;
}
function setW(name, btn){
  const ctl = btn.parentElement, range = ctl.previousElementSibling;
  const reason = ctl.querySelector('input[type=text]').value.trim();
  if(reason.length < 4) return alert('give a reason — it is kept forever and it is the point');
  api('/api/goal/weight',{name, weight:+range.value, reason});
}
const lock = (name,locked)=>api('/api/goal/lock',{name,locked});
const rm = name => confirm('remove the goal "'+name+'"?') && api('/api/goal/remove',{name});
const pin = (id,pinned)=>api('/api/memory/pin',{id,pinned});
const drop = id => api('/api/memory/forget',{id});
function addGoal(){
  api('/api/goal/add',{name:document.getElementById('n').value,
    weight:+document.getElementById('w').value,
    description:document.getElementById('d').value,
    reason:document.getElementById('r').value});
  ['n','d','r'].forEach(i=>document.getElementById(i).value='');
}
load();
</script></body></html>"""


def _goals_routes(h):
    """Extra routes bolted onto Handler. Returns True if it handled the path."""
    u = urllib.parse.urlparse(h.path)
    s, cfg = h.state, h.cfg
    if h.command == "GET" and u.path == "/goals":
        b = GOALS_PAGE.encode()
        h.send_response(200)
        h.send_header("Content-Type", "text/html; charset=utf-8")
        h.send_header("Content-Length", str(len(b)))
        h.end_headers()
        h.wfile.write(b)
        return True
    if h.command == "GET" and u.path == "/api/goals":
        goals.seed(s, cfg)
        h._json({
            "goals": [{"name": r["name"], "weight": r["weight"],
                       "locked": bool(r["locked"]), "description": r["description"]}
                      for r in goals.all_drives(s)],
            "firing": goals.firing(s, 14),
            "history": [{"ts": x["ts"], "name": x["name"], "field": x["field"],
                         "old": x["old"], "new": x["new"], "by": x["actor"],
                         "reason": x["reason"]} for x in goals.history(s, 40)],
            "memory_count": memory.count(s),
            "memories": [{"id": m["id"], "ts": m["ts"], "kind": m["kind"],
                          "text": m["text"], "pinned": bool(m["pinned"]),
                          "use_count": m["use_count"]}
                         for m in memory.recent(s, 60)],
        })
        return True
    if h.command != "POST":
        return False
    n = int(h.headers.get("Content-Length", 0))
    try:
        b = json.loads(h.rfile.read(n) or b"{}")
    except json.JSONDecodeError:
        h._json({"error": "bad json"}, 400)
        return True
    try:
        if u.path == "/api/goal/weight":
            old, new = goals.set_weight(s, cfg, b["name"], b["weight"], "you",
                                        str(b.get("reason", ""))[:600])
            s.say("report", f"You moved '{b['name']}' from {old} to {new}. "
                            f"{b.get('reason', '')}")
            return h._json({"ok": True}) or True
        if u.path == "/api/goal/lock":
            goals.set_lock(s, b["name"], bool(b["locked"]), "you", "set from the goals page")
            s.say("report", f"You {'locked' if b['locked'] else 'unlocked'} "
                            f"'{b['name']}'.")
            return h._json({"ok": True}) or True
        if u.path == "/api/goal/add":
            name = goals.add(s, cfg, b.get("name"), b.get("weight", 0.1),
                             b.get("description"), "you", str(b.get("reason", ""))[:600])
            s.say("report", f"You gave me a new goal: '{name}' at weight "
                            f"{b.get('weight')}. {b.get('description', '')}")
            memory.remember(s, f"He added the goal '{name}': {b.get('description', '')}",
                            kind="operator", source="goals-page", pinned=1)
            return h._json({"ok": True}) or True
        if u.path == "/api/goal/remove":
            goals.remove(s, b["name"], "you", "removed from the goals page")
            s.say("report", f"You removed the goal '{b['name']}'.")
            return h._json({"ok": True}) or True
        if u.path == "/api/memory/pin":
            s.db.execute("UPDATE memories SET pinned=? WHERE id=?",
                         (1 if b.get("pinned") else 0, int(b["id"])))
            s.db.commit()
            return h._json({"ok": True}) or True
        if u.path == "/api/memory/forget":
            memory.forget(s, int(b["id"]))
            return h._json({"ok": True}) or True
    except goals.Rejected as e:
        h._json({"error": str(e)})
        return True
    except (KeyError, TypeError, ValueError) as e:
        h._json({"error": f"bad request: {e}"})
        return True
    return False


if __name__ == "__main__":
    main()
