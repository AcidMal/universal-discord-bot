#!/usr/bin/env bash
# Universal deploy for macOS, Linux, WSL, and Git Bash.
# Requires Docker with the Compose plugin (or docker-compose).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

REPLICAS=1
NONINTERACTIVE=0
BUILD=1

usage() {
  cat <<'EOF'
Usage: ./deploy.sh [options]

  --noninteractive, -y   Do not prompt. Read values from the environment or .env.
  --replicas N           Run N gateway replicas. Leave NODE_ID empty so each one is unique.
  --no-build             Reuse existing images.
  -h, --help             Show this help.

The script copies .env.example to .env when needed, fills a session secret,
starts Postgres 18.1, the API, the dashboard, and the bot, then waits for
http://localhost:8000/health.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --noninteractive|-y) NONINTERACTIVE=1; shift ;;
    --replicas)
      REPLICAS="${2:-}"
      shift 2
      ;;
    --no-build) BUILD=0; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
  esac
done

if ! [[ "$REPLICAS" =~ ^[1-9][0-9]*$ ]]; then
  echo "Replicas must be a positive integer." >&2
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is not installed. Install Docker Desktop or Docker Engine, then run this script again." >&2
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "Docker is installed but the daemon is not running." >&2
  exit 1
fi

if docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE=(docker-compose)
else
  echo "Docker Compose is missing. Install the docker compose plugin." >&2
  exit 1
fi

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env from .env.example"
fi

set_kv() {
  local key="$1"
  local value="$2"
  local tmp
  tmp="$(mktemp)"
  if grep -q "^${key}=" .env; then
    awk -v k="$key" -v v="$value" 'BEGIN {FS=OFS="="} $1==k {print k "=" v; next} {print}' .env >"$tmp"
  else
    cp .env "$tmp"
    printf '%s=%s\n' "$key" "$value" >>"$tmp"
  fi
  mv "$tmp" .env
}

get_kv() {
  local key="$1"
  local line
  line="$(grep -E "^${key}=" .env | tail -n 1 || true)"
  printf '%s' "${line#*=}"
}

prompt_value() {
  local key="$1"
  local label="$2"
  local secret="$3"
  local current env_value entered
  current="$(get_kv "$key")"
  if [[ -n "$current" ]]; then
    return 0
  fi
  env_value="${!key:-}"
  if [[ -n "$env_value" ]]; then
    set_kv "$key" "$env_value"
    return 0
  fi
  if [[ "$NONINTERACTIVE" -eq 1 ]]; then
    return 0
  fi
  if [[ "$secret" -eq 1 ]]; then
    read -r -s -p "$label: " entered
    printf '\n'
  else
    read -r -p "$label: " entered
  fi
  if [[ -n "$entered" ]]; then
    set_kv "$key" "$entered"
  fi
}

random_secret() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 32
  elif command -v python3 >/dev/null 2>&1; then
    python3 -c 'import secrets; print(secrets.token_hex(32))'
  else
    date +%s | shasum | awk '{print $1}'
  fi
}

prompt_value DISCORD_TOKEN "Discord bot token" 1
prompt_value DISCORD_CLIENT_ID "Discord application client ID" 0
prompt_value DISCORD_CLIENT_SECRET "Discord application client secret" 1
prompt_value TWITCH_CLIENT_ID "Twitch client ID (optional, Enter to skip)" 0
prompt_value TWITCH_CLIENT_SECRET "Twitch client secret (optional, Enter to skip)" 1

public_url="$(get_kv PUBLIC_URL)"
if [[ -z "$public_url" ]]; then
  if [[ "$NONINTERACTIVE" -eq 1 ]]; then
    set_kv PUBLIC_URL "${PUBLIC_URL:-http://localhost:5173}"
  else
    read -r -p "Public dashboard URL [http://localhost:5173]: " entered
    set_kv PUBLIC_URL "${entered:-http://localhost:5173}"
  fi
fi

if [[ -z "$(get_kv SESSION_SECRET)" ]]; then
  set_kv SESSION_SECRET "$(random_secret)"
fi

if [[ -z "$(get_kv TWITCH_EVENTSUB_SECRET)" ]]; then
  set_kv TWITCH_EVENTSUB_SECRET "$(random_secret)"
fi

if [[ -z "$(get_kv SHARD_COUNT)" ]]; then
  set_kv SHARD_COUNT "${SHARD_COUNT:-0}"
fi

# Compose forces a blank NODE_ID so replicas do not share one lease identity.
set_kv NODE_ID ""

up_args=(up -d)
if [[ "$BUILD" -eq 1 ]]; then
  up_args+=(--build)
fi
if [[ "$REPLICAS" -gt 1 ]]; then
  up_args+=(--scale "bot=${REPLICAS}")
fi

echo "Starting Postgres, API, dashboard, and ${REPLICAS} bot replica(s)..."
"${COMPOSE[@]}" "${up_args[@]}"

echo "Waiting for the API..."
ready=0
for _ in $(seq 1 60); do
  if command -v curl >/dev/null 2>&1 && curl -fsS "http://localhost:8000/health" >/dev/null 2>&1; then
    ready=1
    break
  fi
  if command -v wget >/dev/null 2>&1 && wget -q -O /dev/null "http://localhost:8000/health"; then
    ready=1
    break
  fi
  sleep 2
done

client_id="$(get_kv DISCORD_CLIENT_ID)"
public_url="$(get_kv PUBLIC_URL)"
public_url="${public_url%/}"

cat <<EOF

Dashboard: ${public_url:-http://localhost:5173}
API health: http://localhost:8000/health
Command reference: COMMANDS.md

Discord Developer Portal
  1. OAuth2 redirect: ${public_url:-http://localhost:5173}/auth/callback
  2. Privileged intents: Message Content, Server Members
  3. Invite the bot (permissions ${INVITE_PERMISSIONS:-1099780156438}):
EOF

if [[ -n "$client_id" ]]; then
  echo "     https://discord.com/oauth2/authorize?client_id=${client_id}&scope=bot%20applications.commands&permissions=1099780156438"
else
  echo "     Set DISCORD_CLIENT_ID in .env, then run ./deploy.sh again."
fi

if [[ "$ready" -ne 1 ]]; then
  echo
  echo "The API did not answer /health yet. Check logs with: ${COMPOSE[*]} logs api"
  exit 1
fi

echo
echo "API is up. Slash commands sync after the bot connects."
