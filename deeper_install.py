#!/usr/bin/env python3
"""Let the agent see its own project, and let it open a thread.

    sudo cp deeper_install.py /opt/riffle/
    sudo python3 /opt/riffle/deeper_install.py
    sudo systemctl restart riffle-dash
    sudo systemctl start riffle-cycle.service

THE BUG THAT EXPLAINS THE SHALLOWNESS

    parts.append("FRONT PAGE: ...")
    material = "\\n\\n".join(parts)[:budget]     <-- frozen here
    parts.append(project.as_context(...))       <-- never read
    parts.append("WHAT YOU REMEMBER: ...")      <-- never read
    parts.append("YOUR GOALS RIGHT NOW: ...")   <-- never read

`material` was assembled before three of the five blocks were added. The agent
has never seen its project, its memories, or its goal table during a cycle.
Every wake really was a cold start, exactly as it kept saying.

Mine, from an earlier patch: I added a new assembly line and tried to remove
the original by matching its text, and the match found the line I had just
written. The same mistake as the marker collisions — replacing by content when
the content occurs twice.

THREE FIXES

1. ASSEMBLY. Structural blocks are joined first and the front page gets
   whatever budget is left, never the reverse. A front page cannot push the
   project out of the prompt, because the project is already in it.

2. TRUNCATION THAT ADMITS ITSELF. Post bodies were dumped whole and then cut
   by a slice across the whole prompt — which is why it kept complaining about
   things being cut off. Each body is now trimmed to a fixed length and marked
   `"body_truncated": true`, so a cut is a labelled fact rather than a sentence
   that stops.

3. read_thread. The front page is an index. Reading it and never opening
   anything is not shallowness of character, it is having no way to open a
   post. `read_thread <id>` fetches the post and its comments and files the
   substance into the open project as a source note — so what it reads
   accumulates instead of evaporating at the end of the cycle.

Backups written as .bak-deeper.
"""
import json
import os
import shutil
import sys

RIFFLE = "/opt/riffle"
CYCLE = f"{RIFFLE}/agent/cycle.py"
DRIVES = f"{RIFFLE}/agent/drives.py"
CORTEX = f"{RIFFLE}/agent/cortex.py"
SCHEMA_JSON = f"{RIFFLE}/proposal_schema.json"

READ_THREAD_PAYLOAD = {
    "type": "object",
    "properties": {"post_id": {"type": "integer", "minimum": 1}},
    "required": ["post_id"], "additionalProperties": False,
}

OLD_BLOCK = '''    parts.append("FRONT PAGE:\\n" + json.dumps(
        [{k: p.get(k) for k in ("id", "title", "author", "votes", "comments", "body")}
         for p in front], indent=1))
    material = "\\n\\n".join(parts)[:budget]

    parts.append(project.as_context(state, cfg,
                                    budget=int(budget * 0.45)))
    recalled = memory.recall(state, f"{drive} " + " ".join(
        str(p.get("title", "")) for p in front[:8]), limit=8)
    goal_lines = "\\n".join(
        f"  {r['name']}: {r['weight']:.2f}{' [locked]' if r['locked'] else ''}"
        f"  — {r['description'] or ''}" for r in goals.all_drives(state))
    parts.append("WHAT YOU REMEMBER:\\n" + memory.as_context(recalled))
    parts.append("YOUR GOALS RIGHT NOW (you may propose adjust_drive on an unlocked one):\\n"
                 + goal_lines)'''

NEW_BLOCK = '''    # Structural blocks first, front page with whatever is left. The previous
    # order froze `material` before these were appended, so none of them ever
    # reached the model and every cycle really was the cold start it described.
    recalled = memory.recall(state, f"{drive} " + " ".join(
        str(p.get("title", "")) for p in front[:8]), limit=8)
    goal_lines = "\\n".join(
        f"  {r['name']}: {r['weight']:.2f}{' [locked]' if r['locked'] else ''}"
        f"  — {r['description'] or ''}" for r in goals.all_drives(state))
    parts.append(project.as_context(state, cfg, budget=int(budget * 0.40)))
    parts.append("WHAT YOU REMEMBER:\\n" + memory.as_context(recalled))
    parts.append("YOUR GOALS RIGHT NOW (you may propose adjust_drive on an "
                 "unlocked one):\\n" + goal_lines)

    fixed = "\\n\\n".join(parts)
    room = max(1800, budget - len(fixed) - 400)

    # Trim each body to a fixed size and SAY SO, rather than letting one slice
    # cut the last post mid-sentence. A labelled truncation is something the
    # agent can act on; an unlabelled one just looks like the board is broken.
    per = max(220, min(700, room // max(1, len(front))))
    rows = []
    for p in front:
        body = (p.get("body") or "")
        row = {"id": p.get("id"), "title": p.get("title"),
               "author": p.get("author"), "votes": p.get("votes"),
               "comments": p.get("comments"),
               "body": body[:per]}
        if len(body) > per:
            row["body_truncated"] = True
            row["body_full_chars"] = len(body)
        rows.append(row)
    front_block = ("FRONT PAGE — an index, not the posts themselves. Bodies are "
                   "cut to " + str(per) + " characters and comments are not "
                   "included at all. Use `read_thread` on an id to get the whole "
                   "post and its replies; what you read is filed into your "
                   "project.\\n" + json.dumps(rows, indent=1)[:room])
    parts.append(front_block)
    material = "\\n\\n".join(parts)'''


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
    if not os.path.exists(f"{path}.bak-deeper"):
        shutil.copy(path, f"{path}.bak-deeper")
    open(path, "w").write(s.replace(old, new, 1))
    print(f"  patched: {label}")
    return True


def main():
    # ---- 1. assembly ------------------------------------------------------
    patch(CYCLE, OLD_BLOCK, NEW_BLOCK,
          "prompt assembly: structural blocks can no longer be dropped",
          marker="Structural blocks first, front page with whatever is left")

    # ---- 2. read_thread ---------------------------------------------------
    patch(DRIVES, '    "open_project": (["title", "question"], [],',
          '''    "read_thread": (["post_id"], [],
                    lambda p: {"post_id": _i(p["post_id"], "post_id")}),
    "open_project": (["title", "question"], [],''',
          "read_thread in the gate schema", marker='"read_thread": (')

    patch(CYCLE, '    if kind in ("open_project", "project_note", "close_project"):',
          '''    if kind == "read_thread":
        return apply_read_thread(state, cfg, cid, payload, drive)

    if kind in ("open_project", "project_note", "close_project"):''',
          "cycle routes read_thread", marker="apply_read_thread(state, cfg, cid")

    patch(CYCLE, "def apply_project(state, cfg, cid, kind, p, drive, rationale):",
          '''def apply_read_thread(state, cfg, cid, p, drive):
    """Open a post properly and keep what it said.

    The front page is an index. Without this the agent could see that a thread
    existed and never read it, which is what it kept apologising for.
    """
    pid = p["post_id"]
    try:
        data = Reader(cfg["base"]).post(pid)
    except HttpError as e:
        state.log(f"could not read post {pid}: {e}", level="warn", drive=drive)
        state.say("error", f"Cycle {cid} · could not open #{pid}: {e}")
        state.end_cycle(cid, "read-failed")
        return 0

    post = data.get("post") or data
    title = str(post.get("title") or "")[:160]
    body = str(post.get("body") or "")
    author = post.get("author") or "?"
    comments = data.get("comments") or post.get("comments") or []
    if isinstance(comments, int):
        comments = []
    ctext = " || ".join(
        f"{c.get('author', '?')}: {str(c.get('body', ''))[:300]}"
        for c in comments[:12] if isinstance(c, dict))

    digest = (f"#{pid} \\"{title}\\" by {author}. {body[:900]}"
              + (f" REPLIES: {ctext[:900]}" if ctext else " (no replies)"))

    proj = project.active(state)
    if proj:
        try:
            project.add_note(state, proj["id"], cid, "source", digest,
                             source=f"1f916:{pid}")
            s = project.stats(state, proj["id"])
            where = (f"filed into '{proj['title']}' — now {s['notes']} notes "
                     f"from {s['sources']} sources")
        except ValueError as e:
            where = f"not filed: {e}"
    else:
        memory.remember(state, digest[:600], kind="board", source=f"1f916:{pid}")
        where = ("no project is open, so this went to short-term memory. Open "
                 "one if the thread is worth returning to.")

    state.log(f"read #{pid} ({len(body)} chars, {len(comments)} replies); {where}",
              drive=drive)
    state.say("report", f"Cycle {cid} · read #{pid} \\"{title}\\" "
                        f"({len(body)} chars, {len(comments)} replies). {where}",
              {"drive": drive})
    state.end_cycle(cid, "thread-read")
    return 0


def apply_project(state, cfg, cid, kind, p, drive, rationale):''',
          "apply_read_thread handler", marker="def apply_read_thread(")

    # ---- 3. contract ------------------------------------------------------
    patch(CORTEX, '  open_project        {"title": string, "question": string}',
          '''  read_thread         {"post_id": int}
  open_project        {"title": string, "question": string}''',
          "contract lists read_thread", marker='read_thread         {"post_id"')

    patch(CORTEX, "A POST COMES OUT OF A PROJECT",
          '''THE FRONT PAGE IS AN INDEX. The bodies you see there are cut short and the
replies are not shown at all. If a thread looks like it matters, read it —
`read_thread <id>` fetches the whole post with its replies and files it into
your project, where the next cycle will see it. Reading two threads properly
beats skimming fifteen.

A POST COMES OUT OF A PROJECT''',
          "contract explains the index", marker="THE FRONT PAGE IS AN INDEX")

    # ---- 4. constrained decoding -----------------------------------------
    if os.path.exists(SCHEMA_JSON):
        sch = json.load(open(SCHEMA_JSON))
        have = {b["properties"]["action"]["const"] for b in sch["oneOf"]}
        if "read_thread" in have:
            print("  already present: read_thread in the schema")
        else:
            sch["oneOf"].append({
                "type": "object",
                "properties": {"action": {"const": "read_thread"},
                               "payload": READ_THREAD_PAYLOAD,
                               "rationale": {"type": "string"},
                               "sources": {"type": "object"}},
                "required": ["action", "payload", "rationale"],
                "additionalProperties": False})
            shutil.copy(SCHEMA_JSON, f"{SCHEMA_JSON}.bak-deeper")
            json.dump(sch, open(SCHEMA_JSON, "w"), indent=1)
            print(f"  added read_thread to proposal_schema.json "
                  f"({len(sch['oneOf'])} branches)")

    import ast
    for f in (CYCLE, DRIVES, CORTEX):
        ast.parse(open(f).read())
    print("\n  modules parse.")
    print("""
  BEFORE RESTARTING, check the deepen restriction that refused cycle 27:

    sudo sqlite3 -header -column /var/lib/riffle/state.sqlite \\
      "SELECT name, selects, forbids FROM drives;"

  If deepen's `selects` is not empty, clear it — the drive should be able to
  read, note, comment and post, not only open projects:

    sudo sqlite3 /var/lib/riffle/state.sqlite \\
      "UPDATE drives SET selects=NULL WHERE name='deepen';"

  Then:
    sudo systemctl restart riffle-dash
    sudo systemctl start riffle-cycle.service""")


if __name__ == "__main__":
    main()
