from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .execution import ExecutionBackend, LocalIsolatedProcessBackend
from .util import file_digest, sha256_bytes, stable_json, utc_now


class VerificationError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProtectedVerificationResult:
    accepted: bool
    metrics: dict[str, Any]
    verifier_digest: str
    backend: str
    backend_digest: str
    policy_digest: str
    stdout_sha256: str
    stderr_sha256: str
    started_at: str
    finished_at: str
    result: dict[str, Any]
    returncode: int


def default_verifier_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "verifiers" / "motoko_issue_1_v2"


def verifier_digest(verifier_dir: Path | None = None) -> str:
    root = verifier_dir or default_verifier_dir()
    pieces = []
    for name in ("contract.json", "README.md", "verifier.py"):
        path = root / name
        pieces.append(f"{name}:{file_digest(path)}")
    return sha256_bytes("\n".join(pieces).encode("utf-8"))


class ProtectedVerifierRunner:
    def __init__(
        self,
        *,
        verifier_dir: Path | None = None,
        timeout_seconds: float = 20.0,
        max_output_bytes: int = 2_000_000,
        backend: ExecutionBackend | None = None,
    ):
        self.verifier_dir = verifier_dir or default_verifier_dir()
        self.timeout_seconds = timeout_seconds
        self.max_output_bytes = max_output_bytes
        self.backend = backend or LocalIsolatedProcessBackend()

    def run(
        self,
        *,
        bounty_id: str,
        motoko_repo: Path,
        base_commit: str,
        candidate_commit: str,
    ) -> ProtectedVerificationResult:
        script = self.verifier_dir / "verifier.py"
        digest = verifier_digest(self.verifier_dir)
        cmd = [
            sys.executable,
            str(script),
            "--bounty-id",
            bounty_id,
            "--candidate-repo",
            str(motoko_repo),
            "--base-commit",
            base_commit,
            "--candidate-commit",
            candidate_commit,
            "--backend",
            self.backend.name,
        ]
        completed = self.backend.run(
            cmd,
            cwd=self.verifier_dir,
            env={},
            timeout_seconds=self.timeout_seconds,
            max_output_bytes=self.max_output_bytes,
        )
        stdout = completed.stdout[: self.max_output_bytes]
        stderr = completed.stderr[: self.max_output_bytes]
        stdout_hash = sha256_bytes(stdout)
        stderr_hash = sha256_bytes(stderr)
        if completed.timed_out:
            result = {
                "schema": "protected-verifier-result-v1",
                "accepted": False,
                "error": f"verifier timed out after {self.timeout_seconds:g}s",
            }
            return ProtectedVerificationResult(
                accepted=False,
                metrics={},
                verifier_digest=digest,
                backend=completed.backend,
                backend_digest=completed.backend_digest,
                policy_digest=completed.policy_digest,
                stdout_sha256=sha256_bytes(stdout),
                stderr_sha256=sha256_bytes(stderr),
                started_at=completed.started_at,
                finished_at=completed.finished_at,
                result=result,
                returncode=124,
            )
        try:
            text = stdout.decode("utf-8")
            result = json.loads(text)
        except Exception as exc:
            result = {
                "schema": "protected-verifier-result-v1",
                "accepted": False,
                "error": f"malformed verifier JSON: {type(exc).__name__}",
            }
        if not isinstance(result, dict):
            result = {
                "schema": "protected-verifier-result-v1",
                "accepted": False,
                "error": "malformed verifier JSON: root was not an object",
            }
        accepted = completed.returncode == 0 and result.get("accepted") is True
        metrics = result.get("metrics")
        if not isinstance(metrics, dict):
            metrics = {}
        backend = str(result.get("backend") or completed.backend)
        backend_digest = str(result.get("backend_digest") or completed.backend_digest)
        policy_digest = str(result.get("policy_digest") or completed.policy_digest)
        return ProtectedVerificationResult(
            accepted=accepted,
            metrics=metrics,
            verifier_digest=digest,
            backend=backend,
            backend_digest=backend_digest,
            policy_digest=policy_digest,
            stdout_sha256=stdout_hash,
            stderr_sha256=stderr_hash,
            started_at=completed.started_at,
            finished_at=completed.finished_at,
            result=result,
            returncode=completed.returncode,
        )


def receipt_payload(
    *,
    bounty_id: str,
    project_id: str,
    issue_ref: str,
    submission_id: str,
    solver_id: str,
    candidate_repo_path: str,
    verifier_id: str,
    base_commit: str,
    candidate_commit: str,
    result: ProtectedVerificationResult,
) -> dict[str, Any]:
    failure_reasons = result.result.get("failure_reasons")
    if not isinstance(failure_reasons, list):
        error = result.result.get("error")
        failure_reasons = [str(error)] if error else []
    return {
        "schema": "verification-receipt-v2",
        "bounty_id": bounty_id,
        "project_id": project_id,
        "issue_ref": issue_ref,
        "submission_id": submission_id,
        "solver_id": solver_id,
        "candidate_repo_path": candidate_repo_path,
        "verifier_id": verifier_id,
        "verifier_name": result.result.get("verifier_id") or verifier_id,
        "verifier_version": result.result.get("verifier_version"),
        "base_commit": base_commit,
        "candidate_commit": candidate_commit,
        "verifier_digest": result.verifier_digest,
        "backend": result.backend,
        "backend_digest": result.backend_digest,
        "policy_digest": result.policy_digest,
        "accepted": result.accepted,
        "metrics": result.metrics,
        "failure_reasons": failure_reasons,
        "stdout_sha256": result.stdout_sha256,
        "stderr_sha256": result.stderr_sha256,
        "started_at": result.started_at,
        "finished_at": result.finished_at,
        "result_digest": sha256_bytes(stable_json(result.result).encode("utf-8")),
    }
