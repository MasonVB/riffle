#!/usr/bin/env python3
"""Rename goals to settings, and put the knobs on it.

    sudo cp settings_install.py agent_policy.py /opt/riffle/
    sudo mv /opt/riffle/agent_policy.py /opt/riffle/agent/policy.py
    sudo python3 /opt/riffle/settings_install.py
    sudo systemctl restart riffle-dash

/goals becomes /settings and gains three panels:

  ACTIONS      every action set to auto, queue or never, from the page.
               Actions that reach the square are marked, because setting one
               of those to auto is the only change here that can put text in
               front of strangers without you.

  DRIVES       per drive, which actions it may propose. Two lists: `only`
               (a whitelist — dangerous) and `never`. This is the thing that
               silently pinned `deepen` to open_project for three days with no
               way to see or change it short of sqlite3.

  PROJECTS     what it is working on, how much is behind it, what it has read
               and how much of each thread is left unread.

WHY THE AUTONOMY TABLE HAD TO MOVE

It lived in config.yaml, which the dashboard cannot write and should not be
able to. So it moves to the database with the file seeding it once — exactly
what the goal table did, for exactly the same reason.

The boundary is unchanged: the AGENT cannot reach any of this. It has no route
to the console and nothing in the cycle writes these tables. Reading
config.yaml still tells you where things started; the page tells you where
they are.

Backups written as .bak-settings.
"""
import json
import os
import shutil
import sys

RIFFLE = "/opt/riffle"
DASH = f"{RIFFLE}/agent/dash.py"
CYCLE = f"{RIFFLE}/agent/cycle.py"


def patch(path, old, new, label, marker):
    s = open(path).read()
    if marker in s:
        print(f"  already present: {label}")
        return False
    if old not in s:
        sys.exit(f"  FAILED: anchor not found in {os.path.basename(path)} "
                 f"({label}). Nothing changed.")
    if s.count(old) != 1:
        sys.exit(f"  FAILED: anchor matched {s.count(old)} times ({label}).")
    if not os.path.exists(f"{path}.bak-settings"):
        shutil.copy(path, f"{path}.bak-settings")
    open(path, "w").write(s.replace(old, new, 1))
    print(f"  patched: {label}")
    return True


PANEL_CSS = """
.act{display:grid;grid-template-columns:1fr auto;gap:10px;align-items:center;
  padding:9px 0;border-bottom:1px solid var(--line)}
.act:last-child{border-bottom:0}
.act .n{font-family:ui-monospace,Menlo,monospace;font-size:13.5px}
.act .n small{display:block;color:var(--dim);font-size:11px;
  font-family:-apple-system,sans-serif;letter-spacing:0;text-transform:none}
.seg{display:inline-flex;border:1px solid var(--line);border-radius:99px;
  overflow:hidden}
.seg button{background:transparent;color:var(--dim);border:0;border-radius:0;
  padding:5px 12px;font-size:12px;font-weight:600;cursor:pointer}
.seg button.on[data-m=auto]{background:var(--sig);color:var(--bg)}
.seg button.on[data-m=queue]{background:var(--dim);color:var(--bg)}
.seg button.on[data-m=never]{background:var(--bad);color:var(--bg)}
@media (hover:hover){.seg button:hover{color:var(--fg)}}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0}
.chip{font-family:ui-monospace,monospace;font-size:11px;padding:3px 9px;
  border:1px solid var(--line);border-radius:99px;color:var(--dim);cursor:pointer;
  user-select:none}
.chip.only{border-color:var(--sig);color:var(--bg);background:var(--sig)}
.chip.never{border-color:var(--bad);color:var(--bg);background:var(--bad)}
.warn{color:var(--bad);font-size:12.5px;margin:6px 0}
.pj{border-left:3px solid var(--sig);padding-left:12px;margin-bottom:14px}
.pj.done{border-left-color:var(--line);color:var(--dim)}
.pj h3{margin:0 0 3px;font-size:15px}
.pj .q{color:var(--dim);font-size:13.5px;margin-bottom:6px}
.pj .rd{font-family:ui-monospace,monospace;font-size:12px;color:var(--dim);
  padding:3px 0}
.pj .rd b{color:var(--fg)}
"""

PANEL_HTML = """
<h2>actions &mdash; what it may do without asking</h2>
<div class=note><b>auto</b> happens. <b>queue</b> waits for your tap in the
chat. <b>never</b> means it cannot even propose it, and the refusal shows up as
a wasted cycle. Actions marked <span style="color:var(--sig)">&#9679;</span>
reach the square, where strangers read them.</div>
<div class=g id=actions></div>

<h2>drives &mdash; which actions each one may choose</h2>
<div class=note>Tap an action to cycle it: neutral &rarr; <b>only</b> (gold,
the drive may propose nothing else) &rarr; <b>never</b> (red) &rarr; neutral.
<b>only</b> is rarely what you want; a drive restricted to one action spends
every other cycle refusing itself.</div>
<div class=g id=restrict></div>

<h2>projects</h2>
<div class=note>A post has to come out of one of these. The bar is notes,
distinct sources, a draft, and an objection to its own argument.</div>
<div class=g id=projects></div>
"""

PANEL_JS = """
const ACTS = %ACTS%;
let pol = null;

async function loadPolicy(){
  pol = await (await fetch('/api/policy')).json();
  document.getElementById('actions').innerHTML = ACTS.map(function(a){
    const m = pol.modes[a] || 'queue';
    const sq = pol.square.indexOf(a) >= 0
      ? '<span style="color:var(--sig)">&#9679;</span> ' : '';
    return '<div class=act><div class=n>' + sq + esc(a) +
      (pol.notes[a] ? '<small>' + esc(pol.notes[a]) + '</small>' : '') +
      '</div><div class=seg>' +
      ['auto','queue','never'].map(function(x){
        return '<button data-m="' + x + '" class="' + (m===x?'on':'') +
          '" onclick="setMode(\\'' + a + '\\',\\'' + x + '\\')">' + x + '</button>';
      }).join('') + '</div></div>';
  }).join('');

  document.getElementById('restrict').innerHTML = pol.drives.map(function(d){
    const r = pol.restrictions[d] || {only:[],never:[]};
    const chips = ACTS.map(function(a){
      const cls = r.only.indexOf(a)>=0 ? 'chip only'
                : r.never.indexOf(a)>=0 ? 'chip never' : 'chip';
      return '<span class="' + cls + '" data-d="' + d + '" data-a="' + a +
             '" onclick="cycleChip(this)">' + esc(a) + '</span>';
    }).join('');
    const warn = r.only.length
      ? '<div class=warn>&#9888; this drive may ONLY propose ' +
        esc(r.only.join(', ')) + ' &mdash; everything else it thinks of is refused</div>'
      : '';
    return '<div style="margin-bottom:16px"><div class=gn>' + esc(d) + '</div>' +
      warn + '<div class=chips>' + chips + '</div>' +
      '<button onclick="saveRestrict(\\'' + d + '\\')">save ' + esc(d) + '</button></div>';
  }).join('');

  document.getElementById('projects').innerHTML = pol.projects.length
    ? pol.projects.map(function(p){
        const reads = (p.reads||[]).map(function(r){
          return '<div class=rd>#' + r.post_id + ' <b>' + esc(r.title) +
            '</b> &middot; ' + r.seen + ' of ' + r.total + ' replies read' +
            (r.left ? ', <span style="color:var(--sig)">' + r.left +
             ' unread</span>' : '') + '</div>';
        }).join('');
        return '<div class="pj' + (p.status==='active'?'':' done') + '">' +
          '<h3>' + esc(p.title) + '</h3><div class=q>' + esc(p.question) + '</div>' +
          '<div class=legend><span>' + p.notes + ' notes &middot; ' + p.sources +
          ' sources &middot; ' + p.age + 'h &middot; ' + esc(p.status) + '</span>' +
          '<span' + (p.ready?' style="color:var(--sig)"':'') + '>' +
          (p.ready?'ready to post':'not ready') + '</span></div>' + reads +
          (p.status==='active'
            ? '<div class=ctl><button class=warn2 onclick="closeProject()">close it</button></div>'
            : '') + '</div>';
      }).join('')
    : '<div style="color:var(--dim)">no projects yet</div>';
}
async function setMode(kind, mode){
  await api('/api/policy/mode', {kind:kind, mode:mode});
  await loadPolicy();
}
function cycleChip(el){
  el.className = el.className === 'chip' ? 'chip only'
               : el.className === 'chip only' ? 'chip never' : 'chip';
}
async function saveRestrict(d){
  const only = [], never = [];
  document.querySelectorAll('[data-d="' + d + '"]').forEach(function(el){
    if(el.className.indexOf('only')>=0) only.push(el.dataset.a);
    else if(el.className.indexOf('never')>=0) never.push(el.dataset.a);
  });
  await api('/api/policy/restrict', {drive:d, only:only, never:never});
  await loadPolicy();
}
async function closeProject(){
  if(!confirm('Close the open project? Its notes and reads are kept.')) return;
  await api('/api/project/close', {});
  await loadPolicy();
}
"""

ROUTES = '''    if h.command == "GET" and u.path == "/api/policy":
        from agent import policy, project as _pj
        policy.ensure(s, cfg)
        rows = s.db.execute("SELECT * FROM projects ORDER BY id DESC LIMIT 12").fetchall()
        projects = []
        for p in rows:
            st_ = _pj.stats(s, p["id"])
            ok, _why = _pj.ready(s, cfg, p["id"])
            reads = []
            for r in _pj.reads(s, p["id"]):
                try:
                    left = _pj.unread_count(s, r["id"])
                except Exception:
                    left = 0
                reads.append({"post_id": r["post_id"], "title": r["title"],
                              "seen": (r["comments_total"] or 0) - left,
                              "total": r["comments_total"] or 0, "left": left})
            projects.append({"id": p["id"], "title": p["title"],
                             "question": p["question"], "status": p["status"],
                             "notes": st_["notes"], "sources": st_["sources"],
                             "age": st_["age_hours"], "ready": bool(ok),
                             "reads": reads})
        h._json({"modes": policy.modes(s),
                 "kinds": policy.ACTION_KINDS,
                 "square": sorted(policy.REACHES_THE_SQUARE),
                 "notes": POLICY_NOTES,
                 "drives": [r["name"] for r in goals.all_drives(s)],
                 "restrictions": policy.restrictions(s),
                 "projects": projects})
        return True
'''

POST_ROUTES = '''        if u.path == "/api/policy/mode":
            from agent import policy
            old, new = policy.set_mode(s, b["kind"], b["mode"], "you")
            s.say("report", f"You set {b['kind']} to {b['mode']}"
                            + (f" (was {old})" if old and old != new else "") + ".")
            return h._json({"ok": True}) or True
        if u.path == "/api/policy/restrict":
            from agent import policy
            only, never = policy.set_restrictions(
                s, b["drive"], b.get("only"), b.get("never"), "you")
            s.say("report", f"You set what '{b['drive']}' may propose. "
                            + (f"Only: {', '.join(only)}. " if only else "")
                            + (f"Never: {', '.join(never)}." if never else "")
                            + ("No restrictions." if not only and not never else ""))
            return h._json({"ok": True}) or True
        if u.path == "/api/project/close":
            from agent import project as _pj
            p = _pj.active(s)
            if not p:
                return h._json({"error": "no project is open"}) or True
            _pj.close_project(s, p["id"], "abandoned")
            s.say("report", f"You closed the project '{p['title']}'. Its notes "
                            f"and reads are kept.")
            return h._json({"ok": True}) or True
'''

POLICY_NOTES = {
    "post": "one per UTC day, and only after a project clears the bar",
    "comment": "the main way it takes part",
    "read_thread": "opens a post and files it into the project",
    "read_more": "the next batch of replies on a thread already opened",
    "request_cycle": "asks to wake again sooner; capped daily",
    "open_project": "starts the thing a post has to come out of",
    "project_note": "an observation, source, draft, objection or correction",
    "adjust_drive": "moves its own goal weights, within goal_policy bounds",
    "add_goal": "always a proposal, never an act",
    "remember": "writes a durable memory",
    "listing_submission": "the only way it can be paid",
}


def main():
    if not os.path.exists(f"{RIFFLE}/agent/policy.py"):
        sys.exit("  agent/policy.py is missing — copy it in first.")

    # ---- cycle uses the database's autonomy map ---------------------------
    patch(CYCLE, "from agent import chat, cortex, drives, goals, memory, notify, project",
          "from agent import chat, cortex, drives, goals, memory, notify, policy, project",
          "cycle imports policy", marker="notify, policy, project")

    patch(CYCLE, "    goals.seed(state, cfg)\n    project.ensure(state)",
          "    goals.seed(state, cfg)\n    project.ensure(state)\n"
          "    policy.ensure(state, cfg)\n"
          "    # The settings page writes these; config.yaml only seeds them.\n"
          "    cfg[\"autonomy\"] = policy.effective(state, cfg)",
          "cycle reads autonomy from the database",
          marker="cfg[\"autonomy\"] = policy.effective(state, cfg)")

    # ---- rename ------------------------------------------------------------
    for old, new, label in (
            # The page uses a literal em dash, not the entity. Anchors have to
            # match the file, not the source it was generated from.
            ('<title>riffle \u2014 goals</title>',
             '<title>riffle \u2014 settings</title>', "settings title"),
            ('<a class="pill link" href="/goals">goals</a>',
             '<a class="pill link" href="/settings">settings</a>',
             "header link says settings"),
            ('if h.command == "GET" and u.path == "/goals":',
             'if h.command == "GET" and u.path in ("/settings", "/goals"):',
             "/settings route, /goals still works")):
        patch(DASH, old, new, label, marker=new[:46])

    # The history page links to goals too, if that patch is installed.
    s = open(DASH).read()
    if 'href="/goals">goals</a></header>' in s:
        open(DASH, "w").write(
            s.replace('href="/goals">goals</a></header>',
                      'href="/settings">settings</a></header>'))
        print("  patched: history page link")
    else:
        print("  skipped: history page link (not present)")

    # ---- panels ------------------------------------------------------------
    patch(DASH, "<h2>add a goal</h2>", PANEL_HTML + "\n<h2>add a goal</h2>",
          "action, drive and project panels", marker="what it may do without asking")

    patch(DASH, ".mem .k{font-family:ui-monospace,monospace;", PANEL_CSS
          + ".mem .k{font-family:ui-monospace,monospace;",
          "panel styling", marker=".seg button.on[data-m=auto]")

    # The /act review page has its own load(); anchor on the goals page's,
    # which is the only one that fetches /api/goals.
    patch(DASH, "async function load(){\n  data = await (await fetch('/api/goals')).json();",
          PANEL_JS + "\nasync function load(){\n"
          "  data = await (await fetch('/api/goals')).json();",
          "panel script", marker="async function loadPolicy()")

    sys.path.insert(0, RIFFLE)
    from agent import policy as _pol
    s = open(DASH).read()
    if "%ACTS%" in s:
        open(DASH, "w").write(
            s.replace("%ACTS%", json.dumps(_pol.ACTION_KINDS), 1))
        print(f"  inlined {len(_pol.ACTION_KINDS)} action kinds into the page")

    s = open(DASH).read()
    if "load(); loadPolicy();" in s:
        print("  already present: settings page loads the panels")
    elif "\nload();\n</script>" in s:
        open(DASH, "w").write(
            s.replace("\nload();\n</script>", "\nload(); loadPolicy();\n</script>", 1))
        print("  patched: settings page loads the panels")
    else:
        sys.exit("  FAILED: could not find the goals page bootstrap call.")

    patch(DASH, '    if h.command == "GET" and u.path == "/api/goals":',
          ROUTES + '    if h.command == "GET" and u.path == "/api/goals":',
          "/api/policy route", marker='u.path == "/api/policy"')

    patch(DASH, '        if u.path == "/api/goal/weight":',
          POST_ROUTES + '        if u.path == "/api/goal/weight":',
          "policy write routes", marker='"/api/policy/mode"')

    # do_POST only forwards two prefixes to the settings handler; the new
    # routes fall outside both and were answering 404.
    patch(DASH,
          '        if self.path.startswith("/api/goal/") or self.path.startswith("/api/memory/"):',
          '        if self.path.startswith(("/api/goal/", "/api/memory/",\n'
          '                                 "/api/policy/", "/api/project/")):',
          "settings POST routes reach the handler",
          marker='"/api/policy/", "/api/project/"')

    # Create the table when the dashboard starts. It was only being created by
    # the cycle or by the first GET, so a POST arriving first crashed the
    # handler thread.
    patch(DASH, "    goals.seed(st, cfg)",
          "    goals.seed(st, cfg)\n"
          "    from agent import policy as _policy\n"
          "    _policy.ensure(st, cfg)",
          "policy table created at startup", marker="_policy.ensure(st, cfg)")

    patch(DASH, "def _goals_routes(h):",
          "POLICY_NOTES = " + repr(POLICY_NOTES) + "\n\n\ndef _goals_routes(h):",
          "POLICY_NOTES constant", marker="POLICY_NOTES = {")

    import ast
    for f in (DASH, CYCLE):
        ast.parse(open(f).read())
    print("\n  modules parse.")
    print("\n  Next:  sudo systemctl restart riffle-dash   then open /settings")


if __name__ == "__main__":
    main()
