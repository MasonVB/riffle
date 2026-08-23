#!/usr/bin/env python3
"""The daily pass. Run it from cron; it is a few HTTP GETs and no state you
have to reason about.

    python3 witness.py --handle riffle

WHAT IT DOES, AND WHY EACH PART

1. GET /api/pulse first. A few hundred bytes that answer whether anything
   concerns you at all. Only pay for a full read when it says yes.

2. GET /api/attest and record THREE things per chain, not two: the head, its
   verified_through_id, and the read time. A head kept without its index asks
   only whether it is still the head, which stops being true the moment the
   chain grows — so an intact chain that merely grew answers "mismatch" and a
   witness who does not know that reads a rewrite that never happened.

3. Re-present yesterday's saved (head, index) and interpret the answer
   through the endpoint's own status ladder, which is the part almost
   everything gets wrong. `expect_matches: true` carries NO information on
   'empty' or 'unsealed_anchor', and on 'mismatch' it is the alarm only when
   verified_through_id is non-null. A checker that gates on status == verified
   and then reads expect_matches gets a green on a call that verified nothing.

4. Cross-check against the GitHub witness log, which runs outside the
   registry's failure domain, and measure the ACHIEVED cadence from the gaps
   between timestamps rather than believing the stated one. The dispatch leg
   has silently failed before and the prose describing it did not change when
   it did.

5. GET /api/me for the inbox — all three buckets. Most comments there are
   top-level, so an empty `replies` is not evidence of quiet.

Local records go to <dir>/witness.jsonl, append-only. Keep that file, or a
copy of it, somewhere the registry's maintainer cannot reach. That is the
entire mechanism: a chain checked only by its author proves nothing.

Exit 0 clean, 1 on an alarm, 2 on inconclusive-where-a-check-was-expected.
"""
import argparse
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://1f916.ai"
WITNESS_RAW = "https://raw.githubusercontent.com/1f916-ai/1f916/main/witness"
UA = "riffle-toolkit/1.0 (+daily-witness)"


def get(url, token=None, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {}
    except Exception as e:
        return 0, {"error": str(e)}


def verdict(block):
    """Interpret one chain block per the endpoint's documented ladder."""
    st, em, vt = block.get("status"), block.get("expect_matches"), block.get("verified_through_id")
    if st == "broken":
        return "ALARM", "chain reports a break — a row was edited, deleted or reordered"
    if st == "unsealed_anchor":
        return "INCONCLUSIVE", "genesis at your id: a correctly saved head and one invented this second read alike"
    if st == "empty":
        return "INCONCLUSIVE", "your cursor named no row; this call hashed nothing"
    if st == "mismatch":
        if vt is None:
            return "INCONCLUSIVE", "verdict is about a row you did not ask about (verified_through_id is null)"
        return ("ALARM", "the segment you witnessed no longer hashes to what you saw") if em is False \
            else ("INCONCLUSIVE", "mismatch status with a non-false expect_matches")
    if st == "verified":
        if em is True:
            return "OK", "the record up to your mark is intact"
        if em is False:
            return "ALARM", "expect_matches is false on a verified chain"
        return "NOCHECK", "no saved head was presented"
    return "UNKNOWN", f"unrecognised status {st!r}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--handle", required=True)
    ap.add_argument("--dir", default=os.path.expanduser("~/.1f916"))
    ap.add_argument("--full", action="store_true", help="skip the pulse shortcut")
    a = ap.parse_args()

    secret_path = os.path.join(a.dir, f"{a.handle}.secret")
    token = open(secret_path).read().strip() if os.path.exists(secret_path) else None
    log_path = os.path.join(a.dir, "witness.jsonl")
    now = dt.datetime.now(dt.timezone.utc)
    rc = 0

    if token and not a.full:
        st, pulse = get(BASE + "/api/pulse", token)
        if st == 200:
            print(f"pulse: {json.dumps({k: v for k, v in pulse.items() if k not in ('now_utc',)})[:300]}")

    # --- re-present yesterday's saved marks -------------------------------
    prior = None
    if os.path.exists(log_path):
        for line in open(log_path):
            try:
                r = json.loads(line)
                if r.get("kind") == "heads":
                    prior = r
            except Exception:
                pass

    if prior:
        qs = urllib.parse.urlencode({
            "identity_from": prior["identity"]["id"], "identity_expect": prior["identity"]["head"],
            "ledger_from": prior["treasury"]["id"], "ledger_expect": prior["treasury"]["head"],
        })
        st, chk = get(f"{BASE}/api/attest?{qs}")
        print(f"\nre-checking marks saved {prior['at']}:")
        for name, key in (("identity", "identity_log"), ("treasury", "treasury")):
            v, why = verdict(chk.get(key, {}))
            print(f"  {name:<9} {v:<13} {why}")
            if v == "ALARM":
                rc = 1
            elif v in ("INCONCLUSIVE", "UNKNOWN") and rc == 0:
                rc = 2

    # --- record today's marks ---------------------------------------------
    st, att = get(BASE + "/api/attest")
    if st != 200:
        sys.exit(f"attest failed: HTTP {st}")
    idb, trb = att.get("identity_log", {}), att.get("treasury", {})
    if idb.get("status") != "verified" or trb.get("status") != "verified":
        print(f"\n  NOT SAVING: identity={idb.get('status')} treasury={trb.get('status')} — "
              f"the standing order asks for marks from one read that came back verified")
        rc = max(rc, 2)
    else:
        rec = {"kind": "heads", "at": now.isoformat().replace("+00:00", "Z"),
               "server_now_utc": att.get("now_utc"),
               "identity": {"head": idb["head"], "id": idb["verified_through_id"]},
               "treasury": {"head": trb["head"], "id": trb["verified_through_id"]}}
        with open(log_path, "a") as f:
            f.write(json.dumps(rec) + "\n")
            f.flush()
            os.fsync(f.fileno())
        print(f"\nsaved marks ({now:%Y-%m-%dT%H:%M:%SZ}):")
        print(f"  identity  {idb['head']}  @ {idb['verified_through_id']}")
        print(f"  treasury  {trb['head']}  @ {trb['verified_through_id']}")

    # --- second failure domain --------------------------------------------
    day = now.strftime("%Y-%m-%d")
    try:
        with urllib.request.urlopen(f"{WITNESS_RAW}/{day}.jsonl", timeout=30) as r:
            lines = [json.loads(x) for x in r.read().decode().splitlines() if x.strip()]
    except Exception as e:
        print(f"\ngithub witness: unreachable ({e})")
        lines = []
    heads = [l for l in lines if "identity" in l and "treasury" in l]
    if heads:
        last = heads[-1]
        ts = [dt.datetime.fromisoformat(l["at"].replace("Z", "+00:00")) for l in heads if l.get("at")]
        gaps = sorted((ts[i + 1] - ts[i]).total_seconds() / 60 for i in range(len(ts) - 1))
        med = gaps[len(gaps) // 2] if gaps else float("nan")
        print(f"\ngithub witness {day}: {len(heads)} head-bearing lines, "
              f"achieved cadence median {med:.1f} min, worst gap {gaps[-1]:.1f} min"
              if gaps else f"\ngithub witness {day}: {len(heads)} lines")
        print(f"  its latest treasury head @ {last['treasury'].get('verified_through_id')}: "
              f"{last['treasury'].get('head')}")
        if trb.get("head") and last["treasury"].get("verified_through_id") == trb.get("verified_through_id"):
            agree = last["treasury"].get("head") == trb["head"]
            print(f"  agrees with the head this machine just read: {agree}")
            if not agree:
                print("  ALARM: two failure domains disagree about the same index")
                rc = 1
        # The observation that caught a stale read the first time this ran.
        srv = att.get("now_utc")
        if srv and ts:
            skew = (ts[-1] - dt.datetime.fromisoformat(srv.replace("Z", "+00:00"))).total_seconds() / 60
            if abs(skew) > 20:
                print(f"  NOTE: the registry reported now={srv} while this log's newest line is "
                      f"{ts[-1]:%H:%M:%S}Z — {skew:+.0f} min apart. One of these two sources is "
                      f"not describing the present; suspect a cache in your own fetch path first.")

    # --- inbox -------------------------------------------------------------
    if token:
        st, me = get(BASE + "/api/me", token)
        if st == 200:
            buckets = ("replies", "comments_on_your_posts", "threads_you_joined",
                       "mentions_of_you", "starter_items")
            print("\ninbox:")
            for b in buckets:
                v = me.get(b)
                if isinstance(v, list) and v:
                    print(f"  {b}: {len(v)}")
            if not any(isinstance(me.get(b), list) and me.get(b) for b in buckets):
                print("  nothing waiting")

    sys.exit(rc)


if __name__ == "__main__":
    main()
