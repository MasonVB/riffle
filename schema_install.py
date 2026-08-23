#!/usr/bin/env python3
"""Install the working schema, without fragile source-splicing.

    sudo python3 /opt/riffle/schema_install.py

The previous installer tried to find the old function by matching a literal
string in the file, and lost because pprint had reformatted that string when
the first patch wrote it. Rewriting source by string-matching source is how
that goes.

So this does not rewrite the function body at all. It writes the schema to
/opt/riffle/proposal_schema.json and replaces proposal_schema() with a version
that reads it. Editing the schema afterwards is then a JSON edit rather than a
Python patch, which is what it should have been from the start.

The regex below matches from `def proposal_schema():` to the next top-level
`def` or end of file, and refuses to run if it does not match exactly once.
"""
import json
import os
import re
import shutil
import sys

CORTEX = "/opt/riffle/agent/cortex.py"
SCHEMA_JSON = "/opt/riffle/proposal_schema.json"

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

SCHEMA = {"oneOf": [
    {"type": "object",
     "properties": {"action": {"const": n}, "payload": p,
                    "rationale": {"type": "string"},
                    "sources": {"type": "object"}},
     "required": ["action", "payload", "rationale"],
     "additionalProperties": False}
    for n, p in PAYLOADS.items()]}

NEW_FN = '''def proposal_schema():
    """Constrained-decoding schema for one proposal, loaded from JSON.

    Kept in /opt/riffle/proposal_schema.json rather than inline, so changing
    it is a JSON edit rather than a Python patch.

    String LENGTH bounds are deliberately absent. llama.cpp expands maxLength
    into explicit repetition in the generated grammar, and an 8000-character
    body across eleven branches produced a grammar its parser refused. Every
    construct here compiled individually; the assembled one did not, and the
    lengths were the difference.

    Lengths, caps, locks and drive restrictions live in drives.gate, which is
    the right split: the grammar guarantees a COMPLETE, WELL-SHAPED object so
    the parser never sees a truncated one, and the gate decides policy. The
    first attempt had the two overlapping, and the overlap is what broke it.

    Neither makes the content TRUE. A schema-valid comment can still carry the
    wrong post_id under a fluent rationale.
    """
    import json as _json
    import os as _os
    _p = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
                       "proposal_schema.json")
    with open(_p) as _f:
        return _json.load(_f)
'''

PAT = re.compile(r"^def proposal_schema\(\):.*?(?=^def |\Z)", re.S | re.M)


def main():
    if not os.path.exists(CORTEX):
        sys.exit(f"{CORTEX} not found")
    src = open(CORTEX).read()

    n = len(PAT.findall(src))
    if n != 1:
        sys.exit(f"expected exactly one proposal_schema() in {CORTEX}, found {n}. "
                 f"Nothing changed.")

    with open(SCHEMA_JSON, "w") as f:
        json.dump(SCHEMA, f, indent=1)
    os.chmod(SCHEMA_JSON, 0o644)
    print(f"  wrote {SCHEMA_JSON} ({len(json.dumps(SCHEMA))} bytes, "
          f"{len(SCHEMA['oneOf'])} branches)")

    shutil.copy(CORTEX, CORTEX + ".bak-install")
    open(CORTEX, "w").write(PAT.sub(NEW_FN + "\n\n", src, count=1))

    import ast
    ast.parse(open(CORTEX).read())
    print(f"  rewrote proposal_schema() in cortex.py "
          f"(backup: {os.path.basename(CORTEX)}.bak-install)")

    sys.path.insert(0, "/opt/riffle")
    from agent import cortex
    got = cortex.proposal_schema()
    assert got == SCHEMA, "loaded schema does not match what was written"
    print(f"  verified: cortex.proposal_schema() loads {len(got['oneOf'])} branches "
          f"from disk")
    print("\n  Now:  sudo systemctl start riffle-cycle.service")


if __name__ == "__main__":
    main()
