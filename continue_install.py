#!/usr/bin/env python3
"""Stop replies dying mid-sentence, and continue the ones that do.

    sudo cp continue_install.py /opt/riffle/
    sudo python3 /opt/riffle/continue_install.py
    sudo systemctl restart riffle-dash

WHY IT STOPPED AT "The maintainer"

Not the token limit — the context limit. #1916 is a very long post, its tool
result is roughly 2,500 tokens, and with the system prompt, the record and the
recalled memories on top, the 12,288-token window filled while the answer was
still being written. The server stops mid-word, because there is nowhere left
to put the next one. The HTTP 400 you saw earlier with three read_post calls
in a row was the same thing further along.

TWO FIXES

1. A BUDGET ACROSS TOOL RESULTS, not just a count. Six lookups were allowed
   with no limit on their combined size, so three large threads could fill the
   window before the model wrote a word. Results now share a character budget
   and each one is trimmed to what remains, with the trim labelled. A tool
   loop that can exhaust its own context is not bounded, whatever the call
   count says.

2. CONTINUATION. If a reply stops because the window filled, the answer
   continues in a second call — and the continuation drops the tool results
   and the record, keeping the system prompt, the question and what was
   written so far. That is the point: continuing with the same context would
   hit the same wall in the same place. Up to two continuations, then it says
   plainly that it ran out of room.

   The text is appended to the same message, so you see one reply, not three.
   A visible seam would be an implementation detail leaking into the thing you
   are trying to read.

Backups written as .bak-continue.
"""
import os
import shutil
import sys

RIFFLE = "/opt/riffle"
CHAT = f"{RIFFLE}/agent/chat.py"


def patch(old, new, label, marker):
    s = open(CHAT).read()
    if marker in s:
        print(f"  already present: {label}")
        return False
    if old not in s:
        sys.exit(f"  FAILED: anchor not found ({label}). Nothing changed.")
    if s.count(old) != 1:
        sys.exit(f"  FAILED: anchor matched {s.count(old)} times ({label}).")
    if not os.path.exists(f"{CHAT}.bak-continue"):
        shutil.copy(CHAT, f"{CHAT}.bak-continue")
    open(CHAT, "w").write(s.replace(old, new, 1))
    print(f"  patched: {label}")
    return True


CONTINUE_FN = '''

CONTINUE_SYSTEM = """You are riffle, continuing an answer that was cut off because the context
window filled. The text you had written is below. Carry straight on from where
it stops — do not greet, do not restate, do not summarise what you already
said. If the cut fell mid-word, complete that word.

The material you looked up is no longer in front of you. Work from what you
already wrote. If something you were about to cite is gone, say so rather than
reconstructing it from memory."""


def continue_reply(cfg, state, mid, question, partial, on_delta, rounds=2):
    """Finish a reply that ran out of window.

    Deliberately drops the tool results and the record. Continuing with the
    same context would refill the window at the same point and stop in the
    same place, which is a loop rather than a fix.
    """
    text = partial
    for _ in range(rounds):
        meta = {}
        msgs = [{"role": "system", "content": CONTINUE_SYSTEM},
                {"role": "user",
                 "content": "The question was:\\n" + question[:1500]
                            + "\\n\\nWhat you had written:\\n" + text[-4000:]},
                {"role": "assistant", "content": ""}]
        more = stream_completion(cfg["llm"]["composer"], msgs, on_delta,
                                 meta=meta)
        text += more
        if meta.get("finish_reason") != "length":
            return text, True
    on_delta("\\n\\n[stopped here — the answer was longer than the context "
             "window allows. Ask for the rest of a specific part.]")
    return text, False
'''


def main():
    # ---- 1. finish_reason surfaces from the stream -------------------------
    patch('''def stream_completion(llm_cfg, messages, on_delta, timeout=2400):''',
          '''def stream_completion(llm_cfg, messages, on_delta, timeout=2400, meta=None):''',
          "stream_completion accepts a meta dict", marker="timeout=2400, meta=None")

    patch('''            delta = (chunk.get("choices") or [{}])[0].get("delta", {}).get("content")
            if delta:
                full.append(delta)
                on_delta(delta)''',
          '''            choice = (chunk.get("choices") or [{}])[0]
            # The last chunk carries why generation stopped. "length" means the
            # window filled, which is the difference between a finished answer
            # and one that was cut off mid-word.
            if meta is not None and choice.get("finish_reason"):
                meta["finish_reason"] = choice["finish_reason"]
            delta = choice.get("delta", {}).get("content")
            if delta:
                full.append(delta)
                on_delta(delta)''',
          "capture why generation stopped", marker='meta["finish_reason"] = choice')

    patch("def run_tool(reader, line, cfg=None):", CONTINUE_FN
          + "\ndef run_tool(reader, line, cfg=None):",
          "continue_reply()", marker="def continue_reply(")

    # ---- 2. tool results share a budget ------------------------------------
    patch('''        tools_used = []
        wcfg = cfg.get("web") or {}''',
          '''        tools_used = []
        # A count is not a bound. Six lookups with no size limit could fill the
        # window before a word was written, which is what produced both the
        # HTTP 400 and the reply that stopped at "The maintainer".
        tool_chars_left = int((cfg.get("web") or {}).get("tool_char_budget", 9000))
        wcfg = cfg.get("web") or {}''',
          "tool results share a character budget", marker="tool_chars_left")

    patch('''            tools_used.append(tool_line.strip())
            result = run_tool(reader, tool_line, cfg)''',
          '''            tools_used.append(tool_line.strip())
            result = run_tool(reader, tool_line, cfg)
            if len(result) > tool_chars_left:
                result = (result[:max(400, tool_chars_left)]
                          + "\\n\\n[cut here: the lookups for this answer have "
                            "used their share of the context window. Ask about "
                            "one thing at a time if you need more.]")
            tool_chars_left = max(0, tool_chars_left - len(result))''',
          "each result trimmed to what is left", marker="used their share of the context window")

    # ---- 3. continue when the window fills ---------------------------------
    patch('''            out = stream_completion(cfg["llm"]["composer"], msgs, on_delta)
            tool_line = next((ln for ln in out.splitlines()''',
          '''            _meta = {}
            out = stream_completion(cfg["llm"]["composer"], msgs, on_delta,
                                    meta=_meta)
            if _meta.get("finish_reason") == "length":
                # Cut off by the window rather than finished. Continue with a
                # smaller context instead of leaving a half sentence.
                continue_reply(cfg, state, mid, question, out, on_delta)
                break
            tool_line = next((ln for ln in out.splitlines()''',
          "continue a reply cut off by the window", marker="Cut off by the window rather than finished")

    # config knob
    cfgp = f"{RIFFLE}/config.yaml"
    c = open(cfgp).read()
    if "tool_char_budget" not in c:
        shutil.copy(cfgp, f"{cfgp}.bak-continue")
        open(cfgp, "w").write(c.replace(
            "  max_tool_calls: 6",
            "  max_tool_calls: 6\n"
            "  # Shared across ALL lookups in one answer. The window is 12,288\n"
            "  # tokens; leave room for the reply.\n"
            "  tool_char_budget: 9000"))
        print("  added web.tool_char_budget")
    else:
        print("  already present: tool_char_budget")

    import ast
    ast.parse(open(CHAT).read())
    print("\n  chat.py parses.")
    print("\n  Next:  sudo systemctl restart riffle-dash")


if __name__ == "__main__":
    main()
