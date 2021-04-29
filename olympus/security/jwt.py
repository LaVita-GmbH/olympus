from typing import List, Optional, Tuple
from contextvars import ContextVar
from jose import jwt
from fastapi import HTTPException
from fastapi.security import SecurityScopes
from fastapi.security.api_key import APIKeyHeader
from starlette.requests import Request
from ..schemas import Error, Access, AccessToken, AccessScope


access: ContextVar[Access] = ContextVar('access')


class JWTToken(APIKeyHeader):
    def __init__(
        self, *, name: str = 'Authorization', scheme_name: Optional[str] = None, auto_error: bool = True, key: str, algorithm: str, issuer: Optional[str] = None,
    ):
        self.key = key
        self.algorithms = [algorithm]
        self.issuer = issuer

        super().__init__(name=name, scheme_name=scheme_name, auto_error=auto_error)

    def decode_token(self, token, audience=None):
        return jwt.decode(
            token=token,
            key=self.key,
            algorithms=self.algorithms,
            issuer=self.issuer,
            audience=audience,
            options={
                'verify_aud': bool(audience),
            },
        )

    async def __call__(self, request: Request, scopes: SecurityScopes = None) -> Optional[Access]:
        token = await super().__call__(request)
        if not token:
            return

        current_access = Access(
            token=AccessToken(**self.decode_token(token)),
        )

        if scopes:
            audiences = current_access.token.has_audiences(scopes.scopes)
            if not audiences:
                raise HTTPException(status_code=403, detail=Error(
                    type='JWTClaimsError',
                    code='required_audience_missing',
                    message='The required scope is not included in the given token.',
                    detail=scopes.scopes,
                ))

            aud_scopes = [AccessScope.from_str(audience) for audience in audiences]
            current_access.scopes = aud_scopes
            current_access.scope = aud_scopes[0]

        access.set(current_access)

        return current_access
