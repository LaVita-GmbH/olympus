from typing import Callable, Dict, ForwardRef, Optional, Type
from pydantic import BaseModel, create_model, Field
from pydantic.fields import ModelField


def to_optional(id_key: str = 'id'):
    def wrapped(cls: Type[BaseModel]):
        def optional_model(c, __module__: str, __parent__module__: str):
            if issubclass(c, BaseModel):
                field: ModelField
                fields = {}
                for key, field in c.__fields__.items():
                    field_type = optional_model(field.type_, __module__=__module__, __parent__module__=__parent__module__)
                    default = field.default
                    if key == id_key and not field.allow_none:
                        default = default or ...

                    elif not field.allow_none:
                        field_type = Optional[field_type]

                    elif field.required:
                        default = default or ...

                    fields[key] = (field_type, Field(default, **field.field_info.extra))

                return create_model(
                    c.__qualname__,
                    __base__=c,
                    __module__=c.__module__ if c.__module__ != __parent__module__ else __module__,
                    **fields,
                )

            return c

        return optional_model(cls, __module__=cls.__module__, __parent__module__=cls.__base__.__module__)

    return wrapped


class Reference(BaseModel):
    def __init_subclass__(cls, rel: Optional[str] = None, rel_params: Optional[Callable] = None, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        cls._rel = rel
        cls._rel_params = rel_params
        c = cls
        while cls._rel is None:
            if issubclass(c.__base__, Reference):
                c = c.__base__
                if not c:
                    raise AssertionError("Cannot find parent Reference with `rel` set")

                try:
                    cls._rel = c._rel
                    cls._rel_params = c._rel_params

                except AttributeError:
                    pass

            else:
                raise AssertionError


def include_reference(reference_key: str = '$rel', reference_params_key: str = '$rel_params'):
    def wrapped(cls: Type[BaseModel]):
        def model_with_rel(c, __module__: str, __parent__module__: str):
            if isinstance(c, ForwardRef):
                return c

            if issubclass(c, BaseModel):
                field: ModelField
                fields = {}
                has_reference = False
                for key, field in c.__fields__.items():
                    field_type = model_with_rel(field.type_, __module__=__module__, __parent__module__=__parent__module__)
                    if not isinstance(c, type) and issubclass(field_type, Reference):
                        has_reference = True

                    fields[key] = (field_type, Field(field.default, **field.field_info.extra))

                if issubclass(c, Reference):
                    fields[reference_key] = (str, Field(c._rel, example=c._rel, orm_field=None, alias=reference_key, const=True))
                    if c._rel_params:
                        fields[reference_params_key] = (dict, Field(alias=reference_params_key, orm_method=c._rel_params))

                if has_reference:
                    return create_model(
                        c.__qualname__,
                        __base__=c,
                        __module__=c.__module__ if c.__module__ != __parent__module__ else __module__,
                        **fields,
                    )

            return c

        return model_with_rel(cls, __module__=cls.__module__, __parent__module__=cls.__base__.__module__)

    return wrapped
