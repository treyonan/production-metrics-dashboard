You're working on production-metrics-dashboard, a read-only FastAPI service that aggregates
data from SQL Server, external REST APIs, and an Ignition tag historian, and
serves it to a polling web dashboard (refresh cadence 1–5 minutes) used by
plant engineers, operators, and management.

Before doing anything else, orient yourself by reading these files in order:

1. `CLAUDE.md` (project root) — project context, tech stack, architecture,
   conventions. The tech stack is my recommendation but open to challenge
   if you see a materially better option.
2. `tasks/lessons.md` — corrections and patterns from prior sessions. Apply
   them.
3. `tasks/todo.md` — current plan state, if any.
4. `context/` — domain knowledge. At minimum skim `domain.md` (if present)
   before touching SCADA-specific logic. For any work involving the
   production report payload, read
   `context/sample-data/production-report/payload-schema.md`.

You should also know:

- `examples/` holds reference implementations from prior projects. Read for
  pattern guidance; do NOT modify them.
- My global CLAUDE.md defines workflow rules (plan mode default, verify
  before done, self-improvement loop, etc.). Those apply here on top of
  anything project-specific.
- Windows-only deployment. Docker on Windows.
- Read-only API — no endpoints should write back to SQL.

## Today's focus

 - "Set up the initial FastAPI skeleton and a working /api/health endpoint."
 - "Draft Pydantic models for the production report payload based on the
    schema doc, and write tests that validate against the example JSON."
 - "Design the SQL integration layer — connection pooling, query file
    loading, parameterization conventions."
 - "Review existing structure and propose the first spec to put in
    tasks/specs/."
]

## How to work

- Enter plan mode. Write the plan to `tasks/todo.md` before implementing.
- Check in with me on the plan before starting work.
- Track progress in `tasks/todo.md` as you go.
- If you hit ambiguity, ask rather than guess. The "Open Questions" section
  in the project CLAUDE.md lists things I've already flagged as undecided.
- After I correct anything, update `tasks/lessons.md` per the format in
  that file.
- Follow the "where new content goes" rules from project CLAUDE.md. Don't
  invent new top-level folders without asking.

Ready when you are — start by confirming you've read the orientation files
and summarize what you understand about the project in 3–5 bullets. Then
we'll talk through today's focus.
