#!/usr/bin/env python3
"""Rename the button, and show which messages steered a cycle.

    sudo cp goldborder_install.py /opt/riffle/
    sudo python3 /opt/riffle/goldborder_install.py
    sudo systemctl restart riffle-dash

  "send + cycle"  ->  "send to cycle"

  A message sent that way now carries a gold border in the thread, so
  scrolling back tells you which of your messages were questions and which
  were directives. That distinction is invisible otherwise, and it is the one
  that explains why a cycle did what it did.

The flag is stored on the message rather than inferred from the instructions
table, because instructions are spent and eventually cleared — the border has
to survive that or the record disagrees with itself a day later.

Backups written as .bak-gold.
"""
import os
import shutil
import sys

RIFFLE = "/opt/riffle"
DASH = f"{RIFFLE}/agent/dash.py"


def patch(old, new, label, marker):
    s = open(DASH).read()
    if marker in s:
        print(f"  already present: {label}")
        return False
    if old not in s:
        sys.exit(f"  FAILED: anchor not found ({label}). Nothing changed.")
    if s.count(old) != 1:
        sys.exit(f"  FAILED: anchor matched {s.count(old)} times ({label}).")
    if not os.path.exists(f"{DASH}.bak-gold"):
        shutil.copy(DASH, f"{DASH}.bak-gold")
    open(DASH, "w").write(s.replace(old, new, 1))
    print(f"  patched: {label}")
    return True


def main():
    patch('  <button id=sendcyc title="also carried into the next wake cycle">'
          'send + cycle</button>',
          '  <button id=sendcyc title="also carried into the next wake cycle '
          'as a standing instruction">send to cycle</button>',
          "button reads 'send to cycle'", marker=">send to cycle</button>")

    patch(".user{align-self:flex-end;background:#23281c;border:1px solid var(--line);",
          """/* A message that steered a cycle is marked, and stays marked. The
   instruction it created will be spent and cleared; the record of having
   given it should not disappear with it. */
.msg.user.instr{border-color:var(--sig)}
.user{align-self:flex-end;background:#23281c;border:1px solid var(--line);""",
          "gold border styling", marker=".msg.user.instr{border-color:var(--sig)}")

    patch("""  el.className = 'msg ' + (m.role==='user'?'user':m.role==='report'?'report':
                           m.role==='error'?'err':'agent');""",
          """  el.className = 'msg ' + (m.role==='user'?'user':m.role==='report'?'report':
                           m.role==='error'?'err':'agent')
    + (m.role==='user' && m.meta && m.meta.instruct ? ' instr' : '');""",
          "renderer applies the class", marker="m.meta.instruct ? ' instr' : ''")

    # Two installers have layered comments between these lines, so anchor on
    # the two statements alone rather than the block between them.
    patch('            self.state.say("user", q)\n',
          '            steering = bool(body.get("instruct"))\n'
          '            self.state.say("user", q, {"instruct": steering})\n',
          "the flag is stored on the message",
          marker='self.state.say("user", q, {"instruct": steering})')

    patch('            if body.get("instruct"):\n',
          '            if steering:\n',
          "handler uses the same flag", marker="            if steering:")

    # the history page renders statically, so it needs the class too
    s = open(DASH).read()
    old = '''    cls = {"user": "msg user", "report": "msg report",
           "error": "msg err"}.get(m["role"], "msg agent")'''
    if "msg user instr" in s:
        print("  already present: history page border")
    elif old in s:
        new = '''    cls = {"user": "msg user", "report": "msg report",
           "error": "msg err"}.get(m["role"], "msg agent")
    if m["role"] == "user" and meta.get("instruct"):
        cls = "msg user instr"'''
        if not os.path.exists(f"{DASH}.bak-gold"):
            shutil.copy(DASH, f"{DASH}.bak-gold")
        open(DASH, "w").write(s.replace(old, new, 1))
        print("  patched: history page shows the border too")
    else:
        print("  skipped: history page renderer not found")

    import ast
    ast.parse(open(DASH).read())
    print("\n  dash.py parses.")
    print("\n  Next:  sudo systemctl restart riffle-dash, then hard-refresh")


if __name__ == "__main__":
    main()
