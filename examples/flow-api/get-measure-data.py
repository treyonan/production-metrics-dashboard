"""
Flow MQTT Module

Reads and parses Flow measure data published via MQTT to Ignition tags.
Provides functions for retrieving latest values, fetching historical data
via embedded API endpoints, and converting responses to Ignition-native types.

Public Functions
----------------
get_measure_data_latest_value
    Return the latest measure value from an MQTT tag payload.
get_measure_data_api_endpoint
    Extract the measureDataApiEndpoint URL from an MQTT tag payload.
get_measure_data_history
    Fetch historical measure data using the embedded API endpoint.
to_dataset
    Convert a history API response to an Ignition BasicDataset.
to_list
    Extract a flat list of numeric values from a history API response.
to_dict_list
    Extract a list of dicts from a history API response.

Notes
-----
- Designed for Ignition/Jython 2.7 environment
- MQTT tags contain JSON payloads published by Flow InfoHub
- Historical data requests use the embedded API endpoint URLs directly,
  substituting [PeriodStart] and [PeriodEnd] with caller-supplied times
- API response structure: dict with 'values' list, each containing 'data'
  list of points with keys: start, end, value, formatted, duration,
  datetime, periodid, detail (nested: quality.value, preferred, pending)
"""

from MES.Integrations.Flow import Client
from MES.Integrations.Flow import Config
from MES.Integrations.Flow.Utils import format_utc_to_local



# ============================================================================
# PRIVATE HELPERS
# ============================================================================

def _read_mqtt_tag(tag_path):
    """Read an MQTT tag and return the parsed JSON payload.

    Parameters
    ----------
    tag_path : str
        Full Ignition tag path (e.g., '[MQTT Engine]Flow/Big_Canyon/C4/Odometer').

    Returns
    -------
    dict
        Parsed JSON payload from the MQTT tag.

    Raises
    ------
    Exception
        If tag quality is bad or value is None.
    """
    qv = system.tag.readBlocking([tag_path])[0]

    if qv.quality.isNotGood():
        raise Exception("Bad tag quality for {}: {}".format(tag_path, qv.quality))

    raw = qv.value
    if raw is None:
        raise Exception("Tag value is None for {}".format(tag_path))

    return system.util.jsonDecode(raw)


# ============================================================================
# PUBLIC FUNCTIONS
# ============================================================================

def get_measure_data_latest_value(tag_path):
    """Return the latest measure value from the MQTT tag payload.

    Reads the tag directly — no API call required. The MQTT payload
    contains the most recent value published by Flow.

    Parameters
    ----------
    tag_path : str
        Full Ignition tag path (e.g., '[MQTT Engine]Flow/Big_Canyon/C4/Odometer').

    Returns
    -------
    float or None
        The latest measure value, or None if no values exist in the payload.
    """
    data = _read_mqtt_tag(tag_path)
    values = data.get('values', [])
    if not values:
        return None
    return values[0].get('value')


def get_measure_data_api_endpoint(tag_path):
    """Extract the measureDataApiEndpoint URL from the MQTT tag payload.

    The returned URL contains placeholder tokens [PeriodStart] and
    [PeriodEnd] that must be replaced with ISO-8601 timestamps before use.

    Parameters
    ----------
    tag_path : str
        Full Ignition tag path (e.g., '[MQTT Engine]Flow/Big_Canyon/C4/Odometer').

    Returns
    -------
    str
        The measureDataApiEndpoint URL template, or empty string if not found.
    """
    data = _read_mqtt_tag(tag_path)
    measure = data.get('measure', {})
    return measure.get('measureDataApiEndpoint', '')


def get_measure_data_history(tag_path, start, end):
    """Fetch historical measure data using the embedded API endpoint.

    Reads the MQTT tag to get the pre-configured API endpoint URL,
    substitutes [PeriodStart] and [PeriodEnd] with the supplied times,
    and executes an authenticated GET request.

    Parameters
    ----------
    tag_path : str
        Full Ignition tag path (e.g., '[MQTT Engine]Flow/Big_Canyon/C4/Odometer').
    start : str
        Start time in ISO-8601 format (e.g., '2026-01-01T00:00:00.000Z').
    end : str
        End time in ISO-8601 format (e.g., '2026-01-02T00:00:00.000Z').

    Returns
    -------
    dict or list
        Raw JSON-decoded API response from Flow.

    Raises
    ------
    Exception
        If no endpoint URL is found in the tag payload, or the API request fails.

    Examples
    --------
    Fetch one day of history::

        >>> response = get_measure_data_history(
        ...     '[MQTT Engine]Flow/Big_Canyon/C4/Odometer',
        ...     '2026-03-01T00:00:00.000Z',
        ...     '2026-03-02T00:00:00.000Z'
        ... )
        >>> values = to_list(response)
    """
    endpoint = get_measure_data_api_endpoint(tag_path)
    if not endpoint:
        raise Exception("No measureDataApiEndpoint found in tag payload for {}".format(tag_path))

    url = endpoint.replace('[PeriodStart]', start).replace('[PeriodEnd]', end)
    return Client.get_url(url)


# ============================================================================
# RESPONSE HELPERS
# ============================================================================

def _extract_data_points(api_response):
    """Extract the flat list of data point dicts from an API response.

    The API returns::

        {
            "values": [
                {"id": 1174, "name": "...", "data": [ {point}, {point}, ... ]},
                ...
            ],
            ...
        }

    This helper flattens across all measures in the response.

    Parameters
    ----------
    api_response : dict
        Raw API response from get_measure_data_history.

    Returns
    -------
    list of dict
        Flat list of data point dicts from all measures.
    """
    points = []
    for measure in api_response.get('values', []):
        points.extend(measure.get('data', []))
    return points



def to_dataset(api_response):
    """Convert a history API response to an Ignition BasicDataset.

    Timestamp columns (start, end, datetime) are converted from UTC
    to Central time in 'yyyy-MM-dd HH:mm' format.

    Parameters
    ----------
    api_response : dict
        Raw API response from get_measure_data_history.

    Returns
    -------
    com.inductiveautomation.ignition.common.BasicDataset
        Dataset with columns: start, end, value, formatted, duration,
        quality, datetime, periodid.
    """
    headers = ['start', 'end', 'value', 'formatted', 'duration',
               'quality', 'datetime', 'periodid']
    rows = []

    for item in _extract_data_points(api_response):
        detail = item.get('detail', {})
        quality = detail.get('quality', {}).get('value')

        rows.append([
            format_utc_to_local(item.get('start', '')),
            format_utc_to_local(item.get('end', '')),
            item.get('value'),
            item.get('formatted', ''),
            item.get('duration'),
            quality,
            format_utc_to_local(item.get('datetime', '')),
            item.get('periodid')
        ])

    return system.dataset.toDataSet(headers, rows)


def to_list(api_response):
    """Extract a flat list of numeric values from a history API response.

    Parameters
    ----------
    api_response : dict
        Raw API response from get_measure_data_history.

    Returns
    -------
    list of float
        Ordered list of measure values.
    """
    return [item.get('value') for item in _extract_data_points(api_response)]


def to_dict_list(api_response):
    """Extract a list of dicts from a history API response.

    Parameters
    ----------
    api_response : dict
        Raw API response from get_measure_data_history.

    Returns
    -------
    list of dict
        Each dict contains keys: start, end, value, formatted, duration,
        quality, datetime, periodid.
    """
    results = []
    for item in _extract_data_points(api_response):
        detail = item.get('detail', {})
        quality = detail.get('quality', {}).get('value')

        results.append({
            'start': item.get('start', ''),
            'end': item.get('end', ''),
            'value': item.get('value'),
            'formatted': item.get('formatted', ''),
            'duration': item.get('duration'),
            'quality': quality,
            'datetime': item.get('datetime', ''),
            'periodid': item.get('periodid')
        })
    return results


# ============================================================================
# DEBUG UTILITIES
# ============================================================================

def print_mqtt_data(data, indent=''):
    """Pretty-print a nested MQTT JSON payload for debugging.

    Parameters
    ----------
    data : dict, list, or primitive
        Parsed JSON data from an MQTT tag.
    indent : str, optional
        Current indentation level (used for recursion).

    Examples
    --------
    ::

        tag_path = '[MQTT Engine]Flow/Big_Canyon/C4/Odometer'
        data = system.tag.readBlocking([tag_path])[0].value
        data = system.util.jsonDecode(data)
        print_mqtt_data(data)
    """
    if isinstance(data, dict):
        for key, val in data.items():
            if isinstance(val, (dict, list)):
                print "{0}{1} -->".format(indent, key)
                print_mqtt_data(val, indent + '    ')
            else:
                print "{0}{1} --> {2}".format(indent, key, val)
    elif isinstance(data, list):
        for i, item in enumerate(data):
            if isinstance(item, (dict, list)):
                print "{0}[{1}] -->".format(indent, i)
                print_mqtt_data(item, indent + '    ')
            else:
                print "{0}[{1}] --> {2}".format(indent, i, item)
    else:
        print "{0}{1}".format(indent, data)


def print_api_response(api_response, indent=''):
    """Pretty-print a Flow API response for debugging.

    Use this to inspect the actual response structure from
    get_measure_data_history and verify field names used by
    the response helper functions.

    Parameters
    ----------
    api_response : dict, list, or primitive
        Raw API response from get_measure_data_history.
    indent : str, optional
        Current indentation level (used for recursion).

    Examples
    --------
    ::

        response = get_measure_data_history(
            '[MQTT Engine]Flow/Big_Canyon/C4/Odometer',
            '2026-03-01T00:00:00.000Z',
            '2026-03-02T00:00:00.000Z'
        )
        print_api_response(response)
    """
    print_mqtt_data(api_response, indent)


# ============================================================================
# EXAMPLE MQTT PAYLOAD (from print_mqtt_data output)
# ============================================================================

'''
Verification script — paste into Ignition Script Console:

from MES.Integrations.Flow import MQTT

tag_path = '[MQTT Engine]Flow/Big_Canyon/C4/Odometer'

response = MQTT.get_measure_data_history(
    tag_path,
    '2026-04-01T00:00:00.000Z',
    '2026-04-02T00:00:00.000Z'
)

print "--- to_list ---"
print MQTT.to_list(response)

print "\n--- to_dict_list (first entry) ---"
dicts = MQTT.to_dict_list(response)
if dicts:
    for k, v in dicts[0].items():
        print "  {} --> {}".format(k, v)

print "\n--- to_dataset ---"
ds = MQTT.to_dataset(response)
print "Rows: {}, Cols: {}".format(ds.rowCount, ds.columnCount)
print "Headers: {}".format(list(ds.columnNames))
'''

'''
Example print_mqtt_data() output:

$namespace --> https://github.com/flow-software/InfoHub-Profiles/blob/6027bead6c6d60f58ee5f75c8e95692f808d62d2/Profiles/Measure/FlowMeasureValueData.schema.json
values -->
    [0] -->
        $namespace --> https://github.com/flow-software/InfoHub-Profiles/blob/6027bead6c6d60f58ee5f75c8e95692f808d62d2/Profiles/Measure/FlowMeasureValue.schema.json
        $comment --> Measure value — a single data point with optional attribute breakdown
        quality --> 192
        duration --> 3600000
        formattedValue --> 0.0
        value --> 0.0
measure -->
    $namespace --> https://github.com/flow-software/InfoHub-Profiles/blob/bf0a941dd1edcee469a782c56f90c1a821bdcd39/Profiles/Measure/FlowMeasure.schema.json
    parent --> C4
    hierarchicalName --> C4.Odometer.Odometer
    format --> 0.0
    description --> C4_Odometer
    $comment --> Measure definition — identifies the measure being reported
    measureDataApiEndpoint --> http://dbp-bcq:4501/flow-software/flow/instances/80D1092C-EFBF-4592-9425-C85ABE2EC7FB/server/api/v1/data/measures?start=[PeriodStart]&end=[PeriodEnd]&preferred=true&eventPeriods=false&calendarid=1&id=1174&comments=false&exceptions=false&attributes=false&users=false&limit=1000
    measureDataApiEndpointWithAttributes --> http://dbp-bcq:4501/flow-software/flow/instances/80D1092C-EFBF-4592-9425-C85ABE2EC7FB/server/api/v1/data/measures?start=[PeriodStart]&end=[PeriodEnd]&preferred=true&eventPeriods=false&calendarid=1&id=1174&comments=false&exceptions=false&attributes=true&users=false&limit=1000
    uom --> Tons
    intervalType --> Hourly
    name --> Odometer
    id --> 1174
modelAttributes -->
    $namespace --> https://github.com/flow-software/InfoHub-Profiles/blob/bf0a941dd1edcee469a782c56f90c1a821bdcd39/Profiles/Measure/FlowModelAttributes.schema.json
    Site --> Big_Canyon
    ConnectionProperty.Tagname --> Odometer
    ConnectionProperty.State -->
    Conveyor_Number --> C4
    $comment --> Model attributes — contextual metadata from the data model hierarchy
    ConnectionProperty.ScaleFactor --> 1
    Line --> Conveyor
    ConnectionProperty.ComparatorType --> Equals
    Area --> Secondary
    ConnectionProperty.AggregationType --> Counter
    Entity_ID --> 214
    Workcenter_ID --> 3
    ConnectionProperty.Rollover --> 0
    ConnectionProperty.RolloverDeadband --> 0
timePeriod -->
    $namespace --> https://github.com/flow-software/InfoHub-Profiles/blob/bf0a941dd1edcee469a782c56f90c1a821bdcd39/Profiles/Measure/FlowTimePeriod.schema.json
    timeScheme --> Production
    timeSchemeShift --> Morning
    start --> 2026-04-01T14:00:00.0000000Z
    $comment --> Time period — defines the reporting window for the values
    endUnix --> 1775055600
    end --> 2026-04-01T15:00:00.0000000Z
    startUnix --> 1775052000
'''