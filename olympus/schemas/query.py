from typing import List, Union
from pydantic import BaseModel
from django.db.models import Q, QuerySet
from django.db.models.manager import BaseManager


class Pagination(BaseModel):
    limit: int
    offset: int
    order_by: List[str]

    def query(self, objects: Union[BaseManager, QuerySet], q_filters: Q) -> QuerySet:
        """
        Filter a given model's BaseManager or pre-filtered Queryset with the given q_filters and apply order_by and offset/limit from the pagination.
        """
        return objects.filter(q_filters).order_by(*self.order_by)[self.offset:self.limit]
