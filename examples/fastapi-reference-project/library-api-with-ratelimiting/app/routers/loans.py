from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Dict, Any
from app.schemas.loan import Loan, LoanCreate, LoanUpdate
from app.crud.loan import (
    get_loans, get_loan, create_loan, update_loan,
    partial_update_loan, delete_loan
)
from app.database import get_db

router = APIRouter()

@router.get("/", response_model=List[Loan], status_code=status.HTTP_200_OK)
def read_loans(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return get_loans(db, skip=skip, limit=limit)

@router.get("/{loan_id}", response_model=Loan, status_code=status.HTTP_200_OK)
def read_loan(loan_id: int, db: Session = Depends(get_db)):
    loan = get_loan(db, loan_id)
    if not loan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Loan not found")
    return loan

@router.post("/", response_model=Loan, status_code=status.HTTP_201_CREATED)
def create_new_loan(loan: LoanCreate, db: Session = Depends(get_db)):
    return create_loan(db, loan)

@router.put("/{loan_id}", response_model=Loan, status_code=status.HTTP_200_OK)
def update_existing_loan(loan_id: int, loan: LoanUpdate, db: Session = Depends(get_db)):
    updated_loan = update_loan(db, loan_id, loan)
    if not updated_loan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Loan not found")
    return updated_loan

@router.patch("/{loan_id}", response_model=Loan, status_code=status.HTTP_200_OK)
def partial_update_existing_loan(loan_id: int, loan_data: Dict[str, Any], db: Session = Depends(get_db)):
    updated_loan = partial_update_loan(db, loan_id, loan_data)
    if not updated_loan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Loan not found")
    return updated_loan

@router.delete("/{loan_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_existing_loan(loan_id: int, db: Session = Depends(get_db)):
    deleted_loan = delete_loan(db, loan_id)
    if not deleted_loan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Loan not found")