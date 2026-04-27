from pydantic import BaseModel

class BranchBase(BaseModel):
    name: str
    address: str
    library_id: int

class BranchCreate(BranchBase):
    pass

class BranchUpdate(BranchBase):
    pass

class Branch(BranchBase):
    id: int

    class Config:
        from_attributes = True