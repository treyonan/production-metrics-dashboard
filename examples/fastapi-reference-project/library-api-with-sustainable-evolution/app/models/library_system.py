from sqlalchemy import Column, Integer, String
from app.database import Base

class LibrarySystem(Base):
    __tablename__ = "library_system"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)