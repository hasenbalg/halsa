import re
import subprocess

new = None
for line in open("/opt/data/halsa/.env"):
    m = re.match(r"POSTGRES_PASSWORD=(.*)", line.strip())
    if m:
        new = m.group(1)
assert new and len(new) == 32

# escape single quotes for SQL literal
sql = "ALTER USER halsa WITH PASSWORD (%s);"
# use psql variable to avoid quoting issues entirely
cmd = ["docker", "compose", "-f", "/opt/data/halsa/docker-compose.yml",
       "exec", "-T", "db", "psql", "-U", "halsa", "-d", "postgres",
       "-v", f"pw={new}", "-c", "ALTER USER halsa WITH PASSWORD :'pw';"]
r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
print("rc:", r.returncode, "out:", r.stdout.strip(), "err:", r.stderr.strip()[:200])
