# Flow API

![Flow Software](./help/logo.svg)

Select a definitionv1

## Flow API v1 

OAS 3.0

[/flow-software/flow/instances/80D1092C-EFBF-4592-9425-C85ABE2EC7FB/server/api/v1/docs.json](/flow-software/flow/instances/80D1092C-EFBF-4592-9425-C85ABE2EC7FB/server/api/v1/docs.json)

Documents for version 1 of the Flow API

[Flow Support - Website](https://support.flow-software.com/)

Servers

/flow-software/flow/instances/80d1092c-efbf-4592-9425-c85abe2ec7fb/server

### Config

GET

/api/v1/config/enumerationgroups

Returns all enumeration groups, but excludes their ordinals.

#### Parameters

Try it out

No parameters

#### Responses

Code

Description

Links

200

Success

_No links_

204

No Content

_No links_

400

Bad Request

_No links_

401

Not Authorized

_No links_

403

Not Licensed

_No links_

404

Not Found

_No links_

GET

/api/v1/config/enumerationgroups/{id}

Returns the specified enumeration group, including its ordinals.

#### Parameters

Try it out

Name

Description

id \*

integer($int32)

(path)

Enumeration group id

#### Responses

Code

Description

Links

200

Success

_No links_

204

No Content

_No links_

400

Bad Request

_No links_

401

Not Authorized

_No links_

403

Not Licensed

_No links_

404

Not Found

_No links_

GET

/api/v1/config/enumerations

Returns all enumerations, but excludes their ordinals.

#### Parameters

Try it out

No parameters

#### Responses

Code

Description

Links

200

Success

_No links_

204

No Content

_No links_

400

Bad Request

_No links_

401

Not Authorized

_No links_

403

Not Licensed

_No links_

404

Not Found

_No links_

GET

/api/v1/config/enumerations/{id}

Returns the specified enumeration, including its ordinals.

#### Parameters

Try it out

Name

Description

id \*

integer($int32)

(path)

Enumeration id

#### Responses

Code

Description

Links

200

Success

_No links_

204

No Content

_No links_

400

Bad Request

_No links_

401

Not Authorized

_No links_

403

Not Licensed

_No links_

404

Not Found

_No links_

GET

/api/v1/config/calendars

Returns all calendars, but excludes their shift details.

#### Parameters

Try it out

No parameters

#### Responses

Code

Description

Links

200

Success

_No links_

204

No Content

_No links_

400

Bad Request

_No links_

401

Not Authorized

_No links_

403

Not Licensed

_No links_

404

Not Found

_No links_

GET

/api/v1/config/calendars/{id}

Returns the specified calendar, its shift details.

#### Parameters

Try it out

Name

Description

id \*

integer($int32)

(path)

Calendar id

#### Responses

Code

Description

Links

200

Success

_No links_

204

No Content

_No links_

400

Bad Request

_No links_

401

Not Authorized

_No links_

403

Not Licensed

_No links_

404

Not Found

_No links_

GET

/api/v1/config/calendars/{id}/shifts

Returns the shift details for the specified calendar

#### Parameters

Try it out

Name

Description

id \*

integer($int32)

(path)

Calendar id

#### Responses

Code

Description

Links

200

Success

_No links_

204

No Content

_No links_

400

Bad Request

_No links_

401

Not Authorized

_No links_

403

Not Licensed

_No links_

404

Not Found

_No links_

POST

/api/v1/config/calendars/{id}/shifts

Create a new shift pattern with the specified shift scheme

#### Parameters

Try it out

Name

Description

id \*

integer($int32)

(path)

Calendar id

#### Request body

application/json-patch+jsonapplication/jsontext/jsonapplication/\*+json

Shift scheme configuration of the new shift pattern.

*   Example Value
*   Schema

```json
{
  "id": 0,
  "dateTime": "2026-01-21T17:43:23.778Z",
  "intervals": [
    {
      "shift": {
        "name": "string",
        "color": "string"
      },
      "intervalStart": 0,
      "intervalCount": 0
    }
  ]
}
```

#### Responses

Code

Description

Links

200

Success

_No links_

204

No Content

_No links_

400

Bad Request

_No links_

401

Not Authorized

_No links_

403

Not Licensed

_No links_

404

Not Found

_No links_

DELETE

/api/v1/config/calendars/{id}/shifts

Delete the specified shift pattern if no time periods exists.

#### Parameters

Try it out

Name

Description

id \*

integer($int32)

(path)

Calendar id

schemeid

integer($int32)

(query)

Shift Scheme id

#### Responses

Code

Description

Links

200

Success

_No links_

204

No Content

_No links_

400

Bad Request

_No links_

401

Not Authorized

_No links_

403

Not Licensed

_No links_

404

Not Found

_No links_

### Data

GET

/api/v1/data/events

Returns event data for the specified event id(s).

Start and end times must be specified in ISO-8601 formats (e.g. YYYY-MM-DDTHH:mm:ss.mmmZ for UTC and YYYY-MM-DDTHH:mm:ss.mmm for local). If the start and end time parameters are not specified, the last event period will be returned.

#### Parameters

Try it out

Name

Description

start

string($date-time)

(query)

Start time.

end

string($date-time)

(query)

End time. Defaults to now.

id

array\[integer\]

(query)

Event id. _Can be specified multiple times to return data for more than one event._

templateid

array\[integer\]

(query)

Specify event template id(s) to return data for all related instantiated events. _Can be specified multiple times to return data for more than one event._

count

integer($int32)

(query)

Specify the period count when using eventid or calendarid.

preferred

boolean

(query)

Return only preferred data.

_Default value_ : true

\--truefalse

attributes

boolean

(query)

Include event attribute data.

_Default value_ : true

\--truefalse

comments

boolean

(query)

Include comment data.

_Default value_ : false

\--truefalse

users

boolean

(query)

Include user data.

_Default value_ : false

\--truefalse

limit

integer($int32)

(query)

Limit number of data points returned.

_Default value_ : 1000

#### Responses

Code

Description

Links

200

Success

_No links_

204

No Content

_No links_

400

Bad Request

_No links_

401

Not Authorized

_No links_

403

Not Licensed

_No links_

404

Not Found

_No links_

GET

/api/v1/data/measures

Returns measure data for the specified measure id(s).

Start and end times must be specified in ISO-8601 formats (e.g. YYYY-MM-DDTHH:mm:ss.mmmZ for UTC and YYYY-MM-DDTHH:mm:ss.mmm for local). If the start and end time parameters are not specified, the last measure value will be returned.

#### Parameters

Try it out

Name

Description

start

string($date-time)

(query)

Start time.

end

string($date-time)

(query)

End time. Defaults to now.

id

array\[integer\]

(query)

Measure id. _Can be specified multiple times to return data for more than one measure._

templateid

array\[integer\]

(query)

Specify measure template id(s) to return data for all related instantiated measures. _Can be specified multiple times to return data for more than one measure._

preferred

boolean

(query)

Return only preferred data.

_Default value_ : true

\--truefalse

eventPeriods

boolean

(query)

Return measures’ event period data.

_Default value_ : false

\--truefalse

eventid

integer($int32)

(query)

Specify event context's id

calendarid

integer($int32)

(query)

Specify calendar context's id

count

integer($int32)

(query)

Specify the period count when using eventid or calendarid.

comments

boolean

(query)

Include comment data.

_Default value_ : false

\--truefalse

exceptions

boolean

(query)

Include limit exception data.

_Default value_ : false

\--truefalse

attributes

boolean

(query)

Include attribute context.

_Default value_ : false

\--truefalse

users

boolean

(query)

Include user data.

_Default value_ : false

\--truefalse

limit

integer($int32)

(query)

Limit number of data points returned.

_Default value_ : 1000

#### Responses

Code

Description

Links

200

Success

_No links_

204

No Content

_No links_

400

Bad Request

_No links_

401

Not Authorized

_No links_

403

Not Licensed

_No links_

404

Not Found

_No links_

GET

/api/v1/data/tags

Returns tag data for the specified measure id(s).

Start and end times must be specified in ISO-8601 formats (e.g. YYYY-MM-DDTHH:mm:ss.mmmZ for UTC and YYYY-MM-DDTHH:mm:ss.mmm for local). If the start and end time parameters are not specified, the last tag value will be returned.

The properties field is used with certain aggregation types like 'Counter'. It is a string lookup and can contain the properties, 'Comparator', 'State', 'Rollover', and 'Deadband'.

When no aggregation type is specified the raw data is returned. However, when aggregation is specified, an event or calendar id can be used to return aggregations for the determined periods. Alternatively the resolution can be used to retrieve aggregates for the resolution duration.

#### Parameters

Try it out

Name

Description

start

string($date-time)

(query)

Start time.

end

string($date-time)

(query)

End time. Defaults to now.

tagid

array\[integer\]

(query)

Specify tag id(s) to return data for. _Can be specified multiple times to return data for more than one tag._

templateid

array\[integer\]

(query)

Specify tag template id(s) to return data for all related instantiated measures. _Can be specified multiple times to return data for more than one tag._

aggregation

string

(query)

Aggregate the raw data using this aggregation type.

_Available values_ : sum, average, minimum, maximum, counter, range, delta, first, last, count, timeInState, variance, standardDeviation

\--sumaverageminimummaximumcounterrangedeltafirstlastcounttimeInStatevariancestandardDeviation

properties

object

(query)

Aggregation peroperties to be used.

{ "additionalProp1": "string", "additionalProp2": "string", "additionalProp3": "string" }

resolution

integer($int32)

(query)

Specify the period resolution in milliseconds.

eventid

integer($int32)

(query)

Specify event's id

calendarid

integer($int32)

(query)

Specify calendar's id

interval

string

(query)

Specify the interval type to use when using calendar periods. _Default value : Hourly_

_Available values_ : timestamp, minutely, hourly, shiftly, daily, weekly, monthly, quarterly, yearly

\--timestampminutelyhourlyshiftlydailyweeklymonthlyquarterlyyearly

count

integer($int32)

(query)

Specify the period count when using eventid or calendarid.

limit

integer($int32)

(query)

Limit number of data points returned.

_Default value_ : 1000

#### Responses

Code

Description

Links

200

Success

_No links_

204

No Content

_No links_

400

Bad Request

_No links_

401

Not Authorized

_No links_

403

Not Licensed

_No links_

404

Not Found

_No links_

### Information

GET

/api/v1/information/charts

Returns charts for the specified id(s).

Returns all charts if the id parameter is not specified.

#### Parameters

Try it out

Name

Description

id

array\[integer\]

(query)

Chart id. _Can be specified multiple times to return information for more than one chart._

#### Responses

Code

Description

Links

200

Success

_No links_

204

No Content

_No links_

400

Bad Request

_No links_

401

Not Authorized

_No links_

403

Not Licensed

_No links_

404

Not Found

_No links_

GET

/api/v1/information/charts/{id}/measures

Returns all measures for a chart with the specified id.

#### Parameters

Try it out

Name

Description

id \*

integer($int32)

(path)

Chart id.

retrieval

array\[string\]

(query)

Retrieval type. _Defaults to all._

_Available values_ : manual, retrieved, aggregated, calculated, replicated

\--manualretrievedaggregatedcalculatedreplicated

interval

array\[string\]

(query)

Interval type. _Defaults to all._

_Available values_ : timestamp, minutely, hourly, shiftly, daily, weekly, monthly, quarterly, yearly

\--timestampminutelyhourlyshiftlydailyweeklymonthlyquarterlyyearly

config

boolean

(query)

Use configured or rendered measures. _Defaults to false._

_Default value_ : false

\--truefalse

#### Responses

Code

Description

Links

200

Success

_No links_

204

No Content

_No links_

400

Bad Request

_No links_

401

Not Authorized

_No links_

403

Not Licensed

_No links_

404

Not Found

_No links_

GET

/api/v1/information/charts/{id}/events

Returns all events for a chart with the specified id.

#### Parameters

Try it out

Name

Description

id \*

integer($int32)

(path)

Chart id.

config

boolean

(query)

Use configured or rendered measures. _Defaults to false._

_Default value_ : false

\--truefalse

#### Responses

Code

Description

Links

200

Success

_No links_

204

No Content

_No links_

400

Bad Request

_No links_

401

Not Authorized

_No links_

403

Not Licensed

_No links_

404

Not Found

_No links_

GET

/api/v1/information/charts/usage

Returns the usage statistics per chart for the specified id(s).

Start and end times must be specified in ISO-8601 formats (e.g. YYYY-MM-DDTHH:mm:ss.mmmZ for UTC and YYYY-MM-DDTHH:mm:ss.mmm for local). The statistics consist of the user and the amount of times the chart was opened over the specified time range

#### Parameters

Try it out

Name

Description

ids

array\[integer\]

(query)

Chart id. _Can be specified multiple times to return information for more than one chart._

start

string($date-time)

(query)

Start time.

end

string($date-time)

(query)

End time. Defaults to now.

#### Responses

Code

Description

Links

200

Success

_No links_

204

No Content

_No links_

400

Bad Request

_No links_

401

Not Authorized

_No links_

403

Not Licensed

_No links_

404

Not Found

_No links_

GET

/api/v1/information/dashboards

Returns dashboards for the specified id(s).

Returns all dashboards if the id parameter is not specified.

#### Parameters

Try it out

Name

Description

id

array\[integer\]

(query)

Dashboard id. _Can be specified multiple times to return information for more than one dashboard._

#### Responses

Code

Description

Links

200

Success

_No links_

204

No Content

_No links_

400

Bad Request

_No links_

401

Not Authorized

_No links_

403

Not Licensed

_No links_

404

Not Found

_No links_

GET

/api/v1/information/dashboards/{id}/charts

Returns charts contained by the specified dashboard.

#### Parameters

Try it out

Name

Description

id \*

integer($int32)

(path)

Dashboard id

embedded

boolean

(query)

Include charts used in the dashboard

_Default value_ : false

\--truefalse

#### Responses

Code

Description

Links

200

Success

_No links_

204

No Content

_No links_

400

Bad Request

_No links_

401

Not Authorized

_No links_

403

Not Licensed

_No links_

404

Not Found

_No links_

GET

/api/v1/information/folders

Returns folders for the specified id(s).

Returns all folders if the id parameter is not specified.

#### Parameters

Try it out

Name

Description

id

array\[integer\]

(query)

Folder id. _Can be specified multiple times to return information for more than one folder._

#### Responses

Code

Description

Links

200

Success

_No links_

204

No Content

_No links_

400

Bad Request

_No links_

401

Not Authorized

_No links_

403

Not Licensed

_No links_

404

Not Found

_No links_

GET

/api/v1/information/folders/{id}/folders

Returns folders contained by the specified folder.

#### Parameters

Try it out

Name

Description

id \*

integer($int32)

(path)

Folder id

#### Responses

Code

Description

Links

200

Success

_No links_

204

No Content

_No links_

400

Bad Request

_No links_

401

Not Authorized

_No links_

403

Not Licensed

_No links_

404

Not Found

_No links_

GET

/api/v1/information/folders/{id}/charts

Returns charts contained by the specified folder.

#### Parameters

Try it out

Name

Description

id \*

integer($int32)

(path)

Folder id

#### Responses

Code

Description

Links

200

Success

_No links_

204

No Content

_No links_

400

Bad Request

_No links_

401

Not Authorized

_No links_

403

Not Licensed

_No links_

404

Not Found

_No links_

GET

/api/v1/information/folders/{id}/dashboards

Returns dashboards contained by the specified folder.

#### Parameters

Try it out

Name

Description

id \*

integer($int32)

(path)

Folder id

#### Responses

Code

Description

Links

200

Success

_No links_

204

No Content

_No links_

400

Bad Request

_No links_

401

Not Authorized

_No links_

403

Not Licensed

_No links_

404

Not Found

_No links_

### Model

GET

/api/v1/model/events

Returns events for the specified id(s).

Returns all events if the id parameter is not specified.

#### Parameters

Try it out

Name

Description

id

array\[integer\]

(query)

Event id

attributes

boolean

(query)

Include event attributes.

_Default value_ : true

\--truefalse

fields

boolean

(query)

Include model attributes.

_Default value_ : false

\--truefalse

#### Responses

Code

Description

Links

200

Success

_No links_

204

No Content

_No links_

400

Bad Request

_No links_

401

Not Authorized

_No links_

403

Not Licensed

_No links_

404

Not Found

_No links_

GET

/api/v1/model/events/{id}/measures

Returns measures contained by the specified event.

#### Parameters

Try it out

Name

Description

id \*

integer($int32)

(path)

Event id

retrieval

array\[string\]

(query)

Retrieval type. _Defaults to all._

_Available values_ : manualEntry, retrieved, aggregation, calculation, replicated

\--manualEntryretrievedaggregationcalculationreplicated

interval

array\[string\]

(query)

Interval type. _Defaults to all._

_Available values_ : timestamp, minutely, hourly, shiftly, daily, weekly, monthly, quarterly, yearly

\--timestampminutelyhourlyshiftlydailyweeklymonthlyquarterlyyearly

fields

boolean

(query)

Include model attributes.

_Default value_ : false

\--truefalse

#### Responses

Code

Description

Links

200

Success

_No links_

204

No Content

_No links_

400

Bad Request

_No links_

401

Not Authorized

_No links_

403

Not Licensed

_No links_

404

Not Found

_No links_

GET

/api/v1/model/folders

Returns folders for the specified id(s).

Returns all folders if the id parameter is not specified.

#### Parameters

Try it out

Name

Description

id

array\[integer\]

(query)

Folder id. _Can be specified multiple times to return information for more than one folder._

fields

boolean

(query)

Include model attributes.

_Default value_ : false

\--truefalse

#### Responses

Code

Description

Links

200

Success

_No links_

204

No Content

_No links_

400

Bad Request

_No links_

401

Not Authorized

_No links_

403

Not Licensed

_No links_

404

Not Found

_No links_

GET

/api/v1/model/folders/{id}/folders

Returns folders contained by the specified folder.

#### Parameters

Try it out

Name

Description

id \*

integer($int32)

(path)

Folder id

fields

boolean

(query)

Include model attributes.

_Default value_ : false

\--truefalse

#### Responses

Code

Description

Links

200

Success

_No links_

204

No Content

_No links_

400

Bad Request

_No links_

401

Not Authorized

_No links_

403

Not Licensed

_No links_

404

Not Found

_No links_

GET

/api/v1/model/folders/{id}/events

Returns events contained by the specified folder.

#### Parameters

Try it out

Name

Description

id \*

integer($int32)

(path)

Folder id

attributes

boolean

(query)

Include event attributes.

_Default value_ : true

\--truefalse

fields

boolean

(query)

Include model attributes.

_Default value_ : false

\--truefalse

#### Responses

Code

Description

Links

200

Success

_No links_

204

No Content

_No links_

400

Bad Request

_No links_

401

Not Authorized

_No links_

403

Not Licensed

_No links_

404

Not Found

_No links_

GET

/api/v1/model/folders/{id}/metrics

Returns metrics contained by the specified folder.

#### Parameters

Try it out

Name

Description

id \*

integer($int32)

(path)

Folder id

fields

boolean

(query)

Include model attributes.

_Default value_ : false

\--truefalse

#### Responses

Code

Description

Links

200

Success

_No links_

204

No Content

_No links_

400

Bad Request

_No links_

401

Not Authorized

_No links_

403

Not Licensed

_No links_

404

Not Found

_No links_

GET

/api/v1/model/measures

Returns measures for the specified id(s).

Returns all measures if the id parameter is not specified.

#### Parameters

Try it out

Name

Description

retrieval

array\[string\]

(query)

Retrieval type. _Defaults to all._

_Available values_ : manual, retrieved, aggregated, calculated, replicated

\--manualretrievedaggregatedcalculatedreplicated

interval

array\[string\]

(query)

Interval type. _Defaults to all._

_Available values_ : timestamp, minutely, hourly, shiftly, daily, weekly, monthly, quarterly, yearly

\--timestampminutelyhourlyshiftlydailyweeklymonthlyquarterlyyearly

id

array\[integer\]

(query)

Measure id

fields

boolean

(query)

Include model attributes.

_Default value_ : false

\--truefalse

metadata

boolean

(query)

Include metadata, eg. retrieval properties and dependents.

_Default value_ : false

\--truefalse

#### Responses

Code

Description

Links

200

Success

_No links_

204

No Content

_No links_

400

Bad Request

_No links_

401

Not Authorized

_No links_

403

Not Licensed

_No links_

404

Not Found

_No links_

GET

/api/v1/model/metrics

Returns metrics for the specified id(s).

Returns all metrics if the id parameter is not specified.

#### Parameters

Try it out

Name

Description

id

array\[integer\]

(query)

Metric id. _Can be specified multiple times to return information for more than one metric._

fields

boolean

(query)

Include model attributes.

_Default value_ : false

\--truefalse

#### Responses

Code

Description

Links

200

Success

_No links_

204

No Content

_No links_

400

Bad Request

_No links_

401

Not Authorized

_No links_

403

Not Licensed

_No links_

404

Not Found

_No links_

GET

/api/v1/model/metrics/{id}/measures

Returns measures contained by the specified metric.

#### Parameters

Try it out

Name

Description

id \*

integer($int32)

(path)

Metric id

retrieval

array\[string\]

(query)

Retrieval type. _Default to all._

_Available values_ : manual, retrieved, aggregated, calculated, replicated

\--manualretrievedaggregatedcalculatedreplicated

interval

array\[string\]

(query)

Interval type. _Default to all._

_Available values_ : timestamp, minutely, hourly, shiftly, daily, weekly, monthly, quarterly, yearly

\--timestampminutelyhourlyshiftlydailyweeklymonthlyquarterlyyearly

fields

boolean

(query)

Include model attributes.

_Default value_ : false

\--truefalse

#### Responses

Code

Description

Links

200

Success

_No links_

204

No Content

_No links_

400

Bad Request

_No links_

401

Not Authorized

_No links_

403

Not Licensed

_No links_

404

Not Found

_No links_

### Search

GET

/api/v1/search

The search endpoint is used for model discovery. Use it to find model objects (e.g. measures or events), template objects or information objects (e.g. dashboards or charts).

#### Parameters

Try it out

Name

Description

query \*

array\[string\]

(query)

Search string treated as “contains”. _Can be specified multiple times to seach for multiple criteria_

type

array\[string\]

(query)

Type of objects to search for. _Defaults to all object types._

_Available values_ : folder, templateFolder, metric, templateMetric, event, templateEvent, measure, templateMeasure, informationFolder, chart, form, dashboard, dashboardLoop

\--foldertemplateFoldermetrictemplateMetriceventtemplateEventmeasuretemplateMeasureinformationFolderchartformdashboarddashboardLoop

match

array\[string\]

(query)

Properties of objects to search within. _Defaults to all property options._

_Available values_ : name, description, property, field

\--namedescriptionpropertyfield

limit

integer($int32)

(query)

Limit results returned per page.

_Default value_ : 1000

page

integer($int32)

(query)

Specify the page of results to be returned. This works in combination with the “limit” parameter.

_Default value_ : 1

#### Responses

Code

Description

Links

200

Success

_No links_

204

No Content

_No links_

400

Bad Request

_No links_

401

Not Authorized

_No links_

403

Not Licensed

_No links_

404

Not Found

_No links_

### Template

GET

/api/v1/template/events

Returns events for the specified id(s).

Returns all events if the id parameter is not specified.

#### Parameters

Try it out

Name

Description

id

array\[integer\]

(query)

Event id

attributes

boolean

(query)

Include event attributes.

_Default value_ : true

\--truefalse

fields

boolean

(query)

Include model attributes.

_Default value_ : false

\--truefalse

#### Responses

Code

Description

Links

200

Success

_No links_

204

No Content

_No links_

400

Bad Request

_No links_

401

Not Authorized

_No links_

403

Not Licensed

_No links_

404

Not Found

_No links_

GET

/api/v1/template/events/{id}/measures

Returns measures contained by the specified event.

#### Parameters

Try it out

Name

Description

id \*

integer($int32)

(path)

Event id

retrieval

array\[string\]

(query)

Retrieval type. _Defaults to all._

_Available values_ : manualEntry, retrieved, aggregation, calculation, replicated

\--manualEntryretrievedaggregationcalculationreplicated

interval

array\[string\]

(query)

Interval type. _Defaults to all._

_Available values_ : timestamp, minutely, hourly, shiftly, daily, weekly, monthly, quarterly, yearly

\--timestampminutelyhourlyshiftlydailyweeklymonthlyquarterlyyearly

fields

boolean

(query)

Include model attributes.

_Default value_ : false

\--truefalse

#### Responses

Code

Description

Links

200

Success

_No links_

204

No Content

_No links_

400

Bad Request

_No links_

401

Not Authorized

_No links_

403

Not Licensed

_No links_

404

Not Found

_No links_

GET

/api/v1/template/folders

Returns folders for the specified id(s).

Returns all folders if the id parameter is not specified.

#### Parameters

Try it out

Name

Description

id

array\[integer\]

(query)

Folder id. _Can be specified multiple times to return information for more than one folder._

fields

boolean

(query)

Include model attributes.

_Default value_ : false

\--truefalse

#### Responses

Code

Description

Links

200

Success

_No links_

204

No Content

_No links_

400

Bad Request

_No links_

401

Not Authorized

_No links_

403

Not Licensed

_No links_

404

Not Found

_No links_

GET

/api/v1/template/folders/{id}/folders

Returns folders contained by the specified folder.

#### Parameters

Try it out

Name

Description

id \*

integer($int32)

(path)

Folder id

fields

boolean

(query)

Include model attributes.

_Default value_ : false

\--truefalse

#### Responses

Code

Description

Links

200

Success

_No links_

204

No Content

_No links_

400

Bad Request

_No links_

401

Not Authorized

_No links_

403

Not Licensed

_No links_

404

Not Found

_No links_

GET

/api/v1/template/folders/{id}/events

Returns events contained by the specified folder.

#### Parameters

Try it out

Name

Description

id \*

integer($int32)

(path)

Folder id

attributes

boolean

(query)

Include event attributes.

_Default value_ : true

\--truefalse

fields

boolean

(query)

Include model attributes.

_Default value_ : false

\--truefalse

#### Responses

Code

Description

Links

200

Success

_No links_

204

No Content

_No links_

400

Bad Request

_No links_

401

Not Authorized

_No links_

403

Not Licensed

_No links_

404

Not Found

_No links_

GET

/api/v1/template/folders/{id}/metrics

Returns metrics contained by the specified folder.

#### Parameters

Try it out

Name

Description

id \*

integer($int32)

(path)

Folder id

fields

boolean

(query)

Include model attributes.

_Default value_ : false

\--truefalse

#### Responses

Code

Description

Links

200

Success

_No links_

204

No Content

_No links_

400

Bad Request

_No links_

401

Not Authorized

_No links_

403

Not Licensed

_No links_

404

Not Found

_No links_

GET

/api/v1/template/measures

Returns measures for the specified id(s).

Returns all measures if the id parameter is not specified.

#### Parameters

Try it out

Name

Description

retrieval

array\[string\]

(query)

Retrieval type. _Defaults to all._

_Available values_ : manual, retrieved, aggregated, calculated, replicated

\--manualretrievedaggregatedcalculatedreplicated

interval

array\[string\]

(query)

Interval type. _Defaults to all._

_Available values_ : timestamp, minutely, hourly, shiftly, daily, weekly, monthly, quarterly, yearly

\--timestampminutelyhourlyshiftlydailyweeklymonthlyquarterlyyearly

id

array\[integer\]

(query)

Measure id

fields

boolean

(query)

Include model attributes.

_Default value_ : false

\--truefalse

metadata

boolean

(query)

Include metadata, eg. retrieval properties and dependents.

_Default value_ : false

\--truefalse

#### Responses

Code

Description

Links

200

Success

_No links_

204

No Content

_No links_

400

Bad Request

_No links_

401

Not Authorized

_No links_

403

Not Licensed

_No links_

404

Not Found

_No links_

GET

/api/v1/template/metrics

Returns metrics for the specified id(s).

Returns all metrics if the id parameter is not specified.

#### Parameters

Try it out

Name

Description

id

array\[integer\]

(query)

Metric id. _Can be specified multiple times to return information for more than one metric._

fields

boolean

(query)

Include model attributes.

_Default value_ : false

\--truefalse

#### Responses

Code

Description

Links

200

Success

_No links_

204

No Content

_No links_

400

Bad Request

_No links_

401

Not Authorized

_No links_

403

Not Licensed

_No links_

404

Not Found

_No links_

GET

/api/v1/template/metrics/{id}/measures

Returns measures contained by the specified metric.

#### Parameters

Try it out

Name

Description

id \*

integer($int32)

(path)

Metric id

retrieval

array\[string\]

(query)

Retrieval type. _Default to all._

_Available values_ : manual, retrieved, aggregated, calculated, replicated

\--manualretrievedaggregatedcalculatedreplicated

interval

array\[string\]

(query)

Interval type. _Default to all._

_Available values_ : timestamp, minutely, hourly, shiftly, daily, weekly, monthly, quarterly, yearly

\--timestampminutelyhourlyshiftlydailyweeklymonthlyquarterlyyearly

fields

boolean

(query)

Include model attributes.

_Default value_ : false

\--truefalse

#### Responses

Code

Description

Links

200

Success

_No links_

204

No Content

_No links_

400

Bad Request

_No links_

401

Not Authorized

_No links_

403

Not Licensed

_No links_

404

Not Found

_No links_