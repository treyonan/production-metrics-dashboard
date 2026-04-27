from fastapi import FastAPI
from app.database import engine
from app.models import (
    author, book, branch,
    library_system as library_system_model,
    loan, patron
)
from app.routers import (
    authors, books, branches,
    library_system as ls_router,
    loans, patrons
)

API_PREFIX = "/api"  # Module-level variable for common API prefix

app = FastAPI(title="Public Library API | OAuth 2.0 Security | Iteration 1")

# Create all tables
author.Base.metadata.create_all(bind=engine)  # Still works as Base is shared

app.include_router(authors.router, prefix=f"{API_PREFIX}/authors", tags=["authors"])
app.include_router(books.router, prefix=f"{API_PREFIX}/books", tags=["books"])
app.include_router(branches.router, prefix=f"{API_PREFIX}/branches", tags=["branches"])
app.include_router(ls_router.router, prefix=f"{API_PREFIX}/library-system", tags=["library-system"])  # Updated
app.include_router(loans.router, prefix=f"{API_PREFIX}/loans", tags=["loans"])
app.include_router(patrons.router, prefix=f"{API_PREFIX}/patrons", tags=["patrons"])