"""The HTML the dashboard serves.

Split out of dash.py, which had grown to 1,805 lines of which 850 were these
four string constants. A one-line change to a handler meant re-reading the
whole chat page to find it, and every stylesheet edit meant scrolling past two
others. Nothing here executes: these are templates and one helper that slices
one of them.

The three pages share a stylesheet by convention rather than by import — the
history page lifts the chat page's <style> block at import time via
_chat_css() so the two cannot drift. Now that all three live in one file,
doing the same for the goals page is a small change rather than a cross-file
refactor.

%MODEL% in PAGE is substituted at serve time, in dash.Handler.
"""

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
/* `.brand` rather than `a.brand`: the settings page puts the class on the
   anchor, the chat page on a <span> inside a.brandwrap. The anchor-only
   selector matched settings and silently missed chat, which then rendered
   as a default browser link — blue, then purple once visited. */
a.brandwrap{text-decoration:none;color:var(--sig)}
.brand{font-family:ui-monospace,Menlo,monospace;letter-spacing:.07em;
  color:var(--sig);text-decoration:none;font-weight:700;padding:2px 6px;
  border-radius:6px;margin-left:-6px;transition:background .12s ease,color .12s ease}
@media (hover:hover){a.brandwrap:hover .brand,a.brand:hover{background:var(--sig);color:var(--bg)}}
a.brandwrap:active .brand,a.brand:active{background:var(--sig);color:var(--bg)}
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
/* position:FIXED, not absolute, and placed by JS from the pill's rect.
   #pills has overflow-x:auto so the pills can scroll on a phone, and a
   scroll container clips absolutely-positioned descendants on BOTH axes —
   so the panel was rendering correctly and being cut off by its own parent.
   Fixed positioning escapes every clipping ancestor. Hover-open is gone with
   it: hover cannot place a panel whose coordinates are computed on open, and
   this is a control that mostly gets used on a phone, where there is no
   hover anyway. */
.alarmpanel{display:none;position:fixed;z-index:400;
  min-width:min(78vw,440px);max-width:min(92vw,520px);max-height:min(56vh,340px);
  overflow-y:auto;background:var(--panel);border:1px solid var(--bad);
  border-radius:9px;padding:0;box-shadow:0 10px 34px rgba(0,0,0,.6);
  -webkit-overflow-scrolling:touch}
.alarmwrap.pinned .alarmpanel{display:block}
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
/* Tap a message to see when it arrived. The row is always in the markup and
   hidden by CSS, so showing it is a class flip rather than a redraw —
   render() only rebuilds innerHTML when the content changed, and anything
   appended outside that would vanish on the next poll that did. */
.msg{cursor:pointer}
.msg .when.at{display:none}
.msg.showts .when.at{display:block}
.msg.user .when.at{text-align:right}
.msg.report .when.at,.msg.err .when.at{font-size:10.5px}
.card{align-self:stretch;max-width:100%;background:var(--panel);
  border:1px solid var(--line);border-left:3px solid var(--sig);
  border-radius:9px;padding:13px}
/* A question riffle asked, not an action it took. Different accent so the two
   do not read the same in scrollback. */
.card.ask{border-left-color:#9ecbff}
.card.ask h4{color:#9ecbff}
.ansbox{width:100%;margin-top:8px;background:#0e100b;color:var(--fg);
  border:1px solid var(--line);border-radius:8px;padding:8px 10px;font:inherit;
  resize:vertical}
.answered{margin-top:8px;padding:8px 10px;border-left:2px solid var(--sig);
  white-space:pre-wrap}
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
    // "sent without asking" rather than a bare tick: with comment, vote, tag,
    // seal, porch and attestation all on auto, the difference between a card
    // you approved and one that went out on its own is the thing worth seeing
    // at a glance.
    return '<div class=sentline>&#10003; Sent ' + esc(p.sent_at || '') +
           (p.auto ? ' &middot; on auto, not asked' : '') +
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

function placeAlarmPanel(){
  // The panel is position:fixed, so it needs viewport coordinates. Anchor it
  // under the pill, then pull it back inside the right edge if it would hang
  // off — on a 412px screen a 440px panel anchored at x=200 goes off-screen,
  // which looks exactly like not opening at all.
  const pill = document.getElementById('p-state');
  const panel = document.getElementById('alarmpanel');
  if(!pill || !panel) return;
  const r = pill.getBoundingClientRect();
  panel.style.top = (r.bottom + 6) + 'px';
  panel.style.left = '0px';
  panel.style.visibility = 'hidden';
  panel.style.display = 'block';
  const w = panel.getBoundingClientRect().width;
  panel.style.display = '';
  panel.style.visibility = '';
  panel.style.left = Math.max(8, Math.min(r.left, window.innerWidth - w - 8)) + 'px';
}
function toggleAlarms(e){
  e.stopPropagation();
  const w = document.getElementById('alarmwrap');
  if(!w.dataset.has) return;              // nothing to show, nothing to pin
  const opening = !w.classList.contains('pinned');
  if(opening) placeAlarmPanel();
  w.classList.toggle('pinned');
  document.getElementById('p-state').classList.toggle('pinned',
    w.classList.contains('pinned'));
}
// A fixed panel does not move with its anchor, so reposition it if the
// viewport changes underneath it rather than leaving it stranded.
window.addEventListener('resize', function(){
  const w = document.getElementById('alarmwrap');
  if(w && w.classList.contains('pinned')) placeAlarmPanel();
});
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

/* Which messages are currently showing their timestamp. render() reassigns
   className on every poll, so the set is the only place this can live. */
const tsShown = new Set();

function atTime(ts){
  if(!ts) return '';
  const d = new Date(ts);                       // ts ends in Z, so this is UTC
  if(isNaN(d)) return ts;
  const t = d.toLocaleTimeString([], {hour:'numeric', minute:'2-digit'});
  const today = new Date();
  return d.toDateString() === today.toDateString() ? t
       : d.toLocaleDateString([], {month:'short', day:'numeric'}) + ', ' + t;
}

document.getElementById('log').addEventListener('click', function(e){
  const el = e.target.closest('.msg');
  if(!el) return;
  const id = el.id.slice(1);
  if(tsShown.has(id)) { tsShown.delete(id); el.classList.remove('showts'); }
  else                { tsShown.add(id);    el.classList.add('showts'); }
});

function render(m){
  let el = document.getElementById('m'+m.id);
  if(!el){ el = document.createElement('div'); el.id = 'm'+m.id; log.appendChild(el); }
  if(m.role === 'question'){
    const p = m.meta || {};
    const _qsig = JSON.stringify([p.status, p.answer, m.content.length]);
    if(el.dataset.sig === _qsig) return;
    el.dataset.sig = _qsig;
    el.className = 'card ask';
    el.innerHTML = '<h4>riffle is asking you &middot; drive ' + esc(p.drive||'') +
      '</h4><div class=why>' + esc(m.content) + '</div>' +
      (p.why ? '<div class=when>' + esc(p.why) + '</div>' : '') +
      (p.status === 'answered'
        ? '<div class=answered>' + esc(p.answer||'') + '</div>' +
          '<div class=sentline>&#10003; answered ' + esc(p.answered_at||'') + '</div>'
        : '<textarea class=ansbox id="a'+p.qid+'" rows=2 ' +
          'placeholder="your answer becomes a source it can cite"></textarea>' +
          '<div class=btns><button class=go onclick="sendAnswer('+p.qid+
          ',this)">answer</button></div>');
    return;
  }
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
    + (m.role==='user' && m.meta && m.meta.instruct ? ' instr' : '')
    + (tsShown.has(String(m.id)) ? ' showts' : '');
  // Rebuilding innerHTML throws away the scroll position of any <pre>
  // inside, and proposal cards are re-sent every poll so their state
  // can change. Draw only when what we would draw is different.
  const _sig = m.role + '|' + m.done + '|' + m.content.length;
  if(el.dataset.sig === _sig) return;
  el.dataset.sig = _sig;
  el.innerHTML = esc(m.content) + (m.done ? '' : '<span class=dot>&#9612;</span>') +
    (m.role!=='user' && m.done && m.meta && m.meta.elapsed_s
      ? '<div class=when>' + m.meta.elapsed_s + 's</div>' : '') +
    '<div class="when at">' + esc(atTime(m.ts)) + '</div>';
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
async function sendAnswer(qid, btn){
  const box = document.getElementById('a' + qid);
  const text = (box && box.value || '').trim();
  if(!text){ box && box.focus(); return; }
  btn.disabled = true; btn.textContent = 'sending\u2026';
  await fetch('/api/answer', {method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({qid: qid, answer: text})});
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
/* Queued reads as pending rather than running or finished: same accent as an
   active project, dashed, because it is going to happen but has not. */
.pj.queued{border-left-style:dashed;border-left-color:var(--sig)}
.pj.queued h3{color:var(--fg)}
.qbadge{display:inline-block;font-family:ui-monospace,Menlo,monospace;
  font-size:10.5px;letter-spacing:.06em;text-transform:uppercase;
  color:var(--sig);border:1px solid var(--sig);border-radius:99px;
  padding:1px 8px;margin-left:8px;vertical-align:2px;white-space:nowrap}
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

/* `.brand` rather than `a.brand`: the settings page puts the class on the
   anchor, the chat page on a <span> inside a.brandwrap. The anchor-only
   selector matched settings and silently missed chat, which then rendered
   as a default browser link — blue, then purple once visited. */
a.brandwrap{text-decoration:none;color:var(--sig)}
.brand{font-family:ui-monospace,Menlo,monospace;letter-spacing:.07em;
  color:var(--sig);text-decoration:none;font-weight:700;padding:2px 6px;
  border-radius:6px;margin-left:-6px;transition:background .12s ease,color .12s ease}
@media (hover:hover){a.brandwrap:hover .brand,a.brand:hover{background:var(--sig);color:var(--bg)}}
a.brandwrap:active .brand,a.brand:active{background:var(--sig);color:var(--bg)}
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
working on. An instruction takes the next cycle: the drive becomes
<b>operator</b> and the request goes to the top of the prompt. It is spent
once the model has <b>answered</b> &mdash; a refused proposal still spends it,
a cycle that never reached the model does not.</div>
<div class=g id=instructions></div>

<h2>how often it wakes</h2>
<div class=note>The timer fires every five minutes; this is how many of those
firings actually become a cycle. A cycle takes two to three minutes on this
box, so anything under ten leaves it doing little else. The run-cycle button
and <code>request_cycle</code> ignore this and wake it immediately.</div>
<div class=g style="margin-bottom:18px">
  <label style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
    <input id=ivmins type=number min=5 max=1440 step=5
           style="width:96px;background:#0e100b;color:var(--fg);
                  border:1px solid var(--line);border-radius:8px;padding:8px 10px;
                  font:inherit">
    <span style="color:var(--dim)">minutes between wakes</span>
    <button onclick="saveInterval()">save</button>
  </label>
</div>

<h2>projects</h2>
<div class=note>A post has to come out of one of these. The bar is notes,
distinct sources, a draft, and an objection to its own argument. Only one runs
at a time &mdash; a note carries no project id, so two at once would mean
filing every note against the right one by hand. Ask for another and it
queues, in the order shown, and starts when the running one is posted or
closed.</div>
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


// The action list comes from the API, which reads policy.ACTION_KINDS.
//
// It used to be a literal here, copied from that list by hand. Six actions
// were added to Python — porch, knock, attestation, fetch, build, sign — and
// the settings page kept rendering the old sixteen, so the new ones existed,
// were seeded in the database, were enforced by the gate, and could not be
// seen or changed by anyone. Silent, and only findable by counting rows.
//
// Same shape as the a.brand selector that matched the settings page and
// missed the chat page: two copies of one truth, and only one of them
// maintained. There is now one copy.
let ACTS = [];
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
  ACTS = pol.kinds || [];
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

  if(pol.interval) document.getElementById('ivmins').value = pol.interval;
  document.getElementById('projects').innerHTML = pol.projects.length
    ? pol.projects.map(function(p){
        const reads = (p.reads||[]).map(function(r){
          return '<div class=rd>#' + r.post_id + ' <b>' + esc(r.title) +
            '</b> &middot; ' + r.seen + ' of ' + r.total + ' replies read' +
            (r.left ? ', <span style="color:var(--sig)">' + r.left +
             ' unread</span>' : '') + '</div>';
        }).join('');
        const queued = !!p.queue_pos;
        // A queued project has no notes, no sources and no age worth showing:
        // its counters would all read zero and look like a stalled project
        // rather than one that has not started.
        const legend = queued
          ? '<div class=legend><span>waiting</span><span>starts when the ' +
            'running project is posted or closed</span></div>'
          : '<div class=legend><span>' + p.notes + ' notes &middot; ' + p.sources +
            ' sources &middot; ' + p.age + 'h &middot; ' + esc(p.status) + '</span>' +
            '<span' + (p.ready?' style="color:var(--sig)"':'') + '>' +
            (p.ready?'ready to post':'not ready') + '</span></div>';
        const btn = queued
          ? '<div class=ctl><button class=warn2 onclick="dequeueProject(' + p.id +
            ',' + JSON.stringify(p.title) + ')">remove from queue</button></div>'
          : (p.status==='active'
            ? '<div class=ctl><button class=warn2 onclick="closeProject()">close it</button></div>'
            : '');
        return '<div class="pj' + (queued ? ' queued'
                                  : p.status==='active' ? '' : ' done') + '">' +
          '<h3>' + esc(p.title) +
          (queued ? '<span class=qbadge>#' + p.queue_pos + ' in queue</span>' : '') +
          '</h3><div class=q>' + esc(p.question) + '</div>' +
          legend + reads + btn + '</div>';
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
async function dequeueProject(id, title){
  if(!confirm('Remove \u201c' + title + '\u201d from the queue? It never '
              + 'started, so there is nothing to keep.')) return;
  await api('/api/project/dequeue', {id:id});
  await loadPolicy();
}
async function saveInterval(){
  const v = parseInt(document.getElementById('ivmins').value, 10);
  if(!v || v < 5 || v > 1440){ alert('Between 5 and 1440 minutes.'); return; }
  await api('/api/interval', {minutes: v});
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
