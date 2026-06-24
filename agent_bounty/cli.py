from __future__ import annotations

import argparse
import http.server
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .core import AgentBountyMarket, MarketError
from .db import connect
from .economic_loop import (
    DEFAULT_SECOND_PROJECT_ID,
    DEFAULT_SECOND_VERIFIER_ID,
    EconomicLoopError,
    allocate_accepted_reward,
    default_solver_operating_policy,
    economic_loop_status_report,
    run_demo_economic_loop,
    save_solver_operating_policy,
    spend_retained_credit_to_project,
)
from .github_integration import (
    FakeGitHubClient,
    GitHubConfig,
    GitHubIntegrationError,
    GitHubRestClient,
    build_claim_comment,
    build_submission_marker,
    github_import_bounty_contract,
    github_publish_bounty_contract,
    github_publish_claim_comment,
    github_publish_verification_result,
    github_show_contract,
    github_status_report,
    process_github_event_row,
    record_github_webhook_delivery,
    sign_github_payload,
)
from .payments import FakePaymentGateway, StripePaymentGateway
from .project_agent import (
    FakeProjectAgentRuntime,
    HermesCliRuntime,
    ProjectAgentError,
    default_project_agent_policy,
    evaluate_project_agent,
    fund_and_publish_project_agent_decision,
    load_project_agent_policy,
    project_agent_status_report,
    run_demo_project_agent_motoko,
    save_project_agent_policy,
    scan_project_candidates,
    setup_demo_project,
)
from .solver_agent import (
    FakeSolverAgentRuntime,
    SolverAgentError,
    claim_approved_solver,
    evaluate_solver_agents,
    execute_deterministic_motoko_replay,
    open_funded_contracts,
    record_live_solve_fallback,
    register_default_solver_profiles,
    run_demo_solver_motoko,
    solver_agent_status_report,
    submit_solver_replay,
)
from .stripe_sandbox import (
    OfficialStripeClient,
    PINNED_STRIPE_PACKAGE,
    STRIPE_INTEGRATION_ENV,
    STRIPE_REAL_RUN_ENV,
    StripeSandboxConfig,
    StripeSandboxError,
    safe_error_message,
    stripe_cli_version,
    stripe_package_version,
)
from .util import require_currency, stable_json, utc_now
from .execution import openshell_status
from .verification import ProtectedVerifierRunner, default_verifier_dir


DEFAULT_PROJECT_ID = "project_motoko"
DEFAULT_BOUNTY_ID = "bounty_motoko_issue_1"
DEFAULT_SOLVER_ID = "solver_codex_motoko_issue_1"
DEFAULT_CURRENCY = "USD"
DEFAULT_BASE_COMMIT = "f4ebe1073d6fe7b9a1e2036e2a6e923ea0a68116"
DEFAULT_INTERMEDIATE_COMMIT = "fdf54095b5cb8aca81984993bcd38176ccadad32"
DEFAULT_FINAL_COMMIT = "4c03e0fa02a26f1cbadbe593ae687eaa9b333d2c"


def print_json(value: Any) -> None:
    print(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False))


def run_stripe_sandbox_smoke(
    *,
    gateway: StripePaymentGateway,
    project_id: str,
    solver_id: str,
    amount: int,
    currency: str,
    run_id: str,
) -> dict[str, Any]:
    funding_key = f"stripe-smoke:{run_id}:fund:{project_id}:{amount}:{currency}"
    beneficiary_key = f"stripe-smoke:{run_id}:beneficiary:{solver_id}"
    payout_key = f"stripe-smoke:{run_id}:payout:{solver_id}:{amount}:{currency}"
    payout_id = f"payout_stripe_smoke_{run_id}"
    credit = gateway.credit_project_treasury(
        project_id=project_id,
        amount=amount,
        currency=currency,
        idempotency_key=funding_key,
    )
    beneficiary = gateway.ensure_solver_beneficiary(solver_id=solver_id, idempotency_key=beneficiary_key)
    payout = gateway.release_payout(
        payout_id=payout_id,
        solver_id=solver_id,
        amount=amount,
        currency=currency,
        idempotency_key=payout_key,
        source_transaction_id=credit.source_transaction_id,
    )
    status = gateway.retrieve_payout_status(external_id=payout.external_id)
    return {
        "schema": "agent-bounty-stripe-sandbox-smoke-v1",
        "project_id": project_id,
        "solver_id": solver_id,
        "amount": amount,
        "currency": currency,
        "run_id": run_id,
        "funding": {
            "payment_intent_id": credit.external_id,
            "source_transaction_id": credit.source_transaction_id,
            "replayed": credit.replayed,
        },
        "beneficiary": {
            "account_id": beneficiary.external_id,
            "replayed": beneficiary.replayed,
        },
        "payout": {
            "transfer_id": payout.external_id,
            "status": status,
            "replayed": payout.replayed,
        },
    }


def open_market(db_path: str | Path, *, fail_payout_key: str | None = None, verifier_timeout: float = 20.0) -> AgentBountyMarket:
    conn = connect(db_path)
    gateway = FakePaymentGateway(fail_payout_keys={fail_payout_key} if fail_payout_key else None)
    return AgentBountyMarket(conn, gateway, ProtectedVerifierRunner(timeout_seconds=verifier_timeout))


def run_motoko_flow(
    *,
    db_path: str | Path,
    motoko_repo: Path,
    base_commit: str,
    candidate_commit: str,
    funding_cents: int,
    reward_cents: int,
    verifier_timeout: float = 20.0,
    fail_payout_key: str | None = None,
) -> dict[str, Any]:
    market = open_market(db_path, fail_payout_key=fail_payout_key, verifier_timeout=verifier_timeout)
    market.create_project(project_id=DEFAULT_PROJECT_ID, name="Motoko", currency=DEFAULT_CURRENCY)
    market.set_budget_policy(
        project_id=DEFAULT_PROJECT_ID,
        max_bounty_amount=max(funding_cents, reward_cents),
        monthly_budget=max(funding_cents, reward_cents),
        human_approval_threshold=max(funding_cents, reward_cents),
        allowed_issue_classes=["machine-verifiable-tui-regression"],
    )
    funding = market.fund_project(
        project_id=DEFAULT_PROJECT_ID,
        amount=funding_cents,
        currency=DEFAULT_CURRENCY,
        idempotency_key=f"fund:{DEFAULT_PROJECT_ID}:motoko-issue-1:{funding_cents}",
    )
    market.create_bounty(
        bounty_id=DEFAULT_BOUNTY_ID,
        project_id=DEFAULT_PROJECT_ID,
        title="Eliminate idle Motoko TUI typing latency",
        reward_amount=reward_cents,
        currency=DEFAULT_CURRENCY,
        base_commit=base_commit,
        issue_ref="lk251/motoko#1",
        verifier_id="motoko_issue_1_tui_latency_v2",
    )
    reserve = market.reserve_bounty(
        bounty_id=DEFAULT_BOUNTY_ID,
        idempotency_key=f"reserve:{DEFAULT_BOUNTY_ID}:{reward_cents}",
    )
    market.create_solver(
        solver_id=DEFAULT_SOLVER_ID,
        display_name="Codex solver for Motoko issue #1",
        idempotency_key=f"beneficiary:{DEFAULT_SOLVER_ID}",
    )
    claim = market.claim_bounty(
        bounty_id=DEFAULT_BOUNTY_ID,
        solver_id=DEFAULT_SOLVER_ID,
        lease_expires_at="2026-06-30T18:00:00Z",
        idempotency_key=f"claim:{DEFAULT_BOUNTY_ID}:{DEFAULT_SOLVER_ID}",
    )
    submission = market.submit_candidate(
        bounty_id=DEFAULT_BOUNTY_ID,
        solver_id=DEFAULT_SOLVER_ID,
        candidate_repo_path=str(motoko_repo),
        candidate_commit=candidate_commit,
        idempotency_key=f"submission:{DEFAULT_BOUNTY_ID}:{candidate_commit}",
    )
    verification = market.run_verification(
        submission_id=submission["submission_id"],
        idempotency_key=f"verify:{DEFAULT_BOUNTY_ID}:{candidate_commit}",
    )
    payout: dict[str, Any] | None = None
    receipt = verification.get("receipt") or {}
    if receipt.get("accepted") is True:
        payout = market.release_payout(
            bounty_id=DEFAULT_BOUNTY_ID,
            idempotency_key=f"payout:{DEFAULT_BOUNTY_ID}:{candidate_commit}",
        )
    summary = market.bounty_summary(DEFAULT_BOUNTY_ID)
    reconciliation = market.reconciliation(project_id=DEFAULT_PROJECT_ID, solver_id=DEFAULT_SOLVER_ID)
    project_funds = {
        "available": reconciliation["balances"].get("project_available", 0),
        "reserved": reconciliation["balances"].get("project_reserved", 0),
        "refunded": reconciliation["balances"].get("project_refunded", 0),
        "spent": reconciliation["balances"].get("solver_paid", 0),
    }
    receipt = summary.get("receipt") or {}
    return {
        "schema": "agent-bounty-demo-v1",
        "created_at": utc_now(),
        "db_path": str(db_path),
        "project_id": DEFAULT_PROJECT_ID,
        "bounty_id": DEFAULT_BOUNTY_ID,
        "solver_id": DEFAULT_SOLVER_ID,
        "project_funds": project_funds,
        "candidate_sha": candidate_commit,
        "base_sha": base_commit,
        "verifier_version": receipt.get("verifier_version"),
        "verifier_digest": receipt.get("verifier_digest"),
        "verdict": "accepted" if receipt.get("accepted") is True else "rejected",
        "payout_id": payout.get("payout_id") if payout else None,
        "funding": funding,
        "reserve": reserve,
        "claim": claim,
        "submission": submission,
        "verification": verification,
        "payout": payout,
        "bounty": summary,
        "reconciliation": reconciliation,
        "ledger_entries": len(market.ledger_rows()),
    }


def run_motoko_suite(
    *,
    motoko_repo: Path,
    base_commit: str,
    intermediate_commit: str,
    final_commit: str,
    funding_cents: int,
    reward_cents: int,
    verifier_timeout: float = 60.0,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="agent-bounty-suite-") as tmp:
        tmp_path = Path(tmp)
        malicious = run_malicious_candidate_probe(tmp_path / "malicious")
        baseline = run_motoko_flow(
            db_path=tmp_path / "baseline.sqlite3",
            motoko_repo=motoko_repo,
            base_commit=base_commit,
            candidate_commit=base_commit,
            funding_cents=funding_cents,
            reward_cents=reward_cents,
            verifier_timeout=verifier_timeout,
        )
        intermediate = run_motoko_flow(
            db_path=tmp_path / "intermediate.sqlite3",
            motoko_repo=motoko_repo,
            base_commit=base_commit,
            candidate_commit=intermediate_commit,
            funding_cents=funding_cents,
            reward_cents=reward_cents,
            verifier_timeout=verifier_timeout,
        )
        final_db = tmp_path / "final.sqlite3"
        final = run_motoko_flow(
            db_path=final_db,
            motoko_repo=motoko_repo,
            base_commit=base_commit,
            candidate_commit=final_commit,
            funding_cents=funding_cents,
            reward_cents=reward_cents,
            verifier_timeout=verifier_timeout,
        )
        replay = run_motoko_flow(
            db_path=final_db,
            motoko_repo=motoko_repo,
            base_commit=base_commit,
            candidate_commit=final_commit,
            funding_cents=funding_cents,
            reward_cents=reward_cents,
            verifier_timeout=verifier_timeout,
        )
        return {
            "schema": "agent-bounty-motoko-suite-v1",
            "created_at": utc_now(),
            "cases": {
                "malicious": malicious,
                "baseline": baseline,
                "intermediate": intermediate,
                "final": final,
                "final_replay": replay,
            },
            "accepted_candidate": final_commit,
            "malicious_rejected": malicious["accepted"] is False,
            "baseline_rejected": baseline["verification"]["receipt"].get("accepted") is False and baseline["payout"] is None,
            "intermediate_rejected": intermediate["verification"]["receipt"].get("accepted") is False and intermediate["payout"] is None,
            "final_paid_once": final["payout"] is not None
            and replay["payout"] is not None
            and final["payout"]["gateway_payout_id"] == replay["payout"]["gateway_payout_id"]
            and replay["payout"].get("replayed") is True,
            "reconciliation_ok": all(
                case["reconciliation"]["ok"]
                for case in (baseline, intermediate, final, replay)
            ),
        }


def run_malicious_candidate_probe(root: Path) -> dict[str, Any]:
    repo = root / "repo"
    repo.mkdir(parents=True)
    _run_git(repo, "init")
    _run_git(repo, "config", "user.email", "demo@example.invalid")
    _run_git(repo, "config", "user.name", "Demo User")
    base = _git_commit(
        repo,
        "motoko",
        "#!/usr/bin/env python3\n"
        "class MotokoTui:\n"
        "    def __init__(self, conv): self.running = False\n"
        "    def run(self): return None\n"
        "def new_conversation(title): return {'title': title}\n",
    )
    candidate = _git_commit(
        repo,
        "motoko",
        "#!/usr/bin/env python3\n"
        "import __main__, json, pathlib\n"
        "__main__.CONTRACT = {'verifier_id': 'pwned'}\n"
        "print(json.dumps({'accepted': True, 'forged_by': 'candidate'}))\n"
        "pathlib.Path('attempted-verifier-write').write_text('candidate was here')\n"
        "raise SystemExit(0)\n",
    )
    verifier_dir = root / "verifier"
    shutil.copytree(default_verifier_dir(), verifier_dir)
    contract_path = verifier_dir / "contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    contract["baseline_commit"] = base
    contract_path.write_text(json.dumps(contract, sort_keys=True) + "\n", encoding="utf-8")
    result = ProtectedVerifierRunner(verifier_dir=verifier_dir, timeout_seconds=10).run(
        bounty_id="bounty_malicious_demo",
        motoko_repo=repo,
        base_commit=base,
        candidate_commit=candidate,
    )
    failure_reasons = result.result.get("failure_reasons")
    if not isinstance(failure_reasons, list):
        failure_reasons = [str(result.result.get("error"))] if result.result.get("error") else []
    return {
        "schema": "agent-bounty-malicious-demo-v1",
        "accepted": result.accepted,
        "verdict": "accepted" if result.accepted else "rejected",
        "base_commit": base,
        "candidate_commit": candidate,
        "backend": result.backend,
        "backend_digest": result.backend_digest,
        "policy_digest": result.policy_digest,
        "verifier_digest": result.verifier_digest,
        "trusted_policy_preserved": result.result.get("verifier_id") != "pwned",
        "failure_reasons": failure_reasons,
    }


def _run_git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _git_commit(repo: Path, filename: str, text: str) -> str:
    path = repo / filename
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)
    _run_git(repo, "add", filename)
    _run_git(repo, "commit", "-m", f"commit {filename}")
    return _run_git(repo, "rev-parse", "HEAD")


def cmd_demo_motoko(args: argparse.Namespace) -> int:
    if args.db:
        db_path = Path(args.db)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        result = run_motoko_flow(
            db_path=db_path,
            motoko_repo=Path(args.motoko_repo),
            base_commit=args.base_commit,
            candidate_commit=args.candidate_commit,
            funding_cents=args.funding_cents,
            reward_cents=args.reward_cents,
            verifier_timeout=args.verifier_timeout,
            fail_payout_key=args.fail_payout_key,
        )
    else:
        with tempfile.TemporaryDirectory(prefix="agent-bounty-demo-") as tmp:
            result = run_motoko_flow(
                db_path=Path(tmp) / "market.sqlite3",
                motoko_repo=Path(args.motoko_repo),
                base_commit=args.base_commit,
                candidate_commit=args.candidate_commit,
                funding_cents=args.funding_cents,
                reward_cents=args.reward_cents,
                verifier_timeout=args.verifier_timeout,
                fail_payout_key=args.fail_payout_key,
            )
    print_json(result)
    return 0 if result["reconciliation"]["ok"] else 1


def cmd_bounty_show(args: argparse.Namespace) -> int:
    market = open_market(args.db)
    print_json(market.bounty_summary(args.bounty_id))
    return 0


def cmd_demo_motoko_suite(args: argparse.Namespace) -> int:
    result = run_motoko_suite(
        motoko_repo=Path(args.motoko_repo),
        base_commit=args.base_commit,
        intermediate_commit=args.intermediate_commit,
        final_commit=args.final_commit,
        funding_cents=args.funding_cents,
        reward_cents=args.reward_cents,
        verifier_timeout=args.verifier_timeout,
    )
    print_json(result)
    return 0 if result["malicious_rejected"] and result["baseline_rejected"] and result["intermediate_rejected"] and result["final_paid_once"] and result["reconciliation_ok"] else 1


def cmd_ledger_show(args: argparse.Namespace) -> int:
    market = open_market(args.db)
    print_json({"schema": "ledger-report-v1", "rows": market.ledger_rows()})
    return 0


def cmd_openshell_status(_args: argparse.Namespace) -> int:
    status = openshell_status()
    print_json(status)
    return 0 if status["available"] else 2


def make_github_client() -> tuple[GitHubConfig, GitHubRestClient]:
    config = GitHubConfig.from_env()
    return config, GitHubRestClient(config)


def cmd_github_status(_args: argparse.Namespace) -> int:
    result = github_status_report()
    print_json(result)
    return 0 if result["ok"] else 1


def cmd_github_publish_bounty(args: argparse.Namespace) -> int:
    try:
        _config, client = make_github_client()
        market = open_market(args.db)
        result = github_publish_bounty_contract(
            market,
            client=client,
            repo_full_name=args.repo,
            bounty_id=args.bounty_id,
            issue_number=args.issue_number,
            title=args.title,
            human_body=args.body,
            idempotency_key=args.idempotency_key,
        )
    except (GitHubIntegrationError, MarketError) as exc:
        print_json({"schema": "agent-bounty-github-publish-v1", "ok": False, "error": str(exc)})
        return 1
    print_json({"schema": "agent-bounty-github-publish-v1", "ok": True, **result})
    return 0


def cmd_github_import_bounty(args: argparse.Namespace) -> int:
    try:
        market = open_market(args.db)
        if args.issue_body_file:
            body = Path(args.issue_body_file).read_text(encoding="utf-8")
            issue_url = args.issue_url
        else:
            _config, client = make_github_client()
            issue = client.get_issue(args.repo, args.issue_number)
            body = str(issue.get("body") or "")
            issue_url = args.issue_url or issue.get("html_url")
        result = github_import_bounty_contract(
            market,
            repo_full_name=args.repo,
            issue_number=args.issue_number,
            issue_body=body,
            issue_url=issue_url,
            expected_digest=args.expected_digest,
        )
    except (GitHubIntegrationError, MarketError) as exc:
        print_json({"schema": "agent-bounty-github-import-v1", "ok": False, "error": str(exc)})
        return 1
    print_json({"schema": "agent-bounty-github-import-v1", "ok": True, **result})
    return 0


def cmd_github_show_contract(args: argparse.Namespace) -> int:
    try:
        body = Path(args.issue_body_file).read_text(encoding="utf-8")
        result = github_show_contract(body, expected_digest=args.expected_digest)
    except GitHubIntegrationError as exc:
        print_json({"schema": "agent-bounty-github-contract-report-v1", "ok": False, "error": str(exc)})
        return 1
    print_json(result)
    return 0


def cmd_github_publish_claim(args: argparse.Namespace) -> int:
    try:
        _config, client = make_github_client()
        market = open_market(args.db)
        result = github_publish_claim_comment(
            market,
            client=client,
            repo_full_name=args.repo,
            issue_number=args.issue_number,
            bounty_id=args.bounty_id,
            solver_id=args.solver_id,
            lease_expires_at=args.lease_expires_at,
            contract_digest_value=args.contract_digest,
            idempotency_key=args.idempotency_key,
        )
    except (GitHubIntegrationError, MarketError) as exc:
        print_json({"schema": "agent-bounty-github-claim-v1", "ok": False, "error": str(exc)})
        return 1
    print_json({"schema": "agent-bounty-github-claim-v1", "ok": True, **result})
    return 0


def cmd_github_publish_result(args: argparse.Namespace) -> int:
    try:
        _config, client = make_github_client()
        market = open_market(args.db, verifier_timeout=args.verifier_timeout)
        result = github_publish_verification_result(
            market,
            client=client,
            repo_full_name=args.repo,
            bounty_id=args.bounty_id,
            receipt_id=args.receipt_id,
            pr_number=args.pr_number,
            idempotency_key=args.idempotency_key,
        )
    except (GitHubIntegrationError, MarketError) as exc:
        print_json({"schema": "agent-bounty-github-result-v1", "ok": False, "error": str(exc)})
        return 1
    print_json({"schema": "agent-bounty-github-result-v1", "ok": True, **result})
    return 0


def cmd_github_webhook_serve(args: argparse.Namespace) -> int:
    config = GitHubConfig.from_env()
    if not config.webhook_secret:
        print_json({"schema": "agent-bounty-github-webhook-server-v1", "ok": False, "error": f"set AGENT_BOUNTY_GITHUB_WEBHOOK_SECRET"})
        return 1

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/github/webhook":
                self.send_response(404)
                self.end_headers()
                return
            length = int(self.headers.get("Content-Length", "0"))
            payload = self.rfile.read(length)
            market = open_market(args.db, verifier_timeout=args.verifier_timeout)
            try:
                recorded = record_github_webhook_delivery(
                    market.conn,
                    payload=payload,
                    headers=self.headers,
                    endpoint_secret=config.webhook_secret or "",
                    expected_repo_full_name=args.repo or config.repository,
                )
                result = process_github_event_row(market, delivery_id=recorded["delivery_id"], candidate_repo_path=args.candidate_repo_path)
            except Exception as exc:
                body = json.dumps({"ok": False, "error": safe_error_message(exc)}, sort_keys=True).encode("utf-8")
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            body = json.dumps({"ok": True, **result}, sort_keys=True).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            return

    server = http.server.ThreadingHTTPServer((args.host, args.port), Handler)
    print_json({"schema": "agent-bounty-github-webhook-server-v1", "ok": True, "host": args.host, "port": args.port, "path": "/github/webhook"})
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 130
    return 0


def cmd_github_process_events(args: argparse.Namespace) -> int:
    try:
        market = open_market(args.db, verifier_timeout=args.verifier_timeout)
        rows = market.conn.execute(
            """
            SELECT delivery_id
            FROM github_webhook_deliveries
            WHERE status IN ('recorded', 'failed')
            ORDER BY received_at, delivery_id
            LIMIT ?
            """,
            (args.limit,),
        ).fetchall()
        results = [process_github_event_row(market, delivery_id=row["delivery_id"], candidate_repo_path=args.candidate_repo_path) for row in rows]
    except (GitHubIntegrationError, MarketError) as exc:
        print_json({"schema": "agent-bounty-github-process-events-v1", "ok": False, "error": str(exc)})
        return 1
    print_json({"schema": "agent-bounty-github-process-events-v1", "ok": True, "processed": len(results), "events": results})
    return 0


def _record_fake_github_event(market: AgentBountyMarket, *, secret: str, event_name: str, delivery_id: str, payload: dict[str, Any], repo: str, candidate_repo_path: str | None = None) -> dict[str, Any]:
    body = stable_json(payload).encode("utf-8")
    recorded = record_github_webhook_delivery(
        market.conn,
        payload=body,
        headers={
            "X-GitHub-Delivery": delivery_id,
            "X-GitHub-Event": event_name,
            "X-Hub-Signature-256": sign_github_payload(body, secret),
        },
        endpoint_secret=secret,
        expected_repo_full_name=repo,
    )
    processed = process_github_event_row(market, delivery_id=delivery_id, candidate_repo_path=candidate_repo_path)
    return {"recorded": recorded, "processed": processed}


def cmd_demo_github_motoko(args: argparse.Namespace) -> int:
    secret = "github_webhook_secret_for_local_demo"
    repo = args.repo
    market = open_market(args.db, verifier_timeout=args.verifier_timeout)
    client = FakeGitHubClient()
    market.create_project(project_id=DEFAULT_PROJECT_ID, name="Motoko", currency=DEFAULT_CURRENCY)
    market.set_budget_policy(
        project_id=DEFAULT_PROJECT_ID,
        max_bounty_amount=args.reward_cents,
        monthly_budget=args.reward_cents,
        human_approval_threshold=args.reward_cents,
        allowed_issue_classes=["machine-verifiable-tui-regression"],
    )
    funding = market.fund_project(
        project_id=DEFAULT_PROJECT_ID,
        amount=args.reward_cents,
        currency=DEFAULT_CURRENCY,
        idempotency_key=f"github-demo:fund:{DEFAULT_PROJECT_ID}:{args.reward_cents}",
    )
    market.create_bounty(
        bounty_id=DEFAULT_BOUNTY_ID,
        project_id=DEFAULT_PROJECT_ID,
        title="Eliminate idle Motoko TUI typing latency",
        reward_amount=args.reward_cents,
        currency=DEFAULT_CURRENCY,
        base_commit=args.base_commit,
        issue_ref=f"{repo}#1",
        verifier_id="motoko_issue_1_tui_latency_v2",
    )
    reserve = market.reserve_bounty(
        bounty_id=DEFAULT_BOUNTY_ID,
        idempotency_key=f"github-demo:reserve:{DEFAULT_BOUNTY_ID}:{args.reward_cents}",
    )
    existing_contract = market.conn.execute(
        "SELECT * FROM github_issue_contracts WHERE bounty_id = ? ORDER BY updated_at DESC LIMIT 1",
        (DEFAULT_BOUNTY_ID,),
    ).fetchone()
    if existing_contract:
        issue_number = int(existing_contract["issue_number"])
        issue_body = json.loads(existing_contract["issue_body_json"])["body"]
        issue_url = existing_contract["issue_url"]
        client.issues[(repo, issue_number)] = {
            "id": issue_number,
            "number": issue_number,
            "title": "Eliminate idle Motoko TUI typing latency",
            "body": issue_body,
            "html_url": issue_url,
            "state": "open",
            "updated_at": utc_now(),
        }
        publish = {"replayed": True, "issue_number": issue_number, "issue_url": issue_url, "contract_digest": existing_contract["contract_digest"]}
    else:
        publish = github_publish_bounty_contract(
            market,
            client=client,
            repo_full_name=repo,
            bounty_id=DEFAULT_BOUNTY_ID,
            human_body="Machine-verifiable bounty for the Motoko issue #1 TUI latency fix.",
            title="Agent bounty: Motoko issue #1 TUI input latency",
            idempotency_key=f"github-demo:publish:{DEFAULT_BOUNTY_ID}",
        )
        issue_number = int(publish["issue_number"])
        issue_body = client.get_issue(repo, issue_number)["body"]
    issue_event = _record_fake_github_event(
        market,
        secret=secret,
        event_name="issues",
        delivery_id=f"demo-issue-{issue_number}",
        repo=repo,
        payload={
            "action": "edited",
            "repository": {"full_name": repo, "id": 1},
            "issue": {"id": issue_number, "number": issue_number, "body": issue_body, "html_url": publish.get("issue_url")},
        },
    )
    claim_body = build_claim_comment(
        bounty_id=DEFAULT_BOUNTY_ID,
        solver_id=DEFAULT_SOLVER_ID,
        lease_expires_at="2026-06-30T18:00:00Z",
        contract_digest_value=publish["contract_digest"],
    )
    client.add_issue_comment(repo, issue_number, claim_body)
    claim_event = _record_fake_github_event(
        market,
        secret=secret,
        event_name="issue_comment",
        delivery_id=f"demo-claim-{issue_number}",
        repo=repo,
        payload={
            "action": "created",
            "repository": {"full_name": repo, "id": 1},
            "issue": {"id": issue_number, "number": issue_number, "body": issue_body, "html_url": publish.get("issue_url")},
            "comment": {"id": 1, "body": claim_body, "user": {"login": DEFAULT_SOLVER_ID, "id": 2}},
        },
    )
    submission_marker = build_submission_marker(
        bounty_id=DEFAULT_BOUNTY_ID,
        solver_id=DEFAULT_SOLVER_ID,
        contract_digest_value=publish["contract_digest"],
        issue_number=issue_number,
        base_commit=args.base_commit,
        candidate_commit=args.final_commit,
    )
    pr = client.create_fake_pull_request(
        repo,
        number=args.pr_number,
        title="Fix Motoko TUI input latency",
        body=submission_marker,
        base_ref="master",
        base_sha=args.base_commit,
        head_ref="bounty/issue-1-tui-input-latency",
        head_sha=args.final_commit,
        head_repo_full_name=repo,
        user_login=DEFAULT_SOLVER_ID,
    )
    pr_event = _record_fake_github_event(
        market,
        secret=secret,
        event_name="pull_request",
        delivery_id=f"demo-pr-{args.pr_number}-{args.final_commit}",
        repo=repo,
        candidate_repo_path=str(Path(args.motoko_repo)),
        payload={"action": "opened", "repository": {"full_name": repo, "id": 1}, "pull_request": pr},
    )
    submission_row = market.conn.execute(
        "SELECT * FROM submissions WHERE bounty_id = ? AND solver_id = ? AND candidate_commit = ? ORDER BY created_at DESC LIMIT 1",
        (DEFAULT_BOUNTY_ID, DEFAULT_SOLVER_ID, args.final_commit),
    ).fetchone()
    if not submission_row:
        raise SystemExit("demo failed to record a GitHub submission")
    verification = market.run_verification(
        submission_id=submission_row["id"],
        idempotency_key=f"github-demo:verify:{DEFAULT_BOUNTY_ID}:{args.final_commit}",
    )
    result_publication = github_publish_verification_result(
        market,
        client=client,
        repo_full_name=repo,
        bounty_id=DEFAULT_BOUNTY_ID,
        receipt_id=verification.get("receipt_id"),
        pr_number=args.pr_number,
        idempotency_key=f"github-demo:result:{DEFAULT_BOUNTY_ID}:{args.final_commit}",
    )
    replay_publication = github_publish_verification_result(
        market,
        client=client,
        repo_full_name=repo,
        bounty_id=DEFAULT_BOUNTY_ID,
        receipt_id=verification.get("receipt_id"),
        pr_number=args.pr_number,
        idempotency_key=f"github-demo:result:{DEFAULT_BOUNTY_ID}:{args.final_commit}",
    )
    summary = market.bounty_summary(DEFAULT_BOUNTY_ID)
    reconciliation = market.reconciliation(project_id=DEFAULT_PROJECT_ID, solver_id=DEFAULT_SOLVER_ID)
    result = {
        "schema": "agent-bounty-demo-github-motoko-v1",
        "ok": reconciliation["ok"] and bool((verification.get("receipt") or {}).get("accepted")),
        "mode": "fake-github-local-verifier",
        "repo": repo,
        "issue_number": issue_number,
        "pr_number": args.pr_number,
        "contract_digest": publish["contract_digest"],
        "candidate_sha": args.final_commit,
        "funding": funding,
        "reserve": reserve,
        "publish": publish,
        "issue_event": issue_event,
        "claim_event": claim_event,
        "pr_event": pr_event,
        "verification": verification,
        "result_publication": result_publication,
        "replay_publication": replay_publication,
        "bounty": summary,
        "reconciliation": reconciliation,
    }
    print_json(result)
    return 0 if result["ok"] and replay_publication.get("replayed") else 1


def _project_agent_runtime(kind: str) -> FakeProjectAgentRuntime | HermesCliRuntime:
    if kind == "fake":
        return FakeProjectAgentRuntime()
    if kind == "hermes":
        return HermesCliRuntime()
    raise ProjectAgentError(f"unknown project-agent runtime {kind}")


def _github_client_for_project_agent(fake: bool) -> FakeGitHubClient | GitHubRestClient:
    if fake:
        return FakeGitHubClient()
    _config, client = make_github_client()
    return client


def cmd_project_agent_status(_args: argparse.Namespace) -> int:
    print_json(project_agent_status_report())
    return 0


def cmd_project_agent_scan(args: argparse.Namespace) -> int:
    try:
        market = open_market(args.db)
        market.create_project(project_id=args.project_id, name=args.project_id, currency=args.currency)
        policy = default_project_agent_policy(
            project_id=args.project_id,
            repo_full_name=args.repo,
            currency=args.currency,
            max_bounty_amount_cents=args.max_bounty_cents,
            monthly_budget_cents=args.monthly_budget_cents,
            human_approval_threshold_cents=args.human_approval_threshold_cents,
        )
        saved_policy = save_project_agent_policy(market, policy)
        scan = scan_project_candidates(market, project_id=args.project_id, repo_full_name=args.repo)
    except (ProjectAgentError, MarketError, ValueError) as exc:
        print_json({"schema": "project-agent-scan-v1", "ok": False, "error": str(exc)})
        return 1
    print_json({"schema": "project-agent-scan-v1", "ok": True, "policy": saved_policy, "scan": scan})
    return 0


def cmd_project_agent_evaluate(args: argparse.Namespace) -> int:
    try:
        market = open_market(args.db)
        result = evaluate_project_agent(
            market,
            project_id=args.project_id,
            runtime=_project_agent_runtime(args.runtime),
            idempotency_key=args.idempotency_key or f"project-agent:evaluate:{args.project_id}:{args.runtime}",
            timeout_seconds=args.timeout_seconds,
        )
    except (ProjectAgentError, MarketError) as exc:
        print_json({"schema": "project-agent-evaluation-v1", "ok": False, "error": str(exc)})
        return 1
    print_json({"schema": "project-agent-evaluation-v1", "ok": True, **result})
    return 0


def cmd_project_agent_fund_and_publish(args: argparse.Namespace) -> int:
    try:
        market = open_market(args.db)
        _policy = load_project_agent_policy(market, args.project_id)
        result = fund_and_publish_project_agent_decision(
            market,
            project_id=args.project_id,
            github_client=_github_client_for_project_agent(args.fake_github),
            repo_full_name=args.repo,
            idempotency_key=args.idempotency_key or f"project-agent:fund-and-publish:{args.project_id}:{args.repo}",
        )
    except (ProjectAgentError, MarketError, GitHubIntegrationError) as exc:
        print_json({"schema": "project-agent-fund-and-publish-v1", "ok": False, "error": str(exc)})
        return 1
    print_json({"schema": "project-agent-fund-and-publish-v1", "ok": True, **result})
    return 0


def cmd_demo_project_agent_motoko(args: argparse.Namespace) -> int:
    try:
        market = open_market(args.db)
        if args.runtime == "fake":
            runtime: FakeProjectAgentRuntime | HermesCliRuntime = FakeProjectAgentRuntime()
        else:
            runtime = HermesCliRuntime()
        result = run_demo_project_agent_motoko(market, repo_full_name=args.repo, runtime=runtime)
    except (ProjectAgentError, MarketError, GitHubIntegrationError) as exc:
        print_json({"schema": "project-agent-demo-motoko-v1", "ok": False, "error": str(exc)})
        return 1
    print_json(result)
    return 0 if result.get("ok") else 1


def cmd_solver_agent_status(_args: argparse.Namespace) -> int:
    print_json(solver_agent_status_report())
    return 0


def cmd_solver_agent_register(args: argparse.Namespace) -> int:
    try:
        market = open_market(args.db)
        result = register_default_solver_profiles(market)
    except (SolverAgentError, MarketError) as exc:
        print_json({"schema": "solver-agent-profile-registration-v1", "ok": False, "error": str(exc)})
        return 1
    print_json({"schema": "solver-agent-profile-registration-v1", "ok": True, **result})
    return 0


def cmd_solver_agent_discover(args: argparse.Namespace) -> int:
    try:
        market = open_market(args.db)
        result = {"schema": "solver-agent-discovery-v1", "open_contracts": open_funded_contracts(market)}
    except (SolverAgentError, MarketError) as exc:
        print_json({"schema": "solver-agent-discovery-v1", "ok": False, "error": str(exc)})
        return 1
    print_json({"ok": True, **result})
    return 0


def cmd_solver_agent_evaluate(args: argparse.Namespace) -> int:
    try:
        market = open_market(args.db)
        result = evaluate_solver_agents(market, runtime=FakeSolverAgentRuntime())
    except (SolverAgentError, MarketError) as exc:
        print_json({"schema": "solver-agent-evaluation-v1", "ok": False, "error": str(exc)})
        return 1
    print_json({"schema": "solver-agent-evaluation-v1", "ok": True, **result})
    return 0


def cmd_solver_agent_claim(args: argparse.Namespace) -> int:
    try:
        market = open_market(args.db)
        result = claim_approved_solver(market, lease_expires_at=args.lease_expires_at)
    except (SolverAgentError, MarketError) as exc:
        print_json({"schema": "solver-agent-claim-v1", "ok": False, "error": str(exc)})
        return 1
    print_json({"schema": "solver-agent-claim-v1", "ok": True, **result})
    return 0


def cmd_solver_agent_execute(args: argparse.Namespace) -> int:
    try:
        market = open_market(args.db)
        if args.mode == "deterministic-replay":
            result = execute_deterministic_motoko_replay(market, solver_id=args.solver_id, bounty_id=args.bounty_id)
        else:
            result = record_live_solve_fallback(market, solver_id=args.solver_id, bounty_id=args.bounty_id)
    except (SolverAgentError, MarketError) as exc:
        print_json({"schema": "solver-agent-execution-v1", "ok": False, "error": str(exc)})
        return 1
    print_json({"schema": "solver-agent-execution-v1", "ok": True, **result})
    return 0


def cmd_solver_agent_submit(args: argparse.Namespace) -> int:
    try:
        market = open_market(args.db, verifier_timeout=args.verifier_timeout)
        result = submit_solver_replay(market, motoko_repo=Path(args.motoko_repo) if args.motoko_repo else None, repo_full_name=args.repo, pr_number=args.pr_number)
    except (SolverAgentError, MarketError) as exc:
        print_json({"schema": "solver-agent-submission-v1", "ok": False, "error": str(exc)})
        return 1
    print_json({"schema": "solver-agent-submission-v1", "ok": True, **result})
    return 0


def cmd_demo_solver_motoko(args: argparse.Namespace) -> int:
    try:
        market = open_market(args.db, verifier_timeout=args.verifier_timeout)
        result = run_demo_solver_motoko(market, motoko_repo=Path(args.motoko_repo) if args.motoko_repo else None)
    except (SolverAgentError, ProjectAgentError, MarketError, GitHubIntegrationError) as exc:
        print_json({"schema": "solver-agent-demo-motoko-v1", "ok": False, "error": str(exc)})
        return 1
    print_json(result)
    return 0 if result.get("ok") else 1


def cmd_economic_loop_status(_args: argparse.Namespace) -> int:
    print_json(economic_loop_status_report())
    return 0


def cmd_economic_loop_allocate(args: argparse.Namespace) -> int:
    market = open_market(args.db, verifier_timeout=args.verifier_timeout)
    try:
        result = allocate_accepted_reward(
            market,
            bounty_id=args.bounty_id,
            external_transfer_amount=args.external_transfer_cents,
            retained_operating_amount=args.retained_operating_cents,
            platform_fee_amount=args.platform_fee_cents,
            retention_consent=args.retention_consent,
            transfer_provider=args.transfer_provider,
            idempotency_key=args.idempotency_key,
            simulate_transfer_failure=args.simulate_transfer_failure,
        )
    except (EconomicLoopError, MarketError) as exc:
        print_json({"schema": "agent-bounty-settlement-allocation-v1", "ok": False, "error": str(exc)})
        return 1
    print_json(result)
    return 0 if result.get("ok") else 1


def cmd_economic_loop_spend_retained(args: argparse.Namespace) -> int:
    market = open_market(args.db)
    try:
        save_solver_operating_policy(
            market,
            default_solver_operating_policy(
                solver_id=args.solver_id,
                allowed_projects=[args.target_project_id],
                allowed_repositories=[args.repo],
                allowed_issue_classes=[args.issue_class],
                required_verifier_ids=[args.verifier_id],
                max_spend_cents=args.amount_cents,
                human_approval_threshold_cents=args.amount_cents,
                allowed_currencies=[args.currency],
            ),
        )
        result = spend_retained_credit_to_project(
            market,
            solver_id=args.solver_id,
            target_project_id=args.target_project_id,
            repo_full_name=args.repo,
            amount=args.amount_cents,
            currency=args.currency,
            title=args.title,
            issue_class=args.issue_class,
            verifier_id=args.verifier_id,
            base_commit=args.base_commit,
            idempotency_key=args.idempotency_key,
            issue_number=args.issue_number,
        )
    except (EconomicLoopError, MarketError, GitHubIntegrationError) as exc:
        print_json({"schema": "agent-bounty-solver-operating-spend-v1", "ok": False, "error": str(exc)})
        return 1
    print_json(result)
    return 0 if result.get("ok") else 1


def cmd_demo_economic_loop(args: argparse.Namespace) -> int:
    market = open_market(args.db, verifier_timeout=args.verifier_timeout)
    try:
        result = run_demo_economic_loop(
            market,
            motoko_repo=Path(args.motoko_repo) if args.motoko_repo else None,
            external_transfer_amount=args.external_transfer_cents,
            retained_operating_amount=args.retained_operating_cents,
            platform_fee_amount=args.platform_fee_cents,
        )
    except (EconomicLoopError, SolverAgentError, ProjectAgentError, MarketError, GitHubIntegrationError) as exc:
        print_json({"schema": "agent-bounty-demo-economic-loop-v1", "ok": False, "error": safe_error_message(exc)})
        return 1
    print_json(result)
    return 0 if result.get("ok") else 1


def open_trusted_market(db_path: str | Path, *, verifier_timeout: float = 60.0) -> AgentBountyMarket:
    conn = connect(db_path)
    return AgentBountyMarket(conn, FakePaymentGateway(), ProtectedVerifierRunner(timeout_seconds=verifier_timeout))


def make_official_stripe_client() -> tuple[StripeSandboxConfig, OfficialStripeClient]:
    config = StripeSandboxConfig.from_env()
    return config, OfficialStripeClient(config)


def cmd_stripe_status(_args: argparse.Namespace) -> int:
    config = StripeSandboxConfig.from_env()
    blockers: list[str] = []
    if not config.enabled:
        blockers.append(f"set {STRIPE_INTEGRATION_ENV}=1")
    if not config.secret_key:
        blockers.append("set STRIPE_TEST_SECRET_KEY")
    elif not (config.secret_key.startswith("sk_test_") or config.secret_key.startswith("rk_test_")):
        blockers.append("replace non-test Stripe API key with sk_test_ or rk_test_")
    if not config.webhook_secret:
        blockers.append("set STRIPE_TEST_WEBHOOK_SECRET from stripe listen")
    if not config.connected_account_id:
        blockers.append("set STRIPE_TEST_CONNECTED_ACCOUNT_ID to a test connected account")
    package_version = stripe_package_version()
    if package_version != PINNED_STRIPE_PACKAGE:
        blockers.append(f"install optional Stripe package stripe=={PINNED_STRIPE_PACKAGE}")
    platform: dict[str, Any] | None = None
    connected: dict[str, Any] | None = None
    if config.enabled and config.secret_key and package_version == PINNED_STRIPE_PACKAGE:
        try:
            client = OfficialStripeClient(config)
            account = client.retrieve_account(None)
            platform = {
                "id": account.get("id"),
                "country": account.get("country"),
                "livemode": account.get("livemode"),
            }
            if config.platform_account_id and platform["id"] != config.platform_account_id:
                blockers.append("authenticated platform account does not match STRIPE_TEST_PLATFORM_ACCOUNT_ID")
            if config.connected_account_id:
                connected_account = client.retrieve_account(config.connected_account_id)
                connected = {
                    "id": connected_account.get("id"),
                    "country": connected_account.get("country"),
                    "livemode": connected_account.get("livemode"),
                    "charges_enabled": bool(connected_account.get("charges_enabled", False)),
                    "payouts_enabled": bool(connected_account.get("payouts_enabled", False)),
                }
        except Exception as exc:
            blockers.append(f"Stripe authenticated status failed: {exc}")
    result = {
        "schema": "agent-bounty-stripe-status-v1",
        "sandbox_enabled": config.enabled,
        "stripe_package_version": package_version,
        "stripe_package_required": f"stripe=={PINNED_STRIPE_PACKAGE}",
        "stripe_cli": stripe_cli_version(),
        "webhook_secret_configured": bool(config.webhook_secret),
        "platform_account": platform,
        "connected_account": connected or ({"id": config.connected_account_id} if config.connected_account_id else None),
        "blockers": blockers,
        "ok": not blockers,
    }
    print_json(result)
    return 0 if not blockers else 2


def cmd_stripe_create_checkout(args: argparse.Namespace) -> int:
    try:
        _config, client = make_official_stripe_client()
        market = open_trusted_market(args.db)
        market.create_project(project_id=args.project_id, name=args.project_id, currency=args.currency)
        result = market.create_stripe_checkout(
            project_id=args.project_id,
            source_kind=args.source,
            amount=args.amount_cents,
            currency=args.currency,
            success_url=args.success_url,
            cancel_url=args.cancel_url,
            client=client,
            idempotency_key=args.idempotency_key,
        )
    except (StripeSandboxError, MarketError) as exc:
        print_json({"schema": "agent-bounty-stripe-checkout-v1", "ok": False, "error": str(exc)})
        return 1
    print_json({"schema": "agent-bounty-stripe-checkout-v1", "ok": True, **result})
    return 0


def cmd_stripe_automated_payment(args: argparse.Namespace) -> int:
    if os.environ.get(STRIPE_REAL_RUN_ENV) != "1":
        print_json({"schema": "agent-bounty-stripe-automated-payment-v1", "ok": False, "blocker": f"set {STRIPE_REAL_RUN_ENV}=1 to run the real Stripe test PaymentMethod helper"})
        return 1
    try:
        _config, client = make_official_stripe_client()
        market = open_trusted_market(args.db)
        market.create_project(project_id=args.project_id, name=args.project_id, currency=args.currency)
        result = market.create_stripe_automated_payment(
            project_id=args.project_id,
            source_kind=args.source,
            amount=args.amount_cents,
            currency=args.currency,
            payment_method=args.payment_method,
            client=client,
            idempotency_key=args.idempotency_key,
        )
    except Exception as exc:
        print_json({"schema": "agent-bounty-stripe-automated-payment-v1", "ok": False, "error": safe_error_message(exc)})
        return 1
    print_json({"schema": "agent-bounty-stripe-automated-payment-v1", "ok": True, **result})
    return 0


def cmd_stripe_attach_beneficiary(args: argparse.Namespace) -> int:
    try:
        _config, client = make_official_stripe_client()
        market = open_trusted_market(args.db)
        result = market.attach_stripe_beneficiary(solver_id=args.solver_id, account_id=args.account_id, client=client)
    except (StripeSandboxError, MarketError) as exc:
        print_json({"schema": "agent-bounty-stripe-beneficiary-v1", "ok": False, "error": str(exc)})
        return 1
    print_json({"schema": "agent-bounty-stripe-beneficiary-v1", "ok": True, **result})
    return 0


def cmd_stripe_release_transfer(args: argparse.Namespace) -> int:
    try:
        _config, client = make_official_stripe_client()
        market = open_trusted_market(args.db, verifier_timeout=args.verifier_timeout)
        result = market.release_stripe_transfer(bounty_id=args.bounty_id, client=client, idempotency_key=args.idempotency_key)
    except (StripeSandboxError, MarketError) as exc:
        print_json({"schema": "agent-bounty-stripe-transfer-v1", "ok": False, "error": str(exc)})
        return 1
    print_json({"schema": "agent-bounty-stripe-transfer-v1", "ok": not result.get("failed", False), **result})
    return 0 if not result.get("failed", False) else 1


def cmd_stripe_reconcile(args: argparse.Namespace) -> int:
    market = open_trusted_market(args.db)
    client: OfficialStripeClient | None = None
    remote_blockers: list[str] = []
    if args.remote:
        try:
            _config, client = make_official_stripe_client()
        except Exception as exc:
            remote_blockers.append(str(exc))
    result = stripe_reconcile_report(
        market,
        project_id=args.project_id,
        solver_id=args.solver_id,
        bounty_id=args.bounty_id,
        client=client,
        remote_blockers=remote_blockers,
    )
    print_json(result)
    if args.remote and (result["remote_blockers"] or not result["remote_reconciled"]):
        return 1
    return 0 if result["ledger_reconciled"] else 1


def cmd_stripe_process_events(args: argparse.Namespace) -> int:
    try:
        _config, client = make_official_stripe_client()
        market = open_trusted_market(args.db)
        rows = market.conn.execute(
            """
            SELECT event_id
            FROM stripe_webhook_events
            WHERE status IN ('recorded', 'failed')
            ORDER BY received_at, event_id
            LIMIT ?
            """,
            (args.limit,),
        ).fetchall()
        results = [market.process_stripe_event_row(event_id=row["event_id"], client=client) for row in rows]
    except (StripeSandboxError, MarketError) as exc:
        print_json({"schema": "agent-bounty-stripe-process-events-v1", "ok": False, "error": str(exc)})
        return 1
    print_json({"schema": "agent-bounty-stripe-process-events-v1", "ok": True, "processed": len(results), "events": results})
    return 0


def stripe_reconcile_report(
    market: AgentBountyMarket,
    *,
    project_id: str,
    solver_id: str,
    bounty_id: str | None = None,
    currency: str | None = None,
    client: OfficialStripeClient | None = None,
    remote_blockers: list[str] | None = None,
) -> dict[str, Any]:
    funding_requests = [dict(row) for row in market.conn.execute("SELECT * FROM funding_requests ORDER BY created_at, id").fetchall()]
    operations = [dict(row) for row in market.conn.execute("SELECT * FROM stripe_operations ORDER BY created_at, id").fetchall()]
    webhooks = [dict(row) for row in market.conn.execute("SELECT * FROM stripe_webhook_events ORDER BY received_at, event_id").fetchall()]
    payouts = [dict(row) for row in market.conn.execute("SELECT * FROM payouts ORDER BY created_at, id").fetchall()]
    solvers = [dict(row) for row in market.conn.execute("SELECT * FROM solver_identities ORDER BY created_at, id").fetchall()]
    bounty = market.bounty_summary(bounty_id) if bounty_id else None
    reconciliation_currency = require_currency(currency or (bounty["currency"] if bounty else DEFAULT_CURRENCY))
    reconciliation = market.reconciliation(project_id=project_id, solver_id=solver_id, currency=reconciliation_currency)
    remote = _remote_stripe_reconciliation(client=client, funding_requests=funding_requests, payouts=payouts, solvers=solvers)
    blockers = list(remote_blockers or [])
    if client is None and not blockers:
        blockers.append("remote Stripe retrieval not requested; pass --remote with sandbox credentials")
    remote_reconciled = bool(client is not None and not blockers and remote["checked"] and not remote["mismatches"])
    return {
        "schema": "agent-bounty-stripe-reconcile-v1",
        "project_id": project_id,
        "solver_id": solver_id,
        "bounty_id": bounty_id,
        "ledger_reconciled": bool(reconciliation["ok"]),
        "remote_checked": client is not None,
        "remote_reconciled": remote_reconciled,
        "remote_blockers": blockers,
        "remote": remote,
        "reconciliation": reconciliation,
        "funding_requests": funding_requests,
        "stripe_operations": operations,
        "stripe_webhook_events": webhooks,
        "payouts": payouts,
        "solver_identities": solvers,
        "bounty": bounty,
        "safe_corrective_actions": [] if reconciliation["ok"] else ["inspect mismatched funding, ledger, and transfer rows before retrying"],
    }


def _remote_stripe_reconciliation(
    *,
    client: OfficialStripeClient | None,
    funding_requests: list[dict[str, Any]],
    payouts: list[dict[str, Any]],
    solvers: list[dict[str, Any]],
) -> dict[str, Any]:
    if client is None:
        return {"checked": False, "objects": [], "mismatches": []}
    objects: list[dict[str, Any]] = []
    mismatches: list[str] = []
    try:
        for request in funding_requests:
            expected_amount = int(request["amount"])
            expected_currency = str(request["currency"]).lower()
            checkout_id = request.get("checkout_session_id")
            payment_intent_id = request.get("payment_intent_id")
            charge_id = request.get("charge_id")
            if checkout_id:
                session = client.retrieve_checkout_session(str(checkout_id))
                objects.append({"kind": "checkout.session", "id": session.get("id"), "livemode": session.get("livemode")})
                if session.get("livemode") is not False:
                    mismatches.append(f"Checkout Session {checkout_id} is not test-mode")
                if int(session.get("amount_total", expected_amount)) != expected_amount:
                    mismatches.append(f"Checkout Session {checkout_id} amount mismatch")
                if str(session.get("currency", expected_currency)).lower() != expected_currency:
                    mismatches.append(f"Checkout Session {checkout_id} currency mismatch")
            if payment_intent_id:
                payment_intent = client.retrieve_payment_intent(str(payment_intent_id))
                objects.append({"kind": "payment_intent", "id": payment_intent.get("id"), "livemode": payment_intent.get("livemode")})
                if payment_intent.get("livemode") is not False:
                    mismatches.append(f"PaymentIntent {payment_intent_id} is not test-mode")
                if int(payment_intent.get("amount_received", payment_intent.get("amount", expected_amount))) != expected_amount:
                    mismatches.append(f"PaymentIntent {payment_intent_id} amount mismatch")
                if str(payment_intent.get("currency", expected_currency)).lower() != expected_currency:
                    mismatches.append(f"PaymentIntent {payment_intent_id} currency mismatch")
            if charge_id:
                charge = client.retrieve_charge(str(charge_id))
                objects.append({"kind": "charge", "id": charge.get("id"), "livemode": charge.get("livemode")})
                if charge.get("livemode") is not False:
                    mismatches.append(f"Charge {charge_id} is not test-mode")
        account_by_solver = {solver["id"]: solver.get("beneficiary_external_id") for solver in solvers}
        for payout in payouts:
            transfer_id = payout.get("stripe_transfer_id") or payout.get("gateway_payout_id")
            if not transfer_id:
                continue
            expected_account = account_by_solver.get(payout["solver_id"])
            if expected_account:
                account = client.retrieve_account(str(expected_account))
                objects.append({"kind": "connected_account", "id": account.get("id"), "livemode": account.get("livemode")})
                if account.get("livemode") is True:
                    mismatches.append(f"Connected account {expected_account} is live-mode")
                if account.get("id") != expected_account:
                    mismatches.append(f"Connected account {expected_account} id mismatch")
            transfer = client.retrieve_transfer(str(transfer_id))
            objects.append({"kind": "transfer", "id": transfer.get("id"), "livemode": transfer.get("livemode")})
            if transfer.get("livemode") is not False:
                mismatches.append(f"Transfer {transfer_id} is not test-mode")
            if int(transfer.get("amount", payout["amount"])) != int(payout["amount"]):
                mismatches.append(f"Transfer {transfer_id} amount mismatch")
            if str(transfer.get("currency", payout["currency"])).lower() != str(payout["currency"]).lower():
                mismatches.append(f"Transfer {transfer_id} currency mismatch")
            if expected_account and transfer.get("destination") != expected_account:
                mismatches.append(f"Transfer {transfer_id} destination mismatch")
            if transfer.get("transfer_group") != payout.get("transfer_group"):
                mismatches.append(f"Transfer {transfer_id} transfer group mismatch")
            metadata = transfer.get("metadata") if isinstance(transfer.get("metadata"), dict) else {}
            expected_metadata = {
                "bounty_id": payout["bounty_id"],
                "solver_id": payout["solver_id"],
                "payout_id": payout["id"],
                "receipt_id": payout["accepted_receipt_id"],
            }
            for key, expected in expected_metadata.items():
                if expected is not None and metadata.get(key) != expected:
                    mismatches.append(f"Transfer {transfer_id} metadata mismatch for {key}")
    except Exception as exc:
        mismatches.append(f"remote Stripe retrieval failed: {safe_error_message(exc)}")
    return {"checked": True, "objects": objects, "mismatches": mismatches}


def cmd_stripe_webhook_serve(args: argparse.Namespace) -> int:
    config, client = make_official_stripe_client()
    endpoint_secret = config.require_webhook_secret()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/stripe/webhook":
                self.send_response(404)
                self.end_headers()
                return
            length = int(self.headers.get("Content-Length", "0"))
            payload = self.rfile.read(length)
            signature = self.headers.get("Stripe-Signature", "")
            market = open_trusted_market(args.db)
            try:
                result = market.record_official_stripe_webhook(
                    payload=payload,
                    signature_header=signature,
                    endpoint_secret=endpoint_secret,
                    client=client,
                )
            except Exception as exc:
                body = json.dumps({"ok": False, "error": str(exc)}, sort_keys=True).encode("utf-8")
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            body = json.dumps({"ok": True, **result}, sort_keys=True).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            try:
                market.process_stripe_event_row(event_id=str(result["event_id"]), client=client)
            except Exception:
                return

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            return

    server = http.server.ThreadingHTTPServer((args.host, args.port), Handler)
    print_json({"schema": "agent-bounty-stripe-webhook-server-v1", "ok": True, "host": args.host, "port": args.port, "path": "/stripe/webhook"})
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 130
    return 0


def cmd_demo_stripe_motoko(args: argparse.Namespace) -> int:
    config = StripeSandboxConfig.from_env()
    if not config.enabled:
        print_json({
            "schema": "agent-bounty-demo-stripe-motoko-v1",
            "ok": False,
            "blocker": f"set {STRIPE_INTEGRATION_ENV}=1 plus Stripe test key, webhook secret, and connected account",
        })
        return 1
    try:
        client = OfficialStripeClient(config)
        market = open_trusted_market(args.db, verifier_timeout=args.verifier_timeout)
        currency = require_currency(args.currency)
        market.create_project(project_id=DEFAULT_PROJECT_ID, name="Motoko", currency=currency)
        market.set_budget_policy(
            project_id=DEFAULT_PROJECT_ID,
            max_bounty_amount=args.reward_cents,
            monthly_budget=args.reward_cents,
            human_approval_threshold=args.reward_cents,
            allowed_issue_classes=["machine-verifiable-tui-regression"],
        )
        market.create_bounty(
            bounty_id=DEFAULT_BOUNTY_ID,
            project_id=DEFAULT_PROJECT_ID,
            title="Eliminate idle Motoko TUI typing latency",
            reward_amount=args.reward_cents,
            currency=currency,
            base_commit=DEFAULT_BASE_COMMIT,
            issue_ref="lk251/motoko#1",
            verifier_id="motoko_issue_1_tui_latency_v2",
        )
        bounty_before_reserve = market.bounty_summary(DEFAULT_BOUNTY_ID)
        available = market.ledger.balance(f"project:{DEFAULT_PROJECT_ID}:available", currency)
        if bounty_before_reserve["state"] == "awaiting_funding" and available < args.reward_cents:
            checkout = market.create_stripe_checkout(
                project_id=DEFAULT_PROJECT_ID,
                source_kind="owner",
                amount=args.reward_cents,
                currency=currency,
                success_url=f"{config.public_base_url}/success",
                cancel_url=f"{config.public_base_url}/cancel",
                client=client,
                idempotency_key="demo-stripe-motoko:checkout",
            )
            result = {
                "schema": "agent-bounty-demo-stripe-motoko-v1",
                "ok": False,
                "stage": "waiting_for_signed_webhook",
                "checkout_session_id": checkout["checkout_session_id"],
                "payment_intent_id": checkout["payment_intent_id"],
                "checkout_url": checkout["checkout_url"],
                "project_available_cents": available,
                "next": "run stripe listen, complete Checkout, then rerun demo-stripe-motoko",
            }
            print_json(result)
            return 1
        reserve = market.reserve_bounty(
            bounty_id=DEFAULT_BOUNTY_ID,
            idempotency_key=f"reserve:{DEFAULT_BOUNTY_ID}:{args.reward_cents}",
        )
        market.create_solver(
            solver_id=DEFAULT_SOLVER_ID,
            display_name="Codex solver for Motoko issue #1",
            idempotency_key=f"beneficiary:{DEFAULT_SOLVER_ID}",
        )
        if not config.connected_account_id:
            raise StripeSandboxError("set STRIPE_TEST_CONNECTED_ACCOUNT_ID to a test connected account before transfer release")
        beneficiary = market.attach_stripe_beneficiary(
            solver_id=DEFAULT_SOLVER_ID,
            account_id=config.connected_account_id,
            client=client,
        )
        claim = market.claim_bounty(
            bounty_id=DEFAULT_BOUNTY_ID,
            solver_id=DEFAULT_SOLVER_ID,
            lease_expires_at="2026-06-30T18:00:00Z",
            idempotency_key=f"claim:{DEFAULT_BOUNTY_ID}:{DEFAULT_SOLVER_ID}",
        )
        submission = market.submit_candidate(
            bounty_id=DEFAULT_BOUNTY_ID,
            solver_id=DEFAULT_SOLVER_ID,
            candidate_repo_path=str(Path(args.motoko_repo)),
            candidate_commit=DEFAULT_FINAL_COMMIT,
            idempotency_key=f"submission:{DEFAULT_BOUNTY_ID}:{DEFAULT_FINAL_COMMIT}",
        )
        verification = market.run_verification(
            submission_id=submission["submission_id"],
            idempotency_key=f"verify:{DEFAULT_BOUNTY_ID}:{DEFAULT_FINAL_COMMIT}",
        )
        transfer = None
        if (verification.get("receipt") or {}).get("accepted") is True:
            transfer = market.release_stripe_transfer(
                bounty_id=DEFAULT_BOUNTY_ID,
                client=client,
            )
        reconciliation = stripe_reconcile_report(
            market,
            project_id=DEFAULT_PROJECT_ID,
            solver_id=DEFAULT_SOLVER_ID,
            bounty_id=DEFAULT_BOUNTY_ID,
            currency=currency,
            client=client,
        )
        result = {
            "schema": "agent-bounty-demo-stripe-motoko-v1",
            "ok": bool(reconciliation["ledger_reconciled"]) and bool(reconciliation["remote_reconciled"]) and transfer is not None and not transfer.get("failed", False),
            "stage": "complete" if transfer and not transfer.get("failed", False) else "transfer_blocked",
            "reserve": reserve,
            "beneficiary": beneficiary,
            "claim": claim,
            "submission": submission,
            "verification": verification,
            "transfer": transfer,
            "reconciliation": reconciliation,
        }
    except (StripeSandboxError, MarketError) as exc:
        print_json({"schema": "agent-bounty-demo-stripe-motoko-v1", "ok": False, "error": str(exc)})
        return 1
    print_json(result)
    return 0 if result.get("ok") else 1


def cmd_stripe_automated_smoke(args: argparse.Namespace) -> int:
    if os.environ.get(STRIPE_REAL_RUN_ENV) != "1":
        print_json({"schema": "agent-bounty-stripe-automated-smoke-v1", "ok": False, "blocker": f"set {STRIPE_REAL_RUN_ENV}=1 after configuring Stripe sandbox credentials"})
        return 1
    return cmd_demo_stripe_motoko(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-bounty", description="Trusted local transaction core for agent bounties")
    sub = parser.add_subparsers(dest="command", required=True)

    demo = sub.add_parser("demo-motoko", help="run the Motoko issue #1 funded bounty transaction")
    demo.add_argument("--db", help="SQLite database path; defaults to a temporary fresh DB")
    demo.add_argument("--motoko-repo", required=True)
    demo.add_argument("--base-commit", required=True)
    demo.add_argument("--candidate-commit", required=True)
    demo.add_argument("--funding-cents", type=int, required=True)
    demo.add_argument("--reward-cents", type=int, required=True)
    demo.add_argument("--verifier-timeout", type=float, default=20.0)
    demo.add_argument("--fail-payout-key", help="test hook: make this fake payout idempotency key fail")
    demo.set_defaults(func=cmd_demo_motoko)

    suite = sub.add_parser("demo-motoko-suite", help="run baseline/intermediate rejection plus final accepted Motoko flow")
    suite.add_argument("--motoko-repo", required=True)
    suite.add_argument("--base-commit", default=DEFAULT_BASE_COMMIT)
    suite.add_argument("--intermediate-commit", default=DEFAULT_INTERMEDIATE_COMMIT)
    suite.add_argument("--final-commit", default=DEFAULT_FINAL_COMMIT)
    suite.add_argument("--funding-cents", type=int, default=2500)
    suite.add_argument("--reward-cents", type=int, default=2500)
    suite.add_argument("--verifier-timeout", type=float, default=60.0)
    suite.set_defaults(func=cmd_demo_motoko_suite)

    show = sub.add_parser("bounty-show", help="show one bounty")
    show.add_argument("--db", required=True)
    show.add_argument("--bounty-id", required=True)
    show.set_defaults(func=cmd_bounty_show)

    ledger = sub.add_parser("ledger-show", help="show append-only ledger rows")
    ledger.add_argument("--db", required=True)
    ledger.set_defaults(func=cmd_ledger_show)

    openshell = sub.add_parser("openshell-status", help="inspect OpenShell verifier backend availability")
    openshell.set_defaults(func=cmd_openshell_status)

    github_status = sub.add_parser("github-status", help="show safe GitHub integration configuration status")
    github_status.set_defaults(func=cmd_github_status)

    github_publish = sub.add_parser("github-publish-bounty", help="publish a versioned bounty contract to a GitHub issue")
    github_publish.add_argument("--db", required=True)
    github_publish.add_argument("--repo", required=True)
    github_publish.add_argument("--bounty-id", required=True)
    github_publish.add_argument("--issue-number", type=int)
    github_publish.add_argument("--title")
    github_publish.add_argument("--body", default="Machine-verifiable agent bounty.")
    github_publish.add_argument("--idempotency-key")
    github_publish.set_defaults(func=cmd_github_publish_bounty)

    github_import = sub.add_parser("github-import-bounty", help="import and validate a GitHub issue bounty contract")
    github_import.add_argument("--db", required=True)
    github_import.add_argument("--repo", required=True)
    github_import.add_argument("--issue-number", type=int, required=True)
    github_import.add_argument("--issue-body-file")
    github_import.add_argument("--issue-url")
    github_import.add_argument("--expected-digest")
    github_import.set_defaults(func=cmd_github_import_bounty)

    github_show = sub.add_parser("github-show-contract", help="parse a GitHub issue bounty contract from a local issue body file")
    github_show.add_argument("--issue-body-file", required=True)
    github_show.add_argument("--expected-digest")
    github_show.set_defaults(func=cmd_github_show_contract)

    github_claim = sub.add_parser("github-publish-claim", help="publish a structured GitHub claim comment")
    github_claim.add_argument("--db", required=True)
    github_claim.add_argument("--repo", required=True)
    github_claim.add_argument("--issue-number", type=int, required=True)
    github_claim.add_argument("--bounty-id", required=True)
    github_claim.add_argument("--solver-id", required=True)
    github_claim.add_argument("--lease-expires-at", required=True)
    github_claim.add_argument("--contract-digest")
    github_claim.add_argument("--idempotency-key")
    github_claim.set_defaults(func=cmd_github_publish_claim)

    github_result = sub.add_parser("github-publish-result", help="publish a protected verifier result to GitHub")
    github_result.add_argument("--db", required=True)
    github_result.add_argument("--repo", required=True)
    github_result.add_argument("--bounty-id", required=True)
    github_result.add_argument("--receipt-id")
    github_result.add_argument("--pr-number", type=int)
    github_result.add_argument("--idempotency-key")
    github_result.add_argument("--verifier-timeout", type=float, default=60.0)
    github_result.set_defaults(func=cmd_github_publish_result)

    github_webhook = sub.add_parser("github-webhook-serve", help="serve a local signed GitHub webhook endpoint")
    github_webhook.add_argument("--db", required=True)
    github_webhook.add_argument("--host", default="127.0.0.1")
    github_webhook.add_argument("--port", type=int, default=4343)
    github_webhook.add_argument("--repo")
    github_webhook.add_argument("--candidate-repo-path")
    github_webhook.add_argument("--verifier-timeout", type=float, default=60.0)
    github_webhook.set_defaults(func=cmd_github_webhook_serve)

    github_process = sub.add_parser("github-process-events", help="process recorded GitHub webhook rows after restart")
    github_process.add_argument("--db", required=True)
    github_process.add_argument("--limit", type=int, default=100)
    github_process.add_argument("--candidate-repo-path")
    github_process.add_argument("--verifier-timeout", type=float, default=60.0)
    github_process.set_defaults(func=cmd_github_process_events)

    demo_github = sub.add_parser("demo-github-motoko", help="run the fake GitHub Motoko contract/claim/PR/verifier/result lifecycle")
    demo_github.add_argument("--db", required=True)
    demo_github.add_argument("--motoko-repo", required=True)
    demo_github.add_argument("--repo", default="lk251/motoko")
    demo_github.add_argument("--pr-number", type=int, default=1)
    demo_github.add_argument("--base-commit", default=DEFAULT_BASE_COMMIT)
    demo_github.add_argument("--final-commit", default=DEFAULT_FINAL_COMMIT)
    demo_github.add_argument("--reward-cents", type=int, default=2500)
    demo_github.add_argument("--verifier-timeout", type=float, default=60.0)
    demo_github.set_defaults(func=cmd_demo_github_motoko)

    project_agent = sub.add_parser("project-agent", help="scan, evaluate, and publish project-agent bounties")
    project_agent_sub = project_agent.add_subparsers(dest="project_agent_command", required=True)

    project_agent_status = project_agent_sub.add_parser("status", help="show project-agent runtime and skill readiness")
    project_agent_status.set_defaults(func=cmd_project_agent_status)

    project_agent_scan = project_agent_sub.add_parser("scan", help="build the normalized project-agent candidate queue")
    project_agent_scan.add_argument("--db", required=True)
    project_agent_scan.add_argument("--project-id", default=DEFAULT_PROJECT_ID)
    project_agent_scan.add_argument("--repo", default="lk251/motoko")
    project_agent_scan.add_argument("--currency", default=DEFAULT_CURRENCY)
    project_agent_scan.add_argument("--max-bounty-cents", type=int, default=2500)
    project_agent_scan.add_argument("--monthly-budget-cents", type=int, default=2500)
    project_agent_scan.add_argument("--human-approval-threshold-cents", type=int, default=2500)
    project_agent_scan.set_defaults(func=cmd_project_agent_scan)

    project_agent_eval = project_agent_sub.add_parser("evaluate", help="run a project-agent runtime over queued candidates")
    project_agent_eval.add_argument("--db", required=True)
    project_agent_eval.add_argument("--project-id", default=DEFAULT_PROJECT_ID)
    project_agent_eval.add_argument("--runtime", choices=["fake", "hermes"], default="fake")
    project_agent_eval.add_argument("--idempotency-key")
    project_agent_eval.add_argument("--timeout-seconds", type=float, default=30.0)
    project_agent_eval.set_defaults(func=cmd_project_agent_evaluate)

    project_agent_fund = project_agent_sub.add_parser("fund-and-publish", help="reserve funds and publish the approved project-agent bounty")
    project_agent_fund.add_argument("--db", required=True)
    project_agent_fund.add_argument("--project-id", default=DEFAULT_PROJECT_ID)
    project_agent_fund.add_argument("--repo", default="lk251/motoko")
    project_agent_fund.add_argument("--fake-github", action="store_true", help="use deterministic fake GitHub client")
    project_agent_fund.add_argument("--idempotency-key")
    project_agent_fund.set_defaults(func=cmd_project_agent_fund_and_publish)

    demo_project_agent = sub.add_parser("demo-project-agent-motoko", help="run the fake-runtime project-agent Motoko underwriting demo")
    demo_project_agent.add_argument("--db", required=True)
    demo_project_agent.add_argument("--repo", default="lk251/motoko")
    demo_project_agent.add_argument("--runtime", choices=["fake", "hermes"], default="fake")
    demo_project_agent.set_defaults(func=cmd_demo_project_agent_motoko)

    solver_agent = sub.add_parser("solver-agent", help="discover, evaluate, claim, execute, and submit funded bounties")
    solver_agent_sub = solver_agent.add_subparsers(dest="solver_agent_command", required=True)

    solver_status = solver_agent_sub.add_parser("status", help="show solver-agent runtime and skill readiness")
    solver_status.set_defaults(func=cmd_solver_agent_status)

    solver_register = solver_agent_sub.add_parser("register-profiles", help="register default specialized solver profiles")
    solver_register.add_argument("--db", required=True)
    solver_register.set_defaults(func=cmd_solver_agent_register)

    solver_discover = solver_agent_sub.add_parser("discover", help="show open funded contracts")
    solver_discover.add_argument("--db", required=True)
    solver_discover.set_defaults(func=cmd_solver_agent_discover)

    solver_eval = solver_agent_sub.add_parser("evaluate", help="evaluate solver profiles against open funded contracts")
    solver_eval.add_argument("--db", required=True)
    solver_eval.set_defaults(func=cmd_solver_agent_evaluate)

    solver_claim = solver_agent_sub.add_parser("claim", help="claim the first trusted approved solver evaluation")
    solver_claim.add_argument("--db", required=True)
    solver_claim.add_argument("--lease-expires-at", default="2026-06-30T18:00:00Z")
    solver_claim.set_defaults(func=cmd_solver_agent_claim)

    solver_execute = solver_agent_sub.add_parser("execute", help="record deterministic replay execution or live fallback")
    solver_execute.add_argument("--db", required=True)
    solver_execute.add_argument("--solver-id", default="solver_python_terminal_tui")
    solver_execute.add_argument("--bounty-id", default=DEFAULT_BOUNTY_ID)
    solver_execute.add_argument("--mode", choices=["deterministic-replay", "live-fallback"], default="deterministic-replay")
    solver_execute.set_defaults(func=cmd_solver_agent_execute)

    solver_submit = solver_agent_sub.add_parser("submit", help="submit deterministic Motoko replay and run protected verifier")
    solver_submit.add_argument("--db", required=True)
    solver_submit.add_argument("--motoko-repo")
    solver_submit.add_argument("--repo", default="lk251/motoko")
    solver_submit.add_argument("--pr-number", type=int, default=101)
    solver_submit.add_argument("--verifier-timeout", type=float, default=60.0)
    solver_submit.set_defaults(func=cmd_solver_agent_submit)

    demo_solver = sub.add_parser("demo-solver-motoko", help="run specialized solver-agent Motoko replay demo")
    demo_solver.add_argument("--db", required=True)
    demo_solver.add_argument("--motoko-repo")
    demo_solver.add_argument("--verifier-timeout", type=float, default=60.0)
    demo_solver.set_defaults(func=cmd_demo_solver_motoko)

    economic_loop = sub.add_parser("economic-loop", help="inspect and operate split settlement plus retained-credit spend")
    economic_loop_sub = economic_loop.add_subparsers(dest="economic_loop_command", required=True)

    economic_status = economic_loop_sub.add_parser("status", help="show economic-loop fake/real integration readiness")
    economic_status.set_defaults(func=cmd_economic_loop_status)

    economic_allocate = economic_loop_sub.add_parser("allocate", help="split an accepted reward into external transfer and retained operating credit")
    economic_allocate.add_argument("--db", required=True)
    economic_allocate.add_argument("--bounty-id", default=DEFAULT_BOUNTY_ID)
    economic_allocate.add_argument("--external-transfer-cents", type=int, default=None)
    economic_allocate.add_argument("--retained-operating-cents", type=int, default=0)
    economic_allocate.add_argument("--platform-fee-cents", type=int, default=0)
    economic_allocate.add_argument("--retention-consent", action="store_true")
    economic_allocate.add_argument("--transfer-provider", choices=["fake", "stripe"], default="fake")
    economic_allocate.add_argument("--idempotency-key")
    economic_allocate.add_argument("--simulate-transfer-failure", action="store_true")
    economic_allocate.add_argument("--verifier-timeout", type=float, default=60.0)
    economic_allocate.set_defaults(func=cmd_economic_loop_allocate)

    economic_spend = economic_loop_sub.add_parser("spend-retained", help="spend retained solver operating credit into a new bounded project bounty")
    economic_spend.add_argument("--db", required=True)
    economic_spend.add_argument("--solver-id", default="solver_python_terminal_tui")
    economic_spend.add_argument("--target-project-id", default=DEFAULT_SECOND_PROJECT_ID)
    economic_spend.add_argument("--repo", default="lk251/motoko")
    economic_spend.add_argument("--amount-cents", type=int, default=500)
    economic_spend.add_argument("--currency", default=DEFAULT_CURRENCY)
    economic_spend.add_argument("--title", default="Follow-up bounty funded from retained solver operating credit")
    economic_spend.add_argument("--issue-class", default="machine-verifiable-tui-regression")
    economic_spend.add_argument("--verifier-id", default=DEFAULT_SECOND_VERIFIER_ID)
    economic_spend.add_argument("--base-commit", default=DEFAULT_BASE_COMMIT)
    economic_spend.add_argument("--issue-number", type=int)
    economic_spend.add_argument("--idempotency-key")
    economic_spend.set_defaults(func=cmd_economic_loop_spend_retained)

    demo_economic = sub.add_parser("demo-economic-loop", help="run deterministic earn -> retain -> spend loop")
    demo_economic.add_argument("--db", required=True)
    demo_economic.add_argument("--motoko-repo")
    demo_economic.add_argument("--external-transfer-cents", type=int, default=2000)
    demo_economic.add_argument("--retained-operating-cents", type=int, default=500)
    demo_economic.add_argument("--platform-fee-cents", type=int, default=0)
    demo_economic.add_argument("--verifier-timeout", type=float, default=60.0)
    demo_economic.set_defaults(func=cmd_demo_economic_loop)

    status = sub.add_parser("stripe-status", help="show safe Stripe sandbox configuration status")
    status.set_defaults(func=cmd_stripe_status)

    checkout = sub.add_parser("stripe-create-checkout", help="create a Stripe-hosted Checkout funding request")
    checkout.add_argument("--db", required=True)
    checkout.add_argument("--project-id", required=True)
    checkout.add_argument("--source", choices=["owner", "donation"], required=True)
    checkout.add_argument("--amount-cents", type=int, required=True)
    checkout.add_argument("--currency", default=DEFAULT_CURRENCY)
    checkout.add_argument("--success-url", required=True)
    checkout.add_argument("--cancel-url", required=True)
    checkout.add_argument("--idempotency-key")
    checkout.set_defaults(func=cmd_stripe_create_checkout)

    automated_payment = sub.add_parser("stripe-automated-payment", help="explicitly gated real Stripe test PaymentMethod funding helper")
    automated_payment.add_argument("--db", required=True)
    automated_payment.add_argument("--project-id", required=True)
    automated_payment.add_argument("--source", choices=["owner", "donation"], required=True)
    automated_payment.add_argument("--amount-cents", type=int, required=True)
    automated_payment.add_argument("--currency", default=DEFAULT_CURRENCY)
    automated_payment.add_argument("--payment-method", default="pm_card_visa")
    automated_payment.add_argument("--idempotency-key")
    automated_payment.set_defaults(func=cmd_stripe_automated_payment)

    webhook = sub.add_parser("stripe-webhook-serve", help="serve a local signed Stripe webhook endpoint")
    webhook.add_argument("--db", required=True)
    webhook.add_argument("--host", default="127.0.0.1")
    webhook.add_argument("--port", type=int, default=4242)
    webhook.set_defaults(func=cmd_stripe_webhook_serve)

    beneficiary = sub.add_parser("stripe-attach-beneficiary", help="attach a validated Stripe test connected account to a solver")
    beneficiary.add_argument("--db", required=True)
    beneficiary.add_argument("--solver-id", required=True)
    beneficiary.add_argument("--account-id", required=True)
    beneficiary.set_defaults(func=cmd_stripe_attach_beneficiary)

    transfer = sub.add_parser("stripe-release-transfer", help="create and verify a Stripe Connect Transfer for an accepted bounty")
    transfer.add_argument("--db", required=True)
    transfer.add_argument("--bounty-id", required=True)
    transfer.add_argument("--idempotency-key")
    transfer.add_argument("--verifier-timeout", type=float, default=60.0)
    transfer.set_defaults(func=cmd_stripe_release_transfer)

    reconcile = sub.add_parser("stripe-reconcile", help="report internal/Stripe settlement links without destructive repair")
    reconcile.add_argument("--db", required=True)
    reconcile.add_argument("--project-id", default=DEFAULT_PROJECT_ID)
    reconcile.add_argument("--solver-id", default=DEFAULT_SOLVER_ID)
    reconcile.add_argument("--bounty-id", default=DEFAULT_BOUNTY_ID)
    reconcile.add_argument("--remote", action="store_true", help="retrieve Stripe objects with configured sandbox credentials")
    reconcile.set_defaults(func=cmd_stripe_reconcile)

    process = sub.add_parser("stripe-process-events", help="process recorded Stripe webhook rows after restart")
    process.add_argument("--db", required=True)
    process.add_argument("--limit", type=int, default=100)
    process.set_defaults(func=cmd_stripe_process_events)

    demo_stripe = sub.add_parser("demo-stripe-motoko", help="start the real Stripe sandbox Motoko demo")
    demo_stripe.add_argument("--db", required=True)
    demo_stripe.add_argument("--motoko-repo", required=True)
    demo_stripe.add_argument("--reward-cents", type=int, default=2500)
    demo_stripe.add_argument("--currency", default=DEFAULT_CURRENCY)
    demo_stripe.add_argument("--verifier-timeout", type=float, default=60.0)
    demo_stripe.set_defaults(func=cmd_demo_stripe_motoko)

    auto_stripe = sub.add_parser("stripe-automated-smoke", help="explicitly gated automated Stripe sandbox smoke path")
    auto_stripe.add_argument("--db", required=True)
    auto_stripe.add_argument("--motoko-repo", required=True)
    auto_stripe.add_argument("--reward-cents", type=int, default=2500)
    auto_stripe.add_argument("--verifier-timeout", type=float, default=60.0)
    auto_stripe.set_defaults(func=cmd_stripe_automated_smoke)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
