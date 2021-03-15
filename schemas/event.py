from enum import Enum
import secrets
from datetime import datetime
from django.utils import timezone
from typing import Any, List, Optional
from pydantic import BaseModel, Field

def default_eid():
    return secrets.token_hex(32)

class EventMetadata(BaseModel):
    eid: str = Field(min_length=64, max_length=64, default_factory=default_eid)
    event_type: Optional[str]
    occurred_at: datetime = Field(default_factory=timezone.now)
    # received_at
    # version
    parent_eids: List[str] = Field([])
    flow_id: Optional[str] = Field(None)



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
