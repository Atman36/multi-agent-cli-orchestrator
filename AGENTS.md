<INSTRUCTIONS>
Этот файл добавляет системные инструкции для код-агентов (Codex/Claude Code и т.п.) при работе с этим репозиторием.

## Общие правила
- Пиши ответы и комментарии в PR/коммитах кратко и по делу, по возможности на русском.
- Делай изменения минимальными и точечными; не трогай несвязанные файлы.
- Перед изменениями изучай существующие паттерны в соседних модулях.
- Перед коммитом проверяй, что версия `next` не ниже `16.0.10`.
</INSTRUCTIONS>

---

# Multi-Agent CLI Orchestrator — Руководство для AI-агентов

## Обзор проекта

**Multi-Agent CLI Orchestrator** — это always-on оркестратор задач (jobs) для запуска нескольких headless CLI-агентов (OpenCode / Claude Code / Codex) через файловую очередь, с фиксированными артефактами на диске.

**Ключевые принципы архитектуры:**
- **Stateless**: всё состояние хранится в файловой системе (`artifacts/`, `var/queue/`), нет базы данных
- **Filesystem queue**: очередь на основе перемещения файлов между директориями (без Redis)
- **Фиксированная структура артефактов**: строго определённые пути и имена файлов
- **Simulation mode по умолчанию**: без реальных CLI-команд, работает "из коробки"

## Технологический стек

- **Язык**: Python 3.11+
- **Веб-фреймворк**: FastAPI 0.115.6 + uvicorn
- **Валидация данных**: Pydantic v2
- **Валидация JSON Schema**: jsonschema 4.23.0
- **Планировщик**: croniter (cron-like scheduling)
- **Конфигурация**: python-dotenv (`.env` файл)
- **Тестирование**: pytest + unittest
- **Среда**: Linux / macOS

## Структура репозитория

```
.
├── gateway/                  # FastAPI webhook server
│   └── webhook_server.py     # POST /webhook, GET /jobs/{id}, GET /metrics
├── orchestrator/             # Ядро оркестратора
│   ├── runner.py             # Главный цикл выполнения job
│   ├── scheduler.py          # Cron-планировщик задач
│   ├── models.py             # Pydantic-модели: JobSpec, StepSpec, JobResult, StepResult
│   ├── config.py             # Settings — загрузка конфигурации из env
│   ├── artifact_store.py     # Файловое хранилище артефактов (атомарная запись)
│   ├── policy.py             # ExecutionPolicy — политика выполнения
│   ├── preflight.py          # Проверка версий бинарников
│   ├── workspace.py          # WorkspaceManager — изоляция рабочих директорий
│   ├── git_utils.py          # Утилиты для работы с git
│   ├── log_sanitizer.py      # Редактирование чувствительных данных в логах
│   ├── logging_utils.py      # Настройка логирования
│   ├── validator.py          # Валидация JSON по схемам
│   ├── metrics.py            # Prometheus-метрики
│   └── retention.py          # Очистка старых артефактов
├── workers/                  # Адаптеры CLI-агентов
│   ├── base.py               # BaseWorker — базовый класс для всех воркеров
│   ├── agent_executor.py     # AgentExecutor — для реальных CLI
│   ├── opencode_worker.py    # OpenCode агент
│   ├── codex_worker.py       # Codex агент
│   ├── claude_worker.py      # Claude Code агент
│   └── registry.py           # Реестр воркеров (register_worker, get_worker)
├── fsqueue/                  # Файловая очередь
│   └── file_queue.py         # FileQueue — pending/running/done/failed
├── contracts/                # JSON Schema контракты
│   ├── job.schema.json       # Валидация входящих job
│   └── result.schema.json    # Валидация результата
├── examples/                 # Примеры
│   ├── jobs/                 # Примеры job-файлов для CLI
│   └── webhook_payloads/     # Примеры payload для webhook
├── docs/                     # Документация
│   ├── SECURITY.md           # Модель безопасности
│   ├── DEPLOYMENT.md         # Развёртывание
│   ├── ADD_AGENT.md          # Добавление нового агента
│   └── ...
├── deploy/                   # Шаблоны для деплоя
│   ├── systemd/              # Service-файлы
│   ├── nginx/                # Конфиг nginx
│   └── logrotate/            # Настройка ротации логов
├── scripts/                  # Вспомогательные скрипты
│   ├── dev.sh                # Запуск всех сервисов для разработки
│   └── webhook_example.sh    # Пример webhook-запроса
├── tests/                    # Тесты pytest
├── cli.py                    # CLI-интерфейс (submit, status)
├── Makefile                  # Команды сборки и запуска
└── requirements.txt          # Python-зависимости
```

## Быстрые команды

### Установка и настройка
```bash
make venv && source .venv/bin/activate && make install  # Первая установка
cp .env.example .env                                     # Создать конфиг
```

### Запуск сервисов
```bash
make dev              # API + runner + scheduler (foreground, Ctrl+C для остановки)
make api              # Только FastAPI webhook server (порт 8080)
make runner           # Только job runner
make scheduler        # Только cron-шедулер
```

### Отправка задач
```bash
make submit-example   # Отправить пример через CLI
make webhook-example  # Отправить пример через webhook
curl -X POST "http://127.0.0.1:8080/webhook" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer dev-token" \
  -d @examples/webhook_payloads/simple.json
```

### CLI
```bash
python -m cli submit <job_file.json>   # Отправить job
python -m cli status <job_id>          # Проверить статус
```

### Тестирование
```bash
pytest tests/                          # Все тесты
pytest tests/test_file_queue.py        # Один модуль
```

## Архитектура выполнения job

### Pipeline по умолчанию (default_pipeline)

```
Job (goal)
├── Step 01_plan      → OpenCode (planner)     → создаёт план
├── Step 02_implement → Codex (implementer)    → читает план, создаёт патч
└── Step 03_review    → Claude (reviewer)      → читает всё, пишет feedback
```

### Жизненный цикл job

1. **Enqueue**: job попадает в `var/queue/pending/<job_id>.json`
2. **Claim**: runner атомарно перемещает в `var/queue/running/`
3. **Execution**: последовательное выполнение steps
4. **Artifacts**: каждый step пишет в `artifacts/<job_id>/steps/<step_id>/`
5. **Complete**: job перемещается в `var/queue/done/` или `var/queue/failed/`

## Роли и границы агентов

- `opencode` (planner): формирует план и риски, не делает финальные выводы о применённом коде без артефактов.
- `codex` (implementer): вносит минимальные изменения по плану, пишет патч и логи.
- `claude` (reviewer): проводит review результата, ищет риски и пропуски тестов.
- Запрещено: выполнять несанкционированные сетевые/системные действия, обходить sandbox/allowlist, писать секреты в артефакты.
- Источник поведенческих правил для воркеров: этот файл `AGENTS.md`.

### Фиксированные артефакты

**Для каждого шага** (`artifacts/<job_id>/steps/<step_id>/`):
- `result.json` — структурированный результат (JSON)
- `report.md` — человекочитаемый отчёт
- `patch.diff` — патч (unified diff)
- `logs.txt` — логи выполнения
- `raw_stdout.txt`, `raw_stderr.txt` — (опционально) сырый вывод

**Для job целиком** (`artifacts/<job_id>/`):
- `job.json` — нормализованный JobSpec
- `state.json` — текущие статусы/попытки
- `result.json` — агрегированный результат
- `report.md`, `patch.diff`, `logs.txt` — агрегированные артефакты

## Конфигурация (.env)

Ключевые переменные окружения:

```bash
# Безопасность (важно!)
ENABLE_REAL_CLI=0              # По умолчанию: симуляция (без реальных CLI)
SANDBOX=1                      # Включить sandbox
ALLOWED_BINARIES=opencode,claude,codex,git,python
ENV_ALLOWLIST=ANTHROPIC_API_KEY,OPENAI_API_KEY,PATH,HOME
SENSITIVE_ENV_VARS=ANTHROPIC_API_KEY,OPENAI_API_KEY

# Пути
QUEUE_ROOT=var/queue
ARTIFACTS_ROOT=artifacts
WORKSPACES_ROOT=workspaces
PROJECT_ALIASES=               # project_id=/absolute/path/to/repo

# Runner
RUNNER_POLL_INTERVAL_SEC=1
RUNNER_MAX_IDLE_SEC=120
RUNNER_RECLAIM_AFTER_SEC=600   # Возврат "зависших" job в pending
RUNNER_MAX_ATTEMPTS_PER_STEP=3

# Webhook
WEBHOOK_TOKEN=dev-token
MAX_WEBHOOK_BODY_BYTES=262144

# Retention
RETENTION_INTERVAL_SEC=300
ARTIFACTS_TTL_SEC=604800       # 7 дней
WORKSPACES_TTL_SEC=172800      # 2 дня

# Логирование
LOG_LEVEL=INFO
LOG_JSON=0
```

## Код-стайл и соглашения

### Python
- Использовать `from __future__ import annotations`
- Типизация: обязательная типизация для публичных API
- Pydantic v2 для всех моделей данных
- Pathlib вместо строковых путей
- Время в UTC ISO формате (`datetime.now(timezone.utc).isoformat()`)

### Ошибки
- Пользовать кастомные исключения: `WorkerError`, `QueueEmpty`, `DuplicateJobError`
- В `StepResult` поле `error` имеет тип `ErrorInfo(code, message, details)`

### Безопасность
- **Никогда не использовать** `shell=True` в subprocess
- Проверка path traversal для всех путей
- Atomарная запись файлов (через временный файл + rename)
- Редактирование чувствительных данных в логах

## Тестирование

### Стратегия тестирования
- **Unit-тесты**: каждый модуль тестируется изолированно
- **Использование tempfile**: тесты не должны полагаться на реальные директории
- **Моки**: внешние зависимости мокаются

### Запуск тестов
```bash
pytest tests/ -v              # Подробный вывод
pytest tests/test_file_queue.py::FileQueueTests::test_enqueue_rejects_duplicate_job_id  # Один тест
```

### Добавление новых тестов
- Тестовые классы наследуют `unittest.TestCase`
- Использовать `tempfile.TemporaryDirectory()` для изоляции
- Имена методов: `test_<что_тестируем>_<условие>()`

## Добавление нового агента (worker)

1. **Создать файл** `workers/my_agent.py`:
   - Наследовать `BaseWorker`
   - Реализовать `run(ctx: StepContext) -> StepResult`
   - Обязательно писать файлы: `report.md`, `patch.diff`, `logs.txt` в `ctx.step_dir`

2. **Зарегистрировать** в `workers/registry.py`:
   ```python
   from workers.my_agent import MyAgentWorker
   register_worker(MyAgentWorker())
   ```

3. **Использовать** в job:
   ```json
   {"step_id": "04_docs", "agent": "my_agent", "role": "documenter", "prompt": "..."}
   ```

Подробнее см. `docs/ADD_AGENT.md`.

## Безопасность (критически важно)

### Принципы default-deny
1. `ENABLE_REAL_CLI=0` по умолчанию — реальные CLI не запускаются
2. `ALLOWED_BINARIES` — allowlist обязателен
3. `SANDBOX=1` — без sandbox wrapper команды не запускаются
4. `shell=True` запрещён везде
5. Workspace isolation — каждый job в своей директории

### Для включения реальных CLI
Необходимо явно выставить:
- `ENABLE_REAL_CLI=1`
- `ALLOWED_BINARIES=...` (список разрешённых бинарников)
- `MIN_BINARY_VERSIONS=...` (минимальные версии)
- `SANDBOX_WRAPPER=bwrap` (или другой sandbox)
- `ENV_ALLOWLIST=...` (переменные окружения для передачи)
- `NON_GIT_WORKDIR_STATUS=needs_human|failed`

Подробнее см. `docs/SECURITY.md`.

## Перед коммитом

- Проверь `git status` и убери лишние изменения/мусорные файлы
- Запусти релевантные тесты: `pytest tests/`
- Убедись, что код следует существующим паттернам в соседних модулях
- Комментарии и commit messages — по возможности на русском, кратко и по делу
