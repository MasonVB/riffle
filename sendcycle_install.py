#!/usr/bin/env python3
"""Two send buttons: one that talks, one that also steers the next cycle.

    sudo cp sendcycle_install.py /opt/riffle/
    sudo python3 /opt/riffle/sendcycle_install.py
    sudo systemctl restart riffle-dash

    [ ask what it's been doing...        ]  [ send ] [ send + cycle ]

  send           a conversation. Nothing reaches the wake cycle.
  send + cycle   the same, and the message is carried into the next cycle as
                 a standing instruction.

WHY THE SPLIT IS WORTH HAVING

Since the last patch every chat message became an instruction, which is wrong
in the common case. Most of what you type is a question — "what have you been
doing", "why did you refuse that" — and turning each one into a directive
means the next cycle wakes carrying your idle curiosity as a mandate.

Now the default is inert and steering is a deliberate second button.

It does NOT start a cycle. The instruction waits for the next wake, or for the
run cycle button. Firing one automatically would queue two generations behind
the same composer lock and hand you six minutes of nothing; the sequencing is
better left to you.

Enter still sends. Ctrl+Enter sends with the cycle, so the deliberate one
needs a deliberate keystroke.

Backups written as .bak-sendcycle.
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
    if not os.path.exists(f"{DASH}.bak-sendcycle"):
        shutil.copy(DASH, f"{DASH}.bak-sendcycle")
    open(DASH, "w").write(s.replace(old, new, 1))
    print(f"  patched: {label}")
    return True


def main():
    patch('  <button id=send>send</button>',
          '  <button id=send>send</button>\n'
          '  <button id=sendcyc title="also carried into the next wake cycle">'
          'send + cycle</button>',
          "second button in the footer", marker="id=sendcyc")

    patch("#send:disabled{opacity:.35}",
          """#send:disabled{opacity:.35}
/* The steering one is outlined rather than filled: it is the deliberate
   choice, not the frequent one. */
#sendcyc{background:transparent;color:var(--sig);border:1px solid var(--sig);
  border-radius:11px;height:44px;padding:0 13px;font:inherit;font-weight:600;
  cursor:pointer;white-space:nowrap;
  transition:background .12s ease,color .12s ease}
@media (hover:hover){#sendcyc:hover{background:var(--sig);color:var(--bg)}}
#sendcyc:active{background:var(--sig);color:var(--bg)}
#sendcyc:disabled{opacity:.35}
footer{gap:7px}
@media (max-width:430px){#send,#sendcyc{padding:0 11px;font-size:13.5px}}""",
          "styling for the second button", marker="#sendcyc{background:transparent")

    patch('''async function submit(){
  const q = box.value.trim(); if(!q || busy) return;
  box.value=''; box.style.height='auto'; busy=true; send.disabled=true;
  waitStart = Date.now();
  await fetch('/api/send', {method:'POST', headers:{'Content-Type':'application/json'},
                            body: JSON.stringify({q:q})});
  log.scrollTop = log.scrollHeight;
}''',
          '''async function submit(instruct){
  const q = box.value.trim(); if(!q || busy) return;
  box.value=''; box.style.height='auto'; busy=true;
  send.disabled = true; document.getElementById('sendcyc').disabled = true;
  waitStart = Date.now();
  await fetch('/api/send', {method:'POST', headers:{'Content-Type':'application/json'},
                            body: JSON.stringify({q:q, instruct: !!instruct})});
  log.scrollTop = log.scrollHeight;
}''',
          "submit takes an instruct flag", marker="async function submit(instruct)")

    patch("send.onclick = submit;",
          "send.onclick = function(){ submit(false); };\n"
          "document.getElementById('sendcyc').onclick = function(){ submit(true); };",
          "each button wired", marker="document.getElementById('sendcyc').onclick")

    patch('''  if(e.key==='Enter' && !e.shiftKey && !matchMedia('(pointer:coarse)').matches){
    e.preventDefault(); submit(); }});''',
          '''  if(e.key==='Enter' && !e.shiftKey && !matchMedia('(pointer:coarse)').matches){
    // Ctrl+Enter steers. The deliberate action gets the deliberate keystroke.
    e.preventDefault(); submit(e.ctrlKey || e.metaKey); }});''',
          "Ctrl+Enter sends with the cycle", marker="submit(e.ctrlKey || e.metaKey)")

    patch("    busy = d.generating; send.disabled = busy;",
          "    busy = d.generating; send.disabled = busy;\n"
          "    document.getElementById('sendcyc').disabled = busy;",
          "both buttons follow the busy state", marker="'sendcyc').disabled = busy")

    # only create an instruction when asked
    patch('''            from agent.state import add_instruction
            add_instruction(self.state, q,
                            int((self.cfg.get("instructions") or {})
                                .get("default_cycles", 1)))''',
          '''            # Only when you asked for it. Turning every question into a
            # directive meant the next cycle woke carrying idle curiosity as a
            # mandate.
            if body.get("instruct"):
                from agent.state import add_instruction
                add_instruction(self.state, q,
                                int((self.cfg.get("instructions") or {})
                                    .get("default_cycles", 1)))
                self.state.log("you sent an instruction to the next cycle: "
                               + q[:160])''',
          "plain send no longer steers the cycle", marker='if body.get("instruct"):')

    import ast
    ast.parse(open(DASH).read())
    print("\n  dash.py parses.")
    print("\n  Next:  sudo systemctl restart riffle-dash  then hard-refresh the page")


if __name__ == "__main__":
    main()
