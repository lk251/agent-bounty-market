from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Iterable

from .execution import OpenShellBackend, openshell_status, scrubbed_env
from .hermes_integration import hermes_executable, hermes_status_report
from .util import file_digest, sha256_bytes, stable_json, utc_now
from .verification import ProtectedVerifierRunner


NVIDIA_STATUS_SCHEMA = "agent-bounty-nvidia-runtime-status-v1"
NVIDIA_DEMO_SCHEMA = "agent-bounty-nvidia-sandbox-demo-v1"
NVIDIA_POLICY_SCHEMA = "agent-bounty-nvidia-policy-report-v1"
NVIDIA_SANDBOX_NAME_ENV = "AGENT_BOUNTY_NVIDIA_SANDBOX_NAME"
NVIDIA_MODEL_ENV = "AGENT_BOUNTY_NVIDIA_MODEL_ID"
NVIDIA_API_KEY_ENV = "NVIDIA_API_KEY"
NVIDIA_BASE_URL_ENV = "NVIDIA_BASE_URL"


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def policy_dir() -> Path:
    return repo_root() / "nvidia" / "openshell"


def policy_file() -> Path:
    return policy_dir() / "agent-bounty-policy.yaml"


def manifest_file() -> Path:
    return policy_dir() / "manifest.json"


def sandbox_name() -> str:
    return os.environ.get(NVIDIA_SANDBOX_NAME_ENV, "agent-bounty-verifier").strip() or "agent-bounty-verifier"


def command_status(command: str, version_args: Iterable[str] = ("--version",)) -> dict[str, Any]:
    path = shutil.which(command)
    if not path:
        return {"command": command, "available": False, "path": None, "version": None, "blocker": f"{command} executable not found on PATH"}
    try:
        result = subprocess.run(
            [path, *version_args],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except Exception as exc:
        return {"command": command, "available": False, "path": path, "version": None, "blocker": f"{command} version probe failed: {type(exc).__name__}"}
    text = (result.stdout or result.stderr or "").strip().splitlines()
    version = text[0][:240] if text else None
    return {
        "command": command,
        "available": result.returncode == 0,
        "path": path,
        "version": version,
        "blocker": None if result.returncode == 0 else f"{command} version probe exited {result.returncode}",
    }


def docker_status_report() -> dict[str, Any]:
    path = shutil.which("docker")
    if not path:
        return {"available": False, "path": None, "info_ok": False, "blocker": "docker executable not found on PATH"}
    try:
        result = subprocess.run(["docker", "info", "--format", "{{json .ServerVersion}}"], capture_output=True, text=True, timeout=8, check=False)
    except Exception as exc:
        return {"available": False, "path": path, "info_ok": False, "blocker": f"docker info failed: {type(exc).__name__}"}
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        summary = detail[0][:240] if detail else "docker info failed"
        return {"available": False, "path": path, "info_ok": False, "blocker": summary}
    return {"available": True, "path": path, "info_ok": True, "blocker": None}


def policy_report() -> dict[str, Any]:
    policy = policy_file()
    manifest = manifest_file()
    policy_exists = policy.exists()
    manifest_exists = manifest.exists()
    manifest_payload: dict[str, Any] = {}
    if manifest_exists:
        try:
            manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
        except Exception as exc:
            manifest_payload = {"error": f"manifest parse failed: {type(exc).__name__}"}
    pieces = []
    for path in (policy, manifest):
        if path.exists():
            pieces.append(f"{path.relative_to(repo_root())}:{file_digest(path)}")
    return {
        "schema": NVIDIA_POLICY_SCHEMA,
        "policy_path": str(policy.relative_to(repo_root())),
        "policy_exists": policy_exists,
        "policy_digest": file_digest(policy) if policy_exists else None,
        "manifest_path": str(manifest.relative_to(repo_root())),
        "manifest_exists": manifest_exists,
        "manifest_digest": file_digest(manifest) if manifest_exists else None,
        "effective_policy_digest": sha256_bytes("\n".join(pieces).encode("utf-8")) if pieces else None,
        "manifest": manifest_payload,
    }


def sanitized_inference_config() -> dict[str, Any]:
    return {
        "nvidia_api_key_configured": bool(os.environ.get(NVIDIA_API_KEY_ENV)),
        "nvidia_base_url_configured": bool(os.environ.get(NVIDIA_BASE_URL_ENV)),
        "nvidia_base_url_host": _safe_host(os.environ.get(NVIDIA_BASE_URL_ENV)),
        "model_id": os.environ.get(NVIDIA_MODEL_ENV),
    }


def _safe_host(value: str | None) -> str | None:
    if not value:
        return None
    text = value.strip()
    if "://" in text:
        text = text.split("://", 1)[1]
    return text.split("/", 1)[0][:160] or None


def nvidia_runtime_status_report(*, discover_models: bool = False, doctor: bool = False) -> dict[str, Any]:
    docker = docker_status_report()
    openshell = openshell_status()
    openshell_cli = command_status("openshell")
    nemoclaw = command_status("nemoclaw")
    policy = policy_report()
    hermes = hermes_status_report(probe_doctor=doctor, discover_models=discover_models)
    inference = sanitized_inference_config()
    blockers: list[str] = []
    if not docker["available"]:
        blockers.append(str(docker["blocker"]))
    if not openshell_cli["path"]:
        blockers.append("openshell executable not found on PATH")
    elif not openshell.get("available"):
        blockers.append(str(openshell.get("blocker") or "OpenShell sandbox is unavailable"))
    if not policy["policy_exists"] or not policy["manifest_exists"]:
        blockers.append("project-owned OpenShell policy or manifest is missing")
    if not inference["nvidia_api_key_configured"]:
        blockers.append("set NVIDIA_API_KEY for real NVIDIA NIM/Nemotron inference")
    if not inference["model_id"]:
        blockers.append(f"set {NVIDIA_MODEL_ENV} after NVIDIA model discovery")
    return {
        "schema": NVIDIA_STATUS_SCHEMA,
        "created_at": utc_now(),
        "ok": not blockers,
        "real_backend_ready": bool(docker["available"] and openshell.get("available") and policy["policy_exists"] and policy["manifest_exists"]),
        "real_hermes_in_sandbox_ready": bool(docker["available"] and openshell.get("available") and inference["nvidia_api_key_configured"] and inference["model_id"]),
        "sandbox_name": sandbox_name(),
        "docker": docker,
        "openshell": openshell,
        "openshell_cli": openshell_cli,
        "nemoclaw": nemoclaw,
        "policy": policy,
        "inference": inference,
        "hermes": {
            "ok": hermes.get("ok"),
            "cli": hermes.get("hermes_cli"),
            "provider": hermes.get("provider"),
            "blockers": hermes.get("blockers"),
        },
        "blockers": blockers,
    }


def adversarial_probe_plan() -> list[dict[str, Any]]:
    return [
        {"id": "deny_example_dot_com", "expectation": "candidate outbound public internet denied"},
        {"id": "deny_github_api", "expectation": "candidate direct GitHub API denied"},
        {"id": "deny_stripe_api", "expectation": "candidate direct Stripe API denied"},
        {"id": "sentinel_absent", "expectation": "host sentinel secret absent from sandbox"},
        {"id": "policy_readonly", "expectation": "candidate cannot write host verifier policy"},
        {"id": "hang_bounded", "expectation": "fork/hang/output flood bounded and killed"},
        {"id": "path_escape_blocked", "expectation": "host path escape or symlink traversal blocked"},
        {"id": "inference_allowlist", "expectation": "inference endpoint allows only required methods and paths"},
        {"id": "teardown_clean", "expectation": "sandbox teardown removes ephemeral candidate state"},
        {"id": "snapshot_filtered", "expectation": "snapshots exclude secrets, keys, tokens, .env, .demo, and personal state"},
    ]


def safe_sandbox_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = scrubbed_env(extra or {})
    for key in list(env):
        if key.upper().startswith("NVIDIA_") or key.upper().startswith("AGENT_BOUNTY_NVIDIA_"):
            env.pop(key, None)
    return env


def run_adversarial_probes(*, real_backend: bool) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for probe in adversarial_probe_plan():
        rows.append(
            {
                **probe,
                "status": "not_run" if not real_backend else "requires_live_openshell_operator_review",
                "passed": None if not real_backend else False,
                "backend": "openshell" if real_backend else None,
            }
        )
    return rows


def verification_case_rows(
    *,
    motoko_repo: Path,
    base_commit: str,
    intermediate_commit: str,
    final_commit: str,
    real_backend: bool,
    timeout_seconds: float,
) -> list[dict[str, Any]]:
    cases = [
        ("baseline", base_commit, False),
        ("intermediate", intermediate_commit, False),
        ("final", final_commit, True),
    ]
    if not real_backend:
        return [
            {"case": label, "candidate_commit": commit, "expected_accepted": expected, "status": "not_run", "backend": None}
            for label, commit, expected in cases
        ]
    runner = ProtectedVerifierRunner(backend=OpenShellBackend(sandbox_name=sandbox_name(), policy_file=policy_file()), timeout_seconds=timeout_seconds)
    rows: list[dict[str, Any]] = []
    for label, commit, expected in cases:
        result = runner.run(
            bounty_id=f"bounty_motoko_issue_1_{label}",
            motoko_repo=motoko_repo,
            base_commit=base_commit,
            candidate_commit=commit,
        )
        rows.append(
            {
                "case": label,
                "candidate_commit": commit,
                "expected_accepted": expected,
                "accepted": result.accepted,
                "status": "pass" if result.accepted is expected else "fail",
                "backend": result.backend,
                "backend_digest": result.backend_digest,
                "policy_digest": result.policy_digest,
                "verifier_digest": result.verifier_digest,
                "result_digest": sha256_bytes(stable_json(result.result).encode("utf-8")),
            }
        )
    return rows


def run_nvidia_sandbox_demo(
    *,
    motoko_repo: Path,
    bundle_dir: Path | None,
    require_real: bool,
    base_commit: str,
    intermediate_commit: str,
    final_commit: str,
    timeout_seconds: float = 60.0,
) -> dict[str, Any]:
    status = nvidia_runtime_status_report(discover_models=False, doctor=False)
    real_backend = bool(status.get("real_backend_ready"))
    if require_real and not real_backend:
        return {
            "schema": NVIDIA_DEMO_SCHEMA,
            "ok": False,
            "real_backend": False,
            "real_hermes_in_sandbox": False,
            "blocker": "; ".join(status.get("blockers") or ["OpenShell backend is not ready"]),
            "status": status,
        }
    rows = verification_case_rows(
        motoko_repo=motoko_repo,
        base_commit=base_commit,
        intermediate_commit=intermediate_commit,
        final_commit=final_commit,
        real_backend=real_backend,
        timeout_seconds=timeout_seconds,
    )
    adversarial = run_adversarial_probes(real_backend=real_backend)
    payload = {
        "schema": NVIDIA_DEMO_SCHEMA,
        "created_at": utc_now(),
        "ok": True,
        "real_backend": real_backend,
        "real_hermes_in_sandbox": bool(real_backend and status.get("real_hermes_in_sandbox_ready")),
        "sandbox_name": sandbox_name(),
        "policy_digest": status["policy"]["effective_policy_digest"],
        "policy_file_digest": status["policy"]["policy_digest"],
        "manifest_digest": status["policy"]["manifest_digest"],
        "openshell_version": status["openshell_cli"].get("version"),
        "nemoclaw_version": status["nemoclaw"].get("version"),
        "hermes_executable": hermes_executable(),
        "blockers": status.get("blockers", []),
        "adversarial_probes": adversarial,
        "verification_cases": rows,
        "cleanup": {"status": "not_run" if not real_backend else "backend_managed"},
        "status": status,
    }
    if bundle_dir:
        bundle_dir.mkdir(parents=True, exist_ok=True)
        bundle_path = bundle_dir / "nvidia-sandbox-demo.json"
        bundle_path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
        payload["bundle_path"] = str(bundle_path)
        payload["bundle_digest"] = file_digest(bundle_path)
    return payload
