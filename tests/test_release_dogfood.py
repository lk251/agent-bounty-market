from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from agent_bounty.release_dogfood import (
    RELEASE_DOGFOOD_REWARD_CENTS,
    RELEASE_DOGFOOD_SCHEMA,
    open_release_dogfood_market,
    release_dogfood_report,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


class ReleaseDogfoodTests(unittest.TestCase):
    def test_release_provenance_issue_is_funded_verified_settled_and_replay_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            candidate_repo = copy_current_tree_to_git_repo(Path(tmp) / "candidate")
            candidate_sha = git(candidate_repo, "rev-parse", "HEAD")
            market = open_release_dogfood_market(Path(tmp) / "market.sqlite3")

            result = release_dogfood_report(market, candidate_repo=candidate_repo, candidate_sha=candidate_sha, issue_number=21)

        self.assertEqual(result["schema"], RELEASE_DOGFOOD_SCHEMA)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["candidate_sha"], candidate_sha)
        self.assertEqual(result["source_retained_credit"]["retained_operating_amount"], RELEASE_DOGFOOD_REWARD_CENTS)
        self.assertTrue(result["source_retained_credit"]["allocation_replayed"])
        self.assertEqual(result["retained_credit_spend"]["amount"], RELEASE_DOGFOOD_REWARD_CENTS)
        self.assertTrue(result["retained_credit_spend"]["replay_reused_spend"])
        self.assertTrue(result["accepted_verification"]["accepted"])
        self.assertEqual(result["accepted_verification"]["candidate_commit"], candidate_sha)
        self.assertEqual(result["second_settlement"]["external_transfer_amount"], RELEASE_DOGFOOD_REWARD_CENTS)
        self.assertEqual(result["second_settlement"]["retained_operating_amount"], 0)
        self.assertTrue(result["second_settlement"]["replay_reused_allocation"])
        self.assertTrue(str(result["evidence_digest"]).startswith("sha256:"))


def copy_current_tree_to_git_repo(target: Path) -> Path:
    def ignore(_dir: str, names: list[str]) -> set[str]:
        ignored = {".git", ".demo", "__pycache__", ".pytest_cache"}
        return {name for name in names if name in ignored or name.endswith(".pyc")}

    shutil.copytree(REPO_ROOT, target, ignore=ignore)
    git(target, "init")
    git(target, "config", "user.email", "dogfood-test@example.invalid")
    git(target, "config", "user.name", "Dogfood Test")
    git(target, "add", ".")
    git(target, "commit", "-m", "candidate")
    return target


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise AssertionError(result.stderr or result.stdout)
    return result.stdout.strip()
