from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from api.routes import router
from api.twitch_routes import router as twitch_router
from shared.db import get_engine
from shared.settings import get_settings

app = FastAPI(title="universal-discord-bot", version="0.1.0")
settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.public_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)
app.include_router(twitch_router)


@app.get("/health")
async def health() -> dict[str, str]:
    engine = get_engine()
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))
    return {"status": "ok", "node_id": get_settings().node_id}
