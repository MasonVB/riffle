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
