#!/usr/bin/env python3
"""Restart the composer without giving the dashboard any privileges at all.

    sudo cp restart_via_path_install.py /opt/riffle/
    sudo python3 /opt/riffle/restart_via_path_install.py
    sudo systemctl daemon-reload
    sudo systemctl enable --now riffle-restart-composer.path
    sudo systemctl restart riffle-dash

WHAT WENT WRONG

    sudo: The "no new privileges" flag is set, which prevents sudo from
    running as root.

riffle-dash.service sets NoNewPrivileges=true, which makes it impossible for
that process or any child to gain privileges — including via setuid binaries
like sudo. That is the hardening doing precisely its job, and my previous
patch tried to punch through it.

I could have removed the flag. That would have been the wrong trade:
NoNewPrivileges is one of the more valuable lines in that unit, and dropping
it to gain a convenience button is backwards.

THE BETTER SHAPE

The dashboard writes an empty file. A root-owned systemd path unit is watching
for it, and when it appears the matching service deletes it and restarts the
composer.

    dash (unprivileged)  ->  touch /var/lib/riffle/restart-composer.request
    systemd path unit    ->  sees it
    systemd service      ->  rm the file, restart llama-composer

The dashboard gains nothing. No sudo, no capability, no relaxed flags, no
setuid anything. It can create a file in a directory it already owns, which
it could already do. The privilege stays entirely on systemd's side of the
line, and the only action reachable through it is the one hard-coded in the
unit — there is no argument to smuggle anything into, which is a stronger
guarantee than the sudoers rule gave.

This also removes /etc/sudoers.d/riffle-model. The riffle account goes back to
having no sudo, which is where it should have stayed.

Backups written as .bak-pathrestart.
"""
import os
import shutil
import sys

RIFFLE = "/opt/riffle"
DASH = f"{RIFFLE}/agent/dash.py"
SUDOERS = "/etc/sudoers.d/riffle-model"
FLAG = "/var/lib/riffle/restart-composer.request"

PATH_UNIT = """[Unit]
Description=watch for a composer restart request from the dashboard

[Path]
# The dashboard is unprivileged and cannot restart a service. It can create a
# file in its own state directory, so that is the entire interface. There is no
# argument and nothing to smuggle: the only thing this can cause is the one
# command in riffle-restart-composer.service.
PathExists=/var/lib/riffle/restart-composer.request
Unit=riffle-restart-composer.service

[Install]
WantedBy=paths.target
"""

SERVICE_UNIT = """[Unit]
Description=restart the composer on request
After=llama-composer.service

[Service]
Type=oneshot
# Remove the flag first so the path unit re-arms, and so a failed restart does
# not leave it looping.
ExecStartPre=/bin/rm -f /var/lib/riffle/restart-composer.request
ExecStart=/usr/bin/systemctl restart llama-composer.service
"""

NEW_CALL = '''            try:
                # Ask systemd rather than becoming root. riffle-restart-composer.path
                # is watching this file; the matching service deletes it and does
                # the restart. The dashboard needs no privilege of any kind.
                open("/var/lib/riffle/restart-composer.request", "w").close()
            except Exception as e:
                self.state.say("error", f"could not signal a restart: {e}")
                return
            try:'''

OLD_CALL = '''            try:
                r = subprocess.run(
                    ["sudo", "-n", "/usr/bin/systemctl", "restart",
                     "llama-composer.service"],
                    capture_output=True, text=True, timeout=300)
                if r.returncode != 0:
                    self.state.say("error", "could not restart the composer: "
                                            + (r.stderr or "").strip()[:300])
                    return'''


def main():
    s = open(DASH).read()
    if "restart-composer.request" in s:
        print("  already present: path-trigger restart")
    else:
        if OLD_CALL not in s:
            sys.exit("  FAILED: could not find the sudo call in dash.py. "
                     "Nothing changed.")
        shutil.copy(DASH, f"{DASH}.bak-pathrestart")
        open(DASH, "w").write(s.replace(OLD_CALL, NEW_CALL, 1))
        print("  patched: dash signals by file instead of calling sudo")

    for name, body in (("riffle-restart-composer.path", PATH_UNIT),
                       ("riffle-restart-composer.service", SERVICE_UNIT)):
        for d in ("/etc/systemd/system", f"{RIFFLE}/systemd"):
            p = os.path.join(d, name)
            if os.path.isdir(d):
                open(p, "w").write(body)
                print(f"  wrote {p}")

    if os.path.exists(SUDOERS):
        os.rename(SUDOERS, SUDOERS + ".removed")
        print(f"  removed {SUDOERS} — riffle has no sudo again")
        print("    (kept as .removed; delete it once this is working)")
    else:
        print("  no sudoers file to remove")

    import ast
    ast.parse(open(DASH).read())
    print("\n  dash.py parses.")
    print("""
  Next:
    sudo systemctl daemon-reload
    sudo systemctl enable --now riffle-restart-composer.path
    sudo systemctl restart riffle-dash

  Test it without the browser:
    sudo -u riffle touch /var/lib/riffle/restart-composer.request
    sleep 2 && systemctl is-active llama-composer      # 'activating' or 'active'
    ls /var/lib/riffle/restart-composer.request        # should be gone
""")


if __name__ == "__main__":
    main()
