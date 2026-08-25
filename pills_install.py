#!/usr/bin/env python3
"""Uniform pill heights, a pinned pill that stays filled, and "0 waiting".

    sudo cp pills_install.py /opt/riffle/
    sudo python3 /opt/riffle/pills_install.py
    sudo systemctl restart riffle-dash

THREE FIXES

1. HEIGHTS. The pills were three different shapes: .pill had 2px vertical
   padding, .pillbtn had 3px, and a.link had its own. Each was styled where it
   was added rather than against a shared rule, so they drifted. One rule now
   fixes height, font size, padding and border for all three, and the colour
   variants keep their own overrides.

2. THE PINNED PILL LOSING ITS FILL. This was a real bug rather than a style
   nit. poll() rebuilds p-state.className from scratch every 2.5 seconds:

       st.className = 'pill' + (d.alarms ? ' bad' : ...)

   which wipes the `pinned` class the click added. The panel stayed open,
   because that class lives on the wrapper, but the pill reverted to outline —
   so the two halves of one state disagreed, and hovering off made it visible.
   poll() now re-derives `pinned` from the wrapper, which is the single place
   that state actually lives.

3. "0 waiting" instead of an empty pill. An empty element with a border is a
   grey smudge that reads as a rendering fault. Zero is information: it says
   nothing is waiting on you.

Backups written as .bak-pills.
"""
import os
import shutil
import sys

DASH = "/opt/riffle/agent/dash.py"


def patch(old, new, label, marker, required=True):
    s = open(DASH).read()
    if marker in s:
        print(f"  already present: {label}")
        return False
    if old not in s:
        if required:
            sys.exit(f"  FAILED: anchor not found ({label}). Nothing changed.")
        print(f"  skipped: {label}")
        return False
    if not os.path.exists(f"{DASH}.bak-pills"):
        shutil.copy(DASH, f"{DASH}.bak-pills")
    open(DASH, "w").write(s.replace(old, new, 1))
    print(f"  patched: {label}")
    return True


PILL_CSS = """
/* One shape for every pill in the header. These were styled separately as
   each was added and had drifted to three different heights; the colour
   variants below carry more specificity and keep their own overrides. */
.pill,.pillbtn,a.link{
  display:inline-flex;align-items:center;justify-content:center;
  height:23px;box-sizing:border-box;
  font:inherit;font-size:11.5px;line-height:1;letter-spacing:.01em;
  padding:0 11px;border-radius:99px;border:1px solid var(--line);
  white-space:nowrap;vertical-align:middle;text-decoration:none}
.alarmwrap{display:inline-flex;align-items:center;vertical-align:middle}
header{align-items:center}"""


def main():
    patch(".pill.bad{color:var(--bad);border-color:var(--bad)}",
          ".pill.bad{color:var(--bad);border-color:var(--bad)}" + PILL_CSS,
          "one shape for every pill", marker="One shape for every pill")

    # 0 waiting, and correct plurals on the alarm pill
    patch("""    q.textContent = d.queued ? d.queued + ' waiting' : '';""",
          """    q.textContent = d.queued + ' waiting';""",
          'queue pill shows "0 waiting"', marker="d.queued + ' waiting';")

    patch("""    st.textContent = d.generating ? 'thinking' : (d.alarms ? d.alarms + ' alarm' : 'idle');""",
          """    st.textContent = d.generating ? 'thinking'
      : (d.alarms ? d.alarms + ' alarm' + (d.alarms === 1 ? '' : 's') : 'idle');""",
          "alarm pill pluralises", marker="d.alarms === 1 ? '' : 's'")

    # the actual bug: poll() was wiping the pinned class every 2.5s
    patch("""    st.className = 'pill' + (d.alarms ? ' bad' : d.generating ? ' hot' : '');""",
          """    // The wrapper owns whether the panel is open. Re-derive `pinned` from
    // it rather than rebuilding className blind, which used to drop the fill
    // every poll while the panel stayed open.
    const openNow = document.getElementById('alarmwrap').classList.contains('pinned');
    st.className = 'pill' + (d.alarms ? ' bad' : d.generating ? ' hot' : '')
      + (openNow && d.alarms ? ' pinned' : '');""",
          "pinned fill survives polling", marker="openNow && d.alarms")

    import ast
    ast.parse(open(DASH).read())
    print("\n  dash.py parses.")
    print("\n  Next:  sudo systemctl restart riffle-dash")
    print("  Then hard-refresh the page (Ctrl+Shift+R) — the CSS is inline in the\n"
          "  document, so a cached copy will show the old shapes.")


if __name__ == "__main__":
    main()
