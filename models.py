from django.db import models
from django.db.transaction import atomic


class ModelAtomicSave(models.Model):
    @atomic
    def save(self, *args, **kwargs):
        return super().save(*args, **kwargs)

    class Meta:
        abstract = True
