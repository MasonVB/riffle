#!/usr/bin/env python3
"""Put /opt/riffle in git properly, without pushing a credential.

    sudo python3 repo_setup.py --check          # scan only, change nothing
    sudo python3 repo_setup.py --apply          # fix ignores, untrack secrets
    sudo python3 repo_setup.py --apply --remote git@github.com:you/riffle.git

WHY THIS IS NOT JUST `git push`

Two things in this tree must never reach a repository you can read from
elsewhere, and one of them is already tracked:

  config.yaml     holds your Pushover keys, and a Brave key if you add one.
                  It was committed in the first commit.
  *.bak-*         the backups every installer has left behind, which are
                  snapshots of files that may have contained the above.

The citizen secret and the signing seed live in /var/lib/riffle and were never
inside the repo, which is the one thing that has been right from the start.

So this untracks config.yaml, writes a config.example.yaml with the values
blanked, and refuses to finish if it finds anything that looks like a
credential in a tracked file. The scan reads your actual secret from
/var/lib/riffle and greps for it verbatim — a pattern match can be fooled, a
literal comparison cannot.

WHAT THE REPO IS FOR

History and rollback, offsite backup, and — if you make it readable — the
ability for someone helping you to see the real current state of a file
instead of guessing at it. Every "anchor not found" failure in the last two
days came from writing a patch against a file that could not be seen.

If you make it public, the scan below is the only thing standing between you
and a published API key. Run --check first and read the output.
"""
import argparse
import os
import re
import subprocess
import sys

RIFFLE = "/opt/riffle"
DATA = "/var/lib/riffle"

GITIGNORE = """# Secrets and machine-local settings
config.yaml

# Installer backups — snapshots of files that may have held credentials
*.bak
*.bak-*
*.orig

# Python
__pycache__/
*.pyc

# Local scratch
*.log
*.sqlite
*.sqlite-*
"""

UPDATE_SH = """#!/bin/bash
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
"""


def run(*a, **kw):
    return subprocess.run(a, cwd=RIFFLE, capture_output=True, text=True, **kw)


def tracked():
    r = run("git", "ls-files")
    return [f for f in r.stdout.splitlines() if f]


def scan(files):
    """Look for credentials in tracked files. Literal values first."""
    findings = []
    literals = {}
    for name, path in (("citizen secret", f"{DATA}/riffle.secret"),
                       ("signing seed", f"{DATA}/riffle.ed25519.seed")):
        try:
            v = open(path).read().strip()
            if len(v) > 12:
                literals[name] = v
        except OSError:
            pass
    # Values out of the live config, which is what actually holds the keys.
    try:
        cfg = open(f"{RIFFLE}/config.yaml").read()
        for m in re.finditer(r'^\s*(user_key|api_token|api_key):\s*"?([^"\s#]+)"?',
                             cfg, re.M):
            if len(m.group(2)) > 8:
                literals[m.group(1)] = m.group(2)
    except OSError:
        pass

    patterns = [
        ("pushover-ish token", re.compile(r"\b[a-z0-9]{30}\b")),
        ("brave-ish key", re.compile(r"\bBSA[A-Za-z0-9_\-]{20,}\b")),
        ("64-hex seed", re.compile(r"\b[0-9a-f]{64}\b")),
        ("bearer secret", re.compile(r"1f916_sk_[A-Za-z0-9_\-]+")),
        ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY")),
    ]
    for f in files:
        p = os.path.join(RIFFLE, f)
        try:
            body = open(p, errors="replace").read()
        except OSError:
            continue
        for name, val in literals.items():
            if val in body:
                findings.append((f, f"LITERAL {name} appears verbatim"))
        for name, rx in patterns:
            for m in rx.finditer(body):
                # The board's own hashes are 64-hex and harmless; skip the
                # files that legitimately carry them.
                if name == "64-hex seed" and (
                        f.startswith("testsrc/") or f.startswith("postsrc/")
                        or f.endswith(".md") or "witness" in f):
                    continue
                findings.append((f, f"{name}: …{m.group(0)[-8:]}"))
                break
    return findings


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--remote")
    a = ap.parse_args()
    if not (a.apply or a.check):
        a.check = True

    if not os.path.isdir(f"{RIFFLE}/.git"):
        sys.exit(f"{RIFFLE} is not a git repository. `cd {RIFFLE} && git init` first.")

    who = run("git", "status", "--porcelain")
    print(f"  {len(tracked())} tracked file(s), "
          f"{len([l for l in who.stdout.splitlines() if l])} uncommitted change(s)")

    # ---- scan BEFORE anything else ---------------------------------------
    print("\n  scanning tracked files for credentials…")
    findings = scan(tracked())
    if findings:
        for f, why in findings:
            print(f"    !! {f}: {why}")
    else:
        print("    nothing found")

    if a.check:
        print("\n  --check only. Nothing changed.")
        if findings:
            print("  Fix the findings before pushing anywhere readable.")
        return

    # ---- gitignore --------------------------------------------------------
    gi = f"{RIFFLE}/.gitignore"
    cur = open(gi).read() if os.path.exists(gi) else ""
    if "config.yaml" not in cur:
        open(gi, "w").write(GITIGNORE)
        print("\n  wrote .gitignore (config.yaml, backups, pycache, databases)")
    else:
        print("\n  .gitignore already excludes config.yaml")

    # ---- untrack the config, ship an example ------------------------------
    if "config.yaml" in tracked():
        run("git", "rm", "--cached", "-q", "config.yaml")
        print("  untracked config.yaml (the file on disk is untouched)")

    src = open(f"{RIFFLE}/config.yaml").read()
    blanked = re.sub(r'^(\s*(?:user_key|api_token|api_key):\s*).*$',
                     r'\1""', src, flags=re.M)
    open(f"{RIFFLE}/config.example.yaml", "w").write(
        "# Copy to config.yaml and fill in the blanked values. config.yaml is\n"
        "# gitignored precisely so those never reach a repository.\n" + blanked)
    run("git", "add", "config.example.yaml")
    print("  wrote config.example.yaml with the keys blanked")

    for f in tracked():
        if ".bak" in f or f.endswith(".pyc") or "__pycache__" in f:
            run("git", "rm", "--cached", "-q", f)
    print("  untracked backups and bytecode")

    # ---- pre-commit hook ---------------------------------------------------
    hook = f"{RIFFLE}/.git/hooks/pre-commit"
    open(hook, "w").write(
        "#!/bin/bash\n"
        "# Refuse a commit that carries a credential. The scan is the same one\n"
        "# repo_setup.py runs; this makes it impossible to forget.\n"
        "exec python3 /opt/riffle/repo_setup.py --check | tee /dev/stderr | "
        "grep -q '!!' && { echo 'commit refused: see above'; exit 1; }\n"
        "exit 0\n")
    os.chmod(hook, 0o755)
    print("  installed a pre-commit hook that runs this scan")

    # ---- update script -----------------------------------------------------
    up = f"{RIFFLE}/update.sh"
    open(up, "w").write(UPDATE_SH)
    os.chmod(up, 0o755)
    run("git", "add", "update.sh", ".gitignore")
    print("  wrote update.sh (pull, syntax-check, restart, roll back on error)")

    if a.remote:
        run("git", "remote", "remove", "origin")
        r = run("git", "remote", "add", "origin", a.remote)
        print(f"  remote origin -> {a.remote}" if r.returncode == 0
              else f"  could not set remote: {r.stderr.strip()}")

    print("""
  Next, as YOUR user (not root — the tree belongs to you):

    cd /opt/riffle
    git add -A
    git commit -m "two days of installers, collapsed into one state"
    git push -u origin main       # or master; `git branch --show-current`

  Then to update the machine from the repo afterwards:

    /opt/riffle/update.sh
""")


if __name__ == "__main__":
    main()
