from typing import Optional
from asgiref.sync import sync_to_async
from fastapi import Query
from ..schemas import Pagination


def depends_pagination(max_limit: Optional[int] = 1000):
    def get_pagination(limit: Optional[int] = Query(None, le=max_limit, ge=1), offset: Optional[int] = Query(None, ge=0)) -> Pagination:
        if offset is None:
            offset = 0

        return Pagination(
            limit=offset + (limit or max_limit),
            offset=offset,
        )

    return get_pagination
