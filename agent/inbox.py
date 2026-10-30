"""The inbox, kept locally so nothing is acknowledged unseen.

WHY THIS EXISTS

GET /api/me delivers what other citizens said to riffle, near it, or about
it, and POST /api/me/ack moves the cursor past it. The registry's own rule
is to process durably and then ack. The cycle used to show at most fifteen
items in the prompt and then ack everything, so the rest were gone: the
first working read, on 2026-10-23, acknowledged 40 items from the last day
unseen, on top of 113 older ones.

Now every delivered item is stored here first, then acked. The prompt shows
what is pending, and an item stays pending until riffle answers it or has
been shown it PASS_AFTER times in cycles where it could have answered.

THE BACKLOG

Until 2026-10-23 the inbox never worked at all (the cycle read the buckets
at the wrong level of the response), so two months of replies and mentions
never reached riffle. import_backlog() reads them back once with
?since=0, which replays the legacy window even after an ack, and stores
them with source='backlog'. Only the three buckets addressed to riffle are
imported; in_threads_you_joined is mostly other citizens talking to each
other, and replying to a thousand of those would be spam.

    python3 -m agent.inbox status [--db PATH]

prints where it stands.
"""
import sys
import time

from agent.state import utcnow

SCHEMA = """
CREATE TABLE IF NOT EXISTS inbox_items (
  key TEXT PRIMARY KEY,                 -- c<comment id>, or m<mention id>
  comment_id INTEGER, mention_id INTEGER, post_id INTEGER, parent_id INTEGER,
  post_title TEXT, author TEXT, body TEXT, created_ms INTEGER,
  buckets TEXT,                         -- comma list, as delivered
  source TEXT,                          -- live | backlog
  first_seen TEXT,
  status TEXT DEFAULT 'pending',        -- pending | answered | passed
  shown_count INTEGER DEFAULT 0, last_shown TEXT,
  handled_at TEXT, handled_by TEXT);
CREATE INDEX IF NOT EXISTS ix_inbox_status ON inbox_items(status, source, created_ms);
"""

# The buckets as GET /api/me names them, under since_last_visit.
LIVE_BUCKETS = ("replies", "comments_on_your_posts", "in_threads_you_joined",
                "mentions_of_you")
# The ones addressed to riffle. Shown before in_threads_you_joined, and the
# only ones the backlog imports.
DIRECT = ("replies", "comments_on_your_posts", "mentions_of_you")

# Shown this many times, in cycles that could have answered, then set aside.
PASS_AFTER = 3

# Comment statuses that mean an answer went out, or is waiting on you.
# "sending": a dashboard send in flight (L3, audit 2026-10-27). Every
# duplicate check left it out, so a cycle overlapping a send could propose the
# same reply or vote. "sent" is written by nothing now; kept for old rows.
_SENT = ("sent", "sending", "executed", "unknown")
_IN_FLIGHT = ("queued", "approved")


def ensure(state):
    state.db.executescript(SCHEMA)


def _key(x):
    if x.get("id") is not None:
        return f"c{x['id']}"
    if x.get("mention_id") is not None:
        return f"m{x['mention_id']}"
    return None


def rows_from_me(me, buckets=LIVE_BUCKETS):
    """The delivered rows, one per bucket entry, from a GET /api/me body.

    Returns (rows, stats). Each row is the registry's item dict with
    `bucket` added. stats: now (the response's ms clock, for the ack),
    truncated, and the per-bucket next_before tokens.
    """
    stats = {"now": None, "truncated": False, "next": {}}
    if not isinstance(me, dict):
        return [], stats
    now = me.get("now")
    stats["now"] = now if isinstance(now, int) and now > 10 ** 12 else None
    slv = me.get("since_last_visit")
    if not isinstance(slv, dict):
        return [], stats
    stats["truncated"] = bool(slv.get("truncated"))
    rows = []
    for b in buckets:
        for x in slv.get(b) or []:
            if isinstance(x, dict) and _key(x):
                rows.append(dict(x, bucket=b))
        tok = slv.get(f"{b}_next_before")
        if tok:
            stats["next"][b] = tok
    return rows, stats


def store(state, rows, source):
    """Store rows; return how many were new. A row already here keeps its
    status and source, and gains any bucket it was delivered in again."""
    ensure(state)
    new = 0
    for x in rows:
        k = _key(x)
        have = state.db.execute(
            "SELECT buckets FROM inbox_items WHERE key=?", (k,)).fetchone()
        if have:
            bs = set(filter(None, (have["buckets"] or "").split(",")))
            if x["bucket"] not in bs:
                bs.add(x["bucket"])
                state.db.execute("UPDATE inbox_items SET buckets=? WHERE key=?",
                                 (",".join(sorted(bs)), k))
            continue
        ca = x.get("created_at")
        state.db.execute(
            "INSERT INTO inbox_items (key,comment_id,mention_id,post_id,"
            "parent_id,post_title,author,body,created_ms,buckets,source,"
            "first_seen) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (k, x.get("id"), x.get("mention_id"), x.get("post_id"),
             x.get("parent_id"), (x.get("post_title") or "")[:300],
             (x.get("author") or "")[:80], x.get("body") or "",
             ca if isinstance(ca, int) else None, x["bucket"], source,
             utcnow()))
        new += 1
    state.db.commit()
    return new


def _page(writer, bucket, token, since=None):
    """One more page of ONE bucket. The registry applies a single ?before= to
    every bucket, keyed in each bucket's own id space, so only the bucket the
    token came from is kept from each response."""
    me = writer.me(since=since, before=token)
    rows, stats = rows_from_me(me, (bucket,))
    return rows, stats["next"].get(bucket)


def drain(writer, first_stats, log, buckets=LIVE_BUCKETS, max_pages=6):
    """The rest of a truncated live read, before it is acked.

    Each truncated bucket is paged with its own next_before token. A live
    read rarely needs this (the window is one cycle long); it is what keeps
    a burst from being acknowledged past the first page.
    """
    out = []
    for b in buckets:
        tok, pages = first_stats["next"].get(b), 0
        while tok and pages < max_pages:
            rows, tok = _page(writer, b, tok)
            out += rows
            pages += 1
        if tok:
            log(f"inbox: {b} still had more after {max_pages} extra pages; "
                f"the ack will skip the rest", level="warn")
    return out


def import_backlog(state, writer, log, buckets=DIRECT, max_pages=40):
    """Store every item addressed to riffle since it registered, once.

    ?since=0 replays the legacy window from the start even after an ack, and
    reads never move the cursor, so this changes nothing on the registry.
    Each request costs the registry a scan of the whole board for the naming
    estimate (?since= cannot be combined with ?named_days=), so it is paged
    only as far as it needs to go and run once.

    Returns {bucket: rows stored} and raises on an HTTP error, so a half
    import is not mistaken for a whole one.
    """
    got = {}
    for b in buckets:
        rows, stats = rows_from_me(writer.me(since=0), (b,))
        tok, pages, n = stats["next"].get(b), 1, store(state, rows, "backlog")
        while tok and pages < max_pages:
            rows, tok = _page(writer, b, tok, since=0)
            n += store(state, rows, "backlog")
            pages += 1
        if tok:
            log(f"backlog: {b} had more than {max_pages} pages; the oldest "
                f"were not imported", level="warn")
        got[b] = n
    return got


def reconcile(state):
    """Mark what has been answered, then set aside what was passed over.

    Answered means a comment went out (or is waiting on you) with this item's
    comment as its parent; for a mention in a post, which has no comment, a
    top-level comment on that post made after the item arrived. Read from the
    actions table each time rather than hooked into the send path, so a
    comment you reject puts its item back.
    """
    ensure(state)
    by_parent, top_level = {}, {}
    for r in state.db.execute(
            "SELECT id, status, created_at,"
            " CAST(json_extract(payload,'$.parent_id') AS INTEGER) AS par,"
            " CAST(json_extract(payload,'$.post_id') AS INTEGER) AS post"
            " FROM actions WHERE kind='comment' AND status IN"
            " ('sent','sending','executed','unknown','queued','approved')"):
        if r["par"]:
            by_parent.setdefault(r["par"], []).append(r)
        elif r["post"]:
            top_level.setdefault(r["post"], []).append(r)
    now = utcnow()
    for it in state.db.execute(
            "SELECT * FROM inbox_items WHERE status='pending'").fetchall():
        if it["comment_id"] is not None:
            acts = by_parent.get(it["comment_id"], [])
        else:
            # Since the MENTION was made, not since the store first saw it:
            # backlog items were all first seen on the import day, so an
            # answer riffle gave in September looked pending (R4.5, audit 4).
            _since = (time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                    time.gmtime(it["created_ms"] / 1000))
                      if it["created_ms"] else (it["first_seen"] or ""))
            # AND A TOP-LEVEL COMMENT THAT WOULD BLOCK A NEW ONE (L5, audit
            # 2026-10-27). If riffle had already commented top-level on the
            # post within the last 24 hours, its answer to the mention was
            # refused by the one-per-post-per-day rule, the mention stayed
            # pending, and it forced up to three wasted answer cycles. The
            # window is the rule's own: 24 hours, compared in the same
            # timestamp form (cycle.top_level_today).
            _blocks = time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                    time.gmtime(time.time() - 24 * 3600))
            acts = [a for a in top_level.get(it["post_id"], [])
                    if (a["created_at"] or "") >= _since
                    or (a["created_at"] or "") > _blocks]
        sent = [a for a in acts if a["status"] in _SENT]
        if sent:
            state.db.execute(
                "UPDATE inbox_items SET status='answered', handled_at=?,"
                " handled_by=? WHERE key=?",
                (now, f"action:{sent[0]['id']}", it["key"]))
        elif not acts and it["shown_count"] >= PASS_AFTER:
            state.db.execute(
                "UPDATE inbox_items SET status='passed', handled_at=?,"
                " handled_by='passed' WHERE key=?", (now, it["key"]))
    state.db.commit()


def _in_flight(state):
    """Comment ids and post ids an answer is already waiting on you for."""
    pars, posts = set(), set()
    for r in state.db.execute(
            "SELECT CAST(json_extract(payload,'$.parent_id') AS INTEGER) AS par,"
            " CAST(json_extract(payload,'$.post_id') AS INTEGER) AS post"
            " FROM actions WHERE kind='comment' AND status IN"
            " ('queued','approved')"):
        if r["par"]:
            pars.add(r["par"])
        elif r["post"]:
            posts.add(r["post"])
    return pars, posts


def pending(state, source=None):
    """Pending items as plain dicts, direct buckets first, newest first.

    Dicts, not sqlite3.Row: callers use .get(), and a Row has none.
    Items with an answer already waiting on you are left out.
    """
    ensure(state)
    q = "SELECT * FROM inbox_items WHERE status='pending'"
    args = ()
    if source:
        q += " AND source=?"
        args = (source,)
    pars, posts = _in_flight(state)
    out = []
    for r in state.db.execute(q, args).fetchall():
        d = dict(r)
        if (d["comment_id"] in pars
                or (d["comment_id"] is None and d["post_id"] in posts)):
            continue
        bs = (d["buckets"] or "").split(",")
        d["bucket"] = bs
        d["_direct"] = any(b in DIRECT for b in bs)
        out.append(d)
    out.sort(key=lambda d: (not d["_direct"], -(d["created_ms"] or 0)))
    return out


def counts(state):
    ensure(state)
    out = {"live": 0, "backlog": 0, "answered": 0, "passed": 0}
    for r in state.db.execute(
            "SELECT source, status, COUNT(*) n FROM inbox_items"
            " GROUP BY source, status"):
        if r["status"] == "pending":
            out[r["source"]] = out.get(r["source"], 0) + r["n"]
        else:
            out[r["status"]] = out.get(r["status"], 0) + r["n"]
    return out


def pick(state, n_live=5, n_backlog=2):
    """What this cycle's prompt shows: (live, backlog) item dicts.

    Five new and two older, with bodies cut to 300 chars, titles to 80 and
    authors to 40 in for_prompt: at most 4,802 chars, measured with both
    headers and every field at its cap. It was ten and three at 500, ~9,000 chars, which
    _fit cut by ~7,800 every cycle on the box (2026-10-24), leaving riffle a
    message or two of the inbox it was meant to work through. The two INBOX
    blocks are protected from _fit now (_NEVER_TRIM), which is only safe
    because this keeps them small.
    """
    return pending(state, "live")[:n_live], pending(state, "backlog")[:n_backlog]


def mark_shown(state, items):
    """Count a showing. The cycle calls this AFTER the composer returns, and
    only when the cycle could have answered (the drive may propose a comment
    and today's allowance is not spent). Counted at prompt time, a run of
    composer failures would set messages aside that the model never saw."""
    now = utcnow()
    for d in items:
        state.db.execute(
            "UPDATE inbox_items SET shown_count=shown_count+1,"
            " last_shown=? WHERE key=?", (now, d["key"]))
    state.db.commit()


def for_prompt(items, body_chars=300):
    """Item dicts trimmed and labelled for the prompt."""
    import time
    out = []
    for d in items:
        body = d.get("body") or ""
        # Title and author capped too: the inbox blocks are protected from
        # _fit, so their worst case has to be bounded, and a 300-char title
        # on every line was most of it.
        o = {"comment_id": d.get("comment_id"), "post_id": d.get("post_id"),
             "parent_id": d.get("parent_id"),
             "post_title": (d.get("post_title") or "")[:80],
             "author": (d.get("author") or "")[:40], "bucket": d.get("bucket"),
             "body": body[:body_chars]}
        if d.get("comment_id") is None and d.get("mention_id") is not None:
            o["mention_id"] = d["mention_id"]
        if len(body) > body_chars:
            o["body_truncated"] = True
            o["body_full_chars"] = len(body)
        ms = d.get("created_ms")
        if isinstance(ms, int):
            o["at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ms / 1000))
            o["age_days"] = round((time.time() - ms / 1000) / 86400, 1)
        out.append(o)
    return out


def _status(db_path):
    from agent.state import State
    st = State(db_path)
    c = counts(st)
    print(f"pending: {c['live']} live, {c['backlog']} backlog")
    print(f"handled: {c['answered']} answered, {c['passed']} set aside")
    for r in st.db.execute(
            "SELECT source, status, COUNT(*) n FROM inbox_items"
            " GROUP BY source, status ORDER BY source, status"):
        print(f"  {r['source']:8} {r['status']:9} {r['n']}")
    print(f"backlog imported: {st.note('backlog_imported') or 'not yet'}")


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] != "status":
        sys.exit("usage: python3 -m agent.inbox status [--db PATH]")
    db = "/var/lib/riffle/state.sqlite"
    if "--db" in args:
        db = args[args.index("--db") + 1]
    _status(db)
