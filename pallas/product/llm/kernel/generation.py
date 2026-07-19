"""Shared generation task contract for repeater and llm_chat."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .candidates import ConversationCandidate
from .models import ConversationAction, ConversationMode, ConversationPath, ConversationScene, GenerationStage


class GenerationTask(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    path: ConversationPath
    action: ConversationAction
    stage: GenerationStage
    scene: ConversationScene = ConversationScene.SMALLTALK
    mode: ConversationMode = ConversationMode.NORMAL
    user_text: str = ""
    candidate_pool: list[str] = Field(default_factory=list)
    candidate_text: str = ""
    fallback_text: str = ""
    constraints_max_length: int = Field(default=0, ge=0)


class GenerationPlan(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    path: ConversationPath
    tasks: list[GenerationTask] = Field(default_factory=list)
    fallback_text: str = ""
    candidate_text: str = ""
    candidate_pool: list[str] = Field(default_factory=list)

    @property
    def stage_names(self) -> list[str]:
        return [task.stage.value for task in self.tasks]


def build_repeater_generation_plan(
    *,
    path: ConversationPath,
    stages: list[GenerationStage],
    scene: ConversationScene,
    mode: ConversationMode,
    user_text: str,
    candidate_pool: list[str],
    candidate_text: str,
    fallback_text: str,
    constraints_max_length: int = 0,
) -> GenerationPlan:
    tasks = [
        GenerationTask(
            path=path,
            action=stage_to_action(stage),
            stage=stage,
            scene=scene,
            mode=mode,
            user_text=user_text,
            candidate_pool=list(candidate_pool),
            candidate_text=candidate_text,
            fallback_text=fallback_text,
            constraints_max_length=constraints_max_length,
        )
        for stage in stages
    ]
    return GenerationPlan(
        path=path,
        tasks=tasks,
        fallback_text=fallback_text,
        candidate_text=candidate_text,
        candidate_pool=list(candidate_pool),
    )


def stage_to_action(stage: GenerationStage) -> ConversationAction:
    if stage == GenerationStage.SELECT:
        return ConversationAction.REPLY_CORPUS
    if stage == GenerationStage.REWRITE:
        return ConversationAction.REPLY_REWRITE
    if stage == GenerationStage.STITCH:
        return ConversationAction.REPLY_STITCH
    return ConversationAction.REPLY_GENERATE


def candidate_from_task_result(task: GenerationTask, text: str) -> ConversationCandidate:
    return ConversationCandidate.from_text(
        text,
        source=stage_to_candidate_source(task.stage),
        stage=task.stage,
        grounded=task.stage != GenerationStage.GENERATE,
        base_score=0.7 if task.stage != GenerationStage.GENERATE else 0.55,
    )


def stage_to_candidate_source(stage: GenerationStage):
    from .candidates import CandidateSource

    mapping = {
        GenerationStage.SELECT: CandidateSource.SELECT,
        GenerationStage.REWRITE: CandidateSource.REWRITE,
        GenerationStage.STITCH: CandidateSource.STITCH,
        GenerationStage.GENERATE: CandidateSource.GENERATE,
    }
    return mapping.get(stage, CandidateSource.CORPUS)
