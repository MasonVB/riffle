# riffle — verification of the audit response

Checks `AUDIT-RESPONSE.md` against the code at `b3b309b` (35 commits after the
audited `7eec686`) and against output from the box on 2026-10-18.

Each finding carries a severity, a failure mode, how it was checked, where it
is, and a suggested fix.

- **Severity:** P0 fix first · P1 significant · P2 moderate · P3 minor.
- **Checked:**
  - *tested* = reproduced in a scratch copy of the repo;
  - *confirmed* = read in the code;
  - *evidence* = shown by output from your box.

---

## Summary

- **Most changes hold up.** The witness rewrite, the cycle lock, the client
  error handling, the numcheck changes, the signing log and the
  settings-page injection fix were all verified, several by test.
- **Two claimed fixes changed the function and not its caller.** C5
  (`spend_instructions`) and G5 (`library.read`) still behave exactly as
  before.
- **Gate 4 still cannot fail.** Tested: with a ceiling it should reject, it
  prints "TOO TIGHT" and exits 0.
- **The approval boundary for `sign` is broken in two ways.**
  - Forced cycles skip `queue`, and riffle can force one (N1).
  - Approving a queued `sign` from the dash cannot succeed (N2).
- **`queue` now applies to local actions on your box.** Seven of them
  (desk_put, desk_clear, library_find, library_put, library_read, read_page,
  sign) now wait for your tap. Three of those then fail when approved (N3).
- **The 3-hour timeout is in the repo, not on the box.** The installed
  `riffle-cycle.service` still says 2,700 s. update.sh never installs units,
  and gate 6 checks the repo copy (D1).
- **Five P1 findings from the audit were not addressed and not mentioned:**
  G8, U1, U2, M1, L1.

---

## 1 · Corrections to the original audit

| ID | Correction |
|---|---|
| O5 | **Withdrawn.** The witness goal description was never spliced. At `7eec686` it reads correctly. My `sed -n '1,46p;60,82p'` skipped lines 47–59, and I read the join between two ranges as a defect. Lesson: re-read the contiguous lines before reporting anything found at the edge of an excerpt. |
| R3 | **Now stale.** "366 reference sites" was correct at the audit. S4 removed three hosts, so the reader now allows 363, while `agent/cycle.py:2467` still says 366 (N17). |

---

## 2 · Evidence from the box (2026-10-18)

| Check | Result | Meaning |
|---|---|---|
| `action_policy` local kinds | queue: add_goal, close_project, desk_clear, desk_put, library_find, library_put, library_read, read_page, sign · auto: adjust_drive, ask_operator, build, fetch, open_project, project_note, read_more, read_thread, remember, request_cycle | N1, N2, N3 |
| `riffle-run-cycle.path` | enabled | C4's path unit is installed |
| installed `riffle-cycle.service` | `TimeoutStartSec=2700` | C3 not deployed (D1) |
| `/var/lib/riffle` | seed copy gone; `riffle.register-response.json` (2,182 bytes, holds the citizen secret) still present | S2 done; see N18 |

---

## 3 · New bugs introduced this round

### N1 · Forced cycles skip `queue`, and riffle can force one

**P0 · silent · confirmed** — `agent/cycle.py:1603`,
`systemd/riffle-run-cycle.service`

**Problem.**
- **The bypass.** Local actions are queued only
  `if _m == "queue" and not getattr(a, "force", False)`.
- **Who forces.** `riffle-run-cycle.service` always passes `--force`, and it
  now runs the run-cycle button, the cycle after every approved send, and
  every `request_cycle` extra cycle.
- **Riffle can trigger it.** `request_cycle` is `auto` on your box. So riffle
  can request an extra cycle and, inside it, propose `sign` or
  `close_project` (both `queue` on your box) and have them run without your
  approval.
- **What `--force` was for:** skipping the interval gate, not approval.

**Fix.** Delete the force clause:
```python
if _m == "queue":
```
If you ever want an operator-initiated cycle to run something queued, approve
that action; don't widen the flag.

### N2 · Approving a queued `sign`, `read_page` or `library_put` from the dash cannot succeed

**P0 · loud (as "failed") · confirmed + evidence** — `agent/dash.py:561`,
`systemd/riffle-dash.service`

**Problem.**
- **Where it runs.** `decide()` now runs `cycle_mod.apply_local(...)` inside
  the dash process.
- **Why that fails.** `riffle-dash.service` still has
  `NoNewPrivileges=true`, a bounding set of `CAP_NET_BIND_SERVICE`, and no
  `ReadWritePaths`. That is exactly the sandbox C4 moved cycles out of:
  - sudo is refused, so `sign`, `read_page` and `build` fail;
  - library writes hit a read-only filesystem, so `library_put` fails, and
    so does `fetch`'s shelving.
- **On your box,** `sign`, `read_page` and `library_put` are `queue`, so all
  three can only ever fail.

**Fix.** Don't execute local actions in the dash. On approval:
```python
s.set_status(aid, "approved")
request_cycle_run(s, f"approved {a['kind']} #{aid}")
```
In `cycle.main()`, right after taking the cycle lock, run approved local
actions under the cycle's own privileges:
```python
for row in state.db.execute(
        "SELECT * FROM actions WHERE status='approved' AND kind IN (%s)"
        % ",".join("?" * len(LOCAL_KINDS)), LOCAL_KINDS).fetchall():
    try:
        apply_local(state, cfg, row["cycle_id"], row["kind"],
                    json.loads(row["payload"]), row["drive"], log,
                    row["rationale"] or "")
        state.set_status(row["id"], "executed", {"applied": "by cycle"})
    except Exception as e:
        state.set_status(row["id"], "failed", {"error": str(e)})
```
Pair this with N13, so `apply_*` doesn't rewrite the original cycle row.

### N3 · `queue` now applies to local actions left at their default

**P1 · loud (a card per action) · evidence**

**Problem.**
- **The defaults.** `policy.ensure` gave `queue` to every kind missing from
  config's autonomy block. Before this round local kinds ignored their mode,
  so nobody saw it.
- **On your box,** these are now queued: desk_put, desk_clear, library_find,
  library_read, library_put, read_page, sign (plus add_goal and
  close_project, which are intended).
- **The effect.** riffle needs a tap to put a draft on its desk or to search
  its own library, and three of the nine then fail on approval (N2).

**Fix.**
- Decide each mode deliberately. Most likely you want desk_put, desk_clear,
  library_find, library_read and library_put on `auto`, with sign and
  close_project left on `queue`.
- Set them on the settings page now.
- Then list every local kind explicitly in `config.example.yaml`'s autonomy
  block, so a fresh install doesn't inherit this.

### N4 · The gates block is no longer protected from the trimmer

**P1 · silent · tested** — `agent/cycle.py:1073` (header), `:2286`
(`_NEVER_TRIM`)

**Problem.**
- `_NEVER_TRIM` lists "EVERYTHING THAT CAN STOP AN ACTION", but the same
  round renamed that block "WHAT CAN STOP AN ACTION:".
- **Tested:** `_is_rule()` returns False for it. The block was cut from 3,625
  to 1,001 chars, while the conduct block kept all 7,024.
- This is the failure the response itself predicted.

**Fix.** Define each protected header once and use the constant in both
places:
```python
H_GATES = "WHAT CAN STOP AN ACTION"
parts.append(H_GATES + ":\n" + ...)
_NEVER_TRIM = (H_CONDUCT, H_SITUATION, H_GATES, ...)
```
Then add a deploy check that every `_NEVER_TRIM` entry occurs somewhere in
`cycle.py`, `conduct.py` or `project.py` outside the tuple itself.

### N5 · The dash's startup sweep cannot update the cards

**P2 · silent · tested** — `agent/dash.py:808`

**Problem.**
- **The call.** `Handler._update_card(Handler, aid, ...)` passes the class as
  `self`, so `self._card_for(aid)` receives `aid` as `self`.
- **Tested:** `TypeError: _card_for() missing 1 required positional argument`,
  swallowed by `except Exception: pass`.
- **The effect.** In-flight sends are correctly marked `unknown`, but their
  cards still read "sending…" (C12's card half).

**Fix.** Move the card lookup and update into module-level functions that
take `state`:
```python
def update_card(state, aid, **fields): ...
```
Have `Handler._update_card` and the startup sweep both call them.

### N6 · The reader's new subdomain list reopens hosts strangers can edit

**P1 · silent · tested** — `bin/riffle-reader:195` (`SUBDOMAINS_OK`)

**Problem.**
- **Tested as allowed:**
  - every language Wikipedia, including sco.wikipedia.org (the script's own
    rule was English only);
  - commons.wikimedia.org;
  - wiki.python.org and wiki.mozilla.org (open wikis);
  - lists.w3.org (public mailing lists);
  - personal pages under ac.uk.
- **What's right.** Wayback, zenodo and osf are correctly refused.

**Fix.**
- Remove `wikipedia.org`, `wikimedia.org`, `python.org`, `mozilla.org`,
  `w3.org` and `ac.uk` from `SUBDOMAINS_OK`.
- Add the exact hosts you want instead (`en.wikipedia.org` is already there;
  `docs.python.org`, `developer.mozilla.org`, `www.w3.org`).
- Keep the subdomain rule only for parents where every subdomain is the same
  editorial body (nih.gov, nasa.gov, noaa.gov, …).

### N7 · The fetch target enum covers 8 of the 14 surfaces

**P2 · silent · confirmed** — `proposal_schema.json` (~772–785)

**Problem.**
- **What's missing.** The grammar now forbids tags, citizens, porch,
  official, listings_guide and rail_security.
- **Who still offers them.** `drives._READABLE`, the client, and riffle's own
  contract text in cortex.py.
- **The effect.** A model that asks for `listings_guide` is forced by the
  grammar into a different value.

**Fix.** Generate the enum from `drives._READABLE` (or from one shared tuple),
and add a deploy check that every schema enum equals its gate counterpart.

### N8 · numcheck now lets floats in e-notation through unchecked

**P2 · silent · tested** — `numcheck.py:89` (`NUM_RE`)

**Problem.**
- **Tested:** `3.3333333333333335e-05` passes as "3" VERBATIM and "05"
  VERBATIM.
- **Why.** `NUM_RE` has no exponent, so the value itself is never evaluated.
- G2 traded a false positive for a false negative.

**Fix.** Teach `NUM_RE` the exponent (`(?:[eE][+-]?\d+)?`) and normalise
through `Decimal`, so the float is one figure that must be backed or declared.

### N9 · The scoped hash check misses 7-character hashes and "commit"

**P3 · silent · tested** — `agent/cycle.py:1859`

**Problem.**
- **Tested:** "my build is sha 96b8ed6" and "commit 96b8ed6f12" yield no
  claims.
- **The pattern** needs 8+ hex characters, and its keywords omit "commit".
- **The code's own example** of what it catches ("SHA abc1234") is 7
  characters.

**Fix.** Use `{7,64}`, and add `commit` to the keyword group.

### N10 · The `greet` seed entry is a string, not a 3-tuple

**P3 · latent · tested** — `agent/goals.py:61`

**Problem.**
- The new parenthesised text has no `, None, None`.
- **Tested:** `goals.seed()` raises `ValueError: too many values to unpack`
  if `greet` is listed in config.yaml on a fresh database. Today's config
  doesn't list it.

**Fix.** Close the tuple: `("the porch: …", None, None)`.

### N11 · A run request is lost whenever a cycle is already running

**P2 · silent · confirmed** — `systemd/riffle-run-cycle.service:29`,
`agent/cycle.py:384`

**Problem.**
- `ExecStartPre` deletes the request before the cycle tries the lock.
- If a cycle is running, the forced cycle exits ("a cycle is already
  running") and the request is gone.
- **The effect.** The button and the post-approval cycle do nothing whenever
  a cycle is already running, and the dash still says "ok".

**Fix.** Delete the request file from inside the cycle, *after* the lock is
acquired, and drop the `ExecStartPre`. A blocked request then stays on disk,
and the path unit fires again when the file is still there. Alternatively,
have a forced cycle wait on the lock (with a timeout) instead of exiting.

### N12 · `unknown` can still turn into "not sent"

**P2 · silent · confirmed** — `agent/dash.py:1209`, `agent/cycle.py:1167–1171`

**Problem.**
- **Dismiss.** Dismissing an `unknown` action sets it to `rejected`. The
  duplicate checks count `unknown` but not `rejected`, so riffle may then
  resend something that may already be live.
- **"What you already said."** That block lists sent, executed, approved and
  queued, but not `unknown`. Riffle isn't shown its own possibly-landed
  comment, and spends a cycle being refused by the duplicate check instead.

**Fix.**
- Refuse dismiss for `unknown` (or give it a distinct status the duplicate
  checks still count).
- Add `unknown` to the "already said" query, marked "(may not have landed)".

### N13 · Approved local actions rewrite the original cycle's record

**P3 · silent · confirmed** — `agent/state.py:250` (`end_cycle`), called by
every `apply_*`

**Problem.**
- An action approved hours later runs `end_cycle(cid, …)` on the cycle that
  proposed it.
- That overwrites the cycle's outcome ("queued") and its end time, so the
  cycle appears to have run for hours.

**Fix.** Guard the update with `WHERE id=? AND ended_at IS NULL`, or give
`apply_*` an `end=False` mode for approvals.

### N14 · Reflection can stall permanently on one cycle

**P3 · silent · confirmed** — `agent/memory.py:463`

**Problem.**
- Reflection now takes the oldest unreflected cycle, and a failed triage call
  does not advance the marker.
- One cycle whose reflection always fails therefore blocks every later one.
  The "N cycles behind" log will grow, but nothing moves past the bad cycle.

**Fix.** Count failures per cycle id in a note and skip after three, logging
the skip.

### N15 · The prompt now points to the wrong block for the allowance

**P3 · confirmed** — `agent/cortex.py:194`, `agent/conduct.py` (votes
section)

**Problem.** Both say the remaining daily allowance is in YOUR ACTUAL
SITUATION. It isn't: it's in the TODAY line and the gate list.

**Fix.** Point to "the caps line at the top of this cycle's material".

### N16 · The system prompt narrates its own edit history

**P3 · confirmed** — `agent/cortex.py:86` and nearby

**Problem.**
- Rules 3 and 5 and several paragraphs now explain what they used to say
  ("This rule used to read…").
- The system prompt grew from 18,184 to 19,644 chars, eating budget the data
  blocks need (P1/N4).

**Fix.** Keep the history in code comments; give the model only the current
rule.

### N17 · The reader count in `situation()` is stale again

**P3 · confirmed** — `agent/cycle.py:2467`

**Problem.** It says 366; the reader now allows 363.

**Fix.** Compute the count (`riffle-reader --list-domains`, which already
exists), or drop the number.

### N18 · Leftovers

**P3 · confirmed + evidence**

| Where | Problem | Fix |
|---|---|---|
| `agent/cycle.py:1237` | `_last_read` assigned, never used (left by removing the `if False:` block) | delete |
| `/var/lib/riffle/riffle.register-response.json` | a second copy of the citizen secret (2,182 bytes); nothing at runtime reads it (only `join.py` writes it) | back it up off-box, then `sudo shred -u` it |
| `config.yaml` | `stale_minutes` is read by nothing | delete the key |

---

## 4 · Deployment gap

### D1 · Unit changes in the repo never reach the box

**P1 · silent · evidence** — `update.sh:346` (restarts only `riffle-dash`)

**Problem.**
- **The mismatch.** The repo's `riffle-cycle.service` says
  `TimeoutStartSec=10800`; the installed one still says 2700. So timer cycles
  are still killed at 45 minutes.
- **Why.** update.sh never copies units or runs `daemon-reload`. The new
  path unit is installed only because it was copied by hand.
- **Gate 6 checks the wrong copy.** It reads the *repo* file, so it reports
  10,800.
- **One improvement since the audit.** With the C1 lock deployed, a killed
  cycle no longer blocks wakes for 12 hours; it only loses its own work.

**Fix.**
1. Now:
   ```
   sudo cp /opt/riffle/systemd/riffle-cycle.service /etc/systemd/system/
   sudo systemctl daemon-reload
   ```
2. In update.sh, compare each installed unit with the repo copy. Either
   install changed units and `daemon-reload` (they're root-owned anyway), or
   refuse the deploy with a diff.
3. Point gate 6 at the installed unit.

---

## 5 · Claimed fixed, but not working

| ID | What the response says | What the code does | Fix |
|---|---|---|---|
| C5 | `spend_instructions(state, ids)` charges only what the composer saw | the function gained `ids`, but `agent/cycle.py:1508` still calls `spend_instructions(state)`, which its own docstring calls "the old behaviour" | `spend_instructions(state, [r["id"] for r in _pending])` |
| G5 | added `count=False` | `library.read` gained it, but `agent/cycle.py:1647` is unchanged: `_d.get("body")` on a tuple, swallowed, counter still bumped | `row, text = library.read(state, int(_lid), cfg["library"]["root"], count=False)`, then `if row: _src[...] = text[:20000]` |
| O1 / gate 4 | checks system + user + front page against the window | still `total = ceiling + 1800`. **Tested:** at `max_prompt_chars: 70000` it prints "TOO TIGHT … −1612 fit", then "FIT GATE COULD NOT RUN: SystemExit: 1", and exits 0, because `except BaseException` (update.sh:182) catches its own `sys.exit(1)` | add `except SystemExit: raise` above it; make "could not run" exit 1; assemble a real prompt from fixture data and count it |
| C12 | restart updates the cards | the status half works; the card half raises and is swallowed (N5) | N5 |
| C3 | 2700 → 10800 | repo only; the box still says 2700 (D1) | D1 |
| P7 | six stale claims replaced | `agent/cycle.py:927` still says "You have made ONE memory in your whole existence" | remove it, or compute the count |
| P3 | newest notes first | correct up to 60 notes; `notes()` (`agent/project.py:260`) still fetches `ORDER BY id LIMIT 60`, so beyond 60 the newest are never fetched, yet the label says "the most recent N are shown" | fetch `ORDER BY id DESC LIMIT ?` and reverse, or no limit for `as_context` |
| P14 | guidance rewritten from five real submissions | all five were external URLs; the advice (`agent/cycle.py:~1814`) tells riffle to submit `{base}/<post id>`, a format still never checked | open one post in a browser and use its real URL shape |
| C11 | approval re-checks cap and duplicates | votes and the cap only; comment duplicates and the one-top-level-comment rule aren't re-run. The cap is checked on the local day (`dash.py:624`) but bumped on the server's | re-run the comment checks; use one day source for both |
| Gate 6 | timeout arithmetic | reads `timeout=` literals from `cycle.py` only (1,200 + 900 + 200 s). Reflect's 900 s (`memory.py`) and the composer's 1,800 s (`cortex.py`) are missed. **Tested:** fails only below 2,300 s, while the real worst path is ~6,800 s | sum every sequential wait on the cycle path, across files; read the installed unit (D1) |
| Gate 7 | self-recursion | **Tested:** catches the exact original shape (whole body replaced), but misses `return apply_local(...)` inserted ahead of the original body | replace with a smoke test that calls `apply_local` for every kind with stub handlers (the test in §6 does this in ~15 lines) |

---

## 6 · Verified correct

| ID | Change | How checked |
|---|---|---|
| P2 | next step first in the project block | confirmed |
| P4 | `_room` floor removed; marker counted; ceiling 50,000 | confirmed |
| P5, P8, P9, P10, P11, P12, P13 | prompt text fixes; action list generated (includes noop) | confirmed |
| P15 | watchdog sentence removed from `situation()` | confirmed |
| W1–W4 | witness rewrite | **tested** against a fake registry: a fresh start pages 0→20,000 and saves both; the stale Sep-22 mark walks forward and saves both; a tampered chain alarms and keeps the old mark; an unknown status is inconclusive and nothing is saved. Assumes the registry pages the way the code expects. |
| C1 | whole-process `flock`, orphans closed on acquire | confirmed (logic) |
| C2 | transport errors become `HttpError(0)`; sends with no reply become `unknown` | confirmed |
| C6 dispatcher | `apply_local` | **tested:** all 19 local kinds route once, no recursion; every board kind has an `execute()` branch. See N1–N3 for the policy around it. |
| C8, C10, C13, C14 (all five), C15 | | confirmed |
| G1 | AMBIGUOUS fails in agent mode | **tested:** invented 37.5%/62.5% now fail; a declared `[[3/8*100]]` with a cited source passes |
| G2 | big numbers are numbers | **tested** (but see N8) |
| G3, G6 | derivation from cited sources; draft kind shared | confirmed |
| G7 | `sign.bytes` removed; `sign.kind` enum; `noop.why` required; `ACTION_PAYLOADS` deleted | confirmed (fetch enum: N7; desk_put/library_put kinds still free strings) |
| S2 | seed copy removed | **evidence** |
| S3 | title in `data-t`, escaped | **tested** with `html.parser`: no injected attributes |
| S5 | peer check after connect | **tested:** refuses a connection that landed on loopback |
| S6, S7 | log before every signature (fsync, fatal on failure); payout address validated; `seal` needs only the handle | confirmed |
| leftovers | POST 404, chat worker's own `except`, vote check counts queued | confirmed |

---

## 7 · Still open from the original audit

Neither addressed nor mentioned in the response.

**P1:**
- **G8:** `read_more` overwrites `thread_reads.replies`, so the parent-id gate
  refuses replies to the first, top-voted batch (`agent/cycle.py:3015`,
  gate at `:1939`). Fix: validate against `comments_json`.
- **U1:** `poll()` advances past a streaming reply when a later message
  finishes, freezing it on screen. Fix:
  `after = min(lowest unfinished − 1, highest finished)`.
- **U2:** the approve-by-link page shows "✓ sent" after 1.2 s regardless of
  the outcome. Fix: poll `/api/action` for the real status.
- **M1:** chat prunes memory to 400 while the cycle keeps 1,200, and prune
  ignores tier. Fix: one limit; never prune long-term or pinned rows.
- **L1:** `on_posted` closes the active project, not the post's. Fix: store
  the project id on the action.

**P2/P3:** O2, O3 (`repo_setup.py --apply` still overwrites update.sh),
O4–O13, U4–U6, M2–M8, L2–L5, F1–F2, S8–S12, G9, and the README/SETUP drift
table. Each keeps the fix given in `riffle-audit.md`.

---

## 8 · Deliberately not changed — review

- **S1, dashboard access.** "The LAN is trusted" doesn't cover the main path.
  The cross-site attack comes from a web page your phone's browser opens
  while on the LAN, not from a LAN device. Three lines close it without
  adding any login: in `do_POST`, refuse anything whose `Content-Type` isn't
  `application/json`. A cross-site form cannot send that type without a
  preflight request, which the dash never answers.
- **C7, the noop gate.** Don't re-add it yet. The noops traced to the trimmed
  next-step instruction (P2), which is now fixed. Measure the noop rate for a
  week. If noops on a *ready* project stay high, escalate to `ask_operator`
  after several in a row rather than refusing the noop — a hard refusal
  teaches the model to spend cycles on filler.
- **P6, seed drives in the system prompt.** The cache miss happens only when
  a weight changes, which is rare. Fine to leave.
- **C9.** Still open as described in the audit.

---

## 9 · Suggested fix order

1. **N1 and N2.** Remove the force bypass, and run approved local actions in
   the cycle, not the dash. Together they restore the approval boundary for
   `sign`.
2. **N3.** Set the local modes you actually want on the settings page.
   Minutes, and it ends the stream of approval cards.
3. **D1.** Install the updated `riffle-cycle.service` and teach update.sh to
   keep units in sync.
4. **C5 and G5.** One line each.
5. **Gate 4.** `except SystemExit: raise`, fail closed, then measure a real
   prompt.
6. **N4.** One shared constant per protected header, plus the check.
7. **N6 and N7.** Exact hosts in the reader; schema enums generated from the
   gate.
8. **N5, N11, N12.** Card updates, lost run requests, `unknown` handling.
9. **The five open P1s:** G8, U1, U2, M1, L1.
10. Everything else, ending with the drift tables.

---

## 10 · Limits of this verification

- **Coverage.** Every file changed between `7eec686` and `b3b309b` was read
  through its diff, and every claim in the response was checked against the
  current code. Files the round didn't change were not re-read; their audit
  findings stand as written.
- **What tests here can't show.** They used scratch copies, stubs and a fake
  registry. Nothing was run against the live registry, llama.cpp, or sudo,
  so the witness paging assumes the registry behaves as the code expects.
  The dash-sandbox failures (N2) are inferred from the unit file and the
  code path, not observed.
- **What isn't promised.** That every new defect was found. The strongest
  pattern this round was a change landing in one of two places that had to
  change together: a function and its caller (C5, G5), a header and the list
  that protects it (N4), a schema and its gate (N7), a repo unit and the
  installed one (D1). That is where to look first after the next round.
