"""What riffle may say in public: the checks from the communications audit.

The audit of 2026-11-20 (audits/AUDIT-COMMUNICATIONS-2026-11-20.md) read
every word riffle sent over four days. These are the things it found that a
check can catch. Each is a function that returns why the action may not go,
or None, and check() runs them in order. The cycle runs check() before it
queues or sends; the dashboard runs it again when you approve, since a queued
action can wait for hours and the record changes under it (a second
submission to the same listing went out two seconds after the first).

THE PRINCIPLE (the operator, 2026-11-20): riffle's library is on this
machine. Nobody reading the square can open it, and the square takes text
only: there is no attaching a file and no editing a post. So a hash or a
library number of riffle's own file proves nothing to a reader unless the
file itself is in what they can read. Every check about libraries, hashes
and artifacts follows from that.

  declaration-orphan   a [[...]] that does not follow the figure it computes
                       (riffle copied the prompt's example, [[3/8*100]], into
                       a post four times). A valid one is sent as plain
                       arithmetic, by finish().
  library-private      "library #N", "my library", "the library entry": a
                       reader cannot open any of them.
  hash-wrong-file      a hash named beside a file it is not the hash of
                       (b74ff0d9d5 is solve.py; riffle called it
                       regime_test.py, twice).
  hash-unpublished     a hash of riffle's own file, when the file is in
                       neither this text nor a post of riffle's it links.
  post-cannot-change   "I will correct the post": posts cannot be edited.
  claim-unbacked       "I have updated my notes / corrected the draft" with
                       no such action in the last six hours.
  wrong-addressee      a reply opening "Name:" or "Name (cN):" when its
                       parent was written by someone else, or is not cN.
  voted-unread         a vote on a post or comment riffle has not read.
  listing-submitted    a second submission to a listing, sent or waiting.
  artifact-not-a-post  a listing artifact that is not a post riffle sent.
  project-repeat       a post that says what a post from the same project
                       already said (the operator: several posts per project
                       are fine "if the posts are substantially different and
                       communicating different ideas").
  post-claimed         "I am posting it … the post is #13370" with no post
                       sent or queued, or a post number that is not riffle's
                       (2026-11-24).
  credited             a reply crediting its addressee with a number, or a
                       finding, their comment does not carry ("the
                       suppression rate you observed", 2026-11-24).
  misread              a reply the triage model, reading it beside the comment
                       it answers, finds misstates what that comment said
                       (second_read; run by the cycle, not by check(): it
                       costs a model call).
  claimed-before       "the same six I flagged earlier" when nothing riffle
                       sent in 30 days says so (2026-11-26).
  figure-assumed       a rate a simulation of riffle's printed after being
                       given it: `random() < 0.718`, reported as "71.7%
                       suppression in simulation" (2026-11-24).

And for the number check: public_build_outputs() is what riffle's builds
printed, for each build a reader can see; build_route() is what riffle is
told about a figure one of its builds printed that it has not yet shown.

And invented_instruction(), for a rationale that says the operator told
riffle to do something no record of his says (action 3762: "The operator has
instructed to focus on Listing 65". He had not).

WHAT THESE CANNOT DO, said here and in AUDIT-RESPONSE section 23:
  - wrong-addressee sees only the opening "Name:" form. A reply that answers
    the wrong point without naming anyone, or answers as if riffle were the
    person addressed (actions 3973, 3991), is not caught.
  - claim-unbacked knows notes, drafts, the desk, the library and memory.
    Promises of future work ("I will run this") are not refused: some are
    kept, and nothing can tell which in advance.
  - invented_instruction compares numbers and words with what the operator
    has written; a claim that shares them with something he said about
    something else passes.
  - Misreporting another citizen's data (section 3.2 of the audit) is not
    checked at all. It needs reading comprehension, not a pattern. It
    happened again on 2026-11-24 (action 4345 credited swift-lantern with "the
    suppression rate you observed"; that comment had no such rate).
  - figure-assumed knows a rate set with random() compared to a number,
    binomial/bernoulli/choices, or a name assigned one in the file. A rate
    computed from other inputs, read from a file, or set by a distribution
    with another name is not seen; nor is a figure riffle states without
    naming or showing the build.
  - post-claimed knows the present ("I am posting", "I have posted") and
    "my post is #N". "As I posted earlier" passes.
"""
import datetime as dt
import json
import os
import re

# ------------------------------------------------------------------ helpers

TEXT_FIELDS = {
    "post": ("title", "body"),
    "comment": ("body",),
    "porch": ("body",),
    "listing_submission": ("artifact", "note"),
    "attestation": ("claim", "evidence"),
    "seal": ("label",),
    "flag": ("reason",),
}

DECL_RE = re.compile(r"\[\[([^\]\n]+)\]\]")
# numcheck reads a declaration as the derivation of the figure that ends at
# most three characters before it ("37.5% [[...]]": the % and a space).
_FIGURE_BEFORE = re.compile(r"\d[^\w\[\]\n]{0,3}$")

LIBRARY_RE = re.compile(
    r"\blibrary\s*(?:#|no\.?\s*|id\s*#?\s*|entry\s*#?\s*|doc(?:ument)?\s*#?\s*)\s*\d+"
    r"|\bmy\s+library\b"
    r"|\blibrary\s+(?:entry|entries|document|documents|doc|docs|id|ids)\b",
    re.I)

HEX_RE = re.compile(r"(?<![0-9A-Za-z])([0-9a-fA-F]{7,64})(?![0-9A-Za-z])")
FILE_RE = re.compile(r"(?<![\w/.-])([\w-]+\.(?:py|sh|js|ts|c|h|go|rs|txt|json|csv|md))\b")

EDIT_POST_RE = re.compile(
    r"\bI(?:'ll|\s+will|\s+shall|\s+am\s+going\s+to|\s+plan\s+to)\s+(?:now\s+|also\s+|soon\s+)?"
    r"(?:correct|edit|update|amend|revise|fix|change|rewrite)\s+(?:the|my|this|that)\s+"
    r"(?:original\s+)?post\b(?!\s*(?:count|id|number|clock|cap|limit|allowance))"
    r"|\bI(?:'ve|\s+have)\s+(?:now\s+|already\s+|just\s+)?"
    r"(?:corrected|edited|updated|amended|revised|fixed|changed|rewritten)\s+"
    r"(?:the|my|this|that)\s+(?:original\s+)?post\b"
    r"|\b(?:the|my)\s+post\s+(?:has\s+been|is\s+now|was)\s+(?:corrected|edited|updated|amended|revised|fixed)\b",
    re.I)

CLAIM_RE = re.compile(
    r"\bI(?:'ve|\s+have)\s+(?:now\s+|just\s+|already\s+|also\s+)?"
    r"(?:updated|corrected|revised|amended|added|recorded|noted|logged|saved|"
    r"filed|shelved|written|put|stored|changed)\b"
    r"[^.!?\n]{0,60}?\b(notes?|draft|desk|library|memory|memories)\b",
    re.I)
# What each noun says was done, and the actions that would have done it.
_CLAIM_KINDS = {
    "note": ("project_note", "remember"), "notes": ("project_note", "remember"),
    "draft": ("desk_put", "project_note"), "desk": ("desk_put", "desk_clear"),
    "library": ("library_put", "build"),
    "memory": ("remember",), "memories": ("remember",),
}
CLAIM_HOURS = 6

# A reply opening "Name:", "@Name,", "Name (c149881):" or "Name —".
OPENING_RE = re.compile(
    r"\s*@?([A-Za-z0-9][\w.\-]{1,39})\s*(?:\(\s*c?(\d+)\s*\))?\s*[:,—–]")

_OPERATOR_RE = re.compile(
    r"\b(?:the|my|your|our)\s+operator(?:'s)?\b[^.;!?\n]{0,60}?"
    r"\b(?:instructed|instructs|instruction|directed|directs|direction|told|"
    r"asked|asks|wants|wanted|requested|request|ordered)\b"
    r"|\b(?:instructed|directed|told|asked|requested|ordered)\s+(?:to\s+\w+\s+)?by\s+"
    r"(?:the|my|your|our)\s+operator\b",
    re.I)
_STOP = set("""operator operators instructed instructs instruction directed directs
direction told asked asks wants wanted requested request ordered explicitly
that this with from have has been will would should could which their there
them they then than into about after before your mine also only just some
more most such what when where while were being does done make made more
over under again here very much many each other these those first second
focus on the and for are was not but you""".split())

OPERATOR_DAYS = 30


def _norm(t):
    return " ".join(str(t or "").split())


def _words(t):
    return frozenset(w for w in re.findall(r"[a-z0-9]+", (t or "").lower()) if len(w) > 3)


def _overlap(a, b):
    A, B = _words(a), _words(b)
    if not A or not B:
        return 0.0
    return len(A & B) / max(len(A), len(B))


def _tables(state):
    try:
        return {r[0] for r in state.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    except Exception:
        return set()


def public_text(kind, payload):
    """Everything in this action that a reader on the square will see."""
    out = []
    for f in TEXT_FIELDS.get(kind, ()):
        v = (payload or {}).get(f)
        if isinstance(v, list):
            out.extend(str(x) for x in v)
        elif v:
            out.append(str(v))
    return "\n".join(out)


def _lib_root(cfg):
    from agent import library
    return ((cfg or {}).get("library") or {}).get("root", library.ROOT)


def _docs_for(state, h):
    """Library documents whose sha256 starts with h."""
    try:
        return state.db.execute(
            "SELECT id, title, kind, source, path, sha256, bytes FROM library"
            " WHERE sha256 LIKE ? ORDER BY id DESC LIMIT 20",
            (h.lower() + "%",)).fetchall()
    except Exception:
        return []


def _doc_name(row):
    """The file a library document is: 'solve.py' for a build file titled
    'solve.py — note', and for its output, 'output of solve.py — note'."""
    t = str(row["title"] or "")
    head = t.split(" — ")[0].strip()
    m = re.match(r"output of (\S+)", head)
    return (m.group(1) if m else head).lower()


def doc_label(row):
    """What a library document is, in words a reader can use: 'solve.py', or
    'output of solve.py'."""
    return str(row["title"] or "").split(" \u2014 ")[0].strip()


def _doc_text(cfg, row):
    try:
        with open(os.path.join(_lib_root(cfg), row["path"]), "rb") as f:
            return f.read().decode("utf-8", "replace")
    except OSError:
        return None


def my_posts(state):
    """{post_id: body} for every post riffle sent."""
    out = {}
    try:
        for r in state.db.execute(
                "SELECT payload, response FROM actions WHERE kind='post'"
                " AND status IN ('executed','sent','unknown') AND json_valid(response)"):
            try:
                n = (json.loads(r["response"]) or {}).get("post_id")
                if n is not None:
                    out[int(n)] = (json.loads(r["payload"] or "{}") or {}).get("body") or ""
            except (ValueError, TypeError, AttributeError):
                continue
    except Exception:
        pass
    return out


def published_in(state, cfg, row, text="", posts=None):
    """Where a reader can see library document `row`: 'here' (in text),
    'post N' (in a post riffle sent), its own URL, or None."""
    body = _doc_text(cfg, row)
    src = str(row["source"] or "")
    if src.startswith("http") and src in (text or ""):
        return src
    if body is None or not _norm(body):
        return None
    nb = _norm(body)

    def carries(t):
        # A short document ("49", "drift ok") is inside almost any text by
        # chance: it counts only as a line of its own.
        if len(nb) < 20:
            return any(_norm(ln) == nb for ln in str(t or "").splitlines())
        return nb in _norm(t)
    if carries(text):
        return "here"
    posts = my_posts(state) if posts is None else posts
    for pid, pb in sorted(posts.items(), reverse=True):
        if carries(pb):
            return f"post {pid}"
    return None


FENCE_RE = re.compile(r"(?ms)^[ \t]*(```|~~~~)[^\n]*\n(.*?)^[ \t]*\1[ \t]*$")


def mask_published_code(state, text):
    """text with each fenced code block that is, byte for byte, a file one of
    riffle's builds shelved (or a build's output), blanked out (line count kept, so the number
    check's line numbers still match). Its literals are code, not figures,
    and the file is what the reader is being given to check. A block that is
    anything else, an output pasted by hand included, is left for the check."""
    import hashlib

    def one(m):
        body = m.group(2).replace("\r\n", "\n")
        cands = {body, body.rstrip("\n") + "\n", body.rstrip("\n")}
        for c in cands:
            h = hashlib.sha256(c.encode("utf-8")).hexdigest()
            try:
                if state.db.execute(
                        "SELECT 1 FROM library WHERE sha256=? AND kind IN ('code','data')"
                        " AND source LIKE 'build:%' LIMIT 1", (h,)).fetchone():
                    return "\n" * m.group(0).count("\n")
            except Exception:
                return m.group(0)
        return m.group(0)
    return FENCE_RE.sub(one, text or "")


def outside_fences(text):
    """text with every fenced code block's contents blanked, lines kept."""
    return FENCE_RE.sub(lambda m: "\n" * m.group(0).count("\n"), text or "")


def post_url(cfg, pid):
    return f"{((cfg or {}).get('base') or 'https://1f916.ai').rstrip('/')}/api/post/{pid}"


# ------------------------------------------- attaching, and the ways to cite
#
# The square takes text only. So an attachment is text at the end of the
# post: riffle names its build files in "append", and attach() puts each one
# there in full, byte for byte, under its name and sha256. A reader can copy
# it, hash it and run it, and the number check knows the block for the file
# it is (mask_published_code). The operator, 2026-11-21: riffle should be
# able to "provide evidence even if the attachment is just appended text on
# the post", and a citation that cannot go should come back with the ways it
# can, not a bare refusal. ways() is those ways, with the real URL, file name,
# size and room filled in.

BODY_MAX = 8000
APPENDIX_MARK = "\n\n---\nAppendix A: "
_LETTERS = "ABC"
_TEXT_MAX = {"post": 8000, "comment": 8000, "porch": 500, "flag": 200}


def is_build(row):
    return (str(row["kind"] or "") in ("code", "data")
            and str(row["source"] or "").startswith("build:"))


def _page_url(row):
    src = str(row["source"] or "")
    return src if src.startswith(("http://", "https://")) else None


def _doc(state, n):
    try:
        return state.db.execute("SELECT * FROM library WHERE id=?", (int(n),)).fetchone()
    except Exception:
        return None


def _appendix(cfg, row, letter):
    text = _doc_text(cfg, row)
    if text is None:
        return None
    fence = "~~~~" if "```" in text else "```"
    if not text.endswith("\n"):
        text += "\n"
    return (f"Appendix {letter}: {doc_label(row)}, sha256 {str(row['sha256']).lower()}\n"
            f"{fence}\n{text}{fence}")


def _numbered(opts):
    return " Ways to do it: " + " ".join(f"({i}) {o}" for i, o in enumerate(opts, 1))


def ways(state, cfg, kind, payload, row=None):
    """The ways riffle can give a reader what it meant to cite."""
    payload = payload or {}
    body = str(payload.get("body") or payload.get("note") or "")
    opts = []
    if row is not None:
        url, label, n = _page_url(row), doc_label(row), row["id"]
        if url:
            return _numbered([
                f"cite the page itself, {url}, and quote the sentence you rely on, "
                f"in quotation marks, so a reader can find it there",
                "or say what it says in your own words, with that URL"])
        if is_build(row):
            size = int(row["bytes"] or 0)
            pub = published_in(state, cfg, row, "", my_posts(state))
            if pub and pub.startswith("post "):
                p = int(pub.split()[1])
                opts.append(f"cite post {p}, which already carries {label} in full: "
                            f"{post_url(cfg, p)}")
            room = BODY_MAX - len(body) - size - 120
            if kind in ("post", "comment") and room >= 0:
                opts.append(f"add \"append\": [{n}] to this {kind}. {label} goes at "
                            f"the end in full, as text, with its sha256 ({size} "
                            f"characters, and there is room); call it \"Appendix A\"")
            elif size + 200 <= BODY_MAX:
                opts.append(f"post it first: a short post saying what {label} is and "
                            f"what it printed, with \"append\": [{n}] ({size} "
                            f"characters); then cite that post here by its URL")
            else:
                opts.append(f"{label} is {size} characters, more than a post holds "
                            f"({BODY_MAX}): say what it does and what it printed, and "
                            f"build a shorter script if a reader needs to run it")
            opts.append("or leave the file out and say in words what it does and "
                        "what it printed")
            return _numbered(opts)
        return _numbered([
            f"say the point itself here, in your own words: #{n} ({label[:50]}) is "
            f"your own writing, and a note of yours is not evidence to anyone else"]
            + ([f"cite where it came from: {row['source']}"]
               if str(row["source"] or "").startswith("http") else []))
    return _numbered([
        "a file one of your builds made: add \"append\": [its library id] to a "
        "post or comment, and it goes at the end in full, as text, with its sha256",
        "a page you read: cite its URL and quote the sentence you rely on",
        "a post of yours that carries it: cite that post's URL",
        "or say it in your own words"])


def attach(state, cfg, kind, payload):
    """(payload with its "append" files at the end of the body and "append"
    gone, why not or None). Run again on a rewritten body, it replaces the
    appendices rather than adding a second set."""
    p = dict(payload or {})
    ids = p.pop("append", None) or []
    if not ids or kind not in ("post", "comment"):
        return p, None
    body = str(p.get("body") or "")
    i = body.find(APPENDIX_MARK)
    if i >= 0:
        body = body[:i].rstrip()
    parts = []
    for k, n in enumerate(ids[:3]):
        row = _doc(state, n)
        if row is None:
            return p, (f"\"append\" names library #{n}, and there is no such "
                       f"document. library_find it first." + ways(state, cfg, kind, p))
        if not is_build(row):
            return p, (f"\"append\" takes your build files and their output; "
                       f"#{n} ({doc_label(row)[:60]}) is a {row['kind']}."
                       + ways(state, cfg, kind, p, row))
        a = _appendix(cfg, row, _LETTERS[k])
        if a is None:
            return p, f"library #{n} could not be read from the shelf, so it cannot be appended."
        parts.append(a)
    new = body + "\n\n---\n" + "\n\n".join(parts)
    if len(new) > BODY_MAX:
        return p, (f"with its appendices this {kind} would be {len(new)} characters, "
                   f"and the square takes {BODY_MAX}. Post each file on its own (a "
                   f"short post with \"append\": [one id]) and cite those posts by "
                   f"URL here, or append fewer, or say in words what they show.")
    p["body"] = new
    return p, None


ATTACH_RE = re.compile(
    r"\b(?:see|in|find|check|read|open)\s+(?:the\s+|my\s+)?attach(?:ed|ment)\b"
    r"|\bI(?:'ve|\s+have)?\s+(?:also\s+)?attach(?:ed)?\b"
    r"|\b(?:the\s+)?attached\s+(?:script|file|code|csv|output|data|log|notebook|simulation)\b"
    r"|\b(?:is|are)\s+(?:also\s+)?attached\b"
    r"|\battachments?\b",
    re.I)


def attachment_claimed(state, cfg, kind, payload, text):
    """A post that says something is attached, with nothing appended."""
    m = ATTACH_RE.search(text or "")
    if not m or APPENDIX_MARK in str((payload or {}).get("body") or ""):
        return None
    row = None
    for fm in FILE_RE.finditer(text or ""):
        try:
            row = state.db.execute(
                "SELECT * FROM library WHERE kind IN ('code','data') AND source LIKE 'build:%'"
                " AND (lower(title)=? OR lower(title) LIKE ?) ORDER BY id DESC LIMIT 1",
                (fm.group(1).lower(), fm.group(1).lower() + " \u2014%")).fetchone()
        except Exception:
            row = None
        if row:
            break
    return (f"you wrote \"{m.group(0)}\", and nothing is attached: the square "
            f"takes text only." + ways(state, cfg, kind, payload, row))


# ------------------------------------------------- figures riffle's builds printed
#
# 2026-11-24, the operator's export of 11-21 to 11-24. riffle proposed 48
# posts after batch 21 and sent none: 34 were refused by the number check on
# one figure, 71.7%, which its own simulation had printed. Three things
# together made that a trap with no way out:
#   - the number check counted only the LAST build's output, and a newer
#     build (verify_hypergeom.py) had replaced the one that printed it;
#   - the only other way it counted a build's output was "library #N" in the
#     text, which library-private refuses (the same check, two answers);
#   - its refusal said "search_web a reference site", and riffle read the
#     Wikipedia page on the hypergeometric distribution twice, looking for its
#     own simulation's result.
# And the figure was not a finding. verify_suppression.py and verify_final.py
# drew each trial with `random.random() < 0.718`, "as per previous findings",
# and reported the 0.717 that came back as confirmation.
#
# So: a figure a build of riffle's printed counts when a reader can see that
# build, appended to the text or carried by a post of riffle's the text names
# (public_build_outputs); the refusal for one that does not count names the
# build and the ways to show it (build_route); and a figure a simulation was
# given as its input is refused as a finding (figure_assumed).

def _run_docs(state, run):
    """(code rows, output row or None) of build run `run` ("build:c4936"),
    including files shared with other runs through library_aliases."""
    try:
        rows = state.db.execute(
            "SELECT * FROM library WHERE source IN (?, ?) UNION "
            "SELECT l.* FROM library l JOIN library_aliases a ON a.lib_id = l.id"
            " WHERE a.source IN (?, ?) ORDER BY id",
            (run, run + ":stdout", run, run + ":stdout")).fetchall()
    except Exception:
        try:
            rows = state.db.execute("SELECT * FROM library WHERE source IN (?, ?) ORDER BY id",
                                    (run, run + ":stdout")).fetchall()
        except Exception:
            return [], None
    code = [r for r in rows if r["kind"] == "code"]
    out = [r for r in rows if r["kind"] == "data"]
    return code, (out[-1] if out else None)


def _runs_of(state, row):
    """Every build run a library document came from: its own source and its
    aliases, as "build:cN"."""
    srcs = [str(row["source"] or "")]
    try:
        srcs += [str(a[0]) for a in state.db.execute(
            "SELECT source FROM library_aliases WHERE lib_id=?", (row["id"],))]
    except Exception:
        pass
    out = []
    for s in srcs:
        m = re.match(r"(build:[^:\s]+)", s)
        if m and m.group(1) not in out:
            out.append(m.group(1))
    return out


def _values(text):
    out = []
    for m in re.finditer(r"(?<![\w.])-?\d+(?:,\d{3})*(?:\.\d+)?(?:[eE]-?\d+)?", text or ""):
        try:
            out.append(float(m.group(0).replace(",", "")))
        except ValueError:
            pass
    return out


def _printed_as(token, values):
    """The printed value a figure written as `token` is, or None: 71.7 is 0.717
    printed, or 71.7; 0.025 is 0.025012... printed. Whole numbers of ten or
    less are everywhere, and are not looked for."""
    try:
        t = float(str(token).replace(",", ""))
    except ValueError:
        return None
    d = len(str(token).split(".")[1]) if "." in str(token) else 0
    if d == 0 and abs(t) <= 10:
        return None
    for v in values:
        for k in (1, 100):
            if round(v * k, d) == round(t, d):
                return v
    return None


_RATE_LIT = r"(\d*\.\d+|1(?:\.0+)?)"
_RATE_RES = (
    re.compile(r"random\w*\([^()\n]*\)\s*[<>]=?\s*" + _RATE_LIT + r"(?![\d.])"),
    re.compile(r"(?<![\w.])" + _RATE_LIT + r"\s*[<>]=?\s*[\w.]*random\w*\("),
    re.compile(r"\b(?:binomial|bernoulli|choices)\([^()\n]*?(?:p\s*=\s*|,\s*)" + _RATE_LIT + r"(?![\d.])"),
)
_RATE_NAME_RE = re.compile(r"random\w*\([^()\n]*\)\s*[<>]=?\s*([A-Za-z_]\w*)")


def assumed_rates(code):
    """The probabilities a script draws its trials with: `random() < 0.718`,
    `binomial(n, 0.3)`, or `random() < P` with `P = 0.718` set in the file."""
    code = code or ""
    out = set()
    for rx in _RATE_RES:
        for m in rx.finditer(code):
            try:
                v = float(m.group(1))
            except ValueError:
                continue
            if 0 < v < 1:
                out.add(v)
    for m in _RATE_NAME_RE.finditer(code):
        a = re.search(r"(?m)^\s*" + re.escape(m.group(1)) + r"\s*=\s*" + _RATE_LIT + r"\s*(?:#.*)?$", code)
        if a:
            try:
                v = float(a.group(1))
            except ValueError:
                continue
            if 0 < v < 1:
                out.add(v)
    return out


def _assumes(state, cfg, code_rows, value):
    """The rate in these files that `value` merely reproduces, or None."""
    if value is None or not (0 < value < 1):
        return None
    for c in code_rows:
        for p in assumed_rates(_doc_text(cfg, c)):
            if abs(value - p) <= 0.02 or abs(value - (1 - p)) <= 0.02:
                return p
    return None


def build_outputs(state, limit=200):
    """Every build output document, newest first."""
    try:
        return state.db.execute(
            "SELECT * FROM library WHERE kind='data' AND (source LIKE 'build:%:stdout'"
            " OR id IN (SELECT lib_id FROM library_aliases WHERE source LIKE 'build:%:stdout'))"
            " ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    except Exception:
        try:
            return state.db.execute(
                "SELECT * FROM library WHERE kind='data' AND source LIKE 'build:%:stdout'"
                " ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        except Exception:
            return []


def figure_source(state, cfg, token):
    """(output row, code rows, printed value) for the newest build of riffle's
    whose output carries the figure written as `token`, or None."""
    for o in build_outputs(state):
        v = _printed_as(token, _values(_doc_text(cfg, o)))
        if v is None:
            continue
        code = []
        for run in _runs_of(state, o):
            code += [c for c in _run_docs(state, run)[0] if c not in code]
        return o, code, v
    return None


def build_route(state, cfg, kind, payload, token):
    """What riffle is told about a figure the number check could not back,
    when one of its builds printed it; None when none did."""
    hit = figure_source(state, cfg, token)
    if not hit:
        return None
    o, code, v = hit
    files = ", ".join(doc_label(c) for c in code) or doc_label(o)
    when = str(o["created_at"] or "")[:16].replace("T", " ")
    p = _assumes(state, cfg, code, v)
    if p is not None:
        return (f" {token} is what {files} printed ({when}), and {files} was given "
                f"it: each trial is drawn with a probability of {p}. A simulation "
                f"that sets a rate and then counts it has measured its own input, "
                f"so {token} is your assumption, not a finding, and no source can "
                f"back it as one. Say it as the assumption it is, or build "
                f"something that measures the rate instead of setting it.")
    return (f" {token} is what {files} printed ({when}). It counts once a reader "
            f"can see that build."
            + ways(state, cfg, kind, payload, code[0] if code else o))


def public_build_outputs(state, cfg, text):
    """{"build_output_<id>": what it printed} for each build of riffle's a
    reader of `text` can see: one of its files or its output appended to the
    text, or carried in full by a post of riffle's that the text names."""
    from agent.cycle import _square_refs
    mine = my_posts(state)
    named = {n for k, n in _square_refs(text or "", cfg) if k == "post"}
    posts = {p: b for p, b in mine.items() if p in named}
    hay = "\n".join([text or ""] + list(posts.values()))
    shas = {h.lower() for _, _, h in _hash_tokens(hay)}
    names = {m.group(1).lower() for m in FILE_RE.finditer(hay)}
    if not shas and not names:
        return {}
    try:
        rows = state.db.execute(
            "SELECT * FROM library WHERE kind IN ('code','data') AND (source LIKE 'build:%'"
            " OR id IN (SELECT lib_id FROM library_aliases WHERE source LIKE 'build:%'))"
            " ORDER BY id DESC LIMIT 400").fetchall()
    except Exception:
        return {}
    out, done = {}, set()
    for r in rows:
        sha = str(r["sha256"] or "").lower()
        if not (any(sha.startswith(h) for h in shas) or _doc_name(r) in names):
            continue
        if not published_in(state, cfg, r, text, posts):
            continue
        for run in _runs_of(state, r):
            if run in done:
                continue
            done.add(run)
            o = r if r["kind"] == "data" else _run_docs(state, run)[1]
            t = _doc_text(cfg, o) if o is not None else None
            if t:
                out[f"build_output_{o['id']}"] = t[:20000]
    return out


_FIGURE_RE = re.compile(r"(?<![\w.#])(\d+(?:\.\d+)?)\s*%|(?<![\w.#])(\d*\.\d+)(?![\w.])")


def figure_assumed(state, cfg, kind, payload, text):
    """A percentage or fraction in the text that a build of riffle's printed
    after being given it as its trial probability: the 0.718 that came back
    as 71.7%. Only builds this text names or shows are looked at."""
    t = text or ""
    names = {m.group(1).lower() for m in FILE_RE.finditer(t)}
    shown = public_build_outputs(state, cfg, t)
    outs = []
    for o in build_outputs(state):
        if f"build_output_{o['id']}" in shown:
            outs.append(o)
            continue
        runs = _runs_of(state, o)
        if names and any(_doc_name(c) in names for run in runs for c in _run_docs(state, run)[0]):
            outs.append(o)
    if not outs:
        return None
    for m in _FIGURE_RE.finditer(outside_fences(t)):
        tok = m.group(1) or m.group(2)
        for o in outs:
            v = _printed_as(tok, _values(_doc_text(cfg, o)))
            if v is None:
                continue
            code = []
            for run in _runs_of(state, o):
                code += [c for c in _run_docs(state, run)[0] if c not in code]
            p = _assumes(state, cfg, code, v)
            if p is None:
                continue
            files = ", ".join(doc_label(c) for c in code)
            return (f"you give {m.group(0).strip()} as a result, and it is what {files} "
                    f"printed after drawing every trial with a probability of {p}. A "
                    f"simulation that sets a rate and counts it back has measured its "
                    f"own input: the figure is your assumption, not a finding, and "
                    f"presenting it as one tells readers something was confirmed that "
                    f"was not. Say it as the assumption it is (\"assuming {p} of ...\"), "
                    f"or build something that measures the rate instead of setting it.")
    return None


# ------------------------------------------------ saying a post exists

POST_CLAIM_RE = re.compile(
    r"\bI(?:'m|\s+am)\s+(?:now\s+|also\s+)?(?:posting|publishing)\b"
    r"|\bI(?:'ve|\s+have)\s+(?:now\s+|just\s+|also\s+)?(?:posted|published)\b"
    r"|\b(?:my|the)\s+(?:new\s+|standalone\s+)?(?:post|analysis|synthesis|write-?up)\s+"
    r"(?:is|was|will\s+be|went\s+out\s+as)\s+(?:post\s+)?#\s?\d+"
    # "The tripwire post is queued with the build appended" (porch 4548,
    # 2026-11-26): no post was queued or sent.
    r"|\b(?:my|the)\s+(?:[\w-]+\s+){0,3}?post\s+is\s+(?:now\s+)?(?:queued|waiting|up|out|live|sent)\b",
    re.I)
_POST_NUM_RE = re.compile(r"#\s?(\d+)")


def post_claimed(state, cfg, text, kind=None):
    """"I am posting it … The post is #13370" (action 4350, 2026-11-24), when
    riffle has sent no post in six hours, or names a post number that is not
    one of its own. Every one of its 48 posts in those three days was refused."""
    mine = None
    for m in POST_CLAIM_RE.finditer(text or ""):
        if mine is None:
            mine = my_posts(state)
        n = _POST_NUM_RE.search(m.group(0))
        if n:
            if int(n.group(1)) in mine:
                continue
            return (f"you wrote \"{m.group(0)}\", and #{n.group(1)} is not a post you "
                    f"sent. Name only a post that exists, and only once it does.")
        if kind == "post":
            continue            # "I am posting this because ..." is the post itself
        lo = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=CLAIM_HOURS)
              ).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            hit = state.db.execute(
                "SELECT 1 FROM actions WHERE kind='post' AND created_at > ?"
                " AND status IN ('executed','sent','approved','queued') LIMIT 1",
                (lo,)).fetchone()
        except Exception:
            hit = True
        if not hit:
            return (f"you wrote \"{m.group(0)}\", and you have sent or queued no post in "
                    f"the last {CLAIM_HOURS} hours. Say a post exists once it does, and "
                    f"give its number then.")
    return None


# ------------------------------------------------------------- the checks

def orphan_declaration(text):
    for m in DECL_RE.finditer(text or ""):
        if not _FIGURE_BEFORE.search((text or "")[:m.start()]):
            before = " ".join((text or "")[max(0, m.start() - 50):m.start()].split())
            return (f"\"{m.group(0)}\" follows \"…{before}\", not a figure. A "
                    f"[[...]] is the derivation of the number directly before it, "
                    f"37.5% [[3/8*100]], and is for the number check: on its own "
                    f"it is markup a reader cannot make sense of. \"3/8*100\" is "
                    f"the prompt's example, not your arithmetic. Take it out, or "
                    f"put the figure it computes in front of it.")
    return None


def library_reference(state, cfg, kind, payload, text):
    m = LIBRARY_RE.search(text or "")
    if not m:
        return None
    num = re.search(r"\d+", m.group(0))
    row = _doc(state, num.group(0)) if num else None
    # ALREADY APPENDED (2026-11-27). All 32 of these refusals in three days
    # were posts with "append": [414] (or [426]) set and "library #414" in
    # the prose, and the first way offered was "add "append": [414] to this
    # post". It was there; what was wrong was the number.
    # The appendix itself is the evidence: attach() has taken "append" out of
    # the payload by now and written each file under "Appendix X: name,
    # sha256 H", and that is also what the operator approves.
    letter = None
    if row is not None:
        for am in re.finditer(r"(?m)^Appendix ([A-Z]): .*?, sha256 ([0-9a-f]{64})\s*$", text or ""):
            if am.group(2) == str(row["sha256"] or "").lower():
                letter = am.group(1)
                break
    if letter:
        return (f"you wrote \"{m.group(0)}\", and {_doc_name(row)} is already appended to "
                f"this {kind} as Appendix {letter}. A reader sees the appendix, not your "
                f"library's numbering: write \"Appendix {letter}\" or \"{_doc_name(row)}\" "
                f"wherever you wrote \"{m.group(0)}\", and keep the append.")
    return (f"you wrote \"{m.group(0)}\". Your library is on this machine: nobody "
            f"reading can open it, so it is not a source and not evidence."
            + ways(state, cfg, kind, payload, row))


def _hash_tokens(text):
    return [(m.start(), m.end(), m.group(1)) for m in HEX_RE.finditer(text or "")
            if re.search(r"\d", m.group(1))]


def hash_wrong_file(state, text):
    t = text or ""
    for s, e, h in _hash_tokens(t):
        docs = _docs_for(state, h)
        if not docs:
            continue
        names = {_doc_name(d) for d in docs}
        line_start = t.rfind("\n", 0, s) + 1
        line_end = t.find("\n", e)
        line_end = len(t) if line_end < 0 else line_end
        before = [(fm.group(1), s - fm.end()) for fm in FILE_RE.finditer(t, max(line_start, s - 100), s)]
        after = [(fm.group(1), fm.start() - e) for fm in FILE_RE.finditer(t, e, min(line_end, e + 40))]
        near = (min(before, key=lambda x: x[1]) if before else
                min(after, key=lambda x: x[1]) if after else None)
        if near and near[0].lower() not in names:
            d = docs[0]
            try:
                other = state.db.execute(
                    "SELECT id, sha256 FROM library WHERE kind IN ('code','data')"
                    " AND (lower(title)=? OR lower(title) LIKE ?) ORDER BY id DESC LIMIT 1",
                    (near[0].lower(), near[0].lower() + " \u2014%")).fetchone()
            except Exception:
                other = None
            return (f"you name {h} as {near[0]}, and {h} is {_doc_name(d)} "
                    f"(library #{d['id']}, \"{d['title'][:60]}\"). A hash is a "
                    f"claim about one file. Ways to do it: (1) if you mean "
                    f"{_doc_name(d)}, call it {_doc_name(d)} "
                    + (f"(2) if you mean {near[0]}, its hash is "
                       f"{str(other['sha256'])[:12]} (library #{other['id']}) "
                       if other else
                       f"(2) if you mean {near[0]}, you have no build of it: leave "
                       f"the hash out ")
                    + "(3) whichever it is, append the file so a reader can check it.")
    return None


def hash_unpublished(state, cfg, kind, text):
    t = text or ""
    posts = None
    for s, e, h in _hash_tokens(t):
        docs = _docs_for(state, h)
        if not docs:
            continue
        if posts is None:
            from agent.cycle import _square_refs
            mine = my_posts(state)
            named = {n for k, n in _square_refs(t, cfg) if k == "post"}
            posts = {p: b for p, b in mine.items() if p in named}
        if any(published_in(state, cfg, d, t, posts) for d in docs):
            continue
        d = docs[0]
        return (f"{h} is the hash of {doc_label(d)} (library #{d['id']}), a file "
                f"only you have. Nobody reading this {kind} can see it, so its "
                f"hash proves nothing to them."
                + ways(state, cfg, kind, {"body": t}, d))
    return None


def edit_promise(text):
    m = EDIT_POST_RE.search(text or "")
    if not m:
        return None
    return (f"you wrote \"{m.group(0)}\". A post cannot be edited once it is sent; "
            f"there is no edit on the square. Say what was wrong, and the "
            f"correction, here, where it will be read.")


def claim_unbacked(state, text):
    for m in CLAIM_RE.finditer(text or ""):
        kinds = _CLAIM_KINDS.get(m.group(1).lower(), ())
        lo = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=CLAIM_HOURS)
              ).strftime("%Y-%m-%dT%H:%M:%SZ")
        q = ",".join("?" * len(kinds))
        try:
            hit = state.db.execute(
                f"SELECT 1 FROM actions WHERE kind IN ({q}) AND created_at > ?"
                " AND status IN ('accepted','executed') LIMIT 1",
                (*kinds, lo)).fetchone()
        except Exception:
            hit = True
        if not hit:
            return (f"you wrote \"{m.group(0)}\", and you have done no "
                    f"{' or '.join(kinds)} in the last {CLAIM_HOURS} hours. Say "
                    f"what you did only once you have done it. And a reader "
                    f"cannot see your notes, draft or library: what matters to "
                    f"them is what you say here.")
    return None


def _author_of(state, comment_id):
    have = _tables(state)
    cid = int(comment_id)
    try:
        if "inbox_items" in have:
            r = state.db.execute("SELECT author FROM inbox_items WHERE comment_id=?"
                                 " AND author IS NOT NULL", (cid,)).fetchone()
            if r:
                return r["author"]
        for t in ("thread_reads", "board_cache"):
            if t not in have:
                continue
            r = state.db.execute(
                f"SELECT json_extract(j.value,'$.author') AS a FROM {t}, "
                f"json_each(CASE WHEN json_valid({t}.comments_json) THEN {t}.comments_json ELSE '[]' END) j"
                f" WHERE CAST(json_extract(j.value,'$.id') AS INTEGER)=? LIMIT 1",
                (cid,)).fetchone()
            if r and r["a"]:
                return r["a"]
    except Exception:
        return None
    return None


def _is_citizen(state, name):
    have = _tables(state)
    n = name.lower()
    try:
        if "inbox_items" in have and state.db.execute(
                "SELECT 1 FROM inbox_items WHERE lower(author)=? LIMIT 1", (n,)).fetchone():
            return True
        for t in ("thread_reads", "board_cache"):
            if t not in have:
                continue
            if state.db.execute(f"SELECT 1 FROM {t} WHERE lower(author)=? LIMIT 1",
                                (n,)).fetchone():
                return True
            if state.db.execute(
                    f"SELECT 1 FROM {t}, json_each(CASE WHEN json_valid({t}.comments_json)"
                    f" THEN {t}.comments_json ELSE '[]' END) j"
                    f" WHERE lower(json_extract(j.value,'$.author'))=? LIMIT 1",
                    (n,)).fetchone():
                return True
    except Exception:
        return False
    return False


def wrong_addressee(state, payload):
    par = (payload or {}).get("parent_id")
    if par is None:
        return None
    m = OPENING_RE.match((payload or {}).get("body") or "")
    if not m:
        return None
    name, cited = m.group(1), m.group(2)
    try:
        par = int(par)
    except (TypeError, ValueError):
        return None
    author = _author_of(state, par)
    if cited and int(cited) != par:
        return (f"this replies to c{par}"
                + (f" by {author}" if author else "")
                + f", and opens by answering c{cited}. A reply is shown under "
                  f"the comment it replies to. Reply to c{cited} itself, or "
                  f"answer c{par}.")
    if (author and name.lower() != str(author).lower()
            and _is_citizen(state, name)):
        return (f"this replies to c{par} by {author}, and opens by addressing "
                f"{name}. A reply is shown under {author}'s comment and goes to "
                f"{author}. If you meant {name}, reply to {name}'s comment; if "
                f"you meant {author}, address {author}.")
    return None


# ------------------------------------------------ what riffle says they said
#
# The communications audit of 2026-11-20 found riffle misreporting other
# citizens' data, and it did again on 11-24: action 4345 told swift-lantern
# "the suppression rate you observed", replying to a comment about Merkle
# proof folds that has no rate in it. Whether a paraphrase is fair needs
# reading; whether a number or a finding credited to someone is in what they
# wrote does not.

_CREDIT_VERBS = (r"observed|measured|found|reported|saw|computed|counted|got|"
                 r"confirmed|ran|walked|showed|identified|recorded|noted|derived")
_CREDIT_RES = (
    # "the suppression rate you observed", "the inversion that you measured"
    re.compile(r"\bthe\s+((?:[\w-]+\s+){0,4}?[\w-]+)\s+(?:that\s+)?you(?:'ve|\s+have)?\s+(?:"
               + _CREDIT_VERBS + r")\b", re.I),
    # "you measured 267 rows", "you found zero structural mismatches"
    re.compile(r"\byou(?:'ve|\s+have)?\s+(?:" + _CREDIT_VERBS + r")\s+([^.;:!?\n]{1,80})", re.I),
    # "your 55 ms inversion"
    re.compile(r"\byour\s+(\d[\d,.]*(?:\s*(?:ms|s|%|rows?|runs?|pages?|hits?))?)", re.I),
)
_STOP = {"that", "this", "these", "those", "with", "from", "your", "their", "which",
         "what", "there", "here", "into", "about", "some", "more", "each", "very",
         "just", "only", "also", "even", "much", "than", "then", "them", "they",
         "were", "have", "been", "being", "when", "where", "while", "point", "note",
         "thing", "things", "result", "results", "finding", "work", "check", "same"}


def _body_of(state, comment_id):
    """The text of comment `comment_id` as riffle has it, or None."""
    have = _tables(state)
    cid = int(comment_id)
    try:
        if "inbox_items" in have:
            r = state.db.execute("SELECT body FROM inbox_items WHERE comment_id=?"
                                 " AND body IS NOT NULL", (cid,)).fetchone()
            if r and r["body"]:
                return r["body"]
        for t in ("thread_reads", "board_cache"):
            if t not in have:
                continue
            r = state.db.execute(
                f"SELECT json_extract(j.value,'$.body') AS b FROM {t}, "
                f"json_each(CASE WHEN json_valid({t}.comments_json) THEN {t}.comments_json ELSE '[]' END) j"
                f" WHERE CAST(json_extract(j.value,'$.id') AS INTEGER)=? LIMIT 1",
                (cid,)).fetchone()
            if r and r["b"]:
                return r["b"]
    except Exception:
        return None
    return None


def credited_wrongly(said, theirs):
    """What a reply credits to its addressee that their text does not carry,
    as (the phrase, what is missing), or None. `said` is riffle's reply,
    `theirs` the comment it replies to."""
    if not said or not theirs:
        return None
    t = theirs.lower()
    tnums = {n.replace(",", "") for n in re.findall(r"\d[\d,]*(?:\.\d+)?", t)}
    tstems = {w[:5] for w in re.findall(r"[a-z][a-z-]{3,}", t)}
    for k, rx in enumerate(_CREDIT_RES):
        for m in rx.finditer(outside_fences(said)):
            phrase = m.group(1)
            nums = [n.replace(",", "").rstrip(".") for n in re.findall(r"\d[\d,]*(?:\.\d+)?", phrase)]
            bad = [n for n in nums if n not in tnums]
            if bad:
                return m.group(0).strip(), ", ".join(bad)
            if k == 0:
                words = [w for w in re.findall(r"[a-z][a-z-]{3,}", phrase.lower()) if w not in _STOP]
                if words and not any(w[:5] in tstems for w in words):
                    return m.group(0).strip(), " ".join(words)
    return None


def credited(state, payload):
    """A reply that credits its addressee with a number or a finding their
    comment does not carry."""
    par = (payload or {}).get("parent_id")
    if par is None:
        return None
    try:
        par = int(par)
    except (TypeError, ValueError):
        return None
    theirs = _body_of(state, par)
    hit = credited_wrongly((payload or {}).get("body") or "", theirs)
    if not hit:
        return None
    phrase, missing = hit
    who = _author_of(state, par) or f"c{par}"
    return (f"you wrote \"{phrase[:90]}\", replying to {who}, and their comment "
            f"c{par} has nothing of it ({missing}). Credit them only with what they "
            f"wrote. If it is your reading of what they wrote, or something you "
            f"found yourself, say so: \"I read this as …\", \"my own run found …\".")


# ------------------------------------------------ what riffle says it said before
#
# Action 4531 (2026-11-26) told uriel "The six created_at inversions you note
# are the same six I flagged earlier". riffle had flagged none: holdfast named
# five and uriel found the sixth; riffle's one earlier mention of an inversion
# (action 4483) was of uriel's sixth, thanking someone else for it.

_NUMERALS = {"two", "three", "four", "five", "six", "seven", "eight", "nine",
             "ten", "eleven", "twelve", "dozen", "twenty", "hundred"}
BEFORE_RE = re.compile(
    r"([^.;!?\n]{0,140}?)\bI(?:'d|\s+had|\s+have|'ve)?\s+(?:already\s+)?"
    r"(?:flagged|reported|found|noted|identified|raised|pointed\s+out|showed|posted|"
    r"mentioned|measured|computed|named|called\s+out)\s+(?:it|them|this|these|that)?\s*"
    r"(?:earlier|before|previously|already|last\s+week|yesterday|in\s+my\s+(?:post|comment))\b",
    re.I)


def _said_before(state, days=30):
    """The text of everything riffle sent in the last `days` days."""
    lo = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = []
    try:
        for r in state.db.execute(
                "SELECT payload FROM actions WHERE kind IN ('comment','post','porch')"
                " AND status IN ('executed','sent') AND created_at > ?", (lo,)):
            try:
                p = json.loads(r["payload"] or "{}")
            except ValueError:
                continue
            out.append(" ".join(str(p.get(k) or "") for k in ("title", "body", "text")).lower())
    except Exception:
        return None
    return out


def claimed_before(state, text):
    """"… the same six I flagged earlier" when nothing riffle sent in 30 days
    carries what it says it flagged: every number in the claim, and a word
    of it."""
    prior = None
    for m in BEFORE_RE.finditer(outside_fences(text or "")):
        what = m.group(1).lower()
        nums = set(re.findall(r"\d[\d,]*(?:\.\d+)?", what)) | {w for w in re.findall(r"[a-z]+", what)
                                                                if w in _NUMERALS}
        stems = {w[:5] for w in re.findall(r"[a-z][a-z_-]{3,}", what) if w not in _STOP
                 and w not in _NUMERALS and w not in ("same", "note", "notes", "flagged")}
        if not nums and not stems:
            continue
        if prior is None:
            prior = _said_before(state)
            if prior is None:
                return None
        ok = any(all(re.search(rf"(?<![\w.]){re.escape(n)}(?![\w])", t) for n in nums)
                 and (not stems or stems & {w[:5] for w in re.findall(r"[a-z][a-z_-]{3,}", t)})
                 for t in prior)
        if not ok:
            said = m.group(0).strip()
            return (f"you wrote \"{said[:100]}\", and nothing you sent in the last 30 "
                    f"days says it. Say only what you did. If they found it, it is "
                    f"theirs: credit them.")
    return None


# ------------------------------------------------ a second reading
#
# credited and claimed-before catch a number or a word riffle credits to
# someone that is not in what they wrote. They caught none of the five
# misstatements in the 14 comments of 2026-11-24 to 11-27: "#34 carries the
# fix" (silt had said #33), "the full-row hash you measured" (there was no
# second hash), "your measurement confirms the suppression hypothesis" (it
# said nothing of gate order). Those are misreadings, and catching one needs
# reading. The operator's decision, 2026-11-27: before a reply goes out the
# triage model reads it beside the comment it answers.

SECOND_READ_SYSTEM = """You check one reply before it is posted on a public forum. You are \
shown a comment and a reply to it.

Find every place where the reply says the comment's author said, measured, \
found, showed, confirmed, agreed to or proposed something that their comment \
does not say, or says differently: a number changed, a claim turned into \
support for something else, one thing credited as another.

Disagreeing, adding the replier's own view, guessing, or asking a question is \
fine and is not a misstatement. Only what the reply says THEY said counts.

Answer NONE if there is none. Otherwise answer with up to three lines, each \
quoting the reply's words and then THEIR comment's own words that show what \
they actually said, both copied exactly:
MISSTATED: "<exact words from the reply>" | "<exact words from their comment>\""""

# BOTH HALVES ARE QUOTES, AND BOTH ARE CHECKED (box, 2026-11-28). The first
# refusal on the box, cycle 5274, answered lucykimi's c162821. The reply did
# misread it: lucykimi asked for a seat set deliberately wrong as a test the
# board had NOT seen, and the reply called it "the one bellwether and
# head-of-experiments just ran", then offered the same idea as its own. But
# the model's verdict named the reply's last sentence (riffle's own
# prediction) and gave, as "what their comment says", that same sentence
# again, which riffle was then told. A finding is now kept only when its
# second half is words of their comment, and not when the reply's words are
# theirs too (quoting someone accurately is not misstating them).
_MIS_RE = re.compile(r'(?im)^\s*MISSTATED:\s*["\u201c](.+?)["\u201d]\s*\|\s*["\u201c](.+?)["\u201d]\s*$')


def second_read(state, cfg, kind, payload, log=None):
    """Why the triage model, reading a reply beside the comment it answers,
    finds it misstates what that comment said; None when it finds nothing,
    or cannot be asked. Fails open: a reply is never held because the check
    could not run. Every verdict goes to the journal, so a week of them can
    be judged."""
    sr = cfg.get("second_read") or {}
    if kind != "comment" or not sr.get("enabled", True):
        return None
    par = (payload or {}).get("parent_id")
    try:
        par = int(par)
    except (TypeError, ValueError):
        return None
    theirs = _body_of(state, par)
    said = outside_fences((payload or {}).get("body") or "")
    if not theirs or not said.strip():
        return None
    who = _author_of(state, par) or f"c{par}"
    from agent import cortex
    tri = dict((cfg.get("llm") or {}).get("triage") or {})
    if not tri:
        return None
    tri["max_tokens"] = int(sr.get("max_tokens", 300))
    try:
        cortex.set_purpose("second read")
        out = cortex.complete(tri, SECOND_READ_SYSTEM,
                              f"THEIR COMMENT (c{par}, by {who}):\n{theirs[:3000]}\n\n"
                              f"THE REPLY:\n{said[:3000]}",
                              timeout=int(sr.get("timeout_seconds", 240)))
    except Exception as e:
        if log:
            log(f"second read of the reply to c{par} could not run ({type(e).__name__}: "
                f"{str(e)[:120]}); sent unread", level="warn")
        return None
    flat = " ".join(said.split()).lower()
    tflat = " ".join(theirs.split()).lower()
    found = []
    for m in _MIS_RE.finditer(out or ""):
        q = " ".join(m.group(1).split())
        w = " ".join(m.group(2).split())
        # Each quote must be where it says it is: a model can invent the
        # words it objects to, or what it says they said, and a refusal
        # built on words nobody wrote teaches nothing.
        if (len(q) >= 12 and q.lower() in flat and len(w) >= 12
                and w.lower() in tflat and q.lower() not in tflat):
            found.append((q, w))
    if log:
        log(f"second read of the reply to c{par} by {who}: "
            + ("; ".join(f'"{q[:80]}" | "{w[:120]}"' for q, w in found) if found else
               "nothing misstated" + ("" if not (out or "").strip().upper().startswith("MISSTATED")
                                      else " (what it quoted was not in the reply and their "
                                           "comment, or was their own words, or under 12 characters)")),
            level="warn" if found else "info")
    if not found:
        return None
    q, w = found[0]
    return (f"read beside {who}'s comment c{par}, your reply says \"{q[:120]}\", where "
            f"their comment says \"{w[:240]}\". Say only what they said. If it is your "
            f"own reading, or your own finding, say so in those words."
            + (f" ({len(found) - 1} more like it.)" if len(found) > 1 else ""))


def voted_unread(state, payload):
    tt = (payload or {}).get("target_type") or "post"
    try:
        tid = int((payload or {}).get("target_id"))
    except (TypeError, ValueError):
        return None
    have = _tables(state)
    try:
        if tt == "post":
            for t in ("thread_reads", "board_cache"):
                if t in have and state.db.execute(
                        f"SELECT 1 FROM {t} WHERE post_id=? LIMIT 1", (tid,)).fetchone():
                    return None
        else:
            from agent.cycle import _seen_post_of
            if _seen_post_of(state, tid) is not None:
                return None
            if "board_cache" in have and state.db.execute(
                    "SELECT 1 FROM board_cache, json_each(CASE WHEN json_valid(comments_json)"
                    " THEN comments_json ELSE '[]' END) j"
                    " WHERE CAST(json_extract(j.value,'$.id') AS INTEGER)=? LIMIT 1",
                    (tid,)).fetchone():
                return None
    except Exception:
        return None
    what = f"post {tid}" if tt == "post" else f"comment {tid}"
    return (f"you have not read {what}: it is in no thread you read and nothing "
            f"you fetched. A vote tells everyone it is worth their time, and you "
            f"cannot know that from a title. read_thread it first, or vote on "
            f"something you have read.")


def listing_submitted(state, payload, exclude_id=None):
    """Proposing (exclude_id None): any other submission to the listing, sent
    or waiting, refuses this one. Approving (exclude_id = this action): only
    one already sent or on its way does. Two waiting cards are both
    approvable until one of them goes; then the other is refused."""
    lid = (payload or {}).get("listing_id")
    sts = ("'approved','sending','sent','executed','unknown'" if exclude_id is not None
           else "'queued','approved','sending','sent','executed','unknown'")
    try:
        r = state.db.execute(
            "SELECT id, status, created_at FROM actions WHERE kind='listing_submission'"
            f" AND status IN ({sts})"
            " AND CAST(json_extract(payload,'$.listing_id') AS INTEGER)=CAST(? AS INTEGER)"
            " AND id<>? ORDER BY id LIMIT 1", (lid, exclude_id or -1)).fetchone()
    except Exception:
        return None
    if not r:
        return None
    where = ("is waiting for your operator" if r["status"] in ("queued", "approved", "sending")
             else "was sent")
    return (f"you have already submitted to listing {lid}: #{r['id']}, which "
            f"{where} ({r['created_at'][:16]}). One submission per listing. If "
            f"the work has changed, say how in a comment on the post you "
            f"submitted.")


def artifact_not_a_post(state, cfg, payload):
    from agent.cycle import _square_refs, _sent_by_me
    art = str((payload or {}).get("artifact") or "")
    posts = [n for k, n in _square_refs(art, cfg) if k == "post"]
    if any(_sent_by_me(state, "post", n) for n in posts):
        return None
    if posts:
        return None          # another citizen's post: refused as artifact-not-yours
    mine = sorted(my_posts(state), reverse=True)[:5]
    # What the artifact meant, if it names a file of riffle's.
    row = None
    m = re.search(r"library\s*#?\s*(\d+)", art, re.I)
    if m:
        row = _doc(state, m.group(1))
    for _s, _e, h in ([] if row else _hash_tokens(art)):
        docs = _docs_for(state, h)
        if docs:
            row = docs[0]
            break
    opts = []
    if row is not None and is_build(row):
        pub = published_in(state, cfg, row, "", my_posts(state))
        if pub and pub.startswith("post "):
            p = int(pub.split()[1])
            opts.append(f"post {p} already carries {doc_label(row)} in full: "
                        f"submit {post_url(cfg, p)}")
        opts.append(f"post the work first, a post saying what it is and what it "
                    f"printed, with \"append\": [{row['id']}] so {doc_label(row)} "
                    f"goes at its end in full; then submit that post's URL")
    else:
        opts.append("post the work first, with the build file appended (\"append\": "
                    "[its library id]); then submit that post's URL")
    if mine:
        opts.append(f"if one of your posts already carries the work, submit its URL "
                    f"(your latest: {', '.join(str(p) for p in mine)})")
    return (f"the artifact \"{art[:80]}\" is not a post of yours. The square "
            f"takes text only and your library is on this machine, so the one "
            f"thing a funder can fetch and check is a post you sent that carries "
            f"the work in full." + _numbered(opts))


def _related_projects(state, pid):
    try:
        me = state.db.execute("SELECT id, title, question FROM projects WHERE id=?",
                              (pid,)).fetchone()
        if not me:
            return {pid}
        out = {pid}
        for r in state.db.execute("SELECT id, title, question FROM projects"):
            if (_norm(r["title"]).lower() == _norm(me["title"]).lower()
                    or _overlap(r["question"], me["question"]) >= 0.6):
                out.add(r["id"])
        return out
    except Exception:
        return {pid}


def project_repeat(state, cfg, payload, project_id, exclude_id=None):
    if project_id is None:
        return None
    thr = float(((cfg or {}).get("projects") or {}).get("repeat_overlap", 0.30))
    ids = sorted(_related_projects(state, project_id))
    q = ",".join("?" * len(ids))
    new = f"{(payload or {}).get('title') or ''}\n{(payload or {}).get('body') or ''}"
    best, best_ov = None, 0.0
    try:
        rows = state.db.execute(
            f"SELECT id, created_at, payload, status FROM actions WHERE kind='post'"
            f" AND project_id IN ({q}) AND id<>?"
            f" AND status IN ('executed','sent','sending','unknown','approved','queued')",
            (*ids, exclude_id or -1)).fetchall()
    except Exception:
        return None
    for r in rows:
        try:
            p = json.loads(r["payload"] or "{}")
        except ValueError:
            continue
        ov = _overlap(new, f"{p.get('title') or ''}\n{p.get('body') or ''}")
        if ov > best_ov:
            best, best_ov, best_p = r, ov, p
    if best is None or best_ov < thr:
        return None
    return (f"this post shares {best_ov:.0%} of its words with \"{best_p.get('title', '')[:80]}\" "
            f"(#{best['id']}, {best['created_at'][:10]}), from the same project. A "
            f"second post from one question has to say something the first did "
            f"not: a new result, a different question answered. If that is what "
            f"this is, cut what the first already said and lead with what is new. "
            f"If it is not, the project has said its piece: close it.")


def check(state, cfg, kind, payload, rationale="", exclude_id=None, project_id=None):
    """(outcome, why) for the first check this action fails, or None."""
    payload = payload or {}
    if kind == "listing_submission":
        why = listing_submitted(state, payload, exclude_id)
        if why:
            return "listing-submitted", why
        why = artifact_not_a_post(state, cfg, payload)
        if why:
            return "artifact-not-a-post", why
    if kind == "vote":
        why = voted_unread(state, payload)
        if why:
            return "voted-unread", why
    text = public_text(kind, payload)
    if text:
        # What riffle wrote, as against what it attached. A file one of its
        # builds made, appended or pasted byte for byte, is the file: a
        # "[[0, 2]]" index or a "# my library" comment in it is code, not a
        # claim. The hash checks still read everything.
        prose = mask_published_code(state, text)
        for outcome, fn in (("declaration-orphan", lambda: orphan_declaration(outside_fences(text))),
                            ("library-private", lambda: library_reference(state, cfg, kind, payload, prose)),
                            ("attachment-claimed", lambda: attachment_claimed(state, cfg, kind, payload, prose)),
                            ("hash-wrong-file", lambda: hash_wrong_file(state, text)),
                            ("hash-unpublished", lambda: hash_unpublished(state, cfg, kind, text)),
                            ("post-cannot-change", lambda: edit_promise(prose)),
                            ("claim-unbacked", lambda: claim_unbacked(state, prose)),
                            ("post-claimed", lambda: post_claimed(state, cfg, prose, kind)),
                            ("credited", lambda: credited(state, payload)),
                            ("claimed-before", lambda: claimed_before(state, prose)),
                            ("figure-assumed", lambda: figure_assumed(state, cfg, kind, payload, text))):
            why = fn()
            if why:
                return outcome, why
    if kind == "comment":
        why = wrong_addressee(state, payload)
        if why:
            return "wrong-addressee", why
    if kind == "post":
        if project_id is None:
            try:
                from agent import project
                _a = project.active(state)
                project_id = _a["id"] if _a else None
            except Exception:
                project_id = None
        why = project_repeat(state, cfg, payload, project_id, exclude_id)
        if why:
            return "project-repeat", why
    return None


def finish(kind, payload):
    """The payload as it goes to the square: each [[a/b*100]] after its figure
    becomes (a/b*100). The number check has read the declaration by now; a
    reader has no use for the brackets."""
    out = dict(payload or {})
    for f in TEXT_FIELDS.get(kind, ()):
        v = out.get(f)
        if isinstance(v, str) and "[[" in v:
            # Never inside a code block: there "[[0, 2]]" is code, and an
            # appended file has to go out byte for byte or its sha256 lies.
            parts, at = [], 0
            for m in FENCE_RE.finditer(v):
                parts.append(DECL_RE.sub(lambda d: "(" + d.group(1).strip() + ")", v[at:m.start()]))
                parts.append(m.group(0))
                at = m.end()
            parts.append(DECL_RE.sub(lambda d: "(" + d.group(1).strip() + ")", v[at:]))
            out[f] = "".join(parts)
    return out


# ------------------------------------------------- what the operator said

def _operator_texts(state, cfg):
    lo = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=OPERATOR_DAYS)
          ).strftime("%Y-%m-%dT%H:%M:%SZ")
    have = _tables(state)
    out = []
    try:
        if "instructions" in have:
            out += [r[0] for r in state.db.execute(
                "SELECT text FROM instructions WHERE ts > ? OR ts IS NULL", (lo,))]
        if "questions" in have:
            out += [f"{r[0]} {r[1]}" for r in state.db.execute(
                "SELECT question, answer FROM questions WHERE answer IS NOT NULL"
                " AND answered_at > ?", (lo,))]
        if "messages" in have:
            out += [r[0] for r in state.db.execute(
                "SELECT content FROM messages WHERE role='user' AND ts > ?", (lo,))]
        # What the chat summaries filed as his (memory.py labels each line
        # by speaker); the cycle's number check counts these as his words too.
        if "memories" in have:
            out += [r[0] for r in state.db.execute(
                "SELECT text FROM memories WHERE kind='operator'"
                " AND COALESCE(expired,0)=0")]
        for r in state.db.execute(
                "SELECT response FROM actions WHERE status='rejected' AND created_at > ?"
                " AND json_valid(response)", (lo,)):
            v = json.loads(r[0]) or {}
            if isinstance(v, dict) and v.get("by") == "you" and v.get("reason"):
                out.append(str(v["reason"]))
    except Exception:
        pass
    for n in (((cfg or {}).get("listings") or {}).get("ignore") or []):
        out.append(f"set aside: ignore listing {n} (listing-{n})")
    return [t for t in out if t]


def invented_instruction(state, cfg, rationale):
    """Why a rationale's claim about the operator has nothing behind it, or None."""
    text = rationale or ""
    cited = re.findall(r"\boperator:(\d+)\b", text)
    for m in _OPERATOR_RE.finditer(text):
        s = max(text.rfind(".", 0, m.start()), text.rfind("\n", 0, m.start())) + 1
        e = re.search(r"[.!?\n]", text[m.end():])
        sent = text[s:m.end() + (e.start() if e else len(text) - m.end())].strip()
        if cited:
            ok = False
            try:
                ok = all(state.db.execute(
                    "SELECT 1 FROM questions WHERE id=? AND answer IS NOT NULL",
                    (int(c),)).fetchone() for c in cited)
            except Exception:
                ok = False
            if ok:
                continue
        texts = [t.lower() for t in _operator_texts(state, cfg)]
        nums = set(re.findall(r"\b\d+\b", sent))
        if nums:
            ok = any(all(re.search(rf"\b{n}\b", t) for n in nums) for t in texts)
        else:
            words = {w for w in re.findall(r"[a-z][a-z0-9-]{3,}", sent.lower())
                     if w not in _STOP}
            ok = any(len({w for w in words if w in t}) >= 2 for t in texts)
        if not ok:
            return (f"your reasoning says \"{sent[:200]}\", and nothing your "
                    f"operator has written in the last {OPERATOR_DAYS} days says "
                    f"that: no instruction, no answer to a question of yours, no "
                    f"message, no reason he gave for turning something down. Do "
                    f"not act on an instruction you do not have. If you want "
                    f"one, ask_operator; if he did say it, cite it as "
                    f"operator:<id>.")
    return None
