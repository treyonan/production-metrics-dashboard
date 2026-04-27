from sqlalchemy import Column, Integer, String, ForeignKey, Boolean
from app.database import Base

class Book(Base):
    __tablename__ = "books"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True)
    isbn = Column(String, unique=True)
    author_id = Column(Integer, ForeignKey("authors.id"))
    is_sold_out = Column(Boolean, nullable=False, default=False)