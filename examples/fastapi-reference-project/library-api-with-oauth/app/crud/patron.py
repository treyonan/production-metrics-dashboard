from sqlalchemy.orm import Session
from app.models.patron import Patron
from app.schemas.patron import PatronCreate, PatronUpdate

def get_patrons(db: Session, skip: int = 0, limit: int = 100):
    return db.query(Patron).offset(skip).limit(limit).all()

def get_patron(db: Session, patron_id: int):
    return db.query(Patron).filter(Patron.id == patron_id).first()

def create_patron(db: Session, patron: PatronCreate):
    db_patron = Patron(**patron.dict())
    db.add(db_patron)
    db.commit()
    db.refresh(db_patron)
    return db_patron

def update_patron(db: Session, patron_id: int, patron: PatronUpdate):
    db_patron = get_patron(db, patron_id)
    if db_patron:
        for key, value in patron.dict().items():
            setattr(db_patron, key, value)
        db.commit()
        db.refresh(db_patron)
    return db_patron

def partial_update_patron(db: Session, patron_id: int, patron_data: dict):
    db_patron = get_patron(db, patron_id)
    if db_patron:
        for key, value in patron_data.items():
            if hasattr(db_patron, key):
                setattr(db_patron, key, value)
        db.commit()
        db.refresh(db_patron)
    return db_patron

def delete_patron(db: Session, patron_id: int):
    db_patron = get_patron(db, patron_id)
    if db_patron:
        db.delete(db_patron)
        db.commit()
    return db_patron