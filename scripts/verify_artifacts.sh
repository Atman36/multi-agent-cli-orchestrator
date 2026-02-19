#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "usage: $0 <step_dir>" >&2
  exit 2
fi

STEP_DIR="$1"
if [ ! -d "$STEP_DIR" ]; then
  echo "step_dir does not exist: $STEP_DIR" >&2
  exit 2
fi

# Potentially dangerous filenames should never appear in published artifacts.
if find "$STEP_DIR" -type f \( -name '.env' -o -name '.env.*' -o -name '*.key' -o -name '*credentials*' -o -name '*secret*' \) | grep -q .; then
  echo "suspicious file name detected in artifacts"
  find "$STEP_DIR" -type f \( -name '.env' -o -name '.env.*' -o -name '*.key' -o -name '*credentials*' -o -name '*secret*' \) | sed 's/^/ - /'
  exit 1
fi

PATTERNS=(
  'AKIA[0-9A-Z]{16}'
  'ASIA[0-9A-Z]{16}'
  '-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----'
  'OPENAI_API_KEY'
  'ANTHROPIC_API_KEY'
  'xox[baprs]-[0-9A-Za-z-]+'
  'ghp_[0-9A-Za-z]{36}'
  'AIza[0-9A-Za-z_-]{35}'
  '(api[_-]?key|secret|password|token)[[:space:]]*[:=][[:space:]]*[A-Za-z0-9_\-]{8,}'
)

SCAN_FILES=$(find "$STEP_DIR" -type f | sort)
if [ -z "$SCAN_FILES" ]; then
  echo "no artifact files to scan"
  exit 0
fi

TMP_HITS="$(mktemp)"
trap 'rm -f "$TMP_HITS"' EXIT

for pattern in "${PATTERNS[@]}"; do
  if grep -R -n -I -E -- "$pattern" "$STEP_DIR" >"$TMP_HITS" 2>/dev/null; then
    echo "possible secret found (pattern: $pattern)"
    sed 's/^/ - /' "$TMP_HITS" | head -n 20
    exit 1
  fi
done

echo "secrets check passed"
exit 0
