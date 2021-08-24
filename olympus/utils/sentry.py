import inspect
from functools import wraps
from typing import Callable, Union
from sentry_sdk import start_span
from sentry_sdk.tracing import Span
from contextvars import ContextVar


span: ContextVar[Span] = ContextVar('span')


def instrument_span(op: str, description: Union[str, Callable], **instrument_kwargs):
    def wrapper(wrapped):
        @wraps(wrapped)
        def with_instrumentation(*args, **kwargs):
            with start_span(
                op=op,
                description=description(*args, **kwargs) if callable(description) else description,
                **instrument_kwargs,
            ) as _span:
                span.set(_span)

                return wrapped(*args, **kwargs)

        return with_instrumentation

    return wrapper
