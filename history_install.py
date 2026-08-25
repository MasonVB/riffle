#!/usr/bin/env python3
"""A clear button, and a history page to clear into.

    sudo cp history_install.py /opt/riffle/
    sudo python3 /opt/riffle/history_install.py
    sudo systemctl restart riffle-dash

HEADER, LEFT TO RIGHT

    riffle   [state] [queue]  ...  [caps] [run cycle] [restart model]
             [history] [goals]      [clear]

Clear sits apart from the others with a wider gap, in red, because it is the
only header control that changes what you can see.

CLEARING ARCHIVES, IT DOES NOT DELETE

Every message gets an archived_at stamp and drops out of the chat view. The
history page shows them all, oldest first, with a rule between each clearing
and the time it happened. Chat plus history is still the complete log. Same
choice as the alarm badge, the memory store and the project notes: the record
of what happened outlives the decision to stop looking at it.

WHAT THE MODEL SEES DOES NOT CHANGE

You said this is for your reading, so `chat.answer` still pulls its recent
turns from the full table including archived ones. Worth knowing the
consequence: after a clear, the agent can refer to an exchange you can no
longer see. If you would rather clearing also reset its conversational memory,
that is one word — say so and I will make the history window skip archived
rows.

THE CSS IS NOT COPIED

Two pages already carry their own inline stylesheet and I said last time that
a third should force a shared one. Extracting the accumulated CSS out of two
working pages is a change I cannot test against your exact file, so instead
the history page reads the chat page's <style> block at import time. One
source of truth, no refactor, and every future style patch reaches all of it.

Backups written as .bak-history.
"""
import os
import shutil
import sqlite3
import sys

RIFFLE = "/opt/riffle"
DASH = f"{RIFFLE}/agent/dash.py"
STATE = f"{RIFFLE}/agent/state.py"
DB = "/var/lib/riffle/state.sqlite"


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
    if not os.path.exists(f"{path}.bak-history"):
        shutil.copy(path, f"{path}.bak-history")
    open(path, "w").write(s.replace(old, new, 1))
    print(f"  patched: {label}")
    return True


HISTORY_BLOCK = '''

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
            f"<header><a class=brand href=\\"/\\">riffle</a>"
            f"<span class=pill>{len(rows)} archived</span>"
            f"<span style='flex:1'></span>"
            f"<a class=link href=\\"/\\">chat</a>"
            f"<a class=link href=\\"/goals\\">goals</a></header>"
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
    when = (f"<div class=when>{_esc(_pretty(m['ts']))}</div>"
            if m["role"] != "user" else "")
    return f"<div class='{cls}'>{_esc(m['content'])}{when}</div>"
'''

CLEAR_HANDLER = '''    def clear_chat(self):
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

    def restart_model(self):'''


def main():
    # ---- column -----------------------------------------------------------
    con = sqlite3.connect(DB)
    if "archived_at" not in [r[1] for r in con.execute("PRAGMA table_info(messages)")]:
        con.execute("ALTER TABLE messages ADD COLUMN archived_at TEXT")
        con.commit()
        print("  added messages.archived_at")
    else:
        print("  already present: messages.archived_at")
    con.close()

    patch(STATE, "  done INTEGER DEFAULT 1);   -- 0 while a response is still streaming in",
          "  done INTEGER DEFAULT 1,   -- 0 while a response is still streaming in\n"
          "  archived_at TEXT);        -- set by the clear button; never deleted",
          "archived_at in the schema itself", marker="archived_at TEXT);")

    # the chat view hides archived rows; tail() deliberately does not
    patch(STATE,
          '''    def messages(self, after=0, limit=400):
        return self.db.execute(
            "SELECT * FROM messages WHERE id > ? ORDER BY id LIMIT ?", (after, limit)).fetchall()''',
          '''    def messages(self, after=0, limit=400, include_archived=False):
        """The chat view. Archived rows are hidden here and only here.

        `tail()` below still sees them, because that is what feeds the model's
        recent-turn window, and clearing the screen is not meant to give the
        agent amnesia."""
        q = "SELECT * FROM messages WHERE id > ?"
        if not include_archived:
            q += " AND archived_at IS NULL"
        return self.db.execute(q + " ORDER BY id LIMIT ?", (after, limit)).fetchall()''',
          "chat view hides archived rows", marker="include_archived=False")

    patch(STATE,
          '''    def pending_generation(self):
        return self.db.execute(
            "SELECT * FROM messages WHERE done=0 ORDER BY id DESC LIMIT 1").fetchone()''',
          '''    def pending_generation(self):
        return self.db.execute(
            "SELECT * FROM messages WHERE done=0 AND archived_at IS NULL"
            " ORDER BY id DESC LIMIT 1").fetchone()''',
          "an archived row cannot look like a live generation",
          marker="done=0 AND archived_at IS NULL")

    # ---- header -----------------------------------------------------------
    patch(DASH, '  <a class="pill link" href="/goals">goals</a>',
          '  <a class="pill link" href="/history">history</a>\n'
          '  <a class="pill link" href="/goals">goals</a>\n'
          '  <button id=clearbtn class="pillbtn danger" onclick="clearChat()">clear</button>',
          "history and clear in the header", marker='href="/history"')

    # Anchor on a rule the chat page alone carries. `a.brand{` is in both
    # stylesheets and matched twice.
    patch(DASH, ".pillbtn:disabled{opacity:.35;cursor:default}",
          """.pillbtn:disabled{opacity:.35;cursor:default}
.pillbtn.danger{color:var(--bad);border-color:var(--bad);margin-left:14px}
@media (hover:hover){.pillbtn.danger:hover{background:var(--bad);color:var(--bg)}}
.pillbtn.danger:active{background:var(--bad);color:var(--bg)}""",
          "clear button styling and its wider gap", marker=".pillbtn.danger{")

    patch(DASH, "async function restartModel(){",
          '''async function clearChat(){
  if(!confirm('Clear the chat?\\n\\nEverything moves to the history page. '
            + 'Nothing is deleted, and the agent still remembers the '
            + 'conversation.')) return;
  await fetch('/api/clear-chat', {method:'POST',
    headers:{'Content-Type':'application/json'}, body:'{}'});
  document.getElementById('log').innerHTML = '';
  after = 0;
}
async function restartModel(){''',
          "clearChat() in the page script", marker="async function clearChat()")

    # ---- routes -----------------------------------------------------------
    patch(DASH, '        if u.path == "/api/messages":',
          '''        if u.path == "/history":
            b = history_page(self.state).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            return self.wfile.write(b)
        if u.path == "/api/messages":''',
          "/history route", marker='u.path == "/history"')

    patch(DASH, '        if u.path == "/api/restart-model":',
          '''        if u.path == "/api/clear-chat":
            return self._json(self.clear_chat())
        if u.path == "/api/restart-model":''',
          "clear-chat route", marker='"/api/clear-chat"')

    # The snapshot re-sends recent proposal cards past the cursor so they can
    # update in place. That query did not know about archiving, so a cleared
    # card came straight back.
    patch(DASH,
          '''        for m in s.db.execute("SELECT * FROM messages WHERE role='proposal'"
                              " ORDER BY id DESC LIMIT 25"):''',
          '''        for m in s.db.execute("SELECT * FROM messages WHERE role='proposal'"
                              " AND archived_at IS NULL"
                              " ORDER BY id DESC LIMIT 25"):''',
          "cleared cards stay cleared",
          marker="AND archived_at IS NULL\"\n                              \" ORDER BY id DESC LIMIT 25")

    patch(DASH, "    def restart_model(self):", CLEAR_HANDLER,
          "clear_chat handler", marker="def clear_chat(self):")

    patch(DASH, "\n\ndef _goals_routes(h):", HISTORY_BLOCK + "\n\ndef _goals_routes(h):",
          "history page renderer", marker="def history_page(state):")

    import ast
    for f in (DASH, STATE):
        ast.parse(open(f).read())
    print("\n  modules parse.")
    print("\n  Next:  sudo systemctl restart riffle-dash")


if __name__ == "__main__":
    main()
