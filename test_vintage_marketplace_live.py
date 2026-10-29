"""Vintage Finder Light offline tests; mocked official APIs and Discord only."""
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock

from vintage_marketplace_live import (
    image_url, enrich, get_details, prepare, payload, publish, read_state
)

NOW = datetime(2026, 10, 29, 7, tzinfo=timezone.utc)


def item(i, title="Pokemon Gym Heroes lot 11 st"):
    return {"id": i, "shortDescription": title,
            "itemUrl": f"http://www.tradera.com/item/1001342/{i}/old-lot"}


def details(i, price=123):
    return {
        "id": i, "status": {"ended": False},
        "endDate": (NOW + timedelta(days=1)).isoformat(),
        "numberOfImages": 4,
        "detailedImageLinks": [{"url": "http://img.tradera.net/images/safe.jpeg"}],
        "nextBidSpecified": True, "nextBid": price,
    }


def response(obj):
    r = Mock(status_code=200)
    r.json.return_value = obj
    r.raise_for_status.return_value = None
    return r


def search_transport(url, **kwargs):
    return response({"items": [item(100), item(101), item(102)],
                     "errors": []})


class LightLiveTests(unittest.TestCase):
    def test_bootstrap_marks_seen_and_produces_zero_discord(self):
        calls = Mock()
        state = {"version": 1, "initialized": False, "seen": {}, "sent_at": []}
        after, selected, count, baseline = prepare(
            " APP\n", " KEY\n", state, NOW,
            search_transport=search_transport, detail_transport=calls)
        self.assertTrue(baseline)
        self.assertEqual(selected, [])
        self.assertEqual(count, 3)
        self.assertEqual(len(after["seen"]), 3)
        calls.assert_not_called()

    def test_new_items_capped_and_duplicates_do_not_realert(self):
        s = {"version": 1, "initialized": True, "seen": {},
             "sent_at": []}
        client = Mock(side_effect=lambda url, **kwargs:
                      response(details(int(url.rsplit("/", 1)[-1]))))
        s, selected, _, baseline = prepare(
            "APP", "KEY", s, NOW,
            search_transport=search_transport, detail_transport=client)
        self.assertFalse(baseline)
        self.assertLessEqual(len(selected), 3)
        self.assertEqual(len(selected), 3)
        self.assertEqual({x["price_label"] for x in selected}, {"Næste bud"})
        self.assertEqual({x["image"] for x in selected},
                         {"https://img.tradera.net/images/safe.jpeg"})
        self.assertTrue(all(x["verification"] == "UNVERIFIED" for x in selected))
        _, repeated, _, _ = prepare(
            "APP", "KEY", s, NOW,
            search_transport=search_transport, detail_transport=client)
        self.assertEqual(repeated, [])

    def test_prevents_invalid_images_expired_and_unpriced(self):
        candidate = {"id": "100", "title": "Pokemon Gym Heroes lot",
                     "url": "https://www.tradera.com/item/1001342/100",
                     "tier": "VINTAGE_LOT", "verification": "UNVERIFIED"}
        self.assertIsNotNone(enrich(candidate, details(100), NOW))
        for changed in (
            {"status": {"ended": True}},
            {"endDate": (NOW - timedelta(days=1)).isoformat()},
            {"nextBidSpecified": False},
            {"nextBid": "NaN"},
            {"detailedImageLinks": [{"url": "https://evil.invalid/a.png"}],
             "thumbnailLink": "https://evil.invalid/b.png"},
            {"id": 999},
            {"numberOfImages": 0},
        ):
            with self.subTest(changed=changed):
                self.assertIsNone(enrich(candidate, {**details(100), **changed}, NOW))
        self.assertEqual(image_url("https://img.tradera.net.evil.invalid/a"), "")

    def test_discord_requires_verified_destination_and_existing_reservation(self):
        candidate = {"id": "100", "title": "Pokemon Gym Heroes lot",
                     "url": "https://www.tradera.com/item/1001342/100",
                     "tier": "VINTAGE_LOT", "verification": "UNVERIFIED"}
        selected = enrich(candidate, details(100), NOW)
        reservation = { "version": 1, "seen": {"100": NOW.isoformat()},
                        "sent_at": [], "initialized": True}
        good_get = Mock(return_value=response({"channel_id": "1540094708439711904"}))
        post = Mock(return_value=Mock(status_code=204))
        result = publish([selected], reservation,
                         "https://discord.com/api/webhooks/123456789/opaqueSecretToken12345",
                         NOW, verify_transport=good_get, send_transport=post)
        self.assertEqual(result, 1)
        self.assertEqual(post.call_count, 1)
        _, kwargs = post.call_args
        self.assertFalse(kwargs["allow_redirects"])
        self.assertEqual(kwargs["json"]["embeds"][0]["title"].split(" · ")[1],
                         "UDVALGT FUND")
        self.assertIn("ikke et købsråd", kwargs["json"]["embeds"][0]["description"])
        post.reset_mock()
        wrong = Mock(return_value=response({"channel_id": "999"}))
        with self.assertRaises(RuntimeError):
            publish([selected], reservation,
                    "https://discord.com/api/webhooks/123456789/opaqueSecretToken12345",
                    NOW, verify_transport=wrong, send_transport=post)
        post.assert_not_called()
        missing = {"version": 1, "seen": {}, "sent_at": []}
        self.assertEqual(publish([selected], missing, "invalid", NOW,
                                 send_transport=post), 0)
        post.assert_not_called()

    def test_read_state_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            with self.assertRaises(ValueError):
                read_state(path)
            path.write_text("{}", encoding="utf-8")
            with self.assertRaises(ValueError):
                read_state(path)

    def test_payload_rejects_unapproved_statuses(self):
        candidate = enrich(
            {"id": "100", "title": "Pokemon WotC lot",
             "url": "https://www.tradera.com/item/1001342/100",
             "tier": "VINTAGE_LOT", "verification": "UNVERIFIED"},
            details(100), NOW)
        self.assertIn("UDVALGT FUND", payload(candidate)["embeds"][0]["title"])
        with self.assertRaises(ValueError):
            payload({**candidate, "verification": "BUY"})
        with self.assertRaises(ValueError):
            payload({**candidate, "tier": "SINGLE"})


if __name__ == "__main__":
    unittest.main()
