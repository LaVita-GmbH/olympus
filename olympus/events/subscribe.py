import warnings
import logging
import json
from typing import Type, TypeVar, Union, Iterable, Optional, Dict
from event_consumer.handlers import DEFAULT_EXCHANGE
from event_consumer.conf import settings
from pydantic import BaseModel
from django.db import models
from ..handlers.event_consumer import message_handler
from ..utils import transfer_to_orm
from ..schemas import DataChangeEvent


TBaseModel = TypeVar('TBaseModel', bound=BaseModel)
TDjangoModel = TypeVar('TDjangoModel', bound=models.Model)


class EventSubscription:
    __orm_obj: Optional[TDjangoModel] = None

    def __init_subclass__(
        cls,
        event_schema: Type[TBaseModel],
        orm_model: Type[TDjangoModel],
        routing_keys: Union[str, Iterable],
        queue: Optional[str] = None,
        exchange: str = DEFAULT_EXCHANGE,
        queue_arguments: Optional[Dict[str, object]] = None,
        **kwargs,
    ):
        super().__init_subclass__(**kwargs)
        cls.event_schema = event_schema
        cls.orm_model = orm_model
        cls.routing_keys = routing_keys
        cls.queue = queue
        cls.exchange = exchange
        cls.queue_arguments = queue_arguments
        cls.logger = logging.getLogger(f'{cls.__module__}.{cls.__name__}')

        message_handler(
            routing_keys=cls.routing_keys,
            queue=cls.queue,
            exchange=cls.exchange,
            queue_arguments=cls.queue_arguments,
        )(cls.handle)

        if not hasattr(cls.orm_model, 'updated_at'):
            warnings.warn("%s has no field 'updated_at'" % cls.orm_model)

        cls.is_tenant_bound = hasattr(cls.orm_model, 'tenant_id')

        cls.logger.debug(
            "Registered EventSubscription %r with event_schema %r and orm_model %r with queue '%s' on exchange '%s'",
            cls,
            cls.event_schema,
            cls.orm_model,
            cls.queue,
            cls.exchange,
        )

    @classmethod
    def handle(cls, body):
        instance = cls(body)
        instance.process()

    def __init__(self, body):
        self.body = body
        self.event = DataChangeEvent.parse_raw(self.body) if isinstance(self.body, (bytes, str)) else DataChangeEvent.parse_obj(self.body)

    def process(self):
        if self.event.data_op == DataChangeEvent.DataOperation.DELETE:
            self.op_delete()

        else:
            self.op_create_or_update()

    @property
    def orm_obj(self) -> TDjangoModel:
        if not self.__orm_obj:
            query = models.Q(id=json.loads(self.body).get('id'))
            if self.is_tenant_bound:
                query &= models.Q(tenant_id=self.event.tenant_id)

            self.__orm_obj = self.orm_model.objects.get(query)

        return self.__orm_obj

    @orm_obj.setter
    def orm_obj(self, value):
        self.__orm_obj = value

    def create_orm_obj(self, data: TBaseModel):
        fields = {'id': models.Q(id=data.id)}
        if self.is_tenant_bound:
            fields['tenant_id'] = self.event.tenant_id

        self.orm_obj = self.orm_model(**fields)

    def op_delete(self):
        try:
            self.orm_obj.delete()

        except self.orm_model.DoesNotExist:
            pass

    def op_create_or_update(self):
        data: TBaseModel = self.event_schema.parse_obj(self.event.data)
        try:
            try:
                if self.orm_obj.updated_at > self.event.metadata.occurred_at:
                    self.logger.warning("Received data older than last record update for %s. Discarding change!", self.orm_obj)
                    return

            except AttributeError:
                pass

        except self.orm_model.DoesNotExist:
            self.create_orm_obj(data)

        transfer_to_orm(data, self.orm_obj)
        self.orm_obj.save()
