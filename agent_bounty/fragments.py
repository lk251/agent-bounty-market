from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .demo_presentation import SECRET_PATTERNS, validate_bundle, write_bundle
from .util import file_digest, sha256_text, stable_json, utc_now


FRAGMENT_VALIDATION_SCHEMA = "agent-bounty-fragment-validation-v1"
FRAGMENT_IMPORT_SCHEMA = "agent-bounty-fragment-import-v1"
FRAGMENT_LIST_SCHEMA = "agent-bounty-fragment-list-v1"
FRAGMENT_BUILD_SCHEMA = "agent-bounty-fragment-build-winning-v1"
IMPORTED_FRAGMENTS_KEY = "imported-fragments"

FRAGMENT_SCHEMAS: dict[str, set[str]] = {
    "hermes-decision-fragment-v1": {"hermes_executable", "nemotron_model", "project_agent_decision", "solver_agent_decision"},
    "nvidia-sandbox-fragment-v1": {"openshell_nemoclaw"},
    "github-lifecycle-fragment-v1": {"github_lifecycle"},
    "stripe-split-settlement-fragment-v1": {"stripe_split_transfer"},
    "motoko-verification-fragment-v1": {"motoko_verification_receipt"},
}
TRUTH_STATUSES = {"real", "recorded-real", "fallback", "blocked"}
STATUS_RANK = {"blocked": 0, "fallback": 0, "recorded-real": 1, "real": 2}
REAL_ID_MARKERS = ("fake_", "local_", "sim_", "tr_test_", "pi_test_", "cs_test_", "ch_test_")
PLACEHOLDER_MARKERS = ("REPLACE_", "PLACEHOLDER", "YOUR_", "TODO", "<")


class FragmentError(RuntimeError):
    pass


def load_json_file(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise FragmentError(f"fragment is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise FragmentError("fragment root must be a JSON object")
    return data


def fragment_evidence_digest(safe_evidence: dict[str, Any]) -> str:
    return sha256_text(stable_json(safe_evidence))


def validate_fragment_file(path: Path, *, bundle_dir: Path | None = None) -> dict[str, Any]:
    fragment = load_json_file(path)
    return validate_fragment(fragment, bundle_dir=bundle_dir, fragment_path=path)


def validate_fragment(fragment: dict[str, Any], *, bundle_dir: Path | None = None, fragment_path: Path | None = None) -> dict[str, Any]:
    errors: list[str] = []
    schema = fragment.get("schema")
    allowed_components = FRAGMENT_SCHEMAS.get(str(schema))
    if allowed_components is None:
        errors.append("unsupported fragment schema")
    component_id = fragment.get("component_id")
    if allowed_components is not None and component_id not in allowed_components:
        errors.append(f"component_id {component_id!r} is not valid for schema {schema!r}")
    truth_status = fragment.get("truth_status")
    if truth_status not in TRUTH_STATUSES:
        errors.append("truth_status must be real, recorded-real, fallback, or blocked")
    for field in ("source_issue", "source_commit", "source_command", "captured_at", "source_digest", "safe_evidence", "evidence_digest", "consistency"):
        if field not in fragment:
            errors.append(f"missing required field: {field}")
    safe_evidence = fragment.get("safe_evidence")
    if not isinstance(safe_evidence, dict):
        errors.append("safe_evidence must be an object")
        safe_evidence = {}
    consistency = fragment.get("consistency")
    if not isinstance(consistency, dict):
        errors.append("consistency must be an object")
        consistency = {}
    if truth_status in {"fallback", "blocked"} and not fragment.get("blocker"):
        errors.append("fallback or blocked fragments require blocker")
    if truth_status in {"real", "recorded-real"} and fragment.get("blocker"):
        errors.append("real or recorded-real fragments cannot carry blocker")
    expected_digest = fragment_evidence_digest(safe_evidence)
    if fragment.get("evidence_digest") != expected_digest:
        errors.append("evidence_digest does not match safe_evidence")
    if "source_digest" in fragment and not str(fragment.get("source_digest")).startswith("sha256:"):
        errors.append("source_digest must start with sha256:")
    serialized = stable_json(fragment)
    for marker in SECRET_PATTERNS:
        if marker in serialized:
            errors.append(f"secret-like pattern {marker} found in fragment")
    for marker in PLACEHOLDER_MARKERS:
        if marker in serialized:
            errors.append(f"placeholder marker {marker} remains in fragment")
            break
    if truth_status == "real":
        errors.extend(_validate_real_fragment_evidence(str(schema), safe_evidence))
        evidence_text = stable_json(safe_evidence)
        if any(marker in evidence_text for marker in REAL_ID_MARKERS):
            errors.append("real fragment contains fake/local/sim/test identifier")
    if bundle_dir is not None:
        errors.extend(_validate_fragment_against_bundle(fragment, bundle_dir))
    return {
        "schema": FRAGMENT_VALIDATION_SCHEMA,
        "ok": not errors,
        "fragment_file": str(fragment_path) if fragment_path else None,
        "fragment_schema": schema,
        "component_id": component_id,
        "truth_status": truth_status,
        "evidence_digest": fragment.get("evidence_digest"),
        "errors": errors,
    }


def import_fragment_file(bundle_dir: Path, fragment_path: Path, *, downgrade_ok: bool = False) -> dict[str, Any]:
    fragment = load_json_file(fragment_path)
    validation = validate_fragment(fragment, bundle_dir=bundle_dir, fragment_path=fragment_path)
    if not validation["ok"]:
        return {
            "schema": FRAGMENT_IMPORT_SCHEMA,
            "ok": False,
            "bundle_dir": str(bundle_dir),
            "fragment_file": str(fragment_path),
            "validation": validation,
            "error": "fragment validation failed",
        }
    bundle_validation = validate_bundle(bundle_dir)
    if not bundle_validation["ok"]:
        return {
            "schema": FRAGMENT_IMPORT_SCHEMA,
            "ok": False,
            "bundle_dir": str(bundle_dir),
            "fragment_file": str(fragment_path),
            "validation": validation,
            "bundle_validation": bundle_validation,
            "error": "bundle validation failed",
        }
    bundle = _load_bundle(bundle_dir)
    component_id = str(fragment["component_id"])
    rows = _truth_rows(bundle)
    existing = next((row for row in rows if row.get("component_id") == component_id), None)
    existing_status = str(existing.get("status")) if existing else "blocked"
    new_status = str(fragment["truth_status"])
    if STATUS_RANK[new_status] < STATUS_RANK.get(existing_status, 0) and not downgrade_ok:
        return {
            "schema": FRAGMENT_IMPORT_SCHEMA,
            "ok": False,
            "bundle_dir": str(bundle_dir),
            "fragment_file": str(fragment_path),
            "validation": validation,
            "error": f"refusing to downgrade {component_id} from {existing_status} to {new_status}",
        }
    new_row = _truth_row_from_fragment(fragment, validation)
    if existing:
        rows[rows.index(existing)] = new_row
    else:
        rows.append(new_row)
    _refresh_truth_matrix(bundle)
    imported = bundle.setdefault("evidence", {}).setdefault(IMPORTED_FRAGMENTS_KEY, {})
    imported[component_id] = {
        "fragment": fragment,
        "validation": validation,
        "imported_at": utc_now(),
        "fragment_file_digest": file_digest(fragment_path),
    }
    manifest = write_bundle(bundle_dir, bundle, overwrite=False)
    refreshed = validate_bundle(bundle_dir)
    return {
        "schema": FRAGMENT_IMPORT_SCHEMA,
        "ok": refreshed["ok"],
        "bundle_dir": str(bundle_dir),
        "fragment_file": str(fragment_path),
        "component_id": component_id,
        "previous_status": existing_status,
        "new_status": new_status,
        "bundle_digest": manifest.get("bundle_digest"),
        "attestation_digest": manifest.get("attestation_digest"),
        "validation": validation,
        "bundle_validation": refreshed,
    }


def list_imported_fragments(bundle_dir: Path) -> dict[str, Any]:
    validation = validate_bundle(bundle_dir)
    bundle = _load_bundle(bundle_dir) if validation["ok"] else {}
    imported = (bundle.get("evidence") or {}).get(IMPORTED_FRAGMENTS_KEY, {})
    return {
        "schema": FRAGMENT_LIST_SCHEMA,
        "ok": validation["ok"],
        "bundle_dir": str(bundle_dir),
        "bundle_digest": validation.get("bundle_digest"),
        "truth_overall": (validation.get("truth_matrix") or {}).get("overall_status"),
        "fragments": [
            {
                "component_id": component_id,
                "schema": record.get("fragment", {}).get("schema"),
                "truth_status": record.get("fragment", {}).get("truth_status"),
                "evidence_digest": record.get("fragment", {}).get("evidence_digest"),
                "imported_at": record.get("imported_at"),
            }
            for component_id, record in sorted(imported.items())
        ],
        "bundle_validation": validation,
    }


def rebuild_bundle_from_imports(bundle_dir: Path) -> dict[str, Any]:
    validation = validate_bundle(bundle_dir)
    if not validation["ok"]:
        return {"schema": FRAGMENT_BUILD_SCHEMA, "ok": False, "bundle_dir": str(bundle_dir), "bundle_validation": validation}
    bundle = _load_bundle(bundle_dir)
    manifest = write_bundle(bundle_dir, bundle, overwrite=False)
    refreshed = validate_bundle(bundle_dir)
    return {
        "schema": FRAGMENT_BUILD_SCHEMA,
        "ok": refreshed["ok"],
        "bundle_dir": str(bundle_dir),
        "bundle_digest": manifest.get("bundle_digest"),
        "attestation_digest": manifest.get("attestation_digest"),
        "bundle_validation": refreshed,
    }


def _validate_real_fragment_evidence(schema: str, evidence: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    requirements = {
        "hermes-decision-fragment-v1": ("hermes_version", "provider_model_id", "skill_digests", "command_digest", "decision_digest"),
        "nvidia-sandbox-fragment-v1": ("openshell_version", "sandbox_id", "policy_digest", "adversarial_proof_rows", "receipt_backend_digest"),
        "github-lifecycle-fragment-v1": ("repository_url", "issue_number", "issue_url", "claim_comment_id", "claim_comment_url", "pr_number", "pr_url", "candidate_sha", "receipt_publication_id", "receipt_publication_url"),
        "stripe-split-settlement-fragment-v1": ("checkout_session", "payment_intent", "charge", "funding_event", "connected_account", "transfer", "transfer_event", "reconciliation_digest"),
        "motoko-verification-fragment-v1": ("candidate_sha", "receipt_id", "verifier_digest", "backend_digest", "metrics_digest"),
    }
    for field in requirements.get(schema, ()):
        if field not in evidence:
            errors.append(f"real {schema} missing safe_evidence.{field}")
    if schema == "stripe-split-settlement-fragment-v1":
        prefixes = {
            "checkout_session": "cs_",
            "payment_intent": "pi_",
            "charge": "ch_",
            "funding_event": "evt_",
            "connected_account": "acct_",
            "transfer": "tr_",
            "transfer_event": "evt_",
        }
        for field, prefix in prefixes.items():
            value = str(evidence.get(field, ""))
            if not value.startswith(prefix):
                errors.append(f"real Stripe evidence {field} must start with {prefix}")
    return errors


def _validate_fragment_against_bundle(fragment: dict[str, Any], bundle_dir: Path) -> list[str]:
    validation = validate_bundle(bundle_dir)
    if not validation["ok"]:
        return ["target bundle does not validate"]
    bundle = _load_bundle(bundle_dir)
    summary = bundle.get("summary") or {}
    consistency = fragment.get("consistency") or {}
    checks = {
        "project": summary.get("project"),
        "candidate_sha": summary.get("candidate_sha"),
        "currency": summary.get("currency"),
        "reward_amount": summary.get("reward"),
        "receipt_id": summary.get("receipt_id"),
    }
    errors: list[str] = []
    for field, expected in checks.items():
        actual = consistency.get(field)
        if actual is not None and expected is not None and actual != expected:
            errors.append(f"fragment {field} {actual!r} does not match bundle {expected!r}")
    return errors


def _load_bundle(bundle_dir: Path) -> dict[str, Any]:
    path = bundle_dir / "bundle.json"
    if not path.exists():
        raise FragmentError(f"bundle.json missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _truth_rows(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    matrix = bundle.setdefault("truth_matrix", {})
    rows = matrix.setdefault("rows", [])
    if not isinstance(rows, list):
        raise FragmentError("truth_matrix.rows must be a list")
    return rows


def _truth_row_from_fragment(fragment: dict[str, Any], validation: dict[str, Any]) -> dict[str, Any]:
    evidence = fragment.get("safe_evidence") or {}
    return {
        "component_id": fragment.get("component_id"),
        "label": fragment.get("label") or str(fragment.get("component_id")).replace("_", " ").title(),
        "status": fragment.get("truth_status"),
        "safe_evidence": evidence,
        "safe_evidence_digest": fragment_evidence_digest(evidence),
        "blocker": fragment.get("blocker"),
        "source_issue": fragment.get("source_issue"),
        "source_commit": fragment.get("source_commit"),
        "imported_fragment_schema": fragment.get("schema"),
        "imported_fragment_validation": validation,
    }


def _refresh_truth_matrix(bundle: dict[str, Any]) -> None:
    matrix = bundle.get("truth_matrix") or {}
    rows = matrix.get("rows") or []
    statuses = {row.get("status") for row in rows}
    matrix["all_required_real"] = bool(statuses) and statuses <= {"real", "recorded-real"}
    matrix["overall_status"] = "recorded-real" if matrix["all_required_real"] else "mixed-real-fallback"
    matrix["digest"] = sha256_text(stable_json(rows))
    bundle["truth_matrix"] = matrix
    bundle["truth_mode"] = matrix["overall_status"]
    if bundle.get("summary"):
        bundle["summary"]["truth_overall"] = matrix["overall_status"]
