# OpenClaw integration (how-to)

Идея: OpenClaw — always-on “front door” (cron/webhook/manual), а этот orchestrator — “job runner” с очередью и артефактами.

## Вариант A: OpenClaw вызывает наш webhook

1) Поднимите orchestrator:
```bash
make dev
```

2) В OpenClaw настройте action/cron, который делает HTTP POST:
- URL: `http://<host>:8080/webhook`
- Headers:
  - `Authorization: Bearer <WEBHOOK_TOKEN>`
  - `Content-Type: application/json`
- Body (пример):
```json
{ "goal": "Run pipeline on repo X", "workdir": "/srv/repo" }
```

## Вариант B: Orchestrator вызывает OpenClaw (callback)

MVP этого не делает, но вы можете добавить:
- `callbacks.on_complete.webhook_url`
- после job completion отправлять `result.json` в OpenClaw

## Что важно

- Подпись webhooks (HMAC) и rate-limits — обязательно для production
- Не давайте OpenClaw “сырой” доступ к запуску опасных команд без sandbox+allowlist
