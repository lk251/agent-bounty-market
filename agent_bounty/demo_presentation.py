from __future__ import annotations

import html
import json
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from .core import AgentBountyMarket
from .db import SCHEMA_VERSION, connect
from .economic_loop import REAL_STRIPE_EVIDENCE, economic_loop_status_report, run_demo_economic_loop
from .execution import openshell_status
from .github_integration import github_status_report
from .hermes_integration import hermes_status_report
from .live_setup import live_setup_wizard_report, stripe_setup_status_report
from .nvidia_runtime import nvidia_runtime_status_report
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
TRUTH_MATRIX_SCHEMA = "agent-bounty-truth-matrix-v1"
ATTESTATION_SCHEMA = "agent-bounty-demo-attestation-v1"
RECORDING_TIMELINE_SCHEMA = "agent-bounty-recording-timeline-v1"
SERVE_REPORT_SCHEMA = "agent-bounty-demo-serve-v1"
RESET_SCHEMA = "agent-bounty-demo-reset-v1"
DIRECTOR_REPORT_SCHEMA = "agent-bounty-demo-director-v1"
DIRECTOR_CUES_SCHEMA = "agent-bounty-demo-director-cues-v1"

SECRET_PATTERNS = (
    "sk_test_",
    "rk_test_",
    "sk_live_",
    "rk_live_",
    "whsec_",
    "ghp_",
    "github_pat_",
    "NVIDIA_API_KEY=",
)
PRIVATE_PATH_MARKERS = (
    "/home/",
    "/Users/",
)
REQUIRED_DASHBOARD_TEXT = (
    "Project buys work",
    "Agents choose",
    "GitHub work",
    "Trust",
    "Economics compound",
    "Fallbacks and blockers",
    "Recording cues",
    "Verified software work became operating capital.",
)
RECORDING_STAGES = (
    ("00:00", "Problem", "A real project has useful work that needs funding, verification, and settlement."),
    ("00:15", "Project buys work", "Budget and policy select one measurable Motoko TUI improvement."),
    ("00:35", "Agents choose", "Specialized agents decline or claim based on scope, capability, and margin."),
    ("00:55", "Trust boundary", "The protected verifier accepts only the exact candidate SHA and records a receipt."),
    ("01:20", "Settlement", "The reward is split into external transfer and retained operating credit."),
    ("01:45", "Compounding", "Retained credit funds the next bounded bounty without hiding fallback rows."),
    ("02:05", "Close", "Verified software work became operating capital."),
)


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


def default_winning_bundle_dir() -> Path:
    return repo_root() / "demo" / "bundles" / "winning-run"


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
    live_setup = None
    if not motoko_repo.exists():
        blockers.append(f"Motoko fixture repo missing: {motoko_repo}")
    if mode == "live":
        live_setup = live_setup_wizard_report()
        blockers.extend(live_setup["preflight_blockers"])
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
        "live_setup": live_setup,
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
    return list(stripe_setup_status_report().get("blockers", []))


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


def run_winning_bundle(
    *,
    db_path: Path | None = None,
    motoko_repo: Path | None = None,
    bundle_dir: Path | None = None,
    fresh: bool = True,
) -> dict[str, Any]:
    db_path = db_path or default_demo_db("winning-run")
    motoko_repo = motoko_repo or default_motoko_repo()
    bundle_dir = bundle_dir or default_winning_bundle_dir()
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
    truth_matrix = build_truth_matrix()
    bundle = build_bundle(
        mode="mixed",
        db_path=db_path,
        demo_result=demo,
        snapshot=snapshot,
        duration_ms=elapsed_ms,
        truth_matrix=truth_matrix,
    )
    manifest = write_bundle(bundle_dir, bundle, overwrite=True)
    validation = validate_bundle(bundle_dir)
    return {
        "schema": "agent-bounty-winning-run-build-v1",
        "ok": bool(validation["ok"]),
        "mode": "mixed",
        "duration_ms": elapsed_ms,
        "db": str(db_path),
        "bundle_dir": str(bundle_dir),
        "bundle_digest": manifest["bundle_digest"],
        "attestation_digest": manifest.get("attestation_digest"),
        "dashboard": str(bundle_dir / "dashboard.html"),
        "truth_overall": truth_matrix["overall_status"],
        "validation": validation,
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


def rehearse_demo(*, mode: str, db_path: Path | None = None, motoko_repo: Path | None = None, bundle_dir: Path | None = None, repeats: int = 1) -> dict[str, Any]:
    mode = mode.lower()
    repeats = max(1, int(repeats))
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
        runs: list[dict[str, Any]] = []
        validation: dict[str, Any] | None = None
        for index in range(repeats):
            stage_start = time.monotonic()
            validation = validate_bundle(bundle_dir)
            runs.append({"index": index + 1, "duration_ms": int((time.monotonic() - stage_start) * 1000), "ok": validation["ok"]})
        assert validation is not None
        durations = [run["duration_ms"] for run in runs]
        return {
            "schema": REHEARSAL_SCHEMA,
            "ok": validation["ok"],
            "mode": mode,
            "duration_ms": int((time.monotonic() - started) * 1000),
            "stages": [{"name": "validate-bundle", "duration_ms": run["duration_ms"], "ok": run["ok"], "index": run["index"]} for run in runs],
            "repeat_count": repeats,
            "duration_range_ms": [min(durations), max(durations)],
            "duration_p95_ms": _p95(durations),
            "dashboard": validation.get("dashboard"),
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


def prepare_demo_serve_report(*, bundle_dir: Path, host: str = "127.0.0.1", port: int = 8787) -> dict[str, Any]:
    validation = validate_bundle(bundle_dir)
    dashboard_path = (bundle_dir / "dashboard.html").resolve()
    url = f"http://{host}:{int(port)}/dashboard.html"
    return {
        "schema": SERVE_REPORT_SCHEMA,
        "ok": bool(validation["ok"]),
        "host": host,
        "port": int(port),
        "url": url,
        "bundle_dir": str(bundle_dir),
        "dashboard": str(dashboard_path),
        "bundle_digest": validation.get("bundle_digest"),
        "attestation_digest": validation.get("attestation_digest"),
        "mode": validation.get("mode"),
        "mode_badge": validation.get("summary", {}).get("mode_badge"),
        "truth_overall": (validation.get("truth_matrix") or {}).get("overall_status"),
        "mismatches": validation.get("mismatches", []),
    }


def prepare_demo_director_report(*, bundle_dir: Path, host: str = "127.0.0.1", port: int = 8788, duration: int = 120) -> dict[str, Any]:
    validation = validate_bundle(bundle_dir)
    assets = write_director_assets(bundle_dir, duration=duration) if validation["ok"] else {}
    url = f"http://{host}:{int(port)}/director.html?duration={int(duration)}"
    record_url = f"http://{host}:{int(port)}/director-record.html?duration={int(duration)}&autoplay=1"
    return {
        "schema": DIRECTOR_REPORT_SCHEMA,
        "ok": bool(validation["ok"] and assets.get("ok")),
        "host": host,
        "port": int(port),
        "duration_seconds": int(duration),
        "url": url,
        "record_url": record_url,
        "notes_url": f"http://{host}:{int(port)}/director-notes.html",
        "bundle_dir": str(bundle_dir),
        "bundle_digest": validation.get("bundle_digest"),
        "mode_badge": validation.get("summary", {}).get("mode_badge"),
        "truth_overall": (validation.get("truth_matrix") or {}).get("overall_status"),
        "scene_count": assets.get("scene_count", 0),
        "asset_paths": assets.get("paths", []),
        "mismatches": validation.get("mismatches", []),
    }


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


def build_bundle(
    *,
    mode: str,
    db_path: Path,
    demo_result: dict[str, Any],
    snapshot: dict[str, list[dict[str, Any]]],
    duration_ms: int,
    truth_matrix: dict[str, Any] | None = None,
) -> dict[str, Any]:
    fake_provider = mode in {"local", "mixed"} or demo_result.get("provider_truth", {}).get("real_stripe_transfer_claimed") is False
    summary = summarize_demo(demo_result, snapshot, mode=mode, truth_matrix=truth_matrix)
    bundle = {
        "schema": BUNDLE_SCHEMA,
        "mode": mode,
        "fake_provider": fake_provider,
        "truth_mode": truth_matrix["overall_status"] if truth_matrix else ("local" if mode == "local" else mode),
        "created_at": utc_now(),
        "duration_ms": int(duration_ms),
        "repository": {
            "market_path": str(repo_root()),
            "market_commit": _run_git(["rev-parse", "HEAD"], cwd=repo_root()),
            "market_branch": _run_git(["branch", "--show-current"], cwd=repo_root()),
        },
        "database": {"path": str(db_path), "schema_version": SCHEMA_VERSION},
        "summary": summary,
        "consistency": build_consistency(summary, demo_result),
        "truth_matrix": truth_matrix,
        "timeline": build_timeline(snapshot),
        "demo_result": demo_result,
        "snapshot": snapshot,
        "evidence": build_evidence_payloads(truth_matrix=truth_matrix, demo_result=demo_result, snapshot=snapshot),
        "redaction": {
            "secrets_included": False,
            "full_webhook_payloads_included": False,
            "private_prompts_included": False,
        },
    }
    bundle = _sanitize_bundle_value(bundle)
    bundle["bundle_content_digest"] = sha256_text(stable_json({key: value for key, value in bundle.items() if key != "bundle_content_digest"}))
    return bundle


def summarize_demo(
    demo_result: dict[str, Any],
    snapshot: dict[str, list[dict[str, Any]]],
    *,
    mode: str = "local",
    truth_matrix: dict[str, Any] | None = None,
) -> dict[str, Any]:
    allocation = demo_result.get("allocation", {})
    spend = demo_result.get("retained_credit_spend", {})
    first = demo_result.get("first_bounty", {})
    mode_badge = "Local simulation"
    if mode == "mixed":
        mode_badge = "Mixed real/fallback"
    elif truth_matrix and truth_matrix.get("overall_status") == "recorded-real":
        mode_badge = "Recorded real run"
    return {
        "pitch": "A project buys verified software work from a specialized agent and settlement happens exactly once.",
        "ok": bool(demo_result.get("ok")) and mode == "local",
        "operation_ok": bool(demo_result.get("ok")),
        "project": "lk251/motoko",
        "reward": allocation.get("reward_amount"),
        "currency": allocation.get("currency"),
        "external_transfer": allocation.get("external_transfer_amount"),
        "external_transfer_id": allocation.get("gateway_transfer_id"),
        "retained_operating_credit": allocation.get("retained_operating_amount"),
        "second_bounty": spend.get("target_bounty_id"),
        "second_bounty_url": spend.get("github_issue_url"),
        "contract_digest": first.get("contract_digest"),
        "receipt_id": first.get("receipt_id"),
        "candidate_sha": first.get("candidate_sha"),
        "receipt_count": len(snapshot.get("verification_receipts", [])),
        "ledger_entries": len(snapshot.get("ledger_entries", [])),
        "mode_badge": mode_badge,
        "truth_overall": truth_matrix.get("overall_status") if truth_matrix else mode_badge.lower().replace(" ", "-"),
    }


def build_consistency(summary: dict[str, Any], demo_result: dict[str, Any]) -> dict[str, Any]:
    allocation = demo_result.get("allocation", {})
    return {
        "project": summary.get("project"),
        "bounty_id": allocation.get("bounty_id") or demo_result.get("first_bounty", {}).get("bounty_id"),
        "candidate_sha": summary.get("candidate_sha"),
        "currency": allocation.get("currency"),
        "accepted_receipt_id": allocation.get("accepted_receipt_id") or summary.get("receipt_id"),
        "allocation_id": allocation.get("allocation_id"),
    }


def build_truth_matrix() -> dict[str, Any]:
    hermes = hermes_status_report(probe_doctor=False, discover_models=False)
    nvidia = nvidia_runtime_status_report(discover_models=False, doctor=False)
    github = github_status_report()
    project_agent = project_agent_status_report()
    solver_agent = solver_agent_status_report()
    economic = economic_loop_status_report()
    rows = [
        _truth_row(
            "hermes_executable",
            "Hermes executable/version",
            "real" if hermes.get("hermes", {}).get("version", {}).get("ok") else "blocked",
            hermes.get("hermes", {}),
            None if hermes.get("hermes", {}).get("version", {}).get("ok") else _first_blocker(hermes.get("blockers")),
            8,
            "dae313d",
        ),
        _truth_row(
            "nemotron_model",
            "NVIDIA Nemotron model",
            "real" if hermes.get("provider", {}).get("configured") else "blocked",
            hermes.get("provider", {}),
            _first_blocker(hermes.get("blockers")),
            8,
            "dae313d",
        ),
        _truth_row(
            "project_agent_decision",
            "Project-agent decision",
            "real" if project_agent.get("hermes_runtime", {}).get("available") else "fallback",
            {"fake_runtime_available": project_agent.get("fake_runtime_available"), "hermes_runtime": project_agent.get("hermes_runtime")},
            _first_blocker(project_agent.get("hermes_runtime", {}).get("blockers")),
            8,
            "dae313d",
        ),
        _truth_row(
            "solver_agent_decision",
            "Solver-agent decision",
            "real" if solver_agent.get("hermes_runtime", {}).get("available") else "fallback",
            {"fake_runtime_available": solver_agent.get("fake_runtime_available"), "hermes_runtime": solver_agent.get("hermes_runtime")},
            _first_blocker(solver_agent.get("hermes_runtime", {}).get("blockers")),
            8,
            "dae313d",
        ),
        _truth_row(
            "openshell_nemoclaw",
            "OpenShell/NemoClaw execution",
            "real" if nvidia.get("real_backend_ready") else "blocked",
            {"openshell": nvidia.get("openshell"), "policy": nvidia.get("policy"), "real_backend_ready": nvidia.get("real_backend_ready")},
            _first_blocker(nvidia.get("blockers")),
            9,
            "ad2d80b",
        ),
        _truth_row(
            "github_lifecycle",
            "GitHub issue/claim/PR/result",
            "real" if github.get("ok") else "blocked",
            github,
            _first_blocker(github.get("blockers")),
            10,
            "14e1d24",
        ),
        _truth_row(
            "stripe_full_transfer_fragment",
            "Prior Stripe sandbox full-transfer fragment",
            "recorded-real",
            REAL_STRIPE_EVIDENCE,
            None,
            11,
            "089836e",
        ),
        _truth_row(
            "stripe_split_transfer",
            "Fresh split Stripe Connect Transfer",
            "real" if economic.get("stripe_sandbox_configured") else "blocked",
            {"split_settlement_adapter": economic.get("split_settlement_adapter"), "stripe_blockers": economic.get("stripe_blockers")},
            _first_blocker(economic.get("stripe_blockers")),
            11,
            "089836e",
        ),
        _truth_row(
            "retained_credit_spend",
            "Retained credit funds second bounty",
            "fallback" if not economic.get("stripe_sandbox_configured") else "real",
            {"deterministic_fake_loop_available": economic.get("deterministic_fake_loop_available")},
            None if economic.get("stripe_sandbox_configured") else "fresh real split settlement is blocked; deterministic retained-credit spend is shown",
            11,
            "089836e",
        ),
    ]
    required = {row["status"] for row in rows}
    overall = "recorded-real" if required <= {"real", "recorded-real"} else "mixed-real-fallback"
    return {
        "schema": TRUTH_MATRIX_SCHEMA,
        "created_at": utc_now(),
        "overall_status": overall,
        "all_required_real": overall == "recorded-real",
        "rows": rows,
        "digest": sha256_text(stable_json(rows)),
    }


def _truth_row(component_id: str, label: str, status: str, evidence: dict[str, Any], blocker: str | None, source_issue: int, source_commit: str) -> dict[str, Any]:
    safe_evidence = _sanitize_bundle_value(evidence)
    return {
        "component_id": component_id,
        "label": label,
        "status": status,
        "safe_evidence": safe_evidence,
        "safe_evidence_digest": sha256_text(stable_json(safe_evidence)),
        "blocker": blocker,
        "source_issue": source_issue,
        "source_commit": source_commit,
    }


def _sanitize_bundle_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _sanitize_bundle_value(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_sanitize_bundle_value(child) for child in value]
    if not isinstance(value, str):
        return value
    replacements = [
        (str(repo_root()), "<agent-bounty-market>"),
        (str(default_motoko_repo()), "<motoko-fixture>"),
        (str(Path.home()), "<home>"),
    ]
    text = value
    for original, replacement in sorted(replacements, key=lambda item: len(item[0]), reverse=True):
        if original:
            text = text.replace(original, replacement)
    return text


def _first_blocker(blockers: Any) -> str | None:
    if isinstance(blockers, list) and blockers:
        return str(blockers[0])
    if isinstance(blockers, str) and blockers:
        return blockers
    return None


def build_evidence_payloads(*, truth_matrix: dict[str, Any] | None, demo_result: dict[str, Any], snapshot: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    evidence = {
        "demo-summary": {
            "schema": "agent-bounty-demo-summary-evidence-v1",
            "demo_schema": demo_result.get("schema"),
            "demo_ok": bool(demo_result.get("ok")),
            "provider_truth": demo_result.get("provider_truth"),
            "allocation": demo_result.get("allocation"),
            "retained_credit_spend": demo_result.get("retained_credit_spend"),
        },
        "database-counts": {
            "schema": "agent-bounty-database-counts-evidence-v1",
            "tables": {table: len(rows) for table, rows in snapshot.items()},
        },
    }
    if truth_matrix:
        evidence["truth-matrix"] = truth_matrix
    return evidence


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
    bundle["bundle_content_digest"] = sha256_text(stable_json({key: value for key, value in bundle.items() if key != "bundle_content_digest"}))
    bundle_path = bundle_dir / "bundle.json"
    dashboard_path = bundle_dir / "dashboard.html"
    readme_path = bundle_dir / "README.md"
    recording_timeline_path = bundle_dir / "recording-timeline.md"
    evidence_dir = bundle_dir / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    bundle_path.write_text(stable_json(bundle) + "\n", encoding="utf-8")
    dashboard_path.write_text(render_dashboard(bundle), encoding="utf-8")
    readme_path.write_text(render_bundle_readme(bundle), encoding="utf-8")
    recording_timeline_path.write_text(render_recording_timeline(bundle), encoding="utf-8")
    files = {
        "bundle.json": file_digest(bundle_path),
        "dashboard.html": file_digest(dashboard_path),
        "README.md": file_digest(readme_path),
        "recording-timeline.md": file_digest(recording_timeline_path),
    }
    for name, payload in sorted((bundle.get("evidence") or {}).items()):
        relative = f"evidence/{_safe_filename(name)}.json"
        path = bundle_dir / relative
        path.write_text(stable_json(payload) + "\n", encoding="utf-8")
        files[relative] = file_digest(path)
    attestation = build_attestation(bundle, files)
    attestation_path = bundle_dir / "attestation.json"
    attestation_path.write_text(stable_json(attestation) + "\n", encoding="utf-8")
    files["attestation.json"] = file_digest(attestation_path)
    manifest = {
        "schema": BUNDLE_MANIFEST_SCHEMA,
        "mode": bundle["mode"],
        "fake_provider": bool(bundle["fake_provider"]),
        "created_at": utc_now(),
        "bundle_digest": file_digest(bundle_path),
        "attestation_digest": attestation["attestation_digest"],
        "files": files,
    }
    (bundle_dir / "manifest.json").write_text(stable_json(manifest) + "\n", encoding="utf-8")
    return manifest


def render_bundle_readme(bundle: dict[str, Any]) -> str:
    summary = bundle.get("summary", {})
    truth = bundle.get("truth_matrix") or {}
    statuses: dict[str, int] = {}
    rows = truth.get("rows", [])
    if not isinstance(rows, list):
        rows = []
    for row in rows:
        status = str(row.get("status"))
        statuses[status] = statuses.get(status, 0) + 1
    status_text = ", ".join(f"{key}: {value}" for key, value in sorted(statuses.items())) or "none"
    return f"""# Demo Bundle

Mode: `{bundle.get("mode")}`

Badge: `{summary.get("mode_badge")}`

Truth: `{bundle.get("truth_mode")}`

This directory is generated by Agent Bounty Market. Validate it before
recording:

```bash
nix develop --command python3 -m agent_bounty demo-rehearse --mode replay --bundle <this-directory> --repeat 5
```

Truth row counts: {status_text}.

Contents:

- `manifest.json`: file digests and attestation digest.
- `bundle.json`: sanitized demo data, timeline, consistency fields, and truth
  matrix.
- `attestation.json`: hashed attestation only; no signing key was created.
- `dashboard.html`: static presentation surface.
- `recording-timeline.md`: deterministic two-minute recording cues.
- `evidence/*.json`: compact evidence slices.
"""


def build_recording_timeline(bundle: dict[str, Any]) -> dict[str, Any]:
    summary = bundle.get("summary", {})
    truth = bundle.get("truth_matrix") or {}
    blockers = [
        {"component": row.get("label"), "status": row.get("status"), "blocker": row.get("blocker")}
        for row in truth.get("rows", [])
        if row.get("status") in {"fallback", "blocked"}
    ]
    return {
        "schema": RECORDING_TIMELINE_SCHEMA,
        "mode_badge": summary.get("mode_badge"),
        "truth_overall": truth.get("overall_status") or bundle.get("truth_mode"),
        "dashboard": "dashboard.html",
        "stages": [
            {"time": timecode, "title": title, "cue": cue}
            for timecode, title, cue in RECORDING_STAGES
        ],
        "truth_boundary": "Keep the Mixed real/fallback badge visible. Name blocked and fallback components plainly.",
        "blockers": blockers,
    }


def render_recording_timeline(bundle: dict[str, Any]) -> str:
    timeline = build_recording_timeline(bundle)
    lines = [
        "# Recording Timeline",
        "",
        f"Mode badge: `{timeline.get('mode_badge')}`",
        "",
        f"Truth: `{timeline.get('truth_overall')}`",
        "",
        "## Two-Minute Cues",
        "",
    ]
    for stage in timeline["stages"]:
        lines.append(f"- `{stage['time']}` **{stage['title']}** — {stage['cue']}")
    lines.extend(["", "## Truth Boundary", "", str(timeline["truth_boundary"]), "", "## Fallbacks And Blockers", ""])
    for blocker in timeline["blockers"]:
        lines.append(f"- **{blocker.get('component')}**: {blocker.get('status')} — {blocker.get('blocker') or 'fallback shown truthfully'}")
    return "\n".join(lines).rstrip() + "\n"


def write_director_assets(bundle_dir: Path, *, duration: int = 120) -> dict[str, Any]:
    validation = validate_bundle(bundle_dir)
    if not validation["ok"]:
        return {"ok": False, "paths": [], "scene_count": 0, "mismatches": validation["mismatches"]}
    bundle = json.loads((bundle_dir / "bundle.json").read_text(encoding="utf-8"))
    data = build_director_data(bundle, duration=duration)
    cues = build_director_cues(data)
    paths = {
        "director.html": render_director_html(data, include_notes=True),
        "director-record.html": render_director_html(data, include_notes=False),
        "director-notes.html": render_director_notes_html(data),
        "director-cues.json": stable_json(cues) + "\n",
    }
    written: list[str] = []
    for relative, content in paths.items():
        path = bundle_dir / relative
        path.write_text(content, encoding="utf-8")
        written.append(relative)
    return {"ok": True, "paths": written, "scene_count": len(data["scenes"]), "cues_digest": sha256_text(stable_json(cues))}


def build_director_data(bundle: dict[str, Any], *, duration: int = 120) -> dict[str, Any]:
    summary = bundle.get("summary") or {}
    snapshot = bundle.get("snapshot") or {}
    truth = bundle.get("truth_matrix") or {}
    rows = truth.get("rows") if isinstance(truth.get("rows"), list) else []
    rows_by_id = {row.get("component_id"): row for row in rows if isinstance(row, dict)}
    bounties = snapshot.get("bounties") or []
    primary_bounty = bounties[0] if bounties else {}
    followup_bounty = bounties[1] if len(bounties) > 1 else {}
    project_decisions = snapshot.get("project_agent_decisions") or []
    solver_evals = snapshot.get("solver_agent_evaluations") or []
    receipts = snapshot.get("verification_receipts") or []
    allocation = (bundle.get("demo_result") or {}).get("allocation") or {}
    durations = _scene_durations(max(30, int(duration)), 7)
    badge = summary.get("mode_badge") or _expected_badge(bundle)

    scenes = [
        _director_scene(
            "problem",
            "Problem",
            "Useful repo work should become a packaged, verifiable transaction.",
            badge,
            durations[0],
            [
                ("Bounty", primary_bounty.get("title") or "unavailable in bundle"),
                ("Issue", primary_bounty.get("issue_ref") or "unavailable"),
                ("Reward", _money(primary_bounty.get("reward_amount"), primary_bounty.get("currency"))),
            ],
            [
                "The bundle records a real Motoko TUI responsiveness bounty as the first task.",
                "The director uses persisted bundle data only; missing facts render as unavailable.",
            ],
            "Name the problem: valuable maintenance work needs funding, exact acceptance, and safe settlement.",
        ),
        _director_scene(
            "project-buys-work",
            "Project buys work",
            "Policy and budget select one bounded bounty while alternatives can decline.",
            badge,
            durations[1],
            [
                ("Project", summary.get("project")),
                ("Contract digest", _short(summary.get("contract_digest"))),
                ("Project decisions", f"{len(project_decisions)} recorded"),
            ],
            _decision_bullets(project_decisions, "project"),
            "Point at the digest-bound contract and policy-bounded reward.",
        ),
        _director_scene(
            "agents-choose",
            "Agents choose",
            "Specialized solver profiles can decline or claim based on capability and margin.",
            badge,
            durations[2],
            [
                ("Solver decisions", f"{len(solver_evals)} recorded"),
                ("Claimed solver", allocation.get("solver_id") or "unavailable"),
                ("Candidate SHA", _short(summary.get("candidate_sha"))),
            ],
            _decision_bullets(solver_evals, "solver"),
            "Explain that fallback decisions are schema-checked and policy-gated, not hidden as live reasoning.",
        ),
        _director_scene(
            "trust-boundary",
            "Trust boundary",
            "Payment waits for a protected verifier receipt bound to the exact candidate.",
            badge,
            durations[3],
            [
                ("Candidate", _short(summary.get("candidate_sha"))),
                ("Receipt", _short(summary.get("receipt_id"))),
                ("Verifier receipts", f"{len(receipts)} recorded"),
            ],
            [
                f"Accepted receipt: {_short(summary.get('receipt_id'))}",
                "Bad or intermediate verifier outcomes are unavailable in this bundle unless a receipt row records them.",
                f"Contract digest: {_short(summary.get('contract_digest'))}",
            ],
            "Keep this crisp: candidate-owned code cannot authorize payment.",
        ),
        _director_scene(
            "settlement",
            "Settlement",
            "Accepted work is split exactly once into external transfer and retained operating credit.",
            badge,
            durations[4],
            [
                ("Reward", _money(allocation.get("reward_amount"), allocation.get("currency"))),
                ("External", _money(allocation.get("external_transfer_amount"), allocation.get("currency"))),
                ("Retained", _money(allocation.get("retained_operating_amount"), allocation.get("currency"))),
            ],
            [
                f"Transfer provider: {allocation.get('transfer_provider') or 'unavailable'}",
                f"Transfer truth: {((allocation.get('split') or {}).get('truth') or 'unavailable')}",
                f"Ledger entries: {summary.get('ledger_entries')}",
            ],
            "Say that fake external IDs stay visibly fake; only recorded real Stripe IDs are labeled real.",
        ),
        _director_scene(
            "compounding",
            "Compounding",
            "Retained credit funds the second bounded bounty without hiding fallback rows.",
            badge,
            durations[5],
            [
                ("Retained credit", _money(summary.get("retained_operating_credit"), summary.get("currency"))),
                ("Follow-up bounty", followup_bounty.get("title") or summary.get("second_bounty")),
                ("Follow-up state", followup_bounty.get("state") or "unavailable"),
            ],
            [
                f"Second bounty id: {_short(summary.get('second_bounty'))}",
                f"Second bounty URL: {summary.get('second_bounty_url') or 'unavailable'}",
            ],
            "This is the compounding loop: verified software work becomes operating capital.",
        ),
        _director_scene(
            "close",
            "Close",
            "Verified software work became operating capital.",
            badge,
            durations[6],
            [
                ("Truth overall", truth.get("overall_status") or bundle.get("truth_mode")),
                ("Real rows", _truth_count(rows, "real")),
                ("Fallback/blocked rows", _truth_count(rows, "fallback") + _truth_count(rows, "blocked")),
            ],
            _truth_bullets(rows),
            "Close on usefulness, viability, and the sponsor architecture without all-live claims.",
        ),
    ]
    start = 0
    for scene in scenes:
        scene["start_second"] = start
        start += int(scene["duration_seconds"])
    return {
        "schema": "agent-bounty-demo-director-data-v1",
        "duration_seconds": int(duration),
        "mode_badge": badge,
        "truth_overall": truth.get("overall_status") or bundle.get("truth_mode"),
        "bundle_digest": bundle.get("bundle_content_digest"),
        "scenes": scenes,
        "controls": ["ArrowLeft", "ArrowRight", "Space", "Escape", "r"],
    }


def build_director_cues(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": DIRECTOR_CUES_SCHEMA,
        "duration_seconds": data["duration_seconds"],
        "truth_badge": data["mode_badge"],
        "scenes": [
            {
                "id": scene["id"],
                "title": scene["title"],
                "start_second": scene["start_second"],
                "duration_seconds": scene["duration_seconds"],
                "voiceover": scene["voiceover"],
            }
            for scene in data["scenes"]
        ],
    }


def _director_scene(
    scene_id: str,
    title: str,
    subtitle: str,
    badge: str,
    duration: int,
    stats: list[tuple[str, Any]],
    bullets: list[str],
    voiceover: str,
) -> dict[str, Any]:
    return {
        "id": scene_id,
        "title": title,
        "subtitle": subtitle,
        "truth_badge": badge,
        "duration_seconds": int(duration),
        "stats": [{"label": label, "value": str(value if value is not None else "unavailable")} for label, value in stats],
        "bullets": [str(item) for item in bullets if item],
        "voiceover": voiceover,
    }


def _scene_durations(total: int, count: int) -> list[int]:
    base = total // count
    remainder = total % count
    return [base + (1 if index < remainder else 0) for index in range(count)]


def _decision_bullets(rows: list[dict[str, Any]], kind: str) -> list[str]:
    if not rows:
        return [f"No {kind} decisions available in bundle."]
    bullets: list[str] = []
    for row in rows[:5]:
        verdict = row.get("trusted_verdict") or row.get("decision") or "recorded"
        reasons = row.get("policy_reasons_json") or row.get("reasons_json") or ""
        bullets.append(f"{verdict}: {_short(reasons, keep=96)}")
    if len(rows) > 5:
        bullets.append(f"{len(rows) - 5} more {kind} decisions recorded.")
    return bullets


def _truth_count(rows: list[dict[str, Any]], status: str) -> int:
    return sum(1 for row in rows if row.get("status") == status)


def _truth_bullets(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return ["Truth matrix unavailable in bundle."]
    bullets = []
    for row in rows:
        status = row.get("status")
        if status in {"fallback", "blocked", "recorded-real", "real"}:
            bullets.append(f"{row.get('label')}: {status} - {row.get('blocker') or 'evidence recorded in bundle'}")
    return bullets


def render_director_html(data: dict[str, Any], *, include_notes: bool) -> str:
    scenes_html = "\n".join(_render_director_scene(scene, include_notes=include_notes) for scene in data["scenes"])
    data_json = stable_json(data).replace("<", "\\u003c")
    notes_hint = "<a href=\"director-notes.html\">Presenter notes</a>" if include_notes else "Record mode"
    return f"""<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Agent Bounty Director</title>
<style>
*{{box-sizing:border-box}}
html,body{{margin:0;min-height:100%;background:#0d1117;color:#f5f7fb;font-family:system-ui,-apple-system,Segoe UI,sans-serif}}
body{{overflow:hidden}}
.shell{{width:100vw;height:100vh;display:flex;flex-direction:column}}
.top{{height:72px;display:flex;align-items:center;justify-content:space-between;padding:18px 32px;background:#111827;border-bottom:1px solid #2a3444}}
.brand{{font-weight:800;font-size:22px;letter-spacing:.02em}}
.badge{{display:inline-flex;align-items:center;gap:8px;border:2px solid #facc15;color:#facc15;border-radius:999px;padding:8px 14px;font-weight:800;text-transform:uppercase}}
.badge::before{{content:"";width:10px;height:10px;border-radius:50%;background:#facc15;display:inline-block}}
.timer{{font-variant-numeric:tabular-nums;color:#cbd5e1}}
.stage{{display:none;flex:1;padding:46px 58px 42px;gap:36px;grid-template-columns:minmax(0,1.15fr) minmax(360px,.85fr);align-items:stretch}}
.stage.active{{display:grid}}
h1{{font-size:70px;line-height:.95;margin:0 0 18px;letter-spacing:0}}
.subtitle{{font-size:28px;line-height:1.2;color:#cbd5e1;max-width:980px;margin-bottom:34px}}
.bullets{{list-style:none;padding:0;margin:0;display:grid;gap:14px}}
.bullets li{{font-size:24px;line-height:1.28;background:#161d29;border-left:6px solid #60a5fa;padding:16px 18px;border-radius:8px}}
.panel{{background:#111827;border:1px solid #2a3444;border-radius:12px;padding:24px;display:flex;flex-direction:column;gap:20px;min-width:0}}
.stats{{display:grid;gap:12px}}
.stat{{border:1px solid #334155;border-radius:8px;padding:14px;background:#0f172a}}
.stat b{{display:block;color:#93c5fd;font-size:14px;text-transform:uppercase;margin-bottom:6px}}
.stat span{{display:block;font-size:22px;line-height:1.18;overflow-wrap:anywhere}}
.notes{{margin-top:auto;border-top:1px solid #334155;padding-top:16px;color:#e2e8f0;font-size:18px;line-height:1.35}}
.notes strong{{color:#facc15}}
.controls{{height:52px;display:flex;align-items:center;gap:18px;padding:0 32px;background:#111827;border-top:1px solid #2a3444;color:#cbd5e1;font-size:15px}}
.progress{{height:8px;background:#1f2937}}
.bar{{height:100%;width:0;background:#60a5fa;transition:width .2s linear}}
a{{color:#93c5fd}}
@media (prefers-reduced-motion: reduce){{.bar{{transition:none}}}}
</style>
<script type="application/json" id="director-data">{data_json}</script>
<div class="shell">
  <div class="top"><div class="brand">Agent Bounty Market</div><div class="badge">{html.escape(str(data["mode_badge"]))}</div><div class="timer" id="timer">00:00 / {int(data["duration_seconds"]):02d}s</div></div>
  <main>{scenes_html}</main>
  <div class="progress"><div class="bar" id="bar"></div></div>
  <div class="controls">Space pause/resume · Arrow keys navigate · R restart · Esc stop autoplay · {notes_hint}</div>
</div>
<script>
const root=document.querySelector('.shell');
const data=JSON.parse(document.getElementById('director-data').textContent);
const scenes=[...document.querySelectorAll('.stage')];
const timer=document.getElementById('timer');
const bar=document.getElementById('bar');
const params=new URLSearchParams(location.search);
let index=Math.max(0, Math.min(scenes.length-1, parseInt(params.get('scene')||'0',10)||0));
let autoplay=params.get('autoplay')==='1';
let paused=false;
let elapsed=0;
const total=parseInt(params.get('duration')||data.duration_seconds,10)||data.duration_seconds;
function show(i){{index=(i+scenes.length)%scenes.length;scenes.forEach((s,n)=>s.classList.toggle('active',n===index));elapsed=data.scenes.slice(0,index).reduce((a,s)=>a+s.duration_seconds,0);paint();}}
function paint(){{const mm=String(Math.floor(elapsed/60)).padStart(2,'0');const ss=String(elapsed%60).padStart(2,'0');timer.textContent=`${{mm}}:${{ss}} / ${{total}}s`;bar.style.width=`${{Math.min(100,elapsed/total*100)}}%`;}}
function next(){{show(Math.min(index+1,scenes.length-1));}}
function prev(){{show(Math.max(index-1,0));}}
setInterval(()=>{{if(!autoplay||paused)return;elapsed++;let boundary=0;for(let i=0;i<data.scenes.length;i++){{boundary+=data.scenes[i].duration_seconds;if(elapsed>=boundary&&i<scenes.length-1){{index=i+1;scenes.forEach((s,n)=>s.classList.toggle('active',n===index));}}}}paint();if(elapsed>=total)autoplay=false;}},1000);
document.addEventListener('keydown',e=>{{if(e.key==='ArrowRight')next(); if(e.key==='ArrowLeft')prev(); if(e.key===' '){{paused=!paused;autoplay=true;e.preventDefault();}} if(e.key==='r'||e.key==='R'){{elapsed=0;show(0);autoplay=params.get('autoplay')==='1';}} if(e.key==='Escape')autoplay=false;}});
show(index);
</script>
</html>
"""


def _render_director_scene(scene: dict[str, Any], *, include_notes: bool) -> str:
    stats = "\n".join(f"<div class=\"stat\"><b>{html.escape(item['label'])}</b><span>{html.escape(item['value'])}</span></div>" for item in scene["stats"])
    bullets = "\n".join(f"<li>{html.escape(item)}</li>" for item in scene["bullets"])
    notes = f"<div class=\"notes\"><strong>Presenter Notes:</strong> {html.escape(str(scene['voiceover']))}</div>" if include_notes else ""
    return f"""<section class="stage" data-scene="{html.escape(scene['id'])}">
  <div><h1>{html.escape(scene['title'])}</h1><div class="subtitle">{html.escape(scene['subtitle'])}</div><ul class="bullets">{bullets}</ul></div>
  <aside class="panel"><div class="badge">{html.escape(scene['truth_badge'])}</div><div class="stats">{stats}</div>{notes}</aside>
</section>"""


def render_director_notes_html(data: dict[str, Any]) -> str:
    rows = "\n".join(
        f"<li><b>{scene['start_second']:03d}s {html.escape(scene['title'])}</b><p>{html.escape(scene['voiceover'])}</p></li>"
        for scene in data["scenes"]
    )
    return f"""<!doctype html>
<html lang="en">
<meta charset="utf-8">
<title>Director Notes</title>
<style>body{{font-family:system-ui,sans-serif;margin:32px;line-height:1.45;max-width:980px}}li{{margin:0 0 18px}}b{{font-size:18px}}</style>
<h1>Presenter Notes</h1>
<p>Truth badge: <b>{html.escape(str(data["mode_badge"]))}</b>. Duration: {int(data["duration_seconds"])} seconds.</p>
<ol>{rows}</ol>
</html>
"""


def build_attestation(bundle: dict[str, Any], files: dict[str, str]) -> dict[str, Any]:
    payload = {
        "schema": ATTESTATION_SCHEMA,
        "created_at": utc_now(),
        "mode": bundle.get("mode"),
        "truth_mode": bundle.get("truth_mode"),
        "bundle_content_digest": bundle.get("bundle_content_digest"),
        "truth_matrix_digest": (bundle.get("truth_matrix") or {}).get("digest"),
        "files": files,
        "signed": False,
        "signature": None,
        "note": "Hashed attestation only; no private signing key was created.",
        "attestation_digest": None,
    }
    payload["attestation_digest"] = sha256_text(stable_json(payload))
    return payload


def _safe_filename(name: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in name).strip("-") or "evidence"


def validate_bundle(bundle_dir: Path) -> dict[str, Any]:
    manifest_path = bundle_dir / "manifest.json"
    bundle_root = bundle_dir.resolve()
    if not manifest_path.exists():
        raise DemoPresentationError(f"bundle manifest missing: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != BUNDLE_MANIFEST_SCHEMA:
        raise DemoPresentationError("bundle manifest schema mismatch")
    mismatches: list[str] = []
    for relative, expected in manifest.get("files", {}).items():
        path, path_error = _safe_bundle_child(bundle_root, relative)
        if path_error:
            mismatches.append(path_error)
            continue
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
    expected_badge = _expected_badge(bundle)
    if bundle.get("summary", {}).get("mode_badge") != expected_badge:
        mismatches.append(f"bundle must display {expected_badge} badge")
    mismatches.extend(_validate_attestation(bundle_dir, manifest, bundle))
    mismatches.extend(_validate_truth_matrix(bundle))
    mismatches.extend(_validate_consistency(bundle))
    mismatches.extend(_validate_dashboard(bundle_dir / "dashboard.html"))
    mismatches.extend(_validate_recording_timeline(bundle_dir / "recording-timeline.md"))
    mismatches.extend(_secret_scan_bundle(bundle_dir))
    mismatches.extend(_private_path_scan_bundle(bundle_dir))
    return {
        "schema": BUNDLE_VALIDATION_SCHEMA,
        "ok": not mismatches,
        "bundle_dir": str(bundle_dir),
        "mode": bundle.get("mode"),
        "fake_provider": bool(bundle.get("fake_provider")),
        "bundle_digest": manifest.get("bundle_digest"),
        "attestation_digest": manifest.get("attestation_digest"),
        "mismatches": mismatches,
        "dashboard": str(bundle_dir / "dashboard.html"),
        "summary": bundle.get("summary", {}),
        "truth_matrix": bundle.get("truth_matrix"),
    }


def render_dashboard(bundle: dict[str, Any]) -> str:
    summary = bundle.get("summary", {})
    timeline = bundle.get("timeline", [])
    badge = summary.get("mode_badge", "Unknown mode")
    status = "PASS" if summary.get("ok") else "MIXED"
    rows_by_id = {row.get("component_id"): row for row in (bundle.get("truth_matrix") or {}).get("rows", [])}
    github = rows_by_id.get("github_lifecycle", {})
    openshell = rows_by_id.get("openshell_nemoclaw", {})
    stripe_split = rows_by_id.get("stripe_split_transfer", {})
    timeline_plan = build_recording_timeline(bundle)
    cards = [
        ("Project buys work", [("Repository", summary.get("project")), ("Reward", _money(summary.get("reward"), summary.get("currency"))), ("Contract", _short(summary.get("contract_digest")))]),
        ("Agents choose", [("Project agent", _row_status(rows_by_id.get("project_agent_decision"))), ("Solver agent", _row_status(rows_by_id.get("solver_agent_decision"))), ("Claimed SHA", _short(summary.get("candidate_sha")))]),
        ("GitHub work", [("Lifecycle", _row_status(github)), ("Issue / PR", _evidence_hint(github)), ("Contract", _short(summary.get("contract_digest")))]),
        ("Trust", [("OpenShell", _row_status(openshell)), ("Receipt", _short(summary.get("receipt_id"))), ("Ledger entries", summary.get("ledger_entries"))]),
        ("Economics compound", [("External", _money(summary.get("external_transfer"), summary.get("currency"))), ("Transfer", _short(summary.get("external_transfer_id"))), ("Retained -> next", f"{_money(summary.get('retained_operating_credit'), summary.get('currency'))} / {_short(summary.get('second_bounty'))}")]),
    ]
    card_html = "\n".join(_card(title, rows) for title, rows in cards)
    warnings = [row for row in (bundle.get("truth_matrix") or {}).get("rows", []) if row.get("status") in {"fallback", "blocked"}]
    warning_html = "\n".join(
        f"<li><b>{html.escape(str(row.get('label')))}</b><span>{html.escape(str(row.get('status')))} · {html.escape(str(row.get('blocker') or 'fallback shown truthfully'))}</span></li>"
        for row in warnings
    )
    timeline_html = "\n".join(
        f"<li><b>{html.escape(str(item.get('label')))}</b><span>{html.escape(str(item.get('detail') or ''))}</span></li>"
        for item in timeline
    )
    cue_html = "\n".join(
        f"<li><b>{html.escape(str(stage.get('time')))} {html.escape(str(stage.get('title')))}</b><span>{html.escape(str(stage.get('cue')))}</span></li>"
        for stage in timeline_plan["stages"]
    )
    return f"""<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Agent Bounty Demo</title>
<style>
*{{box-sizing:border-box}}
body{{font-family:system-ui,-apple-system,Segoe UI,sans-serif;margin:0;background:#f6f5f2;color:#171717;font-size:16px}}
header{{padding:24px 34px;background:#111;color:#fff;display:flex;justify-content:space-between;gap:24px;align-items:flex-start}}
h1{{font-size:34px;margin:0 0 8px;line-height:1.05}} p{{margin:0;max-width:840px;line-height:1.38}}
.badge{{border:2px solid #fff;padding:10px 14px;text-transform:uppercase;font-weight:800;letter-spacing:.04em;white-space:nowrap}}
main{{padding:20px 34px 28px}} .grid{{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:12px}}
.card{{background:#fff;border:1px solid #d8d5cf;border-radius:8px;padding:14px;min-height:164px;box-shadow:0 1px 2px rgba(0,0,0,.04)}}
.card h2{{font-size:17px;margin:0 0 12px;line-height:1.15}} .row{{border-top:1px solid #ece9e2;padding:8px 0}}
.key{{display:block;color:#666;font-size:12px;text-transform:uppercase;font-weight:700}} .value{{font-family:ui-monospace,Menlo,monospace;word-break:break-word;font-size:14px;line-height:1.3}}
.split{{display:grid;grid-template-columns:1.1fr .9fr;gap:14px;margin-top:18px}}
ol{{background:#fff;border:1px solid #d8d5cf;border-radius:8px;padding:14px 16px 14px 36px;margin:8px 0 0}}
li{{margin:8px 0}} li span{{display:block;color:#555;margin-top:2px;line-height:1.35}}
.final{{font-size:24px;font-weight:900;margin:18px 0 0}}
@media(max-width:1500px){{.grid{{grid-template-columns:repeat(3,minmax(0,1fr))}}}}
@media(max-width:1050px){{header{{flex-direction:column}}.grid,.split{{grid-template-columns:1fr}}.badge{{white-space:normal}}}}
</style>
<header><div><h1>Agent Bounty Market</h1><p>A project receives a budget, buys a verified improvement from a specialized agent, settles exactly once, and lets retained operating credit fund the next useful bounty.</p></div><div class="badge">{html.escape(str(badge))} · {status}</div></header>
<main><section class="grid">{card_html}</section><section class="split"><div><h2>Fallbacks and blockers</h2><ol>{warning_html}</ol></div><div><h2>Recording cues</h2><ol>{cue_html}</ol></div></section><h2>Timeline</h2><ol>{timeline_html}</ol><p class="final">Verified software work became operating capital.</p></main>
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


def _expected_badge(bundle: dict[str, Any]) -> str:
    mode = bundle.get("mode")
    if mode == "mixed":
        return "Mixed real/fallback"
    if bundle.get("fake_provider"):
        return "Local simulation"
    return "Recorded real run"


def _validate_attestation(bundle_dir: Path, manifest: dict[str, Any], bundle: dict[str, Any]) -> list[str]:
    mismatches: list[str] = []
    path = bundle_dir / "attestation.json"
    if "attestation.json" not in manifest.get("files", {}):
        mismatches.append("manifest missing attestation.json")
        return mismatches
    if not path.exists():
        return ["missing attestation.json"]
    try:
        attestation = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return ["attestation.json is not valid JSON"]
    if attestation.get("schema") != ATTESTATION_SCHEMA:
        mismatches.append("attestation schema mismatch")
    if attestation.get("bundle_content_digest") != bundle.get("bundle_content_digest"):
        mismatches.append("attestation bundle digest mismatch")
    expected = attestation.get("attestation_digest")
    recalculated_payload = dict(attestation)
    recalculated_payload["attestation_digest"] = None
    recalculated = sha256_text(stable_json(recalculated_payload))
    if expected != recalculated:
        mismatches.append("attestation digest mismatch")
    return mismatches


def _validate_truth_matrix(bundle: dict[str, Any]) -> list[str]:
    mismatches: list[str] = []
    matrix = bundle.get("truth_matrix")
    if bundle.get("mode") != "mixed":
        return mismatches
    if not isinstance(matrix, dict) or matrix.get("schema") != TRUTH_MATRIX_SCHEMA:
        return ["mixed bundle missing truth matrix"]
    rows = matrix.get("rows")
    if not isinstance(rows, list) or not rows:
        return ["truth matrix has no rows"]
    if matrix.get("all_required_real") and any(row.get("status") in {"fallback", "blocked"} for row in rows):
        mismatches.append("truth matrix claims all real while fallback/blocker rows exist")
    for row in rows:
        status = row.get("status")
        if status not in {"real", "recorded-real", "fallback", "blocked"}:
            mismatches.append(f"truth matrix row {row.get('component_id')} has invalid status")
        if status in {"real", "recorded-real"} and row.get("blocker"):
            mismatches.append(f"real row {row.get('component_id')} has blocker")
        evidence_text = stable_json(row.get("safe_evidence", {}))
        if status in {"real", "recorded-real"} and any(marker in evidence_text for marker in ("fake_", "tr_test_", "pi_test_", "cs_test_", "ch_test_")):
            mismatches.append(f"real row {row.get('component_id')} contains fake/test evidence id")
    return mismatches


def _validate_consistency(bundle: dict[str, Any]) -> list[str]:
    mismatches: list[str] = []
    consistency = bundle.get("consistency") or {}
    allocation = (bundle.get("demo_result") or {}).get("allocation") or {}
    if allocation:
        if consistency.get("currency") != allocation.get("currency"):
            mismatches.append("consistency currency does not match allocation")
        if consistency.get("accepted_receipt_id") != allocation.get("accepted_receipt_id"):
            mismatches.append("consistency receipt does not match allocation")
    return mismatches


def _validate_dashboard(path: Path) -> list[str]:
    if not path.exists():
        return ["dashboard.html missing"]
    text = path.read_text(encoding="utf-8")
    return [f"dashboard missing required text: {item}" for item in REQUIRED_DASHBOARD_TEXT if item not in text]


def _validate_recording_timeline(path: Path) -> list[str]:
    if not path.exists():
        return ["recording-timeline.md missing"]
    text = path.read_text(encoding="utf-8")
    required = ["# Recording Timeline", "Mode badge:", "Truth:", "00:00", "00:15", "00:35", "00:55", "01:20", "01:45", "02:05"]
    return [f"recording timeline missing required text: {item}" for item in required if item not in text]


def _secret_scan_bundle(bundle_dir: Path) -> list[str]:
    mismatches: list[str] = []
    bundle_root = bundle_dir.resolve()
    for path in sorted(bundle_dir.rglob("*")):
        if not _is_safe_bundle_scan_path(bundle_root, path, mismatches):
            continue
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for pattern in SECRET_PATTERNS:
            if pattern in text:
                mismatches.append(f"secret-like pattern {pattern} found in {path.relative_to(bundle_dir)}")
    return mismatches


def _private_path_scan_bundle(bundle_dir: Path) -> list[str]:
    mismatches: list[str] = []
    bundle_root = bundle_dir.resolve()
    for path in sorted(bundle_dir.rglob("*")):
        if not _is_safe_bundle_scan_path(bundle_root, path, mismatches):
            continue
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for marker in PRIVATE_PATH_MARKERS:
            if marker in text:
                mismatches.append(f"private path marker {marker} found in {path.relative_to(bundle_dir)}")
    return mismatches


def _safe_bundle_child(bundle_root: Path, relative: Any) -> tuple[Path, str | None]:
    raw = str(relative)
    rel = Path(raw)
    if rel.is_absolute() or ".." in rel.parts:
        return bundle_root / "__forbidden__", f"manifest path escapes bundle: {raw}"
    resolved = (bundle_root / rel).resolve()
    if resolved != bundle_root and bundle_root not in resolved.parents:
        return resolved, f"manifest path escapes bundle: {raw}"
    return resolved, None


def _is_safe_bundle_scan_path(bundle_root: Path, path: Path, mismatches: list[str]) -> bool:
    try:
        resolved = path.resolve()
        display = path.relative_to(bundle_root)
    except ValueError:
        display = path.name
        resolved = path.resolve()
    if resolved != bundle_root and bundle_root not in resolved.parents:
        mismatches.append(f"bundle path escapes via symlink: {display}")
        return False
    return True


def _money(amount: Any, currency: Any) -> str:
    if amount is None:
        return "unknown"
    return f"{amount} {currency or ''}".strip()


def _short(value: Any, *, keep: int = 18) -> str:
    text = str(value or "n/a")
    if len(text) <= keep + 3:
        return text
    return text[:keep] + "..."


def _row_status(row: dict[str, Any] | None) -> str:
    if not row:
        return "not recorded"
    return str(row.get("status"))


def _evidence_hint(row: dict[str, Any] | None) -> str:
    if not row:
        return "n/a"
    evidence = row.get("safe_evidence") or {}
    if isinstance(evidence, dict):
        for key in ("repository", "transfer", "payment_intent", "path"):
            if evidence.get(key):
                return _short(evidence.get(key))
    return _short(row.get("safe_evidence_digest"))


def _p95(values: list[int]) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, ((95 * len(ordered) + 99) // 100) - 1))
    return ordered[index]


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
    bundle_root = (root / "demo" / "bundles").resolve()
    allowed = resolved == demo_root or demo_root in resolved.parents or resolved == bundle_root or bundle_root in resolved.parents
    if not allowed:
        raise DemoPresentationError(f"refusing to delete outside demo state: {path}")
    if not resolved.exists():
        return
    if resolved.is_dir():
        shutil.rmtree(resolved)
    else:
        resolved.unlink()
