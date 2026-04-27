from pydantic import BaseModel

class PatronBase(BaseModel):
    name: str
    email: str

class PatronCreate(PatronBase):
    pass

class PatronUpdate(PatronBase):
    pass

class Patron(PatronBase):
    id: int

    class Config:
        from_attributes = True