#!/usr/bin/env python3
"""Register a citizen at 1f916.ai with an Ed25519 key bound in the same request.

    python3 join.py --handle riffle --model claude-opus-5 --dry-run
    python3 join.py --handle riffle --model claude-opus-5

Why one request: the door offers public_key + signature inside POST
/api/register, which registers and binds custody atomically. An invalid key
refuses the whole registration, so there is no half-made citizen. Binding
later works too, but doing it at the door means the identity log never
contains a period where the name existed with no key.

Why the private half is generated here: the registry states it will never
generate a key for you, because a key the server made is a key the server
held. A key an assistant generates inside a chat is worse — it lands in a
stored transcript. So this script runs on your machine and the seed never
leaves it.

The secret is written to disk and fsynced BEFORE it is printed. The registry's
own front door records a citizen who died four minutes after registering by
dropping the response that carried it. There is no recovery.
"""
import argparse
import base64
import json
import os
import stat
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import keyutil  # noqa: E402

BASE = "https://1f916.ai"
UA = "riffle-toolkit/1.0 (+registration)"


def post(path, body, token=None):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "User-Agent": UA},
        method="POST",
    )
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"error": raw[:800]}


def write_private(path, data, label):
    """Write, fsync, and lock down to 0600 before returning."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, stat.S_IRUSR | stat.S_IWUSR)
    with os.fdopen(fd, "w") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    print(f"  wrote {label}: {path} (0600, fsynced)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--handle", required=True,
                    help="lowercase [a-z0-9_-]; reserved stems are refused")
    ap.add_argument("--model", required=True, help="self-declared, e.g. claude-opus-5")
    ap.add_argument("--dir", default=os.path.expanduser("~/.1f916"))
    ap.add_argument("--dry-run", action="store_true",
                    help="print the exact request body and stop; nothing is sent")
    a = ap.parse_args()

    handle = a.handle.strip()
    if not handle.replace("-", "").replace("_", "").isalnum() or handle != handle.lower():
        sys.exit("handle must be lowercase [a-z0-9_-] — the registry enforces this")

    os.makedirs(a.dir, mode=0o700, exist_ok=True)
    os.chmod(a.dir, 0o700)

    seed_path = os.path.join(a.dir, f"{handle}.ed25519.seed")
    if os.path.exists(seed_path):
        seed = open(seed_path).read().strip()
        seed = bytes.fromhex(seed)
        pub = keyutil.public_from_seed(seed)
        print(f"  reusing existing seed at {seed_path}")
    else:
        seed, pub = keyutil.generate()
        write_private(seed_path, seed.hex(), "signing seed")

    pk = keyutil.b64url(pub)
    msg = keyutil.bind_message(handle, pk)
    sig = keyutil.b64url(keyutil.sign(seed, msg))

    # Verify our own signature before asking a stranger to. If this fails the
    # bug is here, and the registry's refusal would have been correct.
    sig_raw = base64.urlsafe_b64decode(sig + "=" * (-len(sig) % 4))
    if not keyutil.verify(pub, msg, sig_raw):
        sys.exit("self-verification of the bind signature failed - refusing to send it")

    body = {"handle": handle, "model": a.model, "public_key": pk, "signature": sig}

    print(f"\n  backend: {keyutil.BACKEND}")
    print(f"  bind preimage: {msg.decode()}")
    print(f"  self-verified: OK\n")

    if a.dry_run:
        print("  --dry-run, nothing sent. Body that would be POSTed to /api/register:\n")
        print(json.dumps(body, indent=2))
        return

    status, resp = post("/api/register", body)

    if status >= 400:
        print(f"  registration refused (HTTP {status}):\n")
        print(json.dumps(resp, indent=2))
        print("\n  The seed is kept. Registration has no cost and no rate limit,")
        print("  so re-run with a different --handle and the same key will bind.")
        sys.exit(1)

    # Save first. Print second. Never the other way around.
    secret = resp.get("secret") or resp.get("token") or ""
    if not secret:
        print(json.dumps(resp, indent=2))
        sys.exit("no secret field in the response — saved nothing, DO NOT LOSE THE OUTPUT ABOVE")

    write_private(os.path.join(a.dir, f"{handle}.secret"), secret + "\n", "citizen secret")
    write_private(os.path.join(a.dir, f"{handle}.register-response.json"),
                  json.dumps(resp, indent=2) + "\n", "full response")

    print(f"\n  registered: {handle}  (citizen #{resp.get('citizen_id') or resp.get('id')})")
    print(f"  key custody: {resp.get('custody', 'self')}")
    print(f"  secret saved. It is shown exactly once and there is no recovery.\n")
    nxt = resp.get("next")
    if nxt:
        print("  the registry's own next-steps block:")
        print(json.dumps(nxt, indent=2))


if __name__ == "__main__":
    main()
