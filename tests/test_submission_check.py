from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from agent_bounty.operator_submission import MANUAL_MEDIA_REPORT_SCHEMA, OPERATOR_STATE_SCHEMA
from agent_bounty.submission_check import extract_tweet_variants, submission_check_report, tweet_character_count


REPO_ROOT = Path(__file__).resolve().parents[1]


class SubmissionCheckTests(unittest.TestCase):
    def test_submission_check_passes_current_docs(self):
        report = submission_check_report(REPO_ROOT)
        self.assertTrue(report["ok"], report["errors"])
        self.assertIn("submission/JUDGE_QA.md", report["checked_files"])
        self.assertIn("demo/bundles/winning-run/bundle.json", report["checked_files"])

    def test_injected_forbidden_phrase_fails(self):
        with copied_submission_tree() as root:
            target = root / "submission" / "SUBMISSION.md"
            target.write_text(target.read_text(encoding="utf-8") + "\nThis is fully live now.\n", encoding="utf-8")
            report = submission_check_report(root)
        self.assertFalse(report["ok"])
        self.assertIn("banned_term", error_codes(report))

    def test_issue_29_stale_judge_phrases_fail(self):
        stale_phrases = [
            "idle-only",
            "Reward exceeds maximum bounty amount",
            "Minimum remaining reserve would be violated",
            "Policy and budget select one bounded bounty while alternatives can decline",
            "alternatives can decline",
        ]
        for phrase in stale_phrases:
            with self.subTest(phrase=phrase), copied_submission_tree() as root:
                target = root / "submission" / "SUBMISSION.md"
                target.write_text(target.read_text(encoding="utf-8") + f"\n{phrase}\n", encoding="utf-8")
                report = submission_check_report(root)
            self.assertFalse(report["ok"], phrase)
            self.assertIn("banned_term", error_codes(report))

    def test_missing_limitations_and_truth_status_fail(self):
        with copied_submission_tree() as root:
            (root / "submission" / "LIMITATIONS.md").unlink()
            script = root / "submission" / "DEMO_SCRIPT_90S.md"
            script.write_text(script.read_text(encoding="utf-8").replace("Mixed real/fallback", "mixed boundary"), encoding="utf-8")
            report = submission_check_report(root)
        self.assertFalse(report["ok"])
        self.assertIn("missing_required_doc", error_codes(report))
        self.assertIn("missing_truth_boundary", error_codes(report))
        self.assertIn("demo_script_missing_mode", error_codes(report))

    def test_secret_like_text_fails(self):
        with copied_submission_tree() as root:
            target = root / "submission" / "SPONSOR_INTEGRATION.md"
            target.write_text(target.read_text(encoding="utf-8") + "\nSTRIPE_TEST_SECRET_KEY=sk_test_should_not_leak\n", encoding="utf-8")
            report = submission_check_report(root)
        self.assertFalse(report["ok"])
        self.assertIn("secret_like_text", error_codes(report))

    def test_sponsor_table_contains_required_rows(self):
        report = submission_check_report(REPO_ROOT)
        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual(report["required_sponsor_rows"], ["Stripe", "GitHub", "Hermes", "NVIDIA/OpenShell"])
        text = (REPO_ROOT / "submission" / "SPONSOR_INTEGRATION.md").read_text(encoding="utf-8")
        for row in report["required_sponsor_rows"]:
            self.assertIn(row, text)

    def test_demo_scripts_include_mode_boundary(self):
        for name in ["DEMO_SCRIPT_90S.md", "DEMO_SCRIPT_3MIN.md"]:
            text = (REPO_ROOT / "submission" / name).read_text(encoding="utf-8")
            self.assertIn("Mixed real/fallback", text)
            self.assertIn("fallback", text.lower())
            self.assertIn("blocked", text.lower())

    def test_entry_check_passes_current_package_in_draft_mode(self):
        report = submission_check_report(REPO_ROOT, entry=True)
        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual(report["mode"], "entry-draft")
        self.assertGreater(report["entry"]["placeholder_count"], 0)
        self.assertEqual(len(report["entry"]["tweet_variants"]), 4)

    def test_entry_prepost_uses_default_ignored_operator_state(self):
        with copied_submission_tree() as root:
            write_default_operator_state(root)
            report = submission_check_report(root, entry=True, prepost=True)

        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual(report["mode"], "entry-prepost")
        self.assertEqual(report["entry"]["operator"]["mode"], "prepost")
        self.assertTrue(report["entry"]["operator"]["ok"])

    def test_tweet_variants_have_measured_counts_and_required_tag(self):
        text = (REPO_ROOT / "submission" / "TWEET.md").read_text(encoding="utf-8")
        variants = extract_tweet_variants(text)
        self.assertEqual(len(variants), 4)
        for variant in variants:
            self.assertEqual(variant["declared_count"], tweet_character_count(variant["body"]), variant["name"])
            self.assertLessEqual(tweet_character_count(variant["body"]), 280)
            self.assertIn("@NousResearch", variant["body"])
            self.assertIn("Mixed real/fallback", variant["body"])

    def test_entry_final_mode_rejects_operator_placeholders(self):
        report = submission_check_report(REPO_ROOT, entry=True, final=True)
        self.assertFalse(report["ok"])
        self.assertIn("final_placeholder", error_codes(report))

    def test_entry_missing_required_doc_fails(self):
        with copied_submission_tree() as root:
            (root / "submission" / "DISCORD_SUBMISSION.md").unlink()
            report = submission_check_report(root, entry=True)
        self.assertFalse(report["ok"])
        self.assertIn("missing_entry_doc", error_codes(report))

    def test_entry_missing_nous_tag_fails(self):
        with copied_submission_tree() as root:
            tweet = root / "submission" / "TWEET.md"
            tweet.write_text(tweet.read_text(encoding="utf-8").replace("@NousResearch", "@OtherLab"), encoding="utf-8")
            report = submission_check_report(root, entry=True)
        self.assertFalse(report["ok"])
        self.assertIn("tweet_missing_nous_tag", error_codes(report))

    def test_entry_character_count_mismatch_fails(self):
        with copied_submission_tree() as root:
            tweet = root / "submission" / "TWEET.md"
            tweet.write_text(tweet.read_text(encoding="utf-8").replace("Character count: 251", "Character count: 250", 1), encoding="utf-8")
            report = submission_check_report(root, entry=True)
        self.assertFalse(report["ok"])
        self.assertIn("tweet_character_count_mismatch", error_codes(report))

    def test_entry_stale_bundle_digest_fails(self):
        with copied_submission_tree() as root:
            current_digest = (
                root / "demo" / "bundles" / "winning-run" / "manifest.json"
            )
            digest = json.loads(current_digest.read_text(encoding="utf-8"))["bundle_digest"]
            checklist = root / "submission" / "SUBMISSION_PORTAL_CHECKLIST.md"
            checklist.write_text(
                checklist.read_text(encoding="utf-8").replace(
                    digest,
                    "sha256:" + "0" * 64,
                ),
                encoding="utf-8",
            )
            report = submission_check_report(root, entry=True)
        self.assertFalse(report["ok"])
        self.assertIn("entry_bundle_digest_missing", error_codes(report))

    def test_entry_duration_outside_requirements_fails(self):
        with copied_submission_tree() as root:
            video = root / "submission" / "VIDEO_METADATA.md"
            video.write_text(video.read_text(encoding="utf-8").replace("1-3 minutes", "3-4 minutes"), encoding="utf-8")
            report = submission_check_report(root, entry=True)
        self.assertFalse(report["ok"])
        self.assertIn("entry_video_duration_requirement", error_codes(report))


def copied_submission_tree():
    temp = tempfile.TemporaryDirectory()
    root = Path(temp.name)
    shutil.copy2(REPO_ROOT / "README.md", root / "README.md")
    shutil.copytree(REPO_ROOT / "submission", root / "submission")
    bundle_root = root / "demo" / "bundles"
    bundle_root.mkdir(parents=True)
    shutil.copytree(REPO_ROOT / "demo" / "bundles" / "winning-run", bundle_root / "winning-run")

    class _Context:
        def __enter__(self) -> Path:
            return root

        def __exit__(self, exc_type, exc, tb) -> None:
            temp.cleanup()

    return _Context()


def write_default_operator_state(root: Path) -> None:
    demo = root / ".demo"
    demo.mkdir()
    video = demo / "agent-bounty-market-hackathon-test.mp4"
    video.write_bytes(b"fake mp4 bytes")
    manual = demo / "manual-media.json"
    manual.write_text(
        json.dumps(
            {
                "schema": MANUAL_MEDIA_REPORT_SCHEMA,
                "duration_seconds": 120,
                "container": "mp4",
                "video_codec": "h264",
                "audio_codec": "aac",
                "width": 1920,
                "height": 1080,
                "frame_rate": 30,
                "audio_stream_present": True,
                "attested_by": "operator",
                "created_at": "2026-06-28T00:00:00Z",
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    state = {
        "schema": OPERATOR_STATE_SCHEMA,
        "repo_url": "https://github.com/lk251/agent-bounty-market",
        "video_file_path": str(video),
        "video_filename": video.name,
        "team_name": "Bounty Market Test Team",
        "team_member_names": ["Alice Example"],
        "contact_email_or_handle": "alice@example.invalid",
        "final_tweet_url": "",
        "discord_confirmation_path": "",
        "typeform_confirmation_path": "",
        "bundle_backup_path": str(demo / "bundle-backup"),
        "manual_media_report_path": str(manual),
        "submission_timestamp": "2026-06-28T00:00:00Z",
    }
    (demo / "operator-submission.json").write_text(json.dumps(state, sort_keys=True) + "\n", encoding="utf-8")


def error_codes(report: dict) -> set[str]:
    return {str(error["code"]) for error in report["errors"]}
