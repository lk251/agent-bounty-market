from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .core import AgentBountyMarket, new_id
from .domain import BountyState
from .github_integration import FakeGitHubClient, github_publish_bounty_contract
from .ledger import (
    LedgerError,
    platform_fee_account,
    project_available_account,
    solver_earned_account,
    solver_operating_available_account,
    solver_paid_account,
    solver_payout_transit_account,
)
from .project_agent import DEFAULT_BASE_COMMIT, DEFAULT_REPO
from .solver_agent import (
    PYTHON_SOLVER_ID,
    execute_deterministic_motoko_replay,
    register_default_solver_profiles,
    run_demo_solver_motoko,
    submit_solver_replay,
)
from .stripe_sandbox import (
    StripeClient,
    StripeSandboxConfig,
    request_digest,
    require_id,
    safe_error_message,
    transfer_params,
)
from .util import require_currency, require_positive_amount, sha256_text, stable_json, utc_now


ECONOMIC_LOOP_STATUS_SCHEMA = "agent-bounty-economic-loop-status-v1"
SETTLEMENT_POLICY_SCHEMA = "agent-bounty-settlement-policy-v1"
SETTLEMENT_ALLOCATION_SCHEMA = "agent-bounty-settlement-allocation-v1"
SOLVER_OPERATING_POLICY_SCHEMA = "agent-bounty-solver-operating-policy-v1"
SOLVER_OPERATING_SPEND_SCHEMA = "agent-bounty-solver-operating-spend-v1"
ECONOMIC_LOOP_DEMO_SCHEMA = "agent-bounty-demo-economic-loop-v1"
ECONOMIC_LOOP_LIVE_SCHEMA = "agent-bounty-demo-economic-loop-live-v1"

DEFAULT_FIRST_BOUNTY_ID = "bounty_motoko_issue_1"
DEFAULT_SECOND_PROJECT_ID = "project_motoko_retained_credit"
DEFAULT_SECOND_BOUNTY_ID = "bounty_retained_credit_followup"
DEFAULT_SECOND_VERIFIER_ID = "economic_loop_fixture_verifier_v1"

REAL_STRIPE_EVIDENCE = {
    "source": "docs/chatgpt-pro-stripe-blocker-report.md",
    "database": ".demo/stripe-final2.sqlite3",
    "payment_intent": "pi_3Tleim2MCkccMoa914w0sD0C",
    "charge": "ch_3Tleim2MCkccMoa91pVUsdmF",
    "funding_event": "evt_3Tleim2MCkccMoa91oxQFSP4",
    "connected_account": "acct_1TlaGA2MCkdsU43l",
    "transfer": "tr_3Tleim2MCkccMoa91ZC6yBOQ",
    "transfer_audit_event": "evt_3Tleim2MCkccMoa91tozrj04",
    "currency": "EUR",
    "note": "prior real sandbox full-transfer evidence; split settlement demo is deterministic unless explicitly wired to real credentials",
}


class EconomicLoopError(RuntimeError):
    pass


def _stable_id(prefix: str, payload: Any) -> str:
    return f"{prefix}_{sha256_text(stable_json(payload))[-24:]}"


def _json_row(row: Any | None, key: str, default: Any) -> Any:
    if not row:
        return default
    value = row[key]
    return json.loads(value) if value else default


def _nonnegative(name: str, value: int) -> int:
    value = int(value)
    if value < 0:
        raise EconomicLoopError(f"{name} must be non-negative")
    return value


def default_settlement_policy(
    *,
    solver_id: str,
    reward_amount: int = 2500,
    currency: str = "USD",
    external_transfer_amount: int | None = None,
    retained_operating_amount: int = 0,
    platform_fee_amount: int = 0,
    retention_consent: bool = False,
) -> dict[str, Any]:
    require_positive_amount(reward_amount)
    currency = require_currency(currency)
    retained_operating_amount = _nonnegative("retained_operating_amount", retained_operating_amount)
    platform_fee_amount = _nonnegative("platform_fee_amount", platform_fee_amount)
    if not retention_consent and retained_operating_amount:
        raise EconomicLoopError("retained operating credit requires explicit operator consent")
    if external_transfer_amount is None:
        external_transfer_amount = reward_amount - retained_operating_amount - platform_fee_amount
    external_transfer_amount = _nonnegative("external_transfer_amount", external_transfer_amount)
    if external_transfer_amount + retained_operating_amount + platform_fee_amount != reward_amount:
        raise EconomicLoopError("settlement split must sum exactly to reward_amount")
    return {
        "schema": SETTLEMENT_POLICY_SCHEMA,
        "solver_id": solver_id,
        "reward_amount": reward_amount,
        "currency": currency,
        "external_transfer_amount": external_transfer_amount,
        "retained_operating_amount": retained_operating_amount,
        "platform_fee_amount": platform_fee_amount,
        "retention_consent": bool(retention_consent),
        "consent_text": "operator permits retained operating credit" if retention_consent else "default full external transfer",
    }


def save_settlement_policy(market: AgentBountyMarket, policy: dict[str, Any], *, idempotency_key: str | None = None) -> dict[str, Any]:
    if policy.get("schema") != SETTLEMENT_POLICY_SCHEMA:
        raise EconomicLoopError("settlement policy schema mismatch")
    solver_id = str(policy.get("solver_id") or "")
    if not solver_id:
        raise EconomicLoopError("settlement policy missing solver_id")
    digest = sha256_text(stable_json(policy))
    policy_id = _stable_id("settle_policy", {"solver_id": solver_id, "digest": digest})
    now = utc_now()
    key = idempotency_key or f"settlement-policy:{solver_id}:{digest}"
    with market.conn:
        market.conn.execute(
            """
            INSERT INTO settlement_policies(id, solver_id, policy_json, policy_digest, created_at, updated_at, idempotency_key)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(idempotency_key) DO UPDATE SET
                policy_json = excluded.policy_json,
                policy_digest = excluded.policy_digest,
                updated_at = excluded.updated_at
            """,
            (policy_id, solver_id, stable_json(policy), digest, now, now, key),
        )
    return {"policy_id": policy_id, "policy_digest": digest, "policy": policy}


def default_solver_operating_policy(
    *,
    solver_id: str,
    allowed_projects: list[str] | None = None,
    allowed_repositories: list[str] | None = None,
    allowed_issue_classes: list[str] | None = None,
    required_verifier_ids: list[str] | None = None,
    max_spend_cents: int = 500,
    human_approval_threshold_cents: int = 500,
    minimum_remaining_reserve_cents: int = 0,
    allowed_currencies: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "schema": SOLVER_OPERATING_POLICY_SCHEMA,
        "solver_id": solver_id,
        "allowed_projects": allowed_projects or [DEFAULT_SECOND_PROJECT_ID],
        "allowed_repositories": allowed_repositories or [DEFAULT_REPO],
        "allowed_issue_classes": allowed_issue_classes or ["machine-verifiable-tui-regression"],
        "required_verifier_ids": required_verifier_ids or [DEFAULT_SECOND_VERIFIER_ID],
        "allowed_currencies": [require_currency(currency) for currency in (allowed_currencies or ["USD"])],
        "max_spend_cents": int(max_spend_cents),
        "human_approval_threshold_cents": int(human_approval_threshold_cents),
        "minimum_remaining_reserve_cents": int(minimum_remaining_reserve_cents),
        "publication_mode": "fake-github-contract",
        "trusted_policy_owner": "agent-bounty-market",
    }


def save_solver_operating_policy(market: AgentBountyMarket, policy: dict[str, Any]) -> dict[str, Any]:
    if policy.get("schema") != SOLVER_OPERATING_POLICY_SCHEMA:
        raise EconomicLoopError("solver operating policy schema mismatch")
    solver_id = str(policy.get("solver_id") or "")
    if not solver_id:
        raise EconomicLoopError("solver operating policy missing solver_id")
    digest = sha256_text(stable_json(policy))
    policy_id = f"sop_{solver_id}"
    now = utc_now()
    with market.conn:
        market.conn.execute(
            """
            INSERT INTO solver_operating_policies(id, solver_id, policy_json, policy_digest, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                policy_json = excluded.policy_json,
                policy_digest = excluded.policy_digest,
                updated_at = excluded.updated_at
            """,
            (policy_id, solver_id, stable_json(policy), digest, now, now),
        )
    return {"policy_id": policy_id, "policy_digest": digest, "policy": policy}


def load_solver_operating_policy(market: AgentBountyMarket, *, solver_id: str) -> dict[str, Any]:
    row = market.conn.execute(
        "SELECT policy_json FROM solver_operating_policies WHERE solver_id = ? ORDER BY updated_at DESC LIMIT 1",
        (solver_id,),
    ).fetchone()
    if not row:
        raise EconomicLoopError(f"no solver operating policy for solver {solver_id}")
    return json.loads(row["policy_json"])


def _accepted_context(market: AgentBountyMarket, bounty_id: str) -> dict[str, Any]:
    bounty = market.conn.execute("SELECT * FROM bounties WHERE id = ?", (bounty_id,)).fetchone()
    if not bounty:
        raise EconomicLoopError(f"unknown bounty {bounty_id}")
    if bounty["state"] not in {BountyState.ACCEPTED.value, BountyState.PAYOUT_FAILED.value, BountyState.PAYOUT_PENDING.value, BountyState.PAID.value}:
        raise EconomicLoopError(f"cannot settle bounty from state {bounty['state']}")
    receipt_id = bounty["accepted_receipt_id"]
    if not receipt_id:
        raise EconomicLoopError("bounty has no accepted receipt")
    receipt = market.conn.execute("SELECT * FROM verification_receipts WHERE id = ?", (receipt_id,)).fetchone()
    if not receipt or int(receipt["accepted"]) != 1:
        raise EconomicLoopError("accepted receipt is missing or not accepted")
    submission = market.conn.execute(
        "SELECT * FROM submissions WHERE id = ?",
        (receipt["submission_id"],),
    ).fetchone()
    if not submission:
        submission = market.conn.execute(
            "SELECT * FROM submissions WHERE bounty_id = ? AND solver_id = ? ORDER BY created_at DESC LIMIT 1",
            (bounty_id, receipt["solver_id"]),
        ).fetchone()
    if not submission:
        raise EconomicLoopError("accepted bounty has no solver submission")
    if submission["solver_id"] != receipt["solver_id"]:
        raise EconomicLoopError("accepted receipt solver does not match submission")
    return {"bounty": bounty, "receipt": receipt, "submission": submission}


def _allocation_result(market: AgentBountyMarket, row: Any, *, replayed: bool) -> dict[str, Any]:
    split = _json_row(row, "allocation_json", {})
    balances = settlement_balances(market, solver_id=row["solver_id"], currency=row["currency"])
    return {
        "schema": SETTLEMENT_ALLOCATION_SCHEMA,
        "ok": row["transfer_status"] == "paid",
        "replayed": replayed,
        "allocation_id": row["id"],
        "bounty_id": row["bounty_id"],
        "solver_id": row["solver_id"],
        "accepted_receipt_id": row["accepted_receipt_id"],
        "payout_id": row["payout_id"],
        "reward_amount": int(row["reward_amount"]),
        "external_transfer_amount": int(row["external_transfer_amount"]),
        "retained_operating_amount": int(row["retained_operating_amount"]),
        "platform_fee_amount": int(row["platform_fee_amount"]),
        "currency": row["currency"],
        "retention_consent": bool(row["retention_consent"]),
        "transfer_provider": row["transfer_provider"],
        "gateway_transfer_id": row["gateway_transfer_id"],
        "transfer_status": row["transfer_status"],
        "allocation_digest": row["allocation_digest"],
        "split": split,
        "balances": balances,
    }


def allocate_accepted_reward(
    market: AgentBountyMarket,
    *,
    bounty_id: str,
    external_transfer_amount: int | None = None,
    retained_operating_amount: int = 0,
    platform_fee_amount: int = 0,
    retention_consent: bool = False,
    transfer_provider: str = "fake",
    stripe_client: StripeClient | None = None,
    stripe_connected_account_id: str | None = None,
    idempotency_key: str | None = None,
    simulate_transfer_failure: bool = False,
) -> dict[str, Any]:
    context = _accepted_context(market, bounty_id)
    bounty = context["bounty"]
    receipt = context["receipt"]
    submission = context["submission"]
    solver_id = submission["solver_id"]
    reward_amount = int(bounty["reward_amount"])
    currency = str(bounty["currency"])
    policy = default_settlement_policy(
        solver_id=solver_id,
        reward_amount=reward_amount,
        currency=currency,
        external_transfer_amount=external_transfer_amount,
        retained_operating_amount=retained_operating_amount,
        platform_fee_amount=platform_fee_amount,
        retention_consent=retention_consent,
    )
    save_settlement_policy(market, policy)
    external_transfer_amount = int(policy["external_transfer_amount"])
    retained_operating_amount = int(policy["retained_operating_amount"])
    platform_fee_amount = int(policy["platform_fee_amount"])
    key = idempotency_key or f"settlement:{bounty_id}:{sha256_text(stable_json(policy))[-16:]}"
    existing = market.conn.execute(
        "SELECT * FROM settlement_allocations WHERE idempotency_key = ? OR bounty_id = ?",
        (key, bounty_id),
    ).fetchone()
    if existing:
        expected = {
            "external_transfer_amount": external_transfer_amount,
            "retained_operating_amount": retained_operating_amount,
            "platform_fee_amount": platform_fee_amount,
            "currency": currency,
            "retention_consent": bool(retention_consent),
            "transfer_provider": transfer_provider,
        }
        actual = {
            "external_transfer_amount": int(existing["external_transfer_amount"]),
            "retained_operating_amount": int(existing["retained_operating_amount"]),
            "platform_fee_amount": int(existing["platform_fee_amount"]),
            "currency": existing["currency"],
            "retention_consent": bool(existing["retention_consent"]),
            "transfer_provider": existing["transfer_provider"],
        }
        if actual != expected:
            raise EconomicLoopError("settlement allocation replayed with different split")
        return _allocation_result(market, existing, replayed=True)
    if bounty["state"] == BountyState.PAID.value:
        raise EconomicLoopError("bounty is already paid without a recorded split allocation")
    transfer_provider = transfer_provider.strip().lower()
    if transfer_provider not in {"fake", "stripe"}:
        raise EconomicLoopError("transfer provider must be fake or stripe")
    if transfer_provider == "stripe":
        if stripe_client is None:
            raise EconomicLoopError("split Stripe Connect transfer requires an explicit Stripe client")
        if external_transfer_amount <= 0:
            raise EconomicLoopError("split Stripe Connect transfer requires a positive external transfer amount")

    payout_id: str | None = None
    gateway_transfer_id: str | None = None
    now = utc_now()
    if external_transfer_amount:
        payout_id = _ensure_split_payout(
            market,
            bounty=bounty,
            submission=submission,
            receipt=receipt,
            amount=external_transfer_amount,
            idempotency_key=key,
        )
        market._transition_bounty(bounty_id, BountyState.PAYOUT_PENDING, reason="split_settlement_started", idempotency_key=f"state:{key}:payout_pending")
        if simulate_transfer_failure:
            with market.conn:
                market.conn.execute("UPDATE payouts SET status = 'failed', updated_at = ? WHERE id = ?", (utc_now(), payout_id))
                market._transition_bounty(bounty_id, BountyState.PAYOUT_FAILED, reason="split_transfer_failed:simulated", idempotency_key=f"state:{key}:payout_failed")
            return {
                "schema": SETTLEMENT_ALLOCATION_SCHEMA,
                "ok": False,
                "replayed": False,
                "bounty_id": bounty_id,
                "solver_id": solver_id,
                "payout_id": payout_id,
                "transfer_status": "failed",
                "error": "simulated external transfer failure before allocation",
            }
        if transfer_provider == "stripe":
            try:
                gateway_transfer_id = _create_split_stripe_transfer(
                    market,
                    bounty=bounty,
                    submission=submission,
                    receipt=receipt,
                    payout_id=payout_id,
                    amount=external_transfer_amount,
                    client=stripe_client,
                    connected_account_id=stripe_connected_account_id,
                    idempotency_key=key,
                )
            except Exception as exc:
                with market.conn:
                    market.conn.execute("UPDATE payouts SET status = 'failed', idempotency_key = ?, updated_at = ? WHERE id = ?", (key, utc_now(), payout_id))
                    market._transition_bounty(bounty_id, BountyState.PAYOUT_FAILED, reason=f"split_stripe_transfer_failed:{safe_error_message(exc)}", idempotency_key=f"state:{key}:payout_failed")
                return {
                    "schema": SETTLEMENT_ALLOCATION_SCHEMA,
                    "ok": False,
                    "replayed": False,
                    "bounty_id": bounty_id,
                    "solver_id": solver_id,
                    "payout_id": payout_id,
                    "transfer_status": "failed",
                    "transfer_provider": "stripe",
                    "error": safe_error_message(exc),
                }
        else:
            gateway_transfer_id = f"fake_transfer_{sha256_text(key)[-24:]}"
    else:
        market._transition_bounty(bounty_id, BountyState.PAYOUT_PENDING, reason="internal_only_settlement_started", idempotency_key=f"state:{key}:payout_pending")

    allocation = {
        "schema": SETTLEMENT_ALLOCATION_SCHEMA,
        "bounty_id": bounty_id,
        "solver_id": solver_id,
        "accepted_receipt_id": receipt["id"],
        "reward_amount": reward_amount,
        "external_transfer_amount": external_transfer_amount,
        "retained_operating_amount": retained_operating_amount,
        "platform_fee_amount": platform_fee_amount,
        "currency": currency,
        "retention_consent": bool(retention_consent),
        "transfer_provider": transfer_provider,
        "gateway_transfer_id": gateway_transfer_id,
        "truth": "fake external transfer id is deterministic test evidence; only tr_ IDs are real Stripe transfers",
    }
    allocation_digest = sha256_text(stable_json(allocation))
    allocation_id = _stable_id("settle", {"bounty_id": bounty_id, "digest": allocation_digest})
    try:
        with market.conn:
            if external_transfer_amount:
                market.ledger.transfer(
                    event_type="split_payout_in_transit",
                    idempotency_key=f"ledger:{key}:external:transit",
                    from_account=solver_earned_account(solver_id),
                    to_account=solver_payout_transit_account(solver_id),
                    amount=external_transfer_amount,
                    currency=currency,
                    project_id=bounty["project_id"],
                    bounty_id=bounty_id,
                    solver_id=solver_id,
                    payout_id=payout_id,
                    prevent_negative_accounts={solver_earned_account(solver_id)},
                )
                market.ledger.transfer(
                    event_type="split_payout_paid",
                    idempotency_key=f"ledger:{key}:external:paid",
                    from_account=solver_payout_transit_account(solver_id),
                    to_account=solver_paid_account(solver_id),
                    amount=external_transfer_amount,
                    currency=currency,
                    project_id=bounty["project_id"],
                    bounty_id=bounty_id,
                    solver_id=solver_id,
                    payout_id=payout_id,
                    external_id=gateway_transfer_id,
                    prevent_negative_accounts={solver_payout_transit_account(solver_id)},
                )
                market.conn.execute(
                    """
                    UPDATE payouts
                    SET status = 'paid', gateway_payout_id = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (gateway_transfer_id, utc_now(), payout_id),
                )
            if retained_operating_amount:
                market.ledger.transfer(
                    event_type="solver_operating_credit_retained",
                    idempotency_key=f"ledger:{key}:retained",
                    from_account=solver_earned_account(solver_id),
                    to_account=solver_operating_available_account(solver_id),
                    amount=retained_operating_amount,
                    currency=currency,
                    project_id=bounty["project_id"],
                    bounty_id=bounty_id,
                    solver_id=solver_id,
                    prevent_negative_accounts={solver_earned_account(solver_id)},
                )
            if platform_fee_amount:
                market.ledger.transfer(
                    event_type="platform_fee_retained",
                    idempotency_key=f"ledger:{key}:fee",
                    from_account=solver_earned_account(solver_id),
                    to_account=platform_fee_account(),
                    amount=platform_fee_amount,
                    currency=currency,
                    project_id=bounty["project_id"],
                    bounty_id=bounty_id,
                    solver_id=solver_id,
                    prevent_negative_accounts={solver_earned_account(solver_id)},
                )
            market.conn.execute(
                """
                INSERT INTO settlement_allocations(
                    id, bounty_id, solver_id, accepted_receipt_id, payout_id, reward_amount,
                    external_transfer_amount, retained_operating_amount, platform_fee_amount,
                    currency, retention_consent, transfer_provider, gateway_transfer_id,
                    transfer_status, allocation_json, allocation_digest, created_at, updated_at,
                    idempotency_key
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'paid', ?, ?, ?, ?, ?)
                """,
                (
                    allocation_id,
                    bounty_id,
                    solver_id,
                    receipt["id"],
                    payout_id,
                    reward_amount,
                    external_transfer_amount,
                    retained_operating_amount,
                    platform_fee_amount,
                    currency,
                    1 if retention_consent else 0,
                    transfer_provider,
                    gateway_transfer_id,
                    stable_json(allocation),
                    allocation_digest,
                    now,
                    utc_now(),
                    key,
                ),
            )
            market._transition_bounty(bounty_id, BountyState.PAID, reason="split_settlement_paid", idempotency_key=f"state:{key}:paid")
    except LedgerError as exc:
        raise EconomicLoopError(str(exc)) from exc
    row = market.conn.execute("SELECT * FROM settlement_allocations WHERE id = ?", (allocation_id,)).fetchone()
    return _allocation_result(market, row, replayed=False)


def _ensure_split_payout(
    market: AgentBountyMarket,
    *,
    bounty: Any,
    submission: Any,
    receipt: Any,
    amount: int,
    idempotency_key: str,
) -> str:
    existing = market.conn.execute("SELECT * FROM payouts WHERE bounty_id = ?", (bounty["id"],)).fetchone()
    if existing:
        if int(existing["amount"]) != amount:
            raise EconomicLoopError("existing payout amount does not match external settlement amount")
        return existing["id"]
    payout_id = new_id("payout")
    now = utc_now()
    with market.conn:
        market.conn.execute(
            """
            INSERT INTO payouts(
                id, bounty_id, solver_id, amount, currency, status,
                accepted_receipt_id, verifier_digest, idempotency_key, transfer_group,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?)
            """,
            (
                payout_id,
                bounty["id"],
                submission["solver_id"],
                amount,
                bounty["currency"],
                receipt["id"],
                receipt["verifier_digest"],
                idempotency_key,
                f"agent-bounty:{bounty['id']}:{payout_id}",
                now,
                now,
            ),
        )
    return payout_id


def _create_split_stripe_transfer(
    market: AgentBountyMarket,
    *,
    bounty: Any,
    submission: Any,
    receipt: Any,
    payout_id: str,
    amount: int,
    client: StripeClient,
    connected_account_id: str | None,
    idempotency_key: str,
) -> str:
    solver_id = submission["solver_id"]
    if connected_account_id:
        market.attach_stripe_beneficiary(solver_id=solver_id, account_id=connected_account_id, client=client)
    solver = market.conn.execute("SELECT * FROM solver_identities WHERE id = ?", (solver_id,)).fetchone()
    account_id = solver["beneficiary_external_id"] if solver else None
    if not isinstance(account_id, str) or not account_id.startswith("acct_"):
        raise EconomicLoopError("solver has no validated Stripe connected account")
    params = transfer_params(
        project_id=bounty["project_id"],
        bounty_id=bounty["id"],
        solver_id=solver_id,
        payout_id=payout_id,
        amount=amount,
        currency=bounty["currency"],
        destination_account_id=account_id,
        accepted_receipt_id=receipt["id"],
        candidate_sha=submission["candidate_commit"],
        verifier_digest=receipt["verifier_digest"],
        backend_digest=receipt["backend_digest"],
        policy_digest=receipt["policy_digest"],
        source_transaction_id=_source_transaction_for_split_payout(
            market,
            project_id=bounty["project_id"],
            currency=bounty["currency"],
            amount=amount,
        ),
    )
    operation_id = market._begin_stripe_operation(
        kind="split_transfer_create",
        idempotency_key=idempotency_key,
        request_parameters_digest=request_digest(params),
    )
    try:
        transfer = client.create_transfer(idempotency_key=idempotency_key, params=params)
        transfer_id = require_id(transfer, prefix="tr_", object_name="Connect Transfer")
        retrieved = client.retrieve_transfer(transfer_id)
        market._validate_transfer(retrieved, expected=params)
    except Exception as exc:
        with market.conn:
            market._finish_stripe_operation(
                operation_id=operation_id,
                status="failed",
                safe_error_message=safe_error_message(exc),
            )
        raise
    with market.conn:
        market._finish_stripe_operation(
            operation_id=operation_id,
            status="succeeded",
            stripe_object_type="transfer",
            stripe_object_id=transfer_id,
        )
        market.conn.execute(
            """
            UPDATE payouts
            SET status = 'pending', gateway_payout_id = ?, stripe_transfer_id = ?,
                idempotency_key = ?, transfer_group = ?, updated_at = ?
            WHERE id = ?
            """,
            (transfer_id, transfer_id, idempotency_key, params["transfer_group"], utc_now(), payout_id),
        )
    return transfer_id


def _source_transaction_for_split_payout(market: AgentBountyMarket, *, project_id: str, currency: str, amount: int) -> str | None:
    row = market.conn.execute(
        """
        SELECT gateway_source_transaction_id
        FROM funding_events
        WHERE project_id = ?
          AND currency = ?
          AND amount >= ?
          AND gateway_source_transaction_id IS NOT NULL
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (project_id, currency, amount),
    ).fetchone()
    return row["gateway_source_transaction_id"] if row else None


def mark_settlement_transfer_reversed(market: AgentBountyMarket, *, gateway_transfer_id: str, reason: str) -> dict[str, Any]:
    row = market.conn.execute("SELECT * FROM settlement_allocations WHERE gateway_transfer_id = ?", (gateway_transfer_id,)).fetchone()
    if not row:
        return {"gateway_transfer_id": gateway_transfer_id, "action": "ignored_unknown_transfer"}
    if row["transfer_status"] == "reversed":
        return {"allocation_id": row["id"], "gateway_transfer_id": gateway_transfer_id, "action": "already_reversed"}
    payout_result = market.mark_gateway_payout_reversed(gateway_payout_id=gateway_transfer_id, reason=reason)
    with market.conn:
        market.conn.execute(
            "UPDATE settlement_allocations SET transfer_status = 'reversed', updated_at = ? WHERE id = ?",
            (utc_now(), row["id"]),
        )
    return {"allocation_id": row["id"], "gateway_transfer_id": gateway_transfer_id, "action": "reversal_recorded", "payout": payout_result}


def settlement_balances(market: AgentBountyMarket, *, solver_id: str, currency: str) -> dict[str, int]:
    currency = require_currency(currency)
    accounts = {
        "solver_earned": solver_earned_account(solver_id),
        "solver_paid": solver_paid_account(solver_id),
        "solver_payout_transit": solver_payout_transit_account(solver_id),
        "solver_operating_available": solver_operating_available_account(solver_id),
        "platform_fees": platform_fee_account(),
    }
    balances = market.ledger.balances(accounts.values(), currency)
    return {name: balances[account] for name, account in accounts.items()}


def spend_retained_credit_to_project(
    market: AgentBountyMarket,
    *,
    solver_id: str,
    target_project_id: str,
    repo_full_name: str,
    amount: int,
    currency: str,
    title: str,
    issue_class: str,
    verifier_id: str,
    base_commit: str = DEFAULT_BASE_COMMIT,
    idempotency_key: str | None = None,
    issue_number: int | None = None,
) -> dict[str, Any]:
    require_positive_amount(amount)
    currency = require_currency(currency)
    key = idempotency_key or f"solver-operating-spend:{solver_id}:{target_project_id}:{amount}:{currency}:{repo_full_name}"
    existing = market.conn.execute("SELECT * FROM solver_operating_spends WHERE idempotency_key = ?", (key,)).fetchone()
    if existing:
        return _spend_result(existing, replayed=True)
    policy = load_solver_operating_policy(market, solver_id=solver_id)
    _check_spend_policy(
        market,
        policy=policy,
        solver_id=solver_id,
        target_project_id=target_project_id,
        repo_full_name=repo_full_name,
        amount=amount,
        currency=currency,
        issue_class=issue_class,
        verifier_id=verifier_id,
    )
    allocation = market.conn.execute(
        """
        SELECT * FROM settlement_allocations
        WHERE solver_id = ? AND retained_operating_amount > 0 AND transfer_status = 'paid'
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (solver_id,),
    ).fetchone()
    bounty_id = DEFAULT_SECOND_BOUNTY_ID if target_project_id == DEFAULT_SECOND_PROJECT_ID else _stable_id("bounty", {"solver_id": solver_id, "project": target_project_id, "amount": amount})
    market.create_project(project_id=target_project_id, name=target_project_id, currency=currency)
    market.set_budget_policy(
        project_id=target_project_id,
        max_bounty_amount=amount,
        monthly_budget=amount,
        human_approval_threshold=amount,
        allowed_issue_classes=[issue_class],
    )
    with market.conn:
        market.ledger.transfer(
            event_type="solver_operating_spend",
            idempotency_key=f"ledger:{key}:to_project",
            from_account=solver_operating_available_account(solver_id),
            to_account=project_available_account(target_project_id),
            amount=amount,
            currency=currency,
            project_id=target_project_id,
            solver_id=solver_id,
            prevent_negative_accounts={solver_operating_available_account(solver_id)},
        )
    market.create_bounty(
        bounty_id=bounty_id,
        project_id=target_project_id,
        title=title,
        reward_amount=amount,
        currency=currency,
        base_commit=base_commit,
        issue_ref=f"{repo_full_name}#{issue_number or 0}",
        verifier_id=verifier_id,
    )
    reserve = market.reserve_bounty(bounty_id=bounty_id, idempotency_key=f"reserve:{key}:{bounty_id}")
    publication = github_publish_bounty_contract(
        market,
        client=FakeGitHubClient(),
        repo_full_name=repo_full_name,
        bounty_id=bounty_id,
        human_body="Retained solver operating credit funds this follow-up machine-verifiable bounty.",
        title=title,
        issue_number=issue_number,
        idempotency_key=f"github:{key}:{bounty_id}",
    )
    spend = {
        "schema": SOLVER_OPERATING_SPEND_SCHEMA,
        "solver_id": solver_id,
        "source_allocation_id": allocation["id"] if allocation else None,
        "target_project_id": target_project_id,
        "target_bounty_id": bounty_id,
        "repo_full_name": repo_full_name,
        "amount": amount,
        "currency": currency,
        "issue_class": issue_class,
        "verifier_id": verifier_id,
        "contract_digest": publication.get("contract_digest"),
        "github_issue_url": publication.get("issue_url"),
    }
    digest = sha256_text(stable_json(spend))
    spend_id = _stable_id("opspend", {"key": key, "digest": digest})
    now = utc_now()
    with market.conn:
        market.conn.execute(
            """
            INSERT INTO solver_operating_spends(
                id, solver_id, source_allocation_id, target_project_id, target_bounty_id,
                repo_full_name, amount, currency, status, github_issue_url, contract_digest,
                spend_json, spend_digest, created_at, updated_at, idempotency_key
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'published', ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                spend_id,
                solver_id,
                allocation["id"] if allocation else None,
                target_project_id,
                bounty_id,
                repo_full_name,
                amount,
                currency,
                publication.get("issue_url"),
                publication.get("contract_digest"),
                stable_json(spend),
                digest,
                now,
                utc_now(),
                key,
            ),
        )
    row = market.conn.execute("SELECT * FROM solver_operating_spends WHERE id = ?", (spend_id,)).fetchone()
    result = _spend_result(row, replayed=False)
    result["reserve"] = reserve
    result["publication"] = publication
    return result


def _check_spend_policy(
    market: AgentBountyMarket,
    *,
    policy: dict[str, Any],
    solver_id: str,
    target_project_id: str,
    repo_full_name: str,
    amount: int,
    currency: str,
    issue_class: str,
    verifier_id: str,
) -> None:
    reasons: list[str] = []
    if policy.get("solver_id") != solver_id:
        reasons.append("policy solver mismatch")
    if target_project_id not in set(policy.get("allowed_projects", [])):
        reasons.append("target project is not allowlisted")
    if repo_full_name not in set(policy.get("allowed_repositories", [])):
        reasons.append("repository is not allowlisted")
    if issue_class not in set(policy.get("allowed_issue_classes", [])):
        reasons.append("issue class is not allowlisted")
    if verifier_id not in set(policy.get("required_verifier_ids", [])):
        reasons.append("required verifier is missing")
    if currency not in set(policy.get("allowed_currencies", [])):
        reasons.append("currency is not allowlisted")
    if amount > int(policy.get("max_spend_cents", 0)):
        reasons.append("amount exceeds max spend")
    if amount > int(policy.get("human_approval_threshold_cents", 0)):
        reasons.append("amount requires human approval")
    balance = market.ledger.balance(solver_operating_available_account(solver_id), currency)
    if balance < amount:
        reasons.append("insufficient retained operating balance")
    if balance - amount < int(policy.get("minimum_remaining_reserve_cents", 0)):
        reasons.append("minimum remaining reserve would be violated")
    if reasons:
        raise EconomicLoopError("; ".join(reasons))


def _spend_result(row: Any, *, replayed: bool) -> dict[str, Any]:
    return {
        "schema": SOLVER_OPERATING_SPEND_SCHEMA,
        "ok": row["status"] == "published",
        "replayed": replayed,
        "spend_id": row["id"],
        "solver_id": row["solver_id"],
        "source_allocation_id": row["source_allocation_id"],
        "target_project_id": row["target_project_id"],
        "target_bounty_id": row["target_bounty_id"],
        "repo_full_name": row["repo_full_name"],
        "amount": int(row["amount"]),
        "currency": row["currency"],
        "status": row["status"],
        "github_issue_url": row["github_issue_url"],
        "contract_digest": row["contract_digest"],
        "spend_digest": row["spend_digest"],
        "spend": _json_row(row, "spend_json", {}),
    }


def economic_loop_status_report() -> dict[str, Any]:
    config = StripeSandboxConfig.from_env()
    blockers = []
    if not config.enabled:
        blockers.append("set AGENT_BOUNTY_STRIPE_SANDBOX=1 for real Stripe sandbox commands")
    if not config.secret_key:
        blockers.append("set STRIPE_TEST_SECRET_KEY")
    if not config.webhook_secret:
        blockers.append("set STRIPE_TEST_WEBHOOK_SECRET from stripe listen")
    if not config.connected_account_id:
        blockers.append("set STRIPE_TEST_CONNECTED_ACCOUNT_ID")
    return {
        "schema": ECONOMIC_LOOP_STATUS_SCHEMA,
        "deterministic_fake_loop_available": True,
        "split_settlement_adapter": "fake by default; demo-economic-loop-live creates a real split Connect Transfer only with explicit Stripe sandbox configuration",
        "stripe_sandbox_configured": not blockers,
        "stripe_blockers": blockers,
        "prior_real_stripe_evidence": REAL_STRIPE_EVIDENCE,
    }


def run_demo_economic_loop(
    market: AgentBountyMarket,
    *,
    motoko_repo: Path | None,
    external_transfer_amount: int = 500,
    retained_operating_amount: int = 2000,
    platform_fee_amount: int = 0,
) -> dict[str, Any]:
    solver_demo = run_demo_solver_motoko(market, motoko_repo=motoko_repo)
    allocation = allocate_accepted_reward(
        market,
        bounty_id=DEFAULT_FIRST_BOUNTY_ID,
        external_transfer_amount=external_transfer_amount,
        retained_operating_amount=retained_operating_amount,
        platform_fee_amount=platform_fee_amount,
        retention_consent=True,
        transfer_provider="fake",
        idempotency_key="economic-loop:settle:motoko-issue-1",
    )
    replay_allocation = allocate_accepted_reward(
        market,
        bounty_id=DEFAULT_FIRST_BOUNTY_ID,
        external_transfer_amount=external_transfer_amount,
        retained_operating_amount=retained_operating_amount,
        platform_fee_amount=platform_fee_amount,
        retention_consent=True,
        transfer_provider="fake",
        idempotency_key="economic-loop:settle:motoko-issue-1",
    )
    policy = save_solver_operating_policy(
        market,
        default_solver_operating_policy(
            solver_id=PYTHON_SOLVER_ID,
            allowed_projects=[DEFAULT_SECOND_PROJECT_ID],
            allowed_repositories=[DEFAULT_REPO],
            required_verifier_ids=[DEFAULT_SECOND_VERIFIER_ID],
            max_spend_cents=retained_operating_amount,
            human_approval_threshold_cents=retained_operating_amount,
            allowed_currencies=[allocation["currency"]],
        ),
    )
    spend = spend_retained_credit_to_project(
        market,
        solver_id=PYTHON_SOLVER_ID,
        target_project_id=DEFAULT_SECOND_PROJECT_ID,
        repo_full_name=DEFAULT_REPO,
        amount=retained_operating_amount,
        currency=allocation["currency"],
        title="Follow-up bounty funded from retained solver operating credit",
        issue_class="machine-verifiable-tui-regression",
        verifier_id=DEFAULT_SECOND_VERIFIER_ID,
        base_commit=DEFAULT_BASE_COMMIT,
        idempotency_key="economic-loop:spend-retained:followup",
    )
    replay_spend = spend_retained_credit_to_project(
        market,
        solver_id=PYTHON_SOLVER_ID,
        target_project_id=DEFAULT_SECOND_PROJECT_ID,
        repo_full_name=DEFAULT_REPO,
        amount=retained_operating_amount,
        currency=allocation["currency"],
        title="Follow-up bounty funded from retained solver operating credit",
        issue_class="machine-verifiable-tui-regression",
        verifier_id=DEFAULT_SECOND_VERIFIER_ID,
        base_commit=DEFAULT_BASE_COMMIT,
        idempotency_key="economic-loop:spend-retained:followup",
    )
    balances = settlement_balances(market, solver_id=PYTHON_SOLVER_ID, currency=allocation["currency"])
    ok = (
        bool(solver_demo["ok"])
        and allocation["ok"]
        and replay_allocation["replayed"]
        and spend["ok"]
        and replay_spend["replayed"]
        and balances["solver_earned"] == 0
        and balances["solver_operating_available"] == 0
        and allocation["external_transfer_amount"] + allocation["retained_operating_amount"] + allocation["platform_fee_amount"] == allocation["reward_amount"]
    )
    return {
        "schema": ECONOMIC_LOOP_DEMO_SCHEMA,
        "ok": ok,
        "provider_truth": {
            "funding_provider": "fake project-agent funding in deterministic demo",
            "external_transfer_provider": "fake",
            "real_stripe_transfer_claimed": False,
            "only_tr_prefix_is_real_stripe": True,
            "prior_real_stripe_evidence": REAL_STRIPE_EVIDENCE,
        },
        "project_and_solver": {
            "project_agent_decisions": solver_demo["project_agent"].get("evaluation", {}).get("decisions", []),
            "solver_decisions": solver_demo["evaluation"]["evaluations"],
        },
        "first_bounty": {
            "bounty_id": DEFAULT_FIRST_BOUNTY_ID,
            "contract_digest": solver_demo["submission"]["evidence"]["contract_digest"],
            "candidate_sha": solver_demo["submission"]["evidence"]["candidate_commit"],
            "receipt_id": solver_demo["submission"]["evidence"]["verification_receipt_id"],
        },
        "allocation": allocation,
        "allocation_replay": replay_allocation,
        "operating_policy": policy,
        "retained_credit_spend": spend,
        "retained_credit_spend_replay": replay_spend,
        "second_bounty": {
            "project_id": spend["target_project_id"],
            "bounty_id": spend["target_bounty_id"],
            "issue_url": spend["github_issue_url"],
            "contract_digest": spend["contract_digest"],
        },
        "balances": balances,
    }


def stripe_split_blockers(config: StripeSandboxConfig) -> list[str]:
    blockers: list[str] = []
    if not config.enabled:
        blockers.append("set AGENT_BOUNTY_STRIPE_SANDBOX=1")
    if not config.secret_key:
        blockers.append("set STRIPE_TEST_SECRET_KEY")
    elif not (config.secret_key.startswith("sk_test_") or config.secret_key.startswith("rk_test_")):
        blockers.append("replace non-test Stripe API key with sk_test_ or rk_test_")
    if not config.webhook_secret:
        blockers.append("set STRIPE_TEST_WEBHOOK_SECRET from stripe listen")
    if not config.connected_account_id:
        blockers.append("set STRIPE_TEST_CONNECTED_ACCOUNT_ID to a test connected account")
    return blockers


def setup_live_split_bounty(market: AgentBountyMarket, *, reward_amount: int, currency: str) -> dict[str, Any]:
    currency = require_currency(currency)
    market.create_project(project_id="project_motoko", name="Motoko", currency=currency)
    market.set_budget_policy(
        project_id="project_motoko",
        max_bounty_amount=reward_amount,
        monthly_budget=reward_amount,
        human_approval_threshold=reward_amount,
        allowed_issue_classes=["machine-verifiable-tui-regression"],
    )
    market.create_bounty(
        bounty_id=DEFAULT_FIRST_BOUNTY_ID,
        project_id="project_motoko",
        title="Eliminate Motoko TUI background-study typing freeze",
        reward_amount=reward_amount,
        currency=currency,
        base_commit=DEFAULT_BASE_COMMIT,
        issue_ref="lk251/motoko#1",
        verifier_id="motoko_issue_1_tui_latency_v2",
    )
    bounty = market._bounty(DEFAULT_FIRST_BOUNTY_ID)
    available = market.ledger.balance(project_available_account("project_motoko"), currency)
    return {"bounty_id": DEFAULT_FIRST_BOUNTY_ID, "state": bounty["state"], "project_available_cents": available, "currency": currency}


def run_demo_economic_loop_live(
    market: AgentBountyMarket,
    *,
    motoko_repo: Path | None,
    config: StripeSandboxConfig,
    client: StripeClient | None,
    reward_amount: int = 2500,
    currency: str = "EUR",
    external_transfer_amount: int = 500,
    retained_operating_amount: int = 2000,
    platform_fee_amount: int = 0,
) -> dict[str, Any]:
    blockers = stripe_split_blockers(config)
    if blockers:
        return {
            "schema": ECONOMIC_LOOP_LIVE_SCHEMA,
            "ok": False,
            "stage": "blocked_configuration",
            "blockers": blockers,
            "real_stripe_transfer_claimed": False,
        }
    if client is None:
        return {
            "schema": ECONOMIC_LOOP_LIVE_SCHEMA,
            "ok": False,
            "stage": "blocked_configuration",
            "blockers": ["construct an explicit Stripe client from sandbox configuration"],
            "real_stripe_transfer_claimed": False,
        }
    setup = setup_live_split_bounty(market, reward_amount=reward_amount, currency=currency)
    if setup["state"] == BountyState.AWAITING_FUNDING.value and int(setup["project_available_cents"]) < reward_amount:
        checkout = market.create_stripe_checkout(
            project_id="project_motoko",
            source_kind="owner",
            amount=reward_amount,
            currency=currency,
            success_url=f"{config.public_base_url}/success",
            cancel_url=f"{config.public_base_url}/cancel",
            client=client,
            idempotency_key=f"economic-loop-live:checkout:{reward_amount}:{currency}",
        )
        return {
            "schema": ECONOMIC_LOOP_LIVE_SCHEMA,
            "ok": False,
            "stage": "waiting_for_signed_webhook",
            "setup": setup,
            "checkout_session_id": checkout["checkout_session_id"],
            "payment_intent_id": checkout["payment_intent_id"],
            "checkout_url": checkout["checkout_url"],
            "next": "complete Checkout, let stripe-webhook-serve process the signed event, then rerun demo-economic-loop-live",
            "real_stripe_transfer_claimed": False,
        }
    reserve = market.reserve_bounty(
        bounty_id=DEFAULT_FIRST_BOUNTY_ID,
        idempotency_key=f"economic-loop-live:reserve:{DEFAULT_FIRST_BOUNTY_ID}:{reward_amount}:{currency}",
    )
    profiles = register_default_solver_profiles(market)
    market.create_solver(
        solver_id=PYTHON_SOLVER_ID,
        display_name="Python terminal/TUI concurrency specialist",
        idempotency_key=f"economic-loop-live:solver:{PYTHON_SOLVER_ID}",
    )
    beneficiary = market.attach_stripe_beneficiary(
        solver_id=PYTHON_SOLVER_ID,
        account_id=str(config.connected_account_id),
        client=client,
    )
    bounty = market._bounty(DEFAULT_FIRST_BOUNTY_ID)
    claim: dict[str, Any] | None = None
    if bounty["state"] == BountyState.OPEN.value:
        claim = market.claim_bounty(
            bounty_id=DEFAULT_FIRST_BOUNTY_ID,
            solver_id=PYTHON_SOLVER_ID,
            lease_expires_at="2026-06-30T18:00:00Z",
            idempotency_key=f"economic-loop-live:claim:{DEFAULT_FIRST_BOUNTY_ID}:{PYTHON_SOLVER_ID}",
        )
    execution = execute_deterministic_motoko_replay(market, solver_id=PYTHON_SOLVER_ID, bounty_id=DEFAULT_FIRST_BOUNTY_ID)
    submission = submit_solver_replay(market, motoko_repo=motoko_repo)
    allocation = allocate_accepted_reward(
        market,
        bounty_id=DEFAULT_FIRST_BOUNTY_ID,
        external_transfer_amount=external_transfer_amount,
        retained_operating_amount=retained_operating_amount,
        platform_fee_amount=platform_fee_amount,
        retention_consent=True,
        transfer_provider="stripe",
        stripe_client=client,
        stripe_connected_account_id=config.connected_account_id,
        idempotency_key="economic-loop-live:split-stripe-transfer",
    )
    if not allocation.get("ok"):
        return {
            "schema": ECONOMIC_LOOP_LIVE_SCHEMA,
            "ok": False,
            "stage": "split_transfer_failed",
            "setup": setup,
            "reserve": reserve,
            "profiles": profiles,
            "beneficiary": beneficiary,
            "claim": claim,
            "execution": execution,
            "submission": submission,
            "allocation": allocation,
            "real_stripe_transfer_claimed": False,
        }
    policy = save_solver_operating_policy(
        market,
        default_solver_operating_policy(
            solver_id=PYTHON_SOLVER_ID,
            allowed_projects=[DEFAULT_SECOND_PROJECT_ID],
            allowed_repositories=[DEFAULT_REPO],
            required_verifier_ids=[DEFAULT_SECOND_VERIFIER_ID],
            max_spend_cents=retained_operating_amount,
            human_approval_threshold_cents=retained_operating_amount,
            allowed_currencies=[allocation["currency"]],
        ),
    )
    spend = spend_retained_credit_to_project(
        market,
        solver_id=PYTHON_SOLVER_ID,
        target_project_id=DEFAULT_SECOND_PROJECT_ID,
        repo_full_name=DEFAULT_REPO,
        amount=retained_operating_amount,
        currency=allocation["currency"],
        title="Follow-up bounty funded from retained solver operating credit",
        issue_class="machine-verifiable-tui-regression",
        verifier_id=DEFAULT_SECOND_VERIFIER_ID,
        base_commit=DEFAULT_BASE_COMMIT,
        idempotency_key="economic-loop-live:spend-retained:followup",
    )
    balances = settlement_balances(market, solver_id=PYTHON_SOLVER_ID, currency=allocation["currency"])
    ok = (
        allocation["ok"]
        and str(allocation.get("gateway_transfer_id", "")).startswith("tr_")
        and spend["ok"]
        and balances["solver_earned"] == 0
        and balances["solver_operating_available"] == 0
    )
    return {
        "schema": ECONOMIC_LOOP_LIVE_SCHEMA,
        "ok": ok,
        "stage": "complete" if ok else "review_required",
        "setup": setup,
        "reserve": reserve,
        "profiles": profiles,
        "beneficiary": beneficiary,
        "claim": claim,
        "execution": execution,
        "submission": submission,
        "allocation": allocation,
        "operating_policy": policy,
        "retained_credit_spend": spend,
        "balances": balances,
        "real_stripe_transfer_claimed": str(allocation.get("gateway_transfer_id", "")).startswith("tr_"),
    }
