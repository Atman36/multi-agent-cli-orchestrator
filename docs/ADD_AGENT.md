# Как добавить нового агента (worker)

## 1) Создайте worker

Например, `workers/gemini_worker.py`:

- наследуйте `BaseWorker`
- реализуйте `run(ctx: StepContext) -> StepResult`
- **обязательно** записывайте файлы:
  - `ctx.step_dir / report.md`
  - `ctx.step_dir / patch.diff`
  - `ctx.step_dir / logs.txt`

Runner сам сохранит `result.json` по контракту.

## 2) Зарегистрируйте worker в реестре

В файле worker зарегистрируйте экземпляр в `workers/registry.py`:

```py
from workers.registry import register_worker

register_worker(GeminiWorker())
```

`runner.py` и `orchestrator/models.py` менять не нужно: реестр подхватит новый агент по имени.

## 3) Добавьте шаги в job

В `steps[]` используйте `agent="gemini"` и `step_id` вроде `04_docs`.

Для Claude-шагов можно задать явный override инструментов:

```json
{
  "step_id": "03_review",
  "agent": "claude",
  "role": "reviewer",
  "prompt": "Review changes",
  "allowed_tools": ["Read", "Grep", "Glob"]
}
```

## 4) Следуйте контрактам

- вход: `contracts/job.schema.json`
- выход: `contracts/result.schema.json`
- артефакты строго фиксированы (имена файлов и каталоги)
