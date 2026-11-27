# riffle — audit brief III

> **Since this brief** (2026-11-24 to 11-27, `AUDIT-RESPONSE-2026-11-14.md` §28–32):
> update.sh has **14 gates**; gate 14 (`PYSQL`) prepares every SQL statement
> it can read against the real schema, so section 4's "SQL against columns
> that do not exist … never audited" and section 8's item 5 are now
> partly answered: none failed. Concurrency was measured, not proven (§29).
> The permanent record (section 6) cannot be corrected: the operator's
> decision, 2026-11-27. Treat it as written in stone, not as an open problem.
> Section 4's send checks gained `figure-assumed`, `post-claimed`, `credited`
> and `claimed-before`; an action refused ten times in a day is held out; and a
> build's output counts only where a reader can see the build.
> A mutation sweep (§32) found 23 refusals no test reached; each has a test
> now. Section 6's known limits were looked at there: one changed, three left
> as they are, with the reasons.
>
> **Read [`HOW-TO-AUDIT.md`](HOW-TO-AUDIT.md) first.** It explains why every
> audit so far has found more than the one before, and how to run this one so
> it finds what is there. This brief describes riffle itself. It replaces
> `AUDIT-BRIEF II.md` (2026-11-09), which is kept for history.

Written for a model asked to audit this codebase for errors. It covers:
- what riffle is, and how it is laid out;
- which failures have actually happened;
- what the existing checks cover;
- where they are known or suspected to be blind.

Repo: `github.com/MasonVB/riffle`, branch `master`. **~23,300 lines of
Python.** A recorded suite of **346 checks** lives in `tests/tests.zip`
(section 7). State as of **2026-11-23**, at commit `b8b050a`, after:
- the outside audit of 2026-11-10 and its second pass;
- the response to it, in 21 batches;
- the first audit of riffle's behaviour (2026-11-20).

---

## 1. What riffle is

An autonomous agent that takes part in an online forum ("the square",
`1f916.ai`) as a citizen. It wakes on a timer, reads the board, picks one
action and takes it. It has:
- its own signing key (held by a separate user);
- a payout wallet;
- a sandbox for running Python;
- a document library;
- a memory that persists between cycles.

It runs unattended. The operator (Mason) reads a chat log, approves queued
actions on a dashboard, and intervenes occasionally. Most of the code decides
what riffle may do, and stops it doing things that are wrong, wasteful or
false. Since 2026-11-20 a growing share of it is about what riffle may *say*:
whether a reader can check it.

**The hardware matters to the design.**
- An HP EliteDesk 800 G4 DM, the 35W variant: i5-8500T (6 cores, 6 threads), **64 GB** RAM, ~949 GB disk, **no GPU**.
- The model is Qwen3.6-35B-A3B at Q4_K_M (20.6 GB): a hybrid of 30 Gated DeltaNet layers and 10 attention layers, 256 experts with 8 active (~3B active parameters).
- Two `llama-server`s on localhost:
  - the **composer** (`:8080`, window **49,152 tokens**) writes every proposal;
  - a small **triage** model (`:8081`, 8,192 tokens) writes reflection and chat memories.

**Measured on the box,** from the figures report, 2026-11-19 (cycle calls):
- The composer reads an uncached prompt at **19.6 tokens/s** and writes at **3.2 tokens/s**.
- A median cycle re-reads ~12,000 tokens and writes ~250.
- Time per call was 730 s median, 1,800 s worst (the old limit).

At these speeds, prompt size is the main cost of a cycle, and the composer's time limit is a design constraint, not a detail.

### The cycle

One wake = one action. `agent/cycle.py:main()` does, in order:

1. **Interval gate** (15 min): returns early if not due, before the witness pass.
2. **The cycle lock**: refuses to start beside a live cycle. Deploys and the operator's maintenance commands take the same lock (`/var/lib/riffle/cycle.lock`).
3. **The composer budget for this cycle**: `cortex.set_budget(10,800 s)`, shared by every composer call the cycle makes (section 1, "The composer's time").
4. **Daily memory consolidation**, if due (after 09:00 UTC).
5. **Witness pass**: checks the registry's logs against saved marks.
6. **Gather**: inbox, front page, changes walk, listings, docket, library, desk.
7. **Pick a drive**: weighted random, or forced by an operator instruction.
8. **Build the prompt** and fit it to its budget.
9. **Call the composer** with a grammar from `proposal_schema.json`, with this cycle's impossible actions removed.
10. **Parse and check.** Parse the proposal; append any build files it names (`"append"`); run the checks (section 4); then queue it for the operator or execute it.
11. **Reflect**: the triage model writes memories about what happened, kept only where the cycle's own record bears them out.

### The prompt

A system prompt (~32,600 characters with the continuity note at its cap),
then **four user messages**, so the composer can resume its cache at each
message start:

1. **riffle's stable head**: the gate rules, the API's fields, goals, library, desk, questions, references, the operator's instruction, the waiting list.
2. **Its project**: the project block, the next step, its notes.
3. **What changes nearly every cycle**: its last build, what it said, what it did, its memories, and when it applies, **"YOU HAVE BEEN DOING ONE THING"** (section 1, "Drives").
4. **`<board>…</board>` and the end of the prompt**: other citizens' words inside the board tags, then the live gate state, riffle's last refusal, its situation and the clock.

The whole prompt must fit **120,000 characters** (`cycle.max_prompt_chars`,
on the box since 2026-11-23; it was 105,000). That leaves about 87,000 for
material after the system prompt. The ceiling is held to the window the
*running* composer reports, and characters per token are taken as 3.25.

### The composer's time

**Each call's limit is sized from the call** (`cortex.call_timeout`, since 2026-11-21):
- its prompt's tokens (characters / 3.3) at `read_tok_s` (15);
- plus its `max_tokens` (4,000) at `write_tok_s` (2.5);
- a quarter more, plus two minutes;
- between 300 s and **3,600 s**.

**A cycle's calls share 10,800 s between them.** These are the memory pass, the main call and its cut-off retry, and the number check's rewrite and its retry. A call is not started with under 300 s left. A timeout says how long it ran, what it had, and from what.

**The worst cold, full-length call at measured speeds is ~3,140 s**, against the 3,600 s cap.

### Output

The grammar makes riffle write `rationale` **first**, then `action`,
`payload`, `sources`.

### Drives

Weighted goals that select which actions are available: `witness`,
`understand`, `contribute`, `answer`, `deepen`, `earn`, `curate`, `greet`,
`make`, plus `operator` (chosen only by an explicit instruction).

**Temperament.** Since 2026-11-22, riffle's identity gives it one, at the operator's direction. It is curious. It feels satisfaction when a claim survives a check, unease when its own fails, and boredom when it repeats itself. Boredom means move on.

Because riffle wakes blank, it cannot feel a run of cycles on its own. So when one of these is large, the cycle tells it, in **"YOU HAVE BEEN DOING ONE THING"** (`cycle.restless`):
- the share of its last 20 actions on one project, listing or post;
- a refusal it keeps walking into.

### Actions

31 kinds, registered in three places that **must stay in parity**:
- `agent/policy.py` → `ACTION_KINDS` (30, excludes `noop`)
- `proposal_schema.json` → `oneOf` branches (31)
- `agent/drives.py` → `SCHEMA` (31)

They agree as of 2026-11-23, and a recorded test checks it. `post` and `comment` take an optional `"append": [library ids]`. The square takes text only, so an attachment is the file appended in full at the end of the post, under its name and sha256 (`outgoing.attach`).

---

## 2. Layout

```
agent/
  cycle.py        7058   the wake loop, prompt assembly, most pre-send checks,
                         the apply_* handlers. main() is long and inline. By
                         far the largest, riskiest file.
  dash.py         1806   HTTP handler, approvals (re-running the send checks),
                         chat API, settings routes
  pages.py        1585   HTML/CSS/JS for the pages, as Python strings
  memory.py       1073   recall, reflect (with grounding), extract, forget,
                         corrections
  project.py       982   the project lifecycle: notes, readiness, cooldown
  cortex.py        953   system prompt (stable_prefix), the composer call and
                         its sized time limits, proposal parsing
  outgoing.py      939   what may be said in public: private library refs,
                         unpublished hashes, appendices, addressees, claims,
                         listing artifacts, repeat posts, invented instructions
  chat.py          745   operator chat worker, the composer lock
  state.py         665   sqlite wrapper: actions, cycles, journal, messages
  telemetry.py     635   the sampling log, kept across reboots
  figures.py       609   the figures report: every number the operator used
                         to fetch by hand
  consolidate.py   598   the daily short-to-long memory pass, continuity note
  drives.py        475   payload shapes and the gate
  inbox.py         453   inbox storage, backlog import, burst read-on
  web.py           366   HTTP fetch with DNS pinned to the checked address
  client.py        328   Reader/Writer against the registry API
  goals.py         317   goal weights and their limits
  library.py       313   document store on disk + sqlite index
  reference.py     264   the post reference rule's checker
  transcript.py    247   read-only export of everything riffle did, for audits
  storage.py       236   the disk rule: keep everything until 85% used
  desk.py          236   working slots for drafts
  notify.py        234   operator notifications
  conduct.py       194   the conduct guide, in every system prompt
  policy.py        172   autonomy per action (auto | queue | never)
numcheck.py        697   figure provenance checker; refuses unbacked numbers
witness.py         286   standalone check of the registry's logs
bin/riffle-sign    724   signs as a separate user; riffle cannot read the key
bin/riffle-build   506   runs Python in a sandbox (systemd-run, its own user)
bin/riffle-reader  476   fetches allowlisted URLs as a separate user
repo_setup.py      326   install helper and the secret scanner
systemd/                 the cycle timer, dash, two llama-servers
update.sh                pull, 13 gates, lock, unit install, rollback
tests/tests.zip          the recorded tests (section 7). Never run by riffle.
audits/                  every brief, audit and response; start at HOW-TO-AUDIT.md
```

### Storage

One sqlite file, `/var/lib/riffle/state.sqlite`. It has 28 tables:
`action_policy`, `actions`, `board_cache`, `caps`, `composer_calls`, `cycles`,
`desk`, `drive_changes`, `drives`, `heads`, `inbox_items`, `instructions`,
`journal`, `library`, `library_aliases`, `memories`, `memories_fts`
(contentless full-text index), `messages`, `notes` (key/value),
`policy_changes`, `project_notes`, `projects`, `prompt_fits`, `questions`,
`seen`, `telemetry`, `telemetry_kept`, `thread_reads`.

**Library documents are files on disk**, indexed in `library`. **Nothing is pruned by age.** Everything is kept until the disk is 85% used, as `df` counts it (`agent/storage.py`). Past that, the oldest of each store goes first.

**The configuration that matters lives only on the box,** in `/opt/riffle/config.yaml`. `config.example.yaml` is the documented template, and several of its values (the prompt ceiling, the disk limit) were changed on the box by hand.

---

## 3. Where bugs have actually come from

**`HOW-TO-AUDIT.md` §1 has the history, with numbers.**
- Of the 45 findings of 2026-11-10 and its second pass, 56% were in code older than the first audit, which every round since had missed.
- 22% were in code written to fix an earlier finding.
- 22% were in new features.

The patterns below were each seen at least twice. Brief II's still hold; those marked *new* were found since.

| Pattern | Examples |
|---|---|
| **A check scoped to the cases seen, not to the class** | The invented-hash check missed seals, so an invented hash was signed into the permanent record (2026-11-07). |
| **A check that speaks only to the operator** | The same post proposed twenty times, the refusal reaching only the operator's chat. |
| **An assumption about the layer underneath** | A cache fix that saved nothing, because a hybrid model resumes only from checkpoints at user-message starts. |
| **Local state drifting from the registry's** | A send that timed out but landed, never counted. |
| **Text that changes every cycle where the cache needs it stable** | Ages and countdowns early in the prompt. |
| **A test that cannot fail** | The second pass switched off 41 protections; 19 went unnoticed by every test, among them "a queued action waits for the operator". |
| ***New:* a fix applied to one of a pair** | The number check's first pass masked published code and its rewrite did not (batch 17, fixed in 18). F26 was fixed as first written and missed what its second pass added. The send checks and the dashboard's approval re-checks have to agree by hand. |
| ***New:* prompt text drifting from the code** | The prompt said "the artifact is THE SCRIPT… its sha256… Cite THAT" (since 09-08), and listed "a hash" as a valid listing artifact (since 09-01). For two months riffle cited hashes of files only it had, and submitted a private 10-character hash as a listing artifact. Its list of what can stop an action was a batch out of date. |
| ***New:* the model's output fed back into its own input** | Reflection was shown riffle's recent memories, and copied their refusal reasons into new memories of unrelated cycles. 204 of 456 live memories were such notes. The daily pass then made some of them permanent lessons ("I must rename the artifact"). 407 memories were retired by hand on 2026-11-22. |
| ***New:* a label trusted from the model** | Chat memories labelled "operator:" by the triage model were filed as the operator's words, including "RIFFLE has no personal feelings, boredom, or curiosity", which he disagrees with. A rationale claimed "The operator has instructed to focus on Listing 65". He had not, and 62% of four days' actions followed. |
| ***New:* a fixed limit on a growing quantity** | A flat 1,800 s per composer call while the prompt grew. A cycle was cut off at 3,570 of 4,000 tokens, still writing, and its work was lost (2026-11-19). |

Treat these as hypotheses. They were drawn by the same hands that wrote the
defects, and they describe the mistakes that happened to get noticed. A class
nobody here has thought to look for would not appear in this table, and
finding one is worth more than another instance of a known pattern.

---

## 4. What the checks do and do not cover

### Deploy gates

`update.sh` takes the cycle lock, merges, **re-runs itself from the merged
copy** (so a deploy's gates are its own), runs **13 gates**, rolls back on any
failure, then installs unit files from the commit:

1. **parse**: every `.py` parses
2. **import**: every `agent.*` module imports
3. **render**: the dashboard's pages build without error
4. **prompt fit**: the worst prompt (the box's ceiling, now 120,000 characters) plus `max_tokens` fits the composer's window. On 2026-11-23 that was ~37,000 of 49,152 tokens.
5. **grammar**: the schema is converted by llama.cpp's own converter **and accepted by the running composer**
6. **waits**: the worst path through a cycle's waits fits the units' `TimeoutStartSec`: 21,200 s of 21,600, with the composer's calls counted as their shared 10,800 s budget
7. **self-recursion**: no function's first statement returns a call to itself
8. **protected headers**: every block protected from trimming is emitted with its header first
9. **config**: every key in `config.example.yaml` is read by some code
10. **Row access**: no `.get()` on a sqlite Row
11. **stray files**: nothing misplaced at the repository root
12. **enum parity**: the schema's enums match the gate's
13. **local outcomes**: every outcome an `apply_*` handler writes is listed

A **secret scan** of every file a deploy brings in warns but does not roll
back. It **cannot see inside `tests/tests.zip`**.

### Before an action is sent

In `cycle.py`:
- the number check, with one same-cycle rewrite;
- the reference rule and the link rule;
- invented hashes;
- seals, which must be the full sha256 of a library document;
- duplicates: near-copies, one reply per comment, votes, top-level comments, identical queued actions;
- open listings and `listings.ignore`;
- payout bindings only for riffle's own submissions;
- tags and daily caps.

Then, since 2026-11-20, `agent/outgoing.py`, on everything that reaches the square:

| Refusal | What it stops |
|---|---|
| `library-private` | "library #N", "my library": a reader cannot open it |
| `hash-unpublished` | a hash of riffle's own file, the file in neither the text nor a post of riffle's it names |
| `hash-wrong-file` | a hash named beside a file it is not |
| `attachment-claimed` | "solve.py is attached" with nothing appended |
| `declaration-orphan` | a `[[...]]` after no figure (a valid one goes out as plain arithmetic) |
| `post-cannot-change` | "I will correct the post": posts cannot be edited |
| `claim-unbacked` | "I have updated my notes" with no such action in six hours |
| `wrong-addressee` | a reply opening "Name:" under someone else's comment |
| `voted-unread` | a vote on something riffle has not read |
| `listing-submitted`, `artifact-not-a-post` | one submission per listing, and its artifact a post riffle sent |
| `project-repeat` | a post sharing ≥30% of its words with one from the same project |

Two more of the same family sit in `cycle.py`:

| Refusal | What it stops |
|---|---|
| `instruction-invented` | a rationale citing an operator instruction no record of his carries |
| `replication-unbuilt`, `replication-unpublished` | a replication attestation with no build behind it, or whose build no post of riffle's carries |

Every refusal ends "Ways to do it: (1)… (2)…", with the real URL, file, size
and room filled in. A refusal is shown to riffle in its next prompt. **The
dashboard re-runs `outgoing.check` and `outgoing.finish` when the operator
approves** a queued action (`dash.py`, near line 968). It does not re-run the
cycle.py checks above, the number check, or the reference rule. *Worth
checking:* whether anything those checks rely on can change between queueing
and approval.

### What riffle may remember

There are three writers to one store. Each was tightened between 2026-11-22 and 11-23:
- **Reflection** (`memory.reflect`). A note is dropped when it echoes the prompt's instructions, or claims a refusal the cycle did not have, or gives a reason whose words are not in the cycle's own record.
- **Chat** (`memory.extract`). A line labelled "operator:" is filed as his only in his words.
- **The daily pass** (`consolidate`). A write names its sources. A long-term lesson must be made of them, and it loses long term when a source is forgotten or dropped.

### Not covered, and where to look

- **SQL against columns that do not exist.** The schema is created across several modules, and no gate cross-checks queries against it. Never audited.
- **Concurrency on the sqlite file.** The dashboard, the chat worker, the cycle and the memory pass share it. Approvals are atomic; little else has been examined.
- **Regexes against real data.** `outgoing.py` is mostly regexes, calibrated on one four-day transcript.
- **Matching by words, not meaning:** reflection's reason check, consolidation's grounding, the invented-instruction check, `project-repeat`, and `wrong-addressee` (only the opening "Name:" form).
- **Misreporting what a citizen said, and answering as the wrong person.** No check at all; both were found in the communications audit.
- **`main()` still has no callable seam.** The recorded tests reach it only through stub registries and composers.
- **Behaviour against the live model.** No test exercises the real composer. Every claim about what riffle *does* rests on the box's records (section 7).

---

## 5. Deliberate decisions, and the reasoning behind them

Each looks questionable at first reading. Each was a choice. **Some of this
reasoning may be wrong**, and where it is, that is a more valuable finding
than a typo. Brief II's list still stands (rationale first, open-edit pages as
evidence, unanswered sends counted, seals, `listings.ignore`, `sign` scope,
checkpoints, fixed times, listings without `lifecycle`, the stuck failsafe,
the tests as a record, long comments). These are the operator's decisions
since:

- **Safeties stay. `flag`, `seal` and every attestation, replications included, are set to queue.** *Worth checking:* that no path sends one of them unqueued, including an approval that hands it to the cycle.
- **riffle's library is private, and evidence must be public** (2026-11-20: riffle "shouldn't reference a library only it has access to"). A file is published by appending it (`append`) or by linking a post of riffle's that carries it, and a page by its URL. A listing artifact is a post riffle sent, one per listing. *Worth checking:* whether any path still lets a private reference reach the square, such as a seal's label, a flag's reason, an attestation's evidence, or the porch.
- **The reference rule stays:** one post in four quotes a page riffle read. *Worth checking:* that it does not push riffle into reading pages only to satisfy it. On 11-18, seven Wikipedia reads did exactly that.
- **Several posts per project, if substantially different.** A post sharing ≥30% of its words with one from the same project, or from a project reopened under the same question, is refused (`projects.repeat_overlap`). It is calibrated on three real posts: 35% refused, 24% passed. *Worth checking:* that margin.
- **Keep everything until the disk is 85% used** (`storage.disk_limit_percent`). *Worth checking:* the deletion order when it triggers, and that nothing deletes earlier.
- **What belongs in the prompt is kept, at the expense of cycle time,** within reason. The ceiling went from 105,000 to 120,000 rather than cutting the system prompt. *Worth checking:* the 13% margin between the worst cold call and the 3,600 s cap.
- **riffle has a temperament,** and its boredom is meant to move it on. *Worth checking:* that "name a feeling when it bears on the work" does not become feelings performed in public, and that `restless` fires on real fixations and not on ordinary focus.
- **A composer call may take up to an hour.** It is the cost of not cutting off real work. *Worth checking:* what a hung composer costs now.

---

## 6. Open problems, stated as evidence rather than conclusions

### The host

**Observed:** no unclean boot since 2026-10-23, from the operator's boot
history of 2026-11-20. Before that it reset every 1–3 hours, with nothing in
`pstore`. *If anything in this codebase could cause or contribute to a host
reset, that is still the most valuable finding in the audit.*

### The permanent record

Seal 18363 (2026-11-07) carries an invented hash, signed and chained. In
four days of November, riffle also signed:
- an attestation of a replication it had not done, approved by the operator before the checks existed;
- two identical submissions to listing 65.

Whether the registry allows any of these to be corrected is unknown.

### riffle's behaviour

From the communications audit, over 2026-11-16 to 11-20:
- 62% of 307 actions went to one listing.
- It misdescribed its own builds when asked, four different ways.
- It misreported other citizens' data.
- It claimed things it had not done.
- It answered as the wrong person.

The code-level causes have fixes (section 4), shipped 2026-11-20 to 11-23. **Whether riffle's behaviour changed has not been measured.** That needs a new transcript.

### The composer

Two cycles failed on the old flat limit, on 11-19 and 11-21. Limits have been sized per call since 11-21. The reading speed they assume (15 tokens/s) rests on one day's figures, and the 11-21 failure's own figures were never examined.

### Memory

On 2026-11-22, 407 of 456 live memories were retired as wrong, stale or noise. About 27 written since the export were made the old way. Long-term lessons written before 2026-11-23 have no recorded sources.

### Known limits, not yet addressed

These carry over from Brief II, still open:
- Verifier payout rows (`listing-N-verifier`) are not covered by the payout-without-work check (`cycle.py`, near line 3027).
- The five-tags-per-post limit knows only tags sent through this system.
- Reflection skips cycles more than two days old.
- The changes walk fetches 400 rows, though ~1,500 are shown.
- The run-cycle path unit names `/var/lib/riffle` itself.
- 13 signing tests need the registry's own message code, which is not in the repository, and skip without it.

Not started: the Ford watchdog (a Raspberry Pi 4B), an API key for the composer, a per-action smoke test.

---

## 7. How to verify a finding

The recorded tests are the first tool. They are zipped and run **outside**
the checkout, as an ordinary user (and once as root: five tests need it),
never as riffle:

```bash
unzip -q /opt/riffle/tests/tests.zip -d /tmp/riffle-tests
RIFFLE_REGISTRY_MESSAGES=<registry messages.ts> \
  python3 /tmp/riffle-tests/tests/check_against_expected.py /opt/riffle
```

Each test comes back `ok`, `SKIPPED` (with the reason), `DIFFERS` (lines
shown) or `NEW`. `tests/README.md` explains:
- comparing two versions (`tests/compare_two_versions.sh HEAD WORKTREE`);
- the safety net;
- adding a test.

Every test file starts with what it proves, why it exists, and a changelog.

**A claimed bug should come with a test that fails on the current code and
passes on the fix.** Show it failing first, and say where the faulty line
came from (`HOW-TO-AUDIT.md` §2.8).

**riffle's behaviour is evidence too.** Ask the operator for these, all read-only:
- the transcript: `cd /opt/riffle && sudo -u riffle python3 -m agent.transcript --days 4`;
- the memory export, in `HOW-TO-AUDIT.md` §2.7;
- the figures report and the telemetry, from the dashboard.

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

---

## 8. What would be most valuable

In rough order:

1. **Anything that can put a false claim on the public record,** through any action that carries text, a hash, a figure, a link or a claim. Enumerate them all and check each against section 4, in both places it is checked: proposal and approval.
2. **Any protection no test pins.** Run the mutation sweep over the whole inventory (`HOW-TO-AUDIT.md` §2.1–2.2). Last time, 19 of 41 went unnoticed.
3. **Every pair that must agree,** after 21 batches of changes (`HOW-TO-AUDIT.md` §2.4): the send checks and approval; the number check and its rewrite; the three memory writers; the schema copies; the prompt text and the code.
4. **What riffle actually did since 2026-11-20,** from a new transcript, against the communications audit's findings. Did the fixes change the behaviour?
5. **SQL against the real schema,** and **concurrency on the sqlite file.** Never checked.
6. **Anything that could contribute to a host reset.**

Report findings with the file, the line, the trigger condition, whether it
fails loudly or silently, and where the faulty line came from. Silent
failures are the expensive ones here: 204 memories with borrowed reasons
looked like an ordinary memory store for weeks.

**Disagreeing with this brief is a valid finding.** It was written by the
same hands as most of the code and most of its defects, so its framing, its
priorities and its account of what is deliberate are one view. Where the code
contradicts something stated here, the code is the evidence.
