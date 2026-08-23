#!/usr/bin/env python3
"""Repair the constrained-decoding schema by testing candidates on THIS server.

    sudo cp schema_fix.py /opt/riffle/ && sudo chmod 644 /opt/riffle/schema_fix.py
    sudo -u riffle python3 /opt/riffle/schema_fix.py --probe     # test only
    sudo python3 /opt/riffle/schema_fix.py --install             # test, then write

WHY THE FIRST SCHEMA FAILED

Every construct it used compiles fine on its own — enum, const, oneOf, pattern,
numeric bounds, union types, all twelve probes passed. The assembled schema
still failed, which means the problem is size rather than syntax.

The suspect is string length bounds. llama.cpp converts a JSON schema into a
GBNF grammar, and `maxLength` becomes explicit repetition in that grammar.
`maxLength: 40` is a small rule; `maxLength: 8000` on a post body is an
enormous one, and eleven branches of those together exceed what the parser
will take.

So the candidates below drop length bounds and keep everything that carries
real structural information: which action names exist, which payload shape
belongs to each one, no extra fields, numeric ranges, and name patterns.

Nothing is lost by dropping them. `drives.gate` already enforces every length
limit, and did so correctly on cycle 2 when it rejected a 710-character `why`.
The grammar's job is to guarantee a COMPLETE, WELL-SHAPED object so the parser
never sees a truncated one; the gate's job is policy. Keeping length checks in
the gate and out of the grammar puts each where it works.

Candidates are tried strongest first and the first one this server accepts is
the one installed.
"""
import argparse
import json
import os
import re
import shutil
import sys
import urllib.error
import urllib.request

CORTEX = "/opt/riffle/agent/cortex.py"
URL = "http://127.0.0.1:8080/v1/chat/completions"

# Payload shapes WITHOUT string length bounds. Structure, enums, patterns and
# numeric ranges are kept; lengths live in the gate.
PAYLOADS = {
    "post": {"type": "object", "properties": {
        "title": {"type": "string"}, "body": {"type": "string"},
        "url": {"type": "string"}},
        "required": ["title", "body"], "additionalProperties": False},
    "comment": {"type": "object", "properties": {
        "post_id": {"type": "integer", "minimum": 1},
        "body": {"type": "string"},
        "parent_id": {"type": ["integer", "null"]}},
        "required": ["post_id", "body"], "additionalProperties": False},
    "vote": {"type": "object", "properties": {
        "target_type": {"type": "string", "enum": ["post", "comment"]},
        "target_id": {"type": "integer", "minimum": 1}},
        "required": ["target_type", "target_id"], "additionalProperties": False},
    "tag": {"type": "object", "properties": {
        "post_id": {"type": "integer", "minimum": 1},
        "tag": {"type": "string"}, "remove": {"type": "boolean"}},
        "required": ["post_id", "tag"], "additionalProperties": False},
    "flag": {"type": "object", "properties": {
        "target_type": {"type": "string", "enum": ["post", "comment"]},
        "target_id": {"type": "integer", "minimum": 1},
        "reason": {"type": "string"}},
        "required": ["target_type", "target_id", "reason"],
        "additionalProperties": False},
    "seal": {"type": "object", "properties": {
        "hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "label": {"type": "string"}},
        "required": ["hash", "label"], "additionalProperties": False},
    "listing_submission": {"type": "object", "properties": {
        "listing_id": {"type": "integer", "minimum": 1},
        "artifact": {"type": "string"}, "note": {"type": "string"}},
        "required": ["listing_id", "artifact", "note"],
        "additionalProperties": False},
    "adjust_drive": {"type": "object", "properties": {
        "name": {"type": "string", "pattern": "^[a-z0-9_-]{2,24}$"},
        "weight": {"type": "number", "exclusiveMinimum": 0, "maximum": 1},
        "reason": {"type": "string"}},
        "required": ["name", "weight", "reason"], "additionalProperties": False},
    "add_goal": {"type": "object", "properties": {
        "name": {"type": "string", "pattern": "^[a-z0-9_-]{2,24}$"},
        "weight": {"type": "number", "exclusiveMinimum": 0, "maximum": 1},
        "description": {"type": "string"}, "reason": {"type": "string"}},
        "required": ["name", "weight", "description", "reason"],
        "additionalProperties": False},
    "remember": {"type": "object", "properties": {
        "text": {"type": "string"}, "pinned": {"type": "boolean"}},
        "required": ["text"], "additionalProperties": False},
    "noop": {"type": "object", "properties": {"why": {"type": "string"}},
             "required": ["why"], "additionalProperties": False},
}

ACTIONS = list(PAYLOADS)


def cand_full():
    """Strongest: action and payload cannot disagree."""
    return {"oneOf": [
        {"type": "object",
         "properties": {"action": {"const": n}, "payload": p,
                        "rationale": {"type": "string"},
                        "sources": {"type": "object"}},
         "required": ["action", "payload", "rationale"],
         "additionalProperties": False}
        for n, p in PAYLOADS.items()]}


def cand_no_patterns():
    """Same, minus regex patterns, in case those are what bloats it."""
    s = json.loads(json.dumps(cand_full()))
    def strip(o):
        if isinstance(o, dict):
            o.pop("pattern", None)
            for v in o.values():
                strip(v)
        elif isinstance(o, list):
            for v in o:
                strip(v)
    strip(s)
    return s


def cand_flat():
    """Weakest useful: a complete object with a real action name.

    This cannot stop a comment payload appearing under action "vote" — the
    gate catches that — but it does make a truncated object with no action
    key impossible, which is the failure that cost a six-minute cycle.
    """
    return {"type": "object",
            "properties": {"action": {"type": "string", "enum": ACTIONS},
                           "payload": {"type": "object"},
                           "rationale": {"type": "string"},
                           "sources": {"type": "object"}},
            "required": ["action", "payload", "rationale"],
            "additionalProperties": False}


CANDIDATES = [
    ("full oneOf, no length bounds", cand_full),
    ("oneOf without regex patterns", cand_no_patterns),
    ("flat enum + free payload", cand_flat),
]


def try_schema(schema, timeout=120):
    body = {"messages": [{"role": "user",
                          "content": "Emit one minimal noop proposal."}],
            "max_tokens": 60,
            "response_format": {"type": "json_schema",
                                "json_schema": {"schema": schema}}}
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return True, json.loads(r.read())["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        try:
            return False, json.loads(e.read())["error"]["message"][:90]
        except Exception:
            return False, f"HTTP {e.code}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"[:90]


def pick():
    for label, fn in CANDIDATES:
        sch = fn()
        size = len(json.dumps(sch))
        ok, detail = try_schema(sch)
        print(f"  {'OK  ' if ok else 'FAIL'}  {label:<32} ({size:>5}b)  "
              f"{str(detail)[:60].replace(chr(10), ' ')}")
        if ok:
            return label, fn, sch
    return None, None, None


def install(label, fn):
    src = open(CORTEX).read()
    start = src.index("def proposal_schema()")
    end = src.index("\n\n", src.index("for name, payload in ACTION_PAYLOADS.items()]}"))
    new_fn = (
        'def proposal_schema():\n'
        '    """Constrained-decoding schema for one proposal.\n\n'
        '    Selected empirically against this llama.cpp build by schema_fix.py:\n'
        f'    "{label}".\n\n'
        '    String LENGTH bounds are deliberately absent. The GBNF converter\n'
        '    expands maxLength into explicit grammar repetition, and an 8000-\n'
        '    character body across eleven branches produced a grammar the parser\n'
        '    refused. Lengths are enforced by drives.gate instead, which is where\n'
        '    they belong: the grammar guarantees a complete, well-shaped object so\n'
        '    the parser never sees a truncated one, and the gate decides policy.\n'
        '    """\n'
        f'    return {json.dumps(fn(), indent=4)}\n'
    )
    shutil.copy(CORTEX, CORTEX + ".bak-schemafix")
    open(CORTEX, "w").write(src[:start] + new_fn + src[end:])
    import ast
    ast.parse(open(CORTEX).read())
    print(f"\n  installed: {label}")
    print(f"  backup: {os.path.basename(CORTEX)}.bak-schemafix")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--install", action="store_true")
    ap.add_argument("--probe", action="store_true")
    a = ap.parse_args()
    if not (a.install or a.probe):
        a.probe = True

    print(f"testing candidates against {URL}\n")
    label, fn, sch = pick()
    if not label:
        print("\n  None compiled. Roll back with:")
        print("    sudo cp /opt/riffle/agent/cortex.py.bak-schema "
              "/opt/riffle/agent/cortex.py")
        print("    sudo cp /opt/riffle/agent/cycle.py.bak-schema "
              "/opt/riffle/agent/cycle.py")
        sys.exit(1)

    if a.install:
        install(label, fn)
        print("\n  Now run a cycle:  sudo systemctl start riffle-cycle.service")
    else:
        print(f"\n  winner: {label}")
        print("  re-run with --install (as root) to write it in")


if __name__ == "__main__":
    main()
