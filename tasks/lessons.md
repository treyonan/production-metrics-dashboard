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

### "Latest value" vs "most representative value" -- 2026-04-23
**Mistake**: When Trey asked for a per-conveyor Produced_Item_Description
label on the bar chart, I implemented "latest value in window" because
the feature sounded straightforward and