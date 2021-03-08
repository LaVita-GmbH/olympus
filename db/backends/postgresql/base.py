import logging
from psycopg2 import InterfaceError
from django.utils.asyncio import async_unsafe
from django.db.backends.postgresql.base import DatabaseWrapper as PGSQLDatabaseWrapper


class DatabaseWrapper(PGSQLDatabaseWrapper):
    @async_unsafe
    def create_cursor(self, name=None):
        try:
            return super().create_cursor(name=name)

        except InterfaceError:
            try:
                self.connection.close()

            except Exception as error:
                logging.warning(error)

            self.connection = None

            self.ensure_connection()
            return super().create_cursor(name=name)
