#!/bin/bash
# Pull, verify, restart. Refuses to leave the machine on code that does not
# parse — a syntax error here means the agent stops waking, silently.
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

if ! python3 - <<'PY'
import ast, glob, sys
bad = 0
for f in sorted(glob.glob('*.py') + glob.glob('agent/*.py')):
    try:
        ast.parse(open(f).read())
    except SyntaxError as e:
        print(f"  SYNTAX ERROR {f}:{e.lineno}: {e.msg}")
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
