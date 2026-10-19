# Hälsa — OWASP Top 10 Security Audit

Date: 2026-10-19 · Target: Django 5.2.18 / PostgreSQL 17 / Caddy stack at
`/opt/data/halsa` (live production + isolated load DB for authed probes).

Method: bandit static analysis, pip-audit dependency scan, `manage.py check
--deploy`, 25 anonymous live probes (`scripts/audit_anon.py`), 17
authenticated live probes (`scripts/audit_authed.py`), code review of every
trust boundary. Final state: **25/25 + 17/17 probes pass, 75 tests green**.

## Findings

### CRITICAL — weak/truncated secrets in `.env` (A02/A05) — FIXED
`DJANGO_SECRET_KEY` was 13 chars (truncated at scaffold time),
`POSTGRES_PASSWORD` 12, `DJANGO_SUPERUSER_PASSWORD` 11. A short secret key
allows session forgery; short DB password is brute-forceable if the port is
ever exposed.
**Fix:** all four secrets rotated to 32/64-hex random values (DB role
password ALTERed in place, superuser password reset), stack recreated and
re-verified. `install.sh` already generates full-length secrets, so fresh
installs were never affected.

### MEDIUM — open redirect after login (A01) — FIXED
`login_view` accepted any `next` starting with `/`, so `?next=//evil.example`
(protocol-relative) redirected users to an attacker host after login.
**Fix:** `url_has_allowed_host_and_scheme()` with the request host; verified
live that `//evil`, `/\evil` are coerced to `/` while `/safe/page/` is kept.
Regression tests added (`tracker/tests4.py`).

### MEDIUM — no login/2FA throttling (A07) — OPEN (recommendation)
Unlimited password and TOTP-code attempts per IP/user. Mitigating factors:
TOTP codes rotate every 30 s and the app is single-user-scale behind HTTPS.
**Recommend:** django-axes (or a small lockout counter) before multi-user use.

### LOW — unbounded note field (A04/A05) — FIXED
`note` was a `TextField` with no length limit (5 000-char notes stored fine).
**Fix:** `max_length=2000` on all three reading models + migration
`0002_note_max_length`; form now rejects oversized notes (probe verified).

### LOW — missing security headers (A05) — FIXED
No CSP, no HSTS, `Server: gunicorn` disclosed.
**Fix (Caddyfile + gunicorn.conf.py):** strict CSP
(`script-src 'none'` — the app is zero-JS; `/admin/*` excluded so Django
admin keeps working), HSTS `max-age=31536000; includeSubDomains`,
`server_header = False` + `header -Server`. Verified live.

### INFO — accepted risks / by design
- **TOTP seeds stored in plaintext** in Postgres (pyotp standard). Anyone
  with DB read access bypasses 2FA; disk-level protection assumed.
- **mark_safe in `charts.py`** (bandit B308/B703): reviewed — all sinks get
  escaped labels, float-formatted numbers, and hardcoded `var(--…)` colors;
  no user string reaches them. Safe by construction; keep it that way.
- **Forged `Host:` header** gets an empty Caddy reply (app never sees it);
  Django `ALLOWED_HOSTS` is the second gate.
- **Email header injection** via schedule names: CRLF stays inert body text,
  never a header (probe verified `Bcc` is not parsed).
- **Access log contains client IPs** (needed for abuse triage); measurement
  values and personal data are never logged (enforced + tested, tests3).
- **Login timing**: PBKDF2 runs only for existing users → user enumeration
  by timing is theoretically possible; acceptable at this scale.
- **`check --deploy` W004/W008** (HSTS/SSL-redirect in Django): intentionally
  handled at the proxy, not the app.

## Clean results
- **A02 Crypto:** HTTPS-only (Caddy `tls internal`), HSTS now on, cookie
  flags verified `Secure` + `SameSite=Lax`, Argon2/PBKDF2 password hashing.
- **A03 Injection:** bandit clean apart from reviewed `mark_safe`; ORM-only
  queries (no raw SQL); stored XSS probe (`<img onerror>`) escaped in
  dashboard/metric/history; JSON export `application/json` + `nosniff`;
  PDF is text-rendered (no HTML); NUL bytes rejected by form validation.
- **A01 Access control:** every route bounces anonymous users to login;
  IDOR edit/delete of another user's row → 404 (victim row survives);
  scheduler tick requires bearer token (403 without/with wrong token);
  CSRF enforced (403 tokenless POST).
- **A06 Vulnerable components:** pip-audit clean (Django 5.2.18, psycopg
  3.3.6, gunicorn 26.2.0, reportlab 5.0.1, PyOTP 2.10.0).
- **A07 Auth:** 2FA flow verified live (pending session without auth, wrong
  TOTP rejected, valid TOTP accepted); session key rotates on login.
- **A09 Logging:** privacy rule holds (events + counts only); rotation live.
- **A10 SSRF:** no outbound fetches (SMTP only, config-driven).

## Reproduce
```
python3 scripts/audit_anon.py            # anonymous battery vs https://localhost
docker exec -w /app halsa-load python scripts_audit_authed.py   # authed battery (isolated DB)
/opt/data/handball-registration/.venv/bin/bandit -r halsa tracker scripts -q
pip-audit -r requirements.txt
docker compose exec web python manage.py check --deploy
```
