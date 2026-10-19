import re
import subprocess

env = open("/opt/data/halsa/.env").read()
pw = re.search(r"DJANGO_SUPERUSER_PASSWORD=(\w+)", env).group(1)
user = re.search(r"DJANGO_SUPERUSER_USERNAME=(\w+)", env).group(1)
code = (
    "import os, django; django.setup();"
    "from django.contrib.auth import get_user_model;"
    "U = get_user_model();"
    f"u = U.objects.filter(username='{user}').first();"
    f"u.set_password({pw!r}); u.save();"
    "print('password reset for', u.username)"
)
r = subprocess.run(
    ["docker", "compose", "-f", "/opt/data/halsa/docker-compose.yml",
     "exec", "-T", "-e", "DJANGO_SETTINGS_MODULE=halsa.settings",
     "web", "python", "-c", code],
    capture_output=True, text=True, timeout=120)
print("rc:", r.returncode, "|", (r.stdout.strip() or r.stderr.strip()[-200:]))
