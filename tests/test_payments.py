from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_bounty.core import MarketError

from tests.helpers import accepted_verifier, make_market, submit_ready


class PaymentTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
