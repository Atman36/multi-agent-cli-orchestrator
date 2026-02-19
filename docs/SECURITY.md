# Security model (MVP)

Этот репозиторий — оркестратор, который потенциально запускает внешние CLI-агенты.
Это **высокий риск**, особенно если вы обрабатываете untrusted репозитории или webhooks.

## Принципы (закреплено в коде)

1) **Default-deny** на выполнение внешних команд:
   - `ENABLE_REAL_CLI=0` по умолчанию
2) **Allowlist**:
   - `ALLOWED_BINARIES` обязателен для любых subprocess
3) **Sandbox-first**:
   - если `ENABLE_REAL_CLI=1` и `SANDBOX=1`, но wrapper не задан → оркестратор откажется запускать команды
4) **No shell=True**:
   - subprocess запускаются списком аргументов, чтобы не допустить shell injection
5) **Workspace isolation**:
   - каждый job исполняется в `WORKSPACES_ROOT/<job_id>/work`
   - `webhook.workdir` игнорируется; для выбора исходного репо используйте `project_id` + `PROJECT_ALIASES`

## Что sandbox НЕ делает в MVP

MVP не реализует sandbox сам — он только *оборачивает* команду в `SANDBOX_WRAPPER`.
Вы можете использовать:
- `bwrap` (bubblewrap)
- `firejail`
- `docker run --rm ...`

## Рекомендации для production

- Запускать каждый job в отдельном workspace/worktree
- Подключить redaction для логов (секреты, токены)
- Запретить сетевой доступ на уровне sandbox (если возможно)
- Ограничить ресурсы: CPU/RAM/pids/timeout
- Ввести подпись webhooks (GitHub HMAC) + rate-limit + audit log
