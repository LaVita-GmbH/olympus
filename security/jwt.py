from typing import List, Optional, Tuple
from jose import jwt
from fastapi import Depends, HTTPException
from fastapi.security import SecurityScopes
from fastapi.security.api_key import APIKeyHeader
from starlette.requests import Request


def has_audience(token: dict, audiences: List[str]) -> Optional[str]:
    for audience in audiences:
        if audience in token['aud']:
            return audience

    return


class JWTToken(APIKeyHeader):
    def __init__(
        self, *, name: str = 'Authorization', scheme_name: Optional[str] = None, auto_error: bool = True, key: str, algorithm: str, issuer: Optional[str] = None,
    ):
        self.key = key
        self.algorithms = [algorithm]
        self.issuer = issuer

        super().__init__(name=name, scheme_name=scheme_name, auto_error=auto_error)

    def decode_token(self, token, audience=None):
        try:
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

        except jwt.JWTClaimsError as error:
            raise HTTPException(status_code=401, detail=str(error)) from error

    async def __call__(self, request: Request, scopes: SecurityScopes = None) -> Optional[dict]:
        token = await super().__call__(request)
        if not token:
            return

        token_decoded = self.decode_token(token)

        if scopes:
            audience = has_audience(token_decoded, scopes.scopes)
            if not audience:
                raise HTTPException(status_code=403)

            token_decoded['aud_used'] = audience

        return token_decoded
