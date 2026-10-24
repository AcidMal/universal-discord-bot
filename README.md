# universal-discord-bot

One Discord bot, many servers. It is a moderation bot: cases, timed punishments, automod, lockdown, staff notes, and member reports. There is no music module.

PostgreSQL 18.1 is the only shared datastore. Gateway replicas claim shards with row locks, timed jobs are claimed with `SKIP LOCKED`, and config changes fan out with `LISTEN/NOTIFY`. No Redis.

The dashboard and the Discord embeds read the same theme row, so a server can take a preset (Midnight, Light, Nord, Rose) or its own colors without breaking the layout.

Slash command options, permissions, and examples live in [COMMANDS.md](COMMANDS.md).

## What you get

- Guild-installable slash commands for setup, cases, notes, reports, automod, lockdown, and theme preview
- A case log embed that is edited when a timed ban, timeout, or lockdown is reversed
- Automod for words, links, mention spam, message spam, and join raids
- A FastAPI dashboard with Discord OAuth for overview, cases, reports, notes, automod, staff roles, and a live theme preview
- More than one bot process, each holding a distinct set of shards

## Architecture

```text
Discord gateway
    |                |
 gateway node A   gateway node B
    |                |
    +-------+--------+
            |
     PostgreSQL 18.1
       |         |
   FastAPI     Vite dashboard
```

Each bot process:

1. Upserts itself in `cluster_nodes`
2. Asks Discord for the recommended shard count, unless `SHARD_COUNT` is set
3. Claims expired or unowned shard rows with `FOR UPDATE SKIP LOCKED`
4. Heartbeats every 5 seconds. Leases last about 15 seconds
5. Listens on `guild_invalidate` and drops that server's cached config
6. Runs the scheduler. Due unban, untimeout, and unlock jobs are claimed so only one node performs each job

The API does not hold shards. Scale it separately from the gateway.

## Requirements

- Docker Desktop or Docker Engine, with Compose v2 (`docker compose`) or `docker-compose`
- A Discord application: <https://discord.com/developers/applications>

For a host install without Docker you also need Python 3.12+, Node.js 22+, and PostgreSQL 18.

The bot needs these privileged intents turned on in the Developer Portal under Bot:

- Message Content Intent (automod reads message text)
- Server Members Intent (raid detection and member lookups)

OAuth2 redirect to add under OAuth2 → Redirects:

```text
http://localhost:5173/auth/callback
```

Use your real public URL in production, with no trailing slash. It must match `PUBLIC_URL`.

Invite URL permissions cover kick, ban, timeout, manage channels, manage roles, view/send/manage messages, embed links, and read history:

```text
https://discord.com/oauth2/authorize?client_id=YOUR_CLIENT_ID&scope=bot%20applications.commands&permissions=1099780156438
```

## Deploy with one script

From the repo root.

macOS, Linux, WSL, or Git Bash:

```bash
chmod +x deploy.sh
./deploy.sh
```

Windows PowerShell:

```powershell
.\deploy.ps1
```

The script:

1. Checks that Docker is running and Compose is available
2. Creates `.env` from `.env.example` if you do not have one
3. Asks for the bot token, client id, and client secret when they are empty
4. Generates `SESSION_SECRET` when it is empty
5. Builds and starts Postgres, the API (which migrates on boot), the dashboard, and the bot
6. Waits until `http://localhost:8000/health` answers
7. Prints the dashboard URL, the OAuth redirect, and the invite link

Useful flags:

```bash
./deploy.sh --noninteractive
./deploy.sh --replicas 2
./deploy.sh --no-build
```

`--noninteractive` reads `DISCORD_TOKEN`, `DISCORD_CLIENT_ID`, `DISCORD_CLIENT_SECRET`, and `PUBLIC_URL` from the environment or an existing `.env` and does not prompt. `--replicas` is only useful once Discord assigns more than one shard. A second replica waits until a lease expires; it does not steal a live connection.

Compose clears `NODE_ID` on the bot service so each container generates its own id. Do not pin one `NODE_ID` across replicas or they will fight over the same leases.

After the first boot:

1. Confirm the OAuth redirect printed by the script is saved in the Discord application
2. Open the dashboard and sign in with Discord
3. Invite the bot, then run `/setup` in that server
4. Slash commands sync when the gateway connects. If they are missing, check `docker compose logs bot`

Day-two commands:

```bash
docker compose logs -f bot
docker compose logs -f api
docker compose up -d --build
docker compose down
```

`docker compose down` keeps the Postgres volume. `docker compose down -v` deletes it. The volume is mounted at `/var/lib/postgresql`, which is where the Postgres 18 image writes its data.

## Deploy on Kubernetes

You need Docker, `kubectl`, and `kubectl config current-context` pointed at the cluster you want. The script creates Postgres, the API, the bot, and the dashboard. On a remote cluster it publishes images for both `linux/amd64` and `linux/arm64`, so Intel and ARM nodes pull the matching build.

### 1. Create a GitHub token

Skip this step for Docker Desktop, kind, minikube, or k3d. Those clusters use the image on your machine.

For any other cluster, open GitHub → **Settings → Developer settings → Personal access tokens → Tokens (classic)** and create a token with the **write:packages** scope. It starts with `ghp_`. Copy it. The script asks for it once and stores it in `deploy/kubernetes/cluster.env`, which is not committed.

### 2. Run the script

macOS, Linux, WSL, or Git Bash:

```bash
chmod +x deploy-k8s.sh
./deploy-k8s.sh
```

Windows PowerShell:

```powershell
.\deploy-k8s.ps1
```

### 3. Answer the questions

- Discord bot token, client ID, and client secret, if `.env` does not already have them
- Dashboard URL, such as `https://bot.example.com`. This becomes the Ingress host. Use `https://` when you want Twitch go-live alerts.
- The GitHub token from step 1, on a remote cluster

It prints the cluster name and waits for you to confirm. Postgres keeps the same password on later runs.

### 4. Finish Discord setup

The script prints an OAuth redirect and an invite link.

1. In the Discord Developer Portal, add that redirect under **OAuth2 → Redirects**
2. Under **Bot**, turn on **Message Content Intent** and **Server Members Intent**
3. Open the dashboard URL
4. Open the invite link and add the bot to a server, then run `/setup` there

### 5. Check that it is up

```bash
kubectl get pods -n universal-discord-bot
kubectl logs -n universal-discord-bot -l app=api -f
kubectl logs -n universal-discord-bot -l app=bot -f
```

`api` and `bot` should become `Running`. The API log ends after migrations. The bot log shows the shards it claimed. A `401` while pulling means the pod has no registry credentials. Run `./deploy-k8s.sh` again so it refreshes the `ghcr` pull secret, then delete the pod so Kubernetes retries the pull.

Run `./deploy-k8s.sh` again after you change `.env` or `cluster.env`. Add `--replicas 2` only after Discord assigns more than one shard. Add `--no-build` to skip rebuilding images.

## Configuration

Copy `.env.example` to `.env` if you are not using the deploy script.

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | Async SQLAlchemy URL. Inside Compose the host is `postgres`. On the host machine use `localhost`. |
| `DISCORD_TOKEN` | Bot token. Empty keeps the bot process idle. |
| `DISCORD_CLIENT_ID` | Application id for OAuth and the invite link |
| `DISCORD_CLIENT_SECRET` | OAuth client secret |
| `PUBLIC_URL` | Dashboard origin, no trailing slash. OAuth returns to `{PUBLIC_URL}/auth/callback` |
| `SESSION_SECRET` | Signs the dashboard cookie. Generate a long random value |
| `NODE_ID` | Optional stable id for a single process. Leave empty for an automatic id |
| `SHARD_COUNT` | `0` asks Discord. Set it only when you need a fixed count at least as high as Discord's recommendation |
| `BOT_ADMIN_IDS` | Comma-separated Discord user IDs that can edit the bot's presence |
| `TWITCH_CLIENT_ID` / `TWITCH_CLIENT_SECRET` | Twitch application used for live alerts |
| `TWITCH_EVENTSUB_SECRET` | Verifies instant go-live pushes. Generated by the deploy script |

Default Compose ports:

| Service | URL |
| --- | --- |
| Dashboard | http://localhost:5173 |
| API | http://localhost:8000/health |
| Postgres | `localhost:5432`, user `bot`, password `bot`, database `bot` |

## Install without Docker

Create a PostgreSQL 18 database, then:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
```

Point `DATABASE_URL` at the database with the `postgresql+asyncpg://` scheme:

```bash
export DATABASE_URL=postgresql+asyncpg://bot:bot@localhost:5432/bot
alembic upgrade head
uvicorn api.main:app --reload --port 8000
python -m bot
```

Dashboard, in another shell:

```bash
cd web
npm install
npm run dev
```

The Vite dev server proxies `/api`, `/auth`, `/health`, and `/twitch` to `http://localhost:8000`. Sign-in cookies stay on port 5173, so use the dashboard URL in the browser and as `PUBLIC_URL`.

## Migrations

The API container runs `alembic upgrade head` before it serves traffic. The bot waits until that health check passes.

```bash
docker compose run --rm api alembic upgrade head
```

On a host install, from the repo root with the virtualenv active:

```bash
alembic upgrade head
```

New revisions:

```bash
alembic revision --autogenerate -m "describe the change"
```

Opaque ids (reports, notes, rules, jobs) use Postgres 18 `uuidv7()`. Discord snowflakes stay `BIGINT` and are sent to the dashboard as strings so JavaScript does not round them.

## Dashboard

The status page is public. It lists every gateway node and API process that is heartbeating into Postgres, plus each shard's gateway state and latency. It refreshes every 2 seconds and does not require a login.

**Sign in with Discord** to edit a server. You only see servers where the bot is present and you have Manage Server, Administrator, or a configured staff role.

Put your Discord user ID in `BOT_ADMIN_IDS` to unlock **Bot** after you sign in. That page sets the account presence (`online`, `idle`, `dnd`, `invisible`) and the status text (`custom`, `playing`, `watching`, or `listening`). Every connected node applies it as soon as the row is saved.

| Tab | What it edits |
| --- | --- |
| Overview | Timezone, log channel id, default timeout, module toggles |
| Cases | Search by user id |
| Reports | Claim, resolve, reject |
| Notes | Staff notes by user id |
| Automod | Create, toggle, and delete rules |
| Staff | Role ids allowed to warn, timeout, kick, and ban |
| Theme | Presets, colors, footer, author, logo, live embed preview |

Theme placeholders in embed title and description are `{case}`, `{type}`, `{target}`, `{reason}`, and `{moderator}`. Other `{tokens}` are rejected. The layout stays a normal embed: color, title, description, footer, author, thumbnail.

## Twitch live alerts

`/twitch add` posts an embed in a Discord channel when that Twitch channel goes live. The embed uses the server accent color and includes the stream title, the channel name, and the stream thumbnail.

Twitch pushes `stream.online` to `{PUBLIC_URL}/twitch/eventsub` as soon as the broadcast starts. That URL has to be public https, and the host in front of the bot must forward `/twitch` to the API (the dashboard dev server already does). A 10-second check also runs, so a missed push still posts, and local installs without a public URL still work.

Create a Twitch application at <https://dev.twitch.tv/console/apps> and put the client id and secret in `.env`. The deploy script can prompt for them and generates `TWITCH_EVENTSUB_SECRET`.

Command details are in [COMMANDS.md](COMMANDS.md).

## Multi-node

Run a second gateway only when `SHARD_COUNT` or Discord's recommendation is greater than 1.

```bash
./deploy.sh --replicas 2
```

Or on an existing stack:

```bash
docker compose up -d --scale bot=2
```

Both processes share `DATABASE_URL`. Each one heartbeats its own leases. If a process stops, its leases expire in about 15 seconds and another replica can claim them on its next start. A process that is already connected does not hot-add shards; restart it to pick up a new assignment.

The scheduler is safe to run on every connected node. `scheduled_actions` rows are claimed with `FOR UPDATE SKIP LOCKED`.

## Project layout

| Path | Role |
| --- | --- |
| `bot/` | discord.py process, shard leases, commands, automod, scheduler |
| `api/` | FastAPI OAuth and dashboard JSON |
| `shared/` | SQLAlchemy models, settings, theme renderer |
| `web/` | Vite + React dashboard |
| `migrations/` | Alembic |
| `deploy.sh`, `deploy.ps1` | One-command Docker deploy |
| `deploy-k8s.sh`, `deploy-k8s.ps1` | One-command Kubernetes deploy |
| `deploy/kubernetes/` | Kubernetes manifests used by that script |
| `COMMANDS.md` | Slash command reference |

## Tests

Unit tests cover duration parsing and the theme renderer. They do not need Postgres or Discord.

```bash
PYTHONPATH=. python -m unittest tests.test_units
```

## Out of scope

Music, leveling, tickets, ban appeals, billing, cross-server bans, and custom command scripting.
