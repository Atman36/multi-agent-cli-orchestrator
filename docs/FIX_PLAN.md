# FIX_PLAN.md — Architectural Review & Improvement Plan

> Reviewed: 2026-02-19
> Reviewer role: LLM orchestration systems architect
> Scope: full codebase audit — can Claude Code operate as a managed agent here?

---

## Verdict

**Yes** — the architecture is solid for an MVP orchestrator. The pipeline model (plan → implement → review), filesystem queue, atomic artifacts, and policy-based security are well-designed. Claude Code can be launched and managed as a worker agent. However, there are issues that limit production readiness and flexibility.

---

## P0 — Critical (blocks real CLI usage)

### 1. Claude worker hardcoded to read-only tools

**File:** `workers/claude_worker.py:19-32`

`_claude_allowed_tools()` silently overrides any `allowed_tools` from StepSpec if they include write tools. Even when the job spec explicitly grants `Edit` or `Write`, the worker forces `["Read", "Grep", "Glob"]`.

```python
# Current: always falls back to read-only
def _claude_allowed_tools(ctx: StepContext) -> list[str]:
    readonly = {"Read", "Grep", "Glob"}
    requested = ctx.step.allowed_tools or _default_allowed_tools(ctx.step.role)
    if set(requested).issubset(readonly):
        return requested
    return ["Read", "Grep", "Glob"]  # <-- override!
```

**Impact:** Claude cannot be used as implementer or any role that requires writing code. This defeats the purpose of a multi-agent orchestrator.

**Fix:** Respect `allowed_tools` from StepSpec when explicitly provided. Add a configurable allowlist per role instead of a hardcoded override.

```python
CLAUDE_SAFE_TOOLS = {"Read", "Grep", "Glob", "Edit", "Write", "Bash"}

def _claude_allowed_tools(ctx: StepContext) -> list[str]:
    if ctx.step.allowed_tools:
        # Job spec explicitly declares tools — respect it
        unknown = set(ctx.step.allowed_tools) - CLAUDE_SAFE_TOOLS
        if unknown:
            log.warning("Unknown tools requested: %s", unknown)
        return ctx.step.allowed_tools
    return _default_allowed_tools(ctx.step.role)
```

---

### 2. FileQueue glob pattern matches prefix collisions

**File:** `fsqueue/file_queue.py:50,144-145`

`_job_exists_anywhere()` and `_find_job_file()` use `folder.glob(f"{job_id}*.json")`. If job IDs share prefixes (e.g., `job-1` and `job-123`), the glob `job-1*.json` matches both.

**Impact:** Duplicate detection may block valid jobs. `approve()` and `unlock()` may operate on wrong job.

**Fix:** Use exact match pattern `f"{job_id}.json"` or `f"{job_id}.*.json"` (for collision-suffixed files):

```python
def _find_job_files(self, folder: Path, job_id: str) -> list[Path]:
    exact = folder / f"{job_id}.json"
    results = [exact] if exact.exists() else []
    # Also find collision-suffixed variants: {job_id}.{ns}.json
    results.extend(folder.glob(f"{job_id}.*.json"))
    return sorted(results, key=lambda p: p.stat().st_mtime)
```

---

### 3. Network policy is declared but never enforced

**File:** `orchestrator/policy.py`

`ExecutionPolicy` stores `network_policy` field but has zero enforcement code. The comment says "enforced via sandbox wrapper" — but if no sandbox wrapper is configured (MVP default), network access is unrestricted.

**Impact:** Agents with `network: "deny"` can still make HTTP requests.

**Fix (short-term):** Log a WARNING at startup if `network_policy != "allow"` and no sandbox wrapper is configured. Refuse to run real CLI jobs with `network: "deny"` unless a wrapper is present.

**Fix (long-term):** Add native network restriction via `unshare --net` on Linux or a lightweight firejail profile.

---

## P1 — High (correctness & security)

### 4. Scheduler cron state is in-memory only

**File:** `orchestrator/scheduler.py`

`CronScheduler.next_runs` is a plain dict — lost on restart. After restart, all schedules re-fire immediately if their `next_run` time has passed.

**Impact:** Duplicate job execution after scheduler restart.

**Fix:** Persist `next_runs` to a JSON file (`var/scheduler_state.json`). Load on startup, write atomically after each tick.

---

### 5. No retry limit tracking across reclaims

**Files:** `orchestrator/runner.py`, `fsqueue/file_queue.py`

When `reclaim_stale_running()` returns a stuck job to `pending`, there's no counter. A fundamentally broken job (e.g., segfault in agent binary) will reclaim → run → crash → reclaim indefinitely.

**Impact:** Infinite retry loop consuming resources.

**Fix:** Track `attempt_count` in the job JSON. Increment on each claim. After `MAX_RECLAIM_ATTEMPTS` (e.g., 3), move to `failed/` instead of `pending/`.

---

### 6. Budget race condition between multiple runners

**File:** `orchestrator/budget.py`

`check_budget()` reads aggregate, then `log_budget()` writes. Two runners can both pass the check before either writes, exceeding limits.

**Impact:** Budget overshoot proportional to runner count.

**Fix:** Use SQLite `BEGIN IMMEDIATE` transaction for check+write atomically:

```python
def check_and_log(self, worker: str, api_calls: int, cost_usd: float) -> None:
    with self._conn:
        self._conn.execute("BEGIN IMMEDIATE")
        snapshot = self._today_snapshot()
        if snapshot.api_calls + api_calls > self.max_daily_api_calls:
            raise BudgetExceeded(...)
        self._insert(worker, api_calls, cost_usd)
```

---

### 7. Workspace symlink escape check is shallow

**File:** `orchestrator/workspace.py:27-38`

Only checks target path and its direct parent for symlinks. Doesn't check grandparent or deeper ancestors. TOCTOU gap between `is_symlink()` check and actual use.

**Fix:** Use `Path.resolve(strict=True)` and compare resolved path against allowed root:

```python
def _check_no_symlink_escape(target: Path, allowed_root: Path) -> None:
    resolved = target.resolve()
    allowed = allowed_root.resolve()
    if not str(resolved).startswith(str(allowed) + os.sep) and resolved != allowed:
        raise WorkspaceError(f"Path escapes workspace: {target} -> {resolved}")
```

---

### 8. Preflight `--version` assumption breaks non-compliant binaries

**File:** `orchestrator/preflight.py`

Uses `binary --version` universally. Some CLIs use `-v`, `-V`, or `version` subcommand.

**Fix:** Add version command override in `MIN_BINARY_VERSIONS` config:

```
MIN_BINARY_VERSIONS=opencode=0.1.0:--version,codex=0.2.0:-v,claude=1.0.0:--version
```

---

## P2 — Medium (performance & reliability)

### 9. JSON schema loaded from disk on every validation

**File:** `orchestrator/validator.py`

`_load_schema()` reads and parses JSON file on each call to `validate_json()`.

**Fix:** Add `@functools.lru_cache` on `_load_schema()`.

---

### 10. Subprocess log file written line-by-line

**File:** `orchestrator/subprocess_utils.py`

Each stdout line triggers a file write. Under high-output agents (e.g., verbose builds), this creates I/O bottleneck.

**Fix:** Buffer writes (flush every N lines or every K seconds).

---

### 11. Retention uses mtime — recently accessed artifacts get deleted

**File:** `orchestrator/retention.py`

Uses `st_mtime` (last modified) for TTL. A job read by `/jobs/{id}` endpoint doesn't update mtime, so artifacts may expire while still being queried.

**Fix:** Use `max(st_mtime, st_atime)` or touch artifacts on read.

---

### 12. Metrics have no time windowing or per-agent breakdown

**File:** `orchestrator/metrics.py`

All metrics aggregate full history. No way to see "errors in last hour" or "cost per agent".

**Fix:** Add labels `{agent="claude"}`, `{window="1h"}`. Consider a sliding window counter or histogram for durations.

---

### 13. Log sanitizer may over-redact common env values

**File:** `orchestrator/log_sanitizer.py`

`redact()` replaces env var values with `str.replace()`. If an env var value is a common word (e.g., `true`, `production`), legitimate log text gets corrupted.

**Fix:** Only redact values longer than a minimum length (e.g., 8 chars). Add word-boundary matching for short values.

---

## P3 — Low (polish & developer experience)

### 14. Missing `pytest` in requirements.txt

Tests exist but `pytest` is not listed as a dependency.

**Fix:** Add `pytest>=7.0` to `requirements.txt` (or create `requirements-dev.txt`).

---

### 15. No scheduler documentation

**File:** `orchestrator/scheduler.py` exists but `docs/SCHEDULER.md` doesn't.

**Fix:** Create `docs/SCHEDULER.md` with cron syntax, schedule JSON format, and examples.

---

### 16. Health check port binding only checks 127.0.0.1

**File:** `orchestrator/health.py`

Checks if port 8080 is free on `127.0.0.1` but webhook server may bind `0.0.0.0:8080`.

**Fix:** Check both `127.0.0.1` and `0.0.0.0`.

---

### 17. No webhook request audit logging

**File:** `gateway/webhook_server.py`

No structured log entry for who called the webhook, from which IP, with which job.

**Fix:** Add access log: `log.info("webhook_submit", extra={"job_id": ..., "remote_ip": ..., "project_id": ...})`.

---

### 18. Git operations have no timeout

**File:** `orchestrator/git_utils.py`

`subprocess.run()` without `timeout=` parameter. A `git diff` on a huge repo can hang.

**Fix:** Add `timeout=60` (configurable) to all `_run_git()` calls.

---

## Feature Suggestions (beyond bugs)

### F1. Allow Claude as implementer (write-capable agent)

Currently Claude is review-only. With `allowed_tools` properly respected (see P0.1), Claude Code could serve as planner, implementer, AND reviewer — making it a universal agent in the pipeline.

Suggested new default pipeline option:
```
01_plan   → claude (role=planner, tools=[Read,Grep,Glob])
02_impl   → claude (role=implementer, tools=[Read,Edit,Write,Bash,Grep,Glob])
03_review → claude (role=reviewer, tools=[Read,Grep,Glob])
```

### F2. Step dependency graph (DAG) instead of linear pipeline

Current pipeline is strictly sequential. Allow steps to declare `depends_on: [step_id]` for parallel execution of independent steps.

### F3. Webhook callback on job completion

Add optional `callback_url` to JobSpec. POST result JSON to callback URL when job finishes. Enables async integrations (GitHub Actions, Slack, CI/CD).

### F4. Agent health probing

Periodically run `agent --version` for all registered workers. Expose in `/health` and `/metrics`. Detect agent binary updates or removals at runtime.

### F5. Cost estimation before execution

Use token estimation (prompt length × model pricing) to predict cost before running a step. Reject jobs that would exceed remaining daily budget.

---

## Summary Matrix

| # | Priority | Category | File(s) | Effort |
|---|----------|----------|---------|--------|
| 1 | P0 | Flexibility | claude_worker.py | S |
| 2 | P0 | Correctness | file_queue.py | S |
| 3 | P0 | Security | policy.py | M |
| 4 | P1 | Reliability | scheduler.py | S |
| 5 | P1 | Reliability | runner.py, file_queue.py | M |
| 6 | P1 | Correctness | budget.py | S |
| 7 | P1 | Security | workspace.py | S |
| 8 | P1 | Compatibility | preflight.py | S |
| 9 | P2 | Performance | validator.py | XS |
| 10 | P2 | Performance | subprocess_utils.py | S |
| 11 | P2 | Reliability | retention.py | S |
| 12 | P2 | Observability | metrics.py | M |
| 13 | P2 | Correctness | log_sanitizer.py | S |
| 14 | P3 | DX | requirements.txt | XS |
| 15 | P3 | DX | docs/ | S |
| 16 | P3 | Correctness | health.py | XS |
| 17 | P3 | Security | webhook_server.py | S |
| 18 | P3 | Reliability | git_utils.py | XS |

Effort: XS = <30min, S = 1-2h, M = 3-5h
