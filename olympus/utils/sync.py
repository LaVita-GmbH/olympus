from typing import Callable
from functools import wraps
from asgiref import sync
from .sentry import instrument_span, span as span_ctx


def sync_to_async(callable: Callable, **wrapper_kwargs):
    @wraps(callable)
    @instrument_span('sync_to_async')
    def wrapper(*args, **kwargs):
        return sync.sync_to_async(
            instrument_span(
                'sync_to_async.callable',
                description=callable.__name__,
            )(callable),
        **wrapper_kwargs)(*args, **kwargs)

    return wrapper

def async_to_sync(callable: Callable, **wrapper_kwargs):
    @wraps(callable)
    @instrument_span('async_to_sync')
    def wrapper(*args, **kwargs):
        return sync.async_to_sync(
            instrument_span(
                'async_to_sync.callable',
                description=callable.__name__,
            )(callable),
        **wrapper_kwargs)(*args, **kwargs)

    return wrapper
