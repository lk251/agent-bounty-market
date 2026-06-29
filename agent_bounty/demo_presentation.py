from __future__ import annotations

import html
import json
import re
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
from .project_agent import DEFAULT_BASE_COMMIT, DEFAULT_FINAL_COMMIT, project_agent_status_report
from .solver_agent import solver_agent_status_report
from .stripe_sandbox import stripe_cli_version, stripe_package_version
from .util import file_digest, sha256_text, stable_json, utc_now
from .verification import ProtectedVerifierRunner, receipt_payload


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
MOTOKO_VERIFICATION_FRAGMENT_SCHEMA = "motoko-verification-fragment-v1"
ISSUE21_DOGFOOD_EVIDENCE_SCHEMA = "agent-bounty-issue21-dogfood-evidence-v1"
DEFAULT_INTERMEDIATE_COMMIT = "fdf54095b5cb8aca81984993bcd38176ccadad32"
MOTOKO_ORIGINAL_CASE = "original-buggy-version"
MOTOKO_SUPERFICIAL_CASE = "superficial-typing-fix"
MOTOKO_FINAL_CASE = "final-background-study-fix"
MOTOKO_ISSUE_URL = "https://github.com/lk251/motoko/issues/1"
ISSUE21_DOGFOOD_URL = "https://github.com/lk251/agent-bounty-market/issues/21"
ISSUE21_DOGFOOD_CANDIDATE = "5ffb2835fec5d5fd9373b129f850aa52396bbd4a"
ISSUE21_DOGFOOD_RECEIPT = "receipt_ecc99fd087984590ae9313933d17fa48"
ISSUE21_DOGFOOD_VERIFIER_DIGEST = "sha256:3429d7b5a728ba3f61db2ee0a2588d292ff5fdac361dae1570188be59e250170"
ISSUE21_DOGFOOD_SOURCE_DIGEST = "sha256:45c3ac46faca4a49a4f9dfcfc25a96f5894b0ce24a93a38eba6545d38f1aeba8"

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
    "MARES ENGINEERING",
    "Project spends",
    "Agents choose",
    "Motoko verifier proof",
    "GitHub work",
    "Trust",
    "Solver wallet split",
    "Issue #21 dogfood",
    "Fallbacks and blockers",
    "Recording cues",
    "data engine for better agent orchestration",
)
RECORDING_STAGES = (
    ("00:00", "Problem", "Open-source projects need a native market where project agents can buy verified fixes and specialist agents can earn from them."),
    ("00:15", "Project spends", "The project agent uses its budget to fund a $25 Motoko bounty because the task has a protected verifier."),
    ("00:35", "Agents choose", "Frontend and CUDA specialists decline; the Python terminal/TUI specialist claims the task because it matches history and margin."),
    ("00:55", "Verification", "The verifier rejects the original bug and superficial typing fix, then accepts only the final background-study fix."),
    ("01:20", "Settlement", "The solver earns $25; its wallet keeps $20 as operating credit and sends $5 through the Stripe settlement path to the operator account."),
    ("01:40", "Flywheel", "Every claim, decline, patch, verifier result, payout, and spend becomes high-quality training data for future orchestrators."),
    ("02:05", "Close", "Agent Bounty Market is a verified agent labor market and a data engine for better agent orchestration."),
)
MARES_WORDMARK = "MARES ENGINEERING"
MARES_DISPLAY_FONT_FACE = """
@font-face {
  font-family: 'Mares Display';
  src: url('https://mares-engineering.com/assets/fonts/eurostile-extended-black.woff2') format('woff2');
  font-style: normal;
  font-weight: 900;
  font-display: swap;
}
"""
MARES_THEME_CSS = """
:root {
  --mares-bg: #050607;
  --mares-fg: #efefef;
  --mares-muted: #b4b4b4;
  --mares-line: rgba(151,208,236,.24);
  --mares-panel: rgba(12,18,25,.78);
  --mares-panel-strong: rgba(18,28,40,.9);
  --mares-blue: #88b0c5;
  --mares-blue-strong: #5f86a5;
  --mares-blue-light: #beddea;
  --mares-white: #f8fbff;
  --mares-display: 'Mares Display', 'Eurostile Extended Black', 'Eurostyle Extended Black', 'Arial Black', 'Trebuchet MS', 'Franklin Gothic Demi Cond', sans-serif;
  --mares-body: Baskerville, 'Baskerville Old Face', 'Times New Roman', serif;
}
* { box-sizing: border-box; }
html {
  background: var(--mares-bg);
}
body {
  background:
    radial-gradient(ellipse 92% 32% at 50% 53%, rgba(20,48,72,.12), rgba(12,30,48,.05) 45%, rgba(5,6,7,0) 78%),
    radial-gradient(ellipse 130% 92% at 50% 48%, #18191a 0%, #101112 46%, var(--mares-bg) 100%);
  color: var(--mares-fg);
  font-family: var(--mares-body);
  letter-spacing: 0;
}
.mares-wordmark {
  margin: 0;
  font-family: var(--mares-display);
  font-weight: 900;
  font-stretch: expanded;
  letter-spacing: 0;
  line-height: 1;
  text-transform: uppercase;
  color: transparent;
  background: linear-gradient(180deg, #beddea 0%, #a9cada 26%, #88b0c5 58%, #5f86a5 100%);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
  -webkit-text-stroke: .045em rgba(151,208,236,.32);
  filter:
    drop-shadow(0 0 .012em rgba(194,230,247,.22))
    drop-shadow(0 0 .08em rgba(105,178,226,.16))
    drop-shadow(0 0 .22em rgba(45,112,174,.12));
  text-shadow:
    0 .006em 0 rgba(24,55,82,.22),
    0 0 .035em rgba(110,184,226,.14);
}
.brand-kicker {
  margin-top: 6px;
  font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif;
  color: rgba(239,239,239,.78);
  font-size: 13px;
  line-height: 1.2;
  letter-spacing: 0;
}
.truth-badge {
  display: inline-flex;
  align-items: center;
  gap: 9px;
  border: 1px solid rgba(190,221,234,.54);
  color: var(--mares-white);
  background: rgba(8,18,28,.72);
  border-radius: 999px;
  padding: 9px 14px;
  font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif;
  font-size: 13px;
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: 0;
  box-shadow: 0 0 24px rgba(96,151,185,.14), inset 0 1px 0 rgba(255,255,255,.08);
  white-space: nowrap;
}
.truth-badge::before {
  content: "";
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: var(--mares-blue-light);
  box-shadow: 0 0 14px rgba(190,221,234,.72);
}
"""


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
    motoko_verification = build_motoko_verification_fragment(motoko_repo=motoko_repo, demo_result=demo)
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
        motoko_verification=motoko_verification,
        issue21_dogfood=build_issue21_dogfood_evidence(),
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
    motoko_verification: dict[str, Any] | None = None,
    issue21_dogfood: dict[str, Any] | None = None,
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
        "evidence": build_evidence_payloads(
            truth_matrix=truth_matrix,
            demo_result=demo_result,
            snapshot=snapshot,
            motoko_verification=motoko_verification,
            issue21_dogfood=issue21_dogfood,
        ),
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
        ("https://github.test/", "fake-github://"),
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


def build_evidence_payloads(
    *,
    truth_matrix: dict[str, Any] | None,
    demo_result: dict[str, Any],
    snapshot: dict[str, list[dict[str, Any]]],
    motoko_verification: dict[str, Any] | None = None,
    issue21_dogfood: dict[str, Any] | None = None,
) -> dict[str, Any]:
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
    if motoko_verification:
        evidence["motoko-verification-fragment"] = motoko_verification
    if issue21_dogfood:
        evidence["issue-21-dogfood"] = issue21_dogfood
    return evidence


def build_motoko_verification_fragment(*, motoko_repo: Path, demo_result: dict[str, Any]) -> dict[str, Any]:
    cases = [
        _motoko_verification_case(MOTOKO_ORIGINAL_CASE, motoko_repo=motoko_repo, candidate_commit=DEFAULT_BASE_COMMIT),
        _motoko_verification_case(MOTOKO_SUPERFICIAL_CASE, motoko_repo=motoko_repo, candidate_commit=DEFAULT_INTERMEDIATE_COMMIT),
        _motoko_verification_case(MOTOKO_FINAL_CASE, motoko_repo=motoko_repo, candidate_commit=DEFAULT_FINAL_COMMIT),
    ]
    final_case = cases[-1]
    receipt_id = (demo_result.get("first_bounty") or {}).get("receipt_id")
    metrics_digest = sha256_text(stable_json(final_case.get("metrics", {})))
    safe_evidence = {
        "candidate_sha": DEFAULT_FINAL_COMMIT,
        "receipt_id": receipt_id,
        "verifier_digest": final_case.get("verifier_digest"),
        "backend_digest": final_case.get("backend_digest"),
        "metrics_digest": metrics_digest,
        "motoko_issue_url": MOTOKO_ISSUE_URL,
        "cases": cases,
        "final_payment_replay": bool((demo_result.get("allocation_replay") or {}).get("replayed")),
        "settlement_replay_safe": bool((demo_result.get("allocation_replay") or {}).get("replayed")),
    }
    return {
        "schema": MOTOKO_VERIFICATION_FRAGMENT_SCHEMA,
        "component_id": "motoko_verification_receipt",
        "label": "Motoko issue #1 verifier proof",
        "truth_status": "recorded-real",
        "source_issue": MOTOKO_ISSUE_URL,
        "source_commit": DEFAULT_FINAL_COMMIT,
        "source_command": "python -m agent_bounty demo-motoko-suite --motoko-repo /home/mares/repos/motoko-issue-1-tui-input-latency",
        "captured_at": utc_now(),
        "source_digest": sha256_text(stable_json(cases)),
        "safe_evidence": safe_evidence,
        "evidence_digest": sha256_text(stable_json(safe_evidence)),
        "consistency": {
            "project": "lk251/motoko",
            "candidate_sha": DEFAULT_FINAL_COMMIT,
            "currency": "USD",
            "reward_amount": 2500,
            "receipt_id": receipt_id,
        },
        "blocker": None,
    }


def _motoko_verification_case(name: str, *, motoko_repo: Path, candidate_commit: str) -> dict[str, Any]:
    result = ProtectedVerifierRunner(timeout_seconds=60.0).run(
        bounty_id=f"bounty_motoko_issue_1_{name}",
        motoko_repo=motoko_repo,
        base_commit=DEFAULT_BASE_COMMIT,
        candidate_commit=candidate_commit,
    )
    receipt = receipt_payload(
        bounty_id=f"bounty_motoko_issue_1_{name}",
        project_id="project_motoko",
        issue_ref="lk251/motoko#1",
        submission_id=f"submission_probe_{name}",
        solver_id="solver_codex_motoko_issue_1",
        candidate_repo_path=str(motoko_repo),
        verifier_id="motoko_issue_1_tui_latency_v2",
        base_commit=DEFAULT_BASE_COMMIT,
        candidate_commit=candidate_commit,
        result=result,
    )
    metrics = result.metrics.get("background_study", {}) if isinstance(result.metrics, dict) else {}
    return {
        "case": name,
        "candidate_sha": candidate_commit,
        "accepted": bool(result.accepted),
        "verdict": "accepted" if result.accepted else "rejected",
        "failure_reasons": receipt.get("failure_reasons", []),
        "verifier_digest": result.verifier_digest,
        "backend_digest": result.backend_digest,
        "policy_digest": result.policy_digest,
        "result_digest": receipt.get("result_digest"),
        "metrics": {
            "phase": metrics.get("phase"),
            "p95_ms": metrics.get("p95_ms"),
            "max_ms": metrics.get("max_ms"),
            "samples": metrics.get("samples"),
            "input_integrity": metrics.get("input_integrity"),
            "artifact_integrity": metrics.get("artifact_integrity"),
            "background_completed": metrics.get("background_completed"),
            "visible_before_phase_end": metrics.get("visible_before_phase_end"),
        },
    }


def build_issue21_dogfood_evidence() -> dict[str, Any]:
    safe_evidence = {
        "issue_url": ISSUE21_DOGFOOD_URL,
        "candidate_sha": ISSUE21_DOGFOOD_CANDIDATE,
        "receipt_id": ISSUE21_DOGFOOD_RECEIPT,
        "verifier_id": "release_provenance_v2",
        "verifier_digest": ISSUE21_DOGFOOD_VERIFIER_DIGEST,
        "recorded_evidence_digest": ISSUE21_DOGFOOD_SOURCE_DIGEST,
        "retained_credit_spend_replay": True,
        "second_settlement_replay": True,
        "truth": "deterministic retained-credit dogfood of release provenance; fake provider IDs are not Stripe or GitHub live transport",
    }
    return {
        "schema": ISSUE21_DOGFOOD_EVIDENCE_SCHEMA,
        "label": "Issue #21 retained-credit dogfood proof",
        "source_issue": ISSUE21_DOGFOOD_URL,
        "source_commit": ISSUE21_DOGFOOD_CANDIDATE,
        "source_command": "python -m agent_bounty release-dogfood-issue --candidate-repo .",
        "captured_at": utc_now(),
        "source_digest": ISSUE21_DOGFOOD_SOURCE_DIGEST,
        "safe_evidence": safe_evidence,
        "evidence_digest": sha256_text(stable_json(safe_evidence)),
    }


def build_timeline(snapshot: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for row in snapshot.get("funding_events", []):
        events.append({"at": row.get("created_at"), "kind": "funding", "label": "Project treasury funded", "detail": f"{_money(row.get('amount'), row.get('currency'))} via fake funding event"})
    for row in snapshot.get("project_agent_decisions", []):
        verdict = _human_verdict(row.get("trusted_verdict"))
        label = "Project agent funded verifier-backed bounty" if verdict == "approved" else "Project policy left candidate unfunded"
        events.append({"at": row.get("created_at"), "kind": "project-agent", "label": label, "detail": _human_reasons(row.get("policy_reasons_json"))})
    for row in snapshot.get("github_issue_contracts", []):
        events.append({"at": row.get("created_at"), "kind": "github", "label": "GitHub bounty contract published", "detail": row.get("contract_digest")})
    for row in snapshot.get("solver_agent_evaluations", []):
        events.append({"at": row.get("created_at"), "kind": "solver-agent", "label": f"Solver {_human_verdict(row.get('trusted_verdict'))}", "detail": _human_reasons(row.get("policy_reasons_json"))})
    for row in snapshot.get("verification_receipts", []):
        verdict = "accepted" if int(row.get("accepted", 0)) else "rejected"
        events.append({"at": row.get("created_at"), "kind": "verification", "label": f"Verifier {verdict}", "detail": row.get("id")})
    for row in snapshot.get("settlement_allocations", []):
        events.append({"at": row.get("created_at"), "kind": "settlement", "label": "Solver wallet split recorded", "detail": f"operating credit {_money(row.get('retained_operating_amount'), row.get('currency'))}; operator payout {_money(row.get('external_transfer_amount'), row.get('currency'))}"})
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
    evidence = bundle.get("evidence") or {}
    motoko_verification = evidence.get("motoko-verification-fragment") or {}
    dogfood = evidence.get("issue-21-dogfood") or {}
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
            "Open-source projects need a native market for verified software work.",
            badge,
            durations[0],
            [
                ("Bounty", primary_bounty.get("title") or "unavailable in bundle"),
                ("Issue", primary_bounty.get("issue_ref") or "unavailable"),
                ("Reward", _money(primary_bounty.get("reward_amount"), primary_bounty.get("currency"))),
                ("Before p95", _motoko_case_latency(motoko_verification, MOTOKO_ORIGINAL_CASE)),
                ("After p95", _motoko_case_latency(motoko_verification, MOTOKO_FINAL_CASE)),
            ],
            [
                "Open-source projects have endless useful work, but no native market where project agents can buy verified fixes.",
                "Specialist solver agents need a way to earn from evidence-backed work, not persuasion.",
            ],
            "Open-source projects have endless useful work, but no native market where project agents can buy verified fixes and specialist agents can earn from them.",
        ),
        _director_scene(
            "project-spends",
            "Project spends",
            "The project agent funds the measurable issue with a verifier; vague or unaffordable work is left unfunded.",
            badge,
            durations[1],
            [
                ("Project", summary.get("project")),
                ("Reward", _money(summary.get("reward"), summary.get("currency"))),
                ("Contract digest", _short(summary.get("contract_digest"))),
                ("Project decisions", f"{len(project_decisions)} recorded"),
            ],
            _decision_bullets(project_decisions, "project"),
            "My Motoko project has a real bug: typing froze while background evidence-store work was running. The project agent uses its budget to fund a $25 bounty, but only because the task has a protected verifier.",
        ),
        _director_scene(
            "agents-choose",
            "Agents choose",
            "Specialized solver profiles can decline or claim based on capability and margin.",
            badge,
            durations[2],
            [
                ("Solver decisions", f"{len(solver_evals)} recorded"),
                ("Claimed solver", _solver_display(allocation.get("solver_id"))),
                ("Candidate SHA", _short(summary.get("candidate_sha"))),
            ],
            _decision_bullets(solver_evals, "solver"),
            "Specialist agents inspect the bounty. The frontend and CUDA agents decline because it is outside their verified skill set. The Python terminal/TUI specialist claims it because the task matches its history and margin.",
        ),
        _director_scene(
            "verification",
            "Verification",
            "Evidence, not persuasion, decides whether payment can happen.",
            badge,
            durations[3],
            [
                ("Candidate", _short(summary.get("candidate_sha"))),
                ("Receipt", _short(summary.get("receipt_id"))),
                ("Verifier receipts", f"{len(receipts)} recorded"),
            ],
            _motoko_verification_bullets(motoko_verification, summary),
            "The project does not trust the solver's claim. Its verifier tests the original buggy version, a superficial typing fix, and the final background-study fix. Only the real fix passes.",
        ),
        _director_scene(
            "settlement",
            "Settlement",
            "The solver-side wallet decides how accepted reward becomes operating credit and operator payout.",
            badge,
            durations[4],
            [
                ("Reward", _money(allocation.get("reward_amount"), allocation.get("currency"))),
                ("Operating credit", _money(allocation.get("retained_operating_amount"), allocation.get("currency"))),
                ("Operator payout", _money(allocation.get("external_transfer_amount"), allocation.get("currency"))),
            ],
            [
                _settlement_mode_line(allocation.get("transfer_provider")),
                f"Transfer truth: {((allocation.get('split') or {}).get('truth') or 'unavailable')}",
                "Deterministic fallback split uses a Stripe-compatible settlement envelope; prior real Stripe sandbox evidence is preserved separately.",
                f"Ledger entries: {summary.get('ledger_entries')}",
            ],
            "The solver earns the $25 bounty. Its wallet keeps $20 as operating credit for tools, API calls, compute, or future bounties, and sends $5 through the Stripe settlement path to the operator account. The split is recorded exactly once.",
        ),
        _director_scene(
            "flywheel",
            "Flywheel",
            "Paid and rejected market outcomes become training data for better orchestrators.",
            badge,
            durations[5],
            [
                ("Operating credit", _money(summary.get("retained_operating_credit"), summary.get("currency"))),
                ("Follow-up bounty", followup_bounty.get("title") or summary.get("second_bounty")),
                ("Follow-up state", followup_bounty.get("state") or "unavailable"),
                ("Dogfood issue", _short((dogfood.get("safe_evidence") or {}).get("issue_url"), keep=80)),
            ],
            [
                "Every claim, decline, patch, verifier result, payout, and spend becomes a labeled trajectory.",
                "Economic outcomes filter the data: paid accepted work is high-signal, rejected work is negative signal.",
                f"Second bounty id: {_short(summary.get('second_bounty'))}",
                f"Issue #21 candidate: {_short((dogfood.get('safe_evidence') or {}).get('candidate_sha'))}",
                f"Issue #21 receipt: {_short((dogfood.get('safe_evidence') or {}).get('receipt_id'))}",
                f"Retained-credit replay: {_yes_no((dogfood.get('safe_evidence') or {}).get('retained_credit_spend_replay'))}; settlement replay: {_yes_no((dogfood.get('safe_evidence') or {}).get('second_settlement_replay'))}",
            ],
            "That operating credit funds the next useful issue. The market also produces high-quality training data for future orchestrators that learn which specialist agents to call.",
        ),
        _director_scene(
            "close",
            "Close",
            "A verified agent labor market and a data engine for better agent orchestration.",
            badge,
            durations[6],
            [
                ("Truth overall", truth.get("overall_status") or bundle.get("truth_mode")),
                ("Real rows", _truth_count(rows, "real")),
                ("Fallback/blocked rows", _truth_count(rows, "fallback") + _truth_count(rows, "blocked")),
            ],
            _truth_bullets(rows),
            "Agent Bounty Market turns open-source maintenance into a verified agent labor market and a data engine for better agent orchestration.",
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
        verdict = _human_verdict(row.get("trusted_verdict") or row.get("decision") or "recorded")
        reasons = _human_reasons(row.get("policy_reasons_json") or row.get("reasons_json") or "")
        if kind == "project":
            prefix = "Funded" if verdict == "approved" else "Not funded"
            reasons = _project_decision_display_reason(reasons, funded=verdict == "approved")
        else:
            prefix = verdict[:1].upper() + verdict[1:]
        bullets.append(f"{prefix}: {_short(reasons, keep=120)}")
    if len(rows) > 5:
        bullets.append(f"{len(rows) - 5} more {kind} decisions recorded.")
    return bullets


def _truth_count(rows: list[dict[str, Any]], status: str) -> int:
    return sum(1 for row in rows if row.get("status") == status)


def _truth_bullets(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return ["Truth matrix unavailable in bundle."]
    real_count = _truth_count(rows, "real")
    recorded_count = _truth_count(rows, "recorded-real")
    fallback_count = _truth_count(rows, "fallback")
    blocked_count = _truth_count(rows, "blocked")
    blocked_labels = ", ".join(str(row.get("label")) for row in rows if row.get("status") == "blocked") or "none"
    fallback_labels = ", ".join(str(row.get("label")) for row in rows if row.get("status") == "fallback") or "none"
    return [
        f"Real or recorded-real evidence rows: {real_count + recorded_count}.",
        f"Fallback rows: {fallback_count} ({fallback_labels}).",
        f"Blocked live paths: {blocked_count} ({_short(blocked_labels, keep=130)}).",
        "Prior Stripe full-transfer evidence stays separate from the deterministic split-settlement fallback.",
        "The market is also a data engine: paid, verified fixes become supervised trajectories for training the next orchestrator.",
    ]


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
{MARES_DISPLAY_FONT_FACE}
{MARES_THEME_CSS}
html,body{{margin:0;min-height:100%;}}
body{{overflow:hidden}}
.shell{{width:100vw;height:100vh;display:flex;flex-direction:column;background:linear-gradient(180deg,rgba(255,255,255,.02),rgba(255,255,255,0));}}
.top{{height:94px;display:grid;grid-template-columns:minmax(260px,1fr) auto auto;align-items:center;gap:24px;padding:18px 34px;background:rgba(5,6,7,.78);border-bottom:1px solid var(--mares-line);box-shadow:0 20px 60px rgba(0,0,0,.28)}}
.brand-lockup{{min-width:0}}
.brand-lockup .mares-wordmark{{font-size:29px;white-space:nowrap}}
.timer{{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-variant-numeric:tabular-nums;color:rgba(239,239,239,.82);font-size:16px}}
.stage{{display:none;flex:1;padding:42px 58px 38px;gap:32px;grid-template-columns:minmax(0,1.12fr) minmax(360px,.88fr);align-items:stretch}}
.stage.active{{display:grid}}
h1{{font-family:var(--mares-display);font-size:68px;line-height:.96;margin:0 0 18px;letter-spacing:0;text-transform:uppercase;color:var(--mares-white);text-shadow:0 0 28px rgba(106,169,210,.18)}}
.subtitle{{font-size:30px;line-height:1.18;color:rgba(239,239,239,.82);max-width:980px;margin-bottom:32px}}
.bullets{{list-style:none;padding:0;margin:0;display:grid;gap:14px}}
.bullets li{{font-size:24px;line-height:1.28;background:rgba(12,18,25,.72);border:1px solid rgba(151,208,236,.16);border-left:6px solid var(--mares-blue);padding:16px 18px;border-radius:8px;box-shadow:0 18px 48px rgba(0,0,0,.22)}}
.panel{{background:var(--mares-panel);border:1px solid var(--mares-line);border-radius:8px;padding:24px;display:flex;flex-direction:column;gap:20px;min-width:0;box-shadow:0 24px 70px rgba(0,0,0,.28), inset 0 1px 0 rgba(255,255,255,.05)}}
.stats{{display:grid;gap:12px}}
.stat{{border:1px solid rgba(151,208,236,.18);border-radius:8px;padding:14px;background:rgba(5,10,16,.72)}}
.stat b{{display:block;color:var(--mares-blue-light);font-family:ui-sans-serif,system-ui,-apple-system,Segoe UI,sans-serif;font-size:13px;text-transform:uppercase;margin-bottom:6px;letter-spacing:0}}
.stat span{{display:block;font-size:22px;line-height:1.18;overflow-wrap:anywhere}}
.notes{{margin-top:auto;border-top:1px solid rgba(151,208,236,.18);padding-top:16px;color:rgba(239,239,239,.88);font-size:18px;line-height:1.35}}
.notes strong{{color:var(--mares-blue-light)}}
.controls{{height:52px;display:flex;align-items:center;gap:18px;padding:0 32px;background:rgba(5,6,7,.82);border-top:1px solid var(--mares-line);color:rgba(239,239,239,.72);font-family:ui-sans-serif,system-ui,-apple-system,Segoe UI,sans-serif;font-size:15px}}
.progress{{height:8px;background:rgba(151,208,236,.12)}}
.bar{{height:100%;width:0;background:linear-gradient(90deg,var(--mares-blue-strong),var(--mares-blue-light));box-shadow:0 0 20px rgba(151,208,236,.38);transition:width .2s linear}}
a{{color:var(--mares-blue-light)}}
@media(max-width:1100px){{.top{{grid-template-columns:1fr;gap:10px;height:auto;align-items:start}}.truth-badge{{white-space:normal}}.stage{{grid-template-columns:1fr;padding:28px 22px}}h1{{font-size:44px}}.subtitle{{font-size:23px}}}}
@media (prefers-reduced-motion: reduce){{.bar{{transition:none}}}}
</style>
<script type="application/json" id="director-data">{data_json}</script>
<div class="shell">
  <div class="top"><div class="brand-lockup"><div class="mares-wordmark">{MARES_WORDMARK}</div><div class="brand-kicker">Agent Bounty Market demo</div></div><div class="truth-badge">{html.escape(str(data["mode_badge"]))}</div><div class="timer" id="timer">00:00 / {int(data["duration_seconds"]):02d}s</div></div>
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
  <aside class="panel"><div class="truth-badge">{html.escape(scene['truth_badge'])}</div><div class="stats">{stats}</div>{notes}</aside>
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
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
{MARES_DISPLAY_FONT_FACE}
{MARES_THEME_CSS}
html,body{{margin:0;min-height:100%}}
body{{padding:34px;line-height:1.45}}
.notes-shell{{max-width:1060px;margin:0 auto}}
header{{display:flex;align-items:flex-start;justify-content:space-between;gap:28px;margin-bottom:30px;border-bottom:1px solid var(--mares-line);padding-bottom:22px}}
.mares-wordmark{{font-size:34px;white-space:nowrap}}
h1{{font-family:var(--mares-display);font-size:46px;line-height:1;margin:18px 0 8px;text-transform:uppercase;letter-spacing:0}}
p{{margin:0;color:rgba(239,239,239,.78);font-size:18px}}
ol{{margin:0;padding:0;list-style:none;display:grid;gap:16px}}
li{{background:var(--mares-panel);border:1px solid var(--mares-line);border-left:6px solid var(--mares-blue);border-radius:8px;padding:18px 20px;box-shadow:0 18px 48px rgba(0,0,0,.18)}}
b{{display:block;font-family:ui-sans-serif,system-ui,-apple-system,Segoe UI,sans-serif;font-size:18px;color:var(--mares-blue-light);margin-bottom:8px}}
li p{{font-size:20px;color:var(--mares-white);line-height:1.35}}
@media(max-width:760px){{body{{padding:20px}}header{{display:block}}.mares-wordmark{{font-size:24px;white-space:normal}}h1{{font-size:34px}}}}
</style>
<div class="notes-shell">
<header><div><div class="mares-wordmark">{MARES_WORDMARK}</div><div class="brand-kicker">Agent Bounty Market presenter notes</div></div><div class="truth-badge">{html.escape(str(data["mode_badge"]))}</div></header>
<h1>Presenter Notes</h1>
<p>Duration: {int(data["duration_seconds"])} seconds.</p>
<ol>{rows}</ol>
</div>
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
    mismatches.extend(_validate_required_evidence(bundle))
    mismatches.extend(_validate_dashboard(bundle_dir / "dashboard.html"))
    mismatches.extend(_validate_recording_timeline(bundle_dir / "recording-timeline.md"))
    mismatches.extend(_validate_judge_facing_assets(bundle_dir))
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
    evidence = bundle.get("evidence") or {}
    motoko_verification = evidence.get("motoko-verification-fragment") or {}
    dogfood = evidence.get("issue-21-dogfood") or {}
    badge = summary.get("mode_badge", "Unknown mode")
    status = "PASS" if summary.get("ok") else "MIXED"
    rows_by_id = {row.get("component_id"): row for row in (bundle.get("truth_matrix") or {}).get("rows", [])}
    github = rows_by_id.get("github_lifecycle", {})
    openshell = rows_by_id.get("openshell_nemoclaw", {})
    stripe_split = rows_by_id.get("stripe_split_transfer", {})
    timeline_plan = build_recording_timeline(bundle)
    cards = [
        ("Project spends", [("Repository", summary.get("project")), ("Reward", _money(summary.get("reward"), summary.get("currency"))), ("Contract", _short(summary.get("contract_digest")))]),
        ("Agents choose", [("Project agent", _row_status(rows_by_id.get("project_agent_decision"))), ("Solver agent", _row_status(rows_by_id.get("solver_agent_decision"))), ("Claimed SHA", _short(summary.get("candidate_sha")))]),
        (
            "Motoko verifier proof",
            [
                ("Original buggy version", _motoko_case_result(motoko_verification, MOTOKO_ORIGINAL_CASE)),
                ("Superficial typing fix", _motoko_case_result(motoko_verification, MOTOKO_SUPERFICIAL_CASE)),
                ("Final background-study fix", _motoko_case_result(motoko_verification, MOTOKO_FINAL_CASE)),
            ],
        ),
        ("GitHub work", [("Lifecycle", _row_status(github)), ("Issue / PR", _evidence_hint(github)), ("Contract", _short(summary.get("contract_digest")))]),
        ("Trust", [("OpenShell", _row_status(openshell)), ("Receipt", _short(summary.get("receipt_id"))), ("Ledger entries", summary.get("ledger_entries"))]),
        ("Solver wallet split", [("Operator payout", _money(summary.get("external_transfer"), summary.get("currency"))), ("Transfer", _short(summary.get("external_transfer_id"))), ("Operating credit -> next", f"{_money(summary.get('retained_operating_credit'), summary.get('currency'))} / {_short(summary.get('second_bounty'))}")]),
        (
            "Issue #21 dogfood",
            [
                ("Issue", _short((dogfood.get("safe_evidence") or {}).get("issue_url"), keep=34)),
                ("Candidate", _short((dogfood.get("safe_evidence") or {}).get("candidate_sha"))),
                ("Receipt", _short((dogfood.get("safe_evidence") or {}).get("receipt_id"))),
            ],
        ),
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
{MARES_DISPLAY_FONT_FACE}
{MARES_THEME_CSS}
html,body{{margin:0;min-height:100%}}
body{{font-size:16px}}
header{{padding:28px 36px 24px;background:rgba(5,6,7,.82);border-bottom:1px solid var(--mares-line);display:grid;grid-template-columns:minmax(260px,1fr) minmax(320px,1.2fr) auto;gap:28px;align-items:center;box-shadow:0 22px 64px rgba(0,0,0,.28)}}
.mares-wordmark{{font-size:34px;white-space:nowrap}}
h1{{font-family:var(--mares-display);font-size:42px;line-height:1;margin:0 0 10px;text-transform:uppercase;letter-spacing:0;color:var(--mares-white)}}
p{{margin:0;max-width:880px;line-height:1.42;color:rgba(239,239,239,.78);font-size:18px}}
main{{padding:24px 34px 32px;max-width:1740px;margin:0 auto}}
.grid{{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:14px}}
.card{{background:var(--mares-panel);border:1px solid var(--mares-line);border-radius:8px;padding:16px;min-height:174px;box-shadow:0 18px 48px rgba(0,0,0,.22), inset 0 1px 0 rgba(255,255,255,.04)}}
.card h2{{font-family:var(--mares-display);font-size:18px;margin:0 0 12px;line-height:1.1;text-transform:uppercase;letter-spacing:0;color:var(--mares-white)}}
.row{{border-top:1px solid rgba(151,208,236,.14);padding:9px 0}}
.key{{display:block;color:var(--mares-blue-light);font-family:ui-sans-serif,system-ui,-apple-system,Segoe UI,sans-serif;font-size:12px;text-transform:uppercase;font-weight:800;letter-spacing:0}}
.value{{font-family:ui-monospace,Menlo,Consolas,monospace;word-break:break-word;font-size:14px;line-height:1.3;color:rgba(248,251,255,.9)}}
.split{{display:grid;grid-template-columns:1.1fr .9fr;gap:16px;margin-top:20px}}
h2{{font-family:var(--mares-display);text-transform:uppercase;letter-spacing:0;color:var(--mares-white);font-size:22px;margin:0 0 10px}}
ol{{background:rgba(12,18,25,.62);border:1px solid var(--mares-line);border-radius:8px;padding:14px 16px 14px 36px;margin:8px 0 0;box-shadow:0 18px 48px rgba(0,0,0,.16)}}
li{{margin:8px 0;color:var(--mares-white)}} li span{{display:block;color:rgba(239,239,239,.72);margin-top:2px;line-height:1.35}}
.final{{font-family:var(--mares-display);font-size:27px;font-weight:900;line-height:1.12;margin:20px 0 0;text-transform:uppercase;letter-spacing:0;color:var(--mares-white);text-shadow:0 0 26px rgba(106,169,210,.16)}}
@media(max-width:1500px){{.grid{{grid-template-columns:repeat(3,minmax(0,1fr))}}header{{grid-template-columns:1fr auto}}header .pitch{{grid-column:1 / -1;grid-row:2}}}}
@media(max-width:1050px){{header{{display:block}}.brand-kicker{{margin-bottom:18px}}.grid,.split{{grid-template-columns:1fr}}.truth-badge{{white-space:normal;margin-top:18px}}.mares-wordmark{{font-size:28px;white-space:normal}}}}
</style>
<header><div><div class="mares-wordmark">{MARES_WORDMARK}</div><div class="brand-kicker">Agent Bounty Market demo</div></div><div class="pitch"><h1>Verified Agent Labor Market</h1><p>A project agent spends from a project budget to buy verified software work, a specialist solver earns the bounty, and the solver wallet split is recorded exactly once.</p></div><div class="truth-badge">{html.escape(str(badge))} · {status}</div></header>
<main><section class="grid">{card_html}</section><section class="split"><div><h2>Fallbacks and blockers</h2><ol>{warning_html}</ol></div><div><h2>Recording cues</h2><ol>{cue_html}</ol></div></section><h2>Timeline</h2><ol>{timeline_html}</ol><p class="final">Agent Bounty Market turns open-source maintenance into a verified agent labor market and a data engine for better agent orchestration.</p></main>
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


def _validate_required_evidence(bundle: dict[str, Any]) -> list[str]:
    if bundle.get("mode") != "mixed":
        return []
    mismatches: list[str] = []
    evidence = bundle.get("evidence")
    if not isinstance(evidence, dict):
        return ["mixed bundle missing evidence map"]
    motoko = evidence.get("motoko-verification-fragment")
    if not isinstance(motoko, dict) or motoko.get("schema") != MOTOKO_VERIFICATION_FRAGMENT_SCHEMA:
        mismatches.append("mixed bundle missing motoko-verification-fragment evidence")
    else:
        safe = motoko.get("safe_evidence") if isinstance(motoko.get("safe_evidence"), dict) else {}
        cases = safe.get("cases")
        if not isinstance(cases, list):
            mismatches.append("motoko verification evidence missing case list")
        else:
            by_case = {case.get("case"): case for case in cases if isinstance(case, dict)}
            if by_case.get(MOTOKO_ORIGINAL_CASE, {}).get("accepted") is not False:
                mismatches.append("motoko original buggy version case must be rejected")
            if by_case.get(MOTOKO_SUPERFICIAL_CASE, {}).get("accepted") is not False:
                mismatches.append("motoko superficial typing fix case must be rejected")
            if by_case.get(MOTOKO_FINAL_CASE, {}).get("accepted") is not True:
                mismatches.append("motoko final background-study fix case must be accepted")
        if safe.get("candidate_sha") != DEFAULT_FINAL_COMMIT:
            mismatches.append("motoko verification evidence candidate mismatch")
        if not str(safe.get("receipt_id") or "").startswith("receipt_"):
            mismatches.append("motoko verification evidence missing accepted receipt id")
        if motoko.get("evidence_digest") != sha256_text(stable_json(safe)):
            mismatches.append("motoko verification evidence digest mismatch")
    dogfood = evidence.get("issue-21-dogfood")
    if not isinstance(dogfood, dict) or dogfood.get("schema") != ISSUE21_DOGFOOD_EVIDENCE_SCHEMA:
        mismatches.append("mixed bundle missing issue-21-dogfood evidence")
    else:
        safe = dogfood.get("safe_evidence") if isinstance(dogfood.get("safe_evidence"), dict) else {}
        required = {
            "issue_url": ISSUE21_DOGFOOD_URL,
            "candidate_sha": ISSUE21_DOGFOOD_CANDIDATE,
            "receipt_id": ISSUE21_DOGFOOD_RECEIPT,
            "verifier_digest": ISSUE21_DOGFOOD_VERIFIER_DIGEST,
            "recorded_evidence_digest": ISSUE21_DOGFOOD_SOURCE_DIGEST,
        }
        for field, expected in required.items():
            if safe.get(field) != expected:
                mismatches.append(f"issue #21 dogfood evidence {field} mismatch")
        if safe.get("retained_credit_spend_replay") is not True:
            mismatches.append("issue #21 dogfood retained-credit replay evidence missing")
        if safe.get("second_settlement_replay") is not True:
            mismatches.append("issue #21 dogfood settlement replay evidence missing")
        if dogfood.get("evidence_digest") != sha256_text(stable_json(safe)):
            mismatches.append("issue #21 dogfood evidence digest mismatch")
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
    required = ["# Recording Timeline", "Mode badge:", "Truth:", "00:00", "00:15", "00:35", "00:55", "01:20", "01:40", "02:05"]
    return [f"recording timeline missing required text: {item}" for item in required if item not in text]


def _validate_judge_facing_assets(bundle_dir: Path) -> list[str]:
    mismatches: list[str] = []
    raw_currency = ("2500 USD", "2000 USD", "500 USD")
    raw_labels = ("agent_declined", "policy_reasons_json", '["agent declined candidate"]', '["solver declined"]')
    stale_phrases = (
        "idle-only",
        "Idle-only",
        "Reward exceeds maximum bounty amount",
        "reward exceeds maximum bounty amount",
        "Minimum remaining reserve would be violated",
        "minimum remaining reserve would be violated",
        "Policy and budget select one bounded bounty while alternatives can decline",
        "alternatives can decline",
        "not funded: Not funded",
        "background_study",
        "Transfer provider: fake",
        "solver_python_terminal_tui",
        "Vi" + "ca",
        "VI" + "CA",
        "vi" + "ca",
    )
    for relative in (
        "README.md",
        "dashboard.html",
        "recording-timeline.md",
        "director.html",
        "director-record.html",
        "director-notes.html",
        "director-cues.json",
    ):
        path = bundle_dir / relative
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if "github.test" in text:
            mismatches.append(f"judge-facing asset {relative} contains github.test URL")
        for marker in raw_currency:
            if marker in text:
                mismatches.append(f"judge-facing asset {relative} contains raw minor-unit currency {marker}")
        for marker in raw_labels:
            if marker in text:
                mismatches.append(f"judge-facing asset {relative} contains raw machine label {marker}")
        for marker in stale_phrases:
            if marker in text:
                mismatches.append(f"judge-facing asset {relative} contains stale presentation phrase {marker}")
    return mismatches


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


def _human_verdict(value: Any) -> str:
    text = str(value or "recorded").strip().lower().replace("_", " ")
    replacements = {
        "agent declined": "declined",
        "declined": "declined",
        "approved": "approved",
        "recorded": "recorded",
    }
    return replacements.get(text, text)


def _human_reasons(value: Any) -> str:
    if isinstance(value, str):
        try:
            loaded = json.loads(value)
        except json.JSONDecodeError:
            loaded = value
    else:
        loaded = value
    if isinstance(loaded, list):
        parts = [str(item).strip() for item in loaded if str(item).strip()]
    elif loaded:
        parts = [str(loaded).strip()]
    else:
        parts = ["No reason recorded"]
    cleaned = []
    for part in parts:
        normalized = part.strip().lower().replace("_", " ")
        replacements = {
            "agent declined candidate": "not funded: vague, unverifiable, or outside project policy",
            "reward exceeds maximum bounty amount": "estimated funding need is above the project spending cap",
            "minimum remaining reserve would be violated": "project budget would not leave the required reserve",
            "trusted policy approved bounded spend": "trusted project policy approved a verifier-backed bounty",
            "trusted policy approved bounded spend; minimum remaining reserve would be violated": "project policy approved a verifier-backed bounty, then budget reserve blocked the candidate",
        }
        sentence = replacements.get(normalized, part).replace("_", " ")
        if sentence:
            cleaned.append(sentence[0].upper() + sentence[1:])
    return "; ".join(cleaned)


def _project_decision_display_reason(text: str, *, funded: bool) -> str:
    if funded:
        return text
    cleaned = re.sub(r"(?i)^not funded:\s*", "", text.strip())
    normalized = cleaned.lower()
    replacements = {
        "task is vague, subjective, or lacks measurable acceptance": "vague, subjective, or missing verifier",
        "no protected verifier is available yet": "missing protected verifier",
        "project policy left this candidate unfunded": "outside current project policy",
    }
    return replacements.get(normalized, cleaned)


def _humanize_display_text(text: Any) -> str:
    return str(text).replace("background_study", "background study").replace("_", " ")


def _solver_display(value: Any) -> str:
    solver_id = str(value or "").strip()
    if solver_id == "solver_python_terminal_tui":
        return "Python terminal/TUI specialist"
    return solver_id or "unavailable"


def _settlement_mode_line(provider: Any) -> str:
    text = str(provider or "").strip().lower()
    if text == "fake":
        return "Settlement mode: deterministic fallback"
    if text:
        return f"Settlement mode: {text}"
    return "Settlement mode: unavailable"


def _money(amount: Any, currency: Any) -> str:
    if amount is None:
        return "unknown"
    if not isinstance(amount, int) or isinstance(amount, bool):
        try:
            amount = int(amount)
        except (TypeError, ValueError):
            return f"{amount} {currency or ''}".strip()
    currency_text = str(currency or "").upper()
    major = amount // 100
    minor = abs(amount) % 100
    sign = "-" if amount < 0 else ""
    if currency_text == "USD":
        return f"{sign}${abs(major)}.{minor:02d}"
    if currency_text == "EUR":
        return f"{sign}€{abs(major)}.{minor:02d}"
    suffix = f" {currency_text}" if currency_text else ""
    return f"{sign}{abs(major)}.{minor:02d}{suffix}"


def _yes_no(value: Any) -> str:
    return "yes" if value is True else "no" if value is False else "unknown"


def _motoko_cases(fragment: dict[str, Any]) -> dict[str, dict[str, Any]]:
    safe = fragment.get("safe_evidence") if isinstance(fragment.get("safe_evidence"), dict) else {}
    cases = safe.get("cases")
    if not isinstance(cases, list):
        return {}
    return {str(case.get("case")): case for case in cases if isinstance(case, dict)}


def _motoko_case_latency(fragment: dict[str, Any], case_name: str) -> str:
    case = _motoko_cases(fragment).get(case_name) or {}
    metrics = case.get("metrics") if isinstance(case.get("metrics"), dict) else {}
    value = metrics.get("p95_ms")
    if value is None:
        return "unavailable"
    try:
        return f"{float(value):.3f} ms"
    except (TypeError, ValueError):
        return str(value)


def _motoko_case_result(fragment: dict[str, Any], case_name: str) -> str:
    case = _motoko_cases(fragment).get(case_name) or {}
    verdict = case.get("verdict") or "unavailable"
    return f"{verdict}; p95 {_motoko_case_latency(fragment, case_name)}"


def _motoko_verification_bullets(fragment: dict[str, Any], summary: dict[str, Any]) -> list[str]:
    cases = _motoko_cases(fragment)
    if not cases:
        return [
            f"Accepted receipt: {_short(summary.get('receipt_id'))}",
            f"Contract digest: {_short(summary.get('contract_digest'))}",
        ]
    bullets = []
    for name, label in (
        (MOTOKO_ORIGINAL_CASE, "Original buggy version"),
        (MOTOKO_SUPERFICIAL_CASE, "Superficial typing fix"),
        (MOTOKO_FINAL_CASE, "Final background-study fix"),
    ):
        case = cases.get(name) or {}
        reasons = case.get("failure_reasons") if isinstance(case.get("failure_reasons"), list) else []
        reason_text = _humanize_display_text("; ".join(str(reason) for reason in reasons)) if reasons else "no failure reasons"
        bullets.append(f"{label}: {case.get('verdict') or 'unavailable'}; p95 {_motoko_case_latency(fragment, name)}; {_short(reason_text, keep=90)}")
    bullets.append(f"Accepted receipt: {_short(summary.get('receipt_id'))}")
    return bullets


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
