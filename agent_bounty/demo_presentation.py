from __future__ import annotations

import html
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from .core import AgentBountyMarket
from .db import SCHEMA_VERSION, connect
from .economic_loop import run_demo_economic_loop
from .execution import openshell_status
from .github_integration import github_status_report
from .payments import FakePaymentGateway
from .project_agent import project_agent_status_report
from .solver_agent import solver_agent_status_report
from .stripe_sandbox import stripe_cli_version, stripe_package_version
from .util import file_digest, sha256_text, stable_json, utc_now
from .verification import ProtectedVerifierRunner


PREFLIGHT_SCHEMA = "agent-bounty-demo-preflight-v1"
REHEARSAL_SCHEMA = "agent-bounty-demo-rehearsal-v1"
BUNDLE_SCHEMA = "agent-bounty-demo-bundle-v1"
BUNDLE_MANIFEST_SCHEMA = "agent-bounty-demo-bundle-manifest-v1"
BUNDLE_VALIDATION_SCHEMA = "agent-bounty-demo-bundle-validation-v1"
RESET_SCHEMA = "agent-bounty-demo-reset-v1"


class DemoPresentationError(RuntimeError):
    pass


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def default_motoko_repo() -> Path:
    return Path("/home/mares/repos/motoko-issue-1-tui-input-latency")


def default_demo_db(mode: str) -> Path:
    return repo_root() / ".demo" / f"{mode}.sqlite3"


def default_bundle_dir(mode: str) -> Path:
    return repo_root() / ".demo" / "bundles" / f"{mode}-run"


def _run_git(args: list[str], *, cwd: Path) -> str | None:
    try:
        return subprocess.run(["git", *args], cwd=cwd, check=False, capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        return None


def _port_available(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def _safe_bool(value: Any) -> bool:
    return bool(value)


def demo_preflight_report(*, mode: str = "local", db_path: Path | None = None, motoko_repo: Path | None = None) -> dict[str, Any]:
    mode = mode.lower()
    if mode not in {"local", "replay", "live"}:
        raise DemoPresentationError("mode must be local, replay, or live")
    root = repo_root()
    motoko_repo = motoko_repo or default_motoko_repo()
    db_path = db_path or default_demo_db(mode)
    branch = _run_git(["branch", "--show-current"], cwd=root)
    commit = _run_git(["rev-parse", "HEAD"], cwd=root)
    dirty = bool(_run_git(["status", "--short"], cwd=root))
    github = github_status_report()
    project_agent = project_agent_status_report()
    solver_agent = solver_agent_status_report()
    openshell = openshell_status()
    stripe_package = stripe_package_version()
    blockers: list[str] = []
    if not motoko_repo.exists():
        blockers.append(f"Motoko fixture repo missing: {motoko_repo}")
    if mode == "live":
        if github.get("ok") is not True:
            blockers.extend([f"github: {item}" for item in github.get("blockers", [])])
        if not project_agent.get("hermes_runtime", {}).get("available"):
            blockers.extend([f"project-agent Hermes: {item}" for item in project_agent.get("hermes_runtime", {}).get("blockers", [])])
        if not solver_agent.get("hermes_runtime", {}).get("available"):
            blockers.extend([f"solver-agent Hermes: {item}" for item in solver_agent.get("hermes_runtime", {}).get("blockers", [])])
        if not solver_agent.get("openshell_nemoclaw", {}).get("available"):
            blockers.append(f"solver OpenShell/NemoClaw: {solver_agent.get('openshell_nemoclaw', {}).get('blocker')}")
        if not openshell.get("available"):
            blockers.append(f"OpenShell verifier backend: {openshell.get('blocker')}")
        stripe_blockers = _stripe_live_blockers()
        blockers.extend([f"stripe: {item}" for item in stripe_blockers])
    secret_files = _tracked_or_unignored_secret_files(root)
    if secret_files:
        blockers.extend([f"secret file is tracked or unignored: {path}" for path in secret_files])
    fallback_mode = None if not blockers else ("replay" if mode == "live" else "local")
    return {
        "schema": PREFLIGHT_SCHEMA,
        "ok": not blockers,
        "mode": mode,
        "created_at": utc_now(),
        "repository": {
            "path": str(root),
            "branch": branch,
            "commit": commit,
            "dirty": dirty,
        },
        "motoko_fixture": {
            "path": str(motoko_repo),
            "exists": motoko_repo.exists(),
            "commit": _run_git(["rev-parse", "HEAD"], cwd=motoko_repo) if motoko_repo.exists() else None,
        },
        "database": {
            "path": str(db_path),
            "schema_version": SCHEMA_VERSION,
            "exists": db_path.exists(),
        },
        "github": github,
        "stripe": {
            "package_version": stripe_package,
            "cli_version": stripe_cli_version(),
            "blockers": _stripe_live_blockers(),
        },
        "project_agent": project_agent,
        "solver_agent": solver_agent,
        "openshell": openshell,
        "ports": {"4242": _port_available(4242), "8088": _port_available(8088)},
        "runtime": {
            "python": sys.version.split()[0],
            "nix": shutil.which("nix") is not None,
        },
        "secret_scan": {"tracked_or_unignored_secret_files": secret_files, "ok": not secret_files},
        "blockers": blockers,
        "fallback_mode": fallback_mode,
    }


def _stripe_live_blockers() -> list[str]:
    blockers: list[str] = []
    if os.environ.get("AGENT_BOUNTY_STRIPE_SANDBOX") != "1":
        blockers.append("set AGENT_BOUNTY_STRIPE_SANDBOX=1")
    if not os.environ.get("STRIPE_TEST_SECRET_KEY"):
        blockers.append("set STRIPE_TEST_SECRET_KEY")
    if not os.environ.get("STRIPE_TEST_WEBHOOK_SECRET"):
        blockers.append("set STRIPE_TEST_WEBHOOK_SECRET")
    if not os.environ.get("STRIPE_TEST_CONNECTED_ACCOUNT_ID"):
        blockers.append("set STRIPE_TEST_CONNECTED_ACCOUNT_ID")
    if stripe_package_version() is None:
        blockers.append("install optional stripe==15.2.0 package")
    if stripe_cli_version() is None:
        blockers.append("install/authenticate Stripe CLI")
    return blockers


def _tracked_or_unignored_secret_files(root: Path) -> list[str]:
    candidates = [root / ".env", root / ".demo" / "stripe.sqlite3"]
    unsafe: list[str] = []
    for path in candidates:
        if not path.exists():
            continue
        tracked = subprocess.run(["git", "ls-files", "--error-unmatch", str(path.relative_to(root))], cwd=root, capture_output=True, text=True)
        ignored = subprocess.run(["git", "check-ignore", "-q", str(path.relative_to(root))], cwd=root, capture_output=True)
        if tracked.returncode == 0 or ignored.returncode != 0:
            unsafe.append(str(path.relative_to(root)))
    return unsafe


def run_local_demo(
    *,
    db_path: Path | None = None,
    motoko_repo: Path | None = None,
    bundle_dir: Path | None = None,
    fresh: bool = True,
) -> dict[str, Any]:
    db_path = db_path or default_demo_db("local")
    motoko_repo = motoko_repo or default_motoko_repo()
    bundle_dir = bundle_dir or default_bundle_dir("local")
    if not motoko_repo.exists():
        raise DemoPresentationError(f"Motoko fixture repo missing: {motoko_repo}")
    if fresh and db_path.exists():
        _delete_demo_path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    market = AgentBountyMarket(connect(db_path), FakePaymentGateway(), ProtectedVerifierRunner(timeout_seconds=60.0))
    demo = run_demo_economic_loop(market, motoko_repo=motoko_repo)
    elapsed_ms = int((time.monotonic() - start) * 1000)
    snapshot = snapshot_database(market)
    bundle = build_bundle(
        mode="local",
        db_path=db_path,
        demo_result=demo,
        snapshot=snapshot,
        duration_ms=elapsed_ms,
    )
    manifest = write_bundle(bundle_dir, bundle, overwrite=True)
    return {
        "schema": REHEARSAL_SCHEMA,
        "ok": bool(demo.get("ok")),
        "mode": "local",
        "duration_ms": elapsed_ms,
        "db": str(db_path),
        "bundle_dir": str(bundle_dir),
        "bundle_digest": manifest["bundle_digest"],
        "dashboard": str(bundle_dir / "dashboard.html"),
        "demo": demo,
    }


def live_refusal_report(*, db_path: Path | None = None, motoko_repo: Path | None = None) -> dict[str, Any]:
    preflight = demo_preflight_report(mode="live", db_path=db_path, motoko_repo=motoko_repo)
    return {
        "schema": "agent-bounty-demo-live-v1",
        "ok": False,
        "stage": "preflight",
        "blockers": preflight["blockers"],
        "fallback": "use demo-replay with an authenticated bundle or demo-local for deterministic development",
        "preflight": preflight,
    }


def rehearse_demo(*, mode: str, db_path: Path | None = None, motoko_repo: Path | None = None, bundle_dir: Path | None = None) -> dict[str, Any]:
    mode = mode.lower()
    started = time.monotonic()
    if mode == "local":
        result = run_local_demo(db_path=db_path, motoko_repo=motoko_repo, bundle_dir=bundle_dir, fresh=True)
        stages = [{"name": "local-economic-loop", "duration_ms": result["duration_ms"], "ok": result["ok"]}]
        return {
            "schema": REHEARSAL_SCHEMA,
            "ok": result["ok"],
            "mode": mode,
            "duration_ms": int((time.monotonic() - started) * 1000),
            "stages": stages,
            "result": {key: value for key, value in result.items() if key != "demo"},
        }
    if mode == "replay":
        if bundle_dir is None:
            bundle_dir = default_bundle_dir("local")
        validation = validate_bundle(bundle_dir)
        return {
            "schema": REHEARSAL_SCHEMA,
            "ok": validation["ok"],
            "mode": mode,
            "duration_ms": int((time.monotonic() - started) * 1000),
            "stages": [{"name": "validate-bundle", "duration_ms": int((time.monotonic() - started) * 1000), "ok": validation["ok"]}],
            "validation": validation,
        }
    if mode == "live":
        report = live_refusal_report(db_path=db_path, motoko_repo=motoko_repo)
        return {
            "schema": REHEARSAL_SCHEMA,
            "ok": False,
            "mode": mode,
            "duration_ms": int((time.monotonic() - started) * 1000),
            "stages": [{"name": "live-preflight", "duration_ms": int((time.monotonic() - started) * 1000), "ok": False}],
            "blockers": report["blockers"],
            "result": report,
        }
    raise DemoPresentationError("mode must be local, replay, or live")


def snapshot_database(market: AgentBountyMarket) -> dict[str, list[dict[str, Any]]]:
    tables = [
        "projects",
        "treasuries",
        "funding_events",
        "bounties",
        "claims",
        "submissions",
        "verification_receipts",
        "payouts",
        "ledger_entries",
        "github_issue_contracts",
        "project_agent_decisions",
        "solver_agent_evaluations",
        "solver_agent_submissions",
        "settlement_allocations",
        "solver_operating_spends",
    ]
    snapshot: dict[str, list[dict[str, Any]]] = {}
    for table in tables:
        try:
            rows = market.conn.execute(f"SELECT * FROM {table}").fetchall()
        except Exception:
            rows = []
        snapshot[table] = [dict(row) for row in rows]
    return snapshot


def build_bundle(*, mode: str, db_path: Path, demo_result: dict[str, Any], snapshot: dict[str, list[dict[str, Any]]], duration_ms: int) -> dict[str, Any]:
    fake_provider = mode == "local" or demo_result.get("provider_truth", {}).get("real_stripe_transfer_claimed") is False
    bundle = {
        "schema": BUNDLE_SCHEMA,
        "mode": mode,
        "fake_provider": fake_provider,
        "created_at": utc_now(),
        "duration_ms": int(duration_ms),
        "repository": {
            "market_path": str(repo_root()),
            "market_commit": _run_git(["rev-parse", "HEAD"], cwd=repo_root()),
            "market_branch": _run_git(["branch", "--show-current"], cwd=repo_root()),
        },
        "database": {"path": str(db_path), "schema_version": SCHEMA_VERSION},
        "summary": summarize_demo(demo_result, snapshot),
        "timeline": build_timeline(snapshot),
        "demo_result": demo_result,
        "snapshot": snapshot,
        "redaction": {
            "secrets_included": False,
            "full_webhook_payloads_included": False,
            "private_prompts_included": False,
        },
    }
    bundle["bundle_content_digest"] = sha256_text(stable_json({key: value for key, value in bundle.items() if key != "bundle_content_digest"}))
    return bundle


def summarize_demo(demo_result: dict[str, Any], snapshot: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    allocation = demo_result.get("allocation", {})
    spend = demo_result.get("retained_credit_spend", {})
    first = demo_result.get("first_bounty", {})
    return {
        "pitch": "A project buys verified software work from a specialized agent and settlement happens exactly once.",
        "ok": bool(demo_result.get("ok")),
        "project": "lk251/motoko",
        "reward": allocation.get("reward_amount"),
        "external_transfer": allocation.get("external_transfer_amount"),
        "external_transfer_id": allocation.get("gateway_transfer_id"),
        "retained_operating_credit": allocation.get("retained_operating_amount"),
        "second_bounty": spend.get("target_bounty_id"),
        "second_bounty_url": spend.get("github_issue_url"),
        "contract_digest": first.get("contract_digest"),
        "receipt_id": first.get("receipt_id"),
        "receipt_count": len(snapshot.get("verification_receipts", [])),
        "ledger_entries": len(snapshot.get("ledger_entries", [])),
        "mode_badge": "Local simulation" if demo_result.get("provider_truth", {}).get("real_stripe_transfer_claimed") is False else "Recorded real run",
    }


def build_timeline(snapshot: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for row in snapshot.get("funding_events", []):
        events.append({"at": row.get("created_at"), "kind": "funding", "label": "Project treasury funded", "detail": f"{row.get('amount')} {row.get('currency')} via {row.get('gateway_event_id')}"})
    for row in snapshot.get("project_agent_decisions", []):
        events.append({"at": row.get("created_at"), "kind": "project-agent", "label": f"Project agent {row.get('trusted_verdict')}", "detail": row.get("policy_reasons_json")})
    for row in snapshot.get("github_issue_contracts", []):
        events.append({"at": row.get("created_at"), "kind": "github", "label": "GitHub bounty contract published", "detail": row.get("contract_digest")})
    for row in snapshot.get("solver_agent_evaluations", []):
        events.append({"at": row.get("created_at"), "kind": "solver-agent", "label": f"Solver {row.get('trusted_verdict')}", "detail": row.get("policy_reasons_json")})
    for row in snapshot.get("verification_receipts", []):
        verdict = "accepted" if int(row.get("accepted", 0)) else "rejected"
        events.append({"at": row.get("created_at"), "kind": "verification", "label": f"Verifier {verdict}", "detail": row.get("id")})
    for row in snapshot.get("settlement_allocations", []):
        events.append({"at": row.get("created_at"), "kind": "settlement", "label": "Reward split settled", "detail": f"external {row.get('external_transfer_amount')} retained {row.get('retained_operating_amount')}"})
    for row in snapshot.get("solver_operating_spends", []):
        events.append({"at": row.get("created_at"), "kind": "compound", "label": "Retained credit funds next bounty", "detail": row.get("target_bounty_id")})
    return sorted(events, key=lambda item: (str(item.get("at") or ""), item["kind"], item["label"]))


def write_bundle(bundle_dir: Path, bundle: dict[str, Any], *, overwrite: bool = False) -> dict[str, Any]:
    if bundle_dir.exists() and overwrite:
        _delete_demo_path(bundle_dir)
    bundle_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = bundle_dir / "bundle.json"
    dashboard_path = bundle_dir / "dashboard.html"
    bundle_path.write_text(stable_json(bundle) + "\n", encoding="utf-8")
    dashboard_path.write_text(render_dashboard(bundle), encoding="utf-8")
    manifest = {
        "schema": BUNDLE_MANIFEST_SCHEMA,
        "mode": bundle["mode"],
        "fake_provider": bool(bundle["fake_provider"]),
        "created_at": utc_now(),
        "bundle_digest": file_digest(bundle_path),
        "files": {
            "bundle.json": file_digest(bundle_path),
            "dashboard.html": file_digest(dashboard_path),
        },
    }
    (bundle_dir / "manifest.json").write_text(stable_json(manifest) + "\n", encoding="utf-8")
    return manifest


def validate_bundle(bundle_dir: Path) -> dict[str, Any]:
    manifest_path = bundle_dir / "manifest.json"
    if not manifest_path.exists():
        raise DemoPresentationError(f"bundle manifest missing: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != BUNDLE_MANIFEST_SCHEMA:
        raise DemoPresentationError("bundle manifest schema mismatch")
    mismatches: list[str] = []
    for relative, expected in manifest.get("files", {}).items():
        path = bundle_dir / relative
        if not path.exists():
            mismatches.append(f"missing {relative}")
            continue
        actual = file_digest(path)
        if actual != expected:
            mismatches.append(f"digest mismatch for {relative}")
    bundle = json.loads((bundle_dir / "bundle.json").read_text(encoding="utf-8"))
    if bundle.get("schema") != BUNDLE_SCHEMA:
        mismatches.append("bundle schema mismatch")
    if bundle.get("mode") != manifest.get("mode"):
        mismatches.append("manifest mode does not match bundle mode")
    if bool(bundle.get("fake_provider")) != bool(manifest.get("fake_provider")):
        mismatches.append("manifest fake_provider does not match bundle")
    if bundle.get("fake_provider") and bundle.get("mode") == "live":
        mismatches.append("fake bundle cannot claim live mode")
    if bundle.get("fake_provider") and bundle.get("summary", {}).get("mode_badge") != "Local simulation":
        mismatches.append("fake bundle must display Local simulation badge")
    return {
        "schema": BUNDLE_VALIDATION_SCHEMA,
        "ok": not mismatches,
        "bundle_dir": str(bundle_dir),
        "mode": bundle.get("mode"),
        "fake_provider": bool(bundle.get("fake_provider")),
        "bundle_digest": manifest.get("bundle_digest"),
        "mismatches": mismatches,
        "dashboard": str(bundle_dir / "dashboard.html"),
        "summary": bundle.get("summary", {}),
    }


def render_dashboard(bundle: dict[str, Any]) -> str:
    summary = bundle.get("summary", {})
    timeline = bundle.get("timeline", [])
    badge = summary.get("mode_badge", "Unknown mode")
    status = "PASS" if summary.get("ok") else "CHECK"
    cards = [
        ("Project", [("Repository", summary.get("project")), ("Reward", summary.get("reward")), ("Contract", summary.get("contract_digest"))]),
        ("Agent Decision", [("Mode", badge), ("Receipt", summary.get("receipt_id")), ("Ledger entries", summary.get("ledger_entries"))]),
        ("Economics", [("External", summary.get("external_transfer")), ("Transfer ID", summary.get("external_transfer_id")), ("Retained", summary.get("retained_operating_credit"))]),
        ("Compounding", [("Second bounty", summary.get("second_bounty")), ("URL", summary.get("second_bounty_url")), ("Bundle", bundle.get("bundle_content_digest"))]),
    ]
    card_html = "\n".join(_card(title, rows) for title, rows in cards)
    timeline_html = "\n".join(
        f"<li><b>{html.escape(str(item.get('label')))}</b><span>{html.escape(str(item.get('detail') or ''))}</span></li>"
        for item in timeline
    )
    return f"""<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Agent Bounty Demo</title>
<style>
body{{font-family:system-ui,-apple-system,Segoe UI,sans-serif;margin:0;background:#f6f5f2;color:#171717}}
header{{padding:32px 40px;background:#111;color:#fff;display:flex;justify-content:space-between;gap:24px;align-items:flex-start}}
h1{{font-size:34px;margin:0 0 10px}} p{{margin:0;max-width:780px;line-height:1.45}}
.badge{{border:1px solid #fff;padding:8px 12px;text-transform:uppercase;font-weight:700;letter-spacing:.04em}}
main{{padding:28px 40px}} .grid{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px}}
.card{{background:#fff;border:1px solid #d8d5cf;border-radius:8px;padding:16px;min-height:150px}}
.card h2{{font-size:16px;margin:0 0 12px}} .row{{border-top:1px solid #ece9e2;padding:8px 0}}
.key{{display:block;color:#666;font-size:12px;text-transform:uppercase}} .value{{font-family:ui-monospace,Menlo,monospace;word-break:break-word}}
ol{{background:#fff;border:1px solid #d8d5cf;border-radius:8px;padding:18px 18px 18px 42px}}
li{{margin:10px 0}} li span{{display:block;color:#555;margin-top:2px}}
@media(max-width:1000px){{.grid{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}
</style>
<header><div><h1>Agent Bounty Market</h1><p>A project receives a budget, buys a verified improvement from a specialized agent, settles exactly once, and lets retained operating credit fund the next useful bounty.</p></div><div class="badge">{html.escape(str(badge))} · {status}</div></header>
<main><section class="grid">{card_html}</section><h2>Timeline</h2><ol>{timeline_html}</ol></main>
</html>
"""


def _card(title: str, rows: list[tuple[str, Any]]) -> str:
    body = "\n".join(
        f"<div class=\"row\"><span class=\"key\">{html.escape(key)}</span><span class=\"value\">{html.escape(str(value))}</span></div>"
        for key, value in rows
    )
    return f"<article class=\"card\"><h2>{html.escape(title)}</h2>{body}</article>"


def replay_bundle(bundle_dir: Path) -> dict[str, Any]:
    validation = validate_bundle(bundle_dir)
    return {
        "schema": "agent-bounty-demo-replay-v1",
        "ok": validation["ok"],
        "mode": "replay",
        "label": "Replay of recorded real run" if not validation["fake_provider"] else "Replay of local simulation",
        "validation": validation,
    }


def reset_demo_state(path: Path | None = None, *, yes: bool = False) -> dict[str, Any]:
    target = path or (repo_root() / ".demo")
    if not yes:
        raise DemoPresentationError("demo reset requires --yes")
    _delete_demo_path(target)
    return {"schema": RESET_SCHEMA, "ok": True, "deleted": str(target)}


def _delete_demo_path(path: Path) -> None:
    root = repo_root().resolve()
    resolved = path.resolve()
    demo_root = (root / ".demo").resolve()
    if resolved != demo_root and demo_root not in resolved.parents:
        raise DemoPresentationError(f"refusing to delete outside .demo: {path}")
    if not resolved.exists():
        return
    if resolved.is_dir():
        shutil.rmtree(resolved)
    else:
        resolved.unlink()
