from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.models.branch import Branch
from app.schemas.branch import BranchCreate, BranchUpdate
from app.exceptions.librarycrudexception import LibraryCRUDException

def get_branches(db: Session, skip: int = 0, limit: int = 100):
    return db.query(Branch).offset(skip).limit(limit).all()

def get_branch(db: Session, branch_id: int):
    return db.query(Branch).filter(Branch.id == branch_id).first()

def create_branch(db: Session, branch: BranchCreate):
    try:
        db_branch = Branch(**branch.dict())
        db.add(db_branch)
        db.commit()
        db.refresh(db_branch)
        return db_branch
    except IntegrityError as e:
        db.rollback()

        # Check if it's a foreign key constraint violation
        error_msg = str(e.args).lower()
        if "foreign key constraint failed" in error_msg:
            if "library_id" in e.statement:
                raise LibraryCRUDException(
                    message="Invalid library_id: Library System does not exist",
                    error_type="foreign_key_violation"
                )
            else:
                raise LibraryCRUDException(
                    message="Referenced entity does not exist",
                    error_type="foreign_key_violation"
                )


def update_branch(db: Session, branch_id: int, branch: BranchUpdate):
    try:
        db_branch = get_branch(db, branch_id)
        if db_branch:
            for key, value in branch.dict().items():
                setattr(db_branch, key, value)
            db.commit()
            db.refresh(db_branch)
        return db_branch
    except IntegrityError as e:
        db.rollback()

        # Check if it's a foreign key constraint violation
        error_msg = str(e.args).lower()
        if "foreign key constraint failed" in error_msg:
            if "library_id" in e.statement:
                raise LibraryCRUDException(
                    message="Invalid library_id: Library System does not exist",
                    error_type="foreign_key_violation"
                )
            else:
                raise LibraryCRUDException(
                    message="Referenced entity does not exist",
                    error_type="foreign_key_violation"
                )

def partial_update_branch(db: Session, branch_id: int, branch_data: dict):
    db_branch = get_branch(db, branch_id)
    if db_branch:
        for key, value in branch_data.items():
            if hasattr(db_branch, key):
                setattr(db_branch, key, value)
        db.commit()
        db.refresh(db_branch)
    return db_branch

def delete_branch(db: Session, branch_id: int):
    db_branch = get_branch(db, branch_id)
    if db_branch:
        db.delete(db_branch)
        db.commit()
    return db_branch