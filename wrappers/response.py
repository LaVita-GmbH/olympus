from typing import Callable
import functools
from ..schemas import Response


def wrap_into_response(func: Callable):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        data = await func(*args, **kwargs)
        return Response(data=data)

    return wrapper
