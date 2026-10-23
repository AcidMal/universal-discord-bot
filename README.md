# universal-discord-bot

Multi-tenant Discord moderation bot: discord.py gateway, FastAPI API, Vite/React dashboard, PostgreSQL 18.1 as the only datastore.

## Layout

- `bot/` — gateway process (`python -m bot`)
- `api/` — FastAPI (`uvicorn api.main:app`)
- `shared/` — SQLAlchemy models, settings, DB session, theme presets
- `web/` — dashboard UI
- `migrations/` — Alembic

Python packages are `bot`, `api`, and `shared` (install with `pip install -e .`).

## Environment

Copy `.env.example` to `.env`. Variables:

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | SQLAlchemy async URL, `postgresql+asyncpg://…` |
| `DISCORD_TOKEN` | Gateway token (optional until the bot connects) |
| `DISCORD_CLIENT_ID` / `DISCORD_CLIENT_SECRET` | Dashboard OAuth (later) |
| `PUBLIC_URL` | Public web origin |
| `NODE_ID` | Gateway replica id; generated on boot if unset |

## Run locally

```bash
cp .env.example .env
docker compose up --build
```

- Postgres: `localhost:5432` (user/password/db: `bot`)
- API health: `http://localhost:8000/health`
- Web placeholder: `http://localhost:5173`

The API container runs `alembic upgrade head` on start.

Without Compose, after `pip install -e .` and a local Postgres 18.1:

```bash
export DATABASE_URL=postgresql+asyncpg://bot:bot@localhost:5432/bot
alembic upgrade head
uvicorn api.main:app --reload
python -m bot
```

Dashboard separately: `cd web && npm install && npm run dev`.

## Migrations

```bash
# Compose
docker compose run --rm api alembic upgrade head

# Host (editable install)
alembic upgrade head
```

New revisions: `alembic revision --autogenerate -m "…"`. Opaque IDs use Postgres 18 `uuidv7()`; Discord snowflakes are `BIGINT`.
