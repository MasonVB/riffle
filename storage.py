"""What riffle keeps, and what it lets go of when the disk fills.

THE RULE (the operator's, 2026-11-19)
Keep everything until the disk is 85% used (as `df` counts it), by anything
at all: riffle, the models, the system, other files. Past that, every time riffle saves
something, it deletes its own oldest things whose sizes add up to at least
what it just saved. So past 85% riffle's own use of the disk stops growing,
and it never deletes more than it adds. Below 85% nothing is deleted for
age or size.

It replaces the limits that were there before:
  - the library's byte cap (config.yaml's library.max_bytes, 40 GB) and its
    "keep 5 GB free" rule, which evicted the least recently read;
  - telemetry: samples after 24 hours, dumps after 21 days or past 500, the
    copies kept from each boot after 90 days;
  - the figures tables (model calls, prompt fits) after 30 days.

TWO STORES, ONE RULE EACH
  library   whole documents on disk. When one is shelved past the limit, the
            oldest unpinned documents (by when they were shelved) go until
            their bytes add up to the new one's. library.put calls
            make_room_in_library.
  database  history rows in state.sqlite: the journal, telemetry and the
            per-boot copies, model calls, prompt fits, finished dashboard
            messages, and the board cache. Rows are written all the time, by
            the cycle and the dashboard, so they are settled in batches: after
            each cycle, and every hour in the dashboard. check() measures how
            much the database's live pages grew since the last check and, past
            the limit, deletes the oldest of those rows, across all the
            tables by timestamp, until their sizes add up to that growth.

  SQLite does not give deleted space back to the disk: the file stays its
  size and the freed pages are reused for the next rows. That is the rule
  here, nothing added past the limit without as much taken away, and it is
  why growth is measured in live pages rather than in the file's size.

WHAT IS NEVER DELETED HERE
  - Cycles and actions: the record of what riffle did and said, which the
    checks against saying, voting or replying twice read. Small (a few MB a
    year), and kept.
  - Memories: their limit (1,200, memory.prune) is about what riffle can
    recall well, not about disk.
  - What riffle has seen and read (seen, thread_reads, inbox_items): the
    checks against reading or answering twice use them.
  - Goals, notes, projects, the desk, questions, policy and drive changes,
    the witness heads: riffle's state, not its history.
  - Pinned library documents.
  - A failed build's directory is still bounded by bin/riffle-build (five,
    256 MiB): that is a safety against a build flooding the disk, not a
    retention rule.
"""
import os

DISK_LIMIT_PERCENT = 85          # config.yaml: storage.disk_limit_percent

# Each history table: (name, column that orders it oldest first, timestamp
# column, size of a row in bytes as SQLite stores its text, and which rows
# may go). Rows are ordered by their own index, then merged by timestamp.
_ROW = 40                        # a row's overhead beyond its text, roughly
HISTORY = (
    ("journal", "id", "ts",
     "length(COALESCE(text,''))+length(COALESCE(level,''))+length(COALESCE(drive,''))+20", ""),
    ("telemetry", "id", "ts",
     "length(COALESCE(payload,''))+length(COALESCE(kind,''))+length(COALESCE(label,''))+20", ""),
    ("telemetry_kept", "id", "ts",
     "length(COALESCE(payload,''))+length(COALESCE(kind,''))+length(COALESCE(label,''))+56", ""),
    ("composer_calls", "id", "at",
     "length(COALESCE(purpose,''))+length(COALESCE(finish,''))+length(COALESCE(error,''))+100", ""),
    ("prompt_fits", "id", "at", "length(COALESCE(blocks,''))+80", ""),
    # A message still streaming in, or the card for an action still waiting
    # on you, is not history yet. Only finished ones go. (The COALESCE is
    # load-bearing: a message with no action_id gives NULL, NULL IN (...) is
    # NULL, and NOT NULL is not true, so without it every ordinary message
    # was kept whenever any action was waiting.)
    ("messages", "id", "ts",
     "length(COALESCE(content,''))+length(COALESCE(meta,''))+length(COALESCE(role,''))+20",
     "done=1 AND NOT (json_valid(meta) AND COALESCE(json_extract(meta, '$.action_id'), -1) IN"
     " (SELECT id FROM actions WHERE status IN ('proposed', 'queued', 'approved')))"),
    ("board_cache", "fetched_at", "fetched_at",
     "length(COALESCE(body,''))+length(COALESCE(comments_json,''))"
     "+length(COALESCE(title,''))+length(COALESCE(author,''))+20", ""),
)


def limit_percent(cfg):
    try:
        v = float(((cfg or {}).get("storage") or {}).get("disk_limit_percent",
                                                          DISK_LIMIT_PERCENT))
    except (TypeError, ValueError):
        v = DISK_LIMIT_PERCENT
    return v if 0 < v <= 100 else DISK_LIMIT_PERCENT


def disk_used_percent(path):
    """How full the disk holding `path` is, as `df` shows it (Use%): used
    over used plus available, so the blocks ext4 reserves for root count as
    neither. None if it cannot be read.

    Not the figures report's "% used", which counts the reserve as used (5%
    of an ext4 disk by default): near the limit it reads about a point
    higher, df's 85% being its 85.75%."""
    try:
        s = os.statvfs(path)
    except OSError:
        return None
    used = s.f_blocks - s.f_bfree
    if used + s.f_bavail <= 0:
        return None
    return 100.0 * used / (used + s.f_bavail)


def over_limit(path, cfg):
    u = disk_used_percent(path)
    return u is not None and u >= limit_percent(cfg)


# ------------------------------------------------------------------- library
def make_room_in_library(state, root, need, keep_id=None):
    """Delete the oldest unpinned documents until their bytes add up to at
    least `need`. Returns their titles. Called by library.put only when the
    disk is over the limit; the document just shelved (keep_id) is not one."""
    dropped, freed = [], 0
    while freed < need:
        row = state.db.execute(
            "SELECT id, title, path, bytes FROM library WHERE pinned=0 AND id != ?"
            " ORDER BY id LIMIT 1", (keep_id or -1,)).fetchone()
        if not row:
            break                       # nothing left that may go
        try:
            os.remove(os.path.join(root, row["path"]))
        except OSError:
            pass
        state.db.execute("DELETE FROM library WHERE id=?", (row["id"],))
        state.db.execute("DELETE FROM library_aliases WHERE lib_id=?", (row["id"],))
        state.db.commit()
        dropped.append(row["title"])
        freed += int(row["bytes"] or 0)
    return dropped


# ------------------------------------------------------------------ database
def db_live_bytes(state):
    """Bytes in the database's pages that hold data (not its free list)."""
    pc = state.db.execute("PRAGMA page_count").fetchone()[0]
    fl = state.db.execute("PRAGMA freelist_count").fetchone()[0]
    ps = state.db.execute("PRAGMA page_size").fetchone()[0]
    return (pc - fl) * ps


def _db_dir(state):
    try:
        for row in state.db.execute("PRAGMA database_list"):
            if row[1] == "main" and row[2]:
                return os.path.dirname(row[2])
    except Exception:
        pass
    return None


def _tables(state):
    return {r[0] for r in state.db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}


def make_room_in_db(state, need, batch=500):
    """Delete the oldest history rows, across HISTORY by timestamp, until
    their sizes add up to at least `need` bytes. Returns {table: rows}."""
    have = _tables(state)
    gone, freed = {}, 0
    while freed < need:
        cand = []
        for name, order, ts, size, where in HISTORY:
            if name not in have:
                continue
            w = f" WHERE {where}" if where else ""
            for r in state.db.execute(
                    f"SELECT rowid, COALESCE({ts}, ''), {size} FROM {name}{w}"
                    f" ORDER BY {order} LIMIT ?", (batch,)):
                cand.append((str(r[1])[:19], name, r[0], int(r[2] or 0) + _ROW))
        if not cand:
            break                       # nothing left that may go
        cand.sort()
        doomed = {}
        for t, name, rowid, sz in cand:
            doomed.setdefault(name, []).append(rowid)
            freed += sz
            if freed >= need:
                break
        for name, ids in doomed.items():
            for i in range(0, len(ids), 500):
                chunk = ids[i:i + 500]
                state.db.execute(
                    f"DELETE FROM {name} WHERE rowid IN ({','.join('?' * len(chunk))})", chunk)
            gone[name] = gone.get(name, 0) + len(ids)
        state.db.commit()
    return gone


def check(state, cfg, log=None):
    """Past the limit, take back what the database grew since the last
    check; below it, only note where the database stands. Never raises."""
    try:
        live = db_live_bytes(state)
        last = state.note("storage_db_live")
        last = int(last) if last not in (None, "") else live
        where = _db_dir(state) or cfg.get("data_dir") or "/"
        gone = {}
        if over_limit(where, cfg) and live > last:
            gone = make_room_in_db(state, live - last)
            if log and gone:
                log(f"the disk is past {limit_percent(cfg):g}% used "
                    f"({disk_used_percent(where):.1f}%): the database grew "
                    f"{(live - last) / 1024:.0f} KiB since the last check, so "
                    f"the oldest history went to match it: "
                    + ", ".join(f"{n} {k}" for k, n in sorted(gone.items())),
                    level="warn")
            live = db_live_bytes(state)
        state.note("storage_db_live", str(live))
        return gone
    except Exception as e:
        if log:
            log(f"storage check failed: {type(e).__name__}: {e}", level="warn")
        return {}


def describe(cfg, path):
    """One line for the prompt and the figures: how full the disk is."""
    u = disk_used_percent(path)
    if u is None:
        return "the disk's use could not be read"
    lim = limit_percent(cfg)
    if u < lim:
        return (f"the disk is {u:.0f}% used; everything is kept until it is "
                f"{lim:g}% used")
    return (f"the disk is {u:.0f}% used, past {lim:g}%: each thing saved now "
            f"replaces the oldest of its kind")
