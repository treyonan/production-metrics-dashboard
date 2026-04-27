from fastapi import FastAPI
from starlette.routing import Mount
from starlette.applications import Starlette
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from app.database import engine
from app.models import (
    author, book, branch,
    library_system as library_system_model,
    loan, patron
)
from app.routers.v1 import (
    authors as v1_authors, books as v1_books, branches as v1_branches,
    library_system as v1_ls_router, loans as v1_loans, patrons as v1_patrons
)
from app.routers.v2 import (
    books as v2_books
)

# REST API Configs
v1_API_PREFIX = "/api/v1"
v1_app = FastAPI(title="Public Library API v1 | Sustainable Evolution | Iteration 3")
v2_API_PREFIX = "/api/v2"
v2_app = FastAPI(title="Public Library API v2 | Sustainable Evolution | Iteration 3")

# v1 API Rate-Limiter Config
v1_limiter = Limiter(key_func=get_remote_address)
v1_app.state.limiter = v1_limiter
v1_app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# v2 API Rate-Limiter Config
v2_limiter = Limiter(key_func=get_remote_address)
v2_app.state.limiter = v2_limiter
v2_app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Create all tables
author.Base.metadata.create_all(bind=engine)  # Still works as Base is shared

# Register Routes for v1
v1_app.include_router(v1_authors.create_authors_router(v1_limiter), prefix=f"{v1_API_PREFIX}/authors", tags=["authors"])
v1_app.include_router(v1_books.create_authors_router(v1_limiter), prefix=f"{v1_API_PREFIX}/books", tags=["books"])
v1_app.include_router(v1_branches.router, prefix=f"{v1_API_PREFIX}/branches", tags=["branches"])
v1_app.include_router(v1_ls_router.router, prefix=f"{v1_API_PREFIX}/library-system", tags=["library-system"])  # Updated
v1_app.include_router(v1_loans.router, prefix=f"{v1_API_PREFIX}/loans", tags=["loans"])
v1_app.include_router(v1_patrons.router, prefix=f"{v1_API_PREFIX}/patrons", tags=["patrons"])

# Register Routes for v2 (tbd)...
v2_app.include_router(v1_authors.create_authors_router(v2_limiter), prefix=f"{v2_API_PREFIX}/authors", tags=["authors"])
v2_app.include_router(v2_books.create_authors_router(v2_limiter), prefix=f"{v2_API_PREFIX}/books", tags=["books"])
v2_app.include_router(v1_branches.router, prefix=f"{v2_API_PREFIX}/branches", tags=["branches"])
v2_app.include_router(v1_ls_router.router, prefix=f"{v2_API_PREFIX}/library-system", tags=["library-system"])  # Updated
v2_app.include_router(v1_loans.router, prefix=f"{v2_API_PREFIX}/loans", tags=["loans"])
v2_app.include_router(v1_patrons.router, prefix=f"{v2_API_PREFIX}/patrons", tags=["patrons"])

# Root app to mount API versions
app = Starlette(routes=[
    Mount(v1_API_PREFIX, app=v1_app),
    Mount(v2_API_PREFIX, app=v2_app)
])