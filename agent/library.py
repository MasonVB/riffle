"""The library. Documents kept because they might matter later.

THREE STORES, THREE LIFETIMES

  memories   600 characters, distilled, promoted by a daily pass. What you
             would want to know in a month with no other context.
  desk       twelve items, always fully in the prompt. What you are working
             on right now and intend to pick back up.
  library    whole documents on disk, indexed and searched, never in the
             prompt unless you go and get one. What you might want in a year.

The distinction that matters: the desk is IN VIEW and the library is NOT. A
library you could see all of would just be a bigger desk, and a prompt is
thousands of characters while this holds gigabytes. So the library is reached
through search, and search is the only way in.

WHY FILES AND NOT ROWS

state.sqlite holds the cycle log, the journal, the actions and the desk, and
it gets backed up and queried constantly. Putting gigabytes of documents in it
would make every backup enormous and every query slower for the sake of blobs
nothing joins against. The documents live on disk; only the index is a table.

PRUNING

Bounded by total bytes, default 300 GB, dropping least-recently-READ first.
Reading protects a document, which is the opposite of the desk's rule, and for
the opposite reason: a desk item is protected by being worked, a library
document by being wanted. Pinned documents are never dropped.

The cap will very likely never be reached. Written anyway, because a store
with no eviction path is a store that eventually fills a disk at three in the
morning, and the failure mode of a full disk on this machine is the agent
stopping entirely.
"""
import datetime as dt
import hashlib
import json
import os
import re
import shutil

ROOT = "/var/lib/riffle-library"
MAX_BYTES = 300 * 1024 * 1024 * 1024        # 300 GB
MAX_DOC = 8 * 1024 * 1024                   # 8 MB per document
READ_CHARS = 12000                          # how much a read puts in the prompt
KINDS = ("note", "code", "page", "thread", "post", "data", "reference")

SCHEMA = """
CREATE TABLE IF NOT EXISTS library (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  path        TEXT NOT NULL UNIQUE,
  title       TEXT NOT NULL,
  kind        TEXT NOT NULL,
  tags        TEXT DEFAULT '',
  summary     TEXT DEFAULT '',
  source      TEXT DEFAULT '',
  bytes       INTEGER NOT NULL,
  sha256      TEXT NOT NULL,
  created_at  TEXT NOT NULL,
  last_read   TEXT,
  reads       INTEGER DEFAULT 0,
  pinned      INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS library_read ON library(last_read);
CREATE INDEX IF NOT EXISTS library_sha  ON library(sha256);
"""

_SLUG = re.compile(r"[^a-z0-9]+")


def ensure(state, root=ROOT):
    state.db.executescript(SCHEMA)
    os.makedirs(root, exist_ok=True)


def _now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _slug(title):
    s = _SLUG.sub("-", title.lower()).strip("-")[:60]
    return s or "untitled"


def total_bytes(state):
    r = state.db.execute("SELECT COALESCE(SUM(bytes),0) b FROM library").fetchone()
    return int(r["b"])


def put(state, title, body, kind="note", tags="", summary="", source="",
        pinned=False, root=ROOT, cap=MAX_BYTES):
    """Shelve a document. Returns (id, evicted_titles).

    Deduplicated by content hash: shelving the same bytes twice returns the
    existing row rather than a second copy. An agent that re-reads a thread
    every cycle should not end up with forty identical files, and it has no
    way to notice that it has.
    """
    title = str(title).strip()[:200]
    if not title:
        raise ValueError("a document needs a title you can search for later")
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    raw = body if isinstance(body, bytes) else str(body).encode("utf-8")
    if len(raw) < 8:
        raise ValueError("nothing to shelve")
    if len(raw) > MAX_DOC:
        raise ValueError(f"{len(raw)} bytes is over the {MAX_DOC} per-document limit")

    digest = hashlib.sha256(raw).hexdigest()
    dupe = state.db.execute(
        "SELECT id, title FROM library WHERE sha256=?", (digest,)).fetchone()
    if dupe:
        return dupe["id"], []

    ensure(state, root)
    day = _now()[:10]
    os.makedirs(os.path.join(root, day), exist_ok=True)
    name = f"{_slug(title)}-{digest[:8]}.txt"
    rel = os.path.join(day, name)
    with open(os.path.join(root, rel), "wb") as f:
        f.write(raw)

    cur = state.db.execute(
        "INSERT INTO library (path,title,kind,tags,summary,source,bytes,sha256,"
        "created_at,last_read,reads,pinned) VALUES (?,?,?,?,?,?,?,?,?,NULL,0,?)",
        (rel, title, kind, str(tags)[:300], str(summary)[:600],
         str(source)[:300], len(raw), digest, _now(), 1 if pinned else 0))
    state.db.commit()
    return cur.lastrowid, prune(state, root, cap)


def find(state, query, limit=10):
    """Search titles, tags, summaries and sources. Never the bodies.

    Bodies are not searched on purpose: grepping gigabytes on a box that is
    already stalling under load is a good way to cause the thing we spent a
    week diagnosing. The index is what you write when you shelve something,
    so a document with a lazy title is a document you will not find — which
    is true of a real library too.
    """
    q = f"%{str(query).strip()[:120]}%"
    rows = state.db.execute(
        "SELECT id,title,kind,tags,summary,bytes,created_at,reads,pinned"
        " FROM library WHERE title LIKE ? OR tags LIKE ? OR summary LIKE ?"
        " OR source LIKE ? ORDER BY pinned DESC, reads DESC, id DESC LIMIT ?",
        (q, q, q, q, int(limit))).fetchall()
    return rows


def read(state, doc_id, root=ROOT, chars=READ_CHARS):
    """Fetch one document and mark it read. Returns (row, text) or (None, '')."""
    row = state.db.execute("SELECT * FROM library WHERE id=?",
                           (int(doc_id),)).fetchone()
    if not row:
        return None, ""
    try:
        with open(os.path.join(root, row["path"]), "rb") as f:
            raw = f.read()
    except OSError as e:
        return row, f"[the file is indexed but unreadable: {e}]"
    state.db.execute(
        "UPDATE library SET last_read=?, reads=reads+1 WHERE id=?",
        (_now(), row["id"]))
    state.db.commit()
    text = raw.decode("utf-8", "replace")
    if len(text) > chars:
        text = text[:chars] + f"\n[...{len(text) - chars} more characters; "\
                              f"the whole document is on disk]"
    return row, text


def forget(state, doc_id, root=ROOT):
    row = state.db.execute("SELECT * FROM library WHERE id=?",
                           (int(doc_id),)).fetchone()
    if not row:
        return False
    try:
        os.remove(os.path.join(root, row["path"]))
    except OSError:
        pass
    state.db.execute("DELETE FROM library WHERE id=?", (row["id"],))
    state.db.commit()
    return True


def prune(state, root=ROOT, cap=MAX_BYTES):
    """Drop least-recently-read documents until under the cap. Never pinned.

    NULL last_read sorts first, so something shelved and never opened goes
    before something read once a year ago. Shelving is cheap and reading is a
    decision; the decision is the signal.
    """
    dropped = []
    while total_bytes(state) > cap:
        row = state.db.execute(
            "SELECT id,title,path FROM library WHERE pinned=0"
            " ORDER BY last_read IS NOT NULL, last_read, id LIMIT 1").fetchone()
        if not row:
            break                       # everything left is pinned
        try:
            os.remove(os.path.join(root, row["path"]))
        except OSError:
            pass
        state.db.execute("DELETE FROM library WHERE id=?", (row["id"],))
        state.db.commit()
        dropped.append(row["title"])
    return dropped


def as_context(state, cap=MAX_BYTES):
    """One line in the prompt. The library is reached by search, not by being shown."""
    r = state.db.execute(
        "SELECT COUNT(*) n, COALESCE(SUM(bytes),0) b FROM library").fetchone()
    if not r["n"]:
        return ("YOUR LIBRARY IS EMPTY. It holds whole documents on disk — "
                "code you wrote, a thread worth keeping, a reference you will "
                "want again. `library_put` shelves one, `library_find` searches "
                "the titles and tags you gave it, `library_read` opens it. "
                "Unlike the desk it is not in front of you: a document you "
                "shelve with a vague title is one you will never find again.")
    gb = r["b"] / (1024 ** 3)
    recent = state.db.execute(
        "SELECT title FROM library ORDER BY id DESC LIMIT 5").fetchall()
    return (f"YOUR LIBRARY: {r['n']} document(s), {gb:.2f} GB of "
            f"{cap / (1024 ** 3):.0f} GB. Search it with `library_find` before "
            f"deciding you do not know something.\n  most recent: "
            + "; ".join(x["title"][:60] for x in recent))
