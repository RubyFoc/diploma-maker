#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

required_files=(
  "AGENTS.md"
  "Academic_Platform_PRD.md"
  "docs/README.md"
  "docs/project/brief.md"
  "docs/architecture/overview.md"
  "docs/architecture/diagrams.md"
  "docs/architecture/decisions.md"
  "docs/engineering/best-practices.md"
  "docs/testing/strategy.md"
  "docs/operations/github-workflow.md"
  ".ai/team/workflow.md"
)

missing=0
for f in "${required_files[@]}"; do
  if [ ! -f "$f" ]; then
    echo "MISSING: $f"
    missing=1
  fi
done

if [ "$missing" -ne 0 ]; then
  echo "Docs structure check failed."
  exit 1
fi

echo "Docs structure check passed."
