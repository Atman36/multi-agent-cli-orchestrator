# CLAUDE.md

Системная документация репозитория: команды, соглашения и архитектурные заметки для работы ассистентов (Claude Code/Codex и т.п.) в этом проекте.

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Setup
make venv && source .venv/bin/activate && make install

# Run all services (api + runner + scheduler)
make dev

# Run services individually
make api          # FastAPI webhook server on port 8080
make runner       # Job runner (polls queue)
make scheduler    # Cron scheduler

# Tests
python3 -m unittest discover -s tests  # All tests (pytest not installed)
python3 -m unittest tests.test_file_queue  # Single module

# Submit jobs
make submit-example                    # CLI submit
make webhook-example                   # HTTP webhook
python -m cli submit <job_file.json>   # Direct CLI
python -m cli status <job_id>          # Check status
```

## Architecture

### Job Execution Pipeline

Jobs are sequential **steps** submitted as a `JobSpec` (JSON). The default 3-step pipeline is:
1. **01_plan** → OpenCode (planner role) → creates plan artifact
2. **02_implement** → Codex (implementer role) → reads plan, produces patch
3. **03_review** → Claude (reviewer role) → reads all artifacts, writes feedback

The runner processes one job at a time from the filesystem queue. Each step writes standardized artifacts (`report.md`, `patch.diff`, `logs.txt`, `result.json`) to `artifacts/<job_id>/steps/<step_id>/`. The runner reads these after each step completes.

### Filesystem Queue (`fsqueue/`)

No message broker — queue is file moves between directories:
```
var/queue/pending/ → running/ → done/ | failed/ | awaiting_approval/
```
`claim()` uses atomic rename. `reclaim_stale_running()` returns orphaned jobs (>600s in running) to pending.

### Worker Pattern (`workers/`)

All agents inherit `BaseWorker` → `AgentExecutor`. Two execution modes:
- **Simulation** (`ENABLE_REAL_CLI=0`, default): Workers return canned responses — no real CLI executed. Use for development/testing.
- **Real CLI** (`ENABLE_REAL_CLI=1`): Executes actual `opencode`/`codex`/`claude` commands. Requires preflight version checks (`orchestrator/preflight.py`).

Add new agents: create `workers/my_agent.py` extending `BaseWorker`, register in `workers/registry.py`. See `docs/ADD_AGENT.md`.
For LLM API workers (no CLI): extend `APIWorker` (`workers/api_worker.py`) and implement `call_api(prompt, context)`.

### Artifact Store (`orchestrator/artifact_store.py`)

All writes are atomic (write to `.tmp` then rename). Path traversal is checked — paths must stay within `artifacts/<job_id>/`. The `artifacts/` layout is fixed:
```
artifacts/<job_id>/
├── job.json, state.json, result.json, report.md, patch.diff, logs.txt, context.json
└── steps/<step_id>/result.json, report.md, patch.diff, logs.txt, raw_stdout.txt
```

### Configuration (`orchestrator/config.py`)

Settings loaded from `.env` (see `.env.example`). Key variables:
- `ENABLE_REAL_CLI` — toggle simulation vs. real execution
- `QUEUE_ROOT`, `ARTIFACTS_ROOT`, `WORKSPACES_ROOT` — storage paths
- `WEBHOOK_TOKEN` — Bearer token for `POST /webhook`
- `ENV_ALLOWLIST` — env vars passed to subprocesses (principle of least privilege)
- `PROJECT_ALIASES` — maps `project_id` strings to absolute repo paths
- `SANDBOX`, `NETWORK_POLICY`, `ALLOWED_BINARIES` — security policy defaults

### Security Layers

1. **Per-job policy** (`policy.py`): `sandbox`, `network`, `allowed_binaries` from `JobSpec.policy`
2. **Env hygiene** (`config.py`): Only `ENV_ALLOWLIST` vars reach subprocesses; `SENSITIVE_ENV_VARS` are redacted from logs (`log_sanitizer.py`)
3. **Input limits**: `MAX_INPUT_ARTIFACTS_FILES`, `MAX_INPUT_ARTIFACT_CHARS`, `MAX_WEBHOOK_BODY_BYTES`

### Gateway (`gateway/webhook_server.py`)

FastAPI endpoints:
- `POST /webhook` — submit job (validated against `contracts/job.schema.json`)
- `GET /jobs/{job_id}` — read `artifacts/<job_id>/result.json`
- `GET /metrics` — Prometheus metrics

### Data Models (`orchestrator/models.py`)

`JobSpec` → contains list of `StepSpec` → runner produces `StepResult` per step → aggregated into `JobResult`. All validated with Pydantic v2. JSON schemas in `contracts/` are used for webhook input validation.
- `JobSpec.context_window` / `context_strategy` — conversation history shared across steps; persisted to `artifacts/<job_id>/context.json` after each step.
- `StepSpec.on_failure` — supports `stop` | `continue` | `ask_human` | `goto:<step_id>`. `ask_human` → status `needs_human` → job moves to `awaiting_approval/` queue.

## Key Design Decisions

- **Stateless runner**: All state lives in `artifacts/` and `var/queue/`. Multiple runners can share a queue directory for horizontal scaling.
- **Fixed artifact layout**: Workers must write `report.md`, `patch.diff`, `logs.txt` to `ctx.step_dir`. Runner does not inspect worker internals.
- **No database**: Filesystem is the only persistence layer. This is intentional for the MVP.
- `NON_GIT_WORKDIR_STATUS` controls behavior when `workdir` is not a git repo (`needs_human` or `failed`).
