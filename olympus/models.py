from typing import Optional, Callable
from django.db import models
from django.db.transaction import atomic
from .schemas import Access
from .exceptions import AccessError


class ModelAtomicSave(models.Model):
    @atomic
    def save(self, *args, **kwargs):
        return super().save(*args, **kwargs)

    class Meta:
        abstract = True


class AccessMixin(models.Model):
    def check_access(self, access: Access, selector: Optional[str] = None, action: Optional[str] = None):
        try:
            if access.tenant_id != self.tenant_id:
                raise AccessError

        except AttributeError:
            # Model is not tenant-specific
            pass

        if not selector:
            selector = access.scope.selector

        try:
            selector_check: Callable = getattr(self, f'_check_access_{selector}')

        except AttributeError as error:
            raise AccessError from error

        selector_check(access=access, action=action)

    class Meta:
        abstract = True
