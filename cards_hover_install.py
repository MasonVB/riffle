#!/usr/bin/env python3
"""Hover inversion everywhere, and make "send it" visibly do something.

    sudo cp cards_hover_install.py /opt/riffle/
    sudo python3 /opt/riffle/cards_hover_install.py
    sudo systemctl restart riffle-dash

WHY "SEND IT" LOOKED DEAD

It was not dead — it posted to the square. The card just never changed. Two
causes, both mine:

  The handler appended a NEW message saying "Sent", while the ORIGINAL card
  kept its meta at status "queued", so its buttons stayed.

  And the page only fetches messages newer than its cursor. A card that
  changes in place is older than the cursor by definition, so even a corrected
  meta would never have reached the browser.

So: the handler now updates the original card's meta rather than appending
beside it, and the snapshot always re-sends recent proposal cards regardless
of cursor. There are only ever a handful, and a card whose state can never
reach the screen is worse than no card.

WHAT APPROVAL DOES NOW

  1. the card immediately reads "sending…" and the buttons disappear
  2. a background thread performs the actual POST to the square
  3. the card becomes "Sent 4:32 PM" with the registry's id, or "Refused"
     with the error text
  4. a wake cycle starts, so riffle sees its own action landed, records it,
     and can react to what happens next

Step 4 is the "wake and send it" you asked for. The send itself is immediate;
the cycle is what makes the agent aware of it.

Backups written as .bak-cards.
"""
import os
import shutil
import sys

RIFFLE = "/opt/riffle"
DASH = f"{RIFFLE}/agent/dash.py"


def patch(old, new, label, marker, path=DASH, required=True):
    s = open(path).read()
    if marker in s:
        print(f"  already present: {label}")
        return False
    if old not in s:
        if required:
            sys.exit(f"  FAILED: anchor not found ({label}). Nothing changed.")
        print(f"  skipped: {label}")
        return False
    if not os.path.exists(f"{path}.bak-cards"):
        shutil.copy(path, f"{path}.bak-cards")
    open(path, "w").write(s.replace(old, new, 1))
    print(f"  patched: {label}")
    return True


HOVER_CSS = """
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
@keyframes sp{to{transform:rotate(360deg)}}"""

CARD_OLD = """      (p.status === 'queued'
        ? '<div class=btns><button class=go onclick="decide('+p.action_id+',\\'approve\\')">send it</button>'+
          '<button class=no onclick="decide('+p.action_id+',\\'reject\\')">reject</button></div>'
        : '<div class=when>' + esc(p.status||'') + '</div>');"""

CARD_NEW = """      (p.status === 'queued'
        ? '<div class=btns><button class=go onclick="decide('+p.action_id+',\\'approve\\',this)">send it</button>'+
          '<button class=no onclick="decide('+p.action_id+',\\'reject\\',this)">reject</button></div>'
        : statusLine(p));"""

STATUS_JS = """function statusLine(p){
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
"""

DECIDE_JS_OLD = """async function decide(id, verdict){
  await fetch('/api/decide', {method:'POST', headers:{'Content-Type':'application/json'},
                              body: JSON.stringify({id:id, verdict:verdict})});
}"""

DECIDE_JS_NEW = """async function decide(id, verdict, btn){
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
}"""

DECIDE_PY = '''    def _local_time(self):
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

    def _decide_old_unused(self, aid, verdict):'''


def main():
    patch(".pill.bad{color:var(--bad);border-color:var(--bad)}",
          ".pill.bad{color:var(--bad);border-color:var(--bad)}" + HOVER_CSS,
          "hover inversion CSS", marker="@media (hover:hover){")

    patch("function toggleAlarms(e){", STATUS_JS + "function toggleAlarms(e){",
          "statusLine() renderer", marker="function statusLine(p){")

    patch(CARD_OLD, CARD_NEW, "card renders status instead of bare text",
          marker=": statusLine(p)")

    patch(DECIDE_JS_OLD, DECIDE_JS_NEW, "decide() swaps buttons immediately",
          marker="async function decide(id, verdict, btn)")

    # always re-send proposal cards, whatever the cursor says
    patch('''        return {"messages": out, "queued": len(s.queued()),''',
          '''        # A card that changes state is by definition older than the
        # client's cursor, so it would never be re-fetched. Re-send recent
        # proposal cards every poll; there are only ever a handful, and the
        # client renders by id so they update in place.
        have = {m["id"] for m in out}
        for m in s.db.execute("SELECT * FROM messages WHERE role='proposal'"
                              " ORDER BY id DESC LIMIT 25"):
            if m["id"] not in have:
                out.append({"id": m["id"], "role": m["role"], "content": m["content"],
                            "meta": json.loads(m["meta"]) if m["meta"] else {},
                            "done": True, "ts": m["ts"]})
        out.sort(key=lambda x: x["id"])

        return {"messages": out, "queued": len(s.queued()),''',
          "snapshot re-sends proposal cards", marker="Re-send recent")

    patch("    def decide(self, aid, verdict):", DECIDE_PY,
          "decide() updates the card in place and wakes a cycle",
          marker="def _update_card(self, aid")

    import ast
    ast.parse(open(DASH).read())
    print("\n  dash.py parses.")
    print("\n  Next:  sudo systemctl restart riffle-dash")


if __name__ == "__main__":
    main()
