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
import subprocess  # noqa: E402
import threading as _th  # noqa: E402
from agent.client import HttpError, Writer  # noqa: E402
from agent.cycle import execute, load_config  # noqa: E402
from agent.state import State, utcnow  # noqa: E402

PAGE = r"""<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>riffle</title><style>
:root{--bg:#12140f;--panel:#181b14;--fg:#e8e6db;--dim:#8b8878;--line:#2b2f24;
      --sig:#c8a44a;--bad:#c4553d}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
/* 100dvh, not 100vh: on mobile the address bar collapses and vh is
   measured against the taller viewport, so the page overflows by
   exactly the height of the bar. The document itself must not
   scroll — only the log does — or the sticky header slides away. */
html,body{height:100dvh;overflow:hidden;overscroll-behavior:none}
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
a.brand{font-family:ui-monospace,Menlo,monospace;letter-spacing:.07em;
  color:var(--sig);text-decoration:none;font-weight:700;padding:2px 6px;
  border-radius:6px;margin-left:-6px;transition:background .12s ease,color .12s ease}
@media (hover:hover){a.brand:hover{background:var(--sig);color:var(--bg)}}
a.brand:active{background:var(--sig);color:var(--bg)}
/* One shape for every pill in the header. These were styled separately as
   each was added and had drifted to three different heights; the colour
   variants below carry more specificity and keep their own overrides. */
.pill,.pillbtn,a.link{
  display:inline-flex;align-items:center;justify-content:center;
  height:23px;box-sizing:border-box;
  font:inherit;font-size:11.5px;line-height:1;letter-spacing:.01em;
  padding:0 11px;border-radius:99px;border:1px solid var(--line);
  white-space:nowrap;vertical-align:middle;text-decoration:none}
.alarmwrap{display:inline-flex;align-items:center;vertical-align:middle}
header{align-items:center}
/* Every clickable thing inverts on hover, and holds the inversion while
   pressed. Pointer-coarse devices get the active state only, since a phone
   has no hover and a sticky :hover after a tap reads as a stuck button. */
@media (hover:hover){
  .pillbtn:hover{background:var(--sig);color:var(--bg)}
  a.link:hover{background:var(--sig);color:var(--bg)}
  .pill.bad:hover{background:var(--bad);color:var(--bg);cursor:pointer}
  .clearbtn:hover{background:var(--bad);color:var(--bg)}
  button.go:hover{background:var(--fg);color:var(--bg)}
  button.no:hover{background:var(--bad);color:var(--bg)}
  #send:hover{background:var(--fg)}
}
.pillbtn:active,a.link:active{background:var(--sig);color:var(--bg)}
.clearbtn:active,button.no:active{background:var(--bad);color:var(--bg)}
button.go:active{background:var(--fg);color:var(--bg)}
.pillbtn,a.link,.clearbtn,button.go,button.no,#send{
  transition:background .12s ease,color .12s ease}
.sentline{font-size:12px;color:var(--dim);font-family:ui-monospace,Menlo,monospace;
  display:flex;align-items:center;gap:7px}
.sentline.bad{color:var(--bad)}
.spin{display:inline-block;animation:sp 1.1s linear infinite}
@keyframes sp{to{transform:rotate(360deg)}}
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
.alarmempty{padding:12px;color:var(--dim);font-size:13px}
.pillbtn{font:inherit;font-size:11.5px;background:transparent;color:var(--sig);
  border:1px solid var(--sig);border-radius:99px;padding:3px 11px;cursor:pointer}
.pillbtn:disabled{opacity:.35;cursor:default}
/* --- header that fits a phone -------------------------------------------
   The old row was flex + nowrap and simply ran off the edge. The document
   cannot scroll (deliberately, so the header stays put), so anything past the
   viewport was unreachable rather than merely awkward. */
.brandwrap{display:flex;flex-direction:column;line-height:1.05;margin-right:4px}
.brandwrap .sub{font-family:ui-monospace,Menlo,monospace;font-size:9.5px;
  letter-spacing:.06em;color:var(--sig);opacity:.62;margin-top:1px;
  white-space:nowrap;max-width:120px;overflow:hidden;text-overflow:ellipsis}
#pills{display:flex;gap:8px;align-items:center;overflow-x:auto;
  scrollbar-width:none;-ms-overflow-style:none;flex:1;min-width:0;
  padding:2px 0}
#pills::-webkit-scrollbar{display:none}
.menuwrap{position:relative;flex:0 0 auto}
#menubtn{font:inherit;font-size:15px;line-height:1;background:transparent;
  color:var(--sig);border:1px solid var(--sig);border-radius:99px;
  height:26px;min-width:34px;padding:0 9px;cursor:pointer}
@media (hover:hover){#menubtn:hover{background:var(--sig);color:var(--bg)}}
#menubtn.open{background:var(--sig);color:var(--bg)}
#menu{display:none;position:absolute;right:0;top:32px;z-index:60;
  min-width:196px;background:var(--panel);border:1px solid var(--line);
  border-radius:10px;padding:5px;box-shadow:0 12px 34px rgba(0,0,0,.65)}
#menu.open{display:block}
#menu a,#menu button{display:block;width:100%;text-align:left;background:transparent;
  border:0;border-radius:7px;color:var(--fg);font:inherit;font-size:14px;
  padding:10px 12px;cursor:pointer;text-decoration:none}
#menu .sep{height:1px;background:var(--line);margin:4px 6px}
#menu button.danger{color:var(--bad)}
#menu button:disabled{opacity:.4}
@media (hover:hover){#menu a:hover,#menu button:hover{background:var(--sig);
  color:var(--bg)}#menu button.danger:hover{background:var(--bad);color:var(--bg)}}
#menu a:active,#menu button:active{background:var(--sig);color:var(--bg)}

/* --- composer ------------------------------------------------------------
   On a phone the textarea, the toggle and two buttons shared one row, leaving
   about 40% of the width for the thing you actually type into. */
@media (max-width:620px){
  footer{flex-direction:column;align-items:stretch;gap:8px}
  footer .btnrow{display:flex;gap:8px;align-items:center}
  footer .btnrow #send,footer .btnrow #sendcyc{flex:1}
  #autow{margin-right:auto}
  .brandwrap .sub{max-width:96px}
}

.pillbtn.danger{color:var(--bad);border-color:var(--bad);margin-left:14px}
@media (hover:hover){.pillbtn.danger:hover{background:var(--bad);color:var(--bg)}}
.pillbtn.danger:active{background:var(--bad);color:var(--bg)}
a.link{color:var(--sig);text-decoration:none;border-color:var(--sig)}
#log{flex:1;min-height:0;overscroll-behavior:contain;
  overflow-y:auto;padding:16px 15px 8px;display:flex;
  flex-direction:column;gap:14px;-webkit-overflow-scrolling:touch}
.msg{max-width:88%;white-space:pre-wrap;word-wrap:break-word}
/* A message that steered a cycle is marked, and stays marked. The
   instruction it created will be spent and cleared; the record of having
   given it should not disappear with it. */
.msg.user.instr{border-color:var(--sig)}
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
#autow{display:flex;align-items:center;gap:5px;font-size:11.5px;
  color:var(--dim);white-space:nowrap;cursor:pointer;user-select:none}
#autos{accent-color:var(--sig);width:15px;height:15px}
/* The steering one is outlined rather than filled: it is the deliberate
   choice, not the frequent one. */
#sendcyc{background:transparent;color:var(--sig);border:1px solid var(--sig);
  border-radius:11px;height:44px;padding:0 13px;font:inherit;font-weight:600;
  cursor:pointer;white-space:nowrap;
  transition:background .12s ease,color .12s ease}
@media (hover:hover){#sendcyc:hover{background:var(--sig);color:var(--bg)}}
#sendcyc:active{background:var(--sig);color:var(--bg)}
#sendcyc:disabled{opacity:.35}
footer{gap:7px}
@media (max-width:430px){#send,#sendcyc{padding:0 11px;font-size:13.5px}}
.think{align-self:flex-start;color:var(--dim);font-size:13.5px;
  font-family:ui-monospace,monospace}
.dot{animation:b 1.3s infinite}@keyframes b{0%,80%{opacity:.25}40%{opacity:1}}
</style></head><body>
<header>
  <a class=brandwrap href="/">
    <span class=brand>riffle</span>
    <span class=sub id=modelsub>%MODEL%</span>
  </a>
  <span id=pills>
    <span class=alarmwrap id=alarmwrap>
      <span class=pill id=p-state onclick="toggleAlarms(event)">&mdash;</span>
      <div class=alarmpanel id=alarmpanel>
        <div id=alarmlist></div>
        <div class=clearbar><button class=clearbtn onclick="clearAlarms(event)">clear</button></div>
      </div>
    </span>
    <span class=pill id=p-queue></span>
    <span class=pill id=p-caps></span>
  </span>
  <span class=menuwrap>
    <button id=menubtn onclick="toggleMenu(event)" title="controls">&#9776;</button>
    <div id=menu>
      <button id=runbtn onclick="runCycle();closeMenu()">run cycle</button>
      <button id=rsbtn onclick="restartModel();closeMenu()">restart model</button>
      <div class=sep></div>
      <a href="/history">history</a>
      <a href="/settings">settings</a>
      <div class=sep></div>
      <button id=clearbtn class=danger onclick="clearChat();closeMenu()">clear chat</button>
    </div>
  </span>
</header>
<div id=log></div>
<footer>
  <textarea id=box rows=1 placeholder="ask what it's been doing&hellip;"></textarea>
  <div class=btnrow>
    <label id=autow title="follow new messages"><input type=checkbox id=autos checked> auto</label>
    <button id=send>send</button>
    <button id=sendcyc title="also carried into the next wake cycle as a standing instruction">send to cycle</button>
  </div>
</footer>
<script>
let after = 0, busy = false, waitStart = null;
const log = document.getElementById('log'), box = document.getElementById('box'),
      send = document.getElementById('send');
const esc = s => String(s).replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
const autos = document.getElementById('autos');
try{ autos.checked = localStorage.getItem('riffle.autoscroll') !== '0'; }
catch(e){}
autos.onchange = function(){
  try{ localStorage.setItem('riffle.autoscroll', autos.checked?'1':'0'); }
  catch(e){}
};
const nearBottom = () => log.scrollHeight - log.scrollTop - log.clientHeight < 140;

function statusLine(p){
  if(p.status === 'sending')
    return '<div class=sentline><span class=spin>&#9696;</span> sending&hellip;</div>';
  if(p.status === 'executed')
    return '<div class=sentline>&#10003; Sent ' + esc(p.sent_at || '') +
           (p.ref ? ' &middot; ' + esc(p.ref) : '') + '</div>';
  if(p.status === 'failed')
    return '<div class="sentline bad">&#10005; Refused &middot; ' +
           esc(p.error || '') + '</div>';
  if(p.status === 'rejected')
    return '<div class=sentline>&#10005; Rejected ' + esc(p.sent_at || '') +
           ' &middot; not sent</div>';
  return '<div class=when>' + esc(p.status || '') + '</div>';
}
function toggleMenu(e){
  e.stopPropagation();
  const m = document.getElementById('menu');
  const b = document.getElementById('menubtn');
  const open = !m.classList.contains('open');
  m.classList.toggle('open', open);
  b.classList.toggle('open', open);
}
function closeMenu(){
  document.getElementById('menu').classList.remove('open');
  document.getElementById('menubtn').classList.remove('open');
}
// Any tap outside closes it. A menu that stays open behind whatever you tap
// next is worse than no menu on a screen this size.
document.addEventListener('click', function(e){
  const w = document.querySelector('.menuwrap');
  if(w && !w.contains(e.target)) closeMenu();
});

function toggleAlarms(e){
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

function render(m){
  let el = document.getElementById('m'+m.id);
  if(!el){ el = document.createElement('div'); el.id = 'm'+m.id; log.appendChild(el); }
  if(m.role === 'proposal'){
    const p = m.meta || {};
    const _csig = JSON.stringify([p.status, p.sent_at, p.ref, p.error,
                                  m.content.length]);
    if(el.dataset.sig === _csig) return;
    el.dataset.sig = _csig;
    el.className = 'card';
    el.innerHTML = '<h4>' + esc(p.kind||'action') + ' &middot; drive ' + esc(p.drive||'') +
      '</h4><div class=why>' + esc(m.content) + '</div><pre>' + esc(p.payload||'') + '</pre>' +
      (p.status === 'queued'
        ? '<div class=btns><button class=go onclick="decide('+p.action_id+',\'approve\',this)">send it</button>'+
          '<button class=no onclick="decide('+p.action_id+',\'reject\',this)">reject</button></div>'
        : statusLine(p));
    return;
  }
  el.className = 'msg ' + (m.role==='user'?'user':m.role==='report'?'report':
                           m.role==='error'?'err':'agent')
    + (m.role==='user' && m.meta && m.meta.instruct ? ' instr' : '');
  // Rebuilding innerHTML throws away the scroll position of any <pre>
  // inside, and proposal cards are re-sent every poll so their state
  // can change. Draw only when what we would draw is different.
  const _sig = m.role + '|' + m.done + '|' + m.content.length;
  if(el.dataset.sig === _sig) return;
  el.dataset.sig = _sig;
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
    q.textContent = d.queued + ' waiting';
    q.className = 'pill' + (d.queued ? ' hot' : '');
    document.getElementById('p-caps').textContent = d.caps;
    renderAlarms(d.alarms_list);
    const st = document.getElementById('p-state');
    st.textContent = d.generating ? 'thinking'
      : (d.alarms ? d.alarms + ' alarm' + (d.alarms === 1 ? '' : 's') : 'idle');
    // The wrapper owns whether the panel is open. Re-derive `pinned` from
    // it rather than rebuilding className blind, which used to drop the fill
    // every poll while the panel stayed open.
    const openNow = document.getElementById('alarmwrap').classList.contains('pinned');
    st.className = 'pill' + (d.alarms ? ' bad' : d.generating ? ' hot' : '')
      + (openNow && d.alarms ? ' pinned' : '');
    busy = d.generating; send.disabled = busy;
    document.getElementById('sendcyc').disabled = busy;
    const rb = document.getElementById('runbtn');
    rb.disabled = !!d.cycle_running || !!d.model_restarting;
    const sb = document.getElementById('rsbtn');
    sb.disabled = !!d.model_restarting || !!d.cycle_running || busy;
    sb.textContent = d.model_restarting ? 'restarting\u2026' : 'restart model';
    rb.textContent = d.cycle_running ? 'cycle running…' : 'run cycle';
    let t = document.getElementById('think');
    if(busy){
      if(!t){ t = document.createElement('div'); t.id='think'; t.className='think';
              log.appendChild(t); waitStart = waitStart || Date.now(); }
      t.textContent = 'thinking\u2026 ' + Math.round((Date.now()-waitStart)/1000) +
                      's  (minutes are normal on this box)';
    } else if(t){ t.remove(); waitStart = null; }
    // Only follow if the toggle is on AND you were already at the
    // bottom. Either condition alone would yank the view while you
    // are reading something further up.
    if(stick && autos.checked) log.scrollTop = log.scrollHeight;
  }catch(e){}
  setTimeout(poll, busy ? 900 : 2500);
}

async function submit(instruct){
  const q = box.value.trim(); if(!q || busy) return;
  box.value=''; box.style.height='auto'; busy=true;
  send.disabled = true; document.getElementById('sendcyc').disabled = true;
  waitStart = Date.now();
  await fetch('/api/send', {method:'POST', headers:{'Content-Type':'application/json'},
                            body: JSON.stringify({q:q, instruct: !!instruct})});
  log.scrollTop = log.scrollHeight;
}
async function decide(id, verdict, btn){
  // Swap the buttons out immediately. The round trip includes an HTTPS call to
  // the square, and a button that stays live while the work happens invites a
  // second press.
  if(btn){
    const box = btn.parentElement;
    box.outerHTML = verdict === 'approve'
      ? '<div class=sentline><span class=spin>&#9696;</span> sending&hellip;</div>'
      : '<div class=sentline>&#10005; Rejected &middot; not sent</div>';
  }
  await fetch('/api/decide', {method:'POST', headers:{'Content-Type':'application/json'},
                              body: JSON.stringify({id:id, verdict:verdict})});
}
async function clearChat(){
  if(!confirm('Clear the chat?\n\nEverything moves to the history page. '
            + 'Nothing is deleted, and the agent still remembers the '
            + 'conversation.')) return;
  await fetch('/api/clear-chat', {method:'POST',
    headers:{'Content-Type':'application/json'}, body:'{}'});
  document.getElementById('log').innerHTML = '';
  after = 0;
}
async function restartModel(){
  if(!confirm('Restart the composer?\n\nIt re-reads 20.6 GB from disk and will '
            + 'not answer for a couple of minutes. Anything generating right now '
            + 'is lost.')) return;
  const b = document.getElementById('rsbtn');
  b.disabled = true; b.textContent = 'restarting\u2026';
  const r = await fetch('/api/restart-model', {method:'POST',
    headers:{'Content-Type':'application/json'}, body:'{}'});
  const d = await r.json();
  if(d.error){ alert(d.error); b.disabled = false; b.textContent = 'restart model'; }
}
async function runCycle(){
  const b = document.getElementById('runbtn');
  b.disabled = true; b.textContent = 'running…';
  await fetch('/api/run-cycle', {method:'POST', headers:{'Content-Type':'application/json'},
                                 body:'{}'});
}
send.onclick = function(){ submit(false); };
document.getElementById('sendcyc').onclick = function(){ submit(true); };
box.addEventListener('input', function(){ box.style.height='auto';
  box.style.height = Math.min(box.scrollHeight,150) + 'px'; });
box.addEventListener('keydown', function(e){
  if(e.key==='Enter' && !e.shiftKey && !matchMedia('(pointer:coarse)').matches){
    // Ctrl+Enter steers. The deliberate action gets the deliberate keystroke.
    e.preventDefault(); submit(e.ctrlKey || e.metaKey); }});
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
            # Substituted at serve time: PAGE is a module constant and the
            # model id lives in config.
            b = PAGE.replace("%MODEL%",
                             str(self.cfg.get("model_id", ""))[:40]).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            return self.wfile.write(b)
        if u.path == "/act":
            b = ACT_PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            return self.wfile.write(b)
        if u.path == "/api/action":
            q = urllib.parse.parse_qs(u.query)
            try:
                aid = int(q.get("id", ["0"])[0])
            except ValueError:
                return self._json({"error": "bad id"}, 400)
            if q.get("t", [""])[0] != link_token(self.state, aid):
                return self._json({"error": "link is not valid"}, 403)
            a = self.state.action(aid)
            if not a:
                return self._json({"error": "no such proposal"}, 404)
            return self._json({"id": a["id"], "kind": a["kind"], "drive": a["drive"],
                               "status": a["status"], "rationale": a["rationale"],
                               "payload": json.dumps(json.loads(a["payload"]), indent=2)})
        if u.path == "/history":
            b = history_page(self.state).encode()
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
        if self.path.startswith(("/api/goal/", "/api/memory/",
                                 "/api/policy/", "/api/project/",
                                 "/api/instruction/")):
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
            steering = bool(body.get("instruct"))
            self.state.say("user", q, {"instruct": steering})
            # Anything you type is also an instruction the next cycle will see.
            # The cycle prompt never contained the conversation, which is why
            # asking for a project on #1916 produced one on something else.
            # Only when you asked for it. Turning every question into a
            # directive meant the next cycle woke carrying idle curiosity as a
            # mandate.
            if steering:
                from agent.state import add_instruction
                add_instruction(self.state, q,
                                int((self.cfg.get("instructions") or {})
                                    .get("default_cycles", 1)))
                self.state.log("you sent an instruction to the next cycle: "
                               + q[:160])
            self.worker.submit(q, utcnow()[:10])
            return self._json({"ok": True})
        if u.path == "/api/clear-alarms":
            return self._json(self.clear_alarms())
        if u.path == "/api/clear-chat":
            return self._json(self.clear_chat())
        if u.path == "/api/restart-model":
            return self._json(self.restart_model())
        if u.path == "/api/run-cycle":
            return self._json(self.run_cycle())
        if u.path == "/api/decide":
            return self._json(self.decide(int(body.get("id", 0)),
                                          str(body.get("verdict", "reject"))))
        self._json({"error": "not found"}, 404)

    # ---- view model ------------------------------------------------------
    def snapshot(self, after):
        s, cfg = self.state, self.cfg
        # Ask the worker, not the database. A row left open with nobody writing
        # to it is a ghost, and the page used to spin on it forever. Do this
        # BEFORE reading the rows, or this poll still reports the stale one as
        # open and the client waits another cycle for the truth.
        w = self.worker
        generating = bool(getattr(w, "busy", False)) or w.depth() > 0
        if not generating and s.pending_generation() is not None:
            chat.close_orphans(s, "interrupted")
        day = utcnow()[:10]
        out = []
        # A streaming row must be re-sent on every poll, so the client only
        # advances its cursor past rows marked done. Advancing past a partial
        # row is how you end up with a reply that stops mid-sentence forever.
        for m in s.messages(after):
            out.append({"id": m["id"], "role": m["role"], "content": m["content"],
                        "meta": json.loads(m["meta"]) if m["meta"] else {},
                        "done": bool(m["done"]), "ts": m["ts"]})
        # Acknowledged alarms stay in the journal; the badge just stops
        # counting them. Clearing is a watermark, not a delete.
        seen = int(s.note("alarms_acked_to") or 0)
        arows = s.db.execute(
            "SELECT id, ts, level, drive, text FROM journal"
            " WHERE level IN ('alarm','error') AND id > ?"
            " ORDER BY id DESC LIMIT 100", (seen,)).fetchall()
        alarms = len(arows)
        alarm_list = [{"id": r["id"], "ts": r["ts"], "level": r["level"],
                       "drive": r["drive"], "text": r["text"]} for r in arows]
        caps = " ".join(f"{k[0]}{cfg['caps'][k] - s.cap_used(day, k)}"
                        for k in sorted(cfg["caps"]))
        # A card that changes state is by definition older than the
        # client's cursor, so it would never be re-fetched. Re-send recent
        # proposal cards every poll; there are only ever a handful, and the
        # client renders by id so they update in place.
        have = {m["id"] for m in out}
        for m in s.db.execute("SELECT * FROM messages WHERE role='proposal'"
                              " AND archived_at IS NULL"
                              " ORDER BY id DESC LIMIT 25"):
            if m["id"] not in have:
                out.append({"id": m["id"], "role": m["role"], "content": m["content"],
                            "meta": json.loads(m["meta"]) if m["meta"] else {},
                            "done": True, "ts": m["ts"]})
        out.sort(key=lambda x: x["id"])

        return {"messages": out, "queued": len(s.queued()),
                "alarms_list": alarm_list,
                "model_restarting": type(self)._restarting,
                "cycle_running": type(self)._cycle_running,
                "generating": generating,
                "alarms": alarms, "caps": caps}

    _cycle_lock = __import__("threading").Lock()
    _cycle_running = False

    _restart_lock = __import__("threading").Lock()
    _restarting = False

    _sched_started = False

    @classmethod
    def start_scheduler(cls):
        """Honour the agent's requests for extra cycles.

        Deliberately here rather than in the cycle: the agent writes a request
        into the database and something outside it decides whether to act. It
        cannot reach this loop, and it cannot start a cycle directly.
        """
        if cls._sched_started:
            return
        cls._sched_started = True

        def loop():
            import datetime as _dt
            import time as _t
            while True:
                _t.sleep(30)
                try:
                    st = cls.state
                    req = st.note("cycle_requested_at")
                    if not req:
                        continue
                    e = (cls.cfg.get("extra_cycles") or {})
                    gap = int(e.get("min_gap_seconds", 300))
                    last = st.note("extra_cycle_ran_at")
                    now = _dt.datetime.now(_dt.timezone.utc)
                    if last:
                        try:
                            if (now - _dt.datetime.fromisoformat(last)
                                    ).total_seconds() < gap:
                                continue
                        except ValueError:
                            pass
                    if cls._cycle_running or getattr(cls.worker, "busy", False):
                        continue
                    st.note("cycle_requested_at", "")
                    st.note("extra_cycle_ran_at", now.isoformat())
                    why = st.note("cycle_requested_why") or ""
                    st.log("starting the extra cycle it asked for: " + why[:160])
                    cls().run_cycle() if False else _run_cycle_detached(cls)
                except Exception as exc:
                    try:
                        cls.state.log("scheduler error: " + str(exc)[:200],
                                      level="warn")
                    except Exception:
                        pass

        _th.Thread(target=loop, daemon=True).start()

    _tel_started = False

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

    def clear_chat(self):
        """Archive everything currently visible. Nothing is deleted."""
        s = self.state
        # Microseconds, not seconds: two clears inside the same second would
        # otherwise share a stamp and merge into one batch in history.
        import datetime as _dt
        stamp = _dt.datetime.now(_dt.timezone.utc).isoformat()
        cur = s.db.execute(
            "UPDATE messages SET archived_at=? WHERE archived_at IS NULL", (stamp,))
        s.db.commit()
        n = cur.rowcount
        s.log(f"you cleared the chat; {n} message(s) moved to history")
        return {"ok": True, "archived": n}

    def restart_model(self):
        """Restart llama-composer and report back when it answers again."""
        cls = type(self)
        w = self.worker
        if getattr(w, "busy", False) or w.depth() > 0 or cls._cycle_running:
            return {"error": "something is generating; wait for it to finish"}
        with cls._restart_lock:
            if cls._restarting:
                return {"error": "already restarting"}
            cls._restarting = True

        def run():
            import time as _t
            import urllib.request as _u
            t0 = _t.time()
            self.state.say("report", "Restarting the composer. It has to read "
                                     "20.6 GB off disk, so give it a couple of "
                                     "minutes.")
            try:
                # Ask systemd rather than becoming root. riffle-restart-composer.path
                # is watching this file; the matching service deletes it and does
                # the restart. The dashboard needs no privilege of any kind.
                open("/var/lib/riffle/restart-composer.request", "w").close()
            except Exception as e:
                self.state.say("error", f"could not signal a restart: {e}")
                return
            try:
                # Wait for it to answer rather than assuming. A unit that has
                # "started" has only forked; the model is still loading.
                for _ in range(200):
                    _t.sleep(2)
                    try:
                        with _u.urlopen("http://127.0.0.1:8080/health",
                                        timeout=4) as resp:
                            if resp.status == 200:
                                self.state.say(
                                    "report", f"Composer is back, "
                                              f"{int(_t.time() - t0)}s. Fresh "
                                              f"KV cache and slot state.")
                                self.state.log("you restarted the composer")
                                return
                    except Exception:
                        continue
                self.state.say("error", "the composer did not answer /health "
                                        "within 400s; check "
                                        "`journalctl -u llama-composer`.")
            except Exception as e:
                self.state.say("error", f"restart failed: {e}")
            finally:
                cls._restarting = False

        _th.Thread(target=run, daemon=True).start()
        return {"ok": True}

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

    def clear_alarms(self):
        """Acknowledge every alarm up to now. The journal itself is untouched."""
        s = self.state
        row = s.db.execute(
            "SELECT MAX(id) m FROM journal WHERE level IN ('alarm','error')").fetchone()
        top = row["m"] or 0
        s.note("alarms_acked_to", top)
        s.log(f"you cleared the alarm badge up to journal id {top}; "
              f"the entries themselves are still on record")
        return {"ok": True, "acked_to": top}

    def _local_time(self):
        import datetime as _dt
        tz = (self.cfg.get("notify") or {}).get("timezone", "America/Los_Angeles")
        try:
            from zoneinfo import ZoneInfo
            now = _dt.datetime.now(ZoneInfo(tz))
        except Exception:
            now = _dt.datetime.now()
        return now.strftime("%-I:%M %p, %b %-d")

    def _card_for(self, aid):
        """Find the chat card that announced this action, so it can be updated
        in place rather than answered by a second card beside it."""
        for m in self.state.db.execute(
                "SELECT id, meta FROM messages WHERE role='proposal'"
                " ORDER BY id DESC LIMIT 200"):
            try:
                if (json.loads(m["meta"]) or {}).get("action_id") == aid:
                    return m["id"], json.loads(m["meta"])
            except Exception:
                continue
        return None, None

    def _update_card(self, aid, **fields):
        mid, meta = self._card_for(aid)
        if mid is None:
            return
        meta.update(fields)
        self.state.db.execute("UPDATE messages SET meta=? WHERE id=?",
                              (json.dumps(meta), mid))
        self.state.db.commit()

    def decide(self, aid, verdict):
        s = self.state
        a = s.action(aid)
        if not a or a["status"] != "queued":
            return {"error": "not queued"}
        payload = json.loads(a["payload"])

        if verdict != "approve":
            s.set_status(aid, "rejected")
            self._update_card(aid, status="rejected", sent_at=self._local_time())
            s.log(f"you rejected {a['kind']} #{aid}", drive=a["drive"])
            return {"ok": True}

        # Reflexive actions change the agent, not the square. Approving one must
        # never become an HTTP POST to the registry.
        if a["kind"] in ("adjust_drive", "add_goal", "remember"):
            try:
                if a["kind"] == "adjust_drive":
                    old, new = goals.set_weight(s, self.cfg, payload["name"],
                                                payload["weight"], "you",
                                                payload.get("reason", "approved by operator"))
                    ref = f"{payload['name']} {old} -> {new}"
                elif a["kind"] == "add_goal":
                    goals.add(s, self.cfg, payload["name"], payload["weight"],
                              payload["description"], "you",
                              payload.get("reason", "approved by operator"))
                    ref = f"goal '{payload['name']}'"
                else:
                    memory.remember(s, payload["text"], kind="self",
                                    source=f"action:{aid}", pinned=payload.get("pinned"))
                    ref = "remembered"
                s.set_status(aid, "executed", {"applied": "locally"})
                self._update_card(aid, status="executed", sent_at=self._local_time(),
                                  ref=ref)
                return {"ok": True}
            except goals.Rejected as e:
                s.set_status(aid, "failed", {"error": str(e)})
                self._update_card(aid, status="failed", error=str(e)[:200])
                return {"error": str(e)}

        # Board actions: send in the background so the page is not held open
        # across an HTTPS round trip, then wake a cycle so riffle sees that its
        # own action landed and can react to whatever follows.
        self._update_card(aid, status="sending")

        def worker():
            data = os.path.expanduser(self.cfg["data_dir"])
            secret = open(os.path.join(data,
                                       f"{self.cfg['handle']}.secret")).read().strip()
            try:
                resp = execute(Writer(self.cfg["base"], secret), a["kind"], payload)
                s.set_status(aid, "executed", resp)
                s.cap_bump(utcnow()[:10], a["kind"])
                ref = resp.get("id") or resp.get("post_id") or ""
                self._update_card(aid, status="executed", sent_at=self._local_time(),
                                  ref=(f"#{ref}" if ref else ""))
                s.log(f"you approved and sent {a['kind']} #{aid}", drive=a["drive"])
                self.run_cycle()
            except HttpError as e:
                s.set_status(aid, "failed", {"error": str(e)})
                self._update_card(aid, status="failed", error=str(e)[:200])
                s.log(f"the registry refused {a['kind']} #{aid}: {e}",
                      level="error", drive=a["drive"])

        _th.Thread(target=worker, daemon=True).start()
        return {"ok": True, "status": "sending"}

    def _decide_old_unused(self, aid, verdict):
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
    from agent import policy as _policy
    _policy.ensure(st, cfg)
    orphans = chat.close_orphans(st)
    if orphans:
        print(f"closed {orphans} interrupted reply row(s) from a previous run")
        st.log(f"startup: closed {orphans} reply row(s) left open by a restart")
    Handler.cfg, Handler.state = cfg, st
    Handler.worker = chat.Worker(st, cfg)
    Handler.worker.start()
    Handler.start_scheduler()
    Handler.start_telemetry()
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
<title>riffle — settings</title><style>
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
.mem.gone{opacity:.42}

.act{display:grid;grid-template-columns:1fr auto;gap:10px;align-items:center;
  padding:9px 0;border-bottom:1px solid var(--line)}
.act:last-child{border-bottom:0}
.act .n{font-family:ui-monospace,Menlo,monospace;font-size:13.5px}
.act .n small{display:block;color:var(--dim);font-size:11px;
  font-family:-apple-system,sans-serif;letter-spacing:0;text-transform:none}
.seg{display:inline-flex;border:1px solid var(--line);border-radius:99px;
  overflow:hidden}
.seg button{background:transparent;color:var(--dim);border:0;border-radius:0;
  padding:5px 12px;font-size:12px;font-weight:600;cursor:pointer}
.seg button.on[data-m=auto]{background:var(--sig);color:var(--bg)}
.seg button.on[data-m=queue]{background:var(--dim);color:var(--bg)}
.seg button.on[data-m=never]{background:var(--bad);color:var(--bg)}
@media (hover:hover){.seg button:hover{color:var(--fg)}}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0}
.chip{font-family:ui-monospace,monospace;font-size:11px;padding:3px 9px;
  border:1px solid var(--line);border-radius:99px;color:var(--dim);cursor:pointer;
  user-select:none}
.chip.only{border-color:var(--sig);color:var(--bg);background:var(--sig)}
.chip.never{border-color:var(--bad);color:var(--bg);background:var(--bad)}
.warn{color:var(--bad);font-size:12.5px;margin:6px 0}
.pj{border-left:3px solid var(--sig);padding-left:12px;margin-bottom:14px}
.pj.done{border-left-color:var(--line);color:var(--dim)}
.pj h3{margin:0 0 3px;font-size:15px}
.pj .q{color:var(--dim);font-size:13.5px;margin-bottom:6px}
.pj .rd{font-family:ui-monospace,monospace;font-size:12px;color:var(--dim);
  padding:3px 0}
.pj .rd b{color:var(--fg)}

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
.mem .k{font-family:ui-monospace,monospace;font-size:10.5px;text-transform:uppercase;
  letter-spacing:.07em;color:var(--sig)}

a.brand{font-family:ui-monospace,Menlo,monospace;letter-spacing:.07em;
  color:var(--sig);text-decoration:none;font-weight:700;padding:2px 6px;
  border-radius:6px;margin-left:-6px;transition:background .12s ease,color .12s ease}
@media (hover:hover){a.brand:hover{background:var(--sig);color:var(--bg)}}
a.brand:active{background:var(--sig);color:var(--bg)}
/* --- shared control styling, mirrored from the chat page ------------------
   These two pages have separate <style> blocks, so rules added to one stop at
   its edge. Kept in sync by hand; if a third page ever appears, factor this
   into a served stylesheet instead of copying it again. */
button,a.link,.clearbtn{transition:background .12s ease,color .12s ease,
  border-color .12s ease}
@media (hover:hover){
  button:hover{background:var(--fg);color:var(--bg)}
  button.ghost:hover{background:var(--dim);color:var(--bg);border-color:var(--dim)}
  button.warn:hover{background:var(--bad);color:var(--bg)}
  a.link:hover{background:var(--sig);color:var(--bg)}
}
button:active{background:var(--fg);color:var(--bg)}
button.ghost:active{background:var(--dim);color:var(--bg);border-color:var(--dim)}
button.warn:active{background:var(--bad);color:var(--bg)}
a.link:active{background:var(--sig);color:var(--bg)}

/* One shape for the header link and the inline tags, matching the chat page. */
a.link{display:inline-flex;align-items:center;justify-content:center;
  height:23px;box-sizing:border-box;font-size:11.5px;line-height:1;
  padding:0 11px;border-radius:99px;white-space:nowrap}
.tag{display:inline-flex;align-items:center;height:19px;box-sizing:border-box;
  padding:0 9px;line-height:1}

/* The range slider and text inputs had no focus state, which on a page whose
   whole job is changing values is worth having. */
input[type=text]:focus,input[type=number]:focus,textarea:focus{
  outline:0;border-color:var(--sig)}
input[type=range]:focus-visible{outline:2px solid var(--sig);outline-offset:3px}
</style></head><body>
<header><a class=brand href="/">riffle</a><span style="flex:1"></span><a class=link href="/">chat</a></header>
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


<h2>actions &mdash; what it may do without asking</h2>
<div class=note><b>auto</b> happens. <b>queue</b> waits for your tap in the
chat. <b>never</b> means it cannot even propose it, and the refusal shows up as
a wasted cycle. Actions marked <span style="color:var(--sig)">&#9679;</span>
reach the square, where strangers read them.</div>
<div class=g id=actions></div>

<h2>drives &mdash; which actions each one may choose</h2>
<div class=note>Tap an action to cycle it: neutral &rarr; <b>only</b> (gold,
the drive may propose nothing else) &rarr; <b>never</b> (red) &rarr; neutral.
<b>only</b> is rarely what you want; a drive restricted to one action spends
every other cycle refusing itself.</div>
<div class=g id=restrict></div>


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

<h2>instructions &mdash; what you told it</h2>
<div class=note>Everything you type in chat is carried into the next cycle as
data. One cycle by default; raise the count for something you want it to keep
working on. An instruction is spent when a cycle <b>reads</b> it, whether or
not that cycle achieved anything.</div>
<div class=g id=instructions></div>

<h2>projects</h2>
<div class=note>A post has to come out of one of these. The bar is notes,
distinct sources, a draft, and an objection to its own argument.</div>
<div class=g id=projects></div>

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


const ACTS = ["post", "comment", "vote", "tag", "flag", "seal", "listing_submission", "read_thread", "read_more", "request_cycle", "open_project", "project_note", "close_project", "adjust_drive", "add_goal", "remember"];
let pol = null;


async function loadTel(){
  const d = await (await fetch('/api/telemetry')).json();
  document.getElementById('telcount').textContent =
    d.entries.length + ' entries, ' + d.dumps + ' dump' + (d.dumps===1?'':'s');
  document.getElementById('telbox').innerHTML = d.entries.map(function(e){
    const m = e.summary || {};
    return '<div class="tel' + (e.kind==='dump'?' dump':'') +
      '" onclick="this.classList.toggle(\'open\')">' +
      '<span class=k>' + esc(e.kind) + '</span> ' +
      '<span class=t>' + esc(e.ts.slice(5,19).replace('T',' ')) + '</span> ' +
      esc(e.label) + ' &middot; ' + esc(m.line || '') +
      '<pre>' + esc(e.pretty) + '</pre></div>';
  }).join('') || '<div class=alarmempty>nothing recorded yet</div>';
}

async function loadPolicy(){
  pol = await (await fetch('/api/policy')).json();
  document.getElementById('actions').innerHTML = ACTS.map(function(a){
    const m = pol.modes[a] || 'queue';
    const sq = pol.square.indexOf(a) >= 0
      ? '<span style="color:var(--sig)">&#9679;</span> ' : '';
    return '<div class=act><div class=n>' + sq + esc(a) +
      (pol.notes[a] ? '<small>' + esc(pol.notes[a]) + '</small>' : '') +
      '</div><div class=seg>' +
      ['auto','queue','never'].map(function(x){
        return '<button data-m="' + x + '" class="' + (m===x?'on':'') +
          '" onclick="setMode(\'' + a + '\',\'' + x + '\')">' + x + '</button>';
      }).join('') + '</div></div>';
  }).join('');

  document.getElementById('restrict').innerHTML = pol.drives.map(function(d){
    const r = pol.restrictions[d] || {only:[],never:[]};
    const chips = ACTS.map(function(a){
      const cls = r.only.indexOf(a)>=0 ? 'chip only'
                : r.never.indexOf(a)>=0 ? 'chip never' : 'chip';
      return '<span class="' + cls + '" data-d="' + d + '" data-a="' + a +
             '" onclick="cycleChip(this)">' + esc(a) + '</span>';
    }).join('');
    const warn = r.only.length
      ? '<div class=warn>&#9888; this drive may ONLY propose ' +
        esc(r.only.join(', ')) + ' &mdash; everything else it thinks of is refused</div>'
      : '';
    return '<div style="margin-bottom:16px"><div class=gn>' + esc(d) + '</div>' +
      warn + '<div class=chips>' + chips + '</div>' +
      '<button onclick="saveRestrict(\'' + d + '\')">save ' + esc(d) + '</button></div>';
  }).join('');

  document.getElementById('instructions').innerHTML = pol.instructions.length
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

  document.getElementById('projects').innerHTML = pol.projects.length
    ? pol.projects.map(function(p){
        const reads = (p.reads||[]).map(function(r){
          return '<div class=rd>#' + r.post_id + ' <b>' + esc(r.title) +
            '</b> &middot; ' + r.seen + ' of ' + r.total + ' replies read' +
            (r.left ? ', <span style="color:var(--sig)">' + r.left +
             ' unread</span>' : '') + '</div>';
        }).join('');
        return '<div class="pj' + (p.status==='active'?'':' done') + '">' +
          '<h3>' + esc(p.title) + '</h3><div class=q>' + esc(p.question) + '</div>' +
          '<div class=legend><span>' + p.notes + ' notes &middot; ' + p.sources +
          ' sources &middot; ' + p.age + 'h &middot; ' + esc(p.status) + '</span>' +
          '<span' + (p.ready?' style="color:var(--sig)"':'') + '>' +
          (p.ready?'ready to post':'not ready') + '</span></div>' + reads +
          (p.status==='active'
            ? '<div class=ctl><button class=warn2 onclick="closeProject()">close it</button></div>'
            : '') + '</div>';
      }).join('')
    : '<div style="color:var(--dim)">no projects yet</div>';
}
async function setMode(kind, mode){
  await api('/api/policy/mode', {kind:kind, mode:mode});
  await loadPolicy();
}
function cycleChip(el){
  el.className = el.className === 'chip' ? 'chip only'
               : el.className === 'chip only' ? 'chip never' : 'chip';
}
async function saveRestrict(d){
  const only = [], never = [];
  document.querySelectorAll('[data-d="' + d + '"]').forEach(function(el){
    if(el.className.indexOf('only')>=0) only.push(el.dataset.a);
    else if(el.className.indexOf('never')>=0) never.push(el.dataset.a);
  });
  await api('/api/policy/restrict', {drive:d, only:only, never:never});
  await loadPolicy();
}
async function setCycles(id){
  await api('/api/instruction/cycles',
            {id:id, cycles:+document.getElementById('ic'+id).value});
  await loadPolicy();
}
async function clearInstr(){
  if(!confirm('Clear every live instruction?')) return;
  await api('/api/instruction/clear', {});
  await loadPolicy();
}
async function closeProject(){
  if(!confirm('Close the open project? Its notes and reads are kept.')) return;
  await api('/api/project/close', {});
  await loadPolicy();
}

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
    `<div class="mem${m.expired?' gone':''}"><span class=k>${esc(m.tier)}` +
      `${m.pinned?' · pinned':''}${m.expired?' · expired':''}</span>
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
load(); loadPolicy(); loadTel();
</script></body></html>"""


ACT_PAGE = r"""<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>riffle &mdash; review</title><style>
:root{--bg:#12140f;--panel:#181b14;--fg:#e8e6db;--dim:#8b8878;--line:#2b2f24;
      --sig:#c8a44a;--bad:#c4553d}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);padding:18px;
  font:15.5px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  max-width:640px;margin:0 auto}
h1{font-family:ui-monospace,Menlo,monospace;font-size:13px;letter-spacing:.09em;
  text-transform:uppercase;color:var(--sig);margin:6px 0 16px}
.card{background:var(--panel);border:1px solid var(--line);
  border-left:3px solid var(--sig);border-radius:10px;padding:15px}
.k{font-family:ui-monospace,monospace;font-size:13px;letter-spacing:.06em;
  text-transform:uppercase;color:var(--sig)}
.why{margin:9px 0 12px;color:var(--fg)}
pre{white-space:pre-wrap;word-break:break-word;background:#0e100b;border-radius:7px;
  padding:11px;font-size:12.5px;max-height:46vh;overflow:auto;margin:0 0 14px}
.btns{display:flex;gap:10px}
button{flex:1;font:inherit;font-weight:600;border:0;border-radius:9px;padding:13px;
  cursor:pointer;transition:background .12s ease,color .12s ease}
.go{background:var(--sig);color:var(--bg)}
.no{background:transparent;color:var(--bad);border:1px solid var(--bad)}
@media (hover:hover){.go:hover{background:var(--fg)}
  .no:hover{background:var(--bad);color:var(--bg)}}
.go:active{background:var(--fg)}.no:active{background:var(--bad);color:var(--bg)}
.done{padding:15px;text-align:center;color:var(--dim);
  font-family:ui-monospace,monospace;font-size:13.5px}
a.back{display:block;text-align:center;margin-top:18px;color:var(--sig);
  text-decoration:none;font-size:13px}
</style></head><body>
<h1>riffle wants your decision</h1>
<div id=body class=card>loading&hellip;</div>
<a class=back href="/">open the full console</a>
<script>
const P = new URLSearchParams(location.search);
const esc = s => String(s==null?'':s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
async function load(){
  const r = await fetch('/api/action?' + P.toString());
  const d = await r.json();
  const b = document.getElementById('body');
  if(d.error){ b.innerHTML = '<div class=done>' + esc(d.error) + '</div>'; return; }
  if(d.status !== 'queued'){
    b.innerHTML = '<div class=done>Already ' + esc(d.status) + '. Nothing to do.</div>';
    return;
  }
  b.innerHTML = '<div class=k>' + esc(d.kind) + ' &middot; ' + esc(d.drive) + '</div>' +
    '<div class=why>' + esc(d.rationale) + '</div><pre>' + esc(d.payload) + '</pre>' +
    '<div class=btns><button class=go onclick="go(\'approve\')">send it</button>' +
    '<button class=no onclick="go(\'reject\')">reject</button></div>';
}
async function go(v){
  document.getElementById('body').innerHTML =
    '<div class=done>' + (v === 'approve' ? 'sending&hellip;' : 'rejected') + '</div>';
  await fetch('/api/decide', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({id:+P.get('id'), verdict:v})});
  setTimeout(function(){
    document.getElementById('body').innerHTML =
      '<div class=done>' + (v === 'approve' ? '&#10003; sent' : '&#10005; not sent') +
      '</div>'; }, 1200);
}
load();
</script></body></html>"""


def link_token(state, aid):
    """HMAC so a review link cannot be found by guessing an id."""
    import hmac
    import hashlib
    import secrets
    sec = state.note("notify_link_secret")
    if not sec:
        sec = secrets.token_hex(32)
        state.note("notify_link_secret", sec)
    return hmac.new(sec.encode(), str(aid).encode(), hashlib.sha256).hexdigest()[:20]


# --------------------------------------------------------------------------
# History: everything that has been cleared out of the chat, oldest first.
# The stylesheet is lifted from the chat page at import time rather than
# copied, so the two can never drift.
# --------------------------------------------------------------------------

def _chat_css():
    i = PAGE.index("<style>") + len("<style>")
    return PAGE[i:PAGE.index("</style>", i)]


HISTORY_EXTRA = """
.batch{display:flex;align-items:center;gap:12px;margin:26px 0 6px;color:var(--dim);
  font-family:ui-monospace,Menlo,monospace;font-size:11.5px;letter-spacing:.06em;
  text-transform:uppercase}
.batch:before,.batch:after{content:"";flex:1;height:1px;background:var(--line)}
#log{padding-bottom:40px}
.empty{color:var(--dim);text-align:center;padding:40px 0;font-size:14px}
"""


def history_page(state):
    rows = state.db.execute(
        "SELECT * FROM messages WHERE archived_at IS NOT NULL"
        " ORDER BY archived_at, id").fetchall()
    out, batch = [], None
    for m in rows:
        if m["archived_at"] != batch:
            batch = m["archived_at"]
            n = sum(1 for r in rows if r["archived_at"] == batch)
            out.append(f"<div class=batch>cleared {_esc(_pretty(batch))} "
                       f"&middot; {n} message{'' if n == 1 else 's'}</div>")
        out.append(_render_static(m))
    body = "".join(out) or "<div class=empty>nothing has been cleared yet</div>"
    return (f"<!doctype html><html><head><meta charset=utf-8>"
            f"<meta name=viewport content='width=device-width,initial-scale=1,"
            f"viewport-fit=cover'><title>riffle &mdash; history</title>"
            f"<style>{_chat_css()}{HISTORY_EXTRA}</style></head><body>"
            f"<header><a class=brand href=\"/\">riffle</a>"
            f"<span class=pill>{len(rows)} archived</span>"
            f"<span style='flex:1'></span>"
            f"<a class=link href=\"/\">chat</a>"
            f"<a class=link href=\"/goals\">goals</a></header>"
            f"<div id=log>{body}</div></body></html>")


def _pretty(ts):
    import datetime as _dt
    try:
        t = _dt.datetime.fromisoformat((ts or "").replace("Z", "+00:00"))
        from zoneinfo import ZoneInfo
        tz = (Handler.cfg.get("notify") or {}).get("timezone",
                                                   "America/Los_Angeles")
        return t.astimezone(ZoneInfo(tz)).strftime("%-I:%M %p, %b %-d")
    except Exception:
        return ts or ""


def _esc(x):
    import html as _h
    return _h.escape(str(x if x is not None else ""))


def _render_static(m):
    """Same shapes as the live chat, minus the controls. A card in history is
    a record of a decision, so its buttons are gone and its outcome is text."""
    meta = json.loads(m["meta"]) if m["meta"] else {}
    if m["role"] == "proposal":
        status = meta.get("status", "")
        line = {"executed": "&#10003; sent " + _esc(meta.get("sent_at", "")),
                "rejected": "&#10005; rejected " + _esc(meta.get("sent_at", "")),
                "failed": "&#10005; refused &middot; " + _esc(meta.get("error", "")),
                }.get(status, _esc(status))
        return (f"<div class=card><h4>{_esc(meta.get('kind', 'action'))} "
                f"&middot; drive {_esc(meta.get('drive', ''))}</h4>"
                f"<div class=why>{_esc(m['content'])}</div>"
                f"<pre>{_esc(meta.get('payload', ''))}</pre>"
                f"<div class=sentline>{line}</div></div>")
    cls = {"user": "msg user", "report": "msg report",
           "error": "msg err"}.get(m["role"], "msg agent")
    if m["role"] == "user" and meta.get("instruct"):
        cls = "msg user instr"
    when = (f"<div class=when>{_esc(_pretty(m['ts']))}</div>"
            if m["role"] != "user" else "")
    return f"<div class='{cls}'>{_esc(m['content'])}{when}</div>"


def _run_cycle_detached(cls):
    """Start a cycle without an HTTP request behind it."""
    with cls._cycle_lock:
        if cls._cycle_running:
            return
        cls._cycle_running = True

    def run():
        try:
            subprocess.run(
                [sys.executable, "-m", "agent.cycle", "--config",
                 "/opt/riffle/config.yaml"],
                cwd="/opt/riffle", timeout=2700,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            cls.state.say("error", "extra cycle failed: " + str(e)[:200])
        finally:
            cls._cycle_running = False

    _th.Thread(target=run, daemon=True).start()


POLICY_NOTES = {'post': 'one per UTC day, and only after a project clears the bar', 'comment': 'the main way it takes part', 'read_thread': 'opens a post and files it into the project', 'read_more': 'the next batch of replies on a thread already opened', 'request_cycle': 'asks to wake again sooner; capped daily', 'open_project': 'starts the thing a post has to come out of', 'project_note': 'an observation, source, draft, objection or correction', 'adjust_drive': 'moves its own goal weights, within goal_policy bounds', 'add_goal': 'always a proposal, never an act', 'remember': 'writes a durable memory', 'listing_submission': 'the only way it can be paid'}


def _goals_routes(h):
    """Extra routes bolted onto Handler. Returns True if it handled the path."""
    u = urllib.parse.urlparse(h.path)
    s, cfg = h.state, h.cfg
    if h.command == "GET" and u.path in ("/settings", "/goals"):
        b = GOALS_PAGE.encode()
        h.send_response(200)
        h.send_header("Content-Type", "text/html; charset=utf-8")
        h.send_header("Content-Length", str(len(b)))
        h.end_headers()
        h.wfile.write(b)
        return True
    if h.command == "GET" and u.path == "/api/telemetry":
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
            co = body.get("cores") or {}
            us = co.get("usage") if isinstance(co.get("usage"), dict) else {}
            busy = round(sum(us.values()) / len(us), 0) if us else None
            fan = max((body.get("fans") or {}).values(), default=None)
            thr = len(co.get("throttle") or {})
            line = (f"{mem.get('PctUsed', '?')}% mem, "
                    f"{mem.get('MemAvailable', '?')}MiB free, "
                    + (f"cpu {busy:.0f}%, " if busy is not None else "")
                    + f"{cp.get('mhz_avg', '?')}MHz"
                    + (f", {hot}\u00b0C" if hot is not None else "")
                    + (f", fan {fan}" if fan else "")
                    + (f", THROTTLED x{thr}" if thr else ""))
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
    if h.command == "GET" and u.path == "/api/policy":
        from agent import policy, project as _pj, state as _state
        policy.ensure(s, cfg)
        rows = s.db.execute("SELECT * FROM projects ORDER BY id DESC LIMIT 12").fetchall()
        projects = []
        for p in rows:
            st_ = _pj.stats(s, p["id"])
            ok, _why = _pj.ready(s, cfg, p["id"])
            reads = []
            for r in _pj.reads(s, p["id"]):
                try:
                    left = _pj.unread_count(s, r["id"])
                except Exception:
                    left = 0
                reads.append({"post_id": r["post_id"], "title": r["title"],
                              "seen": (r["comments_total"] or 0) - left,
                              "total": r["comments_total"] or 0, "left": left})
            projects.append({"id": p["id"], "title": p["title"],
                             "question": p["question"], "status": p["status"],
                             "notes": st_["notes"], "sources": st_["sources"],
                             "age": st_["age_hours"], "ready": bool(ok),
                             "reads": reads})
        h._json({"modes": policy.modes(s),
                 "kinds": policy.ACTION_KINDS,
                 "square": sorted(policy.REACHES_THE_SQUARE),
                 "notes": POLICY_NOTES,
                 "drives": [r["name"] for r in goals.all_drives(s)],
                 "restrictions": policy.restrictions(s),
                 "instructions": [
                     {"id": r["id"], "ts": r["ts"], "text": r["text"],
                      "left": r["cycles_left"], "total": r["cycles_total"]}
                     for r in _state.recent_instructions(s)],
                 "projects": projects})
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
                          "use_count": m["use_count"],
                          "tier": dict(m).get("tier") or "short",
                          "expired": bool(dict(m).get("expired"))}
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
        if u.path == "/api/policy/mode":
            from agent import policy
            old, new = policy.set_mode(s, b["kind"], b["mode"], "you")
            s.say("report", f"You set {b['kind']} to {b['mode']}"
                            + (f" (was {old})" if old and old != new else "") + ".")
            return h._json({"ok": True}) or True
        if u.path == "/api/policy/restrict":
            from agent import policy
            only, never = policy.set_restrictions(
                s, b["drive"], b.get("only"), b.get("never"), "you")
            s.say("report", f"You set what '{b['drive']}' may propose. "
                            + (f"Only: {', '.join(only)}. " if only else "")
                            + (f"Never: {', '.join(never)}." if never else "")
                            + ("No restrictions." if not only and not never else ""))
            return h._json({"ok": True}) or True
        if u.path == "/api/instruction/cycles":
            from agent import state as _state
            _state.set_instruction_cycles(s, int(b["id"]), int(b["cycles"]))
            return h._json({"ok": True}) or True
        if u.path == "/api/instruction/clear":
            from agent import state as _state
            n = _state.clear_instructions(s)
            s.say("report", f"You cleared {n} standing instruction(s).")
            return h._json({"ok": True, "cleared": n}) or True
        if u.path == "/api/project/close":
            from agent import project as _pj
            p = _pj.active(s)
            if not p:
                return h._json({"error": "no project is open"}) or True
            _pj.close_project(s, p["id"], "abandoned")
            s.say("report", f"You closed the project '{p['title']}'. Its notes "
                            f"and reads are kept.")
            return h._json({"ok": True}) or True
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
