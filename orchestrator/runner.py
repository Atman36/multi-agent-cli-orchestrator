from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from dotenv import load_dotenv

from orchestrator.artifact_store import ArtifactStore
from orchestrator.config import Settings
from orchestrator.logging_utils import setup_logging
from orchestrator.models import JobSpec, JobResult, StepResult, ArtifactPaths, ErrorInfo, utc_now_iso
from orchestrator.policy import build_policy_from_env, PolicyError
from orchestrator.validator import validate_json, SchemaValidationError
from fsqueue.file_queue import FileQueue, QueueEmpty

from workers.base import StepContext
from workers import ensure_workers_registered, get_worker


log = logging.getLogger("runner")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _contracts_dir() -> Path:
    return _repo_root() / "contracts"


def _read_text(p: Path) -> str:
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8")


async def _sleep_backoff(base_sec: int, attempt: int) -> None:
    # Exponential backoff with cap
    delay = min(base_sec * (2 ** max(0, attempt - 1)), 30)
    await asyncio.sleep(delay)


async def run_forever_async() -> None:
    load_dotenv()
    settings = Settings.load()
    setup_logging(settings.log_level)
    ensure_workers_registered()

    q = FileQueue(settings.queue_root)
    store = ArtifactStore(settings.artifacts_root)

    job_schema = _contracts_dir() / "job.schema.json"
    result_schema = _contracts_dir() / "result.schema.json"

    policy = build_policy_from_env(
        allowed_binaries=settings.allowed_binaries,
        sandbox=settings.sandbox,
        sandbox_wrapper=settings.sandbox_wrapper,
        sandbox_wrapper_args=settings.sandbox_wrapper_args,
        network_policy=settings.network_policy,
    )

    log.info("Runner started. enable_real_cli=%s sandbox=%s", settings.enable_real_cli, settings.sandbox)

    while True:
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

            for step in job.steps:
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
                        policy=policy,
                        env_allowlist=settings.env_allowlist,
                        sensitive_env_vars=settings.sensitive_env_vars,
                        max_input_artifacts_chars=settings.max_input_artifacts_chars,
                        idle_watchdog_sec=settings.runner_max_idle_sec,
                    )

                    try:
                        # Hard timeout enforced here too (worker may also enforce)
                        res: StepResult = await asyncio.wait_for(worker.run(ctx), timeout=step.timeout_sec + 5)
                        # Overwrite attempts to reflect retries
                        res.attempts = attempt
                        last_result = res
                    except PolicyError as e:
                        overall_status = "failed"
                        overall_error = ErrorInfo(code="policy", message=str(e))
                        last_result = None
                        break
                    except asyncio.TimeoutError:
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

                    # Persist step artifacts (fixed filenames)
                    report_md = _read_text(step_dir / "report.md")
                    patch_diff = _read_text(step_dir / "patch.diff")
                    logs_txt = _read_text(step_dir / "logs.txt")
                    store.write_step_artifacts(
                        job.job_id,
                        step_id,
                        report_md=report_md,
                        patch_diff=patch_diff,
                        logs_txt=logs_txt,
                        result_obj=last_result.model_dump(),
                    )

                    # Validate result contract (best effort)
                    try:
                        validate_json(last_result.model_dump(), result_schema)
                    except SchemaValidationError as e:
                        log.error("Result schema validation failed: %s", e)

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
                    overall_status = "failed"
                    overall_error = ErrorInfo(code="step_failed", message=f"Step {step_id} failed with status={last_result.status}")
                    break

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
                steps=step_results,
                error=overall_error,
            )

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

            if overall_status == "success":
                q.ack(claimed)
            else:
                q.fail(claimed)

            log.info("Job %s finished: %s", job.job_id, overall_status)

        except Exception as e:
            log.exception("Job failed unexpectedly: %s", e)
            try:
                q.fail(claimed)
            except Exception:
                pass


def run_forever() -> None:
    asyncio.run(run_forever_async())


if __name__ == "__main__":
    run_forever()
