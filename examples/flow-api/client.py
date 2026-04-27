"""
Flow HTTP Client

Shared HTTP request layer for all Flow API calls.
Handles authentication, request execution, response parsing, and error handling.

Public Functions
----------------
get
    Authenticated GET against the Flow API (endpoint-based).
get_url
    Authenticated GET against a full URL (no base URL prefix).
post
    Authenticated POST against the Flow API.
delete
    Authenticated DELETE against the Flow API.

Notes
-----
- Designed for Ignition/Jython 2.7 environment
- Uses Bearer token authentication via Config.get_api_key()
- All responses are JSON-decoded; empty 204 responses return None
"""

from java.lang import String
from MES.Integrations.Flow import Config


def get(endpoint, params=None):
    """Authenticated GET against the Flow API.

    Parameters
    ----------
    endpoint : str
        API path (e.g., '/api/v1/data/measures').
        Will be appended to Config.get_base_url().
    params : dict, optional
        Query parameters to include in the request.

    Returns
    -------
    dict or list or None
        JSON-decoded response body, or None for empty responses.
    """
    url = Config.get_base_url() + endpoint
    return _request("GET", url, params=params)


def get_url(url):
    """Authenticated GET against a full URL (no base URL prefix).

    Used for requests where the complete URL is already provided,
    such as embedded API endpoint URLs from MQTT payloads.

    Parameters
    ----------
    url : str
        Full URL including query parameters.

    Returns
    -------
    dict or list or None
        JSON-decoded response body, or None for empty responses.
    """
    return _request("GET", url)


def post(endpoint, data=None, params=None):
    """Authenticated POST against the Flow API.

    Parameters
    ----------
    endpoint : str
        API path (e.g., '/api/v1/config/calendars/1/shifts').
    data : dict, optional
        Request body. Will be JSON-encoded before sending.
    params : dict, optional
        Query parameters.

    Returns
    -------
    dict or list or None
        JSON-decoded response body, or None for empty responses.
    """
    url = Config.get_base_url() + endpoint
    return _request("POST", url, data=data, params=params)


def delete(endpoint, params=None):
    """Authenticated DELETE against the Flow API.

    Parameters
    ----------
    endpoint : str
        API path (e.g., '/api/v1/config/calendars/1/shifts').
    params : dict, optional
        Query parameters.

    Returns
    -------
    dict or list or None
        JSON-decoded response body, or None for empty responses.
    """
    url = Config.get_base_url() + endpoint
    return _request("DELETE", url, params=params)


# ============================================================================
# PRIVATE
# ============================================================================

def _build_query_string(params):
    """Build a URL query string from a params dict.

    Handles list values by repeating the key (e.g., id=1&id=2).
    Ignition's httpClient does not expand list values into repeated
    query parameters, so we build the query string manually.

    Parameters
    ----------
    params : dict
        Query parameters. Values may be scalars or lists.

    Returns
    -------
    str
        URL-encoded query string (without leading '?'), or empty string.
    """
    if not params:
        return ''

    from java.net import URLEncoder
    parts = []
    for key, value in params.items():
        if isinstance(value, (list, tuple)):
            for item in value:
                parts.append(
                    URLEncoder.encode(str(key), "UTF-8") + "=" +
                    URLEncoder.encode(str(item), "UTF-8")
                )
        else:
            parts.append(
                URLEncoder.encode(str(key), "UTF-8") + "=" +
                URLEncoder.encode(str(value), "UTF-8")
            )
    return '&'.join(parts)


def _request(method, url, params=None, data=None):
    """Execute an authenticated HTTP request.

    Parameters
    ----------
    method : str
        HTTP method ('GET', 'POST', 'DELETE').
    url : str
        Full URL.
    params : dict, optional
        Query parameters. List values are expanded into repeated keys.
    data : dict, optional
        Request body for POST. Will be JSON-encoded.

    Returns
    -------
    dict or list or None
        JSON-decoded response body, or None for empty responses.

    Raises
    ------
    Exception
        If the API returns a non-2xx status code.
    """
    token = Config.get_api_key()
    headers = {
        "Authorization": "Bearer " + token,
        "Content-Type": "application/json"
    }

    # Build query string manually to support repeated keys (e.g., id=1&id=2)
    qs = _build_query_string(params)
    if qs:
        separator = '&' if '?' in url else '?'
        url = url + separator + qs

    client = system.net.httpClient()

    if method == "GET":
        response = client.get(url, headers=headers)
    elif method == "POST":
        body = system.util.jsonEncode(data) if data else ""
        response = client.post(url, body, headers=headers)
    elif method == "DELETE":
        response = client.delete(url, headers=headers)
    else:
        raise ValueError("Unsupported HTTP method: " + method)

    status = response.getStatusCode()
    body_str = String(response.getBody(), "UTF-8")

    if status < 200 or status >= 300:
        raise Exception(
            "Flow API {0} {1} failed. status={2}, body={3}".format(
                method, url, status, body_str
            )
        )

    if not body_str or not body_str.strip():
        return None

    return system.util.jsonDecode(body_str)