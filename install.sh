#!/usr/bin/env bash
#
# Hälsa installer — an interactive question game that pulls the
# published image from ghcr.io (it never builds).
#
#   curl -fsSL https://raw.githubusercontent.com/hasenbalg/halsa/main/install.sh | bash
#
# or from a clone:  ./install.sh
#
# Installs into the current directory (override with
# HALSA_INSTALL_DIR=/path). Re-running in an installed directory backs
# up .env and the database, then offers to update the image in place or
# redo the questions.
#
# Requires: docker with the compose plugin, curl.
set -euo pipefail

RAW="https://raw.githubusercontent.com/hasenbalg/halsa/main"
IMAGE="ghcr.io/hasenbalg/halsa:latest"
cd "${HALSA_INSTALL_DIR:-$PWD}"

say() { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

command -v docker >/dev/null || die "docker is not installed"
docker compose version >/dev/null 2>&1 || die "docker compose plugin missing"
command -v curl >/dev/null || die "curl is not installed"

gen_hex() {  # $1 = bytes -> hex on stdout
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex "$1"
  else
    head -c "$1" /dev/urandom | od -An -tx1 | tr -d ' \n'
  fi
}

# read helpers: normal run reads the terminal; curl|bash reads /dev/tty;
# piped stdin (automation/tests) is the last resort. The tty is probed
# by actually opening it — [ -r /dev/tty ] lies without a controlling
# terminal.
if [ -t 0 ]; then
  TTY_OK=0
elif : </dev/tty 2>/dev/null; then
  TTY_OK=1
else
  TTY_OK=0
fi

read_line() {  # one line on stdout; exits the script on EOF
  local ans=""
  if [ "$TTY_OK" = 1 ]; then
    read -r ans </dev/tty || die "input stream closed"
  else
    read -r ans || die "input stream closed"
  fi
  printf '%s' "$ans"
}

read_hidden() {  # one hidden line on stdout; exits the script on EOF
  local ans=""
  if [ "$TTY_OK" = 1 ]; then
    read -rs ans </dev/tty || die "input stream closed"; echo >&2
  elif [ -t 0 ]; then
    read -rs ans || die "input stream closed"; echo >&2
  else
    read -r ans || die "input stream closed"
  fi
  printf '%s' "$ans"
}

ask() {  # ask "prompt" "default" -> answer on stdout
  local prompt="$1" def="$2" ans=""
  printf '\033[1;32m?\033[0m %s \033[2m[%s]\033[0m ' "$prompt" "$def" >&2
  ans=$(read_line)
  printf '%s' "${ans:-$def}"
}

ask_secret() {  # hidden input on stdout
  local prompt="$1"
  printf '\033[1;32m?\033[0m %s ' "$prompt" >&2
  read_hidden
}

banner() {
  printf '\033[1m  H\xc3\xa4lsa\033[0m  \033[2minstaller\033[0m\n'
  echo "  health tracking on your own server"
  echo
}
banner

# ---------------------------------------------------------------------------
# existing installation?  back up, then offer update / redo / quit
# ---------------------------------------------------------------------------
KEEP_PG_USER="" ; KEEP_PG_DB="" ; KEEP_PG_PW=""
if [ -f .env ] && [ -f docker-compose.yml ]; then
  say "existing Hälsa installation found here"
  mkdir -p backups
  ts=$(date +%Y%m%d-%H%M%S)
  cp -p .env "backups/env-$ts"
  say "backed up .env -> backups/env-$ts"
  if docker compose ps --status running --services 2>/dev/null | grep -qx db; then
    docker compose exec -T db pg_dump -U halsa halsa < /dev/null | gzip > "backups/halsa-$ts.sql.gz"
    say "dumped database -> backups/halsa-$ts.sql.gz"
  else
    say "database not running; skipped the pg_dump backup"
  fi
  echo
  echo "  1) update to the latest image (keep settings + data)"
  echo "  2) redo the questions (keep the database)"
  echo "  3) quit"
  choice=$(ask "Choice" 1)
  case "$choice" in
    1)
      say "pulling $IMAGE"
      docker compose pull
      docker compose up -d
      say "updated. logs: docker compose logs -f web"
      exit 0 ;;
    2)
      # the postgres volume keeps its password — reuse the old one
      KEEP_PG_USER=$(grep -s '^POSTGRES_USER=' .env | cut -d= -f2-)
      KEEP_PG_DB=$(grep -s '^POSTGRES_DB=' .env | cut -d= -f2-)
      KEEP_PG_PW=$(grep -s '^POSTGRES_PASSWORD=' .env | cut -d= -f2-)
      say "redoing the questions (database password preserved)" ;;
    *)
      say "nothing changed" ; exit 0 ;;
  esac
fi

# ---------------------------------------------------------------------------
# the question game
# ---------------------------------------------------------------------------
echo
say "let's configure Hälsa — press Enter to accept a default"

HTTP_PORT=$(ask "Which TCP port should Hälsa listen on?" 8000)
HOSTS=$(ask "Hostnames this app is reachable at (comma-separated)" "localhost,127.0.0.1")
PROXY=$(ask "Is a TLS reverse proxy in front of it? (y/N)" n)
case "$PROXY" in [yY]*) PROXY=1 ;; *) PROXY=0 ;; esac

TIMEZ=$(ask "Timezone for schedules and reminders" "Europe/Berlin")

SMTP_HOST=$(ask "SMTP host for reminder emails (empty = skip)" "")
SMTP_PORT=587 ; SMTP_USER="" ; SMTP_PW="" ; SMTP_FROM="" ; SMTP_TLS=1
if [ -n "$SMTP_HOST" ]; then
  SMTP_PORT=$(ask "SMTP port" 587)
  tls=$(ask "Use STARTTLS? (Y/n)" y)
  case "$tls" in [nN]*) SMTP_TLS=0 ;; esac
  SMTP_USER=$(ask "SMTP username (empty = no auth)" "")
  if [ -n "$SMTP_USER" ]; then
    SMTP_PW=$(ask_secret "SMTP password for $SMTP_USER")
  fi
  SMTP_FROM=$(ask "From address" "halsa@${HOSTS%%,*}")
fi

ADMIN_USER=$(ask "Admin username to create" admin)
while :; do
  ADMIN_PW=$(ask_secret "Admin password (min 8 chars)")
  if [ "${#ADMIN_PW}" -lt 8 ]; then say "too short — try again"; continue; fi
  again=$(ask_secret "Repeat it")
  if [ "$ADMIN_PW" = "$again" ]; then break; fi
  say "passwords did not match — try again"
done

# ---------------------------------------------------------------------------
# generate .env with fresh secrets
# ---------------------------------------------------------------------------
umask 077
PG_USER="${KEEP_PG_USER:-halsa}"
PG_DB="${KEEP_PG_DB:-halsa}"
PG_PW="${KEEP_PG_PW:-$(gen_hex 16)}"
SECRET=$(gen_hex 32)
TOK=$(gen_hex 16)
if [ "$PROXY" = 1 ]; then
  BASE_URL="https://${HOSTS%%,*}"
  COOKIES=0
else
  BASE_URL="http://localhost:${HTTP_PORT}"
  COOKIES=1
fi
{
  echo "POSTGRES_DB=$PG_DB"
  echo "POSTGRES_USER=$PG_USER"
  echo "POSTGRES_PASSWORD=$PG_PW"
  echo "DJANGO_SECRET_KEY=$SECRET"
  echo "DJANGO_ALLOWED_HOSTS=${HOSTS},web"
  echo "DJANGO_SUPERUSER_USERNAME=$ADMIN_USER"
  echo "DJANGO_SUPERUSER_PASSWORD=$ADMIN_PW"
  echo "DJANGO_SUPERUSER_EMAIL="
  echo "SCHEDULER_TOKEN=$TOK"
  echo "SITE_BASE_URL=$BASE_URL"
  echo "HALSA_HTTP_PORT=$HTTP_PORT"
  echo "TIME_ZONE=$TIMEZ"
  echo "INSECURE_COOKIES=$COOKIES"
  echo "HALSA_BEHIND_PROXY=$PROXY"
  if [ -n "$SMTP_HOST" ]; then
    echo "EMAIL_HOST=$SMTP_HOST"
    echo "EMAIL_PORT=$SMTP_PORT"
    echo "EMAIL_USE_TLS=$SMTP_TLS"
    echo "EMAIL_HOST_USER=$SMTP_USER"
    echo "EMAIL_HOST_PASSWORD=$SMTP_PW"
    echo "EMAIL_FROM=$SMTP_FROM"
  fi
} > .env
chmod 600 .env
umask 022
say ".env written with fresh secrets (chmod 600)"

# ---------------------------------------------------------------------------
# compose file + pull + start
# ---------------------------------------------------------------------------
if [ -f docker-compose.release.yml ]; then
  cp docker-compose.release.yml docker-compose.yml
else
  curl -fsSL "$RAW/docker-compose.release.yml" -o docker-compose.yml \
    || die "could not download docker-compose.release.yml from GitHub"
fi
say "compose file ready (image-based, no build)"

say "pulling $IMAGE"
docker compose pull

say "starting the stack"
docker compose up -d

say "waiting for the app to answer"
ready=""
for _ in $(seq 1 60); do
  if docker compose exec -T web python -c \
       "import urllib.request as u; u.urlopen('http://localhost:8000/accounts/login/')" \
       </dev/null >/dev/null 2>&1; then
    ready=1; break
  fi
  sleep 2
done
[ -n "$ready" ] || die "web did not become ready — check: docker compose logs web"

# ---------------------------------------------------------------------------
# superuser (created once; existing accounts are never touched)
# ---------------------------------------------------------------------------
exists=$(docker compose exec -T web python manage.py shell -c \
  "from django.contrib.auth import get_user_model as g; print(g().objects.filter(username='$ADMIN_USER').exists())" \
  </dev/null 2>/dev/null | tail -1 || true)
if [ "$exists" = "True" ]; then
  say "admin user '$ADMIN_USER' present (if it pre-dated this install its password was not changed)"
else
  docker compose exec -T web python manage.py createsuperuser --noinput \
    </dev/null >/dev/null 2>&1 || die "could not create the admin user — check: docker compose logs web"
  say "admin user '$ADMIN_USER' created"
fi

# ---------------------------------------------------------------------------
# summary
# ---------------------------------------------------------------------------
code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 \
  "$BASE_URL/accounts/login/" || true)
echo
say "done. Hälsa answers at ${BASE_URL} (HTTP $code)"
echo "  login: $ADMIN_USER / the password you just chose"
echo
echo "  next steps:"
echo "    1. log in, enable 2FA in Settings"
echo "    2. reminder emails: $( [ -n "$SMTP_HOST" ] && echo "SMTP configured ($SMTP_HOST)" || echo "no SMTP set — re-run to add it, or edit .env (EMAIL_*)" )"
echo "    3. scheduler token (for external cron): $TOK"
echo "    4. backups: docker compose exec db pg_dump -U $PG_DB $PG_DB | gzip > halsa.sql.gz"
echo "    5. logs: docker compose logs -f web"
if [ "$PROXY" = 0 ]; then
  echo
  echo "  NOTE: plain http on a LAN. For anything beyond that, put a TLS"
  echo "  reverse proxy in front — docs/DEPLOYMENT.md has the details."
fi
