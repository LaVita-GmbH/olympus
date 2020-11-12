from typing import List, Optional, Tuple
from jose import jwt
from fastapi import HTTPException
from fastapi.security import SecurityScopes
from fastapi.security.api_key import APIKeyHeader
from starlette.requests import Request
from ..schemas import Error, Access, AccessToken, AccessScope


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

        access = Access(
            token=AccessToken(**self.decode_token(token)),
        )

        if scopes:
            audience = access.token.has_audience(scopes.scopes)
            if not audience:
                raise HTTPException(status_code=403, detail=Error(
                    type='JWTClaimsError',
                    code='required_audience_missing',
                    message='The required scope is not included in the given token.',
                    detail=scopes.scopes,
                ))

            access.scope = AccessScope.from_str(audience)

        return access
