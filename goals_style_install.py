#!/usr/bin/env python3
"""Carry the button and pill styling across to the goals page.

    sudo cp goals_style_install.py /opt/riffle/
    sudo python3 /opt/riffle/goals_style_install.py
    sudo systemctl restart riffle-dash

The two pages carry separate <style> blocks, so every rule added to the chat
page stopped at its edge — the goals page still had its own button shapes and
no hover state at all. That is the same drift that gave the header three pill
heights: styling added where it was needed rather than against a shared rule.

Properly fixed, the two blocks would be one served stylesheet. That is a
bigger change than it looks — both pages are single self-contained strings
with no static file route — so this mirrors the rules across instead, and
says so here rather than pretending the duplication is not there.

WHAT CHANGES ON /goals

  every button inverts on hover and holds it while pressed
    set / add      -> fills to foreground
    lock / pin     -> fills to dim
    remove/forget  -> fills to red
  the chat link in the header matches the pills on the chat page
  the intended/actual/locked tags share one height
  focus rings on inputs, which were missing entirely

Backups written as .bak-goalstyle.
"""
import os
import shutil
import sys

DASH = "/opt/riffle/agent/dash.py"

ANCHOR = """.mem .k{font-family:ui-monospace,monospace;font-size:10.5px;text-transform:uppercase;
  letter-spacing:.07em;color:var(--sig)}
</style>"""

ADDED = """.mem .k{font-family:ui-monospace,monospace;font-size:10.5px;text-transform:uppercase;
  letter-spacing:.07em;color:var(--sig)}

/* --- shared control styling, mirrored from the chat page ------------------
   These two pages have separate <style> blocks, so rules added to one stop at
   its edge. Kept in sync by hand; if a third page ever appears, factor this
   into a served stylesheet instead of copying it again. */
button,a.link,.clearbtn{transition:background .12s ease,color .12s ease,
  border-color .12s ease}
@media (hover:hover){
  button:hover{background:var(--fg);color:var(--bg)}
  button.ghost:hover{background:var(--dim);color:var(--bg);border-color:var(--dim)}
  button.warn:hover{background:var(--bad);color:var(--bg)}
  a.link:hover{background:var(--sig);color:var(--bg)}
}
button:active{background:var(--fg);color:var(--bg)}
button.ghost:active{background:var(--dim);color:var(--bg);border-color:var(--dim)}
button.warn:active{background:var(--bad);color:var(--bg)}
a.link:active{background:var(--sig);color:var(--bg)}

/* One shape for the header link and the inline tags, matching the chat page. */
a.link{display:inline-flex;align-items:center;justify-content:center;
  height:23px;box-sizing:border-box;font-size:11.5px;line-height:1;
  padding:0 11px;border-radius:99px;white-space:nowrap}
.tag{display:inline-flex;align-items:center;height:19px;box-sizing:border-box;
  padding:0 9px;line-height:1}

/* The range slider and text inputs had no focus state, which on a page whose
   whole job is changing values is worth having. */
input[type=text]:focus,input[type=number]:focus,textarea:focus{
  outline:0;border-color:var(--sig)}
input[type=range]:focus-visible{outline:2px solid var(--sig);outline-offset:3px}
</style>"""


def main():
    s = open(DASH).read()
    if "mirrored from the chat page" in s:
        print("  already present: goals page control styling")
        return
    if ANCHOR not in s:
        sys.exit("  FAILED: could not find the goals page style block. Nothing changed.")
    if s.count(ANCHOR) != 1:
        sys.exit(f"  FAILED: anchor matched {s.count(ANCHOR)} times, expected 1.")

    shutil.copy(DASH, f"{DASH}.bak-goalstyle")
    open(DASH, "w").write(s.replace(ANCHOR, ADDED, 1))

    import ast
    ast.parse(open(DASH).read())
    print("  patched: goals page buttons, link and tags")
    print("  dash.py parses.")
    print("\n  Next:  sudo systemctl restart riffle-dash")
    print("  Then hard-refresh /goals — the CSS is inline, so a cached page keeps\n"
          "  the old shapes.")


if __name__ == "__main__":
    main()
