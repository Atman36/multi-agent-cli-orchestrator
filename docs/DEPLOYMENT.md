# Deployment (single Linux host)

## Components

- `orchestrator-api.service`: webhook API (`gateway.webhook_server`)
- `orchestrator-runner.service`: job execution (`orchestrator.runner`)
- `orchestrator-scheduler.service`: cron schedules (`orchestrator.scheduler`)

Service templates are in `deploy/systemd/`.

## Installation outline

1. Create service user:
   - `sudo useradd --system --create-home --shell /usr/sbin/nologin orchestrator`
2. Place repo in `/opt/multi-agent-cli-orchestrator`
3. Create env file `/etc/multi-agent-orchestrator/orchestrator.env`
4. Copy units:
   - `sudo cp deploy/systemd/*.service /etc/systemd/system/`
   - `sudo systemctl daemon-reload`
   - `sudo systemctl enable --now orchestrator-api orchestrator-runner orchestrator-scheduler`

## Hardening defaults

Each unit uses:

- `NoNewPrivileges=true`
- `ProtectSystem=strict`
- `ProtectHome=true`
- `PrivateTmp=true`
- dedicated service user
- explicit writable paths only

## Reverse proxy

Nginx sample config: `deploy/nginx/orchestrator.conf`

- TLS termination
- request rate limiting for `/webhook`
- `client_max_body_size` limit
- restricted access to `/metrics`

## Log rotation

Sample logrotate policy: `deploy/logrotate/orchestrator`
