#!/bin/bash
# rebuild + run tests, dump failures
cd /opt/data/halsa
docker compose up -d db >/dev/null 2>&1
sleep 6
docker compose build -q web || exit 1
docker compose run --rm --no-deps web python manage.py test tracker -v 1 > /tmp/halsa-tests.txt 2>&1
echo "exit=$?  $(grep -E '^Ran ' /tmp/halsa-tests.txt)"
grep -A14 -E '^(FAIL|ERROR): ' /tmp/halsa-tests.txt | head -160
