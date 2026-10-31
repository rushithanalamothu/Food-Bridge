import pytest

from foodbridge.domain.states import DonationStatus as S
from foodbridge.domain.states import assert_transition


def test_a_delivered_donation_cannot_be_reopened():
    with pytest.raises(ValueError):
        assert_transition(S.DELIVERED, S.MATCHING)


def test_declined_offer_can_be_rematched():
    assert_transition(S.OFFERED, S.MATCHING)


def test_cannot_claim_pickup_before_reservation_and_assignment():
    with pytest.raises(ValueError):
        assert_transition(S.OFFERED, S.PICKED_UP)


def test_driver_decline_releases_assignment_without_rematching_recipient():
    assert_transition(S.PICKUP_ASSIGNED, S.RESERVED)
