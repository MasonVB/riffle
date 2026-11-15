"""Every figure the operator has been asked to fetch by hand, in one report.

WHY THIS EXISTS (2026-11-15, the operator's request)

For weeks each change ended with commands to run on the box and paste back:
`journalctl -u llama-composer ... | grep "prompt eval time"`, `systemctl show
llama-composer -p MemoryCurrent -p MemoryPeak; free -m`, a dozen sqlite
queries over cycles, actions, the journal, memories, questions and the
library, the auditor's box-check scripts. Each needed sudo, each was typed on
a phone, and each answered one question. This module records what those
commands read, and writes it as one plain-text report:

  - on the dashboard, at /figures, with a button that copies all of it;
  - as a file, figures.txt in the data directory, rewritten after every cycle
    (`sudo cat /var/lib/riffle/figures.txt`).

Copy either and paste it; it carries everything the last month's requests
asked for, and the figures I would have asked for next.

TWO THINGS ARE NEWLY RECORDED, because nothing kept them:

  composer_calls  every call to a model: what it was for, how many characters
                  went, how many tokens the server READ, how many it REUSED
                  from its cache, how many it WROTE, the milliseconds of each,
                  how it finished. llama-server returns these (`timings`,
                  `usage`) in every response, and cortex threw them away; the
                  only copy was the server's own log, which only sudo reads.
                  This is what "prompt eval time" was fetched for, and it adds
                  the cache reuse and the measured characters per token.
  prompt_fits     each cycle's fit: the ceiling, the running window, the room,
                  and every block's size wanted and sent. What the "blocks
                  before fitting" and "prompt fitted" queries were for.

Both are pruned to 30 days. Nothing here can change what a cycle does:
every reading is guarded, and a failure costs its own line of the report.

WHAT IT CANNOT READ, by design: the composer's systemd journal and the CPU's
package power (RAPL) both need root, and the cycle runs as riffle. The
timings above replace the first; the power reading is left out.
"""
import datetime as dt
import json
import os
import platform
import re
import socket
import statistics
import time
import urllib.request

SCHEMA = """
CREATE TABLE IF NOT EXISTS composer_calls (
  id INTEGER PRIMARY KEY, at TEXT, cycle_id INTEGER, purpose TEXT, port INTEGER,
  chars INTEGER, max_tokens INTEGER, finish TEXT,
  prompt_n INTEGER, cache_n INTEGER, prompt_ms REAL,
  predicted_n INTEGER, predicted_ms REAL, wall_s REAL, error TEXT);
CREATE INDEX IF NOT EXISTS ix_ccalls_at ON composer_calls(at);
CREATE TABLE IF NOT EXISTS prompt_fits (
  id INTEGER PRIMARY KEY, at TEXT, cycle_id INTEGER, ceiling INTEGER,
  running_ctx INTEGER, sys_chars INTEGER, tail_chars INTEGER, room INTEGER,
  wanted INTEGER, sent INTEGER, blocks TEXT);
CREATE INDEX IF NOT EXISTS ix_pfits_at ON prompt_fits(at);
"""
KEEP_DAYS = 30


def ensure(state):
    state.db.executescript(SCHEMA)
    state.db.commit()


def _utc(hours_ago=0):
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours_ago)
            ).strftime("%Y-%m-%dT%H:%M:%SZ")


# ------------------------------------------------------------------ recording
def save_calls(state, calls, cycle_id=None):
    """Store the model calls cortex noted (cortex.CALLS), and empty that list."""
    if not calls:
        return 0
    ensure(state)
    taken = []
    while calls:                      # pop, not copy-and-clear: another
        try:                          # thread may be adding to it (the chat)
            taken.append(calls.pop(0))
        except IndexError:
            break
    rows = []
    for c in taken:
        t = c.get("timings") or {}
        u = c.get("usage") or {}
        rows.append((c.get("at"), cycle_id, c.get("purpose"), c.get("port"),
                     c.get("chars"), c.get("max_tokens"), c.get("finish"),
                     t.get("prompt_n", u.get("prompt_tokens")), t.get("cache_n"),
                     t.get("prompt_ms"), t.get("predicted_n", u.get("completion_tokens")),
                     t.get("predicted_ms"), c.get("wall_s"), c.get("error")))
    state.db.executemany(
        "INSERT INTO composer_calls (at,cycle_id,purpose,port,chars,max_tokens,finish,"
        "prompt_n,cache_n,prompt_ms,predicted_n,predicted_ms,wall_s,error)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    state.db.commit()
    return len(rows)


def record_fit(state, cycle_id, ceiling, running_ctx, sys_chars, tail_chars,
               room, before, after, name_of):
    """One row per cycle: each block's size wanted (before) and sent (after)."""
    try:
        ensure(state)
        blocks = {}
        for b, a in zip(before, after):
            n = name_of(b)
            if n in blocks:
                n = f"{n} #{sum(1 for k in blocks if k.startswith(n)) + 1}"
            blocks[n] = [len(b), len(a)]
        state.db.execute(
            "INSERT INTO prompt_fits (at,cycle_id,ceiling,running_ctx,sys_chars,"
            "tail_chars,room,wanted,sent,blocks) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (_utc(), cycle_id, ceiling, running_ctx, sys_chars, tail_chars, room,
             sum(len(b) for b in before), sum(len(a) for a in after),
             json.dumps(blocks)))
        state.db.commit()
    except Exception:
        pass


def prune(state):
    try:
        ensure(state)
        lo = _utc(24 * KEEP_DAYS)
        state.db.execute("DELETE FROM composer_calls WHERE at < ?", (lo,))
        state.db.execute("DELETE FROM prompt_fits WHERE at < ?", (lo,))
        state.db.commit()
    except Exception:
        pass


def after_cycle(state, cfg, calls):
    """Called once when a cycle process ends: store its calls, prune, and
    rewrite figures.txt. Never raises."""
    try:
        cid = (state.db.execute("SELECT MAX(id) FROM cycles").fetchone() or [None])[0]
        save_calls(state, calls, cid)
        prune(state)
        data = os.path.expanduser(cfg.get("data_dir", "/var/lib/riffle"))
        text = report(state, cfg)
        tmp = os.path.join(data, ".figures.txt.tmp")
        with open(tmp, "w") as f:
            f.write(text)
        os.chmod(tmp, 0o644)
        os.replace(tmp, os.path.join(data, "figures.txt"))
    except Exception:
        pass


# ------------------------------------------------------------------- helpers
def _med(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def _n(x, d=0):
    if x is None:
        return "-"
    if isinstance(x, float) and d:
        return f"{x:,.{d}f}"
    return f"{int(round(x)):,}"


def _read(path, limit=200000):
    try:
        with open(path, errors="replace") as f:
            return f.read(limit)
    except OSError:
        return None


def _git_head(repo):
    """The short commit a checkout is at, read from .git without running git."""
    try:
        head = (_read(os.path.join(repo, ".git", "HEAD")) or "").strip()
        if head.startswith("ref: "):
            ref = head[5:]
            sha = (_read(os.path.join(repo, ".git", ref)) or "").strip()
            if not sha:
                for line in (_read(os.path.join(repo, ".git", "packed-refs")) or "").splitlines():
                    if line.endswith(" " + ref):
                        sha = line.split()[0]
            return sha[:9] or "?"
        return head[:9] or "?"
    except Exception:
        return "?"


def _q(state, sql, args=()):
    try:
        return state.db.execute(sql, args).fetchall()
    except Exception:
        return []


def _one(state, sql, args=(), default=None):
    r = _q(state, sql, args)
    return r[0][0] if r and r[0][0] is not None else default


def _cg(unit, name):
    v = _read(f"/sys/fs/cgroup/system.slice/{unit}.service/{name}")
    try:
        return int(v.strip()) if v and v.strip() != "max" else None
    except ValueError:
        return None


def _gb(b):
    return "-" if b is None else f"{b / 1e9:.1f} GB"


def _props(url):
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/props", timeout=4) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except Exception:
        return None


def _unit_flags(path):
    text = _read(path) or ""
    text = " ".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))
    out = {}
    for flag in ("ctx-size", "checkpoint-min-step", "ctx-checkpoints", "cache-ram",
                 "threads", "batch-size", "ubatch-size", "parallel", "cache-reuse"):
        m = re.search(r"--" + flag + r"[\s=]+(\S+)", text)
        if m:
            out[flag] = m.group(1)
    return out


# -------------------------------------------------------------------- report
def report(state, cfg):
    """The whole report, as text. Each section is guarded on its own."""
    out = []

    def sec(title, fn):
        out.append(f"\n== {title}")
        try:
            fn()
        except Exception as e:
            out.append(f"  (could not read: {type(e).__name__}: {e})"[:200])

    def say(s=""):
        out.append(s)

    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    now_l = time.strftime("%Y-%m-%d %H:%M %Z")
    say(f"riffle figures, {_utc()} ({now_l}), riffle at {_git_head(here)}")
    say("Copy all of this and paste it as it is.")

    def machine():
        up = _read("/proc/uptime")
        up_h = float(up.split()[0]) / 3600 if up else None
        model = next((l.split(":", 1)[1].strip() for l in (_read("/proc/cpuinfo") or "").splitlines()
                      if l.startswith("model name")), "?")
        say(f"  host {socket.gethostname()}, Python {platform.python_version()}, "
            f"up {_n(up_h, 1)} h, boot {(_read('/proc/sys/kernel/random/boot_id') or '?').strip()[:8]}")
        say(f"  cpu {model}, {os.cpu_count()} threads")
        from agent import telemetry
        m, c = telemetry.memory(), telemetry.cpu()
        say(f"  memory: total {_n(m.get('MemTotal'))} MiB, available {_n(m.get('MemAvailable'))} MiB, "
            f"swap used {_n((m.get('SwapTotal') or 0) - (m.get('SwapFree') or 0))} MiB of {_n(m.get('SwapTotal'))}")
        say(f"  load {c.get('load1')} {c.get('load5')} {c.get('load15')}, clock avg {c.get('mhz_avg')} MHz "
            f"(max {c.get('mhz_max')}), governor {c.get('governor')}")
        for u in ("llama-composer", "llama-triage"):
            say(f"  {u}: memory now {_gb(_cg(u, 'memory.current'))}, peak {_gb(_cg(u, 'memory.peak'))}, "
                f"swap {_gb(_cg(u, 'memory.swap.current'))}")
        t = telemetry.temps()
        flat = []
        for chip, v in (t or {}).items():
            if isinstance(v, dict):
                flat += [(f"{chip}/{k}", x) for k, x in v.items() if isinstance(x, (int, float))]
            elif isinstance(v, (int, float)):
                flat.append((chip, v))
        if flat:
            hot = sorted(flat, key=lambda kv: -kv[1])[:4]
            say("  hottest now: " + ", ".join(f"{k} {v}" for k, v in hot))
        for p, d in telemetry.disks().items():
            say(f"  disk {p}: {d['free_gb']} GB free of {d['total_gb']} ({d['pct_used']}% used)")
        # The last day of the once-a-minute samples, at their extremes.
        rows = _q(state, "SELECT payload FROM telemetry WHERE kind='sample' AND ts > ?", (_utc(24),))
        avail, load, temp = [], [], []
        for (p,) in rows:
            try:
                j = json.loads(p)
            except ValueError:
                continue
            avail.append((j.get("mem") or {}).get("MemAvailable"))
            load.append((j.get("cpu") or {}).get("load1"))
            for chip, v in (j.get("temps") or {}).items():
                if isinstance(v, dict):
                    temp += [x for x in v.values() if isinstance(x, (int, float))]
        if rows:
            say(f"  last 24 h, {len(rows)} samples: least memory available "
                f"{_n(min([a for a in avail if a is not None], default=None))} MiB, "
                f"highest load {max([x for x in load if x is not None], default='-')}, "
                f"hottest {max(temp, default='-')}")

    def composer():
        comp = (cfg.get("llm") or {}).get("composer") or {}
        pr = _props(comp.get("url", "http://127.0.0.1:8080"))
        if pr:
            g = pr.get("default_generation_settings") or {}
            say(f"  running: window {g.get('n_ctx') or pr.get('n_ctx')} tokens, slots "
                f"{pr.get('total_slots')}, model {os.path.basename(str(pr.get('model_path') or '?'))}")
        else:
            say("  running: did not answer /props")
        for path in ("/etc/systemd/system/llama-composer.service",):
            f = _unit_flags(path)
            if f:
                say("  installed unit: " + ", ".join(f"--{k} {v}" for k, v in f.items()))
        f = _unit_flags(os.path.join(here, "systemd", "llama-composer.service"))
        if f:
            say("  repository unit: " + ", ".join(f"--{k} {v}" for k, v in f.items()))
        say(f"  llama.cpp at {_git_head('/opt/llama.cpp')}; max_tokens {comp.get('max_tokens')}, "
            f"temperature {comp.get('temperature')}")
        rows = _q(state, "SELECT * FROM composer_calls WHERE at > ? ORDER BY id", (_utc(24),))
        if not rows:
            say("  no model calls recorded in the last 24 h (recording began 2026-11-15)")
            return
        say("  model calls, last 24 h, by purpose. read = tokens the server processed; reused =")
        say("  tokens taken from its cache; wrote = tokens generated; medians, with the largest after /")
        by = {}
        for r in rows:
            by.setdefault(f"{r['purpose'] or '?'}@{r['port'] or '?'}", []).append(r)
        for k, rs in sorted(by.items()):
            ok = [r for r in rs if not r["error"]]
            rate = [r["prompt_n"] / (r["prompt_ms"] / 1000) for r in ok
                    if r["prompt_n"] and r["prompt_ms"]]
            wrate = [r["predicted_n"] / (r["predicted_ms"] / 1000) for r in ok
                     if r["predicted_n"] and r["predicted_ms"]]
            cpt = [r["chars"] / (r["prompt_n"] + (r["cache_n"] or 0)) for r in ok
                   if r["chars"] and r["prompt_n"]]
            say(f"    {k:22} {len(rs):3} calls, {len(rs) - len(ok)} failed | read "
                f"{_n(_med([r['prompt_n'] for r in ok]))}/{_n(max([r['prompt_n'] or 0 for r in ok], default=None))}"
                f" | reused {_n(_med([r['cache_n'] for r in ok]))} | wrote "
                f"{_n(_med([r['predicted_n'] for r in ok]))}/{_n(max([r['predicted_n'] or 0 for r in ok], default=None))}"
                f" | read {_n(_med(rate), 1)} tok/s, write {_n(_med(wrate), 1)} tok/s | "
                f"{_n(_med([r['wall_s'] for r in rs]))}/{_n(max([r['wall_s'] or 0 for r in rs], default=None))} s"
                f" | {_n(_med(cpt), 2)} chars/token")
        cold = [r for r in rows if not r["error"] and (r["cache_n"] or 0) < 1000 and (r["prompt_n"] or 0) > 5000]
        if cold:
            w = max(cold, key=lambda r: r["wall_s"] or 0)
            say(f"  cold reads (under 1,000 reused): {len(cold)}, the slowest {_n(w['wall_s'])} s for "
                f"{_n(w['prompt_n'])} tokens read ({w['at'][:16]}); the call times out at 1,800 s")
        cut = [r for r in rows if r["finish"] == "length"]
        if cut:
            say(f"  cut off at max_tokens: {len(cut)}")
        for r in [r for r in rows if r["error"]][-3:]:
            say(f"  failed {r['at'][:16]} {r['purpose']}: {(r['error'] or '')[:150]}")
        say("  last 10 calls: time, purpose, chars sent, read, reused, wrote, seconds, finish")
        for r in rows[-10:]:
            say(f"    {r['at'][5:16]} {(r['purpose'] or '?')[:14]:14} {_n(r['chars']):>8} "
                f"{_n(r['prompt_n']):>7} {_n(r['cache_n']):>7} {_n(r['predicted_n']):>6} "
                f"{_n(r['wall_s']):>6} {r['finish'] or (r['error'] or '')[:30]}")

    def prompt():
        ccfg = cfg.get("cycle") or {}
        say(f"  max_prompt_chars {ccfg.get('max_prompt_chars')}, interval {ccfg.get('interval_minutes')} min "
            f"(set: {_one(state, 'SELECT value FROM notes WHERE key=?', ('cycle_interval_minutes',), 'config')})")
        rows = _q(state, "SELECT * FROM prompt_fits ORDER BY id DESC LIMIT 100")
        if rows:
            r = rows[0]
            say(f"  last fit ({r['at'][:16]}, cycle {r['cycle_id']}): ceiling {_n(r['ceiling'])}, running window "
                f"{_n(r['running_ctx'])} tokens, system {_n(r['sys_chars'])}, end {_n(r['tail_chars'])}, room "
                f"{_n(r['room'])}; blocks wanted {_n(r['wanted'])}, sent {_n(r['sent'])}")
            say(f"  last {len(rows)} fits: blocks wanted median {_n(_med([x['wanted'] for x in rows]))}, max "
                f"{_n(max(x['wanted'] for x in rows))}; sent median {_n(_med([x['sent'] for x in rows]))}; "
                f"room median {_n(_med([x['room'] for x in rows]))}; cycles with any block cut: "
                f"{sum(1 for x in rows if x['sent'] < x['wanted'])}")
            per = {}
            for x in rows:
                try:
                    for name, (w, s) in json.loads(x["blocks"] or "{}").items():
                        per.setdefault(name, []).append((w, s))
                except (ValueError, TypeError):
                    continue
            say("  each block over those fits: in how many, wanted median/max, and how often cut (sent less)")
            for name, ws in sorted(per.items(), key=lambda kv: -(_med([w for w, _ in kv[1]]) or 0))[:32]:
                cuts = [(w, s) for w, s in ws if s < w]
                say(f"    {name[:44]:44} {len(ws):3} | {_n(_med([w for w, _ in ws])):>6}/{_n(max(w for w, _ in ws)):>6}"
                    + (f" | cut {len(cuts)}x, median sent {_n(_med([s for _, s in cuts]))}" if cuts else ""))
        for (t,) in _q(state, "SELECT text FROM journal WHERE text LIKE 'prompt sent%'"
                              " ORDER BY id DESC LIMIT 4"):
            say("  " + t[:200])
        for (ts, t) in _q(state, "SELECT ts, text FROM journal WHERE (text LIKE 'cap cuts%'"
                                 " OR text LIKE 'prompt fitted%' OR text LIKE '%running composer%'"
                                 " OR text LIKE 'prompt STILL over%') AND ts > ? ORDER BY id DESC LIMIT 8",
                          (_utc(24),)):
            say(f"  {ts[5:16]} {t[:260]}")

    def cycles():
        rows = _q(state, "SELECT * FROM cycles WHERE started_at > ? ORDER BY id", (_utc(24),))
        oc = {}
        for r in rows:
            oc[r["outcome"]] = oc.get(r["outcome"], 0) + 1
        durs, gaps = [], []
        prev = None
        for r in rows:
            try:
                a = dt.datetime.fromisoformat(r["started_at"].replace("Z", "+00:00"))
                if r["ended_at"]:
                    durs.append((dt.datetime.fromisoformat(r["ended_at"].replace("Z", "+00:00")) - a).total_seconds())
                if prev:
                    gaps.append((a - prev).total_seconds() / 60)
                prev = a
            except (ValueError, AttributeError, TypeError):
                pass
        say(f"  last 24 h: {len(rows)} cycles, each took median {_n(_med(durs))} s (max {_n(max(durs, default=None))}),"
            f" started median {_n(_med(gaps), 1)} min apart")
        say("  outcomes: " + ", ".join(f"{k} {v}" for k, v in sorted(oc.items(), key=lambda kv: -kv[1])))
        say("  last 40: id, time (UTC), drive, outcome, notes | first action and its rationale")
        for c in reversed(_q(state, "SELECT * FROM cycles ORDER BY id DESC LIMIT 40")):
            a = _q(state, "SELECT kind, status, rationale FROM actions WHERE cycle_id=? ORDER BY id LIMIT 1", (c["id"],))
            a = a[0] if a else None
            say(f"    #{c['id']} {(c['started_at'] or '')[5:16]} {(c['drive'] or '')[:10]:10} "
                f"{(c['outcome'] or '')[:18]:18} {(c['notes'] or '')[:36]:36} | "
                + (f"{a['kind']} [{a['status']}] {(a['rationale'] or '')[:90]}" if a else ""))

    def actions():
        rows = _q(state, "SELECT kind, status, COUNT(*) n FROM actions WHERE created_at > ?"
                         " GROUP BY kind, status ORDER BY kind", (_utc(24),))
        say("  last 24 h: " + "; ".join(f"{r['kind']} {r['status']} {r['n']}" for r in rows))
        last = _one(state, "SELECT MAX(COALESCE(executed_at, created_at)) FROM actions"
                           " WHERE status='executed' AND kind IN ('post','comment','porch','vote','tag',"
                           "'seal','attestation','flag','listing_submission','knock')", (), None)
        if last:
            try:
                h = (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(
                    last.replace("Z", "+00:00"))).total_seconds() / 3600
                say(f"  last thing that reached the square: {last[:16]}, {h:.1f} h ago")
            except ValueError:
                pass
        rows = _q(state, "SELECT substr(COALESCE(executed_at, created_at),1,10) d, kind, COUNT(*) n"
                         " FROM actions WHERE status='executed' AND COALESCE(executed_at, created_at) > ?"
                         " AND kind IN ('post','comment','porch','vote','tag','seal','attestation','flag',"
                         "'listing_submission') GROUP BY d, kind ORDER BY d", (_utc(24 * 7),))
        days = {}
        for r in rows:
            days.setdefault(r["d"], []).append(f"{r['kind']} {r['n']}")
        say("  sent per day, last 7 days: " + ("; ".join(f"{d[5:]}: {', '.join(v)}" for d, v in days.items())
                                             or "nothing"))
        rows = _q(state, "SELECT status, COUNT(*) n FROM actions WHERE status IN"
                         " ('queued','sending','approved','running','unknown') GROUP BY status")
        say("  waiting now: " + (", ".join(f"{r['status']} {r['n']}" for r in rows) or "nothing"))
        for r in _q(state, "SELECT id, kind, created_at, response FROM actions WHERE status='unknown' ORDER BY id"):
            say(f"    unknown #{r['id']} {r['kind']} {r['created_at'][:16]} {(r['response'] or '')[:100]}")
        rows = _q(state, "SELECT outcome, COUNT(*) n FROM cycles WHERE started_at > ? AND outcome NOT IN"
                         " ('executed','queued','noop','thread-read','built','library-searched','library-read',"
                         "'desk-updated','desk-placed','desk-cleared','fetched','note-added','asked','page-read',"
                         "'searched','remembered','thread-exhausted') GROUP BY outcome ORDER BY n DESC", (_utc(24 * 7),))
        say("  refused or failed, last 7 days: " + (", ".join(f"{r['outcome']} {r['n']}" for r in rows) or "none"))
        lib = [x[0] or "" for x in _q(state, "SELECT sha256 FROM library")]
        rows = _q(state, "SELECT started_at, outcome, notes FROM cycles WHERE outcome IN"
                         " ('hash-unknown','hash-unresolvable','seal-not-held') AND started_at > ?"
                         " ORDER BY id DESC LIMIT 8", (_utc(24 * 7),))
        for r in rows:
            h = re.sub(r"[^0-9a-f]", "", (r["notes"] or "").lower())
            say(f"    {r['started_at'][5:16]} {r['outcome']}: {(r['notes'] or '')[:44]} | starts like a library "
                f"hash: {bool(h) and len(h) >= 12 and any(x.startswith(h[:12]) for x in lib)}")
        rows = _q(state, "SELECT substr(started_at,1,10) d, outcome, notes, COUNT(*) n FROM cycles WHERE outcome IN"
                         " ('listing-not-open','payout-without-work','listing-ignored') AND started_at > ?"
                         " GROUP BY d, outcome, notes ORDER BY d", (_utc(24 * 7),))
        if rows:
            say("  listing work refused, last 7 days: " + "; ".join(
                f"{r['d'][5:]} {r['outcome']} {(r['notes'] or '')[:8]} x{r['n']}" for r in rows))
        say("  seals and attestations, last 5: id, time, kind, status, signed, what")
        for r in _q(state, "SELECT * FROM actions WHERE kind IN ('seal','attestation') ORDER BY id DESC LIMIT 5"):
            try:
                pl, resp = json.loads(r["payload"] or "{}"), json.loads(r["response"] or "{}")
            except ValueError:
                pl, resp = {}, {}
            what = (f"#{pl.get('library_id')} {pl.get('label')}" if r["kind"] == "seal" else
                    f"{pl.get('cls')} {pl.get('subject')}: {(pl.get('claim') or '')[:60]} | evidence {pl.get('evidence')}")
            signed = ("-" if r["status"] != "executed" else
                      ("no: " + str(resp.get("unsigned_because"))[:40]) if resp.get("unsigned_because") else "yes")
            say(f"    #{r['id']} {r['created_at'][5:16]} {r['kind']} {r['status']} {signed} | {what[:140]}")
        say("  posts, last 6: id, time, status, title")
        for r in _q(state, "SELECT id, created_at, status, payload FROM actions WHERE kind='post' ORDER BY id DESC LIMIT 6"):
            try:
                t = json.loads(r["payload"] or "{}").get("title") or ""
            except ValueError:
                t = ""
            say(f"    #{r['id']} {r['created_at'][5:16]} {r['status']:9} {t[:80]}")

    def questions():
        try:
            from agent.state import open_questions
            qs = open_questions(state)
        except Exception:
            qs = []
        say(f"  open: {len(qs)}")
        for q in qs:
            seen = _one(state, "SELECT seen FROM questions WHERE id=?", (q["id"],), 0)
            say(f"    #{q['id']} asked {(q['asked_at'] or '')[:16]}, pushed {'yes' if seen else 'no'}: "
                f"{(q['question'] or '')[:120]}")
        say(f"  answered in the last 7 days: "
            f"{_one(state, 'SELECT COUNT(*) FROM questions WHERE answered_at > ?', (_utc(24 * 7),), 0)}")

    def memory():
        rows = _q(state, "SELECT tier, kind, pinned, COALESCE(expired,0) e, COUNT(*) n FROM memories"
                         " GROUP BY tier, kind, pinned, e ORDER BY tier, kind")
        say("  tier/kind/pinned/expired: " + "; ".join(
            f"{r['tier']} {r['kind']} p{r['pinned']} x{r['e']} {r['n']}" for r in rows))
        try:
            fts = _one(state, "SELECT COUNT(*) FROM memories_fts", (), None)
            mem = _one(state, "SELECT COUNT(*) FROM memories", (), None)
            if fts is not None:
                say(f"  search index rows {fts} for {mem} memories (more rows than memories = orphans)")
        except Exception:
            pass
        for (ts, t) in _q(state, "SELECT ts, text FROM journal WHERE (text LIKE 'memory pass%'"
                                 " OR text LIKE 'consolidat%' OR text LIKE 'daily memory%') ORDER BY id DESC LIMIT 4"):
            say(f"  {ts[5:16]} {t[:200]}")
        rows = _q(state, "SELECT CASE WHEN key LIKE 'reflect_fail_%' THEN 'reflect_fail_*'"
                         " WHEN key LIKE 'extra_cycles_%' THEN 'extra_cycles_*' WHEN key LIKE 'seeded:%' THEN 'seeded:*'"
                         " ELSE 'fixed keys' END k, COUNT(*) n FROM notes GROUP BY k")
        say("  notes table: " + ", ".join(f"{r['k']} {r['n']}" for r in rows))

    def work():
        # The witness pass is riffle's one obligation: when it last walked
        # each chain, and to where.
        rows = _q(state, "SELECT chain, MAX(ts) ts, head, through_id FROM heads GROUP BY chain")
        if rows:
            say("  witness: " + "; ".join(f"{r['chain']} {(r['ts'] or '')[:16]} through "
                                          f"{r['through_id']}" for r in rows))
        else:
            say("  witness: no marks recorded")
        try:
            from agent import project
            p = project.active(state)
            if p:
                s = project.stats(state, p["id"])
                say(f"  project #{p['id']} {p['title'][:70]!r}, opened {(p['opened_at'] or '')[:16]}, "
                    f"notes {s.get('notes')}, sources {s.get('sources')}")
            else:
                say("  no project open")
        except Exception as e:
            say(f"  project: {type(e).__name__}")
        rows = _q(state, "SELECT slot, kind, length(body) n, updated_at FROM desk ORDER BY rowid")
        say(f"  desk: {len(rows)} slot(s), {sum(r['n'] for r in rows):,} chars" + "".join(
            f"\n    {r['slot'][:40]} {r['kind']} {r['n']} chars, {(r['updated_at'] or '')[5:16]}" for r in rows))
        rows = _q(state, "SELECT kind, COUNT(*) n FROM library GROUP BY kind")
        say("  library: " + ", ".join(f"{r['kind']} {r['n']}" for r in rows))
        try:
            lb = json.loads(_one(state, "SELECT value FROM notes WHERE key='last_build'", (), "{}") or "{}")
            if lb:
                say(f"  last build {lb.get('at', '')[:16]} {lb.get('entry')} ok={lb.get('ok')} exit {lb.get('exit_code')}, "
                    f"library #{lb.get('library_id')}, files " + ", ".join(
                        f"{n} {h[:12]}" for n, h in (lb.get("file_sha256") or {}).items()))
        except (ValueError, TypeError):
            pass

    def settings():
        try:
            from agent import policy
            m = policy.effective(state, cfg)
            groups = {}
            for k, v in sorted(m.items()):
                groups.setdefault(v, []).append(k)
            for v, ks in groups.items():
                say(f"  {v}: {', '.join(ks)}")
        except Exception as e:
            say(f"  autonomy: {type(e).__name__}")
        say(f"  caps: {cfg.get('caps')}")
        say(f"  listings.ignore: {(cfg.get('listings') or {}).get('ignore')}, notify.enabled: "
            f"{(cfg.get('notify') or {}).get('enabled')}")
        rows = _q(state, "SELECT kind, used FROM caps WHERE day_utc=?", (_utc()[:10],))
        say("  used today (UTC): " + (", ".join(f"{r['kind']} {r['used']}" for r in rows) or "nothing"))

    def journal():
        n = _q(state, "SELECT level, COUNT(*) n FROM journal WHERE ts > ? AND level IN ('warn','error','alarm')"
                      " GROUP BY level", (_utc(24),))
        say("  last 24 h: " + (", ".join(f"{r['level']} {r['n']}" for r in n) or "no warnings or errors"))
        for r in reversed(_q(state, "SELECT ts, level, text FROM journal WHERE level IN ('warn','error','alarm')"
                                    " ORDER BY id DESC LIMIT 15")):
            say(f"    {r['ts'][5:16]} {r['level']:5} {(r['text'] or '')[:180]}")

    sec("THE MACHINE", machine)
    sec("THE COMPOSER", composer)
    sec("THE PROMPT", prompt)
    sec("CYCLES", cycles)
    sec("ACTIONS", actions)
    sec("QUESTIONS FOR YOU", questions)
    sec("MEMORY", memory)
    sec("WORK", work)
    sec("SETTINGS", settings)
    sec("WARNINGS AND ERRORS", journal)
    return "\n".join(out) + "\n"
