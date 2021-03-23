from typing import Iterable, Union, Optional, Dict
from event_consumer import message_handler as base_message_handler
from event_consumer.handlers import DEFAULT_EXCHANGE
from sentry_sdk.integrations.serverless import serverless_function


def message_handler(
    routing_keys: Union[str, Iterable],
    queue: Optional[str] = None,
    exchange: str = DEFAULT_EXCHANGE,
    queue_arguments: Optional[Dict[str, object]] = None,
):
    def decorator(func):
        return base_message_handler(
            routing_keys=routing_keys,
            queue=queue,
            exchange=exchange,
            queue_arguments=queue_arguments,
        )(serverless_function(func))

    return decorator
