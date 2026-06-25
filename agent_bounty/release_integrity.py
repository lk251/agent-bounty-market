from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .demo_presentation import default_winning_bundle_dir, validate_bundle
from .economic_loop import REAL_STRIPE_EVIDENCE
from .release_provenance import ReleaseProvenanceError, audit_annotated_tag, validate_release_manifest_v2
from .submission_check import SECRET_PATTERNS
from .util import file_digest


RELEASE_AUDIT_SCHEMA = "agent-bounty-release-audit-v1"
RELEASE_MANIFEST_SCHEMA = "agent-bounty-release-manifest-v2"
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
REQUIRED_BUNDLE_FILES = [
    "manifest.json",
    "bundle.json",
    "attestation.json",
    "dashboard.html",
    "README.md",
    "recording-timeline.md",
    "evidence/database-counts.json",
    "evidence/demo-summary.json",
    "evidence/truth-matrix.json",
]
PRIVATE_PATH_MARKERS = ("/home/", "/Users/")
SAFE_STRIPE_FILES = {
    "bundle.json",
    "evidence/demo-summary.json",
    "evidence/truth-matrix.json",
}


def release_audit_report(root: Path | None = None, bundle_dir: Path | None = None, *, strict_release_metadata: bool = True, tag: str | None = None) -> dict[str, Any]:
    root_path = (root or Path.cwd()).resolve()
    bundle_path = (bundle_dir or default_winning_bundle_dir()).resolve()
    if not bundle_path.is_absolute():
        bundle_path = (root_path / bundle_path).resolve()
    errors: list[dict[str, Any]] = []
    validation: dict[str, Any] | None = None
    manifest: dict[str, Any] = {}
    bundle: dict[str, Any] = {}
    release_manifest: dict[str, Any] = {}
    tag_audit: dict[str, Any] | None = None

    for relative in REQUIRED_BUNDLE_FILES:
        if not (bundle_path / relative).is_file():
            errors.append(_error("missing_bundle_file", f"demo/bundles/winning-run/{relative}", f"missing required bundle file `{relative}`"))

    try:
        validation = validate_bundle(bundle_path)
        for mismatch in validation.get("mismatches", []):
            errors.append(_error("bundle_validation", "demo/bundles/winning-run", str(mismatch)))
    except Exception as exc:
        errors.append(_error("bundle_validation_failed", "demo/bundles/winning-run", str(exc)))

    manifest_path = bundle_path / "manifest.json"
    bundle_json_path = bundle_path / "bundle.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if bundle_json_path.is_file():
        bundle = json.loads(bundle_json_path.read_text(encoding="utf-8"))

    _check_bundle_claims(bundle_path, manifest, bundle, errors)
    if strict_release_metadata:
        release_manifest = _check_release_manifest(root_path, bundle_path, errors)
        _check_final_handoff(root_path, manifest, bundle, release_manifest, errors)
        if tag:
            try:
                tag_audit = audit_annotated_tag(root=root_path, bundle_dir=bundle_path, tag=tag)
                errors.extend(tag_audit.get("errors") or [])
            except ReleaseProvenanceError as exc:
                errors.append(_error("tag_audit_failed", f"refs/tags/{tag}", str(exc)))

    return {
        "schema": RELEASE_AUDIT_SCHEMA,
        "ok": not errors,
        "release_tag": release_manifest.get("release_tag"),
        "bundle_dir": str(bundle_path.relative_to(root_path)) if _inside(bundle_path, root_path) else str(bundle_path),
        "bundle_digest": manifest.get("bundle_digest"),
        "attestation_digest": manifest.get("attestation_digest"),
        "truth_matrix_digest": ((bundle.get("truth_matrix") or {}).get("digest")),
        "mode": manifest.get("mode"),
        "candidate_sha": ((bundle.get("summary") or {}).get("candidate_sha")),
        "validation_ok": bool(validation and validation.get("ok")),
        "strict_release_metadata": strict_release_metadata,
        "tag_audit": tag_audit,
        "errors": errors,
    }


def _check_bundle_claims(bundle_path: Path, manifest: dict[str, Any], bundle: dict[str, Any], errors: list[dict[str, Any]]) -> None:
    if manifest.get("mode") != "mixed":
        errors.append(_error("mode_not_mixed", "demo/bundles/winning-run/manifest.json", "release bundle must remain mixed unless real fragments upgrade it"))
    summary = bundle.get("summary") or {}
    if not (isinstance(summary.get("candidate_sha"), str) and _SHA_RE.match(summary["candidate_sha"])):
        errors.append(_error("candidate_sha_invalid", "demo/bundles/winning-run/bundle.json", "candidate SHA must be a 40-character lowercase Git SHA"))
    dashboard = bundle_path / "dashboard.html"
    if dashboard.is_file() and "Mixed real/fallback" not in dashboard.read_text(encoding="utf-8", errors="replace"):
        errors.append(_error("missing_truth_badge", "demo/bundles/winning-run/dashboard.html", "dashboard must include Mixed real/fallback"))

    listed = manifest.get("files") if isinstance(manifest.get("files"), dict) else {}
    for relative, expected_digest in listed.items():
        path = bundle_path / str(relative)
        if path.is_file() and file_digest(path) != expected_digest:
            errors.append(_error("manifest_digest_mismatch", f"demo/bundles/winning-run/{relative}", "manifest digest does not match file content"))

    stripe_ids = {str(value) for value in REAL_STRIPE_EVIDENCE.values() if isinstance(value, str) and "_" in value}
    for path in sorted(bundle_path.rglob("*")):
        if not path.is_file():
            continue
        relative = str(path.relative_to(bundle_path))
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for marker in PRIVATE_PATH_MARKERS:
            if marker in text:
                errors.append(_error("private_path", f"demo/bundles/winning-run/{relative}", f"private path marker `{marker}` must not appear"))
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                errors.append(_error("secret_like_text", f"demo/bundles/winning-run/{relative}", "secret-like value must not appear"))
        if "https://checkout.stripe.com" in text or "raw_payload" in text:
            errors.append(_error("unsafe_stripe_payload", f"demo/bundles/winning-run/{relative}", "checkout URLs and raw webhook payloads must not appear"))
        if relative not in SAFE_STRIPE_FILES and any(stripe_id in text for stripe_id in stripe_ids):
            errors.append(_error("stripe_id_outside_safe_evidence", f"demo/bundles/winning-run/{relative}", "prior Stripe IDs must stay in safe evidence fields"))


def _check_release_manifest(root: Path, bundle_path: Path, errors: list[dict[str, Any]]) -> dict[str, Any]:
    rel = Path("submission/RELEASE_MANIFEST.json")
    path = root / rel
    if not path.is_file():
        errors.append(_error("missing_release_manifest", str(rel), "release manifest is required"))
        return {}
    try:
        release = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        errors.append(_error("release_manifest_invalid_json", str(rel), str(exc)))
        return {}
    try:
        errors.extend(validate_release_manifest_v2(root=root, bundle_dir=bundle_path))
    except ReleaseProvenanceError as exc:
        errors.append(_error("release_manifest_validation_failed", str(rel), str(exc)))
    return release


def _check_final_handoff(root: Path, bundle_manifest: dict[str, Any], bundle: dict[str, Any], release: dict[str, Any], errors: list[dict[str, Any]]) -> None:
    rel = Path("submission/FINAL_HANDOFF.md")
    path = root / rel
    if not path.is_file():
        errors.append(_error("missing_final_handoff", str(rel), "final handoff is required"))
        return
    text = path.read_text(encoding="utf-8")
    required = [
        "submission-check",
        "release-audit",
        str(bundle_manifest.get("bundle_digest") or ""),
        str(bundle_manifest.get("attestation_digest") or ""),
        str((bundle.get("truth_matrix") or {}).get("digest") or ""),
        str(release.get("release_tag") or ""),
    ]
    for item in required:
        if item and item not in text:
            errors.append(_error("final_handoff_stale", str(rel), f"final handoff missing `{item}`"))


def _error(code: str, path: str, detail: str) -> dict[str, str]:
    return {"code": code, "path": path, "detail": detail}


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
