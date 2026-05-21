"""
i3X API Module

This module provides functions for interacting with the Industrial Information
Interface eXchange (i3X) REST API. It implements the RFC 001 compliant i3X
prototype API for exploring namespaces, object types, relationship types, objects,
querying values and history, writing values, and managing subscriptions.

Public Functions
----------------
Explore
    get_namespaces           Retrieve all namespaces
    get_object_types         Retrieve schemas for all Object Types
    get_relationship_types   Retrieve all Relationship Types
    get_objects              Retrieve all Objects

Query
    get_values               Return last known value(s) for one or more Objects
    get_history              Return historical values for one or more Objects

Update
    update_value             Write the current value of an Object
    update_history           Write historical values for an Object

Subscribe
    list_subscriptions       List all active subscriptions
    create_subscription      Create a new subscription
    get_subscription         Get a single subscription with its registered objects
    delete_subscription      Delete a subscription
    register_items           Add objects to a subscription
    unregister_items         Remove objects from a subscription
    sync                     Return and clear queued value updates

Notes
-----
- Designed for Ignition/Jython 2.7 environment
- API version: 0.0.1 (OAS 3.1, RFC 001 Compliant)
- Base URL: http://10.44.135.12:8080
- No authentication required (local service)
"""

from java.lang import String


BASE_URL = "http://10.44.135.12:8080"


# ============================================================================
# HTTP HELPERS
# ============================================================================

def _Get(endpoint, params=None):
    """
    Execute a GET request against the i3X API.

    Parameters
    ----------
    endpoint : str
        API endpoint path (e.g., '/namespaces'). Appended to BASE_URL.
    params : dict, optional
        Query parameters to include in the request.

    Returns
    -------
    object
        JSON-decoded response body (list or dict).

    Raises
    ------
    Exception
        If the API returns a non-2xx status code. Message includes
        endpoint, status code, and response body.
    """
    url = BASE_URL + endpoint
    client = system.net.httpClient()
    response = client.get(url, params=params)

    status = response.getStatusCode()
    body_str = String(response.getBody(), "UTF-8")

    if status < 200 or status >= 300:
        raise Exception(
            "i3X API GET {0} failed. status={1}, body={2}".format(
                endpoint, status, body_str
            )
        )

    return system.util.jsonDecode(body_str)


def _Post(endpoint, payload=None):
    """
    Execute a POST request against the i3X API.

    Parameters
    ----------
    endpoint : str
        API endpoint path (e.g., '/objects/list'). Appended to BASE_URL.
    payload : dict or list, optional
        Request body. Will be JSON-encoded. Sends empty object if None.

    Returns
    -------
    object
        JSON-decoded response body (list or dict).

    Raises
    ------
    Exception
        If the API returns a non-2xx status code. Message includes
        endpoint, status code, and response body.
    """
    url = BASE_URL + endpoint
    body = system.util.jsonEncode(payload) if payload is not None else "{}"
    headers = {"Content-Type": "application/json"}

    client = system.net.httpClient()
    response = client.post(url, data=body, headers=headers)

    status = response.getStatusCode()
    body_str = String(response.getBody(), "UTF-8")

    if status < 200 or status >= 300:
        raise Exception(
            "i3X API POST {0} failed. status={1}, body={2}".format(
                endpoint, status, body_str
            )
        )

    return system.util.jsonDecode(body_str)


def _Put(endpoint, payload=None):
    """
    Execute a PUT request against the i3X API.

    Parameters
    ----------
    endpoint : str
        API endpoint path (e.g., '/objects/{elementId}/value'). Appended to BASE_URL.
    payload : object, optional
        Request body. Will be JSON-encoded.

    Returns
    -------
    object
        JSON-decoded response body.

    Raises
    ------
    Exception
        If the API returns a non-2xx status code. Message includes
        endpoint, status code, and response body.
    """
    url = BASE_URL + endpoint
    body = system.util.jsonEncode(payload) if payload is not None else "null"
    headers = {"Content-Type": "application/json"}

    client = system.net.httpClient()
    response = client.put(url, data=body, headers=headers)

    status = response.getStatusCode()
    body_str = String(response.getBody(), "UTF-8")

    if status < 200 or status >= 300:
        raise Exception(
            "i3X API PUT {0} failed. status={1}, body={2}".format(
                endpoint, status, body_str
            )
        )

    return system.util.jsonDecode(body_str)


def _Delete(endpoint):
    """
    Execute a DELETE request against the i3X API.

    Parameters
    ----------
    endpoint : str
        API endpoint path (e.g., '/subscriptions/{subscriptionId}'). Appended to BASE_URL.

    Returns
    -------
    object
        JSON-decoded response body.

    Raises
    ------
    Exception
        If the API returns a non-2xx status code. Message includes
        endpoint, status code, and response body.
    """
    url = BASE_URL + endpoint
    client = system.net.httpClient()
    response = client.delete(url)

    status = response.getStatusCode()
    body_str = String(response.getBody(), "UTF-8")

    if status < 200 or status >= 300:
        raise Exception(
            "i3X API DELETE {0} failed. status={1}, body={2}".format(
                endpoint, status, body_str
            )
        )

    return system.util.jsonDecode(body_str)


# ============================================================================
# EXPLORE
# ============================================================================

def get_namespaces():
    """
    Retrieve all namespaces registered in the i3X server.

    Fetches the complete list of namespaces available in the connected i3X
    instance. Namespaces group object types and relationship types and serve
    as the top-level organizational unit of the i3X information model.

    Parameters
    ----------
    None

    Returns
    -------
    list of dict
        Each dict represents one namespace and contains:

        - ``uri``         (str): Unique namespace identifier URI.
        - ``displayName`` (str): Human-readable label for the namespace.

    Raises
    ------
    Exception
        If the i3X server returns a non-2xx status code, or if the server
        is unreachable. Exception message includes status code and response body.

    Examples
    --------
    Retrieve and print all namespaces::

        >>> namespaces = get_namespaces()
        >>> for ns in namespaces:
        ...     print ns['uri'], '-', ns['displayName']

    Retrieve just the URIs::

        >>> uris = [ns['uri'] for ns in get_namespaces()]
    """
    return _Get("/namespaces")


def get_object_types(namespace_uri=None):
    """
    Retrieve the schemas for all Object Types.

    Returns all registered Object Type definitions. Optionally filter to a
    single namespace by providing its URI.

    Parameters
    ----------
    namespace_uri : str, optional
        Namespace URI to filter results. If None, returns types from all
        namespaces.

    Returns
    -------
    list of dict
        Each dict represents one Object Type and contains:

        - ``elementId``    (str): Unique identifier for the type.
        - ``displayName``  (str): Human-readable label.
        - ``namespaceUri`` (str): Owning namespace URI.
        - ``schema``       (dict): JSON schema definition of the type.

    Raises
    ------
    Exception
        If the i3X server returns a non-2xx status code.

    Examples
    --------
    Retrieve all object types::

        >>> types = get_object_types()

    Retrieve types for a specific namespace::

        >>> types = get_object_types(namespace_uri='urn:example:ns')
    """
    params = {"namespaceUri": namespace_uri} if namespace_uri is not None else None
    return _Get("/objecttypes", params=params)


def get_relationship_types(namespace_uri=None):
    """
    Retrieve all Relationship Types.

    Returns all registered Relationship Type definitions. Optionally filter
    to a single namespace by providing its URI.

    Parameters
    ----------
    namespace_uri : str, optional
        Namespace URI to filter results. If None, returns types from all
        namespaces.

    Returns
    -------
    list of dict
        Each dict represents one Relationship Type and contains:

        - ``elementId``    (str): Unique identifier for the relationship type.
        - ``displayName``  (str): Human-readable label.
        - ``namespaceUri`` (str): Owning namespace URI.
        - ``reverseOf``    (str): ElementId of the inverse relationship, if any.

    Raises
    ------
    Exception
        If the i3X server returns a non-2xx status code.

    Examples
    --------
    Retrieve all relationship types::

        >>> rel_types = get_relationship_types()

    Retrieve relationship types for a specific namespace::

        >>> rel_types = get_relationship_types(namespace_uri='urn:example:ns')
    """
    params = {"namespaceUri": namespace_uri} if namespace_uri is not None else None
    return _Get("/relationshiptypes", params=params)


def get_objects(type_id=None, include_metadata=False):
    """
    Retrieve all Objects, with optional filtering by type.

    Returns all Object instances registered in the i3X server. Optionally
    filter to a specific type and include extended metadata.

    Parameters
    ----------
    type_id : str, optional
        ElementId of an Object Type to filter by. If None, all objects are
        returned regardless of type.
    include_metadata : bool, optional
        When True, the response includes extended metadata fields for each
        object. Default: False.

    Returns
    -------
    list of dict
        Each dict represents one Object and contains:

        - ``elementId``      (str): Unique identifier for the object.
        - ``displayName``    (str): Human-readable label.
        - ``typeId``         (str): ElementId of the object's type.
        - ``parentId``       (str): ElementId of the parent object.
        - ``isComposition``  (bool): Whether the parent relationship is a composition.
        - ``namespaceUri``   (str): Owning namespace URI.

    Raises
    ------
    Exception
        If the i3X server returns a non-2xx status code.

    Examples
    --------
    Retrieve all objects::

        >>> objects = get_objects()

    Retrieve all objects of a specific type::

        >>> objects = get_objects(type_id='urn:example:Pump')

    Retrieve all objects with metadata::

        >>> objects = get_objects(include_metadata=True)
    """
    params = {}
    if type_id is not None:
        params["typeId"] = type_id
    if include_metadata:
        params["includeMetadata"] = True
    return _Get("/objects", params=params if params else None)


def query_object_types(element_ids):
    """
    Retrieve the schema for one or more Object Types by ElementId.

    Fetches full type definitions for the specified ElementIds. More
    efficient than get_object_types() when you already know the IDs you need.

    Parameters
    ----------
    element_ids : list of str
        One or more Object Type ElementIds to retrieve.

    Returns
    -------
    list
        Array of Object Type objects matching the requested ElementIds.

    Raises
    ------
    Exception
        If the i3X server returns a non-2xx status code.

    Examples
    --------
    Query a single type by ID::

        >>> types = query_object_types(['urn:example:Pump'])

    Query multiple types::

        >>> types = query_object_types(['urn:example:Pump', 'urn:example:Motor'])
    """
    return _Post("/objecttypes/query", payload={"elementIds": element_ids})


def query_relationship_types(element_ids):
    """
    Retrieve one or more Relationship Types by ElementId.

    Fetches full relationship type definitions for the specified ElementIds.

    Parameters
    ----------
    element_ids : list of str
        One or more Relationship Type ElementIds to retrieve.

    Returns
    -------
    list
        Array of Relationship Type objects matching the requested ElementIds.

    Raises
    ------
    Exception
        If the i3X server returns a non-2xx status code.

    Examples
    --------
    Query a relationship type by ID::

        >>> rel_types = query_relationship_types(['urn:example:HasComponent'])
    """
    return _Post("/relationshiptypes/query", payload={"elementIds": element_ids})


def list_objects(element_ids, include_metadata=False):
    """
    Return one or more Objects by ElementId.

    Fetches full object records for the specified ElementIds. More efficient
    than get_objects() when you already know the IDs you need.

    Parameters
    ----------
    element_ids : list of str
        One or more Object ElementIds to retrieve.
    include_metadata : bool, optional
        When True, includes extended metadata fields in the response.
        Default: False.

    Returns
    -------
    list
        Array of Object records matching the requested ElementIds.

    Raises
    ------
    Exception
        If the i3X server returns a non-2xx status code.

    Examples
    --------
    Retrieve specific objects::

        >>> objects = list_objects(['urn:example:Pump1', 'urn:example:Pump2'])
    """
    payload = {"elementIds": element_ids, "includeMetadata": include_metadata}
    return _Post("/objects/list", payload=payload)


def get_related_objects(element_ids, relationship_type=None, include_metadata=False):
    """
    Return related objects for one or more Objects.

    Traverses the relationship graph and returns objects connected to the
    specified elements. Optionally filter by a specific relationship type.

    Parameters
    ----------
    element_ids : list of str
        One or more Object ElementIds to find related objects for.
    relationship_type : str, optional
        ElementId of a Relationship Type to filter by. If None, returns
        objects across all relationship types.
    include_metadata : bool, optional
        When True, includes extended metadata fields in the response.
        Default: False.

    Returns
    -------
    list
        Array of related Object records.

    Raises
    ------
    Exception
        If the i3X server returns a non-2xx status code.

    Examples
    --------
    Find all objects related to a pump::

        >>> related = get_related_objects(['urn:example:Pump1'])

    Find only child components::

        >>> children = get_related_objects(
        ...     ['urn:example:Pump1'],
        ...     relationship_type='urn:example:HasComponent'
        ... )
    """
    payload = {
        "elementIds": element_ids,
        "includeMetadata": include_metadata
    }
    if relationship_type is not None:
        payload["relationshiptype"] = relationship_type
    return _Post("/objects/related", payload=payload)


# ============================================================================
# QUERY
# ============================================================================

def get_values(element_ids, max_depth=1):
    """
    Return the last known value for one or more Objects.

    Queries the current (last known) value of each specified object. If
    max_depth=0, recursively retrieves values from all HasComponent children
    at infinite depth. Otherwise, recurses only to the specified depth
    (1 = no recursion, just the specified element).

    Parameters
    ----------
    element_ids : list of str
        One or more elementIds to retrieve values for.
    max_depth : int, optional
        Recursion depth for HasComponent children.
        0 = infinite, 1 = no recursion. Default: 1.

    Returns
    -------
    list
        Array of value objects for the requested elements.

    Raises
    ------
    Exception
        If the i3X server returns a non-2xx status code.

    Examples
    --------
    Get current value of a single object::

        >>> values = get_values(['urn:example:Pump1'])

    Get values with full child recursion::

        >>> values = get_values(['urn:example:Site1'], max_depth=0)
    """
    payload = {"elementIds": element_ids, "maxDepth": max_depth}
    return _Post("/objects/value", payload=payload)


def get_history(element_ids, start_time, end_time, max_depth=1):
    """
    Return historical values for one or more Objects.

    Retrieves time-series history for the specified objects over the given
    time range. If max_depth=0, recursively includes HasComponent children
    at infinite depth.

    Parameters
    ----------
    element_ids : list of str
        One or more elementIds to retrieve history for.
    start_time : str
        Start of the time range in ISO-8601 format
        (e.g., '2024-01-01T00:00:00Z').
    end_time : str
        End of the time range in ISO-8601 format.
    max_depth : int, optional
        Recursion depth for HasComponent children.
        0 = infinite, 1 = no recursion. Default: 1.

    Returns
    -------
    list
        Array of historical value objects for the requested elements.

    Raises
    ------
    Exception
        If the i3X server returns a non-2xx status code.

    Examples
    --------
    Retrieve one hour of history for a single object::

        >>> history = get_history(
        ...     element_ids=['urn:example:Pump1'],
        ...     start_time='2024-01-01T08:00:00Z',
        ...     end_time='2024-01-01T09:00:00Z'
        ... )
    """
    payload = {
        "elementIds": element_ids,
        "startTime": start_time,
        "endTime": end_time,
        "maxDepth": max_depth
    }
    return _Post("/objects/history", payload=payload)


# ============================================================================
# UPDATE
# ============================================================================

def update_value(element_id, value):
    """
    Write the current value of an Object.

    Updates the live value of the specified object in the i3X server.

    Parameters
    ----------
    element_id : str
        ElementId of the object to update.
    value : object
        The new value to write. Must be JSON-serializable and compatible
        with the object's type schema.

    Returns
    -------
    object
        JSON-decoded confirmation response from the server.

    Raises
    ------
    Exception
        If the i3X server returns a non-2xx status code.

    Examples
    --------
    Write a numeric value::

        >>> update_value('urn:example:Pump1.Speed', 1450.0)

    Write a string value::

        >>> update_value('urn:example:Pump1.Status', 'Running')
    """
    return _Put("/objects/{0}/value".format(element_id), payload=value)


def update_history(element_id, history):
    """
    Write historical values for an Object.

    Stores one or more historical value records for the specified object
    in the i3X server.

    Parameters
    ----------
    element_id : str
        ElementId of the object to update.
    history : object
        Historical value payload. Must be JSON-serializable and structured
        per the i3X history schema.

    Returns
    -------
    object
        JSON-decoded confirmation response from the server.

    Raises
    ------
    Exception
        If the i3X server returns a non-2xx status code.

    Examples
    --------
    Write a historical record::

        >>> update_history('urn:example:Pump1.Speed', {...})
    """
    return _Put("/objects/{0}/history".format(element_id), payload=history)


# ============================================================================
# SUBSCRIBE
# ============================================================================

def list_subscriptions():
    """
    List all active subscriptions.

    Returns all current subscriptions including their IDs and settings.
    Does not include the registered objects for each subscription — use
    get_subscription() for that detail.

    Parameters
    ----------
    None

    Returns
    -------
    dict
        Contains:

        - ``subscriptionIds`` (list of dict): Each dict has:
            - ``subscriptionId`` (int): Numeric subscription identifier.
            - ``created``        (str): ISO-8601 creation timestamp.

    Raises
    ------
    Exception
        If the i3X server returns a non-2xx status code.

    Examples
    --------
    List all subscriptions::

        >>> subs = list_subscriptions()
        >>> for s in subs['subscriptionIds']:
        ...     print s['subscriptionId'], s['created']
    """
    return _Get("/subscriptions")


def create_subscription():
    """
    Create a new subscription.

    Creates a new subscription session on the i3X server. Monitoring does
    not begin until objects are registered via register_items(). The returned
    subscriptionId must be retained for all subsequent subscription operations.

    Parameters
    ----------
    None

    Returns
    -------
    dict
        Contains:

        - ``subscriptionId`` (str): The ID of the newly created subscription.
        - ``message``        (str): Server confirmation message.

    Raises
    ------
    Exception
        If the i3X server returns a non-2xx status code.

    Examples
    --------
    Create a subscription and capture the ID::

        >>> result = create_subscription()
        >>> sub_id = result['subscriptionId']
    """
    return _Post("/subscriptions", payload={})


def get_subscription(subscription_id):
    """
    Get a single subscription including its registered objects.

    Returns full details for a subscription: settings and the list of
    objects currently registered for monitoring.

    Parameters
    ----------
    subscription_id : str
        The subscriptionId returned by create_subscription().

    Returns
    -------
    object
        JSON-decoded subscription detail object.

    Raises
    ------
    Exception
        If the i3X server returns a non-2xx status code.

    Examples
    --------
    Inspect a subscription::

        >>> sub = get_subscription('abc123')
    """
    return _Get("/subscriptions/{0}".format(subscription_id))


def delete_subscription(subscription_id):
    """
    Delete a subscription.

    Permanently removes the subscription and stops all monitoring for its
    registered objects.

    Parameters
    ----------
    subscription_id : str
        The subscriptionId of the subscription to delete.

    Returns
    -------
    object
        JSON-decoded confirmation response from the server.

    Raises
    ------
    Exception
        If the i3X server returns a non-2xx status code.

    Examples
    --------
    Delete a subscription::

        >>> delete_subscription('abc123')
    """
    return _Delete("/subscriptions/{0}".format(subscription_id))


def register_items(subscription_id, element_ids, max_depth=1):
    """
    Add objects to a subscription for monitoring.

    Registers one or more objects with an existing subscription. After
    registration, value changes for those objects will be queued or streamed
    depending on the active mode.

    Parameters
    ----------
    subscription_id : str
        The subscriptionId to register objects with.
    element_ids : list of str
        ElementIds of objects to register.
    max_depth : int, optional
        Recursion depth for HasComponent children to include.
        0 = infinite, 1 = no recursion. Default: 1.

    Returns
    -------
    object
        JSON-decoded confirmation response from the server.

    Raises
    ------
    Exception
        If the i3X server returns a non-2xx status code.

    Examples
    --------
    Register two objects for monitoring::

        >>> register_items('abc123', ['urn:example:Pump1', 'urn:example:Pump2'])
    """
    payload = {"elementIds": element_ids, "maxDepth": max_depth}
    return _Post("/subscriptions/{0}/register".format(subscription_id), payload=payload)


def unregister_items(subscription_id, element_ids, max_depth=1):
    """
    Remove objects from a subscription.

    Unregisters one or more objects from an existing subscription, stopping
    monitoring for those objects.

    Parameters
    ----------
    subscription_id : str
        The subscriptionId to remove objects from.
    element_ids : list of str
        ElementIds of objects to unregister.
    max_depth : int, optional
        Recursion depth matching the depth used at registration.
        Default: 1.

    Returns
    -------
    object
        JSON-decoded confirmation response from the server.

    Raises
    ------
    Exception
        If the i3X server returns a non-2xx status code.

    Examples
    --------
    Unregister objects from a subscription::

        >>> unregister_items('abc123', ['urn:example:Pump1'])
    """
    payload = {"elementIds": element_ids, "maxDepth": max_depth}
    return _Post("/subscriptions/{0}/unregister".format(subscription_id), payload=payload)


def stream(subscription_id):
    """
    Open a Server-Sent Events (SSE) stream for a subscription.

    Switches the subscription from queue mode to streaming mode. The server
    will push value updates as SSE events over the open connection.

    Note: SSE is a long-lived streaming connection. Handling of the response
    stream may require special treatment depending on the Ignition HTTP client
    version and configuration.

    Parameters
    ----------
    subscription_id : str
        The subscriptionId to open a stream for.

    Returns
    -------
    object
        Initial JSON-decoded response from the server.

    Raises
    ------
    Exception
        If the i3X server returns a non-2xx status code.

    Examples
    --------
    Open an SSE stream::

        >>> stream('abc123')
    """
    return _Get("/subscriptions/{0}/stream".format(subscription_id))


def sync(subscription_id):
    """
    Return and clear queued value updates for a subscription.

    Polls the server for any value changes queued since the last sync call.
    Clears the queue after returning. Use this when an SSE stream is not
    active (queue mode).

    Parameters
    ----------
    subscription_id : str
        The subscriptionId to sync.

    Returns
    -------
    list
        Array of value updates in format: [{elementId: {data: [VQT]}}]

    Raises
    ------
    Exception
        If the i3X server returns a non-2xx status code.

    Examples
    --------
    Poll for updates::

        >>> updates = sync('abc123')
        >>> for update in updates:
        ...     print update
    """
    return _Post("/subscriptions/{0}/sync".format(subscription_id))
