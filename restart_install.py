#!/usr/bin/env python3
"""A button to restart the model server.

    sudo cp restart_install.py /opt/riffle/
    sudo python3 /opt/riffle/restart_install.py
    sudo systemctl restart riffle-dash

WHAT IT DOES

Restarts llama-composer: the model is dropped and re-read from disk, the KV
cache and slot state go with it. Useful when the composer has wedged, when a
flag in the unit file has changed, or when you have swapped the GGUF.

It is not free. `--mlock` pulls 20.6 GB off NVMe before the server answers
anything, so expect 90 to 150 seconds of nothing. The button watches
/health and reports in the chat thread when it is back, with how long it took,
rather than leaving you guessing.

Any generation in flight dies with the server, so the button is disabled while
the worker is busy or a cycle is running. That is a soft guard — it stops the
obvious mistake, not a determined one.

THE PART WORTH READING TWICE

This grants the `riffle` account sudo, which it did not have and which I said
it should not have. That was the right default and this is a real narrowing of
it, so the grant is written as tightly as sudo allows:

    riffle ALL=(root) NOPASSWD: /usr/bin/systemctl restart llama-composer.service
    riffle ALL=(root) NOPASSWD: /usr/bin/systemctl restart llama-triage.service

Two exact command strings. No wildcards, no bare `systemctl` (which would
permit restarting anything, including sshd), no shell. sudo matches the full
argument vector, so `systemctl restart something-else` is refused.

The model still cannot reach this. Its outbound calls are the board lookups
and the web tools; it has no route to localhost:80. A POST here is you
pressing a button, same as the run-cycle button.

If you would rather not grant it at all, skip this patch — `sudo systemctl
restart llama-composer` from your shell does the same thing.

Backups written as .bak-restart.
"""
import os
import shutil
import subprocess
import sys

RIFFLE = "/opt/riffle"
DASH = f"{RIFFLE}/agent/dash.py"
SUDOERS = "/etc/sudoers.d/riffle-model"

SUDOERS_BODY = """# riffle may restart its own model servers and nothing else.
# Exact command strings, no wildcards: sudo matches the whole argument vector,
# so `systemctl restart sshd` is refused by this rule.
riffle ALL=(root) NOPASSWD: {sc} restart llama-composer.service
riffle ALL=(root) NOPASSWD: {sc} restart llama-triage.service
"""


def patch(old, new, label, marker, path=DASH):
    s = open(path).read()
    if marker in s:
        print(f"  already present: {label}")
        return False
    if old not in s:
        sys.exit(f"  FAILED: anchor not found ({label}). Nothing changed.")
    if not os.path.exists(f"{path}.bak-restart"):
        shutil.copy(path, f"{path}.bak-restart")
    open(path, "w").write(s.replace(old, new, 1))
    print(f"  patched: {label}")
    return True


HANDLER = '''    _restart_lock = __import__("threading").Lock()
    _restarting = False

    def restart_model(self):
        """Restart llama-composer and report back when it answers again."""
        cls = type(self)
        w = self.worker
        if getattr(w, "busy", False) or w.depth() > 0 or cls._cycle_running:
            return {"error": "something is generating; wait for it to finish"}
        with cls._restart_lock:
            if cls._restarting:
                return {"error": "already restarting"}
            cls._restarting = True

        def run():
            import time as _t
            import urllib.request as _u
            t0 = _t.time()
            self.state.say("report", "Restarting the composer. It has to read "
                                     "20.6 GB off disk, so give it a couple of "
                                     "minutes.")
            try:
                r = subprocess.run(
                    ["sudo", "-n", "/usr/bin/systemctl", "restart",
                     "llama-composer.service"],
                    capture_output=True, text=True, timeout=300)
                if r.returncode != 0:
                    self.state.say("error", "could not restart the composer: "
                                            + (r.stderr or "").strip()[:300])
                    return
                # Wait for it to answer rather than assuming. A unit that has
                # "started" has only forked; the model is still loading.
                for _ in range(200):
                    _t.sleep(2)
                    try:
                        with _u.urlopen("http://127.0.0.1:8080/health",
                                        timeout=4) as resp:
                            if resp.status == 200:
                                self.state.say(
                                    "report", f"Composer is back, "
                                              f"{int(_t.time() - t0)}s. Fresh "
                                              f"KV cache and slot state.")
                                self.state.log("you restarted the composer")
                                return
                    except Exception:
                        continue
                self.state.say("error", "the composer did not answer /health "
                                        "within 400s; check "
                                        "`journalctl -u llama-composer`.")
            except Exception as e:
                self.state.say("error", f"restart failed: {e}")
            finally:
                cls._restarting = False

        _th.Thread(target=run, daemon=True).start()
        return {"ok": True}

    def run_cycle(self):'''


def main():
    sc = shutil.which("systemctl")
    if not sc:
        sys.exit("  systemctl not found; cannot scope the sudoers rule.")
    print(f"  systemctl is at {sc}")

    # ---- sudoers ----------------------------------------------------------
    if os.path.exists(SUDOERS):
        print(f"  already present: {SUDOERS}")
    else:
        visudo = shutil.which("visudo")
        if not visudo:
            # A malformed file in /etc/sudoers.d can break sudo for everyone on
            # the box. Without visudo there is no way to check, so write
            # nothing and hand the content over instead.
            print("  visudo not found — NOT writing the sudoers file.")
            print("  Add it yourself, validating as you go:\n")
            print("    sudo visudo -f " + SUDOERS + "\n")
            print(SUDOERS_BODY.format(sc=sc))
        else:
            tmp = SUDOERS + ".new"
            with open(tmp, "w") as f:
                f.write(SUDOERS_BODY.format(sc=sc))
            os.chmod(tmp, 0o440)
            check = subprocess.run([visudo, "-cf", tmp], capture_output=True,
                                   text=True)
            if check.returncode != 0:
                os.unlink(tmp)
                sys.exit(f"  FAILED: sudoers file did not validate:\n"
                         f"{check.stderr}\nNothing was installed.")
            os.rename(tmp, SUDOERS)
            print(f"  wrote {SUDOERS} (0440, validated by visudo)")

    if shutil.which("sudo") and os.path.exists(SUDOERS):
        ok = subprocess.run(["sudo", "-n", "-u", "riffle", "sudo", "-n", "-l"],
                            capture_output=True, text=True)
        if "llama-composer" in (ok.stdout or ""):
            print("  verified: riffle may restart llama-composer and nothing else")
        else:
            print("  NOTE: could not confirm the grant; check with\n"
                  "        sudo -u riffle sudo -n -l")

    # ---- button -----------------------------------------------------------
    patch('  <button id=runbtn class=pillbtn onclick="runCycle()">run cycle</button>',
          '  <button id=runbtn class=pillbtn onclick="runCycle()">run cycle</button>\n'
          '  <button id=rsbtn class=pillbtn onclick="restartModel()">restart model</button>',
          "restart button in the header", marker="id=rsbtn")

    patch("async function runCycle(){",
          '''async function restartModel(){
  if(!confirm('Restart the composer?\\n\\nIt re-reads 20.6 GB from disk and will '
            + 'not answer for a couple of minutes. Anything generating right now '
            + 'is lost.')) return;
  const b = document.getElementById('rsbtn');
  b.disabled = true; b.textContent = 'restarting\\u2026';
  const r = await fetch('/api/restart-model', {method:'POST',
    headers:{'Content-Type':'application/json'}, body:'{}'});
  const d = await r.json();
  if(d.error){ alert(d.error); b.disabled = false; b.textContent = 'restart model'; }
}
async function runCycle(){''',
          "restartModel() in the page script", marker="async function restartModel()")

    patch("    rb.disabled = !!d.cycle_running;",
          '''    rb.disabled = !!d.cycle_running || !!d.model_restarting;
    const sb = document.getElementById('rsbtn');
    sb.disabled = !!d.model_restarting || !!d.cycle_running || busy;
    sb.textContent = d.model_restarting ? 'restarting\\u2026' : 'restart model';''',
          "buttons reflect restart state", marker="model_restarting ? 'restarting")

    patch('        if u.path == "/api/run-cycle":',
          '''        if u.path == "/api/restart-model":
            return self._json(self.restart_model())
        if u.path == "/api/run-cycle":''',
          "restart-model route", marker='"/api/restart-model"')

    patch("    def run_cycle(self):", HANDLER,
          "restart_model handler", marker="def restart_model(self):")

    patch('                "alarms_list": alarm_list,',
          '                "alarms_list": alarm_list,\n'
          '                "model_restarting": type(self)._restarting,',
          "expose model_restarting", marker='"model_restarting"')

    import ast
    ast.parse(open(DASH).read())
    print("\n  dash.py parses.")
    print("\n  Next:  sudo systemctl restart riffle-dash")
    print("\n  To undo the sudo grant later:  sudo rm /etc/sudoers.d/riffle-model")


if __name__ == "__main__":
    main()
