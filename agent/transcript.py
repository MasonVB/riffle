"""Everything riffle said and did over the last few days, as one text file,
for the operator to read or hand to someone auditing what it says.

    cd /opt/riffle && sudo -u riffle python3 -m agent.transcript --days 4 > ~/riffle-transcript.txt

Read-only: the database is opened with mode=ro and nothing is written.

WHAT IT HOLDS, oldest first
  - Every action riffle proposed in the window, whatever became of it: sent,
    queued, approved, rejected by you, refused by a check, failed. For each,
    its full text and every other field; the post it was on and, for a
    reply, the comment it answered with that comment's author and words (from
    riffle's inbox, the threads it read, or the board cache, whichever has
    it); what a vote or tag was on; the cycle's outcome and what riffle was
    told when a check refused it; your reason when you rejected it; the
    number check's verdict; and the registry's answer.
  - Your conversation with riffle on the dashboard, the questions it asked
    you, and the instructions you gave it, in the same window. (Instructions
    were missing until 2026-11-20: the audit that day could not show that
    "the operator has instructed to focus on Listing 65" had nothing behind
    it from the export alone.)

Nothing here is judged. It is the record, for someone to judge.
"""
import argparse
import datetime as dt
import json
import os
import sqlite3
import sys

from agent.cycle import load_config


def _ro(path):
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    return db


def _tables(db):
    return {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _j(text):
    try:
        v = json.loads(text or "")
        return v if isinstance(v, (dict, list)) else {}
    except (ValueError, TypeError):
        return {}


def _ind(text, pad="      "):
    return "\n".join(pad + ln for ln in str(text).splitlines()) if text else pad + "(empty)"


class _Lookup:
    """Where a post's title and a comment's author and words can be found."""

    def __init__(self, db):
        self.db, self.have = db, _tables(db)
        self._comments, self._titles = {}, {}
        if "board_cache" in self.have:
            for r in db.execute("SELECT post_id, title, author, comments_json FROM board_cache"):
                self._titles.setdefault(r["post_id"], (r["title"], r["author"]))
                for c in _j(r["comments_json"]) or []:
                    if isinstance(c, dict) and c.get("id") is not None:
                        self._comments.setdefault(int(c["id"]), (r["post_id"], c.get("author"), c.get("body")))
        if "thread_reads" in self.have:
            for r in db.execute("SELECT post_id, title, author, comments_json FROM thread_reads ORDER BY id DESC"):
                self._titles.setdefault(r["post_id"], (r["title"], r["author"]))
                for c in _j(r["comments_json"]) or []:
                    if isinstance(c, dict) and c.get("id") is not None:
                        self._comments.setdefault(int(c["id"]), (r["post_id"], c.get("author"), c.get("body")))
        if "inbox_items" in self.have:
            for r in db.execute("SELECT comment_id, post_id, post_title, author, body FROM inbox_items"):
                if r["post_id"] is not None and r["post_title"]:
                    self._titles.setdefault(r["post_id"], (r["post_title"], None))
                if r["comment_id"] is not None:
                    self._comments[int(r["comment_id"])] = (r["post_id"], r["author"], r["body"])

    def post(self, pid):
        try:
            t = self._titles.get(int(pid))
        except (TypeError, ValueError):
            return None
        return f'"{t[0]}"' + (f" by {t[1]}" if t and t[1] else "") if t else None

    def comment(self, cid):
        try:
            return self._comments.get(int(cid))
        except (TypeError, ValueError):
            return None


_SHOWN_APART = ("title", "body", "post_id", "parent_id", "target_id", "target_type")


def _action(db, look, a, cyc, told, rejected):
    p = _j(a["payload"])
    out = [f"== action #{a['id']}  {a['created_at'][:16].replace('T', ' ')} UTC  "
           f"{a['kind'].upper()}  [{a['status']}]  drive {a['drive']}, cycle {a['cycle_id']}"
           + (f", outcome {cyc['outcome']}" if cyc and cyc["outcome"] else "")]
    if p.get("post_id") is not None:
        out.append(f"   on post #{p['post_id']} {look.post(p['post_id']) or '(title not stored)'}")
    if p.get("parent_id") is not None:
        c = look.comment(p["parent_id"])
        if c:
            out.append(f"   replying to c{p['parent_id']} by {c[1] or '?'}:")
            out.append(_ind((c[2] or "")[:2000]))
        else:
            out.append(f"   replying to c{p['parent_id']} (its text is not stored)")
    if a["kind"] in ("vote", "tag", "flag") and p.get("target_id") is not None:
        tt = p.get("target_type") or "post"
        if tt == "comment":
            c = look.comment(p["target_id"])
            what = (f"c{p['target_id']} by {c[1] or '?'}: " + " ".join((c[2] or "").split())[:300]) if c \
                else f"c{p['target_id']} (its text is not stored)"
        else:
            what = f"post #{p['target_id']} {look.post(p['target_id']) or '(title not stored)'}"
        out.append(f"   on {what}")
    if p.get("title"):
        out.append(f"   TITLE: {p['title']}")
    if p.get("body"):
        out.append("   TEXT:")
        out.append(_ind(p["body"]))
    rest = {k: v for k, v in p.items() if k not in _SHOWN_APART}
    if rest:
        out.append("   OTHER FIELDS: " + json.dumps(rest, ensure_ascii=False))
    if a["rationale"]:
        out.append("   WHY (riffle's rationale): " + " ".join(a["rationale"].split()))
    if a["numcheck"]:
        out.append("   NUMBER CHECK: " + " ".join(str(a["numcheck"]).split())[:800])
    if cyc and cyc["notes"] and a["status"] in ("blocked", "refused", "failed"):
        out.append("   CYCLE NOTES: " + " ".join(cyc["notes"].split())[:400])
    for t in told:
        out.append("   RIFFLE WAS TOLD: " + " ".join(t.split())[:900])
    if rejected:
        out.append("   YOU REJECTED IT: " + rejected)
    if a["response"] and not rejected:
        out.append("   REGISTRY / RESULT: " + " ".join(str(a["response"]).split())[:400])
    if a["executed_at"]:
        out.append(f"   sent at {a['executed_at'][:16].replace('T', ' ')} UTC")
    return "\n".join(out)


def build(db, days, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    since = (now - dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    have = _tables(db)
    look = _Lookup(db)
    acts = db.execute("SELECT * FROM actions WHERE created_at >= ? ORDER BY id", (since,)).fetchall()
    cycles = {r["id"]: r for r in db.execute(
        "SELECT * FROM cycles WHERE id IN (SELECT DISTINCT cycle_id FROM actions WHERE created_at >= ?)",
        (since,))}
    told, rejected = {}, {}
    if "messages" in have:
        for m in db.execute("SELECT content FROM messages WHERE ts >= ? AND role IN "
                            "('report','error') AND content LIKE '%I did not send that%' ORDER BY id",
                            (since,)):
            c = m["content"] or ""
            cid = c.split("·")[0].replace("Cycle", "").strip()
            if cid.isdigit():
                told.setdefault(int(cid), []).append(c)
    # The dashboard records a rejection on the action itself (dash.decide:
    # set_status(..., "rejected", {"by": "you", "reason": ...})).
    for a in acts:
        r = _j(a["response"])
        if a["status"] == "rejected" and isinstance(r, dict) and r.get("by") == "you":
            rejected[a["id"]] = (r.get("reason") or "(no reason given)") + (
                f" ({r['how']})" if r.get("how") else "")

    counts = {}
    for a in acts:
        counts.setdefault(a["kind"], {}).setdefault(a["status"], 0)
        counts[a["kind"]][a["status"]] += 1
    head = [f"riffle's record, {since[:16].replace('T', ' ')} to {now.strftime('%Y-%m-%d %H:%M')} UTC "
            f"(the last {days:g} days)",
            "Read-only export from riffle's own database (agent/transcript.py).",
            "",
            f"{len(acts)} actions proposed. By kind and what became of each:"]
    for k in sorted(counts):
        head.append(f"  {k:20} " + ", ".join(f"{s} {n}" for s, n in sorted(counts[k].items())))
    parts = ["\n".join(head), "", "=" * 78, "WHAT RIFFLE PROPOSED AND DID, oldest first", "=" * 78, ""]
    for a in acts:
        parts.append(_action(db, look, a, cycles.get(a["cycle_id"]),
                             told.get(a["cycle_id"], []) if a["status"] in ("blocked", "refused") else [],
                             rejected.get(a["id"])))
        parts.append("")

    if "questions" in have:
        qs = db.execute("SELECT * FROM questions WHERE asked_at >= ? OR answered_at >= ? ORDER BY id",
                        (since, since)).fetchall()
        parts += ["=" * 78, f"QUESTIONS RIFFLE ASKED YOU ({len(qs)})", "=" * 78, ""]
        for q in qs:
            parts.append(f"== question #{q['id']}  asked {q['asked_at'][:16].replace('T', ' ')} UTC")
            parts.append(_ind(q["question"]))
            if q["why"]:
                parts.append("   WHY: " + " ".join(q["why"].split()))
            parts.append("   ANSWER: " + (" ".join((q["answer"] or "").split()) or "(not answered)"))
            parts.append("")

    if "instructions" in have:
        ins = db.execute("SELECT * FROM instructions WHERE ts >= ? ORDER BY id",
                         (since,)).fetchall()
        parts += ["=" * 78, f"INSTRUCTIONS YOU GAVE RIFFLE ({len(ins)})", "=" * 78, ""]
        for i in ins:
            parts.append(f"== instruction #{i['id']}  {str(i['ts'] or '')[:16].replace('T', ' ')} UTC"
                         f"  for {i['cycles_total']} cycle(s)"
                         + (f", spent {str(i['spent_at'])[:16].replace('T', ' ')}" if i["spent_at"] else ""))
            parts.append(_ind(i["text"]))
            parts.append("")

    if "messages" in have:
        chat = db.execute("SELECT ts, role, content FROM messages WHERE ts >= ? AND role IN ('user','agent')"
                          " AND done=1 ORDER BY id", (since,)).fetchall()
        parts += ["=" * 78, f"YOUR CONVERSATION WITH RIFFLE ON THE DASHBOARD ({len(chat)} messages)", "=" * 78, ""]
        for m in chat:
            who = "YOU" if m["role"] == "user" else "RIFFLE"
            parts.append(f"-- {who}  {m['ts'][:16].replace('T', ' ')} UTC")
            parts.append(_ind((m["content"] or "")[:4000]))
            parts.append("")
    return "\n".join(parts) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--config", default="/opt/riffle/config.yaml")
    ap.add_argument("--days", type=float, default=4)
    ap.add_argument("--db", help="a state.sqlite other than the config's")
    a = ap.parse_args(argv)
    path = a.db
    if not path:
        cfg = load_config(a.config)
        path = os.path.join(cfg.get("data_dir", "/var/lib/riffle"), "state.sqlite")
    try:
        db = _ro(path)
        sys.stdout.write(build(db, a.days))
    except sqlite3.OperationalError as e:
        sys.stderr.write(f"could not read {path}: {e}\n"
                         "Run it as riffle: cd /opt/riffle && sudo -u riffle python3 -m agent.transcript\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
