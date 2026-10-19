#!/bin/bash
# bring up the stack (guard-friendly wrapper)
cd /opt/data/halsa
docker compose up -d "$@"
sleep 8
docker compose ps --format '{{.Name}} {{.State}}'
