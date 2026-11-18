import pytest

from core.enums import OrderStatus
from domain.order import ALLOWED_TRANSITIONS, can_transition

S = OrderStatus

ALLOWED = [
    (S.PENDING, S.PAID),
    (S.PENDING, S.CANCELLED),
    (S.PAID, S.PREPARING),
    (S.PAID, S.CANCELLED),
    (S.PREPARING, S.ON_THE_WAY),
    (S.ON_THE_WAY, S.DELIVERED),
]

FINAL_STATES = [S.DELIVERED, S.CANCELLED]


@pytest.mark.parametrize(("current", "new"), ALLOWED)
def test_allowed_transitions(current: OrderStatus, new: OrderStatus):
    assert can_transition(current, new)


@pytest.mark.parametrize(
    ("current", "new"),
    [
        (current, new)
        for current in OrderStatus
        for new in OrderStatus
        if (current, new) not in ALLOWED
    ],
)
def test_every_other_transition_is_rejected(current: OrderStatus, new: OrderStatus):
    """Covers every pair not in ALLOWED, so a transition added by mistake fails a test."""
    assert not can_transition(current, new)


@pytest.mark.parametrize(
    ("current", "new"),
    [
        (S.PREPARING, S.CANCELLED),  # the food is already being made
        (S.ON_THE_WAY, S.CANCELLED),
        (S.DELIVERED, S.PENDING),
        (S.PENDING, S.DELIVERED),  # can't skip steps
        (S.PAID, S.PAID),  # no self-transitions
    ],
)
def test_notable_rejected_transitions(current: OrderStatus, new: OrderStatus):
    assert not can_transition(current, new)


@pytest.mark.parametrize("status", FINAL_STATES)
def test_final_states_have_no_way_out(status: OrderStatus):
    assert ALLOWED_TRANSITIONS[status] == frozenset()


def test_every_status_has_an_entry():
    """A new status added to the enum but not to the table would raise KeyError at runtime."""
    assert set(ALLOWED_TRANSITIONS) == set(OrderStatus)
