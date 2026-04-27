from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Dict, Any
from app.schemas.patron import Patron, PatronCreate, PatronUpdate
from app.crud.patron import (
    get_patrons, get_patron, create_patron, update_patron,
    partial_update_patron, delete_patron
)
from app.database import get_db

router = APIRouter()

@router.get("/", response_model=List[Patron], status_code=status.HTTP_200_OK)
def read_patrons(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return get_patrons(db, skip=skip, limit=limit)

@router.get("/{patron_id}", response_model=Patron, status_code=status.HTTP_200_OK)
def read_patron(patron_id: int, db: Session = Depends(get_db)):
    patron = get_patron(db, patron_id)
    if not patron:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patron not found")
    return patron

@router.post("/", response_model=Patron, status_code=status.HTTP_201_CREATED)
def create_new_patron(patron: PatronCreate, db: Session = Depends(get_db)):
    return create_patron(db, patron)

@router.put("/{patron_id}", response_model=Patron, status_code=status.HTTP_200_OK)
def update_existing_patron(patron_id: int, patron: PatronUpdate, db: Session = Depends(get_db)):
    updated_patron = update_patron(db, patron_id, patron)
    if not updated_patron:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patron not found")
    return updated_patron

@router.patch("/{patron_id}", response_model=Patron, status_code=status.HTTP_200_OK)
def partial_update_existing_patron(patron_id: int, patron_data: Dict[str, Any], db: Session = Depends(get_db)):
    updated_patron = partial_update_patron(db, patron_id, patron_data)
    if not updated_patron:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patron not found")
    return updated_patron

@router.delete("/{patron_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_existing_patron(patron_id: int, db: Session = Depends(get_db)):
    deleted_patron = delete_patron(db, patron_id)
    if not deleted_patron:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patron not found")