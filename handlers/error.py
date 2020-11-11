import typing
from typing import Any
from jose.exceptions import JOSEError
from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException
from django.core.exceptions import ObjectDoesNotExist

try:
    import sentry_sdk
except ImportError:
    sentry_sdk = None

from .. import schemas


async def respond_details(request: Request, content: Any, status_code: int = 500, headers: dict = None):
    response = {
        'detail': jsonable_encoder(content),
    }

    event_id = request.scope.get('sentry_event_id')
    if event_id:
        response['event_id'] = event_id

    return JSONResponse(
        content=response,
        status_code=status_code,
        headers=headers,
    )


async def http_exception_handler(request: Request, exc: HTTPException):
    content = exc.detail

    if isinstance(content, str):
        content = schemas.Error(
            type=exc.__class__.__name__,
            message=content,
        )

    return await respond_details(
        request,
        content,
        status_code=exc.status_code,
        headers=getattr(exc, 'headers'),
    )


async def object_does_not_exist_handler(request: Request, exc: ObjectDoesNotExist):
    return await respond_details(
        request,
        schemas.Error(
            type=exc.__class__.__name__,
            message=str(exc),
        ),
        status_code=404,
    )


async def jose_error_handler(request: Request, exc: JOSEError):
    return await respond_details(
        request,
        schemas.Error(
            type=exc.__class__.__name__,
            message=str(exc),
        ),
        status_code=401,
    )


async def generic_exception_handler(request: Request, exc: Exception):
    return await respond_details(request, schemas.Error(type='InternalServerError'))
