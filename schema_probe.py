#!/usr/bin/env python3
"""Find which JSON-schema constructs this llama.cpp build can compile to GBNF.

    sudo -u riffle python3 schema_probe.py

Each probe is a minimal schema isolating one feature. A grammar parse failure
happens before any token is generated, so failures return instantly; successes
cost a second or two. The whole run is under a minute.

Why bisect instead of guess: the converter is a specific piece of C++ in a
specific build, and which keywords it handles is a property of that build, not
of JSON Schema. Reading the error text told us only that something in a
5,666-byte schema was unsupported. This tells us which thing.
"""
import json
import sys
import urllib.error
import urllib.request

URL = "http://127.0.0.1:8080/v1/chat/completions"

PROBES = [
    ("plain object",
     {"type": "object", "properties": {"a": {"type": "string"}},
      "required": ["a"], "additionalProperties": False}),

    ("enum",
     {"type": "object", "properties": {"a": {"type": "string", "enum": ["x", "y"]}},
      "required": ["a"], "additionalProperties": False}),

    ("const",
     {"type": "object", "properties": {"a": {"const": "x"}},
      "required": ["a"], "additionalProperties": False}),

    ("string minLength/maxLength",
     {"type": "object", "properties": {"a": {"type": "string", "minLength": 3,
                                             "maxLength": 40}},
      "required": ["a"], "additionalProperties": False}),

    ("integer minimum",
     {"type": "object", "properties": {"a": {"type": "integer", "minimum": 1}},
      "required": ["a"], "additionalProperties": False}),

    ("number exclusiveMinimum/maximum",
     {"type": "object", "properties": {"a": {"type": "number",
                                             "exclusiveMinimum": 0, "maximum": 1}},
      "required": ["a"], "additionalProperties": False}),

    ("union type [integer,null]",
     {"type": "object", "properties": {"a": {"type": ["integer", "null"]}},
      "required": ["a"], "additionalProperties": False}),

    ("string pattern",
     {"type": "object", "properties": {"a": {"type": "string",
                                             "pattern": "^[a-z0-9_-]{2,24}$"}},
      "required": ["a"], "additionalProperties": False}),

    ("bare object (no properties)",
     {"type": "object"}),

    ("oneOf of 2 const branches",
     {"oneOf": [
         {"type": "object", "properties": {"action": {"const": "a"},
                                           "n": {"type": "integer"}},
          "required": ["action", "n"], "additionalProperties": False},
         {"type": "object", "properties": {"action": {"const": "b"},
                                           "s": {"type": "string"}},
          "required": ["action", "s"], "additionalProperties": False}]}),

    ("anyOf of 2 const branches",
     {"anyOf": [
         {"type": "object", "properties": {"action": {"const": "a"},
                                           "n": {"type": "integer"}},
          "required": ["action", "n"], "additionalProperties": False},
         {"type": "object", "properties": {"action": {"const": "b"},
                                           "s": {"type": "string"}},
          "required": ["action", "s"], "additionalProperties": False}]}),

    ("flat: enum action + free payload",
     {"type": "object",
      "properties": {"action": {"type": "string",
                                "enum": ["post", "comment", "vote", "noop"]},
                     "payload": {"type": "object"},
                     "rationale": {"type": "string"}},
      "required": ["action", "payload", "rationale"],
      "additionalProperties": False}),
]


def try_schema(schema, timeout=90):
    body = {"messages": [{"role": "user", "content": "produce a minimal example"}],
            "max_tokens": 24,
            "response_format": {"type": "json_schema",
                                "json_schema": {"schema": schema}}}
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            out = json.loads(r.read())["choices"][0]["message"]["content"]
            return True, out.replace("\n", " ")[:70]
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read())["error"]["message"]
        except Exception:
            msg = f"HTTP {e.code}"
        return False, msg[:70]
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"[:70]


def main():
    print(f"probing {URL}\n")
    supported = []
    for name, schema in PROBES:
        ok, detail = try_schema(schema)
        print(f"  {'OK  ' if ok else 'FAIL'}  {name:<34} {detail}")
        if ok:
            supported.append(name)
    print(f"\n  {len(supported)}/{len(PROBES)} constructs supported")

    # Now the real one, to confirm the diagnosis.
    sys.path.insert(0, "/opt/riffle")
    try:
        from agent import cortex
        ok, detail = try_schema(cortex.proposal_schema())
        print(f"\n  full proposal_schema: {'OK' if ok else 'FAIL'}  {detail}")
    except Exception as e:
        print(f"\n  could not load proposal_schema: {e}")


if __name__ == "__main__":
    main()
