import os
import inspect
import json
import time
from typing import Coroutine, Mapping, Optional, Type, Union
from functools import wraps
from django.db.models.query_utils import DeferredAttribute
from pydantic import BaseModel, parse_obj_as
from pydantic.fields import ModelField, SHAPE_SINGLETON, SHAPE_LIST
from django.db import models
from django.db.models.manager import Manager
from django.db.models.fields.related_descriptors import ManyToManyDescriptor, ReverseManyToOneDescriptor
from django.utils.functional import cached_property
from ...schemas import AccessScope
from ...exceptions import AccessError
from ...security.jwt import access as access_ctx
from ..sentry import instrument_span, span as span_ctx
from ..django import AllowAsyncUnsafe
from ..asyncio import is_async

if os.getenv('USE_ASYNCIO'):
    from ..asyncio import sync_to_async

else:
    from ..sync import sync_to_async


@instrument_span(
    op='transfer_from_orm',
    description=lambda pydantic_cls, django_obj, *args, **kwargs: f'{django_obj} to {pydantic_cls.__name__}',
)
def transfer_from_orm(
    pydantic_cls: Type[BaseModel],
    django_obj: models.Model,
    django_parent_obj: Optional[models.Model] = None,
    pydantic_field_on_parent: Optional[ModelField] = None,
    filter_submodel: Optional[Mapping[Manager, models.Q]] = None,
    _async: bool = False
) -> Union[BaseModel, Coroutine[None, None, BaseModel]]:
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

    if os.getenv('TRANSFER_FROM_ORM_ASYNC') and not os.getenv('DJANGO_ALLOW_ASYNC_UNSAFE'):
        with AllowAsyncUnsafe():
            return transfer_from_orm(
                pydantic_cls=pydantic_cls,
                django_obj=django_obj,
                filter_submodel=filter_submodel,
            )

    if is_async() and not _async:
        if os.getenv('TRANSFER_FROM_ORM_ASYNC'):
            async def async_wrapper(
                pydantic_cls,
                django_obj,
                filter_submodel=None,
                django_parent_obj=None,
                pydantic_field_on_parent=None,
            ):
                return _transfer_from_orm(
                    pydantic_cls=pydantic_cls,
                    django_obj=django_obj,
                    filter_submodel=filter_submodel,
                    django_parent_obj=django_parent_obj,
                    pydantic_field_on_parent=pydantic_field_on_parent,
                    _async=True,
                )

            return async_wrapper(
                pydantic_cls=pydantic_cls,
                django_obj=django_obj,
                filter_submodel=filter_submodel,
                django_parent_obj=django_parent_obj,
                pydantic_field_on_parent=pydantic_field_on_parent,
            )

        if not os.getenv('DJANGO_ALLOW_ASYNC_UNSAFE'):
            return sync_to_async(transfer_from_orm)(
                pydantic_cls=pydantic_cls,
                django_obj=django_obj,
                filter_submodel=filter_submodel,
            )

    return _transfer_from_orm(
        pydantic_cls=pydantic_cls,
        django_obj=django_obj,
        django_parent_obj=django_parent_obj,
        pydantic_field_on_parent=pydantic_field_on_parent,
        filter_submodel=filter_submodel,
        _async=_async,
    )


def timer(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        start = time.time()
        res = func(*args, **kwargs)
        print(" ".join(["" for _ in range(len(inspect.stack(0)))]), "Call to %s took %sms" % (func.__name__, (time.time() - start) * 1000))
        return res

    return wrapper


# @timer
def _transfer_from_orm(
    pydantic_cls: Type[BaseModel],
    django_obj: models.Model,
    django_parent_obj: Optional[models.Model] = None,
    pydantic_field_on_parent: Optional[ModelField] = None,
    filter_submodel: Optional[Mapping[Manager, models.Q]] = None,
    _async: bool = False
) -> Union[BaseModel, Coroutine[None, None, BaseModel]]:
    span = span_ctx.get()
    span.set_tag('transfer_from_orm.pydantic_cls', pydantic_cls.__name__)
    span.set_tag('transfer_from_orm.django_cls', django_obj.__class__.__name__)
    span.set_data('transfer_from_orm.django_obj', django_obj)
    span.set_data('transfer_from_orm.filter_submodel', filter_submodel)
    values = {}
    for key, field in pydantic_cls.__fields__.items():
        orm_method = field.field_info.extra.get('orm_method')
        if orm_method:
            value = orm_method(django_obj)
            if value is not None and issubclass(field.type_, BaseModel) and not isinstance(value, BaseModel):
                if field.shape == SHAPE_SINGLETON:
                    if isinstance(value, models.Model):
                        value = transfer_from_orm(field.type_, value, _async=_async)

                    else:
                        value = field.type_.parse_obj(value)

                elif field.shape == SHAPE_LIST:
                    def _to_pydantic(obj):
                        if isinstance(obj, BaseModel):
                            return obj

                        if isinstance(obj, models.Model):
                            return transfer_from_orm(
                                pydantic_cls=field.type_,
                                django_obj=obj,
                                django_parent_obj=django_obj,
                                filter_submodel=filter_submodel,
                                _async=_async,
                            )

                        return field.type_.parse_obj(obj)

                    value = [
                        _to_pydantic(obj)
                        for obj in value
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

                    elif isinstance(orm_field, DeferredAttribute) and isinstance(orm_field.field, models.JSONField):
                        value = None
                        try:
                            value = getattr(django_obj, orm_field.field.attname)

                        except AttributeError:
                            raise  # attach debugger here ;)

                        values[field.name] = parse_obj_as(field.outer_type_, value or [])
                        continue

                    else:
                        raise NotImplementedError

                    values[field.name] = [
                        transfer_from_orm(
                            pydantic_cls=field.type_,
                            django_obj=rel_obj,
                            django_parent_obj=django_obj,
                            pydantic_field_on_parent=field,
                            filter_submodel=filter_submodel,
                            _async=_async,
                        ) for rel_obj in related_objs
                    ]

                else:
                    raise NotImplementedError

            elif not orm_field and issubclass(field.type_, BaseModel):
                values[field.name] = transfer_from_orm(
                    pydantic_cls=field.type_,
                    django_obj=django_obj,
                    pydantic_field_on_parent=field,
                    filter_submodel=filter_submodel,
                    _async=_async,
                )

            else:
                value = None
                is_property = isinstance(orm_field, (property, cached_property))
                is_django_field = not is_property

                try:
                    if is_property:
                        if isinstance(orm_field, property):
                            value = orm_field.fget(django_obj)

                        elif isinstance(orm_field, cached_property):
                            value = orm_field.__get__(django_obj)

                        else:
                            raise NotImplementedError

                        if isinstance(value, models.Model):
                            value = value.pk

                    else:
                        value = getattr(django_obj, orm_field.field.attname)

                except AttributeError:
                    raise  # attach debugger here ;)

                if field.required and pydantic_field_on_parent and pydantic_field_on_parent.allow_none and value is None:
                    return None

                if is_django_field and value and isinstance(orm_field.field, models.JSONField):
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

                scopes = [AccessScope.from_str(audience) for audience in field.field_info.extra.get('scopes', [])]
                if scopes:
                    try:
                        access = access_ctx.get()

                    except LookupError:
                        pass

                    else:
                        read_scopes = [str(scope) for scope in scopes if scope.action == 'read']
                        if read_scopes:
                            if not access.token.has_audience(read_scopes):
                                value = None

                            else:
                                if hasattr(django_obj, 'check_access'):
                                    for scope in scopes:
                                        if scope.action != 'read':
                                            continue

                                        try:
                                            django_obj.check_access(access, selector=scope.selector)

                                        except AccessError:
                                            value = None

                values[field.name] = value

    return pydantic_cls.construct(**values)
