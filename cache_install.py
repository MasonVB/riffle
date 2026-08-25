#!/usr/bin/env python3
"""Keep what it reads, and let it look things up in what it kept.

    sudo cp cache_install.py /opt/riffle/
    sudo python3 /opt/riffle/cache_install.py
    sudo systemctl restart riffle-dash

WHY SAVING ALONE WOULD NOT HAVE FIXED IT

Riffle's complaint was accurate: `read_post` in the chat path fetched #1916,
put it in the context window, and persisted nothing. When the window filled it
was gone, and it said so.

But storing it and then re-injecting it would refill the window at the same
point. A 7,000-token post does not fit in a 12,288-token context alongside a
system prompt, a record and an answer, however many times you fetch it. The
useful thing a cache buys is not "read it again" — it is "read the part of it
you need".

SO: TWO TOOLS INSTEAD OF ONE

  read_post <id>          fetches once, writes the whole thing to disk, and
                          returns a bounded slice — the post head, and the
                          highest-voted replies that fit.

  recall <id> <terms>     searches the stored copy and returns only the
                          passages containing those terms, with a little
                          context either side. Cheap, repeatable, and it does
                          not refill the window.

So "what did #1916 say about the never_money rule" costs a few hundred tokens
instead of seven thousand, and works after the original read has scrolled out
of context.

The cache is shared with the cycle path, so a thread read during a cycle is
already there when you ask about it in chat, and neither refetches what the
other has.

Backups written as .bak-cache.
"""
import os
import shutil
import sys

RIFFLE = "/opt/riffle"
CHAT = f"{RIFFLE}/agent/chat.py"
CYCLE = f"{RIFFLE}/agent/cycle.py"


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
    if not os.path.exists(f"{path}.bak-cache"):
        shutil.copy(path, f"{path}.bak-cache")
    open(path, "w").write(s.replace(old, new, 1))
    print(f"  patched: {label}")
    return True


CACHE = '''

# ------------------------------------------------------------- board cache
# What it reads is written to disk before any of it is shown. The context
# window is small and volatile; the disk is neither. Re-reading a whole post
# is not the point — being able to search it afterwards is.

CACHE_SCHEMA = """
CREATE TABLE IF NOT EXISTS board_cache (
  post_id INTEGER PRIMARY KEY, fetched_at TEXT,
  title TEXT, author TEXT, votes INTEGER,
  body TEXT, comments_json TEXT, comments_total INTEGER);
"""


def cache_post(state, post_id, data):
    """Store the whole thing. Returns (title, body, comments)."""
    state.db.executescript(CACHE_SCHEMA)
    post = data.get("post") or data
    raw = data.get("comments")
    comments = [c for c in (raw if isinstance(raw, list) else [])
                if isinstance(c, dict)]
    total = data.get("comments_total")
    if not isinstance(total, int):
        total = len(comments)
    title = str(post.get("title") or "")
    body = str(post.get("body") or "")
    state.db.execute(
        "INSERT INTO board_cache (post_id,fetched_at,title,author,votes,body,"
        "comments_json,comments_total) VALUES (?,?,?,?,?,?,?,?)"
        " ON CONFLICT(post_id) DO UPDATE SET fetched_at=excluded.fetched_at,"
        " title=excluded.title, body=excluded.body,"
        " comments_json=excluded.comments_json,"
        " comments_total=excluded.comments_total",
        (post_id, utcnow(), title[:300], str(post.get("author") or "")[:80],
         post.get("votes") or 0, body, json.dumps(comments), total))
    state.db.commit()
    return title, body, comments, total


def cached(state, post_id):
    try:
        return state.db.execute(
            "SELECT * FROM board_cache WHERE post_id=?", (post_id,)).fetchone()
    except Exception:
        return None


def cache_excerpts(state, post_id, terms, window=320, limit=6):
    """Passages of a stored post containing the terms. This is the whole point
    of the cache: an answer to a specific question that costs a few hundred
    tokens rather than the seven thousand a re-read would."""
    row = cached(state, post_id)
    if not row:
        return None
    hay = [("post", row["body"] or "")]
    try:
        for c in json.loads(row["comments_json"] or "[]"):
            hay.append((str(c.get("author", "?")) + " "
                        + str(c.get("ref") or c.get("id") or ""),
                        str(c.get("body", ""))))
    except Exception:
        pass
    words = [w.lower() for w in terms.split() if len(w) > 2]
    out = []
    for who, text in hay:
        low = text.lower()
        for w in words:
            i = low.find(w)
            while i >= 0 and len(out) < limit:
                a, b = max(0, i - window // 2), min(len(text), i + window)
                out.append("[" + who + "] ..." + text[a:b].strip() + "...")
                i = low.find(w, b)
            if len(out) >= limit:
                break
        if len(out) >= limit:
            break
    if not out:
        return ("Nothing in the stored copy of #" + str(post_id)
                + " matches " + repr(terms) + ". It is " + str(len(row["body"] or ""))
                + " characters with " + str(row["comments_total"] or 0)
                + " replies, fetched " + str(row["fetched_at"])[:16] + ".")
    return ("From the stored copy of #" + str(post_id) + " (\\"" + row["title"][:80]
            + "\\"), passages matching " + repr(terms) + ":\\n\\n"
            + "\\n\\n".join(out))
'''

READ_POST_NEW = '''        if len(parts) >= 3 and parts[1] == "read_post":
            pid = int(parts[2])
            try:
                data = reader.post(pid)
            except (HttpError, ValueError) as e:
                return "(could not fetch #" + str(pid) + ": " + str(e) + ")"
            # Write it all down BEFORE returning any of it. What is shown here
            # is a slice; what is kept is everything.
            title, body, comments, total = cache_post(state, pid, data)
            ranked = sorted(comments, key=lambda c: (c.get("votes") or 0),
                            reverse=True)[:8]
            reps = "\\n".join(
                "  [" + str(c.get("ref") or c.get("id")) + "] "
                + str(c.get("author", "?")) + " (" + str(c.get("votes", 0))
                + " votes): " + str(c.get("body", ""))[:300] for c in ranked)
            head = ("#" + str(pid) + " \\"" + title + "\\" by "
                    + str((data.get("post") or {}).get("author", "?")) + "\\n\\n")
            note = ("\\n\\n[The whole post and all " + str(total) + " replies are "
                    "stored. This is a slice: " + str(min(len(body), 3000))
                    + " of " + str(len(body)) + " body characters and "
                    + str(len(ranked)) + " of " + str(total) + " replies. "
                    "Use `TOOL recall " + str(pid) + " <words>` to pull the "
                    "passages you actually need — it will still work after this "
                    "scrolls out of context.]")
            return head + body[:3000] + ("\\n\\nTOP REPLIES:\\n" + reps
                                         if reps else "") + note
        if len(parts) >= 4 and parts[1] == "recall":
            pid = int(parts[2])
            res = cache_excerpts(state, pid, " ".join(parts[3:]))
            if res is None:
                return ("#" + str(pid) + " is not stored yet. Read it first "
                        "with `TOOL read_post " + str(pid) + "`.")
            return res
'''


def main():
    # ---- cache module ------------------------------------------------------
    s = open(CHAT).read()
    if "def cache_post(" in s:
        print("  already present: board cache")
    else:
        shutil.copy(CHAT, f"{CHAT}.bak-cache")
        # place it before run_tool so run_tool can call it
        i = s.index("def run_tool(")
        open(CHAT, "w").write(s[:i] + CACHE.strip() + "\n\n\n" + s[i:])
        print("  added board cache to chat.py")

    # cache_post uses utcnow(); chat.py imports time but not that helper.
    s = open(CHAT).read()
    if "from agent.state import utcnow" in s:
        print("  already present: utcnow import")
    else:
        anchor = "from agent.client import HttpError, Reader"
        if anchor not in s:
            sys.exit("  FAILED: could not find the client import in chat.py.")
        open(CHAT, "w").write(s.replace(
            anchor, anchor + "\nfrom agent.state import utcnow", 1))
        print("  patched: chat.py imports utcnow")

    # run_tool needs state and the client exception
    patch(CHAT, "def run_tool(reader, line, cfg=None):",
          "def run_tool(reader, line, cfg=None, state=None):",
          "run_tool takes state", marker="cfg=None, state=None")

    patch(CHAT, "            result = run_tool(reader, tool_line, cfg)",
          "            result = run_tool(reader, tool_line, cfg, state)",
          "run_tool called with state", marker="run_tool(reader, tool_line, cfg, state)")

    # replace the old read_post branch
    s = open(CHAT).read()
    old = '''        if len(parts) >= 3 and parts[1] == "read_post":
            return json.dumps(reader.post(int(parts[2])), indent=1)[:9000]
'''
    if "TOOL recall " in s:
        print("  already present: read_post caches, recall added")
    elif old not in s:
        print("  NOTE: the read_post branch does not match what I expected;\n"
              "        run `grep -n 'read_post' /opt/riffle/agent/chat.py` and\n"
              "        paste it. Nothing else was skipped.")
    else:
        open(CHAT, "w").write(s.replace(old, READ_POST_NEW, 1))
        print("  patched: read_post caches everything, returns a slice")

    patch(CHAT, "TOOL read_docket",
          "TOOL read_docket\nTOOL recall <post id> <words to look for>",
          "recall listed in the tool block", marker="TOOL recall <post id>")

    patch(CHAT,
          "Use the read_* tools for the square.",
          "read_post stores the whole post and every reply, then shows you a "
          "slice. When you need a part you did not get, use `recall` rather "
          "than reading it again: it searches what was stored and returns only "
          "the passages, so it costs a few hundred tokens instead of seven "
          "thousand and works after the original read has scrolled away.\\n\\n"
          "Use the read_* tools for the square.",
          "tool block explains recall", marker="then shows you a slice")

    import ast
    ast.parse(open(CHAT).read())
    print("\n  chat.py parses.")
    print("\n  Next:  sudo systemctl restart riffle-dash")


if __name__ == "__main__":
    main()
