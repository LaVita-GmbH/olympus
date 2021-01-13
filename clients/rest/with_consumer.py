from typing import Tuple, Optional
from . import Client


class Style2019ConsumerClient(Client):
    DEFAULT_AUTH = 'consumer'

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
                if self.auth == 'consumer' and not self.client._tokens.get('consumer'):
                    self.client.auth_consumer()

                headers['Authorization'] = 'Bearer %s' % self.client._tokens[self.auth]

            return headers

        def _handle_response(self):
            if self._response.status_code == 401:
                if self._response_data and self._response_data.get('error', {}).get('type') in 'ExpiredSignatureError':
                    # Token has expired, retry request
                    # delete consumer token so a new token is fetched before doing the action request
                    del self.client._tokens[self.auth]

                    return self.perform()

            if self.return_plain_response:
                return self._response

            if not self._response.ok and self._response.status_code not in self.other_ok_states:
                if self._response_data:
                    error_type = self._response_data.get('error', {}).get('type') if self._response_data else "Unknown"
                    if 'error' in self._response_data:
                        raise self.APIError(self, error_type, self._response_data['error'])

                    raise self.APIError(self, error_type)

                raise self.APIError(self, self._response.text)

            if self._response_data and self._response_data.get('data'):
                return self._response_data['data']

            return None

    def __init__(self, url, *, timeout=10, verify=True, consumer: Tuple[str, str]):
        super().__init__(url, timeout=timeout, verify=verify)

        self._consumer = consumer
        self._tokens = {}

    def auth_consumer(self):
        data = self.request('POST', '/auth/consumer', auth=None, json={
            'uid': self._consumer[0],
            'key': self._consumer[1],
        })

        self._tokens['consumer'] = data['token']
