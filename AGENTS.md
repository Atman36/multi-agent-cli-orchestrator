<INSTRUCTIONS>
This file adds system instructions for code agents (Codex/Claude Code, etc.) working with this repository.

## General Rules
- Write responses and comments in PRs/commits briefly and to the point, preferably in English.
- Make changes minimal and targeted; don't touch unrelated files.
- Study existing patterns in neighboring modules before making changes.
- Before committing, ensure the `next` version is not lower than `16.0.10`.
</INSTRUCTIONS>

---

# Multi-Agent CLI Orchestrator — Guide for AI Agents

## Project Overview

**Multi-Agent CLI Orchestrator** is an always-on task (jobs) orchestrator for running multiple headless CLI agents (OpenCode / Claude Code / Codex) via a filesystem queue, with fixed artifacts on disk.

**Key Architecture Principles:**
- **Stateless**: all state is stored in the filesystem (`artifacts/`, `var/queue/`), no database
- **Filesystem queue**: queue based on moving files between directories (no Redis)
- **Fixed artifact structure**: strictly defined paths and filenames
- **Simulation mode by default**: no real CLI commands, works "out of the box"

## Technology Stack

- **Language**: Python 3.11+
- **Web Framework**: FastAPI 0.115.6 + uvicorn
- **Data Validation**: Pydantic v2
- **JSON Schema Validation**: jsonschema 4.23.0
- **Scheduler**: croniter (cron-like scheduling)
- **Configuration**: python-dotenv (`.env` file)
- **Testing**: pytest + unittest
- **Environment**: Linux / macOS

## Repository Structure

```
.
├── gateway/                  # FastAPI webhook server
│   └── webhook_server.py     # POST /webhook, GET /jobs/{id}, GET /metrics
├── orchestrator/             # Orchestrator core
│   ├── runner.py             # Main job execution loop
│   ├── scheduler.py          # Cron task scheduler
│   ├── models.py             # Pydantic models: JobSpec, StepSpec, JobResult, StepResult
│   ├── config.py             # Settings — loading configuration from env
│   ├── artifact_store.py     # Filesystem artifact storage (atomic write)
│   ├── policy.py             # ExecutionPolicy — execution policy
│   ├── preflight.py          # Binary version checks
│   ├── workspace.py          # WorkspaceManager — workspace isolation
│   ├── git_utils.py          # Git utilities
│   ├── log_sanitizer.py      # Redacting sensitive data in logs
│   ├── logging_utils.py      # Logging setup
│   ├── validator.py          # JSON schema validation
│   ├── metrics.py            # Prometheus metrics
│   └── retention.py          # Old artifact cleanup
├── workers/                  # CLI agent adapters
│   ├── base.py               # BaseWorker — base class for all workers
│   ├── agent_executor.py     # AgentExecutor — for real CLI
│   ├── opencode_worker.py    # OpenCode agent
│   ├── codex_worker.py       # Codex agent
│   ├── claude_worker.py      # Claude Code agent
│   └── registry.py           # Worker registry (register_worker, get_worker)
├── fsqueue/                  # Filesystem queue
│   └── file_queue.py         # FileQueue — pending/running/done/failed
├── contracts/                # JSON Schema contracts
│   ├── job.schema.json       # Incoming job validation
│   └── result.schema.json    # Result validation
├── examples/                 # Examples
│   ├── jobs/                 # Example job files for CLI
│   └── webhook_payloads/     # Example webhook payloads
├── docs/                     # Documentation
│   ├── SECURITY.md           # Security model
│   ├── DEPLOYMENT.md         # Deployment
│   ├── ADD_AGENT.md          # Adding a new agent
│   └── ...
├── deploy/                   # Deployment templates
│   ├── systemd/              # Service files
│   ├── nginx/                # Nginx config
│   └── logrotate/            # Log rotation settings
├── scripts/                  # Helper scripts
│   ├── dev.sh                # Start all services for development
│   └── webhook_example.sh    # Webhook request example
├── tests/                    # pytest tests
├── cli.py                    # CLI interface (submit, status)
├── Makefile                  # Build and run commands
└── requirements.txt          # Python dependencies
```

## Quick Commands

### Installation and Setup
```bash
make venv && source .venv/bin/activate && make install  # First install
cp .env.example .env                                     # Create config
```

### Running Services
```bash
make dev              # API + runner + scheduler (foreground, Ctrl+C to stop)
make api              # FastAPI webhook server only (port 8080)
make runner           # Job runner only
make scheduler        # Cron scheduler only
```

### Submitting Tasks
```bash
make submit-example   # Submit example via CLI
make webhook-example  # Submit example via webhook
curl -X POST "http://127.0.0.1:8080/webhook" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer dev-token" \
  -d @examples/webhook_payloads/simple.json
```

### CLI
```bash
python -m cli submit <job_file.json>   # Submit job
python -m cli status <job_id>          # Check status
```

### Testing
```bash
pytest tests/                          # All tests
pytest tests/test_file_queue.py        # Single module
```

## Job Execution Architecture

### Default Pipeline (default_pipeline)

```
Job (goal)
├── Step 01_plan      → OpenCode (planner)     → creates plan
├── Step 02_implement → Codex (implementer)    → reads plan, creates patch
└── Step 03_review    → Claude (reviewer)      → reads everything, writes feedback
```

### Job Lifecycle

1. **Enqueue**: job is placed in `var/queue/pending/<job_id>.json`
2. **Claim**: runner atomically moves to `var/queue/running/`
3. **Execution**: sequential execution of steps
4. **Artifacts**: each step writes to `artifacts/<job_id>/steps/<step_id>/`
5. **Complete**: job is moved to `var/queue/done/` or `var/queue/failed/`

## Agent Roles and Boundaries

- `opencode` (planner): forms plan and risks, does not make final conclusions about applied code without artifacts.
- `codex` (implementer): makes minimal changes according to plan, writes patch and logs.
- `claude` (reviewer): reviews result, looks for risks and missing tests.
- Forbidden: performing unauthorized network/system actions, bypassing sandbox/allowlist, writing secrets to artifacts.
- Source of behavioral rules for workers: this file `AGENTS.md`.

### Fixed Artifacts

**For each step** (`artifacts/<job_id>/steps/<step_id>/`):
- `result.json` — structured result (JSON)
- `report.md` — human-readable report
- `patch.diff` — patch (unified diff)
- `logs.txt` — execution logs
- `raw_stdout.txt`, `raw_stderr.txt` — (optional) raw output

**For the entire job** (`artifacts/<job_id>/`):
- `job.json` — normalized JobSpec
- `state.json` — current statuses/attempts
- `result.json` — aggregated result
- `report.md`, `patch.diff`, `logs.txt` — aggregated artifacts

## Configuration (.env)

Key environment variables:

```bash
# Security (important!)
ENABLE_REAL_CLI=0              # Default: simulation (no real CLI)
SANDBOX=1                      # Enable sandbox
ALLOWED_BINARIES=opencode,claude,codex,git,python
ENV_ALLOWLIST=ANTHROPIC_API_KEY,OPENAI_API_KEY,PATH,HOME
SENSITIVE_ENV_VARS=ANTHROPIC_API_KEY,OPENAI_API_KEY

# Paths
QUEUE_ROOT=var/queue
ARTIFACTS_ROOT=artifacts
WORKSPACES_ROOT=workspaces
PROJECT_ALIASES=               # project_id=/absolute/path/to/repo

# Runner
RUNNER_POLL_INTERVAL_SEC=1
RUNNER_MAX_IDLE_SEC=120
RUNNER_RECLAIM_AFTER_SEC=600   # Return "stuck" jobs to pending
RUNNER_MAX_ATTEMPTS_PER_STEP=3

# Webhook
WEBHOOK_TOKEN=dev-token
MAX_WEBHOOK_BODY_BYTES=262144

# Retention
RETENTION_INTERVAL_SEC=300
ARTIFACTS_TTL_SEC=604800       # 7 days
WORKSPACES_TTL_SEC=172800      # 2 days

# Logging
LOG_LEVEL=INFO
LOG_JSON=0
```

## Code Style and Conventions

### Python
- Use `from __future__ import annotations`
- Typing: mandatory typing for public APIs
- Pydantic v2 for all data models
- Pathlib instead of string paths
- Time in UTC ISO format (`datetime.now(timezone.utc).isoformat()`)

### Errors
- Use custom exceptions: `WorkerError`, `QueueEmpty`, `DuplicateJobError`
- In `StepResult`, the `error` field has type `ErrorInfo(code, message, details)`

### Security
- **Never use** `shell=True` in subprocess
- Path traversal check for all paths
- Atomic file writes (via temp file + rename)
- Redacting sensitive data in logs

## Testing

### Testing Strategy
- **Unit tests**: each module is tested in isolation
- **Using tempfile**: tests should not rely on real directories
- **Mocks**: external dependencies are mocked

### Running Tests
```bash
pytest tests/ -v              # Verbose output
pytest tests/test_file_queue.py::FileQueueTests::test_enqueue_rejects_duplicate_job_id  # Single test
```

### Adding New Tests
- Test classes inherit `unittest.TestCase`
- Use `tempfile.TemporaryDirectory()` for isolation
- Method names: `test_<what_we_test>_<condition>()`

## Adding a New Agent (worker)

1. **Create file** `workers/my_agent.py`:
   - Inherit `BaseWorker`
   - Implement `run(ctx: StepContext) -> StepResult`
   - Must write files: `report.md`, `patch.diff`, `logs.txt` to `ctx.step_dir`

2. **Register** in `workers/registry.py`:
   ```python
   from workers.my_agent import MyAgentWorker
   register_worker(MyAgentWorker())
   ```

3. **Use** in job:
   ```json
   {"step_id": "04_docs", "agent": "my_agent", "role": "documenter", "prompt": "..."}
   ```

See `docs/ADD_AGENT.md` for details.

## Security (critically important)

### Default-Deny Principles
1. `ENABLE_REAL_CLI=0` by default — real CLI is not launched
2. `ALLOWED_BINARIES` — allowlist is mandatory
3. `SANDBOX=1` — without sandbox wrapper commands are not launched
4. `shell=True` is forbidden everywhere
5. Workspace isolation — each job in its own directory

### To Enable Real CLI
Must explicitly set:
- `ENABLE_REAL_CLI=1`
- `ALLOWED_BINARIES=...` (list of allowed binaries)
- `MIN_BINARY_VERSIONS=...` (minimum versions)
- `SANDBOX_WRAPPER=bwrap` (or other sandbox)
- `ENV_ALLOWLIST=...` (environment variables to pass)
- `NON_GIT_WORKDIR_STATUS=needs_human|failed`

See `docs/SECURITY.md` for details.

## Before Committing

- Check `git status` and remove unnecessary changes/junk files
- Run relevant tests: `pytest tests/`
- Ensure code follows existing patterns in neighboring modules
- Comments and commit messages — preferably in English, briefly and to the point
