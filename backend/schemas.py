from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class TaskContext(BaseModel):
    use_case: str = "gym_coach"
    task: str = "general_guidance"
    step_number: int = 1
    total_steps: int = 1


class DetectionObject(BaseModel):
    label: str
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    bbox: list[float] = Field(default_factory=list)
    source: str = "yolo26"


class SceneState(BaseModel):
    scene_id: str
    task_context: TaskContext = Field(default_factory=TaskContext)
    objects: list[DetectionObject] = Field(default_factory=list)
    scene_summary: str = "no salient objects detected"
    system_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class GuidancePayload(BaseModel):
    task: str = "general_guidance"
    instruction_text: str = "Hold steady and center the target object."
    visual_type: str = "highlight"
    location_3d: list[float] = Field(default_factory=lambda: [0.0, 0.0, 1.3])
    objects_detected: list[str] = Field(default_factory=list)
    step_number: int = 1
    total_steps: int = 1
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reasoning_source: str = "rule_based"
    debug: dict[str, Any] = Field(default_factory=dict)
