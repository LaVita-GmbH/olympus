def remove_none(d):
    if isinstance(d, dict):
        return {key: remove_none(value) for key, value in d.items() if value is not None}

    else:
        return d
