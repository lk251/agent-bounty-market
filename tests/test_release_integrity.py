from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from agent_bounty.release_integrity import RELEASE_MANIFEST_SCHEMA, release_audit_report
from agent_bounty.release_provenance import audit_annotated_tag, release_manifest_digest, render_tag_message
from agent_bounty.util import file_digest, stable_json


REPO_ROOT = Path(__file__).resolve().parents[1]
BUNDLE_DIR = REPO_ROOT / "demo" / "bundles" / "winning-run"


class ReleaseIntegrityTests(unittest.TestCase):
    def test_release_audit_passes_current_bundle(self):
        report = release_audit_report(REPO_ROOT, strict_release_metadata=False)
        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual(report["mode"], "mixed")
        self.assertEqual(report["candidate_sha"], "4c03e0fa02a26f1cbadbe593ae687eaa9b333d2c")

    def test_release_manifest_schema_and_digests_match_bundle(self):
        manifest = json.loads((REPO_ROOT / "submission" / "RELEASE_MANIFEST.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["schema"], RELEASE_MANIFEST_SCHEMA)
        self.assertRegex(manifest["release_tag"], r"^hackathon-mixed-rc[0-9]+$")
        self.assertNotIn("commit_sha", manifest)
        self.assertRegex(manifest["source_baseline_sha"], r"^[0-9a-f]{40}$")
        self.assertEqual(manifest["truth_status"], "Mixed real/fallback")
        committed_bundle = git_show_text("demo/bundles/winning-run/manifest.json")
        committed_truth = git_show_text("demo/bundles/winning-run/evidence/truth-matrix.json")
        if committed_bundle is None or committed_truth is None:
            self.assertTrue(str(manifest["bundle_digest"]).startswith("sha256:"))
            self.assertTrue(str(manifest["attestation_digest"]).startswith("sha256:"))
            self.assertTrue(str(manifest["truth_matrix_digest"]).startswith("sha256:"))
            return
        bundle_manifest = json.loads(committed_bundle)
        truth = json.loads(committed_truth)
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
            report = release_audit_report(REPO_ROOT, copied, strict_release_metadata=False)
        self.assertFalse(report["ok"])
        self.assertIn("private_path", {error["code"] for error in report["errors"]})

    def test_release_audit_refuses_manifest_path_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            copied = Path(tmp) / "winning-run"
            shutil.copytree(BUNDLE_DIR, copied)
            outside = Path(tmp) / "outside.txt"
            outside.write_text("outside\n", encoding="utf-8")
            manifest_path = copied / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["files"]["../outside.txt"] = file_digest(outside)
            manifest_path.write_text(stable_json(manifest) + "\n", encoding="utf-8")

            report = release_audit_report(REPO_ROOT, copied, strict_release_metadata=False)

        self.assertFalse(report["ok"])
        self.assertIn("manifest_path_escape", {error["code"] for error in report["errors"]})

    def test_release_audit_refuses_symlink_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            copied = Path(tmp) / "winning-run"
            shutil.copytree(BUNDLE_DIR, copied)
            outside = Path(tmp) / "outside-secret.txt"
            outside.write_text("sk_test_" + "1234567890ABCDEF" + "\n", encoding="utf-8")
            (copied / "evidence" / "outside-link.txt").symlink_to(outside)

            report = release_audit_report(REPO_ROOT, copied, strict_release_metadata=False)

        self.assertFalse(report["ok"])
        self.assertIn("bundle_path_escape", {error["code"] for error in report["errors"]})
        self.assertNotIn("outside-secret", json.dumps(report, sort_keys=True))

    def test_release_tag_message_binds_manifest_and_bundle_digests(self):
        payload = json.loads(render_tag_message(root=REPO_ROOT, tag="test-rc"))
        manifest = json.loads((REPO_ROOT / "submission" / "RELEASE_MANIFEST.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["schema"], "agent-bounty-release-tag-provenance-v1")
        self.assertEqual(payload["release_tag"], "test-rc")
        self.assertEqual(payload["release_manifest_schema"], RELEASE_MANIFEST_SCHEMA)
        self.assertEqual(payload["release_manifest_digest"], release_manifest_digest(REPO_ROOT))
        self.assertEqual(payload["bundle_digest"], manifest["bundle_digest"])
        self.assertEqual(payload["truth_status"], "Mixed real/fallback")
        self.assertEqual(payload["target_authority"], "git annotated tag object; not a self-referential committed manifest field")

    def test_annotated_tag_audit_accepts_bound_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = release_fixture(Path(tmp))
            write_annotated_tag(root, "test-rc")
            report = audit_annotated_tag(root=root, bundle_dir=root / "demo" / "bundles" / "winning-run", tag="test-rc")
        self.assertTrue(report["ok"], report["errors"])
        self.assertRegex(report["target_sha"], r"^[0-9a-f]{40}$")
        self.assertRegex(report["tag_object_sha"], r"^[0-9a-f]{40}$")

    def test_lightweight_tag_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = release_fixture(Path(tmp))
            git(root, "tag", "test-rc")
            report = audit_annotated_tag(root=root, bundle_dir=root / "demo" / "bundles" / "winning-run", tag="test-rc")
        self.assertFalse(report["ok"])
        self.assertIn("tag_not_annotated", {error["code"] for error in report["errors"]})

    def test_tag_audit_rejects_stale_manifest_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = release_fixture(Path(tmp))
            write_annotated_tag(root, "test-rc")
            manifest_path = root / "submission" / "RELEASE_MANIFEST.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["source_baseline_note"] = "changed after tag"
            manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            report = audit_annotated_tag(root=root, bundle_dir=root / "demo" / "bundles" / "winning-run", tag="test-rc")
        self.assertFalse(report["ok"])
        self.assertIn("tag_message_digest_mismatch", {error["code"] for error in report["errors"]})

    def test_tag_audit_rejects_wrong_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = release_fixture(Path(tmp))
            write_annotated_tag(root, "test-rc")
            (root / "extra.txt").write_text("later commit\n", encoding="utf-8")
            git(root, "add", "extra.txt")
            git(root, "commit", "-m", "later")
            report = audit_annotated_tag(root=root, bundle_dir=root / "demo" / "bundles" / "winning-run", tag="test-rc")
        self.assertFalse(report["ok"])
        self.assertIn("tag_target_not_head", {error["code"] for error in report["errors"]})


def git_show_text(path: str) -> str | None:
    result = subprocess.run(
        ["git", "show", f"HEAD:{path}"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return result.stdout
    return None


def release_fixture(tmp: Path) -> Path:
    root = tmp / "release"
    shutil.copytree(BUNDLE_DIR, root / "demo" / "bundles" / "winning-run")
    (root / "submission").mkdir(parents=True)
    shutil.copy2(REPO_ROOT / "submission" / "RELEASE_MANIFEST.json", root / "submission" / "RELEASE_MANIFEST.json")
    git(root, "init")
    git(root, "config", "user.email", "release-test@example.invalid")
    git(root, "config", "user.name", "Release Test")
    git(root, "add", ".")
    git(root, "commit", "-m", "release fixture")
    return root


def write_annotated_tag(root: Path, tag: str) -> None:
    message = root / "tag-message.json"
    message.write_text(render_tag_message(root=root, bundle_dir=root / "demo" / "bundles" / "winning-run", tag=tag), encoding="utf-8")
    git(root, "tag", "-a", tag, "-F", str(message))
    message.unlink()


def git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
    if result.returncode != 0:
        raise AssertionError(result.stderr or result.stdout)
    return result.stdout
