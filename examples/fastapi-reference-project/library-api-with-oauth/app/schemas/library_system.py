from pydantic import BaseModel

class LibrarySystemBase(BaseModel):
    name: str

class LibrarySystemCreate(LibrarySystemBase):
    pass

class LibrarySystemUpdate(LibrarySystemBase):
    pass

class LibrarySystem(LibrarySystemBase):
    id: int

    class Config:
        from_attributes = True