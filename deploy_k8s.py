#!/usr/bin/env python3
"""Deploy the bot to the current kubectl context.

Reads Discord settings from .env, asks for the public dashboard URL once,
and on a remote cluster pushes the images and creates a pull secret.
"""

from __future__ import annotations

import argparse
import base64
import getpass
import json
import secrets
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
NAMESPACE = "universal-discord-bot"
IMAGES = (
    "ghcr.io/acidmal/universal-discord-bot-api:latest",
    "ghcr.io/acidmal/universal-discord-bot-bot:latest",
    "ghcr.io/acidmal/universal-discord-bot-web:latest",
)
GHCR_USER = "acidmal"


class EnvFile:
    def __init__(self, path: Path) -> None:
        self.path = path
        text = path.read_text() if path.exists() else ""
        self.lines = text.splitlines()

    def get(self, key: str) -> str:
        prefix = f"{key}="
        for line in reversed(self.lines):
            if line.startswith(prefix):
                value = line[len(prefix) :]
                if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
                    return value[1:-1]
                return value
        return ""

    def set(self, key: str, value: str) -> None:
        prefix = f"{key}="
        updated: list[str] = []
        found = False
        for line in self.lines:
            if line.startswith(prefix):
                updated.append(f"{key}={value}")
                found = True
            else:
                updated.append(line)
        if not found:
            updated.append(f"{key}={value}")
        self.lines = updated

    def save(self, mode: int | None = None) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("\n".join(self.lines) + "\n")
        if mode is not None:
            self.path.chmod(mode)


def run(
    cmd: list[str],
    *,
    input_text: str | None = None,
    check: bool = True,
    quiet: bool = False,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    if not quiet:
        print("+", " ".join(cmd), flush=True)
    result = subprocess.run(
        cmd,
        input=input_text,
        text=True,
        capture_output=True,
        cwd=cwd,
    )
    if not quiet and result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if check and result.returncode != 0:
        if result.stderr:
            sys.stderr.write(result.stderr)
            if not result.stderr.endswith("\n"):
                sys.stderr.write("\n")
        raise SystemExit(result.returncode)
    return result


def kubectl(*args: str, input_text: str | None = None, check: bool = True, quiet: bool = False) -> str:
    result = run(["kubectl", *args], input_text=input_text, check=check, quiet=quiet)
    return result.stdout.strip()


def prompt(label: str, *, secret: bool = False, default: str = "") -> str:
    shown = f"{label} [{default}]" if default else label
    if secret:
        entered = getpass.getpass(f"{shown}: ")
    else:
        entered = input(f"{shown}: ")
    entered = entered.strip()
    return entered or default


def random_secret() -> str:
    return secrets.token_hex(32)


def normalize_public_url(raw: str) -> str:
    value = raw.strip().rstrip("/")
    if "://" not in value:
        value = "https://" + value
    parsed = urlparse(value)
    host = parsed.hostname
    if parsed.scheme not in {"http", "https"} or not host:
        raise SystemExit("The dashboard URL needs a hostname, for example https://bot.example.com")
    if host in {"localhost", "127.0.0.1"}:
        raise SystemExit("Use the hostname that reaches the cluster, not localhost.")
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme}://{host}{port}"


def public_host(public_url: str) -> str:
    host = urlparse(public_url).hostname
    if not host:
        raise SystemExit(f"Could not read a hostname from {public_url}")
    return host


def is_local_context(context: str) -> bool:
    return context == "docker-desktop" or context.startswith(("kind-", "k3d-", "minikube"))


def ensure_tool(name: str) -> None:
    if shutil.which(name) is None:
        raise SystemExit(f"{name} is not installed or not on PATH.")


def compose_cmd() -> list[str]:
    if shutil.which("docker") is None:
        raise SystemExit("Docker is not installed. Install Docker, or re-run with --no-build.")
    probe = subprocess.run(["docker", "compose", "version"], capture_output=True, text=True)
    if probe.returncode == 0:
        return ["docker", "compose"]
    if shutil.which("docker-compose"):
        return ["docker-compose"]
    raise SystemExit("Docker Compose is missing. Install the docker compose plugin.")


def load_dotenv(noninteractive: bool) -> EnvFile:
    env_path = ROOT / ".env"
    example = ROOT / ".env.example"
    if not env_path.exists():
        if not example.exists():
            raise SystemExit("Missing .env.example")
        env_path.write_text(example.read_text())
        print("Created .env from .env.example")
    env = EnvFile(env_path)

    def fill(key: str, label: str, *, secret: bool = False, default: str = "") -> None:
        if env.get(key):
            return
        if noninteractive:
            return
        entered = prompt(label, secret=secret, default=default)
        if entered:
            env.set(key, entered)

    fill("DISCORD_TOKEN", "Discord bot token", secret=True)
    fill("DISCORD_CLIENT_ID", "Discord application client ID")
    fill("DISCORD_CLIENT_SECRET", "Discord application client secret", secret=True)
    fill("TWITCH_CLIENT_ID", "Twitch client ID (optional, Enter to skip)")
    fill("TWITCH_CLIENT_SECRET", "Twitch client secret (optional, Enter to skip)", secret=True)
    if not env.get("SESSION_SECRET"):
        env.set("SESSION_SECRET", random_secret())
    if not env.get("TWITCH_EVENTSUB_SECRET"):
        env.set("TWITCH_EVENTSUB_SECRET", random_secret())
    if not env.get("SHARD_COUNT"):
        env.set("SHARD_COUNT", "0")
    env.save()
    return env


def load_cluster(noninteractive: bool) -> EnvFile:
    path = ROOT / "deploy" / "kubernetes" / "cluster.env"
    cluster = EnvFile(path)
    if not cluster.get("PUBLIC_URL"):
        if noninteractive:
            raise SystemExit(
                "Set PUBLIC_URL in deploy/kubernetes/cluster.env "
                "(https://your-host, not localhost)."
            )
        entered = prompt("Dashboard URL for this cluster (https://bot.example.com)")
        if not entered:
            raise SystemExit("A public dashboard URL is required.")
        cluster.set("PUBLIC_URL", normalize_public_url(entered))
    else:
        cluster.set("PUBLIC_URL", normalize_public_url(cluster.get("PUBLIC_URL")))
    if not cluster.get("GHCR_USERNAME"):
        cluster.set("GHCR_USERNAME", GHCR_USER)
    cluster.save(0o600)
    return cluster


def existing_db_password() -> str:
    result = kubectl(
        "get",
        "secret",
        "bot-secrets",
        "-n",
        NAMESPACE,
        "-o",
        "jsonpath={.data.POSTGRES_PASSWORD}",
        check=False,
        quiet=True,
    )
    if not result:
        return ""
    try:
        return base64.b64decode(result).decode()
    except (ValueError, UnicodeDecodeError):
        return ""


def apply_from_yaml(manifest: str, label: str) -> None:
    print(f"+ kubectl apply {label}", flush=True)
    kubectl("apply", "-f", "-", input_text=manifest, quiet=True)


def apply_secret(env: EnvFile, cluster: EnvFile, password: str) -> None:
    database_url = cluster.get("DATABASE_URL")
    if not database_url:
        database_url = f"postgresql+asyncpg://bot:{password}@postgres:5432/bot"
    manifest = kubectl(
        "create",
        "secret",
        "generic",
        "bot-secrets",
        "-n",
        NAMESPACE,
        f"--from-literal=POSTGRES_PASSWORD={password}",
        f"--from-literal=DATABASE_URL={database_url}",
        f"--from-literal=DISCORD_TOKEN={env.get('DISCORD_TOKEN')}",
        f"--from-literal=DISCORD_CLIENT_SECRET={env.get('DISCORD_CLIENT_SECRET')}",
        f"--from-literal=SESSION_SECRET={env.get('SESSION_SECRET')}",
        f"--from-literal=TWITCH_CLIENT_SECRET={env.get('TWITCH_CLIENT_SECRET')}",
        f"--from-literal=TWITCH_EVENTSUB_SECRET={env.get('TWITCH_EVENTSUB_SECRET')}",
        "--dry-run=client",
        "-o",
        "yaml",
        quiet=True,
    )
    apply_from_yaml(manifest, "secret/bot-secrets")


def apply_config(env: EnvFile, public_url: str) -> None:
    manifest = kubectl(
        "create",
        "configmap",
        "bot-config",
        "-n",
        NAMESPACE,
        f"--from-literal=PUBLIC_URL={public_url}",
        f"--from-literal=DISCORD_CLIENT_ID={env.get('DISCORD_CLIENT_ID')}",
        f"--from-literal=BOT_ADMIN_IDS={env.get('BOT_ADMIN_IDS')}",
        f"--from-literal=SHARD_COUNT={env.get('SHARD_COUNT') or '0'}",
        f"--from-literal=TWITCH_CLIENT_ID={env.get('TWITCH_CLIENT_ID')}",
        "--dry-run=client",
        "-o",
        "yaml",
        quiet=True,
    )
    apply_from_yaml(manifest, "configmap/bot-config")


def apply_pull_secret(username: str, token: str) -> None:
    manifest = kubectl(
        "create",
        "secret",
        "docker-registry",
        "ghcr",
        "-n",
        NAMESPACE,
        "--docker-server=ghcr.io",
        f"--docker-username={username}",
        f"--docker-password={token}",
        "--dry-run=client",
        "-o",
        "yaml",
        quiet=True,
    )
    apply_from_yaml(manifest, "secret/ghcr")


def ingress_class() -> str | None:
    raw = kubectl("get", "ingressclass", "-o", "json", check=False, quiet=True)
    if not raw:
        return None
    try:
        items = json.loads(raw).get("items") or []
    except json.JSONDecodeError:
        return None
    names: list[str] = []
    for item in items:
        name = (item.get("metadata") or {}).get("name")
        if not name:
            continue
        names.append(name)
        annotations = (item.get("metadata") or {}).get("annotations") or {}
        if annotations.get("ingressclass.kubernetes.io/is-default-class") == "true":
            return name
    if len(names) == 1:
        return names[0]
    return None


def format_patch(ops: list[dict]) -> str:
    rows: list[str] = []
    for op in ops:
        rows.append(f"- op: {op['op']}")
        rows.append(f"  path: {json.dumps(op['path'])}")
        if "value" in op:
            rows.append("  value: " + json.dumps(op["value"]))
    return "\n".join(rows)


def write_overlay(
    *,
    host: str,
    ingress: str | None,
    remote: bool,
    replicas: int,
    external_db: bool,
) -> Path:
    directory = ROOT / "deploy" / "kubernetes" / ".generated"
    directory.mkdir(parents=True, exist_ok=True)
    resources = [
        "../namespace.yaml",
        "../api.yaml",
        "../bot.yaml",
        "../web.yaml",
        "../ingress.yaml",
    ]
    if not external_db:
        resources.insert(1, "../postgres.yaml")
    ingress_ops: list[dict] = [{"op": "replace", "path": "/spec/rules/0/host", "value": host}]
    if ingress:
        ingress_ops.append({"op": "replace", "path": "/spec/ingressClassName", "value": ingress})
    else:
        ingress_ops.append({"op": "remove", "path": "/spec/ingressClassName"})
    patches = [{"target": {"kind": "Ingress", "name": "web"}, "patch": format_patch(ingress_ops)}]
    if remote:
        patches.append(
            {
                "target": {"kind": "Deployment"},
                "patch": format_patch(
                    [
                        {
                            "op": "add",
                            "path": "/spec/template/spec/imagePullSecrets",
                            "value": [{"name": "ghcr"}],
                        },
                        {
                            "op": "replace",
                            "path": "/spec/template/spec/containers/0/imagePullPolicy",
                            "value": "Always",
                        },
                    ]
                ),
            }
        )
        patches.append(
            {
                "target": {"kind": "Deployment", "name": "bot"},
                "patch": format_patch(
                    [
                        {
                            "op": "replace",
                            "path": "/spec/template/spec/initContainers/0/imagePullPolicy",
                            "value": "Always",
                        }
                    ]
                ),
            }
        )
    lines = [
        "apiVersion: kustomize.config.k8s.io/v1beta1",
        "kind: Kustomization",
        "resources:",
    ]
    lines.extend(f"  - {item}" for item in resources)
    lines.extend(
        [
            "replicas:",
            "  - name: bot",
            f"    count: {replicas}",
            "patches:",
        ]
    )
    for patch in patches:
        lines.append("  - target:")
        for key, value in patch["target"].items():
            lines.append(f"      {key}: {value}")
        lines.append("    patch: |-")
        for row in str(patch["patch"]).splitlines():
            lines.append(f"      {row}")
    path = directory / "kustomization.yaml"
    path.write_text("\n".join(lines) + "\n")
    return directory


def prepare_images(*, remote: bool, no_build: bool, context: str, username: str, token: str) -> None:
    if no_build:
        print("Skipping image build.")
        return
    compose = compose_cmd()
    info = subprocess.run(["docker", "info"], capture_output=True, text=True)
    if info.returncode != 0:
        raise SystemExit("Docker is installed but the daemon is not running.")
    if remote:
        print("+ docker login ghcr.io", flush=True)
        login = subprocess.run(
            ["docker", "login", "ghcr.io", "-u", username, "--password-stdin"],
            input=token,
            text=True,
            capture_output=True,
        )
        if login.returncode != 0:
            sys.stderr.write(login.stderr or login.stdout)
            raise SystemExit("Docker login to ghcr.io failed.")
    run([*compose, "build", "api", "bot", "web"], cwd=ROOT)
    if remote:
        run([*compose, "push", "api", "bot", "web"], cwd=ROOT)
        return
    if context.startswith("kind-"):
        ensure_tool("kind")
        name = context.removeprefix("kind-")
        for image in IMAGES:
            run(["kind", "load", "docker-image", image, "--name", name])
    elif context.startswith("k3d-"):
        ensure_tool("k3d")
        name = context.removeprefix("k3d-")
        for image in IMAGES:
            run(["k3d", "image", "import", image, "-c", name])
    elif context.startswith("minikube"):
        ensure_tool("minikube")
        for image in IMAGES:
            run(["minikube", "-p", context, "image", "load", image])


def rollout(name: str, kind: str) -> None:
    kubectl(
        "rollout",
        "status",
        f"{kind}/{name}",
        "-n",
        NAMESPACE,
        "--timeout=300s",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Deploy universal-discord-bot to the current Kubernetes context.")
    parser.add_argument("--noninteractive", "-y", action="store_true", help="Do not prompt. Read .env and cluster.env.")
    parser.add_argument("--replicas", type=int, default=1, help="Gateway pods. Use more than 1 only when shard count is above 1.")
    parser.add_argument("--no-build", action="store_true", help="Do not build or push images.")
    parser.add_argument("--local", action="store_true", help="Build images into this machine's cluster. Do not push.")
    parser.add_argument("--remote", action="store_true", help="Build, push to ghcr.io, and create a pull secret.")
    args = parser.parse_args()
    if args.replicas < 1:
        raise SystemExit("Replicas must be a positive integer.")
    if args.local and args.remote:
        raise SystemExit("Choose either --local or --remote.")

    ensure_tool("kubectl")
    context = kubectl("config", "current-context")
    if not context:
        raise SystemExit("kubectl has no current context. Point it at a cluster, then run this again.")
    remote = args.remote or (not args.local and not is_local_context(context))

    env = load_dotenv(args.noninteractive)
    cluster = load_cluster(args.noninteractive)
    public_url = cluster.get("PUBLIC_URL")
    host = public_host(public_url)
    username = cluster.get("GHCR_USERNAME") or GHCR_USER

    if remote and not cluster.get("GHCR_TOKEN"):
        if args.noninteractive:
            raise SystemExit("Set GHCR_TOKEN in deploy/kubernetes/cluster.env. It needs write:packages and read:packages.")
        token = prompt("GitHub token for ghcr.io (write:packages and read:packages)", secret=True)
        if not token:
            raise SystemExit("A GitHub token is required so the cluster can pull the images.")
        cluster.set("GHCR_TOKEN", token)
        cluster.save(0o600)

    image_plan = "use the images already in ghcr.io" if args.no_build else (
        "build and push to ghcr.io/acidmal" if remote else "build into this local cluster"
    )
    print()
    print("Deploy universal-discord-bot")
    print(f"  Context:  {context}")
    print(f"  Images:   {image_plan}")
    print(f"  URL:      {public_url}")
    print(f"  Replicas: {args.replicas}")
    if not args.noninteractive:
        answer = prompt("Continue?", default="Y").lower()
        if answer not in {"y", "yes"}:
            raise SystemExit("Cancelled.")

    if remote:
        prepare_images(
            remote=True,
            no_build=args.no_build,
            context=context,
            username=username,
            token=cluster.get("GHCR_TOKEN"),
        )
    else:
        prepare_images(remote=False, no_build=args.no_build, context=context, username=username, token="")

    password = existing_db_password() or cluster.get("POSTGRES_PASSWORD")
    if not password:
        password = random_secret()
    cluster.set("POSTGRES_PASSWORD", password)
    cluster.save(0o600)

    kubectl("apply", "-f", str(ROOT / "deploy" / "kubernetes" / "namespace.yaml"))
    apply_secret(env, cluster, password)
    apply_config(env, public_url)
    if remote:
        apply_pull_secret(username, cluster.get("GHCR_TOKEN"))

    chosen_ingress = ingress_class()
    if chosen_ingress:
        print(f"Using Ingress class {chosen_ingress}")
    else:
        print("No Ingress class found. The dashboard Service is still created.")
    overlay = write_overlay(
        host=host,
        ingress=chosen_ingress,
        remote=remote,
        replicas=args.replicas,
        external_db=bool(cluster.get("DATABASE_URL")),
    )
    kubectl("apply", "-k", str(overlay))
    if not cluster.get("DATABASE_URL"):
        rollout("postgres", "statefulset")
    for name in ("api", "bot", "web"):
        kubectl("rollout", "restart", f"deployment/{name}", "-n", NAMESPACE)
        rollout(name, "deployment")

    client_id = env.get("DISCORD_CLIENT_ID")
    print()
    print(f"Dashboard: {public_url}")
    print(f"OAuth redirect: {public_url}/auth/callback")
    print("Save that redirect in the Discord application, and enable Message Content and Server Members.")
    if client_id:
        print(
            "Invite: "
            f"https://discord.com/oauth2/authorize?client_id={client_id}"
            "&scope=bot%20applications.commands&permissions=1099780156438"
        )
    else:
        print("Set DISCORD_CLIENT_ID in .env and run this again to print the invite link.")
    print()
    print("Logs: kubectl logs -n universal-discord-bot -l app=bot -f")
    print("Settings live in .env and deploy/kubernetes/cluster.env. Run this script again after you change them.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        raise SystemExit(130) from None
