#!/bin/sh
set -e
export DJANGO_SETTINGS_MODULE=halsa.settings

# log volume (no-op when /logs is a mounted volume)
mkdir -p "${LOG_DIR:-/logs}" 2>/dev/null || true

echo "Waiting for PostgreSQL..."
python - <<'EOF'
import os, socket, sys, time
host = os.environ.get("POSTGRES_HOST", "db")
for _ in range(60):
    try:
        socket.create_connection((host, 5432), timeout=2).close()
        sys.exit(0)
    except OSError:
        time.sleep(1)
sys.exit("database not reachable")
EOF

python manage.py migrate --noinput
python manage.py collectstatic --noinput

# One-time superuser bootstrap (idempotent)
if [ -n "$DJANGO_SUPERUSER_USERNAME" ]; then
python - <<'EOF'
import os, django
django.setup()
from django.contrib.auth import get_user_model
U = get_user_model()
u = os.environ["DJANGO_SUPERUSER_USERNAME"]
if not U.objects.filter(username=u).exists():
    U.objects.create_superuser(
        username=u,
        email=os.environ.get("DJANGO_SUPERUSER_EMAIL", ""),
        password=os.environ["DJANGO_SUPERUSER_PASSWORD"],
    )
    print(f"created superuser {u}")
EOF
fi

exec "$@"
