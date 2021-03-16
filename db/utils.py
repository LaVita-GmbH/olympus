from django.db.utils import OperationalError


class ReconnectingCursorMixin:
    def _execute_with_wrappers(self, sql, params, many, executor):
        try:
            return super()._execute_with_wrappers(sql, params, many, executor)

        except OperationalError as error:
            self.db._reconnect()
            self.cursor.close()
            self.cursor = self.db.create_cursor()
            return super()._execute_with_wrappers(sql, params, many, executor)
