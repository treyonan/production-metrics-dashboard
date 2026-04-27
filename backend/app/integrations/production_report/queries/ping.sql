-- Liveness probe for SqlProductionReportSource. Must return a single
-- row with the integer 1. Any other result or an exception is
-- reported as an unhealthy source in /api/health.
SELECT 1 AS alive;
