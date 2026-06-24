from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from .core import AgentBountyMarket
from .db import connect
from .payments import FakePaymentGateway
from .stripe_sandbox import (
    PINNED_STRIPE_PACKAGE,
    STRIPE_INTEGRATION_ENV,
    stripe_cli_version,
    stripe_package_version,
)
from .util import file_digest, sha256_bytes, stable_json, utc_now
from .verification import ProtectedVerifierRunner, verifier_digest


DEMO_SCHEMA = "agent-bounty-demo-bundle-v1"
LOCAL_PROJECT_ID = "project_demo_local"
LOCAL_BOUNTY_ID = "bounty_demo_local_001"
LOCAL_SOLVER_ID = "solver_demo_local"
LOCAL_CURRENCY = "USD"


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _remove_tree(path: Path) -> None:
    def retry_readonly(function: Any, target: str, _exc: BaseException) -> None:
        os.chmod(target, 0o700)
        function(target)

    shutil.rmtree(path, onexc=retry_readonly)


def _run(cmd: list[str], *, cwd: Path | None = None) -> str:
    return subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def _git_commit(repo: Path, filename: str, text: str, message: str) -> str:
    _write_text(repo / filename, text)
    _run(["git", "add", filename], cwd=repo)
    _run(["git", "commit", "-m", message], cwd=repo)
    return _run(["git", "rev-parse", "HEAD"], cwd=repo)


def build_local_candidate_repo(root: Path) -> dict[str, str]:
    repo = root / "candidate"
    repo.mkdir(parents=True, exist_ok=True)
    _run(["git", "init"], cwd=repo)
    _run(["git", "config", "user.email", "demo@example.invalid"], cwd=repo)
    _run(["git", "config", "user.name", "Agent Bounty Demo"], cwd=repo)
    base = _git_commit(repo, "bug.txt", "typing latency: present\n", "base bug")
    candidate = _git_commit(repo, "bug.txt", "typing latency: fixed\n", "fix typing latency")
    return {"repo": str(repo), "base_commit": base, "candidate_commit": candidate}


def build_local_verifier(root: Path) -> Path:
    verifier_dir = root / "verifier"
    verifier_dir.mkdir(parents=True, exist_ok=True)
    _write_text(verifier_dir / "README.md", "Deterministic local demo verifier.\n")
    _write_text(
        verifier_dir / "contract.json",
        json.dumps({"schema": "local-demo-contract-v1", "verifier_id": "local_demo_verifier"}, sort_keys=True) + "\n",
    )
    _write_text(
        verifier_dir / "verifier.py",
        """from __future__ import annotations

import argparse
import json
import subprocess


parser = argparse.ArgumentParser()
parser.add_argument("--bounty-id", required=True)
parser.add_argument("--candidate-repo", required=True)
parser.add_argument("--base-commit", required=True)
parser.add_argument("--candidate-commit", required=True)
parser.add_argument("--backend", required=True)
args = parser.parse_args()

content = subprocess.run(
    ["git", "-C", args.candidate_repo, "show", f"{args.candidate_commit}:bug.txt"],
    check=True,
    capture_output=True,
    text=True,
).stdout
accepted = "fixed" in content and args.base_commit != args.candidate_commit
print(json.dumps({
    "schema": "protected-verifier-result-v1",
    "verifier_id": "local_demo_verifier",
    "verifier_version": "1.0.0",
    "accepted": accepted,
    "metrics": {"typing_latency_p95_ms": 42 if accepted else 240},
    "failure_reasons": [] if accepted else ["candidate did not contain the local fix marker"],
}, sort_keys=True, separators=(",", ":")))
raise SystemExit(0 if accepted else 1)
""",
    )
    return verifier_dir


def run_demo_local(*, state_dir: Path, bundle_dir: Path | None = None) -> dict[str, Any]:
    state_dir = state_dir.resolve()
    bundle_dir = bundle_dir.resolve() if bundle_dir else None
    state_dir.mkdir(parents=True, exist_ok=True)
    bundle_dir = bundle_dir or (state_dir / "bundles" / "local-run")
    if bundle_dir.exists():
        _remove_tree(bundle_dir)
    bundle_dir.mkdir(parents=True)
    workspace = state_dir / "local-workspace"
    if workspace.exists():
        _remove_tree(workspace)
    workspace.mkdir(parents=True)

    candidate = build_local_candidate_repo(workspace)
    verifier_dir = build_local_verifier(workspace)
    db_path = state_dir / "market.sqlite3"
    if db_path.exists():
        db_path.unlink()
    conn = connect(db_path)
    market = AgentBountyMarket(
        conn,
        FakePaymentGateway(),
        ProtectedVerifierRunner(verifier_dir=verifier_dir, timeout_seconds=10),
    )
    market.create_project(project_id=LOCAL_PROJECT_ID, name="Local simulation project", currency=LOCAL_CURRENCY)
    market.set_budget_policy(
        project_id=LOCAL_PROJECT_ID,
        max_bounty_amount=2500,
        monthly_budget=2500,
        human_approval_threshold=2500,
        allowed_issue_classes=["local-simulation"],
    )
    funding = market.fund_project(
        project_id=LOCAL_PROJECT_ID,
        amount=2500,
        currency=LOCAL_CURRENCY,
        idempotency_key="demo-local:fund",
    )
    market.create_bounty(
        bounty_id=LOCAL_BOUNTY_ID,
        project_id=LOCAL_PROJECT_ID,
        title="Fix local demo typing latency",
        reward_amount=2500,
        currency=LOCAL_CURRENCY,
        base_commit=candidate["base_commit"],
        issue_ref="local/demo#1",
        verifier_id="local_demo_verifier",
    )
    reserve = market.reserve_bounty(bounty_id=LOCAL_BOUNTY_ID, idempotency_key="demo-local:reserve")
    market.create_solver(
        solver_id=LOCAL_SOLVER_ID,
        display_name="Local simulation solver",
        idempotency_key="demo-local:beneficiary",
    )
    claim = market.claim_bounty(
        bounty_id=LOCAL_BOUNTY_ID,
        solver_id=LOCAL_SOLVER_ID,
        lease_expires_at="2026-06-30T18:00:00Z",
        idempotency_key="demo-local:claim",
    )
    submission = market.submit_candidate(
        bounty_id=LOCAL_BOUNTY_ID,
        solver_id=LOCAL_SOLVER_ID,
        candidate_repo_path=candidate["repo"],
        candidate_commit=candidate["candidate_commit"],
        idempotency_key="demo-local:submission",
    )
    verification = market.run_verification(
        submission_id=submission["submission_id"],
        idempotency_key="demo-local:verification",
    )
    payout = market.release_payout(bounty_id=LOCAL_BOUNTY_ID, idempotency_key="demo-local:payout")
    reconciliation = market.reconciliation(project_id=LOCAL_PROJECT_ID, solver_id=LOCAL_SOLVER_ID)
    bounty = market.bounty_summary(LOCAL_BOUNTY_ID)
    bundle = {
        "schema": DEMO_SCHEMA,
        "mode": "local",
        "label": "Local simulation",
        "created_at": utc_now(),
        "repository": {
            "path": candidate["repo"],
            "base_commit": candidate["base_commit"],
            "candidate_commit": candidate["candidate_commit"],
        },
        "project": {
            "id": LOCAL_PROJECT_ID,
            "treasury_available_cents": reconciliation["balances"].get("project_available", 0),
            "treasury_reserved_cents": reconciliation["balances"].get("project_reserved", 0),
            "treasury_spent_cents": reconciliation["balances"].get("solver_paid", 0),
        },
        "bounty": bounty,
        "events": {
            "funding": funding,
            "reserve": reserve,
            "claim": claim,
            "submission": submission,
            "verification": verification,
            "payout": payout,
        },
        "trust": {
            "verifier_digest": verifier_digest(verifier_dir),
            "backend": (verification.get("receipt") or {}).get("backend"),
            "backend_digest": (verification.get("receipt") or {}).get("backend_digest"),
            "policy_digest": (verification.get("receipt") or {}).get("policy_digest"),
            "receipt_id": (verification.get("receipt") or {}).get("receipt_id"),
        },
        "economics": {
            "reward_cents": 2500,
            "external_transfer": payout.get("gateway_payout_id"),
            "retained_operating_credit_cents": 0,
            "estimated_tool_cost_cents": 0,
            "gross_margin_cents": 0,
        },
        "reconciliation": reconciliation,
        "warnings": ["Local simulation: no real GitHub, Hermes/NVIDIA, or Stripe objects were used."],
    }
    payload_path = bundle_dir / "bundle.json"
    payload_path.write_text(stable_json(bundle) + "\n", encoding="utf-8")
    manifest = {
        "schema": "agent-bounty-demo-manifest-v1",
        "bundle_schema": DEMO_SCHEMA,
        "mode": "local",
        "created_at": utc_now(),
        "files": [{"path": "bundle.json", "sha256": file_digest(payload_path)}],
    }
    (bundle_dir / "manifest.json").write_text(stable_json(manifest) + "\n", encoding="utf-8")
    ok = reconciliation["ok"] and bounty["state"] == "paid" and not payout.get("failed", False)
    conn.close()
    return {
        "schema": "agent-bounty-demo-local-result-v1",
        "ok": ok,
        "mode": "local",
        "state_dir": str(state_dir),
        "bundle_dir": str(bundle_dir),
        "bundle_digest": file_digest(payload_path),
        "receipt_id": bundle["trust"]["receipt_id"],
        "payout_id": payout["payout_id"],
        "label": "Local simulation",
    }


def validate_bundle(bundle_dir: Path) -> dict[str, Any]:
    manifest_path = bundle_dir / "manifest.json"
    payload_path = bundle_dir / "bundle.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    bundle = json.loads(payload_path.read_text(encoding="utf-8"))
    mismatches: list[str] = []
    for entry in manifest.get("files", []):
        path = bundle_dir / entry["path"]
        actual = file_digest(path)
        if actual != entry["sha256"]:
            mismatches.append(f"{entry['path']} digest mismatch")
    if manifest.get("bundle_schema") != bundle.get("schema"):
        mismatches.append("manifest bundle_schema does not match bundle schema")
    if bundle.get("schema") != DEMO_SCHEMA:
        mismatches.append("unsupported bundle schema")
    if bundle.get("mode") == "local" and bundle.get("label") != "Local simulation":
        mismatches.append("local bundle must keep the Local simulation label")
    return {
        "schema": "agent-bounty-demo-bundle-validation-v1",
        "ok": not mismatches,
        "bundle_dir": str(bundle_dir),
        "bundle_digest": file_digest(payload_path),
        "mode": bundle.get("mode"),
        "label": bundle.get("label"),
        "mismatches": mismatches,
        "bundle": bundle if not mismatches else None,
    }


def run_demo_replay(*, bundle_dir: Path) -> dict[str, Any]:
    validation = validate_bundle(bundle_dir)
    bundle = validation.pop("bundle", None)
    result = {
        "schema": "agent-bounty-demo-replay-result-v1",
        "ok": validation["ok"],
        "mode": "replay",
        "validation": validation,
        "label": "Replay of recorded real run" if bundle and bundle.get("mode") == "real" else "Local simulation replay",
    }
    if bundle:
        result["timeline"] = {
            "project": bundle.get("project"),
            "bounty_state": (bundle.get("bounty") or {}).get("state"),
            "receipt_id": (bundle.get("trust") or {}).get("receipt_id"),
            "payout": (bundle.get("events") or {}).get("payout"),
            "warnings": bundle.get("warnings", []),
        }
    return result


def _port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def demo_preflight(*, state_dir: Path | None = None) -> dict[str, Any]:
    blockers: list[str] = []
    warnings: list[str] = []
    git_version = None
    try:
        git_version = _run(["git", "--version"])
    except Exception:
        blockers.append("git is not available")
    python_version = _run([sys.executable, "--version"])
    stripe_version = stripe_package_version()
    if stripe_version != PINNED_STRIPE_PACKAGE:
        warnings.append(f"optional Stripe package is {stripe_version}; live Stripe path expects stripe=={PINNED_STRIPE_PACKAGE}")
    if os.environ.get(STRIPE_INTEGRATION_ENV) != "1":
        warnings.append(f"live Stripe disabled; set {STRIPE_INTEGRATION_ENV}=1 for sandbox checks")
    if not _port_available(8765):
        warnings.append("dashboard demo port 8765 is already in use")
    dirty = None
    try:
        dirty = bool(_run(["git", "status", "--short"]))
    except Exception:
        dirty = None
    return {
        "schema": "agent-bounty-demo-preflight-v1",
        "ok": not blockers,
        "mode": "preflight",
        "timestamp": utc_now(),
        "repository": {
            "commit": _run(["git", "rev-parse", "HEAD"]) if git_version else None,
            "branch": _run(["git", "branch", "--show-current"]) if git_version else None,
            "dirty": dirty,
        },
        "python": python_version,
        "git": git_version,
        "stripe": {
            "package_version": stripe_version,
            "required_package": PINNED_STRIPE_PACKAGE,
            "cli": stripe_cli_version(),
            "sandbox_enabled": os.environ.get(STRIPE_INTEGRATION_ENV) == "1",
        },
        "state_dir": str(state_dir) if state_dir else None,
        "ports": [{"host": "127.0.0.1", "port": 8765, "available": _port_available(8765)}],
        "blockers": blockers,
        "warnings": warnings,
    }


def demo_rehearse(*, mode: str, state_dir: Path) -> dict[str, Any]:
    start = time.monotonic()
    stages: list[dict[str, Any]] = []
    preflight = demo_preflight(state_dir=state_dir)
    stages.append({"name": "preflight", "ok": preflight["ok"], "duration_ms": int((time.monotonic() - start) * 1000)})
    if not preflight["ok"]:
        return {"schema": "agent-bounty-demo-rehearsal-v1", "ok": False, "mode": mode, "stages": stages, "preflight": preflight}
    if mode == "local":
        stage_start = time.monotonic()
        local = run_demo_local(state_dir=state_dir, bundle_dir=state_dir / "bundles" / "rehearsal-local")
        stages.append({"name": "local-run", "ok": local["ok"], "duration_ms": int((time.monotonic() - stage_start) * 1000)})
        stage_start = time.monotonic()
        replay = run_demo_replay(bundle_dir=Path(local["bundle_dir"]))
        stages.append({"name": "replay-validation", "ok": replay["ok"], "duration_ms": int((time.monotonic() - stage_start) * 1000)})
        return {
            "schema": "agent-bounty-demo-rehearsal-v1",
            "ok": local["ok"] and replay["ok"],
            "mode": mode,
            "stages": stages,
            "bundle_dir": local["bundle_dir"],
            "bundle_digest": local["bundle_digest"],
            "total_duration_ms": int((time.monotonic() - start) * 1000),
        }
    if mode == "replay":
        bundle_dir = state_dir / "bundles" / "rehearsal-local"
        if not bundle_dir.exists():
            run_demo_local(state_dir=state_dir, bundle_dir=bundle_dir)
        stage_start = time.monotonic()
        replay = run_demo_replay(bundle_dir=bundle_dir)
        stages.append({"name": "replay-validation", "ok": replay["ok"], "duration_ms": int((time.monotonic() - stage_start) * 1000)})
        return {
            "schema": "agent-bounty-demo-rehearsal-v1",
            "ok": replay["ok"],
            "mode": mode,
            "stages": stages,
            "bundle_dir": str(bundle_dir),
            "total_duration_ms": int((time.monotonic() - start) * 1000),
        }
    if mode == "live":
        return {
            "schema": "agent-bounty-demo-rehearsal-v1",
            "ok": False,
            "mode": mode,
            "stages": stages,
            "blockers": ["live rehearsal requires configured GitHub, Hermes/NVIDIA, and Stripe sandbox credentials"],
            "total_duration_ms": int((time.monotonic() - start) * 1000),
        }
    raise ValueError(f"unsupported rehearsal mode {mode}")


def reset_demo_state(*, state_dir: Path, yes: bool) -> dict[str, Any]:
    if not yes:
        return {
            "schema": "agent-bounty-demo-reset-v1",
            "ok": False,
            "state_dir": str(state_dir),
            "blocker": "pass --yes to delete demo state",
        }
    if state_dir.exists():
        with tempfile.TemporaryDirectory() as tmp:
            resolved = state_dir.resolve()
            if resolved == Path(tmp).resolve():
                raise RuntimeError("refusing to delete temporary guard directory")
        _remove_tree(state_dir)
    return {"schema": "agent-bounty-demo-reset-v1", "ok": True, "state_dir": str(state_dir)}
