import logging
from psycopg2 import InterfaceError
from django.utils.asyncio import async_unsafe
from django.db.backends.postgresql.base import DatabaseWrapper as PGSQLDatabaseWrapper, CursorDebugWrapper as BaseCursorDebugWrapper
from django.db.backends.utils import CursorWrapper as BaseCursorWrapper
from ...utils import ReconnectingCursorMixin


class CursorWrapper(ReconnectingCursorMixin, BaseCursorWrapper):
    pass


class CursorDebugWrapper(ReconnectingCursorMixin, BaseCursorDebugWrapper):
    pass


class DatabaseWrapper(PGSQLDatabaseWrapper):
    @async_unsafe
    def _reconnect(self):
        try:
            self.connection.close()

        except Exception as error:
            logging.warning(error)

        self.connection = None

        self.ensure_connection()

    @async_unsafe
    def create_cursor(self, name=None):
        try:
            return super().create_cursor(name=name)

        except InterfaceError:
            self._reconnect()
            return super().create_cursor(name=name)

    def make_cursor(self, cursor: BaseCursorWrapper) -> BaseCursorWrapper:
        cursor_wrapper = super().make_cursor(cursor)
        cursor_wrapper.__class__ = CursorWrapper
        return cursor_wrapper

    def make_debug_cursor(self, cursor: BaseCursorWrapper) -> BaseCursorDebugWrapper:
        cursor_wrapper = super().make_debug_cursor(cursor)
        cursor_wrapper.__class__ = CursorDebugWrapper
        return cursor_wrapper
