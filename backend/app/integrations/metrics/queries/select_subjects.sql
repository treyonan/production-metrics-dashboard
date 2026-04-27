-- Discovery query for /api/metrics/<subject_type>/subjects.
-- Returns one row per (asset, department_id, metric_name, interval)
-- with the most-recent DTM per group. The Python source layer groups
-- these by asset and aggregates metric_names + intervals + last_seen
-- into a single IntervalMetricSubject per asset.
--
-- Parameter order matches select_tags.sql for the leading three
-- params (site_id required, subject_type required, optional
-- department_id passed twice).
--
--   1. site_id        (required, str)
--   2. subject_type   (required, str)
--   3. department_id  (optional; pass NULL or value)
--   4. department_id  (same as #3, repeated)
--
-- Soft-deleted rows excluded.
SELECT
    asset,
    department_id,
    metric_name,
    interval,
    MAX(DTM) AS last_seen
FROM [FLOW].[INTERVAL_METRIC_TAGS]
WHERE enabled = 1
  AND site_id      = ?
  AND subject_type = ?
  AND (? IS NULL OR department_id = ?)
GROUP BY asset, department_id, metric_name, interval
ORDER BY asset, metric_name, interval;
