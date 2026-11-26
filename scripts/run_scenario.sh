#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
LABEL="${1:?uso: run_scenario.sh antes|despues}"
docker compose --profile tools exec tester python scenario.py --label "$LABEL" --baseline 10 --attack 40 --recovery 30 --workers 40
