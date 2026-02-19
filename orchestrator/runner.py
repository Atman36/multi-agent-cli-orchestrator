from __future__ import annotations

import asyncio
import json as _json
import logging
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

from orchestrator.artifact_store import ArtifactStore
from orchestrator.budget import BudgetLimitExceeded, BudgetTracker
from orchestrator.config import Settings
from orchestrator.logging_utils import setup_logging
from orchestrator.models import JobSpec, JobResult, StepResult, ArtifactPaths, ErrorInfo, utc_now_iso
from orchestrator.policy import build_policy_from_env, PolicyError
from orchestrator.preflight import assert_real_cli_ready, PreflightError
from orchestrator.retention import run_retention
from orchestrator.validation import validate_result_contract
from orchestrator.validator import validate_json, SchemaValidationError
from orchestrator.workspace import WorkspaceManager, WorkspaceError
from fsqueue.file_queue import FileQueue, QueueEmpty

from workers.base import StepContext
from workers import ensure_workers_registered, get_worker


log = logging.getLogger("runner")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _contracts_dir() -> Path:
    return _repo_root() / "contracts"


def _verify_script() -> Path:
    return _repo_root() / "scripts" / "verify_artifacts.sh"


def _read_text(p: Path) -> str:
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8")


async def _sleep_backoff(base_sec: int, attempt: int) -> None:
    # Exponential backoff with cap
    delay = min(base_sec * (2 ** max(0, attempt - 1)), 30)
    await asyncio.sleep(delay)


def reclaim_stale_running_jobs(queue: FileQueue, stale_after_sec: int) -> int:
    return queue.reclaim_stale_running(stale_after_sec)


def _run_secrets_check(step_dir: Path) -> tuple[bool, str]:
    script = _verify_script()
    if not script.exists():
        return True, "verify_artifacts.sh not found; check skipped"

    proc = subprocess.run(
        ["bash", str(script), str(step_dir)],
        check=False,
        capture_output=True,
        text=True,
    )
    msg = (proc.stdout or proc.stderr or "").strip()
    if not msg:
        msg = "secrets check completed"
    return proc.returncode == 0, msg


def _resolve_on_failure(on_failure: str, steps: list, current_idx: int) -> int | None:
    """Resolve on_failure directive to next step index.

    Returns:
        None  — stop pipeline (default)
        int   — index of the next step to execute
    """
    if on_failure == "stop":
        return None
    if on_failure == "continue":
        nxt = current_idx + 1
        return nxt if nxt < len(steps) else None
    if on_failure.startswith("goto:"):
        target_id = on_failure[5:]
        for idx, s in enumerate(steps):
            if s.step_id == target_id:
                return idx
        log.warning("on_failure goto target '%s' not found; stopping pipeline", target_id)
        return None
    log.warning("Unknown on_failure value '%s'; stopping pipeline", on_failure)
    return None


async def _fire_callback(callback_url: str, result_obj: dict) -> None:
    """POST job result to callback_url. Best-effort, never raises."""
    parsed = urlparse(callback_url)
    if parsed.scheme not in ("http", "https"):
        log.warning("callback_url has unsupported scheme: %s", callback_url)
        return
    try:
        import urllib.request

        body = _json.dumps(result_obj, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            callback_url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        # Run blocking IO in executor to avoid blocking the event loop
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, lambda: urllib.request.urlopen(req, timeout=15))
        log.info("Callback delivered to %s", callback_url)
    except Exception as e:
        log.warning("Callback to %s failed: %s", callback_url, e)


async def run_forever_async() -> None:
    load_dotenv()
    settings = Settings.load()
    setup_logging(settings.log_level, json_output=settings.log_json)
    ensure_workers_registered()

    q = FileQueue(settings.queue_root)
    store = ArtifactStore(settings.artifacts_root)
    workspace_manager = WorkspaceManager(settings.workspaces_root, settings.project_aliases)
    budget = BudgetTracker(
        db_path=settings.state_db_path,
        max_daily_api_calls=settings.max_daily_api_calls,
        max_daily_cost_usd=settings.max_daily_cost_usd,
    )

    job_schema = _contracts_dir() / "job.schema.json"
    result_schema = _contracts_dir() / "result.schema.json"

    policy = build_policy_from_env(
        allowed_binaries=settings.allowed_binaries,
        sandbox=settings.sandbox,
        sandbox_wrapper=settings.sandbox_wrapper,
        sandbox_wrapper_args=settings.sandbox_wrapper_args,
        network_policy=settings.network_policy,
    )
    if settings.enable_real_cli:
        versions = assert_real_cli_ready(
            allowed_binaries=settings.allowed_binaries,
            min_binary_versions=settings.min_binary_versions,
            required_binaries=["opencode", "codex", "claude", "git"],
        )
        if versions:
            log.info("Real CLI preflight versions: %s", versions)

    log.info("Runner started. enable_real_cli=%s sandbox=%s", settings.enable_real_cli, settings.sandbox)
    if policy.network_policy == "deny" and (not policy.sandbox or not policy.sandbox_wrapper):
        log.warning(
            "NETWORK_POLICY=deny is configured without enforceable sandbox wrapper. "
            "Real CLI jobs requesting network deny will be rejected."
        )
    next_retention_at = 0.0

    while True:
        reclaimed = reclaim_stale_running_jobs(q, settings.runner_reclaim_after_sec)
        if reclaimed:
            log.warning("Reclaimed %s stale running job(s) back to pending", reclaimed)
        if settings.retention_interval_sec > 0 and time.time() >= next_retention_at:
            stats = run_retention(
                queue_root=settings.queue_root,
                artifacts_root=settings.artifacts_root,
                workspaces_root=settings.workspaces_root,
                artifacts_ttl_sec=settings.artifacts_ttl_sec,
                workspaces_ttl_sec=settings.workspaces_ttl_sec,
            )
            if stats.removed_artifacts or stats.removed_workspaces:
                log.info(
                    "Retention cleanup removed artifacts=%s workspaces=%s",
                    stats.removed_artifacts,
                    stats.removed_workspaces,
                )
            next_retention_at = time.time() + settings.retention_interval_sec

        try:
            claimed = q.claim()
        except QueueEmpty:
            await asyncio.sleep(settings.runner_poll_interval_sec)
            continue

        try:
            job_obj = q.read_claimed(claimed)

            # Validate contract early (fail fast)
            validate_json(job_obj, job_schema)

            job = JobSpec.model_validate(job_obj)
            if job.project_id:
                source_hint: Path | None = workspace_manager.resolve_project_alias(job.project_id)
            elif job.source.type == "webhook":
                source_hint = None
            else:
                source_hint = Path(job.workdir).expanduser()
            layout = workspace_manager.prepare_workspace(job_id=job.job_id, source_hint=source_hint)
            job = job.model_copy(update={"workdir": str(layout.workdir)})

            store.ensure_job_layout(job.job_id)
            store.write_job_spec(job.job_id, job.model_dump())

            job_dir = store.job_dir(job.job_id)
            started_at = utc_now_iso()

            # Operational state (written after each step)
            state = {
                "job_id": job.job_id,
                "status": "running",
                "started_at": started_at,
                "finished_at": None,
                "current_step": None,
                "steps": {},
            }
            store.write_state(job.job_id, state)

            step_results: list[StepResult] = []

            overall_status = "success"
            overall_error: ErrorInfo | None = None
            job_policy = policy.for_job(
                job_sandbox=job.policy.sandbox,
                job_network_policy=job.policy.network,
                job_allowed_binaries=job.policy.allowed_binaries,
            )
            if settings.enable_real_cli:
                try:
                    job_policy.assert_real_cli_safe()
                except PolicyError as e:
                    overall_status = "failed"
                    overall_error = ErrorInfo(code="policy", message=str(e))

            step_idx = 0
            while step_idx < len(job.steps):
                step = job.steps[step_idx]
                if overall_error is not None:
                    break
                step_id = step.step_id
                store.ensure_step_layout(job.job_id, step_id)
                step_dir = store.step_dir(job.job_id, step_id)

                state["current_step"] = step_id
                state["steps"].setdefault(step_id, {})
                store.write_state(job.job_id, state)

                worker = get_worker(step.agent)
                if not worker:
                    overall_status = "failed"
                    overall_error = ErrorInfo(code="unknown_agent", message=f"Unknown agent '{step.agent}'")
                    break

                attempt = 0
                last_result: StepResult | None = None

                while attempt <= step.max_retries:
                    attempt += 1

                    state["steps"][step_id].update({
                        "status": "running",
                        "attempt": attempt,
                        "agent": step.agent,
                        "role": step.role,
                        "started_at": utc_now_iso(),
                    })
                    store.write_state(job.job_id, state)

                    ctx = StepContext(
                        job=job,
                        step=step,
                        job_dir=job_dir,
                        step_dir=step_dir,
                        enable_real_cli=settings.enable_real_cli,
                        policy=job_policy,
                        env_allowlist=settings.env_allowlist,
                        sensitive_env_vars=settings.sensitive_env_vars,
                        sandbox_clear_env=settings.sandbox_clear_env,
                        max_input_artifacts_files=settings.max_input_artifacts_files,
                        max_input_artifact_chars=settings.max_input_artifact_chars,
                        max_input_artifacts_chars=settings.max_input_artifacts_chars,
                        idle_watchdog_sec=settings.runner_max_idle_sec,
                        non_git_workdir_status=settings.non_git_workdir_status,
                    )
                    api_call_consumed = False

                    try:
                        if budget.enabled:
                            budget.check_budget()

                        # Hard timeout enforced here too (worker may also enforce)
                        res: StepResult = await asyncio.wait_for(worker.run(ctx), timeout=step.timeout_sec + 5)
                        api_call_consumed = True
                        # Overwrite attempts to reflect retries
                        res.attempts = attempt
                        last_result = res
                    except BudgetLimitExceeded as e:
                        last_result = StepResult(
                            job_id=job.job_id,
                            step_id=step_id,
                            agent=step.agent,
                            role=step.role,
                            status="failed",
                            attempts=attempt,
                            started_at=state["steps"][step_id]["started_at"],
                            finished_at=utc_now_iso(),
                            summary="Budget limit exceeded",
                            artifacts=ArtifactPaths(
                                report_md=str(Path("steps") / step_id / "report.md"),
                                patch_diff=str(Path("steps") / step_id / "patch.diff"),
                                logs_txt=str(Path("steps") / step_id / "logs.txt"),
                                result_json=str(Path("steps") / step_id / "result.json"),
                            ),
                            error=ErrorInfo(code="budget_exceeded", message=str(e)),
                        )
                    except PolicyError as e:
                        overall_status = "failed"
                        overall_error = ErrorInfo(code="policy", message=str(e))
                        last_result = None
                        break
                    except asyncio.TimeoutError:
                        api_call_consumed = True
                        last_result = StepResult(
                            job_id=job.job_id,
                            step_id=step_id,
                            agent=step.agent,
                            role=step.role,
                            status="timeout",
                            attempts=attempt,
                            started_at=state["steps"][step_id]["started_at"],
                            finished_at=utc_now_iso(),
                            summary=f"Step timeout after {step.timeout_sec}s",
                            artifacts=ArtifactPaths(
                                report_md=str(Path("steps") / step_id / "report.md"),
                                patch_diff=str(Path("steps") / step_id / "patch.diff"),
                                logs_txt=str(Path("steps") / step_id / "logs.txt"),
                                result_json=str(Path("steps") / step_id / "result.json"),
                            ),
                        )
                    except Exception as e:
                        api_call_consumed = True
                        last_result = StepResult(
                            job_id=job.job_id,
                            step_id=step_id,
                            agent=step.agent,
                            role=step.role,
                            status="failed",
                            attempts=attempt,
                            started_at=state["steps"][step_id]["started_at"],
                            finished_at=utc_now_iso(),
                            summary="Unhandled exception",
                            artifacts=ArtifactPaths(
                                report_md=str(Path("steps") / step_id / "report.md"),
                                patch_diff=str(Path("steps") / step_id / "patch.diff"),
                                logs_txt=str(Path("steps") / step_id / "logs.txt"),
                                result_json=str(Path("steps") / step_id / "result.json"),
                            ),
                            error=ErrorInfo(code="exception", message=str(e)),
                        )

                    # Validate artifacts for secret leaks and enforce result contract.
                    report_md = _read_text(step_dir / "report.md")
                    patch_diff = _read_text(step_dir / "patch.diff")
                    logs_txt = _read_text(step_dir / "logs.txt")
                    secrets_ok, secrets_msg = _run_secrets_check(step_dir)
                    logs_txt = (logs_txt.rstrip() + "\n\n" if logs_txt.strip() else "") + f"[secrets_check] {secrets_msg}\n"

                    if secrets_ok:
                        last_result = last_result.model_copy(update={"secrets_check": "passed"})
                    else:
                        last_result = last_result.model_copy(
                            update={
                                "status": "failed",
                                "finished_at": utc_now_iso(),
                                "summary": "Secrets check failed",
                                "secrets_check": "failed",
                                "error": ErrorInfo(
                                    code="secrets_check_failed",
                                    message="Potential secrets detected in step artifacts",
                                ),
                            }
                        )

                    try:
                        validate_result_contract(last_result.model_dump(), result_schema)
                    except SchemaValidationError as e:
                        last_result = last_result.model_copy(
                            update={
                                "status": "failed",
                                "finished_at": utc_now_iso(),
                                "summary": "Result schema validation failed",
                                "error": ErrorInfo(code="result_schema_validation_failed", message=str(e)),
                            }
                        )

                    store.write_step_artifacts(
                        job.job_id,
                        step_id,
                        report_md=report_md,
                        patch_diff=patch_diff,
                        logs_txt=logs_txt,
                        result_obj=last_result.model_dump(),
                    )

                    if budget.enabled and api_call_consumed:
                        budget.log_budget(
                            step.agent,
                            api_calls=1,
                            cost_usd=float(last_result.metrics.cost_usd or 0.0),
                        )

                    state["steps"][step_id].update({
                        "status": last_result.status,
                        "finished_at": last_result.finished_at,
                        "summary": last_result.summary,
                    })
                    store.write_state(job.job_id, state)

                    if last_result.status == "success":
                        break

                    if attempt <= step.max_retries:
                        state["steps"][step_id]["status"] = "retrying"
                        store.write_state(job.job_id, state)
                        await _sleep_backoff(step.retry_backoff_sec, attempt)

                if overall_error is not None:
                    break

                if last_result is None:
                    overall_status = "failed"
                    overall_error = ErrorInfo(code="no_result", message=f"No result for step {step_id}")
                    break

                step_results.append(last_result)

                if last_result.status != "success":
                    on_failure = getattr(step, "on_failure", "stop") or "stop"
                    next_idx = _resolve_on_failure(on_failure, job.steps, step_idx)
                    if next_idx is not None:
                        log.info(
                            "Step %s failed (status=%s) but on_failure=%s → jumping to step %s",
                            step_id, last_result.status, on_failure, job.steps[next_idx].step_id,
                        )
                        step_idx = next_idx
                        continue
                    overall_status = "failed"
                    overall_error = ErrorInfo(code="step_failed", message=f"Step {step_id} failed with status={last_result.status}")
                    break

                step_idx += 1

            finished_at = utc_now_iso()

            # Build aggregated artifacts for the job
            agg_report_parts = [f"# Job {job.job_id}\n", f"## Goal\n\n{job.goal}\n"]
            agg_patch_parts = []
            agg_logs_parts = []

            for sr in step_results:
                sd = store.step_dir(job.job_id, sr.step_id)
                agg_report_parts.append(f"\n---\n\n## Step {sr.step_id} ({sr.agent}:{sr.role})\n\n")
                agg_report_parts.append(_read_text(sd / "report.md"))

                patch = _read_text(sd / "patch.diff").strip()
                if patch:
                    agg_patch_parts.append(f"\n\n# --- step {sr.step_id} ({sr.agent}:{sr.role}) ---\n\n{patch}\n")

                logs = _read_text(sd / "logs.txt").strip()
                if logs:
                    agg_logs_parts.append(f"\n\n# --- step {sr.step_id} ({sr.agent}:{sr.role}) ---\n\n{logs}\n")

            job_report_md = "\n".join(agg_report_parts).strip() + "\n"
            job_patch_diff = "\n".join(agg_patch_parts).strip() + "\n"
            job_logs_txt = "\n".join(agg_logs_parts).strip() + "\n"

            job_artifacts = ArtifactPaths(
                report_md="report.md",
                patch_diff="patch.diff",
                logs_txt="logs.txt",
                result_json="result.json",
            )

            job_result = JobResult(
                job_id=job.job_id,
                status=overall_status,
                started_at=started_at,
                finished_at=finished_at,
                summary=f"Completed with status={overall_status}. steps={len(step_results)}",
                artifacts=job_artifacts,
                secrets_check=(
                    "passed"
                    if step_results and all(sr.secrets_check == "passed" for sr in step_results)
                    else "failed"
                ),
                steps=step_results,
                error=overall_error,
            )

            validate_result_contract(job_result.model_dump(), result_schema)

            store.write_job_artifacts(
                job.job_id,
                report_md=job_report_md,
                patch_diff=job_patch_diff,
                logs_txt=job_logs_txt,
                result_obj=job_result.model_dump(),
            )

            state["status"] = overall_status
            state["finished_at"] = finished_at
            store.write_state(job.job_id, state)

            # Fire callback if configured (event-driven notification)
            if job.callback_url:
                await _fire_callback(job.callback_url, job_result.model_dump())

            if overall_status == "success":
                q.ack(claimed)
            else:
                q.fail(claimed)

            log.info("Job %s finished: %s", job.job_id, overall_status)

        except Exception as e:
            if isinstance(e, WorkspaceError):
                log.error("Workspace preparation failed: %s", e)
            if isinstance(e, PreflightError):
                log.error("Preflight failed: %s", e)
            log.exception("Job failed unexpectedly: %s", e)
            try:
                q.fail(claimed)
            except Exception:
                pass


def run_forever() -> None:
    asyncio.run(run_forever_async())


if __name__ == "__main__":
    run_forever()
