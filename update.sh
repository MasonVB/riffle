#!/bin/bash
# Pull, verify, restart. Refuses to leave the machine on code that does not
# parse OR does not import — a failure here means the agent stops waking,
# silently.
set -euo pipefail
cd /opt/riffle

BEFORE=$(git rev-parse HEAD)
echo "at $BEFORE"

git fetch --quiet origin
UPSTREAM="origin/$(git rev-parse --abbrev-ref HEAD)"
if [ "$(git rev-parse "$UPSTREAM")" = "$BEFORE" ]; then
  echo "already up to date"
  exit 0
fi

# NOT UNDER A RUNNING CYCLE (L9, audit 2026-10-27). The merge rewrote files
# while a cycle could be running, and a module it imports later in main()
# would then be the new code under the old. The cycle lock is taken first
# and held until this script ends, through the gates and any rollback: a
# timer wake meanwhile is skipped, a forced one waits. A cycle already
# running is waited for, up to 15 minutes.
LOCK="${RIFFLE_CYCLE_LOCK:-/var/lib/riffle/cycle.lock}"
if [ -e "$LOCK" ]; then
  exec 9<"$LOCK"
  if ! flock -w "${RIFFLE_LOCK_WAIT:-900}" 9; then
    echo "!! a cycle has been running for over 15 minutes; deploy again when it ends"
    exit 1
  fi
  echo "  holding the cycle lock: no cycle starts until this deploy finishes"
fi
git merge --ff-only "$UPSTREAM"
AFTER=$(git rev-parse HEAD)

if [ "$BEFORE" = "$AFTER" ]; then
  echo "already up to date"
  exit 0
fi
echo "-> $AFTER"
git --no-pager log --oneline "$BEFORE..$AFTER"

# A SECRET SCAN OF WHAT ARRIVED (L16, audit 2026-10-27). repo_setup.py's
# pre-commit hook lives in this checkout, and uploads made on GitHub's site
# never pass through it. The same scan runs here on every changed file, as
# you, not as root (this is code from the repo): it reads config.yaml's keys
# literally and matches the shapes of the rest. Already public by now, so a
# finding is a warning to act on, not a rollback, which would hide nothing.
python3 - "$BEFORE" "$AFTER" <<'PYSCAN' || echo "  (the secret scan could not run)"
import subprocess, sys
sys.path.insert(0, "/opt/riffle")
import repo_setup
names = subprocess.run(["git", "diff", "--name-only", "--diff-filter=AM",
                        sys.argv[1], sys.argv[2]],
                       capture_output=True, text=True).stdout.split()
found = repo_setup.scan(names)
for f, what in found:
    print(f"!! SECRET? {f}: {what}")
if found:
    print("!! If any of these is a real credential it is ALREADY PUBLIC on GitHub:")
    print("!! rotate it first, then remove it from the file. Rolling back would not help.")
PYSCAN

# Two gates, in order of how much they prove.
#
# 1. PARSE, every .py in the repo. Cheap, and the CLI tools in the root are
#    only ever run by hand, so this is all they need.
#
# 2. IMPORT, every module under agent/. This is what systemd actually runs,
#    and ast.parse says nothing about whether it will start: a module-scope
#    NameError, a bad `from agent.x import y`, or a file uploaded to the
#    wrong directory all parse perfectly and all take the dashboard down
#    after the restart below. Uploading through the GitHub web UI makes a
#    misplaced file a routine mistake rather than a strange one, and the old
#    gate could not see it at all.
#
#    Importing these is safe: nothing under agent/ binds a port, starts a
#    thread or opens the database at import time - the server only starts
#    inside dash.main(). The whole set takes about a quarter of a second.
#    The timeout is insurance in case that ever stops being true, because a
#    gate that hangs forever never reaches the restart and is its own outage.
if ! timeout 120 python3 - <<'PY'
import ast
import glob
import importlib
import os
import sys
import traceback

bad = 0
for f in sorted(glob.glob('*.py') + glob.glob('agent/*.py')):
    try:
        ast.parse(open(f).read())
    except SyntaxError as e:
        print(f"  SYNTAX ERROR {f}:{e.lineno}: {e.msg}")
        bad += 1
if bad:
    sys.exit(1)

sys.path.insert(0, os.getcwd())
for f in sorted(glob.glob('agent/*.py')):
    mod = 'agent.' + os.path.basename(f)[:-3]
    if mod.endswith('.__init__'):
        mod = 'agent'
    try:
        importlib.import_module(mod)
    except BaseException as e:
        # The last frame names the actual problem; everything above it is
        # import machinery you would be scrolling past at 3am.
        tb = traceback.extract_tb(sys.exc_info()[2])
        where = f" at {tb[-1].filename}:{tb[-1].lineno}" if tb else ""
        print(f"  IMPORT ERROR {mod}: {type(e).__name__}: {e}{where}")
        bad += 1
sys.exit(1 if bad else 0)
PY
then
  echo "!! rolling back to $BEFORE"
  git reset --hard "$BEFORE"
  exit 1
fi

# --- gate 3: does the dashboard actually render ------------------------
#
# Parsing and importing both passed on a change that made every page 500:
# a NameError inside do_GET, because hashlib was imported inside a
# function three hundred lines away and a guard that asked 'is hashlib
# mentioned in this file' found it there and skipped the real import.
#
# An import gate proves the module loads. It says nothing about whether
# the thing the module exists to do still works. This builds each page
# the way the handler does, which is the cheapest test that would have
# caught it.
if ! python3 - <<'PYRENDER'
import io
import sys
import tempfile
sys.path.insert(0, ".")
bad = 0
try:
    from agent.state import State
    from agent import dash

    class Fake(dash.Handler):
        # Exercises do_GET itself, not the page constants. The first
        # version of this gate built pages.PAGE directly and passed
        # cleanly on a NameError that lived in do_GET, which is the whole
        # failure it was written for. A gate that does not run the code
        # path the user hits is a gate that agrees with you.
        command = "GET"
        def __init__(self, path):
            self.path = path
            self.wfile = io.BytesIO()
            self.headers = {}
            self.code = None
        def send_response(self, c):
            self.code = c
        def send_header(self, k, v):
            self.headers[k] = v
        def end_headers(self):
            pass

    dash.Handler.cfg = {"model_id": "gate", "caps": {}, "dash": {}}
    dash.Handler.state = State(tempfile.mktemp(suffix=".sqlite"))

    # A STUB WORKER, so /api/messages can be exercised too.
    #
    # The chat page polls /api/messages every second and this gate never
    # called it — it rendered the three HTML pages and stopped. snapshot()
    # is where the alarm query, the waiting-card list, the queue count and
    # the orphan close all live, and a NameError in any of them would ship
    # cleanly past every gate and then break the page that is open all day.
    #
    # It needs self.worker, which the fake handler has no reason to own, so
    # the gate supplies the two attributes snapshot() actually reads.
    class StubWorker:
        busy = False
        busy_since = None

        def depth(self):
            return 0

    dash.Handler.worker = StubWorker()

    # Rows to walk, not an empty table: a snapshot of nothing exercises
    # almost none of the function.
    _st = dash.Handler.state
    _st.say("user", "a question from the gate")
    _mid = _st.say("assistant", "a partial reply", {"kind": "chat"})
    _st.say("proposal", "a rationale", {"kind": "comment", "action_id": 1,
                                        "status": "queued"})
    _st.log("a journal line the alarm query will walk", level="error")

    for path in ("/", "/settings", "/history", "/api/messages?after=0"):
        h = Fake(path)
        try:
            h.do_GET()
        except BaseException as e:
            print(f"  {path} RAISED {type(e).__name__}: {e}")
            bad += 1
            continue
        body = h.wfile.getvalue().decode("utf-8", "replace")
        if h.code != 200:
            print(f"  {path} returned {h.code}")
            bad += 1
        elif path.startswith("/api/"):
            # JSON, not a page: check it parses and carries what the chat
            # client reads, rather than applying the HTML size floor.
            import json as _json
            try:
                d = _json.loads(body)
            except ValueError as e:
                print(f"  {path} did not return JSON: {e}")
                bad += 1
            else:
                for key in ("messages", "queued", "waiting_ids"):
                    if key not in d:
                        print(f"  {path} has no {key!r}; the chat page reads it")
                        bad += 1
                if isinstance(d.get("messages"), list) and not d["messages"]:
                    print(f"  {path} returned no messages for a seeded store")
                    bad += 1
        elif len(body) < 500:
            print(f"  {path} returned only {len(body)} bytes")
            bad += 1
        elif "__BUILD__" in body or "%MODEL%" in body:
            print(f"  {path} left a placeholder unsubstituted")
            bad += 1
except BaseException as e:
    print(f"  RENDER GATE COULD NOT RUN: {type(e).__name__}: {e}")
    bad += 1
sys.exit(1 if bad else 0)
PYRENDER
then
  echo "!! the dashboard does not serve; rolling back to $BEFORE"
  git reset --hard "$BEFORE"
  exit 1
fi

# --- gate 4: does the whole prompt fit the context window ----------------
#
# The prompt has now overflowed three times for three different reasons:
# unbounded blocks, too small a generation allowance, and a system prompt
# that was never counted. Each fix was aimed at part of the prompt because
# nothing measured all of it.
#
# THIS GATE COULD NOT FAIL UNTIL 2026-10-23. It sat inside an
# `except BaseException`, which caught its own sys.exit(1), and it ended on
# sys.exit(0). With max_prompt_chars at 70000 it printed "TOO TIGHT ... -1612
# fit", then "COULD NOT RUN: SystemExit: 1", and deployed. Now every path
# that is not a clean pass exits 1, including "could not run".
#
# WHAT IT CHECKS is the worst case the cycle's own arithmetic allows, not
# one sample prompt. A prompt assembled from fixture data proves that one
# prompt fits; the bound proves every prompt does. The bound is:
#
#   system + data blocks + volatile lines  <= max_prompt_chars - budget/10
#   front page                             <= max(1800, budget - data - 400)
#
# The second line is not covered by the ceiling: when the data blocks are
# small, the front page takes up to `budget` on its own. Both cases are
# checked. Because this mirrors cycle.py rather than calling it, the gate
# also refuses if those expressions are no longer in cycle.py's code.
#
# The context size comes from the composer unit (installed and repo copy,
# the smaller one), not config.yaml, which has never carried it. The system
# prompt is measured with the continuity note at cortex.CONTINUITY_MAX.
if ! python3 - <<'PYFIT'
import io
import math
import os
import re
import sys
import tokenize
sys.path.insert(0, ".")

CHARS_PER_TOKEN = 3.25   # measured 3.52 (73,864 chars = 20,964 tokens); kept low
TEMPLATE_TOKENS = 64     # chat-template wrapping around system and user
# The end of the prompt, after </board> (cycle._TAIL_HEADS and the clock,
# drive and caps lines), at its largest: the situation check ~2,930, inbox
# guidance up to ~690, the two hints ~300 each, the clock lines ~200.
TAIL_WORST = 4500
# The protected blocks at their largest together (H6): what can stop an
# action ~1,760, the API fields ~650, the inbox up to ~4,800, the next step
# ~350, the reference notice ~600, an operator instruction and the waiting
# list. They are never cut, so the room must hold them all.
PROTECTED_WORST = 9500
# The cycle's budget arithmetic, as code with comments, strings and
# whitespace removed. If any is gone, this gate's model of the prompt is out
# of date and its answer means nothing. Since H6 (2026-10-30) everything,
# the front page included, is fitted inside one room, so the prompt sent is
# at most the ceiling unless the protected blocks alone overflow it.
MIRRORED = ("_room=_ceiling-_sys_chars-_tail_chars-_WRAP_CHARS",
            "if_room<8000:",
            "parts=_fit(parts,_room,log,")
def code_only(path):
    skip = (tokenize.COMMENT, tokenize.STRING, tokenize.NL, tokenize.NEWLINE,
            tokenize.INDENT, tokenize.DEDENT)
    toks = tokenize.generate_tokens(io.StringIO(open(path).read()).readline)
    return "".join(t.string for t in toks if t.type not in skip)
def unit_ctx(path):
    """Per-sequence context from a llama-server unit, or None."""
    try:
        lines = open(path).read().splitlines()
    except OSError:
        return None
    text = " ".join(l for l in lines if not l.lstrip().startswith("#"))
    m = re.search(r"(?:--ctx-size|(?<!\S)-c)[\s=]+(\d+)", text)
    if not m:
        return None
    p = re.search(r"(?:--parallel|(?<!\S)-np)[\s=]+(\d+)", text)
    return int(m.group(1)) // max(1, int(p.group(1)) if p else 1)
try:
    if not os.path.exists("config.yaml"):
        print("  no config.yaml here, and the cycle cannot run without one")
        sys.exit(1)
    import yaml
    from agent import cortex
    cfg = yaml.safe_load(open("config.yaml"))
    code = code_only("agent/cycle.py")
    gone = [m for m in MIRRORED if m not in code]
    if gone:
        for m in gone:
            print(f"  cycle.py no longer contains {m!r}")
        print("  the prompt budget changed; update gate 4 to match it")
        sys.exit(1)
    ctxs = {p: unit_ctx(p) for p in
            ("/etc/systemd/system/llama-composer.service",
             "systemd/llama-composer.service")}
    found = [v for v in ctxs.values() if v]
    if not found:
        print("  no --ctx-size in either llama-composer.service")
        sys.exit(1)
    ctx = min(found)
    comp = (cfg.get("llm") or {}).get("composer") or {}
    want = int(comp.get("max_tokens", 1600))           # cortex's default
    ceiling = int((cfg.get("cycle") or {}).get("max_prompt_chars", 50000))
    # With the continuity note at its cap: riffle writes it daily, and the
    # day it writes its longest is the day the budget has to hold.
    sysc = len(cortex.stable_prefix(cfg, cortex.render_continuity(
        "x" * cortex.CONTINUITY_MAX, "2026-01-01T00:00:00Z")))
    from agent.cycle import _WRAP_CHARS
    data_room = ceiling - sysc - TAIL_WORST - _WRAP_CHARS
    if data_room < max(8000, PROTECTED_WORST):
        print(f"  the system prompt is {sysc} chars of a {ceiling} ceiling, "
              f"leaving {data_room} for the data; the protected blocks alone "
              f"can need {PROTECTED_WORST}")
        sys.exit(1)
    worst = ceiling
    tokens = math.ceil(worst / CHARS_PER_TOKEN) + TEMPLATE_TOKENS
    left = ctx - tokens
    print(f"  worst prompt {worst} chars ~ {tokens} tokens of {ctx}; {left} "
          f"left, max_tokens {want} (system {sysc} with continuity at its "
          f"cap; data room {data_room}, protected worst {PROTECTED_WORST})")
    if left < want:
        print("  TOO TIGHT: lower max_prompt_chars or max_tokens")
        sys.exit(1)
except SystemExit:
    raise
except BaseException as e:
    print(f"  FIT GATE COULD NOT RUN: {type(e).__name__}: {e}")
    sys.exit(1)
PYFIT
then
  echo "!! the prompt does not leave room to answer; rolling back to $BEFORE"
  git reset --hard "$BEFORE"
  exit 1
fi

# --- gate 5: can llama.cpp actually compile the grammar ------------------
#
# proposal_schema.json is converted to GBNF by llama-server. The schema
# being valid JSON says nothing about whether that conversion succeeds.
#
# On 2026-10-10 a minLength/maxLength pair was added to one string field.
# Valid JSON, valid JSON Schema, passed every gate — and llama.cpp
# answered "Failed to initialize samplers: failed to parse grammar" on
# every request for nine hours, because it expands a bounded repetition
# and a 2000-character bound produces a rule it cannot parse.
#
# There is no converter here to test against, so this rejects the
# constructs known to break it rather than pretending to compile. A
# denylist is weaker than a real conversion, but it would have caught
# this one and costs nothing.
if ! python3 - <<'PYGBNF'
import json
import sys
BAD = {
    "minLength": "expands to a bounded repetition llama.cpp may not parse",
    "maxLength": "expands to a bounded repetition llama.cpp may not parse",
    "patternProperties": "unsupported by the GBNF converter",
    "allOf": "unsupported by the GBNF converter",
    "not": "unsupported by the GBNF converter",
    "if": "unsupported by the GBNF converter",
}
bad = []


def walk(node, path):
    if isinstance(node, dict):
        for key, why in BAD.items():
            if key in node:
                bad.append(f"{path}/{key}: {why}")
        for k, v in node.items():
            walk(v, f"{path}/{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            walk(v, f"{path}[{i}]")


try:
    schema = json.load(open("proposal_schema.json"))
except (OSError, ValueError) as e:
    print(f"  proposal_schema.json will not load: {e}")
    sys.exit(1)
walk(schema, "")

# THE DENYLIST ABOVE ONLY KNOWS WHAT HAS ALREADY BROKEN.
#
# It was written after minLength/maxLength took the composer down for nine
# hours, and it lists the five constructs we have since thought of. The next
# unsupported keyword is not on it, by definition.
#
# So: actually convert the schema, with llama.cpp's own converter if it is
# on this machine. That answers the real question — does THIS build's GBNF
# converter accept THIS schema — rather than our memory of past failures.
# The denylist stays as the fast path for a machine without llama.cpp.
import glob as _glob
import importlib.util as _ilu

_conv = None
for _c in ("/opt/llama.cpp/examples/json_schema_to_grammar.py",
           "/opt/llama.cpp/json_schema_to_grammar.py",
           "/opt/llama.cpp/scripts/json_schema_to_grammar.py"):
    if _glob.glob(_c):
        _conv = _c
        break
if _conv:
    # COULD-NOT-RUN IS NOT A FAILURE.
    #
    # The first version of this called SchemaConverter positionally. In this
    # build its __init__ is keyword-only, so it raised TypeError — and I
    # counted that as "the schema is bad" and rolled back a perfectly good
    # deploy. A gate that reports its own breakage as a finding is worse
    # than no gate: it blocks work and points at the wrong file.
    #
    # So: construction problems and signature mismatches fall back to the
    # denylist and say so. ONLY an error raised while actually converting
    # the schema counts against the schema.
    _c2 = None
    try:
        _spec = _ilu.spec_from_file_location("j2g", _conv)
        _m = _ilu.module_from_spec(_spec)
        _spec.loader.exec_module(_m)
        _fn = getattr(_m, "SchemaConverter", None)
        if _fn:
            import inspect as _insp
            _params = _insp.signature(_fn).parameters
            _kw = {}
            for _name, _default in (("prop_order", {}), ("allow_fetch", False),
                                    ("dotall", False), ("raw_pattern", False)):
                if _name in _params:
                    _kw[_name] = _default
            _c2 = _fn(**_kw)
    except BaseException as e:
        print(f"  (could not load llama.cpp's converter: {type(e).__name__}: "
              f"{e}; denylist only)")
        _c2 = None
    if _c2 is not None:
        try:
            _c2.visit(schema, "")
            _c2.format_grammar()
            print("  schema compiles with llama.cpp's own converter")
        except BaseException as e:
            bad.append(f"/: llama.cpp's converter refused this schema: "
                       f"{type(e).__name__}: {e}")
else:
    print("  (llama.cpp converter not found; denylist only)")
# THE SERVER'S OWN CONVERTER (L21, audit 2026-10-27). The Python converter
# above is a stand-in: llama-server compiles schemas with its C++ one. So the
# running composer is asked to compile this schema exactly as the cycle sends
# it (cortex.complete: response_format json_schema, /v1/chat/completions),
# for a one-token reply. A 400 means the server refused the schema. No answer
# (server down, or busy with a chat turn) leaves the result above standing.
# The deploy holds the cycle lock, so no cycle is using the composer now.
try:
    import urllib.request, urllib.error, yaml
    _url = ((yaml.safe_load(open("config.yaml")).get("llm") or {})
            .get("composer") or {}).get("url", "http://127.0.0.1:8080")
    _body = json.dumps({
        "messages": [{"role": "user", "content": "Reply with any valid object."}],
        "max_tokens": 1, "temperature": 0,
        "response_format": {"type": "json_schema", "json_schema": {
            "name": "proposal", "strict": True, "schema": schema}}}).encode()
    _req = urllib.request.Request(_url.rstrip("/") + "/v1/chat/completions",
                                  data=_body, method="POST",
                                  headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(_req, timeout=30).read()
        print("  the running composer accepted the schema (its own converter)")
    except urllib.error.HTTPError as e:
        _msg = e.read().decode("utf-8", "replace")[:300]
        if e.code == 400:
            bad.append(f"/: the running composer refused this schema: {_msg}")
        else:
            print(f"  (the composer answered {e.code}; its converter was not checked)")
except (OSError, ValueError) as e:
    print(f"  (the composer did not answer: {type(e).__name__}; its converter "
          f"was not checked, the result above stands)")
for b in bad:
    print(f"  GRAMMAR RISK {b}")
sys.exit(1 if bad else 0)
PYGBNF
then
  echo "!! the schema uses constructs llama.cpp cannot compile;"
  echo "   rolling back to $BEFORE"
  git reset --hard "$BEFORE"
  exit 1
fi

# --- gate 6: do the internal waits fit inside the unit's timeout ---------
#
# The cycle waits on triage, on two locks and on the composer. systemd
# kills it at TimeoutStartSec. When the sum of the waits exceeds the
# timeout, systemd wins and the cycle dies mid-work with no traceback: a
# silent failure that for weeks looked like the agent choosing to stop.
#
# This compares the two numbers and refuses a deploy where the arithmetic
# does not work.
if ! python3 - <<'PYWAIT'
# AN EXPLICIT WORST CASE (L21, audit 2026-10-27). This summed the five
# largest `timeout=` numbers in five files: one wait written twice counted
# twice, the forced run's 2,400 s lock wait (not written as timeout=) was
# missed, and every wait repeated per page, per call or per bucket counted
# once. It certified 9,000 s for a path that can reach about 16,000.
#
# Now every wait one cycle can sit through in sequence is listed with its
# count, and each is MIRRORED from the line that sets it, as gate 4 does: if
# a line changes, this gate fails until it is updated, so the sum cannot go
# stale. Every wait has its own timeout, so the unit's limit is a backstop
# for code with none; it must sit above this sum or it can kill a cycle that
# is only slow.
import re
import sys
import yaml
bad = []
try:
    src = {p: open(p).read() for p in ("agent/cycle.py", "agent/cortex.py",
                                         "agent/memory.py", "agent/client.py",
                                         "agent/inbox.py")}
    MIRRORED = (
        ("agent/cycle.py", "if _waited >= 2400:"),
        ("agent/cycle.py", "lock.acquire(blocking=True, timeout=900)"),
        ("agent/cycle.py", "lock.acquire(blocking=True, timeout=1200)"),
        ("agent/cortex.py", "def complete(llm_cfg, system, user, timeout=1800, schema=None):"),
        ("agent/memory.py", "timeout=900)"),
        ("agent/client.py", 'def _req(url, method="GET", body=None, token=None, timeout=45):'),
        ("agent/cycle.py", "def do_witness(state, reader, log, max_pages=8):"),
        ("agent/inbox.py", "def drain(writer, first_stats, log, buckets=LIVE_BUCKETS, max_pages=6, state=None):"),
        ("agent/inbox.py", "def resume(state, writer, log, buckets=LIVE_BUCKETS, max_pages=6):"),
        ("agent/cycle.py", "capture_output=True, text=True, timeout=200)"),
    )
    gone = [f"{p}: {line}" for p, line in MIRRORED if line not in src[p]]
    if gone:
        for g in gone:
            bad.append(f"no longer in the code: {g}")
        bad.append("a wait changed; update gate 6 to match it")
    else:
        cfg = yaml.safe_load(open("config.yaml"))
        change_pages = int(((cfg.get("changes") or {}).get("max_pages_per_cycle", 4)))
        buckets = 4                                         # inbox.LIVE_BUCKETS
        http = 10 + 8 + change_pages + 6 * buckets + 6 * buckets
        waits = [
            ("a forced run waiting for the cycle lock", 2400),
            ("reflection's model call", 900),
            ("the memory pass: the composer lock", 900),
            ("the memory pass: two composer calls", 2 * 1800),
            ("the composer lock before the main call", 1200),
            ("the main composer call", 1800),
            ("the number check's same-cycle rewrite", 1800),
            ("the number check itself, twice", 2 * 120),
            ("the action's own helper (a build, the longest)", 200),
            (f"{http} registry requests at 45 s", http * 45),
        ]
        worst = sum(w for _, w in waits)
        unit = open("systemd/riffle-cycle.service").read()
        m = re.search(r"^TimeoutStartSec=([0-9]+)", unit, re.M)
        if not m:
            bad.append("no TimeoutStartSec in systemd/riffle-cycle.service")
        else:
            limit = int(m.group(1))
            print(f"  systemd/riffle-cycle.service allows {limit}s; the worst "
                  f"path one cycle can take is {worst}s")
            if worst > limit:
                for name, w in waits:
                    print(f"    {w:6}s  {name}")
                bad.append(f"systemd kills the cycle at {limit}s and its waits "
                           f"can reach {worst}s")
except BaseException as e:
    bad.append(f"the timeout check could not run: {type(e).__name__}: {e}")
for b in bad:
    print(f"  TIMEOUT: {b}")
sys.exit(1 if bad else 0)
PYWAIT
then
  echo "!! the cycle can wait longer than systemd allows; rolling back"
  git reset --hard "$BEFORE"
  exit 1
fi

# --- gate 7: no unconditional self-recursion ------------------------------
#
# A patch meant to collapse a duplicated dispatch matched inside the new
# dispatcher instead of at the call site, so apply_local() became a function
# whose entire body was `return apply_local(...)`. It parsed, it imported,
# every page rendered, the prompt fit, the grammar compiled, the timeouts
# added up. It raised RecursionError the first time anyone approved a queued
# action.
#
# A `return <self>(...)` that runs before anything that could stop it is
# never intentional here, and that is what this finds in the AST. Recursion
# with a base case passes.
if ! python3 - <<'PYREC'
import ast
import sys

bad = []
for path in ("agent/cycle.py", "agent/dash.py", "agent/project.py",
             "agent/state.py", "agent/memory.py", "agent/library.py",
             "numcheck.py"):
    try:
        tree = ast.parse(open(path).read())
    except (OSError, SyntaxError):
        continue
    for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
        # UNCONDITIONAL SELF-CALL AHEAD OF THE BODY.
        #
        # An earlier rule here caught only a function whose ONLY call was
        # itself (it is gone; see the note further down). A self-call
        # inserted ahead of a real body — `def f(x): return f(x)` followed
        # by the genuine code — passed it, and is just as infinitely
        # recursive. Catch that shape directly: a bare `return <self>(...)`
        # with nothing guarding it.
        #
        # PAST THE DOCSTRING, AND PAST ANYTHING THAT CANNOT END THE CALL.
        # This stopped at the first statement that was not a return, and
        # apply_local's first statement is its docstring, so a self-call
        # where a patch would put it — after the docstring — was never
        # examined. The same held after an import or an assignment. A
        # docstring, assignment, import, global or pass cannot return or
        # branch, so a bare `return <self>(...)` after them is still
        # unconditional. Anything that can branch, raise or assert stops
        # the search: that may be a base case.
        _INERT = (ast.Expr, ast.Assign, ast.AugAssign, ast.AnnAssign,
                  ast.Import, ast.ImportFrom, ast.Global, ast.Nonlocal,
                  ast.Pass)
        for _n in fn.body:
            if isinstance(_n, ast.Return):
                _v = _n.value
                if (isinstance(_v, ast.Call) and isinstance(_v.func, ast.Name)
                        and _v.func.id == fn.name):
                    bad.append(f"{path}:{_n.lineno} {fn.name}() returns a "
                               f"call to itself before anything that could "
                               f"stop it \u2014 unconditional infinite "
                               f"recursion")
                break
            if not isinstance(_n, _INERT):
                break           # this may branch or raise; stop looking

        # The older rule that stood here, "calls only itself", is gone (R4.4,
        # audit 4). It refused any helper whose only non-builtin call was to
        # itself, including real recursion with a base case. The check above
        # (a self-call reached before anything that could stop it) covers the
        # bug the old rule was written for.
for b in bad:
    print(f"  SELF-RECURSION {b}")
sys.exit(1 if bad else 0)
PYREC
then
  echo "!! a function recurses unconditionally; rolling back to $BEFORE"
  git reset --hard "$BEFORE"
  exit 1
fi

# --- gate 8: every protected prompt header is a header something emits ----
#
# _NEVER_TRIM protects prompt blocks from the trimmer by matching the first
# 400 characters of each block against a list of header strings. P9 reworded
# "EVERYTHING THAT CAN STOP AN ACTION" to "WHAT CAN STOP AN ACTION" and the
# list was not touched, so that block silently lost its protection and
# started being cut again — the exact failure the list exists to prevent,
# and invisible because trimming is supposed to happen.
#
# A protected header that no code emits protects nothing.
if ! python3 - <<'PYTRIM'
import ast
import glob
import sys

# _OWN_HEADS too: a block listed as riffle's own that nothing emits is a
# dead entry, and one whose header was reworded silently falls into <board>.
bad = []
try:
    sys.path.insert(0, ".")
    from agent.cycle import _NEVER_TRIM, _OWN_HEADS

    lists = {"_NEVER_TRIM": _NEVER_TRIM, "_OWN_HEADS": _OWN_HEADS}
    found = {(n, k): False for n, ks in lists.items() for k in ks}
    # The tuples' own entries are not uses. Skip exactly those nodes; the old
    # test skipped any literal equal to a key after strip(), which would also
    # skip real uses like "caps remaining today: ".
    own_nodes = set()
    # Tables that NAME headers without emitting them (the prompt's ordering,
    # budgets and end-of-prompt list, H6/M5) are skipped the same way: their
    # entries start with the headers, so they satisfied this gate whether or
    # not any real block did (found when L21 was tested, 2026-10-30).
    TABLES = {"_TAIL_HEADS", "_OWN_ORDER", "_BOARD_ORDER", "_BUDGETS"}
    ctree = ast.parse(open("agent/cycle.py").read())
    for node in ctree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id in set(lists) | TABLES):
            own_nodes |= {id(c) for c in ast.walk(node.value)}
    for path in glob.glob("agent/*.py"):
        try:
            tree = ctree if path == "agent/cycle.py" else ast.parse(open(path).read())
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if (not isinstance(node, ast.Constant) or not isinstance(node.value, str)
                    or id(node) in own_nodes):
                continue
            lit = node.value
            for (n, k) in found:
                # AT THE START, as the cycle matches it (_is_rule and _is_own
                # use lstrip().startswith). "Anywhere in the first 80
                # characters" let a literal that merely mentions a header
                # satisfy this (L21, audit 2026-10-27).
                if lit.lstrip().startswith(k):
                    found[(n, k)] = True
    for (n, k), ok in found.items():
        if not ok:
            bad.append(f"{k!r} is in {n} and no string literal starts with "
                       f"it. Either the header was renamed and the list was "
                       f"not, or the entry is dead.")
except BaseException as e:
    bad.append(f"the protected-header check could not run: "
               f"{type(e).__name__}: {e}")
for b in bad:
    print(f"  ORPHAN PROTECTED HEADER {b}")
sys.exit(1 if bad else 0)
PYTRIM
then
  echo "!! a protected prompt header matches nothing; rolling back"
  git reset --hard "$BEFORE"
  exit 1
fi

# --- gate 9: every config key is read by something -------------------------
#
# config.example.yaml declared wakes_per_day and pulse_shortcut, and nothing
# anywhere read either. The second is the worse kind: it described a feature
# that does not exist, so setting it to false would have left someone
# believing they had turned the composer skip off. A setting that does
# nothing is a lie the file tells every reader.
#
# A key counts as read if its name appears in any .py file.
if ! python3 - <<'PYCFG'
import glob
import sys

import yaml

try:
    cfg = yaml.safe_load(open("config.example.yaml"))
except Exception as e:
    # A gate that cannot read its input has checked nothing: fail, do not
    # pass (L21, audit 2026-10-27).
    print(f"  could not read config.example.yaml: {e}")
    sys.exit(1)
code = ""
for path in glob.glob("*.py") + glob.glob("agent/*.py") + glob.glob("bin/*"):
    try:
        code += open(path).read()
    except (OSError, UnicodeDecodeError):
        pass


def walk(d, prefix=""):
    out = []
    if isinstance(d, dict):
        for k, v in d.items():
            out.append(k)
            out.extend(walk(v, prefix + k + "."))
    return out


# Keys that are structure rather than settings, or read via a loop over the
# whole section rather than by name.
SKIP = {"cycle", "memory", "llm", "library", "dash", "registry", "projects",
        "autonomy", "caps", "drives", "composer", "triage", "desk", "notify",
        "build", "reader", "signer"}
missing = []
for key in set(walk(cfg)):
    if key in SKIP or not isinstance(key, str):
        continue
    if f'"{key}"' not in code and f"'{key}'" not in code:
        missing.append(key)
for k in sorted(missing):
    print(f"  DEAD CONFIG KEY {k!r}: declared in config.example.yaml, read by nothing")
sys.exit(1 if missing else 0)
PYCFG
then
  echo "!! a config key is read by nothing; rolling back"
  git reset --hard "$BEFORE"
  exit 1
fi

# --- gate 10: no .get() on something that returns a sqlite3.Row -----------
#
# `(project.active(state) or {}).get("id")` reads as carefully guarded and
# is not: active() returns a Row when a project exists, and Row has no .get.
# The expression worked only when the answer was None and raised
# AttributeError whenever there was something to read — so every cycle that
# proposed a post died, and the `or {}` is what stopped anyone looking twice.
#
# A None guard that does not guard the TYPE is worse than no guard.
if ! python3 - <<'PYROW'
# GATE 10 WAS A LINE REGEX, AND MISSED TWO OF THREE SHAPES.
#
# It matched `<fn>(...)....get(` on ONE line. Tested by the auditor:
#
#   (project.active(state) or {}).get("id")   caught
#   project.active(state).get("id")           missed
#   p = project.active(state); p.get("id")    missed
#
# The last is the commonest way anyone would write it. An AST pass tracks
# names assigned from a Row-returning call and flags .get on them anywhere
# in the same function.
import ast
import glob
import sys

ROW_FNS = {"active", "fetchone", "read_row", "action", "last_head",
           "note_row", "read_row"}
bad = []
for path in glob.glob("agent/*.py") + glob.glob("*.py"):
    try:
        tree = ast.parse(open(path).read())
    except (OSError, SyntaxError):
        continue

    def row_call(node):
        """True if this expression is a call to something returning a Row."""
        if not isinstance(node, ast.Call):
            return False
        f = node.func
        name = f.attr if isinstance(f, ast.Attribute) else (
            f.id if isinstance(f, ast.Name) else None)
        return name in ROW_FNS

    for fn in [n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        rows = set()
        for node in ast.walk(fn):
            # p = <row call>   /   p = <row call> or {}
            if isinstance(node, ast.Assign):
                v = node.value
                if isinstance(v, ast.BoolOp):
                    v = v.values[0] if v.values else v
                if row_call(v):
                    for t in node.targets:
                        if isinstance(t, ast.Name):
                            rows.add(t.id)
        for node in ast.walk(fn):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "get"):
                continue
            tgt = node.func.value
            # <name>.get(...) where name came from a Row call
            if isinstance(tgt, ast.Name) and tgt.id in rows:
                bad.append(f"{path}:{node.lineno}: {tgt.id}.get() — "
                           f"{tgt.id} holds a sqlite3.Row, which has no .get")
            # <row call>.get(...)  and  (<row call> or {}).get(...)
            inner = tgt
            if isinstance(inner, ast.BoolOp) and inner.values:
                inner = inner.values[0]
            if row_call(inner):
                bad.append(f"{path}:{node.lineno}: .get() straight off a "
                           f"Row-returning call")
for b in sorted(set(bad)):
    print(f"  ROW .get {b}")
sys.exit(1 if bad else 0)
PYROW
then
  echo "!! .get() called on a sqlite3.Row; rolling back"
  git reset --hard "$BEFORE"
  exit 1
fi

# --- gate 11: no stray copies of agent modules ----------------------------
#
# Four cycle.py files have been uploaded to the repo root (f53c416, 8cb25db,
# bccce71, a78bd82). Nothing ran them, so every other gate passed, but each
# was a stale copy waiting to be edited instead of agent/cycle.py. That is
# how the noop gate was lost in October, and the likeliest way the changes
# reported done and later found missing went missing. Gate 9 also read the
# last one, so a config key only it used would have counted as live.
#
# The GitHub uploader drops a file wherever the page you are on is, so this
# is a routine mistake rather than a strange one. Two rules:
#   - a .py at the root must be one of the known hand-run tools;
#   - no .py outside agent/ may share a name with a module in agent/.
#
# ROOT_TOOLS is a hand-maintained list. Adding a new root tool means adding
# it here, which is the point: it should be a decision, not an accident.
if ! python3 - <<'PYSTRAY'
import os
import subprocess
import sys

# TRACKED files, not the working tree: the problem is what is in the repo,
# and an untracked scratch file on the box should not block every deploy.
tracked = [p for p in subprocess.run(
    ["git", "ls-files", "-z"], capture_output=True, check=True
).stdout.decode().split("\0") if p.endswith(".py")]
ROOT_TOOLS = {"ed25519_pure.py", "join.py", "keyutil.py", "numcheck.py",
              "payout_wallet.py", "repo_setup.py", "witness.py"}
agent = {os.path.basename(p) for p in tracked
         if os.path.dirname(p) == "agent"}
bad = []
for p in sorted(tracked):
    if "/" not in p and p not in ROOT_TOOLS:
        bad.append(f"{p} at the repo root is not a known tool")
for p in sorted(tracked):
    if os.path.dirname(p) != "agent" and os.path.basename(p) in agent:
        bad.append(f"{p} shares a name with agent/{os.path.basename(p)}")
for b in sorted(set(bad)):
    print(f"  STRAY {b}")
if bad:
    print("  delete it on GitHub, or add it to ROOT_TOOLS if it is a new tool")
sys.exit(1 if bad else 0)
PYSTRAY
then
  echo "!! a stray .py is in the tree; rolling back to $BEFORE"
  git reset --hard "$BEFORE"
  exit 1
fi

# --- gate 12: every enum the gate enforces is an enum in the grammar ------
#
# The grammar decides what the model can write; drives.SCHEMA decides what
# the gate accepts. Where the gate checks a field against a fixed set and the
# grammar leaves it a free string, the model can write a value the gate will
# refuse: a whole cycle spent producing a refusal. G7 and N7 were this, fixed
# one field at a time. attestation.cls was the next one.
#
# The schema enums are copied into proposal_schema.json by hand; nothing
# generates them. So this compares the copies: for every _enum(...) call in
# drives.SCHEMA it evaluates the allowed values and requires the same set as
# the schema's enum for that action and field. It reads the gate's tuples
# rather than a list kept here, so it cannot itself go stale.
if ! python3 - <<'PYENUM'
import ast
import json
import sys
sys.path.insert(0, ".")

from agent import drives

schema = json.load(open("proposal_schema.json"))
branch = {}
for b in schema.get("oneOf", []):
    kind = ((b.get("properties") or {}).get("action") or {}).get("const")
    if kind:
        branch[kind] = ((b["properties"].get("payload") or {})
                        .get("properties") or {})

tree = ast.parse(open("agent/drives.py").read())
table = None
for node in ast.walk(tree):
    if (isinstance(node, (ast.Assign, ast.AnnAssign))
            and any(isinstance(t, ast.Name) and t.id == "SCHEMA"
                    for t in (node.targets if isinstance(node, ast.Assign)
                              else [node.target]))
            and isinstance(node.value, ast.Dict)):
        table = node.value
if table is None:
    print("  no SCHEMA dict in agent/drives.py; this gate cannot see the gate")
    sys.exit(1)

bad, seen = [], 0
ns = vars(drives)
for k, v in zip(table.keys, table.values):
    if not (isinstance(k, ast.Constant) and isinstance(v, ast.Tuple)):
        continue
    kind = k.value
    for call in ast.walk(v):
        if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
                and call.func.id == "_enum" and len(call.args) == 2):
            continue
        # the field: p["x"] or p.get("x") or p.get("x") or "default"
        a = call.args[0]
        if isinstance(a, ast.BoolOp):
            a = a.values[0]
        field = None
        if isinstance(a, ast.Subscript) and isinstance(a.slice, ast.Constant):
            field = a.slice.value
        elif (isinstance(a, ast.Call) and isinstance(a.func, ast.Attribute)
              and a.func.attr == "get" and a.args
              and isinstance(a.args[0], ast.Constant)):
            field = a.args[0].value
        if field is None:
            bad.append(f"{kind}: an _enum this gate cannot read the field of")
            continue
        try:
            allowed = set(eval(compile(ast.Expression(call.args[1]),
                                       "drives.py", "eval"), ns))
        except Exception as e:
            bad.append(f"{kind}.{field}: could not evaluate the gate's "
                       f"values ({type(e).__name__}: {e})")
            continue
        seen += 1
        prop = (branch.get(kind) or {}).get(field)
        if prop is None:
            bad.append(f"{kind}.{field}: the gate checks it; the schema has "
                       f"no such field")
        elif "enum" not in prop:
            bad.append(f"{kind}.{field}: an enum in the gate "
                       f"{sorted(allowed)}, a free string in the grammar")
        elif set(prop["enum"]) != allowed:
            only_g = sorted(allowed - set(prop["enum"]))
            only_s = sorted(set(prop["enum"]) - allowed)
            bad.append(f"{kind}.{field}: gate-only {only_g}, "
                       f"schema-only {only_s}")
for b in bad:
    print(f"  ENUM {b}")
if not seen and not bad:
    print("  found no _enum calls in drives.SCHEMA; the gate is reading the "
          "wrong thing")
    sys.exit(1)
sys.exit(1 if bad else 0)
PYENUM
then
  echo "!! the grammar and the gate disagree on an enum; rolling back to $BEFORE"
  git reset --hard "$BEFORE"
  exit 1
fi

# --- gate 13: every local outcome is classified ---------------------------
#
# An approved local action's status (executed or failed) comes from the
# outcome its apply_* handler writes, looked up in _LOCAL_OK / _LOCAL_FAIL
# in cycle.py. It used to be guessed from the outcome's NAME, so
# `library-missing` was recorded as executed. This refuses a deploy where a
# handler can write an outcome that is in neither list, or in both, or where
# a list names an outcome nothing writes. A new outcome is then a decision
# someone makes, not whatever its spelling happens to imply.
if ! python3 - <<'PYOUT'
import ast
import sys

tree = ast.parse(open("agent/cycle.py").read())
sets, produced, unreadable = {}, {}, []
for node in tree.body:
    if (isinstance(node, ast.Assign) and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id in ("_LOCAL_OK", "_LOCAL_FAIL")):
        sets[node.targets[0].id] = set(ast.literal_eval(node.value.args[0]))


def literals(e):
    """Every outcome an end_cycle argument can be: a constant, or either
    branch of `a if cond else b`."""
    if isinstance(e, ast.Constant) and isinstance(e.value, str):
        return [e.value]
    if isinstance(e, ast.IfExp):
        return literals(e.body) + literals(e.orelse)
    return None


for fn in tree.body:
    if not (isinstance(fn, ast.FunctionDef) and fn.name.startswith("apply_")):
        continue
    for c in ast.walk(fn):
        if (isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                and c.func.attr == "end_cycle" and len(c.args) >= 2):
            got = literals(c.args[1])
            if got is None:
                unreadable.append(f"{fn.name}:{c.lineno}")
            else:
                for v in got:
                    produced.setdefault(v, set()).add(fn.name)

bad = []
if set(sets) != {"_LOCAL_OK", "_LOCAL_FAIL"}:
    bad.append("could not find both _LOCAL_OK and _LOCAL_FAIL in cycle.py")
else:
    ok, fail = sets["_LOCAL_OK"], sets["_LOCAL_FAIL"]
    for v in sorted(ok & fail):
        bad.append(f"{v!r} is in BOTH lists")
    for v in sorted(set(produced) - ok - fail):
        bad.append(f"{v!r} (from {', '.join(sorted(produced[v]))}) is in "
                   f"neither list; an approval that ends with it is recorded "
                   f"as failed")
    for v in sorted((ok | fail) - set(produced)):
        bad.append(f"{v!r} is listed but no apply_* handler writes it")
for u in unreadable:
    bad.append(f"{u}: an outcome this gate cannot read; write it as a literal")
if not produced and not bad:
    bad.append("found no end_cycle outcomes in apply_*; the gate is reading "
               "the wrong thing")
for b in bad:
    print(f"  OUTCOME {b}")
sys.exit(1 if bad else 0)
PYOUT
then
  echo "!! an apply_* outcome is unclassified; rolling back to $BEFORE"
  git reset --hard "$BEFORE"
  exit 1
fi

if [ -f config.example.yaml ] && [ -f config.yaml ]; then
  python3 - <<'PY'
import re
def keys(p):
    return {m.group(1) for m in re.finditer(r'^([a-z_]+):', open(p).read(), re.M)}
missing = keys('config.example.yaml') - keys('config.yaml')
if missing:
    print("  NOTE: config.example.yaml has sections your config.yaml lacks: "
          + ", ".join(sorted(missing)))
PY
fi

# --- install changed unit files -------------------------------------------
#
# update.sh used to restart the dash and nothing else, so a change under
# systemd/ reached the box only when someone copied it by hand. That is how
# the installed riffle-cycle.service fell behind the repo's, and gate 6 then
# refused deploys for a reason the deploy could have fixed itself.
#
# AFTER the gates, not before: a gate that fails rolls the code back, and a
# unit installed ahead of it would stay behind, describing code that is gone.
# Only units already installed are updated. A unit that is in the repo but
# not installed is reported and left alone: installing it is a decision, and
# enabling it is another. A unit symlinked to the repo is already current.
# Failures are reported, not fatal: set -e would otherwise stop the script
# here, before the dash restart, with the new code half-deployed.
UNITDIR="${RIFFLE_UNITDIR:-/etc/systemd/system}"
changed=()
# TRACKED files only, as gate 11 reads them: untracked leftovers on the box
# (riffle-cycle.timer.bak-notify, riffle-dash.service.bak-alarms) were being
# installed into /etc/systemd/system with the real units.
# FROM WHAT IS COMMITTED, NOT WHAT IS ON DISK (L9, audit 2026-10-27).
# These are installed as root. A unit file changed on the box, by hand or by
# anything able to write there, is not what was reviewed and committed, so
# each unit comes from `git show HEAD:<file>` and a differing copy on disk is
# reported. (riffle itself cannot write /opt/riffle: SETUP.md, section 3.)
for f in $(git ls-files systemd/); do
  name=$(basename "$f")
  dest="$UNITDIR/$name"
  [ -L "$dest" ] && continue
  committed=$(mktemp)
  if ! git show "HEAD:$f" > "$committed" 2>/dev/null; then
    rm -f "$committed"; continue
  fi
  if [ -f "$f" ] && ! cmp -s "$f" "$committed"; then
    echo "!! $f on disk differs from what is committed; the committed version is used"
  fi
  if [ ! -e "$dest" ]; then
    echo "  $name is in the repo but not installed; left alone"
  elif ! cmp -s "$committed" "$dest"; then
    if sudo install -m 0644 -o root -g root "$committed" "$dest"; then
      changed+=("$name")
    else
      echo "!! could not install $name; the old copy is still in place"
    fi
  fi
  rm -f "$committed"
done
if [ "${#changed[@]}" -gt 0 ]; then
  echo "installed changed unit files: ${changed[*]}"
  if sudo systemctl daemon-reload; then
    for name in "${changed[@]}"; do
      case "$name" in
        # A timer or path unit runs continuously; restarting re-arms it with
        # the new definition. Neither starts a cycle by itself.
        *.timer|*.path) sudo systemctl restart "$name" \
                          || echo "!! could not restart $name" ;;
        riffle-dash.service) ;;      # restarted just below
        # The model servers keep running on the old definition until they
        # restart, and a restart reloads the model, so that is left to you.
        llama-*) echo "  $name takes effect when it next restarts" \
                      "(sudo systemctl restart $name reloads the model)" ;;
        # The riffle oneshots (cycle, run-cycle, restart-composer) pick it up
        # the next time they run. Do NOT restart them to "apply" it: starting
        # riffle-cycle.service runs a cycle.
        *) echo "  $name takes effect the next time it runs" ;;
      esac
    done
  else
    echo "!! daemon-reload failed; the new unit files are on disk but not loaded"
  fi
fi

# --- hand-installed copies that have fallen behind -------------------------
#
# These run from root-owned copies outside the checkout, on purpose: code
# that holds the signing key or runs as another user must not be changeable
# by whatever can write /opt/riffle (you, the deploying user; not riffle). So
# they are NOT installed here, which would run the checkout's code as root on
# every deploy. Unit files are different: they are configuration, installed
# above from the committed content only. But
# nothing said when the repo had moved on without them, which is how the
# riffle-sign fallback (#11) sat unnoticed. Now each deploy says.
_root="${RIFFLE_INSTALL_ROOT:-}"
for _f in "bin/riffle-sign:/usr/local/bin/riffle-sign:0755" \
          "bin/riffle-reader:/usr/local/bin/riffle-reader:0755" \
          "bin/riffle-build:/usr/local/bin/riffle-build:0755" \
          "keyutil.py:/usr/local/lib/riffle-signer/keyutil.py:0644" \
          "ed25519_pure.py:/usr/local/lib/riffle-signer/ed25519_pure.py:0644"; do
  _src=${_f%%:*}; _rest=${_f#*:}; _dst=${_rest%%:*}; _mode=${_rest#*:}
  if [ -e "$_root$_dst" ]; then
    if ! cmp -s "$_src" "$_root$_dst"; then
      echo "  $_dst is behind the repo's $_src. Install it when you mean to:"
      echo "    sudo install -m $_mode -o root -g root /opt/riffle/$_src $_dst"
    fi
  elif [ "${_dst#/usr/local/lib/riffle-signer/}" != "$_dst" ] \
       && [ -e "$_root/usr/local/bin/riffle-sign" ]; then
    echo "  $_dst is not installed, and riffle-sign refuses to sign without it:"
    echo "    sudo install -d -m 0755 -o root -g root /usr/local/lib/riffle-signer"
    echo "    sudo install -m $_mode -o root -g root /opt/riffle/$_src $_dst"
  fi
done

sudo systemctl restart riffle-dash
echo "riffle-dash restarted. Cycles pick up the new code on their next wake."
