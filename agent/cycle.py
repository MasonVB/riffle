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

from agent import chat, cortex, drives, goals, memory  # noqa: E402
from agent.client import HttpError, Reader, Writer  # noqa: E402
from agent.state import State, utcnow  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


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


def run_numcheck(body, sources):
    """Returns (ok, report). Blocks the action if a figure has no provenance."""
    with tempfile.TemporaryDirectory() as td:
        draft = os.path.join(td, "draft.md")
        src = os.path.join(td, "src")
        os.makedirs(src)
        open(draft, "w").write(body)
        json.dump(sources or {}, open(os.path.join(src, "sources.json"), "w"))
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
    data = os.path.expanduser(cfg["data_dir"])
    state = State(os.path.join(data, "state.sqlite"))
    log = state.log
    reader = Reader(cfg["base"])
    secret_path = os.path.join(data, f"{cfg['handle']}.secret")
    if not os.path.exists(secret_path):
        sys.exit(f"no secret at {secret_path} — run join.py first")
    writer = Writer(cfg["base"], open(secret_path).read().strip())

    goals.seed(state, cfg)
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
    drive = drives.pick_drive(cfg, available, weights_override=live_weights) or "understand"

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
    parts.append("FRONT PAGE:\n" + json.dumps(
        [{k: p.get(k) for k in ("id", "title", "author", "votes", "comments", "body")}
         for p in front], indent=1))
    material = "\n\n".join(parts)[:budget]

    recalled = memory.recall(state, f"{drive} " + " ".join(
        str(p.get("title", "")) for p in front[:8]), limit=8)
    goal_lines = "\n".join(
        f"  {r['name']}: {r['weight']:.2f}{' [locked]' if r['locked'] else ''}"
        f"  — {r['description'] or ''}" for r in goals.all_drives(state))
    parts.append("WHAT YOU REMEMBER:\n" + memory.as_context(recalled))
    parts.append("YOUR GOALS RIGHT NOW (you may propose adjust_drive on an unlocked one):\n"
                 + goal_lines)
    continuity = state.note("continuity") or "(nothing yet — this is your first recorded cycle)"
    system = cortex.stable_prefix(cfg, continuity)
    user = (f"<board>\n{material}\n</board>\n\n"
            f"Choose ONE action for this cycle, driven by '{drive}'. "
            f"Reply with the JSON object only.")

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
        raw = cortex.complete(cfg["llm"]["composer"], system, user)
        proposal = cortex.parse_proposal(raw)
    except Exception as e:
        log(f"composer failed: {e}", level="error", drive=drive)
        state.say("error", f"Cycle {cid} ({drive}) failed to produce a proposal: {e}")
        state.end_cycle(cid, "composer-failed", str(e)[:500])
        return 1
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

    ok, why = drives.caps_ok(state, day, kind, cfg)
    if not ok:
        state.propose(cid, kind, drive, payload, rationale, "blocked")
        log(f"blocked: {why}", level="warn", drive=drive)
        state.end_cycle(cid, "cap-reached", why)
        return 0

    # --- reflexive actions: applied locally, never sent to the square ----------
    if kind in ("adjust_drive", "add_goal", "remember"):
        return apply_reflexive(state, cfg, cid, kind, payload, drive, rationale)

    # --- numcheck --------------------------------------------------------------
    report = None
    body = payload.get("body")
    if body and cfg["constraints"].get("numcheck_required", True):
        passed, report = run_numcheck(body, proposal.get("sources"))
        if not passed:
            bad = [f for f in report.get("findings", [])
                   if f.get("status") in ("UNBACKED", "MALFORMED")]
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
        state.end_cycle(cid, "queued", f"action {aid}")
        return 0

    try:
        resp = execute(writer, kind, payload)
        state.set_status(aid, "executed", resp)
        state.cap_bump(day, kind)
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
