from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.models.book import Book
from app.schemas.v2_book import BookCreate, BookUpdate
from app.exceptions.bookcrudexception import BookCRUDException

def get_books(db: Session, skip: int = 0, limit: int = 100):
    return db.query(Book).offset(skip).limit(limit).all()

def get_book(db: Session, book_id: int):
    return db.query(Book).filter(Book.id == book_id).first()

def create_book(db: Session, book: BookCreate):
    try:
        db_book = Book(**book.model_dump())
        db.add(db_book)
        db.commit()
        db.refresh(db_book)
        return db_book
    except IntegrityError as e:
        db.rollback()
        
        # Check if it's a foreign key constraint violation
        error_msg = str(e.args).lower()
        if "foreign key constraint failed" in error_msg:
            if "author_id" in e.statement:
                raise BookCRUDException(
                    message="Invalid author_id: Author does not exist",
                    error_type="foreign_key_violation"
                )
            else:
                raise BookCRUDException(
                    message="Referenced entity does not exist",
                    error_type="foreign_key_violation"
                )
        
        # Check if it's a unique constraint violation
        elif "unique constraint" in error_msg or "duplicate" in error_msg:
            raise BookCRUDException(
                message="Book with this information already exists",
                error_type="unique_constraint_violation"
            )
        
        # Generic integrity error
        else:
            raise BookCRUDException(
                message="Data integrity violation",
                error_type="integrity_error"
            )

def update_book(db: Session, book_id: int, book: BookUpdate):
    try:
        db_book = get_book(db, book_id)
        if not db_book:
            return None
            
        for key, value in book.model_dump(exclude_unset=True).items():
            setattr(db_book, key, value)
        
        db.commit()
        db.refresh(db_book)
        return db_book
    except IntegrityError as e:
        db.rollback()
        error_msg = str(e.orig).lower()
        if "foreign key constraint" in error_msg:
            raise BookCRUDException(
                message="Invalid reference: Referenced entity does not exist",
                error_type="foreign_key_violation"
            )
        raise BookCRUDException(
            message="Data integrity violation during update",
            error_type="integrity_error"
        )

def partial_update_book(db: Session, book_id: int, book_data: dict):
    try:
        db_book = get_book(db, book_id)
        if not db_book:
            return None
            
        for key, value in book_data.items():
            if hasattr(db_book, key):
                setattr(db_book, key, value)
        
        db.commit()
        db.refresh(db_book)
        return db_book
    except IntegrityError as e:
        db.rollback()
        error_msg = str(e.orig).lower()
        if "foreign key constraint" in error_msg:
            raise BookCRUDException(
                message="Invalid reference: Referenced entity does not exist",
                error_type="foreign_key_violation"
            )
        raise BookCRUDException(
            message="Data integrity violation during update",
            error_type="integrity_error"
        )

def delete_book(db: Session, book_id: int):
    try:
        db_book = get_book(db, book_id)
        if not db_book:
            return None
            
        db.delete(db_book)
        db.commit()
        return db_book
    except IntegrityError as e:
        db.rollback()
        raise BookCRUDException(
            message="Cannot delete: Book is referenced by other entities",
            error_type="constraint_violation"
        )