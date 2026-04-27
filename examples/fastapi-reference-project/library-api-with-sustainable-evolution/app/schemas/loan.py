from datetime import datetime
from pydantic import BaseModel

class LoanBase(BaseModel):
    book_id: int
    patron_id: int
    branch_id: int
    loan_date: datetime
    due_date: datetime

class LoanCreate(LoanBase):
    pass

class LoanUpdate(LoanBase):
    pass

class Loan(LoanBase):
    id: int

    class Config:
        from_attributes = True