"""Model tool selection is bounded by server observations, not arbitrary task names."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from foodbridge.agents.orchestrator.agent import allowed_tools, baseline_plan, validate_plan
from foodbridge.domain.orchestration import OrchestrationObservation, OrchestrationPlan


@pytest.fixture
def observation():
    return OrchestrationObservation(
        step_id=uuid4(),
        donation_version=2,
        matching_round=1,
        donation_status="matching",
        stage="eligibility",
        attempts=0,
        retry_budget=3,
        failure_code=None,
        seconds_remaining=1000,
        urgency="critical",
        allowed_tools=allowed_tools("eligibility", 0, 1000),
        previous_outcomes=[],
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"tool": "confirm_delivery"},
        {"tool": "execute_python"},
        {"delay_s": 60},
        {"delay_s": 1},
        {"summary": ""},
    ],
)
def test_structured_plan_rejects_unsafe_or_invalid_fields(observation, changes):
    with pytest.raises(ValidationError):
        OrchestrationPlan.model_validate({**baseline_plan(observation).model_dump(), **changes})


@pytest.mark.parametrize(
    "changes",
    [
        {"step_id": uuid4()},
        {"donation_version": 99},
        {"matching_round": 99},
        {"tool": "coordinate_pickup"},
        {"tool": "retry_current_agent"},
    ],
)
def test_model_cannot_change_identifiers_versions_or_stage(observation, changes):
    proposal = OrchestrationPlan.model_validate(
        {**baseline_plan(observation).model_dump(), **changes}
    )
    with pytest.raises(ValueError):
        validate_plan(proposal, observation)


def test_agent_choices_include_real_recovery_options_and_deadline_limits():
    assert "retry_current_agent" in allowed_tools("assignment", 1, 100)
    assert "refresh_eligibility" in allowed_tools("matching", 1, 100)
    assert "wait" not in allowed_tools("matching", 1, 20)
    assert "refresh_eligibility" not in allowed_tools("assignment", 1, 100)
