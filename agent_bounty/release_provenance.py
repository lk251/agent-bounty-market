from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from .demo_presentation import default_winning_bundle_dir
from .util import file_digest, stable_json


RELEASE_MANIFEST_SCHEMA_V2 = "agent-bounty-release-manifest-v2"
RELEASE_TAG_PROVENANCE_SCHEMA = "agent-bounty-release-tag-provenance-v1"

RELEASE_MANIFEST_PATH = Path("submission/RELEASE_MANIFEST.json")
DEFAULT_BUNDLE_PATH = Path("demo/bundles/winning-run")

_TAG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class ReleaseProvenanceError(RuntimeError):
    pass


def load_release_manifest(root: Path | None = None) -> dict[str, Any]:
    root_path = (root or Path.cwd()).resolve()
    path = root_path / RELEASE_MANIFEST_PATH
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ReleaseProvenanceError(f"missing {RELEASE_MANIFEST_PATH}") from exc
    except json.JSONDecodeError as exc:
        raise ReleaseProvenanceError(f"invalid {RELEASE_MANIFEST_PATH}: {exc}") from exc


def release_manifest_digest(root: Path | None = None) -> str:
    root_path = (root or Path.cwd()).resolve()
    return file_digest(root_path / RELEASE_MANIFEST_PATH)


def canonical_release_provenance(
    *,
    root: Path | None = None,
    bundle_dir: Path | None = None,
    tag: str | None = None,
) -> dict[str, Any]:
    root_path = (root or Path.cwd()).resolve()
    bundle_path = _bundle_path(root_path, bundle_dir)
    manifest = load_release_manifest(root_path)
    release_tag = tag or str(manifest.get("release_tag") or "")
    _validate_tag_name(release_tag)

    bundle_manifest = _load_json(bundle_path / "manifest.json")
    bundle = _load_json(bundle_path / "bundle.json")
    truth = _load_json(bundle_path / "evidence" / "truth-matrix.json")
    summary = bundle.get("summary") if isinstance(bundle.get("summary"), dict) else {}

    return {
        "schema": RELEASE_TAG_PROVENANCE_SCHEMA,
        "release_tag": release_tag,
        "release_manifest_path": str(RELEASE_MANIFEST_PATH),
        "release_manifest_schema": manifest.get("schema"),
        "release_manifest_digest": release_manifest_digest(root_path),
        "bundle_path": _display_bundle_path(root_path, bundle_path),
        "bundle_manifest_file_digest": file_digest(bundle_path / "manifest.json"),
        "bundle_digest": bundle_manifest.get("bundle_digest"),
        "attestation_digest": bundle_manifest.get("attestation_digest"),
        "truth_matrix_digest": truth.get("digest"),
        "truth_status": manifest.get("truth_status"),
        "mode": bundle_manifest.get("mode"),
        "candidate_sha": summary.get("candidate_sha"),
        "target_authority": "git annotated tag object; not a self-referential committed manifest field",
    }


def render_tag_message(
    *,
    root: Path | None = None,
    bundle_dir: Path | None = None,
    tag: str | None = None,
) -> str:
    return json.dumps(
        canonical_release_provenance(root=root, bundle_dir=bundle_dir, tag=tag),
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
    ) + "\n"


def audit_annotated_tag(
    *,
    root: Path | None = None,
    bundle_dir: Path | None = None,
    tag: str,
    require_head: bool = True,
) -> dict[str, Any]:
    root_path = (root or Path.cwd()).resolve()
    _validate_tag_name(tag)
    errors: list[dict[str, str]] = []
    tag_type = _git(root_path, ["cat-file", "-t", f"refs/tags/{tag}"], errors=errors, code="tag_missing")
    if tag_type != "tag":
        errors.append(
            _error(
                "tag_not_annotated",
                f"refs/tags/{tag}",
                "release tag must be an annotated tag; lightweight tags are not authoritative release provenance",
            )
        )
        return _tag_report(tag=tag, ok=False, errors=errors)

    target_sha = _git(root_path, ["rev-parse", f"refs/tags/{tag}^{{}}"], errors=errors, code="tag_target_missing")
    tag_object_sha = _git(root_path, ["rev-parse", f"refs/tags/{tag}^{{tag}}"], errors=errors, code="tag_object_missing")
    head_sha = _git(root_path, ["rev-parse", "HEAD"], errors=errors, code="head_missing")
    contents = _git(root_path, ["for-each-ref", f"refs/tags/{tag}", "--format=%(contents)"], errors=errors, code="tag_message_missing")
    if require_head and target_sha and head_sha and target_sha != head_sha:
        errors.append(_error("tag_target_not_head", f"refs/tags/{tag}", "release tag must resolve to the checked release commit"))

    payload: dict[str, Any] = {}
    if contents:
        try:
            parsed = json.loads(contents)
            if isinstance(parsed, dict):
                payload = parsed
            else:
                errors.append(_error("tag_message_schema", f"refs/tags/{tag}", "tag annotation JSON must be an object"))
        except json.JSONDecodeError as exc:
            errors.append(_error("tag_message_json", f"refs/tags/{tag}", f"tag annotation must be canonical JSON: {exc}"))
    if payload:
        expected = canonical_release_provenance(root=root_path, bundle_dir=bundle_dir, tag=tag)
        if payload.get("schema") != RELEASE_TAG_PROVENANCE_SCHEMA:
            errors.append(_error("tag_message_schema", f"refs/tags/{tag}", f"schema must be {RELEASE_TAG_PROVENANCE_SCHEMA}"))
        for key, value in expected.items():
            if payload.get(key) != value:
                errors.append(_error("tag_message_digest_mismatch", f"refs/tags/{tag}", f"{key} must match current release provenance"))

    return _tag_report(
        tag=tag,
        ok=not errors,
        errors=errors,
        target_sha=target_sha,
        tag_object_sha=tag_object_sha,
        head_sha=head_sha,
        payload=payload,
    )


def validate_release_manifest_v2(
    *,
    root: Path | None = None,
    bundle_dir: Path | None = None,
) -> list[dict[str, str]]:
    root_path = (root or Path.cwd()).resolve()
    bundle_path = _bundle_path(root_path, bundle_dir)
    errors: list[dict[str, str]] = []
    manifest = load_release_manifest(root_path)
    if manifest.get("schema") != RELEASE_MANIFEST_SCHEMA_V2:
        errors.append(_error("release_manifest_schema", str(RELEASE_MANIFEST_PATH), f"schema must be {RELEASE_MANIFEST_SCHEMA_V2}"))
    if "commit_sha" in manifest:
        errors.append(_error("release_manifest_self_reference", str(RELEASE_MANIFEST_PATH), "manifest must not carry a self-referential release commit_sha field"))
    release_tag = str(manifest.get("release_tag") or "")
    try:
        _validate_tag_name(release_tag)
    except ReleaseProvenanceError as exc:
        errors.append(_error("release_manifest_tag", str(RELEASE_MANIFEST_PATH), str(exc)))
    source_baseline = manifest.get("source_baseline_sha")
    if source_baseline is not None and not (isinstance(source_baseline, str) and _SHA_RE.match(source_baseline)):
        errors.append(_error("release_manifest_baseline", str(RELEASE_MANIFEST_PATH), "source_baseline_sha must be a 40-character lowercase Git SHA if present"))
    bundle_manifest = _load_json(bundle_path / "manifest.json")
    bundle = _load_json(bundle_path / "bundle.json")
    truth = _load_json(bundle_path / "evidence" / "truth-matrix.json")
    expected = {
        "bundle_digest": bundle_manifest.get("bundle_digest"),
        "attestation_digest": bundle_manifest.get("attestation_digest"),
        "truth_matrix_digest": truth.get("digest"),
    }
    for key, value in expected.items():
        if manifest.get(key) != value:
            errors.append(_error("release_manifest_digest_mismatch", str(RELEASE_MANIFEST_PATH), f"{key} must match current bundle"))
    if manifest.get("truth_status") != "Mixed real/fallback":
        errors.append(_error("release_manifest_truth", str(RELEASE_MANIFEST_PATH), "truth_status must be Mixed real/fallback"))
    summary = bundle.get("summary") if isinstance(bundle.get("summary"), dict) else {}
    candidate_sha = summary.get("candidate_sha")
    if not (isinstance(candidate_sha, str) and _SHA_RE.match(candidate_sha)):
        errors.append(_error("bundle_candidate_sha", "demo/bundles/winning-run/bundle.json", "candidate_sha must be a 40-character lowercase Git SHA"))
    return errors


def _bundle_path(root: Path, bundle_dir: Path | None) -> Path:
    bundle_path = bundle_dir or default_winning_bundle_dir()
    if not bundle_path.is_absolute():
        bundle_path = root / bundle_path
    return bundle_path.resolve()


def _display_bundle_path(root: Path, bundle_path: Path) -> str:
    try:
        return str(bundle_path.relative_to(root))
    except ValueError:
        return str(bundle_path)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ReleaseProvenanceError(f"missing {path}") from exc
    except json.JSONDecodeError as exc:
        raise ReleaseProvenanceError(f"invalid {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ReleaseProvenanceError(f"{path} must contain a JSON object")
    return value


def _validate_tag_name(tag: str) -> None:
    if not tag:
        raise ReleaseProvenanceError("release tag is required")
    if not _TAG_RE.match(tag) or ".." in tag or tag.endswith("/") or tag.endswith(".lock"):
        raise ReleaseProvenanceError("release tag contains unsafe characters")


def _git(root: Path, args: list[str], *, errors: list[dict[str, str]], code: str) -> str:
    completed = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "git command failed").strip()
        errors.append(_error(code, "git", detail))
        return ""
    return completed.stdout.strip()


def _tag_report(
    *,
    tag: str,
    ok: bool,
    errors: list[dict[str, str]],
    target_sha: str = "",
    tag_object_sha: str = "",
    head_sha: str = "",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema": "agent-bounty-release-tag-audit-v1",
        "ok": ok,
        "tag": tag,
        "target_sha": target_sha,
        "tag_object_sha": tag_object_sha,
        "head_sha": head_sha,
        "payload": payload or {},
        "errors": errors,
    }


def _error(code: str, path: str, detail: str) -> dict[str, str]:
    return {"code": code, "path": path, "detail": detail}
