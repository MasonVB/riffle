# How to audit riffle: read this first

Every audit of riffle so far has found more bugs than the one before. This
page says why, from the records in this folder and the git history. It also
sets out how to run the next audit so that it finds what is there, not just
the next layer down. Read it before the brief.

Written 2026-11-23, at commit `75d8002`: 23,300 lines of Python and 346 recorded tests.

---

## 1. What the earlier rounds found, and where the bugs came from

| Round | Date, commit | Size | Looked at | Found |
|---|---|---|---|---|
| First outside audit | 2026-10-11, `7eec686` | 12.9k lines, no tests | Crashes, plumbing, security | About 50 findings (P, C, G, S, W…); the report itself is not in this folder, only its brief and `AUDIT-RESPONSE.md` |
| Verification | 2026-10-17, `b3b309b` | 13.6k | Whether the fixes worked | N1–N18, bugs *introduced by the fixes*; two "fixed" items unchanged; five not addressed; a deploy gap |
| Three internal reviews | 10-27, 11-04, 11-06 | growing | Reports not in this folder | Their fixes are in the code and the suite |
| Outside audit | 2026-11-10, `39a3a5e` | 18.5k, 210 tests | Whether each check proves what it exists to prove | F1–F36 |
| Second pass | 2026-11-14, same commit | same | Every remaining file, plus 41 mutations of the suite | F37–F45 |
| Communications audit | 2026-11-20 | 22k | What riffle actually said in public over four days | `AUDIT-COMMUNICATIONS-2026-11-20.md` |

**Where the 45 findings of 11-10 and 11-14 came from.** I dated the faulty line each one cites with `git blame` at the audited commit. Where a finding cites no line, I dated the code it is about.

| The bug was in | Findings | Share |
|---|---|---|
| Code that existed before the first audit, missed by every round since | 25 | 56% |
| Code written to fix an earlier finding | 10 | 22% |
| Code from a feature added between audits | 10 | 22% |

Two caveats on these numbers:
- Blame gives a line's last edit, so if anything it makes bugs look newer than they are.
- The split of the 20 newer ones into fix and feature is a judgement. They are, from fixes: F2, F3, F6, F10, F12, F20, F36, F37, F38, F44. From features: F5, F7, F14, F15, F27, F34, F40, F41, F43, F45.

High-severity findings lean newer: 4 of 7 were in code written after 10-17.

**The plainest evidence.** The second pass audited the same commit as 11-10 and found nine more bugs, with no code changed in between.

### Why each round found more

1. **Each round went one layer deeper.**
   - Round one found crashes.
   - The verification found broken fixes.
   - 11-10 said it plainly: "The mechanical layer is clean… What is left is in the checks themselves."
   - The second pass tested the tests.
   - The communications audit read riffle's output.
   
   Each audit stopped at the layer it was asked about, and the next one found the layer below it.
2. **Fixes made new bugs, mostly by changing a function and not its callers or its twin.**
   - The first response admitted 11 of its changes fixed bugs it had made itself.
   - The verification found 18 more.
   - One chain ran through every round: the `unknown` send status (C12) led to N12, then F10, F36 and F38.
   - The same thing happened after 11-14. Batch 9 fixed F26 as first written and missed what the second pass added. Batch 17 changed the number check's first pass but not its rewrite.
3. **The tests did not pin the protections.** The second pass switched off 41 protections one at a time, and 19 of those changes passed all 210 tests. Among them was "an action set to `queue` waits for the operator". The suite records output. A test that records what the code does will also record a bug.
4. **Behaviour only shows when the model runs.** The listing-65 fixation, citing private hashes, and 400 wrong memories are not visible in the code alone. Their causes were old: prompt lines from 09-01 and 09-08, and the reflection design from 08-25. They surfaced only when someone read riffle's transcript and memory store.
5. **Growth.** The code doubled between the first audit and now, and new features gave about a fifth of the findings.

---

## 2. How to find all of them

Do these in order. Each produces something to hand back, so whoever comes next can see what was covered.

### 2.1 Inventory the protections before reading anything

List every protection in the code:
- every refusal outcome: `grep -oh 'end_cycle(cid, "[a-z_-]*"' agent/*.py | sort -u`, plus the `_oc` outcomes from `agent/outgoing.py`;
- every check the dashboard re-runs at approval (`dash.Handler.decide`);
- every deploy gate (`update.sh`, gates PY through PYOUT);
- every rule in `drives.SCHEMA` and `policy`;
- the signer's checks (`bin/riffle-sign`) and the reader's rules (`bin/riffle-reader`).

For each one, name the test that would fail if it were switched off. A protection with no such test is a finding.

### 2.2 Run the mutation sweep over the whole inventory

Switch each protection off, one at a time, in a scratch copy, and run the suite. The 11-14 second pass did 41 of these; do all of them. Every unnoticed mutation needs a test before anything else is fixed. The tests README explains running and comparing:

```
unzip -q tests/tests.zip -d /tmp/rt
RIFFLE_REGISTRY_MESSAGES=<registry messages.ts> python3 /tmp/rt/tests/check_against_expected.py <tree>
```

Without `RIFFLE_REGISTRY_MESSAGES` the 13 signing tests skip. Run the suite as an ordinary user as well as root: five tests need root.

### 2.3 Read every line, and say what was read

Keep a coverage table: every tracked file, with read in full, skimmed or not opened, and its line count. "Not opened" should be empty, or each entry should be justified. Include the tests and the docs, because a test can enshrine a bug and a doc can contradict the code. The 11-10 audit said what it had not read, and the second pass found nine bugs there.

### 2.4 For every change since the last audit, check its callers and its twins

The most repeated failure in this history is a fix applied to one path and not its pair. Known pairs in riffle that must agree:

| One side | The other |
|---|---|
| The cycle's send checks | The dashboard's re-checks at approval |
| The number check's first pass | Its same-cycle rewrite |
| `memory.reflect` | `memory.extract` (chat) and `consolidate` (daily): three writers to one store |
| `witness.py` | `cycle.do_witness` |
| `drives.SCHEMA` | `proposal_schema.json` and `policy.ACTION_KINDS` |
| Code defaults | `config.example.yaml`, and the box's own `config.yaml` |
| `bin/riffle-reader` | `reading-allowlist.md` |
| Units and sudoers in the repo | What is installed on the box (update.sh does not install them) |
| Prompt text (`cortex.py`, `conduct.py`, the cycle's blocks) | What the code now enforces |

For each fix in `AUDIT-RESPONSE-2026-11-14.md`, grep for every caller of what changed and every other place that does the same thing.

### 2.5 Re-verify every earlier finding, including what later passes added

Do not trust a "fixed" in a response document. Check each finding against the code, as `AUDIT-RESPONSE-2026-11-14.md` §22 did. Read each finding as the latest report states it, not as first written: F26 was fixed as first written and missed its second-pass addition.

### 2.6 Cover every layer, every time

| Layer | What to look for | Where the evidence is |
|---|---|---|
| Mechanical | Undefined names, signatures, SQL against the schema | pyflakes, compile every statement |
| State | Every action status and every transition, including `unknown`, `sending`, `approved` | `state.py`, `dash.py`, the cycle |
| Checks | Can each check be passed without the thing it exists to establish? | Construct the input that does it |
| Prompt | Does every instruction to the model match what the code now does? Stale prompt text taught riffle to cite private hashes for two months | `cortex.py`, `conduct.py`, the cycle's blocks; the `system prompt contents` test |
| Behaviour | What riffle actually said, remembered and chose | The box (2.7) |
| Deploy | Is the box what the repo says? | Units, sudoers and config on the box |
| Operations | Time, memory, disk, timeouts | The figures report and telemetry |

### 2.7 Read riffle's output, not just its code

Ask the operator for these, all read-only:

- The transcript of what riffle proposed and did, with every refusal and rejection:
  `cd /opt/riffle && sudo -u riffle python3 -m agent.transcript --days 4 > ~/riffle-transcript.txt`
- The live memory store, one memory a line:
  ```
  cd /opt/riffle && sudo -u riffle python3 - > ~/riffle-memories.txt <<'EOF'
  import sqlite3
  d = sqlite3.connect("file:/var/lib/riffle/state.sqlite?mode=ro", uri=True)
  for r in d.execute("SELECT id, ts, kind, tier, pinned, use_count, last_used, source, text"
                     " FROM memories WHERE superseded_by IS NULL AND COALESCE(expired,0)=0 ORDER BY id"):
      print(" | ".join(str(x) for x in r[:-1]), "|", " ".join(str(r[-1]).split()))
  EOF
  ```
- The figures report and telemetry, from the dashboard.

Read them against the rules. Every class of behaviour fault found so far was invisible in the code alone.

### 2.8 Every finding comes with a reproduction, and its origin

For each finding, hand back:
- **A test that fails on the audited commit.** The tests README's "Adding a test" says how to write one.
- **Where the faulty line came from:** `git blame` date and commit, and whether it was original code, a fix (which finding), or a feature. Then the next analysis of "why do audits keep finding more" is a query, not an estimate.

### 2.9 Keep fixes and features apart

The worst rounds mixed the two. While a round's fixes are landing, add no features. Each fix comes with its test and with the twin-and-caller sweep from 2.4.

---

## 3. Known open points, as starting places

These are named in the response document but not fixed:
- **Answering as the wrong person, and misreporting a citizen's data.** Catching these needs reading comprehension; the checks in `agent/outgoing.py` match patterns.
- **Word-matching checks.** These match words, not meaning:
  - reflection's reason check (`memory.unfounded`);
  - consolidation's "a lesson stands on its sources";
  - the invented-instruction check.
- **`cycle.restless` sees one subject at a time.** It counts by project, listing or post, so a fixation spread across a theme is invisible to it.
- **Old long-term lessons have no recorded sources.** Those written before 2026-11-23 cannot be demoted when their notes are retired.
- **Margins:**
  - the worst cold composer call is about 3,140 s against a 3,600 s cap;
  - the system prompt is about 32,600 of a 120,000-character ceiling.
- **The composer.** A hung composer holds a call for up to an hour, and the reading speed behind each call's limit (15 tokens/s) rests on one day's measurements.

---

## 4. Reading order for this folder

1. This page.
2. `AUDIT-BRIEF III.md`: what riffle is, how it is laid out, what the checks cover, the operator's decisions, and what would be most valuable. State as of 2026-11-23 (23,300 lines, 346 tests). It replaces `AUDIT-BRIEF II.md` (2026-11-09), which is history.
3. `AUDIT-2026-11-10.md` and `AUDIT-2026-11-14-second-pass.md`: the last full code audit.
4. `AUDIT-RESPONSE-2026-11-14.md`: the status of every finding (§22) and every change since, batch by batch (§9–27).
5. `AUDIT-COMMUNICATIONS-2026-11-20.md`: the first audit of behaviour.
6. History: `AUDIT-BRIEF II.md` (2026-11-09), and `AUDIT-BRIEF.md`, `AUDIT-RESPONSE.md` and `riffle-audit-verification.md`, from the first round.

`AUDIT_FINDINGS.md` is not about riffle. It is an audit of a different project (United Connection Finder) and is here by mistake; ignore it.
