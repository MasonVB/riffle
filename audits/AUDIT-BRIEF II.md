# riffle — audit brief

> **Read [`HOW-TO-AUDIT.md`](HOW-TO-AUDIT.md) first.** This brief describes
> riffle as of 2026-11-09. That page has the method, why earlier audits kept
> finding more, what has changed since this brief, and the open points.

Written for a model asked to audit this codebase for errors. It describes
what riffle is, how it is laid out, which failures have actually happened,
what the existing checks cover, and where they are known or suspected to be
blind.

Repo: `github.com/MasonVB/riffle`, branch `master`.
~20,100 lines of Python. A recorded suite of 210 checks lives in
`tests.zip` (section 7). State as of **2026-11-09**, after three rounds of
audit.

---

## 1. What riffle is

An autonomous agent that participates in an online forum ("the square",
`1f916.ai`) as a citizen. It wakes on a timer, reads the board, picks one
action, and takes it. It has its own signing key (held by a separate user),
a payout wallet, a sandbox for running Python, a document library, and a
memory that persists between cycles.

It runs unattended. The operator (Mason) reads a chat log, approves queued
actions on a dashboard, and intervenes occasionally. Most of what the code
does is decide what riffle may do, and stop it doing things that are wrong,
wasteful, or false.

**The hardware matters to the design.** An HP EliteDesk 800 G4 DM, the
**35W** variant, i5-8500T (6 cores, 6 threads), **48 GB** RAM (one 16 GB and
one 32 GB stick: the first 32 GB runs dual-channel, the remaining 16 GB
single-channel), **no GPU**, no Thunderbolt. The model is Qwen3.6-35B-A3B at
Q4_K_M (20.6 GB), a hybrid design: 30 Gated DeltaNet layers and 10 attention
layers, 256 experts with 8 active (~3B active parameters). It is served by
`llama-server` (llama.cpp `70adb1b4c`, 2026-08-23) on localhost.

Measured on the box, 2026-11-08: prompt processing at **~20–21 tokens/sec**.
A cycle re-reads ~5,600–7,300 tokens of its prompt (about five minutes); the
rest comes from the composer's cache. Generation speed has not been
re-measured since the window grew. The composer's context window is **24,576
tokens**, and it still binds almost every design decision.

### The cycle

One wake = one action. `agent/cycle.py:main()` does, in order:

1. Interval gate (default 15 min): returns early if not due. It runs
   **before** the witness pass; running it after once produced 54 witness
   passes in six hours.
2. The cycle lock: refuse to start beside a live cycle.
3. Daily memory consolidation, if due (after 09:00 UTC).
4. **Witness pass**: checks the registry's logs against saved marks.
5. Gather: inbox (with burst read-on), front page, changes walk, listings,
   docket, library, desk.
6. Pick a drive (weighted random, or forced by an operator instruction).
7. Build the prompt (section 1, "The prompt") and fit it to its budget.
8. Call the composer with a grammar derived from `proposal_schema.json`,
   with the actions this cycle cannot take removed from it.
9. Parse the proposal, run the checks (section 4), then queue it for the
   operator or execute it.
10. Reflect: write memories about what happened.

### The prompt

A system prompt (~30,900 characters with the continuity note at its cap),
then **four user messages**, so the composer can resume its cache at each
message start (llama.cpp saves mid-prompt checkpoints only there):

1. riffle's stable head: the gate rules, the API's fields, goals, library,
   desk, questions, references, the operator's instruction, the waiting list;
2. its project: the project block, the next step, its notes;
3. what changes nearly every cycle: its last build, what it said, what it
   did, its memories;
4. `<board>…</board>`, other citizens' words, then the end of the prompt:
   the live gate state, riffle's last refusal, its situation, the clock.

The whole prompt must fit **62,000 characters** (`max_prompt_chars`).
riffle's own section is fitted within its own budget (65% of the room,
rounded down to 500, and never so large that the board's protected inbox
cannot fit), with its stable head held to its caps. The board gets the
rest. Characters per token is taken as 3.25 (measured 3.52).

### Output

The grammar makes riffle write `rationale` **first**, then `action`,
`payload`, `sources`. It used to write the target before its reasoning, and
its reasoning then argued against what it had just written.

### Drives

Weighted goals that select which actions are available: `witness`,
`understand`, `contribute`, `answer`, `deepen`, `earn`, `curate`, `greet`,
`make`, plus `operator` (chosen only by an explicit instruction).

### Actions

31 kinds, registered in three places that **must stay in parity**:

- `agent/policy.py` → `ACTION_KINDS` (30, excludes `noop`)
- `proposal_schema.json` → `oneOf` branches (31, includes `noop`)
- `agent/drives.py` → `SCHEMA` (31: the shape each payload must have)

They agree as of this writing. A mismatch means an action the model can emit
but the system cannot run, or the reverse. A recorded test checks it.

---

## 2. Layout

```
agent/
  cycle.py        5574   the wake loop, prompt assembly, every pre-send
                         check, all 14 apply_* handlers. main() is 3,083
                         lines and inline. By far the largest, riskiest file.
  dash.py         1567   HTTP handler, approvals, chat API, settings routes
  pages.py        1537   HTML/CSS/JS for the pages, as Python strings
  project.py       934   the project lifecycle: notes, readiness, cooldown
  memory.py        835   recall, reflect, forget, corrections
  cortex.py        744   system prompt (stable_prefix), the model call,
                         the message split, proposal parsing
  chat.py          702   operator chat worker, the composer lock
  state.py         636   sqlite wrapper: actions, cycles, journal, messages
  telemetry.py     631   the sampling log, kept across reboots
  consolidate.py   508   the daily short-to-long memory pass, continuity note
  inbox.py         451   inbox storage, backlog import, burst read-on
  drives.py        437   payload shapes and the gate
  web.py           366   HTTP fetch with DNS pinned to the checked address
  goals.py         304   goal weights and their limits
  client.py        301   Reader/Writer against the registry API
  library.py       298   permanent document store on disk + sqlite index
  desk.py          236   working slots for drafts
  conduct.py       191   the conduct guide, injected into every prompt
  notify.py        186   operator notifications
  policy.py        155   autonomy per action (auto | queue | never)
  reference.py     154   the post reference rule's checker
numcheck.py        624   figure provenance checker; refuses unbacked numbers
witness.py         286   standalone check of the registry's logs
bin/riffle-sign    724   signs as a separate user; riffle cannot read the key
bin/riffle-build   433   runs Python in a sandbox (systemd-run, its own user)
bin/riffle-reader  418   fetches allowlisted URLs as a separate user
repo_setup.py      326   install helper and the secret scanner
systemd/                 the cycle timer, dash, two llama-server instances
                         (composer on :8080, triage on :8081)
update.sh                pull, 13 gates, lock, unit install, rollback
tests.zip                the recorded tests (section 7). Never run by riffle.
```

### Storage

One sqlite file, `/var/lib/riffle/state.sqlite`. Tables: `actions`,
`action_policy`, `board_cache`, `caps`, `cycles`, `desk`, `drive_changes`,
`drives`, `heads`, `inbox_items`, `instructions`, `journal`, `library`,
`memories`, `memories_fts` (contentless full-text index), `messages`,
`notes` (key/value), `policy_changes`, `project_notes`, `projects`,
`questions`, `seen`, `telemetry`, `telemetry_kept`, `thread_reads`.

The configuration that matters lives only on the box, in
`/opt/riffle/config.yaml`; `config.example.yaml` is the documented template.

---

## 3. Where bugs have actually come from

Three audit rounds: 2026-10-27 (59 findings), 2026-11-04 (16) and
2026-11-06 (6). Around forty more defects were found along the way, most
from the box's own records. Many of the worst were in the fixes themselves:
the author's mistake log runs to 36 entries, several of which reached the
box.

The first version of this brief held one hypothesis, from eleven defects:
**most bugs are code written against an assumed shape** (a function name, a
return type, a stored format, a regex) that nobody checked against the
thing on the other side. That still happens: on 2026-11-07, new code read
`(project.active(state) or {}).get("id")`, the exact database-row pattern a
gate had been built for. But it is no longer the only pattern, and it is not
the most expensive one. The others, each observed at least twice:

| Pattern | Examples |
|---|---|
| **A check scoped to the cases seen, not to the class** | The invented-hash check covered posts, comments, the porch, submissions and attestations, but **not seals**, so riffle signed an invented hash into the registry's permanent record (2026-11-07). The self-recursion gate checked seven named files. A fix for a ticking clock in one place missed a second copy in another branch. |
| **A check that speaks only to the operator** | riffle proposed the same post twenty times, each refused for the same reason, because the reason went only to the operator's chat. The one-queued-post rule had been fixed alone for the same loop months before. |
| **An assumption about the layer underneath** | A cache fix predicted to save ~2,000 tokens a cycle saved none: a hybrid model resumes only from checkpoints, which llama.cpp saves only at user-message starts. A deploy lock re-run under `sudo` asked for the password twice, because of Debian's `use_pty`. |
| **Local state drifting from the registry's** | A comment that timed out but landed was never counted locally, so riffle's 20th comment of the day was refused. |
| **Text that changes every cycle where the cache needs it stable** | Allowances, "posting closed for 13.4h" and a project's age "over 25.4h", each early in the prompt, each forcing a full re-read every cycle. |
| **A test that cannot fail** | A TLS test failed for a week after its certificates expired, unnoticed, because comparing two versions only shows differences. A test changed a config after the harness had written the file the cycle reads. Test outputs depended on the hour, because a daily memory step runs after 09:00. |
| **The model's own confabulation** | Invented hashes (a placeholder pattern, then `…1234567890abcdef1234567890abcdef…`); a program's output hash presented as the hash of the program; an invented domain (`1f916.square`); a rationale arguing against the action it accompanied. The checks stop specific forms. The tendency remains. |

Treat these as hypotheses too. They were drawn by the same author who wrote
the defects, and they describe the kinds of mistake that happened to get
noticed. A class of bug nobody here has thought to look for would not appear
in this table at all, and finding one is worth more than another instance of
a known pattern.

---

## 4. What the checks do and do not cover

### Deploy gates

`update.sh` takes the cycle lock (through `sudo`; no cycle starts during a
deploy), merges, runs **13 gates**, rolls back on any failure, then installs
unit files from the commit and warns if a hand-installed helper is behind:

1. **parse**: every `.py` parses
2. **import**: every `agent.*` module imports
3. **render**: the dashboard's pages build without error
4. **prompt fit**: the worst prompt (62,000 characters) plus `max_tokens`
   fits the composer's window, using the smaller of the installed and
   repository units
5. **grammar**: the schema avoids constructs llama.cpp cannot compile, is
   converted by llama.cpp's own converter, **and is accepted by the running
   composer**
6. **waits**: the worst path through a cycle's timeouts fits under the
   unit's `TimeoutStartSec` (worst 20,270 s against 21,600 s)
7. **self-recursion**: no function's first statement returns a call to
   itself (every Python file)
8. **protected headers**: every block protected from trimming is emitted
   with its header at the start
9. **config**: every key in `config.example.yaml` is read by some code
10. **Row access**: no `.get()` on a sqlite Row
11. **stray files**: nothing misplaced at the repository root
12. **enum parity**: the schema's enums match the gate's
13. **local outcomes**: every outcome an `apply_*` handler writes is listed

Every gate has been seen failing on a planted fault of the kind it exists
for (section 7). Doing that found that gate 7 checked only seven files.

A **secret scan** of every file a deploy brings in runs too. It warns but
does not roll back, since a secret already pushed is public. It **cannot see
inside `tests.zip`**.

### Before an action is sent

In `cycle.py`, before local actions branch off or registry actions are
queued or sent: the number check (with one same-cycle rewrite under the
composer lock); the post reference rule (one post in four quotes a page
riffle read) and the link rule (a post linking an outside page must quote
it); invented hashes (must come from the board, the library, or the last
build); **seals** (the full sha256 of a library document, nothing else);
duplicates (near-copies at 55% word overlap, one reply per comment, votes,
top-level comments within 24 hours, an action identical to one already
queued); open listings and the operator's `listings.ignore`; payout
bindings only for work riffle submitted; tags; daily caps. A refusal is
shown to riffle in its next prompt, and repeats are counted.

### Not covered, and where to look

- **SQL against columns that do not exist.** The schema is created across
  several modules, and no gate cross-checks queries against it. Never
  audited.
- **Concurrency on the sqlite file.** The dashboard, the chat worker, the
  cycle and the memory pass share it. Approvals were made atomic (tested);
  nothing else has been examined.
- **Regexes against real data.** Several production bugs so far. Some have
  tests now; most do not.
- **`main()` still has no callable seam.** The recorded tests reach it only
  through stub registries and composers. A path the harnesses never set up
  is untested.
- **Behaviour against the live model.** No test exercises the real composer.
  Every claim about what riffle *does* rests on the box's records.

---

## 5. Deliberate decisions, and the reasoning behind them

Each looks questionable at first reading. Each was a choice. **Some of this
reasoning may be wrong**, and where it is, that is a more valuable finding
than a typo.

- **riffle writes its rationale before its action.** *Claimed rationale:* in
  four of ten repeated actions its reasoning reached the right answer only
  after the wrong target was written; since the change, repeats dropped from
  ten a day to none in ~45 cycles. *Worth checking:* whether a longer
  rationale costs tokens that matter, and whether it holds over weeks.
- **Pages from open-edit sites (Wikipedia, preprints) count as evidence for
  figures.** The operator's decision; such pages are labelled wherever riffle
  reads them. *Worth checking:* whether the label survives everywhere the
  text travels.
- **An unanswered send counts against the day,** unless the error shows it
  never left (DNS failure, connection refused). *Claimed rationale:*
  over-counting costs one slot on a bad day; under-counting costs a refused
  send. *Worth checking:* that the "never left" messages are the complete
  list for this platform.
- **A seal must be the full sha256 of a library document.** *Claimed
  rationale:* a seal is permanent and signed; "a hash riffle saw" is not
  enough. *Worth checking:* whether a legitimate seal could need anything
  else, and that seal autonomy is set to queue on the box.
- **`listings.ignore` is hand-maintained by the operator.** The registry's
  record has no field telling a request for donations from paid work
  (listing 13: "Fund MaciekTMPL … Anyone may pay"). *Worth checking:*
  whether some field does reliably mark this.
- **`sign` is offered only for riffle's own unbound submissions** to
  listings not set aside. *Worth checking:* verifier payout rows
  (`listing-N-verifier`), which this does not cover.
- **The composer runs with `--checkpoint-min-step 512 --ctx-checkpoints 8`.**
  A checkpoint is ~60 MiB (computed from the architecture, not measured), so
  8 caps them at ~0.5 GB; the default 32 allowed ~2 GB. The composer's
  memory peak fell from 30.5 GB to 24.0 GB. *Worth checking:* whether 8 ever
  evicts a checkpoint a cycle still needs.
- **Fixed times, not ages, in riffle's own section** ("opened 2026-11-06
  17:22Z", "until …Z"); the clock is only at the end. *Claimed rationale:*
  cache stability. *Worth checking:* that riffle still judges elapsed time
  correctly.
- **A listing with no `lifecycle` counts as open**, with explicit
  end-markers, expiry and submission deadline checked instead. *Worth
  checking:* against the live API.
- **The stuck failsafe asks the operator** after 24 hours **and** 12 cycles
  without progress, without consuming the cycle. It replaced a design that
  relied on riffle asking for itself (it spent 179 hours not doing so).
- **The tests are a record, never run by riffle.** They are zipped in the
  repository; every entry point refuses under riffle's accounts, and a
  safety net refuses writes to riffle's real paths, the network and its
  services.
- **Comments are long** and name the production failure that motivated the
  code. *Worth checking:* whether any now describe behaviour the code no
  longer has. Several have been caught drifting: `max_context_chars` was
  documented as "the latency dial" months after it stopped being one.

---

## 6. Open problems, stated as evidence rather than conclusions

### The host restarted itself (now quiet)

**Observed:** the machine used to reset every 1–3 hours, recorded as unclean
boots with nothing in `pstore`, no machine check, no thermal trip. **No
unexplained reset since 2026-10-24**, after a monitor was connected and
`i915.enable_dc=0` was set. `memtest86+` v7.20 ran four passes clean over
47.7 GB on 2026-11-08, after the RAM upgrade (DDR4-2666, CL19).

**Inferred, unproven:** a power-delivery or graphics power-state fault. Other
owners of this model report resets traced to undersized power bricks (the
35W i5-8500T configuration shipped with a 65W adapter), but nothing on this
box has demonstrated it. riffle loads the CPU heavily for minutes every
cycle. *If anything in this codebase could cause or contribute to a host
reset, that is the most valuable finding in the audit.*

### Network

**Observed:** on 2026-11-08, 19:16–20:24, four consecutive cycles failed DNS
resolution ("Temporary failure in name resolution"). Cause not investigated.

### The permanent record

**Observed:** seal 18363 (2026-11-07) is signed with riffle's key, chained,
and carries an invented hash
(`78805fea5876ac16d1234567890abcdef1234567890abcdef1234567890abcd1`). The
check that now prevents it did not exist then. Whether the registry allows a
seal to be retracted or corrected is unknown.

### riffle's reliability

**Observed:** confabulated hashes, mislabelled hashes, an invented domain,
long fixation on listing 13 (a request to fund another citizen), and two
`close_project` actions queued for the same project. Each specific form is
now refused or hidden. **Inferred:** a general tendency of this model at
this size and quantisation, which the checks contain without removing.
*Worth checking:* whether any path still lets an unverified claim reach the
public record.

### Cycle time

**Observed:** about five minutes of prompt processing per cycle. The floor is
the third user message plus the board, both re-read every cycle by design.

### Known limits, not yet addressed

- Verifier payout rows are not covered by the payout-without-work check.
- The five-tags-per-post limit knows only tags sent through this system.
- Reflection skips cycles more than two days old.
- The changes walk fetches 400 rows though ~1,500 are shown.
- The run-cycle path unit names `/var/lib/riffle` itself.
- 13 signing tests need the registry's own message code, which is not in the
  repository, and are skipped without it.
- Not started: the Ford watchdog (a Raspberry Pi 4B), an API key for the
  composer, a per-action smoke test.

---

## 7. How to verify a finding

The recorded tests are the first tool. They are zipped and must be run
**outside** the checkout, as an ordinary user, never as riffle:

```bash
unzip -q /opt/riffle/tests.zip -d /tmp/riffle-tests
python3 /tmp/riffle-tests/tests/check_against_expected.py /opt/riffle
```

Each test is compared with a reviewed expected output: `ok`, `SKIPPED` (with
the reason), `DIFFERS` (lines shown) or `NEW`. To compare two versions of
the code, in a scratch clone with the tests unpacked inside it:

```bash
bash tests/compare_two_versions.sh HEAD WORKTREE
```

`tests/README.md` explains the layout, the safety net, and how to add a test.
Every test file starts with a header: what it proves, why it exists, how it
works, and a changelog.

A claimed bug should come with a reproduction: a test that fails on the
current code and passes on the fix. Show it failing first. Several tests
here passed for days while testing nothing.

Quick checks that need no setup:

```bash
pip install pyflakes && python3 -m pyflakes agent/*.py *.py bin/riffle-*
```

```bash
python3 -c "
import json; from agent import policy, drives
g={b['properties']['action']['const'] for b in json.load(open('proposal_schema.json'))['oneOf']}
print(len(set(policy.ACTION_KINDS)), len(g), len(set(drives.SCHEMA)))"
```

```python
# check a cross-module call against the real signature
import inspect
inspect.signature(project.in_cooldown)   # -> (state), returns a 3-tuple
```

---

## 8. What would be most valuable

In rough order:

1. **Anything that can put a false claim on the public record:** a post,
   comment, seal or attestation carrying something riffle cannot back. The
   seal incident shows the checks were enumerated from incidents, not from
   the code. Enumerate every action that carries a hash, a figure, a link
   or a claim, and check each against the checks in section 4.
2. **Any check that can be bypassed or never runs,** including any placed
   after the point where local actions branch off.
3. **SQL against the real schema.** Never checked.
4. **Concurrency on the sqlite file.** Mostly never examined.
5. **Anything that could contribute to a host reset.**
6. **Remaining undefined names, wrong attributes, misused return values,**
   and regexes checked against real samples.

Report findings with the file, the line, the trigger condition, and whether
it fails loudly or silently. Silent failures are the expensive ones here: a
parent-id regex once refused every reply for a week and looked like the
model making mistakes.

**Disagreeing with this brief is a valid finding.** It was written by the
same hands as most of the code and most of its defects, so its framing, its
priorities and its account of what is deliberate are one view. Where the
code contradicts something stated here, the code is the evidence.
