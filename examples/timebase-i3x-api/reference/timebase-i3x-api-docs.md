# Timebase Historian API

![Timebase](./logo.webp)

Select a definitionv1i3x

## Timebase Historian i3X API i3X.v1 

OAS 3.0

[/api/i3x.json](/api/i3x.json)

The CESMII i3X API for Timebase Historian (Beta)

Authorize

### Explore

Browse namespaces, object types, and objects

GET

/i3x/namespaces

List all namespaces

Returns the Timebase Historian namespace plus all dataset namespaces.

#### Parameters

Try it out

No parameters

#### Responses

Code

Description

Links

200

List of namespaces

Media type

application/json

Controls `Accept` header.

*   Example Value
*   Schema

\[
  {
    "uri": "https://timebase.com/historian",
    "displayName": "Timebase Historian"
  }
\]

_No links_

GET

/i3x/objecttypes

List all object types

Returns all object types: Dataset (root container), Folder (virtual directory), and Tag (time-series data).

#### Parameters

Try it out

Name

Description

namespaceUri

string

(query)

Optional filter by namespace URI

#### Responses

Code

Description

Links

200

List of object types

Media type

application/json

Controls `Accept` header.

*   Example Value
*   Schema

\[
  {
    "elementId": "Dataset",
    "displayName": "Dataset",
    "namespaceUri": "https://timebase.com/historian",
    "schema": {
      "description": "Root container for tags"
    }
  },
  {
    "elementId": "Folder",
    "displayName": "Folder",
    "namespaceUri": "https://timebase.com/historian",
    "schema": {
      "description": "Virtual directory derived from tag paths"
    }
  },
  {
    "elementId": "Tag",
    "displayName": "Tag",
    "namespaceUri": "https://timebase.com/historian",
    "schema": {
      "type": "object"
    }
  }
\]

_No links_

POST

/i3x/objecttypes/query

Query object types by ElementId(s)

Query specific object types by their ElementId. Valid types: Dataset, Folder, Tag. Returns a direct array of found object types.

#### Parameters

Try it out

No parameters

#### Request body

application/json

*   Example Value
*   Schema

{
  "elementIds": \[
    "Dataset",
    "Folder",
    "Tag"
  \]
}

#### Responses

Code

Description

Links

200

Array of requested object types

Media type

application/json

Controls `Accept` header.

*   Example Value
*   Schema

\[
  {
    "elementId": "Dataset",
    "displayName": "Dataset",
    "namespaceUri": "https://timebase.com/historian",
    "schema": {
      "description": "Root container for tags"
    }
  },
  {
    "elementId": "Folder",
    "displayName": "Folder",
    "namespaceUri": "https://timebase.com/historian",
    "schema": {
      "description": "Virtual directory derived from tag paths"
    }
  },
  {
    "elementId": "Tag",
    "displayName": "Tag",
    "namespaceUri": "https://timebase.com/historian",
    "schema": {
      "type": "object"
    }
  }
\]

_No links_

400

Bad Request

Media type

application/problem+json

*   Example Value
*   Schema

{
  "type": "string",
  "title": "string",
  "status": 0,
  "detail": "string",
  "instance": "string",
  "errors": {
    "additionalProp1": \[
      "string"
    \],
    "additionalProp2": \[
      "string"
    \],
    "additionalProp3": \[
      "string"
    \]
  },
  "additionalProp1": "string",
  "additionalProp2": "string",
  "additionalProp3": "string"
}

_No links_

GET

/i3x/relationshiptypes

List all relationship types

Returns relationship types: HasChildren (parent→child) and HasParent (child→parent).

#### Parameters

Try it out

Name

Description

namespaceUri

string

(query)

Optional filter by namespace URI

#### Responses

Code

Description

Links

200

List of relationship types

Media type

application/json

Controls `Accept` header.

*   Example Value
*   Schema

\[
  {
    "elementId": "HasChildren",
    "displayName": "Has Children",
    "namespaceUri": "https://timebase.com/historian",
    "reverseOf": "HasParent"
  },
  {
    "elementId": "HasParent",
    "displayName": "Has Parent",
    "namespaceUri": "https://timebase.com/historian",
    "reverseOf": "HasChildren"
  }
\]

_No links_

POST

/i3x/relationshiptypes/query

Query relationship types by ElementId(s)

Query specific relationship types by ElementId. Valid types: HasChildren, HasParent. Returns a direct array of found relationship types.

#### Parameters

Try it out

No parameters

#### Request body

application/json

*   Example Value
*   Schema

{
  "elementId": "HasChildren"
}

#### Responses

Code

Description

Links

200

Array of requested relationship types

Media type

application/json

Controls `Accept` header.

*   Example Value
*   Schema

\[
  {
    "elementId": "HasChildren",
    "displayName": "Has Children",
    "namespaceUri": "https://timebase.com/historian",
    "reverseOf": "HasParent"
  }
\]

_No links_

400

Bad Request

Media type

application/problem+json

*   Example Value
*   Schema

{
  "type": "string",
  "title": "string",
  "status": 0,
  "detail": "string",
  "instance": "string",
  "errors": {
    "additionalProp1": \[
      "string"
    \],
    "additionalProp2": \[
      "string"
    \],
    "additionalProp3": \[
      "string"
    \]
  },
  "additionalProp1": "string",
  "additionalProp2": "string",
  "additionalProp3": "string"
}

_No links_

GET

/i3x/objects

List all objects

Returns all objects: Datasets (root containers), Folders (virtual directories from tag paths), and Tags.

#### Parameters

Try it out

Name

Description

typeId

string

(query)

Optional filter by object type (Dataset, Folder, or Tag)

namespaceUri

string

(query)

Optional filter by dataset namespace

includeMetadata

boolean

(query)

Include relationships in response

_Default value_ : false

\--truefalse

#### Responses

Code

Description

Links

200

List of objects (hierarchical)

Media type

application/json

Controls `Accept` header.

*   Example Value
*   Schema

\[
  {
    "elementId": "OPCUA Demo",
    "displayName": "OPCUA Demo",
    "typeId": "Dataset",
    "parentId": "/",
    "isComposition": true,
    "hasChildren": true,
    "namespaceUri": "https://timebase.com/historian"
  },
  {
    "elementId": "OPCUA Demo:Room1",
    "displayName": "Room1",
    "typeId": "Folder",
    "parentId": "OPCUA Demo",
    "isComposition": true,
    "hasChildren": true,
    "namespaceUri": "https://timebase.com/historian"
  },
  {
    "elementId": "OPCUA Demo:Room1/Temperature",
    "displayName": "Temperature",
    "typeId": "Tag",
    "parentId": "OPCUA Demo:Room1",
    "isComposition": false,
    "hasChildren": false,
    "namespaceUri": "https://timebase.com/historian"
  }
\]

_No links_

POST

/i3x/objects/list

Query objects by ElementId(s)

Query specific objects by their ElementId.

ElementId formats:

*   Dataset: `{datasetName}` (e.g. `OPCUA Demo`)
*   Folder: `{dataset}:{folderPath}` (e.g. `OPCUA Demo:Room1`)
*   Tag: `{dataset}:{tagPath}` (e.g. `OPCUA Demo:Room1/Temperature`)

Returns a direct array of ObjectInstance objects for found elements.

#### Parameters

Try it out

No parameters

#### Request body

application/json

*   Example Value
*   Schema

{
  "elementIds": \[
    "OPCUA Demo",
    "OPCUA Demo:Room1",
    "OPCUA Demo:Room1/Temperature"
  \],
  "includeMetadata": false
}

#### Responses

Code

Description

Links

200

Array of requested objects

Media type

application/json

Controls `Accept` header.

*   Example Value
*   Schema

\[
  {
    "elementId": "OPCUA Demo",
    "displayName": "OPCUA Demo",
    "typeId": "Dataset",
    "parentId": "/",
    "isComposition": true,
    "hasChildren": true,
    "namespaceUri": "https://timebase.com/historian"
  },
  {
    "elementId": "OPCUA Demo:Room1",
    "displayName": "Room1",
    "typeId": "Folder",
    "parentId": "OPCUA Demo",
    "isComposition": true,
    "hasChildren": true,
    "namespaceUri": "https://timebase.com/historian"
  },
  {
    "elementId": "OPCUA Demo:Room1/Temperature",
    "displayName": "Temperature",
    "typeId": "Tag",
    "parentId": "OPCUA Demo:Room1",
    "isComposition": false,
    "hasChildren": false,
    "namespaceUri": "https://timebase.com/historian"
  }
\]

_No links_

400

Bad Request

Media type

application/problem+json

*   Example Value
*   Schema

{
  "type": "string",
  "title": "string",
  "status": 0,
  "detail": "string",
  "instance": "string",
  "errors": {
    "additionalProp1": \[
      "string"
    \],
    "additionalProp2": \[
      "string"
    \],
    "additionalProp3": \[
      "string"
    \]
  },
  "additionalProp1": "string",
  "additionalProp2": "string",
  "additionalProp3": "string"
}

_No links_

POST

/i3x/objects/related

Query related objects

Query objects related to the specified ElementId(s).

Relationship types:

*   `HasChildren` - Returns direct children of the element
*   `HasParent` - Returns the parent of the element

Returns a direct array of related ObjectInstance objects.

#### Parameters

Try it out

No parameters

#### Request body

application/json

*   Example Value
*   Schema

{
  "elementId": "OPCUA Demo",
  "relationshiptype": "HasChildren",
  "includeMetadata": false
}

#### Responses

Code

Description

Links

200

Array of related objects

Media type

application/json

Controls `Accept` header.

*   Example Value
*   Schema

\[
  {
    "elementId": "OPCUA Demo:Room1",
    "displayName": "Room1",
    "typeId": "Folder",
    "parentId": "OPCUA Demo",
    "isComposition": true,
    "hasChildren": true,
    "namespaceUri": "https://timebase.com/historian"
  },
  {
    "elementId": "OPCUA Demo:SystemStatus",
    "displayName": "SystemStatus",
    "typeId": "Tag",
    "parentId": "OPCUA Demo",
    "isComposition": false,
    "hasChildren": false,
    "namespaceUri": "https://timebase.com/historian"
  }
\]

_No links_

400

Bad Request

Media type

application/problem+json

*   Example Value
*   Schema

{
  "type": "string",
  "title": "string",
  "status": 0,
  "detail": "string",
  "instance": "string",
  "errors": {
    "additionalProp1": \[
      "string"
    \],
    "additionalProp2": \[
      "string"
    \],
    "additionalProp3": \[
      "string"
    \]
  },
  "additionalProp1": "string",
  "additionalProp2": "string",
  "additionalProp3": "string"
}

_No links_

### Query

Query current and historical values

POST

/i3x/objects/value

Get last known value(s) for element(s)

Retrieves the most recent value for one or more elements.

ElementId formats:

*   Dataset: `{datasetName}` (e.g. `OPCUA Demo`)
*   Folder: `{dataset}:{folderPath}` (e.g. `OPCUA Demo:Room1`)
*   Tag: `{dataset}:{tagPath}` (e.g. `OPCUA Demo:Room1/Temperature`)

maxDepth controls compositional value retrieval:

*   `1` (default): Return only the element's own value
*   `0`: Infinite recursion - include all nested child values
*   `N > 1`: Include child values up to N levels deep

For Tags (leaf nodes), maxDepth has no effect - always returns the VQT.

#### Parameters

Try it out

No parameters

#### Request body

application/json

*   Example Value
*   Schema

{
  "elementIds": \[
    "OPCUA Demo:Room1/Temperature",
    "OPCUA Demo:Room1"
  \],
  "maxDepth": 2
}

#### Responses

Code

Description

Links

200

Values for requested elements (structure varies by type and maxDepth)

Media type

application/json

Controls `Accept` header.

*   Example Value
*   Schema

{
  "OPCUA Demo:Room1/Temperature": {
    "data": \[
      {
        "value": 72.5,
        "quality": "GOOD",
        "timestamp": "2026-05-21T15:06:00.795Z"
      }
    \]
  },
  "OPCUA Demo:Room1": {
    "elementId": "OPCUA Demo:Room1",
    "isComposition": true,
    "value": null,
    "children": {
      "OPCUA Demo:Room1/Temperature": {
        "value": 72.5,
        "quality": "GOOD",
        "timestamp": "2026-05-21T15:06:00.795Z"
      }
    }
  }
}

_No links_

400

Bad Request

Media type

application/problem+json

*   Example Value
*   Schema

{
  "type": "string",
  "title": "string",
  "status": 0,
  "detail": "string",
  "instance": "string",
  "errors": {
    "additionalProp1": \[
      "string"
    \],
    "additionalProp2": \[
      "string"
    \],
    "additionalProp3": \[
      "string"
    \]
  },
  "additionalProp1": "string",
  "additionalProp2": "string",
  "additionalProp3": "string"
}

_No links_

404

Not Found

_No links_

POST

/i3x/objects/history

Get historical values for Tag element(s)

Retrieves historical values for one or more **Tag** elements within a time range.

**Important**: This endpoint only supports Tag elementIds. Datasets and Folders (compositional objects) cannot be queried directly. To get historical data for all tags within a folder, first use `POST /objects/related` with `relationshipType='HasChildren'` to discover the child tag elementIds.

ElementId format: `{dataset}:{tagname}` (e.g. `OPCUA Demo:Room1/Temperature`)

Both `startTime` and `endTime` are required and must be in ISO 8601 format.

Provide either `elementId` for a single lookup or `elementIds` for batch lookup.

Returns a dictionary keyed by elementId, where each value contains a `data` array with VQT entries.

#### Parameters

Try it out

No parameters

#### Request body

application/json

*   Example Value
*   Schema

{
  "elementIds": \[
    "OPCUA Demo:131-TT-001.PV"
  \],
  "startTime": "2026-05-21T14:06:00.796Z",
  "endTime": "2026-05-21T15:06:00.796Z",
  "maxDepth": 1
}

#### Responses

Code

Description

Links

200

Historical values for requested elements (dictionary keyed by elementId)

Media type

application/json

Controls `Accept` header.

*   Example Value
*   Schema

{
  "OPCUA Demo:131-TT-001.PV": {
    "data": \[
      {
        "value": 56.788747,
        "quality": "GOOD",
        "timestamp": "2026-05-21T14:06:00.796Z"
      },
      {
        "value": 57.123456,
        "quality": "GOOD",
        "timestamp": "2026-05-21T14:36:00.796Z"
      },
      {
        "value": 57.957364,
        "quality": "GOOD",
        "timestamp": "2026-05-21T15:06:00.796Z"
      }
    \]
  }
}

_No links_

400

Bad Request

Media type

application/problem+json

*   Example Value
*   Schema

{
  "type": "string",
  "title": "string",
  "status": 0,
  "detail": "string",
  "instance": "string",
  "errors": {
    "additionalProp1": \[
      "string"
    \],
    "additionalProp2": \[
      "string"
    \],
    "additionalProp3": \[
      "string"
    \]
  },
  "additionalProp1": "string",
  "additionalProp2": "string",
  "additionalProp3": "string"
}

_No links_

404

Not Found

_No links_

### Subscribe

Manage real-time data subscriptions

GET

/i3x/subscriptions

List all active subscriptions

#### Parameters

Try it out

No parameters

#### Responses

Code

Description

Links

200

OK

Media type

application/json

Controls `Accept` header.

*   Example Value
*   Schema

{
  "subscriptionIds": \[
    {
      "subscriptionId": "string",
      "created": "string"
    }
  \]
}

_No links_

POST

/i3x/subscriptions

Create a new subscription

#### Parameters

Try it out

No parameters

#### Responses

Code

Description

Links

201

Created

Media type

application/json

Controls `Accept` header.

*   Example Value
*   Schema

{
  "subscriptionId": "string",
  "message": "string"
}

_No links_

GET

/i3x/subscriptions/{subscriptionId}

Get subscription details

#### Parameters

Try it out

Name

Description

subscriptionId \*

string

(path)

#### Responses

Code

Description

Links

200

OK

Media type

application/json

Controls `Accept` header.

*   Example Value
*   Schema

{
  "subscriptionId": "string",
  "created": "string",
  "isStreaming": true,
  "queuedUpdates": 0,
  "objects": \[
    "string"
  \]
}

_No links_

404

Not Found

_No links_

DELETE

/i3x/subscriptions/{subscriptionId}

Delete a subscription

#### Parameters

Try it out

Name

Description

subscriptionId \*

string

(path)

#### Responses

Code

Description

Links

200

OK

Media type

application/json

Controls `Accept` header.

*   Example Value
*   Schema

{
  "message": "string",
  "unsubscribed": \[
    "string"
  \],
  "not\_found": \[
    "string"
  \]
}

_No links_

POST

/i3x/subscriptions/{subscriptionId}/register

Register monitored items for a subscription

#### Parameters

Try it out

Name

Description

subscriptionId \*

string

(path)

#### Request body

application/json

*   Example Value
*   Schema

{
  "elementIds": \[
    "string"
  \],
  "maxDepth": 0
}

#### Responses

Code

Description

Links

200

OK

Media type

application/json

Controls `Accept` header.

*   Example Value
*   Schema

{
  "message": "string",
  "totalObjects": 0
}

_No links_

404

Not Found

_No links_

POST

/i3x/subscriptions/{subscriptionId}/unregister

Unregister monitored items from a subscription

#### Parameters

Try it out

Name

Description

subscriptionId \*

string

(path)

#### Request body

application/json

*   Example Value
*   Schema

{
  "elementIds": \[
    "string"
  \],
  "maxDepth": 0
}

#### Responses

Code

Description

Links

200

OK

Media type

application/json

Controls `Accept` header.

*   Example Value
*   Schema

{
  "message": "string"
}

_No links_

404

Not Found

_No links_

GET

/i3x/subscriptions/{subscriptionId}/stream

Stream real-time updates via Server-Sent Events

#### Parameters

Try it out

Name

Description

subscriptionId \*

string

(path)

#### Responses

Code

Description

Links

200

OK

_No links_

404

Not Found

_No links_

POST

/i3x/subscriptions/{subscriptionId}/sync

Poll for pending updates

#### Parameters

Try it out

Name

Description

subscriptionId \*

string

(path)

#### Responses

Code

Description

Links

200

OK

Media type

application/json

Controls `Accept` header.

*   Example Value
*   Schema

\[
  "string"
\]

_No links_

404

Not Found

_No links_

#### Schemas

CreateSubscriptionResponse

DeleteSubscriptionResponse

ElementIdRequest

ElementValue

GetSubscriptionsResponse

HistoryRequest

HttpValidationProblemDetails

I3xNamespace

ObjectInstance

ObjectListRequest

ObjectType

RegisterItemsResponse

RegisterMonitoredItemsRequest

RelatedObjectsRequest

RelationshipType

SubscriptionDetailResponse

SubscriptionSummary

UnregisterItemsResponse

VQT

ValueRequest