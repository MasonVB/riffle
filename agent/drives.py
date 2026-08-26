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
    # being added or renamed. 'earn' ships forbidding every social act: the
    # listings rail pays only for verifiable work, never for a post, comment,
    # vote, flag or tag, and wanting money must not be what selects one.
    forbidden = list((cfg.get("_forbids") or {}).get(drive) or [])
    if drive == "earn" and not forbidden:
        forbidden = list((cfg.get("constraints") or {}).get("earn_may_not_select", []))
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
