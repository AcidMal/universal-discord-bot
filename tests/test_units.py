import unittest

from bot.duration import parse_duration
from shared.pg import asyncpg_connect_args
from shared.theme import PRESETS, render_css_tokens, render_embed


class DatabaseUrlTests(unittest.TestCase):
    def test_ssl_query_becomes_a_connect_option(self) -> None:
        dsn, kwargs = asyncpg_connect_args(
            "postgresql+asyncpg://bot:secret@db.example:28430/defaultdb?ssl=require"
        )
        self.assertEqual(dsn, "postgresql://bot:secret@db.example:28430/defaultdb")
        self.assertEqual(kwargs, {"ssl": "require"})

    def test_local_url_stays_plain(self) -> None:
        dsn, kwargs = asyncpg_connect_args("postgresql+asyncpg://bot:bot@postgres:5432/bot")
        self.assertEqual(dsn, "postgresql://bot:bot@postgres:5432/bot")
        self.assertEqual(kwargs, {})


class DurationTests(unittest.TestCase):
    def test_bare_number_is_minutes(self) -> None:
        self.assertEqual(parse_duration("10"), 600)

    def test_units(self) -> None:
        self.assertEqual(parse_duration("30s"), 30)
        self.assertEqual(parse_duration("2h"), 7200)
        self.assertEqual(parse_duration("1d"), 86400)

    def test_blank_is_none(self) -> None:
        self.assertIsNone(parse_duration(None))
        self.assertIsNone(parse_duration("  "))

    def test_rejects_unknown_unit(self) -> None:
        with self.assertRaises(ValueError):
            parse_duration("5w")


class ThemeTests(unittest.TestCase):
    def test_presets_cover_the_four_looks(self) -> None:
        self.assertEqual(set(PRESETS), {"midnight", "light", "nord", "rose"})

    def test_embed_substitutes_constrained_fields(self) -> None:
        embed = render_embed(
            PRESETS["midnight"],
            "case",
            {"case": "7", "reason": "spam", "target": "user", "type": "warn", "moderator": "mod"},
        )
        self.assertEqual(embed["title"], "Case #7")
        self.assertEqual(embed["description"], "spam")
        self.assertEqual(embed["color"], 0x7C5CFF)

    def test_css_tokens(self) -> None:
        tokens = render_css_tokens(PRESETS["light"])
        self.assertEqual(tokens["--bg"], "#F7F7F5")
        self.assertEqual(tokens["--accent"], "#4F46E5")


if __name__ == "__main__":
    unittest.main()
