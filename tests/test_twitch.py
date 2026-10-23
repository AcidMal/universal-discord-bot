import unittest
from datetime import datetime, timezone

from shared.twitch_format import live_embed, normalize_login, stream_thumbnail, verify_eventsub_signature


class TwitchFormatTests(unittest.TestCase):
    def test_login_from_url(self) -> None:
        self.assertEqual(normalize_login("https://www.twitch.tv/Some_Name/"), "some_name")
        self.assertEqual(normalize_login("@shroud"), "shroud")

    def test_rejects_bad_login(self) -> None:
        with self.assertRaises(ValueError):
            normalize_login("not a channel")

    def test_thumbnail_fills_size_and_cache_bust(self) -> None:
        started = datetime(2026, 10, 23, tzinfo=timezone.utc)
        url = stream_thumbnail(
            "Shroud",
            "https://static-cdn.jtvnw.net/previews-ttv/live_user_shroud-{width}x{height}.jpg",
            started,
        )
        self.assertIn("1280x720", url)
        self.assertIn("t=", url)
        self.assertNotIn("{width}", url)

    def test_embed_has_title_channel_and_thumbnail(self) -> None:
        embed = live_embed(
            accent="#7C5CFF",
            title="Ranked",
            channel_name="Shroud",
            login="shroud",
            thumbnail_url="https://example.test/thumb.jpg",
        )
        self.assertEqual(embed["title"], "Ranked")
        self.assertEqual(embed["author"]["name"], "Shroud")
        self.assertEqual(embed["fields"][0]["name"], "Channel")
        self.assertEqual(embed["image"]["url"], "https://example.test/thumb.jpg")
        self.assertEqual(embed["color"], 0x7C5CFF)

    def test_signature(self) -> None:
        body = b'{"ok":true}'
        secret = "topsecret"
        import hashlib
        import hmac

        digest = hmac.new(secret.encode(), b"id" + b"time" + body, hashlib.sha256).hexdigest()
        self.assertTrue(
            verify_eventsub_signature(
                secret=secret,
                message_id="id",
                timestamp="time",
                body=body,
                signature=f"sha256={digest}",
            )
        )
        self.assertFalse(
            verify_eventsub_signature(
                secret=secret,
                message_id="id",
                timestamp="time",
                body=body,
                signature="sha256=nope",
            )
        )


if __name__ == "__main__":
    unittest.main()
