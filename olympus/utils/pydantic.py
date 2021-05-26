from typing import Optional, Type
from pydantic import BaseModel, create_model, Field
from pydantic.fields import ModelField


def to_optional(id_key: str = 'id'):
    def wrapped(cls: Type[BaseModel]):
        def optional_model(c):
            if issubclass(c, BaseModel):
                field: ModelField
                fields = {}
                for key, field in c.__fields__.items():
                    field_type = optional_model(field.type_)
                    default = field.default
                    if key == id_key and not field.allow_none:
                        default = default or ...

                    elif not field.allow_none:
                        field_type = Optional[field_type]

                    elif field.required:
                        default = default or ...

                    fields[key] = (field_type, Field(default, **field.field_info.extra))

                return create_model(c.__name__, __base__=c, __module__=c.__module__, **fields)

            return c

        return optional_model(cls)

    return wrapped
