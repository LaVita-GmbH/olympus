import os
from typing import List, Optional, Tuple, Type
from django.db.models.fields.related_descriptors import ManyToManyDescriptor, ReverseManyToOneDescriptor
from fastapi import Query
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, validate_model
from django.db import models
from django.db.models.manager import Manager
from pydantic.error_wrappers import ErrorWrapper, ValidationError
from pydantic.fields import ModelField, SHAPE_SINGLETON, SHAPE_LIST, SHAPE_SET
from .schemas import Access, Error, LimitOffset
from .exceptions import AccessError


def transfer_to_orm(pydantic_obj: BaseModel, django_obj: models.Model) -> None:
    """
    Transfers the field contents of pydantic_obj to django_obj.
    For this to work it is required to have orm_field set on all of the pydantic_obj's fields, which has to point to the django model attribute.

    It also works for nested pydantic models which point to a field on the **same** django model.

    Example:

    ```python
    from pydantic import BaseModel, Field
    from django.db import models

    class Address(models.Model):
        name = models.CharField(max_length=56)

    class AddressRequest(BaseModel):
        name: str = Field(orm_field=Address.name)
    ```
    """
    def populate_none(pydantic_cls, django_obj):
        for key, field in pydantic_cls.__fields__.items():
            if issubclass(field.type_, BaseModel):
                populate_none(field.type_, django_obj)

            else:
                orm_field = field.field_info.extra.get('orm_field')
                setattr(django_obj, orm_field.field.attname, None)

    for key, field in pydantic_obj.fields.items():
        value = getattr(pydantic_obj, field.name)
        if issubclass(field.type_, BaseModel):
            if value is None:
                populate_none(field.type_, django_obj)

            else:
                transfer_to_orm(pydantic_obj=value, django_obj=django_obj)

        else:
            orm_field = field.field_info.extra.get('orm_field')
            if not orm_field:
                if 'orm_field' in field.field_info.extra and field.field_info.extra['orm_field'] is None:
                    # Do not raise error when orm_field was explicitly set to None
                    continue

                raise AttributeError("orm_field not found on %r" % field)

            if orm_field.field.is_relation and isinstance(value, models.Model):
                value = value.pk

            setattr(django_obj, orm_field.field.attname, value)


def transfer_from_orm(
    pydantic_cls: Type[BaseModel],
    django_obj: models.Model,
    django_parent_obj: Optional[models.Model] = None,
    pydantic_field_on_parent: Optional[ModelField] = None
) -> BaseModel:
    """
    Transfers the field contents of django_obj to a new instance of pydantic_cls.
    For this to work it is required to have orm_field set on all of the pydantic_obj's fields, which has to point to the django model attribute.

    It also works for nested pydantic models which point to a field on the **same** django model.

    Example:

    ```python
    from pydantic import BaseModel, Field
    from django.db import models

    class Address(models.Model):
        name = models.CharField(max_length=56)

    class AddressRequest(BaseModel):
        name: str = Field(orm_field=Address.name)
    ```
    """
    values = {}
    for key, field in pydantic_cls.__fields__.items():
        orm_field = field.field_info.extra.get('orm_field')
        if not orm_field:
            if 'orm_field' in field.field_info.extra and field.field_info.extra['orm_field'] is None:
                # Do not raise error when orm_field was explicitly set to None
                continue

            if not (field.shape == SHAPE_SINGLETON and issubclass(field.type_, BaseModel)):
                raise AttributeError("orm_field not found on %r (parent: %r)" % (field, pydantic_field_on_parent))

        if field.shape != SHAPE_SINGLETON:
            if field.shape == SHAPE_LIST:
                if isinstance(orm_field, ManyToManyDescriptor):
                    relatedmanager = getattr(django_obj, orm_field.field.attname)
                    related_objs = relatedmanager.through.objects.filter(**{relatedmanager.source_field_name: relatedmanager.instance})

                elif isinstance(orm_field, ReverseManyToOneDescriptor):
                    relatedmanager = getattr(django_obj, orm_field.rel.name)
                    related_objs = relatedmanager.all()

                else:
                    raise NotImplementedError

                values[field.name] = [
                    transfer_from_orm(
                        pydantic_cls=field.type_,
                        django_obj=rel_obj,
                        django_parent_obj=django_obj,
                        pydantic_field_on_parent=field
                    ) for rel_obj in related_objs
                ]

            else:
                raise NotImplementedError

        elif issubclass(field.type_, BaseModel):
            values[field.name] = transfer_from_orm(pydantic_cls=field.type_, django_obj=django_obj, pydantic_field_on_parent=field)

        else:
            value = None
            try:
                value = getattr(django_obj, orm_field.field.attname)

            except AttributeError:
                raise  # attach debugger here ;)

            if field.required and pydantic_field_on_parent and pydantic_field_on_parent.allow_none and value is None:
                return None

            values[field.name] = value

    return pydantic_cls.construct(**values)


def check_field_access(input: BaseModel, access: Access):
    """
    Check access to fields.

    To define scopes of a field, add a list of scopes to the Field defenition in the kwarg scopes.

    Example:
    ```python
    from pydantic import BaseModel, Field

    class AddressRequest(BaseModel):
        name: str = Field(scopes=['elysium.addresses.edit.any',])
    ```
    """
    def check(model: BaseModel, input: dict, access: Access, loc: Optional[List[str]] = None):
        if not loc:
            loc = ['body',]

        for key, value in input.items():
            if isinstance(value, dict):
                check(getattr(model, key), value, access, loc=loc + [key])

            else:
                scopes = model.fields[key].field_info.extra.get('scopes')
                if not scopes:
                    continue

                if not access.token.has_audience(scopes):
                    raise AccessError(detail=Error(
                        type='FieldAccessError',
                        code='access_error.field',
                        detail={
                            'loc': loc + [key],
                        },
                    ))

    check(input, input.dict(exclude_unset=True), access)


async def update_orm(model: Type[BaseModel], orm_obj: models.Model, input: BaseModel, *, access: Optional[Access]) -> BaseModel:
    """
    Apply (partial) changes given in `input` to an orm_obj and return an instance of `model` with the full data of the orm including the updated fields.
    """
    if access:
        check_field_access(input, access)

    data = await model.from_orm(orm_obj)
    input_dict: dict = input.dict(exclude_unset=True)

    def update(model: BaseModel, input: dict):
        for key, value in input.items():
            if isinstance(value, dict):
                update(getattr(model, key), value)

            else:
                setattr(model, key, value)

    update(data, input_dict)

    values, fields_set, validation_error = validate_model(model, data.dict())
    if validation_error:
        raise RequestValidationError(validation_error.raw_errors)

    transfer_to_orm(data, orm_obj)
    return data


def validate_object(obj: BaseModel, is_request: bool = True):
    *_, validation_error = validate_model(obj.__class__, obj.__dict__)
    if validation_error:
        if is_request:
            raise RequestValidationError(validation_error.raw_errors)

        raise validation_error


def dict_remove_none(d):
    if isinstance(d, dict):
        return {key: dict_remove_none(value) for key, value in d.items() if value is not None}

    else:
        return d


def depends_limit_offset(max_limit: Optional[int] = 1000):
    def get_limit_offset(limit: Optional[int] = Query(None, le=max_limit, ge=1), offset: Optional[int] = Query(None, ge=0)) -> LimitOffset:
        return LimitOffset(
            limit=limit or max_limit,
            offset=offset or 0,
        )

    return get_limit_offset


class DjangoAllowAsyncUnsafe:
    def __init__(self):
        self._django_allow_async_unsafe_before = os.environ.get('DJANGO_ALLOW_ASYNC_UNSAFE')

    def __enter__(self):
        os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = '1'

    def __exit__(self, type, value, traceback):
        if self._django_allow_async_unsafe_before is None:
            del os.environ['DJANGO_ALLOW_ASYNC_UNSAFE']

        else:
            os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = self._django_allow_async_unsafe_before
