from typing import Any, Optional, List
from datetime import datetime
from pydantic import BaseModel, Field


class Access(BaseModel):
    token: 'AccessToken'
    scope: Optional['AccessScope'] = None

    user: Optional[Any] = None

    @property
    def user_id(self) -> str:
        return self.token.sub

    @property
    def tenant_id(self) -> str:
        return self.token.ten


class AccessToken(BaseModel):
    iss: str = Field(title='Issuer')
    iat: datetime = Field(title='Issued At')
    nbf: datetime = Field(title='Not Before')
    exp: datetime = Field(title='Expire At')
    sub: str = Field(title='Subject (User)')
    ten: str = Field(title='Tenant')
    aud: List[str] = Field(default=[], title='Audiences')
    jti: str = Field(title='JWT ID')

    def has_audience(self, audiences: List[str]) -> Optional[str]:
        for audience in audiences:
            if audience in self.aud:
                return audience

        return


class AccessScope(BaseModel):
    service: str
    resource: str
    action: str
    selector: Optional[str] = None

    @classmethod
    def from_str(cls, scope: str):
        scopes = scope.split('.') + [None]
        return cls(
            service=scopes[0],
            resource=scopes[1],
            action=scopes[2],
            selector=scopes[3],
        )

    def __str__(self):
        return '.'.join(filter(lambda s: s, [self.service, self.resource, self.action, self.selector,]))


Access.update_forward_refs()