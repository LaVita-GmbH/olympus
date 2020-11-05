import typing
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

try:
    import sentry_sdk
except ImportError:
    sentry_sdk = None

from .. import schemas
from ..encoders import jsonable_encoder


@jsonable_encoder
async def respond_with_error(request: Request, error: schemas.ErrorResponse):
    error.event_id = request.scope.get('sentry_event_id')

    return schemas.Response(error=error)


async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return await respond_with_error(request, schemas.ErrorResponse(
        type='RequestValidationError',
        details=exc.errors(),
    ))


async def http_exception_handler(request: Request, exc: HTTPException):
    return await respond_with_error(request, schemas.ErrorResponse(
        type='HTTPException',
        message=exc.detail,
    ))


async def generic_exception_handler(request: Request, exc: Exception):
    return await respond_with_error(request, schemas.ErrorResponse())
