#!/usr/bin/env bash
# Secrets audit (P10-6): fail if likely secrets are tracked by git.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "Checking tracked files for secrets..."
BAD=0

if git ls-files --error-unmatch .env >/dev/null 2>&1; then
  echo "FAIL: .env is tracked"
  BAD=1
fi

# Patterns that should never appear in tracked files.
while IFS= read -r file; do
  [[ "$file" == scripts/audit_secrets.sh ]] && continue
  if grep -nE '(API_KEY|SECRET_KEY|BEGIN RSA PRIVATE KEY|sk-[a-zA-Z0-9]{20,}|xox[baprs]-)' "$file" >/dev/null 2>&1; then
    echo "FAIL: suspicious secret-like pattern in $file"
    BAD=1
  fi
done < <(git ls-files)

if [[ $BAD -ne 0 ]]; then
  echo "Secrets audit failed."
  exit 1
fi
echo "Secrets audit passed."
