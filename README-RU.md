# Multi-Agent CLI Orchestrator (Linux) — MVP

Always-on оркестратор задач (jobs) для запуска нескольких headless CLI-агентов (OpenCode / Claude Code / Codex) **через файловую очередь**, с **фиксированными артефактами на диске**.

> MVP запускается локально “из коробки”: воркеры **по умолчанию симулируют** выполнение и создают артефакты.
> Подключение реальных CLI-команд — отдельный шаг (см. `docs/REAL_CLI_INTEGRATION.md`).

## Что есть в MVP

- ✅ File queue (без Redis): `var/queue/pending|awaiting_approval|running|done|failed`
- ✅ Webhook server (FastAPI): принимает payload → валидирует → кладёт job в очередь
- ✅ Runner: забирает job из очереди, исполняет шаги, делает retries/timeouts, пишет state
- ✅ Workspace isolation: каждый job выполняется в `workspaces/<job_id>/work`
- ✅ Workers-адаптеры: `opencode_worker`, `claude_worker`, `codex_worker`
  - по умолчанию: **simulation mode** (без внешних зависимостей/ключей)
  - при `ENABLE_REAL_CLI=1`: единый executor, allowlist и preflight версий
- ✅ Контракты:
  - `contracts/job.schema.json`
  - `contracts/result.schema.json`
- ✅ Secrets check артефактов (`scripts/verify_artifacts.sh`) после каждого шага
- ✅ Budget gate (SQLite, дневные лимиты API calls / cost)
- ✅ `/metrics` в формате Prometheus
- ✅ Retention cleanup для `artifacts/` и `workspaces/`
- ✅ Единый каталог артефактов: `artifacts/<job_id>/...`
- ✅ Примеры: `examples/jobs/*` + `examples/webhook_payloads/*`

## Фиксированные пути артефактов (обязательные)

Для **каждого шага** (`artifacts/<job_id>/steps/<step_id>/`) всегда создаются:

- `result.json` — структурированный результат шага (JSON, см. `contracts/result.schema.json`)
- `report.md` — человекочитаемый отчёт
- `patch.diff` — патч (unified diff)
- `logs.txt` — логи выполнения/проверок

Для **job в целом** (`artifacts/<job_id>/`) всегда создаются:

- `job.json` — нормализованный JobSpec (входной контракт)
- `state.json` — текущие статусы/attempts по шагам (операционный state)
- `result.json` — агрегированный результат job (kind=`job`)
- `context.json` — контекстное окно разговора (обновляется после каждого шага)
- `report.md` — агрегированный отчёт
- `patch.diff` — агрегированный патч
- `logs.txt` — агрегированные логи

## Быстрый старт

### 0) Требования
- Linux / macOS
- Python 3.11+

### 1) Установка зависимостей

```bash
make venv
source .venv/bin/activate
make install
```

### 2) Запуск (dev mode): webhook + runner + scheduler

```bash
make dev
```

По умолчанию:
- Webhook API: `http://127.0.0.1:8080`
- Runner + Scheduler запускаются в одном `scripts/dev.sh`

Проверка:
```bash
curl -s http://127.0.0.1:8080/health | jq .
curl -s http://127.0.0.1:8080/metrics
```

### 3) Отправить webhook (создать job)

```bash
make webhook-example
```

Либо вручную:
```bash
curl -X POST "http://127.0.0.1:8080/webhook"   -H "Content-Type: application/json"   -H "Authorization: Bearer dev-token"   -d @examples/webhook_payloads/simple.json
```

Ответ вернёт `job_id`. Артефакты появятся в `./artifacts/<job_id>/...`.

### 4) Ручной запуск (CLI)

```bash
python -m cli submit examples/jobs/simple_job.json
python -m cli status <job_id>
python -m cli doctor
python -m cli recover
python -m cli unlock --job <job_id>
python -m cli approve --job <job_id>
```

## Безопасность (важно)

- Оркестратор **не запускает реальные CLI по умолчанию**.
- Для включения реальных CLI нужно явно выставить:
  - `ENABLE_REAL_CLI=1`
  - (опционально) `MIN_BINARY_VERSIONS=opencode=...,codex=...,claude=...,git=...`
  - настроить allowlist (`ALLOWED_BINARIES=...`)
  - настроить allowlist окружения (`ENV_ALLOWLIST=...`)
  - при необходимости включить жёсткий режим env (`SANDBOX_CLEAR_ENV=1`)
  - настроить лимиты входных артефактов (`MAX_INPUT_ARTIFACTS_FILES`, `MAX_INPUT_ARTIFACT_CHARS`, `MAX_INPUT_ARTIFACTS_CHARS`)
  - настроить sandbox wrapper или отключить sandbox осознанно
  - выбрать поведение для non-git каталога: `NON_GIT_WORKDIR_STATUS=needs_human|failed`

См. подробности: `docs/SECURITY.md`.

## Как добавить нового агента

См. `docs/ADD_AGENT.md`.

## Deployment

См. `docs/DEPLOYMENT.md` и шаблоны в `deploy/`.

## Структура репозитория

```
.
├── gateway/                  # FastAPI webhook server
├── orchestrator/             # runner/scheduler/policy/artifacts
├── workers/                  # adapters for CLI agents (stubbed by default)
├── fsqueue/                 # filesystem queue implementation (Python package)
├── var/queue/                # runtime queue directories (pending/awaiting_approval/running/done/failed)
├── contracts/                # job/result JSON schemas
├── examples/                 # example jobs + webhook payloads
├── docs/                     # integration + security + extension docs
├── scripts/                  # dev scripts
├── artifacts/                # generated (gitignored)
└── workspaces/               # generated (gitignored)
```

## License

MIT (репозиторий-обвязка). Внешние CLI имеют свои лицензии.
