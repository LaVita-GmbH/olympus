import typing
from jose.exceptions import JOSEError
from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException
from django.core.exceptions import ObjectDoesNotExist

try:
    import sentry_sdk
except ImportError:
    sentry_sdk = None

from .. import schemas


async def respond_with_error(request: Request, error: schemas.Error, status_code: int = 500):
    error.event_id = request.scope.get('sentry_event_id')

    return JSONResponse(jsonable_encoder(error), status_code=status_code)


async def object_does_not_exist_handler(request: Request, exc: ObjectDoesNotExist):
    return await respond_with_error(
        request,
        schemas.Error(
            type=exc.__class__.__name__,
            message=str(exc),
        ),
        status_code=404,
    )


async def jose_error_handler(request: Request, exc: JOSEError):
    return await respond_with_error(
        request,
        schemas.Error(
            type=exc.__class__.__name__,
            message=str(exc),
        ),
        status_code=401,
    )


async def generic_exception_handler(request: Request, exc: Exception):
    return await respond_with_error(request, schemas.Error(type='InternalServerError'))
