from pydantic import BaseModel

class BookBase(BaseModel):
    title: str
    isbn: str
    author_id: int
    is_sold_out: bool = False

class BookCreate(BookBase):
    pass

class BookUpdate(BookBase):
    pass

class Book(BookBase):
    id: int

    class Config:
        from_attributes = True