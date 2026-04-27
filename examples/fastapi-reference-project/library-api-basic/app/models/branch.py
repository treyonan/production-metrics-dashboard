from sqlalchemy import Column, Integer, String, ForeignKey
from app.database import Base

class Branch(Base):
    __tablename__ = "branches"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    address = Column(String)
    city = Column(String)
    state = Column(String)
    zip_code = Column(String)    
    library_id = Column(Integer, ForeignKey("library_system.id"))