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
from agent.pages import (ACT_PAGE, GOALS_PAGE, HISTORY_EXTRA,  # noqa: E402
                         PAGE, _chat_css)



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
        # The same numbers, unpacked. The string above was built for a pill
        # narrow enough to need "c18 p0"; the footer spells them out, and
        # parsing that string back apart in JS would be a silly way to get
        # there. `day` is the UTC date, so these roll over at 00:00Z.
        caps_left = {k: cfg["caps"][k] - s.cap_used(day, k) for k in cfg["caps"]}
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
                "alarms": alarms, "caps": caps, "caps_left": caps_left}

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
        # Queue position is the row's place in project.queue(), not its id:
        # dropping #1 has to renumber the rest, and ids never do.
        qpos = {r["id"]: i + 1 for i, r in enumerate(_pj.queue(s))}
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
                             "queue_pos": qpos.get(p["id"]),
                             "reads": reads})
        # Running first, then the queue in the order it will actually run,
        # then everything finished. Plain id order buried the active project
        # under whatever had been queued after it.
        projects.sort(key=lambda d: (0 if d["status"] == "active"
                                     else 1 if d["queue_pos"] else 2,
                                     d["queue_pos"] or -d["id"]))
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
        if u.path == "/api/project/dequeue":
            from agent import project as _pj
            pid = int(b.get("id") or 0)
            row = s.db.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
            # drop_queued only ever touches a row whose status is 'queued', so
            # a stale page cannot use this to kill the running project.
            if not row or not _pj.drop_queued(s, pid):
                return h._json({"error": "not a queued project"}) or True
            s.say("report", f"You removed '{row['title']}' from the project "
                            f"queue. It never started, so nothing is lost.")
            return h._json({"ok": True}) or True
        if u.path == "/api/project/close":
            from agent import project as _pj
            p = _pj.active(s)
            if not p:
                return h._json({"error": "no project is open"}) or True
            nxt = _pj.close_project(s, p["id"], "abandoned")
            s.say("report", f"You closed the project '{p['title']}'. Its notes "
                            f"and reads are kept."
                  + (f" Started the next one in the queue: {nxt['title']}"
                     if nxt else ""))
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
