"""
Timebase API Module

This module provides functions for retrieving and normalizing data from the
Timebase historian API. It handles API requests, sparse event-based data
normalization, and time-aligned dataset construction.

Public Functions
----------------
get_multiple_tag_data
    Retrieve tag data from Timebase API for specified time range
to_dataset
    Convert sparse API response into normalized, time-aligned dataset
build_timebase_url
    Construct properly formatted API URLs

Notes
-----
- Designed for Ignition/Jython 2.7 environment
- Uses @add_exception_context decorator for error handling
- Supports timezone-aware time conversions
- Implements forward-fill logic for sparse historian data
"""

from java.lang import String
from java.net import URLEncoder
from Utils.Errors import add_exception_context
from Utils import Time as TimeUtils
from Integrations.Timebase.Config import site_info as site_info

error_tag = '[Timebase]Timebase_Error'


# ============================================================================
# TIMEBASE DATA REQUEST
# ============================================================================

@add_exception_context()
def get_multiple_tag_data(site, dataset, tags, start_date, end_date, error_tag=error_tag):
    """
    Retrieve multiple tag values from Timebase historian API.

    Fetches historical tag data for specified tags and time range from
    the Timebase historian. Converts Ignition date objects to ISO format
    for API compatibility.

    Parameters
    ----------
    site : str
        Site name from Config.site_info (e.g., 'Roosevelt', 'Ardmore').
        Determines which Timebase server to query.
    dataset: str
        Dataset to use
    tags : str or list of str
        Tag name(s) to retrieve. Can be a single tag name string or
        a list of tag names.
    start_date : java.util.Date or str
        Start of time range. Accepts Ignition Date objects or date strings.
        Will be converted to ISO-8601 format for API.
    end_date : java.util.Date or str
        End of time range. Accepts Ignition Date objects or date strings.
        Will be converted to ISO-8601 format for API.
    error_tag : str, optional
        Tag path where errors will be written.
        Default: '[default]Timebase_Error'

    Returns
    -------
    dict or None
        JSON-decoded response from Timebase API containing tag data.
        Structure: {"tl": [...], "s": start_time, "e": end_time}
        Returns None if API request fails.

    Examples
    --------
    Retrieve single tag::

        >>> raw = get_multiple_tag_data(
        ...     site='Roosevelt',
        ...     dataset='IAP_BCQ_Controls',
        ...     tags='Production.Odometer',
        ...     start_date=start_dt,
        ...     end_date=end_dt
        ... )

    Retrieve multiple tags::

        >>> raw = get_multiple_tag_data(
        ...     site='Roosevelt',
        ...     dataset='IAP_BCQ_Controls',
        ...     tags=['Production.Odometer', 'Production.Product'],
        ...     start_date=start_dt,
        ...     end_date=end_dt
        ... )

    Notes
    -----
    - Site must exist in Config.site_info
    - API endpoint is http://{server}:4511/api/datasets/{dataset}/data
    - Errors are logged to error_tag and None is returned on failure
    - HTTP status codes other than 200 are treated as failures

    See Also
    --------
    to_dataset
        Convert raw API response to normalized dataset
    """
    server = site_info[site].get('server')    

    # Ensure tags is a list
    if isinstance(tags, basestring):
        tags = [tags]

    # Convert incoming Ignition Date objects to proper ISO format for API
    start_iso = TimeUtils.convert_time(start_date, "api")
    end_iso = TimeUtils.convert_time(end_date, "api")

    # Build API URL
    url = build_timebase_url(server, dataset, tags, start_iso, end_iso)

    # Make HTTP request
    client = system.net.httpClient()
    response = client.get(url)
    status = response.getStatusCode()

    if status != 200:
        # Handle error response
        try:
            body = String(response.getBody(), "UTF-8")
        except:
            body = "<unreadable body>"

        err_msg = "Timebase API request failed: status={0}, url={1}, body={2}".format(
            status, url, body
        )

        if error_tag:
            system.tag.writeBlocking([error_tag], [err_msg])

        return None

    # Parse successful response
    body = String(response.getBody(), "UTF-8")
    raw = system.util.jsonDecode(body)
    return raw


# ============================================================================
# CONVERT RAW API JSON → CLEAN NORMALIZED DATASET
# ============================================================================

@add_exception_context()
def to_dataset(raw, anchor_time=True, error_tag=error_tag):
    """
    Normalize sparse, event-based historian data into dense, time-aligned dataset.

    Converts the sparse event-based JSON response from Timebase API into a
    normalized Ignition dataset with forward-filled values and optional time
    anchoring at query boundaries.

    Parameters
    ----------
    raw : dict
        JSON-decoded response from Timebase API.
        Expected structure: {"tl": [...], "s": start_time, "e": end_time}
    anchor_time : bool, optional
        If True, inserts synthetic rows at query start and end times.
        This guarantees at least two rows in the dataset and provides
        consistent boundary values. Default: True
    error_tag : str, optional
        Tag path where errors will be written.
        Default: '[default]Timebase_Error'

    Returns
    -------
    com.inductiveautomation.ignition.common.Dataset
        Normalized dataset with schema: Timestamp | Tag1 | Tag2 | ...

        - Timestamp column contains local time strings
        - Tag columns contain forward-filled values
        - None values are normalized to "None" for strings or None for numbers

    Algorithm
    ---------
    1. Extract all timestamps and tag values from raw response
    2. Determine data type for each tag (numeric or string)
    3. Build complete ordered timeline of all events
    4. Forward-fill values across timeline to reconstruct state
    5. Emit rows only within requested time window
    6. Optionally anchor rows at start/end boundaries

    Examples
    --------
    Basic conversion::

        >>> raw = get_multiple_tag_data(site='Roosevelt', tags=['Odometer'], ...)
        >>> ds = to_dataset(raw)
        >>> print(ds.getColumnNames())
        ['Timestamp', 'Odometer']

    Without time anchoring::

        >>> ds = to_dataset(raw, anchor_time=False)
        >>> # Dataset will only contain actual event rows

    Notes
    -----
    Behavior Details:

    - Uses all timestamps to reconstruct state through forward-fill
    - Emits rows only inside the requested time window
    - Anchors at both time boundaries when anchor_time=True
    - Forward-fills values across timestamps to show state at each point
    - Type detection: numeric vs string based on parseability
    - Empty input returns empty dataset

    Time Anchoring:

    - START anchor: Synthetic row at query start time with current state
    - END anchor: Synthetic row at query end time with final state
    - Guarantees exactly 2 rows minimum when anchor_time=True
    - Useful for calculations that require start/end values

    None Handling:

    - None values normalized to "None" string for string-type tags
    - None values kept as None for numeric-type tags
    - Empty strings treated as "None"
    - Case-insensitive "none" strings normalized to "None"

    See Also
    --------
    get_multiple_tag_data
        Retrieve raw data from Timebase API
    """
    # ----------------------------------------------------------------------
    # 1) Validate input
    # ----------------------------------------------------------------------
    if raw is None:
        return system.dataset.toDataSet([], [])

    tag_blocks = raw.get("tl", [])
    if not tag_blocks:
        return system.dataset.toDataSet([], [])

    # ----------------------------------------------------------------------
    # 2) Build timestamp → {tag → value} updates
    # ----------------------------------------------------------------------
    def normalize_none(value):
        """Normalize None and empty values consistently."""
        if value is None:
            return "None"
        if isinstance(value, basestring):
            text = value.strip()
            if text == "":
                return "None"
            if text.lower() == "none":
                return "None"
        return value

    tag_names = []
    tag_set = set()
    tag_types = {}
    ts_updates = {}

    # Process each tag block from API response
    for block in tag_blocks:
        tagname = block.get("t", {}).get("n", "Unknown_Tag")
        if tagname not in tag_set:
            tag_names.append(tagname)
            tag_set.add(tagname)

        # Process data points for this tag
        for rec in block.get("d", []):
            ts = rec.get("t")
            if ts is None:
                continue

            val = normalize_none(rec.get("v", None))

            # Determine tag type (numeric vs string)
            if val is not None:
                is_numeric = isinstance(val, (int, long, float))

                if not is_numeric and hasattr(val, "doubleValue"):
                    is_numeric = True

                if not is_numeric and isinstance(val, basestring):
                    try:
                        float(val)
                        is_numeric = True
                    except:
                        pass

                if is_numeric:
                    if tag_types.get(tagname) != "string":
                        tag_types[tagname] = "number"
                else:
                    tag_types[tagname] = "string"

            # Record timestamp update
            if ts not in ts_updates:
                ts_updates[ts] = {}
            ts_updates[ts][tagname] = val

    # ----------------------------------------------------------------------
    # 3) Build full ordered timeline
    # ----------------------------------------------------------------------
    all_ts = sorted(ts_updates.keys())
    if not all_ts:
        return system.dataset.toDataSet([], [])

    start_str = raw.get("s")
    end_str = raw.get("e")

    # ----------------------------------------------------------------------
    # 4) Prepare output schema
    # ----------------------------------------------------------------------
    headers = ["Timestamp"] + tag_names

    # ----------------------------------------------------------------------
    # 5) Initialize rolling state
    # ----------------------------------------------------------------------
    current_state = {tag: None for tag in tag_names}
    rows = []
    start_anchor_emitted = False
    end_anchor_emitted = False

    def coerce(tag, val):
        """Coerce value to appropriate type for tag."""
        val = normalize_none(val)
        if val is None:
            if tag_types.get(tag) == "string":
                return "None"
            return None

        tag_type = tag_types.get(tag)
        if tag_type == "number":
            try:
                return float(val)
            except:
                return None
        if tag_type == "string":
            return str(val)
        return val

    # ----------------------------------------------------------------------
    # 6) Walk full timeline
    # ----------------------------------------------------------------------
    for ts in all_ts:
        # --------------------------------------------------------------
        # Anchor at START (synthetic) - BEFORE updating state
        # Only emit if this timestamp doesn't match start_str exactly
        # --------------------------------------------------------------
        if (
            anchor_time
            and start_str
            and not start_anchor_emitted
            and ts >= start_str
        ):
            # Only emit start anchor if current timestamp is NOT exactly at start
            # to avoid duplicate rows when first event matches query start time
            if ts != start_str:
                ts_local = TimeUtils.convert_time(start_str, "display")
                row = [ts_local]
                for tag in tag_names:
                    row.append(coerce(tag, current_state[tag]))
                rows.append(row)
            start_anchor_emitted = True

        # Update state for any tag change
        # IMPORTANT: Only update state for timestamps within or before the query window
        # Don't update state from timestamps after end_str to avoid polluting END anchor
        if end_str and ts > end_str:
            # Skip state update and row emission for timestamps after query end
            continue

        updates = ts_updates.get(ts)
        if updates:
            for tag, val in updates.items():
                current_state[tag] = val

        # --------------------------------------------------------------
        # Emit REAL rows inside window
        # --------------------------------------------------------------
        if start_str and ts < start_str:
            continue

        ts_local = TimeUtils.convert_time(ts, "display")
        row = [ts_local]
        for tag in tag_names:
            row.append(coerce(tag, current_state[tag]))
        rows.append(row)

    # ----------------------------------------------------------------------
    # 7) Ensure START anchor exists (edge case: no ts >= start_str)
    # ----------------------------------------------------------------------
    if anchor_time and start_str and not start_anchor_emitted:
        ts_local = TimeUtils.convert_time(start_str, "display")
        row = [ts_local]
        for tag in tag_names:
            row.append(coerce(tag, current_state[tag]))
        rows.insert(0, row)  # ensure it is the first row
        start_anchor_emitted = True

    # ----------------------------------------------------------------------
    # 8) Anchor at END (synthetic)
    # Only emit if last real row doesn't already match end_str
    # ----------------------------------------------------------------------
    if anchor_time and end_str:
        # Check if last row already has the end timestamp
        emit_end_anchor = True
        if rows:
            last_row_ts_str = rows[-1][0]  # First column is timestamp
            end_str_local = TimeUtils.convert_time(end_str, "display")
            if last_row_ts_str == end_str_local:
                emit_end_anchor = False

        if emit_end_anchor:
            ts_local = TimeUtils.convert_time(end_str, "display")
            row = [ts_local]
            for tag in tag_names:
                row.append(coerce(tag, current_state[tag]))
            rows.append(row)

    # ----------------------------------------------------------------------
    # 9) Return dataset
    # ----------------------------------------------------------------------
    return system.dataset.toDataSet(headers, rows)


# ============================================================================
# URL BUILDER
# ============================================================================

def build_timebase_url(server, dataset, tags, start_iso, end_iso, error_tag=error_tag):
    """
    Construct Timebase API URL with proper encoding.

    Builds a properly formatted and URL-encoded request URL for the
    Timebase historian API.

    Parameters
    ----------
    server : str
        Server hostname or IP address
    dataset : str
        Dataset prefix/name for the site
    tags : list of str
        List of tag names to retrieve
    start_iso : str
        Start time in ISO-8601 format
    end_iso : str
        End time in ISO-8601 format
    error_tag : str, optional
        Error tag (unused, for compatibility). Default: error_tag

    Returns
    -------
    str
        Fully constructed API URL with encoded parameters

    Examples
    --------
    >>> url = build_timebase_url(
    ...     server='10.49.135.12',
    ...     dataset='RVQ_default',
    ...     tags=['Production.Odometer', 'Production.Product'],
    ...     start_iso='2024-01-01T08:00:00-06:00',
    ...     end_iso='2024-01-01T16:00:00-06:00'
    ... )

    Notes
    -----
    - URL format: http://{server}:4511/api/datasets/{dataset}/data
    - Query parameters: tagname, start, end
    - All tag names are URL-encoded
    - Port 4511 is the standard Timebase API port
    """
    base = "http://{server}:4511/api/datasets/{dataset}/data?".format(
        server=server, dataset=dataset
    )

    query_parts = ["tagname=" + URLEncoder.encode(tag, "UTF-8") for tag in tags]

    if start_iso:
        query_parts.append("start=" + start_iso)
    if end_iso:
        query_parts.append("end=" + end_iso)

    return base + "&".join(query_parts)