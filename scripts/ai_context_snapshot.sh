#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

printf '%s\n' '# Git identity'
printf 'branch: '; git branch --show-current
printf 'head: '; git rev-parse --short=12 HEAD
printf '%s\n' '' '# Status'
git status --short --branch
printf '%s\n' '' '# Recent commits'
git log -5 --oneline --decorate

for file in \
  docs/context/SESSION_HANDOFF.md \
  docs/context/CURRENT_STATE.md \
  docs/context/KNOWN_ISSUES.md; do
  if [[ -f "$file" ]]; then
    printf '\n# %s (first 120 lines)\n' "$file"
    sed -n '1,120p' "$file"
  fi
done
