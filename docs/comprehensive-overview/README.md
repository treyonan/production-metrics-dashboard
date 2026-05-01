# Comprehensive overview build

Single-file build script for the project's comprehensive overview Word
document. The doc is regenerated from this script rather than hand-
edited; if you find yourself editing the .docx directly, the next
regeneration will overwrite your changes.

## Files

- `build.js` &mdash; the docx-js script that produces the document.
- `package.json` &mdash; declares the `docx` npm dependency.
- `pics/` &mdash; reference screenshots embedded in the doc.
- `production-metrics-dashboard-overview.docx` &mdash; the output. Generated.
- `.gitignore` &mdash; keeps `node_modules/` out of the repo.

## Regenerate

From this directory:

```bash
npm install        # one-time, after a fresh checkout
node build.js
```

That writes `production-metrics-dashboard-overview.docx` in place.
Validate by opening it in Word; structural validation can also be
run via the project's docx skill.

## When to update

Edit the prose in `build.js` whenever a phase changes the
architecture story &mdash; new data source, new top-level page,
authentication lands, multi-worker caching swaps in, or the
production-report rollups migrate to direct Flow queries. Look for
the `DOCUMENT BODY` section in `build.js`; everything below that is
content, everything above is the docx-js scaffolding (helpers,
styles, page setup).

If a screenshot changes, replace the JPG in `pics/` keeping the same
filename and regenerate &mdash; the build picks up the new image
automatically.

## Why a build script instead of a hand-edited .docx

Document edits are diff-friendly when they live in source. A
hand-edited .docx makes review impossible (binary blob in the diff)
and creates drift between the doc and the repo state. The script is
also the one place that knows the section ordering, the heading
styles, and the figure layout, so successive regenerations stay
visually consistent.
