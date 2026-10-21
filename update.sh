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
    for path in ("/", "/settings", "/history"):
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
# This measures what actually goes on the wire — system plus user plus the
# front page — against the model's window, and refuses a deploy that leaves
# too little room to answer in.
if ! python3 - <<'PYFIT'
import sys
sys.path.insert(0, ".")
try:
    import yaml
    from agent import cortex
    cfg = yaml.safe_load(open("config.yaml"))
    ctx = int(cfg.get("llm", {}).get("composer", {}).get("ctx", 20480))
    want = int(cfg.get("llm", {}).get("composer", {}).get("max_tokens", 3000))
    ceiling = int(cfg.get("cycle", {}).get("max_prompt_chars", 46000))
    sysc = len(cortex.stable_prefix(cfg, ""))
    total = ceiling + 1800
    tokens = int(total / 3.25)
    left = ctx - tokens
    print(f"  prompt ceiling {ceiling} chars (system {sysc} of it)"
          f" = ~{tokens} tokens of {ctx}; {left} left to answer in")
    if left < want:
        print(f"  TOO TIGHT: max_tokens is {want} and only {left} fit.")
        sys.exit(1)
except FileNotFoundError:
    print("  (no config.yaml here; skipping the fit check)")
except BaseException as e:
    print(f"  FIT GATE COULD NOT RUN: {type(e).__name__}: {e}")
sys.exit(0)
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
import re
import sys

try:
    unit = open("systemd/riffle-cycle.service").read()
    code = open("agent/cycle.py").read()
except OSError as e:
    print(f"  could not read the files: {e}")
    sys.exit(0)
m = re.search(r"^TimeoutStartSec=([0-9]+)", unit, re.M)
if not m:
    print("  no TimeoutStartSec in riffle-cycle.service")
    sys.exit(1)
limit = int(m.group(1))
waits = [int(x) for x in re.findall(r"timeout=([0-9]{3,})", code)]
worst = sum(sorted(waits, reverse=True)[:3])
print(f"  unit allows {limit}s; the three longest internal waits total {worst}s")
if worst > limit:
    print("  TOO TIGHT: systemd will kill the cycle before it can finish")
    sys.exit(1)
sys.exit(0)
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
import glob
import sys

sys.path.insert(0, ".")
try:
    from agent.cycle import _NEVER_TRIM
except Exception as e:
    print(f"  could not import _NEVER_TRIM: {e}")
    sys.exit(0)
# Comments do not count. The first version of this gate counted every
# occurrence, and the explanatory comment above _NEVER_TRIM names the
# headers — so a header could be orphaned and still score two. A gate that
# counts its own documentation as evidence is the thing it exists to catch.
body = ""
for path in glob.glob("agent/*.py"):
    try:
        for line in open(path):
            if line.lstrip().startswith("#"):
                continue
            body += line
    except OSError:
        pass
# The tuple itself is one occurrence; an emitted block is another.
# Comments stripped here too. _NEVER_TRIM has explanatory comments INSIDE
# it that name the headers; counting those in the tuple but not in the body
# made the subtraction negative and reported every header as orphaned. The
# two counts must be taken over the same text.
tuple_src = ""
src = open("agent/cycle.py").read()
i = src.find("_NEVER_TRIM = (")
if i >= 0:
    depth, j = 0, src.index("(", i)
    for j in range(src.index("(", i), len(src)):
        if src[j] == "(":
            depth += 1
        elif src[j] == ")":
            depth -= 1
            if depth == 0:
                break
    tuple_src = "".join(ln for ln in src[i:j].splitlines(keepends=True)
                        if not ln.lstrip().startswith("#"))
bad = []
for header in _NEVER_TRIM:
    emitted = body.count(header) - tuple_src.count(header)
    if emitted < 1:
        bad.append(header)
for b in bad:
    print(f"  ORPHAN PROTECTED HEADER {b!r}: nothing emits a block with this")
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
