# coding: utf-8
"""
Upsert one row into [FLOW].[INTERVAL_METRIC_TAGS] from a Flow Software
'Measure Event Period Value Data' MQTT payload.

Project    : production-metrics-dashboard
Layer      : SCADA-side companion script (NOT part of the FastAPI)
Runtime    : Ignition Designer / Gateway, Jython 2.7
Database   : IA_ENTERPRISE (Ignition database connection name)

What this is
------------
Our enterprise FastAPI doesn't touch MQTT. The discovery + URL-storage
side of the interval-metrics architecture lives entirely in Ignition:
when Flow publishes a value-change payload to the enterprise MQTT broker
including the static history URL, an Ignition trigger calls this
function to MERGE the (site, asset, metric_name, interval) row into our
SQL tag table. The FastAPI then reads that table at request time to
discover which tags exist and where to fetch their time-series.

See `docs/data-flows.md` Domain 2 for the full architecture.

Where to put this in Ignition
-----------------------------
1. Open Ignition Designer for the gateway that subscribes to Flow's
   MQTT topics.
2. In the Project Library, create (or open) a script package, e.g.
   `IntervalMetrics`.
3. Paste the contents of this file into that package.
4. From whichever event handler picks up Flow's MQTT messages -- a tag
   change script on a Cirrus Link MQTT Engine tag, an MQTT message
   handler, or a transaction group -- call:
      IntervalMetrics.upsert_interval_metric_tag(
          payload=<deserialized payload dict>,
          site_id=<numeric site id>,
          department_id=<dept id, or None for site-level>,
          subject_type='conveyor',
          database='IA_ENTERPRISE',
      )

The payload is whatever Flow publishes; a sample is at
`context/sample-data/interval-metrics/mqtt-payload-example.json`.

Required SQL DDL
----------------
Reference DDL for the target table. Run this once on IA_ENTERPRISE
before wiring the trigger:

    -- Idempotent setup. Safe to run multiple times -- creates the
    -- FLOW schema if it doesn't already exist, then the table.

    -- CREATE SCHEMA must be alone in a batch in SQL Server; EXEC keeps
    -- the IF NOT EXISTS guard intact.
    IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = 'FLOW')
        EXEC('CREATE SCHEMA [FLOW]');
    GO

    IF OBJECT_ID('[FLOW].[INTERVAL_METRIC_TAGS]', 'U') IS NULL
    BEGIN
        CREATE TABLE [FLOW].[INTERVAL_METRIC_TAGS] (
            site_id        INT          NOT NULL,
            asset          VARCHAR(64)  NOT NULL,
            metric_name    VARCHAR(64)  NOT NULL,
            interval       VARCHAR(16)  NOT NULL,
            history_url    NVARCHAR(512) NOT NULL,
            department_id  INT          NULL,
            subject_type   VARCHAR(32)  NOT NULL DEFAULT 'conveyor',
            enabled        BIT          NOT NULL DEFAULT 1,
            DTM            DATETIME2    NOT NULL DEFAULT SYSUTCDATETIME(),
            -- Unique constraint (not PK) so department_id can be NULL
            -- for site-level metrics. SQL Server unique constraints
            -- allow a single NULL per uniqued-column combination, which
            -- is the right semantics here: at most one site-level row
            -- per (site, asset, metric, interval), AND distinct rows
            -- per non-NULL department_id (so the same physical asset
            -- can carry per-department metrics independently).
            CONSTRAINT UQ_INTERVAL_METRIC_TAGS
              UNIQUE (site_id, department_id, asset, metric_name, interval)
        );
    END;
    GO

    -- Migration from the original PK-only schema (run once, 2026-04-28):
    --   ALTER TABLE [FLOW].[INTERVAL_METRIC_TAGS]
    --     DROP CONSTRAINT PK_INTERVAL_METRIC_TAGS;
    --   ALTER TABLE [FLOW].[INTERVAL_METRIC_TAGS]
    --     ADD CONSTRAINT UQ_INTERVAL_METRIC_TAGS
    --       UNIQUE (site_id, department_id, asset, metric_name, interval);

Idempotency / soft-delete behavior
----------------------------------
* MERGE on the natural key
  (site_id, department_id, asset, metric_name, interval).
* department_id was added to the key on 2026-04-28 so the same physical
  asset (e.g. conveyor C4) can carry independent metric rows when it's
  shared across multiple workcenters. Each row keeps its own
  history_url because Flow publishes the metric per department.
* A new tag's first publish INSERTs with enabled=1.
* Subsequent publishes UPDATE history_url + subject_type + DTM. They
  DO NOT touch `department_id` (it's part of the identity now -- moving
  a tag between departments is a delete + insert, not an in-place
  update) and DO NOT touch `enabled` so a manual `enabled=0`
  soft-delete survives. Re-enable by flipping it back to 1 manually.
* DTM bumps on every publish, so it doubles as a "last seen" signal
  the API can surface as freshness ("3 conveyors silent for 6 hours").
"""

# Ignition globals that this script depends on:
#   system.db.runPrepUpdate
#   system.util.getLogger
# Both are available in Designer + Gateway scoped scripts.


# ---------------------------------------------------------------------
# Interval detection
# ---------------------------------------------------------------------
#
# `measure.intervalType` in the Flow payload describes the *source
# tag's* cadence, not the *published bucket regime* of the message
# we're holding. For a metric whose underlying tag is hourly but is
# SUM-aggregated over a shift event, `intervalType` is still
# "Hourly" -- writing that to our table would be wrong (the consumer
# would think it's getting hourly data and find shift-level
# aggregates instead).
#
# The truthful signal is the structural shape of the payload:
#   * `eventPeriod` present -> event-aggregated. We map to 'shiftly'.
#   * `timePeriod` present  -> calendar-aligned. We map to 'hourly'.
#
# Site policy (2026-04-25): the only calendar interval Flow publishes
# at this site is hourly; anything finer-grained or coarser is
# expressed as an event-aggregated metric instead. So `timePeriod`
# always means hourly. If that policy changes, look at
# values[0]['duration'] (ms) to disambiguate calendar intervals
# (3600000 = hourly, 60000 = every_minute, 86400000 = daily, etc.).


def _determine_interval(payload):
    """Resolve the published bucket regime from a Flow payload.

    Decision rule:
      1. payload['eventPeriod'] exists -> 'shiftly'.
      2. payload['timePeriod']  exists -> 'hourly'.
      3. neither                       -> ValueError.

    Raises:
        ValueError: if the payload has neither period type. The
            Ignition gateway log will surface the message.
    """
    if 'eventPeriod' in payload:
        return 'shiftly'
    if 'timePeriod' in payload:
        return 'hourly'
    raise ValueError(
        "Flow payload has neither 'eventPeriod' nor 'timePeriod' -- "
        "unknown profile shape."
    )


def upsert_interval_metric_tag(
    payload,
    site_id,
    department_id,
    asset=None,
    subject_type='conveyor',
    database='IA_ENTERPRISE',
):
    """
    Upsert one row into [FLOW].[INTERVAL_METRIC_TAGS]. Idempotent;
    safe to call on every Flow value-change message.

    Natural key is (site_id, department_id, asset, metric_name,
    interval). Calling this once with department_id=127 and again
    with department_id=130 for the same conveyor will produce TWO
    rows -- by design. Pass None for site-level metrics (one such
    row per site/asset/metric/interval combination is enforced by
    SQL Server's NULL semantics in unique constraints).

    Args:
        payload (dict): Deserialized Flow Software MQTT payload --
            either the 'Measure Event Period Value Data' shape
            (event-aggregated, e.g. shift) or the 'Measure Value
            Data' shape (calendar-aligned, e.g. hourly). The
            interval string written to the table is derived from
            the payload's structural shape; see _determine_interval
            and the module docstring for the rule. Required fields:
            measure.name, measure.measureDataApiEndpoint, and one of
            payload['eventPeriod'] or payload['timePeriod'] (with
            values[0].duration).
            See samples at
              context/sample-data/interval-metrics/mqtt-payload-example-shiftly.json
              context/sample-data/interval-metrics/mqtt-payload-example-hourly.json
        site_id (int): Numeric site identifier (e.g. 101, 102).
            Required -- the payload only carries the site *name*
            string in modelAttributes.Site (e.g. 'Big_Canyon'), and
            the API filters on the numeric id.
        department_id (int or None): Workcenter / department
            identifier (e.g. 127, 130). Part of the natural key
            since 2026-04-28: a given conveyor in two departments
            produces two distinct rows. Pass None for site-level
            tags that don't roll up to one specific workcenter
            (only one such row per site/asset/metric/interval).
        asset (str, optional): The asset identifier this metric
            belongs to -- e.g. 'C4' for a conveyor, 'Secondary'
            for a workcenter-level rollup, '57-1' for a sub-circuit
            line. Part of the natural key. If not supplied,
            falls back to modelAttributes.Conveyor_Number for
            backward compat with conveyor-only tag handlers; pass
            it explicitly for any non-conveyor subject type since
            those payloads don't carry Conveyor_Number.
        subject_type (str): One of 'conveyor', 'equipment',
            'workcenter', 'circuit', 'line', 'site'. Default
            'conveyor'. Used as a coarse classification on the
            tag row; the natural key does NOT include subject_type
            so changing it on a republish updates the existing
            row rather than creating a duplicate.
        database (str): Ignition database connection name. Default
            'IA_ENTERPRISE' to match the production-report database.

    Returns:
        int: Rows affected (1 on insert or update).

    Raises:
        ValueError: When the payload is missing a required field.
        Any exception raised by system.db.runPrepUpdate is logged
            and re-raised so the gateway log surfaces SQL failures.
    """
    logger = system.util.getLogger("IntervalMetrics.upsert")

    # ---- extract required fields from the payload ----
    measure = payload.get('measure') or {}
    model_attrs = payload.get('modelAttributes') or {}

    # ASSET RESOLUTION:
    # Caller-supplied `asset` wins. If omitted, fall back to
    # modelAttributes.Conveyor_Number for backward compatibility
    # with the original per-conveyor tag handlers. Non-conveyor
    # subject types (workcenter, circuit, line, equipment) DO NOT
    # carry a Conveyor_Number in modelAttributes, so the caller
    # must pass `asset` explicitly for those -- typically derived
    # from a different field of the payload (e.g. Area for
    # workcenter-level metrics, or a Description from
    # eventAttributes for circuit/line). The function is
    # deliberately payload-shape-agnostic at this layer; the
    # caller knows what its tag represents.
    if not asset:
        asset = model_attrs.get('Conveyor_Number')

    metric_name = measure.get('name')
    history_url = measure.get('measureDataApiEndpoint')

    missing = []
    if not asset:
        missing.append(
            "asset (caller-supplied or fallback "
            "modelAttributes.Conveyor_Number)"
        )
    if not metric_name:
        missing.append('measure.name')
    if not history_url:
        missing.append('measure.measureDataApiEndpoint')
    if missing:
        raise ValueError(
            "Flow payload missing required field(s): {}".format(
                ", ".join(missing)
            )
        )

    # Resolve the published bucket regime from the payload's structural
    # shape, NOT from measure.intervalType (which describes the source
    # tag's cadence, not the published aggregation -- see the module
    # docstring for the rationale). _determine_interval raises
    # ValueError if the shape is unknown; let it propagate so the
    # gateway log sees the cause.
    interval = _determine_interval(payload)

    # ---- MERGE the row ----
    # Natural key is (site_id, department_id, asset, metric_name, interval).
    # department_id is part of the key as of 2026-04-28 so the same
    # physical asset (e.g. conveyor C4) can have separate rows when it
    # belongs to multiple workcenters -- each row carries its own
    # history_url because Flow publishes a department-scoped metric.
    #
    # The ON clause handles NULL department_id specially: in SQL,
    # NULL = NULL evaluates to UNKNOWN (treated as false in WHERE/ON),
    # so a naive equality check would fail to match site-level rows
    # whose department_id is NULL. The OR-IS-NULL pair below is the
    # standard fix.
    #
    # `department_id` is NOT in the UPDATE SET -- it's part of the
    # identity now. Moving a tag between departments is an
    # insert+delete operation, not an in-place update.
    #
    # `enabled` deliberately omitted from UPDATE so a manual
    # soft-delete (enabled=0) survives subsequent publishes.
    sql = """
        MERGE [FLOW].[INTERVAL_METRIC_TAGS] AS target
        USING (SELECT
                ? AS site_id,
                ? AS department_id,
                ? AS asset,
                ? AS metric_name,
                ? AS interval) AS src
            ON target.site_id      = src.site_id
           AND target.asset        = src.asset
           AND target.metric_name  = src.metric_name
           AND target.interval     = src.interval
           AND (target.department_id = src.department_id
                OR (target.department_id IS NULL AND src.department_id IS NULL))
        WHEN MATCHED THEN UPDATE SET
            history_url   = ?,
            subject_type  = ?,
            DTM           = SYSUTCDATETIME()
        WHEN NOT MATCHED THEN INSERT
            (site_id, department_id, asset, metric_name, interval,
             history_url, subject_type, enabled, DTM)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1, SYSUTCDATETIME());
    """
    args = [
        # USING source row (5 args -- now includes department_id)
        site_id, department_id, asset, metric_name, interval,
        # WHEN MATCHED UPDATE values (2 args -- department_id removed)
        history_url, subject_type,
        # WHEN NOT MATCHED INSERT values (7 args)
        site_id, department_id, asset, metric_name, interval,
        history_url, subject_type,
    ]

    try:
        rows_affected = system.db.runPrepUpdate(sql, args, database)
    except Exception as exc:
        logger.error(
            "Failed to upsert interval-metric tag: "
            "site_id={} asset={} metric={} interval={} -- error: {}".format(
                site_id, asset, metric_name, interval, exc
            )
        )
        raise

    logger.debug(
        "Upserted interval-metric tag: site_id={} asset={} metric={} "
        "interval={} dept={} subject_type={} rows_affected={}".format(
            site_id, asset, metric_name, interval,
            department_id, subject_type, rows_affected
        )
    )
    return rows_affected


# ---------------------------------------------------------------------
# Example: tag change script on a Cirrus Link MQTT Engine tag whose
# value is the Flow payload as a JSON string. Adapt to whichever event
# source your gateway uses to receive Flow MQTT messages.
#
# Place this in the tag's "Value Changed" event:
#
#     if initialChange:
#         return
#     if not currentValue or not currentValue.value:
#         return
#     try:
#         payload = system.util.jsonDecode(currentValue.value)
#     except Exception as exc:
#         system.util.getLogger("IntervalMetrics").error(
#             "Could not decode Flow MQTT payload: " + str(exc)
#         )
#         return
#     # Site/department resolution lives in the SCADA layer; look up the
#     # numeric ids for this conveyor from your hierarchy lookup before
#     # calling.
#     site_id = lookup_site_id(payload['modelAttributes'].get('Site'))
#     department_id = lookup_department_id(
#         site_id,
#         payload['modelAttributes'].get('Conveyor_Number'),
#     )
#     IntervalMetrics.upsert_interval_metric_tag(
#         payload=payload,
#         site_id=site_id,
#         department_id=department_id,
#         asset=payload['modelAttributes'].get('Conveyor_Number'),
#         subject_type='conveyor',
#     )
#
# For non-conveyor subjects, derive `asset` from the payload field
# that uniquely identifies what the metric is FOR. Examples:
#
#     # Workcenter-level rollup -- use the Area as the asset name.
#     IntervalMetrics.upsert_interval_metric_tag(
#         payload=payload,
#         site_id=site_id,
#         department_id=department_id,
#         asset=payload['modelAttributes'].get('Area'),
#         subject_type='workcenter',
#     )
#
#     # Sub-circuit (line) -- use the Description from eventAttributes.
#     evt = (payload['values'] or [{}])[0].get('eventAttributes') or {}
#     IntervalMetrics.upsert_interval_metric_tag(
#         payload=payload,
#         site_id=site_id,
#         department_id=department_id,
#         asset=evt.get('Circuit_A_Line_A_Description'),
#         subject_type='line',
#     )
