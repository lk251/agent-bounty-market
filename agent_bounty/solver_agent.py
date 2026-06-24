from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from .core import AgentBountyMarket, MarketError
from .domain import BountyState
from .github_integration import FakeGitHubClient, build_submission_marker
from .project_agent import (
    DEFAULT_BASE_COMMIT,
    DEFAULT_BOUNTY_ID,
    DEFAULT_FINAL_COMMIT,
    DEFAULT_PROJECT_ID,
    DEFAULT_REPO,
    DEFAULT_VERIFIER_ID,
    HERMES_RUN_ENV,
    HERMES_CLI_ENV,
    HERMES_COMMAND_ENV,
    HERMES_MODEL_ENV,
    default_skills_dir,
    command_available,
    default_hermes_cli,
    run_demo_project_agent_motoko,
)
from .stripe_sandbox import safe_error_message
from .util import sha256_text, stable_json, utc_now


SOLVER_DECISION_SCHEMA = "solver-bounty-decision-v1"
SOLVER_STATUS_SCHEMA = "solver-agent-status-v1"
SOLVER_PROFILE_VERSION = "0.1.0"
HERMES_SOLVER_COMMAND_ENV = "AGENT_BOUNTY_HERMES_SOLVER_EVALUATE_COMMAND"
NVIDIA_MODEL_ENV = "AGENT_BOUNTY_NVIDIA_MODEL_ID"

PYTHON_SOLVER_ID = "solver_python_terminal_tui"
TYPESCRIPT_SOLVER_ID = "solver_typescript_frontend"
CUDA_SOLVER_ID = "solver_cuda_pytorch_perf"

DECISION_KEYS = {
    "schema",
    "solver_id",
    "bounty_id",
    "decision",
    "capability_match",
    "success_probability_estimate",
    "estimated_cost_cents",
    "estimated_minutes",
    "reward_cents",
    "expected_margin_cents",
    "risk_flags",
    "unknowns",
    "plan",
    "model",
    "skill_versions",
}


class SolverAgentError(RuntimeError):
    pass


def _stable_id(prefix: str, payload: Any) -> str:
    return f"{prefix}_{sha256_text(stable_json(payload))[-24:]}"


def solver_skills_dir() -> Path:
    return default_skills_dir().parent / "solver-agent"


def _parse_skill_metadata(text: str) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for line in text.splitlines()[:40]:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        if key in {"name", "version", "category", "provenance"}:
            metadata[key] = value.strip()
    return metadata


def load_solver_skills() -> list[dict[str, Any]]:
    root = solver_skills_dir()
    if not root.exists():
        return []
    skills: list[dict[str, Any]] = []
    for skill_file in sorted(root.glob("*/SKILL.md")):
        text = skill_file.read_text(encoding="utf-8")
        metadata = _parse_skill_metadata(text)
        name = metadata.get("name") or skill_file.parent.name
        version = metadata.get("version") or "0.0.0"
        digest = sha256_text(text)
        skills.append(
            {
                "id": _stable_id("sskill", {"name": name, "version": version, "digest": digest}),
                "name": name,
                "version": version,
                "digest": digest,
                "path": str(skill_file),
                "content_digest": digest,
                "metadata": metadata,
            }
        )
    return skills


def record_solver_skills(market: AgentBountyMarket, skills: list[dict[str, Any]]) -> None:
    now = utc_now()
    with market.conn:
        for skill in skills:
            market.conn.execute(
                """
                INSERT INTO solver_agent_skills(
                    id, name, version, digest, path, content_digest, metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(name, version, digest) DO UPDATE SET
                    path = excluded.path,
                    content_digest = excluded.content_digest,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                (
                    skill["id"],
                    skill["name"],
                    skill["version"],
                    skill["digest"],
                    skill["path"],
                    skill["content_digest"],
                    stable_json(skill["metadata"]),
                    now,
                    now,
                ),
            )


def skill_versions(skills: list[dict[str, Any]]) -> dict[str, str]:
    return {str(skill["name"]): str(skill["version"]) for skill in skills}


def default_solver_profiles() -> list[dict[str, Any]]:
    return [
        {
            "id": PYTHON_SOLVER_ID,
            "display_name": "Python terminal/TUI concurrency specialist",
            "profile_version": SOLVER_PROFILE_VERSION,
            "specialization": {
                "languages": ["python"],
                "task_families": ["terminal-tui", "pty", "background-concurrency"],
                "supported_versions": ["python3.12"],
                "verified_history": [{"task_family": "terminal-tui", "receipt": "motoko_issue_1_v2"}],
            },
            "operating_budget_cents": 900,
            "allowed_repositories": [DEFAULT_REPO],
            "allowed_issue_classes": ["machine-verifiable-tui-regression", "bugfix"],
            "scope_restrictions": ["no hidden verifier edits", "no network unless trusted host grants it"],
        },
        {
            "id": TYPESCRIPT_SOLVER_ID,
            "display_name": "TypeScript/frontend specialist",
            "profile_version": SOLVER_PROFILE_VERSION,
            "specialization": {
                "languages": ["typescript", "javascript"],
                "task_families": ["frontend", "react", "ui-polish"],
                "supported_versions": ["node20"],
                "verified_history": [],
            },
            "operating_budget_cents": 500,
            "allowed_repositories": [DEFAULT_REPO],
            "allowed_issue_classes": ["frontend", "ui"],
            "scope_restrictions": ["decline backend Python TUI verifier work"],
        },
        {
            "id": CUDA_SOLVER_ID,
            "display_name": "CUDA/PyTorch performance specialist",
            "profile_version": SOLVER_PROFILE_VERSION,
            "specialization": {
                "languages": ["cuda", "python"],
                "task_families": ["gpu-kernels", "pytorch-performance"],
                "supported_versions": ["cuda12"],
                "verified_history": [],
            },
            "operating_budget_cents": 700,
            "allowed_repositories": [DEFAULT_REPO],
            "allowed_issue_classes": ["gpu-performance"],
            "scope_restrictions": ["uncertain without GPU performance benchmark history"],
        },
    ]


def register_default_solver_profiles(market: AgentBountyMarket) -> dict[str, Any]:
    now = utc_now()
    rows: list[dict[str, Any]] = []
    with market.conn:
        for profile in default_solver_profiles():
            digest = sha256_text(stable_json(profile))
            market.conn.execute(
                """
                INSERT INTO solver_agent_profiles(
                    id, display_name, profile_version, specialization_json, operating_budget_cents,
                    allowed_repositories_json, allowed_issue_classes_json, scope_restrictions_json,
                    profile_digest, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    display_name = excluded.display_name,
                    profile_version = excluded.profile_version,
                    specialization_json = excluded.specialization_json,
                    operating_budget_cents = excluded.operating_budget_cents,
                    allowed_repositories_json = excluded.allowed_repositories_json,
                    allowed_issue_classes_json = excluded.allowed_issue_classes_json,
                    scope_restrictions_json = excluded.scope_restrictions_json,
                    profile_digest = excluded.profile_digest,
                    updated_at = excluded.updated_at
                """,
                (
                    profile["id"],
                    profile["display_name"],
                    profile["profile_version"],
                    stable_json(profile["specialization"]),
                    int(profile["operating_budget_cents"]),
                    stable_json(profile["allowed_repositories"]),
                    stable_json(profile["allowed_issue_classes"]),
                    stable_json(profile["scope_restrictions"]),
                    digest,
                    now,
                    now,
                ),
            )
            rows.append({"solver_id": profile["id"], "profile_digest": digest, **profile})
    return {"schema": "solver-agent-profile-registration-v1", "profiles": rows}


def load_solver_profiles(market: AgentBountyMarket) -> list[dict[str, Any]]:
    rows = market.conn.execute("SELECT * FROM solver_agent_profiles ORDER BY id").fetchall()
    profiles: list[dict[str, Any]] = []
    for row in rows:
        profile = dict(row)
        profile["specialization"] = json.loads(row["specialization_json"])
        profile["allowed_repositories"] = json.loads(row["allowed_repositories_json"])
        profile["allowed_issue_classes"] = json.loads(row["allowed_issue_classes_json"])
        profile["scope_restrictions"] = json.loads(row["scope_restrictions_json"])
        profiles.append(profile)
    return profiles


def open_funded_contracts(market: AgentBountyMarket) -> list[dict[str, Any]]:
    rows = market.conn.execute(
        """
        SELECT b.*, g.contract_digest, g.repo_full_name, g.issue_number, g.issue_url, g.contract_json
        FROM bounties b
        LEFT JOIN github_issue_contracts g ON g.bounty_id = b.id
        WHERE b.state = ?
        ORDER BY b.created_at, b.id
        """,
        (BountyState.OPEN.value,),
    ).fetchall()
    return [dict(row) for row in rows]


class FakeSolverAgentRuntime:
    runtime_kind = "fake"
    runtime_name = "fake-solver-agent-runtime-v1"
    model = "deterministic-solver-underwriter-v1"

    def evaluate(self, *, profile: dict[str, Any], bounty: dict[str, Any], skills: list[dict[str, Any]]) -> dict[str, Any]:
        issue_class = "machine-verifiable-tui-regression"
        reward = int(bounty["reward_amount"])
        versions = skill_versions(skills)
        solver_id = profile["id"]
        if solver_id == PYTHON_SOLVER_ID:
            decision = "claim"
            score = 0.92
            cost = {"low": 150, "likely": 350, "high": 700}
            minutes = {"low": 20, "likely": 45, "high": 120}
            risks: list[str] = []
            unknowns = ["exact local runtime availability"]
            plan = [
                "inspect contract and verifier identity",
                "claim exclusive lease",
                "replay known accepted Motoko issue #1 candidate SHA",
                "submit evidence package for protected verification",
            ]
        elif solver_id == TYPESCRIPT_SOLVER_ID:
            decision = "decline"
            score = 0.18
            cost = {"low": 100, "likely": 400, "high": 1000}
            minutes = {"low": 30, "likely": 90, "high": 240}
            risks = ["capability-mismatch"]
            unknowns = ["Python PTY/TUI backend not in verified profile"]
            plan = []
        else:
            decision = "decline"
            score = 0.11
            cost = {"low": 200, "likely": 800, "high": 2000}
            minutes = {"low": 45, "likely": 180, "high": 360}
            risks = ["capability-mismatch", "no-history-uncertainty"]
            unknowns = ["no verified history for terminal responsiveness"]
            plan = []
        likely_cost = int(cost["likely"])
        return {
            "schema": SOLVER_DECISION_SCHEMA,
            "solver_id": solver_id,
            "bounty_id": bounty["id"],
            "decision": decision,
            "capability_match": {"score": score, "evidence": profile["specialization"].get("verified_history", [])},
            "success_probability_estimate": 0.76 if decision == "claim" else 0.0,
            "estimated_cost_cents": cost,
            "estimated_minutes": minutes,
            "reward_cents": reward,
            "expected_margin_cents": reward - likely_cost,
            "risk_flags": risks,
            "unknowns": unknowns,
            "plan": plan,
            "model": self.model,
            "skill_versions": versions,
        }


class HermesSolverAgentRuntime:
    runtime_kind = "hermes"
    runtime_name = "hermes-solver-cli-adapter-v1"

    def __init__(self, *, command: str | None = None, model: str | None = None):
        self.command = command or os.environ.get(HERMES_SOLVER_COMMAND_ENV) or os.environ.get(HERMES_COMMAND_ENV)
        self.model = model or os.environ.get(NVIDIA_MODEL_ENV) or os.environ.get(HERMES_MODEL_ENV, "nvidia/nemotron-configured-by-hermes")

    def blockers(self) -> list[str]:
        blockers: list[str] = []
        hermes_bin = default_hermes_cli()
        if not command_available(hermes_bin):
            blockers.append(f"install Hermes CLI or set {HERMES_CLI_ENV}")
        if os.environ.get(HERMES_RUN_ENV) != "1":
            blockers.append(f"set {HERMES_RUN_ENV}=1")
        if not self.command:
            blockers.append(f"set {HERMES_SOLVER_COMMAND_ENV} to a reviewed Hermes solver wrapper")
        return blockers

    def evaluate(
        self,
        *,
        profile: dict[str, Any],
        bounty: dict[str, Any],
        skills: list[dict[str, Any]],
        timeout_seconds: float = 30.0,
        max_output_bytes: int = 65_536,
    ) -> dict[str, Any]:
        blockers = self.blockers()
        if blockers:
            raise SolverAgentError("; ".join(blockers))
        assert self.command is not None
        request = {
            "schema": "solver-agent-evaluation-request-v1",
            "profile": {
                "id": profile["id"],
                "display_name": profile["display_name"],
                "profile_version": profile["profile_version"],
                "specialization": profile["specialization"],
                "operating_budget_cents": profile["operating_budget_cents"],
                "allowed_repositories": profile["allowed_repositories"],
                "allowed_issue_classes": profile["allowed_issue_classes"],
                "scope_restrictions": profile["scope_restrictions"],
            },
            "bounty": {
                "id": bounty["id"],
                "state": bounty["state"],
                "reward_amount": bounty["reward_amount"],
                "currency": bounty["currency"],
                "base_commit": bounty["base_commit"],
                "issue_ref": bounty["issue_ref"],
                "verifier_id": bounty["verifier_id"],
                "repo_full_name": bounty.get("repo_full_name"),
                "contract_digest": bounty.get("contract_digest"),
            },
            "skill_versions": skill_versions(skills),
            "skill_digests": {str(skill["name"]): str(skill["digest"]) for skill in skills},
            "instructions": [
                "Return exactly one solver-bounty-decision-v1 object.",
                "Claim only when the supplied profile fits the supplied bounty.",
                "Do not change policy, claim a lease, spend money, or request credentials.",
            ],
        }
        start = time.monotonic()
        env = {
            "HOME": os.environ.get("HOME", ""),
            "PATH": os.environ.get("PATH", ""),
            "HERMES_HOME": os.environ.get("HERMES_HOME", ""),
            "AGENT_BOUNTY_SOLVER_AGENT": "1",
            "NVIDIA_API_KEY": os.environ.get("NVIDIA_API_KEY", ""),
            "NVIDIA_BASE_URL": os.environ.get("NVIDIA_BASE_URL", ""),
            "AGENT_BOUNTY_NVIDIA_MODEL_ID": os.environ.get("AGENT_BOUNTY_NVIDIA_MODEL_ID", ""),
            "AGENT_BOUNTY_HERMES_MODEL": os.environ.get("AGENT_BOUNTY_HERMES_MODEL", ""),
        }
        env = {key: value for key, value in env.items() if value}
        proc = subprocess.run(
            shlex.split(self.command),
            input=stable_json(request),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=env,
            check=False,
        )
        stdout = proc.stdout[:max_output_bytes]
        stderr = proc.stderr[:4096]
        if proc.returncode != 0:
            raise SolverAgentError(f"Hermes solver runtime failed with {proc.returncode}: {stderr}")
        try:
            decision = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise SolverAgentError("Hermes solver runtime returned malformed JSON") from exc
        decision = parse_solver_decision(decision)
        decision["model"] = str(decision.get("model") or self.model)
        self.last_safe_trace = {
            "runtime": self.runtime_name,
            "command_digest": sha256_text(self.command),
            "stdout_digest": sha256_text(stdout),
            "stderr_digest": sha256_text(stderr),
            "returncode": proc.returncode,
            "duration_ms": int((time.monotonic() - start) * 1000),
            "credential_exposure": False,
        }
        return decision


def parse_solver_decision(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        raise SolverAgentError("solver decision must be an object")
    extra = set(value) - DECISION_KEYS
    missing = DECISION_KEYS - set(value)
    if extra:
        raise SolverAgentError(f"solver decision has unsupported field(s): {', '.join(sorted(extra))}")
    if missing:
        raise SolverAgentError(f"solver decision missing field(s): {', '.join(sorted(missing))}")
    if value.get("schema") != SOLVER_DECISION_SCHEMA:
        raise SolverAgentError("solver decision schema mismatch")
    if value.get("decision") not in {"claim", "decline", "needs_human"}:
        raise SolverAgentError("solver decision must be claim, decline, or needs_human")
    for key in ("capability_match", "estimated_cost_cents", "estimated_minutes", "skill_versions"):
        if not isinstance(value.get(key), dict):
            raise SolverAgentError(f"solver decision {key} must be an object")
    for key in ("risk_flags", "unknowns", "plan"):
        if not isinstance(value.get(key), list):
            raise SolverAgentError(f"solver decision {key} must be a list")
    return value


def trusted_solver_policy(market: AgentBountyMarket, *, profile: dict[str, Any], bounty: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    if decision["decision"] == "decline":
        return {"trusted_verdict": "agent_declined", "reasons": ["solver declined"], "claim_allowed": False}
    if decision["decision"] == "needs_human":
        return {"trusted_verdict": "needs_human", "reasons": ["solver requested human review"], "claim_allowed": False}
    reasons: list[str] = []
    if bounty["state"] != BountyState.OPEN.value:
        reasons.append("contract is not open")
    if bounty.get("repo_full_name") not in profile["allowed_repositories"]:
        reasons.append("solver is not allowlisted for repository")
    issue_class = "machine-verifiable-tui-regression"
    if issue_class not in profile["allowed_issue_classes"]:
        reasons.append("solver is not allowlisted for issue class")
    if int(decision["estimated_cost_cents"]["likely"]) > int(profile["operating_budget_cents"]):
        reasons.append("expected cost exceeds solver operating budget")
    if int(decision["expected_margin_cents"]) < 0:
        reasons.append("expected margin is negative")
    if int(decision["reward_cents"]) != int(bounty["reward_amount"]):
        reasons.append("reward does not match canonical bounty")
    if "high-risk" in set(decision["risk_flags"]):
        reasons.append("high-risk flag requires human review")
    active = market.conn.execute("SELECT id FROM claims WHERE bounty_id = ? AND status = 'active'", (bounty["id"],)).fetchone()
    if active:
        reasons.append("claim lease is already active")
    if reasons:
        return {"trusted_verdict": "declined", "reasons": reasons, "claim_allowed": False}
    return {"trusted_verdict": "approved", "reasons": ["trusted solver policy approved claim"], "claim_allowed": True}


def validate_path_policy(*, changed_files: list[str], allowed_prefixes: list[str], forbidden_prefixes: list[str]) -> dict[str, Any]:
    violations: list[str] = []
    for path in changed_files:
        normalized = path.strip().lstrip("./")
        if any(normalized == prefix.rstrip("/") or normalized.startswith(prefix.rstrip("/") + "/") for prefix in forbidden_prefixes):
            violations.append(f"forbidden path changed: {path}")
        if allowed_prefixes and not any(normalized == prefix.rstrip("/") or normalized.startswith(prefix.rstrip("/") + "/") for prefix in allowed_prefixes):
            violations.append(f"path outside allowlist: {path}")
    return {"ok": not violations, "violations": violations}


def verify_pr_head_unchanged(*, evidence: dict[str, Any], current_head_sha: str) -> dict[str, Any]:
    expected = evidence.get("candidate_commit")
    ok = isinstance(expected, str) and expected == current_head_sha
    return {"ok": ok, "expected": expected, "current": current_head_sha, "reason": None if ok else "PR head changed after verification"}


def skill_promotion_verdict(*, baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    if candidate.get("protected_receipt_accepted") is not True:
        return {"promote": False, "reason": "no accepted protected receipt"}
    if int(candidate.get("contract_completeness", 0)) < int(baseline.get("contract_completeness", 0)):
        return {"promote": False, "reason": "contract completeness regressed"}
    if int(candidate.get("policy_violations", 0)) > int(baseline.get("policy_violations", 0)):
        return {"promote": False, "reason": "policy compliance regressed"}
    if int(candidate.get("cost_cents", 0)) > int(baseline.get("cost_cents", 0)):
        return {"promote": False, "reason": "cost increased"}
    return {"promote": True, "reason": "accepted receipt and regression fixture improved or held steady"}


def evaluate_solver_agents(
    market: AgentBountyMarket,
    *,
    runtime: FakeSolverAgentRuntime | HermesSolverAgentRuntime | None = None,
    idempotency_prefix: str = "solver-agent:evaluate",
) -> dict[str, Any]:
    runtime = runtime or FakeSolverAgentRuntime()
    skills = load_solver_skills()
    record_solver_skills(market, skills)
    profiles = load_solver_profiles(market)
    bounties = open_funded_contracts(market)
    if not profiles:
        raise SolverAgentError("no solver profiles registered")
    if not bounties:
        raise SolverAgentError("no open funded contracts")
    rows: list[dict[str, Any]] = []
    now = utc_now()
    with market.conn:
        for bounty in bounties:
            for profile in profiles:
                decision = parse_solver_decision(runtime.evaluate(profile=profile, bounty=bounty, skills=skills))
                verdict = trusted_solver_policy(market, profile=profile, bounty=bounty, decision=decision)
                digest = sha256_text(stable_json(decision))
                eval_id = _stable_id("seval", {"solver_id": profile["id"], "bounty_id": bounty["id"], "digest": digest})
                trace = {
                    "runtime": runtime.runtime_name,
                    "solver_id": profile["id"],
                    "bounty_id": bounty["id"],
                    "credential_exposure": False,
                }
                trace.update(getattr(runtime, "last_safe_trace", {}) or {})
                market.conn.execute(
                    """
                    INSERT INTO solver_agent_evaluations(
                        id, solver_id, bounty_id, runtime_kind, runtime_name, model,
                        decision_json, decision_digest, trusted_verdict, policy_reasons_json,
                        safe_trace_json, safe_trace_digest, skill_versions_json, created_at, idempotency_key
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(solver_id, bounty_id, decision_digest) DO UPDATE SET
                        trusted_verdict = excluded.trusted_verdict,
                        policy_reasons_json = excluded.policy_reasons_json
                    """,
                    (
                        eval_id,
                        profile["id"],
                        bounty["id"],
                        runtime.runtime_kind,
                        runtime.runtime_name,
                        runtime.model,
                        stable_json(decision),
                        digest,
                        verdict["trusted_verdict"],
                        stable_json(verdict["reasons"]),
                        stable_json(trace),
                        sha256_text(stable_json(trace)),
                        stable_json(skill_versions(skills)),
                        now,
                        f"{idempotency_prefix}:{profile['id']}:{bounty['id']}",
                    ),
                )
                rows.append({"evaluation_id": eval_id, "decision": decision, "trusted_verdict": verdict["trusted_verdict"], "policy_reasons": verdict["reasons"]})
    return {"schema": "solver-agent-evaluation-v1", "evaluations": rows}


def claim_approved_solver(market: AgentBountyMarket, *, lease_expires_at: str = "2026-06-30T18:00:00Z") -> dict[str, Any]:
    row = market.conn.execute(
        """
        SELECT e.*, p.display_name
        FROM solver_agent_evaluations e
        JOIN solver_agent_profiles p ON p.id = e.solver_id
        WHERE e.trusted_verdict = 'approved'
        ORDER BY e.created_at, e.id
        LIMIT 1
        """
    ).fetchone()
    if not row:
        raise SolverAgentError("no approved solver evaluation")
    market.create_solver(
        solver_id=row["solver_id"],
        display_name=row["display_name"],
        idempotency_key=f"solver-agent:beneficiary:{row['solver_id']}",
    )
    expired_count = market.conn.execute(
        "SELECT COUNT(*) AS count FROM claims WHERE bounty_id = ? AND solver_id = ? AND status = 'expired'",
        (row["bounty_id"], row["solver_id"]),
    ).fetchone()["count"]
    claim = market.claim_bounty(
        bounty_id=row["bounty_id"],
        solver_id=row["solver_id"],
        lease_expires_at=lease_expires_at,
        idempotency_key=f"solver-agent:claim:{row['solver_id']}:{row['bounty_id']}:{expired_count}",
    )
    return {"schema": "solver-agent-claim-v1", "solver_id": row["solver_id"], "bounty_id": row["bounty_id"], "claim": claim}


def execute_deterministic_motoko_replay(market: AgentBountyMarket, *, solver_id: str = PYTHON_SOLVER_ID, bounty_id: str = DEFAULT_BOUNTY_ID) -> dict[str, Any]:
    existing = market.conn.execute(
        "SELECT * FROM solver_agent_executions WHERE idempotency_key = ?",
        (f"solver-agent:execute:replay:{solver_id}:{bounty_id}",),
    ).fetchone()
    if existing:
        return {"schema": "solver-agent-execution-v1", "replayed": True, "execution": dict(existing)}
    now = utc_now()
    execution_id = _stable_id("sexec", {"solver_id": solver_id, "bounty_id": bounty_id, "candidate": DEFAULT_FINAL_COMMIT})
    commands = ["deterministic replay of accepted Motoko issue #1 candidate SHA"]
    changed = ["motoko", "tests/bounty_issue_1.py"]
    path_policy = validate_path_policy(changed_files=changed, allowed_prefixes=["motoko", "tests", "docs"], forbidden_prefixes=["verifiers", ".git"])
    if not path_policy["ok"]:
        raise SolverAgentError("; ".join(path_policy["violations"]))
    with market.conn:
        market.conn.execute(
            """
            INSERT INTO solver_agent_executions(
                id, solver_id, bounty_id, mode, backend, backend_digest, base_commit, candidate_commit,
                worktree_digest, changed_files_json, commands_json, safe_output_digest, status,
                limitations_json, started_at, finished_at, idempotency_key
            ) VALUES (?, ?, ?, 'deterministic-motoko-replay', 'local-isolated-process-fallback',
                ?, ?, ?, ?, ?, ?, ?, 'completed', ?, ?, ?, ?)
            """,
            (
                execution_id,
                solver_id,
                bounty_id,
                sha256_text("local-isolated-process-fallback"),
                DEFAULT_BASE_COMMIT,
                DEFAULT_FINAL_COMMIT,
                sha256_text(DEFAULT_FINAL_COMMIT),
                stable_json(changed),
                stable_json(commands),
                sha256_text(stable_json({"candidate": DEFAULT_FINAL_COMMIT, "mode": "replay"})),
                stable_json(["replay of previously accepted candidate; not a fresh live solve"]),
                now,
                now,
                f"solver-agent:execute:replay:{solver_id}:{bounty_id}",
            ),
        )
    return {"schema": "solver-agent-execution-v1", "replayed": False, "execution_id": execution_id, "candidate_commit": DEFAULT_FINAL_COMMIT}


def record_live_solve_fallback(market: AgentBountyMarket, *, solver_id: str = PYTHON_SOLVER_ID, bounty_id: str = DEFAULT_BOUNTY_ID) -> dict[str, Any]:
    key = f"solver-agent:execute:live-fallback:{solver_id}:{bounty_id}"
    existing = market.conn.execute("SELECT * FROM solver_agent_executions WHERE idempotency_key = ?", (key,)).fetchone()
    if existing:
        return {"schema": "solver-agent-live-fallback-v1", "replayed": True, "execution": dict(existing)}
    now = utc_now()
    execution_id = _stable_id("sexec", {"solver_id": solver_id, "bounty_id": bounty_id, "mode": "live-fallback"})
    with market.conn:
        market.conn.execute(
            """
            INSERT INTO solver_agent_executions(
                id, solver_id, bounty_id, mode, backend, backend_digest, base_commit, candidate_commit,
                worktree_digest, changed_files_json, commands_json, safe_output_digest, status,
                limitations_json, started_at, finished_at, idempotency_key
            ) VALUES (?, ?, ?, 'live-local-fallback', 'not-run-real-live-solve',
                ?, ?, NULL, NULL, ?, ?, ?, 'blocked', ?, ?, ?, ?)
            """,
            (
                execution_id,
                solver_id,
                bounty_id,
                sha256_text("not-run-real-live-solve"),
                DEFAULT_BASE_COMMIT,
                stable_json([]),
                stable_json([]),
                sha256_text("no reviewed safe live issue selected"),
                stable_json(["real live solve requires a reviewed safe issue and configured runtime"]),
                now,
                now,
                key,
            ),
        )
    return {"schema": "solver-agent-live-fallback-v1", "replayed": False, "execution_id": execution_id, "real_live_solve_complete": False}


def submit_solver_replay(
    market: AgentBountyMarket,
    *,
    repo_full_name: str = DEFAULT_REPO,
    pr_number: int = 101,
    motoko_repo: Path | None = None,
) -> dict[str, Any]:
    execution = market.conn.execute(
        "SELECT * FROM solver_agent_executions WHERE bounty_id = ? AND status = 'completed' ORDER BY finished_at DESC LIMIT 1",
        (DEFAULT_BOUNTY_ID,),
    ).fetchone()
    if not execution:
        raise SolverAgentError("no completed solver execution to submit")
    existing = market.conn.execute(
        "SELECT * FROM solver_agent_submissions WHERE idempotency_key = ?",
        (f"solver-agent:submit:{execution['solver_id']}:{execution['bounty_id']}:{execution['candidate_commit']}",),
    ).fetchone()
    if existing:
        return {"schema": "solver-agent-submission-v1", "replayed": True, "submission": dict(existing)}
    submission = market.submit_candidate(
        bounty_id=execution["bounty_id"],
        solver_id=execution["solver_id"],
        candidate_repo_path=str(motoko_repo or Path("/home/mares/repos/motoko-issue-1-tui-input-latency")),
        candidate_commit=execution["candidate_commit"],
        idempotency_key=f"solver-agent:market-submission:{execution['solver_id']}:{execution['bounty_id']}:{execution['candidate_commit']}",
    )
    verification = market.run_verification(
        submission_id=submission["submission_id"],
        idempotency_key=f"solver-agent:verify:{execution['bounty_id']}:{execution['candidate_commit']}",
    )
    receipt = verification.get("receipt") or {}
    contract = market.conn.execute("SELECT * FROM github_issue_contracts WHERE bounty_id = ? ORDER BY updated_at DESC LIMIT 1", (execution["bounty_id"],)).fetchone()
    contract_digest = contract["contract_digest"] if contract else "missing-contract-digest"
    marker = build_submission_marker(
        bounty_id=execution["bounty_id"],
        solver_id=execution["solver_id"],
        contract_digest_value=contract_digest,
        issue_number=int(contract["issue_number"]) if contract else 1,
        base_commit=execution["base_commit"],
        candidate_commit=execution["candidate_commit"],
    )
    evidence = {
        "bounty_id": execution["bounty_id"],
        "contract_digest": contract_digest,
        "solver_id": execution["solver_id"],
        "solver_profile_version": SOLVER_PROFILE_VERSION,
        "base_commit": execution["base_commit"],
        "candidate_commit": execution["candidate_commit"],
        "changed_files": json.loads(execution["changed_files_json"]),
        "commands": json.loads(execution["commands_json"]),
        "safe_output_digest": execution["safe_output_digest"],
        "limitations": json.loads(execution["limitations_json"]),
        "estimated_cost_cents": 350,
        "verification_receipt_id": verification.get("receipt_id"),
        "verification_accepted": bool(receipt.get("accepted")),
    }
    pr_body = marker + "\n\n## Agent Bounty Evidence\n\n```json\n" + stable_json(evidence) + "\n```\n"
    client = FakeGitHubClient()
    client.create_fake_pull_request(
        repo_full_name,
        number=pr_number,
        title="Solver replay for Motoko issue #1",
        body=pr_body,
        base_ref="master",
        base_sha=execution["base_commit"],
        head_ref="solver/motoko-issue-1",
        head_sha=execution["candidate_commit"],
        user_login=execution["solver_id"],
    )
    submission_id = _stable_id("ssub", {"solver_id": execution["solver_id"], "bounty_id": execution["bounty_id"], "candidate": execution["candidate_commit"]})
    now = utc_now()
    settlement_eligible = 1 if receipt.get("accepted") is True else 0
    with market.conn:
        market.conn.execute(
            """
            INSERT INTO solver_agent_submissions(
                id, solver_id, bounty_id, execution_id, submission_id, receipt_id, repo_full_name,
                pr_number, pr_body_digest, evidence_json, status, settlement_eligible,
                created_at, updated_at, idempotency_key
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                submission_id,
                execution["solver_id"],
                execution["bounty_id"],
                execution["id"],
                submission["submission_id"],
                verification.get("receipt_id"),
                repo_full_name,
                pr_number,
                sha256_text(pr_body),
                stable_json(evidence),
                "accepted" if settlement_eligible else "rejected",
                settlement_eligible,
                now,
                now,
                f"solver-agent:submit:{execution['solver_id']}:{execution['bounty_id']}:{execution['candidate_commit']}",
            ),
        )
    update_capability_history(market, solver_id=execution["solver_id"], bounty_id=execution["bounty_id"], receipt_id=verification.get("receipt_id"), accepted=bool(receipt.get("accepted")), reward_cents=int(receipt.get("reward_cents", 2500) or 2500))
    return {"schema": "solver-agent-submission-v1", "replayed": False, "pr_number": pr_number, "evidence": evidence, "verification": verification}


def update_capability_history(
    market: AgentBountyMarket,
    *,
    solver_id: str,
    bounty_id: str,
    receipt_id: str | None,
    accepted: bool,
    reward_cents: int,
) -> dict[str, Any]:
    key = f"solver-agent:capability:{solver_id}:{bounty_id}:{receipt_id}:{accepted}"
    existing = market.conn.execute("SELECT * FROM solver_agent_capability_events WHERE idempotency_key = ?", (key,)).fetchone()
    if existing:
        return {"schema": "solver-agent-capability-update-v1", "replayed": True, "event": dict(existing)}
    skills = load_solver_skills()
    estimated_cost = 350
    now = utc_now()
    event_id = _stable_id("scap", {"solver_id": solver_id, "bounty_id": bounty_id, "receipt": receipt_id, "accepted": accepted})
    with market.conn:
        market.conn.execute(
            """
            INSERT INTO solver_agent_capability_events(
                id, solver_id, bounty_id, receipt_id, outcome, task_family, skill_versions_json,
                reward_cents, estimated_cost_cents, gross_margin_cents, created_at, idempotency_key
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                solver_id,
                bounty_id,
                receipt_id,
                "accepted" if accepted else "rejected",
                "terminal-tui",
                stable_json(skill_versions(skills)),
                reward_cents if accepted else 0,
                estimated_cost,
                (reward_cents - estimated_cost) if accepted else -estimated_cost,
                now,
                key,
            ),
        )
        market.conn.execute(
            """
            UPDATE solver_agent_profiles
            SET attempted_count = attempted_count + 1,
                accepted_count = accepted_count + ?,
                rejected_count = rejected_count + ?,
                median_cost_cents = ?,
                median_completion_seconds = ?,
                last_validation_at = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (1 if accepted else 0, 0 if accepted else 1, estimated_cost, 45 * 60, now, now, solver_id),
        )
    return {"schema": "solver-agent-capability-update-v1", "replayed": False, "event_id": event_id, "accepted": accepted}


def solver_agent_status_report() -> dict[str, Any]:
    hermes_blockers = []
    hermes_bin = default_hermes_cli()
    if not command_available(hermes_bin):
        hermes_blockers.append(f"install Hermes CLI or set {HERMES_CLI_ENV}")
    if os.environ.get(HERMES_RUN_ENV) != "1":
        hermes_blockers.append(f"set {HERMES_RUN_ENV}=1")
    solver_command = os.environ.get(HERMES_SOLVER_COMMAND_ENV) or os.environ.get(HERMES_COMMAND_ENV)
    if not solver_command:
        hermes_blockers.append(f"set {HERMES_SOLVER_COMMAND_ENV} to a reviewed solver wrapper")
    return {
        "schema": SOLVER_STATUS_SCHEMA,
        "fake_runtime_available": True,
        "hermes_runtime": {
            "available": not hermes_blockers,
            "blockers": hermes_blockers,
            "model": os.environ.get(NVIDIA_MODEL_ENV) or os.environ.get(HERMES_MODEL_ENV, "nvidia/nemotron-configured-by-hermes"),
            "runtime": "hermes-solver-cli-adapter-v1",
            "command_configured": bool(solver_command),
        },
        "openshell_nemoclaw": {
            "available": False,
            "blocker": "OpenShell/NemoClaw execution backend is not configured in this environment",
        },
        "skills_dir": str(solver_skills_dir()),
        "skills": [{"name": skill["name"], "version": skill["version"], "digest": skill["digest"]} for skill in load_solver_skills()],
    }


def run_demo_solver_motoko(market: AgentBountyMarket, *, motoko_repo: Path | None = None) -> dict[str, Any]:
    project = run_demo_project_agent_motoko(market)
    profiles = register_default_solver_profiles(market)
    evaluation = evaluate_solver_agents(market)
    claim = claim_approved_solver(market)
    execution = execute_deterministic_motoko_replay(market, solver_id=claim["solver_id"], bounty_id=claim["bounty_id"])
    live_fallback = record_live_solve_fallback(market, solver_id=claim["solver_id"], bounty_id=claim["bounty_id"])
    submission = submit_solver_replay(market, motoko_repo=motoko_repo)
    replay_submission = submit_solver_replay(market, motoko_repo=motoko_repo)
    accepted_capability_count = market.conn.execute(
        "SELECT COUNT(*) AS count FROM solver_agent_capability_events WHERE solver_id = ? AND outcome = 'accepted'",
        (claim["solver_id"],),
    ).fetchone()["count"]
    declines = [row for row in evaluation["evaluations"] if row["decision"]["decision"] == "decline"]
    return {
        "schema": "solver-agent-demo-motoko-v1",
        "ok": len(declines) >= 2 and submission["evidence"]["verification_accepted"] and replay_submission["replayed"] and int(accepted_capability_count) == 1,
        "project_agent": project,
        "profiles": profiles,
        "evaluation": evaluation,
        "claim": claim,
        "execution": execution,
        "live_fallback": live_fallback,
        "submission": submission,
        "replay_submission": replay_submission,
        "accepted_capability_events": accepted_capability_count,
        "runtime_truth": {
            "solver_runtime": "fake-solver-agent-runtime-v1",
            "execution_backend": "local-isolated-process-fallback",
            "openshell_nemoclaw_ran": False,
            "live_solve_real_issue_complete": False,
        },
    }
