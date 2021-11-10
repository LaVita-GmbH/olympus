import logging
from typing import Tuple, Type, TypeVar, Union, TYPE_CHECKING
from functools import partial
from kombu import Exchange, Connection
from pydantic import BaseModel
from django.dispatch import receiver, Signal
from django.db.models.signals import post_save, post_delete
from django.db import models
from ..utils.pydantic_django import transfer_from_orm
from ..utils.sentry import instrument_span, span as span_ctx, capture_exception
from ..schemas import DataChangeEvent, EventMetadata
from ..utils.typing import with_typehint
from ..utils.django import on_transaction_complete


TBaseModel = TypeVar('TBaseModel', bound=BaseModel)
TDjangoModel = TypeVar('TDjangoModel', bound=models.Model)


class EventPublisher:
    action = 'update'

    def __init_subclass__(
        cls,
        orm_model: Type[TDjangoModel],
        event_schema: Type[TBaseModel],
        connection: Connection,
        exchange: Union[Exchange, Tuple[str, Connection], Tuple[str, Connection, dict]],
        data_type: str,
        is_changed_included: bool = False,
        version: str = 'v1',
        type: str = 'data',
        **kwargs,
    ):
        super().__init_subclass__(**kwargs)
        if not isinstance(exchange, Exchange):
            exchange_options = {
                'name': exchange[0],
                'type': 'topic',
                'durable': True,
                'channel': exchange[1].channel(),
                'delivery_mode': Exchange.PERSISTENT_DELIVERY_MODE,
            }
            if len(exchange) > 2:
                exchange_options.update(exchange[2])

            cls.exchange = Exchange(**exchange_options)

        else:
            cls.exchange: Exchange = exchange

        cls.connection = connection

        cls.orm_model = orm_model
        cls.event_schema = event_schema
        cls.data_type = data_type
        cls.version = version
        cls.type = type
        cls.is_changed_included = is_changed_included
        cls.is_tenant_bound = hasattr(cls.orm_model, 'tenant_id')
        cls.logger = logging.getLogger(f'{cls.__module__}.{cls.__name__}')

        cls.register()
        cls.logger.info("Registered EventPublisher %s", cls.__name__)

    @classmethod
    def register(cls):
        raise NotImplementedError

    @classmethod
    @on_transaction_complete()
    @instrument_span(
        op='EventPublisher',
        description=lambda cls, sender, instance, signal, **kwargs: f'{cls} for {instance} via {signal}',
    )
    def handle(cls, sender, instance: TDjangoModel, signal: Signal, **kwargs):
        cls.logger.debug("%s.handle from %s with %s for %s", cls, sender, signal, instance)
        instance = cls(sender, instance, signal, **kwargs)
        instance.process()

    def __init__(self, sender, instance: TDjangoModel, signal: Signal, **kwargs):
        self.sender = sender
        self.instance = instance
        self.signal = signal
        self.kwargs = kwargs

    def get_keys(self):
        return [
            self.version,
            self.type,
            self.action
        ]

    @property
    def routing_key(self):
        keys = self.get_keys()

        if self.is_tenant_bound:
            keys.append(self.instance.tenant_id)

        return '.'.join(keys)

    def get_metadata(self) -> EventMetadata:
        return EventMetadata()

    def get_data_op(self) -> DataChangeEvent.DataOperation:
        return DataChangeEvent.DataOperation.UPDATE

    def get_body(self) -> DataChangeEvent:
        data = transfer_from_orm(self.event_schema, self.instance).dict(by_alias=True)

        if self.is_changed_included:
            modified = self.instance.get_dirty_fields(check_relationship=True)
            data['_changed'] = [
                {
                    'name': field,
                } for field, _value in modified.items()
            ]

        return DataChangeEvent(
            data=data,
            data_type=self.data_type,
            data_op=self.get_data_op(),
            tenant_id=self.instance.tenant_id if self.is_tenant_bound else None,
            metadata=self.get_metadata(),
        )

    def get_retry_policy(self):
        return {
            'max_retries': 3,
        }

    @capture_exception
    def process(self):
        span = span_ctx.get()
        span.set_tag('exchange', self.exchange)
        span.set_tag('routing_key', self.routing_key)
        span.set_tag('sender', self.sender)
        span.set_tag('signal', self.signal)
        span.set_tag('orm_model', self.orm_model)

        self.logger.debug("Publish DataChangeEvent for %s with schema %s on %r", self.orm_model, self.event_schema, self.exchange)
        self.connection.Producer(exchange=self.exchange).publish(
            retry=True,
            retry_policy=self.get_retry_policy(),
            body=self.get_body().json(),
            content_type='application/json',
            routing_key=self.routing_key,
        )


class DataChangePublisher(with_typehint(EventPublisher)):
    @property
    def action(self):
        if self.signal == post_save:
            return 'create' if self.kwargs.get('created') else 'update'

        elif self.signal == post_delete:
            return 'delete'

    def get_data_op(self) -> DataChangeEvent.DataOperation:
        return getattr(DataChangeEvent.DataOperation, self.action.upper())

    @classmethod
    def register(cls):
        cls._handle_post_save = partial(cls.handle, signal=post_save)
        receiver(post_save, sender=cls.orm_model)(cls._handle_post_save)

        cls._handle_post_delete = partial(cls.handle, signal=post_delete)
        receiver(post_delete, sender=cls.orm_model)(cls._handle_post_delete)

        cls.logger.debug("Registered post_save + post_delete handlers for %s", cls.orm_model)


class StatusChangePublisher(with_typehint(EventPublisher)):
    @property
    def action(self):
        return str(self.instance.status).lower()

    @classmethod
    def register(cls):
        cls._handle_status_change = partial(cls.handle, signal=cls.orm_model.STATUS_CHANGE)
        receiver(cls.orm_model.STATUS_CHANGE, sender=cls.orm_model)(cls._handle_status_change)

        cls.logger.debug("Registered status_change handlers for %s", cls.orm_model)
