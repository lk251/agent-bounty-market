from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_bounty.verification import ProtectedVerifierRunner
from agent_bounty.core import MarketError

from tests.helpers import (
    accepted_verifier,
    git_commit,
    init_git_repo,
    malformed_verifier,
    make_market,
    rejected_verifier,
    submit_ready,
    timeout_verifier,
)


class VerificationTests(unittest.TestCase):
    def test_failed_verifier_creates_rejection_receipt_and_no_payout(self):
        with tempfile.TemporaryDirectory() as tmp:
            verifier_dir = rejected_verifier(Path(tmp))
            holder, market = make_market(verifier_dir)
            self.addCleanup(holder.cleanup)
            _project_id, bounty_id, _solver_id, submission_id = submit_ready(market)
            result = market.run_verification(submission_id=submission_id, idempotency_key="verify:test")
            self.assertFalse(result["receipt"]["accepted"])
            self.assertEqual(market.bounty_summary(bounty_id)["state"], "rejected")
            self.assertIsNone(market.bounty_summary(bounty_id)["payout_id"])

    def test_candidate_supplied_verifier_code_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            candidate = Path(tmp) / "candidate"
            (candidate / "tests").mkdir(parents=True)
            (candidate / "tests" / "bounty_issue_1.py").write_text("print('malicious self approval')\n")
            verifier_dir = rejected_verifier(Path(tmp) / "platform")
            holder, market = make_market(verifier_dir)
            self.addCleanup(holder.cleanup)
            _project_id, _bounty_id, _solver_id, submission_id = submit_ready(market, candidate_repo=str(candidate))
            result = market.run_verification(submission_id=submission_id, idempotency_key="verify:test")
            self.assertFalse(result["receipt"]["accepted"])
            row = market.conn.execute("SELECT result_json FROM verification_runs WHERE id = ?", (result["run_id"],)).fetchone()
            self.assertIn("forced rejection", row["result_json"])


    def test_malformed_verifier_json_is_rejected_and_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            verifier_dir = malformed_verifier(Path(tmp))
            holder, market = make_market(verifier_dir)
            self.addCleanup(holder.cleanup)
            _project_id, bounty_id, _solver_id, submission_id = submit_ready(market)
            result = market.run_verification(submission_id=submission_id, idempotency_key="verify:test")
            self.assertFalse(result["receipt"]["accepted"])
            self.assertEqual(market.bounty_summary(bounty_id)["state"], "rejected")

    def test_verifier_timeout_is_rejected_and_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            verifier_dir = timeout_verifier(Path(tmp))
            holder, market = make_market(verifier_dir, timeout=0.1)
            self.addCleanup(holder.cleanup)
            _project_id, bounty_id, _solver_id, submission_id = submit_ready(market)
            result = market.run_verification(submission_id=submission_id, idempotency_key="verify:test")
            self.assertFalse(result["receipt"]["accepted"])
            self.assertEqual(market.bounty_summary(bounty_id)["state"], "rejected")

    def test_accepted_receipt_for_one_sha_cannot_authorize_another_sha(self):
        with tempfile.TemporaryDirectory() as tmp:
            verifier_dir = accepted_verifier(Path(tmp))
            holder, market = make_market(verifier_dir)
            self.addCleanup(holder.cleanup)
            _project_id, bounty_id, _solver_id, submission_id = submit_ready(market)
            result = market.run_verification(submission_id=submission_id, idempotency_key="verify:test")
            self.assertTrue(result["receipt"]["accepted"])
            market.conn.execute(
                "UPDATE submissions SET candidate_commit = ? WHERE id = ?",
                ("candidate-replay", submission_id),
            )
            with self.assertRaises(MarketError):
                market.release_payout(bounty_id=bounty_id, idempotency_key="payout:test")

    def test_real_verifier_rejects_mismatched_base_candidate_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            init_git_repo(repo)
            base = git_commit(repo, "base.txt", "base\n")
            # Create an unrelated orphan candidate so base is not an ancestor.
            import subprocess

            subprocess.run(["git", "-C", str(repo), "checkout", "--orphan", "other"], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(repo), "rm", "-rf", "."], check=True, capture_output=True)
            candidate = git_commit(repo, "candidate.txt", "candidate\n")
            result = ProtectedVerifierRunner(timeout_seconds=5).run(
                bounty_id="bounty_test",
                motoko_repo=repo,
                base_commit=base,
                candidate_commit=candidate,
            )
            self.assertFalse(result.accepted)
            message = " ".join(result.result.get("failure_reasons", [])) + result.result.get("error", "")
            self.assertTrue("ancestor" in message or "contract" in message, message)


if __name__ == "__main__":
    unittest.main()
