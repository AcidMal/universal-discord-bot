from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from api.routes import router
from api.status_routes import forget_api_node, forget_stale_nodes, record_api_heartbeat, router as status_router
from api.twitch_routes import router as twitch_router
from shared.db import get_engine
from shared.settings import get_settings

log = logging.getLogger("api")


async def _api_heartbeat() -> None:
    while True:
        try:
            await record_api_heartbeat(get_settings().node_id)
            await forget_stale_nodes()
        except Exception:
            log.exception("api heartbeat failed")
        await asyncio.sleep(5)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    task = asyncio.create_task(_api_heartbeat())
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        with contextlib.suppress(Exception):
            await forget_api_node(get_settings().node_id)


app = FastAPI(title="universal-discord-bot", version="0.1.0", lifespan=lifespan)
settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.public_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)
app.include_router(status_router)
app.include_router(twitch_router)


@app.exception_handler(Exception)
async def unhandled_error(request: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, HTTPException):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    log.exception("request failed: %s", request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})


@app.get("/health")
async def health() -> dict[str, str]:
    engine = get_engine()
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))
    return {"status": "ok", "node_id": get_settings().node_id}
