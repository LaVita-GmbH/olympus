from typing import Iterable, Union, Optional, Dict
import logging
import json
from functools import wraps
from event_consumer import message_handler as base_message_handler
from event_consumer.handlers import DEFAULT_EXCHANGE
from sentry_sdk.integrations.serverless import serverless_function
from sentry_sdk import start_transaction, last_event_id


_logger = logging.getLogger(__name__)


def transaction_captured_function(func, transaction_name: Optional[str] = None):
    @wraps(func)
    def wrapper(*args, **kwargs):
        trace_id = data = None

        try:
            if isinstance(args[0], (str, bytes)):
                try:
                    data = json.loads(args[0])

                except json.JSONDecodeError:
                    pass

            elif isinstance(args[0], dict):
                data = args[0]

            if data:
                trace_id = data.get('metadata', {}).get('flow_id')

        except IndexError:
            pass

        transaction = start_transaction(
            op='message_handler',
            name=transaction_name or f'{func.__module__}.{func.__name__}',
            trace_id=trace_id,
        )
        with transaction:
            result = func(*args, **kwargs)

        _logger.debug("Logged message handling with trace_id=%s, span_id=%s, id=%s", transaction.trace_id, transaction.span_id, last_event_id())
        return result

    return wrapper


def message_handler(
    routing_keys: Union[str, Iterable],
    queue: Optional[str] = None,
    exchange: str = DEFAULT_EXCHANGE,
    queue_arguments: Optional[Dict[str, object]] = None,
    transaction_name: Optional[str] = None
):
    def decorator(func):
        return base_message_handler(
            routing_keys=routing_keys,
            queue=queue,
            exchange=exchange,
            queue_arguments=queue_arguments,
        )(serverless_function(transaction_captured_function(func, transaction_name=transaction_name)))

    return decorator
