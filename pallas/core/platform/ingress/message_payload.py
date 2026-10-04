def event_message_to_cq(event: object) -> str:
    message = getattr(event, "original_message", None)
    if message is None:
        get_message = getattr(event, "get_message", None)
        message = get_message() if callable(get_message) else None
    if message is not None:
        return str(message)
    return str(getattr(event, "raw_message", "") or "")
