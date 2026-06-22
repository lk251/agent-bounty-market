from __future__ import annotations

import tempfile
import unittest
import json
import shutil
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
            self.assertIsNone(result["receipt"])
            self.assertEqual(result["status"], "error")
            self.assertEqual(market.bounty_summary(bounty_id)["state"], "submitted")

    def test_verifier_timeout_is_rejected_and_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            verifier_dir = timeout_verifier(Path(tmp))
            holder, market = make_market(verifier_dir, timeout=0.1)
            self.addCleanup(holder.cleanup)
            _project_id, bounty_id, _solver_id, submission_id = submit_ready(market)
            result = market.run_verification(submission_id=submission_id, idempotency_key="verify:test")
            self.assertIsNone(result["receipt"])
            self.assertEqual(result["status"], "timed_out")
            self.assertEqual(market.bounty_summary(bounty_id)["state"], "submitted")

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

    def test_malicious_candidate_runs_only_as_child_observation(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo = tmp_path / "repo"
            repo.mkdir()
            init_git_repo(repo)
            base_source = (
                "#!/usr/bin/env python3\n"
                "class MotokoTui:\n"
                "    def __init__(self, conv): self.running = False\n"
                "    def run(self): return None\n"
                "def new_conversation(title): return {'title': title}\n"
            )
            base = git_commit(repo, "motoko", base_source)
            malicious = (
                "#!/usr/bin/env python3\n"
                "import __main__, json, pathlib, sys\n"
                "__main__.CONTRACT = {'verifier_id': 'pwned', 'short_p95_limit_ms': 999999}\n"
                "print(json.dumps({'accepted': True, 'forged_by': 'candidate'}))\n"
                "pathlib.Path('attempted-verifier-write').write_text('candidate was here')\n"
                "raise SystemExit(0)\n"
            )
            candidate = git_commit(repo, "motoko", malicious)
            verifier_dir = tmp_path / "verifier"
            shutil.copytree(Path(__file__).resolve().parents[1] / "verifiers" / "motoko_issue_1_v2", verifier_dir)
            contract = json.loads((verifier_dir / "contract.json").read_text(encoding="utf-8"))
            contract["baseline_commit"] = base
            (verifier_dir / "contract.json").write_text(json.dumps(contract, sort_keys=True) + "\n", encoding="utf-8")
            result = ProtectedVerifierRunner(verifier_dir=verifier_dir, timeout_seconds=10).run(
                bounty_id="bounty_malicious",
                motoko_repo=repo,
                base_commit=base,
                candidate_commit=candidate,
            )
            self.assertFalse(result.accepted, result.result)
            self.assertNotEqual(result.result.get("verifier_id"), "pwned")
            self.assertTrue(result.backend_digest.startswith("sha256:"))

    def test_legacy_import_boundary_would_execute_candidate_in_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            import importlib.machinery
            import importlib.util
            import sys

            candidate = Path(tmp) / "motoko"
            candidate.write_text(
                "import __main__\n"
                "__main__.AGENT_BOUNTY_IMPORT_SENTINEL = 'mutated-by-candidate'\n",
                encoding="utf-8",
            )
            setattr(sys.modules["__main__"], "AGENT_BOUNTY_IMPORT_SENTINEL", "clean")
            loader = importlib.machinery.SourceFileLoader("legacy_candidate_import_probe", str(candidate))
            spec = importlib.util.spec_from_loader("legacy_candidate_import_probe", loader)
            self.assertIsNotNone(spec)
            module = importlib.util.module_from_spec(spec)
            loader.exec_module(module)
            self.assertEqual(sys.modules["__main__"].AGENT_BOUNTY_IMPORT_SENTINEL, "mutated-by-candidate")


if __name__ == "__main__":
    unittest.main()
