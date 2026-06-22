from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

from agent_bounty.verification import ProtectedVerifierRunner


MOTOKO_REPO = Path("/home/mares/repos/motoko-issue-1-tui-input-latency")
BASE_COMMIT = "f4ebe1073d6fe7b9a1e2036e2a6e923ea0a68116"
INTERMEDIATE_COMMIT = "fdf54095b5cb8aca81984993bcd38176ccadad32"
FINAL_COMMIT = "4c03e0fa02a26f1cbadbe593ae687eaa9b333d2c"


def has_commit(repo: Path, commit: str) -> bool:
    if not repo.exists():
        return False
    result = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--verify", f"{commit}^{{commit}}"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


class MotokoIntegrationTests(unittest.TestCase):
    def test_real_motoko_issue_1_v2_contract_distinguishes_three_candidates(self):
        required = (BASE_COMMIT, INTERMEDIATE_COMMIT, FINAL_COMMIT)
        if not all(has_commit(MOTOKO_REPO, commit) for commit in required):
            self.skipTest("Motoko issue #1 fixture commits are not present")
        runner = ProtectedVerifierRunner(timeout_seconds=60)
        baseline = runner.run(
            bounty_id="bounty_motoko_issue_1",
            motoko_repo=MOTOKO_REPO,
            base_commit=BASE_COMMIT,
            candidate_commit=BASE_COMMIT,
        )
        self.assertFalse(baseline.accepted, baseline.result)
        intermediate = runner.run(
            bounty_id="bounty_motoko_issue_1",
            motoko_repo=MOTOKO_REPO,
            base_commit=BASE_COMMIT,
            candidate_commit=INTERMEDIATE_COMMIT,
        )
        self.assertFalse(intermediate.accepted, intermediate.result)
        self.assertIn("background_study", intermediate.metrics)
        final = runner.run(
            bounty_id="bounty_motoko_issue_1",
            motoko_repo=MOTOKO_REPO,
            base_commit=BASE_COMMIT,
            candidate_commit=FINAL_COMMIT,
        )
        self.assertTrue(final.accepted, final.result)
        self.assertLessEqual(final.metrics["short_transcript"]["p95_ms"], 30.0)
        self.assertLessEqual(final.metrics["long_transcript"]["p95_ms"], 40.0)
        self.assertLessEqual(final.metrics["background_study"]["p95_ms"], 50.0)
        self.assertLessEqual(final.metrics["background_study"]["max_ms"], 250.0)


if __name__ == "__main__":
    unittest.main()
