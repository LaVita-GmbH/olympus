from typing import Dict, Optional, Type
from pydantic import BaseModel, create_model, Field
from pydantic.fields import ModelField


def to_optional(id_key: str = 'id'):
    def wrapped(cls: Type[BaseModel]):
        def optional_model(c, __module__: str):
            if issubclass(c, BaseModel):
                field: ModelField
                fields = {}
                for key, field in c.__fields__.items():
                    field_type = optional_model(field.type_, __module__=__module__)
                    default = field.default
                    if key == id_key and not field.allow_none:
                        default = default or ...

                    elif not field.allow_none:
                        field_type = Optional[field_type]

                    elif field.required:
                        default = default or ...

                    fields[key] = (field_type, Field(default, **field.field_info.extra))

                return create_model(c.__name__, __base__=c, __module__=__module__, **fields)

            return c

        return optional_model(cls, __module__=cls.__module__)

    return wrapped


class Reference(BaseModel):
    def __init_subclass__(cls, rel: Optional[str] = None, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        cls._rel = rel
        c = cls
        while cls._rel is None:
            if issubclass(c.__base__, Reference):
                c = c.__base__
                try:
                    cls._rel = c._rel

                except AttributeError:
                    pass


def include_reference(reference_key: str = '$rel'):
    def wrapped(cls: Type[BaseModel]):
        def model_with_rel(c, __module__: str):
            if issubclass(c, BaseModel):
                field: ModelField
                fields = {}
                for key, field in c.__fields__.items():
                    field_type = model_with_rel(field.type_, __module__=__module__)
                    fields[key] = (field_type, Field(field.default, **field.field_info.extra))

                if issubclass(c, Reference):
                    fields[reference_key] = (str, Field(c._rel, example=c._rel, orm_field=None, alias=reference_key, const=True))

                return create_model(c.__name__, __base__=c, __module__=__module__, **fields)

            return c

        return model_with_rel(cls, __module__=cls.__module__)

    return wrapped
