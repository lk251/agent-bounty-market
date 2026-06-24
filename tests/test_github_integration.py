from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_bounty.core import AgentBountyMarket
from agent_bounty.db import connect
from agent_bounty.github_integration import (
    FakeGitHubClient,
    GitHubIntegrationError,
    build_claim_comment,
    build_submission_marker,
    github_publish_bounty_contract,
    github_publish_verification_result,
    parse_contract_from_issue_body,
    process_github_event_row,
    record_github_webhook_delivery,
    sign_github_payload,
)
from agent_bounty.payments import FakePaymentGateway
from agent_bounty.util import stable_json
from agent_bounty.verification import ProtectedVerifierRunner

from tests.helpers import accepted_verifier, bootstrap_bounty


SECRET = "github_webhook_secret"
REPO = "lk251/motoko"


def signed_headers(*, delivery_id: str, event_name: str, payload: dict) -> tuple[bytes, dict[str, str]]:
    body = stable_json(payload).encode("utf-8")
    return body, {
        "X-GitHub-Delivery": delivery_id,
        "X-GitHub-Event": event_name,
        "X-Hub-Signature-256": sign_github_payload(body, SECRET),
    }


def make_github_market(verifier_dir: Path):
    holder = tempfile.TemporaryDirectory()
    conn = connect(Path(holder.name) / "market.sqlite3")
    market = AgentBountyMarket(conn, FakePaymentGateway(), ProtectedVerifierRunner(verifier_dir=verifier_dir, timeout_seconds=5))
    return holder, market


def publish_contract(market: AgentBountyMarket, client: FakeGitHubClient, *, bounty_id: str) -> tuple[int, str, str]:
    result = github_publish_bounty_contract(
        market,
        client=client,
        repo_full_name=REPO,
        bounty_id=bounty_id,
        human_body="Test bounty",
        title="Agent bounty",
        idempotency_key="github:publish:test",
    )
    issue = client.get_issue(REPO, result["issue_number"])
    return int(result["issue_number"]), str(result["contract_digest"]), str(issue["body"])


class GitHubIntegrationTests(unittest.TestCase):
    def test_contract_roundtrip_rejects_duplicates_and_digest_edits(self):
        with tempfile.TemporaryDirectory() as tmp:
            verifier_dir = accepted_verifier(Path(tmp))
            holder, market = make_github_market(verifier_dir)
            self.addCleanup(holder.cleanup)
            _project_id, bounty_id, _solver_id = bootstrap_bounty(market)
            client = FakeGitHubClient()
            _issue_number, digest, body = publish_contract(market, client, bounty_id=bounty_id)

            parsed = parse_contract_from_issue_body(body, expected_digest=digest)
            self.assertEqual(parsed["bounty_id"], bounty_id)
            with self.assertRaises(GitHubIntegrationError):
                parse_contract_from_issue_body(body + body)
            tampered = body.replace('"amount":2500', '"amount":2600')
            with self.assertRaises(GitHubIntegrationError):
                parse_contract_from_issue_body(tampered)

    def test_valid_invalid_and_duplicate_webhook_delivery(self):
        with tempfile.TemporaryDirectory() as tmp:
            verifier_dir = accepted_verifier(Path(tmp))
            holder, market = make_github_market(verifier_dir)
            self.addCleanup(holder.cleanup)
            _project_id, bounty_id, _solver_id = bootstrap_bounty(market)
            client = FakeGitHubClient()
            issue_number, _digest, body = publish_contract(market, client, bounty_id=bounty_id)
            payload = {"action": "edited", "repository": {"full_name": REPO}, "issue": {"number": issue_number, "body": body}}
            raw, headers = signed_headers(delivery_id="delivery-1", event_name="issues", payload=payload)

            recorded = record_github_webhook_delivery(market.conn, payload=raw, headers=headers, endpoint_secret=SECRET, expected_repo_full_name=REPO)
            replay = record_github_webhook_delivery(market.conn, payload=raw, headers=headers, endpoint_secret=SECRET, expected_repo_full_name=REPO)
            self.assertFalse(recorded["replayed"])
            self.assertTrue(replay["replayed"])

            changed_raw, _changed_headers = signed_headers(delivery_id="delivery-1", event_name="issues", payload={**payload, "action": "opened"})
            with self.assertRaises(GitHubIntegrationError):
                record_github_webhook_delivery(market.conn, payload=changed_raw, headers=headers, endpoint_secret=SECRET, expected_repo_full_name=REPO)

            before = market.conn.execute("SELECT COUNT(*) FROM github_webhook_deliveries").fetchone()[0]
            bad_headers = dict(headers)
            bad_headers["X-Hub-Signature-256"] = "sha256:bad"
            with self.assertRaises(GitHubIntegrationError):
                record_github_webhook_delivery(market.conn, payload=raw, headers=bad_headers, endpoint_secret=SECRET, expected_repo_full_name=REPO)
            after = market.conn.execute("SELECT COUNT(*) FROM github_webhook_deliveries").fetchone()[0]
            self.assertEqual(before, after)

    def test_issue_claim_pr_and_result_lifecycle_is_replay_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            verifier_dir = accepted_verifier(Path(tmp))
            holder, market = make_github_market(verifier_dir)
            self.addCleanup(holder.cleanup)
            _project_id, bounty_id, solver_id = bootstrap_bounty(market)
            client = FakeGitHubClient()
            issue_number, digest, body = publish_contract(market, client, bounty_id=bounty_id)

            issue_payload = {"action": "edited", "repository": {"full_name": REPO}, "issue": {"number": issue_number, "body": body}}
            raw, headers = signed_headers(delivery_id="issue-event", event_name="issues", payload=issue_payload)
            record_github_webhook_delivery(market.conn, payload=raw, headers=headers, endpoint_secret=SECRET, expected_repo_full_name=REPO)
            self.assertEqual(process_github_event_row(market, delivery_id="issue-event")["action"], "issue_contract_imported")

            marker = build_submission_marker(
                bounty_id=bounty_id,
                solver_id=solver_id,
                contract_digest_value=digest,
                issue_number=issue_number,
                base_commit="base",
                candidate_commit="candidate",
            )
            pr_payload = {
                "action": "opened",
                "repository": {"full_name": REPO},
                "pull_request": {
                    "number": 7,
                    "body": marker,
                    "state": "open",
                    "draft": True,
                    "base": {"ref": "main", "sha": "base", "repo": {"full_name": REPO}},
                    "head": {"ref": "solver", "sha": "candidate", "repo": {"full_name": REPO}},
                },
            }
            raw, headers = signed_headers(delivery_id="pr-before-claim", event_name="pull_request", payload=pr_payload)
            record_github_webhook_delivery(market.conn, payload=raw, headers=headers, endpoint_secret=SECRET, expected_repo_full_name=REPO)
            self.assertEqual(process_github_event_row(market, delivery_id="pr-before-claim")["action"], "pull_request_recorded_reverification_required")
            self.assertIsNone(market.conn.execute("SELECT id FROM submissions").fetchone())

            claim_body = build_claim_comment(bounty_id=bounty_id, solver_id=solver_id, lease_expires_at="2026-06-30T18:00:00Z", contract_digest_value=digest)
            claim_payload = {
                "action": "created",
                "repository": {"full_name": REPO},
                "issue": {"number": issue_number, "body": body},
                "comment": {"id": 1, "body": claim_body, "user": {"login": solver_id}},
            }
            raw, headers = signed_headers(delivery_id="claim-event", event_name="issue_comment", payload=claim_payload)
            record_github_webhook_delivery(market.conn, payload=raw, headers=headers, endpoint_secret=SECRET, expected_repo_full_name=REPO)
            self.assertEqual(process_github_event_row(market, delivery_id="claim-event")["action"], "claim_recorded")

            raw, headers = signed_headers(delivery_id="pr-after-claim", event_name="pull_request", payload=pr_payload)
            record_github_webhook_delivery(market.conn, payload=raw, headers=headers, endpoint_secret=SECRET, expected_repo_full_name=REPO)
            self.assertEqual(process_github_event_row(market, delivery_id="pr-after-claim", candidate_repo_path="/tmp/candidate")["action"], "submission_recorded")
            submission = market.conn.execute("SELECT id FROM submissions").fetchone()
            verification = market.run_verification(submission_id=submission["id"], idempotency_key="verify:github")
            first = github_publish_verification_result(market, client=client, repo_full_name=REPO, bounty_id=bounty_id, receipt_id=verification["receipt_id"], pr_number=7)
            replay = github_publish_verification_result(market, client=client, repo_full_name=REPO, bounty_id=bounty_id, receipt_id=verification["receipt_id"], pr_number=7)
            self.assertFalse(first["replayed"])
            self.assertTrue(replay["replayed"])
            self.assertEqual(len(client.statuses), 1)

    def test_wrong_solver_stale_sha_and_candidate_ci_do_not_authorize(self):
        with tempfile.TemporaryDirectory() as tmp:
            verifier_dir = accepted_verifier(Path(tmp))
            holder, market = make_github_market(verifier_dir)
            self.addCleanup(holder.cleanup)
            _project_id, bounty_id, solver_id = bootstrap_bounty(market)
            client = FakeGitHubClient()
            issue_number, digest, body = publish_contract(market, client, bounty_id=bounty_id)
            claim = build_claim_comment(bounty_id=bounty_id, solver_id=solver_id, lease_expires_at="2026-06-30T18:00:00Z", contract_digest_value=digest)
            claim_payload = {
                "action": "created",
                "repository": {"full_name": REPO},
                "issue": {"number": issue_number, "body": body},
                "comment": {"id": 1, "body": claim, "user": {"login": solver_id}},
            }
            raw, headers = signed_headers(delivery_id="claim-for-negative-tests", event_name="issue_comment", payload=claim_payload)
            record_github_webhook_delivery(market.conn, payload=raw, headers=headers, endpoint_secret=SECRET, expected_repo_full_name=REPO)
            process_github_event_row(market, delivery_id="claim-for-negative-tests")

            wrong_solver_marker = build_submission_marker(
                bounty_id=bounty_id,
                solver_id="solver_wrong",
                contract_digest_value=digest,
                issue_number=issue_number,
                base_commit="base",
                candidate_commit="candidate",
            )
            wrong_solver_payload = {
                "action": "opened",
                "repository": {"full_name": REPO},
                "pull_request": {
                    "number": 8,
                    "body": wrong_solver_marker,
                    "state": "open",
                    "draft": True,
                    "base": {"ref": "main", "sha": "base", "repo": {"full_name": REPO}},
                    "head": {"ref": "solver", "sha": "candidate", "repo": {"full_name": REPO}},
                },
            }
            raw, headers = signed_headers(delivery_id="wrong-solver-pr", event_name="pull_request", payload=wrong_solver_payload)
            record_github_webhook_delivery(market.conn, payload=raw, headers=headers, endpoint_secret=SECRET, expected_repo_full_name=REPO)
            with self.assertRaises(Exception):
                process_github_event_row(market, delivery_id="wrong-solver-pr")

            stale_marker = build_submission_marker(
                bounty_id=bounty_id,
                solver_id=solver_id,
                contract_digest_value=digest,
                issue_number=issue_number,
                base_commit="base",
                candidate_commit="candidate",
            )
            stale_payload = {
                "action": "opened",
                "repository": {"full_name": REPO},
                "pull_request": {
                    "number": 9,
                    "body": stale_marker,
                    "state": "open",
                    "draft": True,
                    "base": {"ref": "main", "sha": "not-base", "repo": {"full_name": REPO}},
                    "head": {"ref": "solver", "sha": "candidate", "repo": {"full_name": REPO}},
                },
            }
            raw, headers = signed_headers(delivery_id="stale-pr", event_name="pull_request", payload=stale_payload)
            record_github_webhook_delivery(market.conn, payload=raw, headers=headers, endpoint_secret=SECRET, expected_repo_full_name=REPO)
            with self.assertRaises(GitHubIntegrationError):
                process_github_event_row(market, delivery_id="stale-pr")

            status_payload = {"repository": {"full_name": REPO}, "id": 1, "sha": "candidate", "state": "success", "context": "candidate-owned"}
            raw, headers = signed_headers(delivery_id="status-event", event_name="status", payload=status_payload)
            record_github_webhook_delivery(market.conn, payload=raw, headers=headers, endpoint_secret=SECRET, expected_repo_full_name=REPO)
            self.assertEqual(process_github_event_row(market, delivery_id="status-event")["action"], "recorded_non_authoritative_ci_event")
            self.assertIsNone(market.conn.execute("SELECT id FROM verification_receipts").fetchone())

    def test_claim_expiry_allows_explicit_reclaim(self):
        with tempfile.TemporaryDirectory() as tmp:
            verifier_dir = accepted_verifier(Path(tmp))
            holder, market = make_github_market(verifier_dir)
            self.addCleanup(holder.cleanup)
            _project_id, bounty_id, solver_id = bootstrap_bounty(market)
            market.create_solver(solver_id="solver_two", display_name="Second", idempotency_key="beneficiary:two")
            first = market.claim_bounty(bounty_id=bounty_id, solver_id=solver_id, lease_expires_at="2026-06-24T00:00:00Z", idempotency_key="claim:one")
            expired = market.expire_claim(bounty_id=bounty_id, idempotency_key="claim-expire:one")
            second = market.claim_bounty(bounty_id=bounty_id, solver_id="solver_two", lease_expires_at="2026-06-30T18:00:00Z", idempotency_key="claim:two")
            self.assertFalse(first["replayed"])
            self.assertEqual(expired["state"], "open")
            self.assertFalse(second["replayed"])

    def test_restart_processing_preserves_delivery_idempotency(self):
        with tempfile.TemporaryDirectory() as tmp:
            verifier_dir = accepted_verifier(Path(tmp) / "verifier")
            db_path = Path(tmp) / "market.sqlite3"
            market = AgentBountyMarket(connect(db_path), FakePaymentGateway(), ProtectedVerifierRunner(verifier_dir=verifier_dir, timeout_seconds=5))
            _project_id, bounty_id, _solver_id = bootstrap_bounty(market)
            client = FakeGitHubClient()
            issue_number, _digest, body = publish_contract(market, client, bounty_id=bounty_id)
            payload = {"action": "edited", "repository": {"full_name": REPO}, "issue": {"number": issue_number, "body": body}}
            raw, headers = signed_headers(delivery_id="restart-delivery", event_name="issues", payload=payload)
            record_github_webhook_delivery(market.conn, payload=raw, headers=headers, endpoint_secret=SECRET, expected_repo_full_name=REPO)
            market.conn.close()

            reopened = AgentBountyMarket(connect(db_path), FakePaymentGateway(), ProtectedVerifierRunner(verifier_dir=verifier_dir, timeout_seconds=5))
            processed = process_github_event_row(reopened, delivery_id="restart-delivery")
            replay = process_github_event_row(reopened, delivery_id="restart-delivery")
            self.assertEqual(processed["action"], "issue_contract_imported")
            self.assertTrue(replay["replayed"])


if __name__ == "__main__":
    unittest.main()
