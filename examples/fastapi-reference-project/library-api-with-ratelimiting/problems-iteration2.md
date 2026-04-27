# Additions To API with OAuth (Auth0) Implementation
These were the changes that we had to incur in order to implement Rate Limiting to our REST API.

### Note:
This iteration expands on the issues addressed in [Iteration 1](../library-api-with-oauth/problems-iteration1.md).

# Pre-requisites

**None**

# Rate-Limiting for REST APIs
It is a mechanism used to control, with a fixed value, the frequency of requests a client can make to a web server with a specific timeframe.  This helps ensure API stability, prevent abuse (like DDsS attacks), distribute resources fairly among clients of the API and manage infrastructure costs.  It is important to note that fixed-value `Rate Limiting` is considered an implementation of an [API Throtling](https://www.merge.dev/blog/api-throttling-best-practices) approach.  More details on [REST API Rate-Limiting, here](https://www.merge.dev/blog/rest-api-rate-limits).

# Rate-Limiting in Python+FastAPI
A simple, yet elegant, approach to use with FastAPI is a library called [slowapi](https://pypi.org/project/slowapi/).

## Why `slowapi`?
- **Simplicity**
  - Minimal boilerplat. It installs and configures in minutes.
- **Elegance**
  - Applies limits declaratively on routes in your routers, keeeping concerns separated (no code changes to CRUD services, models or schemas)
- **Flexibility**
  - Use in-memory for quick setups or swithch to Redis if needed. It handles `async` / `await` correctly with FastAPI's concurrency model.
- **Best Practice**
  - At the time of this writing, it is widely recommended in the community for FastAPI projects, as it is purpose-built and avoids overkill for most use cases.
  - If your app scales to multiple instances you can easily migrate `slowapi` to use Redis without rewriting code.

## Alternatives?
Alternatives to `slowapi` include:
- fastapi-limiter
- custom Redis implementations

## Changes to the code

### ./app/requirements.txt
- add an entry for `slowapi` library

### ./app/main.py
- Configure the Limiter for the REST API to use, for example, clients IP address
- Pass the `Limiter` to the routes as needed. Se the example for `./router/authors.py`

### ./app/routers/authors.py
- wrapped the creation of the routes with a `.create_authors_router()` method
- make sure to pass in the `Request` parameter since the limiter requires a `request` or `websocket` parameter explicitly defined.