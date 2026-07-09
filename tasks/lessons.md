# Lessons

Patterns learned from user corrections in this project. Reviewed at session
start. Add a new entry every time the user corrects a mistake or points out
a pattern worth preserving.

## Format for each entry

```
### [Short title] — YYYY-MM-DD
**Mistake**: What I did wrong.
**Why it happened**: Root cause, not just the surface symptom.
**Rule**: Concrete check I can apply next time, phrased as a do/don't.
```

Keep entries concise — one short paragraph per field is enough. If a lesson
turns out to apply to every project (not just this one), promote it to the
global CLAUDE.md as a rule rather than leaving it here.

---

<!-- Entries below, newest first -->
### Chart-label CHART_LABEL overrides title only, not formula — 2026-06-08
**Mistake**: In `docs/adding-a-new-site.md` and the `labels.py` module
docstring I described the chart-label resolution as relabeling
"calcs lines like `Total = C1+C8-C7`," implying the whole equation
participates in the lookup. Trey corrected with a screenshot: each
chart panel has a bold **title** (e.g. `TOTAL TONS FED`) and a
separate **formula expression** rendered underneath (e.g. `C1+C8-C7`).
Only the title is resolved from `MES.RUN_REPORTS_CONFIG.CHART_LABEL`;
the formula always renders as the raw conveyor expression.
**Why it happened**: I read the code's resolver logic and inferred a
visual model from the column names + lookup-key shape rather than
opening the dashboard and checking what actually renders. Both the
labels.py docstring and the new-site checklist propagated that
incorrect framing.
**Rule**: When documenting user-facing rendering, ground the
description in what the page *actually* shows -- look at the chart
panel in the browser before writing about it. Resolver code and
DB-column names describe what's looked up, not how it appears.

### TIME FILTER default: probe /latest-date, not "today" — 2026-06-08
**Mistake**: When Trey asked me to default the dashboard's TIME
FILTER to "current day" on launch, I implemented "always today." He
reversed it because production reports don't land until late
afternoon -- an operator opening the dashboard at 8am would see
"Nothing reported for today" even when yesterday's complete data
is right there in SQL.
**Why it happened**: I took "current day" at face value without
walking through the daily shift cycle. Operators want "most recent
populated data," which is yesterday during the morning, today after
the shift wraps. "Today" only matches that intent for ~4 hours of
the day.
**Rule**: For any "default" tied to operational data freshness,
probe the data source for the latest-available value rather than
using wall-clock today. SCADA / shift / batch data lands on its
own schedule; the UI default has to align with that schedule, not
with the system clock. Probe-and-fallback is the canonical pattern:
try /latest-date, fall back to today if the probe returns null or
errors.

### Hostname letters must match site code letters — 2026-06-08
**Mistake**: When commissioning Ardmore, the original commented
sketch in `catalog.example.yaml` used `code: ARP`, but the real
plant hostname turned out to be `dbp-arq` (Q for Quarry, not P). I
committed it as `ARP` matching the sketch; Trey caught the mismatch
on review and asked for a global rename to `ARQ`.
**Why it happened**: Sketch-vs-reality drift. The example.yaml
sketch was a placeholder authored before the real hostname existed,
and I treated it as authoritative when the actual plant box's
hostname was the real source of truth.
**Rule**: When commissioning a new site, the **hostname** is the
canonical identifier (it's what the network team registers and
what Ignition's MQTT URLs already use). Derive `code` from the
hostname (`dbp-arq` -> `ARQ`), not the other way around. If a
committed sketch / example has a code that doesn't match the new
hostname, treat the example as wrong, not the hostname.

### Test invariants, not snapshots of operational config — 2026-06-08
**Mistake**: `test_real_catalog_conveyor_placement_is_per_department`
asserted the exact tuple `("C1", "C2", ..., "C8")` for BCQ
Secondary. When Trey added C10/C11 + a Wash_Plant department, that
test failed -- not because the schema or code regressed, but because
operational config changed. The test was holding catalog.yaml
hostage to its momentary state.
**Why it happened**: I wrote the assertion as "exact tuple" because
the existing test pattern used `==` against a literal. The test's
docstring claimed it was checking "per-site placement" (an
invariant) but the assertion checked the specific data (a snapshot).
**Rule**: Tests against config files / catalogs / live data sources
should assert *structural invariants*, not specific contents:
- "Every conveyor matches `/^C\d+$/`" — invariant
- "At least one department owns Conveyor" — invariant
- "Conveyors == [C1..C8]" — snapshot, will break on every catalog edit
If a test fails the moment someone makes a routine config change,
the test was wrong, not the change.

### Each Flow installation has its own bearer token — 2026-06-08
**Mistake**: When implementing the original Flow integration, I
modeled `FLOW_API_KEY` as a single env var serving every site.
When Ardmore's Flow instance came online, requests for site 100
got 401 because the dashboard was sending BCQ's bearer token to
Ardmore's Flow API.
**Why it happened**: Single-site assumption baked in early when
there was only BCQ. The auth surface wasn't reconsidered when
Ardmore (a separate, independently-administered Flow installation
with its own instance UUID and bearer) was added.
**Rule**: Multi-tenant external APIs almost never share auth. When
adding a second site to the dashboard, AUDIT every external API
client (Flow now, Timebase historian if it ever grows auth) to
confirm whether the credential is shared or per-installation. The
canonical pattern: per-site env vars (`PMD_FLOW_API_KEY_<id>`)
plus an optional default fallback for single-site deployments
and migration ergonomics.

### Verify the server is running your latest code — 2026-04-22
**Mistake**: Chased a "static mount isn't working" theory through three
rewrites of `main.py` while the user's browser was actually hitting a
stale uvicorn process from a previous run. Wasted turns re-diagnosing
route-order, `html=True` quirks, and middleware interactions before
finally seeing `Errno 10048` (port already in use) in the startup log.
**Why it happened**: I assumed a server restart meant the new code was
running, and I didn't embed a quick way to confirm which build of the
code was answering requests. The `INFO: Application startup complete.`
line from uvicorn can appear even when the *new* server failed to bind
and exited — it's the parent watcher printing, not proof the worker is
alive on the port.
**Rule**: When in-browser behavior doesn't match code on disk, *first*
confirm which process is handling requests — embed a build-tag string
in the app (returned by a `/__ping` or similar) and check it before
diagnosing anything else. On Windows specifically, check
`netstat -ano | findstr LISTENING | findstr :PORT` to see if a zombie
process is holding the port; uvicorn with `--reload` occasionally
orphans the child on Ctrl-C. When the user reports misbehavior, ask
for the full startup log (not just "it started"), because a silent
bind failure followed by shutdown is easy to miss at a glance.

### Edit tool truncates files on Windows Cowork mount — 2026-04-22
**Mistake**: Used `Edit` tool to modify several backend files in small
increments; the tool reported "file state is current" each time but on
disk the files were silently truncated mid-content, breaking imports
until I re-wrote them via bash heredoc.
**Why it happened**: A mismatch between the Edit tool's in-memory view
of the file and what actually lands on the Windows-mounted
filesystem. The tool's success message is not proof of a complete
write-to-disk.
**Rule**: On this project, prefer writing files via bash `cat > file
<<'EOF' ... EOF` (or full `Write` calls) rather than chains of small
`Edit` operations. If `Edit` is needed, verify the tail of the file
via `tail -3 <path>` through bash afterward. The file-state notices
at the top of tool responses reflect tool-cache state, not disk
state — they cannot be trusted as disk-write confirmation.
### Retry-after-fail must cover ALL the original script's edits — 2026-04-28
**Mistake**: A multi-edit Python script for the Trends restructure
asserted on its second anchor and aborted. I retried, but the retry
script only fixed the anchor that failed -- it didn't re-include
the FIRST edit (which was a `let _activeTrendsTab = "overview";`
declaration). The first script never wrote anything to disk because
all my scripts accumulate in memory and write at the end on full
success. So that declaration silently disappeared, the dashboard
threw a `ReferenceError: _activeTrendsTab is not defined` at
runtime, and I had to debug it after Trey reported the broken UI.
**Why it happened**: When a Python script fails partway through
multi-file edits, my in-memory-accumulate pattern means NONE of
that script's edits land. But I treated the retry as "fix the one
thing that failed" rather than "re-run the entire intended set of
changes." The retry script was scoped to whatever I noticed needed
fixing, not to everything the original script meant to do.
**Rule**: When a Python rewrite script fails on an `assert`, before
writing the retry: enumerate every edit the original script
intended to make. Verify each one against the file post-failure --
is it already in the file? Did it land? Anything missing goes into
the retry. The mental model: failed scripts are atomic-rollback by
design (good), but my retries are NOT automatic re-runs of the
original intent (bad). Carry the intent across the retry boundary.

### Run `node --check` after rewriting frontend JS — 2026-04-28
**Mistake**: A Python-script regex rewrite of `renderTrends` in
`frontend/app.js` replaced the function body but my replacement
string was missing one closing brace -- the close of the new
`_setActiveTrendsTab` helper that came right after. Brace balance
was off by one, the IIFE wrapper at the end of the file failed to
parse, and the entire script never executed. Dashboard rendered
with an empty topbar (site selector stuck, health pill stuck on
"checking...", no panels) until I diagnosed the parse error.
**Why it happened**: I treated the rewrite as a string replacement
and didn't syntax-check the JS afterward. The Python `py_compile`
I run on backend rewrites doesn't catch JS errors. Browser-side
parse errors silently break everything that depends on the script
including JS that loaded before the error -- there's no graceful
degradation.
**Rule**: After ANY change to `frontend/app.js` (or any JS file in
the project) made via bash + Python rewrite, run `node --check
<file>` as part of the same step. The Linux sandbox has node
installed at /usr/bin/node and the check is fast (< 1 second).
Brace balance via `python3 -c "src=open(...).read(); print(src.count('{{'), src.count('}}'))"` is a useful sanity
fallback when node isn't available, but `node --check` catches
more (mismatched parens, unterminated strings, etc.).

### Theme toggle / re-render needs all payload state, not just one — 2026-04-28
**Mistake**: Phase 14b extended `renderTrends(payload, circuitPayload)`
to take a second argument and added `_lastTrendsCircuitPayload` was
NOT cached on the module level. The theme toggle handler at the top
of `app.js` re-rendered using only `_lastTrendsPayload`, so circuit
subsections silently disappeared when the user flipped light/dark on
the Trends tab -- no JS error, panels just gone until the next data
refresh restored them.
**Why it happened**: I added a new payload to `refreshTrends` but
didn't audit every code path that calls `renderTrends`. The theme
toggle is a code path that triggers a re-render WITHOUT a network
fetch -- it depends on cached state, and any cached state has to
cover everything the render needs.
**Rule**: When extending a render function's signature with a new
payload, grep for ALL call sites of that function and verify each
one passes the new argument. If a call site uses cached module
state, the cache must hold the new payload too. Theme toggle, view
tab switching, and any other "re-render without fetch" handler are
the failure modes to watch for.

### Edit tool truncation, revisited again — 2026-04-28
**Mistake**: Same failure mode bit me twice in one Phase 14a session.
First time: chained Edits to `frontend/app.js` over the Total-column
removal/restore work silently truncated the file at line 1671 (35
lines lost from the tail, ending mid-string in a chart options block).
Second time: chained Edits to `backend/app/{services,schemas,api/routes}/production_report.py`
during Phase 14a additions truncated all three production files
mid-content. Recovered both by `git checkout HEAD -- <files>` and a
single Python-in-bash atomic rewrite using `str.replace` against
unique anchors.
**Why it happened**: Same root cause. I followed the "single Edit +
tail verify" carve-out from the prior lesson, but a sequence of
single-change Edits across the same file in the same session still
triggers the corruption. The carve-out is too generous.
**Rule (tightened)**: For ANY change to any file on this Windows mount,
use the bash + Python rewrite pattern instead of the `Edit` tool. A
single Python script that reads each file once, applies all
substitutions in memory, and writes back is reliably atomic and shows
a syntax-check pass at the end. The `Edit` tool's "file state is
current" reassurance is unreliable on this mount and should be
treated as advisory only. If you must use Edit, verify with `wc -l`
and a `tail` AFTER the call -- the file's tracked-context view
inside the harness can lie.

### Edit tool truncation, revisited — 2026-04-23
**Mistake**: Despite the prior lesson, I used a chain of small targeted
`Edit` calls to flip `[ ]` to `[x]` checkboxes in `tasks/todo.md` during
Phase 4. Each call reported success and "file state is current," but
the final file on disk ended with a half-word "Fake" where text had
been silently truncated. Phase 4 content and the Lessons/Deferred/Review
sections had been cut off entirely. Required a full heredoc-based
rewrite to restore.
**Why it happened**: I had scoped the prior lesson to "large rewrites"
and convinced myself that small, targeted, uniquely-matching Edits were
safe. They are not. The Edit tool corrupts files on this Windows mount
regardless of change size, and the corruption can happen several calls
in — not necessarily on the failing call itself.
**Rule**: For files on this project, do NOT use the `Edit` tool at all
when sequencing more than one change to a single file. Collect all the
edits and apply them in one `cat > file <<'EOF' ... EOF` rewrite via
bash. A single standalone `Edit` call with a `tail` verification is
still OK for a one-shot targeted change, but the moment you're about to
send a second `Edit` to the same file, stop and rewrite it via heredoc
instead. The in-memory tracked-state note is never proof the disk write
succeeded.


### Even bash+Python full-file rewrites truncate large files — 2026-06-08
**Mistake**: Building the Phase 31 run-report export, I rewrote
`frontend/app.js` (~3300 lines) via a `python3 - <<PY ... open(p,"w").write(s) ... PY`
bash heredoc. `node --check` passed immediately after. Many tool calls
later (all on OTHER files), a re-run of `node --check` showed app.js
truncated mid-word at the tail ("  docu"), braces/parens unbalanced.
Trey told me to stop using the tool that keeps truncating, since it's
only caught after the fact.
**Why it happened**: The prior lessons recommended the bash+Python
full-file rewrite as the SAFE alternative to the Edit tool. But that
pattern *also* truncates large files on this Windows mount -- the write
doesn't fully land, and an immediate `node --check` can pass against a
cached/in-flight view while the on-disk file is short. Deferring the
real verification to a later step meant the corruption surfaced long
after the write, far from its cause.
**Rule**: On this mount, NO full-file write method is trustworthy for
large existing files (Edit truncates; bash/Python `open("w")` rewrite
truncates). So:
1. Don't rewrite a large existing file wholesale. Make the smallest
   change that works; for big files prefer append (`>>`) which doesn't
   rewrite existing bytes, or split into the narrowest edit.
2. VERIFY EVERY WRITE IMMEDIATELY, in the same step as the write --
   `wc -l` + `tail -3` + `node --check`/`py_compile`. Never move on to
   another file before confirming the byte-level result of this one.
   The immediate post-write `node --check` is necessary but not
   sufficient; also check `wc -l`/`tail` since a cached pass can lie.
3. Commit (or snapshot) frequently so git reconstruction
   (`git show HEAD:path` + re-apply the small edit) is the cheap
   recovery path -- which is exactly how app.js was restored here.

### Mount truncation dropped the IIFE `();` -- node --check can't catch it — 2026-07-06
**Mistake**: After the %/decimal/title edits to `frontend/app.js`, the
Windows mount truncated the file's tail from `})();` to `})` (and dropped
the trailing newline). The container was rebuilt from that file; the whole
app.js is wrapped in an IIFE `(function(){...})()`, so losing the `()` left
a function that is DEFINED BUT NEVER CALLED. `bootstrap()` never ran ->
`/api/sites` never fetched -> empty site dropdown -> no SQL data anywhere.
Trey reported "recompiled container not loading from SQL; site dropdown
empty." I initially chased the backend (all clean) before diffing the
committed app.js against the last-good commit and seeing `-})();` / `+})`.
**Why it happened**: `node --check` PASSES on `(function(){...})` --
a parenthesized function expression is valid syntax; it just never
executes. So the usual syntax check gave a false all-clear. The
truncation nuked only the final 3 chars, which balance-checks and
`node --check` both miss.
**Rule**: After ANY edit to `frontend/app.js`, verify the FILE TAIL
explicitly, not just `node --check`: `tail -c 12 frontend/app.js` must end
with `})();` (+ newline). Add this to the standard post-write check for
app.js alongside `node --check` + brace balance. More generally: a green
`node --check` is necessary but NOT sufficient proof a JS file is intact --
confirm the expected ending bytes are present. Recovery: `git diff <last-good>`
on the file surfaces the `})();`->`})` corruption immediately.

### device_bash git leaves an un-removable .git/index.lock on this mount — 2026-07-09
**Mistake**: Ran a full-tree `git diff --stat` via device_bash during Phase 38
verification. Git tried to refresh the index (the repo's .gitattributes
normalizes CRLF->LF on many files, so a full-tree stat rewrites index
entries), created `.git/index.lock`, then failed to unlink it: this Cowork
device mount forbids unlink/rm ("Operation not permitted"). A stale
index.lock left behind would make Trey's next NATIVE (Windows) `git` refuse
with "Another git process seems to be running / remove .git/index.lock".
**Why it happened**: device_bash operates on the Windows folder through a
bridge mount that allows create/rename but NOT unlink. Git's normal
create-lock-then-unlink dance can't complete its cleanup. Targeted git reads
(`git status -s <file>`, `git diff <one-file>`) didn't trigger it; the
full-tree diff touching all the CRLF-normalized files did.
**Rule**: On this mount, prefer NARROW git commands via device_bash (scope to
specific paths) and avoid full-tree index-refreshing ops. If a git call warns
"unable to unlink .git/index.lock", clear it as the LAST action with
`mv .git/index.lock .git/<somename>` (rename works; rm/unlink doesn't) and
verify absence with `ls` (NOT another git call, which re-creates it). Leftover
renamed artifacts in .git/ are harmless (git only honors the exact name
`index.lock`) but can only be deleted from Trey's native environment.
