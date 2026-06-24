from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_bounty.execution import scrubbed_env
from agent_bounty.nvidia_runtime import (
    adversarial_probe_plan,
    nvidia_runtime_status_report,
    policy_report,
    run_nvidia_sandbox_demo,
    safe_sandbox_env,
)


def fake_status(*, blockers: list[str] | None = None) -> dict[str, object]:
    blockers = blockers or ["docker executable not found on PATH"]
    return {
        "schema": "agent-bounty-nvidia-runtime-status-v1",
        "ok": False,
        "real_backend_ready": False,
        "real_hermes_in_sandbox_ready": False,
        "sandbox_name": "agent-bounty-verifier",
        "docker": {"available": False, "blocker": blockers[0]},
        "openshell": {"available": False, "blocker": "openshell executable not found on PATH"},
        "openshell_cli": {"version": None},
        "nemoclaw": {"version": None},
        "policy": policy_report(),
        "inference": {
            "nvidia_api_key_configured": False,
            "nvidia_base_url_configured": False,
            "nvidia_base_url_host": None,
            "model_id": None,
        },
        "hermes": {"ok": False, "blockers": []},
        "blockers": blockers,
    }


class NvidiaRuntimeTests(unittest.TestCase):
    def test_status_aggregates_exact_blockers_without_secret_values(self):
        with mock.patch("agent_bounty.nvidia_runtime.docker_status_report", return_value={"available": False, "path": None, "info_ok": False, "blocker": "docker missing"}), mock.patch(
            "agent_bounty.nvidia_runtime.openshell_status",
            return_value={"available": False, "blocker": "sandbox missing", "backend_digest": "sha256:x", "policy_digest": "sha256:y"},
        ), mock.patch(
            "agent_bounty.nvidia_runtime.command_status",
            side_effect=[
                {"command": "openshell", "available": False, "path": None, "version": None, "blocker": "openshell missing"},
                {"command": "nemoclaw", "available": False, "path": None, "version": None, "blocker": "nemoclaw missing"},
            ],
        ), mock.patch(
            "agent_bounty.nvidia_runtime.hermes_status_report",
            return_value={"ok": False, "hermes_cli": {}, "provider": {}, "blockers": ["no provider"]},
        ), mock.patch.dict(os.environ, {"NVIDIA_API_KEY": "nvidia_sentinel_should_not_leak"}, clear=False):
            status = nvidia_runtime_status_report()
        payload = json.dumps(status, sort_keys=True)
        self.assertFalse(status["ok"])
        self.assertIn("docker missing", status["blockers"])
        self.assertIn("openshell executable not found on PATH", status["blockers"])
        self.assertNotIn("nvidia_sentinel_should_not_leak", payload)

    def test_policy_report_has_stable_project_owned_digests(self):
        report = policy_report()
        self.assertTrue(report["policy_exists"])
        self.assertTrue(report["manifest_exists"])
        self.assertTrue(str(report["policy_digest"]).startswith("sha256:"))
        self.assertTrue(str(report["manifest_digest"]).startswith("sha256:"))
        self.assertTrue(str(report["effective_policy_digest"]).startswith("sha256:"))
        self.assertEqual(report["manifest"]["schema"], "agent-bounty-openshell-manifest-v1")

    def test_shared_scrubber_and_sandbox_env_filter_nvidia_credentials(self):
        scrubbed = scrubbed_env({"NVIDIA_API_KEY": "nvapi_secret", "AGENT_BOUNTY_NVIDIA_MODEL_ID": "safe-model", "TERM": "xterm"})
        self.assertNotIn("NVIDIA_API_KEY", scrubbed)
        sandbox_env = safe_sandbox_env({"NVIDIA_API_KEY": "nvapi_secret", "AGENT_BOUNTY_NVIDIA_MODEL_ID": "safe-model", "TERM": "xterm"})
        self.assertNotIn("NVIDIA_API_KEY", sandbox_env)
        self.assertNotIn("AGENT_BOUNTY_NVIDIA_MODEL_ID", sandbox_env)
        self.assertEqual(sandbox_env["TERM"], "xterm")

    def test_demo_fallback_bundle_is_truthfully_labeled_and_secret_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            bundle = tmp_path / "bundle"
            with mock.patch("agent_bounty.nvidia_runtime.nvidia_runtime_status_report", return_value=fake_status()), mock.patch.dict(
                os.environ,
                {"NVIDIA_API_KEY": "nvidia_sentinel_should_not_leak", "STRIPE_TEST_SECRET_KEY": "stripe_sentinel_should_not_leak"},
                clear=False,
            ):
                result = run_nvidia_sandbox_demo(
                    motoko_repo=tmp_path / "missing-motoko",
                    bundle_dir=bundle,
                    require_real=False,
                    base_commit="base",
                    intermediate_commit="intermediate",
                    final_commit="final",
                )
            self.assertTrue(result["ok"])
            self.assertFalse(result["real_backend"])
            self.assertFalse(result["real_hermes_in_sandbox"])
            self.assertTrue(result["bundle_digest"].startswith("sha256:"))
            payload = (bundle / "nvidia-sandbox-demo.json").read_text(encoding="utf-8")
            self.assertNotIn("nvidia_sentinel_should_not_leak", payload)
            self.assertNotIn("stripe_sentinel_should_not_leak", payload)
            self.assertIn('"status": "not_run"', payload)

    def test_require_real_fails_before_fallback_claims(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("agent_bounty.nvidia_runtime.nvidia_runtime_status_report", return_value=fake_status(blockers=["docker missing"])):
                result = run_nvidia_sandbox_demo(
                    motoko_repo=Path(tmp) / "missing-motoko",
                    bundle_dir=Path(tmp) / "bundle",
                    require_real=True,
                    base_commit="base",
                    intermediate_commit="intermediate",
                    final_commit="final",
                )
        self.assertFalse(result["ok"])
        self.assertFalse(result["real_backend"])
        self.assertIn("docker missing", result["blocker"])

    def test_adversarial_probe_plan_covers_required_denials(self):
        probes = {row["id"] for row in adversarial_probe_plan()}
        self.assertGreaterEqual(len(probes), 10)
        self.assertIn("deny_github_api", probes)
        self.assertIn("deny_stripe_api", probes)
        self.assertIn("sentinel_absent", probes)
        self.assertIn("path_escape_blocked", probes)


if __name__ == "__main__":
    unittest.main()
