"""Read-only Discord webhook destination verification for existing channel.

Never POST or print/return webhook credentials. Run before any future publisher.
The independently supplied channel ID must match Discord's channel_id.
"""
import os
from urllib.parse import urlsplit

import requests

WEBHOOK_API_HOST = "discord.com"


def verify_webhook_destination(webhook_url, expected_channel_id, transport=requests.get):
    """Return VERIFIED or NOT_VERIFIED, with no URL, token or channel ID output."""
    if not isinstance(expected_channel_id, str) or not expected_channel_id.isdecimal():
        return "NOT_VERIFIED"
    if not isinstance(webhook_url, str):
        return "NOT_VERIFIED"
    try:
        parts = urlsplit(webhook_url)
        segments = parts.path.strip("/").split("/")
        valid = (
            parts.scheme == "https"
            and parts.hostname == WEBHOOK_API_HOST
            and parts.port is None
            and parts.username is None
            and parts.password is None
            and not parts.query
            and not parts.fragment
            and len(segments) == 4
            and segments[:2] == ["api", "webhooks"]
            and segments[2].isdecimal()
            and len(segments[3]) >= 12
        )
    except ValueError:
        return "NOT_VERIFIED"
    if not valid:
        return "NOT_VERIFIED"
    try:
        response = transport(webhook_url, timeout=10,
                             headers={"Accept": "application/json"})
        if getattr(response, "status_code", None) != 200:
            return "NOT_VERIFIED"
        data = response.json()
    except (ValueError, requests.RequestException):
        return "NOT_VERIFIED"
    if not isinstance(data, dict):
        return "NOT_VERIFIED"
    # Never expose returned ids or name. Exact comparison only.
    return ("VERIFIED" if str(data.get("channel_id") or "") == expected_channel_id
            else "NOT_VERIFIED")


def main():
    status = verify_webhook_destination(
        os.getenv("MARKETPLACE_WEBHOOK_URL"),
        os.getenv("MARKETPLACE_EXPECTED_CHANNEL_ID"),
    )
    print("Existing #marketplace-deals webhook destination: " + status)
    print("Live Vintage Finder Discord publishing: DISABLED")


if __name__ == "__main__":
    main()
