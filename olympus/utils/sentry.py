import threading
from functools import wraps
from typing import Callable, Optional, Union
from sentry_sdk import start_span
from sentry_sdk.tracing import Span
from contextvars import ContextVar


span: ContextVar[Span] = ContextVar('span')


def instrument_span(op: str, description: Optional[Union[str, Callable]] = None, **instrument_kwargs):
    def wrapper(wrapped):
        @wraps(wrapped)
        def with_instrumentation(*args, **kwargs):
            with start_span(
                op=op,
                description=description(*args, **kwargs) if callable(description) else description,
                **instrument_kwargs,
            ) as _span:
                try:
                    _span.set_data("threading.current_thread", threading.current_thread().getName())

                except Exception:
                    pass

                span.set(_span)

                return wrapped(*args, **kwargs)

        return with_instrumentation

    return wrapper
