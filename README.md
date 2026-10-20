# Hälsa

Personal health tracking for **blood glucose**, **weight** and **blood
pressure**. Django + PostgreSQL, designed to be fast and boring:
server-rendered HTML, **zero JavaScript**, server-rendered SVG charts,
automatic dark mode.

Everything runs locally in Docker — your health data never leaves your
network.

<p>
  <img src="docs/screenshots/02-dashboard.png" width="49%" alt="Dashboard with sparklines, today's schedule and long-term trends">
  <img src="docs/screenshots/03-add.png" width="49%" alt="Quick entry: all three metrics side by side">
</p>
<p>
  <img src="docs/screenshots/01-login.png" width="49%" alt="Login">
  <img src="docs/screenshots/07-history.png" width="49%" alt="History with inline edit and delete">
</p>

All screenshots are dark mode (auto-follows your OS); light mode is the
same layout on a white canvas.

## Features

### Quick entry

One page, date/time prefilled, all three metrics side by side; Enter
saves and stays on the page for the next reading. Existing readings are
editable and deletable straight from the history table.

### Charts for everything

Server-rendered SVG line charts with target bands and rolling averages.
No charting library, no JS, tiny pages (~7 ms responses). Each metric
page has a full chart with range selector (7/30/90/365 days, all).

<p>
  <img src="docs/screenshots/04-glucose.png" width="49%" alt="Glucose chart with target band">
  <img src="docs/screenshots/05-weight.png" width="49%" alt="Weight chart">
</p>
<p>
  <img src="docs/screenshots/06-pressure.png" width="49%" alt="Blood pressure chart, systolic and diastolic">
</p>

### Dark mode

Follows your OS `prefers-color-scheme`. Zero clicks, zero JS.

### Units

Data is stored canonically in metric (mmol/L, kg, mmHg); each user
picks metric or imperial display and everything converts — charts,
insights, PDF, entry forms.

### Languages

The whole app — UI, form errors, flash messages, reminder emails and
the doctor-report PDF — speaks **English and German**. Language follows
your browser's `Accept-Language` until you pin one in Settings; a
pinned language sticks to your account (and a cookie keeps even the
login page in it on your browser). German is informal *Du* with local
number and date formats (comma decimals, `20.10.2026`). New languages
are just a new `locale/<code>/` catalog — `makemessages`, translate,
`compilemessages`, no code changes.

<img src="docs/screenshots/18-german-dashboard.png" width="70%" alt="German dashboard (Blutzucker, Gewicht, Blutdruck)">

### Long-term trends

Plain-language insights: 4-week slopes, quarter-over-quarter
comparisons, time-in-range, estimated HbA1c, blood-pressure category
callouts. Shown on the dashboard and inside the PDF.

### Schedules & reminders

Named per-metric schedules (weekday + time), configurable match window
and email grace per user *and* metric, and one digest email per user
when measurements are overdue — with a link straight to the entry page.
The dashboard shows today's slots (done / today / overdue).

<img src="docs/screenshots/09-schedules.png" width="70%" alt="Schedules: per-metric weekday reminders">

### 2FA (TOTP)

Works with any authenticator app; enforcement only starts after you
confirm the setup with a code, so nobody locks themselves out
mid-setup.

<img src="docs/screenshots/10-2fa-setup.png" width="70%" alt="2FA setup with QR code">

### Doctor-report PDF

Header, per-metric summary stats, trend insights, native line charts
and compact reading tables (reportlab, pure Python) — one download for
the whole practice, no JavaScript on either side.

<img src="docs/screenshots/11-pdf.png" width="49%" alt="Doctor-report PDF page with glucose chart and readings table">

### Backup & restore

Full JSON export (readings, schedules, metric settings, profile) in
canonical units; the restore form merges by UUID, so re-importing the
same file never duplicates anything. **UUID primary keys** on every
table — safe to merge exports, no enumerable ids.

<img src="docs/screenshots/08-settings.png" width="70%" alt="Settings: units, reminder tuning, backup and restore">

### Tested

**100 tests** over views, models, scheduling, export, restore, units,
i18n, logging and the 2FA flow; OWASP-based security audit on record
(`security-audit/REPORT.md`).

## Mobile & tablet

One responsive stylesheet, still zero JavaScript: a CSS-only checkbox
hamburger below 700px, stacked entry forms, scrollable history table,
scaling charts and 44px touch targets; tablet trims spacing and keeps
the inline nav.

<p>
  <img src="docs/screenshots/12-mobile-dashboard.png" width="24%" alt="Phone dashboard">
  <img src="docs/screenshots/13-mobile-menu.png" width="24%" alt="Phone menu open">
  <img src="docs/screenshots/14-mobile-add.png" width="24%" alt="Phone quick entry">
  <img src="docs/screenshots/15-mobile-glucose.png" width="24%" alt="Phone glucose chart">
</p>
<p>
  <img src="docs/screenshots/16-tablet-dashboard.png" width="49%" alt="Tablet dashboard">
  <img src="docs/screenshots/17-tablet-glucose.png" width="49%" alt="Tablet glucose chart">
</p>

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

- **Demo data:** `scripts/demo_seed.py` seeds a synthetic `John`
  account with ~90 days of readings (the screenshots above were taken
  from it).
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
