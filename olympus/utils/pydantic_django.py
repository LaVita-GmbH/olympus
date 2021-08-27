import json
import warnings
from typing import List, Mapping, Optional, Tuple, Type, TypeVar, Union
from enum import Enum
from asgiref.sync import sync_to_async, async_to_sync
from django.db.models.query_utils import DeferredAttribute
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, validate_model, SecretStr, parse_obj_as, Field
from pydantic.fields import ModelField, SHAPE_SINGLETON, SHAPE_LIST, Undefined
from django.db import models
from django.db.models.manager import Manager
from django.db.models.fields.related_descriptors import ManyToManyDescriptor, ReverseManyToOneDescriptor
from django.db.transaction import atomic
from django.utils.functional import cached_property
from ..schemas import Access, Error, AccessScope
from ..exceptions import AccessError
from ..security.jwt import access as access_ctx
from .sentry import instrument_span, span as span_ctx
from .django import AllowAsyncUnsafe
from .pydantic import Reference
from .asyncio import is_async


class TransferAction(Enum):
    CREATE = 'CREATE'
    SYNC = 'SYNC'
    NO_SUBOBJECTS = 'NO_SUBOBJECTS'


@instrument_span(
    op='transfer_to_orm',
    description=lambda pydantic_obj, django_obj, *args, **kwargs: f'{pydantic_obj} to {django_obj}',
)
def transfer_to_orm(
    pydantic_obj: BaseModel,
    django_obj: models.Model,
    *,
    action: Optional[TransferAction] = None,
    exclude_unset: bool = False,
    access: Optional[Access] = None,
    created_submodels: Optional[list] = None,
    _just_return_objs: bool = False,
) -> Optional[Tuple[List[models.Model], List[models.Model]]]:
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
    if is_async():
        return sync_to_async(transfer_to_orm)(
            pydantic_obj=pydantic_obj,
            django_obj=django_obj,
            action=action,
            exclude_unset=exclude_unset,
            access=access,
            created_submodels=created_submodels,
        )

    span = span_ctx.get()
    span.set_tag('transfer_to_orm.action', action)
    span.set_tag('transfer_to_orm.exclude_unset', exclude_unset)
    span.set_data('transfer_to_orm.access', access)
    span.set_data('transfer_to_orm.pydantic_obj', pydantic_obj)
    span.set_data('transfer_to_orm.django_obj', django_obj)

    if created_submodels:
        warnings.warn("Use transfer_to_orm with kwarg action instead of created_submodels", category=DeprecationWarning)
        action = TransferAction.CREATE

    if not action:
        warnings.warn("Use transfer_to_orm with kwarg action", category=DeprecationWarning)

    subobjects = created_submodels or []
    existing_objects = []

    if access:
        check_field_access(pydantic_obj, access)

    pydantic_values: Optional[dict] = pydantic_obj.dict(exclude_unset=True) if exclude_unset else None

    def populate_default(pydantic_cls, django_obj):
        for key, field in pydantic_cls.__fields__.items():
            orm_field = field.field_info.extra.get('orm_field')
            if not orm_field and issubclass(field.type_, BaseModel):
                populate_default(field.type_, django_obj)

            else:
                if 'orm_field' in field.field_info.extra and field.field_info.extra['orm_field'] is None:
                    # Do not raise error when orm_field was explicitly set to None
                    continue

                assert orm_field, "orm_field not set on %r of %r" % (field, pydantic_cls)

                setattr(
                    django_obj,
                    orm_field.field.attname,
                    field.field_info.default if field.field_info.default is not Undefined and field.field_info.default is not ... else None,
                )

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
        if field.shape == SHAPE_SINGLETON:
            if not orm_field and issubclass(field.type_, BaseModel):
                if value is None:
                    if exclude_unset and key not in pydantic_values:
                        continue

                    populate_default(field.type_, django_obj)

                elif isinstance(value, BaseModel):
                    sub_transfer = transfer_to_orm(pydantic_obj=value, django_obj=django_obj, exclude_unset=exclude_unset, access=access, action=action, _just_return_objs=True)
                    subobjects += sub_transfer[0]
                    existing_objects += sub_transfer[1]

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

        elif field.shape == SHAPE_LIST:
            if not value:
                continue

            elif isinstance(orm_field, ManyToManyDescriptor):
                relatedmanager = getattr(django_obj, orm_field.field.attname)
                related_model = relatedmanager.through
                obj_fields = {relatedmanager.source_field_name: django_obj}
                existing_object_ids = set()
                if action == TransferAction.SYNC:
                    existing_object_ids = set(related_model.objects.filter(**obj_fields).values_list('id', flat=True))

                for val in value:
                    def get_subobj(force_create: bool = False):
                        obj_manytomany_fields = {**obj_fields}
                        if getattr(val, 'id', None):
                            obj_manytomany_fields[relatedmanager.target_field.attname] = val.id

                        else:
                            raise NotImplementedError

                        if force_create or action == TransferAction.CREATE:
                            return related_model(**obj_manytomany_fields)

                        elif action == TransferAction.SYNC:
                            try:
                                return related_model.objects.get(**obj_manytomany_fields)

                            except related_model.DoesNotExist:
                                return get_subobj(force_create=True)

                        else:
                            raise NotImplementedError

                    sub_obj = get_subobj()
                    existing_object_ids.discard(sub_obj.id)
                    subobjects.append(sub_obj)
                    sub_transfer = transfer_to_orm(val, sub_obj, exclude_unset=exclude_unset, access=access, action=action, _just_return_objs=True)
                    subobjects += sub_transfer[0]
                    existing_objects += sub_transfer[1]

                existing_objects += related_model.objects.filter(id__in=list(existing_object_ids))

            elif isinstance(orm_field, ReverseManyToOneDescriptor):
                relatedmanager = getattr(django_obj, orm_field.rel.name)
                related_model: Type[models.Model] = relatedmanager.field.model
                obj_fields = {relatedmanager.field.name: django_obj}

                existing_object_ids = set()
                if action == TransferAction.SYNC:
                    existing_object_ids = set(related_model.objects.filter(**obj_fields).values_list('id', flat=True))

                val: BaseModel
                for val in value:
                    def get_subobj(force_create: bool = False):
                        if action == TransferAction.SYNC and not getattr(val, 'id', None) and not 'sync_matching' in field.field_info.extra:
                            force_create = True

                        if force_create or action == TransferAction.CREATE:
                            create_fields = {}
                            if getattr(val, 'id', None):
                                create_fields['id'] = getattr(val, 'id', None)

                            return related_model(**obj_fields, **create_fields)

                        elif action == TransferAction.SYNC:
                            try:
                                if getattr(val, 'id', None):
                                    return related_model.objects.get(id=val.id, **obj_fields)

                                elif 'sync_matching' in field.field_info.extra:
                                    matching = field.field_info.extra['sync_matching']
                                    if isinstance(matching, list):
                                        matching_search = models.Q()
                                        pydantic_field_name: str
                                        match_orm_field: models.Field
                                        for pydantic_field_name, match_orm_field in matching:
                                            match_value = val
                                            for _field in pydantic_field_name.split('.'):
                                                match_value = getattr(match_value, _field)

                                            if isinstance(match_value, Reference):
                                                match_value = match_value.id

                                            matching_search &= models.Q(**{match_orm_field.field.attname: match_value})

                                        return related_model.objects.filter(**obj_fields).get(matching_search)

                                    elif isinstance(matching, callable):
                                        raise NotImplementedError

                                    else:
                                        raise NotImplementedError

                                else:
                                    raise NotImplementedError

                            except related_model.DoesNotExist:
                                return get_subobj(force_create=True)

                        else:
                            raise NotImplementedError

                    sub_obj = get_subobj()
                    existing_object_ids.discard(sub_obj.id)
                    subobjects.append(sub_obj)
                    sub_transfer = transfer_to_orm(val, sub_obj, exclude_unset=exclude_unset, access=access, action=action, _just_return_objs=True)
                    subobjects += sub_transfer[0]
                    existing_objects += sub_transfer[1]

                existing_objects += related_model.objects.filter(id__in=list(existing_object_ids))

            else:
                raise NotImplementedError

        else:
            raise NotImplementedError

    if subobjects and not action:
        raise AssertionError('action is not defined but subobjects exist')

    if _just_return_objs:
        return subobjects, existing_objects

    if action in (TransferAction.CREATE, TransferAction.SYNC, TransferAction.NO_SUBOBJECTS) and created_submodels is None:
        with atomic():
            django_obj.save()

            if action != TransferAction.NO_SUBOBJECTS:
                for obj in subobjects:
                    obj.save()

                if action == TransferAction.SYNC:
                    for obj in existing_objects:
                        obj.delete()


transfer_to_orm_async = sync_to_async(transfer_to_orm)


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
                        value = async_to_sync(field.type_.from_orm)(value)

                    else:
                        value = field.type_.parse_obj(value)

                elif field.shape == SHAPE_LIST:
                    def _to_pydantic(obj):
                        if isinstance(obj, BaseModel):
                            return obj

                        if isinstance(obj, models.Model):
                            return async_to_sync(field.type_.from_orm)(obj)

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
                            pydantic_field_on_parent=field
                        ) for rel_obj in related_objs
                    ]

                else:
                    raise NotImplementedError

            elif not orm_field and issubclass(field.type_, BaseModel):
                values[field.name] = transfer_from_orm(pydantic_cls=field.type_, django_obj=django_obj, pydantic_field_on_parent=field)

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
                try:
                    check(getattr(model, key), value, access, loc=loc + [key])

                except AttributeError:
                    pass

            elif key in model.__fields__:
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
    warnings.warn("Use transfer_to_orm with exclude_unset=True instead of this function", category=DeprecationWarning)

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

    access = access_ctx.get()
    if access and hasattr(model, 'tenant_id'):
        value &= models.Q(tenant_id=access.tenant_id)

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
