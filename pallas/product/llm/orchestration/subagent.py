from __future__ import annotations

import time
import uuid

from .models import Artifact, SubAgentRun


def create_subagent_run(
    task_id: str, *, allowed_tools: list[str] | None = None, budget: int = 3, deadline: int | None = None
) -> SubAgentRun:
    return SubAgentRun(
        run_id=f"run-{uuid.uuid4().hex[:12]}",
        task_id=task_id,
        allowed_tools=allowed_tools or [],
        budget=max(1, budget),
        deadline=deadline,
    )


def execute_subagent_stub(run: SubAgentRun, steps: list[str] | None = None) -> SubAgentRun:
    planned = [str(step).strip() for step in (steps or []) if str(step).strip()][: run.budget]
    artifact = Artifact(artifact_id=f"artifact-{uuid.uuid4().hex[:12]}", content="\n".join(planned))
    return run.model_copy(update={"status": "completed", "planned_steps": planned, "artifacts": [artifact]})


def run_subagent_job(run: SubAgentRun, steps: list[str] | None = None) -> SubAgentRun:
    if run.deadline is not None and int(time.time()) > run.deadline:
        return run.model_copy(update={"status": "expired"})
    return execute_subagent_stub(run, steps)
