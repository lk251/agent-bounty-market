from __future__ import annotations

import argparse
import json
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

from .core import AgentBountyMarket
from .db import connect
from .payments import FakePaymentGateway
from .util import stable_json, utc_now
from .verification import ProtectedVerifierRunner


DEFAULT_PROJECT_ID = "project_motoko"
DEFAULT_BOUNTY_ID = "bounty_motoko_issue_1"
DEFAULT_SOLVER_ID = "solver_codex_motoko_issue_1"
DEFAULT_CURRENCY = "USD"


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
        verifier_id="motoko_issue_1_tui_latency",
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
    if verification["receipt"].get("accepted") is True:
        payout = market.release_payout(
            bounty_id=DEFAULT_BOUNTY_ID,
            idempotency_key=f"payout:{DEFAULT_BOUNTY_ID}:{candidate_commit}",
        )
    summary = market.bounty_summary(DEFAULT_BOUNTY_ID)
    reconciliation = market.reconciliation(project_id=DEFAULT_PROJECT_ID, solver_id=DEFAULT_SOLVER_ID)
    return {
        "schema": "agent-bounty-demo-v1",
        "created_at": utc_now(),
        "db_path": str(db_path),
        "project_id": DEFAULT_PROJECT_ID,
        "bounty_id": DEFAULT_BOUNTY_ID,
        "solver_id": DEFAULT_SOLVER_ID,
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


def cmd_ledger_show(args: argparse.Namespace) -> int:
    market = open_market(args.db)
    print_json({"schema": "ledger-report-v1", "rows": market.ledger_rows()})
    return 0


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

    show = sub.add_parser("bounty-show", help="show one bounty")
    show.add_argument("--db", required=True)
    show.add_argument("--bounty-id", required=True)
    show.set_defaults(func=cmd_bounty_show)

    ledger = sub.add_parser("ledger-show", help="show append-only ledger rows")
    ledger.add_argument("--db", required=True)
    ledger.set_defaults(func=cmd_ledger_show)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
