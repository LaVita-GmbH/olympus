from typing import Any, List, Optional
from pydantic import BaseModel


class ErrorResponse(BaseModel):
    type: Optional[str]
    message: Optional[str]
    code: Optional[str]
    event_id: Optional[str]
    details: Optional[Any]


class WarningResponse(BaseModel):
    pass


class DeprecationResponse(ErrorResponse):
    pass


class Response(BaseModel):
    data: Optional[Any]
    meta: Optional[Any]
    error: Optional[ErrorResponse]
    warnings: Optional[List[WarningResponse]]
    deprecations: Optional[List[DeprecationResponse]]
