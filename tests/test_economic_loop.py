from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_bounty.core import AgentBountyMarket
from agent_bounty.db import connect
from agent_bounty.economic_loop import (
    DEFAULT_SECOND_PROJECT_ID,
    DEFAULT_SECOND_VERIFIER_ID,
    EconomicLoopError,
    allocate_accepted_reward,
    default_solver_operating_policy,
    economic_loop_status_report,
    mark_settlement_transfer_reversed,
    run_demo_economic_loop,
    save_solver_operating_policy,
    spend_retained_credit_to_project,
)
from agent_bounty.ledger import (
    project_reserved_account,
    solver_earned_account,
    solver_operating_available_account,
    solver_paid_account,
)
from agent_bounty.payments import FakePaymentGateway
from agent_bounty.solver_agent import PYTHON_SOLVER_ID
from agent_bounty.verification import ProtectedVerifierRunner

from tests.helpers import CANDIDATE, accepted_verifier, rejected_verifier


MOTOKO_REPO = Path("/home/mares/repos/motoko-issue-1-tui-input-latency")


def make_market(db_path: Path, verifier_dir: Path) -> AgentBountyMarket:
    return AgentBountyMarket(connect(db_path), FakePaymentGateway(), ProtectedVerifierRunner(verifier_dir=verifier_dir, timeout_seconds=5.0))


def prepare_bounty(market: AgentBountyMarket, *, currency: str = "USD", accepted: bool = True) -> tuple[str, str, str, str | None]:
    project_id = "project_test"
    bounty_id = "bounty_test"
    solver_id = "solver_test"
    market.create_project(project_id=project_id, name="Test Project", currency=currency)
    market.set_budget_policy(
        project_id=project_id,
        max_bounty_amount=2500,
        monthly_budget=2500,
        human_approval_threshold=2500,
        allowed_issue_classes=["test"],
    )
    market.fund_project(project_id=project_id, amount=2500, currency=currency, idempotency_key=f"fund:{currency}")
    market.create_bounty(
        bounty_id=bounty_id,
        project_id=project_id,
        title="Test bounty",
        reward_amount=2500,
        currency=currency,
        base_commit="base",
        issue_ref="example/repo#1",
        verifier_id="test",
    )
    market.reserve_bounty(bounty_id=bounty_id, idempotency_key="reserve:test")
    market.create_solver(solver_id=solver_id, display_name="Test Solver", idempotency_key="beneficiary:test")
    market.claim_bounty(bounty_id=bounty_id, solver_id=solver_id, lease_expires_at="2026-06-30T18:00:00Z", idempotency_key="claim:test")
    submission = market.submit_candidate(
        bounty_id=bounty_id,
        solver_id=solver_id,
        candidate_repo_path="/tmp/candidate",
        candidate_commit=CANDIDATE,
        idempotency_key="submission:test",
    )
    verification = market.run_verification(submission_id=submission["submission_id"], idempotency_key="verify:test")
    receipt_id = verification.get("receipt_id") if accepted else None
    return project_id, bounty_id, solver_id, receipt_id


class EconomicLoopTests(unittest.TestCase):
    def test_default_settlement_is_full_external_transfer_without_retention(self):
        with tempfile.TemporaryDirectory() as tmp:
            verifier = accepted_verifier(Path(tmp))
            market = make_market(Path(tmp) / "market.sqlite3", verifier)
            _project_id, bounty_id, solver_id, _receipt_id = prepare_bounty(market)

            result = allocate_accepted_reward(market, bounty_id=bounty_id, idempotency_key="settle:full")
            replay = allocate_accepted_reward(market, bounty_id=bounty_id, idempotency_key="settle:full")

            self.assertTrue(result["ok"])
            self.assertTrue(replay["replayed"])
            self.assertEqual(result["external_transfer_amount"], 2500)
            self.assertEqual(result["retained_operating_amount"], 0)
            self.assertEqual(market.ledger.balance(solver_paid_account(solver_id)), 2500)
            self.assertEqual(market.ledger.balance(solver_earned_account(solver_id)), 0)
            self.assertFalse(str(result["gateway_transfer_id"]).startswith("tr_"))

    def test_retained_credit_requires_operator_consent_and_split_sums(self):
        with tempfile.TemporaryDirectory() as tmp:
            verifier = accepted_verifier(Path(tmp))
            market = make_market(Path(tmp) / "market.sqlite3", verifier)
            _project_id, bounty_id, solver_id, _receipt_id = prepare_bounty(market)

            with self.assertRaises(EconomicLoopError):
                allocate_accepted_reward(
                    market,
                    bounty_id=bounty_id,
                    external_transfer_amount=2000,
                    retained_operating_amount=500,
                    retention_consent=False,
                    idempotency_key="settle:denied",
                )

            result = allocate_accepted_reward(
                market,
                bounty_id=bounty_id,
                external_transfer_amount=2000,
                retained_operating_amount=500,
                platform_fee_amount=0,
                retention_consent=True,
                idempotency_key="settle:split",
            )

            self.assertTrue(result["ok"])
            self.assertEqual(result["reward_amount"], result["external_transfer_amount"] + result["retained_operating_amount"] + result["platform_fee_amount"])
            self.assertEqual(market.ledger.balance(solver_paid_account(solver_id)), 2000)
            self.assertEqual(market.ledger.balance(solver_operating_available_account(solver_id)), 500)
            payout = market.conn.execute("SELECT * FROM payouts WHERE bounty_id = ?", (bounty_id,)).fetchone()
            self.assertEqual(int(payout["amount"]), 2000)

    def test_cross_currency_split_uses_bounty_currency(self):
        with tempfile.TemporaryDirectory() as tmp:
            verifier = accepted_verifier(Path(tmp))
            market = make_market(Path(tmp) / "market.sqlite3", verifier)
            _project_id, bounty_id, solver_id, _receipt_id = prepare_bounty(market, currency="EUR")

            result = allocate_accepted_reward(
                market,
                bounty_id=bounty_id,
                external_transfer_amount=1500,
                retained_operating_amount=1000,
                retention_consent=True,
                idempotency_key="settle:eur",
            )

            self.assertEqual(result["currency"], "EUR")
            self.assertEqual(market.ledger.balance(solver_paid_account(solver_id), "EUR"), 1500)
            self.assertEqual(market.ledger.balance(solver_operating_available_account(solver_id), "EUR"), 1000)

    def test_transfer_failure_retry_and_reversal_are_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            verifier = accepted_verifier(Path(tmp))
            market = make_market(Path(tmp) / "market.sqlite3", verifier)
            _project_id, bounty_id, solver_id, _receipt_id = prepare_bounty(market)

            failed = allocate_accepted_reward(
                market,
                bounty_id=bounty_id,
                external_transfer_amount=2000,
                retained_operating_amount=500,
                retention_consent=True,
                idempotency_key="settle:retry",
                simulate_transfer_failure=True,
            )
            self.assertFalse(failed["ok"])
            self.assertEqual(market.ledger.balance(solver_earned_account(solver_id)), 2500)

            paid = allocate_accepted_reward(
                market,
                bounty_id=bounty_id,
                external_transfer_amount=2000,
                retained_operating_amount=500,
                retention_consent=True,
                idempotency_key="settle:retry",
            )
            reversed_once = mark_settlement_transfer_reversed(market, gateway_transfer_id=paid["gateway_transfer_id"], reason="test")
            reversed_twice = mark_settlement_transfer_reversed(market, gateway_transfer_id=paid["gateway_transfer_id"], reason="test")

            self.assertTrue(paid["ok"])
            self.assertEqual(reversed_once["action"], "reversal_recorded")
            self.assertEqual(reversed_twice["action"], "already_reversed")
            row = market.conn.execute("SELECT transfer_status FROM settlement_allocations WHERE id = ?", (paid["allocation_id"],)).fetchone()
            self.assertEqual(row["transfer_status"], "reversed")

    def test_retained_credit_spend_publishes_second_bounty_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            verifier = accepted_verifier(Path(tmp))
            market = make_market(Path(tmp) / "market.sqlite3", verifier)
            _project_id, bounty_id, solver_id, _receipt_id = prepare_bounty(market)
            allocate_accepted_reward(
                market,
                bounty_id=bounty_id,
                external_transfer_amount=2000,
                retained_operating_amount=500,
                retention_consent=True,
                idempotency_key="settle:spend",
            )
            save_solver_operating_policy(market, default_solver_operating_policy(solver_id=solver_id, allowed_currencies=["USD"]))

            spend = spend_retained_credit_to_project(
                market,
                solver_id=solver_id,
                target_project_id=DEFAULT_SECOND_PROJECT_ID,
                repo_full_name="lk251/motoko",
                amount=500,
                currency="USD",
                title="Second bounty",
                issue_class="machine-verifiable-tui-regression",
                verifier_id=DEFAULT_SECOND_VERIFIER_ID,
                idempotency_key="spend:test",
            )
            replay = spend_retained_credit_to_project(
                market,
                solver_id=solver_id,
                target_project_id=DEFAULT_SECOND_PROJECT_ID,
                repo_full_name="lk251/motoko",
                amount=500,
                currency="USD",
                title="Second bounty",
                issue_class="machine-verifiable-tui-regression",
                verifier_id=DEFAULT_SECOND_VERIFIER_ID,
                idempotency_key="spend:test",
            )

            self.assertTrue(spend["ok"])
            self.assertTrue(replay["replayed"])
            self.assertTrue(str(spend["contract_digest"]).startswith("sha256:"))
            self.assertEqual(market.ledger.balance(project_reserved_account(DEFAULT_SECOND_PROJECT_ID)), 500)
            self.assertEqual(market.ledger.balance(solver_operating_available_account(solver_id)), 0)

    def test_spend_policy_denies_arbitrary_repo_and_insufficient_balance(self):
        with tempfile.TemporaryDirectory() as tmp:
            verifier = accepted_verifier(Path(tmp))
            market = make_market(Path(tmp) / "market.sqlite3", verifier)
            _project_id, bounty_id, solver_id, _receipt_id = prepare_bounty(market)
            allocate_accepted_reward(
                market,
                bounty_id=bounty_id,
                external_transfer_amount=2400,
                retained_operating_amount=100,
                retention_consent=True,
                idempotency_key="settle:small",
            )
            save_solver_operating_policy(market, default_solver_operating_policy(solver_id=solver_id, max_spend_cents=500, human_approval_threshold_cents=500, allowed_currencies=["USD"]))

            with self.assertRaises(EconomicLoopError):
                spend_retained_credit_to_project(
                    market,
                    solver_id=solver_id,
                    target_project_id=DEFAULT_SECOND_PROJECT_ID,
                    repo_full_name="evil/repo",
                    amount=100,
                    currency="USD",
                    title="Bad repo",
                    issue_class="machine-verifiable-tui-regression",
                    verifier_id=DEFAULT_SECOND_VERIFIER_ID,
                    idempotency_key="spend:bad-repo",
                )
            with self.assertRaises(EconomicLoopError):
                spend_retained_credit_to_project(
                    market,
                    solver_id=solver_id,
                    target_project_id=DEFAULT_SECOND_PROJECT_ID,
                    repo_full_name="lk251/motoko",
                    amount=500,
                    currency="USD",
                    title="Too much",
                    issue_class="machine-verifiable-tui-regression",
                    verifier_id=DEFAULT_SECOND_VERIFIER_ID,
                    idempotency_key="spend:too-much",
                )

    def test_rejected_work_cannot_be_settled(self):
        with tempfile.TemporaryDirectory() as tmp:
            verifier = rejected_verifier(Path(tmp))
            market = make_market(Path(tmp) / "market.sqlite3", verifier)
            _project_id, bounty_id, solver_id, receipt_id = prepare_bounty(market, accepted=False)

            self.assertIsNone(receipt_id)
            self.assertEqual(market.ledger.balance(solver_earned_account(solver_id)), 0)
            with self.assertRaises(EconomicLoopError):
                allocate_accepted_reward(market, bounty_id=bounty_id, idempotency_key="settle:rejected")

    def test_status_report_does_not_claim_real_split_transfer(self):
        status = economic_loop_status_report()
        self.assertTrue(status["deterministic_fake_loop_available"])
        self.assertFalse(status["prior_real_stripe_evidence"]["transfer"].startswith("fake"))
        self.assertIn("real split Stripe transfer is not claimed", status["split_settlement_adapter"])

    def test_full_deterministic_economic_loop_demo(self):
        if not MOTOKO_REPO.exists():
            self.skipTest("external Motoko issue #1 fixture repo is unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            market = AgentBountyMarket(connect(Path(tmp) / "market.sqlite3"), FakePaymentGateway())
            result = run_demo_economic_loop(market, motoko_repo=MOTOKO_REPO)

            self.assertTrue(result["ok"])
            self.assertFalse(result["provider_truth"]["real_stripe_transfer_claimed"])
            self.assertEqual(result["allocation"]["external_transfer_amount"], 2000)
            self.assertEqual(result["allocation"]["retained_operating_amount"], 500)
            self.assertTrue(result["retained_credit_spend_replay"]["replayed"])
            self.assertTrue(str(result["second_bounty"]["contract_digest"]).startswith("sha256:"))


if __name__ == "__main__":
    unittest.main()
