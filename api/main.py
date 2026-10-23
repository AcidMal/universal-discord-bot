from __future__ import annotations

from fastapi import FastAPI

from shared.settings import get_settings

app = FastAPI(title="universal-discord-bot", version="0.1.0")


@app.get("/health")
async def health() -> dict[str, str]:
    settings = get_settings()
    return {"status": "ok", "node_id": settings.node_id}
