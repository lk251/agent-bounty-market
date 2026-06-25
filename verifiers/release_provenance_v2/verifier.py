#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any


CONTRACT = json.loads((pathlib.Path(__file__).with_name("contract.json")).read_text(encoding="utf-8"))
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
RC_RE = re.compile(r"hackathon-mixed-rc[0-9]+")


class VerificationFailure(RuntimeError):
    pass


def run(cmd: list[str], *, cwd: pathlib.Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if check and completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "command failed").strip()
        raise VerificationFailure(f"{' '.join(cmd)} failed: {detail[:4000]}")
    return completed


def git(repo: pathlib.Path, *args: str, check: bool = True) -> str:
    return run(["git", "-C", str(repo), *args], cwd=repo, check=check).stdout.strip()


def clone_candidate(source: pathlib.Path, candidate_commit: str, parent: pathlib.Path) -> pathlib.Path:
    clone = parent / "candidate"
    run(["git", "clone", "--no-hardlinks", "--quiet", str(source), str(clone)], cwd=parent)
    git(clone, "checkout", "--quiet", candidate_commit)
    git(clone, "config", "user.email", "release-verifier@example.invalid")
    git(clone, "config", "user.name", "Release Verifier")
    return clone


def assert_base_ancestor(repo: pathlib.Path, base_commit: str, candidate_commit: str) -> None:
    if not base_commit or not SHA_RE.match(candidate_commit):
        raise VerificationFailure("candidate commit must be a 40-character lowercase Git SHA")
    result = run(["git", "-C", str(repo), "merge-base", "--is-ancestor", base_commit, candidate_commit], cwd=repo, check=False)
    if result.returncode != 0:
        raise VerificationFailure("base commit is not an ancestor of candidate commit")


def read_json(path: pathlib.Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise VerificationFailure(f"{path} must contain a JSON object")
    return value


def assert_manifest_v2(repo: pathlib.Path) -> dict[str, Any]:
    manifest = read_json(repo / "submission" / "RELEASE_MANIFEST.json")
    if manifest.get("schema") != "agent-bounty-release-manifest-v2":
        raise VerificationFailure("release manifest must use schema v2")
    if "commit_sha" in manifest:
        raise VerificationFailure("release manifest must not contain commit_sha")
    tag = manifest.get("release_tag")
    if not isinstance(tag, str) or not RC_RE.fullmatch(tag):
        raise VerificationFailure("release manifest release_tag must name an RC tag")
    for key in ("bundle_digest", "attestation_digest", "truth_matrix_digest"):
        value = manifest.get(key)
        if not isinstance(value, str) or not value.startswith("sha256:"):
            raise VerificationFailure(f"{key} must be a sha256 digest")
    if manifest.get("truth_status") != "Mixed real/fallback":
        raise VerificationFailure("truth_status must remain Mixed real/fallback")
    return manifest


def assert_no_hardcoded_rc_in_code_or_tests(repo: pathlib.Path) -> int:
    hits: list[str] = []
    for base in (repo / "agent_bounty", repo / "tests"):
        for path in sorted(base.rglob("*.py")):
            text = path.read_text(encoding="utf-8", errors="replace")
            for match in RC_RE.finditer(text):
                hits.append(f"{path.relative_to(repo)}:{match.group(0)}")
    if hits:
        raise VerificationFailure("current RC tag is hard-coded in production/tests: " + ", ".join(hits[:12]))
    return len(hits)


def command_json(repo: pathlib.Path, *args: str, check: bool = True) -> dict[str, Any]:
    completed = run([sys.executable, "-m", "agent_bounty", *args], cwd=repo, check=check)
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise VerificationFailure(f"command did not emit JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise VerificationFailure("command JSON root must be an object")
    return value


def assert_release_commands(repo: pathlib.Path, release_tag: str) -> dict[str, Any]:
    audit = command_json(repo, "release-audit")
    if audit.get("ok") is not True:
        raise VerificationFailure(f"release-audit failed: {audit.get('errors')}")
    tag_message = run([sys.executable, "-m", "agent_bounty", "release-provenance", "render-tag-message", "--tag", release_tag], cwd=repo).stdout
    payload = json.loads(tag_message)
    if payload.get("schema") != "agent-bounty-release-tag-provenance-v1":
        raise VerificationFailure("tag message schema mismatch")
    if payload.get("release_tag") != release_tag:
        raise VerificationFailure("tag message release tag mismatch")
    if payload.get("target_authority") != "git annotated tag object; not a self-referential committed manifest field":
        raise VerificationFailure("tag message does not state tag authority")
    message_path = repo / ".release-tag-message.json"
    message_path.write_text(tag_message, encoding="utf-8")
    run(["git", "tag", "-a", release_tag, "-F", str(message_path)], cwd=repo)
    tagged = command_json(repo, "release-audit", "--tag", release_tag)
    if tagged.get("ok") is not True:
        raise VerificationFailure(f"release-audit --tag failed: {tagged.get('errors')}")
    run(["git", "tag", "lightweight-verifier-tag"], cwd=repo)
    lightweight = command_json(repo, "release-audit", "--tag", "lightweight-verifier-tag", check=False)
    if lightweight.get("ok") is True or "tag_not_annotated" not in {err.get("code") for err in lightweight.get("errors", [])}:
        raise VerificationFailure("lightweight tag was not rejected")
    manifest_path = repo / "submission" / "RELEASE_MANIFEST.json"
    manifest = read_json(manifest_path)
    manifest["source_baseline_note"] = "stale verifier mutation"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    stale = command_json(repo, "release-audit", "--tag", release_tag, check=False)
    if stale.get("ok") is True or "tag_message_digest_mismatch" not in {err.get("code") for err in stale.get("errors", [])}:
        raise VerificationFailure("stale manifest digest was not rejected")
    return {"release_audit": audit, "tagged_audit": tagged, "tag_payload": payload}


def assert_focused_tests(repo: pathlib.Path) -> None:
    run([sys.executable, "-m", "unittest", "tests.test_release_integrity"], cwd=repo)


def verify(args: argparse.Namespace) -> dict[str, Any]:
    candidate_repo = pathlib.Path(args.candidate_repo).resolve()
    candidate_commit = git(candidate_repo, "rev-parse", "--verify", f"{args.candidate_commit}^{{commit}}")
    base_commit = git(candidate_repo, "rev-parse", "--verify", f"{args.base_commit}^{{commit}}")
    assert_base_ancestor(candidate_repo, base_commit, candidate_commit)
    with tempfile.TemporaryDirectory() as tmp:
        clone = clone_candidate(candidate_repo, candidate_commit, pathlib.Path(tmp))
        manifest = assert_manifest_v2(clone)
        rc_hits = assert_no_hardcoded_rc_in_code_or_tests(clone)
        command_metrics = assert_release_commands(clone, str(manifest["release_tag"]))
        assert_focused_tests(clone)
    return {
        "schema": "protected-verifier-result-v1",
        "accepted": True,
        "verifier_id": CONTRACT["verifier_id"],
        "verifier_version": CONTRACT["verifier_version"],
        "metrics": {
            "candidate_commit": candidate_commit,
            "release_tag": manifest["release_tag"],
            "hardcoded_rc_hits": rc_hits,
            "release_manifest_digest": command_metrics["tag_payload"]["release_manifest_digest"],
            "tag_object_sha_present": bool(command_metrics["tagged_audit"]["tag_audit"]["tag_object_sha"]),
            "negative_tag_checks": ["lightweight", "stale-manifest-digest"],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bounty-id", required=True)
    parser.add_argument("--candidate-repo", required=True)
    parser.add_argument("--base-commit", required=True)
    parser.add_argument("--candidate-commit", required=True)
    parser.add_argument("--backend", default="local")
    args = parser.parse_args()
    try:
        result = verify(args)
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    except Exception as exc:
        print(
            json.dumps(
                {
                    "schema": "protected-verifier-result-v1",
                    "accepted": False,
                    "verifier_id": CONTRACT["verifier_id"],
                    "verifier_version": CONTRACT["verifier_version"],
                    "failure_reasons": [str(exc)],
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
