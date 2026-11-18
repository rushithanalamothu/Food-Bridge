"""PostGIS candidates, bounded road routing and constrained match recommendations."""

import json
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from geoalchemy2 import Geography
from pydantic import BaseModel, ValidationError
from sqlalchemy import cast, func, select

from foodbridge.agents.intake.config import load_policy
from foodbridge.agents.intake.policy import evaluate
from foodbridge.agents.intake.service import utcnow
from foodbridge.agents.matching.config import load_matching_config
from foodbridge.agents.matching.ranking import distance_only, multi_criteria
from foodbridge.agents.matching.routing import FakeRouting, NoRoute
from foodbridge.db.models import Organization, User
from foodbridge.db.session import session_factory
from foodbridge.db.workflow import current_driver_facts, current_profile
from foodbridge.db.workflow_models import Assignment, Driver, RecipientState, Reservation
from foodbridge.domain.contracts import Location, MatchRecommendation, RankingEvidence
from foodbridge.domain.errors import AppError
from foodbridge.domain.intake import EligibilityBatch, EligibilityCandidate, RouteFacts
from foodbridge.integrations.ai import generate_structured
from foodbridge.settings import Settings

PROMPT_VERSION = "matching-choice-v1"


class ModelChoice(BaseModel):
    selected_recipient_id: UUID


class LiveMatching:
    def __init__(self, settings: Settings, routing, clock=utcnow):
        self.settings, self.routing, self.clock = settings, routing, clock
        self.sessions = session_factory(settings.database_url)
        self.config = load_matching_config()
        self.policy = load_policy()
        if self.config.eligibility_policy_version != self.policy.version:
            raise ValueError("matching and intake eligibility policy versions differ")

    def _driver_origins(self, session, donation, excluded, now):
        occupied = select(Assignment.driver_id).where(
            Assignment.status.in_(["assigned", "accepted", "collected"]),
            Assignment.start < donation.pickup_window.end,
            Assignment.end > donation.pickup_window.start,
        )
        rows = session.scalars(
            select(Driver)
            .join(User, User.id == Driver.user_id)
            .join(Organization, Organization.id == Driver.organization_id)
            .where(User.active.is_(True), Organization.active.is_(True), Driver.id.not_in(occupied))
            .order_by(Driver.id)
            .limit(50)
        )
        result = []
        for row in rows:
            if row.id in excluded:
                continue
            # Require a fresh, authenticated self-reported starting point. The
            # organization's address is not the driver's current position.
            try:
                origin = Location.model_validate(row.facts["routing_origin"])
                observed = datetime.fromisoformat(row.facts["routing_origin_observed_at"])
                if observed.tzinfo is None:
                    continue
                age = (now - observed).total_seconds()
                if age < -30 or age > self.policy.route_max_age_s:
                    continue
                facts = current_driver_facts(row)
                if (
                    facts.id != row.id
                    or not facts.available
                    or donation.storage not in facts.storage_types
                ):
                    continue
            except (KeyError, TypeError, ValueError, ValidationError):
                continue
            result.append((facts, origin))
            if len(result) >= self.config.max_driver_routes:
                break
        return result

    def _drivers(self, origins, pickup):
        result = []
        for facts, origin in origins:
            try:
                estimate = self.routing.estimate(origin, pickup)
            except NoRoute:
                continue
            result.append(facts.model_copy(update={"to_pickup_time_s": estimate.travel_time_s}))
        return sorted(result, key=lambda facts: (facts.to_pickup_time_s, str(facts.id)))

    def candidates(self, donation, excluded_recipients, excluded_drivers):
        now = self.clock()
        point = cast(
            func.ST_SetSRID(
                func.ST_MakePoint(
                    donation.pickup_location.longitude, donation.pickup_location.latitude
                ),
                4326,
            ),
            Geography(geometry_type="POINT", srid=4326),
        )
        candidates = []
        with self.sessions() as session:
            origins = self._driver_origins(session, donation, excluded_drivers, now)
            rows = list(
                session.scalars(
                    select(RecipientState)
                    .join(Organization, Organization.id == RecipientState.organization_id)
                    .where(
                        RecipientState.verified.is_(True),
                        Organization.active.is_(True),
                        Organization.id != donation.donor_organization_id,
                        Organization.id.not_in(excluded_recipients),
                        func.ST_DWithin(
                            Organization.location, point, self.config.max_search_radius_m
                        ),
                    )
                    .order_by(func.ST_Distance(Organization.location, point), Organization.id)
                    .limit(self.config.max_candidates)
                )
            )
            profiles = []
            for state in rows:
                try:
                    _, profile, _ = current_profile(session, state.organization_id)
                except (ValueError, ValidationError):
                    # Invalid recipient data cannot enter the eligible cohort.
                    continue
                profiles.append(profile)
        # Database reads are complete before any network call. The coordinator
        # rechecks versions and policy when committing an offer.
        drivers = self._drivers(origins, donation.pickup_location)
        for profile in profiles:
            try:
                route = self.routing.estimate(donation.pickup_location, profile.location)
            except NoRoute:
                route = None
            route_facts = (
                RouteFacts(
                    distance_m=route.distance_m,
                    travel_time_s=route.travel_time_s,
                    calculated_at=now,
                    source=(
                        "synthetic" if isinstance(self.routing, FakeRouting) else "routing_provider"
                    ),
                    estimated=route.estimated,
                )
                if route
                else None
            )
            driver = None
            for proposed in drivers:
                candidate = EligibilityCandidate(
                    recipient=profile,
                    active_and_verified=True,
                    route=route_facts,
                    driver=proposed,
                )
                check = evaluate(
                    donation,
                    EligibilityBatch(
                        donation_id=donation.id,
                        expected_donation_version=donation.version,
                        candidates=[candidate],
                        synthetic=isinstance(self.routing, FakeRouting),
                    ),
                    now,
                    self.policy,
                )
                if check.decisions[0].eligible:
                    driver = proposed
                    break
            candidates.append(
                EligibilityCandidate(
                    recipient=profile, active_and_verified=True, route=route_facts, driver=driver
                )
            )
        return EligibilityBatch(
            donation_id=donation.id,
            expected_donation_version=donation.version,
            candidates=candidates,
            synthetic=isinstance(self.routing, FakeRouting),
        )

    def _allocations(self, cohort, now):
        ids = [row.recipient.organization_id for row in cohort]
        if not ids:
            return {}
        with self.sessions() as session:
            return {
                recipient_id: float(total)
                for recipient_id, total in session.execute(
                    select(Reservation.recipient_organization_id, func.sum(Reservation.quantity_kg))
                    .where(
                        Reservation.recipient_organization_id.in_(ids),
                        Reservation.status.in_(["active", "completed"]),
                        Reservation.created_at
                        >= now - timedelta(days=self.config.fairness_window_days),
                    )
                    .group_by(Reservation.recipient_organization_id)
                ).all()
            }

    def rank(self, handoff, matching_round):
        if (
            handoff.result.policy_version != self.policy.version
            or handoff.result.donation_version != handoff.donation.version
            or handoff.result.donation_id != handoff.donation.id
        ):
            raise AppError("eligibility_changed", "Eligibility policy changed; reevaluate.", 409)
        now = self.clock()
        if now >= min(handoff.donation.pickup_window.end, handoff.donation.safe_use_by):
            raise AppError("stale_evaluation", "Donation deadline passed.", 409)
        if any(
            c.route and (now - c.route.calculated_at).total_seconds() > self.policy.route_max_age_s
            for c in handoff.eligible_candidates
        ):
            raise AppError("stale_evaluation", "Route facts expired; reevaluate.", 409)
        provider = model = prompt_version = fallback = None
        if self.settings.matching_algorithm == "distance_only":
            selected = distance_only(handoff)
        else:
            cohort = multi_criteria(
                handoff, self.config, self._allocations(handoff.eligible_candidates, now)
            )
            selected = cohort[0] if cohort else None
            if selected and self.settings.ai_provider != "rules":
                provider, model, prompt_version = (
                    self.settings.ai_provider,
                    self.settings.ai_model,
                    PROMPT_VERSION,
                )
                # Send only eligible IDs and normalized components, never donor text or locations.
                shortlist = cohort[:3]
                input_data = [
                    {
                        "recipient_id": str(row.candidate.recipient.organization_id),
                        "score": row.score,
                        "features": row.features,
                    }
                    for row in shortlist
                ]
                try:
                    choice = generate_structured(
                        self.settings,
                        instructions=(
                            "Choose one listed eligible recipient ID. Do not add IDs or infer "
                            "food safety. Return only the requested schema."
                        ),
                        user_input=json.dumps(input_data, sort_keys=True),
                        output_type=ModelChoice,
                    )
                    selected = next(
                        row
                        for row in shortlist
                        if row.candidate.recipient.organization_id == choice.selected_recipient_id
                    )
                except (StopIteration, ValueError, OSError, TimeoutError):
                    fallback = "invalid_or_unavailable_model_choice"
                except Exception:
                    fallback = "model_provider_failure"
        if selected is None:
            return None
        candidate = selected.candidate
        expiry = min(
            now + timedelta(seconds=self.config.offer_ttl_s),
            handoff.donation.pickup_window.end,
            handoff.donation.safe_use_by,
        )
        if expiry <= now:
            raise AppError("stale_evaluation", "Offer window has elapsed.", 409)
        return MatchRecommendation(
            id=uuid4(),
            donation_id=handoff.donation.id,
            donation_version=handoff.donation.version,
            matching_round=matching_round,
            recipient_organization_id=candidate.recipient.organization_id,
            distance_m=candidate.route.distance_m,
            travel_time_s=candidate.route.travel_time_s,
            offer_expires_at=expiry,
            explanation=(
                "Nearest eligible recipient by road distance."
                if self.settings.matching_algorithm == "distance_only"
                else "Eligible recipient selected from normalized distance, capacity, "
                "recent allocation and feasible pickup slack."
            ),
            algorithm=self.settings.matching_algorithm,
            eligibility_policy_version=self.policy.version,
            ranking_config_version=self.config.version,
            ranking_evidence=RankingEvidence(
                score=selected.score,
                features=selected.features,
                provider=provider,
                model=model,
                prompt_version=prompt_version,
                fallback_reason=fallback,
            ),
        )
