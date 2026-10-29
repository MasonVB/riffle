"""External references in riffle's posts (operator's rule, 2026-10-29).

AT LEAST ONE POST IN FOUR CARRIES A REFERENCE. A reference is the URL of a
page riffle actually read with `read_page` (so it is in the library, kind
"page"), together with a passage QUOTED from that page that really appears in
its text. Both are checked here; neither is taken on riffle's word.

The count is of posts SENT in a row without one:
    0, 1 or 2   the next post should try to carry one; if it does not, it goes
                out anyway and the count goes up;
    3           the next post must carry one. Without it the post is refused
                and riffle is told to rework it around a source it can quote.
                After FAILSAFE refusals in a row it is let through, and the
                count resets: a failsafe, so posting can never stop for good.
A post that carries a reference resets the count to 0.

Comments are only nudged (in the system prompt), never checked here.
"""
import html
import json
import re
import urllib.parse

FREE_POSTS = 3      # posts in a row that may go out without a reference
FAILSAFE = 5        # refusals of the required post before it is let through

_STREAK = "post_ref_streak"
_FAILS = "post_ref_forced_fails"

# Text between double quotes of any common kind; single quotes are left out,
# since apostrophes make them unusable as delimiters.
_QUOTED = re.compile(r'["\u201c\u201e\u00ab]([^"\u201c\u201d\u201e\u00ab\u00bb]{12,1200})'
                     r'["\u201d\u00bb]')
_URL = re.compile(r"(?:https?://)?(?:[a-z0-9-]+\.)+[a-z]{2,}(?:/[^\s<>\"'\)\]]*)?", re.I)


def _norm_url(u):
    """Comparable form of a URL: no scheme, no www., host lowercased, no
    fragment, no trailing slash or trailing punctuation, percent-decoded."""
    u = (u or "").strip().rstrip(".,;:!?")
    if "://" not in u:
        u = "http://" + u
    p = urllib.parse.urlsplit(u)
    host = p.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    path = urllib.parse.unquote(p.path).rstrip("/")
    q = ("?" + urllib.parse.unquote(p.query)) if p.query else ""
    return host + path + q


def _norm_text(t):
    t = html.unescape(t or "")
    for a, b in (("\u2018", "'"), ("\u2019", "'"), ("\u201c", '"'), ("\u201d", '"'),
                 ("\u2013", "-"), ("\u2014", "-"), ("\u00a0", " ")):
        t = t.replace(a, b)
    return re.sub(r"\s+", " ", t).strip().lower()


def _fragments(quote):
    """A quote may elide with ... ; each part must be found on the page."""
    parts = re.split(r"\.\.\.|\u2026|\[\.\.\.\]", quote)
    out = [p.strip(" .,;:!?") for p in parts]
    return [p for p in out if len(p) >= 12]


def check(state, cfg, text):
    """(True, detail) if `text` carries a reference, else (False, why not).

    detail names the URL and the start of the quote that matched."""
    from agent import library
    urls = {_norm_url(m.group(0)) for m in _URL.finditer(text or "")}
    urls = {u for u in urls if "/" in u or "." in u}
    if not urls:
        return False, "it gives no URL"
    pages = {}
    for r in state.db.execute(
            "SELECT id, source FROM library WHERE kind='page' AND source IS NOT NULL"):
        pages.setdefault(_norm_url(r["source"]), r["id"])
    cited = [(u, pages[u]) for u in urls if u in pages]
    if not cited:
        return False, ("none of its URLs is a page you have read with read_page "
                       "(a reference must be one you actually read)")
    quotes = [q for q in (m.group(1) for m in _QUOTED.finditer(text or ""))
              if len(q.split()) >= 4]
    if not quotes:
        return False, "it cites a page you read but quotes nothing from it"
    root = (cfg.get("library") or {}).get("root", library.ROOT)
    for url, lid in cited:
        try:
            _row, page = library.read(state, int(lid), root, count=False)
        except Exception:
            continue
        hay = _norm_text(page)
        for q in quotes:
            frags = _fragments(q)
            if frags and all(_norm_text(f) in hay for f in frags):
                return True, f"{url} quoted: \"{q[:80]}\""
    return False, ("the quoted words are not on the page it cites; quote the "
                   "page's own wording")


def status(state):
    """(posts in a row without a reference, refusals of the required post)."""
    def _int(k):
        try:
            return int(state.note(k) or 0)
        except (TypeError, ValueError):
            return 0
    return _int(_STREAK), _int(_FAILS)


def must_reference(state):
    """True when the next post must carry a reference."""
    streak, fails = status(state)
    return streak >= FREE_POSTS and fails < FAILSAFE


def note_refused(state):
    _s, fails = status(state)
    state.note(_FAILS, str(fails + 1))


def after_post(state, cfg, action_id, log=None):
    """A post was SENT (cycle or dashboard). Update the count from what it said.

    Re-checked from the sent text rather than trusted from the proposal: the
    proposal could have been edited, and both send paths reach this."""
    try:
        r = state.db.execute("SELECT payload FROM actions WHERE id=?",
                             (action_id,)).fetchone()
        p = json.loads(r["payload"]) if r and r["payload"] else {}
    except Exception:
        p = {}
    text = "\n".join(str(p.get(k) or "") for k in ("title", "body", "url"))
    ok, detail = check(state, cfg, text)
    streak, fails = status(state)
    if ok:
        state.note(_STREAK, "0")
        state.note(_FAILS, "0")
        msg = f"post carried a reference ({detail}); the count is back to 0"
    elif streak >= FREE_POSTS:
        # Only the failsafe lets an unreferenced post out at this point.
        state.note(_STREAK, "0")
        state.note(_FAILS, "0")
        msg = (f"post went out without a reference after {fails} refusals "
               f"(the failsafe); the count is back to 0")
    else:
        state.note(_STREAK, str(streak + 1))
        msg = (f"post went out without a reference ({detail}); "
               f"{streak + 1} in a row")
    if log:
        log(msg)
    return ok
