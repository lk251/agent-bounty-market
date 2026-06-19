from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
