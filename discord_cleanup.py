import os
import time
from datetime import datetime, timedelta, timezone

import requests


API_BASE = "https://discord.com/api/v10"
RETENTION_HOURS = max(1, int(os.getenv("DISCORD_RETENTION_HOURS", "24")))
MAX_PAGES_PER_CHANNEL = max(
    1,
    int(os.getenv("DISCORD_CLEANUP_MAX_PAGES", "10")),
)

CHANNEL_ENV_NAMES = (
    "RESTOCK_CHANNEL_ID",
    "PRICE_WATCH_CHANNEL_ID",
    "PRICE_HISTORY_CHANNEL_ID",
    "CARDMARKET_CHANNEL_ID",
)


def _request(method, path, token, **kwargs):
    headers = dict(kwargs.pop("headers", {}))
    headers["Authorization"] = f"Bot {token}"
    headers["User-Agent"] = "Pokemon-Lorcana-MasterBot-Cleanup/1.0"

    for attempt in range(4):
        response = requests.request(
            method,
            f"{API_BASE}{path}",
            headers=headers,
            timeout=30,
            **kwargs,
        )
        if response.status_code != 429:
            response.raise_for_status()
            return response

        retry_after = float(response.json().get("retry_after", 1))
        if attempt == 3:
            response.raise_for_status()
        time.sleep(min(10, max(0.25, retry_after)))

    raise RuntimeError("Discord request fejlede efter rate-limit retries")


def _configured_channels():
    channels = []
    seen = set()
    for env_name in CHANNEL_ENV_NAMES:
        channel_id = os.getenv(env_name, "").strip()
        if not channel_id or channel_id in seen:
            continue
        if not channel_id.isdigit():
            raise ValueError(f"{env_name} skal være et numerisk Discord channel-ID")
        seen.add(channel_id)
        channels.append((env_name, channel_id))
    return channels


def _is_scanner_message(message):
    # Scannerkanalerne kan fortsat bruges til manuelle noter. Kun opslag fra
    # webhooks/bots ryddes automatisk.
    return bool(message.get("webhook_id")) or bool(
        (message.get("author") or {}).get("bot")
    )


def cleanup_channel(token, channel_id, cutoff):
    before = None
    deleted = 0
    scanned = 0

    for _ in range(MAX_PAGES_PER_CHANNEL):
        params = {"limit": 100}
        if before:
            params["before"] = before

        response = _request(
            "GET",
            f"/channels/{channel_id}/messages",
            token,
            params=params,
        )
        messages = response.json()
        if not messages:
            break

        scanned += len(messages)
        before = messages[-1]["id"]

        for message in messages:
            timestamp = datetime.fromisoformat(
                message["timestamp"].replace("Z", "+00:00")
            )
            if timestamp > cutoff or message.get("pinned"):
                continue
            if not _is_scanner_message(message):
                continue

            _request(
                "DELETE",
                f"/channels/{channel_id}/messages/{message['id']}",
                token,
            )
            deleted += 1

        oldest = datetime.fromisoformat(
            messages[-1]["timestamp"].replace("Z", "+00:00")
        )
        if oldest <= cutoff and len(messages) < 100:
            break

    return scanned, deleted


def main():
    token = os.getenv("DISCORD_BOT_TOKEN", "").strip()
    channels = _configured_channels()

    if not token or not channels:
        print(
            "DISCORD CLEANUP: ikke konfigureret; "
            "scannerne fortsætter uden kanaloprydning."
        )
        return 0

    cutoff = datetime.now(timezone.utc) - timedelta(hours=RETENTION_HOURS)
    total_deleted = 0

    for env_name, channel_id in channels:
        scanned, deleted = cleanup_channel(token, channel_id, cutoff)
        total_deleted += deleted
        print(
            f"DISCORD CLEANUP: {env_name} scannet={scanned} "
            f"slettet={deleted} retention={RETENTION_HOURS}h"
        )

    print(f"DISCORD CLEANUP: færdig; slettet i alt={total_deleted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
