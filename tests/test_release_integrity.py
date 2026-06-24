from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from agent_bounty.release_integrity import RELEASE_MANIFEST_SCHEMA, release_audit_report


REPO_ROOT = Path(__file__).resolve().parents[1]
BUNDLE_DIR = REPO_ROOT / "demo" / "bundles" / "winning-run"


class ReleaseIntegrityTests(unittest.TestCase):
    def test_release_audit_passes_current_bundle(self):
        report = release_audit_report(REPO_ROOT)
        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual(report["mode"], "mixed")
        self.assertEqual(report["candidate_sha"], "4c03e0fa02a26f1cbadbe593ae687eaa9b333d2c")

    def test_release_manifest_schema_and_digests_match_bundle(self):
        manifest = json.loads((REPO_ROOT / "submission" / "RELEASE_MANIFEST.json").read_text(encoding="utf-8"))
        bundle_manifest = json.loads((BUNDLE_DIR / "manifest.json").read_text(encoding="utf-8"))
        truth = json.loads((BUNDLE_DIR / "evidence" / "truth-matrix.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["schema"], RELEASE_MANIFEST_SCHEMA)
        self.assertEqual(manifest["release_tag"], "hackathon-mixed-rc2")
        self.assertEqual(manifest["truth_status"], "Mixed real/fallback")
        self.assertEqual(manifest["bundle_digest"], bundle_manifest["bundle_digest"])
        self.assertEqual(manifest["attestation_digest"], bundle_manifest["attestation_digest"])
        self.assertEqual(manifest["truth_matrix_digest"], truth["digest"])

    def test_generated_bundle_files_are_present(self):
        for relative in [
            "manifest.json",
            "bundle.json",
            "attestation.json",
            "dashboard.html",
            "evidence/database-counts.json",
            "evidence/demo-summary.json",
            "evidence/truth-matrix.json",
        ]:
            self.assertTrue((BUNDLE_DIR / relative).is_file(), relative)

    def test_release_checklist_mentions_mixed_and_live_truth(self):
        text = (REPO_ROOT / "submission" / "RELEASE_CHECKLIST.md").read_text(encoding="utf-8")
        self.assertIn("Mixed real/fallback", text)
        self.assertIn("Known Live Blockers", text)
        self.assertIn("release-audit", text)

    def test_docs_reference_existing_release_commands(self):
        combined = "\n".join(
            [
                (REPO_ROOT / "README.md").read_text(encoding="utf-8"),
                (REPO_ROOT / "submission" / "FINAL_HANDOFF.md").read_text(encoding="utf-8"),
            ]
        )
        for command in ["demo-build-winning-run", "submission-check", "release-audit", "demo-rehearse"]:
            self.assertIn(command, combined)

    def test_final_handoff_digest_matches_release_manifest(self):
        manifest = json.loads((REPO_ROOT / "submission" / "RELEASE_MANIFEST.json").read_text(encoding="utf-8"))
        text = (REPO_ROOT / "submission" / "FINAL_HANDOFF.md").read_text(encoding="utf-8")
        self.assertIn(manifest["bundle_digest"], text)
        self.assertIn(manifest["attestation_digest"], text)
        self.assertIn(manifest["truth_matrix_digest"], text)

    def test_private_path_in_bundle_fails_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            copied = Path(tmp) / "winning-run"
            shutil.copytree(BUNDLE_DIR, copied)
            readme = copied / "README.md"
            readme.write_text(readme.read_text(encoding="utf-8") + "private path: /home/mares/secret\n", encoding="utf-8")
            report = release_audit_report(REPO_ROOT, copied)
        self.assertFalse(report["ok"])
        self.assertIn("private_path", {error["code"] for error in report["errors"]})
