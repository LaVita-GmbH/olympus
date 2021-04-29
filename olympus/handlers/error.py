import logging
from typing import Any
from psycopg2.errorcodes import lookup as psycopg2_error_lookup
from jose.exceptions import JOSEError, ExpiredSignatureError
from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException
from django.core.exceptions import ObjectDoesNotExist
from django.db.utils import IntegrityError

try:
    import sentry_sdk
    from sentry_sdk.integrations import asgi as sentry_sdk_asgi

except ImportError:
    sentry_sdk = None

from .. import schemas


_logger = logging.getLogger(__name__)


def capture_exception(exc):
    _logger.exception(exc)
    if not sentry_sdk:
        return

    return sentry_sdk.capture_exception(exc)


async def respond_details(request: Request, content: Any, status_code: int = 500, headers: dict = None):
    response = {
        'detail': jsonable_encoder(content),
    }

    event_id = sentry_sdk.last_event_id() or request.scope.get('sentry_event_id')
    if event_id:
        response['event_id'] = event_id

    return JSONResponse(
        content=response,
        status_code=status_code,
        headers=headers,
    )


async def http_exception_handler(request: Request, exc: HTTPException):
    capture_exception(exc)
    content = exc.detail

    if isinstance(content, str):
        content = schemas.Error(
            type=exc.__class__.__name__,
            message=content,
        )

    if isinstance(content, schemas.Error) and not content.type:
        content.type = exc.__class__.__name__

    return await respond_details(
        request,
        content,
        status_code=exc.status_code,
        headers=getattr(exc, 'headers', None),
    )


async def object_does_not_exist_handler(request: Request, exc: ObjectDoesNotExist):
    capture_exception(exc)
    return await respond_details(
        request,
        schemas.Error(
            type=exc.__class__.__name__,
            message=str(exc),
        ),
        status_code=404,
    )


async def integrity_error_handler(request: Request, exc: IntegrityError):
    capture_exception(exc)
    code = psycopg2_error_lookup(exc.__cause__.pgcode).lower()
    try:
        code += ":" + exc.__cause__.diag.constraint_name

    except AttributeError:
        pass

    return await respond_details(
        request,
        schemas.Error(
            type=exc.__class__.__name__,
            code=code,
        ),
        status_code=420,
    )


async def jose_error_handler(request: Request, exc: JOSEError):
    if not isinstance(exc, ExpiredSignatureError):
        capture_exception(exc)

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
