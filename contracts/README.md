# Contracts

## JobSpec (`job.schema.json`)

JobSpec описывает входной контракт для постановки задачи в очередь.

Ключевые поля:
- `job_id`: уникальный id job
- `goal`: цель
- `workdir`: рабочая директория (репо/проект)
- `steps[]`: шаги, каждый шаг запускается отдельным worker-адаптером
- `policy`: sandbox/network/allowlist

## Result (`result.schema.json`)

Result описывает результат выполнения.

`kind`:
- `step` — результат одного шага (`artifacts/<job_id>/steps/<step_id>/result.json`)
- `job`  — агрегированный результат (`artifacts/<job_id>/result.json`), включает `steps[]`

Фиксированные артефакты для каждого шага:
- `report.md`
- `patch.diff`
- `logs.txt`
- `result.json`

Все пути в `artifacts.*` — относительные пути от `artifacts/<job_id>/`.
