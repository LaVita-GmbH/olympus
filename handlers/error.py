import typing
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

    return JSONResponse(jsonable_encoder(schemas.ErrorResponse(error=error)), status_code=status_code)


# async def validation_exception_handler(request: Request, exc: RequestValidationError):
#     return await respond_with_error(request, schemas.Error(
#         type='RequestValidationError',
#         details=exc.errors(),
#     ))


# async def http_exception_handler(request: Request, exc: HTTPException):
#     return await respond_with_error(request, schemas.Error(
#         type='HTTPException',
#         message=exc.detail,
#     ))


async def object_does_not_exist_handler(request: Request, exc: ObjectDoesNotExist):
    return await respond_with_error(request, schemas.Error(
        type='ObjectDoesNotExist',
        message=str(exc),
    ))


async def generic_exception_handler(request: Request, exc: Exception):
    return await respond_with_error(request, schemas.Error(type='InternalServerError'))
