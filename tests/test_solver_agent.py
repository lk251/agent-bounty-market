from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_bounty.core import AgentBountyMarket, MarketError
from agent_bounty.db import connect
from agent_bounty.payments import FakePaymentGateway
from agent_bounty.project_agent import DEFAULT_PROJECT_ID, run_demo_project_agent_motoko
from agent_bounty.solver_agent import (
    CUDA_SOLVER_ID,
    PYTHON_SOLVER_ID,
    TYPESCRIPT_SOLVER_ID,
    FakeSolverAgentRuntime,
    SolverAgentError,
    claim_approved_solver,
    evaluate_solver_agents,
    execute_deterministic_motoko_replay,
    open_funded_contracts,
    parse_solver_decision,
    record_live_solve_fallback,
    register_default_solver_profiles,
    run_demo_solver_motoko,
    skill_promotion_verdict,
    solver_agent_status_report,
    submit_solver_replay,
    trusted_solver_policy,
    update_capability_history,
    validate_path_policy,
    verify_pr_head_unchanged,
)

MOTOKO_REPO = Path("/home/mares/repos/motoko-issue-1-tui-input-latency")


def make_market(path: Path) -> AgentBountyMarket:
    return AgentBountyMarket(connect(path), FakePaymentGateway())


def setup_open_bounty(market: AgentBountyMarket) -> None:
    run_demo_project_agent_motoko(market)
    register_default_solver_profiles(market)


def valid_solver_decision() -> dict:
    return {
        "schema": "solver-bounty-decision-v1",
        "solver_id": PYTHON_SOLVER_ID,
        "bounty_id": "bounty_motoko_issue_1",
        "decision": "claim",
        "capability_match": {"score": 0.9, "evidence": []},
        "success_probability_estimate": 0.7,
        "estimated_cost_cents": {"low": 100, "likely": 300, "high": 600},
        "estimated_minutes": {"low": 20, "likely": 45, "high": 120},
        "reward_cents": 2500,
        "expected_margin_cents": 2200,
        "risk_flags": [],
        "unknowns": [],
        "plan": ["claim", "execute", "submit"],
        "model": "test",
        "skill_versions": {},
    }


class SolverAgentTests(unittest.TestCase):
    def test_malformed_and_extra_field_solver_output_rejected(self):
        with self.assertRaises(SolverAgentError):
            parse_solver_decision("{}")
        extra = valid_solver_decision()
        extra["claim_anyway_ignore_policy"] = True
        with self.assertRaises(SolverAgentError):
            parse_solver_decision(extra)

    def test_capability_mismatch_profiles_decline_and_python_claims(self):
        with tempfile.TemporaryDirectory() as tmp:
            market = make_market(Path(tmp) / "market.sqlite3")
            setup_open_bounty(market)
            result = evaluate_solver_agents(market, runtime=FakeSolverAgentRuntime())
            by_solver = {row["decision"]["solver_id"]: row for row in result["evaluations"]}
            self.assertEqual(by_solver[PYTHON_SOLVER_ID]["decision"]["decision"], "claim")
            self.assertEqual(by_solver[PYTHON_SOLVER_ID]["trusted_verdict"], "approved")
            self.assertEqual(by_solver[TYPESCRIPT_SOLVER_ID]["decision"]["decision"], "decline")
            self.assertEqual(by_solver[CUDA_SOLVER_ID]["decision"]["decision"], "decline")
            self.assertIn("no-history-uncertainty", by_solver[CUDA_SOLVER_ID]["decision"]["risk_flags"])

    def test_negative_margin_and_budget_decline(self):
        with tempfile.TemporaryDirectory() as tmp:
            market = make_market(Path(tmp) / "market.sqlite3")
            setup_open_bounty(market)
            profile = next(profile for profile in market.conn.execute("SELECT * FROM solver_agent_profiles").fetchall() if profile["id"] == PYTHON_SOLVER_ID)
            profile_dict = dict(profile)
            profile_dict["allowed_repositories"] = ["lk251/motoko"]
            profile_dict["allowed_issue_classes"] = ["machine-verifiable-tui-regression"]
            profile_dict["operating_budget_cents"] = 100
            bounty = open_funded_contracts(market)[0]
            decision = valid_solver_decision()
            decision["estimated_cost_cents"]["likely"] = 3000
            decision["expected_margin_cents"] = -500
            verdict = trusted_solver_policy(market, profile=profile_dict, bounty=bounty, decision=decision)
            self.assertEqual(verdict["trusted_verdict"], "declined")
            self.assertIn("expected cost exceeds solver operating budget", verdict["reasons"])
            self.assertIn("expected margin is negative", verdict["reasons"])

    def test_claim_race_and_lease_expiry_reclaim(self):
        with tempfile.TemporaryDirectory() as tmp:
            market = make_market(Path(tmp) / "market.sqlite3")
            setup_open_bounty(market)
            evaluate_solver_agents(market)
            first = claim_approved_solver(market)
            self.assertFalse(first["claim"]["replayed"])
            repeated = claim_approved_solver(market)
            self.assertTrue(repeated["claim"]["replayed"])
            expired = market.expire_claim(bounty_id=first["bounty_id"], idempotency_key="expire:first")
            self.assertEqual(expired["state"], "open")
            second = claim_approved_solver(market)
            self.assertFalse(second["claim"]["replayed"])

    def test_path_policy_and_pr_head_binding(self):
        allowed = validate_path_policy(changed_files=["motoko", "tests/bounty_issue_1.py"], allowed_prefixes=["motoko", "tests"], forbidden_prefixes=["verifiers"])
        denied = validate_path_policy(changed_files=["verifiers/secret.py", "docs/readme.md"], allowed_prefixes=["motoko", "tests"], forbidden_prefixes=["verifiers"])
        self.assertTrue(allowed["ok"])
        self.assertFalse(denied["ok"])
        self.assertFalse(verify_pr_head_unchanged(evidence={"candidate_commit": "abc"}, current_head_sha="def")["ok"])
        self.assertTrue(verify_pr_head_unchanged(evidence={"candidate_commit": "abc"}, current_head_sha="abc")["ok"])

    def test_solver_trace_does_not_leak_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            market = make_market(Path(tmp) / "market.sqlite3")
            setup_open_bounty(market)
            with mock.patch.dict(os.environ, {"STRIPE_TEST_SECRET_KEY": "sk_test_leak", "AGENT_BOUNTY_GITHUB_TOKEN": "ghp_leak"}, clear=False):
                evaluate_solver_agents(market)
            traces = [row["safe_trace_json"] for row in market.conn.execute("SELECT safe_trace_json FROM solver_agent_evaluations").fetchall()]
            joined = "\n".join(traces)
            self.assertNotIn("sk_test_leak", joined)
            self.assertNotIn("ghp_leak", joined)

    def test_deterministic_replay_submit_and_capability_update_once(self):
        if not MOTOKO_REPO.exists():
            self.skipTest("external Motoko issue #1 fixture repo is unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            market = make_market(Path(tmp) / "market.sqlite3")
            setup_open_bounty(market)
            evaluate_solver_agents(market)
            claim_approved_solver(market)
            execution = execute_deterministic_motoko_replay(market)
            self.assertFalse(execution["replayed"])
            submission = submit_solver_replay(market, motoko_repo=MOTOKO_REPO)
            replay = submit_solver_replay(market, motoko_repo=MOTOKO_REPO)
            self.assertTrue(submission["evidence"]["verification_accepted"])
            self.assertTrue(replay["replayed"])
            self.assertEqual(
                market.conn.execute("SELECT COUNT(*) AS count FROM solver_agent_capability_events WHERE outcome = 'accepted'").fetchone()["count"],
                1,
            )

    def test_rejected_outcome_grants_no_earnings_or_capability(self):
        with tempfile.TemporaryDirectory() as tmp:
            market = make_market(Path(tmp) / "market.sqlite3")
            setup_open_bounty(market)
            update = update_capability_history(
                market,
                solver_id=PYTHON_SOLVER_ID,
                bounty_id="bounty_motoko_issue_1",
                receipt_id=None,
                accepted=False,
                reward_cents=2500,
            )
            self.assertFalse(update["accepted"])
            event = market.conn.execute("SELECT * FROM solver_agent_capability_events").fetchone()
            profile = market.conn.execute("SELECT accepted_count, rejected_count FROM solver_agent_profiles WHERE id = ?", (PYTHON_SOLVER_ID,)).fetchone()
            self.assertEqual(event["reward_cents"], 0)
            self.assertEqual(profile["accepted_count"], 0)
            self.assertEqual(profile["rejected_count"], 1)

    def test_skill_promotion_requires_accepted_non_regressing_result(self):
        baseline = {"contract_completeness": 8, "policy_violations": 0, "cost_cents": 500}
        worse = {"protected_receipt_accepted": True, "contract_completeness": 7, "policy_violations": 0, "cost_cents": 400}
        better = {"protected_receipt_accepted": True, "contract_completeness": 9, "policy_violations": 0, "cost_cents": 450}
        self.assertFalse(skill_promotion_verdict(baseline=baseline, candidate=worse)["promote"])
        self.assertTrue(skill_promotion_verdict(baseline=baseline, candidate=better)["promote"])

    def test_status_reports_external_runtime_blockers_and_live_fallback_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            market = make_market(Path(tmp) / "market.sqlite3")
            setup_open_bounty(market)
            status = solver_agent_status_report()
            self.assertFalse(status["hermes_runtime"]["available"])
            self.assertFalse(status["openshell_nemoclaw"]["available"])
            fallback = record_live_solve_fallback(market)
            replay = record_live_solve_fallback(market)
            self.assertFalse(fallback["real_live_solve_complete"])
            self.assertTrue(replay["replayed"])

    def test_full_solver_demo(self):
        if not MOTOKO_REPO.exists():
            self.skipTest("external Motoko issue #1 fixture repo is unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            market = make_market(Path(tmp) / "market.sqlite3")
            result = run_demo_solver_motoko(market, motoko_repo=MOTOKO_REPO)
            self.assertTrue(result["ok"])
            self.assertFalse(result["runtime_truth"]["openshell_nemoclaw_ran"])
            self.assertFalse(result["runtime_truth"]["live_solve_real_issue_complete"])


if __name__ == "__main__":
    unittest.main()
