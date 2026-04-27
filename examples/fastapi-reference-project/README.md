# api-workshop
REST API Workshop, created for the 4.0 Solutions workshop series on MCP and Agentic AI

# Public Library REST API

This is a RESTful API for managing a public library system using FastAPI. It includes resources for branches, patrons, loans, books, authors, and library-system (singleton).

## Features
- CRUD operations for each resource.
- Uses SQLAlchemy with SQLite for persistence.
- Pydantic for schema validation.
- Follows REST principles with proper HTTP status codes.
- Library-system is a singleton resource (only one instance allowed).

## Directory Structure
- `app/main.py`: FastAPI app entry point.
- `app/database.py`: Database configuration.
- `app/models/`: SQLAlchemy ORM models.
- `app/schemas/`: Pydantic schemas.
- `app/crud/`: CRUD functions.
- `app/routers/`: API routers.

## Setup
1. Create virtual env: `python -m venv venv`
2. Activate: `venv\Scripts\activate` (Windows) or `source venv/bin/activate` (macOS/Linux)
3. Install deps: `pip install -r requirements.txt`
4. Run: `uvicorn app.main:app --reload`

Access docs at http://127.0.0.1:8000/docs.


## Instructions for Setting Up and Running the App

### Create a Virtual Environment:

Open a terminal in the `library-api-basic/` directory.
Run: `> python -m venv venv`

This creates a virtual environment named venv.

### Activate the Virtual ENV:

On Windows:
```ps
  >  .\venv\Scripts\activate.ps1
```

On macOS/Linux: 
```bash
source venv/bin/activate
```

### Install Dependencies:
With the virtual environment activated, run: 

```bash
pip install -r requirements.txt
```

This installs all required packages from the `requirements.txt` file.


### Run the Application:

With the virtual environment activated, run: `uvicorn app.main:app --reload`

This starts the FastAPI server on `http://127.0.0.1:8000`.
Visit `http://127.0.0.1:8000/docs` in your browser for the interactive Swagger UI to test the API.

## Notes
- Database: SQLite (`library.db`).
- Relationships: Books link to authors; loans link to books, patrons, branches.