from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_bounty.demo_presentation import demo_preflight_report
from agent_bounty.live_setup import (
    live_setup_wizard_report,
    render_live_setup_text,
    stripe_setup_status_report,
    write_live_setup_runbook,
)
from agent_bounty.util import stable_json


class LiveSetupWizardTests(unittest.TestCase):
    def test_all_components_missing_reports_actionable_blockers(self):
        with patched_components(hermes=missing_hermes(), nvidia=missing_nvidia(), github=missing_github(), stripe=missing_stripe()):
            report = live_setup_wizard_report()
        self.assertFalse(report["ok"])
        self.assertIn("hermes_nvidia: Hermes executable/version is not ready", report["blockers"])
        self.assertIn("openshell_nemoclaw: Docker available is not ready", report["blockers"])
        self.assertIn("github: gh CLI available/auth status is not ready", report["blockers"])
        self.assertIn("stripe: Test secret key configured is not ready", report["blockers"])
        self.assertIn("python -m agent_bounty hermes-status --discover-models", stable_json(report))

    def test_only_hermes_present_keeps_other_components_blocked(self):
        with patched_components(hermes=ready_hermes(), nvidia=missing_nvidia(), github=missing_github(), stripe=missing_stripe()):
            report = live_setup_wizard_report()
        components = {row["id"]: row for row in report["components"]}
        self.assertTrue(components["hermes_nvidia"]["ready"])
        self.assertFalse(components["openshell_nemoclaw"]["ready"])
        self.assertFalse(components["github"]["ready"])
        self.assertFalse(components["stripe"]["ready"])
        self.assertIn("python -m agent_bounty demo-hermes-decisions", components["hermes_nvidia"]["next_commands"][0])

    def test_stripe_partially_configured_has_no_network_requirement(self):
        with mock.patch.dict(os.environ, {"AGENT_BOUNTY_STRIPE_SANDBOX": "1"}, clear=True), mock.patch(
            "agent_bounty.live_setup.stripe_package_version", return_value="15.2.0"
        ), mock.patch("agent_bounty.live_setup.stripe_cli_version", return_value="stripe version 1.41.2"):
            status = stripe_setup_status_report()
        self.assertFalse(status["ok"])
        self.assertTrue(status["sandbox_enabled"])
        self.assertIn("set STRIPE_TEST_SECRET_KEY", status["blockers"])
        self.assertIn("set STRIPE_TEST_WEBHOOK_SECRET from stripe listen", status["blockers"])
        self.assertIn("set STRIPE_TEST_CONNECTED_ACCOUNT_ID to a test connected account", status["blockers"])

    def test_live_secret_values_are_redacted(self):
        env = {
            "NVIDIA_API_KEY": "nvidia_sentinel_should_not_leak",
            "STRIPE_TEST_SECRET_KEY": "sk_test_should_not_leak",
            "STRIPE_TEST_WEBHOOK_SECRET": "whsec_should_not_leak",
            "AGENT_BOUNTY_GITHUB_TOKEN": "ghp_should_not_leak",
        }
        hermes = missing_hermes(blocker="bad key nvidia_sentinel_should_not_leak")
        github = missing_github(blocker="bad token ghp_should_not_leak")
        stripe = missing_stripe(blocker="bad key sk_test_should_not_leak and whsec_should_not_leak")
        with mock.patch.dict(os.environ, env, clear=False), patched_components(hermes=hermes, nvidia=missing_nvidia(), github=github, stripe=stripe):
            report = live_setup_wizard_report()
            text = render_live_setup_text(report)
        payload = stable_json(report) + text
        self.assertNotIn("nvidia_sentinel_should_not_leak", payload)
        self.assertNotIn("sk_test_should_not_leak", payload)
        self.assertNotIn("whsec_should_not_leak", payload)
        self.assertNotIn("ghp_should_not_leak", payload)

    def test_runbook_contains_placeholders_not_actual_env_values(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ,
            {"STRIPE_TEST_SECRET_KEY": "sk_test_should_not_leak", "STRIPE_TEST_WEBHOOK_SECRET": "whsec_should_not_leak", "NVIDIA_API_KEY": "nvapi-secret"},
            clear=False,
        ), patched_components(hermes=missing_hermes(), nvidia=missing_nvidia(), github=missing_github(), stripe=missing_stripe()):
            report = live_setup_wizard_report()
            result = write_live_setup_runbook(Path(tmp) / "LIVE_SETUP_RUNBOOK.md", report)
            text = Path(result["path"]).read_text(encoding="utf-8")
        self.assertTrue(result["ok"])
        self.assertIn("STRIPE_TEST_SECRET_KEY=sk_test_...", text)
        self.assertIn("STRIPE_TEST_WEBHOOK_SECRET=whsec_...", text)
        self.assertIn("NVIDIA_API_KEY=...", text)
        self.assertNotIn("sk_test_should_not_leak", text)
        self.assertNotIn("whsec_should_not_leak", text)
        self.assertNotIn("nvapi-secret", text)

    def test_json_output_is_stable_and_machine_readable(self):
        with patched_components(hermes=missing_hermes(), nvidia=missing_nvidia(), github=missing_github(), stripe=missing_stripe()):
            report = live_setup_wizard_report()
        encoded = stable_json(report)
        decoded = json.loads(encoded)
        self.assertEqual(decoded["schema"], "agent-bounty-live-setup-wizard-v1")
        self.assertEqual([row["id"] for row in decoded["components"]], ["hermes_nvidia", "openshell_nemoclaw", "github", "stripe"])

    def test_preflight_and_wizard_blocker_lists_agree(self):
        with tempfile.TemporaryDirectory() as tmp, patched_components(hermes=missing_hermes(), nvidia=missing_nvidia(), github=missing_github(), stripe=missing_stripe()):
            wizard = live_setup_wizard_report()
            preflight = demo_preflight_report(mode="live", db_path=Path(tmp) / "market.sqlite3", motoko_repo=Path(tmp))
        self.assertEqual(preflight["blockers"], wizard["preflight_blockers"])

    def test_all_fake_ready_clients_report_next_commands_without_secrets(self):
        with patched_components(hermes=ready_hermes(), nvidia=ready_nvidia(), github=ready_github(), stripe=ready_stripe()):
            report = live_setup_wizard_report()
        payload = stable_json(report)
        self.assertTrue(report["ok"], report)
        self.assertIn("python -m agent_bounty demo-hermes-decisions", payload)
        self.assertIn("python -m agent_bounty demo-nvidia-sandbox", payload)
        self.assertIn("python -m agent_bounty demo-github-motoko-live", payload)
        self.assertIn("python -m agent_bounty demo-economic-loop-live", payload)
        self.assertNotIn("sk_test_", payload)
        self.assertNotIn("whsec_", payload)
        self.assertNotIn("ghp_", payload)


def patched_components(*, hermes: dict, nvidia: dict, github: dict, stripe: dict):
    return mock.patch.multiple(
        "agent_bounty.live_setup",
        hermes_status_report=mock.Mock(return_value=hermes),
        nvidia_runtime_status_report=mock.Mock(return_value=nvidia),
        github_status_report=mock.Mock(return_value=github),
        stripe_setup_status_report=mock.Mock(return_value=stripe),
        _skills_manifest_current=mock.Mock(return_value=hermes.get("_skills_current", False)),
    )


def missing_hermes(*, blocker: str = "set NVIDIA_API_KEY for real NVIDIA NIM/Nemotron") -> dict:
    return {
        "ok": False,
        "hermes": {"path": None, "version": {"ok": False, "error": "Hermes CLI not found"}},
        "provider": {"nvidia_api_key_present": False, "model_id": "not-configured", "context_tokens": None},
        "wrappers": {"project_command_configured": False, "solver_command_configured": False},
        "skills": {"manifest_digest": "sha256:skills", "hermes_skill_root": "/tmp/missing"},
        "blockers": [blocker],
        "_skills_current": False,
    }


def ready_hermes() -> dict:
    return {
        "ok": True,
        "hermes": {"path": "/home/mares/.local/bin/hermes", "version": {"ok": True, "stdout_excerpt": "Hermes Agent v0.17.0"}},
        "provider": {"nvidia_api_key_present": True, "model_id": "nvidia/nemotron", "context_tokens": 65536},
        "wrappers": {"project_command_configured": True, "solver_command_configured": True},
        "skills": {"manifest_digest": "sha256:skills", "hermes_skill_root": "/tmp/ready"},
        "blockers": [],
        "_skills_current": True,
    }


def missing_nvidia() -> dict:
    return {
        "ok": False,
        "docker": {"available": False, "blocker": "docker executable not found on PATH"},
        "openshell": {"available": False, "blocker": "openshell executable not found on PATH"},
        "openshell_cli": {"path": None, "version": None, "blocker": "openshell executable not found on PATH"},
        "nemoclaw": {"path": None, "available": False, "version": None, "blocker": "nemoclaw executable not found on PATH"},
        "policy": {"policy_digest": "sha256:policy", "manifest_digest": "sha256:manifest", "effective_policy_digest": "sha256:effective"},
        "blockers": ["docker executable not found on PATH", "openshell executable not found on PATH"],
    }


def ready_nvidia() -> dict:
    return {
        "ok": True,
        "docker": {"available": True, "path": "/run/current-system/sw/bin/docker"},
        "openshell": {"available": True, "blocker": None},
        "openshell_cli": {"path": "/run/current-system/sw/bin/openshell", "version": "openshell 0.0.68", "blocker": None},
        "nemoclaw": {"path": "/run/current-system/sw/bin/nemoclaw", "available": True, "version": "nemoclaw 0.1.0", "blocker": None},
        "policy": {"policy_digest": "sha256:policy", "manifest_digest": "sha256:manifest", "effective_policy_digest": "sha256:effective"},
        "blockers": [],
    }


def missing_github(*, blocker: str = "set AGENT_BOUNTY_GITHUB_TOKEN or GH_TOKEN to a fine-grained development token") -> dict:
    return {
        "ok": False,
        "enabled": False,
        "development_transport": True,
        "repository_configured": False,
        "repository": None,
        "webhook_secret_configured": False,
        "gh_cli": None,
        "required_capabilities": ["issues:write", "pull_requests:read", "statuses:write", "metadata:read"],
        "blockers": [blocker],
    }


def ready_github() -> dict:
    return {
        "ok": True,
        "enabled": True,
        "development_transport": True,
        "repository_configured": True,
        "repository": {"full_name": "lk251/motoko"},
        "webhook_secret_configured": True,
        "gh_cli": "gh version 2.0.0",
        "required_capabilities": ["issues:write", "pull_requests:read", "statuses:write", "metadata:read"],
        "blockers": [],
    }


def missing_stripe(*, blocker: str = "set STRIPE_TEST_SECRET_KEY") -> dict:
    return {
        "ok": False,
        "sandbox_enabled": False,
        "stripe_package_version": None,
        "stripe_cli": None,
        "secret_key_configured": False,
        "webhook_secret_configured": False,
        "connected_account_configured": False,
        "platform_account": None,
        "connected_account": None,
        "blockers": [blocker],
    }


def ready_stripe() -> dict:
    return {
        "ok": True,
        "sandbox_enabled": True,
        "stripe_package_version": "15.2.0",
        "stripe_cli": "stripe version 1.41.2",
        "secret_key_configured": True,
        "webhook_secret_configured": True,
        "connected_account_configured": True,
        "platform_account": {"id": "acct_platform", "country": "ES"},
        "connected_account": {"id": "acct_connected", "country": "ES"},
        "blockers": [],
    }


if __name__ == "__main__":
    unittest.main()
