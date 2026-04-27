-- Select interval-metric tag rows matching a filter combination.
-- Optional filters use the (? IS NULL OR col = ?) pattern so the SQL
-- shape stays fixed; the caller passes NULL for any filter they want
-- to skip. Each optional filter consumes TWO bound parameters.
--
-- Parameter order:
--   1. site_id            (required, str)
--   2. subject_type       (required, str)
--   3. department_id      (optional; pass NULL or value)
--   4. department_id      (same value as #3, repeated)
--   5. asset              (optional; pass NULL or value)
--   6. asset              (same value as #5, repeated)
--   7. metric_name        (optional; pass NULL or value)
--   8. metric_name        (same value as #7, repeated)
--   9. interval           (optional; pass NULL or value)
--  10. interval           (same value as #9, repeated)
--
-- Returns one row per matching tag. Soft-deleted rows (enabled = 0)
-- are excluded.
SELECT
    site_id,
    asset,
    metric_name,
    interval,
    history_url,
    department_id,
    subject_type,
    DTM
FROM [FLOW].[INTERVAL_METRIC_TAGS]
WHERE enabled = 1
  AND site_id      = ?
  AND subject_type = ?
  AND (? IS NULL OR department_id = ?)
  AND (? IS NULL OR asset         = ?)
  AND (? IS NULL OR metric_name   = ?)
  AND (? IS NULL OR interval      = ?)
ORDER BY asset, metric_name, interval;
