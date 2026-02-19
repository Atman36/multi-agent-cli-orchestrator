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
  # AWS
  'AKIA[0-9A-Z]{16}'
  'ASIA[0-9A-Z]{16}'
  # Private keys
  '-----BEGIN (RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----'
  # API key env vars (explicit names)
  'OPENAI_API_KEY'
  'ANTHROPIC_API_KEY'
  'GOOGLE_API_KEY'
  'AZURE_[A-Z_]*KEY'
  'DATABASE_URL=.+:.+@'
  # Slack tokens
  'xox[baprs]-[0-9A-Za-z-]+'
  # GitHub tokens (PAT, fine-grained, OAuth, app)
  'ghp_[0-9A-Za-z]{36}'
  'github_pat_[0-9A-Za-z_]{22,}'
  'gho_[0-9A-Za-z]{36}'
  'ghs_[0-9A-Za-z]{36}'
  # Google API key
  'AIza[0-9A-Za-z_-]{35}'
  # GitLab tokens
  'glpat-[0-9A-Za-z_-]{20,}'
  # npm tokens
  'npm_[0-9A-Za-z]{36}'
  # Stripe keys
  'sk_live_[0-9A-Za-z]{24,}'
  'rk_live_[0-9A-Za-z]{24,}'
  # Heroku API key
  '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
  # SendGrid
  'SG\.[0-9A-Za-z_-]{22}\.[0-9A-Za-z_-]{43}'
  # Twilio
  'SK[0-9a-f]{32}'
  # Generic secret patterns
  '(api[_-]?key|secret|password|token|passwd|credential)[[:space:]]*[:=][[:space:]]*['\''\""]?[A-Za-z0-9_\-/.+]{8,}'
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
