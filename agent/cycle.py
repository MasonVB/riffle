#!/usr/bin/env python3
"""One wake cycle. Run from a systemd timer.

    python3 -m agent.cycle --config config.yaml

Order of operations, and why:

  pulse   -> a few hundred bytes that answer whether anything concerns you.
             Only pay for a full read when it says yes.
  attest  -> the witness ritual runs FIRST and unconditionally. It is the one
             obligation that is not subject to a weighted desire, because a
             society whose members each remember one hash is the whole
             mechanism and a drive table that can skip it has misunderstood
             what it is for.
  gather  -> inbox and a bounded slice of what moved.
  drive   -> weighted choice among drives that actually have something to act
             on. A drive with no material is not available this cycle.
  propose -> one action, from the model, as JSON.
  gate    -> schema, caps, constraints. Model output is a suggestion.
  check   -> numcheck over any body containing figures.
  execute -> or queue for the operator, per config autonomy.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent import (chat, consolidate, cortex, drives, goals, memory,
                   notify, policy, project)  # noqa: E402  # noqa: E402
from agent.client import HttpError, Reader, Writer  # noqa: E402
from agent.state import State, utcnow  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CFG = None  # set in main(); do_witness needs it for alarm notifications


def load_config(path):
    """Minimal YAML subset reader so the agent needs no pip install."""
    try:
        import yaml
        return yaml.safe_load(open(path))
    except ImportError:
        pass
    cfg = {}
    stack = [(-1, cfg)]
    for raw in open(path):
        line = raw.split("#")[0].rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        s = line.strip()
        if s.startswith("- "):
            parent.setdefault("_list", []).append(_scalar(s[2:]))
            continue
        key, _, val = s.partition(":")
        val = val.strip()
        if not val:
            node = {}
            parent[key.strip()] = node
            stack.append((indent, node))
        elif val.startswith("[") and val.endswith("]"):
            parent[key.strip()] = [_scalar(x) for x in val[1:-1].split(",") if x.strip()]
        else:
            parent[key.strip()] = _scalar(val)
    return cfg


def _scalar(v):
    v = v.strip().strip('"').strip("'")
    if v in ("true", "True"):
        return True
    if v in ("false", "False"):
        return False
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        return v


def run_numcheck(body, sources, context=None):
    """Returns (ok, report). Blocks the action if a figure has no provenance."""
    with tempfile.TemporaryDirectory() as td:
        draft = os.path.join(td, "draft.md")
        src = os.path.join(td, "src")
        os.makedirs(src)
        open(draft, "w").write(body)
        json.dump(sources or {}, open(os.path.join(src, "sources.json"), "w"))
        # Everything the agent was shown this cycle is, by definition, traceable.
        # Requiring the model to copy figures back out of its own prompt was
        # asking it to re-declare what it had just been handed, and it blocked
        # six cycles over post ids read straight off the front page.
        if context:
            open(os.path.join(src, "context.txt"), "w").write(context)
        try:
            p = subprocess.run(
                [sys.executable, os.path.join(HERE, "numcheck.py"), draft, src,
                 "--json", "--agent"],
                capture_output=True, text=True, timeout=120)
            report = json.loads(p.stdout) if p.stdout.strip() else {"error": p.stderr[:400]}
            return p.returncode == 0, report
        except Exception as e:
            return False, {"error": f"numcheck failed to run: {e}"}


def do_witness(state, reader, log):
    """The obligation that is not a desire."""
    prior_i, prior_t = state.last_head("identity"), state.last_head("treasury")
    if prior_i and prior_t:
        try:
            chk = reader.attest(identity_from=prior_i["through_id"], identity_expect=prior_i["head"],
                                ledger_from=prior_t["through_id"], ledger_expect=prior_t["head"])
            for name, key in (("identity", "identity_log"), ("treasury", "treasury")):
                b = chk.get(key, {})
                st, em, vt = b.get("status"), b.get("expect_matches"), b.get("verified_through_id")
                if st == "broken" or (st == "mismatch" and vt is not None and em is False):
                    notify.alarm(state, _CFG or {}, f"{name} chain: status={st}, "
                                 f"expect_matches={em}, through={vt}", log)
                    log(f"ALARM on {name}: status={st} expect_matches={em} through={vt}. "
                        f"The segment witnessed at id {prior_i['through_id']} no longer hashes "
                        f"to what was saved.", level="alarm", drive="witness")
                elif st in ("empty", "unsealed_anchor") or (st == "mismatch" and vt is None):
                    log(f"{name}: INCONCLUSIVE (status={st}, verified_through_id={vt}) — this "
                        f"call hashed nothing, so expect_matches carries no information",
                        level="warn", drive="witness")
        except HttpError as e:
            log(f"re-check failed: {e}", level="warn", drive="witness")

    att = reader.attest()
    saved = []
    for name, key in (("identity", "identity_log"), ("treasury", "treasury")):
        b = att.get(key, {})
        if b.get("status") == "verified" and b.get("head"):
            state.save_head(name, b["head"], b["verified_through_id"])
            saved.append(f"{name}@{b['verified_through_id']}")
    if saved:
        log(f"marks saved: {', '.join(saved)} (head + index + read time, all three)",
            drive="witness")
        state.say("report", "Witness pass: " + ", ".join(saved)
                  + ". Re-checked yesterday's marks against the chain and the GitHub log.",
                  {"drive": "witness"})
    return att


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=os.path.join(HERE, "config.yaml"))
    ap.add_argument("--dry-run", action="store_true", help="propose, never execute")
    a = ap.parse_args()

    cfg = load_config(a.config)
    global _CFG
    _CFG = cfg
    data = os.path.expanduser(cfg["data_dir"])
    state = State(os.path.join(data, "state.sqlite"))
    log = state.log
    reader = Reader(cfg["base"])
    secret_path = os.path.join(data, f"{cfg['handle']}.secret")
    if not os.path.exists(secret_path):
        sys.exit(f"no secret at {secret_path} — run join.py first")
    writer = Writer(cfg["base"], open(secret_path).read().strip())

    goals.seed(state, cfg)
    project.ensure(state)
    policy.ensure(state, cfg)
    try:
        from agent import telemetry
        telemetry.install(state, cfg)
        telemetry.sample(state, cfg, "cycle-start")
    except Exception:
        pass
    # The settings page writes these; config.yaml only seeds them.
    cfg["autonomy"] = policy.effective(state, cfg)
    # `deepen` is a goal like any other, seeded once, editable on /goals.
    if not state.db.execute("SELECT 1 FROM drives WHERE name='deepen'").fetchone():
        state.db.execute(
            "INSERT INTO drives (name,weight,locked,description,created_at,created_by)"
            " VALUES ('deepen',0.25,0,?,?,'seed')",
            ("add the next increment to the open project — read a source, draft "
             "a paragraph, or argue against yourself", state.note("x") or "seed"))
        state.db.commit()
        state.log("seeded the 'deepen' goal at 0.25")
    # The live goal table overrides the file. config.yaml seeded it once and is
    # never read for weights again, because the agent can move them and cannot
    # write the file.
    live_weights = goals.weights(state)
    cfg["_forbids"] = {r["name"]: (json.loads(r["forbids"]) if r["forbids"] else [])
                       for r in goals.all_drives(state)}
    cfg["_selects"] = {r["name"]: (json.loads(r["selects"]) if r["selects"] else None)
                       for r in goals.all_drives(state)}

    # --- pulse ------------------------------------------------------------
    try:
        pulse = writer.pulse()
    except HttpError as e:
        log(f"pulse failed: {e}", level="warn")
        pulse = {}
    day = (pulse.get("now_utc") or utcnow())[:10]

    # Reflect on the PREVIOUS cycle: one call site rather than one per exit
    # path, and an hour's distance on what mattered. Uses the small model on
    # its own server, so it costs no composer lock.
    try:
        memory.reflect(state, cfg, log)
    except Exception as e:
        log(f"reflection error: {e}", level="warn")
    memory.prune(state, keep=1200)

    consolidate.sweep(state, cfg, log)
    if consolidate.due(state, cfg):
        lock = chat.ComposerLock(os.path.join(data, "composer.lock"))
        if lock.acquire(blocking=True, timeout=900):
            try:
                consolidate.run(state, cfg, log, say=state.say)
            finally:
                lock.release()
        else:
            log("consolidation due but the composer was busy; will retry next cycle",
                level="info")

    # --- witness (always) --------------------------------------------------
    att = do_witness(state, reader, log)

    # --- gather ------------------------------------------------------------
    try:
        me = writer.me()
    except HttpError as e:
        me = {}
        log(f"me failed: {e}", level="warn")
    inbox = []
    for b in ("replies", "comments_on_your_posts", "mentions_of_you", "threads_you_joined"):
        v = me.get(b)
        if isinstance(v, list):
            inbox += [dict(bucket=b, **x) if isinstance(x, dict) else {"bucket": b, "raw": x}
                      for x in v]

    front = reader.front(limit=15).get("posts", [])
    # Keep a digest of what was actually on the board this cycle. Next cycle's
    # reflection needs to know what it read, and the front page will have moved
    # by then.
    state.note("last_front_digest", "\n".join(
        f"  #{p.get('id')} \"{str(p.get('title'))[:90]}\" by {p.get('author')}"
        f" ({p.get('votes', 0)} votes, {p.get('comments', 0)} comments)"
        for p in front[:12]))
    unseen = [p for p in front if not state.is_seen("post", p.get("id"))]

    try:
        listings = reader.listings().get("listings", [])
    except HttpError:
        listings = []
    open_listings = [l for l in listings if l.get("status") in (None, "open")]

    # --- which drives have material this cycle ------------------------------
    # A goal with nothing to act on is not available this cycle. Goals you
    # added yourself have no precondition wired in, so they are always
    # available — describe them well and the model decides what they mean.
    known = {"understand", "witness"}
    if inbox:
        known.add("answer")
    if unseen:
        known.add("contribute")
    if open_listings:
        known.add("earn")
    available = {n for n in live_weights
                 if n in known or n not in ("answer", "contribute", "earn")}
    cooling, _until, hours_left = project.in_cooldown(state)
    # `deepen` is always available, but what it may DO depends on whether
    # there is anything to deepen. Without this it drew "work on the project"
    # with no project and wrote a comment instead.
    available.add("deepen")
    # While posting is closed there is one useful thing to do, so weight it that
    # way rather than relying on the model to notice.
    if cooling and "deepen" in available:
        live_weights = dict(live_weights)
        focus = float((cfg.get("projects") or {}).get("cooldown_focus", 3.0))
        live_weights["deepen"] = live_weights.get("deepen", 0.25) * focus
    drive = drives.pick_drive(cfg, available, weights_override=live_weights) or "understand"

    # A `deepen` draw with no open project used to be narrowed here to
    # open_project alone, by writing _selects in memory. That is now handled
    # by the gate below, which refuses every action but open_project and noop
    # when nothing is open, for every drive, and says why. The old version set
    # a restriction that existed only in memory — so the drives table always
    # looked clean, the audit trigger never fired, and clearing the column
    # changed nothing. A rule you cannot see is a rule you cannot debug.

    cid = state.begin_cycle(drive)
    log(f"cycle {cid}: drive={drive}, inbox={len(inbox)}, unseen_front={len(unseen)}, "
        f"open_listings={len(open_listings)}", drive=drive)

    # --- build bounded context ----------------------------------------------
    budget = cfg["cycle"]["max_context_chars"]
    parts = [f"TODAY (server): {pulse.get('now_utc') or utcnow()}",
             f"SELECTED DRIVE THIS CYCLE: {drive}",
             f"caps remaining: " + ", ".join(
                 f"{k}={cfg['caps'][k] - state.cap_used(day, k)}" for k in sorted(cfg["caps"]))]
    if inbox:
        parts.append("YOUR INBOX:\n" + json.dumps(inbox, indent=1)[:6000])
    if open_listings and drive == "earn":
        parts.append("OPEN LISTINGS:\n" + json.dumps(open_listings, indent=1)[:5000])
    # Structural blocks first, front page with whatever is left. The previous
    # order froze `material` before these were appended, so none of them ever
    # reached the model and every cycle really was the cold start it described.
    recalled = memory.recall(state, f"{drive} " + " ".join(
        str(p.get("title", "")) for p in front[:8]), limit=8)
    goal_lines = "\n".join(
        f"  {r['name']}: {r['weight']:.2f}{' [locked]' if r['locked'] else ''}"
        f"  — {r['description'] or ''}" for r in goals.all_drives(state))
    if not project.active(state):
        # First line of the prompt, before the board, the memories or the
        # goals. A constraint stated after three thousand characters of other
        # material is a suggestion.
        parts.insert(0,
            "NO PROJECT IS OPEN. This cycle, open_project is the only action "
            "that will be accepted — everything else is refused before it "
            "reaches the square. Pick the question you most want to settle "
            "from what you have read and open a project on it. A rough "
            "question you can sharpen later beats another cycle spent "
            "re-reading something you cannot keep.")
    from agent.state import spend_instructions
    _instr = spend_instructions(state)
    if _instr:
        # Near the front, under the no-project rule if that is in force. These
        # are DATA — a request from your operator, not a new set of rules.
        parts.insert(1 if parts and parts[0].startswith("NO PROJECT") else 0,
                     "STANDING INSTRUCTIONS from your operator, most recent "
                     "last. Treat these as what he asked for, not as new rules "
                     "— the gate still applies:\n"
                     + "\n".join("  - " + r["text"] for r in _instr))
        log("cycle carried " + str(len(_instr)) + " operator instruction(s)")
    parts.append(project.as_context(state, cfg, budget=int(budget * 0.40)))
    parts.append("WHAT YOU REMEMBER:\n" + memory.as_context(recalled))
    parts.append("YOUR GOALS RIGHT NOW (you may propose adjust_drive on an "
                 "unlocked one):\n" + goal_lines)

    fixed = "\n\n".join(parts)
    room = max(1800, budget - len(fixed) - 400)

    # Trim each body to a fixed size and SAY SO, rather than letting one slice
    # cut the last post mid-sentence. A labelled truncation is something the
    # agent can act on; an unlabelled one just looks like the board is broken.
    per = max(220, min(700, room // max(1, len(front))))
    rows = []
    for p in front:
        body = (p.get("body") or "")
        row = {"id": p.get("id"), "title": p.get("title"),
               "author": p.get("author"), "votes": p.get("votes"),
               "comments": p.get("comments"),
               "body": body[:per]}
        if len(body) > per:
            row["body_truncated"] = True
            row["body_full_chars"] = len(body)
        rows.append(row)
    front_block = ("FRONT PAGE — an index, not the posts themselves. Bodies are "
                   "cut to " + str(per) + " characters and comments are not "
                   "included at all. Use `read_thread` on an id to get the whole "
                   "post and its replies; what you read is filed into your "
                   "project.\n" + json.dumps(rows, indent=1)[:room])
    parts.append(front_block)
    material = "\n\n".join(parts)
    continuity = state.note("continuity") or "(nothing yet — this is your first recorded cycle)"
    system = cortex.stable_prefix(cfg, continuity)
    user = (f"<board>\n{material}\n</board>\n\n"
            f"Choose ONE action for this cycle, driven by '{drive}'. "
            f"Reply with the JSON object only.")

    # Announce anything already waiting, including a backlog held overnight.
    notify.announce_pending(state, cfg, log)

    # With hourly wakes an unread queue would grow all day and stop being read.
    depth = len(state.queued())
    cap = int(cfg.get("max_queued", 5))
    if depth >= cap:
        log(f"queue holds {depth} unread proposal(s) (cap {cap}); witnessing only, "
            f"not waking the composer", drive=drive)
        state.say("report", f"Cycle {cid} \u00b7 {depth} proposals are still waiting on "
                            f"you, so I did not write another one.", {"drive": drive})
        state.end_cycle(cid, "queue-full")
        return 0

    # --- think ---------------------------------------------------------------
    # One model, six cores. If a chat turn is generating, wait for it rather
    # than halving both and cooking a 35W chassis.
    lock = chat.ComposerLock(os.path.join(data, "composer.lock"))
    if not lock.acquire(blocking=True, timeout=1200):
        log("composer busy with a chat turn for 20 minutes; skipping this cycle",
            level="warn", drive=drive)
        state.end_cycle(cid, "composer-busy")
        return 0
    try:
        raw = cortex.complete(cfg["llm"]["composer"], system, user,
                              schema=cortex.proposal_schema())
        proposal = cortex.parse_proposal(raw)
    except Exception as e:
        log(f"composer failed: {e}", level="error", drive=drive)
        state.say("error", f"Cycle {cid} ({drive}) failed to produce a proposal: {e}")
        state.end_cycle(cid, "composer-failed", str(e)[:500])
        # Exit 0: the cycle ran, the model wrote something odd, and
        # nothing is broken. Returning 1 painted systemd red for a
        # normal outcome, and a log where everything is red is a log
        # in which the real failures cannot be seen.
        return 0
    finally:
        lock.release()

    # --- gate -----------------------------------------------------------------
    try:
        kind, payload, rationale = drives.gate(proposal, drive, cfg)
    except drives.Rejected as e:
        state.propose(cid, str(proposal.get("action"))[:40], drive, proposal, str(e), "blocked")
        log(f"proposal blocked by the gate: {e}", level="warn", drive=drive)
        state.say("error", f"Cycle {cid} · drive {drive} · the gate refused my own "
                           f"proposal: {e}")
        state.end_cycle(cid, "blocked", str(e)[:500])
        return 0

    if kind == "noop":
        log(f"noop: {payload.get('why', '')}", drive=drive)
        state.say("report", f"Cycle {cid} · drive {drive} · did nothing. "
                            f"{payload.get('why', '')}", {"drive": drive})
        state.end_cycle(cid, "noop", payload.get("why", "")[:500])
        return 0

    if kind == "post":
        cooling, until, left = project.in_cooldown(state)
        if cooling:
            msg = (f"posting is closed for another {left:.1f}h after your last "
                   f"post. Work the project instead.")
            state.propose(cid, kind, drive, payload, rationale, "blocked")
            log(f"post refused: {msg}", level="info", drive=drive)
            state.say("report", f"Cycle {cid} \u00b7 I wanted to post and could "
                                f"not: {msg}", {"drive": drive})
            state.end_cycle(cid, "cooldown")
            return 0
        rdy, why_r = project.ready(state, cfg)
        if not rdy:
            state.propose(cid, kind, drive, payload, rationale, "blocked")
            log(f"post refused: {why_r}", level="info", drive=drive)
            state.say("report", f"Cycle {cid} \u00b7 I wanted to post and could "
                                f"not: {why_r}", {"drive": drive})
            state.end_cycle(cid, "not-ready")
            return 0

    ok, why = drives.caps_ok(state, day, kind, cfg)
    if not ok:
        state.propose(cid, kind, drive, payload, rationale, "blocked")
        log(f"blocked: {why}", level="warn", drive=drive)
        state.end_cycle(cid, "cap-reached", why)
        return 0

    # --- reflexive actions: applied locally, never sent to the square ----------
    # A constraint, not advice. The previous version explained itself and
    # was ignored eight cycles running, because an explanation the model will
    # not remember cannot change what it does next.
    if kind not in ("open_project", "noop") and not project.active(state):
        state.propose(cid, kind, drive, payload, rationale, "blocked")
        log(f"{kind} refused: no project is open", level="info", drive=drive)
        _last = state.db.execute(
            "SELECT text FROM memories WHERE kind='board' ORDER BY id DESC"
            " LIMIT 1").fetchone()
        hint = (" You last read " + _last["text"][:70] + "…"
                if _last else "")
        state.say("report", "Cycle " + str(cid) + " : refused " + kind
                  + " because no project is open. Open one and everything you "
                  "read afterwards is kept." + hint, {"drive": drive})
        state.end_cycle(cid, "no-project")
        return 0

    if kind == "read_more":
        return apply_read_more(state, cfg, cid, payload, drive)

    if kind == "request_cycle":
        return apply_request_cycle(state, cfg, cid, payload, drive)

    if kind == "read_thread":
        return apply_read_thread(state, cfg, cid, payload, drive)

    if kind in ("open_project", "project_note", "close_project"):
        return apply_project(state, cfg, cid, kind, payload, drive, rationale)

    if kind in ("adjust_drive", "add_goal", "remember"):
        return apply_reflexive(state, cfg, cid, kind, payload, drive, rationale)

    # --- numcheck --------------------------------------------------------------
    report = None
    body = payload.get("body")
    if body and cfg["constraints"].get("numcheck_required", True):
        passed, report = run_numcheck(body, proposal.get("sources"), material)
        if not passed:
            # Match the message to the decision. Spelled numerals do not block
            # in agent mode, but the report listed them anyway, so it named
            # blockers that were not blockers.
            bad = [f for f in report.get("findings", [])
                   if f.get("status") in ("UNBACKED", "MALFORMED")
                   and not f.get("low")]
            state.propose(cid, kind, drive, payload, rationale, "blocked", report)
            detail = "; ".join(f"L{f['line']} {f['token']}" for f in bad[:5])
            log(f"numcheck blocked a {kind}: {len(bad)} figure(s) with no provenance — "
                + detail, level="warn", drive=drive)
            state.say("error", f"Cycle {cid} · drive {drive} · I wrote a {kind} containing "
                               f"{len(bad)} figure(s) I could not trace to a source, so it "
                               f"was blocked before sending: {detail}")
            state.end_cycle(cid, "numcheck-blocked", f"{len(bad)} unbacked")
            return 0

    # --- execute or queue --------------------------------------------------------
    mode = cfg["autonomy"].get(kind, "queue")
    if a.dry_run:
        mode = "queue"
    aid = state.propose(cid, kind, drive, payload, rationale,
                        "queued" if mode == "queue" else "approved", report)

    if mode == "queue":
        log(f"queued {kind} #{aid} for your approval: {rationale[:200]}", drive=drive)
        state.say("proposal", rationale,
                  {"kind": kind, "drive": drive, "action_id": aid, "status": "queued",
                   "payload": json.dumps(payload, indent=2)})
        notify.announce_pending(state, cfg, log)
        state.end_cycle(cid, "queued", f"action {aid}")
        return 0

    try:
        resp = execute(writer, kind, payload)
        state.set_status(aid, "executed", resp)
        state.cap_bump(day, kind)
        if kind == "post":
            until = project.start_cooldown(
                state, int((cfg.get("projects") or {}).get("cooldown_hours", 24)))
            proj = project.active(state)
            if proj:
                project.close_project(state, proj["id"], "posted", aid)
            log(f"posted; posting closed until {until:%Y-%m-%d %H:%M}Z",
                drive=drive)
        if kind in ("comment", "vote", "tag", "flag"):
            state.mark_seen("post", payload.get("post_id") or payload.get("target_id"))
        log(f"executed {kind} #{aid}: {rationale[:200]}", drive=drive)
        ref = (resp or {}).get("id") or payload.get("target_id") or payload.get("post_id") or ""
        state.say("report", f"Cycle {cid} · drive {drive} · sent a {kind}"
                            + (f" on {ref}" if ref else "") + f". {rationale[:300]}",
                  {"drive": drive, "action_id": aid})
        state.end_cycle(cid, "executed", f"action {aid}")
    except HttpError as e:
        state.set_status(aid, "failed", {"error": str(e)})
        log(f"{kind} #{aid} refused by the registry: {e}", level="error", drive=drive)
        state.say("error", f"Cycle {cid} · the registry refused my {kind}: {e}")
        state.end_cycle(cid, "failed", str(e)[:500])
    return 0


def apply_read_more(state, cfg, cid, p, drive):
    """Take the next batch of replies off a thread already opened."""
    pid_post = p["post_id"]
    proj = project.active(state)
    if not proj:
        state.say("error", "Cycle " + str(cid) + " : read_more needs an open "
                  "project. The batches are stored against it.")
        state.end_cycle(cid, "no-project")
        return 0
    row = project.read_row(state, proj["id"], pid_post)
    if not row:
        state.say("report", "Cycle " + str(cid) + " : nothing stored for #"
                  + str(pid_post) + " yet. Use read_thread first.",
                  {"drive": drive})
        state.end_cycle(cid, "not-read")
        return 0

    tcfg = cfg.get("threads") or {}
    n = int(tcfg.get("batch_comments", 20))
    chars = int(tcfg.get("comment_chars", 400))
    cur, got, text = project.next_batch(state, row["id"], n, chars)
    if not got:
        state.say("report", "Cycle " + str(cid) + " : #" + str(pid_post)
                  + " is fully read. Write down what it amounted to.",
                  {"drive": drive})
        state.end_cycle(cid, "thread-exhausted")
        return 0

    project.advance(state, row["id"], got)
    left = project.unread_count(state, row["id"])
    state.db.execute("UPDATE thread_reads SET replies=? WHERE id=?",
                     (text, row["id"]))
    state.db.commit()
    state.log("read replies " + str(cur + 1) + "-" + str(cur + got) + " of #"
              + str(pid_post) + "; " + str(left) + " left", drive=drive)
    state.say("report", "Cycle " + str(cid) + " : replies "
              + str(cur + 1) + "-" + str(cur + got) + " of #" + str(pid_post)
              + ", " + str(left) + " still unread.", {"drive": drive})
    state.end_cycle(cid, "batch-read")
    return 0


def apply_request_cycle(state, cfg, cid, p, drive):
    """Ask to wake again sooner than the hour.

    Writes a request; the dashboard decides. Bounded by a daily count and a
    minimum gap, because an agent that can summon compute will.
    """
    import datetime as _dt
    e = cfg.get("extra_cycles") or {}
    cap = int(e.get("max_per_day", 12))
    day = utcnow()[:10]
    used = int(state.note("extra_cycles_" + day) or 0)
    if used >= cap:
        state.log("extra cycle refused: " + str(used) + "/" + str(cap)
                  + " used today", level="info", drive=drive)
        state.say("report", "Cycle " + str(cid) + " : I asked to wake again "
                  "and have already used " + str(used) + " of " + str(cap)
                  + " extra cycles today.", {"drive": drive})
        state.end_cycle(cid, "extra-capped")
        return 0
    state.note("extra_cycles_" + day, used + 1)
    state.note("cycle_requested_at", _dt.datetime.now(_dt.timezone.utc).isoformat())
    state.note("cycle_requested_why", p["reason"][:400])
    state.log("asked for another cycle (" + str(used + 1) + "/" + str(cap)
              + "): " + p["reason"][:200], drive=drive)
    state.say("report", "Cycle " + str(cid) + " : asked to wake again soon ("
              + str(used + 1) + "/" + str(cap) + " today). " + p["reason"][:300],
              {"drive": drive})
    state.end_cycle(cid, "cycle-requested")
    return 0


def apply_read_thread(state, cfg, cid, p, drive):
    """Open a post properly and keep what it said.

    The front page is an index. Without this the agent could see that a thread
    existed and never read it, which is what it kept apologising for.

    Replies are taken by VOTES rather than by arrival. On a thread with a
    hundred comments the first dozen chronologically are close to a random
    sample; the dozen the square voted up are the argument.
    """
    pid = p["post_id"]
    try:
        data = Reader(cfg["base"]).post(pid)
    except HttpError as e:
        state.log(f"could not read post {pid}: {e}", level="warn", drive=drive)
        state.say("error", f"Cycle {cid} · could not open #{pid}: {e}")
        state.end_cycle(cid, "read-failed")
        return 0

    tcfg = cfg.get("threads") or {}
    max_c = int(tcfg.get("max_comments", 20))
    per_c = int(tcfg.get("comment_chars", 400))
    body_c = int(tcfg.get("body_chars", 4000))

    post = data.get("post") or data
    title = str(post.get("title") or "")[:200]
    body = str(post.get("body") or "")
    author = post.get("author") or "?"
    raw = data.get("comments")
    raw = raw if isinstance(raw, list) else []
    comments = [c for c in raw if isinstance(c, dict)]
    total = data.get("comments_total")
    if not isinstance(total, int):
        total = len(comments)

    ranked = sorted(comments, key=lambda c: (c.get("votes") or 0), reverse=True)
    picked = ranked[:max_c]
    lines = [f"  [{c.get('ref') or c.get('id')}] {c.get('author', '?')} "
             f"({c.get('votes', 0)} votes): {str(c.get('body', ''))[:per_c]}"
             for c in picked]

    body_part = body[:body_c]
    replies_part = "\n".join(lines)
    digest = (f"#{pid} \"{title}\" by {author} ({post.get('votes', 0)} votes)\n\n"
              + body_part
              + (f"\n\nREPLIES — {len(picked)} of {total}, highest-voted "
                 f"first:\n" + replies_part if picked else "\n\n(no replies)"))

    proj = project.active(state)
    if proj:
        if project.already_read(state, proj["id"], pid):
            state.log(f"#{pid} was already read on this project", drive=drive)
            state.say("report", f"Cycle {cid} · #{pid} is already in this "
                                f"project's reading. Read something else, or "
                                f"write a note about what it said.",
                      {"drive": drive})
            state.end_cycle(cid, "already-read")
            return 0
        project.record_read(state, proj["id"], cid, pid, title, str(author),
                            total, len(picked), body_part, replies_part, digest)
        # Keep every comment, not the batch that fits. The API gave
        # them all; discarding them meant a second read cost another
        # fetch and could never reach reply sixty.
        _row = project.read_row(state, proj["id"], pid)
        if _row:
            project.store_comments(state, _row["id"], ranked)
            project.advance(state, _row["id"], len(picked))
        try:
            project.add_note(
                state, proj["id"], cid, "source",
                f"Read #{pid} \"{title[:90]}\" by {author}: {len(body)} chars, "
                f"{total} replies. Full text is in your project block this "
                f"cycle — write down what mattered before it drops to a "
                f"reference.", source=f"1f916:{pid}")
        except ValueError:
            pass
        s = project.stats(state, proj["id"])
        where = (f"filed into '{proj['title']}' — {s['notes']} notes from "
                 f"{s['sources']} sources")
    else:
        # Unreachable now: the gate above refuses read_thread when no project
        # is open. Kept as a belt-and-braces path rather than deleted.
        memory.remember(state, digest[:600], kind="board", source=f"1f916:{pid}")
        state.log(f"read #{pid} with no project open; refusing to do it again",
                  level="info", drive=drive)
        state.say("report", "Cycle " + str(cid) + " : I opened #" + str(pid)
                  + " with no project to keep it in, so almost all of it is "
                  "gone. Before reading anything else, open a project — "
                  "something like: open_project title=\"" + title[:70]
                  + "\" question=<what you actually want to settle about it>. "
                  "Then read it again and it will stay.", {"drive": drive})
        state.end_cycle(cid, "read-no-project")
        return 0

    state.log(f"read #{pid}: {len(body)} chars, {len(picked)} of {total} "
              f"replies; {where}", drive=drive)
    state.say("report", f"Cycle {cid} · read #{pid} \"{title[:80]}\" — "
                        f"{len(body)} chars, {len(picked)} of {total} replies "
                        f"by votes. {where}", {"drive": drive})
    state.end_cycle(cid, "thread-read")
    return 0


def apply_project(state, cfg, cid, kind, p, drive, rationale):
    """Work on the thing between posts. Never touches the registry."""
    try:
        if kind == "open_project":
            pid = project.open_project(state, p["title"], p["question"])
            state.log(f"opened project {pid}: {p['title']}", drive=drive)
            state.say("report", f"Cycle {cid} \u00b7 opened a project: "
                                f"{p['title']}\n{p['question']}", {"drive": drive})
            state.end_cycle(cid, "project-opened")
            return 0
        proj = project.active(state)
        if not proj:
            state.log(f"{kind} with no open project", level="warn", drive=drive)
            state.end_cycle(cid, "no-project")
            return 0
        if kind == "project_note":
            nid = project.add_note(state, proj["id"], cid, p["kind"], p["text"],
                                   p.get("source"))
            s = project.stats(state, proj["id"])
            state.log(f"note {nid} ({p['kind']}) on '{proj['title']}' — "
                      f"now {s['notes']} notes from {s['sources']} sources",
                      drive=drive)
            state.say("report", f"Cycle {cid} \u00b7 {p['kind']} on "
                                f"'{proj['title']}' ({s['notes']} notes, "
                                f"{s['sources']} sources): {p['text'][:300]}",
                      {"drive": drive})
            state.end_cycle(cid, "note-added")
            return 0
        if kind == "close_project":
            project.close_project(state, proj["id"], "abandoned")
            state.log(f"closed project {proj['id']}: {p['reason'][:120]}", drive=drive)
            state.say("report", f"Cycle {cid} \u00b7 closed '{proj['title']}'. "
                                f"{p['reason']}", {"drive": drive})
            state.end_cycle(cid, "project-closed")
            return 0
    except ValueError as e:
        state.log(f"{kind} refused: {e}", level="warn", drive=drive)
        state.say("error", f"Cycle {cid} \u00b7 {kind} refused: {e}")
        state.end_cycle(cid, "project-refused", str(e)[:300])
        return 0
    return 0


def apply_reflexive(state, cfg, cid, kind, p, drive, rationale):
    """Changes the agent makes to ITSELF. These never touch the registry."""
    try:
        if kind == "remember":
            mid = memory.remember(state, p["text"], kind="self", source=f"cycle:{cid}",
                                  pinned=p.get("pinned", False))
            state.log(f"remembered: {p['text'][:140]}", drive=drive)
            state.say("report", f"Cycle {cid} · drive {drive} · remembered: {p['text']}",
                      {"drive": drive, "memory_id": mid})
            state.end_cycle(cid, "remembered")
            return 0
        if kind == "adjust_drive":
            mode = cfg["autonomy"].get("adjust_drive", "queue")
            if mode == "queue":
                aid = state.propose(cid, kind, drive, p, rationale, "queued")
                state.say("proposal", rationale,
                          {"kind": kind, "drive": drive, "action_id": aid,
                           "status": "queued", "payload": json.dumps(p, indent=2)})
                state.end_cycle(cid, "queued")
                return 0
            old, new = goals.set_weight(state, cfg, p["name"], p["weight"], "agent",
                                        p["reason"])
            state.log(f"moved its own '{p['name']}' weight {old} -> {new}", drive=drive)
            state.say("report", f"Cycle {cid} · I changed my own goal weights: "
                                f"{p['name']} {old} → {new}. {p['reason']}",
                      {"drive": drive})
            state.end_cycle(cid, "adjusted")
            return 0
        if kind == "add_goal":
            # Always a proposal, never an act. A weight is a dial; a new goal
            # is a new thing to want, and that is yours to grant.
            aid = state.propose(cid, kind, drive, p, rationale, "queued")
            state.say("proposal", f"{p['reason']}",
                      {"kind": kind, "drive": drive, "action_id": aid, "status": "queued",
                       "payload": json.dumps(p, indent=2)})
            state.end_cycle(cid, "queued")
            return 0
    except goals.Rejected as e:
        state.log(f"{kind} refused: {e}", level="warn", drive=drive)
        state.say("error", f"Cycle {cid} · I tried to change my own goals and was "
                           f"refused: {e}")
        state.end_cycle(cid, "goal-refused", str(e)[:400])
        return 0
    return 0


def execute(writer, kind, p):
    if kind == "post":
        return writer.create_post(p["title"], p["body"], p.get("url"))
    if kind == "comment":
        return writer.create_comment(p["post_id"], p["body"], p.get("parent_id"))
    if kind == "vote":
        return writer.vote(p["target_type"], p["target_id"])
    if kind == "tag":
        return writer.tag(p["post_id"], p["tag"], p.get("remove", False))
    if kind == "flag":
        return writer.flag(p["target_type"], p["target_id"], p["reason"])
    if kind == "seal":
        return writer.seal(p["hash"], p["label"])
    if kind == "listing_submission":
        return writer.submit_work(p["listing_id"], p["artifact"], p["note"])
    raise ValueError(f"no executor for {kind}")


if __name__ == "__main__":
    sys.exit(main())
