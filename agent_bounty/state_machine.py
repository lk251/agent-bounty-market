from __future__ import annotations

from .domain import BountyState


ALLOWED_TRANSITIONS: dict[BountyState, set[BountyState]] = {
    BountyState.DRAFT: {BountyState.AWAITING_FUNDING, BountyState.CANCELLED},
    BountyState.AWAITING_FUNDING: {BountyState.FUNDED, BountyState.CANCELLED},
    BountyState.FUNDED: {BountyState.OPEN, BountyState.REFUNDED, BountyState.CANCELLED},
    BountyState.OPEN: {BountyState.CLAIMED, BountyState.EXPIRED, BountyState.CANCELLED},
    BountyState.CLAIMED: {BountyState.SUBMITTED, BountyState.EXPIRED, BountyState.CANCELLED},
    BountyState.SUBMITTED: {BountyState.VERIFYING, BountyState.CANCELLED},
    BountyState.VERIFYING: {BountyState.ACCEPTED, BountyState.REJECTED},
    BountyState.ACCEPTED: {BountyState.PAYOUT_PENDING},
    BountyState.REJECTED: {BountyState.OPEN, BountyState.CANCELLED, BountyState.REFUNDED},
    BountyState.PAYOUT_PENDING: {BountyState.PAID, BountyState.PAYOUT_FAILED},
    BountyState.PAYOUT_FAILED: {BountyState.PAYOUT_PENDING, BountyState.REFUNDED},
    BountyState.PAID: set(),
    BountyState.EXPIRED: {BountyState.REFUNDED},
    BountyState.CANCELLED: {BountyState.REFUNDED},
    BountyState.REFUNDED: set(),
}


class InvalidTransition(RuntimeError):
    pass


def assert_transition(current: str | BountyState, target: str | BountyState) -> None:
    current_state = BountyState(current)
    target_state = BountyState(target)
    if target_state not in ALLOWED_TRANSITIONS[current_state]:
        raise InvalidTransition(f"invalid bounty transition: {current_state.value} -> {target_state.value}")
