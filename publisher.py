import requests


def publish_to_webhook(webhook_url: str, content: str, timeout_seconds: int = 20) -> bool:
    """
    Works for generic text webhooks (for example, Discord).
    """
    if not webhook_url:
        return False

    payloads = ({"content": content}, {"text": content}, {"message": content})
    for payload in payloads:
        try:
            response = requests.post(webhook_url, json=payload, timeout=timeout_seconds)
            if 200 <= response.status_code < 300:
                return True
        except Exception:
            pass
    return False
