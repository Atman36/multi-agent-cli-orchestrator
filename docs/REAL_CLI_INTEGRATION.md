# Подключение реальных CLI (OpenCode / Claude Code / Codex)

По умолчанию все воркеры работают в **simulation mode** и не запускают внешние процессы.

## 1) Включить real CLI execution

1) Создайте `.env` из `.env.example`:
```bash
cp .env.example .env
```

2) Включите:
```env
ENABLE_REAL_CLI=1
```

3) Настройте allowlist:
```env
ALLOWED_BINARIES=opencode,claude,codex,git
ENV_ALLOWLIST=ANTHROPIC_API_KEY,OPENAI_API_KEY,PATH,HOME,TMPDIR
SENSITIVE_ENV_VARS=ANTHROPIC_API_KEY,OPENAI_API_KEY
```

4) Sandbox (рекомендуется оставить включённым):
```env
SANDBOX=1
SANDBOX_WRAPPER=bwrap
SANDBOX_WRAPPER_ARGS=--unshare-all --die-with-parent --ro-bind /usr /usr --proc /proc --dev /dev --tmpfs /tmp
```

> ВНИМАНИЕ: MVP **откажется** запускать реальные команды, если `SANDBOX=1`, но `SANDBOX_WRAPPER` не задан.

## 2) Где менять команды

- `workers/opencode_worker.py`
- `workers/claude_worker.py`
- `workers/codex_worker.py`

В каждом воркере в методе `run()` есть блок `REAL CLI MODE (TODO...)`.

### OpenCode
Простейший вариант (subprocess):
- `opencode run --format json "<prompt>"`

Production-вариант:
- `opencode serve` + HTTP API (получать diff/patch через API)

### Claude Code
Headless вариант (пример; флаги зависят от версии CLI):
- `claude -p "<prompt>" --allowedTools "Read,Grep,Glob" --output-format json`

**Не включайте** опасные флаги типа “skip permissions” по умолчанию. Вместо этого:
- используйте разрешённые инструменты (allowlist)
- запускайте в sandbox

### Codex
Headless вариант (пример; флаги зависят от версии CLI):
- `codex exec --json "<prompt>"`

## 3) Как получать patch.diff

MVP пока пишет `patch.diff` как:
- пустой (planner/reviewer), или
- симулированный (implementer)

Чтобы сделать правильно:
1) Работайте в git-репо в `workdir`
2) До запуска шага сохраните `git status --porcelain`
3) После шага снимите diff:
   - `git diff` (или `git diff --staged` если агент коммитит)
4) Запишите unified diff в `patch.diff`

Альтернатива: `git format-patch` (если агент делает коммиты).

## 4) Как передавать контекст через артефакты

Стандартный способ:
- шаг 01 создаёт `report.md` (план)
- шаг 02 читает `steps/01_plan/report.md`, создаёт `patch.diff`
- шаг 03 читает `steps/02_implement/patch.diff` + `report.md`, создаёт review `report.md`

В `job.steps[].input_artifacts` указывайте относительные пути внутри `artifacts/<job_id>/`.

Для Claude можно переопределить инструменты прямо в шаге:

```json
{
  "agent": "claude",
  "role": "reviewer",
  "prompt": "Review patch",
  "allowed_tools": ["Read", "Grep", "Glob"]
}
```

## 5) Как подключить API ключи

- Передавайте ключи через **env vars**, а НЕ через аргументы (видно в `ps` (proc list)).
- В этом MVP env vars не “протекают” в артефакты напрямую, но ваш CLI может печатать их в stdout/stderr.
- Если в production: добавьте “санитайзер” логов (redaction).
