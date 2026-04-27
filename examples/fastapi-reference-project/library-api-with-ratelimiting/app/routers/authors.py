from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from typing import List, Dict, Any
from app.schemas.author import Author, AuthorCreate, AuthorUpdate
from app.crud.author import (
    get_authors, get_author, create_author, update_author,
    partial_update_author, delete_author
)
from app.database import get_db
from app.security import get_current_client, TokenPayload # Add this to protect desired endpoints

def create_authors_router(limiter):
    router = APIRouter()

    @router.get("/", response_model=List[Author], status_code=status.HTTP_200_OK)
    @limiter.limit("5/1minute")
    def read_authors(request: Request, skip: int = 0, limit: int = 100, db: Session = Depends(get_db), current_client: TokenPayload = Depends(get_current_client)):
        return get_authors(db, skip=skip, limit=limit)

    @router.get("/{author_id}", response_model=Author, status_code=status.HTTP_200_OK)
    def read_author(author_id: int, db: Session = Depends(get_db)):
        author = get_author(db, author_id)
        if not author:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Author not found")
        return author

    @router.post("/", response_model=Author, status_code=status.HTTP_201_CREATED)
    def create_new_author(author: AuthorCreate, db: Session = Depends(get_db)):
        return create_author(db, author)

    @router.put("/{author_id}", response_model=Author, status_code=status.HTTP_200_OK)
    def update_existing_author(author_id: int, author: AuthorUpdate, db: Session = Depends(get_db)):
        updated_author = update_author(db, author_id, author)
        if not updated_author:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Author not found")
        return updated_author

    @router.patch("/{author_id}", response_model=Author, status_code=status.HTTP_200_OK)
    def partial_update_existing_author(author_id: int, author_data: Dict[str, Any], db: Session = Depends(get_db)):
        updated_author = partial_update_author(db, author_id, author_data)
        if not updated_author:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Author not found")
        return updated_author

    @router.delete("/{author_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_existing_author(author_id: int, db: Session = Depends(get_db)):
        deleted_author = delete_author(db, author_id)
        if not deleted_author:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Author not found")

    return router        