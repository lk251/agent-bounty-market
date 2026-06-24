from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_bounty.demo_presentation import (
    DemoPresentationError,
    demo_preflight_report,
    live_refusal_report,
    rehearse_demo,
    replay_bundle,
    reset_demo_state,
    run_local_demo,
    run_winning_bundle,
    validate_bundle,
)
from agent_bounty.util import file_digest, stable_json


MOTOKO_REPO = Path("/home/mares/repos/motoko-issue-1-tui-input-latency")


class DemoPresentationTests(unittest.TestCase):
    def test_preflight_reports_blockers_without_secret_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(
                "os.environ",
                {
                    "STRIPE_TEST_SECRET_KEY": "sk_test_should_not_leak",
                    "STRIPE_TEST_WEBHOOK_SECRET": "whsec_should_not_leak",
                    "AGENT_BOUNTY_GITHUB_TOKEN": "ghp_should_not_leak",
                },
                clear=False,
            ):
                report = demo_preflight_report(mode="live", db_path=Path(tmp) / "market.sqlite3", motoko_repo=Path(tmp) / "missing")
            text = json.dumps(report, sort_keys=True)
            self.assertFalse(report["ok"])
            self.assertIn("blockers", report)
            self.assertNotIn("sk_test_should_not_leak", text)
            self.assertNotIn("whsec_should_not_leak", text)
            self.assertNotIn("ghp_should_not_leak", text)

    def test_live_mode_refuses_without_fabricating_success(self):
        report = live_refusal_report(motoko_repo=Path("/definitely/missing"))
        self.assertFalse(report["ok"])
        self.assertEqual(report["stage"], "preflight")
        self.assertIn("fallback", report)

    def test_local_bundle_validates_replays_and_detects_tampering(self):
        if not MOTOKO_REPO.exists():
            self.skipTest("external Motoko issue #1 fixture repo is unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            bundle_dir = Path(tmp) / "bundle"
            result = run_local_demo(db_path=Path(tmp) / "market.sqlite3", motoko_repo=MOTOKO_REPO, bundle_dir=bundle_dir)
            validation = validate_bundle(bundle_dir)
            replay = replay_bundle(bundle_dir)

            self.assertTrue(result["ok"])
            self.assertTrue(validation["ok"])
            self.assertTrue(replay["ok"])
            self.assertTrue(validation["fake_provider"])
            self.assertEqual(validation["summary"]["mode_badge"], "Local simulation")
            self.assertTrue((bundle_dir / "dashboard.html").exists())

            bundle_json = bundle_dir / "bundle.json"
            data = json.loads(bundle_json.read_text(encoding="utf-8"))
            data["summary"]["pitch"] = "tampered"
            bundle_json.write_text(json.dumps(data, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
            tampered = validate_bundle(bundle_dir)
            self.assertFalse(tampered["ok"])
            self.assertIn("digest mismatch for bundle.json", tampered["mismatches"])

    def test_winning_bundle_has_truth_matrix_and_rehearses_repeatedly(self):
        if not MOTOKO_REPO.exists():
            self.skipTest("external Motoko issue #1 fixture repo is unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            bundle_dir = Path(tmp) / "winning-run"
            result = run_winning_bundle(db_path=Path(tmp) / "market.sqlite3", motoko_repo=MOTOKO_REPO, bundle_dir=bundle_dir)
            validation = validate_bundle(bundle_dir)
            rehearsal = rehearse_demo(mode="replay", bundle_dir=bundle_dir, repeats=3)

            self.assertTrue(result["ok"])
            self.assertTrue(validation["ok"])
            self.assertEqual(validation["mode"], "mixed")
            self.assertEqual(validation["summary"]["mode_badge"], "Mixed real/fallback")
            self.assertEqual(validation["truth_matrix"]["overall_status"], "mixed-real-fallback")
            self.assertGreaterEqual(len(validation["truth_matrix"]["rows"]), 5)
            self.assertTrue((bundle_dir / "attestation.json").exists())
            self.assertTrue((bundle_dir / "evidence" / "truth-matrix.json").exists())
            self.assertTrue(rehearsal["ok"])
            self.assertEqual(rehearsal["repeat_count"], 3)
            self.assertEqual(len(rehearsal["stages"]), 3)

    def test_winning_bundle_rejects_fake_ids_in_real_rows(self):
        if not MOTOKO_REPO.exists():
            self.skipTest("external Motoko issue #1 fixture repo is unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            bundle_dir = Path(tmp) / "winning-run"
            run_winning_bundle(db_path=Path(tmp) / "market.sqlite3", motoko_repo=MOTOKO_REPO, bundle_dir=bundle_dir)
            bundle = json.loads((bundle_dir / "bundle.json").read_text(encoding="utf-8"))
            bundle["truth_matrix"]["rows"][0]["status"] = "real"
            bundle["truth_matrix"]["rows"][0]["safe_evidence"] = {"transfer": "fake_transfer_should_fail"}
            _rewrite_bundle_and_manifest(bundle_dir, bundle)

            validation = validate_bundle(bundle_dir)
            self.assertFalse(validation["ok"])
            self.assertIn("real row hermes_executable contains fake/test evidence id", validation["mismatches"])

    def test_winning_bundle_rejects_consistency_drift_and_secrets(self):
        if not MOTOKO_REPO.exists():
            self.skipTest("external Motoko issue #1 fixture repo is unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            bundle_dir = Path(tmp) / "winning-run"
            run_winning_bundle(db_path=Path(tmp) / "market.sqlite3", motoko_repo=MOTOKO_REPO, bundle_dir=bundle_dir)
            bundle = json.loads((bundle_dir / "bundle.json").read_text(encoding="utf-8"))
            bundle["consistency"]["currency"] = "EUR"
            bundle["consistency"]["accepted_receipt_id"] = "receipt_drift"
            _rewrite_bundle_and_manifest(bundle_dir, bundle)
            (bundle_dir / "evidence" / "leak.txt").write_text("whsec_should_fail\n", encoding="utf-8")

            validation = validate_bundle(bundle_dir)
            self.assertFalse(validation["ok"])
            self.assertIn("consistency currency does not match allocation", validation["mismatches"])
            self.assertIn("consistency receipt does not match allocation", validation["mismatches"])
            self.assertIn("secret-like pattern whsec_ found in evidence/leak.txt", validation["mismatches"])

    def test_rehearsal_replay_requires_existing_default_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(DemoPresentationError):
                rehearse_demo(mode="replay", bundle_dir=Path(tmp) / "missing")

    def test_reset_requires_confirmation_and_refuses_outside_demo(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(DemoPresentationError):
                reset_demo_state(Path(tmp), yes=False)
            with self.assertRaises(DemoPresentationError):
                reset_demo_state(Path(tmp), yes=True)


def _rewrite_bundle_and_manifest(bundle_dir: Path, bundle: dict) -> None:
    bundle_path = bundle_dir / "bundle.json"
    manifest_path = bundle_dir / "manifest.json"
    bundle_path.write_text(stable_json(bundle) + "\n", encoding="utf-8")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    digest = file_digest(bundle_path)
    manifest["files"]["bundle.json"] = digest
    manifest["bundle_digest"] = digest
    manifest_path.write_text(stable_json(manifest) + "\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
