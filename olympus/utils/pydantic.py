import typing
from typing import Callable, ForwardRef, Optional, Type, Any
from pydantic import BaseModel, create_model, Field
from pydantic.fields import ModelField, FieldInfo, SHAPE_SINGLETON, SHAPE_LIST, Undefined


TypingGenericAlias = type(Any)


def _new_field_from_model_field(
    field: ModelField,
    default: Any = Undefined,
    required: Optional[bool] = None
):
    if default is not Undefined:
        default = field.default

    if required is None and field.required and (default is Undefined or field.default is None):
        default = ...

    return Field(
        default,
        default_factory=field.default_factory,
        alias=field.alias,
        **field.field_info.extra,
    )


def to_optional(id_key: str = 'id'):
    def wrapped(cls: Type[BaseModel]):
        def optional_model(c, __module__: str, __parent__module__: str):
            try:
                if issubclass(c, BaseModel):
                    field: ModelField
                    fields = {}
                    for key, field in c.__fields__.items():
                        field_type = optional_model(field.outer_type_, __module__=__module__, __parent__module__=__parent__module__)
                        default = field.default
                        if key == id_key and not field.allow_none:
                            default = default or ...

                        elif not field.allow_none:
                            field_type = Optional[field_type]

                        elif field.required:
                            default = default or ...

                        fields[key] = (field_type, _new_field_from_model_field(field, default, required=False))

                    return create_model(
                        c.__qualname__,
                        __base__=c,
                        __module__=c.__module__ if c.__module__ != __parent__module__ else __module__,
                        **fields,
                    )

            except TypeError:
                pass

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
    recreated_models = {}
    def wrapped(cls: Type[BaseModel]):
        def model_with_rel(c, __module__: str, __parent__module__: str):
            if isinstance(c, ForwardRef):
                return c, False

            if issubclass(c, BaseModel):
                field: ModelField
                fields = {}
                recreate_model = False
                for key, field in c.__fields__.items():
                    if field.shape not in (SHAPE_SINGLETON, SHAPE_LIST):
                        fields[key] = (field.outer_type_, _new_field_from_model_field(field))
                        continue

                    field_type, recreated_model = model_with_rel(field.type_, __module__=__module__, __parent__module__=__parent__module__)
                    if field.type_ != field.outer_type_:
                        field_type = getattr(typing, field.outer_type_._name)[field_type]

                    if field.allow_none:
                        field_type = Optional[field_type]

                    fields[key] = (field_type, _new_field_from_model_field(field))
                    if recreated_model:
                        recreate_model = True

                    try:
                        if issubclass(field_type, Reference):
                            recreate_model = True

                    except TypeError:
                        pass

                if issubclass(c, Reference):
                    recreate_model = True
                    fields['x_reference_key'] = (str, Field(c._rel, example=c._rel, orm_field=None, alias=reference_key))
                    if c._rel_params:
                        fields['x_reference_params_key'] = (dict, Field(alias=reference_params_key, orm_method=c._rel_params))

                if recreate_model:
                    if c not in recreated_models:
                        recreated_models[c] = create_model(
                            f'{c.__qualname__} [R]',
                            __base__=c,
                            __module__=c.__module__ if c.__module__ != __parent__module__ else __module__,
                            **fields,
                        ), True

                    return recreated_models[c]

            return c, False

        return model_with_rel(cls, __module__=cls.__module__, __parent__module__=cls.__base__.__module__)[0]

    return wrapped
