# Website setup with Cloudflare

Use one public hostname for the dashboard. Discord sign-in and Twitch go-live alerts both call that same host. `PUBLIC_URL` is that origin, with `https://` and no trailing slash.

```text
https://bot.example.com
```

The browser, Discord, and Twitch must all use that host. These paths have to reach the API, on that same host:

| Path | Who calls it |
| --- | --- |
| `/` | Dashboard |
| `/api` | Dashboard |
| `/auth` | Discord OAuth. The redirect is `{PUBLIC_URL}/auth/callback` |
| `/health` | Health check |
| `/twitch` | Twitch EventSub. The callback is `{PUBLIC_URL}/twitch/eventsub` |

Docker Compose and a host install already proxy those API paths through the dashboard on port `5173`. Kubernetes sends them straight to the API and sends everything else to the dashboard.

Cloudflare's normal proxy only connects to origin ports **80** and **443**. A proxied DNS record cannot point at port `5173`. Use a local reverse proxy on port 80, or use a Cloudflare Tunnel, which can reach any local port.

## 1. Add the domain

1. Create a Cloudflare account and add the domain.
2. Point the domain's nameservers at the two Cloudflare nameservers Cloudflare shows you.
3. Wait until the domain status is Active.

## 2. Set SSL and cache

In the Cloudflare dashboard for the domain:

1. Open **SSL/TLS** and set the encryption mode to **Full (strict)** when the origin has a real certificate. Use **Full** when the origin speaks HTTP on port 80 and Cloudflare is the HTTPS endpoint visitors see.
2. Open **Caching → Cache Rules** and add a rule for the hostname that **bypasses cache**. The dashboard and the API are not static files. A cached `/auth` or `/api` response breaks sign-in.
3. If **Bot Fight Mode** or a WAF rule is on, add a skip rule for `POST` requests whose path starts with `/twitch`. Twitch's go-live push is a webhook, and a challenge page stops it.

`PUBLIC_URL` stays `https://bot.example.com` in every structure below. Put that same redirect in the Discord application under **OAuth2 → Redirects**.

After changing `PUBLIC_URL`, restart the API and the bot. On Kubernetes, run `./deploy-k8s.sh` again. With Compose, run `docker compose up -d`.

## 3. Docker Compose on a public server

The dashboard container publishes port `5173`. Put Caddy or nginx on the server so Cloudflare can use port 80.

Caddyfile:

```text
bot.example.com {
    reverse_proxy 127.0.0.1:5173
}
```

1. Start the bot with `./deploy.sh`. In `.env`, set `PUBLIC_URL=https://bot.example.com`.
2. Start Caddy so it listens on port 80 and proxies to `127.0.0.1:5173`.
3. In Cloudflare **DNS**, add an **A** record named `bot` pointing at the server's public IP. Turn the proxy on (orange cloud).
4. Set SSL/TLS to **Full** if Caddy is only on port 80. Set **Full (strict)** if Caddy also has a certificate on port 443.

Visitors hit Cloudflare on 443. Cloudflare connects to Caddy. Caddy connects to the dashboard, and the dashboard proxies `/api`, `/auth`, `/health`, and `/twitch` to the API container.

## 4. Docker Compose or a host install through a tunnel

Use this when the machine should not have a public IP. It covers Compose on a home server or laptop, and a host install where `uvicorn` is on port `8000` and `npm run dev` is on port `5173`.

1. Set `PUBLIC_URL=https://bot.example.com`.
2. Install `cloudflared` from <https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/>.
3. Log in and create a tunnel:

```bash
cloudflared tunnel login
cloudflared tunnel create universal-discord-bot
```

4. Route the hostname to the tunnel. Replace the tunnel id with the id the create command printed:

```bash
cloudflared tunnel route dns universal-discord-bot bot.example.com
```

5. Save this as `~/.cloudflared/config.yml`. The first path rules are only needed if you are not using the dashboard's built-in proxy. Compose and a host install should use the single rule.

```yaml
tunnel: TUNNEL_ID
credentials-file: /Users/you/.cloudflared/TUNNEL_ID.json

ingress:
  - hostname: bot.example.com
    service: http://localhost:5173
  - service: http_status:404
```

6. Start the bot (`./deploy.sh`, or the host install in the README), then start the tunnel:

```bash
cloudflared tunnel run universal-discord-bot
```

Cloudflare terminates HTTPS. The tunnel forwards the whole host to port `5173`.

## 5. Kubernetes with a public load balancer

`./deploy-k8s.sh` sets the Ingress host from `PUBLIC_URL`. The Ingress already splits `/api`, `/auth`, `/health`, and `/twitch` to the API and `/` to the dashboard.

1. Run `./deploy-k8s.sh` and answer the dashboard URL with `https://bot.example.com`.
2. Find the address of the ingress controller:

```bash
kubectl get svc -A | grep -i ingress
```

3. In Cloudflare **DNS**, add a record for `bot`:
   - **A** record if the address is an IP
   - **CNAME** record if the address is a hostname
4. Turn the proxy on.
5. Set SSL/TLS to **Full** when the Ingress serves HTTP on port 80. Set **Full (strict)** when the Ingress serves a certificate on port 443 whose name is `bot.example.com`.

The commented `tls` block in `deploy/kubernetes/ingress.yaml` is where a certificate secret is attached. A Cloudflare Origin Certificate can be stored in that secret. Create the secret in the `universal-discord-bot` namespace and name it in the Ingress. Then use **Full (strict)**.

## 6. Kubernetes through a tunnel

Use this when the cluster has no public load balancer.

1. Run `./deploy-k8s.sh` with `PUBLIC_URL=https://bot.example.com`.
2. Create a tunnel and a DNS route the same way as in the Compose tunnel section.
3. Point the tunnel at the ingress controller inside the cluster, not at a single pod. The Ingress keeps the path split. Example `config.yml` when the ingress controller Service is `ingress-nginx-controller` in the `ingress-nginx` namespace:

```yaml
tunnel: TUNNEL_ID
credentials-file: /etc/cloudflared/TUNNEL_ID.json

ingress:
  - hostname: bot.example.com
    service: http://ingress-nginx-controller.ingress-nginx.svc.cluster.local:80
  - service: http_status:404
```

4. Run `cloudflared` as a Deployment in the cluster, with that config and the tunnel credentials mounted from a Secret. The cloudflared pod must be able to resolve the ingress Service.

If the ingress class is not nginx, use that controller's Service name and namespace. The hostname in the tunnel must match the Ingress host.

## 7. Host install on a public server

The processes are the ones in the README: Postgres, `uvicorn` on port `8000`, and `npm run dev` on port `5173`. The Vite server proxies the API paths, so Cloudflare should reach port `5173` only.

1. Set `PUBLIC_URL=https://bot.example.com` in `.env` and restart `uvicorn` and the bot.
2. Put Caddy or nginx on port 80, proxying `bot.example.com` to `127.0.0.1:5173`, as in the Compose section.
3. Add a proxied **A** record for `bot` pointing at the server.
4. Set SSL/TLS to **Full**, or **Full (strict)** when the reverse proxy has a certificate.

## 8. Check

Open `https://bot.example.com`. The status page should load without a certificate warning.

```bash
curl -fsS https://bot.example.com/health
```

That should return JSON. Then sign in with Discord. If Discord says the redirect is invalid, the redirect saved in the developer portal is not exactly `https://bot.example.com/auth/callback`.

Twitch instant alerts need this URL to answer on port 443:

```text
https://bot.example.com/twitch/eventsub
```

A tunnel or an orange-cloud record both satisfy that, as long as the path reaches the API and the WAF does not challenge the POST.
