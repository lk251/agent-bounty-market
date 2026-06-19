from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .util import file_digest, sha256_bytes, stable_json, utc_now


class VerificationError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProtectedVerificationResult:
    accepted: bool
    metrics: dict[str, Any]
    verifier_digest: str
    stdout_sha256: str
    stderr_sha256: str
    started_at: str
    finished_at: str
    result: dict[str, Any]
    returncode: int


def default_verifier_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "verifiers" / "motoko_issue_1"


def verifier_digest(verifier_dir: Path | None = None) -> str:
    root = verifier_dir or default_verifier_dir()
    pieces = []
    for name in ("contract.json", "README.md", "verifier.py"):
        path = root / name
        pieces.append(f"{name}:{file_digest(path)}")
    return sha256_bytes("\n".join(pieces).encode("utf-8"))


def scrubbed_env() -> dict[str, str]:
    keep: dict[str, str] = {}
    for key in ("PATH", "LANG", "LC_ALL", "TERM", "TZ"):
        value = os_environ_get(key)
        if value:
            keep[key] = value
    keep.setdefault("LANG", "C.UTF-8")
    keep.setdefault("LC_ALL", "C.UTF-8")
    return keep


def os_environ_get(key: str) -> str | None:
    import os

    return os.environ.get(key)


class ProtectedVerifierRunner:
    def __init__(self, *, verifier_dir: Path | None = None, timeout_seconds: float = 20.0, max_output_bytes: int = 2_000_000):
        self.verifier_dir = verifier_dir or default_verifier_dir()
        self.timeout_seconds = timeout_seconds
        self.max_output_bytes = max_output_bytes

    def run(
        self,
        *,
        bounty_id: str,
        motoko_repo: Path,
        base_commit: str,
        candidate_commit: str,
    ) -> ProtectedVerificationResult:
        started_at = utc_now()
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
        ]
        try:
            completed = subprocess.run(
                cmd,
                cwd=str(self.verifier_dir),
                env=scrubbed_env(),
                capture_output=True,
                timeout=self.timeout_seconds,
                check=False,
            )
            stdout = completed.stdout[: self.max_output_bytes]
            stderr = completed.stderr[: self.max_output_bytes]
            stdout_hash = sha256_bytes(stdout)
            stderr_hash = sha256_bytes(stderr)
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
            finished_at = utc_now()
            return ProtectedVerificationResult(
                accepted=accepted,
                metrics=metrics,
                verifier_digest=digest,
                stdout_sha256=stdout_hash,
                stderr_sha256=stderr_hash,
                started_at=started_at,
                finished_at=finished_at,
                result=result,
                returncode=completed.returncode,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = (exc.stdout or b"")[: self.max_output_bytes]
            stderr = (exc.stderr or b"")[: self.max_output_bytes]
            finished_at = utc_now()
            result = {
                "schema": "protected-verifier-result-v1",
                "accepted": False,
                "error": f"verifier timed out after {self.timeout_seconds:g}s",
            }
            return ProtectedVerificationResult(
                accepted=False,
                metrics={},
                verifier_digest=digest,
                stdout_sha256=sha256_bytes(stdout),
                stderr_sha256=sha256_bytes(stderr),
                started_at=started_at,
                finished_at=finished_at,
                result=result,
                returncode=124,
            )


def receipt_payload(
    *,
    bounty_id: str,
    base_commit: str,
    candidate_commit: str,
    result: ProtectedVerificationResult,
) -> dict[str, Any]:
    failure_reasons = result.result.get("failure_reasons")
    if not isinstance(failure_reasons, list):
        error = result.result.get("error")
        failure_reasons = [str(error)] if error else []
    return {
        "schema": "verification-receipt-v1",
        "bounty_id": bounty_id,
        "base_commit": base_commit,
        "candidate_commit": candidate_commit,
        "verifier_digest": result.verifier_digest,
        "accepted": result.accepted,
        "metrics": result.metrics,
        "failure_reasons": failure_reasons,
        "stdout_sha256": result.stdout_sha256,
        "stderr_sha256": result.stderr_sha256,
        "started_at": result.started_at,
        "finished_at": result.finished_at,
        "result_digest": sha256_bytes(stable_json(result.result).encode("utf-8")),
    }
