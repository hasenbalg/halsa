#!/usr/bin/env bash
# Hälsa installer — optional convenience wrapper.
#
#   ./install.sh [superuser-name]     (default: frank)
#
# Environment knobs:
#   HALSA_HTTP_PORT    published app port (default: 8000)
#   HALSA_SUPERUSER    superuser name (alternative to $1)
#
# The app answers plain http on that port. Put your own TLS reverse
# proxy in front for anything beyond a trusted LAN — see
# docs/DEPLOYMENT.md for the exact proxy requirements.
#
# Idempotent: generates .env with fresh secrets on first run (never
# overwrites an existing one), builds the images, starts the stack and
# waits until the site answers. Re-run any time to rebuild + restart.
#
# Requires: docker with the compose plugin; python3 or openssl for
# secret generation.
set -euo pipefail
cd "$(dirname "$0")"

SUPERUSER="${1:-${HALSA_SUPERUSER:-frank}}"
HTTP_PORT="${HALSA_HTTP_PORT:-8000}"
URL="http://localhost:${HTTP_PORT}"

say() { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

command -v docker >/dev/null || die "docker is not installed"
docker compose version >/dev/null 2>&1 || die "docker compose plugin missing"

gen_hex() {  # $1 = number of bytes -> hex on stdout
  if command -v python3 >/dev/null 2>&1; then
    python3 -c "import secrets,sys; print(secrets.token_hex(int(sys.argv[1])))" "$1"
  else
    openssl rand -hex "$1"
  fi
}

# --- 1. configuration ------------------------------------------------------
if [ -f .env ]; then
  say "keeping existing .env"
else
  [ -f .env.example ] || die ".env.example is missing"
  say "generating .env (superuser: $SUPERUSER)"
  PW=$(gen_hex 12)
  umask 077
  {
    echo "POSTGRES_DB=halsa"
    echo "POSTGRES_USER=halsa"
    echo "POSTGRES_PASSWORD=$(gen_hex 16)"
    echo "DJANGO_SECRET_KEY=$(gen_hex 32)"
    echo "DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,web"
    echo "DJANGO_SUPERUSER_USERNAME=$SUPERUSER"
    echo "DJANGO_SUPERUSER_PASSWORD=$PW"
    echo "DJANGO_SUPERUSER_EMAIL="
    echo "SCHEDULER_TOKEN=$(gen_hex 16)"
    echo "SITE_BASE_URL=${URL}"
    echo "HALSA_HTTP_PORT=${HTTP_PORT}"
    echo "INSECURE_COOKIES=1"
  } > .env
  umask 022
  chmod 600 .env
  echo
  echo "  superuser '$SUPERUSER' password: $PW"
  echo "  (also stored in .env — save it now, it is printed only once)"
  echo
  echo "  NOTE: .env sets INSECURE_COOKIES=1 so login works over plain"
  echo "  http. Set it to 0 (+ HALSA_BEHIND_PROXY=1) once a TLS proxy"
  echo "  fronts the app; see docs/DEPLOYMENT.md."
fi

# --- 2. build ----------------------------------------------------------------
say "building images (first build pulls base images)"
docker compose build

# --- 3. start ------------------------------------------------------------------
say "starting stack"
docker compose up -d

# --- 4. wait for readiness ---------------------------------------------------------
say "waiting for the web container"
ready=""
for _ in $(seq 1 40); do
  if docker compose ps --format '{{.Name}} {{.State}}' 2>/dev/null \
       | grep -q 'halsa-web running'; then
    if docker compose exec -T web python -c \
         "import urllib.request as u; u.urlopen('http://localhost:8000/accounts/login/')" \
         >/dev/null 2>&1; then
      ready=1; break
    fi
  fi
  sleep 2
done
[ -n "$ready" ] || die "web did not become ready — check: docker compose logs web"

# --- 5. verify the published port ----------------------------------------------
if command -v curl >/dev/null 2>&1; then
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 \
    "${URL}/accounts/login/" || true)
  [ "$code" = "200" ] && say "login page answers 200 on port ${HTTP_PORT}" \
                     || say "WARNING: got '$code' — check: docker compose logs web"
fi

echo
say "done. Hälsa is up at ${URL}"
echo "  next steps:"
echo "   1. log in as '$SUPERUSER', rotate your password, enable 2FA in Settings"
echo "   2. production use: put a TLS reverse proxy in front — docs/DEPLOYMENT.md"
echo "   3. optional: set EMAIL_* in .env + 'docker compose up -d' for reminder mails"
echo "   4. logs: docker compose logs -f web   (files: docker compose exec web ls /logs)"
