# Deployment (single Linux host)

## Components

- `orchestrator-api.service`: webhook API (`gateway.webhook_server`)
- `orchestrator-runner.service`: job execution (`orchestrator.runner`)
- `orchestrator-runner@.service`: runner pool template (`orchestrator.runner`)
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

### Runner pool mode (optional)

If you need parallel workers, use the templated unit:

- `sudo systemctl disable --now orchestrator-runner`
- `sudo systemctl enable --now orchestrator-runner@1 orchestrator-runner@2 orchestrator-runner@3`

Increase/decrease the number of instances based on host CPU and CLI limits.

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

For multi-tenant webhook auth, configure scoped tokens via `WEBHOOK_TOKENS`
(for example `token-a=project1|project2,token-b=*`) and keep `PROJECT_ALIASES`
in sync with allowed project IDs.

## Log rotation

Sample logrotate policy: `deploy/logrotate/orchestrator`

## macOS (launchd)

- Шаблоны launchd: `deploy/launchd/*.plist`
- Автоустановка/перезагрузка сервисов: `scripts/install_launchd.sh`

Пример:

```bash
bash scripts/install_launchd.sh
```
