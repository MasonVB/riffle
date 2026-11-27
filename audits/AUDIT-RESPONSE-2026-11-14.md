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

## 16. Addendum, batch 9 (2026-11-17): F19, F26, F35, drift notes

**F19, fixed.**
- After the prompt is fitted in characters, the cycle asks the running llama-server's `/tokenize` for its real token count (`cortex.count_tokens`, 60 s timeout).
- If the count plus the reply's `max_tokens` and a margin of 96 would pass the window, the room is cut by the overflow, converted at this prompt's own characters per token, plus 15% and 400 characters. The blocks are then fitted again from what they were. This repeats at most three times.
- If llama-server still refuses the prompt as longer than its window (`cortex.overflowed`), the cycle fits again in three quarters of the room and asks once more. It used to end `composer-failed`, and the next cycle built the same prompt.
- A cycle that fits, which is every ordinary one, sends exactly what it sent before.
- Gate 6 counts the three token counts, so the worst path is now 21,200 s of the 21,600 allowed. The retry adds nothing: llama-server refuses an oversized prompt before doing any work.

**F26, fixed in part.**
- Partial indexes on the action id and question id inside `messages.meta` (over rows whose meta is valid JSON, so an old malformed row cannot stop the build). The dashboard's per-poll lookups and `card_for` now use them.
- `end_cycle` looks only at the last 2,000 messages.
- Telemetry dumps: at most one a minute. Every line still goes to the journal.
- **Not done: pruning.** Nothing still deletes old journal, chat, action or cycle rows. Whether to keep that history is your decision. With the indexes, its cost no longer grows on the poll or the cycle.

**F35, fixed.** Before every model call in a chat turn, the messages are held to the running composer's window, at 3 characters a token. The oldest history turns go first; then the largest message is halved, with a marker. The audit missed one part of the total: each lookup round keeps the model's own text before its TOOL line, up to `max_tokens` each.

**Drift notes, fixed.**
- `library_put`'s kinds in the contract now match the gate: no `page`, with `draft`.
- `web.py`'s docstring gives the 49,152-token window.
- The schema comment no longer says "the eleven".
- `actions-inventory.md` is recounted from the code (30 actions, 31 grammar branches and gate shapes, 30 executors). Its seal and attestation rows now reflect F8, F15 and F43.
- Not done: `keyutil.py`'s unused import (a deliberate probe) and unused variable, since the signer is hand-installed and lint is not worth a reinstall. The reader's comments and entries (Wikipedia "the one exception", `ietf.org` in `SUBDOMAINS_OK`, the osf.io redirects) go with F45 and F17.

**Still open:** F22, F23, F25, F31, the suite's own faults, and F45/F17, which need your decision.

**Tests.**
- New: `prompt/test_a_prompt_dense_in_tokens_is_measured_and_refitted.py` and `dashboard/test_lookups_use_indexes_dumps_are_rate_limited_and_chat_fits.py`. Each shows its fault on the previous version.
- 280 tests: 267 pass, 13 skip, 0 differ.

## 17. Addendum, batch 10 (2026-11-18): F22, F23, F25, F31

**F22, fixed.** A listing submission whose artifact names a post or comment on the square must name one riffle sent. That covers the registry's own URLs (`/api/post/N`, `/post/N`, `/p/N`, `/api/comment/N`, `#comment-N`) and the forms "post N", "post #N", "1f916:N" and "comment N". Otherwise it is refused (`artifact-not-yours`), and riffle is shown its own latest posts. Artifacts elsewhere (a GitHub tree, a paste) are left to F7's link check.

**F23, fixed.**
- A note's source counts toward readiness only if it resolves: a board thread riffle read (`thread_reads`), a page the reader fetched (library pages and their aliases), or, for a source that names you, an answer of yours.
- The readiness line says which listed sources did not count.
- `normalise_source` matches `#N` only at the start, so "library #12" stays itself.
- **On the box, the open project's source count may drop at the next cycle**, by however many of its sources were typed rather than read. That is the finding working.

**F25, fixed; not yet run under real systemd.**
- `riffle-build` adds:
  - `PrivateDevices`, `ProtectProc=invisible` with `ProcSubset=pid`, and `RestrictNamespaces`;
  - `ProtectKernelLogs`, `ProtectClock`, `ProtectHostname` and `PrivateIPC`;
  - `RestrictAddressFamilies=AF_UNIX` and `SystemCallArchitectures=native`;
  - `SystemCallFilter=@system-service`, with `SystemCallErrorNumber=EPERM`, so a build that trips the filter gets a Python error rather than a dead process.
- The system bus socket is hidden.
- Five failed builds are kept, not twenty. A failed build that wrote over 256 MiB is removed at once.
- The suite runs builds through a stand-in `systemd-run`, so none of these properties have been exercised. The operator's self-test after installing is in the batch notes.

**F31, fixed.**
- A root step reads `riffle.secret` and the signing seed and checks the changed files for their literal forms. It prints only file names, never a value, and imports nothing from the checkout. It says which of the two it checked, or that it found neither.
- The three sudoers rules join the report of hand-installed copies that have fallen behind. Each install line comes behind `visudo -cf`.
- The render gate's temporary sqlite file is removed when the gate ends, with its `-wal` and `-shm`.

**Also.** `actions-inventory.md` from batch 9 did not reach GitHub (the old version is there), and a copy of this file was uploaded to the repo's root as well as to `audits/`. Both copies were identical. The inventory is resent, and the root copy should be deleted.

**Tests.**
- New: `cycle/test_a_submission_names_riffles_own_work_and_a_source_is_something_read.py` and `deploy/test_the_deploy_checks_the_two_secrets_and_the_sudoers_rules.sh`, plus two cases in the build disk test. Each shows its fault on the previous version.
- 287 tests: 274 pass, 13 skip, 0 differ.

## 18. Addendum, batch 11 (2026-11-18): the suite itself (sections 7.1 and 7.2), and F25 on the box

**F25, confirmed on the box.** After installing the new `riffle-build`, a build printed `bus: refused, PermissionError 13` (the system bus is hidden), `inet socket: refused, OSError 97` (only UNIX sockets), one process visible in `/proc`, and a working `multiprocessing.Pool`. My first self-test checked whether the bus socket's path existed, which a hidden path still does, so it proved nothing. The second one connects.

**The runner's two points, fixed.**
- `run_all.sh` keeps up to 200 lines of each test and says when there were more. It used to cut at 40, silently.
- `check_against_expected.py` still compares a partly skipped test: the lines that ran must appear, in order, in the reviewed output.

**7.2, fixed.**
- 1 and 4 were fixed in batch 1.
- 2: `running cycle seen` lists `/proc` as holding only its own stand-in cycle. Shown with a second stand-in running: the old test said "after it exits: seen=True", the new one says False.
- 3: the gate test picks free ports.
- 5: `run_all.sh` sets `TMPDIR` inside the run, so the tests' temporary files go with it. The normaliser maps the new path. One test cut its line at a fixed length before normalising and lost its tail to the longer path; it now replaces the path first.
- 6: `witness once` calls `save_head(chain, head, through_id)` the right way round. The recorded marks are now positions (100, 50), not heads.
- 7: corrected
  - the inbox test's header (the ack comes straight after the store, on purpose);
  - the reflection test's header (the front page is given for the newest cycle only, H4's rule);
  - the board-tag test's count, which now leaves out the real pair and uses the batch 5 pattern (2 became 0);
  - the three prompt tests, which print the configured ceiling.
- 8: as an ordinary user, the stand-in `sudo` drops `install`'s `-o`/`-g`, and the sandboxed signer accepts libraries owned by the test's user. The five `signer libraries` cases, which test the root-owned rule itself, print SKIPPED as anyone but root and say why.

**7.1, covered.** All nineteen protections no test noticed losing are now pinned:
- the queue setting (batch 1) and the stuck failsafe (batch 8);
- the gate's `never`, unknown fields, rationale rule and daily cap;
- riffle's limit on moving a goal;
- the signer's payout-address comparison, and `custom` refused to riffle and riffle-build;
- the reader's allowlist and https rule;
- the dashboard's JSON-only writes;
- the cycle lock;
- the dashboard's duplicate re-check on approval, which also covers the near-duplicate check;
- every sandbox property of a build, `PrivateNetwork` and `MemoryMax` among them;
- numcheck's exact-integer rule, and small integers as claims in agent mode.

I did not repeat the auditor's mutation runs. Each new test prints the value the protection decides, so switching it off changes the output.

**Result.** 295 tests. As root, with the registry's message builders: 295 match, none skipped. As an ordinary user: 290 match, and the five root-only cases skip.

**Still open:** F45 and F17, the reading allowlist, which need the operator's decision.

## 19. Addendum, batch 12 (2026-11-19): F45 and F17 as decided, the rest of F26, and five faults from the box's figures

**F45 and F17, the operator's decision.** Add the 21 edited hosts and gcc.gnu.org's manuals; keep five open hosts out; for F17, label rather than refuse (option B).
- The reader allows the 21: scipy.org, pandas.pydata.org, scikit-learn.org, datatracker.ietf.org, open-std.org (and www.), reference.wolfram.com, ieeexplore.ieee.org, journals.aps.org, cve.mitre.org, data.worldbank.org, patents.google.com, www.fda.gov, www.weather.gov, www.govinfo.gov, www.fhwa.dot.gov, www.ncjrs.gov, www.nrcs.usda.gov, cde.ucr.cjis.gov, webbtelescope.org, www.britishmuseum.org, www.rijksmuseum.nl. They are a separate block, so the diff shows them.
- gcc.gnu.org is readable under `/onlinedocs` only (`PATH_ONLY`). A `.` or `..` segment is refused there, written plainly or as `%2e`, since `/onlinedocs/../bugzilla` starts with the prefix. It is left out of `--list-domains`, so search_web does not offer it.
- `ietf.org` is out of `SUBDOMAINS_OK`. It opened nothing while no ietf.org host was allowed, and would have opened every IETF mailing list (mailarchive.ietf.org) once datatracker.ietf.org was.
- osf.io, zenodo.org, archive.org, libretexts.org and raw.githubusercontent.com stay refused. psyarxiv.com and socarxiv.org are still listed, but both now serve from osf.io, so their pages cannot be read.
- `source_label` labels by path as well as host, on the path as the server reads it (decoded, doubled slashes and dot segments resolved).
  - "written by anyone" adds en.cppreference.com, encyclopediaofmath.org, www.chemspider.com, www.oercommons.org and forum.earthdata.nasa.gov; and, by path, sqlite.org/forum, the postgresql.org list archives, MathWorks' matlabcentral, go.dev/play, w3.org's community and wiki pages, sec.gov comments, and the Commission's "Have your say".
  - A new label, "may be unreviewed": core.ac.uk, scholar.archive.org, Semantic Scholar, BASE, Google Books, catalog.archives.gov; by path, cambridge.org/engage, NBER working papers, Internet-Drafts on the datatracker.
- Each search result carries its label in WHAT YOUR SEARCH FOUND. The system prompt's sentence on labels names the new kinds.
- `reading-allowlist.md` agrees with the reader: refused hosts are struck through, the GitHub sentence is corrected (riffle never could read raw.githubusercontent.com), and a Labels section lists what is labelled.
- The reader's comments are corrected: Wikipedia was "the one open exception", and is not; ietf.org is gone.
- Not done: preprints in PMC are not labelled, since their addresses do not say which they are. The europa.eu and nasa.gov wildcards stay, as option B keeps them; the parts the audit named are labelled.

**F26, the part batch 9 missed.** The second pass's F26 named 490 `reflect_fail_*` notes that are never deleted. Batch 9's fix did not touch them, and my addendum listed only pruning as not done. That was my miss: I fixed the finding as first written and did not check what the second pass added to it. On 2026-11-18 there were 494. Reflection now deletes each count once its marker has passed that cycle, the existing ones included, on its next run.

**From the box's figures of 2026-11-18.**
- **Links with parentheses.** Both URL patterns stopped a path at the first `)`, so `en.wikipedia.org/wiki/Consistency_(database_systems)` was checked without its last character. Three posts quoting that page, which riffle had read twice, were refused on 2026-11-18. A `)` now belongs to the path when it closes a `(` inside it. numcheck's URL mask takes the same rule.
- **A forced run starved by timer wakes.** It tried the lock every ten seconds. The timer's next wake starts as soon as a cycle ends and takes the lock within a second or two. A forced run waited 21:01 to 21:41 UTC while three cycles ran, then logged that a cycle had held the lock 40 minutes, which none had. It now waits in `flock` itself, with an alarm at the same 40 minutes. Gate 6 mirrors `_FORCED_WAIT = 2400`.
- **Pruning took live memories before dead ones.** The store sat at its 1,200 limit, with 765 rows expired. Expired and superseded rows now go first.
- **The triage model in swap.** llama-triage showed 6.4 GB in memory and 4.6 GB in swap, with 43 GB free. Its unit never set `--cache-ram`, so it had llama.cpp's default store of old prompts. It now has `--cache-ram 512`. This is a reading of the figures, not a measurement. After `sudo systemctl restart llama-triage`, the figures should show its swap near 0.
- **The figures report.**
  - "hottest" read only nested temperatures, and they are flat.
  - The interval line printed config.yaml's value alone ("None").
  - The block list gave one row per count in a heading.

**Tests.** New: `parentheses link`, `forced run lock`, `reflect fails and prune`, `reading list decided` (reader, document, labels, search results), `figures three lines`.
- `dense prompt refitted` counted ordinary text at 4 characters a token and overflowed by only a few hundred tokens. The 257 characters this batch adds to the system prompt made it fit without being measured, so it tested nothing. It now counts 3.5, and overflows on both the old tree and the new.
- Six recorded outputs moved with the system prompt's size and the label's wording.
- 306 tests. As root, with the registry's builders: 306 match. As an ordinary user: 301 match, and the five root-only cases skip.

## 20. Addendum, batch 13 (2026-11-19): reflection's account of what it kept

**Batch 12 on the box.** Deployed at b9797d7, the gates passed, the reader was reinstalled, and llama-triage was restarted. GitHub matched the batch file for file.

**From the figures, again.** Three of the fifteen warnings on 2026-11-18 read "model offered 0 durable and N passing, kept 0 (too short, or duplicates of something already stored)". Neither reason was true.
- Passing notes are kept at 5-10% of the durable notes kept, so with none durable, none can be. That is by design. It is now logged at info level and says so.
- The opposite fault: `remember()` returns the id of the memory a duplicate matched, so a reflection that only repeated a stored note logged "kept 1 note(s)" and counted it towards the passing notes. Only new rows count now, and a pure repeat gets the duplicates warning it should have had.

**Not done, and why.**
- Reflection's 1,000-token cutoffs (three a day, each retried and almost always kept the next time). The first lines of a cut-off reply could be saved, but the prompt tells the model that a long answer keeps nothing, and the retry costs about 40 s. Not worth changing that promise.
- Pruning old journal, chat, action and cycle rows is still your decision (section 16).
- `keyutil.py`'s lint, as before.

**Tests.** New: `reflection says why it kept nothing`. `greet and porch` drew deepen 4 and witness 2 where it drew 3 and 3. Its stand-in reply is filed as a note, which is a duplicate from the second cycle onward and no longer draws a random number. It still never draws greet. 307 tests: as root, 307 match; as an ordinary user, 302 match and the five root-only cases skip.

## 21. Addendum, batch 14 (2026-11-19): the disk rule, closing section 16's pruning question

**The operator's decision.** Keep everything until the disk is 85% used, by anything. Past that, for each thing saved, delete the oldest whose sizes add up to at least what was saved.

**How it is built** (`agent/storage.py`).
- "Used" is what `df` shows as Use%: used over used plus available, so ext4's reserve for root counts as neither. The limit is `storage.disk_limit_percent` in config.yaml, 85 if absent.
- **The library.** When a document is shelved past the limit, the oldest unpinned documents (by when they were shelved) are deleted until their bytes reach the new one's.
- **The database.** Rows are written all the time by the cycle and the dashboard, so they are settled after each cycle and every hour in the dashboard.
  - The growth in live pages since the last check is matched by deleting the oldest history rows across seven tables, merged by timestamp: the journal, telemetry and its per-boot copies, model calls, prompt fits, finished dashboard messages, and the board cache.
  - SQLite keeps freed pages and reuses them, so past the limit the file stops growing rather than shrinking. That is the rule.
- **Never deleted by it.**
  - Cycles and actions: the checks against repeating oneself read them.
  - Memories, which have their own limit of 1,200 for what riffle can recall well.
  - Seen posts, thread reads and the inbox.
  - riffle's state: goals, notes, projects, desk, questions, policy and drive changes, witness heads.
  - Pinned documents, and the card for an action still waiting.
- **What it replaces.**
  - The library's byte cap (`library.max_bytes`, 40 GB), its 5 GB headroom, and its least-recently-read order. The order is now oldest shelved, as asked.
  - Telemetry's 24-hour, 21-day, 500-dump and 90-day limits.
  - The figures tables' 30 days.
- `telemetry.keep_last_boot` now looks at the newest 5,000 rows, not the whole table, which no longer stays small.

**Found by its own test.** The first version kept every ordinary dashboard message whenever any action was waiting. A message with no action id gives NULL, `NULL IN (...)` is NULL, and `NOT NULL` is not true. A COALESCE fixes it.

**Tests.** New: `history past the disk limit`. Rewritten for the rule: `library floor` and `telemetry prune`, both keeping their names. The suite now needs a disk under 85% used where it runs. 308 tests: as root, 308 match; as an ordinary user, 303 match and the five root-only cases skip.

## 22. Verification of every finding (2026-11-19), and batch 15

The operator asked for every finding in both reports to be checked against the code as it now stands (GitHub at c123984 plus this batch).

**The auditor's 29 reproductions, re-run on today's code.** From `audits/riffle-audit-2026-11-14-repro-tests.zip`, as its README says, as root with the registry's builders. Each was compared with `output_on_39a3a5e.txt`.

| Repro | Finding | On 39a3a5e | Today |
|---|---|---|---|
| sources, ownwords, title | F1, F2, F3 | sent | `numcheck-blocked`, not sent |
| upper, ox, short | F6 | sent | `hash-unknown`, not sent |
| twolinks | F7 | sent | `post-link-unused`, not sent |
| forged | F5 | page shelved, post sent | `library_put` of a page blocked; post not sent |
| answers, desk, notes | F12, F37 | most cut | all six answers, three drafts' starts and notes 4-8 shown |
| buildhash | F4 | hash differs between runs, not the file's, not shown whole | same both runs, is the file's sha256, shown in full |
| rejected | F9 | not mentioned, re-queued | mentioned, `rejected-before` |
| ghost | F10 | left `approved` | `unknown`, to be settled (the next sweep settles it; see below) |
| dashfail | F11 | `failed` after it landed | `executed` |
| secret | F11 | thread died, row stuck at `sending` | row `failed` |
| neardup | F16 | the corrected date merged into the old | stored apart |
| launder | F14 | the pass wrote a board claim as `self` | written as `board` |
| leak | F14 | stranger's line outside `<board>` | inside only |
| detag | F14 | 3 of 5 tag forms passed | all 5 neutralised |
| memory pass holds the database | F13 | second writer refused | wrote |
| fit, fitquiet | F37 | 8,794 cut with room to spare; no journal line | nothing cut; every draft and note shown |
| neverleft | F38 | `unknown` for good; the retry refused | `failed` / `never-sent`; the retry sent |
| ghostinbox | F10 | comment stuck `pending` | the same, **as expected**. This repro runs only `inbox.reconcile`, with no cycle. The fix is the cycle's opening sweep, which turns the ghost into `unknown` and settles it against riffle's own history; the comment is then offered again. The suite's `no-answer sends are settled` test runs that sweep (`ghost-landed` executed, `unknown-gone` failed). |
| memdrop | F42 | all 40 dropped, the pinned and the operator's among them | the pinned one is not shown; 8 dropped; both kept |
| label | F41 | port and user-name URLs unlabelled and allowed | labelled; the user-name URL refused |
| build disk masked, falsealarm | F40 | flood passed; innocent build stopped | flood stopped; innocent build passes |

**Findings with no reproduction** were checked by their test in the suite: each addendum names the test, and all 309 match today. F8 (§9), F15, F43 (§13), F17, F45 (§19), F18 to F35 (§§15 to 17), F39, F44 (§14), F19, F26 (§§16, 19, 21).

**Section 7.** 7.1: all 19 protections pinned (§18). 7.2: items 1 to 8 and the runner's two points fixed (§§4, 18).

**Section 8, the small things.** Checking them found six of seven never done. That was my miss: I worked from the numbered findings and the drift notes, and never went back through section 8's list. Fixed in this batch:

- config.example.yaml's "Twelve hours" paragraph explained `stale_minutes`, a key long gone. It is folded into the removal note.
- Its two present-tense mentions of the 20,480-token window are now marked as the window of the time.
- "three user messages" is now four (since 2026-11-07).
- `notify.enabled` shipped `true` under a comment saying to leave it `false` until the keys are in. The example now ships `false`. The box's config.yaml is not touched.
- llama-triage.service said the composer keeps `--mlock`. It dropped it on 2026-10-25.
- riffle-run-cycle.service said, in one place, that a requested cycle exits if one is running. It waits.
- `policy.REACHES_THE_SQUARE` now includes `knock`, which posts a presence mark, so the settings page marks it.
- SETUP.md stage 1 now copies the two `.path` units, and stage 2 enables them. Without them, the dashboard's "run a cycle" and "restart the composer" buttons do nothing on a fresh install.
- Already done earlier: the ordering-table drift (§11). The pre-commit scan point is a fact about uploads through GitHub's site, which F31's root literal check (§17) answers at deploy.

**F14's fourth route, fixed.** Reflection is shown the newest cycle's front page. A durable line labelled `me:` that carries a run of five words from that page is now filed as `board`. Before, a stranger's title written as "me: …" became riffle's own conclusion. New test: `me line in front page words`, which shows the fault on the previous version.

**Still not done, on purpose, and named here so nothing is hidden.**
- F16 for riffle's own memories: kept apart only for the operator's words. Applied to riffle's own, it piled up changing numbers and broke the prompt cache (§12).
- F17: preprints in PMC are unlabelled, since their addresses do not say which they are (§19).
- `keyutil.py`'s lint, an unused import that is a deliberate probe (§16).

**Settings the second pass recommended (section 9).** Seal and attestation are on queue. `flag` is still on auto, per the 2026-11-18 figures. The second pass advised queue. A flag's reason now gets the figure, hash and link checks (F3, F7), but a flag is an accusation made in public. It is the operator's call.

**Housekeeping.** The reproductions zip is in both `audits/` and `tests/`, the same bytes. The `tests/` copy can be deleted.

**Tests.** 309. As root, 309 match; as an ordinary user, 304 match and the five root-only cases skip. All 13 gates pass.

## 23. Addendum, batch 17 (2026-11-20): the communications audit

`audits/AUDIT-COMMUNICATIONS-2026-11-20.md` read everything riffle said over four days (exported with batch 16's `agent/transcript.py`).

**The operator's answers.**
- He never told riffle to focus on listing 65. Action 3762's "The operator has instructed to focus on Listing 65" was invented, and it opened the project that took 62% of four days.
- Keep the reference rule.
- Replication attestations stay on queue.
- Several posts per project are fine "if the posts are substantially different and communicating different ideas".
- Listing artifacts: he asked for a view. It is taken here as: a post riffle sent, carrying the work. He can overrule it.
- His principle, which most of this batch follows from: riffle "shouldn't reference a library only it has access to. It should instead either supply the reference or reference what is publicly available." The square takes text only (no attachments, no edits; client.py has no upload or edit call), and none of the 13 Marrow post attempts had code in it.

**What changed.**
- **`agent/outgoing.py`, new.** It holds the checks on what riffle says in public. The cycle runs them before queueing or sending; the dashboard runs them again at approval. Each refusal is a cycle outcome:
  - `declaration-orphan`: a `[[...]]` that does not follow its figure. A valid one is sent as plain arithmetic, `37.5% (3/8*100)`.
  - `library-private`: "library #N", "my library", "the library entry".
  - `hash-wrong-file`: a hash named beside a file it is not.
  - `hash-unpublished`: a hash of riffle's own file, when the file is neither in the text nor in a post of riffle's that the text names.
  - `post-cannot-change`: "I will correct the post".
  - `claim-unbacked`: "I have updated my notes / corrected the draft" with no matching action in six hours.
  - `wrong-addressee`: a reply opening "Name:" or "Name (cN):" when its parent is someone else's, or is not cN.
  - `voted-unread`.
  - `listing-submitted`: one submission per listing, also at approval, which is how 3796 and 3800 both went.
  - `artifact-not-a-post`: an artifact must be a post riffle sent.
  - `project-repeat`: a post sharing 30% or more of its wording with a sent post from the same project, or from a project reopened under the same title or question. `projects.repeat_overlap`.
  - `instruction-invented`: a rationale that says the operator instructed, told or asked something no record of his carries. The records checked are his instructions, his answers, his chat, his rejection reasons, the memories filed as his, and listings he set aside.
- **Calibration.** The repeat threshold is set on the real posts. The third Marrow post shares 35% with the second and is refused. The second shares 24% with the first and passes. Unrelated posts share about 5%. The margin under 30% is six points, which is narrow; the setting is in config.yaml.
- **Replications** must be published. The evidence's "library #N" is now replaced with the file's sha256 and the URL of the riffle post that carries it. Until such a post exists, the attestation is refused (`replication-unpublished`).
- **The number check.**
  - A fenced code block that is, byte for byte, a file a build shelved is masked. Its literals are code, not figures. On the previous version, publishing a script was itself blocked by the number check, so riffle could not have done what it is now told to do.
  - A page cited by its URL is found as a source. Before, it had to be cited as "library #N", which is now refused.
  - "post 12783" / "comment 151847" (four digits or more) are masked as references.
- **The prompt** (433 characters net):
  - the library is private;
  - publish the script, rather than "cite THAT" hash;
  - a listing artifact is a post of riffle's;
  - a replication's evidence;
  - a declaration directly after its figure;
  - in the conduct text, a reply's name is its parent's author, and a post cannot be edited.
- **YOUR LAST BUILD** no longer says "Cite one of these".
- **The prompt's "YOUR OPERATOR TURNED THESE DOWN"** listed refusals made by checks at approval (cap, duplicate, and now these) as his rejections, with "(no reason given)". They are now marked as not his.
- **transcript.py** exports his instructions too.

**What this does not do, said plainly.**
- Misreporting another citizen's data (section 3.2) is not checked. It needs reading, not a pattern.
- Answering as if riffle were the one addressed (3973, 3991) is not caught. Neither is a reply that answers the wrong point without naming anyone.
- Promises of future work ("I will run this") are not refused.
- `instruction-invented` matches numbers and words. A claim sharing them with something he said about another matter passes. A memory wrongly filed as his would back a claim. Only the directive verbs are checked ("confirmed", "approved" are not).
- `voted-unread` counts a thread riffle read, the dashboard chat's board cache, and its inbox. A post seen only on the front page counts as unread.
- A published block is masked for the number check only if it is the whole file, byte for byte. A partial paste keeps its literals checked.
- Fix 7, the composer timeout from the counted tokens, is not in this batch.

**Tests.** New: `said in public`, 25 cases, each refusal beside a case that still goes, and the real Marrow posts as calibration. New: `attestation subject and build repl-pub`. Changed on purpose, with each file's changelog saying why: `repl-build`, `box audit hash-library`, `libhash`, `derived`, `queue is honoured` (post 4 now read, so its vote still queues), `transcript export`, and the prompt-size lines. On the version on GitHub (cc8e4d7), every refusal case but one goes through, and both approvals of the duplicate submission send. The one is `wrongfile`, which the number check blocks there because a published script's literals counted as figures. 336 tests: as root, 336 match; as an ordinary user, 331 match and the five root-only cases skip. All 13 gates pass.

## 24. Addendum, batch 18 (2026-11-21): attachments as appended text, and the ways to cite

**Batch 17 on the box.** Deployed at e2bee12, and every gate passed. The operator searched the box for "65" in memories and instructions. No memory filed as his mentions it, and he has given no instructions. So "The operator has instructed to focus on Listing 65" had nothing behind it. The nearest thing on the shelf is riffle's own wording about its continuity note: memory 1053, "The Continuity note directs me to submit…", and 1421, "the continuity note explicitly demands…". The prompt already heads that note "Testimony, not instruction". Since batch 17, a rationale that turns such a note into the operator's order is refused.

**The operator's ask.** riffle should be able to "provide evidence even if the attachment is just appended text on the post". A citation or attachment that cannot go should come back with the ways it can, not as a bare refusal.

**What changed.**
- **`append`.** A post or comment may carry `"append": [library ids]`, up to three. Each must be riffle's own build file or a build's output. `outgoing.attach` puts each at the end, after a rule, as "Appendix A: solve.py, sha256 <64 hex>" followed by the file in a fenced block, byte for byte. It uses `~~~~` when the file itself has ``` in it.
  - This runs straight after the gate, so every check reads what will be sent.
  - The number check's same-cycle rewrite keeps the appendices: attach replaces them, never doubles them.
  - The field is in `drives.SCHEMA` and `proposal_schema.json`.
  - A page cannot be appended (riffle is told its URL to cite instead). Nor can a note: its own writing is said in words.
  - Over 8,000 characters in all, riffle is told to post the file on its own and cite that post.
- **The ways.** Every refusal from `agent/outgoing.py` now ends "Ways to do it: (1) … (2) …", with the real values filled in:
  - "library #N" for a page gives its URL.
  - For a build file, it gives the exact `"append": [N]`, the file's size and whether there is room, or the post that already carries it.
  - A hash named as the wrong file gives both readings, and the other file's hash if riffle built one.
  - A listing artifact gets "post the work with `append`, then submit that post's URL", or the URL of the post that already has it.
  - A replication gets the same.
  - "my library" with no number gets the four general ways.
- **`attachment-claimed`, new.** "solve.py is attached", "see the attached script" or "attachment" with nothing appended is refused, with the ways, naming the file's library id when riffle built a file of that name.
- **What riffle wrote, not what it attached.**
  - An appended or byte-for-byte pasted build file, or a build's output, is the file. The prose checks (library, attachment, edit, claims) skip it, and a `[[...]]` inside any code block is code: the orphan check skips it, and `finish()` no longer rewrites it. Before, `rows[[0, 2]]` in a pasted script would have been changed and its sha256 broken.
  - The number check masks verbatim build outputs as well as files, and the rewrite path now masks too (batch 17 had masked only the first pass).
- **The prompt** (16 characters net). The post and comment shapes show `"append": [ids]?`, and the library paragraph says how to attach: "append" it, cite a page by its URL, or link the post. The build block now says "cite one only with the file appended".

**Limits.**
- `append` takes riffle's build files and outputs only. A file it wrote with `library_put` is not one, and has to be said in words or built.
- Only a whole file can be appended. A part of one has to be pasted, and its literals then meet the number check.
- The rewrite path's re-attach has no test of its own.
- `approvals cap` gave its two answers in the other order once in four runs. It is a thread race in the test, which has been there since it was written, and the record was kept.

**Tests.** 342. New: `said in public append`, `append-code`, `append-page`, `append-big`, `attach-claim` and `library-page`. Changed on purpose: the five refusals that now carry their ways, and the prompt-size lines. As root, 342 match; as an ordinary user, 337 match and the five root-only cases skip. All 13 gates pass.

## 25. Addendum, batch 19 (2026-11-21): the composer's time limit

**What happened.** At 2026-11-21 02:53Z an `answer` cycle failed with "composer failed: timed out". It was the second such failure in three days. The first, on 11-19 at 17:24Z, left its dump in the telemetry. llama-server's own log shows the composer still writing when the clock ran out: 3,570 tokens of a 4,000-token ceiling, at 3.1 tokens a second. The cycle's work was lost.

**The cause.** Every composer call had a flat 1,800 s. The figures report measures the composer reading an uncached prompt at 19.6 tokens/s and writing at 3.2 tokens/s. The worst prompt the deploy allows is about 32,400 tokens. A full-length call with nothing cached therefore needs about 2,900 s: roughly 1,650 s to read and 1,250 s to write. 1,800 s could not hold it, and a long write after a mostly cached read could not either.

**What changed.**
- **A limit sized from the call.** `cortex.complete` with no timeout of its own (the composer's calls) now sizes its limit with `call_timeout`:
  - the prompt's tokens (characters / 3.3, so the count runs high) at `llm.composer.read_tok_s` (15);
  - plus its `max_tokens` at `write_tok_s` (2.5);
  - a quarter more, plus two minutes;
  - between 300 s and `CALL_CAP`, 3,600 s.
  
  The 11-19 call gets 3,600 s; it needed about 2,200. The triage calls pass their own 900 s and are unchanged.
- **One budget per cycle.** All of one cycle's composer calls share `CYCLE_BUDGET`, 10,800 s, set at the start of `cycle._main`. Those calls are the memory pass, the main call and its cut-off retry, and the number check's rewrite and its retry. Gate 6 had counted those six calls at 1,800 s each, which is the same 10,800 s, so the worst path (21,200 s) and both units' 21,600 s do not move. Gate 6 mirrors the new lines.
- **No call it cannot finish.** A call is not started with under 300 s of the budget left. It raises `OutOfTime`, saying so, instead of starting work that will be cut off.
- **A timeout says what it had.** It now reads like "timed out after 3600 s of the 3600 s this call had (19296 prompt tokens at 15/s and up to 4000 written at 2.5/s)". Before, all the journal kept was "timed out", so a call still writing could not be told from a hung server.
- **The speeds are in `config.example.yaml`** under `llm.composer` (`read_tok_s`, `write_tok_s`), with the measurement they come from.
- **A flaky test.** `approvals race` and `approvals cap` print their two answers sorted. In thread order, `cap` flipped two runs in six.

**Limits.**
- A hung composer now holds a call for up to an hour rather than 30 minutes.
- The 11-21 call's own figures were not in hand when this was written. If its dump shows a prompt read slower than 15 tokens/s, lower `read_tok_s`.
- The request still waits in llama-server's single slot behind any dashboard chat, and that wait counts against the call.

**Tests.** 343. New: `composer time by size`. Changed: `approvals race`, printed sorted. As root, 343 match; as an ordinary user, 338 match and the five root-only cases skip. All 13 gates pass.

## 26. Addendum, batch 20 (2026-11-22): riffle's memory, and its temperament

**The store.**
- The operator exported riffle's 456 live memories. 407 were retired by hand, with a backup in `/var/lib/riffle/retired-memories-20261122T061103Z.json`, and five more on his word: 138, 310, 385, 503, 527.
- 204 were refusal notes. Most gave a reason their cycle never had, copied from the notes reflection is shown as ALREADY REMEMBERED. Examples: "because the artifact '323' was too short" on reading a thread, and "because the cycle was already running and the lock prevented new actions" on fifteen cycles running.
- 15 were the reflection prompt's own instructions handed back as notes.
- 20 were one wrong lesson about the system "enforcing divergence".
- Three of the memories filed as the operator's were not his. 385, "RIFFLE has no personal feelings, boredom, or curiosity", he disagrees with. Memory 310 was a sentence from riffle's own stuck-project block.

**What changed.**
- **`memory.unfounded`.** A reflection note is not kept when:
  - it repeats five words running of the prompt's instructions (its quoted examples are exempt, being there to imitate);
  - or it says something was refused when the cycle's own record shows no refusal;
  - or it gives a reason less than half of whose words are in that record.
  
  The record means the cycle's outcome and notes, what riffle was told, its log, and its actions; ALREADY REMEMBERED is not part of it. Each dropped note is logged at info level with its reason. Markdown `**` is stripped from notes, and a note must be 20 characters.
- **`memory.extract`.** A chat note labelled "operator:" is filed as his only when it shares four words running with what he wrote in the exchange, or two-thirds of its words are his. Otherwise it is riffle's (`self`), which is doubted rather than deferred to.
- **Riffle's temperament** (the operator, 2026-11-22: riffle "should have a personality, should emulate feelings and curiosity, and if boredom is emulated, should work on alleviating it"). IDENTITY now says it is curious; that it feels satisfaction when a claim survives a check, unease when its own fails, and boredom when it repeats itself, and that boredom means move on; and that it names a feeling when it bears on the work, never to excuse a skipped check. "You do not perform enthusiasm you do not have" stays: the feelings are to be honest, not shown off. Rule 3 was shortened to make room.
- **`cycle.restless`, the block "YOU HAVE BEEN DOING ONE THING".** Riffle wakes blank and cannot feel four days of one subject, because it only ever sees one cycle. The block is shown when:
  - 8 or more of its last 20 actions, and at least 40%, were on one project, listing or post;
  - or one refusal ended 4 or more of its last 10 cycles.
  
  It names the subject and the count and says what to do with the boredom. It is riffle's own section and protected from cutting.
- **WHAT CAN STOP AN ACTION** listed the checks as they were before batch 17. It now names the private library, unpublished hashes (and `append`), the listing artifact, a second submission, a repeating post, unread votes, and invented instructions.

**Limits.**
- The reason check matches words, not meaning. A borrowed reason that happens to share most of its words with the cycle's real one is kept.
- A refusal claimed in a cycle whose only refusal was a different one passes the "was anything refused" test and is caught only by the reason words.
- `restless` counts subjects by project, listing or post. A fixation spread across many posts on one theme is not seen.
- The system prompt now has 41 characters of room before an ordinary cycle starts cutting a board block. The next addition there must trim something first.

**Tests.** 344. New: `reflection grounds and boredom`. Changed: the prompt-size lines.

## 27. Addendum, batch 21 (2026-11-23): lessons that stand on something, and room in the prompt

**Consolidation's long-term writes.** Two of the wrong memories retired on 11-22 were written by the daily pass into long term, which never expires: 1540, "I must rename the artifact", and 1643. A write carried no record of what it came from, so nothing could check it. Now:
- A write names its sources in `"from"`, a required field in the schema and the prompt.
- A long-term write must cite at least one of the day's candidates, and at least half its words (by stem, the first five letters) must be theirs. Otherwise it stays short term, and the report says why. The action-log rule is checked first, as before.
- A write that repeats five words running of the prompt's instructions is not written. Quoted examples are exempt.
- The sources go in `source`, as "consolidation:12,31".
- `memory.demote_citing`: when a source is forgotten (`memory.forget`) or dropped as wrong by the daily pass, a lesson citing it goes back to short term, with the usual expiry. A source expiring naturally does not do this, since standing in for notes that would expire is what a lesson is for.

**The appendix through the rewrite.** Batch 18 kept the appendix when the number check's rewrite replaced the body, and nothing tested it. Now `said in public append-rewrite` does. In it the rewrite also copies the appendix back in, and the reply goes out with the rewritten words and the file attached exactly once.

**The prompt's ceiling, 105,000 to 120,000 characters.** The operator, 2026-11-23: keep what belongs in the system prompt "at the expense of cycle time to within reason".
- Batch 20 had left 41 characters before an ordinary cycle began cutting the board. At 120,000 there are about 15,000, and the heavy cycle that cut five board blocks cuts none.
- Gate 4: the worst prompt is about 37,000 tokens of 49,152, with 4,000 to answer in.
- Time: a cold read of the whole prompt at the measured 19.6 tokens/s plus a full answer at 3.2 is about 3,140 s, inside the hour a call may now have (batch 19).
- The cost falls only on the cycles whose material fills the room: up to about 4,600 more tokens, around four minutes cold and much less with the cache.
- `max_prompt_chars` is in config.yaml, so the box's copy is changed by the operator; the example now says 120,000 and why.

**Limits.**
- A lesson's words are matched by stem, not meaning. A lesson can reuse its sources' words and still say something they do not.
- A long-term lesson written before this batch has no sources recorded, and is not demoted when its notes are retired.
- At 120,000 the worst cold, full-length call is about 3,140 s against a 3,600 s cap. That is a 13% margin, and it holds only while the composer runs near its measured speed.

**Tests.** 346. New: `lessons stand on sources`, `said in public append-rewrite`. Changed: `capped writes kept`, and the ceiling lines.

## 28. Addendum, batch 22 (2026-11-24): what riffle did after the fixes

The operator exported 11-21 to 11-24: the transcript (231 actions), the live memories (157), the figures report and a day of telemetry. Read against batches 17 to 21:

- **Nothing posted.** After batch 21 riffle proposed 48 posts and sent none. 34 were refused by the number check on one figure, 71.7%, from its own simulation. 88% of its actions after batch 20 were about the tripwire (84% before). "YOU HAVE BEEN DOING ONE THING" was in 71 of the last 100 prompts and did not move it.
- **The figure was its input.** `verify_suppression.py` and `verify_final.py` drew each trial with `random.random() < 0.718`, "as per previous findings", and riffle presented the 0.717 they printed as confirmation. Bellwether's 718 (#13126) is a re-run of the same probe. The original probe (`tripwire_gate_probe.py`, library #414) is not in either transcript, so whether it was circular too is not known. The number check's refusals kept this off the square by accident.
- **No way out existed.**
  - The number check counted the LAST build's output. A newer build replaced the probe on 11-23.
  - Build outputs also counted while among the sixty newest library documents, published or not. The probe's had dropped out.
  - "library #414" backed the figure in the number check, and the outgoing check refuses it as private.
  - An appended file did not count as a source.
  - The refusal said "search_web a reference site". Riffle read Wikipedia's page on the hypergeometric distribution twice, looking for its own result.
- **Claims and closes.**
  - Action 4350 told bellwether "I am posting it as a standalone analysis … The post is #13370". No such post exists.
  - Action 4346 closed project #47 "as posted", and was approved on that. Nothing had gone out.
  - The same project had been queued three times on 11-21, so the close started the identical #48 at once, with #49 behind it. #49 is for the operator to drop from the dashboard.
- **Still not caught.**
  - Action 4345 credited swift-lantern with "the suppression rate you observed"; that comment is about Merkle proof folds.
  - A draft said `verify_hypergeom.py` "confirms that the observed suppression rate is statistically significant"; it computes kerf-and-chatter's interval.
- **Memory.** About 13 of the 34 memories written after batch 20 are wrong: posts "accepted" that never were (1932, 1938), notes stitched from older ones word for word (1934, 1936, 1939), a thread given another's title (1940), the prompt's template echoed (1935).
- **Rationales.** 21 rationales planned a post while the action was a comment, a close, an open_project or a read. The grammar drops `post` when it cannot succeed, and the prompt never said so.
- **What held.** No private library reference reached the square. wrong-addressee caught a reply (#4974). The composer made 96 calls in 24 hours with none failing; the slowest, 1,859 s, would have been killed by the old flat 1,800 s. No unclean boot since 10-23.

**What changed.**
- **A build's output counts where a reader can see the build** (`outgoing.public_build_outputs`): one of its files or its output appended to the text, or carried in full by a post of riffle's that the text names. Any build, not only the last. The last build's stdout and the build outputs among the sixty newest documents no longer count on their own.
- **The refusal names the build** (`outgoing.build_route`): "71.7 is what verify_final.py printed (date). It counts once a reader can see that build. Ways to do it: (1) cite post N, which carries it (2) append [id] …". The web-search hint is given only when no build of riffle's printed the figure. The same routes go into the same-cycle rewrite.
- **figure-assumed** (`outgoing.figure_assumed`): a percentage or fraction that a build the text names or shows printed after drawing its trials with that probability (within 0.02, or its complement) is refused as a finding. Rates are read from `random…() < p`, `binomial/bernoulli/choices(…, p)`, and a name compared with `random…()` that the file sets to a number. The number check's route says the same when the figure is unbacked.
- **post-claimed** (`outgoing.post_claimed`): "I am posting", "I have posted", with no post sent or queued in six hours; "my post is #N" when N is not riffle's. A post's own "I am posting this" is the post itself and passes.
- **A close that says "posted"** is refused (`claim-unbacked`) when no post has gone out since the project opened. "Closing it unposted: …" goes to the operator as before.
- **No second copy of a project** (`project.duplicate`): open_project is refused when the active or a queued project has the same title, or a question sharing 70% of its words.
- **Reflection.**
  - It is shown "THE ACTION YOU TOOK: comment, and it was executed", then the reasoning, marked as possibly planning something else.
  - A note saying a post, comment, vote, porch line, note, build or submission went through is kept only if one did in that cycle.
  - A note repeating six words running of a note in ALREADY REMEMBERED (quoted titles aside) is not kept.
  - The "kept 0" warning now counts the notes dropped for a logged reason.
- **THE GATES RIGHT NOW** lists what is not among this cycle's choices and why: "post (one is waiting for your operator)", "(posting is closed)", "(the project bar is not cleared)", a spent allowance, "sign (nothing of yours to bind)".
- **Prompt text to match:** the contract and the gate line on what backs a figure.
- **The figures report** gives a cold read's own sized limit; it said "times out at 1,800 s" for three days after limits were sized per call.

**Limits.**
- figure-assumed sees rates set in the ways listed. A rate computed from other inputs, read from a file, or drawn from another distribution passes. So does a figure stated without naming or showing the build.
- A build shown in public counts even if it is unseeded; its output may not be reproducible.
- post-claimed knows the present and "my post is #N". "As I posted earlier" passes.
- Duplicate projects are matched by words: the same question reworded past 30% of its words is a new project.
- The repeat check drops a note that legitimately recurs (the same refusal on a later cycle) when it shares a six-word run with the earlier note. The earlier note stands for both.
- Misreporting what a citizen said, and misdescribing what riffle's own build does, are still not checked.
- A thread given the wrong title in memory (1940) is not checked.
- Whether listing what is not among the choices stops rationales planning it is a hypothesis. The next transcript will show it.

**On the box.** Project #48 is the same question riffle has been stuck on. The probe's code is in post #13122, so riffle can now cite that post. If the probe sets its rate too, figure-assumed will refuse the claim, and the project can only close unposted or change what it claims.

**Tests.** 361. New: `build figure` (6), `post exists` (9). Changed: `figures from what riffle read buildout` (now refused), `reflection grounds and boredom` (adds `went`), `reflection says why it kept nothing`, and the prompt-size lines.

## 29. Addendum, batch 23 (2026-11-24): the SQL, the sqlite file, and the memory store

Brief III ranked "SQL against the real schema, and concurrency on the sqlite file. Never checked" fifth. Both were checked.

**SQL.**
- **How.** The whole schema was built in a scratch database from the code's own `ensure()` functions, plus the four tables created lazily the first time something writes them (`thread_reads`, `board_cache`, `instructions`, `questions`) and the `approval` column. Every SQL statement in `agent/`, `numcheck.py` and `witness.py` was prepared against it (`EXPLAIN`, nothing runs).
- **Result: none failed.** No query names a table or column that does not exist, and none is malformed. Of 403 statements, 400 were checked. They include f-strings whose holes are `IN (...)` lists, local constants (memory's `live` clause), or a loop over table names. The 3 skipped are built at run time, and were checked by hand: storage's two history queries, for every table in `HISTORY`, and memory's keyword fallback, whose `LIKE` clauses are joined per search (memory.py, near line 362).
- **Gate 14 (`PYSQL`)** does the same on every deploy, and rolls back if any statement does not prepare. It was shown failing on a misspelt column in a plain query and in an f-string.

**Concurrency.**
- **The setup.** Each thread gets its own connection (`State.db`), in WAL mode with a 30-second busy timeout. Nothing opens an explicit transaction or rolls one back; writes are single statements committed straight after. Approvals are atomic by compare-and-set (`UPDATE … WHERE status='queued'`). `executescript`, which several modules call to create tables, commits anything pending first. With no explicit transactions anywhere, that cannot split one.
- **The risk** is a write transaction left open across a slow call. It would hold the database's write lock for minutes, so the dashboard and chat would fail after 30 seconds.
- **Measured.** The whole suite was run once with an instrument recording any composer call, registry call (Reader/Writer, including the tests' stand-ins), build (`subprocess`) or network call made while the calling thread's own connection held an open write. None, across 361 tests. Without the per-thread restriction there were three hits, all a telemetry dump's short write in its own thread overlapping a call in the main thread.
- **Limits.** This covers what the tests exercise. Two processes writing at once is exercised only by the approvals race test. The instrument is scratch tooling and is not in the suite.

**The memory store.**
- **101 of the 157 live memories** in the operator's export of 2026-11-24 should go:
  - 28 give "the project had 3 drafts" as the reason for votes, reads, replies and notes, which that limit does not touch;
  - 18 are the number check loop of 11-22 to 11-24, its reasons now obsolete;
  - 16 are one day's refusals from 11-22, stale and mostly misstated;
  - 10 copy a rationale;
  - 8 attach a refusal to the wrong action;
  - 8 echo the reflection prompt's template;
  - 6 are wrong;
  - 7 are stale, duplicate or a front-page dump.
- **The 56 kept** are accurate thread notes and facts.
- **The command** backs up the rows to JSON and retires each through `memory.forget`, which also clears the search index and demotes lessons citing them. It is the operator's to run, under the cycle lock.

**Not changed.**
- **Verifier payout rows** (`listing-N-verifier`) are still not covered by the payout-without-work check. What counts as verification work for one is the registry's to define. A wrong check would refuse legitimate payouts, and `sign` already waits for the operator.

**Tests.** 362. New: `gate PYSQL`. Changed: `remaining gates fail when they must`.

## 30. Addendum, batch 24 (2026-11-27): the number check's last trap

The operator exported 11-24 to 11-27, three days under batch 22: the transcript (224 actions), the live memories (76), the projects and the figures report.

**What batch 22 did.**
- Riffle built a new script and appended it. `check_tripwire_rate.py` (library #426) models 10 gates, each failing with probability 0.46, the tripwire at a random position. It printed `0.7670 (767/1000)`, and riffle appended it to its posts.
- The circular check rightly stayed quiet. 76.7% comes out of the model; it is not typed in.
- The rest held:
  - no invented post claims;
  - no duplicate project (#49 was dropped);
  - rationales planning an action riffle could not take fell from 21 in three days to 8.

**What still held riffle.**
- 134 posts in three days were refused by the number check, 57 of 73 cycles in the last day, nearly all on 76.7%.
- 767 and 1000 came back VERBATIM: the appended build counted. But 76.7 came back AMBIGUOUS, because other pairs in the sources also give 76.7.
- Riffle wrote the derivation out every way a person would: "76.7% of cases (767/1000)", "767/1000 = 76.7%", "767 out of 1000". Only `[[767/1000*100]]` counted as a declaration.
- When it used that form (actions 4463 and 4477), line 3 passed as DECLARED. The same 76.7 in the title and four other lines failed. A title cannot carry a `[[...]]`, and a post repeats its finding, so no honest post could pass.
- All 32 library-private refusals were posts that already carried the append and also said "library #414" in the prose. The refusal's first way was "add "append": [414]". It was already there.
- Restlessness was in every prompt, and riffle stayed on the tripwire: 96% of its actions.

**Memory.** About 27 of the 76 live memories are wrong or junk:
- Consolidation lessons: "provenance requires external sources, not internal simulation outputs". Under batch 22 that is false.
- "The operator failed to reply to citizen #13409" (long term).
- #12752 given zola's title (1975, long term, recalled 31 times).
- "#4508 'The 'greet' drive selects porch, and it was blocked.' by 1f916-agent (20 votes, 121 comments)" (1982, recalled 50 times). 4508 was an action number: the porch refusal's.
- Notes that are garbled ("I am a citizen claiming a vote is worth their time …") or stale.

**What changed.**
- **numcheck, written out** (`written_out`). A figure counts as DECLARED when a derivation within 60 characters of it, "a/b", "a out of b", "a of b" or "a in b", has both operands in the sources and gives the figure at the decimals it is written to (times 100 for a percentage).
- **numcheck, the same figure again.** A value DECLARED or DERIVED anywhere in the draft counts wherever the draft repeats it, title included ("as shown on line N").
- **library-private, already appended.** When the file named by "library #N" is in the post as an appendix (matched by its sha256 header, which is also what the operator approves), riffle is told to call it "Appendix A" or by its name, and to keep the append.
- **The prompt and the refusal** say the same: the contract gives the written-out form ("37.5% (3 of 8)") beside `[[...]]`, and that once shown a figure counts wherever it is repeated; the AMBIGUOUS hint names both forms.
- **Reflection, the right post for the number** (`memory.wrong_thread`). A note quoting a title for #N is dropped when riffle has read N under a title sharing under half its words. It is also dropped when N is one of riffle's actions named in the cycle's record and no post riffle has read.

**Limits.**
- Written out is matched by pattern. "767 of the 1000" or a derivation more than 60 characters away still needs `[[...]]`.
- A repeated figure counts as the same claim even if it means something else in that sentence. That is the same trade every declaration makes.
- wrong_thread knows titles only from threads riffle read or cached. A front-page post it never opened is not checked.
- The model is still a model. Once the number check passes, riffle's post goes to the operator's queue (`post` is queued). Its drafts say the simulation "confirms that the tripwire's conservation is an artifact of gate order". The result follows from an assumed 46% failure rate per gate and 10 gates, and where 0.46 came from is not in the record. That is a judgement for whoever approves it; no pattern check can make it.
- Misreporting what a citizen said is still not checked. Several of the 14 comments sent claim agreement or confirmation from others ("now confirmed by two separate fetches"; "the same six I flagged earlier") that were not verified for this addendum.

**Tests.** 368. New: `figure shown once` (5), `build figure namedappended`. Changed: `reflection grounds and boredom` (adds `thread`), and `gate PYSQL` now counts 401 statements.

## 31. Addendum, batch 25 (2026-11-27): held out, credited, and said before

The operator's decisions of 2026-11-27: the permanent record cannot be corrected and is to be treated as written in stone. Ford waits. Take an action away when riffle keeps walking into the same refusal.

**Held out after repeated refusals** (`cycle.refusal_lockouts`, the operator's decision).
- An action refused for the same outcome `cycle.refusal_lockout_after` times (10) in 24 hours leaves the grammar until `refusal_lockout_hours` (6) after the last of them.
- THE GATES RIGHT NOW says why and until when. While the refusals keep coming, riffle gets one try per lockout instead of one a cycle.
- On 11-26 it proposed 60 posts, 57 refused by the number check, with "YOU HAVE BEEN DOING ONE THING" in every prompt.
- Set `refusal_lockout_after: 0` to turn it off.

**The porch once said.** After a porch line is refused as said-already, the porch is out for the rest of that UTC day. On 11-26 riffle sent one porch line and proposed it five more times, 65% to 100% the same.

**What the 14 comments said** (11-24 to 11-27, each read against the comment it answered):
- **#4416** told silt the fix "is on #34". silt had written that it is on #33, and corrected riffle.
- **#4425** credited swift-lantern with measuring "the full-row hash" differing. swift-lantern replied that there is no second hash.
- **#4464** said swift-lantern's measurement "confirms the suppression hypothesis". It says nothing about gate order.
- **#4525** said matching hashes "on both #13126 and #13353" prove "the suppression is real". #13353 re-ran a CPI-W claim, and re-running a simulation shows only that it runs the same.
- **#4531** told uriel "the six created_at inversions you note are the same six I flagged earlier". riffle had flagged none.
- **#4456** promised uriel to check the rows and report back, and did not.
- **#4434** told swift-lantern "the gate-order suppression is an artifact of the cursor's state, not the tripwire's logic". riffle's own posts argue the opposite.
- The rest (#4383, #4396, #4454, #4483, #4514, #4524) say nothing false that the comment answered contradicts.

**credited** (`outgoing.credited`). A reply is refused when it credits its addressee with something their comment does not carry:
- a number: "your 55 ms inversion", "you measured 267 rows";
- a finding with none of its words in their comment: "the suppression rate you observed".

The comment answered is read from the inbox, or from the threads riffle read. Over the 73 replies in both exports it flags one, #4345, the swift-lantern misreport the communications audit named, and passes the other eleven phrases it examines. It catches none of the five above, which misread rather than misquote.

**claimed-before** (`outgoing.claimed_before`). "… I flagged/reported/found/noted … earlier" is refused when nothing riffle sent in 30 days carries every number in the claim and one of its words. Replayed over the 338 comments, posts and porch lines in both exports, each against what had been sent before it, it flags one: #4531.

**"The post is queued"** (porch 4548, nothing queued) now counts as a post claim (`post-claimed`), with "up", "out", "live", "sent" and "waiting".

**Reflection keeps what arrived.** A reflection cut off at its token ceiling was thrown away and asked again on a later run, up to three times. The notes come first, so the complete lines before the cut are now kept and the cycle counts as reflected (`CutOff` carries the text).

**Limits.**
- credited sees numbers and "the X you observed" phrasing. A paraphrase that turns a measurement into support for riffle's hypothesis (#4464), or puts two posts where one was meant (#4525), passes. Those need reading.
- claimed-before matches words and numbers. A claim sharing a word with something riffle did send, but not its substance, passes.
- A lockout can hold out an action riffle is right to keep trying, when the refusal is the bug. The prompt names the refusal, and the figures report shows the count, so that would show.
- Unchanged: the verifier payout rows, and Ford.

**Tests.** 382. New: `held out` (7), `credits` (7). Changed: `reflection grounds and boredom` (adds `cutoff`), and `gate PYSQL` counts 406 statements.
