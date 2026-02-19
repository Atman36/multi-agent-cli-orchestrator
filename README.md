# Multi-Agent CLI Orchestrator

> An always-on task orchestrator for running headless CLI agents (OpenCode / Claude Code / Codex) via a filesystem queue, with fixed artifacts on disk.

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-pytest-green.svg)](tests/)

**[🇷🇺 Русская версия](README-RU.md)**

---

## Overview

Multi-Agent CLI Orchestrator coordinates multiple AI coding agents in a sequential pipeline — plan → implement → review — without requiring a database or message broker. All state lives on the filesystem.

**By default, workers run in simulation mode** — no real CLI commands are executed, no API keys are required. This makes it safe to explore and test locally out of the box.

---

## Features

- **Filesystem queue** — no Redis or RabbitMQ; queue is just file moves between `pending/running/done/failed/awaiting_approval/`
- **Webhook API** — `POST /webhook` accepts jobs, validates against JSON Schema, enqueues
- **Sequential pipeline** — default 3-step: `plan → implement → review`
- **Fixed artifact layout** — every step writes `result.json`, `report.md`, `patch.diff`, `logs.txt` to a deterministic path
- **Simulation mode by default** — safe to run without real CLI agents or API keys
- **Real CLI mode** — set `ENABLE_REAL_CLI=1` to execute actual `opencode`/`codex`/`claude` commands
- **Context between steps** — `context_window` / `context_strategy` passed across steps; persisted to `artifacts/<job_id>/context.json`
- **Human-in-the-loop** — `on_failure: ask_human` pauses job → `needs_human` status → `awaiting_approval/` queue
- **LLM API workers** — `APIWorker` base class for direct API integrations (no CLI needed)
- **Workspace isolation** — each job runs in its own `workspaces/<job_id>/work/`
- **Security layers** — env allowlist, binary allowlist, sandbox wrapper, path traversal checks, log redaction
- **Prometheus metrics** — exposed at `GET /metrics`
- **Retention cleanup** — automatic artifact and workspace pruning
- **Budget gate** — daily API call / cost limits via SQLite

---

## Architecture

### Job Execution Pipeline

```
JobSpec (JSON)
├── Step 01_plan      → opencode  (planner)      → plan artifact
├── Step 02_implement → codex     (implementer)   → reads plan → patch
└── Step 03_review    → claude    (reviewer)      → reads all → feedback
```

### Filesystem Queue

No message broker — queue is atomic file moves:

```
var/queue/
├── pending/             ← new jobs land here
├── running/             ← claimed by runner (atomic rename)
├── done/                ← completed jobs
├── failed/              ← failed jobs
└── awaiting_approval/   ← paused jobs (on_failure: ask_human)
```

`reclaim_stale_running()` returns orphaned jobs (>600s in running) back to pending.

### Artifact Layout

```
artifacts/<job_id>/
├── job.json          ← normalized JobSpec (input contract)
├── state.json        ← current step statuses / attempt counts
├── result.json       ← aggregated job result
├── context.json      ← conversation context window (updated after each step)
├── report.md
├── patch.diff
├── logs.txt
└── steps/
    └── <step_id>/
        ├── result.json
        ├── report.md
        ├── patch.diff
        ├── logs.txt
        └── raw_stdout.txt
```

All writes are atomic (write to `.tmp`, then rename). Path traversal is checked on every write.

---

## Quick Start

### Requirements

- Python 3.11+
- Linux or macOS

### 1. Install

```bash
make venv
source .venv/bin/activate
make install
cp .env.example .env
```

### 2. Run (dev mode)

Starts webhook API + runner + scheduler in one command:

```bash
make dev
```

- Webhook API: `http://127.0.0.1:8080`

Verify:

```bash
curl -s http://127.0.0.1:8080/health | jq .
curl -s http://127.0.0.1:8080/metrics
```

### 3. Submit a job

**Via webhook:**

```bash
make webhook-example

# or manually:
curl -X POST "http://127.0.0.1:8080/webhook" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer dev-token" \
  -d @examples/webhook_payloads/simple.json
```

**Via CLI:**

```bash
python -m cli submit examples/jobs/simple_job.json
python -m cli status <job_id>
```

The response contains a `job_id`. Artifacts appear in `./artifacts/<job_id>/`.

### 4. CLI Commands

```bash
python -m cli submit <job_file.json>   # Submit a job
python -m cli status <job_id>          # Check job status
python -m cli doctor                   # Preflight checks
python -m cli recover                  # Recover stale jobs
python -m cli unlock --job <job_id>    # Unlock a stuck job
python -m cli approve --job <job_id>   # Approve a job awaiting human review
```

---

## Configuration

Copy `.env.example` to `.env` and adjust as needed.

| Variable | Default | Description |
|---|---|---|
| `ENABLE_REAL_CLI` | `0` | `1` to execute real CLI agents |
| `WEBHOOK_TOKEN` | `dev-token` | Bearer token for `POST /webhook` |
| `WEBHOOK_TOKENS` | *(empty)* | Optional token map (`token=project1|project2`, `*` for all projects) |
| `WEBHOOK_RATE_LIMIT_WINDOW_SEC` | `60` | Webhook rate-limit window (seconds) |
| `WEBHOOK_RATE_LIMIT_MAX_REQUESTS` | `30` | Max requests per `(token, client_ip)` within window (`0` disables) |
| `QUEUE_ROOT` | `var/queue` | Filesystem queue root |
| `ARTIFACTS_ROOT` | `artifacts` | Artifacts root |
| `WORKSPACES_ROOT` | `workspaces` | Job workspace root |
| `PROJECT_ALIASES` | *(empty)* | Maps `project_id` → absolute repo path |
| `DEFAULT_ARTIFACT_HANDOFF` | `manual` | Default handoff mode (`manual`, `patch_first`, `workspace_first`) for webhook-created jobs |
| `ALLOWED_BINARIES` | `opencode,claude,codex,git,python` | Subprocess allowlist |
| `ENV_ALLOWLIST` | `ANTHROPIC_API_KEY,OPENAI_API_KEY,PATH,HOME` | Env vars passed to subprocesses |
| `RUNNER_MAX_ATTEMPTS_PER_STEP` | `3` | Retry limit per step |
| `ARTIFACTS_TTL_SEC` | `604800` | Artifact retention (7 days) |
| `LOG_LEVEL` | `INFO` | Logging level |

See `.env.example` for the full list.

---

## Security

The orchestrator **does not execute real CLI commands by default** (`ENABLE_REAL_CLI=0`).

To enable real CLI execution, you must explicitly configure:

```bash
ENABLE_REAL_CLI=1
ALLOWED_BINARIES=opencode,claude,codex,git,python   # allowlist
MIN_BINARY_VERSIONS=opencode=0.1.0,codex=1.0.0      # min versions
SANDBOX=1
SANDBOX_WRAPPER=bwrap                                # bwrap / firejail / docker
ENV_ALLOWLIST=ANTHROPIC_API_KEY,OPENAI_API_KEY,PATH,HOME
NON_GIT_WORKDIR_STATUS=needs_human                   # or: failed
```

Security layers:
1. **Subprocess allowlist** — only `ALLOWED_BINARIES` can be launched
2. **Env hygiene** — only `ENV_ALLOWLIST` vars reach subprocesses; `SENSITIVE_ENV_VARS` are redacted from logs
3. **No `shell=True`** — all subprocesses use argument lists (no shell injection)
4. **Workspace isolation** — each job is confined to its own directory
5. **Atomic writes** — artifacts written via temp-file + rename
6. **Path traversal check** — all artifact paths validated against `artifacts/<job_id>/`

See [`docs/SECURITY.md`](docs/SECURITY.md) for full details.

---

## Extending: Adding a New Agent

1. Create `workers/my_agent.py` extending `BaseWorker`, implement `run(ctx) -> StepResult`
2. Register in `workers/registry.py`
3. Use `"agent": "my_agent"` in your job spec

See [`docs/ADD_AGENT.md`](docs/ADD_AGENT.md) for a step-by-step guide.

---

## Repository Structure

```
.
├── gateway/           # FastAPI webhook server (POST /webhook, GET /metrics)
├── orchestrator/      # Runner, scheduler, models, config, artifact store
├── workers/           # CLI agent adapters (simulation by default)
├── fsqueue/           # Filesystem queue implementation
├── contracts/         # JSON Schema contracts (job + result)
├── examples/          # Example jobs and webhook payloads
├── docs/              # Security, deployment, extension guides
├── deploy/            # systemd units, nginx config, logrotate
├── scripts/           # Dev helper scripts
├── tests/             # pytest test suite
├── cli.py             # CLI entrypoint
├── Makefile           # Common commands
└── requirements.txt   # Python dependencies
```

---

## Running Tests

```bash
python3 -m unittest discover -s tests    # All tests
python3 -m unittest tests.test_file_queue  # Single module
```

---

## Deployment

Systemd service templates, nginx config, and logrotate config are in `deploy/`.

See [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) for the full installation guide.

---

## License

MIT. External CLI tools (opencode, codex, claude) are governed by their own licenses.
