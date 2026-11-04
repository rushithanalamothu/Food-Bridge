"""AI orchestration observations, tool calls and audit contracts; no infrastructure imports."""

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from foodbridge.domain.contracts import Contract

OrchestratorTool = Literal[
    "prepare_candidates",
    "rank_candidates",
    "coordinate_pickup",
    "retry_current_agent",
    "refresh_eligibility",
    "wait",
    "escalate_operator",
]


class StepOutcome(Contract):
    kind: str
    status: str
    attempts: int
    failure_code: str | None


class PlanFeedback(Contract):
    tool: OrchestratorTool
    mode: Literal["model", "rules", "fallback", "rejected"]
    outcome: Literal["dispatched", "deferred", "escalated", "revalidated", "stale"]


class OrchestrationObservation(Contract):
    step_id: UUID
    donation_version: int
    matching_round: int
    donation_status: str
    stage: str
    attempts: int
    retry_budget: int
    failure_code: str | None
    seconds_remaining: int
    urgency: Literal["critical", "high", "normal"]
    allowed_tools: list[OrchestratorTool]
    previous_outcomes: list[StepOutcome]
    previous_decision: PlanFeedback | None = None


class OrchestrationPlan(Contract):
    step_id: UUID
    donation_version: int = Field(ge=1)
    matching_round: int = Field(ge=1)
    tool: OrchestratorTool
    delay_s: int = Field(ge=0, le=30)
    summary: str = Field(min_length=1, max_length=400)

    @model_validator(mode="after")
    def meaningful_delay(self):
        if (self.tool == "wait" and self.delay_s < 5) or (self.tool != "wait" and self.delay_s):
            raise ValueError("Only wait accepts a delay, between 5 and 30 seconds")
        return self


class OrchestrationDecision(Contract):
    generation: int
    decided_at: AwareDatetime
    mode: Literal["model", "rules", "fallback", "rejected"]
    provider: str
    model: str | None
    prompt_version: str
    failure_code: str | None
    outcome: Literal["dispatched", "deferred", "escalated", "revalidated", "stale"]
    observation: OrchestrationObservation
    plan: OrchestrationPlan


class OrchestrationAudit(Contract):
    step_id: UUID
    donation_id: UUID
    status: str
    decisions: list[OrchestrationDecision]
