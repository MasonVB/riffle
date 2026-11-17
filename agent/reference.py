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

Comments are only nudged (in the system prompt) to carry a reference; their
links are checked by `unread_links` (audit F7, 2026-11-10).

EVERY LINK ON ITS OWN (audit F7). `check` passes when any one URL in a post is
a page read and any one quote is on it, so a second link rode along on the
first: a post quoting sqlite.org correctly also cited a page on a domain that
does not exist, and one never read, and was sent. `each_link` holds every
outside link in a post to the rule: a page read with read_page, and a passage
from THAT page quoted. A link written without https:// is a link too.
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


def _pages(state):
    """{normalised URL: library id} of every page riffle read."""
    pages = {}
    for r in state.db.execute(
            "SELECT id, source FROM library WHERE kind='page' AND source IS NOT NULL"):
        pages.setdefault(_norm_url(r["source"]), r["id"])
    return pages


def _quotes(text):
    return [q for q in (m.group(1) for m in _QUOTED.finditer(text or ""))
            if len(q.split()) >= 4]


def _quoted_on(state, cfg, lid, quotes):
    """The first quote whose every fragment is on library page `lid`, or None."""
    from agent import library
    root = (cfg.get("library") or {}).get("root", library.ROOT)
    try:
        _row, page = library.read(state, int(lid), root, count=False)
    except Exception:
        return None
    hay = _norm_text(page)
    for q in quotes:
        frags = _fragments(q)
        if frags and all(_norm_text(f) in hay for f in frags):
            return q
    return None


def check(state, cfg, text):
    """(True, detail) if `text` carries a reference, else (False, why not).

    detail names the URL and the start of the quote that matched."""
    urls = {_norm_url(m.group(0)) for m in _URL.finditer(text or "")}
    urls = {u for u in urls if "/" in u or "." in u}
    if not urls:
        return False, "it gives no URL"
    pages = _pages(state)
    cited = [(u, pages[u]) for u in urls if u in pages]
    if not cited:
        return False, ("none of its URLs is a page you have read with read_page "
                       "(a reference must be one you actually read)")
    quotes = _quotes(text)
    if not quotes:
        return False, "it cites a page you read but quotes nothing from it"
    for url, lid in cited:
        q = _quoted_on(state, cfg, lid, quotes)
        if q:
            return True, f"{url} quoted: \"{q[:80]}\""
    return False, ("the quoted words are not on the page it cites; quote the "
                   "page's own wording")


# AN OUTSIDE LINK (F7). With a scheme, any host. Without one, only host.tld/path
# where the last label is not a file extension: "1f916.square/docs" is a link,
# "cycle.py" and "src/attestations.ts" are not. Not after @ . / - or a word
# character, so an e-mail address or a path's middle never starts one.
_LINK = re.compile(r"(?<![\w@./-])(https?://)?((?:[a-z0-9-]+\.)+([a-z][a-z0-9-]*[a-z]))"
                   r"(?::\d+)?(/[^\s<>\"'\)\]]*)?", re.I)
_FILE_EXT = {"py", "md", "ts", "js", "json", "txt", "sh", "yaml", "yml", "rs", "go",
             "html", "htm", "csv", "sql", "toml", "cfg", "ini", "log", "c", "h",
             "cpp", "hpp", "java", "rb", "pl", "php", "css", "xml", "pdf", "png",
             "jpg", "gz", "zip", "tar", "lock", "service", "conf", "db", "sqlite",
             "ipynb", "tex", "bib", "mjs", "cjs", "tsx", "jsx", "env", "example"}


def _host(u):
    h = urllib.parse.urlsplit(u if "://" in u else "http://" + u).hostname or ""
    return h[4:] if h.startswith("www.") else h


def outside_links(text, home=""):
    """Every link in text that is not to the registry (`home`, a host), in
    order, each once, trailing punctuation dropped."""
    home = (home or "").lower()
    home = home[4:] if home.startswith("www.") else home
    out = []
    for m in _LINK.finditer(text or ""):
        scheme, tld, path = m.group(1), m.group(3).lower(), m.group(4)
        if not scheme and (not path or path == "/" or tld in _FILE_EXT):
            continue
        u = m.group(0).rstrip(".,;:!?")
        h = _host(u)
        if home and (h == home or h.endswith("." + home)):
            continue
        if u not in out:
            out.append(u)
    return out


def each_link(state, cfg, text, links):
    """[(url, why)] for each link in `links` that is not a page riffle read
    with a passage from that page quoted in `text` (F7)."""
    pages = _pages(state)
    quotes = _quotes(text)
    bad = []
    for u in links:
        lid = pages.get(_norm_url(u))
        if lid is None:
            bad.append((u, "it is not a page you read with read_page"))
        elif not quotes:
            bad.append((u, "the post quotes nothing from it"))
        elif not _quoted_on(state, cfg, lid, quotes):
            bad.append((u, "nothing the post quotes is on that page"))
    return bad


def unread_links(state, links, read):
    """The links in `links` riffle has no ground for (F7, for everything that
    is not a post): no page on that host was ever read with read_page, and
    the address appears nowhere in `read` (what riffle read this cycle and
    the pages it fetched)."""
    hosts = {_host(r["source"]) for r in state.db.execute(
        "SELECT source FROM library WHERE kind='page' AND source IS NOT NULL")}
    hay = re.sub(r"https?://(www\.)?", "", (read or "").lower())
    bad = []
    for u in links:
        if _host(u) in hosts:
            continue
        bare = re.sub(r"^https?://(www\.)?", "", u.lower()).rstrip("/")
        if bare and bare in hay:
            continue
        bad.append(u)
    return bad


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
