#!/usr/bin/env python3
"""Wordmark links home, and Pushover notifications get a tap-through link.

    sudo cp brand_actions_install.py /opt/riffle/
    sudo python3 /opt/riffle/brand_actions_install.py
    sudo systemctl restart riffle-dash

ON PUSHOVER BUTTONS — WHAT IS AND IS NOT POSSIBLE

Pushover has no action-button API. A message carries one supplementary `url`
and nothing else. The one thing resembling a button is emergency priority,
whose Acknowledge control can hit a `callback` URL — but that is a single
control meaning "I saw this", and wiring it to "send it to the square" would
make a dismissal indistinguishable from an approval. Not worth it.

What does work: `html=1` renders `<a href>` in the message body, so the
notification can carry real tappable links. This adds one per proposal.

WHY THE LINK OPENS A PAGE RATHER THAN ACTING DIRECTLY

A link that posts to the square on GET is a link that fires if anything ever
follows it — a prefetch, a scanner, a stray tap in a notification shade. So
the link opens /act, which is read-only: it shows the kind, the drive, the
rationale and the full payload, with Send and Reject buttons underneath. Two
taps instead of one, and you see what you are approving.

That page is reachable only on your tailnet, and its URL carries an HMAC of
the action id so it cannot be found by guessing. The secret is generated once
and kept in the notes table.

Backups written as .bak-brand.
"""
import os
import shutil
import sys

DASH = "/opt/riffle/agent/dash.py"
NOTIFY = "/opt/riffle/agent/notify.py"


def patch(path, old, new, label, marker, required=True):
    s = open(path).read()
    if marker in s:
        print(f"  already present: {label}")
        return False
    if old not in s:
        if required:
            sys.exit(f"  FAILED: anchor not found in {os.path.basename(path)} "
                     f"({label}). Nothing changed.")
        print(f"  skipped: {label}")
        return False
    if not os.path.exists(f"{path}.bak-brand"):
        shutil.copy(path, f"{path}.bak-brand")
    open(path, "w").write(s.replace(old, new, 1))
    print(f"  patched: {label}")
    return True


BRAND_CSS = """
a.brand{font-family:ui-monospace,Menlo,monospace;letter-spacing:.07em;
  color:var(--sig);text-decoration:none;font-weight:700;padding:2px 6px;
  border-radius:6px;margin-left:-6px;transition:background .12s ease,color .12s ease}
@media (hover:hover){a.brand:hover{background:var(--sig);color:var(--bg)}}
a.brand:active{background:var(--sig);color:var(--bg)}"""

ACT_PAGE = '''

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
    '<div class=btns><button class=go onclick="go(\\'approve\\')">send it</button>' +
    '<button class=no onclick="go(\\'reject\\')">reject</button></div>';
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
'''

ACT_ROUTES = '''        if u.path == "/act":
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
        if u.path == "/api/messages":'''


def main():
    # ---- 1. wordmark links home on both pages -----------------------------
    patch(DASH, "<header><b>riffle</b>",
          '<header><a class=brand href="/">riffle</a>',
          "chat page wordmark links home", marker='<a class=brand href="/">riffle</a>')

    patch(DASH, '<header><b>riffle</b><span style="flex:1"></span>'
                '<a class=link href="/">chat</a></header>',
          '<header><a class=brand href="/">riffle</a><span style="flex:1"></span>'
          '<a class=link href="/">chat</a></header>',
          "goals page wordmark links home",
          marker='<a class=brand href="/">riffle</a><span style="flex:1">')

    # brand styling into both style blocks
    patch(DASH, ".pill.bad{color:var(--bad);border-color:var(--bad)}",
          ".pill.bad{color:var(--bad);border-color:var(--bad)}" + BRAND_CSS,
          "brand styling on the chat page", marker="a.brand{font-family")

    patch(DASH, "/* --- shared control styling, mirrored from the chat page",
          BRAND_CSS.strip() + "\n/* --- shared control styling, mirrored from the chat page",
          "brand styling on the goals page",
          # Must be unique to THIS insertion. The chat-page patch adds the same
          # BRAND_CSS to the same file, so any marker taken from the CSS itself
          # matches after that patch and this one is skipped in silence.
          marker="color:var(--bg)}\n/* --- shared control styling")

    # ---- 2. the review page -----------------------------------------------
    patch(DASH, '\n\ndef _goals_routes(h):', ACT_PAGE + '\n\ndef _goals_routes(h):',
          "review page + link_token()", marker="def link_token(state, aid):")

    patch(DASH, '        if u.path == "/api/messages":', ACT_ROUTES,
          "/act and /api/action routes", marker='u.path == "/api/action"')

    # ---- 3. notifications carry the link ----------------------------------
    patch(NOTIFY,
          '''    if len(rows) == 1:
        r = rows[0]
        title = f"riffle wants to {r['kind']}"
        msg = f"[{r['drive']}] {r['rationale'][:700]}"''',
          '''    # Pushover has no action-button API. It does render <a href> when html=1,
    # so the notification carries a tap-through link per proposal. The link
    # opens a read-only review page rather than acting on GET: a URL that
    # posts to the square is a URL that fires on any stray follow.
    from agent.dash import link_token
    base = dash_url(cfg).rstrip("/")

    def review(aid):
        return f"{base}/act?id={aid}&t={link_token(state, aid)}"

    if len(rows) == 1:
        r = rows[0]
        title = f"riffle wants to {r['kind']}"
        msg = (f"[{r['drive']}] {r['rationale'][:600]}\\n\\n"
               f'<a href="{review(r["id"])}">Review and decide &#8594;</a>')''',
          "single-proposal notification carries a review link",
          marker="def review(aid):")

    patch(NOTIFY,
          '''        msg = "\\n\\n".join(f"#{r['id']} {r['kind']} ({r['drive']}): "
                          f"{r['rationale'][:180]}" for r in rows[:5])''',
          '''        msg = "\\n\\n".join(
            f'{r["kind"]} ({r["drive"]}): {r["rationale"][:150]}\\n'
            f'<a href="{review(r["id"])}">decide &#8594;</a>' for r in rows[:5])''',
          "batched notification links each proposal",
          # The single-proposal patch above writes "Review and decide &#8594;",
          # which contains "decide &#8594;". Anchor on the '>' before it.
          marker='">decide &#8594;')

    patch(NOTIFY,
          '''    data = {"token": token, "user": user, "title": title[:250],
            "message": message[:1024], "priority": priority}''',
          '''    data = {"token": token, "user": user, "title": title[:250],
            "message": message[:1024], "priority": priority,
            # html=1 is what makes the <a href> links above tappable.
            "html": 1}''',
          "pushover html mode", marker='"html": 1')

    import ast
    for f in (DASH, NOTIFY):
        ast.parse(open(f).read())
    print("\n  modules parse.")
    print("\n  Next:  sudo systemctl restart riffle-dash")


if __name__ == "__main__":
    main()
