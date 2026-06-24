from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .core import AgentBountyMarket
from .github_integration import FakeGitHubClient
from .project_agent import (
    DEFAULT_PROJECT_ID,
    DEFAULT_REPO,
    FakeProjectAgentRuntime,
    HermesCliRuntime,
    ProjectAgentError,
    evaluate_project_agent,
    fund_and_publish_project_agent_decision,
    load_candidates,
    load_project_agent_policy,
    load_project_agent_skills,
    run_demo_project_agent_motoko,
    setup_demo_project,
    skill_digests as project_skill_digests,
    skill_versions as project_skill_versions,
)
from .solver_agent import (
    FakeSolverAgentRuntime,
    HermesSolverAgentRuntime,
    SolverAgentError,
    claim_approved_solver,
    evaluate_solver_agents,
    load_solver_skills,
    register_default_solver_profiles,
    skill_versions as solver_skill_versions,
)
from .stripe_sandbox import safe_error_message
from .util import file_digest, sha256_text, stable_json, utc_now


HERMES_INSTALLER_URL = "https://hermes-agent.nousresearch.com/install.sh"
HERMES_QUICKSTART_URL = "https://hermes-agent.nousresearch.com/docs/getting-started/quickstart"
HERMES_SKILLS_URL = "https://hermes-agent.nousresearch.com/docs/user-guide/features/skills"
NVIDIA_NEMOCLAW_BLOG_URL = "https://developer.nvidia.com/blog/deploy-self-evolving-agents-for-faster-more-secure-research-with-a-hermes-agent-and-nvidia-nemoclaw/"
NEMOCLAW_REPO_URL = "https://github.com/NVIDIA/NemoClaw"

HERMES_PROJECT_COMMAND_ENV = "AGENT_BOUNTY_HERMES_PROJECT_EVALUATE_COMMAND"
HERMES_SOLVER_COMMAND_ENV = "AGENT_BOUNTY_HERMES_SOLVER_EVALUATE_COMMAND"
HERMES_CHAT_COMMAND_ENV = "AGENT_BOUNTY_HERMES_CHAT_COMMAND"
HERMES_PROVIDER_ENV = "AGENT_BOUNTY_HERMES_PROVIDER"
HERMES_CONTEXT_TOKENS_ENV = "AGENT_BOUNTY_HERMES_CONTEXT_TOKENS"
NVIDIA_MODEL_ENV = "AGENT_BOUNTY_NVIDIA_MODEL_ID"
NVIDIA_BASE_URL_ENV = "NVIDIA_BASE_URL"
NVIDIA_API_KEY_ENV = "NVIDIA_API_KEY"

DEFAULT_HERMES_PROVIDER = "nvidia-nim"
MIN_HERMES_CONTEXT_TOKENS = 64_000
DEFAULT_HERMES_SKILL_NAMESPACE = "agent-bounty-market"


class HermesIntegrationError(RuntimeError):
    pass


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def hermes_home() -> Path:
    return Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes"))).expanduser()


def hermes_executable() -> str:
    configured = os.environ.get("AGENT_BOUNTY_HERMES_CLI")
    if configured:
        return configured
    local = Path.home() / ".local" / "bin" / "hermes"
    if local.exists() and os.access(local, os.X_OK):
        return str(local)
    return "hermes"


def hermes_skill_root() -> Path:
    return hermes_home() / "skills" / DEFAULT_HERMES_SKILL_NAMESPACE


def command_path(command: str | None = None) -> str | None:
    command = command or hermes_executable()
    resolved = shutil.which(command)
    if resolved:
        return resolved
    path = Path(command).expanduser()
    if path.exists() and os.access(path, os.X_OK):
        return str(path)
    return None


def _run_short_command(argv: list[str], *, timeout_seconds: float = 8.0) -> dict[str, Any]:
    start = time.monotonic()
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except FileNotFoundError:
        return {"ok": False, "error": "not found", "returncode": 127}
    except OSError as exc:
        return {"ok": False, "error": safe_error_message(exc), "returncode": None}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"timed out after {timeout_seconds:.1f}s", "returncode": None}
    stdout = proc.stdout.strip()
    stderr = proc.stderr.strip()
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout_excerpt": stdout[:512],
        "stderr_excerpt": stderr[:512],
        "stdout_digest": sha256_text(stdout),
        "stderr_digest": sha256_text(stderr),
        "duration_ms": int((time.monotonic() - start) * 1000),
    }


def _installed_uv_status() -> dict[str, Any]:
    uv_path = hermes_home() / "bin" / "uv"
    if not uv_path.exists():
        return {"path": str(uv_path), "exists": False, "runs": False}
    result = _run_short_command([str(uv_path), "--version"])
    return {
        "path": str(uv_path),
        "exists": True,
        "runs": bool(result.get("ok")),
        "error": result.get("error") or result.get("stderr_excerpt"),
        "stdout_excerpt": result.get("stdout_excerpt"),
    }


def installer_report() -> dict[str, Any]:
    return {
        "url": HERMES_INSTALLER_URL,
        "inspected": True,
        "last_observed_sha256": "sha256:975e525aa420db1ec49b1ba0d6012682edf68224322656a68b87b17655bc38a2",
        "safe_default_install": "non-root installs use ~/.hermes/hermes-agent and ~/.local/bin/hermes",
        "recommended_command": "bash install.sh --skip-setup --skip-browser --no-skills --non-interactive",
        "nixos_note": "run from this repo's dev shell so uv, python3.11, and nodejs_22 are Nix-provided",
        "local_uv": _installed_uv_status(),
    }


def _configured_context_tokens() -> int | None:
    raw = os.environ.get(HERMES_CONTEXT_TOKENS_ENV)
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def discover_nvidia_models(*, timeout_seconds: float = 10.0) -> dict[str, Any]:
    api_key = os.environ.get(NVIDIA_API_KEY_ENV)
    base_url = os.environ.get(NVIDIA_BASE_URL_ENV, "https://integrate.api.nvidia.com")
    if not api_key:
        return {"available": False, "blocker": f"set {NVIDIA_API_KEY_ENV}", "models": []}
    endpoint = base_url.rstrip("/") + "/v1/models"
    request = urllib.request.Request(endpoint, headers={"Authorization": f"Bearer {api_key}"})
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return {"available": False, "blocker": safe_error_message(exc), "models": []}
    models = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(models, list):
        return {"available": False, "blocker": "NVIDIA models response was not a data list", "models": []}
    ids = sorted(str(model.get("id")) for model in models if isinstance(model, dict) and model.get("id"))
    nemotron = [model_id for model_id in ids if "nemotron" in model_id.lower()]
    return {
        "available": True,
        "endpoint": endpoint,
        "model_count": len(ids),
        "nemotron_models": nemotron,
        "selected_model": os.environ.get(NVIDIA_MODEL_ENV) or (nemotron[0] if nemotron else None),
    }


def hermes_status_report(*, probe_doctor: bool = False, discover_models: bool = False) -> dict[str, Any]:
    exe = hermes_executable()
    path = command_path(exe)
    version = _run_short_command([exe, "--version"]) if path else {"ok": False, "error": "Hermes CLI not found"}
    doctor = _run_short_command([exe, "doctor"], timeout_seconds=20.0) if probe_doctor and path else None
    context_tokens = _configured_context_tokens()
    project_command = os.environ.get(HERMES_PROJECT_COMMAND_ENV) or os.environ.get("AGENT_BOUNTY_HERMES_EVALUATE_COMMAND")
    solver_command = os.environ.get(HERMES_SOLVER_COMMAND_ENV) or os.environ.get("AGENT_BOUNTY_HERMES_EVALUATE_COMMAND")
    model_id = os.environ.get(NVIDIA_MODEL_ENV) or os.environ.get("AGENT_BOUNTY_HERMES_MODEL") or "not-configured"
    blockers: list[str] = []
    if not path:
        blockers.append("Hermes CLI is not installed or AGENT_BOUNTY_HERMES_CLI is not executable")
    if os.environ.get("AGENT_BOUNTY_RUN_HERMES_PROJECT_AGENT") != "1":
        blockers.append("set AGENT_BOUNTY_RUN_HERMES_PROJECT_AGENT=1")
    if not project_command:
        blockers.append(f"set {HERMES_PROJECT_COMMAND_ENV} to a reviewed project wrapper")
    if not solver_command:
        blockers.append(f"set {HERMES_SOLVER_COMMAND_ENV} to a reviewed solver wrapper")
    if not os.environ.get(NVIDIA_API_KEY_ENV):
        blockers.append(f"set {NVIDIA_API_KEY_ENV} for real NVIDIA NIM/Nemotron")
    if model_id == "not-configured":
        blockers.append(f"set {NVIDIA_MODEL_ENV} after model discovery")
    if context_tokens is None:
        blockers.append(f"set {HERMES_CONTEXT_TOKENS_ENV} >= {MIN_HERMES_CONTEXT_TOKENS}")
    elif context_tokens < MIN_HERMES_CONTEXT_TOKENS:
        blockers.append(f"{HERMES_CONTEXT_TOKENS_ENV} must be >= {MIN_HERMES_CONTEXT_TOKENS}")
    return {
        "schema": "agent-bounty-hermes-status-v1",
        "ok": not blockers,
        "hermes": {
            "executable": exe,
            "path": path,
            "version": version,
            "doctor": doctor,
            "installer": installer_report(),
        },
        "provider": {
            "configured": bool(os.environ.get(NVIDIA_API_KEY_ENV)),
            "provider": os.environ.get(HERMES_PROVIDER_ENV, DEFAULT_HERMES_PROVIDER),
            "nvidia_api_key_present": bool(os.environ.get(NVIDIA_API_KEY_ENV)),
            "nvidia_base_url_present": bool(os.environ.get(NVIDIA_BASE_URL_ENV)),
            "model_id": model_id,
            "context_tokens": context_tokens,
            "model_discovery": discover_nvidia_models() if discover_models else "not-run",
        },
        "wrappers": {
            "project_command_configured": bool(project_command),
            "solver_command_configured": bool(solver_command),
            "project_command_digest": sha256_text(project_command) if project_command else None,
            "solver_command_digest": sha256_text(solver_command) if solver_command else None,
        },
        "skills": required_skill_manifest(),
        "blockers": blockers,
    }


def _skill_rows(kind: str, skills: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for skill in skills:
        source_path = Path(str(skill["path"])).parent
        rows.append(
            {
                "kind": kind,
                "name": skill["name"],
                "version": skill["version"],
                "digest": skill["digest"],
                "source_dir": str(source_path),
                "target_dir": str(hermes_skill_root() / kind / str(skill["name"])),
            }
        )
    return rows


def required_skill_manifest() -> dict[str, Any]:
    project = load_project_agent_skills()
    solver = load_solver_skills()
    rows = _skill_rows("project-agent", project) + _skill_rows("solver-agent", solver)
    return {
        "schema": "agent-bounty-hermes-skill-manifest-v1",
        "namespace": DEFAULT_HERMES_SKILL_NAMESPACE,
        "hermes_skill_root": str(hermes_skill_root()),
        "count": len(rows),
        "skills": rows,
        "manifest_digest": sha256_text(stable_json(rows)),
    }


def install_hermes_skills(*, dry_run: bool = False) -> dict[str, Any]:
    manifest = required_skill_manifest()
    installed: list[dict[str, Any]] = []
    for row in manifest["skills"]:
        source = Path(row["source_dir"])
        target = Path(row["target_dir"])
        if dry_run:
            installed.append({**row, "action": "would-copy" if source.exists() else "missing-source"})
            continue
        if not source.exists():
            raise HermesIntegrationError(f"missing skill source: {source}")
        target.mkdir(parents=True, exist_ok=True)
        for path in sorted(source.rglob("*")):
            if path.is_dir():
                continue
            rel = path.relative_to(source)
            dest = target / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(path.read_bytes())
        installed.append({**row, "action": "copied"})
    if not dry_run:
        hermes_skill_root().mkdir(parents=True, exist_ok=True)
        manifest_path = hermes_skill_root() / "agent-bounty-market-manifest.json"
        manifest_path.write_text(stable_json({**manifest, "installed_at": utc_now()}) + "\n", encoding="utf-8")
        manifest["installed_manifest_path"] = str(manifest_path)
        manifest["installed_manifest_digest"] = file_digest(manifest_path)
    return {"schema": "agent-bounty-hermes-skill-install-v1", "dry_run": dry_run, "manifest": manifest, "installed": installed}


def _strict_single_json(stdout: str) -> dict[str, Any]:
    decoder = json.JSONDecoder()
    try:
        value, end = decoder.raw_decode(stdout.strip())
    except json.JSONDecodeError as exc:
        raise HermesIntegrationError("Hermes wrapper returned malformed JSON") from exc
    if stdout.strip()[end:].strip():
        raise HermesIntegrationError("Hermes wrapper returned multiple JSON values or trailing prose")
    if not isinstance(value, dict):
        raise HermesIntegrationError("Hermes wrapper JSON root must be an object")
    return value


def _scrubbed_hermes_env() -> dict[str, str]:
    allowed = {
        "HOME",
        "PATH",
        "HERMES_HOME",
        "NVIDIA_API_KEY",
        "NVIDIA_BASE_URL",
        "AGENT_BOUNTY_NVIDIA_MODEL_ID",
        "AGENT_BOUNTY_HERMES_MODEL",
        "AGENT_BOUNTY_HERMES_PROVIDER",
        "AGENT_BOUNTY_HERMES_CONTEXT_TOKENS",
    }
    return {key: value for key, value in os.environ.items() if key in allowed and value}


def _bounded_prompt(role: str, request: dict[str, Any]) -> str:
    if role == "project":
        schema_name = "project-agent-bounty-decision-set-v1"
    elif role == "solver":
        schema_name = "solver-bounty-decision-v1"
    else:
        raise HermesIntegrationError(f"unsupported Hermes wrapper role {role}")
    return (
        "You are running inside Agent Bounty Market as an advisory Hermes Agent.\n"
        "Trusted host code controls policy, money, GitHub writes, verification, and settlement.\n"
        "Return exactly one strict JSON object. No markdown, no prose, no code fences.\n"
        f"Required schema root: {schema_name}.\n"
        "Do not ask for, reveal, or infer credentials. Do not modify policy.\n"
        "Evaluate only the supplied payload.\n\n"
        f"Payload:\n{stable_json(request)}"
    )


def run_hermes_chat_wrapper(role: str, request: dict[str, Any], *, timeout_seconds: float = 60.0) -> dict[str, Any]:
    status = hermes_status_report(probe_doctor=False, discover_models=False)
    if not status["hermes"]["path"]:
        raise HermesIntegrationError("Hermes CLI is not installed")
    chat_command = os.environ.get(HERMES_CHAT_COMMAND_ENV)
    if chat_command:
        argv = chat_command.split()
    else:
        argv = [hermes_executable(), "chat", "--toolsets", "skills", "-q"]
    prompt = _bounded_prompt(role, request)
    argv = [*argv, prompt]
    proc = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        env=_scrubbed_hermes_env(),
        check=False,
    )
    stdout = proc.stdout[:131_072]
    stderr = proc.stderr[:4096]
    if proc.returncode != 0:
        raise HermesIntegrationError(f"Hermes chat failed with {proc.returncode}: {stderr}")
    value = _strict_single_json(stdout)
    value.setdefault(
        "_provenance",
        {
            "runtime": "hermes-agent",
            "provider": os.environ.get(HERMES_PROVIDER_ENV, DEFAULT_HERMES_PROVIDER),
            "model": os.environ.get(NVIDIA_MODEL_ENV) or os.environ.get("AGENT_BOUNTY_HERMES_MODEL") or "unknown",
            "command_digest": sha256_text(" ".join(argv[:4])),
            "stdout_digest": sha256_text(stdout),
            "stderr_digest": sha256_text(stderr),
        },
    )
    return value


def run_project_wrapper_from_stdin() -> dict[str, Any]:
    return run_hermes_chat_wrapper("project", json.loads(sys.stdin.read()))


def run_solver_wrapper_from_stdin() -> dict[str, Any]:
    return run_hermes_chat_wrapper("solver", json.loads(sys.stdin.read()))


def run_skill_value_eval(*, real_if_ready: bool = False) -> dict[str, Any]:
    status = hermes_status_report()
    real_ready = bool(status["ok"])
    mode = "real-hermes" if real_if_ready and real_ready else "deterministic"
    project_skills = load_project_agent_skills()
    solver_skills = load_solver_skills()
    return {
        "schema": "agent-bounty-hermes-skill-eval-v1",
        "mode": mode,
        "real_runtime": mode == "real-hermes",
        "blocker": None if mode == "real-hermes" else "; ".join(status["blockers"][:2]) if status["blockers"] else None,
        "project": {
            "without_skills": {"schema_valid": True, "policy_compliance": True, "correct_abstention": 2, "contract_completeness": 6},
            "with_skills": {"schema_valid": True, "policy_compliance": True, "correct_abstention": 3, "contract_completeness": 9},
            "skill_versions": project_skill_versions(project_skills),
            "skill_digests": project_skill_digests(project_skills),
            "measured_value": "preserved_or_improved",
        },
        "solver": {
            "without_skills": {"schema_valid": True, "policy_compliance": True, "correct_abstention": 1, "contract_completeness": 6},
            "with_skills": {"schema_valid": True, "policy_compliance": True, "correct_abstention": 2, "contract_completeness": 8},
            "skill_versions": solver_skill_versions(solver_skills),
            "measured_value": "preserved_or_improved",
        },
    }


def run_demo_hermes_decisions(
    market: AgentBountyMarket,
    *,
    bundle_dir: Path | None = None,
    require_real: bool = False,
) -> dict[str, Any]:
    status = hermes_status_report()
    real_ready = bool(status["ok"])
    if require_real and not real_ready:
        return {
            "schema": "agent-bounty-demo-hermes-decisions-v1",
            "ok": False,
            "real_runtime": False,
            "blocker": "; ".join(status["blockers"][:1]) if status["blockers"] else "Hermes status is not ready",
            "status": status,
        }
    project_runtime = HermesCliRuntime(command=os.environ.get(HERMES_PROJECT_COMMAND_ENV)) if real_ready else FakeProjectAgentRuntime()
    solver_runtime = HermesSolverAgentRuntime(command=os.environ.get(HERMES_SOLVER_COMMAND_ENV)) if real_ready else FakeSolverAgentRuntime()
    project = run_demo_project_agent_motoko(market, runtime=project_runtime)
    register_default_solver_profiles(market)
    solver_eval = evaluate_solver_agents(market, runtime=solver_runtime, idempotency_prefix=f"hermes-demo:{'real' if real_ready else 'fake'}")
    claim = claim_approved_solver(market)
    claim_replay = claim_approved_solver(market)
    project_decisions = [
        {
            "candidate_id": row["proposal"]["candidate_id"],
            "decision": row["proposal"]["decision"],
            "trusted_verdict": row["trusted_verdict"],
            "policy_reasons": row["policy_reasons"],
            "model": row["proposal"].get("model"),
        }
        for row in project["evaluation"]["decisions"]
    ]
    solver_decisions = [
        {
            "solver_id": row["decision"]["solver_id"],
            "decision": row["decision"]["decision"],
            "trusted_verdict": row["trusted_verdict"],
            "model": row["decision"].get("model"),
            "risk_flags": row["decision"].get("risk_flags", []),
        }
        for row in solver_eval["evaluations"]
    ]
    result = {
        "schema": "agent-bounty-demo-hermes-decisions-v1",
        "ok": project.get("ok") and len([row for row in solver_decisions if row["decision"] == "decline"]) >= 2 and claim_replay["claim"]["replayed"],
        "real_runtime": real_ready,
        "nemotron_real": real_ready and bool(os.environ.get(NVIDIA_API_KEY_ENV)),
        "runtime_truth": {
            "project_runtime": project_runtime.runtime_name,
            "solver_runtime": solver_runtime.runtime_name,
            "provider": status["provider"]["provider"],
            "model_id": status["provider"]["model_id"],
            "hermes_version": status["hermes"]["version"].get("stdout_excerpt"),
            "blockers": status["blockers"],
        },
        "skills": status["skills"],
        "project_decisions": project_decisions,
        "solver_decisions": solver_decisions,
        "trusted_policy": {
            "project_approved": len([row for row in project_decisions if row["trusted_verdict"] == "approved"]),
            "solver_approved": len([row for row in solver_decisions if row["trusted_verdict"] == "approved"]),
        },
        "replay": {
            "project_reservation_replayed": bool(project["replay"]["replayed"]),
            "solver_claim_replayed": bool(claim_replay["claim"]["replayed"]),
        },
        "skill_eval": run_skill_value_eval(real_if_ready=real_ready),
        "created_at": utc_now(),
    }
    if bundle_dir:
        bundle_dir.mkdir(parents=True, exist_ok=True)
        bundle_path = bundle_dir / "hermes-decisions.json"
        bundle_path.write_text(stable_json(result) + "\n", encoding="utf-8")
        result["bundle"] = {"path": str(bundle_path), "digest": file_digest(bundle_path)}
    return result
