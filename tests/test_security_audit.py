from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_bounty.security_audit import scan_for_secrets, security_audit_report


REPO_ROOT = Path(__file__).resolve().parents[1]


class SecurityAuditTests(unittest.TestCase):
    def test_quick_security_audit_passes_current_tree(self):
        report = security_audit_report(REPO_ROOT, full=False)

        self.assertTrue(report["ok"], report)
        self.assertEqual(report["schema"], "agent-bounty-security-audit-v1")
        self.assertEqual(report["mode"], "quick")
        self.assertTrue(report["model_check"]["ok"])
        self.assertEqual(report["mutation_score"]["passed"], report["mutation_score"]["total"])
        self.assertTrue(report["fuzz"]["ok"])
        self.assertTrue(report["filesystem"]["ok"])
        self.assertTrue(report["secret_scan"]["ok"])
        self.assertIn("ABM-SEC-001", {finding["id"] for finding in report["findings"]})

    def test_secret_scan_redacts_hits_and_ignores_placeholders(self):
        fake_secret = "sk_test_" + "1234567890ABCDEF"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "sample.txt").write_text(
                "placeholder sk_test_placeholder\n"
                f"real-looking {fake_secret}\n",
                encoding="utf-8",
            )
            git(root, "init")
            git(root, "config", "user.email", "audit@example.invalid")
            git(root, "config", "user.name", "Audit")
            git(root, "add", "sample.txt")
            git(root, "commit", "-m", "sample")

            report = scan_for_secrets(root, include_history=False, history_limit=0)

        self.assertFalse(report["ok"])
        self.assertEqual(report["fail_count"], 1)
        hit = report["hits"][0]
        self.assertEqual(hit["kind"], "stripe_secret_key")
        self.assertIn("match_digest", hit)
        self.assertNotIn(fake_secret, str(report))


def git(root: Path, *args: str) -> str:
    import subprocess

    result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
    if result.returncode != 0:
        raise AssertionError(result.stderr or result.stdout)
    return result.stdout
