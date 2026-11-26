#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
MODO="${1:-vulnerable}"

docker compose --profile tools -f docker-compose.yml -f docker-compose.hardened.yml down -v 2>/dev/null || true

if [ "$MODO" = "hardened" ]; then
  docker compose --profile tools -f docker-compose.yml -f docker-compose.hardened.yml up -d --build
else
  docker compose --profile tools -f docker-compose.yml up -d --build
fi

echo "Modo '$MODO' listo. Gateway: http://localhost:8080/health"
