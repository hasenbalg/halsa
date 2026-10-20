# Hälsa — work log

Personal health tracker: blood glucose, weight, blood pressure.
Django + PostgreSQL + Caddy in Docker. Room: #haelsa. Started 2026-10-17.

## Requirements (grill-me sessions + follow-ups)

Core
- R1  Django app in Docker with PostgreSQL
- R2  Track blood glucose, weight, blood pressure
- R3  Fast to load
- R4  Easy to use
- R5  Graphs for everything
- R6  Dark mode

Grill session 1 (base app)
- G1  Deploy on this host, Caddy reverse proxy, HTTPS, login required
- G2  One quick-entry page: date/time prefilled, metrics side by side,
      Enter saves and stays on page
- G3  Server-rendered SVG charts, zero JS
- G4  Dark mode auto via prefers-color-scheme, zero JS
- G5  Store European units (mmol/L, kg, mmHg); unit preference on the user
      profile; convert for display for imperial users

Follow-up requirements
- R7  Modern design language for the UI
- R8  2FA authentication (TOTP, per django-models-admin recipe)
- R9  UUID primary keys for every table
- R10 Name it "Hälsa"
- R11 Avoid JS where possible (zero JS in practice)
- R12 Point out long-term trends (insights engine)

Grill session 2 (scheduling)
- G6  Named schedules per metric (metric + weekdays + time)
- G7  ONE digest email when multiple measurements are overdue
- G8  Tick runs via HTTP endpoint (token protected)
- G9  Satisfied = reading within +/- window of slot; email at slot + grace;
      window and grace configurable per user AND metric
- G10 busybox sidecar curls the endpoint every 5 min; external cron also OK
- R13 Reminder email contains a link (straight to /add/)

Grill session 3 (export)
- R14 PDF + JSON export
- G11 PDF = doctor report: header, period, per-metric stats, trend insights,
      compact tables; reportlab, pure Python
- G12 PDF includes native reportlab line charts per metric
- G13 JSON = full backup (readings, schedules, metric settings, profile),
      canonical units, ISO timestamps; range selector only affects PDF
- R15 JSON must be importable (restore); put export/import in a
      "Backup and restore data" section
- R16 Track requirements/planning/progress in this work log

## Plan

1. Scaffold compose stack: db (postgres:17), web (Django+gunicorn),
   proxy (caddy, tls internal, 443), ticker (busybox loop)        [done]
2. Models: UUIDModel base; Profile (units + TOTP); GlucoseReading,
   WeightReading, BloodPressureReading; MetricSettings, Schedule,
   OverdueNotice                                                  [done]
3. units.py conversion helpers; charts.py SVG; trends.py insights  [done]
4. Auth: custom login with TOTP step; admin login redirects to it;
   enrollment page with QR (pyotp + segno)                         [done]
5. Views: dashboard (cards + sparklines + insights + today panel),
   quick add, per-metric detail w/ range chips, history, edit/delete,
   settings (units, scheduling knobs, backup/restore, 2FA, password)[done]
6. Scheduling engine: recent_slots, satisfied window, OverdueNotice
   dedupe, one digest email per user per tick, /scheduler/tick/     [done]
7. Export: /export/json/ full backup; /export/pdf/ reportlab report;
   restore.py idempotent merge-by-uuid upload at /settings/restore/ [done]
8. Design system: static/css/app.css, modern minimal, CSS vars,
   light+dark, responsive, no JS                                    [TODO]
9. Tests: models, units, 2FA login, quick add, scheduling (window,
   grace, single notice, digest), tick auth, export json/pdf,
   restore roundtrip                                                [TODO]
10. Build image, run stack, migrate, seed nothing, verify e2e via
   curl through Caddy + browser screenshots (light+dark)            [TODO]
11. README, .gitignore, git init + push to Gitea (ask which instance) [TODO]

## Progress log

- 2026-10-17 Grill 1 (G1-G5) answered; host checked: ports 80/443 free,
  caddy:latest + postgres:17 images present locally.
- 2026-10-17 Scaffold + models + units + charts + trends + forms + views
  written. Redactor quirk hit twice: lines like `SECRET_KEY = env(...)`
  land on disk as `***`; fixed by runtime-built strings; grep after every
  write.
- 2026-10-17 Grill 2 (G6-G10) + R13; scheduling engine + tick endpoint +
  busybox ticker sidecar written.
- 2026-10-17 Grill 3 (G11-G13) + R15; pdfexport.py (reportlab),
  restore.py (merge-by-uuid), settings "Backup and restore" section done.
- 2026-10-17 app.css, tests.py (26 tests) green; migrations generated.
- 2026-10-17 Coverage push: coverage in requirements, tests2.py second
  wave (charts, trends, restore edges, 2FA flow, settings POSTs, sched
  extras, export, edit flows). 63 tests, 98% total (views 97%, models
  99%, pdfexport 95%). Fixed real bugs found by tests: reportlab needed
  HexColor not hex strings; LinePlot has no `joined`/`symbol` attrs;
  next_slot now returns None for inactive schedules; login code step
  now bounces back to password step if 2FA was disabled mid-login.
- 2026-10-17 Deploy fix: host cannot bind-mount single files (Caddyfile)
  -> Dockerfile.proxy bakes it into halsa-proxy image. Caddy bare `:443`
  site gets no internal cert ("no certificate available for 'localhost'")
  -> site address now from HALSA_HOSTNAMES (default localhost)
  + encode zstd gzip. SITE_BASE_URL updated. E2E verified through Caddy:
  login 200 in ~7ms, css 200, http->https 301, tick 403/200 by token.
- 2026-10-17 install.sh (idempotent: gen .env w/ secrets, build, up,
  readiness wait, HTTPS verify) + README.md (features, architecture,
  install, config table, usage, backups, dev, troubleshooting) +
  complete .env.example. Removed debug_login.py. install.sh run
  end-to-end green.
- 2026-10-17 Logging: file + stdout everywhere. halsa/logsetup.py
  SafeRotatingFileHandler (multi-process-safe: reopens on inode change);
  settings LOGGING (console + /logs/app.log, 5 MB x 5, env-tunable
  LOG_DIR/LOG_MAX_BYTES/LOG_BACKUP_COUNT/LOG_LEVEL); gunicorn.conf.py
  splits access log to stdout + /logs/access.log (no referer/UA);
  halsa_logs named volume at /logs; INSECURE_COOKIES=1 opt-in flag for
  plain-http load testing. Privacy rule enforced: events + counts only,
  never values/usernames (tested). tests3.py: 72 tests green.
- 2026-10-17 Load sim: scripts/loadsim.py (seed 5y data, HTTP page
  timings, week simulation, query counts, db stats) + scripts/ladder.sh
  (10->200 users) + scripts/soak.sh (10h+ suite loop + smoke).
- 2026-10-19 Laptop setup: Caddyfile site address now
  {$HALSA_HOSTNAMES:localhost}; compose ports/hostnames via
  HALSA_HTTP_PORT/HALSA_HTTPS_PORT/HALSA_HOSTNAMES (.env-driven);
  install.sh generates laptop-default .env (localhost, 80/443,
  overridable). Fixed gunicorn access file logging for gunicorn 26:
  access records arrive PRE-FORMATTED (msg=fmt, args=atoms dict) ->
  file handler must use default %(message)s formatter; access_log_format
  set without referer/UA. Verified: access.log + app.log both written.
  Repo pushed to the internal Git service (private, 59 files, .env
  excluded, server-side tree verified). 72 tests green.
- 2026-10-19 Load ladder resumed (79 users survived disk-full event;
  results now copied to host after every phase) -> 100 -> 200, then
  10.5h soak chained behind it (scripts/soak.sh, soak.log).
- NEXT: point real DNS/hosts entry at this host, first login + rotate
  superuser password, enable 2FA, configure SMTP for reminder mails.

## Decisions / environment notes

- Directory /opt/data/halsa (ASCII path), display name "Hälsa".
- Caddy `tls internal` (Caddy-managed internal CA); browser
  must import the Caddy root CA or accept the warning once.
- Superuser bootstrapped from .env (frank / generated pw, rotate after
  first login).
- Email: SMTP via EMAIL_* env vars; console backend when unset.
- SCHEDULER_TOKEN in .env; tick accepts GET or POST with
  `Authorization: Bearer <token>`.
- Weekdays stored as JSON ints (Mon=0..Sun=6).
- Weight is day-granular: any same-day reading satisfies a weight slot.


## 2026-10-19 — OWASP security audit

- Full OWASP Top 10 audit: bandit, pip-audit, check --deploy, 25 anon + 17
  authed live probes. Report: security-audit/REPORT.md.
- Fixed: truncated .env secrets (rotated all four), open redirect via
  protocol-relative ?next (url_has_allowed_host_and_scheme + tests4.py),
  unbounded note field (max_length=2000 + migration 0002), missing CSP/HSTS
  (Caddy; /admin excluded), Server header suppressed.
- Open recommendation: login/2FA throttling (django-axes) before multi-user.
- Probe scripts kept: scripts/audit_anon.py, scripts/audit_authed.py.
- 75 tests green; 25/25 + 17/17 probes pass.


## 2026-10-19 — reverse proxy removed from the project

- Caddy is gone: Caddyfile, Dockerfile.proxy, proxy service, caddy
  volumes deleted; running proxy container/volumes/image removed.
- Compose stack = db + web + ticker; web publishes ${HALSA_HTTP_PORT:-8000}.
- App now emits its own hardening headers: halsa/security.py middleware
  (CSP script-src 'none', /admin/ exempt; Referrer-Policy) + Django HSTS
  on TLS answers (HALSA_HSTS_SECONDS). New env: HALSA_BEHIND_PROXY
  (trusts X-Forwarded-Proto), HALSA_HSTS_SECONDS.
- gunicorn 26 fact: server_header switch REMOVED upstream; "Server:
  gunicorn" is unconditional — strip at the proxy (documented).
- docs/DEPLOYMENT.md: full deployment page (compose example, proxy
  requirements, env reference, security notes, testing & benchmarking).
  README slimmed and links to it.
- Test/bench harness intact and re-verified: 78 tests green, audit
  probes 23/23 + 17/17, loadsim pages smoke green (halsa-load now runs
  gunicorn itself, no proxy needed). Soak loop killed after 11h (it had
  entered a test-DB collision spin).

Hosting: public GitHub repo github.com/hasenbalg/halsa (frank's
fresh single-commit init; local history realigned to it — the old
internal-hosting history is not pushed anywhere public).



## Issue #3 — interactive install script (2026-10-19)

install.sh is now a standalone question game (curl | bash) that PULLS
ghcr.io/hasenbalg/halsa:latest — it never builds. Questions: port,
hostnames, TLS-proxy y/n, timezone, optional SMTP, admin account
(hidden, confirmed). Generates .env with fresh secrets. Re-running in
an installed dir: backs up .env + pg_dump, then offers update-in-place
or redo-Q&A (postgres password preserved from old .env).

- docker-compose.release.yml: image-based stack (no container_name, so
  it coexists with the dev stack); dev docker-compose.yml unchanged.
- TIME_ZONE is now an env knob (was hardcoded Europe/Berlin).
- Gotcha: [ -r /dev/tty ] is true even with no controlling terminal —
  probe by opening it; EOF on input must die, not loop.
## Issue #2 — mobile optimization (2026-10-20)

Menu: CSS-only checkbox hamburger below 700px (checkbox + label in
base.html, :checked ~ .nav; burger morphs to X). Breakpoints: 1024px
tablet trims spacing, 700px phone. Plumbing: form-grid stacks, history
table wrapped in .table-scroll (min-width 540), 44px touch targets,
16px inputs (stops iOS focus-zoom), schedule rows + metric knobs
reflow. Desktop verified PIXEL-IDENTICAL (before/after diff at
1280x800; only the prefilled clock minute differs). README gets 4
phone + 2 tablet dark shots (docs/screenshots/12-17).
Gotcha: browser harness device-metrics override resets between
browser_exec calls — re-assert viewport + media emulation in every
call; and JS-set .checked is lost on navigation (set it after the
final goto).

Follow-up: bottom horizontal scrollbars came from unwrapped tables
(dashboard/metric/schedules) overflowing their panels; all four
templates now use .table-scroll (thin scrollbar inside the panel).
Verified zero overflow at 390/820 on every page.

## Issue #9 — glucose meal context (2026-10-20)

Glucose readings get an optional context: Fasting / Before meal /
After meal / Random (plain words in the app, Fasting/Preprandial/
Postprandial/Random in the doctor-report PDF). Compact dropdown on
the add page under Glucose; edit form too. Chart markers encode
context by shape (circle/diamond/square/triangle, only when <=45
points). Badges in glucose + history tables. JSON export carries
the field; old backups restore with blank context. Migration 0003.
88 tests green (tests6.py).
