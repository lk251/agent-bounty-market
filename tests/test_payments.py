from __future__ import annotations

import hashlib
import hmac
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from agent_bounty.core import AgentBountyMarket, MarketError
from agent_bounty.db import connect
from agent_bounty.cli import cmd_stripe_status, run_stripe_sandbox_smoke, stripe_reconcile_report
from agent_bounty.payments import (
    FakePaymentGateway,
    GatewayCredit,
    GatewayPayout,
    PaymentGatewayError,
    StripePaymentGateway,
    StripeTestConfig,
)
from agent_bounty.stripe_sandbox import FakeStripeClient, StripeSandboxConfig
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
                "latest_charge": {"id": "ch_test_funding", "object": "charge"},
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

    def release_payout(
        self,
        *,
        payout_id: str,
        solver_id: str,
        amount: int,
        currency: str,
        idempotency_key: str,
        source_transaction_id: str | None = None,
    ) -> GatewayPayout:
        return GatewayPayout(self.external_id, "pending", amount, currency, False)


class SourceRecordingGateway(FakePaymentGateway):
    def __init__(self):
        super().__init__()
        self.payout_source_transaction_id = None

    def credit_project_treasury(self, *, project_id: str, amount: int, currency: str, idempotency_key: str) -> GatewayCredit:
        return GatewayCredit("pi_source_test", amount, currency, False, "ch_source_test")

    def release_payout(
        self,
        *,
        payout_id: str,
        solver_id: str,
        amount: int,
        currency: str,
        idempotency_key: str,
        source_transaction_id: str | None = None,
    ) -> GatewayPayout:
        self.payout_source_transaction_id = source_transaction_id
        return GatewayPayout("tr_source_test", "paid", amount, currency, False)


def signed_stripe_payload(event: dict, *, secret: str = "whsec_test", timestamp: int = 1_800_000_000) -> tuple[bytes, str]:
    payload = json.dumps(event, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), f"{timestamp}.".encode("utf-8") + payload, hashlib.sha256).hexdigest()
    return payload, f"t={timestamp},v1={digest}"


def signed_current_payload(event: dict, *, secret: str = "whsec_test") -> tuple[bytes, str]:
    return signed_stripe_payload(event, secret=secret, timestamp=int(time.time()))


def make_market_with_gateway(verifier_dir: Path, gateway):
    tmp = tempfile.TemporaryDirectory()
    conn = connect(Path(tmp.name) / "market.sqlite3")
    market = AgentBountyMarket(conn, gateway, ProtectedVerifierRunner(verifier_dir=verifier_dir, timeout_seconds=5.0))
    return tmp, market


class PaymentTests(unittest.TestCase):
    def _stripe_market(self):
        tmp = tempfile.TemporaryDirectory()
        conn = connect(Path(tmp.name) / "market.sqlite3")
        market = AgentBountyMarket(conn, FakePaymentGateway(), ProtectedVerifierRunner(timeout_seconds=5.0))
        market.create_project(project_id="project_test", name="Test Project")
        return tmp, market

    def _checkout(self, market: AgentBountyMarket, client: FakeStripeClient, *, amount: int = 2500):
        return market.create_stripe_checkout(
            project_id="project_test",
            source_kind="owner",
            amount=amount,
            currency="USD",
            success_url="http://127.0.0.1:4242/success",
            cancel_url="http://127.0.0.1:4242/cancel",
            client=client,
            idempotency_key=f"checkout:{amount}",
        )

    def _payment_event(self, payment_intent_id: str, *, event_id: str = "evt_pi_succeeded") -> dict:
        return {
            "id": event_id,
            "type": "payment_intent.succeeded",
            "livemode": False,
            "data": {"object": {"id": payment_intent_id, "object": "payment_intent"}},
        }

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
        self.assertEqual(credit.source_transaction_id, "ch_test_funding")
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
        self.assertNotIn("source_transaction", transfer["data"])
        self.assertEqual(gateway.retrieve_payout_status(external_id="tr_test_payout"), "paid")

    def test_stripe_sandbox_smoke_uses_source_transaction_for_transfer(self):
        transport = RecordingStripeTransport()
        gateway = StripePaymentGateway(
            config=StripeTestConfig(secret_key="sk_test_123", solver_accounts={"solver_test": "acct_test_solver"}),
            explicitly_configured=True,
            transport=transport,
        )
        result = run_stripe_sandbox_smoke(
            gateway=gateway,
            project_id="project_test",
            solver_id="solver_test",
            amount=2500,
            currency="USD",
            run_id="unit",
        )

        transfer = transport.requests[1]
        self.assertEqual(result["funding"]["source_transaction_id"], "ch_test_funding")
        self.assertEqual(result["payout"]["transfer_id"], "tr_test_payout")
        self.assertEqual(result["payout"]["status"], "paid")
        self.assertEqual(transfer["data"]["source_transaction"], "ch_test_funding")

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

    def test_core_passes_stored_funding_source_transaction_to_gateway_payout(self):
        with tempfile.TemporaryDirectory() as tmp:
            verifier_dir = accepted_verifier(Path(tmp))
            gateway = SourceRecordingGateway()
            holder, market = make_market_with_gateway(verifier_dir, gateway)
            self.addCleanup(holder.cleanup)
            project_id, bounty_id, solver_id, submission_id = submit_ready(market)
            market.run_verification(submission_id=submission_id, idempotency_key="verify:test")
            payout = market.release_payout(bounty_id=bounty_id, idempotency_key="payout:test")

            self.assertEqual(gateway.payout_source_transaction_id, "ch_source_test")
            self.assertEqual(payout["gateway_payout_id"], "tr_source_test")
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

    def test_transfer_created_webhook_is_audit_only(self):
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

            self.assertEqual(first["action"], "transfer_created_audit")
            self.assertTrue(replay["replayed"])
            self.assertEqual(len(market.stripe_webhook_rows()), 1)
            self.assertEqual(len(market.ledger_rows()), ledger_count)
            self.assertEqual(market.bounty_summary(bounty_id)["state"], "payout_pending")
            self.assertTrue(market.reconciliation(project_id=project_id, solver_id=solver_id)["ok"])

    def test_transfer_reversed_records_manual_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            verifier_dir = accepted_verifier(Path(tmp))
            holder, market = make_market(verifier_dir)
            self.addCleanup(holder.cleanup)
            _project_id, bounty_id, _solver_id, submission_id = submit_ready(market)
            market.run_verification(submission_id=submission_id, idempotency_key="verify:test")
            paid = market.release_payout(bounty_id=bounty_id, idempotency_key="payout:first")

            event = {
                "id": "evt_transfer_reversed",
                "type": "transfer.reversed",
                "livemode": False,
                "data": {
                    "object": {
                        "id": paid["gateway_payout_id"],
                        "object": "transfer",
                    }
                },
            }
            payload, signature = signed_stripe_payload(event)
            reversed_result = market.ingest_stripe_webhook(
                payload=payload,
                signature_header=signature,
                endpoint_secret="whsec_test",
                now=1_800_000_000,
            )
            self.assertEqual(reversed_result["action"], "reversal_recorded")
            self.assertEqual(market.bounty_summary(bounty_id)["state"], "payout_failed")

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

    def test_stripe_checkout_creation_does_not_credit_treasury(self):
        holder, market = self._stripe_market()
        self.addCleanup(holder.cleanup)
        client = FakeStripeClient()
        checkout = self._checkout(market, client)
        self.assertTrue(checkout["checkout_session_id"].startswith("cs_test_"))
        self.assertEqual(market.ledger.balance("project:project_test:available"), 0)

    def test_automated_payment_creates_payment_intent_without_credit(self):
        holder, market = self._stripe_market()
        self.addCleanup(holder.cleanup)
        client = FakeStripeClient()
        result = market.create_stripe_automated_payment(
            project_id="project_test",
            source_kind="owner",
            amount=2500,
            currency="USD",
            payment_method="pm_card_visa",
            client=client,
            idempotency_key="automated:test",
        )
        self.assertTrue(result["payment_intent_id"].startswith("pi_test_"))
        self.assertTrue(result["charge_id"].startswith("ch_test_"))
        self.assertTrue(result["credit_requires_signed_webhook"])
        self.assertEqual(market.ledger.balance("project:project_test:available"), 0)
        self.assertEqual(client.created_payment_intent_params[0]["params"]["payment_method"], "pm_card_visa")

    def test_automated_payment_credits_only_after_signed_event(self):
        holder, market = self._stripe_market()
        self.addCleanup(holder.cleanup)
        client = FakeStripeClient()
        result = market.create_stripe_automated_payment(
            project_id="project_test",
            source_kind="owner",
            amount=2500,
            currency="USD",
            payment_method="pm_card_visa",
            client=client,
            idempotency_key="automated:test",
        )
        payload, signature = signed_current_payload(self._payment_event(result["payment_intent_id"]))
        credited = market.ingest_official_stripe_webhook(payload=payload, signature_header=signature, endpoint_secret="whsec_test", client=client)
        self.assertEqual(credited["action"], "funding_credited")
        self.assertEqual(market.ledger.balance("project:project_test:available"), 2500)

    def test_signed_payment_intent_credits_once(self):
        holder, market = self._stripe_market()
        self.addCleanup(holder.cleanup)
        client = FakeStripeClient()
        checkout = self._checkout(market, client)
        payload, signature = signed_current_payload(self._payment_event(checkout["payment_intent_id"]))
        first = market.ingest_official_stripe_webhook(payload=payload, signature_header=signature, endpoint_secret="whsec_test", client=client)
        replay = market.ingest_official_stripe_webhook(payload=payload, signature_header=signature, endpoint_secret="whsec_test", client=client)
        self.assertEqual(first["action"], "funding_credited")
        self.assertTrue(replay["replayed"])
        self.assertEqual(market.ledger.balance("project:project_test:available"), 2500)
        self.assertEqual(len([row for row in market.ledger_rows() if row["event_type"] == "project_funded"]), 1)

    def test_signed_webhook_can_record_then_process_after_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "market.sqlite3"
            conn = connect(db_path)
            market = AgentBountyMarket(conn, FakePaymentGateway(), ProtectedVerifierRunner(timeout_seconds=5.0))
            market.create_project(project_id="project_test", name="Test Project")
            client = FakeStripeClient()
            checkout = self._checkout(market, client)
            payload, signature = signed_current_payload(self._payment_event(checkout["payment_intent_id"]))
            recorded = market.record_official_stripe_webhook(payload=payload, signature_header=signature, endpoint_secret="whsec_test", client=client)
            self.assertEqual(recorded["status"], "recorded")
            self.assertEqual(market.ledger.balance("project:project_test:available"), 0)
            conn.close()
            restarted = AgentBountyMarket(connect(db_path), FakePaymentGateway(), ProtectedVerifierRunner(timeout_seconds=5.0))
            processed = restarted.process_stripe_event_row(event_id=recorded["event_id"], client=client)
            replay = restarted.process_stripe_event_row(event_id=recorded["event_id"], client=client)
            self.assertEqual(processed["action"], "funding_credited")
            self.assertTrue(replay["replayed"])
            self.assertEqual(restarted.ledger.balance("project:project_test:available"), 2500)

    def test_checkout_completed_and_payment_intent_succeeded_credit_once(self):
        holder, market = self._stripe_market()
        self.addCleanup(holder.cleanup)
        client = FakeStripeClient()
        checkout = self._checkout(market, client)
        checkout_event = {
            "id": "evt_checkout_completed",
            "type": "checkout.session.completed",
            "livemode": False,
            "data": {"object": {"id": checkout["checkout_session_id"], "object": "checkout.session"}},
        }
        payload, signature = signed_current_payload(checkout_event)
        first = market.ingest_official_stripe_webhook(payload=payload, signature_header=signature, endpoint_secret="whsec_test", client=client)
        payload2, signature2 = signed_current_payload(self._payment_event(checkout["payment_intent_id"], event_id="evt_pi_after_checkout"))
        second = market.ingest_official_stripe_webhook(payload=payload2, signature_header=signature2, endpoint_secret="whsec_test", client=client)
        self.assertEqual(first["action"], "funding_credited")
        self.assertEqual(second["action"], "funding_already_credited")
        self.assertEqual(market.ledger.balance("project:project_test:available"), 2500)

    def test_amount_currency_metadata_mismatch_requires_review_without_credit(self):
        holder, market = self._stripe_market()
        self.addCleanup(holder.cleanup)
        client = FakeStripeClient()
        checkout = self._checkout(market, client)
        client.payment_intents[checkout["payment_intent_id"]]["amount_received"] = 2400
        payload, signature = signed_current_payload(self._payment_event(checkout["payment_intent_id"]))
        result = market.ingest_official_stripe_webhook(payload=payload, signature_header=signature, endpoint_secret="whsec_test", client=client)
        row = market.conn.execute("SELECT status FROM funding_requests WHERE id = ?", (checkout["funding_request_id"],)).fetchone()
        self.assertEqual(result["action"], "funding_review_required")
        self.assertEqual(row["status"], "review_required")
        self.assertEqual(market.ledger.balance("project:project_test:available"), 0)

    def test_payment_failed_and_checkout_expired_do_not_credit(self):
        holder, market = self._stripe_market()
        self.addCleanup(holder.cleanup)
        client = FakeStripeClient()
        checkout = self._checkout(market, client)
        failed_event = {
            "id": "evt_pi_failed",
            "type": "payment_intent.payment_failed",
            "livemode": False,
            "data": {"object": client.payment_intents[checkout["payment_intent_id"]]},
        }
        payload, signature = signed_current_payload(failed_event)
        market.ingest_official_stripe_webhook(payload=payload, signature_header=signature, endpoint_secret="whsec_test", client=client)
        expired_event = {
            "id": "evt_checkout_expired",
            "type": "checkout.session.expired",
            "livemode": False,
            "data": {"object": client.checkout_sessions[checkout["checkout_session_id"]]},
        }
        payload2, signature2 = signed_current_payload(expired_event)
        market.ingest_official_stripe_webhook(payload=payload2, signature_header=signature2, endpoint_secret="whsec_test", client=client)
        self.assertEqual(market.ledger.balance("project:project_test:available"), 0)

    def test_operation_idempotency_rejects_parameter_changes(self):
        holder, market = self._stripe_market()
        self.addCleanup(holder.cleanup)
        client = FakeStripeClient()
        self._checkout(market, client, amount=2500)
        with self.assertRaises(MarketError):
            market.create_stripe_checkout(
                project_id="project_test",
                source_kind="owner",
                amount=2600,
                currency="USD",
                success_url="http://127.0.0.1:4242/success",
                cancel_url="http://127.0.0.1:4242/cancel",
                client=client,
                idempotency_key="checkout:2500",
            )

    def test_attach_beneficiary_validates_connected_account(self):
        holder, market = self._stripe_market()
        self.addCleanup(holder.cleanup)
        client = FakeStripeClient()
        result = market.attach_stripe_beneficiary(solver_id="solver_test", account_id="acct_solver_test", client=client)
        row = market.conn.execute("SELECT beneficiary_external_id FROM solver_identities WHERE id = 'solver_test'").fetchone()
        self.assertEqual(result["account_id"], "acct_solver_test")
        self.assertEqual(row["beneficiary_external_id"], "acct_solver_test")

    def test_stripe_transfer_requires_accepted_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            verifier_dir = accepted_verifier(Path(tmp))
            holder, market = make_market(verifier_dir)
            self.addCleanup(holder.cleanup)
            _project_id, bounty_id, solver_id, _submission_id = submit_ready(market)
            client = FakeStripeClient()
            market.attach_stripe_beneficiary(solver_id=solver_id, account_id="acct_solver_test", client=client)
            with self.assertRaises(MarketError):
                market.release_stripe_transfer(bounty_id=bounty_id, client=client)

    def test_stripe_transfer_creates_and_replays_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            verifier_dir = accepted_verifier(Path(tmp))
            holder, market = make_market(verifier_dir)
            self.addCleanup(holder.cleanup)
            project_id, bounty_id, solver_id, submission_id = submit_ready(market)
            market.run_verification(submission_id=submission_id, idempotency_key="verify:test")
            client = FakeStripeClient()
            market.attach_stripe_beneficiary(solver_id=solver_id, account_id="acct_solver_test", client=client)
            first = market.release_stripe_transfer(bounty_id=bounty_id, client=client, idempotency_key="stripe-transfer:test")
            replay = market.release_stripe_transfer(bounty_id=bounty_id, client=client, idempotency_key="stripe-transfer:test")
            self.assertTrue(first["transfer_id"].startswith("tr_test_"))
            self.assertTrue(replay["replayed"])
            self.assertEqual(market.bounty_summary(bounty_id)["state"], "paid")
            self.assertTrue(market.reconciliation(project_id=project_id, solver_id=solver_id)["ok"])
            transfer_params = client.created_transfer_params[0]["params"]
            self.assertEqual(transfer_params["metadata"]["receipt_id"], market.bounty_summary(bounty_id)["accepted_receipt_id"])

    def test_remote_reconciliation_retrieves_stripe_objects(self):
        with tempfile.TemporaryDirectory() as tmp:
            verifier_dir = accepted_verifier(Path(tmp))
            holder, market = make_market(verifier_dir)
            self.addCleanup(holder.cleanup)
            project_id, bounty_id, solver_id, submission_id = submit_ready(market)
            market.run_verification(submission_id=submission_id, idempotency_key="verify:test")
            client = FakeStripeClient()
            checkout = market.create_stripe_checkout(
                project_id=project_id,
                source_kind="owner",
                amount=2500,
                currency="USD",
                success_url="http://127.0.0.1:4242/success",
                cancel_url="http://127.0.0.1:4242/cancel",
                client=client,
                idempotency_key="checkout:reconcile",
            )
            payload, signature = signed_current_payload(self._payment_event(checkout["payment_intent_id"], event_id="evt_reconcile"))
            market.ingest_official_stripe_webhook(payload=payload, signature_header=signature, endpoint_secret="whsec_test", client=client)
            market.attach_stripe_beneficiary(solver_id=solver_id, account_id="acct_solver_test", client=client)
            market.release_stripe_transfer(bounty_id=bounty_id, client=client, idempotency_key="stripe-transfer:reconcile")
            report = stripe_reconcile_report(market, project_id=project_id, solver_id=solver_id, bounty_id=bounty_id, client=client)
            self.assertTrue(report["remote_checked"])
            self.assertTrue(report["remote_reconciled"])
            self.assertEqual(report["remote"]["mismatches"], [])
            kinds = {item["kind"] for item in report["remote"]["objects"]}
            self.assertIn("checkout.session", kinds)
            self.assertIn("payment_intent", kinds)
            self.assertIn("charge", kinds)
            self.assertIn("connected_account", kinds)
            self.assertIn("transfer", kinds)

    def test_remote_reconciliation_reports_transfer_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            verifier_dir = accepted_verifier(Path(tmp))
            holder, market = make_market(verifier_dir)
            self.addCleanup(holder.cleanup)
            project_id, bounty_id, solver_id, submission_id = submit_ready(market)
            market.run_verification(submission_id=submission_id, idempotency_key="verify:test")
            client = FakeStripeClient()
            market.attach_stripe_beneficiary(solver_id=solver_id, account_id="acct_solver_test", client=client)
            result = market.release_stripe_transfer(bounty_id=bounty_id, client=client, idempotency_key="stripe-transfer:mismatch-report")
            client.transfers[result["transfer_id"]]["amount"] = 1
            report = stripe_reconcile_report(market, project_id=project_id, solver_id=solver_id, bounty_id=bounty_id, client=client)
            self.assertFalse(report["remote_reconciled"])
            self.assertTrue(report["remote"]["mismatches"])

    def test_stripe_transfer_api_failure_records_failed_and_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            verifier_dir = accepted_verifier(Path(tmp))
            holder, market = make_market(verifier_dir)
            self.addCleanup(holder.cleanup)
            _project_id, bounty_id, solver_id, submission_id = submit_ready(market)
            market.run_verification(submission_id=submission_id, idempotency_key="verify:test")
            client = FakeStripeClient()
            market.attach_stripe_beneficiary(solver_id=solver_id, account_id="acct_solver_test", client=client)
            client.fail_next_transfer = "insufficient test balance"
            failed = market.release_stripe_transfer(bounty_id=bounty_id, client=client, idempotency_key="stripe-transfer:fail")
            self.assertTrue(failed["failed"])
            self.assertEqual(market.bounty_summary(bounty_id)["state"], "payout_failed")
            retry = market.release_stripe_transfer(bounty_id=bounty_id, client=client, idempotency_key="stripe-transfer:retry")
            self.assertFalse(retry.get("failed", False))

    def test_stripe_transfer_retrieval_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            verifier_dir = accepted_verifier(Path(tmp))
            holder, market = make_market(verifier_dir)
            self.addCleanup(holder.cleanup)
            _project_id, bounty_id, solver_id, submission_id = submit_ready(market)
            market.run_verification(submission_id=submission_id, idempotency_key="verify:test")
            client = FakeStripeClient()
            market.attach_stripe_beneficiary(solver_id=solver_id, account_id="acct_solver_test", client=client)
            original = client.retrieve_transfer
            def bad_retrieve(transfer_id):
                transfer = original(transfer_id)
                transfer["amount"] = 1
                return transfer
            client.retrieve_transfer = bad_retrieve
            result = market.release_stripe_transfer(bounty_id=bounty_id, client=client, idempotency_key="stripe-transfer:mismatch")
            self.assertTrue(result["failed"])

    def test_database_restart_preserves_stripe_event_idempotency(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "market.sqlite3"
            conn = connect(db_path)
            market = AgentBountyMarket(conn, FakePaymentGateway(), ProtectedVerifierRunner(timeout_seconds=5.0))
            market.create_project(project_id="project_test", name="Test Project")
            client = FakeStripeClient()
            checkout = self._checkout(market, client)
            payload, signature = signed_current_payload(self._payment_event(checkout["payment_intent_id"]))
            market.ingest_official_stripe_webhook(payload=payload, signature_header=signature, endpoint_secret="whsec_test", client=client)
            conn.close()
            restarted = AgentBountyMarket(connect(db_path), FakePaymentGateway(), ProtectedVerifierRunner(timeout_seconds=5.0))
            replay = restarted.ingest_official_stripe_webhook(payload=payload, signature_header=signature, endpoint_secret="whsec_test", client=client)
            self.assertTrue(replay["replayed"])
            self.assertEqual(restarted.ledger.balance("project:project_test:available"), 2500)

    def test_transfer_failed_event_is_not_handled_as_public_stripe_event(self):
        core_text = Path("agent_bounty/core.py").read_text(encoding="utf-8")
        self.assertNotIn("transfer.failed", core_text)

    def test_official_webhook_path_rejects_live_events(self):
        holder, market = self._stripe_market()
        self.addCleanup(holder.cleanup)
        client = FakeStripeClient()
        live_event = {
            "id": "evt_live_official",
            "type": "payment_intent.succeeded",
            "livemode": True,
            "data": {"object": {"id": "pi_live_bad", "object": "payment_intent", "livemode": True}},
        }
        payload, signature = signed_current_payload(live_event)
        with self.assertRaises(StripeWebhookError):
            market.ingest_official_stripe_webhook(payload=payload, signature_header=signature, endpoint_secret="whsec_test", client=client)

    def test_optional_real_stripe_integration_has_explicit_gate(self):
        if os.environ.get("AGENT_BOUNTY_STRIPE_SANDBOX") != "1" or os.environ.get("AGENT_BOUNTY_RUN_STRIPE_INTEGRATION") != "1":
            self.skipTest("set AGENT_BOUNTY_STRIPE_SANDBOX=1 and AGENT_BOUNTY_RUN_STRIPE_INTEGRATION=1 with Stripe test credentials")
        config = StripeSandboxConfig.from_env(dict(os.environ))
        config.require_enabled()


if __name__ == "__main__":
    unittest.main()
