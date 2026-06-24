from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import tempfile
import time
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from .util import sha256_bytes, stable_json, utc_now

if os.name == "posix":
    import fcntl
    import pty
    import termios
else:
    fcntl = None
    pty = None
    termios = None


SENSITIVE_ENV_PREFIXES = (
    "AWS_",
    "AZURE_",
    "GCP_",
    "GITHUB_",
    "GH_",
    "OPENAI_",
    "ANTHROPIC_",
    "GOOGLE_",
    "HF_",
    "HUGGINGFACE_",
    "STRIPE_",
    "SOPS_",
    "SSH_",
)

SENSITIVE_ENV_NAMES = {
    "API_KEY",
    "AUTH_TOKEN",
    "CODEX_AUTH_TOKEN",
    "GIT_ASKPASS",
    "NETRC",
    "NPM_TOKEN",
    "PYPI_TOKEN",
    "TOKEN",
}


@dataclass(frozen=True)
class BackendResult:
    stdout: bytes
    stderr: bytes
    returncode: int
    timed_out: bool
    started_at: str
    finished_at: str
    elapsed_ms: int
    backend: str
    backend_digest: str
    policy_digest: str


class BackendUnavailable(RuntimeError):
    pass


class BackendPtySession:
    def __init__(
        self,
        *,
        master_fd: int,
        process: subprocess.Popen,
        tempdir: tempfile.TemporaryDirectory,
        backend: str,
        backend_digest: str,
        policy_digest: str,
    ):
        self.master_fd = master_fd
        self.process = process
        self._tempdir = tempdir
        self.backend = backend
        self.backend_digest = backend_digest
        self.policy_digest = policy_digest

    def close(self) -> None:
        if self.process.poll() is None:
            kill_process_group(self.process)
        with _suppress_all():
            os.close(self.master_fd)
        self._tempdir.cleanup()

    def wait(self, timeout: float | None = None) -> int:
        return self.process.wait(timeout=timeout)


class ExecutionBackend:
    name = "abstract"

    @property
    def policy(self) -> dict[str, object]:
        return {"backend": self.name}

    @property
    def policy_digest(self) -> str:
        return sha256_bytes(stable_json(self.policy).encode("utf-8"))

    @property
    def backend_digest(self) -> str:
        payload = {
            "backend": self.name,
            "policy_digest": self.policy_digest,
            "implementation": self.__class__.__name__,
        }
        return sha256_bytes(stable_json(payload).encode("utf-8"))

    def scrub_env(self, extra: Mapping[str, str] | None = None) -> dict[str, str]:
        return scrubbed_env(extra)

    def run(
        self,
        cmd: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str] | None = None,
        timeout_seconds: float,
        max_output_bytes: int,
    ) -> BackendResult:
        raise NotImplementedError

    def start_pty(
        self,
        cmd: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str] | None = None,
        timeout_seconds: float,
        rows: int = 24,
        cols: int = 120,
    ) -> BackendPtySession:
        raise NotImplementedError


def scrubbed_env(extra: Mapping[str, str] | None = None) -> dict[str, str]:
    env: dict[str, str] = {}
    for key in ("PATH", "LANG", "LC_ALL", "TERM", "TZ"):
        value = os.environ.get(key)
        if value:
            env[key] = value
    env.setdefault("LANG", "C.UTF-8")
    env.setdefault("LC_ALL", "C.UTF-8")
    if extra:
        for key, value in extra.items():
            if _is_sensitive_env_name(key):
                continue
            env[str(key)] = str(value)
    return env


def _is_sensitive_env_name(key: str) -> bool:
    upper = key.upper()
    return upper in SENSITIVE_ENV_NAMES or any(upper.startswith(prefix) for prefix in SENSITIVE_ENV_PREFIXES)


def bounded(data: bytes, limit: int) -> bytes:
    if len(data) <= limit:
        return data
    marker = f"\n[agent-bounty output truncated to {limit} bytes]\n".encode("utf-8")
    if limit <= len(marker):
        return marker[:limit]
    keep = limit - len(marker)
    return data[:keep] + marker


def _resource_preexec(timeout_seconds: float):
    def apply_limits() -> None:
        with _suppress_all():
            import resource

            cpu_limit = max(1, int(timeout_seconds) + 2)
            resource.setrlimit(resource.RLIMIT_CPU, (cpu_limit, cpu_limit + 1))
            if hasattr(resource, "RLIMIT_AS"):
                memory_limit = 4 * 1024 * 1024 * 1024
                resource.setrlimit(resource.RLIMIT_AS, (memory_limit, memory_limit))
            resource.setrlimit(resource.RLIMIT_FSIZE, (32 * 1024 * 1024, 32 * 1024 * 1024))
            resource.setrlimit(resource.RLIMIT_NOFILE, (128, 128))
            if hasattr(resource, "RLIMIT_NPROC"):
                resource.setrlimit(resource.RLIMIT_NPROC, (128, 128))

    return apply_limits


class _suppress_all:
    def __enter__(self):
        return None

    def __exit__(self, _exc_type, _exc, _tb):
        return True


class LocalIsolatedProcessBackend(ExecutionBackend):
    name = "local-isolated-process"

    def __init__(self, *, temp_root: Path | None = None):
        self.temp_root = temp_root

    @property
    def policy(self) -> dict[str, object]:
        return {
            "backend": self.name,
            "credential_policy": "scrubbed-env-deny-known-secrets",
            "process": "new-session-process-group",
            "network": "not-sandboxed",
            "stdout_stderr": "bounded",
            "resource_limits": ["cpu", "address-space", "file-size", "nofile", "nproc-where-supported"],
            "cleanup": "temporary-home-state-config-workdirs",
            "warning": "local process isolation is not a complete sandbox",
        }

    def run(
        self,
        cmd: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str] | None = None,
        timeout_seconds: float,
        max_output_bytes: int,
    ) -> BackendResult:
        started_at = utc_now()
        started = time.monotonic()
        run_env = self.scrub_env(env)
        with tempfile.TemporaryDirectory(prefix="agent-bounty-backend-", dir=str(self.temp_root) if self.temp_root else None) as tmp:
            tmp_path = Path(tmp)
            run_env.setdefault("HOME", str(tmp_path / "home"))
            run_env.setdefault("AGENT_BOUNTY_WORK", str(tmp_path / "work"))
            Path(run_env["HOME"]).mkdir(parents=True, exist_ok=True)
            Path(run_env["AGENT_BOUNTY_WORK"]).mkdir(parents=True, exist_ok=True)
            proc = subprocess.Popen(
                list(cmd),
                cwd=str(cwd),
                env=run_env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
                preexec_fn=_resource_preexec(timeout_seconds) if os.name == "posix" else None,
            )
            timed_out = False
            try:
                stdout, stderr = proc.communicate(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                timed_out = True
                kill_process_group(proc)
                stdout, stderr = proc.communicate(timeout=2.0)
            finished_at = utc_now()
            return BackendResult(
                stdout=bounded(stdout or b"", max_output_bytes),
                stderr=bounded(stderr or b"", max_output_bytes),
                returncode=124 if timed_out else int(proc.returncode or 0),
                timed_out=timed_out,
                started_at=started_at,
                finished_at=finished_at,
                elapsed_ms=int((time.monotonic() - started) * 1000),
                backend=self.name,
                backend_digest=self.backend_digest,
                policy_digest=self.policy_digest,
            )

    def start_pty(
        self,
        cmd: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str] | None = None,
        timeout_seconds: float,
        rows: int = 24,
        cols: int = 120,
    ) -> BackendPtySession:
        if pty is None:
            raise BackendUnavailable("PTY execution is only available on POSIX platforms")
        tempdir = tempfile.TemporaryDirectory(prefix="agent-bounty-backend-", dir=str(self.temp_root) if self.temp_root else None)
        tmp_path = Path(tempdir.name)
        run_env = self.scrub_env(env)
        run_env.setdefault("HOME", str(tmp_path / "home"))
        run_env.setdefault("AGENT_BOUNTY_WORK", str(tmp_path / "work"))
        Path(run_env["HOME"]).mkdir(parents=True, exist_ok=True)
        Path(run_env["AGENT_BOUNTY_WORK"]).mkdir(parents=True, exist_ok=True)
        master_fd, slave_fd = pty.openpty()
        set_winsz(slave_fd, rows, cols)
        try:
            proc = subprocess.Popen(
                list(cmd),
                cwd=str(cwd),
                env=run_env,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                close_fds=True,
                start_new_session=True,
                preexec_fn=_resource_preexec(timeout_seconds) if os.name == "posix" else None,
            )
        except Exception:
            with _suppress_all():
                os.close(master_fd)
            with _suppress_all():
                os.close(slave_fd)
            tempdir.cleanup()
            raise
        with _suppress_all():
            os.close(slave_fd)
        return BackendPtySession(
            master_fd=master_fd,
            process=proc,
            tempdir=tempdir,
            backend=self.name,
            backend_digest=self.backend_digest,
            policy_digest=self.policy_digest,
        )


def set_winsz(fd: int, rows: int, cols: int) -> None:
    if fcntl is None or termios is None:
        raise BackendUnavailable("terminal window sizing is only available on POSIX platforms")
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


def kill_process_group(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if os.name == "posix":
        with _suppress_all():
            os.killpg(proc.pid, signal.SIGTERM)
        try:
            proc.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            with _suppress_all():
                os.killpg(proc.pid, signal.SIGKILL)
    else:
        with _suppress_all():
            proc.terminate()
        try:
            proc.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            with _suppress_all():
                proc.kill()


class OpenShellBackend(ExecutionBackend):
    name = "openshell"

    def __init__(self, *, sandbox_name: str = "agent-bounty-verifier", policy_file: Path | None = None):
        self.sandbox_name = sandbox_name
        self.policy_file = policy_file if policy_file is not None else default_openshell_policy_file()

    @property
    def policy(self) -> dict[str, object]:
        policy_text = self.policy_file.read_text(encoding="utf-8") if self.policy_file and self.policy_file.exists() else ""
        return {
            "backend": self.name,
            "sandbox": self.sandbox_name,
            "network": "deny-by-default",
            "command": "openshell sandbox exec",
            "policy_sha256": sha256_bytes(policy_text.encode("utf-8")),
            "credential_policy": "credentials stay host-side",
        }

    def blocker(self) -> str | None:
        if shutil.which("openshell") is None:
            return "openshell executable not found on PATH"
        result = subprocess.run(
            ["openshell", "sandbox", "get", self.sandbox_name],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            return f"OpenShell sandbox {self.sandbox_name!r} is unavailable: {detail or 'status command failed'}"
        return None

    def run(
        self,
        cmd: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str] | None = None,
        timeout_seconds: float,
        max_output_bytes: int,
    ) -> BackendResult:
        blocker = self.blocker()
        if blocker:
            raise BackendUnavailable(blocker)
        openshell_cmd = [
            "openshell",
            "sandbox",
            "exec",
            "-n",
            self.sandbox_name,
            "--",
            "env",
            "-i",
        ]
        for key, value in self.scrub_env(env).items():
            openshell_cmd.append(f"{key}={value}")
        openshell_cmd.extend(["bash", "-lc", " ".join(_shell_quote(part) for part in cmd)])
        local = LocalIsolatedProcessBackend().run(
            openshell_cmd,
            cwd=cwd,
            env={},
            timeout_seconds=timeout_seconds,
            max_output_bytes=max_output_bytes,
        )
        return BackendResult(
            stdout=local.stdout,
            stderr=local.stderr,
            returncode=local.returncode,
            timed_out=local.timed_out,
            started_at=local.started_at,
            finished_at=local.finished_at,
            elapsed_ms=local.elapsed_ms,
            backend=self.name,
            backend_digest=self.backend_digest,
            policy_digest=self.policy_digest,
        )

    def start_pty(
        self,
        cmd: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str] | None = None,
        timeout_seconds: float,
        rows: int = 24,
        cols: int = 120,
    ) -> BackendPtySession:
        blocker = self.blocker()
        if blocker:
            raise BackendUnavailable(blocker)
        openshell_cmd = [
            "openshell",
            "sandbox",
            "exec",
            "-n",
            self.sandbox_name,
            "--",
            "env",
            "-i",
        ]
        for key, value in self.scrub_env(env).items():
            openshell_cmd.append(f"{key}={value}")
        openshell_cmd.extend(["bash", "-lc", " ".join(_shell_quote(part) for part in cmd)])
        session = LocalIsolatedProcessBackend().start_pty(
            openshell_cmd,
            cwd=cwd,
            env={},
            timeout_seconds=timeout_seconds,
            rows=rows,
            cols=cols,
        )
        session.backend = self.name
        session.backend_digest = self.backend_digest
        session.policy_digest = self.policy_digest
        return session


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def openshell_status() -> dict[str, object]:
    backend = OpenShellBackend()
    blocker = backend.blocker()
    return {
        "schema": "openshell-backend-status-v1",
        "available": blocker is None,
        "backend": backend.name,
        "backend_digest": backend.backend_digest,
        "policy_digest": backend.policy_digest,
        "sandbox": backend.sandbox_name,
        "blocker": blocker,
    }


def default_openshell_policy_file() -> Path | None:
    path = Path(__file__).resolve().parents[1] / "verifiers" / "motoko_issue_1_v2" / "openshell-policy.yaml"
    return path if path.exists() else None
