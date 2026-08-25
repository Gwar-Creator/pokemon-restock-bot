import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import discord_cleanup


class DiscordCleanupTests(unittest.TestCase):
    def test_configured_channels_deduplicates_ids(self):
        env = {
            "RESTOCK_CHANNEL_ID": "123",
            "PRICE_WATCH_CHANNEL_ID": "456",
            "PRICE_HISTORY_CHANNEL_ID": "456",
            "CARDMARKET_CHANNEL_ID": "",
        }
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(
                discord_cleanup._configured_channels(),
                [
                    ("RESTOCK_CHANNEL_ID", "123"),
                    ("PRICE_WATCH_CHANNEL_ID", "456"),
                ],
            )

    def test_cleanup_keeps_fresh_pinned_and_manual_messages(self):
        now = datetime.now(timezone.utc)
        old = (now - timedelta(hours=25)).isoformat()
        fresh = (now - timedelta(hours=1)).isoformat()
        messages = [
            {"id": "4", "timestamp": fresh, "webhook_id": "w", "author": {}},
            {"id": "3", "timestamp": old, "webhook_id": "w", "author": {}, "pinned": True},
            {"id": "2", "timestamp": old, "author": {"bot": False}},
            {"id": "1", "timestamp": old, "webhook_id": "w", "author": {}},
        ]
        calls = []

        class Response:
            def json(self):
                return messages

        def fake_request(method, path, token, **kwargs):
            calls.append((method, path))
            return Response()

        with patch.object(discord_cleanup, "_request", side_effect=fake_request):
            scanned, deleted = discord_cleanup.cleanup_channel(
                "token",
                "123",
                now - timedelta(hours=24),
            )

        self.assertEqual(scanned, 4)
        self.assertEqual(deleted, 1)
        self.assertEqual(
            [call for call in calls if call[0] == "DELETE"],
            [("DELETE", "/channels/123/messages/1")],
        )


if __name__ == "__main__":
    unittest.main()
