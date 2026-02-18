#!/usr/bin/env bash
# Bootstrap Apache Superset: create admin user, run migrations, initialize.
# Usage: bash scripts/bootstrap_superset.sh

set -euo pipefail

docker compose exec superset superset fab create-admin \
  --username admin --firstname Admin --lastname User \
  --email admin@localhost --password admin

docker compose exec superset superset db upgrade
docker compose exec superset superset init

echo "Superset bootstrapped. Visit http://localhost:8088 (admin/admin)"
