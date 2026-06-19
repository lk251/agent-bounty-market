from __future__ import annotations

import os
import sqlite3
import subprocess
import tempfile
from pathlib import Path
from textwrap import dedent

from agent_bounty.core import AgentBountyMarket
from agent_bounty.db import connect
from agent_bounty.payments import FakePaymentGateway
from agent_bounty.verification import ProtectedVerifierRunner


BASE = "base"
CANDIDATE = "candidate"


def write_verifier(root: Path, body: str) -> Path:
    verifier_dir = root / "verifiers" / "motoko_issue_1"
    verifier_dir.mkdir(parents=True)
    (verifier_dir / "contract.json").write_text('{"schema":"test-contract","verifier_id":"test"}\n')
    (verifier_dir / "README.md").write_text("test verifier\n")
    (verifier_dir / "verifier.py").write_text(dedent(body))
    return verifier_dir


def accepted_verifier(root: Path) -> Path:
    return write_verifier(
        root,
        """
        import json
        import sys
        print(json.dumps({
            "schema": "protected-verifier-result-v1",
            "accepted": True,
            "metrics": {"short_transcript": {"p95_ms": 1.0}, "long_transcript": {"p95_ms": 2.0}},
        }, sort_keys=True, separators=(",", ":")))
        raise SystemExit(0)
        """,
    )


def rejected_verifier(root: Path) -> Path:
    return write_verifier(
        root,
        """
        import json
        print(json.dumps({
            "schema": "protected-verifier-result-v1",
            "accepted": False,
            "metrics": {},
            "failure_reasons": ["forced rejection"],
        }, sort_keys=True, separators=(",", ":")))
        raise SystemExit(1)
        """,
    )


def malformed_verifier(root: Path) -> Path:
    return write_verifier(root, "print('not json')\n")


def timeout_verifier(root: Path) -> Path:
    return write_verifier(root, "import time\ntime.sleep(10)\n")


def make_market(verifier_dir: Path, *, fail_payout_keys: set[str] | None = None, timeout: float = 5.0):
    tmp = tempfile.TemporaryDirectory()
    conn = connect(Path(tmp.name) / "market.sqlite3")
    gateway = FakePaymentGateway(fail_payout_keys=fail_payout_keys)
    market = AgentBountyMarket(conn, gateway, ProtectedVerifierRunner(verifier_dir=verifier_dir, timeout_seconds=timeout))
    return tmp, market


def bootstrap_bounty(market: AgentBountyMarket, *, funding: int = 2500, reward: int = 2500) -> tuple[str, str, str]:
    project_id = "project_test"
    bounty_id = "bounty_test"
    solver_id = "solver_test"
    market.create_project(project_id=project_id, name="Test Project")
    market.set_budget_policy(
        project_id=project_id,
        max_bounty_amount=reward,
        monthly_budget=funding,
        human_approval_threshold=reward,
        allowed_issue_classes=["test"],
    )
    market.fund_project(project_id=project_id, amount=funding, idempotency_key="fund:test")
    market.create_bounty(
        bounty_id=bounty_id,
        project_id=project_id,
        title="Test bounty",
        reward_amount=reward,
        currency="USD",
        base_commit=BASE,
        issue_ref="example/repo#1",
        verifier_id="test",
    )
    market.reserve_bounty(bounty_id=bounty_id, idempotency_key="reserve:test")
    market.create_solver(solver_id=solver_id, display_name="Test Solver", idempotency_key="beneficiary:test")
    return project_id, bounty_id, solver_id


def submit_ready(market: AgentBountyMarket, *, candidate_repo: str = "/tmp/candidate") -> tuple[str, str, str, str]:
    project_id, bounty_id, solver_id = bootstrap_bounty(market)
    claim = market.claim_bounty(
        bounty_id=bounty_id,
        solver_id=solver_id,
        lease_expires_at="2026-06-30T18:00:00Z",
        idempotency_key="claim:test",
    )
    submission = market.submit_candidate(
        bounty_id=bounty_id,
        solver_id=solver_id,
        candidate_repo_path=candidate_repo,
        candidate_commit=CANDIDATE,
        idempotency_key="submission:test",
    )
    return project_id, bounty_id, solver_id, submission["submission_id"]


def init_git_repo(path: Path) -> None:
    subprocess.run(["git", "-C", str(path), "init"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "test@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Test User"], check=True)


def git_commit(path: Path, filename: str, text: str) -> str:
    (path / filename).write_text(text)
    subprocess.run(["git", "-C", str(path), "add", filename], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-m", f"commit {filename}"], check=True, capture_output=True)
    return subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
