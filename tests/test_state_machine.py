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

    def test_idempotency_keys_are_bound_to_original_arguments(self):
        with tempfile.TemporaryDirectory() as tmp:
            verifier_dir = accepted_verifier(Path(tmp))
            holder, market = make_market(verifier_dir)
            self.addCleanup(holder.cleanup)
            market.create_project(project_id="project_test", name="Test Project", currency="USD")
            market.fund_project(project_id="project_test", amount=2500, currency="USD", idempotency_key="fund:test")
            with self.assertRaises(MarketError):
                market.fund_project(project_id="project_test", amount=2600, currency="USD", idempotency_key="fund:test")
            market.create_bounty(
                bounty_id="bounty_test",
                project_id="project_test",
                title="Test bounty",
                reward_amount=2500,
                currency="USD",
                base_commit="base",
                issue_ref="example/repo#1",
                verifier_id="test",
            )
            market.reserve_bounty(bounty_id="bounty_test", idempotency_key="reserve:test")
            market.create_solver(solver_id="solver_test", display_name="Test Solver", idempotency_key="beneficiary:test")
            claim = market.claim_bounty(
                bounty_id="bounty_test",
                solver_id="solver_test",
                lease_expires_at="2026-06-30T18:00:00Z",
                idempotency_key="claim:test",
            )
            with self.assertRaises(MarketError):
                market.claim_bounty(
                    bounty_id="bounty_test",
                    solver_id="solver_other",
                    lease_expires_at="2026-06-30T18:00:00Z",
                    idempotency_key="claim:test",
                )
            submission = market.submit_candidate(
                bounty_id="bounty_test",
                solver_id="solver_test",
                candidate_repo_path="/tmp/candidate",
                candidate_commit="candidate-a",
                idempotency_key="submission:test",
            )
            with self.assertRaises(MarketError):
                market.submit_candidate(
                    bounty_id="bounty_test",
                    solver_id="solver_test",
                    candidate_repo_path="/tmp/candidate",
                    candidate_commit="candidate-b",
                    idempotency_key="submission:test",
                )
            verification = market.run_verification(submission_id=submission["submission_id"], idempotency_key="verify:test")
            self.assertTrue(verification["receipt"]["accepted"])
            with self.assertRaises(MarketError):
                market.run_verification(submission_id="submission_other", idempotency_key="verify:test")

    def test_treasury_and_bounty_currency_must_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            verifier_dir = accepted_verifier(Path(tmp))
            holder, market = make_market(verifier_dir)
            self.addCleanup(holder.cleanup)
            market.create_project(project_id="project_test", name="Test Project", currency="USD")
            with self.assertRaises(MarketError):
                market.fund_project(project_id="project_test", amount=2500, currency="EUR", idempotency_key="fund:eur")
            with self.assertRaises(MarketError):
                market.create_bounty(
                    bounty_id="bounty_test",
                    project_id="project_test",
                    title="Wrong currency",
                    reward_amount=2500,
                    currency="EUR",
                    base_commit="base",
                    issue_ref="example/repo#1",
                    verifier_id="test",
                )

    def test_cancel_expire_and_refund_paths_are_reachable_and_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            verifier_dir = accepted_verifier(Path(tmp))
            holder, market = make_market(verifier_dir)
            self.addCleanup(holder.cleanup)
            project_id, bounty_id, solver_id = bootstrap_bounty(market)
            cancelled = market.cancel_bounty(bounty_id=bounty_id, idempotency_key="cancel:test")
            self.assertEqual(cancelled["state"], "cancelled")
            refunded = market.refund_bounty(bounty_id=bounty_id, idempotency_key="refund:test")
            self.assertEqual(refunded["state"], "refunded")
            replay = market.refund_bounty(bounty_id=bounty_id, idempotency_key="refund:test")
            self.assertTrue(replay["replayed"])
            reconciliation = market.reconciliation(project_id=project_id, solver_id=solver_id)
            self.assertTrue(reconciliation["ok"], reconciliation)
            self.assertEqual(reconciliation["balances"]["project_refunded"], 2500)

    def test_expired_bounty_can_refund_reserved_funds(self):
        with tempfile.TemporaryDirectory() as tmp:
            verifier_dir = accepted_verifier(Path(tmp))
            holder, market = make_market(verifier_dir)
            self.addCleanup(holder.cleanup)
            project_id, bounty_id, solver_id = bootstrap_bounty(market)
            market.expire_bounty(bounty_id=bounty_id, idempotency_key="expire:test")
            market.refund_bounty(bounty_id=bounty_id, idempotency_key="refund:expired")
            reconciliation = market.reconciliation(project_id=project_id, solver_id=solver_id)
            self.assertTrue(reconciliation["ok"], reconciliation)
            self.assertEqual(reconciliation["balances"]["project_refunded"], 2500)


if __name__ == "__main__":
    unittest.main()
