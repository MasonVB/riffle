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
