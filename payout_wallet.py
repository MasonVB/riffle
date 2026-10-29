#!/usr/bin/env python3
"""Prove riffle's payout wallet to the registry, once.

    python3 /opt/riffle/payout_wallet.py            # proof valid 364 days
    python3 /opt/riffle/payout_wallet.py --days 90

Run it as yourself, not as root. It uses sudo for exactly two things: asking
riffle-sign for riffle's half of the proof, and reading riffle's registry
secret to submit it.

WHAT THE PROOF IS. One message,

    1f916.payout-wallet.v1:<handle>:8453:<address>:<expiry>

signed twice: by the wallet in /etc/riffle/payout.conf (EIP-191, as a plain
"sign message" in your wallet app) and by riffle's citizen key. After the
registry records it, riffle's key alone can bind payouts for listings to
that address (each binding still names the listing's exact price, valid 30
days at most). The proof itself authorizes no payment and creates no
entitlement; it is revocable at any time.

ORDER. riffle-sign fetches the registry's preimage and checks it against
payout.conf before signing; this tool checks the same string again, shows it
to you, and only then asks for your wallet's signature. If anything differs,
it stops before anything is submitted.
"""
import argparse
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

CONF = "/etc/riffle/payout.conf"
BASE = "https://1f916.ai"
CHAIN_ID = 8453
SIGNER = ["sudo", "-u", "riffle-signer", "/usr/local/bin/riffle-sign"]
ADDRESS_RE = re.compile(r"0x[0-9a-fA-F]{40}")
WALLET_SIG_RE = re.compile(r"0x[0-9a-fA-F]{130}")


def die(msg):
    sys.exit(f"payout_wallet: {msg}")


def conf():
    out = {}
    try:
        with open(CONF) as f:
            for line in f:
                line = line.split("#", 1)[0].strip()
                if "=" in line:
                    k, v = line.split("=", 1)
                    out[k.strip()] = v.strip()
    except OSError as e:
        die(f"cannot read {CONF}: {e}")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--days", type=int, default=364,
                    help="how long the proof stays valid (1-364; the registry "
                         "allows at most a year)")
    ap.add_argument("--data-dir", default="/var/lib/riffle")
    a = ap.parse_args()
    if not 1 <= a.days <= 364:
        die("--days must be 1-364")

    c = conf()
    handle, address = c.get("handle", ""), c.get("address", "").lower()
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", handle):
        die(f"no usable handle in {CONF}")
    if not ADDRESS_RE.fullmatch(address) or int(address, 16) == 0:
        die(f"no usable address in {CONF} (the placeholder 0x000... is refused)")
    expiry = int(time.time()) + a.days * 86400

    # riffle's half first: riffle-sign fetches and checks the preimage itself.
    r = subprocess.run(SIGNER + ["payout-wallet", f"--expiry={expiry}"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        die(f"riffle-sign refused: {(r.stderr or '').strip()}")
    try:
        cit = json.loads(r.stdout)
        pre = cit["preimage"]
        cit_sig, cit_pub = cit["citizen_signature"], cit["citizen_public_key"]
    except (ValueError, KeyError) as e:
        die(f"unexpected riffle-sign output: {e}")
    expect = f"1f916.payout-wallet.v1:{handle}:{CHAIN_ID}:{address}:{expiry}"
    if pre != expect:
        die(f"preimage {pre!r} is not the expected {expect!r}; nothing submitted")

    print("\nSign this EXACT text as a plain message (EIP-191 / personal_sign),")
    print(f"with the wallet that owns {address}:\n")
    print(f"    {pre}\n")
    print("Check your wallet shows exactly that text and nothing else.")
    sig = input("Paste the wallet's signature (0x followed by 130 hex characters): ").strip()
    if not WALLET_SIG_RE.fullmatch(sig):
        die("that is not a 65-byte 0x-prefixed signature; nothing submitted")

    r = subprocess.run(["sudo", "-u", "riffle", "cat", f"{a.data_dir}/{handle}.secret"],
                       capture_output=True, text=True)
    secret = r.stdout.strip()
    if r.returncode != 0 or not secret:
        die(f"cannot read riffle's secret: {(r.stderr or '').strip()}")

    body = {"version": "1f916.payout-wallet.v1", "handle": handle,
            "chain_id": CHAIN_ID, "address": address, "expiry": expiry,
            "preimage": pre, "signature": sig,
            "citizen_public_key": cit_pub, "citizen_signature": cit_sig}
    req = urllib.request.Request(
        f"{BASE}/api/payout-wallets", data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {secret}"})
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            out = json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        die(f"the registry refused it (HTTP {e.code}): "
            f"{e.read().decode('utf-8', 'replace')[:600]}")
    except urllib.error.URLError as e:
        die(f"could not reach the registry: {e}")
    print("\nRecorded. The registry answered:")
    print(json.dumps(out, indent=1)[:1500])


if __name__ == "__main__":
    main()
