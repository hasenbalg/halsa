#!/usr/bin/env bash
# Ladder: grow the load DB and re-measure at each user count.
# Usage: scripts/ladder.sh 100 200      (user counts to reach)
# Results are copied to the host after every phase (survives container loss).
set -x
cd /opt/data/halsa
docker cp scripts/loadsim.py halsa-load:/app/scripts/loadsim.py
pull() { docker cp halsa-load:/tmp/loadsim-results.jsonl loadsim-results.jsonl 2>/dev/null; }
for N in "$@"; do
  docker exec halsa-load python scripts/loadsim.py seed --users "$N"; pull
  docker exec halsa-load python scripts/loadsim.py pages --users "$N"; pull
  docker exec halsa-load python scripts/loadsim.py week --users "$N"; pull
  docker exec halsa-load python scripts/loadsim.py stats; pull
done
docker exec halsa-load python scripts/loadsim.py queries --users "${@: -1}"
pull
echo LADDER_DONE
