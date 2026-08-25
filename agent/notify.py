"""Push notification when something needs your tap — inside your waking hours.

    weekdays  07:00 - 22:00
    weekends  10:00 - 22:00

DEFERRED, NOT DROPPED. A proposal queued at 03:00 does not vanish; it is
marked un-notified and the next cycle that wakes inside the window sends it.
With an hourly timer that means at most an hour's delay after the window
opens, and no silent loss — which matters, because the whole point of the
queue is that nothing reaches the square without you.

The `notified` flag lives on the action row, so a proposal is announced once
and only once no matter how many cycles pass before you act on it.

Failures here are non-fatal by construction. If Pushover is down or the keys
are wrong, the cycle logs it and carries on — a notification is a convenience,
and the queue in the dashboard is the actual record.
"""
import datetime as dt
import json
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.pushover.net/1/messages.json"


def _tz(name):
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    except Exception:
        return dt.timezone.utc


def in_window(cfg, now=None):
    """True if local time falls inside the configured waking hours."""
    n = cfg.get("notify") or {}
    if not n.get("enabled"):
        return False
    tz = _tz(n.get("timezone", "America/Los_Angeles"))
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(tz)
    w = n.get("windows") or {}
    # Monday is 0; Saturday and Sunday are 5 and 6.
    lo, hi = (w.get("weekend") or [10, 22]) if now.weekday() >= 5 \
        else (w.get("weekday") or [7, 22])
    return lo <= now.hour < hi


def next_window_open(cfg, now=None):
    """When the window next opens, for logging a deferral honestly."""
    n = cfg.get("notify") or {}
    tz = _tz(n.get("timezone", "America/Los_Angeles"))
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(tz)
    w = n.get("windows") or {}
    for add in range(0, 8):
        day = now + dt.timedelta(days=add)
        lo, _hi = (w.get("weekend") or [10, 22]) if day.weekday() >= 5 \
            else (w.get("weekday") or [7, 22])
        cand = day.replace(hour=lo, minute=0, second=0, microsecond=0)
        if cand > now:
            return cand
    return None


def send(cfg, title, message, url=None, priority=0):
    """Post to Pushover. Returns (ok, detail); never raises."""
    n = cfg.get("notify") or {}
    user, token = n.get("user_key"), n.get("api_token")
    if not user or not token:
        return False, "pushover keys not configured"
    data = {"token": token, "user": user, "title": title[:250],
            "message": message[:1024], "priority": priority,
            # html=1 is what makes the <a href> links above tappable.
            "html": 1}
    if url:
        data["url"] = url
        data["url_title"] = "Open riffle"
    try:
        req = urllib.request.Request(
            API, data=urllib.parse.urlencode(data).encode(), method="POST")
        with urllib.request.urlopen(req, timeout=20) as r:
            body = json.loads(r.read().decode())
            return body.get("status") == 1, str(body)[:200]
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: {e.read().decode()[:160]}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"[:160]


def dash_url(cfg):
    host = (cfg.get("notify") or {}).get("dash_host") or "riffle"
    port = cfg.get("dash", {}).get("port", 8917)
    return f"http://{host}/" if int(port) == 80 else f"http://{host}:{port}/"


def announce_pending(state, cfg, log):
    """Notify about queued proposals not yet announced. Call once per cycle.

    Handles both the fresh case and the backlog case with the same code: the
    query is 'queued and not yet notified', so a proposal made at 03:00 and one
    made a moment ago are treated identically once the window is open.
    """
    n = cfg.get("notify") or {}
    if not n.get("enabled"):
        return 0
    rows = state.db.execute(
        "SELECT id, kind, drive, rationale, created_at FROM actions"
        " WHERE status='queued' AND COALESCE(notified,0)=0 ORDER BY id").fetchall()
    if not rows:
        return 0
    if not in_window(cfg):
        nxt = next_window_open(cfg)
        log(f"{len(rows)} proposal(s) waiting; outside notify window, holding until "
            f"{nxt:%a %H:%M} local" if nxt else "outside notify window", level="info")
        return 0

    # Pushover has no action-button API. It does render <a href> when html=1,
    # so the notification carries a tap-through link per proposal. The link
    # opens a read-only review page rather than acting on GET: a URL that
    # posts to the square is a URL that fires on any stray follow.
    from agent.dash import link_token
    base = dash_url(cfg).rstrip("/")

    def review(aid):
        return f"{base}/act?id={aid}&t={link_token(state, aid)}"

    if len(rows) == 1:
        r = rows[0]
        title = f"riffle wants to {r['kind']}"
        msg = (f"[{r['drive']}] {r['rationale'][:600]}\n\n"
               f'<a href="{review(r["id"])}">Review and decide &#8594;</a>')
    else:
        title = f"riffle has {len(rows)} proposals waiting"
        msg = "\n\n".join(
            f'{r["kind"]} ({r["drive"]}): {r["rationale"][:150]}\n'
            f'<a href="{review(r["id"])}">decide &#8594;</a>' for r in rows[:5])
        if len(rows) > 5:
            msg += f"\n\n…and {len(rows) - 5} more"

    ok, detail = send(cfg, title, msg, url=dash_url(cfg))
    if ok:
        state.db.execute(
            f"UPDATE actions SET notified=1 WHERE id IN "
            f"({','.join('?' * len(rows))})", [r["id"] for r in rows])
        state.db.commit()
        log(f"notified you about {len(rows)} queued proposal(s)")
        return len(rows)
    log(f"pushover failed ({detail}); the queue is unaffected", level="warn")
    return 0


def alarm(state, cfg, text, log):
    """Chain alarms ignore the window. A rewritten ledger is not a convenience."""
    if not (cfg.get("notify") or {}).get("enabled"):
        return
    ok, detail = send(cfg, "riffle: WITNESS ALARM", text[:900],
                      url=dash_url(cfg), priority=1)
    if not ok:
        log(f"alarm notification failed: {detail}", level="warn")
