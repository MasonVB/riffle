"""Replay riffle's last cycle request against another model server.

    cd /opt/riffle && sudo -u riffle python3 -m agent.trial \\
        --url http://127.0.0.1:8082 --effort none,low,medium

WHY IT EXISTS (2026-11-28). The operator decided to move the composer to a
larger model with thinking on (Qwen3.8-27B). Two things could not be known
from benchmarks: whether riffle's JSON form lets the model think before it
answers on this llama.cpp build, or takes over from the first token; and how
many tokens of thinking one real decision takes at about one token a second.
This sends the exact request the last cycle sent (cortex.LAST_CYCLE_REQUEST,
saved as <data_dir>/last-cycle-request.json) to a server the operator started
by hand, once per effort, and says what came back.

It only reads. It touches no state, sends nothing to the registry, and the
live composer is not asked. The efforts run one after another on one server,
so the second and later reuse the first one's prompt cache and cost only
their writing.

For each effort it prints:
  - the time taken, the prompt tokens read and those taken from the cache,
    the tokens written, and the speeds the server measured;
  - how much came back as thinking and how much as the answer (an effort
    other than none that brings back no thinking means the JSON form took
    over from the first token);
  - whether the answer is a JSON object with an action (with --no-json-form,
    whether the model kept to JSON without the form making it), and the action,
    rationale and payload, so the decision can be read beside the one the
    live model made.
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.request

import yaml

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EFFORTS = ("none", "low", "medium", "high", "xhigh")


def request_path(config):
    try:
        cfg = yaml.safe_load(open(config)) or {}
    except OSError:
        cfg = {}
    data = os.path.expanduser(cfg.get("data_dir") or "/var/lib/riffle")
    return os.path.join(data, "last-cycle-request.json")


def body_for(saved, effort, max_tokens, json_form=True):
    """The saved request with this effort's thinking switch and token ceiling,
    and without its JSON form if json_form is False."""
    body = json.loads(json.dumps(saved["body"]))
    if not json_form:
        body.pop("response_format", None)
    body["max_tokens"] = int(max_tokens)
    body["cache_prompt"] = True
    kw = {"enable_thinking": effort != "none"}
    if effort != "none":
        kw["reasoning_effort"] = effort
    body["chat_template_kwargs"] = kw
    # Thinking returned apart from the answer, where the server can.
    body["reasoning_format"] = "deepseek"
    return body


def post(url, body, timeout):
    req = urllib.request.Request(url.rstrip("/") + "/v1/chat/completions",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def split_answer(msg):
    """(thinking, answer) from a chat message, whether the server split them
    or left a <think> block in the content."""
    thinking = msg.get("reasoning_content") or ""
    answer = msg.get("content") or ""
    m = re.match(r"(?s)\s*<think>(.*?)</think>\s*(.*)", answer)
    if m:
        thinking, answer = (thinking + m.group(1)), m.group(2)
    return thinking, answer


def judge(answer):
    """What the answer is: a JSON object with an action, or why not."""
    try:
        j = json.loads(answer)
    except ValueError as e:
        return None, f"not JSON ({e})"
    if not isinstance(j, dict) or "action" not in j:
        return None, "JSON, but no 'action'"
    return j, "yes"


def report(effort, out, wall):
    ch = (out.get("choices") or [{}])[0]
    msg = ch.get("message") or {}
    thinking, answer = split_answer(msg)
    u, t = out.get("usage") or {}, out.get("timings") or {}
    read = t.get("prompt_n", u.get("prompt_tokens"))
    cached = t.get("cache_n")
    wrote = u.get("completion_tokens", t.get("predicted_n"))
    lines = [f"== effort {effort}",
             f"  took {wall:,.0f} s | prompt read {read} tokens"
             + (f" (from cache {cached})" if cached is not None else "")
             + (f" at {t['prompt_per_second']:.2f} tok/s" if t.get("prompt_per_second") else "")
             + f" | wrote {wrote} tokens"
             + (f" at {t['predicted_per_second']:.2f} tok/s" if t.get("predicted_per_second") else "")
             + f" | finish {ch.get('finish_reason')}",
             f"  thinking {len(thinking):,} chars | answer {len(answer):,} chars"]
    if effort != "none" and not thinking.strip():
        lines.append("  NO THINKING CAME BACK: the JSON form took over from the first "
                     "token, or the template ignored the switch")
    j, why = judge(answer)
    lines.append(f"  answer is a proposal: {why}")
    if j:
        lines.append(f"  action: {j.get('action')}")
        lines.append(f"  rationale: {' '.join(str(j.get('rationale') or '').split())[:600]}")
        lines.append(f"  payload: {json.dumps(j.get('payload'), ensure_ascii=False)[:900]}")
    else:
        lines.append(f"  answer begins: {answer[:300]!r}")
    if thinking.strip():
        lines.append(f"  thinking ends: {' '.join(thinking.split())[-400:]!r}")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--url", required=True, help="the trial server, e.g. http://127.0.0.1:8082")
    ap.add_argument("--effort", default="none,low",
                    help=f"comma-separated, from {', '.join(EFFORTS)}")
    ap.add_argument("--max-tokens", type=int, default=16000)
    ap.add_argument("--timeout", type=int, default=6 * 3600, help="seconds per effort")
    ap.add_argument("--config", default=os.path.join(HERE, "config.yaml"))
    ap.add_argument("--request", help="a saved request (default: the data dir's)")
    ap.add_argument("--no-json-form", action="store_true",
                    help="send without riffle's JSON form, to see whether the form is "
                         "what stops the thinking")
    a = ap.parse_args(argv)
    efforts = [e.strip() for e in a.effort.split(",") if e.strip()]
    bad = [e for e in efforts if e not in EFFORTS]
    if bad or not efforts:
        sys.exit(f"trial: unknown effort {bad or a.effort!r}; use {', '.join(EFFORTS)}")
    path = a.request or request_path(a.config)
    try:
        saved = json.load(open(path))
    except (OSError, ValueError) as e:
        sys.exit(f"trial: no saved request at {path} ({e}). A cycle that reaches "
                 f"the composer writes it; wait for one.")
    msgs = saved["body"].get("messages") or []
    print(f"request: from the cycle at {saved.get('at')}, sent to {saved.get('url')}; "
          f"{sum(len(m.get('content') or '') for m in msgs):,} chars in {len(msgs)} messages; "
          f"JSON form: {'yes' if saved['body'].get('response_format') else 'no'}")
    print(f"trial server: {a.url}; efforts {', '.join(efforts)}; max_tokens {a.max_tokens}"
          + ("; sent WITHOUT the JSON form" if a.no_json_form else ""))
    sys.stdout.flush()
    for e in efforts:
        t0 = time.monotonic()
        try:
            out = post(a.url, body_for(saved, e, a.max_tokens, not a.no_json_form), a.timeout)
        except Exception as ex:
            print(f"== effort {e}\n  failed after {time.monotonic() - t0:,.0f} s: "
                  f"{type(ex).__name__}: {str(ex)[:300]}")
            sys.stdout.flush()
            continue
        print(report(e, out, time.monotonic() - t0))
        sys.stdout.flush()


if __name__ == "__main__":
    main()
