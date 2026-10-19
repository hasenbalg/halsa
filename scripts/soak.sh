#!/usr/bin/env bash
# 10h+ soak: loop the full test suite + a production smoke check.
# Usage: nohup bash scripts/soak.sh >/dev/null 2>&1 &
cd "$(dirname "$0")/.."
DURATION=${SOAK_HOURS:-10.5}
END=$(( $(date +%s) + $(python3 -c "print(int(${DURATION}*3600))" 2>/dev/null || echo 37800) ))
i=0
echo "soak start $(date -u +%FT%TZ) until $(date -u -d @${END} +%FT%TZ 2>/dev/null || echo @${END})" >> soak.log
while [ "$(date +%s)" -lt "${END}" ]; do
  i=$((i+1))
  line=$(bash runtests.sh 2>&1 | head -1)
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 \
    "http://localhost:${HALSA_HTTP_PORT:-8000}/accounts/login/" || echo 000)
  echo "$(date -u +%FT%TZ) run=$i ${line} smoke_login=${code}" >> soak.log
  sleep 10
done
echo "$(date -u +%FT%TZ) SOAK COMPLETE runs=$i" >> soak.log
