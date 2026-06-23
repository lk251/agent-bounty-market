from __future__ import annotations

import hashlib
import hmac
import json
import tempfile
import unittest
from pathlib import Path

from agent_bounty.core import AgentBountyMarket, MarketError
from agent_bounty.db import connect
from agent_bounty.payments import (
    FakePaymentGateway,
    GatewayPayout,
    PaymentGatewayError,
    StripePaymentGateway,
    StripeTestConfig,
)
from agent_bounty.stripe_webhooks import StripeWebhookError, record_stripe_webhook_event
from agent_bounty.verification import ProtectedVerifierRunner

from tests.helpers import accepted_verifier, make_market, submit_ready


class RecordingStripeTransport:
    def __init__(self):
        self.requests = []

    def request(self, method, path, *, headers, data=None):
        self.requests.append({"method": method, "path": path, "headers": dict(headers), "data": dict(data or {})})
        if path == "/v1/payment_intents":
            return {
                "id": "pi_test_funding",
                "object": "payment_intent",
                "amount": int(data["amount"]),
                "currency": data["currency"],
                "livemode": False,
                "status": "succeeded",
            }
        if path == "/v1/transfers":
            return {
                "id": "tr_test_payout",
                "object": "transfer",
                "amount": int(data["amount"]),
                "currency": data["currency"],
                "livemode": False,
            }
        if path == "/v1/transfers/tr_test_payout":
            return {
                "id": "tr_test_payout",
                "object": "transfer",
                "amount": 2500,
                "currency": "usd",
                "livemode": False,
            }
        raise AssertionError(f"unexpected Stripe request {method} {path}")


class PendingPaymentGateway(FakePaymentGateway):
    def __init__(self, *, external_id: str = "tr_pending_test"):
        super().__init__()
        self.external_id = external_id

    def release_payout(self, *, payout_id: str, solver_id: str, amount: int, currency: str, idempotency_key: str) -> GatewayPayout:
        return GatewayPayout(self.external_id, "pending", amount, currency, False)


def signed_stripe_payload(event: dict, *, secret: str = "whsec_test", timestamp: int = 1_800_000_000) -> tuple[bytes, str]:
    payload = json.dumps(event, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), f"{timestamp}.".encode("utf-8") + payload, hashlib.sha256).hexdigest()
    return payload, f"t={timestamp},v1={digest}"


def make_market_with_gateway(verifier_dir: Path, gateway):
    tmp = tempfile.TemporaryDirectory()
    conn = connect(Path(tmp.name) / "market.sqlite3")
    market = AgentBountyMarket(conn, gateway, ProtectedVerifierRunner(verifier_dir=verifier_dir, timeout_seconds=5.0))
    return tmp, market


class PaymentTests(unittest.TestCase):
    def test_stripe_gateway_requires_explicit_test_configuration(self):
        with self.assertRaises(PaymentGatewayError):
            StripePaymentGateway()
        with self.assertRaises(PaymentGatewayError):
            StripeTestConfig(secret_key="sk_live_bad", solver_accounts={"solver_test": "acct_test"})
        with self.assertRaises(PaymentGatewayError):
            StripePaymentGateway.from_env(
                env={
                    "STRIPE_SECRET_KEY": "sk_test_123",
                    "AGENT_BOUNTY_STRIPE_SOLVER_ACCOUNTS_JSON": '{"solver_test":"acct_test"}',
                },
                explicitly_configured=True,
            )

    def test_stripe_gateway_maps_funding_and_payout_to_test_mode_requests(self):
        transport = RecordingStripeTransport()
        gateway = StripePaymentGateway(
            config=StripeTestConfig(secret_key="sk_test_123", solver_accounts={"solver_test": "acct_test_solver"}),
            explicitly_configured=True,
            transport=transport,
        )

        credit = gateway.credit_project_treasury(
            project_id="project_test",
            amount=2500,
            currency="USD",
            idempotency_key="fund:test",
        )
        beneficiary = gateway.ensure_solver_beneficiary(solver_id="solver_test", idempotency_key="beneficiary:test")
        payout = gateway.release_payout(
            payout_id="payout_test",
            solver_id="solver_test",
            amount=2500,
            currency="USD",
            idempotency_key="payout:test",
        )

        self.assertEqual(credit.external_id, "pi_test_funding")
        self.assertEqual(beneficiary.external_id, "acct_test_solver")
        self.assertEqual(payout.external_id, "tr_test_payout")
        payment_intent = transport.requests[0]
        transfer = transport.requests[1]
        self.assertEqual(payment_intent["path"], "/v1/payment_intents")
        self.assertEqual(payment_intent["headers"]["Idempotency-Key"], "fund:test")
        self.assertEqual(payment_intent["data"]["amount"], "2500")
        self.assertEqual(payment_intent["data"]["currency"], "usd")
        self.assertEqual(payment_intent["data"]["confirm"], "true")
        self.assertEqual(transfer["path"], "/v1/transfers")
        self.assertEqual(transfer["headers"]["Idempotency-Key"], "payout:test")
        self.assertEqual(transfer["data"]["destination"], "acct_test_solver")
        self.assertEqual(transfer["data"]["transfer_group"], "payout_test")
        self.assertEqual(gateway.retrieve_payout_status(external_id="tr_test_payout"), "paid")

    def test_payout_failure_records_failed_and_retries_safely(self):
        payout_key = "payout:test"
        with tempfile.TemporaryDirectory() as tmp:
            verifier_dir = accepted_verifier(Path(tmp))
            holder, market = make_market(verifier_dir, fail_payout_keys={payout_key})
            self.addCleanup(holder.cleanup)
            project_id, bounty_id, solver_id, submission_id = submit_ready(market)
            market.run_verification(submission_id=submission_id, idempotency_key="verify:test")
            failed = market.release_payout(bounty_id=bounty_id, idempotency_key=payout_key)
            self.assertTrue(failed["failed"])
            self.assertEqual(market.bounty_summary(bounty_id)["state"], "payout_failed")
            market.gateway.fail_payout_keys.clear()
            paid = market.release_payout(bounty_id=bounty_id, idempotency_key=payout_key)
            self.assertFalse(paid.get("failed", False))
            self.assertEqual(market.bounty_summary(bounty_id)["state"], "paid")
            self.assertTrue(market.reconciliation(project_id=project_id, solver_id=solver_id)["ok"])

    def test_rejected_bounty_cannot_pay(self):
        with tempfile.TemporaryDirectory() as tmp:
            from tests.helpers import rejected_verifier

            verifier_dir = rejected_verifier(Path(tmp))
            holder, market = make_market(verifier_dir)
            self.addCleanup(holder.cleanup)
            _project_id, bounty_id, _solver_id, submission_id = submit_ready(market)
            market.run_verification(submission_id=submission_id, idempotency_key="verify:test")
            with self.assertRaises(MarketError):
                market.release_payout(bounty_id=bounty_id, idempotency_key="payout:test")

    def test_signed_stripe_webhook_settles_pending_payout_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            verifier_dir = accepted_verifier(Path(tmp))
            holder, market = make_market_with_gateway(verifier_dir, PendingPaymentGateway())
            self.addCleanup(holder.cleanup)
            project_id, bounty_id, solver_id, submission_id = submit_ready(market)
            market.run_verification(submission_id=submission_id, idempotency_key="verify:test")
            pending = market.release_payout(bounty_id=bounty_id, idempotency_key="payout:test")
            self.assertTrue(pending["pending"])
            self.assertEqual(market.bounty_summary(bounty_id)["state"], "payout_pending")

            event = {
                "id": "evt_transfer_created",
                "type": "transfer.created",
                "livemode": False,
                "data": {"object": {"id": pending["gateway_payout_id"], "object": "transfer"}},
            }
            payload, signature = signed_stripe_payload(event)
            first = market.ingest_stripe_webhook(
                payload=payload,
                signature_header=signature,
                endpoint_secret="whsec_test",
                now=1_800_000_000,
            )
            ledger_count = len(market.ledger_rows())
            replay = market.ingest_stripe_webhook(
                payload=payload,
                signature_header=signature,
                endpoint_secret="whsec_test",
                now=1_800_000_000,
            )

            self.assertEqual(first["action"], "paid")
            self.assertTrue(replay["replayed"])
            self.assertEqual(len(market.stripe_webhook_rows()), 1)
            self.assertEqual(len(market.ledger_rows()), ledger_count)
            self.assertEqual(market.bounty_summary(bounty_id)["state"], "paid")
            self.assertTrue(market.reconciliation(project_id=project_id, solver_id=solver_id)["ok"])

    def test_stripe_webhook_failure_can_retry_payout_and_reconcile(self):
        with tempfile.TemporaryDirectory() as tmp:
            verifier_dir = accepted_verifier(Path(tmp))
            holder, market = make_market_with_gateway(verifier_dir, PendingPaymentGateway(external_id="tr_will_fail"))
            self.addCleanup(holder.cleanup)
            project_id, bounty_id, solver_id, submission_id = submit_ready(market)
            market.run_verification(submission_id=submission_id, idempotency_key="verify:test")
            pending = market.release_payout(bounty_id=bounty_id, idempotency_key="payout:first")

            event = {
                "id": "evt_transfer_failed",
                "type": "transfer.failed",
                "livemode": False,
                "data": {
                    "object": {
                        "id": pending["gateway_payout_id"],
                        "object": "transfer",
                        "failure_message": "test transfer failure",
                    }
                },
            }
            payload, signature = signed_stripe_payload(event)
            failed = market.ingest_stripe_webhook(
                payload=payload,
                signature_header=signature,
                endpoint_secret="whsec_test",
                now=1_800_000_000,
            )
            self.assertEqual(failed["action"], "failed")
            self.assertEqual(market.bounty_summary(bounty_id)["state"], "payout_failed")

            market.gateway = FakePaymentGateway()
            paid = market.release_payout(bounty_id=bounty_id, idempotency_key="payout:retry")
            self.assertFalse(paid.get("failed", False))
            self.assertEqual(market.bounty_summary(bounty_id)["state"], "paid")
            self.assertTrue(market.reconciliation(project_id=project_id, solver_id=solver_id)["ok"])

    def test_stripe_webhook_signature_rejects_invalid_and_live_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect(Path(tmp) / "market.sqlite3")
            event = {"id": "evt_bad", "type": "payment_intent.succeeded", "livemode": False, "data": {"object": {"id": "pi_bad"}}}
            payload, _signature = signed_stripe_payload(event)
            with self.assertRaises(StripeWebhookError):
                record_stripe_webhook_event(
                    conn,
                    payload=payload,
                    signature_header="t=1800000000,v1=bad",
                    endpoint_secret="whsec_test",
                    now=1_800_000_000,
                )
            live_event = dict(event, id="evt_live", livemode=True)
            live_payload, live_signature = signed_stripe_payload(live_event)
            with self.assertRaises(StripeWebhookError):
                record_stripe_webhook_event(
                    conn,
                    payload=live_payload,
                    signature_header=live_signature,
                    endpoint_secret="whsec_test",
                    now=1_800_000_000,
                )


if __name__ == "__main__":
    unittest.main()
