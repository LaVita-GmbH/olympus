from typing import Optional, Tuple
from . import Client


class OlympClient(Client):
    DEFAULT_AUTH = 'transaction'

    class Request(Client.Request):
        def __init__(self, client, method, endpoint, timeout: Optional[int], return_plain_response: bool, other_ok_states: Optional[Tuple[int]], **kwargs):
            if 'auth' in kwargs:
                self.auth = kwargs.pop('auth')

            else:
                self.auth = client.DEFAULT_AUTH

            super().__init__(client, method, endpoint, timeout=timeout, return_plain_response=return_plain_response, other_ok_states=other_ok_states, **kwargs)

        def _get_headers(self) -> dict:
            headers = super()._get_headers()

            if self.auth:
                if not self.client._tokens.get(self.auth):
                    getattr(self.client, f'auth_{self.auth}')()

                headers['Authorization'] = self.client._tokens[self.auth]

            return headers

        def _handle_response(self):
            if self._response.status_code == 401:
                if self._response_data and self._response_data.get('detail', {}).get('type') in 'ExpiredSignatureError':
                    # Token has expired, retry request
                    # delete  token so a new token is fetched before doing the action request
                    del self.client._tokens[self.auth]

                    return self.perform()

            if self.return_plain_response:
                return self._response

            if not self._response.ok and self._response.status_code not in self.other_ok_states:
                if self._response_data:
                    error_type = self._response_data.get('detail', {}).get('type') if self._response_data else "Unknown"
                    raise self.APIError(self, error_type, self._response_data)

                raise self.APIError(self, self._response.text)

            if self._response_data:
                return self._response_data

            return None

    def __init__(self, url, *, timeout=10, verify=True, user: Optional[Tuple[str, str, str]] = None, access_token: Optional[str] = None):
        super().__init__(url, timeout=timeout, verify=verify)

        self._user = user
        self._access_token = access_token

        assert user or access_token, "user or access_token must be given"

        self._tokens = {}

    def auth_user(self):
        data = self.access.auth.user.post(auth=None, json={
            'email': self._user[0],
            'password': self._user[1],
            'tenant': {
                'id': self._user[2],
            },
        })

        self._tokens['user'] = data['token']['user']

    def auth_transaction(self):
        data = self.access.auth.transaction.post(auth=None if self._access_token else 'user', json={
            'access_token': self._access_token,
        })

        self._tokens['transaction'] = data['token']['transaction']
