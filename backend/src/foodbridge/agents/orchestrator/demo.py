"""Explicit local synthetic adapter. This does not implement production routing or ranking."""

from datetime import timedelta
from uuid import uuid4

from sqlalchemy import select

from foodbridge.agents.intake.service import utcnow
from foodbridge.db.models import Organization, User
from foodbridge.db.session import session_factory
from foodbridge.db.workflow import current_profile
from foodbridge.db.workflow_models import Assignment, Driver, RecipientState
from foodbridge.domain.contracts import MatchRecommendation
from foodbridge.domain.intake import DriverFacts, EligibilityBatch, EligibilityCandidate, RouteFacts


class DemoMatching:
    def __init__(self, database_url, clock=utcnow):
        self.sessions, self.clock = session_factory(database_url), clock

    def candidates(self, donation, excluded_recipients, excluded_drivers):
        now = self.clock()
        with self.sessions() as session:
            busy = select(Assignment.driver_id).where(
                Assignment.status.in_(["assigned", "accepted", "collected"]), Assignment.end > now
            )
            drivers = list(
                session.scalars(
                    select(Driver)
                    .join(User, User.id == Driver.user_id)
                    .join(Organization, Organization.id == Driver.organization_id)
                    .where(
                        User.active.is_(True), Organization.active.is_(True), Driver.id.not_in(busy)
                    )
                    .order_by(Driver.id)
                )
            )
            driver = next(
                (
                    DriverFacts.model_validate(row.facts)
                    for row in drivers
                    if row.id not in excluded_drivers and row.facts.get("available")
                ),
                None,
            )
            rows = list(
                session.scalars(select(RecipientState).order_by(RecipientState.organization_id))
            )
            candidates = []
            for index, state in enumerate(rows):
                if state.organization_id in excluded_recipients:
                    continue
                _, profile, _ = current_profile(session, state.organization_id)
                org = session.get(Organization, state.organization_id)
                candidates.append(
                    EligibilityCandidate(
                        recipient=profile,
                        active_and_verified=bool(state.verified and org.active),
                        driver=driver,
                        route=RouteFacts(
                            distance_m=1000 + index * 500,
                            travel_time_s=180 + index * 30,
                            calculated_at=now,
                            source="synthetic",
                        ),
                    )
                )
            return EligibilityBatch(
                donation_id=donation.id,
                expected_donation_version=donation.version,
                candidates=candidates,
                synthetic=True,
            )

    def rank(self, handoff, matching_round):
        if not handoff.eligible_candidates:
            return None
        candidate = min(
            handoff.eligible_candidates,
            key=lambda c: (c.route.distance_m, str(c.recipient.organization_id)),
        )
        return MatchRecommendation(
            id=uuid4(),
            donation_id=handoff.donation.id,
            donation_version=handoff.donation.version,
            matching_round=matching_round,
            recipient_organization_id=candidate.recipient.organization_id,
            distance_m=candidate.route.distance_m,
            travel_time_s=candidate.route.travel_time_s,
            offer_expires_at=min(
                self.clock() + timedelta(minutes=5), handoff.donation.pickup_window.end
            ),
            explanation="SYNTHETIC LOCAL DEMO: nearest eligible fixture; no maps or AI call.",
            algorithm="distance_only",
            eligibility_policy_version=handoff.result.policy_version,
            ranking_config_version="synthetic-demo-v1",
        )
