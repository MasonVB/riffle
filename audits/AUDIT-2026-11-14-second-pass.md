# riffle audit, second pass, 2026-11-14

Audited: `github.com/MasonVB/riffle`, branch `master`, commit `39a3a5e`, which is still the head of master today.
Registry cross-checks were redone against `1f916-ai/1f916` at `23b009a` (2026-11-13).
Box evidence: the output of `riffle-box-checks.sh` you ran on 2026-11-12, and your three screenshots of the settings page.

This document adds to `AUDIT-2026-11-10.md`. It does not repeat the detail of F1 to F36. Section 4 gives the status of each after your box output, section 5 has the new findings, and section 6 lists what I got wrong the first time.

## 1. What this pass did, and its limits

Done in this pass:

- Went through the box output line by line and matched it against the code.
- Finished the reading. Every tracked file in the repo and every file in `tests.zip` has now been read, with the one exception below.
- Ran 41 single-point mutations of riffle against the recorded suite, to find protections that no test would notice losing.
- Wrote 8 more reproductions (29 in all) and re-ran the first 21 from a fresh unzip of `tests.zip`. Their output is identical to the output file in the first zip. All 29 print the same as root on Python 3.12 and 3.13, and as an ordinary user on 3.12.
- Ran the suite as root, as an ordinary user, under Python 3.12 and 3.13, and under a different machine name.
- Re-read every line reference and figure in this report against the source before sending it. That pass changed more than a dozen statements; section 6 names the ones that mattered.

Limits:

- `testsrc/witness-2026-08-21.jsonl` (894 public witness records) was checked by program for structure and for anything secret-shaped. I did not read it line by line.
- The registry's source was read only where riffle talks to it.
- Nothing was run against a real model, the real registry or the box. Everything I say about the box comes from one script run on 2026-11-12. Six fitting lines and five memory passes are small samples.
- F17 (the allowlist) is still from what I know of those sites, not from fetching them.
- The mutations are 41 I chose by hand. "Not noticed" means no recorded test changed its output. It does not mean the code is wrong, and a wider sweep would find more.
- My sandbox was wiped and rebuilt from GitHub twice during this work. I re-ran the baseline after each rebuild (210 of 210 as root on Python 3.12) before trusting anything.

## 2. Headline

The box confirms the two findings I most wanted tested. The invented seal of 2026-11-07 is the first 16 characters of a real library hash followed by a made-up tail (F4). And 12 actions have been stuck at `approved` since September (F10).

It also shows four things I did not have.

**Seal, attestation and flag are on auto.** The brief expected seal on queue. An attestation that riffle had replicated another citizen's result went out on 2026-11-12 (F43).

**The prompt is cut more than it needs to be, and the journal only sometimes says so (F37).** In the two cycles where your journal shows both halves of the prompt, there was room for 26,400 and 26,600 characters, and 17,200 and 23,100 were sent. So 9,200 and 3,500 characters of room stood empty while the desk, which holds 6,207 characters, was shown at 1,200.

**The daily memory pass dropped 39 memories in one night** (2026-11-08). Nothing limits how many it may drop, and it may drop ones you pinned or said yourself (F42).

**A send that gets no answer can never be finished or retried (F38).** Six rows on the box are in that state.

From reading the tests, the gap that matters most: **no recorded test checks that an action which reaches the square is queued when it is set to `queue`.** I changed that one line so that every such action went out unattended, and all 210 tests passed. 19 of the 41 protections I switched off are pinned by nothing (section 7).

Four things in my first report were wrong or incomplete, one of them a sentence inside a finding (F15). Section 6.

New counts: 4 Medium (F37, F38, F42, F43) and 5 Low (F39, F40, F41, F44, F45), on top of the first report's 7 High, 12 Medium and 17 Low. Nothing in either pass could by itself reset the host.

## 3. What the box output settles

**Installed files.** Every helper and unit matches the repo. `/etc/sudoers.d/riffle-build` differs, harmlessly: its size and date match commit `1edb310` (2026-08-28), every change since then is in a comment line, and the rule line is the same. Nothing told you it had fallen behind, which is F31. Three leftovers are inert: `riffle-model.removed` in `/etc/sudoers.d` (sudo skips a file name with a dot in it) and two `.bak-` unit files.

**Config.** As expected. There is no `porch` line under `caps`, so the code's default of 3 a day applies (`cycle.py:5537`).

**Autonomy.** On queue: post, listing_submission, sign, close_project, add_goal. The other 25 are on auto, including seal, attestation, flag, comment, porch, vote and tag. Your screenshots show the same. That answers a question my first report left open: seal is not on queue. The number under each control is how many times riffle has ever proposed that action: seal once (the invented one), flag never, attestation six times.

**Each finding the script was written to test:**

| Finding | What the box shows |
|---|---|
| F4 | Confirmed. Library #241 (`solve.py`, shelved 2026-11-06) has a sha256 beginning `78805fea5876ac16`. Action 3131, the seal sent twelve hours later, is those 16 characters followed by `d1234567890abcdef…`. |
| F10 | Confirmed. 12 rows left `approved`: 9 comments, 2 votes, 1 porch line, all from 2026-09-04 to 09-28. |
| F12 | No operator answers are stored yet, so that half is untested. The desk holds 6,207 characters in 5 drafts against a cap of 1,200. |
| F13 | Not seen: no "database is locked" in the journal, and none in three days of the dashboard's log. Those days held three passes, two at about 09:12 UTC (01:12 your time) and one at 15:27 UTC (07:27). |
| F5 | No hand-made `page` rows exist yet. |
| F15 | Row 1653 (2026-10-20) is a correction aimed at someone else, which the code has refused locally since. Rows 2835 and 2839 are the old `observation` default, fixed on 2026-11-03. Neither is the part of F15 that stands (section 6). |
| F8 | The script printed only the start of each response, so it cannot show whether attestations 3422 and 3427 were signed. The second script does. |

**How riffle spends its cycles.** From 2026-11-07 to the moment you ran the script there were 393 cycles. 97 of them (25%) ended with one of the program's checks refusing what riffle proposed, and 11 more failed in the doing. The largest groups of refusals:

- 18 for a hash that nothing riffle had been shown carries (`hash-unknown` 17, `hash-unresolvable` 1). These are hashes written into posts, comments and the like, not seals. I think they are F4's second half at work: riffle is shown 12 or 16 characters of a build's hash and has to write the rest. The second script tests that the way the first tested the seal.
- 14 `post-link-unused` (a post links an outside page and quotes nothing from a page riffle read) and 5 `post-needs-reference` (a reference was due and the post had none that checks out).
- 11 `numcheck-blocked`.
- 11 `listing-not-open` and 6 `payout-without-work`.
- 8 `page-refused`, for pages off the reading allowlist.

The 17 listing refusals need a look. The output does not say which listings they were about. It does show two near-identical drafts on the desk, `draft:listing13_post` and `draft:list13_post`, last written 20 minutes apart, and a post titled "Listing 13 Binding: …" that went out on 2026-11-12. Listing 13 is the donation request you set aside on 2026-11-04, and the code's comments say `listings.ignore` already hides it (`cycle.py:1147-1153`, `:1198-1199`). If that is still so in the box's config, riffle is circling a listing it can no longer see, working from its own drafts, and the refusal does not help it stop: it gives five possible reasons in one sentence (`cycle.py:3098-3101`), of which "set aside by your operator" is only the first. The second script prints the setting and which listing each refusal named.

**Three questions are waiting for you.** All three rows in `questions` are unanswered. Three is the limit (`state.py:482`, checked at `:503`), so riffle cannot ask a fourth, and no push is sent for a question (F29).

**Posts.** Of the last 15 proposed, 11 were blocked by a check. The other 4 were approved and sent, one a day from 11-09 to 11-12, all on one subject. Posts 3267 and 3347 share the first 60 characters of their title, which is all the script printed. In the cycle the near-duplicate check covers comments and porch lines only (`cycle.py:3392`). A post gets it only when you approve it, and then on the body, at 55% word overlap, not the title (`dash.py:821`, `cycle.py:88`). The second script measures those two bodies.

## 4. Status of every finding

"Stands" means nothing in the box output or the second pass changed it.

| ID | Sev | Status |
|---|---|---|
| F1 | High | Stands. Unattended on the box for comment, porch and attestation. |
| F2 | High | Stands. |
| F3 | High | Stands. `flag` and `attestation` are on auto, so a flag's reason and the figures in an attestation's evidence go out unchecked and unattended. |
| F4 | High | **Confirmed on the box.** |
| F5 | High | Stands. Not yet used on the box. |
| F6 | High | Stands. |
| F7 | High / Med | Stands. |
| F8 | Med | Stands. The code has known since U6 that such a send is unsigned: it is logged and reported in chat, and the suite tests that report. It matters more now; see section 9. |
| F9 | Med | Stands. |
| F10 | Med | **Confirmed on the box.** New detail: the comment each ghost reply was answering can never be answered or set aside (reproduced, `ghostinbox`). |
| F11 | Med | Stands. |
| F12 | Med | Stands. F37 is the wider form of it, and the fix I proposed was too narrow. |
| F13 | Med | Stands. Not seen on the box in the three days the script looked at. |
| F14 | Med | Stands. The suite's recorded output shows the way in for two of the routes: the memory pass's first call "sees board paraphrase: True", and reflection is given the front page for the newest cycle. |
| F15 | Med | **One sentence of it was wrong**, corrected in section 6. The core stands. |
| F16 | Med | Stands. Seen again by accident: 38 test memories I wrote in similar words were merged into one. |
| F17 | Med | Stands, still from knowledge. F41 and F45 add to it. |
| F18 | Med | Stands (shown on a model of the script only). |
| F19 | Med | Stands. The suite's recorded gate output gives the same numbers: 19,173 tokens of 24,576, so 1,403 spare after `max_tokens`. |
| F20 to F35 | Low | Stand. Additions: F26, the `notes` table has 490 rows, because keys carrying a day or a cycle id (`extra_cycles_…`, `reflect_fail_…`) are never deleted. F29, see the three questions above. F33 was seen again in a new reproduction. |
| F36 | Low | **My conclusion was incomplete.** F38 replaces it. |
| F37 | Med | New. Every block is cut to a fixed cap whether or not the prompt is over. |
| F38 | Med | New. A send with no answer is `unknown` for good, even one that never left. |
| F39 | Low | New. The memory search index is never rebuilt. |
| F40 | Low | New. The build's disk budget watches the whole disk. |
| F41 | Low | New. The "written by anyone" label is skipped for a URL with a port. |
| F42 | Med | New. The daily memory pass can drop what you pinned or said, without limit. |
| F43 | Med | New. An attestation that riffle replicated someone's work needs no replication. |
| F44 | Low | New. Two rules that exist only as comments. |
| F45 | Low | New. `reading-allowlist.md` and the reader disagree on 28 hosts. |

## 5. New findings in detail

### F37 (Medium). Every block is cut to a fixed cap whether or not the prompt is over, so room stands empty while riffle's own material is cut

`_fit_section` cuts each block to its own cap first, on every cycle (`cycle.py:4241-4244`). Only then does it compare the total with the room, and nothing gives room back afterwards. The board is fitted second and is given whatever riffle's own section did not use (`cycle.py:4183`). So the room the whole prompt leaves empty is the board's room minus what the board sent.

Your journal has two cycles with both lines:

| 2026-11-12 | wanted | room | sent | needed cutting | was cut | left empty |
|---|---|---|---|---|---|---|
| 21:18 UTC | 36,303 | 26,395 | 17,179 | 9,908 | 19,124 | 9,216 (35%) |
| 21:05 UTC | 42,770 | 26,581 | 23,099 | 16,189 | 19,671 | 3,482 (13%) |

A third line, at 20:45, shows the board alone leaving 3,606 of its 13,264 empty.

In the 21:18 cycle riffle's own section asked for 19,315 characters and was sent 10,037. Its room was 17,000, so 2,315 had to go. The caps took 9,278. About 5,000 of that was the desk: it held 6,207 characters in five drafts and its cap is 1,200 (`cycle.py:4111`). The 9,216 characters left empty that cycle are about 2,850 tokens.

For the board, the later steps stop within about 160 characters of the room (`cycle.py:4259-4260`). It was sent 3,500 to 9,200 under, so the caps did all of that cutting too.

Two more things follow from the same lines.

The journal line "prompt fitted … wanted X of Y, sent Z" is written only when a section wanted more than its room (`cycle.py:4297`). When it wanted less, the caps still cut and nothing is logged. A cycle can show riffle one fifth of its desk and leave no line saying so.

The suite's own reviewed output contains the same behaviour. `fit by importance` records "budget 40475: fit total 28781": the function was asked to remove 8,000 characters and removed 19,694.

Shown by `audit second pass fit`: with a desk like the box's, six project notes and one long thread, the prompt wanted 23,658 characters and had room for 29,127. All of it would have fitted. 14,864 was sent, 8,794 was cut, and neither section produced a journal line. None of the five drafts was shown whole, two of six notes were shown, and 7 of 40 replies. `fitquiet` shows the same with only the desk added.

The caps on riffle's own section are constant on purpose: a cut point that moves from cycle to cycle breaks the composer's cached opening, and the comments say so. That reason does not apply to the board, which the code already treats as new every cycle (`cycle.py:4252-4255`).

Fix, in three parts:

1. Board: after the caps, hand the unused room back, most important block first, until the room is full.
2. Own section: keep the caps constant but size them to the room. On the box that section had 3,600 to 7,000 characters to spare in every line shown, and the desk is the first claimant. The operator's answers need a listed budget (F12).
3. Log every cap cut, whether or not the section was over.

One thing to weigh first. A fuller prompt is more for the composer to read on every cycle. If you would rather have the speed, lower `max_prompt_chars` to what is really sent, so that the number means what it says. Either way the room and the caps should agree.

### F38 (Medium). A send with no answer is `unknown` for good, even one that never left the box

When a send gets no answer, the cycle sets the action to `unknown` (`cycle.py:3623-3632`). It then works out whether the request could have left the machine at all. If the error is a name-resolution failure, a refused connection or an unreachable network, the code knows it never left and does not count it against the day (`_NEVER_LEFT`, `cycle.py:3646`). The row stays `unknown` either way.

An `unknown` row is treated as sent by every duplicate check (`cycle.py:105`, `:137`, `:231`), by the inbox, which marks the comment answered (`inbox.py:64`), and by the payout check, which counts it as work submitted (`cycle.py:2586`). And nothing ever resolves one:

- riffle cannot retry it, because the duplicate checks refuse.
- You cannot dismiss it. The dashboard refuses on purpose (`dash.py:1434`), and tells you "if it is not there, approve it again".
- You cannot approve it again. `decide` only claims rows that are `queued` and answers "not queued" for anything else (`dash.py:680-684`).
- The card says "check the square before retrying" and offers no control to do so (`pages.py:1505`).

Four places write `unknown` (`cycle.py:737`, `:3624`, `dash.py:911`, `:976`) and none changes one to anything else. The box has six such rows, and six cycles since 2026-11-07 ended `unknown-outcome`.

For a request that timed out after leaving, refusing a blind resend is right. For one that never left, it means a reply riffle wrote is never sent, and the comment it answered is filed as answered. The suite records this as correct behaviour: `box audit send-dns` expects `unknown-outcome` with nothing counted.

Shown by `audit second pass neverleft`: the send fails at name resolution, the row is `unknown`, the day's count is 0, the same reply next cycle is refused as `already-replied`, and the inbox says `answered`.

Fix: when `_NEVER_LEFT` matches, record the row as `failed`, which every check already treats as not sent. For a true unknown, reconcile at the start of the next cycle: riffle's own recent activity from the registry, or the thread itself, says whether the comment exists. Mark it `executed` if it does and `failed` after a few minutes if it does not. Give the card two buttons, "it is there" and "it is not there". The same sweep can clear the `approved` ghosts of F10.

This replaces F36 in my first report. I wrote there that the short `_NEVER_LEFT` list "only costs a slot". I had looked at the cap and not at what the row does afterwards.

### F42 (Medium). The daily memory pass can drop what you pinned or said, any number at once

The pass shows the composer up to 40 short-term memories and applies whatever it returns under `drop` (`consolidate.py:338-342`). Promotions are capped at 3 a day (`:196`). Drops have no cap. On 2026-11-08 the box's pass reported "dropped 39 as wrong", and 3 more the next night.

The 40 are chosen with no regard to who wrote them or whether they are pinned (`consolidate.py:177-183`). Two kinds of memory are exposed that should not be:

- **Ones you pinned on the dashboard.** The pin route sets `pinned=1` and clears the expiry but leaves the memory in the short tier (`dash.py:1546-1548`), so it stays a candidate. The comment there says "Pinned means permanent". A memory created already pinned is safe, because `memory.remember` puts it in the long tier (`memory.py:151`). The exposure is the ordinary case: riffle wrote it, you pinned it.
- **Your own words.** Memories of kind `operator` start in the short tier like any other.

A dropped memory is marked expired and is no longer recalled. The pass's report to chat lists each drop as an id and the model's reason, not the text (`consolidate.py:410`), so 39 lines of "✗ dropped [812]: wrong" give you nothing to judge by.

Shown by `audit second pass memdrop`: 40 memories, one pinned through the real dashboard route, one an operator instruction. The composer stand-in asks to drop everything it is shown. All 40 are dropped, including both, and neither comes back on recall.

I cannot tell from the first script whether any of the 39 was pinned or yours. The second script prints the text and kind of each one.

Fix: leave pinned and operator memories out of the candidates, or refuse to drop them. Have the pin route move the memory to the long tier. Cap drops at a handful a day. Put the dropped text in the report.

### F43 (Medium). An attestation that riffle replicated someone's work needs no replication

Four of the registry's classes are statements about another citizen's work: `code-merged`, `replicated-total`, `replicated-population`, `docket-shipped`. The prompt glosses the two middle ones as "you replicated their result" (`cortex.py:168-169`). The checks an attestation gets are the class list, the figure check on `claim` (which riffle's own `sources` satisfies, F1), and the hash check on `claim` and `evidence`. Nothing asks whether riffle ran anything. `evidence` is up to ten free strings (`drives.py:242-243`).

On the box `attestation` is on auto. Action 3427, a `replicated-total` attestation about `no-scheduler`, was sent on 2026-11-12. If the setting was the same that day, it went out without you seeing it first. I cannot tell from here whether riffle had replicated anything. The second script prints that attestation's claim and evidence, whether a build ran in the day before it, whether the cycle sent it by itself, and whether it was signed.

This is by reading, plus that one row. The fix has a settings half and a code half. Settings: put `attestation` on queue until the code half exists. Note F8: approved from the dashboard it goes out unsigned. Code: for the two `replicated-` classes, require the evidence to name a library document that a build produced, and check it the way a seal's hash is checked.

### F39 (Low). The memory search index is never rebuilt

Two old faults left words in the search index after their memory was gone: `forget` passed the wrong text to the index, and the daily purge deleted rows without touching it (`memory.py:194-211`, `consolidate.py:498-500`). Both are fixed for new deletions. `rebuild_index` was written to repair stores already affected, and its docstring says it "should be run once" (`memory.py:210`). Nothing calls it: no tool, no deploy step, no dashboard route.

The box's index has 1,007 rows for 999 memories, so at least 8 index entries belong to memories that no longer exist. Words left behind by the old `forget` do not show in that count (I checked how the index counts), so the real number of stale entries may be higher.

The effect is small. Recall joins the index to the table (`memory.py:274-276`), so an orphan cannot come back by itself. The harm the docstring describes needs a new memory to take over a deleted one's row id, which only happens when the newest memory is the one deleted. What it costs for certain is search ranking worked out over entries that are not there.

Fix: run it once from `update.sh` behind a note key, or at the daily pass whenever the two counts differ.

### F40 (Low). The build's disk budget watches the whole disk

`riffle-build` stops a build that "wrote too much to disk". It decides this from the free space of the whole filesystem: `shutil.disk_usage(BUILD_ROOT).free` before the build, compared with the same reading while it runs and after (`bin/riffle-build:289-298`). It never measures the build's own directory. Anything else on that disk moves the reading.

So it fails in both directions. If something else frees space during a build, a flood is not seen. If something else writes more than the budget during a build, or the disk is simply below the 1 GiB floor, an innocent build is stopped, its directory is deleted, and riffle is told "the build wrote too much to disk". With the box's 2 GiB budget the first two need a large coincidence. The last does not: on a nearly full disk every build fails with a message that blames the build.

I found this because the suite's own flood test failed when I ran two copies of the suite at once.

Shown by `audit build disk masked` (a 120 MB flood against a 50 MB budget passes while 300 MB is freed elsewhere) and `falsealarm` (a build that writes nothing is stopped while 120 MB is written elsewhere).

Fix: measure the build's directory by walking it. It holds at most a few dozen files.

### F41 (Low). The "written by anyone" label is skipped for a URL with a port or a user name

`source_label` looks up the URL's `netloc` (`cycle.py:4601`). The reader checks the URL's `hostname` (`bin/riffle-reader:233`). They differ when the URL carries a port or a user name. `https://en.wikipedia.org:443/wiki/Water` is allowed by the reader and gets no label, in the library title, the tags or what riffle is shown. The same holds for arXiv and the other preprint hosts.

riffle has no reason to write such a URL. A stranger who wants riffle to read a wiki page without the warning does.

Shown by `audit second pass label`.

Fix: use `hostname` in `source_label`, and have the reader refuse a URL with a user name or a port other than 443.

### F44 (Low). Two rules that exist only as comments

`systemd/riffle-run-cycle.service` says its privilege directives are "byte-identical to the timer unit on purpose" and "If this block ever drifts from riffle-cycle.service, that bug comes back" (lines 3 and 15). They are identical today. No gate in `update.sh` compares them.

Gate PYWAIT checks that the cycle's time limit covers its worst path, and reads `TimeoutStartSec` from `riffle-cycle.service` only (`update.sh:613`). A forced run uses the other unit. That is the one that waits on the cycle lock, and nothing checks its limit.

Fix: one gate that compares the directive lines of the two units, and have PYWAIT read both.

### F45 (Low). `reading-allowlist.md` and the reader disagree

The document says "In use: `bin/riffle-reader` reads only these domains". I compared the two by program. The reader has 363 hosts. Of the document's 391, the reader refuses 26, among them `scipy.org`, `pandas.pydata.org`, `scikit-learn.org`, `datatracker.ietf.org`, `www.fda.gov`, `www.weather.gov`, `www.govinfo.gov`, `cve.mitre.org`, `zenodo.org`, `osf.io` and `archive.org`. Some of those look like deliberate removals that the document never recorded. Two hosts are in the reader and not in the document (`plants.usda.gov`, `www.merckvetmanual.com`). And 31 hosts are listed in the document with a path, such as `www.postgresql.org/docs` and `www.sec.gov/edgar`, where the reader allows the whole host. That last point is how several of the F17 cases come about.

riffle is shown the reader's own list, so it is not misled. You, or the next agent, would be.

## 6. What I got wrong in the first report

**F15, one sentence.** I wrote that `correction` is self-only and that the four corroboration classes refuse a subject equal to the issuer, and that "neither rule is in the gate or the prompt". For the first rule that is wrong on both counts. A correction aimed at someone else is refused locally at `cycle.py:2985-3007` (outcome `wrong-class`, one on the box since 11-07), and the prompt names which classes are about others and which are about riffle's own record (`cortex.py:167-172`). I had searched the gate in `drives.py` for the registry's wording and did not read the attestation path through the cycle. A row in your output that my account could not explain is what sent me back.

What stands in F15, rechecked against the registry's current code (`src/attestations.ts:205-208` and `:222-228`): `dispute` and `retract` need `target_attestation_id`, `dispute` also needs `withdraw_when`, riffle has neither field, so two of the seven classes can never be sent. The third-party classes are not checked against riffle's own handle (`:193-194`). "fetch guide" names a target that does not exist. Two things I missed: the local refusal for a mis-aimed correction tells riffle "Send it as cls=dispute" (`cycle.py:2999`), which is advice that can only earn a 400. And the prompt files `retract` under "about your OWN record only", where the registry wants the subject of the attestation being withdrawn (`src/attestations.ts:211`, `:216-219`).

**F36.** Covered under F38. I judged the "never left" list by its effect on the daily cap and did not follow the row.

**Coverage.** I listed `witness.sample.jsonl` as not read. There is no such file; the file is `testsrc/witness-2026-08-21.jsonl`. I also left four small files off the list entirely (`first-post.md`, `testdraft.md`, `postsrc/facts.json`, `testsrc/treasury.json`). They are numcheck's original demonstration data and are now read. The caveat about long lines cut by my reader came to one line, `dash.py:1117`, now read.

**F12's fix was too narrow.** I proposed giving the answers block its own budget and raising one cap. That would have fixed three blocks and left the same room empty (F37).

What these have in common: each time I checked a claim against the place I expected the code to be, and stopped there. The box output is what showed it. So this report was checked the other way round, starting from each sentence and reading the line it cites. That found more than a dozen things in my own draft before you saw them. The ones that mattered: a wrong line number, a rule I had placed in the README that is in the runner, two percentages measured against the wrong base, an explanation of F39's count that the index does not support, a check on attestation evidence I said did not exist, a time for the memory pass that held for three of five nights, a refusal count of 99 that is 97, a count of 35 that is 31, and a setting recommendation that blamed seals for refusals that were about posts.

## 7. The test suite

### 7.1 What no test would notice

I made one small change to riffle at a time, each one switching off a protection, and ran the recorded suite against the changed copy. If no test's output changes, nothing in the suite pins that protection. 41 changes, run as root on Python 3.12.

**Noticed (22).** The figure check; the invented-hash check; the seal-must-be-a-library-hash check; the reference rule and the reference checker; one reply per comment; one top-level comment a day; the post cooldown; the board-tag neutraliser; the message-break strip; the open-edit label; the one-site search rule; the witness alarm; counting an unanswered send; a statement and its opposite not merging; an ambiguous derivation in numcheck; a payout binding with no submission; the signer's unsafe library directory, its `allowed_rows` and its payout ceiling; the dashboard's Host check; and `queue` for a local action such as `close_project`, which one test notices (`box audit close-once`).

**Not noticed (19):**

| Switched off | What it means |
|---|---|
| An action that reaches the square is queued when set to `queue` (`cycle.py:3530`) | With it off, every post, comment, seal and attestation would go out unattended. All 210 tests still passed. Every test that proposes one first sets it to auto. |
| The signer compares the payout address | A binding to any address would be signed. |
| The reader's allowlist | Every host readable. No test runs `bin/riffle-reader` at all. |
| The reader's https-only rule | Same. |
| The dashboard's JSON-only POST rule | This is the cross-site protection. |
| The cycle lock | Two cycles could run at once. |
| The near-duplicate check | "You have said this" never fires. |
| The gate's `never` setting | A disabled action could be proposed. |
| The gate's unknown-field check | |
| The gate's rationale requirement | |
| The gate's daily cap (`caps_ok`) | The dashboard's cap on approval is tested. The gate's is not. |
| The dashboard's duplicate re-check on approval | |
| riffle barred from the signer's operator-only command | The sudoers rule is the first line of defence here; this is the second. |
| The build sandbox's `PrivateNetwork` | The build test looks at two of the twenty sandbox properties. |
| The build sandbox's `MemoryMax` | Same. |
| The stuck failsafe | |
| The limit on how far riffle may move a goal's weight | |
| numcheck: an integer must match exactly | The docstring's own example (894/100 rounding to 9) would pass again. |
| numcheck: small integers are claims in agent mode | |

Notes on method. Every "not noticed" above is a run in which all 210 tests passed. I ran the first round two suites at a time, which makes three tests fail for reasons of their own (7.2, items 2 and 3, and F40), so every result that differed only in those three was run again with the suite alone. Three of my first changes left an unused variable or import and were caught only by the lint test, and one returned the wrong type and crashed 17 tests; I redid all four in a clean form. One change turned out to alter nothing (`numcheck.py:322` cannot be reached in the case I meant), so it is not counted.

The first row is the one I would write a test for today. It is the setting everything else leans on.

### 7.2 Faults in the suite itself

1. **The recording machine's name is in the expected output.** The `host check` test prints `socket.gethostname()` and the expected file has `Host vm` (line 486). On any machine not called `vm` it differs. I confirmed it by running the test under the name `riffle`. My sandbox happens to be called `vm` as well, which is why I missed this the first time.

2. **One test sees the real riffle.** `running cycle seen` asks the dashboard's `cycle_running()`, which scans `/proc` for any `python3 -m agent.cycle` (`dash.py:41-62`). If riffle's real cycle is running while the suite runs on the box, the test's "after it exits" line reads True and it differs. Confirmed here with a stand-in process.

3. **Two fixed ports.** The deploy-gate test puts its stand-in composer on port 18099 and expects nothing to be listening on 18098. Two runs at once collide.

4. **The TLS fixture fails on Python 3.13.** Python 3.13 turns on strict X.509 checking by default. The test's hand-made CA has no key-usage extension, so the right certificate is refused ("CA cert does not include key usage extension"), and the wrong one is refused for that same reason instead of for the name mismatch the test is about. Both lines differ, so under 3.13 the suite is 208 of 210. Add `keyUsage=critical,keyCertSign,cRLSign` to the CA. This only bites when the box moves to 3.13, and it is the fixture, not riffle: real sites' certificates carry the extension.

5. **Each run leaves about 230 directories and 30 MB in `/tmp`.** The tests call `tempfile.mkdtemp()` and `mktemp -d`, and the runner deletes only its own scratch directory. The runner's header says the run deletes its "temporary copy, scratch directory and key" (`run_all.sh:22-24`), which is true as far as it goes. Setting `TMPDIR` inside the runner would fix it, and the normaliser's `/tmp/tmp…` pattern would need to follow.

6. **The witness test seeds its marks back to front.** `st.save_head("identity", 100, "aaa")` passes the position and the head the wrong way round: the signature is `save_head(chain, head, through_id)` (`state.py:388`). The recorded output shows it, `marks now [('identity', 'aaa'), ('treasury', 'ttt')]`, and was accepted as correct.

7. **Headers that no longer match what is recorded.** The inbox-order test's header says the inbox is acknowledged after the composer and not at all if the composer fails. The code acknowledges straight after storing, on purpose (`cycle.py:1026-1030`), and the recorded output shows `ack` before `COMPOSER` in both runs. The tag-injection test's header says 0 lookalikes are left; the recorded line says 2, because its pattern also counts the two real tags. The reflection test's title says it "is not given the front page"; the recorded output shows it given for the newest cycle. Three prompt tests still print "of 50000" when run on their own, for a ceiling that is now 62,000.

8. **As an ordinary user, 16 of 210 differ.** From the first report, re-run today with the same 16. So on the box, run as yourself, expect 17 (those and `host check`), 18 if a cycle is running, and 2 more on Python 3.13.

The first report's two points about the runner (`head -40`, and "SKIPPED" hiding a difference) stand.

## 8. Coverage, final

Read in full, first pass or this one: every file under `agent/`, including all of `pages.py`; `numcheck.py`, `keyutil.py`, `ed25519_pure.py`, `witness.py`, `join.py`, `payout_wallet.py`, `repo_setup.py`; `update.sh`; the three helpers, the three sudoers files and `payout.conf.example` in `bin/`; all nine files in `systemd/` with their comments; `config.example.yaml` with its comments; `proposal_schema.json`, all 31 branches; `README.md`, `SETUP.md`, `actions-inventory.md`, `reading-allowlist.md` (all 689 lines, and compared with the reader by program); `first-post.md`, `testdraft.md`, `postsrc/facts.json`, `testsrc/treasury.json`, `.gitignore`.

In `tests.zip`: all 102 test files, headers and code; the runner, the checker, the normaliser, the comparison script; the safety net and the other files in `lib/`; the four harnesses; the fixture; the README; all 210 entries of `list_of_tests.txt`; all 733 lines of `expected_output.txt`.

Checked by program, not read: `testsrc/witness-2026-08-21.jsonl`.

Small things found while reading that are not worth a number:

- `config.example.yaml`: a comment beginning "Twelve hours" describes a key that was removed (line 62). Three comments give the old 20,480 context (lines 38, 114, 271). One says the prompt goes as three user messages; it is four. `notify.enabled` ships `true` under a comment saying to leave it `false` until the keys are filled in.
- `systemd/llama-triage.service` says the composer keeps `--mlock`; the composer's own unit says it does not.
- `systemd/riffle-run-cycle.service` says in one comment that a requested cycle exits at once if one is running (lines 55-58), and in another that a forced run waits (lines 47-50). The second is what the code does.
- `policy.REACHES_THE_SQUARE` omits `knock`, which posts a presence mark to the registry, so the settings page does not mark it.
- `SETUP.md` stage 1 copies `*.service` and `*.timer`, so a fresh install following it never gets the two `.path` units, and `update.sh` only reports a unit that is not installed. Stage 2's "force one now" depends on one of them.
- The pre-commit scan that `repo_setup.py` installs lives in the box's checkout and runs only on a commit made there. A file uploaded through GitHub's site never passes it. The first scan it meets is `update.sh`'s, after it is already on GitHub, and F31 says what that scan cannot see.
- Two more entries in the ordering tables that can never match: `_OWN_ORDER` lists `THINGS YOU NOTED FROM`, which is a board block, and `_BOARD_ORDER` lists `THE NULLS IN WHAT`, which is one of riffle's own. The gate proposed under F12 would catch both.

## 9. What I would do, in order

**Settings, today, no code.**

1. `seal`: off auto. riffle cannot see a full hash (F4), so any seal it writes now can only be refused, and it has proposed one in its life. `never` costs nothing until F4 is fixed. `queue` also works, but a seal you approve goes out unsigned (F8).
2. `attestation` and `flag`: to queue. riffle has never proposed a flag and has proposed six attestations, so this will not slow it down. The cost is that an attestation you approve goes out unsigned until F8 is fixed. Signed and unseen, or seen and unsigned, is your call; I would take seen.
3. Answer or close the three open questions. riffle is at its limit.
4. Check that `listings.ignore` holds 13.

**Code, in the order I would take it.**

1. F1, F2, F3 together: one change to what the figure check is given.
2. F4: seal by library id, show full hashes, hash the source bytes only. This removes the reason riffle invents hashes. If the second script shows the 18 refused hashes came about the same way, it ends most of those refusals too.
3. F8, because the settings above lean on it. It needs your decision first: should an approved seal or attestation be sent by the next cycle, which can sign, instead of by the dashboard, which cannot?
4. F37 with F12: the prompt's room. Ship it alone and watch a day of cycles, since it changes what riffle sees every cycle.
5. F42: the memory pass. Small, and it protects what you tell riffle.
6. F38 with F10: one sweep at the start of a cycle that resolves `unknown` and `approved` rows, and a decision on the 12 ghost rows already there. Marking them `failed` frees whatever comments are still waiting behind them; the second script lists those. I can write that as a one-off if you want it.
7. F5, F6, F7.
8. F43's code half, F15's two classes and the two prompt lines, then the rest.

**Tests, alongside.** A test that an action which reaches the square is queued, and nothing sent, when it is on queue. A test that the signer refuses a payout preimage carrying another address. One test that runs the reader against a host that is not listed. One that posts a form-encoded body to the dashboard. Each is a few lines in the suite's existing style, and each covers something that today can be removed without any test noticing.

## 10. The second box script

`riffle-box-checks-2.sh` is read-only like the first. It answers the questions this pass raised:

    sudo bash riffle-box-checks-2.sh 2>&1 | tee box-checks-2.txt

- the machine's name and Python version (section 7.2), and whether the build root shares a disk with the database (F40)
- `listings.ignore`
- when seal, attestation and flag were set to auto, and by whom
- the three questions waiting for you
- the six `unknown` sends and their error text, which says whether they left the box (F38), and the comments stuck behind the ghost rows (F10)
- memories by tier, kind, pinned and expired; any pinned or operator memory that is expired; the text and kind of each memory the 11-08 pass dropped (F42); index rows with no memory behind them (F39)
- which listing each refusal since 11-07 named, and everything riffle did about listing 13 since 11-04
- the hashes refused since 11-07, and whether each begins like a real library hash (F4)
- the last attestations' class, subject, claim and evidence; whether the cycle sent 3427 by itself, whether it was signed, and whether a build ran before it (F43)
- seals, attestations, flags, submissions and signs per day
- posts 3267 and 3347 compared the way the dashboard compares them
- how much of its ceiling the prompt used over the last 100 cycles, and, for cycles where both halves were fitted, the cut that was needed against the cut that was made (F37)
- how long the memory pass ran on each of the last five nights (F13)
- what fills the `notes` table, and how often reflection failed in the last week (F26)

Every query was run against a scratch database built by riffle's own code, with rows shaped like the box's added, before I sent it. It opens the database read-only and contains no statement that writes.
