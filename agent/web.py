"""Search the web and read pages, for questions the square cannot answer.

PROVIDERS, in the order you would probably want them:

  wikipedia  no key, no service, works the moment this file lands. Narrow, but
             honest about what it is and enough for a great many factual
             questions.
  searxng    your own metasearch instance. Nothing leaves your network except
             the searches themselves, and no third party sees your key.
  brave      Brave Search API. One key, no service to run, a free tier.

Configured in config.yaml under `web:`. With none set the tools report that
plainly instead of degrading into something that looks like an answer.

THREE THINGS THIS FILE IS CAREFUL ABOUT

1. SSRF. A URL can arrive from a board post, a search result, or a page that
   links onward — none of which you wrote. `http://127.0.0.1/api/...` or
   `http://169.254.169.254/` would otherwise let untrusted text steer a fetch
   at your own network. Every hostname is resolved and every resulting address
   checked before the request; loopback, private, link-local, multicast and
   reserved ranges are refused. Redirects are followed manually so the same
   check runs on each hop, because a public host can redirect to a private one.

2. SIZE. Pages are truncated hard. The composer has a 12,288-token context and
   generates at about eight tokens a second; a page that fills the window costs
   minutes and pushes out the conversation that prompted the search.

3. PROVENANCE. Every result carries its URL, so the agent can say where a claim
   came from and you can check it. A search result is a claim someone published,
   not a fact.
"""
import gzip
import html
import io
import ipaddress
import json
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Safari/537.36 riffle-agent/1.0")

MAX_PAGE_BYTES = 800_000
MAX_TEXT_CHARS = 3500
SNIPPET_CHARS = 240


class Refused(Exception):
    pass


# Ranges ipaddress does not flag but which are still "your network" here.
# Python 3.13 reclassified RFC 6598 shared address space (100.64.0.0/10) as
# NOT private — and that is precisely where Tailscale lives, so without this
# an untrusted page could have steered a fetch at any node on the tailnet.
# The rest are RFC 5735 special-use blocks that no legitimate search result
# will ever point at.
EXTRA_BLOCKED = [ipaddress.ip_network(n) for n in (
    "100.64.0.0/10",      # CGNAT / Tailscale
    "0.0.0.0/8",          # "this network"
    "192.0.0.0/24",       # IETF protocol assignments
    "198.18.0.0/15",      # benchmarking
    "fc00::/7",           # IPv6 unique local
    "fe80::/10",          # IPv6 link-local
)]


# ---------------------------------------------------------------- SSRF guard
def _addresses(host):
    try:
        return [ipaddress.ip_address(ai[4][0])
                for ai in socket.getaddrinfo(host, None)]
    except (socket.gaierror, ValueError):
        raise Refused(f"cannot resolve {host!r}")


def check_url(url):
    """Return a normalised URL or raise Refused. Call on EVERY hop."""
    p = urllib.parse.urlparse(url)
    if p.scheme not in ("http", "https"):
        raise Refused(f"only http and https are allowed, not {p.scheme!r}")
    if not p.hostname:
        raise Refused("no host in URL")
    for ip in _addresses(p.hostname):
        blocked = (ip.is_private or ip.is_loopback or ip.is_link_local
                   or ip.is_multicast or ip.is_reserved or ip.is_unspecified
                   or any(ip in net for net in EXTRA_BLOCKED
                          if net.version == ip.version))
        if blocked:
            raise Refused(f"{p.hostname} resolves to {ip}, which is inside your "
                          f"own network; refusing")
    return url


def _open(url, timeout=20, depth=0):
    """Fetch with redirects followed by hand, so each hop is re-checked."""
    if depth > 4:
        raise Refused("too many redirects")
    check_url(url)

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None

    op = urllib.request.build_opener(NoRedirect)
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept-Encoding": "gzip",
        "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8"})
    try:
        return op.open(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        if e.code in (301, 302, 303, 307, 308):
            loc = e.headers.get("Location")
            if not loc:
                raise Refused(f"redirect with no target ({e.code})")
            return _open(urllib.parse.urljoin(url, loc), timeout, depth + 1)
        raise


def _body(resp):
    raw = resp.read(MAX_PAGE_BYTES)
    if resp.headers.get("Content-Encoding") == "gzip":
        try:
            raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read(MAX_PAGE_BYTES)
        except OSError:
            pass
    charset = resp.headers.get_content_charset() or "utf-8"
    return raw.decode(charset, "replace")


# ------------------------------------------------------------ HTML to text
class _Text(HTMLParser):
    SKIP = {"script", "style", "nav", "header", "footer", "aside", "form",
            "noscript", "svg", "button", "select"}
    BREAK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
             "section", "article", "blockquote"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.depth, self.title = [], 0, ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.depth += 1
        elif tag == "title":
            self._in_title = True
        elif tag in self.BREAK:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.depth:
            self.depth -= 1
        elif tag == "title":
            self._in_title = False
        elif tag in self.BREAK:
            self.out.append("\n")

    def handle_data(self, d):
        if self._in_title:
            self.title += d
        elif not self.depth:
            self.out.append(d)


def to_text(raw_html):
    p = _Text()
    try:
        p.feed(raw_html)
    except Exception:
        pass
    text = "".join(p.out)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return p.title.strip(), text.strip()


# ------------------------------------------------------------------ search
def _wikipedia(query, n):
    api = ("https://en.wikipedia.org/w/api.php?action=query&list=search&format=json"
           f"&srlimit={n}&srsearch={urllib.parse.quote(query)}")
    data = json.loads(_body(_open(api)))
    out = []
    for r in data.get("query", {}).get("search", []):
        _t, snip = to_text(r.get("snippet", ""))
        out.append({"title": r["title"],
                    "url": "https://en.wikipedia.org/wiki/"
                           + urllib.parse.quote(r["title"].replace(" ", "_")),
                    "snippet": snip[:SNIPPET_CHARS]})
    return out


def _searxng(cfg, query, n):
    base = cfg["url"].rstrip("/")
    url = f"{base}/search?q={urllib.parse.quote(query)}&format=json"
    # A local instance is exactly what check_url refuses, so bypass the guard
    # here only: this address came from your config file, not from a page.
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    data = json.loads(urllib.request.urlopen(req, timeout=20).read().decode())
    return [{"title": r.get("title", ""), "url": r.get("url", ""),
             "snippet": (r.get("content") or "")[:SNIPPET_CHARS]}
            for r in data.get("results", [])[:n]]


def _brave(cfg, query, n):
    url = ("https://api.search.brave.com/res/v1/web/search?count="
           f"{n}&q={urllib.parse.quote(query)}")
    req = urllib.request.Request(url, headers={
        "Accept": "application/json", "X-Subscription-Token": cfg["api_key"]})
    data = json.loads(urllib.request.urlopen(req, timeout=20).read().decode())
    out = []
    for r in (data.get("web", {}) or {}).get("results", [])[:n]:
        _t, snip = to_text(r.get("description", ""))
        out.append({"title": html.unescape(r.get("title", "")),
                    "url": r.get("url", ""), "snippet": snip[:SNIPPET_CHARS]})
    return out


def search(cfg, query, n=5):
    """Returns (results, note). Never raises."""
    w = (cfg.get("web") or {})
    if not w.get("enabled"):
        return [], "web search is turned off in config.yaml"
    prov = w.get("provider", "wikipedia")
    try:
        if prov == "wikipedia":
            return _wikipedia(query, n), "wikipedia only"
        if prov == "searxng":
            if not w.get("url"):
                return [], "searxng selected but no url configured"
            return _searxng(w, query, n), None
        if prov == "brave":
            if not w.get("api_key"):
                return [], "brave selected but no api_key configured"
            return _brave(w, query, n), None
        return [], f"unknown search provider {prov!r}"
    except Refused as e:
        return [], str(e)
    except Exception as e:
        return [], f"{type(e).__name__}: {e}"[:180]


def read(url, limit=MAX_TEXT_CHARS):
    """Fetch one page as text. Returns (title, text, note)."""
    try:
        resp = _open(url)
    except Refused as e:
        return "", "", str(e)
    except Exception as e:
        return "", "", f"{type(e).__name__}: {e}"[:180]
    ctype = (resp.headers.get_content_type() or "").lower()
    if ctype not in ("text/html", "text/plain", "application/xhtml+xml",
                     "application/json"):
        return "", "", f"not a readable page ({ctype})"
    body = _body(resp)
    if ctype == "application/json":
        return "", body[:limit], None
    title, text = to_text(body)
    note = None
    if len(text) > limit:
        text, note = text[:limit], f"truncated at {limit} characters"
    return title, text, note
