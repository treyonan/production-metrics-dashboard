from fastapi import FastAPI
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
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

# REST API Configs
API_PREFIX = "/api"  # Module-level variable for common API prefix
app = FastAPI(title="Public Library API | Rate Limiting Callers | Iteration 2")

# API Rate-Limiter Config
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Create all tables
author.Base.metadata.create_all(bind=engine)  # Still works as Base is shared

app.include_router(authors.create_authors_router(limiter), prefix=f"{API_PREFIX}/authors", tags=["authors"])
app.include_router(books.create_authors_router(limiter), prefix=f"{API_PREFIX}/books", tags=["books"])
app.include_router(branches.router, prefix=f"{API_PREFIX}/branches", tags=["branches"])
app.include_router(ls_router.router, prefix=f"{API_PREFIX}/library-system", tags=["library-system"])  # Updated
app.include_router(loans.router, prefix=f"{API_PREFIX}/loans", tags=["loans"])
app.include_router(patrons.router, prefix=f"{API_PREFIX}/patrons", tags=["patrons"])