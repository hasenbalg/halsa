# Deploying Hälsa

Hälsa is a plain Django (gunicorn) web app. It listens for **http** on
port 8000 and expects whatever gives it TLS to be someone else's job —
Caddy, nginx, Traefik, a load balancer, a VPN tunnel. The project ships
no proxy config on purpose: pick the one that matches your network.

## Contents

- [Quick start (Docker Compose)](#quick-start-docker-compose)
- [Reverse proxy requirements](#reverse-proxy-requirements)
- [Environment reference](#environment-reference)
- [Security notes](#security-notes)
- [Testing & benchmarking](#testing--benchmarking)

## Quick start (Docker Compose)

Requires Docker with the compose plugin.

```bash
./install.sh                 # or: cp .env.example .env && edit, then:
docker compose build
docker compose up -d
```

The stack is three services:

| service  | what                                   | port                 |
|----------|----------------------------------------|----------------------|
| `db`     | PostgreSQL 17 (named volume)           | internal only        |
| `web`    | Django + gunicorn + whitenoise static  | `${HALSA_HTTP_PORT:-8000}` |
| `ticker` | busybox: `GET /scheduler/tick/` / 5min | none                 |

Open `http://localhost:8000`, log in with the superuser printed by
`install.sh` (or the one from your `.env`), rotate the password and
enable 2FA in Settings.

Compose example you can adapt (this is the whole project file, minus
comments — there is deliberately nothing else):

```yaml
services:
  db:
    image: postgres:17
    env_file: .env
    volumes:
      - halsa_db:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}"]
      interval: 5s
      timeout: 3s
      retries: 12

  web:
    build: .
    env_file: .env
    ports:
      - "${HALSA_HTTP_PORT:-8000}:8000"
    volumes:
      - halsa_logs:/logs
    depends_on:
      db:
        condition: service_healthy

  ticker:
    image: busybox:latest
    env_file: .env
    depends_on: [web]
    entrypoint: ["/bin/sh", "-c"]
    command: >
      while true; do
        wget -q -O /dev/null
        --header="Authorization: Bearer ${SCHE...KEN}"
        http://web:8000/scheduler/tick/ || true
        sleep 300
      done

volumes:
  halsa_db:
  halsa_logs:
```

Bare metal works too: `pip install -r requirements.txt`, point the
`POSTGRES_*`/`DJANGO_*` variables at your database, then
`python manage.py migrate && gunicorn halsa.wsgi:application -c gunicorn.conf.py`.

### Prebuilt image (no local build)

Every push to `main` publishes a multi-arch image
(**linux/amd64** and **linux/arm64**, so the same tag runs on servers
and Raspberry Pi 4/5) via GitHub Actions:

```bash
docker pull ghcr.io/hasenbalg/halsa:latest   # :<commit-sha> for pinning
```

To use it in the compose example above, replace the `build: .` line of
the `web` service with:

```yaml
    image: ghcr.io/hasenbalg/halsa:latest
```

Everything else (env_file, ports, volumes) stays the same. The image
runs migrations at container start, so upgrades are pull-and-restart:
`docker compose pull web && docker compose up -d web`.

## Reverse proxy requirements

The app needs exactly four things from the proxy:

1. **Forward the host name.** Pass the original `Host` header through
   (all proxies do by default). Add every hostname users type into
   `DJANGO_ALLOWED_HOSTS` (comma-separated), or requests answer 400.
2. **Say whether TLS was terminated.** Forward `X-Forwarded-Proto:
   https` and set `HALSA_BEHIND_PROXY=1`. Without this Django cannot
   know the browser is on https, and Secure-cookie/HSTS behaviour will
   be wrong.
3. **Send the scheduler tick** (or rely on the `ticker` sidecar):
   `GET /scheduler/tick/` every ~5 minutes with header
   `Authorization: Bearer `${SCHEDULER_TOKEN}``.
4. **Strip `Server: gunicorn`** if you care (cosmetic): gunicorn 26
   always sends it; e.g. Caddy `header -Server`, nginx
   `proxy_hide_header Server;`.
5. **Optionally: client IP.** `X-Forwarded-For` is respected only for
   logging if you add middleware; by default access logs record the
   proxy's IP, which is fine.

Everything else is yours. A minimal TLS front — any proxy you already
run, e.g. Caddy:

```
halsa.internal {
    reverse_proxy 127.0.0.1:8000 {
        header_up X-Forwarded-Proto https
    }
}
```

…with `.env`: `DJANGO_ALLOWED_HOSTS=halsa.internal,web`,
`HALSA_BEHIND_PROXY=1`, `SITE_BASE_URL=https://halsa.internal`.

Certs: use whatever CA your clients already trust (ACME, an internal
step-ca/Vault PKI, a distribution-pushed root). Hälsa does not manage
certificates.

## Environment reference

| variable | default | meaning |
|---|---|---|
| `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD` | — | database credentials |
| `DJANGO_SECRET_KEY` | — | long random string (`secrets.token_hex(32)`) |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | hostnames served (include `web` for the ticker) |
| `DJANGO_SUPERUSER_USERNAME/_PASSWORD/_EMAIL` | — | bootstrapped on first start only |
| `SCHEDULER_TOKEN` | — | Bearer token for `/scheduler/tick/`; empty disables it |
| `SITE_BASE_URL` | — | absolute base used in reminder-email links |
| `HALSA_HTTP_PORT` | `8000` | published app port (compose) |
| `HALSA_BEHIND_PROXY` | `0` | `1` = trust `X-Forwarded-Proto: https` |
| `HALSA_HSTS_SECONDS` | `31536000` | HSTS max-age on TLS answers; `0` disables |
| `INSECURE_COOKIES` | `0` | `1` = drop the `Secure` cookie flag; plain-http only (trusted LAN, benchmarks) |
| `EMAIL_HOST` … `EMAIL_FROM` | unset | SMTP; unset prints mails to the web log |
| `LOG_DIR` / `LOG_MAX_BYTES` / `LOG_BACKUP_COUNT` / `LOG_LEVEL` | `/logs`, 5 MB, 5, `INFO` | file logging knobs |

## Security notes

- The app sets its own hardening headers: CSP (`script-src 'none'` —
  Hälsa is zero-JavaScript; `/admin/` exempt for Django's own JS),
  `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`,
  `Referrer-Policy: same-origin`, HSTS on TLS answers.
- Keep TLS + a current cipher suite at the proxy; HSTS takes effect
  there automatically via the app header when
  `HALSA_BEHIND_PROXY=1`.
- Login has no built-in throttling; rate-limit `/accounts/` at the
  proxy or firewall if the app is reachable beyond your LAN.
- `.env` holds secrets: `chmod 600`, never commit it.
- Access logs contain client IPs; measurement values and other personal
  data are never logged (enforced by tests).

## Testing & benchmarking

The compose stack doubles as the test/benchmark harness — nothing here
needs a reverse proxy; everything talks to `http://localhost:8000` or
goes through Django's test client.

- **Unit/integration tests** (75): `bash runtests.sh` — rebuilds the
  image and runs the suite in a throwaway `test_*` database. To avoid
  collisions while other runs are active:
  `docker compose run --rm --no-deps -e POSTGRES_DB=halsasec web python manage.py test tracker`
  (create the DB once: `docker compose exec db createdb -U halsa halsasec`).
- **Coverage:** `docker compose run --rm --no-deps web sh -c "coverage
  run --source=tracker,halsa manage.py test tracker; coverage report -m"`.
- **Security audit (OWASP):** `python3 scripts/audit_anon.py` against a
  running stack; the authenticated battery runs inside an isolated
  container/DB:
  `docker compose run -d --name halsa-load --no-deps -e POSTGRES_DB=halsaload -e INSECURE_COOKIES=1 web`
  (starts gunicorn against the load DB), then
  `docker cp scripts/audit_authed.py halsa-load:/app/ && docker exec -w /app halsa-load python scripts_audit_authed.py`.
- **Load simulation:** `scripts/loadsim.py` (seed / pages / queries /
  week / stats phases, JSONL results) run inside the `halsa-load`
  container; `scripts/ladder.sh 100 200` steps user counts and
  checkpoints results to the host after every phase.
- **Soak:** `SOAK_HOURS=10.5 bash scripts/soak.sh` loops the full suite
  plus a login smoke check against `http://localhost:8000` and appends
  to `soak.log`.
- Benchmark databases (`halsaload`, `halsasec`) are separate from the
  app database — drop them when done:
  `docker compose exec db dropdb -U halsa halsaload`.
