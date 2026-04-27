# Additions To Basic-API
These were the changes that we had to incur in order to implement OAuth 2.0, `client-credentials` flow (a.k.a. machine-to-machine, m2m). In this case we are using [Auth0.com](https://auth0.com) as the provider of the identity service.

### Note:
This iteration expands on the issues resolved in [Iteration 0](../library-api-basic/problems-iteration0.md).

# Pre-requisites

## Auth0.com Account Sign-Up
Go to [www.auth0.com/pricing](https://auth0.com/pricing) and selec the `Free Tier`.  If you want to register with a custom domain name, you'll need to verify your account with a valid Credit Card.

## Once your Account is Created
Use your account and customize OAuth for your API.  Use [this guide](https://auth0.com/docs/get-started/auth0-overview/set-up-apis) as a reference setup protection for your API.

### Important:
For the purpose of this exercise, ensure that your `JSON Web Token (JWT) Signing Algorithm` is set to `RS256`.

# Code Changes

## `./requirements.txt`
- added a few libraries to support the access to `auth0.com` services

## `./app/main.py`
- Reaccommodated the `from` / `import` statements to ensure the `library_system` name did not collide across sections of the namespace
- Changed the `API` title to help differentiate when running multiple instances

## `./app/security.py`  * new file *
This file is responsible for
- loading ENV VARs from `.env` or `system VARs`
- define a few module variables (e.g., `AUTH0_DOMIAN`, `AUTH0_AUDIENCE`, etc.)
- Establish `HTTPBearer` and `TokenPayload` data type
- Define functions for
  - Obtain the well-know JASON Web Key Set (`JWKS`)
  - Verify the Token
  - Define the dependency method injected at each of the protected routes

## `./app/routers/authors.py`




