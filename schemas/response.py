from typing import Any, List, Optional
from pydantic import BaseModel, Field


_wrapped_models = {}


class Error(BaseModel):
    type: Optional[str] = None
    message: Optional[str] = None
    code: Optional[str] = None
    event_id: Optional[str] = None
    details: Optional[Any] = None


class Warn(BaseModel):
    pass


class Deprecation(BaseModel):
    pass


class Response(BaseModel):
    data: Optional[Any] = None
    meta: Optional[Any] = None
    warnings: Optional[List[Warn]] = Field(None, nullable=True)
    deprecations: Optional[List[Deprecation]] = Field(None, nullable=True)

    @classmethod
    def wraps(cls, data: BaseModel, meta: Optional[BaseModel] = None):
        if data not in _wrapped_models:
            _wrapped_models[data] = type(f'{data.__name__}Response', (Response,), {})

        response_model = _wrapped_models[data]

        def modify_pydantic_validators(field, new_type):
            response_model.__dict__['__fields__'][field].type_ = new_type
            response_model.__dict__['__fields__'][field].allow_none = False
            response_model.__dict__['__fields__'][field].required = True

        modify_pydantic_validators('data', data)
        if meta:
            modify_pydantic_validators('meta', meta)

        return response_model


class ErrorResponse(Response):
    error: Optional[Error] = None
