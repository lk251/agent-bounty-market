from __future__ import annotations

import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from agent_bounty.operator_submission import (
    MANUAL_MEDIA_REPORT_SCHEMA,
    OPERATOR_STATE_SCHEMA,
    finalize_submission,
    operator_state_report,
    render_tweet_variants,
    video_check_report,
    x_character_count,
)
from agent_bounty.submission_check import submission_check_report


REPO_ROOT = Path(__file__).resolve().parents[1]


class OperatorSubmissionTests(unittest.TestCase):
    def test_operator_state_path_is_ignored_and_example_is_tracked(self):
        ignore_text = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn(".demo/", ignore_text)
        self.assertTrue((REPO_ROOT / "submission" / "operator-submission.example.json").is_file())

    def test_secret_like_operator_state_is_rejected(self):
        with operator_fixture() as fixture:
            state = fixture.state()
            state["contact_email_or_handle"] = "sk_test_should_not_be_here"
            fixture.write_state(state)

            report = operator_state_report(fixture.state_path, root=REPO_ROOT, mode="prepost")

        self.assertFalse(report["ok"])
        self.assertIn("operator_secret_like_value", error_codes(report))

    def test_old_275_character_placeholder_draft_is_unsafe_with_real_url(self):
        old = (
            "Agent Bounty Market for the @NousResearch hackathon: fund a bounded software task, "
            "let agents claim work, verify the exact commit, and settle once. Truthful Mixed "
            "real/fallback demo with Stripe, GitHub, Hermes, and NVIDIA/OpenShell paths visible. "
            "@NVIDIAAI @stripe https://github.com/lk251/agent-bounty-market"
        )

        self.assertGreater(x_character_count(old), 280)

    def test_corrected_variants_pass_conservative_counter(self):
        with operator_fixture() as fixture:
            variants = render_tweet_variants(REPO_ROOT, fixture.state())

        self.assertEqual(len(variants), 4)
        for variant in variants:
            self.assertLessEqual(variant["x_count"], 280, variant["name"])
            self.assertIn("@NousResearch", variant["body"])
            self.assertIn("Mixed real/fallback", variant["body"])

    def test_multiple_urls_unicode_emoji_and_newlines_count_conservatively(self):
        text = "Café mañana résumé 🚀\nhttps://example.com/very/long/path https://github.com/lk251/agent-bounty-market"

        self.assertEqual(x_character_count("https://example.com/long"), 23)
        self.assertGreater(x_character_count(text), 23 * 2)

    def test_missing_video_fails(self):
        report = video_check_report(Path("/tmp/agent-bounty-missing-video.mp4"), ffprobe_path="")

        self.assertFalse(report["ok"])
        self.assertIn("missing_file", error_codes(report))

    def test_mocked_ffprobe_rejects_59s_and_181s(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            video = tmp_path / "video.mp4"
            video.write_bytes(b"not really video")
            for seconds, code in [(59, "duration_too_short"), (181, "duration_too_long")]:
                probe = write_ffprobe(tmp_path, duration=seconds)
                report = video_check_report(video, ffprobe_path=str(probe))
                self.assertFalse(report["ok"], seconds)
                self.assertIn(code, error_codes(report))

    def test_valid_manual_media_report_is_accepted(self):
        with operator_fixture() as fixture:
            report = video_check_report(fixture.video_path, ffprobe_path="", manual_report=fixture.manual_report_path)

        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual(report["metadata"]["source"], "manual-attestation")

    def test_ffprobe_missing_requires_manual_attestation(self):
        with operator_fixture() as fixture:
            report = video_check_report(fixture.video_path, ffprobe_path="")

        self.assertFalse(report["ok"])
        self.assertIn("ffprobe_missing", error_codes(report))

    def test_submission_prepost_uses_state_but_final_requires_posting_fields(self):
        with copied_submission_tree() as root:
            with operator_fixture(root=root) as fixture:
                prepost = submission_check_report(root, entry=True, prepost=True, state=fixture.state_path)
                final = submission_check_report(root, entry=True, final=True, state=fixture.state_path)

        self.assertTrue(prepost["ok"], prepost["errors"])
        self.assertFalse(final["ok"])
        self.assertIn("operator_field_missing", flattened_error_codes(final))

    def test_finalizer_writes_local_files_without_touching_tracked_docs(self):
        with operator_fixture() as fixture:
            original = (REPO_ROOT / "submission" / "TYPEFORM_FINAL.md").read_text(encoding="utf-8")
            report = finalize_submission(state_path=fixture.state_path, output_dir=fixture.output_path, root=REPO_ROOT)
            rendered = (fixture.output_path / "FINAL_TYPEFORM.md").read_text(encoding="utf-8")

        self.assertTrue(report["ok"], report["errors"])
        self.assertIn("Bounty Market Test Team", rendered)
        self.assertEqual((REPO_ROOT / "submission" / "TYPEFORM_FINAL.md").read_text(encoding="utf-8"), original)
        self.assertIn("[TEAM_NAME]", original)

    def test_truth_status_inconsistency_is_rejected(self):
        with copied_submission_tree() as root:
            tweet = root / "submission" / "TWEET.md"
            tweet.write_text(tweet.read_text(encoding="utf-8").replace("Mixed real/fallback", "All live"), encoding="utf-8")
            report = submission_check_report(root, entry=True)

        self.assertFalse(report["ok"])
        self.assertIn("tweet_missing_truth_boundary", error_codes(report))

    def test_unavailable_release_tag_is_rejected_in_final_mode(self):
        with copied_submission_tree() as root, operator_fixture(root=root) as fixture:
            state = fixture.state(final=True)
            fixture.write_state(state)
            report = submission_check_report(root, entry=True, final=True, state=fixture.state_path)

        self.assertFalse(report["ok"])
        self.assertTrue(any(code.startswith("release_tag_") for code in (flattened_error_codes(report) | error_codes(report))))

    def test_finalization_is_deterministic(self):
        with operator_fixture() as fixture:
            first = finalize_submission(state_path=fixture.state_path, output_dir=fixture.output_path, root=REPO_ROOT, check=True)
            second = finalize_submission(state_path=fixture.state_path, output_dir=fixture.output_path, root=REPO_ROOT, check=True)

        self.assertEqual(first["file_digests"], second["file_digests"])

    def test_checker_report_does_not_print_operator_values(self):
        with operator_fixture() as fixture:
            report = operator_state_report(fixture.state_path, root=REPO_ROOT, mode="prepost")
            text = json.dumps(report, sort_keys=True)

        self.assertTrue(report["ok"], report["errors"])
        self.assertNotIn("Bounty Market Test Team", text)
        self.assertNotIn("alice@example.invalid", text)


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


def operator_fixture(root: Path | None = None):
    temp = tempfile.TemporaryDirectory()
    tmp_path = Path(temp.name)

    class _Fixture:
        def __init__(self) -> None:
            self.root = root or REPO_ROOT
            self.video_path = tmp_path / "final-video.mp4"
            self.video_path.write_bytes(b"fake mp4 bytes")
            self.manual_report_path = tmp_path / "manual-media.json"
            self.manual_report_path.write_text(
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
                        "created_at": "2026-06-25T00:00:00Z",
                    },
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            self.state_path = tmp_path / "operator-submission.json"
            self.output_path = tmp_path / "final-submission"
            self.write_state(self.state())

        def state(self, *, final: bool = False) -> dict:
            data = {
                "schema": OPERATOR_STATE_SCHEMA,
                "repo_url": "https://github.com/lk251/agent-bounty-market",
                "video_file_path": str(self.video_path),
                "video_filename": "agent-bounty-market-hackathon-20260625.mp4",
                "team_name": "Bounty Market Test Team",
                "team_member_names": ["Alice Example"],
                "contact_email_or_handle": "alice@example.invalid",
                "final_tweet_url": "",
                "discord_confirmation_path": "",
                "typeform_confirmation_path": "",
                "bundle_backup_path": str(tmp_path / "bundle-backup"),
                "manual_media_report_path": str(self.manual_report_path),
                "submission_timestamp": "2026-06-25T00:00:00Z",
            }
            if final:
                data.update(
                    {
                        "final_tweet_url": "https://x.com/example/status/1234567890123456789",
                        "discord_confirmation_path": str(tmp_path / "discord-confirmation.txt"),
                        "typeform_confirmation_path": str(tmp_path / "typeform-confirmation.txt"),
                    }
                )
            return data

        def write_state(self, data: dict) -> None:
            self.state_path.write_text(json.dumps(data, sort_keys=True) + "\n", encoding="utf-8")

    class _Context:
        def __enter__(self) -> _Fixture:
            return _Fixture()

        def __exit__(self, exc_type, exc, tb) -> None:
            temp.cleanup()

    return _Context()


def write_ffprobe(root: Path, *, duration: int) -> Path:
    script = root / f"ffprobe-{duration}.py"
    payload = {
        "format": {"duration": str(duration), "format_name": "mov,mp4,m4a,3gp,3g2,mj2"},
        "streams": [
            {"codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080, "avg_frame_rate": "30/1"},
            {"codec_type": "audio", "codec_name": "aac"},
        ],
    }
    script.write_text(
        f"#!{sys.executable}\n"
        "import json\n"
        f"print({json.dumps(json.dumps(payload))})\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


def error_codes(report: dict) -> set[str]:
    return {str(error["code"]) for error in report.get("errors", [])}


def flattened_error_codes(report: dict) -> set[str]:
    text = json.dumps(report, sort_keys=True)
    return set(re.findall(r'"code": "([^"]+)"', text))
