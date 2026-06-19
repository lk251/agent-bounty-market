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
        existing = self.conn.execute(
            "SELECT id, gateway_event_id FROM funding_events WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        if existing:
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
        existing = self.conn.execute("SELECT id FROM claims WHERE idempotency_key = ?", (idempotency_key,)).fetchone()
        if existing:
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
        existing = self.conn.execute("SELECT id FROM submissions WHERE idempotency_key = ?", (idempotency_key,)).fetchone()
        if existing:
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
            SELECT r.id AS run_id, rc.id AS receipt_id, rc.receipt_json
            FROM verification_runs r
            LEFT JOIN verification_receipts rc ON rc.run_id = r.id
            WHERE r.idempotency_key = ?
            """,
            (idempotency_key,),
        ).fetchone()
        if existing:
            return {
                "run_id": existing["run_id"],
                "receipt_id": existing["receipt_id"],
                "receipt": self._decode(existing["receipt_json"], {}),
                "replayed": True,
            }
        submission = self.conn.execute("SELECT * FROM submissions WHERE id = ?", (submission_id,)).fetchone()
        if not submission:
            raise MarketError(f"unknown submission {submission_id}")
        bounty = self._bounty(submission["bounty_id"])
        if bounty["state"] != BountyState.SUBMITTED.value:
            raise MarketError(f"cannot verify submission from state {bounty['state']}")
        run_id = new_id("vrun")
        with self.conn:
            self._transition_bounty(submission["bounty_id"], BountyState.VERIFYING, reason="verification_started", idempotency_key=f"state:{idempotency_key}:verifying")
            self.conn.execute(
                """
                INSERT INTO verification_runs(id, bounty_id, submission_id, status, verifier_id, started_at, idempotency_key)
                VALUES (?, ?, ?, 'running', ?, ?, ?)
                """,
                (run_id, submission["bounty_id"], submission_id, bounty["verifier_id"], utc_now(), idempotency_key),
            )
        result = self.verifier.run(
            bounty_id=submission["bounty_id"],
            motoko_repo=Path(submission["candidate_repo_path"]),
            base_commit=bounty["base_commit"],
            candidate_commit=submission["candidate_commit"],
        )
        receipt = receipt_payload(
            bounty_id=submission["bounty_id"],
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
                    "accepted" if result.accepted else "rejected",
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
                    id, run_id, bounty_id, base_commit, candidate_commit, verifier_digest,
                    accepted, metrics_json, stdout_sha256, stderr_sha256, started_at, finished_at,
                    receipt_json, idempotency_key, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    receipt_id,
                    run_id,
                    submission["bounty_id"],
                    bounty["base_commit"],
                    submission["candidate_commit"],
                    result.verifier_digest,
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
        return {"run_id": run_id, "receipt_id": receipt_id, "receipt": receipt, "replayed": False}

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
        if bounty["state"] not in {BountyState.ACCEPTED.value, BountyState.PAYOUT_FAILED.value}:
            raise MarketError(f"cannot release payout from state {bounty['state']}")
        payout_id = existing["id"] if existing else new_id("payout")
        now = utc_now()
        try:
            with self.conn:
                if not existing:
                    self.conn.execute(
                        """
                        INSERT INTO payouts(id, bounty_id, solver_id, amount, currency, status, idempotency_key, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?)
                        """,
                        (
                            payout_id,
                            bounty_id,
                            submission["solver_id"],
                            int(bounty["reward_amount"]),
                            bounty["currency"],
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
            with self.conn:
                self.ledger.transfer(
                    event_type="payout_in_transit",
                    idempotency_key=f"ledger:{idempotency_key}:transit",
                    from_account=solver_earned_account(submission["solver_id"]),
                    to_account=solver_payout_transit_account(submission["solver_id"]),
                    amount=int(bounty["reward_amount"]),
                    currency=bounty["currency"],
                    project_id=bounty["project_id"],
                    bounty_id=bounty_id,
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
                    bounty_id=bounty_id,
                    solver_id=submission["solver_id"],
                    payout_id=payout_id,
                    external_id=gateway_payout.external_id,
                    prevent_negative_accounts={solver_payout_transit_account(submission["solver_id"])},
                )
                self.conn.execute(
                    "UPDATE payouts SET status = 'paid', gateway_payout_id = ?, updated_at = ? WHERE id = ?",
                    (gateway_payout.external_id, utc_now(), payout_id),
                )
                self._transition_bounty(bounty_id, BountyState.PAID, reason="payout_paid", idempotency_key=f"state:{idempotency_key}:paid")
            return {"payout_id": payout_id, "gateway_payout_id": gateway_payout.external_id, "replayed": False}
        except PaymentGatewayError as exc:
            with self.conn:
                self.conn.execute(
                    """
                    INSERT INTO payouts(id, bounty_id, solver_id, amount, currency, status, idempotency_key, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, 'failed', ?, ?, ?)
                    ON CONFLICT(bounty_id) DO UPDATE SET status = 'failed', updated_at = excluded.updated_at
                    """,
                    (
                        payout_id,
                        bounty_id,
                        submission["solver_id"],
                        int(bounty["reward_amount"]),
                        bounty["currency"],
                        idempotency_key,
                        now,
                        utc_now(),
                    ),
                )
                self._transition_bounty(bounty_id, BountyState.PAYOUT_FAILED, reason=f"payout_failed:{exc}", idempotency_key=f"state:{idempotency_key}:payout_failed")
            return {"payout_id": payout_id, "gateway_payout_id": None, "replayed": False, "failed": True, "error": str(exc)}

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
            "receipt": self._decode(receipt["receipt_json"], None) if receipt else None,
        }

    def ledger_rows(self) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM ledger_entries ORDER BY created_at, id").fetchall()
        return [dict(row) for row in rows]

    def _bounty(self, bounty_id: str) -> sqlite3.Row:
        row = self.conn.execute("SELECT * FROM bounties WHERE id = ?", (bounty_id,)).fetchone()
        if not row:
            raise MarketError(f"unknown bounty {bounty_id}")
        return row

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
