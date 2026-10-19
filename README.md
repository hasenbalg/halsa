# Hälsa

Personal health tracking for **blood glucose**, **weight** and **blood
pressure**. Django + PostgreSQL, designed to be fast and boring:
server-rendered HTML, **zero JavaScript**, server-rendered SVG charts,
automatic dark mode.

Everything runs locally in Docker — your health data never leaves your
network.

## Features

- **Quick entry** — one page, date/time prefilled, all three metrics
  side by side; Enter saves and stays on the page for the next reading.
- **Charts for everything** — server-rendered SVG line charts with
  target bands and rolling averages. No charting library, no JS, tiny
  pages (~7 ms responses).
- **Dark mode** — follows your OS `prefers-color-scheme`. Zero clicks,
  zero JS.
- **Units** — data is stored canonically in metric (mmol/L, kg, mmHg);
  each user picks metric or imperial display and everything converts.
- **Long-term trends** — plain-language insights: 4-week slopes,
  quarter-over-quarter comparisons, time-in-range, estimated HbA1c,
  blood-pressure category callouts.
- **Schedules & reminders** — named per-metric schedules (weekday +
  time), configurable window and grace per user *and* metric, and one
  digest email per user when measurements are overdue. Includes a link
  straight to the entry page.
- **2FA (TOTP)** — works with any authenticator app; enforcement only
  starts after you confirm the setup with a code, so nobody locks
  themselves out mid-setup.
- **Doctor-report PDF** — header, per-metric summary stats, trend
  insights, native line charts and compact reading tables
  (reportlab, pure Python).
- **JSON backup & restore** — full export (readings, schedules, metric
  settings, profile) in canonical units; the restore form merges by
  UUID, so re-importing the same file never duplicates anything.
- **UUID primary keys** on every table — safe to merge exports, no
  enumerable ids.
- **75 tests** over views, models, scheduling, export, restore, units,
  logging and the 2FA flow; OWASP-based security audit on record
  (`security-audit/REPORT.md`).

## Deploy

Hälsa is a plain Django (gunicorn) app listening for **http**; TLS is
the job of whatever reverse proxy you already run. Full instructions —
compose example, proxy requirements, environment reference, security
notes — live in **[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)**.

A prebuilt multi-arch image (amd64 + arm64) is published to the GitHub
Container Registry on every push to `main`:
`docker pull ghcr.io/hasenbalg/halsa:latest`.

Fastest path — an interactive question game that pulls the published
image (nothing is built):

```bash
curl -fsSL https://raw.githubusercontent.com/hasenbalg/halsa/main/install.sh | bash
```

It asks for port, hostnames, TLS-proxy y/n, timezone, optional SMTP
and an admin account, generates `.env` with fresh secrets, pulls
`ghcr.io/hasenbalg/halsa:latest` and starts the stack. Re-running it
in the same directory backs up `.env` + database, then offers to
update the image in place or redo the questions.

Manual path (or from a clone):

```bash
git clone https://github.com/hasenbalg/halsa.git
cd halsa
cp .env.example .env    # edit secrets, then:
docker compose -f docker-compose.release.yml up -d   # pull-based
# (docker-compose.yml with build: . is for development)
```

Open `http://localhost:8000`, log in with the admin account you chose,
enable 2FA. The stack is three
services: `db` (postgres:17), `web` (Django + gunicorn + whitenoise,
port `${HALSA_HTTP_PORT:-8000}`), `ticker` (busybox hitting
`/scheduler/tick/` every 5 min). Code is baked into the image — after
changing code: `docker compose build web && docker compose up -d web`.

## Using Hälsa

- **Log a reading:** the *Add* page; Enter saves and refocuses.
  Existing readings are editable/deletable from history.
- **Charts:** dashboard shows sparklines; each metric page has a full
  chart with target band, rolling average and range selector
  (7/30/90/365 days, all).
- **Schedules:** Settings → Schedules. Pick metric, weekday(s) and
  time; tune the match window and email grace per metric. The
  dashboard shows today's slots (done / today / overdue).
- **Reminders:** the `ticker` sidecar hits `/scheduler/tick/` every
  5 minutes; overdue slots produce **one digest email per user**.
  External cron works too:
  `curl -s -H "Authorization: Bearer ${SCHEDULER_TOKEN}" http://localhost:8000/scheduler/tick/`
- **Export:** Settings → doctor-report PDF (range selector) and full
  JSON backup. **Restore** accepts a JSON backup and merges by UUID.

## Logging

Every log line goes to **stdout** (so `docker compose logs web` works)
and to **rotated files** on the `halsa_logs` volume:

- `/logs/app.log` — app events (logins, 2FA, restores, exports,
  scheduler ticks) + all errors, incl. gunicorn errors
- `/logs/access.log` — HTTP access lines (request metadata only)

Rotation is size-based (default 5 MB × 5 files) and multi-process
safe. Tune with `LOG_DIR`, `LOG_MAX_BYTES`, `LOG_BACKUP_COUNT`,
`LOG_LEVEL` in `.env`.

Privacy rule: logs never contain measurement values, notes or
usernames — only events and counts. Access lines carry no referer or
user-agent.

## Backups

```bash
docker compose exec db pg_dump -U halsa halsa | gzip > halsa-$(date +%F).sql.gz
```

…plus the JSON export from Settings (portable, human-readable,
re-importable). Keep both off-host.

## Testing & benchmarking

The compose stack doubles as the test and benchmark harness; nothing
here needs a reverse proxy (everything hits `http://localhost:8000` or
uses Django's test client).

```bash
bash runtests.sh                 # rebuild + full suite (throwaway test DB)

# isolated DB while other runs are active:
docker compose exec db createdb -U halsa halsasec   # once
docker compose run --rm --no-deps -e POSTGRES_DB=halsasec \
    web python manage.py test tracker

# coverage
docker compose run --rm --no-deps web sh -c \
  "coverage run --source=tracker,halsa manage.py test tracker; coverage report -m"
```

- **Security audit (OWASP):** `python3 scripts/audit_anon.py` against a
  running stack; the authenticated battery
  (`scripts/audit_authed.py`) runs inside an isolated container on the
  `halsaload` database — see docs/DEPLOYMENT.md § Testing.
- **Load simulation:** `scripts/loadsim.py` (seed / pages / queries /
  week / stats phases, JSONL results) inside a `halsa-load` container
  running against its own database; `scripts/ladder.sh 100 200` steps
  user counts and checkpoints results to the host after every phase.
- **Soak:** `SOAK_HOURS=10.5 bash scripts/soak.sh` loops the full suite
  plus a login smoke check and appends to `soak.log`.
- Benchmark databases are separate from the app database; drop them
  when done: `docker compose exec db dropdb -U halsa halsaload`.

Conventions: UUID PKs everywhere (`UUIDModel`), canonical metric-unit
storage, no JavaScript in any template, charts are server-rendered
SVG, styling lives in `static/css/app.css`. `WORKLOG.md` tracks
requirements, decisions and progress.

## Troubleshooting

- **400 Bad Request on a hostname** — add it to
  `DJANGO_ALLOWED_HOSTS` in `.env` (comma-separated; include `web` for
  the ticker).
- **Login loops / CSRF failures behind your TLS proxy** — set
  `HALSA_BEHIND_PROXY=1` and make the proxy send
  `X-Forwarded-Proto: https`.
- **Login fails on plain http** — cookies carry the `Secure` flag;
  front the app with TLS, or set `INSECURE_COOKIES=1` on a trusted LAN.
- **`/scheduler/tick/` returns 403** — missing/wrong Bearer token or
  `SCHEDULER_TOKEN` unset in `.env`.
- **No reminder mails** — check `docker compose logs web` (console
  backend prints them) and that `EMAIL_HOST` is set for real SMTP.
- **Code change has no effect** — the code is baked into the image:
  `docker compose build web && docker compose up -d web`.

## Security notes

Login is required for every page; TOTP 2FA is per user; CSRF and
session cookies are hardened (`SameSite`, `Secure` behind TLS); the
app sets CSP (`script-src 'none'`), `X-Frame-Options: DENY`, HSTS on
TLS answers and `nosniff`; there is no JavaScript at all, which removes
a whole class of XSS payloads; the scheduler endpoint is token-gated
and returns only counters. Health data stays on your machine.
