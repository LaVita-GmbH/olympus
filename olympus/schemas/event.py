from enum import Enum
import secrets
from datetime import datetime
from django.utils import timezone
from typing import Any, List, Optional
from pydantic import BaseModel, Field
try:
    import sentry_sdk

except ImportError:
    sentry_sdk = None

from ..security.jwt import access as access_ctx


def default_eid():
    return secrets.token_hex(32)


def _get_flow_id():
    if sentry_sdk:
        try:
            return sentry_sdk.Hub.current.scope.transaction.trace_id

        except (KeyError, AttributeError, IndexError, TypeError):
            pass

    return None


def _get_uid() -> Optional[str]:
    try:
        return access_ctx.get().user_id

    except LookupError:
        return

def _get_scopes() -> list:
    try:
        return list(access_ctx.get().token.get_scopes())

    except LookupError:
        return []


class EventMetadata(BaseModel):
    eid: str = Field(min_length=64, max_length=64, default_factory=default_eid)
    event_type: Optional[str]
    occurred_at: datetime = Field(default_factory=timezone.now)
    # received_at
    # version
    uid: Optional[str] = Field(default_factory=_get_uid)
    scopes: List[str] = Field(default_factory=_get_scopes)
    parent_eids: List[str] = Field([])
    flow_id: Optional[str] = Field(default_factory=_get_flow_id)



class GeneralEvent(BaseModel):
    metadata: EventMetadata = Field(default_factory=EventMetadata)


class DataChangeEvent(GeneralEvent):
    class DataOperation(Enum):
        CREATE = 'C'
        UPDATE = 'U'
        DELETE = 'D'
        SNAPSHOT = 'S'

    data: Any
    data_type: str
    data_op: DataOperation
    tenant_id: Optional[str]
