import os
import logging
from asyncio import Future
from inspect import CO_COROUTINE
from functools import wraps
from typing import Callable, Optional
from django.db import transaction
from .asyncio import is_async


class AllowAsyncUnsafe:
    def __init__(self):
        self._django_allow_async_unsafe_before = os.environ.get('DJANGO_ALLOW_ASYNC_UNSAFE')

    def __enter__(self):
        os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = '1'

    def __exit__(self, type, value, traceback):
        if self._django_allow_async_unsafe_before is None:
            del os.environ['DJANGO_ALLOW_ASYNC_UNSAFE']

        else:
            os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = self._django_allow_async_unsafe_before


def on_transaction_complete(awaitable: bool = False, callback: Optional[Callable] = None, error_callback: Optional[Callable] = None):
    def wrapper(callable):
        @wraps(callable)
        def wrapped(*args, **kwargs):
            is_async_ = is_async()
            if is_async_ and not awaitable:
                raise AssertionError("Cannot call not awaitable from async context")

            elif awaitable and not is_async_:
                raise AssertionError("Cannot call awaitable from sync context")

            future = Future() if awaitable else None
            def call():
                try:
                    result = callable(*args, **kwargs)
                    if awaitable:
                        future.set_result(result)

                    elif callback:
                        callback(result)

                except Exception as error:
                    if awaitable:
                        future.set_exception(error)

                    elif error_callback:
                        error_callback(error)

                    else:
                        logging.exception(error, exc_info=True, stack_info=True)
                        raise

            if not transaction.get_connection().in_atomic_block:
                call()

            else:
                transaction.on_commit(call)

            return future

        if awaitable:
            wrapped.__code__.co_flags &= CO_COROUTINE

        return wrapped

    return wrapper
