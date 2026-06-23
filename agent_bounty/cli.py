from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .core import AgentBountyMarket
from .db import connect
from .payments import FakePaymentGateway
from .util import utc_now
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

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
