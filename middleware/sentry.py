from sentry_sdk.integrations.asgi import SentryAsgiMiddleware as BaseSentryAsgiMiddleware


class SentryAsgiMiddleware(BaseSentryAsgiMiddleware):
    def event_processor(self, event, hint, asgi_scope):
        asgi_scope['sentry_event_id'] = event['event_id']

        return super().event_processor(event, hint, asgi_scope)
