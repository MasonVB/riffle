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
Nothing is dropped for age or size until the disk is 85% used, by anything
(the operator's rule, 2026-11-19; agent/storage.py). Past that, each
document shelved deletes the oldest unpinned documents, by when they were
shelved, until their bytes add up to the new one's: riffle's share of the
disk stops growing, and a disk filled by something else cannot empty the
library, since no more goes than comes in. Pinned documents are never dropped.

Before that, the library had a byte cap (config.yaml's library.max_bytes,
40 GB; 300 GB earlier), kept 5 GB of the disk free, and dropped the least
recently READ first, never below half the cap. The cap and the 5 GB are gone;
the order is now oldest shelved, as the operator asked, so a document read
every week can go before one shelved later and never opened.
"""
import datetime as dt
import hashlib
import os
import re

ROOT = "/var/lib/riffle-library"
MAX_DOC = 8 * 1024 * 1024                   # 8 MB per document
READ_CHARS = 12000                          # how much a read puts in the prompt
# "draft" is here because drives.py added it to the gate on 2026-10-10 and
# this tuple was not touched — so a draft passed the gate and was then
# refused by library.put, which is the loudest possible way to disagree with
# yourself. drives.py now imports this tuple rather than keeping its own.
KINDS = ("note", "code", "page", "thread", "post", "data", "reference",
         "draft")

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
-- Other sources of the same bytes (audit F33): see put().
CREATE TABLE IF NOT EXISTS library_aliases (
  id          INTEGER PRIMARY KEY,
  lib_id      INTEGER NOT NULL,
  kind        TEXT NOT NULL,
  source      TEXT NOT NULL,
  created_at  TEXT NOT NULL,
  UNIQUE (lib_id, source)
);
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
        pinned=False, root=ROOT, cfg=None):
    """Shelve a document. Returns (id, evicted_titles): what went to make
    room for it, which is nothing until the disk is past its limit (cfg's
    storage.disk_limit_percent, 85 by default; agent/storage.py).

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
    ensure(state, root)
    dupe = state.db.execute(
        "SELECT id, title, kind, source FROM library WHERE sha256=?", (digest,)).fetchone()
    if dupe:
        # THE NEW SOURCE IS KEPT (audit F33, 2026-11-10). The same bytes from
        # a second source returned the first row and dropped where they came
        # from: two URLs serving the same text (a consent page, a mirror) left
        # the second with no page row, so a post citing it was refused as
        # "not a page you have read"; a build whose output matched a document
        # riffle had shelved itself kept that row, with no build source, so a
        # replication naming it was refused. The file is still stored once.
        src = str(source or "")[:300]
        if src and (src != (dupe["source"] or "") or kind != dupe["kind"]):
            state.db.execute(
                "INSERT OR IGNORE INTO library_aliases (lib_id,kind,source,created_at)"
                " VALUES (?,?,?,?)", (dupe["id"], kind, src, _now()))
            state.db.commit()
        return dupe["id"], []

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
    from agent import storage
    if storage.over_limit(root, cfg):
        return cur.lastrowid, storage.make_room_in_library(
            state, root, len(raw), keep_id=cur.lastrowid)
    return cur.lastrowid, []


def sources(state, kinds=None):
    """(id, kind, source) of every document AND every other source of the same
    bytes (library_aliases), newest first. What a check asking "was this
    page read" or "did a build produce this" must look at (audit F33)."""
    q = ("SELECT id, kind, source FROM library"
         " UNION ALL SELECT lib_id AS id, kind, source FROM library_aliases")
    try:
        rows = state.db.execute(f"SELECT * FROM ({q}) ORDER BY id DESC").fetchall()
    except Exception:          # no alias table yet: a store put() never ran on
        rows = state.db.execute(
            "SELECT id, kind, source FROM library ORDER BY id DESC").fetchall()
    return [r for r in rows if kinds is None or r["kind"] in kinds]


def from_build(state, doc_id):
    """True if a build shelved this document, as itself or as another source."""
    return any(r["id"] == int(doc_id) and str(r["source"] or "").startswith("build:")
               for r in sources(state))


def find(state, query, limit=10, root=ROOT):
    """Search titles, tags, summaries and sources; the bodies only as a fallback.

    Bodies are not searched on purpose: grepping gigabytes on a box that is
    already stalling under load is a good way to cause the thing we spent a
    week diagnosing. The index is what you write when you shelve something,
    so a document with a lazy title is a document you will not find — which
    is true of a real library too.
    """
    # A HASH FINDS ITS DOCUMENT (box, 2026-11-07: riffle searched for
    # `78805fea`, the start of a library document's own sha256, and was told
    # nothing matched, because the search never looked at the hash). Seven or
    # more hex characters are tried as the start of a sha256 first.
    _hq = str(query).strip().lower()
    if re.fullmatch(r"[0-9a-f]{7,64}", _hq):
        rows = state.db.execute(
            "SELECT id,title,kind,tags,summary,bytes,created_at,reads,pinned,sha256"
            " FROM library WHERE lower(sha256) LIKE ? ORDER BY id DESC LIMIT ?",
            (_hq + "%", int(limit))).fetchall()
        if rows:
            return rows
    q = f"%{str(query).strip()[:120]}%"
    rows = state.db.execute(
        "SELECT id,title,kind,tags,summary,bytes,created_at,reads,pinned,sha256"
        " FROM library WHERE title LIKE ? OR tags LIKE ? OR summary LIKE ?"
        " OR source LIKE ? ORDER BY pinned DESC, reads DESC, id DESC LIMIT ?",
        (q, q, q, q, int(limit))).fetchall()
    if rows:
        return rows

    # FALL BACK TO THE BODIES, but only when the index found nothing and only
    # over a bounded number of the smallest documents.
    #
    # The index was the whole search, deliberately: grepping gigabytes on a box
    # that stalls under load is a bad idea. But most of what gets shelved is
    # fetched automatically — `/docket on 2026-09-06`, titled by a template —
    # so the index describes where a document came from and nothing about what
    # is in it. Riffle searched for "cadence bias sampling interval detection
    # latency" against a library holding two dockets and got nothing, which is
    # correct and useless.
    #
    # Bounded so it cannot become the thing it was avoiding: only when the
    # index misses, only the 40 smallest documents, only up to 8 MB read.
    terms = [w for w in re.split(r"\W+", str(query).lower()) if len(w) > 3][:8]
    if not terms:
        return []
    budget, hits = 8 * 1024 * 1024, []
    for r in state.db.execute(
            "SELECT id,title,kind,tags,summary,bytes,created_at,reads,pinned,path,sha256"
            " FROM library ORDER BY bytes LIMIT 40").fetchall():
        if budget <= 0 or len(hits) >= int(limit):
            break
        budget -= r["bytes"]
        try:
            with open(os.path.join(root, r["path"]), "rb") as f:
                body = f.read(200_000).decode("utf-8", "replace").lower()
        except OSError:
            continue
        if sum(1 for t in terms if t in body) >= max(1, len(terms) // 3):
            hits.append(r)
    return hits


def read(state, doc_id, root=ROOT, chars=READ_CHARS, count=True):
    """Fetch one document. Returns (row, text) or (None, '').

    count=False fetches without marking it read. Used where the code is
    looking something up on riffle's behalf rather than riffle choosing to
    read it: numcheck pulling a cited document to verify a figure bumped the
    read counter, which is what protects a document from pruning. Mentioning
    an id in a draft would have kept it alive forever, and the counter would
    say it was being read when nobody had.
    """
    row = state.db.execute("SELECT * FROM library WHERE id=?",
                           (int(doc_id),)).fetchone()
    if not row:
        return None, ""
    try:
        with open(os.path.join(root, row["path"]), "rb") as f:
            raw = f.read()
    except OSError as e:
        return row, f"[the file is indexed but unreadable: {e}]"
    if count:
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
    state.db.execute("DELETE FROM library_aliases WHERE lib_id=?", (row["id"],))
    state.db.commit()
    return True


def as_context(state, cfg=None, root=ROOT):
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
    from agent import storage
    return (f"YOUR LIBRARY: {r['n']} document(s), {gb:.2f} GB; "
            f"{storage.describe(cfg, root)}. Search it with `library_find` before "
            f"deciding you do not know something.\n  most recent: "
            + "; ".join(x["title"][:60] for x in recent))
