from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import Dict, Any
from app.schemas.library_system import LibrarySystem, LibrarySystemCreate, LibrarySystemUpdate
from app.crud.library_system import (
    get_library_system, create_library_system, update_library_system,
    partial_update_library_system
)
from app.database import get_db

router = APIRouter()

@router.get("/", response_model=LibrarySystem, status_code=status.HTTP_200_OK)
def read_library_system(db: Session = Depends(get_db)):
    library_system = get_library_system(db)
    if not library_system:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Library system not found")
    return library_system

@router.post("/", response_model=LibrarySystem, status_code=status.HTTP_201_CREATED)
def create_new_library_system(library_system: LibrarySystemCreate, db: Session = Depends(get_db)):
    created = create_library_system(db, library_system)
    if not created:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Library system already exists")
    return created

@router.put("/", response_model=LibrarySystem, status_code=status.HTTP_200_OK)
def update_existing_library_system(library_system: LibrarySystemUpdate, db: Session = Depends(get_db)):
    updated = update_library_system(db, library_system)
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Library system not found")
    return updated

@router.patch("/", response_model=LibrarySystem, status_code=status.HTTP_200_OK)
def partial_update_existing_library_system(library_system_data: Dict[str, Any], db: Session = Depends(get_db)):
    updated = partial_update_library_system(db, library_system_data)
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Library system not found")
    return updated

@router.delete("/", status_code=status.HTTP_204_NO_CONTENT)
def delete_existing_library_system(db: Session = Depends(get_db)):
    library_system = get_library_system(db)
    if not library_system:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Library system not found")
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Operation Not Allowed: Library system cannot be deleted once initialized.")