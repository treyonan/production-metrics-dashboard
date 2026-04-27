# Additions To API with Sustainable Evolvability In-Mind
These were the changes that we had to incur in order to implement Rate Limiting to our REST API.

### Note:
This iteration expands on the issues addressed in [Iteration 2](../library-api-with-ratelimiting/problems-iteration2.md).

# Pre-requisites

**None**

# Versioning


## Changes to the code

### ./app/main.py
- Added reference to Starlette library to support multiple `app.()` instances to carry different versions
- Created a `FastAPI` instance for each of the API versions
- Imported the routers from the `v1` and `v2` route implementations
  - Note that for the `v2` routes, this version of the app is re-using the v1 routes for the endpoints that are not changing.
- Created variables to carry the definitions of `v1` and `v2` API contracts
- Leveraged `Starlette` to mount each of the `FastAPI` instance routes as a new `root` level entry point for the API

### ./app/routers/*.py
- Created 2 new directories udner `app/routers/v1` and `app/routers/v2`)
- Moved all the modules that were under the `app/routers` directory into the `v1` sub-directory
- Created a new `books.py` under `app/routers/v2` sub-directory to interact with a new model for the `books` table

### ./app/schemas/v2_book.py
- Added a new module to describe a change to the `books` table
  - added the column `is_sould_out` with data type `bool` to the `BookBase` model.

## Changes to the Database
These changes were specific to the choice of data store for this example. Recall we are using `sqlite3` as the DB engine for this example REST API. For your case, you will need to manage your DB changes depending on your situation. If you are part of the OT team, your IT team will be able to help you with this.  If you are either IT or OT and you do not see "eye to eye" with your colleagues from the other team, this is an opportunity for you to be the agent of change and start bridging the gap of the IT/OT divide.

### ./requirements.txt
- added the [`alembic`](https://pypi.org/project/alembic/) library
- run `pip install -r requirements.txt`

### Use Alembic to define/document DB changes
After `alembic` is installed:
- `cd..` to the directory for this iteration (iteration 3)
- initialize the `./migrations` directory
  - run: `alembic init migrations`
  - this command creates a ./migrations sub-dir
  - this also creates a file called `alembic.ini`
    - configure `alembic.ini`
      - look for the key for `sqlalchemy.url` and set the value to `sqlite:///{your-db-file}
      - in the case of this workshop you should have:
        - `sqlalchemy.url = sqlite:///library.db`
  - this also create a file called `./migrations/env.py`
    - configure it to add your `./app/models/*`

```python
# Define your app's models...
from app.models import author, book, branch, library_system, loan, patron
from app.database import Base
target_metadata = Base.metadata
```

- create a Database revision to add a new column to the `books` table
  - command: `alembic revision -m {message}`
  - run: `alembic revision -m "Add is_sold_out to books"`
  - this creates/documents a new Database version under the `./migrations/versions` sub-dir
  - this also creates some `{hash}_add_is_sold_out_to_books.py` module to govern the modifications sub-dir for your database
  - make sure these migrations get accepted into your code repo

### Edit the `{hash}-{message}.py` Modules to mange DB upgrade
- edit the auto-generated `*.py` module to describe your change
- in this case we need to define
  - the code to upgrade to the database
  - the code to rollback the changes, should something go bad
- see code samples below

```python
from alembic import op
from sqlalchemy import sa

def upgrade():
  op.add_column('books', sa.Column('is_sold_out', sa.Boolean, nullable=False, server_default=`0`))

def downgrade():
  op.drop_column('books', 'is_sold_out')

```

### Apply the migration
Before applying the migration, you could run the following command to see the evidence onf the change.

If you executed this command:
```bash
# Prior to applying the changes...
sqlite3 library.db ".schema books"

# Output prior to "apply"
CREATE TABLE books (
        id INTEGER NOT NULL,
        title VARCHAR,
        isbn VARCHAR,
        author_id INTEGER,
        PRIMARY KEY (id),
        UNIQUE (isbn),
        FOREIGN KEY(author_id) REFERENCES authors (id)
);
CREATE INDEX ix_books_title ON books (title);
CREATE INDEX ix_books_id ON books (id);

# After "apply"
CREATE TABLE books (
        id INTEGER NOT NULL,
        title VARCHAR,
        isbn VARCHAR,
        author_id INTEGER, is_sold_out BOOLEAN DEFAULT '0' NOT NULL,  # <--- new column
        PRIMARY KEY (id),
        UNIQUE (isbn),
        FOREIGN KEY(author_id) REFERENCES authors (id)
);
CREATE INDEX ix_books_title ON books (title);
CREATE INDEX ix_books_id ON books (id);
```

To apply the migration all that is left to execute is the following command:

```bash
alembic upgrade head
```



