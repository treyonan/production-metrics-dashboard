import os
from datetime import datetime, timezone
from typing import Optional
from jose import JWTError, jwt
from jose.jwk import construct
from httpx import AsyncClient
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from async_lru import alru_cache

# Load env vars (install python-dotenv if needed)
from dotenv import load_dotenv
load_dotenv()

AUTH0_DOMAIN = os.getenv("AUTH0_DOMAIN")
API_AUDIENCE = os.getenv("API_AUDIENCE")
ALGORITHM = ["RS256"]
JWK_URL = f"https://{AUTH0_DOMAIN}/.well-known/jwks.json"

security = HTTPBearer(auto_error=False) # Don't auto-raise; handle in dependency

class TokenPayload(BaseModel):
    iss: str
    aud: str
    exp: int
    iat: int
    sub: Optional[str] = None
    client_id: Optional[str] = None # For client-credentials

@alru_cache(maxsize=1)
async def get_jwks() -> dict:
    """Fetch and cache JWKS from Auth0."""
    async with AsyncClient() as client:
        response = await client.get(JWK_URL)
        response.raise_for_status()
        return response.json()

async def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)) -> TokenPayload:
    """Verify JWT and return payload. Raises HTTPException on failure."""
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    try:
        # Get JWKS
        jwks = await get_jwks()
        
        # Find matching key
        kid = jwt.get_unverified_header(credentials.credentials).get("kid")
        signing_key = None
        for key in jwks["keys"]:
            if key["kid"] == kid:
                signing_key = construct(key)
                break
        
        if not signing_key:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token signature")
        
        # Verify JWT
        payload = jwt.decode(
            credentials.credentials,
            signing_key,
            algorithms=ALGORITHM,
            audience=API_AUDIENCE,
            issuer=f"https://{AUTH0_DOMAIN}/",
            options={"verify_signature": True, "verify_aud": True}
        )
        
        # Check expiration (already done by decode, but explicit)
        if datetime.now(timezone.utc) > datetime.fromtimestamp(payload["exp"], timezone.utc):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
        
        return TokenPayload(**payload)
    
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )

# Dependency for routes: Injects verified payload
async def get_current_client(token: TokenPayload = Depends(verify_token)) -> TokenPayload:
    return token