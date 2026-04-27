from sqlalchemy.orm import Session
from app.models.library_system import LibrarySystem
from app.schemas.library_system import LibrarySystemCreate, LibrarySystemUpdate

def get_library_system(db: Session):
    return db.query(LibrarySystem).first()

def create_library_system(db: Session, library_system: LibrarySystemCreate):
    if get_library_system(db):
        return None  # Already exists
    db_library_system = LibrarySystem(**library_system.dict())
    db.add(db_library_system)
    db.commit()
    db.refresh(db_library_system)
    return db_library_system

def update_library_system(db: Session, library_system: LibrarySystemUpdate):
    db_library_system = get_library_system(db)
    if db_library_system:
        for key, value in library_system.dict().items():
            setattr(db_library_system, key, value)
        db.commit()
        db.refresh(db_library_system)
    return db_library_system

def partial_update_library_system(db: Session, library_system_data: dict):
    db_library_system = get_library_system(db)
    if db_library_system:
        for key, value in library_system_data.items():
            if hasattr(db_library_system, key):
                setattr(db_library_system, key, value)
        db.commit()
        db.refresh(db_library_system)
    return db_library_system