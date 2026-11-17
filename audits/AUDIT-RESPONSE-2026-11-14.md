# Response to the 2026-11-10 audit and its 2026-11-14 second pass

Checked against `master` at `d8dce5f`, which is the audited commit `39a3a5e` plus the reproductions zip, so every line number in both reports applies to the code as it stood. Box evidence: `riffle-box-checks-2.sh` as run on 2026-11-14.

## 1. How each item was checked

- All 29 reproductions were run from `riffle-audit-2026-11-14-repro-tests.zip` on that commit, Python 3.13.18. Their output is identical, line for line, to `output_on_39a3a5e.txt`.
- Each finding that has no reproduction was checked by reading the lines it cites.
- The recorded suite on that commit gave 208 of 210 here. The two that differ are the TLS tests, from the Python 3.13 fault in 7.2 item 4. `host check` passed only because this sandbox is also called `vm`.

## 2. Every finding

**Fixed (this batch)** means the item is fixed in the files delivered with this response, and a recorded test pins it.

| ID | Verified how | Result | Status |
|---|---|---|---|
| F1 | repro `sources`; `cycle.py:2756`, `:347` | confirmed | **Fixed (this batch)** |
| F2 | repro `ownwords`; `material` at `:2793` | confirmed | **Fixed (this batch)** |
| F3 | repro `title`; `_tf` at `:2741` | confirmed | **Fixed (this batch)** |
| F4 | repro `buildhash`; `:4912`, `cortex.py:323`, `:3190`; box #241 | confirmed. One correction to its second half, see section 3 | **Fixed (this batch)** |
| F5 | repro `forged`; `reference.py:78`, `drives.py:269` | confirmed | **Fixed (this batch)** |
| F6 | repros `upper`, `ox`, `short`; `_HEXRUN` at `:3960`; rewrite path | confirmed, including the rewrite never getting the hash check | **Fixed (this batch)** |
| F7 | repro `twolinks`; `:3498` | confirmed | open, next batch |
| F8 | `dash.py:874-876`; `riffle-dash.service:16` | confirmed | **needs your decision** (section 6) |
| F9 | repro `rejected`; no reader of `rejected` in `cycle.py` | confirmed | open |
| F10 | repros `ghost`, `ghostinbox`; box shows 12 rows | confirmed | open, with F38 |
| F11 | repros `dashfail`, `secret`; secret read outside the `try` | confirmed | open |
| F12 | repros `answers`, `desk`, `notes`; `_BUDGETS` | confirmed. The box still has no operator answers | open, with F37 |
| F13 | repro; `consolidate.py:379-381` | confirmed. The box's pass ran 453 s on 11-14, longer than the dashboard's 30 s busy timeout | open |
| F14 | repros `launder`, `leak`, `detag`; `consolidate.py:324`, `_BOARD_TAG` | confirmed | open |
| F15 | `drives.py`, `cycle.py:2999`; the second pass's correction | confirmed as corrected | open |
| F16 | repro `neardup`; `memory.py:138` | confirmed | open |
| F17 | not checkable from here (no route to those sites) | stands on knowledge | open |
| F18 | `update.sh:52`, no `exec` | confirmed by reading | open. This batch was checked to be safe under it: the old gates pass against the new tree (section 5) |
| F19 | no retry on a context overflow | confirmed | open |
| F20 | `:489` | confirmed | open |
| F21 | `:1305` `MAX(created_at)` | confirmed | open |
| F22 | `listing_submission.artifact` free text | confirmed | open |
| F23 | `project.py:298` regex matches `library #12` | confirmed | open |
| F24 | no redirect handler; `_req_conditional` reads the body unguarded | confirmed | open |
| F25 | `bin/riffle-build` directives | confirmed by reading | open |
| F26 | `state.py:322`; `telemetry.py:624`; box: 469 `reflect_fail_*` notes | confirmed | open |
| F27 | `riffle-restart-composer.service:17` runs `flock` as root | confirmed | open |
| F28 | the cooldown branch | the line has moved, but the behaviour is there | open |
| F29 | `notify.py` covers proposals only | confirmed | open |
| F30 | `dash.py:291`, `:1412-1420`, `:752`; `policy.py:142` | confirmed | open |
| F31 | not run (needs the box) | stands | open |
| F32 | `cycle.py:2267`, `inbox.py:422` | confirmed | open |
| F33 | `library.put` dedupe | confirmed | open |
| F34 | `near_duplicate` floor of 12 words | confirmed | open |
| F35 | chat prompt has no total budget | confirmed by reading | open |
| F36 | replaced by F38 | agreed | — |
| F37 | repros `fit`, `fitquiet` | confirmed. Smaller on the box on average, see section 3 | open, next batch, shipped alone |
| F38 | repro `neverleft`; box: 7 `unknown` rows, 4 of them DNS (never left) | confirmed | open, next batch |
| F39 | `rebuild_index` called nowhere; box: 8 orphans | confirmed | open |
| F40 | repros `masked`, `falsealarm` | confirmed | open |
| F41 | repro `label` | confirmed | open |
| F42 | repro `memdrop`; box: 39 dropped on 11-08 | confirmed. None of those 39 was pinned or the operator's | open, next batch |
| F43 | `cortex.py:168`; box attestation 3560 (`replicated-population`, evidence "marrow_covariance_drift.py") | confirmed by reading | open |
| F44 | PYWAIT reads one unit | confirmed | open |
| F45 | not re-run by program | stands | open |
| Drift notes | `MEMORIES THAT CARRY`, `THINGS YOU NOTED FROM` in `_OWN_ORDER`, `THE NULLS IN WHAT` in `_BOARD_ORDER` | confirmed | open, goes with the F12 gate |
| 7.1 | the queue line | confirmed: the new test catches the mutation | **test added** |
| 7.2 items 1, 4 | `host check`, TLS fixture | confirmed | **Fixed (this batch)** |
| 7.2 items 2, 3, 5, 6, 7 and the runner points | — | confirmed by reading | open |

## 3. Corrections to the reports

**F4, second half.** The second pass expected the 18 refused hashes to be the first 12 or 16 characters of a real library hash followed by an invented tail. Box-checks-2 shows that is true of 1 of 19: the seal hash `78805fea…`. Fifteen are `27fb78dff1d…`, which is a value riffle's own `solve.py` printed. riffle then cited it as the script's hash, from its own project note and desk draft, after the next build replaced `last_build`. Two are the placeholder `a1b2c3d4e5f6`, and one is unaccounted for. So F4 explains the seal. The loop that followed was riffle citing its own notes, which is F2. Both are fixed in this batch.

**F37 on the box.** Over 149 fitted cycles, the room left empty was 2,466 characters on average, about 4% of the room, not the 13–35% of the two samples. The other half of the finding stands, and it is the part that matters: riffle's own section had 3,600 characters to spare on average while the desk was cut to 1,200.

**A small finding of my own.** `cycle.py:2993`, the correction check, reads `cfg["registry"]["handle"]`. The config has no such key, so it falls back to the literal `"riffle"` and works only because the handle happens to be `riffle`. The new code reads the top-level `handle`. That line itself is not changed yet.

## 4. What changed in this batch, and why

**`numcheck.py`**
- New `--declared FILE` for the writer's own `sources`. These are no longer read as a source file (F1).
- A declared number counts only if a real source or the context carries it, and then only as an operand for a derivation.
- A declared number that nothing carries is reported by name as `NOT-FOUND`. That alone never fails a draft. The draft fails only if a figure leans on it.

**`agent/cycle.py`**
- **One idea of evidence, in `_evidence()`.** It holds:
  - the board side of the prompt, with riffle's own comments, posts and front-page items stripped out;
  - an allowlist of riffle-side blocks that are program facts or the operator's words;
  - stored thread reads, pages the reader fetched, registry fetches, operator answers and operator memories.
- **The figure check (F1, F2) and the hash check both use it.** The hash check also gets the last build's output and file hashes, but not its source, because riffle writes the source.
- **Every outward field is checked for figures and hashes (F3):** title, body, note, artifact, claim, reason and evidence. Flags are now covered too.
- **Hashes (F6).** The check now ignores case, sees `0x` forms, and sees runs of 7 or more characters. Under 12 characters, a run must contain a digit, so "defaced" is not a hash. `c123456` comment references are skipped.
- **The same-cycle rewrite** now gets the hash check, and replaces every text field rather than only one.
- **A cited library document backs a figure only if the program shelved it.** That means a fetched page, a registry fetch, or a build's file or output. A `library_put` of riffle's own does not count, and the refusal says so.
- **Builds (F4).**
  - Each file is shelved as its own exact bytes, so its library sha256 is the file's sha256. It is stable across runs, and anyone with the file can reproduce it.
  - The output is shelved as a separate document.
  - YOUR LAST BUILD now prints every hash in full, before anything that might be cut.
- **Seals (F4)** take `library_id`. The cycle fills in the sha256 and stores both, with the document's title, so the card you approve shows exactly what will be signed.
- **The library tools show every hash in full.** `library_find` and `library_read` print the full sha256, and `library_find` accepts a hash prefix.
- **`library_put` refuses `kind: page`, and sources starting `build:` or `1f916:` (F5).** This is a second line behind the gate.
- **Listing set aside.** Work on a listing in `listings.ignore` (submission or payout binding) now gets one plain refusal: set aside for good, stop, clear its drafts. Before, it listed five possible reasons. Listing 13 drew 17 refusals in a week.

**`agent/drives.py`**
- `seal` takes `library_id`.
- `library_put` kinds exclude `page`, and its source may not claim `build:` or `1f916:`.
- `_hex64` is removed; nothing used it any more.

**`proposal_schema.json`**
- The seal branch has `library_id` in place of `hash`.
- The `library_put` kind enum no longer offers `page`.

**`agent/library.py`**
- `find` returns `sha256` and matches a hash prefix.

**`agent/cortex.py`**
- The contract for `seal`, `sources` and build hashes now says what the code does. This adds 523 characters to the system prompt, and gate 4 still passes.

**`update.sh`**
- Gate 8 skips the two new tables, which name headers without emitting them.

**`actions-inventory.md`**
- The `seal` row is updated.

**`tests.zip`**
- 225 tests: the 15 new ones, the two seal cases rewritten, and the two suite-fixture fixes. Its README changelog says what each is and why.
- Here: 212 pass, 13 skip (the registry-extract tests), 0 differ.

## 5. Limits of this batch, stated plainly

- **Expect more `numcheck-blocked` cycles at first.** Figures riffle carried in its own notes, and not from a thread it read for the project, will be refused until it cites the source. The refusal now says which listed value was not found and why.
- **The own-words stripping works by pattern.** It matches the comment line, the post heading and the JSON `"author"` line. A format I did not find (the inbox, for example) still passes riffle's own words through.
- **Stored evidence is bounded.** It covers the newest 40 thread reads plus the open project's, the newest 60 pages and fetches, and 1.5 MB in all.
- **Nothing checks that a seal's label means anything.**
- **F7 is not touched,** so a post's second link still rides on its first.
- **F18 still holds,** so the gates that ran on the box were the old ones. I checked that the old gates pass against the new tree: old gate 8 sees more literals, not fewer, and gate 5 and the enum gate read the new files.
- **Nothing was run on the box or against the real model.**

## 6. Your decision, before F8 can be written

Should an approved seal or attestation be sent by the next cycle, which can sign, rather than by the dashboard, which cannot? I would say yes. It costs one cycle's delay after you approve.

## 7. Settings for the box

- `seal: queue` or `never`. A seal can no longer carry a typed hash, but it is permanent.
- `attestation: queue` until F43 has its code half. If you approve one now, it goes out unsigned until F8.
- Answer the three open questions; riffle is at its limit. Two are about listing 13: "set aside for good" closes them.

## 8. Next batches, in order

1. F37 with F12 and the drift notes, shipped alone.
2. F38 with F10, plus a decision on the 12 old ghost rows.
3. F42, then F7, then F8 once you have decided.
4. F9, F11, F13, F14, F16, then the Low findings and the remaining suite faults.

## 9. Addendum, batch 2 (later on 2026-11-14)

**F8, fixed, as the operator decided.** A seal or attestation approved on the dashboard is no longer sent by the dashboard. It is marked `approved` with `send_by: cycle`, and a cycle is requested. That cycle sends it under the lock, before anything else it does, and can reach the signer (`cycle._send_approved_signed`).

- **Rows left `approved` by the cycle's own auto path** carry no such mark, and are never sent again. Those are the F10 ghosts, which may have landed.
- **A row cut off mid-send** is `running`, and is swept to `unknown` like an interrupted local action.
- **Once the registry has answered,** no bookkeeping error can turn the row back to failed.

**New, found on the box: questions never reached the operator.** Three questions had waited up to five weeks, and none had been seen. A question was only a chat message:

- the page's first load is the newest 400 messages, about two days;
- the clear button archived it;
- nothing re-sent it or counted it as waiting.

Every open question's card is now sent on every poll, archived or not, and counts in the "waiting" pill, which jumps to it. A clear no longer archives an open question, or a proposal still queued or sending.

**F29, fixed.** Each open question is pushed once, recorded in the previously unused `questions.seen` column.

**Tests.**
- New: `dashboard/test_an_open_question_is_always_on_the_page_counted_as_waiting_and_pushed_once.py`.
- Rewritten for F8: `signing_and_payouts/test_an_unsigned_send_is_reported_...`.
- 226 tests: 213 pass, 13 skip, 0 differ. Both fail on the previous code.

**Layout.** The audits are now in `audits/`, and the tests in `tests/tests.zip`. The tests README says so.

## 10. Addendum, batch 3 (2026-11-15): F10, F38, F36

**F38, fixed.**
- **A send that never left the box is now `failed`**, which every check reads as not sent. That covers name resolution, a refused connection, an unreachable network, and a certificate failure. Before, it was `unknown` for good. On a cycle send it ends `never-sent`. An approved seal or attestation that could not leave stays approved, for the next cycle.
- **A send with no answer is settled at the start of the next cycle,** under the lock, at most every 15 minutes. Anything sent less than 10 minutes ago is left `unknown`, since it may still be arriving.
  - Comments and posts are looked for in riffle's own registry history (`GET /api/me/history`): found means `executed`, not found with the history read to its end means `failed`.
  - Porch lines are looked for on that UTC day's porch.
  - Votes and tags become `failed`, because the registry refuses a second one.
  - Seals, attestations, flags and submissions wait for the operator, whose card now has "it is on the square" and "it is not there" buttons (`POST /api/resolve`).
  - A cycle's no-answer send now gets a card; before, it got a line of text.
  - Unsettled sends count in the "waiting" pill.

**F10, fixed.** At the start of a cycle, any `approved` row of a square-reaching kind is treated as a ghost and becomes `unknown`, so it is settled as above. The exceptions are local kinds, and rows marked `send_by: cycle`.

**F36.** `_NEVER_LEFT` now also has "No address associated with hostname" and certificate-verification failures. Connect timeouts are not included: urllib does not tell them apart from a timeout after sending.

**Bounds.** Each cycle reads at most 4 pages of history and 2 porch days of 4 pages each, and makes at most 2 approved signed sends. Gate 6 counts them, mirrored from the code: the worst-case wait goes from 20,270 s to 21,020 s, against the unit's 21,600 s.

**Limits.**
- A porch line sent just before midnight UTC and landing after it is looked for on the wrong day. It would be marked not sent, wrongly.
- A comment is matched on post id and the first 300 characters of its body, whitespace-normalised. A registry that rewrites a body (it does not today) would make one look missing.

**Tests.**
- New: `send_checks/test_a_send_with_no_answer_is_settled_against_the_square.py`.
- The box-audit `send-*` cases print the reply's status.
- 227 tests: 214 pass, 13 skip, 0 differ.

## 11. Addendum, batch 4 (2026-11-15): F37, F12, drift notes; the box at 64 GB

**The window and the ceiling.**
- The composer's window goes from 24,576 to 49,152 tokens, and `max_prompt_chars` from 62,000 to 105,000.
- What limits the ceiling is time, not memory. A cold read (after a restart, or any change to the system prompt) of ~30,000 tokens at ~21 tokens/s is ~1,420 s, inside the composer call's 1,800 s timeout.
- The rest of the window is margin for token-dense text (F19).
- The cycle now holds the ceiling to the window the *running* composer reports (`/props`), by gate 4's arithmetic. Raising the ceiling before the composer restarts therefore cannot overflow it.

**F37, fixed.**
- **Caps.** Every block's cap is now above the largest that block measured on the box, so an ordinary cycle cuts nothing.
- **Hand-back.** On the board, room left by the caps is handed back to what they cut, most important block first. riffle's own section keeps fixed cut points, for the cache.
- **Logging.** Every cut is logged as "cap cuts …", whether or not the section was over its room.

**F12, fixed.**
- `ANSWERS FROM YOUR OPERATOR` has its own budget (6,000), ranked with the work at hand, and sits in the stable head.
- The desk's cap is 9,500 (desk.py holds it to 9,000).
- The project block and its "posting is closed" form are cut from the middle, keeping their opening, their newest notes and the instruction at the end.

**Drift notes, fixed.**
- `MEMORIES THAT CARRY` is gone.
- `THE NULLS IN WHAT` is out of the board's order.
- `THINGS YOU NOTED FROM` is moved from riffle's own order to the board's, *last*. That is where being unlisted had put it, and it changes most cycles. I first listed it second, which ended the reusable board there; the cache test caught it.

The gate the audit proposed (every header must have a budget and an order entry) is not written.

**What it costs.** The board, new every cycle, is now sent nearly whole. In the suite's realistic pair of cycles, the composer re-reads 31,439 characters instead of 17,585: about 4,000 more tokens, about 3 more minutes a cycle.

**Tests.**
- New: `prompt/test_an_ordinary_box_cycle_sends_every_block_whole.py` and `prompt/test_the_prompt_ceiling_is_held_to_the_running_composers_window.py`.
- Seven recordings were re-made, each checked (see the tests README).
- 229 tests.

## 12. Addendum, batch 5 (2026-11-15): F9, F11, F13, F14, F16, F42

**F9, fixed.**
- The reject button (chat card and ACT page) asks for an optional reason. Cancel aborts the reject; an empty answer rejects with no reason.
- The next prompt has a block, YOUR OPERATOR TURNED THESE DOWN: the last 3 days' rejections, each with what it was and his reason. It sits in the tail, after `</board>`; the reason passes through `_detag`.
- A post, comment, porch line, attestation, flag or listing submission matching one of those (same title, or ≥55% of its body's words) is refused as `rejected-before`, and riffle is told why.
- A card cleared with dismiss after it *failed* or was *refused* is not counted: that was not a judgement on what it said. Dismissing a *queued* card counts as a rejection.
- The dismiss message no longer promises "I will not retry it"; it points to the card's buttons.

**F11, fixed.** In the dashboard's send worker, once the registry accepts, the row is `executed` and stays so. A failure in the bookkeeping after it is logged ("was sent, but recording what followed failed"), not turned into `failed`. The secret is read inside the `try`, so a missing secret ends `failed`, not stuck at `sending`.

**F13, fixed.** The pass commits before the continuity call. No model call with a write open.

**F14, two of three routes fixed; the fourth (by reading) is not.**
- A memory the pass writes while any board-kind memory was among what it was shown is stored as `board`.
- YOUR LAST REFUSAL quotes only the first line of the check's message, so a refusal that appends a thread's replies no longer carries them outside `<board>`.
- `_detag` now uses `<\s*(/?)\s*board\b[^>]*>`, so attributes, spaces and capitals are caught.
- Not done: the reflection pass's `me:` lines from front-page titles.

**F16, fixed for your words only.**
- An operator memory whose figures (digit runs, on/off/yes/no) differ from an otherwise matching one is stored as a new row beside it.
- It does not retire the old row: the same words with another number are as often a different thing as a correction.
- riffle's own memories are still merged as before. Applying the rule to them made reflection memories with changing numbers pile up and change WHAT YOU REMEMBER every cycle, which broke the prompt cache. The suite caught that, and I narrowed the rule.

**F42, fixed.**
- Pinned memories are not candidates. The pin route moves the memory to long term, and the pass moves any pinned before this fix.
- The pass refuses to drop an operator memory.
- Drops are capped at 8 a day (`memory.max_drops_per_day`, default 8; not in config.example.yaml).
- The report shows each dropped memory's text.
- Unpinning leaves the memory in long term.

**Also.** THE GATES' numcheck line now says a figure must be in something riffle read, and that listing it in sources does not back it. That is +99 characters in every prompt.

**Tests.**
- New: `cycle/test_a_rejection_reaches_riffle_with_its_reason_and_a_repeat_is_refused.py`, `memory/test_the_daily_pass_keeps_what_the_operator_pinned_or_said_and_does_not_launder_board_words.py` and `dashboard/test_a_send_that_landed_stays_sent_when_what_follows_fails.py`. Each shows the bug on 30ef918.
- Five recordings were re-made (the +99).
- The audit's own repros for these findings all show the fixes.
- 240 tests: 227 pass, 13 skip, 0 differ.

## 13. Addendum, batch 6 (2026-11-16): F7, F15, F43's code half, F12's gate

**F7, fixed.**
- **Posts.** Every outside link in a post is checked on its own: it must be a page read with `read_page`, and the post must quote a passage from *that* page. A link with no `https://` (`1f916.square/docs`) counts. The refusal names each failing link.
- **Comments, porch lines, submissions, attestations and flags.** A link is refused (`link-unread`) when riffle never read a page on that site and the address appears nowhere in what it read. The registry's own pages are exempt.
- **Order.** This check runs after the hash and figure checks, so those still speak first.
- **System prompt.** Its link paragraph now states both rules.

**F15, fixed.**
- `dispute` and `retract` are out of the grammar and the gate until riffle can send `target_attestation_id` and `withdraw_when`. `bin/riffle-sign` keeps all seven classes, as the registry does.
- A `code-merged`, `replicated-*` or `docket-shipped` attestation addressed to riffle itself is refused locally (`wrong-class`).
- The refusal for a correction aimed at someone else no longer says "send it as cls=dispute". It says to answer their claim in a comment.
- The system prompt lists the five classes, says which are about others, and no longer points to "fetch guide".

**F43, code half, fixed.**
- A `replicated-total` or `replicated-population` attestation must name, as `library #N`, a document a build shelved: one of its files or its output. Otherwise it is refused (`replication-unbuilt`), and riffle is told its builds' newest.
- The cycle adds `library #N sha256 <hash>` to the evidence, as a seal's hash is filled in.
- **Limit:** this shows that a build ran and produced that document. It cannot show that what ran was the subject's method.
- The settings half stands: keep `attestation: queue`.

**F12's gate, written.** Gate 8 now refuses a deploy in four cases:
- One of riffle's own blocks is in none of `_NEVER_TRIM`, `_TAIL_HEADS` or `_BUDGETS`.
- A board block is in `_OWN_ORDER`, or one of riffle's own blocks is in `_BOARD_ORDER`.
- A `_KEEP_WHOLE` or `_CUT_MIDDLE` entry has no budget.
- An entry in any table is a header nothing emits.

Before passing, the gate found five unbudgeted blocks:
- "YOU CAN ASK YOUR OPERATOR A QUESTION" and "PROJECTS WAITING BEHIND THIS ONE" now have budgets, listed last so no other block's rank moves.
- The time, drive and caps lines are protected. On a tight cycle they had been the first blocks stubbed out.

The suite holds the gate to the audit's three drifts. It does not check that a cap is above what its block measures on the box.

**Limits.**
- A site's bare name with no path (`sqlite.org`) is not treated as a link.
- Outside posts, any page on a site riffle read passes, read or not. That is the audit's lesser rule.
- A document first shelved by riffle with `library_put` and later rebuilt byte for byte keeps its first row, which has no build source, so naming it in a replication is refused.
- The system prompt changed, so the first cycle after deploy re-reads it cold, about 1,400 s, inside the 1,800 s timeout.

**Tests.**
- New: `send_checks/test_every_link_is_a_page_riffle_read.py` and `send_checks/test_attestations_go_to_the_right_subject_and_a_replication_names_its_build.py`. Each case shows the bug on the current version.
- Three gate 8 cases were added to `gates fail when they must`.
- 254 tests: 241 pass, 13 skip, 0 differ.

## 14. Addendum, batch 7 (2026-11-16): F39, F40, F41, F44

**F39, fixed.** The daily memory pass now calls `memory.repair_index`. It rebuilds the search index the first time it runs (behind a note key) and again whenever the index stops having exactly one entry per memory. The count alone could not be relied on: a delete given the wrong text still removes the entry's size record, so the words it leaves behind never show in a count. Hence the one unconditional rebuild. The pass logs "search index rebuilt: it had N rows for M memories".

**F40, fixed.**
- `riffle-build` now measures the build's own bytes: its work directory, plus its private `/tmp` and `/var/tmp`, counted as allocated blocks. `PrivateTmp=yes` puts those under `systemd-private-*-<unit>`, and `/var/tmp` is on the main disk. The audit's fix (walk the work directory) would have missed them.
- A disk below the 1 GiB floor still stops a build, but the message now says the disk is full and how much the build itself had written, and tells riffle to tell you.
- The once-a-second check and the last look after the build are kept.

**F41, fixed.**
- `source_label` goes by hostname, matched with or without `www.`.
- The reader refuses a URL with a user name, or with a port other than 443. Port 443 itself is allowed and labelled.
- The library's page titles and tags, and search's site filter, use hostname too.

**F44, fixed.**
- Gate 6 reads `TimeoutStartSec` from both cycle units.
- New gate 14 (PYUNIT) requires every directive line of `riffle-run-cycle.service` to match `riffle-cycle.service`, apart from the four differences its header names (description, `--force`, the request-flag cleanup, the start limit) and the timer unit's `[Install]`.
- While comparing the units I found `riffle-run-cycle.service`'s comments saying "four helpers" while listing three. They now say three. No directive changed.

**Not in this batch.** F45 (the allowlist document and the reader disagree) and F17 (open-edit pages on allowed hosts) need decisions about which sites riffle may read. That is the operator's call, so I have left both.

**Deploy note.** update.sh does not install `bin/riffle-build` or `bin/riffle-reader`, on purpose. It prints the `sudo install` line for each when they are behind. Until those two are installed, F40 and the reader half of F41 are fixed in the repo only.

**Tests.**
- New: `build/test_the_disk_budget_counts_the_builds_own_bytes.py`, `memory/test_the_memory_search_index_is_rebuilt_once_and_when_it_drifts.py` and `web/test_a_port_or_user_name_does_not_lose_the_written_by_anyone_label.py`. Each shows the fault on the previous version.
- `gate PYUNIT` is new, and `gates fail when they must` has five new cases.
- 262 tests: 249 pass, 13 skip, 0 differ.

## 15. Addendum, batch 8 (2026-11-17): F18, F20, F21, F24, F27, F28, F30, F32, F33, F34

**F18, fixed.** After the merge, update.sh `exec`s the merged update.sh with `RIFFLE_AFTER_MERGE` set to the commit it started from. The new copy skips the fetch, the lock and the merge, and runs its own gates against its own tree. `exec` keeps the process id, so the lock helper, which watches that id, still holds the cycle lock. Taking the lock again would have had the helper wait 15 minutes on the lock it already held. **This deploy itself still runs the previous update.sh.** I ran its gates against this tree, and all 13 pass. From the next deploy on, a gate and the code it mirrors can change together.

**F20, fixed.** An alarm verdict on any page of the witness walk, or on a first run with no mark, now alarms and notifies you as on the first page. The log line says which page, and whether the walk started from a mark or from the start.

**F21, fixed.** The stuck failsafe measures the last send by `executed_at`, not by when the action was proposed. With nothing ever sent, it counts from riffle's first cycle and says "I have never sent anything", where before it could never fire.

**F24, fixed.**
- A request carrying the secret goes through an opener that does not follow redirects. A 3xx comes back as an error naming where it pointed, and is never followed.
- Reads carry no secret and still follow redirects.
- `_req_conditional` guards its error-body read, as `_req` does.

**F27, fixed.** `riffle-restart-composer.service` first touches both lock files as riffle (`runuser -u riffle -- touch`), then takes them with `flock`. `touch` changes only an existing file's time, so a lock already held is not disturbed. `install` or `cp` would have replaced the file. The step is prefixed `-`, so a missing data directory doesn't stop the unit.

**F28, fixed.**
- `deepen` is drawn, and boosted during the cooldown, only if it still exists.
- A weight from the goals page must be a finite number from 0 to 1. The page itself offers 0.02 to 0.5.
- On the previous code a NaN weight raised a database error.

**F30, fixed.**
- `/api/decide` answers 400 to a non-number id.
- Discarding an `accepted` or `running` local action is refused, with the reason.
- Approving a `remember` never pins it. The card says it asked for a pin, which is yours to give.
- A change to a goal's restrictions is written to `drive_changes`, the goals' history.

**F32, fixed.** Rows riffle sees as the registry's JSON use the registry's names: `body_truncated` and `body_length`, the registry's own value where the row carries one. `body_full_chars` is gone from them.

**F33, fixed.**
- When identical bytes are shelved from a new source, that source is recorded in `library_aliases`. The file is still stored once.
- The page-read checks (links, references), the replication check (F43) and the evidence the figure check reads now look at aliases too.
- This also closes the batch 6 limit: a build output matching a document riffle had shelved first now counts as the build's.

**F34, fixed.**
- A body under 12 words is caught when it repeats one of the last 60 of its kind word for word, in any order. Overlap on so few words would be noise, so only an exact word set counts.
- The window is 60, up from 15.
- A second reply to the same comment is left to the one-reply check, whose refusal names the comment.

**Limits.**
- The private `/tmp` and lock fixes (F40 last batch, F27 here) were not run under real systemd.
- `/usr/sbin/runuser` is assumed (util-linux on Debian).
- F19 (count real tokens), F22, F23, F25, F26, F31, F35 and the drift notes are still open, as are F45 and F17, which need your decision.

**Tests.**
- New: `deploy/test_the_merged_update_sh_runs_its_own_gates.sh`, `send_checks/test_the_secret_never_follows_a_redirect.py`, `deploy/test_the_composer_restart_never_creates_a_lock_file_as_root.py`, `witness/test_a_broken_chain_alarms_on_any_page_and_on_a_first_run.py` and `cycle/test_small_faults_from_the_first_audit_stay_fixed.py`. Each shows its fault on the previous version.
- 275 tests: 262 pass, 13 skip, 0 differ.
