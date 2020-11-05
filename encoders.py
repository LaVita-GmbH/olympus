import functools
from typing import Callable
from fastapi import encoders
from fastapi.responses import JSONResponse


def jsonable_encoder(func: Callable):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        return JSONResponse(encoders.jsonable_encoder(await func(*args, **kwargs)))

    return wrapper
