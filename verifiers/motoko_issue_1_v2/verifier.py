#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import pathlib
import re
import secrets
import select
import subprocess
import sys
import tempfile
import time
from typing import Any


CONTRACT = json.loads((pathlib.Path(__file__).with_name("contract.json")).read_text())
ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
MAX_PTY_CAPTURE_BYTES = 1_000_000
REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from agent_bounty.execution import ExecutionBackend, LocalIsolatedProcessBackend, OpenShellBackend, scrubbed_env  # noqa: E402
from agent_bounty.util import sha256_bytes, stable_json, utc_now  # noqa: E402


class VerificationFailure(RuntimeError):
    pass


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


def run_git(repo: pathlib.Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=check,
        capture_output=True,
        text=True,
    )


def resolve_commit(repo: pathlib.Path, commit: str) -> str:
    return run_git(repo, "rev-parse", "--verify", f"{commit}^{{commit}}").stdout.strip()


def assert_base_ancestor(repo: pathlib.Path, base_commit: str, candidate_commit: str) -> None:
    result = run_git(repo, "merge-base", "--is-ancestor", base_commit, candidate_commit, check=False)
    if result.returncode != 0:
        raise VerificationFailure("base commit is not an ancestor of candidate commit")


def create_worktree(repo: pathlib.Path, candidate_commit: str, parent: pathlib.Path) -> pathlib.Path:
    worktree = parent / "candidate"
    run_git(repo, "worktree", "add", "--detach", str(worktree), candidate_commit)
    return worktree


def remove_worktree(repo: pathlib.Path, worktree: pathlib.Path) -> None:
    with contextlib.suppress(Exception):
        run_git(repo, "worktree", "remove", "--force", str(worktree), check=False)


def verifier_tree_digest() -> str:
    pieces = []
    for name in ("contract.json", "README.md", "verifier.py"):
        path = pathlib.Path(__file__).with_name(name)
        pieces.append(f"{name}:{sha256_bytes(path.read_bytes())}")
    return sha256_bytes("\n".join(pieces).encode("utf-8"))


def read_available(fd: int) -> str:
    chunks = []
    deadline = time.monotonic() + 0.25
    while time.monotonic() < deadline:
        readable, _writeable, _errors = select.select([fd], [], [], 0.02)
        if not readable:
            continue
        try:
            chunks.append(os.read(fd, 65536))
        except OSError:
            break
        if sum(len(chunk) for chunk in chunks) >= MAX_PTY_CAPTURE_BYTES:
            break
    return b"".join(chunks).decode("utf-8", errors="replace")


def read_until_visible(fd: int, target: str, *, timeout: float = 2.0) -> str:
    chunks: list[bytes] = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        readable, _writeable, _errors = select.select([fd], [], [], 0.02)
        if not readable:
            continue
        try:
            chunks.append(os.read(fd, 65536))
        except OSError:
            break
        if sum(len(chunk) for chunk in chunks) >= MAX_PTY_CAPTURE_BYTES:
            break
        text = b"".join(chunks).decode("utf-8", errors="replace")
        if target in strip_ansi(text):
            return text
    return b"".join(chunks).decode("utf-8", errors="replace")


def read_pty_until(fd: int, predicate, *, timeout: float) -> tuple[str, bool]:
    chunks: list[bytes] = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        readable, _writeable, _errors = select.select([fd], [], [], 0.02)
        if not readable:
            continue
        try:
            chunks.append(os.read(fd, 65536))
        except OSError:
            break
        if sum(len(chunk) for chunk in chunks) >= MAX_PTY_CAPTURE_BYTES:
            break
        text = b"".join(chunks).decode("utf-8", errors="replace")
        if predicate(strip_ansi(text)):
            return text, True
    return b"".join(chunks).decode("utf-8", errors="replace"), False


def wait_for_prefixes(fd: int, *, prefixes: list[str], injected_at: list[float], timeout: float = 3.0) -> tuple[list[float], str]:
    seen: dict[int, float] = {}
    chunks: list[bytes] = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and len(seen) < len(prefixes):
        readable, _writeable, _errors = select.select([fd], [], [], 0.02)
        if not readable:
            continue
        now_value = time.monotonic()
        try:
            chunks.append(os.read(fd, 65536))
        except OSError:
            break
        if sum(len(chunk) for chunk in chunks) >= MAX_PTY_CAPTURE_BYTES:
            break
        visible = strip_ansi(b"".join(chunks).decode("utf-8", errors="replace"))
        for idx, prefix in enumerate(prefixes):
            if idx not in seen and prefix in visible:
                seen[idx] = max(0.0, now_value - injected_at[idx])
    output = b"".join(chunks).decode("utf-8", errors="replace")
    return [seen[idx] for idx in range(len(prefixes)) if idx in seen], output


def percentile_ms(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = int(round((len(ordered) - 1) * (percentile / 100.0)))
    return round(ordered[max(0, min(len(ordered) - 1, idx))] * 1000.0, 3)


def make_measurement_text(nonce: str) -> str:
    samples = int(CONTRACT["samples"])
    base = f"nonce {nonce} ascii latency Café mañana résumé 東京界 Привет alpha beta "
    text = (base * ((samples // len(base)) + 2))[:samples]
    if len(text) != samples or nonce[:8] not in text or not any(ord(char) > 127 for char in text):
        raise VerificationFailure("measurement fixture is invalid")
    return text


def scenario_metrics(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "samples": int(row.get("samples", 0) or 0),
        "p50_ms": float(row.get("p50_ms", 0.0) or 0.0),
        "p95_ms": float(row.get("p95_ms", 0.0) or 0.0),
        "max_ms": float(row.get("max_ms", 0.0) or 0.0),
        "transcript_iterations": int(row.get("transcript_iterations", 0) or 0),
    }


def background_metrics(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "phase": str(row.get("phase", "")),
        "samples": int(row.get("samples", 0) or 0),
        "p50_ms": float(row.get("p50_ms", 0.0) or 0.0),
        "p95_ms": float(row.get("p95_ms", 0.0) or 0.0),
        "max_ms": float(row.get("max_ms", 0.0) or 0.0),
        "longest_stall_ms": float(row.get("longest_stall_ms", 0.0) or 0.0),
        "visible_before_phase_end": bool(row.get("visible_before_phase_end")),
        "input_integrity": bool(row.get("input_integrity")),
        "background_completed": bool(row.get("background_completed")),
        "artifact_integrity": bool(row.get("artifact_integrity")),
    }


def latency_driver_source() -> str:
    return r'''
from __future__ import annotations
import collections
import importlib.machinery
import importlib.util
import pathlib
import sys


class CountingMessageList(list):
    def __init__(self, rows=()):
        super().__init__(rows)
        self.iterations = 0

    def __iter__(self):
        self.iterations += len(self)
        return super().__iter__()


def load_candidate(worktree: pathlib.Path):
    source = worktree / "motoko"
    if not source.exists():
        raise RuntimeError("candidate checkout has no motoko executable")
    sys.path.insert(0, str(worktree))
    loader = importlib.machinery.SourceFileLoader("candidate_motoko_child", str(source))
    spec = importlib.util.spec_from_loader("candidate_motoko_child", loader)
    if spec is None:
        raise RuntimeError("cannot construct candidate module spec")
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def main() -> int:
    worktree = pathlib.Path(sys.argv[1])
    title = sys.argv[2]
    transcript_pairs = int(sys.argv[3])
    m = load_candidate(worktree)
    conv = m.new_conversation(title)
    ui = m.MotokoTui(conv)
    ui.stdin_fd = 0
    ui.stdout_fd = 1
    ui.start_study_loop = lambda: None
    ui.start_maintenance = lambda *args, **kwargs: None
    ui.resume_maintenance_on_start = False
    ui.pending_prompts = collections.deque()
    ui.report_running = 0
    ui.foreground_running = 0
    ui.maintaining = False
    ui.study_running = False
    ui.cwd_indexing = False
    ui.index_progress = None
    ui.status = "ready"
    ui.input_buffer = ""
    ui.cursor = 0
    ui.dropdown_index = 0
    rows = []
    for idx in range(transcript_pairs):
        rows.append({"role": "user", "content": f"transcript user row {idx}"})
        rows.append({"role": "assistant", "content": f"transcript answer row {idx}"})
    ui.messages = CountingMessageList(rows or [{"role": "system", "content": "empty transcript probe"}])
    ui.rendered_message_ids = set()
    ui.bottom_rows_rendered = 0
    ui.bottom_cursor_row_offset = 0
    ui.bottom_frame_key = None
    ui.answer_stream_width = 0
    ui.answer_stream_emitted_lines = 0
    ui.generating = False
    ui.answer_phase = ""
    ui.answer_entry = None
    ui.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def run_latency_probe(
    backend: ExecutionBackend,
    worktree: pathlib.Path,
    *,
    name: str,
    text: str,
    transcript_pairs: int,
) -> dict[str, Any]:
    errors: list[str] = []
    session = None
    try:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            driver_path = tmp_path / "latency_driver.py"
            driver_path.write_text(latency_driver_source(), encoding="utf-8")
            state_dir = tmp_path / "state"
            config_dir = tmp_path / "config"
            env = scrubbed_env(
                {
                    "HOME": str(tmp_path / "home"),
                    "MOTOKO_STATE_HOME": str(state_dir),
                    "MOTOKO_CONFIG_HOME": str(config_dir),
                    "MOTOKO_BACKGROUND_STUDY": "0",
                    "MOTOKO_BACKGROUND_PROFILE": "0",
                    "MOTOKO_TUI_INPUT_BATCH_LIMIT": "64",
                    "MOTOKO_TUI": "1",
                    "TERM": "xterm-256color",
                    "PYTHONUNBUFFERED": "1",
                }
            )
            session = backend.start_pty(
                [sys.executable, str(driver_path), str(worktree), f"Protected Latency {name}", str(transcript_pairs)],
                cwd=str(tmp_path),
                env=env,
                timeout_seconds=8.0,
                rows=18,
                cols=140,
            )
            master_fd = session.master_fd
            initial = read_until_visible(master_fd, f"Protected Latency {name}", timeout=4.0)
            if f"Protected Latency {name}" not in strip_ansi(initial):
                errors.append("initial render did not become visible")
            injected_at: list[float] = []
            prefixes: list[str] = []
            for idx, char in enumerate(text):
                injected_at.append(time.monotonic())
                os.write(master_fd, char.encode("utf-8"))
                prefixes.append(text[: idx + 1])
            observed_latencies, observed_output = wait_for_prefixes(master_fd, prefixes=prefixes, injected_at=injected_at)
            observed_output += read_available(master_fd)
            visible_output = strip_ansi(initial + observed_output)
            final_input = text if text in visible_output else ""
            if final_input != text:
                errors.append("final composer contents were not observed")
            if len(observed_latencies) != len(text):
                errors.append(f"latency samples missing: {len(observed_latencies)}/{len(text)}")
            with contextlib.suppress(OSError):
                os.write(master_fd, b"\x03")
            with contextlib.suppress(Exception):
                session.wait(timeout=2.0)
            return {
                "name": name,
                "final_input": final_input,
                "expected_input": text,
                "p50_ms": percentile_ms(observed_latencies, 50),
                "p95_ms": percentile_ms(observed_latencies, 95),
                "max_ms": round((max(observed_latencies) if observed_latencies else 0.0) * 1000.0, 3),
                "samples": len(observed_latencies),
                "transcript_iterations": 0,
                "output_contains_final": text in visible_output,
                "backend": session.backend,
                "backend_digest": session.backend_digest,
                "policy_digest": session.policy_digest,
                "errors": errors,
            }
    finally:
        if session is not None:
            session.close()


def write_json(path: pathlib.Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def source_fingerprint(path: pathlib.Path) -> dict[str, str]:
    return {"sha256": sha256_hex(path.read_bytes())}


def index_path(state_dir: pathlib.Path, index_id: str) -> pathlib.Path:
    return state_dir / "indexes" / f"{index_id}.json"


def build_background_study_fixture(
    tmp_root: pathlib.Path,
    state_dir: pathlib.Path,
    *,
    nonce: str,
    file_count: int = 20,
    chunks_per_file: int = 2,
    headings_per_chunk: int = 10,
) -> dict:
    docs = tmp_root / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    index_id = "20260621-000000-badfed"
    files = []
    for file_idx in range(file_count):
        chunks = []
        file_parts = []
        source = docs / f"background-{file_idx:04d}.org"
        for chunk_idx in range(chunks_per_file):
            lines = []
            for heading_idx in range(headings_per_chunk):
                ordinal = file_idx * chunks_per_file * headings_per_chunk + chunk_idx * headings_per_chunk + heading_idx
                lines.extend(
                    [
                        f"* [2026-06-{(ordinal % 28) + 1:02d} Mon 10:{ordinal % 60:02d}] Synthetic background day {ordinal}",
                        "** do",
                        f"*** TODO Preserve responsive typing during evidence build {ordinal} :latency:",
                        "** log",
                        (
                            "This deterministic fixture exists only to keep the real background "
                            f"evidence-store code busy while the PTY verifier types into Motoko. Nonce {nonce}."
                        ),
                    ]
                )
            content = "\n".join(lines) + "\n"
            file_parts.append(content)
            chunks.append(
                {
                    "chunk": chunk_idx + 1,
                    "summary": f"Synthetic background evidence chunk {file_idx}-{chunk_idx}.",
                    "content": content,
                    "content_sha256": sha256_hex(content.encode("utf-8")),
                    "content_bytes": len(content.encode("utf-8")),
                }
            )
        source.write_text("".join(file_parts), encoding="utf-8")
        files.append(
            {
                "path": str(source),
                "source_fingerprint": source_fingerprint(source),
                "summary": "Synthetic background-study latency fixture.",
                "chunks": chunks,
            }
        )
    index = {
        "id": index_id,
        "name": "background-study-latency",
        "root": str(docs),
        "glob": "*.org",
        "created": utc_now(),
        "verifier_nonce": nonce,
        "files": files,
    }
    write_json(index_path(state_dir, index_id), index)
    return index


def observe_child_prompt_latency(
    fd: int,
    *,
    text: str,
    phase_end_markers: tuple[str, ...],
    timeout: float,
) -> dict[str, Any]:
    prefixes = [text[: idx + 1] for idx in range(len(text))]
    injected_at: list[float] = []
    seen: dict[int, float] = {}
    chunks: list[bytes] = []
    phase_end_seen_at: float | None = None
    first_prefix_at: float | None = None
    last_visible_change = time.monotonic()
    longest_stall = 0.0

    for char in text:
        injected_at.append(time.monotonic())
        os.write(fd, char.encode("utf-8"))

    deadline = time.monotonic() + timeout
    last_visible = ""
    while time.monotonic() < deadline and (len(seen) < len(prefixes) or phase_end_seen_at is None):
        readable, _writeable, _errors = select.select([fd], [], [], 0.02)
        now_value = time.monotonic()
        if not readable:
            longest_stall = max(longest_stall, now_value - last_visible_change)
            continue
        try:
            chunks.append(os.read(fd, 65536))
        except OSError:
            break
        visible = strip_ansi(b"".join(chunks).decode("utf-8", errors="replace"))
        if visible != last_visible:
            longest_stall = max(longest_stall, now_value - last_visible_change)
            last_visible_change = now_value
            last_visible = visible
        if phase_end_seen_at is None and any(marker in visible for marker in phase_end_markers):
            phase_end_seen_at = now_value
        for idx, prefix in enumerate(prefixes):
            if idx not in seen and prefix in visible:
                seen[idx] = max(0.0, now_value - injected_at[idx])
                if first_prefix_at is None:
                    first_prefix_at = now_value
    output = b"".join(chunks).decode("utf-8", errors="replace")
    latencies = [seen[idx] for idx in range(len(prefixes)) if idx in seen]
    return {
        "latencies": latencies,
        "output": output,
        "visible_text": strip_ansi(output),
        "phase_end_seen": phase_end_seen_at is not None,
        "visible_before_phase_end": (
            first_prefix_at is not None
            and (phase_end_seen_at is None or first_prefix_at <= phase_end_seen_at)
        ),
        "longest_stall_ms": round(longest_stall * 1000.0, 3),
    }


def evidence_artifact_integrity(state_dir: pathlib.Path) -> bool:
    paths = list((state_dir / "evidence-stores").glob("*.json"))
    if not paths:
        return False
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return False
        if not isinstance(data, dict):
            return False
        text = json.dumps(data, sort_keys=True)
        if "background-study-latency" in text and "Synthetic background" in text:
            return True
    return False


def wait_for_background_artifact(state_dir: pathlib.Path, fd: int, *, timeout: float = 5.0) -> tuple[bool, str]:
    chunks: list[bytes] = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if evidence_artifact_integrity(state_dir):
            return True, b"".join(chunks).decode("utf-8", errors="replace")
        readable, _writeable, _errors = select.select([fd], [], [], 0.05)
        if not readable:
            continue
        try:
            chunks.append(os.read(fd, 65536))
        except OSError:
            break
    return evidence_artifact_integrity(state_dir), b"".join(chunks).decode("utf-8", errors="replace")


def run_background_study_latency_probe(
    backend: ExecutionBackend,
    worktree: pathlib.Path,
    *,
    text: str,
    nonce: str,
    width: int = 140,
) -> dict[str, Any]:
    session = None
    errors: list[str] = []
    try:
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = pathlib.Path(tmp_name)
            state_dir = tmp / "state"
            config_dir = tmp / "config"
            build_background_study_fixture(tmp, state_dir, nonce=nonce)
            env = scrubbed_env(
                {
                    "HOME": str(tmp / "home"),
                    "MOTOKO_STATE_HOME": str(state_dir),
                    "MOTOKO_CONFIG_HOME": str(config_dir),
                    "MOTOKO_TUI": "1",
                    "TERM": "xterm-256color",
                    "MOTOKO_BACKGROUND_STUDY": "1",
                    "MOTOKO_BACKGROUND_STUDY_INTERVAL": "1",
                    "MOTOKO_BACKGROUND_STUDY_IDLE_GRACE": "1",
                    "MOTOKO_BACKGROUND_INDEX_ENRICH": "0",
                    "MOTOKO_BACKGROUND_HEAVY_INDEX": "0",
                    "MOTOKO_BACKGROUND_INDEX_CLEANUP": "0",
                    "MOTOKO_BACKGROUND_INDEX_REPAIR": "0",
                    "MOTOKO_BACKGROUND_VECTOR_REFRESH": "0",
                    "MOTOKO_BACKGROUND_PROFILE": "0",
                    "MOTOKO_BACKGROUND_EVIDENCE_REFRESH": "1",
                    "MOTOKO_BACKGROUND_EVIDENCE_REFRESH_LIMIT": "1",
                    "MOTOKO_TUI_INPUT_BATCH_LIMIT": "64",
                }
            )
            session = backend.start_pty(
                [sys.executable, str(worktree / "motoko"), "chat", "--title", "Background Study Latency"],
                cwd=str(tmp),
                env=env,
                timeout_seconds=30.0,
                rows=24,
                cols=width,
            )
            master_fd = session.master_fd
            initial, ready = read_pty_until(master_fd, lambda visible: "Background Study Latency" in visible, timeout=5.0)
            if not ready:
                errors.append("child TUI did not render initial conversation title")
            phase_output, phase_seen = read_pty_until(
                master_fd,
                lambda visible: "study: evidence-store" in visible,
                timeout=12.0,
            )
            cumulative_before_input = strip_ansi(initial + phase_output)
            phase_seen = phase_seen or "study: evidence-store" in cumulative_before_input
            if not phase_seen:
                errors.append("background study evidence-store phase was not observed")
            observed = observe_child_prompt_latency(
                master_fd,
                text=text,
                phase_end_markers=("study: idle", "evidence store(s) refreshed", "catalog fresh"),
                timeout=20.0,
            )
            completed, completion_output = wait_for_background_artifact(state_dir, master_fd, timeout=5.0)
            final_visible = strip_ansi(initial + phase_output + observed["output"] + completion_output)
            if len(observed["latencies"]) != len(text):
                errors.append(f"background latency samples missing: {len(observed['latencies'])}/{len(text)}")
            if text not in final_visible:
                errors.append("background composer final text was not observed")
            if not observed["visible_before_phase_end"]:
                errors.append("typed text was not visible before background phase ended")
            if not completed:
                errors.append("background evidence store was not written or failed integrity checks")
            with contextlib.suppress(OSError):
                os.write(master_fd, b"\x03")
            try:
                session.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(Exception):
                    session.close()
            latencies = observed["latencies"]
            return {
                "phase": "study: evidence-store",
                "samples": len(latencies),
                "p50_ms": percentile_ms(latencies, 50),
                "p95_ms": percentile_ms(latencies, 95),
                "max_ms": round((max(latencies) if latencies else 0.0) * 1000.0, 3),
                "longest_stall_ms": observed["longest_stall_ms"],
                "visible_before_phase_end": observed["visible_before_phase_end"],
                "input_integrity": text in final_visible,
                "background_completed": completed,
                "artifact_integrity": completed,
                "backend": session.backend,
                "backend_digest": session.backend_digest,
                "policy_digest": session.policy_digest,
                "errors": errors,
            }
    finally:
        if session is not None:
            session.close()


def backend_for(name: str):
    if name == "local-isolated-process":
        return LocalIsolatedProcessBackend()
    if name == "openshell":
        return OpenShellBackend()
    raise VerificationFailure(f"unknown execution backend {name!r}")


def verify_candidate(repo: pathlib.Path, base_commit: str, candidate_commit: str, bounty_id: str, *, backend_name: str) -> dict[str, Any]:
    resolved_base = resolve_commit(repo, base_commit)
    resolved_candidate = resolve_commit(repo, candidate_commit)
    expected_base = CONTRACT.get("baseline_commit")
    if expected_base and not resolved_base.startswith(str(expected_base)):
        raise VerificationFailure("base commit does not match verifier contract")
    assert_base_ancestor(repo, resolved_base, resolved_candidate)
    backend = backend_for(backend_name)
    if isinstance(backend, OpenShellBackend):
        blocker = backend.blocker()
        if blocker:
            raise VerificationFailure(f"OpenShell unavailable: {blocker}")
    nonce = secrets.token_hex(8)
    text = make_measurement_text(nonce)
    background_text = f"bg {nonce} Café mañana résumé 東京界 Привет "
    before_digest = verifier_tree_digest()
    with tempfile.TemporaryDirectory(prefix="motoko-issue-1-v2-verifier-") as tmp:
        tmp_path = pathlib.Path(tmp)
        worktree = create_worktree(repo, resolved_candidate, tmp_path)
        try:
            run_latency_probe(backend, worktree, name="warmup", text=text[:32], transcript_pairs=2)
            short = run_latency_probe(backend, worktree, name="short", text=text, transcript_pairs=3)
            long = run_latency_probe(backend, worktree, name="long", text=text, transcript_pairs=900)
            background = run_background_study_latency_probe(backend, worktree, text=background_text, nonce=nonce)
        finally:
            remove_worktree(repo, worktree)
    after_digest = verifier_tree_digest()

    failure_reasons: list[str] = []
    if before_digest != after_digest:
        failure_reasons.append("platform verifier files changed during candidate execution")
    for label, row in (("short_transcript", short), ("long_transcript", long)):
        if row.get("errors"):
            failure_reasons.append(f"{label}: verifier scenario reported errors")
        if row.get("final_input") != text or row.get("expected_input") != text:
            failure_reasons.append(f"{label}: final composer contents did not match expected input")
        if row.get("output_contains_final") is not True:
            failure_reasons.append(f"{label}: final composer output was not observed")
        if int(row.get("samples", 0) or 0) != len(text):
            failure_reasons.append(f"{label}: expected {len(text)} latency samples")
        if int(row.get("transcript_iterations", 0) or 0) != 0:
            failure_reasons.append(f"{label}: ordinary input scanned transcript rows")
    unicode_fragments = ("Café", "mañana", "résumé", "東京", "界", "Привет")
    if not all(fragment in short.get("final_input", "") for fragment in unicode_fragments):
        failure_reasons.append("short_transcript unicode integrity failed")
    if not all(fragment in long.get("final_input", "") for fragment in unicode_fragments):
        failure_reasons.append("long_transcript unicode integrity failed")
    if nonce[:8] not in short.get("final_input", "") or nonce[:8] not in long.get("final_input", ""):
        failure_reasons.append("randomized nonce was not preserved in idle probes")
    short_metrics = scenario_metrics(short)
    long_metrics = scenario_metrics(long)
    if short_metrics["p95_ms"] > float(CONTRACT["short_p95_limit_ms"]):
        failure_reasons.append("short_transcript p95 exceeded contract")
    if long_metrics["p95_ms"] > float(CONTRACT["long_p95_limit_ms"]):
        failure_reasons.append("long_transcript p95 exceeded contract")
    if long_metrics["p95_ms"] - short_metrics["p95_ms"] > float(CONTRACT["max_long_minus_short_p95_ms"]):
        failure_reasons.append("long transcript materially increased p95 latency")

    background_report = background_metrics(background)
    if background.get("errors"):
        failure_reasons.append("background_study: verifier scenario reported errors")
    if background_report["phase"] != "study: evidence-store":
        failure_reasons.append("background_study: evidence-store phase was not observed")
    if background_report["samples"] != len(background_text):
        failure_reasons.append(f"background_study: expected {len(background_text)} latency samples")
    if not background_report["visible_before_phase_end"]:
        failure_reasons.append("background_study: input was withheld until the background phase ended")
    if not background_report["input_integrity"]:
        failure_reasons.append("background_study: exact input integrity failed")
    if not background_report["background_completed"]:
        failure_reasons.append("background_study: synthetic evidence-store work did not complete")
    if not background_report["artifact_integrity"]:
        failure_reasons.append("background_study: synthetic evidence-store artifact failed integrity checks")
    if background_report["p95_ms"] > float(CONTRACT["background_p95_limit_ms"]):
        failure_reasons.append("background_study p95 exceeded contract")
    if background_report["max_ms"] > float(CONTRACT["background_max_limit_ms"]):
        failure_reasons.append("background_study max exceeded contract")
    if background_report["longest_stall_ms"] > float(CONTRACT["background_stall_limit_ms"]):
        failure_reasons.append("background_study visible-progress stall exceeded contract")

    accepted = not failure_reasons
    return {
        "schema": "protected-verifier-result-v2",
        "verifier_id": CONTRACT["verifier_id"],
        "verifier_version": CONTRACT["verifier_version"],
        "bounty_id": bounty_id,
        "base_commit": resolved_base,
        "candidate_commit": resolved_candidate,
        "backend": backend.name,
        "backend_digest": backend.backend_digest,
        "policy_digest": backend.policy_digest,
        "verifier_self_digest_before": before_digest,
        "verifier_self_digest_after": after_digest,
        "challenge_nonce_sha256": sha256_bytes(nonce.encode("utf-8")),
        "accepted": accepted,
        "metrics": {
            "short_transcript": short_metrics,
            "long_transcript": long_metrics,
            "background_study": background_report,
        },
        "failure_reasons": failure_reasons,
    }


def rejected(reason: str, *, bounty_id: str = "", base_commit: str = "", candidate_commit: str = "") -> dict[str, Any]:
    return {
        "schema": "protected-verifier-result-v2",
        "verifier_id": CONTRACT["verifier_id"],
        "verifier_version": CONTRACT["verifier_version"],
        "bounty_id": bounty_id,
        "base_commit": base_commit,
        "candidate_commit": candidate_commit,
        "accepted": False,
        "metrics": {},
        "failure_reasons": [reason],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Protected verifier v2 for Motoko issue #1")
    parser.add_argument("--bounty-id", required=True)
    parser.add_argument("--candidate-repo", required=True)
    parser.add_argument("--base-commit", required=True)
    parser.add_argument("--candidate-commit", required=True)
    parser.add_argument("--backend", default="local-isolated-process")
    args = parser.parse_args(argv)
    try:
        result = verify_candidate(
            pathlib.Path(args.candidate_repo).resolve(),
            args.base_commit,
            args.candidate_commit,
            args.bounty_id,
            backend_name=args.backend,
        )
    except Exception as exc:
        result = rejected(f"{type(exc).__name__}: {exc}", bounty_id=args.bounty_id, base_commit=args.base_commit, candidate_commit=args.candidate_commit)
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result.get("accepted") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
