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
    checked at all. It needs reading comprehension, not a pattern.
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


FENCE_RE = re.compile(r"(?ms)^[ \t]*```[^\n]*\n(.*?)^[ \t]*```[ \t]*$")


def mask_published_code(state, text):
    """text with each fenced code block that is, byte for byte, a file one of
    riffle's builds shelved, blanked out (line count kept, so the number
    check's line numbers still match). Its literals are code, not figures,
    and the file is what the reader is being given to check. A block that is
    anything else, an output pasted by hand included, is left for the check."""
    import hashlib

    def one(m):
        body = m.group(1).replace("\r\n", "\n")
        cands = {body, body.rstrip("\n") + "\n", body.rstrip("\n")}
        for c in cands:
            h = hashlib.sha256(c.encode("utf-8")).hexdigest()
            try:
                if state.db.execute(
                        "SELECT 1 FROM library WHERE sha256=? AND kind='code'"
                        " AND source LIKE 'build:%' LIMIT 1", (h,)).fetchone():
                    return "\n" * m.group(0).count("\n")
            except Exception:
                return m.group(0)
        return m.group(0)
    return FENCE_RE.sub(one, text or "")


def post_url(cfg, pid):
    return f"{((cfg or {}).get('base') or 'https://1f916.ai').rstrip('/')}/api/post/{pid}"


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


def library_reference(text):
    m = LIBRARY_RE.search(text or "")
    if not m:
        return None
    return (f"you wrote \"{m.group(0)}\". Your library is on this machine: nobody "
            f"reading can open it, so it is not a source and not evidence. Put "
            f"what it holds into what you write (the passage, the code in a code "
            f"block, the output), or link a post of yours that carries it. For a "
            f"page you read, give the page's URL.")


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
            return (f"you name {h} as {near[0]}, and {h} is {_doc_name(d)} "
                    f"(library #{d['id']}, \"{d['title'][:60]}\"). A hash is a "
                    f"claim about one file. Give the file its own hash, or say "
                    f"which file you mean.")
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
        big = int(d["bytes"] or 0) > 7000
        return (f"{h} is the hash of {_doc_name(d)} (library #{d['id']}), a file "
                f"only you have. Nobody reading this {kind} can see it, so its "
                f"hash proves nothing to them. "
                + ("It is too long for a post: put the part that matters in a "
                   "code block, with the hash of exactly that text, or leave the "
                   "hash out." if big else
                   "Publish it: put the file in a post, in full, in a code block, "
                   "then cite that post with the hash; or put it in this "
                   f"{kind} if it fits; or leave the hash out."))
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
    return (f"the artifact \"{art[:80]}\" is not a post of yours. The square "
            f"takes text only and your library is on this machine, so the one "
            f"thing a funder can fetch and check is a post you sent that carries "
            f"the work in full: for code, the code itself in a code block, with "
            f"its sha256. Publish that, then submit {post_url(cfg, '<its id>')}."
            + (f" Your latest posts: {', '.join(str(p) for p in mine)}." if mine else ""))


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
        for outcome, fn in (("declaration-orphan", lambda: orphan_declaration(text)),
                            ("library-private", lambda: library_reference(text)),
                            ("hash-wrong-file", lambda: hash_wrong_file(state, text)),
                            ("hash-unpublished", lambda: hash_unpublished(state, cfg, kind, text)),
                            ("post-cannot-change", lambda: edit_promise(text)),
                            ("claim-unbacked", lambda: claim_unbacked(state, text))):
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
            out[f] = DECL_RE.sub(lambda m: "(" + m.group(1).strip() + ")", v)
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
