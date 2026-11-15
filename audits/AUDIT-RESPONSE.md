# Response to the riffle audit

Every finding has been worked on. **This document says what was changed, not
what was fixed** — whether a change is correct is for you to judge against
the code.

Written by the person who wrote most of the defects, so treat the reasoning
with the same suspicion as the original brief.

All changes are on `master`. The tree is now ~13,100 lines.

---

## 1. What you should be most suspicious of

**Eleven of the changes below were written to fix a bug I introduced while
fixing an earlier one.** During this round I shipped at least three new
defects and reported two of them as working:

- `apply_local()` was patched to collapse a duplicated dispatch. The patch
  matched inside the new function instead of at the call site, so its entire
  body became `return apply_local(...)`. It raised `RecursionError` the first
  time a queued action was approved. I had verified the function existed and
  never called it.
- A `minLength`/`maxLength` pair added to `proposal_schema.json` stopped
  llama.cpp compiling the grammar. The composer returned HTTP 400 for nine
  hours.
- A `handle()` helper in `riffle-sign` shadowed a tuple-unpacked local of the
  same name in `cmd_payout`. Caught before deploy; pyflakes and my own AST
  check both missed it, because a tuple unpack is not an `ast.Assign` target.

The recurring mistake is **editing against an assumed interface and shipping
once it imports**. If you check nothing else, check the places where this
round introduced new logic.

---

## 2. P0 — what changed

### P1 · prompt over budget, rules trimmed first
`_fit()` sorted by length and cut the longest blocks. The conduct guide is
one of the longest.

**Changed.** Added `_NEVER_TRIM`, a tuple of block-header prefixes
(`HOW YOU TAKE PART HERE`, `YOUR ACTUAL SITUATION`, `EVERYTHING THAT CAN
STOP AN ACTION`, and four others). `_fit` excludes any block whose first 400
characters contain one of those strings from the trim order. If the
remaining data blocks cannot free enough, it logs at `error` rather than
returning silently over budget.

**Judge:** the match is a substring test on block text. A block whose header
is reworded stops being protected and nothing will say so.

### P2 · the project's next step was cut
`missing_kind()` was appended after the status lines, with notes and the
thread read below it, in a block trimmed from the end.

**Changed.** `head.insert(0, ...)` instead of `head.append(...)` in
`project.as_context`.

### P3 · note selection dropped the newest notes
Notes were walked oldest-first until the budget ran out, and the label said
"earlier note(s) omitted".

**Changed.** Walks `reversed(notes)` into the budget, reverses the result for
display, and labels it "older note(s) omitted to fit; the most recent N are
shown".

### W1/W2/W3 · the witness chain
`do_witness` was rewritten. The `status` ladder moved into a `_verdict()`
function returning `ok` / `alarm` / `incomplete` / `inconclusive`:

- `incomplete` is now recognised and the walk pages forward from the last
  saved mark, up to `max_pages=8`.
- `verified` with `expect_matches: false` now alarms.
- An unrecognised status returns `inconclusive`, not success.
- `reader.attest()` is wrapped; a registry error no longer kills the wake.
- Nothing is saved while any chain is in alarm.
- The treasury alarm prints the treasury `through_id`, not identity's.
- The chat line no longer claims a cross-check "against the GitHub log".

**Judge:** `_verdict` is my reading of the registry's status vocabulary from
one error message and the existing code. If the registry has statuses I have
not seen, they fall to `inconclusive`, which is at least loud.

### S2 · the seed copy
Operator deleted `/var/lib/riffle/riffle.ed25519.seed` after confirming
`riffle-sign pubkey` still returns the bound key. No code change.

### S1 · dashboard access control
**Not changed.** Operator's decision: the LAN is trusted. `bind: 0.0.0.0`,
port 80, no `IPAddressAllow`.

### S3 · injection via project title
`dequeueProject(ID, JSON.stringify(title))` inside a double-quoted `onclick`.

**Changed.** The title now rides in `data-t="..."` through `esc()` and is read
back with `this.dataset.t`. Verified with `html.parser`: the payload
`" onfocus=alert(1) autofocus x="` previously produced real `onfocus` and
`autofocus` attributes and now produces none.

### C7 · the noop gate was never deployed
Confirmed: `noop-refused` existed in `state.py` and nowhere in
`agent/cycle.py`. I had written it into the root `cycle.py` duplicate.

**Changed.** The root `cycle.py` and `state.py` duplicates were deleted. The
noop gate itself was **not** re-added — see §6.

---

## 3. P1 — what changed

### C1 · dead cycle blocked every wake
**Changed.** Removed 93 lines: the `stale_minutes` window, the pre-boot
check, and the composer-lock probe. Replaced with a `flock` on
`<data_dir>/cycle.lock` taken in `main()` and held for the process. If the
lock is taken, the wake exits. If it is acquired, every open cycle row is
closed as abandoned, because nothing else is running.

`stale_minutes` is now read by nothing. It is still in `config.yaml`.

**Judge:** the lock file handle is kept in a module global `_CYCLE_LOCK` so
the kernel releases it on exit. If anything closes or garbage-collects that
handle mid-cycle, the lock is lost silently.

### C2 · network errors escaped every handler
**Changed.** Both `_req` and `_req_conditional` in `client.py` now catch
`URLError`, `OSError` and `ValueError` and re-raise as `HttpError(0, ...)`.

A send that fails with status 0 is recorded as `unknown`, not `failed`,
because the registry may have applied it. `unknown` was added to the
status sets in three duplicate-check queries so riffle will not resend it.

**Judge:** status 0 is my invention. Nothing in the registry uses it.
Any code branching on `HttpError.status` should be checked; I found none.

### C4 · dash-launched cycles ran without sudo
**Changed.** `subprocess.run` replaced with `request_cycle_run()`, which
writes `/var/lib/riffle/run-cycle.request`. New `riffle-run-cycle.path` and
`riffle-run-cycle.service` watch for it. The service was generated by copying
`riffle-cycle.service` and changing four things; all sixteen privilege
directives were diffed and are identical.

**Judge:** two unit files that must stay in sync, with no gate checking it.

### C6 · `queue` ignored for 17 local kinds
Confirmed, including that `sign` defaults to `queue` (it is absent from
`config.example.yaml`'s autonomy block and `policy.ensure` defaults unlisted
kinds to queue) and ran immediately anyway.

**Changed.** Added `LOCAL_KINDS` and `apply_local()` in `cycle.py`. The cycle
checks `policy.modes()` before dispatching and queues if the mode is
`queue`. `dash.decide()` calls the same `apply_local` on approval; it
previously knew only three kinds.

**Judge:** this is the change that introduced the `RecursionError`. The
dispatcher is the single point of failure for nineteen action kinds.

### S4 · reader allowlist bypass
**Changed.** Subdomain matching is now opt-in via `SUBDOMAINS_OK` (about 20
hosts where a subdomain is the same publisher). All other entries require an
exact host match. `archive.org`, `zenodo.org` and `osf.io` removed;
`scholar.archive.org` was already listed separately.

**Judge:** `SUBDOMAINS_OK` is my list. Any legitimate subdomain not on it
now fails, and the refusal will look like a missing allowlist entry.

### G1 · AMBIGUOUS passed in agent mode
**Changed.** `AMBIGUOUS` joins `UNBACKED`/`MALFORMED` in the failing set when
`--agent`. Human mode unchanged. The cycle's refusal message was also
widened to include AMBIGUOUS findings — it filtered to UNBACKED/MALFORMED
and would have refused with an empty list.

Verified an agent can satisfy it: `[[3/8*100]]` → DECLARED, raw counts →
VERBATIM.

---

## 4. P2/P3 — summary of changes

| finding | change |
|---|---|
| P4 | removed the `max(8000, …)` floor on `_room`; reserved 160 chars per trimmed block for the marker (was 60); `max_prompt_chars` 46000 → 50000 |
| P5 | rule 3 now scoped: "OUTSIDE `build` and `read_page`" |
| P6 | **not changed** — see §6 |
| P7 | six stale factual claims replaced with pointers to live figures |
| P8 | the contract's action enumeration is generated from `policy.ACTION_KINDS` |
| P9 | "That is the complete list" removed; quality and structural checks named |
| P10 | rule 5, the contract and the locked-goal line now say the same thing |
| P11 | the cooldown `deepen` boost is skipped when the project is already ready |
| P12 | "one line a day" removed from `goals.py` and `cycle.py`; the registry paces rather than caps |
| P13 | "no web search here" removed; `systemctl start riffle-cycle` no longer described as forcing |
| P14 | artifact guidance rewritten from the five real submissions on listing-57 — all URLs |
| C3 | `TimeoutStartSec` 2700 → 10800, plus gate 6 |
| C5 | `spend_instructions(state, ids)` charges only what the composer saw |
| C8 | the `GATED` tuple now includes `curate` and `make` |
| C9 | **not changed** — see §6 |
| C10 | `queued` no longer counts as movement; an answered question suppresses re-asking for 8 cycles; a refused ask is logged |
| C11 | approval re-checks the cap and duplicate votes; `cap_bump` uses the server's `now_utc` day |
| C12 | restart marks in-flight sends `unknown`, not `failed`, and updates the cards |
| C13 | dismiss refuses while `sending` |
| C14 | five minors: junk timestamp, a dead `if False:` block, comment votes polluting the post seen-table, two instruction helpers raising on a fresh DB |
| C15 | `interval_minutes: 15` added to the example config |
| G2 | hex tokens need a letter that is not a lone exponent; floats are numbers |
| G3 | derivation uses only cited sources, not `context.txt`; cap ×4 |
| G4 | the hash check is scoped to tokens presented as hashes (`SHA x`, `sha256: x`) |
| G5 | `library.read` returns a tuple and was being `.get()`-ed; added `count=False` |
| G6 | `library.KINDS` gained `draft`; `drives.py` imports it instead of copying. **Note:** the import half was silently reverted by a later edit from a different working tree and had to be redone while writing this document — see §5 |
| G7 | `sign.bytes` removed from the grammar; `noop.why` required in the gate; `sign.kind` and `fetch.what` are enums; the dead `ACTION_PAYLOADS` copy deleted |
| S5 | `_check_peer()` verifies the socket's actual peer after connecting |
| S6 | the signing log is written **before** the signature at all six sites, with `required=True` making a failed write fatal |
| S7 | the payout address is validated before any network call; `seal` reads only the handle |
| W4 | the witness chat line posts only when a mark moved |
| the four C14 items left over | POST double-read, chat Worker's own `except`, reflection skipping cycles, vote check ignoring queued |

---

## 5. Deploy gates: two to seven

`update.sh` now runs seven checks in six heredoc blocks (parse and import
share the first):

1. **parse** — `ast.parse` every file
2. **import** — `importlib.import_module` every `agent.*`
3. **render** — builds a fake handler and calls `do_GET` on `/`, `/settings`,
   `/history`, checking status, size and unsubstituted placeholders
4. **prompt fit** — system + user + front page against the context window
5. **grammar risk** — rejects schema constructs that break llama.cpp's GBNF
   converter (`minLength`, `maxLength`, `patternProperties`, `allOf`, `not`,
   `if`)
6. **timeout arithmetic** — the three longest internal waits against
   `TimeoutStartSec`
7. **self-recursion** — any function whose only call is to itself

Gates 3, 5, 6 and 7 each exist because something got through gates 1 and 2.

**Three of these were written badly on the first attempt and passed the bug
they were written for:**

- Gate 3 first rendered `pages.PAGE` directly, and the `NameError` was in
  `dash.do_GET`.
- Gate 5's regex was double-escaped inside the heredoc, so `\\d` was literal.
- Gate 7 counted `ValueError(...)` as a second call, so `len(names) == 1` was
  false on `apply_local`.

Each now has a recorded both-ways test. **Worth checking they still do what
they claim**, since that is twice now that a gate has silently agreed with
everything.

`pyflakes` is not in `update.sh`. It found four live `NameError`s the
original gates had passed and should probably be gate 8.

**One change silently reverted.** While verifying this document against the
deployed tree I found `drives.py` had gone back to a literal `_LIB_KINDS`
tuple: the G6 import was overwritten by a later edit from a different
working copy. The contents happened to still agree, so nothing failed. It
has been redone, but the mechanism is worth noting — it is the same class of
mistake as the duplicate root `cycle.py`, and **no gate detects a change
being quietly undone.** Other changes in this document may have been lost
the same way; the only reliable check is the code.

---

## 6. Deliberately not changed

- **S1** — dashboard access control. Operator trusts the LAN.
- **C7** — the noop gate (refusing a `noop` when a project is ready, posting
  is open and it is over 72h old) was never deployed. Not re-added. It is
  the most forceful intervention in the codebase — the system overriding a
  stated decision — and the deadlock it was built for resolved on its own.
  Worth your view on whether it should exist at all.
- **P6** — the system prompt lists five seed drives at seed weights while the
  user prompt shows the live ten. The fix is in `stable_prefix`, which is
  cached for prompt reuse; making it per-cycle costs a cache miss on every
  wake. Not measured, so not changed.
- **C9** — not reached.
- **`stale_minutes`** — dead but still in `config.yaml`.

---

## 7. What would be most useful now

1. **Re-check anything in §2 and §3 where I introduced new logic**, in
   particular `apply_local` (19 kinds, one dispatcher, already broken once),
   the cycle `flock`, and the `do_witness` rewrite.
2. **Verify the gates fail on their own bugs.** Three were written wrong the
   first time; the fourth may be too.
3. **The `unknown` action status** touches three duplicate-check queries, the
   dash's startup sweep and the approval path. If any code path treats
   `unknown` as "not sent", riffle will resend something that may be live.
4. **`SUBDOMAINS_OK`, `_NEVER_TRIM`, `_DEAD` markers, `LOCAL_KINDS`** — four
   hand-maintained lists added this round, each silently wrong if incomplete.
5. **Anything in a class not represented in the original findings.** The
   defect table shaped what I looked for, and I fixed close to what it
   described. Bugs of a kind neither of us has thought of will not be in
   either document.

Where this document and the code disagree, the code is the evidence.
