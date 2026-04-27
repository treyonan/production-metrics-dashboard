from sqlalchemy import Column, Integer, DateTime, ForeignKey
from app.database import Base

class Loan(Base):
    __tablename__ = "loans"

    id = Column(Integer, primary_key=True, index=True)
    book_id = Column(Integer, ForeignKey("books.id"))
    patron_id = Column(Integer, ForeignKey("patrons.id"))
    branch_id = Column(Integer, ForeignKey("branches.id"))
    loan_date = Column(DateTime)
    due_date = Column(DateTime)