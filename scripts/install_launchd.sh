#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LAUNCHD_DIR="$HOME/Library/LaunchAgents"
mkdir -p "$LAUNCHD_DIR"
mkdir -p "$ROOT_DIR/var/logs"

install_one() {
  local src="$1"
  local dst="$LAUNCHD_DIR/$(basename "$src")"
  sed "s|__PROJECT_ROOT__|$ROOT_DIR|g" "$src" > "$dst"

  local label
  label=$(/usr/libexec/PlistBuddy -c 'Print :Label' "$dst")

  launchctl bootout "gui/$(id -u)/$label" >/dev/null 2>&1 || true
  launchctl bootstrap "gui/$(id -u)" "$dst"
  launchctl enable "gui/$(id -u)/$label"
  launchctl kickstart -k "gui/$(id -u)/$label"

  echo "installed: $label"
}

install_one "$ROOT_DIR/deploy/launchd/com.user.multi-agent-orchestrator.runner.plist"
install_one "$ROOT_DIR/deploy/launchd/com.user.multi-agent-orchestrator.scheduler.plist"

echo "launchd services are active"
