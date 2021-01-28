import json
from typing import Optional, Tuple
import requests


class Client:
    class Endpoint:
        """
        API Endpoint
        Represents a pythonic traversable representation of the api url
        To access an endpoint, use the name of the path segments as attribute/key when calling this object.
        For easy access of the HTTP Methods, each HTTP Method has a corresponding method on Endpoint.
        All arguments you are passing to the method will be passed to `Client.request` and further on to `requests.request`.

        Example:
        endpoint = Endpoint(my_client)  # This is the base endpoint, as it has no path
        cart = endpoint.cart.post(json={"my": "data"})  # Calls POST /cart
        endpoint.cart[cart['id']].get()  # Calls GET /cart/{id}

        And so on...
        It is possible to go as far in depth as you have to.
        """
        def __init__(self, client, path=[]):
            self.client: Client = client
            self.path = path
            self.endpoint = "/" + "/".join([str(el) for el in self.path])

        def __str__(self):
            return f"Endpoint({self.client}: {self.endpoint})"

        def _extend_path(self, name):
            return self.__class__(
                client=self.client,
                path=self.path + [name],
            )

        def get(self, **kwargs):
            return self.client.request(
                method="get",
                endpoint=self.endpoint,
                **kwargs,
            )

        def post(self, **kwargs):
            return self.client.request(
                method="post",
                endpoint=self.endpoint,
                **kwargs,
            )

        def head(self, **kwargs):
            return self.client.request(
                method="get",
                endpoint=self.endpoint,
                **kwargs,
            )

        def put(self, **kwargs):
            return self.client.request(
                method="put",
                endpoint=self.endpoint,
                **kwargs,
            )

        def patch(self, **kwargs):
            return self.client.request(
                method="patch",
                endpoint=self.endpoint,
                **kwargs,
            )

        def delete(self, **kwargs):
            return self.client.request(
                method="delete",
                endpoint=self.endpoint,
                **kwargs,
            )

        def __getattr__(self, name):
            return self._extend_path(name)

        def __getitem__(self, name):
            return self._extend_path(name)

    class Request:
        class APIError(requests.exceptions.RequestException):
            """
            Exception that is raised, when a request was unsuccessfull (e.g. rejected by the api because of not ok response code)
            See `requests.exceptions.RequestException`
            """
            def __init__(self, client_request, *args, **kwargs) -> None:
                self.client_request = client_request
                kwargs['response'] = self.client_request._response
                super().__init__(*args, **kwargs)

            def __repr__(self):
                return f'{self.__class__.__name__}({self.response})'

        _response: requests.Response = None

        def __init__(self, client, method, endpoint, timeout: Optional[int] = None, return_plain_response: bool = False, other_ok_states: Optional[Tuple[int]] = None, **kwargs):
            self.client: Client = client
            self.method = method
            self.endpoint = endpoint
            self.timeout = timeout or self.client.timeout
            self.return_plain_response = return_plain_response
            self.other_ok_states = other_ok_states or tuple()

            if 'verify' not in kwargs:
                kwargs['verify'] = self.client.verify

            self.kwargs = kwargs

        def _get_headers(self) -> dict:
            return {}

        def _perform_request(self):
            headers = self._get_headers()
            if 'headers' in self.kwargs:
                headers.update(self.kwargs.pop('headers'))

            return requests.request(
                self.method.upper(),
                self.client.url + self.endpoint,
                headers=headers,
                timeout=self.timeout,
                **self.kwargs
            )

        def _handle_response(self):
            return self._response_data

        def _get_response_data(self):
            try:
                return self._response.json()

            except ValueError as error:
                return None

        def perform(self):
            self._response = self._response_data = None
            self._response = self._perform_request()

            if not self._response.ok and self._response.status_code not in self.other_ok_states:
                raise self.APIError(self)

        def get_response(self):
            if not self._response:
                self.perform()

            self._response_data = self._get_response_data()

            return self._handle_response()

    # REQUEST_CLASS = Request

    def __init__(self, url, timeout=10, verify=True):
        """
        API Client. Perform requests to the API using this object.
        For easier use of the client, you can call endpoints by giving them as attributes on this object. See `Endpoint`.

        :url: Base url of API, containing version path, without trailing slash
        :consumer: Tuple containing UID and Password ('uid', 'password')
        :customer: Tuple containing Login and Password ('login@example.com', 'password')
        :timeout: Default request timeout
        :verify: verify HTTPS connection
        """
        self.url = url
        self.timeout = timeout
        self.verify = verify
        self.endpoint = self.Endpoint(self)

    def request(self, method, endpoint, timeout=None, return_plain_response=False, other_ok_states=(), **kwargs):
        request = self.Request(
            client=self,
            method=method,
            endpoint=endpoint,
            timeout=timeout,
            return_plain_response=return_plain_response,
            other_ok_states=other_ok_states,
            **kwargs,
        )

        return request.get_response()

    def __getattr__(self, name) -> Endpoint:
        return getattr(self.endpoint, name)
