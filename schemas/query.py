from pydantic import BaseModel


class LimitOffset(BaseModel):
    limit: int
    offset: int
