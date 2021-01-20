from typing import Optional
from asgiref.sync import sync_to_async
from fastapi import Query
from ..schemas import LimitOffset


def depends_limit_offset(max_limit: Optional[int] = 1000):
    def get_limit_offset(limit: Optional[int] = Query(None, le=max_limit, ge=1), offset: Optional[int] = Query(None, ge=0)) -> LimitOffset:
        if offset is None:
            offset = 0

        return LimitOffset(
            limit=offset + (limit or max_limit),
            offset=offset,
        )

    return get_limit_offset
