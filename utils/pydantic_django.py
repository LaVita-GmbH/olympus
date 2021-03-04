from typing import List, Mapping, Optional, Type, TypeVar, Union
import json
from asgiref.sync import sync_to_async
from fastapi import Query
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, validate_model, SecretStr
from pydantic.fields import ModelField, SHAPE_SINGLETON, SHAPE_LIST
from django.db import models
from django.db.models.manager import Manager
from django.db.models.fields.related_descriptors import ManyToManyDescriptor, ReverseManyToOneDescriptor
from olympus.utils.django import AllowAsyncUnsafe
from ..schemas import Access, Error
from ..exceptions import AccessError


def transfer_to_orm(pydantic_obj: BaseModel, django_obj: models.Model, *, exclude_unset: bool = False, access: Optional[Access] = None) -> None:
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
    if access:
        check_field_access(pydantic_obj, access)

    pydantic_values: Optional[dict] = pydantic_obj.dict(exclude_unset=True) if exclude_unset else None

    def populate_none(pydantic_cls, django_obj):
        for key, field in pydantic_cls.__fields__.items():
            orm_field = field.field_info.extra.get('orm_field')
            if not orm_field and issubclass(field.type_, BaseModel):
                populate_none(field.type_, django_obj)

            else:
                if 'orm_field' in field.field_info.extra and field.field_info.extra['orm_field'] is None:
                    # Do not raise error when orm_field was explicitly set to None
                    continue

                assert orm_field, "orm_field not set on %r of %r" % (field, pydantic_cls)
                setattr(django_obj, orm_field.field.attname, None)

    for key, field in pydantic_obj.__fields__.items():
        orm_method = field.field_info.extra.get('orm_method')
        if orm_method:
            if exclude_unset and key not in pydantic_values:
                continue

            value = getattr(pydantic_obj, field.name)
            if isinstance(value, SecretStr):
                value = value.get_secret_value()

            orm_method(django_obj, value)
            continue

        orm_field = field.field_info.extra.get('orm_field')
        if not orm_field:
            if 'orm_field' in field.field_info.extra and field.field_info.extra['orm_field'] is None:
                # Do not raise error when orm_field was explicitly set to None
                continue

            if not (field.shape == SHAPE_SINGLETON and issubclass(field.type_, BaseModel)):
                raise AttributeError("orm_field not found on %r" % field)

        value = getattr(pydantic_obj, field.name)
        if field.shape != SHAPE_SINGLETON:
            raise NotImplementedError

        elif not orm_field and issubclass(field.type_, BaseModel):
            if value is None:
                if exclude_unset and key not in pydantic_values:
                    continue

                populate_none(field.type_, django_obj)

            elif isinstance(value, BaseModel):
                transfer_to_orm(pydantic_obj=value, django_obj=django_obj, exclude_unset=exclude_unset, access=access)

            else:
                raise NotImplementedError

        else:
            if exclude_unset and key not in pydantic_values:
                continue

            if orm_field.field.is_relation and isinstance(value, models.Model):
                value = value.pk

            if isinstance(orm_field.field, models.JSONField) and value:
                if isinstance(value, BaseModel):
                    value = value.json()

                elif isinstance(value, dict):
                    value = json.dumps(value)

                else:
                    raise NotImplementedError

            setattr(django_obj, orm_field.field.attname, value)


def transfer_from_orm(
    pydantic_cls: Type[BaseModel],
    django_obj: models.Model,
    django_parent_obj: Optional[models.Model] = None,
    pydantic_field_on_parent: Optional[ModelField] = None,
    filter_submodel: Optional[Mapping[Manager, models.Q]] = None,
) -> BaseModel:
    """
    Transfers the field contents of django_obj to a new instance of pydantic_cls.
    For this to work it is required to have orm_field set on all of the pydantic_obj's fields, which has to point to the django model attribute.

    It also works for nested pydantic models which point to a field on the **same** django model and for related fields (m2o or m2m).

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
        orm_method = field.field_info.extra.get('orm_method')
        if orm_method:
            value = orm_method(django_obj)
            if value is not None and issubclass(field.type_, BaseModel) and not isinstance(value, BaseModel):
                if field.shape == SHAPE_SINGLETON:
                    value = field.type_.parse_obj(value)

                elif field.shape == SHAPE_LIST:
                    value = [
                        field.type_.parse_obj(item) if not isinstance(value, BaseModel) else item
                        for item in value
                    ]

                else:
                    raise NotImplementedError

            values[field.name] = value

        else:
            orm_field = field.field_info.extra.get('orm_field')
            if 'orm_field' in field.field_info.extra and field.field_info.extra['orm_field'] is None:
                # Do not raise error when orm_field was explicitly set to None
                continue

            if not orm_field and not (field.shape == SHAPE_SINGLETON and issubclass(field.type_, BaseModel)):
                raise AttributeError("orm_field not found on %r (parent: %r)" % (field, pydantic_field_on_parent))

            if field.shape != SHAPE_SINGLETON:
                if field.shape == SHAPE_LIST:
                    sub_filter = filter_submodel and filter_submodel.get(orm_field) or models.Q()

                    if isinstance(orm_field, ManyToManyDescriptor):
                        relatedmanager = getattr(django_obj, orm_field.field.attname)
                        related_objs = relatedmanager.through.objects.filter(models.Q(**{relatedmanager.source_field_name: relatedmanager.instance}) & sub_filter)

                    elif isinstance(orm_field, ReverseManyToOneDescriptor):
                        relatedmanager = getattr(django_obj, orm_field.rel.name)
                        related_objs = relatedmanager.filter(sub_filter)

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

            elif not orm_field and issubclass(field.type_, BaseModel):
                values[field.name] = transfer_from_orm(pydantic_cls=field.type_, django_obj=django_obj, pydantic_field_on_parent=field)

            else:
                value = None
                try:
                    value = getattr(django_obj, orm_field.field.attname)

                except AttributeError:
                    raise  # attach debugger here ;)

                if field.required and pydantic_field_on_parent and pydantic_field_on_parent.allow_none and value is None:
                    return None

                if isinstance(orm_field.field, models.JSONField) and value:
                    if issubclass(field.type_, BaseModel):
                        if isinstance(value, dict):
                            value = field.type_.parse_obj(value)

                        else:
                            value = field.type_.parse_raw(value)

                    elif issubclass(field.type_, dict):
                        if isinstance(value, str):
                            value = json.loads(value)

                    else:
                        raise NotImplementedError

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
        name: str = Field(scopes=['elysium.addresses.update.any',])
    ```
    """
    def check(model: BaseModel, input: dict, access: Access, loc: Optional[List[str]] = None):
        if not loc:
            loc = ['body',]

        for key, value in input.items():
            if isinstance(value, dict):
                check(getattr(model, key), value, access, loc=loc + [key])

            else:
                scopes = model.__fields__[key].field_info.extra.get('scopes')
                if scopes:
                    if not access.token.has_audience(scopes):
                        raise AccessError(detail=Error(
                            type='FieldAccessError',
                            code='access_error.field',
                            detail={
                                'loc': loc + [key],
                            },
                        ))

                elif model.__fields__[key].field_info.extra.get('is_critical'):
                    if not access.token.crt:
                        raise AccessError(detail=Error(
                            type='FieldAccessError',
                            code='access_error.field_is_critical',
                            detail={
                                'loc': loc + [key],
                            },
                        ))

    check(input, input.dict(exclude_unset=True), access)


def dict_resolve_obj_to_id(input):
    if isinstance(input, models.Model):
        return input.pk

    if not isinstance(input, dict):
        return input

    for key, value in input.items():
        input[key] = dict_resolve_obj_to_id(value)

    return input


async def update_orm(model: Type[BaseModel], orm_obj: models.Model, input: BaseModel, *, access: Optional[Access] = None) -> BaseModel:
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
                attr = getattr(model, key)
                if attr is None:
                    setattr(model, key, model.__fields__[key].type_.parse_obj(value))

                else:
                    update(attr, value)

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


TDjangoModel = TypeVar('TDjangoModel', bound=models.Model)

def orm_object_validator(model: Type[TDjangoModel], value: Union[str, models.Q]) -> TDjangoModel:
    if isinstance(value, str):
        value = models.Q(id=value)

    with AllowAsyncUnsafe():
        try:
            return model.objects.get(value)

        except model.DoesNotExist:
            raise ValueError('reference_not_exist')


class DjangoORMBaseModel(BaseModel):
    @classmethod
    @sync_to_async
    def from_orm(cls, obj: models.Model, filter_submodel: Optional[Mapping[Manager, models.Q]] = None):
        return transfer_from_orm(cls, obj, filter_submodel=filter_submodel)

    class Config:
        orm_mode = True
