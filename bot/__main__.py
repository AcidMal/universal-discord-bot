from __future__ import annotations

import asyncio
import logging

from bot.app import create_bot
from shared.settings import get_settings

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("bot")


async def main() -> None:
    settings = get_settings()
    log.info("node_id=%s public_url=%s", settings.node_id, settings.public_url)
    bot = create_bot()
    if not settings.discord_token:
        log.warning("DISCORD_TOKEN unset; idle until later phases connect the gateway")
        await asyncio.Event().wait()
        return
    await bot.start(settings.discord_token)


if __name__ == "__main__":
    asyncio.run(main())
