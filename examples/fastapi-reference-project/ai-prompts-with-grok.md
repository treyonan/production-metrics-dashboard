# AI Prompts for Grok
The following prompts were used to help accelerate the creation of this application.

## First Prompt:
This prompt was the very first interaction with [`Grok`](https://grok.com). It did a nice job to help lay out the foundation of this application.

```text
You are an expert Python coder, who specializes on the creation of REST APIs using python, REST-ful principles and REST Maturity Model Level 2 characteristics of REST APIs.
Create for me a REST API to represent logic for a typical Public Library using FastAPI that has the following resources:

- branches
- patrons
- loans
- books
- authors
- library

 
For each of these resources, create a route for

GET to retrieve all instances of a resource
GET to retrieve a specific resource with an {id}
POST to create a new resource
PUT to update an existing resource
PATCH to update specific properties of a resource
DELETE to remove an existing resource

Make sure you include adequate HTTP Status codes
Please, use the clean code approach and modularize the code. Do not put it all in a single long file. Also, provide for me the structure of the directory and where to add different files. Include a basic README.md. I also want to run the app using uvicorn.
Will you also provide a directory structure for the different files/modules.  Also introduce instructions for creating a virtual env in python and how to pip install from a requirements.txt file.
```

It suggested this directory structure:
```text
library_api/
├── app/
│   ├── __init__.py          # Empty file to make 'app' a package
│   ├── main.py              # Entry point for the FastAPI app
│   ├── database.py          # Database setup and session management
│   ├── models/              # SQLAlchemy models for database tables
│   │   ├── __init__.py
│   │   ├── author.py
│   │   ├── book.py
│   │   ├── branch.py
│   │   ├── library.py
│   │   ├── loan.py
│   │   └── patron.py
│   ├── schemas/             # Pydantic schemas for request/response validation
│   │   ├── __init__.py
│   │   ├── author.py
│   │   ├── book.py
│   │   ├── branch.py
│   │   ├── library.py
│   │   ├── loan.py
│   │   └── patron.py
│   ├── crud/                # CRUD operations for each resource
│   │   ├── __init__.py
│   │   ├── author.py
│   │   ├── book.py
│   │   ├── branch.py
│   │   ├── library.py
│   │   ├── loan.py
│   │   └── patron.py
│   └── routers/             # FastAPI routers for API endpoints
│       ├── __init__.py
│       ├── authors.py
│       ├── books.py
│       ├── branches.py
│       ├── libraries.py
│       ├── loans.py
│       └── patrons.py
├── library.db               # SQLite database file (generated on first run)
├── requirements.txt         # Python dependencies
└── README.md                # Project documentation
```

## Second Prompt:
Since there is only a single representation of the County Library System (i.e., this particular county only oversees a single library system with multiple library branches), there was not a need to enable operations (CRUD) for muliple `libraries`.  

This next prompt indicated that to `Grok` and asked it to modify some of the modules that were created with the first prompt.

```text
I decided to use the concept of `library-system` as the resource representing the overall system (e.g., libraries in a county). So that resource will not have the multiple libraries. There will be only one library with multiple branches.
 
Will you adjust the CRUD .py file and the routers .py file to represent this constraint of the system?
```

`Grok` proposed these changes to the original set of modules (code). It also adjusted the `README.md` file content:
```bash
# Adjusted code for the library resource to represent a singleton "library-system".
# Changes:
# - Renamed "library" to "library_system" across models, schemas, crud, routers.
# - In models/branch.py: Updated ForeignKey to "library_system.id"
# - In main.py: Updated import to from app.models import ... library_system
# - In main.py: app.include_router(library_system.router, prefix="/library-system", tags=["library-system"])
# - In database.create_all: Use library_system.Base.metadata.create_all(bind=engine)
# - Directory adjustments:
#   - app/models/library.py -> app/models/library_system.py
#   - app/schemas/library.py -> app/schemas/library_system.py
#   - app/crud/library.py -> app/crud/library_system.py
#   - app/routers/libraries.py -> app/routers/library_system.py
# - Other files (authors, books, etc.) remain unchanged except for the branch model ForeignKey.
# - For the singleton constraint:
#     - No {id} in paths.
#     - GET /library-system: Returns the single instance or 404.
#     - POST /library-system: Creates if none exists, else 400.
#     - PUT /library-system: Updates the existing one (full replace), 404 if none.
#     - PATCH /library-system: Partial update, 404 if none.
#     - DELETE /library-system: Deletes the existing one, 404 if none.
# - Note: Branches still reference library_system.id; when creating a branch, you must provide the ID of the existing library_system (fetch it first via GET).
# - If DELETE is called, branches will have dangling references (in production, add cascading or checks).
```

## Third Prompt:
It was noticed that some of the CRUD operations were not treating the `library-system` concept as a `singleton`. This next prompt was intended to correct those imperfections.

```text
For the library-system/ route, I would like to amend the DELETE route to reflect that the system record that denotes the library system for the county cannot be deleted after it is created. I'd like to always return something "Operation Not Allowed" when invoked and the response determine that the library system has already been initialized.
 
Likewise, the POST operation should only allow 1 library_system record in the DB. So, multiple calls to the POST /library-system should be responded with a "No content" (or better) response.
```

These were the adjustments that `Grok` proposed as the result of that prompt:
```bash
# Adjustments for library-system routes:
# - POST /library-system: If already exists, raise 409 Conflict with detail "Library system already exists" (better than 204, as 204 on POST is non-standard; 409 is appropriate for conflict/already exists).
# - DELETE /library-system: If exists, raise 403 Forbidden with detail "Operation Not Allowed: Library system cannot be deleted once initialized."
#   If not exists, raise 404 Not Found.
# - No actual deletion occurs; removed call to delete_library_system in router.
# - crud/library_system.py: Removed delete_library_system function as it's no longer used.
# - Other files unchanged.
```

## Fourth Prompt:
This should have been added to the original prompt, but it was left out. Leter on, we realized that it was needed.  The useful `.gitignore` file.

This was the prompt:
```text
I forgot to ask for an appropriate .gitignore file for this project. Will you create one for me?
```

`Grok` responded with this (and a file to download.):
```bash
I forgot to ask for an appropriate .gitignore file for this project. Will you create one for me?
```