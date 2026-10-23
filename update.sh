#!/bin/bash
# Pull, verify, restart. Refuses to leave the machine on code that does not
# parse OR does not import — a failure here means the agent stops waking,
# silently.
set -euo pipefail
cd /opt/riffle

BEFORE=$(git rev-parse HEAD)
echo "at $BEFORE"

git fetch --quiet origin
git merge --ff-only origin/"$(git rev-parse --abbrev-ref HEAD)"
AFTER=$(git rev-parse HEAD)

if [ "$BEFORE" = "$AFTER" ]; then
  echo "already up to date"
  exit 0
fi
echo "-> $AFTER"
git --no-pager log --oneline "$BEFORE..$AFTER"

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
# the smaller one), not config.yaml, which has never carried it.
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
FRONT_HDR = 260          # the FRONT PAGE header (228 chars) plus slack
WRAP = 140               # <board> tags and the closing instruction (99 + drive)

# The cycle's budget arithmetic, as code with comments, strings and
# whitespace removed. If any is gone, this gate's model of the prompt is out
# of date and its answer means nothing.
MIRRORED = ("_room=_ceiling-_sys_chars-int(budget*0.10)",
            "room=max(1800,budget-len(fixed)-400)",
            "if_room<8000:")


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
    budget = int(cfg["cycle"]["max_context_chars"])     # cycle has no default
    sysc = len(cortex.stable_prefix(cfg, ""))

    data_room = ceiling - sysc - int(budget * 0.10)
    if data_room < 8000:
        print(f"  the system prompt is {sysc} chars of a {ceiling} ceiling, "
              f"leaving {data_room} for the rest; the cycle logs an error "
              f"every wake at that size")
        sys.exit(1)

    capped = ceiling - int(budget * 0.10) + 1800        # front page at its floor
    uncapped = sysc + budget - 400                       # front page given `budget`
    worst = max(capped, uncapped) + FRONT_HDR + WRAP
    tokens = math.ceil(worst / CHARS_PER_TOKEN) + TEMPLATE_TOKENS
    left = ctx - tokens
    print(f"  worst prompt {worst} chars ~ {tokens} tokens of {ctx}; "
          f"{left} left, max_tokens {want} (system {sysc}, empty continuity)")
    if left < want:
        print("  TOO TIGHT: lower max_prompt_chars, max_context_chars or max_tokens")
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
# GATE 6 READ ONE FILE AND THE WRONG UNIT.
#
# It summed the three longest waits in cycle.py (1200 + 900 + 200 = 2300)
# and compared that to the unit IN THE REPO. Two problems:
#
#   The big waits are elsewhere. cortex.py holds the composer's 1800 s and
#   memory.py holds reflect's 900 s. A real worst-case path runs the lock
#   wait, reflect, consolidate and the composer in sequence — about 6,800 s,
#   which is nearly three times what this gate measured. It passed a
#   TimeoutStartSec of 3000 against that.
#
#   And update.sh never installs units, so the repo copy can say 10800 while
#   /etc/systemd/system says 2700. The number that matters is the installed
#   one.
import glob
import re
import sys

bad = []
try:
    code = ""
    for path in ("agent/cycle.py", "agent/cortex.py", "agent/memory.py",
                 "agent/consolidate.py", "agent/chat.py"):
        try:
            code += open(path).read()
        except OSError:
            pass
    waits = sorted((int(x) for x in re.findall(r"timeout=([0-9]{3,})", code)),
                   reverse=True)
    # Every distinct long wait a single cycle can sit through in sequence:
    # the composer lock, triage for reflect, triage for consolidate, then
    # the composer itself. Five is a deliberate over-count — a gate about a
    # ceiling should assume the bad case.
    worst = sum(waits[:5])

    # THE INSTALLED UNIT, falling back to the repo copy with a warning.
    unit = None
    for cand in ("/etc/systemd/system/riffle-cycle.service",
                 "systemd/riffle-cycle.service"):
        try:
            unit = open(cand).read()
            where = cand
            break
        except OSError:
            continue
    if unit is None:
        bad.append("no riffle-cycle.service found, installed or in the repo")
    else:
        if where.startswith("systemd/"):
            print("  (no installed unit readable here; checking the repo copy)")
        m = re.search(r"^TimeoutStartSec=([0-9]+)", unit, re.M)
        if not m:
            bad.append(f"no TimeoutStartSec in {where}")
        else:
            limit = int(m.group(1))
            print(f"  {where} allows {limit}s; the five longest internal "
                  f"waits total {worst}s")
            if worst > limit:
                bad.append(f"systemd kills the cycle at {limit}s and the "
                           f"waits can reach {worst}s. SIGTERM runs no "
                           f"finally, so this is a cycle lost mid-work.")
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

# --- gate 7: no function whose only call is to itself ---------------------
#
# A patch meant to collapse a duplicated dispatch matched inside the new
# dispatcher instead of at the call site, so apply_local() became a function
# whose entire body was `return apply_local(...)`. It parsed, it imported,
# every page rendered, the prompt fit, the grammar compiled, the timeouts
# added up. It raised RecursionError the first time anyone approved a queued
# action.
#
# Direct self-recursion with no other call and no obvious base case is never
# intentional here. This finds it in the AST.
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
        # The len(names)==1 test below only catches a function whose ONLY
        # call is itself. A self-call inserted ahead of a real body —
        # `def f(x): return f(x)` followed by the genuine code — passed,
        # and is just as infinitely recursive. Catch that shape directly:
        # a bare `return <self>(...)` with nothing guarding it.
        for _n in fn.body:
            if not isinstance(_n, ast.Return):
                break           # something real happens first; stop looking
            _v = _n.value
            if (isinstance(_v, ast.Call) and isinstance(_v.func, ast.Name)
                    and _v.func.id == fn.name):
                bad.append(f"{path}:{_n.lineno} {fn.name}() returns a call "
                           f"to itself as its first statement, with no "
                           f"condition — unconditional infinite recursion")
            break

        names = {c.func.id for c in ast.walk(fn)
                 if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
        # Builtins and exception constructors are not "work": a function
        # whose only real call is itself still does nothing, whether or not
        # it raises on the way out. The first version of this gate counted
        # ValueError and so missed the very bug it was written for.
        names -= set(dir(__builtins__)) | {
            "ValueError", "TypeError", "OSError", "KeyError", "RuntimeError",
            "len", "str", "int", "float", "dict", "list", "set", "sorted",
            "print", "open", "range", "max", "min", "sum", "any", "all"}
        if fn.name in names and len(names) == 1:
            bad.append(f"{path}:{fn.lineno} {fn.name}() calls only itself")
for b in bad:
    print(f"  SELF-RECURSION {b}")
sys.exit(1 if bad else 0)
PYREC
then
  echo "!! a function calls only itself; rolling back to $BEFORE"
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
# GATE 8 COUNTED MENTIONS, AND A MENTION IS NOT A HEADER.
#
# It compared each _NEVER_TRIM entry against the whole of agent/*.py and
# passed if the string appeared more than once. cortex.py:257 reads
# "...is in YOUR ACTUAL SITUATION, counted from the actions table" — prose,
# in a different prompt — and that satisfied the gate, so renaming the real
# situation block would have gone through unnoticed.
#
# _is_rule asks whether the header is in the first 400 characters of a
# BLOCK. Most blocks are assembled in main() from live state and cannot be
# built here, so the closest honest proxy is positional: a header STARTS a
# string literal; a prose reference sits mid-sentence. That distinguishes
#
#   "YOUR ACTUAL SITUATION, checked this cycle..."     <- a header
#   "...proposed is in YOUR ACTUAL SITUATION, counted" <- a mention
#
# My first rewrite tried to construct every block and flagged five valid
# headers it simply could not reach — a gate that vetoes correct work,
# which is the fault I have now shipped twice in one day.
import ast
import glob
import sys

bad = []
try:
    sys.path.insert(0, ".")
    from agent.cycle import _NEVER_TRIM

    # Every string literal in the package, with the offset of each header.
    starts = {k: False for k in _NEVER_TRIM}
    for path in glob.glob("agent/*.py"):
        try:
            tree = ast.parse(open(path).read())
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            lit = node.value
            for k in _NEVER_TRIM:
                # Within the first 80 characters IS a header; _is_rule
                # allows 400, and no real header sits further in than a
                # short lead-in.
                #
                # But skip a literal that is EXACTLY the header: those are
                # the _NEVER_TRIM entries themselves, and a list that
                # satisfies its own check tests nothing. Renaming the real
                # block left the tuple as the only match, and the gate
                # passed — the audit's exact mutation.
                if lit.strip() == k:
                    continue
                if k in lit[:80]:
                    starts[k] = True
    for k, found in starts.items():
        if not found:
            bad.append(f"{k!r} is protected from trimming and no string "
                       f"literal starts with it. Either the header was "
                       f"renamed and the list was not, or the entry is dead.")
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
    print(f"  could not read config.example.yaml: {e}")
    sys.exit(0)
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
              "repo_setup.py", "witness.py"}
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

sudo systemctl restart riffle-dash
echo "riffle-dash restarted. Cycles pick up the new code on their next wake."
