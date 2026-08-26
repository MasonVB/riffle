"""What the machine and the agent were doing, so an error can be traced after it.

WHY SAMPLING AND DUMPING ARE DIFFERENT THINGS

A sample is cheap and constant: temperatures, memory, disk, load, whether the
four services are up, what the agent is in the middle of. One a minute, kept
for a day. Its job is to answer "what was happening in the ten minutes before
this went wrong", which is the question you cannot ask afterwards unless
something was already writing it down.

A dump is expensive and rare: everything a sample has, plus the recent
journal, the last cycles and actions, the state of every unit, and the tail of
the composer's own log. It fires on an error or an alarm, when the extra cost
is obviously worth paying.

Four freezes in two days were unexplainable because nothing was recording. The
distinction matters: if this had been running, the last sample before each
freeze would have said whether memory was climbing or whether the box died
mid-stride at normal usage — software or hardware, which is the whole question.

RETENTION IS 24 HOURS

Long enough to trace last night, short enough that nobody has to think about
it. About 1,440 samples a day, a megabyte or so.
"""
import datetime as dt
import glob
import json
import os
import re
import shutil
import subprocess
import urllib.request

SCHEMA = """
CREATE TABLE IF NOT EXISTS telemetry (
  id INTEGER PRIMARY KEY, ts TEXT, kind TEXT, label TEXT, payload TEXT);
CREATE INDEX IF NOT EXISTS ix_tel_ts ON telemetry(ts);
"""

UNITS = ("llama-composer", "llama-triage", "riffle-dash", "riffle-cycle.timer",
         "riffle-restart-composer.path")


def ensure(state):
    state.db.executescript(SCHEMA)
    state.db.commit()


# ------------------------------------------------------------------ readings
def temps():
    """Read hwmon directly. `sensors` may not be installed and this cannot
    depend on it — telemetry that fails when a package is missing is telemetry
    that is absent on exactly the machine you need it from."""
    out = {}
    for p in glob.glob("/sys/class/hwmon/hwmon*"):
        try:
            name = open(os.path.join(p, "name")).read().strip()
        except OSError:
            continue
        for f in sorted(glob.glob(os.path.join(p, "temp*_input"))):
            try:
                v = int(open(f).read().strip()) / 1000.0
            except (OSError, ValueError):
                continue
            lbl = f.replace("_input", "_label")
            try:
                key = open(lbl).read().strip()
            except OSError:
                key = os.path.basename(f).replace("_input", "")
            out[f"{name}.{key}"] = round(v, 1)
    for f in sorted(glob.glob("/sys/class/thermal/thermal_zone*/temp")):
        try:
            zone = open(f.replace("temp", "type")).read().strip()
            out.setdefault(zone, round(int(open(f).read()) / 1000.0, 1))
        except (OSError, ValueError):
            continue
    return out


def memory():
    m = {}
    try:
        for line in open("/proc/meminfo"):
            k, _, v = line.partition(":")
            if k in ("MemTotal", "MemFree", "MemAvailable", "Buffers", "Cached",
                     "SwapTotal", "SwapFree", "Dirty"):
                m[k] = int(v.split()[0]) // 1024          # MiB
    except OSError:
        pass
    if "MemTotal" in m and "MemAvailable" in m:
        m["UsedMiB"] = m["MemTotal"] - m["MemAvailable"]
        m["PctUsed"] = round(100.0 * m["UsedMiB"] / m["MemTotal"], 1)
    return m


def cpu():
    out = {}
    try:
        out["load1"], out["load5"], out["load15"] = [
            float(x) for x in open("/proc/loadavg").read().split()[:3]]
    except (OSError, ValueError):
        pass
    mhz = []
    try:
        for line in open("/proc/cpuinfo"):
            if line.startswith("cpu MHz"):
                mhz.append(float(line.split(":")[1]))
    except (OSError, ValueError, IndexError):
        pass
    if mhz:
        out["mhz_avg"] = round(sum(mhz) / len(mhz))
        out["mhz_max"] = round(max(mhz))
    try:
        gov = open("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor").read()
        out["governor"] = gov.strip()
    except OSError:
        pass
    return out


def disks(paths=("/", "/opt", "/var/lib/riffle", "/opt/models")):
    out = {}
    for p in paths:
        try:
            s = os.statvfs(p)
        except OSError:
            continue
        out[p] = {"free_gb": round(s.f_bavail * s.f_frsize / 1e9, 1),
                  "total_gb": round(s.f_blocks * s.f_frsize / 1e9, 1),
                  "pct_used": round(100.0 * (1 - s.f_bavail / max(1, s.f_blocks)), 1)}
    return out


def services():
    out = {}
    sc = shutil.which("systemctl")
    if not sc:
        return out
    for u in UNITS:
        try:
            r = subprocess.run([sc, "is-active", u], capture_output=True,
                               text=True, timeout=5)
            out[u] = r.stdout.strip() or r.stderr.strip()[:40]
        except Exception as e:
            out[u] = f"?{type(e).__name__}"
    return out


def model_health(port=8080):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health",
                                    timeout=4) as r:
            return {"status": r.status}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"[:80]}


def agent_state(state, cfg):
    out = {}
    try:
        c = state.db.execute(
            "SELECT id, drive, outcome, started_at, ended_at FROM cycles"
            " ORDER BY id DESC LIMIT 1").fetchone()
        if c:
            out["last_cycle"] = dict(c)
        out["queued"] = len(state.queued())
        for name, q in (("db_bytes", None),):
            pass
        p = os.path.join(os.path.expanduser(cfg.get("data_dir", "/var/lib/riffle")),
                         "state.sqlite")
        if os.path.exists(p):
            out["db_mb"] = round(os.path.getsize(p) / 1e6, 1)
        r = state.db.execute(
            "SELECT COUNT(*) c FROM journal WHERE level IN ('error','alarm')"
            " AND ts > ?", (_ago(hours=1),)).fetchone()
        out["errors_last_hour"] = r["c"] if r else 0
        try:
            from agent import project
            pr = project.active(state)
            if pr:
                s = project.stats(state, pr["id"])
                out["project"] = {"title": pr["title"][:60], "notes": s["notes"],
                                  "sources": s["sources"]}
        except Exception:
            pass
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"[:120]
    return out


def _ago(hours=24):
    return (dt.datetime.now(dt.timezone.utc)
            - dt.timedelta(hours=hours)).isoformat(timespec="seconds").replace(
                "+00:00", "Z")


def _now():
    return dt.datetime.now(dt.timezone.utc).isoformat(
        timespec="seconds").replace("+00:00", "Z")


# -------------------------------------------------------------------- writing
def sample(state, cfg, label="tick"):
    ensure(state)
    payload = {"mem": memory(), "cpu": cpu(), "temps": temps(),
               "disk": disks(), "services": services(),
               "composer": model_health(), "agent": agent_state(state, cfg)}
    state.db.execute(
        "INSERT INTO telemetry (ts,kind,label,payload) VALUES (?,?,?,?)",
        (_now(), "sample", label, json.dumps(payload)))
    state.db.commit()
    return payload


def dump(state, cfg, label, note=""):
    """Everything, because something went wrong and the cost no longer matters."""
    ensure(state)
    payload = {"note": note[:2000],
               "mem": memory(), "cpu": cpu(), "temps": temps(),
               "disk": disks(), "services": services(),
               "composer": model_health(), "agent": agent_state(state, cfg)}
    try:
        payload["journal"] = [
            {"ts": r["ts"], "level": r["level"], "drive": r["drive"],
             "text": r["text"][:400]}
            for r in state.recent_journal(40)]
        payload["cycles"] = [dict(r) for r in state.recent_cycles(10)]
        payload["actions"] = [
            {k: r[k] for k in ("id", "kind", "drive", "status", "created_at")}
            for r in state.recent_actions(12)]
    except Exception as e:
        payload["state_error"] = f"{type(e).__name__}: {e}"[:160]
    payload["composer_log"] = _journal_tail("llama-composer", 25)
    payload["cycle_log"] = _journal_tail("riffle-cycle", 15)
    payload["dash_log"] = _journal_tail("riffle-dash", 15)
    state.db.execute(
        "INSERT INTO telemetry (ts,kind,label,payload) VALUES (?,?,?,?)",
        (_now(), "dump", label[:80], json.dumps(payload)))
    state.db.commit()
    return payload


def _journal_tail(unit, n):
    jc = shutil.which("journalctl")
    if not jc:
        return ["(journalctl unavailable)"]
    try:
        r = subprocess.run([jc, "-u", unit, "-n", str(n), "--no-pager",
                            "-o", "short-iso"],
                           capture_output=True, text=True, timeout=10)
        if r.returncode != 0:
            return [f"(journalctl exit {r.returncode}: {r.stderr.strip()[:80]})"]
        return [l[:300] for l in r.stdout.splitlines()[-n:]]
    except Exception as e:
        return [f"({type(e).__name__}: {e})"[:120]]


def prune(state, hours=24):
    ensure(state)
    cur = state.db.execute("DELETE FROM telemetry WHERE ts < ?", (_ago(hours),))
    state.db.commit()
    return cur.rowcount


def recent(state, limit=400, kind=None):
    ensure(state)
    q = "SELECT id, ts, kind, label, payload FROM telemetry"
    a = []
    if kind:
        q += " WHERE kind=?"
        a.append(kind)
    q += " ORDER BY id DESC LIMIT ?"
    a.append(limit)
    return state.db.execute(q, a).fetchall()


def as_jsonl(state, hours=24):
    """The whole window, oldest first, one JSON object per line."""
    ensure(state)
    rows = state.db.execute(
        "SELECT ts, kind, label, payload FROM telemetry WHERE ts >= ?"
        " ORDER BY id", (_ago(hours),)).fetchall()
    out = []
    for r in rows:
        try:
            body = json.loads(r["payload"])
        except Exception:
            body = {"unparsed": r["payload"][:400]}
        out.append(json.dumps({"ts": r["ts"], "kind": r["kind"],
                               "label": r["label"], **body}, default=str))
    return "\n".join(out) + "\n"


# --------------------------------------------------------------- the hook
def install(state, cfg):
    """Make an error or alarm in the journal trigger a dump.

    Registered rather than called: state.py must not import this module, and
    a hook keeps the dependency pointing one way.
    """
    from agent import state as state_mod

    def on_error(st, level, text):
        try:
            dump(st, cfg, label=level, note=text)
        except Exception:
            pass                      # telemetry must never break the thing it watches

    state_mod.ERROR_HOOK = on_error
