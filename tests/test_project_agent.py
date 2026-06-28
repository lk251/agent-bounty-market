from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_bounty.core import AgentBountyMarket
from agent_bounty.db import connect
from agent_bounty.github_integration import FakeGitHubClient
from agent_bounty.ledger import project_available_account, project_reserved_account
from agent_bounty.payments import FakePaymentGateway
from agent_bounty.project_agent import (
    DEFAULT_PROJECT_ID,
    FakeProjectAgentRuntime,
    ProjectAgentError,
    build_project_agent_request,
    default_project_agent_policy,
    evaluate_policy,
    evaluate_project_agent,
    fund_and_publish_project_agent_decision,
    load_candidates,
    load_project_agent_policy,
    load_project_agent_skills,
    parse_project_agent_decision,
    project_agent_status_report,
    run_demo_project_agent_motoko,
    save_project_agent_policy,
    scan_project_candidates,
    setup_demo_project,
)
from agent_bounty.util import sha256_text, stable_json


def make_market(path: Path) -> AgentBountyMarket:
    return AgentBountyMarket(connect(path), FakePaymentGateway())


def valid_decision(candidate_id: str = "candidate_valid") -> dict:
    return {
        "schema": "project-agent-bounty-decision-v1",
        "candidate_id": candidate_id,
        "decision": "fund",
        "issue_class": "bugfix",
        "user_value": {"score": 8, "reason": "valuable"},
        "verifiability": {"score": 8, "verifier_id": "motoko_issue_1_tui_latency_v2", "reason": "verified"},
        "estimated_solver_effort": {"low": 10, "likely": 30, "high": 60, "unit": "minutes"},
        "success_probability": 0.7,
        "recommended_reward_cents": 1000,
        "currency": "USD",
        "acceptance_contract": {
            "title": "Fix thing",
            "issue_ref": "lk251/motoko#1",
            "repo_full_name": "lk251/motoko",
            "base_commit": "base",
            "verifier_id": "motoko_issue_1_tui_latency_v2",
            "acceptance_summary": "protected verifier accepts",
        },
        "unknowns": [],
        "risk_flags": [],
        "evidence_refs": ["demo"],
        "model": "test-model",
        "skill_versions": {},
    }


class FailingGitHubClient(FakeGitHubClient):
    def create_issue(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("simulated GitHub outage")


class MalformedRuntime(FakeProjectAgentRuntime):
    runtime_name = "malformed-runtime"

    def evaluate(self, request, *, timeout_seconds=30.0, max_output_bytes=65_536):  # type: ignore[no-untyped-def]
        from agent_bounty.project_agent import ProjectAgentRuntimeResult

        bad = valid_decision(request["candidates"][0]["candidate_id"])
        bad["extra"] = "not allowed"
        return ProjectAgentRuntimeResult(
            runtime_kind="fake",
            runtime_name=self.runtime_name,
            model="malformed",
            response={"schema": "project-agent-bounty-decision-set-v1", "decisions": [bad]},
            safe_trace={"runtime": self.runtime_name},
        )


class ProjectAgentTests(unittest.TestCase):
    def test_malformed_and_extra_field_model_output_rejected(self):
        with self.assertRaises(ProjectAgentError):
            parse_project_agent_decision("{}")
        extra = valid_decision()
        extra["policy_override"] = {"max_bounty_amount_cents": 999999}
        with self.assertRaises(ProjectAgentError):
            parse_project_agent_decision(extra)

    def test_prompt_injection_and_credentials_do_not_enter_request_or_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            market = make_market(Path(tmp) / "market.sqlite3")
            setup_demo_project(market)
            policy = load_project_agent_policy(market, DEFAULT_PROJECT_ID)
            original_digest = sha256_text(stable_json(policy))
            with mock.patch.dict(
                os.environ,
                {
                    "STRIPE_TEST_SECRET_KEY": "sk_test_secret_should_not_leak",
                    "AGENT_BOUNTY_GITHUB_TOKEN": "ghp_secret_should_not_leak",
                },
                clear=False,
            ):
                request = build_project_agent_request(
                    project_id=DEFAULT_PROJECT_ID,
                    policy=policy,
                    candidates=load_candidates(market, DEFAULT_PROJECT_ID),
                    skills=load_project_agent_skills(),
                )
            request_json = stable_json(request)
            self.assertIn("Ignore policy limits", request_json)
            self.assertNotIn("sk_test_secret_should_not_leak", request_json)
            self.assertNotIn("ghp_secret_should_not_leak", request_json)
            self.assertEqual(original_digest, sha256_text(stable_json(load_project_agent_policy(market, DEFAULT_PROJECT_ID))))

    def test_fake_runtime_selects_one_candidate_and_policy_gates_three(self):
        with tempfile.TemporaryDirectory() as tmp:
            market = make_market(Path(tmp) / "market.sqlite3")
            setup_demo_project(market)
            result = evaluate_project_agent(
                market,
                project_id=DEFAULT_PROJECT_ID,
                runtime=FakeProjectAgentRuntime(),
                idempotency_key="eval:policy-gates",
            )
            verdicts = [row["trusted_verdict"] for row in result["decisions"]]
            self.assertEqual(verdicts.count("approved"), 1)
            self.assertGreaterEqual(len([verdict for verdict in verdicts if verdict != "approved"]), 3)
            overspend = next(row for row in result["decisions"] if "policy-overspend" in row["proposal"]["risk_flags"])
            self.assertEqual(overspend["trusted_verdict"], "declined")
            self.assertIn("estimated funding need is above the project spending cap", overspend["policy_reasons"])

    def test_policy_unallowlisted_missing_verifier_and_human_threshold_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            market = make_market(Path(tmp) / "market.sqlite3")
            market.create_project(project_id=DEFAULT_PROJECT_ID, name="Motoko", currency="USD")
            market.fund_project(project_id=DEFAULT_PROJECT_ID, amount=5000, currency="USD", idempotency_key="fund:policy")
            policy = default_project_agent_policy(
                project_id=DEFAULT_PROJECT_ID,
                max_bounty_amount_cents=3000,
                human_approval_threshold_cents=1000,
            )
            save_project_agent_policy(market, policy)
            candidate = {
                "candidate_id": "candidate_valid",
                "repo_full_name": "lk251/motoko",
                "issue_class": "bugfix",
            }
            proposal = valid_decision()
            proposal["recommended_reward_cents"] = 1500
            self.assertEqual(evaluate_policy(market, policy=policy, candidate=candidate, proposal=proposal)["trusted_verdict"], "needs_human")
            proposal["recommended_reward_cents"] = 1000
            bad_repo = dict(candidate)
            bad_repo["repo_full_name"] = "evil/repo"
            self.assertEqual(evaluate_policy(market, policy=policy, candidate=bad_repo, proposal=proposal)["trusted_verdict"], "declined")
            missing_verifier = valid_decision()
            missing_verifier["verifiability"]["verifier_id"] = None
            missing_verifier["acceptance_contract"]["verifier_id"] = None
            self.assertEqual(evaluate_policy(market, policy=policy, candidate=candidate, proposal=missing_verifier)["trusted_verdict"], "declined")

    def test_valid_motoko_proposal_reserves_and_publishes_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            market = make_market(Path(tmp) / "market.sqlite3")
            result = run_demo_project_agent_motoko(market)
            self.assertTrue(result["ok"])
            self.assertTrue(result["replay"]["replayed"])
            self.assertEqual(market.ledger.balance(project_available_account(DEFAULT_PROJECT_ID), "USD"), 0)
            self.assertEqual(market.ledger.balance(project_reserved_account(DEFAULT_PROJECT_ID), "USD"), 2500)
            self.assertEqual(
                market.conn.execute("SELECT COUNT(*) AS count FROM github_issue_contracts").fetchone()["count"],
                1,
            )

    def test_publication_failure_retains_reserved_funds_without_duplicate_reserve(self):
        with tempfile.TemporaryDirectory() as tmp:
            market = make_market(Path(tmp) / "market.sqlite3")
            setup_demo_project(market)
            evaluate_project_agent(
                market,
                project_id=DEFAULT_PROJECT_ID,
                runtime=FakeProjectAgentRuntime(),
                idempotency_key="eval:publication-failure",
            )
            for _ in range(2):
                with self.assertRaises(RuntimeError):
                    fund_and_publish_project_agent_decision(
                        market,
                        project_id=DEFAULT_PROJECT_ID,
                        github_client=FailingGitHubClient(),
                        repo_full_name="lk251/motoko",
                        idempotency_key="fund:publication-failure",
                    )
            self.assertEqual(market.ledger.balance(project_available_account(DEFAULT_PROJECT_ID), "USD"), 0)
            self.assertEqual(market.ledger.balance(project_reserved_account(DEFAULT_PROJECT_ID), "USD"), 2500)
            count = market.conn.execute(
                "SELECT COUNT(*) AS count FROM ledger_entries WHERE event_type = 'bounty_reserved'"
            ).fetchone()["count"]
            self.assertEqual(count, 1)

    def test_restart_replays_completed_agent_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "market.sqlite3"
            market = make_market(db_path)
            setup_demo_project(market)
            first = evaluate_project_agent(
                market,
                project_id=DEFAULT_PROJECT_ID,
                runtime=FakeProjectAgentRuntime(),
                idempotency_key="eval:restart",
            )
            market.conn.close()
            reopened = make_market(db_path)
            replay = evaluate_project_agent(
                reopened,
                project_id=DEFAULT_PROJECT_ID,
                runtime=FakeProjectAgentRuntime(),
                idempotency_key="eval:restart",
            )
            self.assertFalse(first["replayed"])
            self.assertTrue(replay["replayed"])
            self.assertEqual(len(replay["decisions"]), 4)

    def test_runtime_malformed_response_records_failed_run_and_status_reports_blocker(self):
        with tempfile.TemporaryDirectory() as tmp:
            market = make_market(Path(tmp) / "market.sqlite3")
            setup_demo_project(market)
            with self.assertRaises(ProjectAgentError):
                evaluate_project_agent(
                    market,
                    project_id=DEFAULT_PROJECT_ID,
                    runtime=MalformedRuntime(),
                    idempotency_key="eval:malformed",
                )
            row = market.conn.execute("SELECT status, error FROM project_agent_runs WHERE idempotency_key = 'eval:malformed'").fetchone()
            self.assertEqual(row["status"], "failed")
            self.assertIn("unsupported field", row["error"])
            status = project_agent_status_report()
            self.assertFalse(status["hermes_runtime"]["available"])
            self.assertTrue(status["hermes_runtime"]["blockers"])

    def test_scan_command_primitives_are_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            market = make_market(Path(tmp) / "market.sqlite3")
            market.create_project(project_id=DEFAULT_PROJECT_ID, name="Motoko", currency="USD")
            save_project_agent_policy(market, default_project_agent_policy())
            first = scan_project_candidates(market, project_id=DEFAULT_PROJECT_ID)
            second = scan_project_candidates(market, project_id=DEFAULT_PROJECT_ID)
            self.assertEqual(len(first["candidates"]), 4)
            self.assertEqual(
                sorted(candidate["snapshot_digest"] for candidate in first["candidates"]),
                sorted(candidate["snapshot_digest"] for candidate in second["candidates"]),
            )


if __name__ == "__main__":
    unittest.main()
