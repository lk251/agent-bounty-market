from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_bounty.core import AgentBountyMarket, MarketError, new_id
from agent_bounty.db import connect
from agent_bounty.domain import BountyState
from agent_bounty.payments import FakePaymentGateway
from agent_bounty.verification import ProtectedVerifierRunner
from tests.helpers import accepted_verifier, make_market, submit_ready, timeout_verifier


class VerificationRecoveryTests(unittest.TestCase):
    def _reopen(self, tmp_holder: tempfile.TemporaryDirectory, verifier_dir: Path, *, timeout: float = 5.0) -> AgentBountyMarket:
        conn = connect(Path(tmp_holder.name) / "market.sqlite3")
        return AgentBountyMarket(conn, FakePaymentGateway(), ProtectedVerifierRunner(verifier_dir=verifier_dir, timeout_seconds=timeout))

    def _insert_running_run(self, market: AgentBountyMarket, *, submission_id: str, idempotency_key: str) -> str:
        submission = market.conn.execute("SELECT * FROM submissions WHERE id = ?", (submission_id,)).fetchone()
        bounty = market.conn.execute("SELECT * FROM bounties WHERE id = ?", (submission["bounty_id"],)).fetchone()
        run_id = new_id("vrun")
        with market.conn:
            market._transition_bounty(
                submission["bounty_id"],
                BountyState.VERIFYING,
                reason="test_crash_after_run_creation",
                idempotency_key=f"state:{idempotency_key}:verifying",
            )
            market.conn.execute(
                """
                INSERT INTO verification_runs(id, bounty_id, submission_id, status, verifier_id, started_at, idempotency_key)
                VALUES (?, ?, ?, 'running', ?, '2026-06-22T00:00:00Z', ?)
                """,
                (run_id, submission["bounty_id"], submission_id, bounty["verifier_id"], idempotency_key),
            )
        return run_id

    def test_running_without_receipt_recovers_after_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            verifier_dir = accepted_verifier(Path(tmp) / "verifier")
            holder, market = make_market(verifier_dir)
            self.addCleanup(holder.cleanup)
            _project_id, bounty_id, _solver_id, submission_id = submit_ready(market)
            run_id = self._insert_running_run(market, submission_id=submission_id, idempotency_key="verify:test")
            market.conn.close()
            reopened = self._reopen(holder, verifier_dir)
            result = reopened.run_verification(submission_id=submission_id, idempotency_key="verify:test")
            self.assertFalse(result["replayed"])
            self.assertEqual(result["run_id"], run_id)
            self.assertTrue(result["receipt"]["accepted"])
            self.assertEqual(reopened.bounty_summary(bounty_id)["state"], "accepted")

    def test_completed_replay_returns_same_receipt_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            verifier_dir = accepted_verifier(Path(tmp))
            holder, market = make_market(verifier_dir)
            self.addCleanup(holder.cleanup)
            _project_id, _bounty_id, _solver_id, submission_id = submit_ready(market)
            first = market.run_verification(submission_id=submission_id, idempotency_key="verify:test")
            second = market.run_verification(submission_id=submission_id, idempotency_key="verify:test")
            self.assertTrue(second["replayed"])
            self.assertEqual(first["receipt_id"], second["receipt_id"])
            count = market.conn.execute("SELECT COUNT(*) FROM verification_receipts").fetchone()[0]
            self.assertEqual(count, 1)

    def test_timeout_exits_verifying_and_cannot_pay(self):
        with tempfile.TemporaryDirectory() as tmp:
            verifier_dir = timeout_verifier(Path(tmp))
            holder, market = make_market(verifier_dir, timeout=0.1)
            self.addCleanup(holder.cleanup)
            _project_id, bounty_id, _solver_id, submission_id = submit_ready(market)
            result = market.run_verification(submission_id=submission_id, idempotency_key="verify:test")
            self.assertEqual(result["status"], "timed_out")
            self.assertIsNone(result["receipt_id"])
            self.assertEqual(market.bounty_summary(bounty_id)["state"], "submitted")
            with self.assertRaises(MarketError):
                market.release_payout(bounty_id=bounty_id, idempotency_key="payout:test")

    def test_receipt_binds_backend_and_policy_digests(self):
        with tempfile.TemporaryDirectory() as tmp:
            verifier_dir = accepted_verifier(Path(tmp))
            holder, market = make_market(verifier_dir)
            self.addCleanup(holder.cleanup)
            _project_id, bounty_id, _solver_id, submission_id = submit_ready(market)
            result = market.run_verification(submission_id=submission_id, idempotency_key="verify:test")
            receipt = result["receipt"]
            self.assertTrue(receipt["backend_digest"].startswith("sha256:"))
            self.assertTrue(receipt["policy_digest"].startswith("sha256:"))
            market.conn.execute(
                "UPDATE verification_receipts SET policy_digest = NULL WHERE id = ?",
                (result["receipt_id"],),
            )
            with self.assertRaises(MarketError):
                market.release_payout(bounty_id=bounty_id, idempotency_key="payout:test")


if __name__ == "__main__":
    unittest.main()
