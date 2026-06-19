from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class BountyState(StrEnum):
    DRAFT = "draft"
    AWAITING_FUNDING = "awaiting_funding"
    FUNDED = "funded"
    OPEN = "open"
    CLAIMED = "claimed"
    SUBMITTED = "submitted"
    VERIFYING = "verifying"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    PAYOUT_PENDING = "payout_pending"
    PAID = "paid"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"
    PAYOUT_FAILED = "payout_failed"


class PayoutStatus(StrEnum):
    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"


@dataclass(frozen=True)
class Project:
    id: str
    name: str
    created_at: str


@dataclass(frozen=True)
class Treasury:
    project_id: str
    currency: str


@dataclass(frozen=True)
class FundingEvent:
    id: str
    project_id: str
    amount: int
    currency: str
    gateway_event_id: str
    idempotency_key: str
    created_at: str


@dataclass(frozen=True)
class BudgetPolicy:
    id: str
    project_id: str
    max_bounty_amount: int
    monthly_budget: int
    human_approval_threshold: int
    allowed_issue_classes: tuple[str, ...]


@dataclass(frozen=True)
class Bounty:
    id: str
    project_id: str
    title: str
    reward_amount: int
    currency: str
    state: BountyState
    base_commit: str
    issue_ref: str
    verifier_id: str


@dataclass(frozen=True)
class Claim:
    id: str
    bounty_id: str
    solver_id: str
    status: str
    lease_expires_at: str
    idempotency_key: str


@dataclass(frozen=True)
class SolverIdentity:
    id: str
    display_name: str
    beneficiary_external_id: str | None
    created_at: str


@dataclass(frozen=True)
class Submission:
    id: str
    bounty_id: str
    claim_id: str
    solver_id: str
    candidate_commit: str
    candidate_repo_path: str
    idempotency_key: str


@dataclass(frozen=True)
class VerificationRun:
    id: str
    bounty_id: str
    submission_id: str
    status: str
    verifier_id: str
    started_at: str
    finished_at: str | None


@dataclass(frozen=True)
class VerificationReceipt:
    id: str
    run_id: str
    bounty_id: str
    base_commit: str
    candidate_commit: str
    verifier_digest: str
    accepted: bool
    stdout_sha256: str
    stderr_sha256: str
    started_at: str
    finished_at: str


@dataclass(frozen=True)
class Payout:
    id: str
    bounty_id: str
    solver_id: str
    amount: int
    currency: str
    status: PayoutStatus
    gateway_payout_id: str | None
    idempotency_key: str


@dataclass(frozen=True)
class LedgerEntry:
    id: str
    event_type: str
    idempotency_key: str
    from_account: str
    to_account: str
    amount: int
    currency: str
    created_at: str
