from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

from agent_bounty.verification import ProtectedVerifierRunner


MOTOKO_REPO = Path("/home/mares/repos/motoko-issue-1-tui-input-latency")
BASE_COMMIT = "f4ebe1073d6fe7b9a1e2036e2a6e923ea0a68116"
CANDIDATE_COMMIT = "fdf54095b5cb8aca81984993bcd38176ccadad32"


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
    def test_real_motoko_issue_1_candidate_is_accepted_when_fixture_exists(self):
        if not has_commit(MOTOKO_REPO, BASE_COMMIT) or not has_commit(MOTOKO_REPO, CANDIDATE_COMMIT):
            self.skipTest("Motoko issue #1 fixture commits are not present")
        result = ProtectedVerifierRunner(timeout_seconds=60).run(
            bounty_id="bounty_motoko_issue_1",
            motoko_repo=MOTOKO_REPO,
            base_commit=BASE_COMMIT,
            candidate_commit=CANDIDATE_COMMIT,
        )
        self.assertTrue(result.accepted, result.result)
        self.assertLessEqual(result.metrics["short_transcript"]["p95_ms"], 30.0)
        self.assertLessEqual(result.metrics["long_transcript"]["p95_ms"], 40.0)


if __name__ == "__main__":
    unittest.main()
