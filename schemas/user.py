from typing import List, Optional
from pydantic import BaseModel


class UserPermission(BaseModel):
    code: str


class User(BaseModel):
    id: str
    email: Optional[str]
    permissions: List[UserPermission]
