from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from agent_bounty.fragments import (
    fragment_evidence_digest,
    import_fragment_file,
    list_imported_fragments,
    rebuild_bundle_from_imports,
    validate_fragment_file,
)
from agent_bounty.util import stable_json


FIXTURE_BUNDLE = Path("demo/bundles/winning-run")
TEMPLATE_DIR = Path("demo/fragments/templates")


class FragmentImportTests(unittest.TestCase):
    def test_valid_fragment_import_updates_dashboard_truth_matrix(self):
        with bundle_copy() as bundle:
            fragment_path = write_fragment(bundle, github_fragment(bundle))
            imported = import_fragment_file(bundle, fragment_path)
            listed = list_imported_fragments(bundle)
            dashboard = (bundle / "dashboard.html").read_text(encoding="utf-8")

            self.assertTrue(imported["ok"], imported)
            self.assertTrue(listed["ok"], listed)
            self.assertEqual(listed["fragments"][0]["component_id"], "github_lifecycle")
            self.assertIn("GitHub work", dashboard)
            self.assertIn("recorded-real", dashboard)

    def test_missing_required_fields_fail(self):
        with bundle_copy() as bundle:
            fragment = github_fragment(bundle)
            fragment.pop("source_command")
            path = write_fragment(bundle, fragment)
            result = validate_fragment_file(path, bundle_dir=bundle)
            self.assertFalse(result["ok"])
            self.assertIn("missing required field: source_command", result["errors"])

    def test_fake_ids_in_real_fragment_fail(self):
        with bundle_copy() as bundle:
            fragment = stripe_fragment(bundle, truth_status="real")
            fragment["safe_evidence"]["transfer"] = "fake_transfer_bad"
            refresh_digest(fragment)
            path = write_fragment(bundle, fragment)
            result = validate_fragment_file(path, bundle_dir=bundle)
            self.assertFalse(result["ok"])
            self.assertIn("real Stripe evidence transfer must start with tr_", result["errors"])
            self.assertIn("real fragment contains fake/local/sim/test identifier", result["errors"])

    def test_mixed_candidate_sha_rejected(self):
        with bundle_copy() as bundle:
            fragment = github_fragment(bundle)
            fragment["consistency"]["candidate_sha"] = "different"
            path = write_fragment(bundle, fragment)
            result = validate_fragment_file(path, bundle_dir=bundle)
            self.assertFalse(result["ok"])
            self.assertIn("fragment candidate_sha 'different' does not match bundle '4c03e0fa02a26f1cbadbe593ae687eaa9b333d2c'", result["errors"])

    def test_mixed_currency_rejected(self):
        with bundle_copy() as bundle:
            fragment = github_fragment(bundle)
            fragment["consistency"]["currency"] = "EUR"
            path = write_fragment(bundle, fragment)
            result = validate_fragment_file(path, bundle_dir=bundle)
            self.assertFalse(result["ok"])
            self.assertIn("fragment currency 'EUR' does not match bundle 'USD'", result["errors"])

    def test_downgrade_protection(self):
        with bundle_copy() as bundle:
            fragment = hermes_fragment(bundle, truth_status="fallback", blocker="operator provided stale fallback")
            path = write_fragment(bundle, fragment)
            result = import_fragment_file(bundle, path)
            allowed = import_fragment_file(bundle, path, downgrade_ok=True)
            self.assertFalse(result["ok"])
            self.assertIn("refusing to downgrade hermes_executable", result["error"])
            self.assertTrue(allowed["ok"], allowed)

    def test_duplicate_import_is_idempotent(self):
        with bundle_copy() as bundle:
            path = write_fragment(bundle, github_fragment(bundle))
            first = import_fragment_file(bundle, path)
            second = import_fragment_file(bundle, path)
            listed = list_imported_fragments(bundle)
            self.assertTrue(first["ok"])
            self.assertTrue(second["ok"])
            self.assertEqual(len(listed["fragments"]), 1)

    def test_tampered_evidence_digest_fails(self):
        with bundle_copy() as bundle:
            fragment = github_fragment(bundle)
            fragment["evidence_digest"] = "sha256:bad"
            path = write_fragment(bundle, fragment)
            result = validate_fragment_file(path, bundle_dir=bundle)
            self.assertFalse(result["ok"])
            self.assertIn("evidence_digest does not match safe_evidence", result["errors"])

    def test_secret_like_string_fails(self):
        with bundle_copy() as bundle:
            fragment = github_fragment(bundle)
            fragment["safe_evidence"]["note"] = "do not leak ghp_bad"
            refresh_digest(fragment)
            path = write_fragment(bundle, fragment)
            result = validate_fragment_file(path, bundle_dir=bundle)
            self.assertFalse(result["ok"])
            self.assertIn("secret-like pattern ghp_ found in fragment", result["errors"])

    def test_import_into_tampered_bundle_fails_closed(self):
        with bundle_copy() as bundle:
            (bundle / "dashboard.html").write_text("tampered", encoding="utf-8")
            path = write_fragment(bundle, github_fragment(bundle))
            result = import_fragment_file(bundle, path)
            self.assertFalse(result["ok"])
            self.assertIn("target bundle does not validate", result["validation"]["errors"])

    def test_templates_require_placeholder_replacement(self):
        for template in sorted(TEMPLATE_DIR.glob("*-fragment-v1.json")):
            result = validate_fragment_file(template)
            self.assertFalse(result["ok"], template)
            self.assertTrue(any("placeholder marker" in error for error in result["errors"]), result)

    def test_build_winning_rewrites_valid_bundle(self):
        with bundle_copy() as bundle:
            path = write_fragment(bundle, github_fragment(bundle))
            self.assertTrue(import_fragment_file(bundle, path)["ok"])
            result = rebuild_bundle_from_imports(bundle)
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["bundle_validation"]["truth_matrix"]["overall_status"], "mixed-real-fallback")


def bundle_copy():
    temp = tempfile.TemporaryDirectory()
    target = Path(temp.name) / "winning-run"
    shutil.copytree(FIXTURE_BUNDLE, target)

    class Manager:
        def __enter__(self):
            return target

        def __exit__(self, exc_type, exc, tb):
            temp.cleanup()

    return Manager()


def bundle_summary(bundle: Path) -> dict:
    return json.loads((bundle / "bundle.json").read_text(encoding="utf-8"))["summary"]


def write_fragment(bundle: Path, fragment: dict) -> Path:
    path = bundle.parent / "fragment.json"
    path.write_text(stable_json(fragment) + "\n", encoding="utf-8")
    return path


def refresh_digest(fragment: dict) -> None:
    fragment["evidence_digest"] = fragment_evidence_digest(fragment["safe_evidence"])


def base_fragment(bundle: Path, *, schema: str, component_id: str, truth_status: str = "recorded-real", blocker: str | None = None) -> dict:
    summary = bundle_summary(bundle)
    fragment = {
        "schema": schema,
        "component_id": component_id,
        "label": component_id.replace("_", " ").title(),
        "truth_status": truth_status,
        "source_issue": 16,
        "source_commit": "2d1f881",
        "source_command": "safe capture command",
        "captured_at": "2026-06-24T21:10:00Z",
        "source_digest": "sha256:source-output",
        "safe_evidence": {},
        "evidence_digest": "",
        "consistency": {
            "project": summary["project"],
            "candidate_sha": summary["candidate_sha"],
            "currency": summary["currency"],
            "reward_amount": summary["reward"],
            "receipt_id": summary["receipt_id"],
        },
        "blocker": blocker,
    }
    return fragment


def github_fragment(bundle: Path) -> dict:
    fragment = base_fragment(bundle, schema="github-lifecycle-fragment-v1", component_id="github_lifecycle")
    fragment["safe_evidence"] = {
        "repository_url": "https://github.com/lk251/motoko",
        "issue_number": 1,
        "issue_url": "https://github.com/lk251/motoko/issues/1",
        "claim_comment_id": 123,
        "claim_comment_url": "https://github.com/lk251/motoko/issues/1#issuecomment-123",
        "pr_number": 2,
        "pr_url": "https://github.com/lk251/motoko/pull/2",
        "candidate_sha": bundle_summary(bundle)["candidate_sha"],
        "receipt_publication_id": "status-123",
        "receipt_publication_url": "https://github.com/lk251/motoko/status/123",
    }
    refresh_digest(fragment)
    return fragment


def stripe_fragment(bundle: Path, *, truth_status: str = "recorded-real") -> dict:
    fragment = base_fragment(bundle, schema="stripe-split-settlement-fragment-v1", component_id="stripe_split_transfer", truth_status=truth_status)
    fragment["safe_evidence"] = {
        "checkout_session": "cs_live_safe",
        "payment_intent": "pi_live_safe",
        "charge": "ch_live_safe",
        "funding_event": "evt_live_safe1",
        "connected_account": "acct_live_safe",
        "transfer": "tr_live_safe",
        "transfer_event": "evt_live_safe2",
        "reconciliation_digest": "sha256:reconciliation",
    }
    refresh_digest(fragment)
    return fragment


def hermes_fragment(bundle: Path, *, truth_status: str = "recorded-real", blocker: str | None = None) -> dict:
    fragment = base_fragment(bundle, schema="hermes-decision-fragment-v1", component_id="hermes_executable", truth_status=truth_status, blocker=blocker)
    fragment["safe_evidence"] = {
        "fallback_reason": blocker or "recorded evidence",
    }
    refresh_digest(fragment)
    return fragment


if __name__ == "__main__":
    unittest.main()
