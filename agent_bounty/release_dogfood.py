from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from .core import AgentBountyMarket
from .economic_loop import (
    EconomicLoopError,
    allocate_accepted_reward,
    default_solver_operating_policy,
    save_solver_operating_policy,
    settlement_balances,
    spend_retained_credit_to_project,
)
from .ledger import project_reserved_account, solver_operating_available_account, solver_paid_account
from .payments import FakePaymentGateway
from .project_agent import DEFAULT_FINAL_COMMIT
from .util import sha256_bytes, stable_json, utc_now
from .verification import ProtectedVerificationResult, ProtectedVerifierRunner, verifier_digest


RELEASE_DOGFOOD_SCHEMA = "agent-bounty-release-provenance-dogfood-v1"
RELEASE_DOGFOOD_VERIFIER_ID = "release_provenance_v2"
RELEASE_DOGFOOD_REPO = "lk251/agent-bounty-market"
RELEASE_DOGFOOD_ISSUE_CLASS = "release-provenance-correctness"
RELEASE_DOGFOOD_SOURCE_PROJECT_ID = "project_agent_bounty_market_retained_source"
RELEASE_DOGFOOD_SOURCE_BOUNTY_ID = "bounty_prior_release_candidate_work"
RELEASE_DOGFOOD_TARGET_PROJECT_ID = "project_agent_bounty_market_release_provenance"
RELEASE_DOGFOOD_SOLVER_ID = "solver_release_provenance"
RELEASE_DOGFOOD_REWARD_CENTS = 500
RELEASE_DOGFOOD_CURRENCY = "USD"


class ReleaseDogfoodError(RuntimeError):
    pass


class ReleaseDogfoodVerifierRunner:
    def __init__(self, *, release_verifier_dir: Path | None = None, timeout_seconds: float = 120.0):
        self.release_verifier_dir = release_verifier_dir or default_release_verifier_dir()
        self.timeout_seconds = timeout_seconds

    def run(
        self,
        *,
        bounty_id: str,
        motoko_repo: Path,
        base_commit: str,
        candidate_commit: str,
    ) -> ProtectedVerificationResult:
        if bounty_id == RELEASE_DOGFOOD_SOURCE_BOUNTY_ID:
            return _accepted_source_result(bounty_id=bounty_id, candidate_commit=candidate_commit)
        return ProtectedVerifierRunner(verifier_dir=self.release_verifier_dir, timeout_seconds=self.timeout_seconds).run(
            bounty_id=bounty_id,
            motoko_repo=motoko_repo,
            base_commit=base_commit,
            candidate_commit=candidate_commit,
        )


def default_release_verifier_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "verifiers" / "release_provenance_v2"


def release_dogfood_report(
    market: AgentBountyMarket,
    *,
    candidate_repo: Path,
    candidate_sha: str | None = None,
    issue_number: int = 21,
    base_commit: str | None = None,
) -> dict[str, Any]:
    candidate_repo = candidate_repo.resolve()
    if candidate_sha is None:
        candidate_sha = _git(candidate_repo, "rev-parse", "HEAD")
    if base_commit is None:
        base_commit = _git(candidate_repo, "merge-base", "origin/main", candidate_sha, check=False) or _git(candidate_repo, "rev-list", "--max-parents=0", candidate_sha).splitlines()[0]
    source = _ensure_source_retained_credit(market)
    policy = save_solver_operating_policy(
        market,
        default_solver_operating_policy(
            solver_id=RELEASE_DOGFOOD_SOLVER_ID,
            allowed_projects=[RELEASE_DOGFOOD_TARGET_PROJECT_ID],
            allowed_repositories=[RELEASE_DOGFOOD_REPO],
            allowed_issue_classes=[RELEASE_DOGFOOD_ISSUE_CLASS],
            required_verifier_ids=[RELEASE_DOGFOOD_VERIFIER_ID],
            max_spend_cents=RELEASE_DOGFOOD_REWARD_CENTS,
            human_approval_threshold_cents=RELEASE_DOGFOOD_REWARD_CENTS,
            allowed_currencies=[RELEASE_DOGFOOD_CURRENCY],
        ),
    )
    spend = spend_retained_credit_to_project(
        market,
        solver_id=RELEASE_DOGFOOD_SOLVER_ID,
        target_project_id=RELEASE_DOGFOOD_TARGET_PROJECT_ID,
        repo_full_name=RELEASE_DOGFOOD_REPO,
        amount=RELEASE_DOGFOOD_REWARD_CENTS,
        currency=RELEASE_DOGFOOD_CURRENCY,
        title="Release provenance v2: self-contained annotated-tag audit",
        issue_class=RELEASE_DOGFOOD_ISSUE_CLASS,
        verifier_id=RELEASE_DOGFOOD_VERIFIER_ID,
        base_commit=base_commit,
        idempotency_key="release-provenance-v2:spend-retained:issue-21",
        issue_number=issue_number,
    )
    spend_replay = spend_retained_credit_to_project(
        market,
        solver_id=RELEASE_DOGFOOD_SOLVER_ID,
        target_project_id=RELEASE_DOGFOOD_TARGET_PROJECT_ID,
        repo_full_name=RELEASE_DOGFOOD_REPO,
        amount=RELEASE_DOGFOOD_REWARD_CENTS,
        currency=RELEASE_DOGFOOD_CURRENCY,
        title="Release provenance v2: self-contained annotated-tag audit",
        issue_class=RELEASE_DOGFOOD_ISSUE_CLASS,
        verifier_id=RELEASE_DOGFOOD_VERIFIER_ID,
        base_commit=base_commit,
        idempotency_key="release-provenance-v2:spend-retained:issue-21",
        issue_number=issue_number,
    )
    target_bounty_id = spend["target_bounty_id"]
    market.claim_bounty(
        bounty_id=target_bounty_id,
        solver_id=RELEASE_DOGFOOD_SOLVER_ID,
        lease_expires_at="2026-07-01T00:00:00Z",
        idempotency_key="release-provenance-v2:claim:issue-21",
    )
    submission = market.submit_candidate(
        bounty_id=target_bounty_id,
        solver_id=RELEASE_DOGFOOD_SOLVER_ID,
        candidate_repo_path=str(candidate_repo),
        candidate_commit=candidate_sha,
        idempotency_key=f"release-provenance-v2:submission:{candidate_sha}",
    )
    verification = market.run_verification(
        submission_id=submission["submission_id"],
        idempotency_key=f"release-provenance-v2:verify:{candidate_sha}",
    )
    if not verification.get("receipt") or not verification["receipt"].get("accepted"):
        raise ReleaseDogfoodError("release-provenance candidate was not accepted by protected verifier")
    second_settlement = allocate_accepted_reward(
        market,
        bounty_id=target_bounty_id,
        external_transfer_amount=RELEASE_DOGFOOD_REWARD_CENTS,
        retained_operating_amount=0,
        platform_fee_amount=0,
        retention_consent=False,
        transfer_provider="fake",
        idempotency_key="release-provenance-v2:settle:issue-21",
    )
    second_settlement_replay = allocate_accepted_reward(
        market,
        bounty_id=target_bounty_id,
        external_transfer_amount=RELEASE_DOGFOOD_REWARD_CENTS,
        retained_operating_amount=0,
        platform_fee_amount=0,
        retention_consent=False,
        transfer_provider="fake",
        idempotency_key="release-provenance-v2:settle:issue-21",
    )
    balances = settlement_balances(market, solver_id=RELEASE_DOGFOOD_SOLVER_ID, currency=RELEASE_DOGFOOD_CURRENCY)
    ok = (
        bool(source["allocation"]["ok"])
        and bool(spend["ok"])
        and bool(spend_replay["replayed"])
        and bool(verification["receipt"]["accepted"])
        and bool(second_settlement["ok"])
        and bool(second_settlement_replay["replayed"])
        and market.ledger.balance(solver_operating_available_account(RELEASE_DOGFOOD_SOLVER_ID), RELEASE_DOGFOOD_CURRENCY) == 0
        and market.ledger.balance(project_reserved_account(RELEASE_DOGFOOD_TARGET_PROJECT_ID), RELEASE_DOGFOOD_CURRENCY) == 0
        and market.ledger.balance(solver_paid_account(RELEASE_DOGFOOD_SOLVER_ID), RELEASE_DOGFOOD_CURRENCY) == RELEASE_DOGFOOD_REWARD_CENTS
    )
    receipt = verification["receipt"]
    evidence = {
        "schema": RELEASE_DOGFOOD_SCHEMA,
        "ok": ok,
        "issue": f"{RELEASE_DOGFOOD_REPO}#{issue_number}",
        "truth": "deterministic local market dogfood; fake provider IDs are not real Stripe or GitHub activity",
        "candidate_sha": candidate_sha,
        "source_retained_credit": {
            "source_bounty_id": RELEASE_DOGFOOD_SOURCE_BOUNTY_ID,
            "allocation_id": source["allocation"]["allocation_id"],
            "retained_operating_amount": source["allocation"]["retained_operating_amount"],
            "allocation_replayed": source["allocation_replay"]["replayed"],
        },
        "operating_policy": {
            "policy_id": policy["policy_id"],
            "policy_digest": policy["policy_digest"],
            "allowed_repository": RELEASE_DOGFOOD_REPO,
            "required_verifier_id": RELEASE_DOGFOOD_VERIFIER_ID,
        },
        "retained_credit_spend": {
            "spend_id": spend["spend_id"],
            "target_project_id": spend["target_project_id"],
            "target_bounty_id": target_bounty_id,
            "amount": spend["amount"],
            "contract_digest": spend["contract_digest"],
            "github_issue_url": spend["github_issue_url"],
            "replay_reused_spend": spend_replay["replayed"],
        },
        "accepted_verification": {
            "receipt_id": verification["receipt_id"],
            "candidate_commit": receipt["candidate_commit"],
            "accepted": receipt["accepted"],
            "verifier_id": receipt["verifier_id"],
            "verifier_digest": receipt["verifier_digest"],
            "backend_digest": receipt["backend_digest"],
            "policy_digest": receipt["policy_digest"],
            "result_digest": receipt["result_digest"],
        },
        "second_settlement": {
            "allocation_id": second_settlement["allocation_id"],
            "gateway_transfer_id": second_settlement["gateway_transfer_id"],
            "external_transfer_amount": second_settlement["external_transfer_amount"],
            "retained_operating_amount": second_settlement["retained_operating_amount"],
            "replay_reused_allocation": second_settlement_replay["replayed"],
        },
        "balances": balances,
    }
    evidence["evidence_digest"] = sha256_bytes(stable_json(evidence).encode("utf-8"))
    return evidence


def open_release_dogfood_market(db_path: Path) -> AgentBountyMarket:
    from .db import connect

    return AgentBountyMarket(
        connect(db_path),
        FakePaymentGateway(),
        ReleaseDogfoodVerifierRunner(),
    )


def _ensure_source_retained_credit(market: AgentBountyMarket) -> dict[str, Any]:
    project_id = RELEASE_DOGFOOD_SOURCE_PROJECT_ID
    market.create_project(project_id=project_id, name="Prior release candidate work", currency=RELEASE_DOGFOOD_CURRENCY)
    market.set_budget_policy(
        project_id=project_id,
        max_bounty_amount=RELEASE_DOGFOOD_REWARD_CENTS,
        monthly_budget=RELEASE_DOGFOOD_REWARD_CENTS,
        human_approval_threshold=RELEASE_DOGFOOD_REWARD_CENTS,
        allowed_issue_classes=["prior-release-candidate-work"],
    )
    market.fund_project(
        project_id=project_id,
        amount=RELEASE_DOGFOOD_REWARD_CENTS,
        currency=RELEASE_DOGFOOD_CURRENCY,
        idempotency_key="release-provenance-v2:fund-source",
    )
    market.create_bounty(
        bounty_id=RELEASE_DOGFOOD_SOURCE_BOUNTY_ID,
        project_id=project_id,
        title="Prior release candidate work retained-credit source",
        reward_amount=RELEASE_DOGFOOD_REWARD_CENTS,
        currency=RELEASE_DOGFOOD_CURRENCY,
        base_commit=DEFAULT_FINAL_COMMIT,
        issue_ref=f"{RELEASE_DOGFOOD_REPO}#19",
        verifier_id="prior_release_candidate_source_v1",
    )
    market.reserve_bounty(bounty_id=RELEASE_DOGFOOD_SOURCE_BOUNTY_ID, idempotency_key="release-provenance-v2:reserve-source")
    market.create_solver(
        solver_id=RELEASE_DOGFOOD_SOLVER_ID,
        display_name="Release Provenance Solver",
        idempotency_key="release-provenance-v2:solver",
    )
    market.claim_bounty(
        bounty_id=RELEASE_DOGFOOD_SOURCE_BOUNTY_ID,
        solver_id=RELEASE_DOGFOOD_SOLVER_ID,
        lease_expires_at="2026-07-01T00:00:00Z",
        idempotency_key="release-provenance-v2:claim-source",
    )
    source_submission = market.submit_candidate(
        bounty_id=RELEASE_DOGFOOD_SOURCE_BOUNTY_ID,
        solver_id=RELEASE_DOGFOOD_SOLVER_ID,
        candidate_repo_path="prior-release-candidate-record",
        candidate_commit=DEFAULT_FINAL_COMMIT,
        idempotency_key="release-provenance-v2:submission-source",
    )
    source_verification = market.run_verification(
        submission_id=source_submission["submission_id"],
        idempotency_key="release-provenance-v2:verify-source",
    )
    if not source_verification.get("receipt") or not source_verification["receipt"].get("accepted"):
        raise EconomicLoopError("source retained-credit bounty was not accepted")
    allocation = allocate_accepted_reward(
        market,
        bounty_id=RELEASE_DOGFOOD_SOURCE_BOUNTY_ID,
        external_transfer_amount=0,
        retained_operating_amount=RELEASE_DOGFOOD_REWARD_CENTS,
        platform_fee_amount=0,
        retention_consent=True,
        transfer_provider="fake",
        idempotency_key="release-provenance-v2:settle-source-retained",
    )
    allocation_replay = allocate_accepted_reward(
        market,
        bounty_id=RELEASE_DOGFOOD_SOURCE_BOUNTY_ID,
        external_transfer_amount=0,
        retained_operating_amount=RELEASE_DOGFOOD_REWARD_CENTS,
        platform_fee_amount=0,
        retention_consent=True,
        transfer_provider="fake",
        idempotency_key="release-provenance-v2:settle-source-retained",
    )
    return {"verification": source_verification, "allocation": allocation, "allocation_replay": allocation_replay}


def _accepted_source_result(*, bounty_id: str, candidate_commit: str) -> ProtectedVerificationResult:
    now = utc_now()
    result = {
        "schema": "protected-verifier-result-v1",
        "accepted": True,
        "verifier_id": "prior_release_candidate_source_v1",
        "verifier_version": "1.0.0",
        "metrics": {"source_bounty": bounty_id},
        "note": "prior accepted release-candidate work used only to create retained operating credit for issue #21 dogfood",
    }
    return ProtectedVerificationResult(
        accepted=True,
        metrics={"source_bounty": bounty_id},
        verifier_digest=sha256_bytes(stable_json(result).encode("utf-8")),
        backend="trusted-dogfood-source",
        backend_digest=sha256_bytes(b"trusted-dogfood-source"),
        policy_digest=sha256_bytes(f"source:{bounty_id}:{candidate_commit}".encode("utf-8")),
        stdout_sha256=sha256_bytes(stable_json(result).encode("utf-8")),
        stderr_sha256=sha256_bytes(b""),
        started_at=now,
        finished_at=now,
        result=result,
        returncode=0,
    )


def _git(repo: Path, *args: str, check: bool = True) -> str:
    completed = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if completed.returncode != 0:
        if check:
            raise ReleaseDogfoodError((completed.stderr or completed.stdout or "git failed").strip())
        return ""
    return completed.stdout.strip()
