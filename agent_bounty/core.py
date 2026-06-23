from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path
from typing import Any

from .domain import BountyState
from .ledger import (
    Ledger,
    LedgerError,
    external_account,
    project_available_account,
    project_refunded_account,
    project_released_account,
    project_reserved_account,
    solver_earned_account,
    solver_paid_account,
    solver_payout_transit_account,
)
from .payments import PaymentGateway, PaymentGatewayError
from .state_machine import InvalidTransition, assert_transition
from .stripe_webhooks import StripeWebhookError, finish_stripe_webhook_event, record_stripe_webhook_event
from .util import require_currency, require_positive_amount, stable_json, utc_now
from .verification import ProtectedVerifierRunner, receipt_payload


class MarketError(RuntimeError):
    pass


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


class AgentBountyMarket:
    def __init__(self, conn: sqlite3.Connection, gateway: PaymentGateway, verifier: ProtectedVerifierRunner | None = None):
        self.conn = conn
        self.gateway = gateway
        self.verifier = verifier or ProtectedVerifierRunner()
        self.ledger = Ledger(conn)

    def create_project(self, *, project_id: str, name: str, currency: str = "USD") -> str:
        currency = require_currency(currency)
        now = utc_now()
        with self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO projects(id, name, created_at) VALUES (?, ?, ?)",
                (project_id, name, now),
            )
            self.conn.execute(
                "INSERT OR IGNORE INTO treasuries(project_id, currency) VALUES (?, ?)",
                (project_id, currency),
            )
        return project_id

    def set_budget_policy(
        self,
        *,
        project_id: str,
        max_bounty_amount: int,
        monthly_budget: int,
        human_approval_threshold: int,
        allowed_issue_classes: list[str] | tuple[str, ...],
    ) -> str:
        policy_id = f"policy_{project_id}"
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO budget_policies(
                    id, project_id, max_bounty_amount, monthly_budget,
                    human_approval_threshold, allowed_issue_classes_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    max_bounty_amount = excluded.max_bounty_amount,
                    monthly_budget = excluded.monthly_budget,
                    human_approval_threshold = excluded.human_approval_threshold,
                    allowed_issue_classes_json = excluded.allowed_issue_classes_json
                """,
                (
                    policy_id,
                    project_id,
                    int(max_bounty_amount),
                    int(monthly_budget),
                    int(human_approval_threshold),
                    stable_json(list(allowed_issue_classes)),
                ),
            )
        return policy_id

    def fund_project(
        self,
        *,
        project_id: str,
        amount: int,
        currency: str = "USD",
        idempotency_key: str,
    ) -> dict[str, Any]:
        require_positive_amount(amount)
        currency = require_currency(currency)
        treasury = self.conn.execute("SELECT currency FROM treasuries WHERE project_id = ?", (project_id,)).fetchone()
        if not treasury:
            raise MarketError(f"unknown project treasury {project_id}")
        if treasury["currency"] != currency:
            raise MarketError(f"funding currency {currency} does not match treasury currency {treasury['currency']}")
        existing = self.conn.execute(
            "SELECT id, project_id, amount, currency, gateway_event_id FROM funding_events WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        if existing:
            if existing["project_id"] != project_id or int(existing["amount"]) != amount or existing["currency"] != currency:
                raise MarketError("funding idempotency key was replayed with different arguments")
            return {"funding_event_id": existing["id"], "gateway_event_id": existing["gateway_event_id"], "replayed": True}
        credit = self.gateway.credit_project_treasury(
            project_id=project_id,
            amount=amount,
            currency=currency,
            idempotency_key=idempotency_key,
        )
        event_id = new_id("funding")
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO funding_events(id, project_id, amount, currency, gateway_event_id, idempotency_key, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (event_id, project_id, amount, currency, credit.external_id, idempotency_key, utc_now()),
            )
            self.ledger.transfer(
                event_type="project_funded",
                idempotency_key=f"ledger:{idempotency_key}",
                from_account=external_account("owner"),
                to_account=project_available_account(project_id),
                amount=amount,
                currency=currency,
                project_id=project_id,
                external_id=credit.external_id,
            )
        return {"funding_event_id": event_id, "gateway_event_id": credit.external_id, "replayed": False}

    def create_bounty(
        self,
        *,
        bounty_id: str,
        project_id: str,
        title: str,
        reward_amount: int,
        currency: str,
        base_commit: str,
        issue_ref: str,
        verifier_id: str,
    ) -> str:
        require_positive_amount(reward_amount)
        currency = require_currency(currency)
        existing = self.conn.execute("SELECT id FROM bounties WHERE id = ?", (bounty_id,)).fetchone()
        if existing:
            return bounty_id
        treasury = self.conn.execute("SELECT currency FROM treasuries WHERE project_id = ?", (project_id,)).fetchone()
        if not treasury:
            raise MarketError(f"unknown project treasury {project_id}")
        if treasury["currency"] != currency:
            raise MarketError(f"bounty currency {currency} does not match treasury currency {treasury['currency']}")
        now = utc_now()
        with self.conn:
            self.conn.execute(
                """
                INSERT OR IGNORE INTO bounties(
                    id, project_id, title, reward_amount, currency, state,
                    base_commit, issue_ref, verifier_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    bounty_id,
                    project_id,
                    title,
                    reward_amount,
                    currency,
                    BountyState.DRAFT.value,
                    base_commit,
                    issue_ref,
                    verifier_id,
                    now,
                    now,
                ),
            )
            self._transition_bounty(
                bounty_id,
                BountyState.AWAITING_FUNDING,
                reason="bounty_created",
                idempotency_key=f"state:{bounty_id}:awaiting_funding",
            )
        return bounty_id

    def reserve_bounty(self, *, bounty_id: str, idempotency_key: str) -> dict[str, Any]:
        bounty = self._bounty(bounty_id)
        existing_reserve = self.conn.execute(
            "SELECT id, state FROM bounties WHERE reserve_idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        if existing_reserve and existing_reserve["id"] != bounty_id:
            raise MarketError("reserve idempotency key belongs to a different bounty")
        if bounty["reserve_idempotency_key"] == idempotency_key and bounty["state"] in {
            BountyState.FUNDED.value,
            BountyState.OPEN.value,
            BountyState.CLAIMED.value,
            BountyState.SUBMITTED.value,
            BountyState.VERIFYING.value,
            BountyState.ACCEPTED.value,
            BountyState.PAYOUT_PENDING.value,
            BountyState.PAID.value,
        }:
            return {"bounty_id": bounty_id, "replayed": True, "state": bounty["state"]}
        if bounty["state"] != BountyState.AWAITING_FUNDING.value:
            raise MarketError(f"cannot reserve bounty from state {bounty['state']}")
        with self.conn:
            self.ledger.transfer(
                event_type="bounty_reserved",
                idempotency_key=f"ledger:{idempotency_key}",
                from_account=project_available_account(bounty["project_id"]),
                to_account=project_reserved_account(bounty["project_id"]),
                amount=int(bounty["reward_amount"]),
                currency=bounty["currency"],
                project_id=bounty["project_id"],
                bounty_id=bounty_id,
                prevent_negative_accounts={project_available_account(bounty["project_id"])},
            )
            self.conn.execute(
                "UPDATE bounties SET reserve_idempotency_key = ? WHERE id = ?",
                (idempotency_key, bounty_id),
            )
            self._transition_bounty(bounty_id, BountyState.FUNDED, reason="funds_reserved", idempotency_key=f"state:{idempotency_key}:funded")
            self._transition_bounty(bounty_id, BountyState.OPEN, reason="bounty_opened", idempotency_key=f"state:{idempotency_key}:open")
        return {"bounty_id": bounty_id, "replayed": False, "state": BountyState.OPEN.value}

    def create_solver(self, *, solver_id: str, display_name: str, idempotency_key: str) -> str:
        beneficiary = self.gateway.ensure_solver_beneficiary(solver_id=solver_id, idempotency_key=idempotency_key)
        with self.conn:
            self.conn.execute(
                """
                INSERT OR IGNORE INTO solver_identities(id, display_name, beneficiary_external_id, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (solver_id, display_name, beneficiary.external_id, utc_now()),
            )
        return solver_id

    def claim_bounty(self, *, bounty_id: str, solver_id: str, lease_expires_at: str, idempotency_key: str) -> dict[str, Any]:
        existing = self.conn.execute("SELECT id, bounty_id, solver_id FROM claims WHERE idempotency_key = ?", (idempotency_key,)).fetchone()
        if existing:
            if existing["bounty_id"] != bounty_id or existing["solver_id"] != solver_id:
                raise MarketError("claim idempotency key was replayed with different arguments")
            return {"claim_id": existing["id"], "replayed": True}
        bounty = self._bounty(bounty_id)
        if bounty["state"] != BountyState.OPEN.value:
            raise MarketError(f"cannot claim bounty from state {bounty['state']}")
        claim_id = new_id("claim")
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO claims(id, bounty_id, solver_id, status, lease_expires_at, idempotency_key, created_at)
                VALUES (?, ?, ?, 'active', ?, ?, ?)
                """,
                (claim_id, bounty_id, solver_id, lease_expires_at, idempotency_key, utc_now()),
            )
            self._transition_bounty(bounty_id, BountyState.CLAIMED, reason="solver_claimed", idempotency_key=f"state:{idempotency_key}:claimed")
        return {"claim_id": claim_id, "replayed": False}

    def submit_candidate(
        self,
        *,
        bounty_id: str,
        solver_id: str,
        candidate_repo_path: str,
        candidate_commit: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        existing = self.conn.execute(
            "SELECT id, bounty_id, solver_id, candidate_commit, candidate_repo_path FROM submissions WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        if existing:
            if (
                existing["bounty_id"] != bounty_id
                or existing["solver_id"] != solver_id
                or existing["candidate_commit"] != candidate_commit
                or existing["candidate_repo_path"] != candidate_repo_path
            ):
                raise MarketError("submission idempotency key was replayed with different arguments")
            return {"submission_id": existing["id"], "replayed": True}
        bounty = self._bounty(bounty_id)
        if bounty["state"] != BountyState.CLAIMED.value:
            raise MarketError(f"cannot submit candidate from state {bounty['state']}")
        claim = self.conn.execute(
            "SELECT id FROM claims WHERE bounty_id = ? AND solver_id = ? AND status = 'active'",
            (bounty_id, solver_id),
        ).fetchone()
        if not claim:
            raise MarketError("solver does not own an active claim for this bounty")
        submission_id = new_id("submission")
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO submissions(id, bounty_id, claim_id, solver_id, candidate_commit, candidate_repo_path, idempotency_key, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (submission_id, bounty_id, claim["id"], solver_id, candidate_commit, candidate_repo_path, idempotency_key, utc_now()),
            )
            self._transition_bounty(bounty_id, BountyState.SUBMITTED, reason="candidate_submitted", idempotency_key=f"state:{idempotency_key}:submitted")
        return {"submission_id": submission_id, "replayed": False}

    def run_verification(self, *, submission_id: str, idempotency_key: str) -> dict[str, Any]:
        existing = self.conn.execute(
            """
            SELECT r.*, rc.id AS receipt_id, rc.receipt_json
            FROM verification_runs r
            LEFT JOIN verification_receipts rc ON rc.run_id = r.id
            WHERE r.idempotency_key = ?
            """,
            (idempotency_key,),
        ).fetchone()
        if existing:
            if existing["submission_id"] != submission_id:
                raise MarketError("verification idempotency key was replayed for a different submission")
            if existing["receipt_id"]:
                return {
                    "run_id": existing["id"],
                    "receipt_id": existing["receipt_id"],
                    "receipt": self._decode(existing["receipt_json"], {}),
                    "status": existing["status"],
                    "replayed": True,
                }
        submission = self.conn.execute("SELECT * FROM submissions WHERE id = ?", (submission_id,)).fetchone()
        if not submission:
            raise MarketError(f"unknown submission {submission_id}")
        bounty = self._bounty(submission["bounty_id"])
        retrying_run = existing if existing and not existing["receipt_id"] else None
        allowed_start_states = {BountyState.SUBMITTED.value}
        if retrying_run:
            allowed_start_states.add(BountyState.VERIFYING.value)
        if bounty["state"] not in allowed_start_states:
            raise MarketError(f"cannot verify submission from state {bounty['state']}")
        run_id = retrying_run["id"] if retrying_run else new_id("vrun")
        started_at = utc_now()
        with self.conn:
            if bounty["state"] == BountyState.SUBMITTED.value:
                self._transition_bounty(
                    submission["bounty_id"],
                    BountyState.VERIFYING,
                    reason="verification_started",
                    idempotency_key=f"state:{idempotency_key}:verifying",
                )
            if retrying_run:
                self.conn.execute(
                    """
                    UPDATE verification_runs
                    SET status = 'running', started_at = ?, finished_at = NULL,
                        stdout_sha256 = NULL, stderr_sha256 = NULL, result_json = NULL,
                        heartbeat_at = ?, attempt = attempt + 1
                    WHERE id = ?
                    """,
                    (started_at, started_at, run_id),
                )
            else:
                self.conn.execute(
                    """
                    INSERT INTO verification_runs(
                        id, bounty_id, submission_id, status, verifier_id, started_at, heartbeat_at, idempotency_key
                    )
                    VALUES (?, ?, ?, 'running', ?, ?, ?, ?)
                    """,
                    (run_id, submission["bounty_id"], submission_id, bounty["verifier_id"], started_at, started_at, idempotency_key),
                )
        try:
            result = self.verifier.run(
                bounty_id=submission["bounty_id"],
                motoko_repo=Path(submission["candidate_repo_path"]),
                base_commit=bounty["base_commit"],
                candidate_commit=submission["candidate_commit"],
            )
        except Exception as exc:
            from .verification import ProtectedVerificationResult
            from .util import sha256_bytes

            finished_at = utc_now()
            result = ProtectedVerificationResult(
                accepted=False,
                metrics={},
                verifier_digest="sha256:verifier-runner-error",
                backend="runner",
                backend_digest="sha256:runner-error",
                policy_digest="sha256:runner-error",
                stdout_sha256=sha256_bytes(b""),
                stderr_sha256=sha256_bytes(str(exc).encode("utf-8")),
                started_at=started_at,
                finished_at=finished_at,
                result={
                    "schema": "protected-verifier-result-v1",
                    "accepted": False,
                    "error": f"{type(exc).__name__}: {exc}",
                },
                returncode=125,
            )
        status = self._verification_status(result)
        if status in {"error", "timed_out"}:
            with self.conn:
                self.conn.execute(
                    """
                    UPDATE verification_runs
                    SET status = ?, finished_at = ?, stdout_sha256 = ?, stderr_sha256 = ?,
                        result_json = ?, backend = ?, backend_digest = ?, policy_digest = ?
                    WHERE id = ?
                    """,
                    (
                        status,
                        result.finished_at,
                        result.stdout_sha256,
                        result.stderr_sha256,
                        stable_json(result.result),
                        result.backend,
                        result.backend_digest,
                        result.policy_digest,
                        run_id,
                    ),
                )
                current = self._bounty(submission["bounty_id"])
                if current["state"] == BountyState.VERIFYING.value:
                    self._transition_bounty(
                        submission["bounty_id"],
                        BountyState.SUBMITTED,
                        reason=f"verification_{status}",
                        idempotency_key=f"state:{idempotency_key}:{status}:submitted",
                    )
            return {"run_id": run_id, "receipt_id": None, "receipt": None, "status": status, "replayed": False}
        receipt = receipt_payload(
            bounty_id=submission["bounty_id"],
            project_id=bounty["project_id"],
            issue_ref=bounty["issue_ref"],
            submission_id=submission_id,
            solver_id=submission["solver_id"],
            candidate_repo_path=submission["candidate_repo_path"],
            verifier_id=bounty["verifier_id"],
            base_commit=bounty["base_commit"],
            candidate_commit=submission["candidate_commit"],
            result=result,
        )
        receipt_id = new_id("receipt")
        with self.conn:
            self.conn.execute(
                """
                UPDATE verification_runs
                SET status = ?, finished_at = ?, stdout_sha256 = ?, stderr_sha256 = ?, result_json = ?
                WHERE id = ?
                """,
                (
                    status,
                    result.finished_at,
                    result.stdout_sha256,
                    result.stderr_sha256,
                    stable_json(result.result),
                    run_id,
                ),
            )
            self.conn.execute(
                """
                INSERT INTO verification_receipts(
                    id, run_id, bounty_id, project_id, issue_ref, submission_id, solver_id,
                    candidate_repo_path, verifier_id, base_commit, candidate_commit, verifier_digest,
                    backend, backend_digest, policy_digest, accepted, metrics_json, stdout_sha256,
                    stderr_sha256, started_at, finished_at, receipt_json, idempotency_key, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    receipt_id,
                    run_id,
                    submission["bounty_id"],
                    bounty["project_id"],
                    bounty["issue_ref"],
                    submission_id,
                    submission["solver_id"],
                    submission["candidate_repo_path"],
                    bounty["verifier_id"],
                    bounty["base_commit"],
                    submission["candidate_commit"],
                    result.verifier_digest,
                    result.backend,
                    result.backend_digest,
                    result.policy_digest,
                    1 if result.accepted else 0,
                    stable_json(result.metrics),
                    result.stdout_sha256,
                    result.stderr_sha256,
                    result.started_at,
                    result.finished_at,
                    stable_json(receipt),
                    f"receipt:{idempotency_key}",
                    utc_now(),
                ),
            )
            if result.accepted:
                self.ledger.transfer(
                    event_type="bounty_accepted_release",
                    idempotency_key=f"ledger:{idempotency_key}:release",
                    from_account=project_reserved_account(bounty["project_id"]),
                    to_account=solver_earned_account(submission["solver_id"]),
                    amount=int(bounty["reward_amount"]),
                    currency=bounty["currency"],
                    project_id=bounty["project_id"],
                    bounty_id=submission["bounty_id"],
                    solver_id=submission["solver_id"],
                    prevent_negative_accounts={project_reserved_account(bounty["project_id"])},
                )
                self._transition_bounty(submission["bounty_id"], BountyState.ACCEPTED, reason="verification_accepted", idempotency_key=f"state:{idempotency_key}:accepted")
                self.conn.execute("UPDATE bounties SET accepted_receipt_id = ? WHERE id = ?", (receipt_id, submission["bounty_id"]))
            else:
                self._transition_bounty(submission["bounty_id"], BountyState.REJECTED, reason="verification_rejected", idempotency_key=f"state:{idempotency_key}:rejected")
        return {"run_id": run_id, "receipt_id": receipt_id, "receipt": receipt, "status": status, "replayed": False}

    def cancel_bounty(self, *, bounty_id: str, idempotency_key: str, reason: str = "cancelled") -> dict[str, Any]:
        bounty = self._bounty(bounty_id)
        if bounty["state"] == BountyState.CANCELLED.value:
            return {"bounty_id": bounty_id, "state": BountyState.CANCELLED.value, "replayed": True}
        with self.conn:
            self._transition_bounty(
                bounty_id,
                BountyState.CANCELLED,
                reason=reason,
                idempotency_key=f"state:{idempotency_key}:cancelled",
            )
        return {"bounty_id": bounty_id, "state": BountyState.CANCELLED.value, "replayed": False}

    def expire_bounty(self, *, bounty_id: str, idempotency_key: str) -> dict[str, Any]:
        bounty = self._bounty(bounty_id)
        if bounty["state"] == BountyState.EXPIRED.value:
            return {"bounty_id": bounty_id, "state": BountyState.EXPIRED.value, "replayed": True}
        with self.conn:
            self._transition_bounty(
                bounty_id,
                BountyState.EXPIRED,
                reason="expired",
                idempotency_key=f"state:{idempotency_key}:expired",
            )
        return {"bounty_id": bounty_id, "state": BountyState.EXPIRED.value, "replayed": False}

    def refund_bounty(self, *, bounty_id: str, idempotency_key: str) -> dict[str, Any]:
        bounty = self._bounty(bounty_id)
        if bounty["state"] == BountyState.REFUNDED.value:
            return {"bounty_id": bounty_id, "state": BountyState.REFUNDED.value, "replayed": True}
        amount = int(bounty["reward_amount"])
        source_account = project_reserved_account(bounty["project_id"])
        if bounty["state"] == BountyState.PAYOUT_FAILED.value:
            submission = self.conn.execute(
                "SELECT * FROM submissions WHERE bounty_id = ? ORDER BY created_at DESC LIMIT 1",
                (bounty_id,),
            ).fetchone()
            if not submission:
                raise MarketError("cannot refund payout_failed bounty without a submission")
            source_account = solver_earned_account(submission["solver_id"])
        with self.conn:
            if self.ledger.balance(source_account, bounty["currency"]) >= amount:
                self.ledger.transfer(
                    event_type="bounty_refunded",
                    idempotency_key=f"ledger:{idempotency_key}:refund",
                    from_account=source_account,
                    to_account=project_refunded_account(bounty["project_id"]),
                    amount=amount,
                    currency=bounty["currency"],
                    project_id=bounty["project_id"],
                    bounty_id=bounty_id,
                    prevent_negative_accounts={source_account},
                )
            self._transition_bounty(
                bounty_id,
                BountyState.REFUNDED,
                reason="bounty_refunded",
                idempotency_key=f"state:{idempotency_key}:refunded",
            )
        return {"bounty_id": bounty_id, "state": BountyState.REFUNDED.value, "replayed": False}

    def release_payout(self, *, bounty_id: str, idempotency_key: str) -> dict[str, Any]:
        existing = self.conn.execute("SELECT * FROM payouts WHERE bounty_id = ?", (bounty_id,)).fetchone()
        bounty = self._bounty(bounty_id)
        submission = self.conn.execute(
            "SELECT * FROM submissions WHERE bounty_id = ? ORDER BY created_at DESC LIMIT 1",
            (bounty_id,),
        ).fetchone()
        if not submission:
            raise MarketError("cannot release payout without a submission")
        if existing and existing["status"] == "paid":
            return {"payout_id": existing["id"], "gateway_payout_id": existing["gateway_payout_id"], "replayed": True}
        if existing and existing["status"] == "pending" and bounty["state"] == BountyState.PAYOUT_PENDING.value:
            return {
                "payout_id": existing["id"],
                "gateway_payout_id": existing["gateway_payout_id"],
                "replayed": True,
                "pending": True,
            }
        if bounty["state"] not in {BountyState.ACCEPTED.value, BountyState.PAYOUT_FAILED.value}:
            raise MarketError(f"cannot release payout from state {bounty['state']}")
        receipt = self._accepted_receipt_for_payout(bounty, submission)
        payout_id = existing["id"] if existing else new_id("payout")
        now = utc_now()
        try:
            with self.conn:
                if not existing:
                    self.conn.execute(
                        """
                        INSERT INTO payouts(
                            id, bounty_id, solver_id, amount, currency, status,
                            accepted_receipt_id, verifier_digest, idempotency_key, created_at, updated_at
                        )
                        VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?)
                        """,
                        (
                            payout_id,
                            bounty_id,
                            submission["solver_id"],
                            int(bounty["reward_amount"]),
                            bounty["currency"],
                            receipt["id"],
                            receipt["verifier_digest"],
                            idempotency_key,
                            now,
                            now,
                        ),
                    )
                self._transition_bounty(bounty_id, BountyState.PAYOUT_PENDING, reason="payout_release_started", idempotency_key=f"state:{idempotency_key}:payout_pending")
            gateway_payout = self.gateway.release_payout(
                payout_id=payout_id,
                solver_id=submission["solver_id"],
                amount=int(bounty["reward_amount"]),
                currency=bounty["currency"],
                idempotency_key=idempotency_key,
            )
            if gateway_payout.status == "pending":
                with self.conn:
                    self.conn.execute(
                        "UPDATE payouts SET status = 'pending', gateway_payout_id = ?, updated_at = ? WHERE id = ?",
                        (gateway_payout.external_id, utc_now(), payout_id),
                    )
                return {
                    "payout_id": payout_id,
                    "gateway_payout_id": gateway_payout.external_id,
                    "replayed": False,
                    "pending": True,
                }
            if gateway_payout.status == "failed":
                raise PaymentGatewayError(f"gateway payout failed for {gateway_payout.external_id}")
            if gateway_payout.status != "paid":
                raise PaymentGatewayError(f"gateway returned unsupported payout status {gateway_payout.status}")
            self._complete_payout(
                bounty=bounty,
                submission=submission,
                payout_id=payout_id,
                gateway_payout_id=gateway_payout.external_id,
                idempotency_key=idempotency_key,
            )
            return {"payout_id": payout_id, "gateway_payout_id": gateway_payout.external_id, "replayed": False}
        except PaymentGatewayError as exc:
            with self.conn:
                self.conn.execute(
                    """
                    INSERT INTO payouts(
                        id, bounty_id, solver_id, amount, currency, status,
                        accepted_receipt_id, verifier_digest, idempotency_key, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, 'failed', ?, ?, ?, ?, ?)
                    ON CONFLICT(bounty_id) DO UPDATE SET status = 'failed', updated_at = excluded.updated_at
                    """,
                    (
                        payout_id,
                        bounty_id,
                        submission["solver_id"],
                        int(bounty["reward_amount"]),
                        bounty["currency"],
                        receipt["id"],
                        receipt["verifier_digest"],
                        idempotency_key,
                        now,
                        utc_now(),
                    ),
                )
                self._transition_bounty(bounty_id, BountyState.PAYOUT_FAILED, reason=f"payout_failed:{exc}", idempotency_key=f"state:{idempotency_key}:payout_failed")
            return {"payout_id": payout_id, "gateway_payout_id": None, "replayed": False, "failed": True, "error": str(exc)}

    def ingest_stripe_webhook(
        self,
        *,
        payload: bytes,
        signature_header: str,
        endpoint_secret: str,
        now: int | None = None,
        tolerance_seconds: int = 300,
    ) -> dict[str, Any]:
        recorded = record_stripe_webhook_event(
            self.conn,
            payload=payload,
            signature_header=signature_header,
            endpoint_secret=endpoint_secret,
            now=now,
            tolerance_seconds=tolerance_seconds,
        )
        if recorded["replayed"]:
            return {
                "event_id": recorded["event_id"],
                "event_type": recorded["event_type"],
                "replayed": True,
                "status": recorded["status"],
                "action": recorded["action"],
            }
        event = recorded["event"]
        event_id = recorded["event_id"]
        event_type = recorded["event_type"]
        try:
            action = self._apply_stripe_event(event_id=event_id, event_type=event_type, event=event)
            finish_stripe_webhook_event(self.conn, event_id=event_id, status="processed", action=action)
            return {
                "event_id": event_id,
                "event_type": event_type,
                "replayed": False,
                "status": "processed",
                "action": action,
            }
        except (MarketError, StripeWebhookError) as exc:
            finish_stripe_webhook_event(self.conn, event_id=event_id, status="failed", error=str(exc))
            raise

    def reconciliation(self, *, project_id: str, solver_id: str, currency: str = "USD") -> dict[str, Any]:
        currency = require_currency(currency)
        accounts = {
            "project_available": project_available_account(project_id),
            "project_reserved": project_reserved_account(project_id),
            "project_released": project_released_account(project_id),
            "project_refunded": project_refunded_account(project_id),
            "solver_earned": solver_earned_account(solver_id),
            "solver_payout_transit": solver_payout_transit_account(solver_id),
            "solver_paid": solver_paid_account(solver_id),
        }
        balances = self.ledger.balances(accounts.values(), currency)
        named = {name: balances[account] for name, account in accounts.items()}
        internal_total = sum(named.values())
        funding = self.conn.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM funding_events WHERE project_id = ? AND currency = ?",
            (project_id, currency),
        ).fetchone()[0]
        ok = internal_total == int(funding) and all(value >= 0 for value in named.values())
        return {"currency": currency, "balances": named, "funding_total": int(funding), "internal_total": internal_total, "ok": ok}

    def bounty_summary(self, bounty_id: str) -> dict[str, Any]:
        bounty = self._bounty(bounty_id)
        payout = self.conn.execute("SELECT * FROM payouts WHERE bounty_id = ?", (bounty_id,)).fetchone()
        receipt = self.conn.execute(
            "SELECT * FROM verification_receipts WHERE bounty_id = ? ORDER BY created_at DESC LIMIT 1",
            (bounty_id,),
        ).fetchone()
        return {
            "bounty_id": bounty_id,
            "state": bounty["state"],
            "reward_amount": int(bounty["reward_amount"]),
            "currency": bounty["currency"],
            "payout_id": payout["id"] if payout else None,
            "gateway_payout_id": payout["gateway_payout_id"] if payout else None,
            "accepted_receipt_id": payout["accepted_receipt_id"] if payout else None,
            "verifier_digest": payout["verifier_digest"] if payout else None,
            "receipt": self._decode(receipt["receipt_json"], None) if receipt else None,
        }

    def ledger_rows(self) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM ledger_entries ORDER BY created_at, id").fetchall()
        return [dict(row) for row in rows]

    def stripe_webhook_rows(self) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM stripe_webhook_events ORDER BY received_at, event_id").fetchall()
        return [dict(row) for row in rows]

    def mark_gateway_payout_paid(self, *, gateway_payout_id: str, idempotency_key: str) -> dict[str, Any]:
        payout = self.conn.execute("SELECT * FROM payouts WHERE gateway_payout_id = ?", (gateway_payout_id,)).fetchone()
        if not payout:
            return {"gateway_payout_id": gateway_payout_id, "action": "ignored_unknown_payout"}
        if payout["status"] == "paid":
            return {"payout_id": payout["id"], "gateway_payout_id": gateway_payout_id, "replayed": True, "action": "already_paid"}
        if payout["status"] == "failed":
            return {"payout_id": payout["id"], "gateway_payout_id": gateway_payout_id, "action": "ignored_failed_payout"}
        bounty = self._bounty(payout["bounty_id"])
        submission = self.conn.execute(
            "SELECT * FROM submissions WHERE bounty_id = ? AND solver_id = ? ORDER BY created_at DESC LIMIT 1",
            (payout["bounty_id"], payout["solver_id"]),
        ).fetchone()
        if not submission:
            raise MarketError("cannot mark payout paid without a submission")
        self._complete_payout(
            bounty=bounty,
            submission=submission,
            payout_id=payout["id"],
            gateway_payout_id=gateway_payout_id,
            idempotency_key=idempotency_key,
        )
        return {"payout_id": payout["id"], "gateway_payout_id": gateway_payout_id, "replayed": False, "action": "paid"}

    def mark_gateway_payout_failed(self, *, gateway_payout_id: str, reason: str, idempotency_key: str) -> dict[str, Any]:
        payout = self.conn.execute("SELECT * FROM payouts WHERE gateway_payout_id = ?", (gateway_payout_id,)).fetchone()
        if not payout:
            return {"gateway_payout_id": gateway_payout_id, "action": "ignored_unknown_payout"}
        if payout["status"] == "paid":
            return {"payout_id": payout["id"], "gateway_payout_id": gateway_payout_id, "action": "ignored_paid_payout"}
        if payout["status"] == "failed":
            return {"payout_id": payout["id"], "gateway_payout_id": gateway_payout_id, "replayed": True, "action": "already_failed"}
        with self.conn:
            self.conn.execute("UPDATE payouts SET status = 'failed', updated_at = ? WHERE id = ?", (utc_now(), payout["id"]))
            bounty = self._bounty(payout["bounty_id"])
            if bounty["state"] == BountyState.PAYOUT_PENDING.value:
                self._transition_bounty(
                    payout["bounty_id"],
                    BountyState.PAYOUT_FAILED,
                    reason=f"stripe_payout_failed:{reason}",
                    idempotency_key=f"state:{idempotency_key}:payout_failed",
                )
        return {"payout_id": payout["id"], "gateway_payout_id": gateway_payout_id, "replayed": False, "action": "failed"}

    def _complete_payout(
        self,
        *,
        bounty: sqlite3.Row,
        submission: sqlite3.Row,
        payout_id: str,
        gateway_payout_id: str,
        idempotency_key: str,
    ) -> None:
        with self.conn:
            self.ledger.transfer(
                event_type="payout_in_transit",
                idempotency_key=f"ledger:{idempotency_key}:transit",
                from_account=solver_earned_account(submission["solver_id"]),
                to_account=solver_payout_transit_account(submission["solver_id"]),
                amount=int(bounty["reward_amount"]),
                currency=bounty["currency"],
                project_id=bounty["project_id"],
                bounty_id=bounty["id"],
                solver_id=submission["solver_id"],
                payout_id=payout_id,
                prevent_negative_accounts={solver_earned_account(submission["solver_id"])},
            )
            self.ledger.transfer(
                event_type="payout_paid",
                idempotency_key=f"ledger:{idempotency_key}:paid",
                from_account=solver_payout_transit_account(submission["solver_id"]),
                to_account=solver_paid_account(submission["solver_id"]),
                amount=int(bounty["reward_amount"]),
                currency=bounty["currency"],
                project_id=bounty["project_id"],
                bounty_id=bounty["id"],
                solver_id=submission["solver_id"],
                payout_id=payout_id,
                external_id=gateway_payout_id,
                prevent_negative_accounts={solver_payout_transit_account(submission["solver_id"])},
            )
            self.conn.execute(
                "UPDATE payouts SET status = 'paid', gateway_payout_id = ?, updated_at = ? WHERE id = ?",
                (gateway_payout_id, utc_now(), payout_id),
            )
            self._transition_bounty(
                bounty["id"],
                BountyState.PAID,
                reason="payout_paid",
                idempotency_key=f"state:{idempotency_key}:paid",
            )

    def _apply_stripe_event(self, *, event_id: str, event_type: str, event: dict[str, Any]) -> str:
        data = event.get("data")
        obj = data.get("object") if isinstance(data, dict) else None
        if not isinstance(obj, dict):
            return "ignored_missing_object"
        external_id = obj.get("id")
        if not isinstance(external_id, str) or not external_id:
            return "ignored_missing_object_id"
        if event_type in {"transfer.created", "transfer.succeeded", "transfer.paid"}:
            result = self.mark_gateway_payout_paid(
                gateway_payout_id=external_id,
                idempotency_key=f"stripe-webhook:{event_id}:paid",
            )
            return str(result["action"])
        if event_type in {"transfer.failed", "payout.failed"}:
            failure = obj.get("failure_message") or obj.get("failure_code") or event_type
            result = self.mark_gateway_payout_failed(
                gateway_payout_id=external_id,
                reason=str(failure),
                idempotency_key=f"stripe-webhook:{event_id}:failed",
            )
            return str(result["action"])
        return f"ignored_{event_type}"

    def _bounty(self, bounty_id: str) -> sqlite3.Row:
        row = self.conn.execute("SELECT * FROM bounties WHERE id = ?", (bounty_id,)).fetchone()
        if not row:
            raise MarketError(f"unknown bounty {bounty_id}")
        return row

    def _accepted_receipt_for_payout(self, bounty: sqlite3.Row, submission: sqlite3.Row) -> sqlite3.Row:
        receipt_id = bounty["accepted_receipt_id"]
        if not receipt_id:
            raise MarketError("cannot release payout without an accepted receipt")
        receipt = self.conn.execute("SELECT * FROM verification_receipts WHERE id = ?", (receipt_id,)).fetchone()
        if not receipt:
            raise MarketError("accepted receipt is missing")
        if int(receipt["accepted"]) != 1:
            raise MarketError("accepted receipt did not accept the candidate")
        if receipt["bounty_id"] != bounty["id"]:
            raise MarketError("accepted receipt belongs to a different bounty")
        if receipt["submission_id"] != submission["id"]:
            raise MarketError("accepted receipt belongs to a different submission")
        if receipt["solver_id"] != submission["solver_id"]:
            raise MarketError("accepted receipt belongs to a different solver")
        if receipt["candidate_commit"] != submission["candidate_commit"]:
            raise MarketError("accepted receipt candidate commit does not match submission")
        if receipt["candidate_repo_path"] != submission["candidate_repo_path"]:
            raise MarketError("accepted receipt candidate repo does not match submission")
        if receipt["base_commit"] != bounty["base_commit"]:
            raise MarketError("accepted receipt base commit does not match bounty")
        if receipt["issue_ref"] != bounty["issue_ref"]:
            raise MarketError("accepted receipt issue does not match bounty")
        if receipt["verifier_id"] != bounty["verifier_id"]:
            raise MarketError("accepted receipt verifier does not match bounty")
        if not receipt["backend_digest"] or not receipt["policy_digest"]:
            raise MarketError("accepted receipt is missing backend or policy digest")
        payload = self._decode(receipt["receipt_json"], {})
        if payload.get("backend_digest") != receipt["backend_digest"]:
            raise MarketError("accepted receipt backend digest does not match payload")
        if payload.get("policy_digest") != receipt["policy_digest"]:
            raise MarketError("accepted receipt policy digest does not match payload")
        return receipt

    @staticmethod
    def _verification_status(result: Any) -> str:
        if result.accepted:
            return "accepted"
        error = result.result.get("error") if isinstance(result.result, dict) else None
        failure_reasons = result.result.get("failure_reasons") if isinstance(result.result, dict) else None
        if result.returncode == 124 or (isinstance(error, str) and "timed out" in error.lower()):
            return "timed_out"
        if error and not failure_reasons:
            return "error"
        return "rejected"

    def _transition_bounty(self, bounty_id: str, target: BountyState, *, reason: str, idempotency_key: str) -> None:
        bounty = self._bounty(bounty_id)
        current = BountyState(bounty["state"])
        if current == target:
            self.conn.execute(
                """
                INSERT OR IGNORE INTO state_events(id, bounty_id, from_state, to_state, reason, idempotency_key, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (new_id("state"), bounty_id, current.value, target.value, reason, idempotency_key, utc_now()),
            )
            return
        assert_transition(current, target)
        self.conn.execute(
            "UPDATE bounties SET state = ?, updated_at = ? WHERE id = ?",
            (target.value, utc_now(), bounty_id),
        )
        self.conn.execute(
            """
            INSERT OR IGNORE INTO state_events(id, bounty_id, from_state, to_state, reason, idempotency_key, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (new_id("state"), bounty_id, current.value, target.value, reason, idempotency_key, utc_now()),
        )

    @staticmethod
    def _decode(value: str | None, default: Any) -> Any:
        if value is None:
            return default
        import json

        return json.loads(value)
