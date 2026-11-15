# United Connection Finder — Full Audit (Bugs · Functionality · Consolidation)

**Scope:** every file in the repo was read in full (`index.html` line by line, all 13 `api/*.js`, `app-bridge.js`, `awards.js`, both harnesses; `airports.js` shape-checked only, per the brief). **Cybersecurity is deliberately excluded** from this document — the entire §3 security review, plus every security-adjacent observation made along the way, has been packaged as instructions in `OPUS5_SECURITY_INSTRUCTIONS.md` for a later Opus pass.

Special weight was given, as requested, to the price/points API calls and calculations. That focus paid off: four of the five most serious findings live there (F1–F4, F6).

---

## 1. Confirmed bugs, prioritized

### CRITICAL

**F1 — "Refresh" is silently undone: the `force` flag never reaches the server, and the stale entry then resurrects itself.**
`index.html` sends it — `pushCacheEntries(pushedEntries, force)` → `cachePut(entries, !!force)` (app-bridge.js:235) — but `api/cache.js` never reads `body(req).force` (grep confirms zero occurrences). The POST path always applies `better()`, which prefers **wider area first**:

```js
if (prev && !better(e, prev)) continue;   // cache.js:70
```

A forced refresh fetches only the currently requested window/lead, so its entry is *narrower* than the stale wide one → `better()` returns false → the fresh data is never stored. Worse, the stale wide copy is still in `REMOTE_IDX`, and on the **next ordinary search** `ensureSharedEntries` (index.html:2675) sees `entryBetter(remoteStale, localFresh)` → true (same area-first rule) → pulls the stale entry down and `putAirportEntry` **overwrites the fresh local copy the user just paid for**. Net effect: the user spends real API units on ↻ Refresh, sees fresh schedules once, and the next search quietly serves the outdated data again labeled *"Loaded from saved data."* This defeats the feature's whole purpose and wastes paid quota. The comment `// share it; a forced refresh overrides a stale wider copy (H2)` (index.html:1246) describes behavior that does not exist — exactly the kind of stale invariant-comment the brief warned about. Notably, `apitest.mjs`'s "wider kept" test *enshrines* the blocking behavior.
**Fix:** honor `force` in `cache.js` (skip the `better()` check, or `DEL` first), and/or have the client mark that key as "do not re-pull this session" after a forced write. Add `force` propagation to the index metadata if partial-force semantics are wanted.

### HIGH

**F2 — API-unit accounting undercounts by the chunk factor; three different cost numbers are shown for one search.**
`smartSearch` counts one unit per *task*:

```js
// One issued findArrivals/searchHub call == one API unit (api/adb.js makes exactly one
// upstream call per request), so counting issued calls gives this search's true cost.
var apiCalls = 0;            // index.html:1088
```

The comment's premise is false. One `findArrivals`/`searchHub` invocation internally issues `ceil(span / 11.5h)` calls to `/api/adb` via `chunkWindow` (app-bridge.js:76–85), and each of those is one billed upstream request. Concretely: the **default arrival window (08:00–20:00) is exactly 12h → 2 chunks counted as 1**; a `searchHub` window is `depSpread + (hiLead−loLead) + 2h` local (app-bridge.js:160–171), which at the default 1–7h lead is depSpread+8h — routinely 2–3 chunks per hub, each counted as 1. So a default search over 30 hubs really costs ~60–90 units while `apiCalls` records ~31.

Three displays now disagree for the same search: the **estimate** (`estimateUnits`, index.html:3105) correctly counts chunks (`Math.ceil(... / chunkH)`) and says ~62; the **credit pill** uses real quota-header deltas server-side and shows the true ~62; the **history row and `meta.apiUnits`** record `apiCalls` ≈ 31. The `Nu` badge in History and the "0 (61)" replay figure are therefore systematically low, and the user sees the estimate "disagree" with history after every search.
**Fix:** have `findArrivals`/`searchHub` return the number of `postAdb` invocations they made (they already own the loop) and sum those into `apiCalls`; or count in a shared counter inside `postAdb`. (Retries: a 429-`rateLimited` retry re-enters `postAdb` — decide whether RapidAPI bills hard-rate-limit 429s and count accordingly; see the Suspicious list.)

**F3 — `mergeHist` lets a recorded cost be erased by a zero: the "0 (61)" promise breaks across devices.**

```js
if (win.units == null && lose.units != null) win.units = lose.units;   // index.html:2786
```

The inherit-guard only treats `null` as "no figure". But a device whose *first* exposure to a search is a cache-served replay writes `units: 0` (real value, not null): Device A pays 61 and records it; Device B, before/without pulling history, runs the same search, gets it free from the shared Redis cache, `saveHistItem(..., apiCalls=0)` finds no local prior → stores `units: 0` with a **newer ts**. On merge, B's copy wins by ts, `0 != null`, so the 61 is discarded — then `pushHist` propagates the loss to the server and back to Device A. This is precisely the cross-device loss §4 of the brief asked about, and it is reachable in the ordinary two-device flow the feature exists for.
**Fix:** treat `0` like `null` for inheritance (`if ((win.units == null || win.units === 0) && lose.units > 0) win.units = lose.units;`), or keep the max/first-positive. Side nit: `pullHist` only re-pushes when `merged.length !== res.items.length` — a merge that changed *content* but not length isn't shared back (index.html:2802).

**F4 — Cluster fare hydration prices every option against the representative's destination; wrong-route fares are shown with confidence in group-by-departing + multi-airport-city searches.**

```js
// One price lookup covers the whole cluster: every option shares the same hub and
// destination, only the flight differs.
function hydrateOptionPoints(rid, cl, byHub) {
  var rep = cl.rep, from = rep.hubIata, to = rep.destIata, ...   // index.html:2456
```

The brief asked to verify that claim in **both** grouping modes. It holds in group-by-hub (a cluster is one onward flight → one destination). It **fails** in group-by-departing with a multi-airport city (e.g. "London" → LHR,LGW,STN): the cluster key is the United leg only (`'L1|'+unitedNumber+'|'+unitedDepartLocal+'|'+hubIata`, index.html:2405), so one cluster's onward options fan out to *different* destination airports — yet all of them are `priceMatch`ed against `hub→rep.destIata`'s rows, and each option's ratio is then computed at index.html:2470 from `c.hubIata → c.destIata` distances but a **different route's cash fare**. An option to LGW gets an LHR fare presented as its estimate, chips and all. This is the "confidently wrong number" the whole experimental design says is worse than no number. (The single-row panel, `hydrateAwardPanel`, uses the row's own dest and is correct.)
**Fix:** inside `hydrateOptionPoints`, group `cl.rows` by `destIata` and issue one `getPrices` per distinct `(hub,dest)` (usually still 1); or reuse the per-option `dateOf` you already compute and key the fetch per option-dest.

### MEDIUM

**F5 — Every first expansion of a cluster fires the price lookup twice; on a cold cache that is two upstream Travelpayouts calls.**
`toggleDet` (index.html:1906–1915) sets `expandedRows[rid]=true`, calls `render()` — whose tail calls `hydrateOpenPanels()`, which calls `hydrateOptionPoints(rid,…)` and starts `getPrices` — and then, back in `toggleDet`, calls `hydrateOptionPoints(rid,…)` **again**. `PRICE_CACHE[k]` is only written when the async response lands, so the second call misses the session cache and issues a second `/api/price` POST. Server-side there is no request coalescing: if the first request is still fetching upstream, the second also misses Redis and also hits Travelpayouts. Confirmed by direct code order at lines 1909→1914→1915.
**Fix:** delete the explicit `hydrateOptionPoints` call in `toggleDet` (hydrateOpenPanels already covers it), and/or make `getPrices` store an in-flight promise/pending marker with queued callbacks.

**F6 — `api/price.js` never caches "route not found", so empty routes are refetched upstream on every expansion.**
On `json.success === false || !Array.isArray(json.data)` the handler returns `{ok:true, rows:[], empty:true}` **without** writing Redis (price.js:74–77); only the all-rows-filtered-out case reaches the `redis.set` at line 92. Sparse routes — exactly the standby-adjacent city pairs this app lives on — therefore cost one upstream call per user per session per expansion (×2 with F5). The route's own comment says the whole point of the shared cache is to avoid re-fetching.
**Fix:** cache the empty payload with the same (or a shorter) TTL.

**F7 — Coverage over-claim on a window-gap refetch when the hub cap bites (the one §4 invariant that can break).**
On a reused entry with a window gap, gap hubs are re-ranked and only the top `maxHubs` become `queried` (index.html:1136–1146). `finishSmart` then persists `win = union(entry.win, requested)` for `mergedHubs = entry.hubs ∪ queried` (index.html:1189–1207). If an **entry hub** has new arrivals in the gap window but ranks *below* the cap in the gap-only ranking (possible when `maxHubs` was lowered/raised between searches, or flight-count ranking shifts among equal-size airports), its gap-window flights are never `searchHub`'d — yet the stored entry claims the union window for it. The shared cache then asserts coverage it lacks; a later narrow into that slice reports "fully covered by saved data" and silently misses connections. The trigger is narrow (hubSize-first ranking usually re-selects the same big hubs), but this is the exact "entry that claims coverage it lacks" the brief and cache.js's own design forbid.
**Fix:** force-include `p.entry.hubs` in `queried` for gap fetches (exempt from the cap — they were already paid for), or shrink the persisted `win` to what entry hubs were actually fetched over.

**F8 — Two of the four sort modes leave representative/option order undefined in group-by-hub — the same tie class as the already-fixed `depart` bug.**
In group-by-hub a cluster fixes the onward flight and varies the United leg. `mode==='time'` sorts by **onward duration** (index.html:1519), which is constant within such a cluster → every comparison ties → representative and option order fall back to incidental array order. `mode==='hub'` (the "other airport A–Z" default) compares `unitedOriginIata` then `leg2DepartHubLocal` (index.html:1530–1533) — but `leg2DepartHubLocal` is constant within the cluster, so two United options from the *same origin* tie completely and order arbitrarily. The brief predicted exactly this ("check the other three modes for the same class of bug"). `depart` mode is correctly tie-broken in both groupings; group-by-origin `time`/`layover` can tie only when two onward flights share an exact minute (cosmetic).
**Fix:** append `depMs(a) − depMs(b)` as the final tie-break in the `time` and default branches.

**F9 — BA peak pricing is carried in the data and silently ignored in the math.**
`charts.ba_shorthaul` has `peakEcon: 10750` (awards.js:80) and the rebuild prompt documents `Optional peakEcon` — but `chartPoints` (index.html:1963) only ever reads `bands[i].econ`. Every BA/Iberia/Qatar quote is off-peak 10,000, understating peak-date cost by 750 pts and biasing ratios optimistic — a small but systematic accuracy error in the number the feature exists to get right, with no disclosure.
**Fix:** either implement a peak calendar (date → peak?) and use `peakEcon`, or drop the field and label the output "off-peak pricing" so the honesty contract holds.

**F10 — A rebuilt `awards.js` can pass validation and then silently break every points panel.**
`refreshAwardData` validates `['issuers','programs','charts','carrierAlliance','departureTax','carrierSurcharge','bonuses']` (index.html:2344) — **`codeshareHint` and `extraPartners` are missing from the list** even though the prompt requires them and the code dereferences them unguarded: `A.codeshareHint[raw]` (index.html:1937) and `A.extraPartners[p.id]` (index.html:1951) throw on `undefined`. Those throws happen inside `getPrices` callbacks running under the shim's success-handler try/catch, so they're swallowed to console and the panels just stick at "…" for the rest of the session with no message.
**Fix:** add both keys to the validation list, and belt-and-braces guard with `(A.codeshareHint||{})` / `(A.extraPartners||{})`. (Also worth validating `dataVersion` since `awardAge` displays it.)

**F11 — The Travelpayouts token is invisible and un-removable from the UI.**
The server fully supports state and deletion (`key.js` `kind:'tp'` DELETE; `tpSet` in responses), but: `me.js` never reports `tpSet`, so after a reload the Settings panel cannot show that a token exists; the bridge has no `clearTpToken`; and the panel has only a Save button. A user who wants to revoke the credential, or just confirm it's set, has no path short of curl. Given the app's per-user-credential ethos this is a real gap.
**Fix:** add `tpSet: !!(await redis.get(K.tpToken(email)))` to `me.js`, a `clearTpToken()` bridge method (`api('/api/key', {method:'DELETE', body: JSON.stringify({kind:'tp'})})` — note the bridge's DELETE helper must gain body support), and a "token set ✓ / Remove" state in `rowTp`.

### LOW

**F12 — Results-card markup: missing `</div>` puts `#results`, `#meta`, `#warnings` inside the flex `.resultsbar`.**
Verified by tag balance (index.html:755–765): `.sortcol` closes, then the three content divs, then a single `</div>` that closes `.resultsbar`. `.resultsbar { display:flex; flex-wrap:wrap; gap:10px }` so the table becomes a flex item — layout mostly survives *by accident* (the wide table wraps to its own row), but `meta` and `warnings` can sit side-by-side with a 10px gap on wide screens, and any future `.resultsbar` styling will hit the whole results area. One-line fix: close the bar after `.sortcol`.

**F13 — Dead code (the brief asked for confirmation, plus new finds).**
Confirmed dead with zero external callers: **`detailHtml`** (and with it flight time / aircraft-operator display — they now appear nowhere in the UI, as §6 suspected), its private helpers **`timeInline`** and **`durBetween`**; **`getWindow()`** (superseded by `getWindowRange`, zero callers); **`routeKey()`** (its logic is duplicated inline at index.html:1041/1231). Also effectively dead: the `est = 'Estimating fare…'` branch in `awardPanelHtml` (`priced` is never falsy on any call path), and this pair in `paintAwardStatus` which collapses to always-show:

```js
tools.style.display = stale ? 'block' : 'none';
if (!stale) tools.style.display = 'block';   // always allow a manual rebuild
```

Delete the first line and the comment confusion goes away. In `awards.js`, the `logo: 'chase-logo.png'` / `'capitalone-logo.png'` fields are never read (inline SVGs are used) and the files don't exist; the `bonuses` entry `{issuer:'capone', program:'eva', …}` references a program id that doesn't exist, so it can never apply — but it *does* count toward the lapsed-bonus staleness flag (both bonuses lapsed on 2026-07-31, so the panel currently shows "update recommended" partly on the strength of a bonus that never worked).

**F14 — Stray `download` file in the repo root.**
It's an older copy of `usage.js` (the pre-`lastPrev`, pre-zero-cost version). It isn't in `api/`, so it doesn't count against the function cap, but it *will* be deployed and publicly served as `/download` (source disclosure noted for the Opus pass) and it's pure clutter. Delete it; `UPLOAD.md` doesn't list it.

**F15 — `UPLOAD.md` is stale.**
It says "The 17 files", lists `api/logout.js` (merged away), and omits `api/price.js`, `awards.js`, and `README`-described reality. Anyone following it verbatim re-uploads a logout.js (13th function → build fails at the Hobby cap) and omits price.js. Rewrite to match the tree.

**F16 — README vs code: `/api/health` anonymity claim is false.**
README: "Anonymous callers get only a problem count, so the page cannot be used to scout a misconfiguration." Code: `health.js` has no session check at all — env presence booleans, detected variable *names*, `allowlistCount`, storage reachability and raw storage error strings go to anyone. This document records it as a **doc/code contradiction**; how bad the exposure is belongs to the Opus security pass (it's flagged there).

**F17 — Orbitz carrier filter silently drops for digit-bearing airline codes.**
`(String(num).replace(/\s/g,'').match(/^[A-Z]{2}/)||[''])[0]` (index.html:1852) fails on B6, F9, 9E, 3M, G4, 9K… (IATA codes are alphanumeric). The link then opens with the nonstop filter but *no* carrier filter, while `flightLink`'s tooltip still promises "…, JetBlue only". Fix the regex to `^[A-Z0-9]{2}` (optionally reject all-digit matches) and the tooltip becomes honest again. The rest of `orbitzUrl` checks out: TOD buckets 0/5/12/18 are total (no gap → the "unknown bucket voids the filters array" failure can only occur when `depLocal` doesn't parse, in which case the tod filter is correctly omitted), and the JSON goes through `encodeURIComponent` so it can't break the URL or the attribute.

**F18 — `api/config.js` deploy stamp resets on a long-lived deployment, and first-write races.**
The 90-day TTL is never refreshed on read (config.js:33–43), so a deployment that stays live past 90 days loses the key; the next request re-records `BOOTED_AT` of whatever instance answers → the "Version" stamp jumps to *now*, looking like a deploy that never happened — on the exact long-lived deployments the stamp is for. Two concurrent cold starts can also both read-miss and both write (last wins; earlier responses show a different stamp than later ones). Fix: `redis.set(key, BOOTED_AT, { nx: true, ex: … })` then `get` to converge the race, and refresh the TTL (`expire`) on read — or drop the TTL and accept the tiny key residue.

**F19 — `api/cache.js` index read: one corrupt row 500s the whole index.**
`JSON.parse(idx[k])` at cache.js:36 is unguarded inside the loop; a single malformed hash value (e.g. from a partial write) makes every cache GET throw. The error message won't match the storage-connection regex (good — it surfaces as itself), but the shared cache is dead until someone hand-deletes the row. Wrap the parse per-row and skip bad rows (optionally `hdel` them opportunistically like the stale path does).

**F20 — `usage.js` still contains the `Number(null) → 0` sibling the brief told us to hunt for — latent, but present.**
`const remaining = Number(b.remaining)` (usage.js:12): a body of `{"remaining": null}` yields `0`, which passes `isFinite`, is treated as a genuine reading, sets `lastRemaining = 0`, and books `used = previousRemaining` into the running average — the exact class of the fixed adb.js bug. The shipped client can't trigger it (`updateCredit` guards `remaining == null`, and `recordCachedUsage` omits the field so it arrives as `NaN`), so this is robustness, not a live fault — but the route is one stray client edit away from poisoning the average. Apply the `numOrNull` pattern here (and note `limit`/`prev` are already safe: `Number(null)=0` fails their `> 0` guards). `history.js`, `price.js`, `config.js` were checked for the same class and are clean (`history.num`, `price`'s `isFinite(r.price) && r.price > 0`, `config`'s `Number(seen) > 0`).

**F21 — Widening window *and* lead together double-fetches overlapping United windows.**
When both gaps exist, hubs present in both `entry.hubs` and the gap-`queried` list get two `searchHub` tasks — the entry copy over the lead gaps and the gap copy over the full union lead — whose derived United windows overlap heavily. Correctness is preserved (`dedupeConns` — and yes, the two `entryBetter`/`better` implementations were compared and **still agree**, area → conns → maxHubs, as §4 asked), but units are spent twice on the overlap. Low priority; the fix is fiddly (subtract already-covered United windows per hub).

**F22 — Group-by switch leaves orphaned expanded rows that still fire price lookups.**
`setGroupBy` re-renders but doesn't clear `expandedRows`; old rids keep their stale `ROW_CLUSTER` entries, so `hydrateOpenPanels` runs `hydrateOptionPoints` for rows that no longer exist in the DOM. The per-option `getElementById` guards prevent any crash, but the `getPrices` (→ possible `/api/price`) still fires for invisible rows. Clear `expandedRows` (or filter to rids present in the new DOM) on group switch.

**F23 — Legitimately-empty results never sync across devices.**
`remoteUsable` requires `r.conns > 0` (index.html:2640), and `savedDatesSet` mirrors it — so a searched-and-empty (dest,date) is shared to Redis but other devices refuse to reuse it and re-spend the full unit cost to rediscover "no flights". Local reuse *does* work (`entryReusable` doesn't check conns), which makes the inconsistency look unintentional. If deliberate (guarding against a bad zero), flag it in §10; otherwise accept `conns >= 0` remotely.

**F24 — Hub-add costs never reach history, and the pill's "(prev)" is cleared.**
`fetchHub`'s `updateCredit(res.quota.remaining, res.quota.limit)` passes no `prevUnits` → `st.lastPrev = null` (the "(61)" annotation vanishes on a hub add), and neither `RESULTS.meta.apiUnits` nor the history row's `units` grows — so a replay of "that search + the hub I added" under-budgets even beyond F2. Also `saveHistItem`'s refine path discards the widen's *new* units once a prior positive figure exists (`cost = prior`), so a 61-then-+5 search stays recorded as 61 rather than 66 — the stored "first-fetch cost" never covers the widened slice's first fetch.

**F25 — Cache pushed to the server on every search, even pure cache hits.**
`finishSmart` builds `pushedEntries` whenever `!failed && !skipped` — including the zero-fetch path where the persisted entry is byte-identical to what's stored. Each such search still costs a `cachePut` POST → per-entry `redis.get` + the full `hgetall` + eviction scan, then a `pullCacheIndex`. Harmless to correctness (`better()` refuses the write) but real Upstash command volume per free search. Cheap fix: skip the push when nothing was fetched and no entry changed.

**F26 — Transport-failure on identity looks like "signed out".**
`api()` never rejects (it resolves `{ok:false,…}`), so `getAccess` maps a network failure to `{signedIn:false}` and `checkAccess` shows the *sign-in* gate; the dedicated "Couldn't check access … Try reloading" gate is unreachable for the common failure it was written for. Detect `res.error` in `getAccess`/`checkAccess` and route to the error gate.

**F27 — Misleading tooltip when the fare is below the award's cash component.**
`bestAwardOption` only computes a ratio when `cashUSD > cash` — a defensible display choice (§7 asked whether it's right: showing nothing beats showing a negative), but the fallback span's tooltip says *"No fare estimate, so no value ratio"* even though a fare **is** shown two lines up. Change the copy for that case ("fare is below the award's cash cost — redeeming can't win here"), which is also more useful advice.

**F28 — Session-sticky price errors.**
`getPrices` caches failures (`{rows:[], error:'unavailable'}`) in `PRICE_CACHE` for the whole session — one transient blip and that route shows "No cached fare" until reload. Consider not caching error results, or retry-on-next-expand.

**F29 — Two `rel="icon"` links; ~90KB of duplicate/base64 image weight in `index.html`.**
Line 6 embeds a full data-URI favicon; line 509 links `/favicon.png` (which is also shipped, 90KB). The header logo is a second large base64 blob. The data-URI icon is pure duplication — delete it — and moving the logo to a file would cut `index.html` (272KB) roughly in half and let it cache. (Also consider re-encoding favicon.png; 90KB is enormous for a favicon.)

**F30 — `apitest.mjs`'s config check asserts nothing.**
`r = mkRes(); cfg({}, r); console.log('config ->', …)` — the async handler isn't awaited, so `r._json` is logged before it's set. The printed line is noise. (Full harness-coverage assessment in §5.)

---

### Verified-correct (brief items checked and found sound)

To honor "where a section is correct, say so": the local-time pseudo-UTC machinery and UTC matching never mix (`localParts/partsToPseudoMs/…` operate only on strings; matching uses `dep2Utc/arrUtc` epoch ms); `chunkWindow` handles `to<=from` (+1 min) and the last-partial chunk correctly, and boundary-minute duplicates are neutralized by `dedupeConns`/`mergeFlights` keys; the `minLead>maxLead` swap works; lead matching is inclusive with a documented ±1h DST pad; the shim's M2 contract holds (a throw in a success handler cannot fire the failure handler or stall the task counters), and the three new shim methods follow it; `readSession`'s length guard and cookie parsing are as described (deep review → Opus); `numOrNull` in adb.js does its job and the 429 exhausted-vs-paced split is sensible; the 9-column table balances in every state (header, group row `colspan=9`, detail row, blanked expanded cells); `timeCell`/`dayDiff` are correct across month/year boundaries and degrade to no superscript without `LAST.meta.date`; `versionStamp` renders midnight as `00` and returns '' (no throw) without Intl; `esc()` coverage over **API-derived** strings is complete as far as a full sweep of every `innerHTML`/attribute sink found (awards-derived `--awc`/color fields are the exception — Opus doc); `mergeFlights` dedup includes `destIata` (its comment is one field stale); the client/server `entryBetter`/`better` pair agree; slider narrowing is genuinely free and there is **no remaining timer/event path to `/api/adb`** — `scheduleFetch` is gone, `cancelFetchTimer` is the documented no-op, and every fetch routes through `run()`/`smartSearch` or the explicit `fetchHub`; the pending flag is recomputed from `beyondCoverage()` at every relevant edge (slider change, search finish, failure sets covered=∅ → pending) and cannot stick; `applyHist` restores window/maxHubs deterministically; the `history.js`/`key.js`/`me.js` routes match their contracts; every `onclick`/`onchange` handler referenced in markup or generated HTML resolves to a defined global (full cross-check done, including the settings panel and clustered rows); and all `localStorage`/`JSON.parse` on the client are guarded.

---

## 2. Suspicious but not certain

These need live probing or vendor documentation; each is queued in the Opus instructions where marked.

1. **Does a hard-rate-limit 429 consume a RapidAPI unit?** If yes, retried calls cost extra units that neither `apiCalls` (F2) nor the estimate counts; if no, header-delta accounting is already right. Affects how F2's fix should count retries. *(→ Opus live check.)*
2. **Travelpayouts `v2/prices/latest` semantics**: whether `beginning_of_period + period_type=month` filters by *depart* month as the code assumes, whether `flight_number` is populated often enough for the exact-flight rung to ever fire, and whether `one_way`/`show_to_affiliates` behave as assumed. The fallback ladder is correct code-wise; the top rung may be theoretical. *(→ Opus live check.)*
3. **Orbitz URL grammar**: `options=carrier:UA,cabinclass:,maxhops:1,nopenalty:N` — the empty `cabinclass:` token and the enum names are curated; if Expedia rejects any token the whole options/filters set may be ignored. Degradation for a missing TOD is verified safe; enum validity isn't verifiable offline. *(→ Opus live check.)*
4. **`safe()`'s `unauthoriz` classifier**: today nothing but the Upstash client throws "Unauthorized", so no live false positive was found; any future throw containing that substring would be misreported as "Storage is not connected". Same watch-item for `pipeline`. (The K.tpToken-style false positive the brief described is genuinely fixed by the new regex.)
5. **`depart`-sort fallback comparability**: rows lacking `unitedDepartUtc` are ordered by local-string-parsed-as-UTC; if a single group ever mixes null-UTC and real-UTC rows across time zones, their interleave is not strictly chronological. adb.js only nulls `depUtc` when the feed omits it — unknown frequency. Cosmetic if it occurs.
6. **Vercel double-`res.json`**: `safe()`'s handling of a handler that answers twice / throws-after-answer looks right against Node semantics, but real platform behavior should be confirmed once. *(→ Opus.)*
7. **Curated award data plausibility** (per §7's "flag anything stale or implausible"): `EI` (Aer Lingus) is listed under oneworld — it is not a member (it's Avios-bookable via IAG, which may be the intent, but the field is named *alliance*); `VL`→Star is presumably Lufthansa City Airlines (plausible, worth a comment); both transfer bonuses lapsed 2026-07-31 (data is 5+ weeks from its own 90-day line); `capsCash: 3.40` for BA RFS and the flat departureTax table are order-of-magnitude sane but should be spot-checked in the next rebuild. Not code bugs; the code's null-past-last-band honesty holds everywhere (`chartPoints` null is never coerced — every caller checks `pts == null` / `ratio != null`; verified).
8. **`suggestLocal` at 14-result cap with big-airport boost** can bury an exact small-airport city match under metros for 2-letter-ish queries; behavior looked reasonable in reading but deserves a few real queries.

---

## 3. Functionality & user-goal review (works, but fails the user)

The core loop — pick city, see hub options, expand, book — is genuinely well-designed: the pending-state slider model, shared cache, and honest "no ratio rather than a guess" stance are the right calls. Where it still fails the user:

1. **No Stop button.** A 30-hub search runs ~70–120s at 1.15s pacing. The only cancels are the logo (`goHome`) and Clear — both wipe the form. A "Stop (keep what's loaded)" affordance next to the progress bar would let a user bail after seeing enough hubs without losing inputs; the token machinery already supports it (`searchToken++` then `finishSmart`-style partial commit with `failed=true` semantics so nothing over-claims).
2. **Phase-1 progress is indeterminate even though the chunk count is known.** `faTasks.length` is computed before `runFA`; drive the fill bar through both phases (`fa+sh` over `faTasks+shTasks`, re-baselined when shTasks lands) so long searches don't open with a spinner of unknown length.
3. **The three-costs inconsistency (F2) is a UX wound, not just an accounting one** — users reconcile "estimate ~62" / pill "62" / history "31u" and conclude the app can't count. Worth stating in release notes when fixed.
4. **Cache-served searches give no re-verify nudge on old data.** "Loaded from saved data (saved 6 days ago)" is honest, but for a *standby* traveler day-of-travel, a one-tap "↻ verify today's schedule (~N units)" inline with that status would match the actual user moment better than the tucked-away Refresh button. (And Refresh must actually stick — F1.)
5. **US-hub filter meta line** correctly reports hidden counts and the empty-state message is right (verified against §8), but the **best-options box and hub counts** also correctly receive filtered rows — one gap: the *Hubs menu* still lists US hubs as checked with no cue that the display filter is hiding them; a small "(hidden by filter)" suffix would prevent "I checked it, where is it?" confusion.
6. **Experimental-mode discoverability:** single rows in stable mode are intentionally inert (verified: no expander, no onclick, `toggleDet` refuses), but nothing tells a stable-mode user that fares/points exist at all. One line in the empty detail column or the settings hint ("Experimental adds ▸ fare + points per row") would convert the feature's intended audience.
7. **TP token lifecycle** (F11) and the **"needs search results" rows**: the disabled state is genuinely inert (buttons get `disabled`, verified — not just greyed), good; but after results arrive the panel only re-enables if reopened or `paintSettings()` runs — it does run via `showResults`, verified. ✔
8. **History labels omit the arrival window**, so two saved searches differing only by window look identical in the menu (`MUC - 10/17/2026/1-7hr` twice is impossible — same key collapses — but a *window-only* change collapses into one row by design; the label could append `08–20` so the user knows which window a replay restores).
9. **`checkAccess` network-failure path** (F26) leaves a user on flaky Wi-Fi staring at a sign-in button that won't help.
10. **Award verdict trust:** with F4+F9 fixed, add the priced route to the est. line ("Est. fare $118 · BA on this date · LHR route") so multi-airport users can see *which* airport's fare backed the ratio — cheap transparency that would have surfaced F4 to users immediately.

---

## 4. Consolidation, function merges, bloat

### 4a. Server functions — you're at the 12/12 Hobby cap; here's how to get headroom

Merges are ordered by blast-radius (smallest first). Each frees one slot; doing the first two gets you to **10/12 with two free slots** and touches four bridge lines total.

1. **`logs.js` → `health.js`** (17 lines absorbed). `GET /api/health` keeps current behavior; `GET /api/health?logs=MINUTES` requires `requireUser` and returns the events array. Bridge: point the (currently direct-URL) log reading at the new param — nothing in the app UI calls `/api/logs`, so this is nearly free. Delete `logs.js`.
2. **`me.js` → `auth.js`** — session lifecycle and identity belong together (the file's own comment already argues this for logout). `GET /api/auth` = current `me` body; POST = sign-in; DELETE = sign-out. Bridge change: `getAccess` fetches `'/api/auth'`. Keep `me`'s no-`requireUser` semantics on the GET branch only. Delete `me.js`. *(Add `tpSet` here while you're in the file — F11.)*
3. **`usage.js` + `history.js` → `account.js`** if a third slot is ever needed: `GET` returns `{stats, items}` in one round-trip (the app currently calls both at startup — this merge also *saves a request per load*); `POST {kind:'usage'|'history', …}` dispatches. Four bridge methods repoint.
4. **`request-access.js` → `auth.js`** (`POST {action:'request'}`) is available as a fourth, but auth.js is the one file where added branching costs the most review-wise — hold it in reserve.

Also: delete the stray `download` (F14) — not a function, but it ships.

### 4b. Client consolidation / bloat

The big win is **F29**: removing the duplicate data-URI favicon and externalizing the logo cuts `index.html` by roughly half and makes both cacheable. Then, in rough value order: delete the dead set (`detailHtml`+`timeInline`+`durBetween`, `getWindow`, `routeKey`, the unreachable "Estimating fare…" branch, the `paintAwardStatus` always-block pair — F13); collapse the **two haversine implementations** (`haversineMi` and the inlined copy in `expandCityLocal`) into one; extract a `placeLabel(city, code)` helper for the `city !== code ? city+' ' : '' + '(code)'` pattern built five separate times (render, cluster rep, best-route ×2, hub menu); memoize `bestAwardOption` per `(carrier|from|to|cash|issuer)` within a paint — `awardPanelHtml` currently computes each result twice (rows + verdict) and option chips recompute per row; and in `_lib.js`, `logEvent`'s three sequential Redis round-trips (`lpush`,`ltrim`,`expire`) per event can become one pipelined call (Upstash supports pipelining) — at one log per adb call that's ~120 commands saved on a default search. The intentional client/server duplications (`expiryFloorIso`/`floorIso`, `entryBetter`/`better`, `esc` conventions) are currently in agreement (verified) and are fine to keep, but a one-line comment in each pointing at its twin would cheaply guard the next divergence. `price.js`'s `K.price ? … : …` and `K.tpToken ? … : …` stale-`_lib` fallbacks can go once deploy-whole-sets discipline holds — they mask exactly the partial-deploy failure the README warns about, which is arguably worse than failing loudly.

---

## 5. Test harnesses (per the brief: do they prove what they claim?)

**They predate every §6–§9 feature, and cover none of it — confirmed.** `apitest.mjs` exercises me/key/usage/history/cache/config, but: the `kind:'tp'` branch of key.js is untested; usage.js's new zero-cost path (`used:0`), `prev`/`lastPrev` and the reset branch are untested (only the plain decreasing-remaining path runs); history items carry no `units` so the field's round-trip is unproven; `cache` never tests `force` (and its "wider kept" case *is* F1's failure mode, asserted as success); `price.js`, `adb.js`, `auth.js`, `logs.js`, `health.js`, `request-access.js` aren't touched at all; and the config check is a no-op (F30). `devserver.mjs` is a solid manual harness for the core flow (its canned-AeroDataBox correctly exercises codeshare filtering, and its `Map`-based headers satisfy `rlHeader`), but it cannot exercise: 429/backoff, quota-exhaustion messaging, price.js (the fetch stub passes travelpayouts.com through to the real network → locally you can only ever see the `needsToken` path), the deploy stamp against Redis, or any awards/experimental behavior. Minimum worthwhile additions: a usage.js test for the `{used:0, prev:61}` path and the `remaining:null` guard (F20); a cache.js `force:true` test (it will fail today — good); a canned Travelpayouts stub in devserver; and `await`ing the config test.

---

## 6. Verdict

As written, the app's *flight-finding core* is correct: the time math, chunking, matching, dedup, slider economics, and cache-coverage bookkeeping all held up under line-level scrutiny, with exactly one narrow over-claim path (F7) and an agreeing pair of `better()` twins. The *money layer* is where it falls short of its own stated bar: the recorded per-search cost is wrong by design (F2), a paid Refresh is silently reverted (F1), the flagship "0 (61)" figure can be zero-clobbered across devices (F3), and the experimental fare/points panel can attach the wrong route's fare to an option with full confidence (F4) while quietly ignoring peak pricing it possesses (F9) — each one an instance of "confidently wrong number" or "wasted paid quota", the two failure classes the brief weights highest. All are cleanly fixable with small, local changes (none requires re-architecture), and after F1–F6 land the app would genuinely deliver what it promises. Ship those six before trusting any displayed cost or ratio; the rest can follow at leisure.
