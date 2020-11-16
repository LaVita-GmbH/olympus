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
