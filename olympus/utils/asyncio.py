import asyncio


def is_async():
    try:
        event_loop = asyncio.get_event_loop()

    except RuntimeError:
        pass

    else:
        if event_loop.is_running():
            return True

    return False
