#!/usr/bin/env python3
"""Two-tier memory with a daily decision about what survives.

    sudo cp memory_install.py agent_consolidate.py /opt/riffle/
    sudo mv /opt/riffle/agent_consolidate.py /opt/riffle/agent/consolidate.py
    sudo python3 /opt/riffle/memory_install.py
    sudo systemctl restart riffle-dash

WHAT CHANGES

  every memory gets a tier: short (7 days) or long (forever)
  extraction and the remember action write to SHORT, always
  once a day the agent reviews short term and promotes at most three
  expiry runs every cycle; expired rows are marked, never deleted
  recall reserves a slice for long term so it cannot be crowded out

WHY THE MIGRATION SORTS EXISTING ROWS THE WAY IT DOES

Pinned memories become long term, because you pinned them and that is a
judgement already made. Everything else becomes short term dated from when it
was written — so anything already older than the TTL expires on the first
sweep. That is the correct outcome and it will look alarming: a chunk of the
store will vanish from prompts the first time this runs. The rows are still
there, marked expired, and the daily pass will pull back anything that
mattered.

Backups written as .bak-memory.
"""
import os
import shutil
import sqlite3
import sys

RIFFLE = "/opt/riffle"
MEM = f"{RIFFLE}/agent/memory.py"
CYCLE = f"{RIFFLE}/agent/cycle.py"
DASH = f"{RIFFLE}/agent/dash.py"
CFG = f"{RIFFLE}/config.yaml"
DB = "/var/lib/riffle/state.sqlite"

CONFIG_BLOCK = """
# --- memory ---------------------------------------------------------------
# Short term is the default shelf and expires. Long term never does, and the
# daily pass may add at most max_promotions_per_day to it. The cap is what
# turns "is this worth keeping" into "is this among today's three most worth
# keeping", which is a question with a wrong answer.
memory:
  consolidate: true
  consolidate_after_hour_utc: 9    # first cycle at/after this hour each day
  short_ttl_days: 7
  max_promotions_per_day: 3
  purge_expired_after_days: 30     # expired rows are kept this long, then gone
  recall_long_slots: 3             # reserved slots so long term is never crowded out
"""


def patch(path, old, new, label, marker):
    s = open(path).read()
    if marker in s:
        print(f"  already present: {label}")
        return False
    if old not in s:
        sys.exit(f"  FAILED: anchor not found in {os.path.basename(path)} "
                 f"({label}). Nothing changed.")
    if not os.path.exists(f"{path}.bak-memory"):
        shutil.copy(path, f"{path}.bak-memory")
    open(path, "w").write(s.replace(old, new, 1))
    print(f"  patched: {label}")
    return True


NEW_RECALL = '''def recall(state, query, limit=8, long_slots=3):
    """Relevance first, then pinned, then long term, then recent short term.

    Three reserved slices, and the order matters. Keyword hits come first
    because a question deserves an answer about itself. Pinned next, because
    you chose those. Long term next, because a memory that survived the daily
    pass has already beaten the things around it. Recent short term fills what
    is left.

    Expired and superseded rows never appear. They are still in the table —
    "what did I once believe" stays answerable — but they no longer reach a
    prompt.
    """
    live = ("superseded_by IS NULL AND COALESCE(expired,0)=0")
    out, seen = [], set()
    pin_budget = max(1, limit // 4)
    long_budget = max(0, min(long_slots, limit - pin_budget - 1))

    terms = _terms(query)
    if terms:
        rows = []
        if _ensure_fts(state):
            try:
                expr = " OR ".join(f'"{t}"' for t in terms)
                rows = state.db.execute(
                    f"SELECT m.* FROM memories_fts f JOIN memories m ON m.id=f.rowid"
                    f" WHERE memories_fts MATCH ? AND {live}"
                    f" ORDER BY bm25(memories_fts) LIMIT ?",
                    (expr, limit * 3)).fetchall()
            except Exception:
                rows = []
        if not rows:
            like = " OR ".join(["text LIKE ?"] * len(terms))
            rows = state.db.execute(
                f"SELECT * FROM memories WHERE {live} AND ({like})"
                f" ORDER BY pinned DESC, id DESC LIMIT ?",
                [f"%{t}%" for t in terms] + [limit * 3]).fetchall()
        for r in rows:
            if len(out) >= limit - pin_budget - long_budget:
                break
            if r["id"] not in seen:
                out.append(r)
                seen.add(r["id"])

    for r in state.db.execute(
            f"SELECT * FROM memories WHERE pinned=1 AND {live}"
            f" ORDER BY id DESC LIMIT ?", (pin_budget,)):
        if r["id"] not in seen:
            out.append(r)
            seen.add(r["id"])

    if long_budget:
        for r in state.db.execute(
                f"SELECT * FROM memories WHERE tier='long' AND {live}"
                f" ORDER BY use_count DESC, id DESC LIMIT ?", (long_budget,)):
            if r["id"] not in seen:
                out.append(r)
                seen.add(r["id"])

    if len(out) < limit:
        for r in state.db.execute(
                f"SELECT * FROM memories WHERE {live} ORDER BY id DESC LIMIT ?",
                (limit * 2,)):
            if len(out) >= limit:
                break
            if r["id"] not in seen:
                out.append(r)
                seen.add(r["id"])

    out = out[:limit]
    if out:
        state.db.execute(
            f"UPDATE memories SET use_count=use_count+1, last_used=?"
            f" WHERE id IN ({','.join('?' * len(out))})",
            [utcnow()] + [r["id"] for r in out])
        state.db.commit()
    return out


'''


def main():
    if not os.path.exists(f"{RIFFLE}/agent/consolidate.py"):
        sys.exit("  agent/consolidate.py is missing — copy it in first.")

    # ---- database migration ----------------------------------------------
    con = sqlite3.connect(DB)
    cols = [r[1] for r in con.execute("PRAGMA table_info(memories)")]
    added = []
    for name, decl in (("tier", "TEXT DEFAULT 'short'"),
                       ("expires_at", "TEXT"),
                       ("expired", "INTEGER DEFAULT 0")):
        if name not in cols:
            con.execute(f"ALTER TABLE memories ADD COLUMN {name} {decl}")
            added.append(name)
    if added:
        # Pinned rows are a judgement you already made; honour it.
        con.execute("UPDATE memories SET tier='long' WHERE pinned=1")
        con.execute(
            "UPDATE memories SET tier='short',"
            " expires_at = datetime(substr(ts,1,19), '+7 days')"
            " WHERE COALESCE(pinned,0)=0")
        con.commit()
        n_long = con.execute("SELECT COUNT(*) FROM memories "
                             "WHERE tier='long'").fetchone()[0]
        n_short = con.execute("SELECT COUNT(*) FROM memories "
                              "WHERE tier='short'").fetchone()[0]
        print(f"  migrated memories: +{', '.join(added)}")
        print(f"    {n_long} long (were pinned), {n_short} short "
              f"(dated from when written)")
    else:
        print("  already present: tier columns")
    con.close()

    # ---- schema for new databases ----------------------------------------
    patch(f"{RIFFLE}/agent/state.py",
          "  use_count INTEGER DEFAULT 0, last_used TEXT,\n  superseded_by INTEGER);",
          "  use_count INTEGER DEFAULT 0, last_used TEXT,\n"
          "  superseded_by INTEGER,\n"
          "  tier TEXT DEFAULT 'short',   -- short (expires) | long (forever)\n"
          "  expires_at TEXT,\n"
          "  expired INTEGER DEFAULT 0);",
          "tier columns in the schema itself", marker="tier TEXT DEFAULT 'short'")

    # ---- config -----------------------------------------------------------
    cfg = open(CFG).read()
    if "\nmemory:" not in cfg:
        shutil.copy(CFG, f"{CFG}.bak-memory")
        open(CFG, "w").write(cfg.rstrip() + "\n" + CONFIG_BLOCK)
        print("  appended memory block to config.yaml")
    else:
        print("  already present: memory block")

    # ---- remember() stamps a tier ----------------------------------------
    patch(MEM,
          '''    cur = state.db.execute(
        "INSERT INTO memories (ts,kind,text,source,pinned) VALUES (?,?,?,?,?)",
        (utcnow(), kind, text, source, 1 if pinned else 0))''',
          '''    # Everything arrives in short term. Promotion is a decision made later,
    # with a day's distance and against competition — not at the moment of
    # writing, when everything feels worth keeping.
    import datetime as _dt
    exp = None if pinned else (
        _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(days=ttl_days)
    ).isoformat()
    cur = state.db.execute(
        "INSERT INTO memories (ts,kind,text,source,pinned,tier,expires_at)"
        " VALUES (?,?,?,?,?,?,?)",
        (utcnow(), kind, text, source, 1 if pinned else 0,
         "long" if pinned else "short", exp))''',
          "remember() writes to short term", marker="Everything arrives in short term")

    patch(MEM, "def remember(state, text, kind=\"operator\", source=None, pinned=0, supersedes=None):",
          "def remember(state, text, kind=\"operator\", source=None, pinned=0,\n"
          "             supersedes=None, ttl_days=7):",
          "remember() takes a ttl", marker="supersedes=None, ttl_days=7")

    # ---- tier-aware recall ------------------------------------------------
    s = open(MEM).read()
    if "long_slots=3" in s:
        print("  already present: tier-aware recall")
    else:
        a = s.index("def recall(state, query, limit=8")
        b = s.index("def as_context(rows):")
        if not os.path.exists(f"{MEM}.bak-memory"):
            shutil.copy(MEM, f"{MEM}.bak-memory")
        open(MEM, "w").write(s[:a] + NEW_RECALL + s[b:])
        print("  patched: tier-aware recall with reserved long-term slots")

    patch(MEM, '''    return "\\n".join(f"- [{r['kind']}] {r['text']}" for r in rows)''',
          '''    return "\\n".join(
        f"- [{r['kind']}"
        + ("/long" if (dict(r).get("tier") == "long") else "")
        + f"] {r['text']}" for r in rows)''',
          "context marks long-term entries", marker='"/long" if')

    # ---- cycle: sweep every wake, consolidate once a day -------------------
    patch(CYCLE, "from agent import chat, cortex, drives, goals, memory, notify, project",
          "from agent import (chat, consolidate, cortex, drives, goals, memory,\n"
          "                   notify, project)",
          "cycle imports consolidate", marker="consolidate, cortex")

    patch(CYCLE, "    # --- witness (always) --------------------------------------------------",
          '''    consolidate.sweep(state, cfg, log)
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

    # --- witness (always) --------------------------------------------------''',
          "sweep every cycle, consolidate once a day", marker="consolidate.due(state, cfg)")

    # ---- goals page shows the tier ----------------------------------------
    patch(DASH,
          '''                          "text": m["text"], "pinned": bool(m["pinned"]),
                          "use_count": m["use_count"]}''',
          '''                          "text": m["text"], "pinned": bool(m["pinned"]),
                          "use_count": m["use_count"],
                          "tier": dict(m).get("tier") or "short",
                          "expired": bool(dict(m).get("expired"))}''',
          "memory API returns tier", marker='"tier": dict(m).get("tier")')

    patch(DASH,
          """`<div class=mem><span class=k>${esc(m.kind)}${m.pinned?' · pinned':''}</span>""",
          """`<div class="mem${m.expired?' gone':''}"><span class=k>${esc(m.tier)}` +
      `${m.pinned?' · pinned':''}${m.expired?' · expired':''}</span>""",
          "memory list shows the tier", marker="m.expired?' gone':''")

    patch(DASH, ".mem .k{font-family:ui-monospace,monospace;font-size:10.5px;",
          ".mem.gone{opacity:.42}\n"
          ".mem .k{font-family:ui-monospace,monospace;font-size:10.5px;",
          "expired memories dimmed", marker=".mem.gone{")

    import ast
    for f in (MEM, CYCLE, DASH, f"{RIFFLE}/agent/state.py",
              f"{RIFFLE}/agent/consolidate.py"):
        ast.parse(open(f).read())
    print("\n  all modules parse.")
    print("""
  Next:
    sudo systemctl restart riffle-dash

  The first cycle at or after 09:00 UTC runs the pass. To see it now:
    sudo -u riffle python3 -c "import sys; sys.path.insert(0,'/opt/riffle'); \\
      from agent.state import State; from agent.cycle import load_config; \\
      from agent import consolidate; c=load_config('/opt/riffle/config.yaml'); \\
      s=State('/var/lib/riffle/state.sqlite'); \\
      print(consolidate.run(s,c,s.log,say=s.say))"

  Then look at the bottom of /goals — every memory now shows its shelf.""")


if __name__ == "__main__":
    main()
