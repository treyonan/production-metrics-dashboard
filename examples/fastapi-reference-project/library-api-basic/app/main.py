from fastapi import FastAPI
from app.database import engine
from app.models import author, book, branch, library_system, loan, patron  # Updated import
from app.routers import authors, books, branches, library_system, loans, patrons  # Updated import

API_PREFIX = "/api"  # Module-level variable for common API prefix

app = FastAPI(title="Public Library API | Basic Model | Iteration 0")

# Create all tables
author.Base.metadata.create_all(bind=engine)  # Still works as Base is shared

app.include_router(authors.router, prefix=f"{API_PREFIX}/authors", tags=["authors"])
app.include_router(books.router, prefix=f"{API_PREFIX}/books", tags=["books"])
app.include_router(branches.router, prefix=f"{API_PREFIX}/branches", tags=["branches"])
app.include_router(library_system.router, prefix=f"{API_PREFIX}/library-system", tags=["library-system"])  # Updated
app.include_router(loans.router, prefix=f"{API_PREFIX}/loans", tags=["loans"])
app.include_router(patrons.router, prefix=f"{API_PREFIX}/patrons", tags=["patrons"])