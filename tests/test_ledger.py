from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_bounty.core import AgentBountyMarket
from agent_bounty.db import connect
from agent_bounty.payments import FakePaymentGateway
from agent_bounty.verification import ProtectedVerifierRunner
from tests.helpers import accepted_verifier, make_market, submit_ready


class LedgerTests(unittest.TestCase):
    def test_happy_path_pays_exactly_once_and_reconciles(self):
        with tempfile.TemporaryDirectory() as tmp:
            verifier_dir = accepted_verifier(Path(tmp))
            holder, market = make_market(verifier_dir)
            self.addCleanup(holder.cleanup)
            project_id, bounty_id, solver_id, submission_id = submit_ready(market)
            verification = market.run_verification(submission_id=submission_id, idempotency_key="verify:test")
            self.assertTrue(verification["receipt"]["accepted"])
            payout = market.release_payout(bounty_id=bounty_id, idempotency_key="payout:test")
            first_gateway_id = payout["gateway_payout_id"]
            first_ledger_count = len(market.ledger_rows())

            replay_verify = market.run_verification(submission_id=submission_id, idempotency_key="verify:test")
            replay_payout = market.release_payout(bounty_id=bounty_id, idempotency_key="payout:test")
            self.assertTrue(replay_verify["replayed"])
            self.assertTrue(replay_payout["replayed"])
            self.assertEqual(replay_payout["gateway_payout_id"], first_gateway_id)
            self.assertEqual(len(market.ledger_rows()), first_ledger_count)

            reconciliation = market.reconciliation(project_id=project_id, solver_id=solver_id)
            self.assertTrue(reconciliation["ok"], reconciliation)
            self.assertEqual(reconciliation["balances"]["project_available"], 0)
            self.assertEqual(reconciliation["balances"]["project_reserved"], 0)
            self.assertEqual(reconciliation["balances"]["solver_paid"], 2500)
            summary = market.bounty_summary(bounty_id)
            self.assertEqual(summary["state"], "paid")
            self.assertEqual(summary["accepted_receipt_id"], verification["receipt_id"])
            self.assertEqual(summary["verifier_digest"], verification["receipt"]["verifier_digest"])
            self.assertEqual(summary["receipt"]["candidate_commit"], "candidate")
            self.assertEqual(summary["receipt"]["solver_id"], solver_id)

            # Scripted demos replay their whole command sequence, including
            # bounty creation, after the bounty may already be paid.
            market.create_bounty(
                bounty_id=bounty_id,
                project_id=project_id,
                title="Test bounty",
                reward_amount=2500,
                currency="USD",
                base_commit="base",
                issue_ref="example/repo#1",
                verifier_id="test",
            )
            self.assertEqual(market.bounty_summary(bounty_id)["state"], "paid")

    def test_database_rejects_negative_internal_account_balance(self):
        with tempfile.TemporaryDirectory() as tmp:
            verifier_dir = accepted_verifier(Path(tmp))
            holder, market = make_market(verifier_dir)
            self.addCleanup(holder.cleanup)
            with self.assertRaises(Exception):
                market.conn.execute(
                    """
                    INSERT INTO account_balances(account, currency, balance, allow_negative)
                    VALUES ('project:x:available', 'USD', -1, 0)
                    """
                )

    def test_process_restart_preserves_idempotency(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            verifier_dir = accepted_verifier(root)
            db_path = root / "market.sqlite3"
            market = AgentBountyMarket(
                connect(db_path),
                FakePaymentGateway(),
                ProtectedVerifierRunner(verifier_dir=verifier_dir),
            )
            project_id, bounty_id, solver_id, submission_id = submit_ready(market)
            verification = market.run_verification(submission_id=submission_id, idempotency_key="verify:test")
            payout = market.release_payout(bounty_id=bounty_id, idempotency_key="payout:test")
            market.conn.close()

            restarted = AgentBountyMarket(
                connect(db_path),
                FakePaymentGateway(),
                ProtectedVerifierRunner(verifier_dir=verifier_dir),
            )
            funding = restarted.fund_project(project_id=project_id, amount=2500, idempotency_key="fund:test")
            reserve = restarted.reserve_bounty(bounty_id=bounty_id, idempotency_key="reserve:test")
            replay_verify = restarted.run_verification(submission_id=submission_id, idempotency_key="verify:test")
            replay_payout = restarted.release_payout(bounty_id=bounty_id, idempotency_key="payout:test")
            self.assertTrue(funding["replayed"])
            self.assertTrue(reserve["replayed"])
            self.assertTrue(replay_verify["replayed"])
            self.assertTrue(replay_payout["replayed"])
            self.assertEqual(replay_verify["receipt_id"], verification["receipt_id"])
            self.assertEqual(replay_payout["gateway_payout_id"], payout["gateway_payout_id"])
            self.assertTrue(restarted.reconciliation(project_id=project_id, solver_id=solver_id)["ok"])


if __name__ == "__main__":
    unittest.main()
