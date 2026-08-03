#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

echo "Checking backend health..."
curl -sf "http://localhost:${BACKEND_PORT:-8000}/health" >/dev/null && echo "backend: OK" || {
  echo "backend: FAILED"
  exit 1
}

echo "Checking frontend..."
curl -sf "http://localhost:5173" >/dev/null && echo "frontend: OK" || {
  echo "frontend: FAILED"
  exit 1
}

echo "Smoke check passed."
