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
the feature sounded straightforward and that was the first semantic I
reached for. Trey came back with: use the mode instead (most-frequent,
placeholders excluded, tie-break to newest). We shipped twice.
**Why it happened**: I took "the last product" at face value without
asking which question the label was actually answering. "What's
running right now?" (latest) and "What does this conveyor typically
run?" (mode) are genuinely different analytic questions -- they only
coincide on a 1-report Today view. For any multi-report window, mode
is more informative about the conveyor, while latest is more
informative about the current state. I should have surfaced that
distinction up front.
**Rule**: When a feature involves summarizing a series of values into
one display, explicitly name the summarization strategy (latest,
mode, mean, median, max, ...) and ask which one fits. Especially
important for labels where the user will read ONE value -- they'll
assume it represents the whole window unless told otherwise. Three
specific things to check: (1) Which subset of values participates?
Placeholders, nulls, and "idle" sentinels often need to be excluded
from statistical summaries. (2) What happens on ties / empty input?
Tie-breaking rule should be stated, and empty-input fallback
(typically null / em-dash) should be explicit. (3) Does the strategy
coincide across all views (Today/Week/Month, or equivalent scope
differences)? If so, the label's semantic is stable; if not, flag it.
