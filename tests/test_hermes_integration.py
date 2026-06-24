from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_bounty.core import AgentBountyMarket
from agent_bounty.db import connect
from agent_bounty.hermes_integration import (
    HERMES_PROJECT_COMMAND_ENV,
    HERMES_SOLVER_COMMAND_ENV,
    hermes_status_report,
    install_hermes_skills,
    run_demo_hermes_decisions,
)
from agent_bounty.payments import FakePaymentGateway
from agent_bounty.project_agent import (
    DEFAULT_PROJECT_ID,
    HERMES_CLI_ENV,
    HERMES_RUN_ENV,
    HermesCliRuntime,
    evaluate_project_agent,
    setup_demo_project,
)
from agent_bounty.solver_agent import (
    HermesSolverAgentRuntime,
    evaluate_solver_agents,
    register_default_solver_profiles,
)
from agent_bounty.util import stable_json


def make_market(path: Path) -> AgentBountyMarket:
    return AgentBountyMarket(connect(path), FakePaymentGateway())


def write_project_wrapper(path: Path) -> None:
    path.write_text(
        """
import json, sys
request = json.loads(sys.stdin.read())
decisions = []
for candidate in request["candidates"]:
    is_valid = candidate.get("issue_number") == 1
    decisions.append({
        "schema": "project-agent-bounty-decision-v1",
        "candidate_id": candidate["candidate_id"],
        "decision": "fund" if is_valid else "decline",
        "issue_class": candidate.get("issue_class") or "unknown",
        "user_value": {"score": 8 if is_valid else 2, "reason": "wrapper fixture"},
        "verifiability": {"score": 9 if is_valid else 1, "verifier_id": candidate.get("verifier_id"), "reason": "wrapper fixture"},
        "estimated_solver_effort": {"low": 10, "likely": 45, "high": 90, "unit": "minutes"},
        "success_probability": 0.7 if is_valid else 0.0,
        "recommended_reward_cents": int(candidate.get("reward_hint_cents") or 0),
        "currency": candidate.get("currency") or "USD",
        "acceptance_contract": ({
            "title": candidate["title"],
            "issue_ref": f"{candidate['repo_full_name']}#{candidate['issue_number']}",
            "repo_full_name": candidate["repo_full_name"],
            "base_commit": candidate["base_commit"],
            "verifier_id": candidate["verifier_id"],
            "acceptance_summary": "protected verifier accepts"
        } if is_valid else {}),
        "unknowns": [] if is_valid else ["not enough evidence"],
        "risk_flags": [] if is_valid else ["declined-by-wrapper"],
        "evidence_refs": list(candidate.get("evidence_refs") or []),
        "model": "real-wrapper-fixture-model",
        "skill_versions": request.get("skill_versions") or {},
    })
print(json.dumps({"schema": "project-agent-bounty-decision-set-v1", "decisions": decisions}))
""".strip()
        + "\n",
        encoding="utf-8",
    )


def write_solver_wrapper(path: Path) -> None:
    path.write_text(
        """
import json, sys
request = json.loads(sys.stdin.read())
profile = request["profile"]
bounty = request["bounty"]
solver_id = profile["id"]
claim = solver_id == "solver_python_terminal_tui"
likely_cost = 350 if claim else 400
print(json.dumps({
    "schema": "solver-bounty-decision-v1",
    "solver_id": solver_id,
    "bounty_id": bounty["id"],
    "decision": "claim" if claim else "decline",
    "capability_match": {"score": 0.9 if claim else 0.1, "evidence": profile["specialization"].get("verified_history", [])},
    "success_probability_estimate": 0.75 if claim else 0.0,
    "estimated_cost_cents": {"low": 100, "likely": likely_cost, "high": 800},
    "estimated_minutes": {"low": 20, "likely": 45, "high": 120},
    "reward_cents": int(bounty["reward_amount"]),
    "expected_margin_cents": int(bounty["reward_amount"]) - likely_cost,
    "risk_flags": [] if claim else ["capability-mismatch"],
    "unknowns": ["wrapper fixture"],
    "plan": ["claim", "submit"] if claim else [],
    "model": "real-wrapper-fixture-model",
    "skill_versions": request.get("skill_versions") or {},
}))
""".strip()
        + "\n",
        encoding="utf-8",
    )


class HermesIntegrationTests(unittest.TestCase):
    def test_status_reports_missing_runtime_without_secret_values(self):
        with mock.patch.dict(os.environ, {"NVIDIA_API_KEY": "nvapi_secret_value"}, clear=False):
            result = hermes_status_report()
        payload = stable_json(result)
        self.assertEqual(result["schema"], "agent-bounty-hermes-status-v1")
        self.assertFalse(result["ok"])
        self.assertNotIn("nvapi_secret_value", payload)
        self.assertTrue(result["blockers"])

    def test_skill_install_manifest_is_idempotent_and_project_owned(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"HERMES_HOME": tmp}, clear=False):
                dry = install_hermes_skills(dry_run=True)
                first = install_hermes_skills(dry_run=False)
                second = install_hermes_skills(dry_run=False)
            self.assertEqual(dry["manifest"]["count"], 7)
            self.assertEqual(first["manifest"]["manifest_digest"], second["manifest"]["manifest_digest"])
            self.assertTrue(Path(first["manifest"]["installed_manifest_path"]).exists())

    def test_demo_hermes_decisions_fallback_bundle_is_truthful_and_secret_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            market = make_market(Path(tmp) / "market.sqlite3")
            bundle = Path(tmp) / "bundle"
            with mock.patch.dict(os.environ, {"STRIPE_TEST_SECRET_KEY": "sk_test_should_not_leak"}, clear=False):
                result = run_demo_hermes_decisions(market, bundle_dir=bundle)
            payload = (bundle / "hermes-decisions.json").read_text(encoding="utf-8")
            self.assertTrue(result["ok"])
            self.assertFalse(result["real_runtime"])
            self.assertFalse(result["nemotron_real"])
            self.assertIn("NVIDIA_API_KEY", " ".join(result["runtime_truth"]["blockers"]))
            self.assertNotIn("sk_test_should_not_leak", payload)

    def test_role_specific_wrappers_drive_project_and_solver_decisions(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_wrapper = Path(tmp) / "project_wrapper.py"
            solver_wrapper = Path(tmp) / "solver_wrapper.py"
            write_project_wrapper(project_wrapper)
            write_solver_wrapper(solver_wrapper)
            env = {
                HERMES_CLI_ENV: sys.executable,
                HERMES_RUN_ENV: "1",
                HERMES_PROJECT_COMMAND_ENV: f"{sys.executable} {project_wrapper}",
                HERMES_SOLVER_COMMAND_ENV: f"{sys.executable} {solver_wrapper}",
            }
            with mock.patch.dict(os.environ, env, clear=False):
                market = make_market(Path(tmp) / "market.sqlite3")
                setup_demo_project(market)
                project = evaluate_project_agent(
                    market,
                    project_id=DEFAULT_PROJECT_ID,
                    runtime=HermesCliRuntime(),
                    idempotency_key="test:project:hermes-wrapper",
                )
                register_default_solver_profiles(market)
                # The project approval must be published into an open bounty before
                # solver profiles can evaluate it.
                from agent_bounty.github_integration import FakeGitHubClient
                from agent_bounty.project_agent import fund_and_publish_project_agent_decision

                fund_and_publish_project_agent_decision(
                    market,
                    project_id=DEFAULT_PROJECT_ID,
                    github_client=FakeGitHubClient(),
                    repo_full_name="lk251/motoko",
                    idempotency_key="test:project:fund",
                )
                solver = evaluate_solver_agents(
                    market,
                    runtime=HermesSolverAgentRuntime(),
                    idempotency_prefix="test:solver:hermes-wrapper",
                )
            self.assertEqual([row["trusted_verdict"] for row in project["decisions"]].count("approved"), 1)
            by_solver = {row["decision"]["solver_id"]: row for row in solver["evaluations"]}
            self.assertEqual(by_solver["solver_python_terminal_tui"]["trusted_verdict"], "approved")
            self.assertEqual(by_solver["solver_typescript_frontend"]["decision"]["decision"], "decline")
            self.assertEqual(by_solver["solver_cuda_pytorch_perf"]["decision"]["decision"], "decline")


if __name__ == "__main__":
    unittest.main()
