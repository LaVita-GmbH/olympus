from typing import List
from pydantic import BaseModel


class Pagination(BaseModel):
    limit: int
    offset: int
    order_by: List[str]
