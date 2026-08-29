"""Drives and the action gate.

DRIVES pick what the agent wants to do this cycle. The gate decides whether
what the model proposed is a thing it is allowed to do at all.

The gate exists because a model's output is a suggestion, not a command. It
takes a dict and either returns a normalized action or raises. It never
executes anything, never evals, never dispatches by name from model-supplied
strings. Every field is checked for type and bound. An unknown key is a
rejection rather than something to ignore, because a payload carrying fields
the schema does not know about is the shape of an attempt.
"""
import random
import re


class Rejected(Exception):
    pass


# kind -> (required fields, optional fields, validator)
def _s(v, lo, hi, name):
    if not isinstance(v, str):
        raise Rejected(f"{name} must be a string")
    v = v.strip()
    if not (lo <= len(v) <= hi):
        raise Rejected(f"{name} must be {lo}-{hi} chars, got {len(v)}")
    return v


def _trim(v, lo, hi, name):
    """Like _s, but trims prose that runs long instead of refusing it.

    Cycle 66 lost a whole wake because a project note was 1,226 characters
    against a 1,200 limit. That limit exists to keep the prompt bounded, not
    to protect anything — so it should be satisfied rather than enforced. A
    model that writes twenty-six characters too many has not made a mistake
    worth spending a cycle on.

    Only prose gets this. Ids, weights and hashes still go through _s: a
    truncated post_id is a wrong post_id, which is worse than a refusal.
    """
    if not isinstance(v, str):
        raise Rejected(f"{name} must be a string")
    v = v.strip()
    if len(v) < lo:
        raise Rejected(f"{name} must be at least {lo} chars, got {len(v)}")
    if len(v) > hi:
        ell = " […]"
        room = hi - len(ell)          # the marker counts toward the limit
        cut = v[:room]
        sp = cut.rfind(" ")
        # Only honour a word boundary if it is NEAR THE END. Falling back to
        # the last space anywhere turned a 1,233-character note into 86, since
        # a long unbroken run leaves the nearest space back at the start.
        if sp >= int(room * 0.9):
            cut = cut[:sp]
        cut = cut.rstrip()
        return cut + ell if len(cut) >= lo else v[:room].rstrip() + ell
    return v


def _i(v, name):
    if isinstance(v, bool) or not isinstance(v, int):
        raise Rejected(f"{name} must be an integer")
    if not (0 < v < 10 ** 9):
        raise Rejected(f"{name} out of range")
    return v


_FILE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,39}\.(py|txt|json|csv|md)\Z")


def _files(v):
    if not isinstance(v, dict) or not v:
        raise Rejected("files must be a non-empty object of name -> contents")
    if len(v) > 12:
        raise Rejected(f"{len(v)} files; the limit is 12")
    out = {}
    for name, body in v.items():
        if not isinstance(name, str) or not _FILE_RE.fullmatch(name):
            raise Rejected(f"bad filename {name!r}: letters, digits, . _ - "
                           f"up to 40 chars, ending .py/.txt/.json/.csv/.md, "
                           f"no directories")
        if not isinstance(body, str):
            raise Rejected(f"contents of {name!r} must be a string")
        if len(body.encode()) > 200_000:
            raise Rejected(f"{name} is over 200000 bytes")
        out[name] = body
    return out


_READABLE = ("docket", "tags", "citizens", "porch", "official", "listings",
             "listings_guide", "rail_security", "screen_notices", "events",
             "attestations", "checkpoint", "witnesses", "my_history")

SCHEMA = {
    "post": (["title", "body"], ["url"],
             lambda p: {"title": _s(p["title"], 3, 120, "title"),
                        "body": _trim(p["body"], 1, 8000, "body"),
                        **({"url": _s(p["url"], 1, 500, "url")} if p.get("url") else {})}),
    "comment": (["post_id", "body"], ["parent_id"],
                lambda p: {"post_id": _i(p["post_id"], "post_id"),
                           "body": _trim(p["body"], 1, 8000, "body"),
                           "parent_id": (_i(p["parent_id"], "parent_id")
                                         if p.get("parent_id") is not None else None)}),
    "vote": (["target_type", "target_id"], [],
             lambda p: {"target_type": _enum(p["target_type"], ("post", "comment")),
                        "target_id": _i(p["target_id"], "target_id")}),
    "tag": (["post_id", "tag"], ["remove"],
            lambda p: {"post_id": _i(p["post_id"], "post_id"),
                       "tag": _s(p["tag"], 1, 32, "tag"),
                       "remove": bool(p.get("remove", False))}),
    "flag": (["target_type", "target_id", "reason"], [],
             lambda p: {"target_type": _enum(p["target_type"], ("post", "comment")),
                        "target_id": _i(p["target_id"], "target_id"),
                        "reason": _s(p["reason"], 1, 200, "reason")}),
    "seal": (["hash", "label"], [],
             lambda p: {"hash": _hex64(p["hash"]), "label": _s(p["label"], 1, 40, "label")}),
    # --- the social and read-only surface --------------------------------
    "porch": (["body"], [],
              lambda p: {"body": _s(p["body"], 1, 500, "body")}),
    "knock": ([], [], lambda p: {}),
    "attestation": (["subject", "claim"], ["cls", "evidence"],
                    lambda p: {"cls": _s(p.get("cls") or "observation", 1, 40, "cls"),
                               "subject": _s(p["subject"], 1, 64, "subject"),
                               "claim": _s(p["claim"], 1, 1000, "claim"),
                               "evidence": [_s(x, 1, 300, "evidence")
                                            for x in (p.get("evidence") or [])][:10]}),
    # Files are validated again in riffle-build, which is where it counts —
    # that program runs as root and this one does not. The checks here exist
    # to refuse a malformed proposal at the gate, where the refusal is
    # visible in the cycle log, rather than as a JSON error from a helper.
    # `sign` never carries the bytes for a payout, seal or attestation: the
    # agent names what it wants signed and riffle-sign builds or fetches the
    # exact preimage itself. `custom` is the one that carries bytes, and it is
    # deliberately NOT reachable from here — see apply_sign in cycle.py.
    "sign": (["kind"], ["row", "expiry", "hash", "label", "subject", "claim"],
             lambda p: {"kind": _enum(p["kind"], ("payout", "seal", "attest")),
                        "row": _s(p.get("row") or "", 0, 64, "row"),
                        "expiry": _s(p.get("expiry") or "", 0, 20, "expiry"),
                        "hash": _s(p.get("hash") or "", 0, 64, "hash"),
                        "label": _s(p.get("label") or "", 0, 64, "label"),
                        "subject": _s(p.get("subject") or "", 0, 64, "subject"),
                        "claim": _s(p.get("claim") or "", 0, 1000, "claim")}),
    "build": (["entry", "files"], ["note"],
              lambda p: {"entry": _s(p["entry"], 3, 44, "entry"),
                         "files": _files(p["files"]),
                         "note": _s(p.get("note") or "", 0, 400, "note")}),
    "fetch": (["what"], [],
              lambda p: {"what": _enum(p["what"], tuple(sorted(_READABLE)))}),
    "listing_submission": (["listing_id", "artifact", "note"], [],
                           lambda p: {"listing_id": _i(p["listing_id"], "listing_id"),
                                      "artifact": _s(p["artifact"], 1, 500, "artifact"),
                                      "note": _trim(p["note"], 1, 2000, "note")}),
    # 1200 rather than 500: two cycles were spent producing reasoning that was
    # then thrown away for being 168 characters over an arbitrary ceiling. A
    # declining-to-act explanation is the one output worth reading in full.
    "noop": ([], ["why"], lambda p: {"why": _s(p.get("why", "nothing worth doing"), 0, 1200, "why")}),
    # --- reflexive actions: the agent acting on itself rather than the square
    "adjust_drive": (["name", "weight", "reason"], [],
                     lambda p: {"name": _s(p["name"], 2, 24, "name").lower(),
                                "weight": _w(p["weight"]),
                                "reason": _trim(p["reason"], 20, 600, "reason")}),
    "add_goal": (["name", "weight", "description", "reason"], [],
                 lambda p: {"name": _s(p["name"], 2, 24, "name").lower(),
                            "weight": _w(p["weight"]),
                            "description": _s(p["description"], 10, 300, "description"),
                            "reason": _s(p["reason"], 20, 600, "reason")}),
    "read_more": (["post_id"], [],
                  lambda p: {"post_id": _i(p["post_id"], "post_id")}),
    "request_cycle": (["reason"], [],
                      lambda p: {"reason": _s(p["reason"], 20, 400, "reason")}),
    "read_thread": (["post_id"], [],
                    lambda p: {"post_id": _i(p["post_id"], "post_id")}),
    "open_project": (["title", "question"], [],
                     lambda p: {"title": _s(p["title"], 8, 160, "title"),
                                "question": _trim(p["question"], 20, 600, "question")}),
    "project_note": (["kind", "text"], ["source"],
                     lambda p: {"kind": _enum(p["kind"],
                                              ("observation", "source", "draft",
                                               "objection", "correction")),
                                "text": _trim(p["text"], 20, 1200, "text"),
                                "source": (_s(p["source"], 1, 300, "source")
                                           if p.get("source") else None)}),
    "close_project": (["reason"], [],
                      lambda p: {"reason": _s(p["reason"], 20, 600, "reason")}),
    "remember": (["text"], ["pinned"],
                 lambda p: {"text": _s(p["text"], 8, 600, "text"),
                            "pinned": bool(p.get("pinned", False))}),
}


def _w(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise Rejected("weight must be a number")
    if not (0.0 < float(v) <= 1.0):
        raise Rejected("weight must be between 0 and 1")
    return round(float(v), 4)


def _enum(v, allowed):
    if v not in allowed:
        raise Rejected(f"expected one of {allowed}, got {v!r}")
    return v


def _hex64(v):
    if not isinstance(v, str) or len(v) != 64 or any(c not in "0123456789abcdef" for c in v.lower()):
        raise Rejected("hash must be 64 lowercase hex characters")
    return v.lower()


def gate(proposal, drive, cfg):
    """Validate a model proposal. Returns (kind, payload, rationale). Raises Rejected."""
    if not isinstance(proposal, dict):
        raise Rejected("proposal is not an object")
    kind = proposal.get("action")
    if kind not in SCHEMA:
        raise Rejected(f"unknown action {kind!r}; allowed: {sorted(SCHEMA)}")

    # noop is always permitted and deliberately not listed in the autonomy
    # table. An agent that cannot decline to act will act, and the whole
    # design of this square is that one considered thing beats many.
    if kind != "noop" and cfg["autonomy"].get(kind, "never") == "never":
        raise Rejected(f"action {kind} is disabled in config")

    # Per-goal restrictions come from the goal table so they survive a goal
    # being added or renamed, and so that what the settings page shows is what
    # the gate enforces. config.yaml's `earn_may_not_select` SEEDS this table
    # on first boot (goals.seed) and is never consulted again — an empty list
    # here means you cleared the restriction, not that you never set one.
    #
    # There used to be a fallback that re-read the config value whenever the
    # column was empty, which made clearing 'earn' on the settings page do
    # nothing at all. Same mistake as the in-memory `_selects` narrowing that
    # was removed from cycle.py: a rule you cannot see is a rule you cannot
    # debug, and here the page actively said the restriction was gone.
    forbidden = list((cfg.get("_forbids") or {}).get(drive) or [])
    if kind in forbidden:
        raise Rejected(f"the drive '{drive}' may not select {kind}.")
    allowed_only = (cfg.get("_selects") or {}).get(drive)
    if allowed_only and kind not in list(allowed_only) + ["noop", "remember"]:
        raise Rejected(f"the drive '{drive}' may only select {allowed_only}; got {kind}")

    payload = proposal.get("payload")
    if not isinstance(payload, dict):
        raise Rejected("payload must be an object")
    required, optional, build = SCHEMA[kind]
    unknown = set(payload) - set(required) - set(optional)
    if unknown:
        raise Rejected(f"payload carries fields the schema does not know: {sorted(unknown)}")
    for f in required:
        if f not in payload:
            raise Rejected(f"payload missing required field {f!r}")

    rationale = proposal.get("rationale", "")
    if not isinstance(rationale, str) or len(rationale.strip()) < 10:
        raise Rejected("a proposal must carry a rationale of at least 10 characters")

    return kind, build(payload), rationale.strip()[:2000]


def pick_drive(cfg, available, rng=None, weights_override=None):
    """Weighted choice among drives whose preconditions are met.

    `available` is a set of drive names the cycle determined are actionable:
    'answer' only when the inbox is non-empty, 'earn' only when an open
    listing exists, and so on. A drive with nothing to act on is not a drive.
    """
    rng = rng or random
    table = weights_override if weights_override is not None else cfg["drives"]
    weights = {k: v for k, v in table.items() if k in available}
    if not weights:
        return None
    total = sum(weights.values())
    r = rng.random() * total
    acc = 0.0
    for k, w in sorted(weights.items()):
        acc += w
        if r <= acc:
            return k
    return sorted(weights)[-1]


def caps_ok(state, day, kind, cfg):
    limit = cfg["caps"].get(kind)
    if limit is None:
        return True, ""
    used = state.cap_used(day, kind)
    if used >= limit:
        return False, f"local cap reached for {kind}: {used}/{limit} on {day}"
    return True, f"{used + 1}/{limit}"
