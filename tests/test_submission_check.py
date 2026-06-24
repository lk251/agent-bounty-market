from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from agent_bounty.submission_check import submission_check_report


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


def error_codes(report: dict) -> set[str]:
    return {str(error["code"]) for error in report["errors"]}
