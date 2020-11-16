import os
from typing import Type
from pydantic import BaseModel
from django.db import models


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
    for key, field in pydantic_obj.fields.items():
        py_field = getattr(pydantic_obj, field.name)
        if isinstance(py_field, BaseModel):
            transfer_to_orm(pydantic_obj=py_field, django_obj=django_obj)

        else:
            orm_field = field.field_info.extra.get('orm_field')
            if not orm_field:
                raise AttributeError("orm_field not found on %r" % field)

            setattr(django_obj, orm_field.field.attname, py_field)


def transfer_from_orm(pydantic_cls: Type[BaseModel], django_obj: models.Model) -> BaseModel:
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
            values[field.name] = transfer_from_orm(pydantic_cls=field.type_, django_obj=django_obj)

        else:
            orm_field = field.field_info.extra.get('orm_field')
            if not orm_field:
                raise AttributeError("orm_field not found on %r" % field)

            values[field.name] = getattr(django_obj, orm_field.field.attname)

    return pydantic_cls(**values)


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
