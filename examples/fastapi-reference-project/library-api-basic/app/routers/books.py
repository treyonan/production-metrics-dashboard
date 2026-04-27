from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Dict, Any
from app.schemas.book import Book, BookCreate, BookUpdate
from app.exceptions.bookcrudexception import BookCRUDException
from app.crud.book import (
    get_books, get_book, create_book, update_book,
    partial_update_book, delete_book
)
from app.database import get_db

router = APIRouter()

@router.get("/", response_model=List[Book], status_code=status.HTTP_200_OK)
def read_books(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return get_books(db, skip=skip, limit=limit)

@router.get("/{book_id}", response_model=Book, status_code=status.HTTP_200_OK)
def read_book(book_id: int, db: Session = Depends(get_db)):
    book = get_book(db, book_id)
    if not book:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Book not found")
    return book

@router.post("/", response_model=Book, status_code=status.HTTP_201_CREATED)
def create_new_book(book: BookCreate, db: Session = Depends(get_db)):
    try:
        return create_book(db, book)
    except BookCRUDException as e:
        # Map CRUD exceptions to appropriate HTTP status codes
        status_code_map = {
            "foreign_key_violation": status.HTTP_422_UNPROCESSABLE_ENTITY,
            "unique_constraint_violation": status.HTTP_409_CONFLICT,
            "integrity_error": status.HTTP_400_BAD_REQUEST,
            "validation_error": status.HTTP_422_UNPROCESSABLE_ENTITY,
        }
        
        status_code = status_code_map.get(e.error_type, status.HTTP_400_BAD_REQUEST)
        
        raise HTTPException(
            status_code=status_code,
            detail={
                "error": e.error_type,
                "message": e.message
            }
        )

@router.put("/{book_id}", response_model=Book)
def update_existing_book(book_id: int, book: BookUpdate, db: Session = Depends(get_db)):
    try:
        db_book = update_book(db, book_id, book)
        if not db_book:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Book not found"
            )
        return db_book
    except BookCRUDException as e:
        status_code_map = {
            "foreign_key_violation": status.HTTP_422_UNPROCESSABLE_ENTITY,
            "integrity_error": status.HTTP_400_BAD_REQUEST,
        }
        status_code = status_code_map.get(e.error_type, status.HTTP_400_BAD_REQUEST)
        raise HTTPException(status_code=status_code, detail={"error": e.error_type, "message": e.message})


@router.patch("/{book_id}", response_model=Book)
def partially_update_book(book_id: int, book_data: dict, db: Session = Depends(get_db)):
    try:
        db_book = partial_update_book(db, book_id, book_data)
        if not db_book:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Book not found"
            )
        return db_book
    except BookCRUDException as e:
        status_code_map = {
            "foreign_key_violation": status.HTTP_422_UNPROCESSABLE_ENTITY,
            "integrity_error": status.HTTP_400_BAD_REQUEST,
        }
        status_code = status_code_map.get(e.error_type, status.HTTP_400_BAD_REQUEST)
        raise HTTPException(status_code=status_code, detail={"error": e.error_type, "message": e.message})

@router.delete("/{book_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_existing_book(book_id: int, db: Session = Depends(get_db)):
    deleted_book = delete_book(db, book_id)
    if not deleted_book:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Book not found")