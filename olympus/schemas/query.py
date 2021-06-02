from typing import List, Union
from pydantic import BaseModel
from django.db import models


class Pagination(BaseModel):
    limit: int
    offset: int
    order_by: List[str]

    def query(self, objects: Union[models.BaseManager, models.QuerySet], q_filters: models.Q) -> models.QuerySet:
        """
        Filter a given model's BaseManager or pre-filtered Queryset with the given q_filters and apply order_by and offset/limit from the pagination.
        """
        return objects.filter(q_filters).order_by(*self.order_by)[self.offset:self.limit]
