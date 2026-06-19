from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_bounty.core import MarketError
from agent_bounty.ledger import LedgerError

from tests.helpers import accepted_verifier, bootstrap_bounty, make_market


class StateMachineTests(unittest.TestCase):
    def test_insufficient_treasury_funds_cannot_reserve(self):
        with tempfile.TemporaryDirectory() as tmp:
            verifier_dir = accepted_verifier(Path(tmp))
            holder, market = make_market(verifier_dir)
            self.addCleanup(holder.cleanup)
            market.create_project(project_id="project_test", name="Test Project")
            market.fund_project(project_id="project_test", amount=100, idempotency_key="fund:low")
            market.create_bounty(
                bounty_id="bounty_test",
                project_id="project_test",
                title="Too expensive",
                reward_amount=200,
                currency="USD",
                base_commit="base",
                issue_ref="x#1",
                verifier_id="test",
            )
            with self.assertRaises(LedgerError):
                market.reserve_bounty(bounty_id="bounty_test", idempotency_key="reserve:low")

    def test_two_claims_cannot_own_exclusive_bounty(self):
        with tempfile.TemporaryDirectory() as tmp:
            verifier_dir = accepted_verifier(Path(tmp))
            holder, market = make_market(verifier_dir)
            self.addCleanup(holder.cleanup)
            _project_id, bounty_id, solver_id = bootstrap_bounty(market)
            market.create_solver(solver_id="solver_two", display_name="Second", idempotency_key="beneficiary:two")
            market.claim_bounty(
                bounty_id=bounty_id,
                solver_id=solver_id,
                lease_expires_at="2026-06-30T18:00:00Z",
                idempotency_key="claim:one",
            )
            with self.assertRaises(MarketError):
                market.claim_bounty(
                    bounty_id=bounty_id,
                    solver_id="solver_two",
                    lease_expires_at="2026-06-30T18:00:00Z",
                    idempotency_key="claim:two",
                )


if __name__ == "__main__":
    unittest.main()
