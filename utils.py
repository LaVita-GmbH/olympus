import os
from typing import Optional, Type
from pydantic import BaseModel
from django.db import models
from pydantic.fields import ModelField


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


def transfer_from_orm(pydantic_cls: Type[BaseModel], django_obj: models.Model, pydantic_field_on_parent: Optional[ModelField] = None) -> BaseModel:
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
        if issubclass(field.type_, BaseModel):
            values[field.name] = transfer_from_orm(pydantic_cls=field.type_, django_obj=django_obj, pydantic_field_on_parent=field)

        else:
            orm_field = field.field_info.extra.get('orm_field')
            if not orm_field:
                if 'orm_field' in field.field_info.extra and field.field_info.extra['orm_field'] is None:
                    # Do not raise error when orm_field was explicitly set to None
                    continue

                raise AttributeError("orm_field not found on %r" % field)

            value = getattr(django_obj, orm_field.field.attname)
            if field.required and pydantic_field_on_parent and pydantic_field_on_parent.allow_none and value is None:
                return None

            values[field.name] = value

    return pydantic_cls.construct(**values)


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
