from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from .core import AgentBountyMarket
from .db import connect
from .github_integration import (
    FakeGitHubClient,
    GitHubConfig,
    GitHubIntegrationError,
    GitHubRestClient,
    _safe_pr,
    apply_pull_request,
    build_submission_marker,
    github_publish_bounty_contract,
    github_publish_claim_comment,
    github_publish_verification_result,
    github_status_report,
)
from .payments import FakePaymentGateway
from .util import file_digest, sha256_text, stable_json, utc_now
from .verification import ProtectedVerifierRunner


GITHUB_LIVE_SCHEMA = "agent-bounty-github-live-demo-v1"
DEFAULT_PROJECT_ID = "project_motoko"
DEFAULT_BOUNTY_ID = "bounty_motoko_issue_1"
DEFAULT_SOLVER_ID = "solver_python_terminal_tui"
DEFAULT_REPO = "lk251/motoko"
DEFAULT_ISSUE_NUMBER = 1
DEFAULT_BASE_BRANCH = "master"
DEFAULT_HEAD_BRANCH = "bounty/issue-1-tui-input-latency"


def live_rest_blockers(config: GitHubConfig) -> list[str]:
    blockers: list[str] = []
    if not config.enabled:
        blockers.append("set AGENT_BOUNTY_GITHUB_INTEGRATION=1")
    if not config.token:
        blockers.append("set AGENT_BOUNTY_GITHUB_TOKEN or GH_TOKEN to a fine-grained development token")
    if not config.repository:
        blockers.append("set AGENT_BOUNTY_GITHUB_REPOSITORY=owner/repo")
    return blockers


def setup_motoko_bounty_market(db_path: str | Path, *, base_commit: str, reward_cents: int, verifier_timeout: float) -> AgentBountyMarket:
    market = AgentBountyMarket(connect(db_path), FakePaymentGateway(), ProtectedVerifierRunner(timeout_seconds=verifier_timeout))
    market.create_project(project_id=DEFAULT_PROJECT_ID, name="Motoko", currency="USD")
    market.set_budget_policy(
        project_id=DEFAULT_PROJECT_ID,
        max_bounty_amount=reward_cents,
        monthly_budget=reward_cents,
        human_approval_threshold=reward_cents,
        allowed_issue_classes=["machine-verifiable-tui-regression"],
    )
    market.fund_project(project_id=DEFAULT_PROJECT_ID, amount=reward_cents, currency="USD", idempotency_key="github-live:fund:motoko-issue-1")
    market.create_bounty(
        bounty_id=DEFAULT_BOUNTY_ID,
        project_id=DEFAULT_PROJECT_ID,
        title="Eliminate idle Motoko TUI typing latency",
        reward_amount=reward_cents,
        currency="USD",
        base_commit=base_commit,
        issue_ref=f"{DEFAULT_REPO}#1",
        verifier_id="motoko_issue_1_tui_latency_v2",
    )
    market.reserve_bounty(bounty_id=DEFAULT_BOUNTY_ID, idempotency_key="github-live:reserve:motoko-issue-1")
    market.create_solver(solver_id=DEFAULT_SOLVER_ID, display_name="Python terminal/TUI solver", idempotency_key="github-live:solver:python-terminal-tui")
    return market


def push_candidate_branch(*, motoko_repo: Path, remote: str, branch: str, candidate_commit: str) -> dict[str, Any]:
    resolved = subprocess.run(["git", "-C", str(motoko_repo), "rev-parse", candidate_commit], capture_output=True, text=True, check=False, timeout=10)
    if resolved.returncode != 0:
        raise GitHubIntegrationError("candidate commit is not present in the Motoko worktree")
    sha = resolved.stdout.strip()
    result = subprocess.run(
        ["git", "-C", str(motoko_repo), "push", remote, f"{sha}:refs/heads/{branch}"],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        raise GitHubIntegrationError(f"failed to push candidate branch: {(detail[0] if detail else 'git push failed')[:240]}")
    return {"remote": remote, "branch": branch, "candidate_commit": sha, "pushed": True}


def write_bundle(bundle_dir: Path | None, payload: dict[str, Any]) -> dict[str, Any]:
    if not bundle_dir:
        return payload
    bundle_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = bundle_dir / "github-live-demo.json"
    bundle_path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return {**payload, "bundle_path": str(bundle_path), "bundle_digest": file_digest(bundle_path)}


def blocker_payload(*, config: GitHubConfig, status: dict[str, Any], blockers: list[str], bundle_dir: Path | None) -> dict[str, Any]:
    payload = {
        "schema": GITHUB_LIVE_SCHEMA,
        "created_at": utc_now(),
        "ok": False,
        "real_github": False,
        "real_webhook": False,
        "blockers": blockers,
        "status": {
            "ok": status.get("ok"),
            "transport": status.get("transport"),
            "authenticated_user": status.get("authenticated_user"),
            "repository": status.get("repository"),
            "repository_configured": status.get("repository_configured"),
            "webhook_secret_configured": status.get("webhook_secret_configured"),
            "gh_cli": status.get("gh_cli"),
            "required_capabilities": status.get("required_capabilities"),
            "blockers": status.get("blockers"),
        },
        "configured_repository": config.repository,
    }
    return write_bundle(bundle_dir, payload)


def run_demo_github_motoko_live(
    *,
    db_path: Path,
    motoko_repo: Path,
    bundle_dir: Path | None,
    base_commit: str,
    candidate_commit: str,
    reward_cents: int,
    verifier_timeout: float,
    client: Any | None = None,
    config: GitHubConfig | None = None,
    push_branch: bool = False,
    push_remote: str = "github",
    head_branch: str = DEFAULT_HEAD_BRANCH,
    base_branch: str = DEFAULT_BASE_BRANCH,
) -> dict[str, Any]:
    config = config or GitHubConfig.from_env()
    status = github_status_report(config)
    blockers = live_rest_blockers(config)
    if blockers and client is None:
        return blocker_payload(config=config, status=status, blockers=blockers, bundle_dir=bundle_dir)
    repo_full_name = config.repository or DEFAULT_REPO
    client = client or GitHubRestClient(config)
    market = setup_motoko_bounty_market(db_path, base_commit=base_commit, reward_cents=reward_cents, verifier_timeout=verifier_timeout)
    branch_push = None
    if push_branch:
        branch_push = push_candidate_branch(motoko_repo=motoko_repo, remote=push_remote, branch=head_branch, candidate_commit=candidate_commit)
    contract = github_publish_bounty_contract(
        market,
        client=client,
        repo_full_name=repo_full_name,
        bounty_id=DEFAULT_BOUNTY_ID,
        human_body="",
        issue_number=DEFAULT_ISSUE_NUMBER,
        title=None,
    )
    claim = github_publish_claim_comment(
        market,
        client=client,
        repo_full_name=repo_full_name,
        issue_number=DEFAULT_ISSUE_NUMBER,
        bounty_id=DEFAULT_BOUNTY_ID,
        solver_id=DEFAULT_SOLVER_ID,
        lease_expires_at="2026-06-30T18:00:00Z",
        contract_digest_value=contract["contract_digest"],
    )
    marker = build_submission_marker(
        bounty_id=DEFAULT_BOUNTY_ID,
        solver_id=DEFAULT_SOLVER_ID,
        contract_digest_value=contract["contract_digest"],
        issue_number=DEFAULT_ISSUE_NUMBER,
        base_commit=base_commit,
        candidate_commit=candidate_commit,
    )
    pr_body = "\n".join(
        [
            "Agent Bounty submission for Motoko issue #1.",
            "",
            f"Contract digest: `{contract['contract_digest']}`",
            f"Base SHA: `{base_commit}`",
            f"Candidate SHA: `{candidate_commit}`",
            "",
            "Protected verification is platform-owned; candidate CI is advisory only.",
            "",
            marker,
        ]
    )
    pr = client.create_pull_request(
        repo_full_name,
        title="Agent bounty: Motoko TUI input latency",
        body=pr_body,
        head=head_branch,
        base=base_branch,
        draft=True,
    )
    row = {"event_name": "pull_request", "repo_full_name": repo_full_name}
    action = apply_pull_request(market, row=row, payload={"pull_request": _safe_pr(pr)}, candidate_repo_path=str(motoko_repo))
    submission = market.conn.execute("SELECT id FROM submissions WHERE bounty_id = ? ORDER BY created_at DESC LIMIT 1", (DEFAULT_BOUNTY_ID,)).fetchone()
    if not submission:
        raise GitHubIntegrationError("live PR did not create a verification submission")
    verification = market.run_verification(submission_id=submission["id"], idempotency_key=f"github-live:verify:{candidate_commit}")
    receipt = verification.get("receipt") or {}
    result = github_publish_verification_result(
        market,
        client=client,
        repo_full_name=repo_full_name,
        bounty_id=DEFAULT_BOUNTY_ID,
        receipt_id=verification.get("receipt_id"),
        pr_number=int(pr["number"]),
    )
    issue = client.get_issue(repo_full_name, DEFAULT_ISSUE_NUMBER)
    payload = {
        "schema": GITHUB_LIVE_SCHEMA,
        "created_at": utc_now(),
        "ok": bool(receipt.get("accepted")),
        "real_github": not isinstance(client, FakeGitHubClient),
        "real_webhook": False,
        "webhook_blocker": "real webhook not captured; REST fallback used",
        "transport": config.transport,
        "repository": repo_full_name,
        "issue": {
            "number": DEFAULT_ISSUE_NUMBER,
            "url": issue.get("html_url"),
            "body_digest": sha256_text(issue.get("body") or ""),
            "contract_digest": contract["contract_digest"],
        },
        "claim": {"comment_id": claim.get("comment_id"), "comment_url": claim.get("comment_url")},
        "pull_request": {
            "number": pr.get("number"),
            "url": pr.get("html_url"),
            "draft": bool(pr.get("draft")),
            "base_sha": ((pr.get("base") or {}).get("sha") if isinstance(pr.get("base"), dict) else None),
            "head_sha": ((pr.get("head") or {}).get("sha") if isinstance(pr.get("head"), dict) else None),
        },
        "branch_push": branch_push,
        "event_import_action": action,
        "verification": {
            "receipt_id": verification.get("receipt_id"),
            "accepted": receipt.get("accepted"),
            "candidate_sha": receipt.get("candidate_commit"),
            "verifier_digest": receipt.get("verifier_digest"),
            "backend_digest": receipt.get("backend_digest"),
            "policy_digest": receipt.get("policy_digest"),
            "settlement_eligible": bool(receipt.get("accepted")),
        },
        "publication": result,
        "replay": {"github_publication_replayed": bool(result.get("replayed"))},
    }
    return write_bundle(bundle_dir, payload)
