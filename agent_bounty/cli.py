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
from .payments import FakePaymentGateway, StripePaymentGateway
from .stripe_sandbox import (
    OfficialStripeClient,
    PINNED_STRIPE_PACKAGE,
    STRIPE_INTEGRATION_ENV,
    STRIPE_REAL_RUN_ENV,
    StripeSandboxConfig,
    StripeSandboxError,
    stripe_cli_version,
    stripe_package_version,
)
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
    result = stripe_reconcile_report(market, project_id=args.project_id, solver_id=args.solver_id, bounty_id=args.bounty_id)
    print_json(result)
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


def stripe_reconcile_report(market: AgentBountyMarket, *, project_id: str, solver_id: str, bounty_id: str | None = None) -> dict[str, Any]:
    funding_requests = [dict(row) for row in market.conn.execute("SELECT * FROM funding_requests ORDER BY created_at, id").fetchall()]
    operations = [dict(row) for row in market.conn.execute("SELECT * FROM stripe_operations ORDER BY created_at, id").fetchall()]
    webhooks = [dict(row) for row in market.conn.execute("SELECT * FROM stripe_webhook_events ORDER BY received_at, event_id").fetchall()]
    payouts = [dict(row) for row in market.conn.execute("SELECT * FROM payouts ORDER BY created_at, id").fetchall()]
    reconciliation = market.reconciliation(project_id=project_id, solver_id=solver_id)
    bounty = market.bounty_summary(bounty_id) if bounty_id else None
    return {
        "schema": "agent-bounty-stripe-reconcile-v1",
        "project_id": project_id,
        "solver_id": solver_id,
        "bounty_id": bounty_id,
        "ledger_reconciled": bool(reconciliation["ok"]),
        "reconciliation": reconciliation,
        "funding_requests": funding_requests,
        "stripe_operations": operations,
        "stripe_webhook_events": webhooks,
        "payouts": payouts,
        "bounty": bounty,
        "safe_corrective_actions": [] if reconciliation["ok"] else ["inspect mismatched funding, ledger, and transfer rows before retrying"],
    }


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
        market.create_project(project_id=DEFAULT_PROJECT_ID, name="Motoko", currency=DEFAULT_CURRENCY)
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
            currency=DEFAULT_CURRENCY,
            base_commit=DEFAULT_BASE_COMMIT,
            issue_ref="lk251/motoko#1",
            verifier_id="motoko_issue_1_tui_latency_v2",
        )
        available = market.ledger.balance(f"project:{DEFAULT_PROJECT_ID}:available", DEFAULT_CURRENCY)
        if available < args.reward_cents:
            checkout = market.create_stripe_checkout(
                project_id=DEFAULT_PROJECT_ID,
                source_kind="owner",
                amount=args.reward_cents,
                currency=DEFAULT_CURRENCY,
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
                idempotency_key=f"stripe-transfer:{DEFAULT_BOUNTY_ID}:{DEFAULT_FINAL_COMMIT}",
            )
        reconciliation = stripe_reconcile_report(market, project_id=DEFAULT_PROJECT_ID, solver_id=DEFAULT_SOLVER_ID, bounty_id=DEFAULT_BOUNTY_ID)
        result = {
            "schema": "agent-bounty-demo-stripe-motoko-v1",
            "ok": bool(reconciliation["ledger_reconciled"]) and transfer is not None and not transfer.get("failed", False),
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
    reconcile.set_defaults(func=cmd_stripe_reconcile)

    process = sub.add_parser("stripe-process-events", help="process recorded Stripe webhook rows after restart")
    process.add_argument("--db", required=True)
    process.add_argument("--limit", type=int, default=100)
    process.set_defaults(func=cmd_stripe_process_events)

    demo_stripe = sub.add_parser("demo-stripe-motoko", help="start the real Stripe sandbox Motoko demo")
    demo_stripe.add_argument("--db", required=True)
    demo_stripe.add_argument("--motoko-repo", required=True)
    demo_stripe.add_argument("--reward-cents", type=int, default=2500)
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
