# riffle — audit brief

Written for a model asked to audit this codebase for errors. It describes
what riffle is, how it is laid out, which failures have actually happened,
and which classes of bug the existing checks do not catch.

Repo: `github.com/MasonVB/riffle`, branch `master`.
~12,900 lines of Python. No tests.

---

## 1. What riffle is

An autonomous agent that participates in an online forum ("the square",
`1f916.ai`) as a citizen. It wakes on a timer, reads the board, picks one
action, and takes it. It has its own signing key, a wallet address, a
sandbox for running Python, a document library, and a memory that persists
between cycles.

It runs unattended. The operator (Mason) reads a chat log and intervenes
occasionally. Most of what the code does is decide what riffle may do and
stop it doing things that are wrong, wasteful, or false.

**The hardware matters to the design.** An HP EliteDesk 800 G4 Mini, i5-8500T,
32GB RAM, **no GPU**. The model is Qwen3.6-35B-A3B at Q4_K_M, roughly 20.6 GiB,
served by `llama-server` on localhost. Generation runs at about 6 tokens/sec
and prompt processing at about 30 tokens/sec, so a cycle takes 6–12 minutes
and a build cycle can take two hours. The context window is **20,480 tokens**
and this is the binding constraint on almost every design decision.

### The cycle

One wake = one action. `agent/cycle.py:main()` does, in order:

1. Interval gate (default 15 min) — returns early if not due
2. Reap a stale cycle, or refuse to start beside a live one
3. Daily memory consolidation, if due
4. **Witness pass** — unconditional, writes "Witness pass:" to chat
5. Gather: inbox, front page, changes digest, listings, docket
6. Pick a drive (weighted random, or forced by an operator instruction)
7. Build the prompt from ~12 blocks, trimmed to fit the window
8. Call the composer with a GBNF grammar derived from `proposal_schema.json`
9. Parse the proposal, run the gates, either queue it or execute it
10. Reflect: write memories about what happened

### Drives

Weighted goals that select which actions are available: `witness`,
`understand`, `contribute`, `answer`, `deepen`, `earn`, `curate`, `greet`,
`make`, plus `operator` (chosen only by an explicit instruction).

### Actions

30 kinds. Registered in three places that **must stay in parity**:

- `agent/policy.py` → `ACTION_KINDS` (29, excludes `noop`)
- `proposal_schema.json` → `oneOf` branches (30, includes `noop`)
- `agent/drives.py` → `SCHEMA` (30, the shape each payload must have)

A mismatch means an action the model can emit but the system cannot run, or
vice versa. Verify this first.

---

## 2. Layout

```
agent/
  cycle.py        2948   the wake loop, prompt assembly, every gate, all
                         apply_* handlers. By far the largest and riskiest
                         file. main() is ~1700 lines and inline.
  pages.py        1393   HTML/CSS/JS for three pages, as Python strings
  dash.py         1210   HTTP handler, chat API, settings routes
  project.py       699   the project lifecycle: notes, readiness, cooldown
  cortex.py        661   system prompt (stable_prefix), the model call,
                         proposal parsing
  chat.py          607   operator chat worker, the composer lock
  memory.py        578   recall, reflect, forget, forget_like
  state.py         554   sqlite wrapper, actions, cycles, journal, messages
  telemetry.py     474   the 24h sampling log
  drives.py        332   payload shapes and the gate
  consolidate.py   307   the daily short→long memory pass
  web.py           267   HTTP client
  library.py       262   permanent document store on disk + sqlite index
  client.py        256   Reader/Writer against the registry API
  desk.py          209   12 working slots, evicted by sequence
  conduct.py       188   one prose document injected into every prompt
  notify.py        160   operator notifications
  policy.py        154   autonomy levels (auto | queue | off) per action
numcheck.py        514   figure provenance checker; refuses unbacked numbers
bin/riffle-sign           signs as a separate user; the key is not readable
                          by riffle
bin/riffle-build          runs Python in a sandbox as root via sudoers
bin/riffle-reader         fetches allowlisted URLs as a separate user
systemd/                  units for the cycle timer, dash, and two
                          llama-server instances (composer + triage)
update.sh                 pull + five gates + rollback
```

### Storage

One sqlite file, `/var/lib/riffle/state.sqlite`. Tables that matter:
`actions`, `cycles`, `journal`, `messages`, `memories`, `projects`,
`project_notes`, `thread_reads`, `library`, `desk`, `drives`, `notes`
(key/value), `board_cache`, `memories_fts`.

`notes` is a generic key/value store used for cursors, `last_build`,
`continuity`, `last_wake_at`.

---

## 3. Where bugs have actually come from

Eleven defects found and fixed in the last three weeks. **Every one passed
the deploy gates.** Each was confirmed by reproduction, so the table is
observation rather than inference — but the *pattern* drawn from it below is
a generalisation, and generalisations are what this audit exists to test.

| # | Defect | Why it got through |
|---|---|---|
| 1 | `hashlib` used in `dash.do_GET`, imported only inside a function 700 lines away | NameError only at request time |
| 2 | `self._update_card()` inside `_goals_routes(h)`, a module-level function | NameError only when that endpoint is hit |
| 3 | `lib_id` read 30 lines before assignment in `apply_build` | NameError only on a successful build |
| 4 | `project.cooling()` — function does not exist, wrapped in `hasattr` so it silently returned None | the guard hid the error |
| 5 | `project.in_cooldown()` returns `(bool, until, hours)`; used as `not _cool` | a non-empty tuple is always truthy, so the branch never fired |
| 6 | parent-id validator searched `\[(\d+)\]`; the stored format is `[c101424]` | matched nothing, so it refused **every** reply |
| 7 | unresolvable-hash check matched `[0-9a-f]{7,64}` | caught comment refs (`c100136`) and decimal expansions (`00131000000000000021`) |
| 8 | `ask_operator(..., cycle_id=cid)` where `cid` does not exist yet | the failsafe crashed the first time it fired, every 5 min for hours |
| 9 | `minLength`/`maxLength` on a schema string | llama.cpp could not compile the grammar; composer dead for 9 hours |
| 10 | `open_listings` treated a missing `status` as open | submitted to a listing withdrawn 19 days earlier |
| 11 | uptime card counted unclean boots over all of `wtmp` but displayed 40 | summary contradicted the table beneath it |

The generalisation drawn from this, which may be leading you astray: that
most bugs here are *code written against an assumed shape* — a function
name, a return type, a stored string format, a regex — that nobody verified
against the thing on the other side. If that holds, `hasattr(`, bare
`except`, and every `re.findall` / `re.match` are the places to look, each
checked against a real sample of what it parses.

Treat that as a hypothesis with eleven data points, not a map. It was formed
by the same person who wrote the eleven bugs, and it may simply describe the
kind of mistake that happens to get noticed. Bugs of a kind nobody here has
thought to look for would not appear in that table at all, and those are
worth more than another instance of a known pattern.

---

## 4. What the deploy gates do and do not cover

`update.sh` runs five gates and rolls back on any failure:

1. **parse** — `ast.parse` every `.py`
2. **import** — `importlib.import_module` every `agent.*`
3. **render** — builds a fake handler and calls `do_GET` on `/`, `/settings`,
   `/history`, checking status, size, and that no placeholder is left
4. **prompt fit** — system + user + front page against the context window,
   refusing a deploy that leaves less room than `max_tokens` needs
5. **grammar risk** — rejects schema constructs known to break llama.cpp's
   GBNF converter (`minLength`, `maxLength`, `patternProperties`, `allOf`,
   `not`, `if`)

**Not covered, and these are where to look:**

- Any code path not reached by `do_GET` on three URLs. That is most of
  `cycle.py`, including every `apply_*` handler and every gate.
- Runtime type errors. Nothing checks that a function's return value is used
  the way the function returns it.
- SQL against columns that do not exist. The schema is created across several
  modules and no gate cross-checks queries against it.
- Behaviour of the regexes, which have caused three separate production bugs.
- Anything concurrency-related. The dash, the chat worker, the cycle and two
  llama-servers all touch the same sqlite file.

There are **no unit tests at all**. `main()` has no callable seam — the entire
cycle is inline — which is why gate 3 can only exercise the web pages.

---

## 5. Deliberate decisions, and the reasoning behind them

These look wrong at first reading. Each was a deliberate choice, and the
reasoning is given so you can judge it rather than take it on trust. **Some
of this reasoning may be wrong**; where it is, that is a more valuable
finding than a typo.

- **`witness` always reads high** on the drive-usage chart. The witness pass
  runs every cycle before any drive is chosen. *Claimed rationale:* it is an
  obligation, not a choice, so it should not compete for drive weight.
  *Worth checking:* whether running it before the interval-gated section is
  correct, and whether its cost is accounted for anywhere.
- **`None` counts as open** in the listing filter; explicit end-markers
  (`withdrawn_at`, `closed_at`, …) are checked instead. *Claimed rationale:*
  the API may legitimately omit `status` on live rows, and excluding them
  would hide everything. *Worth checking:* whether that is actually true of
  this API, and whether the marker list is complete.
- **`noop` is refused** in exactly one state: project ready, posting open,
  over 72h old. *Claimed rationale:* riffle spent 179 hours declining to act
  on a finished project, and six prompt revisions did not change it. *Worth
  checking:* whether the state is narrow enough, and what happens if the
  model simply re-proposes a noop every cycle.
- **`stale_minutes` is 720** (12 hours), with a cycle predating the current
  boot reaped immediately regardless. *Claimed rationale:* build cycles
  genuinely take over two hours, and the boot check makes the long window
  safe. *Worth checking:* the boot-time calculation in `cycle.py`, which
  reads `/proc/uptime` and compares against an ISO timestamp.
- **The duplicate-content check uses 55% word overlap.** Tuned against real
  repeated comments. *Worth checking:* false-positive risk on short texts,
  where a handful of shared words crosses the threshold easily.
- **Comments are long** and name the specific production failure that
  motivated the code. They are intended as documentation. *Worth checking:*
  whether any of them now describe behaviour the code no longer has — a
  comment that has drifted from its code is worse than none.

## 6. Open problems, stated as evidence rather than conclusions

### The host restarts itself

**Observed:** the machine loses power and comes back on its own, historically
every 1–3 hours, now much less often. `last -x` reports the boots as
unclean. Nothing appears in `pstore`. No MCE, no machine check, no thermal
trip in `dmesg`. A temperature logger sampling every 2 seconds recorded cores
at 33–35 °C and load at 0.01 in the final samples before several restarts.
`memtest86+` ran nine passes clean. The BIOS event log holds fifteen
"Real-Time Clock Power Loss" entries, with timestamps that are mostly
garbage. The CMOS battery was replaced about a month ago. Uptime improved
markedly after physical work on the machine on Oct 3–4 (one boot of 133
hours followed), but nobody recorded exactly what was done.

**Inferred, and unproven:** that this is a hardware fault — power delivery
being the most-suspected candidate. The 65W adapter is the correct genuine
HP part and has not been swapped.

**Why you should not take that inference as given:** the diagnosis was
reached by eliminating software explanations, not by demonstrating a hardware
one, and the elimination was not exhaustive. Specifically, nobody has ruled
out: a driver fault (`e1000e`, `i915`, NVMe, or Tailscale's kernel module);
anything that could trigger a hard reset from userspace; a watchdog timer
configured somewhere and firing; or a systemd or BIOS power-management
setting. `riffle-cycle.service` runs with `TimeoutStartSec=2700`, the cycle
spawns helpers through sudo, and `riffle-build` runs arbitrary generated
Python as root in a sandbox — none of which has been examined with this
symptom in mind.

**If anything in this codebase could cause or contribute to a host reset,
that is the most valuable finding in the audit**, and it would overturn
several weeks of assumption.

### Cycles that produce nothing

**Observed:** over a representative 24 hours, 148 cycles: 58% productive,
26% `noop`, 16% blocked by an internal check. Almost every noop rationale
says some version of "posting is closed for N hours".

**Inferred:** that this is riffle valuing its one daily post above other
available actions, i.e. a design question rather than a defect. *Worth
checking:* whether anything in the prompt or the drive weighting actively
causes it, and whether the cooldown is being computed and presented
correctly.

### Structural

- **`main()` is ~1700 lines inline**, with no callable seam. This is why the
  deploy gates can only exercise the web pages. Not itself a bug; it is the
  reason most bugs here are found in production.
- **The prompt budget is permanently tight.** The system prompt is ~18,200
  chars of a 46,000 ceiling and blocks are trimmed on most cycles. *Worth
  checking:* that `_fit()` trims safely, that nothing load-bearing is
  silently dropped, and that the token estimate (chars ÷ 3.25) holds.

## 7. How to verify a finding

Nothing here has tests, so a claimed bug should come with a reproduction.
Useful patterns:

```python
# exercise a handler for real rather than importing it
class Fake(dash.Handler):
    command = "GET"
    def __init__(self, path): ...
    def send_response(self, c): self.code = c
# then: h.do_GET() and check h.code, the body, and the headers
```

```python
# check a cross-module call against the real signature
import inspect
inspect.signature(project.in_cooldown)   # -> (state)  returns a 3-tuple
```

```bash
# the schema, the policy list and the gate must agree
python3 -c "
import json; from agent import policy, drives
g={b['properties']['action']['const'] for b in json.load(open('proposal_schema.json'))['oneOf']}
print(len(set(policy.ACTION_KINDS)), len(g), len(set(drives.SCHEMA)))"
```

```bash
pip install pyflakes && python3 -m pyflakes agent/*.py *.py bin/riffle-*
```

`pyflakes` found four live `NameError`s that both deploy gates had passed.
Run it first.

---

## 8. What would be most valuable

In rough order:

1. **Any remaining undefined name, wrong attribute, or misused return value.**
   Seven of the eleven known defects were one of these three.
2. **Regexes checked against real data.** Three production bugs so far.
3. **SQL columns verified against the actual schema.** Never checked.
4. **Concurrency on the sqlite file.** Four processes, never examined.
5. **Whether any gate can be fooled** — a check that silently passes
   everything is worse than no check, and that has happened twice
   (#4 and #6).

Report findings with the file, the line, the trigger condition, and whether
it fails loudly or silently. Silent failures are the expensive ones here:
#6 refused every reply for a week and looked like the model making mistakes.

**Disagreeing with this brief is a valid finding.** It was written by the
author of most of the code and all eleven of the known defects, so its
framing, its list of what matters, and its account of what is deliberate are
all one person's view. Where the code contradicts something stated here,
the code is the evidence.
